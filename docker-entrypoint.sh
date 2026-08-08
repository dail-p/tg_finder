#!/usr/bin/env sh
set -e

# Apply database migrations before starting the app.
# Safe to run on every boot: alembic upgrade head is idempotent.
#
# RUN_MIGRATIONS=0 skips this step. Compose sets it for bot and scheduler,
# where the dedicated one-shot `migrate` service owns alembic_version instead.
if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  echo "[entrypoint] applying database migrations..."
  alembic upgrade head
else
  echo "[entrypoint] skipping migrations (RUN_MIGRATIONS=0)"
fi

echo "[entrypoint] starting app (APP_MODE=${APP_MODE:-bot})..."
exec python main.py
