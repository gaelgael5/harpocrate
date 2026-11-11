"""Endpoints admin des cultures — /v1/admin/cultures (épic « Cultures et templates Listmonk »,
feature 1).

Le repository est remplacé par une table en mémoire : la base réelle (contraintes, amorçage
ISO 639-1) est couverte par ``test_cultures_migration.py``.
"""

from __future__ import annotations

import datetime
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.models.db.culture import CultureRow
from tests._helpers import TEST_AUDIENCE, TEST_KID, TEST_PUBLIC_JWK, make_jwt_token

_ADMIN_ROLE = "harpocrate-admin"
_URL = "/v1/admin/cultures"


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


def _culture(code: str, name: str, *, enabled: bool = False, default: bool = False) -> CultureRow:
    return CultureRow(
        code=code,
        english_name=name,
        native_name=None,
        enabled=enabled,
        is_default=default,
        updated_at=datetime.datetime(2026, 11, 1, tzinfo=datetime.UTC),
    )


class _FakeRepo:
    """Table en mémoire, mêmes signatures que le repository réel. Amorcée comme la
    migration : en (défaut) et fr activées, de désactivée."""

    def __init__(self) -> None:
        self.rows: dict[str, CultureRow] = {
            "de": _culture("de", "German"),
            "en": _culture("en", "English", enabled=True, default=True),
            "fr": _culture("fr", "French", enabled=True),
        }

    def _replace(self, code: str, **changes: Any) -> CultureRow | None:
        if code not in self.rows:
            return None
        self.rows[code] = self.rows[code].model_copy(update=changes)
        return self.rows[code]

    async def db_list(self, conn: Any) -> list[CultureRow]:
        return sorted(self.rows.values(), key=lambda r: r.english_name)

    async def db_get(self, conn: Any, code: str, *, for_update: bool = False) -> CultureRow | None:
        return self.rows.get(code)

    async def db_set_enabled(self, conn: Any, code: str, enabled: bool) -> CultureRow | None:
        return self._replace(code, enabled=enabled)

    async def db_clear_default(self, conn: Any) -> None:
        for code, row in list(self.rows.items()):
            if row.is_default:
                self._replace(code, is_default=False)

    async def db_mark_default(self, conn: Any, code: str) -> CultureRow | None:
        # Même garde que l'index unique partiel : deux défauts simultanés sont refusés.
        assert not any(r.is_default for r in self.rows.values()), "two default cultures"
        return self._replace(code, is_default=True)


@pytest.fixture()
def fake_repo(monkeypatch: pytest.MonkeyPatch) -> _FakeRepo:
    from app.db.repositories import cultures as repo_mod

    fake = _FakeRepo()
    for name in ("db_list", "db_get", "db_set_enabled", "db_clear_default", "db_mark_default"):
        monkeypatch.setattr(repo_mod, name, getattr(fake, name))
    return fake


@pytest.fixture()
def audit(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    from app.services import cultures as svc_mod

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


# ─── Autorisation ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("method", "path"), [("get", _URL), ("patch", f"{_URL}/de")])
async def test_cultures_routes_non_admin_returns_403(
    fake_repo: _FakeRepo, audit: AsyncMock, method: str, path: str
) -> None:
    async with _make_client() as client:
        kwargs: dict[str, Any] = {"headers": _user()}
        if method == "patch":
            kwargs["json"] = {"enabled": True}
        r = await getattr(client, method)(path, **kwargs)
    assert r.status_code == 403
    assert fake_repo.rows["de"].enabled is False
    audit.assert_not_awaited()


async def test_cultures_routes_anonymous_is_refused(fake_repo: _FakeRepo, audit: AsyncMock) -> None:
    async with _make_client() as client:
        r = await client.get(_URL)
    assert r.status_code in (401, 403)


# ─── Liste ───────────────────────────────────────────────────────────────────


async def test_list_cultures_returns_all_fields(fake_repo: _FakeRepo, audit: AsyncMock) -> None:
    async with _make_client() as client:
        r = await client.get(_URL, headers=_admin())
    assert r.status_code == 200
    items = r.json()["items"]
    assert [i["code"] for i in items] == ["en", "fr", "de"]
    assert set(items[0]) == {
        "code",
        "english_name",
        "native_name",
        "enabled",
        "is_default",
        "updated_at",
    }
    by_code = {i["code"]: i for i in items}
    assert by_code["en"]["is_default"] is True
    assert by_code["de"]["enabled"] is False


# ─── Activation ──────────────────────────────────────────────────────────────


async def test_enable_culture_updates_row_and_audits(
    fake_repo: _FakeRepo, audit: AsyncMock
) -> None:
    async with _make_client() as client:
        r = await client.patch(f"{_URL}/de", headers=_admin(), json={"enabled": True})
    assert r.status_code == 200
    assert r.json()["enabled"] is True
    assert fake_repo.rows["de"].enabled is True
    audit.assert_awaited_once()
    assert audit.await_args.args[1] == "culture.enabled"
    assert audit.await_args.kwargs["metadata"] == {"code": "de"}


async def test_disable_culture_audits_disabled(fake_repo: _FakeRepo, audit: AsyncMock) -> None:
    async with _make_client() as client:
        r = await client.patch(f"{_URL}/fr", headers=_admin(), json={"enabled": False})
    assert r.status_code == 200
    assert fake_repo.rows["fr"].enabled is False
    assert audit.await_args.args[1] == "culture.disabled"


async def test_patch_culture_without_change_does_not_audit(
    fake_repo: _FakeRepo, audit: AsyncMock
) -> None:
    async with _make_client() as client:
        r = await client.patch(f"{_URL}/fr", headers=_admin(), json={"enabled": True})
    assert r.status_code == 200
    audit.assert_not_awaited()


async def test_disable_default_culture_returns_409(fake_repo: _FakeRepo, audit: AsyncMock) -> None:
    async with _make_client() as client:
        r = await client.patch(f"{_URL}/en", headers=_admin(), json={"enabled": False})
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "default_culture_cannot_be_disabled"
    assert fake_repo.rows["en"].enabled is True
    audit.assert_not_awaited()


# ─── Culture par défaut ──────────────────────────────────────────────────────


async def test_make_default_moves_flag_and_audits_previous(
    fake_repo: _FakeRepo, audit: AsyncMock
) -> None:
    async with _make_client() as client:
        r = await client.patch(f"{_URL}/fr", headers=_admin(), json={"is_default": True})
    assert r.status_code == 200
    assert r.json()["is_default"] is True
    assert fake_repo.rows["fr"].is_default is True
    assert fake_repo.rows["en"].is_default is False
    assert audit.await_args.args[1] == "culture.default_changed"
    assert audit.await_args.kwargs["metadata"] == {"code": "fr", "previous_default": "en"}


async def test_make_default_on_disabled_culture_returns_409(
    fake_repo: _FakeRepo, audit: AsyncMock
) -> None:
    async with _make_client() as client:
        r = await client.patch(f"{_URL}/de", headers=_admin(), json={"is_default": True})
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "culture_disabled"
    assert fake_repo.rows["en"].is_default is True
    audit.assert_not_awaited()


async def test_enable_and_make_default_in_one_request_succeeds(
    fake_repo: _FakeRepo, audit: AsyncMock
) -> None:
    async with _make_client() as client:
        r = await client.patch(
            f"{_URL}/de", headers=_admin(), json={"enabled": True, "is_default": True}
        )
    assert r.status_code == 200
    assert fake_repo.rows["de"].enabled is True
    assert fake_repo.rows["de"].is_default is True
    assert [c.args[1] for c in audit.await_args_list] == [
        "culture.enabled",
        "culture.default_changed",
    ]


# ─── Entrées refusées ────────────────────────────────────────────────────────


async def test_patch_unknown_culture_returns_404(fake_repo: _FakeRepo, audit: AsyncMock) -> None:
    async with _make_client() as client:
        r = await client.patch(f"{_URL}/xx", headers=_admin(), json={"enabled": True})
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "culture_not_found"


@pytest.mark.parametrize("code", ["FR", "fra", "f", "fr-FR", "1a"])
async def test_patch_malformed_code_returns_422(
    fake_repo: _FakeRepo, audit: AsyncMock, code: str
) -> None:
    async with _make_client() as client:
        r = await client.patch(f"{_URL}/{code}", headers=_admin(), json={"enabled": True})
    assert r.status_code == 422


@pytest.mark.parametrize(
    "body",
    [{}, {"is_default": False}, {"enabled": None}, {"enabled": True, "unknown": 1}],
)
async def test_patch_invalid_body_returns_422(
    fake_repo: _FakeRepo, audit: AsyncMock, body: dict[str, Any]
) -> None:
    async with _make_client() as client:
        r = await client.patch(f"{_URL}/de", headers=_admin(), json=body)
    assert r.status_code == 422
    assert fake_repo.rows["de"].enabled is False
