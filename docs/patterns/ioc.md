# Inversion of Control / Dependency Injection

## Probleme
Un module instancie directement ses dependances, ce qui le rend impossible a tester en isolation et cree un couplage fort. Changer une dependance (ex: provider LLM) impose de modifier le module.

## Solution
Les dependances sont injectees de l'exterieur (constructeur, parametre, ou contexte). Le module declare ce dont il a besoin sans savoir d'ou ca vient. Un conteneur ou un contexte se charge de l'assemblage.

## Exemple
```python
from dataclasses import dataclass, field

@dataclass
class AgentContext:
    """Contexte injecte a chaque agent au runtime."""
    team_id: str
    llm_provider: "LLMProvider"
    mcp_client: "MCPClient"
    channel: "MessageChannel"
    db: "AsyncConnection"

class BaseAgent:
    def __init__(self, config: dict, ctx: AgentContext):
        self.config = config
        self.ctx = ctx  # Toutes les dependances injectees

    async def run(self, task: str) -> str:
        # Utilise les dependances injectees, jamais d'import direct
        llm = self.ctx.llm_provider
        response = await llm.invoke(self.config["llm"], task)
        await self.ctx.channel.send(self.ctx.team_id, response)
        return response

# Assemblage au niveau gateway — l'agent ne sait pas d'ou viennent ses deps
ctx = AgentContext(
    team_id="team1",
    llm_provider=get_llm_provider(),
    mcp_client=get_mcp_client(),
    channel=get_default_channel(),
    db=await get_db_connection(),
)
agent = BaseAgent(registry["analyst"], ctx)
```

## Quand l'utiliser
- Les modules doivent etre testables en isolation (mock du LLM, de la DB)
- Plusieurs implementations interchangeables (Discord/Email, Claude/GPT)
- Le contexte runtime varie (equipe, thread, utilisateur)
- On veut un point d'assemblage unique (gateway) plutot que des imports eparpilles

## Quand ne PAS l'utiliser
- Le module n'a qu'une seule dependance stable (ex: `import json`)
- L'injection ajoute de l'indirection sans benefice testabilite
- Scripts simples ou one-shots sans besoin de flexibilite
