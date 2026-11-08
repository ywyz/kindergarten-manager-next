-- Signed prompt-release drafts, preview/stable channels and rollbacks.
--
-- Target: MySQL 8.4, default application database (no PostgreSQL schema).
-- Apply after 0001-0004 to the isolated test database.  This migration only
-- adds three tables and one singleton state row; it does not alter existing
-- tables, create a database, grant privileges or touch package files.
--
-- MySQL DDL auto-commits.  If any statement fails, STOP; record the first
-- failed statement and the objects already created.  Do not rerun blindly or
-- drop shared objects; only an authorized operator may inspect/clean this
-- isolated test database.

CREATE TABLE prompt_release_state (
    id INT NOT NULL,
    last_sequence INT NOT NULL,
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    CONSTRAINT ck_prompt_release_state_singleton CHECK (id = 1),
    CONSTRAINT ck_prompt_release_state_sequence CHECK (last_sequence >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT INTO prompt_release_state (id, last_sequence)
VALUES (1, 0);

CREATE TABLE prompt_release_drafts (
    id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    notes VARCHAR(500) NOT NULL,
    base_stable_sequence INT NULL,
    changes JSON NOT NULL,
    content JSON NOT NULL,
    revisions JSON NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    KEY ix_prompt_release_draft_created (created_at),
    CONSTRAINT ck_prompt_release_draft_notes
        CHECK (CHAR_LENGTH(notes) <= 500),
    CONSTRAINT ck_prompt_release_draft_base
        CHECK (base_stable_sequence IS NULL OR base_stable_sequence >= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE prompt_releases (
    release_sequence INT NOT NULL,
    channel VARCHAR(8) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    draft_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
    notes VARCHAR(500) NULL,
    rollback_of INT NULL,
    expected_stable_sequence INT NULL,
    content JSON NOT NULL,
    revisions JSON NOT NULL,
    package_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    package_byte_size INT NOT NULL,
    key_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    manifest_signature CHAR(88) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (release_sequence),
    UNIQUE KEY uq_prompt_release_channel_draft (channel, draft_id),
    UNIQUE KEY uq_prompt_release_rollback
        (rollback_of, expected_stable_sequence),
    KEY ix_prompt_release_channel_sequence (channel, release_sequence),
    KEY ix_prompt_release_draft (draft_id),
    KEY ix_prompt_release_rollback (rollback_of),
    CONSTRAINT fk_prompt_release_draft
        FOREIGN KEY (draft_id)
        REFERENCES prompt_release_drafts(id) ON DELETE RESTRICT,
    CONSTRAINT fk_prompt_release_rollback
        FOREIGN KEY (rollback_of)
        REFERENCES prompt_releases(release_sequence) ON DELETE RESTRICT,
    CONSTRAINT ck_prompt_release_sequence CHECK (release_sequence >= 1),
    CONSTRAINT ck_prompt_release_channel
        CHECK (channel IN ('preview', 'stable')),
    CONSTRAINT ck_prompt_release_notes
        CHECK (notes IS NULL OR CHAR_LENGTH(notes) <= 500),
    CONSTRAINT ck_prompt_release_sha
        CHECK (CHAR_LENGTH(package_sha256) = 64),
    CONSTRAINT ck_prompt_release_size CHECK (package_byte_size > 0),
    CONSTRAINT ck_prompt_release_key
        CHECK (CHAR_LENGTH(key_id) BETWEEN 1 AND 64),
    CONSTRAINT ck_prompt_release_manifest_signature
        CHECK (CHAR_LENGTH(manifest_signature) = 88),
    CONSTRAINT ck_prompt_release_rollback
        CHECK (rollback_of IS NULL OR rollback_of >= 1),
    CONSTRAINT ck_prompt_release_expected_stable
        CHECK (expected_stable_sequence IS NULL
               OR expected_stable_sequence >= 1),
    CONSTRAINT ck_prompt_release_shape
        CHECK (
            (channel = 'preview' AND draft_id IS NOT NULL
             AND rollback_of IS NULL AND expected_stable_sequence IS NULL)
            OR
            (channel = 'stable' AND (
                (draft_id IS NOT NULL AND rollback_of IS NULL
                 AND expected_stable_sequence IS NULL)
                OR
                (draft_id IS NULL AND rollback_of IS NOT NULL
                 AND expected_stable_sequence IS NOT NULL)
            ))
        )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
