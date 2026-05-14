"""Tests détection install_mode (LOT pairing-exec)."""

from __future__ import annotations

from pathlib import Path

from app.services import install_mode as svc


def test_detect_returns_native_when_no_dockerenv(tmp_path: Path) -> None:
    """Pas de /.dockerenv et pas de socket → mode native."""
    fake_root = tmp_path / "root"
    fake_root.mkdir()
    result = svc.detect(root_path=fake_root, docker_socket_path=fake_root / "no-socket")
    assert result.mode == "native"
    assert result.docker_socket_accessible is False
    assert result.pg_container_data_host_path is None


def test_detect_returns_docker_when_dockerenv_and_socket(tmp_path: Path) -> None:
    """/.dockerenv présent + socket existant → mode docker_compose_auto."""
    fake_root = tmp_path / "root"
    fake_root.mkdir()
    (fake_root / ".dockerenv").write_text("")
    socket = fake_root / "docker.sock"
    socket.write_text("")
    result = svc.detect(root_path=fake_root, docker_socket_path=socket)
    assert result.mode == "docker_compose_auto"
    assert result.docker_socket_accessible is True


def test_detect_native_when_dockerenv_but_no_socket(tmp_path: Path) -> None:
    """Conteneur sans socket monté → mode native (on ne peut pas piloter Docker)."""
    fake_root = tmp_path / "root"
    fake_root.mkdir()
    (fake_root / ".dockerenv").write_text("")
    result = svc.detect(root_path=fake_root, docker_socket_path=fake_root / "no-socket")
    assert result.mode == "native"
    assert result.docker_socket_accessible is False
