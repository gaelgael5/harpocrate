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
                "name": data.get("patroni", {}).get("scope") or data.get("name"),
                "role": data.get("role"),
                "state": data.get("state"),
                "timeline": data.get("timeline"),
                "lag": (data.get("replication_state") or {}).get("lag"),
                "healthy": r.status_code == 200,
            }
        except Exception as exc:
            return {"url": url, "healthy": False, "error": str(exc)}

    # ─── A-9 : actions admin sur le cluster Patroni ──────────────────────────

    async def _find_leader_url(self, client: httpx.AsyncClient) -> str | None:
        """Trouve l'URL du leader actuel parmi `_urls`. Retourne None si aucun
        nœud n'est joignable ou n'est leader."""
        for url in self._urls:
            try:
                r = await client.get(f"{url.rstrip('/')}/patroni")
                if r.status_code == 200 and r.json().get("role") == "master":
                    return url
            except Exception:
                continue
        return None

    async def switchover(
        self,
        *,
        candidate_name: str | None = None,
        scheduled_at: str | None = None,
    ) -> dict[str, Any]:
        """Switchover gracieux Patroni.

        Si `candidate_name` est None, Patroni choisit le meilleur replica.
        Si `scheduled_at` est None, le switchover est immediat.

        Cible le leader actuel pour POST /switchover.
        """
        async with httpx.AsyncClient(timeout=self._timeout * 5) as client:
            leader_url = await self._find_leader_url(client)
            if leader_url is None:
                raise PatroniOperationError(
                    "no_leader_found",
                    "Could not locate the current leader among configured patroni_api_urls",
                )
            # Recupere le nom du leader pour le passer dans le body
            r = await client.get(f"{leader_url.rstrip('/')}/patroni")
            data = r.json() if r.status_code == 200 else {}
            leader_name = (data.get("patroni") or {}).get("scope_name") or data.get(
                "name"
            )

            body: dict[str, Any] = {}
            if leader_name:
                body["leader"] = leader_name
            if candidate_name:
                body["candidate"] = candidate_name
            if scheduled_at:
                body["scheduled_at"] = scheduled_at

            resp = await client.post(
                f"{leader_url.rstrip('/')}/switchover", json=body
            )
            if resp.status_code not in (200, 202):
                raise PatroniOperationError(
                    "switchover_failed",
                    f"Patroni rejected switchover: HTTP {resp.status_code} {resp.text}",
                )
            return {
                "ok": True,
                "leader_url": leader_url,
                "leader_name": leader_name,
                "candidate": candidate_name,
                "patroni_response": resp.text,
            }

    async def reinitialize_member(self, member_url: str) -> dict[str, Any]:
        """Reinitialize un membre du cluster (drop data dir + clone depuis leader).

        L'URL fournie doit etre celle de l'API Patroni du membre cible. Le
        membre lui-meme execute la commande — c'est destructif et long
        (depend de la taille de la DB).

        Refuse de cibler le leader (operation invalide cote Patroni).
        """
        if member_url not in self._urls:
            raise PatroniOperationError(
                "unknown_member",
                f"Member URL {member_url!r} is not in configured patroni_api_urls",
            )
        async with httpx.AsyncClient(timeout=self._timeout * 10) as client:
            # Verifie que le membre n'est pas le leader actuel
            try:
                r = await client.get(f"{member_url.rstrip('/')}/patroni")
                if r.status_code == 200 and r.json().get("role") == "master":
                    raise PatroniOperationError(
                        "cannot_reinit_leader",
                        "Refusing to reinitialize the current leader — switchover first",
                    )
            except PatroniOperationError:
                raise
            except Exception:
                # Si le membre est down, on tente quand meme le reinit
                pass

            resp = await client.post(
                f"{member_url.rstrip('/')}/reinitialize", json={"force": False}
            )
            if resp.status_code not in (200, 202):
                raise PatroniOperationError(
                    "reinit_failed",
                    f"Patroni rejected reinitialize: HTTP {resp.status_code} {resp.text}",
                )
            return {
                "ok": True,
                "member_url": member_url,
                "patroni_response": resp.text,
            }

    async def _set_pause(self, pause: bool) -> dict[str, Any]:
        """Active/desactive l'auto-failover via PATCH /config sur le leader."""
        async with httpx.AsyncClient(timeout=self._timeout * 3) as client:
            leader_url = await self._find_leader_url(client)
            if leader_url is None:
                raise PatroniOperationError(
                    "no_leader_found",
                    "Could not locate the current leader for pause/resume",
                )
            resp = await client.patch(
                f"{leader_url.rstrip('/')}/config",
                json={"pause": pause},
            )
            if resp.status_code not in (200, 202):
                raise PatroniOperationError(
                    "pause_failed",
                    f"Patroni rejected pause={pause}: HTTP {resp.status_code} {resp.text}",
                )
            return {"ok": True, "paused": pause, "leader_url": leader_url}

    async def pause(self) -> dict[str, Any]:
        """Suspend l'auto-failover Patroni (utile pour maintenance)."""
        return await self._set_pause(True)

    async def resume(self) -> dict[str, Any]:
        """Reactive l'auto-failover Patroni."""
        return await self._set_pause(False)


class PatroniOperationError(Exception):
    """Levee quand une operation Patroni (switchover/reinit/pause) echoue."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


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
