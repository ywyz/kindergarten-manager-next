"""Add the nullable personal-todo archive marker.

Revision ID: 20261111_0020_local_todo_archive
Revises: 20261110_0019_local_directional_revisions
Create Date: 2026-11-11

Forward-only: existing rows get archived_at = NULL and remain active. The
archive service enforces "completed only" before setting it; no bundle or AI
schema is touched.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261111_0020_local_todo_archive"
down_revision: Union[str, None] = "20261110_0019_local_directional_revisions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "local_todos",
        sa.Column("archived_at", sa.DateTime(timezone=False), nullable=True),
    )
    op.create_index(
        "ix_local_todos_profile_archive",
        "local_todos",
        ["profile_id", "archived_at"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "local schema is forward-only; restore a verified backup instead"
    )
