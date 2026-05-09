"""Tests provider SFTP — validation des paramètres + comportement avec mocks asyncssh."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.remote_backup_providers.base import RemoteBackupProviderError
from app.services.remote_backup_providers.sftp import SftpProvider

# ─── Validation des inputs ────────────────────────────────────────────────────


def test_init_requires_host() -> None:
    with pytest.raises(ValueError, match="host"):
        SftpProvider(config={}, credentials={"username": "u", "password": "p"})


def test_init_requires_username() -> None:
    with pytest.raises(ValueError, match="username"):
        SftpProvider(config={"host": "h"}, credentials={"password": "p"})


def test_init_password_method_requires_password() -> None:
    with pytest.raises(ValueError, match="password"):
        SftpProvider(config={"host": "h"}, credentials={"username": "u", "auth_method": "password"})


def test_init_private_key_method_requires_key() -> None:
    with pytest.raises(ValueError, match="private_key"):
        SftpProvider(
            config={"host": "h"},
            credentials={"username": "u", "auth_method": "private_key"},
        )


def test_init_rejects_invalid_auth_method() -> None:
    with pytest.raises(ValueError, match="auth_method"):
        SftpProvider(
            config={"host": "h"},
            credentials={"username": "u", "auth_method": "invalid", "password": "p"},
        )


def test_init_invalid_port_type() -> None:
    with pytest.raises(ValueError, match="port"):
        SftpProvider(
            config={"host": "h", "port": "not-a-number"},
            credentials={"username": "u", "password": "p"},
        )


def test_init_accepts_valid_password_auth() -> None:
    p = SftpProvider(
        config={"host": "h", "port": 22, "remote_path": "/x"},
        credentials={"username": "u", "password": "p"},
    )
    assert p._host == "h"
    assert p._port == 22
    assert p._remote_path == "/x"


# ─── Comportement réseau (mock asyncssh) ──────────────────────────────────────


def _make_provider() -> SftpProvider:
    return SftpProvider(
        config={"host": "sftp.test", "port": 2222, "remote_path": "/dest"},
        credentials={"username": "alice", "password": "wonderland"},
    )


@pytest.mark.asyncio
async def test_test_connection_success() -> None:
    """test_connection ouvre, ensure dir, list, ferme — sans lever."""
    sftp_mock = MagicMock()
    sftp_mock.makedirs = AsyncMock(return_value=None)
    sftp_mock.listdir = AsyncMock(return_value=[])
    sftp_ctx = MagicMock()
    sftp_ctx.__aenter__ = AsyncMock(return_value=sftp_mock)
    sftp_ctx.__aexit__ = AsyncMock(return_value=None)

    conn_mock = MagicMock()
    conn_mock.start_sftp_client = MagicMock(return_value=sftp_ctx)
    conn_mock.close = MagicMock()
    conn_mock.wait_closed = AsyncMock()

    with patch("asyncssh.connect", AsyncMock(return_value=conn_mock)):
        await _make_provider().test_connection()

    sftp_mock.makedirs.assert_awaited_once_with("/dest", exist_ok=True)
    sftp_mock.listdir.assert_awaited_once_with("/dest")
    conn_mock.close.assert_called_once()


@pytest.mark.asyncio
async def test_test_connection_wraps_oserror_into_provider_error() -> None:
    """Une OSError au connect est transformée en RemoteBackupProviderError."""
    with (
        patch("asyncssh.connect", AsyncMock(side_effect=OSError("network unreachable"))),
        pytest.raises(RemoteBackupProviderError, match="connection failed"),
    ):
        await _make_provider().test_connection()


@pytest.mark.asyncio
async def test_test_connection_wraps_listdir_failure() -> None:
    """Un échec de listdir (après makedirs OK) → RemoteBackupProviderError avec mention du path."""
    sftp_mock = MagicMock()
    sftp_mock.makedirs = AsyncMock(return_value=None)
    sftp_mock.listdir = AsyncMock(side_effect=OSError("permission denied"))
    sftp_ctx = MagicMock()
    sftp_ctx.__aenter__ = AsyncMock(return_value=sftp_mock)
    sftp_ctx.__aexit__ = AsyncMock(return_value=None)

    conn_mock = MagicMock()
    conn_mock.start_sftp_client = MagicMock(return_value=sftp_ctx)
    conn_mock.close = MagicMock()
    conn_mock.wait_closed = AsyncMock()

    with (
        patch("asyncssh.connect", AsyncMock(return_value=conn_mock)),
        pytest.raises(RemoteBackupProviderError, match="remote_path"),
    ):
        await _make_provider().test_connection()


@pytest.mark.asyncio
async def test_test_connection_wraps_makedirs_failure() -> None:
    """Un échec de makedirs (permission denied sur parent) → RemoteBackupProviderError."""
    sftp_mock = MagicMock()
    sftp_mock.makedirs = AsyncMock(side_effect=OSError("permission denied"))
    sftp_mock.listdir = AsyncMock(return_value=[])
    sftp_ctx = MagicMock()
    sftp_ctx.__aenter__ = AsyncMock(return_value=sftp_mock)
    sftp_ctx.__aexit__ = AsyncMock(return_value=None)

    conn_mock = MagicMock()
    conn_mock.start_sftp_client = MagicMock(return_value=sftp_ctx)
    conn_mock.close = MagicMock()
    conn_mock.wait_closed = AsyncMock()

    with (
        patch("asyncssh.connect", AsyncMock(return_value=conn_mock)),
        pytest.raises(RemoteBackupProviderError, match="cannot create remote_path"),
    ):
        await _make_provider().test_connection()


@pytest.mark.asyncio
async def test_upload_stream_writes_all_chunks_and_returns_total() -> None:
    """upload_stream consomme l'AsyncIterator et retourne le nombre total d'octets."""
    written: list[bytes] = []
    remote_file = MagicMock()
    remote_file.write = AsyncMock(side_effect=lambda b: written.append(b))
    remote_file.__aenter__ = AsyncMock(return_value=remote_file)
    remote_file.__aexit__ = AsyncMock(return_value=None)

    sftp_mock = MagicMock()
    sftp_mock.makedirs = AsyncMock(return_value=None)
    sftp_mock.open = AsyncMock(return_value=remote_file)
    sftp_ctx = MagicMock()
    sftp_ctx.__aenter__ = AsyncMock(return_value=sftp_mock)
    sftp_ctx.__aexit__ = AsyncMock(return_value=None)

    conn_mock = MagicMock()
    conn_mock.start_sftp_client = MagicMock(return_value=sftp_ctx)
    conn_mock.close = MagicMock()
    conn_mock.wait_closed = AsyncMock()

    async def source() -> Any:
        for chunk in (b"hello ", b"world", b"!"):
            yield chunk

    with patch("asyncssh.connect", AsyncMock(return_value=conn_mock)):
        total = await _make_provider().upload_stream("backup.tar.gz", source())

    assert total == len(b"hello world!")
    assert b"".join(written) == b"hello world!"
    sftp_mock.makedirs.assert_awaited_once_with("/dest", exist_ok=True)
    sftp_mock.open.assert_awaited_once_with("/dest/backup.tar.gz", "wb")


@pytest.mark.asyncio
async def test_upload_stream_rejects_path_separators_in_filename() -> None:
    """Sécurité : le filename ne doit pas contenir de '/' (le remote_path est fixé en config)."""

    async def empty_source() -> Any:
        if False:
            yield b""

    with pytest.raises(ValueError, match="path separators"):
        await _make_provider().upload_stream("../etc/passwd", empty_source())
