"""Helpers partagés pour les tests — génération de matériel crypto de test."""
from __future__ import annotations

import time
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

# ─── RSA keypair de test (session-scoped : coûteux à générer) ────────────────

_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_public_jwk: dict[str, Any] = jwt.algorithms.RSAAlgorithm.to_jwk(
    _private_key.public_key(), as_dict=True
)
_public_jwk["kid"] = "test-kid"

TEST_PRIVATE_KEY = _private_key
TEST_PUBLIC_JWK = _public_jwk
TEST_KID = "test-kid"

# Issuer et audience utilisés dans les tests
TEST_ISSUER = "https://keycloak.yoops.org/realms/yoops"
TEST_AUDIENCE = "harpocrate-vault"


def make_jwt_token(
    sub: str = "test-sub-001",
    email: str = "alice@example.com",
    name: str | None = "Alice Test",
    audience: str = TEST_AUDIENCE,
    issuer: str = TEST_ISSUER,
    exp_offset: int = 3600,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Génère un JWT signé avec la clé RSA de test."""
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": sub,
        "email": email,
        "aud": audience,
        "iss": issuer,
        "iat": now,
        "exp": now + exp_offset,
    }
    if name is not None:
        payload["name"] = name
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(
        payload,
        TEST_PRIVATE_KEY,
        algorithm="RS256",
        headers={"kid": TEST_KID},
    )
