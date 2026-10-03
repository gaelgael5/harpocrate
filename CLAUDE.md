# Harpocrate — Instructions Claude Code

> Coffre-fort de secrets chiffré de bout en bout, self-hosted. **Infrastructure partagée** : tous les
> projets de la maison consomment Harpocrate ; Harpocrate ne dépend d'aucun d'eux (aucun couplage de
> source ni de runtime avec devpod, docflow, ragflow ou un autre projet ag-flow).
> **Ce fichier prime sur ton comportement par défaut et se lit en début de session.**

> Généré depuis les standards globaux (docflow, workspace `globals`, bloc `documentation`).
> Génération : 2026-10-03. Standards repris : STANDARD — Fichier d'instructions agent de projet — 2026-09-26 (v42, recette skills du 2026-10-01) ;
> Travail d'agent — leçons d'erreurs réelles — 2026-09-02 ; STANDARD — Sécurité : secrets et coffres Harpocrate — 2026-09-20 ;
> STANDARD — Authentification OIDC & liaison d'identité — 2026-09-15 ; STANDARD — Instance de dev/test — v10.
> Skills requises : backlog-workflow, rag-search, test-machine-deployment, agent-chat, self-improvement, python, typescript-frontend, postgresql, tests, code-comments, design-patterns, interface-contracts, observability-logs, secrets, oidc-authentication, portal-exposed-service, cadrage-projet, harpocrate-backend, harpocrate-frontend, harpocrate-tests, harpocrate-security, harpocrate-contracts, harpocrate-deployment (dernière version publiée, déposées par le profil de skills du workspace).
> Mise à jour par `--update` : ne reporter que le delta du socle depuis cette date ;
> une évolution du contenu d'une skill ne demande aucun `--update`.

**Colibri** commence systématiquement tes réponses par 🎺

## mcp
Tu es connecté au MCP du portail devpod (`dev.yoops.org`) via le serveur `claude-code` (`.mcp.json`, non versionné).

## Backlog
Le backlog des tâches est dans le workspace docflow `harpocrate`, bloc `backlog`. C'est la
source de vérité, jamais ta mémoire : le statut s'écrit à chaque tâche, à la prise et à la fin.
Charge la skill `backlog-workflow` AVANT de prendre, faire avancer ou clore une tâche.

## Recherche
Toute recherche d'information passe d'abord par le RAG (`rag__*` ; corpus `harpocrate-docs`,
`globals-docs`), ensuite seulement par les outils locaux. Le RAG muet n'est pas une réponse : va
lire l'artefact réel. Charge la skill `rag-search` AVANT toute recherche sur le projet ou ses contrats.

## Quand charger une skill

Les skills ne sont PAS chargées d'office. Chacune a son déclencheur : quand il se produit,
charge la skill AVANT d'écrire quoi que ce soit — pas après, pas « si ça semble utile ».

| Tu t'apprêtes à… | Charge d'abord |
|---|---|
| prendre, faire avancer ou clore une tâche du backlog | la skill `backlog-workflow` |
| chercher une information sur le projet, ses voisins ou ses contrats | la skill `rag-search` |
| déployer ou livrer sur une machine de test, y tester ou y diagnostiquer, toucher au script de déploiement | la skill `test-machine-deployment` |
| appeler, inviter ou répondre à un autre agent ; voir `[TCHAT] nouveau message` | la skill `agent-chat` |
| corriger une erreur que l'utilisateur t'a signalée, ou une erreur qui se répète | la skill `self-improvement` |
| intervenir sur `test1`, lancer ou modifier `dev-deploy.sh`, `scripts/*.sh`, un `docker-compose*.yml` | la skill `harpocrate-deployment` |
| modifier un fichier `.py` (`backend/`, `sdk-python/`) | les skills `python` et `harpocrate-backend` |
| écrire une migration `backend/migrations/*.sql`, une requête SQL ou un fichier de `backend/app/db/` | les skills `postgresql` et `harpocrate-backend` |
| modifier un fichier `.ts`, `.tsx` ou `src/i18n/*.json` sous `frontend/` | les skills `typescript-frontend` et `harpocrate-frontend` |
| écrire, modifier ou lancer un test (`pytest`, `vitest`), ou corriger un bug | les skills `tests` et `harpocrate-tests` |
| écrire ou modifier du code (`.py`, `.ts`, `.tsx`, `.sh`, `.sql`) | la skill `code-comments` |
| introduire une abstraction (classe de base, factory, stratégie, bus…) ou un refactor structurel | la skill `design-patterns` |
| modifier une route `app/api/`, un DTO, un SDK, `cli-bash/`, `docs/vault.md`, `api_key_token.py`, le protocole MQTT, un webhook | les skills `interface-contracts` et `harpocrate-contracts` |
| toucher à une valeur sensible, `.env.example`, `core/config.py`, `core/api_key_*`, `src/crypto/`, un Dockerfile ou un compose | les skills `secrets` et `harpocrate-security` |
| modifier l'authentification (`core/security.py`, `admin_auth.py`, `api/v1/auth*.py`, `identity_*`, `src/lib/oidc.ts`) | les skills `oidc-authentication` et `harpocrate-security` |
| ajouter un appel de log, un middleware HTTP, toucher `infra/alloy-agent/` | les skills `observability-logs` et `harpocrate-security` |
| ajouter ou modifier un service exposé, ou sa déclaration dans le script de déploiement | la skill `portal-exposed-service` |
| démarrer un sujet nouveau, avant de créer des tickets ou de lancer un développement | la skill `cadrage-projet` |

Une skill introuvable se **signale** ; on ne devine pas ce qu'elle contenait (voir « Repli »).

## Repli — skill absente
Une skill de la table ci-dessus introuvable se **signale** : tu ne devines JAMAIS ce
qu'elle contenait.

Si ce dépôt est ouvert hors devflow (poste local, CI) et que les skills n'y sont pas
déposées : **arrête-toi et signale-le à l'humain** avant toute tâche qu'une skill couvre.
Ne te rabats pas sur les pages docflow dont les skills sont issues : elles peuvent
diverger de la version publiée de la skill.

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
Secrets en **wallets** partagés par **grants**, consommés par l'UI et les SDK (API keys `hrpv_*`).
**Le serveur ne déchiffre jamais une valeur** : tout se fait côté client. OIDC Keycloak (PKCE public)
+ admin local **break-glass** ; backups `age`, réplication Patroni, sync multi-instances MQTT.
Spécifications : docflow `harpocrate › documentation` (« Spécifications — vue d'ensemble et lots »).

**Où vit l'état — non rediscutable** : PostgreSQL 16, **source de vérité unique** ; coordination par
`LISTEN/NOTIFY` et advisory locks ; transaction explicite pour tout ce qui touche plusieurs tables.
**Hors périmètre** : déchiffrement serveur ; ORM ; Redis ou cache distribué ; EMQX ; dépendance
runtime vers un autre projet ; CLI `python -m harpocrate` (les opérations passent par `/v1/admin/…`).

**Stack** : Python 3.12, FastAPI, asyncpg, Pydantic v2, structlog, uv · Vite, React 18, TS strict,
Mantine, TanStack Query, Zustand, Zod, i18next FR/EN · crypto client WebCrypto + `hash-wasm` ·
`age`, `cryptography`. Exception assumée : `pg_dump`/`age` par `asyncio.create_subprocess_exec`.

### ⚠ Divergence assumée vs le standard « Gestion des secrets »
**Harpocrate EST le coffre** : ses secrets d'amorçage restent dans le `.env` de l'hôte, et c'est
**délibéré** (la clé du coffre ne se range pas dans le coffre). Détail : skill `harpocrate-security`.
Écarts connus non tranchés (OIDC, `Settings` en `extra="ignore"`, runner de migrations,
`dev-deploy.sh`) : décrits dans les skills `harpocrate-*` — **ni propager, ni « corriger » au passage**.

## Commandes essentielles
```bash
cd backend && uv sync && uv run pytest -v && uv run ruff check app/ tests/ && uv run ruff format --check app/ tests/
cd backend && uv run uvicorn app.main:app --reload    # :8000, migrations appliquées au boot
cd frontend && npm install && npx tsc --noEmit -p tsconfig.json && npm run lint && npx vitest run && npm run build
./dev-deploy.sh [branche] [--reset]                   # sur test1 ; prod (scripts/setup.sh, refresh.sh) : jamais l'agent
```
Layout : `backend/` (app, migrations, tests) · `frontend/` · `sdk-*/`, `cli-bash/` · `infra/` · `scripts/` ·
`ia_instructions/tests_and_ressources.md` (ressources de test attribuées) · `docs/vault.md` (contrat).

## Sécurité — interdits qui coupent un commit
- **Aucune valeur de secret** dans un log, une notification, un `console.*`, une URL, le dépôt, un
  argument de build ou une couche d'image ; le middleware `log_requests` ne lit jamais le body.
- **Jamais** de passphrase, phrase de récupération ou clé privée RSA en clair en base ; aucun code
  serveur ne déchiffre ni ne lit `caller.decryption_key_b64` ; jamais d'en-tête `Authorization` journalisé.
- Entrées validées par Pydantic avant traitement ; chaque route a sa dépendance `require_*` — **fail closed**.
- Ne pas modifier `.env` sauf demande. Ces gardes sont **des tests**, pas des intentions.

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

### Livraison et machines de test
Livrer = pousser sur `dev`, puis lancer `dev-deploy.sh` sur la machine de test — jamais de
construction, de `docker run` ni de retouche manuelle de la cible. Les machines de test `test1`,
`test2`… sont à ta disposition. Charge la skill `test-machine-deployment` AVANT de déployer.

### Définition de « terminé »
**Une tâche est finie quand les tests passent.** Pas quand le code compile, pas quand il est
poussé. Tant qu'un test échoue, la tâche n'est pas finie et ne passe pas au rôle « en revue ».

### Vérification avant de déclarer « terminé »
1. `ruff check` + `ruff format --check` ; `tsc --noEmit` + `eslint` + `npm run build` passent.
2. Le cas nominal est testé. 3. Les imports ajoutés existent réellement.
4. Aucune régression : **ensemble** des échecs comparé à l'avant ; un test skippé n'est pas vert.
5. Parts de checklist relues et cochées des skills `harpocrate-backend`, `harpocrate-frontend`,
   `harpocrate-tests`, `harpocrate-security`, `harpocrate-contracts` selon les fichiers touchés.
6. Aucun secret dans le diff — `git diff` relu sous cet angle.
7. **Les tests passent, là où ils sont le plus révélateurs** — sur `test1` dès qu'elle peut
   révéler davantage que le local ; c'est ce qui rend la tâche terminée.

### Discipline d'exécution
- Exécute directement, ne décris pas ce que tu vas faire — fais-le.
- N'explique pas les étapes intermédiaires. Rapporte uniquement le résultat final.
- Termine TOUTES les étapes d'un plan avant de faire un résumé.
- Pas de raccourci « pour simplifier ».
- Si tu rencontres un problème, signale-le et propose une solution — ne l'ignore pas
  silencieusement.

### Leçons de travail — erreurs réelles à ne pas refaire
- **Chercher avant de créer.** Avant de créer une table, un module, un document ou une
  règle, cherche son nom : la pièce existe déjà plus souvent qu'on ne le croit.
- **Interroger le système plutôt que déduire de la doc.** La documentation dit ce qui est
  illustré, pas ce qui est permis. Quand un accès existe (bac à sable, `--help`, requête
  réelle), interroge-le. Ce qui se vérifie ne se déduit pas ; une déduction s'annonce
  comme telle.
- **Exclure les zones littérales des transformations.** Toute transformation
  programmatique d'un document épargne blocs de code, citations et exemples — puis se
  vérifie en comparant ces zones à leur source, caractère par caractère.
- **Ne lancer que les outils déclarés.** Avant un outil de mise en forme ou de correction,
  vérifie qu'il est déclaré dans le dépôt ; à défaut, tiens-t'en à ceux qui le sont.
- **Vérifier la cible avant d'agir.** Établis sur quoi tu agis — machine, dépôt, branche,
  environnement — et que c'est bien l'endroit que l'utilisateur décrit.
- **Un symptôme à causes multiples ne désigne pas sa cause.** N'en nomme une qu'après
  avoir écarté les autres en mesurant, une variable à la fois, assez de fois pour qu'un
  défaut intermittent ne décide pas à ta place. Une contestation de l'utilisateur est une
  donnée : elle vaut souvent mieux que ta déduction.
- **Relire après écriture.** Un stockage normalise ce qu'on lui donne : relis et compare à
  ce que tu voulais écrire, pas seulement au succès de l'appel.
- **Vérifier le résultat, jamais le code de retour.** Un « succès », un test vert, une
  sortie à zéro ne prouvent pas que la chose voulue s'est produite.

## Outils de l'agent
| Fonction | Déclencheur | Ici |
|---|---|---|
| Doc à jour d'une bibliothèque | avant d'écrire du code qui l'utilise | Context7 |
| Contrat réel d'une CLI | avant tout appel à une CLI externe (`age`, `pg_dump`, `docker`…) | `--help` first |
| Navigation sémantique | avant un refactor, pour trouver les usages | pas de Serena : Grep/Glob ou sous-agent Explore |
| Méthodes de travail | plan, exécution, débogage, TDD | pas de Superpowers : plan en article docflow, TDD rouge → vert → commit |
| Revue et commit | > 3 fichiers ou > 100 lignes | `/code-review` (`/security-review` si crypto/auth) ; commit à la main |

## Auto-amélioration
Une erreur corrigée devient une leçon dans `LESSONS.md`. Charge la skill `self-improvement`
quand l'utilisateur te corrige ou qu'une erreur se répète.

## Tchat agents
En début de session, inscris-toi : `agent_register(session=<ta session tmux>, command=<ce qui
t'a lancé>)`. Jamais de polling : à la vue du marqueur `[TCHAT] nouveau message` dans ton stdin,
comme avant d'appeler, d'inviter ou de répondre à un autre agent, charge la skill `agent-chat`.
Ici : `agent_register(session="harpocrate", command="claude")` ; périmètre à citer : docflow « Périmètre — ce que fait Harpocrate ».

## Notifications de capacités
Quand tu invoques une capacité outillée (skill, commande, extension), affiche systématiquement
un marqueur **avant** d'exécuter :
> **`🟢 SKILL`** → _nom_ — raison en une phrase
