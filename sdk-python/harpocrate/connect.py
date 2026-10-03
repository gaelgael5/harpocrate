"""Assistant « Se connecter avec Harpocrate » côté application (feature 6).

Une application déclarée par un admin Harpocrate obtient une API key sur un wallet
choisi par l'utilisateur, sans que celui-ci copie un token et sans que Harpocrate voie
jamais la clé de déchiffrement (dkey) :

    from harpocrate import connect

    # 1. Dans le backend de l'application, quand l'utilisateur clique « Connecter » :
    browser_url, pending = connect.start(
        base_url="https://vault.example",
        client_id="ragflow",
        redirect_uri="https://rag.example/harpocrate/callback",
        permissions=0x01,           # read
        ttl_days=90,
    )
    session["harpocrate_connect"] = pending.to_dict()   # côté serveur, jamais au navigateur
    return redirect(browser_url)

    # 2. Sur redirect_uri, au retour du navigateur :
    if request.args.get("error"):                    # refus de l'utilisateur
        ...
    pending = connect.ConnectState.from_dict(session.pop("harpocrate_connect"))
    result = connect.finish(pending, code=request.args["code"], state=request.args["state"])
    store_encrypted(result.token)                    # le token complet, à chiffrer au repos

`ConnectState` contient le `code_verifier` PKCE et la clé PRIVÉE éphémère : il se garde
côté serveur (session), jamais dans un cookie lisible ni dans l'URL. Rien de sensible
n'est journalisé par ce module.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

import httpx
from joserfc import jwe
from joserfc.errors import JoseError
from joserfc.jwk import ECKey

from harpocrate.exceptions import ConnectError, InvalidTokenError
from harpocrate.http import _check_base_url
from harpocrate.token import parse_token, with_decryption_key

_TIMEOUT = 30.0
_SEAL_ALGORITHMS = ["ECDH-ES", "A256GCM"]


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


@dataclass(frozen=True)
class ConnectState:
    """État d'une demande en cours, à conserver côté serveur entre `start` et `finish`."""

    base_url: str
    client_id: str
    redirect_uri: str
    state: str
    code_verifier: str = field(repr=False)
    private_jwk: dict[str, Any] = field(repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "state": self.state,
            "code_verifier": self.code_verifier,
            "private_jwk": dict(self.private_jwk),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConnectState:
        return cls(
            base_url=str(data["base_url"]),
            client_id=str(data["client_id"]),
            redirect_uri=str(data["redirect_uri"]),
            state=str(data["state"]),
            code_verifier=str(data["code_verifier"]),
            private_jwk=dict(data["private_jwk"]),
        )


@dataclass(frozen=True)
class ConnectResult:
    """API key obtenue : le token complet (avec sa dkey) et ce qu'il désigne."""

    token: str = field(repr=False)
    api_key_id: UUID
    wallet_id: UUID


def _raise_for_status(response: httpx.Response) -> None:
    if response.is_success:
        return
    try:
        detail = response.json().get("detail", {})
        code = str(detail.get("error", "http_error")) if isinstance(detail, dict) else "http_error"
    except ValueError:
        code = "http_error"
    raise ConnectError(code, f"Harpocrate refused the request (HTTP {response.status_code})")


def start(
    base_url: str,
    client_id: str,
    redirect_uri: str,
    permissions: int,
    ttl_days: int | None = None,
    *,
    http_client: httpx.Client | None = None,
) -> tuple[str, ConnectState]:
    """Dépose la demande (PAR) et renvoie (URL où envoyer le navigateur, état à garder).

    Génère le couple PKCE S256 et une paire de clés éphémère P-256 ; seule la clé
    publique part à Harpocrate.
    """
    base_url = base_url.rstrip("/")
    _check_base_url(base_url)
    code_verifier = _b64url(secrets.token_bytes(32))
    code_challenge = _b64url(hashlib.sha256(code_verifier.encode("ascii")).digest())
    state = _b64url(secrets.token_bytes(24))
    key = ECKey.generate_key("P-256")
    body = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "permissions": permissions,
        "ttl_days": ttl_days,
        "app_public_jwk": key.as_dict(private=False),
    }
    client = http_client or httpx.Client(timeout=_TIMEOUT)
    try:
        response = client.post(f"{base_url}/v1/connect/par", json=body)
    finally:
        if http_client is None:
            client.close()
    _raise_for_status(response)
    request_uri = str(response.json()["request_uri"])
    query = urlencode({"client_id": client_id, "request_uri": request_uri})
    pending = ConnectState(
        base_url=base_url,
        client_id=client_id,
        redirect_uri=redirect_uri,
        state=state,
        code_verifier=code_verifier,
        private_jwk=key.as_dict(private=True),
    )
    return f"{base_url}/connect?{query}", pending


def _unseal(sealed: str, private_jwk: dict[str, Any]) -> tuple[str, str]:
    """Ouvre le scellé avec la clé privée éphémère → (token signé, dkey)."""
    try:
        key = ECKey.import_key(private_jwk)
        plaintext = jwe.decrypt_compact(sealed, key, algorithms=_SEAL_ALGORITHMS).plaintext
        payload = json.loads(plaintext or b"")
        return str(payload["token"]), str(payload["dkey"])
    except (JoseError, ValueError, KeyError, TypeError) as exc:
        raise ConnectError("invalid_seal", "The sealed API key cannot be opened") from exc


def finish(
    pending: ConnectState,
    *,
    code: str,
    state: str,
    http_client: httpx.Client | None = None,
) -> ConnectResult:
    """Échange le code (une seule fois) et reconstitue l'API key.

    `state` est celui reçu sur `redirect_uri` : il doit être identique à celui de la
    demande, sinon le retour n'est pas le nôtre (CSRF) et rien n'est échangé.
    """
    if not hmac.compare_digest(state, pending.state):
        raise ConnectError("state_mismatch", "The returned state does not match the request")
    client = http_client or httpx.Client(timeout=_TIMEOUT)
    try:
        response = client.post(
            f"{pending.base_url}/v1/connect/token",
            json={
                "client_id": pending.client_id,
                "code": code,
                "code_verifier": pending.code_verifier,
                "redirect_uri": pending.redirect_uri,
            },
        )
    finally:
        if http_client is None:
            client.close()
    _raise_for_status(response)
    data = response.json()
    signed_token, dkey = _unseal(str(data["jwe"]), pending.private_jwk)
    try:
        token = with_decryption_key(signed_token, dkey)
    except InvalidTokenError as exc:
        raise ConnectError("invalid_seal", "The sealed API key is malformed") from exc
    api_key_id = UUID(str(data["api_key_id"]))
    if parse_token(token).api_key_id != api_key_id:
        raise ConnectError("api_key_mismatch", "The sealed token does not match the API key")
    return ConnectResult(token=token, api_key_id=api_key_id, wallet_id=UUID(str(data["wallet_id"])))
