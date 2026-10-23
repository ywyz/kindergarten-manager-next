"""D3-A local daily-plan history restore event/receipt.

Revision ID: 20261023_0005_local_history
Revises: 20261017_0004_local
Create Date: 2026-10-23

Adds one append-only table. Existing daily-plan content, AI provenance and
receipts are not altered or backfilled. Downgrade is refused for the same
reason as the earlier local migrations: a real local database is never
silently stripped of business history.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261023_0005_local_history"
down_revision: Union[str, None] = "20261017_0004_local"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "local_daily_plan_restores",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("profile_id", sa.String(32), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("daily_plan_id", sa.String(32), nullable=False),
        sa.Column("source_content_id", sa.String(32), nullable=False),
        sa.Column("source_content_version", sa.Integer, nullable=False),
        sa.Column("before_content_id", sa.String(32), nullable=False),
        sa.Column("before_content_version", sa.Integer, nullable=False),
        sa.Column("result_content_id", sa.String(32), nullable=False),
        sa.Column("result_content_version", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "source_content_version >= 1 AND before_content_version >= 1 "
            "AND result_content_version >= 1",
            name="ck_local_daily_plan_restores_versions",
        ),
        sa.UniqueConstraint(
            "profile_id", "request_id",
            name="uq_local_daily_plan_restores_profile_request",
        ),
        sa.UniqueConstraint(
            "result_content_id",
            name="uq_local_daily_plan_restores_result_content",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["local_profile.id"],
            name="fk_local_daily_plan_restores_profile",
        ),
        sa.ForeignKeyConstraint(
            ["daily_plan_id"], ["local_daily_plans.id"],
            name="fk_local_daily_plan_restores_plan",
        ),
        sa.ForeignKeyConstraint(
            ["daily_plan_id", "source_content_id", "source_content_version"],
            [
                "local_daily_plan_contents.daily_plan_id",
                "local_daily_plan_contents.id",
                "local_daily_plan_contents.version",
            ],
            name="fk_local_daily_plan_restores_source_triple",
        ),
        sa.ForeignKeyConstraint(
            ["daily_plan_id", "before_content_id", "before_content_version"],
            [
                "local_daily_plan_contents.daily_plan_id",
                "local_daily_plan_contents.id",
                "local_daily_plan_contents.version",
            ],
            name="fk_local_daily_plan_restores_before_triple",
        ),
        sa.ForeignKeyConstraint(
            ["daily_plan_id", "result_content_id", "result_content_version"],
            [
                "local_daily_plan_contents.daily_plan_id",
                "local_daily_plan_contents.id",
                "local_daily_plan_contents.version",
            ],
            name="fk_local_daily_plan_restores_result_triple",
        ),
    )
    op.create_index(
        "ix_local_daily_plan_restores_plan",
        "local_daily_plan_restores",
        ["daily_plan_id"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "local revision 0005 never drops the history restore receipt table: "
        "downgrade is not supported"
    )
