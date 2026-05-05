# P1.5 — Types obligatoires + API key access + Block deprecated

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (1) Garantir qu'un secret stocké a TOUJOURS un type (résolution automatique vers le type système RAW si non fourni). (2) Empêcher tout secret d'être créé/migré/assigné sur un type qui a été deprecated. (3) Ouvrir les endpoints publics `/v1/secret-types/*` à l'auth API key (en plus de JWT) pour que les clients SDK puissent les consommer sans restriction.

**Architecture:** Validation côté service (pas Pydantic) parce que la résolution RAW nécessite une requête SQL. Nouveau dep FastAPI `require_any_auth_no_scope` factorise le pattern « JWT OU API key, sans wallet/permission » pour les endpoints system-wide. Aucun breaking change pour les clients existants : un POST sans `type_uuid` continue de marcher (RAW assigné automatiquement) et un GET `/v1/secret-types/*` continue de marcher en JWT.

**Tech Stack:** FastAPI + Pydantic v2 + asyncpg + pytest + httpx (ASGITransport).

---

## File Structure

| Fichier | Modification |
|---|---|
| `backend/app/db/repositories/secret_types.py` | Ajout `get_raw_type_with_current_version_uuid()` |
| `backend/app/services/secrets.py` | Modif `create_secret` : résout RAW si `type_uuid is None`, rejette si type fourni est deprecated |
| `backend/app/api/v1/secrets.py` | Modif `migrate_schema` et `assign_type` : rejet 400 si type cible deprecated |
| `backend/app/core/api_key_auth.py` | Ajout `require_any_auth_no_scope()` (auth mixte sans wallet ni permission) |
| `backend/app/api/v1/admin_secret_types.py` | `public_router` passe de `JwtUser` à la nouvelle dep mixte |
| `backend/tests/test_secrets.py` | (NE PAS toucher — pré-existant cassé pour autre raison) |
| `backend/tests/test_secrets_default_raw_type.py` *(nouveau)* | Tests POST sans `type_uuid` → RAW auto + POST avec type deprecated → 400 |
| `backend/tests/test_secret_types_api_key_access.py` *(nouveau)* | Tests GET types via API key (list + detail) |
| `backend/tests/test_secret_types_deprecated_block.py` *(nouveau)* | Tests migrate-schema/assign-type rejetés sur type deprecated |
| `backend/tests/test_any_auth_no_scope.py` *(nouveau)* | Tests unitaires de la nouvelle dep |

---

## Task 1: Helper SQL pour récupérer le type RAW

**Files:**
- Modify: `backend/app/db/repositories/secret_types.py` (ajout d'une fonction)

- [ ] **Step 1.1: Ajouter la fonction `get_raw_type_with_current_version_uuid`**

Dans `backend/app/db/repositories/secret_types.py`, ajouter à la fin du fichier :

```python
async def get_raw_type_with_current_version_uuid(
    conn: asyncpg.Connection,
) -> tuple[UUID, UUID] | None:
    """Retourne (type_uuid, current_version_uuid) du type système RAW.

    Le type RAW est seedé au démarrage via app.services.seed_types depuis
    backend/types/raw/. None si pas encore seedé (cas de boot très précoce).
    """
    row = await conn.fetchrow(
        """SELECT type_uuid, current_version_uuid
           FROM secret_types
           WHERE type = 'raw' AND sous_type = 'raw' AND is_system = TRUE
           LIMIT 1"""
    )
    if row is None or row["current_version_uuid"] is None:
        return None
    return row["type_uuid"], row["current_version_uuid"]
```

- [ ] **Step 1.2: Vérifier l'import**

Run :
```bash
cd /e/srcs/harpocrate/backend && uv run python -c "from app.db.repositories.secret_types import get_raw_type_with_current_version_uuid; print('OK')"
```
Expected : `OK`.

- [ ] **Step 1.3: Commit**

```bash
git add backend/app/db/repositories/secret_types.py
git commit -m "feat(secret_types): helper get_raw_type_with_current_version_uuid"
```

---

## Task 2: Auto-default RAW dans `create_secret` + rejet type deprecated

**Files:**
- Modify: `backend/app/services/secrets.py` (modif de `create_secret`)
- Test: `backend/tests/test_secrets_default_raw_type.py` (nouveau)

- [ ] **Step 2.1: Écrire les tests rouges**

Créer `backend/tests/test_secrets_default_raw_type.py` :

```python
"""Tests P1.5 — Auto-résolution du type RAW + rejet des types deprecated à la création."""
from __future__ import annotations

import base64
import datetime
import uuid
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from tests._helpers import (
    TEST_AUDIENCE,
    TEST_KID,
    TEST_PUBLIC_JWK,
    make_jwt_token,
)

_NOW = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.UTC)
_CALLER_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_WALLET_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")
_SECRET_ID = uuid.UUID("dddddddd-0000-0000-0000-000000000001")
_RAW_TYPE_UUID = uuid.UUID("eeeeeeee-0000-0000-0000-000000000001")
_RAW_VERSION_UUID = uuid.UUID("ffffffff-0000-0000-0000-000000000001")
_DEPRECATED_TYPE_UUID = uuid.UUID("eeeeeeee-0000-0000-0000-000000000099")
_DEPRECATED_VERSION_UUID = uuid.UUID("ffffffff-0000-0000-0000-000000000099")
_FAKE_ENC_VALUE = base64.b64encode(b"fake_encrypted_secret_value").decode()


class FakeRecord(dict[str, Any]):
    def __getitem__(self, key: str) -> Any:
        return super().__getitem__(key)


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://keycloak.yoops.org")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", TEST_AUDIENCE)
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://vault.yoops.org")

    import app.core.security
    _sec = app.core.security.__dict__["settings"]
    monkeypatch.setattr(_sec, "keycloak_url", "https://keycloak.yoops.org")
    monkeypatch.setattr(_sec, "keycloak_realm", "yoops")
    monkeypatch.setattr(_sec, "keycloak_client_id", TEST_AUDIENCE)


@pytest.fixture(autouse=True)
def patch_jwks() -> Generator[None, None, None]:
    from app.core import jwks_cache
    keys_backup = dict(jwks_cache._keys)
    jwks_cache._keys.clear()
    jwks_cache._keys[TEST_KID] = TEST_PUBLIC_JWK
    yield
    jwks_cache._keys.clear()
    jwks_cache._keys.update(keys_backup)


def _fake_user_row() -> FakeRecord:
    return FakeRecord({
        "id": _CALLER_ID, "keycloak_sub": "test-sub-001", "email": "alice@example.com",
        "display_name": "Alice", "rsa_public_key": b"x", "salt_passphrase": b"x" * 16,
        "salt_recovery": b"y" * 16, "encrypted_rsa_private_key": b"x",
        "encrypted_sym_key_by_pass": b"x", "encrypted_sym_key_by_recovery": b"x",
        "kdf_memory_kb": 65536, "kdf_iterations": 3, "kdf_parallelism": 4,
        "rsa_key_size": 2048, "created_at": _NOW, "updated_at": _NOW,
        "last_unlock_at": None,
    })


def _fake_wallet_row(permissions: int = 63) -> FakeRecord:
    return FakeRecord({
        "id": _WALLET_ID, "name": "Test Wallet", "description": None,
        "owner_user_id": _CALLER_ID, "created_at": _NOW, "updated_at": _NOW,
        "my_permissions": permissions, "valued_secrets_count": 0,
        "placeholder_secrets_count": 0, "deleted_at": None,
    })


def _fake_raw_type_row() -> FakeRecord:
    return FakeRecord({
        "type_uuid": _RAW_TYPE_UUID,
        "current_version_uuid": _RAW_VERSION_UUID,
    })


def _fake_deprecated_type_row() -> FakeRecord:
    return FakeRecord({
        "type_uuid": _DEPRECATED_TYPE_UUID,
        "current_version_uuid": _DEPRECATED_VERSION_UUID,
        "type": "old", "sous_type": "old", "label": None, "description": None,
        "is_system": False, "created_by_user_id": None,
        "created_at": _NOW, "updated_at": _NOW,
        "deprecated_at": _NOW,  # ← deprecated
        "cv_version": 1, "cv_schema_data": "{}", "cv_schema_ui": "{}",
        "cv_created_at": _NOW, "used_count": 0,
    })


def _fake_active_type_row() -> FakeRecord:
    return FakeRecord({
        "type_uuid": _RAW_TYPE_UUID,
        "current_version_uuid": _RAW_VERSION_UUID,
        "type": "raw", "sous_type": "raw", "label": "Raw", "description": None,
        "is_system": True, "created_by_user_id": None,
        "created_at": _NOW, "updated_at": _NOW,
        "deprecated_at": None,
        "cv_version": 1, "cv_schema_data": "{}", "cv_schema_ui": "{}",
        "cv_created_at": _NOW, "used_count": 0,
    })


class _FakeTxCtx:
    async def __aenter__(self) -> _FakeTxCtx: return self
    async def __aexit__(self, *args: Any) -> None: pass


def _make_conn() -> MagicMock:
    conn: MagicMock = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock(return_value=None)
    conn.executemany = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=_FakeTxCtx())
    return conn


def _make_pool(conn: MagicMock) -> MagicMock:
    class _AcquireCtx:
        async def __aenter__(self) -> MagicMock: return conn
        async def __aexit__(self, *args: Any) -> None: pass
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_AcquireCtx())
    return pool


def _make_client(pool: MagicMock) -> AsyncClient:
    from app.db import pool as pool_mod
    from app.main import app
    pool_mod._pool = pool
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _auth_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_jwt_token()}"}


# ─── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_secret_without_type_uuid_defaults_to_raw() -> None:
    """POST sans type_uuid → secret créé avec type_uuid = RAW.type_uuid + RAW current version."""
    conn = _make_conn()
    insert_args: list[Any] = []
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row()
        if "secret_types" in query and "raw" in query:
            return _fake_raw_type_row()
        return None

    async def fetchval_side(query: str, *args: Any) -> Any:
        if "INSERT INTO secrets" in query:
            insert_args.append(args)
            return _SECRET_ID
        return None

    conn.fetchrow = fetchrow_side
    conn.fetchval = fetchval_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/wallets/{_WALLET_ID}/secrets",
            json={"name": "MY_KEY", "encrypted_value": _FAKE_ENC_VALUE},
            headers=_auth_header(),
        )

    assert r.status_code == 201, r.text
    # Vérifier que l'INSERT a bien reçu RAW type_uuid + RAW version_uuid
    assert insert_args, "INSERT INTO secrets jamais appelé"
    args = insert_args[0]
    # Signature: wallet_id, name, description, encrypted_value, created_by_user_id, type_uuid, schema_version_uuid
    assert args[5] == _RAW_TYPE_UUID, f"type_uuid attendu RAW, reçu {args[5]}"
    assert args[6] == _RAW_VERSION_UUID, f"schema_version_uuid attendu RAW v1, reçu {args[6]}"


@pytest.mark.asyncio
async def test_post_secret_with_deprecated_type_uuid_returns_400() -> None:
    """POST avec un type_uuid deprecated → 400 invalid_type."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row()
        # 3e fetchrow : get_type sur le type deprecated
        if "secret_types" in query and "type_uuid" in query:
            return _fake_deprecated_type_row()
        return None

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/wallets/{_WALLET_ID}/secrets",
            json={
                "name": "MY_KEY",
                "encrypted_value": _FAKE_ENC_VALUE,
                "type_uuid": str(_DEPRECATED_TYPE_UUID),
                "schema_version_uuid": str(_DEPRECATED_VERSION_UUID),
            },
            headers=_auth_header(),
        )

    assert r.status_code == 400, r.text
    body = r.json()
    assert body["detail"]["error"] == "deprecated_type"


@pytest.mark.asyncio
async def test_post_secret_with_active_type_uuid_succeeds() -> None:
    """POST avec un type_uuid actif (non-deprecated) → 201."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row()
        if "secret_types" in query and "type_uuid" in query:
            return _fake_active_type_row()
        return None

    conn.fetchrow = fetchrow_side
    conn.fetchval = AsyncMock(return_value=_SECRET_ID)
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/wallets/{_WALLET_ID}/secrets",
            json={
                "name": "MY_KEY",
                "encrypted_value": _FAKE_ENC_VALUE,
                "type_uuid": str(_RAW_TYPE_UUID),
                "schema_version_uuid": str(_RAW_VERSION_UUID),
            },
            headers=_auth_header(),
        )

    assert r.status_code == 201, r.text
```

- [ ] **Step 2.2: Lancer les tests → DOIVENT échouer**

Run :
```bash
cd /e/srcs/harpocrate/backend && uv run pytest tests/test_secrets_default_raw_type.py -v
```
Expected : 3 tests FAIL — actuellement le code n'auto-résout pas RAW et ne valide pas deprecated.

- [ ] **Step 2.3: Modifier `create_secret` dans `services/secrets.py`**

Dans `backend/app/services/secrets.py`, fonction `create_secret` (lignes ~183-231), remplacer le corps par :

```python
async def create_secret(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    req: SecretCreateRequest,
    caller_user_id: UUID,
    actor_ip: str | None,
) -> SecretCreateResponse:
    """Crée un secret. Accès vérifié par la couche auth."""
    try:
        enc_value = base64.b64decode(req.encrypted_value)
    except Exception as exc:  # pragma: no cover — validé par Pydantic
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_base64", "message": "encrypted_value is not valid base64"},
        ) from exc

    # ─── P1.5 : résolution du type ────────────────────────────────────────────
    type_uuid = req.type_uuid
    schema_version_uuid = req.schema_version_uuid

    if type_uuid is None:
        # Pas de type fourni → on attache automatiquement RAW
        from app.db.repositories import secret_types as types_repo
        raw = await types_repo.get_raw_type_with_current_version_uuid(conn)
        if raw is None:  # pragma: no cover — RAW est seedé au boot
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": "raw_type_unavailable", "message": "System type RAW not seeded"},
            )
        type_uuid, schema_version_uuid = raw
    else:
        # Type fourni explicitement → vérifier qu'il n'est pas deprecated
        from app.db.repositories import secret_types as types_repo
        type_row = await types_repo.get_type(conn, type_uuid)
        if type_row is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "type_not_found", "message": f"Type {type_uuid} does not exist"},
            )
        if type_row["deprecated_at"] is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "deprecated_type",
                    "message": f"Type {type_uuid} is deprecated and cannot be used for new secrets",
                },
            )

    try:
        async with conn.transaction():
            secret_id = await secrets_repo.insert_secret(
                conn,
                wallet_id=wallet_id,
                name=req.name,
                description=req.description,
                encrypted_value=enc_value,
                tags=req.tags,
                created_by_user_id=caller_user_id,
                type_uuid=type_uuid,
                schema_version_uuid=schema_version_uuid,
            )
            await audit_log_insert(
                conn,
                "secret.created",
                actor_user_id=caller_user_id,
                actor_ip=actor_ip,
                target_wallet_id=wallet_id,
                target_secret_id=secret_id,
                metadata={"secret_name": req.name, "type_uuid": str(type_uuid)},
            )
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "secret_name_exists",
                "message": f"A secret named '{req.name}' already exists in this wallet.",
            },
        ) from exc

    return SecretCreateResponse(secret_id=secret_id)
```

- [ ] **Step 2.4: Tests doivent passer**

Run :
```bash
cd /e/srcs/harpocrate/backend && uv run pytest tests/test_secrets_default_raw_type.py -v
```
Expected : 3 tests PASS.

- [ ] **Step 2.5: Vérifier non-régression sur les anciens tests par-id**

```bash
cd /e/srcs/harpocrate/backend && uv run pytest tests/test_secrets_by_id.py tests/test_invalid_secret_path_handler.py tests/test_secret_paths.py -v 2>&1 | tail -10
```
Expected : tous PASS (pas de régression).

- [ ] **Step 2.6: Commit**

```bash
git add backend/app/services/secrets.py backend/tests/test_secrets_default_raw_type.py
git commit -m "feat(secrets): auto-default RAW + rejet types deprecated à la création"
```

---

## Task 3: Bloquer type deprecated dans `migrate_schema`

**Files:**
- Modify: `backend/app/api/v1/secrets.py` (fonction `migrate_schema`)
- Test: `backend/tests/test_secret_types_deprecated_block.py` (nouveau)

- [ ] **Step 3.1: Écrire le test rouge**

Créer `backend/tests/test_secret_types_deprecated_block.py` :

```python
"""Tests P1.5 — Rejet 400 sur migrate-schema/assign-type vers un type deprecated."""
from __future__ import annotations

import base64
import datetime
import uuid
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from tests._helpers import (
    TEST_AUDIENCE,
    TEST_KID,
    TEST_PUBLIC_JWK,
    make_jwt_token,
)

_NOW = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.UTC)
_CALLER_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_WALLET_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")
_SECRET_ID = uuid.UUID("dddddddd-0000-0000-0000-000000000001")
_TYPE_UUID = uuid.UUID("eeeeeeee-0000-0000-0000-000000000001")
_DEPRECATED_TYPE_UUID = uuid.UUID("eeeeeeee-0000-0000-0000-000000000099")
_TARGET_VERSION_UUID = uuid.UUID("ffffffff-0000-0000-0000-000000000099")
_FAKE_ENC = base64.b64encode(b"new").decode()


class FakeRecord(dict[str, Any]):
    def __getitem__(self, key: str) -> Any:
        return super().__getitem__(key)


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://keycloak.yoops.org")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", TEST_AUDIENCE)
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://vault.yoops.org")

    import app.core.security
    _sec = app.core.security.__dict__["settings"]
    monkeypatch.setattr(_sec, "keycloak_url", "https://keycloak.yoops.org")
    monkeypatch.setattr(_sec, "keycloak_realm", "yoops")
    monkeypatch.setattr(_sec, "keycloak_client_id", TEST_AUDIENCE)


@pytest.fixture(autouse=True)
def patch_jwks() -> Generator[None, None, None]:
    from app.core import jwks_cache
    keys_backup = dict(jwks_cache._keys)
    jwks_cache._keys.clear()
    jwks_cache._keys[TEST_KID] = TEST_PUBLIC_JWK
    yield
    jwks_cache._keys.clear()
    jwks_cache._keys.update(keys_backup)


def _user_row() -> FakeRecord:
    return FakeRecord({
        "id": _CALLER_ID, "keycloak_sub": "test-sub-001", "email": "alice@example.com",
        "display_name": "Alice", "rsa_public_key": b"x", "salt_passphrase": b"x" * 16,
        "salt_recovery": b"y" * 16, "encrypted_rsa_private_key": b"x",
        "encrypted_sym_key_by_pass": b"x", "encrypted_sym_key_by_recovery": b"x",
        "kdf_memory_kb": 65536, "kdf_iterations": 3, "kdf_parallelism": 4,
        "rsa_key_size": 2048, "created_at": _NOW, "updated_at": _NOW,
        "last_unlock_at": None,
    })


def _wallet_row() -> FakeRecord:
    return FakeRecord({
        "id": _WALLET_ID, "name": "W", "description": None,
        "owner_user_id": _CALLER_ID, "created_at": _NOW, "updated_at": _NOW,
        "my_permissions": 63, "valued_secrets_count": 0,
        "placeholder_secrets_count": 0, "deleted_at": None,
    })


def _secret_row(type_uuid: uuid.UUID = _TYPE_UUID) -> FakeRecord:
    return FakeRecord({
        "id": _SECRET_ID, "wallet_id": _WALLET_ID, "name": "MY",
        "description": None, "encrypted_value": b"old",
        "is_placeholder": False, "generation_version": 1,
        "generation_descriptor": None, "linked_secret_id": None,
        "created_at": _NOW, "updated_at": _NOW,
        "created_by_user_id": _CALLER_ID, "created_by_api_key_id": None,
        "updated_by_user_id": None, "updated_by_api_key_id": None,
        "type_uuid": type_uuid, "schema_version_uuid": None,
    })


def _deprecated_type_row() -> FakeRecord:
    return FakeRecord({
        "type_uuid": _DEPRECATED_TYPE_UUID,
        "current_version_uuid": _TARGET_VERSION_UUID,
        "type": "old", "sous_type": "old", "label": None, "description": None,
        "is_system": False, "created_by_user_id": None,
        "created_at": _NOW, "updated_at": _NOW,
        "deprecated_at": _NOW,
        "cv_version": 1, "cv_schema_data": "{}", "cv_schema_ui": "{}",
        "cv_created_at": _NOW, "used_count": 0,
    })


class _Tx:
    async def __aenter__(self) -> _Tx: return self
    async def __aexit__(self, *a: Any) -> None: pass


def _conn() -> MagicMock:
    c: MagicMock = MagicMock()
    c.fetchrow = AsyncMock(return_value=None)
    c.fetchval = AsyncMock(return_value=None)
    c.fetch = AsyncMock(return_value=[])
    c.execute = AsyncMock(return_value=None)
    c.executemany = AsyncMock(return_value=None)
    c.transaction = MagicMock(return_value=_Tx())
    return c


def _pool(conn: MagicMock) -> MagicMock:
    class _A:
        async def __aenter__(self) -> MagicMock: return conn
        async def __aexit__(self, *a: Any) -> None: pass
    p = MagicMock()
    p.acquire = MagicMock(return_value=_A())
    return p


def _client(pool: MagicMock) -> AsyncClient:
    from app.db import pool as pm
    from app.main import app
    pm._pool = pool
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _hdr() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_jwt_token()}"}


@pytest.mark.asyncio
async def test_migrate_schema_to_deprecated_type_returns_400() -> None:
    """PATCH /migrate-schema vers une version d'un type deprecated → 400."""
    conn = _conn()
    call_n = 0

    async def fr(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _user_row()
        if call_n == 2:
            return _wallet_row()
        if "secret_schemas" in query and "version_uuid" in query and "parent_uuid" in query:
            # check du parent_uuid (dans migrate_schema existant)
            return FakeRecord({"parent_uuid": _DEPRECATED_TYPE_UUID})
        if "secret_types" in query and "type_uuid" in query:
            # nouveau check : on charge le type pour vérifier deprecated_at
            return _deprecated_type_row()
        if "secrets" in query.lower() and "wallet_id" in query and "name" in query:
            return _secret_row(type_uuid=_DEPRECATED_TYPE_UUID)
        return None

    conn.fetchrow = fr
    conn.fetch = AsyncMock(return_value=[])

    async with _client(_pool(conn)) as cli:
        r = await cli.patch(
            f"/v1/wallets/{_WALLET_ID}/secrets/MY/migrate-schema",
            json={"encrypted_value": _FAKE_ENC, "target_schema_version_uuid": str(_TARGET_VERSION_UUID)},
            headers=_hdr(),
        )

    assert r.status_code == 400, r.text
    assert r.json()["detail"]["error"] == "deprecated_type"


@pytest.mark.asyncio
async def test_assign_type_to_deprecated_type_returns_400() -> None:
    """PATCH /assign-type avec un type deprecated → 400."""
    conn = _conn()
    call_n = 0

    async def fr(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _user_row()
        if call_n == 2:
            return _wallet_row()
        if "secret_schemas" in query and "version_uuid" in query and "parent_uuid" in query:
            return FakeRecord({"parent_uuid": _DEPRECATED_TYPE_UUID})
        if "secret_types" in query and "type_uuid" in query:
            return _deprecated_type_row()
        if "secrets" in query.lower() and "wallet_id" in query and "name" in query:
            return _secret_row(type_uuid=_TYPE_UUID)
        return None

    conn.fetchrow = fr
    conn.fetch = AsyncMock(return_value=[])

    async with _client(_pool(conn)) as cli:
        r = await cli.patch(
            f"/v1/wallets/{_WALLET_ID}/secrets/MY/assign-type",
            json={
                "type_uuid": str(_DEPRECATED_TYPE_UUID),
                "schema_version_uuid": str(_TARGET_VERSION_UUID),
                "encrypted_value": _FAKE_ENC,
            },
            headers=_hdr(),
        )

    assert r.status_code == 400, r.text
    assert r.json()["detail"]["error"] == "deprecated_type"
```

- [ ] **Step 3.2: Lancer les tests → DOIVENT échouer**

Run :
```bash
cd /e/srcs/harpocrate/backend && uv run pytest tests/test_secret_types_deprecated_block.py -v
```
Expected : 2 tests FAIL.

- [ ] **Step 3.3: Ajouter le check deprecated dans `migrate_schema` et `assign_type`**

Dans `backend/app/api/v1/secrets.py`, fonction `migrate_schema` (vers ligne 393), juste après le check `target_row is None or target_row["parent_uuid"] != secret.type_uuid`, ajouter une vérification du type cible :

```python
        # P1.5 : refuser de migrer vers une version d'un type deprecated
        from app.db.repositories import secret_types as types_repo
        target_type = await types_repo.get_type(conn, secret.type_uuid)
        if target_type is not None and target_type["deprecated_at"] is not None:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "deprecated_type",
                    "message": "Cannot migrate to a version of a deprecated type",
                },
            )
```

Et dans `assign_type` (vers ligne 464), juste après le check `schema_row is None or schema_row["parent_uuid"] != req.type_uuid`, ajouter :

```python
        # P1.5 : refuser d'assigner un type deprecated
        from app.db.repositories import secret_types as types_repo
        target_type = await types_repo.get_type(conn, req.type_uuid)
        if target_type is not None and target_type["deprecated_at"] is not None:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "deprecated_type",
                    "message": "Cannot assign a deprecated type to a secret",
                },
            )
```

- [ ] **Step 3.4: Tests doivent passer**

```bash
cd /e/srcs/harpocrate/backend && uv run pytest tests/test_secret_types_deprecated_block.py -v
```
Expected : 2 tests PASS.

- [ ] **Step 3.5: Commit**

```bash
git add backend/app/api/v1/secrets.py backend/tests/test_secret_types_deprecated_block.py
git commit -m "feat(secret_types): bloque migrate-schema et assign-type vers types deprecated"
```

---

## Task 4: Nouvelle dep FastAPI `require_any_auth_no_scope`

**Files:**
- Modify: `backend/app/core/api_key_auth.py` (ajout d'une dep)
- Test: `backend/tests/test_any_auth_no_scope.py` (nouveau)

- [ ] **Step 4.1: Écrire les tests rouges**

Créer `backend/tests/test_any_auth_no_scope.py` :

```python
"""Tests unitaires P1.5 — require_any_auth_no_scope (auth sans wallet ni permission)."""
from __future__ import annotations

import base64
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests._helpers import (
    TEST_AUDIENCE,
    TEST_KID,
    TEST_PUBLIC_JWK,
    make_jwt_token,
)


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://keycloak.yoops.org")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", TEST_AUDIENCE)
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://vault.yoops.org")

    import app.core.security
    _sec = app.core.security.__dict__["settings"]
    monkeypatch.setattr(_sec, "keycloak_url", "https://keycloak.yoops.org")
    monkeypatch.setattr(_sec, "keycloak_realm", "yoops")
    monkeypatch.setattr(_sec, "keycloak_client_id", TEST_AUDIENCE)


@pytest.fixture(autouse=True)
def patch_jwks() -> Generator[None, None, None]:
    from app.core import jwks_cache
    keys_backup = dict(jwks_cache._keys)
    jwks_cache._keys.clear()
    jwks_cache._keys[TEST_KID] = TEST_PUBLIC_JWK
    yield
    jwks_cache._keys.clear()
    jwks_cache._keys.update(keys_backup)


def _build_test_app() -> FastAPI:
    """Mini-app avec une route protégée par require_any_auth_no_scope."""
    from fastapi import Depends
    from app.core.api_key_auth import require_any_auth_no_scope

    app = FastAPI()

    @app.get("/test-protected")
    async def protected(_auth: Any = Depends(require_any_auth_no_scope)) -> dict[str, str]:
        return {"ok": "yes"}

    return app


def test_no_scope_no_token_returns_401() -> None:
    app = _build_test_app()
    client = TestClient(app)
    r = client.get("/test-protected")
    assert r.status_code == 401


def test_no_scope_with_invalid_token_returns_401() -> None:
    app = _build_test_app()
    client = TestClient(app)
    r = client.get("/test-protected", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


def test_no_scope_with_valid_jwt_returns_200() -> None:
    app = _build_test_app()
    client = TestClient(app)
    r = client.get(
        "/test-protected",
        headers={"Authorization": f"Bearer {make_jwt_token()}"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": "yes"}
```

- [ ] **Step 4.2: Lancer les tests → DOIVENT échouer**

```bash
cd /e/srcs/harpocrate/backend && uv run pytest tests/test_any_auth_no_scope.py -v
```
Expected : `ImportError` parce que `require_any_auth_no_scope` n'existe pas encore.

- [ ] **Step 4.3: Ajouter `require_any_auth_no_scope` dans `api_key_auth.py`**

Dans `backend/app/core/api_key_auth.py`, à la fin du fichier, ajouter :

```python
async def require_any_auth_no_scope(
    authorization: Annotated[str | None, Header()] = None,
    pool: asyncpg.Pool = Depends(get_pool),
) -> AuthContext:
    """Auth mixte JWT/API key sans wallet ni permission requise.

    Pour les endpoints system-wide (catalogue de types, doc OpenAPI, etc.)
    qui ne sont scopés à aucun wallet et qui doivent être consommables aussi
    bien depuis le frontend (JWT) que depuis un client SDK (API key).
    """
    from app.core.security import _validate_jwt
    from app.db.repositories import users as users_repo

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "missing_bearer_token", "message": "Authorization header required"},
        )

    token = authorization[7:]

    if token.startswith("hrpv_"):
        api_key_caller = await validate_api_key_token(token, pool=pool)
        return AuthContext(
            user_db_id=None,
            api_key=api_key_caller,
            my_permissions=api_key_caller.permissions,
        )

    # JWT path
    claims = _validate_jwt(token)
    async with pool.acquire() as conn:
        user_row = await users_repo.get_by_keycloak_sub(conn, claims["sub"])
        if user_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "first_login", "message": "User not bootstrapped"},
            )
        return AuthContext(
            user_db_id=user_row["id"],
            api_key=None,
            my_permissions=0,
        )
```

- [ ] **Step 4.4: Tests doivent passer**

```bash
cd /e/srcs/harpocrate/backend && uv run pytest tests/test_any_auth_no_scope.py -v
```
Expected : 3 PASS (le test JWT peut requérir aussi un mock de `users_repo.get_by_keycloak_sub` — si fail, ajouter un patch dans la fixture).

Si le test JWT échoue avec un 404 first_login, il faut mocker `users_repo.get_by_keycloak_sub`. Adapter le test JWT comme ceci :

```python
def test_no_scope_with_valid_jwt_returns_200(monkeypatch: pytest.MonkeyPatch) -> None:
    import uuid
    from app.db.repositories import users as users_repo

    async def _fake_get_by_sub(conn: Any, sub: str) -> dict[str, Any]:
        return {"id": uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001"), "keycloak_sub": sub}

    monkeypatch.setattr(users_repo, "get_by_keycloak_sub", _fake_get_by_sub)

    # Mock pool aussi
    from app.db import pool as pool_mod

    class _FakeConn:
        pass
    class _FakeCtx:
        async def __aenter__(self): return _FakeConn()
        async def __aexit__(self, *a): pass
    class _FakePool:
        def acquire(self): return _FakeCtx()

    pool_mod._pool = _FakePool()  # type: ignore[assignment]

    app = _build_test_app()
    client = TestClient(app)
    r = client.get(
        "/test-protected",
        headers={"Authorization": f"Bearer {make_jwt_token()}"},
    )
    assert r.status_code == 200, r.text
```

- [ ] **Step 4.5: Commit**

```bash
git add backend/app/core/api_key_auth.py backend/tests/test_any_auth_no_scope.py
git commit -m "feat(auth): require_any_auth_no_scope pour endpoints system-wide"
```

---

## Task 5: `public_router` accepte API key

**Files:**
- Modify: `backend/app/api/v1/admin_secret_types.py` (changer 2 routes du `public_router`)
- Test: `backend/tests/test_secret_types_api_key_access.py` (nouveau)

- [ ] **Step 5.1: Écrire les tests rouges**

Créer `backend/tests/test_secret_types_api_key_access.py` :

```python
"""Tests P1.5 — Endpoints publics de secret-types accessibles via API key."""
from __future__ import annotations

import base64
import datetime
import uuid
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from tests._helpers import (
    TEST_AUDIENCE,
    TEST_KID,
    TEST_PUBLIC_JWK,
)

_NOW = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.UTC)
_API_KEY_TOKEN = "hrpv_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890aBcDeFgHi"  # placeholder


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://keycloak.yoops.org")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", TEST_AUDIENCE)
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://vault.yoops.org")


@pytest.fixture(autouse=True)
def patch_jwks() -> Generator[None, None, None]:
    from app.core import jwks_cache
    keys_backup = dict(jwks_cache._keys)
    jwks_cache._keys.clear()
    jwks_cache._keys[TEST_KID] = TEST_PUBLIC_JWK
    yield
    jwks_cache._keys.clear()
    jwks_cache._keys.update(keys_backup)


def _make_client_with_mocked_pool() -> AsyncClient:
    from app.db import pool as pool_mod
    from app.main import app

    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])

    class _Ctx:
        async def __aenter__(self): return conn
        async def __aexit__(self, *a): pass

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_Ctx())
    pool_mod._pool = pool

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_list_types_with_api_key_returns_200(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /v1/secret-types avec un Bearer hrpv_* doit retourner 200."""
    # Mock validate_api_key_token pour qu'il renvoie un caller valide sans toucher la BDD
    from app.core import api_key_auth as auth_mod

    class _FakeCaller:
        owner_user_id = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
        wallet_id = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")
        permissions = 63

    async def _fake_validate(token: str, *, pool: Any, required_permission: int = 0) -> Any:
        return _FakeCaller()

    monkeypatch.setattr(auth_mod, "validate_api_key_token", _fake_validate)

    async with _make_client_with_mocked_pool() as cli:
        r = await cli.get(
            "/v1/secret-types",
            headers={"Authorization": f"Bearer {_API_KEY_TOKEN}"},
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert "types" in body


@pytest.mark.asyncio
async def test_get_type_with_api_key_returns_200(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /v1/secret-types/{uuid} avec un Bearer hrpv_* doit retourner 200 (ou 404 si pas trouvé)."""
    from app.core import api_key_auth as auth_mod

    class _FakeCaller:
        owner_user_id = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
        wallet_id = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")
        permissions = 63

    async def _fake_validate(token: str, *, pool: Any, required_permission: int = 0) -> Any:
        return _FakeCaller()

    monkeypatch.setattr(auth_mod, "validate_api_key_token", _fake_validate)

    type_uuid = uuid.UUID("eeeeeeee-0000-0000-0000-000000000001")

    async with _make_client_with_mocked_pool() as cli:
        r = await cli.get(
            f"/v1/secret-types/{type_uuid}",
            headers={"Authorization": f"Bearer {_API_KEY_TOKEN}"},
        )

    # 404 acceptable (le mock renvoie None pour fetchrow) — l'important est que ce ne soit PAS 401/403
    assert r.status_code in (200, 404), r.text


@pytest.mark.asyncio
async def test_list_types_without_token_still_returns_401() -> None:
    """GET /v1/secret-types sans Authorization → 401."""
    async with _make_client_with_mocked_pool() as cli:
        r = await cli.get("/v1/secret-types")
    assert r.status_code == 401
```

- [ ] **Step 5.2: Lancer les tests → DOIVENT échouer (les API key tests)**

```bash
cd /e/srcs/harpocrate/backend && uv run pytest tests/test_secret_types_api_key_access.py -v
```
Expected : les 2 tests API key FAIL avec 401 (parce que `JwtUser` rejette les tokens hrpv_*). Le 3e test (sans token) doit déjà passer.

- [ ] **Step 5.3: Switcher la dep dans `admin_secret_types.py`**

Dans `backend/app/api/v1/admin_secret_types.py`, modifier les imports en tête :

```python
from app.core.api_key_auth import require_any_auth_no_scope, AuthContext
```

Garder `from app.core.security import JwtUser` car il sert encore aux routes admin (admin uses AdminJwt, not JwtUser — vérifier que JwtUser n'est plus utilisé après modif et le retirer si oui).

Ensuite, dans la section `# ─── Public endpoint ──────────────────────────────────────────────────────────`, remplacer les signatures :

```python
@public_router.get("", response_class=JSONResponse)
async def list_secret_types_public(
    auth: Annotated[AuthContext, Depends(require_any_auth_no_scope)],
    q: str | None = Query(default=None),
    include_deprecated: bool = Query(default=False),
) -> JSONResponse:
    """Liste publique des types de secrets (pour UI création de secret).

    Accepte JWT user OU API key (hrpv_*).
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await repo.list_types(conn, q=q, include_deprecated=include_deprecated)
    return JSONResponse({"types": [_type_list_item(r) for r in rows]})


@public_router.get("/{type_uuid}", response_class=JSONResponse)
async def get_secret_type_public(
    type_uuid: UUID,
    auth: Annotated[AuthContext, Depends(require_any_auth_no_scope)],
) -> JSONResponse:
    """Détail public d'un type. Accepte JWT user OU API key."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await repo.get_type(conn, type_uuid)
        if not row:
            raise HTTPException(status_code=404, detail={"error": "type_not_found"})
        versions = await repo.get_type_versions(conn, type_uuid)
    result = _type_list_item(row)
    if row["current_version_uuid"] is not None:
        sd = row["cv_schema_data"]
        su = row["cv_schema_ui"]
        result["current_version_full"] = {
            "version_uuid": str(row["current_version_uuid"]),
            "version": row["cv_version"],
            "schema_data": json.loads(sd) if isinstance(sd, str) else dict(sd),
            "schema_ui": json.loads(su) if isinstance(su, str) else dict(su),
            "created_at": row["cv_created_at"].isoformat() if row["cv_created_at"] else None,
        }
    else:
        result["current_version_full"] = None
    result["all_versions"] = [_version_dict(v) for v in versions]
    return JSONResponse(result)
```

Et ajouter en tête du fichier les imports manquants :
```python
from typing import Annotated
from fastapi import Depends
```

Si `JwtUser` n'est plus référencé, retirer son import.

- [ ] **Step 5.4: Tests doivent passer**

```bash
cd /e/srcs/harpocrate/backend && uv run pytest tests/test_secret_types_api_key_access.py -v
```
Expected : 3 PASS.

- [ ] **Step 5.5: Commit**

```bash
git add backend/app/api/v1/admin_secret_types.py backend/tests/test_secret_types_api_key_access.py
git commit -m "feat(secret_types): endpoints publics accessibles via API key"
```

---

## Task 6: Vérification finale P1.5

- [ ] **Step 6.1: Suite complète sur les fichiers touchés**

```bash
cd /e/srcs/harpocrate/backend && uv run pytest tests/test_secret_paths.py tests/test_invalid_secret_path_handler.py tests/test_secrets_by_id.py tests/test_secrets_default_raw_type.py tests/test_secret_types_deprecated_block.py tests/test_any_auth_no_scope.py tests/test_secret_types_api_key_access.py -v 2>&1 | tail -30
```
Expected : tous PASS.

- [ ] **Step 6.2: Ruff sur tous les fichiers touchés**

```bash
cd /e/srcs/harpocrate/backend && uv run ruff check \
  app/db/repositories/secret_types.py \
  app/services/secrets.py \
  app/api/v1/secrets.py \
  app/api/v1/admin_secret_types.py \
  app/core/api_key_auth.py \
  tests/test_secrets_default_raw_type.py \
  tests/test_secret_types_deprecated_block.py \
  tests/test_any_auth_no_scope.py \
  tests/test_secret_types_api_key_access.py 2>&1
```
Expected : `All checks passed!`

- [ ] **Step 6.3: Format ruff (auto-fix si nécessaire)**

```bash
cd /e/srcs/harpocrate/backend && uv run ruff format \
  app/db/repositories/secret_types.py \
  app/services/secrets.py \
  app/api/v1/secrets.py \
  app/api/v1/admin_secret_types.py \
  app/core/api_key_auth.py \
  tests/test_secrets_default_raw_type.py \
  tests/test_secret_types_deprecated_block.py \
  tests/test_any_auth_no_scope.py \
  tests/test_secret_types_api_key_access.py 2>&1
```

Si reformaté, commit :
```bash
git add -u && git commit -m "chore: ruff format après P1.5"
```

- [ ] **Step 6.4: Vérification OpenAPI / route enregistrement**

```bash
cd /e/srcs/harpocrate/backend && uv run python -c "
from app.main import app
routes = [(sorted(r.methods), r.path) for r in app.routes if hasattr(r, 'methods')]
secret_type_routes = [r for r in routes if 'secret-types' in r[1]]
for m, p in sorted(secret_type_routes, key=lambda x: x[1]):
    print(f'{m} {p}')
"
```
Expected : on voit les 2 endpoints publics + les endpoints admin (préfixés `/admin/`).

---

## Acceptance criteria P1.5

- ✅ POST `/v1/wallets/{wid}/secrets` sans `type_uuid` → secret créé avec type_uuid = RAW (pas null)
- ✅ POST `/v1/wallets/{wid}/secrets` avec `type_uuid` d'un type deprecated → 400 `deprecated_type`
- ✅ POST `/v1/wallets/{wid}/secrets` avec `type_uuid` d'un type actif → 201
- ✅ PATCH `/migrate-schema` vers une version d'un type deprecated → 400 `deprecated_type`
- ✅ PATCH `/assign-type` avec un type deprecated → 400 `deprecated_type`
- ✅ GET `/v1/secret-types` avec un token API key (hrpv_*) → 200
- ✅ GET `/v1/secret-types/{uuid}` avec un token API key → 200/404
- ✅ GET `/v1/secret-types` sans token → 401
- ✅ Aucune régression sur P1 (tests by-id, validation paths, handler 400)
- ✅ Ruff propre sur tous les fichiers touchés

## Hors scope P1.5 (reporté)

- Migration des secrets existants qui ont `type_uuid IS NULL` vers RAW (pas demandé — ils restent en l'état)
- Déprécation côté frontend / SDK : on l'accroche dans P2/P3 quand on touchera ces couches
- by-id pour `migrate-schema` et `assign-type` → P3.5
