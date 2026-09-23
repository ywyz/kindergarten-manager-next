"""I3: daily plans, append-only content versions, weekly sync projection.

日计划头、不可变内容版本与周计划待确认投影。daily_plans 与
daily_plan_contents 循环外键：先建两表（contents 内联 FK 指向 plans），再
ALTER 添加 plans 上的复合指针 FK。生成列 effective_date 实现“同班同日仅一条
有效记录”（删除行该列为 NULL，唯一索引允许多条 NULL）。同时把
operation_records.target_type CHECK 值域扩展出 daily_plan。不修改 I1/I2 数据。
"""

from alembic import op
import sqlalchemy as sa


revision = "20260923_i3_daily_plans"
down_revision = "20260922_i2_terms_calendar"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_plans",
        sa.Column("id", sa.String(32, collation="utf8mb4_bin"),
                  nullable=False),
        sa.Column("class_id", sa.String(32, collation="utf8mb4_bin"),
                  nullable=False),
        sa.Column("term_id", sa.String(32, collation="utf8mb4_bin"),
                  nullable=False),
        sa.Column("plan_date", sa.Date(), nullable=False),
        sa.Column("creator_id", sa.String(32, collation="utf8mb4_bin"),
                  nullable=False),
        sa.Column("week_number", sa.Integer(), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        # Pointer columns stay nullable so the creation transaction can
        # insert the header first, the first content row second, then the
        # pointer update; the composite FK below enforces ownership.
        sa.Column("current_content_id",
                  sa.String(32, collation="utf8mb4_bin"), nullable=True),
        sa.Column("current_content_version", sa.Integer(), nullable=True),
        sa.Column("creator_display_name", sa.String(80), nullable=True),
        sa.Column("school_name", sa.String(120), nullable=True),
        sa.Column("class_name", sa.String(80), nullable=False),
        sa.Column("grade", sa.String(20), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("deleted_by", sa.String(32, collation="utf8mb4_bin"),
                  nullable=True),
        sa.Column(
            "effective_date",
            sa.Date(),
            sa.Computed(
                "CASE WHEN deleted_at IS NULL THEN plan_date END",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"]),
        sa.ForeignKeyConstraint(["term_id"], ["terms.id"]),
        sa.ForeignKeyConstraint(["creator_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["deleted_by"], ["accounts.id"]),
        sa.CheckConstraint(
            "current_content_version IS NULL OR current_content_version >= 1",
            name="ck_daily_plans_current_content_version",
        ),
        sa.UniqueConstraint(
            "class_id", "effective_date",
            name="uq_daily_plans_class_effective_date",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("ix_daily_plans_class_id", "daily_plans", ["class_id"])
    op.create_index("ix_daily_plans_term_id", "daily_plans", ["term_id"])
    op.create_index("ix_daily_plans_plan_date", "daily_plans", ["plan_date"])

    op.create_table(
        "daily_plan_contents",
        sa.Column("id", sa.String(32, collation="utf8mb4_bin"),
                  nullable=False),
        sa.Column("daily_plan_id", sa.String(32, collation="utf8mb4_bin"),
                  nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("raw_lesson_plan", sa.Text(), nullable=True),
        sa.Column("split_baseline", sa.JSON(), nullable=True),
        sa.Column("adopted_content", sa.JSON(), nullable=False),
        sa.Column("editor_id", sa.String(32, collation="utf8mb4_bin"),
                  nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["daily_plan_id"], ["daily_plans.id"]),
        sa.ForeignKeyConstraint(["editor_id"], ["accounts.id"]),
        sa.CheckConstraint("version >= 1",
                           name="ck_daily_plan_contents_version"),
        sa.UniqueConstraint(
            "daily_plan_id", "id", "version",
            name="uq_daily_plan_contents_plan_id_version",
        ),
        sa.UniqueConstraint(
            "daily_plan_id", "version",
            name="uq_daily_plan_contents_plan_version",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "ix_daily_plan_contents_daily_plan_id",
        "daily_plan_contents", ["daily_plan_id"],
    )

    # Resolve the cycle: the header may only point at a content row that
    # belongs to this same plan (daily_plan_id, id, version).
    op.create_foreign_key(
        "fk_daily_plans_current_content",
        "daily_plans",
        "daily_plan_contents",
        ["id", "current_content_id", "current_content_version"],
        ["daily_plan_id", "id", "version"],
    )

    op.create_table(
        "weekly_plan_sync_states",
        sa.Column("id", sa.String(32, collation="utf8mb4_bin"),
                  nullable=False),
        sa.Column("class_id", sa.String(32, collation="utf8mb4_bin"),
                  nullable=False),
        sa.Column("term_id", sa.String(32, collation="utf8mb4_bin"),
                  nullable=False),
        sa.Column("week_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("deterministic_themes", sa.JSON(), nullable=False),
        sa.Column("game_source_manifest", sa.JSON(), nullable=False),
        sa.Column("current_week_source_manifest", sa.JSON(), nullable=False),
        sa.Column("last_trigger_daily_plan_id",
                  sa.String(32, collation="utf8mb4_bin"), nullable=True),
        sa.Column("last_trigger_content_version", sa.Integer(), nullable=True),
        sa.Column("last_trigger_event", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"]),
        sa.ForeignKeyConstraint(["term_id"], ["terms.id"]),
        sa.ForeignKeyConstraint(["last_trigger_daily_plan_id"],
                                ["daily_plans.id"]),
        sa.CheckConstraint("status = 'pending_projection'",
                           name="ck_weekly_plan_sync_states_status"),
        sa.CheckConstraint(
            "last_trigger_event IS NULL OR last_trigger_event IN "
            "('create', 'update', 'delete')",
            name="ck_weekly_plan_sync_states_last_trigger_event",
        ),
        sa.UniqueConstraint(
            "class_id", "term_id", "week_number",
            name="uq_weekly_plan_sync_states_class_term_week",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "ix_weekly_plan_sync_states_class_id",
        "weekly_plan_sync_states", ["class_id"],
    )
    op.create_index(
        "ix_weekly_plan_sync_states_term_id",
        "weekly_plan_sync_states", ["term_id"],
    )

    # Extend the I2 target_type CHECK with daily_plan only.
    op.execute(
        "ALTER TABLE operation_records "
        "DROP CONSTRAINT ck_operation_record_target_type"
    )
    op.execute(
        "ALTER TABLE operation_records "
        "ADD CONSTRAINT ck_operation_record_target_type "
        "CHECK (target_type IN ('account', 'class', 'school', 'term', "
        "'calendar', 'daily_plan'))"
    )


def downgrade() -> None:
    """Destructive; blocked like the base I1/I2 migrations."""
    raise RuntimeError(
        "I3 daily plan downgrade is intentionally blocked: it would drop "
        "daily plans, content versions and weekly sync projection rows. "
        "Back up and downgrade manually if truly required."
    )
