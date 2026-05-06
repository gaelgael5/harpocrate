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

```bash
https://your ip :8443/
```


---

## Configuration Keycloak (OIDC)

L'application utilise un **client public PKCE** — pas de client secret (le code tourne dans le navigateur).

### 1. Créer le client

Dans **Clients → Create client** :

| Champ | Valeur |
|---|---|
| Client type | OpenID Connect |
| Client ID | `harpocrate-vault` |
| Client authentication | **OFF** (client public) |
| Standard flow | ON |
| Direct access grants | OFF |

Onglet **Settings** du client :

| Champ | Valeur |
|---|---|
| Valid redirect URIs | `https://vault.yoops.org/oauth-callback` |
| Valid post logout redirect URIs | `https://vault.yoops.org/` |
| Web origins | `https://vault.yoops.org` |

### 2. Créer le rôle realm admin

**Realm roles → Create role** : `harpocrate-admin`

Assigner ce rôle aux utilisateurs qui doivent avoir accès aux écrans d'administration (**User → Role mapping → Assign role → Filter by realm roles → `harpocrate-admin`**).

### 3. Vérifier les client scopes

Dans le client, onglet **Client scopes** : s'assurer que `email` et `profile` sont présents dans les scopes assignés (c'est le cas par défaut).

### 4. Configurer `.env`

```env
HARPOCRATE_KEYCLOAK_URL=https://security.yoops.org
HARPOCRATE_KEYCLOAK_REALM=yoops
HARPOCRATE_KEYCLOAK_CLIENT_ID=harpocrate-vault
HARPOCRATE_PUBLIC_URL=https://vault.yoops.org
```

### 5. Vérifier l'intégration

```bash
curl https://vault-api.yoops.org/v1/config/keycloak
```

Réponse attendue :
```json
{
  "realm": "yoops",
  "client_id": "harpocrate-vault",
  "issuer": "https://security.yoops.org/realms/yoops"
}
```

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

```bash

# voir les logs du frontend
docker compose -f /opt/harpocrate/docker-compose.yml logs -f frontend

# voir les logs du backend
docker compose -f /opt/harpocrate/docker-compose.yml logs -f backend

```

---

## Sauvegardes

Trois mécanismes complémentaires, accessibles via **Administration → Sauvegardes** :

- **Sauvegardes locales** — création d'un `.tar.age` chiffré avec la clé publique AGE configurée dans `HARPOCRATE_AGE_PUBLIC_KEY`. Restauration via la clé privée saisie côté UI uniquement, jamais persistée serveur.
- **Snapshots automatiques** — politique GFS (hourly/daily/weekly/monthly/yearly) configurable depuis l'écran Snapshots auto.
- **Backups distants** — connexions SFTP gérées dans **Backups distants**, push manuel d'une sauvegarde locale vers la connexion choisie. Les credentials sont chiffrés serveur via AES-GCM (clé dérivée HKDF de `HARPOCRATE_HMAC_KEY`) et ne sont jamais retournés en clair par l'API. Stream chunk-par-chunk vers le serveur distant — le fichier n'est jamais chargé entièrement en RAM.
- **Push S3** — alternative S3 compatible (`HARPOCRATE_S3_*`).

---

## Documentation

Documentation détaillée (architecture, modèle de menace, intégration SDK) :  
👉 [Wiki Harpocrate](https://github.com/gaelgael5/harpocrate/wiki)

SDK clients officiels (Python, …) téléchargeables depuis l'écran **Intégration** de l'application.

---

## Licence

Voir [LICENSE](./LICENSE).
