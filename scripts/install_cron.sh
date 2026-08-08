#!/usr/bin/env bash
#
# Installs the cron jobs for backups and the watchdog for the current user.
# Idempotent: existing tg_finder entries are replaced, everything else is kept.
#
#   ./scripts/install_cron.sh              # backup 04:00 daily + watchdog /15m
#   ./scripts/install_cron.sh --no-backup  # watchdog only
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MARKER="# tg_finder"
WITH_BACKUP=1
[ "${1-}" = "--no-backup" ] && WITH_BACKUP=0

current="$(crontab -l 2>/dev/null || true)"
kept="$(printf '%s\n' "$current" | grep -v "$MARKER" || true)"

{
  [ -n "$kept" ] && printf '%s\n' "$kept"
  if [ "$WITH_BACKUP" = 1 ]; then
    echo "0 4 * * * $REPO_ROOT/scripts/backup_db.sh >> $HOME/tg_backup.log 2>&1 $MARKER"
  fi
  echo "*/15 * * * * $REPO_ROOT/scripts/watchdog.sh >> $HOME/tg_watchdog.log 2>&1 $MARKER"
} | crontab -

echo "[cron] installed:"
crontab -l | grep "$MARKER"
