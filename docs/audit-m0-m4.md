# Audit M0-M4 — Spec vs Implementation

**Date** : 2026-04-11
**Scope** : modules M0 (Secrets), M1 (Dockerfiles), M2 (Rôles), M3 (Catalogues), M4 (Composition phase 5a)
**Source** : audit parallèle par 5 sous-agents + consolidation

**Légende sévérité :**
- 🔴 **BLOCKING** — contrat de la spec cassé ou feature promise absente et bloquante
- 🟠 **MISSING** — feature décrite dans la spec, totalement absente du code
- 🟡 **PARTIAL** — feature commencée mais incomplète
- 🔵 **SPEC DRIFT** — décisions d'impl divergeant de la spec, à arbitrer (maj spec ou maj code)

---

## Résumé exécutif

| Module | 🔴 BLOCKING | 🟠 MISSING | 🟡 PARTIAL | 🔵 SPEC DRIFT |
|---|---:|---:|---:|---:|
| M0 Secrets       | 2 | 2 | 2 | 0 |
| M1 Dockerfiles   | 5 | 6 | 3 | 0 |
| M2 Rôles         | 1 | 7 | 0 | 2 |
| M3 Catalogues    | 2 | 5 | 2 | 0 |
| M4 Composition   | 4 | 4 | 2 | 0 |
| **Total**        | **14** | **24** | **9** | **2** |

**49 gaps identifiés** au total + 2 décisions de spec à trancher + **3 features hors spec** demandées (NF-1 chat Docker builder, NF-2 CRUD service types, **NF-3 profils de missions**).

**Source** : audit automatique (5 sous-agents) + feedback utilisateur 2026-04-11 (en plusieurs passes).

---

## Thèmes transverses (cross-cutting)

Ces problèmes apparaissent dans plusieurs modules et méritent d'être traités ensemble plutôt que module par module.

### 🔴 TR-4 — Responsive mobile _(feedback utilisateur)_
**Le site doit être utilisable sur mobile.** Toute l'impl actuelle est desktop-only :
- Sidebar 240px fixe → doit devenir drawer off-canvas sous 768px
- Tables M0-M3 en largeur fixe → doivent soit scroller, soit se transformer en cards sous 640px
- Formulaires M2/M4 en grid multi-colonnes → empiler en mobile
- `AppLayout` actuel en `flex h-screen` → tester sur viewport mobile (iOS safe-area, soft keyboard)
- Pas de point de bascule défini ; proposer `sm 640 / md 768 / lg 1024` Tailwind standard
- **Correctif** : chantier global qui touche `AppLayout`, `Sidebar`, toutes les pages. Doit être fait **pendant la refonte design 5b-B/C** pour ne pas tout refaire en 2 passes.

### 🔴 TR-1 — Indicateurs visuels 🔴🟠🟢 sur variables d'env (convention M0)
La spec M0 lignes 45-52 déclare une convention visuelle (🔴 missing / 🟠 empty / 🟢 ok) pour **toute variable d'env référencée**. L'endpoint backend `GET /api/admin/secrets/resolve-status` existe et fonctionne. **Aucune page ne l'utilise.**
- **M0** : la page `SecretsPage` n'affiche pas le statut.
- **M3 Discovery** : `api_key_var` affiché en `<code>` plat, pas d'indicateur.
- **M3 MCP** : paramètres stockant des refs `$VAR`, pas d'indicateur.
- **M4 AgentEditor** : champ env_vars avec valeurs `$VAR` , pas d'indicateur.
- **Correctif** : créer un composant `<EnvVarStatus varName="..." />` qui utilise une query React partagée `useEnvVarStatus(names)` et l'appliquer partout. **Chantier unique qui corrige 4 modules.**

### 🔴 TR-2 — Paramètres configurables par l'UI (M1 + M3 + M2 + M4)
Pattern récurrent : des JSONB `parameters` stockés en base, mais aucune UI pour les éditer.
- **M1** : `dockerfiles.parameters` (JSONB) — déclaré dans le schema, jamais exposé à l'UI, jamais substitué dans le Dockerfile au build.
- **M3 MCP** : `mcp_servers.parameters` (JSONB) — endpoint `PUT .../parameters` existe, aucun bouton dans `MCPCatalogPage` pour l'éditer.
- **M2 Roles** : `roles.runtime_config` (JSONB) — stocké, jamais exposé (tab Runtime manquant).
- **M4 Agents** : `agent_mcp_servers.parameters_override` (JSONB) — editable via textarea JSON brute dans `AgentEditorPage` (fonctionnel mais moche).
- **Correctif** : concevoir un pattern `<JsonParametersEditor schema={parameters_schema} value={parameters}/>` avec `parameters_schema` comme source de vérité pour les champs.

### 🔵 TR-3 — Spec drift : migrations destructives non reflétées dans la spec
Deux migrations ont retiré des champs que la spec décrit toujours.
- **005_drop_role_llm_fields** retire `llm_type/temperature/max_tokens` (`migrations/005_drop_role_llm_fields.sql`). Spec M2 ligne 128 les mentionne toujours dans le General tab.
- **006_drop_prompt_agent_md** retire `prompt_agent_md`. Spec M2 ligne 138 parle toujours d'un "prompt agent (2e personne) injecté dans le container".
- **Décision à prendre** : (a) mettre à jour la spec pour refléter l'impl simplifiée, ou (b) restaurer les champs.

---

## M0 — Secrets

### 🔴 BLOCKING

**M0-B1** `[spec:39]` **Agent-scoped secrets absent de l'API.**
Le schéma DB supporte `scope='agent'` + `agent_id`, `secrets_service.create()` accepte `agent_id`, mais :
- `SecretCreate` schema n'a pas de champ `agent_id`
- `api/admin/secrets.py:36` n'accepte jamais `agent_id`
- **Résultat** : impossible de créer un secret scoped à un agent via l'API.

**M0-B2** `[spec:43]` **`used_by` toujours vide.**
La spec dit "Utilisé par (liste des agents/Dockerfiles qui le référencent)". Impl : hardcodé à `[]` dans `secrets_service.py:50,61,71,121`. Aucune requête ne cherche quels agents/Dockerfiles référencent chaque secret.

### 🟠 MISSING

**M0-M1** `[spec:43]` **UI d'édition absente.**
`SecretsPage.tsx` n'a pas de bouton "Éditer", seulement "Supprimer". `updateMutation` existe côté hook mais n'est jamais appelé.

**M0-M2** `[spec:45-52]` **Indicateurs visuels 🔴🟠🟢 pas utilisés côté frontend.** (→ voir **TR-1**)

### 🟡 PARTIAL

**M0-P1** `[spec:39]` Agent-scoped implémenté en DB + service mais dead code parce que API layer ne le provisionne jamais.

**M0-P2** `[spec:42]` Masking un-way (auto-hide après 10s ✓) mais pas d'édition de la valeur en place — nécessite suppression + recréation.

### ✅ OK
- Encryption `pgp_sym_encrypt` correcte
- Scope enum restreint `('global', 'agent')` via CHECK + Pydantic Literal
- Endpoint test key pour les API keys Anthropic/OpenAI

---

## M1 — Dockerfiles

### 🔴 BLOCKING

**M1-B1** `[spec:63-68]` **Aucune validation de type de fichier.**
Spec liste Dockerfile, entrypoint `.sh`, `run.cmd.md` comme types normés. Impl : n'importe quel fichier plat, aucune distinction. `dockerfiles.py:48-60` valide juste "pas de séparateur de répertoire".

**M1-B2** `[spec:85-92]` **Protocole entrypoint JSON non enforced.**
Spec mandate un contrat stdin/stdout strict (`task_id`, `instruction`, `timeout_seconds`, `model` en input ; events `progress` et `result` en output). Aucune validation, aucune doc runtime, aucune référence dans le code.

**M1-B3** `[spec:101-103]` **`run.cmd.md` sans handling spécial.**
Spec décrit un "fichier markdown dédié" avec flags Docker standardisés. Impl : traité comme n'importe quel fichier. `dockerfile_files_service.py` n'a aucune logique pour le distinguer.

**M1-B4** `[user]` 🐛 **BUG : contenu du fichier disparaît au save.**
Quand on enregistre les modifs sur un fichier dans `DockerfilesPage`, le contenu du textarea disparaît. Il faut re-cliquer sur le fichier pour le voir réapparaître. Probable bug de state React : la mutation `updateFile` invalide la query mais le composant d'édition ne re-synchronise pas son state local sur les nouvelles données. **Très visible, à corriger en priorité.**

**M1-B5** `[user]` **Création agent : auto-seed Dockerfile + entrypoint.sh indépouillables.**
Quand on crée un nouveau dockerfile, il doit contenir **au moins** 2 fichiers auto-créés vides : `Dockerfile` et `entrypoint.sh`. Ces 2 fichiers ne doivent pas pouvoir être supprimés. Impl actuelle : création = dockerfile vide sans aucun fichier, suppression libre. **Recouvre partiellement M1-B1 (typage des fichiers) — les traiter ensemble.**

### 🟠 MISSING

**M1-M1** `[spec:78-83]` **Pas de skip de rebuild sur hash inchangé.**
Spec : "si le hash n'a pas changé depuis le dernier build, l'image est déjà à jour". Impl : `compute_hash` existe mais `POST /{id}/build` crée toujours une nouvelle build row et lance `docker build`, peu importe que le hash match le dernier build success. Gaspillage compute.

**M1-M2** `[spec:94-99]` **Paramètres Dockerfile non substitués.**
Spec liste API_KEY_NAME, ANTHROPIC_API_KEY, OPENAI_API_KEY, WORKSPACE_PATH avec syntaxe templating `{VAR}` et fallback `${VAR:-default}`. Impl stocke `parameters: dict` mais ne parse/substitue jamais. (→ voir **TR-2**)

**M1-M3** `[spec:105-113]` **Volumes normalisés non enforcés.**
Spec définit 4 volumes standards (`/app`, `/app/skills`, `/app/config`, `/app/output`). Impl : aucune déclaration, aucune validation, aucune sémantique.

**M1-M4** `[user]` **Fenêtre de compilation : auto-scroll vers le bas.**
Quand on compile et que les logs arrivent progressivement, la fenêtre doit rester scrollée au bas pour voir les nouveaux logs. Impl actuelle : scroll figé au top.

**M1-M5** `[user]` **Fenêtre de compilation : erreurs en rouge.**
Les lignes d'erreur doivent être colorisées en rouge (`ERROR`, `error`, exit codes, etc.). Impl actuelle : tout en gris monochrome.

**M1-M6** `[user]` **Fenêtre de compilation : bouton copier les logs.**
Pas de bouton "Copier" dans `BuildModal.tsx`. Nécessaire pour partager un log d'erreur.

### 🟡 PARTIAL

**M1-P1** `[spec:74-75]` **Logs streaming via polling au lieu de SSE/WebSocket.**
Frontend `BuildModal.tsx` polle `/status` toutes les 1.5s. Backend append les logs séquentiellement. Simulé — pas de vrai streaming.

**M1-P2** `[spec:63-68]` **Sidebar fichiers plats sans grouping.**
Affiche les fichiers flat sort alphabétique. Pas d'icônes par type (Dockerfile vs .sh vs .md).

**M1-P3** `[user]` **Fenêtre d'édition des fichiers ne remplit pas la hauteur.**
Le panneau d'affichage/édition des fichiers ne va pas jusqu'en bas de l'écran — hauteur fixée par le contenu. Doit occuper toute la hauteur disponible sous la top bar.

### ✅ OK
- CRUD complet dockerfiles + files
- Hash déterministe (SHA256 + sort, ✓ tests)
- aiodocker wrapper pour build
- Tag image déterministe `agflow-{id}:{hash}`

---

## M2 — Rôles

### 🔴 BLOCKING

**M2-B1** `[spec:149,160]` **Sections sidebar hardcodées.**
`migrations/004_role_documents.sql:6` : `CHECK (section IN ('roles','missions','competences'))`. Frontend `RoleSidebar.tsx:11` : `const SECTIONS = ["roles","missions","competences"]`. Spec : "Trois sous-sections **dynamiques**" + "On peut ajouter des répertoires/groupes". **Pas d'ajout possible.**
→ **C'est l'exemple donné par l'utilisateur qui a déclenché cet audit.**

### 🟠 MISSING

**M2-M1** `[spec:130]` **Tab Runtime absent.**
Colonne `runtime_config JSONB` stockée mais aucun tab dans `RolesPage.tsx:14` (seulement `["general","prompt","chat"]`). (→ voir **TR-2**)

**M2-M2** `[spec:142-145]` **Tab Chat non implémenté.**
Existe dans l'UI mais contient juste `{t("roles.chat_placeholder")}`. Aucun endpoint, aucune table de messages, aucune boucle LLM.

**M2-M3** `[spec:160,166]` **Hiérarchie répertoires/groupes absente.**
Le champ `parent_path` existe en DB et service, mais aucune UI pour créer ou naviguer dans des arborescences.

**M2-M4** `[spec:166]` **Bouton Importer absent.**
Pas d'endpoint dans `api/admin/roles.py`, pas de bouton dans la page.

**M2-M5** `[user]` **Suppression de catégories vides.**
Pour les catégories ajoutées en plus de `roles/missions/competences`, on doit pouvoir les supprimer si elles sont vides. Les 3 catégories natives doivent rester non-supprimables. **Dépend de M2-B1** (sections dynamiques).

**M2-M6** `[user]` **Chat mal placé : doit montrer l'impact sur les documents.**
Le Chat tab actuel est un onglet séparé avec juste un placeholder. UX souhaitée : pouvoir **discuter avec le LLM ET voir en temps réel les documents qu'il modifie** (split-view, chat à côté/sous les documents). Refonte du layout M2 nécessaire — pas juste implémenter le chat (M2-M2) mais revoir où il vit dans la page.

**M2-M7** `[user]` **Gestion des types de services (CRUD).**
Actuellement les 7 types de services (Documentation, Code, Design, Automatisme, Liste de tâches, Specs, Contrat) sont hardcodés dans `_ALLOWED_SERVICE_TYPES` Python. L'utilisateur veut **une page pour gérer ces types** (ajouter, supprimer). Nécessite : nouvelle table `service_types`, migration, service, endpoint, page admin. **Question** : page autonome, ou sous-page de Roles ?

### 🔵 SPEC DRIFT

**M2-D1** `[spec:128]` **Paramètres LLM retirés mais toujours dans la spec.**
Migration 005 supprime `llm_type/temperature/max_tokens`. La spec les mentionne toujours dans le General tab.

**M2-D2** `[spec:138]` **`prompt_agent_md` retiré mais toujours dans la spec.**
Migration 006 supprime le champ avec justification : "on compose le prompt à la volée au launch". Spec parle toujours d'un "prompt agent 2e personne injecté dans le container".

### ✅ OK
- Service types checkboxes (7 types)
- Identity 2e personne éditable
- Prompt orchestrateur 3e personne avec génération LLM (Anthropic)
- Flag `protected` avec convention visuelle 📄/🔒

---

## M3 — Catalogues

### 🔴 BLOCKING

**M3-B1** `[spec:200]` **Action "Configurer" absente pour les MCP.**
Spec : "Chaque serveur : nom court (bold), identifiant package… actions **configurer**/supprimer". `MCPCatalogPage.tsx:123-130` n'a que Supprimer. Endpoint backend `PUT /api/admin/mcp-catalog/{id}/parameters` existe mais zero UI pour l'appeler.

**M3-B2** `[spec:212]` **Liens Repo et Documentation non cliquables dans les résultats de recherche.**
Spec : "modale search results must show 'liens Repo et Documentation'". `SearchModal.tsx` affiche le texte mais pas de `<a href={repo_url}>`.

### 🟠 MISSING

**M3-M1** `[spec:183-186]` **Indicateurs 🔴🟠🟢 sur `api_key_var`.** `DiscoveryServicesPage.tsx:85-90` affiche le nom de variable en `<code>` plat. (→ voir **TR-1**)

**M3-M2** `[spec:189]` **Bouton "Éditer" pour les discovery services.**
Spec : "Actions : Tester, **Éditer**, Supprimer". Impl : Tester + Supprimer seulement.

**M3-M3** `[spec:193]` **Section "Recherche MCP" en bas de la page Discovery Services.**
Spec dit qu'il faut pouvoir chercher des MCP directement depuis la page Discovery. Impl : recherche accessible uniquement depuis `MCPCatalogPage`.

**M3-M4** `[spec:205-207]` **UI éditeur de paramètres MCP globaux.**
Endpoint existe, pas d'UI. (→ voir **TR-2**)

**M3-M5** `[spec:206]` **Indicateurs 🔴🟠🟢 sur les refs `$VAR` dans les paramètres MCP.** (→ voir **TR-1**)

### 🟡 PARTIAL

**M3-P1** `[spec:201]` **Noms de repos non cliquables.**
`MCPCatalogPage.tsx:87-90` affiche le nom en header de groupe mais sans `<a href={repo_url}>`.

**M3-P2** `[spec:214-223]` **Module 3d (instanciation globale des MCP) deferred mais non documenté.**
Le catalogue stocke les MCPs mais aucune implémentation d'instanciation globale, health checks, routing vers les agents. Deferred implicitement — devrait être marqué explicitement.

### ✅ OK
- 3a CRUD + test connectivity multi-registry
- 3b Grouping MCPs par repo avec compteurs
- 3b Transport badge (stdio/sse/docker)
- 3c CRUD + search Skills
- 3b SearchModal avec checkbox semantic (correctement absent de 3c)

---

## M4 — Composition (Phase 5a scope)

### 🔴 BLOCKING

**M4-B1** `[spec:237]` **Image freshness indicator 🔴🟠🟢 pas affiché dans l'UI.**
Backend `agents_service._compute_image_status()` retourne `missing/stale/fresh` ✓ , i18n keys `agents.image_status.*` existent ✓ , mais `AgentsPage` n'a pas de colonne Image et `AgentEditorPage` ne l'affiche nulle part. Code mort côté frontend.

### 🟠 MISSING

**M4-M1** `[spec:244]` **Paramètre `model` par défaut absent du schéma lifecycle.**
Spec : "Lancement : variables d'environnement, timeout, **model par défaut**, workspace path, network mode". Impl : pas de colonne `default_model` dans `agents` table, pas dans `AgentCreate` schema, pas dans le form.

### 🟡 PARTIAL

**M4-P1** `[spec:237]` Image status calculé mais seulement exposé dans `AgentDetail`, pas dans `AgentSummary` — impossible à afficher dans la liste sans N+1 queries.

**M4-P2** `[spec:275-277]` **Builder visuel riche correctement reporté** à phase 5b post-mockups, mais pas de lien explicite vers le plan 5b dans le code/commentaires. Cosmétique.

### ⏸ DEFERRED (correctement hors scope 5a, documenté dans le plan 5a)
- Builder visuel drag-and-drop → 5b post-mockups
- Session de test (container + WebSocket) → Phase 8
- Personnalisation par mission → Phase 5b ou ultérieure
- Communication inter-agents → Phases 6/7
- Tools normalisés + RAG → Phases 6/7
- Écriture config directory sur disque → Phase 8

### ✅ OK
- Migrations 013/014/015
- Schemas Pydantic (AgentCreate/Update/Summary/Detail, ConfigPreview)
- CRUD atomique avec transactions
- `composition_builder.build_preview` avec 6 validations d'erreurs
- Router `/api/admin/agents` complet
- Frontend hooks + API + 2 pages
- Tests backend (agents_service 10, composition_builder 6, agents_endpoint 7)
- **Note** : `frontend/tests/pages/AgentsPage.test.tsx` existe bel et bien (2 tests) — un agent d'audit a raté le fichier.

---

## Features hors spec demandées par l'utilisateur (2026-04-11)

Ces items ne sont pas dans `specs/home.md` mais ont été demandés explicitement. À intégrer au backlog mais pas prioritaires vs. correction des lacunes spec.

### NF-1 — Chat spécialisé pour créer des images Docker
Un assistant conversationnel dédié à la création de Dockerfiles : on décrit en langage naturel ce qu'on veut ("un agent claude-code avec Python 3.12 et git") et le chat génère le Dockerfile + entrypoint.sh + run.cmd.md. Nécessite :
- Endpoint backend avec LLM (Anthropic via `ANTHROPIC_API_KEY` déjà en place)
- Nouvelle page/modal dans M1 Dockerfiles
- Stockage des conversations (ou stateless ?)
- Décision : où vit-il (bouton dans `DockerfilesPage` ? Page dédiée ? Modal ?)

### NF-2 — Gestion CRUD des types de services (catégorisation des Rôles)
Voir **M2-M7**. Les 7 types hardcodés (Documentation/Code/Design/…) doivent devenir une table CRUD. Nouvelle page admin.

### NF-3 — Profils de missions (Agents)
**Concept** : refonte fondamentale du comportement par défaut de `composition_builder`.

**Modèle actuel (phase 5a)** : 1 Agent → 1 Role → prompt = identité + **tous** les documents (pollution permanente).

**Modèle cible** :
- Agent instantié **sans profil** → prompt = identité seule (léger, non pollué)
- Agent instantié **avec profil X** → prompt = identité + documents sélectionnés par X
- Un **profil** = liste de documents sélectionnés cross-catégorie (roles + missions + compétences + futures catégories custom)
- Les profils sont **scopés à l'agent**, stockés au niveau M4

**Design :**
```sql
CREATE TABLE agent_profiles (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id        UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    document_ids    UUID[] NOT NULL DEFAULT '{}',    -- refs soft à role_documents.id
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (agent_id, name)
);

CREATE INDEX idx_agent_profiles_agent ON agent_profiles(agent_id);
```

**Choix délibéré** : `document_ids UUID[]` en colonne plutôt que table de liaison avec FK. Raison : si un `role_document` est supprimé (ou si l'agent change de Role), les UUIDs deviennent orphelins — ce qu'on **veut détecter** comme erreur plutôt que silencieusement cascader.

**Détection d'erreur** :
- `build_preview(agent_id, profile_id?)` resolve chaque UUID via `role_documents`
- UUIDs introuvables → `validation_errors.append("Profile X references N missing docs")`
- L'agent passe en état "erreur de composition" → visible en liste (badge rouge) et dans le builder (bannière)

**Même mécanisme** couvre 2 cas :
1. Document supprimé depuis la page Roles
2. Role de l'agent changée (les UUIDs du profil appartiennent à l'ancienne Role)

**Décisions utilisateur (validées) :**
- ✅ Pas de default profile sur l'agent — toujours explicite au runtime
- ✅ Suppression d'un doc permise, agent en erreur si référencé

**Items :**

| ID | Titre | Sévérité |
|---|---|---|
| **M4-NEW-B1** | Migration 016 `agent_profiles` avec `document_ids UUID[]` | 🔴 |
| **M4-NEW-B2** | `composition_builder.build_preview` par défaut = identité seule + support `profile_id` + détection broken refs | 🔴 |
| **M4-NEW-B3** | État "erreur de composition" propagé dans `ConfigPreview` + `AgentSummary.has_errors` pour list view | 🔴 |
| **M4-NEW-M1** | CRUD `agent_profiles` service + router + endpoints + `GET /config-preview?profile_id=XXX` | 🟠 |
| **M4-NEW-M2** | UI section "Profils de missions" dans AgentEditorPage (liste + éditeur checkbox grid par catégorie + broken refs en rouge) | 🟠 |
| **M4-NEW-M3** | Badge 🔴 "En erreur" dans AgentsPage list view quand `has_errors == true` | 🟠 |

**Dépendances strictes :** M2-B1 (sections dynamiques) → M4-NEW-B1 → M4-NEW-B2 → M4-NEW-B3 → M4-NEW-M1 → M4-NEW-M2 → M4-NEW-M3

---

## Ordre de correction recommandé (révisé avec feedback user)

Priorisation par **valeur user / effort / dépendances**. Le feedback utilisateur a réordonné certains items — notamment **M1-B4 (bug save) passe en tête** car c'est un bug critique visible immédiatement.

### Sprint 0 — Bug fix urgent (1 journée)
0. **M1-B4** 🐛 Bug : contenu qui disparaît au save (state React non resync après mutation)

### Sprint 1 — Cross-cutting (débloque plusieurs modules + pose les fondations design)
1. **TR-4** Responsive mobile — à faire **pendant** la refonte 5b-B/C sinon double travail
2. **TR-1** Composant `EnvVarStatus` + hook `useEnvVarStatus` → applique M0/M3/M4
3. **M2-B1 + M2-M5** Sections dynamiques + suppression de catégories vides (1 chantier cohérent)

### Sprint 2 — Cohérence spec + typage Dockerfiles
4. **M2-D1 + M2-D2** Trancher spec drift rôles (restaurer OU mettre à jour la spec)
5. **M1-B1 + M1-B3 + M1-B5** Typage fichiers Dockerfile + handling `run.cmd.md` + auto-seed Dockerfile/entrypoint.sh undeletable (1 chantier cohérent)

### Sprint 3 — Features manquantes bloquantes
6. **M0-B1 + M0-B2** Agent-scoped secrets end-to-end + `used_by` real
7. **M3-B1 + M3-M4** UI éditeur paramètres MCP (→ pattern TR-2)
8. **M1-M2** Substitution paramètres Dockerfile au build
9. **M1-M1** Skip rebuild sur hash inchangé

### Sprint 4 — UX BuildModal + features manquantes non bloquantes
10. **M1-M4 + M1-M5 + M1-M6 + M1-P3** Refonte `BuildModal` + panneau d'édition fichiers : auto-scroll logs, erreurs en rouge, bouton copy, panel plein hauteur (1 chantier UI cohérent)
11. **M2-M1** Tab Runtime roles (→ pattern TR-2)
12. **M0-M1** UI édition secrets
13. **M3-M2** Bouton Edit discovery services
14. **M3-B2 + M3-P1** Liens cliquables repo/doc
15. **M4-B1 + M4-P1** Image status affiché en liste + detail
16. **M4-M1** Paramètre `default_model`

### Sprint 5 — Features hors spec + nice-to-have
17. **NF-2 / M2-M7** Page CRUD des types de services
18. **M2-M6** Refonte UX du Chat tab roles (split-view avec docs) — **dépend de M2-M2**
19. **M2-M2** Implémentation effective du Chat LLM roles (gros chantier)
20. **NF-1** Chat Docker builder (gros chantier, dépend de patterns posés par M2-M2)
21. **M1-B2** Documentation + validation protocole entrypoint JSON
22. **M1-M3** Volumes normalisés
23. **M2-M3** Hiérarchie répertoires (parent_path déjà en DB)
24. **M2-M4** Import roles
25. **M3-M3** Section "recherche MCP" sur DiscoveryServices
26. **M1-P1** Logs streaming SSE (vs polling actuel)

### Hors sprint
- **M3-P2** Marquer 3d explicitement comme deferred dans les docs
- **M4-P2** Ajouter pointer vers plan 5b dans les fichiers M4

---

## Ordonnancement vs. refonte design (Passes 5b-B / 5b-C)

**Question critique** : dans quel ordre par rapport aux Passes 5b-B (refonte AgentsPage + AgentEditorPage) et 5b-C (refonte M0-M3 pages) ?

Proposition :
1. **Sprint 0** (bug save) immédiat — sinon tout le monde le voit
2. **Sprint 1 thème TR-4 responsive** doit être fait **pendant** 5b-B/C — chaque page refaite en design system est responsive dès la première passe, sinon on refait 2 fois
3. **Sprints 2-4** (backend + logique manquante) peuvent être fait **en parallèle** de 5b-B/C — les corrections backend n'impactent pas le design, et les corrections frontend UX qui ne touchent que M0-M3 peuvent être intégrées dans la refonte 5b-C
4. **Sprint 5** (features hors spec + chats LLM) reste séparé et vient après

Ordre suggéré d'exécution :
```
Sprint 0 (bug save)
  ↓
5b-B (refonte M4) + TR-4 responsive
  ↓
Sprint 1-2-3 en parallèle de 5b-C (refonte M0-M3)
  ↓
Sprint 4 (UX BuildModal) dans 5b-C directement
  ↓
Sprint 5 (features hors spec)
```

---

## Décisions à prendre par l'utilisateur

1. **M2 spec drift (TR-3)** — 2 items :
   - (a) Restaurer paramètres LLM dans Roles, OU (b) mettre à jour la spec pour refléter le drop
   - (a) Restaurer `prompt_agent_md`, OU (b) formaliser dans la spec que le prompt agent est composé à la volée
   - **Ma recommandation** : option (b) dans les deux cas — la spec devient cohérente avec le design actuel, les champs LLM reviendront quand on supportera vraiment le multi-LLM

2. **Ordre des sprints + intercalage avec design** — OK avec la proposition d'ordonnancement ci-dessus ?

3. **NF-2 Types de services** — page dédiée autonome (`/service-types`) ou sous-page de Roles ? Admin-only ou visible à tous les users ?

4. **NF-1 Chat Docker builder** — où vit-il : bouton "Créer via chat" dans `DockerfilesPage` → modal, page dédiée, ou mini-chat dans la sidebar ?

5. **Chats LLM** (M2-M2 + NF-1) — besoin d'une abstraction commune `useLLMChat` + store de conversations, ou 2 implémentations indépendantes ? Les deux utilisent Anthropic via Module 0.

6. **Responsive breakpoints** — OK avec `sm 640 / md 768 / lg 1024` Tailwind standard ? Priorité mobile (smartphone) uniquement, ou tablette aussi ?

7. **BuildModal M1-M4/5/6** — tu veux colorisation ANSI des logs (parser des couleurs ANSI du build Docker) ou juste highlight keyword `error` en rouge ?
