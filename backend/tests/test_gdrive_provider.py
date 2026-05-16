"""Tests du provider GoogleDriveProvider."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.remote_backup_providers.base import RemoteBackupProviderError
from app.services.remote_backup_providers.gdrive import GoogleDriveProvider

# ── Validation des inputs ────────────────────────────────────────────────────


def test_missing_client_id_raises() -> None:
    with pytest.raises(ValueError, match="client_id"):
        GoogleDriveProvider(
            config={"folder_name": "F"},
            credentials={"client_secret": "s", "refresh_token": "r"},
        )


def test_missing_client_secret_raises() -> None:
    with pytest.raises(ValueError, match="client_secret"):
        GoogleDriveProvider(
            config={"client_id": "id", "folder_name": "F"},
            credentials={"refresh_token": "r"},
        )


def test_missing_refresh_token_raises() -> None:
    with pytest.raises(ValueError, match="refresh_token"):
        GoogleDriveProvider(
            config={"client_id": "id", "folder_name": "F"},
            credentials={"client_secret": "s"},
        )


def test_missing_folder_name_raises() -> None:
    with pytest.raises(ValueError, match="folder_name"):
        GoogleDriveProvider(
            config={"client_id": "id"},
            credentials={"client_secret": "s", "refresh_token": "r"},
        )


def test_valid_inputs_construct() -> None:
    p = GoogleDriveProvider(
        config={"client_id": "id", "folder_name": "F"},
        credentials={"client_secret": "s", "refresh_token": "r"},
    )
    assert p is not None


# ── test_connection ──────────────────────────────────────────────────────────


@pytest.fixture
def _mock_gdrive_client():
    """Patch toute la couche gdrive_client. Retourne un namespace mocks."""
    with patch("app.services.remote_backup_providers.gdrive.gdrive_client") as m:
        m.build_credentials.return_value = MagicMock(name="creds")
        m.build_drive_service.return_value = MagicMock(name="drive")
        m.refresh.return_value = None
        yield m


def _files_list_response(items: list[dict] | None = None) -> dict:
    return {"files": items or []}


@pytest.mark.asyncio
async def test_test_connection_creates_folder_when_missing(_mock_gdrive_client) -> None:
    drive = _mock_gdrive_client.build_drive_service.return_value
    drive.files.return_value.list.return_value.execute.side_effect = [
        _files_list_response([]),  # lookup folder → vide
        _files_list_response([{"id": "x"}]),  # listing après création
    ]
    drive.files.return_value.create.return_value.execute.return_value = {"id": "new-folder-id"}

    p = GoogleDriveProvider(
        config={"client_id": "id", "folder_name": "Backups"},
        credentials={"client_secret": "s", "refresh_token": "r"},
    )
    patch_out = await p.test_connection("/ignored")
    assert patch_out == {"folder_id": "new-folder-id"}
    drive.files.return_value.create.assert_called_once()


@pytest.mark.asyncio
async def test_test_connection_finds_existing_folder(_mock_gdrive_client) -> None:
    drive = _mock_gdrive_client.build_drive_service.return_value
    drive.files.return_value.list.return_value.execute.side_effect = [
        _files_list_response([{"id": "existing-id"}]),
        _files_list_response([{"id": "any"}]),
    ]

    p = GoogleDriveProvider(
        config={"client_id": "id", "folder_name": "Backups"},
        credentials={"client_secret": "s", "refresh_token": "r"},
    )
    patch_out = await p.test_connection("/ignored")
    assert patch_out == {"folder_id": "existing-id"}
    drive.files.return_value.create.assert_not_called()


@pytest.mark.asyncio
async def test_test_connection_skips_lookup_when_folder_id_present(_mock_gdrive_client) -> None:
    drive = _mock_gdrive_client.build_drive_service.return_value
    drive.files.return_value.list.return_value.execute.return_value = _files_list_response(
        [{"id": "any"}]
    )

    p = GoogleDriveProvider(
        config={"client_id": "id", "folder_name": "Backups", "folder_id": "preset-id"},
        credentials={"client_secret": "s", "refresh_token": "r"},
    )
    patch_out = await p.test_connection("/ignored")
    assert patch_out is None  # folder_id déjà connu — pas de patch


@pytest.mark.asyncio
async def test_test_connection_refresh_error_raises(_mock_gdrive_client) -> None:
    from google.auth.exceptions import RefreshError

    _mock_gdrive_client.refresh.side_effect = RefreshError("invalid_grant")

    p = GoogleDriveProvider(
        config={"client_id": "id", "folder_name": "Backups"},
        credentials={"client_secret": "s", "refresh_token": "r"},
    )
    with pytest.raises(RemoteBackupProviderError, match="credentials_revoked"):
        await p.test_connection("/ignored")


@pytest.mark.asyncio
async def test_test_connection_http_error_raises(_mock_gdrive_client) -> None:
    from googleapiclient.errors import HttpError

    drive = _mock_gdrive_client.build_drive_service.return_value
    fake_resp = MagicMock(status=500, reason="Internal Server Error")
    drive.files.return_value.list.return_value.execute.side_effect = HttpError(
        resp=fake_resp, content=b'{"error": "boom"}'
    )

    p = GoogleDriveProvider(
        config={"client_id": "id", "folder_name": "Backups"},
        credentials={"client_secret": "s", "refresh_token": "r"},
    )
    with pytest.raises(RemoteBackupProviderError, match="drive_api_error"):
        await p.test_connection("/ignored")
