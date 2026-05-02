# Lot 12a — Backend backup / restore + mode maintenance

> **Prérequis** : Lots 00-11.

## Objectif

Implémenter le **backend complet** du backup/restore : endpoints admin, format `age` à clé admin, mode maintenance, invalidation de sessions post-restore, CLI admin standalone, intégration des env vars non-sensibles dans le backup principal.

C'est le **lot bloquant** pour aller en production. Sans lui, perte de la base = perte définitive des secrets.

## Dépendances

- Lots 00-11

## Périmètre

### Inclus

- Endpoints `/v1/admin/backups/*` complet (list, create, get, download, manifest, upload, verify, delete, restore)
- Endpoints `/v1/admin/maintenance/*` (enable, disable, status)
- Format de backup : `harpocrate-backup-{ts}.tar.age`
  - Contenu : `dump.sql.gz`, `env-non-sensitive.json`, `manifest.json`
  - Chiffrement `age` avec clé admin (publique connue du serveur)
  - Checksum SHA-256 inclus dans le manifest
- Stockage local : `/var/lib/harpocrate/backups/` (volume Docker)
- CLI admin `harpocrate-admin` (Python + click) qui appelle les endpoints (utilisable en SSH)
- Détection du rôle Keycloak `harpocrate-admin` dans le JWT
- Rotation du `server_session_epoch` après restore (invalidation des sessions actives)
- Audit log complet pour toutes les opérations admin
- Tests E2E de round-trip backup → drop database → restore

### Exclus

- Pas d'UI admin (lot 12b)
- Pas de backup distant S3 (lot 13)
- Pas de cron snapshots (lot 14)
- Pas de gestion env sensibles (lot 12e)

## Spécifications fonctionnelles

### Format du fichier de backup

Une archive TAR chiffrée par `age` :

```
harpocrate-backup-2026-05-02-14-23-00.tar.age
└── (déchiffré) :
    backup.tar
    ├── manifest.json
    ├── dump.sql.gz
    └── env-non-sensitive.json
```

#### `manifest.json`

```json
{
  "format_version": "1",
  "harpocrate_version": "0.1.0",
  "created_at": "2026-05-02T14:23:00.123Z",
  "created_by": {
    "user_id": "uuid",
    "email": "gael@yoops.org"
  },
  "description": "Pre-migration backup",
  "checksums": {
    "dump_sql_gz": "sha256:a3f2...",
    "env_non_sensitive_json": "sha256:b4e8..."
  },
  "stats": {
    "users_count": 4,
    "wallets_count": 12,
    "secrets_count": 87,
    "api_keys_count": 8,
    "audit_log_entries_count": 2340
  },
  "age_recipient": "age1qyqszqgpqyqszqgpqyqszqgpqyq...",
  "schema_version": "001",
  "session_epoch_at_backup": 42
}
```

#### `dump.sql.gz`

Le résultat de `pg_dump --format=plain` gzippé. Inclut tout : schéma, triggers, données, séquences, server_session_epoch.

#### `env-non-sensitive.json`

```json
{
  "HARPOCRATE_KEYCLOAK_URL": "https://keycloak.yoops.org",
  "HARPOCRATE_KEYCLOAK_REALM": "harpocrate",
  "HARPOCRATE_KEYCLOAK_CLIENT_ID": "harpocrate",
  "HARPOCRATE_AGE_PUBLIC_KEY": "age1...",
  "HARPOCRATE_KDF_MEMORY_KB": 65536,
  "HARPOCRATE_KDF_ITERATIONS": 3,
  "HARPOCRATE_AUDIT_RETENTION_DAYS": 90,
  "HARPOCRATE_PUBLIC_URL": "https://harpocrate.yoops.org",
  "...": "..."
}
```

Variables `is_secret=True` exclues. Voir lot 12e pour leur backup séparé.

### `POST /v1/admin/backups`

- **Auth** : JWT + rôle `harpocrate-admin`
- **Body** :
```json
{
  "description": "Pre-migration backup"
}
```
- **Effets** :
  1. `pg_dump --format=plain --serializable-deferrable | gzip` → `/tmp/dump.sql.gz`
  2. Sérialisation des env non-sensibles → `/tmp/env-non-sensitive.json`
  3. Calcul des SHA-256
  4. Composition du `manifest.json`
  5. Création de `backup.tar` avec les 3 fichiers
  6. Chiffrement : `age -r $HARPOCRATE_AGE_PUBLIC_KEY -o backup.tar.age backup.tar`
  7. Move vers `/var/lib/harpocrate/backups/harpocrate-backup-{ts}.tar.age`
  8. INSERT dans une table `backups_local` (voir DDL ci-dessous)
- **Réponse** : `201`
```json
{
  "backup_id": "uuid",
  "filename": "harpocrate-backup-2026-05-02-14-23-00.tar.age",
  "size_bytes": 12340567,
  "created_at": "...",
  "stats": { "users_count": 4, ... }
}
```
- **Audit** : `admin.backup_created`

### `GET /v1/admin/backups`

- **Auth** : JWT + admin
- **Query** : `limit`, `cursor`, `since`, `until`
- **Réponse** :
```json
{
  "backups": [
    {
      "id": "uuid",
      "filename": "...",
      "size_bytes": ...,
      "created_at": "...",
      "created_by_email": "gael@yoops.org",
      "description": "...",
      "stats": { ... },
      "checksum_sha256": "..."
    }
  ],
  "next_cursor": null
}
```

### `GET /v1/admin/backups/{id}`

- **Auth** : JWT + admin
- **Réponse** : détails complets du backup (manifest inclus)

### `GET /v1/admin/backups/{id}/manifest`

- **Auth** : JWT + admin
- **Réponse** : juste le manifest, sans déchiffrer le tar.age. Utile pour l'UI qui veut afficher les stats.
- **Implémentation** : le manifest est stocké en clair dans la table `backups_local` (extrait du tar.age au moment de la création).

### `GET /v1/admin/backups/{id}/download`

- **Auth** : JWT + admin
- **Réponse** : streaming du fichier `.tar.age`
- **Headers** : `Content-Type: application/octet-stream`, `Content-Disposition: attachment; filename=...`
- **Audit** : `admin.backup_downloaded` (sensible)

### `POST /v1/admin/backups/upload`

- **Auth** : JWT + admin
- **Body** : `multipart/form-data` avec field `file` (le `.tar.age`)
- **Streaming** : le serveur écrit chunks dans un fichier temporaire pour éviter saturation RAM
- **Validations** :
  - Fichier `.age` valide (header magic)
  - Taille raisonnable (< 1 GB par défaut, configurable)
- **Effets** :
  - Déplace vers `/var/lib/harpocrate/backups/uploaded-{ts}-{filename}`
  - Tente d'extraire le manifest **sans déchiffrement** (impossible — il faut la clé) → marqué comme "manifest unknown until restore preview"
  - INSERT dans `backups_local` avec flag `imported=TRUE`
- **Réponse** : `201 { "backup_id": "uuid" }`
- **Audit** : `admin.backup_uploaded`

### `POST /v1/admin/backups/{id}/verify`

- **Auth** : JWT + admin
- **Body** :
```json
{
  "age_private_key": "AGE-SECRET-KEY-1..."
}
```
- **Effets** :
  - Tente de déchiffrer en mémoire (sans persister la clé)
  - Vérifie que le tar contient bien manifest + dump + env
  - Vérifie les checksums internes
  - Ne fait PAS de restore
- **Réponse** :
```json
{
  "valid": true,
  "manifest": { ... },
  "checksums_match": true,
  "dump_sql_lines": 12345
}
```
- **Audit** : `admin.backup_verified`
- **Notes** : la clé privée n'est jamais persistée. Logs explicites : "private key received, used to decrypt, discarded".

### `DELETE /v1/admin/backups/{id}`

- **Auth** : JWT + admin + reverify token
- **Effets** : suppression du fichier + ligne en DB
- **Audit** : `admin.backup_deleted`

### `POST /v1/admin/backups/{id}/restore`

- **Auth** : JWT + admin + reverify token
- **Body** :
```json
{
  "age_private_key": "AGE-SECRET-KEY-1...",
  "confirmation": "RESTORE harpocrate-backup-2026-05-02-14-23-00",
  "auto_enable_maintenance": true
}
```
- **Validations** :
  - `confirmation` matche exactement `RESTORE {filename without .tar.age}`
  - `age_private_key` déchiffre bien le backup
  - Manifest valide, checksums OK
- **Effets** (idempotent et atomique autant que possible) :
  1. Si `auto_enable_maintenance` : POST `/admin/maintenance/enable` interne
  2. Décrypter `.tar.age` → `.tar`, extraire dump.sql.gz et env-non-sensitive.json
  3. Vérifier checksums
  4. **Drop existing schema** : `DROP SCHEMA public CASCADE; CREATE SCHEMA public;`
  5. Replay dump : `psql < dump.sql`
  6. **Rotate `server_session_epoch`** (raison: "post_restore_at_{ts}")
  7. Charger les env non-sensibles : génère un fichier `.env.restore` à appliquer manuellement (le serveur ne se redémarre pas tout seul)
  8. Mettre à jour `last_restored_at` quelque part en DB (table `system_metadata`)
  9. Si `auto_enable_maintenance` : disable maintenance après restore réussi
- **Réponse** :
```json
{
  "success": true,
  "restored_at": "...",
  "restored_from_backup_id": "uuid",
  "stats_after": { ... },
  "session_epoch_new": 43,
  "env_restore_file_path": "/var/lib/harpocrate/.env.restore.20260502_142300",
  "next_actions": [
    "Review /var/lib/harpocrate/.env.restore.* and merge into your .env if needed",
    "All active sessions are invalidated, users must re-login"
  ]
}
```
- **Audit** : `admin.restore_executed` avec metadata `{backup_id, session_epoch_old, session_epoch_new}`
- **Pendant l'opération** : toutes les autres requêtes mutatives sont bloquées en 503 par le mode maintenance

### `POST /v1/admin/maintenance/enable`

- **Auth** : JWT + admin
- **Body** :
```json
{
  "reason": "Database restore in progress",
  "delay_seconds": 30,
  "estimated_duration_minutes": 5
}
```
- **Effets** :
  - Set variable globale `MAINTENANCE_MODE = True` (en RAM, et dans une table `system_metadata` pour persistance)
  - Diffusion via WebSocket (lot 11) ou polling : tous les clients UI reçoivent l'event
  - Si `delay_seconds > 0` : countdown UI avant blocage effectif
  - Audit log
- **Réponse** : `200 { "maintenance_started_at": "...", "effective_at": "..." }`

### `POST /v1/admin/maintenance/disable`

- **Auth** : JWT + admin
- **Effets** : désactive le mode maintenance
- **Audit** : `admin.maintenance_disabled`

### `GET /v1/admin/maintenance/status`

- **Auth** : aucune (publique pour que les clients sachent)
- **Réponse** :
```json
{
  "active": true,
  "started_at": "...",
  "effective_at": "...",
  "estimated_end_at": "...",
  "reason": "Database restore in progress"
}
```

### Middleware mode maintenance

```python
@app.middleware("http")
async def maintenance_middleware(request: Request, call_next):
    if MAINTENANCE_MODE_ACTIVE:
        # Toujours autoriser les endpoints admin et health
        if (request.url.path.startswith("/v1/admin/")
            or request.url.path == "/v1/health"
            or request.url.path == "/v1/maintenance/status"):
            return await call_next(request)

        # Tout le reste : 503
        return JSONResponse(
            status_code=503,
            content={
                "error": "maintenance_in_progress",
                "estimated_end_at": MAINTENANCE_END_AT,
            },
            headers={"Retry-After": str(retry_seconds)},
        )

    return await call_next(request)
```

## Spécifications techniques

### Migration DDL ajoutée (lot 12)

`migrations/002_backup_tables.sql` :

```sql
CREATE TABLE backups_local (
    id                              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename                        TEXT NOT NULL UNIQUE,
    size_bytes                      BIGINT NOT NULL,
    checksum_sha256                 TEXT NOT NULL,
    age_recipient                   TEXT NOT NULL,
    manifest                        JSONB NOT NULL,
    description                     TEXT,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by_user_id              UUID REFERENCES users(id) ON DELETE SET NULL,
    imported                        BOOLEAN NOT NULL DEFAULT FALSE,

    CONSTRAINT backups_local_filename_format
        CHECK (filename ~ '^harpocrate-backup-.*\.tar\.age$' OR imported = TRUE)
);

CREATE INDEX idx_backups_local_created_at ON backups_local(created_at DESC);

CREATE TABLE system_metadata (
    key                             TEXT PRIMARY KEY,
    value                           JSONB NOT NULL,
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO system_metadata (key, value) VALUES
    ('maintenance_mode', '{"active": false}'::jsonb),
    ('last_restored_at', 'null'::jsonb),
    ('last_backup_at', 'null'::jsonb);
```

### Module `app/services/backup.py`

```python
import asyncio
import gzip
import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from datetime import datetime
from uuid import uuid4

from app.core.config import settings, Settings
from app.core.logging import logger


class BackupService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.backup_dir = Path(settings.backup_local_path)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    async def create_backup(
        self,
        description: str | None,
        created_by_user_id: UUID,
        created_by_email: str,
    ) -> BackupRecord:
        timestamp = datetime.utcnow().strftime("%Y-%m-%d-%H-%M-%S")
        filename = f"harpocrate-backup-{timestamp}.tar.age"
        out_path = self.backup_dir / filename

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            # 1. pg_dump
            logger.info("backup_pg_dump_start")
            dump_path = tmp / "dump.sql"
            with open(dump_path, "wb") as out:
                proc = await asyncio.create_subprocess_exec(
                    "pg_dump",
                    self.settings.db_dsn,
                    "--format=plain",
                    "--serializable-deferrable",
                    "--no-owner",
                    "--no-acl",
                    stdout=out,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await proc.communicate()
                if proc.returncode != 0:
                    raise BackupError(f"pg_dump failed: {stderr.decode()}")

            # 2. gzip
            dump_gz_path = tmp / "dump.sql.gz"
            with open(dump_path, "rb") as f_in, gzip.open(dump_gz_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
            dump_path.unlink()

            # 3. Env non-sensitive
            env_path = tmp / "env-non-sensitive.json"
            non_sensitive = self._extract_non_sensitive_env()
            env_path.write_text(json.dumps(non_sensitive, indent=2))

            # 4. Stats
            stats = await self._compute_stats()

            # 5. Manifest
            manifest = {
                "format_version": "1",
                "harpocrate_version": "0.1.0",
                "created_at": datetime.utcnow().isoformat() + "Z",
                "created_by": {
                    "user_id": str(created_by_user_id),
                    "email": created_by_email,
                },
                "description": description,
                "checksums": {
                    "dump_sql_gz": "sha256:" + sha256_file(dump_gz_path),
                    "env_non_sensitive_json": "sha256:" + sha256_file(env_path),
                },
                "stats": stats,
                "age_recipient": self.settings.age_public_key,
                "schema_version": "001",
                "session_epoch_at_backup": await get_current_session_epoch(),
            }
            manifest_path = tmp / "manifest.json"
            manifest_path.write_text(json.dumps(manifest, indent=2))

            # 6. Tar
            tar_path = tmp / "backup.tar"
            with tarfile.open(tar_path, "w") as tar:
                tar.add(manifest_path, arcname="manifest.json")
                tar.add(dump_gz_path, arcname="dump.sql.gz")
                tar.add(env_path, arcname="env-non-sensitive.json")

            # 7. Age encrypt
            tar_age_path = tmp / "backup.tar.age"
            proc = await asyncio.create_subprocess_exec(
                "age",
                "-r", self.settings.age_public_key,
                "-o", str(tar_age_path),
                str(tar_path),
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise BackupError(f"age encryption failed: {stderr.decode()}")

            # 8. Final checksum + move
            final_checksum = sha256_file(tar_age_path)
            shutil.move(str(tar_age_path), str(out_path))

        # 9. DB record
        size = out_path.stat().st_size
        return await self._insert_record(
            filename=filename,
            size=size,
            checksum=final_checksum,
            manifest=manifest,
            description=description,
            created_by_user_id=created_by_user_id,
        )

    def _extract_non_sensitive_env(self) -> dict:
        result = {}
        for name, field in Settings.model_fields.items():
            is_secret = (field.json_schema_extra or {}).get("is_secret", False)
            if is_secret:
                continue
            value = getattr(self.settings, name)
            # Convertir en JSON-serializable
            result[f"HARPOCRATE_{name.upper()}"] = value
        return result

    async def restore(
        self,
        backup_id: UUID,
        age_private_key: str,
        actor_user_id: UUID,
    ) -> RestoreResult:
        record = await self._fetch_record(backup_id)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            # 1. Decrypt
            tar_path = tmp / "backup.tar"
            proc = await asyncio.create_subprocess_exec(
                "age", "-d",
                "-i", "-",  # private key from stdin
                "-o", str(tar_path),
                str(self.backup_dir / record.filename),
                stdin=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate(input=age_private_key.encode())
            if proc.returncode != 0:
                raise RestoreError(f"age decryption failed: {stderr.decode()}")

            # 2. Extract
            with tarfile.open(tar_path) as tar:
                tar.extractall(tmp / "extracted")
            extracted = tmp / "extracted"

            # 3. Verify checksums
            manifest = json.loads((extracted / "manifest.json").read_text())
            for fname, expected in manifest["checksums"].items():
                fpath = extracted / fname.replace("_", ".")
                actual = "sha256:" + sha256_file(fpath)
                if actual != expected:
                    raise RestoreError(f"Checksum mismatch on {fname}")

            # 4. Drop schema + replay dump
            dump_gz = extracted / "dump.sql.gz"
            with gzip.open(dump_gz, "rt") as f_dump:
                # Run via psql piped from dump
                proc = await asyncio.create_subprocess_exec(
                    "psql", self.settings.db_dsn,
                    "-c", "DROP SCHEMA public CASCADE; CREATE SCHEMA public;",
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await proc.communicate()
                if proc.returncode != 0:
                    raise RestoreError(f"DROP SCHEMA failed: {stderr.decode()}")

                proc = await asyncio.create_subprocess_exec(
                    "psql", self.settings.db_dsn,
                    stdin=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await proc.communicate(input=f_dump.read().encode())
                if proc.returncode != 0:
                    raise RestoreError(f"psql replay failed: {stderr.decode()}")

            # 5. Rotate session epoch
            new_epoch = await rotate_session_epoch(reason=f"post_restore_backup_{backup_id}")

            # 6. Save env-restore file
            env_restore = json.loads((extracted / "env-non-sensitive.json").read_text())
            env_restore_path = Path("/var/lib/harpocrate") / f".env.restore.{int(time.time())}"
            with open(env_restore_path, "w") as f:
                for k, v in env_restore.items():
                    f.write(f"{k}={v}\n")

            return RestoreResult(
                success=True,
                restored_from_backup_id=backup_id,
                session_epoch_new=new_epoch,
                env_restore_file_path=str(env_restore_path),
            )
```

### CLI admin standalone

`harpocrate-admin` (Python click) :

```bash
harpocrate-admin backup [--description TEXT]
harpocrate-admin list-backups
harpocrate-admin show-backup <id>
harpocrate-admin verify <id> --age-key-file ~/.harpocrate/age.key
harpocrate-admin restore <id> --age-key-file ~/.harpocrate/age.key
harpocrate-admin maintenance enable [--reason TEXT]
harpocrate-admin maintenance disable
harpocrate-admin maintenance status
```

Configuration via env :
```
HARPOCRATE_ADMIN_URL=https://harpocrate.yoops.org
HARPOCRATE_ADMIN_TOKEN=<JWT obtained via OAuth flow>
```

L'admin lance `harpocrate-admin login` au début de session pour obtenir un JWT (flow OAuth standard, similaire à `gh auth login`).

## Critères de succès

1. ✅ `POST /v1/admin/backups` crée un fichier `.tar.age` valide
2. ✅ Le fichier est déchiffrable avec `age -d -i admin.key`
3. ✅ Le tar contient manifest, dump.sql.gz, env-non-sensitive.json
4. ✅ Manifest contient stats correctes
5. ✅ `GET /v1/admin/backups` liste le backup
6. ✅ `GET /v1/admin/backups/{id}/download` stream le fichier
7. ✅ Upload depuis poste fonctionne
8. ✅ Verify avec mauvaise clé `age` → erreur claire
9. ✅ Restore complet fonctionne : DROP + replay
10. ✅ Après restore, session_epoch incrémenté
11. ✅ Tous les users sont déconnectés (409 session_invalidated_by_restore au prochain appel)
12. ✅ Mode maintenance bloque les requêtes non-admin (503)
13. ✅ Mode maintenance laisse passer `/v1/health`
14. ✅ Confirmation textuelle exacte requise pour restore
15. ✅ Reverify token requis pour restore et delete
16. ✅ Audit log complet
17. ✅ CLI `harpocrate-admin backup` fonctionne en SSH
18. ✅ Round-trip complet validé : backup → drop database → restore → user reconnecte → secret toujours déchiffrable

## Pièges connus

- **`pg_dump --serializable-deferrable`** : garantit la cohérence transactionnelle (snapshot atomique) sans bloquer les writes pendant le dump.
- **`psql` qui plante en milieu de replay** : le `DROP SCHEMA public CASCADE` est destructif. Si le replay échoue, la base est cassée. **Mitigation MVP** : faire le restore vers une base tampon, puis swap. Ou : exiger `auto_enable_maintenance=true`. Ou : utiliser `pg_dump --format=custom` + `pg_restore --clean --if-exists`. **Décision** : utiliser `--format=custom` pour plus de robustesse au restore.
- **`age` private key en RAM** : ne JAMAIS la persister, ne JAMAIS la logger. Passer via stdin pour ne pas l'avoir dans `argv` (visible dans `ps`).
- **Streaming upload** : utiliser `request.stream()` pour les gros fichiers. Sinon `await request.body()` charge tout en RAM.
- **Streaming download** : `FileResponse` natif FastAPI gère le streaming.
- **Mode maintenance et requêtes en cours** : les requêtes déjà en cours au moment de l'enable continuent. Seules les nouvelles sont bloquées. C'est OK pour MVP, sinon faire un soft drain.
- **Session epoch invalidation** : l'UI doit gérer le 409 et forcer un re-unlock. Pas un re-login OAuth (le JWT reste valide), juste un re-déchiffrement RAM.
- **`harpocrate-admin` rôle Keycloak** : à configurer manuellement dans Keycloak (Realm Roles → create `harpocrate-admin` → assign to user). Documenter dans `03_installation.md`.
- **Confirmation textuelle case-sensitive** : `RESTORE harpocrate-backup-...` exactement, pas trimmé. Force la concentration.
- **Backup pendant un autre backup** : protéger avec un lock (table ou fichier). Sinon double `pg_dump` peut créer des soucis de perf.
- **Volume de backup** : à 100 wallets × 10 secrets × 1 KB blob = ~1 MB. Mais audit log de plusieurs millions de lignes peut faire grossir à plusieurs centaines de MB. À surveiller.
- **`/v1/admin/backups/{id}/manifest`** : le manifest est extrait à la création (avant chiffrement) et stocké en clair en DB. Lecture rapide, mais le manifest dans le `.tar.age` reste la source de vérité pour la vérification post-déchiffrement.
- **Restore d'une version `harpocrate_version` différente** : peut casser si le schéma DB a changé. À vérifier dans le manifest. Pour MVP : warning, pas un blocage. Pour prod : faire du `pg_dump --schema-only` avant le drop pour comparer.

## Tests à écrire

- `test_create_backup_produces_valid_age_file`
- `test_backup_contains_manifest_dump_env`
- `test_backup_excludes_sensitive_env_vars`
- `test_backup_manifest_stats_correct`
- `test_list_backups`
- `test_download_backup_streaming`
- `test_upload_backup_streaming`
- `test_upload_too_large_413`
- `test_verify_wrong_key_fails`
- `test_verify_correct_key_succeeds`
- `test_delete_requires_reverify`
- `test_restore_full_roundtrip`
- `test_restore_invalidates_sessions`
- `test_restore_wrong_confirmation_400`
- `test_maintenance_blocks_mutations`
- `test_maintenance_allows_health`
- `test_maintenance_allows_admin`
- `test_admin_role_required`
- `test_audit_log_for_all_admin_ops`
- `test_cli_backup_via_ssh`
- `test_concurrent_backup_locked`

## Ce qui suit

Le **lot 12b** ajoute l'UI admin pour piloter tout ça depuis le navigateur.
