"""Settings Pydantic — validation des floors crypto au démarrage."""

from __future__ import annotations

import base64

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HARPOCRATE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    db_dsn: str
    keycloak_url: str
    keycloak_realm: str
    keycloak_client_id: str
    hmac_key: str

    kdf_memory_kb: int = Field(default=65536, ge=65536)
    kdf_iterations: int = Field(default=3, ge=3)
    kdf_parallelism: int = Field(default=4, ge=4)
    rsa_key_size_min: int = Field(default=2048)
    passphrase_length_min: int = Field(default=12, ge=12)

    wallet_key_cache_ttl_seconds: int = 600
    api_key_validation_cache_ttl_seconds: int = 60
    audit_retention_days: int = 90

    public_url: str
    log_level: str = "INFO"
    apps_file: str = Field(default="/app/apps.json")

    # ─── Auth locale (alternative à Keycloak OIDC) ────────────────────────────
    # WARNING : mot de passe stocké en clair dans .env — le fichier doit être en 600.
    # Activer uniquement pour dev / break-glass.
    admin_local_enabled: bool = False
    admin_local_username: str = ""
    admin_local_password: str = ""
    admin_local_email: str = "admin@harpocrate.local"
    admin_local_display_name: str = "Local Admin"

    # Mode developpement — affiche un bandeau d'avertissement permanent dans l'UI.
    # Aucun impact sur la crypto ou la securite : juste un repere visuel pour ne
    # JAMAIS confondre une instance dev avec la prod. A activer explicitement.
    dev_mode: bool = False
    dev_mode_label: str = "DEV"

    @field_validator("rsa_key_size_min")
    @classmethod
    def _validate_rsa(cls, v: int) -> int:
        if v not in (2048, 4096):
            raise ValueError("RSA key size must be 2048 or 4096")
        return v

    @field_validator("hmac_key")
    @classmethod
    def _validate_hmac(cls, v: str) -> str:
        try:
            decoded = base64.b64decode(v, validate=True)
        except Exception as e:
            raise ValueError(f"hmac_key must be base64 encoded: {e}") from e
        if len(decoded) != 32:
            raise ValueError("hmac_key must be 32 bytes when decoded")
        return v

    @model_validator(mode="after")
    def _validate_local_admin(self) -> Settings:
        if self.admin_local_enabled:
            if not self.admin_local_username:
                raise ValueError(
                    "admin_local_username must not be empty when admin_local_enabled=True"
                )
            if not self.admin_local_password:
                raise ValueError(
                    "admin_local_password must not be empty when admin_local_enabled=True"
                )
        return self


settings = Settings()
