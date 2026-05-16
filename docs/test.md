# Procédure de test d'intégration

Cette procédure valide bout-en-bout que le code de la branche `dev` se déploie
proprement sur un LXC Proxmox fraîchement créé : création du container,
installation Docker, clone du repo, exécution de `dev-deploy.sh`, et smoke
test du backend.

**Une seule commande depuis ton poste local**. Le script `run-test.sh` pousse
tout sur `pve` et déclenche le test à distance — aucune intervention manuelle
sur l'hôte Proxmox.

```bash
./scripts/run-test.sh
```

---

## Architecture

```
┌── poste local (Windows / branche dev) ────────────────────────────┐
│                                                                   │
│   ./scripts/run-test.sh                                           │
│        │                                                          │
│        │  1. scp scripts/test-create-lxc.sh  ──┐                  │
│        │  2. scp scripts/.env.test.<project name>   ──┤                   │
│        │  3. ssh pve "test-create-lxc.sh …"  ─┤                   │
│        ▼                                       │                  │
│                                                ▼                  │
│   ┌── hôte Proxmox (pve) ─────────────────────────────────────┐   │
│   │   /opt/scripts/test-create-lxc.sh .env.test.<project name>        │   │
│   │       ├─ trouve un CTID libre dans 900..999               │   │
│   │       ├─ pct create + install Docker                      │   │
│   │       ├─ pct push .env.git + git clone (branche dev)      │   │
│   │       ├─ pct exec ./dev-deploy.sh                         │   │
│   │       └─ 7 assertions (Docker OK, /health, …)             │   │
│   │                                                            │   │
│   │   ┌── LXC créé : test-<project name>-<CTID> ───────┐       │   │
│   │   │   /opt/<project name>  (clone branche dev)     │       │   │
│   │   │   docker compose -f docker-compose.dev.yml up │       │   │
│   │   └────────────────────────────────────────────────┘       │   │
│   └────────────────────────────────────────────────────────────┘   │
└───────────────────────────────────────────────────────────────────┘
```

---

## Pré-requis

### Côté poste local

| Pré-requis | Vérification |
|---|---|
| Alias SSH `pve` dans `~/.ssh/config` | `ssh pve hostname` retourne le hostname Proxmox |
| `scp` disponible | fourni par OpenSSH (standard) |
| Sur la branche `dev` du repo | `git branch --show-current` → `dev` |

### Côté hôte Proxmox (`pve`)

| Pré-requis | Vérification |
|---|---|
| `pct` (cli Proxmox) | `ssh pve "command -v pct"` |
| `python3` | parsing du JSON de `create-lxc.sh` |
| `curl` | check API GitHub + smoke `/health` |
| `/opt/scripts/.env.git` | PAT GitHub valide (scope `repo`), voir ci-dessous |

Le script télécharge automatiquement `create-lxc.sh` et `list-instances.sh`
depuis le repo public `Configurations/Proxmox` s'ils ne sont pas déjà
présents sous `/opt/scripts/`. Aucune action manuelle pour ces deux scripts.

### Le `.env.git` (token GitHub)

Procédure détaillée dans
[`Install-dev.md` § Étape 2](../Install-dev.md#étape-2--accès-github-via-personal-access-token-pat).
Résumé minimal **côté pve uniquement** :

```bash
ssh pve "mkdir -p /opt/scripts && chmod 700 /opt/scripts"
ssh pve "cat > /opt/scripts/.env.git" <<'EOF'
TOKEN=ghp_REMPLACE_PAR_TON_TOKEN
EOF
ssh pve "chmod 600 /opt/scripts/.env.git"
```

Le test échoue tôt avec un message explicite si le fichier est absent, vide,
invalide (HTTP 401) ou sans accès au repo (HTTP 404).

---

## Le fichier de paramètres

`scripts/.env.test.<project name>` (versionné dans le repo) :

```bash
GIT_REPO="gaelgael5/<project name>"
GIT_BRANCH="dev"
APP_DIR="/opt/<project name>"
DEPLOY_SCRIPT="./dev-deploy.sh"

CTID_MIN=900
CTID_MAX=999
SCRIPTS_DIR="/opt/scripts"
```

| Variable | Rôle |
|---|---|
| `GIT_REPO` | `<org>/<repo>` cloné dans le LXC |
| `GIT_BRANCH` | Branche à tester (typiquement `dev`) |
| `APP_DIR` | Chemin absolu du clone dans le LXC |
| `DEPLOY_SCRIPT` | Script de déploiement relatif à `APP_DIR` |
| `CTID_MIN` / `CTID_MAX` | Plage de CTID candidats (le premier libre est pris) |
| `SCRIPTS_DIR` | Dossier hôte qui contient `.env.git`, `create-lxc.sh`, `list-instances.sh` |

Pour tester un autre projet (par ex. `rag`, `harpocrate`), créer
`scripts/.env.test.<projet>` avec les valeurs adaptées et lancer :

```bash
./scripts/run-test.sh .env.test.<projet>
```

---

## Lancer le test

```bash
./scripts/run-test.sh
```

Variantes :

| Commande | Effet |
|---|---|
| `./scripts/run-test.sh` | Config par défaut `scripts/.env.test.<project name>`. LXC conservé. |
| `CLEANUP=1 ./scripts/run-test.sh` | Purge le LXC créé à la fin du test (`pct destroy --purge`). |
| `./scripts/run-test.sh .env.test.staging` | Config alternative depuis `scripts/.env.test.staging`. |
| `SSH_HOST=pve2 ./scripts/run-test.sh` | Override de l'hôte SSH cible (défaut : `pve`). |

---

## Ce qui se passe pas-à-pas

`run-test.sh` (côté poste local — 3 étapes) :

1. `ssh pve "mkdir -p /opt/scripts"` puis `scp scripts/test-create-lxc.sh pve:/opt/scripts/` + `chmod +x`
2. `scp scripts/.env.test.<project name> pve:/opt/scripts/`
3. `ssh -t pve "cd /opt/scripts && CLEANUP=… ./test-create-lxc.sh .env.test.<project name>"`

`test-create-lxc.sh` (côté pve — 8 étapes) :

| # | Étape | Description |
|---|---|---|
| 0 | Bootstrap | Charge `.env.test.<project name>`. Vérifie les 7 variables requises. Télécharge `list-instances.sh` et `create-lxc.sh` depuis `Configurations/Proxmox` si absents de `SCRIPTS_DIR`. |
| 1 | Auth GitHub | Lit `${SCRIPTS_DIR}/.env.git`. Vérifie le token via `/api/github.com/user` et `/api/github.com/repos/${GIT_REPO}`. Échoue tôt si KO. |
| 2 | CTID libre | Énumère les LXC existants via `list-instances.sh` et choisit le premier CTID disponible dans la plage `[CTID_MIN..CTID_MAX]`. |
| 3 | Nom | Calcule le nom du LXC : `test-<repo>-<CTID>`. |
| 4 | Création LXC | `create-lxc.sh <CTID> <NAME> --docker`. Provisionne le container, installe Docker, lance `hello-world`. Récupère le JSON de sortie (IP, version Docker, etc.). |
| 5 | Push `.env.git` + clone | `pct push` du token dans le LXC, puis `git clone --branch ${GIT_BRANCH} https://${TOKEN}@github.com/${GIT_REPO}.git ${APP_DIR}`. |
| 6 | Déploiement | Exécute `${DEPLOY_SCRIPT}` dans le LXC. Pour <project name> : `dev-deploy.sh` provisionne `.env` (auto-génération secrets + bcrypt admin), build les images, lance la stack. |
| 7 | Validation | Joue 7 assertions (tableau ci-dessous). Compte pass / fail. |
| 8 | Nettoyage | Si `CLEANUP=1` : `pct stop` + `pct destroy --purge`. Sinon, affiche les commandes manuelles. |

### Les 7 assertions

| # | Critère |
|---|---|
| 1 | `status == "ok"` dans le JSON de `create-lxc.sh` |
| 2 | `machine.systeme.ip` non vide (DHCP obtenu) |
| 3 | `docker.docker_ok == 1` |
| 4 | `docker.hello_world_ok == true` |
| 5 | `${APP_DIR}` existe dans le LXC |
| 6 | `${APP_DIR}/.git` existe (clone complet) |
| 7 | `curl http://<CT_IP>:8000/health` répond — **smoke applicatif backend** |

---

## Sortie attendue

À la fin du run, rapport :

```
=========================================
  RÉSULTAT DES TESTS
=========================================
  Projet       : <project name>
  CTID         : 900
  Nom          : test-<project name>-900
  IP           : 192.168.10.xxx
  Branche      : dev
  Sources      : /opt/<project name>
  -----------------------------------------
  Tests OK     : 7/7
  Tests FAIL   : 0/7

  Statut       : OK SUCCES
=========================================
```

Codes de sortie :
- `0` : tous les tests passés
- `1` : au moins un test a échoué ou erreur fatale en cours de route

---

## Inspecter le LXC créé (CLEANUP non défini)

```bash
# Entrer dans le LXC depuis pve
ssh pve
pct enter <CTID>

# Logs backend depuis pve
ssh pve "pct exec <CTID> -- docker compose -f /opt/<project name>/docker-compose.dev.yml logs --tail=200 backend"

# Inspecter le .env généré par dev-deploy.sh
ssh pve "pct exec <CTID> -- cat /opt/<project name>/.env"
```

Supprimer manuellement après inspection :

```bash
ssh pve "pct stop <CTID> && pct destroy <CTID> --purge"
```

---

## Dépannage

### `Fichier de config introuvable` côté local
Vérifier que `scripts/.env.test.<project name>` existe. Si tu as renommé ou supprimé,
le recréer ou passer le bon nom : `./scripts/run-test.sh <ton-fichier>`.

### `Could not resolve hostname pve`
Ajouter l'alias dans `~/.ssh/config` :
```
Host pve
    HostName 192.168.10.41
    User root
    IdentityFile ~/.ssh/id_shellia
```
Ou override : `SSH_HOST=192.168.10.41 ./scripts/run-test.sh`.

### `ARRÊT : /opt/scripts/.env.git absent` (côté pve)
Le PAT GitHub n'est pas posé sur l'hôte Proxmox. Voir § « Le `.env.git` »
ci-dessus.

### `ARRÊT : token invalide ou expiré` (HTTP 401)
Le PAT a expiré ou a été révoqué. En regénérer un sur
<https://github.com/settings/tokens>, scope `repo`, puis remplacer la
valeur dans `/opt/scripts/.env.git` sur pve.

### `ARRÊT : impossible d'accéder au repo (HTTP 404)`
Soit le token n'a pas le scope `repo`, soit le compte GitHub authentifié n'a
pas accès au repo privé. Vérifier les deux.

### `Aucun CTID disponible dans la plage 900–999`
Plus de 100 LXC de test traînent. Purger les anciens sur pve :
```bash
ssh pve "for id in \$(seq 900 999); do pct status \$id 2>/dev/null && pct destroy \$id --purge 2>/dev/null; done"
```

### `dev-deploy.sh a échoué dans le LXC`
Le déploiement a planté côté LXC. Inspecter :
```bash
ssh pve "pct exec <CTID> -- bash -c 'cd /opt/<project name> && docker compose -f docker-compose.dev.yml logs --tail=200 backend'"
```
Causes fréquentes : `HARPOCRATE_KEY` non renseignée, image backend qui ne
build pas, secret non interpolé dans `.env`.

### `Backend agflow ne répond pas sur /health` (test 7 FAIL)
La stack a démarré mais le backend n'a pas atteint l'état healthy dans le
délai imparti. Vérifier :
1. `pct exec <CTID> -- docker compose ps` — `agflow-backend` doit être `Up (healthy)`
2. Migrations DB : `docker compose logs backend | grep migration`
3. Connexion Postgres : `DATABASE_URL` dans `.env` cohérent avec le `POSTGRES_PASSWORD` généré

---

## Quand l'utiliser

- **Avant une PR vers `main`** : valider que la branche `dev` est déployable
  depuis zéro.
- **Après refactor de `dev-deploy.sh`, `docker-compose.dev.yml` ou
  `.env.example`** : vérifier qu'on n'a pas cassé l'amorçage.
- **Smoke quotidien** (cron côté Proxmox) : détecter au plus tôt une
  régression de boot.

Hors de ces cas, préférer un déploiement direct sur un LXC déjà provisionné
plutôt que de recréer un LXC à chaque fois.
