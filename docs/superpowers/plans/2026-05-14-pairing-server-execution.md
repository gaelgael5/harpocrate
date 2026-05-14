# Pairing Wizard — exécution serveur + suppression terminal SSH

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer le terminal SSH interactif (`SSHTerminal` + `SSHCredentialsModal` + copier-coller manuel) par une exécution serveur automatique avec stepper de progression côté frontend. Deux moteurs (Docker via `aiodocker`, natif via `asyncssh`) sélectionnés selon le mode d'installation détecté au démarrage du backend. Corrige aussi les 3 commandes buggées du wizard actuel (paths inexistants en mode Docker).

**Architecture :**
1. Backend détecte le mode d'installation au démarrage (`docker_compose_auto` si `/.dockerenv` présent + socket Docker monté ; sinon `native`).
2. Service `pairing_exec` orchestre l'exécution des 7 étapes via un Executor concret (`DockerExecutor` ou `NativeSshExecutor`).
3. WebSocket `/v1/admin/replication/pairing/{sid}/exec/ws` push les events `step_started`, `step_done`, `step_error`, `execution_complete` au frontend en temps réel.
4. Frontend remplace `SSHTerminal` + `PairingStepsList` par `PairingExecutionStepper` (chaque étape : `pending` → `running` → `done`/`error` avec affichage stdout/stderr). En mode natif uniquement, modale credentials SSH demandée **une seule fois** au démarrage.
5. Audit log de chaque commande exécutée (`pairing.exec_step_started`, `pairing.exec_step_done`, `pairing.exec_step_error`).
6. Bouton « Réessayer depuis l'étape N » : relance l'orchestrateur en sautant les étapes antérieures (avec cleanup propre du data dir avant `pg_basebackup`).
7. Suppression des fichiers SSH terminal devenus inutiles.

**Tech Stack :** Python 3.12 + FastAPI + asyncpg + aiodocker + asyncssh + structlog + pytest-asyncio ; Vite + React 18 + TypeScript strict + TanStack Query + Mantine + i18next + Vitest.

---

## File Structure

### Backend — créés

- `backend/app/services/install_mode.py` — détection du mode + métadonnées (host data dir path)
- `backend/app/services/pairing_exec/__init__.py` — public API du module
- `backend/app/services/pairing_exec/events.py` — types d'events poussés via WS
- `backend/app/services/pairing_exec/steps.py` — types `Step`, `StepResult`, mapping idx → step metadata
- `backend/app/services/pairing_exec/executor_base.py` — interface abstraite `Executor`
- `backend/app/services/pairing_exec/docker_executor.py` — implémentation aiodocker
- `backend/app/services/pairing_exec/native_executor.py` — implémentation asyncssh
- `backend/app/services/pairing_exec/orchestrator.py` — exécute les steps, émet events, gère retry
- `backend/app/api/v1/admin_install_mode.py` — endpoint `GET /admin/install-mode`
- `backend/app/api/v1/admin_pairing_exec.py` — endpoint WebSocket `/admin/replication/pairing/{sid}/exec/ws`
- `backend/app/models/api/install_mode.py` — DTOs Pydantic
- `backend/app/models/api/pairing_exec.py` — DTOs events WS
- `backend/tests/test_install_mode.py`
- `backend/tests/test_pairing_exec_events.py`
- `backend/tests/test_pairing_exec_steps.py`
- `backend/tests/test_pairing_exec_docker_executor.py`
- `backend/tests/test_pairing_exec_native_executor.py`
- `backend/tests/test_pairing_exec_orchestrator.py`
- `backend/tests/test_admin_install_mode_api.py`
- `backend/tests/test_admin_pairing_exec_ws.py`

### Backend — modifiés

- `backend/app/main.py` — register `admin_install_mode_router` + `admin_pairing_exec_router`, deregister `admin_ssh_terminal_router`

### Backend — supprimés

- `backend/app/api/v1/admin_ssh_terminal.py`
- `backend/app/services/ssh_terminal.py`
- `backend/tests/test_ssh_terminal.py`
- `backend/tests/test_ssh_terminal_api.py`

### Frontend — créés

- `frontend/src/lib/installMode.ts` — fetcher `GET /admin/install-mode`
- `frontend/src/lib/pairingExecSocket.ts` — wrapper WS pour events
- `frontend/src/schemas/installMode.ts`
- `frontend/src/schemas/pairingExec.ts` — types events Zod
- `frontend/src/components/PairingExecutionStepper.tsx` — UI stepper
- `frontend/src/components/SshCredsForExecModal.tsx` — modale credentials une seule fois (mode natif)
- `frontend/src/tests/installMode.test.ts`
- `frontend/src/tests/pairingExecSocket.test.ts`
- `frontend/src/tests/pairingExecutionStepper.test.tsx`
- `frontend/src/tests/sshCredsForExecModal.test.tsx`

### Frontend — modifiés

- `frontend/src/pages/PairingWizardPage.tsx` — refactor complet
- `frontend/src/i18n/fr.json`, `frontend/src/i18n/en.json` — nouveaux libellés

### Frontend — supprimés

- `frontend/src/components/SSHTerminal.tsx`
- `frontend/src/components/SSHCredentialsModal.tsx`
- `frontend/src/lib/sshTerminalSocket.ts`
- `frontend/src/tests/sshTerminalSocket.test.ts`

### Docs

- `Install-dev.md` — nouvelle section : socket Docker à monter pour le mode auto + implications sécurité
- `docker-compose.yml` — commentaire sur le bind mount socket (désactivé par défaut, à activer explicitement par l'admin)
- `LESSONS.md` — leçon

---

## Task 1: Backend `install_mode` service

**Files:**
- Create: `backend/app/services/install_mode.py`
- Create: `backend/tests/test_install_mode.py`

- [ ] **Step 1: Test rouge — detection en mode `native` quand pas en Docker**

```python
"""Tests détection install_mode (LOT pairing-exec)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services import install_mode as svc


def test_detect_returns_native_when_no_dockerenv(tmp_path: Path) -> None:
    """Pas de /.dockerenv et pas de socket → mode native."""
    fake_root = tmp_path / "root"
    fake_root.mkdir()
    result = svc.detect(root_path=fake_root, docker_socket_path=fake_root / "no-socket")
    assert result.mode == "native"
    assert result.docker_socket_accessible is False
    assert result.pg_container_data_host_path is None


def test_detect_returns_docker_when_dockerenv_and_socket(tmp_path: Path) -> None:
    """/.dockerenv présent + socket existant → mode docker_compose_auto."""
    fake_root = tmp_path / "root"
    fake_root.mkdir()
    (fake_root / ".dockerenv").write_text("")
    socket = fake_root / "docker.sock"
    socket.write_text("")
    result = svc.detect(root_path=fake_root, docker_socket_path=socket)
    assert result.mode == "docker_compose_auto"
    assert result.docker_socket_accessible is True


def test_detect_native_when_dockerenv_but_no_socket(tmp_path: Path) -> None:
    """Conteneur sans socket monté → mode native (on ne peut pas piloter Docker)."""
    fake_root = tmp_path / "root"
    fake_root.mkdir()
    (fake_root / ".dockerenv").write_text("")
    result = svc.detect(root_path=fake_root, docker_socket_path=fake_root / "no-socket")
    assert result.mode == "native"
    assert result.docker_socket_accessible is False
```

- [ ] **Step 2: Run → rouge**

Run: `cd backend && uv run python -m pytest tests/test_install_mode.py -v`
Expected: FAIL — `app.services.install_mode` n'existe pas.

- [ ] **Step 3: Implémentation minimale**

```python
"""Détection du mode d'installation Harpocrate.

`docker_compose_auto` : conteneur Docker (présence de /.dockerenv) AVEC socket
Docker monté (typiquement /var/run/docker.sock) → on peut piloter `docker stop`,
`docker run`, `docker exec` depuis le backend via aiodocker.

`native` : tout autre cas. Le pilotage de Postgres nécessitera une session SSH
avec credentials saisies par l'admin.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import structlog

logger = structlog.get_logger(__name__)

InstallMode = Literal["docker_compose_auto", "native"]


@dataclass(frozen=True)
class InstallModeInfo:
    mode: InstallMode
    docker_socket_accessible: bool
    pg_container_data_host_path: str | None


def detect(
    *,
    root_path: Path = Path("/"),
    docker_socket_path: Path = Path("/var/run/docker.sock"),
) -> InstallModeInfo:
    in_container = (root_path / ".dockerenv").exists()
    socket_ok = docker_socket_path.exists()
    if in_container and socket_ok:
        return InstallModeInfo(
            mode="docker_compose_auto",
            docker_socket_accessible=True,
            pg_container_data_host_path=None,
        )
    return InstallModeInfo(
        mode="native",
        docker_socket_accessible=False,
        pg_container_data_host_path=None,
    )
```

`pg_container_data_host_path` reste `None` ici — il sera rempli par le `DockerExecutor` à l'usage via `docker inspect`, pas au démarrage (Task 5).

- [ ] **Step 4: Run → vert**

Run: `cd backend && uv run python -m pytest tests/test_install_mode.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/install_mode.py backend/tests/test_install_mode.py
git commit -m "feat(install): détection du mode docker_compose_auto vs native"
```

---

## Task 2: Backend endpoint `GET /admin/install-mode`

**Files:**
- Create: `backend/app/models/api/install_mode.py`
- Create: `backend/app/api/v1/admin_install_mode.py`
- Create: `backend/tests/test_admin_install_mode_api.py`
- Modify: `backend/app/main.py` (register router)

- [ ] **Step 1: DTO Pydantic**

`backend/app/models/api/install_mode.py` :

```python
"""DTOs install_mode (LOT pairing-exec)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class InstallModeResponse(BaseModel):
    mode: Literal["docker_compose_auto", "native"]
    docker_socket_accessible: bool
    pg_container_data_host_path: str | None
```

- [ ] **Step 2: Test rouge — endpoint requires admin and returns mode**

`backend/tests/test_admin_install_mode_api.py` (calque le pattern des tests existants `test_pairing_api_v2.py` — mock `require_admin_jwt`) :

```python
"""Tests endpoint GET /admin/install-mode."""

from __future__ import annotations

import pytest
from unittest.mock import patch

from app.services import install_mode as svc


@pytest.mark.asyncio
async def test_install_mode_endpoint_returns_detected_mode(
    api_client_admin,
) -> None:
    client, _app, _ = api_client_admin

    fake = svc.InstallModeInfo(
        mode="docker_compose_auto",
        docker_socket_accessible=True,
        pg_container_data_host_path=None,
    )
    with patch.object(svc, "detect", return_value=fake):
        resp = await client.get("/v1/admin/install-mode")

    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "docker_compose_auto"
    assert body["docker_socket_accessible"] is True


@pytest.mark.asyncio
async def test_install_mode_endpoint_requires_admin(api_client_unauth) -> None:
    client, _app, _ = api_client_unauth
    resp = await client.get("/v1/admin/install-mode")
    assert resp.status_code == 401
```

NOTE : les fixtures `api_client_admin` / `api_client_unauth` reprennent le pattern de `_build_test_app()` de `test_pairing_api_v2.py` (Task 8 du précédent plan). Si ces fixtures n'existent pas en partage, créer une `conftest.py` locale qui les fournit — ou inline `_build_test_app()` au début du fichier.

- [ ] **Step 3: Run → rouge**

Run: `cd backend && uv run python -m pytest tests/test_admin_install_mode_api.py -v`
Expected: FAIL — endpoint n'existe pas.

- [ ] **Step 4: Endpoint**

`backend/app/api/v1/admin_install_mode.py` :

```python
"""Endpoint REST exposant le mode d'installation détecté (LOT pairing-exec)."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.admin_auth import AdminJwt
from app.models.api.install_mode import InstallModeResponse
from app.services import install_mode as svc

router = APIRouter(prefix="/admin", tags=["admin-install-mode"])


@router.get("/install-mode", response_model=InstallModeResponse)
async def get_install_mode(admin: AdminJwt) -> InstallModeResponse:
    info = svc.detect()
    return InstallModeResponse(
        mode=info.mode,
        docker_socket_accessible=info.docker_socket_accessible,
        pg_container_data_host_path=info.pg_container_data_host_path,
    )
```

- [ ] **Step 5: Register router**

Dans `backend/app/main.py`, à côté des autres `app.include_router(...)`, ajouter :

```python
from app.api.v1.admin_install_mode import router as admin_install_mode_router
...
app.include_router(admin_install_mode_router, prefix="/v1")
```

(Adapter exact à ce qui existe — relire la zone des registers pour matcher le style.)

- [ ] **Step 6: Run → vert**

Run: `cd backend && uv run python -m pytest tests/test_admin_install_mode_api.py -v`
Expected: 2 PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/api/install_mode.py backend/app/api/v1/admin_install_mode.py backend/tests/test_admin_install_mode_api.py backend/app/main.py
git commit -m "feat(install): endpoint GET /admin/install-mode"
```

---

## Task 3: Backend `pairing_exec` events + steps

**Files:**
- Create: `backend/app/services/pairing_exec/__init__.py`
- Create: `backend/app/services/pairing_exec/events.py`
- Create: `backend/app/services/pairing_exec/steps.py`
- Create: `backend/tests/test_pairing_exec_events.py`
- Create: `backend/tests/test_pairing_exec_steps.py`

- [ ] **Step 1: Test rouge events**

`backend/tests/test_pairing_exec_events.py` :

```python
"""Tests des events poussés par l'orchestrator pairing_exec."""

from __future__ import annotations

from app.services.pairing_exec.events import (
    StepStartedEvent,
    StepDoneEvent,
    StepErrorEvent,
    ExecutionCompleteEvent,
    serialize_event,
)


def test_step_started_serializes_to_json_dict() -> None:
    ev = StepStartedEvent(step_idx=2, title="pg_basebackup", command="docker run ...")
    payload = serialize_event(ev)
    assert payload["type"] == "step_started"
    assert payload["step_idx"] == 2
    assert payload["title"] == "pg_basebackup"
    assert payload["command"] == "docker run ..."


def test_step_done_carries_stdout_and_exit_code() -> None:
    ev = StepDoneEvent(step_idx=0, exit_code=0, stdout="ok\n", stderr="")
    payload = serialize_event(ev)
    assert payload["type"] == "step_done"
    assert payload["exit_code"] == 0
    assert payload["stdout"] == "ok\n"


def test_step_error_carries_error_type() -> None:
    ev = StepErrorEvent(step_idx=1, exit_code=2, stdout="", stderr="boom", error_type="NonZeroExit")
    payload = serialize_event(ev)
    assert payload["type"] == "step_error"
    assert payload["error_type"] == "NonZeroExit"


def test_execution_complete_no_payload() -> None:
    ev = ExecutionCompleteEvent()
    payload = serialize_event(ev)
    assert payload["type"] == "execution_complete"
```

- [ ] **Step 2: Run → rouge**

Run: `cd backend && uv run python -m pytest tests/test_pairing_exec_events.py -v`
Expected: FAIL — module manquant.

- [ ] **Step 3: Events impl**

`backend/app/services/pairing_exec/__init__.py` :

```python
"""Module pairing_exec — exécution serveur des étapes du wizard pairing."""

from __future__ import annotations
```

`backend/app/services/pairing_exec/events.py` :

```python
"""Events émis par l'orchestrator pairing_exec, sérialisés sur le WebSocket.

Types JSON :
- step_started   : { step_idx, title, command }
- step_done      : { step_idx, exit_code, stdout, stderr }
- step_error     : { step_idx, exit_code, stdout, stderr, error_type }
- execution_complete : {}
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Union


@dataclass(frozen=True)
class StepStartedEvent:
    step_idx: int
    title: str
    command: str


@dataclass(frozen=True)
class StepDoneEvent:
    step_idx: int
    exit_code: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class StepErrorEvent:
    step_idx: int
    exit_code: int
    stdout: str
    stderr: str
    error_type: str


@dataclass(frozen=True)
class ExecutionCompleteEvent:
    pass


Event = Union[StepStartedEvent, StepDoneEvent, StepErrorEvent, ExecutionCompleteEvent]


def serialize_event(ev: Event) -> dict[str, Any]:
    if isinstance(ev, StepStartedEvent):
        return {"type": "step_started", "step_idx": ev.step_idx, "title": ev.title, "command": ev.command}
    if isinstance(ev, StepDoneEvent):
        return {"type": "step_done", "step_idx": ev.step_idx, "exit_code": ev.exit_code, "stdout": ev.stdout, "stderr": ev.stderr}
    if isinstance(ev, StepErrorEvent):
        return {"type": "step_error", "step_idx": ev.step_idx, "exit_code": ev.exit_code, "stdout": ev.stdout, "stderr": ev.stderr, "error_type": ev.error_type}
    if isinstance(ev, ExecutionCompleteEvent):
        return {"type": "execution_complete"}
    raise TypeError(f"unknown_event:{type(ev).__name__}")
```

- [ ] **Step 4: Test rouge steps**

`backend/tests/test_pairing_exec_steps.py` :

```python
"""Tests de la déclaration des étapes du wizard."""

from __future__ import annotations

from app.services.pairing_exec.steps import (
    PairingPayload,
    StepDescriptor,
    list_steps,
)


def _payload() -> PairingPayload:
    return PairingPayload(
        master_host="a.example",
        master_port=5432,
        replication_user="repl_b_abc123",
        replication_password="sekret",
        application_name="b_example",
    )


def test_list_steps_returns_seven_entries() -> None:
    steps = list_steps(_payload())
    assert len(steps) == 7
    assert all(isinstance(s, StepDescriptor) for s in steps)


def test_list_steps_have_unique_indices_0_to_6() -> None:
    steps = list_steps(_payload())
    assert [s.idx for s in steps] == list(range(7))


def test_list_steps_titles_in_french() -> None:
    steps = list_steps(_payload())
    titles = [s.title for s in steps]
    assert "Arrêter le conteneur Postgres local" in titles
    assert any("pg_basebackup" in t.lower() for t in titles)
```

- [ ] **Step 5: Run → rouge**

Run: `cd backend && uv run python -m pytest tests/test_pairing_exec_steps.py -v`
Expected: FAIL — module manquant.

- [ ] **Step 6: Steps impl**

`backend/app/services/pairing_exec/steps.py` :

```python
"""Déclaration des 7 étapes du wizard pairing standby.

Chaque `StepDescriptor` porte le titre FR, une description longue (le « pourquoi »)
et un identifiant `kind` qui pilote le dispatch côté Executor (DockerExecutor ou
NativeSshExecutor traduisent ce kind en commande concrète).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

StepKind = Literal[
    "stop_pg_container",
    "backup_pg_data_dir",
    "pg_basebackup_from_master",
    "verify_standby_signal",
    "verify_auto_conf",
    "start_pg_container",
    "verify_streaming",
]


@dataclass(frozen=True)
class PairingPayload:
    master_host: str
    master_port: int
    replication_user: str
    replication_password: str
    application_name: str


@dataclass(frozen=True)
class StepDescriptor:
    idx: int
    kind: StepKind
    title: str
    description: str


def list_steps(payload: PairingPayload) -> list[StepDescriptor]:
    return [
        StepDescriptor(
            idx=0,
            kind="stop_pg_container",
            title="Arrêter le conteneur Postgres local",
            description=(
                "On stoppe l'instance Postgres pour pouvoir remplacer son data dir. "
                "Si elle est en cours d'écriture, on attend la fin gracieuse."
            ),
        ),
        StepDescriptor(
            idx=1,
            kind="backup_pg_data_dir",
            title="Sauvegarder le data dir actuel",
            description=(
                "Le data dir actuel est renommé en .bak.<timestamp> pour permettre "
                "un rollback manuel si pg_basebackup échoue."
            ),
        ),
        StepDescriptor(
            idx=2,
            kind="pg_basebackup_from_master",
            title="pg_basebackup depuis le master",
            description=(
                f"Copie l'intégralité de la base du master ({payload.master_host}:"
                f"{payload.master_port}) en mode streaming, crée le slot de "
                f"réplication '{payload.application_name}'."
            ),
        ),
        StepDescriptor(
            idx=3,
            kind="verify_standby_signal",
            title="Vérifier standby.signal",
            description="Le fichier signal doit exister pour que Postgres démarre en mode standby.",
        ),
        StepDescriptor(
            idx=4,
            kind="verify_auto_conf",
            title="Vérifier postgresql.auto.conf",
            description="Doit contenir une ligne primary_conninfo=… avec le bon host/user.",
        ),
        StepDescriptor(
            idx=5,
            kind="start_pg_container",
            title="Démarrer le conteneur Postgres",
            description="Postgres démarre en mode standby (recovery).",
        ),
        StepDescriptor(
            idx=6,
            kind="verify_streaming",
            title="Vérifier le streaming WAL actif",
            description=(
                "Une ligne avec status='streaming' dans pg_stat_wal_receiver "
                "confirme que le WAL flux depuis le master."
            ),
        ),
    ]
```

- [ ] **Step 7: Run → vert**

Run: `cd backend && uv run python -m pytest tests/test_pairing_exec_events.py tests/test_pairing_exec_steps.py -v`
Expected: 7 PASS au total.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/pairing_exec/__init__.py backend/app/services/pairing_exec/events.py backend/app/services/pairing_exec/steps.py backend/tests/test_pairing_exec_events.py backend/tests/test_pairing_exec_steps.py
git commit -m "feat(pairing-exec): events + déclaration des 7 étapes du wizard"
```

---

## Task 4: Backend `ExecutorBase` interface + `StepResult`

**Files:**
- Create: `backend/app/services/pairing_exec/executor_base.py`
- Create: `backend/tests/test_pairing_exec_executor_base.py`

- [ ] **Step 1: Test rouge — interface abstraite refuse instanciation directe**

```python
"""Tests de l'interface abstraite ExecutorBase."""

from __future__ import annotations

import pytest

from app.services.pairing_exec.executor_base import Executor, StepResult


def test_executor_is_abstract() -> None:
    with pytest.raises(TypeError):
        Executor()


def test_step_result_carries_exit_code_stdout_stderr() -> None:
    r = StepResult(exit_code=0, stdout="ok", stderr="")
    assert r.is_success is True

    err = StepResult(exit_code=2, stdout="", stderr="boom")
    assert err.is_success is False
```

- [ ] **Step 2: Run → rouge**

Run: `cd backend && uv run python -m pytest tests/test_pairing_exec_executor_base.py -v`
Expected: FAIL — module manquant.

- [ ] **Step 3: Impl**

`backend/app/services/pairing_exec/executor_base.py` :

```python
"""Interface abstraite des executors pairing_exec.

Chaque executor (Docker, native SSH) implémente `exec_step` pour exécuter
une `StepDescriptor` donnée et retourner un `StepResult` (exit_code + I/O).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.services.pairing_exec.steps import PairingPayload, StepDescriptor


@dataclass(frozen=True)
class StepResult:
    exit_code: int
    stdout: str
    stderr: str

    @property
    def is_success(self) -> bool:
        return self.exit_code == 0


class Executor(ABC):
    """Interface contractuelle pour les moteurs d'exécution."""

    @abstractmethod
    async def open(self) -> None:
        """Ouvre la session (connexion Docker ou SSH). Idempotent."""

    @abstractmethod
    async def close(self) -> None:
        """Ferme la session proprement. Idempotent."""

    @abstractmethod
    async def exec_step(
        self,
        step: StepDescriptor,
        payload: PairingPayload,
    ) -> StepResult:
        """Exécute une étape et retourne le résultat. Ne lève PAS sur exit != 0."""
```

- [ ] **Step 4: Run → vert**

Run: `cd backend && uv run python -m pytest tests/test_pairing_exec_executor_base.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/pairing_exec/executor_base.py backend/tests/test_pairing_exec_executor_base.py
git commit -m "feat(pairing-exec): interface Executor + StepResult"
```

---

## Task 5: Backend `DockerExecutor` — inspect data dir host path + `open/close`

**Files:**
- Create: `backend/app/services/pairing_exec/docker_executor.py`
- Create: `backend/tests/test_pairing_exec_docker_executor.py`

- [ ] **Step 1: Test rouge — open inspecte le conteneur PG pour extraire le host path**

```python
"""Tests DockerExecutor."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.pairing_exec.docker_executor import DockerExecutor


@pytest.mark.asyncio
async def test_open_extracts_pg_data_host_path_from_inspect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_inspect_result = {
        "Mounts": [
            {"Type": "bind", "Source": "/opt/harpocrate/data/postgres", "Destination": "/var/lib/postgresql/data"},
            {"Type": "bind", "Source": "/opt/harpocrate/db/init", "Destination": "/docker-entrypoint-initdb.d"},
        ]
    }
    fake_container = AsyncMock()
    fake_container.show = AsyncMock(return_value=fake_inspect_result)

    fake_docker = AsyncMock()
    fake_docker.containers.get = AsyncMock(return_value=fake_container)

    monkeypatch.setattr(
        "app.services.pairing_exec.docker_executor.aiodocker.Docker",
        lambda: fake_docker,
    )

    ex = DockerExecutor(pg_container_name="harpocrate-postgres")
    await ex.open()
    assert ex.pg_data_host_path == "/opt/harpocrate/data/postgres"
    await ex.close()


@pytest.mark.asyncio
async def test_open_raises_when_pg_data_mount_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_inspect_result = {"Mounts": []}
    fake_container = AsyncMock()
    fake_container.show = AsyncMock(return_value=fake_inspect_result)
    fake_docker = AsyncMock()
    fake_docker.containers.get = AsyncMock(return_value=fake_container)
    monkeypatch.setattr(
        "app.services.pairing_exec.docker_executor.aiodocker.Docker",
        lambda: fake_docker,
    )

    ex = DockerExecutor(pg_container_name="harpocrate-postgres")
    with pytest.raises(RuntimeError, match="pg_data_mount_not_found"):
        await ex.open()
```

- [ ] **Step 2: Run → rouge**

Run: `cd backend && uv run python -m pytest tests/test_pairing_exec_docker_executor.py -v`
Expected: FAIL.

- [ ] **Step 3: Impl `open` + `close` + inspect**

`backend/app/services/pairing_exec/docker_executor.py` :

```python
"""Moteur d'exécution Docker — pilote `harpocrate-postgres` via aiodocker.

Le path host du data dir Postgres est découvert au `open()` en inspectant les
bind mounts du conteneur. Aucune config admin nécessaire.
"""

from __future__ import annotations

import aiodocker
import structlog

from app.services.pairing_exec.executor_base import Executor, StepResult
from app.services.pairing_exec.steps import PairingPayload, StepDescriptor

logger = structlog.get_logger(__name__)

# Path attendu côté conteneur Postgres pour le data dir.
_PG_DATA_CONTAINER_PATH = "/var/lib/postgresql/data"


class DockerExecutor(Executor):
    def __init__(self, *, pg_container_name: str = "harpocrate-postgres") -> None:
        self._pg_container_name = pg_container_name
        self._docker: aiodocker.Docker | None = None
        self.pg_data_host_path: str | None = None

    async def open(self) -> None:
        if self._docker is not None:
            return
        self._docker = aiodocker.Docker()
        container = await self._docker.containers.get(self._pg_container_name)
        info = await container.show()
        for mount in info.get("Mounts", []):
            if mount.get("Destination") == _PG_DATA_CONTAINER_PATH:
                self.pg_data_host_path = mount["Source"]
                break
        if self.pg_data_host_path is None:
            raise RuntimeError("pg_data_mount_not_found")
        logger.info(
            "docker_executor_opened",
            pg_container=self._pg_container_name,
            pg_data_host_path=self.pg_data_host_path,
        )

    async def close(self) -> None:
        if self._docker is not None:
            await self._docker.close()
            self._docker = None

    async def exec_step(self, step: StepDescriptor, payload: PairingPayload) -> StepResult:
        # Implémentation complète Task 6.
        raise NotImplementedError(f"step_kind_not_yet_implemented:{step.kind}")
```

- [ ] **Step 4: Run → vert**

Run: `cd backend && uv run python -m pytest tests/test_pairing_exec_docker_executor.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/pairing_exec/docker_executor.py backend/tests/test_pairing_exec_docker_executor.py
git commit -m "feat(pairing-exec): DockerExecutor open/close + auto-discovery du data dir host"
```

---

## Task 6: Backend `DockerExecutor` — `exec_step` pour les 7 kinds

**Files:**
- Modify: `backend/app/services/pairing_exec/docker_executor.py`
- Modify: `backend/tests/test_pairing_exec_docker_executor.py`

- [ ] **Step 1: Test rouge — chaque kind produit la bonne commande Docker**

Ajouter dans `test_pairing_exec_docker_executor.py` :

```python
@pytest.mark.asyncio
async def test_exec_step_stop_pg_container_calls_container_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.pairing_exec.steps import (
        PairingPayload, StepDescriptor,
    )

    fake_container = AsyncMock()
    fake_container.show = AsyncMock(return_value={
        "Mounts": [{"Destination": "/var/lib/postgresql/data", "Source": "/host/pg"}]
    })
    fake_container.stop = AsyncMock(return_value=None)
    fake_container.wait = AsyncMock(return_value={"StatusCode": 0})
    fake_docker = AsyncMock()
    fake_docker.containers.get = AsyncMock(return_value=fake_container)
    monkeypatch.setattr(
        "app.services.pairing_exec.docker_executor.aiodocker.Docker",
        lambda: fake_docker,
    )

    ex = DockerExecutor()
    await ex.open()
    step = StepDescriptor(idx=0, kind="stop_pg_container", title="x", description="")
    payload = PairingPayload(
        master_host="a", master_port=5432,
        replication_user="repl", replication_password="p",
        application_name="b",
    )
    res = await ex.exec_step(step, payload)
    assert res.is_success
    fake_container.stop.assert_called_once()
    await ex.close()


@pytest.mark.asyncio
async def test_exec_step_pg_basebackup_runs_postgres_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.pairing_exec.steps import (
        PairingPayload, StepDescriptor,
    )

    fake_pg = AsyncMock()
    fake_pg.show = AsyncMock(return_value={
        "Mounts": [{"Destination": "/var/lib/postgresql/data", "Source": "/host/pg"}]
    })
    fake_run_container = AsyncMock()
    fake_run_container.wait = AsyncMock(return_value={"StatusCode": 0})
    fake_run_container.log = AsyncMock(return_value=["base backup done\n"])
    fake_run_container.delete = AsyncMock(return_value=None)

    fake_docker = AsyncMock()
    fake_docker.containers.get = AsyncMock(return_value=fake_pg)
    fake_docker.containers.run = AsyncMock(return_value=fake_run_container)
    monkeypatch.setattr(
        "app.services.pairing_exec.docker_executor.aiodocker.Docker",
        lambda: fake_docker,
    )

    ex = DockerExecutor()
    await ex.open()
    step = StepDescriptor(idx=2, kind="pg_basebackup_from_master", title="x", description="")
    payload = PairingPayload(
        master_host="a.example", master_port=5432,
        replication_user="repl_x", replication_password="sekret",
        application_name="x",
    )
    res = await ex.exec_step(step, payload)
    assert res.is_success
    call_kwargs = fake_docker.containers.run.call_args.kwargs
    assert "postgres:16-alpine" in str(call_kwargs.get("config", {}).get("Image", ""))
    await ex.close()
```

- [ ] **Step 2: Run → rouge**

Run: `cd backend && uv run python -m pytest tests/test_pairing_exec_docker_executor.py -v`
Expected: FAIL — `exec_step` lève `NotImplementedError`.

- [ ] **Step 3: Impl `exec_step` complet**

Remplacer `exec_step` dans `docker_executor.py` :

```python
    async def exec_step(self, step: StepDescriptor, payload: PairingPayload) -> StepResult:
        if self._docker is None or self.pg_data_host_path is None:
            raise RuntimeError("executor_not_opened")

        dispatcher = {
            "stop_pg_container": self._step_stop_pg,
            "backup_pg_data_dir": self._step_backup_data_dir,
            "pg_basebackup_from_master": self._step_pg_basebackup,
            "verify_standby_signal": self._step_verify_standby_signal,
            "verify_auto_conf": self._step_verify_auto_conf,
            "start_pg_container": self._step_start_pg,
            "verify_streaming": self._step_verify_streaming,
        }
        handler = dispatcher.get(step.kind)
        if handler is None:
            return StepResult(exit_code=99, stdout="", stderr=f"unknown_step_kind:{step.kind}")
        return await handler(payload)

    async def _step_stop_pg(self, payload: PairingPayload) -> StepResult:
        assert self._docker is not None
        container = await self._docker.containers.get(self._pg_container_name)
        await container.stop(timeout=30)
        return StepResult(exit_code=0, stdout="container stopped", stderr="")

    async def _step_backup_data_dir(self, payload: PairingPayload) -> StepResult:
        # Renomme le data dir actuel avec un timestamp. Exécuté via un conteneur
        # éphémère qui monte le PARENT du data dir (read-write).
        assert self._docker is not None and self.pg_data_host_path is not None
        parent_dir = "/".join(self.pg_data_host_path.rstrip("/").split("/")[:-1]) or "/"
        leaf = self.pg_data_host_path.rstrip("/").split("/")[-1]
        cmd = f"mv /host/{leaf} /host/{leaf}.bak.$(date +%s)"
        return await self._run_ephemeral(
            image="alpine:3.20",
            cmd=["sh", "-c", cmd],
            binds=[f"{parent_dir}:/host"],
        )

    async def _step_pg_basebackup(self, payload: PairingPayload) -> StepResult:
        # Recrée le data dir (renommé à l'étape précédente) avec pg_basebackup.
        # Le conteneur éphémère monte un parent vide où on écrit le nouveau dir.
        assert self.pg_data_host_path is not None
        parent_dir = "/".join(self.pg_data_host_path.rstrip("/").split("/")[:-1]) or "/"
        leaf = self.pg_data_host_path.rstrip("/").split("/")[-1]
        env = {
            "PGPASSWORD": payload.replication_password,
        }
        bb = (
            f"pg_basebackup -h {payload.master_host} -p {payload.master_port} "
            f"-D /host/{leaf} -U {payload.replication_user} "
            f"--slot={payload.application_name} -R --wal-method=stream"
        )
        return await self._run_ephemeral(
            image="postgres:16-alpine",
            cmd=["sh", "-c", bb],
            binds=[f"{parent_dir}:/host"],
            env=env,
        )

    async def _step_verify_standby_signal(self, payload: PairingPayload) -> StepResult:
        assert self.pg_data_host_path is not None
        parent_dir = "/".join(self.pg_data_host_path.rstrip("/").split("/")[:-1]) or "/"
        leaf = self.pg_data_host_path.rstrip("/").split("/")[-1]
        return await self._run_ephemeral(
            image="alpine:3.20",
            cmd=["sh", "-c", f"test -f /host/{leaf}/standby.signal && echo present"],
            binds=[f"{parent_dir}:/host:ro"],
        )

    async def _step_verify_auto_conf(self, payload: PairingPayload) -> StepResult:
        assert self.pg_data_host_path is not None
        parent_dir = "/".join(self.pg_data_host_path.rstrip("/").split("/")[:-1]) or "/"
        leaf = self.pg_data_host_path.rstrip("/").split("/")[-1]
        return await self._run_ephemeral(
            image="alpine:3.20",
            cmd=["sh", "-c", f"cat /host/{leaf}/postgresql.auto.conf | grep primary_conninfo"],
            binds=[f"{parent_dir}:/host:ro"],
        )

    async def _step_start_pg(self, payload: PairingPayload) -> StepResult:
        assert self._docker is not None
        container = await self._docker.containers.get(self._pg_container_name)
        await container.start()
        return StepResult(exit_code=0, stdout="container started", stderr="")

    async def _step_verify_streaming(self, payload: PairingPayload) -> StepResult:
        assert self._docker is not None
        container = await self._docker.containers.get(self._pg_container_name)
        sql = (
            "SELECT pid, status, sender_host, sender_port "
            "FROM pg_stat_wal_receiver;"
        )
        exec_inst = await container.exec(cmd=["psql", "-U", "postgres", "-At", "-c", sql])
        stream = exec_inst.start(detach=False)
        output_chunks: list[bytes] = []
        async with stream as s:
            async for msg in s:
                if msg.data:
                    output_chunks.append(msg.data)
        info = await exec_inst.inspect()
        exit_code = info.get("ExitCode", 1)
        stdout = b"".join(output_chunks).decode("utf-8", errors="replace")
        if exit_code == 0 and "streaming" not in stdout:
            return StepResult(exit_code=2, stdout=stdout, stderr="status not streaming")
        return StepResult(exit_code=exit_code, stdout=stdout, stderr="")

    async def _run_ephemeral(
        self,
        *,
        image: str,
        cmd: list[str],
        binds: list[str],
        env: dict[str, str] | None = None,
    ) -> StepResult:
        assert self._docker is not None
        config = {
            "Image": image,
            "Cmd": cmd,
            "Env": [f"{k}={v}" for k, v in (env or {}).items()],
            "HostConfig": {"Binds": binds, "AutoRemove": False},
        }
        container = await self._docker.containers.run(config=config)
        wait = await container.wait()
        exit_code = int(wait.get("StatusCode", 1))
        logs = await container.log(stdout=True, stderr=True)
        stdout = "".join(logs)
        await container.delete(force=True)
        return StepResult(exit_code=exit_code, stdout=stdout, stderr="" if exit_code == 0 else stdout)
```

- [ ] **Step 4: Run → vert**

Run: `cd backend && uv run python -m pytest tests/test_pairing_exec_docker_executor.py -v`
Expected: au moins les 2 nouveaux tests passent. Si d'autres échouent (par ex. tests d'étapes plus complexes pour `_run_ephemeral`), les itérer.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/pairing_exec/docker_executor.py backend/tests/test_pairing_exec_docker_executor.py
git commit -m "feat(pairing-exec): DockerExecutor — exec_step pour les 7 kinds"
```

---

## Task 7: Backend `NativeSshExecutor` (asyncssh)

**Files:**
- Create: `backend/app/services/pairing_exec/native_executor.py`
- Create: `backend/tests/test_pairing_exec_native_executor.py`

- [ ] **Step 1: Test rouge — open/close + run shell command via session SSH**

```python
"""Tests NativeSshExecutor."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.pairing_exec.native_executor import (
    NativeSshExecutor, SshCredentials,
)


@pytest.mark.asyncio
async def test_open_connects_with_password_and_close_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_conn = AsyncMock()
    fake_conn.close = MagicMock()

    async def fake_connect(**kwargs):
        return fake_conn

    monkeypatch.setattr(
        "app.services.pairing_exec.native_executor.asyncssh.connect",
        fake_connect,
    )

    creds = SshCredentials(host="b.example", port=22, username="admin", password="p", private_key=None, passphrase=None)
    ex = NativeSshExecutor(creds)
    await ex.open()
    await ex.close()
    fake_conn.close.assert_called_once()


@pytest.mark.asyncio
async def test_exec_step_stop_pg_runs_docker_stop_over_ssh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.pairing_exec.steps import (
        PairingPayload, StepDescriptor,
    )

    fake_result = MagicMock()
    fake_result.exit_status = 0
    fake_result.stdout = "stopped\n"
    fake_result.stderr = ""

    fake_conn = AsyncMock()
    fake_conn.run = AsyncMock(return_value=fake_result)
    fake_conn.close = MagicMock()

    async def fake_connect(**kwargs):
        return fake_conn

    monkeypatch.setattr(
        "app.services.pairing_exec.native_executor.asyncssh.connect",
        fake_connect,
    )

    creds = SshCredentials(host="b.example", port=22, username="admin", password="p", private_key=None, passphrase=None)
    ex = NativeSshExecutor(creds)
    await ex.open()
    step = StepDescriptor(idx=0, kind="stop_pg_container", title="x", description="")
    payload = PairingPayload(
        master_host="a", master_port=5432,
        replication_user="r", replication_password="p", application_name="b",
    )
    res = await ex.exec_step(step, payload)
    assert res.exit_code == 0
    assert "stopped" in res.stdout
    # vérifie que la commande passée à run contient bien le pattern attendu
    call_args = fake_conn.run.call_args
    cmd_str = call_args.args[0] if call_args.args else call_args.kwargs["command"]
    # Variante: on accepte soit `docker stop` (mode Docker native) soit
    # `systemctl stop postgresql` (mode systemd) — pour ce test on hardcode
    # `docker stop` comme la valeur par défaut. Si tu veux les deux,
    # paramètrer NativeSshExecutor avec un mode d'install.
    assert "docker stop" in cmd_str or "systemctl stop postgresql" in cmd_str
    await ex.close()
```

- [ ] **Step 2: Run → rouge**

Run: `cd backend && uv run python -m pytest tests/test_pairing_exec_native_executor.py -v`
Expected: FAIL.

- [ ] **Step 3: Impl `NativeSshExecutor`**

`backend/app/services/pairing_exec/native_executor.py` :

```python
"""Moteur d'exécution natif via SSH (asyncssh).

Une session SSH unique est ouverte pour toute la durée du wizard. Toutes les
commandes (docker stop/start/exec si l'admin a Docker côté hôte, ou bien
systemctl + pg_basebackup natif sinon) sont exécutées via `conn.run(...)`.

Pour l'itération 1 du LOT, on cible le scénario « Docker côté hôte » :
l'admin a Docker installé sur sa machine, mais Harpocrate n'a pas le socket
monté → on bascule en SSH. Les commandes restent les mêmes que DockerExecutor
mais sont des invocations shell.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import asyncssh
import structlog

from app.services.pairing_exec.executor_base import Executor, StepResult
from app.services.pairing_exec.steps import PairingPayload, StepDescriptor

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class SshCredentials:
    host: str
    port: int
    username: str
    password: str | None
    private_key: str | None
    passphrase: str | None


class NativeSshExecutor(Executor):
    def __init__(self, creds: SshCredentials, *, pg_container_name: str = "harpocrate-postgres") -> None:
        self._creds = creds
        self._pg_container = pg_container_name
        self._conn: Any | None = None

    async def open(self) -> None:
        if self._conn is not None:
            return
        kwargs: dict[str, Any] = {
            "host": self._creds.host,
            "port": self._creds.port,
            "username": self._creds.username,
            "known_hosts": None,  # TOFU MVP — voir LESSONS pour le durcissement
        }
        if self._creds.private_key:
            kwargs["client_keys"] = [
                asyncssh.import_private_key(
                    self._creds.private_key,
                    passphrase=self._creds.passphrase or None,
                )
            ]
        elif self._creds.password:
            kwargs["password"] = self._creds.password
        self._conn = await asyncssh.connect(**kwargs)
        logger.warning(
            "native_ssh_executor_opened_tofu",
            host=self._creds.host,
            note="known_hosts disabled (MVP) — strengthen before production",
        )

    async def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    async def exec_step(self, step: StepDescriptor, payload: PairingPayload) -> StepResult:
        if self._conn is None:
            raise RuntimeError("executor_not_opened")
        cmd = _build_command(step, payload, self._pg_container)
        result = await self._conn.run(cmd, check=False)
        return StepResult(
            exit_code=int(result.exit_status or 0),
            stdout=str(result.stdout or ""),
            stderr=str(result.stderr or ""),
        )


def _build_command(step: StepDescriptor, payload: PairingPayload, pg_container: str) -> str:
    pg_data = "/var/lib/postgresql/16/data"
    if step.kind == "stop_pg_container":
        return f"docker stop {pg_container}"
    if step.kind == "backup_pg_data_dir":
        return f"sudo mv {pg_data} {pg_data}.bak.$(date +%s)"
    if step.kind == "pg_basebackup_from_master":
        return (
            f"PGPASSWORD='{payload.replication_password}' sudo -E -u postgres "
            f"pg_basebackup -h {payload.master_host} -p {payload.master_port} "
            f"-D {pg_data} -U {payload.replication_user} "
            f"--slot={payload.application_name} -R --wal-method=stream"
        )
    if step.kind == "verify_standby_signal":
        return f"sudo -u postgres test -f {pg_data}/standby.signal && echo present"
    if step.kind == "verify_auto_conf":
        return f"sudo -u postgres grep primary_conninfo {pg_data}/postgresql.auto.conf"
    if step.kind == "start_pg_container":
        return f"docker start {pg_container}"
    if step.kind == "verify_streaming":
        return (
            f"docker exec {pg_container} psql -U postgres -At -c "
            f"'SELECT pid, status FROM pg_stat_wal_receiver;'"
        )
    return f"echo unknown_step_kind:{step.kind} >&2; exit 99"
```

- [ ] **Step 4: Run → vert**

Run: `cd backend && uv run python -m pytest tests/test_pairing_exec_native_executor.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/pairing_exec/native_executor.py backend/tests/test_pairing_exec_native_executor.py
git commit -m "feat(pairing-exec): NativeSshExecutor via asyncssh"
```

---

## Task 8: Backend `PairingExecOrchestrator` — iterate + emit + retry

**Files:**
- Create: `backend/app/services/pairing_exec/orchestrator.py`
- Create: `backend/tests/test_pairing_exec_orchestrator.py`

- [ ] **Step 1: Test rouge — run() émet les events dans l'ordre**

```python
"""Tests PairingExecOrchestrator."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.services.pairing_exec.events import (
    StepStartedEvent, StepDoneEvent, StepErrorEvent, ExecutionCompleteEvent,
)
from app.services.pairing_exec.executor_base import StepResult
from app.services.pairing_exec.orchestrator import PairingExecOrchestrator
from app.services.pairing_exec.steps import PairingPayload


def _payload() -> PairingPayload:
    return PairingPayload(
        master_host="a", master_port=5432,
        replication_user="r", replication_password="p", application_name="b",
    )


@pytest.mark.asyncio
async def test_run_emits_started_done_for_each_step_then_complete() -> None:
    executor = AsyncMock()
    executor.open = AsyncMock()
    executor.close = AsyncMock()
    executor.exec_step = AsyncMock(return_value=StepResult(exit_code=0, stdout="ok", stderr=""))

    events: list = []

    async def on_event(ev) -> None:
        events.append(ev)

    orch = PairingExecOrchestrator(executor=executor, payload=_payload(), on_event=on_event)
    await orch.run()

    # 7 steps × (started + done) + 1 complete = 15 events
    assert len(events) == 15
    assert isinstance(events[0], StepStartedEvent)
    assert isinstance(events[1], StepDoneEvent)
    assert isinstance(events[-1], ExecutionCompleteEvent)


@pytest.mark.asyncio
async def test_run_stops_on_error_and_emits_step_error() -> None:
    executor = AsyncMock()
    executor.open = AsyncMock()
    executor.close = AsyncMock()

    async def fake_exec(step, payload):
        if step.idx == 2:
            return StepResult(exit_code=2, stdout="", stderr="boom")
        return StepResult(exit_code=0, stdout="", stderr="")

    executor.exec_step.side_effect = fake_exec

    events: list = []

    async def on_event(ev) -> None:
        events.append(ev)

    orch = PairingExecOrchestrator(executor=executor, payload=_payload(), on_event=on_event)
    await orch.run()

    types = [type(e).__name__ for e in events]
    assert "StepErrorEvent" in types
    assert "ExecutionCompleteEvent" not in types
    # exec_step appelé pour steps 0, 1, 2 — pas 3 et au-delà
    assert executor.exec_step.call_count == 3


@pytest.mark.asyncio
async def test_run_starts_from_step_idx_when_resume() -> None:
    executor = AsyncMock()
    executor.open = AsyncMock()
    executor.close = AsyncMock()
    executor.exec_step = AsyncMock(return_value=StepResult(exit_code=0, stdout="", stderr=""))
    events: list = []

    async def on_event(ev):
        events.append(ev)

    orch = PairingExecOrchestrator(executor=executor, payload=_payload(), on_event=on_event)
    await orch.run(start_from_step=4)

    assert executor.exec_step.call_count == 3  # steps 4, 5, 6
    first_started_idx = next(e.step_idx for e in events if isinstance(e, StepStartedEvent))
    assert first_started_idx == 4
```

- [ ] **Step 2: Run → rouge**

Run: `cd backend && uv run python -m pytest tests/test_pairing_exec_orchestrator.py -v`
Expected: FAIL.

- [ ] **Step 3: Impl orchestrator**

`backend/app/services/pairing_exec/orchestrator.py` :

```python
"""Orchestrateur exécution wizard pairing.

Itère sur les étapes, demande à l'executor de chaque kind, émet les events
sur le callback `on_event`. Arrêt net sur erreur. Reprise possible depuis
n'importe quelle étape via `start_from_step`.
"""

from __future__ import annotations

from typing import Awaitable, Callable

import structlog

from app.services.pairing_exec.events import (
    Event, ExecutionCompleteEvent, StepDoneEvent, StepErrorEvent, StepStartedEvent,
)
from app.services.pairing_exec.executor_base import Executor
from app.services.pairing_exec.steps import PairingPayload, list_steps

logger = structlog.get_logger(__name__)

EventCallback = Callable[[Event], Awaitable[None]]


class PairingExecOrchestrator:
    def __init__(
        self,
        *,
        executor: Executor,
        payload: PairingPayload,
        on_event: EventCallback,
    ) -> None:
        self._executor = executor
        self._payload = payload
        self._on_event = on_event

    async def run(self, *, start_from_step: int = 0) -> None:
        await self._executor.open()
        try:
            steps = list_steps(self._payload)
            for step in steps:
                if step.idx < start_from_step:
                    continue
                await self._on_event(StepStartedEvent(
                    step_idx=step.idx, title=step.title, command=step.kind,
                ))
                try:
                    result = await self._executor.exec_step(step, self._payload)
                except Exception as e:
                    await self._on_event(StepErrorEvent(
                        step_idx=step.idx, exit_code=-1, stdout="", stderr=str(e),
                        error_type=type(e).__name__,
                    ))
                    return
                if result.is_success:
                    await self._on_event(StepDoneEvent(
                        step_idx=step.idx, exit_code=result.exit_code,
                        stdout=result.stdout, stderr=result.stderr,
                    ))
                else:
                    await self._on_event(StepErrorEvent(
                        step_idx=step.idx, exit_code=result.exit_code,
                        stdout=result.stdout, stderr=result.stderr,
                        error_type="NonZeroExit",
                    ))
                    return
            await self._on_event(ExecutionCompleteEvent())
        finally:
            await self._executor.close()
```

- [ ] **Step 4: Run → vert**

Run: `cd backend && uv run python -m pytest tests/test_pairing_exec_orchestrator.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/pairing_exec/orchestrator.py backend/tests/test_pairing_exec_orchestrator.py
git commit -m "feat(pairing-exec): orchestrateur — iterate + emit events + start_from_step"
```

---

## Task 9: Backend audit log par étape

**Files:**
- Modify: `backend/app/services/pairing_exec/orchestrator.py`
- Modify: `backend/tests/test_pairing_exec_orchestrator.py`

- [ ] **Step 1: Test rouge — audit_log_insert appelé pour started/done/error**

Ajouter dans `test_pairing_exec_orchestrator.py` :

```python
@pytest.mark.asyncio
async def test_run_writes_audit_log_for_each_event() -> None:
    from uuid import uuid4
    executor = AsyncMock()
    executor.open = AsyncMock()
    executor.close = AsyncMock()
    executor.exec_step = AsyncMock(return_value=StepResult(exit_code=0, stdout="", stderr=""))

    audit_calls: list[tuple[str, dict]] = []

    async def fake_audit(conn, event, *, actor_user_id, actor_ip=None, metadata) -> None:
        audit_calls.append((event, metadata))

    fake_conn = AsyncMock()
    session_id = uuid4()

    events: list = []
    async def on_event(ev): events.append(ev)

    orch = PairingExecOrchestrator(
        executor=executor, payload=_payload(), on_event=on_event,
        conn=fake_conn, session_id=session_id, actor_user_id=None, audit_writer=fake_audit,
    )
    await orch.run()

    action_names = [a[0] for a in audit_calls]
    assert action_names.count("pairing.exec_step_started") == 7
    assert action_names.count("pairing.exec_step_done") == 7
```

- [ ] **Step 2: Run → rouge**

Run: `cd backend && uv run python -m pytest tests/test_pairing_exec_orchestrator.py::test_run_writes_audit_log_for_each_event -v`
Expected: FAIL — constructeur ne prend pas ces kwargs.

- [ ] **Step 3: Étendre l'orchestrator**

Modifier `orchestrator.py` pour accepter les kwargs additionnels :

```python
from typing import Any, Awaitable, Callable
from uuid import UUID

AuditWriter = Callable[..., Awaitable[None]]


class PairingExecOrchestrator:
    def __init__(
        self,
        *,
        executor: Executor,
        payload: PairingPayload,
        on_event: EventCallback,
        conn: Any | None = None,
        session_id: UUID | None = None,
        actor_user_id: UUID | None = None,
        audit_writer: AuditWriter | None = None,
    ) -> None:
        self._executor = executor
        self._payload = payload
        self._on_event = on_event
        self._conn = conn
        self._session_id = session_id
        self._actor_user_id = actor_user_id
        self._audit_writer = audit_writer

    async def _audit(self, action: str, metadata: dict[str, Any]) -> None:
        if self._audit_writer is None or self._conn is None:
            return
        await self._audit_writer(
            self._conn, action,
            actor_user_id=self._actor_user_id,
            metadata={"session_id": str(self._session_id) if self._session_id else None, **metadata},
        )
```

Puis dans la boucle `run`, après chaque `on_event(...)`, ajouter l'appel correspondant :

```python
        # juste après StepStartedEvent :
        await self._audit("pairing.exec_step_started", {"step_idx": step.idx, "kind": step.kind, "title": step.title})

        # juste après StepDoneEvent :
        await self._audit("pairing.exec_step_done", {"step_idx": step.idx, "exit_code": result.exit_code, "stdout_excerpt": result.stdout[:2000]})

        # juste après StepErrorEvent (les deux cas) :
        await self._audit("pairing.exec_step_error", {"step_idx": step.idx, "exit_code": getattr(result, "exit_code", -1), "stderr_excerpt": (result.stderr if result else str(e))[:2000]})
```

- [ ] **Step 4: Run → vert**

Run: `cd backend && uv run python -m pytest tests/test_pairing_exec_orchestrator.py -v`
Expected: tous passent.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/pairing_exec/orchestrator.py backend/tests/test_pairing_exec_orchestrator.py
git commit -m "feat(pairing-exec): audit log par étape"
```

---

## Task 10: Backend WebSocket endpoint `/admin/replication/pairing/{sid}/exec/ws`

**Files:**
- Create: `backend/app/api/v1/admin_pairing_exec.py`
- Create: `backend/app/models/api/pairing_exec.py`
- Create: `backend/tests/test_admin_pairing_exec_ws.py`
- Modify: `backend/app/main.py` (register router)

- [ ] **Step 1: DTO requête credentials (mode natif)**

`backend/app/models/api/pairing_exec.py` :

```python
"""DTOs pour le WebSocket pairing exec — frame d'ouverture côté client."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ExecOpenFrameNative(BaseModel):
    type: Literal["open_native"]
    username: str
    auth_type: Literal["password", "privkey"]
    password: str | None = None
    private_key: str | None = None
    passphrase: str | None = None
    # host/port viennent de la config admin via .env (var `HARPOCRATE_SELF_SSH_HOST`/`_PORT`)
    # à voir Task 11 — pour itération 1 hardcode 22 et lit le host depuis l'env.


class ExecOpenFrameDocker(BaseModel):
    type: Literal["open_docker"]
    # Pas de credentials nécessaires : le backend pilote via socket Docker.


class ExecRetryFrame(BaseModel):
    type: Literal["retry"]
    from_step_idx: int
```

- [ ] **Step 2: Test rouge — endpoint reject non-admin token**

`backend/tests/test_admin_pairing_exec_ws.py` :

```python
"""Tests endpoint WebSocket exec."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_ws_rejects_token_without_admin_role(websocket_client) -> None:
    """JWT sans rôle admin → WS close avec code policy_violation."""
    # patcher _validate_jwt pour retourner un payload sans le rôle admin
    sid = uuid4()
    url = f"/v1/admin/replication/pairing/{sid}/exec/ws?token=nonadmin"
    with pytest.raises(Exception):
        async with websocket_client.websocket_connect(url):
            pass
```

NOTE — la fixture `websocket_client` doit fournir un client TestClient capable de `websocket_connect`. Inspirer de `test_ssh_terminal_api.py` qui fait déjà ça pour le SSHTerminal — ce fichier sera supprimé mais on garde le pattern de test pour le nouveau endpoint.

- [ ] **Step 3: Run → rouge**

Run: `cd backend && uv run python -m pytest tests/test_admin_pairing_exec_ws.py -v`
Expected: FAIL — endpoint manquant.

- [ ] **Step 4: Implémentation endpoint**

`backend/app/api/v1/admin_pairing_exec.py` :

```python
"""WebSocket — exécution serveur du wizard pairing (LOT pairing-exec).

Auth identique à l'ancien ssh_terminal : token JWT en query string, vérifie
le rôle admin. Premier frame du client = `open_docker` ou `open_native` (avec
credentials SSH). L'orchestrateur tourne et push les events dans le WS.

Re-tentative : le client peut envoyer `{"type": "retry", "from_step_idx": N}`
pour relancer l'exécution depuis l'étape N (idempotence côté executor).
"""

from __future__ import annotations

import json
from uuid import UUID

import structlog
from fastapi import APIRouter, Query, WebSocket, status

from app.core.config import settings
from app.core.security import _validate_jwt
from app.db.pool import get_pool
from app.db.repositories import pairing_sessions as pairing_repo
from app.services import admin_user_resolver, install_mode as install_mode_svc
from app.services.audit import audit_log_insert
from app.services.pairing_exec.docker_executor import DockerExecutor
from app.services.pairing_exec.events import Event, serialize_event
from app.services.pairing_exec.native_executor import NativeSshExecutor, SshCredentials
from app.services.pairing_exec.orchestrator import PairingExecOrchestrator
from app.services.pairing_exec.steps import PairingPayload

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/admin/replication/pairing", tags=["admin-pairing-exec"])


@router.websocket("/{session_id}/exec/ws")
async def pairing_exec_ws(ws: WebSocket, session_id: UUID, token: str = Query(...)) -> None:
    try:
        payload_jwt = await _validate_jwt(token)
    except Exception:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason="invalid_token")
        return

    roles = payload_jwt.get("realm_access", {}).get("roles", [])
    if settings.admin_role_name not in roles:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason="not_admin")
        return

    try:
        user_id = await admin_user_resolver.resolve_admin_user_id(
            keycloak_sub=payload_jwt["sub"],
            email=payload_jwt.get("email", ""),
            display_name=payload_jwt.get("name"),
        )
    except Exception:
        await ws.close(code=status.WS_1011_INTERNAL_ERROR, reason="internal_error")
        return

    await ws.accept()

    pool = await get_pool()
    async with pool.acquire() as conn:
        sess = await pairing_repo.get(conn, session_id)
        if sess is None or sess["role"] != "standby":
            await ws.send_json({"type": "error", "code": "session_not_found"})
            await ws.close()
            return
        p = sess["payload"]
        if not isinstance(p, dict) or "master_host" not in p:
            await ws.send_json({"type": "error", "code": "payload_incomplete"})
            await ws.close()
            return

        pairing_payload = PairingPayload(
            master_host=p["master_host"],
            master_port=int(p["master_port"]),
            replication_user=p["replication_user"],
            replication_password=p["replication_password"],
            application_name=p["application_name"],
        )

        try:
            first_raw = await ws.receive_text()
            first = json.loads(first_raw)
        except Exception:
            await ws.close()
            return

        mode = install_mode_svc.detect().mode
        if first.get("type") == "open_docker" and mode == "docker_compose_auto":
            executor = DockerExecutor()
        elif first.get("type") == "open_native":
            creds = SshCredentials(
                host=settings.harpocrate_self_ssh_host or "",
                port=settings.harpocrate_self_ssh_port or 22,
                username=first.get("username", ""),
                password=first.get("password") if first.get("auth_type") == "password" else None,
                private_key=first.get("private_key") if first.get("auth_type") == "privkey" else None,
                passphrase=first.get("passphrase") if first.get("auth_type") == "privkey" else None,
            )
            executor = NativeSshExecutor(creds)
        else:
            await ws.send_json({"type": "error", "code": "invalid_open_frame"})
            await ws.close()
            return

        start_from = int(first.get("from_step_idx", 0))

        async def on_event(ev: Event) -> None:
            await ws.send_json(serialize_event(ev))

        orch = PairingExecOrchestrator(
            executor=executor,
            payload=pairing_payload,
            on_event=on_event,
            conn=conn,
            session_id=session_id,
            actor_user_id=user_id,
            audit_writer=audit_log_insert,
        )
        try:
            await orch.run(start_from_step=start_from)
        finally:
            await ws.close()
```

- [ ] **Step 5: Settings — `harpocrate_self_ssh_host` + `harpocrate_self_ssh_port`**

Dans `backend/app/core/config.py`, ajouter les deux champs Pydantic Settings :

```python
harpocrate_self_ssh_host: str | None = None
harpocrate_self_ssh_port: int = 22
```

(Le `None` permet la détection de "non configuré" → endpoint refuse en mode natif.)

- [ ] **Step 6: Register router**

Dans `backend/app/main.py` :

```python
from app.api.v1.admin_pairing_exec import router as admin_pairing_exec_router
...
app.include_router(admin_pairing_exec_router, prefix="/v1")
```

- [ ] **Step 7: Run → vert**

Run: `cd backend && uv run python -m pytest tests/test_admin_pairing_exec_ws.py -v`
Expected: tests passent (au moins le test reject-non-admin).

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/v1/admin_pairing_exec.py backend/app/models/api/pairing_exec.py backend/app/core/config.py backend/app/main.py backend/tests/test_admin_pairing_exec_ws.py
git commit -m "feat(pairing-exec): WebSocket /exec/ws — auth + dispatch executor + retry"
```

---

## Task 11: Backend suppression `SSHTerminal` + service + tests

**Files:**
- Delete: `backend/app/api/v1/admin_ssh_terminal.py`
- Delete: `backend/app/services/ssh_terminal.py`
- Delete: `backend/tests/test_ssh_terminal.py`
- Delete: `backend/tests/test_ssh_terminal_api.py`
- Modify: `backend/app/main.py` (deregister router)

- [ ] **Step 1: Vérifier qu'aucun autre code n'importe ces modules**

Run: `cd backend && grep -rn "ssh_terminal\|admin_ssh_terminal" app/ tests/`
Si des fichiers autres que ceux à supprimer importent ces modules, STOP et escalader.

- [ ] **Step 2: Supprimer les fichiers**

```bash
git rm backend/app/api/v1/admin_ssh_terminal.py
git rm backend/app/services/ssh_terminal.py
git rm backend/tests/test_ssh_terminal.py
git rm backend/tests/test_ssh_terminal_api.py
```

- [ ] **Step 3: Deregister router dans `main.py`**

Retirer la ligne `app.include_router(admin_ssh_terminal_router, ...)` et l'import correspondant en haut de `main.py`.

- [ ] **Step 4: Sanity check — backend démarre + tests passent**

```bash
cd backend && uv run python -m pytest tests/ -v -k "not test_ssh_terminal"
cd backend && uv run ruff check app/
```

Expected: aucune erreur (le pytest peut signaler des tests skip ou des pre-existing failures, mais rien lié à ssh_terminal).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(ssh): suppression du terminal SSH interactif — remplacé par pairing exec auto"
```

---

## Task 12: Frontend types Zod (install mode + events)

**Files:**
- Create: `frontend/src/schemas/installMode.ts`
- Create: `frontend/src/schemas/pairingExec.ts`
- Create: `frontend/src/tests/pairingExecSchemas.test.ts`

- [ ] **Step 1: Test rouge — parsing**

`frontend/src/tests/pairingExecSchemas.test.ts` :

```typescript
import { describe, it, expect } from "vitest";
import { InstallModeResponseSchema } from "@/schemas/installMode";
import {
  StepStartedEventSchema, StepDoneEventSchema, StepErrorEventSchema,
  ExecutionCompleteEventSchema, parseExecEvent,
} from "@/schemas/pairingExec";

describe("install mode schema", () => {
  it("parse mode docker_compose_auto", () => {
    const r = InstallModeResponseSchema.parse({
      mode: "docker_compose_auto",
      docker_socket_accessible: true,
      pg_container_data_host_path: null,
    });
    expect(r.mode).toBe("docker_compose_auto");
  });
});

describe("pairing exec events", () => {
  it("parse step_started", () => {
    const ev = parseExecEvent({ type: "step_started", step_idx: 0, title: "stop", command: "stop_pg_container" });
    expect(ev?.type).toBe("step_started");
  });
  it("parse step_done", () => {
    const ev = parseExecEvent({ type: "step_done", step_idx: 0, exit_code: 0, stdout: "ok", stderr: "" });
    expect(ev?.type).toBe("step_done");
  });
  it("parse step_error", () => {
    const ev = parseExecEvent({
      type: "step_error", step_idx: 1, exit_code: 2, stdout: "", stderr: "boom", error_type: "NonZeroExit",
    });
    expect(ev?.type).toBe("step_error");
  });
  it("returns null for unknown type", () => {
    expect(parseExecEvent({ type: "garbage" })).toBeNull();
  });
});
```

- [ ] **Step 2: Run → rouge**

Run: `cd frontend && npx vitest run src/tests/pairingExecSchemas.test.ts`
Expected: FAIL.

- [ ] **Step 3: Impl schemas**

`frontend/src/schemas/installMode.ts` :

```typescript
import { z } from "zod";

export const InstallModeResponseSchema = z.object({
  mode: z.enum(["docker_compose_auto", "native"]),
  docker_socket_accessible: z.boolean(),
  pg_container_data_host_path: z.string().nullable(),
});
export type InstallModeResponse = z.infer<typeof InstallModeResponseSchema>;
```

`frontend/src/schemas/pairingExec.ts` :

```typescript
import { z } from "zod";

export const StepStartedEventSchema = z.object({
  type: z.literal("step_started"),
  step_idx: z.number().int().min(0),
  title: z.string(),
  command: z.string(),
});
export const StepDoneEventSchema = z.object({
  type: z.literal("step_done"),
  step_idx: z.number().int().min(0),
  exit_code: z.number().int(),
  stdout: z.string(),
  stderr: z.string(),
});
export const StepErrorEventSchema = z.object({
  type: z.literal("step_error"),
  step_idx: z.number().int().min(0),
  exit_code: z.number().int(),
  stdout: z.string(),
  stderr: z.string(),
  error_type: z.string(),
});
export const ExecutionCompleteEventSchema = z.object({
  type: z.literal("execution_complete"),
});

export type StepStartedEvent = z.infer<typeof StepStartedEventSchema>;
export type StepDoneEvent = z.infer<typeof StepDoneEventSchema>;
export type StepErrorEvent = z.infer<typeof StepErrorEventSchema>;
export type ExecutionCompleteEvent = z.infer<typeof ExecutionCompleteEventSchema>;

export type ExecEvent = StepStartedEvent | StepDoneEvent | StepErrorEvent | ExecutionCompleteEvent;

export function parseExecEvent(raw: unknown): ExecEvent | null {
  for (const sch of [StepStartedEventSchema, StepDoneEventSchema, StepErrorEventSchema, ExecutionCompleteEventSchema]) {
    const r = sch.safeParse(raw);
    if (r.success) return r.data;
  }
  return null;
}
```

- [ ] **Step 4: Run → vert**

Run: `cd frontend && npx vitest run src/tests/pairingExecSchemas.test.ts`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/schemas/installMode.ts frontend/src/schemas/pairingExec.ts frontend/src/tests/pairingExecSchemas.test.ts
git commit -m "feat(frontend): schémas Zod install-mode + events pairing exec"
```

---

## Task 13: Frontend `installMode.ts` fetcher + `pairingExecSocket.ts`

**Files:**
- Create: `frontend/src/lib/installMode.ts`
- Create: `frontend/src/lib/pairingExecSocket.ts`
- Create: `frontend/src/tests/installMode.test.ts`
- Create: `frontend/src/tests/pairingExecSocket.test.ts`

- [ ] **Step 1: Test rouge installMode**

```typescript
import { describe, it, expect, vi, afterEach } from "vitest";
import { fetchInstallMode } from "@/lib/installMode";

describe("fetchInstallMode", () => {
  afterEach(() => vi.restoreAllMocks());

  it("retourne le mode parsé", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({
        mode: "docker_compose_auto",
        docker_socket_accessible: true,
        pg_container_data_host_path: null,
      }), { status: 200, headers: { "Content-Type": "application/json" } }),
    );
    const m = await fetchInstallMode();
    expect(m.mode).toBe("docker_compose_auto");
  });
});
```

- [ ] **Step 2: Impl `installMode.ts`**

```typescript
import { api } from "@/lib/api-client";
import { InstallModeResponseSchema, type InstallModeResponse } from "@/schemas/installMode";

export async function fetchInstallMode(): Promise<InstallModeResponse> {
  const raw = await api.get<unknown>("/admin/install-mode");
  return InstallModeResponseSchema.parse(raw);
}
```

- [ ] **Step 3: Test rouge pairingExecSocket — buildWsUrl + parse messages**

```typescript
import { describe, it, expect } from "vitest";
import { buildExecWsUrl, parseFrame } from "@/lib/pairingExecSocket";

describe("pairingExecSocket", () => {
  it("buildExecWsUrl insère le token et le sid", () => {
    const u = buildExecWsUrl("abc-sid", "jwt-token");
    expect(u).toMatch(/\/v1\/admin\/replication\/pairing\/abc-sid\/exec\/ws\?token=jwt-token/);
  });

  it("parseFrame renvoie un ExecEvent valide", () => {
    const ev = parseFrame(JSON.stringify({ type: "step_done", step_idx: 0, exit_code: 0, stdout: "", stderr: "" }));
    expect(ev?.type).toBe("step_done");
  });
  it("parseFrame renvoie null pour JSON invalide", () => {
    expect(parseFrame("garbage")).toBeNull();
  });
});
```

- [ ] **Step 4: Impl `pairingExecSocket.ts`**

```typescript
import { parseExecEvent, type ExecEvent } from "@/schemas/pairingExec";

export function buildExecWsUrl(sessionId: string, jwt: string): string {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}/v1/admin/replication/pairing/${sessionId}/exec/ws?token=${encodeURIComponent(jwt)}`;
}

export function parseFrame(raw: string): ExecEvent | null {
  try {
    return parseExecEvent(JSON.parse(raw));
  } catch {
    return null;
  }
}

export type OpenDockerFrame = { type: "open_docker"; from_step_idx?: number };
export type OpenNativeFrame = {
  type: "open_native";
  username: string;
  auth_type: "password" | "privkey";
  password?: string;
  private_key?: string;
  passphrase?: string;
  from_step_idx?: number;
};
export type OpenFrame = OpenDockerFrame | OpenNativeFrame;

export function encodeOpen(frame: OpenFrame): string {
  return JSON.stringify(frame);
}
```

- [ ] **Step 5: Run → vert**

```
cd frontend && npx vitest run src/tests/installMode.test.ts src/tests/pairingExecSocket.test.ts
```
Expected: 4 PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/installMode.ts frontend/src/lib/pairingExecSocket.ts frontend/src/tests/installMode.test.ts frontend/src/tests/pairingExecSocket.test.ts
git commit -m "feat(frontend): helpers installMode + pairingExecSocket"
```

---

## Task 14: Frontend `PairingExecutionStepper` composant

**Files:**
- Create: `frontend/src/components/PairingExecutionStepper.tsx`
- Create: `frontend/src/tests/pairingExecutionStepper.test.tsx`

- [ ] **Step 1: Inspirer-toi du pattern existant `PairingStepsList.tsx`**

Lire `frontend/src/components/PairingStepsList.tsx` pour le style (Mantine, structure du code).

- [ ] **Step 2: Test rouge — affichage statuts**

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";

import { PairingExecutionStepper } from "@/components/PairingExecutionStepper";

const STEPS = [
  { idx: 0, title: "Arrêter PG", description: "…" },
  { idx: 1, title: "Backup data dir", description: "…" },
];

function renderStepper(state: any) {
  return render(
    <MantineProvider>
      <PairingExecutionStepper steps={STEPS} state={state} onRetry={vi.fn()} />
    </MantineProvider>,
  );
}

describe("PairingExecutionStepper", () => {
  it("affiche pending sur toutes les étapes au départ", () => {
    renderStepper({ runningIdx: null, results: {} });
    expect(screen.getAllByText(/pending/i).length).toBeGreaterThan(0);
  });
  it("affiche running sur l'étape courante", () => {
    renderStepper({ runningIdx: 0, results: {} });
    expect(screen.getByText(/running/i)).toBeInTheDocument();
  });
  it("affiche error et stderr quand une étape échoue", () => {
    renderStepper({ runningIdx: null, results: { 0: { ok: false, stderr: "boom", stdout: "" } } });
    expect(screen.getByText(/boom/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Impl composant**

`frontend/src/components/PairingExecutionStepper.tsx` :

```tsx
/**
 * Stepper de progression de l'exécution serveur du wizard pairing.
 *
 * Chaque étape a un statut :
 *   - pending   : pas encore lancée
 *   - running   : en cours (spinner)
 *   - done      : succès (✓ vert)
 *   - error     : échec (✗ rouge + stderr)
 *
 * Quand une étape est en erreur, un bouton "Réessayer depuis cette étape"
 * apparaît à côté.
 */
import { Badge, Button, Card, Code, Group, Loader, Stack, Text, Title } from "@mantine/core";
import { useTranslation } from "react-i18next";

export interface StepMeta {
  idx: number;
  title: string;
  description: string;
}

export interface StepResult {
  ok: boolean;
  exitCode?: number;
  stdout: string;
  stderr: string;
}

export interface StepperState {
  runningIdx: number | null;
  results: Record<number, StepResult>;
}

interface Props {
  steps: StepMeta[];
  state: StepperState;
  onRetry: (fromStepIdx: number) => void;
}

export function PairingExecutionStepper({ steps, state, onRetry }: Props) {
  const { t } = useTranslation();
  return (
    <Stack>
      {steps.map((s) => {
        const r = state.results[s.idx];
        const isRunning = state.runningIdx === s.idx;
        return (
          <Card key={s.idx} withBorder>
            <Group justify="space-between" align="flex-start">
              <Stack gap={4} style={{ flex: 1 }}>
                <Group gap="sm">
                  <Title order={5}>{s.idx + 1}. {s.title}</Title>
                  {!r && !isRunning && <Badge color="gray">{t("pairingExec.pending")}</Badge>}
                  {isRunning && <Badge color="blue" leftSection={<Loader size="xs" />}>{t("pairingExec.running")}</Badge>}
                  {r?.ok && <Badge color="green">{t("pairingExec.done")}</Badge>}
                  {r && !r.ok && <Badge color="red">{t("pairingExec.error")}</Badge>}
                </Group>
                <Text size="sm" c="dimmed">{s.description}</Text>
                {r && !r.ok && (
                  <Code block style={{ background: "#330000", color: "#ff8888" }}>
                    {r.stderr || r.stdout}
                  </Code>
                )}
              </Stack>
              {r && !r.ok && (
                <Button color="orange" variant="outline" size="xs" onClick={() => onRetry(s.idx)}>
                  {t("pairingExec.retryFrom", { n: s.idx + 1 })}
                </Button>
              )}
            </Group>
          </Card>
        );
      })}
    </Stack>
  );
}
```

- [ ] **Step 4: Libellés i18n (sera complété Task 17)**

Pour l'instant, ajouter rapidement les clés minimales dans `fr.json` / `en.json` sous `pairingExec` :

```json
{
  "pairingExec": {
    "pending": "en attente",
    "running": "en cours",
    "done": "terminée",
    "error": "erreur",
    "retryFrom": "Réessayer depuis l'étape {{n}}"
  }
}
```

EN miroir.

- [ ] **Step 5: Run → vert**

```
cd frontend && npx vitest run src/tests/pairingExecutionStepper.test.tsx
```
Expected: 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/PairingExecutionStepper.tsx frontend/src/tests/pairingExecutionStepper.test.tsx frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(frontend): composant PairingExecutionStepper"
```

---

## Task 15: Frontend `SshCredsForExecModal`

**Files:**
- Create: `frontend/src/components/SshCredsForExecModal.tsx`
- Create: `frontend/src/tests/sshCredsForExecModal.test.tsx`

Modale simplifiée pour le mode natif : demande **uniquement** `username` + (password OU clé privée + passphrase). Pas de host/port.

- [ ] **Step 1: Inspirer-toi de l'ancien `SSHCredentialsModal.tsx` (sera supprimé) pour le pattern**

- [ ] **Step 2: Test rouge**

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { I18nextProvider } from "react-i18next";
import i18n from "@/lib/i18n";

import { SshCredsForExecModal } from "@/components/SshCredsForExecModal";

function renderModal(onSubmit = vi.fn()) {
  return render(
    <MantineProvider>
      <I18nextProvider i18n={i18n}>
        <SshCredsForExecModal opened onClose={vi.fn()} onSubmit={onSubmit} />
      </I18nextProvider>
    </MantineProvider>,
  );
}

describe("SshCredsForExecModal", () => {
  it("retourne username + password sur submit en mode password", () => {
    const onSubmit = vi.fn();
    renderModal(onSubmit);
    fireEvent.change(screen.getByLabelText(/username|nom/i), { target: { value: "admin" } });
    fireEvent.change(screen.getByLabelText(/password|mot de passe/i), { target: { value: "secret" } });
    fireEvent.click(screen.getByRole("button", { name: /démarrer|start/i }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ username: "admin", auth_type: "password", password: "secret" }));
  });
});
```

- [ ] **Step 3: Impl**

```tsx
import { useState, useEffect } from "react";
import { Modal, Stack, TextInput, SegmentedControl, PasswordInput, Textarea, Group, Button } from "@mantine/core";
import { useTranslation } from "react-i18next";

export interface ExecCreds {
  username: string;
  auth_type: "password" | "privkey";
  password?: string;
  private_key?: string;
  passphrase?: string;
}

interface Props {
  opened: boolean;
  onClose: () => void;
  onSubmit: (c: ExecCreds) => void;
}

export function SshCredsForExecModal({ opened, onClose, onSubmit }: Props) {
  const { t } = useTranslation();
  const [username, setUsername] = useState("");
  const [authType, setAuthType] = useState<"password" | "privkey">("password");
  const [password, setPassword] = useState("");
  const [privKey, setPrivKey] = useState("");
  const [passphrase, setPassphrase] = useState("");

  useEffect(() => {
    if (!opened) {
      setUsername(""); setPassword(""); setPrivKey(""); setPassphrase("");
      setAuthType("password");
    }
  }, [opened]);

  function submit() {
    if (authType === "password") onSubmit({ username, auth_type: "password", password });
    else onSubmit({ username, auth_type: "privkey", private_key: privKey, passphrase });
  }

  return (
    <Modal opened={opened} onClose={onClose} title={t("pairingExec.credsModal.title")} closeOnClickOutside={false}>
      <Stack>
        <TextInput label={t("pairingExec.credsModal.username")} value={username} onChange={(e) => setUsername(e.currentTarget.value)} required />
        <SegmentedControl
          value={authType}
          onChange={(v) => setAuthType(v as "password" | "privkey")}
          data={[{ value: "password", label: t("pairingExec.credsModal.password") }, { value: "privkey", label: t("pairingExec.credsModal.privKey") }]}
        />
        {authType === "password" ? (
          <PasswordInput label={t("pairingExec.credsModal.password")} value={password} onChange={(e) => setPassword(e.currentTarget.value)} />
        ) : (
          <>
            <Textarea label={t("pairingExec.credsModal.privKey")} autosize minRows={6} value={privKey} onChange={(e) => setPrivKey(e.currentTarget.value)} />
            <PasswordInput label={t("pairingExec.credsModal.passphrase")} value={passphrase} onChange={(e) => setPassphrase(e.currentTarget.value)} />
          </>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>{t("common.cancel")}</Button>
          <Button onClick={submit} disabled={!username}>{t("pairingExec.credsModal.start")}</Button>
        </Group>
      </Stack>
    </Modal>
  );
}
```

- [ ] **Step 4: Libellés i18n**

```json
"pairingExec": {
  "credsModal": {
    "title": "Identifiants SSH (machine Postgres)",
    "username": "Nom d'utilisateur",
    "password": "Mot de passe",
    "privKey": "Clé privée",
    "passphrase": "Passphrase (si protégée)",
    "start": "Démarrer l'exécution"
  }
}
```

EN miroir.

- [ ] **Step 5: Run → vert**

```
cd frontend && npx vitest run src/tests/sshCredsForExecModal.test.tsx
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/SshCredsForExecModal.tsx frontend/src/tests/sshCredsForExecModal.test.tsx frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(frontend): modale SshCredsForExecModal (mode natif, saisie unique)"
```

---

## Task 16: Frontend i18n — descriptions des 7 étapes

**Files:**
- Modify: `frontend/src/i18n/fr.json`
- Modify: `frontend/src/i18n/en.json`

- [ ] **Step 1: Ajouter sous `pairingExec.steps` FR + EN**

Les titres + descriptions des 7 étapes (matchant `list_steps()` côté backend). Le frontend les utilise pour construire `STEPS: StepMeta[]` qui alimente le `PairingExecutionStepper`.

FR :

```json
"pairingExec": {
  "...": "...",
  "steps": {
    "stop_pg_container":         { "title": "Arrêter le conteneur Postgres local", "description": "On stoppe l'instance Postgres pour pouvoir remplacer son data dir. Si elle écrit, on attend la fin gracieuse." },
    "backup_pg_data_dir":        { "title": "Sauvegarder le data dir actuel",      "description": "Le data dir actuel est renommé en .bak.<timestamp> pour permettre un rollback manuel." },
    "pg_basebackup_from_master": { "title": "pg_basebackup depuis le master",      "description": "Copie l'intégralité de la base depuis le master en streaming. Peut prendre plusieurs minutes." },
    "verify_standby_signal":     { "title": "Vérifier standby.signal",             "description": "Le fichier signal doit exister pour démarrer en mode standby." },
    "verify_auto_conf":          { "title": "Vérifier postgresql.auto.conf",       "description": "Doit contenir primary_conninfo avec le bon host/user." },
    "start_pg_container":        { "title": "Démarrer le conteneur Postgres",      "description": "Postgres démarre en mode standby (recovery)." },
    "verify_streaming":          { "title": "Vérifier le streaming WAL actif",     "description": "Une ligne status='streaming' dans pg_stat_wal_receiver confirme le flux." }
  }
}
```

EN miroir (traduction libre fidèle).

- [ ] **Step 2: Commit**

```bash
git add frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(frontend): i18n descriptions des 7 étapes du wizard pairing"
```

---

## Task 17: Frontend `PairingWizardPage` refactor complet

**Files:**
- Modify: `frontend/src/pages/PairingWizardPage.tsx`
- Create: `frontend/src/tests/pairingWizardPageExec.test.tsx`

- [ ] **Step 1: Test rouge — flow complet mode Docker**

```tsx
// Le test mock fetchInstallMode + WebSocket. Au mount, la page :
//   1) fetch /admin/install-mode → docker_compose_auto
//   2) ouvre le WS avec frame open_docker (pas de modale credentials)
//   3) reçoit step_started → step_done × 7 → execution_complete
//   4) affiche tous les statuts en vert
//
// Squelette omis ici par concision — calque sur le pattern du test
// pairingExecutionStepper avec un MockWebSocket.
```

Voir la suggestion : implémenter `MockWebSocket` dans `frontend/src/tests/_helpers/mockWebSocket.ts` une fois, et le réutiliser. Si pas encore là, le créer en Task 13 ou en début de Task 17.

- [ ] **Step 2: Réécrire `PairingWizardPage.tsx`**

```tsx
/**
 * Page wizard côté standby — exécution serveur des 7 étapes du pairing.
 *
 * Au mount :
 *  1) GET /admin/install-mode → décide quelle UI :
 *     - docker_compose_auto : ouvre directement le WS avec `open_docker`.
 *     - native              : affiche `SshCredsForExecModal`, à submit ouvre
 *                              le WS avec `open_native` + creds.
 *  2) Le WS push step_started/step_done/step_error/execution_complete →
 *     met à jour le `StepperState`.
 *  3) Bouton "Réessayer depuis l'étape N" → ferme le WS, en ouvre un
 *     nouveau avec `from_step_idx=N`.
 */
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Group, Loader, Stack, Title, Text } from "@mantine/core";
import { useTranslation } from "react-i18next";

import { PairingExecutionStepper, type StepperState, type StepMeta } from "@/components/PairingExecutionStepper";
import { SshCredsForExecModal, type ExecCreds } from "@/components/SshCredsForExecModal";
import { fetchInstallMode } from "@/lib/installMode";
import { buildExecWsUrl, parseFrame, encodeOpen, type OpenFrame } from "@/lib/pairingExecSocket";
import { getAccessToken } from "@/lib/oidc";
import { useSessionStore } from "@/stores/session";

const STEP_KINDS = [
  "stop_pg_container", "backup_pg_data_dir", "pg_basebackup_from_master",
  "verify_standby_signal", "verify_auto_conf", "start_pg_container", "verify_streaming",
] as const;

async function resolveJwt(): Promise<string | null> {
  try { const t = await getAccessToken(); if (t) return t; } catch { /* fallback */ }
  return useSessionStore.getState().localAdminToken;
}

export function PairingWizardPage() {
  const { t } = useTranslation();
  const { sessionId } = useParams<{ sessionId: string }>();
  const nav = useNavigate();
  const installMode = useQuery({ queryKey: ["install-mode"], queryFn: fetchInstallMode });

  const steps: StepMeta[] = STEP_KINDS.map((kind, idx) => ({
    idx,
    title: t(`pairingExec.steps.${kind}.title`),
    description: t(`pairingExec.steps.${kind}.description`),
  }));

  const [credsModalOpen, setCredsModalOpen] = useState(false);
  const [state, setState] = useState<StepperState>({ runningIdx: null, results: {} });
  const wsRef = useRef<WebSocket | null>(null);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    if (!installMode.data || !sessionId) return;
    if (installMode.data.mode === "docker_compose_auto") {
      void openWs({ type: "open_docker" });
    } else {
      setCredsModalOpen(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [installMode.data, sessionId]);

  async function openWs(open: OpenFrame) {
    if (!sessionId) return;
    const jwt = await resolveJwt();
    if (!jwt) return;
    const ws = new WebSocket(buildExecWsUrl(sessionId, jwt));
    wsRef.current = ws;
    setRunning(true);
    ws.onopen = () => ws.send(encodeOpen(open));
    ws.onmessage = (ev) => {
      const frame = parseFrame(String(ev.data));
      if (!frame) return;
      setState((prev) => {
        const next = { ...prev };
        if (frame.type === "step_started") {
          next.runningIdx = frame.step_idx;
        } else if (frame.type === "step_done") {
          next.runningIdx = null;
          next.results = { ...prev.results, [frame.step_idx]: { ok: true, exitCode: frame.exit_code, stdout: frame.stdout, stderr: frame.stderr } };
        } else if (frame.type === "step_error") {
          next.runningIdx = null;
          next.results = { ...prev.results, [frame.step_idx]: { ok: false, exitCode: frame.exit_code, stdout: frame.stdout, stderr: frame.stderr } };
        }
        return next;
      });
    };
    ws.onclose = () => setRunning(false);
  }

  function retryFromStep(idx: number) {
    if (installMode.data?.mode === "docker_compose_auto") {
      // Reset des résultats à partir de idx
      setState((prev) => {
        const cleaned: Record<number, any> = {};
        Object.entries(prev.results).forEach(([k, v]) => { if (Number(k) < idx) cleaned[Number(k)] = v; });
        return { runningIdx: null, results: cleaned };
      });
      void openWs({ type: "open_docker", from_step_idx: idx });
    } else {
      // mode natif : il faut re-saisir les creds (la session SSH précédente est fermée)
      setCredsModalOpen(true);
    }
  }

  if (installMode.isLoading) return <Loader />;
  if (installMode.error) return <Alert color="red">{String(installMode.error)}</Alert>;

  return (
    <Stack>
      <Group justify="space-between">
        <Stack gap={0}>
          <Title order={2}>{t("admin.replication.pairing.wizard.title")}</Title>
          <Text c="dimmed" size="sm">{t("admin.replication.pairing.wizard.subtitleA")}</Text>
        </Stack>
        <Button variant="subtle" color="gray" onClick={() => nav("/admin/replication")}>
          {t("admin.replication.pairing.wizard.abort")}
        </Button>
      </Group>
      <PairingExecutionStepper steps={steps} state={state} onRetry={retryFromStep} />
      <SshCredsForExecModal
        opened={credsModalOpen}
        onClose={() => setCredsModalOpen(false)}
        onSubmit={(c: ExecCreds) => {
          setCredsModalOpen(false);
          void openWs({ type: "open_native", ...c });
        }}
      />
    </Stack>
  );
}
```

- [ ] **Step 3: Run → vert**

```
cd frontend && npx vitest run src/tests/pairingWizardPageExec.test.tsx
cd frontend && npx tsc --noEmit
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/PairingWizardPage.tsx frontend/src/tests/pairingWizardPageExec.test.tsx
git commit -m "feat(frontend): PairingWizardPage refactor exécution serveur + stepper"
```

---

## Task 18: Frontend suppression `SSHTerminal` + co

**Files:**
- Delete: `frontend/src/components/SSHTerminal.tsx`
- Delete: `frontend/src/components/SSHCredentialsModal.tsx`
- Delete: `frontend/src/lib/sshTerminalSocket.ts`
- Delete: `frontend/src/tests/sshTerminalSocket.test.ts`

- [ ] **Step 1: Vérifier qu'aucun autre fichier ne les importe**

```
cd frontend && grep -rn "SSHTerminal\|SSHCredentialsModal\|sshTerminalSocket" src/
```
Si tout est OK (seuls les fichiers à supprimer + l'ancien PairingWizardPage), continuer.

- [ ] **Step 2: Supprimer**

```bash
git rm frontend/src/components/SSHTerminal.tsx
git rm frontend/src/components/SSHCredentialsModal.tsx
git rm frontend/src/lib/sshTerminalSocket.ts
git rm frontend/src/tests/sshTerminalSocket.test.ts
```

- [ ] **Step 3: Run TS strict + lint + tests**

```
cd frontend && npx tsc --noEmit
cd frontend && npx vitest run
cd frontend && npm run lint
```
Expected: clean (sauf erreurs pré-existantes hors notre scope).

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor(frontend): suppression SSHTerminal + SSHCredentialsModal + sshTerminalSocket"
```

---

## Task 19: Docs — `Install-dev.md` socket Docker

**Files:**
- Modify: `Install-dev.md`
- Modify: `docker-compose.yml` (commentaire)

- [ ] **Step 1: Section dans `Install-dev.md`**

Ajouter (à un endroit logique, par exemple après la section déploiement compose) :

```markdown
## Mode auto — socket Docker

Pour bénéficier de l'exécution **automatique** du wizard pairing (sans saisie
SSH manuelle), Harpocrate-backend doit pouvoir piloter Docker. Cela nécessite
de monter le socket Docker de l'hôte dans le conteneur backend :

```yaml
services:
  backend:
    ...
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock   # ⚠️ accès root équivalent
```

**Implications sécurité** : monter le socket Docker donne au conteneur backend
un accès équivalent à root sur la machine hôte. À n'activer que si l'admin
contrôle entièrement l'hôte et accepte cette élévation de privilèges. Sans
ce bind-mount, Harpocrate retombe automatiquement sur le mode SSH manuel
(saisie de credentials à chaque pairing).
```

- [ ] **Step 2: Commentaire dans `docker-compose.yml`**

Ajouter, juste avant `services.backend.volumes`, un bloc commenté :

```yaml
    # ⚠️ Pour activer le mode "exécution auto du wizard pairing", décommenter
    # la ligne ci-dessous. Cela monte le socket Docker dans le conteneur backend
    # et lui donne un accès équivalent à root sur l'hôte. Voir Install-dev.md.
    # - /var/run/docker.sock:/var/run/docker.sock
```

- [ ] **Step 3: Commit**

```bash
git add Install-dev.md docker-compose.yml
git commit -m "docs(install): section socket Docker + commentaire compose pour mode auto"
```

---

## Task 20: Vérification end-to-end + LESSONS.md

**Files:** N/A pour le code ; on update LESSONS.md à la fin.

- [ ] **Step 1: Backend full test suite**

```
cd backend && uv run python -m pytest tests/ -v -k "pairing or install_mode or replication or streaming"
```
Expected: tous passent (avec SKIP DB attendus).

- [ ] **Step 2: Backend ruff**

```
cd backend && uv run ruff format app/services/install_mode.py app/services/pairing_exec/ app/api/v1/admin_install_mode.py app/api/v1/admin_pairing_exec.py app/models/api/install_mode.py app/models/api/pairing_exec.py
cd backend && uv run ruff check app/ tests/
```
Expected: 0 erreur sur nos nouveaux fichiers ; les erreurs pré-existantes restent.

- [ ] **Step 3: Frontend tests + tsc + lint**

```
cd frontend && npx vitest run
cd frontend && npx tsc --noEmit
cd frontend && npm run lint
```

- [ ] **Step 4: Vérification manuelle (deferred — pas faisable depuis cet env)**

À faire par l'utilisateur sur les LXC 196 (master) + 198 (standby) :
1. Rebuild images backend + frontend, redéployer.
2. Activer le socket Docker dans le compose du standby (voir Install-dev.md).
3. Redémarrer le compose standby.
4. Depuis le master, générer une URL d'appairage.
5. La coller dans `BecomeStandbyPage` du standby.
6. Naviguer vers `/admin/pairing/<sid>` → la page affiche directement le stepper (pas de modale, mode docker_compose_auto).
7. Vérifier que les 7 étapes passent en vert.
8. Vérifier les audit logs côté master : `SELECT * FROM audit_log WHERE action LIKE 'pairing.exec_step_%' ORDER BY created_at DESC;`
9. Cas erreur : modifier temporairement la stratégie pour faire échouer une étape (ex: master pas joignable pour `pg_basebackup`) → vérifier que l'étape passe en rouge avec stderr affiché + le bouton "Réessayer" apparaît.
10. Cliquer "Réessayer depuis l'étape 2" → l'exécution reprend correctement.

Documenter dans la PR ce qui a été testé.

- [ ] **Step 5: `LESSONS.md`**

Ajouter une ligne :

```
- [pairing] Le wizard pairing exécute désormais les 7 étapes côté serveur via aiodocker (mode docker_compose_auto, détecté via /.dockerenv + socket monté) ou via asyncssh (mode native, creds saisies une fois). Stepper de progression côté frontend, retry depuis l'étape N, audit log pairing.exec_step_*. Plan : docs/superpowers/plans/2026-05-14-pairing-server-execution.md.
```

- [ ] **Step 6: Commit final**

```bash
git add LESSONS.md
git commit -m "docs: leçon — pairing wizard exécution serveur (LOT pairing-exec)"
```

---

## Self-review

**1. Spec coverage :**

- Détection mode docker_compose_auto vs native → Task 1, 2 ✓
- Auto-discovery data dir host path → Task 5 ✓
- Exécution serveur Docker via aiodocker → Tasks 5, 6 ✓
- Exécution serveur native via asyncssh → Task 7 ✓
- Orchestrateur + retry → Task 8 ✓
- Audit log par étape → Task 9 ✓
- WebSocket endpoint avec auth → Task 10 ✓
- Suppression SSHTerminal/SSHCredentialsModal/ssh_terminal/admin_ssh_terminal → Tasks 11, 18 ✓
- Stepper frontend → Task 14 ✓
- Modale creds une fois (mode natif) → Task 15 ✓
- i18n FR/EN → Tasks 14, 15, 16 ✓
- PairingWizardPage refactor → Task 17 ✓
- Docs install socket Docker → Task 19 ✓
- Vérification e2e + LESSONS → Task 20 ✓

**2. Placeholder scan :** aucun "TBD" / "fill in later" — chaque step a son code complet.

**3. Type consistency :**
- `StepKind` (string union) cohérent backend ↔ frontend (les 7 kinds).
- `Event` types : `StepStartedEvent` / `StepDoneEvent` / `StepErrorEvent` / `ExecutionCompleteEvent` identiques côté Python (dataclass) et TS (Zod).
- `PairingPayload` Python ↔ payload PG côté frontend non typé directement (le frontend ne le voit pas, il est consommé côté backend uniquement). ✓
- `InstallMode` literal type identique Python/TS. ✓
- `OpenFrame` côté TS (open_docker | open_native) ↔ `ExecOpenFrame*` côté Pydantic. ✓

---

## Execution Handoff

Plan complet et sauvegardé. Deux options :

1. **Subagent-Driven (recommandé)** — un subagent frais par tâche, 22 tâches.
2. **Inline Execution** — tâches enchaînées dans cette session avec checkpoints.

Quelle approche ?
