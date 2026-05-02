# Chain of Responsibility

## Problème

Une requête doit passer par plusieurs étapes séquentielles. Chaque étape décide si elle traite la requête ou la passe à la suivante.

## Solution

Une chaîne de handlers. Chaque handler traite ou délègue au suivant.

## Exemple

```python
# Les groupes d'une phase s'exécutent en chaîne : A → B → C
# Le groupe A doit finir avant que B ne commence

async def execute_phase_groups(phase_def: dict, state: dict):
    groups = sorted(phase_def.get("groups", []), key=lambda g: g.get("order", 0))
    
    for group in groups:
        agents = group.get("agents", [])
        
        # Exécuter les agents du groupe en parallèle
        await run_agents_parallel(agents, state)
        
        # Vérifier si le groupe est réussi avant de passer au suivant
        if not all_deliverables_complete(group, state):
            raise GroupIncompleteError(group["id"])
    
    # Tous les groupes sont passés
    return state
```

## Quand l'utiliser

- Traitement séquentiel avec des étapes conditionnelles
- Chaque étape peut court-circuiter la chaîne (échec, validation)
- L'ordre des étapes est important

## Quand ne PAS l'utiliser

- Les étapes sont indépendantes → exécuter en parallèle
- Une seule étape → appel direct
