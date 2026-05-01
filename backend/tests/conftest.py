"""Shared pytest fixtures."""
from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def patch_asyncpg_create_pool() -> Iterator[None]:
    """Stub asyncpg.create_pool so the FastAPI lifespan doesn't try a real DB."""
    fake_pool = AsyncMock()
    with patch("asyncpg.create_pool", return_value=fake_pool):
        yield
