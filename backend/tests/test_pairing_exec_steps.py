"""Tests de la déclaration des étapes du wizard."""

from __future__ import annotations

from app.services.pairing_exec.steps import (
    PairingPayload,
    StepDescriptor,
    list_steps,
)


def _payload() -> PairingPayload:
    return PairingPayload(
        master_host="a.example",
        master_port=5432,
        replication_user="repl_b_abc123",
        replication_password="sekret",
        application_name="b_example",
    )


def test_list_steps_returns_eight_entries() -> None:
    steps = list_steps(_payload())
    assert len(steps) == 8
    assert all(isinstance(s, StepDescriptor) for s in steps)


def test_list_steps_have_unique_indices_0_to_7() -> None:
    steps = list_steps(_payload())
    assert [s.idx for s in steps] == list(range(8))


def test_list_steps_first_is_verify_master_reachable() -> None:
    """L'étape 0 doit être non-destructive (pré-vérif du master)."""
    steps = list_steps(_payload())
    assert steps[0].kind == "verify_master_reachable"
    assert steps[0].idx == 0


def test_list_steps_titles_in_french() -> None:
    steps = list_steps(_payload())
    titles = [s.title for s in steps]
    assert "Arrêter le conteneur Postgres local" in titles
    assert any("pg_basebackup" in t.lower() for t in titles)
