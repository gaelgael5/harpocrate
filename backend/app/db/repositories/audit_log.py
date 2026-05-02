"""Requêtes SQL pour la table audit_log — lecture (LOT_10).

Le repository gère uniquement la couche SQL (pas de logique métier).
La logique de filtrage selon le type d'auth est dans app/services/audit_log.py.
"""
from __future__ import annotations

import base64
import datetime
from typing import Any
from uuid import UUID

import asyncpg

# ─── Clés metadata sensibles à bannir (défense en profondeur) ─────────────────

_SENSITIVE_METADATA_KEYS: frozenset[str] = frozenset(
    {
        "passphrase",
        "password",
        "encrypted_value",
        "encrypted_rsa_private_key",
        "encrypted_sym_key",
        "encrypted_wallet_key",
        "salt",
        "auth_hash",
        "auth_secret",
        "dkey",
        "decryption_key",
        "recovery_key",
        "token",
        "secret_value",
        "plaintext",
    }
)


def _strip_sensitive_metadata(
    raw: dict[str, Any] | None,
) -> dict[str, object] | None:
    """Supprime les clés sensibles du JSONB metadata (défense en profondeur).

    Cette vérification est appliquée au niveau API pour garantir qu'aucune
    valeur cryptographique ne fuite, même si audit_log_insert était appelé
    incorrectement.
    """
    if raw is None:
        return None
    cleaned: dict[str, object] = {}
    for key, value in raw.items():
        if key.lower() in _SENSITIVE_METADATA_KEYS:
            # On remplace silencieusement par un marqueur — pas de KeyError
            cleaned[key] = "[REDACTED]"
        else:
            cleaned[key] = value
    return cleaned or None


# ─── Cursor helpers ───────────────────────────────────────────────────────────


def encode_cursor(occurred_at: datetime.datetime, row_id: int) -> str:
    """Encode (occurred_at, id) en base64 URL-safe sans padding."""
    raw = f"{occurred_at.isoformat()}|{row_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime.datetime, int]:
    """Décode un cursor en (occurred_at, id). Lève ValueError si invalide."""
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded).decode()
        ts_str, id_str = raw.split("|", 1)
        return datetime.datetime.fromisoformat(ts_str), int(id_str)
    except Exception as exc:
        raise ValueError(f"Cursor invalide : {exc}") from exc


# ─── Query principale ─────────────────────────────────────────────────────────


async def query_audit_log(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    # Contraintes de sécurité (forcées par le service)
    force_actor_api_key_id: UUID | None = None,
    jwt_user_id: UUID | None = None,
    jwt_owned_wallet_ids: list[UUID] | None = None,
    # Filtres optionnels (ignorés pour API key)
    filter_wallet_id: UUID | None = None,
    filter_action: str | None = None,
    filter_action_prefix: str | None = None,
    filter_since: datetime.datetime | None = None,
    filter_until: datetime.datetime | None = None,
    filter_actor_user_id: UUID | None = None,
    filter_actor_api_key_id: UUID | None = None,
    filter_target_secret_id: UUID | None = None,
    filter_success: bool | None = None,
    # Pagination
    cursor_occurred_at: datetime.datetime | None = None,
    cursor_id: int | None = None,
    limit: int = 50,
) -> list[asyncpg.Record]:
    """Exécute la query audit_log avec filtres de sécurité et optionnels.

    Le paramètre limit+1 est récupéré pour permettre la détection de has_more.
    """
    conditions: list[str] = ["1=1"]
    params: list[Any] = []
    idx = 1

    # ── Contraintes de sécurité (TOUJOURS appliquées en premier) ─────────────

    if force_actor_api_key_id is not None:
        # API key : filtre forcé — le caller ne voit que ses propres actions
        conditions.append(f"al.actor_api_key_id = ${idx}")
        params.append(force_actor_api_key_id)
        idx += 1
    elif jwt_user_id is not None:
        # JWT : ses propres actions OU actions sur ses wallets owned
        owned = jwt_owned_wallet_ids or []
        if owned:
            conditions.append(
                f"(al.actor_user_id = ${idx} OR al.target_wallet_id = ANY(${idx + 1}::uuid[]))"
            )
            params.append(jwt_user_id)
            params.append(owned)
            idx += 2
        else:
            conditions.append(f"al.actor_user_id = ${idx}")
            params.append(jwt_user_id)
            idx += 1

    # ── Filtres optionnels (seulement pour JWT) ────────────────────────────────

    if force_actor_api_key_id is None:
        if filter_wallet_id is not None:
            conditions.append(f"al.target_wallet_id = ${idx}")
            params.append(filter_wallet_id)
            idx += 1

        if filter_actor_user_id is not None:
            conditions.append(f"al.actor_user_id = ${idx}")
            params.append(filter_actor_user_id)
            idx += 1

        if filter_actor_api_key_id is not None:
            conditions.append(f"al.actor_api_key_id = ${idx}")
            params.append(filter_actor_api_key_id)
            idx += 1

        if filter_target_secret_id is not None:
            conditions.append(f"al.target_secret_id = ${idx}")
            params.append(filter_target_secret_id)
            idx += 1

    # Filtres communs (action, dates, success)
    if filter_action is not None:
        conditions.append(f"al.action = ${idx}")
        params.append(filter_action)
        idx += 1
    elif filter_action_prefix is not None:
        # LIKE 'prefix%' — optimisé par l'index sur action
        conditions.append(f"al.action LIKE ${idx}")
        params.append(filter_action_prefix.rstrip("%") + "%")
        idx += 1

    if filter_since is not None:
        conditions.append(f"al.occurred_at >= ${idx}")
        params.append(filter_since)
        idx += 1

    if filter_until is not None:
        conditions.append(f"al.occurred_at <= ${idx}")
        params.append(filter_until)
        idx += 1

    if filter_success is not None:
        conditions.append(f"al.success = ${idx}")
        params.append(filter_success)
        idx += 1

    # ── Pagination cursor ──────────────────────────────────────────────────────

    if cursor_occurred_at is not None and cursor_id is not None:
        conditions.append(
            f"(al.occurred_at, al.id) < (${idx}::timestamptz, ${idx + 1})"
        )
        params.append(cursor_occurred_at)
        params.append(cursor_id)
        idx += 2

    where_clause = " AND ".join(conditions)
    params.append(limit + 1)  # +1 pour détecter has_more

    sql = f"""
        SELECT
            al.id,
            al.occurred_at,
            al.action,
            al.actor_user_id,
            al.actor_api_key_id,
            al.actor_ip::text AS actor_ip,
            al.target_wallet_id,
            al.target_secret_id,
            al.target_user_id,
            al.target_api_key_id,
            al.metadata,
            al.success,
            al.error_code,
            u.email AS actor_user_email,
            u.display_name AS actor_user_display_name,
            ak.name AS actor_api_key_name,
            w.name AS target_wallet_name
        FROM audit_log al
        LEFT JOIN users u ON u.id = al.actor_user_id
        LEFT JOIN api_keys ak ON ak.id = al.actor_api_key_id
        LEFT JOIN wallets w ON w.id = al.target_wallet_id
        WHERE {where_clause}
        ORDER BY al.occurred_at DESC, al.id DESC
        LIMIT ${idx}
    """

    return list(await conn.fetch(sql, *params))


# ─── Query actions distinctes ─────────────────────────────────────────────────


async def get_distinct_actions(
    conn: asyncpg.Connection[asyncpg.Record],
) -> list[str]:
    """Retourne la liste des actions distinctes présentes dans audit_log."""
    rows = await conn.fetch(
        "SELECT DISTINCT action FROM audit_log ORDER BY action ASC"
    )
    return [row["action"] for row in rows]


# ─── Query wallets owned par un user ─────────────────────────────────────────


async def get_owned_wallet_ids(
    conn: asyncpg.Connection[asyncpg.Record],
    user_id: UUID,
) -> list[UUID]:
    """Retourne les IDs des wallets dont user_id est owner."""
    rows = await conn.fetch(
        "SELECT id FROM wallets WHERE owner_user_id = $1",
        user_id,
    )
    return [row["id"] for row in rows]


# ─── strip_sensitive exposé pour les tests ────────────────────────────────────

strip_sensitive_metadata = _strip_sensitive_metadata
