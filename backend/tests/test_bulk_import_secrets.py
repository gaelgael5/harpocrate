"""Tests du service `bulk_import_secrets` — focused unit tests avec mocks."""

from __future__ import annotations

import base64
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest


_WALLET_ID = uuid4()
_CALLER_ID = uuid4()
_TYPE_RAW = uuid4()
_TYPE_VERSION = uuid4()
_FAKE_ENC = base64.b64encode(b"encrypted-bytes").decode()


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "x")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")


def _make_conn(*, existing_secrets: dict[str, Any] | None = None) -> MagicMock:
    """Mock conn qui simule un wallet avec quelques secrets existants.

    `existing_secrets` : map name → {id} pour piloter `get_secret_by_name`.
    """
    existing = existing_secrets or {}

    conn = MagicMock()
    # transaction() context manager
    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=tx)
    tx.__aexit__ = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=tx)
    # Pas d'audit log côté DB direct — patché via monkeypatch dans les tests.
    conn.execute = AsyncMock()
    return conn, existing


def _patch_repos(monkeypatch: pytest.MonkeyPatch, *, existing_secrets: dict[str, Any]) -> dict:
    """Patch types_repo + secrets_repo + audit_log_insert. Retourne un
    dict d'enregistrement pour vérifier les appels."""
    from app.db.repositories import secret_types as types_repo
    from app.db.repositories import secrets as secrets_repo
    from app.services import secrets as secrets_svc

    log: dict[str, Any] = {"inserts": [], "updates": [], "audits": []}

    async def _raw_type(_c: Any) -> tuple[UUID, UUID]:
        return (_TYPE_RAW, _TYPE_VERSION)

    monkeypatch.setattr(types_repo, "get_raw_type_with_current_version_uuid", _raw_type)

    async def _by_name(_c: Any, *, wallet_id: UUID, name: str) -> Any:
        if name in existing_secrets:
            return {"id": existing_secrets[name]["id"]}
        return None

    monkeypatch.setattr(secrets_repo, "get_secret_by_name", _by_name)

    async def _insert(_c: Any, **kw: Any) -> UUID:
        new_id = uuid4()
        log["inserts"].append({**kw, "id": new_id})
        return new_id

    monkeypatch.setattr(secrets_repo, "insert_secret", _insert)

    async def _update(_c: Any, **kw: Any) -> int:
        log["updates"].append(kw)
        return 2  # nouvelle generation_version

    monkeypatch.setattr(secrets_repo, "update_secret_value", _update)

    async def _audit(_c: Any, _action: str, **kw: Any) -> int:
        log["audits"].append({"action": _action, **kw})
        return 1

    monkeypatch.setattr(secrets_svc, "audit_log_insert", _audit)

    return log


# ─── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_import_creates_new_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Aucun conflit → tous les secrets sont créés (action='created')."""
    from app.services.secrets import bulk_import_secrets

    conn, _ = _make_conn()
    log = _patch_repos(monkeypatch, existing_secrets={})

    result = await bulk_import_secrets(
        conn,
        wallet_id=_WALLET_ID,
        items=[
            {"name": "API_KEY", "encrypted_value": _FAKE_ENC, "override": False},
            {"name": "DB_PASS", "encrypted_value": _FAKE_ENC, "override": False},
        ],
        caller_user_id=_CALLER_ID,
        actor_ip=None,
    )

    assert result["summary"] == {"created": 2, "updated": 0, "skipped": 0, "failed": 0}
    assert all(item["action"] == "created" for item in result["items"])
    assert len(log["inserts"]) == 2
    assert len(log["updates"]) == 0
    # Type RAW appliqué sur tous
    assert all(ins["type_uuid"] == _TYPE_RAW for ins in log["inserts"])


@pytest.mark.asyncio
async def test_bulk_import_skips_existing_without_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Conflit + override=False → action='skipped', pas d'INSERT/UPDATE."""
    from app.services.secrets import bulk_import_secrets

    conn, _ = _make_conn()
    existing_id = uuid4()
    log = _patch_repos(
        monkeypatch, existing_secrets={"API_KEY": {"id": existing_id}}
    )

    result = await bulk_import_secrets(
        conn,
        wallet_id=_WALLET_ID,
        items=[
            {"name": "API_KEY", "encrypted_value": _FAKE_ENC, "override": False},
            {"name": "NEW_ONE", "encrypted_value": _FAKE_ENC, "override": False},
        ],
        caller_user_id=_CALLER_ID,
        actor_ip=None,
    )

    assert result["summary"] == {"created": 1, "updated": 0, "skipped": 1, "failed": 0}
    items_by_name = {item["name"]: item for item in result["items"]}
    assert items_by_name["API_KEY"]["action"] == "skipped"
    assert items_by_name["API_KEY"]["reason"] == "exists_without_override"
    assert items_by_name["NEW_ONE"]["action"] == "created"
    assert len(log["inserts"]) == 1  # juste NEW_ONE
    assert len(log["updates"]) == 0


@pytest.mark.asyncio
async def test_bulk_import_updates_existing_with_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Conflit + override=True → UPDATE, pas d'INSERT."""
    from app.services.secrets import bulk_import_secrets

    conn, _ = _make_conn()
    existing_id = uuid4()
    log = _patch_repos(
        monkeypatch, existing_secrets={"API_KEY": {"id": existing_id}}
    )

    result = await bulk_import_secrets(
        conn,
        wallet_id=_WALLET_ID,
        items=[
            {"name": "API_KEY", "encrypted_value": _FAKE_ENC, "override": True},
        ],
        caller_user_id=_CALLER_ID,
        actor_ip=None,
    )

    assert result["summary"] == {"created": 0, "updated": 1, "skipped": 0, "failed": 0}
    assert result["items"][0]["action"] == "updated"
    assert result["items"][0]["secret_id"] == str(existing_id)
    assert len(log["updates"]) == 1
    assert log["updates"][0]["secret_id"] == existing_id


@pytest.mark.asyncio
async def test_bulk_import_invalid_base64_marked_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Item avec encrypted_value non-base64 → action='failed', autres items
    continuent."""
    from app.services.secrets import bulk_import_secrets

    conn, _ = _make_conn()
    log = _patch_repos(monkeypatch, existing_secrets={})

    result = await bulk_import_secrets(
        conn,
        wallet_id=_WALLET_ID,
        items=[
            {"name": "BAD", "encrypted_value": "not-base64-!!!", "override": False},
            {"name": "GOOD", "encrypted_value": _FAKE_ENC, "override": False},
        ],
        caller_user_id=_CALLER_ID,
        actor_ip=None,
    )

    assert result["summary"]["failed"] == 1
    assert result["summary"]["created"] == 1
    failed_item = next(i for i in result["items"] if i["name"] == "BAD")
    assert failed_item["action"] == "failed"
    assert "invalid_base64" in failed_item["error"]


@pytest.mark.asyncio
async def test_bulk_import_empty_name_marked_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Item sans name → action='failed'."""
    from app.services.secrets import bulk_import_secrets

    conn, _ = _make_conn()
    _patch_repos(monkeypatch, existing_secrets={})

    result = await bulk_import_secrets(
        conn,
        wallet_id=_WALLET_ID,
        items=[
            {"name": "  ", "encrypted_value": _FAKE_ENC, "override": False},
        ],
        caller_user_id=_CALLER_ID,
        actor_ip=None,
    )

    assert result["summary"]["failed"] == 1
    assert "name is required" in result["items"][0]["error"]


@pytest.mark.asyncio
async def test_bulk_import_audit_log_per_item(monkeypatch: pytest.MonkeyPatch) -> None:
    """Chaque create/update produit une row audit_log avec action 'secret.bulk_imported'."""
    from app.services.secrets import bulk_import_secrets

    conn, _ = _make_conn()
    existing_id = uuid4()
    log = _patch_repos(
        monkeypatch, existing_secrets={"OLD": {"id": existing_id}}
    )

    await bulk_import_secrets(
        conn,
        wallet_id=_WALLET_ID,
        items=[
            {"name": "NEW", "encrypted_value": _FAKE_ENC, "override": False},
            {"name": "OLD", "encrypted_value": _FAKE_ENC, "override": True},
        ],
        caller_user_id=_CALLER_ID,
        actor_ip="1.2.3.4",
    )

    assert len(log["audits"]) == 2
    assert all(a["action"] == "secret.bulk_imported" for a in log["audits"])
    actions_in_meta = {a["metadata"]["action"] for a in log["audits"]}
    assert actions_in_meta == {"created", "updated"}
