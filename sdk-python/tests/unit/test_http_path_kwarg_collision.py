"""Régression — bug `TypeError: VaultHttpClient.get() got multiple values for argument 'path'`.

Avant le fix : `VaultHttpClient.get(self, path: str, **params)` avait pour 1er
positionnel un paramètre nommé `path`. Quand `client.py` voulait passer un
query param nommé `path` (pour filtrer par dossier dans `/v1/wallets/.../secrets`,
`/v1/wallets/.../tree`, etc.), Python levait TypeError car le kwarg `path=...`
entrait en collision avec le positionnel.

Le fix renomme le 1er positionnel `path` → `url` dans les 5 méthodes publiques
(`get/post/put/patch/delete`) et dans `_request`. Le kwarg `path` peut alors
être passé en query param sans collision.

Ces tests instancient un VRAI `VaultHttpClient` (pas de MagicMock(spec=...)) +
patchent `httpx.request` au niveau réseau. C'est la seule manière de reproduire
le TypeError — un mock spec accepte n'importe quel kwarg sans broncher, donc
les tests préexistants `test_pathstyle_lookup.py` passaient alors que le code
plantait en prod.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from harpocrate.http import VaultHttpClient


def _fake_response(status: int = 200, payload: Any = None) -> MagicMock:
    """Réponse httpx mockée."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.json.return_value = payload if payload is not None else {}
    resp.text = str(payload) if payload is not None else ""
    return resp


@pytest.fixture(autouse=True)
def _allow_insecure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Autorise http:// pour les tests (sinon `_check_base_url` lève)."""
    monkeypatch.setenv("HARPOCRATE_ALLOW_INSECURE", "1")


def test_get_accepts_path_kwarg_as_query_param() -> None:
    """Régression du bug : `.get(url, path="...")` ne lève PAS TypeError.

    Avant le fix : TypeError car `path` était à la fois le 1er positionnel
    (recevant l'URL) et un kwarg explicite (recevant le filtre query param).
    Après le fix : `path` n'est plus le nom du positionnel — il est libre
    comme kwarg et passe dans **params (query params httpx).
    """
    client = VaultHttpClient(base_url="http://localhost:8000", token="hrpv_test")
    fake_resp = _fake_response(200, {"secrets": []})

    with patch("httpx.request", return_value=fake_resp) as mock_request:
        # AVANT LE FIX : cet appel lève `TypeError: VaultHttpClient.get() got
        # multiple values for argument 'path'`.
        result = client.get("/v1/wallets/abc/secrets", path="/users/no_email/")

    assert result == {"secrets": []}
    # Vérifie que le kwarg `path` a bien été transmis comme query param httpx.
    call_kwargs = mock_request.call_args.kwargs
    assert call_kwargs["params"] == {"path": "/users/no_email/"}


def test_get_with_unpacked_params_containing_path() -> None:
    """`list_secrets(path=...)` fait `_http.get(url, **params)` avec `params["path"]`.

    Avant le fix : pareil, collision sur `path`. Après : OK.
    """
    client = VaultHttpClient(base_url="http://localhost:8000", token="hrpv_test")
    fake_resp = _fake_response(200, {"secrets": []})
    params = {"limit": 50, "path": "/foo/bar/"}

    with patch("httpx.request", return_value=fake_resp) as mock_request:
        result = client.get("/v1/wallets/abc/secrets", **params)

    assert result == {"secrets": []}
    assert mock_request.call_args.kwargs["params"] == {"limit": 50, "path": "/foo/bar/"}


def test_get_without_path_kwarg_still_works() -> None:
    """Non-régression : `.get(url)` sans kwarg fonctionne (URL en seul positionnel)."""
    client = VaultHttpClient(base_url="http://localhost:8000", token="hrpv_test")
    fake_resp = _fake_response(200, {"id": "x"})

    with patch("httpx.request", return_value=fake_resp) as mock_request:
        result = client.get("/v1/wallets/abc/secrets/by-id/some-id")

    assert result == {"id": "x"}
    # params=None ou dict vide selon l'implémentation — les deux sont acceptables.
    call_kwargs = mock_request.call_args.kwargs
    assert call_kwargs.get("params") in (None, {})


def test_get_with_multiple_query_params() -> None:
    """Plusieurs query params arbitraires passent comme **params."""
    client = VaultHttpClient(base_url="http://localhost:8000", token="hrpv_test")
    fake_resp = _fake_response(200, {"types": []})

    with patch("httpx.request", return_value=fake_resp) as mock_request:
        result = client.get("/v1/secret-types", q="bcrypt", include_deprecated=True)

    assert result == {"types": []}
    assert mock_request.call_args.kwargs["params"] == {
        "q": "bcrypt",
        "include_deprecated": True,
    }


def test_post_put_patch_delete_signatures_dont_clash_with_path() -> None:
    """Les autres méthodes (post/put/patch/delete) renommées aussi pour cohérence.

    Note : post/put/patch n'avaient pas de `**params` donc le bug n'existait
    pas, mais on renomme pour cohérence + lisibilité (le nom du positionnel
    décrit mieux ce qu'il représente : une URL, pas un "path" métier).
    """
    client = VaultHttpClient(base_url="http://localhost:8000", token="hrpv_test")
    fake_resp = _fake_response(204)

    with patch("httpx.request", return_value=fake_resp) as mock_request:
        client.post("/v1/x", json={"a": 1})
        client.put("/v1/x", json={"a": 2})
        client.patch("/v1/x", json={"a": 3})
        client.delete("/v1/x")

    # 4 appels httpx, dans l'ordre.
    methods = [c.args[0] for c in mock_request.call_args_list]
    assert methods == ["POST", "PUT", "PATCH", "DELETE"]
