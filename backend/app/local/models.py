"""Local (desktop) SQLite models.

Mirrors the D1A spec §3 objects and constraints. All comparisons use
native TEXT semantics (SQLite default is binary/case-sensitive), dates are
ISO dates and timestamps are UTC. The effective-plan uniqueness is a
partial unique index on ``(class_id, plan_date) WHERE deleted_at IS NULL``
(no redundant ``effective_date`` column).
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    LargeBinary,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.local.base import LocalBase, utc_now


class LocalProfile(LocalBase):
    """The single local teacher profile."""

    __tablename__ = "local_profile"
    __table_args__ = (
        CheckConstraint("singleton = 1", name="ck_local_profile_singleton"),
        CheckConstraint(
            "length(display_name) BETWEEN 1 AND 80",
            name="ck_local_profile_display_name",
        ),
        UniqueConstraint("singleton", name="uq_local_profile_singleton"),
    )

    # Random opaque stable ID (22 url-safe characters); never regenerated.
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    singleton: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalClass(LocalBase):
    """One local class. D1A only creates it during initialization."""

    __tablename__ = "local_classes"
    __table_args__ = (
        CheckConstraint(
            "grade IN ('small', 'middle', 'large')",
            name="ck_local_classes_grade",
        ),
        CheckConstraint(
            "length(name) BETWEEN 1 AND 80", name="ck_local_classes_name"
        ),
        CheckConstraint(
            "caregiver_name IS NULL OR length(caregiver_name) BETWEEN 1 AND 80",
            name="ck_local_classes_caregiver_name",
        ),
        UniqueConstraint("name", name="uq_local_classes_name"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    grade: Mapped[str] = mapped_column(String(20), nullable=False)
    # Ordered, duplicate-preserving header names; service validation enforces
    # at most 100 items, 1..80 characters each and 32 KiB canonical JSON.
    header_teacher_names: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    caregiver_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalTerm(LocalBase):
    """One local term; its current-calendar-revision pointer is deferred FK."""

    __tablename__ = "local_terms"
    __table_args__ = (
        CheckConstraint("start_date <= end_date", name="ck_local_terms_date_order"),
        CheckConstraint("length(name) BETWEEN 1 AND 80", name="ck_local_terms_name"),
        ForeignKeyConstraint(
            ["id", "current_calendar_revision_id"],
            ["local_calendar_revisions.term_id", "local_calendar_revisions.id"],
            name="fk_local_terms_current_revision",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Non-null since revision 20261012_0002_local: every term references its
    # first (current) calendar revision; the composite FK is deferred so the
    # term row and its first revision commit atomically.
    current_calendar_revision_id: Mapped[str] = mapped_column(
        String(32), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalCalendarRevision(LocalBase):
    """Immutable calendar snapshot header; stored revisions are never recomputed."""

    __tablename__ = "local_calendar_revisions"
    __table_args__ = (
        CheckConstraint(
            "revision_no >= 1", name="ck_local_calendar_revisions_revision_no"
        ),
        UniqueConstraint(
            "term_id", "revision_no",
            name="uq_local_calendar_revisions_term_revision",
        ),
        # Candidate key referenced by local_terms and local_daily_plans so a
        # revision pointer can only reference a revision owned by that term.
        UniqueConstraint(
            "term_id", "id", name="uq_local_calendar_revisions_term_id"
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    term_id: Mapped[str] = mapped_column(
        ForeignKey("local_terms.id"), nullable=False
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    library_version: Mapped[str] = mapped_column(String(50), nullable=False)
    created_by: Mapped[str] = mapped_column(
        ForeignKey("local_profile.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalCalendarDay(LocalBase):
    """One persisted calendar day of one revision (complete snapshot)."""

    __tablename__ = "local_calendar_days"
    __table_args__ = (
        CheckConstraint(
            "base_state IN ('teaching', 'non_teaching', 'unknown')",
            name="ck_local_calendar_days_base_state",
        ),
        CheckConstraint(
            "override_state IS NULL OR override_state IN ('teaching', 'non_teaching')",
            name="ck_local_calendar_days_override_state",
        ),
        CheckConstraint(
            "effective_state IN ('teaching', 'non_teaching', 'unknown')",
            name="ck_local_calendar_days_effective_state",
        ),
        CheckConstraint(
            "override_state IS NULL OR "
            "(override_reason IS NOT NULL "
            "AND length(trim(override_reason)) BETWEEN 1 AND 200)",
            name="ck_local_calendar_days_override_reason",
        ),
        CheckConstraint(
            "effective_state = COALESCE(override_state, base_state)",
            name="ck_local_calendar_days_effective",
        ),
    )

    revision_id: Mapped[str] = mapped_column(
        ForeignKey("local_calendar_revisions.id"), primary_key=True
    )
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    base_state: Mapped[str] = mapped_column(String(20), nullable=False)
    base_library_version: Mapped[str] = mapped_column(String(50), nullable=False)
    override_state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    override_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    effective_state: Mapped[str] = mapped_column(String(20), nullable=False)


class LocalDailyPlan(LocalBase):
    """Daily plan header; identity/date/header snapshot are immutable."""

    __tablename__ = "local_daily_plans"
    __table_args__ = (
        CheckConstraint(
            "current_content_version >= 1",
            name="ck_local_daily_plans_current_content_version",
        ),
        CheckConstraint("week_number >= 1", name="ck_local_daily_plans_week_number"),
        CheckConstraint(
            "weekday BETWEEN 1 AND 7", name="ck_local_daily_plans_weekday"
        ),
        CheckConstraint(
            "length(class_name) BETWEEN 1 AND 80",
            name="ck_local_daily_plans_class_name",
        ),
        CheckConstraint(
            "school_name IS NULL OR length(school_name) BETWEEN 1 AND 120",
            name="ck_local_daily_plans_school_name",
        ),
        # Same-day effective uniqueness; soft-deleted rows leave the index.
        Index(
            "uq_local_daily_plans_effective_class_date",
            "class_id",
            "plan_date",
            unique=True,
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index("ix_local_daily_plans_plan_date", "plan_date"),
        # The revision pointer must belong to this plan's term.
        ForeignKeyConstraint(
            ["term_id", "calendar_revision_id"],
            ["local_calendar_revisions.term_id", "local_calendar_revisions.id"],
            name="fk_local_daily_plans_term_revision",
        ),
        # Current content pointer: inline composite FK, deferred so the
        # header and its first content row commit together or not at all.
        ForeignKeyConstraint(
            ["id", "current_content_id", "current_content_version"],
            [
                "local_daily_plan_contents.daily_plan_id",
                "local_daily_plan_contents.id",
                "local_daily_plan_contents.version",
            ],
            name="fk_local_daily_plans_current_content",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    class_id: Mapped[str] = mapped_column(
        ForeignKey("local_classes.id"), nullable=False
    )
    term_id: Mapped[str] = mapped_column(
        ForeignKey("local_terms.id"), nullable=False
    )
    plan_date: Mapped[date] = mapped_column(Date, nullable=False)
    creator_id: Mapped[str] = mapped_column(
        ForeignKey("local_profile.id"), nullable=False
    )
    week_number: Mapped[int] = mapped_column(Integer, nullable=False)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)
    calendar_revision_id: Mapped[str] = mapped_column(String(32), nullable=False)

    current_content_id: Mapped[str] = mapped_column(String(32), nullable=False)
    current_content_version: Mapped[int] = mapped_column(Integer, nullable=False)

    # Immutable four-field header snapshot taken at creation.
    creator_display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    school_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    class_name: Mapped[str] = mapped_column(String(80), nullable=False)
    grade: Mapped[str] = mapped_column(String(20), nullable=False)

    # Soft-delete columns are reserved; no delete/recover API in D1A.
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    deleted_by: Mapped[str | None] = mapped_column(
        ForeignKey("local_profile.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalDailyPlanContent(LocalBase):
    """Append-only content version; rows are never updated in place."""

    __tablename__ = "local_daily_plan_contents"
    __table_args__ = (
        CheckConstraint(
            "version >= 1", name="ck_local_daily_plan_contents_version"
        ),
        UniqueConstraint(
            "daily_plan_id", "version",
            name="uq_local_daily_plan_contents_plan_version",
        ),
        # Triple referenced by the deferred composite pointer of the header.
        UniqueConstraint(
            "daily_plan_id", "id", "version",
            name="uq_local_daily_plan_contents_plan_id_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    daily_plan_id: Mapped[str] = mapped_column(
        ForeignKey("local_daily_plans.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_lesson_plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    split_baseline: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )
    adopted_content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    editor_id: Mapped[str] = mapped_column(
        ForeignKey("local_profile.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalSettings(LocalBase):
    """Singleton local settings: school name, current class, init retry key."""

    __tablename__ = "local_settings"
    __table_args__ = (
        CheckConstraint("id = 'singleton'", name="ck_local_settings_singleton_id"),
        CheckConstraint("singleton = 1", name="ck_local_settings_singleton"),
        CheckConstraint(
            "school_name IS NULL OR length(school_name) BETWEEN 1 AND 120",
            name="ck_local_settings_school_name",
        ),
        CheckConstraint(
            "length(init_request_id) BETWEEN 1 AND 36",
            name="ck_local_settings_init_request_id",
        ),
        CheckConstraint(
            "length(init_input_fingerprint) = 64",
            name="ck_local_settings_init_fingerprint",
        ),
        # Global configuration concurrency control for the single local
        # profile (D1B spec §10.3): a strict positive integer, distinct from
        # plan content versions and calendar revision numbers.
        CheckConstraint(
            "config_version >= 1", name="ck_local_settings_config_version"
        ),
        CheckConstraint(
            "ui_theme IN ('light', 'dark')", name="ck_local_settings_ui_theme"
        ),
        CheckConstraint(
            "typeof(ui_theme_version) = 'integer' AND ui_theme_version >= 1",
            name="ck_local_settings_ui_theme_version",
        ),
        UniqueConstraint("singleton", name="uq_local_settings_singleton"),
    )

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    singleton: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    school_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    current_class_id: Mapped[str] = mapped_column(
        ForeignKey("local_classes.id"), nullable=False
    )
    init_request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    init_input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    # 1 for a freshly initialized profile; bumped by every applied
    # configuration change (never by plan content saves).
    config_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )
    # Appearance preference: updated only by the appearance service; it never
    # changes config_version, calendar/game revisions or business settings.
    ui_theme: Mapped[str] = mapped_column(
        String(5), nullable=False, default="light", server_default="light"
    )
    ui_theme_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalConfigOperation(LocalBase):
    """Committed configuration receipt (idempotent apply retries).

    Stores only the request id, the input fingerprint (config version +
    normalized change), the result JSON, the committed configuration
    version and the time. Never stores lesson-plan content.
    """

    __tablename__ = "local_config_operations"
    __table_args__ = (
        CheckConstraint(
            "length(request_id) BETWEEN 1 AND 36",
            name="ck_local_config_operations_request_id",
        ),
        CheckConstraint(
            "length(input_fingerprint) = 64",
            name="ck_local_config_operations_fingerprint",
        ),
        CheckConstraint(
            "config_version >= 1",
            name="ck_local_config_operations_config_version",
        ),
        UniqueConstraint(
            "request_id", name="uq_local_config_operations_request_id"
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    config_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalOperationRecord(LocalBase):
    """Local audit record; committed in the same transaction as its change."""

    __tablename__ = "local_operation_records"
    __table_args__ = (
        CheckConstraint(
            "length(action) BETWEEN 1 AND 50",
            name="ck_local_operation_records_action",
        ),
        CheckConstraint(
            "length(target_type) BETWEEN 1 AND 30",
            name="ck_local_operation_records_target_type",
        ),
        CheckConstraint(
            "target_version_after IS NULL OR target_version_after >= 1",
            name="ck_local_operation_records_target_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )
    actor_id: Mapped[str] = mapped_column(
        ForeignKey("local_profile.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    target_type: Mapped[str] = mapped_column(String(30), nullable=False)
    target_id: Mapped[str] = mapped_column(String(32), nullable=False)
    target_version_after: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )


# ---------------------------------------------------------------------------
# D2 local AI persistence (engineering spec §2.1)
# ---------------------------------------------------------------------------


class LocalAIState(LocalBase):
    """Per-profile AI configuration pointers and blocking state.

    Empty database before profile initialization has no row. Both
    configuration pointers are deferred composite FKs so the state row and
    a newly created config version can commit together.
    """

    __tablename__ = "local_ai_state"
    __table_args__ = (
        ForeignKeyConstraint(
            ["profile_id", "current_config_version"],
            [
                "local_ai_config_versions.profile_id",
                "local_ai_config_versions.version",
            ],
            name="fk_local_ai_state_current_config",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["profile_id", "blocked_config_version"],
            [
                "local_ai_config_versions.profile_id",
                "local_ai_config_versions.version",
            ],
            name="fk_local_ai_state_blocked_config",
            deferrable=True,
            initially="DEFERRED",
        ),
        UniqueConstraint(
            "database_uuid", name="uq_local_ai_state_database_uuid"
        ),
    )

    profile_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("local_profile.id"), primary_key=True
    )
    database_uuid: Mapped[str] = mapped_column(String(64), nullable=False)
    current_config_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    blocked_config_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    blocked_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalAICredential(LocalBase):
    """Encrypted secret material: one row per key_id per profile.

    Active rows carry a 12-byte nonce and tagged ciphertext; cleared rows
    have both null. Version metadata is never cleared.
    """

    __tablename__ = "local_ai_credentials"
    __table_args__ = (
        CheckConstraint(
            "state IN ('active', 'retired', 'cleared')",
            name="ck_local_ai_credentials_state",
        ),
        # Active 凭据必须：key_id 有效、nonce 非 NULL 且恰好 12 字节、
        # ciphertext 非 NULL 且至少16字节（含 GCM 16字节tag）。不依赖
        # CHECK 对 NULL 的宽松语义，显式排除 NULL。
        CheckConstraint(
            "(state <> 'active') OR "
            "(key_id IS NOT NULL AND nonce IS NOT NULL AND length(nonce) = 12 "
            "AND ciphertext IS NOT NULL AND length(ciphertext) >= 16)",
            name="ck_local_ai_credentials_active_has_material",
        ),
        CheckConstraint(
            "(state <> 'cleared') OR (nonce IS NULL AND ciphertext IS NULL)",
            name="ck_local_ai_credentials_cleared_no_material",
        ),
        # Any non-NULL key_id must be a non-empty URL-safe opaque token
        # (1..64 chars from [A-Za-z0-9_-]); it can never be a path. The
        # typeof/instr guards are load-bearing: SQLite length() and GLOB
        # silently truncate at an embedded NUL and treat BLOBs as passing
        # "NOT GLOB", so a text type with no NUL byte is required first.
        # Active rows must still carry one (see active_has_material).
        CheckConstraint(
            "key_id IS NULL OR (typeof(key_id) = 'text' "
            "AND instr(key_id, char(0)) = 0 "
            "AND length(key_id) BETWEEN 1 AND 64 "
            "AND key_id NOT GLOB '*[^A-Za-z0-9_-]*')",
            name="ck_local_ai_credentials_key_id_shape",
        ),
        UniqueConstraint(
            "profile_id", "id", name="uq_local_ai_credentials_profile_id"
        ),
        ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_ai_credentials_profile_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    key_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    nonce: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalAIConfigVersion(LocalBase):
    """Immutable AI configuration snapshot per profile and version.

    protocol_id is fixed to ``chat_completions_v1``. ``credential_id``
    null means no secret configured (not an empty string).
    """

    __tablename__ = "local_ai_config_versions"
    __table_args__ = (
        CheckConstraint(
            "typeof(version) = 'integer' AND version >= 1",
            name="ck_local_ai_config_versions_version",
        ),
        CheckConstraint(
            "protocol_id = 'chat_completions_v1'",
            name="ck_local_ai_config_versions_protocol",
        ),
        ForeignKeyConstraint(
            ["profile_id", "credential_id"],
            [
                "local_ai_credentials.profile_id",
                "local_ai_credentials.id",
            ],
            name="fk_local_ai_config_versions_credential",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_ai_config_versions_profile_id",
        ),
        PrimaryKeyConstraint(
            "profile_id", "version", name="pk_local_ai_config_versions"
        ),
        UniqueConstraint(
            "profile_id", "version",
            name="uq_local_ai_config_versions_profile_version",
        ),
    )

    profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    protocol_id: Mapped[str] = mapped_column(
        String(50), nullable=False, default="chat_completions_v1"
    )
    base_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    credential_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalClassGameRevision(LocalBase):
    """Immutable class game configuration snapshot."""

    __tablename__ = "local_class_game_revisions"
    __table_args__ = (
        CheckConstraint(
            "typeof(revision_no) = 'integer' AND revision_no >= 1",
            name="ck_local_class_game_revisions_revision_no",
        ),
        UniqueConstraint(
            "class_id", "revision_no",
            name="uq_local_class_game_revisions_class_revision",
        ),
        UniqueConstraint(
            "class_id", "id", name="uq_local_class_game_revisions_class_id"
        ),
        ForeignKeyConstraint(
            ["class_id"],
            ["local_classes.id"],
            name="fk_local_class_game_revisions_class_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    class_id: Mapped[str] = mapped_column(String(32), nullable=False)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalClassGameHead(LocalBase):
    """Current game revision pointer per class."""

    __tablename__ = "local_class_game_heads"
    __table_args__ = (
        ForeignKeyConstraint(
            ["class_id", "current_revision_id"],
            [
                "local_class_game_revisions.class_id",
                "local_class_game_revisions.id",
            ],
            name="fk_local_class_game_heads_current_revision",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["class_id"],
            ["local_classes.id"],
            name="fk_local_class_game_heads_class_id",
        ),
    )

    class_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("local_classes.id"), primary_key=True
    )
    current_revision_id: Mapped[str] = mapped_column(
        String(32), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalPromptBundle(LocalBase):
    """Frozen default prompt bundle delivered with the application package.

    Same contract version + default revision content with a different hash
    must not be silently overwritten.
    """

    __tablename__ = "local_prompt_bundles"
    __table_args__ = (
        CheckConstraint(
            "task_type IN ('daily_lesson_split', 'daily_process_adapt', "
            "'daily_other_activities', 'game_observation_generate', "
            "'game_observation_rewrite', 'weekly_games_select', "
            "'weekly_key_week_focus', 'weekly_environment_setup', "
            "'weekly_habit_culture', 'weekly_home_cooperation', "
            "'weekly_materials_generate', 'listening_note_draft', "
            "'listening_domain_evaluate', 'listening_group_notes', "
            "'listening_goal_suggest', 'class_game_config_extract', "
            "'daily_reflection_generate', 'curriculum_split', "
            "'curriculum_review', 'curriculum_edit')",
            name="ck_local_prompt_bundles_task_type",
        ),
        CheckConstraint(
            "typeof(contract_version) = 'integer' AND contract_version >= 1",
            name="ck_local_prompt_bundles_contract_version",
        ),
        CheckConstraint(
            "typeof(default_revision) = 'integer' AND default_revision >= 1",
            name="ck_local_prompt_bundles_default_revision",
        ),
        PrimaryKeyConstraint(
            "task_type", "contract_version", "default_revision",
            name="pk_local_prompt_bundles",
        ),
    )

    task_type: Mapped[str] = mapped_column(String(40), nullable=False)
    contract_version: Mapped[int] = mapped_column(Integer, nullable=False)
    default_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    input_schema_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    output_schema_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    guidance_defaults_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    bundle_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalPersonalPromptVersion(LocalBase):
    """Teacher's personal prompt revision for one task type."""

    __tablename__ = "local_personal_prompt_versions"
    __table_args__ = (
        CheckConstraint(
            "action IN ('initial', 'edit', 'accept', 'reject', 'adapt')",
            name="ck_local_personal_prompt_versions_action",
        ),
        CheckConstraint(
            "typeof(revision) = 'integer' AND revision >= 1",
            name="ck_local_personal_prompt_versions_revision",
        ),
        CheckConstraint(
            "typeof(contract_version) = 'integer' AND contract_version >= 1",
            name="ck_local_personal_prompt_versions_contract_version",
        ),
        CheckConstraint(
            "typeof(based_default_revision) = 'integer' AND based_default_revision >= 1",
            name="ck_local_personal_prompt_versions_based_default_revision",
        ),
        CheckConstraint(
            "rejected_default_revision IS NULL OR "
            "(typeof(rejected_default_revision) = 'integer' AND rejected_default_revision >= 1)",
            name="ck_local_personal_prompt_versions_rejected_default_revision",
        ),
        ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_personal_prompt_versions_profile_id",
        ),
        ForeignKeyConstraint(
            ["task_type", "contract_version", "based_default_revision"],
            [
                "local_prompt_bundles.task_type",
                "local_prompt_bundles.contract_version",
                "local_prompt_bundles.default_revision",
            ],
            name="fk_local_personal_prompt_versions_bundle",
        ),
        # 拒绝的默认修订也必须引用存在且同contract的bundle（可为NULL）。
        ForeignKeyConstraint(
            ["task_type", "contract_version", "rejected_default_revision"],
            [
                "local_prompt_bundles.task_type",
                "local_prompt_bundles.contract_version",
                "local_prompt_bundles.default_revision",
            ],
            name="fk_local_personal_prompt_versions_rejected_bundle",
            deferrable=True,
            initially="DEFERRED",
        ),
        PrimaryKeyConstraint(
            "profile_id", "task_type", "revision",
            name="pk_local_personal_prompt_versions",
        ),
        UniqueConstraint(
            "profile_id", "task_type", "revision",
            name="uq_local_personal_prompt_versions_profile_task_revision",
        ),
    )

    profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    task_type: Mapped[str] = mapped_column(String(40), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    contract_version: Mapped[int] = mapped_column(Integer, nullable=False)
    based_default_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    guidance_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    orphaned_guidance_json: Mapped[dict | None] = mapped_column(
        JSON, nullable=True
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False, default="initial")
    rejected_default_revision: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalPersonalPromptHead(LocalBase):
    """Current personal prompt head per profile and task type."""

    __tablename__ = "local_personal_prompt_heads"
    __table_args__ = (
        CheckConstraint(
            "typeof(current_revision) = 'integer' AND current_revision >= 1",
            name="ck_local_personal_prompt_heads_current_revision",
        ),
        CheckConstraint(
            "typeof(required_contract_version) = 'integer' AND required_contract_version >= 1",
            name="ck_local_personal_prompt_heads_required_contract_version",
        ),
        CheckConstraint(
            "typeof(latest_default_revision) = 'integer' AND latest_default_revision >= 1",
            name="ck_local_personal_prompt_heads_latest_default_revision",
        ),
        ForeignKeyConstraint(
            ["profile_id", "task_type", "current_revision"],
            [
                "local_personal_prompt_versions.profile_id",
                "local_personal_prompt_versions.task_type",
                "local_personal_prompt_versions.revision",
            ],
            name="fk_local_personal_prompt_heads_current_version",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["task_type", "required_contract_version", "latest_default_revision"],
            [
                "local_prompt_bundles.task_type",
                "local_prompt_bundles.contract_version",
                "local_prompt_bundles.default_revision",
            ],
            name="fk_local_personal_prompt_heads_required_bundle",
        ),
        PrimaryKeyConstraint(
            "profile_id", "task_type",
            name="pk_local_personal_prompt_heads",
        ),
    )

    profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    task_type: Mapped[str] = mapped_column(String(40), nullable=False)
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    required_contract_version: Mapped[int] = mapped_column(Integer, nullable=False)
    latest_default_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalAIInput(LocalBase):
    """Immutable business input snapshot for one AI task.

    ``source_kind`` is the non-null discriminator.  The old daily columns stay
    present for byte-for-byte upgrade compatibility; the branch CHECK makes
    them non-null for daily rows and null for observation rows.  Observation
    input pins the stable record, never a draft revision or a history version.
    """

    __tablename__ = "local_ai_inputs"
    __table_args__ = (
        CheckConstraint(
            "typeof(input_schema_version) = 'integer' AND input_schema_version >= 1",
            name="ck_local_ai_inputs_input_schema_version",
        ),
        CheckConstraint(
            "task_type IN ('daily_lesson_split', 'daily_process_adapt', "
            "'daily_other_activities', 'game_observation_generate', "
            "'game_observation_rewrite', 'weekly_games_select', "
            "'weekly_key_week_focus', 'weekly_environment_setup', "
            "'weekly_habit_culture', 'weekly_home_cooperation', "
            "'weekly_materials_generate', 'listening_note_draft', "
            "'listening_domain_evaluate', 'listening_group_notes', "
            "'listening_goal_suggest', 'class_game_config_extract', "
            "'daily_reflection_generate', 'curriculum_split', "
            "'curriculum_review', 'curriculum_edit')",
            name="ck_local_ai_inputs_task_type",
        ),
        CheckConstraint(
            "source_kind IN ('daily_plan', 'game_observation', 'weekly_plan', 'one_to_one_listening', 'class_game_config', 'curriculum_deliberation')",
            name="ck_local_ai_inputs_source_kind",
        ),
        CheckConstraint(
            "(source_kind = 'daily_plan' "
            "AND task_type IN ('daily_lesson_split', 'daily_process_adapt', "
            "'daily_other_activities', 'daily_reflection_generate') "
            "AND daily_plan_id IS NOT NULL "
            "AND content_id IS NOT NULL "
            "AND content_version IS NOT NULL "
            "AND target_grade IS NOT NULL "
            "AND target_grade IN ('small', 'middle', 'large') "
            "AND observation_id IS NULL "
            "AND source_id = daily_plan_id "
            "AND source_revision IS NULL "
            "AND weekly_plan_id IS NULL AND weekly_draft_id IS NULL "
            "AND create_operation_id IS NULL) "
            "OR "
            "(source_kind = 'game_observation' "
            "AND task_type IN ('game_observation_generate', "
            "'game_observation_rewrite') "
            "AND daily_plan_id IS NULL "
            "AND content_id IS NULL "
            "AND content_version IS NULL "
            "AND target_grade IS NULL "
            "AND observation_id IS NOT NULL "
            "AND source_id = observation_id "
            "AND source_revision IS NOT NULL "
            "AND typeof(source_revision) = 'integer' "
            "AND source_revision >= 1 "
            "AND weekly_plan_id IS NULL AND weekly_draft_id IS NULL "
            "AND create_operation_id IS NULL) "
            "OR "
            "(source_kind = 'weekly_plan' "
            "AND task_type IN ('weekly_games_select', 'weekly_key_week_focus', "
            "'weekly_environment_setup', 'weekly_habit_culture', "
            "'weekly_home_cooperation', 'weekly_materials_generate') "
            "AND daily_plan_id IS NULL AND content_id IS NULL "
            "AND content_version IS NULL AND target_grade IS NULL "
            "AND observation_id IS NULL "
            "AND source_id = weekly_plan_id "
            "AND weekly_plan_id IS NOT NULL AND weekly_draft_id IS NOT NULL "
            "AND source_revision IS NOT NULL "
            "AND typeof(source_revision) = 'integer' AND source_revision >= 1 "
            "AND create_operation_id IS NOT NULL) "
            "OR "
            "(source_kind = 'one_to_one_listening' "
            "AND task_type IN ('listening_note_draft', 'listening_domain_evaluate', "
            "'listening_group_notes', 'listening_goal_suggest') "
            "AND daily_plan_id IS NULL AND content_id IS NULL "
            "AND content_version IS NULL AND target_grade IS NULL "
            "AND observation_id IS NULL AND source_id = listening_record_id "
            "AND listening_record_id IS NOT NULL AND listening_domain IS NOT NULL "
            "AND ((task_type = 'listening_note_draft' AND listening_group_id IS NOT NULL) "
            "OR (task_type IN ('listening_domain_evaluate', 'listening_group_notes', "
            "'listening_goal_suggest') AND listening_group_id IS NULL)) "
            "AND source_revision IS NOT NULL "
            "AND typeof(source_revision) = 'integer' AND source_revision >= 1 "
            "AND weekly_plan_id IS NULL AND weekly_draft_id IS NULL "
            "AND create_operation_id IS NOT NULL) "
            "OR "
            "(source_kind = 'class_game_config' "
            "AND task_type = 'class_game_config_extract' "
            "AND daily_plan_id IS NULL AND content_id IS NULL "
            "AND content_version IS NULL AND target_grade IS NULL "
            "AND observation_id IS NULL "
            "AND weekly_plan_id IS NULL AND weekly_draft_id IS NULL "
            "AND listening_record_id IS NULL AND listening_domain IS NULL "
            "AND listening_group_id IS NULL "
            "AND create_operation_id IS NULL "
            "AND source_revision IS NOT NULL "
            "AND typeof(source_revision) = 'integer' AND source_revision >= 1) "
            "OR "
            "(source_kind = 'curriculum_deliberation' "
            "AND task_type IN ('curriculum_split', 'curriculum_review', "
            "'curriculum_edit') "
            "AND daily_plan_id IS NULL AND content_id IS NULL "
            "AND content_version IS NULL "
            "AND observation_id IS NULL "
            "AND weekly_plan_id IS NULL AND weekly_draft_id IS NULL "
            "AND listening_record_id IS NULL AND listening_domain IS NULL "
            "AND listening_group_id IS NULL "
            "AND create_operation_id IS NULL "
            "AND (target_grade IS NULL OR target_grade IN ('small', 'middle', 'large')) "
            "AND source_revision IS NOT NULL "
            "AND typeof(source_revision) = 'integer' AND source_revision >= 0)",
            name="ck_local_ai_inputs_source_match",
        ),
        CheckConstraint(
            "source_kind = 'one_to_one_listening' "
            "OR (listening_record_id IS NULL "
            "AND listening_domain IS NULL "
            "AND listening_group_id IS NULL)",
            name="ck_local_ai_aiinput_listening_columns",
        ),
        ForeignKeyConstraint(
            ["daily_plan_id", "content_id", "content_version"],
            [
                "local_daily_plan_contents.daily_plan_id",
                "local_daily_plan_contents.id",
                "local_daily_plan_contents.version",
            ],
            name="fk_local_ai_inputs_content_triple",
        ),
        ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_ai_inputs_profile_id",
        ),
        ForeignKeyConstraint(
            ["profile_id", "observation_id"],
            [
                "local_observation_records.creator_profile_id",
                "local_observation_records.id",
            ],
            name="fk_local_ai_inputs_observation",
        ),
        ForeignKeyConstraint(
            ["profile_id", "weekly_plan_id"],
            ["local_weekly_plans.profile_id", "local_weekly_plans.id"],
            name="fk_local_ai_inputs_weekly_plan",
        ),
        ForeignKeyConstraint(
            ["weekly_plan_id", "weekly_draft_id", "source_revision"],
            [
                "local_weekly_plan_contents.weekly_plan_id",
                "local_weekly_plan_contents.id",
                "local_weekly_plan_contents.version",
            ],
            name="fk_local_ai_inputs_weekly_draft",
        ),
        ForeignKeyConstraint(
            ["profile_id", "create_operation_id"],
            ["local_ai_operations.profile_id", "local_ai_operations.id"],
            name="fk_local_ai_inputs_create_operation",
        ),
        ForeignKeyConstraint(
            ["profile_id", "listening_record_id"],
            ["local_listening_records.profile_id", "local_listening_records.id"],
            name="fk_local_ai_inputs_listening_record",
        ),
        ForeignKeyConstraint(
            ["listening_record_id", "listening_domain"],
            ["local_listening_domains.record_id", "local_listening_domains.domain"],
            name="fk_local_ai_inputs_listening_domain",
        ),
        ForeignKeyConstraint(
            ["listening_record_id", "listening_domain", "listening_group_id"],
            [
                "local_listening_photo_groups.record_id",
                "local_listening_photo_groups.domain",
                "local_listening_photo_groups.id",
            ],
            name="fk_local_ai_inputs_listening_group",
        ),
        UniqueConstraint(
            "daily_plan_id", "id", "task_type",
            name="uq_local_ai_inputs_plan_id_task",
        ),
        UniqueConstraint(
            "profile_id", "source_kind", "source_id", "id", "task_type",
            name="uq_local_ai_inputs_source_task",
        ),
        UniqueConstraint(
            "profile_id", "source_kind", "source_id", "id",
            name="uq_local_ai_inputs_source_id",
        ),
        Index(
            "ix_local_ai_inputs_source_task",
            "profile_id", "source_kind", "source_id", "task_type",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    observation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    daily_plan_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    content_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    content_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weekly_plan_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    weekly_draft_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    listening_record_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    listening_domain: Mapped[str | None] = mapped_column(String(20), nullable=True)
    listening_group_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    create_operation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    task_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_grade: Mapped[str | None] = mapped_column(String(20), nullable=True)
    input_schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    dependencies_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    dependency_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    target_hashes_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalAITask(LocalBase):
    """Mutable scheduling head for one AI task on one plan or observation."""

    __tablename__ = "local_ai_tasks"
    __table_args__ = (
        CheckConstraint(
            "typeof(generation) = 'integer' AND generation >= 0",
            name="ck_local_ai_tasks_generation",
        ),
        CheckConstraint(
            "status IN ('pending', 'claimed', 'dispatching', 'retry_wait', "
            "'paused', 'succeeded', 'failed', 'outcome_unknown', 'cancelled')",
            name="ck_local_ai_tasks_status",
        ),
        CheckConstraint(
            "source_kind IN ('daily_plan', 'game_observation', 'weekly_plan', 'one_to_one_listening', 'class_game_config', 'curriculum_deliberation')",
            name="ck_local_ai_tasks_source_kind",
        ),
        CheckConstraint(
            "(source_kind = 'daily_plan' "
            "AND task_type IN ('daily_lesson_split', 'daily_process_adapt', "
            "'daily_other_activities', 'daily_reflection_generate') "
            "AND daily_plan_id IS NOT NULL "
            "AND observation_id IS NULL "
            "AND weekly_plan_id IS NULL "
            "AND source_id = daily_plan_id) "
            "OR "
            "(source_kind = 'game_observation' "
            "AND task_type IN ('game_observation_generate', "
            "'game_observation_rewrite') "
            "AND daily_plan_id IS NULL "
            "AND observation_id IS NOT NULL "
            "AND weekly_plan_id IS NULL "
            "AND source_id = observation_id) "
            "OR "
            "(source_kind = 'weekly_plan' "
            "AND task_type IN ('weekly_games_select', 'weekly_key_week_focus', "
            "'weekly_environment_setup', 'weekly_habit_culture', "
            "'weekly_home_cooperation', 'weekly_materials_generate') "
            "AND daily_plan_id IS NULL AND observation_id IS NULL "
            "AND weekly_plan_id IS NOT NULL "
            "AND source_id = weekly_plan_id) "
            "OR "
            "(source_kind = 'one_to_one_listening' "
            "AND task_type IN ('listening_note_draft', 'listening_domain_evaluate', "
            "'listening_group_notes', 'listening_goal_suggest') "
            "AND daily_plan_id IS NULL AND observation_id IS NULL "
            "AND weekly_plan_id IS NULL AND source_id = listening_record_id "
            "AND listening_record_id IS NOT NULL AND listening_domain IS NOT NULL "
            "AND ((task_type = 'listening_note_draft' AND listening_group_id IS NOT NULL) "
            "OR (task_type IN ('listening_domain_evaluate', 'listening_group_notes', "
            "'listening_goal_suggest') AND listening_group_id IS NULL))) "
            "OR "
            "(source_kind = 'class_game_config' "
            "AND task_type = 'class_game_config_extract' "
            "AND daily_plan_id IS NULL AND observation_id IS NULL "
            "AND weekly_plan_id IS NULL "
            "AND listening_record_id IS NULL AND listening_domain IS NULL "
            "AND listening_group_id IS NULL) "
            "OR "
            "(source_kind = 'curriculum_deliberation' "
            "AND task_type IN ('curriculum_split', 'curriculum_review', "
            "'curriculum_edit') "
            "AND daily_plan_id IS NULL AND observation_id IS NULL "
            "AND weekly_plan_id IS NULL "
            "AND listening_record_id IS NULL AND listening_domain IS NULL "
            "AND listening_group_id IS NULL)",
            name="ck_local_ai_tasks_source_match",
        ),
        CheckConstraint(
            "source_kind = 'one_to_one_listening' "
            "OR (listening_record_id IS NULL "
            "AND listening_domain IS NULL "
            "AND listening_group_id IS NULL)",
            name="ck_local_ai_aitask_listening_columns",
        ),
        ForeignKeyConstraint(
            ["daily_plan_id", "input_id", "task_type"],
            [
                "local_ai_inputs.daily_plan_id",
                "local_ai_inputs.id",
                "local_ai_inputs.task_type",
            ],
            name="fk_local_ai_tasks_input",
        ),
        ForeignKeyConstraint(
            ["profile_id", "source_kind", "source_id", "input_id", "task_type"],
            [
                "local_ai_inputs.profile_id",
                "local_ai_inputs.source_kind",
                "local_ai_inputs.source_id",
                "local_ai_inputs.id",
                "local_ai_inputs.task_type",
            ],
            name="fk_local_ai_tasks_source_input",
        ),
        ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_ai_tasks_profile_id",
        ),
        ForeignKeyConstraint(
            ["profile_id", "weekly_plan_id"],
            ["local_weekly_plans.profile_id", "local_weekly_plans.id"],
            name="fk_local_ai_tasks_weekly_plan",
        ),
        ForeignKeyConstraint(
            ["profile_id", "listening_record_id"],
            ["local_listening_records.profile_id", "local_listening_records.id"],
            name="fk_local_ai_tasks_listening_record",
        ),
        ForeignKeyConstraint(
            ["listening_record_id", "listening_domain"],
            ["local_listening_domains.record_id", "local_listening_domains.domain"],
            name="fk_local_ai_tasks_listening_domain",
        ),
        ForeignKeyConstraint(
            ["listening_record_id", "listening_domain", "listening_group_id"],
            [
                "local_listening_photo_groups.record_id",
                "local_listening_photo_groups.domain",
                "local_listening_photo_groups.id",
            ],
            name="fk_local_ai_tasks_listening_group",
        ),
        # Deferred composite self-reference to executions: pending tasks may
        # have no current execution yet.
        ForeignKeyConstraint(
            ["id", "current_execution_id"],
            [
                "local_ai_executions.task_id",
                "local_ai_executions.id",
            ],
            name="fk_local_ai_tasks_current_execution",
            deferrable=True,
            initially="DEFERRED",
        ),
        UniqueConstraint(
            "daily_plan_id", "id", "input_id", "task_type",
            name="uq_local_ai_tasks_plan_input",
        ),
        UniqueConstraint(
            "profile_id", "source_kind", "source_id", "id", "input_id",
            "task_type",
            name="uq_local_ai_tasks_source_input",
        ),
        Index(
            "ix_local_ai_tasks_source_status",
            "profile_id", "source_kind", "source_id", "status", "updated_at",
        ),
        Index(
            "ix_local_ai_tasks_plan_created",
            "daily_plan_id", "created_at", "id",
        ),
        Index(
            "ix_local_ai_tasks_status_created",
            "status", "created_at", "id",
        ),
        Index(
            "uq_local_ai_tasks_active_per_plan_type",
            "daily_plan_id", "task_type",
            unique=True,
            sqlite_where=text(
                "status IN ('pending', 'claimed', 'dispatching', 'retry_wait')"
            ),
        ),
        Index(
            "uq_local_ai_tasks_active_per_source_type",
            "profile_id", "source_kind", "source_id", "task_type",
            unique=True,
            sqlite_where=text(
                "source_kind = 'game_observation' AND status IN "
                "('pending', 'claimed', 'dispatching', 'retry_wait')"
            ),
        ),
        Index(
            "uq_local_ai_tasks_active_per_weekly_type",
            "profile_id", "weekly_plan_id", "task_type",
            unique=True,
            sqlite_where=text(
                "source_kind = 'weekly_plan' AND status IN "
                "('pending', 'claimed', 'dispatching', 'retry_wait')"
            ),
        ),
        Index(
            "uq_local_ai_tasks_active_per_config_type",
            "profile_id", "source_kind", "source_id", "task_type",
            unique=True,
            sqlite_where=text(
                "source_kind = 'class_game_config' AND status IN "
                "('pending', 'claimed', 'dispatching', 'retry_wait')"
            ),
        ),
        Index(
            "uq_local_ai_tasks_active_listening_note",
            "profile_id", "listening_record_id", "listening_domain",
            "listening_group_id", "task_type",
            unique=True,
            sqlite_where=text(
                "source_kind = 'one_to_one_listening' "
                "AND task_type = 'listening_note_draft' "
                "AND listening_group_id IS NOT NULL "
                "AND status IN ('pending', 'claimed', 'dispatching', 'retry_wait')"
            ),
        ),
        Index(
            "uq_local_ai_tasks_active_listening_domain",
            "profile_id", "listening_record_id", "listening_domain", "task_type",
            unique=True,
            sqlite_where=text(
                "source_kind = 'one_to_one_listening' "
                "AND task_type = 'listening_domain_evaluate' "
                "AND listening_group_id IS NULL "
                "AND status IN ('pending', 'claimed', 'dispatching', 'retry_wait')"
            ),
        ),
        Index(
            "uq_local_ai_tasks_active_listening_group_notes",
            "profile_id", "listening_record_id", "listening_domain", "task_type",
            unique=True,
            sqlite_where=text(
                "source_kind = 'one_to_one_listening' "
                "AND task_type = 'listening_group_notes' "
                "AND listening_group_id IS NULL "
                "AND status IN ('pending', 'claimed', 'dispatching', 'retry_wait')"
            ),
        ),
        Index(
            "uq_local_ai_tasks_active_listening_goal",
            "profile_id", "listening_record_id", "listening_domain", "task_type",
            unique=True,
            sqlite_where=text(
                "source_kind = 'one_to_one_listening' "
                "AND task_type = 'listening_goal_suggest' "
                "AND listening_group_id IS NULL "
                "AND status IN ('pending', 'claimed', 'dispatching', 'retry_wait')"
            ),
        ),
        Index(
            "uq_local_ai_tasks_active_curriculum",
            "profile_id", "source_kind", "source_id", "task_type",
            unique=True,
            sqlite_where=text(
                "source_kind = 'curriculum_deliberation' "
                "AND status IN ('pending', 'claimed', 'dispatching', 'retry_wait')"
            ),
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    observation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    daily_plan_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    weekly_plan_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    listening_record_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    listening_domain: Mapped[str | None] = mapped_column(String(20), nullable=True)
    listening_group_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    task_type: Mapped[str] = mapped_column(String(40), nullable=False)
    input_id: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    current_execution_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    runtime_meta_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalAIExecution(LocalBase):
    """One execution attempt of a task, pinned to configuration versions."""

    __tablename__ = "local_ai_executions"
    __table_args__ = (
        CheckConstraint(
            "typeof(generation) = 'integer' AND generation >= 1",
            name="ck_local_ai_executions_generation",
        ),
        CheckConstraint(
            "typeof(config_version) = 'integer' AND config_version >= 1",
            name="ck_local_ai_executions_config_version_check",
        ),
        CheckConstraint(
            "typeof(personal_revision) = 'integer' AND personal_revision >= 1",
            name="ck_local_ai_executions_personal_revision_check",
        ),
        CheckConstraint(
            "typeof(contract_version) = 'integer' AND contract_version >= 1",
            name="ck_local_ai_executions_contract_version_check",
        ),
        CheckConstraint(
            "typeof(default_revision) = 'integer' AND default_revision >= 1",
            name="ck_local_ai_executions_default_revision_check",
        ),
        CheckConstraint(
            "state IN ('pending', 'claimed', 'dispatching', 'retry_wait', "
            "'paused', 'succeeded', 'failed', 'outcome_unknown', 'cancelled')",
            name="ck_local_ai_executions_state",
        ),
        CheckConstraint(
            "source_kind IN ('daily_plan', 'game_observation', 'weekly_plan', 'one_to_one_listening', 'class_game_config', 'curriculum_deliberation')",
            name="ck_local_ai_executions_source_kind",
        ),
        CheckConstraint(
            "(source_kind = 'daily_plan' "
            "AND task_type IN ('daily_lesson_split', 'daily_process_adapt', "
            "'daily_other_activities', 'daily_reflection_generate') "
            "AND daily_plan_id IS NOT NULL "
            "AND observation_id IS NULL "
            "AND weekly_plan_id IS NULL "
            "AND source_id = daily_plan_id) "
            "OR "
            "(source_kind = 'game_observation' "
            "AND task_type IN ('game_observation_generate', "
            "'game_observation_rewrite') "
            "AND daily_plan_id IS NULL "
            "AND observation_id IS NOT NULL "
            "AND weekly_plan_id IS NULL "
            "AND source_id = observation_id) "
            "OR "
            "(source_kind = 'weekly_plan' "
            "AND task_type IN ('weekly_games_select', 'weekly_key_week_focus', "
            "'weekly_environment_setup', 'weekly_habit_culture', "
            "'weekly_home_cooperation', 'weekly_materials_generate') "
            "AND daily_plan_id IS NULL AND observation_id IS NULL "
            "AND weekly_plan_id IS NOT NULL "
            "AND source_id = weekly_plan_id) "
            "OR "
            "(source_kind = 'one_to_one_listening' "
            "AND task_type IN ('listening_note_draft', 'listening_domain_evaluate', "
            "'listening_group_notes', 'listening_goal_suggest') "
            "AND daily_plan_id IS NULL AND observation_id IS NULL "
            "AND weekly_plan_id IS NULL AND source_id = listening_record_id "
            "AND listening_record_id IS NOT NULL AND listening_domain IS NOT NULL "
            "AND ((task_type = 'listening_note_draft' AND listening_group_id IS NOT NULL) "
            "OR (task_type IN ('listening_domain_evaluate', 'listening_group_notes', "
            "'listening_goal_suggest') AND listening_group_id IS NULL))) "
            "OR "
            "(source_kind = 'class_game_config' "
            "AND task_type = 'class_game_config_extract' "
            "AND daily_plan_id IS NULL AND observation_id IS NULL "
            "AND weekly_plan_id IS NULL "
            "AND listening_record_id IS NULL AND listening_domain IS NULL "
            "AND listening_group_id IS NULL) "
            "OR "
            "(source_kind = 'curriculum_deliberation' "
            "AND task_type IN ('curriculum_split', 'curriculum_review', "
            "'curriculum_edit') "
            "AND daily_plan_id IS NULL AND observation_id IS NULL "
            "AND weekly_plan_id IS NULL "
            "AND listening_record_id IS NULL AND listening_domain IS NULL "
            "AND listening_group_id IS NULL)",
            name="ck_local_ai_executions_source_match",
        ),
        CheckConstraint(
            "source_kind = 'one_to_one_listening' "
            "OR (listening_record_id IS NULL "
            "AND listening_domain IS NULL "
            "AND listening_group_id IS NULL)",
            name="ck_local_ai_aiexecution_listening_columns",
        ),
        ForeignKeyConstraint(
            ["daily_plan_id", "task_id", "input_id", "task_type"],
            [
                "local_ai_tasks.daily_plan_id",
                "local_ai_tasks.id",
                "local_ai_tasks.input_id",
                "local_ai_tasks.task_type",
            ],
            name="fk_local_ai_executions_task",
        ),
        ForeignKeyConstraint(
            ["profile_id", "source_kind", "source_id", "task_id", "input_id",
             "task_type"],
            [
                "local_ai_tasks.profile_id",
                "local_ai_tasks.source_kind",
                "local_ai_tasks.source_id",
                "local_ai_tasks.id",
                "local_ai_tasks.input_id",
                "local_ai_tasks.task_type",
            ],
            name="fk_local_ai_executions_source_task",
        ),
        ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_ai_executions_profile_id",
        ),
        ForeignKeyConstraint(
            ["profile_id", "weekly_plan_id"],
            ["local_weekly_plans.profile_id", "local_weekly_plans.id"],
            name="fk_local_ai_executions_weekly_plan",
        ),
        ForeignKeyConstraint(
            ["profile_id", "listening_record_id"],
            ["local_listening_records.profile_id", "local_listening_records.id"],
            name="fk_local_ai_executions_listening_record",
        ),
        ForeignKeyConstraint(
            ["listening_record_id", "listening_domain"],
            ["local_listening_domains.record_id", "local_listening_domains.domain"],
            name="fk_local_ai_executions_listening_domain",
        ),
        ForeignKeyConstraint(
            ["listening_record_id", "listening_domain", "listening_group_id"],
            [
                "local_listening_photo_groups.record_id",
                "local_listening_photo_groups.domain",
                "local_listening_photo_groups.id",
            ],
            name="fk_local_ai_executions_listening_group",
        ),
        # Pinned configuration version for this execution.
        ForeignKeyConstraint(
            ["profile_id", "config_version"],
            [
                "local_ai_config_versions.profile_id",
                "local_ai_config_versions.version",
            ],
            name="fk_local_ai_executions_config_version",
            deferrable=True,
            initially="DEFERRED",
        ),
        # Pinned personal prompt revision for this execution.
        ForeignKeyConstraint(
            ["profile_id", "task_type", "personal_revision"],
            [
                "local_personal_prompt_versions.profile_id",
                "local_personal_prompt_versions.task_type",
                "local_personal_prompt_versions.revision",
            ],
            name="fk_local_ai_executions_personal_revision",
            deferrable=True,
            initially="DEFERRED",
        ),
        # Pinned default prompt bundle for this execution.
        ForeignKeyConstraint(
            ["task_type", "contract_version", "default_revision"],
            [
                "local_prompt_bundles.task_type",
                "local_prompt_bundles.contract_version",
                "local_prompt_bundles.default_revision",
            ],
            name="fk_local_ai_executions_default_bundle",
            deferrable=True,
            initially="DEFERRED",
        ),
        UniqueConstraint(
            "task_id", "generation",
            name="uq_local_ai_executions_task_generation",
        ),
        UniqueConstraint(
            "task_id", "id", name="uq_local_ai_executions_task_id",
        ),
        UniqueConstraint(
            "daily_plan_id", "task_id", "input_id", "task_type", "id",
            name="uq_local_ai_executions_plan_task_input_id",
        ),
        UniqueConstraint(
            "profile_id", "source_kind", "source_id", "id", "task_id",
            "input_id", "task_type",
            name="uq_local_ai_executions_source_task_input_id",
        ),
        Index(
            "ix_local_ai_executions_source_task",
            "profile_id", "source_kind", "source_id", "task_id", "generation",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(32), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    observation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    daily_plan_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    weekly_plan_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    listening_record_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    listening_domain: Mapped[str | None] = mapped_column(String(20), nullable=True)
    listening_group_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    input_id: Mapped[str] = mapped_column(String(32), nullable=False)
    task_type: Mapped[str] = mapped_column(String(40), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    launch_id: Mapped[str] = mapped_column(String(36), nullable=False)
    permit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    config_version: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    personal_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    contract_version: Mapped[int] = mapped_column(Integer, nullable=False)
    default_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    runtime_meta_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )


class LocalAIAttempt(LocalBase):
    """One network attempt within an execution."""

    __tablename__ = "local_ai_attempts"
    __table_args__ = (
        CheckConstraint(
            "typeof(attempt_no) = 'integer' AND attempt_no BETWEEN 1 AND 3",
            name="ck_local_ai_attempts_attempt_no",
        ),
        ForeignKeyConstraint(
            ["execution_id"],
            ["local_ai_executions.id"],
            name="fk_local_ai_attempts_execution_id",
        ),
        UniqueConstraint(
            "execution_id", "attempt_no",
            name="uq_local_ai_attempts_execution_attempt",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    execution_id: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    dispatch_marked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    evidence_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider_request_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    returned_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    usage_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalAICandidate(LocalBase):
    """Validated model candidate, immutable after commit."""

    __tablename__ = "local_ai_candidates"
    __table_args__ = (
        CheckConstraint(
            "typeof(contract_version) = 'integer' AND contract_version >= 1",
            name="ck_local_ai_candidates_contract_version",
        ),
        CheckConstraint(
            "typeof(schema_version) = 'integer' AND schema_version >= 1",
            name="ck_local_ai_candidates_schema_version",
        ),
        CheckConstraint(
            "source_kind IN ('daily_plan', 'game_observation', 'weekly_plan', 'one_to_one_listening', 'class_game_config', 'curriculum_deliberation')",
            name="ck_local_ai_candidates_source_kind",
        ),
        CheckConstraint(
            "(source_kind = 'daily_plan' "
            "AND task_type IN ('daily_lesson_split', 'daily_process_adapt', "
            "'daily_other_activities', 'daily_reflection_generate') "
            "AND daily_plan_id IS NOT NULL "
            "AND observation_id IS NULL "
            "AND weekly_plan_id IS NULL "
            "AND source_id = daily_plan_id) "
            "OR "
            "(source_kind = 'game_observation' "
            "AND task_type IN ('game_observation_generate', "
            "'game_observation_rewrite') "
            "AND daily_plan_id IS NULL "
            "AND observation_id IS NOT NULL "
            "AND weekly_plan_id IS NULL "
            "AND source_id = observation_id) "
            "OR "
            "(source_kind = 'weekly_plan' "
            "AND task_type IN ('weekly_games_select', 'weekly_key_week_focus', "
            "'weekly_environment_setup', 'weekly_habit_culture', "
            "'weekly_home_cooperation', 'weekly_materials_generate') "
            "AND daily_plan_id IS NULL AND observation_id IS NULL "
            "AND weekly_plan_id IS NOT NULL "
            "AND source_id = weekly_plan_id) "
            "OR "
            "(source_kind = 'one_to_one_listening' "
            "AND task_type IN ('listening_note_draft', 'listening_domain_evaluate', "
            "'listening_group_notes', 'listening_goal_suggest') "
            "AND daily_plan_id IS NULL AND observation_id IS NULL "
            "AND weekly_plan_id IS NULL AND source_id = listening_record_id "
            "AND listening_record_id IS NOT NULL AND listening_domain IS NOT NULL "
            "AND ((task_type = 'listening_note_draft' AND listening_group_id IS NOT NULL) "
            "OR (task_type IN ('listening_domain_evaluate', 'listening_group_notes', "
            "'listening_goal_suggest') AND listening_group_id IS NULL))) "
            "OR "
            "(source_kind = 'class_game_config' "
            "AND task_type = 'class_game_config_extract' "
            "AND daily_plan_id IS NULL AND observation_id IS NULL "
            "AND weekly_plan_id IS NULL "
            "AND listening_record_id IS NULL AND listening_domain IS NULL "
            "AND listening_group_id IS NULL) "
            "OR "
            "(source_kind = 'curriculum_deliberation' "
            "AND task_type IN ('curriculum_split', 'curriculum_review', "
            "'curriculum_edit') "
            "AND daily_plan_id IS NULL AND observation_id IS NULL "
            "AND weekly_plan_id IS NULL "
            "AND listening_record_id IS NULL AND listening_domain IS NULL "
            "AND listening_group_id IS NULL)",
            name="ck_local_ai_candidates_source_match",
        ),
        CheckConstraint(
            "source_kind = 'one_to_one_listening' "
            "OR (listening_record_id IS NULL "
            "AND listening_domain IS NULL "
            "AND listening_group_id IS NULL)",
            name="ck_local_ai_aicandidate_listening_columns",
        ),
        ForeignKeyConstraint(
            ["execution_id", "task_id", "daily_plan_id", "input_id", "task_type"],
            [
                "local_ai_executions.id",
                "local_ai_executions.task_id",
                "local_ai_executions.daily_plan_id",
                "local_ai_executions.input_id",
                "local_ai_executions.task_type",
            ],
            name="fk_local_ai_candidates_execution",
        ),
        ForeignKeyConstraint(
            ["profile_id", "source_kind", "source_id", "execution_id",
             "task_id", "input_id", "task_type"],
            [
                "local_ai_executions.profile_id",
                "local_ai_executions.source_kind",
                "local_ai_executions.source_id",
                "local_ai_executions.id",
                "local_ai_executions.task_id",
                "local_ai_executions.input_id",
                "local_ai_executions.task_type",
            ],
            name="fk_local_ai_candidates_source_execution",
        ),
        ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_ai_candidates_profile_id",
        ),
        ForeignKeyConstraint(
            ["profile_id", "weekly_plan_id"],
            ["local_weekly_plans.profile_id", "local_weekly_plans.id"],
            name="fk_local_ai_candidates_weekly_plan",
        ),
        ForeignKeyConstraint(
            ["profile_id", "listening_record_id"],
            ["local_listening_records.profile_id", "local_listening_records.id"],
            name="fk_local_ai_candidates_listening_record",
        ),
        ForeignKeyConstraint(
            ["listening_record_id", "listening_domain"],
            ["local_listening_domains.record_id", "local_listening_domains.domain"],
            name="fk_local_ai_candidates_listening_domain",
        ),
        ForeignKeyConstraint(
            ["listening_record_id", "listening_domain", "listening_group_id"],
            [
                "local_listening_photo_groups.record_id",
                "local_listening_photo_groups.domain",
                "local_listening_photo_groups.id",
            ],
            name="fk_local_ai_candidates_listening_group",
        ),
        UniqueConstraint(
            "execution_id", name="uq_local_ai_candidates_execution"
        ),
        UniqueConstraint(
            "daily_plan_id", "id", name="uq_local_ai_candidates_plan_id",
        ),
        UniqueConstraint(
            "profile_id", "source_kind", "source_id", "id",
            name="uq_local_ai_candidates_source_id",
        ),
        Index(
            "ix_local_ai_candidates_source_created",
            "profile_id", "source_kind", "source_id", "created_at",
        ),
        Index(
            "ix_local_ai_candidates_plan_created",
            "daily_plan_id", "created_at", "id",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    execution_id: Mapped[str] = mapped_column(String(32), nullable=False)
    task_id: Mapped[str] = mapped_column(String(32), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    observation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    daily_plan_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    weekly_plan_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    listening_record_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    listening_domain: Mapped[str | None] = mapped_column(String(20), nullable=True)
    listening_group_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    input_id: Mapped[str] = mapped_column(String(32), nullable=False)
    task_type: Mapped[str] = mapped_column(String(40), nullable=False)
    contract_version: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_candidate_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    candidate_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalDailyPlanAIProvenance(LocalBase):
    """Content-to-candidate linkage for AI adoption."""

    __tablename__ = "local_daily_plan_ai_provenance"
    __table_args__ = (
        ForeignKeyConstraint(
            ["daily_plan_id", "content_id", "content_version"],
            [
                "local_daily_plan_contents.daily_plan_id",
                "local_daily_plan_contents.id",
                "local_daily_plan_contents.version",
            ],
            name="fk_local_daily_plan_ai_provenance_content_triple",
        ),
        ForeignKeyConstraint(
            ["daily_plan_id", "baseline_candidate_id"],
            [
                "local_ai_candidates.daily_plan_id",
                "local_ai_candidates.id",
            ],
            name="fk_local_daily_plan_ai_provenance_baseline",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["daily_plan_id", "adopted_candidate_id"],
            [
                "local_ai_candidates.daily_plan_id",
                "local_ai_candidates.id",
            ],
            name="fk_local_daily_plan_ai_provenance_adopted",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    content_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    daily_plan_id: Mapped[str] = mapped_column(String(32), nullable=False)
    content_version: Mapped[int] = mapped_column(Integer, nullable=False)
    baseline_candidate_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    adopted_candidate_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    selected_targets_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    adopted_payload_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalDailyPlanRestore(LocalBase):
    """D3-A whole-plan restore event and its idempotent receipt."""

    __tablename__ = "local_daily_plan_restores"
    __table_args__ = (
        CheckConstraint(
            "source_content_version >= 1 AND before_content_version >= 1 "
            "AND result_content_version >= 1",
            name="ck_local_daily_plan_restores_versions",
        ),
        UniqueConstraint(
            "profile_id", "request_id",
            name="uq_local_daily_plan_restores_profile_request",
        ),
        UniqueConstraint(
            "result_content_id",
            name="uq_local_daily_plan_restores_result_content",
        ),
        ForeignKeyConstraint(
            ["profile_id"], ["local_profile.id"],
            name="fk_local_daily_plan_restores_profile",
        ),
        ForeignKeyConstraint(
            ["daily_plan_id"], ["local_daily_plans.id"],
            name="fk_local_daily_plan_restores_plan",
        ),
        ForeignKeyConstraint(
            ["daily_plan_id", "source_content_id", "source_content_version"],
            [
                "local_daily_plan_contents.daily_plan_id",
                "local_daily_plan_contents.id",
                "local_daily_plan_contents.version",
            ],
            name="fk_local_daily_plan_restores_source_triple",
        ),
        ForeignKeyConstraint(
            ["daily_plan_id", "before_content_id", "before_content_version"],
            [
                "local_daily_plan_contents.daily_plan_id",
                "local_daily_plan_contents.id",
                "local_daily_plan_contents.version",
            ],
            name="fk_local_daily_plan_restores_before_triple",
        ),
        ForeignKeyConstraint(
            ["daily_plan_id", "result_content_id", "result_content_version"],
            [
                "local_daily_plan_contents.daily_plan_id",
                "local_daily_plan_contents.id",
                "local_daily_plan_contents.version",
            ],
            name="fk_local_daily_plan_restores_result_triple",
        ),
        Index("ix_local_daily_plan_restores_plan", "daily_plan_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    daily_plan_id: Mapped[str] = mapped_column(String(32), nullable=False)
    source_content_id: Mapped[str] = mapped_column(String(32), nullable=False)
    source_content_version: Mapped[int] = mapped_column(Integer, nullable=False)
    before_content_id: Mapped[str] = mapped_column(String(32), nullable=False)
    before_content_version: Mapped[int] = mapped_column(Integer, nullable=False)
    result_content_id: Mapped[str] = mapped_column(String(32), nullable=False)
    result_content_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalAIOperation(LocalBase):
    """Committed D2 AI operation receipt: idempotent read-back by request_id."""

    __tablename__ = "local_ai_operations"
    __table_args__ = (
        CheckConstraint(
            "fingerprint_kind IN ('sha256', 'hmac_sha256')",
            name="ck_local_ai_operations_fingerprint_kind",
        ),
        CheckConstraint(
            "(fingerprint_kind <> 'hmac_sha256') OR (fingerprint_key_id IS NOT NULL)",
            name="ck_local_ai_operations_hmac_key_id",
        ),
        # Any non-NULL fingerprint_key_id (mandatory for HMAC receipts) must be
        # a non-empty URL-safe opaque token of 1..64 chars, never a path. The
        # typeof/instr guards stop embedded-NUL truncation and BLOB bypasses.
        CheckConstraint(
            "fingerprint_key_id IS NULL OR (typeof(fingerprint_key_id) = 'text' "
            "AND instr(fingerprint_key_id, char(0)) = 0 "
            "AND length(fingerprint_key_id) BETWEEN 1 AND 64 "
            "AND fingerprint_key_id NOT GLOB '*[^A-Za-z0-9_-]*')",
            name="ck_local_ai_operations_fingerprint_key_id_shape",
        ),
        ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_ai_operations_profile_id",
        ),
        UniqueConstraint(
            "profile_id", "request_id",
            name="uq_local_ai_operations_profile_request",
        ),
        UniqueConstraint(
            "profile_id", "id",
            name="uq_local_ai_operations_profile_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    operation_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    fingerprint_key_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


# ---------------------------------------------------------------------------
# D4-E observation persistence (E01/E02/E04 data foundation only)
# ---------------------------------------------------------------------------


class LocalObservationRecord(LocalBase):
    """Stable observation identity plus list/search projection."""

    __tablename__ = "local_observation_records"
    __table_args__ = (
        CheckConstraint(
            "record_type IN ('public', 'indoor', 'outdoor')",
            name="ck_local_observation_records_type",
        ),
        CheckConstraint(
            "typeof(current_draft_revision) = 'integer' "
            "AND current_draft_revision >= 1",
            name="ck_local_observation_records_draft_revision",
        ),
        CheckConstraint(
            "current_version IS NULL OR "
            "(typeof(current_version) = 'integer' AND current_version >= 1)",
            name="ck_local_observation_records_version",
        ),
        CheckConstraint(
            "adult_count IS NULL OR "
            "(typeof(adult_count) = 'integer' AND adult_count >= 0)",
            name="ck_local_observation_records_adult_count",
        ),
        CheckConstraint(
            "child_count IS NULL OR "
            "(typeof(child_count) = 'integer' AND child_count >= 0)",
            name="ck_local_observation_records_child_count",
        ),
        CheckConstraint(
            "age_years IS NULL OR "
            "(typeof(age_years) = 'integer' AND age_years >= 0)",
            name="ck_local_observation_records_age",
        ),
        ForeignKeyConstraint(
            ["creator_profile_id"],
            ["local_profile.id"],
            name="fk_local_observation_records_profile",
        ),
        ForeignKeyConstraint(
            ["term_id"],
            ["local_terms.id"],
            name="fk_local_observation_records_term",
        ),
        ForeignKeyConstraint(
            ["id", "current_version"],
            ["local_observation_versions.observation_id",
             "local_observation_versions.version"],
            name="fk_local_observation_records_current_version",
            deferrable=True,
            initially="DEFERRED",
        ),
        UniqueConstraint(
            "creator_profile_id", "id",
            name="uq_local_observation_records_profile_id",
        ),
        Index(
            "ix_local_observation_records_profile_date",
            "creator_profile_id", "observation_date", "id",
        ),
        Index(
            "ix_local_observation_records_term_date",
            "term_id", "observation_date", "id",
        ),
        Index(
            "ix_local_observation_records_type_date",
            "record_type", "observation_date", "id",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    creator_profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    observation_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    record_type: Mapped[str] = mapped_column(String(20), nullable=False)
    start_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    end_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    term_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    term_snapshot_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    school_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    class_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    observer_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    adult_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    child_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    age_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    subjects_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    environment: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_draft_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    current_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalObservationDraft(LocalBase):
    """The only current content authority for one observation."""

    __tablename__ = "local_observation_drafts"
    __table_args__ = (
        CheckConstraint(
            "typeof(revision) = 'integer' AND revision >= 1",
            name="ck_local_observation_drafts_revision",
        ),
        ForeignKeyConstraint(
            ["observation_id"],
            ["local_observation_records.id"],
            name="fk_local_observation_drafts_record",
        ),
    )

    observation_id: Mapped[str] = mapped_column(
        String(32), primary_key=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalObservationVersion(LocalBase):
    """Immutable retained observation history version."""

    __tablename__ = "local_observation_versions"
    __table_args__ = (
        CheckConstraint(
            "typeof(version) = 'integer' AND version >= 1",
            name="ck_local_observation_versions_version",
        ),
        CheckConstraint(
            "source_kind IN ('manual', 'restore', 'adopt', 'retain')",
            name="ck_local_observation_versions_source_kind",
        ),
        ForeignKeyConstraint(
            ["observation_id"],
            ["local_observation_records.id"],
            name="fk_local_observation_versions_record",
        ),
        ForeignKeyConstraint(
            ["creator_profile_id"],
            ["local_profile.id"],
            name="fk_local_observation_versions_profile",
        ),
        UniqueConstraint(
            "observation_id", "version",
            name="uq_local_observation_versions_record_version",
        ),
        UniqueConstraint(
            "observation_id", "id",
            name="uq_local_observation_versions_record_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    observation_id: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    creator_profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalObservationAsset(LocalBase):
    """Immutable managed original image (no external path is stored)."""

    __tablename__ = "local_observation_assets"
    __table_args__ = (
        CheckConstraint(
            "typeof(byte_size) = 'integer' AND byte_size >= 0",
            name="ck_local_observation_assets_size",
        ),
        CheckConstraint(
            "typeof(width) = 'integer' AND typeof(height) = 'integer' "
            "AND width >= 0 AND height >= 0",
            name="ck_local_observation_assets_dimensions",
        ),
        ForeignKeyConstraint(
            ["observation_id"],
            ["local_observation_records.id"],
            name="fk_local_observation_assets_record",
        ),
        UniqueConstraint(
            "observation_id", "id",
            name="uq_local_observation_assets_record_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    observation_id: Mapped[str] = mapped_column(String(32), nullable=False)
    relative_path: Mapped[str] = mapped_column(String(500), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    orientation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalObservationAssetDerivative(LocalBase):
    """Append-only AI/export working copy of one original asset."""

    __tablename__ = "local_observation_asset_derivatives"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('ai', 'export')",
            name="ck_local_observation_asset_derivatives_purpose",
        ),
        CheckConstraint(
            "typeof(width) = 'integer' AND typeof(height) = 'integer' "
            "AND width >= 0 AND height >= 0",
            name="ck_local_observation_asset_derivatives_dimensions",
        ),
        ForeignKeyConstraint(
            ["observation_id", "asset_id"],
            ["local_observation_assets.observation_id",
             "local_observation_assets.id"],
            name="fk_local_observation_asset_derivatives_asset",
        ),
        UniqueConstraint(
            "observation_id", "id",
            name="uq_local_observation_asset_derivatives_record_id",
        ),
        UniqueConstraint(
            "observation_id", "asset_id", "id",
            name="uq_local_observation_asset_derivatives_asset_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    observation_id: Mapped[str] = mapped_column(String(32), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(32), nullable=False)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    params_version: Mapped[str] = mapped_column(String(50), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    relative_path: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalObservationDraftPhoto(LocalBase):
    """Ordered current photo association; removing does not delete the asset."""

    __tablename__ = "local_observation_draft_photos"
    __table_args__ = (
        CheckConstraint(
            "typeof(sort_order) = 'integer' AND sort_order >= 0",
            name="ck_local_observation_draft_photos_order",
        ),
        ForeignKeyConstraint(
            ["observation_id", "asset_id"],
            ["local_observation_assets.observation_id",
             "local_observation_assets.id"],
            name="fk_local_observation_draft_photos_asset",
        ),
        UniqueConstraint(
            "observation_id", "sort_order",
            name="uq_local_observation_draft_photos_order",
        ),
    )

    observation_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    asset_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)


class LocalObservationVersionPhoto(LocalBase):
    """Immutable ordered photo reference for one retained version."""

    __tablename__ = "local_observation_version_photos"
    __table_args__ = (
        CheckConstraint(
            "typeof(sort_order) = 'integer' AND sort_order >= 0",
            name="ck_local_observation_version_photos_order",
        ),
        ForeignKeyConstraint(
            ["observation_id", "version_id"],
            ["local_observation_versions.observation_id",
             "local_observation_versions.id"],
            name="fk_local_observation_version_photos_version",
        ),
        ForeignKeyConstraint(
            ["observation_id", "asset_id"],
            ["local_observation_assets.observation_id",
             "local_observation_assets.id"],
            name="fk_local_observation_version_photos_asset",
        ),
        UniqueConstraint(
            "version_id", "sort_order",
            name="uq_local_observation_version_photos_order",
        ),
    )

    version_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    asset_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    observation_id: Mapped[str] = mapped_column(String(32), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)


class LocalObservationOperation(LocalBase):
    """Observation business idempotency envelope (not a content authority)."""

    __tablename__ = "local_observation_operations"
    __table_args__ = (
        CheckConstraint(
            "length(request_id) BETWEEN 1 AND 36",
            name="ck_local_observation_operations_request_id",
        ),
        CheckConstraint(
            "length(request_fingerprint) = 64",
            name="ck_local_observation_operations_fingerprint",
        ),
        CheckConstraint(
            "status IN ('committed', 'failed')",
            name="ck_local_observation_operations_status",
        ),
        ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_observation_operations_profile",
        ),
        ForeignKeyConstraint(
            ["profile_id", "observation_id"],
            ["local_observation_records.creator_profile_id",
             "local_observation_records.id"],
            name="fk_local_observation_operations_record",
        ),
        UniqueConstraint(
            "profile_id", "request_id",
            name="uq_local_observation_operations_profile_request",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    operation_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    observation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalObservationRestore(LocalBase):
    """Restore detail row; the idempotency receipt is the linked operation."""

    __tablename__ = "local_observation_restores"
    __table_args__ = (
        CheckConstraint(
            "typeof(source_version) = 'integer' AND source_version >= 1 "
            "AND typeof(result_version) = 'integer' AND result_version >= 1 "
            "AND typeof(before_draft_revision) = 'integer' "
            "AND before_draft_revision >= 1",
            name="ck_local_observation_restores_versions",
        ),
        CheckConstraint(
            "before_version IS NULL OR "
            "(typeof(before_version) = 'integer' AND before_version >= 1)",
            name="ck_local_observation_restores_before_version",
        ),
        CheckConstraint(
            "changed IN (0, 1)",
            name="ck_local_observation_restores_changed",
        ),
        CheckConstraint(
            "term_decision IN ('keep_history', 'keep_current', "
            "'assign_selected', 'unassigned')",
            name="ck_local_observation_restores_term_decision",
        ),
        ForeignKeyConstraint(
            ["operation_id"],
            ["local_observation_operations.id"],
            name="fk_local_observation_restores_operation",
        ),
        ForeignKeyConstraint(
            ["observation_id", "source_version"],
            ["local_observation_versions.observation_id",
             "local_observation_versions.version"],
            name="fk_local_observation_restores_source_version",
        ),
        ForeignKeyConstraint(
            ["observation_id", "result_version"],
            ["local_observation_versions.observation_id",
             "local_observation_versions.version"],
            name="fk_local_observation_restores_result_version",
        ),
        UniqueConstraint(
            "operation_id",
            name="uq_local_observation_restores_operation",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    operation_id: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    observation_id: Mapped[str] = mapped_column(String(32), nullable=False)
    source_version: Mapped[int] = mapped_column(Integer, nullable=False)
    result_version: Mapped[int] = mapped_column(Integer, nullable=False)
    before_draft_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    before_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    changed: Mapped[int] = mapped_column(Integer, nullable=False)
    term_decision: Mapped[str] = mapped_column(String(20), nullable=False)
    effective_term_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    effective_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalObservationRestorePreview(LocalBase):
    """One-time restore preview binding; not a business commit."""

    __tablename__ = "local_observation_restore_previews"
    __table_args__ = (
        CheckConstraint(
            "typeof(source_version) = 'integer' AND source_version >= 1 "
            "AND typeof(base_draft_revision) = 'integer' "
            "AND base_draft_revision >= 1",
            name="ck_local_observation_restore_previews_versions",
        ),
        ForeignKeyConstraint(
            ["observation_id", "source_version"],
            ["local_observation_versions.observation_id",
             "local_observation_versions.version"],
            name="fk_local_observation_restore_previews_source",
        ),
        UniqueConstraint(
            "token_hash",
            name="uq_local_observation_restore_previews_token",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    observation_id: Mapped[str] = mapped_column(String(32), nullable=False)
    source_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    base_draft_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    base_draft_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_term_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    term_snapshot_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    effective_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    material_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalObservationAIProvenance(LocalBase):
    """Ledger proving which candidate output was adopted into a version."""

    __tablename__ = "local_observation_ai_provenance"
    __table_args__ = (
        CheckConstraint(
            "source_kind = 'game_observation' AND source_id = observation_id",
            name="ck_local_observation_ai_provenance_source",
        ),
        CheckConstraint(
            "typeof(version) = 'integer' AND version >= 1",
            name="ck_local_observation_ai_provenance_version",
        ),
        ForeignKeyConstraint(
            ["observation_id", "version"],
            ["local_observation_versions.observation_id",
             "local_observation_versions.version"],
            name="fk_local_observation_ai_provenance_version",
        ),
        ForeignKeyConstraint(
            ["profile_id", "source_kind", "source_id", "candidate_id"],
            ["local_ai_candidates.profile_id",
             "local_ai_candidates.source_kind",
             "local_ai_candidates.source_id",
             "local_ai_candidates.id"],
            name="fk_local_observation_ai_provenance_candidate",
        ),
        UniqueConstraint(
            "observation_id", "version", "candidate_id",
            name="uq_local_observation_ai_provenance_version_candidate",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    source_id: Mapped[str] = mapped_column(String(32), nullable=False)
    observation_id: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_id: Mapped[str] = mapped_column(String(32), nullable=False)
    adopted_targets_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    output_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalObservationAIInputPhoto(LocalBase):
    """Frozen ordered photo/derivative reference for one observation input."""

    __tablename__ = "local_observation_ai_input_photos"
    __table_args__ = (
        CheckConstraint(
            "source_kind = 'game_observation' "
            "AND observation_id IS NOT NULL "
            "AND source_id = observation_id",
            name="ck_local_observation_ai_input_photos_source",
        ),
        CheckConstraint(
            "typeof(sort_order) = 'integer' AND sort_order >= 0",
            name="ck_local_observation_ai_input_photos_order",
        ),
        ForeignKeyConstraint(
            ["profile_id", "source_kind", "source_id", "input_id"],
            ["local_ai_inputs.profile_id",
             "local_ai_inputs.source_kind",
             "local_ai_inputs.source_id",
             "local_ai_inputs.id"],
            name="fk_local_observation_ai_input_photos_input",
        ),
        ForeignKeyConstraint(
            ["observation_id", "asset_id"],
            ["local_observation_assets.observation_id",
             "local_observation_assets.id"],
            name="fk_local_observation_ai_input_photos_asset",
        ),
        ForeignKeyConstraint(
            ["observation_id", "asset_id", "derivative_id"],
            ["local_observation_asset_derivatives.observation_id",
             "local_observation_asset_derivatives.asset_id",
             "local_observation_asset_derivatives.id"],
            name="fk_local_observation_ai_input_photos_derivative",
        ),
        UniqueConstraint(
            "input_id", "sort_order",
            name="uq_local_observation_ai_input_photos_order",
        ),
        UniqueConstraint(
            "input_id", "asset_id",
            name="uq_local_observation_ai_input_photos_asset",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    source_id: Mapped[str] = mapped_column(String(32), nullable=False)
    observation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    input_id: Mapped[str] = mapped_column(String(32), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(32), nullable=False)
    derivative_id: Mapped[str] = mapped_column(String(32), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    work_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class LocalObservationExportSnapshot(LocalBase):
    """Frozen export manifest; snapshot_id is not a bearer credential."""

    __tablename__ = "local_observation_export_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_observation_export_snapshots_profile",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    launch_id: Mapped[str] = mapped_column(String(36), nullable=False)
    session_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)


class LocalObservationExportToken(LocalBase):
    """Restricted one-time export bearer token (stored only as a digest)."""

    __tablename__ = "local_observation_export_tokens"
    __table_args__ = (
        ForeignKeyConstraint(
            ["snapshot_id"],
            ["local_observation_export_snapshots.id"],
            name="fk_local_observation_export_tokens_snapshot",
        ),
        UniqueConstraint(
            "token_hash",
            name="uq_local_observation_export_tokens_hash",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalObservationExportAttempt(LocalBase):
    """Host-reported save attempt; external IO is the result source."""

    __tablename__ = "local_observation_export_attempts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('in_progress', 'saved', 'cancelled', 'failed', "
            "'indeterminate')",
            name="ck_local_observation_export_attempts_status",
        ),
        CheckConstraint(
            "byte_size IS NULL OR "
            "(typeof(byte_size) = 'integer' AND byte_size >= 0)",
            name="ck_local_observation_export_attempts_size",
        ),
        ForeignKeyConstraint(
            ["snapshot_id"],
            ["local_observation_export_snapshots.id"],
            name="fk_local_observation_export_attempts_snapshot",
        ),
        UniqueConstraint(
            "profile_id", "export_id_hash",
            name="uq_local_observation_export_attempts_profile_export",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    snapshot_id: Mapped[str] = mapped_column(String(32), nullable=False)
    export_id_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    filename_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    result_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


# ---------------------------------------------------------------------------
# Desktop weekly plans (engineering spec §2.2)
# ---------------------------------------------------------------------------


class LocalWeeklyPlan(LocalBase):
    """Immutable weekly-plan identity plus current draft/confirmation pointers."""

    __tablename__ = "local_weekly_plans"
    __table_args__ = (
        CheckConstraint(
            "strftime('%w', week_anchor_date) = '1'",
            name="ck_local_weekly_plans_anchor_monday",
        ),
        CheckConstraint(
            "typeof(week_number_snapshot) = 'integer' "
            "AND week_number_snapshot >= 1",
            name="ck_local_weekly_plans_week_number",
        ),
        CheckConstraint(
            "typeof(current_draft_version) = 'integer' "
            "AND current_draft_version >= 1",
            name="ck_local_weekly_plans_draft_version",
        ),
        CheckConstraint(
            "current_confirmed_version IS NULL OR "
            "(typeof(current_confirmed_version) = 'integer' "
            "AND current_confirmed_version >= 1)",
            name="ck_local_weekly_plans_confirmed_version",
        ),
        CheckConstraint(
            "(current_confirmed_id IS NULL AND current_confirmed_version IS NULL) "
            "OR (current_confirmed_id IS NOT NULL "
            "AND current_confirmed_version IS NOT NULL)",
            name="ck_local_weekly_plans_confirmed_pair",
        ),
        CheckConstraint(
            "term_start_date <= term_end_date",
            name="ck_local_weekly_plans_term_order",
        ),
        CheckConstraint(
            "length(header_hash) = 64",
            name="ck_local_weekly_plans_header_hash",
        ),
        ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_weekly_plans_profile",
        ),
        ForeignKeyConstraint(
            ["class_id"],
            ["local_classes.id"],
            name="fk_local_weekly_plans_class",
        ),
        ForeignKeyConstraint(
            ["term_id"],
            ["local_terms.id"],
            name="fk_local_weekly_plans_term",
        ),
        ForeignKeyConstraint(
            ["term_id", "calendar_revision_id"],
            ["local_calendar_revisions.term_id", "local_calendar_revisions.id"],
            name="fk_local_weekly_plans_term_revision",
        ),
        UniqueConstraint(
            "class_id", "term_id", "week_anchor_date",
            name="uq_local_weekly_plans_class_term_week",
        ),
        UniqueConstraint(
            "profile_id", "id", name="uq_local_weekly_plans_profile_id"
        ),
        ForeignKeyConstraint(
            ["id", "current_draft_id", "current_draft_version"],
            [
                "local_weekly_plan_contents.weekly_plan_id",
                "local_weekly_plan_contents.id",
                "local_weekly_plan_contents.version",
            ],
            name="fk_local_weekly_plans_current_draft",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["id", "current_confirmed_id", "current_confirmed_version"],
            [
                "local_weekly_plan_confirmations.weekly_plan_id",
                "local_weekly_plan_confirmations.id",
                "local_weekly_plan_confirmations.version",
            ],
            name="fk_local_weekly_plans_current_confirmed",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    class_id: Mapped[str] = mapped_column(String(32), nullable=False)
    term_id: Mapped[str] = mapped_column(String(32), nullable=False)
    week_anchor_date: Mapped[date] = mapped_column(Date, nullable=False)
    week_number_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    term_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    term_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    calendar_revision_id: Mapped[str] = mapped_column(String(32), nullable=False)
    header_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    header_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    current_draft_id: Mapped[str] = mapped_column(String(32), nullable=False)
    current_draft_version: Mapped[int] = mapped_column(Integer, nullable=False)
    current_confirmed_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    current_confirmed_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalWeeklyPlanContent(LocalBase):
    """Append-only weekly draft content version."""

    __tablename__ = "local_weekly_plan_contents"
    __table_args__ = (
        CheckConstraint(
            "typeof(version) = 'integer' AND version >= 1",
            name="ck_local_weekly_plan_contents_version",
        ),
        CheckConstraint(
            "typeof(schema_version) = 'integer' AND schema_version IN (1, 2)",
            name="ck_local_weekly_plan_contents_schema_version",
        ),
        CheckConstraint(
            "length(content_hash) = 64",
            name="ck_local_weekly_plan_contents_hash",
        ),
        ForeignKeyConstraint(
            ["weekly_plan_id"],
            ["local_weekly_plans.id"],
            name="fk_local_weekly_plan_contents_plan",
        ),
        ForeignKeyConstraint(
            ["editor_profile_id"],
            ["local_profile.id"],
            name="fk_local_weekly_plan_contents_editor",
        ),
        UniqueConstraint(
            "weekly_plan_id", "version",
            name="uq_local_weekly_plan_contents_plan_version",
        ),
        UniqueConstraint(
            "weekly_plan_id", "id", "version",
            name="uq_local_weekly_plan_contents_plan_id_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    weekly_plan_id: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    editor_profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalWeeklyPlanAIAdoption(LocalBase):
    """One atomic AI adoption event per target and resulting draft."""

    __tablename__ = "local_weekly_plan_ai_adoption"
    __table_args__ = (
        CheckConstraint(
            "source_kind = 'weekly_plan'",
            name="ck_local_weekly_plan_ai_adoption_source",
        ),
        CheckConstraint(
            "target_key IN ('games', 'key_week_focus', 'environment_setup', "
            "'habit_culture', 'home_cooperation', 'materials')",
            name="ck_local_weekly_plan_ai_adoption_target",
        ),
        CheckConstraint(
            "typeof(draft_version) = 'integer' AND draft_version >= 1",
            name="ck_local_weekly_plan_ai_adoption_version",
        ),
        CheckConstraint(
            "length(before_hash) = 64 AND length(after_hash) = 64",
            name="ck_local_weekly_plan_ai_adoption_hash",
        ),
        ForeignKeyConstraint(
            ["profile_id", "weekly_plan_id"],
            ["local_weekly_plans.profile_id", "local_weekly_plans.id"],
            name="fk_local_weekly_plan_ai_adoption_plan",
        ),
        ForeignKeyConstraint(
            ["weekly_plan_id", "draft_id", "draft_version"],
            [
                "local_weekly_plan_contents.weekly_plan_id",
                "local_weekly_plan_contents.id",
                "local_weekly_plan_contents.version",
            ],
            name="fk_local_weekly_plan_ai_adoption_draft",
        ),
        ForeignKeyConstraint(
            ["profile_id", "source_kind", "weekly_plan_id", "candidate_id"],
            [
                "local_ai_candidates.profile_id",
                "local_ai_candidates.source_kind",
                "local_ai_candidates.source_id",
                "local_ai_candidates.id",
            ],
            name="fk_local_weekly_plan_ai_adoption_candidate",
        ),
        ForeignKeyConstraint(
            ["profile_id", "operation_id"],
            ["local_ai_operations.profile_id", "local_ai_operations.id"],
            name="fk_local_weekly_plan_ai_adoption_operation",
        ),
        UniqueConstraint(
            "draft_id", "target_key",
            name="uq_local_weekly_plan_ai_adoption_draft_target",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    weekly_plan_id: Mapped[str] = mapped_column(String(32), nullable=False)
    draft_id: Mapped[str] = mapped_column(String(32), nullable=False)
    draft_version: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_id: Mapped[str] = mapped_column(String(32), nullable=False)
    target_key: Mapped[str] = mapped_column(String(32), nullable=False)
    before_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    after_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    operation_id: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalListeningAIAdoption(LocalBase):
    """One adopted AI target on one listening group or domain revision."""

    __tablename__ = "local_listening_ai_adoption"
    __table_args__ = (
        CheckConstraint(
            "source_kind = 'one_to_one_listening'",
            name="ck_local_listening_ai_adoption_source",
        ),
        CheckConstraint(
            "target_key IN ('listening_text', 'overall_evaluation', "
            "'support_strategy', 'goal') OR target_key GLOB 'health_[0-9]*' "
            "OR target_key GLOB 'language_[0-9]*' "
            "OR target_key GLOB 'social_[0-9]*' "
            "OR target_key GLOB 'science_[0-9]*' "
            "OR target_key GLOB 'art_[0-9]*'",
            name="ck_local_listening_ai_adoption_target",
        ),
        CheckConstraint(
            "length(before_hash) = 64 AND length(after_hash) = 64",
            name="ck_local_listening_ai_adoption_hash",
        ),
        CheckConstraint(
            "typeof(revision_before) = 'integer' AND revision_before >= 1 "
            "AND typeof(revision_after) = 'integer' AND revision_after >= 1",
            name="ck_local_listening_ai_adoption_revision",
        ),
        ForeignKeyConstraint(
            ["profile_id", "record_id"],
            ["local_listening_records.profile_id", "local_listening_records.id"],
            name="fk_local_listening_ai_adoption_record",
        ),
        ForeignKeyConstraint(
            ["record_id", "domain"],
            ["local_listening_domains.record_id", "local_listening_domains.domain"],
            name="fk_local_listening_ai_adoption_domain",
        ),
        ForeignKeyConstraint(
            ["record_id", "domain", "group_id"],
            [
                "local_listening_photo_groups.record_id",
                "local_listening_photo_groups.domain",
                "local_listening_photo_groups.id",
            ],
            name="fk_local_listening_ai_adoption_group",
        ),
        ForeignKeyConstraint(
            ["profile_id", "source_kind", "record_id", "candidate_id"],
            [
                "local_ai_candidates.profile_id",
                "local_ai_candidates.source_kind",
                "local_ai_candidates.source_id",
                "local_ai_candidates.id",
            ],
            name="fk_local_listening_ai_adoption_candidate",
        ),
        ForeignKeyConstraint(
            ["profile_id", "operation_id"],
            ["local_ai_operations.profile_id", "local_ai_operations.id"],
            name="fk_local_listening_ai_adoption_operation",
        ),
        UniqueConstraint(
            "record_id", "domain", "scope_key", "target_key", "revision_after",
            name="uq_local_listening_ai_adoption_revision_target",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    record_id: Mapped[str] = mapped_column(String(32), nullable=False)
    domain: Mapped[str] = mapped_column(String(20), nullable=False)
    group_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    scope_key: Mapped[str] = mapped_column(String(32), nullable=False)
    target_key: Mapped[str] = mapped_column(String(80), nullable=False)
    candidate_id: Mapped[str] = mapped_column(String(32), nullable=False)
    input_id: Mapped[str] = mapped_column(String(32), nullable=False)
    before_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    after_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    revision_before: Mapped[int] = mapped_column(Integer, nullable=False)
    revision_after: Mapped[int] = mapped_column(Integer, nullable=False)
    operation_id: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalWeeklyPlanConfirmation(LocalBase):
    """Immutable confirmation snapshot of one exact draft version."""

    __tablename__ = "local_weekly_plan_confirmations"
    __table_args__ = (
        CheckConstraint(
            "typeof(version) = 'integer' AND version >= 1",
            name="ck_local_weekly_plan_confirmations_version",
        ),
        CheckConstraint(
            "typeof(draft_version) = 'integer' AND draft_version >= 1",
            name="ck_local_weekly_plan_confirmations_draft_version",
        ),
        CheckConstraint(
            "schema_version = 1",
            name="ck_local_weekly_plan_confirmations_schema_version",
        ),
        CheckConstraint(
            "length(snapshot_hash) = 64",
            name="ck_local_weekly_plan_confirmations_snapshot_hash",
        ),
        CheckConstraint(
            "length(facts_hash) = 64",
            name="ck_local_weekly_plan_confirmations_facts_hash",
        ),
        ForeignKeyConstraint(
            ["weekly_plan_id"],
            ["local_weekly_plans.id"],
            name="fk_local_weekly_plan_confirmations_plan",
        ),
        ForeignKeyConstraint(
            ["confirmed_by"],
            ["local_profile.id"],
            name="fk_local_weekly_plan_confirmations_profile",
        ),
        ForeignKeyConstraint(
            ["weekly_plan_id", "draft_id", "draft_version"],
            [
                "local_weekly_plan_contents.weekly_plan_id",
                "local_weekly_plan_contents.id",
                "local_weekly_plan_contents.version",
            ],
            name="fk_local_weekly_plan_confirmations_draft",
        ),
        UniqueConstraint(
            "weekly_plan_id", "version",
            name="uq_local_weekly_plan_confirmations_plan_version",
        ),
        UniqueConstraint(
            "weekly_plan_id", "id", "version",
            name="uq_local_weekly_plan_confirmations_plan_id_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    weekly_plan_id: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    draft_id: Mapped[str] = mapped_column(String(32), nullable=False)
    draft_version: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    facts_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    facts_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_by: Mapped[str] = mapped_column(String(32), nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalWeeklyPlanOperation(LocalBase):
    """Business/export idempotency receipt; never a content authority."""

    __tablename__ = "local_weekly_plan_operations"
    __table_args__ = (
        CheckConstraint(
            "length(request_id) BETWEEN 1 AND 36",
            name="ck_local_weekly_plan_operations_request_id",
        ),
        CheckConstraint(
            "length(input_fingerprint) = 64",
            name="ck_local_weekly_plan_operations_fingerprint",
        ),
        CheckConstraint(
            "action IN ('create', 'save', 'refresh', 'confirm', "
            "'export_create', 'export_retry')",
            name="ck_local_weekly_plan_operations_action",
        ),
        CheckConstraint(
            "result_draft_version IS NULL OR "
            "(typeof(result_draft_version) = 'integer' "
            "AND result_draft_version >= 1)",
            name="ck_local_weekly_plan_operations_draft_version",
        ),
        CheckConstraint(
            "result_confirmed_version IS NULL OR "
            "(typeof(result_confirmed_version) = 'integer' "
            "AND result_confirmed_version >= 1)",
            name="ck_local_weekly_plan_operations_confirmed_version",
        ),
        CheckConstraint(
            "(action IN ('create', 'save', 'refresh') "
            "AND weekly_plan_id IS NOT NULL "
            "AND result_draft_id IS NOT NULL "
            "AND result_draft_version IS NOT NULL "
            "AND result_confirmed_id IS NULL "
            "AND result_confirmed_version IS NULL "
            "AND result_snapshot_id IS NULL AND result_token_id IS NULL) "
            "OR (action = 'confirm' "
            "AND weekly_plan_id IS NOT NULL "
            "AND result_draft_id IS NOT NULL "
            "AND result_draft_version IS NOT NULL "
            "AND result_confirmed_id IS NOT NULL "
            "AND result_confirmed_version IS NOT NULL "
            "AND result_snapshot_id IS NULL AND result_token_id IS NULL) "
            "OR (action IN ('export_create', 'export_retry') "
            "AND weekly_plan_id IS NULL "
            "AND result_draft_id IS NULL AND result_draft_version IS NULL "
            "AND result_confirmed_id IS NULL "
            "AND result_confirmed_version IS NULL "
            "AND result_snapshot_id IS NOT NULL "
            "AND result_token_id IS NOT NULL "
            "AND launch_id IS NOT NULL "
            "AND session_scope_hash IS NOT NULL "
            "AND length(session_scope_hash) = 64)",
            name="ck_local_weekly_plan_operations_result_shape",
        ),
        ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_weekly_plan_operations_profile",
        ),
        ForeignKeyConstraint(
            ["profile_id", "weekly_plan_id"],
            ["local_weekly_plans.profile_id", "local_weekly_plans.id"],
            name="fk_local_weekly_plan_operations_plan",
        ),
        ForeignKeyConstraint(
            ["weekly_plan_id", "result_draft_id", "result_draft_version"],
            [
                "local_weekly_plan_contents.weekly_plan_id",
                "local_weekly_plan_contents.id",
                "local_weekly_plan_contents.version",
            ],
            name="fk_local_weekly_plan_operations_draft",
        ),
        ForeignKeyConstraint(
            ["weekly_plan_id", "result_confirmed_id",
             "result_confirmed_version"],
            [
                "local_weekly_plan_confirmations.weekly_plan_id",
                "local_weekly_plan_confirmations.id",
                "local_weekly_plan_confirmations.version",
            ],
            name="fk_local_weekly_plan_operations_confirmed",
        ),
        ForeignKeyConstraint(
            ["result_snapshot_id", "profile_id"],
            [
                "local_weekly_export_snapshots.id",
                "local_weekly_export_snapshots.profile_id",
            ],
            name="fk_local_weekly_plan_operations_snapshot",
        ),
        ForeignKeyConstraint(
            ["result_token_id", "profile_id"],
            [
                "local_weekly_export_tokens.id",
                "local_weekly_export_tokens.profile_id",
            ],
            name="fk_local_weekly_plan_operations_token",
        ),
        ForeignKeyConstraint(
            ["result_token_id", "profile_id", "result_snapshot_id"],
            [
                "local_weekly_export_tokens.id",
                "local_weekly_export_tokens.profile_id",
                "local_weekly_export_tokens.snapshot_id",
            ],
            name="fk_local_weekly_plan_operations_token_snapshot",
        ),
        UniqueConstraint(
            "profile_id", "request_id",
            name="uq_local_weekly_plan_operations_profile_request",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    weekly_plan_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    result_draft_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    result_draft_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    result_confirmed_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    result_confirmed_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    result_snapshot_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    result_token_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    launch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    session_scope_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalWeeklyExportSnapshot(LocalBase):
    """Frozen weekly export manifest; the id alone is not a credential."""

    __tablename__ = "local_weekly_export_snapshots"
    __table_args__ = (
        CheckConstraint(
            "length(manifest_hash) = 64",
            name="ck_local_weekly_export_snapshots_hash",
        ),
        ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_weekly_export_snapshots_profile",
        ),
        UniqueConstraint(
            "id", "profile_id",
            name="uq_local_weekly_export_snapshots_id_profile",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    launch_id: Mapped[str] = mapped_column(String(36), nullable=False)
    session_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False
    )


class LocalWeeklyExportToken(LocalBase):
    """Restricted export bearer token stored only as a digest."""

    __tablename__ = "local_weekly_export_tokens"
    __table_args__ = (
        CheckConstraint(
            "length(token_hash) = 64",
            name="ck_local_weekly_export_tokens_hash",
        ),
        ForeignKeyConstraint(
            ["snapshot_id", "profile_id"],
            [
                "local_weekly_export_snapshots.id",
                "local_weekly_export_snapshots.profile_id",
            ],
            name="fk_local_weekly_export_tokens_snapshot",
        ),
        ForeignKeyConstraint(
            ["profile_id", "snapshot_id", "parent_attempt_id"],
            [
                "local_weekly_export_attempts.profile_id",
                "local_weekly_export_attempts.snapshot_id",
                "local_weekly_export_attempts.id",
            ],
            name="fk_local_weekly_export_tokens_parent_attempt",
        ),
        UniqueConstraint(
            "token_hash", name="uq_local_weekly_export_tokens_hash"
        ),
        UniqueConstraint(
            "id", "profile_id",
            name="uq_local_weekly_export_tokens_id_profile",
        ),
        UniqueConstraint(
            "id", "profile_id", "snapshot_id",
            name="uq_local_weekly_export_tokens_id_profile_snapshot",
        ),
        Index(
            "uq_local_weekly_export_tokens_parent",
            "profile_id", "snapshot_id", "parent_attempt_id",
            unique=True,
            sqlite_where=text("parent_attempt_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    parent_attempt_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalWeeklyExportAttempt(LocalBase):
    """Host-reported native save attempt for one weekly export."""

    __tablename__ = "local_weekly_export_attempts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('in_progress', 'saved', 'cancelled', 'failed', "
            "'indeterminate')",
            name="ck_local_weekly_export_attempts_status",
        ),
        CheckConstraint(
            "byte_size IS NOT NULL AND "
            "(typeof(byte_size) = 'integer' AND byte_size >= 0)",
            name="ck_local_weekly_export_attempts_size",
        ),
        CheckConstraint(
            "(status = 'saved' AND byte_size > 0 "
            "AND result_hash IS NOT NULL AND length(result_hash) = 64) "
            "OR (status <> 'saved' AND byte_size = 0 "
            "AND result_hash IS NULL)",
            name="ck_local_weekly_export_attempts_result_shape",
        ),
        CheckConstraint(
            "length(export_id_hash) = 64",
            name="ck_local_weekly_export_attempts_export_hash",
        ),
        CheckConstraint(
            "length(filename_fingerprint) = 64",
            name="ck_local_weekly_export_attempts_filename",
        ),
        CheckConstraint(
            "result_hash IS NULL OR length(result_hash) = 64",
            name="ck_local_weekly_export_attempts_result_hash",
        ),
        ForeignKeyConstraint(
            ["snapshot_id", "profile_id"],
            [
                "local_weekly_export_snapshots.id",
                "local_weekly_export_snapshots.profile_id",
            ],
            name="fk_local_weekly_export_attempts_snapshot",
        ),
        ForeignKeyConstraint(
            ["token_id", "profile_id", "snapshot_id"],
            [
                "local_weekly_export_tokens.id",
                "local_weekly_export_tokens.profile_id",
                "local_weekly_export_tokens.snapshot_id",
            ],
            name="fk_local_weekly_export_attempts_token",
        ),
        UniqueConstraint(
            "profile_id", "export_id_hash",
            name="uq_local_weekly_export_attempts_profile_export",
        ),
        UniqueConstraint(
            "profile_id", "snapshot_id", "id",
            name="uq_local_weekly_export_attempts_profile_snapshot_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    snapshot_id: Mapped[str] = mapped_column(String(32), nullable=False)
    token_id: Mapped[str] = mapped_column(String(32), nullable=False)
    export_id_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    filename_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    result_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    byte_size: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


# ---------------------------------------------------------------------------
# One-to-one listening (L1: records, five domains, stable groups, assets)
# ---------------------------------------------------------------------------


class LocalListeningRecord(LocalBase):
    """Stable listening identity; five domain tables share one revision."""

    __tablename__ = "local_listening_records"
    __table_args__ = (
        CheckConstraint(
            "grade IN ('small', 'middle', 'large')",
            name="ck_local_listening_records_grade",
        ),
        CheckConstraint(
            "length(child_name) BETWEEN 1 AND 80",
            name="ck_local_listening_records_child_name",
        ),
        CheckConstraint(
            "typeof(revision) = 'integer' AND revision >= 1",
            name="ck_local_listening_records_revision",
        ),
        ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_listening_records_profile",
        ),
        ForeignKeyConstraint(
            ["class_id"],
            ["local_classes.id"],
            name="fk_local_listening_records_class",
        ),
        ForeignKeyConstraint(
            ["term_id"],
            ["local_terms.id"],
            name="fk_local_listening_records_term",
        ),
        UniqueConstraint(
            "profile_id", "id",
            name="uq_local_listening_records_profile_id",
        ),
        Index(
            "ix_local_listening_records_profile_class_term",
            "profile_id", "class_id", "term_id", "id",
        ),
        Index(
            "ix_local_listening_records_profile_name",
            "profile_id", "class_id", "term_id", "child_name",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    class_id: Mapped[str] = mapped_column(String(32), nullable=False)
    term_id: Mapped[str] = mapped_column(String(32), nullable=False)
    grade: Mapped[str] = mapped_column(String(20), nullable=False)
    child_name: Mapped[str] = mapped_column(String(80), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalListeningDomain(LocalBase):
    """One of the five domain forms of a listening record."""

    __tablename__ = "local_listening_domains"
    __table_args__ = (
        CheckConstraint(
            "domain IN ('health', 'language', 'social', 'science', 'art')",
            name="ck_local_listening_domains_domain",
        ),
        CheckConstraint(
            "length(template_version) BETWEEN 1 AND 20",
            name="ck_local_listening_domains_template_version",
        ),
        CheckConstraint(
            "length(template_sha256) = 64",
            name="ck_local_listening_domains_template_sha",
        ),
        CheckConstraint(
            "observation_date_text IS NULL "
            "OR length(observation_date_text) <= 120",
            name="ck_local_listening_domains_observation_date",
        ),
        CheckConstraint(
            "adult_count_text IS NULL OR length(adult_count_text) <= 80",
            name="ck_local_listening_domains_adult_count",
        ),
        CheckConstraint(
            "child_age_text IS NULL OR length(child_age_text) <= 80",
            name="ck_local_listening_domains_child_age",
        ),
        CheckConstraint(
            "goal IS NULL OR length(goal) <= 4000",
            name="ck_local_listening_domains_goal",
        ),
        CheckConstraint(
            "observation_area IS NULL OR length(observation_area) <= 4000",
            name="ck_local_listening_domains_area",
        ),
        CheckConstraint(
            "overall_evaluation IS NULL OR length(overall_evaluation) <= 20000",
            name="ck_local_listening_domains_overall",
        ),
        CheckConstraint(
            "support_strategy IS NULL OR length(support_strategy) <= 20000",
            name="ck_local_listening_domains_support",
        ),
        ForeignKeyConstraint(
            ["record_id"],
            ["local_listening_records.id"],
            name="fk_local_listening_domains_record",
        ),
        PrimaryKeyConstraint(
            "record_id", "domain",
            name="pk_local_listening_domains",
        ),
    )

    record_id: Mapped[str] = mapped_column(String(32), nullable=False)
    domain: Mapped[str] = mapped_column(String(20), nullable=False)
    template_version: Mapped[str] = mapped_column(String(20), nullable=False)
    template_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    observation_date_text: Mapped[str | None] = mapped_column(
        String(120), nullable=True
    )
    adult_count_text: Mapped[str | None] = mapped_column(
        String(80), nullable=True
    )
    child_age_text: Mapped[str | None] = mapped_column(
        String(80), nullable=True
    )
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    observation_area: Mapped[str | None] = mapped_column(Text, nullable=True)
    overall_evaluation: Mapped[str | None] = mapped_column(Text, nullable=True)
    support_strategy: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalListeningEvaluationChoice(LocalBase):
    """One template item's empty or single 1/2/3 star choice."""

    __tablename__ = "local_listening_evaluation_choices"
    __table_args__ = (
        CheckConstraint(
            "length(item_id) BETWEEN 1 AND 40",
            name="ck_local_listening_choices_item_id",
        ),
        CheckConstraint(
            "stars IS NULL OR "
            "(typeof(stars) = 'integer' AND stars IN (1, 2, 3))",
            name="ck_local_listening_choices_stars",
        ),
        ForeignKeyConstraint(
            ["record_id", "domain"],
            ["local_listening_domains.record_id",
             "local_listening_domains.domain"],
            name="fk_local_listening_choices_domain",
        ),
        PrimaryKeyConstraint(
            "record_id", "domain", "item_id",
            name="pk_local_listening_evaluation_choices",
        ),
    )

    record_id: Mapped[str] = mapped_column(String(32), nullable=False)
    domain: Mapped[str] = mapped_column(String(20), nullable=False)
    item_id: Mapped[str] = mapped_column(String(40), nullable=False)
    stars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalListeningAsset(LocalBase):
    """Immutable managed listening original image."""

    __tablename__ = "local_listening_assets"
    __table_args__ = (
        CheckConstraint(
            "length(relative_path) BETWEEN 1 AND 500",
            name="ck_local_listening_assets_path",
        ),
        CheckConstraint(
            "substr(relative_path, 1, 30) = 'observations/assets/listening/'",
            name="ck_local_listening_assets_path_root",
        ),
        CheckConstraint(
            "length(display_name) BETWEEN 1 AND 255",
            name="ck_local_listening_assets_display_name",
        ),
        CheckConstraint(
            "mime_type IN ('image/jpeg', 'image/png', 'image/webp', "
            "'image/gif', 'image/bmp')",
            name="ck_local_listening_assets_mime",
        ),
        CheckConstraint(
            "length(content_hash) = 64",
            name="ck_local_listening_assets_hash",
        ),
        CheckConstraint(
            "typeof(byte_size) = 'integer' AND byte_size >= 0",
            name="ck_local_listening_assets_size",
        ),
        CheckConstraint(
            "typeof(width) = 'integer' AND typeof(height) = 'integer' "
            "AND width >= 0 AND height >= 0",
            name="ck_local_listening_assets_dimensions",
        ),
        CheckConstraint(
            "orientation IS NULL OR "
            "(typeof(orientation) = 'integer' AND orientation BETWEEN 1 AND 8)",
            name="ck_local_listening_assets_orientation",
        ),
        CheckConstraint(
            "typeof(rotation_quarters) = 'integer' "
            "AND rotation_quarters BETWEEN 0 AND 3",
            name="ck_local_listening_assets_rotation",
        ),
        ForeignKeyConstraint(
            ["record_id"],
            ["local_listening_records.id"],
            name="fk_local_listening_assets_record",
        ),
        UniqueConstraint(
            "record_id", "id",
            name="uq_local_listening_assets_record_id",
        ),
        UniqueConstraint(
            "relative_path",
            name="uq_local_listening_assets_path",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    record_id: Mapped[str] = mapped_column(String(32), nullable=False)
    relative_path: Mapped[str] = mapped_column(String(500), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    orientation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rotation_quarters: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalListeningPhotoGroup(LocalBase):
    """Stable per-domain text/photo position; position is a swap placeholder."""

    __tablename__ = "local_listening_photo_groups"
    __table_args__ = (
        CheckConstraint(
            "position IS NULL OR "
            "(typeof(position) = 'integer' AND position BETWEEN 0 AND 2)",
            name="ck_local_listening_groups_position",
        ),
        CheckConstraint(
            "work_date_text IS NULL OR length(work_date_text) <= 120",
            name="ck_local_listening_groups_work_date",
        ),
        CheckConstraint(
            "listening_text IS NULL OR length(listening_text) <= 20000",
            name="ck_local_listening_groups_text",
        ),
        CheckConstraint(
            "asset_id IS NULL OR length(asset_id) BETWEEN 1 AND 32",
            name="ck_local_listening_groups_asset",
        ),
        ForeignKeyConstraint(
            ["record_id", "domain"],
            ["local_listening_domains.record_id",
             "local_listening_domains.domain"],
            name="fk_local_listening_groups_domain",
        ),
        ForeignKeyConstraint(
            ["record_id", "asset_id"],
            ["local_listening_assets.record_id",
             "local_listening_assets.id"],
            name="fk_local_listening_groups_asset",
        ),
        UniqueConstraint(
            "record_id", "domain", "position",
            name="uq_local_listening_groups_position",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    record_id: Mapped[str] = mapped_column(String(32), nullable=False)
    domain: Mapped[str] = mapped_column(String(20), nullable=False)
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    work_date_text: Mapped[str | None] = mapped_column(
        String(120), nullable=True
    )
    listening_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    asset_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


class LocalListeningOperation(LocalBase):
    """Listening business idempotency envelope (not a content authority)."""

    __tablename__ = "local_listening_operations"
    __table_args__ = (
        CheckConstraint(
            "length(request_id) BETWEEN 1 AND 36",
            name="ck_local_listening_operations_request_id",
        ),
        CheckConstraint(
            "length(request_fingerprint) = 64",
            name="ck_local_listening_operations_fingerprint",
        ),
        CheckConstraint(
            "length(operation_kind) BETWEEN 1 AND 40",
            name="ck_local_listening_operations_kind",
        ),
        CheckConstraint(
            "status IN ('committed', 'failed')",
            name="ck_local_listening_operations_status",
        ),
        ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_listening_operations_profile",
        ),
        ForeignKeyConstraint(
            ["profile_id", "record_id"],
            ["local_listening_records.profile_id",
             "local_listening_records.id"],
            name="fk_local_listening_operations_record",
        ),
        UniqueConstraint(
            "profile_id", "request_id",
            name="uq_local_listening_operations_profile_request",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    operation_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    record_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )


# ---------------------------------------------------------------------------
# Desktop curriculum deliberation (teacher-confirmed 2026-11-09)
# ---------------------------------------------------------------------------


class LocalCurriculumDeliberation(LocalBase):
    """One saved curriculum deliberation, scoped to profile and stable class."""

    __tablename__ = "local_curriculum_deliberations"
    __table_args__ = (
        CheckConstraint(
            "length(id) = 36",
            name="ck_local_curriculum_deliberations_id",
        ),
        CheckConstraint(
            "typeof(version) = 'integer' AND version >= 1",
            name="ck_local_curriculum_deliberations_version",
        ),
        CheckConstraint(
            "length(content_hash) = 64",
            name="ck_local_curriculum_deliberations_hash",
        ),
        ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_curriculum_deliberations_profile",
        ),
        ForeignKeyConstraint(
            ["class_id"],
            ["local_classes.id"],
            name="fk_local_curriculum_deliberations_class",
        ),
        Index(
            "ix_local_curriculum_deliberations_profile_class_updated",
            "profile_id",
            "class_id",
            "updated_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    class_id: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    activity_name: Mapped[str] = mapped_column(Text, nullable=False)
    activity_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now, nullable=False
    )
    document_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )


# Personal todo tables live in their own module but join the shared local
# metadata so the single migration chain and backup fingerprints see them.
from app.local import todo_models as _todo_models  # noqa: E402,F401
