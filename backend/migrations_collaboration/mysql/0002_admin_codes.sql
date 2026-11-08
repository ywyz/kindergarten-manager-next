-- Online collaboration administrator login and one-time teacher codes.
--
-- Target: MySQL 8.4, default application database (no PostgreSQL schema).
-- Apply after the base collaboration migration on an isolated test database:
--
--   mysql --protocol=TCP -h HOST -u USER -p DBNAME \
--       < backend/migrations_collaboration/mysql/0002_admin_codes.sql
--
-- The service never creates or alters these tables at startup.  Plaintext
-- passwords, session tokens, CSRF tokens and redemption codes are never
-- stored here; only scrypt/keyed-SHA-256 values are persisted.

CREATE TABLE admin_users (
    id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    username VARCHAR(80) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
    password_hash VARCHAR(255) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    failed_attempts INT NOT NULL DEFAULT 0,
    locked_until DATETIME(6) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uq_admin_users_username (username),
    CONSTRAINT ck_admin_users_username
        CHECK (CHAR_LENGTH(username) BETWEEN 3 AND 80),
    CONSTRAINT ck_admin_users_failed_attempts CHECK (failed_attempts >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE admin_sessions (
    id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    admin_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    token_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    csrf_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    expires_at DATETIME(6) NOT NULL,
    revoked_at DATETIME(6) NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_admin_sessions_token_hash (token_hash),
    KEY ix_admin_sessions_admin (admin_id),
    CONSTRAINT fk_admin_sessions_admin FOREIGN KEY (admin_id)
        REFERENCES admin_users(id) ON DELETE CASCADE,
    CONSTRAINT ck_admin_sessions_token_hash CHECK (CHAR_LENGTH(token_hash) = 64),
    CONSTRAINT ck_admin_sessions_csrf_hash CHECK (CHAR_LENGTH(csrf_hash) = 64)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE admin_codes (
    id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    code_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    purpose VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    teacher_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    school_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    created_by_admin_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    expires_at DATETIME(6) NOT NULL,
    used_at DATETIME(6) NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_admin_codes_code_hash (code_hash),
    KEY ix_admin_codes_teacher (teacher_id, purpose, created_at),
    KEY ix_admin_codes_school (school_id, created_at),
    CONSTRAINT fk_admin_codes_teacher_school FOREIGN KEY (teacher_id, school_id)
        REFERENCES teachers(id, school_id) ON DELETE RESTRICT,
    CONSTRAINT fk_admin_codes_school FOREIGN KEY (school_id)
        REFERENCES schools(id) ON DELETE RESTRICT,
    CONSTRAINT fk_admin_codes_admin FOREIGN KEY (created_by_admin_id)
        REFERENCES admin_users(id) ON DELETE RESTRICT,
    CONSTRAINT ck_admin_codes_purpose CHECK (purpose IN ('join', 'recovery')),
    CONSTRAINT ck_admin_codes_hash CHECK (CHAR_LENGTH(code_hash) = 64)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
