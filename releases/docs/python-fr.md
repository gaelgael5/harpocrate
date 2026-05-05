# SDK Python

Client Python avec déchiffrement E2E côté client, cache `wallet_key` et 9 générateurs de secrets. Compatible Python 3.10+.

## Installation

```bash
# Depuis le wheel téléchargé
pip install harpocrate-0.4.0-py3-none-any.whl

# Ou directement depuis le vault
pip install https://vault.yoops.org/v1/sdk/python-wheel
```

## Démarrage rapide

```python
from harpocrate import VaultClient

client = VaultClient(
    token="hrpv_1_...",           # clé API créée dans l'interface
    base_url="https://vault.yoops.org",
)

# Lire un secret (déchiffrement côté client)
api_key = client.secrets.get("ANTHROPIC_API_KEY")

# Lire un secret avec path (résout l'ID en interne via lookup)
db_pass = client.secrets.get("/users/no_email/database/postgres")

# Lister les secrets
secrets = client.secrets.list()

# Catalogue des types disponibles (P1.5)
types = client.types.list()

# Peupler un placeholder
client.secrets.populate("DATABASE_PASSWORD")

# Peupler tous les placeholders d'un coup
results = client.secrets.populate_all()
```

## Via variables d'environnement

```bash
export HARPOCRATE_TOKEN="hrpv_1_..."
export HARPOCRATE_URL="https://vault.yoops.org"

python -c "from harpocrate import VaultClient; c = VaultClient(); print(c.secrets.get('MY_SECRET'))"
```

## Permissions requises

Selon les opérations utilisées :

| Opération | Permission |
|---|---|
| `secrets.get(name)` | `[read]` |
| `secrets.list()` | `[read]` |
| `secrets.create(...)` | `[add]` |
| `secrets.put(name, value)` | `[write]` |
| `secrets.delete(name)` | `[remove]` |
| `secrets.populate(name)` | `[init]` |
| `types.list()` / `types.get(uuid)` | aucune (endpoint public) |
