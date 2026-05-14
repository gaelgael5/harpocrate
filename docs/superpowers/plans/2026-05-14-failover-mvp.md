# Failover MVP — promotion manuelle du standby

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre à un admin de promouvoir le standby en master via un bouton UI, lors d'un failover planifié ou suite à une panne du master, sans risque de split-brain accidentel.

**Architecture:** Endpoint `POST /v1/admin/replication/promote` qui exige une confirmation explicite "ancien master arrêté", exécute `pg_promote()`, met à jour `replication.is_standby_of = NULL` dans `system_metadata`, écrit un audit log. UI : bouton sur la page Réplication (visible uniquement si rôle = standby), modale de confirmation à 2 cases à cocher (master down + clients à reconfigurer), reload après succès.

**Tech Stack:** FastAPI + asyncpg pour le backend, React + TanStack Query + Mantine + i18next pour le front, pytest + Vitest pour les tests. Aucune nouvelle dépendance.

**Hors scope (itérations futures) :**
- Rebuild de l'ancien master en nouveau standby (pg_basebackup en sens inverse)
- Détection automatique de la perte du master (heartbeat inter-instances)
- Quorum/witness pour failover automatique
- Demote distant de l'ancien master via HTTPS

---

## File Structure

**Backend** :
- Modifier : `backend/app/api/v1/admin_replication.py` (ajouter 2 endpoints : `GET /can-promote`, `POST /promote`)
- Modifier : `backend/app/services/streaming_replication.py` (ajouter `promote_standby_to_master()` + `get_promote_eligibility()`)
- Modifier : `backend/app/models/api/replication.py` ou nouveau fichier — DTOs Pydantic `PromoteRequest`, `PromoteResponse`, `CanPromoteResponse`
- Modifier : `backend/app/services/audit.py` ou similaire — pas de changement si l'audit générique suffit (action = `"replication.promoted_to_master"`)

**Backend tests** :
- Nouveau : `backend/tests/test_admin_replication_promote.py`
- Nouveau : `backend/tests/test_streaming_replication_promote.py`

**Frontend** :
- Nouveau : `frontend/src/components/PromoteToMasterButton.tsx`
- Nouveau : `frontend/src/components/PromoteConfirmationModal.tsx`
- Modifier : page Réplication (probablement `frontend/src/pages/AdminReplicationPage.tsx`) pour intégrer le bouton
- Modifier : `frontend/src/lib/adminApi.ts` (ajouter `fetchCanPromote()` + `promoteToMaster()`)
- Modifier : `frontend/src/i18n/fr.json` + `en.json` (strings de la modale)

**Frontend tests** :
- Nouveau : `frontend/src/components/PromoteToMasterButton.test.tsx`
- Nouveau : `frontend/src/components/PromoteConfirmationModal.test.tsx`

**Documentation** :
- Nouveau : `docs/operations/replication-failover.md` — guide opérationnel pour l'admin
- Modifier : `LESSONS.md` — note sur le scope MVP

---

## Task 1 : Service `promote_standby_to_master` (backend)

**Files :**
- Modify : `backend/app/services/streaming_replication.py` (ajouter à la fin)
- Test : `backend/tests/test_streaming_replication_promote.py` (nouveau)

- [ ] **Step 1: Écrire les tests TDD (rouges)**

Fichier `backend/tests/test_streaming_replication_promote.py` :

```python
"""Tests promote_standby_to_master + get_promote_eligibility (failover MVP)."""

from __future__ import annotations

import base64
from typing import Any
from unittest.mock import AsyncMock

import pytest


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://kc.test")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", "x")
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://standby.example/")


def _fake_conn(fetchval_returns: list[Any]) -> AsyncMock:
    conn = AsyncMock()
    conn.fetchval = AsyncMock(side_effect=fetchval_returns)
    conn.execute = AsyncMock(return_value=None)
    return conn


@pytest.mark.asyncio
async def test_get_promote_eligibility_returns_can_true_when_standby() -> None:
    from app.services.streaming_replication import get_promote_eligibility

    conn = _fake_conn(fetchval_returns=[True])  # pg_is_in_recovery() = True
    # mock meta_repo.get_value
    # ...
    result = await get_promote_eligibility(conn)
    assert result.can_promote is True
    assert result.current_role == "standby"


@pytest.mark.asyncio
async def test_get_promote_eligibility_returns_false_when_already_master() -> None:
    from app.services.streaming_replication import get_promote_eligibility

    conn = _fake_conn(fetchval_returns=[False])  # not in recovery = master
    result = await get_promote_eligibility(conn)
    assert result.can_promote is False
    assert result.current_role == "master"
    assert result.reason == "already_master"


@pytest.mark.asyncio
async def test_promote_standby_to_master_succeeds() -> None:
    from app.services.streaming_replication import promote_standby_to_master

    # pg_is_in_recovery: True before, False after promote
    conn = _fake_conn(fetchval_returns=[True, True, False])
    result = await promote_standby_to_master(conn, actor_user_id=None)
    assert result.promoted is True
    # `SELECT pg_promote(...)` doit avoir été appelé
    pg_promote_called = any(
        "pg_promote" in (str(call.args[0]) if call.args else "")
        for call in conn.fetchval.call_args_list + conn.execute.call_args_list
    )
    assert pg_promote_called


@pytest.mark.asyncio
async def test_promote_refuses_if_not_standby() -> None:
    from app.services.streaming_replication import (
        NotInStandbyModeError,
        promote_standby_to_master,
    )

    conn = _fake_conn(fetchval_returns=[False])  # already master
    with pytest.raises(NotInStandbyModeError):
        await promote_standby_to_master(conn, actor_user_id=None)


@pytest.mark.asyncio
async def test_promote_raises_if_pg_promote_fails_to_exit_recovery() -> None:
    from app.services.streaming_replication import (
        PromotionFailedError,
        promote_standby_to_master,
    )

    # in_recovery=True before, pg_promote returns True, but in_recovery still True after
    conn = _fake_conn(fetchval_returns=[True, True, True])
    with pytest.raises(PromotionFailedError):
        await promote_standby_to_master(conn, actor_user_id=None)


@pytest.mark.asyncio
async def test_promote_clears_is_standby_of_metadata() -> None:
    from app.services.streaming_replication import promote_standby_to_master

    conn = _fake_conn(fetchval_returns=[True, True, False])
    # before promote, is_standby_of = "https://old-master/"
    # after promote, must be None
    # ... vérifie que meta_repo.set_value est appelé avec None
    await promote_standby_to_master(conn, actor_user_id=None)
    # assert sur conn.execute appel UPDATE system_metadata SET value=NULL WHERE key='replication.is_standby_of'
```

Run: `uv run pytest tests/test_streaming_replication_promote.py -v`
Expected: FAIL (fonctions n'existent pas)

- [ ] **Step 2: Implémenter `get_promote_eligibility()` + `promote_standby_to_master()` dans `streaming_replication.py`**

À la fin du fichier `backend/app/services/streaming_replication.py` :

```python
from dataclasses import dataclass
from typing import Literal

from app.services.audit import audit_log_insert
from app.db.repositories import system_metadata as meta_repo


class NotInStandbyModeError(Exception):
    """Tentative de promote alors que l'instance est déjà primary."""


class PromotionFailedError(Exception):
    """pg_promote() a été appelé mais l'instance reste en recovery."""


@dataclass(frozen=True)
class PromoteEligibility:
    can_promote: bool
    current_role: Literal["standby", "master", "standalone"]
    master_url: str | None
    reason_if_not: str | None  # "already_master", "no_replication_configured", etc.


async def get_promote_eligibility(
    conn: asyncpg.Connection,
) -> PromoteEligibility:
    """Indique si l'instance peut être promue."""
    in_recovery = await conn.fetchval("SELECT pg_is_in_recovery()")
    if not in_recovery:
        master_url = await meta_repo.get_value(conn, "replication.is_standby_of")
        if master_url is None:
            return PromoteEligibility(
                can_promote=False,
                current_role="standalone",
                master_url=None,
                reason_if_not="no_replication_configured",
            )
        # in_recovery=False mais is_standby_of est set → état incohérent, mais on est primary
        return PromoteEligibility(
            can_promote=False,
            current_role="master",
            master_url=master_url,
            reason_if_not="already_master",
        )
    master_url = await meta_repo.get_value(conn, "replication.is_standby_of")
    return PromoteEligibility(
        can_promote=True,
        current_role="standby",
        master_url=master_url,
        reason_if_not=None,
    )


@dataclass(frozen=True)
class PromoteResult:
    promoted: bool
    old_master_url: str | None


async def promote_standby_to_master(
    conn: asyncpg.Connection,
    *,
    actor_user_id: UUID | None,
    pg_promote_timeout_seconds: int = 60,
) -> PromoteResult:
    """Promeut le standby local en master via pg_promote().

    Pré-condition : l'instance DOIT être en mode recovery (standby).
    Post-condition :
      - pg_is_in_recovery() retourne false
      - replication.is_standby_of est NULL
      - audit log écrit (action=replication.promoted_to_master)
    """
    in_recovery_before = await conn.fetchval("SELECT pg_is_in_recovery()")
    if not in_recovery_before:
        raise NotInStandbyModeError("not_in_recovery")

    old_master_url = await meta_repo.get_value(conn, "replication.is_standby_of")

    # pg_promote(wait=true, wait_seconds=N) bloque jusqu'à promotion ou timeout.
    # Retourne true si la promotion a réussi, false sinon.
    promoted = await conn.fetchval(
        "SELECT pg_promote(wait => true, wait_seconds => $1)",
        pg_promote_timeout_seconds,
    )

    # Re-check explicite : pg_promote peut retourner true mais recovery toujours en cours.
    in_recovery_after = await conn.fetchval("SELECT pg_is_in_recovery()")
    if in_recovery_after:
        raise PromotionFailedError(
            "pg_promote completed but instance still in recovery"
        )

    # Nettoyage : cette instance n'est plus standby de personne.
    await meta_repo.set_value(conn, "replication.is_standby_of", None)

    # Audit (best-effort — si la DB redémarre pendant le call, on log via structlog).
    try:
        await audit_log_insert(
            conn,
            "replication.promoted_to_master",
            actor_user_id=actor_user_id,
            metadata={"old_master_url": old_master_url},
        )
    except Exception:
        logger.warning(
            "promote_audit_log_failed",
            old_master_url=old_master_url,
        )

    return PromoteResult(promoted=True, old_master_url=old_master_url)
```

Run: `uv run pytest tests/test_streaming_replication_promote.py -v`
Expected: PASS (tous les tests verts)

- [ ] **Step 3: Lint**

Run: `uv run ruff check app/services/streaming_replication.py tests/test_streaming_replication_promote.py`
Expected: All checks passed

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/streaming_replication.py backend/tests/test_streaming_replication_promote.py
git commit -m "feat(replication): service promote_standby_to_master + get_promote_eligibility"
```

---

## Task 2 : Endpoints `GET /can-promote` + `POST /promote` (API)

**Files :**
- Modify : `backend/app/api/v1/admin_replication.py`
- Modify : `backend/app/models/api/replication.py` (créer le fichier s'il n'existe pas) ou ajouter à un fichier de schemas existant
- Test : `backend/tests/test_admin_replication_promote.py` (nouveau)

- [ ] **Step 1: Écrire les tests TDD (rouges)**

Fichier `backend/tests/test_admin_replication_promote.py` :

```python
"""Tests endpoints /v1/admin/replication/{can-promote,promote}."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


def test_can_promote_returns_200_when_standby(client_with_admin, mod) -> None:
    """GET /can-promote retourne can_promote=true + role=standby quand en recovery."""
    from app.services.streaming_replication import PromoteEligibility

    eligibility = PromoteEligibility(
        can_promote=True,
        current_role="standby",
        master_url="https://master.example/",
        reason_if_not=None,
    )
    with patch.object(mod.repl_svc, "get_promote_eligibility",
                       AsyncMock(return_value=eligibility)):
        r = client_with_admin.get("/v1/admin/replication/can-promote")
    assert r.status_code == 200
    body = r.json()
    assert body["can_promote"] is True
    assert body["current_role"] == "standby"
    assert body["master_url"] == "https://master.example/"


def test_can_promote_returns_200_when_already_master(client_with_admin, mod) -> None:
    """can_promote=false + reason=already_master quand déjà primary."""
    # ...


def test_promote_returns_200_when_confirm_master_down_true(client_with_admin, mod) -> None:
    """POST /promote avec confirm_master_down=true → 200 + promoted=true."""
    from app.services.streaming_replication import PromoteResult

    result = PromoteResult(promoted=True, old_master_url="https://master.example/")
    with patch.object(mod.repl_svc, "promote_standby_to_master",
                       AsyncMock(return_value=result)):
        r = client_with_admin.post(
            "/v1/admin/replication/promote",
            json={"confirm_master_down": True, "confirm_clients_will_be_reconfigured": True},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["promoted"] is True


def test_promote_returns_400_when_confirm_master_down_false(client_with_admin) -> None:
    """POST /promote sans confirm_master_down → 400 missing_confirmation."""
    r = client_with_admin.post(
        "/v1/admin/replication/promote",
        json={"confirm_master_down": False, "confirm_clients_will_be_reconfigured": True},
    )
    assert r.status_code == 400
    body = r.json()
    assert body["detail"]["error"] == "missing_confirmation"


def test_promote_returns_409_when_already_master(client_with_admin, mod) -> None:
    """POST /promote sur primary → 409 already_master."""
    from app.services.streaming_replication import NotInStandbyModeError

    with patch.object(mod.repl_svc, "promote_standby_to_master",
                       AsyncMock(side_effect=NotInStandbyModeError("not_in_recovery"))):
        r = client_with_admin.post(
            "/v1/admin/replication/promote",
            json={"confirm_master_down": True, "confirm_clients_will_be_reconfigured": True},
        )
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "not_in_standby_mode"


def test_promote_returns_500_when_pg_promote_fails(client_with_admin, mod) -> None:
    """POST /promote où pg_promote échoue → 500 promotion_failed."""
    from app.services.streaming_replication import PromotionFailedError

    with patch.object(mod.repl_svc, "promote_standby_to_master",
                       AsyncMock(side_effect=PromotionFailedError("timeout"))):
        r = client_with_admin.post(
            "/v1/admin/replication/promote",
            json={"confirm_master_down": True, "confirm_clients_will_be_reconfigured": True},
        )
    assert r.status_code == 500
    assert r.json()["detail"]["error"] == "promotion_failed"


def test_can_promote_requires_admin_auth(client_no_auth) -> None:
    """GET /can-promote sans JWT admin → 401."""
    r = client_no_auth.get("/v1/admin/replication/can-promote")
    assert r.status_code == 401


def test_promote_requires_admin_auth(client_no_auth) -> None:
    """POST /promote sans JWT admin → 401."""
    r = client_no_auth.post(
        "/v1/admin/replication/promote",
        json={"confirm_master_down": True, "confirm_clients_will_be_reconfigured": True},
    )
    assert r.status_code == 401
```

(Note : les fixtures `client_with_admin`, `client_no_auth`, `mod` suivent le pattern existant dans `test_admin_replication_sync.py` et `test_pairing_api_v2.py`. Reproduire fidèlement.)

Run: `uv run pytest tests/test_admin_replication_promote.py -v`
Expected: FAIL (endpoints n'existent pas)

- [ ] **Step 2: Ajouter les DTOs Pydantic**

Dans `backend/app/models/api/replication.py` (ou créer le fichier) :

```python
from pydantic import BaseModel, Field


class CanPromoteResponse(BaseModel):
    """A → admin UI : indique si la promotion est possible."""

    can_promote: bool
    current_role: str  # Literal["standby", "master", "standalone"]
    master_url: str | None = None
    reason_if_not: str | None = None


class PromoteRequest(BaseModel):
    """Body de POST /promote — exige les 2 confirmations admin."""

    confirm_master_down: bool = Field(
        ..., description="L'admin confirme que l'ancien master est arrêté."
    )
    confirm_clients_will_be_reconfigured: bool = Field(
        ...,
        description="L'admin confirme qu'il reconfigurera les clients après promotion.",
    )


class PromoteResponse(BaseModel):
    promoted: bool
    old_master_url: str | None
```

- [ ] **Step 3: Ajouter les 2 endpoints dans `admin_replication.py`**

```python
from app.models.api.replication import (
    CanPromoteResponse,
    PromoteRequest,
    PromoteResponse,
)
from app.services import streaming_replication as repl_svc


@router.get("/can-promote", response_model=CanPromoteResponse)
async def can_promote_endpoint(admin: AdminJwt) -> CanPromoteResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        elig = await repl_svc.get_promote_eligibility(conn)
    return CanPromoteResponse(
        can_promote=elig.can_promote,
        current_role=elig.current_role,
        master_url=elig.master_url,
        reason_if_not=elig.reason_if_not,
    )


@router.post(
    "/promote",
    response_model=PromoteResponse,
    status_code=status.HTTP_200_OK,
)
async def promote_endpoint(
    req: PromoteRequest,
    admin: AdminJwt,
) -> PromoteResponse:
    """Promeut le standby local en master via pg_promote().

    Exige les 2 confirmations admin (master_down + clients_will_be_reconfigured)
    — toutes les deux à true sinon 400 missing_confirmation. Refuse si on n'est
    pas en mode standby (409 not_in_standby_mode).
    """
    if not (req.confirm_master_down and req.confirm_clients_will_be_reconfigured):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "missing_confirmation"},
        )
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            result = await repl_svc.promote_standby_to_master(
                conn,
                actor_user_id=admin.user_id,
            )
        except repl_svc.NotInStandbyModeError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": "not_in_standby_mode"},
            ) from None
        except repl_svc.PromotionFailedError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": "promotion_failed", "cause": str(e)},
            ) from e
    return PromoteResponse(
        promoted=result.promoted,
        old_master_url=result.old_master_url,
    )
```

Run: `uv run pytest tests/test_admin_replication_promote.py -v`
Expected: PASS

- [ ] **Step 4: Lint + test global**

Run: `uv run ruff check app/api/v1/admin_replication.py app/models/api/replication.py tests/test_admin_replication_promote.py`
Run: `uv run pytest tests/test_admin_replication_promote.py tests/test_streaming_replication_promote.py tests/test_admin_replication.py`
Expected: All green

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/admin_replication.py backend/app/models/api/replication.py backend/tests/test_admin_replication_promote.py
git commit -m "feat(replication): endpoints GET /can-promote + POST /promote"
```

---

## Task 3 : Lib API client frontend

**Files :**
- Modify : `frontend/src/lib/adminApi.ts`

- [ ] **Step 1: Ajouter les types + fonctions API**

```ts
// Types
export interface CanPromoteResponse {
  can_promote: boolean;
  current_role: "standby" | "master" | "standalone";
  master_url: string | null;
  reason_if_not: string | null;
}

export interface PromoteRequest {
  confirm_master_down: boolean;
  confirm_clients_will_be_reconfigured: boolean;
}

export interface PromoteResponse {
  promoted: boolean;
  old_master_url: string | null;
}

export async function fetchCanPromote(): Promise<CanPromoteResponse> {
  const r = await adminFetch("/v1/admin/replication/can-promote");
  if (!r.ok) throw new Error(`can-promote ${r.status}`);
  return r.json();
}

export async function promoteToMaster(
  req: PromoteRequest,
): Promise<PromoteResponse> {
  const r = await adminFetch("/v1/admin/replication/promote", {
    method: "POST",
    body: JSON.stringify(req),
    headers: { "Content-Type": "application/json" },
  });
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body?.detail?.error ?? `promote ${r.status}`);
  }
  return r.json();
}
```

- [ ] **Step 2: Test rapide (smoke check TypeScript)**

Run: `cd frontend && npx tsc --noEmit`
Expected: pas d'erreur de type

---

## Task 4 : Composant `PromoteConfirmationModal`

**Files :**
- Create : `frontend/src/components/PromoteConfirmationModal.tsx`
- Create : `frontend/src/components/PromoteConfirmationModal.test.tsx`
- Modify : `frontend/src/i18n/fr.json` + `en.json`

- [ ] **Step 1: i18n keys**

Dans `fr.json` :

```json
"admin": {
  "replication": {
    "promote": {
      "buttonLabel": "Promouvoir en master",
      "modalTitle": "Promouvoir cette instance en master",
      "warningTitle": "Action irréversible",
      "warningBody": "Cette opération promeut le standby local en primary read-write. L'ancien master ({masterUrl}) ne doit plus accepter d'écritures sous peine de divergence permanente (split-brain).",
      "confirmMasterDown": "Je confirme que l'ancien master est arrêté",
      "confirmClientsReconfigured": "Je m'engage à reconfigurer les clients vers ce nouveau master",
      "submit": "Promouvoir maintenant",
      "cancel": "Annuler",
      "successToast": "Promotion réussie. Cette instance est maintenant master.",
      "errors": {
        "missing_confirmation": "Les deux cases doivent être cochées.",
        "not_in_standby_mode": "Cette instance n'est pas en mode standby.",
        "promotion_failed": "La promotion a échoué : pg_promote n'a pas pu sortir du mode recovery.",
        "unknown": "Erreur inconnue."
      }
    }
  }
}
```

Idem `en.json` traduit.

- [ ] **Step 2: Écrire le test rouge**

`frontend/src/components/PromoteConfirmationModal.test.tsx` :

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PromoteConfirmationModal } from "./PromoteConfirmationModal";

describe("PromoteConfirmationModal", () => {
  it("submit button is disabled until both checkboxes are checked", () => {
    render(
      <PromoteConfirmationModal
        opened={true}
        masterUrl="https://old-master/"
        onClose={() => {}}
        onSubmit={() => {}}
      />,
    );
    const submit = screen.getByRole("button", { name: /promouvoir maintenant/i });
    expect(submit).toBeDisabled();

    fireEvent.click(screen.getByRole("checkbox", { name: /ancien master.*arr/i }));
    expect(submit).toBeDisabled();

    fireEvent.click(
      screen.getByRole("checkbox", { name: /reconfigurer les clients/i }),
    );
    expect(submit).toBeEnabled();
  });

  it("calls onSubmit when submit is clicked", () => {
    const onSubmit = vi.fn();
    render(
      <PromoteConfirmationModal
        opened={true}
        masterUrl="https://old-master/"
        onClose={() => {}}
        onSubmit={onSubmit}
      />,
    );
    fireEvent.click(screen.getByRole("checkbox", { name: /ancien master.*arr/i }));
    fireEvent.click(
      screen.getByRole("checkbox", { name: /reconfigurer les clients/i }),
    );
    fireEvent.click(screen.getByRole("button", { name: /promouvoir maintenant/i }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });
});
```

Run: `cd frontend && npm test PromoteConfirmationModal`
Expected: FAIL

- [ ] **Step 3: Implémenter le composant**

`frontend/src/components/PromoteConfirmationModal.tsx` :

```tsx
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Modal, Stack, Alert, Checkbox, Group, Button } from "@mantine/core";

interface Props {
  opened: boolean;
  masterUrl: string | null;
  onClose: () => void;
  onSubmit: () => void;
}

export function PromoteConfirmationModal({ opened, masterUrl, onClose, onSubmit }: Props): JSX.Element {
  const { t } = useTranslation();
  const [c1, setC1] = useState(false);
  const [c2, setC2] = useState(false);
  const canSubmit = c1 && c2;
  return (
    <Modal opened={opened} onClose={onClose} title={t("admin.replication.promote.modalTitle")} size="lg">
      <Stack>
        <Alert color="orange" title={t("admin.replication.promote.warningTitle")}>
          {t("admin.replication.promote.warningBody", { masterUrl: masterUrl ?? "?" })}
        </Alert>
        <Checkbox
          checked={c1}
          onChange={(e) => setC1(e.currentTarget.checked)}
          label={t("admin.replication.promote.confirmMasterDown")}
        />
        <Checkbox
          checked={c2}
          onChange={(e) => setC2(e.currentTarget.checked)}
          label={t("admin.replication.promote.confirmClientsReconfigured")}
        />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {t("admin.replication.promote.cancel")}
          </Button>
          <Button color="orange" disabled={!canSubmit} onClick={onSubmit}>
            {t("admin.replication.promote.submit")}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
```

Run: `cd frontend && npm test PromoteConfirmationModal`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/PromoteConfirmationModal.tsx frontend/src/components/PromoteConfirmationModal.test.tsx frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(ui): PromoteConfirmationModal avec double check-box"
```

---

## Task 5 : Composant `PromoteToMasterButton` + intégration page Réplication

**Files :**
- Create : `frontend/src/components/PromoteToMasterButton.tsx`
- Create : `frontend/src/components/PromoteToMasterButton.test.tsx`
- Modify : `frontend/src/pages/AdminReplicationPage.tsx` (ou équivalent)

- [ ] **Step 1: Écrire le test rouge**

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PromoteToMasterButton } from "./PromoteToMasterButton";
import * as adminApi from "@/lib/adminApi";

function withQc(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{node}</QueryClientProvider>;
}

describe("PromoteToMasterButton", () => {
  it("not rendered when can_promote=false", async () => {
    vi.spyOn(adminApi, "fetchCanPromote").mockResolvedValue({
      can_promote: false, current_role: "master", master_url: null, reason_if_not: "already_master",
    });
    render(withQc(<PromoteToMasterButton />));
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: /promouvoir/i })).toBeNull();
    });
  });

  it("rendered when can_promote=true", async () => {
    vi.spyOn(adminApi, "fetchCanPromote").mockResolvedValue({
      can_promote: true, current_role: "standby", master_url: "https://m/", reason_if_not: null,
    });
    render(withQc(<PromoteToMasterButton />));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /promouvoir/i })).toBeInTheDocument();
    });
  });

  it("calls promoteToMaster on submit + shows success toast", async () => {
    // ... avec MantineProvider notifications mock
  });
});
```

- [ ] **Step 2: Implémenter le composant**

```tsx
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@mantine/core";
import { notifications } from "@mantine/notifications";

import { fetchCanPromote, promoteToMaster } from "@/lib/adminApi";
import { PromoteConfirmationModal } from "./PromoteConfirmationModal";

export function PromoteToMasterButton(): JSX.Element | null {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);

  const eligibility = useQuery({
    queryKey: ["replication", "can-promote"],
    queryFn: fetchCanPromote,
    refetchInterval: 10_000,
  });

  const mutation = useMutation({
    mutationFn: () =>
      promoteToMaster({
        confirm_master_down: true,
        confirm_clients_will_be_reconfigured: true,
      }),
    onSuccess: () => {
      setModalOpen(false);
      notifications.show({
        color: "green",
        title: t("admin.replication.promote.successToast"),
        message: "",
      });
      qc.invalidateQueries({ queryKey: ["replication"] });
    },
    onError: (err: Error) => {
      const code = err.message;
      notifications.show({
        color: "red",
        title: t("admin.replication.promote.modalTitle"),
        message: t(
          `admin.replication.promote.errors.${code}`,
          { defaultValue: t("admin.replication.promote.errors.unknown") },
        ),
      });
    },
  });

  if (!eligibility.data?.can_promote) return null;

  return (
    <>
      <Button color="orange" onClick={() => setModalOpen(true)}>
        {t("admin.replication.promote.buttonLabel")}
      </Button>
      <PromoteConfirmationModal
        opened={modalOpen}
        masterUrl={eligibility.data?.master_url ?? null}
        onClose={() => setModalOpen(false)}
        onSubmit={() => mutation.mutate()}
      />
    </>
  );
}
```

- [ ] **Step 3: Intégrer dans la page Réplication**

Identifier la page (`AdminReplicationPage.tsx` ou similaire), ajouter `<PromoteToMasterButton />` dans le bloc admin standby. Visible seulement quand pertinent (le composant retourne null lui-même si non applicable).

- [ ] **Step 4: Test + lint front**

Run: `cd frontend && npm test`
Run: `cd frontend && npx tsc --noEmit && npm run lint`
Expected: green

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/PromoteToMasterButton.tsx \
        frontend/src/components/PromoteToMasterButton.test.tsx \
        frontend/src/pages/AdminReplicationPage.tsx
git commit -m "feat(ui): bouton Promouvoir en master sur la page Réplication"
```

---

## Task 6 : Documentation opérationnelle

**Files :**
- Create : `docs/operations/replication-failover.md`

- [ ] **Step 1: Écrire le guide**

```markdown
# Failover réplication — guide opérationnel

## Quand utiliser

- Panne du master (down définitif)
- Maintenance planifiée du master nécessitant un basculement

## Pré-requis

- L'ancien master doit être **arrêté** avant de procéder. Démarche :
  - Si encore joignable : `docker compose stop postgres backend` côté master
  - Si déjà down : passer à l'étape suivante
- L'admin a un accès JWT à l'UI du standby

## Procédure

1. Ouvrir l'UI du standby (`https://<standby>/admin/replication`)
2. Section "Réplication entrante" → bouton **"Promouvoir en master"** (visible
   uniquement si l'instance est en mode standby)
3. Modale s'affiche, cocher les 2 cases :
   - ☑ L'ancien master est arrêté
   - ☑ Les clients seront reconfigurés
4. Cliquer **"Promouvoir maintenant"**
5. Toast vert "Promotion réussie" → l'instance est maintenant master

## Vérifications post-failover

```bash
# Côté nouveau master (ex-standby) :
docker compose -f docker-compose-dev.yml exec -T postgres psql -U harpocrate \
  harpocrate -c "SELECT pg_is_in_recovery();"   # → f (false = primary)

# Test d'écriture :
docker compose -f docker-compose-dev.yml exec -T postgres psql -U harpocrate \
  harpocrate -c "INSERT INTO audit_log (action) VALUES ('test.write_after_promote');"   # → INSERT 0 1
```

## Reconfigurer les clients

Les clients (UI, scripts, autres instances) pointaient vers l'ancien master.
Mettre à jour leur URL Harpocrate vers le nouveau master.

## Réintégrer l'ancien master comme nouveau standby (manuel — pas industrialisé)

Pour cette itération MVP, **non couvert par l'UI**. Procédure manuelle :

1. S'assurer que l'ancien master n'a pas de divergence (idéalement il était down
   pendant la promotion → pas de write divergent)
2. Effacer le PGDATA de l'ancien master : `rm -rf data/postgres/*`
3. Faire un pg_basebackup depuis le nouveau master vers l'ancien
4. Démarrer Postgres sur l'ancien master en mode standby
5. Reconfigurer `replication.is_standby_of` dans `system_metadata` de l'ancien master

⚠️ Cette étape sera industrialisée dans une itération future via un endpoint
`POST /v1/admin/replication/rebuild-as-standby` + UI dédiée.
```

- [ ] **Step 2: Mise à jour LESSONS.md**

Ajouter :

```
- [replication] Failover MVP = promotion manuelle guidée via UI : pg_promote() + nettoyage `replication.is_standby_of`. L'admin garde la responsabilité de stopper l'ancien master AVANT promote (modale exige double-check). Pas de détection split-brain auto (un heartbeat inter-instances est prévu pour une itération future). Rebuild de l'ancien master en nouveau standby reste manuel pour l'instant — chantier dédié à venir.
```

- [ ] **Step 3: Commit**

```bash
git add docs/operations/replication-failover.md LESSONS.md
git commit -m "docs: guide opérationnel du failover MVP + leçon LESSONS.md"
```

---

## Task 7 : Test global + cleanup

- [ ] **Step 1: Full test suite backend**

Run: `cd backend && uv run pytest tests/ --ignore=tests/test_admin_scheduled_backups.py --ignore=tests/test_admin_remote_backups.py`

(les 2 fichiers exclus sont des fixtures HMAC cross-pollution préexistantes, indépendantes de ce plan)

Expected: All green sur tests pertinents

- [ ] **Step 2: Full test suite frontend**

Run: `cd frontend && npm test`
Expected: All green

- [ ] **Step 3: Lint global**

Run: `cd backend && uv run ruff check app/`
Run: `cd frontend && npm run lint && npx tsc --noEmit`
Expected: green sur fichiers touchés

- [ ] **Step 4: Squash + push**

Optionnel selon préférence : squasher les 6 commits du plan en un seul commit "feat(replication): failover MVP — promotion manuelle guidée" pour un historique propre.

```bash
git push
```

---

## Self-Review

**Spec coverage** : 
- pg_promote() exécuté : Task 1
- Nettoyage replication.is_standby_of : Task 1
- Audit log : Task 1
- Endpoint /can-promote : Task 2
- Endpoint /promote avec validation des 2 confirmations : Task 2
- Bouton UI visible seulement si standby : Task 5
- Modale double check-box : Task 4
- Toast succès + reload : Task 5
- Doc opérationnelle : Task 6

**Hors scope explicitement** :
- Détection automatique de la perte du master
- Demote distant de l'ancien master via HTTPS
- Détection split-brain
- Rebuild automatique de l'ancien master en standby
- Reconfiguration automatique des clients

**Risques identifiés** :
- Split-brain si l'admin ment dans la confirmation : accepté (responsabilité admin)
- L'ancien master toujours accessible accidentellement : à mitigér en prod via VIP/firewall (hors scope MVP)
- Le backend du nouveau master continue de marquer cluster_listen_skipped_standby_mode pendant max 60s après promote, puis détecte au reconnect : OK c'est intégré au refactor pool précédent
