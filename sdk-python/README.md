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

## Détection de rotation (LOT_22, ≥ 0.5.0)

Quand un secret est rotaté côté Harpocrate, l'application qui consomme ce
secret détecte typiquement l'expiration via une réponse 401 de l'API tierce
(Anthropic, OpenAI, etc.). Le SDK fournit un mécanisme déclaratif pour gérer
ce cas :

```python
from harpocrate import VaultClient

client = VaultClient(token="hrpv_...", base_url="https://vault.yoops.org")

# 1. Enregistrer un callback pour un secret nommé
@client.on_auth_error("anthropic_api_key")
async def on_anthropic_rotated(new_value: str) -> None:
    anthropic_client.api_key = new_value

# 2. Filet de sécurité : callback pour TOUS les secrets
@client.on_any_auth_error
async def log_any_rotation(name: str, new_value: str) -> None:
    logger.warning("secret rotated: %s", name)

# 3. Quand l'app détecte un 401 sur un appel utilisant le secret :
async def call_anthropic(prompt: str) -> str:
    key = client.secrets.get("anthropic_api_key")
    try:
        return await anthropic.complete(prompt, api_key=key)
    except anthropic.AuthenticationError:
        # Le SDK refait un GET forcé, déchiffre, appelle les callbacks
        new_key = await client.notify_auth_error("anthropic_api_key")
        return await anthropic.complete(prompt, api_key=new_key)
```

### Context manager (sucre syntaxique)

```python
async with client.using_secret("anthropic_api_key") as get_value:
    key = await get_value()
    try:
        return await anthropic.complete(prompt, api_key=key)
    except anthropic.AuthenticationError:
        key = await get_value(retry=True)  # force_refresh + callbacks
        return await anthropic.complete(prompt, api_key=key)
```

### Force refresh ponctuel

```python
# Invalide le cache wallet_key local et refait un GET
new_value = client.secrets.get("anthropic_api_key", force_refresh=True)
```

### Exceptions

- `SecretRefreshFailed` : le refresh a échoué (secret supprimé, API key révoquée)

## Se connecter avec Harpocrate (≥ 0.8.0)

Pour qu'une application obtienne une API key sans copier-coller : l'application doit
être déclarée par un admin Harpocrate (registre des applications, URL de retour exacte).

```python
from harpocrate import connect

# Backend de l'application, au clic sur « Connecter » :
browser_url, pending = connect.start(
    base_url="https://vault.example",
    client_id="ragflow",
    redirect_uri="https://rag.example/harpocrate/callback",
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

Le code de retour vaut 60 s et ne s'échange qu'une fois ; la demande vaut 15 min.

## CLI harpocrate-gen

```bash
export HARPOCRATE_TOKEN=hrpv_1_...
export HARPOCRATE_URL=https://vault.yoops.org

harpocrate-gen list
harpocrate-gen get --name ANTHROPIC_API_KEY
harpocrate-gen populate --name DB_PASSWORD
harpocrate-gen populate-all
```
