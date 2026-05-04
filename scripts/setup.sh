#!/usr/bin/env bash
###############################################################################
# Script 02 : Initialisation de la stack harpocrate dans le LXC
#
# A executer DANS le container LXC (en tant que root).
# Telecharge docker-compose.yml + .env.example + refresh.sh depuis GitHub,
# puis cree un .env pret a editer.
#
# Usage depuis l'hote Proxmox :
#   pct exec <CTID> -- bash -c "$(wget -qLO - https://raw.githubusercontent.com/gaelgael5/harpocrate/refs/heads/main/scripts/setup.sh)"
#
# Ou directement dans le container :
#   bash -c "$(wget -qLO - https://raw.githubusercontent.com/gaelgael5/harpocrate/refs/heads/main/scripts/setup.sh)"
###############################################################################
set -euo pipefail

RAW_BASE="https://raw.githubusercontent.com/gaelgael5/harpocrate/refs/heads/main"
DEPLOY_DIR="/opt/harpocrate"

echo "==========================================="
echo "  Setup harpocrate -> ${DEPLOY_DIR}"
echo "==========================================="

# ── 1. Arborescence ──────────────────────────────────────────────────────────
echo "[1/4] Creation des dossiers..."
mkdir -p "${DEPLOY_DIR}/db/init" "${DEPLOY_DIR}/data" "${DEPLOY_DIR}/releases"
echo "  -> OK"

# ── 2. Telecharger les fichiers de la stack ───────────────────────────────────
echo "[2/4] Telechargement des fichiers..."

wget -qO "${DEPLOY_DIR}/docker-compose.yml" \
    "${RAW_BASE}/docker-compose-prod.yml"
echo "  -> docker-compose.yml"

wget -qO "${DEPLOY_DIR}/.env.example" \
    "${RAW_BASE}/deploy/.env.example"
echo "  -> .env.example"

wget -qO "${DEPLOY_DIR}/db/init/01-extensions.sql" \
    "${RAW_BASE}/db/init/01-extensions.sql"
echo "  -> db/init/01-extensions.sql"

wget -qO "${DEPLOY_DIR}/refresh.sh" \
    "${RAW_BASE}/scripts/refresh.sh"
chmod +x "${DEPLOY_DIR}/refresh.sh"
echo "  -> refresh.sh"

# ── 3. Creer apps.json minimal si absent ─────────────────────────────────────
if [ ! -f "${DEPLOY_DIR}/apps.json" ]; then
    echo "[]" > "${DEPLOY_DIR}/apps.json"
    echo "  -> apps.json (vide)"
fi

# ── 4. Initialiser .env ──────────────────────────────────────────────────────
echo "[3/4] Initialisation du .env..."
if [ -f "${DEPLOY_DIR}/.env" ]; then
    echo "  -> .env existant conserve"
else
    cp "${DEPLOY_DIR}/.env.example" "${DEPLOY_DIR}/.env"
    chmod 600 "${DEPLOY_DIR}/.env"
    echo "  -> .env cree depuis .env.example"
fi

echo "[4/4] Verification Docker..."
docker --version 2>/dev/null || echo "  [!] Docker absent — installer via install-docker.sh"
docker compose version 2>/dev/null || true

# ── Resume ────────────────────────────────────────────────────────────────────
echo ""
echo "==========================================="
echo "  Setup OK"
echo "==========================================="
echo ""
echo "  PROCHAINE ETAPE : editer ${DEPLOY_DIR}/.env"
echo ""
echo "  Champs obligatoires :"
echo "    POSTGRES_PASSWORD  — mot de passe base de donnees"
echo "    HARPOCRATE_HMAC_KEY — cle HMAC (base64 32 octets)"
echo "      openssl rand -base64 32"
echo "    HARPOCRATE_PUBLIC_URL — URL publique du vault"
echo ""
echo "  Auth locale (sans Keycloak) :"
echo "    HARPOCRATE_ADMIN_LOCAL_ENABLED=true"
echo "    HARPOCRATE_ADMIN_LOCAL_USERNAME=admin"
echo "    HARPOCRATE_ADMIN_LOCAL_PASSWORD=..."
echo ""
echo "  Puis lancer :"
echo "    cd ${DEPLOY_DIR} && ./refresh.sh"
echo ""
