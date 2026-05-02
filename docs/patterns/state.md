# State

## Probleme
Un objet change de comportement selon son etat interne. Les cascades de if/elif sur l'etat rendent le code fragile et difficile a etendre (ajouter un nouvel etat = modifier toutes les methodes).

## Solution
Encapsuler chaque etat dans une classe distincte avec son propre comportement. L'objet delegue a l'etat courant et les transitions sont explicites.

## Exemple
```python
from abc import ABC, abstractmethod

class PhaseState(ABC):
    @abstractmethod
    async def on_enter(self, ctx: "WorkflowContext"): ...
    @abstractmethod
    async def on_agent_complete(self, ctx: "WorkflowContext", agent_id: str): ...

class PendingState(PhaseState):
    async def on_enter(self, ctx):
        logger.info(f"Phase {ctx.phase_id} en attente")
    async def on_agent_complete(self, ctx, agent_id):
        pass  # Rien a faire, pas encore demarre

class RunningState(PhaseState):
    async def on_enter(self, ctx):
        await ctx.dispatch_agents(ctx.current_group)
    async def on_agent_complete(self, ctx, agent_id):
        ctx.mark_done(agent_id)
        if ctx.group_complete():
            if ctx.has_next_group():
                await ctx.dispatch_agents(ctx.next_group())
            else:
                ctx.transition_to(CompletedState())

class CompletedState(PhaseState):
    async def on_enter(self, ctx):
        await ctx.notify_human_gate()
    async def on_agent_complete(self, ctx, agent_id):
        logger.warning(f"Agent {agent_id} termine apres completion de phase")
```

## Quand l'utiliser
- L'objet a des etats bien definis avec des transitions claires (pending/running/completed)
- Le comportement varie significativement selon l'etat
- Le workflow engine gere des phases, groupes, livrables avec des cycles de vie
- On veut rendre les transitions explicites et testables

## Quand ne PAS l'utiliser
- Seulement 2 etats simples (actif/inactif) — un booleen suffit
- Les transitions sont triviales et le comportement peu different entre etats
