"""Local SQLite baseline: single profile, term calendar, manual daily plans.

Revision ID: 20261012_0001_local
Revises: (none)
Create Date: 2026-10-12

One-shot baseline for the empty local database. Downgrade is intentionally
refused: this slice never drops or downgrades a real business database.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261012_0001_local"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- single local teacher profile -------------------------------------
    op.create_table(
        "local_profile",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("singleton", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint("singleton = 1", name="ck_local_profile_singleton"),
        sa.CheckConstraint(
            "length(display_name) BETWEEN 1 AND 80",
            name="ck_local_profile_display_name",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_profile"),
        sa.UniqueConstraint("singleton", name="uq_local_profile_singleton"),
    )

    # --- classes -----------------------------------------------------------
    op.create_table(
        "local_classes",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("grade", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "grade IN ('small', 'middle', 'large')", name="ck_local_classes_grade"
        ),
        sa.CheckConstraint(
            "length(name) BETWEEN 1 AND 80", name="ck_local_classes_name"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_classes"),
        sa.UniqueConstraint("name", name="uq_local_classes_name"),
    )

    # --- terms (composite deferred FK to the current calendar revision) ----
    op.create_table(
        "local_terms",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("current_calendar_revision_id", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint("start_date <= end_date", name="ck_local_terms_date_order"),
        sa.CheckConstraint("length(name) BETWEEN 1 AND 80", name="ck_local_terms_name"),
        sa.ForeignKeyConstraint(
            ["id", "current_calendar_revision_id"],
            ["local_calendar_revisions.term_id", "local_calendar_revisions.id"],
            name="fk_local_terms_current_revision",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_terms"),
    )

    # --- calendar revisions -------------------------------------------------
    op.create_table(
        "local_calendar_revisions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("term_id", sa.String(length=32), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("library_version", sa.String(length=50), nullable=False),
        sa.Column("created_by", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "revision_no >= 1", name="ck_local_calendar_revisions_revision_no"
        ),
        sa.ForeignKeyConstraint(
            ["term_id"], ["local_terms.id"], name="fk_local_calendar_revisions_term_id"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["local_profile.id"],
            name="fk_local_calendar_revisions_created_by",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_calendar_revisions"),
        sa.UniqueConstraint(
            "term_id",
            "revision_no",
            name="uq_local_calendar_revisions_term_revision",
        ),
        # Candidate key referenced by local_terms and local_daily_plans.
        sa.UniqueConstraint(
            "term_id", "id", name="uq_local_calendar_revisions_term_id"
        ),
    )

    # --- calendar days -------------------------------------------------------
    op.create_table(
        "local_calendar_days",
        sa.Column("revision_id", sa.String(length=32), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("base_state", sa.String(length=20), nullable=False),
        sa.Column("base_library_version", sa.String(length=50), nullable=False),
        sa.Column("override_state", sa.String(length=20), nullable=True),
        sa.Column("override_reason", sa.String(length=200), nullable=True),
        sa.Column("effective_state", sa.String(length=20), nullable=False),
        sa.CheckConstraint(
            "base_state IN ('teaching', 'non_teaching', 'unknown')",
            name="ck_local_calendar_days_base_state",
        ),
        sa.CheckConstraint(
            "override_state IS NULL OR override_state IN ('teaching', 'non_teaching')",
            name="ck_local_calendar_days_override_state",
        ),
        sa.CheckConstraint(
            "effective_state IN ('teaching', 'non_teaching', 'unknown')",
            name="ck_local_calendar_days_effective_state",
        ),
        sa.CheckConstraint(
            "override_state IS NULL OR (override_reason IS NOT NULL AND "
            "length(trim(override_reason)) BETWEEN 1 AND 200)",
            name="ck_local_calendar_days_override_reason",
        ),
        sa.CheckConstraint(
            "effective_state = COALESCE(override_state, base_state)",
            name="ck_local_calendar_days_effective",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["local_calendar_revisions.id"],
            name="fk_local_calendar_days_revision_id",
        ),
        sa.PrimaryKeyConstraint(
            "revision_id", "date", name="pk_local_calendar_days"
        ),
    )

    # --- daily plan headers --------------------------------------------------
    op.create_table(
        "local_daily_plans",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("class_id", sa.String(length=32), nullable=False),
        sa.Column("term_id", sa.String(length=32), nullable=False),
        sa.Column("plan_date", sa.Date(), nullable=False),
        sa.Column("creator_id", sa.String(length=32), nullable=False),
        sa.Column("week_number", sa.Integer(), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("calendar_revision_id", sa.String(length=32), nullable=False),
        sa.Column("current_content_id", sa.String(length=32), nullable=False),
        sa.Column("current_content_version", sa.Integer(), nullable=False),
        sa.Column("creator_display_name", sa.String(length=80), nullable=False),
        sa.Column("school_name", sa.String(length=120), nullable=True),
        sa.Column("class_name", sa.String(length=80), nullable=False),
        sa.Column("grade", sa.String(length=20), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("deleted_by", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "current_content_version >= 1",
            name="ck_local_daily_plans_current_content_version",
        ),
        sa.CheckConstraint(
            "week_number >= 1", name="ck_local_daily_plans_week_number"
        ),
        sa.CheckConstraint(
            "weekday BETWEEN 1 AND 7", name="ck_local_daily_plans_weekday"
        ),
        sa.CheckConstraint(
            "length(class_name) BETWEEN 1 AND 80",
            name="ck_local_daily_plans_class_name",
        ),
        sa.CheckConstraint(
            "school_name IS NULL OR length(school_name) BETWEEN 1 AND 120",
            name="ck_local_daily_plans_school_name",
        ),
        sa.ForeignKeyConstraint(
            ["class_id"], ["local_classes.id"], name="fk_local_daily_plans_class_id"
        ),
        sa.ForeignKeyConstraint(
            ["term_id"], ["local_terms.id"], name="fk_local_daily_plans_term_id"
        ),
        sa.ForeignKeyConstraint(
            ["creator_id"],
            ["local_profile.id"],
            name="fk_local_daily_plans_creator_id",
        ),
        sa.ForeignKeyConstraint(
            ["deleted_by"],
            ["local_profile.id"],
            name="fk_local_daily_plans_deleted_by",
        ),
        # The plan's calendar revision must belong to the same term.
        sa.ForeignKeyConstraint(
            ["term_id", "calendar_revision_id"],
            ["local_calendar_revisions.term_id", "local_calendar_revisions.id"],
            name="fk_local_daily_plans_term_revision",
        ),
        # Current content pointer; deferred so header + first content commit
        # together (a missing first version can never be committed).
        sa.ForeignKeyConstraint(
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
        sa.PrimaryKeyConstraint("id", name="pk_local_daily_plans"),
    )
    op.create_index(
        "ix_local_daily_plans_plan_date",
        "local_daily_plans",
        ["plan_date"],
        unique=False,
    )
    # Effective-row uniqueness (no redundant effective_date column).
    op.create_index(
        "uq_local_daily_plans_effective_class_date",
        "local_daily_plans",
        ["class_id", "plan_date"],
        unique=True,
        sqlite_where=sa.text("deleted_at IS NULL"),
    )

    # --- daily plan contents --------------------------------------------------
    op.create_table(
        "local_daily_plan_contents",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("daily_plan_id", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("raw_lesson_plan", sa.Text(), nullable=True),
        sa.Column("split_baseline", sa.JSON(), nullable=True),
        sa.Column("adopted_content", sa.JSON(), nullable=False),
        sa.Column("editor_id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "version >= 1", name="ck_local_daily_plan_contents_version"
        ),
        sa.ForeignKeyConstraint(
            ["daily_plan_id"],
            ["local_daily_plans.id"],
            name="fk_local_daily_plan_contents_daily_plan_id",
        ),
        sa.ForeignKeyConstraint(
            ["editor_id"],
            ["local_profile.id"],
            name="fk_local_daily_plan_contents_editor_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_daily_plan_contents"),
        sa.UniqueConstraint(
            "daily_plan_id",
            "version",
            name="uq_local_daily_plan_contents_plan_version",
        ),
        sa.UniqueConstraint(
            "daily_plan_id",
            "id",
            "version",
            name="uq_local_daily_plan_contents_plan_id_version",
        ),
    )

    # --- local settings --------------------------------------------------------
    op.create_table(
        "local_settings",
        sa.Column("id", sa.String(length=16), nullable=False),
        sa.Column("singleton", sa.Integer(), nullable=False),
        sa.Column("school_name", sa.String(length=120), nullable=True),
        sa.Column("current_class_id", sa.String(length=32), nullable=False),
        sa.Column("init_request_id", sa.String(length=36), nullable=False),
        sa.Column("init_input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint("id = 'singleton'", name="ck_local_settings_singleton_id"),
        sa.CheckConstraint("singleton = 1", name="ck_local_settings_singleton"),
        sa.CheckConstraint(
            "school_name IS NULL OR length(school_name) BETWEEN 1 AND 120",
            name="ck_local_settings_school_name",
        ),
        sa.CheckConstraint(
            "length(init_request_id) BETWEEN 1 AND 36",
            name="ck_local_settings_init_request_id",
        ),
        sa.CheckConstraint(
            "length(init_input_fingerprint) = 64",
            name="ck_local_settings_init_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["current_class_id"],
            ["local_classes.id"],
            name="fk_local_settings_current_class_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_settings"),
        sa.UniqueConstraint("singleton", name="uq_local_settings_singleton"),
    )

    # --- operation records -------------------------------------------------------
    op.create_table(
        "local_operation_records",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("actor_id", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("target_type", sa.String(length=30), nullable=False),
        sa.Column("target_id", sa.String(length=32), nullable=False),
        sa.Column("target_version_after", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "length(action) BETWEEN 1 AND 50",
            name="ck_local_operation_records_action",
        ),
        sa.CheckConstraint(
            "length(target_type) BETWEEN 1 AND 30",
            name="ck_local_operation_records_target_type",
        ),
        sa.CheckConstraint(
            "target_version_after IS NULL OR target_version_after >= 1",
            name="ck_local_operation_records_target_version",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["local_profile.id"],
            name="fk_local_operation_records_actor_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_operation_records"),
    )


def downgrade() -> None:
    raise RuntimeError(
        "local baseline downgrade is not supported: this slice never "
        "downgrades or drops a real local database"
    )
