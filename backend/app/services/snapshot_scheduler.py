"""Scheduler de snapshots automatiques cron + rotation GFS — LOT_14.

Push remote :
  - Le push vers S3 hardcodé du `.env` est DÉPRÉCIÉ (LOT scheduled-backups).
  - Le push se fait désormais vers les `remote_backup_connection` listées
    dans `policy.remote_destinations_to_push` (interprétée comme `list[UUID]`).
  - Pour chaque cible, on utilise `prefix_snapshots`/`remote_path_snapshots`
    de la connexion. Si non configuré, on skip ce remote avec une anomalie.
  - Best-effort : un échec sur un remote n'arrête pas les autres. Chaque
    échec génère une `system_anomaly_event` (visible dans la page Anomalies).
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from datetime import datetime
from pathlib import Path
from uuid import UUID

import asyncpg

from app.core.config import settings
from app.core.logging import logger
from app.db.repositories import backups as backups_repo
from app.db.repositories import oauth_pending_session as oauth_repo
from app.db.repositories import system_metadata as meta_repo
from app.services import backup as backup_svc
from app.services import remote_backup_connections as remote_svc
from app.services import system_anomalies as anomaly_svc
from app.services.backup_lock import get_global_backup_lock
from app.services.gfs_rotation import GFSPolicy, RotationAction, rotate
from app.services.remote_backup_providers import (
    RemoteBackupProviderError,
    get_provider,
)


async def get_policy(conn: asyncpg.Connection) -> GFSPolicy:
    raw = await meta_repo.get_value(conn, "snapshot_policy")
    if raw is None:
        return GFSPolicy()
    if isinstance(raw, str):
        import json

        raw = json.loads(raw)
    return GFSPolicy.from_dict(raw)


async def set_policy(conn: asyncpg.Connection, policy: GFSPolicy) -> None:
    await meta_repo.set_value(conn, "snapshot_policy", policy.to_dict())


class SnapshotScheduler:
    """Ne capture pas le pool : chaque acquire fetch `get_pool()` actuel.

    Garantit que le scheduler survit à `refresh_pool()` (pairing standby).
    """

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    @staticmethod
    async def _get_pool() -> asyncpg.Pool:
        from app.db.pool import get_pool

        return await get_pool()

    async def start(self) -> None:
        async with (await self._get_pool()).acquire() as conn:
            policy = await get_policy(conn)
        if policy.interval_minutes <= 0:
            logger.info("snapshot_scheduler_disabled")
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop(policy))
        logger.info("snapshot_scheduler_started", interval_minutes=policy.interval_minutes)

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._stop.set()
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def restart(self) -> None:
        await self.stop()
        await self.start()

    async def trigger(
        self, force: bool = False, skip_remote: bool = False, description: str | None = None
    ) -> backups_repo.BackupRecord:
        async with (await self._get_pool()).acquire() as conn:
            policy = await get_policy(conn)
            return await self._tick(
                conn, policy, force=force, skip_remote=skip_remote, description=description
            )

    async def _run_loop(self, policy: GFSPolicy) -> None:
        while not self._stop.is_set():
            try:
                async with (await self._get_pool()).acquire() as conn:
                    await self._tick(conn, policy)
                # Reload policy after each tick (may have been updated)
                async with (await self._get_pool()).acquire() as conn:
                    policy = await get_policy(conn)
                if policy.interval_minutes <= 0:
                    logger.info("snapshot_scheduler_disabled_during_run")
                    return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("snapshot_tick_failed", error=str(exc))

            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=policy.interval_minutes * 60,
                )
            except asyncio.TimeoutError:
                pass

    async def _tick(
        self,
        conn: asyncpg.Connection,
        policy: GFSPolicy,
        *,
        force: bool = False,
        skip_remote: bool = False,
        description: str | None = None,
    ) -> backups_repo.BackupRecord:
        t0 = time.monotonic()

        # ─── Purge des sessions OAuth expirées ───────────────────────────────
        purged = await oauth_repo.purge_expired(conn)
        if purged:
            logger.info("oauth_sessions_purged", count=purged)

        # ─── Détection de changement ─────────────────────────────────────────
        last_change = await conn.fetchval("""
            SELECT GREATEST(
              COALESCE((SELECT MAX(updated_at) FROM users), '1970-01-01'::timestamptz),
              COALESCE((SELECT MAX(updated_at) FROM wallets), '1970-01-01'::timestamptz),
              COALESCE((SELECT MAX(updated_at) FROM secrets), '1970-01-01'::timestamptz),
              COALESCE((SELECT MAX(occurred_at) FROM audit_log), '1970-01-01'::timestamptz)
            )
        """)
        last_snapshot = await conn.fetchval(
            "SELECT MAX(created_at) FROM backups_local WHERE filename LIKE 'harpocrate-snapshot-%'"
        )

        if (
            not force
            and policy.skip_if_no_change
            and last_snapshot
            and last_change <= last_snapshot
        ):
            logger.info(
                "snapshot_skipped_no_change",
                last_change=last_change.isoformat() if last_change else None,
                last_snapshot=last_snapshot.isoformat() if last_snapshot else None,
            )
            raise _NoChangeError()

        # ─── Création du snapshot ─────────────────────────────────────────────
        # Lock global partagé avec scheduled_backups_scheduler : empêche deux
        # pg_dump concurrents (CPU/IO/RAM doublés sans bénéfice + risque de
        # contention disque). Si un autre worker tient le lock, on attend.
        backup_lock = get_global_backup_lock()
        async with backup_lock:
            logger.info("snapshot_creating", trigger="manual" if description else "auto")
            timestamp = datetime.utcnow().strftime("%Y-%m-%d-%H-%M-%S")
            backup = await _create_snapshot_record(
                conn,
                timestamp=timestamp,
                tier="hourly",
                description=description or "Auto snapshot",
            )

        # ─── Push vers remote_backup_connection (best-effort sériel) ─────────
        # Push HORS du lock : l'upload réseau peut être long et n'a pas besoin
        # de bloquer un autre pg_dump éventuellement en attente.
        remote_pushes: list[dict] = []
        if not skip_remote and policy.push_remote_after_snapshot:
            remote_pushes = await self._push_snapshot_to_remotes(conn, backup=backup, policy=policy)

        # ─── Rotation ─────────────────────────────────────────────────────────
        rotation_actions = await self._apply_rotation(conn, policy)

        logger.info(
            "snapshot_tick",
            snapshot_id=str(backup.id),
            snapshot_size_bytes=backup.size_bytes,
            remote_pushes=remote_pushes,
            rotation_actions=[
                {"action": a.action, "snapshot_id": str(a.snapshot_id), "reason": a.reason}
                for a in rotation_actions
            ],
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
        return backup

    async def _push_snapshot_to_remotes(
        self,
        conn: asyncpg.Connection,
        *,
        backup: backups_repo.BackupRecord,
        policy: GFSPolicy,
    ) -> list[dict]:
        """Push le snapshot fraîchement créé vers chaque cible de la policy.

        - Parse `policy.remote_destinations_to_push` comme une liste d'UUID.
          Les valeurs non-UUID (legacy "s3" du push hardcodé .env) sont
          ignorées avec un warning au log — l'admin doit migrer en créant
          une `remote_backup_connection` S3 et en remplaçant l'entrée.
        - Pour chaque UUID : get_connection + creds + resolve_path("snapshots")
          + upload_stream. Tout échec → `system_anomaly_event` (severity=warning),
          on continue avec le remote suivant.
        - Retourne une liste de dicts pour log structuré (pas un statut DB —
          on ne stocke pas l'historique des push par snapshot pour l'instant ;
          les anomalies suffisent côté UI).
        """
        results: list[dict] = []
        file_path = Path(settings.backup_local_path) / backup.filename

        for raw_dest in policy.remote_destinations_to_push:
            try:
                remote_id = UUID(str(raw_dest))
            except (ValueError, TypeError):
                # Legacy "s3" ou autre valeur non-UUID — on signale et on skip.
                logger.warning(
                    "snapshot_remote_dest_legacy_skipped",
                    raw_destination=str(raw_dest),
                    note="migrate to remote_backup_connection UUID",
                )
                results.append(
                    {"destination": str(raw_dest), "success": False, "skipped": "legacy"}
                )
                continue

            r = await self._push_snapshot_to_one_remote(
                conn, backup=backup, remote_id=remote_id, file_path=file_path
            )
            results.append(r)
        return results

    async def _push_snapshot_to_one_remote(
        self,
        conn: asyncpg.Connection,
        *,
        backup: backups_repo.BackupRecord,
        remote_id: UUID,
        file_path: Path,
    ) -> dict:
        """Push vers UNE connexion. Génère une anomalie en cas d'échec et
        retourne un dict {destination, success, error?, bytes?} pour le log."""
        from app.api.v1.admin_backups import _stream_file_chunks  # réutilise le streamer

        remote = await remote_svc.get_connection(conn, remote_id)
        if remote is None:
            await anomaly_svc.report(
                conn,
                severity="warning",
                anomaly_type="snapshot_remote_not_found",
                source="snapshot_remote_push",
                source_ref_id=remote_id,
                message=f"Snapshot push: remote connection {remote_id} not found (deleted?).",
                metadata={"backup_id": str(backup.id), "remote_id": str(remote_id)},
            )
            return {"destination": str(remote_id), "success": False, "error": "remote_not_found"}

        creds = await remote_svc.get_decrypted_credentials(conn, remote_id)
        if creds is None:
            await anomaly_svc.report(
                conn,
                severity="warning",
                anomaly_type="snapshot_remote_no_credentials",
                source="snapshot_remote_push",
                source_ref_id=remote_id,
                message=f"Snapshot push: remote {remote.name!r} has no stored credentials.",
                metadata={"backup_id": str(backup.id), "remote_name": remote.name},
            )
            return {"destination": remote.name, "success": False, "error": "no_credentials"}

        target_path = remote_svc.resolve_path(remote.config, remote.kind, "snapshots")
        if not target_path:
            await anomaly_svc.report(
                conn,
                severity="warning",
                anomaly_type="snapshot_remote_no_snapshots_path",
                source="snapshot_remote_push",
                source_ref_id=remote_id,
                message=(
                    f"Snapshot push: remote {remote.name!r} has no 'snapshots' path "
                    f"configured. Set remote_path_snapshots / prefix_snapshots in the "
                    f"remote connection settings."
                ),
                metadata={"backup_id": str(backup.id), "remote_name": remote.name},
            )
            return {"destination": remote.name, "success": False, "error": "no_snapshots_path"}

        if not file_path.exists():
            await anomaly_svc.report(
                conn,
                severity="critical",
                anomaly_type="snapshot_local_file_missing",
                source="snapshot_remote_push",
                source_ref_id=backup.id,
                message=(
                    f"Snapshot push: local file {file_path.name!r} missing on disk. "
                    f"Cannot push to remote {remote.name!r}."
                ),
                metadata={"backup_id": str(backup.id), "filename": backup.filename},
            )
            return {"destination": remote.name, "success": False, "error": "local_file_missing"}

        provider = get_provider(remote.kind, remote.config, creds)
        try:
            bytes_pushed = await provider.upload_stream(
                target_path, backup.filename, _stream_file_chunks(file_path)
            )
        except RemoteBackupProviderError as exc:
            await anomaly_svc.report(
                conn,
                severity="warning",
                anomaly_type="snapshot_remote_push_failed",
                source="snapshot_remote_push",
                source_ref_id=remote_id,
                message=(f"Snapshot push to remote {remote.name!r} failed: {exc}"),
                metadata={
                    "backup_id": str(backup.id),
                    "remote_name": remote.name,
                    "remote_kind": remote.kind,
                    "error": str(exc),
                },
            )
            return {"destination": remote.name, "success": False, "error": str(exc)}

        return {"destination": remote.name, "success": True, "bytes": bytes_pushed}

    async def _apply_rotation(
        self, conn: asyncpg.Connection, policy: GFSPolicy
    ) -> list[RotationAction]:
        snapshots = await backups_repo.list_snapshots(conn, limit=500)
        actions = rotate(snapshots, policy)

        for action in actions:
            if action.action == "delete":
                record = await backups_repo.get_backup(conn, action.snapshot_id)
                if record:
                    file_path = Path(settings.backup_local_path) / record.filename
                    if file_path.exists():
                        file_path.unlink()
                    await backups_repo.delete_backup(conn, action.snapshot_id)
            elif action.action == "promote":
                await backups_repo.set_backup_tier(
                    conn,
                    action.snapshot_id,
                    tier=action.new_tier or "daily",
                    promoted_from_id=None,
                )

        return actions


class _NoChangeError(Exception):
    pass


async def run_scheduler_cycle_once(
    conn: asyncpg.Connection,
    policy: GFSPolicy | None = None,
) -> None:
    """Exécute un cycle scheduler complet (purge OAuth + snapshot + rotation).

    Fonction libre testable sans instancier le scheduler. Si `policy` est None,
    charge la policy depuis la DB (conn requis).
    """
    if policy is None:
        policy = await get_policy(conn)
    scheduler = SnapshotScheduler()
    with contextlib.suppress(_NoChangeError):
        await scheduler._tick(conn, policy)


async def _create_snapshot_record(
    conn: asyncpg.Connection,
    *,
    timestamp: str,
    tier: str,
    description: str | None,
) -> backups_repo.BackupRecord:
    import gzip
    import hashlib
    import json
    import tarfile
    import tempfile
    import shutil

    filename = f"harpocrate-snapshot-{timestamp}.tar.age"
    out_dir = Path(settings.backup_local_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename

    # Re-use backup service internals
    stats = await backup_svc._compute_stats(conn)
    epoch = await backup_svc.get_current_session_epoch(conn)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        proc = await asyncio.create_subprocess_exec(
            "pg_dump",
            settings.effective_db_dsn,
            "--format=plain",
            "--serializable-deferrable",
            "--no-owner",
            "--no-acl",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        dump_sql, stderr_bytes = await proc.communicate()
        if proc.returncode != 0:
            raise backup_svc.BackupError(f"pg_dump failed: {stderr_bytes.decode()}")

        dump_gz_path = tmp / "dump.sql.gz"
        with gzip.open(dump_gz_path, "wb") as gz:
            gz.write(dump_sql)

        env_path = tmp / "env-non-sensitive.json"
        env_path.write_text(json.dumps(settings.get_non_sensitive_fields(), indent=2))

        dump_sha = backup_svc._sha256_file(dump_gz_path)
        env_sha = backup_svc._sha256_file(env_path)

        manifest: dict = {
            "format_version": "1",
            "harpocrate_version": "0.1.0",
            "created_at": datetime.utcnow().isoformat() + "Z",
            "created_by": {"user_id": None, "email": "scheduler"},
            "description": description,
            "checksums": {
                "dump_sql_gz": f"sha256:{dump_sha}",
                "env_non_sensitive_json": f"sha256:{env_sha}",
            },
            "stats": stats,
            "age_recipient": settings.age_public_key,
            "schema_version": "001",
            "session_epoch_at_backup": epoch,
            "tier": tier,
        }
        manifest_path = tmp / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2))

        tar_path = tmp / "backup.tar"
        with tarfile.open(tar_path, "w") as tar:
            tar.add(manifest_path, arcname="manifest.json")
            tar.add(dump_gz_path, arcname="dump.sql.gz")
            tar.add(env_path, arcname="env-non-sensitive.json")

        tar_age_path = tmp / "backup.tar.age"
        proc2 = await asyncio.create_subprocess_exec(
            "age",
            "-r",
            settings.age_public_key,
            "-o",
            str(tar_age_path),
            str(tar_path),
            stderr=asyncio.subprocess.PIPE,
        )
        _, age_stderr = await proc2.communicate()
        if proc2.returncode != 0:
            raise backup_svc.BackupError(f"age encryption failed: {age_stderr.decode()}")

        h = hashlib.sha256()
        with open(tar_age_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        final_checksum = h.hexdigest()
        shutil.move(str(tar_age_path), str(out_path))

    size = out_path.stat().st_size
    return await backups_repo.insert_backup(
        conn,
        filename=filename,
        size_bytes=size,
        checksum_sha256=final_checksum,
        age_recipient=settings.age_public_key,
        manifest=manifest,
        description=description,
        created_by_user_id=None,
        tier=tier,
    )


# Module-level singleton managed by main.py lifespan
_scheduler: SnapshotScheduler | None = None


def get_scheduler() -> SnapshotScheduler:
    if _scheduler is None:
        raise RuntimeError("SnapshotScheduler not initialized")
    return _scheduler


def init_scheduler() -> SnapshotScheduler:
    """Init le snapshot scheduler. Ne prend plus de pool — chaque acquire
    fetch via `get_pool()` à chaque utilisation (résilience à refresh_pool)."""
    global _scheduler
    _scheduler = SnapshotScheduler()
    return _scheduler
