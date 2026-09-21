"""I1: identity registration, sessions and operation records.

账号、会话、首次管理员控制及操作记录表。
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260921_i1_identity_reg"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.String(32, collation="utf8mb4_bin"), nullable=False),
        sa.Column("username", sa.String(32, collation="utf8mb4_bin"), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("display_name", sa.String(80), nullable=True),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("auth_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=False),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username", name="uq_accounts_username"),
        sa.CheckConstraint("role IN ('admin', 'teacher')", name="ck_account_role"),
        sa.CheckConstraint("username = LOWER(username)", name="ck_username_lowercase"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )

    op.create_table(
        "first_admin_control",
        sa.Column("id", sa.String(32, collation="utf8mb4_bin"), nullable=False),
        sa.Column(
            "claimed", sa.Boolean(), nullable=False, server_default="0"
        ),
        sa.Column("first_admin_id", sa.String(32, collation="utf8mb4_bin"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["first_admin_id"],
            ["accounts.id"],
        ),
        sa.CheckConstraint("id = 'singleton'", name="ck_first_admin_control_singleton"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.String(32, collation="utf8mb4_bin"), nullable=False),
        sa.Column("token_hash", sa.String(64, collation="utf8mb4_bin"), nullable=False),
        sa.Column("account_id", sa.String(32, collation="utf8mb4_bin"), nullable=False),
        sa.Column("auth_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=False), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("ix_sessions_account_id", "sessions", ["account_id"])

    op.create_table(
        "operation_records",
        sa.Column("id", sa.String(32, collation="utf8mb4_bin"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("operator_id", sa.String(32, collation="utf8mb4_bin"), nullable=True),
        sa.Column("operator_type", sa.String(30), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("target_account_id", sa.String(32, collation="utf8mb4_bin"), nullable=False),
        sa.Column("account_version_after", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["operator_id"],
            ["accounts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["target_account_id"],
            ["accounts.id"],
        ),
        sa.CheckConstraint(
            "operator_type IN ('account', 'server_operator')",
            name="ck_operation_record_operator_type",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )

    op.bulk_insert(
        sa.table(
            "first_admin_control",
            sa.column("id", sa.String(32, collation="utf8mb4_bin")),
            sa.column("claimed", sa.Boolean),
            sa.column("first_admin_id", sa.String(32, collation="utf8mb4_bin")),
        ),
        [
            {"id": "singleton", "claimed": False, "first_admin_id": None},
        ],
    )


def downgrade() -> None:
    op.drop_table("operation_records")
    op.drop_index("ix_sessions_account_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("first_admin_control")
    op.drop_table("accounts")
