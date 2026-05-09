"""Repository — table recovery_sessions (LOT_57)."""
from __future__ import annotations

import datetime
from uuid import UUID

import asyncpg


async def insert(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    user_id: UUID | None,
    email: str,
    expires_at: datetime.datetime,
    ip_started: str | None,
) -> tuple[UUID, UUID]:
    """Crée une nouvelle session pending et retourne `(session_id, tracking_id)`.

    `user_id` peut être NULL si l'email ne correspond à aucun utilisateur en
    base (anti-énumération). `tracking_id` est généré par le DEFAULT DB et
    permet au client front de s'abonner à un futur WebSocket de suivi de
    livraison sans exposer `session_id` (qui reste secret, reçu par mail).
    """
    row = await conn.fetchrow(
        """
        INSERT INTO recovery_sessions (user_id, email, expires_at, ip_started)
        VALUES ($1, $2, $3, $4)
        RETURNING id, tracking_id
        """,
        user_id,
        email,
        expires_at,
        ip_started,
    )
    return row["id"], row["tracking_id"]


async def get_by_id(
    conn: asyncpg.Connection[asyncpg.Record],
    session_id: UUID,
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT id, user_id, email, created_at, expires_at,
               status, attempts, ip_started, ip_consumed, consumed_at
        FROM recovery_sessions
        WHERE id = $1
        """,
        session_id,
    )


async def increment_attempts(
    conn: asyncpg.Connection[asyncpg.Record],
    session_id: UUID,
    *,
    max_attempts: int,
) -> int | None:
    """Incrémente le compteur. Si on atteint `max_attempts`, on flippe
    automatiquement le status à 'failed' dans la même requête.

    Retourne le nombre d'attempts après incrément, ou None si la session
    n'était pas en status='pending' (déjà consommée/expired/failed).
    `max_attempts` est paramétrable (cf. `settings.recovery_max_attempts`)
    pour permettre les tests sans bloquer la session.
    """
    return await conn.fetchval(
        """
        UPDATE recovery_sessions
        SET attempts = attempts + 1,
            status = CASE
                WHEN attempts + 1 >= $2 THEN 'failed'
                ELSE status
            END
        WHERE id = $1 AND status = 'pending'
        RETURNING attempts
        """,
        session_id,
        max_attempts,
    )


async def set_novu_transaction_id(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    session_id: UUID,
    transaction_id: str,
) -> None:
    """Persiste le transactionId du provider mail retourné par le trigger
    pour traçabilité (corrélation logs côté provider / debug delivery)."""
    await conn.execute(
        "UPDATE recovery_sessions SET novu_transaction_id = $2 WHERE id = $1",
        session_id,
        transaction_id,
    )


async def set_sent_at(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    transaction_id: str,
    sent_at: datetime.datetime,
) -> int:
    """Marque la session comme effectivement envoyée par le provider.

    Retourne le nombre de rows affectées (0 si transaction_id inconnu —
    ce qui est tolérable, le webhook peut concerner un autre type d'event).
    """
    result = await conn.execute(
        """
        UPDATE recovery_sessions
        SET sent_at = $2
        WHERE novu_transaction_id = $1 AND sent_at IS NULL
        """,
        transaction_id,
        sent_at,
    )
    try:
        return int(result.split()[-1])
    except (ValueError, IndexError):
        return 0


async def set_delivery_status(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    transaction_id: str,
    status: str,
    status_at: datetime.datetime,
) -> int:
    """Met à jour le statut de livraison (`sent`/`delivered`/`failed`).

    Le CHECK SQL valide que la valeur est dans l'enum. Retourne le nombre
    de rows affectées (0 si transaction_id inconnu).
    """
    result = await conn.execute(
        """
        UPDATE recovery_sessions
        SET delivery_status = $2,
            delivery_status_at = $3
        WHERE novu_transaction_id = $1
        """,
        transaction_id,
        status,
        status_at,
    )
    try:
        return int(result.split()[-1])
    except (ValueError, IndexError):
        return 0


async def get_by_tracking_id(
    conn: asyncpg.Connection[asyncpg.Record],
    tracking_id: UUID,
) -> asyncpg.Record | None:
    """Lookup pour le futur endpoint WebSocket — récupère une session via
    son tracking_id public (séparé du session_id secret)."""
    return await conn.fetchrow(
        """
        SELECT id, tracking_id, status, sent_at, delivery_status, delivery_status_at
        FROM recovery_sessions
        WHERE tracking_id = $1
        """,
        tracking_id,
    )


async def mark_consumed(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    session_id: UUID,
    ip_consumed: str | None,
) -> None:
    await conn.execute(
        """
        UPDATE recovery_sessions
        SET status = 'consumed',
            consumed_at = NOW(),
            ip_consumed = $2
        WHERE id = $1
        """,
        session_id,
        ip_consumed,
    )


async def expire_pending(
    conn: asyncpg.Connection[asyncpg.Record],
) -> int:
    """Worker lifespan : passe les sessions pending dont expires_at est
    dépassé en status 'expired'. Retourne le nombre de rows affectées."""
    result = await conn.execute(
        """
        UPDATE recovery_sessions
        SET status = 'expired'
        WHERE status = 'pending' AND expires_at < NOW()
        """
    )
    try:
        return int(result.split()[-1])
    except (ValueError, IndexError):
        return 0


async def count_unsuccessful_for_email(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    email: str,
    since: datetime.datetime,
) -> int:
    """Count des sessions failed/expired pour cet email depuis `since`.
    Utilisé pour la détection d'anomalie (≥5/24h)."""
    return await conn.fetchval(
        """
        SELECT COUNT(*) FROM recovery_sessions
        WHERE email = $1 AND created_at >= $2
          AND status IN ('failed', 'expired')
        """,
        email,
        since,
    )
