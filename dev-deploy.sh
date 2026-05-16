#!/usr/bin/env bash
#
# dev-deploy.sh — Build local + déploiement Docker pour une instance DEV.
#
# Cible : machine de dev (LXC, VM, poste local) avec Docker installé.
# Le script :
#   1. git pull (ou clone si pas encore fait)
#   2. Crée .env depuis .env.example si absent
#   3. Crée les dossiers data/ pour les volumes Docker (gitignored)
#   4. Build les images locales backend + frontend
#   5. Down + up de la stack via docker-compose-dev.yml
#
# Usage :
#   ./dev-deploy.sh                       # reste sur la branche courante, pull
#   ./dev-deploy.sh feat/ma-branche       # checkout cette branche, puis pull
#   ./dev-deploy.sh --reset               # DESTRUCTIF : down + wipe data/postgres + redeploy
#   ./dev-deploy.sh feat/ma-branche --reset
#
# Le flag --reset force la suppression du data dir Postgres (`data/postgres/`).
# Utile quand le standby a été basebackuppé depuis un master avec un
# POSTGRES_PASSWORD différent, ou pour repartir d'une base fraîche en dev.
# Ne supprime PAS `data/backups/` ni `.env`.
#
# Pour la PROD (pull GHCR, pas de build local), utiliser scripts/refresh.sh.

set -euo pipefail

REPO_URL="${REPO_URL:-git@github.com:gaelgael5/harpocrate.git}"
COMPOSE_FILE="docker-compose-dev.yml"

# Parse args : on accepte un mix « branche optionnelle » + « flags --xxx ».
# Tout ce qui commence par `--` est un flag ; le reste est la branche.
TARGET_BRANCH=""
RESET_DATA=0
for arg in "$@"; do
  case "$arg" in
    --reset)
      RESET_DATA=1
      ;;
    --*)
      echo "✗ Flag inconnu : ${arg}" >&2
      echo "  Flags supportés : --reset" >&2
      exit 1
      ;;
    *)
      if [ -n "$TARGET_BRANCH" ]; then
        echo "✗ Plusieurs branches passées en argument : '${TARGET_BRANCH}' et '${arg}'" >&2
        exit 1
      fi
      TARGET_BRANCH="$arg"
      ;;
  esac
done

# ─── 0) Pré-requis : Docker installé ─────────────────────────────────────────

if ! command -v docker >/dev/null 2>&1; then
  cat >&2 <<'EOF'
✗ Docker n'est pas installé sur ce serveur.

Installer Docker sur Debian/Ubuntu :
    curl -fsSL https://get.docker.com | sh
    sudo systemctl enable --now docker

Ou si tu utilises un LXC Proxmox, le recréer avec le flag --docker :
    bash <(wget -qO- .../create-lxc.sh) <CTID> harpocrate-dev --docker

Puis relancer ./dev-deploy.sh.
EOF
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "✗ Docker Compose v2 manquant (commande 'docker compose' absente)." >&2
  echo "  Installer le plugin compose : sudo apt install docker-compose-plugin" >&2
  exit 1
fi

# ─── 1) Positionnement dans le repo ─────────────────────────────────────────

if [ -d ".git" ]; then
  if [ -n "$TARGET_BRANCH" ]; then
    echo "[1/6] Repo détecté dans $(pwd) — switch vers ${TARGET_BRANCH}..."
    git fetch origin
    git checkout "$TARGET_BRANCH"
    git pull --ff-only origin "$TARGET_BRANCH"
  else
    CURRENT_BRANCH="$(git branch --show-current)"
    echo "[1/6] Repo détecté dans $(pwd) — pull branche courante (${CURRENT_BRANCH})..."
    git pull --ff-only
  fi
else
  APP_DIR="harpocrate"
  if [ -d "$APP_DIR/.git" ]; then
    if [ -n "$TARGET_BRANCH" ]; then
      echo "[1/6] Repo dans ./${APP_DIR} — switch vers ${TARGET_BRANCH}..."
      git -C "$APP_DIR" fetch origin
      git -C "$APP_DIR" checkout "$TARGET_BRANCH"
      git -C "$APP_DIR" pull --ff-only origin "$TARGET_BRANCH"
    else
      CURRENT_BRANCH="$(git -C "$APP_DIR" branch --show-current)"
      echo "[1/6] Repo dans ./${APP_DIR} — pull branche courante (${CURRENT_BRANCH})..."
      git -C "$APP_DIR" pull --ff-only
    fi
  else
    # Premier clone : on demande explicitement une branche cible (sinon
    # on ne sait pas laquelle prendre — pas de "branche courante" possible).
    if [ -z "$TARGET_BRANCH" ]; then
      echo "[1/6] Aucun repo trouvé. Premier clone — précise la branche en argument :"
      echo "      ./dev-deploy.sh main"
      exit 1
    fi
    echo "[1/6] Clone du repo dans ./${APP_DIR} (branche ${TARGET_BRANCH})..."
    git clone --branch "$TARGET_BRANCH" "$REPO_URL" "$APP_DIR"
  fi
  cd "$APP_DIR"
fi

# ─── 2) .env ────────────────────────────────────────────────────────────────

# Génère un secret URL-safe de N chars (base64-derived, sans +/=).
# Utilisable directement dans une URL ou un DSN sans escape.
gen_urlsafe() {
  openssl rand -base64 48 | tr '+/' '-_' | tr -d '=' | head -c "${1:-24}"
}

# Génère une chaîne base64 standard d'exactement N bytes décodés.
# Pour HARPOCRATE_HMAC_KEY (Pydantic Settings la décode → 32 bytes).
gen_b64_bytes() {
  openssl rand -base64 "${1:-32}" | tr -d '\n'
}

# Substitue la valeur d'une clé `KEY=...` dans un .env.
# Délimiteur sed = `#` pour ne pas être gêné par `/` (présent dans base64).
# Les valeurs générées ne contiennent ni `#` ni `&` (caractères spéciaux sed).
set_env_value() {
  local file="$1" key="$2" value="$3"
  sed -i "s#^${key}=.*#${key}=${value}#" "$file"
}

# Détecte l'IPv4 de l'interface eth0. Retourne vide si l'interface n'existe
# pas (ex: serveur où l'interface s'appelle ens18, enp0s3, etc.).
detect_eth0_ip() {
  ip -4 -o addr show dev eth0 2>/dev/null \
    | awk '{print $4}' | cut -d/ -f1 | head -1
}

# Détecte le port HÔTE mappé sur le port 443 (HTTPS) du service frontend.
# Source de vérité = le compose, pas l'image (l'image expose des ports
# internes via Dockerfile EXPOSE — le mapping host n'est défini que par
# le compose ou la CLI `docker run -p`).
#
# Stratégie en cascade :
#   1) Runtime : `docker compose port frontend 443` (si les containers
#      tournent déjà). Source de vérité absolue.
#   2) Compose YAML : grep sur le mapping `"...:NNNN:443"`. Fonctionne
#      avant le up.
#   3) Fallback : 8443 (valeur du compose dev par défaut).
detect_frontend_https_port() {
  local port=""

  # Source 1 : runtime (containers up)
  if docker compose -f "$COMPOSE_FILE" ps -q frontend 2>/dev/null | grep -q .; then
    port=$(docker compose -f "$COMPOSE_FILE" port frontend 443 2>/dev/null \
           | awk -F: '{print $NF}' | head -1)
    if [ -n "$port" ]; then
      echo "$port"
      return
    fi
  fi

  # Source 2 : compose YAML (avant le up)
  port=$(grep -oE '"[0-9.]+:[0-9]+:443"' "$COMPOSE_FILE" 2>/dev/null \
         | head -1 | awk -F: '{print $2}')
  if [ -n "$port" ]; then
    echo "$port"
    return
  fi

  # Fallback
  echo "8443"
}

# Ajoute au .env les clés présentes dans .env.example mais manquantes côté
# local (typiquement : nouvelles variables introduites par un git pull). Les
# valeurs existantes ne sont JAMAIS écrasées — on ajoute seulement les clés
# absentes, avec la valeur par défaut du .env.example. Sans ce sync, une
# nouvelle var Pydantic restera invisible côté container malgré le commit
# repo, jusqu'à ce que l'admin édite manuellement le .env du serveur.
sync_new_vars_from_example() {
  local env_file=".env" example_file=".env.example"
  [ -f "$env_file" ] || return 0
  [ -f "$example_file" ] || return 0
  local added=()
  while IFS= read -r line; do
    case "$line" in
      ''|\#*) continue ;;
    esac
    local key="${line%%=*}"
    [ -z "$key" ] && continue
    if ! grep -qE "^${key}=" "$env_file"; then
      # Premier ajout : on prefixe d'un séparateur lisible.
      if [ ${#added[@]} -eq 0 ]; then
        {
          echo ""
          echo "# Nouvelles variables ajoutées par dev-deploy.sh ($(date -I))"
        } >> "$env_file"
      fi
      echo "$line" >> "$env_file"
      added+=("$key")
    fi
  done < "$example_file"
  if [ ${#added[@]} -gt 0 ]; then
    echo "      + ${#added[@]} nouvelle(s) variable(s) ajoutée(s) au .env :"
    for k in "${added[@]}"; do
      echo "          - ${k}"
    done
  fi
}

if [ ! -f ".env" ]; then
  if [ -f ".env.example" ]; then
    echo "[2/6] .env absent → création depuis .env.example + génération secrets aléatoires"
    cp .env.example .env

    # Secrets auto-générés : tout ce qui PEUT être random sans casser
    # l'usage. Les autres valeurs (KEYCLOAK_*, PUBLIC_URL, listmonk) restent
    # à éditer manuellement par l'admin.
    PG_PASS="$(gen_urlsafe 32)"
    HMAC_KEY="$(gen_b64_bytes 32)"
    ADMIN_PASS="$(gen_urlsafe 24)"

    set_env_value .env "POSTGRES_PASSWORD" "$PG_PASS"
    set_env_value .env "HARPOCRATE_HMAC_KEY" "$HMAC_KEY"
    set_env_value .env "HARPOCRATE_ADMIN_LOCAL_PASSWORD" "$ADMIN_PASS"
    # Active aussi l'admin local par défaut en dev (sinon le password
    # généré ne sert à rien).
    set_env_value .env "HARPOCRATE_ADMIN_LOCAL_ENABLED" "true"

    # PUBLIC_URL : URL externe d'accès au frontend en HTTPS. On résout le
    # port directement depuis le compose (pas hardcodé) — si tu changes le
    # mapping de port côté compose, le script suit automatiquement.
    ETH0_IP="$(detect_eth0_ip)"
    HTTPS_PORT="$(detect_frontend_https_port)"
    if [ -n "$ETH0_IP" ]; then
      PUBLIC_URL="https://${ETH0_IP}:${HTTPS_PORT}"
      set_env_value .env "HARPOCRATE_PUBLIC_URL" "$PUBLIC_URL"
    fi

    # `.env` contient des secrets : restreindre les permissions.
    chmod 600 .env

    echo "      ✓ POSTGRES_PASSWORD            : généré ($(echo -n "$PG_PASS" | wc -c) chars)"
    echo "      ✓ HARPOCRATE_HMAC_KEY          : généré (base64 de 32 bytes)"
    echo "      ✓ HARPOCRATE_ADMIN_LOCAL_PASSWORD : généré ($(echo -n "$ADMIN_PASS" | wc -c) chars)"
    echo "      ✓ HARPOCRATE_ADMIN_LOCAL_ENABLED : true (admin local activé pour le dev)"
    if [ -n "$ETH0_IP" ]; then
      echo "      ✓ HARPOCRATE_PUBLIC_URL        : ${PUBLIC_URL} (IP eth0 détectée)"
    else
      echo "      ⚠  HARPOCRATE_PUBLIC_URL : eth0 non détectée — édite .env manuellement"
    fi
    echo
    echo "      ⚠  Login admin local : admin / ${ADMIN_PASS}"
    echo "         (récupérable plus tard dans .env — chmod 600)"
    echo
    echo "      ⚠  À ÉDITER MANUELLEMENT dans .env si nécessaire :"
    echo "         - HARPOCRATE_KEYCLOAK_URL / REALM / CLIENT_ID  (si auth OIDC)"
    echo "         - HARPOCRATE_LISTMONK_*                         (si envoi mails recovery)"
  else
    echo "[2/6] ⚠  .env absent et .env.example introuvable — config requise pour démarrer"
  fi
else
  echo "[2/6] .env déjà présent (secrets non régénérés)."
  sync_new_vars_from_example
fi

# ─── 3) Dossiers data/ pour volumes Docker (ignorés par .gitignore) ─────────

echo "[3/6] Création des dossiers data/ (gitignored) si absents..."
mkdir -p data/postgres
mkdir -p data/backups
# UID 1001 = user 'harpocrate' dans l'image backend (Dockerfile prod stage).
# Sans ce chown, le container échoue à écrire dans /var/lib/harpocrate/backups.
# `2>/dev/null || true` car en local Windows/MINGW on n'a pas chown utile.
chown -R 1001:1001 data/backups 2>/dev/null || true
# Override password Postgres — fichier optionnel rempli par le wizard pairing
# côté standby. Le bind mount dans docker-compose-dev.yml exige que le fichier
# EXISTE côté hôte (sinon Docker crée un dossier vide à sa place). On le touch
# vide ici ; le backend l'ignore tant qu'il est vide.
[ -f data/db-password-override.txt ] || touch data/db-password-override.txt

# ─── 4) Build images locales ────────────────────────────────────────────────

echo "[4/6] Build de harpocrate-backend:dev..."
docker build -t harpocrate-backend:dev backend/

echo "      Build de harpocrate-frontend:dev..."
docker build -t harpocrate-frontend:dev frontend/

# ─── 5) Stop + cleanup orphelins ────────────────────────────────────────────

echo "[5/6] Arrêt de la stack (incl. orphelins)..."
if [ "$RESET_DATA" = "1" ]; then
  # `down -v` supprime aussi les volumes nommés (au cas où on en aurait
  # ajouté plus tard). Les bind mounts (data/postgres, data/backups) ne sont
  # PAS impactés par -v — on les nettoie explicitement juste après.
  docker compose -f "$COMPOSE_FILE" down -v --remove-orphans || true
else
  docker compose -f "$COMPOSE_FILE" down --remove-orphans || true
fi

# Reset des bind mounts si demandé. On supprime UNIQUEMENT le data dir
# Postgres : les backups (`data/backups`) et le .env sont conservés. Les
# fichiers du data dir Postgres appartiennent à l'uid 999 du conteneur
# (user `postgres`) → on a besoin de root sur l'hôte pour les rm. Fallback
# sudo si rm direct échoue (cas où l'admin lance le script sans root).
if [ "$RESET_DATA" = "1" ]; then
  echo "      ⚠  --reset : suppression de data/postgres (DESTRUCTIF)..."
  if [ -d "data/postgres" ]; then
    rm -rf data/postgres 2>/dev/null || sudo rm -rf data/postgres
  fi
  echo "      ✓ data/postgres supprimé — Postgres se réinitialisera avec POSTGRES_PASSWORD du .env"
fi

# ─── 6) Pull images registry restantes (postgres) puis up ──────────────────

echo "[6/6] Pull images registry (postgres)..."
docker compose -f "$COMPOSE_FILE" pull postgres || true

echo "      Démarrage de la stack..."
docker compose -f "$COMPOSE_FILE" up -d --remove-orphans --pull never

echo
echo "✓ Déploiement DEV terminé. Services :"
docker compose -f "$COMPOSE_FILE" ps
echo
echo "Logs en direct :"
echo "  docker compose -f ${COMPOSE_FILE} logs -f backend"
echo "  docker compose -f ${COMPOSE_FILE} logs -f frontend"
echo

# ─── Affichage final : URL d'accès ──────────────────────────────────────────
# On lit la PUBLIC_URL réelle dans .env (source de vérité). Fallback sur
# l'IP eth0 si elle existe, sinon localhost.
APP_URL=""
if [ -f ".env" ]; then
  APP_URL="$(awk -F'=' '/^HARPOCRATE_PUBLIC_URL=/ {print $2}' .env | tr -d '\r')"
fi
if [ -z "$APP_URL" ]; then
  # À ce stade les containers tournent : detect_frontend_https_port utilise
  # directement `docker compose port` → source de vérité runtime.
  HTTPS_PORT_FINAL="$(detect_frontend_https_port)"
  ETH0_IP_FINAL="$(detect_eth0_ip)"
  if [ -n "$ETH0_IP_FINAL" ]; then
    APP_URL="https://${ETH0_IP_FINAL}:${HTTPS_PORT_FINAL}"
  else
    APP_URL="https://localhost:${HTTPS_PORT_FINAL}"
  fi
fi

cat <<EOF
═════════════════════════════════════════════════════════════════
  → Ouvre dans ton navigateur :   ${APP_URL}
═════════════════════════════════════════════════════════════════
EOF

# ─── Affichage credentials admin local ──────────────────────────────────────
# Si l'admin local est activé dans le .env, on rappelle username + password
# à chaque déploiement. Évite à l'admin d'aller fouiller dans .env quand il
# lance le script depuis une nouvelle session.
if [ -f ".env" ]; then
  ADMIN_ENABLED="$(awk -F'=' '/^HARPOCRATE_ADMIN_LOCAL_ENABLED=/ {print $2}' .env | tr -d '\r')"
  if [ "$ADMIN_ENABLED" = "true" ]; then
    ADMIN_USER="$(awk -F'=' '/^HARPOCRATE_ADMIN_LOCAL_USERNAME=/ {print $2}' .env | tr -d '\r')"
    ADMIN_PWD="$(awk -F'=' '/^HARPOCRATE_ADMIN_LOCAL_PASSWORD=/ {print $2}' .env | tr -d '\r')"
    : "${ADMIN_USER:=admin}"
    cat <<EOF
  → Admin local activé :
      username : ${ADMIN_USER}
      password : ${ADMIN_PWD}
═════════════════════════════════════════════════════════════════
EOF
  fi
fi
