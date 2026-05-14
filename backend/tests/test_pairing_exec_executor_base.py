"""Tests de l'interface abstraite ExecutorBase."""

from __future__ import annotations

import pytest

from app.services.pairing_exec.executor_base import Executor, StepResult


def test_executor_is_abstract() -> None:
    with pytest.raises(TypeError):
        Executor()


def test_step_result_carries_exit_code_stdout_stderr() -> None:
    r = StepResult(exit_code=0, stdout="ok", stderr="")
    assert r.is_success is True

    err = StepResult(exit_code=2, stdout="", stderr="boom")
    assert err.is_success is False
