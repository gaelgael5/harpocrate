"""Tests NativeSshExecutor."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.pairing_exec.native_executor import (
    NativeSshExecutor,
    SshCredentials,
)
from app.services.pairing_exec.steps import PairingPayload, StepDescriptor


@pytest.mark.asyncio
async def test_open_connects_with_password_and_close_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_conn = AsyncMock()
    fake_conn.close = MagicMock()

    async def fake_connect(**kwargs):
        return fake_conn

    monkeypatch.setattr(
        "app.services.pairing_exec.native_executor.asyncssh.connect",
        fake_connect,
    )

    creds = SshCredentials(
        host="b.example", port=22, username="admin", password="p", private_key=None, passphrase=None
    )
    ex = NativeSshExecutor(creds)
    await ex.open()
    await ex.close()
    fake_conn.close.assert_called_once()


@pytest.mark.asyncio
async def test_exec_step_stop_pg_runs_docker_stop_over_ssh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_result = MagicMock()
    fake_result.exit_status = 0
    fake_result.stdout = "stopped\n"
    fake_result.stderr = ""

    fake_conn = AsyncMock()
    fake_conn.run = AsyncMock(return_value=fake_result)
    fake_conn.close = MagicMock()

    async def fake_connect(**kwargs):
        return fake_conn

    monkeypatch.setattr(
        "app.services.pairing_exec.native_executor.asyncssh.connect",
        fake_connect,
    )

    creds = SshCredentials(
        host="b.example", port=22, username="admin", password="p", private_key=None, passphrase=None
    )
    ex = NativeSshExecutor(creds)
    await ex.open()
    step = StepDescriptor(idx=0, kind="stop_pg_container", title="x", description="")
    payload = PairingPayload(
        master_host="a", master_port=5432,
        replication_user="r", replication_password="p", application_name="b",
    )
    res = await ex.exec_step(step, payload)
    assert res.exit_code == 0
    assert "stopped" in res.stdout
    call_args = fake_conn.run.call_args
    cmd_str = call_args.args[0] if call_args.args else call_args.kwargs.get("command", "")
    assert "docker stop" in cmd_str
    await ex.close()
