# Builder

## Probleme
Construire un objet complexe avec de nombreux parametres optionnels conduit a des constructeurs illisibles ou a des objets partiellement initialises. L'ordre de construction peut aussi compter.

## Solution
Separer la construction d'un objet de sa representation. Un builder expose des methodes chainees pour configurer chaque aspect, puis une methode `build()` produit l'objet final valide.

## Exemple
```python
class WorkflowStateBuilder:
    def __init__(self, team_id: str):
        self._state = {"_team_id": team_id, "messages": [], "agents": []}

    def with_phase(self, phase_id: str, status: str = "pending"):
        self._state["current_phase"] = {"id": phase_id, "status": status}
        return self

    def with_agents(self, agent_ids: list[str]):
        self._state["agents"] = agent_ids
        return self

    def with_deliverables(self, deliverables: list[dict]):
        self._state["deliverables"] = deliverables
        return self

    def build(self) -> dict:
        if "current_phase" not in self._state:
            raise ValueError("Phase is required")
        return self._state

# Usage
state = (WorkflowStateBuilder("team1")
    .with_phase("discovery", "running")
    .with_agents(["analyst", "architect"])
    .with_deliverables([{"id": "prd", "agent": "analyst"}])
    .build())
```

## Quand l'utiliser
- L'objet a beaucoup de parametres optionnels ou des combinaisons complexes
- L'ordre de construction compte (phase avant deliverables)
- On veut valider la coherence de l'objet a la construction
- Plusieurs representations du meme processus de construction

## Quand ne PAS l'utiliser
- L'objet est simple (quelques champs obligatoires)
- Pydantic BaseModel avec des validators couvre deja le besoin
