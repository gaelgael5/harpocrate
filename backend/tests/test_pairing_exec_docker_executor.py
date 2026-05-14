"""Tests DockerExecutor."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.services.pairing_exec.docker_executor import DockerExecutor


@pytest.mark.asyncio
async def test_open_extracts_pg_data_host_path_from_inspect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_inspect_result = {
        "Mounts": [
            {
                "Type": "bind",
                "Source": "/opt/harpocrate/data/postgres",
                "Destination": "/var/lib/postgresql/data",
            },
            {
                "Type": "bind",
                "Source": "/opt/harpocrate/db/init",
                "Destination": "/docker-entrypoint-initdb.d",
            },
        ]
    }
    fake_container = AsyncMock()
    fake_container.show = AsyncMock(return_value=fake_inspect_result)

    fake_docker = AsyncMock()
    fake_docker.containers.get = AsyncMock(return_value=fake_container)

    monkeypatch.setattr(
        "app.services.pairing_exec.docker_executor.aiodocker.Docker",
        lambda: fake_docker,
    )

    ex = DockerExecutor(pg_container_name="harpocrate-postgres")
    await ex.open()
    assert ex.pg_data_host_path == "/opt/harpocrate/data/postgres"
    await ex.close()


@pytest.mark.asyncio
async def test_open_raises_when_pg_data_mount_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_inspect_result = {"Mounts": []}
    fake_container = AsyncMock()
    fake_container.show = AsyncMock(return_value=fake_inspect_result)
    fake_docker = AsyncMock()
    fake_docker.containers.get = AsyncMock(return_value=fake_container)
    monkeypatch.setattr(
        "app.services.pairing_exec.docker_executor.aiodocker.Docker",
        lambda: fake_docker,
    )

    ex = DockerExecutor(pg_container_name="harpocrate-postgres")
    with pytest.raises(RuntimeError, match="pg_data_mount_not_found"):
        await ex.open()


@pytest.mark.asyncio
async def test_exec_step_stop_pg_container_calls_container_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.pairing_exec.steps import (
        PairingPayload,
        StepDescriptor,
    )

    fake_container = AsyncMock()
    fake_container.show = AsyncMock(
        return_value={
            "Mounts": [{"Destination": "/var/lib/postgresql/data", "Source": "/host/pg"}]
        }
    )
    fake_container.stop = AsyncMock(return_value=None)
    fake_docker = AsyncMock()
    fake_docker.containers.get = AsyncMock(return_value=fake_container)
    monkeypatch.setattr(
        "app.services.pairing_exec.docker_executor.aiodocker.Docker",
        lambda: fake_docker,
    )

    ex = DockerExecutor()
    await ex.open()
    step = StepDescriptor(idx=0, kind="stop_pg_container", title="x", description="")
    payload = PairingPayload(
        master_host="a",
        master_port=5432,
        replication_user="repl",
        replication_password="p",
        application_name="b",
    )
    res = await ex.exec_step(step, payload)
    assert res.is_success
    fake_container.stop.assert_called_once()
    await ex.close()


@pytest.mark.asyncio
async def test_start_pg_waits_pg_isready_before_returning_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """start_pg_container ne retourne step_done qu'après que pg_isready réussisse.

    Sans cette attente, le step suivant (verify_streaming) fait psql immédiatement
    et échoue avec 'socket No such file or directory' — Postgres prend quelques
    secondes pour créer son socket Unix après container.start().
    """
    from app.services.pairing_exec.steps import PairingPayload, StepDescriptor

    fake_pg = AsyncMock()
    fake_pg.show = AsyncMock(
        return_value={
            "Mounts": [{"Destination": "/var/lib/postgresql/data", "Source": "/host/pg"}]
        }
    )
    fake_pg.start = AsyncMock(return_value=None)

    fake_docker = AsyncMock()
    fake_docker.containers.get = AsyncMock(return_value=fake_pg)
    monkeypatch.setattr(
        "app.services.pairing_exec.docker_executor.aiodocker.Docker",
        lambda: fake_docker,
    )
    # Évite d'attendre vraiment 1s entre chaque essai
    monkeypatch.setattr("asyncio.sleep", AsyncMock(return_value=None))

    ex = DockerExecutor()
    await ex.open()
    # Simule pg_isready : pas prêt aux 2 premiers essais, prêt au 3e.
    ready_calls = [False, False, True]
    call_idx = {"i": 0}

    async def fake_isready(container: object) -> bool:
        i = call_idx["i"]
        call_idx["i"] = i + 1
        return ready_calls[i]

    monkeypatch.setattr(ex, "_exec_pg_isready", fake_isready)

    step = StepDescriptor(idx=7, kind="start_pg_container", title="x", description="")
    payload = PairingPayload(
        master_host="a",
        master_port=5432,
        replication_user="r",
        replication_password="p",
        application_name="b",
    )
    res = await ex.exec_step(step, payload)
    assert res.is_success
    fake_pg.start.assert_called_once()
    assert call_idx["i"] == 3  # a bien bouclé 3 fois
    await ex.close()


@pytest.mark.asyncio
async def test_start_pg_returns_error_when_pg_isready_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si pg_isready ne répond jamais OK, step_error explicite (pas un crash)."""
    from app.services.pairing_exec.steps import PairingPayload, StepDescriptor

    fake_pg = AsyncMock()
    fake_pg.show = AsyncMock(
        return_value={
            "Mounts": [{"Destination": "/var/lib/postgresql/data", "Source": "/host/pg"}]
        }
    )
    fake_pg.start = AsyncMock(return_value=None)
    fake_docker = AsyncMock()
    fake_docker.containers.get = AsyncMock(return_value=fake_pg)
    monkeypatch.setattr(
        "app.services.pairing_exec.docker_executor.aiodocker.Docker",
        lambda: fake_docker,
    )
    monkeypatch.setattr("asyncio.sleep", AsyncMock(return_value=None))

    # Timeout court (3 essais) pour ne pas attendre 30 essais.
    ex = DockerExecutor(pg_isready_timeout_seconds=3)
    await ex.open()
    monkeypatch.setattr(
        ex,
        "_exec_pg_isready",
        AsyncMock(return_value=False),
    )

    step = StepDescriptor(idx=7, kind="start_pg_container", title="x", description="")
    payload = PairingPayload(
        master_host="a",
        master_port=5432,
        replication_user="r",
        replication_password="p",
        application_name="b",
    )
    res = await ex.exec_step(step, payload)
    assert not res.is_success
    assert "timeout" in res.stderr.lower()
    await ex.close()


@pytest.mark.asyncio
async def test_exec_step_pg_basebackup_runs_postgres_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.pairing_exec.steps import (
        PairingPayload,
        StepDescriptor,
    )

    fake_pg = AsyncMock()
    fake_pg.show = AsyncMock(
        return_value={
            "Mounts": [{"Destination": "/var/lib/postgresql/data", "Source": "/host/pg"}]
        }
    )
    fake_run_container = AsyncMock()
    fake_run_container.wait = AsyncMock(return_value={"StatusCode": 0})
    fake_run_container.log = AsyncMock(return_value=["base backup done\n"])
    fake_run_container.delete = AsyncMock(return_value=None)

    fake_docker = AsyncMock()
    fake_docker.containers.get = AsyncMock(return_value=fake_pg)
    fake_docker.containers.run = AsyncMock(return_value=fake_run_container)
    monkeypatch.setattr(
        "app.services.pairing_exec.docker_executor.aiodocker.Docker",
        lambda: fake_docker,
    )

    ex = DockerExecutor()
    await ex.open()
    step = StepDescriptor(
        idx=2, kind="pg_basebackup_from_master", title="x", description=""
    )
    payload = PairingPayload(
        master_host="a.example",
        master_port=5432,
        replication_user="repl_x",
        replication_password="sekret",
        application_name="x",
    )
    res = await ex.exec_step(step, payload)
    assert res.is_success
    call_kwargs = fake_docker.containers.run.call_args.kwargs
    config = call_kwargs.get("config", {})
    assert config.get("Image") == "postgres:16-alpine"
    await ex.close()
