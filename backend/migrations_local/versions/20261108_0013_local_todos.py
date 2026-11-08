"""Personal todo tables.

Revision ID: 20261108_0013_local_todos
Revises: 20261108_0012_local_listening_rotation
Create Date: 2026-11-08

Forward-only: adds the two personal todo tables and their indexes.  Ownership
is the single local teacher profile; no class/term columns are introduced.
No existing table or row is rebuilt, so old archives stay readable and the
normal startup head upgrade only appends the new tables.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261108_0013_local_todos"
down_revision: Union[str, None] = "20261108_0012_local_listening_rotation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "local_todos",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("profile_id", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("completed", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "length(title) BETWEEN 1 AND 200",
            name="ck_local_todos_title",
        ),
        sa.CheckConstraint("version >= 1", name="ck_local_todos_version"),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_todos_profile",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_todos"),
    )
    op.create_index(
        "ix_local_todos_profile_order",
        "local_todos",
        ["profile_id", "completed", "due_date"],
    )

    op.create_table(
        "local_todo_operations",
        sa.Column("profile_id", sa.String(length=32), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("todo_id", sa.String(length=32), nullable=True),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "action IN ('create','update','delete')",
            name="ck_local_todo_operations_action",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_todo_operations_profile",
        ),
        sa.PrimaryKeyConstraint(
            "profile_id", "request_id",
            name="pk_local_todo_operations",
        ),
    )
    op.create_index(
        "ix_local_todo_operations_todo",
        "local_todo_operations",
        ["profile_id", "todo_id"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "local schema is forward-only; restore a verified backup instead"
    )
