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

# ── 3. Pull + up ─────────────────────────────────────────────────────────────
echo "[1/4] Pull des images..."
docker compose pull

echo "[2/4] Redemarrage des services..."
docker compose up -d --remove-orphans

echo "[3/4] Cleanup des images obsoletes..."
docker image prune -f >/dev/null

echo "[4/4] Status :"
docker compose ps

echo ""
echo "==========================================="
echo "  Refresh OK"
echo "==========================================="
