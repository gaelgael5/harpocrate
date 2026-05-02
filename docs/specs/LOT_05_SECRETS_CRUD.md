# Lot 05 — Secrets CRUD basique

> **Prérequis** : Lots 00, 01, 02, 03, 04.

## Objectif

Permettre de **créer, lister, lire, modifier, supprimer** des secrets dans un wallet, avec leurs tags. Pas encore de placeholder ni de générateur (lot 06).

## Dépendances

- Lots 00-04

## Périmètre

### Inclus

- Endpoints CRUD secrets
- Tags secret (création, liste, modification via PATCH)
- Vérifications de permissions par opération (`read`, `add`, `write`, `remove`)
- Filtres `?tag=`, `?name_contains=`
- Pagination cursor
- Audit log avec `metadata.secret_name`
- Body des endpoints `/secrets` **jamais loggé** (configurer middleware structlog en conséquence)

### Exclus

- Pas de `is_placeholder` exposé fonctionnellement (le champ existe en DB mais on insère toujours `is_placeholder=FALSE` dans ce lot)
- Pas de `generation_descriptor` exposé (lot 06)
- Pas d'API key (lot 08)

## Spécifications fonctionnelles

### `GET /v1/wallets/{id}/secrets`

- **Auth** : JWT, au moins une permission sur le wallet (lecture des métadonnées)
- **Query** : `tag`, `name_contains`, `limit`, `cursor`
- **Réponse** :
```json
{
  "secrets": [
    {
      "id": "uuid",
      "name": "ANTHROPIC_API_KEY",
      "description": "...",
      "tags": ["llm", "prod"],
      "is_placeholder": false,
      "generation_version": 1,
      "linked_secret_id": null,
      "created_at": "...",
      "updated_at": "...",
      "created_by": { "type": "user", "id": "uuid" },
      "updated_by": null
    }
  ],
  "next_cursor": null
}
```
- **Notes** : pas de `encrypted_value` dans la liste (endpoint dédié pour la valeur)

### `GET /v1/wallets/{id}/secrets/{name}`

- **Auth** : JWT, permission `[read]`
- **Réponse** :
```json
{
  "id": "uuid",
  "name": "ANTHROPIC_API_KEY",
  "encrypted_value": "<base64>",
  "encrypted_wallet_key": "<base64 du encrypted_wallet_key du caller>",
  "description": "...",
  "tags": [...],
  "is_placeholder": false,
  "generation_version": 1
}
```
- **Notes** : `encrypted_wallet_key` provient du grant du caller (`wallet_grants.encrypted_wallet_key`), permet au client de tout déchiffrer en un appel.

### `POST /v1/wallets/{id}/secrets`

- **Auth** : JWT, permission `[add]`
- **Body** :
```json
{
  "name": "ANTHROPIC_API_KEY",
  "description": "...",
  "tags": ["llm"],
  "encrypted_value": "<base64>"
}
```
- **Validations** :
  - Nom : non vide, ≤ 255, regex `^[A-Za-z0-9_.-]+$` (caractères safe pour env vars)
  - `encrypted_value` non vide
  - Tags normalisés
  - Pas de duplicata sur `(wallet_id, name)` (409)
- **Réponses** :
  - `201 { "secret_id": "..." }`
  - `409 secret_name_exists`

### `PUT /v1/wallets/{id}/secrets/{name}`

- **Auth** : JWT, permission `[write]`
- **Body** : `{ "encrypted_value": "<base64>" }`
- **Effets** : UPDATE encrypted_value, generation_version++, updated_by_user_id, updated_at
- **Réponses** :
  - `200 { "generation_version": 2 }`
  - `404 secret_not_found`

### `PATCH /v1/wallets/{id}/secrets/{name}`

- **Auth** : JWT, permission `[write]`
- **Body** : `{ "description"?: "...", "tags"?: [...] }`
- **Notes** : ne touche pas à la valeur. Pour modifier la valeur c'est PUT.
- **Réponse** : `200`

### `DELETE /v1/wallets/{id}/secrets/{name}`

- **Auth** : JWT, permission `[remove]`
- **Effets** : DELETE secrets (cascade sur secret_tags)
- **Réponse** : `204`

## Spécifications techniques

### Configuration structlog : exclure les bodies de `/secrets`

Middleware FastAPI qui log les requêtes mais SANS le body sur les paths matchant `/secrets`.

```python
@app.middleware("http")
async def log_request(request: Request, call_next):
    log_body = not request.url.path.endswith("/secrets") \
               and "/secrets/" not in request.url.path
    # ... ne JAMAIS logger request.body() pour ces chemins ...
    response = await call_next(request)
    logger.info(
        "http_request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        body_logged=log_body,
    )
    return response
```

### Helper pour récupérer `encrypted_wallet_key` du caller

```python
# app/db/repositories/wallet_grants.py
async def get_my_encrypted_wallet_key(
    conn: asyncpg.Connection, wallet_id: UUID, user_id: UUID
) -> bytes | None:
    return await conn.fetchval(
        "SELECT encrypted_wallet_key FROM wallet_grants "
        "WHERE wallet_id = $1 AND grantee_user_id = $2",
        wallet_id, user_id,
    )
```

### Format de `encrypted_value`

C'est un blob AES-GCM côté client. Le serveur le voit comme `bytes`. **Le serveur ne valide PAS le format.** Stockage opaque.

Limite raisonnable : `len(encrypted_value) ≤ 5 MB`. Au-delà → 413 Payload Too Large. (Un secret de 5MB est déjà très inhabituel : un certificat fait quelques KB, une clé privée RSA 4096 fait ~3KB.)

### Audit log metadata

Toujours inclure `metadata.secret_name` (en clair, on a accepté que les noms soient visibles côté serveur). Permet de rechercher facilement "qui a touché ANTHROPIC_API_KEY".

```python
await audit.log(
    conn, "secret.read",
    actor_user_id=user.id,
    target_wallet_id=wallet_id,
    target_secret_id=secret_id,
    metadata={"secret_name": secret_name},
)
```

## Critères de succès

1. ✅ POST création secret avec encrypted_value chiffrée côté client (test avec valeur arbitraire base64)
2. ✅ GET liste retourne tous les secrets sans encrypted_value
3. ✅ GET d'un secret retourne encrypted_value + encrypted_wallet_key
4. ✅ Permission `[read]` requise pour GET
5. ✅ Permission `[add]` requise pour POST, échec si nom existe déjà
6. ✅ Permission `[write]` requise pour PUT, generation_version++
7. ✅ Permission `[remove]` requise pour DELETE
8. ✅ User avec uniquement `[read]` ne peut PAS write/add/remove
9. ✅ Filtre tag fonctionne
10. ✅ Body /secrets jamais loggé (vérifier les logs)
11. ✅ Audit log avec secret_name en metadata

## Pièges connus

- **Body NEVER logged** : crucial. Tester explicitement avec un body contenant une "valeur sensible" qu'on cherche dans les logs. Si elle apparaît → bug critique.
- **Caractères dans le nom** : restreindre aux env-var-safe pour éviter les surprises (`/`, `\`, espaces, etc.).
- **`encrypted_value` peut contenir des bytes arbitraires** : utiliser `BYTEA` côté DB et base64 côté API. Pas de `TEXT`.
- **Le `created_by_user_id` ou `created_by_api_key_id` doit toujours être set** : la CHECK constraint au schéma le force. À l'INSERT, mettre l'un ou l'autre selon le type d'auth.
- **`generation_version`** : initialiser à 1 à la création, +1 à chaque PUT.
- **Permission ⊆ caller's permissions** : il n'y a pas de cascade ici (pas de partage), mais s'assurer que les checks sont faits dans le bon ordre (auth → grant → permission).
- **Le retour `GET /secrets/{name}` inclut `encrypted_wallet_key`** : c'est un raccourci pour le client (un seul appel pour avoir tout). Rappel : c'est `wallet_grants.encrypted_wallet_key` du caller, pas une copie globale.

## Tests à écrire

- `test_create_secret_happy_path`
- `test_create_secret_duplicate_name_409`
- `test_create_secret_invalid_name_400`
- `test_list_secrets_no_value`
- `test_get_secret_returns_value_and_wallet_key`
- `test_get_secret_403_without_read`
- `test_put_secret_increments_version`
- `test_delete_secret_cascade_tags`
- `test_filter_by_tag`
- `test_pagination_cursor`
- `test_body_not_logged` : appel avec body contenant marqueur, vérif logs
- `test_audit_log_secret_name_in_metadata`

## Ce qui suit

Le **lot 06** ajoute les placeholders et les générateurs (workflow `populate`, descripteurs JSON).
