-- Online collaboration term registry and same-class promotion.
--
-- Target: MySQL 8.4, default application database (no PostgreSQL schema).
-- Apply only after 0001 and 0002 to the isolated test database, with the
-- database selected on the connection:
--
--   mysql --protocol=TCP -h HOST -u USER -p DBNAME \
--       < backend/migrations_collaboration/mysql/0003_class_promotion.sql
--
-- This is a forward-only additive migration.  It does not alter existing
-- classes, teachers, memberships or configuration rows, does not create a
-- database and does not grant privileges.  MySQL DDL auto-commits: if any
-- statement fails, STOP; record the first failed statement and the objects
-- already created, and let an authorized operator inspect/clean only this
-- isolated test database before another attempt.

CREATE TABLE terms (
    id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    school_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    name VARCHAR(80) NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uq_terms_id_school (id, school_id),
    KEY ix_terms_school_start (school_id, start_date),
    CONSTRAINT fk_terms_school FOREIGN KEY (school_id)
        REFERENCES schools(id) ON DELETE RESTRICT,
    CONSTRAINT ck_terms_name CHECK (CHAR_LENGTH(name) BETWEEN 1 AND 80),
    CONSTRAINT ck_terms_date_order CHECK (start_date <= end_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE class_promotion_states (
    class_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    school_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    class_number INT NOT NULL,
    base_grade VARCHAR(8) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    version INT NOT NULL DEFAULT 1,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (class_id),
    KEY ix_promotion_state_school (school_id),
    KEY ix_promotion_state_class_school (class_id, school_id),
    CONSTRAINT fk_promotion_state_class_school
        FOREIGN KEY (class_id, school_id)
        REFERENCES classes(id, school_id) ON DELETE RESTRICT,
    CONSTRAINT ck_promotion_state_number
        CHECK (class_number BETWEEN 1 AND 99),
    CONSTRAINT ck_promotion_state_base_grade
        CHECK (base_grade IN ('small', 'middle', 'large')),
    CONSTRAINT ck_promotion_state_version CHECK (version >= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE class_promotion_history (
    id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    class_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    school_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    term_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    grade VARCHAR(8) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    version_after INT NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uq_promotion_history_class_term (class_id, term_id),
    KEY ix_promotion_history_class_school (class_id, school_id),
    KEY ix_promotion_history_term_school (term_id, school_id),
    CONSTRAINT fk_promotion_history_class_school
        FOREIGN KEY (class_id, school_id)
        REFERENCES classes(id, school_id) ON DELETE RESTRICT,
    CONSTRAINT fk_promotion_history_term_school
        FOREIGN KEY (term_id, school_id)
        REFERENCES terms(id, school_id) ON DELETE RESTRICT,
    CONSTRAINT ck_promotion_history_grade
        CHECK (grade IN ('small', 'middle', 'large')),
    CONSTRAINT ck_promotion_history_version CHECK (version_after >= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE class_promotion_operations (
    actor_teacher_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    request_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    school_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    class_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    effective_term_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    target_grade VARCHAR(8) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    expected_version INT NOT NULL,
    result_version INT NOT NULL,
    result_grade VARCHAR(8) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    result_class_name VARCHAR(80) NOT NULL,
    request_fingerprint CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (actor_teacher_id, request_id),
    KEY ix_promotion_operation_actor_school (actor_teacher_id, school_id),
    KEY ix_promotion_operation_class_school (class_id, school_id),
    KEY ix_promotion_operation_term_school (effective_term_id, school_id),
    KEY ix_promotion_operation_actor_created (actor_teacher_id, created_at),
    KEY ix_promotion_operation_class_created (class_id, created_at),
    CONSTRAINT fk_promotion_operation_actor_school
        FOREIGN KEY (actor_teacher_id, school_id)
        REFERENCES teachers(id, school_id) ON DELETE RESTRICT,
    CONSTRAINT fk_promotion_operation_class_school
        FOREIGN KEY (class_id, school_id)
        REFERENCES classes(id, school_id) ON DELETE RESTRICT,
    CONSTRAINT fk_promotion_operation_term_school
        FOREIGN KEY (effective_term_id, school_id)
        REFERENCES terms(id, school_id) ON DELETE RESTRICT,
    CONSTRAINT ck_promotion_operation_target_grade
        CHECK (target_grade IN ('small', 'middle', 'large')),
    CONSTRAINT ck_promotion_operation_result_grade
        CHECK (result_grade IN ('small', 'middle', 'large')),
    CONSTRAINT ck_promotion_operation_name
        CHECK (CHAR_LENGTH(result_class_name) BETWEEN 1 AND 80),
    CONSTRAINT ck_promotion_operation_fingerprint
        CHECK (CHAR_LENGTH(request_fingerprint) = 64),
    CONSTRAINT ck_promotion_operation_versions
        CHECK (expected_version >= 1 AND result_version >= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
