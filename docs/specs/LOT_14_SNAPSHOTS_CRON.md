# Lot 14 — Snapshots automatisés cron + rotation GFS

> **Prérequis** : Lots 00-13.

## Objectif

Mettre en place des **snapshots automatiques** pilotés par cron interne (asyncio task), avec **détection de changement** pour ne pas snapshot si rien n'a bougé, et **rotation GFS (Grandfather-Father-Son)** pour limiter le volume tout en gardant un historique long.

## Dépendances

- Lots 00-13

## Périmètre

### Inclus

- Tâche asyncio interne au backend qui se réveille toutes les N minutes
- Détection de changement via `MAX(updated_at)` cross-tables
- Création d'un snapshot (= backup standard) si changement
- Push vers destinations distantes configurées (lot 13)
- Rotation GFS configurable (hourly/daily/weekly/monthly retention)
- Endpoints `/v1/admin/snapshots/policy` (configure) et `/v1/admin/snapshots/trigger` (manuel)
- UI page `/admin/snapshots` : politique, historique, trigger manuel
- Logs de cycle structurés

### Exclus

- Pas de cron externe (k8s CronJob, systemd timer) — tout interne au container
- Pas de Point-in-time recovery vraiment fin (PITR Postgres natif)
- Pas de réplication WAL (overkill pour ce cas d'usage)

## Spécifications fonctionnelles

### Détection de changement

Calcul du « pulse » de la base à chaque tick de cron :

```sql
SELECT GREATEST(
  COALESCE((SELECT MAX(updated_at) FROM users), '1970-01-01'),
  COALESCE((SELECT MAX(updated_at) FROM wallets), '1970-01-01'),
  COALESCE((SELECT MAX(updated_at) FROM secrets), '1970-01-01'),
  COALESCE((SELECT MAX(occurred_at) FROM audit_log), '1970-01-01')
) AS last_change_at;
```

Si `last_change_at <= last_snapshot_at`, on skippe.

Note : on inclut audit_log pour ne pas rater des actions read-only (qui n'updatent pas users/wallets/secrets mais comptent comme activité métier à archiver).

### Politique GFS

Configurable via JSON :

```json
{
  "interval_minutes": 60,
  "retention": {
    "hourly": 24,
    "daily": 7,
    "weekly": 4,
    "monthly": 12,
    "yearly": 5
  },
  "push_remote_after_snapshot": true,
  "remote_destinations_to_push": ["all"],
  "skip_if_no_change": true
}
```

Lecture :
- Snapshot toutes les heures (interval_minutes=60)
- Garder 24 heures de snapshots horaires
- Garder 7 jours de snapshots quotidiens (1 par jour, le plus récent)
- Garder 4 semaines de snapshots hebdomadaires (1 par semaine)
- Garder 12 mois de snapshots mensuels
- Garder 5 ans de snapshots annuels
- Push automatique vers toutes les destinations distantes
- Skip si aucun changement détecté

### Endpoints

#### `GET /v1/admin/snapshots/policy`

- **Auth** : JWT + admin
- **Réponse** : JSON de la politique courante

#### `PUT /v1/admin/snapshots/policy`

- **Auth** : JWT + admin + reverify
- **Body** : JSON de politique
- **Validations** :
  - `interval_minutes >= 5`
  - Retention values >= 0
  - destinations exists
- **Effet** : update + redémarrage du timer interne

#### `POST /v1/admin/snapshots/trigger`

- **Auth** : JWT + admin
- **Body** :
```json
{
  "force": false,
  "skip_remote": false,
  "description": "Manual snapshot before risky operation"
}
```
- **Effet** : déclenche un snapshot maintenant. Si `force=false`, vérifie quand même la détection de changement.

#### `GET /v1/admin/snapshots/history`

- **Auth** : JWT + admin
- **Query** : `since`, `until`, `limit`, `cursor`, `tier` (hourly/daily/weekly/monthly/yearly)
- **Réponse** :
```json
{
  "snapshots": [
    {
      "id": "uuid",
      "filename": "harpocrate-snapshot-2026-05-02-14-00-00.tar.age",
      "created_at": "...",
      "tier": "hourly",
      "size_bytes": 12340567,
      "trigger": "auto|manual",
      "remote_pushes": [
        { "destination_name": "r2-primary", "success": true }
      ],
      "next_promotion_at": "2026-05-03T14:00:00Z",
      "next_deletion_at": "2026-05-03T14:00:00Z"
    }
  ]
}
```

### Logique de rotation

À chaque tick :

1. Liste les snapshots existants groupés par tier
2. Pour chaque tier (hourly/daily/weekly/monthly/yearly) :
   - Si nombre > retention → supprimer les plus vieux qui ne seront pas promus à un tier supérieur
3. Promotion :
   - Snapshot horaire le plus récent du jour → conservé comme "daily" si pas déjà fait
   - Snapshot quotidien le plus récent de la semaine → conservé comme "weekly"
   - Etc.

Algorithme :

```python
def rotate(snapshots: list[Snapshot], policy: GFSPolicy) -> list[SnapshotAction]:
    actions = []

    # Group by tier
    by_tier = {tier: [] for tier in ["hourly", "daily", "weekly", "monthly", "yearly"]}
    for s in snapshots:
        by_tier[s.tier].append(s)

    # Pour chaque tier descendant, trim au retention count
    for tier, retention in [
        ("hourly", policy.retention.hourly),
        ("daily", policy.retention.daily),
        ("weekly", policy.retention.weekly),
        ("monthly", policy.retention.monthly),
        ("yearly", policy.retention.yearly),
    ]:
        items = sorted(by_tier[tier], key=lambda s: s.created_at, reverse=True)
        keep = items[:retention]
        delete = items[retention:]

        for s in delete:
            actions.append(SnapshotAction(action="delete", snapshot_id=s.id))

    # Promotion : à chaque transition de période
    # - Si on n'a pas de daily pour aujourd'hui, promouvoir le hourly le plus récent du jour précédent
    # - Idem week/month/year

    today = date.today()
    yesterday = today - timedelta(days=1)

    has_daily_for_yesterday = any(
        s.created_at.date() == yesterday for s in by_tier["daily"]
    )
    if not has_daily_for_yesterday:
        candidate = next(
            (s for s in sorted(by_tier["hourly"], key=lambda s: s.created_at, reverse=True)
             if s.created_at.date() == yesterday),
            None,
        )
        if candidate:
            actions.append(SnapshotAction(
                action="promote", snapshot_id=candidate.id, new_tier="daily"
            ))

    # Idem pour weekly (chaque dimanche), monthly (1er du mois), yearly (1er janvier)
    # ...

    return actions
```

### Tâche asyncio

```python
# app/services/snapshot_scheduler.py

import asyncio
from datetime import datetime, timedelta


class SnapshotScheduler:
    def __init__(self, pool, settings, backup_service, remote_service):
        self.pool = pool
        self.settings = settings
        self.backup_service = backup_service
        self.remote_service = remote_service
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self):
        policy = await self._load_policy()
        if policy.interval_minutes <= 0:
            logger.info("snapshot_scheduler_disabled")
            return

        self._task = asyncio.create_task(self._run_loop(policy))
        logger.info("snapshot_scheduler_started", interval=policy.interval_minutes)

    async def stop(self):
        if self._task:
            self._stop.set()
            await self._task

    async def _run_loop(self, policy):
        while not self._stop.is_set():
            try:
                await self._tick(policy)
            except Exception as e:
                logger.error("snapshot_tick_failed", error=str(e))

            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=policy.interval_minutes * 60,
                )
            except asyncio.TimeoutError:
                pass  # normal, on continue

    async def _tick(self, policy):
        async with self.pool.acquire() as conn:
            # 1. Détection de changement
            last_change = await conn.fetchval("""
                SELECT GREATEST(
                  COALESCE((SELECT MAX(updated_at) FROM users), '1970-01-01'),
                  COALESCE((SELECT MAX(updated_at) FROM wallets), '1970-01-01'),
                  COALESCE((SELECT MAX(updated_at) FROM secrets), '1970-01-01'),
                  COALESCE((SELECT MAX(occurred_at) FROM audit_log), '1970-01-01')
                )
            """)
            last_snapshot = await conn.fetchval(
                "SELECT MAX(created_at) FROM backups_local WHERE filename LIKE 'harpocrate-snapshot-%'"
            )

            if policy.skip_if_no_change and last_snapshot and last_change <= last_snapshot:
                logger.info("snapshot_skipped_no_change",
                           last_change=last_change.isoformat(),
                           last_snapshot=last_snapshot.isoformat())
                return

            # 2. Création du snapshot
            logger.info("snapshot_creating", trigger="auto")
            backup = await self.backup_service.create_backup(
                description="Auto snapshot",
                filename_prefix="harpocrate-snapshot",
                tier="hourly",  # par défaut, promu plus tard
            )

            # 3. Push remote si configuré
            if policy.push_remote_after_snapshot:
                destinations = await self._resolve_destinations(policy)
                if destinations:
                    await self.remote_service.push(backup.id, destinations)

            # 4. Rotation
            await self._apply_rotation(policy)

    async def _apply_rotation(self, policy):
        async with self.pool.acquire() as conn:
            snapshots = await conn.fetch("""
                SELECT id, filename, created_at, manifest->>'tier' AS tier
                FROM backups_local
                WHERE filename LIKE 'harpocrate-snapshot-%'
                ORDER BY created_at DESC
            """)

            actions = rotate(snapshots, policy)

            for action in actions:
                if action.action == "delete":
                    await self._delete_snapshot(conn, action.snapshot_id)
                elif action.action == "promote":
                    await self._promote_snapshot(conn, action.snapshot_id, action.new_tier)
```

### Hook lifecycle FastAPI

```python
# app/main.py

@app.on_event("startup")
async def on_startup():
    # ... existing startup ...
    app.state.snapshot_scheduler = SnapshotScheduler(
        pool=app.state.pool,
        settings=settings,
        backup_service=app.state.backup_service,
        remote_service=app.state.remote_service,
    )
    await app.state.snapshot_scheduler.start()

@app.on_event("shutdown")
async def on_shutdown():
    if hasattr(app.state, "snapshot_scheduler"):
        await app.state.snapshot_scheduler.stop()
```

### Page UI `/admin/snapshots`

```
Automated snapshots
═════════════════════════════════════════════════

Status: ✓ Active (interval: every 60 minutes)
Last snapshot: 23 minutes ago
Next snapshot: in 37 minutes

─── Retention policy ───

Hourly:    24 snapshots  (last 24 hours)
Daily:      7 snapshots  (last week)
Weekly:     4 snapshots  (last month)
Monthly:   12 snapshots  (last year)
Yearly:     5 snapshots  (last 5 years)

Total estimated max: ~52 snapshots × 12 MB = ~625 MB local

Skip if no change: ✓ enabled
Push to remote after snapshot: ✓ enabled
Push destinations: r2-primary, b2-secondary

[Edit policy]

─── Manual trigger ───

[Trigger snapshot now]
[Trigger snapshot now (force, even if no change)]

─── History ───

Filter: [All tiers ▾]

┌──────────────────┬─────────┬──────────┬─────────────┬─────────────┐
│ Created          │ Tier    │ Size     │ Remote push │ Next action │
├──────────────────┼─────────┼──────────┼─────────────┼─────────────┤
│ 14:00 (23m ago)  │ hourly  │ 12.3 MB  │ ✓✓ 2/2      │ promote→day │
│ 13:00            │ hourly  │ 12.3 MB  │ ✓✓ 2/2      │ delete in 23h│
│ ...              │ ...     │ ...      │ ...         │ ...         │
│ 2026-05-01 14:00 │ daily   │ 12.1 MB  │ ✓✓ 2/2      │ delete in 6d │
│ 2026-04-25 14:00 │ weekly  │ 11.8 MB  │ ✓✓ 2/2      │ delete in 3w │
│ 2026-04-01 14:00 │ monthly │ 11.2 MB  │ ✓✓ 2/2      │ delete in11mo│
│ 2026-01-01 00:00 │ yearly  │ 10.5 MB  │ ✓✓ 2/2      │ delete in 5y │
└──────────────────┴─────────┴──────────┴─────────────┴─────────────┘
```

### Modal "Edit policy"

```
Snapshot policy

Interval (minutes):     [60     ] (minimum 5)
Skip if no change:      [☑]
Push to remote after:   [☑]

Retention:
  Hourly:   [24] snapshots
  Daily:    [ 7] snapshots
  Weekly:   [ 4] snapshots
  Monthly:  [12] snapshots
  Yearly:   [ 5] snapshots

Remote destinations to push:
  ☑ r2-primary
  ☑ b2-secondary
  ☐ minio-homelab

⚠ Estimated max storage:
  Local: ~52 snapshots × 12 MB = ~625 MB
  Remote (per destination): same

[Cancel]  [Save policy]
```

## Spécifications techniques

### Migration

```sql
-- migrations/005_snapshots_policy.sql

-- Stockage de la politique
INSERT INTO system_metadata (key, value) VALUES
('snapshot_policy', '{
  "interval_minutes": 0,
  "retention": {
    "hourly": 24,
    "daily": 7,
    "weekly": 4,
    "monthly": 12,
    "yearly": 5
  },
  "push_remote_after_snapshot": false,
  "remote_destinations_to_push": [],
  "skip_if_no_change": true
}'::jsonb);

-- Tracking des promotions/déletions
ALTER TABLE backups_local ADD COLUMN tier TEXT;
ALTER TABLE backups_local ADD COLUMN promoted_from_id UUID REFERENCES backups_local(id);

CREATE INDEX idx_backups_local_tier ON backups_local(tier) WHERE tier IS NOT NULL;
```

### Logs structurés du cycle

À chaque tick :

```json
{
  "event": "snapshot_tick",
  "timestamp": "...",
  "policy_interval_minutes": 60,
  "last_change_at": "...",
  "last_snapshot_at": "...",
  "skipped": false,
  "snapshot_created": true,
  "snapshot_id": "uuid",
  "snapshot_size_bytes": 12340567,
  "remote_pushes": [
    { "destination": "r2-primary", "success": true, "duration_ms": 3450 }
  ],
  "rotation_actions": [
    { "action": "delete", "snapshot_id": "...", "reason": "exceeded hourly retention" },
    { "action": "promote", "snapshot_id": "...", "from": "hourly", "to": "daily" }
  ],
  "duration_ms": 5670
}
```

### Coordination avec backups manuels

Les snapshots automatiques sont nommés `harpocrate-snapshot-*` et les backups manuels `harpocrate-backup-*`. Distinction dans la DB via `tier` (NULL pour manuel).

Le mécanisme de rotation ne touche jamais les backups manuels.

## Critères de succès

1. ✅ Tick à intervalle correct
2. ✅ Détection de changement fonctionne
3. ✅ Skip si pas de changement (avec policy.skip_if_no_change=true)
4. ✅ Force snapshot manuel ignore le skip
5. ✅ Premier tick depuis instance propre fait un snapshot
6. ✅ Rotation horaire respecte le compte
7. ✅ Promotion automatique horaire → quotidien
8. ✅ Promotion quotidien → hebdo (chaque dimanche)
9. ✅ Promotion hebdo → mensuel (1er du mois)
10. ✅ Promotion mensuel → annuel (1er janvier)
11. ✅ Suppression des snapshots obsolètes
12. ✅ Backups manuels jamais supprimés par rotation
13. ✅ Push remote après snapshot
14. ✅ UI affiche statut, prochaine exécution, historique
15. ✅ Edit policy redémarre le scheduler
16. ✅ Trigger manuel fonctionne

## Pièges connus

- **Tâche asyncio dans FastAPI** : si le serveur est multi-process (gunicorn), chaque worker lance son scheduler → snapshots en double. **Solution MVP** : utiliser uvicorn mono-worker. **Solution prod** : un lock distributé via Postgres advisory lock (`pg_try_advisory_lock`) au tick, seul un worker prend le lock.
- **Détection de changement audit_log** : le `MAX(occurred_at)` peut être lourd sur grosse table. Index `(occurred_at DESC)` déjà créé. À monitorer.
- **Snapshot pendant un autre snapshot** : peut arriver si tick > duration. Lock advisory également.
- **Rotation pendant restore** : ne pas rotater si le mode maintenance est actif.
- **Promotion vs déletion ordre** : promouvoir AVANT de supprimer, sinon on peut perdre le candidat à promouvoir.
- **Rotation lourde** : si beaucoup de snapshots, le DELETE en masse peut prendre du temps. Faire en background ou par batch.
- **Datetime timezones** : tous en UTC. Postgres stocke en `TIMESTAMPTZ`. Toujours `NOW()` pour le serveur.
- **Persistance du timer après restart** : le scheduler redémarre au boot du conteneur. Donc si crash juste avant un tick, on peut rater une heure. Acceptable pour MVP.
- **Politique avec `interval_minutes=0`** : désactivation propre du scheduler.
- **Skip + audit_log** : tout READ-only crée un audit_log entry. Donc skip_if_no_change ne skippe que si **personne n'a fait quoi que ce soit**, ce qui est rare. À ajuster : option d'ignorer audit_log dans la détection (pour ne snapshotter que si data métier change).

## Tests

- `test_snapshot_scheduler_starts_and_stops`
- `test_skip_when_no_change`
- `test_create_snapshot_on_change`
- `test_force_snapshot_ignores_skip`
- `test_rotation_trims_hourly`
- `test_promotion_hourly_to_daily`
- `test_promotion_daily_to_weekly_on_sunday`
- `test_rotation_does_not_touch_manual_backups`
- `test_remote_push_after_snapshot`
- `test_policy_change_restarts_scheduler`
- `test_advisory_lock_prevents_concurrent_ticks`
- `test_manual_trigger`
- `test_history_filtering_by_tier`

## Conclusion du backup

Avec les lots 12, 13, 14, le système de backup couvre :

| Risque | Couverture |
|---|---|
| Crash disque, perte VM | Lot 12 (local) |
| Erreur humaine, DROP | Lot 12 (restore manuel) |
| Migration vers autre infra | Lot 12 (download + upload) |
| Ransomware sur la machine | Lot 13 (remote + Object Lock) |
| Sinistre site | Lot 13 (remote multi-destination) |
| Point-in-time recovery | Lot 14 (snapshots GFS) |
| Compromission credentials S3 | Lot 13 (Object Lock empêche delete) |

**Reste hors scope :**
- HSM/TPM pour `HMAC_KEY` (roadmap)
- Restore granulaire 1 wallet (roadmap)
- Réplication WAL Postgres native (roadmap, sortie du périmètre Harpocrate)

## Ce qui suit

C'est la fin du backend Harpocrate. La suite sera de la **documentation utilisateur multilingue** (FR + EN) en 8 fichiers : user guide, admin guide, installation, backup/restore, automation, best practices, keys & recovery, defense in depth.
