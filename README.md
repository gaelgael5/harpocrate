# harpocrate

Coffre-fort de secrets E2E — chiffrement côté client, accès par wallet, API REST.

## Installation

L'installation se fait en trois étapes exécutées sur l'**hôte Proxmox**, puis dans le **container LXC**.

---

### Étape 1 — Créer le container LXC

Sur l'hôte Proxmox, créer et configurer le LXC (Docker-ready, SSH, réseau DHCP) :

```bash
bash <(wget -qO- https://raw.githubusercontent.com/gaelgael5/harpocrate/refs/heads/main/scripts/create-lxc.sh) 202 harpocrate --docker
```

Remplacer `202` par le CTID souhaité et `harpocrate` par le nom du container.

> Le script installe Docker automatiquement s'il détecte `install-docker.sh` dans le même répertoire.  
> Si Docker n'a pas été installé, l'étape 2 s'en charge manuellement.

---

### Étape 2 — Installer Docker *(si non fait automatiquement)*

```bash
pct exec 202 -- bash -c "$(wget -qLO - https://raw.githubusercontent.com/gaelgael5/harpocrate/refs/heads/main/scripts/install-docker.sh)"
```

---

### Étape 3 — Initialiser la stack

Télécharge `docker-compose.yml`, `.env.example` et `refresh.sh` dans `/opt/harpocrate`, puis crée un `.env` prêt à éditer :

```bash
pct exec 202 -- bash -c "$(wget -qLO - https://raw.githubusercontent.com/gaelgael5/harpocrate/refs/heads/main/scripts/setup.sh)"
```

---

### Étape 4 — Configurer `.env`

Se connecter au container et éditer le fichier :

```bash
pct exec 202 -- bash
nano /opt/harpocrate/.env
```

Champs obligatoires :

| Variable | Description |
|---|---|
| `POSTGRES_PASSWORD` | Mot de passe PostgreSQL |
| `HARPOCRATE_HMAC_KEY` | Clé HMAC — `openssl rand -base64 32` |
| `HARPOCRATE_PUBLIC_URL` | URL publique du vault (ex: `https://vault.example.com`) |

Auth locale (sans Keycloak) :

```env
HARPOCRATE_ADMIN_LOCAL_ENABLED=true
HARPOCRATE_ADMIN_LOCAL_USERNAME=admin
HARPOCRATE_ADMIN_LOCAL_PASSWORD=mot-de-passe-fort
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
