"""I2 terms & persisted effective calendar.

学期、不可变日历修订与逐日有效状态。Term.current_calendar_revision_id 与
CalendarRevision.term_id 构成循环外键，前者用 use_alter 延后创建。有效状态为
COALESCE(override_state, base_state)；范围完整性由服务提交前校验，CHECK 不放
子查询（MySQL 限制）。
"""

from alembic import op
import sqlalchemy as sa


revision = "20260922_i2_terms_calendar"
down_revision = "20260921_i2_classes_assignments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "terms",
        sa.Column("id", sa.String(32, collation="utf8mb4_bin"),
                  nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        # Deferred FK column: added as nullable, no FK in create_table so the
        # cycle with calendar_revisions can be resolved afterwards.
        sa.Column(
            "current_calendar_revision_id",
            sa.String(32, collation="utf8mb4_bin"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("start_date <= end_date",
                           name="ck_terms_date_order"),
        sa.CheckConstraint("version >= 1", name="ck_terms_version"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("ix_terms_start_date", "terms", ["start_date"])
    op.create_index("ix_terms_end_date", "terms", ["end_date"])

    op.create_table(
        "calendar_revisions",
        sa.Column("id", sa.String(32, collation="utf8mb4_bin"),
                  nullable=False),
        sa.Column("term_id", sa.String(32, collation="utf8mb4_bin"),
                  nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("term_version", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("library_version", sa.String(50), nullable=False),
        sa.Column("created_by", sa.String(32, collation="utf8mb4_bin"),
                  nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["term_id"], ["terms.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["accounts.id"]),
        sa.UniqueConstraint("term_id", "revision_no",
                            name="uq_calendar_revisions_term_rev"),
        # Candidate key for the terms composite FK: proves a revision belongs
        # to a specific term, enabling cross-term pointer rejection.
        sa.UniqueConstraint("term_id", "id",
                            name="uq_calendar_revisions_term_id"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )

    op.create_table(
        "calendar_days",
        sa.Column("revision_id", sa.String(32, collation="utf8mb4_bin"),
                  nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("base_state", sa.String(20), nullable=False),
        sa.Column("base_library_version", sa.String(50), nullable=False),
        sa.Column("override_state", sa.String(20), nullable=True),
        sa.Column("override_reason", sa.String(200), nullable=True),
        sa.Column("effective_state", sa.String(20), nullable=False),
        sa.PrimaryKeyConstraint("revision_id", "date"),
        sa.ForeignKeyConstraint(["revision_id"],
                                ["calendar_revisions.id"]),
        sa.CheckConstraint(
            "base_state IN ('teaching', 'non_teaching', 'unknown')",
            name="ck_calendar_days_base_state",
        ),
        sa.CheckConstraint(
            "override_state IS NULL OR override_state IN "
            "('teaching', 'non_teaching')",
            name="ck_calendar_days_override_state",
        ),
        sa.CheckConstraint(
            "effective_state IN ('teaching', 'non_teaching', 'unknown')",
            name="ck_calendar_days_effective_state",
        ),
        sa.CheckConstraint(
            "override_state IS NULL OR "
            "(override_reason IS NOT NULL AND "
            "CHAR_LENGTH(TRIM(override_reason)) BETWEEN 1 AND 200)",
            name="ck_calendar_days_override_reason",
        ),
        sa.CheckConstraint(
            "effective_state = COALESCE(override_state, base_state)",
            name="ck_calendar_days_effective",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )

    # Resolve the cycle with a COMPOSITE FK: (terms.id,
    # current_calendar_revision_id) must match (revisions.term_id,id), so a
    # term can never point at another term's revision. A single-column FK on
    # the revision id could not guarantee term ownership.
    op.create_foreign_key(
        "fk_terms_current_revision_of_term",
        "terms",
        "calendar_revisions",
        ["id", "current_calendar_revision_id"],
        ["term_id", "id"],
    )


def downgrade() -> None:
    """Destructive; blocked like the base I2 migration."""
    raise RuntimeError(
        "I2 terms/calendar downgrade is intentionally blocked: it would "
        "drop persisted calendar revisions. Back up and downgrade manually "
        "if truly required."
    )
