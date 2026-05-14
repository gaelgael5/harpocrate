"""Events émis par l'orchestrator pairing_exec, sérialisés sur le WebSocket.

Types JSON :
- step_started   : { step_idx, title, command }
- step_done      : { step_idx, exit_code, stdout, stderr }
- step_error     : { step_idx, exit_code, stdout, stderr, error_type }
- execution_complete : {}
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StepStartedEvent:
    step_idx: int
    title: str
    command: str


@dataclass(frozen=True)
class StepDoneEvent:
    step_idx: int
    exit_code: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class StepErrorEvent:
    step_idx: int
    exit_code: int
    stdout: str
    stderr: str
    error_type: str


@dataclass(frozen=True)
class ExecutionCompleteEvent:
    pass


Event = StepStartedEvent | StepDoneEvent | StepErrorEvent | ExecutionCompleteEvent


def serialize_event(ev: Event) -> dict[str, Any]:
    if isinstance(ev, StepStartedEvent):
        return {
            "type": "step_started",
            "step_idx": ev.step_idx,
            "title": ev.title,
            "command": ev.command,
        }
    if isinstance(ev, StepDoneEvent):
        return {
            "type": "step_done",
            "step_idx": ev.step_idx,
            "exit_code": ev.exit_code,
            "stdout": ev.stdout,
            "stderr": ev.stderr,
        }
    if isinstance(ev, StepErrorEvent):
        return {
            "type": "step_error",
            "step_idx": ev.step_idx,
            "exit_code": ev.exit_code,
            "stdout": ev.stdout,
            "stderr": ev.stderr,
            "error_type": ev.error_type,
        }
    if isinstance(ev, ExecutionCompleteEvent):
        return {"type": "execution_complete"}
    raise TypeError(f"unknown_event:{type(ev).__name__}")
