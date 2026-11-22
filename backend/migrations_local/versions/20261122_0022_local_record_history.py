"""Retained listening/curriculum deliberation save history.

Revision ID: 20261122_0022_local_record_history
Revises: 20261112_0021_local_term_name_changes
Create Date: 2026-11-22

Forward-only addition: two append-only snapshot tables retain one full
read-only content copy per actual listening record save and per curriculum
deliberation save, bound to the record's own revision/version counter.
Existing rows, records and exported files are untouched.  A pre-feature
database upgrades with both tables empty; a record first modified afterwards
keeps its usable pre-modification original as the lowest retained version
instead of fabricating unknown intermediate revisions.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261122_0022_local_record_history"
down_revision: Union[str, None] = "20261112_0021_local_term_name_changes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "local_listening_record_versions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("record_id", sa.String(length=32), nullable=False),
        sa.Column("profile_id", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content_json", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "typeof(version) = 'integer' AND version >= 1",
            name="ck_local_listening_record_versions_version",
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64",
            name="ck_local_listening_record_versions_hash",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_listening_record_versions_profile",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id", "record_id"],
            ["local_listening_records.profile_id",
             "local_listening_records.id"],
            name="fk_local_listening_record_versions_record",
        ),
        sa.PrimaryKeyConstraint(
            "id", name="pk_local_listening_record_versions"
        ),
        sa.UniqueConstraint(
            "record_id", "version",
            name="uq_local_listening_record_versions_record_version",
        ),
    )
    op.create_index(
        "ix_local_listening_record_versions_profile_record",
        "local_listening_record_versions",
        ["profile_id", "record_id", "version"],
    )

    op.create_table(
        "local_curriculum_deliberation_versions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("record_id", sa.String(length=36), nullable=False),
        sa.Column("profile_id", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content_json", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("document_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "typeof(version) = 'integer' AND version >= 1",
            name="ck_local_curriculum_deliberation_versions_version",
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64",
            name="ck_local_curriculum_deliberation_versions_hash",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_curriculum_deliberation_versions_profile",
        ),
        sa.ForeignKeyConstraint(
            ["record_id"],
            ["local_curriculum_deliberations.id"],
            name="fk_local_curriculum_deliberation_versions_record",
        ),
        sa.PrimaryKeyConstraint(
            "id", name="pk_local_curriculum_deliberation_versions"
        ),
        sa.UniqueConstraint(
            "record_id", "version",
            name="uq_local_curriculum_deliberation_versions_record_version",
        ),
    )
    op.create_index(
        "ix_local_curriculum_deliberation_versions_record",
        "local_curriculum_deliberation_versions",
        ["record_id", "version"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "local schema is forward-only; restore a verified backup instead"
    )
