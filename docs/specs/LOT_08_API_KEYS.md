# Lot 08 — API keys

> **Prérequis** : Lots 00-07.

## Objectif

Permettre la **création d'API keys** scopées à un wallet, avec un sous-ensemble de permissions héritées de l'owner. Les API keys sont des credentials machine au format `hrp_*` qui peuvent consommer **uniquement les endpoints `/secrets/*`**.

C'est le lot le plus dense en logique sécurité du projet. Lis-le entièrement avant d'implémenter quoi que ce soit.

## Dépendances

- Lots 00-07

## Périmètre

### Inclus

- Endpoints CRUD sur API keys (création, listage, modif metadata, révocation)
- Format de token `hrp_v_id_exp_perms_authsecret_dkey_hmac` complet
- Calcul HMAC-SHA256 côté serveur avec `master_hmac_key_server`
- Validation du token : 4 checks 0-DB (parse, exp, HMAC, perms) + 2 checks DB (lookup + Argon2id verify)
- Cache de validation (api_key_id → True/False) avec TTL 60s
- Cascade : suppression des API keys quand le grant du owner est révoqué (lot 04 update)
- Mise à jour des endpoints `/secrets/*` pour accepter les API keys
- Mise à jour de `GET /v1/wallets` et `GET /v1/wallets/{id}` pour API keys (scope au wallet propre)
- Mise à jour de `GET /v1/audit-log` (API key voit ses propres actions seulement)
- Audit log : `api_key.created`, `api_key.revoked`, `api_key.used` (sur usage normal)

### Exclus

- Pas d'auto-création d'API key (création par autre API key) — interdit au MVP
- Pas de UI (lot 11)
- Pas de SDK (lot 09)

## Spécifications fonctionnelles

### Format du token (rappel)

```
hrp_<v>_<api_key_id>_<exp>_<perms>_<auth_secret>_<decryption_key>_<hmac>
```

| Champ | Format | Encodage | Origine |
|---|---|---|---|
| `hrp` | littéral | — | constant |
| `v` | "1" | — | version courante |
| `api_key_id` | UUID 16 bytes | base32 lowercase sans padding (26 chars) | DB |
| `exp` | timestamp Unix | base36 | calculé à la création |
| `perms` | 1 byte (0..63) | hex 2 chars | header au token |
| `auth_secret` | 32 bytes random | base64url sans padding (43 chars) | client/serveur |
| `decryption_key` | 32 bytes random | base64url sans padding (43 chars) | client |
| `hmac` | 16 bytes | base64url sans padding (22 chars) | serveur |

**Total** : 3 + 1 + 26 + ~7 + 2 + 43 + 43 + 22 + 7 séparateurs = ~155 chars

**Le `decryption_key` n'est PAS dans le calcul HMAC.**

### Calcul du HMAC

```python
message = f"{v}_{api_key_id}_{exp}_{perms}_{auth_secret}".encode()
hmac_full = hmac.new(master_hmac_key_server, message, hashlib.sha256).digest()
hmac_truncated = hmac_full[:16]
hmac_b64 = base64.urlsafe_b64encode(hmac_truncated).rstrip(b"=").decode()
```

### `POST /v1/wallets/{id}/api-keys`

- **Auth** : JWT, permission `[share]`
- **Body** :
```json
{
  "name": "agent-llm-prod",
  "description": "...",
  "permissions": 5,
  "expires_at": "2027-01-01T00:00:00Z",
  "auth_hash": "<base64>",
  "auth_salt": "<base64 16 bytes>",
  "auth_kdf_memory_kb": 65536,
  "auth_kdf_iterations": 3,
  "auth_kdf_parallelism": 4,
  "encrypted_wallet_key": "<base64>",
  "encrypted_decryption_key_for_owner": "<base64>"
}
```
- **Validations** :
  - `permissions ⊆ caller_permissions` sur ce wallet
  - `permissions > 0`
  - `expires_at` futur (ou null = pas d'expiration)
  - Floors KDF respectés
  - `auth_salt` 16 bytes
  - Tous les champs non vides
- **Effets** :
  1. Le client a déjà :
     - Généré `auth_secret = random(32)`
     - Calculé `auth_hash = Argon2id(auth_secret, auth_salt, params)`
     - Généré `decryption_key = random(32)`
     - Récupéré sa wallet_key (déchiffrement de son `wallet_grants.encrypted_wallet_key` via sa rsa_priv)
     - Calculé `encrypted_wallet_key = AES-256-GCM(wallet_key, decryption_key)`
     - Calculé `encrypted_decryption_key_for_owner = RSA-OAEP(decryption_key, rsa_pub_owner)`
  2. Le serveur :
     - Vérifie permissions ⊆ caller permissions
     - Génère `api_key_id = uuid()`
     - Calcule `exp` selon `expires_at` (ou 0 si null)
     - Reçoit `auth_secret` du client (au choix, voir piège ci-dessous)
     - **Décision retenue** : le **client** envoie `auth_secret` ET `auth_hash` au serveur. Le serveur stocke `auth_hash + salt + params`, et reçoit `auth_secret` *uniquement pour calculer le HMAC du token*. Le serveur peut soit jeter `auth_secret` après calcul, soit le ré-encoder dans le token. **Le serveur ne stocke jamais `auth_secret` en clair.**
     - Calcule HMAC sur `(v, id, exp, perms, auth_secret)`
     - Assemble token complet
     - INSERT api_keys
     - Renvoie token au client (one-shot)

**Alternative architecturale (plus propre)** : faire que `auth_secret` ne quitte JAMAIS le client. Le client envoie `auth_hash + salt + params` mais PAS `auth_secret`. Le client demande au serveur le HMAC en lui envoyant uniquement les champs publics (`v, id, exp, perms`) sans `auth_secret`. Mais alors le HMAC ne couvre pas `auth_secret`, et un attaquant qui modifie `auth_secret` dans un token ne casse pas le HMAC, juste le check Argon2id en DB.

→ **Décision MVP** : le `auth_secret` est dans le HMAC, donc le client doit l'envoyer au serveur à la création (sur HTTPS). Le serveur ne le stocke pas, il le passe juste dans le HMAC puis l'oublie. Cohérent avec le fait que le serveur va de toute façon recevoir `auth_secret` à chaque requête future.

- **Réponses** :
  - `201` :
```json
{
  "api_key_id": "uuid",
  "token": "hrp_1_<id>_<exp>_<perms>_<auth_secret>_<dkey>_<hmac>"
}
```
  - `400 permissions_exceed_caller`
  - `400 invalid_expiration`

### `GET /v1/wallets/{id}/api-keys`

- **Auth** : JWT, permission `[share]`
- **Réponse** :
```json
{
  "api_keys": [
    {
      "id": "uuid",
      "name": "...",
      "description": "...",
      "owner_user_id": "uuid",
      "permissions": 5,
      "expires_at": "...",
      "revoked_at": null,
      "last_used_at": "...",
      "created_at": "..."
    }
  ]
}
```
- **Notes** : pas de hash, pas de blob, juste les métadonnées.

### `PATCH /v1/wallets/{id}/api-keys/{api_key_id}`

- **Auth** : JWT, permission `[share]`
- **Body** : `{ "name"?, "description"?, "expires_at"? }`
- **Notes** : on ne peut PAS modifier `permissions` (signées dans le HMAC du token).

### `DELETE /v1/wallets/{id}/api-keys/{api_key_id}`

- **Auth** : JWT, permission `[share]`
- **Effets** : `UPDATE api_keys SET revoked_at = NOW()` (soft delete)
- **Réponse** : `204`

### Middleware d'auth API key

Une nouvelle dependency `require_api_key`. Elle :

1. Parse le token (split par `_`, vérif format)
2. Vérifie `exp > now()` (rejet 401 si expiré)
3. Recalcule HMAC avec les champs publics, compare en constant-time (rejet 401)
4. Vérifie que `perms` contient la permission requise (rejet 403)
5. Lookup api_keys par `id` :
   - Vérif `revoked_at IS NULL` (rejet 401)
   - Vérif `Argon2id(auth_secret, salt, params) == auth_hash` constant-time
6. Vérif que owner a toujours un grant valide sur le wallet (cascade Option 2)
7. UPDATE last_used_at (best-effort, peut être différé via background task)

```python
async def require_api_key(
    authorization: Annotated[str | None, Header()] = None,
    pool: asyncpg.Pool = Depends(get_pool),
) -> ApiKeyAuth:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing_bearer_token")
    token = authorization[7:]
    if not token.startswith("hrp_"):
        raise HTTPException(401, "expected_api_key_token")

    # Parse 0-DB
    parts = token.split("_")
    if len(parts) != 8:
        raise HTTPException(401, "malformed_token")
    _, v, id_b32, exp_b36, perms_hex, auth_secret_b64, dkey_b64, hmac_b64 = parts

    # Version
    if v != "1":
        raise HTTPException(401, "unsupported_token_version")

    # Decode id
    try:
        api_key_id = uuid.UUID(bytes=base64.b32decode((id_b32 + "======").upper()))
        exp = int(exp_b36, 36)
        perms = int(perms_hex, 16)
    except Exception:
        raise HTTPException(401, "malformed_token_fields")

    # Expiration (0 = no expiration)
    if exp != 0 and exp < int(time.time()):
        raise HTTPException(401, "token_expired")

    # HMAC verify
    message = f"{v}_{id_b32}_{exp_b36}_{perms_hex}_{auth_secret_b64}".encode()
    expected = hmac.new(master_key, message, hashlib.sha256).digest()[:16]
    expected_b64 = base64.urlsafe_b64encode(expected).rstrip(b"=").decode()
    if not hmac.compare_digest(expected_b64, hmac_b64):
        raise HTTPException(401, "invalid_signature")

    # DB lookup + Argon2id (avec cache 60s)
    cache_key = f"{api_key_id}:{auth_secret_b64}"
    if cache_key in _validation_cache and _validation_cache[cache_key].expires_at > now:
        api_key_row = _validation_cache[cache_key].row
    else:
        async with pool.acquire() as conn:
            api_key_row = await conn.fetchrow(
                "SELECT * FROM api_keys WHERE id = $1 AND revoked_at IS NULL",
                api_key_id,
            )
            if not api_key_row:
                raise HTTPException(401, "api_key_revoked_or_unknown")

            # Argon2id verify
            from argon2 import PasswordHasher
            ph = PasswordHasher(...)
            try:
                ph.verify(api_key_row["auth_hash"].decode(), base64url_decode(auth_secret_b64))
            except VerifyMismatchError:
                raise HTTPException(401, "invalid_auth_secret")

            _validation_cache[cache_key] = CacheEntry(api_key_row, now + 60)

    # Owner grant check (cascade)
    async with pool.acquire() as conn:
        grant = await conn.fetchrow(
            "SELECT permissions FROM wallet_grants "
            "WHERE wallet_id = $1 AND grantee_user_id = $2",
            api_key_row["wallet_id"], api_key_row["owner_user_id"],
        )
        if not grant:
            raise HTTPException(403, "owner_grant_revoked")
        # Cascade : permissions de l'API key ne peuvent pas excéder celles de l'owner
        if not is_subset(perms, grant["permissions"]):
            raise HTTPException(403, "owner_permissions_reduced")

    # last_used_at (best-effort, async fire-and-forget)
    asyncio.create_task(_update_last_used(api_key_id))

    return ApiKeyAuth(
        api_key_id=api_key_id,
        wallet_id=api_key_row["wallet_id"],
        owner_user_id=api_key_row["owner_user_id"],
        permissions=perms,
        decryption_key_b64=dkey_b64,  # à passer au handler pour le retour
    )
```

### Mise à jour des endpoints existants

Les endpoints `/v1/wallets/{id}/secrets/*` (lots 05, 06) doivent maintenant accepter **soit** JWT **soit** API key.

Approche : créer un dependency `require_any_auth_with_permission(perm)` :

```python
def require_any_auth_with_permission(perm: int):
    async def _check(
        authorization: Annotated[str | None, Header()] = None,
        wallet_id: UUID,
        # ...
    ) -> AuthContext:
        if authorization and authorization.startswith("Bearer hrp_"):
            api_key = await require_api_key(...)
            if api_key.wallet_id != wallet_id:
                raise HTTPException(404, "not_found")  # scope mismatch
            if not has(api_key.permissions, perm):
                raise HTTPException(403, "missing_permission")
            return AuthContext(api_key=api_key)
        else:
            user = await require_jwt_user(authorization)
            grant = await get_grant(...)
            if not has(grant.permissions, perm):
                raise HTTPException(403)
            return AuthContext(user=user, grant=grant)
    return _check
```

### Comportement du endpoint `GET /v1/wallets` avec API key

Une API key ne voit qu'**un seul wallet** : le sien. Le listage retourne une liste à 1 élément :

```python
if isinstance(auth, ApiKeyAuth):
    # SELECT spécifique au wallet de l'API key
    wallet = await get_wallet(auth.wallet_id)
    return {"wallets": [build_wallet_dto(wallet, auth.permissions)], "next_cursor": None}
```

### Comportement de `GET /v1/wallets/{id}` avec API key

- Si `id == auth.wallet_id` → 200
- Sinon → 404 (pas 403, pour éviter de révéler l'existence)

### Endpoints REFUSÉS aux API keys

Liste exhaustive des endpoints qui doivent retourner **401 `api_key_not_allowed_here`** si appelés avec un token `hrp_*` :

- Tous les `/me/*`
- `POST /wallets`
- `PATCH /wallets/{id}`
- `DELETE /wallets/{id}`
- `POST /wallets/{id}/transfer-ownership`
- `GET /wallets/{id}/export`
- `POST /wallets/import`
- Tous les `/grants` endpoints
- `GET /users/lookup`
- Tous les `/api-keys` endpoints
- `GET /v1/audit-log` est ouvert mais filtré (voir lot 10)

Ce check est dans la dependency `require_jwt_user` qui rejette explicitement les tokens `hrp_*`.

### Cascade de révocation

Quand un grant est supprimé (lot 04, `DELETE /grants/{id}`), il faut maintenant aussi :

```sql
DELETE FROM api_keys
WHERE wallet_id = $1 AND owner_user_id = $2
```

Ou via `UPDATE api_keys SET revoked_at = NOW()` pour préserver l'audit. **Décision MVP : DELETE physique** (cohérent avec le hard delete des wallets).

À ajouter au lot 04 (rétroactivement) : ajouter cette suppression dans `DELETE /grants`.

## Critères de succès

1. ✅ Création d'API key avec permissions valides → 201 + token
2. ✅ Token au format `hrp_1_xxx_yyy_05_zzz_www_hhhh`
3. ✅ Permissions demandées > permissions du caller → 400
4. ✅ Token avec HMAC modifié → 401 (sans hit DB)
5. ✅ Token expiré → 401 (sans hit DB)
6. ✅ Token avec `auth_secret` modifié → 401 au check Argon2id (1 hit DB)
7. ✅ Token révoqué → 401 (1 hit DB)
8. ✅ API key accède à `/secrets` du wallet propre → 200
9. ✅ API key tente `/me` → 401
10. ✅ API key tente `POST /wallets` → 401
11. ✅ API key tente d'accéder à un autre wallet → 404
12. ✅ Révocation du grant owner → API keys associées supprimées
13. ✅ Cache de validation : 2e requête avec même token → pas de hit Argon2id (mock)
14. ✅ `last_used_at` mis à jour
15. ✅ Audit log `api_key.created`, `api_key.revoked`

## Pièges connus

- **Ordre des checks ULTRA important** : parse → exp → HMAC → perms (0 DB), puis lookup → Argon2id (DB). Inverser → fuite d'info ou perf catastrophique.
- **Constant-time compare** : utiliser `hmac.compare_digest` partout, jamais `==`.
- **Argon2id verify** : `PasswordHasher().verify()` lève `VerifyMismatchError`. Catcher proprement.
- **Cache de validation** : la clé doit être `(api_key_id, auth_secret)`. Si on cache juste par `api_key_id`, un attaquant qui change l'auth_secret pour un id valide passera le cache. Le HMAC le bloque avant, mais ceinture+bretelles.
- **Cache invalidation** : à la révocation, invalider l'entrée. Sinon TTL 60s peut laisser un token révoqué fonctionnel pendant 1 min.
- **`exp = 0` = pas d'expiration** : convention. Documenter clairement.
- **Encoding base32** vs base64url : on a choisi base32 pour les UUIDs (plus court qu'hex, URL-safe), base64url pour les bytes random (plus dense que base32).
- **`last_used_at` async** : si on bloque la requête sur cet UPDATE, perf dégradée. Utiliser `asyncio.create_task()` fire-and-forget. Acceptable de perdre cette info sous charge.
- **Décodage base32 Python** : `base64.b32decode` exige du padding `=`. Compléter à 40 chars (multiple de 8).
- **HMAC key rotation** : si jamais on change `master_hmac_key_server`, tous les tokens deviennent invalides. Pour une rotation propre, prévoir le champ `version` du token (`v=1` actuel, `v=2` future) qui pointe vers une clé différente. Pas dans MVP mais le format le permet.
- **Body NEVER logged** sur les endpoints de secrets, **ni** le token Authorization en debug logs (jamais).

## Tests à écrire

- `test_create_api_key_returns_token`
- `test_token_format_correct`
- `test_token_hmac_validates_no_db`
- `test_token_expired_no_db_check`
- `test_token_modified_auth_secret_fails_argon`
- `test_token_revoked_fails`
- `test_api_key_scope_to_wallet`
- `test_api_key_cannot_access_other_wallet_404`
- `test_api_key_cannot_access_human_endpoints`
- `test_grant_revocation_cascades_api_keys`
- `test_validation_cache_hit`
- `test_validation_cache_invalidated_on_revoke`
- `test_owner_permissions_reduced_blocks_api_key`
- `test_perms_subset_check`
- `test_last_used_at_updated`

## Ce qui suit

Le **lot 09** apporte le SDK Python et le CLI Bash, avec l'implémentation des générateurs côté client et le déchiffrement complet pour consommer les secrets.
