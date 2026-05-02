"""Service de gouvernance d'identité (LOT_02).

Fonctions : extraction d'identité externe depuis JWT, détection d'anomalies,
application de quarantaine, vérification d'état de quarantaine.
"""
from __future__ import annotations

from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Any

import asyncpg

from app.core.config import settings
from app.db.repositories import anomalies as anomalies_repo
from app.models.db.user import UserRow

# ─── Extraction d'identité ────────────────────────────────────────────────────


def extract_external_identity(jwt_payload: dict[str, Any]) -> tuple[str, str]:
    """Extrait (provider, external_subject) depuis un payload JWT.

    Ordre de priorité :
    1. Claims explicites ``external_sub`` + ``external_provider`` (mapper Keycloak).
    2. Claim ``federated_identity`` (liste de fédérations Keycloak).
    3. Fallback sur ``("keycloak_internal", payload["sub"])``.
    """
    external_sub: str | None = jwt_payload.get("external_sub")
    external_provider: str | None = jwt_payload.get("external_provider")
    if external_sub and external_provider:
        return (external_provider, external_sub)

    federated: list[dict[str, Any]] = jwt_payload.get("federated_identity", [])
    if federated:
        first = federated[0]
        provider: str = first.get("identityProvider", "google")
        sub: str | None = first.get("userId") or first.get("sub")
        if sub:
            return (provider, sub)

    return ("keycloak_internal", jwt_payload["sub"])


# ─── Détection d'anomalies ────────────────────────────────────────────────────


def _names_similar(old: str, new: str) -> bool:
    """Similarité naïve : ratio SequenceMatcher > 0.7."""
    return SequenceMatcher(None, old.lower(), new.lower()).ratio() > 0.7


async def detect_login_anomalies(
    conn: asyncpg.Connection,  # type: ignore[type-arg]
    user: UserRow,
    jwt_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """Compare les claims JWT avec le snapshot utilisateur.

    Insère chaque anomalie dans ``identity_anomaly_events`` via le repository.
    Retourne la liste des anomalies émises (chacune comme dict avec severity/type/metadata).

    Cette fonction est best-effort : elle ne doit PAS lever d'exception en cas d'anomalie
    info/warning. Les anomalies critiques sont enregistrées mais ne bloquent pas ici ;
    c'est l'appelant qui décide de bloquer.
    """
    emitted: list[dict[str, Any]] = []

    new_email: str = jwt_payload.get("email", "")
    new_name: str = jwt_payload.get("name", "")

    # 1. Email changé
    if new_email and new_email != user.email:
        anomaly: dict[str, Any] = {
            "severity": "info",
            "type": "email_changed",
            "metadata": {"old": user.email, "new": new_email},
        }
        await anomalies_repo.insert(
            conn,
            user_id=user.id,
            severity=anomaly["severity"],
            anomaly_type=anomaly["type"],
            metadata=anomaly["metadata"],
        )
        emitted.append(anomaly)

    # 2. Display name changé significativement
    if user.display_name and new_name and not _names_similar(user.display_name, new_name):
        anomaly = {
            "severity": "warning",
            "type": "display_name_changed_significantly",
            "metadata": {"old": user.display_name, "new": new_name},
        }
        await anomalies_repo.insert(
            conn,
            user_id=user.id,
            severity=anomaly["severity"],
            anomaly_type=anomaly["type"],
            metadata=anomaly["metadata"],
        )
        emitted.append(anomaly)

    # 3. Inactivité longue
    if user.last_unlock_at is not None:
        last = user.last_unlock_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        days_inactive = (datetime.now(UTC) - last).days
        if days_inactive > settings.quarantine_inactivity_days:
            anomaly = {
                "severity": "warning",
                "type": "long_inactivity",
                "metadata": {"days": days_inactive},
            }
            await anomalies_repo.insert(
                conn,
                user_id=user.id,
                severity=anomaly["severity"],
                anomaly_type=anomaly["type"],
                metadata=anomaly["metadata"],
            )
            emitted.append(anomaly)

    # 4. email_verified flipped to false
    if not jwt_payload.get("email_verified", True):
        anomaly = {
            "severity": "critical",
            "type": "email_no_longer_verified",
            "metadata": {},
        }
        await anomalies_repo.insert(
            conn,
            user_id=user.id,
            severity=anomaly["severity"],
            anomaly_type=anomaly["type"],
            metadata=anomaly["metadata"],
        )
        emitted.append(anomaly)

    return emitted


# ─── Quarantaine ──────────────────────────────────────────────────────────────


def is_in_quarantine(user: UserRow) -> bool:
    """Retourne True si l'utilisateur est actuellement en quarantaine."""
    if user.quarantine_until is None:
        return False
    q_until = user.quarantine_until
    if q_until.tzinfo is None:
        q_until = q_until.replace(tzinfo=UTC)
    return q_until > datetime.now(UTC)


async def apply_quarantine_if_needed(
    conn: asyncpg.Connection,  # type: ignore[type-arg]
    user: UserRow,
    anomalies: list[dict[str, Any]],
) -> None:
    """Applique ou lève la quarantaine selon l'état du user et les anomalies.

    Cas 1 : quarantaine déjà active — si expirée, on la lève.
    Cas 2 : inactivité longue détectée → quarantaine pour quarantine_duration_days.
    Cas 3 : anomalie critique → quarantaine immédiate.
    """
    from app.services.audit import audit_log_insert

    if user.quarantine_until is not None:
        q_until = user.quarantine_until
        if q_until.tzinfo is None:
            q_until = q_until.replace(tzinfo=UTC)
        if q_until > datetime.now(UTC):
            return  # quarantaine encore active
        # Quarantaine expirée → lever
        await conn.execute(
            "UPDATE users SET quarantine_until = NULL, quarantine_reason = NULL "
            "WHERE id = $1",
            user.id,
        )
        return

    duration = settings.quarantine_duration_days

    has_long_inactivity = any(a["type"] == "long_inactivity" for a in anomalies)
    has_critical = any(a["severity"] == "critical" for a in anomalies)

    if has_long_inactivity:
        await conn.execute(
            f"""UPDATE users
               SET quarantine_until = NOW() + INTERVAL '{duration} days',
                   quarantine_reason = 'long_inactivity_login'
               WHERE id = $1""",
            user.id,
        )
        await audit_log_insert(
            conn,
            "user.quarantine_started",
            actor_user_id=user.id,
            target_user_id=user.id,
            metadata={"reason": "long_inactivity_login"},
        )

    if has_critical:
        await conn.execute(
            f"""UPDATE users
               SET quarantine_until = NOW() + INTERVAL '{duration} days',
                   quarantine_reason = 'critical_anomaly_detected'
               WHERE id = $1""",
            user.id,
        )
        await audit_log_insert(
            conn,
            "user.quarantine_started",
            actor_user_id=user.id,
            target_user_id=user.id,
            metadata={"reason": "critical_anomaly_detected"},
        )
