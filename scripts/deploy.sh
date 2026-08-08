#!/usr/bin/env bash
#
# Deploy (or redeploy) tg_finder on the VPS: pull, build, migrate, restart.
#
#   ./scripts/deploy.sh              # git pull + rebuild + up
#   ./scripts/deploy.sh --no-pull    # rebuild from the working tree as-is
#
# Verifies .env before touching containers, and fails if bot or scheduler is
# not running afterwards.
set -euo pipefail

# shellcheck source=scripts/_env.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_env.sh"

PULL=1
[ "${1-}" = "--no-pull" ] && PULL=0

log() { printf '\n[deploy] %s\n' "$*"; }

# --- preflight ----------------------------------------------------------------
require_env_file

perms="$(stat -c '%a' "$ENV_FILE" 2>/dev/null || stat -f '%Lp' "$ENV_FILE")"
if [ "$perms" != "600" ]; then
  log "tightening permissions on .env ($perms -> 600)"
  chmod 600 "$ENV_FILE"
fi

missing=()
for key in BOT_TOKEN TELEGRAM_API_ID TELEGRAM_API_HASH TELEGRAM_SESSION_STRING OPENAI_API_KEY; do
  value="$(read_env "$key")"
  if [ -z "$value" ] || [[ "$value" == *replace_me* ]]; then
    missing+=("$key")
  fi
done
if [ ${#missing[@]} -gt 0 ]; then
  echo "ERROR: .env is incomplete: ${missing[*]}" >&2
  echo "TELEGRAM_SESSION_STRING comes from 'python scripts/gen_session.py'." >&2
  exit 1
fi

[ "$(read_env ALLOWED_USER_IDS)" ] \
  || log "WARNING: ALLOWED_USER_IDS is empty — the bot will answer anyone"
[ "$(read_env POSTGRES_PASSWORD)" != "tg_finder" ] \
  || log "WARNING: POSTGRES_PASSWORD is still the example default"
[ "$(read_env ENVIRONMENT)" = "prod" ] \
  || log "WARNING: ENVIRONMENT is not 'prod'"

# --- deploy -------------------------------------------------------------------
if [ "$PULL" = 1 ]; then
  log "pulling latest main"
  git -C "$REPO_ROOT" pull --ff-only
fi

log "building and starting (migrations run first, via the migrate service)"
compose up -d --build

log "state"
compose ps

failed=()
for svc in db bot scheduler; do
  state="$(service_state "$svc")"
  echo "  $svc: $state"
  [ "$state" = "running" ] || failed+=("$svc:$state")
done

if [ ${#failed[@]} -gt 0 ]; then
  echo >&2
  echo "ERROR: not running: ${failed[*]}" >&2
  compose logs --tail=50 "${failed[@]%%:*}" >&2 || true
  exit 1
fi

log "pruning dangling images"
docker image prune -f >/dev/null

log "recent logs"
compose logs --tail=20 bot scheduler

cat <<EOF

[deploy] done. Follow logs with:
  docker compose logs -f --tail=50 bot scheduler
EOF
