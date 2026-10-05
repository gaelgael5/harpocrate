# SDK Python

Client Python avec déchiffrement E2E côté client, cache `wallet_key` et 9 générateurs de secrets. Compatible Python 3.10+.

## Installation

```bash
# Depuis le wheel téléchargé
pip install harpocrate-0.8.0-py3-none-any.whl

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

## Se connecter avec Harpocrate (≥ 0.8.0)

Pour qu'une **application** obtienne une API key sans copier-coller : l'utilisateur clique « Connecter à Harpocrate », choisit (ou crée) son wallet dans Harpocrate, et revient dans l'application avec la clé. L'application doit être **déclarée** par un admin Harpocrate (écran « Applications connectées » : `client_id`, URLs de retour exactes).

```python
from harpocrate import ConnectError, connect

# Backend de l'application, au clic sur « Connecter » :
browser_url, pending = connect.start(
    base_url="https://vault.yoops.org",
    client_id="mon-app",
    redirect_uri="https://mon-app.example/harpocrate/callback",
    permissions=0x01,  # read
    ttl_days=90,
)
session["harpocrate_connect"] = pending.to_dict()  # côté serveur uniquement
# → rediriger le navigateur vers browser_url

# Sur redirect_uri :
if "error" in request.args:  # access_denied : l'utilisateur a refusé
    ...
pending = connect.ConnectState.from_dict(session.pop("harpocrate_connect"))
result = connect.finish(pending, code=request.args["code"], state=request.args["state"])
# result.token : API key complète, à chiffrer au repos ; result.wallet_id, result.api_key_id
```

- `ConnectState` contient le `code_verifier` et une clé privée éphémère : à garder **côté serveur** (session), jamais dans un cookie lisible ni dans l'URL. Le `state` doit être lié à la session de l'utilisateur.
- Le code de retour vaut 60 s et ne s'échange qu'une fois ; la demande vaut 15 min.
- Erreurs : `ConnectError` (attribut `error_code` : `state_mismatch`, `invalid_grant`, `invalid_seal`, `invalid_client`, `invalid_redirect_uri`…).
- Contrat : `GET /v1/openapi-connect.json`.

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
