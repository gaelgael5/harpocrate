#!/usr/bin/env bash
#
# destroy-test.sh — Supprime un LXC de test créé par run-test.sh.
#
# Usage :
#   ./scripts/destroy-test.sh <CTID>
#   ./scripts/destroy-test.sh <CTID> <autre-config>
#
# Exemple :
#   ./scripts/destroy-test.sh 400
#
# Sécurités :
#   - Refuse si CTID est hors de la plage [CTID_MIN..CTID_MAX] du fichier
#     de config (évite de détruire un LXC de prod par erreur)
#   - Refuse si le nom du LXC distant ne commence pas par "test-"
#     (deuxième garde-fou : un LXC non-test dans la plage par accident)
#   - `pct stop` puis `pct destroy --purge` (efface aussi les backups
#     dans Proxmox storage)
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ $# -lt 1 ]; then
    echo "✗ Usage : $0 <CTID> [<fichier-config>]" >&2
    echo "  Exemple : $0 400" >&2
    exit 1
fi

CTID="$1"
CONFIG_NAME="${2:-.env.test.docker}"
LOCAL_CONFIG="${SCRIPT_DIR}/${CONFIG_NAME}"
SSH_HOST="${SSH_HOST:-pve}"

# ─── Validation de CTID (numérique) ────────────────────────────────────────
if ! [[ "$CTID" =~ ^[0-9]+$ ]]; then
    echo "✗ CTID doit être numérique, reçu : '${CTID}'" >&2
    exit 1
fi

# ─── Chargement du fichier de config (strip \r si CRLF) ────────────────────
if [ ! -f "${LOCAL_CONFIG}" ]; then
    echo "✗ Fichier de config introuvable : ${LOCAL_CONFIG}" >&2
    exit 1
fi
_CONFIG_TMP="$(mktemp)"
tr -d '\r' < "${LOCAL_CONFIG}" > "${_CONFIG_TMP}"
# shellcheck source=/dev/null
. "${_CONFIG_TMP}"
rm -f "${_CONFIG_TMP}"

for _var in CTID_MIN CTID_MAX; do
    if [ -z "${!_var:-}" ]; then
        echo "✗ ${_var} absente ou vide dans ${LOCAL_CONFIG}" >&2
        exit 1
    fi
done

# ─── Garde-fou 1 : CTID dans la plage déclarée ─────────────────────────────
if [ "$CTID" -lt "$CTID_MIN" ] || [ "$CTID" -gt "$CTID_MAX" ]; then
    echo "✗ CTID ${CTID} hors de la plage de test [${CTID_MIN}..${CTID_MAX}]" >&2
    echo "  Refus pour éviter de toucher un LXC de prod par erreur." >&2
    echo "  Si tu veux vraiment supprimer ${CTID}, fais-le à la main :" >&2
    echo "    ssh ${SSH_HOST} \"pct stop ${CTID} && pct destroy ${CTID} --purge\"" >&2
    exit 1
fi

# ─── Garde-fou 2 : LXC existe + nom commence par "test-" ──────────────────
echo "→ Vérification du LXC ${CTID} sur ${SSH_HOST}..."
LXC_NAME="$(ssh "${SSH_HOST}" "pct config ${CTID} 2>/dev/null | awk '/^hostname:/ {print \$2}'")"

if [ -z "${LXC_NAME}" ]; then
    echo "✗ LXC ${CTID} introuvable sur ${SSH_HOST} (déjà supprimé ?)." >&2
    exit 1
fi

if [[ ! "${LXC_NAME}" =~ ^test- ]]; then
    echo "✗ Le LXC ${CTID} (nom: '${LXC_NAME}') ne commence pas par 'test-'." >&2
    echo "  Refus pour éviter de détruire un LXC non-test par accident." >&2
    exit 1
fi

echo "  ✓ LXC ${CTID} (${LXC_NAME}) éligible à la suppression"

# ─── Stop + destroy ────────────────────────────────────────────────────────
echo "→ Stop du LXC ${CTID}..."
ssh "${SSH_HOST}" "pct stop ${CTID} 2>&1 || true"
sleep 2

echo "→ Destroy --purge du LXC ${CTID}..."
ssh "${SSH_HOST}" "pct destroy ${CTID} --purge"

echo ""
echo "✓ LXC ${CTID} (${LXC_NAME}) supprimé."
