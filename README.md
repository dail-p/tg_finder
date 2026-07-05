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
