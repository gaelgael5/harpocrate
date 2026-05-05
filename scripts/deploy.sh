#!/usr/bin/env bash
###############################################################################
# Deploy harpocrate sur le LXC de test (CT 202 via l'hote Proxmox).
#
# A executer DEPUIS le poste de developpement.
# Pousse vers le LXC :
#   - deploy/docker-compose.yml -> /opt/harpocrate/docker-compose.yml
#   - deploy/.env.example      -> /opt/harpocrate/.env.example
#   - db/init/*.sql            -> /opt/harpocrate/db/init/
#   - scripts/refresh.sh       -> /opt/harpocrate/refresh.sh
# Puis execute refresh.sh dans le LXC (pull + up).
#
# Usage :
#   ./scripts/deploy.sh                  # tag latest
#   TAG=v0.2.0 ./scripts/deploy.sh       # tag specifique
#   CTID=205 ./scripts/deploy.sh         # autre container
###############################################################################
set -euo pipefail

PVE_HOST="${PVE_HOST:-pve}"
CTID="${CTID:-202}"
REMOTE_DIR="${REMOTE_DIR:-/opt/harpocrate}"
TAG="${TAG:-latest}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==========================================="
echo "  Deploy harpocrate"
echo "  Cible : ${PVE_HOST} -> CT ${CTID} -> ${REMOTE_DIR}"
echo "  Tag   : ${TAG}"
echo "==========================================="

# ── 1. Preparer arborescence dans le LXC ─────────────────────────────────────
echo "[1/4] Preparation du dossier ${REMOTE_DIR} dans CT ${CTID}..."
ssh "${PVE_HOST}" "pct exec ${CTID} -- mkdir -p ${REMOTE_DIR}/db/init"

# ── 2. Stage local sur l'hote pve ────────────────────────────────────────────
TMPDIR_PVE="/tmp/harpocrate-deploy-$$"
echo "[2/4] Stage des fichiers sur ${PVE_HOST}:${TMPDIR_PVE}..."
ssh "${PVE_HOST}" "mkdir -p ${TMPDIR_PVE}/db/init"
scp "${REPO_ROOT}/deploy/docker-compose.yml"       "${PVE_HOST}:${TMPDIR_PVE}/docker-compose.yml"
scp "${REPO_ROOT}/deploy/.env.example"            "${PVE_HOST}:${TMPDIR_PVE}/.env.example"
scp "${REPO_ROOT}/db/init/01-extensions.sql"      "${PVE_HOST}:${TMPDIR_PVE}/db/init/01-extensions.sql"
scp "${REPO_ROOT}/scripts/refresh.sh"             "${PVE_HOST}:${TMPDIR_PVE}/refresh.sh"
if [ -d "${REPO_ROOT}/types" ]; then
    scp -r "${REPO_ROOT}/types" "${PVE_HOST}:${TMPDIR_PVE}/types"
fi
if [ -d "${REPO_ROOT}/releases" ]; then
    scp -r "${REPO_ROOT}/releases" "${PVE_HOST}:${TMPDIR_PVE}/releases"
fi
if [ -f "${REPO_ROOT}/.env" ]; then
    scp "${REPO_ROOT}/.env" "${PVE_HOST}:${TMPDIR_PVE}/.env"
    HAS_ENV=1
else
    HAS_ENV=0
fi

# ── 3. Push dans le LXC ──────────────────────────────────────────────────────
echo "[3/4] Push dans CT ${CTID}..."
ssh "${PVE_HOST}" "pct push ${CTID} ${TMPDIR_PVE}/docker-compose.yml    ${REMOTE_DIR}/docker-compose.yml"
ssh "${PVE_HOST}" "pct push ${CTID} ${TMPDIR_PVE}/.env.example          ${REMOTE_DIR}/.env.example"
ssh "${PVE_HOST}" "pct push ${CTID} ${TMPDIR_PVE}/db/init/01-extensions.sql ${REMOTE_DIR}/db/init/01-extensions.sql"
ssh "${PVE_HOST}" "pct push ${CTID} ${TMPDIR_PVE}/refresh.sh            ${REMOTE_DIR}/refresh.sh"
ssh "${PVE_HOST}" "pct exec ${CTID} -- chmod +x ${REMOTE_DIR}/refresh.sh"
if [ -d "${TMPDIR_PVE}/types" ] 2>/dev/null || ssh "${PVE_HOST}" "[ -d '${TMPDIR_PVE}/types' ]" 2>/dev/null; then
    echo "  -> Deploiement des types de secrets..."
    for TYPE_DIR in raw site_login; do
        ssh "${PVE_HOST}" "pct exec ${CTID} -- mkdir -p ${REMOTE_DIR}/types/${TYPE_DIR}"
        for FNAME in meta.json schema_data.json schema_ui.json; do
            SRC="${TMPDIR_PVE}/types/${TYPE_DIR}/${FNAME}"
            DEST="${REMOTE_DIR}/types/${TYPE_DIR}/${FNAME}"
            if ssh "${PVE_HOST}" "[ -f '${SRC}' ]" 2>/dev/null; then
                ssh "${PVE_HOST}" "pct push ${CTID} ${SRC} ${DEST}"
                echo "    -> types/${TYPE_DIR}/${FNAME}"
            fi
        done
    done
fi
if ssh "${PVE_HOST}" "[ -d '${TMPDIR_PVE}/releases' ]" 2>/dev/null; then
    echo "  -> Deploiement des artefacts SDK + CLI (releases/)..."
    ssh "${PVE_HOST}" "pct exec ${CTID} -- mkdir -p ${REMOTE_DIR}/releases"
    # Liste les fichiers cote pve puis push un par un (pct push n'accepte pas les dirs)
    for FNAME in $(ssh "${PVE_HOST}" "ls ${TMPDIR_PVE}/releases/" 2>/dev/null); do
        ssh "${PVE_HOST}" "pct push ${CTID} ${TMPDIR_PVE}/releases/${FNAME} ${REMOTE_DIR}/releases/${FNAME}"
        echo "    -> releases/${FNAME}"
    done
fi
if [ "${HAS_ENV}" = "1" ]; then
    ssh "${PVE_HOST}" "pct push ${CTID} ${TMPDIR_PVE}/.env ${REMOTE_DIR}/.env"
    echo "  -> .env local pousse"
else
    echo "  -> Pas de .env local. Le LXC utilisera .env.example (a editer sur place)."
fi

# Cleanup stage
ssh "${PVE_HOST}" "rm -rf ${TMPDIR_PVE}"

# ── 4. Refresh stack (pull + up) ─────────────────────────────────────────────
echo "[4/4] Refresh stack dans CT ${CTID}..."
ssh "${PVE_HOST}" "pct exec ${CTID} -- bash -c 'cd ${REMOTE_DIR} && TAG=${TAG} ./refresh.sh'"

echo ""
echo "==========================================="
echo "  Deploy harpocrate OK"
echo "==========================================="
