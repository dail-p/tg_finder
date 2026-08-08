# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`tg_finder` is a Telegram bot (aiogram 3.x) that answers questions about posts from indexed
Telegram channels using a two-step LLM pipeline: title selection, then full-post answer
synthesis. A Telethon "user" session parses channels; posts are stored in Postgres and indexed
periodically by an APScheduler job.

## Commands

All commands run through the Makefile, which wraps `.venv` binaries directly (no `source
.venv/bin/activate` needed):

```bash
make install       # pip install -e ".[dev]"
make test          # pytest -q
make test-cov      # pytest --cov=src --cov-report=term-missing
make lint          # ruff check .
make lint-fix      # ruff check --fix .
make typecheck     # mypy src tests
make check         # lint + typecheck + test (run this before considering work done)
make local_db_up   # docker compose up db, wait for it, ensure `vector` extension exists
make local_db_down # docker compose down
make migrate       # local_db_up + alembic upgrade head
```

Run a single test: `.venv/bin/python -m pytest tests/test_selector.py -k some_case -q`

`tests/conftest.py` sets hermetic env vars (`DATABASE_URL`, `BOT_TOKEN`, etc.) via
`setdefault` *before* any `src` import, because `src.config.settings` is a module-level
singleton constructed at import time. Tests generally don't need a live Postgres — CI is
the exception (see below) and spins up a real `pgvector/pgvector` container and runs
Alembic migrations before pytest.

CLI for indexing (installed as a console script, `tg-finder-index = src.indexer.cli:main`):

```bash
tg-finder-index add @channel              # add + incrementally index a channel
tg-finder-index add @channel --full       # re-index from scratch
tg-finder-index add @channel --limit 100  # only the 100 most recent posts
tg-finder-index list                      # list indexed channels
tg-finder-index prune                     # delete posts past the retention window
tg-finder-index prune --days 90 --dry-run # preview with a custom window
```

Generate a Telethon session string for prod (interactive prompt for phone/code/2FA):
`python scripts/gen_session.py`

## Architecture

### Two-step LLM search (the core design)

1. **Selector step** (`src/search/selector.py`, `TitleSelector`): loads non-empty post
   titles (+ channel, date, hashtags) from the current user's folders, orders freshest-first,
   truncates to fit `SELECTOR_TOKEN_BUDGET` using tiktoken, and sends the whole list to
   `SELECTOR_MODEL` in one JSON-mode request. The model returns a JSON object of relevant
   `post_ids`.
2. **Answer step** (`src/search/answerer.py`): loads full post content for those ids, merges
   album media by `grouped_id`, and sends the context (capped at `ANSWER_TOKEN_BUDGET`) to
   `ANSWER_MODEL` for a synthesized answer.
3. The bot (`src/bot/handlers/search.py`) formats the answer as HTML and appends source links
   with titles and a photo-count marker where relevant.

Empty `SELECTOR_MODEL` / `ANSWER_MODEL` settings fall back to `LLM_MODEL`
(`settings.selector_model_name` / `settings.answer_model_name` in `src/config.py`). This lets
`OPENAI_BASE_URL` point at a proxy without a hardcoded model name.

There is no embeddings/vector search in the current pipeline — despite `pgvector` being
provisioned in Docker/CI, the selector works purely on titles via LLM. Don't assume vector
similarity search exists; grep before relying on it.

### Indexing pipeline

`src/indexer/pipeline.py` (`index_channel`) is incremental by default: it tracks
`Channel.last_indexed_message_id` and only parses newer messages via `TelethonParser.iter_posts`
(handles Telegram FloodWait). Each post is inserted inside a `session.begin_nested()`
SAVEPOINT so one bad post can't roll back the whole batch or the channel row; the channel row
itself is committed before the indexing loop starts so a mid-run crash never orphans posts via
a dangling FK. Progress commits happen every 50 created posts. `src/scheduler/tasks.py` runs
`index_all_channels` for channels assigned to at least one folder on a periodic APScheduler job
(`INDEXER_INTERVAL_MINUTES`, default 15).

### Retention

`src/indexer/retention.py` (`prune_old_posts`) deletes posts older than
`POST_RETENTION_DAYS` (default 180; `<= 0` disables) using
`COALESCE(posted_at, indexed_at) < cutoff`, in batches of `DELETE_BATCH_SIZE` with a commit
per batch. `build_scheduler` registers it as a second APScheduler job
(`RETENTION_INTERVAL_HOURS`, default 24) with `next_run_time=now` — interval jobs otherwise
first fire a full interval after start, and a daily job on a frequently redeployed service
would never run. Pruning never touches `Channel.last_indexed_message_id`, so deleted posts
are not re-indexed.

### Data model (`src/db/models.py`)

`User` → `ChannelPack` (named groups of channels a user owns) → `PackChannel` (join table) →
`Channel` → `Post`. Posts carry `title`/`hashtags`/`media` extracted at parse time
(`src/parser/extract.py`) plus raw `content`. `grouped_id` links album posts. Uniqueness is
enforced on `(channel_id, telegram_message_id)`. Channels and posts are shared internally,
but `/folders`, folder callbacks, and `/search` are scoped to the current owner.

### Bot wiring (`src/bot/app.py`)

aiogram `Dispatcher` with two middlewares applied globally:
- `AuthMiddleware` — whitelist gate via `ALLOWED_USER_IDS`; when the whitelist is empty,
  auth is disabled (`settings.auth_enabled`).
- `DbSessionMiddleware` — injects a fresh `AsyncSession` per update as `db_session` in
  handler kwargs (no manual session management in handlers).

### Run modes (`main.py`, `APP_MODE` env var)

- `bot` — polling bot only.
- `scheduler` — periodic indexer only.
- `both` (default) — bot + scheduler in one asyncio process/event loop.

In production `bot` and `scheduler` run as separate compose services so an indexer crash never
takes down the bot (see README and `docs/setup/vps-migration.md`). Migrations belong to the
one-shot `migrate` compose service; `docker-entrypoint.sh` still runs `alembic upgrade head`
unless `RUN_MIGRATIONS=0`, which compose sets for bot and scheduler. Host-side ops scripts
(`scripts/deploy.sh`, `backup_db.sh`, `watchdog.sh`) read `.env` through `scripts/_env.sh`
with grep rather than `source`, so secrets are never re-interpreted by the shell.

### Config (`src/config.py`)

Single `pydantic-settings` `Settings` class, cached via `lru_cache` and exposed as the
module-level `settings` singleton. Reads `.env` plus real env vars. A bare `postgresql://`
`DATABASE_URL` is auto-normalized to `postgresql+asyncpg://`.

## Notes for changes

- `mypy` has a relaxed override for `tests.*` (`arg-type`, `attr-defined`, `call-arg` disabled)
  because test fakes (e.g. `FakeSession`) are structurally compatible with SQLAlchemy/openai
  types without inheriting from them — follow that pattern rather than fighting mypy with
  real fixtures.
- Ruff config: line-length 100, `E501` ignored, target py312.
- `RESEARCH/` contains model-comparison notes (unrelated to app code); not part of the running
  system.
