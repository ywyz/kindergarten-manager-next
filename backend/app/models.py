from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utc_now() -> datetime:
    """Return a naive UTC datetime; MySQL DateTime does not store time zones."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'teacher')", name="ck_account_role"),
        CheckConstraint("username = LOWER(username)", name="ck_username_lowercase"),
        CheckConstraint("version >= 1", name="ck_accounts_version"),
        CheckConstraint("auth_version >= 1", name="ck_accounts_auth_version"),
        UniqueConstraint("username", name="uq_accounts_username"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: Mapped[str] = mapped_column(
        String(32, collation="utf8mb4_bin"), primary_key=True
    )
    username: Mapped[str] = mapped_column(
        String(32, collation="utf8mb4_bin"), nullable=False
    )
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    auth_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_now, nullable=False
    )

    sessions: Mapped[list["AccountSession"]] = relationship(
        "AccountSession", back_populates="account", lazy="dynamic"
    )


class FirstAdminControl(Base):
    __tablename__ = "first_admin_control"
    __table_args__ = (
        CheckConstraint("id = 'singleton'", name="ck_first_admin_control_singleton"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: Mapped[str] = mapped_column(
        String(32, collation="utf8mb4_bin"), primary_key=True
    )
    claimed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    first_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("accounts.id"), nullable=True
    )


class AccountSession(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: Mapped[str] = mapped_column(
        String(32, collation="utf8mb4_bin"), primary_key=True
    )
    token_hash: Mapped[str] = mapped_column(
        String(64, collation="utf8mb4_bin"), unique=True, nullable=False, index=True
    )
    account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id"), nullable=False, index=True
    )
    auth_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_now, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

    account: Mapped["Account"] = relationship("Account", back_populates="sessions")


class OperationRecord(Base):
    __tablename__ = "operation_records"
    __table_args__ = (
        CheckConstraint(
            "operator_type IN ('account', 'server_operator')",
            name="ck_operation_record_operator_type",
        ),
        CheckConstraint(
            "target_type IN ('account', 'class', 'school', 'term', 'calendar', "
            "'daily_plan', 'weekly_plan')",
            name="ck_operation_record_target_type",
        ),
        # For account-targeted records the legacy columns stay required and
        # consistent with the generic target columns (issue 5).
        CheckConstraint(
            "target_type <> 'account' OR ("
            "target_account_id IS NOT NULL "
            "AND account_version_after IS NOT NULL "
            "AND target_account_id = target_id "
            "AND account_version_after = target_version_after)",
            name="ck_operation_record_account_target",
        ),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: Mapped[str] = mapped_column(
        String(32, collation="utf8mb4_bin"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_now, nullable=False
    )
    operator_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    operator_type: Mapped[str] = mapped_column(String(30), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    # Generic target columns (I2). For account-targeted records the legacy
    # columns below are still populated, required and kept compatible.
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[str] = mapped_column(
        String(32, collation="utf8mb4_bin"), nullable=False
    )
    target_version_after: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("accounts.id"), nullable=True
    )
    account_version_after: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SchoolSettings(Base):
    """Singleton row holding school-wide configuration."""

    __tablename__ = "school_settings"
    __table_args__ = (
        CheckConstraint("id = 'singleton'", name="ck_school_settings_singleton"),
        CheckConstraint("version >= 1", name="ck_school_settings_version"),
        CheckConstraint(
            "schedule_version >= 1", name="ck_school_settings_schedule_version"
        ),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: Mapped[str] = mapped_column(
        String(32, collation="utf8mb4_bin"), primary_key=True
    )
    school_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # School-wide term/calendar write sequence, used for range conflict checks
    # and preview invalidation.
    schedule_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # Irreversible marker: set inside the first plan-creation transaction (I3).
    plans_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_now, nullable=False
    )


class Class(Base):
    __tablename__ = "classes"
    __table_args__ = (
        CheckConstraint("grade IN ('small', 'middle', 'large')", name="ck_classes_grade"),
        CheckConstraint(
            "caregiver_name IS NULL OR CHAR_LENGTH(TRIM(caregiver_name)) BETWEEN 1 AND 80",
            name="ck_classes_caregiver_name",
        ),
        CheckConstraint("version >= 1", name="ck_classes_version"),
        # P3: school-wide unique name. The column uses an explicit binary
        # collation, so the unique index compares names literally
        # (case-sensitive) instead of the default fuzzy collation.
        UniqueConstraint("name", name="uq_classes_name"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: Mapped[str] = mapped_column(
        String(32, collation="utf8mb4_bin"), primary_key=True
    )
    name: Mapped[str] = mapped_column(
        String(80, collation="utf8mb4_bin"), nullable=False
    )
    grade: Mapped[str] = mapped_column(String(20), nullable=False)
    # Ordered list of header teacher names; never account IDs, never synced.
    header_teacher_names: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    caregiver_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_now, nullable=False
    )

    assignments: Mapped[list["TeacherAssignment"]] = relationship(
        "TeacherAssignment", back_populates="school_class"
    )


class TeacherAssignment(Base):
    """Current teacher->class ownership. Absence of a row means unassigned."""

    __tablename__ = "teacher_assignments"
    __table_args__ = (
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    teacher_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id"), primary_key=True
    )
    class_id: Mapped[str] = mapped_column(
        ForeignKey("classes.id"), nullable=False, index=True
    )
    assigned_by: Mapped[str] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_now, nullable=False
    )

    teacher: Mapped["Account"] = relationship(
        "Account", foreign_keys=[teacher_id]
    )
    school_class: Mapped["Class"] = relationship(
        "Class", back_populates="assignments"
    )


class Term(Base):
    __tablename__ = "terms"
    __table_args__ = (
        CheckConstraint("start_date <= end_date", name="ck_terms_date_order"),
        CheckConstraint("version >= 1", name="ck_terms_version"),
        Index("ix_terms_start_date", "start_date"),
        Index("ix_terms_end_date", "end_date"),
        # Composite, deferrable-cycle FK: the current revision must belong to
        # THIS term. References the (term_id,id) candidate key below; a
        # single-column FK on revision id could not enforce term ownership.
        ForeignKeyConstraint(
            ["id", "current_calendar_revision_id"],
            ["calendar_revisions.term_id", "calendar_revisions.id"],
            name="fk_terms_current_revision_of_term",
            use_alter=True,
        ),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: Mapped[str] = mapped_column(
        String(32, collation="utf8mb4_bin"), primary_key=True
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # Pointer to the current revision. Deferred FK (use_alter) because the
    # revision itself references the term.
    current_calendar_revision_id: Mapped[str | None] = mapped_column(
        String(32, collation="utf8mb4_bin"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_now, nullable=False
    )

    revisions: Mapped[list["CalendarRevision"]] = relationship(
        "CalendarRevision",
        back_populates="term",
        foreign_keys="CalendarRevision.term_id",
    )


class CalendarRevision(Base):
    __tablename__ = "calendar_revisions"
    __table_args__ = (
        UniqueConstraint("term_id", "revision_no", name="uq_calendar_revisions_term_rev"),
        # Candidate key referenced by the terms composite FK so a term can
        # only point at a revision owned by that same term.
        UniqueConstraint("term_id", "id", name="uq_calendar_revisions_term_id"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: Mapped[str] = mapped_column(
        String(32, collation="utf8mb4_bin"), primary_key=True
    )
    term_id: Mapped[str] = mapped_column(
        ForeignKey("terms.id"), nullable=False, index=True
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    term_version: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    library_version: Mapped[str] = mapped_column(String(50), nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_now, nullable=False
    )

    term: Mapped["Term"] = relationship(
        "Term",
        back_populates="revisions",
        foreign_keys=[term_id],
    )
    days: Mapped[list["CalendarDay"]] = relationship(
        "CalendarDay", back_populates="revision"
    )


class CalendarDay(Base):
    __tablename__ = "calendar_days"
    __table_args__ = (
        CheckConstraint(
            "base_state IN ('teaching', 'non_teaching', 'unknown')",
            name="ck_calendar_days_base_state",
        ),
        CheckConstraint(
            "override_state IS NULL OR override_state IN ('teaching', 'non_teaching')",
            name="ck_calendar_days_override_state",
        ),
        CheckConstraint(
            "effective_state IN ('teaching', 'non_teaching', 'unknown')",
            name="ck_calendar_days_effective_state",
        ),
        CheckConstraint(
            "override_state IS NULL OR "
            "(override_reason IS NOT NULL AND CHAR_LENGTH(TRIM(override_reason)) BETWEEN 1 AND 200)",
            name="ck_calendar_days_override_reason",
        ),
        CheckConstraint(
            "effective_state = COALESCE(override_state, base_state)",
            name="ck_calendar_days_effective",
        ),
        # NOTE: MySQL CHECK constraints cannot contain subqueries, so the
        # "dates must lie within the revision range and be complete" rule is
        # enforced by the builder and a commit-time check in the service.
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    revision_id: Mapped[str] = mapped_column(
        ForeignKey("calendar_revisions.id"), primary_key=True
    )
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    base_state: Mapped[str] = mapped_column(String(20), nullable=False)
    base_library_version: Mapped[str] = mapped_column(String(50), nullable=False)
    override_state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    override_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    effective_state: Mapped[str] = mapped_column(String(20), nullable=False)

    revision: Mapped["CalendarRevision"] = relationship(
        "CalendarRevision", back_populates="days"
    )


class ConfigurationChange(Base):
    """Pending or applied configuration change proposal (never the live config)."""

    __tablename__ = "configuration_changes"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('school_update', 'class_create', 'class_update', "
            "'term_create', 'term_update', 'calendar_override', 'calendar_reimport')",
            name="ck_configuration_changes_kind",
        ),
        CheckConstraint(
            "status IN ('pending', 'applied')",
            name="ck_configuration_changes_status",
        ),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: Mapped[str] = mapped_column(
        String(32, collation="utf8mb4_bin"), primary_key=True
    )
    operator_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    target_id: Mapped[str] = mapped_column(
        String(32, collation="utf8mb4_bin"), nullable=False
    )
    normalized_proposal: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    base_versions: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    impact_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_now, nullable=False
    )
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    result_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Persisted versions of the actual committed result (issue 9). Filled at
    # apply time; repeated/retried applications return these same versions.
    result_versions: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class DailyPlan(Base):
    """One effective (or soft-deleted) daily plan header for a class/date.

    Identity and the school/class/creator snapshot are immutable after
    creation; content lives in append-only :class:`DailyPlanContent` rows
    referenced by the composite current pointer.
    """

    __tablename__ = "daily_plans"
    __table_args__ = (
        CheckConstraint(
            "current_content_version IS NULL OR current_content_version >= 1",
            name="ck_daily_plans_current_content_version",
        ),
        # Effective-row uniqueness: generated column is plan_date while the
        # row is live and NULL once soft-deleted, so MySQL's unique index
        # admits many deleted rows per date but at most one effective row.
        UniqueConstraint(
            "class_id", "effective_date",
            name="uq_daily_plans_class_effective_date",
        ),
        Index("ix_daily_plans_class_id", "class_id"),
        Index("ix_daily_plans_term_id", "term_id"),
        Index("ix_daily_plans_plan_date", "plan_date"),
        # Cycle with daily_plan_contents (that table FKs daily_plans.id):
        # both tables are created first, this composite FK is added after.
        ForeignKeyConstraint(
            ["id", "current_content_id", "current_content_version"],
            [
                "daily_plan_contents.daily_plan_id",
                "daily_plan_contents.id",
                "daily_plan_contents.version",
            ],
            name="fk_daily_plans_current_content",
            use_alter=True,
        ),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: Mapped[str] = mapped_column(
        String(32, collation="utf8mb4_bin"), primary_key=True
    )
    class_id: Mapped[str] = mapped_column(
        ForeignKey("classes.id"), nullable=False
    )
    term_id: Mapped[str] = mapped_column(ForeignKey("terms.id"), nullable=False)
    plan_date: Mapped[date] = mapped_column(Date, nullable=False)
    creator_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id"), nullable=False
    )
    week_number: Mapped[int] = mapped_column(Integer, nullable=False)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)

    # Current content pointer; may be NULL only inside the creation
    # transaction, before the first content row is written back to it.
    current_content_id: Mapped[str | None] = mapped_column(
        String(32, collation="utf8mb4_bin"), nullable=True
    )
    current_content_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )

    # Immutable identity snapshot taken at creation (decision A).
    creator_display_name: Mapped[str | None] = mapped_column(
        String(80), nullable=True
    )
    school_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    class_name: Mapped[str] = mapped_column(String(80), nullable=False)
    grade: Mapped[str] = mapped_column(String(20), nullable=False)

    # Soft-delete columns reserved by decision B (delete/recover deferred).
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    deleted_by: Mapped[str | None] = mapped_column(
        ForeignKey("accounts.id"), nullable=True
    )

    # Server-generated effective_date (STORED); never written by the app.
    effective_date: Mapped[date | None] = mapped_column(
        Date,
        Computed(
            "CASE WHEN deleted_at IS NULL THEN plan_date END",
            persisted=True,
        ),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_now, nullable=False
    )


class DailyPlanContent(Base):
    """Append-only content version of one daily plan; never updated in place."""

    __tablename__ = "daily_plan_contents"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_daily_plan_contents_version"),
        UniqueConstraint(
            "daily_plan_id", "id", "version",
            name="uq_daily_plan_contents_plan_id_version",
        ),
        UniqueConstraint(
            "daily_plan_id", "version",
            name="uq_daily_plan_contents_plan_version",
        ),
        Index("ix_daily_plan_contents_daily_plan_id", "daily_plan_id"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: Mapped[str] = mapped_column(
        String(32, collation="utf8mb4_bin"), primary_key=True
    )
    daily_plan_id: Mapped[str] = mapped_column(
        ForeignKey("daily_plans.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_lesson_plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    split_baseline: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )
    adopted_content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    editor_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_now, nullable=False
    )


class WeeklyPlanSyncState(Base):
    """Pending weekly projection of a class/term/week (option A).

    Read-state only: it is not a weekly plan table, decides no weekly-plan
    owner, and must not reference tables that do not exist yet.
    """

    __tablename__ = "weekly_plan_sync_states"
    __table_args__ = (
        CheckConstraint(
            "status = 'pending_projection'",
            name="ck_weekly_plan_sync_states_status",
        ),
        CheckConstraint(
            "last_trigger_event IS NULL OR last_trigger_event IN "
            "('create', 'update', 'delete')",
            name="ck_weekly_plan_sync_states_last_trigger_event",
        ),
        UniqueConstraint(
            "class_id", "term_id", "week_number",
            name="uq_weekly_plan_sync_states_class_term_week",
        ),
        Index("ix_weekly_plan_sync_states_class_id", "class_id"),
        Index("ix_weekly_plan_sync_states_term_id", "term_id"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: Mapped[str] = mapped_column(
        String(32, collation="utf8mb4_bin"), primary_key=True
    )
    class_id: Mapped[str] = mapped_column(ForeignKey("classes.id"), nullable=False)
    term_id: Mapped[str] = mapped_column(ForeignKey("terms.id"), nullable=False)
    week_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    deterministic_themes: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    game_source_manifest: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    current_week_source_manifest: Mapped[list[Any]] = mapped_column(
        JSON, nullable=False
    )
    last_trigger_daily_plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("daily_plans.id"), nullable=True
    )
    last_trigger_content_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    last_trigger_event: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_now, nullable=False
    )


class WeeklyPlan(Base):
    """One effective weekly plan header for a class/term/week (I4).

    Effective-row uniqueness uses a generated column so soft-deleted rows
    leave the unique index while live rows stay one-per-(class, term, week).
    The current draft/confirmed pointers are composite FKs into the
    append-only content tables, filled inside the creation transaction.
    Header snapshot columns are immutable after creation (decision U1=A).
    """

    __tablename__ = "weekly_plans"
    __table_args__ = (
        CheckConstraint("week_number >= 1", name="ck_weekly_plans_week_number"),
        CheckConstraint(
            "current_draft_version IS NULL OR current_draft_version >= 1",
            name="ck_weekly_plans_current_draft_version",
        ),
        CheckConstraint(
            "current_confirmed_content_version IS NULL "
            "OR current_confirmed_content_version >= 1",
            name="ck_weekly_plans_current_confirmed_content_version",
        ),
        UniqueConstraint(
            "class_id", "term_id", "effective_week",
            name="uq_weekly_plans_class_term_effective_week",
        ),
        Index("ix_weekly_plans_class_id", "class_id"),
        Index("ix_weekly_plans_term_id", "term_id"),
        # Cycles with weekly_plan_contents / weekly_plan_confirmed_contents:
        # all three tables are created first, these composite FKs are added
        # by ALTER afterwards (same pattern as fk_daily_plans_current_content).
        ForeignKeyConstraint(
            ["id", "current_draft_content_id", "current_draft_version"],
            [
                "weekly_plan_contents.weekly_plan_id",
                "weekly_plan_contents.id",
                "weekly_plan_contents.version",
            ],
            name="fk_weekly_plans_current_draft_content",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["id", "current_confirmed_content_id",
             "current_confirmed_content_version"],
            [
                "weekly_plan_confirmed_contents.weekly_plan_id",
                "weekly_plan_confirmed_contents.id",
                "weekly_plan_confirmed_contents.version",
            ],
            name="fk_weekly_plans_current_confirmed_content",
            use_alter=True,
        ),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: Mapped[str] = mapped_column(
        String(32, collation="utf8mb4_bin"), primary_key=True
    )
    class_id: Mapped[str] = mapped_column(ForeignKey("classes.id"), nullable=False)
    term_id: Mapped[str] = mapped_column(ForeignKey("terms.id"), nullable=False)
    week_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # creator_id is immutable; owner_id equals creator_id in I4 (takeover
    # arrives in a later slice).
    creator_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    owner_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), nullable=False)

    # Draft pointer; NULL only inside the creation transaction before the
    # first content row is written back.
    current_draft_content_id: Mapped[str | None] = mapped_column(
        String(32, collation="utf8mb4_bin"), nullable=True
    )
    current_draft_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Confirmed pointer; NULL means never confirmed (not an error).
    current_confirmed_content_id: Mapped[str | None] = mapped_column(
        String(32, collation="utf8mb4_bin"), nullable=True
    )
    current_confirmed_content_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )

    # Immutable header snapshot taken at creation (decision U1=A).
    school_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    class_name: Mapped[str] = mapped_column(String(80), nullable=False)
    grade: Mapped[str] = mapped_column(String(20), nullable=False)
    header_teacher_names: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    caregiver_name: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # Coarse "daily-plan side moved on since last consumption" banner hint;
    # authoritative freshness is the per-source version comparison.
    projection_consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )

    # Soft-delete columns reserved for delete/recover (no I4 entry point).
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    deleted_by: Mapped[str | None] = mapped_column(
        ForeignKey("accounts.id"), nullable=True
    )

    # Server-generated effective_week (STORED); never written by the app.
    # Declared after deleted_at, which the expression references.
    effective_week: Mapped[int | None] = mapped_column(
        Integer,
        Computed(
            "CASE WHEN deleted_at IS NULL THEN week_number END",
            persisted=True,
        ),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_now, nullable=False
    )


class WeeklyPlanContent(Base):
    """Append-only draft content version of one weekly plan (never updated)."""

    __tablename__ = "weekly_plan_contents"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_weekly_plan_contents_version"),
        CheckConstraint(
            "editor_role IN ('owner', 'admin')",
            name="ck_weekly_plan_contents_editor_role",
        ),
        UniqueConstraint(
            "weekly_plan_id", "id", "version",
            name="uq_weekly_plan_contents_plan_id_version",
        ),
        UniqueConstraint(
            "weekly_plan_id", "version",
            name="uq_weekly_plan_contents_plan_version",
        ),
        Index("ix_weekly_plan_contents_weekly_plan_id", "weekly_plan_id"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: Mapped[str] = mapped_column(
        String(32, collation="utf8mb4_bin"), primary_key=True
    )
    weekly_plan_id: Mapped[str] = mapped_column(
        ForeignKey("weekly_plans.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    editor_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    editor_role: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_now, nullable=False
    )


class WeeklyPlanConfirmedContent(Base):
    """Immutable confirmed snapshot of one weekly plan (append-only)."""

    __tablename__ = "weekly_plan_confirmed_contents"
    __table_args__ = (
        CheckConstraint("version >= 1",
                        name="ck_weekly_plan_confirmed_contents_version"),
        UniqueConstraint(
            "weekly_plan_id", "id", "version",
            name="uq_weekly_plan_confirmed_contents_plan_id_version",
        ),
        UniqueConstraint(
            "weekly_plan_id", "version",
            name="uq_weekly_plan_confirmed_contents_plan_version",
        ),
        Index(
            "ix_weekly_plan_confirmed_contents_weekly_plan_id",
            "weekly_plan_id",
        ),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: Mapped[str] = mapped_column(
        String(32, collation="utf8mb4_bin"), primary_key=True
    )
    weekly_plan_id: Mapped[str] = mapped_column(
        ForeignKey("weekly_plans.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    draft_version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    facts: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    confirmed_by: Mapped[str] = mapped_column(
        ForeignKey("accounts.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_now, nullable=False
    )
