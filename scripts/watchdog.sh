#!/usr/bin/env bash
# Self-healing watchdog for Bombi On Duty.
#
# Runs from cron on the droplet (installed by deploy_droplet.sh). If the bot
# stops answering its health check — e.g. frozen on a hung Google Sheets call —
# it restarts just the bot's app container. The packaging app is never touched.
#
# Manual test:  bash scripts/watchdog.sh
set -uo pipefail

REPO="/opt/bombi-on-duty"
COMPOSE="docker compose -f ${REPO}/deploy/docker-compose.yml"
LOG="/var/log/bombi-watchdog.log"

# Find the bot's domain (written to deploy/.env by the deploy script).
DOMAIN="$(grep -h '^DOMAIN=' "${REPO}/deploy/.env" "${REPO}/.env" 2>/dev/null | head -1 | cut -d= -f2)"
[ -z "${DOMAIN}" ] && DOMAIN="$(hostname -I 2>/dev/null | awk '{print $1}' | tr '.' '-').nip.io"
URL="https://${DOMAIN}/healthz"

code="$(curl -sk -m 15 -o /dev/null -w '%{http_code}' "${URL}" 2>/dev/null || echo 000)"

if [ "${code}" = "200" ]; then
  exit 0  # healthy
fi

# Two strikes (avoid restarting on a single transient blip): re-check after 10s.
sleep 10
code2="$(curl -sk -m 15 -o /dev/null -w '%{http_code}' "${URL}" 2>/dev/null || echo 000)"
if [ "${code2}" = "200" ]; then
  exit 0
fi

echo "$(date -u '+%Y-%m-%d %H:%M:%S') UTC  unhealthy (${code}/${code2}) -> restarting app" >> "${LOG}"
cd "${REPO}" && ${COMPOSE} restart app >> "${LOG}" 2>&1
