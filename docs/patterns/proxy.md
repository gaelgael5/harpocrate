# Proxy

## Problème

Tu veux contrôler l'accès à un objet — ajouter du logging, du cache, de la sécurité, ou rediriger les appels vers un autre système (ex: un container Docker).

## Solution

Un objet intermédiaire qui a la même interface que l'objet réel et délègue les appels en ajoutant sa logique.

## Exemple

```python
# Le vrai objet est dans un container Docker
# Le proxy est dans la gateway et fait la médiation

class ToolProxy:
    """Proxy de tools pour un agent Docker.
    
    L'agent émet des tool calls sur stdout.
    Le proxy les intercepte, exécute les tools localement,
    et renvoie les résultats sur stdin.
    """
    def __init__(self, tools: list, process_stdin, process_stdout):
        self.tools = {t.name: t for t in tools}
        self.stdin = process_stdin
        self.stdout = process_stdout
    
    async def handle_tool_call(self, call: dict) -> str:
        tool_name = call["name"]
        tool_args = call["args"]
        
        tool = self.tools.get(tool_name)
        if not tool:
            return "Tool not found: {}".format(tool_name)
        
        # Exécute le tool localement
        result = tool.invoke(tool_args)
        
        # Renvoie le résultat au container
        self.stdin.write(json.dumps({"tool_result": result}))
        return result
```

## Quand l'utiliser

- Accès à un objet distant (container, API externe)
- Ajout de cache devant un objet coûteux
- Contrôle d'accès (vérification de droits avant délégation)
- Logging transparent des appels

## Quand ne PAS l'utiliser

- Accès direct sans contrainte → appel direct
- Le proxy n'ajoute aucune valeur
