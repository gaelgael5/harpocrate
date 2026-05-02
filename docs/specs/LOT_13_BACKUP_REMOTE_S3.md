# Lot 13 — Backup distant S3 multi-destinations

> **Prérequis** : Lots 00-12.

## Objectif

Étendre le système de backup avec des **destinations distantes S3-compatibles** (Cloudflare R2, Backblaze B2, MinIO, Garage, AWS S3, Scaleway, OVH, Wasabi). Multi-destination simultané. **Object Lock / Immutability** pour protection ransomware.

## Dépendances

- Lots 00-12

## Périmètre

### Inclus

- Driver unique `S3v4Driver` qui couvre tous les services compatibles S3 v4
- Configuration multi-destination via JSON dans une env var ou table DB
- Endpoints `/v1/admin/backups/remote/*` : list, push, pull, configure
- Object Lock optionnel via `backup_s3_object_lock_days`
- Push synchrone ou asynchrone (background task)
- Restore depuis distant : pull + restore standard
- UI page `/admin/backups/remote` : liste destinations, statut, push manuel
- CLI `harpocrate-admin remote-backup push|list|pull`

### Exclus

- Pas de cron (lot 14)
- Pas de réplication cross-region automatique
- Pas de déduplication ni de compression delta

## Spécifications fonctionnelles

### Destinations supportées

Toutes via S3 v4 standard avec custom endpoint :

| Service | Endpoint pattern | Region | Object Lock | Notes |
|---|---|---|---|---|
| **AWS S3** | `s3.{region}.amazonaws.com` | us-east-1, eu-west-1, etc. | ✅ | classique |
| **Cloudflare R2** | `{account_id}.r2.cloudflarestorage.com` | auto | ❌ (versioning OK) | pas d'egress fees |
| **Backblaze B2** | `s3.{region}.backblazeb2.com` | us-west-002, etc. | ✅ | très bon prix |
| **MinIO** | `minio.example.com` | us-east-1 (alias) | ✅ | self-hosted |
| **Garage** | `garage.example.com` | garage | ❌ (Object Lock partial) | self-hosted, bon pour homelab |
| **Scaleway** | `s3.{region}.scw.cloud` | fr-par, etc. | ✅ | EU, GDPR |
| **OVH Object Storage** | `s3.{region}.cloud.ovh.net` | gra, etc. | ✅ | EU |
| **Wasabi** | `s3.{region}.wasabisys.com` | us-east-1, etc. | ✅ | bon prix |

### Configuration multi-destination

Stockée dans une table DB (pour pouvoir modifier sans restart) :

```sql
-- migrations/004_backup_remote.sql
CREATE TABLE backup_remote_destinations (
    id                              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                            TEXT NOT NULL UNIQUE,
    enabled                         BOOLEAN NOT NULL DEFAULT TRUE,

    -- S3 v4 config
    endpoint_url                    TEXT NOT NULL,
    region                          TEXT NOT NULL,
    bucket                          TEXT NOT NULL,
    prefix                          TEXT,

    -- Credentials (sensible, séparé)
    access_key_id                   TEXT NOT NULL,
    secret_access_key_encrypted     BYTEA NOT NULL,  -- chiffré par HMAC_KEY ou similaire

    -- Options
    object_lock_days                INTEGER NOT NULL DEFAULT 0,
    storage_class                   TEXT,  -- ex: "GLACIER", "DEEP_ARCHIVE" pour AWS
    use_path_style                  BOOLEAN NOT NULL DEFAULT FALSE,  -- requis pour MinIO/Garage

    -- Stats
    last_push_at                    TIMESTAMPTZ,
    last_push_success               BOOLEAN,
    last_push_error                 TEXT,

    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by_user_id              UUID REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX idx_backup_remote_enabled ON backup_remote_destinations(enabled)
    WHERE enabled = TRUE;
```

Le `secret_access_key` est chiffré au repos avec une clé dérivée du `HMAC_KEY` du serveur (réutilisation de la clé maître pour ne pas créer une 4e clé). Décrypté en RAM uniquement au moment de l'usage.

### Endpoints

#### `POST /v1/admin/backups/remote/destinations`

- **Auth** : JWT + admin + reverify
- **Body** :
```json
{
  "name": "r2-primary",
  "endpoint_url": "https://abc123.r2.cloudflarestorage.com",
  "region": "auto",
  "bucket": "harpocrate-backups",
  "prefix": "prod/",
  "access_key_id": "AKIAIOSFODNN7EXAMPLE",
  "secret_access_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
  "object_lock_days": 30,
  "use_path_style": false
}
```
- **Effets** :
  - INSERT dans `backup_remote_destinations`
  - Test connectivité immédiat (HEAD bucket)
  - Si Object Lock demandé, verify que le bucket le supporte
- **Réponse** : `201 { "destination_id": "...", "test_result": "ok" }`

#### `GET /v1/admin/backups/remote/destinations`

Liste des destinations avec statut.

#### `PATCH /v1/admin/backups/remote/destinations/{id}`

Modifier nom, prefix, enabled, object_lock_days, etc. Pas les credentials (utiliser DELETE + recreate pour la rotation).

#### `DELETE /v1/admin/backups/remote/destinations/{id}`

Suppression (avec reverify).

#### `POST /v1/admin/backups/{backup_id}/push-remote`

- **Auth** : JWT + admin
- **Body** :
```json
{
  "destination_ids": ["uuid1", "uuid2"],
  "async": false
}
```
- **Effets** :
  - Pour chaque destination, upload du `.tar.age` via S3 PUT
  - Si `object_lock_days > 0`, ajouter le header `x-amz-object-lock-mode=GOVERNANCE` (ou COMPLIANCE) et `x-amz-object-lock-retain-until-date`
  - Update `last_push_at`, `last_push_success`
  - Audit log `admin.backup_pushed_remote`
- **Réponse** :
```json
{
  "results": [
    { "destination_id": "uuid1", "name": "r2-primary", "success": true, "duration_ms": 3450, "size_bytes": 12340567 },
    { "destination_id": "uuid2", "name": "b2-secondary", "success": false, "error": "..." }
  ]
}
```

#### `GET /v1/admin/backups/remote/list`

- **Auth** : JWT + admin
- **Query** : `destination_id`, `prefix`, `since`, `until`
- **Réponse** :
```json
{
  "destination": { "id": "uuid", "name": "r2-primary" },
  "remote_backups": [
    {
      "key": "prod/harpocrate-backup-2026-05-02-14-23-00.tar.age",
      "size_bytes": 12340567,
      "last_modified": "2026-05-02T14:23:30Z",
      "etag": "...",
      "object_lock_retain_until": "2026-06-01T14:23:30Z",
      "exists_locally": true,
      "local_id": "uuid"
    }
  ]
}
```

`exists_locally`: indique si une copie locale existe (matching filename).

#### `POST /v1/admin/backups/remote/pull`

- **Auth** : JWT + admin
- **Body** :
```json
{
  "destination_id": "uuid",
  "key": "prod/harpocrate-backup-...tar.age"
}
```
- **Effets** :
  - Download de S3 vers `/var/lib/harpocrate/backups/`
  - INSERT dans `backups_local` avec `imported=TRUE`
- **Réponse** : `201 { "backup_id": "uuid" }`

### Page UI `/admin/backups/remote`

```
Remote backup destinations
═══════════════════════════════════════════════════

Configured destinations:

┌────────────────┬────────────────────────────┬─────────┬──────────┬──────────┐
│ Name           │ Endpoint                   │ Bucket  │ Lock     │ Last push│
├────────────────┼────────────────────────────┼─────────┼──────────┼──────────┤
│ r2-primary     │ abc123.r2.cloudflare...    │ ...     │ ✓ 30d    │ 2h ago ✓ │
│ b2-secondary   │ s3.us-w-002.bb.com         │ ...     │ ✓ 30d    │ 2h ago ✓ │
│ minio-homelab  │ minio.yoops.org            │ ...     │ ✓ 90d    │ 2h ago ✓ │
└────────────────┴────────────────────────────┴─────────┴──────────┴──────────┘

[+ Add destination]

─── Push existing backup to remote ───

Select backup:    [harpocrate-backup-2026-05-02-14-23-00.tar.age ▾]
Select destinations:
  ☑ r2-primary
  ☑ b2-secondary
  ☐ minio-homelab

[Push to selected destinations]

─── Browse remote backups ───

Destination: [r2-primary ▾]
Prefix: [prod/]

┌──────────────────────────────────────────┬─────────┬──────────┬─────────┐
│ Key                                       │ Size    │ Modified │ Lock    │
├──────────────────────────────────────────┼─────────┼──────────┼─────────┤
│ prod/harpocrate-backup-2026-05-02-...    │ 12.3 MB │ 2h ago   │ to 6/01 │
│ prod/harpocrate-backup-2026-05-01-...    │ 12.1 MB │ 26h ago  │ to 5/31 │
│ ...                                       │         │          │         │
└──────────────────────────────────────────┴─────────┴──────────┴─────────┘
```

### Modal "Add destination"

Wizard en 3 étapes :

**Step 1 — Type de service** (presets pour les services connus) :

```
Select service type:

  ◯ AWS S3
  ◉ Cloudflare R2
  ◯ Backblaze B2
  ◯ MinIO (self-hosted)
  ◯ Garage (self-hosted)
  ◯ Scaleway
  ◯ OVH
  ◯ Wasabi
  ◯ Custom S3 v4
```

Le choix pré-remplit le pattern d'endpoint, les paramètres (`use_path_style`), etc.

**Step 2 — Configuration** : endpoint complet, bucket, region, prefix, credentials, Object Lock.

**Step 3 — Test et confirmation** : test de connexion en live, affichage du résultat, confirmation finale.

## Spécifications techniques

### Driver S3v4

```python
# app/services/backup_remote.py

import aioboto3
from typing import Optional


class S3v4Driver:
    def __init__(
        self,
        endpoint_url: str,
        region: str,
        access_key_id: str,
        secret_access_key: str,
        use_path_style: bool = False,
    ):
        self.endpoint_url = endpoint_url
        self.region = region
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.use_path_style = use_path_style

    def _client_config(self):
        from botocore.config import Config
        return Config(
            signature_version="s3v4",
            s3={"addressing_style": "path" if self.use_path_style else "virtual"},
        )

    async def put_object(
        self,
        bucket: str,
        key: str,
        data: bytes | bytearray | "AsyncIterable[bytes]",
        object_lock_days: int = 0,
        storage_class: Optional[str] = None,
    ) -> dict:
        session = aioboto3.Session()
        async with session.client(
            "s3",
            endpoint_url=self.endpoint_url,
            region_name=self.region,
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            config=self._client_config(),
        ) as s3:
            kwargs = {
                "Bucket": bucket,
                "Key": key,
                "Body": data,
            }
            if storage_class:
                kwargs["StorageClass"] = storage_class
            if object_lock_days > 0:
                from datetime import datetime, timedelta
                retain_until = datetime.utcnow() + timedelta(days=object_lock_days)
                kwargs["ObjectLockMode"] = "GOVERNANCE"  # ou COMPLIANCE pour stricter
                kwargs["ObjectLockRetainUntilDate"] = retain_until

            return await s3.put_object(**kwargs)

    async def list_objects(
        self,
        bucket: str,
        prefix: str = "",
        max_keys: int = 1000,
    ) -> list[dict]:
        session = aioboto3.Session()
        async with session.client(
            "s3",
            endpoint_url=self.endpoint_url,
            region_name=self.region,
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            config=self._client_config(),
        ) as s3:
            response = await s3.list_objects_v2(
                Bucket=bucket, Prefix=prefix, MaxKeys=max_keys
            )
            return response.get("Contents", [])

    async def get_object(self, bucket: str, key: str) -> bytes:
        session = aioboto3.Session()
        async with session.client(
            "s3",
            endpoint_url=self.endpoint_url,
            region_name=self.region,
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            config=self._client_config(),
        ) as s3:
            response = await s3.get_object(Bucket=bucket, Key=key)
            return await response["Body"].read()

    async def head_bucket(self, bucket: str) -> bool:
        try:
            session = aioboto3.Session()
            async with session.client(
                "s3",
                endpoint_url=self.endpoint_url,
                region_name=self.region,
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                config=self._client_config(),
            ) as s3:
                await s3.head_bucket(Bucket=bucket)
                return True
        except Exception:
            return False

    async def get_object_lock_configuration(self, bucket: str) -> dict | None:
        try:
            session = aioboto3.Session()
            async with session.client(
                "s3",
                endpoint_url=self.endpoint_url,
                region_name=self.region,
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                config=self._client_config(),
            ) as s3:
                response = await s3.get_object_lock_configuration(Bucket=bucket)
                return response.get("ObjectLockConfiguration")
        except Exception:
            return None  # Non supporté ou non configuré
```

### Service multi-destination

```python
class RemoteBackupService:
    def __init__(self, pool, settings, hmac_key):
        self.pool = pool
        self.settings = settings
        self.hmac_key = hmac_key  # pour déchiffrer les secret_access_key

    async def push(self, backup_id: UUID, destination_ids: list[UUID]) -> list[PushResult]:
        async with self.pool.acquire() as conn:
            backup = await conn.fetchrow(
                "SELECT * FROM backups_local WHERE id = $1", backup_id
            )
            destinations = await conn.fetch(
                "SELECT * FROM backup_remote_destinations WHERE id = ANY($1)",
                destination_ids,
            )

        backup_path = Path(self.settings.backup_local_path) / backup["filename"]

        results = []
        for dest in destinations:
            try:
                driver = self._build_driver(dest)
                key = (dest["prefix"] or "") + backup["filename"]

                with open(backup_path, "rb") as f:
                    data = f.read()

                await driver.put_object(
                    bucket=dest["bucket"],
                    key=key,
                    data=data,
                    object_lock_days=dest["object_lock_days"],
                )

                async with self.pool.acquire() as conn:
                    await conn.execute(
                        """UPDATE backup_remote_destinations
                           SET last_push_at = NOW(), last_push_success = TRUE,
                               last_push_error = NULL WHERE id = $1""",
                        dest["id"],
                    )

                results.append(PushResult(success=True, ...))
            except Exception as e:
                async with self.pool.acquire() as conn:
                    await conn.execute(
                        """UPDATE backup_remote_destinations
                           SET last_push_at = NOW(), last_push_success = FALSE,
                               last_push_error = $1 WHERE id = $2""",
                        str(e), dest["id"],
                    )
                results.append(PushResult(success=False, error=str(e), ...))

        return results

    def _build_driver(self, dest_row) -> S3v4Driver:
        secret = decrypt_with_hmac_key(dest_row["secret_access_key_encrypted"], self.hmac_key)
        return S3v4Driver(
            endpoint_url=dest_row["endpoint_url"],
            region=dest_row["region"],
            access_key_id=dest_row["access_key_id"],
            secret_access_key=secret,
            use_path_style=dest_row["use_path_style"],
        )
```

## Critères de succès

1. ✅ Driver fonctionne avec AWS S3 (test live ou MinIO local en lieu et place)
2. ✅ Driver fonctionne avec MinIO (path style)
3. ✅ Driver fonctionne avec R2 (virtual host style)
4. ✅ Configuration destinations en DB
5. ✅ `secret_access_key` chiffré au repos
6. ✅ `POST /push-remote` envoie sur 1+ destinations en parallèle
7. ✅ Object Lock activé quand demandé (vérifiable côté S3)
8. ✅ Object Lock empêche le DELETE (test : tenter de delete avant retain_until → erreur)
9. ✅ `GET /list` retourne les objets distants
10. ✅ `POST /pull` télécharge un backup distant en local
11. ✅ Restore depuis local pulled → fonctionne comme un local classique
12. ✅ Test de connectivité au moment de la création de destination
13. ✅ UI permet de configurer/lister/push
14. ✅ Audit log

## Pièges connus

- **`use_path_style`** : MinIO et Garage requièrent path style. R2/B2/AWS sont en virtual hosted style. Le toggle est important.
- **R2 region "auto"** : Cloudflare R2 utilise `region="auto"`. AWS rejette ça. À conditionner.
- **Object Lock GOVERNANCE vs COMPLIANCE** : GOVERNANCE peut être levé par un admin S3, COMPLIANCE non. Pour MVP : GOVERNANCE (pour permettre le ménage manuel en cas de bug).
- **Object Lock + bucket déjà existant** : impossible d'activer Object Lock après coup sur certains providers. Le bucket doit être créé avec Object Lock dès le départ. Documenter.
- **Storage class GLACIER** : nécessite restore avant download. Coûteux. Pour MVP : ne pas proposer dans l'UI, juste exposer en config.
- **Multipart upload** : pour fichiers > 100 MB. `aioboto3` le gère automatiquement. À tester en CI.
- **Credentials chiffrées** : la clé de chiffrement est la `HMAC_KEY` du serveur. Si elle est perdue, les credentials sont irrécupérables. Documenter dans `04_backup_restore.md`.
- **Multi-region pour mono-destination** : R2 gère ça en interne. Pour AWS, créer 2 destinations dans 2 régions différentes.
- **Quota S3** : monitorer. Sinon push silencieux qui échoue.

## Tests

- `test_s3v4_driver_aws`
- `test_s3v4_driver_minio_path_style`
- `test_object_lock_set_correctly`
- `test_object_lock_prevents_delete`
- `test_multi_destination_push`
- `test_push_partial_failure`
- `test_pull_remote_backup`
- `test_restore_from_pulled_remote`
- `test_credentials_encrypted_at_rest`
- `test_credentials_decryption_with_hmac_key`
- `test_connectivity_test_at_destination_create`

## Ce qui suit

Le **lot 14** ajoute le cron de snapshots automatisés avec rotation GFS.
