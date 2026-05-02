#!/usr/bin/env bash
# Smoke test du CLI harpocrate-cli — LOT_09
#
# Nécessite un serveur Vault de test (LXC 201) et une API key valide.
#
# Usage :
#   export HARPOCRATE_TOKEN=hrpv_1_...
#   export HARPOCRATE_URL=http://192.168.10.158:8000  # ou HTTPS en prod
#   export HARPOCRATE_ALLOW_INSECURE=1  # pour dev HTTP
#   bash cli-bash/tests/smoke.sh
#
# Ce test est MANUEL — il n'est pas exécuté en CI sans serveur.
# Il documente le workflow complet d'un install.sh type.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLI="${SCRIPT_DIR}/../harpocrate-cli"

# Vérifications préliminaires
if [[ -z "${HARPOCRATE_TOKEN:-}" ]]; then
    echo "SKIP: HARPOCRATE_TOKEN not set — smoke test requires a live server"
    exit 0
fi

if [[ -z "${HARPOCRATE_URL:-}" ]]; then
    echo "SKIP: HARPOCRATE_URL not set — smoke test requires a live server"
    exit 0
fi

echo "=== Smoke test: harpocrate-cli ==="
echo "URL: ${HARPOCRATE_URL}"
echo "Token: hrpv_******* (masked)"
echo ""

# Test 1: whoami
echo "--- whoami ---"
"${CLI}" whoami
echo ""

# Test 2: list
echo "--- list ---"
"${CLI}" list
echo ""

# Test 3: list --json
echo "--- list --json ---"
"${CLI}" list --json | python3 -m json.tool || true
echo ""

# Test 4: populate-all
echo "--- populate-all ---"
"${CLI}" populate-all
echo ""

# Test 5: get (pour chaque secret valorisé)
echo "--- get secrets ---"
for name in $("${CLI}" list --valued --json | python3 -c "
import sys, json
data = json.load(sys.stdin)
for s in data:
    print(s['name'])
" 2>/dev/null || true); do
    echo -n "${name}: "
    "${CLI}" get "${name}" | head -c 20
    echo "..."
done
echo ""

echo "=== Smoke test PASSED ==="
