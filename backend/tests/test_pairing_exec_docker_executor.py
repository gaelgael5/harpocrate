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
