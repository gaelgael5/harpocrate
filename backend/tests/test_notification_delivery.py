"""Tests du service notification_delivery (LOT_57 — refonte event-sourced)."""
from __future__ import annotations

import base64
import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "x")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://t")


# ─── record_event (depuis webhook) ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_event_inserts_with_correct_type() -> None:
    """Mapping `message.sent` → event_type='sent'."""
    from app.db.repositories import notification_events as repo
    from app.services import notification_delivery as svc

    conn = MagicMock()
    with patch.object(repo, "insert_event", AsyncMock(return_value=42)) as m:
        ok = await svc.record_event(
            conn,
            transaction_id="tx-1",
            provider_event="message.sent",
        )
    assert ok is True
    assert m.await_args.kwargs["event_type"] == "sent"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        ("message.sent", "sent"),
        ("sent", "sent"),
        ("email.sent", "sent"),
        ("message.delivered", "delivery"),
        ("delivered", "delivery"),
        ("message.deliveredmail", "delivery"),
        ("message.opened", "open"),
        ("opened", "open"),
        ("open", "open"),
        ("message.clicked", "click"),
        ("clicked", "click"),
        ("link.clicked", "click"),
        ("message.failed", "failed"),
        ("bounce", "failed"),
        ("bounced", "failed"),
    ],
)
async def test_record_event_provider_mapping(
    provider: str, expected: str
) -> None:
    from app.db.repositories import notification_events as repo
    from app.services import notification_delivery as svc

    conn = MagicMock()
    with patch.object(repo, "insert_event", AsyncMock(return_value=1)) as m:
        ok = await svc.record_event(
            conn, transaction_id="tx-1", provider_event=provider
        )
    assert ok is True
    assert m.await_args.kwargs["event_type"] == expected


@pytest.mark.asyncio
async def test_record_event_case_insensitive() -> None:
    from app.db.repositories import notification_events as repo
    from app.services import notification_delivery as svc

    conn = MagicMock()
    with patch.object(repo, "insert_event", AsyncMock(return_value=1)) as m:
        ok = await svc.record_event(
            conn, transaction_id="tx-1", provider_event="Message.SENT"
        )
    assert ok is True
    assert m.await_args.kwargs["event_type"] == "sent"


@pytest.mark.asyncio
async def test_record_event_unknown_provider_event_returns_false() -> None:
    from app.db.repositories import notification_events as repo
    from app.services import notification_delivery as svc

    conn = MagicMock()
    with patch.object(repo, "insert_event", AsyncMock()) as m:
        ok = await svc.record_event(
            conn, transaction_id="tx-1", provider_event="message.subscriber_added"
        )
    assert ok is False
    m.assert_not_called()


@pytest.mark.asyncio
async def test_record_event_empty_transaction_id_returns_false() -> None:
    from app.services import notification_delivery as svc

    conn = MagicMock()
    ok = await svc.record_event(
        conn, transaction_id="", provider_event="message.sent"
    )
    assert ok is False


@pytest.mark.asyncio
async def test_record_event_passes_occurred_at_and_metadata() -> None:
    from app.db.repositories import notification_events as repo
    from app.services import notification_delivery as svc

    conn = MagicMock()
    fixed_ts = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.UTC)
    meta = {"ip": "1.2.3.4", "url": "https://x"}
    with patch.object(repo, "insert_event", AsyncMock(return_value=1)) as m:
        await svc.record_event(
            conn,
            transaction_id="tx-1",
            provider_event="message.clicked",
            occurred_at=fixed_ts,
            metadata=meta,
        )
    assert m.await_args.kwargs["event_type"] == "click"
    assert m.await_args.kwargs["occurred_at"] == fixed_ts
    assert m.await_args.kwargs["metadata"] == meta


# ─── record_local_sent (au moment du trigger) ─────────────────────────────────


@pytest.mark.asyncio
async def test_record_local_sent_inserts_sent_event() -> None:
    from app.db.repositories import notification_events as repo
    from app.services import notification_delivery as svc

    conn = MagicMock()
    with patch.object(repo, "insert_event", AsyncMock(return_value=99)) as m:
        event_id = await svc.record_local_sent(
            conn,
            transaction_id="tx-1",
            metadata={"source": "trigger"},
        )
    assert event_id == 99
    assert m.await_args.kwargs["event_type"] == "sent"
    assert m.await_args.kwargs["metadata"] == {"source": "trigger"}
    # occurred_at doit être un datetime UTC
    assert isinstance(m.await_args.kwargs["occurred_at"], datetime.datetime)
