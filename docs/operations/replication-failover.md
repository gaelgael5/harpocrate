# Failover réplication — guide opérationnel

## Quand utiliser

- **Panne du master** (down définitif, perte matérielle, corruption).
- **Maintenance planifiée du master** nécessitant un basculement de rôle.

## Pré-requis CRITIQUES

⚠️ **L'ancien master DOIT être arrêté avant la promotion**, sous peine de
**split-brain** (deux primaries qui acceptent des écritures en parallèle →
divergence permanente, irrécupérable sans perte).

Démarche :

- **Si l'ancien master est encore joignable** (failover planifié) :

  ```bash
  ssh root@<ancien-master>
  cd /opt/harpocrate
  docker compose -f docker-compose-dev.yml stop postgres backend
  ```

- **Si l'ancien master est déjà down** (panne) : passer à l'étape suivante.

## Procédure

1. Ouvrir l'UI du standby (`https://<standby>:8443/admin/replication`).
2. Section "Stratégies / Streaming" → un bouton orange **"Promouvoir en master"**
   apparaît automatiquement (visible uniquement si l'instance est en mode
   standby — auto-masqué sur master ou standalone).
3. Modale de confirmation s'affiche. Cocher les **2 cases** :
   - ☑ Je confirme que l'ancien master est arrêté
   - ☑ Je m'engage à reconfigurer les clients vers ce nouveau master
4. Le bouton "Promouvoir maintenant" s'active.
5. Cliquer → toast vert "Promotion réussie".

## Vérifications post-failover

Sur le nouveau master (ex-standby) :

```bash
# Doit retourner false = primary (plus en recovery)
docker compose -f docker-compose-dev.yml exec -T postgres \
  psql -U harpocrate harpocrate -c "SELECT pg_is_in_recovery();"

# Test d'écriture — doit réussir (alors qu'avant la promotion ça refusait)
docker compose -f docker-compose-dev.yml exec -T postgres \
  psql -U harpocrate harpocrate -c \
  "INSERT INTO audit_log (action) VALUES ('test.write_after_promote');"
# → INSERT 0 1
```

Côté backend Harpocrate :

```bash
# Logs : doit voir cluster_listen_connected (le LISTEN passif du standby
# bascule en LISTEN actif maintenant qu'on est primary)
docker compose -f docker-compose-dev.yml logs -f backend | grep cluster_listen
# → cluster_listen_connected channels=[...]  dans les 60s qui suivent
```

## Reconfigurer les clients

Les clients (UI utilisateurs, scripts, autres instances Harpocrate) pointaient
vers l'ancien master. Mettre à jour leur URL Harpocrate vers le nouveau master.

En prod, prévoir un **VIP** ou **DNS qui bascule** (ex: Cloudflare, Caddy
upstream) pour éviter cette reconfiguration manuelle.

## Réintégrer l'ancien master comme nouveau standby (manuel — pas industrialisé)

Pour cette itération **MVP**, **non couvert par l'UI**. Procédure manuelle :

1. S'assurer que l'ancien master n'a pas de divergence (idéalement il était
   down pendant la promotion → pas de write divergent).
2. Effacer le PGDATA de l'ancien master : `rm -rf data/postgres/*`.
3. Faire un `pg_basebackup` depuis le nouveau master vers l'ancien (voir le
   wizard pairing).
4. Démarrer Postgres sur l'ancien master en mode standby.
5. Reconfigurer `replication.is_standby_of` dans `system_metadata` de
   l'ancien master.

⚠️ Cette étape sera industrialisée dans une itération future via un endpoint
`POST /v1/admin/replication/rebuild-as-standby` + UI dédiée.

## Limitations connues du MVP

- ⨯ **Pas de détection automatique** de la perte du master (le standby ne se
  promeut pas tout seul ; intervention admin requise).
- ⨯ **Pas de demote distant** : le standby ne contacte pas l'ancien master
  pour lui demander de s'arrêter (admin doit le faire à la main).
- ⨯ **Pas de détection de split-brain** : si l'admin coche les cases sans
  avoir arrêté l'ancien master, la divergence se crée silencieusement.
- ⨯ **Pas de reconfiguration automatique des clients** : à la charge de
  l'opérateur (en prod, prévoir VIP/DNS).
- ⨯ **Pas de rebuild automatique de l'ancien master** en nouveau standby.

Tous ces sujets sont **chantiers futurs séparés**.

## Endpoints API utilisés

- `GET /v1/admin/replication/can-promote` → indique si la promotion est
  possible (utilisé par l'UI pour afficher/masquer le bouton).
- `POST /v1/admin/replication/promote` → exécute la promotion (exige les
  2 confirmations dans le body).

Le body de `POST /promote` :

```json
{
  "confirm_master_down": true,
  "confirm_clients_will_be_reconfigured": true
}
```

Codes d'erreur :

| Code HTTP | `detail.error` | Cause |
|---|---|---|
| 400 | `missing_confirmation` | Une des 2 cases non cochée |
| 401 | `unauthorized` | JWT admin absent ou invalide |
| 409 | `not_in_standby_mode` | Instance déjà primary (idempotence) |
| 500 | `promotion_failed` | `pg_promote()` n'a pas pu sortir du recovery |
