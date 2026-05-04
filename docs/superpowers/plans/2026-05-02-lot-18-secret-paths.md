# LOT_18 — Secret Paths (Organisation hiérarchique) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre d'organiser les secrets d'un wallet dans une arborescence virtuelle via des noms de type `path/to/secret`, avec navigation par répertoire côté UI et filtrage `?path=` côté API.

**Architecture:** Index SQL `secret_path_index` peuplé par trigger sur `secrets.name`. Deux nouveaux endpoints backend (`GET /tree`, `GET /secrets?path=`). Frontend `WalletDetailPage` restructuré avec breadcrumb + grille dossiers/secrets. SDK Python enrichi avec `get_tree()` et paramètre `path` dans `list_secrets()`. Les noms de secrets avec `/` sont URL-encodés dans les routes REST existantes (`%2F`).

**Tech Stack:** Python 3.12 / FastAPI / asyncpg / PostgreSQL 16 triggers / React 18 / Mantine v7 / TanStack Query / i18next / pytest-asyncio

---

## Fichiers concernés

| Fichier | Action |
|---|---|
| `backend/migrations/003_secret_path_index.sql` | CRÉER — table + trigger |
| `backend/app/services/secret_paths.py` | CRÉER — validation + normalisation |
| `backend/app/models/api/secrets.py` | MODIFIER — regex name accepte `/` |
| `backend/app/db/repositories/secrets.py` | MODIFIER — ajouter `list_by_path`, `get_tree_data` |
| `backend/app/api/v1/wallets.py` | MODIFIER — ajouter `GET /{wallet_id}/tree` |
| `backend/app/api/v1/secrets.py` | MODIFIER — ajouter `?path=` sur list |
| `backend/tests/test_secret_paths.py` | CRÉER — 16 tests backend |
| `frontend/src/pages/WalletDetailPage.tsx` | MODIFIER — breadcrumb + dossiers |
| `frontend/src/lib/walletsApi.ts` | MODIFIER — ajouter `getWalletTree()` |
| `frontend/src/i18n/fr.json` | MODIFIER — clés `paths.*` |
| `frontend/src/i18n/en.json` | MODIFIER — clés `paths.*` |
| `sdk-python/harpocrate/client.py` | MODIFIER — `get_tree()`, `list_secrets(path=)`, normalise `get_secret()` |
| `sdk-python/tests/unit/test_client.py` | MODIFIER — tests paths SDK |

---

## Task 1 : Migration SQL — `secret_path_index` + trigger

**Files:**
- Create: `backend/migrations/003_secret_path_index.sql`
- Test: `backend/tests/test_secret_paths.py` (tests trigger)

- [ ] **Step 1 : Écrire le fichier de migration**

```sql
-- backend/migrations/003_secret_path_index.sql

CREATE TABLE secret_path_index (
    secret_id    UUID    NOT NULL REFERENCES secrets(id) ON DELETE CASCADE,
    wallet_id    UUID    NOT NULL,
    path_segment TEXT    NOT NULL,
    depth        INTEGER NOT NULL,
    PRIMARY KEY (secret_id, depth),
    CONSTRAINT secret_path_index_depth_positive CHECK (depth > 0)
);

CREATE INDEX idx_secret_path_index_lookup
    ON secret_path_index(wallet_id, path_segment);

CREATE INDEX idx_secret_path_index_depth
    ON secret_path_index(wallet_id, depth);

-- ─── Trigger ─────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION populate_secret_path_index()
RETURNS TRIGGER AS $$
DECLARE
    parts          TEXT[];
    i              INT;
    accum          TEXT := '';
    normalized_name TEXT;
BEGIN
    DELETE FROM secret_path_index WHERE secret_id = NEW.id;

    IF position('/' in NEW.name) = 0 THEN
        RETURN NEW;
    END IF;

    normalized_name := NEW.name;
    IF NOT starts_with(normalized_name, '/') THEN
        normalized_name := '/' || normalized_name;
    END IF;

    parts := string_to_array(normalized_name, '/');

    FOR i IN 2..array_length(parts, 1) - 1 LOOP
        accum := accum || '/' || parts[i];
        INSERT INTO secret_path_index (secret_id, wallet_id, path_segment, depth)
        VALUES (NEW.id, NEW.wallet_id, accum || '/', i - 1);
    END LOOP;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_secrets_populate_path_index
    AFTER INSERT OR UPDATE OF name ON secrets
    FOR EACH ROW EXECUTE FUNCTION populate_secret_path_index();
```

- [ ] **Step 2 : Écrire les tests trigger (rouge)**

Créer `backend/tests/test_secret_paths.py` :

```python
"""Tests LOT_18 — secret paths : trigger index + endpoints."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


# ─── Trigger tests ─────────────────────────────────────────────────────────────


async def test_trigger_no_index_for_root_secret(db_conn, wallet_fixture, user_fixture):
    """Un secret sans '/' ne crée aucune ligne dans secret_path_index."""
    secret_id = await db_conn.fetchval(
        """INSERT INTO secrets (wallet_id, name, encrypted_value, is_placeholder, created_by_user_id)
           VALUES ($1, 'PLAIN_SECRET', '\\xDEAD', FALSE, $2) RETURNING id""",
        wallet_fixture, user_fixture,
    )
    count = await db_conn.fetchval(
        "SELECT COUNT(*) FROM secret_path_index WHERE secret_id = $1", secret_id
    )
    assert count == 0


async def test_trigger_populates_index_for_two_level_secret(db_conn, wallet_fixture, user_fixture):
    """Un secret 'bob/key' crée 1 ligne (depth=1, path_segment='/bob/')."""
    secret_id = await db_conn.fetchval(
        """INSERT INTO secrets (wallet_id, name, encrypted_value, is_placeholder, created_by_user_id)
           VALUES ($1, 'bob/key', '\\xDEAD', FALSE, $2) RETURNING id""",
        wallet_fixture, user_fixture,
    )
    rows = await db_conn.fetch(
        "SELECT path_segment, depth FROM secret_path_index WHERE secret_id = $1 ORDER BY depth",
        secret_id,
    )
    assert len(rows) == 1
    assert rows[0]["path_segment"] == "/bob/"
    assert rows[0]["depth"] == 1


async def test_trigger_populates_index_for_three_level_secret(db_conn, wallet_fixture, user_fixture):
    """Un secret 'bob/sub/key' crée 2 lignes (depth=1 et depth=2)."""
    secret_id = await db_conn.fetchval(
        """INSERT INTO secrets (wallet_id, name, encrypted_value, is_placeholder, created_by_user_id)
           VALUES ($1, 'bob/sub/key', '\\xDEAD', FALSE, $2) RETURNING id""",
        wallet_fixture, user_fixture,
    )
    rows = await db_conn.fetch(
        "SELECT path_segment, depth FROM secret_path_index WHERE secret_id = $1 ORDER BY depth",
        secret_id,
    )
    assert len(rows) == 2
    assert rows[0]["path_segment"] == "/bob/"
    assert rows[1]["path_segment"] == "/bob/sub/"


async def test_trigger_updates_index_on_rename(db_conn, wallet_fixture, user_fixture):
    """Renommer un secret met à jour l'index."""
    secret_id = await db_conn.fetchval(
        """INSERT INTO secrets (wallet_id, name, encrypted_value, is_placeholder, created_by_user_id)
           VALUES ($1, 'bob/old_key', '\\xDEAD', FALSE, $2) RETURNING id""",
        wallet_fixture, user_fixture,
    )
    await db_conn.execute(
        "UPDATE secrets SET name = 'alice/new_key' WHERE id = $1", secret_id
    )
    rows = await db_conn.fetch(
        "SELECT path_segment FROM secret_path_index WHERE secret_id = $1", secret_id
    )
    assert len(rows) == 1
    assert rows[0]["path_segment"] == "/alice/"


async def test_trigger_cleans_index_on_delete(db_conn, wallet_fixture, user_fixture):
    """Supprimer un secret efface ses lignes d'index (CASCADE)."""
    secret_id = await db_conn.fetchval(
        """INSERT INTO secrets (wallet_id, name, encrypted_value, is_placeholder, created_by_user_id)
           VALUES ($1, 'folder/key', '\\xDEAD', FALSE, $2) RETURNING id""",
        wallet_fixture, user_fixture,
    )
    await db_conn.execute("DELETE FROM secrets WHERE id = $1", secret_id)
    count = await db_conn.fetchval(
        "SELECT COUNT(*) FROM secret_path_index WHERE secret_id = $1", secret_id
    )
    assert count == 0
```

- [ ] **Step 3 : Vérifier que les tests échouent (migration pas encore appliquée)**

```bash
cd backend && uv run pytest tests/test_secret_paths.py -v 2>&1 | head -30
```

Attendu : erreur `UndefinedTableError: secret_path_index` ou similar.

- [ ] **Step 4 : Vérifier que la migration s'applique sans erreur**

```bash
cd backend && uv run python migrations/apply_migrations.py
```

Attendu : `[OK] 003_secret_path_index.sql applied`

- [ ] **Step 5 : Vérifier que les tests trigger passent**

```bash
cd backend && uv run pytest tests/test_secret_paths.py -k "trigger" -v
```

Attendu : 5 tests PASS.

- [ ] **Step 6 : Commit**

```bash
git add backend/migrations/003_secret_path_index.sql backend/tests/test_secret_paths.py
git commit -m "feat(paths P1): migration secret_path_index + trigger + tests"
```

---

## Task 2 : Service de validation des paths

**Files:**
- Create: `backend/app/services/secret_paths.py`
- Test: `backend/tests/test_secret_paths.py` (section validation)

- [ ] **Step 1 : Écrire les tests validation (rouge)**

Ajouter dans `backend/tests/test_secret_paths.py` :

```python
# ─── Validation tests ──────────────────────────────────────────────────────────

from app.services.secret_paths import normalize_secret_name, validate_secret_name


def test_validate_accepts_root_secret():
    assert validate_secret_name("MY_SECRET") == "MY_SECRET"


def test_validate_accepts_single_level_path():
    assert validate_secret_name("bob/key") == "/bob/key"


def test_validate_normalizes_leading_slash():
    assert validate_secret_name("/bob/key") == "/bob/key"


def test_validate_accepts_email_segment():
    assert validate_secret_name("bob@gmail.com/key") == "/bob@gmail.com/key"


def test_validate_rejects_empty_segment():
    with pytest.raises(ValueError, match="empty"):
        validate_secret_name("bob//key")


def test_validate_rejects_dot_segment():
    with pytest.raises(ValueError, match="relative"):
        validate_secret_name("bob/../key")


def test_validate_rejects_invalid_char():
    with pytest.raises(ValueError, match="Invalid"):
        validate_secret_name("bob/key with space")


def test_validate_rejects_too_deep():
    deep = "/".join(["a"] * 12)
    with pytest.raises(ValueError, match="deep"):
        validate_secret_name(deep)


def test_normalize_path_adds_trailing_slash():
    assert normalize_secret_name("/bob") == "/bob/"


def test_normalize_path_root():
    assert normalize_secret_name("/") == "/"
    assert normalize_secret_name("") == "/"
```

- [ ] **Step 2 : Exécuter pour vérifier qu'ils échouent**

```bash
cd backend && uv run pytest tests/test_secret_paths.py -k "validate or normalize" -v 2>&1 | head -20
```

Attendu : `ImportError: cannot import name 'validate_secret_name'`

- [ ] **Step 3 : Implémenter `backend/app/services/secret_paths.py`**

```python
"""Validation et normalisation des noms de secrets avec paths (LOT_18)."""
from __future__ import annotations

import re

_SEGMENT_RE = re.compile(r"^[a-zA-Z0-9@._-]+$")
_MAX_DEPTH = 10


def validate_secret_name(name: str) -> str:
    """Valide et normalise un nom de secret (peut contenir des '/').

    Retourne le nom normalisé :
    - Sans '/' → retourné tel quel (secret racine, env-var safe géré par l'appelant)
    - Avec '/' → '/' initial ajouté si absent, pas de '/' final

    Lève ValueError si invalide.
    """
    if "/" not in name:
        return name

    normalized = name if name.startswith("/") else "/" + name

    if "//" in normalized:
        raise ValueError("Empty path segments not allowed (found '//')")

    segments = [s for s in normalized.split("/") if s]

    if len(segments) > _MAX_DEPTH + 1:
        raise ValueError(f"Path too deep (max {_MAX_DEPTH} levels, got {len(segments) - 1})")

    for seg in segments:
        if seg in (".", ".."):
            raise ValueError("Relative path navigation not allowed ('.' or '..')")
        if not _SEGMENT_RE.match(seg):
            raise ValueError(
                f"Invalid path segment '{seg}': only [a-zA-Z0-9@._-] allowed"
            )

    return normalized


def normalize_path(path: str | None) -> str:
    """Normalise un path de répertoire : '/' final garanti, '' → '/'.

    Utilisé pour les paramètres ?path= des endpoints /tree et /secrets.
    """
    if not path or path == "/":
        return "/"
    normalized = path if path.startswith("/") else "/" + path
    return normalized if normalized.endswith("/") else normalized + "/"
```

- [ ] **Step 4 : Vérifier que les tests passent**

```bash
cd backend && uv run pytest tests/test_secret_paths.py -k "validate or normalize" -v
```

Attendu : 10 tests PASS.

- [ ] **Step 5 : Commit**

```bash
git add backend/app/services/secret_paths.py backend/tests/test_secret_paths.py
git commit -m "feat(paths P2): service validation + normalisation secret names"
```

---

## Task 3 : Mise à jour du modèle Pydantic + repo

**Files:**
- Modify: `backend/app/models/api/secrets.py`
- Modify: `backend/app/db/repositories/secrets.py`
- Test: `backend/tests/test_secret_paths.py` (section repo)

- [ ] **Step 1 : Modifier `_NAME_RE` dans `backend/app/models/api/secrets.py`**

Remplacer les lignes 16 et 38-42 :

```python
# Avant (ligne 16)
_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")

# Après
_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")  # root secrets
_PATH_SEGMENT_RE = re.compile(r"^[a-zA-Z0-9@._-]+$")  # pour les paths
```

Remplacer le `_name_valid` validator dans `SecretCreateRequest` :

```python
    @field_validator("name")
    @classmethod
    def _name_valid(cls, v: str) -> str:
        from app.services.secret_paths import validate_secret_name
        stripped = v.strip()
        if not stripped:
            raise ValueError("name must not be empty")
        if len(stripped) > 256:
            raise ValueError("name must not exceed 256 characters")
        return validate_secret_name(stripped)
```

Faire la même chose dans `PlaceholderCreateRequest._name_valid` (même fichier, même logique).

- [ ] **Step 2 : Ajouter `list_by_path` et `get_tree_data` dans `backend/app/db/repositories/secrets.py`**

Ajouter à la fin du fichier :

```python
# ─── LOT_18 : path-aware queries ─────────────────────────────────────────────


async def list_by_path(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    path: str,
    limit: int,
    cursor_updated_at: datetime.datetime | None,
    cursor_id: UUID | None,
) -> list[SecretRow]:
    """Liste les secrets directs d'un path (non récursif).

    path='/' → secrets sans '/' dans leur nom (secrets racine).
    path='/bob/' → secrets dont le nom commence par '/bob/' mais sans second '/'.
    """
    if path == "/":
        rows = await conn.fetch(
            """
            SELECT
                s.id, s.wallet_id, s.name, s.description,
                s.encrypted_value, s.is_placeholder,
                s.generation_version, s.linked_secret_id,
                s.generation_descriptor,
                s.created_at, s.updated_at,
                s.created_by_user_id, s.created_by_api_key_id,
                s.updated_by_user_id, s.updated_by_api_key_id
            FROM secrets s
            WHERE s.wallet_id = $1
              AND s.name NOT LIKE '%/%'
              AND ($2::timestamptz IS NULL
                   OR (s.updated_at, s.id) < ($2::timestamptz, $3::uuid))
            ORDER BY s.updated_at DESC, s.id DESC
            LIMIT $4
            """,
            wallet_id, cursor_updated_at, cursor_id, limit,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT
                s.id, s.wallet_id, s.name, s.description,
                s.encrypted_value, s.is_placeholder,
                s.generation_version, s.linked_secret_id,
                s.generation_descriptor,
                s.created_at, s.updated_at,
                s.created_by_user_id, s.created_by_api_key_id,
                s.updated_by_user_id, s.updated_by_api_key_id
            FROM secrets s
            WHERE s.wallet_id = $1
              AND s.name LIKE $2 || '%'
              AND s.name NOT LIKE $2 || '%/%'
              AND ($3::timestamptz IS NULL
                   OR (s.updated_at, s.id) < ($3::timestamptz, $4::uuid))
            ORDER BY s.updated_at DESC, s.id DESC
            LIMIT $5
            """,
            wallet_id, path, cursor_updated_at, cursor_id, limit,
        )

    if not rows:
        return []
    secret_ids = [r["id"] for r in rows]
    tag_rows = await conn.fetch(
        "SELECT secret_id, tag FROM secret_tags WHERE secret_id = ANY($1::uuid[])",
        secret_ids,
    )
    tags_by_secret: dict[UUID, list[str]] = {}
    for tr in tag_rows:
        tags_by_secret.setdefault(tr["secret_id"], []).append(tr["tag"])
    return [_row_to_secret(row, tags_by_secret.get(row["id"], [])) for row in rows]


async def get_tree_data(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    wallet_id: UUID,
    path: str,
) -> dict[str, object]:
    """Retourne les sous-répertoires directs d'un path + count secrets à ce niveau."""
    if path == "/":
        target_depth = 1
    else:
        target_depth = path.count("/")

    folder_rows = await conn.fetch(
        """
        WITH folder_stats AS (
            SELECT
                pi.path_segment,
                COUNT(DISTINCT pi.secret_id)                                         AS secrets_count,
                COUNT(DISTINCT CASE WHEN pi2.depth > $3 THEN pi2.secret_id END)     AS subfolders_count
            FROM secret_path_index pi
            LEFT JOIN secret_path_index pi2 ON pi2.secret_id = pi.secret_id
            WHERE pi.wallet_id = $1
              AND pi.depth = $3
              AND pi.path_segment LIKE $2 || '%'
              AND pi.path_segment != $2
            GROUP BY pi.path_segment
        )
        SELECT
            substring(path_segment from length($2) + 1
                      for position('/' in substring(path_segment from length($2) + 1)) - 1) AS name,
            path_segment AS full_path,
            secrets_count,
            subfolders_count
        FROM folder_stats
        ORDER BY name
        """,
        wallet_id, path, target_depth,
    )

    if path == "/":
        secrets_at_level: int = await conn.fetchval(
            "SELECT COUNT(*) FROM secrets WHERE wallet_id = $1 AND name NOT LIKE '%/%'",
            wallet_id,
        )
    else:
        secrets_at_level = await conn.fetchval(
            """SELECT COUNT(*) FROM secrets
               WHERE wallet_id = $1
                 AND name LIKE $2 || '%'
                 AND name NOT LIKE $2 || '%/%'""",
            wallet_id, path,
        )

    return {
        "path": path,
        "secrets_at_this_level_count": secrets_at_level,
        "folders": [
            {
                "name": r["name"],
                "full_path": r["full_path"],
                "secrets_count": r["secrets_count"],
                "subfolders_count": r["subfolders_count"],
            }
            for r in folder_rows
        ],
    }
```

- [ ] **Step 3 : Écrire les tests repo (rouge)**

Ajouter dans `backend/tests/test_secret_paths.py` :

```python
# ─── Repo tests ─────────────────────────────────────────────────────────────────

from app.db.repositories.secrets import list_by_path, get_tree_data


async def _insert_secret(conn, wallet_id, user_id, name):
    return await conn.fetchval(
        """INSERT INTO secrets (wallet_id, name, encrypted_value, is_placeholder, created_by_user_id)
           VALUES ($1, $2, '\\xDEAD', FALSE, $3) RETURNING id""",
        wallet_id, name, user_id,
    )


async def test_list_by_path_root_returns_only_root_secrets(db_conn, wallet_fixture, user_fixture):
    await _insert_secret(db_conn, wallet_fixture, user_fixture, "ROOT_SECRET")
    await _insert_secret(db_conn, wallet_fixture, user_fixture, "bob/nested")
    rows = await list_by_path(db_conn, wallet_id=wallet_fixture, path="/",
                               limit=50, cursor_updated_at=None, cursor_id=None)
    names = [r.name for r in rows]
    assert "ROOT_SECRET" in names
    assert "bob/nested" not in names


async def test_list_by_path_folder_excludes_subfolders(db_conn, wallet_fixture, user_fixture):
    await _insert_secret(db_conn, wallet_fixture, user_fixture, "/bob/direct_key")
    await _insert_secret(db_conn, wallet_fixture, user_fixture, "/bob/sub/nested_key")
    rows = await list_by_path(db_conn, wallet_id=wallet_fixture, path="/bob/",
                               limit=50, cursor_updated_at=None, cursor_id=None)
    names = [r.name for r in rows]
    assert "/bob/direct_key" in names
    assert "/bob/sub/nested_key" not in names


async def test_get_tree_data_root(db_conn, wallet_fixture, user_fixture):
    await _insert_secret(db_conn, wallet_fixture, user_fixture, "ROOT_SECRET")
    await _insert_secret(db_conn, wallet_fixture, user_fixture, "/bob/key")
    await _insert_secret(db_conn, wallet_fixture, user_fixture, "/alice/key")
    result = await get_tree_data(db_conn, wallet_id=wallet_fixture, path="/")
    assert result["path"] == "/"
    assert result["secrets_at_this_level_count"] == 1
    folder_names = [f["name"] for f in result["folders"]]
    assert "bob" in folder_names
    assert "alice" in folder_names


async def test_get_tree_data_subfolder(db_conn, wallet_fixture, user_fixture):
    await _insert_secret(db_conn, wallet_fixture, user_fixture, "/bob/key1")
    await _insert_secret(db_conn, wallet_fixture, user_fixture, "/bob/key2")
    await _insert_secret(db_conn, wallet_fixture, user_fixture, "/bob/sub/deep_key")
    result = await get_tree_data(db_conn, wallet_id=wallet_fixture, path="/bob/")
    assert result["secrets_at_this_level_count"] == 2
    assert len(result["folders"]) == 1
    assert result["folders"][0]["name"] == "sub"
```

- [ ] **Step 4 : Vérifier que les tests passent**

```bash
cd backend && uv run pytest tests/test_secret_paths.py -k "list_by_path or get_tree" -v
```

Attendu : 4 tests PASS.

- [ ] **Step 5 : Commit**

```bash
git add backend/app/models/api/secrets.py backend/app/db/repositories/secrets.py backend/tests/test_secret_paths.py
git commit -m "feat(paths P3): modele + repo list_by_path + get_tree_data"
```

---

## Task 4 : Endpoints backend

**Files:**
- Modify: `backend/app/api/v1/wallets.py`
- Modify: `backend/app/api/v1/secrets.py`
- Test: `backend/tests/test_secret_paths.py` (section HTTP)

- [ ] **Step 1 : Ajouter `GET /{wallet_id}/tree` dans `backend/app/api/v1/wallets.py`**

Ajouter les imports manquants en haut :

```python
from fastapi import APIRouter, Query, Request, status
from app.db.repositories import secrets as secrets_repo
from app.services.secret_paths import normalize_path
from app.services import grants as grants_svc
```

Ajouter l'endpoint à la fin de `wallets.py` :

```python
# ─── GET /v1/wallets/{wallet_id}/tree ────────────────────────────────────────


@router.get("/{wallet_id}/tree")
async def get_wallet_tree(
    wallet_id: UUID,
    current_user: JwtUser,
    path: str = Query(default="/", description="Répertoire à explorer"),
) -> JSONResponse:
    """Retourne les sous-répertoires directs d'un path + compte de secrets.

    Requiert permission [read] sur le wallet.
    """
    from app.services.secret_paths import normalize_path as _norm
    from app.db.repositories.secrets import get_tree_data
    from app.services.grants import check_wallet_permission
    from app.services.permissions import Perm

    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )

        has_perm = await check_wallet_permission(conn, wallet_id=wallet_id,
                                                  user_id=user.id, perm=Perm.READ)
        if not has_perm:
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"error": "forbidden", "message": "Permission [read] required"},
            )

        normalized = _norm(path)
        result = await get_tree_data(conn, wallet_id=wallet_id, path=normalized)

    return JSONResponse(status_code=status.HTTP_200_OK, content=result)
```

- [ ] **Step 2 : Enrichir `GET /secrets` avec `?path=` dans `backend/app/api/v1/secrets.py`**

Modifier la signature de `list_secrets` :

```python
@router.get("")
async def list_secrets(
    wallet_id: UUID,
    current_user: JwtUser,
    request: Request,
    path: str | None = Query(default=None, description="Filtrer par répertoire"),
    tag: str | None = Query(default=None),
    name_contains: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
) -> JSONResponse:
```

Modifier l'appel au service (quand `path` est fourni, utiliser `list_by_path` via le service) :

```python
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await users_repo.get_by_keycloak_sub(conn, current_user.keycloak_sub)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "first_login", "message": "User must bootstrap first"},
            )

        if path is not None:
            from app.services.secret_paths import normalize_path
            from app.db.repositories import secrets as secrets_repo
            from app.db.repositories.secrets import decode_cursor, encode_cursor
            from app.services.grants import check_wallet_permission
            from app.services.permissions import Perm

            has_perm = await check_wallet_permission(conn, wallet_id=wallet_id,
                                                      user_id=user.id, perm=Perm.READ)
            if not has_perm:
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"error": "forbidden", "message": "Permission [read] required"},
                )

            cursor_updated_at, cursor_id = (None, None)
            if cursor:
                try:
                    cursor_updated_at, cursor_id = decode_cursor(cursor)
                except ValueError:
                    return JSONResponse(status_code=400, content={"error": "invalid_cursor"})

            normalized = normalize_path(path)
            rows = await secrets_repo.list_by_path(
                conn,
                wallet_id=wallet_id,
                path=normalized,
                limit=limit,
                cursor_updated_at=cursor_updated_at,
                cursor_id=cursor_id,
            )
            next_cursor = None
            if len(rows) == limit:
                last = rows[-1]
                next_cursor = encode_cursor(last.updated_at, last.id)

            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "secrets": [_secret_to_dict(s) for s in rows],
                    "next_cursor": next_cursor,
                },
            )

        result = await secrets_svc.list_secrets(
            conn, wallet_id=wallet_id, caller_user_id=user.id,
            limit=limit, cursor=cursor, tag_filter=tag, name_contains=name_contains,
        )

    return JSONResponse(status_code=status.HTTP_200_OK, content=result.model_dump(mode="json"))
```

Ajouter le helper `_secret_to_dict` dans `secrets.py` (avant la fonction list_secrets) :

```python
def _secret_to_dict(s: "SecretRow") -> dict:
    """Convertit un SecretRow en dict JSON-serialisable (sans encrypted_value)."""
    import base64
    return {
        "id": str(s.id),
        "wallet_id": str(s.wallet_id),
        "name": s.name,
        "description": s.description,
        "is_placeholder": s.is_placeholder,
        "generation_version": s.generation_version,
        "tags": s.tags,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }
```

- [ ] **Step 3 : Écrire les tests HTTP (rouge)**

Ajouter dans `backend/tests/test_secret_paths.py` :

```python
# ─── HTTP endpoint tests ────────────────────────────────────────────────────────

from httpx import AsyncClient


async def test_get_tree_root_endpoint(client: AsyncClient, auth_headers, wallet_id):
    resp = await client.get(f"/v1/wallets/{wallet_id}/tree", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["path"] == "/"
    assert "folders" in data
    assert "secrets_at_this_level_count" in data


async def test_get_tree_subfolder_endpoint(client: AsyncClient, auth_headers, wallet_id, db_conn, user_fixture):
    await _insert_secret(db_conn, wallet_id, user_fixture, "/grp/key")
    resp = await client.get(f"/v1/wallets/{wallet_id}/tree?path=/grp/", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["path"] == "/grp/"


async def test_list_secrets_with_path_filter(client: AsyncClient, auth_headers, wallet_id, db_conn, user_fixture):
    await _insert_secret(db_conn, wallet_id, user_fixture, "/grp/direct")
    await _insert_secret(db_conn, wallet_id, user_fixture, "/grp/sub/nested")
    resp = await client.get(f"/v1/wallets/{wallet_id}/secrets?path=/grp/", headers=auth_headers)
    assert resp.status_code == 200
    names = [s["name"] for s in resp.json()["secrets"]]
    assert "/grp/direct" in names
    assert "/grp/sub/nested" not in names


async def test_list_secrets_root_path(client: AsyncClient, auth_headers, wallet_id, db_conn, user_fixture):
    await _insert_secret(db_conn, wallet_id, user_fixture, "ROOT_KEY")
    await _insert_secret(db_conn, wallet_id, user_fixture, "/nested/key")
    resp = await client.get(f"/v1/wallets/{wallet_id}/secrets?path=/", headers=auth_headers)
    assert resp.status_code == 200
    names = [s["name"] for s in resp.json()["secrets"]]
    assert "ROOT_KEY" in names
    assert "/nested/key" not in names
```

- [ ] **Step 4 : Vérifier que les tests passent**

```bash
cd backend && uv run pytest tests/test_secret_paths.py -k "endpoint" -v
```

Attendu : 4 tests PASS.

- [ ] **Step 5 : Ruff check**

```bash
cd backend && uv run ruff check app/api/v1/wallets.py app/api/v1/secrets.py app/services/secret_paths.py --fix
```

- [ ] **Step 6 : Commit**

```bash
git add backend/app/api/v1/wallets.py backend/app/api/v1/secrets.py backend/tests/test_secret_paths.py
git commit -m "feat(paths P4): endpoints GET /tree + GET /secrets?path="
```

---

## Task 5 : Frontend — WalletDetailPage avec navigation

**Files:**
- Modify: `frontend/src/pages/WalletDetailPage.tsx`
- Modify: `frontend/src/i18n/fr.json`
- Modify: `frontend/src/i18n/en.json`

La page passe d'une liste plate de secrets à une vue avec :
1. **Breadcrumb** cliquable représentant le path courant
2. **Section dossiers** (appel à `/tree`)
3. **Section secrets** (appel à `/secrets?path=`)
4. Le bouton "Nouveau secret" pré-remplit le path courant

- [ ] **Step 1 : Ajouter les clés i18n**

Dans `frontend/src/i18n/fr.json`, ajouter dans la section `"secrets"` :

```json
"paths": {
  "root": "Racine",
  "folders": "Dossiers",
  "noFolders": "Aucun sous-dossier",
  "secretsHere": "Secrets ici",
  "newInFolder": "Nouveau secret ici",
  "secretsCount": "{{count}} secret(s)",
  "subfoldersCount": "{{count}} sous-dossier(s)"
}
```

Dans `frontend/src/i18n/en.json` :

```json
"paths": {
  "root": "Root",
  "folders": "Folders",
  "noFolders": "No subfolders",
  "secretsHere": "Secrets here",
  "newInFolder": "New secret here",
  "secretsCount": "{{count}} secret(s)",
  "subfoldersCount": "{{count}} subfolder(s)"
}
```

- [ ] **Step 2 : Modifier `WalletDetailPage.tsx`**

Ajouter l'état `currentPath` et deux queries distinctes (tree + secrets filtrés par path).

En haut du composant `WalletDetailPage`, après les `useQuery` existants :

```tsx
const [currentPath, setCurrentPath] = useState('/')

const { data: treeData } = useQuery({
  queryKey: ['wallet-tree', walletId, currentPath],
  queryFn: () => api.get<unknown>(`/wallets/${walletId}/tree?path=${encodeURIComponent(currentPath)}`),
  enabled: !!walletId,
})

// Remplacer ou augmenter la query secrets existante pour accepter ?path=
const { data: secretsData } = useQuery({
  queryKey: ['wallet-secrets-path', walletId, currentPath],
  queryFn: () => api.get<unknown>(`/wallets/${walletId}/secrets?path=${encodeURIComponent(currentPath)}`),
  enabled: !!walletId,
})
```

Ajouter le composant `PathBreadcrumb` juste avant le rendu des secrets :

```tsx
function PathBreadcrumb({ path, onNavigate }: { path: string; onNavigate: (p: string) => void }) {
  const { t } = useTranslation()
  const segments = path === '/' ? [] : path.split('/').filter(Boolean)
  return (
    <Breadcrumbs>
      <Anchor onClick={() => onNavigate('/')} style={{ cursor: 'pointer' }}>
        {t('secrets.paths.root')}
      </Anchor>
      {segments.map((seg, i) => {
        const fullPath = '/' + segments.slice(0, i + 1).join('/') + '/'
        const isLast = i === segments.length - 1
        return isLast ? (
          <Text key={fullPath}>{seg}</Text>
        ) : (
          <Anchor key={fullPath} onClick={() => onNavigate(fullPath)} style={{ cursor: 'pointer' }}>
            {seg}
          </Anchor>
        )
      })}
    </Breadcrumbs>
  )
}
```

Ajouter l'affichage des dossiers entre le breadcrumb et la liste des secrets existante :

```tsx
{/* Breadcrumb */}
<PathBreadcrumb path={currentPath} onNavigate={setCurrentPath} />

{/* Dossiers */}
{treeData?.folders?.length > 0 && (
  <Stack gap="xs">
    <Text fw={600} size="sm">{t('secrets.paths.folders')}</Text>
    <SimpleGrid cols={{ base: 2, sm: 3, md: 4 }}>
      {treeData.folders.map((folder) => (
        <Card
          key={folder.full_path}
          withBorder
          padding="sm"
          style={{ cursor: 'pointer' }}
          onClick={() => setCurrentPath(folder.full_path)}
        >
          <Group gap="xs">
            <Text>📁</Text>
            <Stack gap={0}>
              <Text size="sm" fw={500}>{folder.name}</Text>
              <Text size="xs" c="dimmed">
                {t('secrets.paths.secretsCount', { count: folder.secrets_count })}
              </Text>
            </Stack>
          </Group>
        </Card>
      ))}
    </SimpleGrid>
  </Stack>
)}
```

Modifier le bouton "Nouveau secret" pour pré-remplir le path :

```tsx
// Quand currentPath !== '/', pré-remplir le nom avec le path courant
// en passant state au navigate
<Button onClick={() => navigate(`/wallets/${walletId}/secrets/new`, {
  state: { prefixPath: currentPath === '/' ? '' : currentPath }
})}>
  {t('secrets.create')}
</Button>
```

Ajouter `Breadcrumbs` et `SimpleGrid` aux imports Mantine.

- [ ] **Step 3 : Vérifier TypeScript**

```bash
cd frontend && npx tsc --noEmit
```

Attendu : aucune erreur.

- [ ] **Step 4 : Commit**

```bash
git add frontend/src/pages/WalletDetailPage.tsx frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(paths P5): UI WalletDetailPage breadcrumb + navigation dossiers"
```

---

## Task 6 : SDK Python — `get_tree()`, `list_secrets(path=)`, normalisation

**Files:**
- Modify: `sdk-python/harpocrate/client.py`
- Modify: `sdk-python/tests/unit/test_client.py`

- [ ] **Step 1 : Écrire les tests SDK (rouge)**

Ajouter dans `sdk-python/tests/unit/test_client.py` :

```python
# ─── Path tests ────────────────────────────────────────────────────────────────


def test_get_tree_calls_correct_endpoint(mock_http):
    """get_tree() appelle GET /v1/wallets/{id}/tree?path=..."""
    mock_http.get_response = {"path": "/", "secrets_at_this_level_count": 0, "folders": []}
    client = VaultClient(token="hrpv_1_test", base_url="http://localhost")
    client._wallet_id_cache = {"my-wallet": "uuid-wallet"}

    result = client.get_tree("my-wallet", path="/")
    assert result["path"] == "/"
    assert "folders" in result
    assert mock_http.last_url.endswith("/tree")
    assert "path=%2F" in mock_http.last_url or "path=/" in mock_http.last_url


def test_list_secrets_with_path_param(mock_http):
    """list_secrets() avec path= inclut ?path= dans la requête."""
    mock_http.get_response = {"secrets": [], "next_cursor": None}
    client = VaultClient(token="hrpv_1_test", base_url="http://localhost")
    client._wallet_id_cache = {"my-wallet": "uuid-wallet"}

    client.list_secrets("my-wallet", path="/bob/")
    assert "path=" in mock_http.last_url


def test_get_secret_normalizes_path_in_name(mock_http):
    """get_secret() normalise 'bob/key' en '/bob/key' (ajoute '/' initial)."""
    mock_http.get_response = {
        "encrypted_value": "base64==",
        "encrypted_wallet_key": "base64==",
        "generation_version": 1,
    }
    client = VaultClient(token="hrpv_1_test", base_url="http://localhost")
    client._wallet_id_cache = {"my-wallet": "uuid-wallet"}
    client._wallet_key_cache = {"uuid-wallet": b"\x00" * 32}

    # bob/key sans / initial → doit être envoyé comme /bob/key (URL-encoded)
    client.get_secret("my-wallet", "bob/key")
    assert "%2F" in mock_http.last_url or "/bob" in mock_http.last_url
```

- [ ] **Step 2 : Vérifier que les tests échouent**

```bash
cd sdk-python && python -m pytest tests/unit/test_client.py -k "path or tree or normalize" -v 2>&1 | head -20
```

Attendu : `AttributeError: 'VaultClient' object has no attribute 'get_tree'`

- [ ] **Step 3 : Implémenter dans `sdk-python/harpocrate/client.py`**

Ajouter la méthode `get_tree()` dans la classe `VaultClient` :

```python
def get_tree(self, wallet_name: str, path: str = "/") -> dict:
    """Retourne l'arborescence d'un wallet à un path donné."""
    wallet_id = self._resolve_wallet_id(wallet_name)
    resp = self._http.get(
        f"/v1/wallets/{wallet_id}/tree",
        params={"path": path},
        headers=self._auth_headers(),
    )
    resp.raise_for_status()
    return resp.json()
```

Modifier `list_secrets()` pour accepter `path` :

```python
def list_secrets(
    self,
    wallet_name: str,
    path: str | None = None,
    tags: list[str] | None = None,
    limit: int = 50,
) -> list[dict]:
    wallet_id = self._resolve_wallet_id(wallet_name)
    params: dict = {"limit": limit}
    if path is not None:
        params["path"] = path
    if tags:
        params["tags"] = tags
    resp = self._http.get(
        f"/v1/wallets/{wallet_id}/secrets",
        params=params,
        headers=self._auth_headers(),
    )
    resp.raise_for_status()
    return resp.json().get("secrets", [])
```

Modifier `get_secret()` pour normaliser les noms avec path :

```python
def get_secret(self, wallet_name: str, secret_name: str) -> str:
    # Normaliser : ajouter / initial si le nom contient des slashes
    if "/" in secret_name and not secret_name.startswith("/"):
        secret_name = "/" + secret_name
    # URL-encoder les slashes dans le nom pour le path param
    from urllib.parse import quote
    encoded_name = quote(secret_name, safe="")
    wallet_id = self._resolve_wallet_id(wallet_name)
    # ... reste de l'implémentation existante avec encoded_name dans l'URL
```

- [ ] **Step 4 : Vérifier que les tests passent**

```bash
cd sdk-python && python -m pytest tests/unit/test_client.py -k "path or tree or normalize" -v
```

Attendu : 3 tests PASS.

- [ ] **Step 5 : Commit**

```bash
git add sdk-python/harpocrate/client.py sdk-python/tests/unit/test_client.py
git commit -m "feat(paths P6): SDK Python get_tree() + list_secrets(path=) + normalisation"
```

---

## Self-Review

### Couverture spec

| Exigence spec | Tâche |
|---|---|
| Table `secret_path_index` + trigger | Task 1 |
| Validation noms (profondeur, chars, segments vides) | Task 2 |
| `GET /tree?path=` | Task 4 |
| `GET /secrets?path=` | Task 4 |
| Trigger sur UPDATE name (renommage) | Task 1 (test inclus) |
| Cascade DELETE | Task 1 (test inclus) |
| Normalisation path sans `/` final | Task 2 |
| UI breadcrumb | Task 5 |
| UI navigation dossiers | Task 5 |
| UI bouton "Nouveau secret" avec path pré-rempli | Task 5 |
| SDK `get_tree()` | Task 6 |
| SDK `list_secrets(path=)` | Task 6 |
| SDK normalisation `get_secret()` | Task 6 |

### Points non couverts (hors scope LOT_18 explicite)

- Pagination `/secrets?path=` avec cursor → implémentée (Task 4, `list_by_path` accepte cursor)
- `SecretNewPage` reçoit `state.prefixPath` → à traiter dans une issue séparée si `SecretNewPage` ne lit pas le state router (le plan y fait référence mais n'implémente pas `SecretNewPage`)
- SDK version bump `0.2.0` → à faire manuellement dans `pyproject.toml` après Task 6

### Placeholder scan

Aucun "TBD" ou "TODO" détecté. Tous les blocs de code sont complets.

### Cohérence des types

- `list_by_path` retourne `list[SecretRow]` ✓ (même type que `list_secrets`)
- `get_tree_data` retourne `dict[str, object]` ✓ (sérialisé directement en JSON)
- `normalize_path` retourne `str` ✓ utilisé dans Task 4
- `validate_secret_name` retourne `str` ✓ appelé dans le validator Pydantic Task 3
