"""Tests PairingExecOrchestrator."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services.pairing_exec.events import (
    ExecutionCompleteEvent,
    StepDoneEvent,
    StepStartedEvent,
)
from app.services.pairing_exec.executor_base import StepResult
from app.services.pairing_exec.orchestrator import PairingExecOrchestrator
from app.services.pairing_exec.steps import PairingPayload


def _payload() -> PairingPayload:
    return PairingPayload(
        master_host="a", master_port=5432,
        replication_user="r", replication_password="p", application_name="b",
    )


@pytest.mark.asyncio
async def test_run_emits_started_done_for_each_step_then_complete() -> None:
    executor = AsyncMock()
    executor.open = AsyncMock()
    executor.close = AsyncMock()
    executor.exec_step = AsyncMock(return_value=StepResult(exit_code=0, stdout="ok", stderr=""))

    events: list = []

    async def on_event(ev) -> None:
        events.append(ev)

    orch = PairingExecOrchestrator(executor=executor, payload=_payload(), on_event=on_event)
    await orch.run()

    # 7 steps x (started + done) + 1 complete = 15 events
    assert len(events) == 15
    assert isinstance(events[0], StepStartedEvent)
    assert isinstance(events[1], StepDoneEvent)
    assert isinstance(events[-1], ExecutionCompleteEvent)


@pytest.mark.asyncio
async def test_run_stops_on_error_and_emits_step_error() -> None:
    executor = AsyncMock()
    executor.open = AsyncMock()
    executor.close = AsyncMock()

    async def fake_exec(step, payload):
        if step.idx == 2:
            return StepResult(exit_code=2, stdout="", stderr="boom")
        return StepResult(exit_code=0, stdout="", stderr="")

    executor.exec_step.side_effect = fake_exec

    events: list = []

    async def on_event(ev) -> None:
        events.append(ev)

    orch = PairingExecOrchestrator(executor=executor, payload=_payload(), on_event=on_event)
    await orch.run()

    types = [type(e).__name__ for e in events]
    assert "StepErrorEvent" in types
    assert "ExecutionCompleteEvent" not in types
    # exec_step appelé pour steps 0, 1, 2 — pas 3 et au-delà
    assert executor.exec_step.call_count == 3


@pytest.mark.asyncio
async def test_run_starts_from_step_idx_when_resume() -> None:
    executor = AsyncMock()
    executor.open = AsyncMock()
    executor.close = AsyncMock()
    executor.exec_step = AsyncMock(return_value=StepResult(exit_code=0, stdout="", stderr=""))
    events: list = []

    async def on_event(ev):
        events.append(ev)

    orch = PairingExecOrchestrator(executor=executor, payload=_payload(), on_event=on_event)
    await orch.run(start_from_step=4)

    assert executor.exec_step.call_count == 3  # steps 4, 5, 6
    first_started_idx = next(e.step_idx for e in events if isinstance(e, StepStartedEvent))
    assert first_started_idx == 4


@pytest.mark.asyncio
async def test_run_writes_audit_log_for_each_event() -> None:
    executor = AsyncMock()
    executor.open = AsyncMock()
    executor.close = AsyncMock()
    executor.exec_step = AsyncMock(return_value=StepResult(exit_code=0, stdout="", stderr=""))

    audit_calls: list[tuple[str, dict[str, Any]]] = []

    async def fake_audit(conn, event, *, actor_user_id, actor_ip=None, metadata) -> None:
        audit_calls.append((event, metadata))

    fake_conn = AsyncMock()
    session_id = uuid4()

    events: list = []

    async def on_event(ev):
        events.append(ev)

    orch = PairingExecOrchestrator(
        executor=executor, payload=_payload(), on_event=on_event,
        conn=fake_conn, session_id=session_id, actor_user_id=None, audit_writer=fake_audit,
    )
    await orch.run()

    action_names = [a[0] for a in audit_calls]
    assert action_names.count("pairing.exec_step_started") == 7
    assert action_names.count("pairing.exec_step_done") == 7
