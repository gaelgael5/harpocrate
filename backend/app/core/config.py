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

    db_dsn: str = Field(json_schema_extra={"is_secret": True})
    keycloak_url: str
    keycloak_realm: str
    keycloak_client_id: str
    hmac_key: str = Field(json_schema_extra={"is_secret": True})

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
    admin_local_password: str = Field(default="", json_schema_extra={"is_secret": True})
    admin_local_email: str = "admin@harpocrate.local"
    admin_local_display_name: str = "Local Admin"

    # Mode developpement — affiche un bandeau d'avertissement permanent dans l'UI.
    # Aucun impact sur la crypto ou la securite : juste un repere visuel pour ne
    # JAMAIS confondre une instance dev avec la prod. A activer explicitement.
    dev_mode: bool = False
    dev_mode_label: str = "DEV"

    # Gouvernance d'identite (LOT_02) : duree d'inactivite avant quarantaine.
    quarantine_inactivity_days: int = 90
    # Duree de la quarantaine elle-meme (combien de temps l'utilisateur est bloque).
    quarantine_duration_days: int = 30

    # ─── Backup (LOT_12A) ─────────────────────────────────────────────────────
    age_public_key: str = Field(default="", json_schema_extra={"is_secret": False})
    backup_local_path: str = Field(default="/var/lib/harpocrate/backups")
    admin_role_name: str = Field(default="harpocrate-admin")
    backup_upload_max_bytes: int = Field(default=1 * 1024 * 1024 * 1024)

    # ─── S3 remote backup (LOT_13) ────────────────────────────────────────────
    s3_endpoint: str = Field(default="")
    s3_bucket: str = Field(default="")
    s3_access_key_id: str = Field(default="", json_schema_extra={"is_secret": True})
    s3_secret_access_key: str = Field(default="", json_schema_extra={"is_secret": True})
    s3_region: str = Field(default="us-east-1")
    s3_key_prefix: str = Field(default="harpocrate-backups/")

    @property
    def s3_configured(self) -> bool:
        return bool(self.s3_bucket and self.s3_access_key_id and self.s3_secret_access_key)

    def get_sensitive_fields(self) -> list[str]:
        """Retourne les noms des champs Settings marqués is_secret=True."""
        result = []
        for name, field in Settings.model_fields.items():
            extra = field.json_schema_extra or {}
            if isinstance(extra, dict) and extra.get("is_secret", False):
                result.append(name)
        return result

    def get_non_sensitive_fields(self) -> dict[str, object]:
        """Retourne les champs non-sensibles sous forme {HARPOCRATE_NAME: value}."""
        result: dict[str, object] = {}
        sensitive = set(self.get_sensitive_fields())
        for name in Settings.model_fields:
            if name not in sensitive:
                value = getattr(self, name)
                result[f"HARPOCRATE_{name.upper()}"] = value
        return result

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
