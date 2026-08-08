# tg_finder

Telegram bot that answers questions about posts from Telegram channels using a
two-step LLM pipeline: title selection, then full-post answer synthesis.

## Stage 1 (MVP) scope

- Aiogram 3.x bot with auth whitelist (`/start`, `/help`, `/folders`, `/search`).
- Personal channel folders with add, incremental refresh, removal, and folder-scoped search.
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

4. Run interactively once to authorize the Telethon user session. A `*.session`
   file is created in the project root:

   ```bash
   .venv/bin/tg-finder-index add @some_channel
   ```

5. Run the bot + scheduler:

   ```bash
   python main.py
   ```

6. Open `/folders` in the bot, create a folder, and add channels by `@username`,
   `t.me/channel` link, or a forwarded channel post. Adding a channel starts the
   initial indexing immediately.

## Bot usage

- `/folders` is the only channel-management entry point. It creates, renames,
  and deletes personal folders.
- Open a folder to add channels or search only within that folder.
- Open a channel card to index new posts immediately or remove the channel from
  that folder. Removing the last channel also removes the empty folder.
- `/search <question>` searches the union of channels in all folders owned by
  the current user. Channels that only belong to other users are excluded.
- Shared channel rows and posts are deduplicated internally. Removing a channel
  from one user's folder never removes it from another user's folders.
- The scheduler refreshes only channels that still belong to at least one folder.

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

## Production deployment (VPS)

The bot is a long-running polling service with no inbound traffic: no domain,
DNS, reverse proxy or TLS is involved. A single VPS running `docker compose`
(`db` + `migrate` + `bot` + `scheduler`) is the whole deployment.

Migration steps and the rollback path are in
[docs/setup/vps-migration.md](docs/setup/vps-migration.md) (Russian).

### 1. One-time: generate the Telethon session string

Production has no interactive terminal, so authorize the *user* session locally
once and store the result as a secret:

```bash
python scripts/gen_session.py   # enter phone + code (+ 2FA) when prompted
```

Copy the printed value into `TELEGRAM_SESSION_STRING`.

### 2. Prepare the server

Debian 12 / Ubuntu 22.04+, 2 vCPU / 4 GB RAM / 40 GB SSD. As root:

```bash
curl -fsSL https://raw.githubusercontent.com/dail-p/tg_finder/main/scripts/vps_bootstrap.sh -o bootstrap.sh
bash bootstrap.sh   # deploy user, SSH hardening, ufw, swap, Docker
```

The script refuses to run without an SSH key in `/root/.ssh/authorized_keys` —
disabling password auth without one locks you out.

### 3. Deploy

```bash
ssh deploy@<ip>
git clone https://github.com/dail-p/tg_finder.git && cd tg_finder
cp .env.example .env && nano .env && chmod 600 .env
./scripts/deploy.sh
```

`deploy.sh` validates `.env`, pulls, builds, runs migrations, starts the
services and exits non-zero if any of them is not running.

The `migrate` service owns `alembic upgrade head`; `bot` and `scheduler` wait
for it via `condition: service_completed_successfully` and run with
`RUN_MIGRATIONS=0`, so two containers can never race on the same migration.
A failed migration leaves the previous version running.

### 4. Backups and alerts

```bash
./scripts/install_cron.sh   # pg_dump daily at 04:00 + watchdog every 15 min
```

`scripts/backup_db.sh` writes rotated `pg_dump -Fc` archives (and uploads them
via rclone if `BACKUP_REMOTE` is set). `scripts/watchdog.sh` reports a stopped
container, a restart loop or a filling disk to Telegram using the bot's token.

### 5. Add channels

Open `/folders` in the deployed bot, create a folder, and add channels there.
The bot indexes each newly added channel immediately; the scheduler handles
subsequent periodic updates. The CLI remains available for maintenance.

Pushes to `main` trigger the CI (`.github/workflows/ci.yml`). Deployment is
manual: `./scripts/deploy.sh` on the server.

### Local prod-like run

```bash
docker compose up --build   # db + bot + scheduler, migrations auto-applied
```

Postgres is published on `127.0.0.1:5432` only — a public bind would bypass
`ufw`, since Docker writes its own iptables rules. Reach it from a laptop with
`ssh -L 5432:127.0.0.1:5432 deploy@<ip>`.

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
scripts/      session generator + VPS ops (bootstrap, deploy, backup, watchdog)
```
