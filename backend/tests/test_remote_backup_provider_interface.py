"""L'interface RemoteBackupProvider.test_connection retourne un dict | None."""

from __future__ import annotations

import inspect


def test_test_connection_returns_optional_dict() -> None:
    from app.services.remote_backup_providers.base import RemoteBackupProvider

    src = inspect.getsource(RemoteBackupProvider.test_connection)
    assert "dict[str, Any] | None" in src or "Optional[dict[str, Any]]" in src
