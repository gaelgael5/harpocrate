#!/usr/bin/env bash
#
# run-test.sh — Orchestre le test d'intégration LXC depuis le poste local.
#
# Étapes :
#   1. Pousse scripts/test-create-lxc.sh vers pve:/opt/scripts/ (écrase, chmod +x)
#   2. Pousse scripts/.env.test.docker vers pve:/opt/scripts/ (écrase)
#   3. Lance sur pve : /opt/scripts/test-create-lxc.sh .env.test.docker
#
# Usage :
#   ./scripts/run-test.sh                # config par défaut: scripts/.env.test.docker
#   ./scripts/run-test.sh <autre-config> # exemple: ./scripts/run-test.sh .env.test.staging
#   CLEANUP=1 ./scripts/run-test.sh      # purge le LXC créé après les tests
#   SSH_HOST=pve2 ./scripts/run-test.sh  # override de l'hôte SSH cible
#
# Pré-requis :
#   - alias SSH `pve` dans ~/.ssh/config (ou override via SSH_HOST=…)
#   - /opt/scripts/.env.git côté pve (PAT GitHub avec scope `repo`)
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_SCRIPT="${SCRIPT_DIR}/test-create-lxc.sh"
DESTROY_SCRIPT="${SCRIPT_DIR}/destroy-test.sh"

CONFIG_NAME="${1:-.env.test.docker}"
LOCAL_CONFIG="${SCRIPT_DIR}/${CONFIG_NAME}"

SSH_HOST="${SSH_HOST:-pve}"
REMOTE_DIR="/opt/scripts"
CLEANUP="${CLEANUP:-0}"

# ─── Vérifications locales ──────────────────────────────────────────────────
if [ ! -f "${TEST_SCRIPT}" ]; then
    echo "✗ Script local introuvable : ${TEST_SCRIPT}" >&2
    exit 1
fi
if [ ! -f "${DESTROY_SCRIPT}" ]; then
    echo "✗ Script local introuvable : ${DESTROY_SCRIPT}" >&2
    exit 1
fi
if [ ! -f "${LOCAL_CONFIG}" ]; then
    echo "✗ Fichier de config introuvable : ${LOCAL_CONFIG}" >&2
    echo "  Tu peux passer un autre nom de config en argument :" >&2
    echo "    $0 .env.test.staging" >&2
    exit 1
fi

echo "→ Cible SSH         : ${SSH_HOST}"
echo "→ Scripts à pousser : ${TEST_SCRIPT}"
echo "                      ${DESTROY_SCRIPT}"
echo "→ Config à pousser  : ${LOCAL_CONFIG}"
echo "→ Destination       : ${SSH_HOST}:${REMOTE_DIR}/"
echo ""

# ─── 1) Push des scripts test-create-lxc.sh + destroy-test.sh ─────────────
echo "[1/3] Push scripts → ${SSH_HOST}:${REMOTE_DIR}/..."
ssh "${SSH_HOST}" "mkdir -p ${REMOTE_DIR}"
scp "${TEST_SCRIPT}" "${SSH_HOST}:${REMOTE_DIR}/test-create-lxc.sh"
scp "${DESTROY_SCRIPT}" "${SSH_HOST}:${REMOTE_DIR}/destroy-test.sh"
ssh "${SSH_HOST}" "chmod +x ${REMOTE_DIR}/test-create-lxc.sh ${REMOTE_DIR}/destroy-test.sh"
echo "      ✓ test-create-lxc.sh + destroy-test.sh poussés et exécutables"

# ─── 2) Push du fichier de config (converti en LF si CRLF) ────────────────
# Sur Windows, l'éditeur peut sauver en CRLF. Source-r un .env avec CRLF
# colle un `\r` à chaque valeur, ce qui pourrit silencieusement les URLs
# et chemins côté pve. On strippe les `\r` avant le scp.
echo "[2/3] Push ${CONFIG_NAME} (LF normalisé) → ${SSH_HOST}:${REMOTE_DIR}/..."
_CONFIG_TMP="$(mktemp)"
tr -d '\r' < "${LOCAL_CONFIG}" > "${_CONFIG_TMP}"
scp "${_CONFIG_TMP}" "${SSH_HOST}:${REMOTE_DIR}/${CONFIG_NAME}"
rm -f "${_CONFIG_TMP}"
echo "      ✓ poussé"
echo ""

# ─── 3) Lancement du test sur pve ──────────────────────────────────────────
echo "[3/3] Exécution sur ${SSH_HOST} : ${REMOTE_DIR}/test-create-lxc.sh ${CONFIG_NAME}"
echo "──────────────────────────────────────────────────────────────────────────"

# CLEANUP est propagé côté distant via -t pour avoir une TTY (logs en direct).
# `bash -lc` pour que le PATH inclue /usr/sbin (pour `pct`) sur certaines
# images Proxmox.
ssh -t "${SSH_HOST}" \
    "cd ${REMOTE_DIR} && CLEANUP=${CLEANUP} bash -lc './test-create-lxc.sh ${CONFIG_NAME}'"
