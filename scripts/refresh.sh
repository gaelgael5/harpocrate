#!/usr/bin/env bash
###############################################################################
# Refresh harpocrate stack : pull les dernieres images et redemarre les services.
#
# A executer SUR le serveur cible, dans le dossier de deploiement (par defaut
# /opt/harpocrate). Lit ./.env (qui contient TAG, POSTGRES_*, LOG_LEVEL...).
#
# Usage :
#   ./refresh.sh                     # tag pris depuis .env (TAG=...) ou "latest"
#   TAG=v0.2.0 ./refresh.sh          # override en ligne de commande
#   TAG=sha-abc1234 ./refresh.sh     # tag par commit SHA (du workflow CI)
###############################################################################
set -euo pipefail

cd "$(dirname "$0")"

# ── 1. Verifier que .env existe ──────────────────────────────────────────────
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "[!] .env genere depuis .env.example."
        echo "    Editez les credentials avant de relancer ce script."
        exit 1
    fi
    echo "ERREUR : .env manquant et pas de .env.example."
    exit 1
fi

# ── 2. Resoudre le tag (priorite : env var > .env > 'latest') ────────────────
if [ -z "${TAG:-}" ]; then
    TAG=$(grep -E '^TAG=' .env 2>/dev/null | cut -d= -f2- | tr -d '"' || true)
fi
TAG="${TAG:-latest}"
export TAG

echo "==========================================="
echo "  Refresh harpocrate (TAG=${TAG})"
echo "==========================================="

# ── 3. Préparer les volumes de données (idempotent) ──────────────────────────
# Le container backend tourne sous l'user 'harpocrate' (uid 1001 dans l'image).
# Les volumes bind ./backups et ./data/postgres doivent appartenir à cet uid
# côté hôte sinon le mkdir/écriture échoue (Errno 13).
BACKUPS_DIR="$(pwd)/backups"
if [ ! -d "${BACKUPS_DIR}" ]; then
    echo "[*] Création de ${BACKUPS_DIR} (uid 1001 — user harpocrate du container)..."
    install -d -o 1001 -g 1001 "${BACKUPS_DIR}"
else
    # S'assure que les permissions restent correctes même si le dossier
    # existe déjà (cas où l'admin l'a créé manuellement avant ce commit).
    current_uid=$(stat -c '%u' "${BACKUPS_DIR}")
    if [ "${current_uid}" != "1001" ]; then
        echo "[*] Réajustement de l'ownership de ${BACKUPS_DIR} → 1001:1001"
        chown -R 1001:1001 "${BACKUPS_DIR}"
    fi
fi

# ── 4. Sync releases/ depuis le repo Git (index.json + artefacts + docs) ─────
RAW_BASE="https://raw.githubusercontent.com/gaelgael5/harpocrate/refs/heads/main"
RELEASES_DIR="$(pwd)/releases"
DOCS_DIR="${RELEASES_DIR}/docs"
mkdir -p "${DOCS_DIR}"

echo "[1/6] Sync releases/index.json depuis ${RAW_BASE}..."
INDEX_PATH="${RELEASES_DIR}/index.json"
INDEX_TMP="${INDEX_PATH}.tmp"
if curl -fsSL -o "${INDEX_TMP}" "${RAW_BASE}/releases/index.json"; then
    mv "${INDEX_TMP}" "${INDEX_PATH}"
    echo "  -> index.json a jour."
else
    rm -f "${INDEX_TMP}"
    echo "  [!] Telechargement de index.json a echoue."
    echo "      Le manifest sera vide et les boutons telecharger seront grises."
fi

if [ -f "${INDEX_PATH}" ] && command -v jq >/dev/null 2>&1; then
    echo "[2/6] Telechargement des artefacts manquants..."
    # Extrait toutes les filenames d'artefacts (un par ligne)
    while IFS= read -r FNAME; do
        [ -z "${FNAME}" ] && continue
        DEST="${RELEASES_DIR}/${FNAME}"
        if [ -f "${DEST}" ]; then
            echo "  -> ${FNAME} deja present."
            continue
        fi
        echo "  -> Telechargement ${FNAME}..."
        if curl -fsSL -o "${DEST}.tmp" "${RAW_BASE}/releases/${FNAME}"; then
            mv "${DEST}.tmp" "${DEST}"
            echo "     OK"
        else
            rm -f "${DEST}.tmp"
            echo "     [!] Echec download ${FNAME} (pas grave : artefact marque indisponible cote IHM)."
        fi
    done < <(jq -r '.sdks[].artifacts[]?.filename // empty' "${INDEX_PATH}")

    echo "[3/6] Telechargement des docs manquantes..."
    while IFS= read -r FNAME; do
        [ -z "${FNAME}" ] && continue
        DEST="${DOCS_DIR}/${FNAME}"
        if [ -f "${DEST}" ]; then
            echo "  -> docs/${FNAME} deja present."
            continue
        fi
        echo "  -> Telechargement docs/${FNAME}..."
        if curl -fsSL -o "${DEST}.tmp" "${RAW_BASE}/releases/docs/${FNAME}"; then
            mv "${DEST}.tmp" "${DEST}"
            echo "     OK"
        else
            rm -f "${DEST}.tmp"
            echo "     [!] Echec download docs/${FNAME} (pas grave : doc marquee indisponible)."
        fi
    done < <(jq -r '.sdks[].docs | values[]?' "${INDEX_PATH}")
else
    if ! command -v jq >/dev/null 2>&1; then
        echo "  [!] jq absent — installe-le (apt install jq) pour activer le sync auto."
    fi
fi

# ── 4. Pull + up ─────────────────────────────────────────────────────────────
echo "[4/6] Pull des images..."
docker compose pull

echo "[5/6] Redemarrage des services..."
docker compose up -d --remove-orphans

echo "[6/6] Cleanup + status :"
docker image prune -f >/dev/null
docker compose ps

echo ""
echo "==========================================="
echo "  Refresh OK"
echo "==========================================="
