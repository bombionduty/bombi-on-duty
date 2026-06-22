#!/usr/bin/env bash
# =====================================================================
# One-shot deploy for Bombi On Duty on a DigitalOcean Droplet.
# Free HTTPS via Caddy + Let's Encrypt on a nip.io hostname (no domain).
#
# Prereqs (the README/Claude walks you through these):
#   * You are in the cloned repo folder.
#   * A .env file exists here with all your secrets.
#   * Ports 80 and 443 are free on this Droplet.
#
# Run:  bash scripts/deploy_droplet.sh
# =====================================================================
set -euo pipefail

cd "$(dirname "$0")/.."   # repo root

echo "==> Detecting public IP..."
IP="$(curl -s https://api.ipify.org || hostname -I | awk '{print $1}')"
if [[ -z "$IP" ]]; then echo "Could not detect IP"; exit 1; fi
DOMAIN="${IP//./-}.nip.io"
echo "    IP=$IP   DOMAIN=$DOMAIN"

if [[ ! -f .env ]]; then
  echo "ERROR: .env not found. Create it first (Claude gives you the contents)."
  exit 1
fi

# --- upsert key=value into .env ---
set_env() {
  local key="$1" val="$2"
  if grep -q "^${key}=" .env; then
    # use | as sed delimiter since values contain / and :
    sed -i "s|^${key}=.*|${key}=${val}|" .env
  else
    echo "${key}=${val}" >> .env
  fi
}
echo "==> Writing production settings into .env..."
set_env APP_BASE_URL "https://${DOMAIN}"
set_env DOMAIN "${DOMAIN}"
set_env TELEGRAM_MODE "webhook"
set_env TEST_MODE "false"
set_env ENVIRONMENT_NAME "production"
set_env PORT "8000"
export DOMAIN

# --- install Docker if missing ---
if ! command -v docker >/dev/null 2>&1; then
  echo "==> Installing Docker..."
  curl -fsSL https://get.docker.com | sh
fi

# --- add swap if RAM is small (protects against build OOM) ---
if [[ ! -f /swapfile ]] && [[ "$(free -m | awk '/^Mem:/{print $2}')" -lt 1200 ]]; then
  echo "==> Low RAM detected — adding 1GB swap..."
  fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "==> Building and starting containers..."
DOMAIN="$DOMAIN" docker compose -f deploy/docker-compose.yml up -d --build

echo ""
echo "============================================================"
echo " Bombi On Duty is starting."
echo " Your HTTPS URL:  https://${DOMAIN}"
echo " Health check:    https://${DOMAIN}/healthz"
echo ""
echo " Use this Mini App URL in BotFather /newapp (short name: ops):"
echo "   https://${DOMAIN}/static/staff/index.html"
echo "============================================================"
