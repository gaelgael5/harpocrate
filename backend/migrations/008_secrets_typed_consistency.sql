-- migrations/008_secrets_typed_consistency.sql
-- LOT 17 — Trigger de cohérence type↔schema sur les secrets

-- Trigger : si type_uuid renseigné, schema_version_uuid doit avoir parent_uuid = type_uuid
CREATE OR REPLACE FUNCTION enforce_secret_schema_belongs_to_type()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.type_uuid IS NOT NULL AND NEW.schema_version_uuid IS NOT NULL THEN
        IF NOT EXISTS (
            SELECT 1 FROM secret_schemas
            WHERE version_uuid = NEW.schema_version_uuid
              AND parent_uuid = NEW.type_uuid
        ) THEN
            RAISE EXCEPTION
                'secrets.schema_version_uuid must reference a schema with parent_uuid = secrets.type_uuid'
                USING ERRCODE = '23000';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_secrets_type_schema_consistency
    BEFORE INSERT OR UPDATE OF type_uuid, schema_version_uuid ON secrets
    FOR EACH ROW EXECUTE FUNCTION enforce_secret_schema_belongs_to_type();
