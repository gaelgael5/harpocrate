"""Tests résolution `users.id` pour les admins JWT (LOT_56)."""
from __future__ import annotations

import base64
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "x")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")


@pytest.fixture(autouse=True)
def mock_admin_user_resolver() -> None:
    """Override la fixture autouse conftest qui mocke
    `resolve_admin_user_id` — ici on TESTE cette fonction, donc on la
    veut intacte. Une fixture du même nom redéfinie au niveau module
    masque celle du conftest racine."""
    return None


def _patch_pool(monkeypatch: pytest.MonkeyPatch, conn: MagicMock) -> None:
    class _AcquireCtx:
        async def __aenter__(self) -> MagicMock:
            return conn

        async def __aexit__(self, *a: Any) -> None:
            pass

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_AcquireCtx())

    async def _fake_get_pool() -> MagicMock:
        return pool

    from app.services import admin_user_resolver
    monkeypatch.setattr(admin_user_resolver, "get_pool", _fake_get_pool)


@pytest.mark.asyncio
async def test_local_admin_resolves_via_keycloak_sub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Depuis l'unification : le local-admin est lookupé par keycloak_sub
    (qui vaut 'local-admin' en DB), comme un user Keycloak normal."""
    from app.services import admin_user_resolver

    expected_id = uuid4()
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=expected_id)  # get_id_by_keycloak_sub
    _patch_pool(monkeypatch, conn)

    resolved = await admin_user_resolver.resolve_admin_user_id(
        keycloak_sub="local-admin",
        email="admin@harpocrate.local",
        display_name="Local Admin",
    )

    assert resolved == expected_id


@pytest.mark.asyncio
async def test_local_admin_missing_row_creates_shell_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si la row local-admin manque (lifespan bootstrap pas exécuté), on
    crée un shell à la volée plutôt que de raise 500. Plus résilient."""
    from app.services import admin_user_resolver

    new_id = uuid4()
    conn = MagicMock()
    # 1er fetchval: get_id_by_keycloak_sub → None
    # 2e fetchval: insert_system_user → new_id
    conn.fetchval = AsyncMock(side_effect=[None, new_id])
    _patch_pool(monkeypatch, conn)

    resolved = await admin_user_resolver.resolve_admin_user_id(
        keycloak_sub="local-admin",
        email="admin@harpocrate.local",
        display_name=None,
    )
    assert resolved == new_id
    assert conn.fetchval.await_count == 2


@pytest.mark.asyncio
async def test_keycloak_admin_with_existing_row(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import admin_user_resolver

    expected_id = uuid4()
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=expected_id)  # premier SELECT id
    _patch_pool(monkeypatch, conn)

    resolved = await admin_user_resolver.resolve_admin_user_id(
        keycloak_sub="kc-sub-123",
        email="admin@yoops.org",
        display_name="Admin",
    )

    assert resolved == expected_id


@pytest.mark.asyncio
async def test_keycloak_admin_without_row_creates_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un admin Keycloak sans row → shell row is_system=TRUE créée à la volée."""
    from app.services import admin_user_resolver

    new_id = uuid4()
    conn = MagicMock()
    # 1er fetchval: get_id_by_keycloak_sub → None (absente)
    # 2e fetchval: insert_system_user → new_id
    conn.fetchval = AsyncMock(side_effect=[None, new_id])
    _patch_pool(monkeypatch, conn)

    resolved = await admin_user_resolver.resolve_admin_user_id(
        keycloak_sub="kc-new-456",
        email="newadmin@yoops.org",
        display_name="New Admin",
    )

    assert resolved == new_id
    assert conn.fetchval.await_count == 2
    insert_sql = conn.fetchval.await_args_list[1].args[0]
    assert "INSERT INTO users" in insert_sql
    assert "is_system" in insert_sql
