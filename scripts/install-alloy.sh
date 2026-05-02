#!/bin/bash
###############################################################################
# Script 03 : Installation Grafana Alloy (collecteur logs Docker + journald)
#
# A executer DANS le container LXC (en tant que root).
#
# Detecte automatiquement la presence de Docker :
#   - Si Docker present  -> deploiement via docker-compose (image grafana/alloy)
#   - Si Docker absent   -> installation paquet Debian + service systemd
#
# Variables d'environnement requises :
#   LOKI_URL  - endpoint Loki, ex : http://192.168.10.<IP_LXC116>:3100/loki/api/v1/push
#   HOSTNAME  - identifiant du LXC (label `host`), ex : lxc201
#
# Variables optionnelles :
#   STRICT_CHECKS=1     - echec si Loki injoignable (defaut : 0, juste warning)
#   ALLOY_SRC_DIR=...   - dossier source des fichiers (defaut : /tmp/alloy-agent)
#   ALLOY_DST_DIR=...   - dossier d'installation (defaut : /opt/alloy-agent)
#
# Pre-requis (mode docker) :
#   - ${ALLOY_SRC_DIR}/ contient :
#       * docker-compose.yml
#       * config.alloy
#       * config-journald-only.alloy
#     (copie via : pct push <CTID> LXC/alloy-agent/* ${ALLOY_SRC_DIR}/)
###############################################################################
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
APT_OPTS=(-o Dpkg::Options::=--force-confold -o Dpkg::Options::=--force-confdef)

LOKI_URL="${LOKI_URL:-}"
HOSTNAME_LABEL="${HOSTNAME:-$(hostname)}"
ALLOY_SRC_DIR="${ALLOY_SRC_DIR:-/tmp/alloy-agent}"
ALLOY_DST_DIR="${ALLOY_DST_DIR:-/opt/alloy-agent}"
STRICT_CHECKS="${STRICT_CHECKS:-0}"

echo "==========================================="
echo "  Installation Grafana Alloy"
echo "==========================================="
echo "  HOSTNAME     : ${HOSTNAME_LABEL}"
echo "  LOKI_URL     : ${LOKI_URL}"
echo "  Source dir   : ${ALLOY_SRC_DIR}"
echo "  Target dir   : ${ALLOY_DST_DIR}"
echo "  Strict mode  : ${STRICT_CHECKS}"
echo ""

if [ -z "${LOKI_URL}" ]; then
    echo "ERREUR : LOKI_URL doit etre defini."
    exit 1
fi

if [ "$(id -u)" -ne 0 ]; then
    echo "ERREUR : Ce script doit etre execute en tant que root."
    exit 1
fi

if [ ! -d "${ALLOY_SRC_DIR}" ]; then
    echo "ERREUR : Source dir ${ALLOY_SRC_DIR} introuvable."
    echo "         Copier LXC/alloy-agent/* dans ${ALLOY_SRC_DIR} avant d'executer."
    exit 1
fi

# ── Test connectivite Loki (warning ou error selon STRICT_CHECKS) ────────────
echo "  Test de connectivite vers Loki..."
# Extraire host:port depuis l'URL Loki (format : http://host:port/...)
LOKI_HOST=$(echo "${LOKI_URL}" | sed -E 's|^https?://([^:/]+).*|\1|')
LOKI_PORT=$(echo "${LOKI_URL}" | sed -E 's|^https?://[^:]+:([0-9]+).*|\1|')
# Si pas de port explicite, defaut HTTP=80, HTTPS=443
if [ "${LOKI_PORT}" = "${LOKI_URL}" ]; then
    case "${LOKI_URL}" in
        https://*) LOKI_PORT=443 ;;
        *) LOKI_PORT=80 ;;
    esac
fi

# Construction de l'URL /ready de Loki pour le check
LOKI_BASE=$(echo "${LOKI_URL}" | sed -E 's|(https?://[^/]+).*|\1|')
LOKI_READY_URL="${LOKI_BASE}/ready"

LOKI_OK=0
if command -v curl &>/dev/null; then
    if curl -sf --max-time 5 "${LOKI_READY_URL}" >/dev/null 2>&1; then
        LOKI_OK=1
        echo "  -> Loki joignable : OK (${LOKI_BASE})"
    fi
fi

if [ "${LOKI_OK}" -eq 0 ]; then
    if [ "${STRICT_CHECKS}" -eq 1 ]; then
        echo "  -> ERREUR : Loki injoignable sur ${LOKI_BASE}"
        echo "             Verifiez que Loki tourne et que le reseau est OK."
        echo "             Mode strict actif (STRICT_CHECKS=1) : abandon."
        exit 1
    else
        echo "  -> ATTENTION : Loki injoignable sur ${LOKI_BASE}"
        echo "                Alloy demarrera quand meme et retentera de pousser."
        echo "                Pour echouer en cas de Loki injoignable : STRICT_CHECKS=1"
    fi
fi
echo ""

# ── Detection Docker ─────────────────────────────────────────────────────────
HAS_DOCKER=0
if command -v docker &>/dev/null && [ -S /var/run/docker.sock ]; then
    HAS_DOCKER=1
    echo "  Docker detecte -> mode container"
else
    echo "  Docker absent -> mode binaire systemd"
fi
echo ""

mkdir -p "${ALLOY_DST_DIR}"

# ══════════════════════════════════════════════════════════════════════════════
# MODE DOCKER
# ══════════════════════════════════════════════════════════════════════════════
if [ "${HAS_DOCKER}" -eq 1 ]; then

    echo "[1/4] Copie des fichiers vers ${ALLOY_DST_DIR}..."
    cp "${ALLOY_SRC_DIR}/docker-compose.yml" "${ALLOY_DST_DIR}/"
    cp "${ALLOY_SRC_DIR}/config.alloy" "${ALLOY_DST_DIR}/"
    echo "  -> OK"

    echo "[2/4] Ecriture .env..."
    cat > "${ALLOY_DST_DIR}/.env" << EOF
LOKI_URL=${LOKI_URL}
HOSTNAME=${HOSTNAME_LABEL}
EOF
    echo "  -> ${ALLOY_DST_DIR}/.env"

    echo "[3/4] Demarrage du container Alloy..."
    cd "${ALLOY_DST_DIR}"
    # Pull avec retry (registry parfois lente)
    PULL_OK=0
    for attempt in 1 2 3; do
        if docker compose pull 2>&1; then
            PULL_OK=1
            break
        fi
        echo "  -> Tentative ${attempt}/3 echouee, retry dans 3s..."
        sleep 3
    done
    if [ "${PULL_OK}" -eq 0 ]; then
        echo "  ERREUR : impossible de puller l'image Alloy apres 3 tentatives."
        exit 1
    fi
    docker compose up -d
    echo "  -> OK"

    echo "[4/4] Verification post-install..."
    sleep 4
    # Verifier que le container est en running
    CONTAINER_STATE=$(docker compose ps --format json 2>/dev/null | grep -o '"State":"[^"]*"' | head -1 | cut -d'"' -f4 || echo "unknown")
    # Fallback : ancienne syntaxe docker compose ps
    if [ "${CONTAINER_STATE}" = "unknown" ] || [ -z "${CONTAINER_STATE}" ]; then
        CONTAINER_STATE=$(docker compose ps 2>/dev/null | grep -i "agflow-alloy-agent" | awk '{print $NF}' | head -1 || echo "unknown")
    fi

    if echo "${CONTAINER_STATE}" | grep -qiE "running|up"; then
        echo "  -> Container Alloy : OK (${CONTAINER_STATE})"
    else
        echo "  -> ERREUR : Container Alloy n'est pas en running (etat : ${CONTAINER_STATE})"
        echo ""
        echo "  Logs des 20 dernieres lignes :"
        docker compose logs --tail 20 2>&1 | sed 's/^/    /'
        exit 1
    fi

    # Verifier qu'Alloy a bien commence a pousser (apres ~5s de fonctionnement)
    sleep 2
    ALLOY_LOGS=$(docker compose logs --tail 50 2>/dev/null || echo "")
    if echo "${ALLOY_LOGS}" | grep -qi "error.*loki\|connection refused\|no route to host"; then
        if [ "${STRICT_CHECKS}" -eq 1 ]; then
            echo "  -> ERREUR : Alloy a des erreurs de push vers Loki"
            echo "${ALLOY_LOGS}" | grep -iE "error|refused" | tail -5 | sed 's/^/    /'
            exit 1
        else
            echo "  -> ATTENTION : Alloy a des erreurs de push vers Loki (continue, retry auto)"
            echo "${ALLOY_LOGS}" | grep -iE "error|refused" | tail -5 | sed 's/^/    /'
        fi
    else
        echo "  -> Alloy push Loki : OK (pas d'erreur detectee)"
    fi

    echo ""
    docker compose ps

# ══════════════════════════════════════════════════════════════════════════════
# MODE BINAIRE SYSTEMD
# ══════════════════════════════════════════════════════════════════════════════
else

    echo "[1/5] Ajout du depot Grafana..."
    if ! command -v wget &>/dev/null || ! command -v gpg &>/dev/null; then
        apt-get update -qq
        apt-get "${APT_OPTS[@]}" install -y -qq wget gnupg ca-certificates
    fi
    install -m 0755 -d /etc/apt/keyrings
    if [ ! -f /etc/apt/keyrings/grafana.gpg ] || [ ! -s /etc/apt/keyrings/grafana.gpg ]; then
        wget -qO- https://apt.grafana.com/gpg.key | gpg --dearmor -o /etc/apt/keyrings/grafana.gpg
        chmod a+r /etc/apt/keyrings/grafana.gpg
    fi
    echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" \
        > /etc/apt/sources.list.d/grafana.list
    apt-get update -qq
    echo "  -> OK"

    echo "[2/5] Installation paquet alloy..."
    apt-get "${APT_OPTS[@]}" install -y -qq alloy
    echo "  -> OK"

    echo "[3/5] Ecriture config et environment..."
    cp "${ALLOY_SRC_DIR}/config-journald-only.alloy" /etc/alloy/config.alloy
    # L'unit systemd du paquet Debian attend CONFIG_FILE et CUSTOM_ARGS.
    # Sans CONFIG_FILE, `alloy run` echoue ("accepts 1 arg(s), received 0").
    cat > /etc/default/alloy << EOF
CONFIG_FILE="/etc/alloy/config.alloy"
CUSTOM_ARGS=""
RESTART_ON_UPGRADE=true
LOKI_URL=${LOKI_URL}
HOSTNAME=${HOSTNAME_LABEL}
EOF
    echo "  -> /etc/alloy/config.alloy"
    echo "  -> /etc/default/alloy"

    echo "[4/5] Demarrage service alloy..."
    systemctl daemon-reload
    systemctl enable alloy
    systemctl restart alloy
    sleep 3
    echo "  -> OK"

    echo "[5/5] Verification post-install..."
    if systemctl is-active --quiet alloy; then
        echo "  -> Service alloy : OK (active)"
    else
        echo "  -> ERREUR : Service alloy n'est pas actif"
        systemctl status alloy --no-pager --lines=10 || true
        exit 1
    fi

    # Verifier les erreurs Loki recentes
    sleep 2
    JOURNAL_LOGS=$(journalctl -u alloy --since "30 seconds ago" --no-pager 2>/dev/null || echo "")
    if echo "${JOURNAL_LOGS}" | grep -qi "error.*loki\|connection refused\|no route to host"; then
        if [ "${STRICT_CHECKS}" -eq 1 ]; then
            echo "  -> ERREUR : Alloy a des erreurs de push vers Loki"
            echo "${JOURNAL_LOGS}" | grep -iE "error|refused" | tail -5 | sed 's/^/    /'
            exit 1
        else
            echo "  -> ATTENTION : Alloy a des erreurs de push vers Loki (continue, retry auto)"
            echo "${JOURNAL_LOGS}" | grep -iE "error|refused" | tail -5 | sed 's/^/    /'
        fi
    else
        echo "  -> Alloy push Loki : OK (pas d'erreur detectee)"
    fi

    systemctl status alloy --no-pager --lines=5 || true
fi

echo ""
echo "==========================================="
echo "  Alloy installe et demarre"
echo "==========================================="
echo "{\"status\":\"ok\",\"hostname\":\"${HOSTNAME_LABEL}\",\"loki_url\":\"${LOKI_URL}\",\"loki_reachable\":${LOKI_OK},\"strict_checks\":${STRICT_CHECKS},\"mode\":\"$([ ${HAS_DOCKER} -eq 1 ] && echo docker || echo systemd)\"}"
