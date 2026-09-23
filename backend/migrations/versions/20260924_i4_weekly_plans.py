"""I4: weekly plans, append-only drafts, immutable confirmed snapshots.

三表先建（weekly_plans 指针列可空），再 ALTER 添加两条复合指针外键
（同 I3 fk_daily_plans_current_content 模式）。生成列 effective_week 实现
“同班同学期同周仅一条有效记录”（软删除行该列为 NULL，唯一索引允许多条
NULL）。扩展 operation_records.target_type CHECK 加入 weekly_plan，不移除
既有值。weekly_plan_sync_states 零改动；不修改 I1/I2/I3 任何既有行。
"""

from alembic import op
import sqlalchemy as sa


revision = "20260924_i4_weekly_plans"
down_revision = "20260923_i3_daily_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "weekly_plans",
        sa.Column("id", sa.String(32, collation="utf8mb4_bin"),
                  nullable=False),
        sa.Column("class_id", sa.String(32, collation="utf8mb4_bin"),
                  nullable=False),
        sa.Column("term_id", sa.String(32, collation="utf8mb4_bin"),
                  nullable=False),
        sa.Column("week_number", sa.Integer(), nullable=False),
        sa.Column("creator_id", sa.String(32, collation="utf8mb4_bin"),
                  nullable=False),
        sa.Column("owner_id", sa.String(32, collation="utf8mb4_bin"),
                  nullable=False),
        # Pointer columns stay nullable so the creation transaction can
        # insert the header first, the first draft row second, then the
        # pointer update; the composite FKs below enforce ownership.
        sa.Column("current_draft_content_id",
                  sa.String(32, collation="utf8mb4_bin"), nullable=True),
        sa.Column("current_draft_version", sa.Integer(), nullable=True),
        sa.Column("current_confirmed_content_id",
                  sa.String(32, collation="utf8mb4_bin"), nullable=True),
        sa.Column("current_confirmed_content_version", sa.Integer(),
                  nullable=True),
        sa.Column("school_name", sa.String(120), nullable=True),
        sa.Column("class_name", sa.String(80), nullable=False),
        sa.Column("grade", sa.String(20), nullable=False),
        sa.Column("header_teacher_names", sa.JSON(), nullable=False),
        sa.Column("caregiver_name", sa.String(80), nullable=True),
        sa.Column("projection_consumed_at", sa.DateTime(timezone=False),
                  nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("deleted_by", sa.String(32, collation="utf8mb4_bin"),
                  nullable=True),
        sa.Column(
            "effective_week",
            sa.Integer(),
            sa.Computed(
                "CASE WHEN deleted_at IS NULL THEN week_number END",
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
        sa.ForeignKeyConstraint(["owner_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["deleted_by"], ["accounts.id"]),
        sa.CheckConstraint("week_number >= 1",
                           name="ck_weekly_plans_week_number"),
        sa.CheckConstraint(
            "current_draft_version IS NULL OR current_draft_version >= 1",
            name="ck_weekly_plans_current_draft_version",
        ),
        sa.CheckConstraint(
            "current_confirmed_content_version IS NULL "
            "OR current_confirmed_content_version >= 1",
            name="ck_weekly_plans_current_confirmed_content_version",
        ),
        sa.UniqueConstraint(
            "class_id", "term_id", "effective_week",
            name="uq_weekly_plans_class_term_effective_week",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("ix_weekly_plans_class_id", "weekly_plans", ["class_id"])
    op.create_index("ix_weekly_plans_term_id", "weekly_plans", ["term_id"])

    op.create_table(
        "weekly_plan_contents",
        sa.Column("id", sa.String(32, collation="utf8mb4_bin"),
                  nullable=False),
        sa.Column("weekly_plan_id", sa.String(32, collation="utf8mb4_bin"),
                  nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("editor_id", sa.String(32, collation="utf8mb4_bin"),
                  nullable=False),
        sa.Column("editor_role", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["weekly_plan_id"], ["weekly_plans.id"]),
        sa.ForeignKeyConstraint(["editor_id"], ["accounts.id"]),
        sa.CheckConstraint("version >= 1",
                           name="ck_weekly_plan_contents_version"),
        sa.CheckConstraint(
            "editor_role IN ('owner', 'admin')",
            name="ck_weekly_plan_contents_editor_role",
        ),
        sa.UniqueConstraint(
            "weekly_plan_id", "id", "version",
            name="uq_weekly_plan_contents_plan_id_version",
        ),
        sa.UniqueConstraint(
            "weekly_plan_id", "version",
            name="uq_weekly_plan_contents_plan_version",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "ix_weekly_plan_contents_weekly_plan_id",
        "weekly_plan_contents", ["weekly_plan_id"],
    )

    op.create_table(
        "weekly_plan_confirmed_contents",
        sa.Column("id", sa.String(32, collation="utf8mb4_bin"),
                  nullable=False),
        sa.Column("weekly_plan_id", sa.String(32, collation="utf8mb4_bin"),
                  nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("draft_version", sa.Integer(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("facts", sa.JSON(), nullable=False),
        sa.Column("confirmed_by", sa.String(32, collation="utf8mb4_bin"),
                  nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["weekly_plan_id"], ["weekly_plans.id"]),
        sa.ForeignKeyConstraint(["confirmed_by"], ["accounts.id"]),
        sa.CheckConstraint("version >= 1",
                           name="ck_weekly_plan_confirmed_contents_version"),
        sa.UniqueConstraint(
            "weekly_plan_id", "id", "version",
            name="uq_weekly_plan_confirmed_contents_plan_id_version",
        ),
        sa.UniqueConstraint(
            "weekly_plan_id", "version",
            name="uq_weekly_plan_confirmed_contents_plan_version",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "ix_weekly_plan_confirmed_contents_weekly_plan_id",
        "weekly_plan_confirmed_contents", ["weekly_plan_id"],
    )

    # Resolve the cycles: the header may only point at a content row that
    # belongs to this same plan (weekly_plan_id, id, version).
    op.create_foreign_key(
        "fk_weekly_plans_current_draft_content",
        "weekly_plans",
        "weekly_plan_contents",
        ["id", "current_draft_content_id", "current_draft_version"],
        ["weekly_plan_id", "id", "version"],
    )
    op.create_foreign_key(
        "fk_weekly_plans_current_confirmed_content",
        "weekly_plans",
        "weekly_plan_confirmed_contents",
        [
            "id",
            "current_confirmed_content_id",
            "current_confirmed_content_version",
        ],
        ["weekly_plan_id", "id", "version"],
    )

    # Extend the I3 target_type CHECK with weekly_plan only; keep every
    # existing value.
    op.execute(
        "ALTER TABLE operation_records "
        "DROP CONSTRAINT ck_operation_record_target_type"
    )
    op.execute(
        "ALTER TABLE operation_records "
        "ADD CONSTRAINT ck_operation_record_target_type "
        "CHECK (target_type IN ('account', 'class', 'school', 'term', "
        "'calendar', 'daily_plan', 'weekly_plan'))"
    )


def downgrade() -> None:
    """Destructive; blocked like the base I1/I2/I3 migrations."""
    raise RuntimeError(
        "I4 weekly plan downgrade is intentionally blocked: it would drop "
        "weekly plans, draft versions and confirmed snapshots. "
        "Back up and downgrade manually if truly required."
    )
