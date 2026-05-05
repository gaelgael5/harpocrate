# P3 — SDK Python : migration by-id + accès au catalogue de types

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Faire fonctionner le SDK Python pour TOUS les noms de secrets (y compris ceux contenant des `/`) en routant les opérations unitaires via les nouvelles routes by-id du backend (P1 + P3.5). Exposer un nouveau sous-client `client.types` qui consomme `/v1/secret-types` (accès API key débloqué en P1.5). Permettre à `create()` et `create_placeholder()` d'accepter un `type_uuid` optionnel.

**Architecture:** L'API publique du SDK reste rétro-compatible : `client.secrets.get(name)` continue de marcher pour les noms simples (route name-based directe) ET pour les noms à `/` (résolution interne du nom → UUID via `GET /secrets?path=...`, puis appel `/by-id/{sid}`). Pour les opérations sans changement requis (`get` simple), une seule requête HTTP. Pour les noms à path, deux requêtes (lookup + opération). Les nouvelles méthodes `client.types.list()` et `client.types.get(uuid)` sont des wrappers fins sur `/v1/secret-types[/{uuid}]`.

**Tech Stack:** Python 3.12 + httpx synchrone + Pydantic-free (modèles dataclass dans `harpocrate/models/`) + pytest avec mocks `httpx`.

---

## File Structure

| Fichier | Modification |
|---|---|
| `sdk-python/harpocrate/client.py` | `SecretsClient` : ajout `_resolve_id_if_pathstyle` + `_path_for_op`. Modif `get/put/patch/delete/get_descriptor/populate` pour utiliser `_path_for_op`. Modif `create` + `create_placeholder` pour accepter `type_uuid` optionnel. Ajout classe `TypesClient`. `VaultClient` : ajout `self.types = TypesClient(...)` |
| `sdk-python/harpocrate/models/__init__.py` | Ajout `SecretType`, `SchemaVersion` |
| `sdk-python/harpocrate/models/secret_type.py` *(nouveau)* | Dataclass `SecretType` + `SchemaVersion` |
| `sdk-python/tests/unit/test_pathstyle_lookup.py` *(nouveau)* | Tests : noms à `/` routés via lookup → by-id |
| `sdk-python/tests/unit/test_types_client.py` *(nouveau)* | Tests : `client.types.list()` et `.get(uuid)` |
| `sdk-python/tests/unit/test_create_with_type.py` *(nouveau)* | Tests : `create(name, value, type_uuid=...)` envoie bien `type_uuid` dans le body |

---

## Task 1: Modèles dataclass `SecretType` et `SchemaVersion`

**Files:**
- Create: `sdk-python/harpocrate/models/secret_type.py`
- Modify: `sdk-python/harpocrate/models/__init__.py`

- [ ] **Step 1.1: Créer le module `secret_type.py`**

Créer `sdk-python/harpocrate/models/secret_type.py` :

```python
"""Modèles SDK pour le catalogue de types de secrets."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class SchemaVersion:
    """Version d'un schéma de type de secret."""

    version_uuid: UUID
    version: int
    schema_data: dict[str, Any]
    schema_ui: dict[str, Any]
    created_at: str | None = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> SchemaVersion:
        return SchemaVersion(
            version_uuid=UUID(d["version_uuid"]),
            version=int(d["version"]),
            schema_data=dict(d.get("schema_data") or {}),
            schema_ui=dict(d.get("schema_ui") or {}),
            created_at=d.get("created_at"),
        )


@dataclass(frozen=True)
class SecretType:
    """Type de secret (avec sa version courante)."""

    type_uuid: UUID
    type: str
    sous_type: str
    label: str | None
    description: str | None
    is_system: bool
    deprecated_at: str | None
    current_version: SchemaVersion | None
    used_by_secrets_count: int = 0
    all_versions: list[SchemaVersion] = field(default_factory=list)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> SecretType:
        cv_full = d.get("current_version_full")
        cv = SchemaVersion.from_dict(cv_full) if cv_full else None
        # Le list endpoint renvoie une forme courte 'current_version' ;
        # le detail endpoint renvoie 'current_version_full' avec les schémas.
        if cv is None and d.get("current_version"):
            short = d["current_version"]
            cv = SchemaVersion(
                version_uuid=UUID(short["version_uuid"]),
                version=int(short["version"]),
                schema_data={},
                schema_ui={},
                created_at=short.get("created_at"),
            )
        all_versions = [SchemaVersion.from_dict(v) for v in d.get("all_versions", [])]
        return SecretType(
            type_uuid=UUID(d["type_uuid"]),
            type=str(d["type"]),
            sous_type=str(d["sous_type"]),
            label=d.get("label"),
            description=d.get("description"),
            is_system=bool(d.get("is_system", False)),
            deprecated_at=d.get("deprecated_at"),
            current_version=cv,
            used_by_secrets_count=int(d.get("used_by_secrets_count", 0)),
            all_versions=all_versions,
        )
```

- [ ] **Step 1.2: Exporter dans le package `models`**

Dans `sdk-python/harpocrate/models/__init__.py`, ajouter :

```python
from harpocrate.models.secret_type import SchemaVersion, SecretType
```

- [ ] **Step 1.3: Vérifier l'import**

```bash
cd /e/srcs/harpocrate/sdk-python && uv run python -c "from harpocrate.models import SecretType, SchemaVersion; print('OK')"
```
Expected : `OK`. Si `uv` n'est pas configuré pour le SDK, utiliser `python -c` directement après avoir activé l'env Python du projet.

Pas de commit isolé — on commit avec T2.

---

## Task 2: `TypesClient` + intégration dans `VaultClient`

**Files:**
- Modify: `sdk-python/harpocrate/client.py` (ajout d'une classe + accessor)
- Test: `sdk-python/tests/unit/test_types_client.py` (nouveau)

- [ ] **Step 2.1: Écrire les tests rouges**

Créer `sdk-python/tests/unit/test_types_client.py` :

```python
"""Tests P3 — TypesClient : accès au catalogue /v1/secret-types via API key."""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest

from harpocrate.client import TypesClient
from harpocrate.http import VaultHttpClient
from harpocrate.models import SecretType


def _mock_http_with_responses(responses: dict[str, Any]) -> MagicMock:
    mock_http = MagicMock(spec=VaultHttpClient)

    def fake_get(path: str, **kwargs: Any) -> Any:
        if path in responses:
            return responses[path]
        raise AssertionError(f"unexpected path {path}")

    mock_http.get.side_effect = fake_get
    return mock_http


def test_types_list_returns_list_of_secret_type() -> None:
    """`client.types.list()` retourne une liste de SecretType."""
    type_uuid = uuid.UUID("eeeeeeee-0000-0000-0000-000000000001")
    version_uuid = uuid.UUID("ffffffff-0000-0000-0000-000000000001")
    http = _mock_http_with_responses({
        "/v1/secret-types": {
            "types": [
                {
                    "type_uuid": str(type_uuid),
                    "type": "raw",
                    "sous_type": "raw",
                    "label": "Raw",
                    "description": None,
                    "is_system": True,
                    "deprecated_at": None,
                    "current_version": {
                        "version_uuid": str(version_uuid),
                        "version": 1,
                        "created_at": "2026-01-01T00:00:00",
                    },
                    "used_by_secrets_count": 5,
                },
            ],
        },
    })

    client = TypesClient(http=http)
    types = client.list()

    assert len(types) == 1
    assert isinstance(types[0], SecretType)
    assert types[0].type_uuid == type_uuid
    assert types[0].type == "raw"
    assert types[0].sous_type == "raw"
    assert types[0].is_system is True
    assert types[0].used_by_secrets_count == 5
    assert types[0].current_version is not None
    assert types[0].current_version.version_uuid == version_uuid


def test_types_get_returns_full_type_with_schemas() -> None:
    """`client.types.get(uuid)` retourne le SecretType avec schema_data + schema_ui complets."""
    type_uuid = uuid.UUID("eeeeeeee-0000-0000-0000-000000000001")
    version_uuid = uuid.UUID("ffffffff-0000-0000-0000-000000000001")
    http = _mock_http_with_responses({
        f"/v1/secret-types/{type_uuid}": {
            "type_uuid": str(type_uuid),
            "type": "raw",
            "sous_type": "raw",
            "label": "Raw",
            "description": None,
            "is_system": True,
            "deprecated_at": None,
            "current_version": {
                "version_uuid": str(version_uuid),
                "version": 1,
                "created_at": "2026-01-01T00:00:00",
            },
            "current_version_full": {
                "version_uuid": str(version_uuid),
                "version": 1,
                "schema_data": {"type": "object", "properties": {"value": {"type": "string"}}},
                "schema_ui": {"value": {"widget": "password"}},
                "created_at": "2026-01-01T00:00:00",
            },
            "all_versions": [
                {
                    "version_uuid": str(version_uuid),
                    "parent_uuid": str(type_uuid),
                    "version": 1,
                    "schema_data": {"type": "object"},
                    "schema_ui": {},
                    "notes": None,
                    "created_at": "2026-01-01T00:00:00",
                },
            ],
            "used_by_secrets_count": 5,
        },
    })

    client = TypesClient(http=http)
    secret_type = client.get(type_uuid)

    assert secret_type.type_uuid == type_uuid
    assert secret_type.current_version is not None
    assert secret_type.current_version.schema_data == {
        "type": "object",
        "properties": {"value": {"type": "string"}},
    }
    assert secret_type.current_version.schema_ui == {"value": {"widget": "password"}}
    assert len(secret_type.all_versions) == 1


def test_types_list_with_query_passes_q_param() -> None:
    """`client.types.list(q='password')` passe q en query string."""
    http = MagicMock(spec=VaultHttpClient)
    http.get.return_value = {"types": []}
    client = TypesClient(http=http)
    client.list(q="password")
    http.get.assert_called_once_with("/v1/secret-types", q="password")
```

- [ ] **Step 2.2: Lancer les tests → DOIVENT échouer**

```bash
cd /e/srcs/harpocrate/sdk-python && uv run pytest tests/unit/test_types_client.py -v 2>&1 | tail -10
```
Expected : `ImportError` parce que `TypesClient` n'existe pas.

- [ ] **Step 2.3: Ajouter `TypesClient` dans `client.py`**

Dans `sdk-python/harpocrate/client.py`, **avant** la classe `VaultClient` (vers ligne 308), ajouter :

```python
class TypesClient:
    """Sous-client pour le catalogue de types de secrets (lecture seule).

    Utilise les endpoints publics /v1/secret-types accessibles via API key
    depuis P1.5 (ou via JWT user).
    """

    def __init__(self, http: VaultHttpClient) -> None:
        self._http = http

    def list(self, q: str | None = None, include_deprecated: bool = False) -> list["SecretType"]:
        """Liste les types de secrets disponibles.

        Paramètres :
            q : filtre fulltext (type, sous_type, label)
            include_deprecated : inclure les types dépréciés

        Retourne : list[SecretType]
        """
        from harpocrate.models import SecretType

        params: dict[str, Any] = {}
        if q is not None:
            params["q"] = q
        if include_deprecated:
            params["include_deprecated"] = include_deprecated

        data = self._http.get("/v1/secret-types", **params)
        return [SecretType.from_dict(t) for t in data.get("types", [])]

    def get(self, type_uuid: UUID) -> "SecretType":
        """Retourne le détail d'un type avec son schéma complet (data + UI) et toutes les versions."""
        from harpocrate.models import SecretType

        data = self._http.get(f"/v1/secret-types/{type_uuid}")
        return SecretType.from_dict(data)
```

(L'import `from harpocrate.models import SecretType` est mis dans les méthodes pour éviter un cycle si `models` finit par importer `client`.)

- [ ] **Step 2.4: Brancher `TypesClient` sur `VaultClient`**

Dans `sdk-python/harpocrate/client.py`, dans `VaultClient.__init__` (vers ligne 343, juste après `self.secrets = SecretsClient(...)`), ajouter :

```python
        self.types = TypesClient(http=self._http)
```

- [ ] **Step 2.5: Tests verts**

```bash
cd /e/srcs/harpocrate/sdk-python && uv run pytest tests/unit/test_types_client.py -v 2>&1 | tail -10
```
Expected : 3 PASS.

- [ ] **Step 2.6: Commit**

```bash
git add sdk-python/harpocrate/models/secret_type.py sdk-python/harpocrate/models/__init__.py sdk-python/harpocrate/client.py sdk-python/tests/unit/test_types_client.py
git commit -m "feat(sdk): TypesClient pour /v1/secret-types accessible via API key"
```

---

## Task 3: `_resolve_id_if_pathstyle` + `_path_for_op` dans `SecretsClient`

**Files:**
- Modify: `sdk-python/harpocrate/client.py` (`SecretsClient`)
- Test: `sdk-python/tests/unit/test_pathstyle_lookup.py` (nouveau)

- [ ] **Step 3.1: Écrire les tests rouges**

Créer `sdk-python/tests/unit/test_pathstyle_lookup.py` :

```python
"""Tests P3 — SecretsClient route les opérations unitaires sur des noms à '/'
via le lookup interne (list par path) puis via les routes /by-id/{sid}.
"""
from __future__ import annotations

import base64
import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest

from harpocrate.cache import WalletKeyCache
from harpocrate.client import SecretsClient
from harpocrate.http import VaultHttpClient
from harpocrate.token import parse_token

_TEST_DKEY_BYTES = bytes(range(32))
_TEST_DKEY_B64 = base64.urlsafe_b64encode(_TEST_DKEY_BYTES).rstrip(b"=").decode()
_TEST_API_KEY_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
_TEST_WALLET_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
_TEST_AUTH_SECRET = "A" * 43
_TEST_HMAC = "B" * 22


def _uuid_to_b32(uid: uuid.UUID) -> str:
    return base64.b32encode(uid.bytes).decode().lower().rstrip("=")


_TEST_TOKEN = (
    f"hrpv_1_{_uuid_to_b32(_TEST_API_KEY_ID)}_0_3f_{_TEST_AUTH_SECRET}_{_TEST_DKEY_B64}_{_TEST_HMAC}"
)


def _make_secrets_client(responses: dict[str, Any]) -> tuple[SecretsClient, MagicMock]:
    http = MagicMock(spec=VaultHttpClient)

    def fake_get(path: str, **kwargs: Any) -> Any:
        if path in responses:
            return responses[path]
        raise AssertionError(f"unexpected GET {path}")

    def fake_delete(path: str) -> None:
        if path not in responses.get("__delete_paths__", []):
            raise AssertionError(f"unexpected DELETE {path}")

    http.get.side_effect = fake_get
    http.delete.side_effect = fake_delete

    parsed = parse_token(_TEST_TOKEN)
    cache = WalletKeyCache(ttl_seconds=600)
    sc = SecretsClient(
        http=http,
        wallet_id=_TEST_WALLET_ID,
        parsed_token=parsed,
        cache=cache,
    )
    return sc, http


def test_simple_name_uses_name_based_route_directly() -> None:
    """Un nom sans '/' est appelé directement via la route name-based (1 requête, pas de lookup)."""
    secret_id = uuid.UUID("dddddddd-0000-0000-0000-000000000001")
    responses = {
        f"/v1/wallets/{_TEST_WALLET_ID}/secrets/MY_KEY": {
            "id": str(secret_id),
            "name": "MY_KEY",
            "encrypted_value": base64.b64encode(b"x").decode(),
            "encrypted_wallet_key": base64.b64encode(b"y").decode(),
            "is_placeholder": False,
            "generation_version": 1,
            "tags": [],
        },
        "__delete_paths__": [f"/v1/wallets/{_TEST_WALLET_ID}/secrets/MY_KEY"],
    }
    sc, http = _make_secrets_client(responses)

    sc.delete("MY_KEY")
    # Vérifie qu'aucun appel à /secrets?path= n'a été fait (donc pas de lookup pour les noms simples)
    list_calls = [c for c in http.get.call_args_list if c.args[0].endswith("/secrets") and "path" in c.kwargs]
    assert list_calls == []


def test_pathstyle_name_resolves_id_then_calls_by_id_for_delete() -> None:
    """Un nom à '/' déclenche un lookup (list par path) puis appelle /by-id/{sid}."""
    secret_id = uuid.UUID("dddddddd-0000-0000-0000-000000000099")
    name = "/users/no_email/api-1"
    parent_path = "/users/no_email/"

    responses = {
        f"/v1/wallets/{_TEST_WALLET_ID}/secrets": {
            "secrets": [
                {
                    "id": str(secret_id),
                    "name": name,
                    "is_placeholder": False,
                    "generation_version": 1,
                    "tags": [],
                    "description": None,
                    "created_at": "2026-01-01",
                    "updated_at": "2026-01-01",
                },
            ],
            "next_cursor": None,
        },
        "__delete_paths__": [f"/v1/wallets/{_TEST_WALLET_ID}/secrets/by-id/{secret_id}"],
    }
    sc, http = _make_secrets_client(responses)

    sc.delete(name)

    # Vérifie qu'on a fait un GET /secrets?path=/users/no_email/ pour résoudre l'ID
    list_calls = [c for c in http.get.call_args_list if c.kwargs.get("path") == parent_path]
    assert len(list_calls) == 1, f"attendu 1 appel list, eu {len(list_calls)}"

    # Vérifie qu'on a fait un DELETE /secrets/by-id/{secret_id}
    delete_calls = [c for c in http.delete.call_args_list]
    assert len(delete_calls) == 1
    assert delete_calls[0].args[0] == f"/v1/wallets/{_TEST_WALLET_ID}/secrets/by-id/{secret_id}"
```

- [ ] **Step 3.2: Lancer les tests → DOIVENT échouer**

```bash
cd /e/srcs/harpocrate/sdk-python && uv run pytest tests/unit/test_pathstyle_lookup.py -v 2>&1 | tail -10
```
Expected : 2 FAIL — le 1er parce que le test n'a pas encore le bon comportement à vérifier (ou peut passer si le SDK actuel fait déjà 1 seul appel pour les noms simples — vérifier), le 2e fail car `delete("/users/no_email/api-1")` appelle `/secrets/%2Fusers%2Fno_email%2Fapi-1` (l'ancien comportement).

- [ ] **Step 3.3: Ajouter `_resolve_id_if_pathstyle` et `_path_for_op` dans `SecretsClient`**

Dans `sdk-python/harpocrate/client.py`, dans la classe `SecretsClient`, ajouter les méthodes (après `_path` vers ligne 84) :

```python
    def _resolve_id_if_pathstyle(self, name: str) -> str | None:
        """Résout l'UUID d'un secret si son nom contient un '/' (path-style).

        Pour les noms sans '/', retourne None — l'appelant utilisera la route name-based.
        Pour les noms à '/', liste les secrets au path parent et trouve l'entrée matching.
        Lève SecretNotFound si aucun secret ne correspond.
        """
        from harpocrate.exceptions import SecretNotFound

        if "/" not in name:
            return None

        normalized = self._normalize_name(name)
        # Path parent : tout sauf le dernier segment, avec '/' final garanti
        parent_path = normalized.rsplit("/", 1)[0] + "/"
        # Cas spécial : nom à un seul segment après le '/' initial → parent = '/'
        if parent_path == "/" and not normalized.startswith("//"):
            pass  # parent_path déjà '/'

        data = self._http.get(
            f"/v1/wallets/{self._wallet_id}/secrets",
            path=parent_path,
        )
        for s in data.get("secrets", []):
            if s.get("name") == normalized:
                return str(s["id"])

        raise SecretNotFound(f"Secret '{name}' not found in wallet")

    def _path_for_op(self, name: str) -> str:
        """URL d'opération unitaire — by-id si nom path-style, by-name sinon."""
        sid = self._resolve_id_if_pathstyle(name)
        if sid is not None:
            return f"/v1/wallets/{self._wallet_id}/secrets/by-id/{sid}"
        return self._path(name)
```

- [ ] **Step 3.4: Modifier `delete` pour utiliser `_path_for_op`**

Ligne 170-172 dans `client.py`, remplacer :
```python
def delete(self, name: str) -> None:
    """Supprime un secret. Requiert [remove]."""
    self._http.delete(self._path(name))
```
par :
```python
def delete(self, name: str) -> None:
    """Supprime un secret (résout l'ID si le nom est path-style). Requiert [remove]."""
    self._http.delete(self._path_for_op(name))
```

- [ ] **Step 3.5: Tests verts pour delete**

```bash
cd /e/srcs/harpocrate/sdk-python && uv run pytest tests/unit/test_pathstyle_lookup.py -v 2>&1 | tail -10
```
Expected : 2 PASS.

Pas de commit isolé — on commit avec T4.

---

## Task 4: Migrer `get`, `put`, `patch`, `get_descriptor`, `populate` vers `_path_for_op`

**Files:** Modify `sdk-python/harpocrate/client.py`.

- [ ] **Step 4.1: Migrer chaque méthode**

Dans `sdk-python/harpocrate/client.py`, remplacer **chaque** occurrence de `self._path(name)` dans les méthodes suivantes par `self._path_for_op(name)` :

- `put` (ligne ~150) : `self._http.put(self._path(name), json=...)` → `self._http.put(self._path_for_op(name), json=...)`
- `patch` (ligne ~168) : `self._http.patch(self._path(name), json=body)` → `self._http.patch(self._path_for_op(name), json=body)`
- `get` (ligne ~202) : `data = self._http.get(self._path(name))` → `data = self._http.get(self._path_for_op(name))`
- `get_descriptor` (ligne ~237) : `f"{self._path(name)}/descriptor"` → `f"{self._path_for_op(name)}/descriptor"`
- `populate` : la fonction utilise probablement `f"{self._path(name)}/populate"` quelque part — remplacer par `f"{self._path_for_op(name)}/populate"`

NE PAS toucher `_path` lui-même (il sert à `create`, `list_secrets`, et reste utilisable pour les noms simples).

- [ ] **Step 4.2: Ajouter test couvrant get + put pour les noms path-style**

À la fin de `sdk-python/tests/unit/test_pathstyle_lookup.py`, ajouter :

```python
def test_pathstyle_name_resolves_id_then_calls_by_id_for_get() -> None:
    """get(name) avec un nom à '/' fait lookup puis appelle /by-id/{sid}."""
    secret_id = uuid.UUID("dddddddd-0000-0000-0000-000000000099")
    name = "/users/no_email/api-1"
    parent_path = "/users/no_email/"

    # Encoded value : utilisons la wallet_key déchiffrable pour faire passer la décryption
    # (simplification : on vérifie juste l'URL appelée, pas le déchiffrement complet)
    responses = {
        f"/v1/wallets/{_TEST_WALLET_ID}/secrets": {
            "secrets": [
                {
                    "id": str(secret_id), "name": name, "is_placeholder": False,
                    "generation_version": 1, "tags": [], "description": None,
                    "created_at": "2026-01-01", "updated_at": "2026-01-01",
                },
            ],
            "next_cursor": None,
        },
        f"/v1/wallets/{_TEST_WALLET_ID}/secrets/by-id/{secret_id}": {
            "id": str(secret_id), "name": name,
            "encrypted_value": base64.b64encode(b"x").decode(),
            "encrypted_wallet_key": base64.b64encode(b"y").decode(),
            "is_placeholder": False, "generation_version": 1, "tags": [],
        },
    }
    sc, http = _make_secrets_client(responses)

    # On ne déchiffre pas (nécessite mock crypto), on vérifie juste l'URL
    try:
        sc.get(name)
    except Exception:
        pass  # déchiffrement échouera, c'est OK — on vérifie les appels HTTP

    # Vérifie : 1 list (lookup) + 1 GET by-id
    list_calls = [c for c in http.get.call_args_list if c.kwargs.get("path") == parent_path]
    assert len(list_calls) == 1
    by_id_calls = [c for c in http.get.call_args_list if "by-id" in c.args[0]]
    assert len(by_id_calls) == 1
    assert by_id_calls[0].args[0] == f"/v1/wallets/{_TEST_WALLET_ID}/secrets/by-id/{secret_id}"
```

- [ ] **Step 4.3: Lancer tous les tests SDK**

```bash
cd /e/srcs/harpocrate/sdk-python && uv run pytest tests/unit/ -v 2>&1 | tail -25
```
Expected : tous les tests SDK PASS (les anciens + les nouveaux).

- [ ] **Step 4.4: Commit**

```bash
git add sdk-python/harpocrate/client.py sdk-python/tests/unit/test_pathstyle_lookup.py
git commit -m "feat(sdk): SecretsClient résout les noms path-style via lookup + by-id"
```

---

## Task 5: `create()` et `create_placeholder()` acceptent `type_uuid`

**Files:**
- Modify: `sdk-python/harpocrate/client.py`
- Test: `sdk-python/tests/unit/test_create_with_type.py` (nouveau)

- [ ] **Step 5.1: Écrire les tests rouges**

Créer `sdk-python/tests/unit/test_create_with_type.py` :

```python
"""Tests P3 — create() et create_placeholder() acceptent un type_uuid optionnel."""
from __future__ import annotations

import base64
import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest

from harpocrate.cache import WalletKeyCache
from harpocrate.client import SecretsClient
from harpocrate.http import VaultHttpClient
from harpocrate.token import parse_token


_TEST_DKEY_BYTES = bytes(range(32))
_TEST_DKEY_B64 = base64.urlsafe_b64encode(_TEST_DKEY_BYTES).rstrip(b"=").decode()
_TEST_API_KEY_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
_TEST_WALLET_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
_TEST_AUTH_SECRET = "A" * 43
_TEST_HMAC = "B" * 22


def _uuid_to_b32(uid: uuid.UUID) -> str:
    return base64.b32encode(uid.bytes).decode().lower().rstrip("=")


_TEST_TOKEN = (
    f"hrpv_1_{_uuid_to_b32(_TEST_API_KEY_ID)}_0_3f_{_TEST_AUTH_SECRET}_{_TEST_DKEY_B64}_{_TEST_HMAC}"
)


def _make_sc() -> tuple[SecretsClient, MagicMock]:
    http = MagicMock(spec=VaultHttpClient)
    parsed = parse_token(_TEST_TOKEN)
    cache = WalletKeyCache(ttl_seconds=600)
    # Pré-cache la wallet_key pour éviter le wallet_key fetch
    cache.set(str(_TEST_WALLET_ID), _TEST_DKEY_BYTES)
    sc = SecretsClient(
        http=http,
        wallet_id=_TEST_WALLET_ID,
        parsed_token=parsed,
        cache=cache,
    )
    return sc, http


def test_create_without_type_uuid_omits_field_in_body() -> None:
    """create(name, value) sans type_uuid → body n'a pas la clé."""
    sc, http = _make_sc()
    http.post.return_value = {"secret_id": str(uuid.uuid4())}

    sc.create("MY_KEY", "secret_value")

    call = http.post.call_args
    body = call.kwargs.get("json") or call.args[1]
    assert "type_uuid" not in body
    assert "schema_version_uuid" not in body


def test_create_with_type_uuid_includes_field() -> None:
    """create(name, value, type_uuid=X) → body contient type_uuid=X."""
    sc, http = _make_sc()
    http.post.return_value = {"secret_id": str(uuid.uuid4())}

    type_uuid = uuid.UUID("eeeeeeee-0000-0000-0000-000000000001")
    schema_version_uuid = uuid.UUID("ffffffff-0000-0000-0000-000000000001")

    sc.create("MY_KEY", "secret_value", type_uuid=type_uuid, schema_version_uuid=schema_version_uuid)

    call = http.post.call_args
    body = call.kwargs.get("json") or call.args[1]
    assert body["type_uuid"] == str(type_uuid)
    assert body["schema_version_uuid"] == str(schema_version_uuid)


def test_create_placeholder_with_type_uuid_includes_field() -> None:
    """create_placeholder(...) avec type_uuid → body contient type_uuid."""
    sc, http = _make_sc()
    http.post.return_value = {"secret_id": str(uuid.uuid4())}

    type_uuid = uuid.UUID("eeeeeeee-0000-0000-0000-000000000001")
    sc.create_placeholder(
        "MY_KEY",
        descriptor={"type": "random", "length": 32, "encoding": "base64"},
        type_uuid=type_uuid,
    )

    call = http.post.call_args
    body = call.kwargs.get("json") or call.args[1]
    assert body["type_uuid"] == str(type_uuid)
```

- [ ] **Step 5.2: Lancer les tests → DOIVENT échouer**

```bash
cd /e/srcs/harpocrate/sdk-python && uv run pytest tests/unit/test_create_with_type.py -v 2>&1 | tail -10
```

- [ ] **Step 5.3: Modifier `create` et `create_placeholder` pour accepter `type_uuid`**

Dans `sdk-python/harpocrate/client.py`, fonction `create` (vers ligne 120), modifier la signature et le corps :

```python
def create(
    self,
    name: str,
    value: str,
    description: str | None = None,
    tags: list[str] | None = None,
    type_uuid: UUID | None = None,
    schema_version_uuid: UUID | None = None,
) -> str:
    """Crée un secret avec une valeur chiffrée côté client.

    Si `type_uuid` n'est pas fourni, le serveur attache automatiquement le type RAW.
    Retourne le secret_id (UUID string). Requiert [add].
    """
    wallet_key = self._wallet_key()
    enc_value = aes_gcm_encrypt(value.encode("utf-8"), wallet_key)
    enc_value_b64 = base64.b64encode(enc_value).decode()
    body: dict[str, Any] = {"name": name, "encrypted_value": enc_value_b64}
    if description is not None:
        body["description"] = description
    if tags is not None:
        body["tags"] = tags
    if type_uuid is not None:
        body["type_uuid"] = str(type_uuid)
    if schema_version_uuid is not None:
        body["schema_version_uuid"] = str(schema_version_uuid)
    result = self._http.post(self._path(), json=body)
    return str(result["secret_id"])
```

Et `create_placeholder` (vers ligne 174) :

```python
def create_placeholder(
    self,
    name: str,
    descriptor: dict[str, Any],
    description: str | None = None,
    tags: list[str] | None = None,
    type_uuid: UUID | None = None,
    schema_version_uuid: UUID | None = None,
) -> str:
    """Crée un placeholder avec son descripteur de génération.

    Si `type_uuid` n'est pas fourni, le serveur attache automatiquement le type RAW.
    Retourne le secret_id. Requiert [add].
    """
    body: dict[str, Any] = {"name": name, "generation_descriptor": descriptor}
    if description is not None:
        body["description"] = description
    if tags is not None:
        body["tags"] = tags
    if type_uuid is not None:
        body["type_uuid"] = str(type_uuid)
    if schema_version_uuid is not None:
        body["schema_version_uuid"] = str(schema_version_uuid)
    result = self._http.post(
        f"/v1/wallets/{self._wallet_id}/secrets/placeholder", json=body
    )
    return str(result["secret_id"])
```

- [ ] **Step 5.4: Tests verts**

```bash
cd /e/srcs/harpocrate/sdk-python && uv run pytest tests/unit/test_create_with_type.py -v 2>&1 | tail -10
```
Expected : 3 PASS.

- [ ] **Step 5.5: Commit**

```bash
git add sdk-python/harpocrate/client.py sdk-python/tests/unit/test_create_with_type.py
git commit -m "feat(sdk): create() et create_placeholder() acceptent type_uuid optionnel"
```

---

## Task 6: Vérification finale P3

- [ ] **Step 6.1: Suite SDK complète**

```bash
cd /e/srcs/harpocrate/sdk-python && uv run pytest tests/unit/ -v 2>&1 | tail -30
```
Expected : tous les tests PASS.

- [ ] **Step 6.2: Lint + format si dispo**

```bash
cd /e/srcs/harpocrate/sdk-python && uv run ruff check harpocrate/ tests/ 2>&1 | tail -10
```
Si erreurs : appliquer `uv run ruff check --fix` ou `uv run ruff format`.

- [ ] **Step 6.3: Smoke import du package**

```bash
cd /e/srcs/harpocrate/sdk-python && uv run python -c "
from harpocrate import VaultClient
from harpocrate.models import SecretType, SchemaVersion
from harpocrate.client import TypesClient
print('OK')
"
```
Expected : `OK`.

- [ ] **Step 6.4: Commit final si reformat**

```bash
git status && (git diff --quiet || (git add -u && git commit -m "chore: ruff format après P3"))
```

---

## Acceptance criteria P3

- ✅ `client.types.list()` retourne une liste de `SecretType`
- ✅ `client.types.get(uuid)` retourne un `SecretType` avec `current_version.schema_data` et `schema_ui` complets
- ✅ `client.secrets.delete("MY_KEY")` (nom simple) → 1 seul HTTP call (route name-based)
- ✅ `client.secrets.delete("/users/foo/key")` (nom path-style) → 2 HTTP calls (lookup list par path + DELETE by-id)
- ✅ Pareil pour `get`, `put`, `patch`, `get_descriptor`, `populate`
- ✅ `client.secrets.create("name", "value", type_uuid=X)` envoie `type_uuid: X` dans le body
- ✅ `client.secrets.create("name", "value")` (sans type_uuid) → backend défaute RAW (cf. P1.5)
- ✅ Tous les tests SDK PASS (anciens + nouveaux)

## Hors scope P3

- CLI `harpocrate-gen` : n'a pas besoin de migration tant qu'il utilise des noms simples ; reporter à un futur lot si besoin.
- E2E SDK contre une vraie instance backend : reporter au déploiement P4.
