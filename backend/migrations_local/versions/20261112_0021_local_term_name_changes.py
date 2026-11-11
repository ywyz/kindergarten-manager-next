"""Add the append-only local term rename timeline.

Revision ID: 20261112_0021_local_term_name_changes
Revises: 20261111_0020_local_todo_archive
Create Date: 2026-11-12

Forward-only addition: one row per committed local term rename records the old
and new names, whether existing documents switch to the new name, the
configuration version and the record-time boundary.  Existing terms, records,
snapshots and exported files are untouched.  A pre-feature database upgrades
with an empty timeline and keeps every current name unchanged.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261112_0021_local_term_name_changes"
down_revision: Union[str, None] = "20261111_0020_local_todo_archive"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "local_term_name_changes",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("term_id", sa.String(length=32), nullable=False),
        sa.Column("old_name", sa.String(length=80), nullable=False),
        sa.Column("new_name", sa.String(length=80), nullable=False),
        sa.Column(
            "update_existing_documents",
            sa.Boolean(),
            nullable=False,
        ),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column(
            "changed_at", sa.DateTime(timezone=False), nullable=False
        ),
        sa.CheckConstraint(
            "length(old_name) BETWEEN 1 AND 80",
            name="ck_local_term_name_changes_old_name",
        ),
        sa.CheckConstraint(
            "length(new_name) BETWEEN 1 AND 80",
            name="ck_local_term_name_changes_new_name",
        ),
        sa.CheckConstraint(
            "config_version >= 1",
            name="ck_local_term_name_changes_config_version",
        ),
        sa.ForeignKeyConstraint(
            ["term_id"],
            ["local_terms.id"],
            name="fk_local_term_name_changes_term",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_local_term_name_changes_term_time",
        "local_term_name_changes",
        ["term_id", "changed_at"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "local schema is forward-only; restore a verified backup instead"
    )
