"""Listening photo manual display rotation.

Revision ID: 20261108_0012_local_listening_rotation
Revises: 20261108_0011_local_config_ai
Create Date: 2026-11-08

Forward-only: adds one non-null quarter-turn count to managed listening
originals.  Original bytes, hashes, EXIF orientation and every existing row are
preserved; old rows default to zero manual rotation.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261108_0012_local_listening_rotation"
down_revision: Union[str, None] = "20261108_0011_local_config_ai"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("local_listening_assets") as batch_op:
        batch_op.add_column(
            sa.Column(
                "rotation_quarters",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
        batch_op.create_check_constraint(
            "ck_local_listening_assets_rotation",
            "typeof(rotation_quarters) = 'integer' "
            "AND rotation_quarters BETWEEN 0 AND 3",
        )


def downgrade() -> None:
    raise RuntimeError(
        "local schema is forward-only; restore a verified backup instead"
    )
