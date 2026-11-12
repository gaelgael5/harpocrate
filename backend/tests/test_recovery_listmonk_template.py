"""Choix du template Listmonk à l'envoi du mail de récupération (épic « Cultures et
templates Listmonk paramétrés en base », feature 2).

Le template est résolu en base selon la culture du user ; sans template, aucun mail ne
part et le tx_id n'est pas persisté.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.models.db.listmonk_template import ResolvedTemplate


def _pool() -> MagicMock:
    class _Acq:
        async def __aenter__(self) -> MagicMock:
            return MagicMock()

        async def __aexit__(self, *a: Any) -> None:
            return None

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_Acq())
    return pool


async def _start_session_for_user(resolved: ResolvedTemplate | None) -> tuple[AsyncMock, AsyncMock]:
    """Démarre une session pour un vrai user et attend la tâche d'envoi en arrière-plan.
    Retourne (trigger_recovery, set_novu_transaction_id)."""
    from app.db.repositories import recovery_sessions as repo
    from app.services import listmonk_templates as tpl_svc
    from app.services import notify_listmonk
    from app.services import recovery as svc

    user_id = uuid4()
    trigger = AsyncMock(return_value=False)
    persist_tx = AsyncMock()
    with (
        patch.object(repo, "insert", AsyncMock(return_value=(uuid4(), uuid4()))),
        patch.object(repo, "set_novu_transaction_id", persist_tx),
        patch(
            "app.services.recovery.users_repo.get_id_and_is_system_by_email",
            AsyncMock(return_value=(user_id, False)),
        ),
        patch.object(svc, "_maybe_record_anomaly", AsyncMock()),
        patch.object(svc, "audit_log_insert", AsyncMock()),
        patch.object(
            tpl_svc, "resolve_template_for_user", AsyncMock(return_value=resolved)
        ) as resolve,
        patch.object(notify_listmonk, "trigger_recovery", trigger),
        patch("app.db.pool.get_pool", AsyncMock(return_value=_pool())),
    ):
        await svc.start_session(MagicMock(), email="g@example.com", ip="1.2.3.4")
        await asyncio.gather(*list(svc._BACKGROUND_TASKS))
    assert resolve.await_args.args[1:] == ("recovery", user_id)
    return trigger, persist_tx


@pytest.mark.asyncio
async def test_recovery_mail_uses_resolved_template_id() -> None:
    trigger, persist_tx = await _start_session_for_user(
        ResolvedTemplate(template_id=42, culture_code="fr")
    )
    trigger.assert_awaited_once()
    assert trigger.await_args.kwargs["template_id"] == 42
    persist_tx.assert_awaited_once()


@pytest.mark.asyncio
async def test_recovery_mail_without_template_sends_nothing() -> None:
    trigger, persist_tx = await _start_session_for_user(None)
    trigger.assert_not_called()
    # Pas de trace d'envoi pour un mail qui n'est pas parti.
    persist_tx.assert_not_called()
