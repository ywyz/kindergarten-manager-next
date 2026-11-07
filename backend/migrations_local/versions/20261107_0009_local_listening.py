"""One-to-one listening storage (L1).

Revision ID: 20261107_0009_local_listening
Revises: 20261102_0008_local_weekly_ai
Create Date: 2026-11-07

This revision only creates the six listening tables.  It does not rewrite any
old row, does not seed a template row (the controlled manifest is the
template authority), and does not alter the observation resource path.  A
listening photo is registered in its own asset table and lives under the
existing managed root at
``observations/assets/listening/{record_id}/{asset_id}/...``.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261107_0009_local_listening"
down_revision: Union[str, None] = "20261102_0008_local_weekly_ai"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "local_listening_records",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("profile_id", sa.String(32), nullable=False),
        sa.Column("class_id", sa.String(32), nullable=False),
        sa.Column("term_id", sa.String(32), nullable=False),
        sa.Column("grade", sa.String(20), nullable=False),
        sa.Column("child_name", sa.String(80), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "grade IN ('small', 'middle', 'large')",
            name="ck_local_listening_records_grade",
        ),
        sa.CheckConstraint(
            "length(child_name) BETWEEN 1 AND 80",
            name="ck_local_listening_records_child_name",
        ),
        sa.CheckConstraint(
            "typeof(revision) = 'integer' AND revision >= 1",
            name="ck_local_listening_records_revision",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_listening_records_profile",
        ),
        sa.ForeignKeyConstraint(
            ["class_id"],
            ["local_classes.id"],
            name="fk_local_listening_records_class",
        ),
        sa.ForeignKeyConstraint(
            ["term_id"],
            ["local_terms.id"],
            name="fk_local_listening_records_term",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_listening_records"),
        sa.UniqueConstraint(
            "profile_id", "id",
            name="uq_local_listening_records_profile_id",
        ),
    )
    op.create_index(
        "ix_local_listening_records_profile_class_term",
        "local_listening_records",
        ["profile_id", "class_id", "term_id", "id"],
    )
    op.create_index(
        "ix_local_listening_records_profile_name",
        "local_listening_records",
        ["profile_id", "class_id", "term_id", "child_name"],
    )

    op.create_table(
        "local_listening_domains",
        sa.Column("record_id", sa.String(32), nullable=False),
        sa.Column("domain", sa.String(20), nullable=False),
        sa.Column("template_version", sa.String(20), nullable=False),
        sa.Column("template_sha256", sa.String(64), nullable=False),
        sa.Column("observation_date_text", sa.String(120), nullable=True),
        sa.Column("adult_count_text", sa.String(80), nullable=True),
        sa.Column("child_age_text", sa.String(80), nullable=True),
        sa.Column("goal", sa.Text(), nullable=True),
        sa.Column("observation_area", sa.Text(), nullable=True),
        sa.Column("overall_evaluation", sa.Text(), nullable=True),
        sa.Column("support_strategy", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "domain IN ('health', 'language', 'social', 'science', 'art')",
            name="ck_local_listening_domains_domain",
        ),
        sa.CheckConstraint(
            "length(template_version) BETWEEN 1 AND 20",
            name="ck_local_listening_domains_template_version",
        ),
        sa.CheckConstraint(
            "length(template_sha256) = 64",
            name="ck_local_listening_domains_template_sha",
        ),
        sa.CheckConstraint(
            "observation_date_text IS NULL "
            "OR length(observation_date_text) <= 120",
            name="ck_local_listening_domains_observation_date",
        ),
        sa.CheckConstraint(
            "adult_count_text IS NULL OR length(adult_count_text) <= 80",
            name="ck_local_listening_domains_adult_count",
        ),
        sa.CheckConstraint(
            "child_age_text IS NULL OR length(child_age_text) <= 80",
            name="ck_local_listening_domains_child_age",
        ),
        sa.CheckConstraint(
            "goal IS NULL OR length(goal) <= 4000",
            name="ck_local_listening_domains_goal",
        ),
        sa.CheckConstraint(
            "observation_area IS NULL OR length(observation_area) <= 4000",
            name="ck_local_listening_domains_area",
        ),
        sa.CheckConstraint(
            "overall_evaluation IS NULL OR length(overall_evaluation) <= 20000",
            name="ck_local_listening_domains_overall",
        ),
        sa.CheckConstraint(
            "support_strategy IS NULL OR length(support_strategy) <= 20000",
            name="ck_local_listening_domains_support",
        ),
        sa.ForeignKeyConstraint(
            ["record_id"],
            ["local_listening_records.id"],
            name="fk_local_listening_domains_record",
        ),
        sa.PrimaryKeyConstraint(
            "record_id", "domain",
            name="pk_local_listening_domains",
        ),
    )

    op.create_table(
        "local_listening_assets",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("record_id", sa.String(32), nullable=False),
        sa.Column("relative_path", sa.String(500), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("orientation", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "length(relative_path) BETWEEN 1 AND 500",
            name="ck_local_listening_assets_path",
        ),
        sa.CheckConstraint(
            "substr(relative_path, 1, 30) = 'observations/assets/listening/'",
            name="ck_local_listening_assets_path_root",
        ),
        sa.CheckConstraint(
            "length(display_name) BETWEEN 1 AND 255",
            name="ck_local_listening_assets_display_name",
        ),
        sa.CheckConstraint(
            "mime_type IN ('image/jpeg', 'image/png', 'image/webp', "
            "'image/gif', 'image/bmp')",
            name="ck_local_listening_assets_mime",
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64",
            name="ck_local_listening_assets_hash",
        ),
        sa.CheckConstraint(
            "typeof(byte_size) = 'integer' AND byte_size >= 0",
            name="ck_local_listening_assets_size",
        ),
        sa.CheckConstraint(
            "typeof(width) = 'integer' AND typeof(height) = 'integer' "
            "AND width >= 0 AND height >= 0",
            name="ck_local_listening_assets_dimensions",
        ),
        sa.CheckConstraint(
            "orientation IS NULL OR "
            "(typeof(orientation) = 'integer' AND orientation BETWEEN 1 AND 8)",
            name="ck_local_listening_assets_orientation",
        ),
        sa.ForeignKeyConstraint(
            ["record_id"],
            ["local_listening_records.id"],
            name="fk_local_listening_assets_record",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_listening_assets"),
        sa.UniqueConstraint(
            "record_id", "id",
            name="uq_local_listening_assets_record_id",
        ),
        sa.UniqueConstraint(
            "relative_path",
            name="uq_local_listening_assets_path",
        ),
    )

    op.create_table(
        "local_listening_photo_groups",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("record_id", sa.String(32), nullable=False),
        sa.Column("domain", sa.String(20), nullable=False),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("work_date_text", sa.String(120), nullable=True),
        sa.Column("listening_text", sa.Text(), nullable=True),
        sa.Column("asset_id", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "position IS NULL OR "
            "(typeof(position) = 'integer' AND position BETWEEN 0 AND 2)",
            name="ck_local_listening_groups_position",
        ),
        sa.CheckConstraint(
            "work_date_text IS NULL OR length(work_date_text) <= 120",
            name="ck_local_listening_groups_work_date",
        ),
        sa.CheckConstraint(
            "listening_text IS NULL OR length(listening_text) <= 20000",
            name="ck_local_listening_groups_text",
        ),
        sa.CheckConstraint(
            "asset_id IS NULL OR length(asset_id) BETWEEN 1 AND 32",
            name="ck_local_listening_groups_asset",
        ),
        sa.ForeignKeyConstraint(
            ["record_id", "domain"],
            ["local_listening_domains.record_id",
             "local_listening_domains.domain"],
            name="fk_local_listening_groups_domain",
        ),
        sa.ForeignKeyConstraint(
            ["record_id", "asset_id"],
            ["local_listening_assets.record_id",
             "local_listening_assets.id"],
            name="fk_local_listening_groups_asset",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_listening_photo_groups"),
        sa.UniqueConstraint(
            "record_id", "domain", "position",
            name="uq_local_listening_groups_position",
        ),
    )

    op.create_table(
        "local_listening_evaluation_choices",
        sa.Column("record_id", sa.String(32), nullable=False),
        sa.Column("domain", sa.String(20), nullable=False),
        sa.Column("item_id", sa.String(40), nullable=False),
        sa.Column("stars", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "length(item_id) BETWEEN 1 AND 40",
            name="ck_local_listening_choices_item_id",
        ),
        sa.CheckConstraint(
            "stars IS NULL OR "
            "(typeof(stars) = 'integer' AND stars IN (1, 2, 3))",
            name="ck_local_listening_choices_stars",
        ),
        sa.ForeignKeyConstraint(
            ["record_id", "domain"],
            ["local_listening_domains.record_id",
             "local_listening_domains.domain"],
            name="fk_local_listening_choices_domain",
        ),
        sa.PrimaryKeyConstraint(
            "record_id", "domain", "item_id",
            name="pk_local_listening_evaluation_choices",
        ),
    )

    op.create_table(
        "local_listening_operations",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("profile_id", sa.String(32), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("operation_kind", sa.String(40), nullable=False),
        sa.Column("record_id", sa.String(32), nullable=True),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "length(request_id) BETWEEN 1 AND 36",
            name="ck_local_listening_operations_request_id",
        ),
        sa.CheckConstraint(
            "length(request_fingerprint) = 64",
            name="ck_local_listening_operations_fingerprint",
        ),
        sa.CheckConstraint(
            "length(operation_kind) BETWEEN 1 AND 40",
            name="ck_local_listening_operations_kind",
        ),
        sa.CheckConstraint(
            "status IN ('committed', 'failed')",
            name="ck_local_listening_operations_status",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_listening_operations_profile",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id", "record_id"],
            ["local_listening_records.profile_id",
             "local_listening_records.id"],
            name="fk_local_listening_operations_record",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_listening_operations"),
        sa.UniqueConstraint(
            "profile_id", "request_id",
            name="uq_local_listening_operations_profile_request",
        ),
    )


def downgrade() -> None:
    op.drop_table("local_listening_operations")
    op.drop_table("local_listening_evaluation_choices")
    op.drop_table("local_listening_photo_groups")
    op.drop_table("local_listening_assets")
    op.drop_table("local_listening_domains")
    op.drop_index(
        "ix_local_listening_records_profile_name",
        table_name="local_listening_records",
    )
    op.drop_index(
        "ix_local_listening_records_profile_class_term",
        table_name="local_listening_records",
    )
    op.drop_table("local_listening_records")
