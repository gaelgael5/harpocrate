# Fragment — Python (backend, `sdk-python/`)

> Source : globals › « Fichier d'instructions — spécificités Python » (révision 2026-09-02).
> Déclencheur : avant de modifier un fichier `.py`. Lire aussi `20_tests.md` avant d'écrire un test.

### Conventions Python

- Python 3.12+, async/await partout — **jamais** de `subprocess.run` ni d'I/O bloquant dans
  un chemin asynchrone
- pydantic v2, `extra="forbid"` sur tous les modèles de configuration
- `structlog.get_logger(__name__)` — **jamais** `print()`. Un secret ne se déballe qu'au
  point d'injection
- `from __future__ import annotations` en tête de fichier, annotations de type partout
- Fichiers max 300 lignes ; une classe = une responsabilité ; méthodes de 5 à 15 lignes
- Entrées utilisateur validées par regex stricte AVANT tout usage en chemin, identifiant ou
  nom d'hôte — la concaténation de chaînes est une faute

### Nommage Python

| Élément | Convention |
|---|---|
| Fichiers, fonctions, variables | `snake_case` |
| Classes | `PascalCase` |
| Constantes | `UPPER_SNAKE` |
| Privé | préfixe `_` |

**Préfixer selon la SOURCE de la donnée** — c'est ce qui dit, au nom seul, ce qu'une
méthode touche et donc comment la tester :

| Préfixe | Ce que la méthode fait |
|---|---|
| `db_` | lit ou écrit en base |
| `file_` | lit ou écrit un fichier |
| `resolve_` | orchestre les deux, et décide |

Le nom dit ce que la fonction **fait**, pas comment : `resolve_agent_avatar()`, pas
`process()` ni `handle()`.

### Erreurs en Python

- **Aucun repli silencieux.** Une valeur par défaut qui masque une donnée manquante
  transforme un bug en comportement, et le symptôme apparaît loin de sa cause.
  `state.get("team_id", "team1")` est une faute ; exiger la donnée et lever sinon.
- **Aucun `except` nu ni `except: pass`.** Attraper une exception précise, journaliser le
  contexte, et relancer si l'appelant doit savoir.
- **Les erreurs se traitent à la frontière**, pas au milieu : la couche qui peut décider
  quoi faire les attrape, les autres les laissent passer.
- Aucune constante magique dans le code : une valeur qui décide se nomme.

## Spécifique Harpocrate

- **Paquet = `app`** (pas `src/<pkg>`) : `backend/app/`. Point d'entrée `app.main:app`.
- **asyncpg direct, jamais d'ORM.** Accès base dans `app/db/repositories/` (un module par
  agrégat) ; pool via `app/db/pool.py`. Dans ce dépôt, **le module de repository tient le
  rôle du préfixe `db_`** : une nouvelle lecture/écriture en base va dans le repository de
  l'agrégat, pas dans un service.
- **Toujours `settings.effective_db_dsn`**, jamais `settings.db_dsn`, pour toute connexion
  hors pool (LISTEN, `pg_dump`, `psql`…) — cf. `LESSONS.md` [db].
- **Ne jamais capturer le pool** dans une classe ou une closure longue durée :
  `pool = await db_pool.get_pool()` à chaque tick (le pool est recréé après un pairing).
- Processus externes : **uniquement `asyncio.create_subprocess_exec`**, exception assumée
  faute d'API Python équivalente — `pg_dump`, `age`, `age-keygen` (`services/backup.py`,
  `services/age_keygen.py`, `services/snapshot_scheduler.py`). Jamais `subprocess.run`,
  jamais `shell=True`.
- Endpoints : dépendance `require_api_key` pour les routes API key (ne lit **jamais**
  `caller.decryption_key_b64`), `require_admin` pour les routes admin. Rate limiting via
  `Depends(rate_limit_dep(...))` (`app/core/rate_limit.py`), **jamais** `@limiter.limit`
  de slowapi (casse les forward-refs sous `from __future__ import annotations`).
- Tout champ ajouté à une réponse doit être déclaré dans le DTO `response_model`
  (FastAPI filtre en silence le reste) et asserté dans un test sur `r.json()`.
- Dépendances : `cd backend && uv add <pkg>` puis commit de `pyproject.toml` + `uv.lock`.
  Le `Dockerfile` installe via `uv sync --frozen` : **jamais** de dépendance déclarée dans
  le Dockerfile.

### Écarts constatés avec le standard (à signaler, pas à propager ni à « corriger » d'office)

- `app/core/config.py` : `Settings` porte `extra="ignore"` (le standard exige `forbid`).
  Passer à `forbid` avec `env_file=".env"` ferait échouer le boot sur toute variable non
  préfixée du `.env` — décision à prendre par l'utilisateur, pas au passage.
- `mypy` est une dépendance dev mais **aucune configuration mypy** n'existe et la base n'a
  jamais été typée-vérifiée : ne pas présenter `mypy` comme une porte de validation tant que
  ce n'est pas décidé.
- Quelques `except Exception:` larges existent (`core/replication.py`, `api_key_auth.py`,
  `admin_pairing_exec.py`…) : ne pas en ajouter ; les réduire seulement dans une tâche dédiée.

## Commandes essentielles

```bash
cd backend && uv sync
cd backend && uv run uvicorn app.main:app --reload         # :8000
cd backend && uv run pytest -v
cd backend && uv run pytest tests/test_<module>.py -v
cd backend && uv run pytest -x -v                          # arrêt au premier échec
cd backend && uv run ruff check app/ tests/
cd backend && uv run ruff format app/ tests/
cd backend && uv run ruff format --check app/ tests/
```

`uv` n'est **pas installé** dans le devcontainer actuel : le signaler plutôt que de lancer
`pip` à la place.

## Pièges connus

**`extra="forbid"` n'est pas décoratif.** Sans lui, une clef de configuration mal orthographiée est ignorée en silence et le défaut s'applique — le symptôme apparaît en production, loin de sa cause.

**`from __future__ import annotations` change le sens des annotations** : elles deviennent des chaînes. Ce qui les lit à l'exécution — pydantic, certains décorateurs — doit pouvoir les résoudre ; un type importé sous `if TYPE_CHECKING:` ne le sera pas.

**`structlog` réserve la clef `event`** pour le message. `log.info("truc", event=x)` lève un `TypeError` **à l'exécution** et jamais au lint.

**Le formateur n'est pas le linter.** `ruff check` et `ruff format` sont deux commandes ; passer l'une ne dit rien de l'autre.

**Une violation de contrainte en base avorte la transaction entière** — voir `10_postgresql.md`.

## Part de checklist

- [ ] `ruff check` et `ruff format --check` passent sur le périmètre modifié
- [ ] Aucun I/O bloquant introduit dans un chemin asynchrone
- [ ] Les modèles de configuration ajoutés portent `extra="forbid"`
- [ ] Aucun repli silencieux, aucun `except` nu ajouté
- [ ] Les accès base ajoutés vivent dans un repository, et sont testés en conséquence
- [ ] Les entrées utilisateur nouvelles sont validées avant tout usage en chemin ou identifiant
- [ ] Tout champ de réponse ajouté est déclaré dans le DTO et asserté dans un test
