"""Service de backup/restore avec chiffrement age — LOT_12A."""
from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import shutil
import tarfile
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID

import asyncpg
from fastapi import HTTPException, status

from app.core.config import settings
from app.db.repositories import backups as backups_repo
from app.db.repositories import system_metadata as meta_repo


class BackupError(Exception):
    pass


@dataclass
class VerifyResult:
    valid: bool
    manifest: dict
    checksums_match: bool
    dump_sql_lines: int


@dataclass
class RestoreResult:
    success: bool
    restored_from_backup_id: UUID
    session_epoch_new: int
    env_restore_file_path: str


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


async def _run(cmd: list[str], stdin: bytes | None = None) -> tuple[int, bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE if stdin is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(input=stdin)
    return proc.returncode or 0, stdout, stderr


def _backup_dir() -> Path:
    path = Path(settings.backup_local_path)
    path.mkdir(parents=True, exist_ok=True)
    return path


async def _compute_stats(conn: asyncpg.Connection) -> dict:
    row = await conn.fetchrow("""
        SELECT
            (SELECT count(*) FROM users) AS users_count,
            (SELECT count(*) FROM wallets) AS wallets_count,
            (SELECT count(*) FROM secrets) AS secrets_count,
            (SELECT count(*) FROM api_keys) AS api_keys_count,
            (SELECT count(*) FROM audit_log) AS audit_log_entries_count
    """)
    assert row is not None
    return {k: int(row[k]) for k in row.keys()}


async def get_current_session_epoch(conn: asyncpg.Connection) -> int:
    row = await conn.fetchrow("SELECT epoch FROM server_session_epoch LIMIT 1")
    if row is None:
        return 0
    return int(row["epoch"])


async def rotate_session_epoch(conn: asyncpg.Connection, reason: str) -> int:
    """Incrémente l'epoch et notifie le cluster (LOT_21A).

    Le NOTIFY est émis dans la même transaction que le UPDATE — Postgres ne
    livre les notifications qu'au COMMIT, donc tout rollback annule la notif.
    """
    row = await conn.fetchrow(
        """
        UPDATE server_session_epoch
        SET epoch = epoch + 1,
            rotated_reason = $1,
            rotated_at = NOW()
        RETURNING epoch
        """,
        reason,
    )
    assert row is not None
    new_epoch = int(row["epoch"])
    # Import paresseux : évite import circulaire si cluster_notify importe backup.
    from app.services.cluster_notify import notify_epoch_changed
    await notify_epoch_changed(conn, new_epoch)
    return new_epoch


async def create_backup(
    conn: asyncpg.Connection,
    *,
    description: str | None,
    created_by_user_id: UUID | None,
    created_by_email: str,
) -> backups_repo.BackupRecord:
    """Crée un backup chiffré avec age et l'enregistre en DB."""
    if not settings.age_public_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "age_key_not_configured", "message": "HARPOCRATE_AGE_PUBLIC_KEY not set"},
        )

    timestamp = datetime.utcnow().strftime("%Y-%m-%d-%H-%M-%S")
    filename = f"harpocrate-backup-{timestamp}.tar.age"
    out_path = _backup_dir() / filename

    stats = await _compute_stats(conn)
    epoch = await get_current_session_epoch(conn)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # pg_dump → stdout
        proc = await asyncio.create_subprocess_exec(
            "pg_dump", settings.db_dsn,
            "--format=plain", "--serializable-deferrable", "--no-owner", "--no-acl",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        dump_sql, stderr_bytes = await proc.communicate()
        if proc.returncode != 0:
            raise BackupError(f"pg_dump failed: {stderr_bytes.decode()}")

        # Gzip
        dump_gz_path = tmp / "dump.sql.gz"
        with gzip.open(dump_gz_path, "wb") as gz:
            gz.write(dump_sql)

        # Env non-sensible
        env_path = tmp / "env-non-sensitive.json"
        env_path.write_text(json.dumps(settings.get_non_sensitive_fields(), indent=2))

        # Checksums
        dump_sha = _sha256_file(dump_gz_path)
        env_sha = _sha256_file(env_path)

        # Manifest
        manifest: dict = {
            "format_version": "1",
            "harpocrate_version": "0.1.0",
            "created_at": datetime.utcnow().isoformat() + "Z",
            "created_by": {"user_id": str(created_by_user_id), "email": created_by_email},
            "description": description,
            "checksums": {
                "dump_sql_gz": f"sha256:{dump_sha}",
                "env_non_sensitive_json": f"sha256:{env_sha}",
            },
            "stats": stats,
            "age_recipient": settings.age_public_key,
            "schema_version": "001",
            "session_epoch_at_backup": epoch,
        }
        manifest_path = tmp / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2))

        # Tar
        tar_path = tmp / "backup.tar"
        with tarfile.open(tar_path, "w") as tar:
            tar.add(manifest_path, arcname="manifest.json")
            tar.add(dump_gz_path, arcname="dump.sql.gz")
            tar.add(env_path, arcname="env-non-sensitive.json")

        # Age encrypt
        tar_age_path = tmp / "backup.tar.age"
        proc2 = await asyncio.create_subprocess_exec(
            "age", "-r", settings.age_public_key,
            "-o", str(tar_age_path),
            str(tar_path),
            stderr=asyncio.subprocess.PIPE,
        )
        _, age_stderr = await proc2.communicate()
        if proc2.returncode != 0:
            raise BackupError(f"age encryption failed: {age_stderr.decode()}")

        final_checksum = _sha256_file(tar_age_path)
        shutil.move(str(tar_age_path), str(out_path))

    size = out_path.stat().st_size
    await meta_repo.set_value(conn, "last_backup_at", datetime.utcnow().isoformat() + "Z")
    return await backups_repo.insert_backup(
        conn,
        filename=filename,
        size_bytes=size,
        checksum_sha256=final_checksum,
        age_recipient=settings.age_public_key,
        manifest=manifest,
        description=description,
        created_by_user_id=created_by_user_id,
    )


async def verify_backup(backup_id: UUID, age_private_key: str, conn: asyncpg.Connection) -> VerifyResult:
    """Vérifie l'intégrité du backup en le déchiffrant (sans restaurer)."""
    record = await backups_repo.get_backup(conn, backup_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "backup_not_found", "message": "Backup not found"},
        )

    backup_path = _backup_dir() / record.filename
    if not backup_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "backup_file_missing", "message": "Backup file not found on disk"},
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        tar_path = tmp / "backup.tar"

        proc = await asyncio.create_subprocess_exec(
            "age", "-d", "-i", "-",
            "-o", str(tar_path),
            str(backup_path),
            stdin=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate(input=age_private_key.encode())
        if proc.returncode != 0:
            return VerifyResult(valid=False, manifest={}, checksums_match=False, dump_sql_lines=0)

        extracted = tmp / "extracted"
        with tarfile.open(tar_path) as tar:
            tar.extractall(extracted)

        manifest_data = json.loads((extracted / "manifest.json").read_text())

        checksums_ok = True
        checksum_map = {
            "dump_sql_gz": "dump.sql.gz",
            "env_non_sensitive_json": "env-non-sensitive.json",
        }
        for key, expected in manifest_data.get("checksums", {}).items():
            fname = checksum_map.get(key, key)
            fpath = extracted / fname
            if fpath.exists():
                actual = f"sha256:{_sha256_file(fpath)}"
                if actual != expected:
                    checksums_ok = False
            else:
                checksums_ok = False

        dump_lines = 0
        dump_gz = extracted / "dump.sql.gz"
        if dump_gz.exists():
            with gzip.open(dump_gz, "rt", errors="replace") as f:
                dump_lines = sum(1 for _ in f)

        return VerifyResult(
            valid=True,
            manifest=manifest_data,
            checksums_match=checksums_ok,
            dump_sql_lines=dump_lines,
        )


async def restore_backup(
    backup_id: UUID,
    age_private_key: str,
    conn: asyncpg.Connection,
) -> RestoreResult:
    """Restaure la base depuis un backup (DROP SCHEMA + replay). DESTRUCTIF."""
    record = await backups_repo.get_backup(conn, backup_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "backup_not_found", "message": "Backup not found"},
        )

    backup_path = _backup_dir() / record.filename
    if not backup_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "backup_file_missing", "message": "Backup file not found on disk"},
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        tar_path = tmp / "backup.tar"

        proc = await asyncio.create_subprocess_exec(
            "age", "-d", "-i", "-",
            "-o", str(tar_path),
            str(backup_path),
            stdin=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate(input=age_private_key.encode())
        if proc.returncode != 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "decryption_failed", "message": "age decryption failed — wrong key?"},
            )

        extracted = tmp / "extracted"
        with tarfile.open(tar_path) as tar:
            tar.extractall(extracted)

        checksum_map = {
            "dump_sql_gz": "dump.sql.gz",
            "env_non_sensitive_json": "env-non-sensitive.json",
        }
        manifest_data = json.loads((extracted / "manifest.json").read_text())
        for key, expected in manifest_data.get("checksums", {}).items():
            fname = checksum_map.get(key, key)
            fpath = extracted / fname
            if not fpath.exists():
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={"error": "backup_incomplete", "message": f"Missing {fname} in archive"},
                )
            actual = f"sha256:{_sha256_file(fpath)}"
            if actual != expected:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={"error": "checksum_mismatch", "message": f"Checksum mismatch on {fname}"},
                )

        rc, _, drop_stderr = await _run([
            "psql", settings.db_dsn,
            "-c", "DROP SCHEMA public CASCADE; CREATE SCHEMA public;",
        ])
        if rc != 0:
            raise BackupError(f"DROP SCHEMA failed: {drop_stderr.decode()}")

        dump_gz = extracted / "dump.sql.gz"
        with gzip.open(dump_gz, "rb") as gz:
            dump_bytes = gz.read()

        proc2 = await asyncio.create_subprocess_exec(
            "psql", settings.db_dsn,
            stdin=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr2 = await proc2.communicate(input=dump_bytes)
        if proc2.returncode != 0:
            raise BackupError(f"psql replay failed: {stderr2.decode()}")

        new_epoch = await rotate_session_epoch(conn, reason=f"post_restore_backup_{backup_id}")

        env_data = json.loads((extracted / "env-non-sensitive.json").read_text())
        backup_dir = _backup_dir()
        env_restore_path = backup_dir.parent / f".env.restore.{int(time.time())}"
        with open(env_restore_path, "w") as f:
            for k, v in env_data.items():
                f.write(f"{k}={v}\n")

        await meta_repo.set_value(conn, "last_restored_at", datetime.utcnow().isoformat() + "Z")

        return RestoreResult(
            success=True,
            restored_from_backup_id=backup_id,
            session_epoch_new=new_epoch,
            env_restore_file_path=str(env_restore_path),
        )
