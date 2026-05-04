# harpocrate

Coffre-fort de secrets E2E — chiffrement côté client, accès par wallet, API REST.

## Installation

L'installation se fait en trois étapes exécutées sur l'**hôte Proxmox**, puis dans le **container LXC**.

---

### Étape 1 — Créer le container LXC

Sur l'hôte Proxmox, créer et configurer le LXC (Docker-ready, SSH, réseau DHCP).

> `bash <(wget -qO- URL)` est requis ici (pas `bash -c "$(wget ...)"`) car le script reçoit des arguments positionnels (`$1` = CTID, `$2` = nom).

```bash
bash <(wget -qO- https://raw.githubusercontent.com/Configurations/Proxmox/main/LXC/create-lxc.sh) 202 harpocrate --docker
```

Remplacer `202` par le CTID souhaité et `harpocrate` par le nom du container.  
Le flag `--docker` installe Docker automatiquement dans le LXC.

---

### Étape 2 — Initialiser la stack

Télécharge `docker-compose.yml`, `.env.example` et `refresh.sh` dans `/opt/harpocrate`, puis crée un `.env` prêt à éditer :

```bash
pct exec 202 -- bash -c "$(wget -qLO - https://raw.githubusercontent.com/gaelgael5/harpocrate/refs/heads/main/scripts/setup.sh)"
```

---

### Étape 3 — Configurer `.env`

Se connecter au container et éditer le fichier :

```bash
pct exec 202 -- bash
nano /opt/harpocrate/.env
```


Auth locale (sans Keycloak) :

```env

POSTGRES_USER=harpocrate
POSTGRES_PASSWORD=GAgyAUFete1g58sR1Y0KxusQlED7v8h
POSTGRES_DB=harpocrate

HARPOCRATE_KEYCLOAK_URL=https://security.yourdomain.org
HARPOCRATE_KEYCLOAK_REALM=yoops
HARPOCRATE_KEYCLOAK_CLIENT_ID=
HARPOCRATE_HMAC_KEY=
HARPOCRATE_PUBLIC_URL=https://vault.yourdomain.org
HARPOCRATE_LOG_LEVEL=INFO

# Auth locale activee
HARPOCRATE_ADMIN_LOCAL_ENABLED=true
HARPOCRATE_ADMIN_LOCAL_USERNAME=admin
HARPOCRATE_ADMIN_LOCAL_PASSWORD=mot-de-passe-fort-2026
HARPOCRATE_ADMIN_LOCAL_EMAIL=gaelgael5@gmail.com
HARPOCRATE_ADMIN_LOCAL_DISPLAY_NAME=Local Admin

# Mode dev (bandeau visuel permanent)
# HARPOCRATE_DEV_MODE=true
# HARPOCRATE_DEV_MODE_LABEL=DEV - LXC 202

```

---

### Étape 5 — Lancer la stack

```bash
pct exec 202 -- bash -c "cd /opt/harpocrate && ./refresh.sh"
```

La stack démarre, les images sont pullées depuis GHCR, les migrations DB sont appliquées au premier boot.

---

## Mise à jour

```bash
pct exec 202 -- bash -c "cd /opt/harpocrate && ./refresh.sh"
```

Pour épingler une version spécifique :

```bash
pct exec 202 -- bash -c "cd /opt/harpocrate && TAG=v1.2.0 ./refresh.sh"
```

---

## Développement local

```bash
# Dépendances infra (Postgres) sur le LXC
ssh pve "pct exec 202 -- bash -c 'cd /opt/harpocrate && docker compose up -d postgres'"

# Backend (hot-reload)
cd backend && uv run uvicorn app.main:app --reload

# Frontend (proxy Vite -> :8000)
cd frontend && npm run dev
```
