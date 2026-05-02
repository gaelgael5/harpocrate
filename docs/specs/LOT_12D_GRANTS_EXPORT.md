# Lot 12d — Export "Dashlane parachute" des grants utilisateur

> **Prérequis** : Lots 00-11, 12a-c.

## Objectif

Permettre à un utilisateur d'exporter **ses propres grants** (la liste de ses wallets accessibles avec leurs permissions et leurs encrypted_wallet_keys) dans un format JSON copiable dans Dashlane (ou tout autre password manager). C'est la **roue de secours personnelle** : si Harpocrate disparaît mais que l'user a son export à jour, il peut reconstituer ses accès sur une nouvelle instance.

Ce n'est pas un export des **valeurs** des secrets (toujours zero-knowledge), mais un export des **clés de coffre** chiffrées pour cet user.

## Dépendances

- Lots 00-11, 12a-c

## Périmètre

### Inclus

- Endpoint `GET /v1/me/grants/export` qui retourne un JSON formaté pour Dashlane
- Endpoint `GET /v1/me/grants/export/{wallet_id}` pour un wallet seul
- Page UI `/account/grants/export` avec :
  - Aperçu du JSON
  - Bouton "Copy to clipboard"
  - Bouton "Download as .json"
  - Instructions de stockage dans Dashlane
- Audit log
- Documentation utilisateur explicite

### Exclus

- Pas de re-import (l'utilisateur copie/colle manuellement quand il en aura besoin)
- Pas d'intégration native Dashlane (juste du JSON copiable)
- Pas d'export pour d'autres users (pas d'admin override → ne sert à rien, l'admin n'a pas la passphrase user)

## Spécifications fonctionnelles

### `GET /v1/me/grants/export`

- **Auth** : JWT (pas API key)
- **Query** : aucune
- **Réponse** :

```json
{
  "format_version": "1",
  "export_type": "harpocrate_user_grants_dashlane",
  "exported_at": "2026-05-02T14:23:00Z",
  "exported_by": {
    "user_id": "uuid",
    "email": "alice@example.com"
  },
  "harpocrate_instance": {
    "public_url": "https://harpocrate.yoops.org",
    "version": "0.1.0"
  },
  "user_crypto_material": {
    "rsa_public_key": "<base64>",
    "salt_passphrase": "<base64>",
    "salt_recovery": "<base64>",
    "encrypted_rsa_private_key": "<base64>",
    "encrypted_sym_key_by_pass": "<base64>",
    "encrypted_sym_key_by_recovery": "<base64>",
    "kdf_params": {
      "memory_kb": 65536,
      "iterations": 3,
      "parallelism": 4
    },
    "rsa_key_size": 2048
  },
  "grants": [
    {
      "wallet_id": "uuid-1",
      "wallet_name": "ag-flow-prod",
      "wallet_description": "Production secrets for ag.flow",
      "is_owner": true,
      "permissions": 63,
      "permissions_human": ["read", "add", "init", "write", "remove", "share"],
      "encrypted_wallet_key": "<base64 RSA-OAEP encrypted with my pubkey>",
      "granted_at": "2026-01-15T...",
      "granted_by": {
        "user_id": "uuid",
        "email": "self"
      }
    },
    {
      "wallet_id": "uuid-2",
      "wallet_name": "shared-team-secrets",
      "wallet_description": "...",
      "is_owner": false,
      "permissions": 7,
      "permissions_human": ["read", "add", "init"],
      "encrypted_wallet_key": "<base64>",
      "granted_at": "...",
      "granted_by": {
        "user_id": "uuid-bob",
        "email": "bob@example.com"
      }
    }
  ],
  "external_identities": [
    {
      "provider": "google",
      "external_subject": "1234567890123456789",
      "is_primary": true,
      "linked_email": "alice@example.com"
    }
  ],
  "instructions_for_recovery": "To restore access on a new Harpocrate instance: (1) bootstrap a new account using the same external identity (Google) so the new instance recognizes you. (2) Import your user_crypto_material via /me/restore-from-export endpoint. (3) Import your grants via /me/grants/import endpoint. Both endpoints require your passphrase."
}
```

### `GET /v1/me/grants/export/{wallet_id}`

- **Auth** : JWT
- **Réponse** : même structure mais avec un seul élément dans `grants[]`. Utile pour copier juste un wallet critique dans Dashlane.

### Page UI `/account/grants/export`

```
Export your grants — Dashlane parachute
═══════════════════════════════════════════

This export is your personal recovery kit.
It contains everything needed to restore access to your wallets
on a new Harpocrate instance.

⚠️ This export does NOT contain the actual secret values.
It only contains the encrypted keys to access your wallets.

You can store this safely in your personal password manager
(Dashlane, 1Password, Bitwarden, etc.) as a backup of last resort.

┌──────────────────────────────────────────────────────────┐
│ Format: JSON                                             │
│ Size: 2.3 KB                                             │
│ Wallets included: 5                                      │
│ Including 3 wallets you own and 2 shared with you       │
└──────────────────────────────────────────────────────────┘

[👁 Preview] [📋 Copy to clipboard] [⬇ Download as .json]

Per-wallet export:

  ag-flow-prod    [Copy] [Download]
  dev-personal    [Copy] [Download]
  shared-team     [Copy] [Download]
  ...

How to use this in Dashlane:
  1. Open Dashlane
  2. Create a new "Secure Note" entry
  3. Title: "Harpocrate recovery — alice@example.com"
  4. Paste the JSON in the body
  5. Update this entry whenever you create or revoke a wallet grant

Last exported: 2 days ago. [Refresh export]
```

### Aperçu (Preview)

Affiche le JSON dans une modale avec syntax highlighting (Monaco editor déjà utilisé pour les autres écrans). Read-only.

### Tracker du dernier export

Stocker en DB la date du dernier export, pour rappeler à l'user de le rafraîchir s'il a fait des changements depuis :

```sql
ALTER TABLE users ADD COLUMN last_grants_export_at TIMESTAMPTZ;
```

UI affiche un badge sur le menu Account si :
- Dernière modification d'un grant > dernier export
- Et dernier export > 30 jours

```
Account ⚠
  Your grants export is out of date.
```

### Notification post-changement

Quand l'user modifie ses grants (lot 04) ou crée un nouveau wallet (lot 03), un toast :

```
✓ Grant created
Tip: don't forget to refresh your grants export to keep your
recovery kit up to date. [Refresh now] [Later]
```

## Spécifications techniques

### Service backend

```python
# app/services/grants_export.py

async def export_user_grants(
    user_id: UUID,
    pool: asyncpg.Pool,
    settings: Settings,
) -> dict:
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT * FROM users WHERE id = $1", user_id
        )
        if not user:
            raise NotFoundError()

        grants = await conn.fetch(
            """SELECT g.id, g.wallet_id, g.permissions, g.granted_at,
                      g.encrypted_wallet_key,
                      w.name AS wallet_name, w.description AS wallet_description,
                      w.owner_user_id, gby.email AS granted_by_email,
                      gby.id AS granted_by_user_id
               FROM wallet_grants g
               JOIN wallets w ON w.id = g.wallet_id
               JOIN users gby ON gby.id = g.granted_by_user_id
               WHERE g.grantee_user_id = $1""",
            user_id,
        )

        identities = await conn.fetch(
            """SELECT provider, external_subject, is_primary, linked_email
               FROM user_external_identities WHERE user_id = $1""",
            user_id,
        )

        # UPDATE last_grants_export_at
        await conn.execute(
            "UPDATE users SET last_grants_export_at = NOW() WHERE id = $1",
            user_id,
        )

        # Audit
        await audit_log(conn, "user.grants_exported",
                        actor_user_id=user_id,
                        metadata={"grants_count": len(grants)})

    return {
        "format_version": "1",
        "export_type": "harpocrate_user_grants_dashlane",
        "exported_at": now().isoformat() + "Z",
        "exported_by": {
            "user_id": str(user_id),
            "email": user["email"],
        },
        "harpocrate_instance": {
            "public_url": settings.public_url,
            "version": "0.1.0",
        },
        "user_crypto_material": {
            "rsa_public_key": b64(user["rsa_public_key"]),
            "salt_passphrase": b64(user["salt_passphrase"]),
            "salt_recovery": b64(user["salt_recovery"]),
            "encrypted_rsa_private_key": b64(user["encrypted_rsa_private_key"]),
            "encrypted_sym_key_by_pass": b64(user["encrypted_sym_key_by_pass"]),
            "encrypted_sym_key_by_recovery": b64(user["encrypted_sym_key_by_recovery"]),
            "kdf_params": {
                "memory_kb": user["kdf_memory_kb"],
                "iterations": user["kdf_iterations"],
                "parallelism": user["kdf_parallelism"],
            },
            "rsa_key_size": user["rsa_key_size"],
        },
        "grants": [
            {
                "wallet_id": str(g["wallet_id"]),
                "wallet_name": g["wallet_name"],
                "wallet_description": g["wallet_description"],
                "is_owner": g["owner_user_id"] == user_id,
                "permissions": g["permissions"],
                "permissions_human": permissions_to_list(g["permissions"]),
                "encrypted_wallet_key": b64(g["encrypted_wallet_key"]),
                "granted_at": g["granted_at"].isoformat() + "Z",
                "granted_by": {
                    "user_id": str(g["granted_by_user_id"]),
                    "email": g["granted_by_email"] if g["granted_by_user_id"] != user_id else "self",
                },
            }
            for g in grants
        ],
        "external_identities": [
            {
                "provider": i["provider"],
                "external_subject": i["external_subject"],
                "is_primary": i["is_primary"],
                "linked_email": i["linked_email"],
            }
            for i in identities
        ],
        "instructions_for_recovery": "To restore access ... (full text)",
    }
```

### Migration

```sql
-- migrations/003_grants_export.sql
ALTER TABLE users ADD COLUMN last_grants_export_at TIMESTAMPTZ;
```

### Frontend

```typescript
// frontend/src/routes/account/GrantsExport.tsx

function GrantsExportPage() {
  const { data, refetch } = useQuery(['me/grants/export'], () =>
    api.get('/v1/me/grants/export').then(r => r.data)
  );

  const onCopy = async () => {
    await navigator.clipboard.writeText(JSON.stringify(data, null, 2));
    notifications.show({ message: 'Copied to clipboard' });
  };

  const onDownload = () => {
    const blob = new Blob([JSON.stringify(data, null, 2)],
                         { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `harpocrate-grants-${data.exported_by.email}-${dateStr}.json`;
    a.click();
  };

  return (
    <Stack>
      <Title>Export your grants — Dashlane parachute</Title>
      <Text>Your personal recovery kit ...</Text>

      <Card>
        <Text>Format: JSON</Text>
        <Text>Wallets: {data?.grants.length}</Text>
        <Group>
          <Button onClick={() => setShowPreview(true)}>👁 Preview</Button>
          <Button onClick={onCopy}>📋 Copy to clipboard</Button>
          <Button onClick={onDownload}>⬇ Download</Button>
        </Group>
      </Card>

      <PerWalletExports grants={data?.grants} />

      <DashlaneInstructions />

      <LastExportedFooter exportedAt={data?.exported_at} />
    </Stack>
  );
}
```

## Critères de succès

1. ✅ `GET /me/grants/export` renvoie le JSON complet
2. ✅ Format version "1", type "harpocrate_user_grants_dashlane"
3. ✅ Inclut toutes les grants (owned + granted-to-me)
4. ✅ Inclut user_crypto_material complet
5. ✅ Inclut external_identities
6. ✅ `is_owner: true` pour les wallets en propriété
7. ✅ `granted_by.email = "self"` pour les wallets en propriété
8. ✅ Per-wallet export filtré correctement
9. ✅ UI affiche aperçu, copy, download
10. ✅ Per-wallet UI fonctionne
11. ✅ `last_grants_export_at` mis à jour
12. ✅ Badge "out of date" si mod > export
13. ✅ Toast post-création de grant suggère un refresh
14. ✅ Audit log

## Pièges connus

- **Pas d'API key access** : cet endpoint manipule le crypto material complet. Une API key ne devrait jamais pouvoir l'extraire. Vérifier 401 sur API key.
- **Taille du JSON** : peut être gros si beaucoup de wallets. À 100 wallets avec RSA 2048 → ~30 KB. Reste copiable manuellement dans Dashlane.
- **Stockage Dashlane** : Dashlane a une limite de taille pour les Secure Notes. Si l'export dépasse, recommander le download + stockage dans Dashlane "Documents" attached.
- **Re-export régulier** : sans cela, le parachute est obsolète. UI doit pousser au rafraîchissement.
- **Pas de re-import au MVP** : on documente la procédure mais on n'implémente pas l'endpoint d'import. C'est un cas extrême "Harpocrate disparu". Sera traité dans un futur lot.
- **Privacy** : l'export contient `external_subject` complet (utile pour re-bootstrap). C'est OK car c'est l'user qui voit ses propres données.
- **`permissions_human`** : aide pour Dashlane, pas pour le parsing. Le code parse `permissions` (int).

## Tests

- `test_export_returns_correct_format`
- `test_export_includes_all_grants`
- `test_export_includes_crypto_material`
- `test_export_per_wallet_filters_correctly`
- `test_export_blocked_for_api_key`
- `test_export_updates_last_exported_at`
- `test_ui_copy_to_clipboard`
- `test_ui_download`

## Ce qui suit

Le **lot 12e** ajoute la gestion explicite des variables d'environnement (sensibles vs non-sensibles) avec backup séparé.
