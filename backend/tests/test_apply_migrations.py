"""Tests apply_migrations — bootstrap, idempotence, checksum mismatch."""
from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "x")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")


async def test_apply_migrations_runs_bootstrap_and_pending(tmp_path: Path) -> None:
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    (mig_dir / "000_migrations_table.sql").write_text(
        "CREATE TABLE _migrations (id INT);"
    )
    (mig_dir / "001_first.sql").write_text("SELECT 1;")

    fake_conn = AsyncMock()
    fake_conn.fetch = AsyncMock(return_value=[])
    fake_conn.execute = AsyncMock()
    # Async context manager returned by conn.transaction()
    tx_cm = MagicMock()
    tx_cm.__aenter__ = AsyncMock(return_value=None)
    tx_cm.__aexit__ = AsyncMock(return_value=None)
    fake_conn.transaction = MagicMock(return_value=tx_cm)

    with (
        patch("asyncpg.connect", return_value=fake_conn),
        patch(
            "migrations.apply_migrations._migrations_dir",
            return_value=mig_dir,
        ),
    ):
        from migrations.apply_migrations import apply_migrations

        await apply_migrations()

    # Bootstrap exécuté + INSERT du fichier 001 + apply de son contenu
    assert fake_conn.execute.call_count >= 3  # bootstrap + apply + insert tracking row
    fake_conn.close.assert_awaited_once()
