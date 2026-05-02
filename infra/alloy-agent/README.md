# Alloy — collecteur de logs (module harpocrate)

Agent Grafana Alloy qui collecte les logs Docker et journald du LXC hôte et les pousse vers la stack Loki centralisée.

## Architecture

```
LXC cible (202, etc.)
  └── harpocrate-alloy-agent (Docker)
        ├── Docker socket  → logs containers
        └── journald       → logs système
              │
              ▼
  LXC 116 (agflow-logs)
        ├── Loki  : http://192.168.10.110:3100/loki/api/v1/push
        └── Grafana : https://log.yoops.org
```

## Stack centrale (LXC 116 — agflow-logs)

- **Loki** : accepte les pushes entrants sur `http://192.168.10.110:3100/loki/api/v1/push`
- **Grafana** : `https://log.yoops.org`
  - Auth : Keycloak SSO, realm `yoops`, client `grafana`
  - Rôles disponibles : `admin`, `editor`, `viewer`
- Rétention logs : 7 jours
- Ne pas modifier cette stack depuis ce repo — elle est gérée séparément dans `infra/logs-stack/` du repo `agflow.docker`.

## Label module

Tous les logs poussés par cet agent portent le label `module="harpocrate"`. Utile pour filtrer dans les dashboards Loki/Grafana inter-modules.

## Déploiement sur un nouveau host

### Prérequis

- Docker installé sur le LXC cible
- Accès SSH au host Proxmox (`pve`) pour les CTID, ou SSH direct pour les alias

### Étapes

```bash
# Depuis le poste de développement, à la racine du repo
./scripts/infra/deploy-alloy.sh <CTID>      # ex : 202
# ou
./scripts/infra/deploy-alloy.sh <ssh-alias> # ex : mon-serveur
```

Le script :
1. Pousse `infra/alloy-agent/` vers `/opt/alloy/` sur la cible
2. Crée un `.env` depuis `.env.template` si absent, puis demande de l'éditer
3. Lance `docker compose up -d`
4. Vérifie que l'agent répond sur `:12345/-/ready`
5. Affiche les 20 dernières lignes de logs du container

### Déploiement manuel

```bash
# Copier les fichiers
scp -r infra/alloy-agent/ <host>:/opt/alloy/

# Sur le LXC cible
cd /opt/alloy
cp .env.template .env
# Editer .env : remplacer lxc<CTID> par le vrai identifiant
nano .env

docker compose up -d
curl http://localhost:12345/-/ready
```

## Vérification dans Grafana

1. Ouvrir `https://log.yoops.org`
2. Menu **Explore** → source **Loki**
3. Filtre : `{module="harpocrate"}` ou `{host="lxc202"}`
4. Dashboard **Docker** : filtrer par label `host` pour voir le LXC

## Variante sans Docker (LXC systemd uniquement)

Utiliser `config-journald-only.alloy` à la place de `config.alloy`. Dans ce cas, passer par `scripts/install-alloy.sh` (installation du paquet Debian Alloy + service systemd).

## Fichiers

| Fichier | Rôle |
|---------|------|
| `docker-compose.yml` | Stack Docker Alloy |
| `config.alloy` | Config River : Docker socket + journald |
| `config-journald-only.alloy` | Config River : journald seul (sans Docker) |
| `.env.template` | Variables d'environnement à copier en `.env` |
