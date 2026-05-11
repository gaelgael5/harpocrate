"""Tests du service ssh_terminal (LOT 1)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import ssh_terminal as svc


def test_parse_open_message_password() -> None:
    msg = {
        "type": "open",
        "host": "h",
        "port": 22,
        "username": "u",
        "auth_type": "password",
        "password": "p",
    }
    creds = svc._parse_open_message(msg)
    assert creds.host == "h"
    assert creds.password == "p"
    assert creds.private_key is None


def test_parse_open_message_privkey() -> None:
    msg = {
        "type": "open",
        "host": "h",
        "port": 22,
        "username": "u",
        "auth_type": "privkey",
        "private_key": (
            "-----BEGIN OPENSSH PRIVATE KEY-----\n...\n-----END OPENSSH PRIVATE KEY-----"
        ),
        "passphrase": "p",
    }
    creds = svc._parse_open_message(msg)
    assert creds.private_key is not None
    assert creds.passphrase == "p"
    assert creds.password is None


def test_parse_open_message_wrong_first_type_raises() -> None:
    with pytest.raises(svc.InvalidHandshakeError):
        svc._parse_open_message({"type": "data", "payload": "x"})


def test_parse_open_message_unsupported_auth_type_raises() -> None:
    with pytest.raises(svc.InvalidHandshakeError):
        svc._parse_open_message(
            {
                "type": "open",
                "host": "h",
                "port": 22,
                "username": "u",
                "auth_type": "agent",
            }
        )


def test_parse_open_message_missing_host_raises() -> None:
    with pytest.raises(svc.InvalidHandshakeError):
        svc._parse_open_message(
            {
                "type": "open",
                "port": 22,
                "username": "u",
                "auth_type": "password",
                "password": "p",
            }
        )


async def test_run_session_emits_open_and_close_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Vérifie que ssh_session.opened/closed sont émis pour une session normale."""
    audit_calls: list[tuple[str, dict]] = []

    async def fake_audit(conn, event: str, **kwargs) -> None:
        audit_calls.append((event, kwargs))

    monkeypatch.setattr(svc, "_audit", fake_audit)

    fake_proc = MagicMock()
    fake_proc.stdout.read = AsyncMock(side_effect=[b"hello", b""])
    fake_proc.stdin.write = MagicMock()
    fake_proc.close = MagicMock()
    fake_conn = MagicMock()
    fake_conn.create_process = AsyncMock(return_value=fake_proc)
    fake_conn.close = MagicMock()

    fake_ws = MagicMock()
    fake_ws.client = MagicMock(host="127.0.0.1")
    # Premier appel : handshake open. Second appel (ws_to_ssh) : close propre.
    fake_ws.receive_text = AsyncMock(
        side_effect=[
            json.dumps(
                {
                    "type": "open",
                    "host": "h",
                    "port": 22,
                    "username": "u",
                    "auth_type": "password",
                    "password": "p",
                }
            ),
            json.dumps({"type": "close"}),
        ]
    )
    fake_ws.send_json = AsyncMock()
    fake_ws.close = AsyncMock()

    fake_db_conn = MagicMock()

    with patch("asyncssh.connect", AsyncMock(return_value=fake_conn)):
        await svc.run_session(
            fake_ws,
            fake_db_conn,
            actor_user_id=None,
            idle_timeout_seconds=30,
        )

    events = [e for e, _ in audit_calls]
    assert "ssh_session.opened" in events
    assert "ssh_session.closed" in events


async def test_run_session_invalid_handshake_emits_error_and_no_open_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si le premier message est invalide, on n'ouvre PAS la connexion SSH
    et on n'émet PAS d'audit ssh_session.opened (creds = None côté finally)."""
    audit_calls: list[tuple[str, dict]] = []

    async def fake_audit(conn, event: str, **kwargs) -> None:
        audit_calls.append((event, kwargs))

    monkeypatch.setattr(svc, "_audit", fake_audit)

    fake_ws = MagicMock()
    fake_ws.client = MagicMock(host="127.0.0.1")
    fake_ws.receive_text = AsyncMock(return_value=json.dumps({"type": "data", "payload": "x"}))
    fake_ws.send_json = AsyncMock()
    fake_ws.close = AsyncMock()

    fake_db_conn = MagicMock()

    await svc.run_session(
        fake_ws,
        fake_db_conn,
        actor_user_id=None,
        idle_timeout_seconds=2,
    )

    events = [e for e, _ in audit_calls]
    assert "ssh_session.opened" not in events
    assert "ssh_session.closed" not in events  # creds None → no close audit either
    fake_ws.send_json.assert_any_call(
        {
            "type": "error",
            "code": "first_message_must_be_open",
        }
    )


async def test_run_session_ssh_auth_failure_sends_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """asyncssh.PermissionDenied → WS reçoit {type:error, code:ssh_auth_failed}."""
    audit_calls: list[tuple[str, dict]] = []

    async def fake_audit(conn, event, **kwargs) -> None:
        audit_calls.append((event, kwargs))

    monkeypatch.setattr(svc, "_audit", fake_audit)

    fake_ws = MagicMock()
    fake_ws.client = MagicMock(host="127.0.0.1")
    fake_ws.receive_text = AsyncMock(
        return_value=json.dumps(
            {
                "type": "open",
                "host": "h",
                "port": 22,
                "username": "u",
                "auth_type": "password",
                "password": "bad",
            }
        )
    )
    fake_ws.send_json = AsyncMock()
    fake_ws.close = AsyncMock()

    import asyncssh

    fake_db_conn = MagicMock()
    with patch(
        "asyncssh.connect",
        AsyncMock(side_effect=asyncssh.PermissionDenied(reason="denied")),
    ):
        await svc.run_session(
            fake_ws,
            fake_db_conn,
            actor_user_id=None,
            idle_timeout_seconds=2,
        )

    fake_ws.send_json.assert_any_call(
        {
            "type": "error",
            "code": "ssh_auth_failed",
            "message": "denied",
        }
    )


async def test_run_session_idle_timeout_sets_close_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si aucun message ni byte SSH ne circule, le timeout déclenche close avec idle_timeout."""
    audit_calls: list[tuple[str, dict]] = []

    async def fake_audit(conn, event, **kwargs) -> None:
        audit_calls.append((event, kwargs))

    monkeypatch.setattr(svc, "_audit", fake_audit)

    # Setup : connect réussit, mais ni ws.receive_text ni proc.stdout.read ne reviennent.
    async def never_returns(*args, **kwargs):
        await asyncio.sleep(10)

    fake_proc = MagicMock()
    fake_proc.stdout.read = AsyncMock(side_effect=never_returns)
    fake_proc.stdin.write = MagicMock()
    fake_proc.close = MagicMock()

    fake_conn = MagicMock()
    fake_conn.create_process = AsyncMock(return_value=fake_proc)
    fake_conn.close = MagicMock()

    fake_ws = MagicMock()
    fake_ws.client = MagicMock(host="127.0.0.1")
    open_msg = json.dumps(
        {
            "type": "open",
            "host": "h",
            "port": 22,
            "username": "u",
            "auth_type": "password",
            "password": "p",
        }
    )
    receive_calls = 0

    async def receive_text_side_effect():
        nonlocal receive_calls
        receive_calls += 1
        if receive_calls == 1:
            return open_msg
        await asyncio.sleep(10)

    fake_ws.receive_text = receive_text_side_effect
    fake_ws.send_json = AsyncMock()
    fake_ws.close = AsyncMock()

    fake_db_conn = MagicMock()
    with patch("asyncssh.connect", AsyncMock(return_value=fake_conn)):
        # idle_timeout très court pour ne pas bloquer le test
        await svc.run_session(
            fake_ws,
            fake_db_conn,
            actor_user_id=None,
            idle_timeout_seconds=0.2,
        )

    # close audit doit indiquer idle_timeout dans reason
    close_kwargs = [kw for ev, kw in audit_calls if ev == "ssh_session.closed"]
    assert close_kwargs
    assert close_kwargs[0].get("reason") == "idle_timeout"
