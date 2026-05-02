#!/usr/bin/env bash
###############################################################################
# Déploie l'agent Alloy (collecteur Loki) sur un LXC ou un hôte SSH distant.
#
# Usage :
#   ./scripts/infra/deploy-alloy.sh <CTID>        # CTID Proxmox numérique (ex: 202)
#   ./scripts/infra/deploy-alloy.sh <ssh-alias>   # Alias SSH quelconque (ex: mon-serveur)
#
# CTID numérique : transit via l'hôte Proxmox (ssh pve + pct push).
# Alias SSH      : scp direct + ssh.
#
# Pousse infra/alloy-agent/ vers /opt/alloy/ sur la cible,
# vérifie/crée le .env, lance docker compose up -d,
# puis effectue un smoke test (/-/ready + docker logs).
###############################################################################
set -euo pipefail

# ── Paramètres ────────────────────────────────────────────────────────────────
TARGET="${1:-}"
PVE_HOST="${PVE_HOST:-pve}"
REMOTE_DIR="/opt/alloy"
ALLOY_PORT=12345

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC_DIR="${REPO_ROOT}/infra/alloy-agent"

# ── Validation des arguments ──────────────────────────────────────────────────
if [ -z "${TARGET}" ]; then
    echo "Erreur : argument manquant."
    echo "Usage : $0 <CTID|ssh-alias>"
    exit 1
fi

if [ ! -d "${SRC_DIR}" ]; then
    echo "Erreur : dossier source introuvable : ${SRC_DIR}"
    exit 1
fi

echo "==========================================="
echo "  Deploy Alloy agent (module=harpocrate)"
echo "  Cible  : ${TARGET}"
echo "  Source : ${SRC_DIR}"
echo "  Dest   : ${REMOTE_DIR}"
echo "==========================================="

# ── Détection du mode (CTID numérique vs alias SSH) ──────────────────────────
IS_CTID=0
if [[ "${TARGET}" =~ ^[0-9]+$ ]]; then
    IS_CTID=1
    CTID="${TARGET}"
    echo "  Mode : Proxmox pct (CT ${CTID} via ${PVE_HOST})"
else
    SSH_TARGET="${TARGET}"
    echo "  Mode : SSH direct (${SSH_TARGET})"
fi
echo ""

# ── Fonctions helpers ─────────────────────────────────────────────────────────

# Exécute une commande sur la cible
remote_exec() {
    if [ "${IS_CTID}" -eq 1 ]; then
        ssh "${PVE_HOST}" "pct exec ${CTID} -- bash -c '$*'"
    else
        ssh "${SSH_TARGET}" "$@"
    fi
}

# Copie un fichier local vers la cible
remote_push() {
    local local_path="$1"
    local remote_path="$2"
    if [ "${IS_CTID}" -eq 1 ]; then
        # Transit par l'hôte Proxmox : scp local -> pve, puis pct push pve -> LXC
        local tmp_path="/tmp/alloy-deploy-$$/$(basename "${local_path}")"
        ssh "${PVE_HOST}" "mkdir -p $(dirname "${tmp_path}")"
        scp "${local_path}" "${PVE_HOST}:${tmp_path}"
        ssh "${PVE_HOST}" "pct push ${CTID} ${tmp_path} ${remote_path}"
        ssh "${PVE_HOST}" "rm -f ${tmp_path}"
    else
        scp "${local_path}" "${SSH_TARGET}:${remote_path}"
    fi
}

# ── 1. Préparer le dossier cible ──────────────────────────────────────────────
echo "[1/5] Préparation du dossier ${REMOTE_DIR}..."
remote_exec "mkdir -p ${REMOTE_DIR}"

# Préparer le répertoire temporaire sur pve pour le mode CTID
if [ "${IS_CTID}" -eq 1 ]; then
    TMP_PVE="/tmp/alloy-deploy-$$"
    ssh "${PVE_HOST}" "mkdir -p ${TMP_PVE}"
fi

# ── 2. Push des fichiers ──────────────────────────────────────────────────────
echo "[2/5] Push des fichiers vers ${REMOTE_DIR}..."

ALLOY_FILES=(
    "docker-compose.yml"
    "config.alloy"
    "config-journald-only.alloy"
    ".env.template"
)

if [ "${IS_CTID}" -eq 1 ]; then
    # Copie tous les fichiers vers pve en une passe, puis pct push pour chacun
    for f in "${ALLOY_FILES[@]}"; do
        if [ -f "${SRC_DIR}/${f}" ]; then
            scp "${SRC_DIR}/${f}" "${PVE_HOST}:${TMP_PVE}/${f}"
            ssh "${PVE_HOST}" "pct push ${CTID} ${TMP_PVE}/${f} ${REMOTE_DIR}/${f}"
            echo "  -> ${f}"
        fi
    done
    # Nettoyage du répertoire temporaire sur pve
    ssh "${PVE_HOST}" "rm -rf ${TMP_PVE}"
else
    for f in "${ALLOY_FILES[@]}"; do
        if [ -f "${SRC_DIR}/${f}" ]; then
            scp "${SRC_DIR}/${f}" "${SSH_TARGET}:${REMOTE_DIR}/${f}"
            echo "  -> ${f}"
        fi
    done
fi

# ── 3. Vérifier / créer .env ──────────────────────────────────────────────────
echo ""
echo "[3/5] Vérification du .env..."

ENV_EXISTS=$(remote_exec "[ -f ${REMOTE_DIR}/.env ] && echo yes || echo no")

if [ "${ENV_EXISTS}" = "no" ]; then
    echo "  -> Aucun .env trouvé. Copie depuis .env.template..."
    remote_exec "cp ${REMOTE_DIR}/.env.template ${REMOTE_DIR}/.env"
    echo ""
    echo "  ATTENTION : Le fichier ${REMOTE_DIR}/.env a été créé depuis le template."
    echo "  Editez-le sur la cible pour renseigner les vraies valeurs :"
    echo ""
    echo "    LOKI_URL=http://192.168.10.158:3100/loki/api/v1/push"
    echo "    HOSTNAME=lxc${TARGET}"
    echo ""
    echo "  Puis relancez ce script."
    exit 0
else
    echo "  -> .env présent : OK"
fi

# ── 4. Lancer docker compose up -d ───────────────────────────────────────────
echo ""
echo "[4/5] Démarrage du container Alloy..."
remote_exec "cd ${REMOTE_DIR} && docker compose pull && docker compose up -d"
echo "  -> docker compose up -d : OK"

# ── 5. Smoke test ─────────────────────────────────────────────────────────────
echo ""
echo "[5/5] Smoke test..."

# Attendre quelques secondes que le container démarre
sleep 5

# Test /-/ready depuis la cible elle-même
echo "  -> curl http://localhost:${ALLOY_PORT}/-/ready :"
READY_RESULT=$(remote_exec "curl -sf --max-time 10 http://localhost:${ALLOY_PORT}/-/ready || echo FAILED")
if echo "${READY_RESULT}" | grep -qi "FAILED\|error"; then
    echo "  -> ATTENTION : Alloy ne répond pas encore sur /-/ready"
    echo "     (normal si l'image vient d'être pullée, retry dans quelques secondes)"
else
    echo "  -> Alloy ready : OK"
fi

# Logs du container
echo ""
echo "  -> Logs harpocrate-alloy-agent (20 dernières lignes) :"
remote_exec "docker logs harpocrate-alloy-agent --tail 20 2>&1 || docker compose -f ${REMOTE_DIR}/docker-compose.yml logs --tail 20" | sed 's/^/    /'

echo ""
echo "==========================================="
echo "  Alloy déployé sur ${TARGET}"
echo "  Labels Loki : host=<HOSTNAME> module=harpocrate"
echo "  Interface   : http://<host>:${ALLOY_PORT}"
echo "  Grafana     : https://log.yoops.org"
echo "==========================================="
