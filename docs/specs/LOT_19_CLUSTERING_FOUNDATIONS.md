# Lot 19 — Fondations du clustering

> **Statut** : Document d'architecture — pose les bases et décisions de design.
> **Aucun code à implémenter dans ce lot.**
> Les implémentations viendront dans les lots 20+ au moment opportun.

## Objectif

Définir les **règles d'architecture immuables** qui gouverneront le clustering d'Harpocrate. Ce document est la référence à consulter avant toute décision technique liée à la scalabilité, la haute disponibilité, ou le déploiement multi-nœuds. Il établit les contraintes, les invariants, et les décisions prises — afin que les implémentations futures ne remettent pas en cause les fondations.

## Contexte

Harpocrate est un **secrets manager end-to-end encrypted**. Cette caractéristique fondamentale — le serveur ne voit jamais les valeurs en clair — impose des contraintes de clustering qui diffèrent d'une application web classique. Les décisions prises ici en découlent directement.

---

## Partie 1 — Invariants absolus

Ces règles ne sont **jamais négociables**, quelle que soit l'architecture de déploiement choisie.

### I-1 : Le serveur ne déchiffre jamais

Aucun nœud du cluster ne stocke, ne transmet, ne logue, et ne met en cache une valeur de secret déchiffrée. La `decryption_key` ne transite jamais par le réseau serveur. Un nœud qui recevrait accidentellement une `decryption_key` (format de token complet) doit rejeter la requête et logger une alerte critique.

### I-2 : La HMAC_KEY est identique sur tous les nœuds

La `HMAC_KEY` signe les API keys. Si deux nœuds ont des `HMAC_KEY` différentes, les tokens signés par l'un sont rejetés par l'autre. Cette clé est déployée comme secret d'orchestration (Docker Swarm secret, Kubernetes secret) et doit être identique sur l'ensemble du cluster à tout instant.

**Corollaire** : la rotation de `HMAC_KEY` invalide toutes les API keys existantes et doit être coordonnée sur tous les nœuds simultanément (rolling restart avec overlap).

### I-3 : La session_epoch est la source de vérité globale

La table `system_metadata.session_epoch` (Postgres) est l'unique référence d'invalidation des sessions. Tous les nœuds doivent lire et honorer cette valeur. Un nœud qui a un epoch RAM inférieur à l'epoch DB est dans un état incohérent et doit refuser de servir.

### I-4 : Postgres est la source de vérité unique

Il n'y a pas de source de données distribuée au niveau applicatif. Harpocrate ne fait pas de consensus entre nœuds applicatifs. La cohérence est déléguée entièrement à Postgres. Les nœuds applicatifs sont stateless.

### I-5 : Le mode maintenance est global

Quand `maintenance_active = TRUE` en DB, **tous les nœuds** refusent les requêtes avec 503. Il n'existe pas de maintenance "par nœud". Un nœud qui ignorerait ce flag servirait des données potentiellement incohérentes pendant un backup ou restore.

---

## Partie 2 — Architecture cible

### Vue d'ensemble

```
                    ┌──────────────────────────────────────┐
                    │          Load Balancer               │
                    │     (round-robin, no sticky)         │
                    └──────┬──────────────┬────────────────┘
                           │              │
               ┌───────────▼──┐    ┌──────▼───────────┐
               │  Nœud App 1  │    │   Nœud App 2     │
               │  Harpocrate  │    │   Harpocrate     │
               │  (stateless) │    │   (stateless)    │
               └──────┬───────┘    └──────┬────────────┘
                      │                   │
                      └─────────┬─────────┘
                                │
                    ┌───────────▼──────────┐
                    │   Postgres Primary   │
                    │   (source de vérité) │
                    └───────────┬──────────┘
                                │ streaming replication
                    ┌───────────▼──────────┐
                    │   Postgres Replica   │
                    │   (read-only)        │
                    └──────────────────────┘
```

### Nœuds applicatifs

- **Stateless** : un nœud peut être tué et remplacé sans perte de données
- **Pas de sticky sessions** nécessaire (pas d'état côté serveur, JWT et API keys sont self-contained)
- **Scalabilité horizontale** : ajouter un nœud = le faire pointer vers le même Postgres
- **Instances identiques** : même image Docker, mêmes env vars (sauf `INSTANCE_ID` optionnel pour les logs)

### Load balancer

- Algorithme : round-robin ou least-connections
- Health check : `GET /health` avec timeout 2s, seuil 3 échecs consécutifs
- Drain avant kill : 30s de grace period pour finir les requêtes en cours
- Pas de terminaison TLS sur le load balancer (TLS end-to-end recommandé, ou terminaison acceptable si réseau interne de confiance)

### Postgres

Deux configurations supportées selon le niveau de criticité :

**Configuration A — Standalone** (MVP, homelab)
- Un seul nœud Postgres
- SPOF assumé et documenté
- Backup S3 (lot 13) comme seule protection contre la perte de données
- Acceptable : RTO ~minutes (restore depuis backup), RPO = dernier snapshot (lot 14)

**Configuration B — Primary + Replica** (production)
- Streaming replication synchrone ou asynchrone (choix selon latence acceptable)
- Failover manuel ou automatique (Patroni recommandé)
- Harpocrate écrit toujours sur le primary
- Lectures read-only (métriques, audit log export, browse wallets) peuvent aller sur replica
- **Lag de réplication** : si async, les lectures sur replica peuvent être stale de quelques ms à quelques secondes. Acceptable pour les listes, jamais pour les lectures critiques (secrets, grants, epoch)

**Configuration C — Postgres managé** (cloud)
- AWS RDS, Google Cloud SQL, Supabase, Neon, etc.
- Délègue HA, backups, failover au provider
- Harpocrate se connecte comme à n'importe quel Postgres
- Vérifier que le provider supporte : `pg_notify`, advisory locks, `gen_random_uuid()`, `pgcrypto`

---

## Partie 3 — Règles de cohérence

### Cohérence des écritures

Les opérations suivantes sont **critiques** et doivent toujours aller sur le Postgres primary, avec les protections suivantes :

| Opération | Protection requise |
|---|---|
| Création d'une version de schema | `SELECT FOR UPDATE` sur le type parent |
| Création d'une API key | Contrainte UNIQUE en DB |
| Révocation d'une API key | `SELECT FOR UPDATE` |
| Bump de `generation_version` sur un secret | `SELECT FOR UPDATE` |
| Backup / snapshot | Advisory lock `pg_advisory_lock` |
| Incrémentation de `session_epoch` | Transaction sérialisée |
| Activation / désactivation maintenance | Transaction sérialisée |

### Cohérence de la session_epoch

Chaque nœud maintient en RAM l'epoch courant. Il doit le rafraîchir depuis la DB :
- Au démarrage (obligatoire)
- À chaque requête entrante (option stricte) ou périodiquement toutes les N secondes (option performance)
- Via LISTEN/NOTIFY Postgres sur le canal `harpocrate_epoch_changed` (option réactive)

**Décision choisie** : LISTEN/NOTIFY + refresh périodique toutes les 5 secondes comme filet de sécurité. Ni trop agressif (charge DB), ni trop lent (window d'incohérence acceptable : <5s).

### Cohérence du mode maintenance

Même logique que l'epoch :
- LISTEN/NOTIFY sur le canal `harpocrate_maintenance_changed`
- Refresh périodique toutes les 5 secondes
- Au démarrage : lire l'état courant avant d'accepter le premier trafic

### Ordering de l'audit log

Les nœuds multiples écrivent dans `audit_log` avec `occurred_at = NOW()`. Si les horloges sont synchronisées via NTP (exigence déploiement), `occurred_at` est suffisant pour l'ordering.

**Exigence déploiement** : NTP obligatoire sur tous les nœuds. Drift maximum toléré : 1 seconde. Si non garanti, ajouter une colonne `seq BIGSERIAL` à l'audit_log pour un ordering strict.

**Décision choisie** : NTP requis, `seq` ajouté préventiment à l'audit_log dans la migration initiale (coût nul maintenant, évite une migration lourde plus tard).

---

## Partie 4 — Coordination inter-nœuds

### Modèle de coordination choisi : Postgres-centric

Il n'y a **pas de communication directe entre nœuds applicatifs**. Toute coordination passe par Postgres :

- **State partagé** : tables Postgres (`system_metadata`, `audit_log`, etc.)
- **Broadcast** : `LISTEN/NOTIFY` Postgres pour les événements critiques (epoch change, maintenance toggle)
- **Exclusion mutuelle** : advisory locks Postgres pour les opérations singleton (backup, snapshot)
- **Élection de leader** : advisory lock try-acquire pour les tâches singleton (scheduler de snapshots)

Ce modèle est délibérément **simple** : pas de Redis, pas de ZooKeeper, pas de consensus distribué (Raft/Paxos). Postgres est déjà le SPOF assumé — autant l'utiliser pour la coordination.

### Canaux NOTIFY définis

```sql
-- Broadcast par n'importe quel nœud, écouté par tous

harpocrate_epoch_changed        -- session_epoch modifié (après restore)
harpocrate_maintenance_changed  -- maintenance_active modifié
harpocrate_jwks_invalidated     -- forcer refresh JWKS sur tous les nœuds
```

Format du payload NOTIFY :

```json
{
  "event": "epoch_changed",
  "new_value": 44,
  "emitted_by": "node-abc123",
  "emitted_at": "2026-05-04T14:23:00Z"
}
```

### Advisory locks définis

```
Magic numbers (immuables une fois choisis) :

1000000001  →  backup_restore_lock
              Une seule opération de backup ou restore à la fois sur le cluster.
              Tenant : le nœud qui déclenche le backup/restore.
              Durée : release explicite en fin d'opération ou à la mort du process.

1000000002  →  snapshot_scheduler_lock
              Un seul scheduler de snapshots actif à la fois (élu parmi les nœuds).
              Tenant : le nœud qui a gagné l'élection.
              Durée : pg_advisory_lock (bloquant, jusqu'à mort du nœud).
              Renouvellement : pas nécessaire (lock de session Postgres).

1000000003  →  epoch_increment_lock
              Serialise les incréments de session_epoch.
              Durée : le temps de la transaction.
```

---

## Partie 5 — Exigences de déploiement

Ces exigences sont **obligatoires** pour tout déploiement cluster. Les ignorer invalide les garanties de cohérence.

### E-1 : Synchronisation NTP

Tous les nœuds applicatifs et Postgres doivent être synchronisés NTP. Drift maximum toléré : **1 seconde**. Vérification recommandée en CI/CD avant déploiement.

### E-2 : Variables d'environnement identiques sur tous les nœuds

Les variables suivantes doivent être **bit-pour-bit identiques** sur tous les nœuds :

```
HARPOCRATE_HMAC_KEY
HARPOCRATE_KEYCLOAK_CLIENT_SECRET
HARPOCRATE_KDF_MEMORY_KB
HARPOCRATE_KDF_ITERATIONS
HARPOCRATE_KDF_PARALLELISM
HARPOCRATE_RSA_KEY_SIZE_MIN
```

Les variables suivantes peuvent **différer par nœud** :

```
HARPOCRATE_LOG_LEVEL         (debug sur un nœud spécifique pour diagnostic)
HARPOCRATE_INSTANCE_ID       (identifiant unique du nœud pour les logs)
```

### E-3 : Un seul scheduler de snapshots actif

Le lot 14 démarre un scheduler asyncio par nœud. En cluster, un seul doit être actif (élu via advisory lock `snapshot_scheduler_lock`). Les autres nœuds tentent d'acquérir le lock au démarrage : s'ils échouent, ils n'activent pas le scheduler. Si le nœud leader tombe, le lock est libéré et un autre nœud peut prendre le relais.

### E-4 : Graceful shutdown obligatoire

Chaque nœud doit écouter `SIGTERM` et :
1. Arrêter d'accepter de nouvelles connexions (retrait du pool load balancer via health check)
2. Attendre la fin des requêtes en cours (grace period : 30 secondes)
3. Libérer les advisory locks Postgres
4. Fermer proprement les connections Postgres (connection pool drain)
5. S'arrêter

Un nœud qui ignore `SIGTERM` laisse des advisory locks orphelins en Postgres.

**Note** : les locks de session Postgres sont automatiquement libérés quand la connexion est fermée. Le graceful shutdown garantit juste que les opérations en cours se terminent proprement.

### E-5 : Health check

Endpoint `GET /health` obligatoire. Doit vérifier **au minimum** :

- Connexion Postgres active (SELECT 1)
- `session_epoch` RAM == `session_epoch` DB (cohérence epoch)
- JWKS chargé en RAM (non null, non expiré)
- `maintenance_active` DB lu (cohérence maintenance)

Réponse :

```json
{
  "status": "ok",                    // "ok" | "degraded" | "down"
  "checks": {
    "db": "ok",
    "epoch_coherent": true,
    "jwks_loaded": true,
    "maintenance_active": false
  },
  "instance_id": "node-abc123",
  "uptime_seconds": 3600,
  "session_epoch": 43
}
```

- `200 ok` : le nœud sert normalement
- `200 degraded` : le nœud sert mais avec avertissements (ex: JWKS bientôt à rafraîchir)
- `503 down` : le nœud doit être retiré du pool

### E-6 : Pas de données sensibles dans les logs distribués

En cluster, les logs partent souvent vers un agrégateur (Loki, Elasticsearch, Datadog). Règles applicables au single-node mais **critiques en cluster** :

- Jamais de token API key (complet ou tronqué) dans les logs
- Jamais de valeur de secret
- Jamais de passphrase ou clé de déchiffrement
- Jamais de `HMAC_KEY` ou `KEYCLOAK_CLIENT_SECRET`
- Loguer librement : UUIDs, noms de wallets, noms de secrets, codes d'erreur, durées, instance_id

---

## Partie 6 — Ce que le clustering ne change PAS

Il est important de noter ce que l'ajout de nœuds **ne modifie pas** :

- **Le modèle cryptographique** : E2E reste E2E, le cluster ne déchiffre pas plus qu'un seul nœud
- **Les permissions** : les grants et ACLs sont en DB, tous les nœuds les lisent identiquement
- **Les API keys** : fonctionnent sur tous les nœuds sans configuration supplémentaire (HMAC_KEY identique)
- **Les backups** : le lot 13/14 continue à fonctionner sur le nœud élu (advisory lock)
- **Les paths de secrets** (lot 18) : index en DB, cohérent sur tous les nœuds
- **L'i18n** : stateless, aucun impact

---

## Partie 7 — Décisions architecturales actées

Ces décisions sont **définitives** et ne doivent pas être remises en cause lors de l'implémentation.

| # | Décision | Raison |
|---|---|---|
| D-1 | Nœuds applicatifs stateless | Scalabilité simple, pas de coordination complexe |
| D-2 | Coordination via Postgres uniquement | Postgres est déjà le SPOF, pas de complexité additionnelle |
| D-3 | LISTEN/NOTIFY pour epoch et maintenance | Réactif, pas de polling intensif |
| D-4 | Advisory locks pour les opérations singleton | Atomique, libéré automatiquement si nœud crashe |
| D-5 | NTP obligatoire, pas de séquence par défaut | Simplifie le schéma, NTP est standard |
| D-6 | Configuration A (standalone) pour MVP | Complexité proportionnelle au besoin |
| D-7 | Pas de cache applicatif des métadonnées | Évite la complexité d'invalidation distribuée |
| D-8 | Pas de communication directe inter-nœuds | Postgres suffit, simplifie le déploiement |
| D-9 | Un seul scheduler de snapshots (élu) | Évite les snapshots en double |
| D-10 | Graceful shutdown 30s | Standard Kubernetes/Swarm, acceptable |

---

## Partie 8 — Roadmap d'implémentation clustering

Les lots suivants implémenteront les fondations posées ici, dans l'ordre :

### Lot 20 — Infrastructure de base cluster

- `GET /health` endpoint complet
- Graceful shutdown (SIGTERM handler)
- `HARPOCRATE_INSTANCE_ID` dans les logs
- Colonne `seq BIGSERIAL` sur `audit_log` (migration préventive)
- Tests : startup/shutdown propre, health check dans différents états

### Lot 21 — Cohérence epoch et maintenance en cluster

- Background task : LISTEN/NOTIFY sur `harpocrate_epoch_changed` et `harpocrate_maintenance_changed`
- Refresh périodique toutes les 5s comme filet de sécurité
- Rejet des requêtes si epoch RAM < epoch DB
- Tests : simulation changement d'epoch sur un nœud, vérification que les autres le détectent

### Lot 22 — Advisory locks et élection de leader

- `pg_advisory_lock` sur backup/restore (lot 12a revisité)
- Élection du scheduler de snapshots (lot 14 revisité)
- Tests : deux nœuds tentent un backup simultané → seul un gagne

### Lot 23 — Documentation déploiement cluster

- Docker Swarm : stack file multi-nœuds avec secrets management
- Kubernetes : Deployment + HPA + liveness/readiness probes
- Checklist déploiement (NTP, HMAC_KEY identique, Postgres reachable)
- Runbook : ajouter un nœud, retirer un nœud, rolling update

---

## Partie 9 — Hors scope (décisions explicites de ne PAS faire)

Ces sujets ont été considérés et **délibérément exclus** du périmètre Harpocrate.

| Sujet | Raison de l'exclusion |
|---|---|
| Sharding des secrets entre nœuds | Inutile : Postgres gère la volumétrie à ce stade |
| Réplication applicative (sans Postgres) | Complexité disproportionnée, Postgres suffit |
| Cache distribué (Redis, Memcached) | Dangereux (risque de leak de métadonnées), inutile (E2E) |
| Consensus distribué (Raft, Paxos) | Overkill, Postgres fournit déjà ACID |
| Multi-region active-active | Complexité de réplication Postgres cross-région hors scope |
| Secrets en RAM partagée entre nœuds | Impossible par définition (E2E, le serveur ne déchiffre pas) |
| Load balancing au niveau secret (shard par wallet) | Inutile, la charge est uniforme |
| WAL shipping applicatif | Délégué à Postgres (streaming replication) |

---

## Résumé pour Claude Code

Quand tu implémentes une feature dans Harpocrate qui pourrait être affectée par le clustering :

1. **Vérifie** que tu n'introduis pas d'état RAM local qui ne serait pas cohérent entre nœuds
2. **Vérifie** que les écritures critiques ont un `SELECT FOR UPDATE` ou une contrainte UNIQUE en DB
3. **Vérifie** que tu n'as pas besoin d'émettre un NOTIFY (epoch change, maintenance toggle)
4. **Vérifie** que les opérations singleton acquièrent l'advisory lock approprié
5. **Ne fais jamais** de coordination directe entre nœuds applicatifs (pas de HTTP inter-nœuds, pas de Redis pub/sub)
6. **Réfère-toi** à la liste des décisions actées (D-1 à D-10) avant de proposer une alternative

Ce document fait référence. En cas de doute, la règle la plus simple compatible avec les invariants I-1 à I-5 est la bonne.
