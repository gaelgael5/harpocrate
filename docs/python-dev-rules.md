# Règles de développement Python

## Philosophie

Le code Python de LandGraph suit deux principes fondamentaux :
- **Clarté** : le code est écrit pour être lu par des humains, pas par des machines
- **Responsabilité unique** : chaque classe, chaque méthode, chaque module fait UNE chose et la fait bien

## Classes

### Une classe = une responsabilité

Avant de créer une classe, réponds à cette question : **"Cette classe sert à quoi en une phrase ?"**
Si la phrase contient "et", c'est deux classes.

```python
# MAL — fait deux choses
class UserManager:
    def authenticate(self, email, password): ...
    def send_welcome_email(self, user): ...

# BIEN — chaque classe a sa responsabilité
class Authenticator:
    def authenticate(self, email, password): ...

class WelcomeNotifier:
    def send(self, user): ...
```

### Avant d'ajouter du code à une classe existante

Pose-toi la question : **"Est-ce que c'est le travail de cette classe ou celui d'une nouvelle classe ?"**

Signaux d'alerte :
- La classe fait plus de 200 lignes → probablement trop de responsabilités
- Tu ajoutes des méthodes qui n'utilisent pas les mêmes attributs → ce sont deux classes
- Le nom de la classe ne décrit plus ce qu'elle fait → il faut découper

### Pas de classes inutiles

Ne crée pas une classe quand une fonction suffit. Une classe se justifie quand :
- Elle maintient un état interne (attributs)
- Elle a un cycle de vie (init, configure, execute, cleanup)
- Elle implémente une interface ou un protocole

```python
# INUTILE — pas d'état, une fonction suffit
class TextFormatter:
    def format(self, text):
        return text.strip().lower()

# SIMPLE — une fonction
def format_text(text: str) -> str:
    return text.strip().lower()
```

## Méthodes et fonctions

### Une méthode = une action

Une méthode fait UNE chose. Si elle fait deux choses, c'est deux méthodes.

```python
# MAL — fait deux choses
def process_order(order):
    validate_stock(order)
    charge_payment(order)
    send_confirmation(order)
    update_inventory(order)

# BIEN — orchestration claire, chaque étape est isolée
def process_order(order):
    _validate(order)
    _charge(order)
    _confirm(order)
    _update_stock(order)
```

### Taille d'une méthode

- Idéal : 5-15 lignes
- Maximum : 30 lignes
- Au-delà : découper en sous-méthodes

### Paramètres

- Maximum 4 paramètres. Au-delà, utiliser un dataclass ou un dict typé
- Pas de `**kwargs` sauf pour du forwarding transparent
- Typer tous les paramètres et retours

```python
# MAL — trop de paramètres
def create_user(name, email, role, team, avatar, language, timezone): ...

# BIEN — regrouper dans un objet
@dataclass
class UserCreate:
    name: str
    email: str
    role: str
    team: str
    avatar: str = ""
    language: str = "fr"
    timezone: str = "UTC"

def create_user(data: UserCreate): ...
```

## SOLID appliqué au projet

### S — Single Responsibility (Responsabilité unique)
Chaque module, classe, méthode a une seule raison de changer.
- `team_resolver.py` → résolution des chemins, rien d'autre
- `llm_provider.py` → instanciation des LLM, rien d'autre
- `orchestrator_tools.py` → tools de l'orchestrateur, rien d'autre

### O — Open/Closed (Ouvert/Fermé)
Le code est ouvert à l'extension, fermé à la modification.
- Ajouter un nouveau tool → créer une fonction `@tool`, l'ajouter à la liste
- Ajouter un canal de communication → implémenter `MessageChannel`, pas modifier `channels.py`
- Ajouter un type de LLM → ajouter dans `llm_providers.json`, pas modifier `llm_provider.py`

### L — Liskov Substitution
Toute sous-classe doit pouvoir remplacer sa classe parente sans casser le code.
- Un agent Docker doit respecter la même interface qu'un agent in-process
- Un canal Email doit se comporter comme un canal Discord du point de vue de l'appelant

### I — Interface Segregation
Pas d'interface fourre-tout. Préférer plusieurs petites interfaces.
- `save_deliverable` est un tool séparé de `rag_search` — pas un mega-tool "file_operations"

### D — Dependency Inversion
Dépendre des abstractions, pas des implémentations.
- Jamais `import psycopg` dans un tool — passer par `execute()` / `fetch_one()`
- Jamais `import requests` pour appeler le RAG — passer par le service dédié
- Les tools lisent le contexte depuis `_ctx`, pas depuis des variables globales

## Nommage

### Convention projet

| Élément | Convention | Exemple |
|---------|-----------|---------|
| Fichiers | snake_case | `orchestrator_tools.py` |
| Classes | PascalCase | `BaseAgent`, `ProjectState` |
| Fonctions/méthodes | snake_case | `get_orchestrator_tools()` |
| Constantes | UPPER_SNAKE | `ONBOARDING_THREAD_PREFIX` |
| Variables | snake_case | `team_id`, `agent_config` |
| Préfixe privé | `_` | `_load_config()`, `_ctx` |

### Préfixes de méthodes selon la source

| Préfixe | Source | Exemple |
|---------|--------|---------|
| `db_` | Lecture/écriture DB | `db_get_phase()`, `db_create_next_group()` |
| `file_` | Lecture fichier | `file_find_phase_def()` |
| `resolve_` | Orchestre DB + fichier | `resolve_next_phase()` |

### Nommage explicite

Le nom doit dire ce que fait la fonction, pas comment elle le fait.

```python
# MAL
def process(data): ...
def handle(event): ...
def do_stuff(): ...

# BIEN
def resolve_agent_avatar(team_id, agent_id): ...
def create_hitl_request(thread_id, prompt): ...
def check_human_gate(workflow_id, phase_key): ...
```

## Gestion des erreurs

### Pas de fallback silencieux

Jamais de valeur par défaut qui masque un bug. Si une donnée est requise, lever une erreur.

```python
# MAL — masque un bug
team_id = state.get("_team_id", "team1")

# BIEN — erreur explicite
from agents.shared.team_resolver import require_team_id
team_id = require_team_id(state)
```

### Pas de except vide

```python
# MAL
try:
    result = do_something()
except:
    pass

# BIEN
try:
    result = do_something()
except SpecificError as exc:
    logger.error("context: %s", exc)
    raise
```

### Erreurs à la frontière, pas au milieu

Valider les entrées au début de la fonction, pas au milieu du traitement.

```python
# BIEN — validation en entrée
def save_deliverable(key: str, content: str) -> str:
    if not key:
        return "Erreur: deliverable_key vide."
    if not content.strip():
        return "Erreur: contenu vide."
    # ... logique métier sans vérifications
```

## Pas de hardcode

### Pas de constantes magiques

```python
# MAL
if agent_id == "Orchestrator": ...
if team_id == "team1": ...

# BIEN — lire depuis la config
orch_id = get_team_info(team_id).get("orchestrator", "")
if agent_id == orch_id: ...
```

## Python 3.11 (Docker)

Le code tourne en Python 3.11 dans Docker. Restrictions :
- **Pas de backslash dans les f-strings** : utiliser `.format()` à la place
- **Pas de `type` statement** (Python 3.12+)
- **Pas de `match` exhaustif** avec `type` guards (limité en 3.11)

```python
# MAL en 3.11
f"path: {path.replace('\\', '/')}"

# BIEN
"path: {}".format(path.replace("\\", "/"))
```

## Récursivité

### Quand utiliser la récursivité

La récursivité est le bon choix quand la structure de données est elle-même récursive :
- Arborescence de workflows (workflow → phase externe → sous-workflow → ...)
- Parcours de graphe (entités avec relations)
- Structures hiérarchiques (équipes, dossiers, dépendances)

### Règles obligatoires

**1. Toujours un cas d'arrêt clair**

Le cas d'arrêt est la première chose dans la méthode, pas caché au milieu.

```python
# BIEN — cas d'arrêt immédiat et visible
async def db_get_current_position(workflow_id: int) -> dict:
    workflow = await fetch_one(...)
    if not workflow:
        return {"error": "Workflow not found"}       # cas d'arrêt 1
    if not workflow["current_phase_id"]:
        return {"status": "not_started"}              # cas d'arrêt 2
    # ... logique récursive
```

**2. Limiter la profondeur**

Toujours protéger contre la récursion infinie avec un compteur de profondeur.

```python
MAX_DEPTH = 10

async def db_get_current_position(workflow_id: int, _depth: int = 0) -> dict:
    if _depth >= MAX_DEPTH:
        return {"error": "Profondeur max atteinte — cycle detecte"}
    # ...
    if phase.get("depends_on_workflow_id"):
        return await db_get_current_position(
            phase["depends_on_workflow_id"], _depth=_depth + 1
        )
```

**3. Isoler la logique récursive dans une méthode dédiée**

La méthode récursive ne fait que naviguer. Le traitement est dans des méthodes séparées.

```python
# MAL — mélange navigation et traitement
async def process_workflow(workflow_id):
    workflow = load(workflow_id)
    create_phase(workflow)         # traitement
    send_notification(workflow)    # traitement
    if has_child:
        process_workflow(child_id) # récursion + traitement

# BIEN — navigation séparée du traitement
async def db_get_current_position(workflow_id):
    """Navigation uniquement."""
    # ... suit la chaîne, retourne la position

async def process_at_position(position):
    """Traitement uniquement."""
    # ... agit sur la position trouvée
```

**4. Pas d'effets de bord dans la récursion**

La méthode récursive lit et retourne, elle ne modifie pas l'état. Les modifications sont faites par l'appelant avec le résultat.

```python
# MAL — modifie l'état pendant la récursion
async def advance(workflow_id):
    update_status(workflow_id, "running")  # effet de bord
    if has_child:
        advance(child_id)                  # récursion avec effet de bord

# BIEN — la récursion ne fait que lire
async def db_get_current_position(workflow_id):
    # ... navigation pure, retourne la position

# L'appelant décide quoi faire
position = await db_get_current_position(workflow_id)
await update_status(position["phase"]["id"], "running")
```

**5. Tester les cas limites**

Pour chaque méthode récursive, tester :
- Profondeur 0 (cas d'arrêt immédiat)
- Profondeur 1 (un seul niveau)
- Profondeur max (cycle ou chaîne longue)
- Données manquantes (workflow inexistant, phase null)

## Async/Await

- Les fonctions DB sont async (`fetch_one`, `execute`)
- Les endpoints FastAPI sont async
- Les MCP tools peuvent être sync ou async — toujours gérer les deux cas
- Pas de `asyncio.run()` dans une coroutine — utiliser `ThreadPoolExecutor` si nécessaire

```python
# Pattern pour appeler un tool async depuis du sync
try:
    result = tool.invoke(args)
except NotImplementedError:
    import asyncio
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as pool:
        result = pool.submit(asyncio.run, tool.ainvoke(args)).result()
```

## Design Patterns

Utiliser le bon pattern pour le bon problème. Ne pas forcer un pattern quand une fonction simple suffit.

### Creational — création d'objets

| Pattern | Quand l'utiliser | Détails |
|---------|-----------------|---------|
| **Factory** | Créer un objet dont le type dépend d'une config (ex: quel LLM, quel canal) | [factory.md](patterns/factory.md) |
| **Abstract Factory** | Créer des familles d'objets liés (ex: suite de composants UI par thème) | [abstract-factory.md](patterns/abstract-factory.md) |
| **Builder** | Construire un objet complexe étape par étape (ex: construire un state LangGraph) | [builder.md](patterns/builder.md) |
| **Singleton** | Une seule instance partagée dans tout le process (ex: langfuse callback, event bus) | [singleton.md](patterns/singleton.md) |
| **Prototype** | Créer un objet en copiant un modèle existant (ex: cloner une config d'agent) | [prototype.md](patterns/prototype.md) |

### Structural — organisation des objets

| Pattern | Quand l'utiliser | Détails |
|---------|-----------------|---------|
| **Proxy** | Un intermédiaire qui contrôle l'accès à un objet (ex: gateway proxy de tools Docker) | [proxy.md](patterns/proxy.md) |
| **Adapter** | Faire collaborer des interfaces incompatibles (ex: wrapper MCP stdio → HTTP) | [adapter.md](patterns/adapter.md) |
| **Facade** | Interface simplifiée devant un système complexe (ex: `team_resolver` devant config/) | [facade.md](patterns/facade.md) |
| **Decorator** | Ajouter un comportement à un objet sans le modifier (ex: `@tool`, logging, retry) | [decorator.md](patterns/decorator.md) |
| **Composite** | Traiter un arbre d'objets uniformément (ex: workflow → phases → groupes → agents) | [composite.md](patterns/composite.md) |

### Behavioral — comportement et communication

| Pattern | Quand l'utiliser | Détails |
|---------|-----------------|---------|
| **Strategy** | Plusieurs implémentations interchangeables d'une même interface (ex: canaux Discord/Email) | [strategy.md](patterns/strategy.md) |
| **Observer** | Notifier plusieurs composants quand un événement se produit (ex: event bus, PG NOTIFY) | [observer.md](patterns/observer.md) |
| **Mediator** | Un composant central coordonne les interactions entre d'autres (ex: orchestrateur) | [mediator.md](patterns/mediator.md) |
| **Template Method** | Un squelette d'algorithme avec des étapes que les sous-classes adaptent (ex: BaseAgent) | [template-method.md](patterns/template-method.md) |
| **Chain of Responsibility** | Passer une requête le long d'une chaîne de handlers (ex: groupes séquentiels A→B→C) | [chain-of-responsibility.md](patterns/chain-of-responsibility.md) |
| **Command** | Encapsuler une action comme un objet (ex: tool calls, dispatcher_tasks en DB) | [command.md](patterns/command.md) |
| **State** | Changer le comportement d'un objet selon son état interne (ex: workflow pending→running→completed) | [state.md](patterns/state.md) |
| **Visitor** | Appliquer une opération à une structure sans la modifier (ex: parcourir les livrables pour indexation RAG) | [visitor.md](patterns/visitor.md) |

### Architectural — organisation du système

| Pattern | Quand l'utiliser | Détails |
|---------|-----------------|---------|
| **IoC / Dependency Injection** | Inverser les dépendances — le code dépend d'abstractions pas d'implémentations (ex: `_ctx`, tools injectés) | [ioc.md](patterns/ioc.md) |
| **Repository** | Abstraire l'accès aux données (ex: `db_get_phase`, `db_create_next_group`) | [repository.md](patterns/repository.md) |
| **Event-Driven** | Architecture pilotée par les événements (ex: PG NOTIFY → WS → frontend) | [event-driven.md](patterns/event-driven.md) |

## Tests

- Un test par comportement, pas par méthode
- Nommer les tests : `test_{ce_qui_est_testé}_{condition}_{résultat_attendu}`
- Utiliser `pytest` avec fixtures
- Mocker les dépendances externes (DB, HTTP, LLM)
- Pas de test qui dépend de l'ordre d'exécution
