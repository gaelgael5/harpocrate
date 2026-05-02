# Harpocrate — Packages distribuables

Artefacts générés à partir du repo (branche `feat/local-admin-auth`).

## Contenu

| Fichier | Quoi |
|---|---|
| `harpocrate-0.1.0-py3-none-any.whl` | SDK Python (wheel installable via `pip install`) |
| `harpocrate-sdk-0.1.0.tar.gz` | SDK Python (sdist source) |
| `harpocrate-cli-0.1.0.tar.gz` | CLI bash (script `harpocrate-cli` + helper `lib/harpocrate-gen.py`) |

## Installation SDK Python

```bash
pip install harpocrate-0.1.0-py3-none-any.whl
```

Usage minimal :

```python
from harpocrate import VaultClient

client = VaultClient(
    token="hrpv_<ton_token>",
    base_url="https://vault.yoops.org",  # adapte à ton instance
)

# Lire un secret
value = client.get_secret("DATABASE_URL")

# Lister les secrets du wallet de l'API key
secrets = client.list_secrets()

# Peupler tous les placeholders du wallet
client.populate_all()
```

L'entry point CLI Python `harpocrate-gen` est installé en même temps :

```bash
harpocrate-gen --help
harpocrate-gen list --token hrpv_... --base-url https://vault.yoops.org
```

## Installation CLI bash

```bash
tar -xzf harpocrate-cli-0.1.0.tar.gz -C ~/bin
export PATH="$PATH:$HOME/bin"
chmod +x ~/bin/harpocrate-cli

# Pré-requis : pip install harpocrate (pour le helper Python qui fait la crypto)
pip install harpocrate-0.1.0-py3-none-any.whl

# Configuration via env
export HARPOCRATE_TOKEN=hrpv_...
export HARPOCRATE_BASE_URL=https://vault.yoops.org

harpocrate-cli list
harpocrate-cli get DATABASE_URL
harpocrate-cli populate-all
```

## URL d'instance

Cette instance Harpocrate est servie sur l'URL configurée par l'opérateur via la variable
`HARPOCRATE_PUBLIC_URL` côté backend. Pour la connaître depuis l'UI, demande à ton admin
ou consulte la page d'intégration `/integration` (à venir).

## Sécurité

- Le token `hrpv_*` ne doit JAMAIS être commité ni loggé. Il est affiché une seule
  fois lors de la création depuis l'UI Harpocrate (ou via l'API `POST /v1/wallets/{id}/api-keys`).
- Le SDK fait toute la crypto côté client (zero-knowledge). Le serveur ne voit jamais
  les valeurs en clair.

## Versions

- SDK Python : `0.1.0`
- CLI bash : `0.1.0`
- Compatible avec backend Harpocrate `0.1.0`
