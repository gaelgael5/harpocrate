"""Tests génération des étapes wizard appairage (LOT 3)."""

from __future__ import annotations

from app.services.pairing_steps import WizardStep, build_standby_steps


def _sample_steps() -> list[WizardStep]:
    return build_standby_steps(
        master_host="1.2.3.4",
        master_port=5432,
        replication_user="rep_x",
        replication_password="pwd123",
        application_name="app_x",
    )


def test_build_standby_steps_returns_8_steps() -> None:
    steps = _sample_steps()
    assert len(steps) == 8


def test_build_standby_steps_have_sequential_indices() -> None:
    steps = _sample_steps()
    assert [s.idx for s in steps] == list(range(8))


def test_basebackup_command_contains_creds_and_target() -> None:
    steps = _sample_steps()
    bb = next(s for s in steps if "pg_basebackup" in s.command)
    assert "1.2.3.4" in bb.command
    assert "5432" in bb.command
    assert "rep_x" in bb.command
    assert "app_x" in bb.command
    # Password injected via PGPASSWORD prefix
    assert "pwd123" in bb.command


def test_basebackup_password_uses_pgpassword_env() -> None:
    """Le password doit être passé via PGPASSWORD=... pour ne pas apparaître
    dans la liste des processus (ps -ef)."""
    steps = _sample_steps()
    bb = next(s for s in steps if "pg_basebackup" in s.command)
    assert bb.command.startswith("PGPASSWORD='pwd123' ")


def test_steps_include_all_expected_phases() -> None:
    """Vérifie la présence des phases clés."""
    steps = _sample_steps()
    commands = [s.command for s in steps]
    assert any("docker stop" in c for c in commands)
    assert any("mv " in c and ".bak." in c for c in commands)
    assert any("pg_basebackup" in c for c in commands)
    assert any("standby.signal" in c for c in commands)
    assert any("postgresql.auto.conf" in c for c in commands)
    assert any("docker start" in c for c in commands)
    assert any("pg_is_in_recovery" in c for c in commands)
    assert any("pg_stat_wal_receiver" in c for c in commands)


def test_each_step_has_non_empty_title_and_command() -> None:
    steps = _sample_steps()
    for s in steps:
        assert s.title.strip() != ""
        assert s.command.strip() != ""


def test_custom_container_and_data_dir() -> None:
    steps = build_standby_steps(
        master_host="h",
        master_port=5432,
        replication_user="u",
        replication_password="p",
        application_name="a",
        container_name="custom-pg",
        pg_data_dir="/custom/data",
    )
    commands = " ".join(s.command for s in steps)
    assert "custom-pg" in commands
    assert "/custom/data" in commands
