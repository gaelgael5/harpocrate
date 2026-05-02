# Lot 12e — Gestion des variables d'environnement (sensibles vs non-sensibles)

> **Prérequis** : Lots 00-11, 12a-d.

## Objectif

Fournir à l'admin une **interface claire pour visualiser, exporter et restaurer** les variables d'environnement de l'instance Harpocrate, en distinguant strictement les **non-sensibles** (incluses dans le backup principal) et les **sensibles** (backup séparé chiffré, à stocker dans le coffre personnel de l'admin).

## Dépendances

- Lots 00-11, 12a-d

## Périmètre

### Inclus

- Endpoint `GET /v1/admin/system/env` qui liste toutes les env vars avec leur type
- Endpoint `GET /v1/admin/system/env/non-sensitive` (export JSON pour stockage classique)
- Endpoint `GET /v1/admin/system/env/sensitive/backup` (export chiffré `age` séparé)
- Endpoint `POST /v1/admin/system/env/sensitive/restore-preview` (déchiffrement et preview, sans application)
- Page UI `/admin/system/env` avec deux onglets distincts
- CLI `harpocrate-admin env export` et `harpocrate-admin env import`
- Documentation explicite sur : "que faire si je perds mes variables sensibles"

### Exclus

- Pas de modification en live des env vars depuis l'UI (Pydantic Settings est lu au démarrage, modification = restart conteneur)
- Pas d'application automatique d'un backup d'env (génération d'un fichier `.env.restore` à appliquer manuellement)

## Spécifications fonctionnelles

### Pourquoi cette séparation ?

- **Non-sensibles** (URL, floors, paths) : incluses dans le backup principal. Si tu restaures un backup principal sur une nouvelle machine, les valeurs de config "fonctionnelles" sont disponibles.
- **Sensibles** (HMAC_KEY, KEYCLOAK_CLIENT_SECRET, S3_SECRET_KEY) : leur perte est catastrophique :
  - `HMAC_KEY` perdue → toutes les API keys existantes deviennent invalides
  - `KEYCLOAK_CLIENT_SECRET` perdue → recréer dans Keycloak admin
  - `S3_SECRET_KEY` perdue → recréer dans le provider cloud

→ ces variables doivent être **stockées séparément**, idéalement dans le coffre personnel de l'admin (Dashlane, 1Password) **et** chiffrées via `age` dans un fichier de backup distinct.

### Catégorisation des variables

```python
# Récupérée via Settings.model_fields et metadata is_secret

NON_SENSITIVE = [
    "HARPOCRATE_KEYCLOAK_URL",
    "HARPOCRATE_KEYCLOAK_REALM",
    "HARPOCRATE_KEYCLOAK_CLIENT_ID",
    "HARPOCRATE_AGE_PUBLIC_KEY",          # publique par nature
    "HARPOCRATE_KDF_*",
    "HARPOCRATE_RSA_KEY_SIZE_MIN",
    "HARPOCRATE_PASSPHRASE_LENGTH_MIN",
    "HARPOCRATE_AUDIT_RETENTION_DAYS",
    "HARPOCRATE_QUARANTINE_*",
    "HARPOCRATE_REVERIFY_VALIDITY_MINUTES",
    "HARPOCRATE_BACKUP_LOCAL_PATH",
    "HARPOCRATE_BACKUP_S3_ENDPOINT",
    "HARPOCRATE_BACKUP_S3_BUCKET",
    "HARPOCRATE_BACKUP_S3_REGION",
    "HARPOCRATE_BACKUP_S3_OBJECT_LOCK_DAYS",
    "HARPOCRATE_SNAPSHOT_INTERVAL_MINUTES",
    "HARPOCRATE_SNAPSHOT_RETENTION_GFS",
    "HARPOCRATE_LOG_LEVEL",
    "HARPOCRATE_PUBLIC_URL",
]

SENSITIVE = [
    "HARPOCRATE_DB_DSN",                  # contient le mot de passe Postgres
    "HARPOCRATE_KEYCLOAK_CLIENT_SECRET",
    "HARPOCRATE_HMAC_KEY",                # le plus critique
    "HARPOCRATE_BACKUP_S3_ACCESS_KEY",
    "HARPOCRATE_BACKUP_S3_SECRET_KEY",
]
```

Cette catégorisation est **dérivée automatiquement** de la metadata `is_secret=True` posée sur les `Field` Pydantic au lot 00. Une seule source de vérité.

### `GET /v1/admin/system/env`

- **Auth** : JWT + admin
- **Réponse** :

```json
{
  "non_sensitive": {
    "count": 18,
    "fields": [
      {
        "name": "HARPOCRATE_KEYCLOAK_URL",
        "value": "https://keycloak.yoops.org",
        "type": "str",
        "default": null,
        "required": true,
        "current_matches_default": false
      },
      {
        "name": "HARPOCRATE_KDF_MEMORY_KB",
        "value": 65536,
        "type": "int",
        "default": 65536,
        "required": false,
        "current_matches_default": true
      }
    ]
  },
  "sensitive": {
    "count": 5,
    "fields": [
      {
        "name": "HARPOCRATE_DB_DSN",
        "is_set": true,
        "masked_value": "postgresql://harpocrate:****@postgres:5432/harpocrate",
        "type": "str",
        "required": true
      },
      {
        "name": "HARPOCRATE_HMAC_KEY",
        "is_set": true,
        "masked_value": "Y29uZ3JhdHU****",
        "type": "str",
        "required": true,
        "criticality": "highest",
        "loss_impact": "All existing API keys become invalid; users must recreate them"
      },
      {
        "name": "HARPOCRATE_BACKUP_S3_SECRET_KEY",
        "is_set": false,
        "masked_value": null,
        "type": "str",
        "required": false,
        "criticality": "high",
        "loss_impact": "Cannot push or read remote backups; recreate in cloud provider"
      }
    ]
  }
}
```

Pour les sensibles, on ne renvoie JAMAIS la valeur en clair. Juste un `masked_value` (premiers et derniers caractères, ou un masking heuristique pour DSN).

### `GET /v1/admin/system/env/non-sensitive`

- **Auth** : JWT + admin
- **Réponse** : JSON brut directement copiable (mêmes champs que le backup principal `env-non-sensitive.json`)

```json
{
  "HARPOCRATE_KEYCLOAK_URL": "https://keycloak.yoops.org",
  "HARPOCRATE_KEYCLOAK_REALM": "harpocrate",
  ...
}
```

### `GET /v1/admin/system/env/sensitive/backup`

- **Auth** : JWT + admin + reverify
- **Réponse** : streaming du fichier `harpocrate-secrets-{ts}.env.age`

Format avant chiffrement :
```
HARPOCRATE_DB_DSN=postgresql://harpocrate:s3cr3t@postgres:5432/harpocrate
HARPOCRATE_KEYCLOAK_CLIENT_SECRET=abc123...
HARPOCRATE_HMAC_KEY=eW91ci0zMi1ieXRlcy1obWFjLWtleS1pbi1iNjQ=
HARPOCRATE_BACKUP_S3_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE
HARPOCRATE_BACKUP_S3_SECRET_KEY=wJalrXUtnFEMI...
```

Chiffré avec la clé publique `age` admin (la même que pour le backup principal).

- **Audit** : `admin.env_sensitive_exported` (sensible, à monitorer)

### `POST /v1/admin/system/env/sensitive/restore-preview`

- **Auth** : JWT + admin + reverify
- **Body** : `multipart/form-data` avec `file` (le `.env.age`) + `age_private_key`
- **Effets** :
  - Déchiffrer en mémoire
  - Parser le contenu
  - Comparer avec l'env actuelle :
    - Variables présentes dans le backup mais pas dans l'env actuelle → "missing"
    - Variables présentes dans l'env actuelle mais pas dans le backup → "extra"
    - Variables présentes dans les deux avec valeurs différentes → "changed"
    - Variables présentes dans les deux avec mêmes valeurs → "unchanged"
- **Réponse** :

```json
{
  "preview": {
    "missing_in_current": ["HARPOCRATE_BACKUP_S3_SECRET_KEY"],
    "extra_in_current": [],
    "changed": [
      { "name": "HARPOCRATE_HMAC_KEY", "match": false }
    ],
    "unchanged": ["HARPOCRATE_DB_DSN", "HARPOCRATE_KEYCLOAK_CLIENT_SECRET"]
  },
  "instructions": "To apply: SSH into the server, edit .env, restart the harpocrate container.",
  "warning_hmac_key_change": "If HARPOCRATE_HMAC_KEY changes, all existing API keys become invalid."
}
```

**Ne modifie JAMAIS** le runtime. L'admin doit éditer manuellement son `.env` puis redémarrer le conteneur. C'est intentionnel — ces vars sont critiques, pas de modif en un clic.

### Page UI `/admin/system/env`

```
System configuration
═════════════════════════════════════════════

[Non-sensitive (18)] [Sensitive (5)]

  ─── Onglet "Non-sensitive" ───

  These configuration values are included in your main backups.

  Search: ____________

  ┌─────────────────────────────────────────┬─────────────────┬──────┐
  │ Variable                                 │ Value           │      │
  ├─────────────────────────────────────────┼─────────────────┼──────┤
  │ HARPOCRATE_KEYCLOAK_URL                  │ https://...     │ Copy │
  │ HARPOCRATE_KEYCLOAK_REALM                │ harpocrate      │ Copy │
  │ HARPOCRATE_KDF_MEMORY_KB                 │ 65536  (default)│ Copy │
  │ ...                                      │ ...             │      │
  └─────────────────────────────────────────┴─────────────────┴──────┘

  [Export all as .env file] [Export all as JSON]
```

```
  ─── Onglet "Sensitive" ───

  ⚠️ These values are NEVER included in main backups for security reasons.
     They must be backed up SEPARATELY and stored in your personal vault
     (Dashlane, 1Password, etc.).

  ┌─────────────────────────────────────────┬─────────────────┬─────────────┐
  │ Variable                                 │ Status          │ Criticality │
  ├─────────────────────────────────────────┼─────────────────┼─────────────┤
  │ HARPOCRATE_DB_DSN                        │ ✓ set           │ high        │
  │ HARPOCRATE_KEYCLOAK_CLIENT_SECRET        │ ✓ set           │ high        │
  │ HARPOCRATE_HMAC_KEY                      │ ✓ set           │ HIGHEST     │
  │ HARPOCRATE_BACKUP_S3_ACCESS_KEY          │ ⚠ not set       │ medium      │
  │ HARPOCRATE_BACKUP_S3_SECRET_KEY          │ ⚠ not set       │ medium      │
  └─────────────────────────────────────────┴─────────────────┴─────────────┘

  Why is HARPOCRATE_HMAC_KEY the most critical?
  > It signs all API keys. If lost, every API key currently in use
    becomes invalid and must be regenerated by users.

  [⬇ Download encrypted backup (.env.age)]
  [⬆ Upload .env.age to preview]
```

### Modal "Download encrypted backup"

```
Download sensitive env backup

This will download a file `harpocrate-secrets-{ts}.env.age`
containing all sensitive environment variables, encrypted
with your admin age public key.

Recommendations:
  □ Store this file in your password manager (Dashlane, 1Password, etc.)
    as a Secure Note attachment
  □ Also store a copy on a USB drive in a safe location
  □ Never share this file or its decrypted contents

Re-enter passphrase to confirm:
┌──────────────────────────────────┐
│                                  │
└──────────────────────────────────┘

[Cancel]  [Download]
```

### Modal "Upload to preview"

```
Preview a sensitive env backup

Upload your .env.age file to compare with the current configuration.
This is read-only — no values will be applied automatically.

  [📁 Drop .env.age file or click to browse]

Age private key:
┌──────────────────────────────────┐
│ AGE-SECRET-KEY-1...              │
└──────────────────────────────────┘

Re-enter passphrase to confirm:
┌──────────────────────────────────┐
│                                  │
└──────────────────────────────────┘

[Cancel]  [Decrypt and preview]
```

Affichage du résultat :

```
Comparison result

✓ 2 variables match the current configuration
⚠ 1 variable differs from current
✗ 1 variable is missing from current

Details:
┌──────────────────────────────────────┬──────────────┐
│ HARPOCRATE_DB_DSN                    │ ✓ unchanged  │
│ HARPOCRATE_KEYCLOAK_CLIENT_SECRET    │ ✓ unchanged  │
│ HARPOCRATE_HMAC_KEY                  │ ⚠ DIFFERENT  │
│ HARPOCRATE_BACKUP_S3_SECRET_KEY      │ ✗ missing    │
└──────────────────────────────────────┴──────────────┘

⚠️ Warning: HARPOCRATE_HMAC_KEY differs.
   If you apply this backup, all currently active API keys will become invalid.

To apply changes:
  1. SSH into the server
  2. Edit /opt/harpocrate/.env (or your equivalent)
  3. Update or add the listed variables
  4. Restart the harpocrate container: `docker compose restart harpocrate`
```

### CLI

```bash
# Export non-sensible
harpocrate-admin env export --non-sensitive --output config.env

# Export sensible (chiffré)
harpocrate-admin env export --sensitive \
  --output secrets.env.age

# Preview d'un backup chiffré
harpocrate-admin env import --preview \
  --file secrets.env.age \
  --age-key-file ~/.harpocrate/age.key
```

## Spécifications techniques

### Service backend

```python
# app/services/env_management.py

import json
import tempfile
from pathlib import Path
from app.core.config import Settings


class EnvManagementService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def list_all(self) -> dict:
        """Liste structurée de toutes les env vars."""
        non_sensitive = []
        sensitive = []

        for name, field in Settings.model_fields.items():
            is_secret = (field.json_schema_extra or {}).get("is_secret", False)
            value = getattr(self.settings, name)
            env_name = f"HARPOCRATE_{name.upper()}"

            base = {
                "name": env_name,
                "type": str(field.annotation.__name__) if hasattr(field.annotation, "__name__") else "str",
                "required": field.is_required(),
            }

            if is_secret:
                sensitive.append({
                    **base,
                    "is_set": value is not None and value != "",
                    "masked_value": self._mask(value, name),
                    "criticality": self._criticality(env_name),
                    "loss_impact": self._loss_impact(env_name),
                })
            else:
                non_sensitive.append({
                    **base,
                    "value": value,
                    "default": field.default if not field.is_required() else None,
                    "current_matches_default": (
                        not field.is_required() and value == field.default
                    ),
                })

        return {
            "non_sensitive": {
                "count": len(non_sensitive),
                "fields": non_sensitive,
            },
            "sensitive": {
                "count": len(sensitive),
                "fields": sensitive,
            },
        }

    def _mask(self, value, name):
        if value is None or value == "":
            return None
        if name == "db_dsn":
            # postgresql://user:****@host:port/db
            import re
            return re.sub(r":([^:@]+)@", ":****@", value)
        # default: keep first 8 chars, mask the rest
        return value[:8] + "*" * (len(value) - 12) + value[-4:]

    def _criticality(self, name):
        return {
            "HARPOCRATE_HMAC_KEY": "highest",
            "HARPOCRATE_DB_DSN": "high",
            "HARPOCRATE_KEYCLOAK_CLIENT_SECRET": "high",
            "HARPOCRATE_BACKUP_S3_ACCESS_KEY": "medium",
            "HARPOCRATE_BACKUP_S3_SECRET_KEY": "medium",
        }.get(name, "low")

    def _loss_impact(self, name):
        return {
            "HARPOCRATE_HMAC_KEY":
                "All existing API keys become invalid; users must recreate them.",
            "HARPOCRATE_DB_DSN":
                "Application cannot connect to database; reset Postgres password if lost.",
            "HARPOCRATE_KEYCLOAK_CLIENT_SECRET":
                "JWT validation fails; regenerate client secret in Keycloak admin.",
            "HARPOCRATE_BACKUP_S3_ACCESS_KEY":
                "Cannot push/read remote backups; recreate in cloud provider.",
            "HARPOCRATE_BACKUP_S3_SECRET_KEY":
                "Cannot push/read remote backups; recreate in cloud provider.",
        }.get(name, "")

    def export_non_sensitive_json(self) -> dict:
        result = {}
        for name, field in Settings.model_fields.items():
            is_secret = (field.json_schema_extra or {}).get("is_secret", False)
            if is_secret:
                continue
            value = getattr(self.settings, name)
            result[f"HARPOCRATE_{name.upper()}"] = value
        return result

    async def export_sensitive_age_encrypted(self, age_recipient: str) -> bytes:
        """Génère un .env.age en mémoire."""
        env_lines = []
        for name, field in Settings.model_fields.items():
            is_secret = (field.json_schema_extra or {}).get("is_secret", False)
            if not is_secret:
                continue
            value = getattr(self.settings, name)
            if value is None:
                continue
            env_lines.append(f"HARPOCRATE_{name.upper()}={value}")

        env_content = "\n".join(env_lines).encode()

        # Encrypt with age
        proc = await asyncio.create_subprocess_exec(
            "age", "-r", age_recipient,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(input=env_content)
        if proc.returncode != 0:
            raise ExportError(f"age encryption failed: {stderr.decode()}")

        return stdout

    async def preview_sensitive_restore(
        self, encrypted_blob: bytes, age_private_key: str
    ) -> dict:
        # Decrypt
        proc = await asyncio.create_subprocess_exec(
            "age", "-d", "-i", "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        # Pass key via stdin first, then encrypted blob
        # ... (implementation detail: temp file for key)

        # Parse decrypted content
        backup_vars = {}
        for line in decrypted.decode().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                backup_vars[k] = v

        # Compare with current
        current_vars = {
            f"HARPOCRATE_{name.upper()}": getattr(self.settings, name)
            for name, field in Settings.model_fields.items()
            if (field.json_schema_extra or {}).get("is_secret", False)
        }

        return self._compare(current_vars, backup_vars)
```

## Critères de succès

1. ✅ `GET /admin/system/env` liste toutes les vars correctement catégorisées
2. ✅ Sensitive vars : valeurs masquées correctement (DSN, autres)
3. ✅ Sensitive vars : info `criticality` et `loss_impact` présentes
4. ✅ Export non-sensitive en JSON brut
5. ✅ Export sensible chiffré `.env.age`
6. ✅ Preview restore : comparaison correcte
7. ✅ Preview signale changement de HMAC_KEY comme warning
8. ✅ Preview ne modifie JAMAIS le runtime
9. ✅ UI 2 onglets distincts
10. ✅ UI export sensible exige reverify
11. ✅ UI preview affiche comparaison claire
12. ✅ CLI fonctionne (export/import)
13. ✅ Audit log
14. ✅ Documentation expose la procédure de restore manuelle

## Pièges connus

- **Catégorisation auto via `is_secret`** : si un dev oublie le metadata, la var fuite dans le backup public. Test obligatoire qui check les vars critiques.
- **Masking DSN** : la regex doit gérer les cas avec `?sslmode=`, port absent, user sans password, etc. Tests unitaires.
- **`age` private key reçue côté backend** : ne pas la logger, ne pas la persister, la passer via stdin pour ne pas être visible dans `argv`.
- **Restart manuel** : intentionnel. Le dev qui reprend devrait être tenté d'automatiser avec un signal SIGHUP ou un endpoint de reload — résister. Ces vars sont à modifier rarement et toujours avec attention.
- **Variables ajoutées entre versions** : si une version 0.2.0 ajoute `HARPOCRATE_NEW_FOO`, l'ancien backup ne contient pas cette var. Le preview doit le signaler comme "missing in backup", pas comme une erreur.
- **Stockage Dashlane Secure Note** : l'admin colle le contenu du `.env.age` (binaire base64) dans un Secure Note. Ou attache le fichier directement. Documenter les deux approches.
- **Loss impact est de la documentation runtime** : utile pour qu'un admin qui découvre le système comprenne ce qu'il manipule.

## Tests

- `test_list_env_categorizes_correctly`
- `test_sensitive_var_value_never_in_response`
- `test_dsn_masking_correct`
- `test_export_non_sensitive_includes_only_non_sensitive`
- `test_export_sensitive_age_encrypted_decryptable`
- `test_preview_detects_unchanged_changed_missing_extra`
- `test_preview_warns_on_hmac_key_change`
- `test_preview_never_applies`
- `test_export_sensitive_requires_reverify`
- `test_cli_env_export_import`
- `test_audit_log_for_env_operations`

## Ce qui suit

Le **lot 13** ajoute les destinations distantes S3-compatibles (R2, B2, MinIO, etc.) avec Object Lock pour le backup principal.
