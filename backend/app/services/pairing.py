"""Service appairage entre 2 instances Harpocrate — partie master (LOT 2).

Ce module contiendra à terme :
- init_master (Task 2.2 — celui-ci)
- confirm_master, accept_standby (Task 2.3)
- advance_step, back_step (Task 3.2)
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import asyncpg
import httpx
import structlog

from app.db.repositories import pairing_sessions as repo
from app.db.repositories import replication_strategies as strat_repo
from app.services import streaming_replication as streaming_svc
from app.services.audit import audit_log_insert

logger = structlog.get_logger(__name__)


# ─── Exceptions spécifiques au pairing ───────────────────────────────────────


class InvalidCodeError(Exception):
    """Code 4 chiffres invalide ou expiré."""


class TooManyAttemptsError(Exception):
    """Trop d'essais sur le même code — la session est failed."""


class PairingAcceptError(Exception):
    """Erreur lors du contact HTTP entre B et A, ou configuration manquante côté A."""


class InvalidPairingPreconditionError(Exception):
    """Précondition non remplie côté master (ex: pas de stratégie active)."""


# ─── DTOs ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class InitResult:
    """Résultat de init_master — code à transmettre à l'admin de B."""

    session_id: UUID
    code: str
    expires_in_seconds: int


# ─── Helpers internes ────────────────────────────────────────────────────────


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


def _host_from_url(url: str) -> str:
    """Extrait le hostname d'une URL ; raise PairingAcceptError si malformé."""
    parsed = urlparse(url)
    if not parsed.hostname:
        raise PairingAcceptError(f"invalid_standby_url:{url!r}")
    return parsed.hostname


# ─── init_master ──────────────────────────────────────────────────────────────


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


# ─── confirm_master ───────────────────────────────────────────────────────────


async def confirm_master(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    code: str,
    standby_url: str,
    actor_user_id: UUID | None,
) -> dict[str, Any]:
    """A reçoit l'appel de B avec le code → crée le node standby + retourne payload.

    Étapes :
    1. Trouve la session active par code
    2. Incrémente le compteur d'essais AVANT de vérifier le seuil
    3. Bloque si le nouveau compteur dépasse pairing_max_attempts
    4. Récupère la stratégie active (nécessaire à add_node)
    5. Récupère l'IP + port master via `streaming_svc.get_postgres_info`
    6. Crée le replication node via `streaming_svc.add_node`
    7. Stocke le payload dans la session (statut=confirmed) et retourne au caller

    Raises InvalidCodeError si le code n'existe pas / a expiré.
    Raises TooManyAttemptsError si la session dépasse pairing_max_attempts tentatives.
    Raises InvalidPairingPreconditionError si aucune stratégie active n'est configurée.
    """
    # Import tardif : évite l'instanciation de Settings à la collecte pytest.
    from app.core.config import settings

    sess = await repo.get_active_by_code(conn, code)
    if sess is None:
        raise InvalidCodeError("invalid_or_expired_code")

    # Incrémenter AVANT de vérifier le seuil — chaque tentative compte.
    new_attempts = await repo.increment_attempts(conn, sess["id"]) or 0

    if new_attempts > settings.pairing_max_attempts:
        async with conn.transaction():
            await repo.set_status(conn, sess["id"], "failed")
            await audit_log_insert(
                conn,
                "pairing.failed",
                actor_user_id=actor_user_id,
                metadata={"role": "master", "reason": "too_many_attempts"},
            )
        raise TooManyAttemptsError("too_many_attempts")

    # Récupère la stratégie active — obligatoire pour add_node.
    strategy_row = await strat_repo.get_active_strategy(conn)
    if strategy_row is None:
        raise InvalidPairingPreconditionError("no_active_strategy")

    # Master host = hostname du public_url de cette instance (l'admin a la
    # responsabilité que ce host expose aussi Postgres sur le port annoncé).
    # Master port = setting dédié (défaut 5432).
    master_host = urlparse(settings.public_url).hostname
    if not master_host:
        raise InvalidPairingPreconditionError("public_url_missing_hostname")
    master_port = settings.replication_advertised_pg_port

    # Extrait le hostname du standby depuis son URL.
    standby_host = _host_from_url(standby_url)

    # add_node retourne tuple[UUID, NodeBundle].
    # NodeBundle.password contient le mot de passe de réplication (affiché 1x).
    _node_id, bundle = await streaming_svc.add_node(
        conn,
        strategy_id=strategy_row["id"],
        label=standby_url,
        host=standby_host,
        port=5432,  # Port Postgres standby inconnu — défaut, à ajuster dans le wizard Task 3.
        role="standby_ro",
        notes=f"Créé automatiquement lors de l'appairage avec {standby_url}",
        master_host=master_host,
        master_port=master_port,
        created_by_user_id=actor_user_id,
    )

    payload: dict[str, Any] = {
        "master_host": master_host,
        "master_port": master_port,
        "replication_user": bundle.replication_user,
        "replication_password": bundle.password,
        "application_name": bundle.application_name,
        "node_id": str(bundle.node_id),
    }

    async with conn.transaction():
        await repo.set_payload(conn, sess["id"], payload)
        await repo.set_status(conn, sess["id"], "confirmed")

    return payload


# ─── accept_standby ───────────────────────────────────────────────────────────


async def accept_standby(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    master_url: str,
    code: str,
    self_url: str,
    actor_user_id: UUID | None,
) -> UUID:
    """B reçoit le code + URL master → contacte A et stocke le payload localement.

    Le payload reçu (host master, replication user, password) est mémorisé dans
    une session role=standby status=wizard prête à être consommée par le wizard
    de Task 3.

    Raises InvalidCodeError si A répond 401/403.
    Raises TooManyAttemptsError si A répond 429.
    Raises PairingAcceptError en cas d'erreur réseau ou de status HTTP inattendu.
    """
    # Import tardif : évite l'instanciation de Settings à la collecte pytest.
    from app.core.config import settings

    url = master_url.rstrip("/") + "/v1/admin/replication/pairing/confirm"
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=True) as client:
            resp = await client.post(
                url,
                json={"code": code, "standby_url": self_url},
            )
    except httpx.HTTPError as e:
        raise PairingAcceptError(f"network_error:{e}") from e

    if resp.status_code in (401, 403):
        raise InvalidCodeError("invalid_or_expired_code")
    if resp.status_code == 429:
        raise TooManyAttemptsError("too_many_attempts")
    if resp.status_code != 200:
        raise PairingAcceptError(f"unexpected_status:{resp.status_code}")

    payload = resp.json()

    async with conn.transaction():
        sid = await repo.create(
            conn,
            role="standby",
            code=code,
            partner_url=master_url,
            ttl_seconds=settings.pairing_code_ttl_seconds,
            actor_user_id=actor_user_id,
        )
        await repo.set_payload(conn, sid, payload)
        await repo.set_status(conn, sid, "wizard")
        await audit_log_insert(
            conn,
            "pairing.standby_accepted",
            actor_user_id=actor_user_id,
            metadata={"master_url": master_url, "session_id": str(sid)},
        )

    return sid


# ─── advance_step / back_step ─────────────────────────────────────────────────


class StepCursorMismatchError(Exception):
    """Le curseur passé par le caller ne correspond pas à l'état serveur."""


async def advance_step(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    session_id: UUID,
    current_idx: int,
    total: int,
    actor_user_id: UUID | None,
) -> int:
    """Marque l'étape `current_idx` comme done et avance le curseur.

    Si le nouveau curseur atteint `total`, marque la session comme completed,
    audite, et déclenche le hook is_standby_of pour les sessions role=standby.

    Raises StepCursorMismatchError si current_idx != sess.current_step_idx.
    Raises InvalidCodeError si la session n'existe pas.
    """
    from app.services import streaming_replication as streaming_svc

    sess = await repo.get(conn, session_id)
    if sess is None:
        raise InvalidCodeError("session_not_found")
    if sess["current_step_idx"] != current_idx:
        raise StepCursorMismatchError(
            f"expected_step_idx={sess['current_step_idx']}_got={current_idx}",
        )
    new_idx = current_idx + 1
    async with conn.transaction():
        await repo.set_step_idx(conn, session_id, new_idx)
        if new_idx >= total:
            await repo.set_status(conn, session_id, "completed")
            await audit_log_insert(
                conn,
                "pairing.completed",
                actor_user_id=actor_user_id,
                metadata={
                    "role": sess["role"],
                    "partner_url": sess["partner_url"],
                },
            )
            if sess["role"] == "standby" and sess["partner_url"]:
                await streaming_svc.set_standby_of(
                    conn,
                    master_url=sess["partner_url"],
                )
    return new_idx


async def back_step(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    session_id: UUID,
    current_idx: int,
) -> int:
    """Recule d'une étape. Idempotent à 0 (renvoie 0).

    Raises StepCursorMismatchError si current_idx != sess.current_step_idx.
    Raises InvalidCodeError si la session n'existe pas.
    """
    sess = await repo.get(conn, session_id)
    if sess is None:
        raise InvalidCodeError("session_not_found")
    if current_idx <= 0:
        return 0
    if sess["current_step_idx"] != current_idx:
        raise StepCursorMismatchError(
            f"expected_step_idx={sess['current_step_idx']}_got={current_idx}",
        )
    new_idx = current_idx - 1
    async with conn.transaction():
        await repo.set_step_idx(conn, session_id, new_idx)
    return new_idx
