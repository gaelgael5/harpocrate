# Patroni + etcd — Déploiement Harpocrate (LOT 20)

Cluster Postgres haute-disponibilité pour Harpocrate, avec failover automatique.

> **À exécuter manuellement par l'admin Proxmox.** L'application Harpocrate
> consomme uniquement le DSN du primary (résolu via DNS dynamique). Aucune
> dépendance code Harpocrate sur Patroni — la stratégie est sélectionnée via
> la variable d'environnement `HARPOCRATE_REPLICATION_STRATEGY`.

## Architecture cible

| LXC | Nom         | Ressources | Rôle                              |
|-----|-------------|------------|-----------------------------------|
| 210 | etcd        | 256MB / 1c | Store de consensus (DCS Patroni)  |
| 211 | pg-primary  | 2GB / 2c   | Postgres 16 + Patroni             |
| 212 | pg-replica  | 2GB / 2c   | Postgres 16 + Patroni             |

DNS (Pi-hole/dnsmasq) :
- `postgres-primary.home.lan` → IP du primary courant (mis à jour par callback Patroni)
- `postgres-replica.home.lan` → IP statique du replica
- `etcd.home.lan` → IP statique etcd

## Prérequis

- Proxmox VE avec template Ubuntu 24.04 LTS
- Pi-hole accessible avec API key (ou clé SSH vers `pihole.home.lan`)
- Réseau bridge identique pour les 3 LXC + le LXC Harpocrate

## Procédure

### 1. Créer les LXC

Sur l'hôte Proxmox, utiliser le script standard `create-lxc.sh` :

```bash
bash <(wget -qO- https://raw.githubusercontent.com/Configurations/Proxmox/main/LXC/create-lxc.sh) 210 etcd
bash <(wget -qO- https://raw.githubusercontent.com/Configurations/Proxmox/main/LXC/create-lxc.sh) 211 pg-primary
bash <(wget -qO- https://raw.githubusercontent.com/Configurations/Proxmox/main/LXC/create-lxc.sh) 212 pg-replica
```

Ajuster les ressources : `pct set 211 -memory 2048 -cores 2 -rootfs local-lvm:32`.

### 2. Installer etcd (LXC 210)

```bash
pct push 210 infra/etcd/install-etcd.sh /tmp/install-etcd.sh
pct exec 210 -- bash /tmp/install-etcd.sh
pct push 210 infra/etcd/etcd.conf.yml.template /etc/etcd/etcd.conf.yml
# Éditer /etc/etcd/etcd.conf.yml et remplacer <ETCD_IP>
pct push 210 infra/etcd/etcd.service /etc/systemd/system/etcd.service
pct exec 210 -- systemctl daemon-reload && systemctl enable --now etcd
pct exec 210 -- etcdctl --endpoints=http://127.0.0.1:2379 endpoint health
```

### 3. Installer Patroni primary (LXC 211)

```bash
pct push 211 infra/patroni/install-patroni.sh /tmp/install-patroni.sh
pct exec 211 -- bash /tmp/install-patroni.sh
pct push 211 infra/patroni/patroni-primary.yml.template /etc/patroni/patroni.yml
# Éditer /etc/patroni/patroni.yml : remplacer <PG_PRIMARY_IP>, <PG_REPLICA_IP>, <ETCD_IP>
pct push 211 infra/patroni/patroni.env.template /etc/patroni/.env
# Éditer /etc/patroni/.env : générer 3 mots de passe forts
chmod 600 /etc/patroni/.env
pct push 211 infra/patroni/callbacks/on_role_change.sh /etc/patroni/callbacks/on_role_change.sh
chmod +x /etc/patroni/callbacks/on_role_change.sh
pct push 211 infra/patroni/patroni.service /etc/systemd/system/patroni.service
pct exec 211 -- systemctl daemon-reload && systemctl enable --now patroni
```

### 4. Installer Patroni replica (LXC 212)

Identique au primary, avec `patroni-replica.yml.template` au lieu de `patroni-primary.yml.template`.

### 5. Vérification

```bash
pct exec 211 -- patronictl -c /etc/patroni/patroni.yml list
```

Sortie attendue :

```
+ Cluster: harpocrate-postgres ----+----+-----------+
| Member     | Host             | Role   | TL | Lag in MB |
+------------+------------------+--------+----+-----------+
| pg-primary | <PG_PRIMARY_IP>  | Leader |  1 |           |
| pg-replica | <PG_REPLICA_IP>  | Replica|  1 |         0 |
+------------+------------------+--------+----+-----------+
```

### 6. DNS dnsmasq

Sur le LXC Pi-hole (ou hôte dnsmasq) :

```bash
# /etc/dnsmasq.d/harpocrate.conf
address=/postgres-primary.home.lan/<PG_PRIMARY_IP>
address=/postgres-replica.home.lan/<PG_REPLICA_IP>
address=/etcd.home.lan/<ETCD_IP>
```

Reload : `systemctl reload dnsmasq` (ou redémarrer le service Pi-hole).

### 7. Activer la stratégie côté Harpocrate

Dans le `.env` de Harpocrate :

```env
HARPOCRATE_DB_DSN=postgresql://harpocrate:PASSWORD@postgres-primary.home.lan:5432/harpocrate
HARPOCRATE_REPLICATION_STRATEGY=patroni
HARPOCRATE_PATRONI_API_URLS=http://<PG_PRIMARY_IP>:8008,http://<PG_REPLICA_IP>:8008
HARPOCRATE_POSTGRES_REPLICA_DSN=postgresql://harpocrate:PASSWORD@postgres-replica.home.lan:5432/harpocrate
```

Restart Harpocrate. La page `/admin/replication` doit afficher l'état Patroni.

## Procédure de failover (test)

```bash
# 1. Couper le primary
pct exec 211 -- systemctl stop patroni

# 2. Observer la promotion (~15s)
pct exec 212 -- patronictl -c /etc/patroni/patroni.yml list

# 3. Vérifier que DNS pointe vers le nouveau primary
dig postgres-primary.home.lan

# 4. Vérifier qu'Harpocrate sert toujours
curl https://vault.yoops.org/v1/health
```

## Retour de l'ancien primary

```bash
pct exec 211 -- systemctl start patroni
# Patroni détecte qu'il y a déjà un leader → démarre en replica
# pg_rewind resynchronise les divergences automatiquement
```

## Limites connues

- **MVP single-node etcd** : un seul nœud etcd. Pour la haute-dispo réelle d'etcd, il faut 3 nœuds (futur).
- **DNS dynamique** : le callback Patroni doit avoir un accès Pi-hole valide. Si l'API Pi-hole change, mettre à jour `callbacks/on_role_change.sh`.
- **Backup management** : les backups Harpocrate (LOT 12A) restent inchangés ; ils tournent sur le primary.
