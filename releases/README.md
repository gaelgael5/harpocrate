# Harpocrate — Packages distribuables

Catalogue des SDK affiché par la page Intégration (`/integration`), décrit par
`index.json`. Un SDK publié sur le registre officiel de son langage n'y figure plus que
par sa déclaration `registry` : on l'installe depuis ce registre, pas depuis ce dossier.

## Contenu

| SDK | Où l'obtenir |
|---|---|
| SDK Python | [PyPI](https://pypi.org/project/harpocrate/) — `pip install harpocrate` / `uv add harpocrate` (publication : `sdk-python/RELEASING.md`) |
| CLI bash | `harpocrate-cli-<version>.tar.gz` ici (script `harpocrate-cli` + helper `lib/harpocrate-gen.py`) |

Les fichiers `harpocrate-*.whl` encore présents ici sont les anciennes livraisons du SDK
Python ; ils ne sont plus proposés par la page Intégration et seront retirés.

## Installation SDK Python

```bash
pip install harpocrate
# ou
uv add harpocrate
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

# Pré-requis : le SDK Python (pour le helper qui fait la crypto)
pip install harpocrate

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

Les versions courantes sont celles déclarées dans `index.json` (et, pour le SDK Python,
celle publiée sur PyPI).
