# Event-Driven Architecture

## Probleme
Les composants doivent reagir aux changements d'etat (agent termine, phase complete, livrable valide) mais un couplage direct entre emetteur et recepteurs cree une toile de dependances ingerable.

## Solution
Les composants emettent des evenements sur un bus central. Les recepteurs s'abonnent aux types d'evenements qui les interessent. L'emetteur ne connait pas ses recepteurs.

## Exemple
```python
from typing import Callable
from collections import defaultdict

class EventBus:
    def __init__(self):
        self._handlers: dict[str, list[Callable]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: Callable):
        self._handlers[event_type].append(handler)

    async def emit(self, event_type: str, payload: dict):
        for handler in self._handlers[event_type]:
            await handler(payload)

bus = EventBus()

# Recepteurs independants — aucun couplage entre eux
bus.subscribe("agent_complete", lambda p: db_update_status(p["agent_id"], "done"))
bus.subscribe("agent_complete", lambda p: ws_broadcast(p["team_id"], p))
bus.subscribe("phase_complete", lambda p: pg_notify("phase_events", p["phase_id"]))

# Emetteur — ne sait pas qui ecoute
await bus.emit("agent_complete", {
    "agent_id": "analyst",
    "team_id": "team1",
    "deliverable_id": "prd",
})
```

## Quand l'utiliser
- Plusieurs composants doivent reagir au meme evenement (DB + WebSocket + Langfuse)
- PG NOTIFY vers le frontend via WebSocket pour le refresh temps reel
- Decoupler le workflow engine des canaux de notification
- Audit trail et observabilite (chaque evenement est un fait immutable)

## Quand ne PAS l'utiliser
- Un seul recepteur pour un evenement (un appel direct est plus simple)
- L'ordre d'execution des handlers est critique (le bus ne garantit pas l'ordre)
- Le debug est prioritaire (les evenements asynchrones compliquent le tracing)
