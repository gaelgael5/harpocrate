# CLI Bash harpocrate-cli — LOT_09

Script bash mince qui orchestre le helper Python `harpocrate-gen` pour les opérations Vault.

## Installation

### Prérequis

- bash >= 4.0
- `harpocrate-gen` (Python helper du SDK Harpocrate) :

```bash
pip install harpocrate
```

### Sans pip (dev)

```bash
# Le shim cli-bash/lib/harpocrate-gen.py résout automatiquement le SDK depuis sdk-python/
python3 cli-bash/lib/harpocrate-gen.py --help
```

## Configuration

```bash
export HARPOCRATE_TOKEN=hrpv_1_...          # Token API key (requis)
export HARPOCRATE_URL=https://vault.yoops.org  # URL du serveur (requis)
export HARPOCRATE_ALLOW_INSECURE=1          # HTTP autorisé en dev (optionnel)
```

## Usage

```bash
# Lister les secrets
harpocrate-cli list
harpocrate-cli list --placeholder   # placeholders seulement
harpocrate-cli list --valued        # secrets remplis seulement
harpocrate-cli list --json          # sortie JSON

# Lire un secret
harpocrate-cli get ANTHROPIC_API_KEY

# Peupler un placeholder
harpocrate-cli populate DB_PASSWORD

# Peupler tous les placeholders
harpocrate-cli populate-all

# Info API key
harpocrate-cli whoami

# Lire ou générer si placeholder
harpocrate-cli get-or-populate DB_PASSWORD
```

## Options globales

```
--token TOKEN    Token hrpv_* (sinon HARPOCRATE_TOKEN)
--url URL        URL du serveur (sinon HARPOCRATE_URL)
--json           Sortie JSON
--help           Aide
```

## Intégration dans install.sh

```bash
#!/bin/bash
set -euo pipefail

export HARPOCRATE_TOKEN="${HARPOCRATE_TOKEN:?must be set}"
export HARPOCRATE_URL="${HARPOCRATE_URL:-https://vault.yoops.org}"

# 1. Générer tous les secrets manquants
harpocrate-cli populate-all

# 2. Pousser dans Docker Swarm
for name in $(harpocrate-cli list --json | jq -r '.[].name'); do
    value=$(harpocrate-cli get "$name")
    docker secret rm "$name" 2>/dev/null || true
    echo -n "$value" | docker secret create "$name" -
    echo "✓ $name pushed to Swarm"
done
```

## Tests manuels (smoke)

Les tests bash nécessitent un serveur de test (LXC 201).

```bash
export HARPOCRATE_TOKEN=hrpv_1_...
export HARPOCRATE_URL=http://192.168.10.158:8000
export HARPOCRATE_ALLOW_INSECURE=1
bash cli-bash/tests/smoke.sh
```

## Sécurité

- Le token n'est jamais loggé ni écrit dans stdout
- `set -x` est explicitement désactivé dans le script
- HTTPS requis sauf `HARPOCRATE_ALLOW_INSECURE=1`
- Tout le travail crypto est délégué à `harpocrate-gen` (Python)

## Architecture

```
cli-bash/
├── harpocrate-cli         # Script bash principal (orchestrateur)
├── lib/
│   └── harpocrate-gen.py  # Shim Python pour usage sans pip
├── README.md              # Ce fichier
└── tests/
    └── smoke.sh           # Smoke test manuel (requiert serveur live)
```
