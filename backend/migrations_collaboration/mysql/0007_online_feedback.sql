-- In-app online feedback: idempotent submissions and admin processing state.
--
-- Target: MySQL 8.4, default application database (no PostgreSQL schema).
-- Apply after migrations 0001-0006 on the isolated collaboration database:
--
--   mysql --protocol=TCP -h HOST -u USER -p DBNAME \
--       < backend/migrations_collaboration/mysql/0007_online_feedback.sql
--
-- Required privileges for this step on the target database: CREATE (new
-- table), plus the existing INSERT/SELECT/UPDATE/DELETE/REFERENCES grants.
-- The table references admin_users(id), which already exists from 0002;
-- the applying account needs REFERENCES on it.  The service never creates or
-- alters this table at startup, and the migration contains no DROP and no
-- database/schema creation: it stops on any partial DDL so a failed apply is
-- investigated, never auto-repaired.
--
-- Runtime configuration (set on the collaboration service process, reported
-- separately for deployment): KGM_COLLAB_FEEDBACK_CODE holds the
-- organizer-distributed feedback code.  Leaving it empty disables the
-- in-app feedback entry (the API answers 503 FEEDBACK_NOT_CONFIGURED); the
-- code is verified as a keyed digest and never logged or stored in
-- plaintext.
--
-- Plaintext feedback codes are never stored; only a keyed SHA-256 digest is
-- persisted.  Submission content is the teacher-typed text, optional contact
-- information and the application version string only.  `request_id` is the
-- idempotency key: a retried submission resolves against the committed row
-- and never enters the admin list twice.

CREATE TABLE feedback_submissions (
    id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    request_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    content_fingerprint CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    content TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
    contact VARCHAR(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL,
    app_version VARCHAR(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL,
    feedback_code_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    status VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'new',
    handled_by_admin_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
    handled_at DATETIME(6) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uq_feedback_request_id (request_id),
    KEY ix_feedback_status_created (status, created_at),
    KEY ix_feedback_created (created_at),
    CONSTRAINT fk_feedback_handled_by_admin FOREIGN KEY (handled_by_admin_id)
        REFERENCES admin_users(id) ON DELETE RESTRICT,
    CONSTRAINT ck_feedback_status CHECK (status IN ('new', 'processing', 'resolved')),
    CONSTRAINT ck_feedback_content_length CHECK (CHAR_LENGTH(content) BETWEEN 1 AND 12000),
    CONSTRAINT ck_feedback_contact_length
        CHECK (contact IS NULL OR (CHAR_LENGTH(contact) BETWEEN 1 AND 200)),
    CONSTRAINT ck_feedback_app_version_length
        CHECK (app_version IS NULL OR (CHAR_LENGTH(app_version) BETWEEN 1 AND 100)),
    CONSTRAINT ck_feedback_code_hash CHECK (CHAR_LENGTH(feedback_code_hash) = 64),
    CONSTRAINT ck_feedback_fingerprint CHECK (CHAR_LENGTH(content_fingerprint) = 64)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
