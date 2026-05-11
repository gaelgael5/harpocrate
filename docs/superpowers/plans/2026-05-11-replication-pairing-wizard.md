# Replication Pairing Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre l'appairage guidé de deux instances Harpocrate en master/standby Postgres, sans automatisation des commandes shell : Harpocrate ouvre une session SSH dans son UI (creds saisis par l'admin, jamais persistés), affiche pas-à-pas les commandes à coller dans le terminal, et trace l'état d'avancement.

**Architecture :**
1. **Bridge SSH terminal in-browser** — backend WebSocket reliant `xterm.js` à une session `asyncssh` interactive ; creds en RAM uniquement.
2. **Protocole d'appairage à code 4 chiffres** — A initie, génère un code, expose `/pairing/confirm` ; B saisit URL+code et reçoit un payload (host, replication user, password généré).
3. **Wizard step-by-step** — backend génère la liste ordonnée des commandes Postgres ; endpoints `done`/`back` portent le curseur ; UI 2-colonnes (terminal SSH + stepper Mantine).
4. **Mode asservi** — flag `is_standby_of` bloquant les actions de gestion réplication côté B et affichant un bandeau permanent.

Le promote (failover manuel) est **hors scope** de ce plan, à traiter dans un plan séparé une fois le pairing en production.

**Tech Stack :**
- Backend : Python 3.12, FastAPI, asyncpg, asyncssh ≥ 2.22 (déjà installé), structlog, pytest
- Frontend : React 18, TypeScript strict, Mantine v7, TanStack Query, react-i18next, **xterm.js** (à ajouter)
- DB : PostgreSQL 16 (migrations 028–031)

---

## File Structure

### Backend — création

| Fichier | Responsabilité |
|---|---|
| `backend/migrations/028_pairing_sessions.sql` | Table `pairing_session` (sessions actives, code 4 chiffres, payload JSONB, curseur step) |
| `backend/migrations/029_system_metadata_standby.sql` | Seed clé `replication.is_standby_of` (NULL par défaut) |
| `backend/app/db/repositories/pairing_sessions.py` | CRUD `pairing_session` |
| `backend/app/services/ssh_terminal.py` | Bridge bidirectionnel WebSocket ↔ asyncssh (PTY interactive) |
| `backend/app/services/pairing.py` | Logique métier appairage (init, accept, completion) |
| `backend/app/services/pairing_steps.py` | Génération de la liste ordonnée des commandes Postgres |
| `backend/app/api/v1/admin_ssh_terminal.py` | Endpoint WS `/admin/ssh-terminal/ws` |
| `backend/app/api/v1/admin_replication_pairing.py` | REST `/admin/replication/pairing/*` |
| `backend/app/schemas/pairing.py` | DTOs Pydantic (PairingInit, PairingConfirm, StepStatus, etc.) |
| `backend/tests/test_ssh_terminal.py` | Tests unit (auth, ouverture/fermeture session, audit) |
| `backend/tests/test_pairing_service.py` | Tests unit (init, accept, expiration, rate-limit) |
| `backend/tests/test_pairing_steps.py` | Tests unit (génération de commandes, paramètres template) |
| `backend/tests/test_pairing_api.py` | Tests intégration (endpoints REST appairage + wizard) |

### Backend — modification

| Fichier | Changement |
|---|---|
| `backend/app/main.py` | Inclusion routers `admin_ssh_terminal.router` + `admin_replication_pairing.router` |
| `backend/app/core/config.py` | Settings `pairing_code_ttl_seconds: int = 600`, `pairing_max_attempts: int = 3`, `ssh_terminal_idle_timeout_seconds: int = 1800` |
| `backend/app/services/streaming_replication.py` | Hook `set_standby_of()` après complétion appairage (set system_metadata) |
| `backend/app/services/audit_log.py` | Pas de modification — réutiliser l'API existante (events `pairing.*`, `ssh_session.*`) |

### Frontend — création

| Fichier | Responsabilité |
|---|---|
| `frontend/src/components/SSHTerminal.tsx` | Composant terminal xterm.js + WS client + resize |
| `frontend/src/components/SSHCredentialsModal.tsx` | Saisie host/port/user/auth (password OU clé privée + passphrase) |
| `frontend/src/components/StandbyBanner.tsx` | Bandeau permanent affiché quand `is_standby_of` non-null |
| `frontend/src/components/AddStandbyModal.tsx` | Modale côté A : saisie URL B → init → affiche code 4 chiffres |
| `frontend/src/components/PairingStepsList.tsx` | Stepper Mantine avec commandes, click-to-copy, OK/Retour |
| `frontend/src/pages/PairingWizardPage.tsx` | Page B — terminal à gauche + stepper à droite |
| `frontend/src/pages/BecomeStandbyPage.tsx` | Page B — saisie URL master + code → POST /accept → redirect wizard |
| `frontend/src/lib/sshTerminalSocket.ts` | Helper WebSocket (URL, JWT, reconnect logic minimal) |
| `frontend/src/schemas/pairing.ts` | Zod schemas (mirror des DTOs backend) |
| `frontend/src/i18n/fr.json` + `en.json` | Sections `admin.replication.pairing.*` et `admin.ssh.*` |
| `frontend/src/tests/sshTerminalSocket.test.ts` | Tests parse messages WS |
| `frontend/src/tests/pairingStepsList.test.tsx` | Tests stepper (click-to-copy, navigation OK/Retour) |

### Frontend — modification

| Fichier | Changement |
|---|---|
| `frontend/src/lib/adminApi.ts` | Ajout `initPairing`, `acceptPairing`, `getPairingStatus`, `markStepDone`, `markStepBack`, `setStandbyOf` |
| `frontend/src/lib/api-client.ts` | Helper `getJwtForWs()` exposant le token courant pour le query-string WS |
| `frontend/src/components/StreamingNodesPanel.tsx` | Bouton « Ajouter un standby (assistant) » → ouvre `AddStandbyModal` |
| `frontend/src/components/Layout.tsx` | Render `<StandbyBanner />` global avant `<Outlet />` |
| `frontend/src/App.tsx` | Routes `/admin/become-standby` + `/admin/pairing/:sessionId` (Layout protégé) |
| `frontend/package.json` | Ajout deps `xterm`, `@xterm/addon-fit`, `@xterm/addon-attach` |
| `frontend/src/pages/AdminReplicationPage.tsx` | Désactivation conditionnelle des actions quand `is_standby_of` |

---

## Conventions transverses

**Cycle TDD pour CHAQUE tâche** (rappel — les steps individuels « écrire test rouge / écrire impl / vérifier vert » sont implicites et regroupés par tâche pour la lisibilité du plan) :
1. Écrire le test qui échoue
2. `pytest -xvs <test>` → confirmer FAIL avec le message attendu
3. Implémenter le minimum pour passer
4. `pytest -xvs <test>` → confirmer PASS
5. Lancer la suite ciblée + `ruff check` + `ruff format`
6. Commit

**Format commits** : conventionnel français — `feat:`, `fix:`, `chore:`, `test:`, `docs:`. Suffixe `(LOT N)` optionnel.

**Auth admin backend** : `from app.core.admin_auth import AdminJwt` puis `admin: AdminJwt` en paramètre de l'endpoint (pour les WS, voir Task 1.3 — handshake spécifique).

**i18n** : aucun label en clair dans le JSX — toujours `t('admin.replication.pairing.<key>')`. Ajouter chaque nouvelle clé dans `fr.json` ET `en.json` (anglais traduit en dernier — voir mémoire `workflow_doc_validation_after_features`).

**Audit log events introduits** :
- `ssh_session.opened` — metadata `{host, port, username, source_ip}`
- `ssh_session.closed` — metadata `{host, port, duration_seconds, reason}`
- `pairing.master_init` — metadata `{partner_url, code_prefix}` (code masqué : `12**`)
- `pairing.standby_accepted` — metadata `{master_url, session_id}`
- `pairing.completed` — metadata `{role, partner_url}`
- `pairing.failed` — metadata `{role, reason}`
- `replication.standby_of_set` — metadata `{master_url}`

---

# LOT 1 — Bridge SSH Terminal (3 j)

**Objectif** : exposer un terminal SSH interactif dans le navigateur, contrôlé par l'admin Harpocrate, sans persistance des credentials.

**Dépendances** : `asyncssh ≥ 2.22` (déjà installé), `xterm` côté frontend.

---

### Task 1.1 : Migration table `pairing_session`

**Files :**
- Create : `backend/migrations/028_pairing_sessions.sql`
- Test : `backend/tests/test_pairing_session_migration.py`

- [ ] **Step 1 : Test de migration**

```python
# backend/tests/test_pairing_session_migration.py
import pytest
from app.db.pool import get_pool

@pytest.mark.asyncio
async def test_pairing_session_table_exists():
    pool = await get_pool()
    async with pool.acquire() as conn:
        cols = await conn.fetch(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = 'pairing_session' ORDER BY ordinal_position"
        )
    names = [c["column_name"] for c in cols]
    for expected in [
        "id", "role", "code", "partner_url", "status", "payload",
        "current_step_idx", "created_at", "expires_at", "attempts",
        "actor_user_id",
    ]:
        assert expected in names, f"missing column {expected}"
```

- [ ] **Step 2 : Run pour confirmer échec** : `uv run pytest -xvs backend/tests/test_pairing_session_migration.py` → FAIL (table absente)

- [ ] **Step 3 : Écrire la migration**

```sql
-- backend/migrations/028_pairing_sessions.sql
CREATE TABLE pairing_session (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    role          TEXT NOT NULL CHECK (role IN ('master', 'standby')),
    code          TEXT NOT NULL,
    partner_url   TEXT,
    status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','confirmed','wizard','completed','expired','failed')),
    payload       JSONB NOT NULL DEFAULT '{}'::jsonb,
    current_step_idx INTEGER NOT NULL DEFAULT 0,
    attempts      INTEGER NOT NULL DEFAULT 0,
    actor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at    TIMESTAMPTZ NOT NULL
);

CREATE INDEX pairing_session_status_idx ON pairing_session(status);
CREATE INDEX pairing_session_code_pending_idx
    ON pairing_session(code) WHERE status IN ('pending', 'confirmed');
```

- [ ] **Step 4 : Appliquer + relancer le test** : `uv run python -m app.db.migrations` puis `uv run pytest -xvs backend/tests/test_pairing_session_migration.py` → PASS

- [ ] **Step 5 : Commit**

```bash
git add backend/migrations/028_pairing_sessions.sql backend/tests/test_pairing_session_migration.py
git commit -m "feat(replication): table pairing_session pour appairage guidé (LOT 1)"
```

---

### Task 1.2 : Repository `pairing_sessions`

**Files :**
- Create : `backend/app/db/repositories/pairing_sessions.py`
- Test : `backend/tests/test_pairing_sessions_repo.py`

- [ ] **Step 1 : Tests CRUD**

```python
# backend/tests/test_pairing_sessions_repo.py
import pytest
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from app.db.pool import get_pool
from app.db.repositories import pairing_sessions as repo

@pytest.mark.asyncio
async def test_create_and_fetch():
    pool = await get_pool()
    async with pool.acquire() as conn:
        sid = await repo.create(
            conn,
            role="master",
            code="1234",
            partner_url="https://b.example/",
            ttl_seconds=600,
            actor_user_id=None,
        )
        row = await repo.get(conn, sid)
    assert row["role"] == "master"
    assert row["code"] == "1234"
    assert row["status"] == "pending"
    assert row["current_step_idx"] == 0

@pytest.mark.asyncio
async def test_get_active_by_code():
    pool = await get_pool()
    async with pool.acquire() as conn:
        sid = await repo.create(conn, role="master", code="9876",
                                 partner_url=None, ttl_seconds=600, actor_user_id=None)
        found = await repo.get_active_by_code(conn, "9876")
    assert found is not None and found["id"] == sid

@pytest.mark.asyncio
async def test_increment_attempts():
    pool = await get_pool()
    async with pool.acquire() as conn:
        sid = await repo.create(conn, role="master", code="5555",
                                 partner_url=None, ttl_seconds=600, actor_user_id=None)
        n = await repo.increment_attempts(conn, sid)
    assert n == 1

@pytest.mark.asyncio
async def test_set_status_payload_step():
    pool = await get_pool()
    async with pool.acquire() as conn:
        sid = await repo.create(conn, role="standby", code="0001",
                                 partner_url="https://a.example/",
                                 ttl_seconds=600, actor_user_id=None)
        await repo.set_status(conn, sid, "wizard")
        await repo.set_payload(conn, sid, {"replication_user": "rep_x"})
        await repo.set_step_idx(conn, sid, 3)
        row = await repo.get(conn, sid)
    assert row["status"] == "wizard"
    assert row["payload"]["replication_user"] == "rep_x"
    assert row["current_step_idx"] == 3
```

- [ ] **Step 2 : Implémenter le repo**

```python
# backend/app/db/repositories/pairing_sessions.py
"""CRUD pairing_session — sessions d'appairage entre 2 instances Harpocrate."""
from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID
import asyncpg

async def create(
    conn: asyncpg.Connection, *, role: str, code: str,
    partner_url: str | None, ttl_seconds: int, actor_user_id: UUID | None,
) -> UUID:
    expires = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    row = await conn.fetchrow(
        """
        INSERT INTO pairing_session (role, code, partner_url, expires_at, actor_user_id)
        VALUES ($1, $2, $3, $4, $5) RETURNING id
        """,
        role, code, partner_url, expires, actor_user_id,
    )
    return row["id"]

async def get(conn: asyncpg.Connection, sid: UUID) -> dict | None:
    row = await conn.fetchrow("SELECT * FROM pairing_session WHERE id = $1", sid)
    if row is None:
        return None
    out = dict(row)
    if isinstance(out["payload"], str):
        out["payload"] = json.loads(out["payload"])
    return out

async def get_active_by_code(conn: asyncpg.Connection, code: str) -> dict | None:
    row = await conn.fetchrow(
        """SELECT * FROM pairing_session
           WHERE code = $1 AND status IN ('pending', 'confirmed')
             AND expires_at > now()
           ORDER BY created_at DESC LIMIT 1""",
        code,
    )
    if row is None:
        return None
    out = dict(row)
    if isinstance(out["payload"], str):
        out["payload"] = json.loads(out["payload"])
    return out

async def increment_attempts(conn: asyncpg.Connection, sid: UUID) -> int:
    row = await conn.fetchrow(
        "UPDATE pairing_session SET attempts = attempts + 1 WHERE id = $1 RETURNING attempts",
        sid,
    )
    return row["attempts"] if row else 0

async def set_status(conn: asyncpg.Connection, sid: UUID, status: str) -> None:
    await conn.execute("UPDATE pairing_session SET status = $1 WHERE id = $2", status, sid)

async def set_payload(conn: asyncpg.Connection, sid: UUID, payload: dict[str, Any]) -> None:
    await conn.execute(
        "UPDATE pairing_session SET payload = $1::jsonb WHERE id = $2",
        json.dumps(payload), sid,
    )

async def set_step_idx(conn: asyncpg.Connection, sid: UUID, idx: int) -> None:
    await conn.execute(
        "UPDATE pairing_session SET current_step_idx = $1 WHERE id = $2", idx, sid,
    )

async def expire_old(conn: asyncpg.Connection) -> int:
    res = await conn.execute(
        "UPDATE pairing_session SET status = 'expired' "
        "WHERE status IN ('pending','confirmed','wizard') AND expires_at < now()"
    )
    return int(res.split()[-1]) if res else 0
```

- [ ] **Step 3 : Tests verts** : `uv run pytest -xvs backend/tests/test_pairing_sessions_repo.py`

- [ ] **Step 4 : Lint + commit**

```bash
cd backend && uv run ruff format src/ tests/ && uv run ruff check src/ tests/
git add backend/app/db/repositories/pairing_sessions.py backend/tests/test_pairing_sessions_repo.py
git commit -m "feat(replication): repository pairing_sessions (LOT 1)"
```

---

### Task 1.3 : Service `ssh_terminal` — bridge WS ↔ asyncssh

**Files :**
- Create : `backend/app/services/ssh_terminal.py`
- Test : `backend/tests/test_ssh_terminal.py`

**Design notes :**
- L'endpoint WebSocket attend en premier message un JSON `{type:"open", host, port, username, auth_type, password?, private_key?, passphrase?}`.
- Connexion asyncssh avec `known_hosts=None` (TOFU pour le MVP, warning loggé). Améliorable ultérieurement.
- Ouvre `await conn.create_process(term_type='xterm-256color', encoding=None)` pour avoir un PTY.
- Deux tâches asyncio en parallèle :
  - `ws_to_ssh` : reçoit `{type:"data", payload}` et `{type:"resize", cols, rows}` → écrit dans stdin / appelle `proc.change_terminal_size`
  - `ssh_to_ws` : lit stdout binaire chunk par chunk → envoie `{type:"data", payload: base64}`
- À la fermeture (côté WS ou côté SSH) : `proc.close()` + `conn.close()` + audit log + retour close frame.
- Idle timeout `ssh_terminal_idle_timeout_seconds` (30 min par défaut) — mesuré depuis dernier message reçu OU envoyé.

- [ ] **Step 1 : Tests unit (auth, ouverture, audit)**

```python
# backend/tests/test_ssh_terminal.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services import ssh_terminal as svc

@pytest.mark.asyncio
async def test_validate_open_message_password():
    msg = {"type": "open", "host": "h", "port": 22, "username": "u",
           "auth_type": "password", "password": "p"}
    creds = svc._parse_open_message(msg)
    assert creds.host == "h" and creds.password == "p"
    assert creds.private_key is None

@pytest.mark.asyncio
async def test_validate_open_message_privkey():
    msg = {"type": "open", "host": "h", "port": 22, "username": "u",
           "auth_type": "privkey",
           "private_key": "-----BEGIN OPENSSH PRIVATE KEY-----\n...\n-----END OPENSSH PRIVATE KEY-----",
           "passphrase": "p"}
    creds = svc._parse_open_message(msg)
    assert creds.private_key is not None and creds.passphrase == "p"

@pytest.mark.asyncio
async def test_invalid_first_message_raises():
    with pytest.raises(svc.InvalidHandshakeError):
        svc._parse_open_message({"type": "data", "payload": "x"})

@pytest.mark.asyncio
async def test_invalid_auth_type_raises():
    with pytest.raises(svc.InvalidHandshakeError):
        svc._parse_open_message({"type": "open", "host": "h", "port": 22,
                                  "username": "u", "auth_type": "agent"})

@pytest.mark.asyncio
async def test_run_session_audit_logs(monkeypatch):
    """Vérifie que ssh_session.opened/closed sont émis."""
    # mocking asyncssh: voir docs/superpowers/plans pour helpers
    fake_proc = MagicMock()
    fake_proc.stdout.read = AsyncMock(side_effect=[b"", asyncio.CancelledError()])
    fake_proc.stdin.write = MagicMock()
    fake_proc.close = MagicMock()
    fake_conn = MagicMock()
    fake_conn.create_process = AsyncMock(return_value=fake_proc)
    fake_conn.close = MagicMock()

    audit_calls = []
    async def fake_audit(event, **kw):
        audit_calls.append((event, kw))
    monkeypatch.setattr(svc, "_audit", fake_audit)

    fake_ws = MagicMock()
    fake_ws.receive_text = AsyncMock(return_value='{"type":"open","host":"h","port":22,"username":"u","auth_type":"password","password":"p"}')
    fake_ws.client = MagicMock(host="127.0.0.1")
    fake_ws.send_json = AsyncMock()
    fake_ws.close = AsyncMock()

    with patch("asyncssh.connect", AsyncMock(return_value=fake_conn)):
        await svc.run_session(fake_ws, actor_user_id=None)

    assert any(e == "ssh_session.opened" for e, _ in audit_calls)
    assert any(e == "ssh_session.closed" for e, _ in audit_calls)
```

- [ ] **Step 2 : Implémenter le service**

```python
# backend/app/services/ssh_terminal.py
"""Bridge WebSocket ↔ asyncssh (PTY interactive).

Sécurité : creds en RAM uniquement (jamais persistés). Audit log open/close,
sans contenu de session. Idle timeout configurable.
"""
from __future__ import annotations
import asyncio
import base64
import json
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import asyncssh
import structlog
from fastapi import WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.services import audit_log as audit_svc

log = structlog.get_logger(__name__)


class InvalidHandshakeError(ValueError):
    """Premier message WS mal formé ou auth_type non supporté."""


@dataclass(frozen=True)
class SshCredentials:
    host: str
    port: int
    username: str
    password: str | None
    private_key: str | None
    passphrase: str | None


def _parse_open_message(msg: dict[str, Any]) -> SshCredentials:
    if not isinstance(msg, dict) or msg.get("type") != "open":
        raise InvalidHandshakeError("first_message_must_be_open")
    auth_type = msg.get("auth_type")
    if auth_type not in ("password", "privkey"):
        raise InvalidHandshakeError(f"unsupported_auth_type:{auth_type}")
    host = msg.get("host")
    username = msg.get("username")
    port = int(msg.get("port", 22))
    if not host or not username:
        raise InvalidHandshakeError("missing_host_or_username")
    return SshCredentials(
        host=str(host),
        port=port,
        username=str(username),
        password=msg.get("password") if auth_type == "password" else None,
        private_key=msg.get("private_key") if auth_type == "privkey" else None,
        passphrase=msg.get("passphrase") if auth_type == "privkey" else None,
    )


async def _audit(event: str, *, actor_user_id: UUID | None, **metadata: Any) -> None:
    """Wrapper léger sur audit_log — fonction monkeypatchable en test."""
    await audit_svc.write_event(
        event_type=event,
        actor_user_id=actor_user_id,
        metadata=metadata,
    )


async def _connect_asyncssh(creds: SshCredentials) -> asyncssh.SSHClientConnection:
    if creds.private_key:
        client_keys = [asyncssh.import_private_key(
            creds.private_key, passphrase=creds.passphrase or None
        )]
        return await asyncssh.connect(
            host=creds.host, port=creds.port, username=creds.username,
            client_keys=client_keys, known_hosts=None,
        )
    return await asyncssh.connect(
        host=creds.host, port=creds.port, username=creds.username,
        password=creds.password, known_hosts=None,
    )


async def run_session(ws: WebSocket, *, actor_user_id: UUID | None) -> None:
    """Boucle principale : handshake → connexion SSH → bridge bidirectionnel."""
    started_at = time.monotonic()
    creds: SshCredentials | None = None
    conn = None
    proc = None
    close_reason = "normal"
    source_ip = ws.client.host if ws.client else "unknown"

    try:
        first = await asyncio.wait_for(ws.receive_text(), timeout=10.0)
        creds = _parse_open_message(json.loads(first))

        await _audit(
            "ssh_session.opened",
            actor_user_id=actor_user_id,
            host=creds.host, port=creds.port, username=creds.username,
            source_ip=source_ip,
        )

        conn = await _connect_asyncssh(creds)
        proc = await conn.create_process(term_type="xterm-256color", encoding=None)

        await ws.send_json({"type": "ready"})

        async def ws_to_ssh() -> None:
            while True:
                raw = await ws.receive_text()
                msg = json.loads(raw)
                t = msg.get("type")
                if t == "data":
                    proc.stdin.write(base64.b64decode(msg["payload"]))
                elif t == "resize":
                    proc.change_terminal_size(int(msg["cols"]), int(msg["rows"]))
                elif t == "close":
                    return

        async def ssh_to_ws() -> None:
            while True:
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    return
                await ws.send_json({
                    "type": "data",
                    "payload": base64.b64encode(chunk).decode("ascii"),
                })

        try:
            await asyncio.wait_for(
                asyncio.gather(ws_to_ssh(), ssh_to_ws()),
                timeout=settings.ssh_terminal_idle_timeout_seconds,
            )
        except asyncio.TimeoutError:
            close_reason = "idle_timeout"

    except WebSocketDisconnect:
        close_reason = "client_disconnect"
    except InvalidHandshakeError as e:
        close_reason = f"invalid_handshake:{e}"
        await ws.send_json({"type": "error", "code": str(e)})
    except (asyncssh.PermissionDenied, asyncssh.DisconnectError) as e:
        close_reason = f"ssh_auth:{type(e).__name__}"
        await ws.send_json({"type": "error", "code": "ssh_auth_failed",
                             "message": str(e)})
    except Exception as e:
        log.exception("ssh_terminal_unexpected", error=str(e))
        close_reason = f"unexpected:{type(e).__name__}"
    finally:
        if proc is not None:
            proc.close()
        if conn is not None:
            conn.close()
        if creds is not None:
            await _audit(
                "ssh_session.closed",
                actor_user_id=actor_user_id,
                host=creds.host, port=creds.port,
                duration_seconds=int(time.monotonic() - started_at),
                reason=close_reason,
            )
        try:
            await ws.close()
        except Exception:
            pass
```

- [ ] **Step 3 : Tests verts** : `uv run pytest -xvs backend/tests/test_ssh_terminal.py`

- [ ] **Step 4 : Lint + commit**

```bash
cd backend && uv run ruff format src/ tests/ && uv run ruff check src/ tests/
git add backend/app/services/ssh_terminal.py backend/tests/test_ssh_terminal.py
git commit -m "feat(ssh): service bridge WebSocket vers asyncssh PTY (LOT 1)"
```

---

### Task 1.4 : Endpoint WebSocket `/admin/ssh-terminal/ws` + auth

**Files :**
- Create : `backend/app/api/v1/admin_ssh_terminal.py`
- Modify : `backend/app/main.py` (inclusion router)
- Modify : `backend/app/core/config.py` (settings)
- Test : `backend/tests/test_ssh_terminal_api.py`

**Auth WebSocket** : impossible d'utiliser `Depends(require_admin_jwt)` directement (FastAPI Header n'est pas exposé identique en WS). Le client envoie le JWT en query string `?token=<jwt>`. Le handler valide via `_validate_jwt` + check rôle admin avant d'ouvrir la session SSH.

- [ ] **Step 1 : Tests endpoint**

```python
# backend/tests/test_ssh_terminal_api.py
import pytest
from fastapi.testclient import TestClient
from app.main import app

def test_ws_rejects_missing_token():
    client = TestClient(app)
    with pytest.raises(Exception):
        with client.websocket_connect("/v1/admin/ssh-terminal/ws"):
            pass

def test_ws_rejects_invalid_token():
    client = TestClient(app)
    with pytest.raises(Exception):
        with client.websocket_connect("/v1/admin/ssh-terminal/ws?token=bad"):
            pass

def test_ws_rejects_api_key_token():
    client = TestClient(app)
    with pytest.raises(Exception):
        with client.websocket_connect("/v1/admin/ssh-terminal/ws?token=hrpv_abc"):
            pass
```

- [ ] **Step 2 : Implémenter l'endpoint**

```python
# backend/app/api/v1/admin_ssh_terminal.py
"""Endpoint WebSocket — bridge SSH terminal pour l'UI admin (LOT 1)."""
from __future__ import annotations
import structlog
from fastapi import APIRouter, Query, WebSocket, status

from app.core.config import settings
from app.core.security import _validate_jwt
from app.services import admin_user_resolver
from app.services import ssh_terminal as svc

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/admin/ssh-terminal", tags=["admin-ssh-terminal"])


@router.websocket("/ws")
async def ssh_terminal_ws(ws: WebSocket, token: str = Query(...)) -> None:
    if token.startswith("hrpv_"):
        await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason="api_key_not_allowed")
        return
    try:
        payload = await _validate_jwt(token)
    except Exception:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason="invalid_token")
        return

    roles = payload.get("realm_access", {}).get("roles", [])
    if settings.admin_role_name not in roles:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason="not_admin")
        return

    user_id = await admin_user_resolver.resolve_admin_user_id(
        keycloak_sub=payload["sub"],
        email=payload.get("email", ""),
        display_name=payload.get("name"),
    )
    await ws.accept()
    await svc.run_session(ws, actor_user_id=user_id)
```

- [ ] **Step 3 : Ajouter settings**

```python
# backend/app/core/config.py — dans la classe Settings
ssh_terminal_idle_timeout_seconds: int = 1800
pairing_code_ttl_seconds: int = 600
pairing_max_attempts: int = 3
```

- [ ] **Step 4 : Inclure le router**

```python
# backend/app/main.py — section où sont inclus les autres routers admin_*
from app.api.v1 import admin_ssh_terminal  # noqa
app.include_router(admin_ssh_terminal.router, prefix="/v1")
```

- [ ] **Step 5 : Tests verts** : `uv run pytest -xvs backend/tests/test_ssh_terminal_api.py`

- [ ] **Step 6 : Commit**

```bash
git add backend/app/api/v1/admin_ssh_terminal.py backend/app/main.py \
        backend/app/core/config.py backend/tests/test_ssh_terminal_api.py
git commit -m "feat(ssh): endpoint WebSocket admin/ssh-terminal/ws avec auth JWT (LOT 1)"
```

---

### Task 1.5 : Frontend — installation `xterm` + helper WS

**Files :**
- Modify : `frontend/package.json`
- Create : `frontend/src/lib/sshTerminalSocket.ts`
- Create : `frontend/src/tests/sshTerminalSocket.test.ts`

- [ ] **Step 1 : Installer les deps**

```bash
cd frontend && npm install xterm @xterm/addon-fit @xterm/addon-attach
```

- [ ] **Step 2 : Tests parser**

```typescript
// frontend/src/tests/sshTerminalSocket.test.ts
import { describe, it, expect } from 'vitest'
import { encodeOpen, encodeData, encodeResize, parseServerMessage } from '@/lib/sshTerminalSocket'

describe('sshTerminalSocket', () => {
  it('encodes open message with password', () => {
    const m = encodeOpen({ host: 'h', port: 22, username: 'u',
                            authType: 'password', password: 'p' })
    expect(JSON.parse(m)).toEqual({
      type: 'open', host: 'h', port: 22, username: 'u',
      auth_type: 'password', password: 'p',
    })
  })

  it('encodes open message with private key + passphrase', () => {
    const m = encodeOpen({ host: 'h', port: 22, username: 'u',
                            authType: 'privkey',
                            privateKey: '-----BEGIN-----\n...', passphrase: 'pp' })
    expect(JSON.parse(m).private_key).toContain('BEGIN')
    expect(JSON.parse(m).passphrase).toBe('pp')
  })

  it('encodes data as base64', () => {
    const m = JSON.parse(encodeData('hello'))
    expect(m.type).toBe('data')
    expect(atob(m.payload)).toBe('hello')
  })

  it('encodes resize', () => {
    const m = JSON.parse(encodeResize(80, 24))
    expect(m).toEqual({ type: 'resize', cols: 80, rows: 24 })
  })

  it('parses server data into Uint8Array', () => {
    const r = parseServerMessage(JSON.stringify({ type: 'data', payload: btoa('xy') }))
    expect(r.type).toBe('data')
    expect(new TextDecoder().decode(r.data!)).toBe('xy')
  })

  it('parses error message', () => {
    const r = parseServerMessage(JSON.stringify({
      type: 'error', code: 'ssh_auth_failed', message: 'denied' }))
    expect(r.type).toBe('error')
    expect(r.errorCode).toBe('ssh_auth_failed')
  })
})
```

- [ ] **Step 3 : Implémenter le helper**

```typescript
// frontend/src/lib/sshTerminalSocket.ts
/**
 * Helper WebSocket pour SSHTerminal — encode/parse les messages, résout l'URL WS.
 * Pas de logique de UI ici, juste de la sérialisation.
 */

export type SshOpenArgs =
  | { host: string; port: number; username: string; authType: 'password'; password: string }
  | { host: string; port: number; username: string; authType: 'privkey';
      privateKey: string; passphrase?: string }

export function encodeOpen(args: SshOpenArgs): string {
  const base = { type: 'open', host: args.host, port: args.port, username: args.username }
  if (args.authType === 'password') {
    return JSON.stringify({ ...base, auth_type: 'password', password: args.password })
  }
  return JSON.stringify({
    ...base, auth_type: 'privkey',
    private_key: args.privateKey,
    passphrase: args.passphrase ?? '',
  })
}

export function encodeData(text: string): string {
  // btoa attend une chaîne latin-1 ; pour de l'UTF-8 robuste on passe par TextEncoder
  const bytes = new TextEncoder().encode(text)
  let bin = ''
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]!)
  return JSON.stringify({ type: 'data', payload: btoa(bin) })
}

export function encodeResize(cols: number, rows: number): string {
  return JSON.stringify({ type: 'resize', cols, rows })
}

export function encodeClose(): string {
  return JSON.stringify({ type: 'close' })
}

export type ServerMessage =
  | { type: 'ready' }
  | { type: 'data'; data: Uint8Array }
  | { type: 'error'; errorCode: string; message?: string }

export function parseServerMessage(raw: string): ServerMessage {
  const m = JSON.parse(raw) as { type: string; payload?: string; code?: string; message?: string }
  if (m.type === 'ready') return { type: 'ready' }
  if (m.type === 'data' && typeof m.payload === 'string') {
    const bin = atob(m.payload)
    const out = new Uint8Array(bin.length)
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
    return { type: 'data', data: out }
  }
  return { type: 'error', errorCode: m.code ?? 'unknown', message: m.message }
}

export function buildWsUrl(jwt: string): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}/v1/admin/ssh-terminal/ws?token=${encodeURIComponent(jwt)}`
}
```

- [ ] **Step 4 : Tests verts** : `npm test -- sshTerminalSocket`

- [ ] **Step 5 : Commit**

```bash
git add frontend/package.json frontend/package-lock.json \
        frontend/src/lib/sshTerminalSocket.ts \
        frontend/src/tests/sshTerminalSocket.test.ts
git commit -m "feat(frontend): helper WS SSH terminal + xterm.js installé (LOT 1)"
```

---

### Task 1.6 : Composants `SSHCredentialsModal` + `SSHTerminal`

**Files :**
- Create : `frontend/src/components/SSHCredentialsModal.tsx`
- Create : `frontend/src/components/SSHTerminal.tsx`
- Modify : `frontend/src/i18n/fr.json` + `en.json`

- [ ] **Step 1 : i18n keys**

Ajouter dans `fr.json` :
```json
"admin": {
  "ssh": {
    "credentials": {
      "title": "Connexion SSH",
      "subtitle": "Renseigne les identifiants pour ouvrir la session. Ils ne sont jamais enregistrés.",
      "host": "Hôte",
      "port": "Port",
      "username": "Utilisateur",
      "authMethod": "Méthode d'authentification",
      "password": "Mot de passe",
      "privateKey": "Clé privée (collée)",
      "passphrase": "Passphrase (optionnelle)",
      "connect": "Se connecter",
      "cancel": "Annuler"
    },
    "terminal": {
      "connecting": "Connexion en cours…",
      "connected": "Connecté",
      "disconnected": "Déconnecté",
      "errorAuth": "Authentification SSH refusée",
      "errorGeneric": "Erreur de connexion SSH"
    }
  }
}
```
Mêmes clés en anglais dans `en.json` (traduction littérale).

- [ ] **Step 2 : Composant `SSHCredentialsModal`**

```tsx
// frontend/src/components/SSHCredentialsModal.tsx
import { useState } from 'react'
import { Modal, Stack, TextInput, NumberInput, SegmentedControl,
          Textarea, PasswordInput, Group, Button, Text } from '@mantine/core'
import { useTranslation } from 'react-i18next'
import type { SshOpenArgs } from '@/lib/sshTerminalSocket'

interface Props {
  opened: boolean
  onClose: () => void
  onSubmit: (creds: SshOpenArgs) => void
}

export function SSHCredentialsModal({ opened, onClose, onSubmit }: Props) {
  const { t } = useTranslation()
  const [host, setHost] = useState('')
  const [port, setPort] = useState<number | string>(22)
  const [username, setUsername] = useState('')
  const [authType, setAuthType] = useState<'password' | 'privkey'>('password')
  const [password, setPassword] = useState('')
  const [privateKey, setPrivateKey] = useState('')
  const [passphrase, setPassphrase] = useState('')

  function submit() {
    const portN = typeof port === 'number' ? port : parseInt(String(port), 10) || 22
    if (authType === 'password') {
      onSubmit({ host, port: portN, username, authType, password })
    } else {
      onSubmit({ host, port: portN, username, authType, privateKey, passphrase })
    }
  }

  return (
    <Modal opened={opened} onClose={onClose} title={t('admin.ssh.credentials.title')}
            size="lg" closeOnClickOutside={false}>
      <Stack>
        <Text size="sm" c="dimmed">{t('admin.ssh.credentials.subtitle')}</Text>
        <TextInput label={t('admin.ssh.credentials.host')} value={host}
                    onChange={(e) => setHost(e.currentTarget.value)} required />
        <NumberInput label={t('admin.ssh.credentials.port')} value={port}
                      onChange={setPort} min={1} max={65535} required />
        <TextInput label={t('admin.ssh.credentials.username')} value={username}
                    onChange={(e) => setUsername(e.currentTarget.value)} required />
        <SegmentedControl
          value={authType}
          onChange={(v) => setAuthType(v as 'password' | 'privkey')}
          data={[
            { value: 'password', label: t('admin.ssh.credentials.password') },
            { value: 'privkey', label: t('admin.ssh.credentials.privateKey') },
          ]}
        />
        {authType === 'password' ? (
          <PasswordInput label={t('admin.ssh.credentials.password')}
                          value={password}
                          onChange={(e) => setPassword(e.currentTarget.value)} />
        ) : (
          <>
            <Textarea label={t('admin.ssh.credentials.privateKey')}
                      autosize minRows={6} maxRows={12}
                      placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"
                      value={privateKey}
                      onChange={(e) => setPrivateKey(e.currentTarget.value)} />
            <PasswordInput label={t('admin.ssh.credentials.passphrase')}
                            value={passphrase}
                            onChange={(e) => setPassphrase(e.currentTarget.value)} />
          </>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {t('admin.ssh.credentials.cancel')}
          </Button>
          <Button onClick={submit} disabled={!host || !username}>
            {t('admin.ssh.credentials.connect')}
          </Button>
        </Group>
      </Stack>
    </Modal>
  )
}
```

- [ ] **Step 3 : Composant `SSHTerminal`**

```tsx
// frontend/src/components/SSHTerminal.tsx
/**
 * Terminal SSH dans le navigateur — xterm.js + WebSocket bridge backend.
 * L'admin saisit ses creds dans la modale ; rien n'est persisté côté front.
 */
import { useEffect, useRef, useState } from 'react'
import { Card, Stack, Group, Badge, Button, Alert } from '@mantine/core'
import { Terminal } from 'xterm'
import { FitAddon } from '@xterm/addon-fit'
import { useTranslation } from 'react-i18next'
import 'xterm/css/xterm.css'

import { SSHCredentialsModal } from './SSHCredentialsModal'
import {
  encodeOpen, encodeData, encodeResize, parseServerMessage, buildWsUrl,
  type SshOpenArgs,
} from '@/lib/sshTerminalSocket'
import { useAuthStore } from '@/lib/authStore'

type Status = 'idle' | 'connecting' | 'connected' | 'disconnected' | 'error'

export function SSHTerminal() {
  const { t } = useTranslation()
  const containerRef = useRef<HTMLDivElement>(null)
  const termRef = useRef<Terminal | null>(null)
  const fitRef = useRef<FitAddon | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const [status, setStatus] = useState<Status>('idle')
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [credModalOpen, setCredModalOpen] = useState(false)
  const jwt = useAuthStore((s) => s.jwt)

  useEffect(() => {
    if (!containerRef.current) return
    const term = new Terminal({ convertEol: true, cursorBlink: true,
                                  fontFamily: 'monospace', fontSize: 13 })
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.open(containerRef.current)
    fit.fit()
    termRef.current = term
    fitRef.current = fit
    const onResize = () => {
      fit.fit()
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(encodeResize(term.cols, term.rows))
      }
    }
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      wsRef.current?.close()
      term.dispose()
    }
  }, [])

  function openConnection(creds: SshOpenArgs) {
    if (!jwt) { setErrorMsg('no_jwt'); setStatus('error'); return }
    setStatus('connecting'); setErrorMsg(null)
    const ws = new WebSocket(buildWsUrl(jwt))
    wsRef.current = ws

    ws.onopen = () => ws.send(encodeOpen(creds))
    ws.onmessage = (ev) => {
      const m = parseServerMessage(String(ev.data))
      if (m.type === 'ready') {
        setStatus('connected')
        const term = termRef.current!
        ws.send(encodeResize(term.cols, term.rows))
        term.onData((d: string) => ws.send(encodeData(d)))
      } else if (m.type === 'data') {
        termRef.current?.write(m.data)
      } else if (m.type === 'error') {
        setErrorMsg(m.message ?? m.errorCode)
        setStatus('error')
      }
    }
    ws.onclose = () => setStatus((prev) => (prev === 'error' ? 'error' : 'disconnected'))
    ws.onerror = () => { setStatus('error'); setErrorMsg('ws_error') }
  }

  return (
    <Card withBorder p="sm">
      <Stack gap="xs">
        <Group justify="space-between">
          <Group gap="xs">
            <StatusBadge status={status} />
            {status === 'idle' || status === 'disconnected' ? (
              <Button size="xs" onClick={() => setCredModalOpen(true)}>
                {t('admin.ssh.credentials.connect')}
              </Button>
            ) : null}
          </Group>
        </Group>
        {errorMsg && <Alert color="red">{t('admin.ssh.terminal.errorGeneric')}: {errorMsg}</Alert>}
        <div ref={containerRef} style={{ width: '100%', height: 480, background: '#000' }} />
        <SSHCredentialsModal
          opened={credModalOpen}
          onClose={() => setCredModalOpen(false)}
          onSubmit={(creds) => { setCredModalOpen(false); openConnection(creds) }}
        />
      </Stack>
    </Card>
  )
}

function StatusBadge({ status }: { status: Status }) {
  const { t } = useTranslation()
  if (status === 'connected') return <Badge color="green">{t('admin.ssh.terminal.connected')}</Badge>
  if (status === 'connecting') return <Badge color="blue">{t('admin.ssh.terminal.connecting')}</Badge>
  if (status === 'error') return <Badge color="red">{t('admin.ssh.terminal.errorGeneric')}</Badge>
  return <Badge color="gray">{t('admin.ssh.terminal.disconnected')}</Badge>
}
```

- [ ] **Step 4 : Vérifier qu'il existe un `useAuthStore` qui expose `jwt`** : `grep -r "useAuthStore" frontend/src/`. Si non : adapter le `import` au store réel utilisé (ex `useSession`, `getJwt()` dans `api-client.ts`). Si refactor nécessaire pour exposer le JWT côté front : faire l'adaptation MINIMUM (une fonction qui lit le token depuis le storage).

- [ ] **Step 5 : Build TS check** : `npx tsc --noEmit` → 0 erreur

- [ ] **Step 6 : Commit**

```bash
git add frontend/src/components/SSHCredentialsModal.tsx \
        frontend/src/components/SSHTerminal.tsx \
        frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(frontend): composants SSHTerminal + modale credentials (LOT 1)"
```

---

### Task 1.7 : Test manuel end-to-end SSH terminal

**Files :** aucun

- [ ] **Step 1 :** `cd backend && uv run uvicorn app.main:app --reload`
- [ ] **Step 2 :** `cd frontend && npm run dev`
- [ ] **Step 3 :** Sur la page Réplication, ajouter temporairement un `<SSHTerminal />` pour test (sera retiré au LOT 4 quand intégré au wizard)
- [ ] **Step 4 :** Se connecter à un host SSH connu (par exemple `localhost` si OpenSSH activé sur Windows, ou la LXC 201) avec password puis avec clé privée — vérifier que le terminal fonctionne dans les 2 cas
- [ ] **Step 5 :** Vérifier que `audit_log` contient `ssh_session.opened` puis `ssh_session.closed` avec la durée
- [ ] **Step 6 :** Fermer l'onglet → vérifier que la session SSH côté backend se ferme proprement (pas de connexion zombie)
- [ ] **Step 7 :** Retirer le `<SSHTerminal />` de la page Réplication, commit fix de cleanup si nécessaire

---

# LOT 2 — Protocole d'appairage (2 j)

**Objectif** : permettre à A d'initier un appairage avec B, et à B de rejoindre A avec un code 4 chiffres + URL master, en échangeant les infos nécessaires (host master, replication user, password).

**Dépendances** : LOT 1 non requis pour ce LOT (purement REST), mais le WI doit s'enchaîner.

---

### Task 2.1 : Schemas Pydantic + Zod pour appairage

**Files :**
- Create : `backend/app/schemas/pairing.py`
- Create : `frontend/src/schemas/pairing.ts`
- Test : `backend/tests/test_pairing_schemas.py`

- [ ] **Step 1 : Tests schemas backend**

```python
# backend/tests/test_pairing_schemas.py
from app.schemas.pairing import (
    PairingInitRequest, PairingInitResponse,
    PairingAcceptRequest, PairingConfirmRequest, PairingConfirmResponse,
    PairingStatusResponse,
)

def test_init_request_validates_url():
    r = PairingInitRequest(partner_url="https://b.example/")
    assert r.partner_url == "https://b.example/"

def test_accept_validates_code():
    import pytest
    with pytest.raises(ValueError):
        PairingAcceptRequest(master_url="https://a/", code="abc")
    with pytest.raises(ValueError):
        PairingAcceptRequest(master_url="https://a/", code="12345")
    PairingAcceptRequest(master_url="https://a/", code="1234")

def test_confirm_response_payload_shape():
    PairingConfirmResponse(
        master_host="a.example", master_port=5432,
        replication_user="rep_x", replication_password="abc",
        application_name="app_x",
    )
```

- [ ] **Step 2 : Implémenter schemas backend**

```python
# backend/app/schemas/pairing.py
from __future__ import annotations
import re
from pydantic import BaseModel, Field, field_validator
from uuid import UUID


class PairingInitRequest(BaseModel):
    partner_url: str = Field(..., min_length=1)


class PairingInitResponse(BaseModel):
    session_id: UUID
    code: str
    expires_in_seconds: int


class PairingAcceptRequest(BaseModel):
    master_url: str = Field(..., min_length=1)
    code: str

    @field_validator("code")
    @classmethod
    def _check_code(cls, v: str) -> str:
        if not re.fullmatch(r"\d{4}", v):
            raise ValueError("code_must_be_4_digits")
        return v


class PairingConfirmRequest(BaseModel):
    code: str
    standby_url: str

    @field_validator("code")
    @classmethod
    def _check_code(cls, v: str) -> str:
        if not re.fullmatch(r"\d{4}", v):
            raise ValueError("code_must_be_4_digits")
        return v


class PairingConfirmResponse(BaseModel):
    master_host: str
    master_port: int
    replication_user: str
    replication_password: str
    application_name: str


class PairingStatusResponse(BaseModel):
    session_id: UUID
    role: str
    status: str
    partner_url: str | None
    current_step_idx: int
    expires_at: str
```

- [ ] **Step 3 : Schemas frontend**

```typescript
// frontend/src/schemas/pairing.ts
import { z } from 'zod'

export const PairingInitResponseSchema = z.object({
  session_id: z.string().uuid(),
  code: z.string().regex(/^\d{4}$/),
  expires_in_seconds: z.number().int().positive(),
})
export type PairingInitResponse = z.infer<typeof PairingInitResponseSchema>

export const PairingStatusSchema = z.object({
  session_id: z.string().uuid(),
  role: z.enum(['master', 'standby']),
  status: z.enum(['pending', 'confirmed', 'wizard', 'completed', 'expired', 'failed']),
  partner_url: z.string().nullable(),
  current_step_idx: z.number().int().min(0),
  expires_at: z.string(),
})
export type PairingStatus = z.infer<typeof PairingStatusSchema>

export const PairingStepSchema = z.object({
  idx: z.number().int().min(0),
  title: z.string(),
  command: z.string(),
  hint: z.string().optional(),
})
export type PairingStep = z.infer<typeof PairingStepSchema>

export const PairingStepsResponseSchema = z.object({
  steps: z.array(PairingStepSchema),
  current_step_idx: z.number().int().min(0),
  status: z.string(),
})
export type PairingStepsResponse = z.infer<typeof PairingStepsResponseSchema>
```

- [ ] **Step 4 : Tests verts** : `uv run pytest -xvs backend/tests/test_pairing_schemas.py` + `npx tsc --noEmit`

- [ ] **Step 5 : Commit**

```bash
git add backend/app/schemas/pairing.py backend/tests/test_pairing_schemas.py \
        frontend/src/schemas/pairing.ts
git commit -m "feat(pairing): schemas DTO appairage (LOT 2)"
```

---

### Task 2.2 : Service `pairing` — init côté master

**Files :**
- Create : `backend/app/services/pairing.py`
- Test : `backend/tests/test_pairing_service.py`

- [ ] **Step 1 : Tests init**

```python
# backend/tests/test_pairing_service.py
import pytest
from uuid import uuid4
from app.db.pool import get_pool
from app.services import pairing as svc

@pytest.mark.asyncio
async def test_init_master_creates_session_with_4digit_code():
    pool = await get_pool()
    async with pool.acquire() as conn:
        sess = await svc.init_master(conn, partner_url="https://b/", actor_user_id=None)
    assert len(sess.code) == 4 and sess.code.isdigit()
    assert sess.session_id is not None

@pytest.mark.asyncio
async def test_init_master_unique_code_among_active():
    """Si un code est déjà en circulation, on en regénère un autre."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        codes = set()
        for _ in range(20):
            sess = await svc.init_master(conn, partner_url="https://b/", actor_user_id=None)
            codes.add(sess.code)
    assert len(codes) >= 15  # collision possible mais rare sur 10000 valeurs
```

- [ ] **Step 2 : Implémenter `init_master`**

```python
# backend/app/services/pairing.py
"""Service appairage entre 2 instances Harpocrate (LOT 2)."""
from __future__ import annotations
import secrets
from dataclasses import dataclass
from uuid import UUID
import asyncpg
import httpx
import structlog

from app.core.config import settings
from app.db.repositories import pairing_sessions as repo
from app.services import audit_log as audit_svc
from app.services import streaming_replication as streaming_svc

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class InitResult:
    session_id: UUID
    code: str
    expires_in_seconds: int


def _generate_code() -> str:
    return f"{secrets.randbelow(10000):04d}"


async def _generate_unique_code(conn: asyncpg.Connection) -> str:
    for _ in range(20):
        c = _generate_code()
        existing = await repo.get_active_by_code(conn, c)
        if existing is None:
            return c
    raise RuntimeError("could_not_generate_unique_code")


async def init_master(
    conn: asyncpg.Connection, *, partner_url: str, actor_user_id: UUID | None,
) -> InitResult:
    code = await _generate_unique_code(conn)
    sid = await repo.create(
        conn, role="master", code=code, partner_url=partner_url,
        ttl_seconds=settings.pairing_code_ttl_seconds, actor_user_id=actor_user_id,
    )
    await audit_svc.write_event(
        event_type="pairing.master_init",
        actor_user_id=actor_user_id,
        metadata={"partner_url": partner_url, "code_prefix": code[:2] + "**"},
    )
    return InitResult(session_id=sid, code=code,
                      expires_in_seconds=settings.pairing_code_ttl_seconds)
```

- [ ] **Step 3 : Tests verts** : `uv run pytest -xvs backend/tests/test_pairing_service.py::test_init_master_creates_session_with_4digit_code`

- [ ] **Step 4 : Commit**

```bash
git add backend/app/services/pairing.py backend/tests/test_pairing_service.py
git commit -m "feat(pairing): service init_master + génération code 4 chiffres (LOT 2)"
```

---

### Task 2.3 : Service `pairing` — confirm côté master + accept côté standby

**Files :**
- Modify : `backend/app/services/pairing.py`
- Modify : `backend/tests/test_pairing_service.py`

**Flow** :
- B reçoit URL_A + code → appelle `accept_standby(code, master_url=A_URL)`. Le service POST `{A_URL}/v1/admin/replication/pairing/confirm` avec `{code, standby_url=self_url}`.
- A reçoit ce POST → `confirm_master(code, standby_url)` :
  1. Trouve la session active par code (rate-limit attempts ≤ 3)
  2. Si OK : crée une replication node via `streaming_svc.add_node(label=standby_url)` → récupère le bundle (replication_user, replication_password, application_name)
  3. Marque session `confirmed`, payload contient les creds + master_host/port (via `streaming_svc.get_postgres_info`)
  4. Retourne le payload à B
- B reçoit la réponse → crée sa propre session locale role=standby, payload = ce qui a été reçu, status `wizard` (prêt pour le wizard)

- [ ] **Step 1 : Tests confirm + accept**

```python
# backend/tests/test_pairing_service.py — append
@pytest.mark.asyncio
async def test_confirm_master_with_valid_code_returns_payload(monkeypatch):
    pool = await get_pool()
    async with pool.acquire() as conn:
        sess = await svc.init_master(conn, partner_url="https://b/", actor_user_id=None)

        # mock streaming_svc.add_node + get_postgres_info
        async def fake_add_node(c, label):
            return {
                "id": uuid4(), "label": label,
                "replication_user": "rep_test",
                "replication_password": "pwd_test",
                "application_name": "app_test",
            }
        async def fake_postgres_info(c):
            return type("PI", (), {"server_addr": "10.0.0.1",
                                     "settings": {"port": "5432"}})()
        monkeypatch.setattr(svc.streaming_svc, "add_node", fake_add_node)
        monkeypatch.setattr(svc.streaming_svc, "get_postgres_info", fake_postgres_info)

        payload = await svc.confirm_master(conn, code=sess.code,
                                            standby_url="https://b.example/",
                                            actor_user_id=None)
    assert payload["master_host"] == "10.0.0.1"
    assert payload["master_port"] == 5432
    assert payload["replication_user"] == "rep_test"
    assert payload["replication_password"] == "pwd_test"

@pytest.mark.asyncio
async def test_confirm_master_with_wrong_code_raises():
    pool = await get_pool()
    async with pool.acquire() as conn:
        with pytest.raises(svc.InvalidCodeError):
            await svc.confirm_master(conn, code="0000",
                                      standby_url="https://b/", actor_user_id=None)

@pytest.mark.asyncio
async def test_confirm_master_rate_limits_attempts(monkeypatch):
    pool = await get_pool()
    async with pool.acquire() as conn:
        sess = await svc.init_master(conn, partner_url="https://b/", actor_user_id=None)
        # 3 essais sur mauvais code échouent en InvalidCodeError;
        # le bon code après 3 essais sur la même session échoue en TooManyAttemptsError.
        # On simule en utilisant le bon code mais en incrémentant attempts directement.
        from app.db.repositories import pairing_sessions as r
        await r.increment_attempts(conn, sess.session_id)
        await r.increment_attempts(conn, sess.session_id)
        await r.increment_attempts(conn, sess.session_id)
        with pytest.raises(svc.TooManyAttemptsError):
            await svc.confirm_master(conn, code=sess.code,
                                      standby_url="https://b/", actor_user_id=None)
```

- [ ] **Step 2 : Implémenter `confirm_master` + `accept_standby`**

```python
# Append à backend/app/services/pairing.py

class InvalidCodeError(Exception):
    pass

class TooManyAttemptsError(Exception):
    pass

class PairingAcceptError(Exception):
    pass


async def confirm_master(
    conn: asyncpg.Connection, *, code: str, standby_url: str,
    actor_user_id: UUID | None,
) -> dict:
    """A reçoit l'appel de B avec le code → crée le node standby + retourne le payload."""
    sess = await repo.get_active_by_code(conn, code)
    if sess is None:
        raise InvalidCodeError("invalid_or_expired_code")

    if sess["attempts"] >= settings.pairing_max_attempts:
        await repo.set_status(conn, sess["id"], "failed")
        await audit_svc.write_event(
            event_type="pairing.failed",
            actor_user_id=actor_user_id,
            metadata={"role": "master", "reason": "too_many_attempts"},
        )
        raise TooManyAttemptsError("too_many_attempts")

    bundle = await streaming_svc.add_node(conn, label=standby_url)
    pg_info = await streaming_svc.get_postgres_info(conn)
    pg_port_str = pg_info.settings.get("port", "5432")
    payload = {
        "master_host": pg_info.server_addr or "127.0.0.1",
        "master_port": int(pg_port_str),
        "replication_user": bundle["replication_user"],
        "replication_password": bundle["replication_password"],
        "application_name": bundle["application_name"],
        "node_id": str(bundle["id"]),
    }
    await repo.set_payload(conn, sess["id"], payload)
    await repo.set_status(conn, sess["id"], "confirmed")
    return payload


async def accept_standby(
    conn: asyncpg.Connection, *, master_url: str, code: str, self_url: str,
    actor_user_id: UUID | None,
) -> UUID:
    """B reçoit le code + URL master → contacte A et stocke le payload localement."""
    url = master_url.rstrip("/") + "/v1/admin/replication/pairing/confirm"
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=True) as client:
            resp = await client.post(url, json={"code": code, "standby_url": self_url})
    except httpx.HTTPError as e:
        raise PairingAcceptError(f"network_error:{e}")

    if resp.status_code == 401 or resp.status_code == 403:
        raise InvalidCodeError("invalid_or_expired_code")
    if resp.status_code == 429:
        raise TooManyAttemptsError("too_many_attempts")
    if resp.status_code != 200:
        raise PairingAcceptError(f"unexpected_status:{resp.status_code}")

    payload = resp.json()
    sid = await repo.create(
        conn, role="standby", code=code, partner_url=master_url,
        ttl_seconds=settings.pairing_code_ttl_seconds, actor_user_id=actor_user_id,
    )
    await repo.set_payload(conn, sid, payload)
    await repo.set_status(conn, sid, "wizard")
    await audit_svc.write_event(
        event_type="pairing.standby_accepted",
        actor_user_id=actor_user_id,
        metadata={"master_url": master_url, "session_id": str(sid)},
    )
    return sid
```

- [ ] **Step 3 : Tests verts** : `uv run pytest -xvs backend/tests/test_pairing_service.py`

- [ ] **Step 4 : Commit**

```bash
git add backend/app/services/pairing.py backend/tests/test_pairing_service.py
git commit -m "feat(pairing): confirm_master + accept_standby avec rate-limit (LOT 2)"
```

---

### Task 2.4 : Endpoints REST appairage

**Files :**
- Create : `backend/app/api/v1/admin_replication_pairing.py`
- Modify : `backend/app/main.py`
- Test : `backend/tests/test_pairing_api.py`

- [ ] **Step 1 : Tests endpoints**

```python
# backend/tests/test_pairing_api.py
from unittest.mock import patch, AsyncMock
import pytest
from app.tests.fixtures import client, admin_jwt  # supposés exister

def test_init_returns_code(client, admin_jwt):
    r = client.post("/v1/admin/replication/pairing/init",
                     json={"partner_url": "https://b/"},
                     headers={"Authorization": f"Bearer {admin_jwt}"})
    assert r.status_code == 200
    body = r.json()
    assert "code" in body and len(body["code"]) == 4
    assert "session_id" in body

def test_init_requires_admin(client):
    r = client.post("/v1/admin/replication/pairing/init",
                     json={"partner_url": "https://b/"})
    assert r.status_code == 401

def test_confirm_no_auth_required(client, admin_jwt):
    """confirm est appelé inter-instances : on n'exige PAS un JWT admin
    (sinon B devrait stocker un JWT admin de A, ce qu'on veut éviter).
    Le code 4 chiffres + TTL court est l'authentification."""
    init = client.post("/v1/admin/replication/pairing/init",
                        json={"partner_url": "https://b/"},
                        headers={"Authorization": f"Bearer {admin_jwt}"})
    code = init.json()["code"]
    with patch("app.services.pairing.streaming_svc.add_node",
                AsyncMock(return_value={"id": "uuid", "label": "https://b/",
                                          "replication_user": "u",
                                          "replication_password": "p",
                                          "application_name": "a"})), \
          patch("app.services.pairing.streaming_svc.get_postgres_info",
                AsyncMock(return_value=type("PI", (), {
                    "server_addr": "1.2.3.4",
                    "settings": {"port": "5432"},
                })())):
        r = client.post("/v1/admin/replication/pairing/confirm",
                         json={"code": code, "standby_url": "https://b/"})
    assert r.status_code == 200
    assert r.json()["master_host"] == "1.2.3.4"
```

- [ ] **Step 2 : Implémenter le router**

```python
# backend/app/api/v1/admin_replication_pairing.py
"""Endpoints REST appairage maître/standby (LOT 2)."""
from __future__ import annotations
from uuid import UUID
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from app.core.admin_auth import AdminJwt
from app.db.pool import get_pool
from app.db.repositories import pairing_sessions as repo
from app.services import pairing as svc
from app.schemas.pairing import (
    PairingInitRequest, PairingInitResponse,
    PairingConfirmRequest, PairingConfirmResponse,
    PairingAcceptRequest, PairingStatusResponse,
)

router = APIRouter(prefix="/admin/replication/pairing",
                    tags=["admin-replication-pairing"])


@router.post("/init", response_model=PairingInitResponse)
async def init_pairing(req: PairingInitRequest, admin: AdminJwt) -> PairingInitResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await svc.init_master(
            conn, partner_url=req.partner_url, actor_user_id=admin.user_id,
        )
    return PairingInitResponse(
        session_id=result.session_id, code=result.code,
        expires_in_seconds=result.expires_in_seconds,
    )


@router.post("/confirm", response_model=PairingConfirmResponse)
async def confirm_pairing(req: PairingConfirmRequest) -> PairingConfirmResponse:
    """Authentification = code + TTL (pas de JWT). Appelé par B vers A."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            payload = await svc.confirm_master(
                conn, code=req.code, standby_url=req.standby_url, actor_user_id=None,
            )
        except svc.InvalidCodeError:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                  detail={"error": "invalid_or_expired_code"})
        except svc.TooManyAttemptsError:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                                  detail={"error": "too_many_attempts"})
    return PairingConfirmResponse(**payload)


@router.post("/accept")
async def accept_pairing(req: PairingAcceptRequest, admin: AdminJwt) -> JSONResponse:
    """B appelle ça : contacte A avec le code, stocke le payload reçu."""
    from app.core.config import settings
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            sid = await svc.accept_standby(
                conn, master_url=req.master_url, code=req.code,
                self_url=settings.public_url, actor_user_id=admin.user_id,
            )
        except svc.InvalidCodeError:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                  detail={"error": "invalid_or_expired_code"})
        except svc.TooManyAttemptsError:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                                  detail={"error": "too_many_attempts"})
        except svc.PairingAcceptError as e:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                                  detail={"error": str(e)})
    return JSONResponse({"session_id": str(sid)})


@router.get("/{session_id}/status", response_model=PairingStatusResponse)
async def get_status(session_id: UUID, admin: AdminJwt) -> PairingStatusResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        sess = await repo.get(conn, session_id)
    if sess is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"error": "not_found"})
    return PairingStatusResponse(
        session_id=sess["id"], role=sess["role"], status=sess["status"],
        partner_url=sess["partner_url"],
        current_step_idx=sess["current_step_idx"],
        expires_at=sess["expires_at"].isoformat(),
    )
```

- [ ] **Step 3 : Inclure router**

```python
# backend/app/main.py
from app.api.v1 import admin_replication_pairing  # noqa
app.include_router(admin_replication_pairing.router, prefix="/v1")
```

- [ ] **Step 4 : Vérifier qu'un setting `public_url` existe** : `grep public_url backend/app/core/config.py`. Sinon : ajouter `public_url: str = "http://localhost:8000"` (déjà géré par `dev-deploy.sh` côté .env).

- [ ] **Step 5 : Tests verts** : `uv run pytest -xvs backend/tests/test_pairing_api.py`

- [ ] **Step 6 : Commit**

```bash
git add backend/app/api/v1/admin_replication_pairing.py backend/app/main.py
git commit -m "feat(pairing): endpoints REST init/confirm/accept/status (LOT 2)"
```

---

# LOT 3 — Wizard steps (1.5 j)

**Objectif** : générer la liste ordonnée des commandes Postgres à exécuter côté B en standby, avec endpoints pour faire avancer/reculer le curseur.

---

### Task 3.1 : Service `pairing_steps` — génération des commandes

**Files :**
- Create : `backend/app/services/pairing_steps.py`
- Test : `backend/tests/test_pairing_steps.py`

**Liste fixe des étapes pour un standby Postgres 16 dans Docker** :

1. Stop postgres : `docker stop harpocrate-postgres`
2. Sauvegarder le data dir actuel : `sudo mv /var/lib/postgresql/16/data /var/lib/postgresql/16/data.bak.$(date +%s)`
3. pg_basebackup depuis A : `sudo -u postgres pg_basebackup -h <master_host> -p <master_port> -D /var/lib/postgresql/16/data -U <replication_user> -P --slot=<application_name> -R --wal-method=stream` (le mot de passe sera demandé interactivement, OU `PGPASSWORD=<password>` en variable d'env — on va le passer en clair dans la commande affichée car la session SSH est privée à l'admin)
4. Vérifier la présence de `standby.signal` : `sudo -u postgres ls /var/lib/postgresql/16/data/standby.signal`
5. Vérifier `postgresql.auto.conf` : `sudo -u postgres cat /var/lib/postgresql/16/data/postgresql.auto.conf`
6. Démarrer postgres : `docker start harpocrate-postgres`
7. Vérifier le mode standby : `docker exec harpocrate-postgres psql -U postgres -c "SELECT pg_is_in_recovery();"` → attendu `t`
8. Vérifier le streaming : `docker exec harpocrate-postgres psql -U postgres -c "SELECT * FROM pg_stat_wal_receiver;"`

- [ ] **Step 1 : Tests génération**

```python
# backend/tests/test_pairing_steps.py
from app.services.pairing_steps import build_standby_steps

def test_build_standby_steps_includes_all_phases():
    steps = build_standby_steps(
        master_host="1.2.3.4", master_port=5432,
        replication_user="rep_x", replication_password="pwd123",
        application_name="app_x",
    )
    titles = [s.title for s in steps]
    assert any("stop" in t.lower() for t in titles)
    assert any("basebackup" in t.lower() for t in titles)
    assert any("standby.signal" in t.lower() for t in titles)
    assert any("recovery" in t.lower() for t in titles) or any(
        "is_in_recovery" in s.command for s in steps)

def test_basebackup_command_contains_creds():
    steps = build_standby_steps(
        master_host="1.2.3.4", master_port=5432,
        replication_user="rep_x", replication_password="pwd123",
        application_name="app_x",
    )
    bb = next(s for s in steps if "pg_basebackup" in s.command)
    assert "1.2.3.4" in bb.command
    assert "5432" in bb.command
    assert "rep_x" in bb.command
    assert "app_x" in bb.command
    # Le password doit aussi y figurer (PGPASSWORD prefix)
    assert "pwd123" in bb.command

def test_steps_have_unique_indices():
    steps = build_standby_steps(
        master_host="h", master_port=5432, replication_user="u",
        replication_password="p", application_name="a",
    )
    idxs = [s.idx for s in steps]
    assert idxs == list(range(len(steps)))
```

- [ ] **Step 2 : Implémenter `build_standby_steps`**

```python
# backend/app/services/pairing_steps.py
"""Génération de la liste ordonnée des commandes pour transformer un host en
standby Postgres d'un master donné (LOT 3).

Les commandes sont AFFICHÉES à l'admin pour copier-coller dans son SSH.
Harpocrate n'exécute rien lui-même.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class WizardStep:
    idx: int
    title: str
    command: str
    hint: str = ""


def build_standby_steps(
    *, master_host: str, master_port: int,
    replication_user: str, replication_password: str,
    application_name: str,
    container_name: str = "harpocrate-postgres",
    pg_data_dir: str = "/var/lib/postgresql/16/data",
) -> list[WizardStep]:
    bb_cmd = (
        f"PGPASSWORD='{replication_password}' "
        f"sudo -E -u postgres pg_basebackup "
        f"-h {master_host} -p {master_port} "
        f"-D {pg_data_dir} -U {replication_user} "
        f"-P --slot={application_name} -R --wal-method=stream"
    )
    return [
        WizardStep(0, "Arrêter le conteneur Postgres local",
                    f"docker stop {container_name}",
                    "Le conteneur doit être stoppé avant de remplacer le data dir."),
        WizardStep(1, "Sauvegarder le data dir actuel",
                    f"sudo mv {pg_data_dir} {pg_data_dir}.bak.$(date +%s)",
                    "On garde l'ancien data dir au cas où — à supprimer plus tard."),
        WizardStep(2, "Lancer pg_basebackup depuis le master",
                    bb_cmd,
                    "Cette étape peut prendre plusieurs minutes selon la taille de la base."),
        WizardStep(3, "Vérifier la présence de standby.signal",
                    f"sudo -u postgres ls {pg_data_dir}/standby.signal",
                    "Doit afficher le chemin complet — sinon pg_basebackup -R a échoué."),
        WizardStep(4, "Vérifier postgresql.auto.conf",
                    f"sudo -u postgres cat {pg_data_dir}/postgresql.auto.conf",
                    "Doit contenir une ligne primary_conninfo=… avec le bon host/user."),
        WizardStep(5, "Démarrer le conteneur Postgres",
                    f"docker start {container_name}",
                    "Démarre Postgres en mode standby."),
        WizardStep(6, "Vérifier le mode recovery",
                    f"docker exec {container_name} psql -U postgres -c 'SELECT pg_is_in_recovery();'",
                    "Attendu : t (true) — l'instance est bien en standby."),
        WizardStep(7, "Vérifier le streaming WAL actif",
                    f"docker exec {container_name} psql -U postgres -c 'SELECT pid, status, sender_host, sender_port FROM pg_stat_wal_receiver;'",
                    "Une ligne avec status='streaming' confirme que le WAL flux depuis A."),
    ]
```

- [ ] **Step 3 : Tests verts + commit**

```bash
uv run pytest -xvs backend/tests/test_pairing_steps.py
git add backend/app/services/pairing_steps.py backend/tests/test_pairing_steps.py
git commit -m "feat(pairing): génération des étapes wizard standby (LOT 3)"
```

---

### Task 3.2 : Endpoints `steps` GET/done/back + service complétion

**Files :**
- Modify : `backend/app/api/v1/admin_replication_pairing.py`
- Modify : `backend/app/services/pairing.py`
- Modify : `backend/tests/test_pairing_api.py`

- [ ] **Step 1 : Tests endpoints**

```python
# backend/tests/test_pairing_api.py — append
def test_get_steps_returns_list(client, admin_jwt, pairing_session_in_wizard):
    sid = pairing_session_in_wizard
    r = client.get(f"/v1/admin/replication/pairing/{sid}/steps",
                    headers={"Authorization": f"Bearer {admin_jwt}"})
    assert r.status_code == 200
    body = r.json()
    assert len(body["steps"]) == 8
    assert body["current_step_idx"] == 0

def test_done_advances_index(client, admin_jwt, pairing_session_in_wizard):
    sid = pairing_session_in_wizard
    r = client.post(f"/v1/admin/replication/pairing/{sid}/steps/0/done",
                     headers={"Authorization": f"Bearer {admin_jwt}"})
    assert r.status_code == 200
    assert r.json()["current_step_idx"] == 1

def test_back_decrements_index(client, admin_jwt, pairing_session_in_wizard):
    sid = pairing_session_in_wizard
    client.post(f"/v1/admin/replication/pairing/{sid}/steps/0/done",
                 headers={"Authorization": f"Bearer {admin_jwt}"})
    client.post(f"/v1/admin/replication/pairing/{sid}/steps/1/done",
                 headers={"Authorization": f"Bearer {admin_jwt}"})
    r = client.post(f"/v1/admin/replication/pairing/{sid}/steps/2/back",
                     headers={"Authorization": f"Bearer {admin_jwt}"})
    assert r.status_code == 200
    assert r.json()["current_step_idx"] == 1

def test_done_on_last_step_marks_completed(client, admin_jwt, pairing_session_in_wizard):
    sid = pairing_session_in_wizard
    for i in range(8):
        r = client.post(f"/v1/admin/replication/pairing/{sid}/steps/{i}/done",
                         headers={"Authorization": f"Bearer {admin_jwt}"})
    body = client.get(f"/v1/admin/replication/pairing/{sid}/status",
                       headers={"Authorization": f"Bearer {admin_jwt}"}).json()
    assert body["status"] == "completed"
```

Fixture à créer dans `backend/tests/conftest.py` :
```python
@pytest.fixture
async def pairing_session_in_wizard(admin_jwt, client):
    # Crée une session standby directement en DB en status 'wizard'
    from app.db.pool import get_pool
    from app.db.repositories import pairing_sessions as repo
    pool = await get_pool()
    async with pool.acquire() as conn:
        sid = await repo.create(conn, role="standby", code="0000",
                                 partner_url="https://a/", ttl_seconds=600,
                                 actor_user_id=None)
        await repo.set_payload(conn, sid, {
            "master_host": "1.2.3.4", "master_port": 5432,
            "replication_user": "rep", "replication_password": "pwd",
            "application_name": "app",
        })
        await repo.set_status(conn, sid, "wizard")
    return sid
```

- [ ] **Step 2 : Service complétion + endpoints**

Append à `backend/app/services/pairing.py` :
```python
async def advance_step(
    conn: asyncpg.Connection, *, session_id: UUID, current_idx: int, total: int,
    actor_user_id: UUID | None,
) -> int:
    """Marque l'étape comme done et avance le curseur. Si on dépasse, status=completed."""
    sess = await repo.get(conn, session_id)
    if sess is None:
        raise InvalidCodeError("session_not_found")
    if sess["current_step_idx"] != current_idx:
        raise InvalidCodeError("step_mismatch")
    new_idx = current_idx + 1
    if new_idx >= total:
        await repo.set_status(conn, session_id, "completed")
        await audit_svc.write_event(
            event_type="pairing.completed",
            actor_user_id=actor_user_id,
            metadata={"role": sess["role"], "partner_url": sess["partner_url"]},
        )
        # Hook : marquer cette instance comme is_standby_of (LOT 5)
        if sess["role"] == "standby":
            await streaming_svc.set_standby_of(conn, master_url=sess["partner_url"])
    await repo.set_step_idx(conn, session_id, new_idx)
    return new_idx


async def back_step(
    conn: asyncpg.Connection, *, session_id: UUID, current_idx: int,
) -> int:
    sess = await repo.get(conn, session_id)
    if sess is None:
        raise InvalidCodeError("session_not_found")
    if current_idx <= 0:
        return 0
    if sess["current_step_idx"] != current_idx:
        raise InvalidCodeError("step_mismatch")
    new_idx = current_idx - 1
    await repo.set_step_idx(conn, session_id, new_idx)
    return new_idx
```

Append à `backend/app/api/v1/admin_replication_pairing.py` :
```python
from app.services import pairing_steps as steps_svc

@router.get("/{session_id}/steps")
async def get_steps(session_id: UUID, admin: AdminJwt) -> JSONResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        sess = await repo.get(conn, session_id)
    if sess is None or sess["role"] != "standby":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"error": "not_found"})
    p = sess["payload"]
    steps = steps_svc.build_standby_steps(
        master_host=p["master_host"], master_port=p["master_port"],
        replication_user=p["replication_user"],
        replication_password=p["replication_password"],
        application_name=p["application_name"],
    )
    return JSONResponse({
        "steps": [{"idx": s.idx, "title": s.title, "command": s.command, "hint": s.hint}
                  for s in steps],
        "current_step_idx": sess["current_step_idx"],
        "status": sess["status"],
    })


@router.post("/{session_id}/steps/{idx}/done")
async def step_done(session_id: UUID, idx: int, admin: AdminJwt) -> JSONResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            new_idx = await svc.advance_step(
                conn, session_id=session_id, current_idx=idx, total=8,
                actor_user_id=admin.user_id,
            )
        except svc.InvalidCodeError as e:
            raise HTTPException(status.HTTP_409_CONFLICT, detail={"error": str(e)})
    return JSONResponse({"current_step_idx": new_idx})


@router.post("/{session_id}/steps/{idx}/back")
async def step_back(session_id: UUID, idx: int, admin: AdminJwt) -> JSONResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            new_idx = await svc.back_step(conn, session_id=session_id, current_idx=idx)
        except svc.InvalidCodeError as e:
            raise HTTPException(status.HTTP_409_CONFLICT, detail={"error": str(e)})
    return JSONResponse({"current_step_idx": new_idx})
```

- [ ] **Step 3 : Stub `streaming_svc.set_standby_of` (sera complété au LOT 5)** :
```python
# backend/app/services/streaming_replication.py — ajouter en fin de fichier
async def set_standby_of(conn, *, master_url: str | None) -> None:
    """Marque/démarque cette instance comme asservie à un master (LOT 5).
    Stub LOT 3 : juste set la clé system_metadata."""
    from app.db.repositories import system_metadata as meta_repo
    await meta_repo.set_value(conn, "replication.is_standby_of", master_url)
```

- [ ] **Step 4 : Tests verts** : `uv run pytest -xvs backend/tests/test_pairing_api.py`

- [ ] **Step 5 : Commit**

```bash
git add backend/app/api/v1/admin_replication_pairing.py \
        backend/app/services/pairing.py \
        backend/app/services/streaming_replication.py \
        backend/tests/test_pairing_api.py backend/tests/conftest.py
git commit -m "feat(pairing): endpoints steps + advance/back + hook is_standby_of (LOT 3)"
```

---

# LOT 4 — UI complète d'appairage (3 j)

**Objectif** : intégrer côté A (modale init + display code) et côté B (saisie code + page wizard 2-colonnes terminal/stepper).

---

### Task 4.1 : Helpers `adminApi.ts` pour pairing

**Files :**
- Modify : `frontend/src/lib/adminApi.ts`

- [ ] **Step 1 : Ajouter les helpers**

```typescript
// Append à frontend/src/lib/adminApi.ts
import {
  PairingInitResponseSchema, type PairingInitResponse,
  PairingStatusSchema, type PairingStatus,
  PairingStepsResponseSchema, type PairingStepsResponse,
} from '@/schemas/pairing'

export async function initPairing(partnerUrl: string): Promise<PairingInitResponse> {
  const r = await apiClient.post('/v1/admin/replication/pairing/init',
                                  { partner_url: partnerUrl })
  return PairingInitResponseSchema.parse(r)
}

export async function acceptPairing(masterUrl: string, code: string): Promise<{session_id: string}> {
  return apiClient.post('/v1/admin/replication/pairing/accept',
                         { master_url: masterUrl, code })
}

export async function getPairingStatus(sid: string): Promise<PairingStatus> {
  const r = await apiClient.get(`/v1/admin/replication/pairing/${sid}/status`)
  return PairingStatusSchema.parse(r)
}

export async function getPairingSteps(sid: string): Promise<PairingStepsResponse> {
  const r = await apiClient.get(`/v1/admin/replication/pairing/${sid}/steps`)
  return PairingStepsResponseSchema.parse(r)
}

export async function markStepDone(sid: string, idx: number): Promise<{current_step_idx: number}> {
  return apiClient.post(`/v1/admin/replication/pairing/${sid}/steps/${idx}/done`, {})
}

export async function markStepBack(sid: string, idx: number): Promise<{current_step_idx: number}> {
  return apiClient.post(`/v1/admin/replication/pairing/${sid}/steps/${idx}/back`, {})
}
```

- [ ] **Step 2 : Build TS check** : `npx tsc --noEmit`

- [ ] **Step 3 : Commit**

```bash
git add frontend/src/lib/adminApi.ts
git commit -m "feat(frontend): helpers adminApi pour pairing (LOT 4)"
```

---

### Task 4.2 : Composant `AddStandbyModal` côté A

**Files :**
- Create : `frontend/src/components/AddStandbyModal.tsx`
- Modify : `frontend/src/components/StreamingNodesPanel.tsx`
- Modify : `frontend/src/i18n/fr.json` + `en.json`

- [ ] **Step 1 : i18n**

Ajouter dans `fr.json` sous `admin.replication` :
```json
"pairing": {
  "addStandby": "Ajouter un standby (assistant)",
  "modal": {
    "title": "Appairer un nouveau standby",
    "step1": "Étape 1 — URL du standby",
    "step1Hint": "Saisis l'URL publique de l'instance Harpocrate qui deviendra standby de celle-ci.",
    "partnerUrl": "URL du standby",
    "generate": "Générer le code d'appairage",
    "step2": "Étape 2 — Code à transmettre",
    "step2Hint": "Communique ce code à l'admin de l'instance standby. Il expire dans {{minutes}} minutes.",
    "code": "Code",
    "waiting": "En attente de l'autre instance…",
    "completed": "Appairage terminé. Le standby va répliquer.",
    "expired": "Code expiré. Recommence l'opération.",
    "failed": "L'appairage a échoué."
  },
  "becomeStandby": {
    "title": "Devenir standby d'une autre instance",
    "subtitle": "Saisis l'URL du master Harpocrate et le code 4 chiffres qu'il t'a transmis.",
    "masterUrl": "URL du master",
    "code": "Code 4 chiffres",
    "submit": "Démarrer l'appairage"
  },
  "wizard": {
    "title": "Assistant d'appairage standby",
    "subtitleA": "Connecte-toi en SSH à la machine qui héberge ce conteneur Postgres.",
    "subtitleB": "Une fois connecté, suis les étapes ci-contre.",
    "stepProgress": "Étape {{current}} sur {{total}}",
    "command": "Commande à exécuter",
    "copy": "Copier",
    "copied": "Copié",
    "markDone": "Étape exécutée → suivant",
    "back": "← Étape précédente",
    "completed": "Appairage terminé !",
    "completedSubtitle": "Cette instance est maintenant standby de {{master}}.",
    "abort": "Abandonner"
  }
}
```

- [ ] **Step 2 : Composant**

```tsx
// frontend/src/components/AddStandbyModal.tsx
import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Modal, Stack, TextInput, Button, Group, Text, Code, Alert } from '@mantine/core'
import { useTranslation } from 'react-i18next'
import { initPairing, getPairingStatus } from '@/lib/adminApi'
import type { PairingInitResponse, PairingStatus } from '@/schemas/pairing'

interface Props { opened: boolean; onClose: () => void }

export function AddStandbyModal({ opened, onClose }: Props) {
  const { t } = useTranslation()
  const [partnerUrl, setPartnerUrl] = useState('')
  const [init, setInit] = useState<PairingInitResponse | null>(null)

  const initMut = useMutation({
    mutationFn: () => initPairing(partnerUrl),
    onSuccess: (r) => setInit(r),
  })

  const statusQuery = useQuery({
    queryKey: ['pairing-status', init?.session_id],
    queryFn: () => getPairingStatus(init!.session_id),
    enabled: !!init,
    refetchInterval: 3000,
  })

  function reset() { setInit(null); setPartnerUrl(''); onClose() }

  const status: PairingStatus | undefined = statusQuery.data

  return (
    <Modal opened={opened} onClose={reset} size="lg" title={t('admin.replication.pairing.modal.title')}>
      {!init ? (
        <Stack>
          <Text size="sm" c="dimmed">{t('admin.replication.pairing.modal.step1Hint')}</Text>
          <TextInput label={t('admin.replication.pairing.modal.partnerUrl')}
                      value={partnerUrl}
                      onChange={(e) => setPartnerUrl(e.currentTarget.value)}
                      placeholder="https://harpo-2.example/" />
          <Group justify="flex-end">
            <Button variant="default" onClick={reset}>{t('common.cancel')}</Button>
            <Button onClick={() => initMut.mutate()} loading={initMut.isPending}
                    disabled={!partnerUrl}>
              {t('admin.replication.pairing.modal.generate')}
            </Button>
          </Group>
        </Stack>
      ) : (
        <Stack>
          <Text size="sm" c="dimmed">
            {t('admin.replication.pairing.modal.step2Hint',
                { minutes: Math.round(init.expires_in_seconds / 60) })}
          </Text>
          <Group justify="center">
            <Code style={{ fontSize: '2.5rem', letterSpacing: '0.5rem',
                            padding: '1rem 2rem' }}>{init.code}</Code>
          </Group>
          {status?.status === 'pending' && (
            <Alert color="blue">{t('admin.replication.pairing.modal.waiting')}</Alert>
          )}
          {status?.status === 'confirmed' && (
            <Alert color="blue">{t('admin.replication.pairing.modal.waiting')}</Alert>
          )}
          {status?.status === 'wizard' && (
            <Alert color="blue">{t('admin.replication.pairing.modal.waiting')}</Alert>
          )}
          {status?.status === 'completed' && (
            <Alert color="green">{t('admin.replication.pairing.modal.completed')}</Alert>
          )}
          {status?.status === 'expired' && (
            <Alert color="orange">{t('admin.replication.pairing.modal.expired')}</Alert>
          )}
          {status?.status === 'failed' && (
            <Alert color="red">{t('admin.replication.pairing.modal.failed')}</Alert>
          )}
          <Group justify="flex-end">
            <Button onClick={reset}>{t('common.close')}</Button>
          </Group>
        </Stack>
      )}
    </Modal>
  )
}
```

- [ ] **Step 3 : Bouton dans `StreamingNodesPanel`**

```tsx
// frontend/src/components/StreamingNodesPanel.tsx — dans le header de la card
import { AddStandbyModal } from './AddStandbyModal'
// ... dans le composant :
const [pairingOpen, setPairingOpen] = useState(false)
// ... dans le JSX, à côté de "Ajouter manuellement" :
<Button onClick={() => setPairingOpen(true)}>
  {t('admin.replication.pairing.addStandby')}
</Button>
<AddStandbyModal opened={pairingOpen} onClose={() => setPairingOpen(false)} />
```

- [ ] **Step 4 : Vérifier visuel** : `npm run dev`, ouvrir page Réplication, cliquer sur le bouton, vérifier le flow init → display code

- [ ] **Step 5 : Commit**

```bash
git add frontend/src/components/AddStandbyModal.tsx \
        frontend/src/components/StreamingNodesPanel.tsx \
        frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(pairing): modale AddStandby côté master + bouton dans StreamingNodesPanel (LOT 4)"
```

---

### Task 4.3 : Page `BecomeStandbyPage` côté B

**Files :**
- Create : `frontend/src/pages/BecomeStandbyPage.tsx`
- Modify : `frontend/src/App.tsx` (route)
- Modify : `frontend/src/pages/AdminReplicationPage.tsx` (lien "Devenir standby")

- [ ] **Step 1 : Page**

```tsx
// frontend/src/pages/BecomeStandbyPage.tsx
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { Stack, Title, Text, TextInput, PinInput, Group, Button, Card, Alert } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useTranslation } from 'react-i18next'
import { acceptPairing } from '@/lib/adminApi'
import { ApiError } from '@/lib/api-client'

export function BecomeStandbyPage() {
  const { t } = useTranslation()
  const nav = useNavigate()
  const [masterUrl, setMasterUrl] = useState('')
  const [code, setCode] = useState('')

  const mut = useMutation({
    mutationFn: () => acceptPairing(masterUrl, code),
    onSuccess: (r) => nav(`/admin/pairing/${r.session_id}`),
    onError: (e) => notifications.show({
      color: 'red', title: t('common.error'),
      message: e instanceof ApiError ? e.message : String(e),
    }),
  })

  return (
    <Stack maw={600} mx="auto" mt="xl">
      <Title order={2}>{t('admin.replication.pairing.becomeStandby.title')}</Title>
      <Text c="dimmed">{t('admin.replication.pairing.becomeStandby.subtitle')}</Text>
      <Card withBorder>
        <Stack>
          <TextInput
            label={t('admin.replication.pairing.becomeStandby.masterUrl')}
            placeholder="https://harpo-1.example/"
            value={masterUrl}
            onChange={(e) => setMasterUrl(e.currentTarget.value)}
          />
          <Stack gap="xs">
            <Text size="sm" fw={500}>
              {t('admin.replication.pairing.becomeStandby.code')}
            </Text>
            <PinInput length={4} type="number" value={code} onChange={setCode} />
          </Stack>
          <Group justify="flex-end">
            <Button loading={mut.isPending}
                    disabled={!masterUrl || code.length !== 4}
                    onClick={() => mut.mutate()}>
              {t('admin.replication.pairing.becomeStandby.submit')}
            </Button>
          </Group>
        </Stack>
      </Card>
    </Stack>
  )
}
```

- [ ] **Step 2 : Route dans `App.tsx`**

```tsx
// Dans App.tsx, dans le block <Route element={<Layout/>}>
<Route path="/admin/become-standby" element={<BecomeStandbyPage />} />
<Route path="/admin/pairing/:sessionId" element={<PairingWizardPage />} />
```

- [ ] **Step 3 : Lien "Devenir standby" sur `AdminReplicationPage.tsx`**

```tsx
// Ajouter dans AdminReplicationPage, à côté du Title :
import { Link } from 'react-router-dom'
// ...
<Group justify="space-between">
  <Title order={2}>{t('admin.replication.title')}</Title>
  <Button component={Link} to="/admin/become-standby" variant="light">
    {t('admin.replication.pairing.becomeStandby.title')}
  </Button>
</Group>
```

- [ ] **Step 4 : Build TS check + commit**

```bash
npx tsc --noEmit
git add frontend/src/pages/BecomeStandbyPage.tsx frontend/src/App.tsx \
        frontend/src/pages/AdminReplicationPage.tsx
git commit -m "feat(pairing): page BecomeStandby + route + lien depuis Réplication (LOT 4)"
```

---

### Task 4.4 : Composant `PairingStepsList`

**Files :**
- Create : `frontend/src/components/PairingStepsList.tsx`
- Create : `frontend/src/tests/pairingStepsList.test.tsx`

- [ ] **Step 1 : Tests**

```tsx
// frontend/src/tests/pairingStepsList.test.tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { PairingStepsList } from '@/components/PairingStepsList'
import { I18nextProvider } from 'react-i18next'
import i18n from '@/i18n'

const STEPS = [
  { idx: 0, title: 'Stop pg', command: 'docker stop x' },
  { idx: 1, title: 'Backup', command: 'pg_basebackup …' },
]

describe('PairingStepsList', () => {
  it('shows the active step command and disables Back at idx 0', () => {
    render(
      <I18nextProvider i18n={i18n}>
        <PairingStepsList steps={STEPS} currentIdx={0}
                           onDone={vi.fn()} onBack={vi.fn()} />
      </I18nextProvider>
    )
    expect(screen.getByText('docker stop x')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /étape précédente/i })).toBeDisabled()
  })

  it('calls onDone with current idx when "suivant" clicked', () => {
    const onDone = vi.fn()
    render(
      <I18nextProvider i18n={i18n}>
        <PairingStepsList steps={STEPS} currentIdx={0}
                           onDone={onDone} onBack={vi.fn()} />
      </I18nextProvider>
    )
    fireEvent.click(screen.getByRole('button', { name: /suivant/i }))
    expect(onDone).toHaveBeenCalledWith(0)
  })

  it('calls onBack with current idx', () => {
    const onBack = vi.fn()
    render(
      <I18nextProvider i18n={i18n}>
        <PairingStepsList steps={STEPS} currentIdx={1}
                           onDone={vi.fn()} onBack={onBack} />
      </I18nextProvider>
    )
    fireEvent.click(screen.getByRole('button', { name: /étape précédente/i }))
    expect(onBack).toHaveBeenCalledWith(1)
  })
})
```

- [ ] **Step 2 : Composant**

```tsx
// frontend/src/components/PairingStepsList.tsx
import { useState } from 'react'
import { Stack, Stepper, Card, Code, Text, Group, Button } from '@mantine/core'
import { useTranslation } from 'react-i18next'
import type { PairingStep } from '@/schemas/pairing'

interface Props {
  steps: PairingStep[]
  currentIdx: number
  onDone: (idx: number) => void
  onBack: (idx: number) => void
  busy?: boolean
}

export function PairingStepsList({ steps, currentIdx, onDone, onBack, busy }: Props) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)
  const active = steps[currentIdx]
  const total = steps.length
  const done = currentIdx >= total

  async function copyCmd() {
    if (!active) return
    try {
      await navigator.clipboard.writeText(active.command)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch { /* clipboard non dispo : sélection manuelle */ }
  }

  return (
    <Stack>
      <Stepper active={currentIdx} size="sm" iconSize={20}>
        {steps.map((s) => <Stepper.Step key={s.idx} label={s.title} />)}
        <Stepper.Completed>
          <Text mt="md" fw={500}>{t('admin.replication.pairing.wizard.completed')}</Text>
        </Stepper.Completed>
      </Stepper>

      {!done && active && (
        <Card withBorder>
          <Stack gap="xs">
            <Text size="sm" c="dimmed">
              {t('admin.replication.pairing.wizard.stepProgress',
                  { current: currentIdx + 1, total })}
            </Text>
            <Text fw={600}>{active.title}</Text>
            {active.hint && <Text size="sm" c="dimmed">{active.hint}</Text>}
            <Text size="sm" fw={500} mt="xs">
              {t('admin.replication.pairing.wizard.command')}
            </Text>
            <Group align="flex-start" wrap="nowrap">
              <Code block style={{ flex: 1, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                {active.command}
              </Code>
              <Button size="xs" variant="light" onClick={() => void copyCmd()}>
                {copied
                  ? t('admin.replication.pairing.wizard.copied')
                  : t('admin.replication.pairing.wizard.copy')}
              </Button>
            </Group>
            <Group justify="space-between" mt="md">
              <Button variant="default" onClick={() => onBack(currentIdx)}
                      disabled={currentIdx === 0 || busy}>
                {t('admin.replication.pairing.wizard.back')}
              </Button>
              <Button onClick={() => onDone(currentIdx)} loading={busy}>
                {t('admin.replication.pairing.wizard.markDone')}
              </Button>
            </Group>
          </Stack>
        </Card>
      )}
    </Stack>
  )
}
```

- [ ] **Step 3 : Tests verts** : `npm test -- pairingStepsList`

- [ ] **Step 4 : Commit**

```bash
git add frontend/src/components/PairingStepsList.tsx \
        frontend/src/tests/pairingStepsList.test.tsx
git commit -m "feat(pairing): composant PairingStepsList + tests (LOT 4)"
```

---

### Task 4.5 : Page `PairingWizardPage` (terminal + stepper)

**Files :**
- Create : `frontend/src/pages/PairingWizardPage.tsx`

- [ ] **Step 1 : Page**

```tsx
// frontend/src/pages/PairingWizardPage.tsx
import { useParams, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Stack, Grid, Title, Text, Card, Loader, Center, Alert, Group, Button } from '@mantine/core'
import { useTranslation } from 'react-i18next'

import { SSHTerminal } from '@/components/SSHTerminal'
import { PairingStepsList } from '@/components/PairingStepsList'
import { getPairingSteps, markStepDone, markStepBack } from '@/lib/adminApi'

export function PairingWizardPage() {
  const { t } = useTranslation()
  const { sessionId } = useParams<{ sessionId: string }>()
  const nav = useNavigate()
  const qc = useQueryClient()

  const stepsQuery = useQuery({
    queryKey: ['pairing-steps', sessionId],
    queryFn: () => getPairingSteps(sessionId!),
    enabled: !!sessionId,
    refetchInterval: 3000,
  })

  const doneMut = useMutation({
    mutationFn: (idx: number) => markStepDone(sessionId!, idx),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['pairing-steps', sessionId] }),
  })
  const backMut = useMutation({
    mutationFn: (idx: number) => markStepBack(sessionId!, idx),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['pairing-steps', sessionId] }),
  })

  if (stepsQuery.isLoading) {
    return <Center mt="xl"><Loader /></Center>
  }
  if (stepsQuery.error) {
    return <Alert color="red">{String(stepsQuery.error)}</Alert>
  }
  const data = stepsQuery.data!

  return (
    <Stack>
      <Group justify="space-between">
        <Stack gap={0}>
          <Title order={2}>{t('admin.replication.pairing.wizard.title')}</Title>
          <Text c="dimmed" size="sm">
            {t('admin.replication.pairing.wizard.subtitleA')}{' '}
            {t('admin.replication.pairing.wizard.subtitleB')}
          </Text>
        </Stack>
        <Button variant="subtle" color="gray" onClick={() => nav('/admin/replication')}>
          {t('admin.replication.pairing.wizard.abort')}
        </Button>
      </Group>

      <Grid gutter="md">
        <Grid.Col span={{ base: 12, md: 7 }}>
          <SSHTerminal />
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 5 }}>
          <Card withBorder>
            <PairingStepsList
              steps={data.steps}
              currentIdx={data.current_step_idx}
              onDone={(i) => doneMut.mutate(i)}
              onBack={(i) => backMut.mutate(i)}
              busy={doneMut.isPending || backMut.isPending}
            />
          </Card>
        </Grid.Col>
      </Grid>
    </Stack>
  )
}
```

- [ ] **Step 2 : Vérifier visuel** : suivre tout le flow dev :
  - Sur instance A : créer le code via `AddStandbyModal`
  - Sur instance B : aller sur `/admin/become-standby`, saisir URL_A + code
  - Atterrir sur `/admin/pairing/<sid>` → voir terminal à gauche, stepper à droite
  - Connecter le terminal SSH à la machine hôte de B
  - Cliquer sur "Copier" puis coller dans le terminal, valider → suivant
  - Faire toutes les étapes jusqu'à completed

- [ ] **Step 3 : Commit**

```bash
git add frontend/src/pages/PairingWizardPage.tsx
git commit -m "feat(pairing): page wizard 2-colonnes terminal + stepper (LOT 4)"
```

---

### Task 4.6 : Test manuel end-to-end LOT 1-4

**Files :** aucun (procédure manuelle)

- [ ] **Step 1 :** Provisionner deux LXC `harpo-test-A` et `harpo-test-B` via `dev-deploy.sh`
- [ ] **Step 2 :** Sur A : aller dans Réplication → Ajouter un standby (assistant) → entrer `https://B/` → noter le code 4 chiffres
- [ ] **Step 3 :** Sur B : aller dans Réplication → Devenir standby → entrer `https://A/` + code → cliquer Démarrer
- [ ] **Step 4 :** B redirige vers `/admin/pairing/<sid>` → ouvrir terminal SSH vers `harpo-test-B` (root + password LXC)
- [ ] **Step 5 :** Suivre les 8 étapes → vérifier que la dernière étape (`pg_stat_wal_receiver`) montre `status='streaming'`
- [ ] **Step 6 :** Vérifier qu'A voit le node dans la liste des standby avec un lag faible
- [ ] **Step 7 :** Vérifier que `system_metadata.replication.is_standby_of` côté B vaut bien `https://A/` (LOT 5 vérifiera l'effet UI)

---

# LOT 5 — Mode asservi (1.5 j)

**Objectif** : afficher visuellement et bloquer fonctionnellement les actions de gestion réplication sur l'instance B une fois qu'elle est devenue standby de A.

---

### Task 5.1 : Migration + endpoint `is_standby_of`

**Files :**
- Create : `backend/migrations/029_system_metadata_standby.sql`
- Modify : `backend/app/api/v1/admin_replication.py` (endpoint GET)
- Test : `backend/tests/test_replication_standby_of.py`

- [ ] **Step 1 : Migration (idempotent insert de la clé)**

```sql
-- backend/migrations/029_system_metadata_standby.sql
INSERT INTO system_metadata (key, value)
VALUES ('replication.is_standby_of', 'null'::jsonb)
ON CONFLICT (key) DO NOTHING;
```

- [ ] **Step 2 : Endpoint GET**

```python
# backend/app/api/v1/admin_replication.py — ajouter
from app.db.repositories import system_metadata as meta_repo

@router.get("/standby-of", response_class=JSONResponse)
async def get_standby_of(admin: AdminJwt) -> JSONResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        v = await meta_repo.get_value(conn, "replication.is_standby_of")
    return JSONResponse({"is_standby_of": v})
```

- [ ] **Step 3 : Test**

```python
# backend/tests/test_replication_standby_of.py
def test_get_standby_of_returns_null_by_default(client, admin_jwt):
    r = client.get("/v1/admin/replication/standby-of",
                    headers={"Authorization": f"Bearer {admin_jwt}"})
    assert r.status_code == 200
    assert r.json() == {"is_standby_of": None}
```

- [ ] **Step 4 : Run + commit**

```bash
uv run pytest -xvs backend/tests/test_replication_standby_of.py
git add backend/migrations/029_system_metadata_standby.sql \
        backend/app/api/v1/admin_replication.py \
        backend/tests/test_replication_standby_of.py
git commit -m "feat(replication): endpoint GET /admin/replication/standby-of (LOT 5)"
```

---

### Task 5.2 : Composant `StandbyBanner` global

**Files :**
- Create : `frontend/src/components/StandbyBanner.tsx`
- Modify : `frontend/src/lib/adminApi.ts` (ajouter `getStandbyOf`)
- Modify : `frontend/src/components/Layout.tsx`
- Modify : `frontend/src/i18n/fr.json` + `en.json`

- [ ] **Step 1 : i18n**

Ajouter dans `fr.json` sous `admin.replication.pairing` :
```json
"banner": {
  "title": "Mode asservi (standby)",
  "message": "Cette instance Harpocrate est asservie au master {{master}}. Les actions de gestion réplication sont désactivées sur cette instance.",
  "learnMore": "En savoir plus"
}
```

- [ ] **Step 2 : Helper API**

```typescript
// frontend/src/lib/adminApi.ts — append
export async function getStandbyOf(): Promise<{ is_standby_of: string | null }> {
  return apiClient.get('/v1/admin/replication/standby-of')
}
```

- [ ] **Step 3 : Composant**

```tsx
// frontend/src/components/StandbyBanner.tsx
import { useQuery } from '@tanstack/react-query'
import { Alert, Text } from '@mantine/core'
import { useTranslation } from 'react-i18next'
import { getStandbyOf } from '@/lib/adminApi'
import { useAuthStore } from '@/lib/authStore'

export function StandbyBanner() {
  const { t } = useTranslation()
  const isAdmin = useAuthStore((s) => s.isAdmin)
  const q = useQuery({
    queryKey: ['standby-of'],
    queryFn: getStandbyOf,
    enabled: !!isAdmin,
    refetchInterval: 60_000,
    retry: false,
  })
  const master = q.data?.is_standby_of
  if (!master) return null
  return (
    <Alert color="orange" title={t('admin.replication.pairing.banner.title')} mb="sm">
      <Text size="sm">
        {t('admin.replication.pairing.banner.message', { master })}
      </Text>
    </Alert>
  )
}
```

- [ ] **Step 4 : Intégrer dans Layout**

```tsx
// frontend/src/components/Layout.tsx — juste avant <Outlet />
import { StandbyBanner } from './StandbyBanner'
// ...
<StandbyBanner />
<Outlet />
```

- [ ] **Step 5 : Vérifier visuel**

`npm run dev` puis manuellement set la clé : 
```bash
ssh pve "pct exec <lxc> -- docker exec harpocrate-postgres \
  psql -U postgres -d harpocrate -c \"\
  UPDATE system_metadata SET value = '\\\"https://harpo-test-A/\\\"'::jsonb \
  WHERE key = 'replication.is_standby_of';\""
```
Recharger la page → bandeau orange visible en haut.

- [ ] **Step 6 : Commit**

```bash
git add frontend/src/components/StandbyBanner.tsx \
        frontend/src/components/Layout.tsx \
        frontend/src/lib/adminApi.ts \
        frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(replication): bandeau StandbyBanner global quand asservi (LOT 5)"
```

---

### Task 5.3 : Désactivation actions réplication côté standby

**Files :**
- Modify : `frontend/src/pages/AdminReplicationPage.tsx`
- Modify : `frontend/src/components/StreamingNodesPanel.tsx`

- [ ] **Step 1 : Hook réutilisable**

Créer `frontend/src/lib/useIsStandby.ts` :
```typescript
import { useQuery } from '@tanstack/react-query'
import { getStandbyOf } from './adminApi'

export function useIsStandby(): boolean {
  const q = useQuery({
    queryKey: ['standby-of'], queryFn: getStandbyOf,
    refetchInterval: 60_000, retry: false,
  })
  return q.data?.is_standby_of != null
}
```

- [ ] **Step 2 : Désactiver dans `AdminReplicationPage`**

```tsx
// AdminReplicationPage.tsx — wrap le Switch d'activate/deactivate strategy :
const isStandby = useIsStandby()
// ...
<Switch
  ...
  disabled={!s.enabled || toggleMut.isPending || isStandby}
/>
```

- [ ] **Step 3 : Désactiver `AddStandbyModal` trigger dans `StreamingNodesPanel`**

```tsx
const isStandby = useIsStandby()
<Button onClick={() => setPairingOpen(true)} disabled={isStandby}>
  {t('admin.replication.pairing.addStandby')}
</Button>
```

Désactiver également les boutons "Ajouter manuellement", "Supprimer node", "Reload pg_hba" du panel.

- [ ] **Step 4 : Vérifier visuel** avec la clé set comme en Task 5.2 → tous les boutons grisés.

- [ ] **Step 5 : Commit**

```bash
git add frontend/src/lib/useIsStandby.ts \
        frontend/src/pages/AdminReplicationPage.tsx \
        frontend/src/components/StreamingNodesPanel.tsx
git commit -m "feat(replication): désactivation des actions réplication en mode asservi (LOT 5)"
```

---

### Task 5.4 : Affichage côté A — ligne « réplication active vers » dans la liste des nodes

**Files :**
- Modify : `frontend/src/components/StreamingNodesPanel.tsx`

Ce qu'on a déjà : la table des nodes existante affiche les standby. Le LOT 4 a déjà ajouté la création de node via `add_node` dans `confirm_master`. Donc la ligne « réplication active vers X » est NATURELLEMENT affichée par la table existante.

- [ ] **Step 1 : Vérifier qu'après un appairage, le standby apparaît bien dans la table** (validé en Task 4.6)
- [ ] **Step 2 : Ajouter un badge `via assistant` sur les nodes créés via le pairing**

Ce badge nécessite une colonne `created_via` dans la table replication_nodes. Vu la portée, on considère que c'est OPTIONNEL et reportable. **Skipper pour l'instant** — la liste existante suffit fonctionnellement.

- [ ] **Step 3 : Pas de commit** (rien changé)

---

### Task 5.5 : Test manuel global LOT 1-5

**Files :** aucun

- [ ] **Step 1 :** Repartir de zéro avec deux LXC frais (A et B)
- [ ] **Step 2 :** Faire l'appairage complet via le wizard (LOT 4 Task 4.6)
- [ ] **Step 3 :** Vérifier sur B que le bandeau orange apparaît, que les boutons réplication sont grisés
- [ ] **Step 4 :** Vérifier sur A que B apparaît dans la liste des standby avec lag faible
- [ ] **Step 5 :** Créer un wallet sur A → vérifier qu'il apparaît côté B après quelques secondes (réplication WAL)
- [ ] **Step 6 :** Audit log : vérifier les events `pairing.master_init`, `pairing.standby_accepted`, `pairing.completed`, `replication.standby_of_set`, `ssh_session.opened/closed`

---

# Self-Review — checklist post-rédaction

**1. Couverture spec**

| Exigence | Tâche |
|---|---|
| Terminal SSH dans le navigateur | Task 1.5–1.7 |
| Creds SSH non persistés | Task 1.3 (RAM seulement) |
| Auth WS via JWT admin | Task 1.4 |
| Audit log open/close (pas le contenu) | Task 1.3 + 1.4 |
| Code 4 chiffres + TTL | Task 2.2 + settings (config.py) |
| Rate-limit 3 essais | Task 2.3 |
| Échange master_host/user/password | Task 2.3 |
| Wizard step-by-step click-to-copy | Task 4.4 |
| Boutons OK / Retour | Task 4.4 |
| Bandeau mode asservi | Task 5.2 |
| Désactivation actions réplication | Task 5.3 |
| Multi-standby côté A | Couvert : `streaming_svc.add_node` existant, on ajoute un node par appairage |
| Promote / failover | **HORS SCOPE** — plan séparé à venir |

**2. Placeholder scan** : pas de TBD/TODO/etc. Quelques tâches OPTIONNELLES (Task 5.4 step 2) sont explicitement marquées « skipper pour l'instant ».

**3. Cohérence des types**

- `pairing_session.payload` JSONB côté DB ↔ `dict` côté Python ↔ `PairingConfirmResponse` Pydantic ↔ `PairingStepsResponse` (champ `current_step_idx`) côté Zod ✓
- `WizardStep.idx/title/command/hint` cohérent partout ✓
- `is_standby_of` clé `system_metadata` cohérente : Task 3.2 (set), Task 5.1 (get), Task 5.2 (UI) ✓
- `setStandbyOf` annoncé dans la file structure mais le PATCH se fait via le hook `streaming_svc.set_standby_of` côté backend uniquement, pas exposé en endpoint REST. Suppression de `setStandbyOf` de la liste des helpers `adminApi` (Task 4.1) — **noté ici, à ne pas implémenter**.

---

## Plan complet et sauvegardé

Plan complet et sauvegardé à `docs/superpowers/plans/2026-05-11-replication-pairing-wizard.md`. Deux options d'exécution :

**1. Subagent-Driven (recommandé)** — je dispatche un subagent frais par tâche avec deux passes de revue (spec compliance puis code quality), itération rapide. Adapté pour ce gros chantier où la qualité doit primer.

**2. Inline Execution** — j'exécute les tâches dans cette session avec checkpoints, plus séquentiel et sous ton œil direct.

Quelle approche ?
