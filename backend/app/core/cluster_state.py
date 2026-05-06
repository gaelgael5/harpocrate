"""État cluster partagé en RAM (LOT_21A).

Chaque nœud Harpocrate maintient un `ClusterState` synchronisé depuis Postgres
via LISTEN/NOTIFY (réactif) + refresh périodique 5s (filet de sécurité).

Invariants (LOT 19) :
- I-3 `session_epoch` est la source de vérité globale ; un nœud avec
  epoch RAM < epoch DB doit refuser de servir (middleware 503).
- I-5 maintenance globale : si `maintenance_active=TRUE` en DB, tous
  les nœuds 503.

Cet état NE remplace PAS la DB — il en est le miroir local. La DB reste
la source de vérité unique (I-4).
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from app.core.config import settings


@dataclass
class ClusterState:
    """État partagé en RAM, miroir local de Postgres."""

    session_epoch: int = 0
    maintenance_active: bool = False
    maintenance_reason: str | None = None
    maintenance_started_at: datetime.datetime | None = None
    maintenance_effective_at: datetime.datetime | None = None
    maintenance_estimated_end_at: datetime.datetime | None = None

    # Méta — auto-renseignée à chaque refresh
    last_synced_at: datetime.datetime | None = None
    instance_id: str = field(default_factory=lambda: settings.instance_id)

    def is_epoch_coherent(self, db_epoch: int) -> bool:
        """Vrai si l'epoch RAM est >= epoch DB.

        Un nœud avec epoch RAM < epoch DB est en retard et doit refuser
        de servir (sessions issues d'un epoch périmé encore vivantes).
        """
        return self.session_epoch >= db_epoch

    def update_from_db(
        self,
        *,
        epoch: int,
        maintenance_active: bool,
        maintenance_reason: str | None,
        maintenance_started_at: datetime.datetime | None,
        maintenance_effective_at: datetime.datetime | None,
        maintenance_estimated_end_at: datetime.datetime | None,
    ) -> list[str]:
        """Applique l'état lu en DB et retourne la liste des changements détectés."""
        changes: list[str] = []

        if self.session_epoch != epoch:
            self.session_epoch = epoch
            changes.append("epoch")

        if self.maintenance_active != maintenance_active:
            changes.append("maintenance")
        # On synchronise les attributs de maintenance qu'il y ait eu transition
        # ou simple update (changement de reason/estimated_end sans toggle).
        self.maintenance_active = maintenance_active
        self.maintenance_reason = maintenance_reason
        self.maintenance_started_at = maintenance_started_at
        self.maintenance_effective_at = maintenance_effective_at
        self.maintenance_estimated_end_at = maintenance_estimated_end_at

        self.last_synced_at = datetime.datetime.now(datetime.UTC)
        return changes


# Singleton mutable accédé partout dans l'app.
cluster_state = ClusterState()
