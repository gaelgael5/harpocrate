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

RAW_BASE="https://raw.githubusercontent.com/gaelgael5/harpocrate/refs/heads/main"

# ── 4. Sync des fichiers de déploiement (docker-compose.yml, apps.json) ──────
# Sans ça, les modifs côté repo (nouveaux volumes, env vars, healthchecks…)
# ne se propagent jamais au LXC. Backup automatique avant overwrite pour
# préserver d'éventuelles customisations locales (le user peut les retrouver
# dans les .bak.<timestamp>).
sync_repo_file() {
    local local_path="$1"
    local remote_url="$2"
    local tmp="${local_path}.new"
    # Cache-busting GitHub raw (Fastly cache TTL 5 min) : on ajoute un
    # query string unique pour forcer un fetch frais sans risquer de tomber
    # sur une edge node qui sert encore l'ancien contenu.
    local cb="?cb=$(date +%s%N 2>/dev/null || date +%s)"
    if ! curl -fsSL -o "${tmp}" "${remote_url}${cb}"; then
        rm -f "${tmp}"
        echo "  [!] Echec download $(basename "${local_path}") — version locale conservée."
        return 0
    fi
    if [ -f "${local_path}" ] && cmp -s "${tmp}" "${local_path}"; then
        rm -f "${tmp}"
        echo "  -> $(basename "${local_path}") déjà à jour."
        return 0
    fi
    if [ -f "${local_path}" ]; then
        local backup="${local_path}.bak.$(date +%Y%m%d-%H%M%S)"
        cp "${local_path}" "${backup}"
        echo "  -> Mise à jour $(basename "${local_path}") (ancien : $(basename "${backup}"))"
    else
        echo "  -> Création $(basename "${local_path}")"
    fi
    mv "${tmp}" "${local_path}"
}

echo "[*] Sync des fichiers de déploiement..."
sync_repo_file "$(pwd)/docker-compose.yml" "${RAW_BASE}/docker-compose.yml"
sync_repo_file "$(pwd)/apps.json" "${RAW_BASE}/apps.json"
# Configs des collecteurs d'observabilité, montées par docker-compose.yml.
mkdir -p "$(pwd)/alloy"
sync_repo_file "$(pwd)/alloy/collector.alloy" "${RAW_BASE}/infra/alloy-collector/config.alloy"
sync_repo_file "$(pwd)/alloy/metrics.alloy" "${RAW_BASE}/infra/alloy-metrics/config.alloy"

# Auto-update du script lui-même : si refresh.sh distant diffère, on remplace
# et on relance pour que les changements (nouvelles étapes, fonctions) soient
# pris en compte immédiatement. La var REFRESH_SELF_UPDATED évite la boucle.
if [ -z "${REFRESH_SELF_UPDATED:-}" ]; then
    SELF_PATH="$(pwd)/refresh.sh"
    SELF_TMP="${SELF_PATH}.new"
    SELF_CB="?cb=$(date +%s%N 2>/dev/null || date +%s)"
    if curl -fsSL -o "${SELF_TMP}" "${RAW_BASE}/scripts/refresh.sh${SELF_CB}"; then
        if ! cmp -s "${SELF_TMP}" "${SELF_PATH}"; then
            backup="${SELF_PATH}.bak.$(date +%Y%m%d-%H%M%S)"
            cp "${SELF_PATH}" "${backup}"
            echo "[*] refresh.sh distant a changé — mise à jour + relance"
            echo "    (ancien : $(basename "${backup}"))"
            chmod +x "${SELF_TMP}"
            mv "${SELF_TMP}" "${SELF_PATH}"
            export REFRESH_SELF_UPDATED=1
            exec "${SELF_PATH}" "$@"
        fi
        rm -f "${SELF_TMP}"
    else
        rm -f "${SELF_TMP}"
    fi
fi

# ── Observabilité : compléter .env sans jamais écraser ───────────────────────
# Standard « Gestion des logs » : un Alloy par hôte, sinon l'hôte est un angle
# mort (incident rag du 2026-10-20, indiagnosticable faute de journaux). Les
# collecteurs sont dans docker-compose.yml (profil `observability`). Une clé
# déjà présente dans .env n'est JAMAIS modifiée : l'opérateur garde la main.
# Défauts : la stack Loki/VictoriaMetrics du portail, celle que lit l'outil MCP
# `logs_query` — et non l'ancienne stack 192.168.10.110 de infra/alloy-agent/.
ensure_env_default() {
    local key="$1" value="$2"
    if ! grep -qE "^${key}=" .env; then
        # Un .env sans fin de ligne finale collerait la clé à la dernière valeur.
        if [ -n "$(tail -c1 .env)" ]; then echo >> .env; fi
        if [ -z "${OBS_ENV_HEADER_WRITTEN:-}" ]; then
            printf '\n# Observabilité (ajouté par refresh.sh le %s)\n' "$(date +%F)" >> .env
            OBS_ENV_HEADER_WRITTEN=1
        fi
        printf '%s=%s\n' "${key}" "${value}" >> .env
        echo "  -> .env : ${key} ajouté (${value})"
    fi
}

echo "[1/8] Configuration de l'observabilité..."
ensure_env_default LOKI_URL "http://192.168.10.164:3100/loki/api/v1/push"
ensure_env_default METRICS_URL "http://192.168.10.164:8428/api/v1/write"
ensure_env_default ALLOY_HOSTNAME "$(hostname)"
ensure_env_default ALLOY_ROLE "prod"
# Profil des collecteurs : sans lui, `docker compose up` ne les démarre pas.
export COMPOSE_PROFILES=observability

# ── 5. Sync releases/ depuis le repo Git (index.json + artefacts + docs) ─────
RELEASES_DIR="$(pwd)/releases"
DOCS_DIR="${RELEASES_DIR}/docs"
mkdir -p "${DOCS_DIR}"

echo "[2/8] Sync releases/index.json depuis ${RAW_BASE}..."
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
    echo "[3/8] Telechargement des artefacts manquants..."
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

    # Les docs, contrairement aux artefacts, ne portent pas de version dans leur nom
    # (python-fr.md…) : les sauter quand elles existent les figeait pour toujours
    # (constate le 2026-10-05, page Integration restee sur l'ancienne doc). Elles sont
    # donc retelechargees a chaque passage ; en cas d'echec, la version en place reste.
    echo "[4/8] Mise a jour des docs..."
    while IFS= read -r FNAME; do
        [ -z "${FNAME}" ] && continue
        DEST="${DOCS_DIR}/${FNAME}"
        if curl -fsSL -o "${DEST}.tmp" "${RAW_BASE}/releases/docs/${FNAME}"; then
            mv "${DEST}.tmp" "${DEST}"
            echo "  -> docs/${FNAME} a jour."
        else
            rm -f "${DEST}.tmp"
            if [ -f "${DEST}" ]; then
                echo "  [!] Echec download docs/${FNAME} : version en place conservee."
            else
                echo "  [!] Echec download docs/${FNAME} (pas grave : doc marquee indisponible)."
            fi
        fi
    done < <(jq -r '.sdks[].docs | values[]?' "${INDEX_PATH}")
else
    if ! command -v jq >/dev/null 2>&1; then
        echo "  [!] jq absent — installe-le (apt install jq) pour activer le sync auto."
    fi
fi

# ── 4. Pull + up ─────────────────────────────────────────────────────────────
echo "[5/8] Pull des images..."
docker compose pull

echo "[6/8] Redemarrage des services..."
docker compose up -d --remove-orphans

# Un collecteur arrêté ne produit aucune erreur, il ne produit rien : on le
# constate ici plutôt qu'au prochain incident. Pas d'échec du refresh pour
# autant — l'application, elle, est à jour et doit rester servie.
echo "[7/8] Vérification des collecteurs d'observabilité..."
running="$(docker compose ps --status running --services 2>/dev/null || true)"
for svc in alloy-collector alloy-metrics; do
    if printf '%s\n' "${running}" | grep -qx "${svc}"; then
        echo "  -> ${svc} en marche."
    else
        echo "  [!] ${svc} NE TOURNE PAS : journaux/métriques de cet hôte absents."
        echo "      Diagnostic : docker compose logs --tail 50 ${svc}"
    fi
done

echo "[8/8] Cleanup + status :"
docker image prune -f >/dev/null
docker compose ps

echo ""
echo "==========================================="
echo "  Refresh OK"
echo "==========================================="
