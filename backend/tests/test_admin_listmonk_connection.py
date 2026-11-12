"""Connexion Listmonk paramétrée depuis l'IHM (épic « Cultures et templates Listmonk
paramétrés en base », feature 3).

Couvre : chiffrement du token (aller-retour, clé changée), routes admin (le token n'est
jamais renvoyé ni audité), test de connexion, reprise unique depuis le .env. Le
repository est une ligne en mémoire ; la base réelle est couverte par
``test_listmonk_connection_repository.py``.
"""

from __future__ import annotations

import base64
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from cryptography.exceptions import InvalidTag
from httpx import ASGITransport, AsyncClient

from app.core import server_secret_box
from app.models.db.listmonk_connection import ListmonkConnectionRow
from tests._helpers import TEST_AUDIENCE, TEST_KID, TEST_PUBLIC_JWK, make_jwt_token

_ADMIN_ROLE = "harpocrate-admin"
_URL = "/v1/admin/listmonk"
_CONN_URL = f"{_URL}/connection"
_TOKEN = "very-secret-token"


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


class _FakeConnectionRepo:
    """Ligne unique en mémoire, mêmes signatures que le repository réel."""

    def __init__(self) -> None:
        import datetime

        self.row: ListmonkConnectionRow | None = None
        self._now = datetime.datetime(2026, 11, 12, tzinfo=datetime.UTC)

    async def db_get(self, conn: Any) -> ListmonkConnectionRow | None:
        return self.row

    async def db_upsert(
        self, conn: Any, *, url: str, api_user: str, token_encrypted: bytes, updated_by_user_id: Any
    ) -> None:
        self.row = ListmonkConnectionRow(
            url=url,
            api_user=api_user,
            token_encrypted=token_encrypted,
            updated_by_user_id=updated_by_user_id,
            updated_at=self._now,
        )

    async def db_insert_if_absent(
        self, conn: Any, *, url: str, api_user: str, token_encrypted: bytes
    ) -> bool:
        if self.row is not None:
            return False
        await self.db_upsert(
            conn,
            url=url,
            api_user=api_user,
            token_encrypted=token_encrypted,
            updated_by_user_id=None,
        )
        return True


@pytest.fixture()
def repo(monkeypatch: pytest.MonkeyPatch) -> _FakeConnectionRepo:
    from app.db.repositories import listmonk_connection as repo_mod
    from app.db.repositories import listmonk_templates as templates_repo

    fake = _FakeConnectionRepo()
    for name in ("db_get", "db_upsert", "db_insert_if_absent"):
        monkeypatch.setattr(repo_mod, name, getattr(fake, name))
    monkeypatch.setattr(templates_repo, "db_list", AsyncMock(return_value=[]))
    return fake


@pytest.fixture()
def audit(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    from app.services import listmonk_connection as svc_mod

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


_BODY = {"url": "http://mail.home.lan:9000/", "api_user": "harpocrate-api", "token": _TOKEN}


# ─── Chiffrement du token ────────────────────────────────────────────────────


def test_secret_box_round_trip_returns_plaintext() -> None:
    blob = server_secret_box.seal(_TOKEN, purpose=b"test.v1")
    assert _TOKEN.encode() not in blob
    assert server_secret_box.unseal(blob, purpose=b"test.v1") == _TOKEN


def test_secret_box_other_purpose_cannot_unseal() -> None:
    blob = server_secret_box.seal(_TOKEN, purpose=b"test.v1")
    with pytest.raises(InvalidTag):
        server_secret_box.unseal(blob, purpose=b"other.v1")


def test_secret_box_changed_hmac_key_cannot_unseal(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    blob = server_secret_box.seal(_TOKEN, purpose=b"test.v1")
    monkeypatch.setattr(settings, "hmac_key", base64.b64encode(b"z" * 32).decode())
    with pytest.raises(InvalidTag):
        server_secret_box.unseal(blob, purpose=b"test.v1")


# ─── Autorisation ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("method", "path"), [("put", _CONN_URL), ("post", f"{_CONN_URL}/test")])
async def test_connection_routes_non_admin_returns_403(
    repo: _FakeConnectionRepo, audit: AsyncMock, method: str, path: str
) -> None:
    async with _make_client() as client:
        r = await getattr(client, method)(path, headers=_user(), json=_BODY)
    assert r.status_code == 403
    assert repo.row is None


# ─── Enregistrement ──────────────────────────────────────────────────────────


async def test_put_connection_stores_encrypted_token_and_never_returns_it(
    repo: _FakeConnectionRepo, audit: AsyncMock
) -> None:
    async with _make_client() as client:
        r = await client.put(_CONN_URL, headers=_admin(), json=_BODY)
        got = await client.get(_URL, headers=_admin())
    assert r.status_code == 204
    assert repo.row is not None
    assert repo.row.url == "http://mail.home.lan:9000"
    assert _TOKEN.encode() not in repo.row.token_encrypted
    assert got.json()["connection"] == {
        "url": "http://mail.home.lan:9000",
        "api_user": "harpocrate-api",
        "token_readable": True,
        "updated_at": "2026-11-12T00:00:00Z",
    }
    assert _TOKEN not in got.text
    # Audit : le fait que le token a changé, jamais sa valeur.
    assert audit.await_args.args[1] == "listmonk_connection.updated"
    assert audit.await_args.kwargs["metadata"] == {
        "url": "http://mail.home.lan:9000",
        "api_user": "harpocrate-api",
        "token_changed": True,
    }
    assert _TOKEN not in str(audit.await_args)


async def test_put_connection_without_token_keeps_stored_token(
    repo: _FakeConnectionRepo, audit: AsyncMock
) -> None:
    from app.services import listmonk_connection as svc

    async with _make_client() as client:
        await client.put(_CONN_URL, headers=_admin(), json=_BODY)
        r = await client.put(
            _CONN_URL,
            headers=_admin(),
            json={"url": "http://mail.home.lan:9000", "api_user": "other"},
        )
    assert r.status_code == 204
    resolved = await svc.resolve_connection(MagicMock())
    assert resolved is not None
    assert resolved.api_user == "other"
    assert resolved.token.get_secret_value() == _TOKEN
    assert audit.await_args.kwargs["metadata"]["token_changed"] is False


async def test_put_new_url_without_token_returns_422(
    repo: _FakeConnectionRepo, audit: AsyncMock
) -> None:
    """Le token enregistré ne suit jamais une nouvelle URL : sinon il partirait en clair
    vers un hôte choisi par l'admin, et le token « non relisible » se relirait."""
    async with _make_client() as client:
        await client.put(_CONN_URL, headers=_admin(), json=_BODY)
        r = await client.put(
            _CONN_URL,
            headers=_admin(),
            json={"url": "https://attacker.example", "api_user": "harpocrate-api"},
        )
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "token_required"
    assert repo.row is not None and repo.row.url == "http://mail.home.lan:9000"


async def test_put_first_connection_without_token_returns_422(
    repo: _FakeConnectionRepo, audit: AsyncMock
) -> None:
    async with _make_client() as client:
        r = await client.put(
            _CONN_URL, headers=_admin(), json={"url": "http://a.lan", "api_user": "u"}
        )
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "token_required"
    assert repo.row is None


@pytest.mark.parametrize(
    "patch_",
    [
        {"url": "ftp://mail.lan"},
        {"url": "mail.lan:9000"},
        {"url": "http://user:pw@mail.lan"},
        {"url": "http://mail.lan/?x=1"},
        {"url": "http://mail.lan/#x"},
        {"url": "http://mail.lan:99999"},
        {"api_user": "   "},
        {"token": ""},
        {"extra": 1},
    ],
)
async def test_put_connection_invalid_input_returns_422(
    repo: _FakeConnectionRepo, audit: AsyncMock, patch_: dict[str, Any]
) -> None:
    async with _make_client() as client:
        r = await client.put(_CONN_URL, headers=_admin(), json={**_BODY, **patch_})
    assert r.status_code == 422
    assert repo.row is None


async def test_undecryptable_token_is_reported_and_not_used(
    repo: _FakeConnectionRepo, audit: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings
    from app.services import listmonk_connection as svc

    async with _make_client() as client:
        await client.put(_CONN_URL, headers=_admin(), json=_BODY)
        monkeypatch.setattr(settings, "hmac_key", base64.b64encode(b"z" * 32).decode())
        got = await client.get(_URL, headers=_admin())
    assert got.json()["connection"]["token_readable"] is False
    assert await svc.resolve_connection(MagicMock()) is None


async def test_put_without_token_when_stored_token_unreadable_returns_422(
    repo: _FakeConnectionRepo, audit: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings

    async with _make_client() as client:
        await client.put(_CONN_URL, headers=_admin(), json=_BODY)
        audit.reset_mock()
        monkeypatch.setattr(settings, "hmac_key", base64.b64encode(b"z" * 32).decode())
        r = await client.put(
            _CONN_URL,
            headers=_admin(),
            json={"url": "http://mail.home.lan:9000", "api_user": "other"},
        )
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "token_required"
    audit.assert_not_awaited()


# ─── Test de connexion ───────────────────────────────────────────────────────


def _fake_http(response: httpx.Response | Exception) -> tuple[AsyncMock, list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []

    async def fake_get(url: str, headers: dict[str, str]) -> httpx.Response:
        calls.append({"url": url, "headers": headers})
        if isinstance(response, Exception):
            raise response
        return response

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.get = AsyncMock(side_effect=fake_get)
    return client, calls


async def test_connection_test_calls_health_with_given_credentials(
    repo: _FakeConnectionRepo, audit: AsyncMock
) -> None:
    fake, calls = _fake_http(httpx.Response(200, json={"data": True}))
    with patch("httpx.AsyncClient", return_value=fake):
        async with _make_client() as client:
            r = await client.post(f"{_CONN_URL}/test", headers=_admin(), json=_BODY)
    assert r.status_code == 200
    assert r.json() == {"ok": True, "http_status": 200}
    assert calls == [
        {
            "url": "http://mail.home.lan:9000/api/health",
            "headers": {"Authorization": f"token harpocrate-api:{_TOKEN}"},
        }
    ]
    assert repo.row is None  # un test n'enregistre rien


async def test_connection_test_bad_credentials_reports_status_without_body(
    repo: _FakeConnectionRepo, audit: AsyncMock
) -> None:
    fake, _ = _fake_http(httpx.Response(403, text="secret page content"))
    with patch("httpx.AsyncClient", return_value=fake):
        async with _make_client() as client:
            r = await client.post(f"{_CONN_URL}/test", headers=_admin(), json=_BODY)
    assert r.json() == {"ok": False, "http_status": 403}
    assert "secret page content" not in r.text


async def test_connection_test_unreachable_reports_no_status(
    repo: _FakeConnectionRepo, audit: AsyncMock
) -> None:
    fake, _ = _fake_http(httpx.ConnectError("dns fail"))
    with patch("httpx.AsyncClient", return_value=fake):
        async with _make_client() as client:
            r = await client.post(f"{_CONN_URL}/test", headers=_admin(), json=_BODY)
    assert r.json() == {"ok": False, "http_status": None}


async def test_connection_test_without_token_uses_stored_token(
    repo: _FakeConnectionRepo, audit: AsyncMock
) -> None:
    fake, calls = _fake_http(httpx.Response(200))
    async with _make_client() as client:
        await client.put(_CONN_URL, headers=_admin(), json=_BODY)
        with patch("httpx.AsyncClient", return_value=fake):
            r = await client.post(
                f"{_CONN_URL}/test",
                headers=_admin(),
                json={"url": "http://mail.home.lan:9000", "api_user": "harpocrate-api"},
            )
    assert r.json()["ok"] is True
    assert calls[0]["url"] == "http://mail.home.lan:9000/api/health"
    assert calls[0]["headers"]["Authorization"] == f"token harpocrate-api:{_TOKEN}"


async def test_connection_test_other_url_without_token_never_sends_stored_token(
    repo: _FakeConnectionRepo, audit: AsyncMock
) -> None:
    fake, calls = _fake_http(httpx.Response(200))
    async with _make_client() as client:
        await client.put(_CONN_URL, headers=_admin(), json=_BODY)
        with patch("httpx.AsyncClient", return_value=fake):
            r = await client.post(
                f"{_CONN_URL}/test",
                headers=_admin(),
                json={"url": "https://attacker.example", "api_user": "harpocrate-api"},
            )
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "token_required"
    assert calls == []


async def test_connection_test_without_any_token_returns_422(
    repo: _FakeConnectionRepo, audit: AsyncMock
) -> None:
    async with _make_client() as client:
        r = await client.post(
            f"{_CONN_URL}/test", headers=_admin(), json={"url": "http://a.lan", "api_user": "u"}
        )
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "token_required"


# ─── Reprise depuis le .env ──────────────────────────────────────────────────


def _legacy(monkeypatch: pytest.MonkeyPatch, url: str, user: str, token: str) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "listmonk_url", url)
    monkeypatch.setattr(settings, "listmonk_user", user)
    monkeypatch.setattr(settings, "listmonk_token", token)


async def test_import_legacy_connection_when_absent(
    repo: _FakeConnectionRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import listmonk_connection as svc

    _legacy(monkeypatch, "http://mail.home.lan:9000/", "harpocrate-api", _TOKEN)
    await svc.import_legacy_env_connection(MagicMock())
    resolved = await svc.resolve_connection(MagicMock())
    assert resolved is not None
    assert resolved.url == "http://mail.home.lan:9000"
    assert resolved.token.get_secret_value() == _TOKEN


async def test_import_legacy_connection_never_overwrites(
    repo: _FakeConnectionRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import listmonk_connection as svc

    await repo.db_upsert(
        MagicMock(),
        url="https://ui.example",
        api_user="ui",
        token_encrypted=b"x" * 40,
        updated_by_user_id=None,
    )
    _legacy(monkeypatch, "http://mail.home.lan:9000", "harpocrate-api", _TOKEN)
    await svc.import_legacy_env_connection(MagicMock())
    assert repo.row is not None and repo.row.url == "https://ui.example"


@pytest.mark.parametrize(
    ("url", "user", "token"),
    [
        ("", "harpocrate-api", _TOKEN),
        ("http://mail.lan", "", _TOKEN),
        ("http://mail.lan", "harpocrate-api", ""),
        ("http://api:pw@mail.lan", "harpocrate-api", _TOKEN),
    ],
)
async def test_import_legacy_connection_skips_incomplete_or_invalid(
    repo: _FakeConnectionRepo, monkeypatch: pytest.MonkeyPatch, url: str, user: str, token: str
) -> None:
    from app.services import listmonk_connection as svc

    _legacy(monkeypatch, url, user, token)
    await svc.import_legacy_env_connection(MagicMock())
    assert repo.row is None
