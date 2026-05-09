"""Endpoint webhook générique pour les retours du provider d'envoi de mail.

⚠️ STANDBY (LOT_57) — Le provider final n'est pas encore arrêté (Novu sortant
car les webhooks sont une feature payante). En attendant :

- L'endpoint accepte tout body JSON et répond 200 (pas de retry côté provider).
- Le body est loggé brut côté Loki pour analyse du format réel quand le
  nouveau provider sera branché.
- Le dispatch vers `notification_delivery.update_delivery_status` est
  PRÉPARÉ mais COMMENTÉ : à débrancher dès qu'on connaît le format exact
  des champs (transaction_id, event_type, timestamp) ET la signature HMAC
  à valider via `NOTIFY_WEBHOOK_SECRET`.

Sécurité actuelle : aucune. Endpoint public, pas d'auth, pas de signature.
**À NE PAS BRANCHER À UNE URL PUBLIQUE** tant que la validation n'est pas
implémentée — sinon n'importe qui peut polluer `delivery_status` en DB.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.logging import logger

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/notify")
async def receive_notify_webhook(request: Request) -> JSONResponse:
    """Webhook callback du provider d'envoi de mail.

    Implémentation MINIMALE : log + 200. Le dispatch vers le service
    de mise à jour des statuts (`notification_delivery.update_delivery_status`)
    sera ajouté quand :
      1. Le provider final sera choisi (post-Novu)
      2. La signature HMAC sera connue (header + secret)
      3. Le format JSON exact sera confirmé (champs, casing, enveloppe)
    """
    raw_body = await request.body()
    headers_dict = dict(request.headers)
    # On retire les headers sensibles avant de logger.
    headers_dict.pop("authorization", None)
    headers_dict.pop("cookie", None)

    logger.info(
        "notify_webhook_received_standby",
        headers=headers_dict,
        body=raw_body[:2000].decode("utf-8", errors="replace"),
        body_size=len(raw_body),
        note="endpoint in standby — no signature validation, no DB update",
    )

    # ─── À débrancher quand le provider sera connu : ───────────────────────
    #
    # 1. Validation HMAC :
    #
    #    secret = settings.notify_webhook_secret
    #    signature_header = request.headers.get("X-Provider-Signature")
    #    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    #    if not hmac.compare_digest(expected, signature_header or ""):
    #        raise HTTPException(401, detail={"error": "invalid_signature"})
    #
    # 2. Parsing du payload (format à confirmer côté listmonk) :
    #
    #    payload = await request.json()
    #    transaction_id = (
    #        payload.get("transactionId")
    #        or payload.get("data", {}).get("transactionId")
    #    )
    #    provider_event = payload.get("event") or payload.get("type")
    #    occurred_at_str = payload.get("timestamp")
    #    occurred_at = (
    #        datetime.fromisoformat(occurred_at_str) if occurred_at_str else None
    #    )
    #
    # 3. Persiste l'event dans notification_events (un INSERT par event reçu) :
    #
    #    from app.services import notification_delivery as delivery_svc
    #    pool = await get_pool()
    #    async with pool.acquire() as conn:
    #        await delivery_svc.record_event(
    #            conn,
    #            transaction_id=transaction_id,
    #            provider_event=provider_event,
    #            occurred_at=occurred_at,
    #            metadata=payload,  # garde le payload brut pour debug
    #        )
    #
    # 4. Push WebSocket aux clients abonnés au tracking_id de cette session
    #    (à implémenter en phase 4 — broker `recovery_ws_broker`).
    # ────────────────────────────────────────────────────────────────────────

    return JSONResponse({"received": True})
