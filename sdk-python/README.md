# Harpocrate SDK Python

Client Python zero-knowledge pour Harpocrate Vault.

## Installation

```bash
pip install harpocrate
```

## Usage rapide

```python
from harpocrate import VaultClient

client = VaultClient(
    token="hrpv_1_...",
    base_url="https://vault.yoops.org",
)

# Lire un secret
value = client.secrets.get("ANTHROPIC_API_KEY")

# Lister les secrets
for secret in client.secrets.list().secrets:
    print(secret.name, "placeholder" if secret.is_placeholder else "valued")

# Peupler tous les placeholders
results = client.secrets.populate_all()
for r in results:
    print(r.name, "OK" if r.success else r.error)
```

## CLI harpocrate-gen

```bash
export HARPOCRATE_TOKEN=hrpv_1_...
export HARPOCRATE_URL=https://vault.yoops.org

harpocrate-gen list
harpocrate-gen get --name ANTHROPIC_API_KEY
harpocrate-gen populate --name DB_PASSWORD
harpocrate-gen populate-all
```
