"""Endpoints admin du registre des applications — /v1/admin/connect-clients (feature 1).

Le repository est remplacé par un registre en mémoire : la base réelle est
couverte par ``test_connect_clients_repository.py``.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

from app.models.db.connect_client import ConnectClientRow
from tests._helpers import TEST_AUDIENCE, TEST_KID, TEST_PUBLIC_JWK, make_jwt_token

_ADMIN_ROLE = "harpocrate-admin"
_URL = "/v1/admin/connect-clients"


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", TEST_AUDIENCE)
    import app.core.security

    _sec = app.core.security.__dict__["settings"]
    monkeypatch.setattr(_sec, "keycloak_url", "https://keycloak.yoops.org")
    monkeypatch.setattr(_sec, "keycloak_realm", "yoops")
    monkeypatch.setattr(_sec, "keycloak_client_id", TEST_AUDIENCE)


@pytest.fixture(autouse=True)
def patch_jwks() -> Generator[None, None, None]:
    from app.core import jwks_cache

    backup = dict(jwks_cache._keys)
    jwks_cache._keys.clear()
    jwks_cache._keys[TEST_KID] = TEST_PUBLIC_JWK
    yield
    jwks_cache._keys.clear()
    jwks_cache._keys.update(backup)


class _FakeRepo:
    """Registre en mémoire, mêmes signatures que le repository réel."""

    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, ConnectClientRow] = {}

    async def db_insert(
        self,
        conn: Any,
        *,
        client_id: str,
        name: str,
        description: str | None,
        redirect_uris: list[str],
        created_by_user_id: uuid.UUID | None,
    ) -> ConnectClientRow:
        if any(r.client_id == client_id for r in self.rows.values()):
            raise asyncpg.UniqueViolationError("duplicate key value violates unique constraint")
        now = datetime.datetime.now(datetime.UTC)
        row = ConnectClientRow(
            id=uuid.uuid4(),
            client_id=client_id,
            name=name,
            description=description,
            redirect_uris=list(redirect_uris),
            active=True,
            created_by_user_id=created_by_user_id,
            created_at=now,
            updated_at=now,
        )
        self.rows[row.id] = row
        return row

    async def db_list(self, conn: Any) -> list[ConnectClientRow]:
        return sorted(self.rows.values(), key=lambda r: r.name.lower())

    async def db_get_by_id(
        self, conn: Any, client_pk: uuid.UUID, *, for_update: bool = False
    ) -> ConnectClientRow | None:
        return self.rows.get(client_pk)

    async def db_update(
        self,
        conn: Any,
        client_pk: uuid.UUID,
        *,
        name: str,
        description: str | None,
        redirect_uris: list[str],
        active: bool,
    ) -> ConnectClientRow | None:
        row = self.rows.get(client_pk)
        if row is None:
            return None
        row = row.model_copy(
            update={
                "name": name,
                "description": description,
                "redirect_uris": list(redirect_uris),
                "active": active,
                "updated_at": datetime.datetime.now(datetime.UTC),
            }
        )
        self.rows[client_pk] = row
        return row


@pytest.fixture()
def fake_repo(monkeypatch: pytest.MonkeyPatch) -> _FakeRepo:
    from app.db.repositories import connect_clients as repo_mod

    fake = _FakeRepo()
    for name in ("db_insert", "db_list", "db_get_by_id", "db_update"):
        monkeypatch.setattr(repo_mod, name, getattr(fake, name))
    return fake


@pytest.fixture()
def audit(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    from app.services import connect_clients as svc_mod

    mock = AsyncMock()
    monkeypatch.setattr(svc_mod, "audit_log_insert", mock)
    return mock


def _make_client() -> AsyncClient:
    from app.db import pool as pool_mod
    from app.main import app

    conn = MagicMock()

    class _Tx:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *a: Any) -> None:
            return None

    conn.transaction = MagicMock(return_value=_Tx())

    class _Acq:
        async def __aenter__(self) -> MagicMock:
            return conn

        async def __aexit__(self, *a: Any) -> None:
            return None

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_Acq())
    pool_mod._pool = pool
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _admin() -> dict[str, str]:
    token = make_jwt_token(extra_claims={"realm_access": {"roles": [_ADMIN_ROLE]}})
    return {"Authorization": f"Bearer {token}"}


def _user() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_jwt_token()}"}


_VALID = {
    "client_id": "ragflow",
    "name": "Ragflow",
    "description": "Moteur RAG",
    "redirect_uris": ["https://rag.example/oauth/harpocrate/callback"],
}


# ─── Autorisation ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", _URL),
        ("post", _URL),
        ("get", f"{_URL}/{uuid.uuid4()}"),
        ("patch", f"{_URL}/{uuid.uuid4()}"),
    ],
)
async def test_connect_clients_routes_refuse_non_admin(
    fake_repo: _FakeRepo, audit: AsyncMock, method: str, path: str
) -> None:
    async with _make_client() as client:
        kwargs: dict[str, Any] = {"headers": _user()}
        if method in ("post", "patch"):
            kwargs["json"] = _VALID if method == "post" else {"active": False}
        r = await getattr(client, method)(path, **kwargs)
    assert r.status_code == 403
    assert fake_repo.rows == {}


async def test_connect_clients_routes_refuse_anonymous(
    fake_repo: _FakeRepo, audit: AsyncMock
) -> None:
    async with _make_client() as client:
        r = await client.get(_URL)
    assert r.status_code in (401, 403)


# ─── Création ────────────────────────────────────────────────────────────────


async def test_create_connect_client_returns_201_with_all_fields(
    fake_repo: _FakeRepo, audit: AsyncMock
) -> None:
    async with _make_client() as client:
        r = await client.post(_URL, headers=_admin(), json=_VALID)
    assert r.status_code == 201
    body = r.json()
    assert set(body) == {
        "id",
        "client_id",
        "name",
        "description",
        "redirect_uris",
        "active",
        "created_at",
        "updated_at",
    }
    assert body["client_id"] == "ragflow"
    assert body["redirect_uris"] == _VALID["redirect_uris"]
    assert body["active"] is True
    audit.assert_awaited_once()
    assert audit.await_args.args[1] == "connect_client.created"
    assert audit.await_args.kwargs["metadata"]["client_id"] == "ragflow"


async def test_create_connect_client_duplicate_client_id_returns_409(
    fake_repo: _FakeRepo, audit: AsyncMock
) -> None:
    async with _make_client() as client:
        await client.post(_URL, headers=_admin(), json=_VALID)
        r = await client.post(_URL, headers=_admin(), json={**_VALID, "name": "Autre"})
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "client_id_taken"


@pytest.mark.parametrize(
    "patch",
    [
        {"client_id": "Ragflow"},
        {"client_id": "ab"},
        {"name": ""},
        {"redirect_uris": []},
        {"redirect_uris": ["http://rag.example/cb"]},
        {"redirect_uris": ["https://rag.example/cb#x"]},
        {"redirect_uris": ["https://*.example/cb"]},
        {"redirect_uris": ["https://rag.example/cb"] * 11},
        {"unexpected": "field"},
    ],
)
async def test_create_connect_client_rejects_invalid_input(
    fake_repo: _FakeRepo, audit: AsyncMock, patch: dict[str, Any]
) -> None:
    async with _make_client() as client:
        r = await client.post(_URL, headers=_admin(), json={**_VALID, **patch})
    assert r.status_code == 422
    assert fake_repo.rows == {}
    audit.assert_not_awaited()


async def test_create_connect_client_deduplicates_redirect_uris_keeping_order(
    fake_repo: _FakeRepo, audit: AsyncMock
) -> None:
    uris = ["https://a.example/cb", "https://b.example/cb", "https://a.example/cb"]
    async with _make_client() as client:
        r = await client.post(_URL, headers=_admin(), json={**_VALID, "redirect_uris": uris})
    assert r.status_code == 201
    assert r.json()["redirect_uris"] == ["https://a.example/cb", "https://b.example/cb"]


# ─── Lecture ─────────────────────────────────────────────────────────────────


async def test_list_connect_clients_returns_items(fake_repo: _FakeRepo, audit: AsyncMock) -> None:
    async with _make_client() as client:
        await client.post(_URL, headers=_admin(), json=_VALID)
        r = await client.get(_URL, headers=_admin())
    assert r.status_code == 200
    items = r.json()["items"]
    assert [i["client_id"] for i in items] == ["ragflow"]


async def test_get_connect_client_returns_404_when_absent(
    fake_repo: _FakeRepo, audit: AsyncMock
) -> None:
    async with _make_client() as client:
        r = await client.get(f"{_URL}/{uuid.uuid4()}", headers=_admin())
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "connect_client_not_found"


# ─── Modification / désactivation ────────────────────────────────────────────


async def test_patch_connect_client_updates_only_given_fields(
    fake_repo: _FakeRepo, audit: AsyncMock
) -> None:
    async with _make_client() as client:
        created = (await client.post(_URL, headers=_admin(), json=_VALID)).json()
        r = await client.patch(
            f"{_URL}/{created['id']}", headers=_admin(), json={"name": "Ragflow prod"}
        )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Ragflow prod"
    assert body["description"] == _VALID["description"]
    assert body["redirect_uris"] == _VALID["redirect_uris"]
    assert body["client_id"] == "ragflow"
    assert audit.await_args.args[1] == "connect_client.updated"
    assert audit.await_args.kwargs["metadata"]["changed"] == ["name"]


async def test_patch_connect_client_can_clear_description(
    fake_repo: _FakeRepo, audit: AsyncMock
) -> None:
    async with _make_client() as client:
        created = (await client.post(_URL, headers=_admin(), json=_VALID)).json()
        r = await client.patch(
            f"{_URL}/{created['id']}", headers=_admin(), json={"description": None}
        )
    assert r.status_code == 200
    assert r.json()["description"] is None


async def test_patch_connect_client_disable_is_audited_as_disabled(
    fake_repo: _FakeRepo, audit: AsyncMock
) -> None:
    async with _make_client() as client:
        created = (await client.post(_URL, headers=_admin(), json=_VALID)).json()
        r = await client.patch(f"{_URL}/{created['id']}", headers=_admin(), json={"active": False})
    assert r.status_code == 200
    assert r.json()["active"] is False
    assert audit.await_args.args[1] == "connect_client.disabled"


@pytest.mark.parametrize(
    "body",
    [{}, {"client_id": "autre"}, {"redirect_uris": ["http://rag.example/cb"]}, {"name": ""}],
)
async def test_patch_connect_client_rejects_invalid_or_empty_body(
    fake_repo: _FakeRepo, audit: AsyncMock, body: dict[str, Any]
) -> None:
    async with _make_client() as client:
        created = (await client.post(_URL, headers=_admin(), json=_VALID)).json()
        audit.reset_mock()
        r = await client.patch(f"{_URL}/{created['id']}", headers=_admin(), json=body)
    assert r.status_code == 422
    audit.assert_not_awaited()


async def test_patch_connect_client_returns_404_when_absent(
    fake_repo: _FakeRepo, audit: AsyncMock
) -> None:
    async with _make_client() as client:
        r = await client.patch(f"{_URL}/{uuid.uuid4()}", headers=_admin(), json={"active": False})
    assert r.status_code == 404
