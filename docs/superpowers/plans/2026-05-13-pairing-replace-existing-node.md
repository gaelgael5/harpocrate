# Pairing v2 — remplacement explicite d'un node existant — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre la reprise propre d'un pairing v2 quand un node de réplication portant la même URL existe déjà côté master, via une confirmation explicite de remplacement côté admin du standby (avec audit log et DROP ROLE de l'ancien rôle PG), au lieu de planter en 500 (`UniqueViolationError` non gérée).

**Architecture :** Le master `/confirm-v2` catche les violations d'unicité sur `replication_nodes(label, application_name)` → renvoie 409 `node_already_exists` avec les détails du node existant (`id, label, host, last_state, last_seen_at, application_name`). Le standby `/accept-v2` retransmet le 409 transparent. Le frontend du standby (`BecomeStandbyPage`) ouvre alors une modale `ConfirmReplaceNodeModal` qui montre les détails et propose de remplacer ; sur confirmation, il rappelle `/accept-v2` avec `force: true`, ce qui propage `force=true` au master qui DELETE+DROP ROLE+INSERT+CREATE ROLE dans une seule transaction, audit log `pairing.master_node_replaced`.

**Tech Stack :** Backend Python 3.12 + FastAPI + asyncpg + Pydantic v2 + structlog + pytest-asyncio. Frontend Vite + React 18 + TypeScript strict + TanStack Query + Mantine + i18next + Vitest.

---

## File Structure

**Backend :**
- Modify `backend/app/services/pairing.py` — ajoute `NodeAlreadyExistsError`
- Modify `backend/app/services/streaming_replication.py` — `add_node` : catche `UniqueViolationError`, paramètre `replace_existing: bool = False`
- Modify `backend/app/services/pairing_v2.py` — `confirm_master_v2` : paramètre `force: bool = False` + propagation, audit log replacement ; `accept_standby_v2` : paramètre `force` + parsing du 409 master en exception `NodeAlreadyExistsError`
- Modify `backend/app/models/api/pairing.py` — `PairingConfirmV2Request.force` et `PairingAcceptV2Request.force`
- Modify `backend/app/api/v1/admin_replication_pairing.py` — mapping `NodeAlreadyExistsError` → 409 sur `/confirm-v2` ET `/accept-v2`
- Create `backend/tests/test_streaming_replication_add_node.py` — nouveaux tests unitaires add_node (si déjà existant : étendre)
- Modify `backend/tests/test_pairing_v2_service.py` — tests confirm + accept avec force
- Modify `backend/tests/test_pairing_api_v2.py` — tests endpoint 409 / 200 avec force

**Frontend :**
- Modify `frontend/src/lib/api-client.ts` — `ApiError` porte un champ `detail: unknown` (le body JSON brut)
- Modify `frontend/src/lib/adminApi.ts` — `acceptPairingV2(pairingUrl, force?)`
- Modify `frontend/src/schemas/pairing.ts` — `ExistingNodeSchema`
- Create `frontend/src/components/ConfirmReplaceNodeModal.tsx`
- Modify `frontend/src/pages/BecomeStandbyPage.tsx` — gestion du 409 + modale + retry
- Modify `frontend/src/i18n/fr.json` — libellés modale + erreur
- Modify `frontend/src/i18n/en.json` — idem en
- Create `frontend/src/tests/confirmReplaceNodeModal.test.tsx`
- Create `frontend/src/tests/becomeStandbyPageReplaceFlow.test.tsx`

---

## Task 1: Exception `NodeAlreadyExistsError` côté service

**Files:**
- Modify: `backend/app/services/pairing.py` (ajout après `InvalidPairingPreconditionError`)

- [ ] **Step 1: Ajouter la classe d'exception**

Dans `backend/app/services/pairing.py`, après la classe `InvalidPairingPreconditionError` (ligne ~45) :

```python
class NodeAlreadyExistsError(InvalidPairingPreconditionError):
    """Un node de réplication avec ce label ou application_name existe déjà.

    `existing_node` est un dict sérialisable JSON décrivant la row existante :
    id, label, host, application_name, last_state (str | None), last_seen_at
    (ISO 8601 str | None).
    """

    def __init__(self, existing_node: dict[str, object]) -> None:
        super().__init__("node_already_exists")
        self.existing_node = existing_node
```

- [ ] **Step 2: Vérifier que ruff passe**

Run: `cd backend && uv run ruff check src/app/services/pairing.py`
Expected: pas d'erreur.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/pairing.py
git commit -m "feat(pairing): exception NodeAlreadyExistsError portant le node existant"
```

---

## Task 2: `add_node` catche `UniqueViolationError` → `NodeAlreadyExistsError`

**Files:**
- Modify: `backend/app/services/streaming_replication.py:262-337` (fonction `add_node`)
- Modify: `backend/app/db/repositories/replication_nodes.py:42-65` (utiliser le repo existant)
- Test: `backend/tests/test_streaming_replication_add_node.py` (créer si absent)

- [ ] **Step 1: Vérifier l'existence d'un fichier de test pour add_node**

Run: `ls backend/tests/ | grep streaming_replication`
- Si un fichier existe → étendre.
- Sinon → créer `backend/tests/test_streaming_replication_add_node.py`.

- [ ] **Step 2: Écrire le test rouge — collision label**

Dans le fichier de test :

```python
"""Tests unitaires add_node — branches d'erreur (LOT 5 fix conflit label)."""

from __future__ import annotations

import asyncpg
import pytest

from app.db.repositories import replication_strategies as strat_repo
from app.services import pairing as svc_pairing
from app.services import streaming_replication as svc


async def _create_active_strategy(conn: asyncpg.Connection[asyncpg.Record]) -> str:
    sid = await strat_repo.create(
        conn,
        env_type="docker_compose",
        config={"compose_file": "/tmp/x.yml"},
        notes="test",
        created_by_user_id=None,
    )
    await strat_repo.set_active(conn, strategy_id=sid)
    return sid


async def test_add_node_label_collision_raises_node_already_exists(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        strat_id = await _create_active_strategy(conn)
        try:
            node_id_1, _ = await svc.add_node(
                conn,
                strategy_id=strat_id,
                label="https://b.example/",
                host="b.example",
                port=5432,
                role="standby_ro",
                notes=None,
                master_host="a.example",
                master_port=5432,
                created_by_user_id=None,
            )
            with pytest.raises(svc_pairing.NodeAlreadyExistsError) as exc_info:
                await svc.add_node(
                    conn,
                    strategy_id=strat_id,
                    label="https://b.example/",
                    host="b.example",
                    port=5432,
                    role="standby_ro",
                    notes=None,
                    master_host="a.example",
                    master_port=5432,
                    created_by_user_id=None,
                )
            details = exc_info.value.existing_node
            assert details["id"] == str(node_id_1)
            assert details["label"] == "https://b.example/"
            assert details["host"] == "b.example"
            assert "application_name" in details
            assert "last_state" in details
            assert "last_seen_at" in details
        finally:
            await conn.execute(
                "DELETE FROM replication_nodes WHERE strategy_id = $1",
                strat_id,
            )
            await conn.execute("DELETE FROM replication_strategies WHERE id = $1", strat_id)
            await conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE usename LIKE 'repl_%'"
            )
            # drop best-effort des roles repl_* créés par add_node
            roles = await conn.fetch(
                "SELECT rolname FROM pg_roles WHERE rolname LIKE 'repl_%'"
            )
            for r in roles:
                await conn.execute(f"DROP ROLE IF EXISTS {r['rolname']}")
```

- [ ] **Step 3: Faire tourner le test → rouge attendu**

Run: `cd backend && uv run pytest tests/test_streaming_replication_add_node.py -v`
Expected: FAIL avec `asyncpg.exceptions.UniqueViolationError` non transformée.

- [ ] **Step 4: Implémenter la transformation dans `add_node`**

Dans `backend/app/services/streaming_replication.py`, remplacer la fonction `add_node` (lignes ~262-337) par :

```python
async def add_node(
    conn: asyncpg.Connection,
    *,
    strategy_id: UUID,
    label: str,
    host: str,
    port: int,
    role: str,
    notes: str | None,
    master_host: str,
    master_port: int,
    standby_data_dir: str = "/var/lib/postgresql/16/main",
    created_by_user_id: UUID | None = None,
) -> tuple[UUID, NodeBundle]:
    """Crée le rôle Postgres + insère le node + retourne le bundle.

    Tout est en transaction : si l'INSERT échoue, on DROP le rôle pour ne
    pas laisser d'orphelin côté master. Si l'INSERT échoue à cause d'un
    conflit d'unicité sur `label` ou `application_name`, on remonte une
    `NodeAlreadyExistsError` typée qui porte les détails du node existant.
    """
    from app.services.pairing import NodeAlreadyExistsError

    replication_user = make_replication_user(label)
    application_name = make_application_name(label)
    password = generate_password()

    try:
        async with conn.transaction():
            safe_password = password.replace("'", "''")
            await conn.execute(
                f"CREATE ROLE {replication_user} REPLICATION LOGIN PASSWORD '{safe_password}'"
            )
            try:
                node_id = await nodes_repo.insert(
                    conn,
                    strategy_id=strategy_id,
                    label=label,
                    host=host,
                    port=port,
                    replication_user=replication_user,
                    application_name=application_name,
                    role=role,
                    notes=notes,
                    created_by_user_id=created_by_user_id,
                )
            except Exception:
                logger.warning(
                    "replication_node_insert_failed_role_will_be_rolled_back",
                    replication_user=replication_user,
                )
                raise
    except asyncpg.UniqueViolationError as exc:
        existing = await _load_existing_node_details(
            conn,
            label=label,
            application_name=application_name,
        )
        if existing is None:
            # On a vu une UniqueViolation mais on ne retrouve pas la row ?
            # Ne pas masquer l'incohérence — remonter telle quelle.
            raise
        raise NodeAlreadyExistsError(existing) from exc

    bundle = _build_bundle(
        node_id=node_id,
        replication_user=replication_user,
        application_name=application_name,
        password=password,
        master_host=master_host,
        master_port=master_port,
        standby_host=host,
        standby_data_dir=standby_data_dir,
    )
    logger.info(
        "replication_node_added",
        node_id=str(node_id),
        replication_user=replication_user,
        application_name=application_name,
        standby_host=host,
    )
    return node_id, bundle


async def _load_existing_node_details(
    conn: asyncpg.Connection,
    *,
    label: str,
    application_name: str,
) -> dict[str, object] | None:
    """Récupère le node existant qui a déclenché la `UniqueViolationError`.

    Le conflit peut venir de l'index sur `LOWER(label)` ou sur
    `LOWER(application_name)` — on cherche les deux.
    """
    row = await conn.fetchrow(
        """
        SELECT id, label, host, application_name, last_state, last_seen_at
        FROM replication_nodes
        WHERE LOWER(label) = LOWER($1) OR LOWER(application_name) = LOWER($2)
        LIMIT 1
        """,
        label,
        application_name,
    )
    if row is None:
        return None
    last_seen_at = row["last_seen_at"]
    return {
        "id": str(row["id"]),
        "label": row["label"],
        "host": row["host"],
        "application_name": row["application_name"],
        "last_state": row["last_state"],
        "last_seen_at": last_seen_at.isoformat() if last_seen_at is not None else None,
    }
```

- [ ] **Step 5: Faire tourner le test → vert attendu**

Run: `cd backend && uv run pytest tests/test_streaming_replication_add_node.py -v`
Expected: PASS.

- [ ] **Step 6: Ruff**

Run: `cd backend && uv run ruff check src/app/services/streaming_replication.py tests/test_streaming_replication_add_node.py`
Expected: pas d'erreur.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/streaming_replication.py backend/tests/test_streaming_replication_add_node.py
git commit -m "fix(replication): add_node remonte NodeAlreadyExistsError typée sur conflit label/app_name"
```

---

## Task 3: `add_node` accepte `replace_existing: bool = False`

**Files:**
- Modify: `backend/app/services/streaming_replication.py` (fonction `add_node`)
- Modify: `backend/tests/test_streaming_replication_add_node.py`

- [ ] **Step 1: Écrire le test rouge — remplacement**

Ajouter dans le fichier de test :

```python
async def test_add_node_with_replace_existing_replaces_collision(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        strat_id = await _create_active_strategy(conn)
        try:
            node_id_1, _bundle_1 = await svc.add_node(
                conn,
                strategy_id=strat_id,
                label="https://b.example/",
                host="b.example",
                port=5432,
                role="standby_ro",
                notes=None,
                master_host="a.example",
                master_port=5432,
                created_by_user_id=None,
            )
            node_id_2, bundle_2 = await svc.add_node(
                conn,
                strategy_id=strat_id,
                label="https://b.example/",
                host="b.example",
                port=5432,
                role="standby_ro",
                notes=None,
                master_host="a.example",
                master_port=5432,
                created_by_user_id=None,
                replace_existing=True,
            )
            assert node_id_2 != node_id_1
            old = await conn.fetchrow(
                "SELECT id FROM replication_nodes WHERE id = $1", node_id_1
            )
            assert old is None  # ancienne row supprimée
            new = await conn.fetchrow(
                "SELECT id FROM replication_nodes WHERE id = $1", node_id_2
            )
            assert new is not None
            assert bundle_2.password != ""
        finally:
            await conn.execute(
                "DELETE FROM replication_nodes WHERE strategy_id = $1", strat_id
            )
            await conn.execute("DELETE FROM replication_strategies WHERE id = $1", strat_id)
            roles = await conn.fetch(
                "SELECT rolname FROM pg_roles WHERE rolname LIKE 'repl_%'"
            )
            for r in roles:
                await conn.execute(f"DROP ROLE IF EXISTS {r['rolname']}")
```

- [ ] **Step 2: Faire tourner → rouge attendu**

Run: `cd backend && uv run pytest tests/test_streaming_replication_add_node.py::test_add_node_with_replace_existing_replaces_collision -v`
Expected: FAIL — `add_node` n'accepte pas `replace_existing` (`TypeError`).

- [ ] **Step 3: Implémenter le paramètre**

Dans `add_node`, modifier la signature et le bloc `try` :

```python
async def add_node(
    conn: asyncpg.Connection,
    *,
    strategy_id: UUID,
    label: str,
    host: str,
    port: int,
    role: str,
    notes: str | None,
    master_host: str,
    master_port: int,
    standby_data_dir: str = "/var/lib/postgresql/16/main",
    created_by_user_id: UUID | None = None,
    replace_existing: bool = False,
) -> tuple[UUID, NodeBundle]:
```

Puis ajouter une boucle de retry contrôlée : après attrapage de la `UniqueViolationError`, si `replace_existing` est vrai, on supprime explicitement l'ancien node (DROP ROLE + DELETE row) et on réessaie une fois. Remplacer le bloc `except asyncpg.UniqueViolationError` par :

```python
    except asyncpg.UniqueViolationError as exc:
        existing = await _load_existing_node_details(
            conn,
            label=label,
            application_name=application_name,
        )
        if existing is None:
            raise
        if not replace_existing:
            raise NodeAlreadyExistsError(existing) from exc

        # Remplacement explicite : delete + retry.
        existing_id = UUID(str(existing["id"]))
        await delete_node(conn, existing_id)
        logger.info(
            "replication_node_replaced",
            old_node_id=str(existing_id),
            new_label=label,
        )
        async with conn.transaction():
            safe_password = password.replace("'", "''")
            await conn.execute(
                f"CREATE ROLE {replication_user} REPLICATION LOGIN PASSWORD '{safe_password}'"
            )
            node_id = await nodes_repo.insert(
                conn,
                strategy_id=strategy_id,
                label=label,
                host=host,
                port=port,
                replication_user=replication_user,
                application_name=application_name,
                role=role,
                notes=notes,
                created_by_user_id=created_by_user_id,
            )
```

Important : `delete_node` est exécuté hors de la transaction parente (qui a déjà rollback à cause de la `UniqueViolationError`). Le retry crée sa propre transaction. Si le retry échoue à nouveau, on laisse l'exception propager (rare cas : double-insertion concurrente — l'admin retry).

- [ ] **Step 4: Faire tourner → vert attendu**

Run: `cd backend && uv run pytest tests/test_streaming_replication_add_node.py -v`
Expected: les deux tests passent.

- [ ] **Step 5: Ruff**

Run: `cd backend && uv run ruff check src/app/services/streaming_replication.py`

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/streaming_replication.py backend/tests/test_streaming_replication_add_node.py
git commit -m "feat(replication): add_node accepte replace_existing pour remplacer un node en conflit"
```

---

## Task 4: `confirm_master_v2` accepte `force` + audit log

**Files:**
- Modify: `backend/app/services/pairing_v2.py:137-211` (fonction `confirm_master_v2`)
- Modify: `backend/tests/test_pairing_v2_service.py`

- [ ] **Step 1: Test rouge — conflit sans force**

Ajouter dans `backend/tests/test_pairing_v2_service.py` :

```python
async def test_confirm_master_v2_raises_node_already_exists_on_label_collision(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    """Si un node existe déjà pour ce standby_url, on lève NodeAlreadyExistsError."""
    async with real_db_pool.acquire() as conn:
        from app.db.repositories import replication_strategies as strat_repo
        from app.services import streaming_replication as streaming_svc

        strat_id = await strat_repo.create(
            conn,
            env_type="docker_compose",
            config={"compose_file": "/tmp/x.yml"},
            notes="test",
            created_by_user_id=None,
        )
        await strat_repo.set_active(conn, strategy_id=strat_id)

        # 1) crée un node existant pour b.example
        await streaming_svc.add_node(
            conn,
            strategy_id=strat_id,
            label="https://b.example/",
            host="b.example",
            port=5432,
            role="standby_ro",
            notes=None,
            master_host="a.example",
            master_port=5432,
            created_by_user_id=None,
        )

        # 2) prépare une session pending pour confirm_master_v2
        init = await svc.init_master_v2(
            conn,
            standby_url="https://b.example/",
            actor_user_id=None,
        )
        try:
            with pytest.raises(svc_v1.NodeAlreadyExistsError) as exc_info:
                await svc.confirm_master_v2(
                    conn,
                    session_id=init.session_id,
                    token=_token_from_pairing_url(init.pairing_url),
                    standby_url="https://b.example/",
                    actor_user_id=None,
                )
            assert "id" in exc_info.value.existing_node
            assert exc_info.value.existing_node["label"] == "https://b.example/"
        finally:
            await conn.execute("DELETE FROM pairing_session WHERE id = $1", init.session_id)
            await conn.execute("DELETE FROM replication_nodes WHERE strategy_id = $1", strat_id)
            await conn.execute("DELETE FROM replication_strategies WHERE id = $1", strat_id)
            roles = await conn.fetch(
                "SELECT rolname FROM pg_roles WHERE rolname LIKE 'repl_%'"
            )
            for r in roles:
                await conn.execute(f"DROP ROLE IF EXISTS {r['rolname']}")
```

Helper en haut du fichier (à ajouter si pas déjà là) :

```python
def _token_from_pairing_url(pairing_url: str) -> str:
    from urllib.parse import parse_qs, urlparse
    qs = parse_qs(urlparse(pairing_url).query)
    return qs["t"][0]
```

- [ ] **Step 2: Run → rouge attendu**

Run: `cd backend && uv run pytest tests/test_pairing_v2_service.py::test_confirm_master_v2_raises_node_already_exists_on_label_collision -v`
Expected: FAIL — la `UniqueViolationError` brute remonte au lieu de `NodeAlreadyExistsError` (parce que `confirm_master_v2` ne demande pas `force`, mais l'`add_node` modifié au Task 2 doit déjà transformer l'erreur). En fait avec Task 2 le test devrait PASSER directement → c'est OK, ça valide qu'on n'a rien régressé. Si ça passe, on garde tel quel et on passe au Step 3.

- [ ] **Step 3: Test rouge — force=True remplace**

Ajouter :

```python
async def test_confirm_master_v2_with_force_replaces_existing_node(
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    async with real_db_pool.acquire() as conn:
        from app.db.repositories import replication_strategies as strat_repo
        from app.services import streaming_replication as streaming_svc

        strat_id = await strat_repo.create(
            conn,
            env_type="docker_compose",
            config={"compose_file": "/tmp/x.yml"},
            notes="test",
            created_by_user_id=None,
        )
        await strat_repo.set_active(conn, strategy_id=strat_id)
        old_node_id, _ = await streaming_svc.add_node(
            conn,
            strategy_id=strat_id,
            label="https://b.example/",
            host="b.example",
            port=5432,
            role="standby_ro",
            notes=None,
            master_host="a.example",
            master_port=5432,
            created_by_user_id=None,
        )
        init = await svc.init_master_v2(
            conn,
            standby_url="https://b.example/",
            actor_user_id=None,
        )
        try:
            payload = await svc.confirm_master_v2(
                conn,
                session_id=init.session_id,
                token=_token_from_pairing_url(init.pairing_url),
                standby_url="https://b.example/",
                actor_user_id=None,
                force=True,
            )
            assert payload["master_host"]
            assert payload["replication_user"].startswith("repl_")
            # ancien node supprimé
            assert await conn.fetchrow(
                "SELECT id FROM replication_nodes WHERE id = $1", old_node_id
            ) is None
            # nouveau node créé
            new_row = await conn.fetchrow(
                "SELECT id FROM replication_nodes WHERE id = $1::uuid",
                payload["node_id"],
            )
            assert new_row is not None
            # audit log replacement
            audit = await conn.fetchrow(
                "SELECT * FROM audit_log "
                "WHERE action = 'pairing.master_node_replaced' "
                "AND created_at >= now() - interval '1 minute' "
                "ORDER BY created_at DESC LIMIT 1"
            )
            assert audit is not None
        finally:
            await conn.execute("DELETE FROM pairing_session WHERE id = $1", init.session_id)
            await conn.execute("DELETE FROM replication_nodes WHERE strategy_id = $1", strat_id)
            await conn.execute("DELETE FROM replication_strategies WHERE id = $1", strat_id)
            await conn.execute(
                "DELETE FROM audit_log WHERE action IN "
                "('pairing.master_init_v2', 'pairing.master_node_replaced') "
                "AND created_at >= now() - interval '1 minute'"
            )
            roles = await conn.fetch(
                "SELECT rolname FROM pg_roles WHERE rolname LIKE 'repl_%'"
            )
            for r in roles:
                await conn.execute(f"DROP ROLE IF EXISTS {r['rolname']}")
```

- [ ] **Step 4: Run → rouge attendu**

Run: `cd backend && uv run pytest tests/test_pairing_v2_service.py::test_confirm_master_v2_with_force_replaces_existing_node -v`
Expected: FAIL — `confirm_master_v2` n'accepte pas `force` (`TypeError`).

- [ ] **Step 5: Implémenter `force`**

Modifier `confirm_master_v2` dans `backend/app/services/pairing_v2.py` :

```python
async def confirm_master_v2(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    session_id: UUID,
    token: str,
    standby_url: str,
    actor_user_id: UUID | None,
    force: bool = False,
) -> dict[str, Any]:
    """A reçoit l'appel inter-instances du standby : (session_id, token).

    Vérifie que la session est active, que le token correspond, crée le node
    de réplication et stocke le payload pour répondre au standby.

    Si `force=True` et qu'un node existe déjà avec le même label (ou
    application_name), il est supprimé puis recréé. Cette opération est
    auditée séparément (`pairing.master_node_replaced`).
    """
    from app.core.config import settings
    from app.services.pairing import NodeAlreadyExistsError

    sess = await repo.get(conn, session_id)
    if sess is None:
        raise InvalidCodeError("session_not_found")

    new_attempts = await repo.increment_attempts(conn, session_id) or 0
    if new_attempts > settings.pairing_max_attempts:
        async with conn.transaction():
            await repo.set_status(conn, session_id, "failed")
            await audit_log_insert(
                conn,
                "pairing.failed",
                actor_user_id=actor_user_id,
                metadata={"role": "master", "reason": "too_many_attempts_v2"},
            )
        raise TooManyAttemptsError("too_many_attempts")

    if sess["status"] not in ("pending", "confirmed"):
        raise InvalidCodeError("session_not_active")
    if sess["code"] != token:
        raise InvalidCodeError("token_mismatch")

    strategy_row = await strat_repo.get_active_strategy(conn)
    if strategy_row is None:
        raise InvalidPairingPreconditionError("no_active_strategy")

    master_host = urlparse(settings.public_url).hostname
    if not master_host:
        raise InvalidPairingPreconditionError("public_url_missing_hostname")
    master_port = settings.replication_advertised_pg_port

    standby_host = _host_from_url(standby_url)

    try:
        _node_id, bundle = await streaming_svc.add_node(
            conn,
            strategy_id=strategy_row["id"],
            label=standby_url,
            host=standby_host,
            port=5432,
            role="standby_ro",
            notes=f"Créé par appairage v2 avec {standby_url}",
            master_host=master_host,
            master_port=master_port,
            created_by_user_id=actor_user_id,
            replace_existing=force,
        )
    except NodeAlreadyExistsError:
        # Le caller (endpoint) traduit cette exception en 409 avec détails.
        raise

    if force:
        await audit_log_insert(
            conn,
            "pairing.master_node_replaced",
            actor_user_id=actor_user_id,
            metadata={
                "session_id": str(session_id),
                "standby_url": standby_url,
                "new_node_id": str(_node_id),
            },
        )

    payload: dict[str, Any] = {
        "master_host": master_host,
        "master_port": master_port,
        "replication_user": bundle.replication_user,
        "replication_password": bundle.password,
        "application_name": bundle.application_name,
        "node_id": str(_node_id),
    }

    async with conn.transaction():
        await repo.set_payload(conn, session_id, payload)
        await repo.set_status(conn, session_id, "confirmed")

    return payload
```

- [ ] **Step 6: Run tous les tests pairing_v2_service**

Run: `cd backend && uv run pytest tests/test_pairing_v2_service.py -v`
Expected: tous passent.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/pairing_v2.py backend/tests/test_pairing_v2_service.py
git commit -m "feat(pairing): confirm_master_v2 accepte force pour remplacer un node existant"
```

---

## Task 5: `PairingConfirmV2Request.force` + `PairingAcceptV2Request.force`

**Files:**
- Modify: `backend/app/models/api/pairing.py`
- Modify: `backend/tests/test_pairing_schemas.py`

- [ ] **Step 1: Test rouge — schémas**

Ajouter dans `backend/tests/test_pairing_schemas.py` (si fichier existe, sinon créer) :

```python
from app.models.api.pairing import PairingAcceptV2Request, PairingConfirmV2Request


def test_pairing_confirm_v2_request_force_defaults_false() -> None:
    req = PairingConfirmV2Request(
        session_id="00000000-0000-0000-0000-000000000000",
        token="a" * 32,
        standby_url="https://b/",
    )
    assert req.force is False


def test_pairing_confirm_v2_request_force_true_accepted() -> None:
    req = PairingConfirmV2Request(
        session_id="00000000-0000-0000-0000-000000000000",
        token="a" * 32,
        standby_url="https://b/",
        force=True,
    )
    assert req.force is True


def test_pairing_accept_v2_request_force_defaults_false() -> None:
    req = PairingAcceptV2Request(pairing_url="https://a/pair?sid=x&t=y")
    assert req.force is False
```

- [ ] **Step 2: Run → rouge attendu**

Run: `cd backend && uv run pytest tests/test_pairing_schemas.py -k force -v`
Expected: FAIL — `force` n'existe pas comme champ.

- [ ] **Step 3: Ajouter `force` aux deux modèles**

Dans `backend/app/models/api/pairing.py` :

```python
class PairingAcceptV2Request(BaseModel):
    """B colle l'URL d'appairage reçue de A."""

    pairing_url: str = Field(..., min_length=1)
    force: bool = False


class PairingConfirmV2Request(BaseModel):
    """B → A : confirme avec session_id + token extraits de l'URL d'appairage."""

    session_id: UUID
    token: str
    standby_url: str = Field(..., min_length=1)
    force: bool = False

    @field_validator("token")
    @classmethod
    def _check_token(cls, v: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{32}", v):
            raise ValueError("token_must_be_32_hex_chars")
        return v
```

- [ ] **Step 4: Run → vert attendu**

Run: `cd backend && uv run pytest tests/test_pairing_schemas.py -k force -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/api/pairing.py backend/tests/test_pairing_schemas.py
git commit -m "feat(pairing): champs force sur PairingConfirmV2Request et PairingAcceptV2Request"
```

---

## Task 6: Endpoint `/confirm-v2` → 409 `node_already_exists` + force

**Files:**
- Modify: `backend/app/api/v1/admin_replication_pairing.py:178-219`
- Modify: `backend/tests/test_pairing_api_v2.py`

- [ ] **Step 1: Test rouge — 409**

Ajouter dans `backend/tests/test_pairing_api_v2.py` :

```python
async def test_confirm_v2_endpoint_returns_409_when_node_label_exists(
    api_client_master_with_active_strategy,
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    """Reproduit le bug du LOT 5 fix : un standby déjà connu ne doit plus 500."""
    client, _strat_id, _admin_jwt = api_client_master_with_active_strategy
    # initialiser une session côté master
    init_resp = await client.post(
        "/v1/admin/replication/pairing/init-v2",
        json={"standby_url": "https://b.example/"},
    )
    assert init_resp.status_code == 200
    sid = init_resp.json()["session_id"]
    token = _token_from_pairing_url(init_resp.json()["pairing_url"])

    # créer un node "fantôme" en DB pour reproduire la collision
    async with real_db_pool.acquire() as conn:
        from app.services import streaming_replication as streaming_svc
        from app.db.repositories import replication_strategies as strat_repo
        strat = await strat_repo.get_active_strategy(conn)
        assert strat is not None
        await streaming_svc.add_node(
            conn,
            strategy_id=strat["id"],
            label="https://b.example/",
            host="b.example",
            port=5432,
            role="standby_ro",
            notes=None,
            master_host="a.example",
            master_port=5432,
            created_by_user_id=None,
        )

    # confirm-v2 sans force → 409 node_already_exists
    resp = await client.post(
        "/v1/admin/replication/pairing/confirm-v2",
        json={"session_id": sid, "token": token, "standby_url": "https://b.example/"},
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["detail"]["error"] == "node_already_exists"
    assert "existing_node" in body["detail"]
    assert body["detail"]["existing_node"]["label"] == "https://b.example/"
```

Le fixture `api_client_master_with_active_strategy` doit déjà exister dans `conftest.py` (sinon, le créer en s'inspirant des autres fixtures de `test_pairing_api_v2.py`). **Vérifier d'abord son existence** :

Run: `cd backend && grep -rn "api_client_master_with_active_strategy" tests/ src/`

Si absent : créer dans `tests/conftest.py` un fixture qui retourne (client TestClient, strategy_id, admin_jwt) — voir le pattern dans `test_pairing_api_v2.py` ligne ~1-50.

- [ ] **Step 2: Run → rouge attendu**

Run: `cd backend && uv run pytest tests/test_pairing_api_v2.py::test_confirm_v2_endpoint_returns_409_when_node_label_exists -v`
Expected: FAIL — actuellement 500 brut.

- [ ] **Step 3: Ajouter le handler 409 dans l'endpoint**

Dans `backend/app/api/v1/admin_replication_pairing.py`, fonction `confirm_pairing_v2` (ligne ~183), modifier :

```python
@router.post(
    "/confirm-v2",
    response_model=PairingConfirmResponse,
    status_code=status.HTTP_200_OK,
)
async def confirm_pairing_v2(req: PairingConfirmV2Request) -> PairingConfirmResponse:
    """B → A : confirmation inter-instances avec (session_id, token).

    Authentification = token aléatoire 128 bits + TTL court (pas de JWT, pour
    les mêmes raisons que l'endpoint /confirm v1).
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            payload = await svc_v2.confirm_master_v2(
                conn,
                session_id=req.session_id,
                token=req.token,
                standby_url=req.standby_url,
                actor_user_id=None,
                force=req.force,
            )
        except svc.NodeAlreadyExistsError as e:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "node_already_exists",
                    "existing_node": e.existing_node,
                },
            ) from e
        except svc.InvalidCodeError:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "invalid_or_expired_token"},
            ) from None
        except svc.TooManyAttemptsError:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"error": "too_many_attempts"},
            ) from None
        except svc.InvalidPairingPreconditionError as e:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": "invalid_pairing_precondition", "cause": str(e)},
            ) from e
        except svc.PairingAcceptError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "pairing_accept_error", "cause": str(e)},
            ) from e
    return PairingConfirmResponse(**payload)
```

L'ordre du `except` importe : `NodeAlreadyExistsError` AVANT `InvalidPairingPreconditionError` (héritage).

- [ ] **Step 4: Test vert pour 409**

Run: `cd backend && uv run pytest tests/test_pairing_api_v2.py::test_confirm_v2_endpoint_returns_409_when_node_label_exists -v`
Expected: PASS.

- [ ] **Step 5: Test 200 avec force=True**

Ajouter :

```python
async def test_confirm_v2_endpoint_replaces_when_force_true(
    api_client_master_with_active_strategy,
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    client, _strat_id, _admin_jwt = api_client_master_with_active_strategy
    init_resp = await client.post(
        "/v1/admin/replication/pairing/init-v2",
        json={"standby_url": "https://b.example/"},
    )
    sid = init_resp.json()["session_id"]
    token = _token_from_pairing_url(init_resp.json()["pairing_url"])

    async with real_db_pool.acquire() as conn:
        from app.services import streaming_replication as streaming_svc
        from app.db.repositories import replication_strategies as strat_repo
        strat = await strat_repo.get_active_strategy(conn)
        assert strat is not None
        await streaming_svc.add_node(
            conn,
            strategy_id=strat["id"],
            label="https://b.example/",
            host="b.example",
            port=5432,
            role="standby_ro",
            notes=None,
            master_host="a.example",
            master_port=5432,
            created_by_user_id=None,
        )

    resp = await client.post(
        "/v1/admin/replication/pairing/confirm-v2",
        json={
            "session_id": sid,
            "token": token,
            "standby_url": "https://b.example/",
            "force": True,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["master_host"]
    assert body["replication_user"].startswith("repl_")
```

- [ ] **Step 6: Run tous les tests pairing_api_v2**

Run: `cd backend && uv run pytest tests/test_pairing_api_v2.py -v`
Expected: tous passent.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/v1/admin_replication_pairing.py backend/tests/test_pairing_api_v2.py
git commit -m "feat(pairing): /confirm-v2 retourne 409 node_already_exists + accepte force"
```

---

## Task 7: `accept_standby_v2` propage `force` + exception côté standby

**Files:**
- Modify: `backend/app/services/pairing_v2.py` (fonction `accept_standby_v2`, ligne ~217)
- Modify: `backend/tests/test_pairing_v2_service.py`

- [ ] **Step 1: Test rouge — accept transmet force**

Ajouter :

```python
async def test_accept_standby_v2_transmits_force_to_master(
    monkeypatch: pytest.MonkeyPatch,
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    """`force=True` doit apparaître dans le body POST vers /confirm-v2."""
    from uuid import uuid4

    captured: dict[str, object] = {}

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json = MagicMock(return_value={
        "master_host": "a", "master_port": 5432,
        "replication_user": "repl_x", "replication_password": "p",
        "application_name": "x", "node_id": str(uuid4()),
    })
    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None

    async def fake_post(url: str, json: dict[str, object]) -> MagicMock:
        captured["url"] = url
        captured["body"] = json
        return fake_resp

    fake_client.post = fake_post
    monkeypatch.setattr(svc.httpx, "AsyncClient", lambda *a, **kw: fake_client)

    url = build_pairing_url("https://a.example", uuid4(), "a" * 32)
    async with real_db_pool.acquire() as conn:
        await svc.accept_standby_v2(
            conn,
            pairing_url=url,
            self_url="https://b/",
            actor_user_id=None,
            force=True,
        )
    assert captured["body"]["force"] is True
```

- [ ] **Step 2: Test rouge — accept transforme 409 en NodeAlreadyExistsError**

Ajouter :

```python
async def test_accept_standby_v2_propagates_409_as_node_already_exists(
    monkeypatch: pytest.MonkeyPatch,
    real_db_pool: asyncpg.Pool[asyncpg.Record],
) -> None:
    from uuid import uuid4

    fake_resp = MagicMock()
    fake_resp.status_code = 409
    fake_resp.json = MagicMock(return_value={
        "detail": {
            "error": "node_already_exists",
            "existing_node": {
                "id": str(uuid4()),
                "label": "https://b/",
                "host": "b",
                "application_name": "b",
                "last_state": "disconnected",
                "last_seen_at": "2026-05-10T12:00:00+00:00",
            },
        },
    })
    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None
    fake_client.post = AsyncMock(return_value=fake_resp)
    monkeypatch.setattr(svc.httpx, "AsyncClient", lambda *a, **kw: fake_client)

    url = build_pairing_url("https://a.example", uuid4(), "a" * 32)
    async with real_db_pool.acquire() as conn:
        with pytest.raises(svc_v1.NodeAlreadyExistsError) as exc_info:
            await svc.accept_standby_v2(
                conn,
                pairing_url=url,
                self_url="https://b/",
                actor_user_id=None,
            )
        assert exc_info.value.existing_node["host"] == "b"
        assert exc_info.value.existing_node["last_state"] == "disconnected"
```

- [ ] **Step 3: Run → rouge attendu**

Run: `cd backend && uv run pytest tests/test_pairing_v2_service.py -k "force or already_exists" -v`
Expected: FAIL — `accept_standby_v2` n'accepte pas `force` et ne parse pas le 409.

- [ ] **Step 4: Implémenter `force` + parsing du 409**

Dans `backend/app/services/pairing_v2.py`, modifier `accept_standby_v2` :

```python
async def accept_standby_v2(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    pairing_url: str,
    self_url: str,
    actor_user_id: UUID | None,
    force: bool = False,
) -> UUID:
    """B parse l'URL d'appairage collée → contacte A → stocke payload local.

    Le master_url est dérivé de l'URL d'appairage. La session locale role=standby
    est créée avec status=wizard et payload prêt à être consommé par
    PairingWizardPage.

    `force=True` est transmis au master pour autoriser le remplacement d'un
    node de réplication déjà enregistré pour la même URL standby.

    Raises InvalidPairingUrlError si l'URL n'a pas le bon format.
    Raises InvalidCodeError si A répond 401/403 (session inconnue/token KO).
    Raises TooManyAttemptsError si A répond 429.
    Raises NodeAlreadyExistsError si A répond 409 avec error=node_already_exists.
    Raises PairingAcceptError en cas d'erreur réseau ou autre HTTP.
    """
    from app.core.config import settings
    from app.services.pairing import NodeAlreadyExistsError

    parsed = parse_pairing_url(pairing_url)
    confirm_url = parsed.master_url + "/v1/admin/replication/pairing/confirm-v2"
    body = {
        "session_id": str(parsed.session_id),
        "token": parsed.token,
        "standby_url": self_url,
        "force": force,
    }
    verify_tls = not settings.replication_insecure_skip_tls_verify
    if not verify_tls:
        logger.warning(
            "pairing_v2.tls_verification_disabled",
            master_url=parsed.master_url,
            session_id=str(parsed.session_id),
        )
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=verify_tls) as client:
            resp = await client.post(confirm_url, json=body)
    except httpx.HTTPError as e:
        logger.error(
            "pairing_v2.confirm_call_failed",
            master_url=parsed.master_url,
            confirm_url=confirm_url,
            error_type=type(e).__name__,
            error=str(e),
            verify_tls=verify_tls,
        )
        raise PairingAcceptError(f"network_error:{type(e).__name__}:{e}") from e

    if resp.status_code in (401, 403):
        raise InvalidCodeError("invalid_or_expired_token")
    if resp.status_code == 429:
        raise TooManyAttemptsError("too_many_attempts")
    if resp.status_code == 409:
        body_json = resp.json()
        detail = body_json.get("detail") if isinstance(body_json, dict) else None
        if (
            isinstance(detail, dict)
            and detail.get("error") == "node_already_exists"
            and isinstance(detail.get("existing_node"), dict)
        ):
            raise NodeAlreadyExistsError(detail["existing_node"])
        raise PairingAcceptError(f"unexpected_409:{body_json}")
    if resp.status_code != 200:
        raise PairingAcceptError(f"unexpected_status:{resp.status_code}")

    payload = resp.json()

    async with conn.transaction():
        sid = await repo.create(
            conn,
            role="standby",
            code=parsed.token,
            partner_url=parsed.master_url,
            ttl_seconds=settings.pairing_code_ttl_seconds,
            actor_user_id=actor_user_id,
        )
        await repo.set_payload(conn, sid, payload)
        await repo.set_status(conn, sid, "wizard")
        await audit_log_insert(
            conn,
            "pairing.standby_accepted_v2",
            actor_user_id=actor_user_id,
            metadata={
                "master_url": parsed.master_url,
                "session_id": str(sid),
                "force": force,
            },
        )

    return sid
```

- [ ] **Step 5: Run → vert attendu**

Run: `cd backend && uv run pytest tests/test_pairing_v2_service.py -v`
Expected: tous passent.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/pairing_v2.py backend/tests/test_pairing_v2_service.py
git commit -m "feat(pairing): accept_standby_v2 propage force + transforme 409 master en NodeAlreadyExistsError"
```

---

## Task 8: Endpoint `/accept-v2` → 409 transparent

**Files:**
- Modify: `backend/app/api/v1/admin_replication_pairing.py:222-263`
- Modify: `backend/tests/test_pairing_api_v2.py`

- [ ] **Step 1: Test rouge — accept-v2 retourne 409 quand master rejette**

Ajouter dans `backend/tests/test_pairing_api_v2.py`. Le test doit mocker l'appel HTTP master → la classe `httpx.AsyncClient` utilisée dans `accept_standby_v2`. Pattern à reprendre des tests `test_accept_standby_v2_*` existants.

```python
async def test_accept_v2_endpoint_returns_409_when_master_node_exists(
    monkeypatch: pytest.MonkeyPatch,
    api_client_standby_admin,
) -> None:
    from uuid import uuid4
    from unittest.mock import AsyncMock, MagicMock
    from app.services import pairing_v2 as svc_v2_mod

    fake_resp = MagicMock()
    fake_resp.status_code = 409
    fake_resp.json = MagicMock(return_value={
        "detail": {
            "error": "node_already_exists",
            "existing_node": {
                "id": str(uuid4()),
                "label": "https://b.example/",
                "host": "b.example",
                "application_name": "b_example",
                "last_state": "disconnected",
                "last_seen_at": None,
            },
        },
    })
    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None
    fake_client.post = AsyncMock(return_value=fake_resp)
    monkeypatch.setattr(svc_v2_mod.httpx, "AsyncClient", lambda *a, **kw: fake_client)

    client, _admin_jwt = api_client_standby_admin
    pairing_url = "https://a.example/pair?sid=" + str(uuid4()) + "&t=" + ("a" * 32)
    resp = await client.post(
        "/v1/admin/replication/pairing/accept-v2",
        json={"pairing_url": pairing_url},
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["detail"]["error"] == "node_already_exists"
    assert body["detail"]["existing_node"]["host"] == "b.example"
```

Si le fixture `api_client_standby_admin` n'existe pas, le créer dans `conftest.py` ou en local (pattern de la TestClient avec un AdminJwt mocké).

- [ ] **Step 2: Run → rouge attendu**

Run: `cd backend && uv run pytest tests/test_pairing_api_v2.py::test_accept_v2_endpoint_returns_409_when_master_node_exists -v`
Expected: FAIL — actuellement 502 (`NodeAlreadyExistsError` est sous-classe de `InvalidPairingPreconditionError` mais cet except n'est pas listé dans `accept_pairing_v2` ; en fait actuellement la fonction `accept_standby_v2` ne sait même pas parser le 409, donc lève `PairingAcceptError` → 502).

- [ ] **Step 3: Ajouter le handler 409 dans `accept_pairing_v2`**

Dans `backend/app/api/v1/admin_replication_pairing.py`, modifier la fonction `accept_pairing_v2` (ligne ~227) :

```python
@router.post(
    "/accept-v2",
    response_model=PairingAcceptResponse,
    status_code=status.HTTP_200_OK,
)
async def accept_pairing_v2(
    req: PairingAcceptV2Request,
    admin: AdminJwt,
) -> PairingAcceptResponse:
    """B colle l'URL d'appairage reçue de A → contact A et démarre le wizard."""
    from app.core.config import settings

    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            sid = await svc_v2.accept_standby_v2(
                conn,
                pairing_url=req.pairing_url,
                self_url=settings.public_url,
                actor_user_id=admin.user_id,
                force=req.force,
            )
        except InvalidPairingUrlError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "invalid_pairing_url", "cause": str(e)},
            ) from e
        except svc.NodeAlreadyExistsError as e:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "node_already_exists",
                    "existing_node": e.existing_node,
                },
            ) from e
        except svc.InvalidCodeError:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "invalid_or_expired_token"},
            ) from None
        except svc.TooManyAttemptsError:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"error": "too_many_attempts"},
            ) from None
        except svc.PairingAcceptError as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"error": "pairing_accept_error", "cause": str(e)},
            ) from e
    return PairingAcceptResponse(session_id=sid)
```

L'import `from app.services import pairing as svc` est déjà en tête de fichier (alias `svc`), donc `svc.NodeAlreadyExistsError` fonctionne.

- [ ] **Step 4: Run → vert attendu**

Run: `cd backend && uv run pytest tests/test_pairing_api_v2.py -v`
Expected: tous passent.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/admin_replication_pairing.py backend/tests/test_pairing_api_v2.py
git commit -m "feat(pairing): /accept-v2 retourne 409 transparent + propage force au master"
```

---

## Task 9: Frontend — `ApiError` porte un champ `detail`

**Files:**
- Modify: `frontend/src/lib/api-client.ts:9-34, 92-119`
- Test: `frontend/src/tests/apiClientError.test.ts` (créer)

- [ ] **Step 1: Test rouge**

Créer `frontend/src/tests/apiClientError.test.ts` :

```typescript
import { describe, it, expect, vi, afterEach } from "vitest";
import { api, ApiError } from "@/lib/api-client";

describe("ApiError", () => {
  afterEach(() => vi.restoreAllMocks());

  it("expose le payload detail structuré sur erreur HTTP", async () => {
    const fakeBody = {
      detail: {
        error: "node_already_exists",
        existing_node: { id: "abc", label: "https://b/", host: "b" },
      },
    };
    vi.spyOn(global, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(fakeBody), {
        status: 409,
        headers: { "Content-Type": "application/json" },
      }),
    );
    try {
      await api.post("/whatever", {});
      throw new Error("should have thrown");
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      const err = e as ApiError;
      expect(err.status).toBe(409);
      expect(err.code).toBe("node_already_exists");
      expect(err.detail).toEqual(fakeBody.detail);
    }
  });
});
```

- [ ] **Step 2: Run → rouge attendu**

Run: `cd frontend && npx vitest run src/tests/apiClientError.test.ts`
Expected: FAIL — `ApiError.detail` n'existe pas.

- [ ] **Step 3: Implémenter**

Dans `frontend/src/lib/api-client.ts`, modifier la classe `ApiError` :

```typescript
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly detail: unknown = null,
  ) {
    super(message);
    this.name = "ApiError";
  }

  get isFirstLogin(): boolean {
    return this.code === "first_login";
  }

  get isUnauthorized(): boolean {
    return this.status === 401;
  }

  get isForbidden(): boolean {
    return this.status === 403;
  }

  get isNotFound(): boolean {
    return this.status === 404;
  }
}
```

Et dans le bloc qui throw (ligne ~119), passer `detail` :

```typescript
    throw new ApiError(response.status, code, msg, detail ?? null);
```

- [ ] **Step 4: Run → vert attendu**

Run: `cd frontend && npx vitest run src/tests/apiClientError.test.ts`
Expected: PASS.

- [ ] **Step 5: TypeScript strict**

Run: `cd frontend && npx tsc --noEmit`
Expected: pas d'erreur.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/api-client.ts frontend/src/tests/apiClientError.test.ts
git commit -m "feat(frontend): ApiError porte le payload detail brut pour les codes 4xx structurés"
```

---

## Task 10: Frontend — `acceptPairingV2(pairingUrl, force?)`

**Files:**
- Modify: `frontend/src/lib/adminApi.ts:590-597`
- Test: `frontend/src/tests/adminApiPairing.test.ts` (créer)

- [ ] **Step 1: Test rouge**

Créer `frontend/src/tests/adminApiPairing.test.ts` :

```typescript
import { describe, it, expect, vi, afterEach } from "vitest";
import { acceptPairingV2 } from "@/lib/adminApi";

describe("acceptPairingV2", () => {
  afterEach(() => vi.restoreAllMocks());

  it("envoie force=false par défaut", async () => {
    let capturedBody: unknown = null;
    vi.spyOn(global, "fetch").mockImplementation(
      async (_url, init) => {
        capturedBody = JSON.parse(String((init as RequestInit).body));
        return new Response(JSON.stringify({ session_id: "00000000-0000-0000-0000-000000000000" }), {
          status: 200, headers: { "Content-Type": "application/json" },
        });
      },
    );
    await acceptPairingV2("https://a/pair?sid=x&t=y");
    expect(capturedBody).toMatchObject({ pairing_url: "https://a/pair?sid=x&t=y", force: false });
  });

  it("envoie force=true quand demandé", async () => {
    let capturedBody: unknown = null;
    vi.spyOn(global, "fetch").mockImplementation(
      async (_url, init) => {
        capturedBody = JSON.parse(String((init as RequestInit).body));
        return new Response(JSON.stringify({ session_id: "00000000-0000-0000-0000-000000000000" }), {
          status: 200, headers: { "Content-Type": "application/json" },
        });
      },
    );
    await acceptPairingV2("https://a/pair?sid=x&t=y", true);
    expect(capturedBody).toMatchObject({ force: true });
  });
});
```

- [ ] **Step 2: Run → rouge attendu**

Run: `cd frontend && npx vitest run src/tests/adminApiPairing.test.ts`
Expected: FAIL — `acceptPairingV2` n'envoie pas `force`.

- [ ] **Step 3: Implémenter**

Dans `frontend/src/lib/adminApi.ts`, remplacer :

```typescript
export async function acceptPairingV2(
  pairingUrl: string,
  force: boolean = false,
): Promise<PairingAcceptResponse> {
  const raw = await api.post<unknown>("/admin/replication/pairing/accept-v2", {
    pairing_url: pairingUrl,
    force,
  });
  return PairingAcceptResponseSchema.parse(raw);
}
```

- [ ] **Step 4: Run → vert attendu**

Run: `cd frontend && npx vitest run src/tests/adminApiPairing.test.ts`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/adminApi.ts frontend/src/tests/adminApiPairing.test.ts
git commit -m "feat(frontend): acceptPairingV2 accepte un flag force pour remplacer un node existant"
```

---

## Task 11: Frontend — schéma `ExistingNode` et libellés i18n

**Files:**
- Modify: `frontend/src/schemas/pairing.ts`
- Modify: `frontend/src/i18n/fr.json`
- Modify: `frontend/src/i18n/en.json`

- [ ] **Step 1: Ajouter le schéma Zod `ExistingNode`**

Dans `frontend/src/schemas/pairing.ts`, ajouter :

```typescript
export const ExistingNodeSchema = z.object({
  id: z.string().uuid(),
  label: z.string(),
  host: z.string(),
  application_name: z.string(),
  last_state: z.enum(["streaming", "catchup", "disconnected", "unknown"]).nullable(),
  last_seen_at: z.string().nullable(),
});
export type ExistingNode = z.infer<typeof ExistingNodeSchema>;
```

- [ ] **Step 2: Libellés i18n FR**

Dans `frontend/src/i18n/fr.json`, sous la clé `admin.replication.pairing.becomeStandby`, ajouter :

```json
"replaceModal": {
  "title": "Un node existe déjà côté master",
  "intro": "Un node de réplication portant cette URL est déjà enregistré sur le master. Le remplacer supprimera l'ancien rôle Postgres et créera un nouveau bundle de credentials.",
  "existingLabel": "URL :",
  "existingHost": "Hôte :",
  "existingAppName": "Application name :",
  "existingState": "Dernier état :",
  "existingSeen": "Vu pour la dernière fois :",
  "neverSeen": "jamais",
  "cancel": "Annuler",
  "replace": "Remplacer le node"
}
```

- [ ] **Step 3: Libellés i18n EN**

Dans `frontend/src/i18n/en.json`, idem sous `admin.replication.pairing.becomeStandby` :

```json
"replaceModal": {
  "title": "A node already exists on the master",
  "intro": "A replication node with this URL is already registered on the master. Replacing it will drop the existing Postgres role and issue a fresh credentials bundle.",
  "existingLabel": "URL:",
  "existingHost": "Host:",
  "existingAppName": "Application name:",
  "existingState": "Last state:",
  "existingSeen": "Last seen:",
  "neverSeen": "never",
  "cancel": "Cancel",
  "replace": "Replace node"
}
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/schemas/pairing.ts frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(frontend): schéma ExistingNode + libellés modale replaceNode fr/en"
```

---

## Task 12: Frontend — composant `ConfirmReplaceNodeModal`

**Files:**
- Create: `frontend/src/components/ConfirmReplaceNodeModal.tsx`
- Create: `frontend/src/tests/confirmReplaceNodeModal.test.tsx`

- [ ] **Step 1: Test rouge**

Créer `frontend/src/tests/confirmReplaceNodeModal.test.tsx` :

```typescript
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { I18nextProvider } from "react-i18next";
import i18n from "@/lib/i18n";

import { ConfirmReplaceNodeModal } from "@/components/ConfirmReplaceNodeModal";
import type { ExistingNode } from "@/schemas/pairing";

const NODE: ExistingNode = {
  id: "11111111-1111-1111-1111-111111111111",
  label: "https://b.example/",
  host: "b.example",
  application_name: "b_example",
  last_state: "disconnected",
  last_seen_at: "2026-05-10T12:00:00+00:00",
};

function renderModal(opened: boolean, onConfirm = vi.fn(), onCancel = vi.fn()) {
  return render(
    <MantineProvider>
      <I18nextProvider i18n={i18n}>
        <ConfirmReplaceNodeModal
          opened={opened}
          existingNode={NODE}
          onConfirm={onConfirm}
          onCancel={onCancel}
          loading={false}
        />
      </I18nextProvider>
    </MantineProvider>,
  );
}

describe("ConfirmReplaceNodeModal", () => {
  it("affiche les détails du node existant", () => {
    renderModal(true);
    expect(screen.getByText(/https:\/\/b\.example\//)).toBeInTheDocument();
    expect(screen.getByText(/b\.example/)).toBeInTheDocument();
    expect(screen.getByText(/disconnected/)).toBeInTheDocument();
  });

  it("appelle onConfirm quand on clique Remplacer", () => {
    const onConfirm = vi.fn();
    renderModal(true, onConfirm);
    fireEvent.click(screen.getByRole("button", { name: /remplacer/i }));
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it("appelle onCancel quand on clique Annuler", () => {
    const onCancel = vi.fn();
    renderModal(true, vi.fn(), onCancel);
    fireEvent.click(screen.getByRole("button", { name: /annuler/i }));
    expect(onCancel).toHaveBeenCalledOnce();
  });
});
```

- [ ] **Step 2: Run → rouge attendu**

Run: `cd frontend && npx vitest run src/tests/confirmReplaceNodeModal.test.tsx`
Expected: FAIL — composant n'existe pas.

- [ ] **Step 3: Créer le composant**

Créer `frontend/src/components/ConfirmReplaceNodeModal.tsx` :

```tsx
/**
 * Modale Mantine — confirmation de remplacement d'un node de réplication
 * existant côté master lors d'un nouveau pairing v2.
 *
 * Affichée par BecomeStandbyPage quand l'API renvoie 409 node_already_exists.
 * Sur confirmation, le caller relance accept-v2 avec force=true.
 */
import {
  Alert,
  Button,
  Group,
  Modal,
  Stack,
  Table,
  Text,
} from "@mantine/core";
import { useTranslation } from "react-i18next";

import type { ExistingNode } from "@/schemas/pairing";

interface Props {
  opened: boolean;
  existingNode: ExistingNode;
  onConfirm: () => void;
  onCancel: () => void;
  loading: boolean;
}

export function ConfirmReplaceNodeModal({
  opened,
  existingNode,
  onConfirm,
  onCancel,
  loading,
}: Props) {
  const { t } = useTranslation();
  const lastSeen = existingNode.last_seen_at
    ? new Date(existingNode.last_seen_at).toLocaleString()
    : t("admin.replication.pairing.becomeStandby.replaceModal.neverSeen");
  return (
    <Modal
      opened={opened}
      onClose={onCancel}
      title={t("admin.replication.pairing.becomeStandby.replaceModal.title")}
      size="lg"
      closeOnClickOutside={false}
    >
      <Stack>
        <Alert color="yellow">
          {t("admin.replication.pairing.becomeStandby.replaceModal.intro")}
        </Alert>
        <Table withTableBorder withColumnBorders>
          <Table.Tbody>
            <Table.Tr>
              <Table.Td>
                {t("admin.replication.pairing.becomeStandby.replaceModal.existingLabel")}
              </Table.Td>
              <Table.Td>
                <Text size="sm" ff="monospace">{existingNode.label}</Text>
              </Table.Td>
            </Table.Tr>
            <Table.Tr>
              <Table.Td>
                {t("admin.replication.pairing.becomeStandby.replaceModal.existingHost")}
              </Table.Td>
              <Table.Td>{existingNode.host}</Table.Td>
            </Table.Tr>
            <Table.Tr>
              <Table.Td>
                {t("admin.replication.pairing.becomeStandby.replaceModal.existingAppName")}
              </Table.Td>
              <Table.Td>{existingNode.application_name}</Table.Td>
            </Table.Tr>
            <Table.Tr>
              <Table.Td>
                {t("admin.replication.pairing.becomeStandby.replaceModal.existingState")}
              </Table.Td>
              <Table.Td>{existingNode.last_state ?? "unknown"}</Table.Td>
            </Table.Tr>
            <Table.Tr>
              <Table.Td>
                {t("admin.replication.pairing.becomeStandby.replaceModal.existingSeen")}
              </Table.Td>
              <Table.Td>{lastSeen}</Table.Td>
            </Table.Tr>
          </Table.Tbody>
        </Table>
        <Group justify="flex-end">
          <Button variant="default" onClick={onCancel} disabled={loading}>
            {t("admin.replication.pairing.becomeStandby.replaceModal.cancel")}
          </Button>
          <Button color="red" loading={loading} onClick={onConfirm}>
            {t("admin.replication.pairing.becomeStandby.replaceModal.replace")}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
```

- [ ] **Step 4: Run → vert attendu**

Run: `cd frontend && npx vitest run src/tests/confirmReplaceNodeModal.test.tsx`
Expected: PASS.

- [ ] **Step 5: TS strict**

Run: `cd frontend && npx tsc --noEmit`

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ConfirmReplaceNodeModal.tsx frontend/src/tests/confirmReplaceNodeModal.test.tsx
git commit -m "feat(frontend): composant ConfirmReplaceNodeModal pour le pairing v2"
```

---

## Task 13: Frontend — `BecomeStandbyPage` gère le 409 et déclenche le retry

**Files:**
- Modify: `frontend/src/pages/BecomeStandbyPage.tsx`
- Create: `frontend/src/tests/becomeStandbyPageReplaceFlow.test.tsx`

- [ ] **Step 1: Test rouge — flow complet**

Créer `frontend/src/tests/becomeStandbyPageReplaceFlow.test.tsx` :

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { I18nextProvider } from "react-i18next";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import i18n from "@/lib/i18n";
import { BecomeStandbyPage } from "@/pages/BecomeStandbyPage";
import * as adminApi from "@/lib/adminApi";
import { ApiError } from "@/lib/api-client";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <Notifications />
        <I18nextProvider i18n={i18n}>
          <MemoryRouter initialEntries={["/admin/replication/become-standby"]}>
            <Routes>
              <Route path="/admin/replication/become-standby" element={<BecomeStandbyPage />} />
              <Route path="/admin/pairing/:sid" element={<div>WizardPage</div>} />
            </Routes>
          </MemoryRouter>
        </I18nextProvider>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

describe("BecomeStandbyPage replace flow", () => {
  beforeEach(() => vi.restoreAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("affiche la modale puis relance avec force=true sur 409 node_already_exists", async () => {
    const acceptSpy = vi.spyOn(adminApi, "acceptPairingV2");
    acceptSpy.mockRejectedValueOnce(
      new ApiError(409, "node_already_exists", "node_already_exists", {
        error: "node_already_exists",
        existing_node: {
          id: "11111111-1111-1111-1111-111111111111",
          label: "https://b/",
          host: "b",
          application_name: "b",
          last_state: "disconnected",
          last_seen_at: null,
        },
      }),
    );
    acceptSpy.mockResolvedValueOnce({
      session_id: "22222222-2222-2222-2222-222222222222",
    });

    renderPage();

    const input = screen.getByPlaceholderText(/harpo-1/i);
    fireEvent.change(input, { target: { value: "https://a/pair?sid=x&t=y" } });
    fireEvent.click(screen.getByRole("button", { name: /confirmer|submit|associer/i }));

    await screen.findByText(/node existe déjà|already exists/i);

    expect(acceptSpy).toHaveBeenCalledWith("https://a/pair?sid=x&t=y");

    fireEvent.click(screen.getByRole("button", { name: /remplacer|replace/i }));

    await waitFor(() => {
      expect(screen.getByText(/WizardPage/)).toBeInTheDocument();
    });
    expect(acceptSpy).toHaveBeenCalledWith("https://a/pair?sid=x&t=y", true);
  });
});
```

- [ ] **Step 2: Run → rouge attendu**

Run: `cd frontend && npx vitest run src/tests/becomeStandbyPageReplaceFlow.test.tsx`
Expected: FAIL — la page ne gère pas le 409 et ne propose pas la modale.

- [ ] **Step 3: Implémenter le flow dans la page**

Modifier `frontend/src/pages/BecomeStandbyPage.tsx` :

```tsx
/**
 * Page côté standby (B) — saisie d'une URL d'appairage (v2, LOT 5).
 *
 * L'admin colle l'URL générée par le master. Le backend extrait master_url +
 * session_id + token, contacte le master pour récupérer les creds de
 * réplication, puis redirige vers PairingWizardPage qui guide l'exécution
 * des commandes SSH.
 *
 * Si le master refuse en 409 node_already_exists, on affiche
 * ConfirmReplaceNodeModal pour relancer avec force=true.
 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import {
  Stack,
  Title,
  Text,
  TextInput,
  Group,
  Button,
  Card,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useTranslation } from "react-i18next";

import { acceptPairingV2 } from "@/lib/adminApi";
import { ApiError } from "@/lib/api-client";
import { ConfirmReplaceNodeModal } from "@/components/ConfirmReplaceNodeModal";
import { ExistingNodeSchema, type ExistingNode } from "@/schemas/pairing";

export function BecomeStandbyPage() {
  const { t } = useTranslation();
  const nav = useNavigate();
  const [pairingUrl, setPairingUrl] = useState("");
  const [existing, setExisting] = useState<ExistingNode | null>(null);

  const submitMut = useMutation({
    mutationFn: (force: boolean) => acceptPairingV2(pairingUrl.trim(), force),
    onSuccess: (r) => {
      setExisting(null);
      nav(`/admin/pairing/${r.session_id}`);
    },
    onError: (e) => {
      if (
        e instanceof ApiError
        && e.status === 409
        && e.code === "node_already_exists"
        && e.detail
        && typeof e.detail === "object"
        && "existing_node" in (e.detail as Record<string, unknown>)
      ) {
        const parsed = ExistingNodeSchema.safeParse(
          (e.detail as { existing_node: unknown }).existing_node,
        );
        if (parsed.success) {
          setExisting(parsed.data);
          return;
        }
      }
      notifications.show({
        color: "red",
        title: t("common.error"),
        message: e instanceof ApiError ? e.message : String(e),
      });
    },
  });

  return (
    <Stack maw={600} mx="auto" mt="xl">
      <Title order={2}>
        {t("admin.replication.pairing.becomeStandby.title")}
      </Title>
      <Text c="dimmed">
        {t("admin.replication.pairing.becomeStandby.subtitle")}
      </Text>
      <Card withBorder>
        <Stack>
          <TextInput
            label={t("admin.replication.pairing.becomeStandby.pairingUrl")}
            description={t(
              "admin.replication.pairing.becomeStandby.pairingUrlHint",
            )}
            placeholder="https://harpo-1.example/pair?sid=...&t=..."
            value={pairingUrl}
            onChange={(e) => setPairingUrl(e.currentTarget.value)}
          />
          <Group justify="flex-end">
            <Button
              loading={submitMut.isPending}
              disabled={!pairingUrl.trim()}
              onClick={() => submitMut.mutate(false)}
            >
              {t("admin.replication.pairing.becomeStandby.submit")}
            </Button>
          </Group>
        </Stack>
      </Card>
      {existing !== null && (
        <ConfirmReplaceNodeModal
          opened={true}
          existingNode={existing}
          loading={submitMut.isPending}
          onCancel={() => setExisting(null)}
          onConfirm={() => submitMut.mutate(true)}
        />
      )}
    </Stack>
  );
}
```

- [ ] **Step 4: Run → vert attendu**

Run: `cd frontend && npx vitest run src/tests/becomeStandbyPageReplaceFlow.test.tsx`
Expected: PASS.

- [ ] **Step 5: TS strict + ESLint**

Run: `cd frontend && npx tsc --noEmit && npm run lint`
Expected: pas d'erreur.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/BecomeStandbyPage.tsx frontend/src/tests/becomeStandbyPageReplaceFlow.test.tsx
git commit -m "feat(frontend): BecomeStandbyPage propose le remplacement quand le master retourne 409"
```

---

## Task 14: Vérification end-to-end et nettoyage

**Files:** N/A (vérification)

- [ ] **Step 1: Backend full test suite**

Run: `cd backend && uv run pytest -v -k "pairing or replication"`
Expected: tous les tests passent (anciens + nouveaux).

- [ ] **Step 2: Backend ruff format + lint sur les fichiers modifiés**

Run :
```bash
cd backend && uv run ruff format src/app/services/pairing.py src/app/services/pairing_v2.py src/app/services/streaming_replication.py src/app/models/api/pairing.py src/app/api/v1/admin_replication_pairing.py
cd backend && uv run ruff check src/ tests/
```
Expected: aucune erreur.

- [ ] **Step 3: Frontend full test suite + TS strict + lint**

Run :
```bash
cd frontend && npm test
cd frontend && npx tsc --noEmit
cd frontend && npm run lint
```
Expected: tous verts.

- [ ] **Step 4: Vérification manuelle sur LXC 201 (deux instances locales)**

Sur la machine de test :
1. Lancer master `192.168.10.196` + standby `192.168.10.198`.
2. Reproduire la situation initiale (un node fantôme côté master pour `https://192.168.10.198:8443`).
3. Depuis le master, générer une URL d'appairage via `AddStandbyModal` pour `https://192.168.10.198:8443`.
4. Coller l'URL dans `BecomeStandbyPage` du standby.
5. **Attendu** : la modale `ConfirmReplaceNodeModal` s'affiche avec les détails du node existant (last_state, last_seen_at).
6. Cliquer `Remplacer` → l'appel `accept-v2` réussit en 200 → navigation vers `/admin/pairing/<sid>` → wizard s'affiche.
7. Vérifier audit log master : `SELECT * FROM audit_log WHERE action = 'pairing.master_node_replaced' ORDER BY created_at DESC LIMIT 5;` → une row récente.
8. Vérifier qu'un seul node existe pour ce standby : `SELECT id, label, replication_user FROM replication_nodes WHERE LOWER(label) = 'https://192.168.10.198:8443';` → exactement 1 row, avec un nouveau `replication_user` (suffixe hex différent).
9. Vérifier qu'aucun ancien rôle PG n'est orphelin : `SELECT rolname FROM pg_roles WHERE rolname LIKE 'repl_%';` → 1 seul rôle correspondant au nouveau node.

- [ ] **Step 5: Mettre à jour `LESSONS.md`**

Ajouter à `LESSONS.md` :

```markdown
- [replication] add_node lève désormais NodeAlreadyExistsError (sous-classe d'InvalidPairingPreconditionError) sur conflit UNIQUE(label/application_name) ; les endpoints pairing v2 mappent en 409 avec `existing_node`. Le param `force` (request body) déclenche un DELETE+DROP ROLE+INSERT atomique pour remplacer le node existant. Audit log : `pairing.master_node_replaced`.
```

- [ ] **Step 6: Commit final**

```bash
git add LESSONS.md
git commit -m "docs: leçon LESSONS.md sur le pairing v2 idempotent (LOT 5 fix)"
```

---

## Self-Review

**Spec coverage** :
- 409 propre côté master au lieu de 500 → Task 6 ✓
- Détails du node existant remontés au frontend → Tasks 2 + 6 + 7 + 8 + 9 ✓
- Confirmation utilisateur explicite → Tasks 11 + 12 + 13 ✓
- Remplacement atomique côté master (DROP ROLE + DELETE + CREATE ROLE + INSERT) → Task 3 ✓
- Audit log `pairing.master_node_replaced` → Task 4 ✓
- Pas de destruction silencieuse (force par défaut false) → Tasks 5 + 10 ✓
- TLS verify policy + auth admin maintenues → Tasks 7 + 8 (héritées du code existant) ✓

**Placeholder scan** : pas de TBD, pas de "similar to Task N", code complet partout. ✓

**Type consistency** :
- `ExistingNode` (TS) ↔ `existing_node` dict (Py) : mêmes champs (`id, label, host, application_name, last_state, last_seen_at`) ✓
- `force` partout `bool` avec défaut `false` ✓
- `NodeAlreadyExistsError` consistant dans Task 1 → 7 ✓
- `replace_existing` (Python, paramètre `add_node`) ≠ `force` (paramètre `confirm_master_v2` + `accept_standby_v2`) — distinction volontaire : `force` est le contrat *transport*, `replace_existing` est l'API du service bas niveau. ✓

---

## Execution Handoff

Plan complet et sauvegardé. Deux options d'exécution :

1. **Subagent-Driven (recommandé)** — un subagent frais par tâche, revue entre tâches, itération rapide.
2. **Inline Execution** — tâches exécutées dans la session courante via `executing-plans`, batchs avec checkpoints.

Quelle approche ?
