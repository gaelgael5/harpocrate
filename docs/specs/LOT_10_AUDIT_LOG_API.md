# Lot 10 — Audit log API

> **Prérequis** : Lots 00-09.

## Objectif

Exposer l'**audit log** via une API consultable par les utilisateurs autorisés, avec filtres pertinents et permissions différenciées (un user voit ses actions et celles sur ses wallets owned, une API key voit uniquement ses propres actions). Ajouter aussi un **job de purge** pour respecter la rétention configurée (90 jours par défaut).

## Dépendances

- Lots 00-09

## Périmètre

### Inclus

- Endpoint `GET /v1/audit-log` avec filtres
- Permissions différenciées :
  - User JWT : voit ses propres actions + toutes les actions sur les wallets dont il est owner
  - API key : voit **uniquement ses propres actions** (filtre forcé)
- Pagination cursor sur `(occurred_at DESC, id DESC)`
- Filtres : `wallet_id`, `action`, `since`, `until`, `actor_user_id`, `actor_api_key_id`, `success`
- Job cron Python (script séparé, lancé par cron système ou par un scheduler) qui purge `audit_log` > N jours
- Endpoint `GET /v1/audit-log/actions` retournant la liste des actions disponibles (utile pour UI)
- Documentation des actions auditées

### Exclus

- Pas d'export CSV/JSON (à ajouter en roadmap si besoin)
- Pas de notifications/alertes sur events (roadmap)
- Pas de stockage long-terme (archivage S3, Loki, etc.) au MVP

## Spécifications fonctionnelles

### `GET /v1/audit-log`

- **Auth** : JWT ou API key
- **Query params** :
  - `wallet_id` : UUID, filtre par wallet cible
  - `action` : string, filtre par action exacte (ex: `secret.read`)
  - `action_prefix` : string, filtre par préfixe (ex: `secret.`)
  - `since` : ISO 8601, événements à partir de
  - `until` : ISO 8601, événements jusqu'à
  - `actor_user_id` : UUID
  - `actor_api_key_id` : UUID
  - `target_secret_id` : UUID
  - `success` : `true`/`false`
  - `limit` : 1..200, défaut 50
  - `cursor` : opaque pour pagination

- **Logique de filtrage selon le type d'auth** :

```python
async def query_audit_log(auth, filters):
    base_query = "SELECT * FROM audit_log WHERE 1=1"
    params = []

    if isinstance(auth, ApiKeyAuth):
        # API key : seulement ses propres actions, peu importe les filtres
        base_query += " AND actor_api_key_id = $1"
        params.append(auth.api_key_id)

    elif isinstance(auth, JwtAuth):
        # JWT : ses actions OU actions sur ses wallets owned
        owned_wallet_ids = await get_owned_wallet_ids(auth.user_id)
        base_query += """
            AND (
                actor_user_id = $1
                OR target_wallet_id = ANY($2::uuid[])
            )
        """
        params.append(auth.user_id)
        params.append(owned_wallet_ids)

    # Filtres standards (avec offset des params)
    if filters.wallet_id:
        base_query += f" AND target_wallet_id = ${len(params) + 1}"
        params.append(filters.wallet_id)
    # ... etc

    base_query += f" ORDER BY occurred_at DESC, id DESC LIMIT ${len(params) + 1}"
    params.append(filters.limit + 1)  # +1 pour détecter has_more

    return await conn.fetch(base_query, *params)
```

- **Réponse** :
```json
{
  "events": [
    {
      "id": 12345,
      "occurred_at": "2026-05-01T14:23:00.123Z",
      "action": "secret.read",
      "actor": {
        "type": "api_key",
        "id": "uuid",
        "name": "agent-llm-prod"
      },
      "target": {
        "wallet_id": "uuid",
        "wallet_name": "ag.flow Production",
        "secret_id": "uuid"
      },
      "metadata": { "secret_name": "ANTHROPIC_API_KEY" },
      "success": true,
      "actor_ip": "10.10.10.5"
    }
  ],
  "next_cursor": "..."
}
```

### `GET /v1/audit-log/actions`

- **Auth** : JWT ou API key
- **Réponse** :
```json
{
  "actions": [
    "user.bootstrapped",
    "user.crypto_accessed",
    "user.passphrase_changed",
    "user.recovery_renewed",
    "user.recovery_accessed",
    "wallet.created",
    "wallet.modified",
    "wallet.deleted",
    "wallet.ownership_transferred",
    "wallet.exported_structure",
    "wallet.imported",
    "grant.created",
    "grant.modified",
    "grant.revoked",
    "secret.created",
    "secret.read",
    "secret.modified",
    "secret.deleted",
    "secret.placeholder_created",
    "secret.populated",
    "api_key.created",
    "api_key.modified",
    "api_key.revoked",
    "api_key.used"
  ]
}
```

### Catalogue des actions auditées

| Action | Acteur | Métadonnées attendues |
|---|---|---|
| `user.bootstrapped` | user | `kdf_params`, `rsa_key_size` |
| `user.crypto_accessed` | user | — |
| `user.passphrase_changed` | user | `kdf_params` |
| `user.recovery_renewed` | user | — |
| `user.recovery_accessed` | user | — |
| `wallet.created` | user | `wallet_name`, `tags` |
| `wallet.modified` | user | `changed_fields` (list) |
| `wallet.deleted` | user | `wallet_name`, `secret_count` |
| `wallet.ownership_transferred` | user | `previous_owner_id`, `new_owner_id` |
| `wallet.exported_structure` | user | `secret_count` |
| `wallet.imported` | user | `source_wallet_name`, `secret_count` |
| `grant.created` | user | `grantee_id`, `permissions` |
| `grant.modified` | user | `grantee_id`, `old_permissions`, `new_permissions` |
| `grant.revoked` | user | `grantee_id` |
| `secret.created` | user/api_key | `secret_name`, `is_placeholder` |
| `secret.read` | user/api_key | `secret_name` |
| `secret.modified` | user/api_key | `secret_name`, `changed_fields` |
| `secret.deleted` | user/api_key | `secret_name` |
| `secret.placeholder_created` | user/api_key | `secret_name`, `generator_type` |
| `secret.populated` | user/api_key | `secret_name`, `generator_type` |
| `api_key.created` | user | `api_key_name`, `permissions`, `expires_at` |
| `api_key.modified` | user | `api_key_id`, `changed_fields` |
| `api_key.revoked` | user | `api_key_id` |

**Note `api_key.used`** : on ne loggue PAS chaque utilisation d'API key (volume excessif). Le champ `last_used_at` sur `api_keys` suffit. Si on veut tracker l'usage, c'est via les events métier (`secret.read`, etc.) avec `actor_api_key_id`.

### Job de purge

Script standalone `scripts/purge_audit_log.py` :

```python
"""Purge des audit logs au-delà de la rétention.

Usage : python scripts/purge_audit_log.py [--dry-run]
À lancer via cron : 0 3 * * * /usr/bin/python /app/scripts/purge_audit_log.py
"""
import argparse
import asyncio
import asyncpg
from app.core.config import settings
from app.core.logging import logger


async def purge(dry_run: bool = False) -> None:
    cutoff = f"NOW() - INTERVAL '{settings.audit_retention_days} days'"
    conn = await asyncpg.connect(dsn=settings.db_dsn)
    try:
        count_query = f"SELECT COUNT(*) FROM audit_log WHERE occurred_at < {cutoff}"
        count = await conn.fetchval(count_query)

        logger.info("audit_purge_target", count=count, dry_run=dry_run)

        if dry_run or count == 0:
            return

        # Purge par batch pour éviter de bloquer
        deleted = 0
        while True:
            batch = await conn.execute(
                f"""DELETE FROM audit_log
                    WHERE id IN (
                        SELECT id FROM audit_log
                        WHERE occurred_at < {cutoff}
                        LIMIT 10000
                    )
                """
            )
            n = int(batch.split()[-1])
            deleted += n
            logger.info("audit_purge_batch", batch_size=n, total=deleted)
            if n < 10000:
                break

        logger.info("audit_purge_complete", deleted=deleted)
    finally:
        await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(purge(dry_run=args.dry_run))
```

À lancer via cron sur l'hôte ou via un sidecar Docker.

**Décision** : pas d'`asyncio.create_task` interne au backend FastAPI. Préférer un cron externe pour l'idempotence et la lisibilité opérationnelle.

## Spécifications techniques

### Index DB

Les index utiles existent déjà au lot 01 :
- `idx_audit_log_occurred_at` (DESC)
- `idx_audit_log_actor_user`
- `idx_audit_log_actor_api_key`
- `idx_audit_log_target_wallet`
- `idx_audit_log_action`

Pour la query du JWT (actor_user OR target_wallet IN owned), Postgres peut utiliser `bitmap or` sur les deux index. À surveiller en prod : si trop lent, ajouter un index composite.

### Pagination cursor

Cursor encode `(occurred_at, id)` en base64 (même pattern que lot 03).

### Limite raisonnable

Hard cap à `limit=200`. Avec un volume normal d'audit log (~1000 events/jour pour un usage modéré), 200 events = ~5h d'historique. Pagination naturelle.

### Endpoint résolution des `actor` et `target`

Le SQL renvoie des UUIDs. L'API renvoie aussi les noms (wallet_name, api_key_name, user_email) pour l'UI. Attention : ces noms peuvent être obsolètes si l'objet a été supprimé (FK SET NULL). Renvoyer alors `null` pour les noms.

```sql
SELECT
    al.*,
    u.email as actor_user_email,
    u.display_name as actor_user_display_name,
    ak.name as actor_api_key_name,
    w.name as target_wallet_name
FROM audit_log al
LEFT JOIN users u ON u.id = al.actor_user_id
LEFT JOIN api_keys ak ON ak.id = al.actor_api_key_id
LEFT JOIN wallets w ON w.id = al.target_wallet_id
WHERE ...
```

## Critères de succès

1. ✅ User connecté voit ses actions
2. ✅ User owner d'un wallet voit les actions de tous (sur ce wallet)
3. ✅ User non-owner et non-acteur ne voit rien d'un wallet
4. ✅ API key voit uniquement ses propres actions
5. ✅ API key qui filtre `actor_user_id=...` autre → résultat vide (filtre forcé prend le pas)
6. ✅ Filtres `since`, `until`, `action`, `wallet_id` fonctionnent
7. ✅ Pagination cursor cohérente
8. ✅ `actions` endpoint retourne la liste exhaustive
9. ✅ Job de purge supprime les events > 90 jours
10. ✅ Job de purge `--dry-run` ne supprime pas
11. ✅ Job de purge tolère un volume élevé (10k+ events) sans timeout

## Pièges connus

- **Filtre forcé pour API key** : crucial. Si un attaquant connaît un `actor_user_id` d'admin, il ne doit PAS pouvoir voir ses actions via une API key. Le filtre `WHERE actor_api_key_id = $self` doit être appliqué AVANT les filtres user (ANDé en bloc), pas en tant que filtre par-dessus.
- **`metadata` JSONB** : les champs sensibles (passphrases, valeurs) ne doivent JAMAIS y apparaître. Vérifier explicitement à l'audit.
- **Cascade SET NULL** : on a configuré `ON DELETE SET NULL` sur `actor_user_id` et `actor_api_key_id` au lot 01. Donc une suppression de user/api_key ne casse pas les logs, mais les rend "anonymes". OK pour MVP.
- **Volume** : un wallet actif peut générer 1000s d'events/jour. Avec rétention 90j, plusieurs millions de lignes. Les index DESC sur `occurred_at` rendent les queries rapides. Surveiller la taille de la table en prod.
- **Race condition à la purge** : si on purge pendant que des events sont en cours d'INSERT, pas de problème (les nouveaux events ont `occurred_at = NOW()` donc loin du cutoff).
- **Cron externe** : documenter dans le `README.md` du backend l'installation du cron. Si oublié, le tableau `audit_log` grossit indéfiniment. Surveiller via `audit_retention_days` dans le `/v1/config/public`.
- **Filtre `action_prefix`** : utiliser `action LIKE 'secret.%'` (avec `%` à la fin uniquement). Postgres optimise bien si l'index existe.
- **`success=false` events** : utile pour détecter les attaques (HMAC invalides, permissions exceeded). Conserver et lister par défaut.

## Tests à écrire

- `test_audit_log_user_sees_own_actions`
- `test_audit_log_owner_sees_all_on_wallet`
- `test_audit_log_user_does_not_see_others_wallets`
- `test_audit_log_api_key_only_sees_own_actions`
- `test_audit_log_api_key_filter_actor_user_ignored`
- `test_audit_log_filter_action`
- `test_audit_log_filter_since_until`
- `test_audit_log_pagination`
- `test_audit_log_actions_list_endpoint`
- `test_purge_dry_run_no_delete`
- `test_purge_deletes_old_events`
- `test_purge_keeps_recent_events`
- `test_purge_handles_large_volume`

## Ce qui suit

Le **lot 11** clôt le projet : UI web React + Mantine pour les utilisateurs humains.
