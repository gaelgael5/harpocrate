#!/usr/bin/env bash
###############################################################################
# Script 02 : Initialisation de la stack harpocrate dans le LXC
#
# A executer DANS le container LXC (en tant que root).
# Telecharge docker-compose.yml, refresh.sh depuis GitHub ; types embarques inline,
# et cree un .env pret a editer (sauf si .env existe deja).
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
echo "[1/5] Creation des dossiers..."
mkdir -p "${DEPLOY_DIR}/db/init" "${DEPLOY_DIR}/data" "${DEPLOY_DIR}/releases" "${DEPLOY_DIR}/types"
echo "  -> OK"

# ── 2. Fichiers de la stack ───────────────────────────────────────────────────
echo "[2/5] Telechargement de la stack..."

wget -qO "${DEPLOY_DIR}/docker-compose.yml" \
    "${RAW_BASE}/deploy/docker-compose.yml"
echo "  -> docker-compose.yml"

wget -qO "${DEPLOY_DIR}/db/init/01-extensions.sql" \
    "${RAW_BASE}/db/init/01-extensions.sql"
echo "  -> db/init/01-extensions.sql"

wget -qO "${DEPLOY_DIR}/refresh.sh" \
    "${RAW_BASE}/scripts/refresh.sh"
chmod +x "${DEPLOY_DIR}/refresh.sh"
echo "  -> refresh.sh"

# ── 3. Types de secrets (embarques dans ce script) ───────────────────────────
echo "[3/5] Creation des types de secrets..."

mkdir -p "${DEPLOY_DIR}/types/raw"
cat > "${DEPLOY_DIR}/types/raw/meta.json" <<'TYPEEOF'
{"type": "raw", "sous_type": "raw"}
TYPEEOF
cat > "${DEPLOY_DIR}/types/raw/schema_data.json" <<'TYPEEOF'
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "title": "Raw",
  "description": "Valeur libre — cle API, token, mot de passe, chaine de connexion, ou tout texte sensible.",
  "properties": {
    "value": {"type": "string", "title": "Valeur", "minLength": 1}
  },
  "required": ["value"],
  "additionalProperties": false
}
TYPEEOF
cat > "${DEPLOY_DIR}/types/raw/schema_ui.json" <<'TYPEEOF'
{
  "value": {"ui:widget": "password", "ui:options": {"reveal": true, "copyable": true, "rows": 4}},
  "ui:order": ["value"]
}
TYPEEOF
echo "  -> types/raw"

mkdir -p "${DEPLOY_DIR}/types/site_login"
cat > "${DEPLOY_DIR}/types/site_login/meta.json" <<'TYPEEOF'
{"type": "credential", "sous_type": "site_login"}
TYPEEOF
cat > "${DEPLOY_DIR}/types/site_login/schema_data.json" <<'TYPEEOF'
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "title": "Web Login",
  "description": "Identifiants de connexion a un site web ou service en ligne.",
  "properties": {
    "email":    {"type": "string", "title": "Email",             "format": "email"},
    "username": {"type": "string", "title": "Nom d'utilisateur"},
    "password": {"type": "string", "title": "Mot de passe",      "minLength": 1},
    "website":  {"type": "string", "title": "Site web",          "format": "uri"},
    "note":     {"type": "string", "title": "Note"}
  },
  "required": ["password"],
  "additionalProperties": false
}
TYPEEOF
cat > "${DEPLOY_DIR}/types/site_login/schema_ui.json" <<'TYPEEOF'
{
  "ui:order": ["email", "username", "password", "website", "note"],
  "email":    {"ui:options": {"copyable": true}},
  "username": {"ui:options": {"copyable": true}},
  "password": {"ui:widget": "password", "ui:options": {"reveal": true, "copyable": true}},
  "website":  {"ui:options": {"linkable": true}},
  "note":     {"ui:widget": "textarea", "ui:options": {"rows": 4}}
}
TYPEEOF
echo "  -> types/site_login"

# ── 4. Creer apps.json minimal si absent ─────────────────────────────────────
if [ ! -f "${DEPLOY_DIR}/apps.json" ]; then
    echo "[]" > "${DEPLOY_DIR}/apps.json"
    echo "  -> apps.json (vide)"
fi

# ── 5. Initialiser .env (seulement si absent) ─────────────────────────────────
echo "[4/5] Configuration .env..."
if [ -f "${DEPLOY_DIR}/.env" ]; then
    echo "  -> .env existant conserve (pas de telechargement)"
else
    wget -qO "${DEPLOY_DIR}/.env.example" \
        "${RAW_BASE}/deploy/.env.example"
    echo "  -> .env.example"
    cp "${DEPLOY_DIR}/.env.example" "${DEPLOY_DIR}/.env"
    chmod 600 "${DEPLOY_DIR}/.env"
    echo "  -> .env cree depuis .env.example"
fi

echo "[5/5] Verification Docker..."
docker --version 2>/dev/null || echo "  [!] Docker absent — installer via install-docker.sh"
docker compose version 2>/dev/null || true

# ── Resume ────────────────────────────────────────────────────────────────────
echo ""
echo "==========================================="
echo "  Setup OK"
echo "==========================================="
echo ""

if [ ! -s "${DEPLOY_DIR}/.env" ] || grep -q "REPLACE_WITH" "${DEPLOY_DIR}/.env" 2>/dev/null; then
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
fi

echo "  Lancer la stack :"
echo "    cd ${DEPLOY_DIR} && ./refresh.sh"
echo ""
echo ""
