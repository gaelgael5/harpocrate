"""Bridge WebSocket ↔ asyncssh (PTY interactive).

Sécurité : creds en RAM uniquement (jamais persistés). Audit log open/close,
sans contenu de session. Idle timeout configurable.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import asyncpg
import asyncssh
import structlog
from fastapi import WebSocket, WebSocketDisconnect

from app.services.audit import audit_log_insert

logger = structlog.get_logger(__name__)

# Idle timeout default — overridable via settings in Task 1.4.
DEFAULT_IDLE_TIMEOUT_SECONDS = 1800


class InvalidHandshakeError(ValueError):
    """Premier message WS mal formé ou auth_type non supporté."""


@dataclass(frozen=True)
class SshCredentials:
    host: str
    port: int
    username: str
    password: str | None
    private_key: str | None
    passphrase: str | None


def _parse_open_message(msg: dict[str, Any]) -> SshCredentials:
    if not isinstance(msg, dict) or msg.get("type") != "open":
        raise InvalidHandshakeError("first_message_must_be_open")
    auth_type = msg.get("auth_type")
    if auth_type not in ("password", "privkey"):
        raise InvalidHandshakeError(f"unsupported_auth_type:{auth_type}")
    host = msg.get("host")
    username = msg.get("username")
    port = int(msg.get("port", 22))
    if not host or not username:
        raise InvalidHandshakeError("missing_host_or_username")
    return SshCredentials(
        host=str(host),
        port=port,
        username=str(username),
        password=msg.get("password") if auth_type == "password" else None,
        private_key=msg.get("private_key") if auth_type == "privkey" else None,
        passphrase=msg.get("passphrase") if auth_type == "privkey" else None,
    )


async def _audit(
    conn: asyncpg.Connection[asyncpg.Record],
    event: str,
    *,
    actor_user_id: UUID | None,
    source_ip: str | None = None,
    **metadata: Any,
) -> None:
    """Wrapper léger sur audit_log — fonction monkeypatchable en test."""
    await audit_log_insert(
        conn,
        event,
        actor_user_id=actor_user_id,
        actor_ip=source_ip,
        metadata=metadata,
    )


async def _connect_asyncssh(creds: SshCredentials) -> asyncssh.SSHClientConnection:
    logger.warning(
        "ssh_connect_known_hosts_disabled",
        host=creds.host,
        port=creds.port,
        note="TOFU mode MVP — add host verification before production",
    )
    if creds.private_key:
        client_keys = [
            asyncssh.import_private_key(
                creds.private_key,
                passphrase=creds.passphrase or None,
            )
        ]
        return await asyncssh.connect(
            host=creds.host,
            port=creds.port,
            username=creds.username,
            client_keys=client_keys,
            known_hosts=None,
        )
    return await asyncssh.connect(
        host=creds.host,
        port=creds.port,
        username=creds.username,
        password=creds.password,
        known_hosts=None,
    )


async def run_session(
    ws: WebSocket,
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    actor_user_id: UUID | None,
    idle_timeout_seconds: int = DEFAULT_IDLE_TIMEOUT_SECONDS,
) -> None:
    """Boucle principale : handshake → connexion SSH → bridge bidirectionnel."""
    started_at = time.monotonic()
    creds: SshCredentials | None = None
    ssh_conn: asyncssh.SSHClientConnection | None = None
    proc: Any = None
    close_reason = "normal"
    source_ip = ws.client.host if ws.client else "unknown"

    try:
        first = await asyncio.wait_for(ws.receive_text(), timeout=10.0)
        creds = _parse_open_message(json.loads(first))

        await _audit(
            conn,
            "ssh_session.opened",
            actor_user_id=actor_user_id,
            host=creds.host,
            port=creds.port,
            username=creds.username,
            source_ip=source_ip,
        )

        ssh_conn = await _connect_asyncssh(creds)
        proc = await ssh_conn.create_process(term_type="xterm-256color", encoding=None)

        await ws.send_json({"type": "ready"})

        async def ws_to_ssh() -> None:
            while True:
                raw = await ws.receive_text()
                msg = json.loads(raw)
                t = msg.get("type")
                if t == "data":
                    proc.stdin.write(base64.b64decode(msg["payload"]))
                elif t == "resize":
                    proc.change_terminal_size(int(msg["cols"]), int(msg["rows"]))
                elif t == "close":
                    return

        async def ssh_to_ws() -> None:
            while True:
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    return
                await ws.send_json(
                    {
                        "type": "data",
                        "payload": base64.b64encode(chunk).decode("ascii"),
                    }
                )

        ws_task = asyncio.create_task(ws_to_ssh())
        ssh_task = asyncio.create_task(ssh_to_ws())
        try:
            done, pending = await asyncio.wait(
                {ws_task, ssh_task},
                timeout=idle_timeout_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                close_reason = "idle_timeout"
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            # Surface unexpected errors from the completed task
            for task in done:
                exc = task.exception()
                if exc is not None and not isinstance(exc, asyncio.CancelledError):
                    raise exc
        finally:
            for task in (ws_task, ssh_task):
                if not task.done():
                    task.cancel()

    except WebSocketDisconnect:
        close_reason = "client_disconnect"
    except InvalidHandshakeError as e:
        close_reason = f"invalid_handshake:{e}"
        await ws.send_json({"type": "error", "code": str(e)})
    except (asyncssh.PermissionDenied, asyncssh.DisconnectError) as e:
        close_reason = f"ssh_auth:{type(e).__name__}"
        await ws.send_json(
            {"type": "error", "code": "ssh_auth_failed", "message": str(e)},
        )
    except Exception as e:
        logger.exception("ssh_terminal_unexpected", error=str(e))
        close_reason = f"unexpected:{type(e).__name__}"
    finally:
        if proc is not None:
            proc.close()
        if ssh_conn is not None:
            ssh_conn.close()
        if creds is not None:
            await _audit(
                conn,
                "ssh_session.closed",
                actor_user_id=actor_user_id,
                host=creds.host,
                port=creds.port,
                duration_seconds=int(time.monotonic() - started_at),
                reason=close_reason,
            )
        with contextlib.suppress(Exception):
            await ws.close()
