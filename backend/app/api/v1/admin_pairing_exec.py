"""WebSocket — exécution serveur du wizard pairing (LOT pairing-exec).

Auth identique à l'ancien ssh_terminal : token JWT en query string, vérifie
le rôle admin. Premier frame du client = `open_docker` ou `open_native` (avec
credentials SSH). L'orchestrator tourne et push les events dans le WS.

Re-tentative : le client peut envoyer `{type: "retry", from_step_idx: N}` dans
la trame d'ouverture (champ `from_step_idx`) pour relancer l'exécution depuis
l'étape N (idempotence côté executor).
"""

from __future__ import annotations

import json
from uuid import UUID

import structlog
from fastapi import APIRouter, Query, WebSocket, status

from app.core.config import settings
from app.core.security import _validate_jwt
from app.db.pool import get_pool
from app.db.repositories import pairing_sessions as pairing_repo
from app.services import admin_user_resolver
from app.services import install_mode as install_mode_svc
from app.services.audit import audit_log_insert
from app.services.pairing_exec.docker_executor import DockerExecutor
from app.services.pairing_exec.events import Event, serialize_event
from app.services.pairing_exec.executor_base import Executor
from app.services.pairing_exec.native_executor import NativeSshExecutor, SshCredentials
from app.services.pairing_exec.orchestrator import PairingExecOrchestrator
from app.services.pairing_exec.steps import PairingPayload

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/admin/replication/pairing", tags=["admin-pairing-exec"])


@router.websocket("/{session_id}/exec/ws")
async def pairing_exec_ws(ws: WebSocket, session_id: UUID, token: str = Query(...)) -> None:
    if token.startswith("hrpv_"):
        logger.warning(
            "ws_auth_rejected",
            reason="api_key_not_allowed",
            remote=ws.client.host if ws.client else None,
        )
        await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason="api_key_not_allowed")
        return
    try:
        payload_jwt = await _validate_jwt(token)
    except Exception:
        logger.warning(
            "ws_auth_rejected",
            reason="invalid_token",
            remote=ws.client.host if ws.client else None,
        )
        await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason="invalid_token")
        return

    roles = payload_jwt.get("realm_access", {}).get("roles", [])
    if settings.admin_role_name not in roles:
        logger.warning(
            "ws_auth_rejected",
            reason="not_admin",
            sub=payload_jwt.get("sub"),
            remote=ws.client.host if ws.client else None,
        )
        await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason="not_admin")
        return

    try:
        user_id = await admin_user_resolver.resolve_admin_user_id(
            keycloak_sub=payload_jwt["sub"],
            email=payload_jwt.get("email", ""),
            display_name=payload_jwt.get("name"),
        )
    except Exception:
        logger.exception("ws_auth_db_error")
        await ws.close(code=status.WS_1011_INTERNAL_ERROR, reason="internal_error")
        return

    await ws.accept()

    pool = await get_pool()
    async with pool.acquire() as conn:
        sess = await pairing_repo.get(conn, session_id)
        if sess is None or sess["role"] != "standby":
            await ws.send_json({"type": "error", "code": "session_not_found"})
            await ws.close()
            return
        p = sess["payload"]
        if not isinstance(p, dict) or "master_host" not in p:
            await ws.send_json({"type": "error", "code": "payload_incomplete"})
            await ws.close()
            return

        pairing_payload = PairingPayload(
            master_host=p["master_host"],
            master_port=int(p["master_port"]),
            replication_user=p["replication_user"],
            replication_password=p["replication_password"],
            application_name=p["application_name"],
        )

        try:
            first_raw = await ws.receive_text()
            first = json.loads(first_raw)
        except Exception:
            await ws.close()
            return

        mode_info = install_mode_svc.detect()
        executor: Executor
        if first.get("type") == "open_docker" and mode_info.mode == "docker_compose_auto":
            executor = DockerExecutor()
        elif first.get("type") == "open_native":
            if not settings.harpocrate_self_ssh_host:
                await ws.send_json({"type": "error", "code": "self_ssh_host_not_configured"})
                await ws.close()
                return
            creds = SshCredentials(
                host=settings.harpocrate_self_ssh_host,
                port=settings.harpocrate_self_ssh_port,
                username=str(first.get("username", "")),
                password=first.get("password") if first.get("auth_type") == "password" else None,
                private_key=(
                    first.get("private_key") if first.get("auth_type") == "privkey" else None
                ),
                passphrase=(
                    first.get("passphrase") if first.get("auth_type") == "privkey" else None
                ),
            )
            executor = NativeSshExecutor(creds)
        else:
            await ws.send_json({"type": "error", "code": "invalid_open_frame"})
            await ws.close()
            return

        start_from = int(first.get("from_step_idx", 0))

        async def on_event(ev: Event) -> None:
            await ws.send_json(serialize_event(ev))

        orch = PairingExecOrchestrator(
            executor=executor,
            payload=pairing_payload,
            on_event=on_event,
            conn=conn,
            session_id=session_id,
            actor_user_id=user_id,
            audit_writer=audit_log_insert,
        )
        try:
            await orch.run(start_from_step=start_from)
        finally:
            await ws.close()
