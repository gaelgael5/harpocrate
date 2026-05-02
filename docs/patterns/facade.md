# Facade

## Probleme
Un sous-systeme complexe expose de nombreuses classes et methodes. Le code appelant doit connaitre les details internes pour l'utiliser, ce qui cree un couplage fort et fragile.

## Solution
Une facade fournit une interface simplifiee qui orchestre les appels internes. Le code appelant n'interagit qu'avec la facade, ignorant la complexite sous-jacente.

## Exemple
```python
class TeamResolver:
    """Facade pour la resolution de fichiers de configuration."""

    def __init__(self):
        self._config_root = self._find_config_root()
        self._teams = self._load_teams_json()

    def get_agent_registry(self, team_id: str) -> dict:
        """Un seul appel au lieu de: trouver root, lire teams.json,
        resoudre le directory, construire le path, lire le JSON."""
        directory = self._teams[team_id]["directory"]
        path = self._config_root / directory / "agents_registry.json"
        return json.loads(path.read_text())

    def get_prompt(self, team_id: str, prompt_file: str) -> str:
        directory = self._teams[team_id]["directory"]
        path = self._config_root / directory / prompt_file
        if not path.exists():
            path = self._config_root / "defaults" / prompt_file
        return path.read_text()

# Usage : un seul point d'entree, zero connaissance de config/
resolver = TeamResolver()
registry = resolver.get_agent_registry("team1")
prompt = resolver.get_prompt("team1", "analyst.md")
```

## Quand l'utiliser
- Un sous-systeme a une API large que la plupart des appelants n'utilisent qu'en partie
- On veut decoupler les modules metier de la structure du filesystem (team_resolver)
- Simplifier l'acces a une combinaison de services (DB + cache + filesystem)
- Fournir un point d'entree stable malgre des refactors internes

## Quand ne PAS l'utiliser
- Le sous-systeme est deja simple (2-3 methodes)
- Les appelants ont besoin d'un controle fin sur les composants internes
