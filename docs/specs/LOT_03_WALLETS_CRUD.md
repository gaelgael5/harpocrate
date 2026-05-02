# Lot 03 — Wallets CRUD basique

> **Prérequis** : Lots 00, 01, 02.

## Objectif

Permettre à un utilisateur authentifié de **créer, lister, lire, modifier, supprimer** ses wallets, avec gestion des tags. Le partage avec d'autres utilisateurs viendra au lot 04.

## Dépendances

- Lots 00, 01, 02

## Périmètre

### Inclus

- Endpoints `GET/POST /v1/wallets`, `GET/PATCH/DELETE /v1/wallets/{id}`
- Endpoint `POST /v1/wallets/{id}/transfer-ownership` (transfert unilatéral)
- Endpoint `GET /v1/users/lookup?email=...` (pour préparer le partage du lot 04)
- Création automatique du grant owner avec permissions `0x3F`
- Hard delete avec confirmation par nom
- Tags wallet (création, listage, modification via PATCH)
- Pagination cursor-based
- Audit log complet
- Filtre `?tag=...` et `?name_contains=...`
- Compteurs `valued_secrets_count` / `placeholder_secrets_count` dans le listage (à 0 puisque pas de secrets encore)

### Exclus

- Aucun secret dans les wallets (lot 05)
- Pas de partage (lot 04)
- Pas d'export/import (lot 07)

## Spécifications fonctionnelles

### `GET /v1/wallets`

- **Auth** : JWT seulement (pas API key dans ce lot, sera étendu au lot 08)
- **Query** : `tag`, `name_contains`, `limit` (défaut 50, max 200), `cursor`
- **Réponse** : `200`
```json
{
  "wallets": [
    {
      "id": "uuid",
      "name": "ag.flow Production",
      "description": "...",
      "tags": ["agflow", "prod"],
      "owner_user_id": "uuid",
      "is_owner": true,
      "my_permissions": 63,
      "valued_secrets_count": 0,
      "placeholder_secrets_count": 0,
      "created_at": "...",
      "updated_at": "..."
    }
  ],
  "next_cursor": null
}
```
- Filtre : seulement les wallets où l'utilisateur a un grant.

### `POST /v1/wallets`

- **Auth** : JWT
- **Body** :
```json
{
  "name": "ag.flow Production",
  "description": "...",
  "tags": ["agflow", "prod"],
  "encrypted_wallet_key_for_owner": "<base64>"
}
```
- **Validations** : nom non vide ≤ 255, description ≤ 1000, tags lowercase trimmed (re-normalisés serveur), `encrypted_wallet_key_for_owner` non vide
- **Effets** :
  - Transaction :
    - INSERT wallets (owner = caller)
    - INSERT wallet_grants (grantee = caller, permissions = 63, encrypted_wallet_key)
    - INSERT wallet_tags pour chaque tag
- **Réponse** : `201 { "wallet_id": "..." }`

### `GET /v1/wallets/{id}`

- **Auth** : JWT, le caller doit avoir un grant
- **Réponse** : `200` (mêmes champs que la liste)
- **Erreur** : `404` si pas de grant (pas `403` pour ne pas révéler l'existence)

### `PATCH /v1/wallets/{id}`

- **Auth** : JWT avec permission `[share]` (ou owner)
- **Body** : `{ "name"?: "...", "description"?: "...", "tags"?: [...] }`
- **Effets** : update partiel des champs fournis. Si `tags` est fourni, on remplace l'ensemble (DELETE puis INSERT).
- **Réponse** : `200` avec le wallet mis à jour

### `DELETE /v1/wallets/{id}`

- **Auth** : JWT, **owner uniquement**
- **Body** : `{ "confirmation": "<wallet_name>" }`
- **Effets** : DELETE wallets (cascade sur grants, secrets, api_keys, tags)
- **Réponses** :
  - `204`
  - `403 not_owner`
  - `400 confirmation_mismatch`

### `POST /v1/wallets/{id}/transfer-ownership`

- **Auth** : JWT, **owner uniquement**
- **Body** : `{ "new_owner_user_id": "uuid" }`
- **Validations** :
  - Le nouvel owner doit déjà avoir un grant sur ce wallet
- **Effets** :
  - `UPDATE wallets SET owner_user_id = ?`
  - L'ancien owner conserve son grant tel quel
- **Audit** : `wallet.ownership_transferred`
- **Réponses** :
  - `200`
  - `400 new_owner_has_no_grant`

### `GET /v1/users/lookup?email=...`

- **Auth** : JWT
- **Réponses** :
  - `200 { "user_id": "...", "email": "...", "display_name": "...", "rsa_public_key": "<base64>" }`
  - `404` : pas trouvé
- **Notes** : à rate-limiter (30 req/min/IP) pour éviter l'énumération. Pour MVP, rate-limit basique en mémoire est suffisant.

## Spécifications techniques

### Pagination cursor-based

Le cursor encode `(updated_at, id)` en base64 :

```python
def encode_cursor(row) -> str:
    raw = f"{row['updated_at'].isoformat()}|{row['id']}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")

def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    padded = cursor + "=" * (-len(cursor) % 4)
    raw = base64.urlsafe_b64decode(padded).decode()
    ts, id_ = raw.split("|")
    return datetime.fromisoformat(ts), UUID(id_)
```

Requête SQL :
```sql
SELECT ... FROM wallets w
JOIN wallet_grants wg ON wg.wallet_id = w.id AND wg.grantee_user_id = $1
WHERE ($2::timestamptz IS NULL OR (w.updated_at, w.id) < ($2, $3))
ORDER BY w.updated_at DESC, w.id DESC
LIMIT $4
```

### Calcul de `valued_secrets_count` / `placeholder_secrets_count`

Au listage, faire le COUNT en JOIN. Les secrets n'existent pas encore (lot 05), mais préparer la requête pour éviter une refonte plus tard :

```sql
LEFT JOIN LATERAL (
    SELECT
        COUNT(*) FILTER (WHERE is_placeholder = FALSE) AS valued,
        COUNT(*) FILTER (WHERE is_placeholder = TRUE) AS placeholder
    FROM secrets WHERE wallet_id = w.id
) s ON true
```

### Rate limiting du `/users/lookup`

```python
from collections import defaultdict
from time import monotonic

_lookup_attempts: dict[str, list[float]] = defaultdict(list)

async def rate_limit_lookup(ip: str) -> None:
    now = monotonic()
    attempts = _lookup_attempts[ip]
    # Nettoyer > 60s
    _lookup_attempts[ip] = [t for t in attempts if now - t < 60]
    if len(_lookup_attempts[ip]) >= 30:
        raise HTTPException(429, "rate_limit_exceeded")
    _lookup_attempts[ip].append(now)
```

(MVP simple. À remplacer par Redis ou middleware FastAPI plus tard si besoin.)

## Critères de succès

1. ✅ POST création wallet + grant owner créé automatiquement
2. ✅ GET liste retourne les wallets de l'utilisateur uniquement
3. ✅ PATCH modifie name, description, tags
4. ✅ DELETE avec mauvais nom → 400, avec bon nom → 204 et cascade
5. ✅ Non-owner ne peut pas DELETE
6. ✅ Transfer ownership refusée si new owner n'a pas de grant
7. ✅ Lookup par email retourne la public key
8. ✅ Rate limit lookup à 30/min
9. ✅ Filtres tag et name_contains
10. ✅ Pagination cursor fonctionne sur 100+ wallets
11. ✅ Tous les endpoints créent un audit log

## Pièges connus

- **`my_permissions`** : récupéré depuis `wallet_grants` du caller, pas hardcodé.
- **`is_owner`** : comparer `wallet.owner_user_id == caller.id`, pas `permissions == 63`.
- **Tags : DELETE puis INSERT en transaction** : si on fait UPDATE on ne peut pas, donc PATCH avec tags = remplacement total.
- **Confirmation par nom** : comparer la string exacte, pas trimmed/lowercase. Si l'utilisateur tape "Production " avec un espace il doit échouer (force la concentration).
- **Énumération via lookup** : dans `404` ne donner aucun détail. Loguer l'échec avec l'IP pour audit.
- **Cascade DELETE** : on a configuré ON DELETE CASCADE sur wallet_grants, secrets, api_keys, wallet_tags. Le DELETE wallet suffit.
- **Owner check pour DELETE** : pas seulement la permission `[share]`, mais bien `wallets.owner_user_id == caller.id`.

## Tests à écrire

- `test_create_wallet_creates_owner_grant`
- `test_list_wallets_only_mine`
- `test_get_wallet_404_if_not_granted`
- `test_patch_wallet_updates_tags_replacement`
- `test_delete_wallet_cascade`
- `test_delete_wallet_wrong_confirmation`
- `test_delete_wallet_not_owner_403`
- `test_transfer_ownership_requires_grant_for_new_owner`
- `test_user_lookup_by_email`
- `test_lookup_rate_limit`
- `test_pagination_cursor`
- `test_audit_log_entries`

## Ce qui suit

Le **lot 04** ajoute le partage de wallets entre utilisateurs (grants).
