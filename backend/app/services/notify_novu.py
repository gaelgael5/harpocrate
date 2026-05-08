"""Client Novu — déclenche des workflows de notification (LOT_57).

Harpocrate ne gère pas l'envoi de mail : il appelle l'API Novu qui s'occupe
du templating, de la localisation et du provider de mail (Brevo, Sendgrid…).
Côté Harpocrate, on POST un event ; côté Novu, l'admin a configuré un
workflow pour ce nom d'event.

Comportement :
- Fire-and-forget : la fonction `trigger_event` est awaitable et fait un
  POST synchrone, mais les callers la lancent typiquement via
  `asyncio.create_task` pour ne pas bloquer la réponse HTTP.
- No-op silencieux si `novu_configured=False` : on log un warning et on
  retourne sans erreur. C'est intentionnel — un déploiement dev sans clé
  Novu ne doit pas casser le flow recovery côté UI (l'utilisateur reçoit
  toujours une 202, on indique juste dans les logs que rien n'a été envoyé).
- Échec réseau ou HTTP 4xx/5xx : log structuré, pas de re-raise. La
  notification est best-effort. Le côté serveur garde la session de
  recovery valide même si l'email n'est pas parti — le user peut retenter.
"""
from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import logger

_TIMEOUT_SECONDS = 5.0


class NovuNotConfiguredError(RuntimeError):
    """Levée uniquement si un caller force l'envoi sans config (tests)."""


async def trigger_event(
    name: str,
    *,
    subscriber_id: str,
    email: str,
    payload: dict[str, Any],
    raise_if_unconfigured: bool = False,
) -> None:
    """Déclenche un workflow Novu pour `name` à destination de `subscriber_id`.

    Args:
        name: nom du workflow Novu (ex: 'passphrase-reset').
        subscriber_id: identifiant stable du destinataire côté Novu (ex: user.id).
            Novu auto-crée le subscriber au premier trigger.
        email: adresse email du destinataire (Novu en a besoin pour le canal mail).
        payload: variables consommées par le template Novu. La forme dépend du
            workflow configuré côté admin Novu.
        raise_if_unconfigured: par défaut False → no-op si pas de clé. À mettre
            True dans les tests qui veulent vérifier que la config est présente.
    """
    if not settings.novu_configured:
        if raise_if_unconfigured:
            raise NovuNotConfiguredError(
                "HARPOCRATE_NOVU_API_KEY not set — cannot trigger Novu workflow"
            )
        logger.warning(
            "novu_not_configured",
            event_name=name,
            subscriber_id=subscriber_id,
            note="event skipped — set HARPOCRATE_NOVU_API_KEY to enable",
        )
        return

    body = {
        "name": name,
        "to": {"subscriberId": subscriber_id, "email": email},
        "payload": payload,
    }
    url = f"{settings.novu_api_url.rstrip('/')}/events/trigger"

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(
                url,
                json=body,
                headers={
                    "Authorization": f"ApiKey {settings.novu_api_key}",
                    "Content-Type": "application/json",
                },
            )
        if response.status_code >= 400:
            logger.warning(
                "novu_trigger_http_error",
                event_name=name,
                subscriber_id=subscriber_id,
                status=response.status_code,
                body=response.text[:500],
            )
            return
        logger.info(
            "novu_trigger_ok",
            event_name=name,
            subscriber_id=subscriber_id,
            status=response.status_code,
        )
    except httpx.HTTPError as exc:
        # Réseau, timeout, DNS… on ne casse pas le flow caller.
        logger.warning(
            "novu_trigger_network_error",
            event_name=name,
            subscriber_id=subscriber_id,
            error=str(exc),
        )
