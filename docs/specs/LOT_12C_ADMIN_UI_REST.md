# Lot 12c — UI Admin reste : users + audit log global + system

> **Prérequis** : Lots 00-11, 12a, 12b.

## Objectif

Compléter l'UI admin avec les pages **gestion des users**, **audit log global**, **system info**, et la **page maintenance détaillée**. C'est ici que l'admin trouve les outils pour traiter les anomalies d'identité, lever une quarantaine, désactiver un user compromis, ou consulter l'activité globale.

## Dépendances

- Lots 00-11, 12a, 12b

## Périmètre

### Inclus

- Endpoints backend `/v1/admin/users/*` complet
- Endpoints backend `/v1/admin/audit-log` (lecture globale)
- Endpoints backend `/v1/admin/system/*` (DB health, Keycloak status, version)
- Page UI `/admin/users` (liste + filtre + actions)
- Page UI `/admin/users/{id}` (détail + identités + anomalies + actions)
- Page UI `/admin/audit` (audit log global avec filtres)
- Page UI `/admin/system` (info système)
- Page UI `/admin/maintenance` complète (historique des activations, reasoning)
- Endpoint admin de relink manuel d'identité (cas extrême)

### Exclus

- Pas d'export Dashlane (lot 12d)
- Pas de gestion env vars (lot 12e)

## Spécifications fonctionnelles

### `GET /v1/admin/users`

- **Auth** : JWT + admin
- **Query** : `q` (search email/name), `status` (active/quarantined/disabled), `cursor`, `limit`
- **Réponse** :
```json
{
  "users": [
    {
      "id": "uuid",
      "email": "alice@example.com",
      "display_name": "Alice",
      "created_at": "...",
      "last_unlock_at": "...",
      "status": "active|quarantined|disabled",
      "quarantine_until": null,
      "identities_count": 2,
      "wallets_owned_count": 3,
      "unacknowledged_anomalies_count": 0,
      "force_reverify_next_login": false
    }
  ],
  "next_cursor": null
}
```

### `GET /v1/admin/users/{id}`

- **Auth** : JWT + admin
- **Réponse** : détails complets, **incluant les `external_subject` complets** (admin a légitimement besoin)

```json
{
  "id": "uuid",
  "email": "...",
  "display_name": "...",
  "created_at": "...",
  "last_unlock_at": "...",
  "quarantine_until": null,
  "quarantine_reason": null,
  "force_reverify_next_login": false,
  "disabled_at": null,
  "disabled_reason": null,
  "identities": [
    {
      "id": "uuid",
      "provider": "google",
      "external_subject": "1234567890123456789",
      "is_primary": true,
      "linked_email": "alice@example.com",
      "linked_display_name": "Alice",
      "linked_at": "...",
      "last_login_at": "..."
    }
  ],
  "anomalies": [
    {
      "id": 42,
      "detected_at": "...",
      "severity": "warning",
      "type": "display_name_changed_significantly",
      "metadata": { "old": "Alice", "new": "Bob" },
      "acknowledged_at": null
    }
  ],
  "wallets_owned": [
    { "id": "...", "name": "...", "secrets_count": 12 }
  ],
  "wallets_granted": [
    { "id": "...", "name": "...", "permissions": 0x07, "granted_at": "..." }
  ],
  "api_keys_active_count": 3,
  "recent_activity": [
    { "occurred_at": "...", "action": "secret.read", "target_wallet": "..." }
  ]
}
```

### `POST /v1/admin/users/{id}/quarantine`

- **Auth** : JWT + admin + reverify
- **Body** : `{ "reason": "Manual lock following suspicious activity", "duration_days": 14 }`
- **Effet** : SET `quarantine_until = NOW() + interval`, `quarantine_reason`
- **Audit** : `admin.user_quarantined`

### `POST /v1/admin/users/{id}/quarantine/lift`

- **Auth** : JWT + admin + reverify
- **Body** : `{ "comment": "Identity verified by phone with the user" }`
- **Effet** : SET `quarantine_until = NULL`
- **Audit** : `admin.user_quarantine_lifted`

### `POST /v1/admin/users/{id}/disable`

- **Auth** : JWT + admin + reverify
- **Body** : `{ "reason": "Account compromised, awaiting investigation" }`
- **Effets** :
  - SET `disabled_at = NOW()`, `disabled_reason`
  - INVALIDATE toutes les API keys actives du user
  - L'user ne peut plus se connecter (refus dès le middleware JWT)
- **Audit** : `admin.user_disabled`

### `POST /v1/admin/users/{id}/enable`

- **Auth** : JWT + admin + reverify
- **Body** : `{ "comment": "..." }`
- **Effet** : SET `disabled_at = NULL`
- **Audit** : `admin.user_enabled`

### `POST /v1/admin/users/{id}/force-reverify-next-login`

- **Auth** : JWT + admin
- **Effet** : SET `force_reverify_next_login = TRUE`
- L'user au prochain login devra prouver sa passphrase pour pouvoir faire quoi que ce soit
- **Audit** : `admin.user_force_reverify_set`

### `POST /v1/admin/users/{id}/identities`

Endpoint **extrême** de relink manuel.

- **Auth** : JWT + admin + reverify
- **Body** :
```json
{
  "provider": "google",
  "external_subject": "1234567890123456789",
  "set_primary": false,
  "comment": "Manual relink after Keycloak reinstall, identity verified by phone with user on 2026-05-02"
}
```
- **Validations** :
  - `comment` obligatoire (>20 chars)
  - Le `(provider, external_subject)` ne doit pas exister déjà pour un autre user (sinon collision dangereuse)
- **Effet** : INSERT user_external_identities
- **Audit** : `admin.user_identity_manually_linked` avec `comment` complet
- **Notification** : si configuré, envoie un email aux autres admins (lot futur)

### `DELETE /v1/admin/users/{id}/identities/{identity_id}`

- **Auth** : JWT + admin + reverify
- **Body** : `{ "comment": "Identity suspected compromised" }`
- **Validations** : pas la dernière identité, pas la primary (sauf si user n'a qu'une identité)
- **Audit** : `admin.user_identity_unlinked`

### `POST /v1/admin/users/{id}/anomalies/{anomaly_id}/acknowledge`

- **Auth** : JWT + admin
- **Body** : `{ "comment": "..." }`
- **Audit** : `admin.anomaly_acknowledged_by_admin`

### `DELETE /v1/admin/users/{id}`

Suppression complète (cas extrême).

- **Auth** : JWT + admin + reverify + double confirmation textuelle
- **Body** : `{ "confirmation": "DELETE USER alice@example.com", "comment": "..." }`
- **Validations** :
  - L'user n'a aucun wallet en propriété (sinon il faut transférer ou supprimer ses wallets d'abord)
  - Si l'user a des wallets : retour 409 avec liste des wallets bloquants
- **Effet** : DELETE FROM users (cascade vers identities, anomalies, grants en tant que grantee, api_keys, audit_log SET NULL)
- **Audit** : `admin.user_deleted`

### `GET /v1/admin/audit-log`

- **Auth** : JWT + admin
- **Query** : `actor_user_id`, `action`, `target_wallet_id`, `since`, `until`, `success`, `cursor`, `limit`
- **Réponse** : standard audit log structure

### `GET /v1/admin/system`

- **Auth** : JWT + admin
- **Réponse** :
```json
{
  "version": "0.1.0",
  "uptime_seconds": 123456,
  "db": {
    "status": "ok",
    "size_mb": 234,
    "connections_active": 5,
    "connections_max": 100
  },
  "keycloak": {
    "status": "ok",
    "url": "https://keycloak.yoops.org",
    "realm": "harpocrate",
    "jwks_last_refresh": "..."
  },
  "backup": {
    "local_path": "/var/lib/harpocrate/backups",
    "local_path_disk_free_mb": 12345,
    "last_backup_at": "...",
    "remote_configured": false
  },
  "age_public_key": "age1qyqs...",
  "schema_version": "002",
  "session_epoch": 43,
  "config_floors": {
    "kdf_memory_kb": 65536,
    "kdf_iterations": 3,
    "kdf_parallelism": 4,
    "rsa_key_size": 2048
  }
}
```

### Page `/admin/users`

Tableau avec colonnes : Email, Display name, Status, Identities, Wallets, Last seen, Actions.

Filtres : recherche, status (active/quarantined/disabled), anomalies non ack.

Code couleur :
- Vert : actif normal
- Orange : quarantine
- Rouge : disabled
- Jaune (badge) : anomalies non acknowledgées

Actions par ligne : 👁 View, ⏸ Quarantine, 🚫 Disable.

### Page `/admin/users/{id}`

Layout en 3 sections :

```
┌─────────────────────────────────────────────────────────┐
│ alice@example.com                       [Disable user]  │
│ Created 2026-01-15  ·  Last seen 2 hours ago            │
│ Status: ✓ Active                                         │
├─────────────────────────────────────────────────────────┤
│ ▾ External identities (2)                                │
│   Google · 1234567890123456789  (primary)                │
│   Linked 2026-01-15 · Last login 2 hours ago             │
│   [Unlink]                                               │
│                                                          │
│   Google · 9876543210987654321                           │
│   Linked 2026-03-01 · Last login 3 days ago             │
│   [Unlink]  [Set as primary]                             │
│                                                          │
│   [+ Manually link new identity (extreme cases)]         │
├─────────────────────────────────────────────────────────┤
│ ▾ Anomalies (1 unacknowledged)                           │
│   ⚠ Warning: display_name_changed (2026-04-15)           │
│     Old: "Alice" → New: "Bob"                            │
│     [Acknowledge]                                        │
├─────────────────────────────────────────────────────────┤
│ ▾ Wallets owned (3)                                      │
│   prod-shared (12 secrets) · dev-personal (5 secrets)... │
├─────────────────────────────────────────────────────────┤
│ ▾ Wallets granted (1)                                    │
│   ag-flow-prod  (read,init,share)  granted by Bob       │
├─────────────────────────────────────────────────────────┤
│ ▾ API keys active (3)                                    │
│   ag-flow-prod-runner · expires in 30d                  │
├─────────────────────────────────────────────────────────┤
│ ▾ Recent activity (last 50)                              │
│   14:20 secret.read on `ANTHROPIC_API_KEY`               │
│   ...                                                    │
├─────────────────────────────────────────────────────────┤
│ Quick actions:                                           │
│   [Force re-verify next login]                           │
│   [Quarantine for 14 days]                               │
│   [Disable account]                                      │
│   [Delete account] (only if no wallets owned)            │
└─────────────────────────────────────────────────────────┘
```

### Modal "Manually link new identity"

Page d'avertissement explicite :

```
⚠️ EXTREME ACTION

Manually linking an identity gives that OAuth account access to this user's
encrypted secrets vault. Only do this AFTER verifying in person (or via a
trusted channel) that the new OAuth subject belongs to the legitimate owner
of this Harpocrate account.

Provider: [Google ▾]

External subject (sub claim from OAuth provider):
┌─────────────────────────────────────────────┐
│                                             │
└─────────────────────────────────────────────┘

Comment (required, will be in audit log):
┌─────────────────────────────────────────────┐
│ Verified identity in person on 2026-05-02   │
│ via video call. Reason for relink: Keycloak │
│ reinstall lost user federation mapping.     │
└─────────────────────────────────────────────┘

☐ I confirm I have verified the user's identity
☐ I have a record of this verification

Type "LINK NEW IDENTITY" to confirm:
┌─────────────────────────────────────────────┐
│                                             │
└─────────────────────────────────────────────┘

Re-enter your passphrase:
┌─────────────────────────────────────────────┐
│                                             │
└─────────────────────────────────────────────┘

[Cancel]  [Link identity]
```

### Page `/admin/audit`

Tableau audit log global avec colonnes : Time, Actor, Action, Target, Success, IP, Metadata.

Filtres avancés :
- Date range (default: last 7 days)
- Actor (search by email)
- Action (multi-select)
- Target wallet
- Success/Failure
- Free text dans metadata

Export CSV : `GET /v1/admin/audit-log/export?format=csv`.

### Page `/admin/system`

Affichage des infos système. 4 cartes :

```
┌─────────────────────────────────┬─────────────────────────────────┐
│ Version & Schema                │ Database                        │
│                                 │                                 │
│ Harpocrate: 0.1.0               │ Status: ✓ ok                    │
│ Schema: 002                     │ Size: 234 MB                    │
│ Session epoch: 43               │ Connections: 5/100              │
│ Started: 2 days ago             │ Last vacuum: 6 hours ago        │
└─────────────────────────────────┴─────────────────────────────────┘
┌─────────────────────────────────┬─────────────────────────────────┐
│ Keycloak                        │ Backup                          │
│                                 │                                 │
│ Status: ✓ ok                    │ Last backup: 2 hours ago        │
│ URL: keycloak.yoops.org         │ Local path: /var/lib/...        │
│ Realm: harpocrate               │ Free space: 12 GB              │
│ External sub claim: external_sub│ Remote: not configured          │
│ JWKS refreshed: 1 hour ago      │ [Configure remote backup →]     │
└─────────────────────────────────┴─────────────────────────────────┘
```

Section "Crypto & Keys" :

```
Age public key (used to encrypt backups):
  age1qyqszqgpqyqszqgpqyqszqgpqyq...
  [Copy]

Reminder: the corresponding private key is held by the administrator
(you) and must be stored securely OFFLINE. Without it, backups cannot
be restored.

KDF floors:
  Memory:      65 536 KB
  Iterations:  3
  Parallelism: 4

RSA key size minimum: 2048
```

Section "Configuration" :

Lien vers `/admin/system/env` (lot 12e).

### Page `/admin/maintenance`

Détaillée :

```
Maintenance mode

Current status: ✓ OFF

Recent activations:
┌──────────────────┬──────────────┬──────────────────┬────────┐
│ Started          │ Duration     │ Reason           │ By     │
├──────────────────┼──────────────┼──────────────────┼────────┤
│ 2026-05-02 14:30 │ 4m 12s       │ DB restore       │ gael@  │
│ 2026-04-15 09:00 │ 12m 03s      │ Schema migration │ gael@  │
└──────────────────┴──────────────┴──────────────────┴────────┘

[Enable maintenance now]
```

## Spécifications techniques

### Endpoints admin agrégés

```python
# app/api/v1/admin/users.py
router = APIRouter(prefix="/v1/admin/users", dependencies=[Depends(require_admin)])

@router.get("")
async def list_users(...): ...

@router.get("/{user_id}")
async def get_user_detail(user_id: UUID, ...): ...

@router.post("/{user_id}/quarantine")
async def quarantine_user(...): ...

@router.post("/{user_id}/quarantine/lift")
async def lift_quarantine(...): ...

# etc.
```

### Dependency `require_admin`

```python
async def require_admin(user: CurrentUser = Depends(require_jwt_user)) -> CurrentUser:
    if "harpocrate-admin" not in user.realm_roles:
        raise HTTPException(403, "admin_role_required")
    return user
```

Le `user.realm_roles` est extrait du JWT au moment de l'auth.

### Page user-detail UI

```typescript
// frontend/src/routes/admin/UserDetail.tsx
function UserDetail() {
  const { id } = useParams();
  const { data: user, refetch } = useQuery(['admin/user', id], ...);

  if (!user) return <Loader />;

  return (
    <Stack>
      <UserHeader user={user} onAction={refetch} />
      <IdentitiesSection identities={user.identities} userId={id!} onChange={refetch} />
      <AnomaliesSection anomalies={user.anomalies} onAck={refetch} />
      <WalletsOwnedSection wallets={user.wallets_owned} />
      <WalletsGrantedSection wallets={user.wallets_granted} />
      <ApiKeysSection count={user.api_keys_active_count} userId={id!} />
      <RecentActivitySection items={user.recent_activity} />
      <QuickActionsSection user={user} onAction={refetch} />
    </Stack>
  );
}
```

## Critères de succès

1. ✅ Liste users avec status, recherche, filtre
2. ✅ Détail user avec toutes les sections
3. ✅ External_subject affichés en clair (admin only)
4. ✅ Quarantine/lift fonctionne
5. ✅ Disable user invalide ses API keys actives
6. ✅ Force-reverify-next-login fonctionne
7. ✅ Manual link identity avec garde-fous (comment + checkbox + textuelle)
8. ✅ Unlink identity fonctionne
9. ✅ Acknowledge anomaly fonctionne
10. ✅ Delete user 409 si wallets en propriété
11. ✅ Audit log global filtrable
12. ✅ Audit log export CSV
13. ✅ System page affiche info correctes
14. ✅ Maintenance page liste les activations
15. ✅ Tous les endpoints admin journalisés en audit log

## Pièges connus

- **Volume audit log** : sur de la prod, des millions de lignes. Pagination cursor obligatoire. Index sur `(occurred_at DESC)` déjà fait.
- **`force_reverify_next_login`** : doit être consommé au login (set false) pour ne pas boucler.
- **Disable user invalide API keys** : ne pas oublier d'UPDATE revoked_at pour toutes les API keys du user. Sinon il peut continuer à lire les secrets via API key.
- **Delete user en cascade** : audit_log a SET NULL, identities CASCADE, grants en tant que grantee CASCADE, mais wallets owner_user_id est RESTRICT (refus si wallets). C'est intentionnel.
- **Manual link identity** : action gravissime. Triple confirmation (checkbox + textuelle + reverify). Audit ultra-explicite.
- **Affichage `external_subject` en clair** : admin uniquement, JAMAIS dans les endpoints user. Vérifier qu'aucun leak.
- **Recherche users** : ILIKE `%query%` peut être lent sur grosse table. Indexer email avec trigram (`pg_trgm`) si besoin.
- **Anomalies pas auto-ack** : il faut explicitement les acknowledger pour les "fermer". Sinon elles s'accumulent. UI bien voyant.

## Tests

- `test_list_users_pagination`
- `test_get_user_detail_includes_external_subjects_for_admin`
- `test_get_user_detail_blocks_for_non_admin`
- `test_quarantine_user_via_admin`
- `test_lift_quarantine`
- `test_disable_user_invalidates_api_keys`
- `test_enable_user`
- `test_force_reverify_next_login`
- `test_manual_link_identity_requires_full_confirmation`
- `test_manual_link_identity_collision_409`
- `test_unlink_identity_via_admin`
- `test_acknowledge_anomaly_via_admin`
- `test_delete_user_blocked_if_owns_wallets`
- `test_delete_user_cascades_correctly`
- `test_audit_log_global_filtering`
- `test_audit_log_export_csv`
- `test_system_endpoint_returns_health`

## Ce qui suit

Le **lot 12d** ajoute l'export "Dashlane parachute" pour qu'un user puisse copier ses secrets/grants critiques dans son gestionnaire personnel.
