"""Tests Pydantic schemas appairage (LOT 2 + LOT 5)."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.models.api.pairing import (
    PairingAcceptRequest,
    PairingAcceptV2Request,
    PairingConfirmRequest,
    PairingConfirmResponse,
    PairingConfirmV2Request,
    PairingInitRequest,
    PairingInitResponse,
    PairingStatusResponse,
)


def test_init_request_validates_url() -> None:
    r = PairingInitRequest(partner_url="https://b.example/")
    assert r.partner_url == "https://b.example/"


def test_init_request_rejects_empty_url() -> None:
    with pytest.raises(ValueError):
        PairingInitRequest(partner_url="")


def test_init_response_serializes() -> None:
    r = PairingInitResponse(
        session_id=uuid4(),
        code="1234",
        expires_in_seconds=600,
    )
    assert r.code == "1234"


def test_accept_validates_code() -> None:
    with pytest.raises(ValueError):
        PairingAcceptRequest(master_url="https://a/", code="abc")
    with pytest.raises(ValueError):
        PairingAcceptRequest(master_url="https://a/", code="12345")
    PairingAcceptRequest(master_url="https://a/", code="1234")


def test_confirm_validates_code() -> None:
    with pytest.raises(ValueError):
        PairingConfirmRequest(code="ab", standby_url="https://b/")
    PairingConfirmRequest(code="0000", standby_url="https://b/")


def test_confirm_response_shape() -> None:
    PairingConfirmResponse(
        master_host="10.0.0.1",
        master_port=5432,
        replication_user="rep_x",
        replication_password="pwd",
        application_name="app_x",
        node_id=uuid4(),
        master_postgres_password="pg_pwd",
    )


def test_status_response_uses_literals() -> None:
    r = PairingStatusResponse(
        session_id=uuid4(),
        role="master",
        status="pending",
        partner_url=None,
        current_step_idx=0,
        expires_at="2026-05-11T12:00:00Z",
    )
    assert r.role == "master"
    assert r.status == "pending"
    # Literal types — invalid values should raise
    with pytest.raises(ValueError):
        PairingStatusResponse(
            session_id=uuid4(),
            role="invalid",  # type: ignore[arg-type]
            status="pending",
            partner_url=None,
            current_step_idx=0,
            expires_at="2026-05-11T12:00:00Z",
        )


def test_confirm_response_node_id_is_uuid() -> None:
    """node_id must be a valid UUID, not a free string."""
    PairingConfirmResponse(
        master_host="h",
        master_port=5432,
        replication_user="u",
        replication_password="p",
        application_name="a",
        node_id=uuid4(),
        master_postgres_password="x",
    )
    with pytest.raises(ValueError):
        PairingConfirmResponse(
            master_host="h",
            master_port=5432,
            replication_user="u",
            replication_password="p",
            application_name="a",
            node_id="not-a-uuid",  # type: ignore[arg-type]
            master_postgres_password="x",
        )


def test_confirm_response_propagates_master_postgres_password() -> None:
    """master_postgres_password DOIT être un champ déclaré du modèle.

    Si absent, FastAPI filtre silencieusement la clé via response_model lors de
    la sérialisation HTTP, et le step 6 du wizard standby
    (write_db_credentials_override) échoue avec
    'master_postgres_password absent du payload pairing'.
    """
    r = PairingConfirmResponse(
        master_host="h",
        master_port=5432,
        replication_user="u",
        replication_password="p",
        application_name="a",
        node_id=uuid4(),
        master_postgres_password="secret-master-pwd",
    )
    assert r.master_postgres_password == "secret-master-pwd"
    dumped = r.model_dump()
    assert "master_postgres_password" in dumped
    assert dumped["master_postgres_password"] == "secret-master-pwd"


# ─── V2 tests (LOT 5) ──────────────────────────────────────────────────────────


def test_pairing_confirm_v2_request_force_defaults_false() -> None:
    req = PairingConfirmV2Request(
        session_id=UUID("00000000-0000-0000-0000-000000000000"),
        token="a" * 32,
        standby_url="https://b/",
    )
    assert req.force is False


def test_pairing_confirm_v2_request_force_true_accepted() -> None:
    req = PairingConfirmV2Request(
        session_id=UUID("00000000-0000-0000-0000-000000000000"),
        token="a" * 32,
        standby_url="https://b/",
        force=True,
    )
    assert req.force is True


def test_pairing_accept_v2_request_force_defaults_false() -> None:
    req = PairingAcceptV2Request(pairing_url="https://a/pair?sid=x&t=y")
    assert req.force is False


def test_pairing_accept_v2_request_force_true_accepted() -> None:
    req = PairingAcceptV2Request(pairing_url="https://a/pair?sid=x&t=y", force=True)
    assert req.force is True
