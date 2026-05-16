# Google Drive Remote Backup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter Google Drive (kind=`gdrive`) comme 4ème provider de `remote_backup_connection`, aux côtés de `sftp` / `s3` / `ftps`, avec un flux OAuth 2.0 user-delegated complet et un wizard UI en 3 phases dans le modal existant.

**Architecture:** Le provider `GoogleDriveProvider` réutilise l'interface existante `RemoteBackupProvider` (étendue de façon rétro-compatible pour permettre `test_connection` de patcher le `config` avec le `folder_id` découvert). Une nouvelle table éphémère `oauth_pending_session` retient les paramètres OAuth (TTL strict 10 min) entre le clic "Autoriser" et le callback Google. La librairie officielle Google sync est wrappée via `asyncio.to_thread` (cohérent avec `boto3`). Le frontend ouvre une popup OAuth qui communique son résultat via `postMessage` (double CSRF check : state + origin).

**Tech Stack:** Python 3.12, asyncpg, FastAPI, `google-auth>=2.30`, `google-auth-oauthlib>=1.2`, `google-api-python-client>=2.130`, React 18 + TypeScript strict, Mantine UI, i18next, Vitest, pytest + pytest-asyncio.

**Spec de référence:** [`docs/superpowers/specs/2026-05-16-google-drive-remote-backup-design.md`](../specs/2026-05-16-google-drive-remote-backup-design.md)

---

## File Structure — vue d'ensemble des fichiers touchés

### Migrations
- **Create** `backend/migrations/030_remote_backup_kinds_gdrive.sql`
- **Create** `backend/migrations/031_oauth_pending_session.sql`

### Backend
- **Create** `backend/src/app/db/repositories/oauth_pending_session.py` — CRUD asyncpg
- **Create** `backend/src/app/services/remote_backup_providers/gdrive_client.py` — couche d'abstraction Google API (mockable)
- **Create** `backend/src/app/services/remote_backup_providers/gdrive.py` — `GoogleDriveProvider`
- **Create** `backend/src/app/services/gdrive_oauth_session.py` — service OAuth (create/finalize/reauthorize)
- **Create** `backend/src/app/api/v1/admin_remote_backups_oauth_gdrive.py` — router OAuth dédié
- **Modify** `backend/src/app/services/remote_backup_providers/base.py` — signature `test_connection` retourne `dict | None`
- **Modify** `backend/src/app/services/remote_backup_providers/{sftp,s3_compatible,ftps}.py` — ajouter `return None`
- **Modify** `backend/src/app/services/remote_backup_providers/__init__.py` — factory + `SUPPORTED_KINDS`
- **Modify** `backend/src/app/api/v1/admin_remote_backups.py` — extension `POST /` pour `kind=gdrive` + propager retour `test_connection`
- **Modify** `backend/src/app/services/snapshot_scheduler.py` — call `purge_expired_oauth_sessions` à chaque cycle
- **Modify** `backend/src/app/main.py` — register nouveau router
- **Modify** `backend/pyproject.toml` — 3 nouvelles deps Google

### Frontend
- **Create** `frontend/src/lib/gdriveOAuth.ts` — popup OAuth + postMessage helpers
- **Create** `frontend/src/components/GDriveFields.tsx` — wizard 3-states pour le modal
- **Modify** `frontend/src/lib/adminApi.ts` — 4 nouvelles fonctions + extension create
- **Modify** `frontend/src/schemas/admin.ts` — types gdrive
- **Modify** `frontend/src/pages/AdminRemoteBackupsPage.tsx` — sélecteur kind, branchement GDriveFields, cellules table, bouton Re-autoriser
- **Modify** `frontend/src/i18n/fr.json` + `frontend/src/i18n/en.json` — nouvelles clés

### Tests
- **Create** `backend/tests/test_oauth_pending_session_migration.py`
- **Create** `backend/tests/test_remote_backup_kinds_gdrive_migration.py`
- **Create** `backend/tests/test_oauth_pending_session_repository.py`
- **Create** `backend/tests/test_gdrive_provider.py`
- **Create** `backend/tests/test_admin_remote_backups_oauth_gdrive.py`
- **Create** `backend/tests/test_admin_remote_backups_create_gdrive.py`
- **Create** `backend/tests/test_purge_expired_oauth_sessions.py`
- **Create** `frontend/src/lib/gdriveOAuth.test.ts`
- **Modify** `frontend/src/pages/AdminRemoteBackupsPage.test.tsx`

### Documentation
- **Create** `docs/admin/gdrive-setup.md`

---

## LOT G1 — Fondations DB & repository

Le LOT G1 livre la base de données prête (deux migrations idempotentes via le runner existant) et un repository asyncpg utilisable par les services du LOT G4. Aucune logique métier — uniquement le socle.

### Task G1.1 — Migration 030 : élargir `kind` à `gdrive`

**Files:**
- Create: `backend/migrations/030_remote_backup_kinds_gdrive.sql`
- Test: `backend/tests/test_remote_backup_kinds_gdrive_migration.py`

- [ ] **Step 1: Écrire le test (qui doit échouer)**

```python
# backend/tests/test_remote_backup_kinds_gdrive_migration.py
"""Migration 030 — vérifie que kind='gdrive' est accepté dans remote_backup_connection."""

from __future__ import annotations

import asyncpg
import pytest


async def test_kind_gdrive_accepted(real_db_pool: asyncpg.Pool[asyncpg.Record]) -> None:
    async with real_db_pool.acquire() as conn:
        # Insère une ligne dummy avec kind='gdrive' puis rollback.
        async with conn.transaction():
            inserted = await conn.fetchval(
                """
                INSERT INTO remote_backup_connection
                    (name, kind, config, credentials_encrypted)
                VALUES ($1, $2, '{}'::jsonb, '\\x00'::bytea)
                RETURNING kind
                """,
                f"gdrive-test-{__import__('uuid').uuid4()}",
                "gdrive",
            )
            assert inserted == "gdrive"
            raise _Rollback()


class _Rollback(Exception):
    """Force le rollback de la transaction de test."""


async def test_kind_unknown_rejected(real_db_pool: asyncpg.Pool[asyncpg.Record]) -> None:
    async with real_db_pool.acquire() as conn:
        with pytest.raises(asyncpg.CheckViolationError):
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO remote_backup_connection
                        (name, kind, config, credentials_encrypted)
                    VALUES ($1, $2, '{}'::jsonb, '\\x00'::bytea)
                    """,
                    f"unknown-test-{__import__('uuid').uuid4()}",
                    "dropbox",  # pas autorisé
                )
```

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `cd backend && uv run pytest tests/test_remote_backup_kinds_gdrive_migration.py -v`
Expected: FAIL (`CheckViolationError` sur l'INSERT gdrive, car la contrainte actuelle n'accepte que sftp/s3/ftps).

- [ ] **Step 3: Écrire la migration**

```sql
-- backend/migrations/030_remote_backup_kinds_gdrive.sql
-- LOT remote-backups-gdrive — ajoute 'gdrive' (Google Drive OAuth user-delegated)
-- aux kinds reconnus par remote_backup_connection.

ALTER TABLE remote_backup_connection
    DROP CONSTRAINT IF EXISTS remote_backup_connection_kind_check;

ALTER TABLE remote_backup_connection
    ADD CONSTRAINT remote_backup_connection_kind_check
    CHECK (kind IN ('sftp', 's3', 'ftps', 'gdrive'));
```

- [ ] **Step 4: Appliquer la migration et relancer le test**

Run:
```
cd backend && uv run python -m migrations.apply_migrations
cd backend && uv run pytest tests/test_remote_backup_kinds_gdrive_migration.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/migrations/030_remote_backup_kinds_gdrive.sql backend/tests/test_remote_backup_kinds_gdrive_migration.py
git commit -m "feat(gdrive-db): migration 030 — kind='gdrive' accepté"
```

### Task G1.2 — Migration 031 : table `oauth_pending_session`

**Files:**
- Create: `backend/migrations/031_oauth_pending_session.sql`
- Test: `backend/tests/test_oauth_pending_session_migration.py`

- [ ] **Step 1: Écrire le test (qui doit échouer)**

```python
# backend/tests/test_oauth_pending_session_migration.py
"""Migration 031 — vérifie que la table oauth_pending_session est créée correctement."""

from __future__ import annotations

import asyncpg
import pytest

_EXPECTED_COLUMNS = [
    "id",
    "state",
    "provider",
    "payload",
    "result",
    "status",
    "target_connection_id",
    "created_by_user_id",
    "created_at",
    "expires_at",
]


async def test_oauth_pending_session_columns(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        cols = await conn.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'oauth_pending_session' "
            "ORDER BY ordinal_position"
        )
    names = [c["column_name"] for c in cols]
    for expected in _EXPECTED_COLUMNS:
        assert expected in names, f"colonne manquante : {expected}"


async def test_oauth_pending_session_state_unique(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    """Le state DOIT être UNIQUE (protection replay)."""
    async with real_db_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO oauth_pending_session
                    (state, provider, payload, expires_at)
                VALUES ('s1', 'gdrive', '{}'::jsonb, NOW() + INTERVAL '10 minutes')
                """
            )
            with pytest.raises(asyncpg.UniqueViolationError):
                await conn.execute(
                    """
                    INSERT INTO oauth_pending_session
                        (state, provider, payload, expires_at)
                    VALUES ('s1', 'gdrive', '{}'::jsonb, NOW() + INTERVAL '10 minutes')
                    """
                )
            raise _Rollback()


async def test_oauth_pending_session_provider_check(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        with pytest.raises(asyncpg.CheckViolationError):
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO oauth_pending_session
                        (state, provider, payload, expires_at)
                    VALUES ('s2', 'dropbox', '{}'::jsonb, NOW() + INTERVAL '10 minutes')
                    """
                )


async def test_oauth_pending_session_status_check(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        with pytest.raises(asyncpg.CheckViolationError):
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO oauth_pending_session
                        (state, provider, payload, status, expires_at)
                    VALUES ('s3', 'gdrive', '{}'::jsonb, 'consumed', NOW() + INTERVAL '10 minutes')
                    """
                )


class _Rollback(Exception):
    """Force le rollback de la transaction de test."""
```

- [ ] **Step 2: Lancer le test (expect FAIL)**

Run: `cd backend && uv run pytest tests/test_oauth_pending_session_migration.py -v`
Expected: FAIL (table inexistante).

- [ ] **Step 3: Écrire la migration**

```sql
-- backend/migrations/031_oauth_pending_session.sql
-- LOT remote-backups-gdrive — état éphémère d'un flux OAuth en cours.
-- Stocke les paramètres OAuth (client_id, client_secret, scope, payload UI)
-- entre le clic "Autoriser avec Google" côté frontend et le retour du callback
-- Google. TTL strict 10 min, purgé par job cron.
-- Une fois la connexion finalisée, la ligne est supprimée immédiatement.

CREATE TABLE oauth_pending_session (
    id                   UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    state                TEXT         NOT NULL UNIQUE,
    provider             TEXT         NOT NULL CHECK (provider IN ('gdrive')),
    payload              JSONB        NOT NULL,
    result               JSONB,
    status               TEXT         NOT NULL DEFAULT 'pending'
                                      CHECK (status IN ('pending', 'authorized', 'failed')),
    target_connection_id UUID         REFERENCES remote_backup_connection(id) ON DELETE CASCADE,
    created_by_user_id   UUID         REFERENCES users(id) ON DELETE SET NULL,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    expires_at           TIMESTAMPTZ  NOT NULL
);

CREATE INDEX idx_oauth_pending_session_state   ON oauth_pending_session(state);
CREATE INDEX idx_oauth_pending_session_expires ON oauth_pending_session(expires_at);
```

- [ ] **Step 4: Appliquer la migration et relancer le test**

Run:
```
cd backend && uv run python -m migrations.apply_migrations
cd backend && uv run pytest tests/test_oauth_pending_session_migration.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/migrations/031_oauth_pending_session.sql backend/tests/test_oauth_pending_session_migration.py
git commit -m "feat(gdrive-db): migration 031 — table oauth_pending_session"
```

### Task G1.3 — Repository `oauth_pending_session.py`

**Files:**
- Create: `backend/src/app/db/repositories/oauth_pending_session.py`
- Test: `backend/tests/test_oauth_pending_session_repository.py`

- [ ] **Step 1: Écrire les tests (qui doivent échouer)**

```python
# backend/tests/test_oauth_pending_session_repository.py
"""Tests du repository oauth_pending_session."""

from __future__ import annotations

import asyncpg
import pytest

from app.db.repositories import oauth_pending_session as repo


async def test_insert_and_get_by_state(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        async with conn.transaction():
            sid = await repo.insert(
                conn,
                state="state-aaa",
                provider="gdrive",
                payload={"client_id": "abc", "folder_name": "Backups"},
                target_connection_id=None,
                created_by_user_id=None,
                ttl_seconds=600,
            )
            assert sid is not None
            row = await repo.get_by_state(conn, "state-aaa")
            assert row is not None
            assert row["status"] == "pending"
            assert row["provider"] == "gdrive"
            raise _Rollback()


async def test_get_by_state_expired_returns_none(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        async with conn.transaction():
            await repo.insert(
                conn,
                state="state-old",
                provider="gdrive",
                payload={},
                target_connection_id=None,
                created_by_user_id=None,
                ttl_seconds=-60,  # déjà expiré
            )
            row = await repo.get_active_by_state(conn, "state-old")
            assert row is None
            raise _Rollback()


async def test_mark_authorized(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        async with conn.transaction():
            await repo.insert(
                conn,
                state="state-bbb",
                provider="gdrive",
                payload={},
                target_connection_id=None,
                created_by_user_id=None,
                ttl_seconds=600,
            )
            await repo.mark_authorized(
                conn, state="state-bbb", result={"user_email": "x@y.z", "refresh_token": "r"}
            )
            row = await repo.get_by_state(conn, "state-bbb")
            assert row["status"] == "authorized"
            assert row["result"]["user_email"] == "x@y.z"
            raise _Rollback()


async def test_mark_failed(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        async with conn.transaction():
            await repo.insert(
                conn,
                state="state-ccc",
                provider="gdrive",
                payload={},
                target_connection_id=None,
                created_by_user_id=None,
                ttl_seconds=600,
            )
            await repo.mark_failed(conn, state="state-ccc", error="access_denied")
            row = await repo.get_by_state(conn, "state-ccc")
            assert row["status"] == "failed"
            assert row["result"]["error"] == "access_denied"
            raise _Rollback()


async def test_delete_by_state(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        async with conn.transaction():
            await repo.insert(
                conn,
                state="state-ddd",
                provider="gdrive",
                payload={},
                target_connection_id=None,
                created_by_user_id=None,
                ttl_seconds=600,
            )
            deleted = await repo.delete_by_state(conn, "state-ddd")
            assert deleted == 1
            assert await repo.get_by_state(conn, "state-ddd") is None
            raise _Rollback()


async def test_purge_expired(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        async with conn.transaction():
            await repo.insert(
                conn, state="alive", provider="gdrive", payload={},
                target_connection_id=None, created_by_user_id=None, ttl_seconds=600,
            )
            await repo.insert(
                conn, state="dead", provider="gdrive", payload={},
                target_connection_id=None, created_by_user_id=None, ttl_seconds=-60,
            )
            n = await repo.purge_expired(conn)
            assert n >= 1
            assert await repo.get_by_state(conn, "dead") is None
            assert await repo.get_by_state(conn, "alive") is not None
            raise _Rollback()


class _Rollback(Exception):
    pass
```

- [ ] **Step 2: Lancer (expect FAIL)**

Run: `cd backend && uv run pytest tests/test_oauth_pending_session_repository.py -v`
Expected: FAIL (`ModuleNotFoundError: oauth_pending_session`).

- [ ] **Step 3: Écrire le repository**

```python
# backend/src/app/db/repositories/oauth_pending_session.py
"""Repository — table oauth_pending_session (LOT gdrive).

État éphémère d'un flux OAuth (gdrive aujourd'hui, extensible). TTL strict.
Aucune logique de chiffrement : payload et result sont des JSONB nus, le secret
est protégé par le fait que la ligne est supprimée dès la finalisation.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import asyncpg


async def insert(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    state: str,
    provider: str,
    payload: dict[str, Any],
    target_connection_id: UUID | None,
    created_by_user_id: UUID | None,
    ttl_seconds: int,
) -> UUID:
    new_id: UUID = await conn.fetchval(
        """
        INSERT INTO oauth_pending_session
            (state, provider, payload, target_connection_id, created_by_user_id,
             expires_at)
        VALUES ($1, $2, $3::jsonb, $4, $5,
                NOW() + make_interval(secs => $6))
        RETURNING id
        """,
        state, provider, json.dumps(payload),
        target_connection_id, created_by_user_id, ttl_seconds,
    )
    return new_id


async def get_by_state(
    conn: asyncpg.Connection[asyncpg.Record], state: str
) -> asyncpg.Record | None:
    """Lit la ligne sans filtrer sur expires_at (debug / audit)."""
    return await conn.fetchrow(
        "SELECT * FROM oauth_pending_session WHERE state = $1", state
    )


async def get_active_by_state(
    conn: asyncpg.Connection[asyncpg.Record], state: str
) -> asyncpg.Record | None:
    """Lit la ligne UNIQUEMENT si pending + non-expirée (pour le callback)."""
    return await conn.fetchrow(
        """
        SELECT * FROM oauth_pending_session
        WHERE state = $1 AND status = 'pending' AND expires_at > NOW()
        """,
        state,
    )


async def mark_authorized(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    state: str,
    result: dict[str, Any],
) -> int:
    return await conn.fetchval(
        """
        UPDATE oauth_pending_session
        SET status = 'authorized', result = $2::jsonb
        WHERE state = $1 AND status = 'pending'
        RETURNING 1
        """,
        state, json.dumps(result),
    ) or 0


async def mark_failed(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    state: str,
    error: str,
) -> int:
    return await conn.fetchval(
        """
        UPDATE oauth_pending_session
        SET status = 'failed', result = jsonb_build_object('error', $2::text)
        WHERE state = $1 AND status = 'pending'
        RETURNING 1
        """,
        state, error,
    ) or 0


async def delete_by_state(
    conn: asyncpg.Connection[asyncpg.Record], state: str
) -> int:
    return await conn.fetchval(
        """
        WITH del AS (DELETE FROM oauth_pending_session WHERE state = $1 RETURNING 1)
        SELECT count(*) FROM del
        """,
        state,
    )


async def purge_expired(conn: asyncpg.Connection[asyncpg.Record]) -> int:
    """Supprime toutes les lignes dont expires_at est dans le passé. Retourne le compte."""
    return await conn.fetchval(
        """
        WITH del AS (DELETE FROM oauth_pending_session WHERE expires_at < NOW() RETURNING 1)
        SELECT count(*) FROM del
        """
    )
```

- [ ] **Step 4: Lancer (expect PASS)**

Run: `cd backend && uv run pytest tests/test_oauth_pending_session_repository.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/app/db/repositories/oauth_pending_session.py backend/tests/test_oauth_pending_session_repository.py
git commit -m "feat(gdrive-db): repository oauth_pending_session (insert/get/mark/delete/purge)"
```

---

## LOT G2 — Évolution rétro-compatible de `RemoteBackupProvider`

Le LOT G2 évolue le Protocol pour permettre à `test_connection` de retourner un patch optionnel (`dict | None`) à fusionner dans le `config` de la connexion. C'est nécessaire pour que `GoogleDriveProvider` puisse persister le `folder_id` découvert au premier appel. Les 3 providers existants reçoivent un `return None` explicite. **Pas de migration DB**, pas de changement de comportement observable côté API publique — uniquement le contrat Python.

### Task G2.1 — Étendre l'interface `RemoteBackupProvider`

**Files:**
- Modify: `backend/src/app/services/remote_backup_providers/base.py`

- [ ] **Step 1: Écrire le test (qui doit échouer)**

```python
# backend/tests/test_remote_backup_provider_interface.py
"""L'interface RemoteBackupProvider.test_connection retourne un dict | None."""

from __future__ import annotations

import inspect

from app.services.remote_backup_providers.base import RemoteBackupProvider


def test_test_connection_returns_optional_dict() -> None:
    sig = inspect.signature(RemoteBackupProvider.test_connection)
    ret = sig.return_annotation
    # Le return annotation doit mentionner Optional / | None.
    src = inspect.getsource(RemoteBackupProvider.test_connection)
    assert "dict[str, Any] | None" in src or "Optional[dict[str, Any]]" in src
```

- [ ] **Step 2: Lancer (expect FAIL)**

Run: `cd backend && uv run pytest tests/test_remote_backup_provider_interface.py -v`
Expected: FAIL (la signature actuelle retourne `None`).

- [ ] **Step 3: Modifier `base.py`**

```python
# backend/src/app/services/remote_backup_providers/base.py
"""Interface abstraite pour les providers de backup distant."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol


class RemoteBackupProviderError(Exception):
    """Erreur générique remontée par un provider (connexion, auth, upload, etc.).

    L'exception encapsule le détail technique. Les routes admin la traduisent
    en HTTP 200 + ok:false (test) ou 422 (push) avec un message lisible côté UI.
    """


class RemoteBackupProvider(Protocol):
    """Contrat commun à tous les providers (SFTP, S3, FTPS, Drive...).

    Les providers sont **stateless sur le path** : `path` est passé en argument
    de chaque opération plutôt que stocké en attribut. Une même connexion
    (host + creds) peut donc cibler plusieurs paths (ex : un pour les
    snapshots, un pour les fulls) sans avoir à instancier deux providers.
    """

    async def test_connection(self, path: str) -> dict[str, Any] | None:
        """Vérifie l'auth + l'accessibilité de `path` sur le serveur distant.

        Lève RemoteBackupProviderError en cas d'échec (auth, host inaccessible,
        path inexistant et non créable, droits insuffisants, etc.).

        Retourne un patch optionnel à fusionner dans le `config` de la
        connexion appelante. Utilisé par GoogleDriveProvider pour persister le
        `folder_id` découvert au premier appel. Les autres providers retournent
        toujours None.
        """
        ...

    async def upload_stream(
        self,
        path: str,
        remote_filename: str,
        source: AsyncIterator[bytes],
    ) -> int:
        """Streame `source` vers `<path>/<remote_filename>` côté distant.

        Retourne le nombre total d'octets envoyés. Lève RemoteBackupProviderError
        en cas d'échec.
        """
        ...
```

- [ ] **Step 4: Lancer (expect PASS)**

Run: `cd backend && uv run pytest tests/test_remote_backup_provider_interface.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/app/services/remote_backup_providers/base.py backend/tests/test_remote_backup_provider_interface.py
git commit -m "feat(remote-backups): test_connection retourne dict|None (patch config)"
```

### Task G2.2 — Adapter les 3 providers existants

**Files:**
- Modify: `backend/src/app/services/remote_backup_providers/sftp.py:107-128`
- Modify: `backend/src/app/services/remote_backup_providers/ftps.py` (méthode test_connection)
- Modify: `backend/src/app/services/remote_backup_providers/s3_compatible.py` (méthode test_connection)

- [ ] **Step 1: Modifier les 3 providers — ajouter `return None` explicite**

Pour chacun des 3 fichiers, dans la méthode `test_connection`, changer la signature et ajouter un `return None` à la fin du happy path.

**sftp.py** — changer la signature ligne ~107 :
```python
async def test_connection(self, path: str) -> dict[str, Any] | None:
    """[docstring existante]"""
    normalized = self._normalize_path(path)
    conn = await self._open_connection()
    try:
        async with conn.start_sftp_client() as sftp:
            await self._ensure_path(sftp, normalized)
            try:
                await sftp.listdir(normalized)
            except (OSError, asyncssh.Error) as exc:
                raise RemoteBackupProviderError(
                    f"SFTP cannot list path={normalized!r}: {exc}"
                ) from exc
    finally:
        conn.close()
        await conn.wait_closed()
    return None
```

**ftps.py** — même pattern, signature + `return None`.

**s3_compatible.py** — même pattern, signature + `return None`.

- [ ] **Step 2: Lancer toute la suite de tests des providers existants**

Run: `cd backend && uv run pytest tests/ -k "sftp or ftps or s3" -v`
Expected: tous PASS (zéro régression, le `return None` est inerte côté tests existants).

- [ ] **Step 3: Commit**

```bash
git add backend/src/app/services/remote_backup_providers/sftp.py backend/src/app/services/remote_backup_providers/ftps.py backend/src/app/services/remote_backup_providers/s3_compatible.py
git commit -m "chore(remote-backups): providers existants retournent None explicite"
```

### Task G2.3 — Propager le retour optionnel dans `admin_remote_backups.py`

**Files:**
- Modify: `backend/src/app/api/v1/admin_remote_backups.py:188-244`

- [ ] **Step 1: Écrire le test (qui doit échouer)**

```python
# backend/tests/test_admin_remote_backups_test_returns_patch.py
"""Le retour de test_connection (patch config) est exposé dans la réponse."""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_test_endpoint_returns_config_patch(client, admin_jwt_headers) -> None:
    # Mock get_provider pour retourner un faux provider avec patch {"folder_id": "X"}.
    class _FakeProvider:
        def __init__(self, **_: object) -> None: ...
        async def test_connection(self, path: str):
            return {"folder_id": "abc123"}
        async def upload_stream(self, *_a, **_kw): ...

    with patch(
        "app.api.v1.admin_remote_backups.get_provider", return_value=_FakeProvider()
    ):
        r = await client.post(
            "/v1/admin/backup-remotes/test",
            json={"kind": "sftp", "config": {"host": "h"}, "credentials": {"username": "u", "auth_method": "password", "password": "p"}, "path": "/x"},
            headers=admin_jwt_headers,
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body.get("config_patch") == {"folder_id": "abc123"}


@pytest.mark.asyncio
async def test_test_endpoint_no_patch_when_provider_returns_none(client, admin_jwt_headers) -> None:
    class _FakeProvider:
        def __init__(self, **_: object) -> None: ...
        async def test_connection(self, path: str):
            return None
        async def upload_stream(self, *_a, **_kw): ...

    with patch(
        "app.api.v1.admin_remote_backups.get_provider", return_value=_FakeProvider()
    ):
        r = await client.post(
            "/v1/admin/backup-remotes/test",
            json={"kind": "sftp", "config": {"host": "h"}, "credentials": {"username": "u", "auth_method": "password", "password": "p"}, "path": "/x"},
            headers=admin_jwt_headers,
        )
    body = r.json()
    assert body["ok"] is True
    assert "config_patch" not in body or body["config_patch"] is None
```

- [ ] **Step 2: Lancer (expect FAIL)**

Run: `cd backend && uv run pytest tests/test_admin_remote_backups_test_returns_patch.py -v`
Expected: FAIL.

- [ ] **Step 3: Modifier `admin_remote_backups.py`**

Dans le helper `_test_response` et les deux endpoints `/test` (POST `/test` et POST `/{connection_id}/test`), accepter et propager le `config_patch` retourné par `await provider.test_connection(path)`.

```python
def _test_response(
    ok: bool,
    error: str | None = None,
    message: str | None = None,
    config_patch: dict[str, Any] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {"ok": ok}
    if not ok:
        body["error"] = error or "test_failed"
        body["message"] = message or ""
    if config_patch:
        body["config_patch"] = config_patch
    return JSONResponse(body, status_code=status.HTTP_200_OK)


@router.post("/test", response_class=JSONResponse)
async def test_remote_backup_with_provided_creds(
    body: RemoteBackupTestNew, admin: AdminJwt
) -> JSONResponse:
    try:
        provider = get_provider(body.kind, body.config, body.credentials)
    except ValueError as exc:
        return _test_response(False, error="invalid_config", message=str(exc))

    try:
        patch_out = await provider.test_connection(body.path)
    except RemoteBackupProviderError as exc:
        return _test_response(False, error="test_failed", message=str(exc))
    return _test_response(True, config_patch=patch_out)


@router.post("/{connection_id}/test", response_class=JSONResponse)
async def test_remote_backup_with_stored_creds(
    connection_id: UUID, body: RemoteBackupTestStored, admin: AdminJwt
) -> JSONResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        item = await svc.get_connection(conn, connection_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "connection_not_found"},
            )
        creds = await svc.get_decrypted_credentials(conn, connection_id)
    if creds is None:
        return _test_response(
            False, error="no_credentials",
            message="Connection has no stored credentials. Save credentials first.",
        )

    config_to_use = body.config if body.config is not None else item.config
    try:
        provider = get_provider(item.kind, config_to_use, creds)
    except ValueError as exc:
        return _test_response(False, error="invalid_config", message=str(exc))

    try:
        patch_out = await provider.test_connection(body.path)
    except RemoteBackupProviderError as exc:
        return _test_response(False, error="test_failed", message=str(exc))

    # Persiste le patch en DB si non-vide (pour Drive : folder_id découvert).
    if patch_out:
        async with pool.acquire() as conn:
            merged = {**item.config, **patch_out}
            await svc.update_connection(
                conn, connection_id=connection_id, name=None,
                config=merged, credentials=None,
            )
    return _test_response(True, config_patch=patch_out)
```

- [ ] **Step 4: Lancer (expect PASS)**

Run: `cd backend && uv run pytest tests/test_admin_remote_backups_test_returns_patch.py tests/test_admin_remote_backups.py -v`
Expected: tous PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/app/api/v1/admin_remote_backups.py backend/tests/test_admin_remote_backups_test_returns_patch.py
git commit -m "feat(remote-backups): endpoints /test propagent le config_patch + persist en stored"
```

---

## LOT G3 — Provider Python Google Drive

Le LOT G3 livre `GoogleDriveProvider` derrière une couche d'abstraction `gdrive_client.py` qui sera mockée dans les tests. **Aucun appel réseau réel** dans les tests : on mocke `gdrive_client.build_drive_service` et `gdrive_client.build_flow`.

### Task G3.1 — Ajouter les dépendances Google

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Ajouter les 3 deps**

Dans `backend/pyproject.toml`, dans la section `[project.dependencies]` (ou `dependencies = [...]`), ajouter :

```toml
"google-auth>=2.30",
"google-auth-oauthlib>=1.2",
"google-api-python-client>=2.130",
```

- [ ] **Step 2: Resolver et installer**

Run: `cd backend && uv sync`
Expected: 3 packages installés (+ leurs deps `cachetools`, `google-api-core`, `googleapis-common-protos`, etc.).

- [ ] **Step 3: Vérifier l'import**

Run: `cd backend && uv run python -c "import google.auth.transport.requests; import google_auth_oauthlib.flow; import googleapiclient.discovery; print('ok')"`
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock
git commit -m "chore(gdrive): ajoute google-auth + oauthlib + api-python-client"
```

### Task G3.2 — Couche d'abstraction `gdrive_client.py`

**Files:**
- Create: `backend/src/app/services/remote_backup_providers/gdrive_client.py`

Ce module est une **fine couche** qui expose 3 fonctions utilisées par `gdrive.py` ET par `gdrive_oauth_session.py`. C'est l'unique point que les tests mockent.

- [ ] **Step 1: Écrire les tests (qui doivent échouer)**

```python
# backend/tests/test_gdrive_client.py
"""La couche gdrive_client expose les helpers utilisés par provider + service OAuth."""

from __future__ import annotations

from app.services.remote_backup_providers import gdrive_client


def test_gdrive_client_exports() -> None:
    """Surface minimale stable."""
    assert hasattr(gdrive_client, "build_credentials")
    assert hasattr(gdrive_client, "build_drive_service")
    assert hasattr(gdrive_client, "build_flow")
    assert hasattr(gdrive_client, "fetch_user_email")


def test_build_credentials_returns_google_credentials() -> None:
    creds = gdrive_client.build_credentials(
        client_id="abc.apps.googleusercontent.com",
        client_secret="GOCSPX-fake",
        refresh_token="rt-fake",
        token_uri="https://oauth2.googleapis.com/token",
        scope="https://www.googleapis.com/auth/drive.file",
    )
    # google.oauth2.credentials.Credentials
    from google.oauth2.credentials import Credentials
    assert isinstance(creds, Credentials)
    assert creds.refresh_token == "rt-fake"


def test_build_flow_uses_drive_file_scope() -> None:
    flow = gdrive_client.build_flow(
        client_id="abc.apps.googleusercontent.com",
        client_secret="GOCSPX-fake",
        redirect_uri="https://harpo.example.com/callback",
    )
    # Une seule scope, drive.file
    assert flow.oauth2session.scope == ["https://www.googleapis.com/auth/drive.file"]
```

- [ ] **Step 2: Lancer (expect FAIL)**

Run: `cd backend && uv run pytest tests/test_gdrive_client.py -v`
Expected: FAIL.

- [ ] **Step 3: Implémenter `gdrive_client.py`**

```python
# backend/src/app/services/remote_backup_providers/gdrive_client.py
"""Couche d'abstraction sur les libs Google.

Toutes les fonctions ici sont sync. Les callers (provider, service OAuth) les
appellent via asyncio.to_thread. Les tests mockent ce module — JAMAIS
googleapiclient directement.
"""

from __future__ import annotations

from typing import Any

import google.auth.transport.requests as _g_requests
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import Resource, build

_DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
_TOKEN_URI = "https://oauth2.googleapis.com/token"


def build_credentials(
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    token_uri: str = _TOKEN_URI,
    scope: str = _DRIVE_FILE_SCOPE,
) -> Credentials:
    """Construit un objet Credentials prêt à refresh."""
    return Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri=token_uri,
        scopes=[scope],
    )


def refresh(creds: Credentials) -> None:
    """Force le refresh de l'access_token (lève RefreshError si invalid_grant)."""
    creds.refresh(_g_requests.Request())


def build_drive_service(creds: Credentials) -> Resource:
    """Construit le client Drive v3 (cache local du discovery doc géré par la lib)."""
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def build_flow(
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> Flow:
    """Construit un Flow OAuth pour échanger un code contre des tokens."""
    return Flow.from_client_config(
        client_config={
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
                "token_uri": _TOKEN_URI,
            }
        },
        scopes=[_DRIVE_FILE_SCOPE],
        redirect_uri=redirect_uri,
    )


def fetch_user_email(creds: Credentials) -> str:
    """Récupère l'email du user autorisateur via l'endpoint userinfo OpenID."""
    service = build("oauth2", "v2", credentials=creds, cache_discovery=False)
    info: dict[str, Any] = service.userinfo().get().execute()
    email = info.get("email") or ""
    return str(email)


__all__ = [
    "build_credentials",
    "build_drive_service",
    "build_flow",
    "fetch_user_email",
    "refresh",
]
```

- [ ] **Step 4: Lancer (expect PASS)**

Run: `cd backend && uv run pytest tests/test_gdrive_client.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/app/services/remote_backup_providers/gdrive_client.py backend/tests/test_gdrive_client.py
git commit -m "feat(gdrive): couche d'abstraction gdrive_client (Credentials/Flow/Drive)"
```

### Task G3.3 — `GoogleDriveProvider` — squelette + validation

**Files:**
- Create: `backend/src/app/services/remote_backup_providers/gdrive.py`
- Test: `backend/tests/test_gdrive_provider.py` (premier groupe de tests)

- [ ] **Step 1: Écrire les tests de validation (qui doivent échouer)**

```python
# backend/tests/test_gdrive_provider.py
"""Tests du provider GoogleDriveProvider."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.remote_backup_providers.base import RemoteBackupProviderError
from app.services.remote_backup_providers.gdrive import GoogleDriveProvider


# ── Validation des inputs ────────────────────────────────────────────────────

def test_missing_client_id_raises() -> None:
    with pytest.raises(ValueError, match="client_id"):
        GoogleDriveProvider(
            config={"folder_name": "F"},
            credentials={"client_secret": "s", "refresh_token": "r"},
        )


def test_missing_client_secret_raises() -> None:
    with pytest.raises(ValueError, match="client_secret"):
        GoogleDriveProvider(
            config={"client_id": "id", "folder_name": "F"},
            credentials={"refresh_token": "r"},
        )


def test_missing_refresh_token_raises() -> None:
    with pytest.raises(ValueError, match="refresh_token"):
        GoogleDriveProvider(
            config={"client_id": "id", "folder_name": "F"},
            credentials={"client_secret": "s"},
        )


def test_missing_folder_name_raises() -> None:
    with pytest.raises(ValueError, match="folder_name"):
        GoogleDriveProvider(
            config={"client_id": "id"},
            credentials={"client_secret": "s", "refresh_token": "r"},
        )


def test_valid_inputs_construct() -> None:
    p = GoogleDriveProvider(
        config={"client_id": "id", "folder_name": "F"},
        credentials={"client_secret": "s", "refresh_token": "r"},
    )
    assert p is not None
```

- [ ] **Step 2: Lancer (expect FAIL)**

Run: `cd backend && uv run pytest tests/test_gdrive_provider.py -v`
Expected: FAIL (`ModuleNotFoundError: gdrive`).

- [ ] **Step 3: Implémenter le squelette + validation**

```python
# backend/src/app/services/remote_backup_providers/gdrive.py
"""Provider Google Drive — OAuth user-delegated, scope drive.file.

Le `path` côté interface RemoteBackupProvider n'a pas de sémantique Drive
(Drive est plat avec des folder_id, pas des chemins POSIX). On le **ignore**
pour gdrive : l'arborescence est `<folder_name>/<remote_filename>` où
`folder_name` vient du config. Le `path` reste accepté pour conformité.

Format des dictionnaires attendus — voir spec section 4.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from app.services.remote_backup_providers import gdrive_client
from app.services.remote_backup_providers.base import RemoteBackupProviderError

_log = logging.getLogger(__name__)
_FOLDER_MIME = "application/vnd.google-apps.folder"
_CHUNK_SIZE = 8 * 1024 * 1024  # 8 MB


class GoogleDriveProvider:
    """Provider Google Drive basé sur googleapiclient (sync) bridgé en async via threads."""

    def __init__(self, *, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        self._client_id = str(config.get("client_id", "")).strip()
        if not self._client_id:
            raise ValueError("GDrive config: 'client_id' is required")
        self._folder_name = str(config.get("folder_name", "")).strip()
        if not self._folder_name:
            raise ValueError("GDrive config: 'folder_name' is required")
        self._folder_id = config.get("folder_id") or None

        self._client_secret = str(credentials.get("client_secret", "")).strip()
        if not self._client_secret:
            raise ValueError("GDrive credentials: 'client_secret' is required")
        self._refresh_token = str(credentials.get("refresh_token", "")).strip()
        if not self._refresh_token:
            raise ValueError("GDrive credentials: 'refresh_token' is required")
        self._token_uri = credentials.get("token_uri") or "https://oauth2.googleapis.com/token"
        self._scope = credentials.get("scope") or "https://www.googleapis.com/auth/drive.file"

    async def test_connection(self, path: str) -> dict[str, Any] | None:
        raise NotImplementedError  # implémenté en G3.4

    async def upload_stream(
        self, path: str, remote_filename: str, source: AsyncIterator[bytes]
    ) -> int:
        raise NotImplementedError  # implémenté en G3.5
```

- [ ] **Step 4: Lancer (expect PASS sur les tests de validation)**

Run: `cd backend && uv run pytest tests/test_gdrive_provider.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/app/services/remote_backup_providers/gdrive.py backend/tests/test_gdrive_provider.py
git commit -m "feat(gdrive): squelette GoogleDriveProvider + validation inputs"
```

### Task G3.4 — `test_connection` : create folder + list

**Files:**
- Modify: `backend/src/app/services/remote_backup_providers/gdrive.py`
- Modify: `backend/tests/test_gdrive_provider.py` (ajout)

- [ ] **Step 1: Ajouter les tests (expect FAIL)**

Append à `backend/tests/test_gdrive_provider.py` :

```python
# ── test_connection ──────────────────────────────────────────────────────────

@pytest.fixture
def _mock_gdrive_client():
    """Patch toute la couche gdrive_client. Retourne un namespace mocks."""
    with patch("app.services.remote_backup_providers.gdrive.gdrive_client") as m:
        m.build_credentials.return_value = MagicMock(name="creds")
        m.build_drive_service.return_value = MagicMock(name="drive")
        m.refresh.return_value = None
        yield m


def _files_list_response(items: list[dict] | None = None) -> dict:
    return {"files": items or []}


@pytest.mark.asyncio
async def test_test_connection_creates_folder_when_missing(_mock_gdrive_client) -> None:
    drive = _mock_gdrive_client.build_drive_service.return_value
    # 1er call: files.list (folder lookup) -> 0 résultats
    drive.files.return_value.list.return_value.execute.side_effect = [
        _files_list_response([]),       # lookup folder
        _files_list_response([{"id": "x"}]),  # listing du folder fraîchement créé
    ]
    drive.files.return_value.create.return_value.execute.return_value = {"id": "new-folder-id"}

    p = GoogleDriveProvider(
        config={"client_id": "id", "folder_name": "Backups"},
        credentials={"client_secret": "s", "refresh_token": "r"},
    )
    patch_out = await p.test_connection("/ignored")
    assert patch_out == {"folder_id": "new-folder-id"}
    drive.files.return_value.create.assert_called_once()


@pytest.mark.asyncio
async def test_test_connection_finds_existing_folder(_mock_gdrive_client) -> None:
    drive = _mock_gdrive_client.build_drive_service.return_value
    drive.files.return_value.list.return_value.execute.side_effect = [
        _files_list_response([{"id": "existing-id"}]),
        _files_list_response([{"id": "any"}]),
    ]

    p = GoogleDriveProvider(
        config={"client_id": "id", "folder_name": "Backups"},
        credentials={"client_secret": "s", "refresh_token": "r"},
    )
    patch_out = await p.test_connection("/ignored")
    assert patch_out == {"folder_id": "existing-id"}
    drive.files.return_value.create.assert_not_called()


@pytest.mark.asyncio
async def test_test_connection_skips_lookup_when_folder_id_present(_mock_gdrive_client) -> None:
    drive = _mock_gdrive_client.build_drive_service.return_value
    drive.files.return_value.list.return_value.execute.return_value = _files_list_response([{"id": "any"}])

    p = GoogleDriveProvider(
        config={"client_id": "id", "folder_name": "Backups", "folder_id": "preset-id"},
        credentials={"client_secret": "s", "refresh_token": "r"},
    )
    patch_out = await p.test_connection("/ignored")
    # Aucun patch retourné car folder_id déjà connu.
    assert patch_out is None


@pytest.mark.asyncio
async def test_test_connection_refresh_error_raises(_mock_gdrive_client) -> None:
    from google.auth.exceptions import RefreshError
    _mock_gdrive_client.refresh.side_effect = RefreshError("invalid_grant")

    p = GoogleDriveProvider(
        config={"client_id": "id", "folder_name": "Backups"},
        credentials={"client_secret": "s", "refresh_token": "r"},
    )
    with pytest.raises(RemoteBackupProviderError, match="credentials_revoked"):
        await p.test_connection("/ignored")


@pytest.mark.asyncio
async def test_test_connection_http_error_raises(_mock_gdrive_client) -> None:
    from googleapiclient.errors import HttpError
    drive = _mock_gdrive_client.build_drive_service.return_value
    fake_resp = MagicMock(status=500, reason="Internal Server Error")
    drive.files.return_value.list.return_value.execute.side_effect = HttpError(
        resp=fake_resp, content=b'{"error": "boom"}'
    )

    p = GoogleDriveProvider(
        config={"client_id": "id", "folder_name": "Backups"},
        credentials={"client_secret": "s", "refresh_token": "r"},
    )
    with pytest.raises(RemoteBackupProviderError, match="drive_api_error"):
        await p.test_connection("/ignored")
```

- [ ] **Step 2: Lancer (expect FAIL)**

Run: `cd backend && uv run pytest tests/test_gdrive_provider.py -v`
Expected: 5 nouveaux FAIL (NotImplementedError ou import errors).

- [ ] **Step 3: Implémenter `test_connection`**

Remplacer la méthode `test_connection` dans `gdrive.py` :

```python
async def test_connection(self, path: str) -> dict[str, Any] | None:
    if path and path.strip() not in ("", "/", "."):
        _log.debug("gdrive provider ignores path argument", extra={"path": path})
    return await asyncio.to_thread(self._test_connection_sync)


def _test_connection_sync(self) -> dict[str, Any] | None:
    creds = gdrive_client.build_credentials(
        client_id=self._client_id,
        client_secret=self._client_secret,
        refresh_token=self._refresh_token,
        token_uri=self._token_uri,
        scope=self._scope,
    )
    try:
        gdrive_client.refresh(creds)
    except Exception as exc:
        if exc.__class__.__name__ == "RefreshError":
            raise RemoteBackupProviderError(
                f"credentials_revoked: {exc}"
            ) from exc
        raise

    drive = gdrive_client.build_drive_service(creds)
    folder_id = self._folder_id
    patch: dict[str, Any] | None = None
    if not folder_id:
        folder_id = self._lookup_or_create_folder(drive)
        patch = {"folder_id": folder_id}

    # Liste le contenu pour valider l'accès.
    try:
        drive.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            pageSize=1, fields="files(id)",
        ).execute()
    except Exception as exc:
        # HttpError ou autre — propage avec message clair.
        raise RemoteBackupProviderError(
            f"drive_api_error: {exc}"
        ) from exc
    return patch


def _lookup_or_create_folder(self, drive: Any) -> str:
    """Cherche un dossier nommé self._folder_name en racine. Le crée si absent."""
    escaped = self._folder_name.replace("'", "\\'")
    try:
        result = drive.files().list(
            q=f"name = '{escaped}' and mimeType = '{_FOLDER_MIME}' "
              f"and 'root' in parents and trashed = false",
            pageSize=1, fields="files(id)",
        ).execute()
    except Exception as exc:
        raise RemoteBackupProviderError(f"drive_api_error: {exc}") from exc

    items = result.get("files", [])
    if items:
        return str(items[0]["id"])

    try:
        created = drive.files().create(
            body={
                "name": self._folder_name,
                "mimeType": _FOLDER_MIME,
                "parents": ["root"],
            },
            fields="id",
        ).execute()
    except Exception as exc:
        raise RemoteBackupProviderError(f"drive_api_error: {exc}") from exc
    return str(created["id"])
```

- [ ] **Step 4: Lancer (expect PASS)**

Run: `cd backend && uv run pytest tests/test_gdrive_provider.py -v`
Expected: 10 passed (5 validation + 5 test_connection).

- [ ] **Step 5: Commit**

```bash
git add backend/src/app/services/remote_backup_providers/gdrive.py backend/tests/test_gdrive_provider.py
git commit -m "feat(gdrive): test_connection — lookup/create folder + listing validation"
```

### Task G3.5 — `upload_stream` : resumable upload via tmp file

**Files:**
- Modify: `backend/src/app/services/remote_backup_providers/gdrive.py`
- Modify: `backend/tests/test_gdrive_provider.py` (ajout)

- [ ] **Step 1: Ajouter les tests (expect FAIL)**

Append à `tests/test_gdrive_provider.py` :

```python
# ── upload_stream ────────────────────────────────────────────────────────────

async def _async_chunks(*chunks: bytes):
    for c in chunks:
        yield c


@pytest.mark.asyncio
async def test_upload_stream_writes_chunks_and_returns_size(_mock_gdrive_client) -> None:
    drive = _mock_gdrive_client.build_drive_service.return_value
    drive.files.return_value.create.return_value.execute.return_value = {
        "id": "uploaded-file-id"
    }

    p = GoogleDriveProvider(
        config={"client_id": "id", "folder_name": "Backups", "folder_id": "F"},
        credentials={"client_secret": "s", "refresh_token": "r"},
    )
    total = await p.upload_stream(
        "/ignored", "snapshot-2026-05-16.tar.age",
        _async_chunks(b"hello ", b"world"),
    )
    assert total == 11  # b"hello world"
    drive.files.return_value.create.assert_called_once()
    kwargs = drive.files.return_value.create.call_args.kwargs
    assert kwargs["body"]["name"] == "snapshot-2026-05-16.tar.age"
    assert kwargs["body"]["parents"] == ["F"]


@pytest.mark.asyncio
async def test_upload_stream_quota_exceeded(_mock_gdrive_client) -> None:
    from googleapiclient.errors import HttpError
    drive = _mock_gdrive_client.build_drive_service.return_value
    fake_resp = MagicMock(status=403, reason="Forbidden")
    drive.files.return_value.create.return_value.execute.side_effect = HttpError(
        resp=fake_resp, content=b'{"error":{"errors":[{"reason":"storageQuotaExceeded"}]}}'
    )

    p = GoogleDriveProvider(
        config={"client_id": "id", "folder_name": "Backups", "folder_id": "F"},
        credentials={"client_secret": "s", "refresh_token": "r"},
    )
    with pytest.raises(RemoteBackupProviderError, match="drive_storage_full|drive_api_error"):
        await p.upload_stream("/", "x.bin", _async_chunks(b"x"))


@pytest.mark.asyncio
async def test_upload_stream_rejects_path_separators() -> None:
    p = GoogleDriveProvider(
        config={"client_id": "id", "folder_name": "Backups", "folder_id": "F"},
        credentials={"client_secret": "s", "refresh_token": "r"},
    )
    with pytest.raises(ValueError, match="path separators"):
        await p.upload_stream("/", "a/b.bin", _async_chunks(b"x"))


@pytest.mark.asyncio
async def test_upload_stream_requires_folder_id(_mock_gdrive_client) -> None:
    p = GoogleDriveProvider(
        config={"client_id": "id", "folder_name": "Backups"},  # pas de folder_id
        credentials={"client_secret": "s", "refresh_token": "r"},
    )
    with pytest.raises(RemoteBackupProviderError, match="folder_id_missing"):
        await p.upload_stream("/", "x.bin", _async_chunks(b"x"))
```

- [ ] **Step 2: Lancer (expect FAIL)**

Run: `cd backend && uv run pytest tests/test_gdrive_provider.py -v -k upload`
Expected: FAIL.

- [ ] **Step 3: Implémenter `upload_stream`**

Remplacer dans `gdrive.py` :

```python
async def upload_stream(
    self, path: str, remote_filename: str, source: AsyncIterator[bytes]
) -> int:
    if "/" in remote_filename or "\\" in remote_filename:
        raise ValueError("remote_filename must not contain path separators")
    if not self._folder_id:
        raise RemoteBackupProviderError(
            "folder_id_missing: run test_connection first to discover/create the target folder"
        )

    # Buffer le AsyncIterator vers un fichier temp local (resumable upload sync
    # requiert un objet seekable). Le tmp est nettoyé en finally.
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".gdrive-upload")
    tmp_path = Path(tmp.name)
    bytes_written = 0
    try:
        try:
            async for chunk in source:
                tmp.write(chunk)
                bytes_written += len(chunk)
        finally:
            tmp.close()
        await asyncio.to_thread(self._upload_sync, tmp_path, remote_filename)
    finally:
        with contextlib.suppress(OSError):
            tmp_path.unlink()
    return bytes_written


def _upload_sync(self, tmp_path: Path, remote_filename: str) -> str:
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    creds = gdrive_client.build_credentials(
        client_id=self._client_id,
        client_secret=self._client_secret,
        refresh_token=self._refresh_token,
        token_uri=self._token_uri,
        scope=self._scope,
    )
    try:
        gdrive_client.refresh(creds)
    except Exception as exc:
        if exc.__class__.__name__ == "RefreshError":
            raise RemoteBackupProviderError(f"credentials_revoked: {exc}") from exc
        raise

    drive = gdrive_client.build_drive_service(creds)
    media = MediaFileUpload(
        str(tmp_path), chunksize=_CHUNK_SIZE,
        resumable=True, mimetype="application/octet-stream",
    )
    try:
        created = drive.files().create(
            body={"name": remote_filename, "parents": [self._folder_id]},
            media_body=media, fields="id",
        ).execute()
    except HttpError as exc:
        content = (exc.content or b"").decode("utf-8", errors="replace")
        if "storageQuotaExceeded" in content:
            raise RemoteBackupProviderError(
                f"drive_storage_full: {content}"
            ) from exc
        if "userRateLimitExceeded" in content:
            raise RemoteBackupProviderError(
                f"drive_quota_exceeded: {content}"
            ) from exc
        raise RemoteBackupProviderError(f"drive_api_error: {exc}") from exc
    except Exception as exc:
        raise RemoteBackupProviderError(f"drive_api_error: {exc}") from exc
    return str(created["id"])
```

- [ ] **Step 4: Lancer (expect PASS)**

Run: `cd backend && uv run pytest tests/test_gdrive_provider.py -v`
Expected: 14 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/app/services/remote_backup_providers/gdrive.py backend/tests/test_gdrive_provider.py
git commit -m "feat(gdrive): upload_stream — resumable upload + mapping erreurs Drive"
```

### Task G3.6 — Câbler la factory + élargir `SUPPORTED_KINDS`

**Files:**
- Modify: `backend/src/app/services/remote_backup_providers/__init__.py`

- [ ] **Step 1: Écrire le test**

```python
# backend/tests/test_remote_backup_providers_factory_gdrive.py
"""La factory get_provider supporte 'gdrive' et SUPPORTED_KINDS le contient."""

from __future__ import annotations

from app.services.remote_backup_providers import SUPPORTED_KINDS, get_provider
from app.services.remote_backup_providers.gdrive import GoogleDriveProvider


def test_supported_kinds_contains_gdrive() -> None:
    assert "gdrive" in SUPPORTED_KINDS


def test_factory_returns_gdrive_provider() -> None:
    p = get_provider(
        "gdrive",
        {"client_id": "id", "folder_name": "F"},
        {"client_secret": "s", "refresh_token": "r"},
    )
    assert isinstance(p, GoogleDriveProvider)
```

- [ ] **Step 2: Lancer (expect FAIL)**

Run: `cd backend && uv run pytest tests/test_remote_backup_providers_factory_gdrive.py -v`
Expected: FAIL.

- [ ] **Step 3: Modifier `__init__.py`**

```python
# backend/src/app/services/remote_backup_providers/__init__.py
"""Providers de backup distant — abstraction + implémentations par protocole.

Chaque provider implémente `RemoteBackupProvider` (cf. base.py) :
  - `test_connection()` : valide les credentials + l'accès au remote_path
  - `upload_stream(remote_filename, source)` : streame un AsyncIterator[bytes] vers le distant

Implémentations :
  - `sftp.SftpProvider`                  (asyncssh)
  - `s3_compatible.S3CompatibleProvider` (boto3 — AWS / R2 / B2 / Scaleway / OVH)
  - `ftps.FtpsProvider`                  (aioftp)
  - `gdrive.GoogleDriveProvider`         (googleapiclient — OAuth user-delegated)
"""

from __future__ import annotations

from typing import Any

from app.services.remote_backup_providers.base import (
    RemoteBackupProvider,
    RemoteBackupProviderError,
)
from app.services.remote_backup_providers.ftps import FtpsProvider
from app.services.remote_backup_providers.gdrive import GoogleDriveProvider
from app.services.remote_backup_providers.s3_compatible import S3CompatibleProvider
from app.services.remote_backup_providers.sftp import SftpProvider

SUPPORTED_KINDS: frozenset[str] = frozenset({"sftp", "s3", "ftps", "gdrive"})


def get_provider(
    kind: str, config: dict[str, Any], credentials: dict[str, Any]
) -> RemoteBackupProvider:
    if kind == "sftp":
        return SftpProvider(config=config, credentials=credentials)
    if kind == "s3":
        return S3CompatibleProvider(config=config, credentials=credentials)
    if kind == "ftps":
        return FtpsProvider(config=config, credentials=credentials)
    if kind == "gdrive":
        return GoogleDriveProvider(config=config, credentials=credentials)
    raise ValueError(f"Unsupported remote backup kind: {kind!r}")


__all__ = [
    "SUPPORTED_KINDS",
    "FtpsProvider",
    "GoogleDriveProvider",
    "RemoteBackupProvider",
    "RemoteBackupProviderError",
    "S3CompatibleProvider",
    "SftpProvider",
    "get_provider",
]
```

- [ ] **Step 4: Lancer (expect PASS)**

Run: `cd backend && uv run pytest tests/test_remote_backup_providers_factory_gdrive.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/app/services/remote_backup_providers/__init__.py backend/tests/test_remote_backup_providers_factory_gdrive.py
git commit -m "feat(gdrive): factory + SUPPORTED_KINDS incluent 'gdrive'"
```

---

## LOT G4 — Service OAuth + endpoints backend

Le LOT G4 livre toute la couche HTTP OAuth : génération d'auth_url, callback Google, lookup de session non-secret, re-autorisation, extension de la création de connexion, branchement du purge sur le scheduler, register du router. À la fin du LOT G4, le backend est utilisable de bout en bout (mais sans UI dédiée — on teste avec `curl` + un navigateur).

### Task G4.1 — Service `gdrive_oauth_session.py`

**Files:**
- Create: `backend/src/app/services/gdrive_oauth_session.py`

Le service ne fait pas d'I/O HTTP — il orchestre les appels au repository, à `gdrive_client`, et fabrique les URLs. Les tests mockent `gdrive_client` (la couche réseau).

- [ ] **Step 1: Écrire les tests**

```python
# backend/tests/test_gdrive_oauth_session.py
"""Tests du service gdrive_oauth_session (orchestrateur OAuth)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import asyncpg
import pytest

from app.services import gdrive_oauth_session as svc


@pytest.mark.asyncio
async def test_create_pending_session_returns_auth_url_and_state(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    fake_flow = MagicMock()
    fake_flow.authorization_url.return_value = (
        "https://accounts.google.com/o/oauth2/v2/auth?response_type=code&client_id=cid&state=STATE",
        "STATE",
    )
    with patch(
        "app.services.gdrive_oauth_session.gdrive_client.build_flow",
        return_value=fake_flow,
    ):
        async with real_db_pool.acquire() as conn:
            async with conn.transaction():
                out = await svc.create_pending_session(
                    conn,
                    name="Backups",
                    client_id="cid",
                    client_secret="csec",
                    folder_name="Harpocrate Backups",
                    redirect_uri="https://harpo.example.com/.../callback",
                    target_connection_id=None,
                    created_by_user_id=None,
                )
                assert "auth_url" in out and "state" in out
                qs = parse_qs(urlparse(out["auth_url"]).query)
                assert qs["state"] == [out["state"]]
                raise _Rollback()


@pytest.mark.asyncio
async def test_finalize_session_marks_authorized_with_user_email(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    fake_flow = MagicMock()
    fake_flow.credentials = MagicMock(refresh_token="rt-xyz")
    with patch(
        "app.services.gdrive_oauth_session.gdrive_client.build_flow",
        return_value=fake_flow,
    ), patch(
        "app.services.gdrive_oauth_session.gdrive_client.fetch_user_email",
        return_value="admin@x.y",
    ):
        async with real_db_pool.acquire() as conn:
            async with conn.transaction():
                created = await svc.create_pending_session(
                    conn, name="N", client_id="cid", client_secret="csec",
                    folder_name="F", redirect_uri="https://h/c",
                    target_connection_id=None, created_by_user_id=None,
                )
                await svc.finalize_session(
                    conn, state=created["state"], code="AUTH_CODE",
                )
                from app.db.repositories import oauth_pending_session as repo
                row = await repo.get_by_state(conn, created["state"])
                assert row["status"] == "authorized"
                assert row["result"]["refresh_token"] == "rt-xyz"
                assert row["result"]["user_email"] == "admin@x.y"
                raise _Rollback()


@pytest.mark.asyncio
async def test_finalize_session_invalid_state_raises(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        with pytest.raises(svc.OAuthSessionError, match="state_not_found"):
            await svc.finalize_session(conn, state="does-not-exist", code="x")


@pytest.mark.asyncio
async def test_mark_failed_records_error(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        async with conn.transaction():
            with patch(
                "app.services.gdrive_oauth_session.gdrive_client.build_flow",
                return_value=MagicMock(authorization_url=lambda **_: ("u", "STATE")),
            ):
                created = await svc.create_pending_session(
                    conn, name="N", client_id="cid", client_secret="csec",
                    folder_name="F", redirect_uri="https://h/c",
                    target_connection_id=None, created_by_user_id=None,
                )
            await svc.mark_session_failed(
                conn, state=created["state"], error="access_denied"
            )
            from app.db.repositories import oauth_pending_session as repo
            row = await repo.get_by_state(conn, created["state"])
            assert row["status"] == "failed"
            assert row["result"]["error"] == "access_denied"
            raise _Rollback()


class _Rollback(Exception):
    pass
```

- [ ] **Step 2: Lancer (expect FAIL)**

Run: `cd backend && uv run pytest tests/test_gdrive_oauth_session.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implémenter le service**

```python
# backend/src/app/services/gdrive_oauth_session.py
"""Service — orchestration des sessions OAuth Google Drive.

Gère le cycle de vie d'une oauth_pending_session :
  create_pending_session -> [callback Google] -> finalize_session -> [save] -> DELETE.

Pas d'I/O HTTP entrant — c'est le rôle du router. Les appels Google passent
par gdrive_client (mockable).
"""

from __future__ import annotations

import logging
import secrets
from typing import Any
from uuid import UUID

import asyncpg

from app.db.repositories import oauth_pending_session as repo
from app.services.remote_backup_providers import gdrive_client

_log = logging.getLogger(__name__)
_PROVIDER = "gdrive"
_TTL_SECONDS = 10 * 60  # 10 min


class OAuthSessionError(Exception):
    """Erreur métier OAuth (state inconnu, expiré, déjà consommé, etc.)."""


async def create_pending_session(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    name: str,
    client_id: str,
    client_secret: str,
    folder_name: str,
    redirect_uri: str,
    target_connection_id: UUID | None,
    created_by_user_id: UUID | None,
) -> dict[str, str]:
    """Crée une oauth_pending_session, retourne {auth_url, state}."""
    state = secrets.token_urlsafe(32)
    flow = gdrive_client.build_flow(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
    )
    auth_url, returned_state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="false",
        prompt="consent",
        state=state,
    )

    await repo.insert(
        conn,
        state=state,
        provider=_PROVIDER,
        payload={
            "name": name,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "folder_name": folder_name,
        },
        target_connection_id=target_connection_id,
        created_by_user_id=created_by_user_id,
        ttl_seconds=_TTL_SECONDS,
    )
    return {"auth_url": auth_url, "state": state}


async def finalize_session(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    state: str,
    code: str,
) -> None:
    """Échange `code` contre des tokens, marque la session 'authorized' avec result."""
    pending = await repo.get_active_by_state(conn, state)
    if pending is None:
        raise OAuthSessionError("state_not_found_or_expired")

    payload = dict(pending["payload"])
    flow = gdrive_client.build_flow(
        client_id=payload["client_id"],
        client_secret=payload["client_secret"],
        redirect_uri=payload["redirect_uri"],
    )
    try:
        flow.fetch_token(code=code)
    except Exception as exc:
        raise OAuthSessionError(f"token_exchange_failed: {exc}") from exc

    creds = flow.credentials
    refresh_token = getattr(creds, "refresh_token", None)
    if not refresh_token:
        raise OAuthSessionError("no_refresh_token_returned")

    try:
        user_email = gdrive_client.fetch_user_email(creds)
    except Exception as exc:
        _log.warning("gdrive_fetch_user_email_failed", extra={"err": str(exc)})
        user_email = ""

    await repo.mark_authorized(
        conn,
        state=state,
        result={
            "refresh_token": refresh_token,
            "user_email": user_email,
            "token_uri": "https://oauth2.googleapis.com/token",
        },
    )


async def mark_session_failed(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    state: str,
    error: str,
) -> None:
    await repo.mark_failed(conn, state=state, error=error)


def public_session_view(row: asyncpg.Record | None) -> dict[str, Any]:
    """Vue publique d'une session — sans aucun secret. Pour GET /session/{state}."""
    if row is None:
        return {"status": "unknown"}
    result = dict(row["result"]) if row["result"] else {}
    safe_result: dict[str, Any] = {}
    if "user_email" in result:
        safe_result["user_email"] = result["user_email"]
    if "error" in result:
        safe_result["error"] = result["error"]
    return {
        "status": row["status"],
        "result": safe_result or None,
    }
```

- [ ] **Step 4: Lancer (expect PASS)**

Run: `cd backend && uv run pytest tests/test_gdrive_oauth_session.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/app/services/gdrive_oauth_session.py backend/tests/test_gdrive_oauth_session.py
git commit -m "feat(gdrive-oauth): service create/finalize/fail + public_session_view"
```

### Task G4.2 — Router OAuth + `GET /redirect-uri`

**Files:**
- Create: `backend/src/app/api/v1/admin_remote_backups_oauth_gdrive.py`
- Test: `backend/tests/test_admin_remote_backups_oauth_gdrive.py`

- [ ] **Step 1: Écrire le test (premier endpoint uniquement)**

```python
# backend/tests/test_admin_remote_backups_oauth_gdrive.py
"""Tests des endpoints /v1/admin/backup-remotes/oauth/gdrive/*."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_redirect_uri_returns_canonical_value(client, admin_jwt_headers, monkeypatch) -> None:
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://harpo.example.com")
    # Recharge settings si nécessaire — sinon utiliser la fixture du projet.
    r = await client.get(
        "/v1/admin/backup-remotes/oauth/gdrive/redirect-uri",
        headers=admin_jwt_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["redirect_uri"].endswith("/v1/admin/backup-remotes/oauth/gdrive/callback")


@pytest.mark.asyncio
async def test_redirect_uri_requires_admin(client) -> None:
    r = await client.get("/v1/admin/backup-remotes/oauth/gdrive/redirect-uri")
    assert r.status_code in (401, 403)
```

- [ ] **Step 2: Lancer (expect FAIL)**

Run: `cd backend && uv run pytest tests/test_admin_remote_backups_oauth_gdrive.py -v`
Expected: FAIL (404 ou ImportError).

- [ ] **Step 3: Créer le router avec son premier endpoint**

```python
# backend/src/app/api/v1/admin_remote_backups_oauth_gdrive.py
"""Endpoints OAuth Google Drive pour les connexions de backup distantes.

Tous protégés par AdminJwt. Préfixe /v1/admin/backup-remotes/oauth/gdrive.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.admin_auth import AdminJwt
from app.core.config import settings

router = APIRouter(
    prefix="/admin/backup-remotes/oauth/gdrive",
    tags=["admin-remote-backups-oauth-gdrive"],
)

_CALLBACK_SUFFIX = "/v1/admin/backup-remotes/oauth/gdrive/callback"


def _canonical_redirect_uri() -> str:
    base = settings.public_url.rstrip("/")
    return f"{base}{_CALLBACK_SUFFIX}"


@router.get("/redirect-uri", response_class=JSONResponse)
async def get_redirect_uri(admin: AdminJwt) -> JSONResponse:
    return JSONResponse({"redirect_uri": _canonical_redirect_uri()})
```

Et register dans `main.py` (anticipation, sinon le test 404) :

```python
# backend/src/app/main.py — section app.include_router(...)
from app.api.v1 import admin_remote_backups_oauth_gdrive
...
app.include_router(admin_remote_backups_oauth_gdrive.router, prefix="/v1")
```

- [ ] **Step 4: Lancer (expect PASS)**

Run: `cd backend && uv run pytest tests/test_admin_remote_backups_oauth_gdrive.py -v -k redirect_uri`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/app/api/v1/admin_remote_backups_oauth_gdrive.py backend/src/app/main.py backend/tests/test_admin_remote_backups_oauth_gdrive.py
git commit -m "feat(gdrive-oauth): router + GET /redirect-uri canonique"
```

### Task G4.3 — `POST /start`

**Files:**
- Modify: `backend/src/app/api/v1/admin_remote_backups_oauth_gdrive.py`
- Modify: `backend/tests/test_admin_remote_backups_oauth_gdrive.py`

- [ ] **Step 1: Ajouter les tests**

Append :

```python
@pytest.mark.asyncio
async def test_oauth_start_creates_pending_and_returns_auth_url(
    client, admin_jwt_headers, real_db_pool,
) -> None:
    fake_flow = MagicMock()
    fake_flow.authorization_url.return_value = (
        "https://accounts.google.com/o/oauth2/v2/auth?...", "STATE-X",
    )
    with patch(
        "app.services.gdrive_oauth_session.gdrive_client.build_flow",
        return_value=fake_flow,
    ):
        r = await client.post(
            "/v1/admin/backup-remotes/oauth/gdrive/start",
            json={
                "name": "Backups perso",
                "client_id": "cid.apps.googleusercontent.com",
                "client_secret": "GOCSPX-fake",
                "folder_name": "Harpocrate Backups",
            },
            headers=admin_jwt_headers,
        )
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "STATE-X"
    assert body["auth_url"].startswith("https://accounts.google.com/")

    # Vérifie qu'une ligne pending a été créée
    async with real_db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM oauth_pending_session WHERE state = $1", "STATE-X"
        )
        assert row is not None
        assert row["status"] == "pending"
        assert row["payload"]["folder_name"] == "Harpocrate Backups"


@pytest.mark.asyncio
async def test_oauth_start_validates_required_fields(client, admin_jwt_headers) -> None:
    r = await client.post(
        "/v1/admin/backup-remotes/oauth/gdrive/start",
        json={"name": "X"},  # manque client_id/secret/folder
        headers=admin_jwt_headers,
    )
    assert r.status_code == 422
```

- [ ] **Step 2: Lancer (expect FAIL)**

Run: `cd backend && uv run pytest tests/test_admin_remote_backups_oauth_gdrive.py -v -k start`
Expected: FAIL.

- [ ] **Step 3: Ajouter l'endpoint au router**

Dans `admin_remote_backups_oauth_gdrive.py` :

```python
from pydantic import BaseModel, Field

from app.db.pool import get_pool
from app.services import gdrive_oauth_session as svc


class StartRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    client_id: str = Field(min_length=1)
    client_secret: str = Field(min_length=1)
    folder_name: str = Field(min_length=1, max_length=255)


@router.post("/start", response_class=JSONResponse)
async def start_oauth_flow(body: StartRequest, admin: AdminJwt) -> JSONResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        out = await svc.create_pending_session(
            conn,
            name=body.name,
            client_id=body.client_id,
            client_secret=body.client_secret,
            folder_name=body.folder_name,
            redirect_uri=_canonical_redirect_uri(),
            target_connection_id=None,
            created_by_user_id=None,
        )
    return JSONResponse(out)
```

- [ ] **Step 4: Lancer (expect PASS)**

Run: `cd backend && uv run pytest tests/test_admin_remote_backups_oauth_gdrive.py -v -k start`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/app/api/v1/admin_remote_backups_oauth_gdrive.py backend/tests/test_admin_remote_backups_oauth_gdrive.py
git commit -m "feat(gdrive-oauth): POST /start — création pending_session + auth_url"
```

### Task G4.4 — `GET /callback`

**Files:**
- Modify: `backend/src/app/api/v1/admin_remote_backups_oauth_gdrive.py`
- Modify: `backend/tests/test_admin_remote_backups_oauth_gdrive.py`

- [ ] **Step 1: Ajouter les tests**

```python
@pytest.mark.asyncio
async def test_oauth_callback_happy_path(
    client, real_db_pool, monkeypatch,
) -> None:
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://harpo.example.com")
    # Insère manuellement une pending_session
    async with real_db_pool.acquire() as conn:
        from app.db.repositories import oauth_pending_session as repo
        await repo.insert(
            conn, state="HAPPY", provider="gdrive",
            payload={
                "client_id": "cid", "client_secret": "sec",
                "redirect_uri": "https://harpo.example.com/v1/admin/backup-remotes/oauth/gdrive/callback",
                "folder_name": "F", "name": "N",
            },
            target_connection_id=None, created_by_user_id=None, ttl_seconds=600,
        )

    fake_flow = MagicMock()
    fake_flow.credentials = MagicMock(refresh_token="RT-OK")
    with patch(
        "app.services.gdrive_oauth_session.gdrive_client.build_flow",
        return_value=fake_flow,
    ), patch(
        "app.services.gdrive_oauth_session.gdrive_client.fetch_user_email",
        return_value="ok@x.y",
    ):
        r = await client.get(
            "/v1/admin/backup-remotes/oauth/gdrive/callback?code=AUTH&state=HAPPY"
        )
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "HAPPY" in r.text
    assert "ok\":true" in r.text or "ok: true" in r.text

    # Vérifie la mise à jour DB
    async with real_db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM oauth_pending_session WHERE state = $1", "HAPPY"
        )
        assert row["status"] == "authorized"
        assert row["result"]["refresh_token"] == "RT-OK"


@pytest.mark.asyncio
async def test_oauth_callback_state_unknown_returns_error_html(client) -> None:
    r = await client.get(
        "/v1/admin/backup-remotes/oauth/gdrive/callback?code=X&state=NOPE"
    )
    assert r.status_code == 400
    assert "text/html" in r.headers["content-type"]
    # PAS de postMessage si state inconnu (opener pourrait être malveillant)
    assert "postMessage" not in r.text


@pytest.mark.asyncio
async def test_oauth_callback_user_refused(client, real_db_pool) -> None:
    async with real_db_pool.acquire() as conn:
        from app.db.repositories import oauth_pending_session as repo
        await repo.insert(
            conn, state="REFUSED", provider="gdrive",
            payload={"client_id": "x", "client_secret": "y", "redirect_uri": "z", "folder_name": "F", "name": "N"},
            target_connection_id=None, created_by_user_id=None, ttl_seconds=600,
        )
    r = await client.get(
        "/v1/admin/backup-remotes/oauth/gdrive/callback?state=REFUSED&error=access_denied"
    )
    assert r.status_code == 200
    assert "REFUSED" in r.text
    assert "false" in r.text  # ok:false
    async with real_db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM oauth_pending_session WHERE state = $1", "REFUSED"
        )
        assert row["status"] == "failed"
        assert row["result"]["error"] == "access_denied"
```

- [ ] **Step 2: Lancer (expect FAIL)**

Run: `cd backend && uv run pytest tests/test_admin_remote_backups_oauth_gdrive.py -v -k callback`
Expected: FAIL.

- [ ] **Step 3: Implémenter l'endpoint**

Ajouter au router (note : pas d'auth admin sur ce endpoint — Google appelle directement, le state est notre CSRF) :

```python
import json as _json

from fastapi import HTTPException, Query
from fastapi.responses import HTMLResponse


_CALLBACK_HTML_OK = """<!doctype html>
<html><head><meta charset="utf-8"><title>Google Drive Authorization</title></head>
<body>
<p>Authorization complete. This window will close automatically.</p>
<script>
(function () {{
  var msg = {{ type: 'gdrive_oauth_done', state: {state_js}, ok: {ok_js}, error: {error_js} }};
  if (window.opener) {{ window.opener.postMessage(msg, window.location.origin); }}
  window.close();
}})();
</script>
</body></html>"""

_CALLBACK_HTML_ERROR_NO_STATE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Authorization error</title></head>
<body>
<p>Authorization error: invalid or expired state. You can close this window.</p>
</body></html>"""


def _render_callback_html(state: str, ok: bool, error: str | None) -> str:
    return _CALLBACK_HTML_OK.format(
        state_js=_json.dumps(state),
        ok_js=_json.dumps(ok),
        error_js=_json.dumps(error),
    )


@router.get("/callback", response_class=HTMLResponse)
async def oauth_callback(
    state: str = Query(...),
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> HTMLResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        from app.db.repositories import oauth_pending_session as repo
        existing = await repo.get_active_by_state(conn, state)
        if existing is None:
            return HTMLResponse(_CALLBACK_HTML_ERROR_NO_STATE, status_code=400)

        if error:
            await svc.mark_session_failed(conn, state=state, error=error)
            return HTMLResponse(_render_callback_html(state, False, error))

        if not code:
            await svc.mark_session_failed(conn, state=state, error="missing_code")
            return HTMLResponse(_render_callback_html(state, False, "missing_code"))

        try:
            await svc.finalize_session(conn, state=state, code=code)
        except svc.OAuthSessionError as exc:
            await svc.mark_session_failed(conn, state=state, error=str(exc))
            return HTMLResponse(_render_callback_html(state, False, str(exc)))

    return HTMLResponse(_render_callback_html(state, True, None))
```

- [ ] **Step 4: Lancer (expect PASS)**

Run: `cd backend && uv run pytest tests/test_admin_remote_backups_oauth_gdrive.py -v -k callback`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/app/api/v1/admin_remote_backups_oauth_gdrive.py backend/tests/test_admin_remote_backups_oauth_gdrive.py
git commit -m "feat(gdrive-oauth): GET /callback — HTML auto-fermant + postMessage"
```

### Task G4.5 — `GET /session/{state}`

**Files:**
- Modify: `backend/src/app/api/v1/admin_remote_backups_oauth_gdrive.py`
- Modify: `backend/tests/test_admin_remote_backups_oauth_gdrive.py`

- [ ] **Step 1: Ajouter les tests**

```python
@pytest.mark.asyncio
async def test_session_lookup_hides_secrets(client, admin_jwt_headers, real_db_pool) -> None:
    async with real_db_pool.acquire() as conn:
        from app.db.repositories import oauth_pending_session as repo
        await repo.insert(
            conn, state="LOOKUP", provider="gdrive",
            payload={"client_id": "x", "client_secret": "SECRET", "redirect_uri": "u",
                     "folder_name": "F", "name": "N"},
            target_connection_id=None, created_by_user_id=None, ttl_seconds=600,
        )
        await repo.mark_authorized(
            conn, state="LOOKUP",
            result={"refresh_token": "RT-SECRET", "user_email": "ok@x.y"},
        )

    r = await client.get(
        "/v1/admin/backup-remotes/oauth/gdrive/session/LOOKUP",
        headers=admin_jwt_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "authorized"
    assert body["result"]["user_email"] == "ok@x.y"
    # Aucun secret ne doit fuiter
    raw = r.text
    assert "RT-SECRET" not in raw
    assert "SECRET" not in raw or raw.count("SECRET") == 0
    assert "client_secret" not in raw
    assert "refresh_token" not in raw


@pytest.mark.asyncio
async def test_session_unknown_returns_unknown(client, admin_jwt_headers) -> None:
    r = await client.get(
        "/v1/admin/backup-remotes/oauth/gdrive/session/DOES_NOT_EXIST",
        headers=admin_jwt_headers,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "unknown"
```

- [ ] **Step 2: Lancer (expect FAIL)**

Run: `cd backend && uv run pytest tests/test_admin_remote_backups_oauth_gdrive.py -v -k session`
Expected: FAIL.

- [ ] **Step 3: Ajouter l'endpoint**

```python
from fastapi import Path


@router.get("/session/{state}", response_class=JSONResponse)
async def get_oauth_session(
    state: str = Path(..., min_length=1, max_length=128),
    admin: AdminJwt = None,  # type: ignore[assignment]
) -> JSONResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        from app.db.repositories import oauth_pending_session as repo
        row = await repo.get_by_state(conn, state)
    return JSONResponse(svc.public_session_view(row))
```

- [ ] **Step 4: Lancer (expect PASS)**

Run: `cd backend && uv run pytest tests/test_admin_remote_backups_oauth_gdrive.py -v -k session`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/app/api/v1/admin_remote_backups_oauth_gdrive.py backend/tests/test_admin_remote_backups_oauth_gdrive.py
git commit -m "feat(gdrive-oauth): GET /session/{state} — vue publique sans secret"
```

### Task G4.6 — `POST /{id}/reauthorize`

**Files:**
- Modify: `backend/src/app/api/v1/admin_remote_backups_oauth_gdrive.py`
- Modify: `backend/tests/test_admin_remote_backups_oauth_gdrive.py`

- [ ] **Step 1: Ajouter le test**

```python
@pytest.mark.asyncio
async def test_reauthorize_creates_pending_with_target(
    client, admin_jwt_headers, real_db_pool,
) -> None:
    # Crée une connexion gdrive existante (via insert direct repo, on évite le flux complet)
    from uuid import uuid4
    conn_id = uuid4()
    async with real_db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO remote_backup_connection
                (id, name, kind, config, credentials_encrypted)
            VALUES ($1, $2, 'gdrive', $3::jsonb, '\\x00'::bytea)
            """,
            conn_id, f"DriveX-{conn_id}",
            __import__("json").dumps({
                "client_id": "cid", "folder_name": "F",
                "redirect_uri": "https://harpo.example.com/v1/admin/backup-remotes/oauth/gdrive/callback",
                "user_email": "old@x.y",
            }),
        )

    fake_flow = MagicMock()
    fake_flow.authorization_url.return_value = ("https://accounts.google/...", "REAUTH-STATE")
    # Mock get_decrypted_credentials : le blob '\x00' inséré n'est pas un vrai AES-GCM,
    # on contourne la couche crypto pour ce test focus reauthorize.
    with patch(
        "app.services.gdrive_oauth_session.gdrive_client.build_flow",
        return_value=fake_flow,
    ), patch(
        "app.api.v1.admin_remote_backups.svc.get_decrypted_credentials",
        return_value={"client_secret": "csec-stored", "refresh_token": "rt-old",
                      "scope": "https://www.googleapis.com/auth/drive.file",
                      "token_uri": "https://oauth2.googleapis.com/token"},
    ):
        r = await client.post(
            f"/v1/admin/backup-remotes/{conn_id}/reauthorize",
            headers=admin_jwt_headers,
        )
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "REAUTH-STATE"

    async with real_db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM oauth_pending_session WHERE state = $1", "REAUTH-STATE"
        )
        assert row["target_connection_id"] == conn_id


@pytest.mark.asyncio
async def test_reauthorize_404_when_connection_missing(client, admin_jwt_headers) -> None:
    from uuid import uuid4
    r = await client.post(
        f"/v1/admin/backup-remotes/{uuid4()}/reauthorize",
        headers=admin_jwt_headers,
    )
    assert r.status_code == 404
```

Note : l'endpoint vit dans `admin_remote_backups.py` (pas le router OAuth) parce qu'il est sur le path `/admin/backup-remotes/{id}/reauthorize`, pas sous `/oauth/gdrive`. **À déplacer dans le bon fichier** — adapter l'import du test.

- [ ] **Step 2: Lancer (expect FAIL)**

Run: `cd backend && uv run pytest tests/test_admin_remote_backups_oauth_gdrive.py -v -k reauthorize`
Expected: FAIL.

- [ ] **Step 3: Implémenter l'endpoint dans `admin_remote_backups.py`**

Ajouter à `backend/src/app/api/v1/admin_remote_backups.py` :

```python
from app.services import gdrive_oauth_session as gdrive_svc


@router.post("/{connection_id}/reauthorize", response_class=JSONResponse)
async def reauthorize_remote_backup(
    connection_id: UUID, admin: AdminJwt
) -> JSONResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        item = await svc.get_connection(conn, connection_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "connection_not_found"},
            )
        if item.kind != "gdrive":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "reauthorize_unsupported_kind", "kind": item.kind},
            )
        cfg = item.config
        existing_creds = await svc.get_decrypted_credentials(conn, connection_id)
        if existing_creds is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "no_existing_credentials"},
            )
        out = await gdrive_svc.create_pending_session(
            conn,
            name=item.name,
            client_id=cfg["client_id"],
            client_secret=existing_creds["client_secret"],
            folder_name=cfg["folder_name"],
            redirect_uri=cfg["redirect_uri"],
            target_connection_id=connection_id,
            created_by_user_id=None,
        )
    return JSONResponse(out)
```

- [ ] **Step 4: Lancer (expect PASS)**

Run: `cd backend && uv run pytest tests/test_admin_remote_backups_oauth_gdrive.py -v -k reauthorize`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/app/api/v1/admin_remote_backups.py backend/tests/test_admin_remote_backups_oauth_gdrive.py
git commit -m "feat(gdrive-oauth): POST /{id}/reauthorize pour connexions gdrive"
```

### Task G4.7 — Extension du `POST /admin/backup-remotes` pour `kind=gdrive`

**Files:**
- Modify: `backend/src/app/api/v1/admin_remote_backups.py`
- Modify: `backend/src/app/services/remote_backup_connections.py` (si nécessaire)
- Create: `backend/tests/test_admin_remote_backups_create_gdrive.py`

- [ ] **Step 1: Écrire les tests**

```python
# backend/tests/test_admin_remote_backups_create_gdrive.py
"""Création d'une connexion gdrive via POST /admin/backup-remotes (consomme oauth_state)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_create_gdrive_consumes_authorized_session(
    client, admin_jwt_headers, real_db_pool,
) -> None:
    # 1. Crée une session authorized en DB
    async with real_db_pool.acquire() as conn:
        from app.db.repositories import oauth_pending_session as repo
        await repo.insert(
            conn, state="OK-CREATE", provider="gdrive",
            payload={
                "name": "Drive perso", "client_id": "cid",
                "client_secret": "csec", "folder_name": "Backups",
                "redirect_uri": "https://harpo.example.com/v1/admin/backup-remotes/oauth/gdrive/callback",
            },
            target_connection_id=None, created_by_user_id=None, ttl_seconds=600,
        )
        await repo.mark_authorized(
            conn, state="OK-CREATE",
            result={"refresh_token": "RT", "user_email": "ok@x.y"},
        )

    r = await client.post(
        "/v1/admin/backup-remotes",
        json={
            "name": "Drive perso",
            "kind": "gdrive",
            "config": {},
            "credentials": {},
            "oauth_state": "OK-CREATE",
        },
        headers=admin_jwt_headers,
    )
    assert r.status_code == 201
    new_id = r.json()["id"]

    async with real_db_pool.acquire() as conn:
        # Pending session supprimée
        row = await conn.fetchrow(
            "SELECT * FROM oauth_pending_session WHERE state = $1", "OK-CREATE"
        )
        assert row is None
        # Connection bien insérée
        row = await conn.fetchrow(
            "SELECT * FROM remote_backup_connection WHERE id = $1", new_id
        )
        assert row["kind"] == "gdrive"
        cfg = row["config"]
        assert cfg["client_id"] == "cid"
        assert cfg["folder_name"] == "Backups"
        assert cfg["user_email"] == "ok@x.y"


@pytest.mark.asyncio
async def test_create_gdrive_missing_oauth_state_422(client, admin_jwt_headers) -> None:
    r = await client.post(
        "/v1/admin/backup-remotes",
        json={
            "name": "X", "kind": "gdrive",
            "config": {}, "credentials": {},
            # pas de oauth_state
        },
        headers=admin_jwt_headers,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_gdrive_pending_session_not_authorized_422(
    client, admin_jwt_headers, real_db_pool,
) -> None:
    async with real_db_pool.acquire() as conn:
        from app.db.repositories import oauth_pending_session as repo
        await repo.insert(
            conn, state="STILL-PENDING", provider="gdrive",
            payload={"name": "X", "client_id": "c", "client_secret": "s",
                     "folder_name": "F", "redirect_uri": "u"},
            target_connection_id=None, created_by_user_id=None, ttl_seconds=600,
        )
        # PAS d'appel à mark_authorized -> reste pending

    r = await client.post(
        "/v1/admin/backup-remotes",
        json={"name": "X", "kind": "gdrive", "config": {}, "credentials": {},
              "oauth_state": "STILL-PENDING"},
        headers=admin_jwt_headers,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_get_gdrive_connection_hides_secrets(
    client, admin_jwt_headers, real_db_pool,
) -> None:
    # Réutilise la fixture précédente — création complète
    async with real_db_pool.acquire() as conn:
        from app.db.repositories import oauth_pending_session as repo
        await repo.insert(
            conn, state="SECRET-CHECK", provider="gdrive",
            payload={"name": "S", "client_id": "c", "client_secret": "VERY-SECRET",
                     "folder_name": "F",
                     "redirect_uri": "https://harpo.example.com/v1/admin/backup-remotes/oauth/gdrive/callback"},
            target_connection_id=None, created_by_user_id=None, ttl_seconds=600,
        )
        await repo.mark_authorized(
            conn, state="SECRET-CHECK",
            result={"refresh_token": "VERY-SECRET-RT", "user_email": "s@x.y"},
        )

    r = await client.post(
        "/v1/admin/backup-remotes",
        json={"name": "S", "kind": "gdrive", "config": {}, "credentials": {},
              "oauth_state": "SECRET-CHECK"},
        headers=admin_jwt_headers,
    )
    new_id = r.json()["id"]

    # GET /admin/backup-remotes/{id} ne doit jamais fuiter les secrets
    r2 = await client.get(
        f"/v1/admin/backup-remotes/{new_id}", headers=admin_jwt_headers
    )
    assert r2.status_code == 200
    raw = r2.text
    assert "VERY-SECRET" not in raw
    assert "client_secret" not in raw
    assert "refresh_token" not in raw

    # LIST aussi
    r3 = await client.get("/v1/admin/backup-remotes", headers=admin_jwt_headers)
    assert r3.status_code == 200
    raw = r3.text
    assert "VERY-SECRET" not in raw
```

- [ ] **Step 2: Lancer (expect FAIL)**

Run: `cd backend && uv run pytest tests/test_admin_remote_backups_create_gdrive.py -v`
Expected: FAIL.

- [ ] **Step 3: Étendre le POST**

Dans `admin_remote_backups.py`, modifier le modèle `RemoteBackupCreate` et l'endpoint `create_remote_backup` :

```python
class RemoteBackupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    kind: str
    config: dict[str, Any]
    credentials: dict[str, Any]
    oauth_state: str | None = None  # requis quand kind='gdrive'

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, v: str) -> str:
        if v not in _ALLOWED_KINDS:
            raise ValueError(f"kind must be one of {sorted(_ALLOWED_KINDS)}")
        return v


@router.post("", status_code=status.HTTP_201_CREATED, response_class=JSONResponse)
async def create_remote_backup(body: RemoteBackupCreate, admin: AdminJwt) -> JSONResponse:
    pool = await get_pool()

    # Branche gdrive : consomme une oauth_pending_session authorized
    if body.kind == "gdrive":
        if not body.oauth_state:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "oauth_state_required_for_gdrive"},
            )
        async with pool.acquire() as conn:
            from app.db.repositories import oauth_pending_session as repo
            pending = await repo.get_by_state(conn, body.oauth_state)
            if pending is None or pending["status"] != "authorized":
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={"error": "oauth_session_not_authorized"},
                )
            payload = dict(pending["payload"])
            result = dict(pending["result"] or {})

            target_id = pending["target_connection_id"]
            cfg = {
                "client_id": payload["client_id"],
                "redirect_uri": payload["redirect_uri"],
                "folder_name": payload["folder_name"],
                "user_email": result.get("user_email", ""),
            }
            creds = {
                "client_secret": payload["client_secret"],
                "refresh_token": result["refresh_token"],
                "scope": "https://www.googleapis.com/auth/drive.file",
                "token_uri": result.get("token_uri", "https://oauth2.googleapis.com/token"),
            }
            try:
                if target_id is None:
                    new_id = await svc.create_connection(
                        conn, name=body.name, kind="gdrive",
                        config=cfg, credentials=creds, created_by_user_id=None,
                    )
                else:
                    await svc.update_connection(
                        conn, connection_id=target_id, name=None,
                        config=cfg, credentials=creds,
                    )
                    new_id = target_id
                await repo.delete_by_state(conn, body.oauth_state)
            except Exception as exc:
                msg = str(exc)
                if "unique" in msg.lower() or "23505" in msg:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={"error": "name_already_exists"},
                    ) from exc
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={"error": "internal_error", "message": msg},
                ) from exc
        return JSONResponse({"id": str(new_id)}, status_code=status.HTTP_201_CREATED)

    # Branche existante (sftp/s3/ftps) inchangée
    async with pool.acquire() as conn:
        try:
            new_id = await svc.create_connection(
                conn, name=body.name, kind=body.kind,
                config=body.config, credentials=body.credentials,
                created_by_user_id=None,
            )
        except Exception as exc:
            msg = str(exc)
            if "unique" in msg.lower() or "23505" in msg:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"error": "name_already_exists"},
                ) from exc
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": "internal_error", "message": msg},
            ) from exc
    return JSONResponse({"id": str(new_id)}, status_code=status.HTTP_201_CREATED)
```

- [ ] **Step 4: Lancer (expect PASS)**

Run: `cd backend && uv run pytest tests/test_admin_remote_backups_create_gdrive.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/app/api/v1/admin_remote_backups.py backend/tests/test_admin_remote_backups_create_gdrive.py
git commit -m "feat(gdrive-oauth): POST /admin/backup-remotes consomme oauth_state pour kind=gdrive"
```

### Task G4.8 — Brancher le purge dans `snapshot_scheduler`

**Files:**
- Modify: `backend/src/app/services/snapshot_scheduler.py`
- Create: `backend/tests/test_purge_expired_oauth_sessions.py`

- [ ] **Step 1: Écrire le test**

```python
# backend/tests/test_purge_expired_oauth_sessions.py
"""Le snapshot scheduler appelle bien purge_expired_oauth_sessions à chaque cycle."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import asyncpg
import pytest


@pytest.mark.asyncio
async def test_purge_called_each_cycle(real_db_pool: asyncpg.Pool[asyncpg.Record]) -> None:
    """Insère une session expirée, lance un cycle, vérifie qu'elle est purgée."""
    async with real_db_pool.acquire() as conn:
        from app.db.repositories import oauth_pending_session as repo
        await repo.insert(
            conn, state="EXPIRED", provider="gdrive", payload={},
            target_connection_id=None, created_by_user_id=None, ttl_seconds=-1,
        )

    from app.services.snapshot_scheduler import run_scheduler_cycle_once
    await run_scheduler_cycle_once()

    async with real_db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM oauth_pending_session WHERE state = $1", "EXPIRED"
        )
        assert row is None
```

- [ ] **Step 2: Lancer (expect FAIL)**

Run: `cd backend && uv run pytest tests/test_purge_expired_oauth_sessions.py -v`
Expected: FAIL (`run_scheduler_cycle_once` probablement à exposer, ou la session ne sera pas purgée).

- [ ] **Step 3: Brancher le purge**

Dans `backend/src/app/services/snapshot_scheduler.py`, exposer `run_scheduler_cycle_once` (s'il n'existe pas — extraire le corps du cycle) et y ajouter l'appel :

```python
# En haut du fichier
from app.db.repositories import oauth_pending_session as oauth_repo

# Dans le cycle (fonction extraite ou existante)
async def run_scheduler_cycle_once() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        # ... logique snapshot existante ...
        # Purge des sessions OAuth expirées (coût négligeable)
        purged = await oauth_repo.purge_expired(conn)
        if purged:
            _log.info("oauth_sessions_purged", extra={"count": purged})
```

- [ ] **Step 4: Lancer (expect PASS)**

Run: `cd backend && uv run pytest tests/test_purge_expired_oauth_sessions.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/app/services/snapshot_scheduler.py backend/tests/test_purge_expired_oauth_sessions.py
git commit -m "feat(gdrive-oauth): purge_expired_oauth_sessions branché sur scheduler"
```

### Task G4.8b — Audit log pour les opérations OAuth gdrive (invariant sécurité #9)

**Files:**
- Modify: `backend/src/app/services/gdrive_oauth_session.py`
- Modify: `backend/src/app/api/v1/admin_remote_backups.py` (endpoint reauthorize)

L'invariant de sécurité #9 de la spec exige des entrées d'audit log pour chaque étape OAuth, sans jamais inclure de secret. On utilise l'API `audit_log` existante du projet (mêmes patterns que les autres services).

- [ ] **Step 1: Écrire les tests**

```python
# backend/tests/test_gdrive_oauth_audit_log.py
"""Les opérations OAuth gdrive écrivent dans audit_log (sans secret)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_oauth_start_writes_audit_log(client, admin_jwt_headers, real_db_pool) -> None:
    fake_flow = MagicMock()
    fake_flow.authorization_url.return_value = ("https://accounts.google/...", "AUD-1")
    with patch(
        "app.services.gdrive_oauth_session.gdrive_client.build_flow",
        return_value=fake_flow,
    ):
        await client.post(
            "/v1/admin/backup-remotes/oauth/gdrive/start",
            json={"name": "X", "client_id": "cid", "client_secret": "csec",
                  "folder_name": "F"},
            headers=admin_jwt_headers,
        )
    async with real_db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM audit_log WHERE action = $1 ORDER BY created_at DESC LIMIT 1",
            "remote_backup.gdrive.oauth_started",
        )
    assert len(rows) == 1
    meta = rows[0]["metadata"]
    if isinstance(meta, str):
        import json as _j
        meta = _j.loads(meta)
    # Aucun secret ne doit fuiter dans metadata
    raw = str(meta)
    assert "csec" not in raw
    assert "client_secret" not in raw


@pytest.mark.asyncio
async def test_oauth_callback_writes_completed_log(client, real_db_pool) -> None:
    async with real_db_pool.acquire() as conn:
        from app.db.repositories import oauth_pending_session as repo
        await repo.insert(
            conn, state="AUD-2", provider="gdrive",
            payload={"client_id": "x", "client_secret": "SECRET",
                     "redirect_uri": "https://harpo.example.com/v1/admin/backup-remotes/oauth/gdrive/callback",
                     "folder_name": "F", "name": "N"},
            target_connection_id=None, created_by_user_id=None, ttl_seconds=600,
        )

    fake_flow = MagicMock()
    fake_flow.credentials = MagicMock(refresh_token="RT-NEVER-LEAK")
    with patch(
        "app.services.gdrive_oauth_session.gdrive_client.build_flow",
        return_value=fake_flow,
    ), patch(
        "app.services.gdrive_oauth_session.gdrive_client.fetch_user_email",
        return_value="ok@x.y",
    ):
        await client.get(
            "/v1/admin/backup-remotes/oauth/gdrive/callback?code=AUTH&state=AUD-2"
        )

    async with real_db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM audit_log WHERE action = $1 ORDER BY created_at DESC LIMIT 1",
            "remote_backup.gdrive.oauth_completed",
        )
    assert len(rows) == 1
    raw = str(rows[0]["metadata"])
    assert "RT-NEVER-LEAK" not in raw
    assert "SECRET" not in raw


@pytest.mark.asyncio
async def test_oauth_callback_failed_writes_failed_log(client, real_db_pool) -> None:
    async with real_db_pool.acquire() as conn:
        from app.db.repositories import oauth_pending_session as repo
        await repo.insert(
            conn, state="AUD-3", provider="gdrive",
            payload={"client_id": "x", "client_secret": "y",
                     "redirect_uri": "z", "folder_name": "F", "name": "N"},
            target_connection_id=None, created_by_user_id=None, ttl_seconds=600,
        )
    await client.get(
        "/v1/admin/backup-remotes/oauth/gdrive/callback?state=AUD-3&error=access_denied"
    )
    async with real_db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM audit_log WHERE action = $1 ORDER BY created_at DESC LIMIT 1",
            "remote_backup.gdrive.oauth_failed",
        )
    assert len(rows) == 1
```

- [ ] **Step 2: Lancer (expect FAIL)**

Run: `cd backend && uv run pytest tests/test_gdrive_oauth_audit_log.py -v`
Expected: FAIL.

- [ ] **Step 3: Brancher l'audit log dans le service**

Dans `gdrive_oauth_session.py`, ajouter en haut :

```python
from app.services.audit_log import log_action  # adapter au nom réel dans le projet
```

Puis dans chaque fonction publique :

```python
async def create_pending_session(...):
    # ... corps existant ...
    await log_action(
        conn,
        action="remote_backup.gdrive.oauth_started",
        actor_user_id=created_by_user_id,
        metadata={
            "connection_name": name,
            "folder_name": folder_name,
            "client_id_suffix": client_id[-12:],  # tail pour debug, pas le secret
            "target_connection_id": str(target_connection_id) if target_connection_id else None,
        },
    )
    return {"auth_url": auth_url, "state": state}


async def finalize_session(...):
    # ... corps existant jusqu'à mark_authorized ...
    await log_action(
        conn,
        action="remote_backup.gdrive.oauth_completed",
        actor_user_id=None,  # callback Google n'a pas notre admin
        metadata={
            "state": state,
            "user_email": user_email,
        },
    )


async def mark_session_failed(...):
    # ... corps existant ...
    await log_action(
        conn,
        action="remote_backup.gdrive.oauth_failed",
        actor_user_id=None,
        metadata={"state": state, "error": error},
    )
```

Et dans l'endpoint reauthorize de `admin_remote_backups.py`, après le `create_pending_session` :

```python
from app.services.audit_log import log_action
# ...
await log_action(
    conn,
    action="remote_backup.gdrive.reauthorized",
    actor_user_id=None,
    metadata={"connection_id": str(connection_id), "connection_name": item.name},
)
```

**Si `log_action` n'existe pas avec cette signature exacte dans le projet** : utiliser le pattern existant (probablement `audit_log_service.write(...)` ou similaire). Inspecter `backend/src/app/services/audit_log*.py` pour adapter, mais ne pas inventer une signature.

- [ ] **Step 4: Lancer (expect PASS)**

Run: `cd backend && uv run pytest tests/test_gdrive_oauth_audit_log.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/app/services/gdrive_oauth_session.py backend/src/app/api/v1/admin_remote_backups.py backend/tests/test_gdrive_oauth_audit_log.py
git commit -m "feat(gdrive-oauth): audit_log entries (started/completed/failed/reauthorized)"
```

### Task G4.9 — Vérification d'intégration backend

**Files:**
- (aucun fichier à modifier)

- [ ] **Step 1: Lancer toute la suite backend pour vérifier qu'aucune régression**

Run: `cd backend && uv run pytest tests/ -v`
Expected: tous passent.

- [ ] **Step 2: Lancer ruff check + format**

Run:
```
cd backend && uv run ruff check src/ tests/
cd backend && uv run ruff format src/ tests/
```
Expected: zéro erreur après le format.

- [ ] **Step 3: Commit (si format a touché quelque chose)**

```bash
git add backend/
git commit -m "style(gdrive): ruff format"
```

---

## LOT G5 — Frontend OAuth + UI wizard

Le LOT G5 livre l'UI utilisable de bout en bout. Les tests Vitest mockent `window.open` et `postMessage` pour valider la mécanique sans navigateur réel.

### Task G5.1 — Types Zod / TypeScript pour gdrive

**Files:**
- Modify: `frontend/src/schemas/admin.ts`

- [ ] **Step 1: Ajouter le test**

```typescript
// frontend/src/schemas/admin.test.ts (ajout ou création)
import { describe, it, expect } from 'vitest';
import { remoteBackupConnectionSchema } from './admin';

describe('remoteBackupConnectionSchema gdrive', () => {
  it('parse une connexion gdrive', () => {
    const result = remoteBackupConnectionSchema.parse({
      id: 'abc-id',
      name: 'My Drive',
      kind: 'gdrive',
      config: {
        client_id: 'cid', redirect_uri: 'u',
        folder_name: 'F', user_email: 'a@b.c',
      },
      has_credentials: true,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });
    expect(result.kind).toBe('gdrive');
  });
});
```

- [ ] **Step 2: Lancer (expect FAIL)**

Run: `cd frontend && npx vitest run src/schemas/admin.test.ts`
Expected: FAIL (kind n'inclut pas gdrive dans le schema).

- [ ] **Step 3: Étendre le schema**

Dans `frontend/src/schemas/admin.ts`, là où le `kind` est typé :

```typescript
export const remoteBackupKindSchema = z.enum(['sftp', 's3', 'ftps', 'gdrive']);
export type RemoteBackupKind = z.infer<typeof remoteBackupKindSchema>;
```

Si le `config` est typé strict, ajouter un cas `gdrive` :
```typescript
export interface GDriveConfig {
  client_id: string;
  redirect_uri: string;
  folder_name: string;
  folder_id?: string;
  user_email?: string;
}
```

- [ ] **Step 4: Lancer (expect PASS)**

Run: `cd frontend && npx vitest run src/schemas/admin.test.ts && npx tsc --noEmit`
Expected: tests PASS + TS strict OK.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/schemas/admin.ts frontend/src/schemas/admin.test.ts
git commit -m "feat(gdrive-ui): schéma Zod kind='gdrive' + types GDriveConfig"
```

### Task G5.2 — Nouvelles fonctions `adminApi.ts`

**Files:**
- Modify: `frontend/src/lib/adminApi.ts`

- [ ] **Step 1: Ajouter les fonctions (sans tests inline — testées via le helper gdriveOAuth)**

Append à `frontend/src/lib/adminApi.ts` :

```typescript
// ── Google Drive OAuth ───────────────────────────────────────────────────

export async function fetchGDriveRedirectUri(): Promise<{ redirect_uri: string }> {
  return apiClient.get('/v1/admin/backup-remotes/oauth/gdrive/redirect-uri');
}

export interface StartGDriveOAuthPayload {
  name: string;
  client_id: string;
  client_secret: string;
  folder_name: string;
}

export async function startGDriveOAuth(
  body: StartGDriveOAuthPayload,
): Promise<{ auth_url: string; state: string }> {
  return apiClient.post('/v1/admin/backup-remotes/oauth/gdrive/start', body);
}

export interface GDriveOAuthSession {
  status: 'pending' | 'authorized' | 'failed' | 'unknown';
  result?: { user_email?: string; error?: string } | null;
}

export async function fetchGDriveOAuthSession(state: string): Promise<GDriveOAuthSession> {
  return apiClient.get(`/v1/admin/backup-remotes/oauth/gdrive/session/${encodeURIComponent(state)}`);
}

export async function reauthorizeGDriveConnection(
  id: string,
): Promise<{ auth_url: string; state: string }> {
  return apiClient.post(`/v1/admin/backup-remotes/${encodeURIComponent(id)}/reauthorize`, {});
}
```

Et étendre `RemoteBackupCreatePayload` pour accepter `oauth_state?: string`.

- [ ] **Step 2: TypeScript strict check**

Run: `cd frontend && npx tsc --noEmit`
Expected: zéro erreur.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/adminApi.ts
git commit -m "feat(gdrive-ui): helpers adminApi (start/session/reauthorize/redirect-uri)"
```

### Task G5.3 — Helper `gdriveOAuth.ts` (popup + postMessage)

**Files:**
- Create: `frontend/src/lib/gdriveOAuth.ts`
- Create: `frontend/src/lib/gdriveOAuth.test.ts`

- [ ] **Step 1: Écrire les tests (expect FAIL)**

```typescript
// frontend/src/lib/gdriveOAuth.test.ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import * as adminApi from './adminApi';

import {
  runGDriveOAuthFlow,
  PopupBlockedError,
  OAuthAbortedError,
  OAuthError,
} from './gdriveOAuth';

const FAKE_PARAMS = {
  client_id: 'cid', client_secret: 'csec',
  folder_name: 'F', name: 'N',
} as const;

function fakePopup(opts: { closed?: boolean } = {}) {
  const p = { closed: false, close: vi.fn() };
  if (opts.closed) p.closed = true;
  return p as unknown as Window;
}

describe('runGDriveOAuthFlow', () => {
  beforeEach(() => {
    vi.spyOn(window, 'addEventListener');
    vi.spyOn(window, 'removeEventListener');
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('happy path : popup ouvre, postMessage reçu, retourne state + email', async () => {
    vi.spyOn(adminApi, 'startGDriveOAuth').mockResolvedValue({
      auth_url: 'https://accounts.google.com/...', state: 'ST',
    });
    vi.spyOn(adminApi, 'fetchGDriveOAuthSession').mockResolvedValue({
      status: 'authorized', result: { user_email: 'ok@x.y' },
    });
    const popup = fakePopup();
    vi.spyOn(window, 'open').mockReturnValue(popup);

    const flow = runGDriveOAuthFlow(FAKE_PARAMS);

    // Simule le postMessage de la popup au parent
    setTimeout(() => {
      window.dispatchEvent(new MessageEvent('message', {
        data: { type: 'gdrive_oauth_done', state: 'ST', ok: true },
        origin: window.location.origin,
      }));
    }, 10);

    await vi.advanceTimersByTimeAsync(20);
    const result = await flow;
    expect(result.state).toBe('ST');
    expect(result.user_email).toBe('ok@x.y');
  });

  it('popup bloquée : throw PopupBlockedError', async () => {
    vi.spyOn(adminApi, 'startGDriveOAuth').mockResolvedValue({
      auth_url: 'x', state: 'ST',
    });
    vi.spyOn(window, 'open').mockReturnValue(null);
    await expect(runGDriveOAuthFlow(FAKE_PARAMS)).rejects.toBeInstanceOf(PopupBlockedError);
  });

  it('postMessage depuis mauvaise origin : ignoré', async () => {
    vi.spyOn(adminApi, 'startGDriveOAuth').mockResolvedValue({ auth_url: 'x', state: 'ST' });
    const popup = fakePopup();
    vi.spyOn(window, 'open').mockReturnValue(popup);

    const flow = runGDriveOAuthFlow(FAKE_PARAMS);
    setTimeout(() => {
      window.dispatchEvent(new MessageEvent('message', {
        data: { type: 'gdrive_oauth_done', state: 'ST', ok: true },
        origin: 'https://evil.example.com',
      }));
      // Puis ferme la popup pour terminer le flow
      (popup as { closed: boolean }).closed = true;
    }, 10);

    await vi.advanceTimersByTimeAsync(2000);
    await expect(flow).rejects.toBeInstanceOf(OAuthAbortedError);
  });

  it('postMessage avec mauvais state : ignoré', async () => {
    vi.spyOn(adminApi, 'startGDriveOAuth').mockResolvedValue({ auth_url: 'x', state: 'ST' });
    const popup = fakePopup();
    vi.spyOn(window, 'open').mockReturnValue(popup);

    const flow = runGDriveOAuthFlow(FAKE_PARAMS);
    setTimeout(() => {
      window.dispatchEvent(new MessageEvent('message', {
        data: { type: 'gdrive_oauth_done', state: 'WRONG', ok: true },
        origin: window.location.origin,
      }));
      (popup as { closed: boolean }).closed = true;
    }, 10);

    await vi.advanceTimersByTimeAsync(2000);
    await expect(flow).rejects.toBeInstanceOf(OAuthAbortedError);
  });

  it('postMessage ok:false : throw OAuthError', async () => {
    vi.spyOn(adminApi, 'startGDriveOAuth').mockResolvedValue({ auth_url: 'x', state: 'ST' });
    const popup = fakePopup();
    vi.spyOn(window, 'open').mockReturnValue(popup);

    const flow = runGDriveOAuthFlow(FAKE_PARAMS);
    setTimeout(() => {
      window.dispatchEvent(new MessageEvent('message', {
        data: { type: 'gdrive_oauth_done', state: 'ST', ok: false, error: 'access_denied' },
        origin: window.location.origin,
      }));
    }, 10);

    await vi.advanceTimersByTimeAsync(20);
    await expect(flow).rejects.toBeInstanceOf(OAuthError);
  });

  it('popup fermée sans message : reject OAuthAbortedError', async () => {
    vi.spyOn(adminApi, 'startGDriveOAuth').mockResolvedValue({ auth_url: 'x', state: 'ST' });
    const popup = fakePopup();
    vi.spyOn(window, 'open').mockReturnValue(popup);

    const flow = runGDriveOAuthFlow(FAKE_PARAMS);
    setTimeout(() => { (popup as { closed: boolean }).closed = true; }, 50);

    await vi.advanceTimersByTimeAsync(2000);
    await expect(flow).rejects.toBeInstanceOf(OAuthAbortedError);
  });
});
```

- [ ] **Step 2: Lancer (expect FAIL)**

Run: `cd frontend && npx vitest run src/lib/gdriveOAuth.test.ts`
Expected: FAIL (module pas créé).

- [ ] **Step 3: Implémenter `gdriveOAuth.ts` (version G5.3 — sans `runGDriveReauthorize`, ajouté en G5.7)**

```typescript
// frontend/src/lib/gdriveOAuth.ts
import {
  startGDriveOAuth,
  fetchGDriveOAuthSession,
  type StartGDriveOAuthPayload,
} from './adminApi';

export class PopupBlockedError extends Error {
  constructor() { super('popup_blocked'); this.name = 'PopupBlockedError'; }
}
export class OAuthAbortedError extends Error {
  constructor() { super('oauth_aborted'); this.name = 'OAuthAbortedError'; }
}
export class OAuthError extends Error {
  constructor(public reason: string) { super(reason); this.name = 'OAuthError'; }
}

interface GDrivePostMessage {
  type: 'gdrive_oauth_done';
  state: string;
  ok: boolean;
  error?: string;
}

const POPUP_FEATURES = 'popup=1,width=520,height=720,resizable=1,scrollbars=1';
const POPUP_POLL_MS = 400;

export async function runGDriveOAuthFlow(
  params: StartGDriveOAuthPayload,
): Promise<{ state: string; user_email: string }> {
  const { auth_url, state } = await startGDriveOAuth(params);
  const popup = window.open(auth_url, 'gdrive_oauth', POPUP_FEATURES);
  if (!popup) throw new PopupBlockedError();

  const message = await waitForOAuthMessage(state, popup);
  if (!message.ok) throw new OAuthError(message.error ?? 'oauth_failed');

  const session = await fetchGDriveOAuthSession(state);
  if (session.status !== 'authorized' || !session.result?.user_email) {
    throw new OAuthError(session.result?.error ?? 'session_not_authorized');
  }
  return { state, user_email: session.result.user_email };
}

function waitForOAuthMessage(
  expectedState: string,
  popup: Window,
): Promise<GDrivePostMessage> {
  return new Promise((resolve, reject) => {
    const listener = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) return;
      const data = event.data as GDrivePostMessage | undefined;
      if (!data || data.type !== 'gdrive_oauth_done') return;
      if (data.state !== expectedState) return;
      cleanup();
      resolve(data);
    };
    const poll = window.setInterval(() => {
      if (popup.closed) { cleanup(); reject(new OAuthAbortedError()); }
    }, POPUP_POLL_MS);
    const cleanup = () => {
      window.removeEventListener('message', listener);
      window.clearInterval(poll);
    };
    window.addEventListener('message', listener);
  });
}
```

- [ ] **Step 4: Lancer (expect PASS)**

Run: `cd frontend && npx vitest run src/lib/gdriveOAuth.test.ts`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/gdriveOAuth.ts frontend/src/lib/gdriveOAuth.test.ts
git commit -m "feat(gdrive-ui): helper gdriveOAuth — popup + postMessage + 3 erreurs typées"
```

### Task G5.4 — i18n FR + EN

**Files:**
- Modify: `frontend/src/i18n/fr.json`
- Modify: `frontend/src/i18n/en.json`

- [ ] **Step 1: Ajouter les clés (pas de test — on couvre via le test de la page en G5.6)**

Dans `fr.json`, sous `admin.remoteBackups` :

```json
"kind": {
  "gdrive": "Google Drive"
},
"gdrive": {
  "step1Title": "Application OAuth Google",
  "step1Desc": "Pour créer cette connexion, créez d'abord une application OAuth dans Google Cloud Console.",
  "fieldClientId": "Client ID",
  "fieldClientSecret": "Client Secret",
  "fieldRedirectUri": "Redirect URI",
  "fieldRedirectUriHint": "À copier-coller dans les Authorized redirect URIs de votre app Google Cloud.",
  "fieldFolderName": "Nom du dossier sur Drive",
  "fieldFolderNamePlaceholder": "Harpocrate Backups",
  "btnAuthorize": "Autoriser avec Google",
  "popupBlocked": "La popup a été bloquée par le navigateur.",
  "openInTab": "Ouvrir dans un onglet",
  "waitingAuth": "Fenêtre Google ouverte — autorisez puis revenez ici.",
  "authorizedAs": "Autorisé en tant que {{email}}",
  "aborted": "Autorisation annulée.",
  "btnRestart": "Recommencer",
  "btnReauthorize": "Ré-autoriser",
  "credentialsRevoked": "Ré-autorisation requise — le token a été révoqué côté Google.",
  "guideLink": "Voir le guide",
  "copyHint": "Copier",
  "copied": "Copié !"
}
```

Et la traduction symétrique en `en.json` :

```json
"kind": {
  "gdrive": "Google Drive"
},
"gdrive": {
  "step1Title": "Google OAuth application",
  "step1Desc": "To create this connection, first create an OAuth application in Google Cloud Console.",
  "fieldClientId": "Client ID",
  "fieldClientSecret": "Client Secret",
  "fieldRedirectUri": "Redirect URI",
  "fieldRedirectUriHint": "Paste this into the Authorized redirect URIs of your Google Cloud app.",
  "fieldFolderName": "Folder name on Drive",
  "fieldFolderNamePlaceholder": "Harpocrate Backups",
  "btnAuthorize": "Authorize with Google",
  "popupBlocked": "Popup was blocked by the browser.",
  "openInTab": "Open in a tab",
  "waitingAuth": "Google window opened — authorize then come back here.",
  "authorizedAs": "Authorized as {{email}}",
  "aborted": "Authorization cancelled.",
  "btnRestart": "Restart",
  "btnReauthorize": "Re-authorize",
  "credentialsRevoked": "Re-authorization required — token was revoked on Google side.",
  "guideLink": "View guide",
  "copyHint": "Copy",
  "copied": "Copied!"
}
```

- [ ] **Step 2: Sanity-check TypeScript (les clés sont juste des strings runtime mais on peut vérifier le JSON parse)**

Run: `cd frontend && node -e "JSON.parse(require('fs').readFileSync('src/i18n/fr.json'))" && node -e "JSON.parse(require('fs').readFileSync('src/i18n/en.json'))"`
Expected: zéro erreur.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(gdrive-ui): clés i18n FR + EN (kind, wizard, erreurs)"
```

### Task G5.5 — Composant `GDriveFields.tsx` (wizard 3 phases)

**Files:**
- Create: `frontend/src/components/GDriveFields.tsx`

- [ ] **Step 1: Implémenter le composant**

```typescript
// frontend/src/components/GDriveFields.tsx
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Alert, Button, Group, PasswordInput, Stack, Text, TextInput, CopyButton,
  ActionIcon, Loader,
} from '@mantine/core';

import { fetchGDriveRedirectUri } from '@/lib/adminApi';
import {
  runGDriveOAuthFlow,
  PopupBlockedError, OAuthAbortedError, OAuthError,
} from '@/lib/gdriveOAuth';

export type GDriveWizardState =
  | { phase: 'idle' }
  | { phase: 'waiting' }
  | { phase: 'authorized'; state: string; user_email: string }
  | { phase: 'error'; message: string };

export interface GDriveFieldsProps {
  name: string;
  onChangeName: (v: string) => void;
  wizard: GDriveWizardState;
  onWizardChange: (s: GDriveWizardState) => void;
  /** Permet au parent de récupérer l'oauth_state final pour le POST de création. */
  onAuthorized: (oauth_state: string) => void;
}

export function GDriveFields({
  name, onChangeName, wizard, onWizardChange, onAuthorized,
}: GDriveFieldsProps) {
  const { t } = useTranslation();
  const [clientId, setClientId] = useState('');
  const [clientSecret, setClientSecret] = useState('');
  const [folderName, setFolderName] = useState('Harpocrate Backups');
  const [redirectUri, setRedirectUri] = useState('');

  useEffect(() => {
    fetchGDriveRedirectUri().then(r => setRedirectUri(r.redirect_uri)).catch(() => {});
  }, []);

  const canAuthorize = useMemo(
    () => name.trim() && clientId.trim() && clientSecret && folderName.trim(),
    [name, clientId, clientSecret, folderName],
  );

  async function handleAuthorize() {
    onWizardChange({ phase: 'waiting' });
    try {
      const result = await runGDriveOAuthFlow({
        name: name.trim(),
        client_id: clientId.trim(),
        client_secret: clientSecret,
        folder_name: folderName.trim(),
      });
      onWizardChange({ phase: 'authorized', state: result.state, user_email: result.user_email });
      onAuthorized(result.state);
    } catch (err) {
      if (err instanceof PopupBlockedError) {
        onWizardChange({ phase: 'error', message: t('admin.remoteBackups.gdrive.popupBlocked') });
      } else if (err instanceof OAuthAbortedError) {
        onWizardChange({ phase: 'error', message: t('admin.remoteBackups.gdrive.aborted') });
      } else if (err instanceof OAuthError) {
        onWizardChange({ phase: 'error', message: err.reason });
      } else {
        onWizardChange({ phase: 'error', message: String(err) });
      }
    }
  }

  if (wizard.phase === 'authorized') {
    return (
      <Stack gap="sm">
        <Alert color="green" variant="light">
          {t('admin.remoteBackups.gdrive.authorizedAs', { email: wizard.user_email })}
        </Alert>
        <Text size="sm" c="dimmed">
          {t('admin.remoteBackups.gdrive.fieldFolderName')} : <code>{folderName}</code>
        </Text>
        <Button variant="subtle" onClick={() => onWizardChange({ phase: 'idle' })}>
          {t('admin.remoteBackups.gdrive.btnRestart')}
        </Button>
      </Stack>
    );
  }

  if (wizard.phase === 'waiting') {
    return (
      <Stack gap="sm">
        <Alert color="blue" variant="light">
          <Group gap="sm"><Loader size="sm" /> {t('admin.remoteBackups.gdrive.waitingAuth')}</Group>
        </Alert>
      </Stack>
    );
  }

  return (
    <Stack gap="sm">
      <Text size="sm">{t('admin.remoteBackups.gdrive.step1Desc')}</Text>
      <TextInput
        label={t('admin.remoteBackups.gdrive.fieldClientId')}
        required value={clientId}
        onChange={(e) => setClientId(e.currentTarget.value)}
      />
      <PasswordInput
        label={t('admin.remoteBackups.gdrive.fieldClientSecret')}
        required value={clientSecret}
        onChange={(e) => setClientSecret(e.currentTarget.value)}
      />
      <Group align="end" gap="xs" wrap="nowrap">
        <TextInput
          label={t('admin.remoteBackups.gdrive.fieldRedirectUri')}
          description={t('admin.remoteBackups.gdrive.fieldRedirectUriHint')}
          value={redirectUri} readOnly style={{ flex: 1 }}
        />
        <CopyButton value={redirectUri}>
          {({ copied, copy }) => (
            <ActionIcon variant="light" onClick={copy} aria-label={t('admin.remoteBackups.gdrive.copyHint')}>
              {copied ? '✓' : '📋'}
            </ActionIcon>
          )}
        </CopyButton>
      </Group>
      <TextInput
        label={t('admin.remoteBackups.gdrive.fieldFolderName')}
        placeholder={t('admin.remoteBackups.gdrive.fieldFolderNamePlaceholder')}
        required value={folderName}
        onChange={(e) => setFolderName(e.currentTarget.value)}
      />
      {wizard.phase === 'error' && (
        <Alert color="red" variant="light">{wizard.message}</Alert>
      )}
      <Button
        onClick={() => void handleAuthorize()}
        disabled={!canAuthorize}
      >
        {t('admin.remoteBackups.gdrive.btnAuthorize')} →
      </Button>
    </Stack>
  );
}
```

- [ ] **Step 2: TypeScript check**

Run: `cd frontend && npx tsc --noEmit`
Expected: zéro erreur.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/GDriveFields.tsx
git commit -m "feat(gdrive-ui): composant GDriveFields (wizard 3 phases dans le modal)"
```

### Task G5.6 — Intégrer dans `AdminRemoteBackupsPage`

**Files:**
- Modify: `frontend/src/pages/AdminRemoteBackupsPage.tsx`

- [ ] **Step 1: Ajouter le test d'intégration**

```typescript
// frontend/src/pages/AdminRemoteBackupsPage.test.tsx (ajout)
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { I18nextProvider } from 'react-i18next';
import { MantineProvider } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';

import { AdminRemoteBackupsPage } from './AdminRemoteBackupsPage';
import * as adminApi from '@/lib/adminApi';
import i18n from '@/i18n';

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MantineProvider>
      <ModalsProvider>
        <I18nextProvider i18n={i18n}>
          <QueryClientProvider client={qc}>
            <AdminRemoteBackupsPage />
          </QueryClientProvider>
        </I18nextProvider>
      </ModalsProvider>
    </MantineProvider>,
  );
}

describe('AdminRemoteBackupsPage gdrive', () => {
  beforeEach(() => {
    vi.spyOn(adminApi, 'fetchRemoteBackupConnections').mockResolvedValue({ connections: [] });
    vi.spyOn(adminApi, 'fetchGDriveRedirectUri').mockResolvedValue({
      redirect_uri: 'https://harpo.example.com/v1/admin/backup-remotes/oauth/gdrive/callback',
    });
  });

  it('sélectionner kind=gdrive affiche GDriveFields', async () => {
    renderPage();
    await userEvent.click(await screen.findByRole('button', { name: /ajouter/i }));
    const kindSelect = await screen.findByLabelText(/type/i);
    await userEvent.click(kindSelect);
    await userEvent.click(await screen.findByText('Google Drive'));
    // Les champs gdrive sont là :
    expect(await screen.findByLabelText(/Client ID/i)).toBeInTheDocument();
    // Les champs SFTP ne sont PAS là (pas de label "Host") :
    expect(screen.queryByLabelText(/^Host$/i)).not.toBeInTheDocument();
  });

  it('bouton Sauvegarder désactivé tant que oauth_state pas obtenu', async () => {
    renderPage();
    await userEvent.click(await screen.findByRole('button', { name: /ajouter/i }));
    const kindSelect = await screen.findByLabelText(/type/i);
    await userEvent.click(kindSelect);
    await userEvent.click(await screen.findByText('Google Drive'));
    await userEvent.type(await screen.findByLabelText(/nom/i), 'My Drive');
    const saveBtn = screen.getByRole('button', { name: /sauvegarder|save|enregistrer/i });
    expect(saveBtn).toBeDisabled();
  });
});
```

(Si le harness du projet diffère sur les providers — i18n, react-query, Mantine — ajuster les wrappers de `renderPage` en s'alignant sur `frontend/src/test/setup.ts` ou un test existant comme `SecretDetailPage.test.tsx`.)

- [ ] **Step 2: Lancer (expect FAIL)**

Run: `cd frontend && npx vitest run src/pages/AdminRemoteBackupsPage.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Modifier `AdminRemoteBackupsPage.tsx`**

Modifications :

1. **Type `Kind`** : `type Kind = 'sftp' | 's3' | 'ftps' | 'gdrive';`
2. **Select kind** : ajouter `{ value: 'gdrive', label: 'Google Drive' }`. **Masquer** la cellule host pour gdrive (et afficher user_email à la place).
3. **`FormValues`** : ajouter un champ optionnel `oauth_state?: string`.
4. **`ConnectionFormModal`** : quand `form.values.kind === 'gdrive'`, afficher `<GDriveFields ... />` au lieu des autres `*Fields`. Le composant met à jour `oauth_state` via `onAuthorized` callback.
5. **`buildPayload`** : pour `kind === 'gdrive'`, envoyer `{name, kind: 'gdrive', config: {}, credentials: {}, oauth_state: values.oauth_state}`.
6. **Bouton "Sauvegarder"** : `disabled` si `kind === 'gdrive' && !oauth_state`.
7. **Cellule `host`** dans la table : pour gdrive, afficher `connection.config.user_email` au lieu de host:port.
8. **`PathsCell`** : pour gdrive, afficher `folder_name` au lieu des paths SFTP/S3.

Snippet du `ConnectionFormModal` :

```typescript
// dans ConnectionFormModal après les autres *Fields
{form.values.kind === 'gdrive' && (
  <GDriveFields
    name={form.values.name}
    onChangeName={(v) => form.setFieldValue('name', v)}
    wizard={gdriveWizard}
    onWizardChange={setGdriveWizard}
    onAuthorized={(state) => form.setFieldValue('oauth_state', state)}
  />
)}
```

Où `gdriveWizard` est `useState<GDriveWizardState>({ phase: 'idle' })` au niveau du composant.

- [ ] **Step 4: Lancer (expect PASS) + TSC**

Run:
```
cd frontend && npx vitest run src/pages/AdminRemoteBackupsPage.test.tsx
cd frontend && npx tsc --noEmit
```
Expected: passed + zéro erreur TS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/AdminRemoteBackupsPage.tsx frontend/src/pages/AdminRemoteBackupsPage.test.tsx
git commit -m "feat(gdrive-ui): intégration GDriveFields dans le modal + cellules table adaptées"
```

### Task G5.7 — Bouton "Re-autoriser" + factorisation runFlow

**Files:**
- Modify: `frontend/src/lib/gdriveOAuth.ts`
- Modify: `frontend/src/pages/AdminRemoteBackupsPage.tsx`

- [ ] **Step 1: Ajouter le test pour reauthorize**

```typescript
// frontend/src/lib/gdriveOAuth.test.ts (ajout)
import { runGDriveReauthorize } from './gdriveOAuth';

describe('runGDriveReauthorize', () => {
  it('appelle reauthorizeGDriveConnection puis utilise le même flow popup', async () => {
    const popup = { closed: false, close: vi.fn() } as unknown as Window;
    vi.spyOn(window, 'open').mockReturnValue(popup);
    vi.spyOn(adminApi, 'reauthorizeGDriveConnection').mockResolvedValue({
      auth_url: 'https://accounts.google/...', state: 'REAUTH-X',
    });
    vi.spyOn(adminApi, 'fetchGDriveOAuthSession').mockResolvedValue({
      status: 'authorized', result: { user_email: 'r@x.y' },
    });
    vi.useFakeTimers();

    const flow = runGDriveReauthorize('conn-id-1');
    setTimeout(() => {
      window.dispatchEvent(new MessageEvent('message', {
        data: { type: 'gdrive_oauth_done', state: 'REAUTH-X', ok: true },
        origin: window.location.origin,
      }));
    }, 10);
    await vi.advanceTimersByTimeAsync(20);
    const result = await flow;
    expect(result.user_email).toBe('r@x.y');
    expect(adminApi.reauthorizeGDriveConnection).toHaveBeenCalledWith('conn-id-1');
  });
});
```

- [ ] **Step 2: Lancer (expect FAIL)**

Run: `cd frontend && npx vitest run src/lib/gdriveOAuth.test.ts -t reauthorize`
Expected: FAIL.

- [ ] **Step 3: Factoriser + ajouter `runGDriveReauthorize`**

Modifier `gdriveOAuth.ts` :

```typescript
// Helper interne factorisé
async function _runFlowFromStart(
  start: { auth_url: string; state: string },
): Promise<{ state: string; user_email: string }> {
  const popup = window.open(start.auth_url, 'gdrive_oauth', POPUP_FEATURES);
  if (!popup) throw new PopupBlockedError();
  const message = await waitForOAuthMessage(start.state, popup);
  if (!message.ok) throw new OAuthError(message.error ?? 'oauth_failed');
  const session = await fetchGDriveOAuthSession(start.state);
  if (session.status !== 'authorized' || !session.result?.user_email) {
    throw new OAuthError(session.result?.error ?? 'session_not_authorized');
  }
  return { state: start.state, user_email: session.result.user_email };
}

export async function runGDriveOAuthFlow(
  params: StartGDriveOAuthPayload,
): Promise<{ state: string; user_email: string }> {
  const start = await startGDriveOAuth(params);
  return _runFlowFromStart(start);
}

export async function runGDriveReauthorize(
  connectionId: string,
): Promise<{ state: string; user_email: string }> {
  const { reauthorizeGDriveConnection } = await import('./adminApi');
  const start = await reauthorizeGDriveConnection(connectionId);
  return _runFlowFromStart(start);
}
```

- [ ] **Step 4: Brancher le bouton "Re-autoriser" dans la table**

Dans `AdminRemoteBackupsPage.tsx`, dans la cellule actions de chaque ligne :

```typescript
{c.kind === 'gdrive' && (
  <Button
    size="xs" variant="subtle"
    onClick={async () => {
      try {
        await runGDriveReauthorize(c.id);
        notifications.show({ color: 'green', message: t('common.success') });
        void qc.invalidateQueries({ queryKey: ['admin-remote-backups'] });
      } catch (err) {
        notifications.show({
          color: 'red', title: t('common.error'),
          message: err instanceof Error ? err.message : String(err),
        });
      }
    }}
  >
    {t('admin.remoteBackups.gdrive.btnReauthorize')}
  </Button>
)}
```

- [ ] **Step 5: Lancer (expect PASS)**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: passed + zéro erreur.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/gdriveOAuth.ts frontend/src/lib/gdriveOAuth.test.ts frontend/src/pages/AdminRemoteBackupsPage.tsx
git commit -m "feat(gdrive-ui): runGDriveReauthorize + bouton Re-autoriser sur lignes gdrive"
```

### Task G5.8 — Lint + format frontend

- [ ] **Step 1: ESLint + Prettier**

Run:
```
cd frontend && npm run lint
cd frontend && npm run format
```
Expected: zéro erreur.

- [ ] **Step 2: Commit (si format a touché quelque chose)**

```bash
git add frontend/
git commit -m "style(gdrive-ui): prettier format"
```

---

## LOT G6 — Documentation utilisateur

### Task G6.1 — Guide `docs/admin/gdrive-setup.md`

**Files:**
- Create: `docs/admin/gdrive-setup.md`

- [ ] **Step 1: Créer le guide**

```markdown
# Configurer une connexion Google Drive pour les backups Harpocrate

Ce guide explique comment créer une application OAuth dans Google Cloud Console,
récupérer un Client ID + Client Secret, et finaliser la connexion côté Harpocrate.
Compter ~10 minutes la première fois.

## 1. Créer un projet Google Cloud (si nécessaire)

1. Ouvrir https://console.cloud.google.com/
2. Cliquer sur le sélecteur de projet en haut → "Nouveau projet"
3. Donner un nom (ex : `harpocrate-backup`) → Créer

## 2. Activer l'API Google Drive

1. Menu hamburger → APIs & Services → Library
2. Chercher "Google Drive API" → Enable

## 3. Configurer l'OAuth consent screen

1. APIs & Services → OAuth consent screen
2. Choisir "External" (sauf si vous êtes en Workspace : "Internal")
3. Remplir les champs obligatoires (nom de l'app, email support, etc.)
4. **Scopes** → ajouter manuellement le scope `https://www.googleapis.com/auth/drive.file`
   (un seul scope, non-sensitive — pas de review Google requise)
5. **Test users** → ajouter votre adresse Google (et celles des autres admins potentiels)
6. Save & continue

## 4. Créer le Client OAuth

1. APIs & Services → Credentials → Create Credentials → OAuth client ID
2. Application type : **Web application**
3. Name : libre (ex : `harpocrate-instance-prod`)
4. **Authorized redirect URIs** → ajouter la valeur affichée dans le formulaire
   Harpocrate (bouton 📋 pour copier). Exemple :
   `https://votre-harpocrate.example.com/v1/admin/backup-remotes/oauth/gdrive/callback`
5. Create
6. Copier le **Client ID** et le **Client Secret** dans le formulaire Harpocrate

## 5. Finaliser dans Harpocrate

1. Page "Connexions distantes" → bouton "Ajouter une connexion"
2. Type : **Google Drive**
3. Remplir : Nom (libre), Client ID, Client Secret, Nom du dossier sur Drive
4. Cliquer **"Autoriser avec Google"** → une popup s'ouvre
5. Choisir le compte Google qui contiendra les backups
6. Accepter les permissions (Harpocrate ne demande que `drive.file` : accès aux
   fichiers qu'il crée lui-même)
7. La popup se ferme automatiquement, le modal affiche "✓ Autorisé en tant que …"
8. Cliquer **"Sauvegarder"**

## Limitations à connaître

- **Mode Testing Google** : le refresh token expire après 7 jours d'inactivité.
  Pour usage durable, passer l'app en "Production" (verification automatique sur
  scope non-sensitive).
- **Mono-compte** : les backups vont dans le Drive du compte qui a autorisé.
  Pour changer de compte, supprimer la connexion et la recréer.
- **Pas de listing depuis Harpocrate** : pour voir/télécharger les backups,
  ouvrir directement Google Drive.

## Que faire si "Re-autorisation requise" s'affiche ?

Le refresh token a été révoqué côté Google (Account → Security → Third-party
apps → vous avez retiré Harpocrate, OU délai d'inactivité atteint en mode
Testing). Cliquer sur "Re-autoriser" à côté de la connexion concernée — le
même flow OAuth est relancé sans avoir à re-saisir Client ID/Secret.
```

- [ ] **Step 2: Commit**

```bash
git add docs/admin/gdrive-setup.md
git commit -m "docs(gdrive): guide admin — créer une app OAuth Google + finaliser"
```

---

## Vérification finale

### Task FINAL — Suite complète + manuel end-to-end

- [ ] **Step 1: Backend full suite**

Run: `cd backend && uv run pytest tests/ -v && uv run ruff check src/ tests/`
Expected: tous PASS + zéro lint.

- [ ] **Step 2: Frontend full suite**

Run: `cd frontend && npm test -- --run && npx tsc --noEmit && npm run lint`
Expected: tous PASS + zéro erreur.

- [ ] **Step 3: Smoke test manuel — bout en bout**

Sur l'instance dev (LXC 201) :
1. Pull la branche, rebuild via `./dev-deploy.sh`
2. Ouvrir l'UI → page Connexions distantes → "Ajouter une connexion"
3. Type = Google Drive → suivre le guide ci-dessus
4. Vérifier qu'après autorisation, la connexion apparaît dans la table avec
   `user_email` affiché et `folder_name` dans la colonne paths
5. Cliquer "Tester" → vérifie la création du dossier sur Drive
6. Cliquer "Re-autoriser" → vérifie qu'un nouveau flow popup s'ouvre

- [ ] **Step 4: Commit éventuel de fixs**

Si des fixs sont nécessaires après smoke test, créer des tasks supplémentaires
selon les patterns ci-dessus (rouge → vert → commit).

---

## Annexe — Conventions de commit utilisées

- `feat(gdrive-db):` — schéma DB (migrations, repository)
- `feat(gdrive):` — provider Python + factory + dépendances
- `feat(gdrive-oauth):` — service + endpoints OAuth backend
- `feat(gdrive-ui):` — UI frontend (composants, helpers, i18n)
- `docs(gdrive):` — documentation utilisateur
- `chore(gdrive):` — modifications mineures (deps, format)
- `style(gdrive-ui):` — prettier/ruff format-only

---

**Fin du plan.**
