"""Tests des events poussés par l'orchestrator pairing_exec."""

from __future__ import annotations

from app.services.pairing_exec.events import (
    ExecutionCompleteEvent,
    StepDoneEvent,
    StepErrorEvent,
    StepStartedEvent,
    serialize_event,
)


def test_step_started_serializes_to_json_dict() -> None:
    ev = StepStartedEvent(step_idx=2, title="pg_basebackup", command="docker run ...")
    payload = serialize_event(ev)
    assert payload["type"] == "step_started"
    assert payload["step_idx"] == 2
    assert payload["title"] == "pg_basebackup"
    assert payload["command"] == "docker run ..."


def test_step_done_carries_stdout_and_exit_code() -> None:
    ev = StepDoneEvent(step_idx=0, exit_code=0, stdout="ok\n", stderr="")
    payload = serialize_event(ev)
    assert payload["type"] == "step_done"
    assert payload["exit_code"] == 0
    assert payload["stdout"] == "ok\n"


def test_step_error_carries_error_type() -> None:
    ev = StepErrorEvent(step_idx=1, exit_code=2, stdout="", stderr="boom", error_type="NonZeroExit")
    payload = serialize_event(ev)
    assert payload["type"] == "step_error"
    assert payload["error_type"] == "NonZeroExit"


def test_execution_complete_no_payload() -> None:
    ev = ExecutionCompleteEvent()
    payload = serialize_event(ev)
    assert payload["type"] == "execution_complete"
