# Fragment — Déploiement (machine de test, scripts, exposition)

> Sources : globals › « Fichier d'instructions — Script de déploiement sur machine de test
> (agnostique) » (révision 2026-09-11), « Déploiement et machines de test — leçons
> d'incidents réels » (2026-09-25), « Fichier d'instructions — Déclarer un service exposé au
> portail (annuaire, code TOTP) » (2026-09-16), « STANDARD — Instance de dev/test » (2026-09-25).
> Déclencheur : avant de modifier `dev-deploy.sh`, `scripts/*.sh`, un `docker-compose*.yml`,
> un `Dockerfile`, `frontend/nginx.conf` — ou avant tout déploiement / diagnostic sur `test1`.

Les règles de branche, de livraison et de fin de tâche sont dans `CLAUDE.md` (blocs
« Branche de développement », « Machines de test », « Livrer sur une machine de test »,
« Définition de terminé ») : push obligatoire sur `dev`, **aucun merge vers `main` sans demande
explicite de l'humain**, livraison par clone puis `dev-deploy.sh`, tâche finie quand les tests
passent. Ce fragment n'en porte que la déclinaison propre à Harpocrate.

## Les trois chemins de déploiement du dépôt

| Chemin | Script | Pour qui |
|---|---|---|
| Dev / test (build local) | `./dev-deploy.sh [branche] [--reset]` + `docker-compose-dev.yml` | **l'agent**, sur `test1`, librement |
| Prod (images GHCR) | `scripts/setup.sh` puis `scripts/refresh.sh` + `docker-compose.yml` | l'utilisateur, **jamais l'agent** |
| Intégration LXC Proxmox | `scripts/run-test.sh` (docflow « Procédure de test d'intégration (LXC) ») | l'utilisateur, sur demande |

Images publiées par `.github/workflows/build-images.yml` (GHCR). Multi-instances :
`docker-compose.cluster.yml` (Mosquitto). HA Postgres : `infra/patroni/`, `infra/etcd/`.

## Machine de test `test1`

`test1` est **à la disposition de l'agent** pour livrer, tester et valider — rien à demander
pour s'en servir. C'est là que le test est le plus révélateur : **la privilégier** pour valider.

- Ce qui a été constaté sur la machine (nom d'hôte, versions, stacks voisines, ports libres) est
  tenu dans `ia_instructions/tests_and_ressources.md` — le lire avant d'agir, le mettre à jour
  quand l'état change.
- **Avant chaque intervention** : `ssh test1 hostname` doit rendre `host-test-23` ; sinon
  l'alias a été recyclé → s'arrêter et le signaler.
- Premier déploiement : cloner la branche `dev` dans un répertoire propre à Harpocrate, et
  isoler la stack par les variables du STANDARD « Instance de dev/test » §3 — `DATA_ROOT`
  dédié, `COMPOSE_PROJECT_NAME=harpocrate`, ports hôte choisis **parmi ceux vérifiés libres**
  au moment du déploiement (jamais devinés, jamais pris à une autre stack). Le dépôt est
  public : cloner en **HTTPS** (`REPO_URL=https://github.com/gaelgael5/harpocrate.git`), la
  machine n'a pas de clé GitHub.
- Cohabitation sur une machine partagée : n'agir que sur le projet compose `harpocrate` ;
  jamais `docker system prune`, jamais un `down`/`rm` sur un autre projet, jamais de volume
  d'autrui.

## Ce que le script de déploiement doit garantir — et état de `dev-deploy.sh`

Chaque garde vient d'une panne réelle ; lire les leçons (globals › « Déploiement et machines
de test — leçons d'incidents réels ») **avant de retirer une garde**.

| # | Garde exigée | `dev-deploy.sh` (2026-09-23) |
|---|---|---|
| 0 | Survivre à la perte de session : ignorer SIGHUP, journaliser dans un fichier (drapeau pour désactiver) | ❌ absent |
| 1 | Prérequis vérifiés, message contenant la commande d'installation | ✅ docker, compose v2 |
| 2 | Se mettre à jour depuis git **puis se ré-exécuter** dans sa version fraîche ; mode bootstrap deploy key si dépôt privé | ⚠ `git pull --ff-only` mais **pas de ré-exécution** |
| 3 | Initialisation idempotente, jamais de régénération de ce qui est durable | ✅ `data/` |
| 4 | Compléter la config sans écraser l'existante | ✅ `.env` généré si absent, `sync_new_vars_from_example` sinon |
| 5 | Construire depuis la copie fraîche, `down --remove-orphans`, relancer | ✅ |
| 6 | Sondes de port **après** l'arrêt, jamais avant | ⚠ `detect_frontend_https_port` interroge la stack **avant** l'arrêt (seulement à la création du `.env`) |
| 7 | Attendre un conteneur réellement exécutable avant de migrer | ➖ migrations au boot du backend (lifespan) |
| 8 | Vérifier que le schéma est à jour, pas seulement le code de retour | ❌ aucun contrôle de `_migrations` |
| 9 | Contrôle de santé final avec plafond, sur le bon port | ❌ se contente de `compose ps` |
| 10 | Purge hebdomadaire bornée (cache de build + images détaggées, témoin horodaté, jamais bloquante) | ❌ absent — et sur `test1` partagée, **ne purger que ses propres images** |
| 11 | Modes destructifs isolés, explicites, confirmés | ⚠ `--reset` explicite mais **sans confirmation** |

Autres points relevés : le script **affiche en clair** le mot de passe admin local généré
(à proscrire dès que la sortie est journalisée, garde 0) ; `REPO_URL` par défaut en SSH ;
Postgres publié sur `0.0.0.0:5432` dans `docker-compose-dev.yml`.

Ces écarts sont **à traiter dans une tâche dédiée** validée par l'utilisateur, pas au passage
d'un autre travail.

## Pièges connus (extraits des leçons d'incidents)

**Le script doit être idempotent.** On le relance après un échec partiel, souvent dans l'urgence. S'il ne supporte pas d'être rejoué, il transforme un incident en panne.

**Un journal de déploiement doit survivre au terminal.** Sans fichier, la seule trace d'un déploiement qui a mal tourné disparaît avec la fenêtre.

**Les étapes numérotées dans les messages doivent correspondre à la réalité.** Un script qui annonce « 4/5 » alors qu'il en fait six laisse croire qu'il reste une étape quand il en reste deux.

**Le vert trompeur** — migrations non jouées, schéma en retard, contrôle de santé qui vise à côté : vérifier le **résultat**, jamais le code de retour.

**git 2.39.5 + HTTP/2 contre GitHub → 401 intermittent** sur un dépôt public (`GET info/refs`
200 puis `POST git-upload-pack` 401). Ce n'est ni un dépôt privé ni un quota : forcer HTTP/1.1
au niveau système (`harden-git-http.sh`, dépôt `ressources`). **Dix essais, pas deux** avant de
conclure sur un défaut intermittent ; ne pas valider une hypothèse git avec `curl`.

**Ne jamais simuler le service livré** par un conteneur jetable : le livrer par
`dev-deploy.sh`, puis lire les journaux réels (`docker compose -f docker-compose-dev.yml logs
backend`, et Loki). Les **outils de test** (runner, base jetable, doublure, outil de mesure)
tournent, eux, librement dans le Docker de `test1`.

## Déclarer un service exposé au portail

Si l'UI Harpocrate de `test1` doit être atteinte depuis l'extérieur, elle se **déclare** à
l'annuaire du portail, authentifiée par un **code TOTP** obtenu via la primitive MCP
`totp_code` (8 chiffres, 30 s), transmis en `Authorization: Bearer <login>:<code>` dans
`PORTAL_TOKEN` — **jamais** le `PORTAL_TOKEN` admin, jamais le code en argv, jamais journalisé.
Routes ouvertes au TOTP : `PUT /me/expositions` (déclarer), `DELETE /me/expositions/{slug}`
(révoquer — un code **différent** par appel, anti-rejeu). Page d'entrée ≠ `/` → `--path`.
Détail : globals › « Fichier d'instructions — Déclarer un service exposé au portail ».

## Part de checklist

- [ ] `ssh test1 hostname` = `host-test-23` vérifié avant d'agir
- [ ] Le commit est poussé sur `dev` AVANT le déploiement ; déploiement par `dev-deploy.sh`, sans construction manuelle ; aucun merge vers `main` sans demande explicite
- [ ] Stack isolée (`DATA_ROOT`, `COMPOSE_PROJECT_NAME=harpocrate`, ports vérifiés libres) ; aucun conteneur, volume ou image d'un autre projet touché
- [ ] Le script modifié se relance sans danger après un échec partiel
- [ ] Il n'écrase aucun secret ni élément cryptographique existant, et n'en affiche aucun
- [ ] Les sondes de port se font après l'arrêt de la stack, pas avant
- [ ] La conclusion s'appuie sur les journaux réels et un contrôle de santé, pas sur le code de retour
- [ ] La validation a eu lieu sur `test1` dès qu'elle pouvait révéler davantage que le local ; la tâche n'est finie que quand les tests passent
