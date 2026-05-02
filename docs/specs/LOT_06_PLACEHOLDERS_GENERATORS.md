# Lot 06 — Placeholders et générateurs

> **Prérequis** : Lots 00-05.

## Objectif

Permettre de **préparer un wallet template** : créer des secrets en placeholder avec un descripteur de génération, puis les peupler ultérieurement (par un client SDK ou par l'UI) via l'endpoint `populate` qui requiert la permission `[init]`.

## Dépendances

- Lots 00-05

## Périmètre

### Inclus

- Endpoint `POST /v1/wallets/{id}/secrets/placeholder`
- Endpoint `POST /v1/wallets/{id}/secrets/{name}/populate`
- Endpoint `GET /v1/wallets/{id}/secrets/{name}/descriptor`
- Validation des `generation_descriptor` (schéma JSON par type)
- Mise à jour du listage : exposer `generation_descriptor`, `is_placeholder`, `linked_secret_id`, compteurs
- Erreur `424 Failed Dependency` sur `GET /secrets/{name}` si placeholder
- `linked_secret_id` : pour les secrets liés (paire clair/hash, public/private)
- Audit log : `secret.placeholder_created`, `secret.populated`

### Exclus

- L'**implémentation des générateurs** côté client (dans le SDK/UI) est **hors scope** de ce lot. Ici on ne fait que **stocker et valider** les descripteurs.
- Pas de SDK Python (lot 09)
- Pas d'UI (lot 11)

## Spécifications fonctionnelles

### Catalogue des descripteurs (validation côté serveur)

Chaque descripteur a un `type` qui détermine son schéma. Le serveur valide la structure mais **n'exécute aucune génération** (ce sera le job du client).

#### `random`

```json
{
  "type": "random",
  "length": 32,
  "charset": "alphanum"
}
```

Validations :
- `length`: int, 8 ≤ length ≤ 1024
- `charset`: enum `["alphanum", "alpha", "numeric", "hex", "base64url", "printable_ascii"]` OR string custom (regex `^[\x20-\x7E]+$`, longueur ≥ 4)

#### `uuid`

```json
{ "type": "uuid", "version": 4 }
```

Validations : `version ∈ {4, 7}`

#### `bytes`

```json
{ "type": "bytes", "length": 32, "encoding": "base64url" }
```

Validations :
- `length`: 1..4096
- `encoding`: `"base64url" | "hex"`

#### `passphrase`

```json
{ "type": "passphrase", "words": 6, "separator": "-", "language": "en" }
```

Validations :
- `words`: 4..16
- `separator`: 1..4 chars (`[\x20-\x7E]+`)
- `language`: `"en" | "fr"` (extensible)

#### `template`

```json
{
  "type": "template",
  "template": "postgresql://{user}:{password}@{host}:5432/{db}",
  "variables": {
    "user": { "literal": "agflow_workflow" },
    "password": { "type": "random", "length": 32, "charset": "alphanum" },
    "host": { "literal": "postgres.home.lan" },
    "db": { "literal": "agflow_workflow" }
  }
}
```

Validations :
- `template`: string contenant des `{name}` placeholders
- Chaque `{name}` doit avoir une entrée dans `variables`
- Chaque `variables[name]` est soit `{ "literal": "..." }`, soit un descripteur récursif (récursion limitée à 1 niveau pour MVP)

#### `rsa_keypair`

```json
{ "type": "rsa_keypair", "key_size": 4096, "format": "pem" }
```

Validations : `key_size ∈ {2048, 3072, 4096}`, `format ∈ {"pem", "openssh"}`

#### `ssh_keypair`

```json
{ "type": "ssh_keypair", "algorithm": "ed25519" }
```

Validations : `algorithm ∈ {"ed25519", "rsa"}`

#### `tls_certificate`

```json
{
  "type": "tls_certificate",
  "common_name": "agent.home.lan",
  "subject_alt_names": ["agent.home.lan"],
  "validity_days": 365,
  "key_size": 2048,
  "self_signed": true
}
```

Validations :
- `common_name`: string non vide
- `subject_alt_names`: array de strings (peut être vide)
- `validity_days`: 1..3650
- `key_size`: 2048 ou 4096
- `self_signed`: doit être `true` au MVP (CA signing en roadmap)

#### `bcrypt_password`

```json
{ "type": "bcrypt_password", "length": 24, "rounds": 12 }
```

Validations :
- `length`: 12..64
- `rounds`: 10..14

### Validation Pydantic

Définir un discriminated union :

```python
from typing import Literal, Annotated, Union
from pydantic import BaseModel, Field

class RandomDescriptor(BaseModel):
    type: Literal["random"]
    length: int = Field(ge=8, le=1024)
    charset: str = "alphanum"

class UuidDescriptor(BaseModel):
    type: Literal["uuid"]
    version: Literal[4, 7] = 4

class BytesDescriptor(BaseModel):
    type: Literal["bytes"]
    length: int = Field(ge=1, le=4096)
    encoding: Literal["base64url", "hex"] = "base64url"

# ... etc pour chaque type ...

GenerationDescriptor = Annotated[
    Union[
        RandomDescriptor, UuidDescriptor, BytesDescriptor,
        PassphraseDescriptor, TemplateDescriptor,
        RsaKeypairDescriptor, SshKeypairDescriptor,
        TlsCertificateDescriptor, BcryptPasswordDescriptor,
    ],
    Field(discriminator="type"),
]
```

### `POST /v1/wallets/{id}/secrets/placeholder`

- **Auth** : JWT, permission `[add]`
- **Body** :
```json
{
  "name": "DB_PASSWORD",
  "description": "...",
  "tags": ["db"],
  "generation_descriptor": { "type": "random", "length": 32, "charset": "alphanum" },
  "linked_secret_id"?: "uuid"
}
```
- **Validations** :
  - Nom non dupliqué
  - `generation_descriptor` valide (Pydantic discriminated union)
  - `linked_secret_id` (optionnel) : doit pointer vers un secret du **même wallet**
- **Effets** : INSERT secrets avec `is_placeholder=TRUE`, `encrypted_value=NULL`, `generation_descriptor=...`
- **Réponse** : `201 { "secret_id": "..." }`

### `POST /v1/wallets/{id}/secrets/{name}/populate`

- **Auth** : JWT, permission `[init]`
- **Body** : `{ "encrypted_value": "<base64>" }`
- **Validations** :
  - Secret existe
  - Secret est un placeholder (`is_placeholder=TRUE`)
  - `encrypted_value` non vide
- **Effets** :
  - UPDATE secrets SET encrypted_value=?, is_placeholder=FALSE, generation_version=generation_version+1, updated_at, updated_by_user_id
- **Réponses** :
  - `200 { "generation_version": 2 }`
  - `409 secret_already_populated` (utiliser PUT avec `[write]`)
  - `404 secret_not_found`

### `GET /v1/wallets/{id}/secrets/{name}/descriptor`

- **Auth** : JWT, permission `[init]` ou `[read]`
- **Réponse** : `200`
```json
{
  "name": "DB_PASSWORD",
  "is_placeholder": true,
  "generation_descriptor": { "type": "random", "length": 32, "charset": "alphanum" },
  "generation_version": 1,
  "linked_secret_id": null
}
```

### `GET /v1/wallets/{id}/secrets/{name}` — comportement avec placeholder

- Si `is_placeholder=TRUE` → `424 Failed Dependency` :
```json
{
  "error": "placeholder_value_missing",
  "message": "Secret has no value yet, populate it first.",
  "details": {
    "name": "DB_PASSWORD",
    "is_placeholder": true,
    "generation_descriptor": {...}
  }
}
```

### Mise à jour de `GET /secrets` (liste)

Le listage expose maintenant `generation_descriptor`, `is_placeholder`, `linked_secret_id`. Filtrage `?is_placeholder=true|false`.

### Mise à jour de `GET /wallets` (liste)

Le compteur `placeholder_secrets_count` reflète maintenant des vraies données.

## Spécifications techniques

### Validation linked_secret_id

```python
# Dans le service de création de placeholder
if body.linked_secret_id:
    linked = await conn.fetchval(
        "SELECT wallet_id FROM secrets WHERE id = $1",
        body.linked_secret_id,
    )
    if linked != wallet_id:
        raise HTTPException(400, "linked_secret_must_be_in_same_wallet")
```

### Validation du descripteur via Pydantic

Le discriminated union de Pydantic v2 valide automatiquement la structure. Les descripteurs invalides (mauvais type, champs hors plage) renvoient 422 avec détails Pydantic.

```python
class CreatePlaceholderBody(BaseModel):
    name: str
    description: str | None = None
    tags: list[str] = []
    generation_descriptor: GenerationDescriptor
    linked_secret_id: UUID | None = None
```

### Stockage du descripteur

JSONB en DB. À l'INSERT, sérialiser via `model_dump()` :

```python
descriptor_json = body.generation_descriptor.model_dump()
await conn.execute(
    """INSERT INTO secrets (..., generation_descriptor, is_placeholder, ...)
       VALUES (..., $X::jsonb, TRUE, ...)""",
    json.dumps(descriptor_json),
    ...,
)
```

## Critères de succès

1. ✅ Création de placeholder avec descripteur valide → 201
2. ✅ Création de placeholder avec descripteur invalide → 422
3. ✅ POST populate sur placeholder → 200, secret valorisé
4. ✅ POST populate sur secret valorisé → 409
5. ✅ PUT (lot 05) sur placeholder → ? (à décider, voir piège)
6. ✅ GET secret valorisé → 200 avec valeur
7. ✅ GET placeholder → 424 avec descripteur dans les détails
8. ✅ GET descriptor seul → 200 (peu importe l'état)
9. ✅ Permission `[init]` requise pour populate, pas `[write]`
10. ✅ Permission `[add]` requise pour création placeholder
11. ✅ User avec `[init]` ne peut PAS write un secret valorisé
12. ✅ User avec `[write]` ne peut PAS populate (PUT échoue sur placeholder)
13. ✅ `linked_secret_id` cross-wallet rejeté
14. ✅ Compteurs `valued_secrets_count` / `placeholder_secrets_count` corrects

## Pièges connus

- **PUT sur placeholder** : doit échouer en 409, **pas** se comporter comme populate. Strictement disjoint. Le serveur regarde `is_placeholder` du secret existant et oriente vers init/write selon le cas.
- **POST `/secrets` (lot 05) sur un nom existant en placeholder** : 409 (le nom existe). L'utilisateur veut sans doute populate, on peut renvoyer un message d'erreur explicite : `"name exists as placeholder, use POST /populate"`.
- **Discriminated union Pydantic** : nécessite Pydantic v2.6+. Vérifier la version.
- **`linked_secret_id`** : on a un index `idx_secrets_linked` mais pas de contrainte CHECK pour le wallet (Postgres ne le supporte pas). Validation **applicative obligatoire**.
- **JSONB**: stocker en JSONB (pas TEXT) pour pouvoir indexer et requêter dessus.
- **Compteurs en SQL** : utiliser `COUNT(*) FILTER (WHERE is_placeholder = TRUE)` pour des compteurs distincts en une seule passe.
- **424 vs 404** : le secret existe mais sa valeur n'est pas disponible. 424 (Failed Dependency) capture exactement ça. Ne pas confondre avec 404.
- **L'audit log de populate** doit indiquer le type de générateur dans metadata (utile pour les stats).

## Exemple de flux complet

```bash
# 1. Créer le wallet (lot 03)
WALLET_ID=$(curl -X POST .../v1/wallets ... | jq -r .wallet_id)

# 2. Créer un placeholder
curl -X POST .../v1/wallets/$WALLET_ID/secrets/placeholder \
  -d '{"name": "DB_PASSWORD", "generation_descriptor": {"type": "random", "length": 32, "charset": "alphanum"}}'

# 3. Lire le descripteur
curl .../v1/wallets/$WALLET_ID/secrets/DB_PASSWORD/descriptor
# → 200 avec descripteur

# 4. Tenter de lire la valeur (placeholder)
curl .../v1/wallets/$WALLET_ID/secrets/DB_PASSWORD
# → 424 avec descripteur

# 5. Populate (avec un encrypted_value chiffré côté client)
curl -X POST .../v1/wallets/$WALLET_ID/secrets/DB_PASSWORD/populate \
  -d '{"encrypted_value": "<base64>"}'
# → 200, generation_version=2

# 6. Lire la valeur
curl .../v1/wallets/$WALLET_ID/secrets/DB_PASSWORD
# → 200 avec encrypted_value
```

## Tests à écrire

- `test_create_placeholder_with_random_descriptor`
- `test_create_placeholder_invalid_descriptor_422`
- `test_populate_placeholder_happy_path`
- `test_populate_already_populated_409`
- `test_populate_requires_init_permission`
- `test_get_placeholder_returns_424`
- `test_get_descriptor_works_for_placeholder_and_valued`
- `test_descriptor_accessible_with_init_permission`
- `test_put_on_placeholder_409`
- `test_linked_secret_must_be_same_wallet`
- `test_counters_correct`
- `test_audit_metadata_includes_generator_type`

## Ce qui suit

Le **lot 07** ajoute l'export et l'import de structures de wallet en JSON.
