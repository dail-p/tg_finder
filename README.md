# tg_finder

Telegram bot that performs semantic search (RAG) across posts of Telegram channels and
answers questions using an LLM grounded in the retrieved content.

## Stage 1 (MVP) scope

- Aiogram 3.x bot with auth whitelist (`/start`, `/help`, `/channels`, `/search`).
- Telethon-based channel parser with FloodWait handling.
- Indexer pipeline: posts → token-bounded overlapping chunks → OpenAI embeddings → pgvector.
- RAG search: pgvector cosine ANN retrieval → LLM synthesis → answer with source links.
- Periodic indexing scheduler (APScheduler, default 15 min).

## Stack

Python 3.12, aiogram 3.x, SQLAlchemy 2.0 async + asyncpg, pgvector, Alembic,
Telethon, openai (embeddings + chat), APScheduler, structlog, tiktoken.

## Quick start (local)

1. Copy `.env.example` → `.env` and fill in `BOT_TOKEN`, `ALLOWED_USER_IDS`,
   `TELEGRAM_API_ID` / `TELEGRAM_API_HASH`, `OPENAI_API_KEY`, `DATABASE_URL`.
2. Start Postgres with pgvector:

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

## Run modes

`APP_MODE=bot` — only the polling bot.
`APP_MODE=scheduler` — only the periodic indexer.
`APP_MODE=both` (default) — bot + scheduler in one process.

## CLI

```bash
tg-finder-index add @channel        # add + index a channel
tg-finder-index add @channel --full # re-index from scratch
tg-finder-index list                # list indexed channels
```

## Production deployment (Railway)

The bot is a long-running polling service, so it needs an always-on host plus a
managed Postgres with the `pgvector` extension. Railway covers both.

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
2. Add a **PostgreSQL** service, then enable pgvector once (Railway shell / psql):
   `CREATE EXTENSION IF NOT EXISTS vector;` (the migration also runs it).
3. Set variables on the app service:
   - `BOT_TOKEN`, `ALLOWED_USER_IDS`
   - `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION_STRING`
   - `OPENAI_API_KEY` (+ `OPENAI_BASE_URL` if using a proxy)
   - `DATABASE_URL` — reference the Postgres plugin
     (`postgresql+asyncpg://...`; a plain `postgresql://` URL is auto-normalized)
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
  db/         SQLAlchemy models, async session, pgvector usage
  parser/     Telethon client + channel history iterator
  indexer/    chunker, embeddings client, indexing pipeline, CLI
  scheduler/  APScheduler periodic indexing
  search/     retriever (pgvector), RAG answerer, confidence levels
  prompts/    LLM prompt templates
alembic/      migrations (initial schema + pgvector extension)
```
