#!/usr/bin/env bash
###############################################################################
# Refresh Harpocrate sur un serveur où le repo est git-cloné directement.
#
# Usage (à exécuter SUR le serveur, dans le repo cloné) :
#   cd <chemin-du-repo>
#   git pull
#   ./scripts/refresh-from-git.sh
#
# Différence avec ./scripts/deploy.sh :
#   - deploy.sh        : run depuis le POSTE DE DEV, push tout vers un LXC distant via pve.
#   - refresh-from-git : run SUR le serveur lui-même, dans le repo cloné. Pas de SSH/pct.
#
# Ce que ce script fait :
#   1. Synchronise releases/  →  deploy/releases/  (où docker-compose attend les SDK)
#   2. Vérifie deploy/.env (sinon copie depuis .env.example et exit pour édition)
#   3. docker compose pull (récupère les nouvelles images)
#   4. docker compose up -d (restart les services modifiés)
#   5. Affiche le status
###############################################################################
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_DIR="${REPO_ROOT}/deploy"
COMPOSE_FILE="${COMPOSE_DIR}/docker-compose.yml"
RELEASES_SRC="${REPO_ROOT}/releases"
RELEASES_DEST="${COMPOSE_DIR}/releases"
ENV_FILE="${COMPOSE_DIR}/.env"
ENV_EXAMPLE="${COMPOSE_DIR}/.env.example"

echo "==========================================="
echo "  Refresh Harpocrate (depuis git)"
echo "  Repo  : ${REPO_ROOT}"
echo "==========================================="

# ── 1. Sanity ────────────────────────────────────────────────────────────────
if [ ! -f "${COMPOSE_FILE}" ]; then
    echo "ERREUR : ${COMPOSE_FILE} introuvable. Le repo est-il complet ?"
    exit 1
fi

# ── 2. Synchroniser releases/  →  deploy/releases/ ──────────────────────────
mkdir -p "${RELEASES_DEST}"
if [ -d "${RELEASES_SRC}" ] && [ -n "$(ls -A "${RELEASES_SRC}" 2>/dev/null)" ]; then
    echo "[1/5] Sync ${RELEASES_SRC}/  →  ${RELEASES_DEST}/ ..."
    if command -v rsync >/dev/null 2>&1; then
        rsync -a --delete "${RELEASES_SRC}/" "${RELEASES_DEST}/"
    else
        # Fallback sans rsync : nettoie puis copie
        find "${RELEASES_DEST}" -mindepth 1 -delete 2>/dev/null || true
        cp -r "${RELEASES_SRC}/." "${RELEASES_DEST}/"
    fi
    echo "      $(ls "${RELEASES_DEST}" | wc -l) fichier(s) déployé(s) :"
    ls -1 "${RELEASES_DEST}" | sed 's/^/        /'
else
    echo "[1/5] [!] ${RELEASES_SRC}/ vide ou absent — pas de SDK à pousser."
    echo "      Les boutons de téléchargement seront grisés dans l'IHM Intégration."
fi

# ── 3. Vérifier .env ─────────────────────────────────────────────────────────
if [ ! -f "${ENV_FILE}" ]; then
    if [ -f "${ENV_EXAMPLE}" ]; then
        cp "${ENV_EXAMPLE}" "${ENV_FILE}"
        echo "[2/5] [!] ${ENV_FILE} créé depuis .env.example."
        echo "       ÉDITE-LE (POSTGRES_PASSWORD, HARPOCRATE_HMAC_KEY, KEYCLOAK_*) puis relance."
        exit 1
    fi
    echo "ERREUR : ni .env ni .env.example dans ${COMPOSE_DIR}/."
    exit 1
fi
echo "[2/5] .env présent."

# ── 4. Pull + up ─────────────────────────────────────────────────────────────
cd "${COMPOSE_DIR}"

echo "[3/5] Pull des images Docker (peut prendre un moment)..."
docker compose pull

echo "[4/5] Redémarrage des services..."
docker compose up -d --remove-orphans

echo "[5/5] Cleanup + status :"
docker image prune -f >/dev/null
docker compose ps

echo ""
echo "==========================================="
echo "  Refresh OK"
echo "  Tester :  curl -s http://127.0.0.1:8000/v1/sdk/manifest | head -50"
echo "==========================================="
