#!/usr/bin/env bash
# Patroni callback — met à jour postgres-primary.home.lan dans Pi-hole/dnsmasq
# quand ce nœud devient master (LOT 20).
#
# Variables Pi-hole API attendues (à renseigner dans /etc/patroni/.env) :
#   PIHOLE_HOST=pihole.home.lan
#   PIHOLE_API_KEY=<token>
#
# Fallback SSH (si pas d'API Pi-hole) :
#   PIHOLE_SSH_HOST=root@pihole.home.lan
#   PIHOLE_DNSMASQ_FILE=/etc/dnsmasq.d/harpocrate.conf

set -euo pipefail

EVENT="${1:-}"
ROLE="${2:-}"
NAME="${3:-}"

logger -t patroni-callback "event=${EVENT} role=${ROLE} name=${NAME}"

if [ "$ROLE" != "master" ]; then
    exit 0  # Rien à faire — seul le passage en master déclenche la maj DNS
fi

MY_IP="$(hostname -I | awk '{print $1}')"
DOMAIN="postgres-primary.home.lan"

if [ -n "${PIHOLE_API_KEY:-}" ] && [ -n "${PIHOLE_HOST:-}" ]; then
    # API Pi-hole v6
    curl -fsS -X PATCH "http://${PIHOLE_HOST}/api/customdns" \
         -H "Authorization: Bearer ${PIHOLE_API_KEY}" \
         -H "Content-Type: application/json" \
         -d "{\"domain\":\"${DOMAIN}\",\"ip\":\"${MY_IP}\"}" \
        || logger -t patroni-callback "ERROR: pihole API update failed"
elif [ -n "${PIHOLE_SSH_HOST:-}" ] && [ -n "${PIHOLE_DNSMASQ_FILE:-}" ]; then
    # Fallback SSH : sed dans le fichier dnsmasq + reload
    ssh "${PIHOLE_SSH_HOST}" \
        "sed -i 's|address=/${DOMAIN}/.*|address=/${DOMAIN}/${MY_IP}|' '${PIHOLE_DNSMASQ_FILE}' && pkill -SIGHUP dnsmasq" \
        || logger -t patroni-callback "ERROR: pihole SSH update failed"
else
    logger -t patroni-callback "WARN: aucun mode Pi-hole configuré, DNS non mis à jour"
fi

logger -t patroni-callback "promoted to master, ${DOMAIN} -> ${MY_IP}"
