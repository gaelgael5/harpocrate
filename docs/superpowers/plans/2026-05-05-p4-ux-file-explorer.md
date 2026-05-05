# P4 — UX file-explorer + path à la création + suppression de dossier

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Présenter le wallet comme un explorateur de fichiers Windows : arbre des dossiers à gauche (cliquable pour naviguer), grille de contenu à droite (sous-dossiers + secrets du niveau courant), breadcrumb en haut. Permettre à l'utilisateur de créer un secret avec un chemin (`/users/foo/my-key`) directement depuis l'IHM. Permettre de supprimer un dossier (= supprimer récursivement tous les secrets enfants).

**Architecture:** Backend ajoute une route `DELETE /v1/wallets/{wid}/secrets/by-path?path=/foo/bar/` qui hard-delete tous les secrets dont le nom commence par le path donné, avec un compte préalable (`GET /v1/wallets/{wid}/secrets/by-path/count?path=...`) pour alimenter la modal de confirmation. Frontend : `SecretNewPage` accepte les noms à `/` (validation client alignée sur le backend `validate_secret_name`). `WalletDetailPage` ajoute un panneau gauche `<FolderTree>` cliquable et un bouton "supprimer ce dossier" sur chaque carte de dossier. Drag & drop entre dossiers et menu contextuel clic-droit = OUT OF SCOPE (futur lot).

**Tech Stack:** Vite + React 18 + TS strict + Mantine + TanStack Query + i18next. Backend FastAPI + asyncpg.

---

## File Structure

| Fichier | Modification |
|---|---|
| `backend/app/services/secrets.py` | Ajout `count_secrets_by_path_prefix` + `delete_secrets_by_path_prefix` |
| `backend/app/db/repositories/secrets.py` | Ajout `count_by_path_prefix` + `delete_by_path_prefix` (cascade naturelle sur `secret_path_index` via FK) |
| `backend/app/api/v1/secrets.py` | Ajout 2 routes : `GET /by-path/count?path=...` + `DELETE /by-path?path=...` |
| `backend/tests/test_delete_by_path.py` *(nouveau)* | Tests des 2 routes |
| `frontend/src/pages/SecretNewPage.tsx` | Relâcher `NAME_RE` pour autoriser `/` ; helper texte ; pré-remplir avec `prefixPath` quand fourni via state |
| `frontend/src/pages/WalletDetailPage.tsx` | Ajout `<FolderTree>` à gauche (panneau persistant), bouton "supprimer dossier" sur chaque `FolderCard`, modal de confirmation avec count |
| `frontend/src/components/FolderTree.tsx` *(nouveau)* | Composant arbre avec dossiers expandables, fetch récursif des sous-niveaux à la demande |
| `frontend/src/lib/api-client.ts` | (déjà OK — utilise les routes existantes) |
| `frontend/src/i18n/fr.json` + `en.json` | Ajout des clés (folder.deleteConfirm, secrets.pathHint, etc.) |
| `frontend/src/tests/folder-tree.test.tsx` *(nouveau)* | Smoke test du composant |
| `frontend/src/tests/folder-delete.test.tsx` *(nouveau)* | Test de la modal de confirmation |

---

## Task 1: Backend — service `count_by_path_prefix` + `delete_by_path_prefix`

**Files:**
- Modify: `backend/app/db/repositories/secrets.py`
- Modify: `backend/app/services/secrets.py`

- [ ] **Step 1.1: Repo functions**

À la fin de `backend/app/db/repositories/secrets.py`, ajouter :

```python
async def count_by_path_prefix(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    path_prefix: str,
) -> int:
    """Compte les secrets dont le nom commence par path_prefix.

    path_prefix doit se terminer par '/'. Match récursif : tous les sous-niveaux comptent.
    """
    count: int = await conn.fetchval(
        """
        SELECT COUNT(*) FROM secrets
        WHERE wallet_id = $1
          AND name LIKE $2 || '%'
        """,
        wallet_id, path_prefix,
    )
    return count


async def delete_by_path_prefix(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    path_prefix: str,
) -> list[tuple[UUID, str]]:
    """Hard-delete tous les secrets dont le nom commence par path_prefix.

    Retourne la liste (id, name) des secrets supprimés (pour audit log).
    Le trigger ON DELETE CASCADE supprime aussi les entrées de secret_path_index et secret_tags.
    """
    rows = await conn.fetch(
        """
        DELETE FROM secrets
        WHERE wallet_id = $1
          AND name LIKE $2 || '%'
        RETURNING id, name
        """,
        wallet_id, path_prefix,
    )
    return [(r["id"], r["name"]) for r in rows]
```

- [ ] **Step 1.2: Service functions**

À la fin de `backend/app/services/secrets.py`, ajouter :

```python
async def count_secrets_by_path(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    path: str,
) -> int:
    """Compte les secrets sous un path. path doit être /-prefixed et /-suffixed."""
    from app.services.secret_paths import normalize_path
    normalized = normalize_path(path)
    if normalized == "/":
        # Racine = tous les secrets du wallet
        return await secrets_repo.count_by_path_prefix(conn, wallet_id=wallet_id, path_prefix="")
    return await secrets_repo.count_by_path_prefix(conn, wallet_id=wallet_id, path_prefix=normalized)


async def delete_secrets_by_path(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    path: str,
    caller_user_id: UUID,
    actor_ip: str | None,
) -> int:
    """Hard-delete tous les secrets sous un path. Retourne le nombre supprimé.

    400 si path vide ou égal à '/' (refus de tout supprimer en une opération — protection).
    """
    from app.services.secret_paths import normalize_path
    normalized = normalize_path(path)
    if normalized == "/":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "cannot_delete_root_path",
                "message": "Refusing to delete all secrets in wallet via path='/'. Delete the wallet itself instead.",
            },
        )

    async with conn.transaction():
        deleted = await secrets_repo.delete_by_path_prefix(
            conn, wallet_id=wallet_id, path_prefix=normalized,
        )
        for secret_id, secret_name in deleted:
            await audit_log_insert(
                conn,
                "secret.deleted",
                actor_user_id=caller_user_id,
                actor_ip=actor_ip,
                target_wallet_id=wallet_id,
                target_secret_id=secret_id,
                metadata={"secret_name": secret_name, "access_via": "by_path", "path": normalized},
            )

    return len(deleted)
```

- [ ] **Step 1.3: Vérifier les imports**

```bash
cd /e/srcs/harpocrate/backend && uv run python -c "
from app.services.secrets import count_secrets_by_path, delete_secrets_by_path
from app.db.repositories.secrets import count_by_path_prefix, delete_by_path_prefix
print('OK')
"
```

- [ ] **Step 1.4: Commit**

```bash
git add backend/app/db/repositories/secrets.py backend/app/services/secrets.py
git commit -m "feat(secrets): services count + delete by path prefix"
```

---

## Task 2: Backend — routes GET /by-path/count + DELETE /by-path

**Files:**
- Modify: `backend/app/api/v1/secrets.py`
- Test: `backend/tests/test_delete_by_path.py` (nouveau)

- [ ] **Step 2.1: Tests rouges**

Créer `backend/tests/test_delete_by_path.py` :

```python
"""Tests P4 — GET /by-path/count + DELETE /by-path (suppression récursive de dossier)."""
from __future__ import annotations

import base64
import datetime
import uuid
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from tests._helpers import (
    TEST_AUDIENCE,
    TEST_KID,
    TEST_PUBLIC_JWK,
    make_jwt_token,
)

_NOW = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.UTC)
_CALLER_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_WALLET_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")


class FakeRecord(dict[str, Any]):
    def __getitem__(self, key: str) -> Any:
        return super().__getitem__(key)


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://keycloak.yoops.org")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", TEST_AUDIENCE)
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://vault.yoops.org")

    import app.core.security
    _sec = app.core.security.__dict__["settings"]
    monkeypatch.setattr(_sec, "keycloak_url", "https://keycloak.yoops.org")
    monkeypatch.setattr(_sec, "keycloak_realm", "yoops")
    monkeypatch.setattr(_sec, "keycloak_client_id", TEST_AUDIENCE)


@pytest.fixture(autouse=True)
def patch_jwks() -> Generator[None, None, None]:
    from app.core import jwks_cache
    keys_backup = dict(jwks_cache._keys)
    jwks_cache._keys.clear()
    jwks_cache._keys[TEST_KID] = TEST_PUBLIC_JWK
    yield
    jwks_cache._keys.clear()
    jwks_cache._keys.update(keys_backup)


def _user_row() -> FakeRecord:
    return FakeRecord({
        "id": _CALLER_ID, "keycloak_sub": "test-sub-001", "email": "alice@example.com",
        "display_name": "Alice", "rsa_public_key": b"x", "salt_passphrase": b"x" * 16,
        "salt_recovery": b"y" * 16, "encrypted_rsa_private_key": b"x",
        "encrypted_sym_key_by_pass": b"x", "encrypted_sym_key_by_recovery": b"x",
        "kdf_memory_kb": 65536, "kdf_iterations": 3, "kdf_parallelism": 4,
        "rsa_key_size": 2048, "created_at": _NOW, "updated_at": _NOW,
        "last_unlock_at": None,
    })


def _wallet_row(permissions: int = 63) -> FakeRecord:
    return FakeRecord({
        "id": _WALLET_ID, "name": "W", "description": None,
        "owner_user_id": _CALLER_ID, "created_at": _NOW, "updated_at": _NOW,
        "my_permissions": permissions, "valued_secrets_count": 0,
        "placeholder_secrets_count": 0, "deleted_at": None,
    })


class _Tx:
    async def __aenter__(self) -> _Tx: return self
    async def __aexit__(self, *a: Any) -> None: pass


def _conn() -> MagicMock:
    c: MagicMock = MagicMock()
    c.fetchrow = AsyncMock(return_value=None)
    c.fetchval = AsyncMock(return_value=None)
    c.fetch = AsyncMock(return_value=[])
    c.execute = AsyncMock(return_value=None)
    c.transaction = MagicMock(return_value=_Tx())
    return c


def _pool(conn: MagicMock) -> MagicMock:
    class _A:
        async def __aenter__(self) -> MagicMock: return conn
        async def __aexit__(self, *a: Any) -> None: pass
    p = MagicMock()
    p.acquire = MagicMock(return_value=_A())
    return p


def _client(pool: MagicMock) -> AsyncClient:
    from app.db import pool as pm
    from app.main import app
    pm._pool = pool
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _hdr() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_jwt_token()}"}


@pytest.mark.asyncio
async def test_count_by_path_returns_count() -> None:
    """GET /by-path/count?path=/foo/ → {count: N}"""
    conn = _conn()
    call_n = 0

    async def fr(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _user_row()
        if call_n == 2:
            return _wallet_row()
        return None

    conn.fetchrow = fr
    conn.fetchval = AsyncMock(return_value=7)  # COUNT result

    async with _client(_pool(conn)) as cli:
        r = await cli.get(
            f"/v1/wallets/{_WALLET_ID}/secrets/by-path/count",
            params={"path": "/users/foo/"},
            headers=_hdr(),
        )

    assert r.status_code == 200, r.text
    assert r.json() == {"count": 7}


@pytest.mark.asyncio
async def test_delete_by_path_returns_deleted_count() -> None:
    """DELETE /by-path?path=/foo/ → {deleted: N}, exécute le DELETE SQL."""
    conn = _conn()
    call_n = 0

    async def fr(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _user_row()
        if call_n == 2:
            return _wallet_row()
        return None

    deleted_rows = [
        FakeRecord({"id": uuid.uuid4(), "name": "/users/foo/key1"}),
        FakeRecord({"id": uuid.uuid4(), "name": "/users/foo/key2"}),
        FakeRecord({"id": uuid.uuid4(), "name": "/users/foo/sub/key3"}),
    ]
    conn.fetchrow = fr
    conn.fetch = AsyncMock(return_value=deleted_rows)

    async with _client(_pool(conn)) as cli:
        r = await cli.delete(
            f"/v1/wallets/{_WALLET_ID}/secrets/by-path",
            params={"path": "/users/foo/"},
            headers=_hdr(),
        )

    assert r.status_code == 200, r.text
    assert r.json() == {"deleted": 3}


@pytest.mark.asyncio
async def test_delete_by_path_root_refused() -> None:
    """DELETE /by-path?path=/ → 400 cannot_delete_root_path."""
    conn = _conn()
    call_n = 0

    async def fr(query: str, *args: Any) -> FakeRecord | None:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return _user_row()
        if call_n == 2:
            return _wallet_row()
        return None

    conn.fetchrow = fr

    async with _client(_pool(conn)) as cli:
        r = await cli.delete(
            f"/v1/wallets/{_WALLET_ID}/secrets/by-path",
            params={"path": "/"},
            headers=_hdr(),
        )

    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "cannot_delete_root_path"
```

- [ ] **Step 2.2: Vérifier RED**

```bash
cd /e/srcs/harpocrate/backend && uv run pytest tests/test_delete_by_path.py -v 2>&1 | tail -10
```
Expected : 3 FAIL avec 404 ou 405.

- [ ] **Step 2.3: Routes**

Dans `backend/app/api/v1/secrets.py`, dans la section by-id (après les routes by-id existantes) ajouter :

```python
# ─── By-path — operations récursives sur un dossier ───────────────────────────


@router.get("/by-path/count")
async def count_secrets_by_path(
    wallet_id: UUID,
    auth: ReadAuth,
    path: str = Query(..., description="Path à compter, ex: /foo/bar/"),
) -> JSONResponse:
    """Compte récursivement les secrets sous un path. Requiert [read]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        count = await secrets_svc.count_secrets_by_path(
            conn, wallet_id=wallet_id, path=path,
        )
    return JSONResponse({"count": count})


@router.delete("/by-path")
async def delete_secrets_by_path(
    wallet_id: UUID,
    auth: RemoveAuth,
    request: Request,
    path: str = Query(..., description="Path à supprimer récursivement, ex: /foo/bar/"),
) -> JSONResponse:
    """Supprime récursivement tous les secrets sous un path. 400 si path = '/'. Requiert [remove]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        deleted = await secrets_svc.delete_secrets_by_path(
            conn,
            wallet_id=wallet_id,
            path=path,
            caller_user_id=auth.caller_user_id,
            actor_ip=_client_ip(request),
        )
    return JSONResponse({"deleted": deleted})
```

**Important** : ces 2 routes ont préfixe `/by-path` qui ne conflicte pas avec `/by-id/{secret_id}`. Pas besoin d'ordre particulier vis-à-vis des routes name-based existantes.

- [ ] **Step 2.4: Tests verts**

```bash
cd /e/srcs/harpocrate/backend && uv run pytest tests/test_delete_by_path.py -v 2>&1 | tail -10
```
Expected : 3 PASS.

- [ ] **Step 2.5: Commit**

```bash
git add backend/app/api/v1/secrets.py backend/tests/test_delete_by_path.py
git commit -m "feat(secrets): routes GET /by-path/count + DELETE /by-path (récursif)"
```

---

## Task 3: Frontend — SecretNewPage accepte les noms à path

**Files:**
- Modify: `frontend/src/pages/SecretNewPage.tsx`

- [ ] **Step 3.1: Relâcher la validation `NAME_RE`**

Dans `frontend/src/pages/SecretNewPage.tsx` ligne 40, remplacer :
```tsx
const NAME_RE = /^[A-Za-z0-9_.-]+$/
```
par :
```tsx
// Aligné sur backend/app/services/secret_paths.py:validate_secret_name
// - sans '/' : [A-Za-z0-9_.-]+
// - avec '/' : segments [a-zA-Z0-9@._-]+, optionnellement '/'-préfixé, pas de '/' final, pas de '//'
const NAME_RE_ROOT = /^[A-Za-z0-9_.-]+$/
const NAME_RE_PATH = /^\/?([a-zA-Z0-9@._-]+\/)*[a-zA-Z0-9@._-]+$/

function validateSecretName(name: string): string | null {
  const stripped = name.trim()
  if (!stripped) return 'common.required'
  if (stripped.length > 256) return 'Max 256 characters'
  if (!stripped.includes('/')) {
    return NAME_RE_ROOT.test(stripped) ? null : 'secrets.nameHint'
  }
  if (stripped.endsWith('/')) return 'secrets.nameTrailingSlash'
  if (stripped.includes('//')) return 'secrets.nameDoubleSlash'
  return NAME_RE_PATH.test(stripped) ? null : 'secrets.namePathHint'
}
```

Et remplacer la validation du formulaire (lignes 71-76) :
```tsx
name: (v) => {
  const stripped = v.trim()
  if (!stripped) return t('common.required')
  if (stripped.length > 256) return 'Max 256 characters'
  if (!NAME_RE.test(stripped)) return t('secrets.nameHint')
  return null
},
```
par :
```tsx
name: (v) => {
  const errKey = validateSecretName(v)
  return errKey ? t(errKey) : null
},
```

- [ ] **Step 3.2: Pré-remplir avec `prefixPath` si fourni via state**

Dans `SecretNewPage`, modifier `useForm`'s `initialValues` pour utiliser `prefixPath` venu du state de `WalletDetailPage` :

```tsx
import { useLocation } from 'react-router-dom'

// Dans le composant, après les hooks existants :
const location = useLocation()
const prefixPath = (location.state as { prefixPath?: string } | null)?.prefixPath ?? ''
```

Et modifier `initialValues` :
```tsx
initialValues: { name: prefixPath, description: '', tags: '', value: '' },
```

(Si l'utilisateur arrive depuis le bouton "+ secret" dans le dossier `/users/foo/`, le champ `name` est pré-rempli avec `/users/foo/` — il complète juste avec le nom final.)

- [ ] **Step 3.3: Ajouter les clés i18n**

Dans `frontend/src/i18n/fr.json`, ajouter dans la section `secrets` :
```json
"nameHint": "Lettres, chiffres, _.- (sans /). Pour un chemin, utilisez /foo/bar/key",
"namePathHint": "Chemin invalide. Format : /dossier/sous-dossier/nom",
"nameTrailingSlash": "Le nom ne peut pas se terminer par /",
"nameDoubleSlash": "Le nom ne peut pas contenir // consécutifs",
"pathHint": "Vous pouvez utiliser des / pour organiser en dossiers : /users/alice/api-key"
```

Idem dans `en.json` (traduit) :
```json
"nameHint": "Letters, digits, _.- (no /). For a path, use /folder/subfolder/key",
"namePathHint": "Invalid path. Format: /folder/subfolder/name",
"nameTrailingSlash": "Name cannot end with /",
"nameDoubleSlash": "Name cannot contain consecutive //",
"pathHint": "You can use / to organize in folders: /users/alice/api-key"
```

- [ ] **Step 3.4: Build TS + lint**

```bash
cd /e/srcs/harpocrate/frontend && npx tsc --noEmit 2>&1 | tail -10
cd /e/srcs/harpocrate/frontend && npm run lint 2>&1 | tail -5
```

- [ ] **Step 3.5: Commit**

```bash
git add frontend/src/pages/SecretNewPage.tsx frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(frontend): SecretNewPage accepte les noms avec path /foo/bar/key"
```

---

## Task 4: Frontend — bouton "supprimer dossier" sur FolderCard + modal de confirmation

**Files:**
- Modify: `frontend/src/pages/WalletDetailPage.tsx`
- Modify: `frontend/src/i18n/fr.json` + `en.json`

- [ ] **Step 4.1: Modifier `FolderCard` pour ajouter une action "Supprimer"**

Dans `frontend/src/pages/WalletDetailPage.tsx`, fonction `FolderCard` (lignes ~100-117), remplacer :
```tsx
function FolderCard({ folder, onClick }: { folder: Folder; onClick: () => void }) {
  const { t } = useTranslation()
  return (
    <Card withBorder padding="sm" style={{ cursor: 'pointer' }} onClick={onClick}>
      <Group gap="xs">
        <Text>📁</Text>
        <Stack gap={0}>
          <Text size="sm" fw={500}>
            {folder.name}
          </Text>
          <Text size="xs" c="dimmed">
            {t('secrets.paths.secretsCount', { count: folder.secrets_count })}
          </Text>
        </Stack>
      </Group>
    </Card>
  )
}
```
par :
```tsx
function FolderCard({
  folder,
  onClick,
  onDelete,
}: {
  folder: Folder
  onClick: () => void
  onDelete: () => void
}) {
  const { t } = useTranslation()
  return (
    <Card withBorder padding="sm">
      <Group justify="space-between" wrap="nowrap">
        <Group gap="xs" style={{ cursor: 'pointer', flex: 1 }} onClick={onClick}>
          <Text>📁</Text>
          <Stack gap={0}>
            <Text size="sm" fw={500}>{folder.name}</Text>
            <Text size="xs" c="dimmed">
              {t('secrets.paths.secretsCount', { count: folder.secrets_count })}
            </Text>
          </Stack>
        </Group>
        <Tooltip label={t('secrets.paths.deleteFolder')}>
          <ActionIcon
            variant="subtle"
            color="red"
            onClick={(e) => {
              e.stopPropagation()
              onDelete()
            }}
            aria-label="delete-folder"
          >
            🗑
          </ActionIcon>
        </Tooltip>
      </Group>
    </Card>
  )
}
```

(Imports à ajouter en haut de fichier : `ActionIcon`, `Tooltip` depuis `@mantine/core`. Probablement déjà importés via `Stack, Title, ...`).

- [ ] **Step 4.2: Ajouter le handler `handleDeleteFolder` dans `WalletDetailPage`**

Dans le corps de `WalletDetailPage`, après les autres handlers (ex après `handleDelete`), ajouter :

```tsx
const deleteFolderMutation = useMutation({
  mutationFn: async (folderPath: string) => {
    // 1. Compter les secrets pour la confirmation
    const countRaw = await api.get<unknown>(
      `/wallets/${walletId ?? ''}/secrets/by-path/count?path=${encodeURIComponent(folderPath)}`,
    )
    const count = (countRaw as { count: number }).count
    return { folderPath, count }
  },
  onSuccess: ({ folderPath, count }) => {
    modals.openConfirmModal({
      title: t('secrets.paths.deleteFolderTitle'),
      children: (
        <Text size="sm">
          {t('secrets.paths.deleteFolderConfirm', { path: folderPath, count })}
        </Text>
      ),
      labels: { confirm: t('secrets.paths.deleteFolder'), cancel: t('common.cancel') },
      confirmProps: { color: 'red' },
      onConfirm: async () => {
        try {
          const r = await api.delete<{ deleted: number }>(
            `/wallets/${walletId ?? ''}/secrets/by-path?path=${encodeURIComponent(folderPath)}`,
          )
          notifications.show({
            color: 'green',
            message: t('secrets.paths.deleteFolderSuccess', { count: r.deleted }),
          })
          await queryClient.invalidateQueries({ queryKey: ['wallet-tree', walletId] })
          await queryClient.invalidateQueries({ queryKey: ['wallet-secrets-path', walletId] })
        } catch (err) {
          const msg = err instanceof ApiError ? err.message : String(err)
          notifications.show({ color: 'red', title: t('common.error'), message: msg })
        }
      },
    })
  },
  onError: (err) => {
    const msg = err instanceof ApiError ? err.message : String(err)
    notifications.show({ color: 'red', title: t('common.error'), message: msg })
  },
})
```

(Vérifier que `useMutation`, `modals` sont importés. `useMutation` l'est déjà. `modals` aussi. `notifications` aussi. `ApiError` aussi.)

- [ ] **Step 4.3: Brancher le bouton sur les `FolderCard`**

Dans le rendu (vers ligne 386), remplacer :
```tsx
{treeData?.folders.map((folder) => (
  <FolderCard
    key={folder.full_path}
    folder={folder}
    onClick={() => setCurrentPath(folder.full_path)}
  />
))}
```
par :
```tsx
{treeData?.folders.map((folder) => (
  <FolderCard
    key={folder.full_path}
    folder={folder}
    onClick={() => setCurrentPath(folder.full_path)}
    onDelete={() => deleteFolderMutation.mutate(folder.full_path)}
  />
))}
```

- [ ] **Step 4.4: i18n**

Dans `fr.json` section `secrets.paths` :
```json
"deleteFolder": "Supprimer ce dossier",
"deleteFolderTitle": "Supprimer le dossier ?",
"deleteFolderConfirm": "Supprimer le dossier {{path}} ? Cela supprimera {{count}} secret(s) de manière irréversible.",
"deleteFolderSuccess": "{{count}} secret(s) supprimé(s)"
```
Idem `en.json`.

- [ ] **Step 4.5: Build TS + lint + test smoke existant**

```bash
cd /e/srcs/harpocrate/frontend && npx tsc --noEmit 2>&1 | tail -5
cd /e/srcs/harpocrate/frontend && npm run lint 2>&1 | tail -5
cd /e/srcs/harpocrate/frontend && npm test -- --run 2>&1 | tail -10
```

- [ ] **Step 4.6: Commit**

```bash
git add frontend/src/pages/WalletDetailPage.tsx frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(frontend): bouton supprimer dossier + modal de confirmation avec compte"
```

---

## Task 5: Frontend — composant `<FolderTree>` (sidebar style Windows)

**Files:**
- Create: `frontend/src/components/FolderTree.tsx`
- Modify: `frontend/src/pages/WalletDetailPage.tsx` (intégrer le composant)

- [ ] **Step 5.1: Créer le composant `FolderTree`**

Créer `frontend/src/components/FolderTree.tsx` :

```tsx
/**
 * FolderTree — arbre de dossiers expandable pour la navigation dans un wallet.
 *
 * Lazy-loading : chaque sous-niveau est fetché à la demande quand l'utilisateur
 * déploie un dossier, via GET /v1/wallets/{wid}/tree?path=...
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Stack, UnstyledButton, Text, Group, Loader } from '@mantine/core'
import { z } from 'zod'

import { api } from '@/lib/api-client'

const FolderSchema = z.object({
  name: z.string(),
  full_path: z.string(),
  secrets_count: z.number(),
  subfolders_count: z.number(),
})

const TreeDataSchema = z.object({
  path: z.string(),
  secrets_at_this_level_count: z.number(),
  folders: z.array(FolderSchema),
})

type Folder = z.infer<typeof FolderSchema>

interface TreeNodeProps {
  walletId: string
  folder: Folder
  currentPath: string
  onSelect: (path: string) => void
  level: number
}

function TreeNode({ walletId, folder, currentPath, onSelect, level }: TreeNodeProps) {
  const [expanded, setExpanded] = useState(false)
  const isCurrent = currentPath === folder.full_path
  const hasChildren = folder.subfolders_count > 0

  const { data, isLoading } = useQuery({
    queryKey: ['wallet-tree-node', walletId, folder.full_path],
    queryFn: async () => {
      const raw = await api.get<unknown>(
        `/wallets/${walletId}/tree?path=${encodeURIComponent(folder.full_path)}`,
      )
      return TreeDataSchema.parse(raw)
    },
    enabled: expanded,
  })

  return (
    <Stack gap={2}>
      <UnstyledButton
        onClick={() => {
          if (hasChildren) setExpanded(!expanded)
          onSelect(folder.full_path)
        }}
        style={{
          paddingLeft: 8 + level * 12,
          paddingRight: 8,
          paddingTop: 4,
          paddingBottom: 4,
          backgroundColor: isCurrent ? 'var(--mantine-color-brand-light)' : undefined,
          borderRadius: 4,
        }}
      >
        <Group gap={4} wrap="nowrap">
          <Text size="xs" w={12}>
            {hasChildren ? (expanded ? '▼' : '▶') : ' '}
          </Text>
          <Text size="xs">📁</Text>
          <Text size="sm" truncate fw={isCurrent ? 600 : 400}>
            {folder.name}
          </Text>
          <Text size="xs" c="dimmed">
            ({folder.secrets_count})
          </Text>
        </Group>
      </UnstyledButton>
      {expanded && (
        <Stack gap={2}>
          {isLoading && <Loader size="xs" ml={level * 12 + 16} />}
          {data?.folders.map((sub) => (
            <TreeNode
              key={sub.full_path}
              walletId={walletId}
              folder={sub}
              currentPath={currentPath}
              onSelect={onSelect}
              level={level + 1}
            />
          ))}
        </Stack>
      )}
    </Stack>
  )
}

export interface FolderTreeProps {
  walletId: string
  currentPath: string
  onSelect: (path: string) => void
}

export function FolderTree({ walletId, currentPath, onSelect }: FolderTreeProps) {
  const isRoot = currentPath === '/'

  const { data, isLoading } = useQuery({
    queryKey: ['wallet-tree-root', walletId],
    queryFn: async () => {
      const raw = await api.get<unknown>(
        `/wallets/${walletId}/tree?path=%2F`,
      )
      return TreeDataSchema.parse(raw)
    },
  })

  return (
    <Stack gap={2} style={{ minWidth: 220, maxWidth: 320 }}>
      <UnstyledButton
        onClick={() => onSelect('/')}
        style={{
          paddingLeft: 8,
          paddingRight: 8,
          paddingTop: 4,
          paddingBottom: 4,
          backgroundColor: isRoot ? 'var(--mantine-color-brand-light)' : undefined,
          borderRadius: 4,
        }}
      >
        <Group gap={4}>
          <Text size="xs">🏠</Text>
          <Text size="sm" fw={isRoot ? 600 : 400}>
            (racine)
          </Text>
        </Group>
      </UnstyledButton>

      {isLoading && <Loader size="xs" />}
      {data?.folders.map((folder) => (
        <TreeNode
          key={folder.full_path}
          walletId={walletId}
          folder={folder}
          currentPath={currentPath}
          onSelect={onSelect}
          level={0}
        />
      ))}
    </Stack>
  )
}
```

- [ ] **Step 5.2: Intégrer `FolderTree` dans `WalletDetailPage`**

Dans `frontend/src/pages/WalletDetailPage.tsx`, ajouter l'import en tête :
```tsx
import { FolderTree } from '@/components/FolderTree'
```

Et changer le rendu du `Tabs.Panel value="secrets"` (vers ligne 364) pour ajouter une grille avec sidebar à gauche :

```tsx
<Tabs.Panel value="secrets" pt="md">
  <Group align="flex-start" wrap="nowrap" gap="md">
    {/* Sidebar arbre */}
    <Stack
      gap="xs"
      style={{
        borderRight: '1px solid var(--mantine-color-gray-3)',
        paddingRight: 12,
        position: 'sticky',
        top: 12,
        maxHeight: 'calc(100vh - 200px)',
        overflowY: 'auto',
      }}
    >
      <Text fw={600} size="sm">
        {t('secrets.paths.folders')}
      </Text>
      {walletId && (
        <FolderTree
          walletId={walletId}
          currentPath={currentPath}
          onSelect={setCurrentPath}
        />
      )}
    </Stack>

    {/* Contenu central */}
    <Stack gap="md" style={{ flex: 1 }}>
      <PathBreadcrumb path={currentPath} onNavigate={setCurrentPath} />
      {/* … (le reste du contenu existant : grille de folders + secrets) */}
    </Stack>
  </Group>
</Tabs.Panel>
```

(Le reste du contenu existant — grille de folders + secrets — reste inchangé, juste enrobé dans le `<Stack style={{ flex: 1 }}>` à droite.)

- [ ] **Step 5.3: Build + lint**

```bash
cd /e/srcs/harpocrate/frontend && npx tsc --noEmit 2>&1 | tail -5
cd /e/srcs/harpocrate/frontend && npm run lint 2>&1 | tail -5
```

- [ ] **Step 5.4: Commit**

```bash
git add frontend/src/components/FolderTree.tsx frontend/src/pages/WalletDetailPage.tsx
git commit -m "feat(frontend): sidebar arbre de dossiers (style explorer Windows)"
```

---

## Task 6: Vérification finale P4

- [ ] **Step 6.1: Tests backend**

```bash
cd /e/srcs/harpocrate/backend && uv run pytest tests/test_delete_by_path.py tests/test_secrets_by_id.py tests/test_secret_paths.py tests/test_invalid_secret_path_handler.py tests/test_secrets_default_raw_type.py tests/test_secret_types_deprecated_block.py tests/test_any_auth_no_scope.py tests/test_secret_types_api_key_access.py tests/test_admin_secret_types.py -v 2>&1 | tail -25
```
Expected : tous PASS.

- [ ] **Step 6.2: Tests frontend**

```bash
cd /e/srcs/harpocrate/frontend && npm test -- --run 2>&1 | tail -15
```
Expected : pas de NEW failures.

- [ ] **Step 6.3: Build production frontend**

```bash
cd /e/srcs/harpocrate/frontend && npm run build 2>&1 | tail -15
```
Expected : build OK.

- [ ] **Step 6.4: Ruff backend**

```bash
cd /e/srcs/harpocrate/backend && uv run ruff check app/db/repositories/secrets.py app/services/secrets.py app/api/v1/secrets.py tests/test_delete_by_path.py 2>&1
```

- [ ] **Step 6.5: Format si besoin + commit final**

```bash
cd /e/srcs/harpocrate/backend && uv run ruff format app/db/repositories/secrets.py app/services/secrets.py app/api/v1/secrets.py tests/test_delete_by_path.py 2>&1
cd /e/srcs/harpocrate && git status && (git diff --quiet || (git add -u && git commit -m "chore: ruff format après P4"))
```

---

## Acceptance criteria P4

- ✅ `GET /v1/wallets/{wid}/secrets/by-path/count?path=/foo/` retourne `{count: N}`
- ✅ `DELETE /v1/wallets/{wid}/secrets/by-path?path=/foo/` retourne `{deleted: N}` + audit log par secret supprimé
- ✅ `DELETE /v1/wallets/{wid}/secrets/by-path?path=/` retourne 400 `cannot_delete_root_path`
- ✅ Frontend `SecretNewPage` accepte les noms à `/` (validation alignée backend)
- ✅ Frontend `SecretNewPage` pré-remplit avec `prefixPath` quand on arrive depuis WalletDetailPage
- ✅ Frontend `FolderCard` a un bouton "🗑 supprimer dossier" + modal de confirmation avec compte
- ✅ Frontend `WalletDetailPage` a un sidebar arbre cliquable (style Windows Explorer)
- ✅ Aucune régression sur les tests existants

## Hors scope P4 (futurs lots)

- Drag & drop entre dossiers (nécessite endpoint backend "move secret")
- Menu contextuel clic-droit (clavier-inaccessible, mauvais sur mobile — préférer les boutons explicites)
- Soft delete pour les suppressions de dossier (la suppression est hard, irréversible — cohérent avec la suppression unitaire actuelle)
- Préservation de l'état "expanded" du tree entre rechargements (URL ou localStorage)
- Recherche fulltext globale dans le wallet
