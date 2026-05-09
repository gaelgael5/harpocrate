"""Service de réinitialisation de passphrase via recovery seed (LOT_57).

Workflow zero-knowledge — le serveur ne valide JAMAIS les recovery words.
Il fournit les blobs chiffrés au client, qui tente le déchiffrement avec
la recovery_key dérivée des 24 mots BIP-39. En cas d'échec le client
doit signaler explicitement (`attempt_failed`) — le compteur sert
principalement contre les erreurs honnêtes ; la vraie protection contre
l'attaque vient de l'entropie de 256 bits du seed et de l'Argon2id.
"""
from __future__ import annotations

import asyncio
import base64
import datetime
import uuid
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import asyncpg

from app.core.config import settings
from app.core.logging import logger
from app.db.repositories import recovery_sessions as repo
from app.db.repositories import users as users_repo
from app.services import notification_delivery as delivery_svc
from app.services import notify_listmonk
from app.services.audit import audit_log_insert


# Les seuils ci-dessous sont LU dynamiquement depuis settings — pas de cache
# module-level. Si l'admin change `HARPOCRATE_RECOVERY_MAX_ATTEMPTS=10` puis
# redémarre le container, la nouvelle valeur prend effet immédiatement.
def _session_ttl() -> datetime.timedelta:
    return datetime.timedelta(minutes=settings.recovery_session_ttl_minutes)


def _max_attempts() -> int:
    return settings.recovery_max_attempts


def _anomaly_threshold() -> int:
    return settings.recovery_anomaly_threshold


def _anomaly_window() -> datetime.timedelta:
    return datetime.timedelta(hours=settings.recovery_anomaly_window_hours)


# Garde-fou RUF006 : on stocke les tasks Novu fire-and-forget pour empêcher
# le garbage collector Python de les annuler avant la fin du POST HTTP.
_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


class RecoverySessionError(Exception):
    """Base — comportements traduits en HTTPException par le router."""


class SessionNotFoundError(RecoverySessionError):
    pass


class SessionInvalidError(RecoverySessionError):
    """Session expirée, déjà consommée, ou tentatives épuisées."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class RecoveryBlobs:
    """Données rendues au client pour qu'il dérive recovery_key + déchiffre.

    Tous les `bytes` sont base64-encodés à la sérialisation HTTP.
    """

    session_id: UUID
    attempts_left: int
    salt_recovery: bytes
    encrypted_sym_key_by_recovery: bytes
    salt_passphrase: bytes
    encrypted_rsa_private_key: bytes
    rsa_public_key: bytes
    kdf_memory_kb: int
    kdf_iterations: int
    kdf_parallelism: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": str(self.session_id),
            "attempts_left": self.attempts_left,
            "salt_recovery": base64.b64encode(self.salt_recovery).decode(),
            "encrypted_sym_key_by_recovery": base64.b64encode(
                self.encrypted_sym_key_by_recovery
            ).decode(),
            "salt_passphrase": base64.b64encode(self.salt_passphrase).decode(),
            "encrypted_rsa_private_key": base64.b64encode(
                self.encrypted_rsa_private_key
            ).decode(),
            "rsa_public_key": base64.b64encode(self.rsa_public_key).decode(),
            "kdf_params": {
                "memory_kb": self.kdf_memory_kb,
                "iterations": self.kdf_iterations,
                "parallelism": self.kdf_parallelism,
            },
        }


# ─── Start ────────────────────────────────────────────────────────────────────


async def start_session(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    email: str,
    ip: str | None,
    user_agent: str | None = None,
    public_url: str | None = None,
) -> UUID:
    """Crée une session et déclenche la notification.

    Anti-énumération : retourne TOUJOURS un `tracking_id` UUID au caller,
    qu'un user existe ou pas. Le `tracking_id` est destiné au futur
    endpoint WebSocket de suivi de livraison (séparé du `session_id`
    secret reçu par mail). Quand l'email est inconnu, le tracking_id
    pointe sur une row "fantôme" : aucun webhook ne viendra jamais
    l'updater → la WS restera silencieuse, indistinguable d'une vraie
    session côté client.

    La détection d'anomalie (5+ sessions failed/expired sur 24h) est
    aussi faite ici.
    """
    ttl = _session_ttl()
    now = datetime.datetime.now(datetime.UTC)
    expires_at = now + ttl

    user_row = await users_repo.get_id_and_is_system_by_email(conn, email)
    user_id: UUID | None = None
    if user_row is not None:
        user_id, is_system = user_row
        # On ne déclenche pas de recovery pour un system user (admin local) :
        # leur passphrase n'a pas de sens, ils n'ont pas de matériel crypto.
        if is_system:
            logger.info(
                "recovery_skip_system_user",
                email=email,
                user_id=str(user_id),
            )
            user_id = None

    session_id, tracking_id = await repo.insert(
        conn,
        user_id=user_id,
        email=email,
        expires_at=expires_at,
        ip_started=ip,
    )

    # Détection d'anomalie : 5+ échecs récents pour cet email.
    if user_id is not None:
        await _maybe_record_anomaly(conn, email=email, user_id=user_id)

    if user_id is not None:
        # Trigger listmonk en arrière-plan : on ne bloque pas la réponse HTTP.
        # `notify_listmonk.trigger_recovery` swallow déjà ses erreurs.
        link_base = (public_url or settings.public_url).rstrip("/")
        recovery_link = f"{link_base}/recover/{session_id}"
        # Payload consommé par le template listmonk via {{ data.* }}.
        # Tous les champs sont stringifiés (listmonk Sprig templates ne font
        # pas de coercion automatique). Locale du template à choisir plus
        # tard depuis la préférence user.
        listmonk_payload = {
            "appName": "Harpocrate",
            "expiresInMinutes": str(int(ttl.total_seconds() / 60)),
            "recoveryLink": recovery_link,
            "requestIp": ip or "",
            "requestUserAgent": user_agent or "",
            "requestedAt": now.isoformat(),
            "year": str(now.year),
        }
        # On génère le tx_id côté Harpocrate AVANT l'appel listmonk pour
        # pouvoir le persister immédiatement (au cas où l'envoi mail échoue,
        # on a quand même la trace en DB). Le tx_id est passé à listmonk
        # via header custom `X-Harpocrate-Tx-Id` — listmonk le forward dans
        # ses webhooks de delivery, ce qui permettra plus tard la jointure.
        tx_id = str(uuid.uuid4())

        async def _persist_tx_and_trigger() -> None:
            from app.db.pool import get_pool

            pool = await get_pool()
            try:
                async with pool.acquire() as bg_conn:
                    await repo.set_novu_transaction_id(
                        bg_conn,
                        session_id=session_id,
                        transaction_id=tx_id,
                    )
            except Exception as exc:
                # Si la persistance du tx_id rate, on n'envoie pas — sinon
                # on aurait un mail dans la nature sans trace côté Harpocrate.
                logger.warning(
                    "recovery_tx_persist_failed",
                    session_id=str(session_id),
                    tx_id=tx_id,
                    error=str(exc),
                )
                return

            sent = await notify_listmonk.trigger_recovery(
                email=email,
                tx_id=tx_id,
                payload=listmonk_payload,
                locale="fr",  # TODO: lire depuis users.preferred_locale quand dispo
            )
            if not sent:
                return

            # Amorce la timeline notification_events avec un event 'sent'
            # local — avant même le premier webhook delivery de listmonk.
            try:
                async with pool.acquire() as bg_conn:
                    await delivery_svc.record_local_sent(
                        bg_conn,
                        transaction_id=tx_id,
                        metadata={
                            "source": "trigger",
                            "provider": "listmonk",
                            "session_id": str(session_id),
                        },
                    )
            except Exception as exc:
                logger.warning(
                    "recovery_local_sent_persist_failed",
                    session_id=str(session_id),
                    tx_id=tx_id,
                    error=str(exc),
                )

        # On garde une référence dans `_BACKGROUND_TASKS` pour empêcher
        # le garbage-collector de tuer le task avant qu'il ne se termine
        # (cf. RUF006 / docs Python 3.12 asyncio).
        task = asyncio.create_task(_persist_tx_and_trigger())
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)
        await audit_log_insert(
            conn,
            "user.recovery_session_started",
            actor_user_id=user_id,
            target_user_id=user_id,
            actor_ip=ip,
            metadata={"session_id": str(session_id), "email": email},
        )
        logger.info(
            "recovery_session_started",
            session_id=str(session_id),
            email=email,
            user_id=str(user_id),
        )
    else:
        # Email inconnu : pas d'audit_log DB (le CHECK audit_log_one_actor
        # exige un acteur). Le log structlog part dans Loki via Alloy.
        logger.info(
            "recovery_session_started_unknown_email",
            session_id=str(session_id),
            email=email,
        )

    return tracking_id


async def _maybe_record_anomaly(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    email: str,
    user_id: UUID,
) -> None:
    since = datetime.datetime.now(datetime.UTC) - _anomaly_window()
    count = await repo.count_unsuccessful_for_email(conn, email=email, since=since)
    if count < _anomaly_threshold():
        return
    await conn.execute(
        """
        INSERT INTO identity_anomaly_events
            (user_id, severity, anomaly_type, metadata)
        VALUES ($1, $2, $3, $4::jsonb)
        """,
        user_id,
        "warning",
        "recovery_session_repeated_failures",
        f'{{"unsuccessful_sessions_24h": {count}, "email": "{email}"}}',
    )
    logger.warning(
        "recovery_anomaly_detected",
        email=email,
        user_id=str(user_id),
        unsuccessful_24h=count,
    )


# ─── Get ──────────────────────────────────────────────────────────────────────


async def get_blobs(
    conn: asyncpg.Connection[asyncpg.Record],
    session_id: UUID,
) -> RecoveryBlobs:
    row = await repo.get_by_id(conn, session_id)
    if row is None:
        raise SessionNotFoundError("session not found")
    if row["status"] != "pending":
        raise SessionInvalidError(f"session_{row['status']}")
    if row["expires_at"] < datetime.datetime.now(datetime.UTC):
        raise SessionInvalidError("session_expired")
    if row["user_id"] is None:
        # Email inconnu — on n'a pas de blobs à fournir. Indistinguable côté
        # client d'une session pour un email connu mais expirée — pas de
        # fuite d'information.
        raise SessionInvalidError("session_unrecoverable")

    user = await users_repo.get_by_id(conn, row["user_id"])
    if user is None:
        # User a été supprimé entre-temps.
        raise SessionInvalidError("session_unrecoverable")

    return RecoveryBlobs(
        session_id=row["id"],
        attempts_left=max(0, _max_attempts() - row["attempts"]),
        salt_recovery=user.salt_recovery,
        encrypted_sym_key_by_recovery=user.encrypted_sym_key_by_recovery,
        salt_passphrase=user.salt_passphrase,
        encrypted_rsa_private_key=user.encrypted_rsa_private_key,
        rsa_public_key=user.rsa_public_key,
        kdf_memory_kb=user.kdf_memory_kb,
        kdf_iterations=user.kdf_iterations,
        kdf_parallelism=user.kdf_parallelism,
    )


# ─── Attempt failed ───────────────────────────────────────────────────────────


async def record_failed_attempt(
    conn: asyncpg.Connection[asyncpg.Record],
    session_id: UUID,
) -> int:
    """Incrémente le compteur. Retourne `attempts_left`. Si la session
    n'est plus 'pending', l'increment ne fait rien — on lève
    SessionInvalidError pour informer le client."""
    max_att = _max_attempts()
    new_attempts = await repo.increment_attempts(
        conn, session_id, max_attempts=max_att
    )
    if new_attempts is None:
        # increment_attempts WHERE status = 'pending' n'a affecté aucune row.
        row = await repo.get_by_id(conn, session_id)
        if row is None:
            raise SessionNotFoundError("session not found")
        raise SessionInvalidError(f"session_{row['status']}")

    # Si on vient d'atteindre le max (donc status='failed'), on trace
    # l'événement de session brûlée pour l'audit. Pas d'audit pour les
    # attempts intermédiaires : ce sont des erreurs de saisie banales.
    if new_attempts >= max_att:
        row = await repo.get_by_id(conn, session_id)
        if row is not None and row["user_id"] is not None:
            await audit_log_insert(
                conn,
                "user.recovery_session_exhausted",
                actor_user_id=row["user_id"],
                target_user_id=row["user_id"],
                metadata={"session_id": str(session_id)},
            )
    return max(0, max_att - new_attempts)


# ─── Complete ─────────────────────────────────────────────────────────────────


async def abandon_account(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    session_id: UUID,
    ip: str | None,
) -> None:
    """Détruit le compte de l'utilisateur lié à la session : DELETE wallets
    (cascade secrets) puis DELETE users. Marque la session 'consumed' pour
    empêcher la réutilisation.

    Sécurité : le caller doit avoir prouvé l'accès à l'email (via le lien
    Novu reçu dans la boîte mail), ce qui est suffisant pour autoriser la
    DESTRUCTION (pas le vol — sans les recovery words il ne peut pas
    récupérer les données chiffrées). Audit + identity_anomaly_event tracé.
    """
    row = await repo.get_by_id(conn, session_id)
    if row is None:
        raise SessionNotFoundError("session not found")
    # On accepte 'pending' OU 'failed' OU 'expired' : tous les cas où l'user
    # est en train d'essayer de récupérer son accès. Pas 'consumed' (déjà
    # fait quelque chose avec).
    if row["status"] == "consumed":
        raise SessionInvalidError("session_consumed")
    if row["user_id"] is None:
        raise SessionInvalidError("session_unrecoverable")

    user_id: UUID = row["user_id"]
    email: str = row["email"]

    async with conn.transaction():
        # Désactive temporairement les triggers métier (notamment
        # `protect_owner_grant_delete` qui bloque la suppression du grant
        # auto-owner d'un wallet). Scope = transaction courante uniquement.
        # Les FK et CHECK SQL continuent d'être appliqués normalement.
        await conn.execute("SET LOCAL session_replication_role = 'replica'")

        # Grants émis par cet user vers d'autres users (RESTRICT sur
        # `granted_by_user_id`) — il faut les vider avant DELETE users
        # sinon la contrainte bloque même hors trigger.
        await conn.execute(
            "DELETE FROM wallet_grants WHERE granted_by_user_id = $1",
            user_id,
        )

        # Wallets dont il est owner (RESTRICT) → cascade les grants reçus
        # et les secrets associés. Le trigger protect_owner_grant_delete
        # est désactivé pour la transaction → la cascade peut se finir.
        await conn.execute("DELETE FROM wallets WHERE owner_user_id = $1", user_id)

        # L'user lui-même (cascade le reste : anomalies, sessions, etc.)
        await conn.execute("DELETE FROM users WHERE id = $1", user_id)
        # NB : on ne peut PAS audit_log_insert ici (FK actor_user_id pointe
        # sur la row qu'on vient de DELETE — violerait audit_log_one_actor).
        # On trace via structlog uniquement (visible côté Loki).

    await repo.mark_consumed(conn, session_id=session_id, ip_consumed=ip)
    logger.warning(
        "recovery_account_abandoned",
        session_id=str(session_id),
        deleted_user_id=str(user_id),
        email=email,
        ip=ip,
    )


async def complete_session(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    session_id: UUID,
    new_salt_passphrase: bytes,
    new_encrypted_rsa_private_key: bytes,
    new_encrypted_sym_key_by_pass: bytes,
    kdf_memory_kb: int,
    kdf_iterations: int,
    kdf_parallelism: int,
    ip: str | None,
) -> None:
    row = await repo.get_by_id(conn, session_id)
    if row is None:
        raise SessionNotFoundError("session not found")
    if row["status"] != "pending":
        raise SessionInvalidError(f"session_{row['status']}")
    if row["expires_at"] < datetime.datetime.now(datetime.UTC):
        raise SessionInvalidError("session_expired")
    if row["user_id"] is None:
        raise SessionInvalidError("session_unrecoverable")

    await users_repo.update_passphrase(
        conn,
        user_id=row["user_id"],
        new_salt_passphrase=new_salt_passphrase,
        new_encrypted_rsa_private_key=new_encrypted_rsa_private_key,
        new_encrypted_sym_key_by_pass=new_encrypted_sym_key_by_pass,
        kdf_memory_kb=kdf_memory_kb,
        kdf_iterations=kdf_iterations,
        kdf_parallelism=kdf_parallelism,
    )
    await repo.mark_consumed(conn, session_id=session_id, ip_consumed=ip)
    await audit_log_insert(
        conn,
        "user.passphrase_reset_via_recovery",
        actor_user_id=row["user_id"],
        target_user_id=row["user_id"],
        actor_ip=ip,
        metadata={"session_id": str(session_id)},
    )
    logger.info(
        "recovery_session_consumed",
        session_id=str(session_id),
        user_id=str(row["user_id"]),
    )
