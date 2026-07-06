#!/usr/bin/env sh
set -e

# Apply database migrations before starting the app.
# Safe to run on every boot: alembic upgrade head is idempotent.
echo "[entrypoint] applying database migrations..."
alembic upgrade head

echo "[entrypoint] starting app (APP_MODE=${APP_MODE:-bot})..."
exec python main.py
