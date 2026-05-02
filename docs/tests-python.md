# Règles de tests Python

## Philosophie

La couverture de test est un outil pour trouver ce qui n'est pas testé.
Ce n'est pas un score à maximiser aveuglément.
On teste pour avoir confiance quand on modifie le code, pas pour cocher une case.

Un bon test :
- Prouve qu'un comportement fonctionne
- Casse quand le comportement change
- Est rapide à exécuter
- Est facile à lire et à maintenir

## Seuils de couverture par zone

| Zone | Min | Justification |
|------|-----|---------------|
| `Agents/Shared/` (tools, tracker, resolver) | 80% | Cœur du système, partagé par tous les modules |
| `hitl/services/` (analysis, hitl, rag) | 75% | Logique métier critique |
| `Agents/gateway.py`, `orchestrator.py` | 60% | Orchestration complexe, beaucoup d'intégration |
| `hitl/routes/` (endpoints) | 60% | Routes simples, peu de logique propre |
| `web/server.py` (admin dashboard) | 40% | UI admin, moins critique |

En dessous de 50% sur une zone → alerte. Au-dessus de 90% → probablement du test inutile.

## Règle du delta

Tout nouveau code ou code modifié doit avoir **90% de couverture** sur les lignes changées.
On ne vérifie pas le projet entier — seulement ce qui a bougé.

## Ce qu'on teste obligatoirement

### Méthodes DB (`db_*`)
Chaque méthode qui lit ou écrit en base doit avoir un test avec mock DB.

```python
@patch("services.analysis_service.fetch_one")
async def test_db_get_phase_returns_phase(mock_fetch):
    mock_fetch.return_value = {"id": 1, "phase_key": "discovery", "status": "running"}
    result = await db_get_phase(1)
    assert result["phase_key"] == "discovery"

@patch("services.analysis_service.fetch_one")
async def test_db_get_phase_returns_none_if_not_found(mock_fetch):
    mock_fetch.return_value = None
    result = await db_get_phase(999)
    assert result is None
```

### Méthodes fichier (`file_*`)
Chaque méthode qui lit un fichier doit avoir un test avec fichiers temporaires.

```python
def test_file_find_phase_def_returns_phase(tmp_path):
    wf = {"phases": {"discovery": {"order": 0, "name": "Discovery"}}}
    wf_file = tmp_path / "test.wrk.json"
    wf_file.write_text(json.dumps(wf))
    result = file_find_phase_def(str(wf_file), 0)
    assert result is not None
    assert result[0] == "discovery"

def test_file_find_phase_def_returns_none_for_missing_order(tmp_path):
    wf = {"phases": {"discovery": {"order": 0}}}
    wf_file = tmp_path / "test.wrk.json"
    wf_file.write_text(json.dumps(wf))
    assert file_find_phase_def(str(wf_file), 5) is None
```

### Méthodes d'orchestration (`resolve_*`)
Test d'intégration qui vérifie le flux complet.

```python
async def test_resolve_next_phase_advances_to_next_group():
    # Setup: workflow avec phase discovery, groupe A terminé, groupe B à faire
    # Assert: retourne la phase discovery/B
    ...

async def test_resolve_next_phase_blocked_by_human_gate():
    # Setup: dernier groupe, human_gate pending
    # Assert: retourne None
    ...
```

### Tools LangChain (`@tool`)
Chaque tool doit avoir un test qui vérifie le comportement nominal et les erreurs.

```python
def test_save_deliverable_writes_file(tmp_path):
    set_deliverable_context({"project_slug": "test", "team_id": "t1", "agent_id": "arch"})
    os.environ["AG_FLOW_ROOT"] = str(tmp_path)
    result = save_deliverable.invoke({"deliverable_key": "review", "content": "# Review"})
    assert "sauvegarde" in result

def test_save_deliverable_rejects_empty_content():
    result = save_deliverable.invoke({"deliverable_key": "x", "content": ""})
    assert "Erreur" in result
```

### Récursivité
Pour chaque méthode récursive, tester :

| Cas | Quoi vérifier |
|-----|--------------|
| Profondeur 0 | Cas d'arrêt immédiat (workflow inexistant, phase null) |
| Profondeur 1 | Un seul niveau de récursion |
| Profondeur max | Retourne l'erreur de profondeur, pas de stack overflow |
| Données manquantes | workflow supprimé, phase orpheline |

```python
async def test_db_get_current_position_depth_limit():
    # Setup: chaîne circulaire workflow A → B → A
    result = await db_get_current_position(workflow_a_id)
    assert "Profondeur max" in result.get("error", "")
```

## Ce qu'on ne teste PAS

- **Logs** : `logger.info(...)`, `logger.warning(...)` — pas de valeur à tester
- **Imports lazy** : `from X import Y` dans les fonctions — c'est de l'infrastructure
- **Code de glue** : fonctions qui ne font que passer des paramètres sans logique
- **Templates/prompts markdown** : le contenu des fichiers `.md`
- **Configuration statique** : les constantes, les dicts de mapping

## Quand tester

### Nouveau module
Tests écrits avant ou en même temps que le code. Pas de merge sans tests.

### Bug fix
1. Écrire un test qui reproduit le bug (le test doit ÉCHOUER)
2. Fixer le bug
3. Le test passe
4. Le test reste pour toujours (test de régression)

### Refactor
Les tests existants doivent passer sans modification.
Si un test casse pendant un refactor, c'est que le refactor change le comportement → c'est pas un refactor.

### Modification d'un module existant
Lancer les tests du module AVANT de modifier.
S'ils passent → modifier → relancer.
S'ils ne passent pas → corriger les tests d'abord.

## Nommage des tests

```
test_{ce_qui_est_testé}_{condition}_{résultat_attendu}
```

Exemples :
- `test_db_get_phase_returns_none_when_not_found`
- `test_resolve_next_phase_advances_to_next_group`
- `test_dispatch_agent_rejects_unauthorized_agent`
- `test_save_deliverable_writes_file_at_correct_path`

## Structure des tests

```
hitl/tests/
    test_analysis_service.py
    test_hitl_service.py
    test_rag_service.py
    test_workflow_service.py
    ...
```

Un fichier de test par module de service. Les fixtures partagées dans `conftest.py`.

## Outils

- **pytest** : framework de test
- **pytest-asyncio** : pour les tests async
- **unittest.mock** / **pytest-mock** : pour les mocks
- **tmp_path** (fixture pytest) : pour les fichiers temporaires
- **Qodo** : pour générer des tests unitaires quand disponible

## Commandes

```bash
# Tous les tests
docker compose exec langgraph-api python -m pytest

# Un module spécifique
docker compose exec langgraph-api python -m pytest tests/test_analysis_service.py -v

# Avec couverture
docker compose exec langgraph-api python -m pytest --cov=services --cov-report=term-missing

# Stop au premier échec
docker compose exec langgraph-api python -m pytest -x -v
```
