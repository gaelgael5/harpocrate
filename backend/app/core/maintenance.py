"""État du mode maintenance en RAM (singleton) — LOT_12A."""
from __future__ import annotations

import datetime
from dataclasses import dataclass


@dataclass
class MaintenanceState:
    """Singleton mutable représentant l'état du mode maintenance."""

    active: bool = False
    reason: str | None = None
    started_at: datetime.datetime | None = None
    effective_at: datetime.datetime | None = None
    estimated_end_at: datetime.datetime | None = None


maintenance_state = MaintenanceState()
