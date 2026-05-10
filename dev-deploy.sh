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
#
# Pour la PROD (pull GHCR, pas de build local), utiliser scripts/refresh.sh.

set -euo pipefail

REPO_URL="${REPO_URL:-git@github.com:gaelgael5/harpocrate.git}"
COMPOSE_FILE="docker-compose-dev.yml"

# Branche cible : argument positionnel optionnel. Si absent, on reste sur la
# branche courante du repo (pas de switch automatique).
TARGET_BRANCH="${1:-}"

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

if [ ! -f ".env" ]; then
  if [ -f ".env.example" ]; then
    echo "[2/6] .env absent → création depuis .env.example"
    cp .env.example .env
    echo "      ⚠  Édite .env pour configurer HARPOCRATE_HMAC_KEY, POSTGRES_PASSWORD, etc."
  else
    echo "[2/6] ⚠  .env absent et .env.example introuvable — config requise pour démarrer"
  fi
else
  echo "[2/6] .env déjà présent."
fi

# ─── 3) Dossiers data/ pour volumes Docker (ignorés par .gitignore) ─────────

echo "[3/6] Création des dossiers data/ (gitignored) si absents..."
mkdir -p data/postgres
mkdir -p data/backups
# UID 1001 = user 'harpocrate' dans l'image backend (Dockerfile prod stage).
# Sans ce chown, le container échoue à écrire dans /var/lib/harpocrate/backups.
# `2>/dev/null || true` car en local Windows/MINGW on n'a pas chown utile.
chown -R 1001:1001 data/backups 2>/dev/null || true

# ─── 4) Build images locales ────────────────────────────────────────────────

echo "[4/6] Build de harpocrate-backend:dev..."
docker build -t harpocrate-backend:dev backend/

echo "      Build de harpocrate-frontend:dev..."
docker build -t harpocrate-frontend:dev frontend/

# ─── 5) Stop + cleanup orphelins ────────────────────────────────────────────

echo "[5/6] Arrêt de la stack (incl. orphelins)..."
docker compose -f "$COMPOSE_FILE" down --remove-orphans || true

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
