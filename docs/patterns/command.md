# Command

## Probleme
On veut decoupler l'emetteur d'une action de son executeur. Les actions doivent etre serialisables, mises en file d'attente, rejouees ou annulees. Un appel direct de methode ne permet pas cela.

## Solution
Encapsuler chaque action dans un objet Command avec une methode `execute()`. Les commandes peuvent etre stockees en DB, mises en queue, et executees de maniere asynchrone.

## Exemple
```python
from dataclasses import dataclass

@dataclass
class DispatchTask:
    """Commande persistee en DB (table dispatcher_tasks)."""
    agent_id: str
    deliverable_id: str
    phase_id: str
    input_data: dict
    status: str = "pending"

    async def execute(self, agent_loader, llm_provider):
        self.status = "running"
        agent = agent_loader.get(self.agent_id)
        prompt = build_prompt(agent, self.deliverable_id, self.input_data)
        result = await llm_provider.invoke(agent.llm, prompt)
        self.status = "completed"
        return result

# File de commandes — decouplement total emetteur/executeur
tasks: list[DispatchTask] = db_get_pending_tasks(phase_id="discovery")
results = await asyncio.gather(*[t.execute(loader, llm) for t in tasks])
```

## Quand l'utiliser
- Actions asynchrones persistees en base (dispatcher_tasks, tool_calls)
- File d'attente de taches avec retry et statut (pending/running/completed/failed)
- Historique des actions pour audit ou replay
- Decoupler la decision de dispatcher de l'execution

## Quand ne PAS l'utiliser
- L'action est instantanee et n'a pas besoin de persistence
- Un simple appel de fonction suffit (pas de queue, pas de retry)
- La complexite de serialisation depasse le benefice
