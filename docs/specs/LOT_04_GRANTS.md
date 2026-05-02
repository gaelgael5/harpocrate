# Lot 04 — Grants (partage entre utilisateurs)

> **Prérequis** : Lots 00, 01, 02, 03.

## Objectif

Permettre à un utilisateur avec la permission `[share]` (typiquement l'owner) de **partager un wallet** avec un autre utilisateur, gérer les permissions accordées, révoquer.

## Dépendances

- Lots 00-03

## Périmètre

### Inclus

- Endpoints `GET /v1/wallets/{id}/grants`, `POST`, `PATCH /grants/{grant_id}`, `DELETE /grants/{grant_id}`
- Vérifications strictes :
  - Permissions accordées ⊆ permissions du caller
  - Caller a `[share]` ou est owner
  - Grant de l'owner immutable (DELETE et UPDATE refusés)
  - Caller ne peut pas `share` à lui-même (pas de duplicata)
- Audit log : `grant.created`, `grant.modified`, `grant.revoked`

### Exclus

- Pas de cascade des API keys au lot 04 (les API keys n'existent pas encore)
- Pas de gestion des secrets

## Spécifications fonctionnelles

### `GET /v1/wallets/{id}/grants`

- **Auth** : JWT, permission `[share]` ou owner
- **Réponse** :
```json
{
  "grants": [
    {
      "id": "uuid",
      "grantee_user_id": "uuid",
      "grantee_email": "bob@example.com",
      "grantee_display_name": "Bob",
      "permissions": 5,
      "is_owner": false,
      "granted_by_user_id": "uuid",
      "granted_at": "..."
    }
  ]
}
```
- L'owner est inclus dans la liste avec `is_owner: true`.

### `POST /v1/wallets/{id}/grants`

- **Auth** : JWT, permission `[share]` ou owner
- **Body** :
```json
{
  "grantee_user_id": "uuid",
  "encrypted_wallet_key_for_grantee": "<base64>",
  "permissions": 5
}
```
- **Validations** :
  - `grantee_user_id` existe (404 sinon)
  - `permissions ∈ [1, 63]`
  - `permissions ⊆ caller_permissions` (en bitwise : `permissions & caller_permissions == permissions`)
  - Pas déjà grantee (409 sinon, utiliser PATCH)
  - Pas de share à soi-même (400)
- **Effets** : INSERT wallet_grants avec `granted_by_user_id = caller`
- **Réponses** :
  - `201 { "grant_id": "..." }`
  - `404 grantee_not_found`
  - `400 permissions_exceed_caller`
  - `400 cannot_share_with_self`
  - `409 grant_exists`

### `PATCH /v1/wallets/{id}/grants/{grant_id}`

- **Auth** : JWT, permission `[share]` ou owner
- **Body** :
```json
{
  "permissions": 7,
  "encrypted_wallet_key_for_grantee"?: "<base64>"
}
```
- **Validations** :
  - Le grant existe et appartient à ce wallet
  - Le grantee n'est pas l'owner (le trigger DB le bloque, mais erreur applicative claire avant)
  - `permissions ⊆ caller_permissions`
  - Si `encrypted_wallet_key_for_grantee` est fourni (rotation de clé), update du blob
- **Réponses** :
  - `200`
  - `403 cannot_modify_owner_grant`
  - `400 permissions_exceed_caller`

### `DELETE /v1/wallets/{id}/grants/{grant_id}`

- **Auth** : JWT, permission `[share]` ou owner
- **Validations** : grant existe, n'est pas celui de l'owner
- **Effets** : DELETE wallet_grants
- **Réponses** :
  - `204`
  - `403 cannot_revoke_owner_grant`

### Endpoints lecture du grant pour le caller (utile pour le client)

Pas un nouvel endpoint mais un comportement : le client a souvent besoin de récupérer son propre `encrypted_wallet_key`. C'est dans les endpoints `GET /v1/wallets/{id}` et `GET /v1/wallets/{id}/secrets` qui retournent le `my_grant.encrypted_wallet_key` quand c'est utile.

**Choix MVP** : on ajoute un endpoint dédié `GET /v1/wallets/{id}/my-grant` :

```json
{
  "id": "uuid",
  "permissions": 63,
  "encrypted_wallet_key": "<base64>",
  "is_owner": true
}
```

Plus simple et plus REST-correct que de surcharger d'autres endpoints.

## Spécifications techniques

### Helper "permissions check"

À ajouter dans `app/services/permissions.py` :

```python
PERM_READ = 0x01
PERM_ADD = 0x02
PERM_INIT = 0x04
PERM_WRITE = 0x08
PERM_REMOVE = 0x10
PERM_SHARE = 0x20
PERM_ALL = 0x3F


def has(permissions: int, required: int) -> bool:
    """Vérifie qu'une permission requise est dans le bitmap."""
    return (permissions & required) == required


def is_subset(subset: int, superset: int) -> bool:
    """Vérifie que subset ⊆ superset."""
    return (subset & superset) == subset


def name_to_bit(name: str) -> int:
    return {
        "read": PERM_READ, "add": PERM_ADD, "init": PERM_INIT,
        "write": PERM_WRITE, "remove": PERM_REMOVE, "share": PERM_SHARE,
    }[name]


def to_names(permissions: int) -> list[str]:
    return [n for n, b in [
        ("read", PERM_READ), ("add", PERM_ADD), ("init", PERM_INIT),
        ("write", PERM_WRITE), ("remove", PERM_REMOVE), ("share", PERM_SHARE),
    ] if has(permissions, b)]
```

### Dependency `require_wallet_grant`

```python
async def require_wallet_grant(
    wallet_id: UUID,
    user: CurrentUser = Depends(require_jwt_user),
    pool: asyncpg.Pool = Depends(get_pool),
) -> WalletGrant:
    """Dépendance qui charge le grant du caller, lève 404 si pas de grant."""
    async with pool.acquire() as conn:
        # ... fetch + raise 404 si rien ...
        return grant
```

Et un decorator helper :

```python
def require_permission(perm: int):
    async def _check(grant: WalletGrant = Depends(require_wallet_grant)):
        if not has(grant.permissions, perm):
            raise HTTPException(403, f"missing_permission_{perm}")
        return grant
    return _check
```

## Critères de succès

1. ✅ Owner peut créer un grant pour un autre user
2. ✅ User avec `[share]` peut créer des grants ⊆ ses propres permissions
3. ✅ User avec `[share]` ne peut PAS donner plus de permissions qu'il n'en a
4. ✅ User sans `[share]` ne peut PAS lister/créer/modifier/supprimer des grants
5. ✅ DELETE du grant de l'owner → 403 (et trigger DB bloque aussi)
6. ✅ PATCH des permissions du grant owner → 403
7. ✅ Grant cascade au DELETE du wallet et au DELETE du user
8. ✅ Lookup grantee 404 si user inexistant
9. ✅ Cannot share with self → 400
10. ✅ Audit log complet

## Pièges connus

- **Subset check correct** : `permissions & caller == permissions` (pas l'inverse).
- **Trigger DB protection owner** : on a déjà mis le trigger au lot 01. Le code applicatif ne doit PAS s'y reposer aveuglément, il doit faire le check avant et donner un message d'erreur clair (la `RaiseError` Postgres remonte sinon avec un message technique).
- **Permission `[share]` vs being owner** : owner a toujours `0x3F`, donc le check `[share]` (`& 0x20`) suffit techniquement. Mais la sémantique "owner" reste utile pour l'UI et certaines opérations spécifiques (DELETE wallet, transfer ownership).
- **Race condition sur création grant** : si deux requêtes arrivent pour le même `(wallet_id, grantee_user_id)`, la contrainte UNIQUE protège. Catcher `UniqueViolationError` → 409.
- **`encrypted_wallet_key_for_grantee` taille** : pas de borne stricte, mais pour RSA-2048 OAEP/SHA-256 le ciphertext fait 256 bytes. Pour RSA-4096, 512 bytes. Vérifier que ce n'est pas absurdement grand (> 1024 bytes refusé).
- **Audit metadata** : inclure les permissions accordées en clair (lisible) dans `metadata.permissions` pour faciliter les enquêtes.

## Tests à écrire

- `test_grant_creation_happy_path`
- `test_grant_subset_enforcement`
- `test_grant_owner_cannot_be_modified`
- `test_grant_owner_cannot_be_deleted`
- `test_grant_self_share_rejected`
- `test_grant_duplicate_409`
- `test_grant_listing_includes_owner`
- `test_my_grant_endpoint`
- `test_grant_cascade_on_user_deletion`
- `test_audit_log_for_grant_operations`

## Ce qui suit

Le **lot 05** ajoute le CRUD des secrets (sans placeholders ni générateurs, qui viennent au lot 06).
