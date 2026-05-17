# Harpocrate — Instructions Claude Code

## Projet

Coffre-fort de secrets E2E (end-to-end encrypted) self-hosted. **Le serveur ne déchiffre jamais les valeurs des secrets** — tout le chiffrement/déchiffrement se fait côté client (navigateur ou SDK). Authentification OIDC (Keycloak en PKCE public) avec mode break-glass admin local. Backups chiffrés `age`, réplication via Patroni (HA Postgres) et MQTT Mosquitto (multi-instances applicative).

Documentation complète et à jour : `harpocrate.wiki/docs/fr/` (FR) et `harpocrate.wiki/docs/en/` (EN). Specs d'implémentation lot par lot : `docs/specs/` (LOT_00 à LOT_22, 27 fichiers).

**Standard de qualité** : code propre et bien fait, jamais la rapidité au détriment de la rigueur. Pas de raccourcis, pas de "c'est pas grave", pas de "on simplifiera plus tard". Chaque tâche est faite correctement ou pas du tout.

**Pas de quick-and-dirty, JAMAIS.** Quand tu présentes des options de design, ne propose PAS d'option "quick & dirty" / "hardcode" / "wire-it-up-and-clean-later". On fait toujours propre, tant pis pour l'effort. Si tu sens qu'une tâche est déraisonnable (>3 mois, scope qui explose, dépendance hors d'atteinte), **alerte explicitement l'utilisateur** plutôt que de proposer un compromis dégradé. L'utilisateur préfère qu'on découpe le chantier et qu'on en fasse correctement la part qu'on prend, plutôt que tout faire à moitié.

## Stack technique

- **Backend** : Python 3.12 + FastAPI + asyncpg (**pas SQLAlchemy**) + structlog JSON + pytest + pytest-asyncio. Géré via **uv** (pas pip + requirements.txt).
- **Frontend** : Vite + React 18 + TypeScript strict + react-router-dom + TanStack Query + **Mantine** (UI) + Zustand (state global) + Zod (validation) + react-i18next (FR/EN) + Vitest + RJSF (secrets typés).
- **BDD** : PostgreSQL 16 + extensions `pgcrypto`, `uuid-ossp`. Source de vérité unique. Coordination cluster via `LISTEN/NOTIFY` + advisory locks (pas de Redis, pas de cache distribué).
- **Crypto client** : Argon2id (`hash-wasm`), AES-256-GCM + RSA-OAEP-SHA256 (WebCrypto natif), BIP-39 (phrase de récupération 24 mots).
- **Crypto serveur** : `cryptography` (PyCA). Token API key `hrpv_*` (8 segments, HMAC-SHA256 tronqué). Backups chiffrés `age` (clé générée par `age_keygen.py`, stockée en DB).
- **Auth** : Keycloak OIDC en **client public PKCE** (pas de client_secret backend) + auth admin locale break-glass (`HARPOCRATE_ADMIN_LOCAL_*`).
- **Reverse proxy** : nginx embarqué dans le conteneur frontend (cert auto-signé en dev sur `:8443`). En prod, Cloudflare Tunnel ou Caddy/Nginx externe terminent TLS.
- **Réplication** : Patroni + etcd (HA Postgres) / Eclipse Mosquitto + `aiomqtt` (sync multi-instances applicative). **Pas EMQX.**
- **Observabilité** : structlog JSON. Stack Loki/Grafana via Grafana Alloy (collecteur dans `infra/alloy-agent/`) — optionnelle, pas un prérequis.

## Dev & cible

- **Développement** : local Windows (uv + node) ou Linux. Tests d'intégration backend connectés à un Postgres local ou LXC Proxmox.
- **Cible de déploiement** : LXC Proxmox Docker-ready, ou n'importe quelle machine Linux avec Docker ≥ 24 et Compose v2. Procédures :
  - **Dev** : `./dev-deploy.sh` (build local + compose up).
  - **Prod** : `scripts/setup.sh` (init LXC + .env) puis `scripts/refresh.sh` (pull GHCR + compose up).
- **Test d'intégration LXC** : `scripts/run-test.sh` (création LXC + clone + déploiement + smoke), procédure complète dans `docs/test.md`.

## Commandes essentielles

```bash
# Backend local
cd backend && uv sync
cd backend && uv run uvicorn app.main:app --reload         # :8000
cd backend && uv run pytest -v                             # Tests Python
cd backend && uv run ruff check app/ tests/                # Lint
cd backend && uv run ruff format app/ tests/               # Format

# Frontend local
cd frontend && npm install
cd frontend && npm run dev                                  # :5173, proxy /v1 -> :8000
cd frontend && npm test                                     # Vitest
cd frontend && npx tsc --noEmit                             # TS strict check
cd frontend && npm run lint                                 # ESLint
cd frontend && npm run format                               # Prettier

# Migrations DB : appliquées automatiquement au boot du backend
# via le lifespan FastAPI (app/db/migrations.py). Pas de CLI dédiée.

# Stack complète en dev (build local + Postgres)
./dev-deploy.sh                                             # :8443 HTTPS auto-signé

# Stack complète en prod (pull GHCR sur LXC)
ssh pve "pct exec <ctid> -- bash -c 'cd /opt/harpocrate && ./refresh.sh'"

# Test d'intégration LXC depuis le poste local
./scripts/run-test.sh                                       # config par défaut
CLEANUP=1 ./scripts/run-test.sh                             # purge le LXC après tests
```

> **Pas de CLI `python -m harpocrate ...`** — aucun `__main__.py` n'est défini dans `backend/app/`. Toutes les opérations (backup, snapshot, maintenance, restore, quarantaine) passent par l'UI admin ou par appel HTTP direct aux endpoints `/v1/admin/...`.

## Layout du code

```
harpocrate/
├── backend/
│   ├── pyproject.toml          # uv
│   ├── app/
│   │   ├── main.py             # FastAPI app + lifespan
│   │   ├── api/v1/             # Endpoints publics + admin_*
│   │   ├── core/               # Pydantic Settings, security, api_key_token, cluster_sync
│   │   ├── db/                 # Pool asyncpg, repositories, migrations runner
│   │   ├── middleware/         # cluster_coherence, log_requests
│   │   ├── models/             # Pydantic schemas + DB models
│   │   └── services/           # ~40 services (auth, secrets, wallets, backup, replication...)
│   ├── migrations/             # SQL numérotés 000_*.sql à 031_*.sql + apply_migrations.py
│   └── tests/
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── nginx.conf              # Image Docker : sert SPA + proxy /v1/ sur :8443 (cert auto-signé)
│   └── src/
│       ├── pages/              # Pages React (route-level)
│       ├── components/         # Composants réutilisables
│       ├── crypto/             # Argon2id, AES-GCM, RSA-OAEP, BIP-39, helpers
│       ├── hooks/
│       ├── i18n/               # fr.json, en.json
│       ├── lib/                # api-client, oidc, query
│       ├── schemas/            # Zod
│       └── stores/             # Zustand (session, crypto)
├── sdk-python/                 # SDK officiel (publié `harpocrate` sur PyPI, v0.6.0)
├── sdk-typescript/, sdk-javascript/, sdk-go/, sdk-rust/, sdk-csharp/  # Squelettes
├── cli-bash/                   # harpocrate-cli + harpocrate-gen
├── infra/
│   ├── patroni/                # install-patroni.sh + templates + callbacks (DNS dnsmasq)
│   ├── etcd/                   # install-etcd.sh + service
│   ├── mosquitto/              # Eclipse Mosquitto (broker MQTT pour sync multi-instances)
│   └── alloy-agent/            # Grafana Alloy (collecteur logs vers Loki)
├── scripts/
│   ├── setup.sh                # Pull docker-compose.yml + .env sur LXC (init prod)
│   ├── refresh.sh              # Pull GHCR + compose up -d (prod)
│   ├── run-test.sh, test-create-lxc.sh, destroy-test.sh
│   └── install-alloy.sh
├── dev-deploy.sh               # Build local + compose up (dev)
├── db/init/                    # 01-extensions.sql, 02-replication-hba.sh
├── docker-compose.yml          # Prod (pull images GHCR)
├── docker-compose-dev.yml      # Dev (build local)
├── docker-compose.cluster.yml  # Ajoute Mosquitto pour multi-instances
├── docs/specs/                 # LOT_00 à LOT_22 (briefs d'implémentation, 27 fichiers)
└── harpocrate.wiki/            # Wiki bilingue FR/EN (sous-module Git)
```

## Conventions de code

### Python (backend)
- Python 3.12+, async/await partout.
- **Pas de SQLAlchemy** — asyncpg direct avec helpers dans `app/db/pool.py` et repositories dans `app/db/repositories/`.
- **Pydantic v2** pour les DTOs, **Pydantic Settings** pour la config (`core/config.py`).
- Logs structurés via `structlog.get_logger(__name__)` — **jamais** `print()` ni `logging` brut.
- `from __future__ import annotations` en tête de fichier, type hints partout.
- Fichiers max 300 lignes ; classes SRP ; méthodes 5-15 lignes.
- Transactions explicites pour les opérations multi-tables (`async with conn.transaction():`).
- `SELECT FOR UPDATE` pour les opérations critiques concurrentes.
- Pour les endpoints API key : utiliser la dépendance `require_api_key` (ne lit JAMAIS `caller.decryption_key_b64` côté serveur — la dkey est juste parsée pour traverser le format).
- Pour les endpoints admin : `require_admin` (vérifie le claim `realm_access.roles` contre `HARPOCRATE_ADMIN_ROLE_NAME`).

### TypeScript (frontend)
- `strict: true`, `noUncheckedIndexedAccess: true`.
- Composants fonctionnels + hooks, pas de classes.
- **TanStack Query** pour tout appel API, pas de `useEffect + fetch` direct.
- **Mantine** pour les composants UI (pas Tailwind/shadcn).
- **Zustand** pour le state global (session, crypto). **Zod** pour la validation des réponses API.
- **react-i18next** sur **tous** les labels affichés (`useTranslation()`), jamais de string brute.
- Fichiers max 300 lignes. Props typées via `interface`, exports nommés.
- **Crypto** : utiliser les helpers de `src/crypto/` (Argon2id via `hash-wasm`, AES-GCM/RSA-OAEP via WebCrypto natif). Jamais de KDF maison.
- **Sécurité UI** : ne jamais afficher une valeur de secret dans un log console ou une notification. Toujours masquer par défaut, dévoiler sur action explicite.

### Base de données
- Migrations = fichiers SQL numérotés dans `backend/migrations/` (ex: `001_schema_initial.sql`, `028_pairing_sessions.sql`). Apply runner = `backend/migrations/apply_migrations.py`, exécuté au lifespan FastAPI.
- Schéma géré en SQL brut, pas d'ORM.
- Extensions requises : `pgcrypto`, `uuid-ossp` (init dans `db/init/01-extensions.sql`).
- Toute nouvelle table → migration SQL numérotée + test de migration (`backend/tests/migrations/`).

### Tests
- **Backend** : pytest + pytest-asyncio ; fixture `client` (TestClient httpx) ; DB Postgres de test (pas de mock pour les tests d'intégration).
- **Frontend** : Vitest + React Testing Library ; `describe`/`it`, pas de `test`.
- **TDD** : test rouge → impl → test vert → commit. Discipline rigoureuse, surtout pour le crypto et l'audit.
- Couverture minimale par zone : voir les briefs `docs/specs/LOT_*.md` (chaque lot liste ses critères de succès).

## Règles de workflow

### Cycle de l'architecte
**Cadrer → Comprendre → Planifier → Agir.** L'utilisateur est architecte. Une question n'est pas une commande d'exécution. Une discussion n'est pas un feu vert. Ne JAMAIS sauter d'étape.

### Livraison
- Ne livre **jamais** le code ni en test ni sur git sans demande explicite.
- Ne modifie pas `.env` sauf si demandé.
- Commit messages en français, format conventionnel (`feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:`…).
- Pour le wiki : `harpocrate.wiki/` est un sous-module Git séparé (`https://github.com/gaelgael5/harpocrate.wiki.git`, branche `master`). Commit et push s'y font indépendamment du repo principal.

### Vérification avant validation
Avant de déclarer une tâche terminée, **toutes** ces étapes sont obligatoires :
1. Le code s'exécute sans erreur (lint + build : `ruff check`, `tsc --noEmit`).
2. Le cas nominal fonctionne (test unitaire ou test manuel via curl/UI).
3. Les imports ajoutés existent réellement.
4. Pas de régression sur les fichiers modifiés (tests existants passent).
5. Si modification frontend : la page charge sans erreur console.
6. Si modification crypto : tester aussi le déchiffrement (round-trip), pas seulement le chiffrement.
7. Si modification migration : tester l'application sur DB existante ET sur DB vierge.

### Discipline d'exécution
- Exécute directement, ne décris pas ce que tu vas faire — fais-le.
- N'explique pas les étapes intermédiaires. Rapporte uniquement le résultat final.
- Termine TOUTES les étapes d'un plan avant de faire un résumé.
- Pas de raccourci "pour simplifier".
- Si tu rencontres un problème, signale-le et propose une solution — ne l'ignore pas silencieusement.

### Sécurité — règles dures
- **Jamais** de valeur de secret dans les logs (le middleware `log_requests` masque le body, ne le contourne jamais).
- **Jamais** de passphrase, phrase de récupération 24 mots, ou clé privée RSA stockée en clair en DB.
- **Toujours** valider les entrées via Pydantic avant traitement.
- **Toujours** vérifier les permissions avant accès aux données (dépendances `require_*` côté API).
- **API keys** : aujourd'hui le SDK envoie le token complet dans le header `Authorization` (`sdk-python/harpocrate/http.py:73`). La conception cible — split-token côté SDK — est sur la roadmap (cf. wiki `philosophy_e2e-model.md`). Tant qu'elle n'est pas faite, ne pas activer le logging des headers `Authorization` côté reverse-proxy.

## Outils Claude Code

### Context7 — documentation live
**Quand** : avant d'écrire du code qui utilise FastAPI, Pydantic v2, asyncpg, aiomqtt, aiohttp, React, TanStack Query, Vite, Mantine, react-i18next, RJSF, Zod, etc. Les API évoluent, ne te fie pas à ta mémoire.

### Serena / Grep / Glob — navigation sémantique
**Quand** : avant un refactor, pour comprendre les dépendances entre modules, ou pour trouver tous les usages d'une fonction/classe/endpoint.

### Superpowers skills
- `writing-plans` : rédiger un plan d'implémentation TDD avant de coder.
- `executing-plans` / `subagent-driven-development` : exécuter un plan tâche par tâche.
- `systematic-debugging` : méthode pour debug un bug ou test qui échoue.
- `test-driven-development` : discipline TDD rigoureuse.
- `brainstorming` : explorer le design avant d'écrire quoi que ce soit.
- `verification-before-completion` : vérifier que le travail est réellement fini avant de le dire.

### /review
**Quand** : avant de présenter un changement multi-fichiers (>3 fichiers ou >100 lignes).

### /commit
**Quand** : quand l'utilisateur demande explicitement de committer. Format français conventionnel.

## Auto-amélioration

Quand tu fais une erreur ou que l'utilisateur te corrige :
- Ajoute une leçon dans `LESSONS.md` à la racine du repo.
- Format : `- [module] description courte de l'erreur et de la bonne pratique`.
- Relis `@LESSONS.md` en début de tâche qui touche un module mentionné.
- Ne dépasse pas 50 lignes — consolide les leçons similaires.

## Notifications de skills

Quand tu invoques une skill via l'outil Skill, affiche systématiquement un marqueur visuel **avant** d'exécuter :

> **`🟢 SKILL`** → _nom-de-la-skill_ — raison en une phrase
