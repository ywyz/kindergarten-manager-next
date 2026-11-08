-- Independent online-collaboration schema.
--
-- This migration is intentionally separate from the local SQLite/Alembic
-- chain and from the retired v1 MySQL schema.  Apply it only to the
-- PostgreSQL database configured for this service.  ``psql`` takes the
-- standard ``postgresql://`` URL, while the service itself must use the
-- SQLAlchemy ``postgresql+psycopg://`` form:
--
--   psql "postgresql://USER:PASSWORD@HOST:5432/DBNAME" \
--       -f backend/migrations_collaboration/0001_initial.sql
--
-- The service never creates or alters these tables at startup.

BEGIN;

CREATE SCHEMA IF NOT EXISTS collaboration;

CREATE TABLE collaboration.schools (
    id uuid PRIMARY KEY,
    name text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_school_name CHECK (length(name) BETWEEN 1 AND 120)
);

CREATE TABLE collaboration.classes (
    id uuid PRIMARY KEY,
    school_id uuid NOT NULL,
    display_name text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_classes_school FOREIGN KEY (school_id)
        REFERENCES collaboration.schools(id) ON DELETE RESTRICT,
    CONSTRAINT uq_classes_id_school UNIQUE (id, school_id),
    CONSTRAINT ck_classes_display_name
        CHECK (length(display_name) BETWEEN 1 AND 120)
);

CREATE TABLE collaboration.teachers (
    id uuid PRIMARY KEY,
    school_id uuid NOT NULL,
    display_name text NOT NULL,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_teachers_school FOREIGN KEY (school_id)
        REFERENCES collaboration.schools(id) ON DELETE RESTRICT,
    CONSTRAINT uq_teachers_id_school UNIQUE (id, school_id),
    CONSTRAINT ck_teachers_display_name
        CHECK (length(display_name) BETWEEN 1 AND 120)
);

CREATE TABLE collaboration.teacher_tokens (
    id uuid PRIMARY KEY,
    teacher_id uuid NOT NULL,
    token_hash character varying(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz,
    revoked_at timestamptz,
    CONSTRAINT fk_teacher_tokens_teacher FOREIGN KEY (teacher_id)
        REFERENCES collaboration.teachers(id) ON DELETE CASCADE,
    CONSTRAINT uq_teacher_tokens_hash UNIQUE (token_hash),
    CONSTRAINT ck_teacher_tokens_hash_length CHECK (length(token_hash) = 64)
);

CREATE INDEX ix_teacher_tokens_teacher
    ON collaboration.teacher_tokens (teacher_id);

CREATE TABLE collaboration.teacher_class_memberships (
    teacher_id uuid PRIMARY KEY,
    school_id uuid NOT NULL,
    class_id uuid NOT NULL,
    membership_generation uuid NOT NULL,
    selected_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_membership_teacher_school
        FOREIGN KEY (teacher_id, school_id)
        REFERENCES collaboration.teachers(id, school_id) ON DELETE CASCADE,
    CONSTRAINT fk_membership_class_school
        FOREIGN KEY (class_id, school_id)
        REFERENCES collaboration.classes(id, school_id) ON DELETE RESTRICT,
    CONSTRAINT ck_membership_school_required CHECK (school_id IS NOT NULL)
);

CREATE INDEX ix_membership_class
    ON collaboration.teacher_class_memberships (school_id, class_id);

CREATE TABLE collaboration.teacher_game_configs (
    teacher_id uuid NOT NULL,
    school_id uuid NOT NULL,
    class_id uuid NOT NULL,
    version integer NOT NULL,
    payload jsonb NOT NULL,
    payload_hash character varying(64) NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (teacher_id, school_id, class_id),
    CONSTRAINT fk_config_teacher_school
        FOREIGN KEY (teacher_id, school_id)
        REFERENCES collaboration.teachers(id, school_id) ON DELETE CASCADE,
    CONSTRAINT fk_config_class_school
        FOREIGN KEY (class_id, school_id)
        REFERENCES collaboration.classes(id, school_id) ON DELETE RESTRICT,
    CONSTRAINT ck_config_version_positive CHECK (version >= 1),
    CONSTRAINT ck_config_payload_hash_length
        CHECK (length(payload_hash) = 64)
);

CREATE INDEX ix_config_school_class
    ON collaboration.teacher_game_configs (school_id, class_id);

CREATE TABLE collaboration.operations (
    actor_teacher_id uuid NOT NULL,
    request_id uuid NOT NULL,
    school_id uuid NOT NULL,
    class_id uuid NOT NULL,
    kind character varying(16) NOT NULL,
    request_fingerprint character varying(64) NOT NULL,
    source_teacher_id uuid,
    source_version integer,
    target_version integer,
    result_json jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (actor_teacher_id, request_id),
    CONSTRAINT fk_operations_actor_school
        FOREIGN KEY (actor_teacher_id, school_id)
        REFERENCES collaboration.teachers(id, school_id) ON DELETE CASCADE,
    CONSTRAINT fk_operations_class_school
        FOREIGN KEY (class_id, school_id)
        REFERENCES collaboration.classes(id, school_id) ON DELETE RESTRICT,
    CONSTRAINT fk_operations_source_school
        FOREIGN KEY (source_teacher_id, school_id)
        REFERENCES collaboration.teachers(id, school_id) ON DELETE RESTRICT,
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
    )
);

CREATE INDEX ix_operations_actor_created
    ON collaboration.operations (actor_teacher_id, created_at);

COMMIT;
