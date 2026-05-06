"""Exceptions publiques du SDK Harpocrate."""

from __future__ import annotations


class HarpocrateError(Exception):
    """Erreur de base du SDK Harpocrate."""


class InvalidTokenError(HarpocrateError):
    """Token hrpv_* malformé ou non reconnu."""

    def __init__(self, error_code: str, message: str = "") -> None:
        super().__init__(message or error_code)
        self.error_code = error_code


class TokenExpiredError(HarpocrateError):
    """Le token hrpv_* est expiré."""


class PermissionDenied(HarpocrateError):
    """Permission insuffisante pour cette opération."""

    def __init__(self, message: str = "Permission denied") -> None:
        super().__init__(message)


class VaultHttpError(HarpocrateError):
    """Erreur HTTP retournée par le serveur Vault."""

    def __init__(self, status_code: int, detail: object = None) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail}")


class VaultDecryptionError(HarpocrateError):
    """Échec du déchiffrement AES-GCM (tag invalide ou clé incorrecte)."""


class SecretNotFound(HarpocrateError):
    """Le secret demandé est introuvable."""


class PlaceholderNotPopulated(HarpocrateError):
    """Le secret est un placeholder sans valeur (424 côté serveur)."""

    def __init__(self, name: str, descriptor: object = None) -> None:
        super().__init__(f"Secret '{name}' is a placeholder — populate it first")
        self.secret_name = name
        self.generation_descriptor = descriptor


class GeneratorError(HarpocrateError):
    """Erreur dans l'un des 9 générateurs."""


class SecretRefreshFailed(HarpocrateError):
    """Le refresh forcé d'un secret a échoué (LOT_22).

    Levée par `notify_auth_error()` ou `using_secret()` quand un retry de
    refresh est impossible (secret supprimé, API key révoquée, etc.).
    """

    def __init__(self, secret_name: str, reason: str) -> None:
        super().__init__(f"Failed to refresh secret '{secret_name}': {reason}")
        self.secret_name = secret_name
        self.reason = reason
