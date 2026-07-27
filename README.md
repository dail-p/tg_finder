# tg_finder

Telegram bot that answers questions about posts from Telegram channels using a
two-step LLM pipeline: title selection, then full-post answer synthesis.

## Stage 1 (MVP) scope

- Aiogram 3.x bot with auth whitelist (`/start`, `/help`, `/channels`, `/search`).
- Telethon-based channel parser with FloodWait handling.
- Indexer pipeline: full posts (text + media metadata + title/hashtags) → Postgres.
- Search: LLM title selector → load full posts → LLM answer with source links.
- Periodic indexing scheduler (APScheduler, default 15 min).

## Stack

Python 3.12, aiogram 3.x, SQLAlchemy 2.0 async + asyncpg, Alembic,
Telethon, openai (chat), APScheduler, structlog, tiktoken.

## Quick start (local)

1. Copy `.env.example` → `.env` and fill in `BOT_TOKEN`, `ALLOWED_USER_IDS`,
   `TELEGRAM_API_ID` / `TELEGRAM_API_HASH`, `OPENAI_API_KEY`, `DATABASE_URL`.
2. Start Postgres:

   ```bash
   docker compose up -d db
   ```

3. Apply migrations:

   ```bash
   .venv/bin/alembic upgrade head
   ```

4. Add and index a channel (run interactively once to authorize the Telethon user
   session — a `*.session` file is created in the project root):

   ```bash
   .venv/bin/tg-finder-index add @some_channel
   ```

5. Run the bot + scheduler:

   ```bash
   python main.py
   ```

## How search works

1. All non-empty post titles (plus channel, date, hashtags) are sent to
   `SELECTOR_MODEL` in one request, truncated to `SELECTOR_TOKEN_BUDGET`
   (freshest first). The model returns relevant post ids as JSON.
2. Full posts for those ids are loaded, album media is merged by `grouped_id`,
   and the context (up to `ANSWER_TOKEN_BUDGET`) goes to `ANSWER_MODEL`.
3. The bot formats the answer in HTML and appends source links with titles
   and a photo count mark when present.

Empty `SELECTOR_MODEL` / `ANSWER_MODEL` fall back to `LLM_MODEL`.

## Retention (automatic cleanup)

Posts older than `POST_RETENTION_DAYS` (default 180 — half a year) are deleted
by a scheduler job that runs at startup and then every
`RETENTION_INTERVAL_HOURS` (default 24). Deletion goes by `posted_at`, falling
back to `indexed_at` when the post has no date, and happens in batches of 5000.
Set `POST_RETENTION_DAYS=0` to disable cleanup entirely.

Pruning doesn't affect incremental indexing: that tracks
`Channel.last_indexed_message_id`, so deleted posts are never re-fetched.

## Run modes

`APP_MODE=bot` — only the polling bot.
`APP_MODE=scheduler` — only the periodic indexer (and retention cleanup).
`APP_MODE=both` (default) — bot + scheduler in one process.

## CLI

```bash
tg-finder-index add @channel              # add + index a channel
tg-finder-index add @channel --full       # re-index from scratch
tg-finder-index add @channel --limit 100  # only the 100 most recent posts
tg-finder-index list                      # list indexed channels
tg-finder-index prune                     # delete posts older than the window
tg-finder-index prune --days 90 --dry-run # preview a different window
```

## Production deployment (Railway)

The bot is a long-running polling service, so it needs an always-on host plus a
managed Postgres. Railway covers both.

### 1. One-time: generate the Telethon session string

Production has no interactive terminal, so authorize the *user* session locally
once and store the result as a secret:

```bash
python scripts/gen_session.py   # enter phone + code (+ 2FA) when prompted
```

Copy the printed value into `TELEGRAM_SESSION_STRING`.

### 2. Create the Railway project

1. New Project → **Deploy from GitHub repo**, select this repo. Railway uses
   `railway.json` / `Dockerfile` automatically.
2. Add a **PostgreSQL** service.
3. Set variables on the app service:
   - `BOT_TOKEN`, `ALLOWED_USER_IDS`
   - `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION_STRING`
   - `OPENAI_API_KEY` (+ `OPENAI_BASE_URL` if using a proxy)
   - `DATABASE_URL` — reference the Postgres plugin
     (`postgresql+asyncpg://...`; a plain `postgresql://` URL is auto-normalized)
   - Optional: `SELECTOR_MODEL`, `ANSWER_MODEL`
   - `ENVIRONMENT=prod`, `LOG_LEVEL=INFO`, `APP_MODE=bot`

Migrations run automatically on every boot via `docker-entrypoint.sh`
(`alembic upgrade head`).

### 3. (Recommended) split bot and scheduler

Run indexing in a separate service so an indexer crash never stops the bot:

- Service **bot**: `APP_MODE=bot`
- Service **scheduler**: `APP_MODE=scheduler`

Both deploy from the same repo/image; only `APP_MODE` differs. For a minimal
setup a single service with `APP_MODE=both` also works.

### 4. Seed channels

Channels are added via the CLI. Run it once from the Railway shell (or locally
against the prod `DATABASE_URL`):

```bash
tg-finder-index add @some_channel
```

Pushes to `main` trigger the CI (`.github/workflows/ci.yml`); Railway
auto-deploys on push once GitHub is connected.

### Local prod-like run

```bash
docker compose up --build   # db + bot + scheduler, migrations auto-applied
```

## Project layout

```
src/
  bot/        aiogram app, routers, middlewares (auth, db session)
  db/         SQLAlchemy models, async session
  parser/     Telethon client, title/hashtag extract, history iterator
  indexer/    indexing pipeline + CLI (full posts, no embeddings)
  scheduler/  APScheduler periodic indexing
  search/     title selector, post answerer, shared LLM client
  prompts/    LLM prompt templates (select + answer)
alembic/      migrations (initial schema)
```
