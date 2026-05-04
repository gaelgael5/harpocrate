-- migrations/006_secret_types_schemas.sql
-- LOT 15 — Catalogue de types de secrets versionnés

-- ─────────────────────────────────────────────────────────────────────────────
-- SECRET TYPES — Catalogue
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE secret_types (
    type_uuid                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type                            TEXT NOT NULL,
    sous_type                       TEXT NOT NULL,
    label                           TEXT,
    description                     TEXT,
    current_version_uuid            UUID,  -- FK croisée ajoutée après secret_schemas

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
-- FK croisée current_version (deferrable pour permettre insert+update en 1 tx)
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE secret_types
    ADD CONSTRAINT fk_secret_types_current_version
        FOREIGN KEY (current_version_uuid)
        REFERENCES secret_schemas(version_uuid)
        ON DELETE RESTRICT
        DEFERRABLE INITIALLY DEFERRED;

-- Trigger : current_version_uuid doit appartenir à ce type
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
-- FK ajoutées sur secrets (nullable, sans logique au lot 15)
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE secrets
    ADD COLUMN type_uuid UUID REFERENCES secret_types(type_uuid) ON DELETE RESTRICT,
    ADD COLUMN schema_version_uuid UUID REFERENCES secret_schemas(version_uuid) ON DELETE RESTRICT;

CREATE INDEX idx_secrets_type ON secrets(type_uuid) WHERE type_uuid IS NOT NULL;
CREATE INDEX idx_secrets_schema_version ON secrets(schema_version_uuid)
    WHERE schema_version_uuid IS NOT NULL;

-- Cohérence : les deux NULL ou les deux NOT NULL
ALTER TABLE secrets
    ADD CONSTRAINT secrets_type_schema_consistency CHECK (
        (type_uuid IS NULL AND schema_version_uuid IS NULL)
        OR
        (type_uuid IS NOT NULL AND schema_version_uuid IS NOT NULL)
    );
