"""Service de mise à jour des statuts de livraison des notifications (LOT_57).

Architecture event-sourced agnostique du provider : chaque event reçu (par
webhook ou émis localement au moment du trigger) est INSERT dans la table
`notification_events`. La timeline complète d'un mail est reconstruite par
SELECT chronologique.

Mapping accepté pour `event_type` (sortie côté DB / enum CHECK) :

    sent      → le mail a été remis au provider (ex: listmonk a accepté)
    delivery  → le mail est arrivé chez le destinataire (delivery report SMTP)
    open      → le destinataire a ouvert le mail (pixel tracking)
    click     → le destinataire a cliqué sur un lien tracké
    failed    → échec définitif (bounce, rejet provider, etc.)

Le provider envoie ses propres noms d'events (ex: `email.delivery.sent`,
`message.delivered`, `delivered`, etc.). Le service les normalise via
`_PROVIDER_EVENT_TO_TYPE`. Les events inconnus sont ignorés silencieusement
(log + pas d'INSERT) pour éviter d'enregistrer du bruit.
"""
from __future__ import annotations

import datetime
from typing import Any

import asyncpg

from app.core.logging import logger
from app.db.repositories import notification_events as repo

# Mapping event provider (en minuscules) → event_type interne.
# Tolérant : on accepte les variantes vues entre providers (Novu / listmonk /
# Brevo / SendGrid). Le mapping peut être étendu sans migration.
_PROVIDER_EVENT_TO_TYPE: dict[str, str] = {
    # sent — le provider a accepté le mail
    "message.sent": "sent",
    "sent": "sent",
    "email.sent": "sent",
    # delivery — le destinataire l'a reçu
    "message.delivered": "delivery",
    "delivered": "delivery",
    "delivery": "delivery",
    "email.delivered": "delivery",
    "message.deliveredmail": "delivery",  # variante observée
    # open — pixel tracking déclenché
    "message.opened": "open",
    "opened": "open",
    "open": "open",
    "email.opened": "open",
    # click — un lien tracké a été cliqué
    "message.clicked": "click",
    "clicked": "click",
    "click": "click",
    "email.clicked": "click",
    "link.clicked": "click",
    # failed — échec définitif
    "message.failed": "failed",
    "failed": "failed",
    "bounce": "failed",
    "bounced": "failed",
    "email.bounced": "failed",
    "email.failed": "failed",
}


async def record_event(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    transaction_id: str,
    provider_event: str,
    occurred_at: datetime.datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Persiste un event de notification reçu d'un provider.

    Args:
        transaction_id: identifiant retourné par le provider au moment du
            trigger (jointure avec recovery_sessions.novu_transaction_id
            pour les mails de recovery).
        provider_event: nom de l'event tel qu'envoyé par le provider
            (ex: `message.sent`, `email.delivered`). Mapping vers l'enum
            interne fait ici (case-insensitive).
        occurred_at: timestamp fourni par le provider (peut différer du
            received_at qui est NOW() côté Harpocrate). Optionnel.
        metadata: payload brut du webhook, persisté en JSONB pour debug
            ultérieur (URL cliquée, IP destinataire, etc.).

    Returns:
        True si l'event a été persisté, False si :
          - transaction_id vide
          - provider_event inconnu (pas dans le mapping)
    """
    if not transaction_id:
        logger.warning(
            "notification_event_missing_transaction_id",
            provider_event=provider_event,
        )
        return False

    normalized = provider_event.lower().strip()
    event_type = _PROVIDER_EVENT_TO_TYPE.get(normalized)
    if event_type is None:
        logger.info(
            "notification_event_unknown_type",
            provider_event=provider_event,
            transaction_id=transaction_id,
        )
        return False

    event_id = await repo.insert_event(
        conn,
        transaction_id=transaction_id,
        event_type=event_type,
        occurred_at=occurred_at,
        metadata=metadata,
    )
    logger.info(
        "notification_event_recorded",
        event_id=event_id,
        transaction_id=transaction_id,
        provider_event=provider_event,
        event_type=event_type,
    )
    return True


async def record_local_sent(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    transaction_id: str,
    metadata: dict[str, Any] | None = None,
) -> int:
    """INSERT direct d'un event `sent` au moment où Harpocrate déclenche le
    trigger (et reçoit le transactionId du provider). Utile pour amorcer la
    timeline avant même le premier webhook — sinon on ne saurait pas qu'un
    mail a été envoyé tant que le webhook 'delivery' n'arrive pas.

    Retourne l'ID de l'event créé.
    """
    return await repo.insert_event(
        conn,
        transaction_id=transaction_id,
        event_type="sent",
        occurred_at=datetime.datetime.now(datetime.UTC),
        metadata=metadata,
    )
