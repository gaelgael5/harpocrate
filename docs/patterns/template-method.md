# Template Method

## Problème

Plusieurs classes suivent le même algorithme global mais certaines étapes varient. Tu veux éviter de dupliquer le squelette.

## Solution

La classe parente définit le squelette de l'algorithme. Les sous-classes redéfinissent les étapes qui varient.

## Exemple

```python
class BaseAgent:
    def __call__(self, state):
        """Squelette — toujours le même."""
        self._setup(state)
        self._override_prompt(state)
        result = self._execute(state)
        self._store_result(state, result)
        return state
    
    def _setup(self, state):
        """Étape commune — pas de redéfinition."""
        self._current_state = state
    
    def _execute(self, state):
        """Étape variable — chaque agent l'implémente."""
        raise NotImplementedError
    
    def _store_result(self, state, result):
        """Étape commune avec possibilité de surcharge."""
        state["agent_outputs"][self.agent_id] = result

class ArchitectAgent(BaseAgent):
    def _execute(self, state):
        # Logique spécifique à l'architecte
        return self.analyze_architecture(state)
```

## Quand l'utiliser

- Le squelette de l'algorithme est identique entre les classes
- Seules certaines étapes varient
- Tu veux garantir que les étapes sont exécutées dans le bon ordre

## Quand ne PAS l'utiliser

- Chaque classe a un algorithme complètement différent
- Une seule classe → pas besoin d'héritage
