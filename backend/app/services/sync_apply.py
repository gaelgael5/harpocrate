"""Application des transactions reçues d'un peer (LOT_21B).

Garantie clé : la transaction est appliquée dans une transaction Postgres
avec `SET LOCAL harpocrate.is_replication = true` — les triggers savent
que c'est une réplication et ne réémettent PAS la transaction (évite la boucle).

L'ack vide est inséré dans `sync_log` dans la même transaction → atomicité.

Whitelist d'entités : seules les tables explicitement supportées sont
appliquées. Toute autre entité est loggée + ignorée plutôt que rejetée
(évite de bloquer le pipeline si un nouveau type d'entité est diffusé
par une instance plus à jour).
"""

from __future__ import annotations

import json
from typing import Any

import asyncpg

from app.core.logging import logger
from app.db.repositories import sync_replication as sync_repo

# Whitelist des entités répliquées. Doit matcher les triggers SQL (migration 013).
_REPLICATED_ENTITIES: frozenset[str] = frozenset({
    "secrets",
    "wallets",
    "users",
    "wallet_grants",
})


async def apply_transaction_in_tx(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    instance_id: str,
    peer_emitter: str,
    peer_seq: int,
    entity_type: str,
    operation: str,
    payload: dict[str, Any],
) -> None:
    """Applique une transaction reçue d'un peer (atomique, idempotente)."""
    if entity_type not in _REPLICATED_ENTITIES:
        logger.warning(
            "sync_apply_unknown_entity_type",
            entity_type=entity_type,
            peer=peer_emitter,
            seq=peer_seq,
        )
        return

    async with conn.transaction():
        # Marqueur session pour empêcher les triggers de réémettre.
        await conn.execute("SET LOCAL harpocrate.is_replication = 'true'")
        # Empêche aussi le trigger de noter notre instance comme emitter.
        await conn.execute(f"SET LOCAL harpocrate.instance_id = '{instance_id}'")

        if operation == "delete":
            await _apply_delete(conn, entity_type, payload)
        elif operation == "upsert":
            await _apply_upsert(conn, entity_type, payload)
        else:
            logger.warning(
                "sync_apply_unknown_operation",
                operation=operation,
                entity_type=entity_type,
            )
            return

        # Ack vide dans sync_log + maj de l'état.
        await sync_repo.insert_replication_ack(
            conn,
            emitter_id=instance_id,
            source_emitter=peer_emitter,
            source_seq=peer_seq,
        )
        await sync_repo.upsert_applied(
            conn, peer=peer_emitter, last_applied_seq=peer_seq
        )


async def _apply_delete(
    conn: asyncpg.Connection[asyncpg.Record],
    entity_type: str,
    payload: dict[str, Any],
) -> None:
    entity_id = payload.get("id")
    if not entity_id:
        logger.warning("sync_apply_delete_missing_id", entity_type=entity_type)
        return
    # entity_type est dans la whitelist → safe pour interpolation
    await conn.execute(
        f"DELETE FROM {entity_type} WHERE id = $1",
        entity_id,
    )


async def _apply_upsert(
    conn: asyncpg.Connection[asyncpg.Record],
    entity_type: str,
    payload: dict[str, Any],
) -> None:
    """UPSERT générique : DELETE puis INSERT du record JSON.

    Atomique car appelé dans une transaction parente (`apply_transaction_in_tx`).
    `jsonb_populate_record` ignore les clés JSON inconnues du schéma — donc
    si une nouvelle colonne est ajoutée sur l'instance émettrice mais pas
    encore sur la nôtre, on récupère ce qu'on peut sans planter.
    """
    entity_id = payload.get("id")
    if not entity_id:
        logger.warning("sync_apply_upsert_missing_id", entity_type=entity_type)
        return
    # entity_type whitelisté
    await conn.execute(
        f"DELETE FROM {entity_type} WHERE id = $1",
        entity_id,
    )
    await conn.execute(
        f"""
        INSERT INTO {entity_type}
        SELECT * FROM jsonb_populate_record(NULL::{entity_type}, $1::jsonb)
        """,
        json.dumps(payload),
    )
