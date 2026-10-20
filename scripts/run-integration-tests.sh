#!/usr/bin/env bash
# Tests backend COMPLETS (intégration comprise) contre une base PostgreSQL jetable.
#
# Sans HARPOCRATE_DB_DSN_TEST, les tests d'intégration sont sautés — dont ceux des
# routes `connect`, qui auraient vu l'incident rag du 2026-10-20 (JWK à `null`).
# À lancer sur une machine de test (Docker requis), depuis un clone du dépôt :
#   scripts/run-integration-tests.sh "$PWD" [args pytest…]
# La base (postgres:16-alpine + db/init, comme la stack) est créée, migrée par
# migrations/apply_migrations.py, puis détruite en sortie, même en cas d'échec.
# Le mot de passe est aléatoire et ne quitte pas la machine.
# Usage : run-db-tests.sh <chemin du dépôt> [args pytest...]
set -euo pipefail
REPO="$1"; shift
NAME="harpocrate-testdb-$$"
NET="harpocrate-testnet-$$"
PW="$(head -c 18 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')"
cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker network create "$NET" >/dev/null
docker run -d --name "$NAME" --network "$NET" \
  --label projet=harpocrate --label usage=tests-jetables \
  -v "${REPO}/db/init:/docker-entrypoint-initdb.d:ro" \
  -e POSTGRES_USER=harpo -e POSTGRES_PASSWORD="$PW" -e POSTGRES_DB=harpocrate_test \
  postgres:16-alpine >/dev/null
for _ in $(seq 1 60); do
  # -h 127.0.0.1 : le serveur temporaire des scripts d'init n'écoute que sur le
  # socket ; seul le serveur définitif répond en TCP.
  docker exec "$NAME" pg_isready -h 127.0.0.1 -U harpo -d harpocrate_test >/dev/null 2>&1 && break
  sleep 1
done

DSN="postgresql://harpo:${PW}@${NAME}:5432/harpocrate_test"
docker run --rm --network "$NET" \
  -v "${REPO}/backend:/src:ro" \
  -e HARPOCRATE_DB_DSN="$DSN" -e HARPOCRATE_DB_DSN_TEST="$DSN" \
  -e UV_PROJECT_ENVIRONMENT=/venv -e UV_LINK_MODE=copy \
  ghcr.io/astral-sh/uv:python3.12-bookworm-slim \
  bash -c 'cp -r /src /work && cd /work && uv sync --frozen --extra dev -q && \
    uv run python -c "import asyncio, tests.conftest; from migrations.apply_migrations import apply_migrations; asyncio.run(apply_migrations())" \
    && uv run pytest -q -p no:cacheprovider "$@"' _ "$@"
