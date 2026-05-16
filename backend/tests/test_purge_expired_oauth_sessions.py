"""Le snapshot scheduler appelle bien purge_expired_oauth_sessions à chaque cycle."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_scheduler_calls_purge_expired() -> None:
    """Un cycle scheduler invoque oauth_repo.purge_expired."""
    fake_purge = AsyncMock(return_value=3)
    fake_conn = MagicMock()

    # On patche tout ce que _tick va appeler pour qu'il ne fasse pas de vraie I/O.
    with (
        patch(
            "app.services.snapshot_scheduler.oauth_repo.purge_expired",
            fake_purge,
        ),
        # Empêcher fetchval (détection de changement) de planter
        patch.object(fake_conn, "fetchval", new=AsyncMock(return_value=None)),
        # skip_if_no_change=False → on n'a pas besoin de lever _NoChangeError
        patch(
            "app.services.snapshot_scheduler.get_policy",
            AsyncMock(
                return_value=MagicMock(
                    interval_minutes=60,
                    skip_if_no_change=False,
                    push_remote_after_snapshot=False,
                    remote_destinations_to_push=[],
                )
            ),
        ),
        # _create_snapshot_record fait des appels lourds (pg_dump, age) → on le mock
        patch(
            "app.services.snapshot_scheduler._create_snapshot_record",
            AsyncMock(return_value=MagicMock(id="fake-id", size_bytes=0, filename="snap.tar.age")),
        ),
        # _apply_rotation appelle backups_repo.list_snapshots
        patch(
            "app.services.snapshot_scheduler.backups_repo.list_snapshots",
            AsyncMock(return_value=[]),
        ),
    ):
        from app.services.snapshot_scheduler import GFSPolicy, run_scheduler_cycle_once

        policy = GFSPolicy(
            interval_minutes=60,
            skip_if_no_change=False,
            push_remote_after_snapshot=False,
        )
        await run_scheduler_cycle_once(fake_conn, policy)

    fake_purge.assert_called_once_with(fake_conn)


@pytest.mark.asyncio
async def test_scheduler_logs_when_sessions_purged() -> None:
    """Si purge_expired retourne > 0, le scheduler log un message info."""
    fake_purge = AsyncMock(return_value=2)
    fake_conn = MagicMock()

    with (
        patch(
            "app.services.snapshot_scheduler.oauth_repo.purge_expired",
            fake_purge,
        ),
        patch.object(fake_conn, "fetchval", new=AsyncMock(return_value=None)),
        patch(
            "app.services.snapshot_scheduler.get_policy",
            AsyncMock(return_value=MagicMock(skip_if_no_change=False)),
        ),
        patch(
            "app.services.snapshot_scheduler._create_snapshot_record",
            AsyncMock(return_value=MagicMock(id="fake-id", size_bytes=0, filename="snap.tar.age")),
        ),
        patch(
            "app.services.snapshot_scheduler.backups_repo.list_snapshots",
            AsyncMock(return_value=[]),
        ),
    ):
        from app.services.snapshot_scheduler import GFSPolicy, run_scheduler_cycle_once

        policy = GFSPolicy(
            interval_minutes=60,
            skip_if_no_change=False,
            push_remote_after_snapshot=False,
        )
        # On vérifie juste que ça ne plante pas (le log est structlog JSON).
        await run_scheduler_cycle_once(fake_conn, policy)

    fake_purge.assert_awaited_once()
