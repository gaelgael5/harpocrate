-- migrations/007_user_locale.sql
-- LOT 16 — Préférence de locale utilisateur

ALTER TABLE users
    ADD COLUMN preferred_locale TEXT NOT NULL DEFAULT 'en'
        CHECK (preferred_locale IN ('en', 'fr'));
