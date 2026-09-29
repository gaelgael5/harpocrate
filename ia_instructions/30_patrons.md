# Fragment — Patrons de conception

> Source : globals › « Fichier d'instructions — Patrons de conception (agnostique) » (révision 2026-09-02).
> Déclencheur : avant d'introduire une nouvelle abstraction — classe de base, interface,
> factory, stratégie, bus d'événements, décorateur, proxy — ou de proposer un refactor
> structurel.

## Deux règles avant tout le reste

- **Le patron le plus simple qui résout le problème.** Pas le plus élégant, pas le plus général.
- **Aucun patron s'il n'y a pas de problème.** Une fonction qui suffit doit rester une fonction.
  Une abstraction posée « au cas où » ne se retire jamais.

La section **« Quand ne PAS l'utiliser »** de chaque patron n'est pas une note de bas de page :
c'est souvent la plus utile des deux.

Les exemples du catalogue sont en Python : **transposer l'intention, pas la syntaxe** —
découpage des responsabilités, sens des dépendances, ce qui est stable et ce qui varie.

## Où lire le catalogue

- Référence : docflow, workspace `globals`, document « Fichier d'instructions — Patrons de
  conception (agnostique) » (via RAG `globals-docs`).
- L'ancienne copie locale `docs/patterns/*.md` a été retirée du dépôt le 2026-09-24 (doublon
  du document globals) : ne pas la recréer.

## Patrons déjà en place dans Harpocrate — les réutiliser avant d'en créer

- **Repository** : `backend/app/db/repositories/` (asyncpg, un module par agrégat).
- **Strategy / Adapter** : fournisseurs de backup distants `services/remote_backup_providers/`
  (S3-compatible, SFTP, FTPS, Google Drive ; base `base.py`), exécuteurs de pairing `services/pairing_exec/` (Docker / SSH natif).
- **Observer / Event-driven** : `LISTEN/NOTIFY` (`core/cluster_sync.py`, `services/cluster_notify.py`)
  et MQTT (`core/sync_publisher.py`, `core/sync_consumer.py`).
- **Singleton de module** : `settings` (`core/config.py`), pool (`db/pool.py`) — jamais capturé
  dans un objet longue durée (cf. `ia_instructions/10_python.md`).

## Part de checklist

- [ ] L'abstraction ajoutée répond à un problème présent, pas hypothétique
- [ ] Un patron existant du dépôt a été cherché avant d'en introduire un nouveau
- [ ] La section « Quand ne PAS l'utiliser » du patron retenu a été relue
