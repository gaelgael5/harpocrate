"""Seeding idempotent des types de secrets système au démarrage."""
from __future__ import annotations

import json
from pathlib import Path

import asyncpg

from app.core.logging import logger
from app.db.repositories import secret_types as repo

# backend/types/ — copié dans /app/types/ dans l'image Docker
_TYPES_DIR = Path(__file__).parent.parent.parent / "types"


async def seed_system_types(conn: asyncpg.Connection) -> None:
    if not _TYPES_DIR.exists():
        logger.warning("seed_types_dir_missing", path=str(_TYPES_DIR))
        return

    for type_dir in sorted(_TYPES_DIR.iterdir()):
        if not type_dir.is_dir():
            continue

        meta_file = type_dir / "meta.json"
        data_file = type_dir / "schema_data.json"
        ui_file = type_dir / "schema_ui.json"

        if not (meta_file.exists() and data_file.exists()):
            continue

        meta = json.loads(meta_file.read_text())
        schema_data = json.loads(data_file.read_text())
        schema_ui = json.loads(ui_file.read_text()) if ui_file.exists() else {}

        type_name: str = meta["type"]
        sous_type: str = meta.get("sous_type", type_dir.name)
        label: str | None = schema_data.get("title")
        description: str | None = schema_data.get("description")

        exists = await conn.fetchval(
            "SELECT 1 FROM secret_types WHERE type=$1 AND sous_type=$2",
            type_name, sous_type,
        )
        if exists:
            continue

        await repo.insert_type_with_v1(
            conn,
            type_=type_name,
            sous_type=sous_type,
            label=label,
            description=description,
            schema_data=schema_data,
            schema_ui=schema_ui,
            notes="Système — chargé au démarrage",
            creator_id=None,
            is_system=True,
        )
        logger.info("system_type_seeded", type=type_name, sous_type=sous_type, label=label)
