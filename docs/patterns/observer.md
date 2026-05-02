# Observer

## Problème

Quand un événement se produit (agent terminé, question posée, phase changée), plusieurs composants doivent réagir sans se connaître.

## Solution

Un bus d'événements. Les émetteurs publient des events, les abonnés les reçoivent.

## Exemple

```python
class EventBus:
    def __init__(self):
        self._handlers: dict[str, list[Callable]] = {}
    
    def on(self, event_type: str, handler: Callable):
        self._handlers.setdefault(event_type, []).append(handler)
    
    def emit(self, event: Event):
        for handler in self._handlers.get(event.type, []):
            handler(event)

# Abonnement
bus = EventBus()
bus.on("agent_complete", log_completion)
bus.on("agent_complete", update_dashboard)
bus.on("agent_complete", notify_user)

# Émission — l'émetteur ne sait pas qui écoute
bus.emit(Event("agent_complete", agent_id="Architect", data={...}))
```

## Quand l'utiliser

- Plusieurs composants doivent réagir au même événement
- L'émetteur ne doit pas connaître les consommateurs
- Tu veux ajouter des réactions sans modifier l'émetteur

## Quand ne PAS l'utiliser

- Un seul consommateur → appel direct
- L'ordre de traitement est important → chaîne explicite
