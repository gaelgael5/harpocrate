# Composite

## Probleme
On manipule une structure arborescente (workflow > phases > groupes > agents) et le code doit traiter uniformement les noeuds individuels et les conteneurs. Sans pattern, chaque niveau necessite un traitement specifique.

## Solution
Definir une interface commune pour les feuilles et les composites. Un composite contient des enfants (feuilles ou autres composites) et delegue les operations recursivement.

## Exemple
```python
from abc import ABC, abstractmethod

class WorkflowNode(ABC):
    @abstractmethod
    def get_status(self) -> str: ...
    @abstractmethod
    def get_agents(self) -> list[str]: ...

class AgentLeaf(WorkflowNode):
    def __init__(self, agent_id: str, status: str = "pending"):
        self.agent_id = agent_id
        self.status = status
    def get_status(self) -> str:
        return self.status
    def get_agents(self) -> list[str]:
        return [self.agent_id]

class ParallelGroup(WorkflowNode):
    def __init__(self, children: list[WorkflowNode]):
        self.children = children
    def get_status(self) -> str:
        statuses = [c.get_status() for c in self.children]
        if all(s == "completed" for s in statuses): return "completed"
        if any(s == "running" for s in statuses): return "running"
        return "pending"
    def get_agents(self) -> list[str]:
        return [a for c in self.children for a in c.get_agents()]

# Workflow > Phase > Group > Agent — traitement uniforme
group_a = ParallelGroup([AgentLeaf("analyst"), AgentLeaf("architect")])
print(group_a.get_agents())  # ["analyst", "architect"]
```

## Quand l'utiliser
- Structure arborescente naturelle (workflow phases/groupes, menus, fichiers)
- Le code client doit traiter feuilles et conteneurs de la meme maniere
- On veut calculer des proprietes aggregees recursivement (statut, cout, duree)
- La profondeur de l'arbre peut varier

## Quand ne PAS l'utiliser
- La structure est plate (une seule liste d'elements)
- Les operations different fondamentalement entre feuilles et conteneurs
