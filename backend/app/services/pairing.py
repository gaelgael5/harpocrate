"""Service appairage entre 2 instances Harpocrate — partie master (LOT 2).

Ce module contiendra à terme :
- init_master (Task 2.2 — celui-ci)
- confirm_master, accept_standby (Task 2.3)
- advance_step, back_step (Task 3.2)
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from uuid import UUID

import asyncpg
import structlog

from app.db.repositories import pairing_sessions as repo
from app.services.audit import audit_log_insert

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class InitResult:
    """Résultat de init_master — code à transmettre à l'admin de B."""

    session_id: UUID
    code: str
    expires_in_seconds: int


def _generate_code() -> str:
    """Code 4 chiffres uniformes via `secrets`."""
    return f"{secrets.randbelow(10000):04d}"


async def _generate_unique_code(conn: asyncpg.Connection[asyncpg.Record]) -> str:
    """Tire un code 4 chiffres qui n'est pas déjà actif (pending/confirmed).

    Réessaie jusqu'à 20 fois avant d'abandonner. La probabilité de collision
    avec 10000 valeurs possibles et < 100 sessions actives est très faible.
    """
    for _ in range(20):
        candidate = _generate_code()
        existing = await repo.get_active_by_code(conn, candidate)
        if existing is None:
            return candidate
    raise RuntimeError("could_not_generate_unique_code")


async def init_master(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    partner_url: str,
    actor_user_id: UUID | None,
) -> InitResult:
    """A initie un appairage : génère un code unique, crée la session, audite.

    Le code retourné doit être communiqué hors-bande à l'admin du standby,
    qui s'en sert pour appeler /accept (Task 2.3).

    `actor_user_id=None` est accepté pour les tests d'unité, mais en
    production le caller doit toujours passer l'UUID de l'admin authentifié
    (issu du JWT). Un audit_log sans actor sur cette opération privilégiée
    serait suspect en review.
    """
    # Import tardif : évite l'instanciation de Settings à la collecte pytest.
    from app.core.config import settings

    code = await _generate_unique_code(conn)
    async with conn.transaction():
        sid = await repo.create(
            conn,
            role="master",
            code=code,
            partner_url=partner_url,
            ttl_seconds=settings.pairing_code_ttl_seconds,
            actor_user_id=actor_user_id,
        )
        await audit_log_insert(
            conn,
            "pairing.master_init",
            actor_user_id=actor_user_id,
            metadata={"partner_url": partner_url, "code_prefix": code[:2] + "**"},
        )
    return InitResult(
        session_id=sid,
        code=code,
        expires_in_seconds=settings.pairing_code_ttl_seconds,
    )
