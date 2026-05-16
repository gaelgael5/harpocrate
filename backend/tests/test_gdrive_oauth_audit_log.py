"""Les opérations OAuth gdrive appellent audit_log_insert (sans secret)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_create_pending_session_calls_audit_log() -> None:
    """create_pending_session appelle audit_log_insert avec action correcte."""
    fake_insert = AsyncMock()
    fake_audit = AsyncMock()
    fake_flow = MagicMock()
    fake_flow.authorization_url.return_value = ("https://x", "STATE")
    fake_conn = MagicMock()
    with (
        patch(
            "app.services.gdrive_oauth_session.gdrive_client.build_flow",
            return_value=fake_flow,
        ),
        patch(
            "app.services.gdrive_oauth_session.repo.insert",
            fake_insert,
        ),
        patch(
            "app.services.gdrive_oauth_session.audit_log_insert",
            fake_audit,
        ),
    ):
        from app.services import gdrive_oauth_session as svc

        await svc.create_pending_session(
            fake_conn,
            name="Backups",
            client_id="cid",
            client_secret="SECRET",
            folder_name="F",
            redirect_uri="u",
            target_connection_id=None,
            created_by_user_id=None,
        )
    fake_audit.assert_called_once()
    call = fake_audit.call_args
    # action est le 2e positional arg (index 1)
    assert call.args[1] == "remote_backup.gdrive.oauth_started"
    # Aucun secret ne fuit dans metadata
    raw = str(call)
    assert "SECRET" not in raw


@pytest.mark.asyncio
async def test_create_pending_session_audit_metadata_has_no_client_secret() -> None:
    """Le metadata d'audit ne contient pas client_secret, seulement les champs safe."""
    fake_audit = AsyncMock()
    fake_flow = MagicMock()
    fake_flow.authorization_url.return_value = ("https://x", "S")
    fake_conn = MagicMock()
    with (
        patch("app.services.gdrive_oauth_session.gdrive_client.build_flow", return_value=fake_flow),
        patch("app.services.gdrive_oauth_session.repo.insert", AsyncMock()),
        patch("app.services.gdrive_oauth_session.audit_log_insert", fake_audit),
    ):
        from app.services import gdrive_oauth_session as svc

        await svc.create_pending_session(
            fake_conn,
            name="Drive perso",
            client_id="cid",
            client_secret="VERY-SECRET",
            folder_name="MyFolder",
            redirect_uri="https://h/c",
            target_connection_id=None,
            created_by_user_id=None,
        )
    call_kwargs = fake_audit.call_args.kwargs
    metadata = call_kwargs.get("metadata", {})
    assert metadata.get("connection_name") == "Drive perso"
    assert metadata.get("folder_name") == "MyFolder"
    assert "VERY-SECRET" not in str(metadata)
    assert "client_secret" not in metadata


@pytest.mark.asyncio
async def test_finalize_session_calls_audit_log_completed() -> None:
    """finalize_session ok → audit_log_insert avec oauth_completed."""
    fake_audit = AsyncMock()
    fake_flow = MagicMock()
    fake_flow.credentials = MagicMock(refresh_token="rt-NEVER-LEAK")
    pending = {
        "state": "S",
        "payload": {
            "client_id": "c",
            "client_secret": "SECRET-NO-LEAK",
            "redirect_uri": "u",
            "folder_name": "F",
            "name": "N",
        },
    }
    fake_conn = MagicMock()
    with (
        patch(
            "app.services.gdrive_oauth_session.repo.get_active_by_state",
            AsyncMock(return_value=pending),
        ),
        patch(
            "app.services.gdrive_oauth_session.gdrive_client.build_flow",
            return_value=fake_flow,
        ),
        patch(
            "app.services.gdrive_oauth_session.gdrive_client.fetch_user_email",
            return_value="ok@x.y",
        ),
        patch(
            "app.services.gdrive_oauth_session.repo.mark_authorized",
            AsyncMock(),
        ),
        patch(
            "app.services.gdrive_oauth_session.audit_log_insert",
            fake_audit,
        ),
    ):
        from app.services import gdrive_oauth_session as svc

        await svc.finalize_session(fake_conn, state="S", code="X")
    fake_audit.assert_called_once()
    raw = str(fake_audit.call_args)
    assert "remote_backup.gdrive.oauth_completed" in raw
    assert "rt-NEVER-LEAK" not in raw
    assert "SECRET-NO-LEAK" not in raw


@pytest.mark.asyncio
async def test_finalize_session_audit_metadata_has_user_email() -> None:
    """finalize_session → metadata contient user_email mais PAS de token."""
    fake_audit = AsyncMock()
    fake_flow = MagicMock()
    fake_flow.credentials = MagicMock(refresh_token="rt-xyz")
    pending = {
        "state": "S2",
        "payload": {
            "client_id": "c",
            "client_secret": "sec",
            "redirect_uri": "u",
            "folder_name": "F",
            "name": "N",
        },
    }
    fake_conn = MagicMock()
    with (
        patch(
            "app.services.gdrive_oauth_session.repo.get_active_by_state",
            AsyncMock(return_value=pending),
        ),
        patch(
            "app.services.gdrive_oauth_session.gdrive_client.build_flow",
            return_value=fake_flow,
        ),
        patch(
            "app.services.gdrive_oauth_session.gdrive_client.fetch_user_email",
            return_value="test@domain.com",
        ),
        patch("app.services.gdrive_oauth_session.repo.mark_authorized", AsyncMock()),
        patch("app.services.gdrive_oauth_session.audit_log_insert", fake_audit),
    ):
        from app.services import gdrive_oauth_session as svc

        await svc.finalize_session(fake_conn, state="S2", code="CODE")
    call_kwargs = fake_audit.call_args.kwargs
    metadata = call_kwargs.get("metadata", {})
    assert metadata.get("user_email") == "test@domain.com"
    assert "rt-xyz" not in str(metadata)
    assert "refresh_token" not in metadata


@pytest.mark.asyncio
async def test_mark_failed_calls_audit_log_failed() -> None:
    """mark_session_failed appelle audit_log_insert avec oauth_failed."""
    fake_audit = AsyncMock()
    fake_conn = MagicMock()
    with (
        patch(
            "app.services.gdrive_oauth_session.repo.mark_failed",
            AsyncMock(),
        ),
        patch(
            "app.services.gdrive_oauth_session.audit_log_insert",
            fake_audit,
        ),
    ):
        from app.services import gdrive_oauth_session as svc

        await svc.mark_session_failed(fake_conn, state="S", error="access_denied")
    fake_audit.assert_called_once()
    raw = str(fake_audit.call_args)
    assert "remote_backup.gdrive.oauth_failed" in raw
    assert "access_denied" in raw


@pytest.mark.asyncio
async def test_mark_failed_audit_success_false() -> None:
    """mark_session_failed → audit_log_insert est appelé avec success=False."""
    fake_audit = AsyncMock()
    fake_conn = MagicMock()
    with (
        patch("app.services.gdrive_oauth_session.repo.mark_failed", AsyncMock()),
        patch("app.services.gdrive_oauth_session.audit_log_insert", fake_audit),
    ):
        from app.services import gdrive_oauth_session as svc

        await svc.mark_session_failed(fake_conn, state="S3", error="some_error")
    call_kwargs = fake_audit.call_args.kwargs
    assert call_kwargs.get("success") is False
