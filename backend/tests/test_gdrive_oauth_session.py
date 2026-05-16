"""Tests du service gdrive_oauth_session (orchestrateur OAuth)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import asyncpg
import pytest

from app.services import gdrive_oauth_session as svc


@pytest.mark.asyncio
async def test_create_pending_session_returns_auth_url_and_state(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    fake_flow = MagicMock()
    fake_flow.authorization_url.return_value = (
        "https://accounts.google.com/o/oauth2/v2/auth?response_type=code&client_id=cid&state=STATE",
        "STATE",
    )
    with patch(
        "app.services.gdrive_oauth_session.gdrive_client.build_flow",
        return_value=fake_flow,
    ):
        async with real_db_pool.acquire() as conn:
            tr = conn.transaction()
            await tr.start()
            try:
                out = await svc.create_pending_session(
                    conn,
                    name="Backups",
                    client_id="cid",
                    client_secret="csec",
                    folder_name="Harpocrate Backups",
                    redirect_uri="https://harpo.example.com/.../callback",
                    target_connection_id=None,
                    created_by_user_id=None,
                )
                assert "auth_url" in out and "state" in out
                qs = parse_qs(urlparse(out["auth_url"]).query)
                assert qs["state"] == [out["state"]]
            finally:
                await tr.rollback()


@pytest.mark.asyncio
async def test_finalize_session_marks_authorized_with_user_email(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    fake_flow = MagicMock()
    fake_flow.authorization_url.return_value = ("https://accounts.google/...", "STATE-OK")
    fake_flow.credentials = MagicMock(refresh_token="rt-xyz")
    with (
        patch(
            "app.services.gdrive_oauth_session.gdrive_client.build_flow",
            return_value=fake_flow,
        ),
        patch(
            "app.services.gdrive_oauth_session.gdrive_client.fetch_user_email",
            return_value="admin@x.y",
        ),
    ):
        async with real_db_pool.acquire() as conn:
            tr = conn.transaction()
            await tr.start()
            try:
                created = await svc.create_pending_session(
                    conn,
                    name="N",
                    client_id="cid",
                    client_secret="csec",
                    folder_name="F",
                    redirect_uri="https://h/c",
                    target_connection_id=None,
                    created_by_user_id=None,
                )
                await svc.finalize_session(
                    conn,
                    state=created["state"],
                    code="AUTH_CODE",
                )
                from app.db.repositories import oauth_pending_session as repo

                row = await repo.get_by_state(conn, created["state"])
                assert row["status"] == "authorized"
                assert row["result"]["refresh_token"] == "rt-xyz"
                assert row["result"]["user_email"] == "admin@x.y"
            finally:
                await tr.rollback()


@pytest.mark.asyncio
async def test_finalize_session_invalid_state_raises(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        with pytest.raises(svc.OAuthSessionError, match="state_not_found"):
            await svc.finalize_session(conn, state="does-not-exist", code="x")


@pytest.mark.asyncio
async def test_mark_failed_records_error(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    fake_flow = MagicMock()
    fake_flow.authorization_url.return_value = ("https://x", "STATE")
    with patch(
        "app.services.gdrive_oauth_session.gdrive_client.build_flow",
        return_value=fake_flow,
    ):
        async with real_db_pool.acquire() as conn:
            tr = conn.transaction()
            await tr.start()
            try:
                created = await svc.create_pending_session(
                    conn,
                    name="N",
                    client_id="cid",
                    client_secret="csec",
                    folder_name="F",
                    redirect_uri="https://h/c",
                    target_connection_id=None,
                    created_by_user_id=None,
                )
                await svc.mark_session_failed(conn, state=created["state"], error="access_denied")
                from app.db.repositories import oauth_pending_session as repo

                row = await repo.get_by_state(conn, created["state"])
                assert row["status"] == "failed"
                assert row["result"]["error"] == "access_denied"
            finally:
                await tr.rollback()


def test_public_session_view_hides_secrets() -> None:
    """public_session_view ne doit JAMAIS exposer refresh_token / client_secret."""
    fake_row = {
        "status": "authorized",
        "result": {
            "user_email": "ok@x.y",
            "refresh_token": "VERY-SECRET",
            "token_uri": "https://oauth2.googleapis.com/token",
        },
    }
    view = svc.public_session_view(fake_row)
    assert view["status"] == "authorized"
    assert view["result"]["user_email"] == "ok@x.y"
    raw = str(view)
    assert "VERY-SECRET" not in raw
    assert "refresh_token" not in raw
    assert "token_uri" not in raw


def test_public_session_view_handles_none() -> None:
    view = svc.public_session_view(None)
    assert view == {"status": "unknown"}
