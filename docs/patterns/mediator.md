# Mediator

## Problème

Plusieurs composants (agents) doivent collaborer mais ne doivent pas se connaître directement. Sans médiateur, chaque agent devrait connaître tous les autres → couplage explosif.

## Solution

Un composant central (l'orchestrateur) qui reçoit les demandes et les redirige vers le bon destinataire.

## Exemple

```python
# Sans médiateur — couplage direct
class Architect:
    def __init__(self, analyst, ux_designer):
        self.analyst = analyst      # connaît l'analyst
        self.ux_designer = ux_designer  # connaît le designer

# Avec médiateur — les agents ne se connaissent pas
class Orchestrator:
    def dispatch(self, agent_id: str, task: str):
        agent = self.agents[agent_id]
        return agent.execute(task)

class Architect:
    def execute(self, task: str):
        # Travaille seul, ne connaît pas les autres
        return self.analyze(task)
```

## Quand l'utiliser

- Beaucoup de composants qui interagissent
- Les interactions changent souvent
- Tu veux centraliser la logique de coordination

## Quand ne PAS l'utiliser

- Deux composants qui communiquent → appel direct
- Le médiateur devient un god object → le découper
