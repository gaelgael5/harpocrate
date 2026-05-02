# Lot 15 — Types de secrets et schemas (backend + admin UI minimale)

> **Prérequis** : Lots 00-14.

## Objectif

Introduire un **catalogue de types de secrets** versionné. Chaque type définit un format attendu (JSON Schema) et des indications de rendu (RJSF uiSchema). L'admin crée et fait évoluer ces types via une UI dédiée. **Aucune logique côté secrets dans ce lot** — on prépare le terrain ; le lot 17 branchera la consommation.

Les colonnes FK sur la table `secrets` sont ajoutées **dès maintenant** (NULLABLE, sans logique applicative) pour éviter une migration future sur cette table critique.

## Dépendances

- Lots 00-14

## Périmètre

### Inclus

- Migration `006_secret_types_schemas.sql` :
  - Tables `secret_types` et `secret_schemas`
  - Triggers de cohérence (`current_version_uuid` doit appartenir au type)
  - FK ajoutées sur `secrets` (`type_uuid`, `schema_version_uuid`) — NULLABLE
- Endpoints admin `/v1/admin/secret-types/*` (CRUD types)
- Endpoints admin `/v1/admin/secret-types/{type_uuid}/schemas/*` (CRUD versions)
- Endpoint public `GET /v1/secret-types` (liste pour les utilisateurs lors du choix de type côté UI au lot 17)
- Validation serveur : `schema_data` est un JSON Schema 2020-12 valide
- Validation serveur : `schema_ui` est un JSON valide (pas de schema strict imposé)
- UI admin :
  - `/admin/secret-types` (liste + recherche)
  - `/admin/secret-types/new` (création type)
  - `/admin/secret-types/{id}` (détail type + liste versions)
  - `/admin/secret-types/{id}/schemas/new` (création nouvelle version avec deux textareas Monaco)
  - `/admin/secret-types/{id}/schemas/{version_uuid}` (vue/édition d'une version)

### Exclus

- Pas de seed de types prédéfinis (créés à la main par l'admin pour MVP)
- Pas de validation client RJSF (lot 17)
- Pas de logique de consommation côté secrets (lot 17)
- Pas d'i18n des labels (lot 16 + amélioration au lot 17)
- Pas d'éditeur RJSF live preview (potentiel lot futur)

## Spécifications fonctionnelles

### Modèle de données

```sql
-- migrations/006_secret_types_schemas.sql

-- ─────────────────────────────────────────────────────────────────────────────
-- SECRET TYPES — Catalogue
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE secret_types (
    type_uuid                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type                            TEXT NOT NULL,
    sous_type                       TEXT NOT NULL,
    label                           TEXT,
    description                     TEXT,
    current_version_uuid            UUID,  -- FK ajoutée plus bas (cycle)

    is_system                       BOOLEAN NOT NULL DEFAULT FALSE,
    deprecated_at                   TIMESTAMPTZ,

    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by_user_id              UUID REFERENCES users(id) ON DELETE SET NULL,

    UNIQUE (type, sous_type),
    CONSTRAINT secret_types_type_not_empty CHECK (length(trim(type)) > 0),
    CONSTRAINT secret_types_sous_type_not_empty CHECK (length(trim(sous_type)) > 0),
    CONSTRAINT secret_types_type_lowercase CHECK (type = lower(trim(type))),
    CONSTRAINT secret_types_sous_type_lowercase CHECK (sous_type = lower(trim(sous_type)))
);

CREATE INDEX idx_secret_types_lookup ON secret_types(type, sous_type);
CREATE INDEX idx_secret_types_active ON secret_types(type_uuid)
    WHERE deprecated_at IS NULL;

CREATE TRIGGER trg_secret_types_updated_at BEFORE UPDATE ON secret_types
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ─────────────────────────────────────────────────────────────────────────────
-- SECRET SCHEMAS — Versions
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE secret_schemas (
    version_uuid                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_uuid                     UUID NOT NULL REFERENCES secret_types(type_uuid) ON DELETE RESTRICT,
    version                         INTEGER NOT NULL,

    schema_data                     JSONB NOT NULL,
    schema_ui                       JSONB NOT NULL DEFAULT '{}'::jsonb,

    notes                           TEXT,

    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by_user_id              UUID REFERENCES users(id) ON DELETE SET NULL,

    UNIQUE (parent_uuid, version),
    CONSTRAINT secret_schemas_version_positive CHECK (version > 0)
);

CREATE INDEX idx_secret_schemas_parent ON secret_schemas(parent_uuid, version DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- FK croisée current_version
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE secret_types
    ADD CONSTRAINT fk_secret_types_current_version
        FOREIGN KEY (current_version_uuid)
        REFERENCES secret_schemas(version_uuid)
        ON DELETE RESTRICT
        DEFERRABLE INITIALLY DEFERRED;

-- Trigger : current_version doit appartenir à ce type
CREATE OR REPLACE FUNCTION enforce_current_version_belongs_to_type()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.current_version_uuid IS NOT NULL THEN
        IF NOT EXISTS (
            SELECT 1 FROM secret_schemas
            WHERE version_uuid = NEW.current_version_uuid
              AND parent_uuid = NEW.type_uuid
        ) THEN
            RAISE EXCEPTION
                'current_version_uuid must reference a schema with parent_uuid = this type_uuid'
                USING ERRCODE = '23000';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_secret_types_current_version_consistency
    BEFORE INSERT OR UPDATE OF current_version_uuid ON secret_types
    FOR EACH ROW EXECUTE FUNCTION enforce_current_version_belongs_to_type();

-- ─────────────────────────────────────────────────────────────────────────────
-- FK ajoutées sur secrets (sans logique au lot 15)
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE secrets
    ADD COLUMN type_uuid UUID REFERENCES secret_types(type_uuid) ON DELETE RESTRICT,
    ADD COLUMN schema_version_uuid UUID REFERENCES secret_schemas(version_uuid) ON DELETE RESTRICT;

CREATE INDEX idx_secrets_type ON secrets(type_uuid) WHERE type_uuid IS NOT NULL;
CREATE INDEX idx_secrets_schema_version ON secrets(schema_version_uuid)
    WHERE schema_version_uuid IS NOT NULL;

-- Cohérence : si type_uuid renseigné, schema_version_uuid doit l'être aussi (et inversement)
ALTER TABLE secrets
    ADD CONSTRAINT secrets_type_schema_consistency CHECK (
        (type_uuid IS NULL AND schema_version_uuid IS NULL)
        OR
        (type_uuid IS NOT NULL AND schema_version_uuid IS NOT NULL)
    );
```

**Notes sur le DDL** :
- `DEFERRABLE INITIALLY DEFERRED` sur la FK `current_version_uuid` permet d'insérer dans une transaction où on crée le type (avec `current_version_uuid = NULL`), puis le schema, puis on UPDATE le type pour pointer.
- La cohérence `(type_uuid, schema_version_uuid)` matched on les deux ou aucun est applicative au lot 17 mais déjà contrainte en DB. Le lot 17 ajoutera un trigger de cohérence (le `schema_version_uuid` doit appartenir au `type_uuid` indiqué).

### API

#### `GET /v1/secret-types`

- **Auth** : JWT (pas admin)
- **Query** : `q` (recherche label/type/sous_type), `include_deprecated` (default false)
- **Réponse** :
```json
{
  "types": [
    {
      "type_uuid": "uuid",
      "type": "aws",
      "sous_type": "credentials",
      "label": "AWS Credentials",
      "description": "Access key ID + secret access key + region",
      "is_system": false,
      "deprecated_at": null,
      "current_version": {
        "version_uuid": "uuid",
        "version": 2,
        "created_at": "..."
      }
    }
  ]
}
```

Ne renvoie **pas** `schema_data` ni `schema_ui` ici (économie de bande passante). Pour les obtenir, il faut faire `GET /v1/secret-types/{type_uuid}` ou directement `GET /v1/secret-types/{type_uuid}/schemas/{version_uuid}`.

#### `GET /v1/secret-types/{type_uuid}`

- **Auth** : JWT
- **Réponse** : type + version courante avec `schema_data` et `schema_ui` complets

```json
{
  "type_uuid": "uuid",
  "type": "aws",
  "sous_type": "credentials",
  "label": "AWS Credentials",
  "description": "...",
  "is_system": false,
  "deprecated_at": null,
  "current_version": {
    "version_uuid": "uuid",
    "version": 2,
    "schema_data": { "...": "..." },
    "schema_ui": { "...": "..." },
    "notes": "Added region field",
    "created_at": "..."
  },
  "all_versions": [
    { "version_uuid": "...", "version": 2, "created_at": "..." },
    { "version_uuid": "...", "version": 1, "created_at": "..." }
  ]
}
```

#### `GET /v1/secret-types/{type_uuid}/schemas/{version_uuid}`

- **Auth** : JWT
- **Réponse** : version spécifique complète (utile pour afficher un secret qui pointe vers une vieille version)

```json
{
  "version_uuid": "uuid",
  "parent_uuid": "uuid",
  "version": 1,
  "schema_data": { "..." },
  "schema_ui": { "..." },
  "notes": "...",
  "created_at": "..."
}
```

#### `POST /v1/admin/secret-types`

- **Auth** : JWT + admin + reverify
- **Body** :
```json
{
  "type": "aws",
  "sous_type": "credentials",
  "label": "AWS Credentials",
  "description": "Access key ID + secret access key + region",
  "schema_data": { "$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "...": "..." },
  "schema_ui": { "ui:order": ["access_key_id", "secret_access_key", "region"] },
  "notes": "Initial version"
}
```
- **Effets** (en transaction unique avec `DEFERRABLE`) :
  1. INSERT secret_types avec `current_version_uuid = NULL`
  2. INSERT secret_schemas avec `version = 1` et `parent_uuid = nouveau type`
  3. UPDATE secret_types SET `current_version_uuid` = nouvelle version
- **Validations serveur** :
  - `type` et `sous_type` non vides, lowercase, trim (sinon erreur 400)
  - Couple `(type, sous_type)` unique (sinon 409 `secret_type_already_exists`)
  - `schema_data` est un JSON Schema 2020-12 valide (lib `jsonschema` Python : `Draft202012Validator.check_schema(schema_data)`)
  - `schema_ui` est un JSON valide (parsé par Pydantic en `dict`)
- **Réponse** : `201` avec le type complet
- **Audit** : `admin.secret_type_created`

#### `PATCH /v1/admin/secret-types/{type_uuid}`

- **Auth** : JWT + admin + reverify
- **Body partiel** : `label`, `description`, `current_version_uuid` (pour basculer la version courante), `deprecated_at` (passe à NOW() ou null pour annuler)
- **Validations** :
  - Si `current_version_uuid` fourni : doit appartenir à ce type (le trigger DB garantit, mais on retourne erreur métier 400 plutôt que 500)
  - `is_system = TRUE` → modification interdite sauf pour `deprecated_at`
- **Réponse** : `200`
- **Audit** : `admin.secret_type_updated`

#### `DELETE /v1/admin/secret-types/{type_uuid}`

- **Auth** : JWT + admin + reverify + confirmation textuelle
- **Body** : `{ "confirmation": "DELETE TYPE aws/credentials" }`
- **Effets** :
  - Vérifier qu'aucun secret n'utilise ce type (au lot 17, requête `SELECT 1 FROM secrets WHERE type_uuid = $1`). Au lot 15, la requête existe mais retournera toujours 0.
  - Vérifier `is_system = FALSE`
  - DELETE secret_schemas (cascade) puis DELETE secret_types
- **Réponses** :
  - `204` succès
  - `409 secret_type_in_use` avec liste des secrets concernés (par wallet, sans noms en clair)
  - `403 cannot_delete_system_type`
- **Audit** : `admin.secret_type_deleted`

#### `POST /v1/admin/secret-types/{type_uuid}/schemas`

- **Auth** : JWT + admin + reverify
- **Body** :
```json
{
  "schema_data": { "...": "..." },
  "schema_ui": { "...": "..." },
  "notes": "Added region with enum",
  "set_as_current": true
}
```
- **Effets** :
  - Calcul automatique : `version = MAX(version) + 1` pour ce parent_uuid
  - INSERT secret_schemas
  - Si `set_as_current = true` : UPDATE secret_types SET `current_version_uuid`
- **Validations** : mêmes que création initiale
- **Réponse** : `201` avec la version complète
- **Audit** : `admin.secret_schema_version_created`

#### `PATCH /v1/admin/secret-types/{type_uuid}/schemas/{version_uuid}`

- **Auth** : JWT + admin + reverify
- **Body partiel** : `notes` (uniquement)
- **Notes** : on **ne permet pas de modifier `schema_data` ou `schema_ui` d'une version existante**. Sinon les secrets qui pointent dessus risquent de devenir incohérents. Pour modifier, on crée une nouvelle version. C'est intentionnel (immutabilité des versions publiées).
- **Audit** : `admin.secret_schema_version_notes_updated`

#### `DELETE /v1/admin/secret-types/{type_uuid}/schemas/{version_uuid}`

- **Auth** : JWT + admin + reverify
- **Validations** :
  - Pas la `current_version_uuid` du type (refus 409 ; promote_other_version_first)
  - Aucun secret n'utilise cette version (refus 409 ; au lot 15 toujours OK)
- **Audit** : `admin.secret_schema_version_deleted`

### Validation JSON Schema serveur

Le serveur valide structurellement que `schema_data` est un JSON Schema. Il **ne valide pas** la conformité des secrets à ce schema (impossible : E2E).

```python
# app/services/secret_types.py
from jsonschema import Draft202012Validator, exceptions as js_exceptions


def validate_json_schema(schema_data: dict) -> None:
    """Lève ValueError si schema_data n'est pas un JSON Schema 2020-12 valide."""
    try:
        Draft202012Validator.check_schema(schema_data)
    except js_exceptions.SchemaError as e:
        raise ValueError(f"Invalid JSON Schema: {e.message}")


def validate_schema_ui(schema_ui: dict) -> None:
    """Validation minimale du schema_ui : doit être un dict, pas de structure imposée."""
    if not isinstance(schema_ui, dict):
        raise ValueError("schema_ui must be a JSON object")
    # Pas de schema imposé, on accepte tout JSON valide RJSF-compatible
```

### UI admin

#### Page `/admin/secret-types`

```
Secret types
══════════════════════════════════════════════════

[+ New type]            Search: [____________]    ☐ Show deprecated

┌────────────────────────────────────────────────────────────────┐
│ Type / Sous-type           Label                Versions  Used │
├────────────────────────────────────────────────────────────────┤
│ aws / credentials          AWS Credentials      v2 (2)   12   │
│ azure / service-principal  Azure SP             v1 (1)    3   │
│ gcp / service-account      GCP SA               v3 (3)    7   │
│ tls / certificate          TLS Certificate      v1 (1)    0   │
│ ssh / keypair-rsa          SSH RSA Keypair      v1 (1)    5   │
└────────────────────────────────────────────────────────────────┘
```

Click sur ligne → `/admin/secret-types/{id}`.

Colonne "Used" affiche le nombre de secrets utilisant ce type (sera 0 partout au lot 15, peuplé au lot 17).

#### Page `/admin/secret-types/{id}` (détail)

```
aws / credentials                                       [Edit] [Deprecate] [Delete]
═══════════════════════════════════════════════════════════════════════════

Label:        AWS Credentials
Description:  Access key ID + secret access key + region
Status:       ✓ Active
Created:      2026-05-02 by gael@yoops.org
Used by:      12 secrets across 4 wallets

─── Versions ───

Current: v2

┌──────────┬───────────────────┬───────────┬─────────────┬──────┐
│ Version  │ Created           │ Author    │ Used by     │      │
├──────────┼───────────────────┼───────────┼─────────────┼──────┤
│ ★ v2     │ 2026-04-15        │ gael@     │ 8 secrets   │ View │
│   v1     │ 2026-03-01        │ gael@     │ 4 secrets   │ View │
└──────────┴───────────────────┴───────────┴─────────────┴──────┘

[+ New version]
```

Click sur "View" → `/admin/secret-types/{id}/schemas/{version_uuid}`.

#### Page `/admin/secret-types/new` (création)

```
New secret type
═══════════════════════════════════════════════════

Type:        [aws___________________] (lowercase, no spaces)
Sous-type:   [credentials__________]

Label:       [AWS Credentials_____________________]
Description: [Access key ID + secret access key + region________]

─── Initial schema (v1) ───

[Schema data] [Schema UI]

  ┌──────────────────────────────────────────────────────────────┐
  │ {                                                            │
  │   "$schema": "https://json-schema.org/draft/2020-12/schema", │
  │   "type": "object",                                          │
  │   "title": "AWS Credentials",                                │
  │   "properties": {                                            │
  │     "access_key_id": {                                       │
  │       "type": "string",                                      │
  │       "pattern": "^AKIA[0-9A-Z]{16}$"                       │
  │     },                                                       │
  │     "...": "..."                                             │
  │   },                                                         │
  │   "required": ["access_key_id", "secret_access_key"]         │
  │ }                                                            │
  └──────────────────────────────────────────────────────────────┘

  [Validate] (validates JSON Schema syntax server-side)

Notes for v1: [_________________________________________]

[Cancel]  [Create type]
```

**Deux onglets Monaco** : un pour `schema_data` et un pour `schema_ui`. Chacun configuré en mode `json` avec syntax highlighting et validation JSON basique.

Bouton "Validate" appelle un endpoint helper :
- `POST /v1/admin/secret-types/validate-schema` `{ "schema_data": {...} }` → retourne `{ "valid": true }` ou `{ "valid": false, "error": "..." }`

#### Page `/admin/secret-types/{id}/schemas/new` (nouvelle version)

Même UI que création initiale, mais sans champs `type/sous_type` (déjà fixés). Affiche en haut :

```
New version of aws/credentials (will become v3)

Previous version: v2 — [View v2 to copy from]

[Schema data] [Schema UI]

  ┌──────────────────────────────────────────────────────────────┐
  │ ... (textarea Monaco)                                        │
  └──────────────────────────────────────────────────────────────┘

Notes for v3: [Added support for session_token field____________]

☑ Set as current version after creation

[Cancel]  [Create v3]
```

#### Page `/admin/secret-types/{id}/schemas/{version_uuid}` (vue version)

```
aws/credentials — v2                       [Set as current]  [Delete]
══════════════════════════════════════════════════════════════════

Created: 2026-04-15 by gael@yoops.org
Notes:   Added region field with enum
Status:  ★ Current version
Used by: 8 secrets

─── Schema data ───
  ┌──────────────────────────────────────┐
  │ {  ... (read-only Monaco)            │
  │ }                                    │
  └──────────────────────────────────────┘

─── Schema UI ───
  ┌──────────────────────────────────────┐
  │ {  ... (read-only Monaco)            │
  │ }                                    │
  └──────────────────────────────────────┘

[Edit notes only]  (schema_data / schema_ui are immutable)
```

Bouton "Set as current" déclenche `PATCH /v1/admin/secret-types/{id}` avec `{ "current_version_uuid": "..." }`.

## Spécifications techniques

### Structure de fichiers

```
backend/app/
├── api/v1/admin/
│   └── secret_types.py          # endpoints CRUD
├── services/
│   └── secret_types.py          # logique + validation
└── models/
    └── secret_types.py          # Pydantic schemas

frontend/src/
├── routes/admin/
│   ├── SecretTypesList.tsx
│   ├── SecretTypeDetail.tsx
│   ├── SecretTypeCreate.tsx
│   ├── SecretSchemaCreate.tsx
│   └── SecretSchemaDetail.tsx
├── api/admin/
│   └── secret_types.ts
└── components/
    └── JsonEditorMonaco.tsx     # wrapper Monaco json
```

### Pydantic models

```python
# app/models/secret_types.py
from pydantic import BaseModel, Field, field_validator
from uuid import UUID
from datetime import datetime


class SchemaUI(BaseModel):
    """Validation minimale RJSF-compatible. Accepte tout JSON object."""
    model_config = {"extra": "allow"}


class SecretTypeCreate(BaseModel):
    type: str = Field(min_length=1, max_length=64)
    sous_type: str = Field(min_length=1, max_length=64)
    label: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    schema_data: dict
    schema_ui: dict = Field(default_factory=dict)
    notes: str | None = None

    @field_validator("type", "sous_type")
    @classmethod
    def lowercase_no_spaces(cls, v: str) -> str:
        v = v.strip().lower()
        if not v.replace("-", "").replace("_", "").replace("/", "").isalnum():
            raise ValueError("Only alphanumeric, dash, underscore, slash allowed")
        return v


class SecretTypeUpdate(BaseModel):
    label: str | None = None
    description: str | None = None
    current_version_uuid: UUID | None = None
    deprecated: bool | None = None  # True → deprecated_at = NOW(), False → NULL


class SchemaVersionCreate(BaseModel):
    schema_data: dict
    schema_ui: dict = Field(default_factory=dict)
    notes: str | None = None
    set_as_current: bool = True


class SchemaVersionUpdateNotesOnly(BaseModel):
    notes: str | None = None


class SecretTypeListItem(BaseModel):
    type_uuid: UUID
    type: str
    sous_type: str
    label: str | None
    description: str | None
    is_system: bool
    deprecated_at: datetime | None
    current_version: dict | None  # { version_uuid, version, created_at }
    used_by_secrets_count: int


class SecretTypeDetail(SecretTypeListItem):
    current_version_full: dict | None  # avec schema_data et schema_ui
    all_versions: list[dict]
```

### Service et requêtes SQL

```python
# app/services/secret_types.py
import asyncpg
from uuid import UUID
from jsonschema import Draft202012Validator, exceptions as js_exc


async def create_type_with_v1(
    conn: asyncpg.Connection,
    creator_id: UUID,
    payload: SecretTypeCreate,
) -> dict:
    # Validation JSON Schema
    try:
        Draft202012Validator.check_schema(payload.schema_data)
    except js_exc.SchemaError as e:
        raise InvalidSchemaError(str(e))

    async with conn.transaction():
        # 1. Insert type avec current_version_uuid = NULL (FK deferred)
        type_row = await conn.fetchrow(
            """INSERT INTO secret_types (type, sous_type, label, description, created_by_user_id)
               VALUES ($1, $2, $3, $4, $5) RETURNING type_uuid""",
            payload.type, payload.sous_type, payload.label, payload.description, creator_id,
        )
        type_uuid = type_row["type_uuid"]

        # 2. Insert v1
        version_row = await conn.fetchrow(
            """INSERT INTO secret_schemas (parent_uuid, version, schema_data, schema_ui, notes, created_by_user_id)
               VALUES ($1, 1, $2::jsonb, $3::jsonb, $4, $5) RETURNING version_uuid""",
            type_uuid, json.dumps(payload.schema_data), json.dumps(payload.schema_ui),
            payload.notes, creator_id,
        )
        version_uuid = version_row["version_uuid"]

        # 3. Update current_version_uuid
        await conn.execute(
            "UPDATE secret_types SET current_version_uuid = $1 WHERE type_uuid = $2",
            version_uuid, type_uuid,
        )

    return {"type_uuid": type_uuid, "version_uuid": version_uuid}


async def add_new_version(
    conn: asyncpg.Connection,
    type_uuid: UUID,
    creator_id: UUID,
    payload: SchemaVersionCreate,
) -> dict:
    Draft202012Validator.check_schema(payload.schema_data)

    async with conn.transaction():
        # Lock le type pour éviter race condition sur le numéro de version
        await conn.execute("SELECT 1 FROM secret_types WHERE type_uuid = $1 FOR UPDATE", type_uuid)

        max_version = await conn.fetchval(
            "SELECT COALESCE(MAX(version), 0) FROM secret_schemas WHERE parent_uuid = $1",
            type_uuid,
        )
        new_version_num = max_version + 1

        version_row = await conn.fetchrow(
            """INSERT INTO secret_schemas (parent_uuid, version, schema_data, schema_ui, notes, created_by_user_id)
               VALUES ($1, $2, $3::jsonb, $4::jsonb, $5, $6) RETURNING version_uuid""",
            type_uuid, new_version_num, json.dumps(payload.schema_data),
            json.dumps(payload.schema_ui), payload.notes, creator_id,
        )

        if payload.set_as_current:
            await conn.execute(
                "UPDATE secret_types SET current_version_uuid = $1 WHERE type_uuid = $2",
                version_row["version_uuid"], type_uuid,
            )

    return {"version_uuid": version_row["version_uuid"], "version": new_version_num}


async def list_types(
    conn: asyncpg.Connection,
    q: str | None = None,
    include_deprecated: bool = False,
) -> list[dict]:
    where_clauses = []
    params = []
    if q:
        where_clauses.append("(type ILIKE $1 OR sous_type ILIKE $1 OR label ILIKE $1)")
        params.append(f"%{q}%")
    if not include_deprecated:
        where_clauses.append("deprecated_at IS NULL")

    where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    rows = await conn.fetch(f"""
        SELECT t.*,
               cv.version AS cv_version,
               cv.created_at AS cv_created_at,
               (SELECT COUNT(*) FROM secrets s WHERE s.type_uuid = t.type_uuid) AS used_count
        FROM secret_types t
        LEFT JOIN secret_schemas cv ON cv.version_uuid = t.current_version_uuid
        {where_sql}
        ORDER BY t.type, t.sous_type
    """, *params)

    return [_row_to_list_item(r) for r in rows]
```

### Composant JsonEditorMonaco

```typescript
// frontend/src/components/JsonEditorMonaco.tsx
import { Editor } from '@monaco-editor/react';
import { useState, useEffect } from 'react';

export function JsonEditorMonaco({
  value,
  onChange,
  readOnly = false,
  height = '400px',
}: {
  value: string;
  onChange?: (v: string) => void;
  readOnly?: boolean;
  height?: string;
}) {
  return (
    <Editor
      height={height}
      language="json"
      value={value}
      onChange={(v) => onChange?.(v ?? '')}
      options={{
        readOnly,
        minimap: { enabled: false },
        formatOnPaste: true,
        scrollBeyondLastLine: false,
        tabSize: 2,
      }}
    />
  );
}
```

### Endpoint helper de validation

```python
@router.post("/admin/secret-types/validate-schema")
async def validate_schema_endpoint(
    body: dict,
    user: CurrentUser = Depends(require_admin),
):
    schema_data = body.get("schema_data")
    if not isinstance(schema_data, dict):
        return {"valid": False, "error": "schema_data must be an object"}
    try:
        Draft202012Validator.check_schema(schema_data)
        return {"valid": True}
    except js_exc.SchemaError as e:
        return {"valid": False, "error": str(e)}
```

## Critères de succès

1. ✅ Migration applique proprement, FK deferrable fonctionne
2. ✅ Trigger empêche `current_version_uuid` qui n'appartient pas au type
3. ✅ Création type + v1 dans une transaction unique réussie
4. ✅ Couple `(type, sous_type)` UNIQUE respecté (409 sur doublon)
5. ✅ Validation JSON Schema 2020-12 fonctionne (rejet schema invalide)
6. ✅ Endpoint helper `validate-schema` retourne valid/invalid
7. ✅ `POST /admin/secret-types/{id}/schemas` calcule version+1 correctement (avec lock)
8. ✅ `set_as_current=true` met à jour le pointeur
9. ✅ PATCH `current_version_uuid` vers une version d'un autre type → 400
10. ✅ DELETE type avec secrets en cours → 409 (test fictif au lot 15, vrai au lot 17)
11. ✅ DELETE schema_version qui est current → 409
12. ✅ DELETE schema_version d'un type system → 403
13. ✅ Modification de `schema_data` d'une version existante → impossible (pas d'endpoint)
14. ✅ Page liste types avec recherche
15. ✅ Page création type avec deux Monaco editors (data + ui)
16. ✅ Page nouvelle version pré-remplie depuis la version précédente
17. ✅ Bouton "Validate" appelle l'endpoint et affiche résultat
18. ✅ Page détail version en read-only
19. ✅ Audit log pour toutes les opérations
20. ✅ Colonnes `secrets.type_uuid` et `secrets.schema_version_uuid` ajoutées (nullable, sans logique)

## Pièges connus

- **FK circulaire deferrable** : sans `DEFERRABLE INITIALLY DEFERRED`, on ne peut pas insérer le type puis le schema dans la même transaction. Bien tester que les autres FK ne sont pas accidentellement deferrable.
- **Race condition sur le numéro de version** : sans le `SELECT FOR UPDATE` sur le type, deux requêtes concurrentes peuvent calculer `MAX(version)+1 = N` et planter sur l'UNIQUE.
- **`schema_data` immutable une fois publié** : intentionnel. Si l'admin se rend compte d'une typo, il doit créer une v2. Ça évite que des secrets existants deviennent silencieusement non-conformes.
- **Validation JSON Schema lib `jsonschema`** : à pinner version (>= 4.0). Important pour `Draft202012Validator`.
- **`schema_ui` non strictement validé** : on accepte tout JSON. C'est intentionnel — RJSF a un vocabulaire mais des extensions sont possibles. La validation se fera côté UI au lot 17 (RJSF lui-même tolère beaucoup de variations).
- **Recherche `q` ILIKE** : performance OK pour quelques centaines de types. Si volume explose, indexer trigram (`pg_trgm`).
- **`is_system` non modifiable** : seul le code (seed futur) peut le mettre à TRUE. Pas exposé via API.
- **Suppression avec dépendances** : compter les secrets utilisateurs avant DELETE. Au lot 15 toujours 0, mais le code doit être prêt. Test Postgres `EXISTS` rapide.
- **Versions historiques accessibles** : un secret au lot 17 pourra pointer vers une v1 même si current est v3. Endpoint `GET /secret-types/{id}/schemas/{version_uuid}` doit retourner v1 sans condition.
- **`label` en anglais MVP** : prévu. Au lot 16 on i18n l'UI mais pas les contenus user-defined.
- **Monaco loader** : Monaco peut être lourd à charger. Code-splitting recommandé. Utiliser `@monaco-editor/react` qui gère ça nativement.
- **Validation côté UI avant envoi** : double validation (UI + serveur). L'UI évite des allers-retours, le serveur est la source de vérité.

## Tests

### Backend

- `test_create_type_with_v1_in_transaction`
- `test_create_type_duplicate_409`
- `test_create_type_invalid_json_schema_400`
- `test_create_type_lowercase_validation`
- `test_add_new_version_increments_correctly`
- `test_concurrent_new_version_no_collision` (avec asyncio.gather)
- `test_set_as_current_updates_pointer`
- `test_patch_current_version_wrong_type_400`
- `test_patch_current_version_immutable_for_system`
- `test_delete_type_with_secrets_409` (mock)
- `test_delete_current_version_409`
- `test_delete_system_type_403`
- `test_validate_schema_endpoint_valid`
- `test_validate_schema_endpoint_invalid`
- `test_get_secret_types_excludes_deprecated_by_default`
- `test_get_secret_type_returns_current_with_full_data`
- `test_get_specific_version_returns_data`
- `test_audit_log_for_all_operations`
- `test_secrets_columns_nullable_at_lot_15`

### Frontend

- `test_secret_types_list_loads`
- `test_search_filter_works`
- `test_create_type_form_validation`
- `test_monaco_editor_renders`
- `test_validate_button_calls_api`
- `test_create_type_with_invalid_schema_shows_error`
- `test_new_version_form_prefills_from_previous`
- `test_view_version_readonly`

## Ce qui suit

Le **lot 16** ajoute l'i18n FR/EN sur l'UI complète (lots 11 + 12 + 15).
