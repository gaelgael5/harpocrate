"""Validation des URLs de retour déclarées pour une application (décision D1).

Une URL de retour mal validée permettrait d'envoyer le code à usage unique vers
un site tiers (redirection ouverte) : chaque cas de rejet est un test.
"""

from __future__ import annotations

import pytest

from app.services.connect_clients import InvalidRedirectUriError, validate_redirect_uri


@pytest.mark.parametrize(
    "uri",
    [
        "https://rag.example/oauth/harpocrate/callback",
        "https://docflow.yoops.org/settings/vault/callback?source=harpocrate",
        "https://portal.example:8443/cb",
        "http://localhost:5173/callback",
        "http://127.0.0.1:8000/callback",
    ],
)
def test_validate_redirect_uri_accepts_exact_https_or_local_http(uri: str) -> None:
    assert validate_redirect_uri(uri) == uri


@pytest.mark.parametrize(
    ("uri", "reason"),
    [
        ("http://rag.example/cb", "http hors poste local"),
        ("ftp://rag.example/cb", "schéma non web"),
        ("javascript:alert(1)", "schéma javascript"),
        ("/callback", "URL relative"),
        ("https:///callback", "hôte absent"),
        ("https://rag.example/cb#frag", "fragment"),
        ("https://*.example/cb", "joker dans l'hôte"),
        ("https://rag.example/*", "joker dans le chemin"),
        ("https://user:pw@rag.example/cb", "identifiants dans l'URL"),
        ("https://rag.example/c b", "espace"),
        ("https://rag.example/" + "a" * 2050, "trop longue"),
        ("", "vide"),
    ],
)
def test_validate_redirect_uri_rejects(uri: str, reason: str) -> None:
    with pytest.raises(InvalidRedirectUriError):
        validate_redirect_uri(uri)
