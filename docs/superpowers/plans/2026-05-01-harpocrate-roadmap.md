# Harpocrate — Roadmap d'implémentation

> **Document maître.** Donne la vue macro des 11 lots, leurs dépendances, les divergences à corriger sur le code existant, et le planning par jalon. **Chaque lot a (ou aura) son propre plan détaillé** dans ce dossier.

**Goal:** Construire `Harpocrate`, un gestionnaire de secrets E2E zero-knowledge, par lots indépendants livrables.

**Architecture:** Backend FastAPI + asyncpg + PostgreSQL 16 ; SDK Python + CLI bash ; UI React/Mantine. Crypto E2E (Argon2id, AES-256-GCM, RSA-OAEP) côté client uniquement — le serveur ne voit jamais les valeurs en clair.

**Tech Stack:** Python 3.12 / FastAPI / asyncpg / Pydantic v2 / structlog / PostgreSQL 16 / Keycloak OIDC / React 18 / Mantine v7 / Zustand / Zod / Vite / argon2-browser (WASM) / WebCrypto API.

---

## 1. État actuel vs spec — divergences à corriger

| Aspect | Existant (à corriger) | Cible (spec) | Lot concerné |
|---|---|---|---|
| Layout backend | `backend/src/harpocrate/main.py` | `backend/app/{api,core,db,models,services}/` | LOT_00 |
| Env prefix | `POSTGRES_*`, `LOG_LEVEL` | `HARPOCRATE_*` | LOT_00 |
| `pyproject.toml` | minimal | mypy strict, ruff étendu, deps verrouillées | LOT_00 |
| Endpoint health | `/health` | `/v1/health` (versionné) | LOT_00 |
| Migrations | aucune | `migrations/*.sql` + `apply_migrations.py` (checksum) | LOT_00 |
| Stack frontend | shadcn + Tailwind + i18next | Mantine v7 + Zustand + Zod + ReactFlow + i18next | LOT_11 |
| Validation client | _absente_ | Zod (matche Pydantic backend exactement) | LOT_11 |
| Crypto navigateur | _absente_ | argon2-browser (WASM) + WebCrypto | LOT_11 |
| `CLAUDE.md` | mentionne `agflow.docker` | doit décrire Harpocrate | dès LOT_00 |

**Conséquence sur les acquis** :
- Le squelette `backend/src/harpocrate/` sera **remplacé** par `backend/app/` au LOT_00 (réécriture, pas migration — la spec donne tout le code).
- Les Dockerfiles multi-stage et le compose dev/deploy + scripts CI/CD restent **valides**, ils sont alignés sur la cible. Seuls les paths internes (`src/` → `app/`) et le `CMD` (uvicorn target) bougent.
- Le frontend actuel (shadcn/Tailwind) est **supprimé au LOT_00** (Task 11). La vraie UI Mantine arrive au LOT_11.

## 2. Découpage en lots

| Lot | Nom | Dépendances | Complexité | Jalon |
|---|---|---|---|---|
| 00 | Foundations (FastAPI, config, healthcheck, migrations) | — | M | — |
| 01 | Schéma DB complet (8 tables, triggers, FKs, CHECKs) | 00 | M | — |
| 02 | Auth Keycloak + bootstrap user (`/me/*`) | 01 | M | — |
| 03 | Wallets CRUD + `/users/lookup` + transfer-ownership | 02 | M | — |
| 04 | Grants (partage, permissions bitmap, révocation) | 03 | S | — |
| 05 | Secrets CRUD (sans placeholder) | 04 | M | — |
| 06 | Placeholders + 9 générateurs (validation côté serveur, exécution côté client) | 05 | L | — |
| 07 | Export / Import structure de wallet | 06 | M | **M1** : MVP backend humain |
| 08 | API keys (token `hrpv_*`, HMAC, Argon2id, cache, cascade) | 07 | XL | — |
| 09 | SDK Python (`harpocrate`) + CLI bash (`harpocrate-cli`) + 9 générateurs côté client | 08 | XL | **M2** : MVP automation |
| 10 | Audit log API (filtre par permission, pagination, job purge) | 09 | M | — |
| 11 | UI Web (Mantine, OIDC, bootstrap, unlock, CRUD complet, audit) | 10 | XL | **M3** : MVP user-facing |

**Estimation** (1 dev senior, TDD discipliné, sans overlap) :
- Backend (00 → 10) : **~3 mois**
- SDK + CLI (09) : **~3-4 semaines** (compte dans les 3 mois si fait en parallèle)
- UI (11) : **~6-8 semaines**

**⚠️ Total ~6 mois de dev.** C'est au-delà des 3 mois mentionnés comme seuil d'alerte dans le `CLAUDE.md`. Approche recommandée : **livrer lot par lot, valider M1 avant d'engager M2, et M2 avant M3**. Chaque jalon donne un livrable utilisable en l'état.

## 3. Stratégie d'exécution

### 3.1 Un plan détaillé par lot
Ce document est la roadmap. Chaque lot aura son propre plan TDD bite-sized dans `docs/superpowers/plans/2026-MM-DD-lot-NN-<nom>.md`. Le LOT_00 est livré en parallèle de cette roadmap. Les suivants seront produits **au fur et à mesure** — on n'écrit pas le plan détaillé du LOT_08 avant d'avoir fini le LOT_07, parce que les apprentissages des lots précédents informent les choix.

### 3.2 Ordre strict des dépendances
Le diagramme du `OVERVIEW.md` est non-négociable :
```
00 → 01 → 02 → 03 → 04
                  ↘ 05 → 06 → 07 → 08 → 09 → 10
                                              ↘ 11
```

### 3.3 Discipline TDD
- **Test rouge → impl → test vert → commit** (cycle court)
- Couverture cible : 80% global, 100% sur les modules crypto
- Aucun lot considéré "fini" sans `pytest`, `ruff check`, `mypy --strict` qui passent

### 3.4 Sécurité — checklist transverse à chaque endpoint
Reproduit du `OVERVIEW.md §14`, à appliquer pour chaque PR :
- [ ] Auth requise (JWT, API key, ou public)
- [ ] Type d'auth approprié (humain seul, ou mixte)
- [ ] Permission requise déclarée et vérifiée
- [ ] Validation Pydantic stricte du body
- [ ] Pas de log du body sur les endpoints `/secrets`
- [ ] Audit log avec metadata pertinente, success/error
- [ ] Codes d'erreur métier (pas juste 400 générique)
- [ ] Constant-time compare pour tout hash
- [ ] AES-GCM avec nonce unique (jamais réutilisé)

### 3.5 Décisions transverses tranchées

1. **Realm Keycloak** : `yoops` (realm partagé avec l'écosystème yoops.org, instance `keycloak.yoops.org`).
2. **Préfixe token API key** : `hrpv_` (à publier dans `secret_scanning` GitHub à terme).
3. **Domaine public** : `vault.yoops.org` (sous-domaine du tunnel Cloudflare existant).
4. **Frontend** : le squelette `frontend/` shadcn/Tailwind est supprimé au LOT_00 (option A). La vraie UI Mantine arrive au LOT_11.
5. **Décisions différées** :
   - **OIDC frontend** : choix de la lib (`react-oidc-context` vs `oidc-client-ts`) à brainstormer au début du LOT_11.
   - **Master HMAC key** : env var `HARPOCRATE_HMAC_KEY` au LOT_00 ; migration HSM/TPM/KMS sur la roadmap post-MVP.

## 4. Livrables après cette session

- ✅ Specs renommées (`ag.flow Vault` → `Harpocrate`, `AGFLOW_VAULT_*` → `HARPOCRATE_*`, `agv_` → `hrpv_`)
- ✅ Cette roadmap (`2026-05-01-harpocrate-roadmap.md`)
- ✅ Plan détaillé LOT_00 (`2026-05-01-lot-00-foundations.md`)
- ⏳ Mise à jour du `CLAUDE.md` (à faire dans le LOT_00, première tâche)
- ⏳ Squelette backend cible + tests + Docker — exécution du plan LOT_00
