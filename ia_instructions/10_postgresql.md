# Fragment — PostgreSQL (`backend/migrations/`, repositories, toute requête SQL)

> Source : globals › « Fichier d'instructions — spécificités PostgreSQL » (révision 2026-09-02).
> Déclencheur : avant d'écrire ou de modifier une migration, une requête SQL, ou un fichier
> de `backend/app/db/`.

### État en base

- Migrations = fichiers **numérotés immuables**. Une migration appliquée ne s'édite JAMAIS : elle est déjà jouée ailleurs, la corriger fait diverger les bases
- Réconciliation **additive** : ajouter une colonne nullable est automatique ; renommer ou supprimer exige une migration explicite, relue
- Requêtes **toujours paramétrées**. Une f-string dans du SQL est une faute, pas un raccourci
- Une opération de cycle de vie = **une** transaction
- Les invariants qu'un DDL ne sait pas exprimer sont validés applicativement **et testés**

## Spécifique Harpocrate

- PostgreSQL 16, extensions `pgcrypto` et `uuid-ossp` (`db/init/01-extensions.sql`).
  **Source de vérité unique** ; coordination de cluster par `LISTEN/NOTIFY` et advisory locks.
  Pas de Redis, pas de cache distribué.
- Migrations : `backend/migrations/NNN_<nom>.sql` (dernière à ce jour : `032_…` — **relire
  `ls backend/migrations` avant d'en créer une**). Appliquées au boot par le lifespan FastAPI
  (`migrations/apply_migrations.py`), chacune dans sa transaction, tracées dans `_migrations`
  **avec leur SHA-256** : éditer une migration déjà appliquée fait **échouer le boot**
  (`checksum mismatch`). Pas de CLI dédiée.
- `SELECT … FOR UPDATE` pour les opérations critiques concurrentes ;
  `async with conn.transaction():` pour tout ce qui touche plusieurs tables.
- Existant à ne pas reproduire : quelques repositories construisent une **liste de colonnes**
  par f-string (`wallets.py`, `remote_backup_connections.py`, `pairing_sessions.py`,
  `scheduled_backups.py`) à partir de constantes ou de champs validés, les valeurs restant
  paramétrées. Ne pas étendre ce motif ; ne jamais y faire entrer une donnée utilisateur.
- `apply_migrations.py` se connecte avec `settings.db_dsn` et journalise via `logging`
  (écarts connus vis-à-vis de `LESSONS.md` [db] et de la règle structlog) — à traiter dans
  une tâche dédiée, pas au passage.
- Test de migration : `backend/tests/test_apply_migrations.py` (runner) ; les tests
  d'intégration sur une vraie base ne tournent que si `HARPOCRATE_DB_DSN_TEST` est défini
  (sinon ils sont **skippés**, ce qui n'est pas un succès — le dire dans le compte rendu).

## Pièges connus

**Une violation de contrainte avorte la transaction entière.** Sur PostgreSQL, un `INSERT` en conflit ne se rattrape pas par un simple `try/except` si la transaction doit continuer : il faut un point de sauvegarde (`SAVEPOINT` / `begin_nested`). C'est décisif quand le conflit est le cas **normal** — une idempotence portée par une contrainte d'unicité, par exemple.

**L'idempotence se joue à l'écriture, jamais par une lecture préalable.** Entre un `SELECT` et un `INSERT`, deux appels concurrents passent tous les deux. On insère, et c'est la base qui tranche.

**Vérifier une migration sur une base vierge ET sur une base existante.** Une migration qui ne passe que sur l'une des deux se découvre en production.

**Un numéro de migration se collisionne dès qu'on travaille à plusieurs.** Vérifier le dernier numéro réellement présent avant d'en créer un — pas celui qu'on croit se rappeler.

**Une table peut déjà exister.** Avant d'en créer une, chercher son nom dans les migrations et le schéma : trouver une table écrite il y a longtemps et jamais appelée est plus fréquent qu'on ne le croit.

## Part de checklist

- [ ] La migration ajoutée porte un numéro libre, vérifié contre l'existant
- [ ] Elle rejoue sur base vierge **et** sur base existante
- [ ] Aucune migration déjà appliquée n'a été modifiée
- [ ] Aucune requête construite par concaténation ou f-string
- [ ] Le nom de toute table ou colonne ajoutée a été cherché avant, pour ne pas doubler l'existant
