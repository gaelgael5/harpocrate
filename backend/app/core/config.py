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
    # Keycloak OIDC : optionnel — si les 3 vars sont vides, le mode OIDC est
    # masqué côté UI (cf. /v1/config/auth-modes) et `prefetch_jwks` est skippé
    # au boot. L'auth admin local doit alors être activée pour qu'au moins un
    # mode de connexion soit dispo (validator `_validate_at_least_one_auth`).
    keycloak_url: str = ""
    keycloak_realm: str = ""
    keycloak_client_id: str = ""
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

    # ─── Clustering (LOT_21A) ─────────────────────────────────────────────────
    # Identifiant unique du nœud dans les logs cluster. Auto-généré si vide
    # (hostname-pid). Injecter manuellement en prod pour avoir des IDs stables.
    instance_id: str = Field(default="")

    # ─── Stratégie de réplication (LOT_20) ────────────────────────────────────
    # Postgres standalone par défaut. Bascule possible en runtime via UI admin.
    replication_strategy: str = Field(
        default="none",
        description="none | patroni | harpocrate_sync | s3_wal",
    )
    patroni_api_urls: str = Field(
        default="",
        description="CSV des URLs API REST Patroni (ex http://10.0.0.1:8008,http://10.0.0.2:8008)",
    )
    postgres_replica_dsn: str = Field(
        default="",
        description="DSN du replica Postgres pour les lectures non critiques (LOT_20)",
        json_schema_extra={"is_secret": True},
    )

    # ─── Réplication MQTT (LOT_21B) ──────────────────────────────────────────
    sync_enabled: bool = Field(
        default=False,
        description="Active la réplication applicative MQTT inter-instances",
    )
    sync_cluster_id: str = Field(
        default="harpocrate",
        description="Identifiant logique du cluster (isolation broker MQTT mutualisé)",
    )
    sync_mqtt_host: str = Field(default="")
    sync_mqtt_port: int = Field(default=1883)
    sync_mqtt_username: str = Field(default="")
    sync_mqtt_password: str = Field(
        default="",
        json_schema_extra={"is_secret": True},
    )
    sync_log_retention_days: int = Field(
        default=7,
        ge=1,
        description="Rétention sync_log avant purge (futur lot de cron)",
    )

    @field_validator("instance_id")
    @classmethod
    def _auto_instance_id(cls, v: str) -> str:
        if v:
            return v
        import os
        import socket

        return f"{socket.gethostname()}-{os.getpid()}"

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

    # ─── Notifications externes via listmonk (LOT_57) ─────────────────────────
    # Harpocrate ne gère pas l'envoi de mail directement : il déclenche
    # un transactional template listmonk via POST /api/tx. Si la config est
    # incomplète, le service retombe en no-op (logge à warning).
    #
    # Toutes les variables utilisent le préfixe global `HARPOCRATE_` (cf.
    # env_prefix). Cohérent avec le reste de la config Harpocrate.
    listmonk_url: str = Field(default="")
    listmonk_user: str = Field(default="")
    listmonk_token: str = Field(default="", json_schema_extra={"is_secret": True})

    # IDs des templates transactional listmonk pour les mails de recovery,
    # par locale. À configurer côté admin listmonk avant le premier envoi.
    # Pattern `*_<locale>` extensible : ajouter `..._es`, `..._de`, etc.
    listmonk_template_recovery_en: int = Field(default=5)
    listmonk_template_recovery_fr: int = Field(default=4)

    @property
    def listmonk_configured(self) -> bool:
        # Les template_id ont des defaults non-zéro, donc l'unique check
        # qui décide de l'activation est la présence des credentials.
        return bool(self.listmonk_url and self.listmonk_user and self.listmonk_token)

    # ─── Recovery passphrase (LOT_57) ─────────────────────────────────────────
    # Tous les seuils/limites du flow recovery sont configurables pour permettre
    # le test (ex. mettre max_attempts=99 pour itérer la saisie des 24 mots
    # sans cramer la session) ou ajuster en prod.
    recovery_session_ttl_minutes: int = Field(default=30, ge=5)
    recovery_max_attempts: int = Field(default=3, ge=1)
    recovery_anomaly_threshold: int = Field(default=5, ge=1)
    recovery_anomaly_window_hours: int = Field(default=24, ge=1)

    # ─── SSH terminal admin (LOT 1) ───────────────────────────────────────────
    # Durée d'inactivité avant fermeture automatique de la session SSH (secondes).
    # Défaut 30 min ; ajustable sans redémarrage via var d'env.
    ssh_terminal_idle_timeout_seconds: int = Field(default=1800, ge=60)
    # Durée de validité d'un code de pairing (LOT 2).
    pairing_code_ttl_seconds: int = Field(default=600, ge=30)
    # Nombre max de tentatives de saisie du code de pairing avant invalidation.
    pairing_max_attempts: int = Field(default=3, ge=1)
    # Port Postgres annoncé aux standby lors de l'appairage. Doit être joignable
    # depuis le standby sur l'hôte extrait de public_url. Par convention 5432.
    replication_advertised_pg_port: int = Field(default=5432, ge=1, le=65535)

    @property
    def keycloak_configured(self) -> bool:
        """True si les 3 vars Keycloak sont remplies. Si False, le mode OIDC
        est masqué côté UI et le prefetch JWKS est skippé au boot."""
        return bool(self.keycloak_url and self.keycloak_realm and self.keycloak_client_id)

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

    @model_validator(mode="after")
    def _validate_at_least_one_auth(self) -> Settings:
        """Au moins un mode d'auth doit être dispo, sinon personne ne peut
        se connecter. On accepte : keycloak configuré, OU admin local activé,
        OU les deux."""
        if not self.keycloak_configured and not self.admin_local_enabled:
            raise ValueError(
                "no auth mode available: configure keycloak_url + keycloak_realm "
                "+ keycloak_client_id, OR set admin_local_enabled=True with "
                "username/password"
            )
        return self


settings = Settings()
