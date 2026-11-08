-- Independent MySQL 8.4 collaboration schema (first online slice).
--
-- Apply only to the fresh, independent test database selected by the
-- connection URL.  This file deliberately does NOT create a database, does
-- NOT use a fixed schema, and does NOT grant privileges.
--
-- Preflight (run separately on the same connection):
--   SELECT VERSION();                 -- must be MySQL 8.4.x
--   SELECT DATABASE();                -- must name the isolated test database
--   SELECT COUNT(*) FROM information_schema.tables
--    WHERE table_schema = DATABASE(); -- must be 0
--   SHOW GRANTS;                      -- migration account only; no global DDL
--
-- Example (the database is selected on the command line, never in this file):
--   mysql --default-character-set=utf8mb4 -h HOST -P 3306 -u USER -p DBNAME \
--       < backend/migrations_collaboration/mysql/0001_initial.sql
--
-- MySQL DDL auto-commits.  If any statement fails, STOP: record the first
-- failed statement and the objects already created.  Do not rerun this file
-- blindly and do not drop shared objects; an authorized operator must inspect
-- or clean only this isolated test database before another attempt.

SET NAMES utf8mb4 COLLATE utf8mb4_0900_ai_ci;
SET SESSION time_zone = '+00:00';
SET SESSION sql_mode = 'STRICT_ALL_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION';
SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED;

CREATE TABLE schools (
    id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    name TEXT NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    CONSTRAINT ck_school_name
        CHECK (CHAR_LENGTH(name) BETWEEN 1 AND 120)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE classes (
    id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    school_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    display_name TEXT NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    CONSTRAINT fk_classes_school FOREIGN KEY (school_id)
        REFERENCES schools(id) ON DELETE RESTRICT,
    CONSTRAINT uq_classes_id_school UNIQUE (id, school_id),
    CONSTRAINT ck_classes_display_name
        CHECK (CHAR_LENGTH(display_name) BETWEEN 1 AND 120),
    KEY ix_classes_school (school_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE teachers (
    id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    school_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    display_name TEXT NOT NULL,
    active TINYINT(1) NOT NULL DEFAULT 1,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    CONSTRAINT fk_teachers_school FOREIGN KEY (school_id)
        REFERENCES schools(id) ON DELETE RESTRICT,
    CONSTRAINT uq_teachers_id_school UNIQUE (id, school_id),
    CONSTRAINT ck_teachers_display_name
        CHECK (CHAR_LENGTH(display_name) BETWEEN 1 AND 120),
    KEY ix_teachers_school (school_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE teacher_tokens (
    id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    teacher_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    token_hash VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    expires_at DATETIME(6) NULL,
    revoked_at DATETIME(6) NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_teacher_tokens_teacher FOREIGN KEY (teacher_id)
        REFERENCES teachers(id) ON DELETE CASCADE,
    CONSTRAINT uq_teacher_tokens_hash UNIQUE (token_hash),
    CONSTRAINT ck_teacher_tokens_hash_length
        CHECK (CHAR_LENGTH(token_hash) = 64),
    KEY ix_teacher_tokens_teacher (teacher_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE teacher_class_memberships (
    teacher_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    school_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    class_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    membership_generation CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    selected_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (teacher_id),
    CONSTRAINT fk_membership_teacher_school
        FOREIGN KEY (teacher_id, school_id)
        REFERENCES teachers(id, school_id) ON DELETE CASCADE,
    CONSTRAINT fk_membership_class_school
        FOREIGN KEY (class_id, school_id)
        REFERENCES classes(id, school_id) ON DELETE RESTRICT,
    CONSTRAINT ck_membership_school_required CHECK (school_id IS NOT NULL),
    KEY ix_membership_teacher_school (teacher_id, school_id),
    KEY ix_membership_class (class_id, school_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE teacher_game_configs (
    teacher_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    school_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    class_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    version INT NOT NULL,
    payload JSON NOT NULL,
    payload_hash VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (teacher_id, school_id, class_id),
    CONSTRAINT fk_config_teacher_school
        FOREIGN KEY (teacher_id, school_id)
        REFERENCES teachers(id, school_id) ON DELETE CASCADE,
    CONSTRAINT fk_config_class_school
        FOREIGN KEY (class_id, school_id)
        REFERENCES classes(id, school_id) ON DELETE RESTRICT,
    CONSTRAINT ck_config_version_positive CHECK (version >= 1),
    CONSTRAINT ck_config_payload_hash_length
        CHECK (CHAR_LENGTH(payload_hash) = 64),
    KEY ix_config_school_class (school_id, class_id),
    KEY ix_config_class_school (class_id, school_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE operations (
    actor_teacher_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    request_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    school_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    class_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    kind VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    request_fingerprint VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    source_teacher_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
    source_version INT NULL,
    target_version INT NULL,
    result_json JSON NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (actor_teacher_id, request_id),
    CONSTRAINT fk_operations_actor_school
        FOREIGN KEY (actor_teacher_id, school_id)
        REFERENCES teachers(id, school_id) ON DELETE CASCADE,
    CONSTRAINT fk_operations_class_school
        FOREIGN KEY (class_id, school_id)
        REFERENCES classes(id, school_id) ON DELETE RESTRICT,
    CONSTRAINT fk_operations_source_school
        FOREIGN KEY (source_teacher_id, school_id)
        REFERENCES teachers(id, school_id) ON DELETE RESTRICT,
    CONSTRAINT ck_operations_kind CHECK (kind IN ('save', 'import')),
    CONSTRAINT ck_operations_source_version
        CHECK (source_version IS NULL OR source_version >= 1),
    CONSTRAINT ck_operations_target_version
        CHECK (target_version IS NULL OR target_version >= 0),
    CONSTRAINT ck_operations_binding CHECK (
        (kind = 'save' AND source_teacher_id IS NULL AND source_version IS NULL)
        OR
        (kind = 'import' AND source_teacher_id IS NOT NULL
            AND source_version IS NOT NULL AND target_version IS NOT NULL)
    ),
    KEY ix_operations_actor_school (actor_teacher_id, school_id),
    KEY ix_operations_class_school (class_id, school_id),
    KEY ix_operations_source_school (source_teacher_id, school_id),
    KEY ix_operations_actor_created (actor_teacher_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
