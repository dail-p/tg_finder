#!/usr/bin/env bash
#
# Container and disk watchdog. `restart: unless-stopped` brings a crashed
# container back, but nothing tells you when it is stuck in a restart loop —
# this does, over Telegram, using the bot's own token.
#
#   */15 * * * * /home/deploy/tg_finder/scripts/watchdog.sh >> /var/log/tg_watchdog.log 2>&1
#
# Alert target: ALERT_CHAT_ID from .env, or the first id in ALLOWED_USER_IDS.
# Optional .env settings: DISK_ALERT_PERCENT (default 85),
# RESTART_ALERT_COUNT (default 5).
set -euo pipefail

# shellcheck source=scripts/_env.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_env.sh"

require_env_file

BOT_TOKEN="$(read_env BOT_TOKEN)"
CHAT_ID="$(read_env ALERT_CHAT_ID)"
[ -n "$CHAT_ID" ] || CHAT_ID="$(read_env ALLOWED_USER_IDS | cut -d, -f1 | tr -d ' ')"
DISK_LIMIT="$(read_env DISK_ALERT_PERCENT 85)"
RESTART_LIMIT="$(read_env RESTART_ALERT_COUNT 5)"
STATE_FILE="${XDG_RUNTIME_DIR:-/tmp}/tg_finder_watchdog.state"

problems=()

for svc in db bot scheduler; do
  state="$(service_state "$svc")"
  if [ "$state" != "running" ]; then
    problems+=("$svc is $state")
    continue
  fi
  cid="$(compose ps -aq "$svc" | head -n1)"
  restarts="$(docker inspect -f '{{.RestartCount}}' "$cid")"
  if [ "$restarts" -ge "$RESTART_LIMIT" ]; then
    problems+=("$svc restarted ${restarts}x — likely a crash loop")
  fi
done

disk="$(df -P "$REPO_ROOT" | awk 'NR==2 {print $5}' | tr -d '%')"
if [ "$disk" -ge "$DISK_LIMIT" ]; then
  problems+=("disk ${disk}% full (limit ${DISK_LIMIT}%)")
fi

if [ ${#problems[@]} -eq 0 ]; then
  echo "[watchdog] $(date +%FT%T%z) ok"
  rm -f "$STATE_FILE"
  exit 0
fi

message="tg_finder on $(hostname):"
for p in "${problems[@]}"; do
  message+=$'\n- '"$p"
done
echo "[watchdog] $(date +%FT%T%z) $message"

# Cron runs every 15 minutes; alert once per distinct problem set, not per run.
if [ -f "$STATE_FILE" ] && [ "$(cat "$STATE_FILE")" = "$message" ]; then
  echo "[watchdog] same problem as last run, alert suppressed"
  exit 0
fi
printf '%s' "$message" > "$STATE_FILE"

if [ -z "$BOT_TOKEN" ] || [ -z "$CHAT_ID" ]; then
  echo "[watchdog] WARNING: no BOT_TOKEN/chat id, cannot send the alert" >&2
  exit 1
fi

curl -fsS -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
  --data-urlencode "chat_id=${CHAT_ID}" \
  --data-urlencode "text=${message}" >/dev/null \
  && echo "[watchdog] alert sent" \
  || echo "[watchdog] WARNING: failed to send the alert" >&2
