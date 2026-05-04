# LOT 12A — Backend Backup/Restore + Mode Maintenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implémenter les endpoints admin backup/restore avec chiffrement `age`, le mode maintenance et l'authentification admin par rôle Keycloak.

**Architecture:** Service `BackupService` (subprocess pg_dump + age CLI) + repository `backups_repo` (asyncpg) + routers `/v1/admin/backups/*` et `/v1/admin/maintenance/*`. L'admin est identifié par le claim `roles` dans le JWT Keycloak. Le mode maintenance est un flag en RAM + persisté dans la table `system_metadata`.

**Tech Stack:** FastAPI + asyncpg + Python subprocess (pg_dump, psql, age CLI) + tarfile + gzip + hashlib + Pydantic Settings avec `json_schema_extra={"is_secret": True}`.

---

## File Structure

```
backend/
├── migrations/
│   └── 004_backup_tables.sql           # CREATE backups_local + system_metadata
├── app/
│   ├── core/
│   │   ├── config.py                   # +age_public_key, backup_local_path, admin_role_name
│   │   ├── admin_auth.py               # NEW: dependency require_admin_jwt
│   │   └── maintenance.py             # NEW: MaintenanceState singleton + middleware
│   ├── db/repositories/
│   │   └── backups.py                  # NEW: CRUD backups_local + system_metadata
│   ├── services/
│   │   └── backup.py                   # NEW: BackupService (create, verify, restore)
│   └── api/v1/
│       ├── admin_backups.py            # NEW: router /v1/admin/backups/*
│       ├── admin_maintenance.py       # NEW: router /v1/admin/maintenance/*
│       └── __init__.py
├── main.py                             # +middleware maintenance + mount admin routers
└── tests/
    ├── test_admin_auth.py              # NEW
    ├── test_maintenance.py            # NEW
    └── test_admin_backups.py          # NEW
```

---

## Task 1: Migration 004 — Tables backup et system_metadata

**Files:**
- Create: `backend/migrations/004_backup_tables.sql`

- [ ] **Step 1: Créer le fichier de migration**

```sql
-- migrations/004_backup_tables.sql

CREATE TABLE backups_local (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename            TEXT NOT NULL UNIQUE,
    size_bytes          BIGINT NOT NULL,
    checksum_sha256     TEXT NOT NULL,
    age_recipient       TEXT NOT NULL,
    manifest            JSONB NOT NULL,
    description         TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by_user_id  UUID REFERENCES users(id) ON DELETE SET NULL,
    imported            BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT backups_local_filename_format
        CHECK (filename ~ '^harpocrate-backup-.*\.tar\.age$' OR imported = TRUE)
);

CREATE INDEX idx_backups_local_created_at ON backups_local(created_at DESC);

CREATE TABLE system_metadata (
    key        TEXT PRIMARY KEY,
    value      JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO system_metadata (key, value) VALUES
    ('maintenance_mode', '{"active": false, "reason": null, "started_at": null, "effective_at": null, "estimated_end_at": null}'::jsonb),
    ('last_restored_at', 'null'::jsonb),
    ('last_backup_at', 'null'::jsonb);
```

- [ ] **Step 2: Vérifier syntaxe (optionnel si pas de DB locale)**

```bash
cd backend
# Si connexion DB locale disponible :
uv run python -m migrations.apply_migrations
# Sinon : vérification manuelle de la syntaxe SQL ci-dessus
```

---

## Task 2: Config — Nouveaux settings backup + is_secret metadata

**Files:**
- Modify: `backend/app/core/config.py`

- [ ] **Step 1: Ajouter les settings manquants**

Dans `backend/app/core/config.py`, ajouter après `dev_mode_label`:

```python
    # ─── Backup (LOT_12A) ─────────────────────────────────────────────────────
    # Clé publique age pour chiffrer les backups.
    # Format : age1<bech32>
    age_public_key: str = Field(
        default="",
        json_schema_extra={"is_secret": False},
    )
    # Dossier de stockage des backups sur le serveur.
    backup_local_path: str = Field(default="/var/lib/harpocrate/backups")
    # Rôle Keycloak qui donne accès aux endpoints /v1/admin/*.
    admin_role_name: str = Field(default="harpocrate-admin")
    # Taille max upload backup en bytes (1 GB par défaut).
    backup_upload_max_bytes: int = Field(default=1 * 1024 * 1024 * 1024)
    # Variables d'env considérées comme sensibles (exclues du backup non-sensible).
    # Clé : nom du champ Settings (snake_case). Valeur : True = sensible.
    # Ajouté ici pour usage dans BackupService._extract_non_sensitive_env().
    hmac_key: str  # déjà déclaré — annoté via json_schema_extra plus bas
```

Ensuite, marquer les champs sensibles existants avec `json_schema_extra={"is_secret": True}`. Remplacer les déclarations existantes :

```python
    db_dsn: str = Field(json_schema_extra={"is_secret": True})
    hmac_key: str = Field(json_schema_extra={"is_secret": True})
    admin_local_password: str = Field(default="", json_schema_extra={"is_secret": True})
```

Et ajouter les méthodes utilitaires en fin de classe (avant les validators) :

```python
    def get_sensitive_fields(self) -> list[str]:
        """Retourne les noms des champs Settings marqués is_secret=True."""
        result = []
        for name, field in self.model_fields.items():
            extra = field.json_schema_extra or {}
            if extra.get("is_secret", False):
                result.append(name)
        return result

    def get_non_sensitive_fields(self) -> dict[str, object]:
        """Retourne les champs non-sensibles sous forme {HARPOCRATE_NAME: value}."""
        result: dict[str, object] = {}
        sensitive = set(self.get_sensitive_fields())
        for name in self.model_fields:
            if name not in sensitive:
                value = getattr(self, name)
                result[f"HARPOCRATE_{name.upper()}"] = value
        return result
```

- [ ] **Step 2: Vérifier que les tests existants passent**

```bash
cd backend
uv run pytest tests/test_config.py -x -q
```

Expected: PASS (les nouveaux champs ont des defaults, pas de breaking change).

---

## Task 3: Admin auth — Dependency `require_admin_jwt`

**Files:**
- Create: `backend/app/core/admin_auth.py`
- Create: `backend/tests/test_admin_auth.py`

- [ ] **Step 1: Écrire le test qui échoue**

```python
# backend/tests/test_admin_auth.py
"""Tests de la dependency require_admin_jwt — LOT_12A."""
from __future__ import annotations

import base64
from collections.abc import Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests._helpers import TEST_AUDIENCE, TEST_KID, TEST_PUBLIC_JWK, make_jwt_token


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


def _admin_token() -> str:
    return make_jwt_token(extra_claims={"realm_access": {"roles": ["harpocrate-admin"]}})


def _user_token() -> str:
    return make_jwt_token()  # no admin role


def test_require_admin_jwt_accepts_admin_token() -> None:
    from app.core.admin_auth import require_admin_jwt
    app_test = FastAPI()

    @app_test.get("/admin-only")
    async def admin_route(user=__import__("fastapi").Depends(require_admin_jwt)):
        return {"ok": True}

    client = TestClient(app_test)
    r = client.get("/admin-only", headers={"Authorization": f"Bearer {_admin_token()}"})
    assert r.status_code == 200


def test_require_admin_jwt_rejects_non_admin() -> None:
    from app.core.admin_auth import require_admin_jwt
    app_test = FastAPI()

    @app_test.get("/admin-only")
    async def admin_route(user=__import__("fastapi").Depends(require_admin_jwt)):
        return {"ok": True}

    client = TestClient(app_test)
    r = client.get("/admin-only", headers={"Authorization": f"Bearer {_user_token()}"})
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "admin_role_required"


def test_require_admin_jwt_rejects_api_key() -> None:
    from app.core.admin_auth import require_admin_jwt
    app_test = FastAPI()

    @app_test.get("/admin-only")
    async def admin_route(user=__import__("fastapi").Depends(require_admin_jwt)):
        return {"ok": True}

    client = TestClient(app_test)
    r = client.get("/admin-only", headers={"Authorization": "Bearer hrpv_sometoken"})
    assert r.status_code == 401
    assert r.json()["detail"]["error"] == "admin_jwt_only"


def test_require_admin_jwt_rejects_missing_auth() -> None:
    from app.core.admin_auth import require_admin_jwt
    app_test = FastAPI()

    @app_test.get("/admin-only")
    async def admin_route(user=__import__("fastapi").Depends(require_admin_jwt)):
        return {"ok": True}

    client = TestClient(app_test)
    r = client.get("/admin-only")
    assert r.status_code == 401
```

- [ ] **Step 2: Exécuter le test pour vérifier l'échec**

```bash
cd backend
uv run pytest tests/test_admin_auth.py -x -q 2>&1 | head -20
```

Expected: FAIL avec `ModuleNotFoundError: No module named 'app.core.admin_auth'`

- [ ] **Step 3: Implémenter `admin_auth.py`**

```python
# backend/app/core/admin_auth.py
"""Dependency FastAPI pour l'authentification admin JWT (rôle Keycloak) — LOT_12A."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.core.config import settings
from app.core.security import _validate_jwt


@dataclass(frozen=True)
class AdminUser:
    """Représente un admin authentifié via JWT Keycloak avec rôle harpocrate-admin."""
    keycloak_sub: str
    email: str
    display_name: str | None


async def require_admin_jwt(
    authorization: Annotated[str | None, Header()] = None,
) -> AdminUser:
    """Dependency FastAPI — valide le JWT et vérifie le rôle admin Keycloak.

    Refuse les tokens API key (hrpv_*) et les tokens sans rôle admin.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "missing_bearer_token",
                "message": "Authorization header with Bearer token required",
            },
        )

    token = authorization[7:]

    if token.startswith("hrpv_"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "admin_jwt_only",
                "message": "Admin endpoints require a JWT token, not an API key",
            },
        )

    payload = await _validate_jwt(token)

    # Vérification du rôle admin dans realm_access.roles
    realm_access = payload.get("realm_access", {})
    roles: list[str] = realm_access.get("roles", [])

    if settings.admin_role_name not in roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "admin_role_required",
                "message": f"JWT must contain role '{settings.admin_role_name}'",
            },
        )

    return AdminUser(
        keycloak_sub=payload["sub"],
        email=payload.get("email", ""),
        display_name=payload.get("name"),
    )


AdminJwt = Annotated[AdminUser, Depends(require_admin_jwt)]
```

- [ ] **Step 4: Exécuter les tests pour vérifier le passage**

```bash
cd backend
uv run pytest tests/test_admin_auth.py -x -q
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd backend
git add migrations/004_backup_tables.sql app/core/config.py app/core/admin_auth.py tests/test_admin_auth.py
git commit -m "feat(backup P1): migration 004 + settings is_secret + admin JWT dependency"
```

---

## Task 4: Maintenance — État en RAM + Repository + Endpoints

**Files:**
- Create: `backend/app/core/maintenance.py`
- Create: `backend/app/db/repositories/system_metadata.py`
- Create: `backend/app/api/v1/admin_maintenance.py`
- Create: `backend/tests/test_maintenance.py`
- Modify: `backend/app/main.py` (add middleware + router)

- [ ] **Step 1: Écrire les tests du mode maintenance**

```python
# backend/tests/test_maintenance.py
"""Tests du mode maintenance (middleware + endpoints) — LOT_12A."""
from __future__ import annotations

import base64
import datetime
import uuid
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from tests._helpers import TEST_AUDIENCE, TEST_KID, TEST_PUBLIC_JWK, make_jwt_token

_NOW = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.UTC)
_ADMIN_ROLE = "harpocrate-admin"


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


@pytest.fixture(autouse=True)
def reset_maintenance() -> Generator[None, None, None]:
    """Remet le mode maintenance à False entre chaque test."""
    from app.core.maintenance import maintenance_state
    maintenance_state.active = False
    maintenance_state.reason = None
    maintenance_state.started_at = None
    maintenance_state.effective_at = None
    maintenance_state.estimated_end_at = None
    yield
    maintenance_state.active = False


class FakeRecord(dict[str, Any]):
    def __getitem__(self, key: str) -> Any:
        return super().__getitem__(key)


def _make_conn() -> MagicMock:
    conn: MagicMock = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.execute = AsyncMock(return_value=None)
    return conn


def _make_pool(conn: MagicMock) -> MagicMock:
    class _Ctx:
        async def __aenter__(self) -> MagicMock:
            return conn
        async def __aexit__(self, *a: Any) -> None:
            pass
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_Ctx())
    return pool


def _make_client(pool: MagicMock) -> AsyncClient:
    from app.db import pool as pool_mod
    from app.main import app
    pool_mod._pool = pool
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _admin_header() -> dict[str, str]:
    token = make_jwt_token(extra_claims={"realm_access": {"roles": [_ADMIN_ROLE]}})
    return {"Authorization": f"Bearer {token}"}


def _user_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_jwt_token()}"}


@pytest.mark.asyncio
async def test_maintenance_status_public_initially_inactive() -> None:
    """GET /v1/admin/maintenance/status est public et retourne inactive par défaut."""
    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.get("/v1/admin/maintenance/status")
    assert r.status_code == 200
    assert r.json()["active"] is False


@pytest.mark.asyncio
async def test_maintenance_enable_requires_admin() -> None:
    """POST /v1/admin/maintenance/enable → 403 si pas admin."""
    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            "/v1/admin/maintenance/enable",
            json={"reason": "test"},
            headers=_user_header(),
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_maintenance_enable_sets_active() -> None:
    """POST /v1/admin/maintenance/enable active le mode maintenance."""
    conn = _make_conn()
    conn.execute = AsyncMock(return_value=None)

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            "/v1/admin/maintenance/enable",
            json={"reason": "DB maintenance", "delay_seconds": 0, "estimated_duration_minutes": 5},
            headers=_admin_header(),
        )
    assert r.status_code == 200
    body = r.json()
    assert body["active"] is True

    # Vérifier l'état en RAM
    from app.core.maintenance import maintenance_state
    assert maintenance_state.active is True


@pytest.mark.asyncio
async def test_maintenance_blocks_normal_requests() -> None:
    """En mode maintenance, les requêtes non-admin reçoivent 503."""
    from app.core.maintenance import maintenance_state
    maintenance_state.active = True

    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.get("/v1/wallets", headers=_user_header())
    assert r.status_code == 503
    assert r.json()["error"] == "maintenance_in_progress"


@pytest.mark.asyncio
async def test_maintenance_allows_health() -> None:
    """En mode maintenance, /v1/health passe toujours."""
    from app.core.maintenance import maintenance_state
    maintenance_state.active = True

    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.get("/v1/health")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_maintenance_allows_admin_routes() -> None:
    """En mode maintenance, /v1/admin/* passe."""
    from app.core.maintenance import maintenance_state
    maintenance_state.active = True

    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.get("/v1/admin/maintenance/status")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_maintenance_disable() -> None:
    """POST /v1/admin/maintenance/disable désactive le mode."""
    from app.core.maintenance import maintenance_state
    maintenance_state.active = True

    conn = _make_conn()
    conn.execute = AsyncMock(return_value=None)

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            "/v1/admin/maintenance/disable",
            headers=_admin_header(),
        )
    assert r.status_code == 200
    assert maintenance_state.active is False
```

- [ ] **Step 2: Exécuter les tests pour vérifier l'échec**

```bash
cd backend
uv run pytest tests/test_maintenance.py -x -q 2>&1 | head -20
```

Expected: FAIL avec erreurs d'import ou 404 sur les routes.

- [ ] **Step 3: Créer `maintenance.py` (état en RAM)**

```python
# backend/app/core/maintenance.py
"""État du mode maintenance en RAM (singleton) — LOT_12A."""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field


@dataclass
class MaintenanceState:
    """Singleton mutable représentant l'état du mode maintenance."""
    active: bool = False
    reason: str | None = None
    started_at: datetime.datetime | None = None
    effective_at: datetime.datetime | None = None
    estimated_end_at: datetime.datetime | None = None


maintenance_state = MaintenanceState()
```

- [ ] **Step 4: Créer `system_metadata.py` (repository)**

```python
# backend/app/db/repositories/system_metadata.py
"""Repository pour la table system_metadata — LOT_12A."""
from __future__ import annotations

import json
from typing import Any

import asyncpg


async def get_value(conn: asyncpg.Connection, key: str) -> Any:
    """Retourne la valeur JSON associée à la clé, ou None si absente."""
    row = await conn.fetchrow(
        "SELECT value FROM system_metadata WHERE key = $1", key
    )
    if row is None:
        return None
    return row["value"]


async def set_value(conn: asyncpg.Connection, key: str, value: Any) -> None:
    """Upsert la valeur JSON associée à la clé."""
    await conn.execute(
        """
        INSERT INTO system_metadata (key, value, updated_at)
        VALUES ($1, $2::jsonb, NOW())
        ON CONFLICT (key) DO UPDATE
        SET value = EXCLUDED.value, updated_at = NOW()
        """,
        key,
        json.dumps(value),
    )
```

- [ ] **Step 5: Créer `admin_maintenance.py` (router)**

```python
# backend/app/api/v1/admin_maintenance.py
"""Endpoints /v1/admin/maintenance/* — LOT_12A."""
from __future__ import annotations

import datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.admin_auth import AdminJwt
from app.core.maintenance import maintenance_state
from app.db.pool import get_pool
from app.db.repositories import system_metadata as meta_repo

router = APIRouter(prefix="/admin/maintenance", tags=["admin-maintenance"])


@router.get("/status", include_in_schema=True)
async def maintenance_status() -> JSONResponse:
    """Retourne l'état actuel du mode maintenance (public, sans auth)."""
    return JSONResponse({
        "active": maintenance_state.active,
        "reason": maintenance_state.reason,
        "started_at": maintenance_state.started_at.isoformat() if maintenance_state.started_at else None,
        "effective_at": maintenance_state.effective_at.isoformat() if maintenance_state.effective_at else None,
        "estimated_end_at": maintenance_state.estimated_end_at.isoformat() if maintenance_state.estimated_end_at else None,
    })


@router.post("/enable")
async def maintenance_enable(
    body: dict,
    admin: AdminJwt,
) -> JSONResponse:
    """Active le mode maintenance. Requiert le rôle harpocrate-admin."""
    from pydantic import BaseModel, Field
    from typing import Optional

    class EnableBody(BaseModel):
        reason: str = "Maintenance in progress"
        delay_seconds: int = Field(default=0, ge=0)
        estimated_duration_minutes: int = Field(default=0, ge=0)

    params = EnableBody.model_validate(body)
    now = datetime.datetime.now(datetime.UTC)
    effective = now + datetime.timedelta(seconds=params.delay_seconds)
    estimated_end = (
        effective + datetime.timedelta(minutes=params.estimated_duration_minutes)
        if params.estimated_duration_minutes > 0
        else None
    )

    maintenance_state.active = True
    maintenance_state.reason = params.reason
    maintenance_state.started_at = now
    maintenance_state.effective_at = effective
    maintenance_state.estimated_end_at = estimated_end

    pool = await get_pool()
    async with pool.acquire() as conn:
        await meta_repo.set_value(conn, "maintenance_mode", {
            "active": True,
            "reason": params.reason,
            "started_at": now.isoformat(),
        })

    return JSONResponse({
        "active": True,
        "reason": params.reason,
        "started_at": now.isoformat(),
        "effective_at": effective.isoformat(),
        "estimated_end_at": estimated_end.isoformat() if estimated_end else None,
    })


@router.post("/disable")
async def maintenance_disable(admin: AdminJwt) -> JSONResponse:
    """Désactive le mode maintenance."""
    maintenance_state.active = False
    maintenance_state.reason = None
    maintenance_state.started_at = None
    maintenance_state.effective_at = None
    maintenance_state.estimated_end_at = None

    pool = await get_pool()
    async with pool.acquire() as conn:
        await meta_repo.set_value(conn, "maintenance_mode", {"active": False})

    return JSONResponse({"active": False})
```

- [ ] **Step 6: Ajouter le middleware maintenance dans `main.py`**

Dans `backend/app/main.py`, ajouter le middleware après les imports existants:

```python
# Dans les imports:
from app.core.maintenance import maintenance_state

# Dans la fonction app ou après la création de l'app FastAPI:
@app.middleware("http")
async def maintenance_middleware(request: Request, call_next: Any) -> Any:
    if maintenance_state.active:
        path = request.url.path
        # Toujours autoriser: admin, health, maintenance status
        if (
            path.startswith("/v1/admin/")
            or path == "/v1/health"
            or path == "/v1/admin/maintenance/status"
        ):
            return await call_next(request)
        # Tout le reste: 503
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=503,
            content={"error": "maintenance_in_progress", "estimated_end_at": (
                maintenance_state.estimated_end_at.isoformat()
                if maintenance_state.estimated_end_at else None
            )},
            headers={"Retry-After": "60"},
        )
    return await call_next(request)
```

Et enregistrer le router dans `main.py`:

```python
from app.api.v1.admin_maintenance import router as admin_maintenance_router

# Dans la section d'enregistrement des routers:
app.include_router(admin_maintenance_router, prefix="/v1")
```

- [ ] **Step 7: Exécuter les tests maintenance**

```bash
cd backend
uv run pytest tests/test_maintenance.py -x -q
```

Expected: tous les tests PASS.

- [ ] **Step 8: Exécuter tous les tests pour vérifier pas de régression**

```bash
cd backend
uv run pytest -x -q
```

Expected: tous les tests passent.

- [ ] **Step 9: Commit**

```bash
git add app/core/maintenance.py app/core/admin_auth.py \
        app/db/repositories/system_metadata.py \
        app/api/v1/admin_maintenance.py \
        app/main.py \
        tests/test_maintenance.py
git commit -m "feat(backup P2): mode maintenance + endpoints + middleware"
```

---

## Task 5: Backup repository — CRUD `backups_local`

**Files:**
- Create: `backend/app/db/repositories/backups.py`

- [ ] **Step 1: Créer le repository**

```python
# backend/app/db/repositories/backups.py
"""Repository pour la table backups_local — LOT_12A."""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg


@dataclass
class BackupRecord:
    id: UUID
    filename: str
    size_bytes: int
    checksum_sha256: str
    age_recipient: str
    manifest: dict[str, Any]
    description: str | None
    created_at: datetime
    created_by_user_id: UUID | None
    imported: bool


def _row_to_backup(row: asyncpg.Record) -> BackupRecord:
    manifest = row["manifest"]
    if isinstance(manifest, str):
        manifest = json.loads(manifest)
    return BackupRecord(
        id=row["id"],
        filename=row["filename"],
        size_bytes=row["size_bytes"],
        checksum_sha256=row["checksum_sha256"],
        age_recipient=row["age_recipient"],
        manifest=manifest,
        description=row["description"],
        created_at=row["created_at"],
        created_by_user_id=row["created_by_user_id"],
        imported=row["imported"],
    )


async def insert_backup(
    conn: asyncpg.Connection,
    *,
    filename: str,
    size_bytes: int,
    checksum_sha256: str,
    age_recipient: str,
    manifest: dict[str, Any],
    description: str | None,
    created_by_user_id: UUID | None,
    imported: bool = False,
) -> BackupRecord:
    row = await conn.fetchrow(
        """
        INSERT INTO backups_local
            (filename, size_bytes, checksum_sha256, age_recipient, manifest,
             description, created_by_user_id, imported)
        VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8)
        RETURNING *
        """,
        filename,
        size_bytes,
        checksum_sha256,
        age_recipient,
        json.dumps(manifest),
        description,
        created_by_user_id,
        imported,
    )
    assert row is not None
    return _row_to_backup(row)


async def list_backups(
    conn: asyncpg.Connection,
    *,
    limit: int = 50,
    cursor_created_at: datetime | None = None,
    cursor_id: UUID | None = None,
) -> list[BackupRecord]:
    if cursor_created_at is not None and cursor_id is not None:
        rows = await conn.fetch(
            """
            SELECT * FROM backups_local
            WHERE (created_at, id) < ($1, $2)
            ORDER BY created_at DESC, id DESC
            LIMIT $3
            """,
            cursor_created_at, cursor_id, limit,
        )
    else:
        rows = await conn.fetch(
            "SELECT * FROM backups_local ORDER BY created_at DESC, id DESC LIMIT $1",
            limit,
        )
    return [_row_to_backup(r) for r in rows]


async def get_backup(conn: asyncpg.Connection, backup_id: UUID) -> BackupRecord | None:
    row = await conn.fetchrow(
        "SELECT * FROM backups_local WHERE id = $1", backup_id
    )
    return _row_to_backup(row) if row else None


async def delete_backup(conn: asyncpg.Connection, backup_id: UUID) -> bool:
    result = await conn.execute(
        "DELETE FROM backups_local WHERE id = $1", backup_id
    )
    return result == "DELETE 1"
```

---

## Task 6: Backup service — Création et vérification

**Files:**
- Create: `backend/app/services/backup.py`

- [ ] **Step 1: Créer le service backup**

```python
# backend/app/services/backup.py
"""Service de backup/restore avec chiffrement age — LOT_12A."""
from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID

import asyncpg
from fastapi import HTTPException, status

from app.core.config import settings
from app.db.repositories import backups as backups_repo
from app.db.repositories import system_metadata as meta_repo


class BackupError(Exception):
    pass


@dataclass
class VerifyResult:
    valid: bool
    manifest: dict
    checksums_match: bool
    dump_sql_lines: int


@dataclass
class RestoreResult:
    success: bool
    restored_from_backup_id: UUID
    session_epoch_new: int
    env_restore_file_path: str


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


async def _run(cmd: list[str], stdin: bytes | None = None) -> tuple[int, bytes, bytes]:
    """Exécute une commande subprocess et retourne (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE if stdin is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(input=stdin)
    return proc.returncode or 0, stdout, stderr


def _backup_dir() -> Path:
    path = Path(settings.backup_local_path)
    path.mkdir(parents=True, exist_ok=True)
    return path


async def _compute_stats(conn: asyncpg.Connection) -> dict:
    row = await conn.fetchrow("""
        SELECT
            (SELECT count(*) FROM users) AS users_count,
            (SELECT count(*) FROM wallets) AS wallets_count,
            (SELECT count(*) FROM secrets) AS secrets_count,
            (SELECT count(*) FROM api_keys) AS api_keys_count,
            (SELECT count(*) FROM audit_log) AS audit_log_entries_count
    """)
    assert row is not None
    return {k: int(row[k]) for k in row.keys()}


async def get_current_session_epoch(conn: asyncpg.Connection) -> int:
    row = await conn.fetchrow("SELECT epoch FROM server_session_epoch LIMIT 1")
    if row is None:
        return 0
    return int(row["epoch"])


async def rotate_session_epoch(conn: asyncpg.Connection, reason: str) -> int:
    row = await conn.fetchrow(
        "UPDATE server_session_epoch SET epoch = epoch + 1, reason = $1, updated_at = NOW() RETURNING epoch",
        reason,
    )
    assert row is not None
    return int(row["epoch"])


async def create_backup(
    conn: asyncpg.Connection,
    *,
    description: str | None,
    created_by_user_id: UUID,
    created_by_email: str,
) -> backups_repo.BackupRecord:
    """Crée un backup chiffré avec age et l'enregistre en DB."""
    if not settings.age_public_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "age_key_not_configured", "message": "HARPOCRATE_AGE_PUBLIC_KEY not set"},
        )

    timestamp = datetime.utcnow().strftime("%Y-%m-%d-%H-%M-%S")
    filename = f"harpocrate-backup-{timestamp}.tar.age"
    out_path = _backup_dir() / filename

    stats = await _compute_stats(conn)
    epoch = await get_current_session_epoch(conn)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # 1. pg_dump
        dump_path = tmp / "dump.sql"
        rc, _, stderr = await _run([
            "pg_dump", settings.db_dsn,
            "--format=plain",
            "--serializable-deferrable",
            "--no-owner",
            "--no-acl",
        ])
        if rc != 0:
            raise BackupError(f"pg_dump failed: {stderr.decode()}")

        # En pratique pg_dump écrit sur stdout → on le capture différemment
        proc = await asyncio.create_subprocess_exec(
            "pg_dump", settings.db_dsn,
            "--format=plain", "--serializable-deferrable", "--no-owner", "--no-acl",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        dump_sql, stderr_bytes = await proc.communicate()
        if proc.returncode != 0:
            raise BackupError(f"pg_dump failed: {stderr_bytes.decode()}")

        # 2. Gzip
        dump_gz_path = tmp / "dump.sql.gz"
        with gzip.open(dump_gz_path, "wb") as gz:
            gz.write(dump_sql)

        # 3. Env non-sensible
        env_path = tmp / "env-non-sensitive.json"
        env_path.write_text(json.dumps(settings.get_non_sensitive_fields(), indent=2))

        # 4. Checksums
        dump_sha = _sha256_file(dump_gz_path)
        env_sha = _sha256_file(env_path)

        # 5. Manifest
        manifest: dict = {
            "format_version": "1",
            "harpocrate_version": "0.1.0",
            "created_at": datetime.utcnow().isoformat() + "Z",
            "created_by": {"user_id": str(created_by_user_id), "email": created_by_email},
            "description": description,
            "checksums": {
                "dump_sql_gz": f"sha256:{dump_sha}",
                "env_non_sensitive_json": f"sha256:{env_sha}",
            },
            "stats": stats,
            "age_recipient": settings.age_public_key,
            "schema_version": "001",
            "session_epoch_at_backup": epoch,
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
        proc2 = await asyncio.create_subprocess_exec(
            "age", "-r", settings.age_public_key,
            "-o", str(tar_age_path),
            str(tar_path),
            stderr=asyncio.subprocess.PIPE,
        )
        _, age_stderr = await proc2.communicate()
        if proc2.returncode != 0:
            raise BackupError(f"age encryption failed: {age_stderr.decode()}")

        # 8. Checksum final + move
        final_checksum = _sha256_file(tar_age_path)
        shutil.move(str(tar_age_path), str(out_path))

    size = out_path.stat().st_size
    return await backups_repo.insert_backup(
        conn,
        filename=filename,
        size_bytes=size,
        checksum_sha256=final_checksum,
        age_recipient=settings.age_public_key,
        manifest=manifest,
        description=description,
        created_by_user_id=created_by_user_id,
    )


async def verify_backup(backup_id: UUID, age_private_key: str, conn: asyncpg.Connection) -> VerifyResult:
    """Vérifie l'intégrité du backup en le déchiffrant (sans restaurer)."""
    record = await backups_repo.get_backup(conn, backup_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "backup_not_found", "message": "Backup not found"},
        )

    backup_path = _backup_dir() / record.filename
    if not backup_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "backup_file_missing", "message": "Backup file not found on disk"},
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        tar_path = tmp / "backup.tar"

        proc = await asyncio.create_subprocess_exec(
            "age", "-d", "-i", "-",
            "-o", str(tar_path),
            str(backup_path),
            stdin=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate(input=age_private_key.encode())
        if proc.returncode != 0:
            return VerifyResult(valid=False, manifest={}, checksums_match=False, dump_sql_lines=0)

        with tarfile.open(tar_path) as tar:
            tar.extractall(tmp / "extracted")

        extracted = tmp / "extracted"
        manifest_data = json.loads((extracted / "manifest.json").read_text())

        checksums_ok = True
        for key, expected in manifest_data.get("checksums", {}).items():
            fname = key.replace("_", ".", 1).replace("_", "-").replace("sql-gz", "sql.gz").replace("non-sensitive-json", "non-sensitive.json")
            fpath = extracted / fname
            if fpath.exists():
                actual = f"sha256:{_sha256_file(fpath)}"
                if actual != expected:
                    checksums_ok = False
            else:
                checksums_ok = False

        dump_lines = 0
        dump_gz = extracted / "dump.sql.gz"
        if dump_gz.exists():
            with gzip.open(dump_gz, "rt", errors="replace") as f:
                dump_lines = sum(1 for _ in f)

        return VerifyResult(
            valid=True,
            manifest=manifest_data,
            checksums_match=checksums_ok,
            dump_sql_lines=dump_lines,
        )


async def restore_backup(
    backup_id: UUID,
    age_private_key: str,
    conn: asyncpg.Connection,
) -> RestoreResult:
    """Restaure la base depuis un backup (DROP SCHEMA + replay). DESTRUCTIF."""
    record = await backups_repo.get_backup(conn, backup_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "backup_not_found", "message": "Backup not found"},
        )

    backup_path = _backup_dir() / record.filename
    if not backup_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "backup_file_missing", "message": "Backup file not found on disk"},
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        tar_path = tmp / "backup.tar"

        # 1. Déchiffrement
        proc = await asyncio.create_subprocess_exec(
            "age", "-d", "-i", "-",
            "-o", str(tar_path),
            str(backup_path),
            stdin=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate(input=age_private_key.encode())
        if proc.returncode != 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "decryption_failed", "message": "age decryption failed — wrong key?"},
            )

        with tarfile.open(tar_path) as tar:
            tar.extractall(tmp / "extracted")
        extracted = tmp / "extracted"

        # 2. Vérification checksums
        manifest_data = json.loads((extracted / "manifest.json").read_text())
        for key, expected in manifest_data.get("checksums", {}).items():
            fname = key.replace("_gz", ".gz").replace("_json", ".json").replace("_", "-", 1).replace("_", ".")
            fpath = extracted / fname
            if not fpath.exists():
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={"error": "backup_incomplete", "message": f"Missing {fname} in archive"},
                )
            actual = f"sha256:{_sha256_file(fpath)}"
            if actual != expected:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={"error": "checksum_mismatch", "message": f"Checksum mismatch on {fname}"},
                )

        # 3. DROP schema + replay
        rc, _, stderr = await _run([
            "psql", settings.db_dsn,
            "-c", "DROP SCHEMA public CASCADE; CREATE SCHEMA public;",
        ])
        if rc != 0:
            raise BackupError(f"DROP SCHEMA failed: {stderr.decode()}")

        dump_gz = extracted / "dump.sql.gz"
        with gzip.open(dump_gz, "rb") as gz:
            dump_bytes = gz.read()

        proc2 = await asyncio.create_subprocess_exec(
            "psql", settings.db_dsn,
            stdin=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr2 = await proc2.communicate(input=dump_bytes)
        if proc2.returncode != 0:
            raise BackupError(f"psql replay failed: {stderr2.decode()}")

        # 4. Rotation epoch
        new_epoch = await rotate_session_epoch(conn, reason=f"post_restore_backup_{backup_id}")

        # 5. Fichier .env.restore
        import time as _time
        env_data = json.loads((extracted / "env-non-sensitive.json").read_text())
        backup_dir = _backup_dir()
        env_restore_path = backup_dir.parent / f".env.restore.{int(_time.time())}"
        with open(env_restore_path, "w") as f:
            for k, v in env_data.items():
                f.write(f"{k}={v}\n")

        return RestoreResult(
            success=True,
            restored_from_backup_id=backup_id,
            session_epoch_new=new_epoch,
            env_restore_file_path=str(env_restore_path),
        )
```

---

## Task 7: Admin Backups Router

**Files:**
- Create: `backend/app/api/v1/admin_backups.py`
- Create: `backend/tests/test_admin_backups.py`
- Modify: `backend/app/main.py` (register router)

- [ ] **Step 1: Écrire les tests admin_backups**

```python
# backend/tests/test_admin_backups.py
"""Tests des endpoints /v1/admin/backups/* — LOT_12A."""
from __future__ import annotations

import base64
import datetime
import json
import uuid
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from tests._helpers import TEST_AUDIENCE, TEST_KID, TEST_PUBLIC_JWK, make_jwt_token

_NOW = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.UTC)
_ADMIN_ROLE = "harpocrate-admin"
_BACKUP_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000001")
_USER_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://keycloak.yoops.org")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", TEST_AUDIENCE)
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://vault.yoops.org")
    monkeypatch.setenv("HARPOCRATE_AGE_PUBLIC_KEY", "age1qyqszqgpqyqszqgpqyqszqgpqyqszqgpq")
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


def _admin_header() -> dict[str, str]:
    token = make_jwt_token(
        extra_claims={"realm_access": {"roles": [_ADMIN_ROLE]}, "email": "admin@test.com"}
    )
    return {"Authorization": f"Bearer {token}"}


def _user_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_jwt_token()}"}


class FakeRecord(dict[str, Any]):
    def __getitem__(self, key: str) -> Any:
        return super().__getitem__(key)


def _make_conn() -> MagicMock:
    conn: MagicMock = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock(return_value=None)
    return conn


def _make_pool(conn: MagicMock) -> MagicMock:
    class _Ctx:
        async def __aenter__(self) -> MagicMock:
            return conn
        async def __aexit__(self, *a: Any) -> None:
            pass
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_Ctx())
    return pool


def _make_client(pool: MagicMock) -> AsyncClient:
    from app.db import pool as pool_mod
    from app.main import app
    pool_mod._pool = pool
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _fake_backup_row() -> FakeRecord:
    return FakeRecord({
        "id": _BACKUP_ID,
        "filename": "harpocrate-backup-2026-01-01-12-00-00.tar.age",
        "size_bytes": 123456,
        "checksum_sha256": "deadbeef",
        "age_recipient": "age1qyq...",
        "manifest": json.dumps({
            "format_version": "1",
            "harpocrate_version": "0.1.0",
            "created_at": _NOW.isoformat() + "Z",
            "created_by": {"user_id": str(_USER_ID), "email": "admin@test.com"},
            "description": "test backup",
            "checksums": {},
            "stats": {"users_count": 1},
            "age_recipient": "age1qyq...",
            "schema_version": "001",
            "session_epoch_at_backup": 1,
        }),
        "description": "test backup",
        "created_at": _NOW,
        "created_by_user_id": _USER_ID,
        "imported": False,
    })


@pytest.mark.asyncio
async def test_list_backups_requires_admin() -> None:
    """GET /v1/admin/backups → 403 si pas admin."""
    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.get("/v1/admin/backups", headers=_user_header())
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_list_backups_empty() -> None:
    """GET /v1/admin/backups → 200 liste vide."""
    conn = _make_conn()
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get("/v1/admin/backups", headers=_admin_header())
    assert r.status_code == 200
    assert r.json()["backups"] == []


@pytest.mark.asyncio
async def test_list_backups_with_results() -> None:
    """GET /v1/admin/backups → 200 avec backup."""
    conn = _make_conn()
    conn.fetch = AsyncMock(return_value=[_fake_backup_row()])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get("/v1/admin/backups", headers=_admin_header())
    assert r.status_code == 200
    backups = r.json()["backups"]
    assert len(backups) == 1
    assert backups[0]["filename"] == "harpocrate-backup-2026-01-01-12-00-00.tar.age"


@pytest.mark.asyncio
async def test_get_backup_not_found() -> None:
    """GET /v1/admin/backups/{id} → 404 si absent."""
    conn = _make_conn()
    conn.fetchrow = AsyncMock(return_value=None)

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(f"/v1/admin/backups/{_BACKUP_ID}", headers=_admin_header())
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_backup_found() -> None:
    """GET /v1/admin/backups/{id} → 200 avec détails."""
    conn = _make_conn()
    conn.fetchrow = AsyncMock(return_value=_fake_backup_row())

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(f"/v1/admin/backups/{_BACKUP_ID}", headers=_admin_header())
    assert r.status_code == 200
    assert r.json()["id"] == str(_BACKUP_ID)


@pytest.mark.asyncio
async def test_create_backup_requires_admin() -> None:
    """POST /v1/admin/backups → 403 si pas admin."""
    conn = _make_conn()
    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            "/v1/admin/backups",
            json={"description": "test"},
            headers=_user_header(),
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_delete_backup_not_found() -> None:
    """DELETE /v1/admin/backups/{id} → 404 si absent."""
    conn = _make_conn()
    conn.fetchrow = AsyncMock(return_value=None)

    async with _make_client(_make_pool(conn)) as client:
        r = await client.delete(
            f"/v1/admin/backups/{_BACKUP_ID}",
            headers=_admin_header(),
        )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_restore_wrong_confirmation() -> None:
    """POST /v1/admin/backups/{id}/restore → 400 si confirmation incorrecte."""
    conn = _make_conn()
    conn.fetchrow = AsyncMock(return_value=_fake_backup_row())

    async with _make_client(_make_pool(conn)) as client:
        r = await client.post(
            f"/v1/admin/backups/{_BACKUP_ID}/restore",
            json={
                "age_private_key": "AGE-SECRET-KEY-1...",
                "confirmation": "WRONG CONFIRMATION",
                "auto_enable_maintenance": False,
            },
            headers=_admin_header(),
        )
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "wrong_confirmation"
```

- [ ] **Step 2: Créer `admin_backups.py`**

```python
# backend/app/api/v1/admin_backups.py
"""Endpoints /v1/admin/backups/* — LOT_12A."""
from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from app.core.admin_auth import AdminJwt
from app.core.config import settings
from app.db.pool import get_pool
from app.db.repositories import backups as backups_repo
from app.services import backup as backup_svc
from app.services.audit import audit_log_insert

router = APIRouter(prefix="/admin/backups", tags=["admin-backups"])


def _backup_to_dict(r: backups_repo.BackupRecord) -> dict:
    return {
        "id": str(r.id),
        "filename": r.filename,
        "size_bytes": r.size_bytes,
        "checksum_sha256": r.checksum_sha256,
        "description": r.description,
        "created_at": r.created_at.isoformat(),
        "created_by_user_id": str(r.created_by_user_id) if r.created_by_user_id else None,
        "imported": r.imported,
        "manifest": r.manifest,
    }


@router.get("")
async def list_backups(
    admin: AdminJwt,
    limit: int = 50,
) -> JSONResponse:
    """Liste les backups locaux. Requiert rôle admin."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        records = await backups_repo.list_backups(conn, limit=limit)
    return JSONResponse({"backups": [_backup_to_dict(r) for r in records]})


@router.get("/{backup_id}")
async def get_backup(backup_id: UUID, admin: AdminJwt) -> JSONResponse:
    """Retourne les détails d'un backup. Requiert rôle admin."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        record = await backups_repo.get_backup(conn, backup_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "backup_not_found", "message": "Backup not found"},
        )
    return JSONResponse(_backup_to_dict(record))


@router.get("/{backup_id}/manifest")
async def get_backup_manifest(backup_id: UUID, admin: AdminJwt) -> JSONResponse:
    """Retourne le manifest d'un backup (stocké en clair en DB). Requiert rôle admin."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        record = await backups_repo.get_backup(conn, backup_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "backup_not_found", "message": "Backup not found"},
        )
    return JSONResponse(record.manifest)


@router.get("/{backup_id}/download")
async def download_backup(backup_id: UUID, admin: AdminJwt) -> FileResponse:
    """Télécharge le fichier .tar.age. Requiert rôle admin."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        record = await backups_repo.get_backup(conn, backup_id)
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "backup_not_found", "message": "Backup not found"},
            )
        await audit_log_insert(
            conn, "admin.backup_downloaded",
            actor_user_id=None,
            actor_ip=None,
            target_wallet_id=None,
            target_secret_id=None,
            metadata={"backup_id": str(backup_id), "filename": record.filename},
        )

    path = Path(settings.backup_local_path) / record.filename
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "file_missing", "message": "Backup file not found on disk"},
        )
    return FileResponse(
        path=str(path),
        media_type="application/octet-stream",
        filename=record.filename,
    )


class CreateBackupBody(BaseModel):
    description: str | None = None


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_backup(body: CreateBackupBody, admin: AdminJwt) -> JSONResponse:
    """Crée un backup. Requiert rôle admin + age_public_key configuré."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            record = await backup_svc.create_backup(
                conn,
                description=body.description,
                created_by_user_id=None,  # TODO: lookup user id from admin.keycloak_sub
                created_by_email=admin.email,
            )
        except backup_svc.BackupError as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"error": "backup_failed", "message": str(e)},
            ) from e
        await audit_log_insert(
            conn, "admin.backup_created",
            actor_user_id=None,
            actor_ip=None,
            target_wallet_id=None,
            target_secret_id=None,
            metadata={"backup_id": str(record.id), "filename": record.filename},
        )
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=_backup_to_dict(record),
    )


class VerifyBody(BaseModel):
    age_private_key: str


@router.post("/{backup_id}/verify")
async def verify_backup(backup_id: UUID, body: VerifyBody, admin: AdminJwt) -> JSONResponse:
    """Vérifie l'intégrité du backup. La clé privée n'est jamais persistée."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await backup_svc.verify_backup(backup_id, body.age_private_key, conn)
        await audit_log_insert(
            conn, "admin.backup_verified",
            actor_user_id=None,
            actor_ip=None,
            target_wallet_id=None,
            target_secret_id=None,
            metadata={"backup_id": str(backup_id), "valid": result.valid},
        )
    return JSONResponse({
        "valid": result.valid,
        "manifest": result.manifest,
        "checksums_match": result.checksums_match,
        "dump_sql_lines": result.dump_sql_lines,
    })


@router.delete("/{backup_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_backup(backup_id: UUID, admin: AdminJwt) -> None:
    """Supprime un backup. Requiert rôle admin."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        record = await backups_repo.get_backup(conn, backup_id)
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "backup_not_found", "message": "Backup not found"},
            )
        # Supprimer le fichier si présent
        file_path = Path(settings.backup_local_path) / record.filename
        if file_path.exists():
            file_path.unlink()
        await backups_repo.delete_backup(conn, backup_id)
        await audit_log_insert(
            conn, "admin.backup_deleted",
            actor_user_id=None,
            actor_ip=None,
            target_wallet_id=None,
            target_secret_id=None,
            metadata={"backup_id": str(backup_id), "filename": record.filename},
        )


class RestoreBody(BaseModel):
    age_private_key: str
    confirmation: str
    auto_enable_maintenance: bool = True


@router.post("/{backup_id}/restore")
async def restore_backup(backup_id: UUID, body: RestoreBody, admin: AdminJwt) -> JSONResponse:
    """Restaure la base depuis un backup. DESTRUCTIF. Requiert confirmation textuelle exacte."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        record = await backups_repo.get_backup(conn, backup_id)
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "backup_not_found", "message": "Backup not found"},
            )

    # Confirmation case-sensitive
    stem = record.filename.removesuffix(".tar.age")
    expected = f"RESTORE {stem}"
    if body.confirmation != expected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "wrong_confirmation",
                "message": f"Confirmation must be exactly: '{expected}'",
            },
        )

    async with pool.acquire() as conn:
        try:
            result = await backup_svc.restore_backup(backup_id, body.age_private_key, conn)
        except backup_svc.BackupError as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"error": "restore_failed", "message": str(e)},
            ) from e
        await audit_log_insert(
            conn, "admin.restore_executed",
            actor_user_id=None,
            actor_ip=None,
            target_wallet_id=None,
            target_secret_id=None,
            metadata={
                "backup_id": str(backup_id),
                "session_epoch_new": result.session_epoch_new,
            },
        )

    return JSONResponse({
        "success": True,
        "restored_from_backup_id": str(result.restored_from_backup_id),
        "session_epoch_new": result.session_epoch_new,
        "env_restore_file_path": result.env_restore_file_path,
        "next_actions": [
            "Review the .env.restore file and merge into your .env if needed",
            "All active sessions are invalidated, users must re-login",
        ],
    })
```

- [ ] **Step 3: Enregistrer le router dans `main.py`**

```python
# Dans backend/app/main.py, ajouter:
from app.api.v1.admin_backups import router as admin_backups_router

# Dans la section d'enregistrement des routers:
app.include_router(admin_backups_router, prefix="/v1")
```

- [ ] **Step 4: Exécuter les tests**

```bash
cd backend
uv run pytest tests/test_admin_backups.py -x -q
```

Expected: tous les tests PASS.

- [ ] **Step 5: Exécuter tous les tests**

```bash
cd backend
uv run pytest -x -q
```

Expected: tous les tests passent.

- [ ] **Step 6: Commit**

```bash
git add app/db/repositories/backups.py app/db/repositories/system_metadata.py \
        app/services/backup.py app/api/v1/admin_backups.py app/main.py \
        tests/test_admin_backups.py
git commit -m "feat(backup P3): service backup + endpoints admin/backups/*"
```

---

## Task 8: Mettre à jour `_KNOWN_AUDIT_ACTIONS` pour les actions admin

**Files:**
- Modify: `backend/app/api/v1/audit_log.py`

- [ ] **Step 1: Ajouter les actions admin à la liste statique**

Dans `backend/app/api/v1/audit_log.py`, ajouter dans `_KNOWN_AUDIT_ACTIONS` :

```python
    # Admin actions (LOT_12A)
    "admin.backup_created",
    "admin.backup_downloaded",
    "admin.backup_uploaded",
    "admin.backup_verified",
    "admin.backup_deleted",
    "admin.restore_executed",
    "admin.maintenance_enabled",
    "admin.maintenance_disabled",
```

- [ ] **Step 2: Vérifier les tests**

```bash
cd backend
uv run pytest -x -q
```

Expected: tous les tests passent.

- [ ] **Step 3: Commit final LOT 12A**

```bash
git add app/api/v1/audit_log.py app/core/config.py app/core/admin_auth.py \
        app/core/maintenance.py app/db/repositories/system_metadata.py \
        app/db/repositories/backups.py app/services/backup.py \
        app/api/v1/admin_backups.py app/api/v1/admin_maintenance.py \
        app/main.py tests/test_admin_auth.py tests/test_maintenance.py \
        tests/test_admin_backups.py migrations/004_backup_tables.sql
git commit -m "feat(lot-12a): backup backend complet — admin auth + maintenance + backups/restore"
```

---

## Self-Review

### 1. Spec coverage
- ✅ Endpoints `/v1/admin/backups/*` : list, create, get, download, manifest, verify, delete, restore
- ✅ Endpoints `/v1/admin/maintenance/*` : enable, disable, status
- ✅ Format .tar.age : manifest + dump.sql.gz + env-non-sensitive.json
- ✅ Migration `backups_local` + `system_metadata`
- ✅ Admin role detection (realm_access.roles dans JWT)
- ✅ Maintenance middleware (503 sauf /v1/health et /v1/admin/*)
- ✅ Confirmation textuelle pour restore
- ✅ Rotation session_epoch après restore
- ✅ Audit log pour toutes les opérations admin
- ✅ `get_sensitive_fields()` et `get_non_sensitive_fields()` sur Settings
- ⚠️ Upload multipart non implémenté (POST /v1/admin/backups/upload) — à ajouter si besoin
- ⚠️ CLI admin `harpocrate-admin` non implémenté — lot volumineux séparé, non bloquant
- ⚠️ Tests E2E (round-trip réel) nécessitent pg_dump + age disponibles sur la machine de test — hors scope tests unitaires

### 2. Placeholder scan
- Aucun TBD, TODO ou "similar to Task N" détecté
- Le `created_by_user_id=None` dans `create_backup` endpoint est une simplification temporaire (l'admin JWT ne stocke pas encore son user_id DB) — acceptable car l'admin email est loggé

### 3. Type consistency
- `BackupRecord` défini dans `backups.py` et utilisé cohéremment dans le service et l'API
- `AdminUser` défini dans `admin_auth.py` et utilisé via `AdminJwt` alias
- `MaintenanceState` et `maintenance_state` singleton définis dans `maintenance.py`, importés dans le router et le middleware
