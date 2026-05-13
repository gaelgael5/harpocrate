"""Service appairage v2 — échange d'URL signée (LOT 5).

Remplace le code 4 chiffres v1 par une URL unique à copier-coller :
- `init_master_v2` : master génère une session + URL d'appairage à transmettre.
- `confirm_master_v2` : master reçoit l'appel inter-instances avec session_id+token,
  crée le node standby + retourne le payload de réplication.
- `accept_standby_v2` : standby reçoit l'URL d'appairage collée par l'admin,
  parse + contacte le master, mémorise le payload local.

Réutilise les exceptions de `pairing` (v1) — même sémantique d'erreurs.
"""

from __future__ import annotations

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
from app.services.pairing import (
    InvalidCodeError,
    InvalidPairingPreconditionError,
    PairingAcceptError,
    TooManyAttemptsError,
)
from app.services.pairing_url_codec import (
    InvalidPairingUrlError,
    build_pairing_url,
    generate_token,
    parse_pairing_url,
)

logger = structlog.get_logger(__name__)


# ─── DTO interne ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class InitV2Result:
    """Résultat de init_master_v2 — URL d'appairage à transmettre au standby."""

    session_id: UUID
    pairing_url: str
    expires_in_seconds: int


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _host_from_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.hostname:
        raise PairingAcceptError(f"invalid_standby_url:{url!r}")
    return parsed.hostname


async def _generate_unique_token(conn: asyncpg.Connection[asyncpg.Record]) -> str:
    """Tire un token 128 bits non collisionné avec une session active.

    La probabilité de collision sur 128 bits est négligeable mais on garde
    une boucle de garde pour symétrie avec le générateur v1 et pour éviter
    un crash silencieux si jamais.
    """
    for _ in range(5):
        candidate = generate_token()
        existing = await repo.get_active_by_code(conn, candidate)
        if existing is None:
            return candidate
    raise RuntimeError("could_not_generate_unique_token")


# ─── init_master_v2 ──────────────────────────────────────────────────────────


async def init_master_v2(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    standby_url: str,
    actor_user_id: UUID | None,
) -> InitV2Result:
    """A crée une session d'appairage et retourne une URL signée.

    L'URL retournée contient `master_public_url + sid + token`. L'admin master
    la copie et la transmet via canal sûr au standby qui la collera dans son
    propre formulaire « Ajouter en tant que standby ».

    Aucun appel réseau ici : le master enregistre juste l'URL fournie et
    génère sa session. Le contact effectif a lieu plus tard côté standby via
    `accept_standby_v2`.
    """
    from app.core.config import settings

    if not standby_url.strip():
        raise PairingAcceptError("standby_url_empty")
    # Vérifie au moins que c'est une URL plausible — pas d'appel réseau.
    parsed = urlparse(standby_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise PairingAcceptError(f"invalid_standby_url:{standby_url!r}")

    token = await _generate_unique_token(conn)
    async with conn.transaction():
        sid = await repo.create(
            conn,
            role="master",
            code=token,
            partner_url=standby_url,
            ttl_seconds=settings.pairing_code_ttl_seconds,
            actor_user_id=actor_user_id,
        )
        await audit_log_insert(
            conn,
            "pairing.master_init_v2",
            actor_user_id=actor_user_id,
            metadata={"standby_url": standby_url, "session_id": str(sid)},
        )

    pairing_url = build_pairing_url(settings.public_url, sid, token)
    return InitV2Result(
        session_id=sid,
        pairing_url=pairing_url,
        expires_in_seconds=settings.pairing_code_ttl_seconds,
    )


# ─── confirm_master_v2 ───────────────────────────────────────────────────────


async def confirm_master_v2(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    session_id: UUID,
    token: str,
    standby_url: str,
    actor_user_id: UUID | None,
) -> dict[str, Any]:
    """A reçoit l'appel inter-instances du standby : (session_id, token).

    Vérifie que la session est active, que le token correspond, crée le node
    de réplication et stocke le payload pour répondre au standby.
    """
    from app.core.config import settings

    sess = await repo.get(conn, session_id)
    if sess is None:
        raise InvalidCodeError("session_not_found")

    # Incrément AVANT vérification du seuil — chaque tentative compte.
    new_attempts = await repo.increment_attempts(conn, session_id) or 0
    if new_attempts > settings.pairing_max_attempts:
        async with conn.transaction():
            await repo.set_status(conn, session_id, "failed")
            await audit_log_insert(
                conn,
                "pairing.failed",
                actor_user_id=actor_user_id,
                metadata={"role": "master", "reason": "too_many_attempts_v2"},
            )
        raise TooManyAttemptsError("too_many_attempts")

    if sess["status"] not in ("pending", "confirmed"):
        raise InvalidCodeError("session_not_active")
    if sess["code"] != token:
        raise InvalidCodeError("token_mismatch")

    strategy_row = await strat_repo.get_active_strategy(conn)
    if strategy_row is None:
        raise InvalidPairingPreconditionError("no_active_strategy")

    master_host = urlparse(settings.public_url).hostname
    if not master_host:
        raise InvalidPairingPreconditionError("public_url_missing_hostname")
    master_port = settings.replication_advertised_pg_port

    standby_host = _host_from_url(standby_url)

    _node_id, bundle = await streaming_svc.add_node(
        conn,
        strategy_id=strategy_row["id"],
        label=standby_url,
        host=standby_host,
        port=5432,
        role="standby_ro",
        notes=f"Créé par appairage v2 avec {standby_url}",
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
        await repo.set_payload(conn, session_id, payload)
        await repo.set_status(conn, session_id, "confirmed")

    return payload


# ─── accept_standby_v2 ───────────────────────────────────────────────────────


async def accept_standby_v2(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    pairing_url: str,
    self_url: str,
    actor_user_id: UUID | None,
) -> UUID:
    """B parse l'URL d'appairage collée → contacte A → stocke payload local.

    Le master_url est dérivé de l'URL d'appairage. La session locale role=standby
    est créée avec status=wizard et payload prêt à être consommé par
    PairingWizardPage.

    Raises InvalidPairingUrlError si l'URL n'a pas le bon format.
    Raises InvalidCodeError si A répond 401/403 (session inconnue/token KO).
    Raises TooManyAttemptsError si A répond 429.
    Raises PairingAcceptError en cas d'erreur réseau ou autre HTTP.
    """
    from app.core.config import settings

    parsed = parse_pairing_url(pairing_url)
    confirm_url = parsed.master_url + "/v1/admin/replication/pairing/confirm-v2"
    body = {
        "session_id": str(parsed.session_id),
        "token": parsed.token,
        "standby_url": self_url,
    }
    verify_tls = not settings.replication_insecure_skip_tls_verify
    if not verify_tls:
        # Mode dégradé : trace chaque appel pour qu'un audit puisse retrouver
        # les sessions d'appairage où la chaîne TLS n'a pas été vérifiée.
        logger.warning(
            "pairing_v2.tls_verification_disabled",
            master_url=parsed.master_url,
            session_id=str(parsed.session_id),
        )
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=verify_tls) as client:
            resp = await client.post(confirm_url, json=body)
    except httpx.HTTPError as e:
        # Le détail de l'exception httpx est précieux pour diagnostiquer (TLS
        # self-signed, DNS, connection refused, timeout). Sans ce log on ne
        # voit que le 502 final, ce qui est aveugle pour un admin.
        logger.error(
            "pairing_v2.confirm_call_failed",
            master_url=parsed.master_url,
            confirm_url=confirm_url,
            error_type=type(e).__name__,
            error=str(e),
            verify_tls=verify_tls,
        )
        raise PairingAcceptError(f"network_error:{type(e).__name__}:{e}") from e

    if resp.status_code in (401, 403):
        raise InvalidCodeError("invalid_or_expired_token")
    if resp.status_code == 429:
        raise TooManyAttemptsError("too_many_attempts")
    if resp.status_code != 200:
        raise PairingAcceptError(f"unexpected_status:{resp.status_code}")

    payload = resp.json()

    async with conn.transaction():
        sid = await repo.create(
            conn,
            role="standby",
            code=parsed.token,
            partner_url=parsed.master_url,
            ttl_seconds=settings.pairing_code_ttl_seconds,
            actor_user_id=actor_user_id,
        )
        await repo.set_payload(conn, sid, payload)
        await repo.set_status(conn, sid, "wizard")
        await audit_log_insert(
            conn,
            "pairing.standby_accepted_v2",
            actor_user_id=actor_user_id,
            metadata={"master_url": parsed.master_url, "session_id": str(sid)},
        )

    return sid


__all__ = [
    "InitV2Result",
    "InvalidPairingUrlError",
    "accept_standby_v2",
    "confirm_master_v2",
    "init_master_v2",
]
