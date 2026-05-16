"""Tests du provider GoogleDriveProvider."""

from __future__ import annotations

import pytest

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
