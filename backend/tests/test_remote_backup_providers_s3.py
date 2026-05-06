"""Tests S3CompatibleProvider — validation des inputs (LOT_55).

Les tests réseau (head_bucket réel) sortent du scope unitaire.
"""
from __future__ import annotations

import base64
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "x")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")


def test_init_requires_bucket() -> None:
    from app.services.remote_backup_providers.s3_compatible import S3CompatibleProvider
    with pytest.raises(ValueError, match="bucket"):
        S3CompatibleProvider(
            config={"region": "us-east-1"},
            credentials={"access_key_id": "k", "secret_access_key": "s"},
        )


def test_init_requires_region() -> None:
    from app.services.remote_backup_providers.s3_compatible import S3CompatibleProvider
    with pytest.raises(ValueError, match="region"):
        S3CompatibleProvider(
            config={"bucket": "b"},
            credentials={"access_key_id": "k", "secret_access_key": "s"},
        )


def test_init_requires_access_key_id() -> None:
    from app.services.remote_backup_providers.s3_compatible import S3CompatibleProvider
    with pytest.raises(ValueError, match="access_key_id"):
        S3CompatibleProvider(
            config={"bucket": "b", "region": "r"},
            credentials={"secret_access_key": "s"},
        )


def test_init_requires_secret_access_key() -> None:
    from app.services.remote_backup_providers.s3_compatible import S3CompatibleProvider
    with pytest.raises(ValueError, match="secret_access_key"):
        S3CompatibleProvider(
            config={"bucket": "b", "region": "r"},
            credentials={"access_key_id": "k"},
        )


def test_init_accepts_valid_config_with_endpoint() -> None:
    from app.services.remote_backup_providers.s3_compatible import S3CompatibleProvider
    p = S3CompatibleProvider(
        config={
            "bucket": "harpo-backups",
            "region": "auto",
            "endpoint_url": "https://acct.r2.cloudflarestorage.com",
            "prefix": "node-paris/",
            "path_style": True,
        },
        credentials={"access_key_id": "AKIA...", "secret_access_key": "secret"},
    )
    assert p._bucket == "harpo-backups"
    assert p._endpoint_url == "https://acct.r2.cloudflarestorage.com"
    assert p._prefix == "node-paris/"
    assert p._path_style is True


@pytest.mark.asyncio
async def test_test_connection_calls_head_bucket() -> None:
    from app.services.remote_backup_providers.s3_compatible import S3CompatibleProvider

    fake_client = MagicMock()
    fake_client.head_bucket = MagicMock(return_value={})

    p = S3CompatibleProvider(
        config={"bucket": "b", "region": "r"},
        credentials={"access_key_id": "k", "secret_access_key": "s"},
    )
    with patch.object(p, "_make_client", return_value=fake_client):
        await p.test_connection()
    fake_client.head_bucket.assert_called_once_with(Bucket="b")


@pytest.mark.asyncio
async def test_test_connection_wraps_errors() -> None:
    from app.services.remote_backup_providers.base import RemoteBackupProviderError
    from app.services.remote_backup_providers.s3_compatible import S3CompatibleProvider

    fake_client = MagicMock()
    fake_client.head_bucket = MagicMock(side_effect=RuntimeError("denied"))

    p = S3CompatibleProvider(
        config={"bucket": "b", "region": "r"},
        credentials={"access_key_id": "k", "secret_access_key": "s"},
    )
    with (
        patch.object(p, "_make_client", return_value=fake_client),
        pytest.raises(RemoteBackupProviderError, match="denied"),
    ):
        await p.test_connection()


@pytest.mark.asyncio
async def test_upload_stream_buffers_and_uploads() -> None:
    from app.services.remote_backup_providers.s3_compatible import S3CompatibleProvider

    fake_client = MagicMock()
    fake_client.upload_fileobj = MagicMock()

    p = S3CompatibleProvider(
        config={"bucket": "b", "region": "r", "prefix": "pf/"},
        credentials={"access_key_id": "k", "secret_access_key": "s"},
    )

    async def source() -> Any:
        for chunk in (b"hello ", b"world"):
            yield chunk

    with patch.object(p, "_make_client", return_value=fake_client):
        total = await p.upload_stream("backup.tar.age", source())

    assert total == 11  # len("hello world")
    fake_client.upload_fileobj.assert_called_once()
    args = fake_client.upload_fileobj.call_args.args
    # args = (fileobj, bucket, key)
    assert args[1] == "b"
    assert args[2] == "pf/backup.tar.age"


@pytest.mark.asyncio
async def test_upload_stream_rejects_path_separators() -> None:
    from app.services.remote_backup_providers.s3_compatible import S3CompatibleProvider

    p = S3CompatibleProvider(
        config={"bucket": "b", "region": "r"},
        credentials={"access_key_id": "k", "secret_access_key": "s"},
    )

    async def empty() -> Any:
        if False:
            yield b""

    with pytest.raises(ValueError, match="path separators"):
        await p.upload_stream("../etc/passwd", empty())
