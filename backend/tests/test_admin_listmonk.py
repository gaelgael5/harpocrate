"""Endpoints admin du paramétrage Listmonk — /v1/admin/listmonk (épic « Cultures et
templates Listmonk paramétrés en base », feature 2), et reprise des variables legacy.

Les repositories sont remplacés par des tables en mémoire : la base réelle (résolution,
import idempotent) est couverte par ``test_listmonk_templates_repository.py``.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.models.db.culture import CultureRow
from app.models.db.listmonk_template import ListmonkTemplateRow
from tests._helpers import TEST_AUDIENCE, TEST_KID, TEST_PUBLIC_JWK, make_jwt_token

_ADMIN_ROLE = "harpocrate-admin"
_URL = "/v1/admin/listmonk"
_NOW = datetime.datetime(2026, 11, 11, tzinfo=datetime.UTC)


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


@pytest.fixture()
def listmonk_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    # URL avec identifiants embarqués : ils ne doivent jamais remonter à l'UI.
    monkeypatch.setattr(settings, "listmonk_url", "https://api:pw@listmonk.example:9000/")
    monkeypatch.setattr(settings, "listmonk_user", "harpocrate-api")
    monkeypatch.setattr(settings, "listmonk_token", "very-secret-token")


class _FakeStore:
    """Cultures et templates en mémoire, mêmes signatures que les repositories réels."""

    def __init__(self) -> None:
        self.cultures = {
            "en": CultureRow(
                code="en",
                english_name="English",
                native_name="English",
                enabled=True,
                is_default=True,
                updated_at=_NOW,
            ),
            "de": CultureRow(
                code="de",
                english_name="German",
                native_name="Deutsch",
                enabled=False,
                is_default=False,
                updated_at=_NOW,
            ),
        }
        self.templates: dict[tuple[str, str], ListmonkTemplateRow] = {}

    async def db_get_culture(
        self, conn: Any, code: str, *, for_update: bool = False
    ) -> CultureRow | None:
        return self.cultures.get(code)

    async def db_list(self, conn: Any) -> list[ListmonkTemplateRow]:
        return [self.templates[k] for k in sorted(self.templates)]

    async def db_get_for_update(
        self, conn: Any, purpose: str, culture_code: str
    ) -> ListmonkTemplateRow | None:
        return self.templates.get((purpose, culture_code))

    async def db_upsert(
        self,
        conn: Any,
        *,
        purpose: str,
        culture_code: str,
        template_id: int,
        updated_by_user_id: uuid.UUID | None,
    ) -> ListmonkTemplateRow:
        row = ListmonkTemplateRow(
            purpose=purpose,
            culture_code=culture_code,
            template_id=template_id,
            updated_by_user_id=updated_by_user_id,
            updated_at=_NOW,
        )
        self.templates[(purpose, culture_code)] = row
        return row

    async def db_delete(self, conn: Any, purpose: str, culture_code: str) -> bool:
        return self.templates.pop((purpose, culture_code), None) is not None


@pytest.fixture()
def store(monkeypatch: pytest.MonkeyPatch) -> _FakeStore:
    from app.db.repositories import cultures as cultures_repo
    from app.db.repositories import listmonk_templates as repo

    fake = _FakeStore()
    monkeypatch.setattr(cultures_repo, "db_get", fake.db_get_culture)
    for name in ("db_list", "db_get_for_update", "db_upsert", "db_delete"):
        monkeypatch.setattr(repo, name, getattr(fake, name))
    return fake


@pytest.fixture()
def audit(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    from app.services import listmonk_templates as svc_mod

    mock = AsyncMock()
    monkeypatch.setattr(svc_mod, "audit_log_insert", mock)
    return mock


def _conn() -> MagicMock:
    conn = MagicMock()

    class _Tx:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *a: Any) -> None:
            return None

    conn.transaction = MagicMock(return_value=_Tx())
    return conn


def _make_client() -> AsyncClient:
    from app.db import pool as pool_mod
    from app.main import app

    conn = _conn()

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


_TPL = f"{_URL}/templates/recovery"


# ─── Autorisation ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("method", "path"),
    [("get", _URL), ("put", f"{_TPL}/en"), ("delete", f"{_TPL}/en")],
)
async def test_listmonk_routes_non_admin_returns_403(
    store: _FakeStore, audit: AsyncMock, method: str, path: str
) -> None:
    async with _make_client() as client:
        kwargs: dict[str, Any] = {"headers": _user()}
        if method == "put":
            kwargs["json"] = {"template_id": 5}
        r = await getattr(client, method)(path, **kwargs)
    assert r.status_code == 403
    assert store.templates == {}


# ─── Lecture ─────────────────────────────────────────────────────────────────


async def test_get_listmonk_settings_never_exposes_credentials(
    store: _FakeStore, audit: AsyncMock, listmonk_env: None
) -> None:
    async with _make_client() as client:
        await client.put(f"{_TPL}/en", headers=_admin(), json={"template_id": 5})
        r = await client.get(_URL, headers=_admin())
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"configured", "url", "purposes", "templates"}
    assert body["configured"] is True
    assert body["url"] == "https://listmonk.example:9000/"
    assert body["purposes"] == ["recovery"]
    assert body["templates"] == [
        {
            "purpose": "recovery",
            "culture_code": "en",
            "template_id": 5,
            "updated_at": "2026-11-11T00:00:00Z",
        }
    ]
    assert "very-secret-token" not in r.text
    assert "harpocrate-api" not in r.text
    assert "pw@" not in r.text


async def test_get_listmonk_settings_unconfigured(
    store: _FakeStore, audit: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "listmonk_url", "")
    async with _make_client() as client:
        r = await client.get(_URL, headers=_admin())
    assert r.json()["configured"] is False
    assert r.json()["url"] == ""


# ─── Écriture ────────────────────────────────────────────────────────────────


async def test_put_template_creates_then_updates_with_audit(
    store: _FakeStore, audit: AsyncMock
) -> None:
    async with _make_client() as client:
        r1 = await client.put(f"{_TPL}/en", headers=_admin(), json={"template_id": 5})
        r2 = await client.put(f"{_TPL}/en", headers=_admin(), json={"template_id": 9})
    assert r1.status_code == 200
    assert r2.json()["template_id"] == 9
    assert store.templates[("recovery", "en")].template_id == 9
    metas = [c.kwargs["metadata"] for c in audit.await_args_list]
    assert [c.args[1] for c in audit.await_args_list] == ["listmonk_template.set"] * 2
    assert metas[0]["previous_template_id"] is None
    assert metas[1] == {
        "purpose": "recovery",
        "culture_code": "en",
        "template_id": 9,
        "previous_template_id": 5,
    }


async def test_put_same_template_does_not_audit(store: _FakeStore, audit: AsyncMock) -> None:
    async with _make_client() as client:
        await client.put(f"{_TPL}/en", headers=_admin(), json={"template_id": 5})
        r = await client.put(f"{_TPL}/en", headers=_admin(), json={"template_id": 5})
    assert r.status_code == 200
    audit.assert_awaited_once()


async def test_put_template_on_disabled_culture_returns_409(
    store: _FakeStore, audit: AsyncMock
) -> None:
    async with _make_client() as client:
        r = await client.put(f"{_TPL}/de", headers=_admin(), json={"template_id": 5})
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "culture_disabled"
    assert store.templates == {}


async def test_put_template_on_unknown_culture_returns_404(
    store: _FakeStore, audit: AsyncMock
) -> None:
    async with _make_client() as client:
        r = await client.put(f"{_TPL}/xx", headers=_admin(), json={"template_id": 5})
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "culture_not_found"


@pytest.mark.parametrize(
    ("path", "body"),
    [
        (f"{_URL}/templates/welcome/en", {"template_id": 5}),
        (f"{_TPL}/EN", {"template_id": 5}),
        (f"{_TPL}/en", {"template_id": 0}),
        (f"{_TPL}/en", {"template_id": 2_147_483_648}),
        (f"{_TPL}/en", {"template_id": "abc"}),
        (f"{_TPL}/en", {"template_id": 5, "extra": 1}),
        (f"{_TPL}/en", {}),
    ],
)
async def test_put_template_invalid_input_returns_422(
    store: _FakeStore, audit: AsyncMock, path: str, body: dict[str, Any]
) -> None:
    async with _make_client() as client:
        r = await client.put(path, headers=_admin(), json=body)
    assert r.status_code == 422
    assert store.templates == {}


async def test_delete_template_removes_row_with_audit(store: _FakeStore, audit: AsyncMock) -> None:
    async with _make_client() as client:
        await client.put(f"{_TPL}/en", headers=_admin(), json={"template_id": 5})
        r = await client.delete(f"{_TPL}/en", headers=_admin())
    assert r.status_code == 204
    assert store.templates == {}
    assert audit.await_args.args[1] == "listmonk_template.deleted"
    assert audit.await_args.kwargs["metadata"]["previous_template_id"] == 5


async def test_delete_missing_template_returns_404(store: _FakeStore, audit: AsyncMock) -> None:
    async with _make_client() as client:
        r = await client.delete(f"{_TPL}/en", headers=_admin())
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "template_not_found"
    audit.assert_not_awaited()


# ─── Reprise des variables legacy au boot ────────────────────────────────────


@pytest.fixture()
def legacy(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Témoin system_metadata et import en mémoire."""
    from app.db.repositories import listmonk_templates as repo
    from app.db.repositories import system_metadata as metadata_repo

    state: dict[str, Any] = {"marker": None, "imported": []}

    async def get_value(conn: Any, key: str) -> Any:
        return state["marker"]

    async def set_value(conn: Any, key: str, value: Any) -> None:
        state["marker"] = value

    async def db_import_legacy(conn: Any, purpose: str, templates: dict[str, int]) -> int:
        state["imported"].append((purpose, dict(templates)))
        return len(templates)

    monkeypatch.setattr(metadata_repo, "get_value", get_value)
    monkeypatch.setattr(metadata_repo, "set_value", set_value)
    monkeypatch.setattr(repo, "db_import_legacy", db_import_legacy)
    return state


async def test_import_legacy_env_templates_imports_set_values_once(
    legacy: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings
    from app.services import listmonk_templates as svc

    monkeypatch.setattr(settings, "listmonk_template_recovery_fr", 5)
    monkeypatch.setattr(settings, "listmonk_template_recovery_en", None)
    await svc.import_legacy_env_templates(_conn())
    await svc.import_legacy_env_templates(_conn())
    assert legacy["imported"] == [("recovery", {"fr": 5})]
    assert legacy["marker"] is True


async def test_import_legacy_env_templates_without_values_sets_marker_only(
    legacy: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings
    from app.services import listmonk_templates as svc

    monkeypatch.setattr(settings, "listmonk_template_recovery_fr", None)
    monkeypatch.setattr(settings, "listmonk_template_recovery_en", None)
    await svc.import_legacy_env_templates(_conn())
    assert legacy["imported"] == []
    assert legacy["marker"] is True


def test_settings_empty_legacy_template_env_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("HARPOCRATE_LISTMONK_TEMPLATE_RECOVERY_FR", "")
    monkeypatch.setenv("HARPOCRATE_LISTMONK_TEMPLATE_RECOVERY_EN", "6")
    s = Settings()
    assert s.listmonk_template_recovery_fr is None
    assert s.listmonk_template_recovery_en == 6
