# Harpocrate — Instructions Claude Code

> Coffre-fort de secrets chiffré de bout en bout, self-hosted. **Infrastructure partagée** :
> tous les projets de la maison consomment Harpocrate ; Harpocrate ne dépend d'aucun d'eux
> (aucun couplage de source ni de runtime avec le portail devpod, docflow, ragflow ou un autre
> projet ag-flow).

> Généré depuis les standards globaux (docflow, workspace `globals`, bloc `documentation`).
> Génération : 2026-09-23. Mise à jour `--update` : 2026-09-29. Standards repris :
> STANDARD — Fichier d'instructions agent de projet : principes, invariants et recette de génération — 2026-09-26 (v42)
> Fichier d'instructions — spécificités Python — 2026-09-02
> Fichier d'instructions — spécificités TypeScript / frontend — 2026-09-02
> Fichier d'instructions — spécificités PostgreSQL — 2026-09-02
> Fichier d'instructions — Tests (agnostique) — 2026-09-25
> Fichier d'instructions — Observabilité et logs (agnostique) — 2026-09-02
> Fichier d'instructions — Contrats d'interface et documentation (agnostique) — 2026-09-09
> Fichier d'instructions — Commentaires de code (agnostique) — 2026-09-06
> Fichier d'instructions — Patrons de conception (agnostique) — 2026-09-02
> Fichier d'instructions — spécificités Secrets — 2026-09-02
> Fichier d'instructions — spécificités Authentification OIDC — 2026-09-02
> Fichier d'instructions — Script de déploiement sur machine de test (agnostique) — 2026-09-11
> Fichier d'instructions — Déclarer un service exposé au portail (annuaire, code TOTP) — 2026-09-16
> Déploiement et machines de test — leçons d'incidents réels — 2026-09-25
> Travail d'agent — leçons d'erreurs réelles — 2026-09-02
> STANDARD — Sécurité : secrets et coffres Harpocrate (modèle, IHM, résolution) — 2026-09-20
> STANDARD — Authentification OIDC & liaison d'identité — 2026-09-15
> Non retenu : Fichier d'instructions — Analyse statique et qualité (agnostique) — 2026-09-02
> (SonarCloud n'est pas encore actif — confirmé par l'utilisateur le 2026-09-24 ; l'article
> docflow « SonarQube Cloud — contrôle qualité du code » décrit la cible. À reprendre dès son
> activation).
> Mise à jour par `--update` : ne reporter que le delta depuis cette date.

**Colibri** commence systématiquement tes réponses par 🎺

**Ce fichier prime sur ton comportement par défaut.** Il est lu en tête de chaque session ;
ses règles sont impératives. Une consigne ambiguë ici est un bug : la signaler.

## mcp
Tu es connecté au MCP du portail devpod (`dev.yoops.org`) via le serveur `claude-code`
(déclaré dans `.mcp.json`, non versionné).

## Backlog
Le backlog est dans le workspace docflow `harpocrate`, bloc `backlog`. **Avant de prendre, de
passer en cours ou de clore une tâche**, lis `ia_instructions/00_backlog.md` (bloc intégral).
Invariants : statuts découverts par introspection, jamais écrits de mémoire ; une tâche passe
« en cours » AVANT de toucher au code et « en revue » à la fin ; le backlog fait foi, pas ta
mémoire ; une question ne bloque pas la file ; on ne s'arrête que pour l'une des quatre raisons
nommées.

## Recherche — le RAG d'abord

**Toute recherche documentaire passe EN PRIORITÉ par le RAG**, via les primitives `rag__*`
de la gateway MCP. Le corpus y est déjà indexé et enrichi : c'est plus rapide et plus
complet qu'un `grep` sur un dépôt, et ça couvre la doc Docflow que le système de fichiers
ne contient pas.

Méthode (namespace `rag`) :

1. **`rag__list_workspaces`** — **à appeler en premier** : donne les slugs interrogeables
   et le scope de la clef. Corpus utiles : `harpocrate-docs` (ce projet),
   `globals-docs` (savoir cross-projet), et un `<voisin>-docs` par projet voisin.
2. **`rag__rag_search(workspace, query, top_k, min_score, scope)`** — recherche
   **sémantique** : question en langue naturelle, concept, intention. C'est le point
   d'entrée par défaut. `min_score` 0.3 par défaut ; monter à 0.5–0.7 pour une question
   précise. `scope='enriched_only'` pour n'interroger que les résumés, listes de fonctions
   et graphes de dépendances.
3. **`rag__search_files(workspace, pattern, mode)`** — recherche **littérale** quand on
   cherche un identifiant exact (nom de fonction, constante, chaîne) : `mode='exact'` par
   défaut (tokens entiers, ne trouve pas les sous-chaînes), `'substring'` pour un fragment,
   `'regex'` en dernier recours (lent).

Ordre de repli, jamais l'inverse : RAG → si le corpus ne répond pas (sujet non indexé, code
modifié depuis l'indexation) → outils locaux (Grep/Glob/Read) ou sous-agent Explore. Le RAG
lit le contenu **indexé**, jamais les fichiers live : pour vérifier l'état courant d'un
fichier qu'on vient de modifier, lire le fichier.

Ce que tu apprends de neuf s'écrit en article de documentation — c'est ce qui alimente le
RAG pour les prochains agents.

**Le RAG muet n'est pas une réponse.** Le corpus ne couvre que ce qu'on y a écrit : une
route d'interface, un motif d'URL, un flag de CLI peuvent en être absents sans que rien ne
le signale — l'absence ressemble à une réponse vide, pas à une lacune. Le repli n'est donc
jamais « la documentation ne le dit pas », c'est **aller lire l'artefact réel** : le bundle
du front pour une route, `--help` pour un flag, l'API pour une forme de réponse, le fichier
lui-même pour son état courant.

Rendre un identifiant brut, un chemin approximatif ou un « je ne peux pas savoir » alors que
l'artefact est joignable, c'est renvoyer le travail à l'utilisateur. Chercher d'abord,
répondre ensuite — et si la recherche échoue vraiment, dire ce qui a été tenté.

> Specs, plans, exploitation et audits vivent dans docflow `harpocrate › documentation` (indexé
> dans `harpocrate-docs`), plus dans le dépôt. RAG muet → `doc__search_documents(q)` filtré sur
> `harpocrate`, puis `doc__get_document` ; un `grep` local ne couvre que le code.

## Quand charger un fragment

Ces fichiers ne sont PAS chargés d'office. Chacun a son déclencheur : quand il se produit,
lire le fichier AVANT d'écrire quoi que ce soit — pas après, pas « si ça semble utile ».

| Tu t'apprêtes à… | Lis d'abord |
|---|---|
| prendre, passer en cours ou clore une tâche du backlog | `ia_instructions/00_backlog.md` |
| ouvrir la session, voir `[TCHAT] nouveau message`, appeler ou répondre à un agent | `ia_instructions/00_tchat.md` |
| committer ou pousser pour livrer, déployer ou tester sur une machine de test, ou recevoir / rendre une ressource | `ia_instructions/00_machines_et_livraison.md` et `ia_instructions/tests_and_ressources.md` |
| modifier un fichier `.py` (backend, `sdk-python/`) | docflow « Fragment — Python » `ea520edf-962d-4edc-80e2-0ae049b86a2f` |
| modifier un fichier sous `frontend/` | docflow « Fragment — TypeScript / frontend » `cdd2fc80-7a46-4a47-bf96-fba21ecaf0bf` |
| écrire ou modifier une migration, une requête SQL, ou un fichier de `backend/app/db/` | docflow « Fragment — PostgreSQL » `ac055cea-6cf6-48f4-8d1d-42bde70a502a` |
| écrire ou modifier un test, ou corriger un bug | docflow « Fragment — Tests » `9d52c6ae-9eb0-415c-8fec-711821fee6c6` |
| écrire ou modifier du code (`.py`, `.ts`, `.tsx`, `.sh`, `.sql`) | docflow « Fragment — Commentaires de code » `186e11e6-9d6a-45b2-807a-26142f8c4f44` |
| ajouter ou modifier un appel de log, un middleware HTTP, `infra/alloy-agent/` | docflow « Fragment — Observabilité et logs » `275b86e4-51d5-4a23-8ca4-cd9de560f58b` |
| modifier une route `backend/app/api/`, un DTO `models/api/`, un SDK, `cli-bash/`, `docs/vault.md`, le protocole MQTT, un webhook | docflow « Fragment — Contrats d'interface et documentation » `68799bc2-3e9c-4394-a2ed-c99aecad1f9c` |
| toucher à une valeur sensible, `.env.example`, `core/config.py`, `core/api_key_*`, un Dockerfile ou un compose | docflow « Fragment — Secrets » `7e889340-cdc6-441c-a60c-bbbe65a64404` |
| modifier l'authentification (`core/security.py`, `admin_auth.py`, `api/v1/auth*.py`, `identity_*`, `frontend/src/lib/oidc.ts`) | docflow « Fragment — Authentification OIDC » `22284d2d-a1d5-41c0-a3cc-c87bcf3208e3` |
| modifier `dev-deploy.sh`, `scripts/`, un compose, `nginx.conf` — ou déployer / diagnostiquer sur `test1` | docflow « Fragment — Déploiement » `126aa026-b42c-4681-be49-844a66739bcf` |
| introduire une abstraction (classe de base, factory, stratégie, bus…) ou proposer un refactor structurel | docflow « Fragment — Patrons de conception » `a9a5f018-d256-4492-b247-ee3af806d76b` |

Un fragment introuvable se **signale** ; on ne devine pas ce qu'il contenait.

> **Remise en forme (quota, 2026-09-29)** : « Backlog », « Tchat agents », « Machines de test »
> et « Livrer sur une machine de test » sont ici en synthèse, texte intégral au mot près dans
> `ia_instructions/00_*.md`. Ne pas les remettre en clair : le plafond ne se relève pas.

### ⚠ Divergence assumée vs le standard — fragments dans docflow (décision du 2026-09-29)
Les fragments par technologie vivent dans docflow, pas dans `ia_instructions/` : les lire par
`doc__get_document(workspace_slug="harpocrate", doc_id=<id>)` (version courante, pas un extrait
RAG) ; MCP indisponible → **s'arrêter et le signaler**. Ne jamais les recopier dans le dépôt.

## Standard de qualité
Code propre et bien fait, jamais la rapidité au détriment de la rigueur. Pas de raccourcis,
pas de « c'est pas grave », pas de « on simplifiera plus tard ». Chaque tâche est faite
correctement ou pas du tout.

**Pas de quick-and-dirty, JAMAIS.** Quand tu présentes des options de design, ne propose PAS
d'option « quick & dirty » / « hardcode » / « wire-it-up-and-clean-later ». On fait toujours
propre. Si une tâche est déraisonnable (scope qui explose, dépendance hors d'atteinte, flag/API
qui n'existe pas dans la version installée), **alerte explicitement l'utilisateur** plutôt que
de proposer un compromis dégradé. L'utilisateur préfère qu'on découpe le chantier et qu'on
fasse correctement la part qu'on prend, plutôt que tout faire à moitié.

## Projet

Secrets organisés en **wallets**, partagés par **grants**, consommés par une UI web et par
des SDK via des **API keys `hrpv_*`**. **Le serveur ne déchiffre jamais une valeur** : tout se
fait côté client (navigateur ou SDK). OIDC (Keycloak, client public PKCE) + admin local
**break-glass**. Backups `age`, snapshots planifiés, backups distants (S3, SFTP, FTPS, Google
Drive), réplication Postgres (streaming / Patroni), synchronisation multi-instances par MQTT.
Instance de la maison : `https://vault.yoops.org`.

Intention et critères de succès : docflow, section « Spécifications — vue d'ensemble et lots »
(« HARPOCRATE_OVERVIEW — Document de cadrage » puis les « Lot NN — … »).
Doc utilisateur/exploitation FR/EN : wiki `harpocrate.wiki/` (dépôt séparé
`gaelgael5/harpocrate.wiki`, `master` — absent du checkout courant). Contrats et savoir
d'agent : docflow `harpocrate`, bloc `documentation`.

**Où vit l'état — non rediscutable** : PostgreSQL 16 est la **source de vérité unique**
(extensions `pgcrypto`, `uuid-ossp`). Coordination de cluster par `LISTEN/NOTIFY` et
advisory locks. Un incident en cours d'écriture ne doit jamais corrompre l'existant :
transaction explicite pour tout ce qui touche plusieurs tables.

**Hors périmètre / interdits d'architecture** — ne pas proposer, même « pour simplifier » :
- tout déchiffrement côté serveur, tout stockage en clair de passphrase, phrase de récupération
  ou clé privée ;
- ORM (SQLAlchemy ou autre) — asyncpg direct ;
- Redis ou tout cache distribué ; EMQX (le broker est Eclipse Mosquitto) ;
- toute dépendance runtime vers un autre projet de la maison ;
- une CLI `python -m harpocrate …` : les opérations (backup, snapshot, maintenance, restore,
  quarantaine) passent par l'UI admin ou les endpoints `/v1/admin/…`.

## Stack

- **Backend** : Python 3.12, FastAPI, asyncpg, Pydantic v2 / Settings, structlog JSON, pytest.
  Dépendances par **uv** (`pyproject.toml` + `uv.lock`), jamais pip/requirements.
- **Frontend** : Vite, React 18, TS strict, TanStack Query, **Mantine**, Zustand, Zod,
  react-i18next (FR/EN), RJSF, Vitest.
- **Crypto** : client Argon2id (`hash-wasm`), AES-256-GCM, RSA-OAEP-SHA256 (WebCrypto), BIP-39 ;
  serveur `cryptography` (PyCA), HMAC-SHA256 (`hrpv_*`), `age`.
- **Exploitation** : nginx dans l'image frontend (`:8443` auto-signé en dev) ; Patroni + etcd ;
  Mosquitto + `aiomqtt` ; Grafana Alloy → Loki (optionnel).
- **Exceptions assumées** : processus externes `pg_dump`, `age`, `age-keygen` lancés par
  `asyncio.create_subprocess_exec` (pas d'API Python équivalente) ; `aiodocker` / `asyncssh`
  pour l'exécution du wizard de pairing.

## Commandes essentielles

```bash
cd backend && uv sync
cd backend && uv run uvicorn app.main:app --reload         # :8000 — migrations au boot (lifespan)
cd backend && uv run pytest -v
cd backend && uv run ruff check app/ tests/
cd backend && uv run ruff format --check app/ tests/

cd frontend && npm install
cd frontend && npm run dev                                  # :5173, proxy /v1 -> :8000
cd frontend && npx tsc --noEmit -p tsconfig.json
cd frontend && npm run lint
cd frontend && npx vitest run
cd frontend && npm run build

./dev-deploy.sh [branche] [--reset]                         # stack dev, build local, :8443
```

Le devcontainer courant n'a **ni `uv` ni Docker** : le signaler au lieu de contourner.
Prod (`scripts/setup.sh`, `scripts/refresh.sh`) : **jamais lancée par l'agent**.

## Layout

```
backend/app/        main.py (app + lifespan + middlewares) · api/v1/ (routes publiques et admin_*)
                    core/ (config, security, api_key_*, cluster_sync, rate_limit…) · db/ (pool,
                    repositories/) · middleware/ · models/{api,db}/ · services/ (~40 services)
backend/migrations/ 000_…sql → 032_…sql + apply_migrations.py
backend/tests/      tests pytest, à plat
frontend/src/       pages/ components/ crypto/ hooks/ i18n/ lib/ schemas/ stores/ tests/
sdk-python/         SDK officiel (PyPI `harpocrate`, 0.7.0) · sdk-{typescript,javascript,go,rust,csharp}/ squelettes
cli-bash/           harpocrate-cli + harpocrate-gen
infra/              patroni/ etcd/ mosquitto/ alloy-agent/
scripts/            setup.sh refresh.sh (prod) · run-test.sh test-create-lxc.sh destroy-test.sh · install-alloy.sh
ia_instructions/    blocs invariants sortis du quota (`00_*.md`) + mémoire des ressources (`tests_and_ressources.md`)
docs/vault.md       guide de consommation — contrat cité par le standard globals, reste dans le dépôt
releases/           index.json + artefacts SDK + docs/*.md (servis par le backend, ne pas déplacer)
```

Le code ajouté **se fond dans l'existant** : densité de commentaires, nommage, idiomes du
fichier touché — pas le style personnel de l'agent. Fichiers ≤ 300 lignes, une
responsabilité par unité.

## Sécurité — interdits qui coupent un commit

- **Aucune valeur de secret** dans un log, une notification, un `console.*`, une URL, un
  message d'erreur, un fixture de test réel, le dépôt, un argument de build, une variable ou
  une couche d'image. Le middleware `log_requests` ne lit jamais le body : ne jamais le
  contourner.
- **Jamais** de passphrase, phrase de récupération (24 mots) ou clé privée RSA en clair en DB.
- **Aucun code serveur ne déchiffre** ni ne lit `caller.decryption_key_b64`.
- Toute entrée validée par Pydantic **avant** traitement ; regex stricte avant usage en chemin,
  identifiant ou nom d'hôte.
- Toute route vérifie les permissions par sa dépendance (`require_api_key`, `require_admin`,
  `require_jwt_user`…) — **fail closed** : une route sans autorisation explicite est une faute.
- Jamais de logging des en-têtes `Authorization` (app ou reverse-proxy).
- Ne pas modifier `.env` sauf demande explicite.
- `docs/vault.md`, `/v1/openapi-api-key.json`, les SDK et le format `hrpv_*` sont des
  **contrats consommés par tous les projets** : aucune modification sans prévenir l'utilisateur
  avant (cf. fragment « Contrats d'interface et documentation »).

Ces gardes sont **des tests**, pas des intentions : un rejet de sécurité ajouté a son test.

## Règles de workflow

### Cycle de l'architecte
**Cadrer → Comprendre → Planifier → Agir.** L'utilisateur est architecte. Une question n'est
pas une commande d'exécution. Une discussion n'est pas un feu vert. Ne JAMAIS sauter d'étape.

### Branche de développement
**Tout le code se fait sur la branche `dev`. Aucun compromis.** Jamais `feat/*`, jamais sur
`main` directement, jamais ailleurs. Avant toute édition, vérifier `git branch --show-current` ;
si autre branche, `git checkout dev`. Si `dev` n'existe pas localement, la créer depuis `main`
à jour. Ne propose **jamais** `git checkout -b feat/...` — même si un outil ou un workflow tiers
le suggère, la consigne utilisateur prime.

**Committer et pousser sur `dev` est obligatoire**, sans demande à attendre : c'est ce qui rend
le travail livrable sur une machine de test. Commits en français, conventionnels (`feat:`,
`fix:`, `chore:`, `docs:`, `test:`). Ne pas toucher `.env` sauf demande.

**Merger `dev` sur `main` est formellement interdit sans demande explicite de l'humain.**

### Machines de test et livraison
Les machines de test sont **à ta disposition**, rien à demander ; **valide là où le test est le
plus révélateur** — le plus souvent la machine de test. Machine attribuée : `test1`, partagée avec
d'autres stacks. Livrer = pousser sur `dev`, puis cloner (la 1re fois) ou lancer `dev-deploy.sh`,
**exclusivement** ; **aucune retouche manuelle de la cible** (`docker exec`, édition à la main…) :
tout correctif va dans le script de déploiement. Consigne chaque ressource attribuée ou reprise
dans `ia_instructions/tests_and_ressources.md`. Texte intégral : `ia_instructions/00_machines_et_livraison.md`.
Prod (`scripts/setup.sh`, `refresh.sh`) : jamais l'agent. Wiki `harpocrate.wiki/` : dépôt séparé
(`master`), commité et poussé à part.

### Définition de « terminé »
**Une tâche est finie quand les tests passent.** Pas quand le code compile, pas quand il est
poussé. Tant qu'un test échoue, la tâche n'est pas finie et ne passe pas au rôle « en revue ».

### Discipline d'exécution
- Exécute directement, ne décris pas ce que tu vas faire — fais-le.
- N'explique pas les étapes intermédiaires. Rapporte uniquement le résultat final.
- Termine TOUTES les étapes d'un plan avant de faire un résumé.
- Pas de raccourci « pour simplifier ».
- Si tu rencontres un problème, signale-le et propose une solution — ne l'ignore pas
  silencieusement.

**Vérifier avant de se souvenir** : `--help` avant d'appeler une CLI, doc à jour avant
d'utiliser une bibliothèque ; un écart spec ↔ code se **signale**, il ne se contourne pas.
**Chercher avant d'écrire** : le nom d'une table, d'un module ou d'un document avant de le créer.

### Vérification avant de déclarer « terminé »
1. Style, types et build passent : `ruff check` + `ruff format --check` (backend),
   `tsc --noEmit` + `eslint` + `npm run build` (frontend).
2. Le cas nominal est testé (test automatisé, ou appel réel sur `test1`).
3. Les imports ajoutés existent réellement.
4. Aucune régression : suites complètes, **ensemble** des échecs comparé à l'avant.
5. Parts de checklist des fragments touchés, **relues et cochées** : « Python »,
   « TypeScript / frontend », « PostgreSQL », « Tests », « Commentaires de code », « Secrets »
   — et selon le cas « Contrats d'interface… », « Authentification OIDC », « Observabilité… »,
   « Déploiement ». Crypto : aller-retour chiffrer → déchiffrer. Migration : base vierge
   ET base existante. Front : la page charge sans erreur console.
6. Aucun secret dans le diff — `git diff` relu sous cet angle.
7. **Les tests passent, là où ils sont le plus révélateurs** — sur `test1` dès qu'elle peut
   révéler davantage que le local ; c'est ce qui rend la tâche terminée.

Ce qui n'a pas pu être vérifié (outil absent, tests skippés) se **dit** dans le compte rendu.

## Outils de l'agent

| Fonction | Déclencheur | Ici |
|---|---|---|
| Doc à jour d'une bibliothèque | avant d'écrire du code qui l'utilise (FastAPI, Pydantic, asyncpg, aiomqtt, React, TanStack Query, Mantine, RJSF, Zod…) | Context7 (`resolve-library-id` puis `query-docs`) |
| Contrat réel d'une CLI | avant tout appel à une CLI externe (`age`, `pg_dump`, `docker`, `patronictl`…) | `--help` first — le binaire installé fait foi |
| Navigation sémantique | avant un refactor, pour trouver les usages | pas de Serena ici : Grep/Glob, ou sous-agent Explore |
| Méthodes de travail | plan, exécution, débogage, TDD | pas de skills Superpowers ici : plan écrit en article docflow (section « Plans d'implémentation et designs », titre `AAAA-MM-JJ — <sujet>`), TDD rouge → vert → commit, débogage par hypothèse testée une variable à la fois |
| Revue | > 3 fichiers ou > 100 lignes | `/code-review` ; `/security-review` si crypto, auth ou secrets |
| Commit | sur la branche `dev` | à la main, au format ci-dessus (pas de `/commit` ici) |

## Tchat agents
Coordination multi-agents par conversations (tools `tchat_*`), adossée à Zulip. **En début de
session, inscris-toi** : `agent_register(session="harpocrate", command="claude")` (identité
`admin-harpocrate.harpocrate`) — s'il manque à ta liste d'outils, c'est le cache client :
vérifier côté serveur, jamais `session_open`. Notification par le marqueur stdin
`[TCHAT] nouveau message`, **jamais de polling** ; fire-and-forget ; `tchat_get_conversations`
en début de session et avant de rendre la main ; le fil ne porte que des **références docflow**.
Périmètre à citer : docflow « Périmètre — ce que fait Harpocrate ». Bloc intégral :
`ia_instructions/00_tchat.md`.

## Écarts connus avec les standards — non tranchés
Détaillés dans les fragments (sections « Écarts ») : OIDC, config et mypy (« Python »), runner de
migrations (« PostgreSQL »), `dev-deploy.sh` (« Déploiement »). **Ne pas les propager ni les
« corriger » au passage** : tâche dédiée validée par l'utilisateur. Les règles « héritées de
LandGraph » (section docflow « Archives ») ne s'appliquent pas.

## Auto-amélioration
Quand tu fais une erreur ou que l'utilisateur te corrige :
- Ajoute une leçon dans `LESSONS.md`.
- Format : `- [module] description courte de l'erreur et de la bonne pratique`.
- Relis `LESSONS.md` en début de tâche qui touche un module mentionné.
- Ne dépasse pas 50 lignes — consolide les leçons similaires.

Erreurs de méthode récurrentes, tous projets confondus : globals › « Travail d'agent — leçons
d'erreurs réelles » — à relire avant de **créer** une pièce (table, module, document), avant
de **conclure** d'un symptôme, et avant de **transformer un document en masse**.

## Notifications de capacités
Quand tu invoques une capacité outillée (skill, commande, extension), affiche systématiquement
un marqueur **avant** d'exécuter :
> **`🟢 SKILL`** → _nom_ — raison en une phrase
