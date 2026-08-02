# AGENTS.md

Telegram bot (aiogram 3.x) that answers questions about indexed Telegram channel posts via a
two-step LLM pipeline. `CLAUDE.md` has the full architecture write-up — this file is the
short, verified version; read `CLAUDE.md` before non-trivial changes.

## Commands

Everything runs through the Makefile, which wraps `.venv/bin/*` directly — never `source
.venv/bin/activate`, just use `make` or call `.venv/bin/<tool>`.

- `make check` — lint → typecheck → test. Run this before considering work done.
- Single test: `.venv/bin/python -m pytest tests/test_selector.py -k some_case -q`
- `make local_db_up` / `make local_db_down` — dockerized pgvector Postgres.
- **`make migrate` is broken**: it depends on a nonexistent `local_up` target. Use
  `make local_db_up` then `.venv/bin/alembic upgrade head` instead.
- Indexer CLI: `tg-finder-index add @channel [--full|--limit N] | list | prune [--days N --dry-run]`.

## Testing

- `tests/conftest.py` sets hermetic env vars via `setdefault` **before any `src` import**,
  because `src.config.settings` is a module-level singleton built at import time. New
  required settings must get a conftest default or every test breaks at collection.
- Tests use structural fakes (e.g. `FakeSession`) and need no live Postgres; only CI spins up
  real pgvector + runs Alembic before pytest. mypy has a relaxed override for `tests.*`
  (`arg-type`, `attr-defined`, `call-arg` disabled) — follow the fake pattern, don't fight it.

## Gotchas that bite

- **No vector search exists.** pgvector is provisioned in Docker/CI, but the selector works
  purely on post titles via one JSON-mode LLM call. Don't assume embeddings/similarity search;
  grep first.
- `APP_MODE` unset defaults to `bot` (both `main.py` and `docker-entrypoint.sh`); any other
  non-`scheduler` value runs bot+scheduler. Production splits these into separate services.
- Empty `SELECTOR_MODEL` / `ANSWER_MODEL` fall back to `LLM_MODEL` — this is what makes
  `OPENAI_BASE_URL` proxies without hardcoded model names work.
- Bare `postgresql://` `DATABASE_URL` is auto-normalized to `postgresql+asyncpg://`.
- Indexer invariants (don't break): per-post SAVEPOINT so one bad post can't roll back the
  batch; the channel row is committed before the indexing loop; progress commits every 50 posts.
- The retention APScheduler job registers `next_run_time=now` on purpose — plain interval jobs
  first fire a full interval after start, so a daily job on a frequently redeployed service
  would never run. Keep that when touching `src/scheduler/tasks.py`.
- Style: ruff line-length 100, `E501` ignored, target py312; pytest `asyncio_mode = "auto"`.
- `RESEARCH/` is model-comparison notes, not part of the running system.

## Core flow (30 seconds)

1. Selector (`src/search/selector.py`): all non-empty post titles, freshest-first, truncated
   to `SELECTOR_TOKEN_BUDGET` (tiktoken) → one JSON-mode request returning `post_ids`.
2. Answerer (`src/search/answerer.py`): full content for those ids (albums merged by
   `grouped_id`), capped at `ANSWER_TOKEN_BUDGET` → synthesized answer.
3. Bot handler formats HTML + source links. Sessions are injected per-update by
   `DbSessionMiddleware` (as `db_session` kwarg) — no manual session management in handlers;
   `AuthMiddleware` whitelists via `ALLOWED_USER_IDS` (empty = auth off).
