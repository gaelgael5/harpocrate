# Lot 00 — Fondations projet

> **Prérequis** : avoir lu `HARPOCRATE_OVERVIEW.md`.

## Objectif

Poser le squelette technique du backend Harpocrate : structure FastAPI, configuration validée, healthcheck, endpoint de configuration publique, packaging Docker. **Aucune table métier**, juste la connectivité.

## Dépendances

- Aucune (premier lot)

## Périmètre

### Inclus

- Structure de projet `backend/` complète selon les conventions overview
- FastAPI + uvicorn + Pydantic v2 + asyncpg + structlog
- Configuration via Pydantic Settings, lecture des `HARPOCRATE_*` env vars
- **Tag `is_secret` sur les Pydantic Fields** pour distinguer variables sensibles vs non-sensibles
- Validation au démarrage : refus si les floors KDF/RSA sont en dessous des minimums
- Pool de connexions asyncpg
- Endpoints `/v1/health` et `/v1/config/public`
- Logging structuré JSON (structlog)
- Linting (ruff), formatage, type checking (mypy strict)
- Dockerfile multi-stage et docker-compose.yml de dev avec Postgres 16
- Pre-commit hooks (ruff, mypy)
- Migrations versionnées : structure `migrations/` avec un script `apply_migrations.py`
- README.md du backend avec instructions de démarrage

### Exclus

- Aucune table métier, juste la table `_migrations`
- Pas d'authentification
- Pas de logique métier

## Spécifications fonctionnelles

### `GET /v1/health`

- **Auth** : aucune
- **Réponses** :
  - `200 { "status": "ok", "version": "0.1.0", "db": "ok" }`
  - `503 { "status": "degraded", "version": "0.1.0", "db": "unreachable" }`

### `GET /v1/config/public`

- **Auth** : aucune
- **Réponses** : `200`
```json
{
  "kdf_floors": {
    "memory_kb": 65536,
    "iterations": 3,
    "parallelism": 4
  },
  "rsa_minimum_key_size": 2048,
  "passphrase_minimum_length": 12,
  "supported_generators": ["random", "uuid", "bytes", "passphrase", "rsa_keypair", "ssh_keypair", "tls_certificate", "bcrypt_password", "template"],
  "audit_retention_days": 90,
  "quarantine_inactivity_days": 90,
  "quarantine_duration_days": 14,
  "version": "0.1.0"
}
```

### `GET /v1/config/keycloak`

- **Auth** : aucune
- **Réponses** : `200`
```json
{
  "realm": "harpocrate",
  "client_id": "harpocrate",
  "auth_url": "https://keycloak.yoops.org/realms/harpocrate",
  "token_url": "...",
  "jwks_url": "...",
  "issuer": "https://keycloak.yoops.org/realms/harpocrate",
  "expected_external_sub_claim": "external_sub",
  "expected_external_provider_claim": "external_provider"
}
```

Les deux derniers champs informent les clients (UI, SDK) de quels claims chercher pour récupérer l'identité fédérée.

## Spécifications techniques

### Structure de fichiers

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── core/
│   │   ├── config.py             # Pydantic Settings avec is_secret tags
│   │   ├── logging.py
│   │   └── exceptions.py
│   ├── db/
│   │   └── pool.py
│   ├── api/
│   │   └── v1/
│   │       ├── health.py
│   │       ├── config_public.py
│   │       └── config_keycloak.py
│   └── models/
├── migrations/
│   ├── 000_migrations_table.sql
│   └── apply_migrations.py
├── tests/
├── pyproject.toml
├── Dockerfile
├── ruff.toml
├── mypy.ini
└── README.md

# Racine du repo
docker-compose.yml
.env.example
```

### `app/core/config.py` — avec metadata `is_secret`

```python
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HARPOCRATE_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # ─── Sensibles (is_secret=True) ───
    db_dsn: str = Field(..., json_schema_extra={"is_secret": True})
    keycloak_client_secret: str = Field(..., json_schema_extra={"is_secret": True})
    hmac_key: str = Field(..., json_schema_extra={"is_secret": True})
    backup_s3_secret_key: str | None = Field(None, json_schema_extra={"is_secret": True})
    backup_s3_access_key: str | None = Field(None, json_schema_extra={"is_secret": True})

    # ─── Non sensibles ───
    keycloak_url: str
    keycloak_realm: str
    keycloak_client_id: str
    age_public_key: str  # publique par nature

    # KDF floors
    kdf_memory_kb: int = Field(default=65536, ge=65536)
    kdf_iterations: int = Field(default=3, ge=3)
    kdf_parallelism: int = Field(default=4, ge=4)
    rsa_key_size_min: int = Field(default=2048)
    passphrase_length_min: int = Field(default=12, ge=12)

    # Audit
    audit_retention_days: int = 90

    # Identity governance
    quarantine_inactivity_days: int = 90
    quarantine_duration_days: int = 14
    quarantine_auto_expire: bool = True
    reverify_validity_minutes: int = 5
    destructive_actions_require_reverify: bool = True

    # Backup
    backup_local_path: str = "/var/lib/harpocrate/backups"
    backup_s3_endpoint: str | None = None
    backup_s3_bucket: str | None = None
    backup_s3_region: str = "auto"
    backup_s3_object_lock_days: int = 0

    # Snapshots
    snapshot_interval_minutes: int = 0  # 0 = disabled
    snapshot_retention_gfs: str = ""  # JSON string, parsed at runtime

    # Caches
    wallet_key_cache_ttl_seconds: int = 600
    api_key_validation_cache_ttl_seconds: int = 60

    # Public
    public_url: str
    log_level: str = "INFO"

    @field_validator("rsa_key_size_min")
    @classmethod
    def validate_rsa(cls, v: int) -> int:
        if v not in (2048, 4096):
            raise ValueError("RSA key size must be 2048 or 4096")
        return v

    @field_validator("hmac_key")
    @classmethod
    def validate_hmac(cls, v: str) -> str:
        import base64
        try:
            decoded = base64.b64decode(v)
        except Exception as e:
            raise ValueError(f"hmac_key must be base64 encoded: {e}")
        if len(decoded) != 32:
            raise ValueError("hmac_key must be 32 bytes when decoded")
        return v

    @field_validator("age_public_key")
    @classmethod
    def validate_age_pub(cls, v: str) -> str:
        if not v.startswith("age1"):
            raise ValueError("age_public_key must start with 'age1'")
        return v

    @classmethod
    def get_non_sensitive_fields(cls) -> dict[str, type]:
        """Renvoie le mapping nom→type pour les champs non sensibles."""
        return {
            name: field.annotation
            for name, field in cls.model_fields.items()
            if not (field.json_schema_extra or {}).get("is_secret", False)
        }

    @classmethod
    def get_sensitive_fields(cls) -> dict[str, type]:
        """Renvoie le mapping nom→type pour les champs sensibles."""
        return {
            name: field.annotation
            for name, field in cls.model_fields.items()
            if (field.json_schema_extra or {}).get("is_secret", False)
        }


settings = Settings()  # type: ignore[call-arg]
```

### Reste de la structure

(Voir lot 00 historique pour `pool.py`, `logging.py`, `main.py`, `Dockerfile`, etc. La logique est identique avec les noms `harpocrate` à la place de `agflow_vault`.)

### `migrations/000_migrations_table.sql`

```sql
CREATE TABLE IF NOT EXISTS _migrations (
    id              SERIAL PRIMARY KEY,
    filename        TEXT NOT NULL UNIQUE,
    applied_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    checksum        TEXT NOT NULL
);
```

### `Dockerfile`

```dockerfile
FROM python:3.12-slim AS builder

WORKDIR /build
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir --target /install \
    fastapi uvicorn[standard] pydantic pydantic-settings asyncpg \
    structlog python-json-logger httpx python-jose[cryptography] \
    argon2-cffi cryptography

FROM python:3.12-slim

# age pour les backups (lot 12), installé dès maintenant pour ne pas refaire l'image
RUN apt-get update && apt-get install -y --no-install-recommends \
    age postgresql-client \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -r -u 1001 -m harpocrate

WORKDIR /app
COPY --from=builder /install /usr/local/lib/python3.12/site-packages
COPY app ./app
COPY migrations ./migrations

# Volume pour les backups
RUN mkdir -p /var/lib/harpocrate/backups /var/lib/harpocrate/env-backups \
    && chown -R harpocrate:harpocrate /var/lib/harpocrate

USER harpocrate

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### `docker-compose.yml`

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: harpocrate
      POSTGRES_USER: harpocrate
      POSTGRES_PASSWORD: dev_password_change_me
    ports:
      - "5432:5432"
    volumes:
      - harpocrate_pg_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U harpocrate"]
      interval: 5s

  harpocrate:
    build: ./backend
    environment:
      HARPOCRATE_DB_DSN: postgresql://harpocrate:dev_password_change_me@postgres:5432/harpocrate
      HARPOCRATE_KEYCLOAK_URL: http://keycloak:8080
      HARPOCRATE_KEYCLOAK_REALM: harpocrate
      HARPOCRATE_KEYCLOAK_CLIENT_ID: harpocrate
      HARPOCRATE_KEYCLOAK_CLIENT_SECRET: "dev-secret"
      HARPOCRATE_HMAC_KEY: "REPLACE_WITH_BASE64_32_BYTES"
      HARPOCRATE_AGE_PUBLIC_KEY: "age1xxx..."
      HARPOCRATE_PUBLIC_URL: http://localhost:8000
      HARPOCRATE_LOG_LEVEL: DEBUG
    ports:
      - "8000:8000"
    volumes:
      - harpocrate_backups:/var/lib/harpocrate
    depends_on:
      postgres:
        condition: service_healthy

volumes:
  harpocrate_pg_data:
  harpocrate_backups:
```

## Critères de succès

1. ✅ `docker compose up --build` démarre le backend et la DB sans erreur
2. ✅ `curl http://localhost:8000/v1/health` retourne `200`
3. ✅ `curl http://localhost:8000/v1/config/public` retourne le JSON attendu (avec quarantine fields)
4. ✅ `curl http://localhost:8000/v1/config/keycloak` retourne les claims attendus
5. ✅ `python migrations/apply_migrations.py` crée la table `_migrations`
6. ✅ Démarrage avec `HARPOCRATE_KDF_MEMORY_KB=10000` → erreur claire
7. ✅ Démarrage avec `HMAC_KEY` mal formaté → erreur explicite
8. ✅ Démarrage avec `AGE_PUBLIC_KEY` mal formaté → erreur explicite
9. ✅ Logs en JSON structuré sur stdout
10. ✅ `Settings.get_sensitive_fields()` retourne bien `{db_dsn, keycloak_client_secret, hmac_key, backup_s3_secret_key, backup_s3_access_key}`
11. ✅ `Settings.get_non_sensitive_fields()` ne contient aucun de ceux ci-dessus
12. ✅ `ruff check` et `mypy --strict app/` passent
13. ✅ `pytest tests/` passe

## Pièges connus

- **`is_secret` est un Pydantic `json_schema_extra`** : utiliser `model_fields` pour accéder via Python, pas `__fields__` (déprécié v1).
- **L'`age_public_key`** est une clé publique : non sensible. Ce qui est sensible, c'est la clé privée que l'admin garde sur son poste (jamais sur le serveur).
- **Le binaire `age` est installé dans l'image Docker** : pour préparer le lot 12, mais peut être omis si on est strict sur les images minimales (le lot 12 le rajoutera alors).
- **Healthcheck Docker compose** : attendre `service_healthy` sur Postgres.

## Tests à écrire

- `test_health_ok`, `test_health_db_down`
- `test_config_public_returns_floors_and_quarantine_settings`
- `test_config_keycloak_includes_external_sub_claim_name`
- `test_settings_rejects_low_kdf`
- `test_settings_rejects_invalid_hmac`
- `test_settings_rejects_invalid_age_pub_key`
- `test_settings_get_sensitive_fields_correct`
- `test_settings_get_non_sensitive_fields_correct`

## Ce qui suit

Le **lot 01** crée toutes les tables métier en une seule migration : `users`, `user_external_identities`, `identity_anomaly_events`, `wallets`, `secrets`, `api_keys`, `audit_log` etc.
