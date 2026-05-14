"""Orchestrateur exécution wizard pairing.

Itère sur les étapes, demande à l'executor d'exécuter chaque kind, émet les
events sur le callback `on_event`. Arrêt net sur erreur. Reprise possible
depuis n'importe quelle étape via `start_from_step`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

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


class PairingExecOrchestrator:
    def __init__(
        self,
        *,
        executor: Executor,
        payload: PairingPayload,
        on_event: EventCallback,
    ) -> None:
        self._executor = executor
        self._payload = payload
        self._on_event = on_event

    async def run(self, *, start_from_step: int = 0) -> None:
        await self._executor.open()
        try:
            steps = list_steps(self._payload)
            for step in steps:
                if step.idx < start_from_step:
                    continue
                await self._on_event(StepStartedEvent(
                    step_idx=step.idx, title=step.title, command=step.kind,
                ))
                try:
                    result = await self._executor.exec_step(step, self._payload)
                except Exception as e:
                    await self._on_event(StepErrorEvent(
                        step_idx=step.idx, exit_code=-1, stdout="", stderr=str(e),
                        error_type=type(e).__name__,
                    ))
                    return
                if result.is_success:
                    await self._on_event(StepDoneEvent(
                        step_idx=step.idx, exit_code=result.exit_code,
                        stdout=result.stdout, stderr=result.stderr,
                    ))
                else:
                    await self._on_event(StepErrorEvent(
                        step_idx=step.idx, exit_code=result.exit_code,
                        stdout=result.stdout, stderr=result.stderr,
                        error_type="NonZeroExit",
                    ))
                    return
            await self._on_event(ExecutionCompleteEvent())
        finally:
            await self._executor.close()
