#!/usr/bin/env bash
#
# Shared helpers for the host-side scripts (deploy / backup / watchdog).
# Sourced, not executed.
#
# Values are read with grep instead of `source .env` on purpose: the file holds
# API keys and session strings that would otherwise be re-interpreted by the
# shell (globs, $substitutions, command substitution).

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env}"

# read_env KEY [DEFAULT] — exported variable wins over .env, last assignment in
# the file wins over earlier ones, surrounding quotes are stripped.
read_env() {
  local key="$1" default="${2-}" value=""
  if [ -n "${!key-}" ]; then
    printf '%s' "${!key}"
    return
  fi
  if [ -f "$ENV_FILE" ]; then
    value="$(grep -E "^[[:space:]]*${key}=" "$ENV_FILE" | tail -n1 | cut -d= -f2-)"
    value="${value%$'\r'}"
    value="${value%\"}"; value="${value#\"}"
    value="${value%\'}"; value="${value#\'}"
  fi
  printf '%s' "${value:-$default}"
}

require_env_file() {
  [ -f "$ENV_FILE" ] || {
    echo "ERROR: $ENV_FILE not found. Copy .env.example and fill it in." >&2
    exit 1
  }
}

# Explicit -f so the scripts work from cron, where cwd is not the repo.
# Compose derives both the working directory and the project name
# ("tg_finder") from the compose file's location, matching a manual run.
compose() {
  docker compose -f "$REPO_ROOT/docker-compose.yml" "$@"
}

# service_state SERVICE — docker state (running / restarting / exited) or "missing".
# -a matters: without it `ps -q` hides stopped containers and every crash would
# be reported as "missing".
service_state() {
  local cid
  cid="$(compose ps -aq "$1" 2>/dev/null | head -n1)"
  if [ -z "$cid" ]; then
    echo missing
    return
  fi
  docker inspect -f '{{.State.Status}}' "$cid" 2>/dev/null || echo missing
}
