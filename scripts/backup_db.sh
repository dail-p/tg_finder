#!/usr/bin/env bash
#
# Postgres backup for the VPS deployment. Nothing backs the database up once
# Railway is gone, so this is meant to run from cron:
#
#   0 4 * * * /home/deploy/tg_finder/scripts/backup_db.sh >> /var/log/tg_backup.log 2>&1
#
# Optional .env settings: BACKUP_DIR, BACKUP_KEEP_DAYS, BACKUP_REMOTE
# (BACKUP_REMOTE is an rclone destination, e.g. "s3:my-bucket/tg_finder").
set -euo pipefail

# shellcheck source=scripts/_env.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_env.sh"

require_env_file

PG_USER="$(read_env POSTGRES_USER tg_finder)"
PG_DB="$(read_env POSTGRES_DB tg_finder)"
BACKUP_DIR="$(read_env BACKUP_DIR "$HOME/tg_finder_backups")"
KEEP_DAYS="$(read_env BACKUP_KEEP_DAYS 14)"
REMOTE="$(read_env BACKUP_REMOTE)"

target="$BACKUP_DIR/${PG_DB}_$(date +%F_%H%M).dump"
# The dump holds every indexed post: keep it readable by the owner only.
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
umask 077

echo "[backup] $(date +%FT%T%z) dumping $PG_DB -> $target"
# -Fc: custom format, restores with pg_restore and compresses by default.
compose exec -T db pg_dump -U "$PG_USER" --no-owner --no-privileges -Fc "$PG_DB" > "$target"

size="$(wc -c < "$target")"
if [ "$size" -lt 1024 ]; then
  rm -f "$target"
  echo "[backup] ERROR: dump is only ${size}B — treating as failure" >&2
  exit 1
fi
echo "[backup] ok, $(numfmt --to=iec "$size" 2>/dev/null || echo "${size}B")"

if [ -n "$REMOTE" ]; then
  if command -v rclone >/dev/null 2>&1; then
    echo "[backup] uploading to $REMOTE"
    rclone copy "$target" "$REMOTE"
  else
    echo "[backup] WARNING: BACKUP_REMOTE set but rclone is not installed" >&2
  fi
fi

# A backup on the same disk does not survive the VPS dying — hence BACKUP_REMOTE.
echo "[backup] removing dumps older than ${KEEP_DAYS}d"
find "$BACKUP_DIR" -name "${PG_DB}_*.dump" -type f -mtime "+${KEEP_DAYS}" -delete
