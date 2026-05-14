"""Orchestrateur exécution wizard pairing.

Itère sur les étapes, demande à l'executor d'exécuter chaque kind, émet les
events sur le callback `on_event`. Arrêt net sur erreur. Reprise possible
depuis n'importe quelle étape via `start_from_step`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import structlog

from app.services.pairing_exec.events import (
    Event,
    ExecutionCompleteEvent,
    StepDoneEvent,
    StepErrorEvent,
    StepStartedEvent,
)
from app.services.pairing_exec.executor_base import Executor
from app.services.pairing_exec.steps import PairingPayload, list_steps

logger = structlog.get_logger(__name__)

EventCallback = Callable[[Event], Awaitable[None]]
AuditWriter = Callable[..., Awaitable[None]]


class PairingExecOrchestrator:
    def __init__(
        self,
        *,
        executor: Executor,
        payload: PairingPayload,
        on_event: EventCallback,
        conn: Any | None = None,
        session_id: UUID | None = None,
        actor_user_id: UUID | None = None,
        audit_writer: AuditWriter | None = None,
    ) -> None:
        self._executor = executor
        self._payload = payload
        self._on_event = on_event
        self._conn = conn
        self._session_id = session_id
        self._actor_user_id = actor_user_id
        self._audit_writer = audit_writer

    async def _audit(self, action: str, metadata: dict[str, Any]) -> None:
        if self._audit_writer is None or self._conn is None:
            return
        await self._audit_writer(
            self._conn,
            action,
            actor_user_id=self._actor_user_id,
            metadata={
                "session_id": str(self._session_id) if self._session_id else None,
                **metadata,
            },
        )

    async def run(self, *, start_from_step: int = 0) -> None:
        await self._executor.open()
        try:
            steps = list_steps(self._payload)
            for step in steps:
                if step.idx < start_from_step:
                    continue
                await self._on_event(
                    StepStartedEvent(
                        step_idx=step.idx,
                        title=step.title,
                        command=step.kind,
                    )
                )
                await self._audit(
                    "pairing.exec_step_started",
                    {
                        "step_idx": step.idx,
                        "kind": step.kind,
                        "title": step.title,
                    },
                )
                try:
                    result = await self._executor.exec_step(step, self._payload)
                except Exception as e:
                    await self._on_event(
                        StepErrorEvent(
                            step_idx=step.idx,
                            exit_code=-1,
                            stdout="",
                            stderr=str(e),
                            error_type=type(e).__name__,
                        )
                    )
                    await self._audit(
                        "pairing.exec_step_error",
                        {
                            "step_idx": step.idx,
                            "exit_code": -1,
                            "stderr_excerpt": str(e)[:2000],
                            "error_type": type(e).__name__,
                        },
                    )
                    return
                if result.is_success:
                    await self._on_event(
                        StepDoneEvent(
                            step_idx=step.idx,
                            exit_code=result.exit_code,
                            stdout=result.stdout,
                            stderr=result.stderr,
                        )
                    )
                    await self._audit(
                        "pairing.exec_step_done",
                        {
                            "step_idx": step.idx,
                            "exit_code": result.exit_code,
                            "stdout_excerpt": result.stdout[:2000],
                        },
                    )
                else:
                    await self._on_event(
                        StepErrorEvent(
                            step_idx=step.idx,
                            exit_code=result.exit_code,
                            stdout=result.stdout,
                            stderr=result.stderr,
                            error_type="NonZeroExit",
                        )
                    )
                    await self._audit(
                        "pairing.exec_step_error",
                        {
                            "step_idx": step.idx,
                            "exit_code": result.exit_code,
                            "stderr_excerpt": result.stderr[:2000],
                            "error_type": "NonZeroExit",
                        },
                    )
                    return
            await self._on_event(ExecutionCompleteEvent())
        finally:
            await self._executor.close()
