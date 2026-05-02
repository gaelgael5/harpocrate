# LOT_00 — Foundations — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Poser le squelette backend Harpocrate selon `docs/specs/LOT_00_FOUNDATIONS.md` : structure FastAPI cible, config validée avec floors, healthcheck, endpoints `/v1/config/*`, migrations versionnées, Docker, tests TDD.

**Architecture:** Réécriture complète de `backend/src/harpocrate/` → `backend/app/` selon la spec. Pyproject strict (mypy + ruff), env prefix `HARPOCRATE_*`, validation Pydantic v2 des floors KDF/RSA au démarrage, pool asyncpg dans le lifespan FastAPI, structlog JSON.

**Tech Stack:** Python 3.12 / FastAPI / asyncpg / Pydantic v2 / pydantic-settings / structlog / pytest / ruff / mypy / Docker / PostgreSQL 16.

**Référence spec:** `docs/specs/LOT_00_FOUNDATIONS.md` — toutes les sections de code y sont reprises ci-dessous, sans réécriture libre.

---

## Pré-requis avant le premier commit

- [ ] Le LXC 202 (`harpocrate-test`, IP `192.168.10.123`) tourne avec Docker + Postgres + Alloy.
- [ ] Le `docker-compose.yml` actuel (mode dev avec build) ne sera **pas** utilisé pour ce lot — il sera réécrit en Task 11. Garder en mémoire que les artefacts CI/CD (Dockerfiles, workflow GitHub, deploy.sh, refresh.sh) sont conservés mais leur contenu sera ajusté ici.
- [ ] Les tâches utilisent `pytest`, `ruff`, `mypy`, `docker compose` — toutes lancées depuis `backend/` (sauf compose qui est à la racine).

---

## Task 1: Cleanup et bootstrap du nouveau backend

**Files:**
- Delete: `backend/src/harpocrate/` (toute l'ancienne arborescence)
- Delete: `backend/pyproject.toml` (sera réécrit)
- Delete: `backend/.dockerignore` (sera réécrit)
- Create: `backend/app/__init__.py` (vide)
- Create: `backend/app/main.py` (placeholder, sera rempli en Task 8)
- Create: `backend/pyproject.toml`
- Create: `backend/ruff.toml`
- Create: `backend/mypy.ini`
- Create: `backend/.dockerignore`
- Create: `backend/.gitignore`

- [ ] **Step 1: Supprimer l'ancien squelette**

```bash
rm -rf backend/src
rm -f backend/pyproject.toml backend/.dockerignore
```

- [ ] **Step 2: Créer la structure cible (dossiers vides)**

```bash
mkdir -p backend/app/{core,db,api/v1,models,services,crypto}
mkdir -p backend/migrations backend/tests
touch backend/app/__init__.py
touch backend/app/core/__init__.py backend/app/db/__init__.py
touch backend/app/api/__init__.py backend/app/api/v1/__init__.py
touch backend/app/models/__init__.py backend/app/services/__init__.py
touch backend/app/crypto/__init__.py
touch backend/tests/__init__.py
```

- [ ] **Step 3: Écrire `backend/pyproject.toml`**

```toml
[project]
name = "harpocrate"
version = "0.1.0"
description = "Harpocrate — gestionnaire de secrets E2E zero-knowledge"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
    "pydantic>=2.6",
    "pydantic-settings>=2.2",
    "asyncpg>=0.29",
    "structlog>=24.1",
    "python-json-logger>=2.0",
    "httpx>=0.27",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "ruff>=0.3",
    "mypy>=1.9",
    "pre-commit>=3.6",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["app"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 4: Écrire `backend/ruff.toml`**

```toml
line-length = 100
target-version = "py312"

[lint]
select = ["E", "F", "I", "B", "N", "UP", "SIM", "RUF"]
```

- [ ] **Step 5: Écrire `backend/mypy.ini`**

```ini
[mypy]
strict = True
python_version = 3.12
plugins = pydantic.mypy

[mypy-asyncpg.*]
ignore_missing_imports = True
```

- [ ] **Step 6: Écrire `backend/.dockerignore`**

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
.mypy_cache/
tests/
```

- [ ] **Step 7: Écrire `backend/.gitignore`**

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
.mypy_cache/
.coverage
htmlcov/
```

- [ ] **Step 8: Vérifier la syntaxe pyproject.toml**

Run: `cd backend && python -c "import tomllib; tomllib.load(open('pyproject.toml','rb'))" && echo OK`
Expected: `OK`

- [ ] **Step 9: Commit**

```bash
git add backend/
git commit -m "chore(backend): bootstrap structure app/ alignee sur LOT_00"
```

---

## Task 2: `app/core/config.py` — Settings Pydantic avec validation des floors

**Files:**
- Create: `backend/app/core/config.py`
- Create: `backend/tests/test_config.py`

- [ ] **Step 1: Écrire le test rouge `tests/test_config.py`**

```python
"""Tests pour app.core.config — validation des floors KDF/RSA/HMAC."""
from __future__ import annotations

import base64
import os
from collections.abc import Iterator

import pytest
from pydantic import ValidationError


@pytest.fixture
def base_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Variables d'env minimales pour instancier Settings."""
    hmac_key = base64.b64encode(b"x" * 32).decode()
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "harpocrate")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "harpocrate-vault")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", hmac_key)
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://test.local")
    yield


def test_settings_loads_with_minimal_env(base_env: None) -> None:
    from app.core.config import Settings

    s = Settings()  # type: ignore[call-arg]
    assert s.kdf_memory_kb == 65536
    assert s.kdf_iterations == 3
    assert s.kdf_parallelism == 4
    assert s.rsa_key_size_min == 2048
    assert s.passphrase_length_min == 12


def test_settings_rejects_low_kdf_memory(
    base_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("HARPOCRATE_KDF_MEMORY_KB", "10000")
    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


def test_settings_rejects_low_kdf_iterations(
    base_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("HARPOCRATE_KDF_ITERATIONS", "1")
    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


def test_settings_rejects_invalid_hmac_format(
    base_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", "not-base64-!!!")
    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


def test_settings_rejects_short_hmac_key(
    base_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import Settings

    short = base64.b64encode(b"x" * 16).decode()
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", short)
    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


def test_settings_rejects_wrong_rsa_size(
    base_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("HARPOCRATE_RSA_KEY_SIZE_MIN", "1024")
    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


def test_settings_accepts_rsa_4096(
    base_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("HARPOCRATE_RSA_KEY_SIZE_MIN", "4096")
    s = Settings()  # type: ignore[call-arg]
    assert s.rsa_key_size_min == 4096
```

- [ ] **Step 2: Run et vérifier que les tests échouent (module manquant)**

Run: `cd backend && python -m pytest tests/test_config.py -v`
Expected: échec avec `ModuleNotFoundError: No module named 'app.core.config'`

- [ ] **Step 3: Écrire `app/core/config.py`**

```python
"""Settings Pydantic — validation des floors crypto au démarrage."""
from __future__ import annotations

import base64

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HARPOCRATE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    db_dsn: str
    keycloak_url: str
    keycloak_realm: str
    keycloak_client_id: str
    hmac_key: str

    kdf_memory_kb: int = Field(default=65536, ge=65536)
    kdf_iterations: int = Field(default=3, ge=3)
    kdf_parallelism: int = Field(default=4, ge=4)
    rsa_key_size_min: int = Field(default=2048)
    passphrase_length_min: int = Field(default=12, ge=12)

    wallet_key_cache_ttl_seconds: int = 600
    api_key_validation_cache_ttl_seconds: int = 60
    audit_retention_days: int = 90

    public_url: str
    log_level: str = "INFO"

    @field_validator("rsa_key_size_min")
    @classmethod
    def _validate_rsa(cls, v: int) -> int:
        if v not in (2048, 4096):
            raise ValueError("RSA key size must be 2048 or 4096")
        return v

    @field_validator("hmac_key")
    @classmethod
    def _validate_hmac(cls, v: str) -> str:
        try:
            decoded = base64.b64decode(v, validate=True)
        except Exception as e:
            raise ValueError(f"hmac_key must be base64 encoded: {e}") from e
        if len(decoded) != 32:
            raise ValueError("hmac_key must be 32 bytes when decoded")
        return v


settings = Settings()  # type: ignore[call-arg]
```

- [ ] **Step 4: Run les tests, ils doivent passer**

Run: `cd backend && python -m pytest tests/test_config.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/config.py backend/tests/test_config.py
git commit -m "feat(config): Settings Pydantic + validation floors KDF/RSA/HMAC"
```

---

## Task 3: `app/core/logging.py` — structlog JSON

**Files:**
- Create: `backend/app/core/logging.py`
- Create: `backend/tests/test_logging.py`

- [ ] **Step 1: Test rouge — la conf doit produire du JSON**

```python
"""Tests structlog JSON setup."""
from __future__ import annotations

import json
import logging
from io import StringIO

import pytest


def test_configure_logging_emits_json(
    monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    import base64
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "harpocrate")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "x")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")

    from app.core.logging import configure_logging, logger

    configure_logging()
    logger.info("event_test", foo="bar")

    out, _ = capfd.readouterr()
    line = out.strip().splitlines()[-1]
    parsed = json.loads(line)
    assert parsed["event"] == "event_test"
    assert parsed["foo"] == "bar"
    assert "timestamp" in parsed
```

- [ ] **Step 2: Run, vérifier l'échec**

Run: `cd backend && python -m pytest tests/test_logging.py -v`
Expected: `ModuleNotFoundError: No module named 'app.core.logging'`

- [ ] **Step 3: Écrire `app/core/logging.py`**

```python
"""Logging structlog JSON. Aucune valeur sensible loggée — règle de l'OVERVIEW §14."""
from __future__ import annotations

import logging
import sys

import structlog

from app.core.config import settings


def configure_logging() -> None:
    logging.basicConfig(
        level=settings.log_level,
        format="%(message)s",
        stream=sys.stdout,
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level)
        ),
        cache_logger_on_first_use=True,
    )


logger = structlog.get_logger()
```

- [ ] **Step 4: Run, doit passer**

Run: `cd backend && python -m pytest tests/test_logging.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/logging.py backend/tests/test_logging.py
git commit -m "feat(logging): structlog JSON sur stdout"
```

---

## Task 4: `app/db/pool.py` — pool asyncpg

**Files:**
- Create: `backend/app/db/pool.py`
- Create: `backend/tests/test_pool.py`

- [ ] **Step 1: Test rouge**

```python
"""Tests pool asyncpg — initialisation, fermeture, double-init idempotent."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    import base64
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "h")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "x")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")


async def test_init_pool_creates_pool() -> None:
    fake_pool = AsyncMock()
    with patch("asyncpg.create_pool", return_value=fake_pool) as create:
        from app.db import pool as pool_mod

        pool_mod._pool = None
        result = await pool_mod.init_pool()
        assert result is fake_pool
        create.assert_called_once()


async def test_init_pool_is_idempotent() -> None:
    fake_pool = AsyncMock()
    with patch("asyncpg.create_pool", return_value=fake_pool) as create:
        from app.db import pool as pool_mod

        pool_mod._pool = None
        await pool_mod.init_pool()
        await pool_mod.init_pool()
        create.assert_called_once()


async def test_close_pool_clears_state() -> None:
    fake_pool = AsyncMock()
    with patch("asyncpg.create_pool", return_value=fake_pool):
        from app.db import pool as pool_mod

        pool_mod._pool = None
        await pool_mod.init_pool()
        await pool_mod.close_pool()
        assert pool_mod._pool is None


async def test_get_pool_raises_if_not_initialized() -> None:
    from app.db import pool as pool_mod

    pool_mod._pool = None
    with pytest.raises(RuntimeError, match="not initialized"):
        await pool_mod.get_pool()
```

- [ ] **Step 2: Run, échec attendu**

Run: `cd backend && python -m pytest tests/test_pool.py -v`
Expected: échec

- [ ] **Step 3: Écrire `app/db/pool.py`**

```python
"""Pool asyncpg — initialisé dans le lifespan FastAPI (cf app/main.py)."""
from __future__ import annotations

import asyncpg

from app.core.config import settings
from app.core.logging import logger

_pool: asyncpg.Pool | None = None


async def init_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=settings.db_dsn,
            min_size=2,
            max_size=10,
            command_timeout=30,
        )
        logger.info("db_pool_initialized")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("db_pool_closed")


async def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialized")
    return _pool
```

- [ ] **Step 4: Run, ça passe**

Run: `cd backend && python -m pytest tests/test_pool.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/pool.py backend/tests/test_pool.py
git commit -m "feat(db): pool asyncpg avec init/close/get idempotents"
```

---

## Task 5: `app/api/v1/health.py` — endpoint /v1/health

**Files:**
- Create: `backend/app/api/v1/health.py`
- Create: `backend/tests/test_health.py`

- [ ] **Step 1: Test rouge — 200 si DB up, 503 si DB down**

```python
"""Tests endpoint /v1/health."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    import base64
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "h")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "x")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")


def _client_with_pool(pool_mock: AsyncMock) -> TestClient:
    from app.main import app
    from app.db import pool as pool_mod

    pool_mod._pool = pool_mock
    return TestClient(app)


def test_health_ok_when_db_responds() -> None:
    fake_conn = AsyncMock()
    fake_conn.fetchval = AsyncMock(return_value=1)
    fake_pool = AsyncMock()
    fake_pool.acquire.return_value.__aenter__.return_value = fake_conn

    client = _client_with_pool(fake_pool)
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": "0.1.0", "db": "ok"}


def test_health_degraded_when_db_unreachable() -> None:
    fake_pool = AsyncMock()
    fake_pool.acquire.side_effect = OSError("connection refused")

    client = _client_with_pool(fake_pool)
    r = client.get("/v1/health")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded"
    assert body["db"] == "unreachable"
```

- [ ] **Step 2: Run, échec attendu**

Run: `cd backend && python -m pytest tests/test_health.py -v`
Expected: ModuleNotFoundError ou import error

- [ ] **Step 3: Écrire `app/api/v1/health.py`**

```python
"""Endpoint /v1/health — pingue le pool asyncpg."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.db.pool import get_pool

router = APIRouter()

_VERSION = "0.1.0"


@router.get("/health")
async def health() -> JSONResponse:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
    except Exception:  # noqa: BLE001 — healthcheck doit attraper tout
        return JSONResponse(
            {"status": "degraded", "version": _VERSION, "db": "unreachable"},
            status_code=503,
        )
    return JSONResponse(
        {"status": "ok", "version": _VERSION, "db": "ok"},
        status_code=200,
    )
```

- [ ] **Step 4: Run, ça passe (après Task 8 qui crée `app/main.py` complet)**

Note : ce test importe `app.main` qui sera complété en Task 8. Si Task 8 n'est pas encore faite, écrire un `app/main.py` minimal :

```python
"""Placeholder, sera complété en Task 8."""
from fastapi import FastAPI
from app.api.v1 import health

app = FastAPI(title="Harpocrate", version="0.1.0")
app.include_router(health.router, prefix="/v1")
```

Run: `cd backend && python -m pytest tests/test_health.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/health.py backend/app/main.py backend/tests/test_health.py
git commit -m "feat(api): GET /v1/health avec ping DB"
```

---

## Task 6: `app/api/v1/config_public.py` — endpoint /v1/config/public

**Files:**
- Create: `backend/app/api/v1/config_public.py`
- Create: `backend/tests/test_config_public.py`

- [ ] **Step 1: Test rouge**

```python
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    import base64
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "h")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "x")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")


def test_config_public_returns_floors() -> None:
    from app.main import app

    client = TestClient(app)
    r = client.get("/v1/config/public")
    assert r.status_code == 200
    body = r.json()
    assert body["kdf_floors"] == {
        "memory_kb": 65536,
        "iterations": 3,
        "parallelism": 4,
    }
    assert body["rsa_minimum_key_size"] == 2048
    assert body["passphrase_minimum_length"] == 12
    assert body["audit_retention_days"] == 90
    assert body["version"] == "0.1.0"
    assert "random" in body["supported_generators"]
    assert "rsa_keypair" in body["supported_generators"]
```

- [ ] **Step 2: Run, échec attendu**

Run: `cd backend && python -m pytest tests/test_config_public.py -v`
Expected: 404 (route non encore ajoutée)

- [ ] **Step 3: Écrire `app/api/v1/config_public.py`**

```python
"""Endpoint /v1/config/public — expose les floors et le catalogue de générateurs."""
from __future__ import annotations

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()

_VERSION = "0.1.0"
_SUPPORTED_GENERATORS: list[str] = [
    "random",
    "uuid",
    "bytes",
    "passphrase",
    "rsa_keypair",
    "ssh_keypair",
    "tls_certificate",
    "bcrypt_password",
    "template",
]


@router.get("/config/public")
async def config_public() -> dict[str, object]:
    return {
        "kdf_floors": {
            "memory_kb": settings.kdf_memory_kb,
            "iterations": settings.kdf_iterations,
            "parallelism": settings.kdf_parallelism,
        },
        "rsa_minimum_key_size": settings.rsa_key_size_min,
        "passphrase_minimum_length": settings.passphrase_length_min,
        "supported_generators": _SUPPORTED_GENERATORS,
        "audit_retention_days": settings.audit_retention_days,
        "version": _VERSION,
    }
```

- [ ] **Step 4: Brancher la route dans `app/main.py`**

Modifier `backend/app/main.py` pour inclure la route :

```python
from app.api.v1 import health, config_public  # ligne d'import

app.include_router(config_public.router, prefix="/v1")
```

- [ ] **Step 5: Run, ça passe**

Run: `cd backend && python -m pytest tests/test_config_public.py -v`
Expected: 1 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/v1/config_public.py backend/app/main.py backend/tests/test_config_public.py
git commit -m "feat(api): GET /v1/config/public — floors et generateurs"
```

---

## Task 7: `app/api/v1/config_keycloak.py` — endpoint /v1/config/keycloak

**Files:**
- Create: `backend/app/api/v1/config_keycloak.py`
- Create: `backend/tests/test_config_keycloak.py`

- [ ] **Step 1: Test rouge**

```python
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    import base64
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://keycloak.yoops.org")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "harpocrate")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "harpocrate-vault")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")


def test_config_keycloak_exposes_realm_and_urls() -> None:
    from app.main import app

    client = TestClient(app)
    r = client.get("/v1/config/keycloak")
    assert r.status_code == 200
    body = r.json()
    assert body["realm"] == "harpocrate"
    assert body["client_id"] == "harpocrate-vault"
    assert body["auth_url"] == "https://keycloak.yoops.org/realms/harpocrate"
    assert body["token_url"].endswith("/protocol/openid-connect/token")
    assert body["jwks_url"].endswith("/protocol/openid-connect/certs")
    assert body["issuer"] == body["auth_url"]
```

- [ ] **Step 2: Run, échec attendu**

Run: `cd backend && python -m pytest tests/test_config_keycloak.py -v`
Expected: 404

- [ ] **Step 3: Écrire `app/api/v1/config_keycloak.py`**

```python
"""Endpoint /v1/config/keycloak — exposé sans auth pour le frontend OIDC."""
from __future__ import annotations

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()


@router.get("/config/keycloak")
async def config_keycloak() -> dict[str, str]:
    base = f"{settings.keycloak_url.rstrip('/')}/realms/{settings.keycloak_realm}"
    return {
        "realm": settings.keycloak_realm,
        "client_id": settings.keycloak_client_id,
        "auth_url": base,
        "token_url": f"{base}/protocol/openid-connect/token",
        "jwks_url": f"{base}/protocol/openid-connect/certs",
        "issuer": base,
    }
```

- [ ] **Step 4: Brancher la route**

Ajouter dans `app/main.py` :
```python
from app.api.v1 import health, config_public, config_keycloak

app.include_router(config_keycloak.router, prefix="/v1")
```

- [ ] **Step 5: Run, ça passe**

Run: `cd backend && python -m pytest tests/test_config_keycloak.py -v`
Expected: 1 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/v1/config_keycloak.py backend/app/main.py backend/tests/test_config_keycloak.py
git commit -m "feat(api): GET /v1/config/keycloak"
```

---

## Task 8: `app/main.py` — assemblage final + lifespan

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Réécrire `app/main.py` complet**

```python
"""FastAPI app — lifespan gère le pool asyncpg."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1 import config_keycloak, config_public, health
from app.core.config import settings
from app.core.logging import configure_logging, logger
from app.db.pool import close_pool, init_pool

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info(
        "starting",
        version="0.1.0",
        public_url=settings.public_url,
    )
    await init_pool()
    try:
        yield
    finally:
        await close_pool()
        logger.info("stopped")


app = FastAPI(
    title="Harpocrate",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router, prefix="/v1")
app.include_router(config_public.router, prefix="/v1")
app.include_router(config_keycloak.router, prefix="/v1")
```

- [ ] **Step 2: Vérifier que tous les tests passent**

Run: `cd backend && python -m pytest -v`
Expected: tous green (config 7 + logging 1 + pool 4 + health 2 + config_public 1 + config_keycloak 1 = 16 passed)

- [ ] **Step 3: Commit**

```bash
git add backend/app/main.py
git commit -m "feat(main): lifespan FastAPI avec pool asyncpg"
```

---

## Task 9: `migrations/000_migrations_table.sql` + apply_migrations.py

**Files:**
- Create: `backend/migrations/000_migrations_table.sql`
- Create: `backend/migrations/apply_migrations.py`
- Create: `backend/tests/test_apply_migrations.py`

- [ ] **Step 1: Test rouge**

```python
"""Tests apply_migrations — bootstrap, idempotence, checksum mismatch."""
from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    import base64
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "h")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "x")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")


async def test_apply_migrations_runs_bootstrap_and_pending(tmp_path: Path) -> None:
    # Stage : un dossier de migrations factice
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    bootstrap = mig_dir / "000_migrations_table.sql"
    bootstrap.write_text("CREATE TABLE _migrations (id INT);")
    pending = mig_dir / "001_first.sql"
    pending.write_text("SELECT 1;")

    fake_conn = AsyncMock()
    fake_conn.fetch = AsyncMock(return_value=[])
    fake_conn.execute = AsyncMock()
    fake_conn.transaction.return_value.__aenter__ = AsyncMock()
    fake_conn.transaction.return_value.__aexit__ = AsyncMock()

    with (
        patch("asyncpg.connect", return_value=fake_conn),
        patch("migrations.apply_migrations._migrations_dir", return_value=mig_dir),
    ):
        from migrations.apply_migrations import apply_migrations

        await apply_migrations()

    # Bootstrap exécuté + INSERT du fichier 001
    assert fake_conn.execute.call_count >= 2
```

Note : ce test isole l'arborescence migrations via `tmp_path`. Le test ne valide que le squelette ; le test E2E vrai est en Task 12.

- [ ] **Step 2: Run, échec attendu**

Run: `cd backend && python -m pytest tests/test_apply_migrations.py -v`
Expected: ModuleNotFoundError

- [ ] **Step 3: Écrire `migrations/000_migrations_table.sql`**

```sql
CREATE TABLE IF NOT EXISTS _migrations (
    id              SERIAL PRIMARY KEY,
    filename        TEXT NOT NULL UNIQUE,
    applied_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    checksum        TEXT NOT NULL
);
```

- [ ] **Step 4: Écrire `migrations/apply_migrations.py`**

```python
"""Apply pending SQL migrations to the database.

Usage: python -m migrations.apply_migrations
"""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import asyncpg

from app.core.config import settings


def _migrations_dir() -> Path:
    return Path(__file__).parent


async def apply_migrations() -> None:
    conn = await asyncpg.connect(dsn=settings.db_dsn)
    try:
        bootstrap = (_migrations_dir() / "000_migrations_table.sql").read_text()
        await conn.execute(bootstrap)

        applied = {
            row["filename"]: row["checksum"]
            for row in await conn.fetch(
                "SELECT filename, checksum FROM _migrations"
            )
        }

        files = sorted(
            f
            for f in _migrations_dir().glob("*.sql")
            if f.name != "000_migrations_table.sql"
        )

        for migration in files:
            content = migration.read_text()
            checksum = hashlib.sha256(content.encode()).hexdigest()

            if migration.name in applied:
                if applied[migration.name] != checksum:
                    raise RuntimeError(
                        f"Migration {migration.name} checksum mismatch — "
                        f"manual review required"
                    )
                continue

            print(f"Applying {migration.name}...")
            async with conn.transaction():
                await conn.execute(content)
                await conn.execute(
                    "INSERT INTO _migrations (filename, checksum) "
                    "VALUES ($1, $2)",
                    migration.name,
                    checksum,
                )

        print("Migrations up to date.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(apply_migrations())
```

- [ ] **Step 5: Créer `migrations/__init__.py` vide pour pouvoir l'importer**

```bash
touch backend/migrations/__init__.py
```

- [ ] **Step 6: Run, ça passe**

Run: `cd backend && python -m pytest tests/test_apply_migrations.py -v`
Expected: 1 passed

- [ ] **Step 7: Commit**

```bash
git add backend/migrations/ backend/tests/test_apply_migrations.py
git commit -m "feat(migrations): bootstrap _migrations + apply_migrations.py"
```

---

## Task 10: `Dockerfile` cible LOT_00

**Files:**
- Modify: `backend/Dockerfile`

- [ ] **Step 1: Réécrire `backend/Dockerfile` selon spec LOT_00**

```dockerfile
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir \
    "fastapi>=0.110" \
    "uvicorn[standard]>=0.27" \
    "pydantic>=2.6" \
    "pydantic-settings>=2.2" \
    "asyncpg>=0.29" \
    "structlog>=24.1" \
    "python-json-logger>=2.0" \
    "httpx>=0.27"

# ── Stage dev : bind-mount du code, reload activé ──────────────────────────
FROM base AS dev
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--reload", "--reload-dir", "/app/app"]

# ── Stage prod : code embarqué, user non-root ──────────────────────────────
FROM base AS prod
RUN useradd -r -u 1001 -m harpocrate
COPY app ./app
COPY migrations ./migrations
USER harpocrate
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Build l'image dev pour vérifier**

Run: `cd backend && docker build -t harpocrate-backend:test --target dev .`
Expected: build success, pas d'erreur

- [ ] **Step 3: Commit**

```bash
git add backend/Dockerfile
git commit -m "build(backend): Dockerfile multi-stage aligne sur LOT_00"
```

---

## Task 11: `docker-compose.yml` racine — version LOT_00

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Delete: `frontend/` (sera réécrit au LOT_11) — **OPTION** : voir note ci-dessous
- Modify: `db/init/01-extensions.sql` (déplacé sous `backend/migrations/` au LOT_01, mais on le garde ici pour ce lot)

**Note frontend** : la spec LOT_00 ne mentionne aucun frontend. Le squelette React actuel (shadcn/Tailwind) sera intégralement remplacé en LOT_11 (Mantine). Choix possible :
- **A.** Le supprimer maintenant pour ne pas porter de code mort.
- **B.** Le conserver comme smoke-test (curl `/v1/health` via UI).

Recommandation : **option A**. Rationale : pas de code mort, alignement strict avec la spec LOT_00, le LOT_11 fera la vraie UI. La présente Task écrit un compose backend-only.

- [ ] **Step 1: Supprimer le frontend actuel (option A)**

```bash
rm -rf frontend
```

- [ ] **Step 2: Réécrire `docker-compose.yml`**

```yaml
services:
  postgres:
    image: postgres:16-alpine
    container_name: harpocrate-postgres
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    ports:
      - "127.0.0.1:5432:5432"
    volumes:
      - ./data/postgres:/var/lib/postgresql/data
      - ./db/init:/docker-entrypoint-initdb.d:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s

  backend:
    build:
      context: ./backend
      target: dev
    image: harpocrate-backend:dev
    container_name: harpocrate-backend
    restart: unless-stopped
    environment:
      HARPOCRATE_DB_DSN: postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
      HARPOCRATE_KEYCLOAK_URL: ${HARPOCRATE_KEYCLOAK_URL}
      HARPOCRATE_KEYCLOAK_REALM: ${HARPOCRATE_KEYCLOAK_REALM}
      HARPOCRATE_KEYCLOAK_CLIENT_ID: ${HARPOCRATE_KEYCLOAK_CLIENT_ID}
      HARPOCRATE_HMAC_KEY: ${HARPOCRATE_HMAC_KEY}
      HARPOCRATE_PUBLIC_URL: ${HARPOCRATE_PUBLIC_URL}
      HARPOCRATE_LOG_LEVEL: ${HARPOCRATE_LOG_LEVEL:-INFO}
    depends_on:
      postgres:
        condition: service_healthy
    ports:
      - "127.0.0.1:8000:8000"
    volumes:
      - ./backend/app:/app/app
      - ./backend/migrations:/app/migrations
```

- [ ] **Step 3: Réécrire `.env.example`**

```
# Postgres
POSTGRES_USER=harpocrate
POSTGRES_PASSWORD=change-me-please
POSTGRES_DB=harpocrate

# Harpocrate backend
HARPOCRATE_KEYCLOAK_URL=https://keycloak.yoops.org
HARPOCRATE_KEYCLOAK_REALM=yoops
HARPOCRATE_KEYCLOAK_CLIENT_ID=harpocrate-vault
# Generer avec : python -c "import base64,os; print(base64.b64encode(os.urandom(32)).decode())"
HARPOCRATE_HMAC_KEY=REPLACE_WITH_BASE64_32_BYTES
HARPOCRATE_PUBLIC_URL=http://localhost:8000
HARPOCRATE_LOG_LEVEL=INFO
```

- [ ] **Step 4: Réécrire `deploy/docker-compose.yml` et `deploy/.env.example`**

`deploy/docker-compose.yml` — même structure mais `image:` au lieu de `build:` et pas de bind mount :

```yaml
services:
  postgres:
    image: postgres:16-alpine
    container_name: harpocrate-postgres
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    ports:
      - "127.0.0.1:5432:5432"
    volumes:
      - ./data/postgres:/var/lib/postgresql/data
      - ./db/init:/docker-entrypoint-initdb.d:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s

  backend:
    image: ghcr.io/gaelgael5/harpocrate-backend:${TAG:-latest}
    container_name: harpocrate-backend
    restart: unless-stopped
    environment:
      HARPOCRATE_DB_DSN: postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
      HARPOCRATE_KEYCLOAK_URL: ${HARPOCRATE_KEYCLOAK_URL}
      HARPOCRATE_KEYCLOAK_REALM: ${HARPOCRATE_KEYCLOAK_REALM}
      HARPOCRATE_KEYCLOAK_CLIENT_ID: ${HARPOCRATE_KEYCLOAK_CLIENT_ID}
      HARPOCRATE_HMAC_KEY: ${HARPOCRATE_HMAC_KEY}
      HARPOCRATE_PUBLIC_URL: ${HARPOCRATE_PUBLIC_URL}
      HARPOCRATE_LOG_LEVEL: ${HARPOCRATE_LOG_LEVEL:-INFO}
    depends_on:
      postgres:
        condition: service_healthy
    ports:
      - "127.0.0.1:8000:8000"
```

`deploy/.env.example` :
```
POSTGRES_USER=harpocrate
POSTGRES_PASSWORD=change-me-please
POSTGRES_DB=harpocrate

HARPOCRATE_KEYCLOAK_URL=https://keycloak.yoops.org
HARPOCRATE_KEYCLOAK_REALM=yoops
HARPOCRATE_KEYCLOAK_CLIENT_ID=harpocrate-vault
HARPOCRATE_HMAC_KEY=REPLACE_WITH_BASE64_32_BYTES
HARPOCRATE_PUBLIC_URL=https://vault.yoops.org
HARPOCRATE_LOG_LEVEL=INFO

TAG=latest
```

- [ ] **Step 5: Adapter le workflow GitHub Actions — supprimer le job frontend**

Modifier `.github/workflows/build-images.yml` pour ne build que le backend :

```yaml
name: build-images

on:
  push:
    branches: [main]
    tags: ['v*']
  workflow_dispatch:

jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - id: meta
        uses: docker/metadata-action@v5
        with:
          images: ghcr.io/${{ github.repository }}-backend
          tags: |
            type=ref,event=branch
            type=sha,format=short
            type=semver,pattern={{version}}
            type=raw,value=latest,enable={{is_default_branch}}
      - uses: docker/build-push-action@v6
        with:
          context: ./backend
          target: prod
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha,scope=backend
          cache-to: type=gha,mode=max,scope=backend
```

- [ ] **Step 6: Adapter `scripts/deploy.sh` — pas de copie frontend**

Le script actuel ne copie déjà que docker-compose + db/init + .env, donc rien à changer. Vérifier juste qu'il n'y a pas de référence frontend dans `scripts/refresh.sh` (il n'y en a pas, c'est un `docker compose pull` générique).

- [ ] **Step 7: Valider compose syntaxiquement**

Run depuis le repo :
```bash
ssh pve "pct exec 202 -- bash -c 'cd /tmp && cat > .env <<EOF
POSTGRES_USER=t
POSTGRES_PASSWORD=t
POSTGRES_DB=t
HARPOCRATE_KEYCLOAK_URL=https://k
HARPOCRATE_KEYCLOAK_REALM=h
HARPOCRATE_KEYCLOAK_CLIENT_ID=h
HARPOCRATE_HMAC_KEY=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
HARPOCRATE_PUBLIC_URL=https://t
EOF'"
scp docker-compose.yml deploy/docker-compose.yml pve:/tmp/
ssh pve "pct push 202 /tmp/docker-compose.yml /tmp/dc-dev.yml && pct push 202 /tmp/docker-compose.yml /tmp/dc-deploy.yml && pct exec 202 -- bash -c 'cd /tmp && docker compose -f dc-dev.yml config --quiet && docker compose -f dc-deploy.yml config --quiet && echo BOTH_OK'"
```
Expected: `BOTH_OK`

- [ ] **Step 8: Commit**

```bash
git add docker-compose.yml deploy/docker-compose.yml deploy/.env.example .env.example .github/workflows/build-images.yml
git rm -r frontend/
git commit -m "build: compose dev/deploy aligne sur LOT_00 + suppression squelette frontend"
```

---

## Task 12: Smoke test E2E — `docker compose up` + curls

**Files:**
- Create: `backend/README.md`

- [ ] **Step 1: Écrire `backend/README.md`**

```markdown
# Harpocrate — Backend

Voir `docs/specs/OVERVIEW.md` et `docs/specs/LOT_00_FOUNDATIONS.md`.

## Démarrer en local

1. Copier `.env.example` à la racine du repo en `.env`, remplir les variables.
2. Générer une `HARPOCRATE_HMAC_KEY` :
   ```bash
   python -c "import base64,os; print(base64.b64encode(os.urandom(32)).decode())"
   ```
3. Démarrer :
   ```bash
   docker compose up -d --build
   ```
4. Appliquer les migrations (depuis le container) :
   ```bash
   docker compose exec backend python -m migrations.apply_migrations
   ```
5. Tester :
   ```bash
   curl http://localhost:8000/v1/health
   curl http://localhost:8000/v1/config/public
   curl http://localhost:8000/v1/config/keycloak
   ```

## Tests

```bash
cd backend
pip install -e ".[dev]"
pytest -v
ruff check .
mypy --strict app/
```
```

- [ ] **Step 2: Démarrer en local et tester**

```bash
cp .env.example .env
# editer .env, remplir HARPOCRATE_HMAC_KEY notamment
docker compose up -d --build
sleep 10
curl -s http://localhost:8000/v1/health | jq .
curl -s http://localhost:8000/v1/config/public | jq .
curl -s http://localhost:8000/v1/config/keycloak | jq .
docker compose exec backend python -m migrations.apply_migrations
docker compose exec postgres psql -U harpocrate -d harpocrate -c "\dt"
# Doit lister _migrations
```

Expected:
- `/v1/health` → `{"status":"ok","version":"0.1.0","db":"ok"}`
- `/v1/config/public` → JSON avec `kdf_floors`, `supported_generators`
- `/v1/config/keycloak` → JSON avec `realm`, `auth_url`
- `\dt` montre `_migrations`

- [ ] **Step 3: Vérifier les logs JSON**

Run: `docker compose logs backend | tail -20`
Expected: lignes JSON avec `event`, `level`, `timestamp`

- [ ] **Step 4: Vérifier qu'un démarrage avec floor invalide échoue**

```bash
HARPOCRATE_KDF_MEMORY_KB=10000 docker compose up backend
```
Expected: container exit avec ValidationError

- [ ] **Step 5: Lint + typecheck final**

```bash
cd backend
ruff check .
mypy --strict app/
pytest -v
```
Expected: tout green, 0 erreur

- [ ] **Step 6: Commit final + tag**

```bash
git add backend/README.md
git commit -m "docs(backend): README LOT_00 (demarrage, tests, smoke)"
git tag lot-00-foundations-done
```

---

## Critères de succès du LOT_00

Reproduits de `docs/specs/LOT_00_FOUNDATIONS.md` :

1. ✅ `docker compose up --build` démarre backend + DB sans erreur
2. ✅ `curl http://localhost:8000/v1/health` → 200 + `{"status":"ok",...}`
3. ✅ `curl http://localhost:8000/v1/config/public` → JSON attendu
4. ✅ `python -m migrations.apply_migrations` crée la table `_migrations`
5. ✅ Démarrage avec `HARPOCRATE_KDF_MEMORY_KB=10000` → erreur claire au démarrage
6. ✅ Démarrage avec `HMAC_KEY` mal formaté → erreur explicite
7. ✅ Logs en JSON structuré sur stdout
8. ✅ `ruff check` et `mypy --strict app/` passent
9. ✅ `pytest tests/` passe (≥ 16 tests dans ce lot)

## Pièges connus (rappel spec)

- **`pydantic-settings` est un package séparé en v2.** Ne pas confondre avec pydantic v1.
- **`type: ignore[call-arg]` sur `Settings()`** : Pydantic Settings reçoit ses args de l'env, mypy strict s'en plaint sans cette annotation.
- **Le pool asyncpg doit être créé dans le lifespan**, pas au top-level du module — sinon fail si DB pas prête au boot.
- **uvicorn multi-workers** : pool par worker, c'est OK.
- **Healthcheck Postgres avec `depends_on: condition: service_healthy`** pour éviter les retries au boot.
- **`jq` requis** sur la machine qui fait les smoke tests.

## Ce qui suit

LOT_01 ajoute toutes les tables métier (users, wallets, secrets, grants, api_keys, audit_log) + triggers. Aucune API, validable via psql direct.
