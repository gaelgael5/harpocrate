"""Scheduler de snapshots automatiques cron + rotation GFS — LOT_14."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime
from pathlib import Path
from uuid import UUID

import asyncpg

from app.core.config import settings
from app.core.logging import logger
from app.db.repositories import backups as backups_repo
from app.db.repositories import system_metadata as meta_repo
from app.services import backup as backup_svc
from app.services import backup_s3 as s3_svc
from app.services.gfs_rotation import GFSPolicy, RotationAction, rotate


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
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        async with self._pool.acquire() as conn:
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

    async def trigger(self, force: bool = False, skip_remote: bool = False, description: str | None = None) -> backups_repo.BackupRecord:
        async with self._pool.acquire() as conn:
            policy = await get_policy(conn)
            return await self._tick(conn, policy, force=force, skip_remote=skip_remote, description=description)

    async def _run_loop(self, policy: GFSPolicy) -> None:
        while not self._stop.is_set():
            try:
                async with self._pool.acquire() as conn:
                    await self._tick(conn, policy)
                # Reload policy after each tick (may have been updated)
                async with self._pool.acquire() as conn:
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

        if not force and policy.skip_if_no_change and last_snapshot and last_change <= last_snapshot:
            logger.info(
                "snapshot_skipped_no_change",
                last_change=last_change.isoformat() if last_change else None,
                last_snapshot=last_snapshot.isoformat() if last_snapshot else None,
            )
            raise _NoChangeError()

        # ─── Création du snapshot ─────────────────────────────────────────────
        logger.info("snapshot_creating", trigger="manual" if description else "auto")
        timestamp = datetime.utcnow().strftime("%Y-%m-%d-%H-%M-%S")
        backup = await _create_snapshot_record(
            conn,
            timestamp=timestamp,
            tier="hourly",
            description=description or "Auto snapshot",
        )

        remote_pushes: list[dict] = []
        if not skip_remote and policy.push_remote_after_snapshot and settings.s3_configured:
            t_push = time.monotonic()
            try:
                s3_key = await s3_svc.push_backup_to_s3(str(backup.id), conn)
                remote_pushes.append({"destination": "s3", "success": True, "s3_key": s3_key})
            except Exception as exc:
                remote_pushes.append({"destination": "s3", "success": False, "error": str(exc)})
                logger.error("snapshot_remote_push_failed", error=str(exc))
            logger.info("snapshot_remote_push_done", duration_ms=int((time.monotonic() - t_push) * 1000))

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
            "pg_dump", settings.db_dsn,
            "--format=plain", "--serializable-deferrable", "--no-owner", "--no-acl",
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
            "age", "-r", settings.age_public_key,
            "-o", str(tar_age_path),
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


def init_scheduler(pool: asyncpg.Pool) -> SnapshotScheduler:
    global _scheduler
    _scheduler = SnapshotScheduler(pool)
    return _scheduler
