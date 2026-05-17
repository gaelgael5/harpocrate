"""Service métier — sauvegardes planifiées.

Responsabilités :
  - Validation des cron expressions (croniter)
  - Calcul du prochain `next_run_at`
  - Politique de "miss" (skip si retard > miss_threshold_minutes)
  - Exécution d'un schedule : créer le backup local + push optionnel vers
    une connexion remote (si `remote_id` non NULL)

Pas de boucle ici — c'est `scheduled_backups_scheduler.py` qui orchestre.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import asyncpg
import structlog
from croniter import CroniterBadCronError, croniter

from app.core.config import settings
from app.db.repositories import backups as backups_repo
from app.db.repositories import scheduled_backups as repo
from app.services import remote_backup_connections as remote_svc
from app.services.backup import create_backup
from app.services.remote_backup_providers import (
    RemoteBackupProviderError,
    get_provider,
)


logger = structlog.get_logger(__name__)

# Valeurs autorisées pour `miss_threshold_minutes`. Doit rester aligné avec
# le CHECK constraint en DB (migration 024).
ALLOWED_MISS_THRESHOLDS: tuple[int, ...] = (5, 10, 20, 30, 60)


@dataclass(frozen=True)
class CronValidation:
    valid: bool
    error: str | None = None
    next_3_occurrences: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "error": self.error,
            "next_3_occurrences": self.next_3_occurrences,
        }


@dataclass(frozen=True)
class ScheduledBackup:
    """DTO côté service pour un schedule."""

    id: UUID
    name: str
    cron_expression: str
    remote_id: UUID | None
    miss_threshold_minutes: int
    enabled: bool
    description: str | None
    next_run_at: str
    last_run_at: str | None
    last_run_status: str | None
    last_run_error: str | None
    remote_id_disconnected_at: str | None
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "name": self.name,
            "cron_expression": self.cron_expression,
            "remote_id": str(self.remote_id) if self.remote_id else None,
            "miss_threshold_minutes": self.miss_threshold_minutes,
            "enabled": self.enabled,
            "description": self.description,
            "next_run_at": self.next_run_at,
            "last_run_at": self.last_run_at,
            "last_run_status": self.last_run_status,
            "last_run_error": self.last_run_error,
            "remote_id_disconnected_at": self.remote_id_disconnected_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _row_to_dto(row: asyncpg.Record) -> ScheduledBackup:
    return ScheduledBackup(
        id=row["id"],
        name=row["name"],
        cron_expression=row["cron_expression"],
        remote_id=row["remote_id"],
        miss_threshold_minutes=row["miss_threshold_minutes"],
        enabled=row["enabled"],
        description=row["description"],
        next_run_at=row["next_run_at"].isoformat(),
        last_run_at=row["last_run_at"].isoformat() if row["last_run_at"] else None,
        last_run_status=row["last_run_status"],
        last_run_error=row["last_run_error"],
        remote_id_disconnected_at=(
            row["remote_id_disconnected_at"].isoformat()
            if row["remote_id_disconnected_at"]
            else None
        ),
        created_at=row["created_at"].isoformat(),
        updated_at=row["updated_at"].isoformat(),
    )


# ─── Validation cron ──────────────────────────────────────────────────────────


def validate_cron(cron_expression: str, *, base: datetime | None = None) -> CronValidation:
    """Valide une expression cron 5-field et retourne les 3 prochaines occurrences.

    Format attendu : `min hour day-of-month month day-of-week`

    Les datetimes retournées sont systématiquement TZ-aware (UTC). croniter peut
    renvoyer un naive datetime selon la version/input → on force l'offset UTC
    avant `.isoformat()` pour que le frontend (dayjs/Date) interprète bien la
    valeur en UTC, pas en local (sinon décalage d'affichage selon fuseau user).
    """
    expr = (cron_expression or "").strip()
    if not expr:
        return CronValidation(valid=False, error="cron_expression is required")
    try:
        base_dt = base or datetime.now(timezone.utc)
        it = croniter(expr, base_dt)
        next_3: list[str] = []
        for _ in range(3):
            next_dt = it.get_next(datetime)
            if next_dt.tzinfo is None:
                next_dt = next_dt.replace(tzinfo=timezone.utc)
            next_3.append(next_dt.isoformat())
    except (CroniterBadCronError, ValueError, KeyError) as exc:
        return CronValidation(valid=False, error=f"invalid cron expression: {exc}")
    return CronValidation(valid=True, next_3_occurrences=next_3)


def compute_next_run(cron_expression: str, *, after: datetime | None = None) -> datetime:
    """Calcule le prochain `next_run_at` strictement après `after` (ou maintenant)."""
    base_dt = after or datetime.now(timezone.utc)
    it = croniter(cron_expression, base_dt)
    next_dt = it.get_next(datetime)
    # croniter retourne parfois un naive datetime si l'input est naive — on force tz-aware
    if next_dt.tzinfo is None:
        next_dt = next_dt.replace(tzinfo=timezone.utc)
    return next_dt


# ─── CRUD avec calcul de next_run ─────────────────────────────────────────────


async def list_schedules(conn: asyncpg.Connection) -> list[ScheduledBackup]:
    rows = await repo.list_all(conn)
    return [_row_to_dto(r) for r in rows]


async def get_schedule(
    conn: asyncpg.Connection, schedule_id: UUID
) -> ScheduledBackup | None:
    row = await repo.get_by_id(conn, schedule_id)
    return _row_to_dto(row) if row else None


async def create_schedule(
    conn: asyncpg.Connection,
    *,
    name: str,
    cron_expression: str,
    remote_id: UUID | None,
    miss_threshold_minutes: int,
    description: str | None,
    enabled: bool = True,
) -> UUID:
    validation = validate_cron(cron_expression)
    if not validation.valid:
        raise ValueError(validation.error or "invalid cron expression")
    if miss_threshold_minutes not in ALLOWED_MISS_THRESHOLDS:
        raise ValueError(
            f"miss_threshold_minutes must be one of {ALLOWED_MISS_THRESHOLDS}"
        )
    next_run = compute_next_run(cron_expression)
    return await repo.insert(
        conn,
        name=name,
        cron_expression=cron_expression,
        remote_id=remote_id,
        miss_threshold_minutes=miss_threshold_minutes,
        description=description,
        next_run_at=next_run,
        enabled=enabled,
    )


async def update_schedule(
    conn: asyncpg.Connection,
    *,
    schedule_id: UUID,
    name: str | None = None,
    cron_expression: str | None = None,
    remote_id: UUID | None = None,
    set_remote_id: bool = False,
    miss_threshold_minutes: int | None = None,
    description: str | None = None,
    set_description: bool = False,
    enabled: bool | None = None,
) -> int:
    """Met à jour un schedule. Si `cron_expression` change, on recalcule
    `next_run_at`. La validation est faite en amont.
    """
    next_run: datetime | None = None
    if cron_expression is not None:
        validation = validate_cron(cron_expression)
        if not validation.valid:
            raise ValueError(validation.error or "invalid cron expression")
        next_run = compute_next_run(cron_expression)
    if (
        miss_threshold_minutes is not None
        and miss_threshold_minutes not in ALLOWED_MISS_THRESHOLDS
    ):
        raise ValueError(
            f"miss_threshold_minutes must be one of {ALLOWED_MISS_THRESHOLDS}"
        )
    return await repo.update(
        conn,
        schedule_id=schedule_id,
        name=name,
        cron_expression=cron_expression,
        remote_id=remote_id,
        set_remote_id=set_remote_id,
        miss_threshold_minutes=miss_threshold_minutes,
        description=description,
        set_description=set_description,
        enabled=enabled,
        next_run_at=next_run,
    )


async def delete_schedule(conn: asyncpg.Connection, schedule_id: UUID) -> int:
    return await repo.delete(conn, schedule_id)


# ─── Exécution d'un schedule ──────────────────────────────────────────────────


@dataclass
class RunResult:
    status: Literal["ok", "failed", "skipped"]
    error: str | None = None
    backup_id: UUID | None = None
    bytes_pushed: int | None = None


async def _last_db_change(conn: asyncpg.Connection) -> datetime:
    """Retourne l'horodatage du dernier changement métier détectable.

    Couvre les tables où `updated_at`/`occurred_at` est touché à chaque mutation
    significative pour le contenu d'un backup. Réutilisé du snapshot scheduler
    pour cohérence du critère "rien n'a bougé".
    """
    return await conn.fetchval(
        """
        SELECT GREATEST(
          COALESCE((SELECT MAX(updated_at)  FROM users),     '1970-01-01'::timestamptz),
          COALESCE((SELECT MAX(updated_at)  FROM wallets),   '1970-01-01'::timestamptz),
          COALESCE((SELECT MAX(updated_at)  FROM secrets),   '1970-01-01'::timestamptz),
          COALESCE((SELECT MAX(occurred_at) FROM audit_log), '1970-01-01'::timestamptz)
        )
        """
    )


async def _last_backup_completed_at(conn: asyncpg.Connection) -> datetime | None:
    """Heure de fin du dernier backup local (snapshot ou full, peu importe).

    `created_at` côté `backups_local` est stamp à l'INSERT, après pg_dump et
    chiffrement age — c'est bien l'heure de FIN du backup.
    """
    return await conn.fetchval(
        "SELECT MAX(created_at) FROM backups_local"
    )


async def run_schedule(
    conn: asyncpg.Connection,
    schedule: ScheduledBackup,
) -> RunResult:
    """Exécute un schedule : crée un backup local, puis push si remote_id non NULL.

    Skip-if-no-change : si le dernier backup local (n'importe lequel) est plus
    récent que le dernier changement métier, on saute — pas la peine d'écrire
    sur disque l'équivalent bit-à-bit du backup précédent. Le statut est
    'skipped' avec un message explicite, et `next_run_at` est avancé pour ne
    pas reboucler.

    Retourne un RunResult — n'écrit pas en DB le résultat (le caller s'en
    charge via `repo.mark_run`, ce qui permet aussi de calculer le prochain
    `next_run_at` au même endroit).
    """
    # 0) Skip-if-no-change : compare dernier change vs dernier backup terminé
    last_backup_end = await _last_backup_completed_at(conn)
    if last_backup_end is not None:
        last_change = await _last_db_change(conn)
        if last_change <= last_backup_end:
            return RunResult(
                status="skipped",
                error=(
                    f"no changes since last backup completed at "
                    f"{last_backup_end.isoformat()}"
                ),
            )

    # 1) Création du backup local
    try:
        record = await create_backup(
            conn,
            description=f"Scheduled: {schedule.name}",
            created_by_user_id=None,
            created_by_email="scheduler@harpocrate",
        )
    except Exception as exc:  # noqa: BLE001 — on remonte tout, le scheduler log
        return RunResult(status="failed", error=f"backup creation failed: {exc}")

    # 2) Pas de push si schedule local-only
    if schedule.remote_id is None:
        return RunResult(status="ok", backup_id=record.id)

    # 3) Push vers la connexion remote
    remote = await remote_svc.get_connection(conn, schedule.remote_id)
    if remote is None:
        return RunResult(
            status="failed",
            backup_id=record.id,
            error="remote connection not found (deleted between schedule creation and run)",
        )
    creds = await remote_svc.get_decrypted_credentials(conn, schedule.remote_id)
    if creds is None:
        return RunResult(
            status="failed",
            backup_id=record.id,
            error="remote connection has no stored credentials",
        )
    target_path = remote_svc.resolve_path(remote.config, remote.kind, "full")
    if not target_path:
        return RunResult(
            status="failed",
            backup_id=record.id,
            error=f"remote {remote.name!r} has no 'full' path configured",
        )

    file_path = Path(settings.backup_local_path) / record.filename
    if not file_path.exists():
        return RunResult(
            status="failed",
            backup_id=record.id,
            error=f"local backup file missing: {file_path.name}",
        )

    provider = get_provider(remote.kind, remote.config, creds)
    try:
        bytes_pushed = await provider.upload_stream(
            target_path, record.filename, _stream_file_chunks(file_path)
        )
    except RemoteBackupProviderError as exc:
        return RunResult(
            status="failed",
            backup_id=record.id,
            error=f"remote push failed: {exc}",
        )
    return RunResult(status="ok", backup_id=record.id, bytes_pushed=bytes_pushed)


_PUSH_CHUNK_SIZE = 64 * 1024


async def _stream_file_chunks(path: Path) -> AsyncIterator[bytes]:
    """Yield le contenu de `path` par blocs (lit en thread pool pour ne pas
    bloquer la boucle asyncio)."""
    f = await asyncio.to_thread(path.open, "rb")
    try:
        while True:
            chunk = await asyncio.to_thread(f.read, _PUSH_CHUNK_SIZE)
            if not chunk:
                return
            yield chunk
    finally:
        await asyncio.to_thread(f.close)


# ─── Politique de miss ────────────────────────────────────────────────────────


def is_miss(
    schedule: ScheduledBackup,
    *,
    now: datetime | None = None,
) -> bool:
    """True si le schedule a manqué son créneau au-delà de sa tolérance.

    Utilisé au démarrage du scheduler : pour un schedule due trop ancien,
    on saute (skip) et on recale `next_run_at` au prochain créneau futur.
    """
    now_dt = now or datetime.now(timezone.utc)
    next_run = datetime.fromisoformat(schedule.next_run_at)
    if next_run.tzinfo is None:
        next_run = next_run.replace(tzinfo=timezone.utc)
    return next_run < now_dt - timedelta(minutes=schedule.miss_threshold_minutes)
