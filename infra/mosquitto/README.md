# Mosquitto — Broker MQTT pour réplication Harpocrate (LOT_21B)

## Génération du fichier de mots de passe

```bash
# Sur l'hôte qui fait tourner Mosquitto (ou via docker run mosquitto_passwd)
docker run --rm -v $(pwd):/m eclipse-mosquitto:2.0 \
    mosquitto_passwd -c -b /m/passwords harpocrate <strong-password>
```

Cela crée `infra/mosquitto/passwords` (haché). À monter en read-only dans
le container.

## Variables d'environnement Harpocrate

```env
HARPOCRATE_SYNC_ENABLED=true
HARPOCRATE_SYNC_CLUSTER_ID=harpocrate           # isole les clusters sur broker mutualisé
HARPOCRATE_SYNC_MQTT_HOST=mosquitto             # hostname du broker
HARPOCRATE_SYNC_MQTT_PORT=1883
HARPOCRATE_SYNC_MQTT_USERNAME=harpocrate
HARPOCRATE_SYNC_MQTT_PASSWORD=<strong-password>
HARPOCRATE_INSTANCE_ID=node-paris-01            # OBLIGATOIRE et UNIQUE en cluster
```

## Topologies supportées

- **2 nœuds** : actif/actif simple. Chaque modification est répliquée vers
  l'autre. Pas de résolution de conflit applicative — ça suppose que les
  clients écrivent toujours sur le même nœud (sticky sessions).
- **N nœuds** : chaque nœud publie ses transactions, écoute toutes les
  autres. Le `cluster_id` isole les groupes ; tout broker MQTT supportant
  QoS 1 + persistent session conviendra (Mosquitto, EMQX, HiveMQ, AWS IoT).

## Limites connues du LOT 21B

- **Pas de full sync à chaud** : un nouveau nœud rejoint le cluster en
  partant d'un restore de backup, pas par catch-up depuis zéro.
- **Pas de résolution de conflit** : si deux nœuds modifient la même entité
  en parallèle, la dernière transaction reçue gagne (LWW).
- **Étagère bornée** : `sync_shelf` peut grossir si un peer émet plus vite
  que les autres consomment. Surveiller via `/v1/admin/replication/sync/status`.
- **Partitionnement journalier** : la table `sync_log` est partitionnée
  mais une seule partition `default` couvre tout pour le MVP. Une cron de
  rotation arrivera dans un futur lot.
