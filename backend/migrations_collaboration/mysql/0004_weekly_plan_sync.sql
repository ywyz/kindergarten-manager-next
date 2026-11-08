-- Shared weekly-plan drafts and append-only confirmations.
--
-- Target: MySQL 8.4, default application database (no PostgreSQL schema).
-- Apply after 0001-0003 to the isolated test database.  The class, term and
-- teacher rows remain owned by the earlier collaboration slices.
--
-- MySQL DDL auto-commits.  If any statement fails, STOP; record the first
-- failed statement and the objects already created.  Do not rerun blindly or
-- drop shared objects; only an authorized operator may inspect/clean this
-- isolated test database.

CREATE TABLE weekly_plan_weeks (
    class_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    term_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    week_start DATE NOT NULL,
    school_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    version INT NOT NULL,
    content JSON NOT NULL,
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (class_id, term_id, week_start),
    KEY ix_weekly_week_school (school_id, week_start),
    KEY ix_weekly_week_class_school (class_id, school_id),
    KEY ix_weekly_week_term_school (term_id, school_id),
    CONSTRAINT fk_weekly_week_class_school
        FOREIGN KEY (class_id, school_id)
        REFERENCES classes(id, school_id) ON DELETE RESTRICT,
    CONSTRAINT fk_weekly_week_term_school
        FOREIGN KEY (term_id, school_id)
        REFERENCES terms(id, school_id) ON DELETE RESTRICT,
    CONSTRAINT ck_weekly_week_version CHECK (version >= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE weekly_plan_confirmations (
    id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    class_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    school_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    term_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    week_start DATE NOT NULL,
    confirmation_version INT NOT NULL,
    version INT NOT NULL,
    class_name VARCHAR(80) NOT NULL,
    grade VARCHAR(8) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    term_name VARCHAR(80) NOT NULL,
    content JSON NOT NULL,
    confirmed_by CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    confirmed_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uq_weekly_confirmation_version
        (class_id, term_id, week_start, confirmation_version),
    UNIQUE KEY uq_weekly_confirmation_saved_version
        (class_id, term_id, week_start, version),
    KEY ix_weekly_confirmation_week (class_id, term_id, week_start),
    KEY ix_weekly_confirmation_class_school (class_id, school_id),
    KEY ix_weekly_confirmation_term_school (term_id, school_id),
    KEY ix_weekly_confirmation_teacher_school (confirmed_by, school_id),
    CONSTRAINT fk_weekly_confirmation_class_school
        FOREIGN KEY (class_id, school_id)
        REFERENCES classes(id, school_id) ON DELETE RESTRICT,
    CONSTRAINT fk_weekly_confirmation_term_school
        FOREIGN KEY (term_id, school_id)
        REFERENCES terms(id, school_id) ON DELETE RESTRICT,
    CONSTRAINT fk_weekly_confirmation_teacher_school
        FOREIGN KEY (confirmed_by, school_id)
        REFERENCES teachers(id, school_id) ON DELETE RESTRICT,
    CONSTRAINT ck_weekly_confirmation_version CHECK (confirmation_version >= 1),
    CONSTRAINT ck_weekly_confirmation_saved CHECK (version >= 1),
    CONSTRAINT ck_weekly_confirmation_class_name
        CHECK (CHAR_LENGTH(class_name) BETWEEN 1 AND 80),
    CONSTRAINT ck_weekly_confirmation_term_name
        CHECK (CHAR_LENGTH(term_name) BETWEEN 1 AND 80),
    CONSTRAINT ck_weekly_confirmation_grade
        CHECK (grade IN ('small', 'middle', 'large'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE weekly_plan_operations (
    actor_teacher_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    request_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    school_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    class_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    term_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    week_start DATE NOT NULL,
    kind VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    request_fingerprint CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    result_json JSON NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (actor_teacher_id, request_id),
    KEY ix_weekly_operation_actor_school (actor_teacher_id, school_id),
    KEY ix_weekly_operation_class_school (class_id, school_id),
    KEY ix_weekly_operation_term_school (term_id, school_id),
    KEY ix_weekly_operation_actor_created (actor_teacher_id, created_at),
    KEY ix_weekly_operation_week (class_id, term_id, week_start),
    CONSTRAINT fk_weekly_operation_actor_school
        FOREIGN KEY (actor_teacher_id, school_id)
        REFERENCES teachers(id, school_id) ON DELETE RESTRICT,
    CONSTRAINT fk_weekly_operation_class_school
        FOREIGN KEY (class_id, school_id)
        REFERENCES classes(id, school_id) ON DELETE RESTRICT,
    CONSTRAINT fk_weekly_operation_term_school
        FOREIGN KEY (term_id, school_id)
        REFERENCES terms(id, school_id) ON DELETE RESTRICT,
    CONSTRAINT ck_weekly_operation_kind CHECK (kind IN ('save', 'confirm')),
    CONSTRAINT ck_weekly_operation_fingerprint
        CHECK (CHAR_LENGTH(request_fingerprint) = 64)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
