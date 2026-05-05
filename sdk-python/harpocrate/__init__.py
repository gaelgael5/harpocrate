"""SDK Python Harpocrate — client zero-knowledge pour Vault.

Interface principale :
    from harpocrate import VaultClient

    client = VaultClient(
        token="hrpv_1_...",
        base_url="https://vault.yoops.org",
    )
    value = client.secrets.get("ANTHROPIC_API_KEY")

Modules :
    harpocrate.client     — VaultClient (point d'entrée principal)
    harpocrate.token      — parse_token, ParsedToken
    harpocrate.crypto     — aes_gcm_encrypt, aes_gcm_decrypt
    harpocrate.generators — dispatch (9 générateurs)
    harpocrate.cache      — WalletKeyCache
    harpocrate.models     — SecretInfo, PopulateResult, WalletInfo, ApiKeyInfo
    harpocrate.exceptions — toutes les exceptions SDK
    harpocrate.cli        — CLI Click (harpocrate-gen)
"""

from __future__ import annotations

from harpocrate.client import VaultClient
from harpocrate.exceptions import (
    GeneratorError,
    HarpocrateError,
    InvalidTokenError,
    PermissionDenied,
    PlaceholderNotPopulated,
    SecretNotFound,
    TokenExpiredError,
    VaultDecryptionError,
    VaultHttpError,
)

__version__ = "0.1.0"

__all__ = [
    "VaultClient",
    "HarpocrateError",
    "InvalidTokenError",
    "TokenExpiredError",
    "PermissionDenied",
    "VaultHttpError",
    "VaultDecryptionError",
    "SecretNotFound",
    "PlaceholderNotPopulated",
    "GeneratorError",
]
