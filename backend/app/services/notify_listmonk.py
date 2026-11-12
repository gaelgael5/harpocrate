"""Client listmonk — déclenche un template transactional (LOT_57).

Harpocrate appelle `POST {LISTMONK_URL}/api/tx` avec le `template_id`
paramétré en base par culture (écran « Paramétrage Listmonk »). Listmonk fait le
rendu (Sprig templates), ajoute son tracking et envoie via son provider SMTP.

Connexion (URL, utilisateur, token) paramétrée en base et résolue par l'appelant
(`listmonk_connection.resolve_connection`). Auth : header
`Authorization: token {api_user}:{token}`.

Le `tx_id` (UUID Harpocrate) est passé via le custom header
`X-Harpocrate-Tx-Id`. listmonk forward typiquement les headers custom dans
ses webhooks de delivery — c'est ce qui nous permettra de corréler les
events reçus en retour avec la `recovery_session` correspondante.

Comportement :
- Échec HTTP/réseau : log warning, retourne False — pas de re-raise.
- L'envoi est best-effort : la session de recovery existe en DB, le user
  peut retenter via `/start` si rien n'arrive.
"""
from __future__ import annotations

from typing import Any

import httpx

from app.core.logging import logger
from app.models.db.listmonk_connection import ListmonkConnection
from app.services.listmonk_connection import auth_header

_TIMEOUT_SECONDS = 5.0
_TX_ID_HEADER = "X-Harpocrate-Tx-Id"


async def _ensure_subscriber(
    client: httpx.AsyncClient, connection: ListmonkConnection, email: str
) -> bool:
    """Crée le subscriber côté listmonk si absent (upsert idempotent).

    Listmonk refuse `POST /api/tx` si le `subscriber_email` n'existe pas
    en base ("Subscriber not found"). Contrairement à Novu il n'auto-crée
    pas. On fait donc un POST `/api/subscribers` avant chaque envoi avec
    `preconfirm_subscriptions=true` (pas de double opt-in pour un mail
    transactional). 409 = déjà existe → traité comme succès.

    Retourne True si le subscriber est garanti exister à l'issue, False
    sinon (network/HTTP error → on remonte au caller).
    """
    url = f"{connection.url}/api/subscribers"
    body = {
        "email": email,
        "name": email,  # listmonk exige un name non-vide
        "status": "enabled",
        "preconfirm_subscriptions": True,
        "lists": [],
    }
    try:
        response = await client.post(
            url,
            json=body,
            headers={
                "Authorization": auth_header(connection),
                "Content-Type": "application/json",
            },
        )
    except httpx.HTTPError as exc:
        logger.warning("listmonk_subscriber_network_error", error=str(exc))
        return False

    if response.status_code in (200, 201):
        return True
    if response.status_code == 409:
        # Subscriber déjà existant → c'est ce qu'on veut.
        return True
    # 400 "email already exists" est une autre forme courante côté listmonk.
    if response.status_code == 400 and "already exists" in response.text.lower():
        return True
    logger.warning(
        "listmonk_subscriber_create_failed",
        status=response.status_code,
        body=response.text[:300],
    )
    return False


async def trigger_recovery(
    *,
    connection: ListmonkConnection,
    email: str,
    tx_id: str,
    payload: dict[str, Any],
    template_id: int,
) -> bool:
    """Déclenche le template transactional listmonk pour un mail de recovery.

    Args:
        connection: connexion Listmonk résolue en base par l'appelant.
        email: adresse du destinataire (`subscriber_email` côté listmonk).
        tx_id: identifiant Harpocrate (UUID) propagé via header custom
            `X-Harpocrate-Tx-Id`. Persisté en DB AVANT l'appel pour la
            corrélation avec les webhooks de delivery.
        payload: variables consommées par le template listmonk (sous la
            clé `data` du body). La forme dépend du template configuré
            côté admin listmonk.
        template_id: ID du template transactional listmonk, résolu par
            l'appelant depuis la base selon la culture du destinataire
            (`listmonk_templates.resolve_template_for_user`).

    Returns:
        True si listmonk a accepté la requête (HTTP 2xx). False si :
          - HTTP 4xx/5xx (token invalide, template_id invalide, payload rejeté)
          - réseau (timeout, DNS, connect refused)
    """
    body = {
        "subscriber_email": email,
        "template_id": template_id,
        "data": payload,
        "headers": [{_TX_ID_HEADER: tx_id}],
    }
    url = f"{connection.url}/api/tx"

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            # 1. Garantir que le subscriber existe côté listmonk
            #    (sinon /api/tx renvoie 400 "Subscriber not found").
            if not await _ensure_subscriber(client, connection, email):
                logger.warning(
                    "listmonk_trigger_aborted_subscriber_missing",
                    tx_id=tx_id,
                    email=email,
                )
                return False

            # 2. Trigger le template transactional.
            response = await client.post(
                url,
                json=body,
                headers={
                    "Authorization": auth_header(connection),
                    "Content-Type": "application/json",
                },
            )
        if response.status_code >= 400:
            logger.warning(
                "listmonk_trigger_http_error",
                tx_id=tx_id,
                status=response.status_code,
                body=response.text[:500],
            )
            return False
        logger.info(
            "listmonk_trigger_ok",
            tx_id=tx_id,
            status=response.status_code,
        )
        return True
    except httpx.HTTPError as exc:
        logger.warning(
            "listmonk_trigger_network_error",
            tx_id=tx_id,
            error=str(exc),
        )
        return False
