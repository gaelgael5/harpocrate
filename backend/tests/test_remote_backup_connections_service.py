"""Tests du service remote_backup_connections — chiffrement transparent + DTO sans creds."""

from __future__ import annotations

import base64
import datetime
import json
import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "x")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")
    import app.core.config

    app.core.config.settings = app.core.config.Settings()


_NOW = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.UTC)
_CALLER_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_CONN_ID = uuid.UUID("11111111-0000-0000-0000-000000000001")


def _fake_row(
    *,
    name: str = "Backup OVH",
    kind: str = "sftp",
    config: dict[str, Any] | None = None,
    encrypted_blob: bytes = b"\x00" * 30,  # placeholder
    deleted_at: datetime.datetime | None = None,
) -> dict[str, Any]:
    if config is None:
        config = {"host": "sftp.example.com", "port": 22, "remote_path": "/backups"}
    return {
        "id": _CONN_ID,
        "name": name,
        "kind": kind,
        "config": json.dumps(config),
        "credentials_encrypted": encrypted_blob,
        "created_at": _NOW,
        "updated_at": _NOW,
        "created_by_user_id": _CALLER_ID,
        "deleted_at": deleted_at,
    }


@pytest.mark.asyncio
async def test_create_encrypts_and_inserts() -> None:
    """create_connection chiffre les credentials avant l'INSERT."""
    from app.services import remote_backup_connections as svc
    from app.services import remote_backup_crypto as crypto

    insert_args: dict[str, Any] = {}

    async def fake_insert(
        conn: Any,
        *,
        name: str,
        kind: str,
        config: dict,
        credentials_encrypted: bytes,
        created_by_user_id: Any,
    ) -> uuid.UUID:
        insert_args["name"] = name
        insert_args["kind"] = kind
        insert_args["config"] = config
        insert_args["credentials_encrypted"] = credentials_encrypted
        insert_args["created_by_user_id"] = created_by_user_id
        return _CONN_ID

    from app.db.repositories import remote_backup_connections as repo

    original = repo.insert
    repo.insert = fake_insert  # type: ignore[assignment]
    try:
        new_id = await svc.create_connection(
            conn=MagicMock(),
            name="OVH Cold",
            kind="sftp",
            config={"host": "h", "port": 22, "remote_path": "/x"},
            credentials={"username": "u", "password": "p"},
            created_by_user_id=_CALLER_ID,
        )
    finally:
        repo.insert = original  # type: ignore[assignment]

    assert new_id == _CONN_ID
    # Vérifier que les credentials ont été chiffrés (pas de "u"/"p" en clair dans le blob)
    blob = insert_args["credentials_encrypted"]
    assert isinstance(blob, bytes) and len(blob) > 16
    assert b'"u"' not in blob and b'"p"' not in blob
    # Round-trip déchiffrement pour confirmer
    decrypted = crypto.decrypt_credentials(blob)
    assert decrypted == {"username": "u", "password": "p"}


@pytest.mark.asyncio
async def test_dto_does_not_expose_credentials() -> None:
    """RemoteBackupConnection.to_dict() ne contient PAS de credentials."""
    from app.services import remote_backup_connections as svc

    row = _fake_row()

    async def fake_list(conn: Any) -> list[Any]:
        return [row]  # type: ignore[return-value]

    from app.db.repositories import remote_backup_connections as repo

    original = repo.list_active
    repo.list_active = fake_list  # type: ignore[assignment]
    try:
        items = await svc.list_connections(MagicMock())
    finally:
        repo.list_active = original  # type: ignore[assignment]

    assert len(items) == 1
    d = items[0].to_dict()
    # Vérifier qu'aucun champ secret n'est dans le DTO. On teste au niveau
    # des CLÉS du dict (récursivement), pas en substring du JSON sérialisé
    # — sinon `has_credentials` (champ booléen public légitime) déclenche
    # un faux positif sur "credentials".
    _assert_no_secret_keys(d)


def _assert_no_secret_keys(obj: object) -> None:
    """Assert récursivement qu'aucune clé secrète (credentials, password,
    private_key, encrypted) n'apparait dans un dict/liste imbriqué.
    Tolère `has_credentials` (booléen public)."""
    secret_keys = {"credentials", "password", "private_key", "secret_key", "encrypted_value"}
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert k not in secret_keys, f"DTO leaks secret key: {k}"
            _assert_no_secret_keys(v)
    elif isinstance(obj, list):
        for item in obj:
            _assert_no_secret_keys(item)


@pytest.mark.asyncio
async def test_get_decrypted_credentials_returns_clear_dict() -> None:
    """get_decrypted_credentials renvoie le dict en clair (pour usage interne uniquement)."""
    from app.services import remote_backup_connections as svc
    from app.services import remote_backup_crypto as crypto

    creds = {"username": "alice", "password": "wonderland"}
    blob = crypto.encrypt_credentials(creds)
    row = _fake_row(encrypted_blob=blob)

    async def fake_get(conn: Any, connection_id: uuid.UUID) -> Any:
        return row  # type: ignore[return-value]

    from app.db.repositories import remote_backup_connections as repo

    original = repo.get_by_id
    repo.get_by_id = fake_get  # type: ignore[assignment]
    try:
        decrypted = await svc.get_decrypted_credentials(MagicMock(), _CONN_ID)
    finally:
        repo.get_by_id = original  # type: ignore[assignment]

    assert decrypted == creds


@pytest.mark.asyncio
async def test_get_returns_none_for_soft_deleted() -> None:
    from app.services import remote_backup_connections as svc

    row = _fake_row(deleted_at=_NOW)

    async def fake_get(conn: Any, connection_id: uuid.UUID) -> Any:
        return row  # type: ignore[return-value]

    from app.db.repositories import remote_backup_connections as repo

    original = repo.get_by_id
    repo.get_by_id = fake_get  # type: ignore[assignment]
    try:
        result = await svc.get_connection(MagicMock(), _CONN_ID)
        decrypted = await svc.get_decrypted_credentials(MagicMock(), _CONN_ID)
    finally:
        repo.get_by_id = original  # type: ignore[assignment]

    assert result is None
    assert decrypted is None


@pytest.mark.asyncio
async def test_update_with_new_credentials_re_encrypts() -> None:
    from app.services import remote_backup_connections as svc
    from app.services import remote_backup_crypto as crypto

    captured: dict[str, Any] = {}

    async def fake_update(
        conn: Any,
        *,
        connection_id: uuid.UUID,
        name: str | None,
        config: dict | None,
        credentials_encrypted: bytes | None,
    ) -> int:
        captured["credentials_encrypted"] = credentials_encrypted
        return 1

    from app.db.repositories import remote_backup_connections as repo

    original = repo.update
    repo.update = fake_update  # type: ignore[assignment]
    try:
        n = await svc.update_connection(
            conn=MagicMock(),
            connection_id=_CONN_ID,
            credentials={"username": "new", "password": "rotated"},
        )
    finally:
        repo.update = original  # type: ignore[assignment]

    assert n == 1
    blob = captured["credentials_encrypted"]
    assert blob is not None
    decrypted = crypto.decrypt_credentials(blob)
    assert decrypted == {"username": "new", "password": "rotated"}


@pytest.mark.asyncio
async def test_update_without_credentials_does_not_touch_them() -> None:
    """Si credentials=None, on n'envoie rien au repo pour ce champ."""
    from app.services import remote_backup_connections as svc

    captured: dict[str, Any] = {}

    async def fake_update(
        conn: Any,
        *,
        connection_id: uuid.UUID,
        name: str | None,
        config: dict | None,
        credentials_encrypted: bytes | None,
    ) -> int:
        captured["credentials_encrypted"] = credentials_encrypted
        return 1

    from app.db.repositories import remote_backup_connections as repo

    original = repo.update
    repo.update = fake_update  # type: ignore[assignment]
    try:
        await svc.update_connection(conn=MagicMock(), connection_id=_CONN_ID, name="renamed only")
    finally:
        repo.update = original  # type: ignore[assignment]

    assert captured["credentials_encrypted"] is None
