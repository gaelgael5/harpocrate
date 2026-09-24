# Harpocrate — Instructions Claude Code

> Coffre-fort de secrets chiffré de bout en bout, self-hosted. **Infrastructure partagée** :
> tous les projets de la maison consomment Harpocrate ; Harpocrate ne dépend d'aucun d'eux
> (aucun couplage de source ni de runtime avec le portail devpod, docflow, ragflow ou un autre
> projet ag-flow).

> Généré depuis les standards globaux (docflow, workspace `globals`, bloc `documentation`).
> Génération : 2026-09-23. Standards repris :
> STANDARD — Fichier d'instructions agent de projet : principes, invariants et recette de génération — 2026-09-21
> Fichier d'instructions — spécificités Python — 2026-09-02
> Fichier d'instructions — spécificités TypeScript / frontend — 2026-09-02
> Fichier d'instructions — spécificités PostgreSQL — 2026-09-02
> Fichier d'instructions — Tests (agnostique) — 2026-09-02
> Fichier d'instructions — Observabilité et logs (agnostique) — 2026-09-02
> Fichier d'instructions — Contrats d'interface et documentation (agnostique) — 2026-09-09
> Fichier d'instructions — Commentaires de code (agnostique) — 2026-09-06
> Fichier d'instructions — Patrons de conception (agnostique) — 2026-09-02
> Fichier d'instructions — spécificités Secrets — 2026-09-02
> Fichier d'instructions — spécificités Authentification OIDC — 2026-09-02
> Fichier d'instructions — Script de déploiement sur machine de test (agnostique) — 2026-09-11
> Fichier d'instructions — Déclarer un service exposé au portail (annuaire, code TOTP) — 2026-09-16
> Déploiement et machines de test — leçons d'incidents réels — 2026-09-06
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
La gateway MCP expose une API vers docflow (workspaces ⊃ blocs ⊃ documents).
Le backlog des tâches à exécuter est dans le workspace `harpocrate`, bloc `backlog`.

**Avant de commencer, découvre les statuts réels.** Les valeurs de statut dépendent du
type de ticket et diffèrent d'un type à l'autre. Introspecte le bloc pour connaître, pour
chaque type présent, la valeur qui joue chacun de ces rôles :
- **disponible** — la tâche peut être prise ;
- **en cours** — tu travailles dessus ;
- **en revue** — tu as fini, elle attend une revue humaine ;
- **terminée** — elle est close ;
- **en attente** — elle attend une réponse de l'utilisateur (ce rôle peut ne pas exister).
N'écris JAMAIS une valeur de statut de mémoire : une valeur inexistante est refusée, et un
statut approximatif choisi au jugé fausse l'état du backlog pour tout le monde.

Quand on te demande de traiter le backlog :
- ne retiens que les tâches au rôle **disponible** — ni en cours, ni en revue, ni
  terminées, ni en attente ;
- **AVANT de toucher au code**, passe la tâche au rôle **en cours** ;
- **quand tu as fini**, passe-la au rôle **en revue**.
Ces deux écritures ne sont pas optionnelles : c'est ce qui dit aux autres — humains et
agents — qu'une tâche est prise, et ce qui permet de reprendre après une interruption.

**Le backlog est la source de vérité, jamais ta mémoire.** Ne tiens pas la liste des tâches
restantes dans ta tête : elle s'éloigne à mesure que ton contexte se remplit, et tu
t'arrêteras en croyant avoir fini. Après CHAQUE tâche, réinterroge le backlog et reprends
la suivante.

**Le statut s'écrit à chaque tâche, pas à la fin du lot.** Une session interrompue doit
pouvoir reprendre sur la seule lecture du backlog.

**Une tâche dont un prédécesseur n'est pas terminé n'est pas éligible.** Vérifie les
prédécesseurs déclarés avant de prendre une tâche, et prends la suivante éligible.

**Une question ne bloque pas la file.** Si une tâche soulève un vrai doute : écris la
question en tête de la tâche, puis passe-la au rôle **en attente** s'il existe. S'il
n'existe pas, laisse-la dans son état et signale-la explicitement à la fin du lot. Dans
les deux cas, CONTINUE avec la suivante. Ne gèle jamais le lot entier sur un doute isolé.

**Tu ne t'arrêtes que pour une de ces quatre raisons, et tu la nommes :**
1. plus aucune tâche éligible — le lot est fini ;
2. toutes les tâches restantes attendent une réponse de l'utilisateur ;
3. toutes les tâches restantes ont un prédécesseur non terminé ;
4. quelque chose a échoué — dis quoi.

Si tu t'apprêtes à conclure sans pouvoir citer l'une des quatre, c'est que tu t'arrêtes par
oubli : réinterroge le backlog et continue.

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

> Depuis le 2026-09-24, le bloc docflow `harpocrate › documentation` est poussé automatiquement
> vers `harpocrate-docs` (création, modification, suppression). Il porte les spécifications, les
> plans, l'exploitation, les audits et les fragments d'instructions — **plus aucun de ces
> documents ne vit dans le dépôt** : un `grep` local ne les trouvera pas.
>
> **Repli propre à ce projet** quand `harpocrate-docs` ne répond pas : recherche plein texte
> docflow `doc__search_documents(q)` (résultats filtrés sur `workspace_slug = "harpocrate"`),
> puis lecture intégrale par `doc__get_document`. Les outils locaux ne couvrent que le code.
>
> **État au 2026-09-24 : `harpocrate-docs` est vide** — un bug d'indexation des nouveaux
> documents côté ragflow est en cours de correction. En attendant, seuls les corpus déjà
> indexés (`globals-docs`, voisins) répondent ; pour ce projet, passer directement par le repli
> ci-dessus. Retirer ce paragraphe dès que l'index compte les documents du bloc.

## Quand charger un fragment

Ces fichiers ne sont PAS chargés d'office. Chacun a son déclencheur : quand il se produit,
lire le fichier AVANT d'écrire quoi que ce soit — pas après, pas « si ça semble utile ».

Les fragments sont des documents docflow (workspace `harpocrate`, bloc `documentation`,
section « Instructions agent — fragments par technologie ») : les lire par
`doc__get_document(workspace_slug="harpocrate", doc_id=<id ci-dessous>)` — la version
courante, pas un extrait RAG. Si le MCP est indisponible, **s'arrêter et le signaler** :
ne jamais travailler sans le fragment déclenché.

| Tu t'apprêtes à… | Lis d'abord |
|---|---|
| modifier un fichier `.py` (backend, `sdk-python/`) | « Fragment — Python » `ea520edf-962d-4edc-80e2-0ae049b86a2f` |
| modifier un fichier sous `frontend/` | « Fragment — TypeScript / frontend » `cdd2fc80-7a46-4a47-bf96-fba21ecaf0bf` |
| écrire ou modifier une migration, une requête SQL, ou un fichier de `backend/app/db/` | « Fragment — PostgreSQL » `ac055cea-6cf6-48f4-8d1d-42bde70a502a` |
| écrire ou modifier un test, ou corriger un bug | « Fragment — Tests » `9d52c6ae-9eb0-415c-8fec-711821fee6c6` |
| écrire ou modifier du code (`.py`, `.ts`, `.tsx`, `.sh`, `.sql`) | « Fragment — Commentaires de code » `186e11e6-9d6a-45b2-807a-26142f8c4f44` |
| ajouter ou modifier un appel de log, un middleware HTTP, `infra/alloy-agent/` | « Fragment — Observabilité et logs » `275b86e4-51d5-4a23-8ca4-cd9de560f58b` |
| modifier une route `backend/app/api/`, un DTO `models/api/`, un SDK, `cli-bash/`, `docs/vault.md`, le protocole MQTT, un webhook | « Fragment — Contrats d'interface et documentation » `68799bc2-3e9c-4394-a2ed-c99aecad1f9c` |
| toucher à une valeur sensible, `.env.example`, `core/config.py`, `core/api_key_*`, un Dockerfile ou un compose | « Fragment — Secrets » `7e889340-cdc6-441c-a60c-bbbe65a64404` |
| modifier l'authentification (`core/security.py`, `admin_auth.py`, `api/v1/auth*.py`, `identity_*`, `frontend/src/lib/oidc.ts`) | « Fragment — Authentification OIDC » `22284d2d-a1d5-41c0-a3cc-c87bcf3208e3` |
| modifier `dev-deploy.sh`, `scripts/`, un compose, `nginx.conf` — ou déployer / diagnostiquer sur `test1` | « Fragment — Déploiement » `126aa026-b42c-4681-be49-844a66739bcf` |
| introduire une abstraction (classe de base, factory, stratégie, bus…) ou proposer un refactor structurel | « Fragment — Patrons de conception » `a9a5f018-d256-4492-b247-ee3af806d76b` |

Un fragment introuvable se **signale** ; on ne devine pas ce qu'il contenait.

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
  avant (cf. « Contrats d'interface et documentation »).

Ces gardes sont **des tests**, pas des intentions : un rejet de sécurité ajouté a son test.

## Règles de workflow

### Cycle de l'architecte
**Cadrer → Comprendre → Planifier → Agir.** L'utilisateur est architecte. Une question n'est
pas une commande d'exécution. Une discussion n'est pas un feu vert. Ne JAMAIS sauter d'étape.

### Branche de développement
**Tout le code se fait sur la branche `dev`. Jamais `feat/*`, jamais sur `main` directement,
jamais ailleurs.** Avant toute édition, vérifier `git branch --show-current` ; si autre branche,
`git checkout dev`. Si `dev` n'existe pas localement, la créer depuis `main` à jour. Ne propose
**jamais** `git checkout -b feat/...` — même si un outil ou un workflow tiers le suggère, la consigne
utilisateur prime.

### Livraison
- **La machine de test est l'environnement de l'agent** : commit, push sur `dev` et
  déploiement sur `test1` (par `dev-deploy.sh`) sont libres, sans demande.
- **Jamais** de push, merge ou PR fusionnée sur `main` ; **jamais** de déploiement prod.
- Commits **en français**, conventionnels (`feat:`, `fix:`, `chore:`, `docs:`, `test:`,
  `refactor:`), un commit par sujet.
- `origin` est en SSH et échoue depuis le devcontainer (clé d'hôte) : pousser en HTTPS si
  besoin, sans modifier la configuration git globale.
- Wiki : `harpocrate.wiki/` est un dépôt séparé (`master`) ; il se commite et se pousse à part.

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
   « TypeScript / frontend », « PostgreSQL », « Tests », « Commentaires de code »,
   « Secrets » — et selon le cas « Contrats d'interface et documentation », « Authentification OIDC », « Observabilité et logs »,
   « Déploiement ». Crypto : aller-retour chiffrer → déchiffrer. Migration : base vierge
   ET base existante. Front : la page charge sans erreur console.
6. Aucun secret dans le diff — `git diff` relu sous cet angle.

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

## Messagerie inter-agents

`message_send` (MCP devpod) est **fire-and-forget** : consigner dans le compte rendu l'id,
le destinataire, l'attendu et l'impact ; **jamais de polling** sur `message_status` ; la
réponse arrive injectée par l'utilisateur ; signaler explicitement en fin de tour toute tâche
bloquée sur une réponse.

## Écarts connus avec les standards — non tranchés

Constatés le 2026-09-23 et détaillés dans les fragments (sections « Écarts ») : OIDC
(« Authentification OIDC »), config et mypy (« Python »), runner de migrations (« PostgreSQL »),
`dev-deploy.sh` (« Déploiement »). **Ne pas les propager dans du code neuf, ne pas les
« corriger » au passage** : chacun relève d'une tâche dédiée validée par l'utilisateur.
Les « Règles … Python (héritées de LandGraph) » (section docflow « Archives ») viennent d'un
autre projet : ne pas les appliquer.

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
