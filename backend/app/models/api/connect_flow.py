"""Schémas Pydantic du flux « Se connecter avec Harpocrate » — demande et consentement.

Le registre des applications est dans `connect.py` ; ici, ce qui circule entre
l'application, le navigateur et Harpocrate pendant une demande (features 2 à 5).
`extra="forbid"` partout en entrée : un champ inattendu est refusé, jamais ignoré.
"""

from __future__ import annotations

import base64
import datetime
import json
from typing import Literal
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric import ec
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.api.api_keys import ApiKeyMaterial
from app.models.api.connect import CLIENT_ID_PATTERN

# base64url sans padding de 32 octets (coordonnée P-256, empreinte SHA-256).
B64URL_32_PATTERN = r"^[A-Za-z0-9_-]{43}$"
REQUEST_URI_PREFIX = "urn:ietf:params:oauth:request_uri:"
REQUEST_URI_PATTERN = r"^urn:ietf:params:oauth:request_uri:[A-Za-z0-9_-]{43}$"


def _b64url_int(value: str) -> int:
    return int.from_bytes(base64.urlsafe_b64decode(value + "="), "big")


class AppPublicJwk(BaseModel):
    """Clé publique éphémère EC P-256 de l'application (RFC 7517).

    `extra="forbid"` refuse en particulier le membre `d` : une application qui enverrait
    sa clé PRIVÉE par erreur est arrêtée ici, avant que la clé ne soit stockée.
    """

    model_config = ConfigDict(extra="forbid")

    kty: Literal["EC"]
    crv: Literal["P-256"]
    x: str = Field(pattern=B64URL_32_PATTERN)
    y: str = Field(pattern=B64URL_32_PATTERN)
    use: Literal["enc"] | None = None
    alg: Literal["ECDH-ES"] | None = None
    kid: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def _point_on_curve(self) -> AppPublicJwk:
        # Un point hors courbe rendrait l'accord de clé ECDH-ES dangereux (attaque par
        # courbe invalide) : on le refuse dès le dépôt.
        try:
            ec.EllipticCurvePublicNumbers(
                _b64url_int(self.x), _b64url_int(self.y), ec.SECP256R1()
            ).public_key()
        except ValueError as exc:
            raise ValueError("app_public_jwk is not a valid P-256 point") from exc
        return self


class ConnectParRequest(BaseModel):
    """Corps de POST /v1/connect/par — dépôt de la demande par le backend de l'application."""

    model_config = ConfigDict(extra="forbid")

    client_id: str = Field(pattern=CLIENT_ID_PATTERN)
    redirect_uri: str = Field(min_length=1, max_length=2048)
    state: str = Field(min_length=1, max_length=512)
    code_challenge: str = Field(pattern=B64URL_32_PATTERN)
    code_challenge_method: Literal["S256"]
    permissions: int = Field(ge=1, le=63)
    ttl_days: int | None = Field(default=None, ge=1, le=3650)
    app_public_jwk: AppPublicJwk


class ConnectParResponse(BaseModel):
    """Réponse du dépôt PAR (RFC 9126 §2.2)."""

    request_uri: str
    expires_in: int


class ConnectClientPublic(BaseModel):
    """Ce que l'utilisateur voit de l'application : son nom DÉCLARÉ, jamais une valeur de
    la requête (invariant 5 du cadrage)."""

    client_id: str
    name: str
    description: str | None


class ConnectRequestView(BaseModel):
    """Réponse de GET /v1/connect/requests/{request_uri} — de quoi afficher le consentement."""

    client: ConnectClientPublic
    redirect_uri: str
    requested_permissions: int
    requested_ttl_days: int | None
    app_public_jwk: AppPublicJwk
    expires_at: datetime.datetime


class ConnectRedirectResponse(BaseModel):
    """Où renvoyer le navigateur : URL de retour DÉCLARÉE + paramètres (code ou erreur)."""

    redirect_to: str


class ConnectApiKeyCreate(ApiKeyMaterial):
    """Corps de POST /v1/connect/requests/{request_uri}/api-key (feature 4).

    Comme la création manuelle, MAIS sans `decryption_key` : `extra="forbid"` la refuse
    si un navigateur l'envoyait quand même. Le serveur ne voit jamais la dkey (D4).
    """

    model_config = ConfigDict(extra="forbid")

    wallet_id: UUID
    permissions: int = Field(ge=1, le=63)
    ttl_days: int | None = Field(default=None, ge=1, le=3650)
    # 32 octets en base64url sans padding : c'est un segment du token.
    auth_secret: str = Field(pattern=B64URL_32_PATTERN)


class ConnectApiKeyResponse(BaseModel):
    """Token signé avec le segment `dkey` de substitution ; le navigateur y remet la vraie
    dkey avant de sceller le tout pour l'application."""

    api_key_id: UUID
    token: str


# JWE compact : cinq segments base64url ; en ECDH-ES direct, la clé chiffrée est vide.
_JWE_COMPACT_PATTERN = r"^[A-Za-z0-9_-]+\.\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$"


class ConnectSealRequest(BaseModel):
    """Corps de POST /v1/connect/requests/{request_uri}/sealed — dépôt du scellé (D5).

    Le serveur ne peut pas lire le contenu ; il en vérifie seulement la forme et l'en-tête
    protégé (algorithmes attendus), pour qu'une erreur du navigateur échoue ici et non
    chez l'application.
    """

    model_config = ConfigDict(extra="forbid")

    jwe: str = Field(max_length=8192, pattern=_JWE_COMPACT_PATTERN)

    @model_validator(mode="after")
    def _expected_algorithms(self) -> ConnectSealRequest:
        encoded = self.jwe.split(".", 1)[0]
        try:
            header = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("jwe protected header is not valid JSON") from exc
        if not isinstance(header, dict):
            raise ValueError("jwe protected header must be an object")
        if header.get("alg") != "ECDH-ES" or header.get("enc") != "A256GCM":
            raise ValueError("jwe must use alg ECDH-ES and enc A256GCM")
        epk = header.get("epk")
        if not isinstance(epk, dict) or epk.get("kty") != "EC" or epk.get("crv") != "P-256":
            raise ValueError("jwe epk must be an EC P-256 key")
        return self


class ConnectTokenRequest(BaseModel):
    """Corps de POST /v1/connect/token — échange du code par le backend de l'application."""

    model_config = ConfigDict(extra="forbid")

    client_id: str = Field(pattern=CLIENT_ID_PATTERN)
    code: str = Field(pattern=B64URL_32_PATTERN)
    # RFC 7636 §4.1 : 43 à 128 caractères non réservés.
    code_verifier: str = Field(pattern=r"^[A-Za-z0-9._~-]{43,128}$")
    redirect_uri: str = Field(min_length=1, max_length=2048)


class ConnectTokenResponse(BaseModel):
    """Le scellé, remis UNE fois puis effacé, et de quoi l'identifier côté application."""

    jwe: str
    api_key_id: UUID
    wallet_id: UUID
