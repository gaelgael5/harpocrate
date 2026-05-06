"""Stratégies de réplication (LOT_20).

Abstraction `ReplicationStrategy` qui permet de basculer entre :
- `none` : Postgres standalone (par défaut MVP)
- `patroni` : Postgres répliqué via Patroni + etcd

Les stratégies futures (`harpocrate_sync`, `s3_wal`) sont déclarées dans
l'enum mais lèvent `NotImplementedError` à l'instanciation pour le MVP.

Cette abstraction est consommée par les endpoints admin pour exposer un
état lisible côté UI sans coupler la logique applicative à un backend
de réplication particulier.
"""

from __future__ import annotations

import abc
from enum import StrEnum
from typing import Any

import httpx


class ReplicationStrategyType(StrEnum):
    NONE = "none"
    PATRONI = "patroni"
    HARPOCRATE_SYNC = "harpocrate_sync"
    S3_WAL = "s3_wal"


class ReplicationStrategy(abc.ABC):
    """Contrat commun à toutes les stratégies."""

    type: ReplicationStrategyType

    @abc.abstractmethod
    async def get_status(self) -> dict[str, Any]:
        """État global : type, status, primary, replicas (selon stratégie)."""
        ...

    async def get_replicas(self) -> list[dict[str, Any]]:
        """Liste des replicas connus. Vide pour les stratégies sans replicas."""
        status = await self.get_status()
        replicas = status.get("replicas", [])
        return list(replicas) if isinstance(replicas, list) else []


class NoneStrategy(ReplicationStrategy):
    """Postgres standalone — pas de réplication."""

    type = ReplicationStrategyType.NONE

    async def get_status(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "status": "ok",
            "primary": None,
            "replicas": [],
        }


class PatroniStrategy(ReplicationStrategy):
    """Patroni + etcd — interroge l'API REST Patroni de chaque nœud."""

    type = ReplicationStrategyType.PATRONI

    def __init__(
        self,
        config: dict[str, Any],
        *,
        http_timeout: float = 2.0,
    ) -> None:
        urls = config.get("patroni_api_urls") or []
        if not isinstance(urls, list) or not all(isinstance(u, str) for u in urls):
            raise ValueError("patroni_api_urls must be a list[str]")
        if not urls:
            raise ValueError("patroni config requires at least one patroni_api_urls entry")
        self._urls: list[str] = urls
        self._timeout = http_timeout
        self._replica_dsn: str | None = config.get("replica_dsn")

    async def get_status(self) -> dict[str, Any]:
        nodes: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for url in self._urls:
                node = await self._probe_node(client, url)
                nodes.append(node)

        primary = next((n for n in nodes if n.get("role") == "master"), None)
        replicas = [n for n in nodes if n.get("role") == "replica"]
        status = "ok" if primary and primary.get("healthy") else "degraded"

        return {
            "type": self.type.value,
            "status": status,
            "primary": primary,
            "replicas": replicas,
            "nodes": nodes,
        }

    async def _probe_node(
        self,
        client: httpx.AsyncClient,
        url: str,
    ) -> dict[str, Any]:
        try:
            r = await client.get(f"{url.rstrip('/')}/patroni")
            data = r.json() if r.status_code == 200 else {}
            return {
                "url": url,
                "role": data.get("role"),
                "state": data.get("state"),
                "timeline": data.get("timeline"),
                "lag": (data.get("replication_state") or {}).get("lag"),
                "healthy": r.status_code == 200,
            }
        except Exception as exc:
            return {"url": url, "healthy": False, "error": str(exc)}


def build_strategy(
    *,
    type_: str,
    config: dict[str, Any],
) -> ReplicationStrategy:
    """Factory : retourne l'instance correspondant au type stocké en DB."""
    try:
        kind = ReplicationStrategyType(type_)
    except ValueError as exc:
        raise ValueError(f"unknown replication strategy: {type_}") from exc

    if kind is ReplicationStrategyType.NONE:
        return NoneStrategy()
    if kind is ReplicationStrategyType.PATRONI:
        return PatroniStrategy(config)
    raise NotImplementedError(
        f"Replication strategy '{kind.value}' not yet implemented "
        "(LOT 20 ne couvre que none + patroni)"
    )
