# By-ID Secret Routes — P1 Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre l'accès individuel (GET/PUT/DELETE) aux secrets dont le nom contient des `/`, en exposant 3 nouvelles routes indexées par UUID au lieu du nom. Resserrer la validation du nom pour rejeter les paths malformés (trailing `/`).

**Architecture:** On laisse les routes existantes `/{name}` intactes (cohabitation, zéro breaking change pour les clients utilisant des noms simples). On ajoute en parallèle 3 routes `/by-id/{secret_id}` qui contournent le décodage `%2F → /` opéré par Cloudflare/Caddy sur les paths d'URL. La validation de nom passe d'un `ValueError` (que Pydantic mappe en 422) à une exception custom `InvalidSecretPath` (que FastAPI mappe en 400 propre via un handler global).

**Tech Stack:** FastAPI + Pydantic v2 + asyncpg + pytest + pytest-asyncio + httpx (ASGITransport pour les tests).

---

## File Structure

**Modifications :**

| Fichier | Responsabilité de la modification |
|---|---|
| `backend/app/services/secret_paths.py` | Ajout de la classe `InvalidSecretPath` ; resserrement de `validate_secret_name` (rejet trailing `/`) ; remplacement des `raise ValueError` par `raise InvalidSecretPath` |
| `backend/app/main.py` | Enregistrement d'un `@app.exception_handler(InvalidSecretPath)` qui retourne `JSONResponse(400, {"error": "invalid_secret_path", "message": str(exc)})` |
| `backend/app/api/v1/secrets.py` | Ajout des 3 routes `GET/PUT/DELETE /wallets/{wallet_id}/secrets/by-id/{secret_id}` |
| `backend/app/services/secrets.py` | Ajout des 3 fonctions service `get_secret_by_id`, `put_secret_by_id`, `delete_secret_by_id` (avec vérification d'appartenance au wallet) |
| `backend/tests/test_secret_paths.py` | Mise à jour des `pytest.raises(ValueError)` → `pytest.raises(InvalidSecretPath)` ; ajout du test trailing slash |

**Créations :**

| Fichier | Responsabilité |
|---|---|
| `backend/tests/test_invalid_secret_path_handler.py` | Test d'intégration : POST avec nom invalide retourne `400 {"error": "invalid_secret_path", ...}` (au lieu de 422 Pydantic) |
| `backend/tests/test_secrets_by_id.py` | Tests des 3 nouvelles routes by-id (happy path + permissions + cross-wallet protection + 404) |

---

## Task 1: Define `InvalidSecretPath` exception class

**Files:**
- Modify: `backend/app/services/secret_paths.py:1-10`
- Test: aucun test direct (la classe sera testée via Tasks 2 & 3 quand elle sera utilisée)

- [ ] **Step 1.1: Ajouter la classe d'exception en tête du module**

Ouvrir `backend/app/services/secret_paths.py` et ajouter immédiatement après les imports (après la ligne `import re`) :

```python
class InvalidSecretPath(Exception):
    """Levée quand un nom de secret ne respecte pas les règles de path.

    N'hérite PAS de ValueError pour ne pas être interceptée par les
    field_validator Pydantic (qui convertissent ValueError en 422).
    Mappée par un handler FastAPI global vers 400 invalid_secret_path.
    """
```

- [ ] **Step 1.2: Vérifier que le module s'importe toujours**

Run :
```bash
cd backend && uv run python -c "from app.services.secret_paths import InvalidSecretPath, validate_secret_name; print('OK')"
```
Expected output : `OK`

- [ ] **Step 1.3: Commit**

```bash
git add backend/app/services/secret_paths.py
git commit -m "feat(secrets): introduit l'exception InvalidSecretPath (préparatoire)"
```

---

## Task 2: Refactor `validate_secret_name` pour lever `InvalidSecretPath`

**Files:**
- Modify: `backend/app/services/secret_paths.py:11-44` (les 3 occurrences de `raise ValueError`)
- Modify: `backend/tests/test_secret_paths.py:195-212` (les 3 `pytest.raises(ValueError)`)

- [ ] **Step 2.1: Mettre à jour les tests existants en RED**

Dans `backend/tests/test_secret_paths.py`, remplacer **chaque** `pytest.raises(ValueError)` (lignes ~195, ~201, ~206, ~212) par `pytest.raises(InvalidSecretPath)`.

Et ajouter l'import en tête de fichier (à côté de la ligne 18) :
```python
from app.services.secret_paths import InvalidSecretPath, normalize_path, validate_secret_name
```

- [ ] **Step 2.2: Exécuter les tests modifiés → DOIVENT échouer**

Run :
```bash
cd backend && uv run pytest tests/test_secret_paths.py -v -k "double_slash or relative or invalid_segment or too_deep" 2>&1 | tail -20
```
Expected : 4 tests FAIL avec `Failed: DID NOT RAISE <class 'app.services.secret_paths.InvalidSecretPath'>` (parce que le validateur lève encore `ValueError`).

- [ ] **Step 2.3: Refactor le validateur pour lever `InvalidSecretPath`**

Dans `backend/app/services/secret_paths.py`, remplacer **chaque** `raise ValueError(` (3 occurrences dans `validate_secret_name`) par `raise InvalidSecretPath(`. Le contenu des messages reste identique.

Le fichier complet de la fonction `validate_secret_name` doit ressembler à :

```python
def validate_secret_name(name: str) -> str:
    """Valide et normalise un nom de secret (peut contenir des '/').

    - Sans '/' → doit matcher [A-Za-z0-9_.-] (env-var safe)
    - Avec '/' → '/' initial ajouté si absent, pas de '/' final

    Lève InvalidSecretPath si invalide.
    """
    if "/" not in name:
        if not _ROOT_NAME_RE.match(name):
            raise InvalidSecretPath(
                f"Invalid secret name '{name}': only [A-Za-z0-9_.-] allowed for root secrets"
            )
        return name

    normalized = name if name.startswith("/") else "/" + name

    if "//" in normalized:
        raise InvalidSecretPath("Empty path segments not allowed (found '//')")

    segments = [s for s in normalized.split("/") if s]

    if len(segments) > _MAX_DEPTH + 1:
        raise InvalidSecretPath(f"Path too deep (max {_MAX_DEPTH} levels, got {len(segments) - 1})")

    for seg in segments:
        if seg in (".", ".."):
            raise InvalidSecretPath("Relative path navigation not allowed ('.' or '..')")
        if not _SEGMENT_RE.match(seg):
            raise InvalidSecretPath(
                f"Invalid path segment '{seg}': only [a-zA-Z0-9@._-] allowed"
            )

    return normalized
```

- [ ] **Step 2.4: Tests doivent maintenant passer en GREEN**

Run :
```bash
cd backend && uv run pytest tests/test_secret_paths.py -v 2>&1 | tail -30
```
Expected : tous les tests `test_secret_paths.py` PASS (les 4 corrigés + les autres inchangés).

- [ ] **Step 2.5: Commit**

```bash
git add backend/app/services/secret_paths.py backend/tests/test_secret_paths.py
git commit -m "refactor(secrets): validate_secret_name lève InvalidSecretPath au lieu de ValueError"
```

---

## Task 3: Rejeter le `/` final dans `validate_secret_name`

**Files:**
- Modify: `backend/app/services/secret_paths.py:11-44`
- Test: `backend/tests/test_secret_paths.py` (ajout d'un nouveau test)

- [ ] **Step 3.1: Écrire le test rouge**

Dans `backend/tests/test_secret_paths.py`, ajouter à la fin de la section validation (après `test_too_deep` ou équivalent) :

```python
def test_validate_secret_name_rejects_trailing_slash():
    """Un nom qui finit par '/' est invalide (sinon il apparaît comme un dossier dans le tree)."""
    with pytest.raises(InvalidSecretPath, match="trailing"):
        validate_secret_name("/foo/bar/")


def test_validate_secret_name_rejects_trailing_slash_without_leading():
    """Même rejet pour les noms sans slash initial qui finissent par /."""
    with pytest.raises(InvalidSecretPath, match="trailing"):
        validate_secret_name("foo/bar/")
```

- [ ] **Step 3.2: Lancer le test → DOIT échouer**

Run :
```bash
cd backend && uv run pytest tests/test_secret_paths.py::test_validate_secret_name_rejects_trailing_slash tests/test_secret_paths.py::test_validate_secret_name_rejects_trailing_slash_without_leading -v
```
Expected : 2 tests FAIL avec `Failed: DID NOT RAISE`.

- [ ] **Step 3.3: Implémenter le rejet du trailing slash**

Dans `backend/app/services/secret_paths.py`, dans `validate_secret_name`, ajouter le check **immédiatement après** le calcul de `normalized` (avant le check `//`) :

```python
    normalized = name if name.startswith("/") else "/" + name

    if normalized.endswith("/"):
        raise InvalidSecretPath(
            f"Invalid secret name '{name}': trailing '/' not allowed"
        )

    if "//" in normalized:
        raise InvalidSecretPath("Empty path segments not allowed (found '//')")
```

- [ ] **Step 3.4: Tests doivent passer**

Run :
```bash
cd backend && uv run pytest tests/test_secret_paths.py -v 2>&1 | tail -10
```
Expected : tous les tests PASS, y compris les 2 nouveaux.

- [ ] **Step 3.5: Commit**

```bash
git add backend/app/services/secret_paths.py backend/tests/test_secret_paths.py
git commit -m "feat(secrets): rejette les noms de secret se terminant par '/'"
```

---

## Task 4: Handler FastAPI pour mapper `InvalidSecretPath` → 400

**Files:**
- Modify: `backend/app/main.py:1-10` (import) et autour de `app = FastAPI(...)`
- Test: `backend/tests/test_invalid_secret_path_handler.py` (nouveau)

- [ ] **Step 4.1: Écrire le test rouge (intégration via POST /secrets)**

Créer `backend/tests/test_invalid_secret_path_handler.py` :

```python
"""Vérifie que les noms de secret invalides retournent 400 invalid_secret_path
(et non 422 ValidationError de Pydantic)."""
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


def _make_pool() -> MagicMock:
    """Pool minimal — l'appel SQL n'arrivera jamais (rejet en validation)."""
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=FakeRecord({
        "id": _CALLER_ID, "keycloak_sub": "test-sub-001", "email": "alice@example.com",
        "display_name": "Alice", "rsa_public_key": b"x", "salt_passphrase": b"x" * 16,
        "salt_recovery": b"y" * 16, "encrypted_rsa_private_key": b"x",
        "encrypted_sym_key_by_pass": b"x", "encrypted_sym_key_by_recovery": b"x",
        "kdf_memory_kb": 65536, "kdf_iterations": 3, "kdf_parallelism": 4,
        "rsa_key_size": 2048, "created_at": _NOW, "updated_at": _NOW,
        "last_unlock_at": None,
    }))
    conn.fetch = AsyncMock(return_value=[])

    class _AcquireCtx:
        async def __aenter__(self) -> MagicMock: return conn
        async def __aexit__(self, *a: Any) -> None: pass

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_AcquireCtx())
    return pool


@pytest.mark.asyncio
async def test_post_secret_with_trailing_slash_returns_400_invalid_secret_path() -> None:
    from app.db import pool as pool_mod
    from app.main import app

    pool_mod._pool = _make_pool()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            f"/v1/wallets/{_WALLET_ID}/secrets",
            json={"name": "/foo/bar/", "encrypted_value": _FAKE_ENC_VALUE},
            headers={"Authorization": f"Bearer {make_jwt_token()}"},
        )

    assert r.status_code == 400, r.text
    body = r.json()
    assert body.get("error") == "invalid_secret_path"
    assert "trailing" in body.get("message", "").lower()


@pytest.mark.asyncio
async def test_post_secret_with_double_slash_returns_400_invalid_secret_path() -> None:
    from app.db import pool as pool_mod
    from app.main import app

    pool_mod._pool = _make_pool()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            f"/v1/wallets/{_WALLET_ID}/secrets",
            json={"name": "/foo//bar", "encrypted_value": _FAKE_ENC_VALUE},
            headers={"Authorization": f"Bearer {make_jwt_token()}"},
        )

    assert r.status_code == 400, r.text
    assert r.json().get("error") == "invalid_secret_path"
```

- [ ] **Step 4.2: Lancer les tests → DOIVENT échouer**

Run :
```bash
cd backend && uv run pytest tests/test_invalid_secret_path_handler.py -v
```
Expected : les 2 tests FAIL. Sans handler, FastAPI laisse remonter l'exception en 500, OU si Pydantic la wrap (peu probable car elle n'hérite pas de ValueError) en 422. Dans tous les cas ce n'est pas un 400 propre.

- [ ] **Step 4.3: Ajouter le handler dans `main.py`**

Dans `backend/app/main.py`, ajouter l'import en tête (après les imports existants) :
```python
from fastapi.responses import JSONResponse
from app.services.secret_paths import InvalidSecretPath
```

Puis, **immédiatement après** la ligne `app = FastAPI(...)` (après `lifespan=lifespan,)` autour de la ligne 91), ajouter :

```python
@app.exception_handler(InvalidSecretPath)
async def _invalid_secret_path_handler(_request: Request, exc: InvalidSecretPath) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"error": "invalid_secret_path", "message": str(exc)},
    )
```

- [ ] **Step 4.4: Tests doivent passer**

Run :
```bash
cd backend && uv run pytest tests/test_invalid_secret_path_handler.py -v
```
Expected : les 2 tests PASS.

Run aussi pour s'assurer qu'on n'a rien cassé :
```bash
cd backend && uv run pytest tests/test_secrets.py -v 2>&1 | tail -15
```
Expected : tous les tests existants PASS.

- [ ] **Step 4.5: Commit**

```bash
git add backend/app/main.py backend/tests/test_invalid_secret_path_handler.py
git commit -m "feat(secrets): handler FastAPI mappe InvalidSecretPath vers 400 invalid_secret_path"
```

---

## Task 5: Service `get_secret_by_id` avec vérif d'appartenance au wallet

**Files:**
- Modify: `backend/app/services/secrets.py` (ajout d'une nouvelle fonction)
- Test: aucun test direct ici (sera testé via Task 6 par l'endpoint HTTP)

- [ ] **Step 5.1: Ajouter la fonction service `get_secret_by_id`**

Dans `backend/app/services/secrets.py`, ajouter à la fin du fichier (après `get_descriptor`) :

```python
# ─── By-ID — get / put / delete avec vérif appartenance wallet ────────────────


async def get_secret_by_id(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    secret_id: UUID,
    caller_user_id: UUID,
    actor_ip: str | None,
) -> SecretDetailResponse:
    """Retourne le secret par son UUID. Vérifie qu'il appartient bien au wallet ciblé.

    404 si le secret n'existe pas OU appartient à un autre wallet (ne pas leak l'existence).
    """
    secret = await secrets_repo.get_secret_by_id(conn, secret_id=secret_id)
    if secret is None or secret.wallet_id != wallet_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "secret_not_found", "message": "Secret not found"},
        )

    if secret.is_placeholder:
        raise HTTPException(
            status_code=status.HTTP_424_FAILED_DEPENDENCY,
            detail={
                "error": "placeholder_value_missing",
                "message": "Secret has no value yet, populate it first.",
                "details": {
                    "name": secret.name,
                    "is_placeholder": True,
                    "generation_descriptor": secret.generation_descriptor,
                },
            },
        )

    enc_wallet_key_bytes = await secrets_repo.get_caller_encrypted_wallet_key(
        conn, wallet_id=wallet_id, user_id=caller_user_id
    )
    if enc_wallet_key_bytes is None:  # pragma: no cover — grant vérifié juste avant
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "grant_key_missing", "message": "Encrypted wallet key not found"},
        )

    await audit_log_insert(
        conn,
        "secret.read",
        actor_user_id=caller_user_id,
        actor_ip=actor_ip,
        target_wallet_id=wallet_id,
        target_secret_id=secret.id,
        metadata={"secret_name": secret.name, "access_via": "by_id"},
    )

    enc_value_b64 = base64.b64encode(secret.encrypted_value or b"").decode()
    enc_key_b64 = base64.b64encode(enc_wallet_key_bytes).decode()

    return SecretDetailResponse(
        id=secret.id,
        name=secret.name,
        encrypted_value=enc_value_b64,
        encrypted_wallet_key=enc_key_b64,
        description=secret.description,
        tags=sorted(secret.tags),
        is_placeholder=secret.is_placeholder,
        generation_version=secret.generation_version,
        type_uuid=secret.type_uuid,
        schema_version_uuid=secret.schema_version_uuid,
    )
```

- [ ] **Step 5.2: Vérifier que le module s'importe**

Run :
```bash
cd backend && uv run python -c "from app.services.secrets import get_secret_by_id; print('OK')"
```
Expected : `OK`

- [ ] **Step 5.3: Commit (préparatoire — pas encore d'endpoint)**

```bash
git add backend/app/services/secrets.py
git commit -m "feat(secrets): service get_secret_by_id avec vérif d'appartenance au wallet"
```

---

## Task 6: Route `GET /wallets/{wid}/secrets/by-id/{sid}`

**Files:**
- Modify: `backend/app/api/v1/secrets.py` (ajout d'une route)
- Test: `backend/tests/test_secrets_by_id.py` (nouveau)

- [ ] **Step 6.1: Créer le fichier de tests `test_secrets_by_id.py` avec le 1er test (happy path GET)**

Créer `backend/tests/test_secrets_by_id.py` :

```python
"""Tests des routes /v1/wallets/{wid}/secrets/by-id/{sid} — accès par UUID
pour les secrets dont le nom contient des '/' (path-style names).
"""
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
_OTHER_WALLET_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000099")
_SECRET_ID = uuid.UUID("dddddddd-0000-0000-0000-000000000001")

_PERM_ALL = 63
_PERM_READ_ONLY = 1
_PERM_NO_READ = 62

_FAKE_ENC_VALUE = b"fake_encrypted_secret_value"
_FAKE_ENC_KEY = b"fake_encrypted_wallet_key_for_caller"
_FAKE_ENC_VALUE_B64 = base64.b64encode(_FAKE_ENC_VALUE).decode()


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


def _fake_wallet_row(wallet_id: uuid.UUID = _WALLET_ID, permissions: int = _PERM_ALL) -> FakeRecord:
    return FakeRecord({
        "id": wallet_id, "name": "Test Wallet", "description": None,
        "owner_user_id": _CALLER_ID, "created_at": _NOW, "updated_at": _NOW,
        "my_permissions": permissions, "valued_secrets_count": 0,
        "placeholder_secrets_count": 0,
    })


def _fake_secret_row(
    *,
    secret_id: uuid.UUID = _SECRET_ID,
    wallet_id: uuid.UUID = _WALLET_ID,
    name: str = "/users/no_email/transcription/openai-whisper/api-1",
    is_placeholder: bool = False,
) -> FakeRecord:
    return FakeRecord({
        "id": secret_id, "wallet_id": wallet_id, "name": name,
        "description": None, "encrypted_value": _FAKE_ENC_VALUE,
        "is_placeholder": is_placeholder, "generation_version": 1,
        "generation_descriptor": None, "linked_secret_id": None,
        "created_at": _NOW, "updated_at": _NOW,
        "created_by_user_id": _CALLER_ID, "created_by_api_key_id": None,
        "updated_by_user_id": None, "updated_by_api_key_id": None,
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


# ─── GET /by-id/{sid} ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_by_id_happy_path() -> None:
    """GET by-id retourne le secret avec encrypted_value et encrypted_wallet_key."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row(permissions=_PERM_ALL)
        if call_n == 3:
            return _fake_secret_row()  # get_secret_by_id
        return None

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])  # tags
    conn.fetchval = AsyncMock(return_value=_FAKE_ENC_KEY)  # encrypted_wallet_key

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(
            f"/v1/wallets/{_WALLET_ID}/secrets/by-id/{_SECRET_ID}",
            headers=_auth_header(),
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == str(_SECRET_ID)
    assert body["name"] == "/users/no_email/transcription/openai-whisper/api-1"
    assert body["encrypted_value"] == _FAKE_ENC_VALUE_B64
    assert body["encrypted_wallet_key"] == base64.b64encode(_FAKE_ENC_KEY).decode()
```

- [ ] **Step 6.2: Lancer le test → DOIT échouer**

Run :
```bash
cd backend && uv run pytest tests/test_secrets_by_id.py::test_get_by_id_happy_path -v
```
Expected : FAIL avec `404 Not Found` (la route n'existe pas encore).

- [ ] **Step 6.3: Ajouter la route GET dans `secrets.py`**

Dans `backend/app/api/v1/secrets.py`, **avant** la section "LOT_17 — Typed secrets" (après le DELETE existant à la ligne ~336), ajouter une nouvelle section :

```python
# ─── By-ID — accès par UUID (contourne les soucis de routing pour noms à '/') ─


@router.get("/by-id/{secret_id}")
async def get_secret_by_id(
    wallet_id: UUID,
    secret_id: UUID,
    auth: ReadAuth,
    request: Request,
) -> JSONResponse:
    """Retourne le secret par UUID. Requiert [read]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await secrets_svc.get_secret_by_id(
            conn,
            wallet_id=wallet_id,
            secret_id=secret_id,
            caller_user_id=auth.caller_user_id,
            actor_ip=_client_ip(request),
        )

    return JSONResponse(status_code=status.HTTP_200_OK, content=result.model_dump(mode="json"))
```

- [ ] **Step 6.4: Test doit maintenant passer**

Run :
```bash
cd backend && uv run pytest tests/test_secrets_by_id.py::test_get_by_id_happy_path -v
```
Expected : PASS.

- [ ] **Step 6.5: Ajouter les tests de sécurité (cross-wallet + permissions + 404)**

Dans `backend/tests/test_secrets_by_id.py`, ajouter à la suite du précédent :

```python
@pytest.mark.asyncio
async def test_get_by_id_cross_wallet_returns_404() -> None:
    """Un secret qui appartient à un autre wallet → 404 (ne pas leak l'existence)."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row(wallet_id=_WALLET_ID, permissions=_PERM_ALL)
        if call_n == 3:
            # Le secret existe mais dans un AUTRE wallet
            return _fake_secret_row(wallet_id=_OTHER_WALLET_ID)
        return None

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(
            f"/v1/wallets/{_WALLET_ID}/secrets/by-id/{_SECRET_ID}",
            headers=_auth_header(),
        )

    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "secret_not_found"


@pytest.mark.asyncio
async def test_get_by_id_requires_read_permission() -> None:
    """403 si le caller n'a pas [read]."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        return _fake_wallet_row(permissions=_PERM_NO_READ)

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(
            f"/v1/wallets/{_WALLET_ID}/secrets/by-id/{_SECRET_ID}",
            headers=_auth_header(),
        )

    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "insufficient_permissions"


@pytest.mark.asyncio
async def test_get_by_id_returns_404_when_secret_does_not_exist() -> None:
    """404 si l'UUID ne correspond à aucun secret."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row(permissions=_PERM_ALL)
        return None  # secret introuvable

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.get(
            f"/v1/wallets/{_WALLET_ID}/secrets/by-id/{_SECRET_ID}",
            headers=_auth_header(),
        )

    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "secret_not_found"
```

- [ ] **Step 6.6: Lancer tous les tests by-id**

Run :
```bash
cd backend && uv run pytest tests/test_secrets_by_id.py -v
```
Expected : 4 tests PASS.

- [ ] **Step 6.7: Commit**

```bash
git add backend/app/api/v1/secrets.py backend/tests/test_secrets_by_id.py
git commit -m "feat(secrets): route GET /by-id/{sid} pour accès par UUID"
```

---

## Task 7: Service `put_secret_by_id`

**Files:**
- Modify: `backend/app/services/secrets.py`

- [ ] **Step 7.1: Ajouter la fonction service**

Dans `backend/app/services/secrets.py`, à la suite de `get_secret_by_id` (ajoutée en Task 5), ajouter :

```python
async def put_secret_by_id(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    secret_id: UUID,
    req: SecretPutRequest,
    caller_user_id: UUID,
    actor_ip: str | None,
) -> SecretPutResponse:
    """Remplace encrypted_value par UUID. 404 si le secret n'existe pas ou n'appartient pas au wallet."""
    secret = await secrets_repo.get_secret_by_id(conn, secret_id=secret_id)
    if secret is None or secret.wallet_id != wallet_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "secret_not_found", "message": "Secret not found"},
        )

    if secret.is_placeholder:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "placeholder_expected",
                "message": (
                    "This secret is a placeholder. "
                    "Use POST /populate (permission [init]) to set its value."
                ),
            },
        )

    try:
        enc_value = base64.b64decode(req.encrypted_value)
    except Exception as exc:  # pragma: no cover — validé par Pydantic
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_base64", "message": "encrypted_value is not valid base64"},
        ) from exc

    async with conn.transaction():
        new_version = await secrets_repo.update_secret_value(
            conn,
            secret_id=secret.id,
            encrypted_value=enc_value,
            updated_by_user_id=caller_user_id,
        )
        await audit_log_insert(
            conn,
            "secret.updated",
            actor_user_id=caller_user_id,
            actor_ip=actor_ip,
            target_wallet_id=wallet_id,
            target_secret_id=secret.id,
            metadata={
                "secret_name": secret.name,
                "field": "encrypted_value",
                "access_via": "by_id",
            },
        )

    return SecretPutResponse(generation_version=new_version)
```

- [ ] **Step 7.2: Vérifier l'import**

Run :
```bash
cd backend && uv run python -c "from app.services.secrets import put_secret_by_id; print('OK')"
```
Expected : `OK`.

- [ ] **Step 7.3: Commit**

```bash
git add backend/app/services/secrets.py
git commit -m "feat(secrets): service put_secret_by_id"
```

---

## Task 8: Route `PUT /wallets/{wid}/secrets/by-id/{sid}`

**Files:**
- Modify: `backend/app/api/v1/secrets.py`
- Test: `backend/tests/test_secrets_by_id.py` (ajout)

- [ ] **Step 8.1: Écrire le test rouge**

Dans `backend/tests/test_secrets_by_id.py`, ajouter :

```python
# ─── PUT /by-id/{sid} ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_put_by_id_happy_path() -> None:
    """PUT by-id remplace encrypted_value et incrémente generation_version."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row(permissions=_PERM_ALL)
        if call_n == 3:
            return _fake_secret_row()  # get_secret_by_id
        return None

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])
    # update_secret_value retourne la nouvelle generation_version
    conn.fetchval = AsyncMock(return_value=2)

    new_value_b64 = base64.b64encode(b"new_encrypted_value").decode()

    async with _make_client(_make_pool(conn)) as client:
        r = await client.put(
            f"/v1/wallets/{_WALLET_ID}/secrets/by-id/{_SECRET_ID}",
            json={"encrypted_value": new_value_b64},
            headers=_auth_header(),
        )

    assert r.status_code == 200, r.text
    assert r.json()["generation_version"] == 2


@pytest.mark.asyncio
async def test_put_by_id_cross_wallet_returns_404() -> None:
    """PUT sur un secret d'un autre wallet → 404."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row(wallet_id=_WALLET_ID, permissions=_PERM_ALL)
        if call_n == 3:
            return _fake_secret_row(wallet_id=_OTHER_WALLET_ID)
        return None

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.put(
            f"/v1/wallets/{_WALLET_ID}/secrets/by-id/{_SECRET_ID}",
            json={"encrypted_value": _FAKE_ENC_VALUE_B64},
            headers=_auth_header(),
        )

    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "secret_not_found"
```

- [ ] **Step 8.2: Lancer les tests → DOIVENT échouer**

Run :
```bash
cd backend && uv run pytest tests/test_secrets_by_id.py -v -k "put_by_id"
```
Expected : 2 tests FAIL avec 405 Method Not Allowed (route GET existe mais pas PUT).

- [ ] **Step 8.3: Ajouter la route PUT**

Dans `backend/app/api/v1/secrets.py`, à la suite de la route GET by-id ajoutée en Task 6 :

```python
@router.put("/by-id/{secret_id}")
async def put_secret_by_id(
    wallet_id: UUID,
    secret_id: UUID,
    req: SecretPutRequest,
    auth: WriteAuth,
    request: Request,
) -> JSONResponse:
    """Remplace encrypted_value par UUID. Requiert [write]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await secrets_svc.put_secret_by_id(
            conn,
            wallet_id=wallet_id,
            secret_id=secret_id,
            req=req,
            caller_user_id=auth.caller_user_id,
            actor_ip=_client_ip(request),
        )

    return JSONResponse(status_code=status.HTTP_200_OK, content=result.model_dump(mode="json"))
```

- [ ] **Step 8.4: Tests doivent passer**

Run :
```bash
cd backend && uv run pytest tests/test_secrets_by_id.py -v
```
Expected : tous PASS (incluant les tests GET et les nouveaux PUT).

- [ ] **Step 8.5: Commit**

```bash
git add backend/app/api/v1/secrets.py backend/tests/test_secrets_by_id.py
git commit -m "feat(secrets): route PUT /by-id/{sid}"
```

---

## Task 9: Service `delete_secret_by_id`

**Files:**
- Modify: `backend/app/services/secrets.py`

- [ ] **Step 9.1: Ajouter la fonction service**

Dans `backend/app/services/secrets.py`, à la suite de `put_secret_by_id` :

```python
async def delete_secret_by_id(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    secret_id: UUID,
    caller_user_id: UUID,
    actor_ip: str | None,
) -> None:
    """Supprime le secret par UUID. 404 si introuvable ou wallet mismatch."""
    secret = await secrets_repo.get_secret_by_id(conn, secret_id=secret_id)
    if secret is None or secret.wallet_id != wallet_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "secret_not_found", "message": "Secret not found"},
        )

    async with conn.transaction():
        await secrets_repo.delete_secret(conn, secret_id=secret.id)
        await audit_log_insert(
            conn,
            "secret.deleted",
            actor_user_id=caller_user_id,
            actor_ip=actor_ip,
            target_wallet_id=wallet_id,
            target_secret_id=secret.id,
            metadata={"secret_name": secret.name, "access_via": "by_id"},
        )
```

- [ ] **Step 9.2: Vérifier l'import**

Run :
```bash
cd backend && uv run python -c "from app.services.secrets import delete_secret_by_id; print('OK')"
```
Expected : `OK`.

- [ ] **Step 9.3: Commit**

```bash
git add backend/app/services/secrets.py
git commit -m "feat(secrets): service delete_secret_by_id"
```

---

## Task 10: Route `DELETE /wallets/{wid}/secrets/by-id/{sid}`

**Files:**
- Modify: `backend/app/api/v1/secrets.py`
- Test: `backend/tests/test_secrets_by_id.py` (ajout)

- [ ] **Step 10.1: Écrire les tests rouges**

Dans `backend/tests/test_secrets_by_id.py`, ajouter :

```python
# ─── DELETE /by-id/{sid} ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_by_id_happy_path() -> None:
    """DELETE by-id retourne 204 et exécute la suppression."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row(permissions=_PERM_ALL)
        if call_n == 3:
            return _fake_secret_row()
        return None

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.delete(
            f"/v1/wallets/{_WALLET_ID}/secrets/by-id/{_SECRET_ID}",
            headers=_auth_header(),
        )

    assert r.status_code == 204, r.text
    # Vérifie qu'un DELETE SQL a été émis
    assert any(
        "DELETE FROM secrets" in str(c.args[0])
        for c in conn.execute.call_args_list
    )


@pytest.mark.asyncio
async def test_delete_by_id_cross_wallet_returns_404() -> None:
    """DELETE sur un secret d'un autre wallet → 404."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        if call_n == 2:
            return _fake_wallet_row(wallet_id=_WALLET_ID, permissions=_PERM_ALL)
        if call_n == 3:
            return _fake_secret_row(wallet_id=_OTHER_WALLET_ID)
        return None

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.delete(
            f"/v1/wallets/{_WALLET_ID}/secrets/by-id/{_SECRET_ID}",
            headers=_auth_header(),
        )

    assert r.status_code == 404
    # Vérifie qu'aucun DELETE SQL n'a été émis (le secret n'a pas été touché)
    assert not any(
        "DELETE FROM secrets" in str(c.args[0])
        for c in conn.execute.call_args_list
    )


@pytest.mark.asyncio
async def test_delete_by_id_requires_remove_permission() -> None:
    """403 si le caller n'a pas [remove]."""
    conn = _make_conn()
    call_n = 0

    async def fetchrow_side(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _fake_user_row()
        # Tout sauf remove (0x10 = 16)
        return _fake_wallet_row(permissions=_PERM_ALL & ~16)

    conn.fetchrow = fetchrow_side
    conn.fetch = AsyncMock(return_value=[])

    async with _make_client(_make_pool(conn)) as client:
        r = await client.delete(
            f"/v1/wallets/{_WALLET_ID}/secrets/by-id/{_SECRET_ID}",
            headers=_auth_header(),
        )

    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "insufficient_permissions"
```

- [ ] **Step 10.2: Lancer les tests → DOIVENT échouer**

Run :
```bash
cd backend && uv run pytest tests/test_secrets_by_id.py -v -k "delete_by_id"
```
Expected : 3 tests FAIL avec 405 Method Not Allowed.

- [ ] **Step 10.3: Ajouter la route DELETE**

Dans `backend/app/api/v1/secrets.py`, à la suite de la route PUT by-id :

```python
@router.delete(
    "/by-id/{secret_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_secret_by_id(
    wallet_id: UUID,
    secret_id: UUID,
    auth: RemoveAuth,
    request: Request,
) -> Response:
    """Supprime le secret par UUID (cascade sur secret_tags + secret_path_index). Requiert [remove]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await secrets_svc.delete_secret_by_id(
            conn,
            wallet_id=wallet_id,
            secret_id=secret_id,
            caller_user_id=auth.caller_user_id,
            actor_ip=_client_ip(request),
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 10.4: Tests doivent passer**

Run :
```bash
cd backend && uv run pytest tests/test_secrets_by_id.py -v
```
Expected : tous les tests `test_secrets_by_id.py` PASS (GET + PUT + DELETE = ~9 tests).

- [ ] **Step 10.5: Commit**

```bash
git add backend/app/api/v1/secrets.py backend/tests/test_secrets_by_id.py
git commit -m "feat(secrets): route DELETE /by-id/{sid}"
```

---

## Task 11: Vérification finale & lint

- [ ] **Step 11.1: Lancer toute la suite de tests backend**

Run :
```bash
cd backend && uv run pytest -v 2>&1 | tail -40
```
Expected : tous les tests PASS, aucune régression sur les tests existants.

- [ ] **Step 11.2: Lancer le lint**

Run :
```bash
cd backend && uv run ruff check src/ tests/ app/ 2>&1
```
Expected : `All checks passed!`

Si erreurs de lint, les corriger avant de poursuivre.

- [ ] **Step 11.3: Lancer le format**

Run :
```bash
cd backend && uv run ruff format app/ tests/ --check 2>&1
```
Si non-formaté : `uv run ruff format app/ tests/`.

- [ ] **Step 11.4: Vérification mypy (si configuré)**

Run :
```bash
cd backend && uv run mypy app/ 2>&1 | tail -10
```
Expected : 0 erreurs (ou compatibles avec le baseline existant).

- [ ] **Step 11.5: Commit final si formatage**

Si Step 11.3 a reformaté des fichiers :
```bash
git add -u && git commit -m "chore: ruff format après ajout des routes by-id"
```

Sinon rien à committer.

---

## Critères d'acceptation P1

- ✅ `validate_secret_name("/foo/bar/")` lève `InvalidSecretPath`
- ✅ `validate_secret_name("/foo//bar")` lève `InvalidSecretPath` (déjà existant, vérifié)
- ✅ POST /v1/wallets/{wid}/secrets avec `name: "/foo/bar/"` retourne `400 {"error": "invalid_secret_path", ...}`
- ✅ GET /v1/wallets/{wid}/secrets/by-id/{sid} retourne le secret si appartient au wallet, 404 sinon
- ✅ PUT /v1/wallets/{wid}/secrets/by-id/{sid} met à jour encrypted_value
- ✅ DELETE /v1/wallets/{wid}/secrets/by-id/{sid} supprime le secret
- ✅ Cross-wallet : un secret de wallet B n'est pas accessible via wallet A même avec son UUID
- ✅ Permissions [read]/[write]/[remove] respectées sur les nouvelles routes
- ✅ Audit log enregistré avec `metadata.access_via = "by_id"` pour distinguer la voie
- ✅ Routes `/{name}` existantes inchangées et fonctionnelles
- ✅ Tous les tests backend passent (anciens + nouveaux)
- ✅ Lint propre

## Hors scope P1 (reporté)

- Frontend (migration `SecretCard` + `SecretDetailPage` vers by-id) → P2
- Suppression récursive par path (`DELETE ?path=/foo/bar/`) → P4
- SDK Python (méthodes `get_by_id`, etc.) → P3
- Réorganisation IHM type Windows Explorer → P4 (avec brainstorming)
- Création de secret avec path en UI → P4
