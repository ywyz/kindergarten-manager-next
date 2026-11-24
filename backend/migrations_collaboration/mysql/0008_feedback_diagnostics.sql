-- In-app online feedback 2026-11-24 adjustment: code-free submissions and
-- the optional attached diagnostics events.
--
-- Target: MySQL 8.4, default application database (no PostgreSQL schema).
-- Incremental migration: apply after 0001-0007 on the collaboration
-- database that already has feedback_submissions:
--
--   mysql --protocol=TCP -h HOST -u USER -p DBNAME \
--       < backend/migrations_collaboration/mysql/0008_feedback_diagnostics.sql
--
-- Required privileges for this step on the target database: ALTER (the one
-- existing table), plus the existing INSERT/SELECT/UPDATE/DELETE/
-- REFERENCES grants.  The service never creates or alters this table at
-- startup, and the migration is ONE atomic ALTER TABLE statement: MySQL
-- 8.4 applies all operations of a single ALTER atomically, so a mid-way
-- failure cannot leave the table half-migrated; a failed apply is
-- investigated, never auto-repaired.  The migration contains no table
-- drop, no database/schema creation and no data rewrite.  Existing rows are
-- untouched (diagnostics_events stays NULL for them and old feedback keeps
-- reading exactly as before).
--
-- Policy change (2026-11-24): a feedback submission needs no feedback code
-- and no collaboration account.  `feedback_code_hash` becomes NULL-able and
-- is stored as NULL for code-free submissions.  The optional request field
-- `feedback_code` exists only for already-released clients that still send
-- one: it is never verified against anything — the legacy
-- KGM_COLLAB_FEEDBACK_CODE variable, if the service process still holds
-- one, is ignored for submissions — and only its keyed SHA-256 digest is
-- stored (plaintext is never stored or logged).  The original SHA-256
-- length constraint semantics are preserved for the digest, now allowing
-- NULL.
--
-- The new `diagnostics_events` column stores the canonical JSON of the
-- bounded diagnostics window the teacher explicitly chose to attach (at
-- most 50 fixed-shape events: a fixed event type, a UTC second stamp, a
-- fixed result and a fixed error code from a shared finite vocabulary —
-- never input content, raw logs, exception text, paths, URLs, originals,
-- ids or credentials).  It stays NULL for submissions without an
-- attachment, including every row written before this migration.

ALTER TABLE feedback_submissions
    MODIFY feedback_code_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
    DROP CHECK ck_feedback_code_hash,
    ADD COLUMN diagnostics_events TEXT CHARACTER SET utf8mb4
        COLLATE utf8mb4_0900_ai_ci NULL,
    ADD CONSTRAINT ck_feedback_code_hash_length
        CHECK (feedback_code_hash IS NULL OR CHAR_LENGTH(feedback_code_hash) = 64),
    ADD CONSTRAINT ck_feedback_diagnostics_length
        CHECK (
            diagnostics_events IS NULL
            OR (CHAR_LENGTH(diagnostics_events) BETWEEN 2 AND 65536)
        );
