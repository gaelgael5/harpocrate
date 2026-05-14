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

    # 9 steps x (started + done) + 1 complete = 19 events
    assert len(events) == 19
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

    assert executor.exec_step.call_count == 5  # steps 4, 5, 6, 7, 8
    first_started_idx = next(e.step_idx for e in events if isinstance(e, StepStartedEvent))
    assert first_started_idx == 4


@pytest.mark.asyncio
async def test_run_invokes_on_pg_started_after_start_pg_container_success() -> None:
    """Après step_done(start_pg_container), l'orchestrator appelle on_pg_started.

    Sert au refresh du pool asyncpg côté backend : le step 6 vient d'écrire
    le password override, le step 7 vient de redémarrer Postgres avec ce
    password — il faut refresh le pool sinon le backend reste en 503.
    """
    executor = AsyncMock()
    executor.open = AsyncMock()
    executor.close = AsyncMock()
    executor.exec_step = AsyncMock(return_value=StepResult(exit_code=0, stdout="", stderr=""))

    pg_started_calls = {"n": 0}

    async def on_pg_started() -> None:
        pg_started_calls["n"] += 1

    orch = PairingExecOrchestrator(
        executor=executor, payload=_payload(), on_event=AsyncMock(),
        on_pg_started=on_pg_started,
    )
    await orch.run()
    # Une seule fois — pas par step, juste au step_done de start_pg_container
    assert pg_started_calls["n"] == 1


@pytest.mark.asyncio
async def test_run_does_not_invoke_on_pg_started_if_start_pg_container_fails() -> None:
    """on_pg_started ne doit PAS être appelé si start_pg_container échoue."""
    executor = AsyncMock()
    executor.open = AsyncMock()
    executor.close = AsyncMock()

    from app.services.pairing_exec.steps import list_steps

    payload = _payload()
    steps = list_steps(payload)
    fail_idx = next(s.idx for s in steps if s.kind == "start_pg_container")

    async def fake_exec(step, _payload):
        if step.idx == fail_idx:
            return StepResult(exit_code=1, stdout="", stderr="boom")
        return StepResult(exit_code=0, stdout="", stderr="")

    executor.exec_step.side_effect = fake_exec

    pg_started_calls = {"n": 0}

    async def on_pg_started() -> None:
        pg_started_calls["n"] += 1

    orch = PairingExecOrchestrator(
        executor=executor, payload=payload, on_event=AsyncMock(),
        on_pg_started=on_pg_started,
    )
    await orch.run()
    assert pg_started_calls["n"] == 0


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
    assert action_names.count("pairing.exec_step_started") == 9
    assert action_names.count("pairing.exec_step_done") == 9
