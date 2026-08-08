#!/usr/bin/env bash
#
# One-time VPS preparation for tg_finder: deploy user, SSH hardening, firewall,
# swap, Docker. Debian 12 / Ubuntu 22.04+ only (apt + systemd + `sudo` group).
#
# Run as root on a fresh machine:
#   ssh root@<ip>
#   curl -fsSL https://raw.githubusercontent.com/dail-p/tg_finder/main/scripts/vps_bootstrap.sh -o bootstrap.sh
#   bash bootstrap.sh
#
# Idempotent: safe to re-run. Environment overrides:
#   DEPLOY_USER=deploy   SWAP_SIZE=2G   SKIP_SSH_HARDENING=1
set -euo pipefail

DEPLOY_USER="${DEPLOY_USER:-deploy}"
SWAP_SIZE="${SWAP_SIZE:-2G}"
SSHD_DROPIN=/etc/ssh/sshd_config.d/99-tg-finder.conf

log() { printf '\n[bootstrap] %s\n' "$*"; }
die() { printf '\n[bootstrap] ERROR: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run as root"
command -v apt-get >/dev/null || die "expected a Debian/Ubuntu host"

log "installing base packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl git ufw unattended-upgrades

# Installing the package is not enough on Debian — the periodic jobs must be
# switched on explicitly.
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF

# --- deploy user ---------------------------------------------------------------
if id -u "$DEPLOY_USER" >/dev/null 2>&1; then
  log "user $DEPLOY_USER already exists"
else
  log "creating user $DEPLOY_USER"
  adduser --disabled-password --gecos "" "$DEPLOY_USER"
fi
usermod -aG sudo "$DEPLOY_USER"

USER_HOME="$(getent passwd "$DEPLOY_USER" | cut -d: -f6)"
USER_KEYS="$USER_HOME/.ssh/authorized_keys"

if [ ! -s "$USER_KEYS" ]; then
  [ -s /root/.ssh/authorized_keys ] \
    || die "no SSH keys found in /root/.ssh/authorized_keys and none for $DEPLOY_USER.
Add a key first — hardening SSH without one locks you out of the server."
  log "copying root SSH keys to $DEPLOY_USER"
  install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$USER_HOME/.ssh"
  install -m 600 -o "$DEPLOY_USER" -g "$DEPLOY_USER" \
    /root/.ssh/authorized_keys "$USER_KEYS"
fi

# Passwordless sudo keeps the deploy scripts non-interactive.
echo "$DEPLOY_USER ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/90-$DEPLOY_USER"
chmod 440 "/etc/sudoers.d/90-$DEPLOY_USER"

# --- SSH hardening ------------------------------------------------------------
if [ "${SKIP_SSH_HARDENING:-0}" = "1" ]; then
  log "skipping SSH hardening (SKIP_SSH_HARDENING=1)"
else
  log "disabling root login and password auth"
  mkdir -p /etc/ssh/sshd_config.d
  cat > "$SSHD_DROPIN" <<'EOF'
# Managed by scripts/vps_bootstrap.sh
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
EOF
  # Never restart on a config sshd itself rejects.
  sshd -t || { rm -f "$SSHD_DROPIN"; die "sshd rejected the config, reverted"; }
  systemctl restart ssh 2>/dev/null || systemctl restart sshd
fi

# --- firewall -----------------------------------------------------------------
SSH_PORT="$(sshd -T 2>/dev/null | awk '/^port /{print $2; exit}')"
SSH_PORT="${SSH_PORT:-22}"
log "configuring ufw (inbound closed except SSH on $SSH_PORT)"
ufw default deny incoming
ufw default allow outgoing
ufw allow "$SSH_PORT/tcp"
ufw --force enable

# --- swap ---------------------------------------------------------------------
if [ "$(swapon --show --noheadings | wc -l)" -gt 0 ]; then
  log "swap already active"
else
  log "creating ${SWAP_SIZE} swapfile (protects Postgres from OOM during builds)"
  # fallocate fails on some filesystems (btrfs), hence the dd fallback. It needs
  # the size in MB, so SWAP_SIZE has to be a whole number of gigabytes.
  case "$SWAP_SIZE" in
    *[0-9]G) swap_mb=$(( ${SWAP_SIZE%G} * 1024 )) ;;
    *) die "SWAP_SIZE must look like '2G', got '$SWAP_SIZE'" ;;
  esac
  fallocate -l "$SWAP_SIZE" /swapfile \
    || dd if=/dev/zero of=/swapfile bs=1M count="$swap_mb" status=none
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# --- docker -------------------------------------------------------------------
if command -v docker >/dev/null 2>&1; then
  log "docker already installed: $(docker --version)"
else
  log "installing docker"
  curl -fsSL https://get.docker.com | sh
fi
docker compose version >/dev/null 2>&1 || die "docker compose v2 plugin missing"
usermod -aG docker "$DEPLOY_USER"
# Brings containers back after a reboot together with their restart policies.
systemctl enable --now docker

cat <<EOF

[bootstrap] done.

Next:
  1. ssh $DEPLOY_USER@<ip>
  2. git clone https://github.com/dail-p/tg_finder.git && cd tg_finder
  3. cp .env.example .env && nano .env && chmod 600 .env
  4. ./scripts/deploy.sh

Root login and password auth are off. Keep this session open until you have
confirmed that '$DEPLOY_USER' can log in and run 'docker ps'.
EOF
