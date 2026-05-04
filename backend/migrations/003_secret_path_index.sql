CREATE TABLE secret_path_index (
    secret_id    UUID    NOT NULL REFERENCES secrets(id) ON DELETE CASCADE,
    wallet_id    UUID    NOT NULL,
    path_segment TEXT    NOT NULL,
    depth        INTEGER NOT NULL,
    PRIMARY KEY (secret_id, depth),
    CONSTRAINT secret_path_index_depth_positive CHECK (depth > 0)
);

CREATE INDEX idx_secret_path_index_lookup
    ON secret_path_index(wallet_id, path_segment);

CREATE INDEX idx_secret_path_index_depth
    ON secret_path_index(wallet_id, depth);

-- ─── Trigger ─────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION populate_secret_path_index()
RETURNS TRIGGER AS $$
DECLARE
    parts           TEXT[];
    i               INT;
    accum           TEXT := '';
    normalized_name TEXT;
BEGIN
    DELETE FROM secret_path_index WHERE secret_id = NEW.id;

    IF position('/' in NEW.name) = 0 THEN
        RETURN NEW;
    END IF;

    normalized_name := NEW.name;
    IF NOT starts_with(normalized_name, '/') THEN
        normalized_name := '/' || normalized_name;
    END IF;

    parts := string_to_array(normalized_name, '/');

    FOR i IN 2..array_length(parts, 1) - 1 LOOP
        accum := accum || '/' || parts[i];
        INSERT INTO secret_path_index (secret_id, wallet_id, path_segment, depth)
        VALUES (NEW.id, NEW.wallet_id, accum || '/', i - 1);
    END LOOP;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_secrets_populate_path_index
    AFTER INSERT OR UPDATE OF name ON secrets
    FOR EACH ROW EXECUTE FUNCTION populate_secret_path_index();
