"""Desktop curriculum deliberation records.

Revision ID: 20261109_0017_local_curriculum_deliberations
Revises: 20261108_0016_local_listening_goal_suggest
Create Date: 2026-11-09

Adds one current content table.  Saves use an explicit version compare; the
profile and stable class id own every row.  The table is forward-only like the
rest of the local schema.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261109_0017_local_curriculum_deliberations"
down_revision: Union[str, None] = "20261108_0016_local_listening_goal_suggest"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "local_curriculum_deliberations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("profile_id", sa.String(32), nullable=False),
        sa.Column("class_id", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("activity_name", sa.Text(), nullable=False),
        sa.Column("activity_date", sa.Date(), nullable=True),
        sa.Column("content_json", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "length(id) = 36",
            name="ck_local_curriculum_deliberations_id",
        ),
        sa.CheckConstraint(
            "typeof(version) = 'integer' AND version >= 1",
            name="ck_local_curriculum_deliberations_version",
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64",
            name="ck_local_curriculum_deliberations_hash",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_curriculum_deliberations_profile",
        ),
        sa.ForeignKeyConstraint(
            ["class_id"],
            ["local_classes.id"],
            name="fk_local_curriculum_deliberations_class",
        ),
        sa.PrimaryKeyConstraint(
            "id", name="pk_local_curriculum_deliberations"
        ),
    )
    op.create_index(
        "ix_local_curriculum_deliberations_profile_class_updated",
        "local_curriculum_deliberations",
        ["profile_id", "class_id", "updated_at"],
        unique=False,
    )


def downgrade() -> None:
    raise RuntimeError(
        "local schema is forward-only; restore a verified backup instead"
    )
