# Prototype

## Probleme
Creer un nouvel objet depuis zero est couteux ou complexe quand un objet similaire existe deja. Dupliquer manuellement chaque champ est fragile et source d'erreurs.

## Solution
Cloner un objet existant (le prototype) puis modifier uniquement les champs qui different. Le prototype fournit une methode `clone()` qui produit une copie profonde.

## Exemple
```python
import copy

class AgentConfig:
    def __init__(self, agent_id: str, llm: str, temperature: float,
                 max_tokens: int, tools: list[str]):
        self.agent_id = agent_id
        self.llm = llm
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.tools = tools

    def clone(self, **overrides) -> "AgentConfig":
        cloned = copy.deepcopy(self)
        for key, value in overrides.items():
            setattr(cloned, key, value)
        return cloned

# Template depuis le registry
base_dev = AgentConfig("dev", "claude-sonnet", 0.3, 32768, ["github", "jira"])

# Cloner pour creer des variantes
frontend_dev = base_dev.clone(agent_id="frontend", tools=["github", "figma"])
backend_dev = base_dev.clone(agent_id="backend", tools=["github", "postgres"])
```

## Quand l'utiliser
- Creer des variantes d'un objet de reference (agents partageant la meme base)
- L'initialisation est couteuse (chargement de prompts, connexions)
- Le registry definit des templates a instancier par equipe
- On veut eviter une hierarchie de classes pour chaque variante

## Quand ne PAS l'utiliser
- Les objets sont simples a construire depuis zero
- Les copies superficielles suffisent (dict.copy())
- Le prototype mutable est partage entre threads sans protection
