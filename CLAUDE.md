# agflow.docker — Instructions Claude Code

## Projet

Plateforme d'instanciation d'agents IA packagés en Docker (claude-code, aider, codex, gemini, goose, mistral, open-code). Panneau d'administration en 7 modules (M0 Secrets, M1 Dockerfiles, M2 Rôles, M3 Catalogues MCP+Skills, M4 Composition, M5 API publique, M6 Supervision). Spec complète : `specs/home.md`.

**Standard de qualité** : code propre et bien fait, jamais la rapidité au détriment de la rigueur. Pas de raccourcis, pas de "c'est pas grave", pas de "on simplifiera plus tard". Chaque tâche est faite correctement ou pas du tout.

**Pas de quick-and-dirty, JAMAIS.** Quand tu présentes des options de design, ne propose PAS d'option "quick & dirty" / "hardcode" / "wire-it-up-and-clean-later". On fait toujours propre, tant pis pour l'effort. Si tu sens qu'une tâche est déraisonnable (>3 mois, scope qui explose, dépendance hors d'atteinte), **alerte explicitement l'utilisateur** plutôt que de proposer un compromis dégradé. L'utilisateur préfère qu'on découpe le chantier et qu'on en fasse correctement la part qu'on prend, plutôt que tout faire à moitié.

## Stack technique

- **Backend** : Python 3.12 + FastAPI + asyncpg (**pas SQLAlchemy**) + structlog JSON + pytest
- **Frontend** : Vite + React 18 + TypeScript strict + react-router-dom + TanStack Query + Tailwind + shadcn/ui + i18next + Vitest
- **BDD** : PostgreSQL 16 + pgcrypto (secrets) — source de vérité unique
- **MOM** : Redis Streams (`redis.asyncio`) avec consumer groups — bus central de toutes les comms agents
- **Docker runtime** : aiodocker (pas de subprocess)
- **Reverse proxy prod** : Caddy (SSL géré par Cloudflare Tunnel en front)
- **Registre externe MCP** : `https://mcp.yoops.org/api/v1`
- **Observabilité** : Loki + Grafana sur LXC 116 (`agflow-logs`), exposé sur `https://log.yoops.org` via Cloudflare tunnel, auth SSO Keycloak (client `grafana` du realm `yoops`). Collecte via Grafana Alloy déployé sur tous les LXC actifs (Docker socket + journald). Rétention 7 jours. Config dans `infra/logs-stack/` (stack centrale) + `infra/alloy-agent/` (collecteur).

## Dev & cible

- **Développement** : local Windows (uv + node), tests connectés à l'infra LXC 201 (Postgres/Redis hébergés sur `192.168.10.158`)
- **Intégration / cible MVP** : LXC 201 (`agflow-docker-test`, 192.168.10.158) — Docker 29.4 + Compose v5.1 déjà installés
- **Stack logs** : LXC 116 (`agflow-logs`) — Loki + Grafana + Alloy, à provisionner via `scripts/infra/00-create-lxc.sh 116 agflow-logs` puis `infra/logs-stack/`
- **Prod future** : à définir quand le MVP vertical sera validé

## Commandes essentielles

```bash
# Infra dépendances (Postgres + Redis) sur LXC 201
ssh pve "pct exec 201 -- bash -c 'cd /root/agflow.docker && docker compose up -d'"

# Backend local (Windows)
cd backend && uv sync
cd backend && uv run uvicorn agflow.main:app --reload    # :8000
cd backend && uv run pytest -v                            # Tests Python
cd backend && uv run ruff check src/ tests/               # Lint
cd backend && uv run ruff format src/ tests/              # Format

# Frontend local (Windows)
cd frontend && npm install
cd frontend && npm run dev                                # :5173 avec proxy /api -> :8000
cd frontend && npm test                                   # Vitest
cd frontend && npx tsc --noEmit                           # TS strict check
cd frontend && npm run lint                               # ESLint
cd frontend && npm run format                             # Prettier

# Migrations DB
cd backend && uv run python -m agflow.db.migrations       # Applique migrations en attente

# Build & déploiement LXC 201
./scripts/deploy.sh                                       # Build images + push + compose up -d
```

## Layout du code

```
agflow.docker/
├── backend/
│   ├── pyproject.toml
│   ├── src/agflow/
│   │   ├── main.py              # FastAPI app + lifespan
│   │   ├── config.py            # Pydantic Settings
│   │   ├── logging_setup.py     # structlog JSON
│   │   ├── api/                 # Routers FastAPI
│   │   │   ├── health.py
│   │   │   ├── admin/           # Endpoints /api/admin/*
│   │   │   └── public/          # Endpoints /api/v1/*   (phases futures)
│   │   ├── auth/                # JWT + dépendances FastAPI
│   │   ├── db/                  # asyncpg pool + migrations runner
│   │   ├── docker/              # aiodocker wrappers           (phases futures)
│   │   ├── mom/                 # Redis Streams producer/consumer (phases futures)
│   │   ├── services/            # Logique métier                (phases futures)
│   │   └── schemas/             # DTOs Pydantic
│   ├── migrations/              # SQL bruts numérotés (001_*.sql, 002_*.sql…)
│   └── tests/
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
│       ├── pages/               # 1 page par module admin
│       ├── components/          # Composants réutilisables (dont StatusIndicator)
│       ├── hooks/
│       ├── lib/                 # api client, i18n
│       └── i18n/                # fr.json, en.json
├── docs/
│   ├── patterns/                # Design patterns (ref transversale)
│   ├── python-dev-rules.md      # Règles Python SOLID
│   ├── tests-python.md          # Couverture tests
│   ├── sonarQube.md             # Qualité code
│   └── superpowers/plans/       # Plans de développement exécutés
├── specs/
│   ├── home.md                  # Spec produit complète (541 lignes, 7 modules)
│   └── plans/                   # Plans techniques (brainstorm, archi)
├── scripts/
│   ├── infra/                   # LXC Proxmox setup (00-create-lxc.sh, 01-install-docker.sh)
│   └── deploy.sh                # Déploiement LXC 201
├── docker-compose.yml           # Dev : postgres + redis (exécuté sur LXC 201)
└── docker-compose.prod.yml      # Prod : stack complète
```

## Conventions de code

### Python (backend)
- Python 3.12+, async/await partout
- **Pas de SQLAlchemy** — asyncpg direct avec helpers `fetch_one` / `fetch_all` / `execute` dans `db/pool.py`
- Pydantic v2 pour les DTOs, Pydantic Settings pour la config
- Logs structurés via `structlog.get_logger(__name__)` — **jamais** `print()`
- `type` hints partout, `from __future__ import annotations` en tête de fichier
- Fichiers max 300 lignes ; classes SRP ; méthodes 5-15 lignes
- Règles détaillées : `@docs/python-dev-rules.md`
- Règles tests : `@docs/tests-python.md`

### TypeScript (frontend)
- `strict: true`, `noUncheckedIndexedAccess: true`
- Composants fonctionnels + hooks, pas de classes
- React Query pour tout appel API, pas de `useEffect + fetch` direct
- i18n sur **tous** les labels affichés — `useTranslation()`, jamais de string brute
- Fichiers max 300 lignes
- Props typées via `interface`, exports nommés

### Base de données
- Migrations = fichiers SQL numérotés dans `backend/migrations/` (ex: `001_init.sql`, `002_secrets.sql`)
- Schéma géré en SQL brut, pas d'ORM
- Extensions requises : `pgcrypto` (secrets), `uuid-ossp` (ids)
- Toute nouvelle table → migration SQL + test de migration

### Tests
- **Backend** : pytest + pytest-asyncio ; fixture `client` (TestClient httpx)
- **Frontend** : Vitest + React Testing Library ; `describe`/`it`, pas de `test`
- **TDD** : test rouge → impl → test vert → commit
- Couverture minimale par zone : voir `docs/tests-python.md`

### Indicateurs visuels secrets (convention spec)
Partout où un secret est référencé par nom de variable d'env, afficher son statut via le composant `StatusIndicator` :
- 🔴 Rouge : variable manquante (non déclarée dans les secrets)
- 🟠 Orange : variable présente mais valeur vide
- 🟢 Vert : variable présente et remplie

## Règles de workflow

### Cycle de l'architecte
**Cadrer → Comprendre → Planifier → Agir.** L'utilisateur est architecte. Une question n'est pas une commande d'exécution. Une discussion n'est pas un feu vert. Ne JAMAIS sauter d'étape.

### Livraison
- Ne livre **jamais** le code ni en test ni sur git sans demande explicite
- Ne modifie pas `.env` sauf si demandé
- Commit messages en français, format conventionnel (`feat:`, `fix:`, `chore:`, `docs:`, `test:`…)

### Vérification avant validation
Avant de déclarer une tâche terminée, **toutes** ces étapes sont obligatoires :
1. Le code s'exécute sans erreur (lint + build)
2. Le cas nominal fonctionne (test unitaire ou manuel)
3. Les imports ajoutés existent réellement
4. Pas de régression sur les fichiers modifiés
5. Si modification frontend : la page charge sans erreur console

### Discipline d'exécution
- Exécute directement, ne décris pas ce que tu vas faire — fais-le
- N'explique pas les étapes intermédiaires. Rapporte uniquement le résultat final
- Termine TOUTES les étapes d'un plan avant de faire un résumé
- Pas de raccourci "pour simplifier"
- Si tu rencontres un problème, signale-le et propose une solution — ne l'ignore pas silencieusement

## Outils Claude Code

### Context7 — documentation live
**Quand** : avant d'écrire du code qui utilise FastAPI, Pydantic v2, asyncpg, aiodocker, redis-py, React Query, Vite, React Router, i18next, Tailwind, etc. Les API évoluent, ne te fie pas à ta mémoire.

### Serena — navigation sémantique
**Quand** : avant un refactor, pour comprendre les dépendances entre modules, ou pour trouver tous les usages d'une fonction/classe.

### Superpowers skills
- `writing-plans` : rédiger un plan d'implémentation TDD avant de coder
- `executing-plans` / `subagent-driven-development` : exécuter un plan tâche par tâche
- `systematic-debugging` : méthode pour debug un bug ou test qui échoue
- `test-driven-development` : discipline TDD rigoureuse
- `brainstorming` : explorer le design avant d'écrire quoi que ce soit
- `verification-before-completion` : vérifier que le travail est réellement fini avant de le dire

### /review
**Quand** : avant de présenter un changement multi-fichiers (>3 fichiers ou >100 lignes).

### /commit
**Quand** : quand l'utilisateur demande explicitement de committer. Format français conventionnel.

## Auto-amélioration

Quand tu fais une erreur ou que l'utilisateur te corrige :
- Ajoute une leçon dans `LESSONS.md`
- Format : `- [module] description courte de l'erreur et de la bonne pratique`
- Relis `@LESSONS.md` en début de tâche qui touche un module mentionné
- Ne dépasse pas 50 lignes — consolide les leçons similaires

## Notifications de skills

Quand tu invoques une skill via l'outil Skill, affiche systématiquement un marqueur visuel **avant** d'exécuter :

> **`🟢 SKILL`** → _nom-de-la-skill_ — raison en une phrase
