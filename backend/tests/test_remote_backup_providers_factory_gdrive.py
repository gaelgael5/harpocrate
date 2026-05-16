"""La factory get_provider supporte 'gdrive' et SUPPORTED_KINDS le contient."""

from __future__ import annotations

from app.services.remote_backup_providers import SUPPORTED_KINDS, get_provider
from app.services.remote_backup_providers.gdrive import GoogleDriveProvider


def test_supported_kinds_contains_gdrive() -> None:
    assert "gdrive" in SUPPORTED_KINDS


def test_factory_returns_gdrive_provider() -> None:
    p = get_provider(
        "gdrive",
        {"client_id": "id", "folder_name": "F"},
        {"client_secret": "s", "refresh_token": "r"},
    )
    assert isinstance(p, GoogleDriveProvider)
