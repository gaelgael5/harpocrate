# Strategy

## Problème

Tu as plusieurs façons de faire la même chose (envoyer un message via Discord, Email, Telegram) et tu veux pouvoir changer d'implémentation sans modifier le code appelant.

## Solution

Une interface commune (classe abstraite ou protocole) avec des implémentations interchangeables.

## Exemple

```python
from abc import ABC, abstractmethod

class MessageChannel(ABC):
    @abstractmethod
    async def send(self, channel_id: str, message: str) -> bool: ...
    
    @abstractmethod
    async def ask(self, channel_id: str, question: str) -> dict: ...

class DiscordChannel(MessageChannel):
    async def send(self, channel_id, message):
        # ... envoie via Discord REST API
        return True

class EmailChannel(MessageChannel):
    async def send(self, channel_id, message):
        # ... envoie via SMTP
        return True

# L'appelant utilise l'interface, pas l'implémentation
channel = get_default_channel()  # retourne Discord ou Email selon la config
await channel.send("123", "Hello")
```

## Quand l'utiliser

- Plusieurs algorithmes/implémentations pour la même opération
- Le choix de l'implémentation est fait à la config ou au runtime
- Tu veux ajouter une implémentation sans toucher aux existantes

## Quand ne PAS l'utiliser

- Une seule implémentation existe et existera
- Les implémentations n'ont pas la même interface
