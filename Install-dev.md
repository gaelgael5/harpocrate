# Installation environnement de DEV — Harpocrate

Cette procédure monte une instance Harpocrate **complète** (Postgres + backend
FastAPI + frontend Nginx) sur un serveur de dev. Cible : LXC Proxmox, VM, ou
toute machine Linux avec Docker installé.

Pour la **prod** (pull GHCR, pas de build local), utiliser `scripts/refresh.sh`.

---

## Étape 1 — Préparer le serveur

### 1.1 Container LXC (si Proxmox)

Sur l'hôte Proxmox, créer un LXC Docker-ready :

```bash
bash <(wget -qO- https://raw.githubusercontent.com/Configurations/Proxmox/main/LXC/create-lxc.sh) 203 harpocrate-dev --docker
```

Remplace `203` par le CTID souhaité et `harpocrate-dev` par le nom du container.
Le flag `--docker` installe Docker dans le LXC.

> **Hors Proxmox** : n'importe quelle machine Linux avec Docker ≥ 24.0 et
> Docker Compose v2 fonctionne. Skipper cette étape, passer directement à 1.2.

### 1.2 Entrer dans le serveur

```bash
pct enter 203                    # depuis l'hôte Proxmox
# ou : ssh user@harpocrate-dev   # autre serveur
```

---

## Étape 2 — Accès SSH GitHub

Le repo est privé. Génère une clé SSH dédiée au déploiement :

```bash
ssh-keygen -t ed25519 -C "harpocrate-dev-deploy"
# Entrée pour accepter ~/.ssh/id_ed25519
# Passphrase vide (déploiement automatique)

eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519
cat ~/.ssh/id_ed25519.pub
```

Ajoute la clé publique sur GitHub :

1. <https://github.com/settings/keys> → **New SSH key**
2. Title : `harpocrate-dev <hostname>`
3. Coller la clé publique → **Add SSH key**

Tester :

```bash
ssh -T git@github.com
# → Hi gaelgael5! You've successfully authenticated, but GitHub does not provide shell access.
```

---

## Étape 3 — Premier déploiement

### 3.1 Cloner le repo

```bash
cd /opt
git clone --branch feat/local-admin-auth git@github.com:gaelgael5/harpocrate.git
cd harpocrate
```

### 3.2 Lancer `dev-deploy.sh`

Le script gère tout (clone si besoin, .env, dossiers `data/`, build images,
up de la stack) :

```bash
./dev-deploy.sh
```

Au premier run, il va :

1. Détecter le repo, faire un `git pull` (idempotent)
2. **Créer `.env` depuis `.env.example`** s'il n'existe pas, en **générant
   automatiquement les secrets aléatoires** (voir 3.3)
3. Créer `data/postgres/` et `data/backups/` (gitignored, voir `.gitignore`)
4. Builder `harpocrate-backend:dev` et `harpocrate-frontend:dev` localement
5. `docker compose -f docker-compose-dev.yml up -d`

### 3.3 Secrets auto-générés vs valeurs à éditer

**Auto-générés à la création de `.env`** (chmod 600 appliqué) :

| Variable | Génération |
|---|---|
| `POSTGRES_PASSWORD` | URL-safe 32 chars (`openssl rand` → `[A-Za-z0-9_-]`) |
| `HARPOCRATE_HMAC_KEY` | base64 de 32 bytes aléatoires |
| `HARPOCRATE_ADMIN_LOCAL_PASSWORD` | URL-safe 24 chars |
| `HARPOCRATE_ADMIN_LOCAL_ENABLED` | `true` (admin local activé pour le dev) |

Le password admin local est **affiché une fois dans la sortie** du script —
copie-le ou récupère-le ensuite avec `grep ADMIN_LOCAL_PASSWORD .env`.

**À éditer manuellement dans `.env`** si nécessaire :

| Variable | Valeur |
|---|---|
| `HARPOCRATE_PUBLIC_URL` | URL d'accès externe au backend (ex: `http://harpocrate-dev.home.lan`) |
| `HARPOCRATE_KEYCLOAK_URL` | ton serveur Keycloak (laisser tel quel si tu n'utilises que l'admin local) |
| `HARPOCRATE_KEYCLOAK_REALM` | realm Keycloak |
| `HARPOCRATE_KEYCLOAK_CLIENT_ID` | client ID OIDC |
| `HARPOCRATE_LISTMONK_*` | si envoi mails de recovery (sinon vide = no-op) |

Si tu modifies `.env`, **relancer** :

```bash
./dev-deploy.sh
```

---

## Étape 4 — Vérifier

```bash
docker compose -f docker-compose-dev.yml ps
```

Les 3 services doivent être `healthy` :

```
NAME                   STATE     PORTS
harpocrate-postgres    healthy   127.0.0.1:5432->5432/tcp
harpocrate-backend     healthy   127.0.0.1:8000->8000/tcp
harpocrate-frontend    healthy   127.0.0.1:8080->80/tcp, 0.0.0.0:8443->443/tcp
```

Test rapide :

```bash
curl http://127.0.0.1:8000/v1/health
# → {"status":"ok"}
```

Accès UI : <http://localhost:8080> (ou via reverse-proxy si tu en as un devant).

Logs :

```bash
docker compose -f docker-compose-dev.yml logs -f backend
docker compose -f docker-compose-dev.yml logs -f frontend
docker compose -f docker-compose-dev.yml logs --tail=50 postgres
```

---

## Étape 5 — Workflow de mise à jour

À chaque fois que tu veux récupérer les dernières modifs et rebuild :

```bash
./dev-deploy.sh
```

C'est tout. Le script fait `git pull`, rebuild les images, et redémarre la
stack. Les volumes `data/postgres` et `data/backups` sont préservés (rebuild
des images n'affecte pas les données).

Par défaut, le script reste sur la branche courante. Pour switcher de branche,
passe-la en argument :

```bash
./dev-deploy.sh feat/ma-branche
```

---

## Arborescence après installation

```
/opt/harpocrate/
├── data/                       # ← gitignored, volumes persistants
│   ├── postgres/               # /var/lib/postgresql/data
│   └── backups/                # /var/lib/harpocrate/backups (UID 1001)
├── .env                        # ← gitignored, config locale
├── .env.example
├── docker-compose-dev.yml      # compose utilisé par dev-deploy.sh
├── docker-compose.yml          # compose PROD (utilisé par scripts/refresh.sh)
├── dev-deploy.sh               # déploiement DEV (build local + up)
├── scripts/refresh.sh          # déploiement PROD (pull GHCR + up)
├── backend/                    # FastAPI + asyncpg
├── frontend/                   # Vite + React + Mantine
├── db/init/                    # SQL d'init (extensions pgcrypto, uuid-ossp)
├── releases/                   # SDK Python + CLI bash exposés via /v1/sdk/*
└── apps.json                   # menu cross-apps (édition à chaud, bind RO)
```

---

## Développement local (hors container)

Pour itérer rapidement sur le code sans rebuild d'image, lancer backend et
frontend **directement** sur ta machine, en gardant juste Postgres dans Docker :

```bash
# Postgres seul (depuis le serveur de dev distant ou local)
docker compose -f docker-compose-dev.yml up -d postgres

# Backend hot-reload (poste local)
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000

# Frontend (poste local) — proxy /api → :8000
cd frontend
npm install
npm run dev
```

UI dev : <http://localhost:5173>

---

## Configurer le client Keycloak (optionnel)

Si tu veux activer l'auth OIDC en plus (ou à la place de) l'admin local :

### 1. Créer le client dans Keycloak

Va sur ton serveur Keycloak admin → realm **yoops** → **Clients** → **Create client**

| Onglet | Champ | Valeur |
|---|---|---|
| General | Client type | `OpenID Connect` |
| General | Client ID | `harpocrate-vault` |
| Capability | Client authentication | **ON** |
| Capability | Standard flow | **ON** |
| Capability | Direct access grants | OFF |
| Login | Root URL | `http://harpocrate-dev.home.lan` |
| Login | Valid redirect URIs | `http://harpocrate-dev.home.lan/*` |
| Login | Web origins | `http://harpocrate-dev.home.lan` |

→ **Save**

### 2. Récupérer le secret

Onglet **Credentials** → copier **Client secret** → mettre dans `.env` :

```env
HARPOCRATE_KEYCLOAK_URL=https://keycloak.yoops.org
HARPOCRATE_KEYCLOAK_REALM=yoops
HARPOCRATE_KEYCLOAK_CLIENT_ID=harpocrate-vault
HARPOCRATE_KEYCLOAK_CLIENT_SECRET=<secret-généré>
HARPOCRATE_PUBLIC_URL=http://harpocrate-dev.home.lan
```

### 3. Rôles (optionnel)

Onglet **Roles** → créer le rôle `harpocrate-admin`.

Assigner le rôle aux users qui doivent avoir accès à l'admin Harpocrate
(`Users` → `<user>` → `Role mapping` → `Assign role` → `harpocrate-admin`).

### 4. Relancer

```bash
docker compose -f docker-compose-dev.yml restart backend
```

---

## Dépannage

### Backend `unhealthy`

```bash
docker compose -f docker-compose-dev.yml logs --tail=100 backend
```

Cause fréquente : `.env` mal configuré (HMAC_KEY manquante, KEYCLOAK_URL
inaccessible). Le backend log explicitement la variable manquante au boot.

### Postgres : `permission denied` sur `data/postgres`

Sur certains LXC unprivileged, les UIDs du container postgres (999) ne mappent
pas. Solution :

```bash
sudo chown -R 999:999 data/postgres
```

### Backups : `Errno 13` côté `/var/lib/harpocrate/backups`

Le user `harpocrate` du container a UID 1001. Le `dev-deploy.sh` fait déjà
`chown 1001:1001 data/backups`, mais si tu l'as créé à la main :

```bash
sudo chown -R 1001:1001 data/backups
```

### Reset complet de la DB

⚠ Détruit toutes les données :

```bash
docker compose -f docker-compose-dev.yml down
sudo rm -rf data/postgres
./dev-deploy.sh
```
