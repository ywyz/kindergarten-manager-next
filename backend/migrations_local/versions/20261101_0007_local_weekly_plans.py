"""Desktop weekly plans and appearance preference.

Revision ID: 20261101_0007_local_weekly
Revises: 20261025_0006_local_game_observations
Create Date: 2026-11-01

DDL/new-column revision only.  It creates the seven ``local_weekly_*``
tables, adds the ordered class header names / caregiver to ``local_classes``
and the appearance preference columns to ``local_settings``.  No existing
row value, config version, calendar/game revision, AI row or audit row is
changed; the weekly tables start empty and old rows get ``[]`` / ``NULL`` /
``light`` / ``1`` defaults.  ``env.py`` owns foreign_keys=OFF, BEGIN
IMMEDIATE, foreign_key_check, COMMIT and the pre/post d1_digest guard.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261101_0007_local_weekly"
down_revision: Union[str, None] = "20261025_0006_local_game_observations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "local_classes_new",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("grade", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column(
            "header_teacher_names",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("caregiver_name", sa.String(length=80), nullable=True),
        sa.CheckConstraint(
            "caregiver_name IS NULL OR length(caregiver_name) BETWEEN 1 AND 80",
            name="ck_local_classes_caregiver_name",
        ),
        sa.CheckConstraint(
            "length(name) BETWEEN 1 AND 80", name="ck_local_classes_name"
        ),
        sa.CheckConstraint(
            "grade IN ('small', 'middle', 'large')",
            name="ck_local_classes_grade",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_classes"),
        sa.UniqueConstraint("name", name="uq_local_classes_name"),
    )
    op.execute(
        'INSERT INTO local_classes_new '
        '(id, name, grade, created_at, updated_at, header_teacher_names, '
        'caregiver_name) '
        "SELECT id, name, grade, created_at, updated_at, '[]', NULL "
        "FROM local_classes"
    )
    op.drop_table("local_classes")
    op.rename_table("local_classes_new", "local_classes")

    op.create_table(
        "local_settings_new",
        sa.Column("id", sa.String(length=16), nullable=False),
        sa.Column("singleton", sa.Integer(), nullable=False),
        sa.Column("school_name", sa.String(length=120), nullable=True),
        sa.Column("current_class_id", sa.String(length=32), nullable=False),
        sa.Column("init_request_id", sa.String(length=36), nullable=False),
        sa.Column("init_input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("ui_theme", sa.String(length=5), nullable=False, server_default=sa.text("'light'")),
        sa.Column("ui_theme_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.CheckConstraint(
            "id = 'singleton'", name="ck_local_settings_singleton_id"
        ),
        sa.CheckConstraint("singleton = 1", name="ck_local_settings_singleton"),
        sa.CheckConstraint(
            "school_name IS NULL OR length(school_name) BETWEEN 1 AND 120",
            name="ck_local_settings_school_name",
        ),
        sa.CheckConstraint(
            "length(init_request_id) BETWEEN 1 AND 36",
            name="ck_local_settings_init_request_id",
        ),
        sa.CheckConstraint(
            "length(init_input_fingerprint) = 64",
            name="ck_local_settings_init_fingerprint",
        ),
        sa.CheckConstraint(
            "config_version >= 1", name="ck_local_settings_config_version"
        ),
        sa.CheckConstraint(
            "ui_theme IN ('light', 'dark')", name="ck_local_settings_ui_theme"
        ),
        sa.CheckConstraint(
            "typeof(ui_theme_version) = 'integer' AND ui_theme_version >= 1",
            name="ck_local_settings_ui_theme_version",
        ),
        sa.ForeignKeyConstraint(
            ["current_class_id"],
            ["local_classes.id"],
            name="fk_local_settings_current_class_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_settings"),
        sa.UniqueConstraint("singleton", name="uq_local_settings_singleton"),
    )
    op.execute(
        'INSERT INTO local_settings_new '
        '(id, singleton, school_name, current_class_id, init_request_id, '
        'init_input_fingerprint, created_at, updated_at, config_version, '
        'ui_theme, ui_theme_version) '
        "SELECT id, singleton, school_name, current_class_id, init_request_id, "
        "init_input_fingerprint, created_at, updated_at, config_version, "
        "'light', 1 FROM local_settings"
    )
    op.drop_table("local_settings")
    op.rename_table("local_settings_new", "local_settings")

    op.create_table(
        "local_weekly_plans",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("profile_id", sa.String(length=32), nullable=False),
        sa.Column("class_id", sa.String(length=32), nullable=False),
        sa.Column("term_id", sa.String(length=32), nullable=False),
        sa.Column("week_anchor_date", sa.Date(), nullable=False),
        sa.Column("week_number_snapshot", sa.Integer(), nullable=False),
        sa.Column("term_start_date", sa.Date(), nullable=False),
        sa.Column("term_end_date", sa.Date(), nullable=False),
        sa.Column("calendar_revision_id", sa.String(length=32), nullable=False),
        sa.Column("header_json", sa.JSON(), nullable=False),
        sa.Column("header_hash", sa.String(length=64), nullable=False),
        sa.Column("current_draft_id", sa.String(length=32), nullable=False),
        sa.Column("current_draft_version", sa.Integer(), nullable=False),
        sa.Column("current_confirmed_id", sa.String(length=32), nullable=True),
        sa.Column("current_confirmed_version", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "strftime('%w', week_anchor_date) = '1'",
            name="ck_local_weekly_plans_anchor_monday",
        ),
        sa.CheckConstraint(
            "typeof(week_number_snapshot) = 'integer' "
            "AND week_number_snapshot >= 1",
            name="ck_local_weekly_plans_week_number",
        ),
        sa.CheckConstraint(
            "typeof(current_draft_version) = 'integer' "
            "AND current_draft_version >= 1",
            name="ck_local_weekly_plans_draft_version",
        ),
        sa.CheckConstraint(
            "current_confirmed_version IS NULL OR "
            "(typeof(current_confirmed_version) = 'integer' "
            "AND current_confirmed_version >= 1)",
            name="ck_local_weekly_plans_confirmed_version",
        ),
        sa.CheckConstraint(
            "(current_confirmed_id IS NULL AND current_confirmed_version IS NULL) "
            "OR (current_confirmed_id IS NOT NULL "
            "AND current_confirmed_version IS NOT NULL)",
            name="ck_local_weekly_plans_confirmed_pair",
        ),
        sa.CheckConstraint(
            "term_start_date <= term_end_date",
            name="ck_local_weekly_plans_term_order",
        ),
        sa.CheckConstraint(
            "length(header_hash) = 64",
            name="ck_local_weekly_plans_header_hash",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_weekly_plans_profile",
        ),
        sa.ForeignKeyConstraint(
            ["class_id"],
            ["local_classes.id"],
            name="fk_local_weekly_plans_class",
        ),
        sa.ForeignKeyConstraint(
            ["term_id"],
            ["local_terms.id"],
            name="fk_local_weekly_plans_term",
        ),
        sa.ForeignKeyConstraint(
            ["term_id", "calendar_revision_id"],
            ["local_calendar_revisions.term_id", "local_calendar_revisions.id"],
            name="fk_local_weekly_plans_term_revision",
        ),
        sa.UniqueConstraint(
            "class_id", "term_id", "week_anchor_date",
            name="uq_local_weekly_plans_class_term_week",
        ),
        sa.UniqueConstraint(
            "profile_id", "id", name="uq_local_weekly_plans_profile_id"
        ),
        sa.ForeignKeyConstraint(
            ["id", "current_draft_id", "current_draft_version"],
            [
                "local_weekly_plan_contents.weekly_plan_id",
                "local_weekly_plan_contents.id",
                "local_weekly_plan_contents.version",
            ],
            name="fk_local_weekly_plans_current_draft",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["id", "current_confirmed_id", "current_confirmed_version"],
            [
                "local_weekly_plan_confirmations.weekly_plan_id",
                "local_weekly_plan_confirmations.id",
                "local_weekly_plan_confirmations.version",
            ],
            name="fk_local_weekly_plans_current_confirmed",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_weekly_plans"),
    )
    op.create_table(
        "local_weekly_plan_contents",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("weekly_plan_id", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("content_json", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("editor_profile_id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "typeof(version) = 'integer' AND version >= 1",
            name="ck_local_weekly_plan_contents_version",
        ),
        sa.CheckConstraint(
            "schema_version = 1",
            name="ck_local_weekly_plan_contents_schema_version",
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64",
            name="ck_local_weekly_plan_contents_hash",
        ),
        sa.ForeignKeyConstraint(
            ["weekly_plan_id"],
            ["local_weekly_plans.id"],
            name="fk_local_weekly_plan_contents_plan",
        ),
        sa.ForeignKeyConstraint(
            ["editor_profile_id"],
            ["local_profile.id"],
            name="fk_local_weekly_plan_contents_editor",
        ),
        sa.UniqueConstraint(
            "weekly_plan_id", "version",
            name="uq_local_weekly_plan_contents_plan_version",
        ),
        sa.UniqueConstraint(
            "weekly_plan_id", "id", "version",
            name="uq_local_weekly_plan_contents_plan_id_version",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_weekly_plan_contents"),
    )
    op.create_table(
        "local_weekly_plan_confirmations",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("weekly_plan_id", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("draft_id", sa.String(length=32), nullable=False),
        sa.Column("draft_version", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("facts_json", sa.JSON(), nullable=False),
        sa.Column("facts_hash", sa.String(length=64), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("confirmed_by", sa.String(length=32), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "typeof(version) = 'integer' AND version >= 1",
            name="ck_local_weekly_plan_confirmations_version",
        ),
        sa.CheckConstraint(
            "typeof(draft_version) = 'integer' AND draft_version >= 1",
            name="ck_local_weekly_plan_confirmations_draft_version",
        ),
        sa.CheckConstraint(
            "schema_version = 1",
            name="ck_local_weekly_plan_confirmations_schema_version",
        ),
        sa.CheckConstraint(
            "length(snapshot_hash) = 64",
            name="ck_local_weekly_plan_confirmations_snapshot_hash",
        ),
        sa.CheckConstraint(
            "length(facts_hash) = 64",
            name="ck_local_weekly_plan_confirmations_facts_hash",
        ),
        sa.ForeignKeyConstraint(
            ["weekly_plan_id"],
            ["local_weekly_plans.id"],
            name="fk_local_weekly_plan_confirmations_plan",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by"],
            ["local_profile.id"],
            name="fk_local_weekly_plan_confirmations_profile",
        ),
        sa.ForeignKeyConstraint(
            ["weekly_plan_id", "draft_id", "draft_version"],
            [
                "local_weekly_plan_contents.weekly_plan_id",
                "local_weekly_plan_contents.id",
                "local_weekly_plan_contents.version",
            ],
            name="fk_local_weekly_plan_confirmations_draft",
        ),
        sa.UniqueConstraint(
            "weekly_plan_id", "version",
            name="uq_local_weekly_plan_confirmations_plan_version",
        ),
        sa.UniqueConstraint(
            "weekly_plan_id", "id", "version",
            name="uq_local_weekly_plan_confirmations_plan_id_version",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_weekly_plan_confirmations"),
    )
    op.create_table(
        "local_weekly_export_snapshots",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("profile_id", sa.String(length=32), nullable=False),
        sa.Column("launch_id", sa.String(length=36), nullable=False),
        sa.Column("session_scope_hash", sa.String(length=64), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("manifest_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "length(manifest_hash) = 64",
            name="ck_local_weekly_export_snapshots_hash",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_weekly_export_snapshots_profile",
        ),
        sa.UniqueConstraint(
            "id", "profile_id",
            name="uq_local_weekly_export_snapshots_id_profile",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_weekly_export_snapshots"),
    )
    op.create_table(
        "local_weekly_export_tokens",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("snapshot_id", sa.String(length=32), nullable=False),
        sa.Column("profile_id", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("parent_attempt_id", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "length(token_hash) = 64",
            name="ck_local_weekly_export_tokens_hash",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id", "profile_id"],
            [
                "local_weekly_export_snapshots.id",
                "local_weekly_export_snapshots.profile_id",
            ],
            name="fk_local_weekly_export_tokens_snapshot",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id", "snapshot_id", "parent_attempt_id"],
            [
                "local_weekly_export_attempts.profile_id",
                "local_weekly_export_attempts.snapshot_id",
                "local_weekly_export_attempts.id",
            ],
            name="fk_local_weekly_export_tokens_parent_attempt",
        ),
        sa.UniqueConstraint(
            "token_hash", name="uq_local_weekly_export_tokens_hash"
        ),
        sa.UniqueConstraint(
            "id", "profile_id",
            name="uq_local_weekly_export_tokens_id_profile",
        ),
        sa.UniqueConstraint(
            "id", "profile_id", "snapshot_id",
            name="uq_local_weekly_export_tokens_id_profile_snapshot",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_weekly_export_tokens"),
    )
    op.create_index(
        "uq_local_weekly_export_tokens_parent",
        "local_weekly_export_tokens",
        ["profile_id", "snapshot_id", "parent_attempt_id"],
        unique=True,
        sqlite_where=sa.text("parent_attempt_id IS NOT NULL"),
    )
    op.create_table(
        "local_weekly_export_attempts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("profile_id", sa.String(length=32), nullable=False),
        sa.Column("snapshot_id", sa.String(length=32), nullable=False),
        sa.Column("token_id", sa.String(length=32), nullable=False),
        sa.Column("export_id_hash", sa.String(length=64), nullable=False),
        sa.Column("filename_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("result_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "byte_size",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "status IN ('in_progress', 'saved', 'cancelled', 'failed', "
            "'indeterminate')",
            name="ck_local_weekly_export_attempts_status",
        ),
        sa.CheckConstraint(
            "byte_size IS NOT NULL AND "
            "(typeof(byte_size) = 'integer' AND byte_size >= 0)",
            name="ck_local_weekly_export_attempts_size",
        ),
        sa.CheckConstraint(
            "(status = 'saved' AND byte_size > 0 "
            "AND result_hash IS NOT NULL AND length(result_hash) = 64) "
            "OR (status <> 'saved' AND byte_size = 0 "
            "AND result_hash IS NULL)",
            name="ck_local_weekly_export_attempts_result_shape",
        ),
        sa.CheckConstraint(
            "length(export_id_hash) = 64",
            name="ck_local_weekly_export_attempts_export_hash",
        ),
        sa.CheckConstraint(
            "length(filename_fingerprint) = 64",
            name="ck_local_weekly_export_attempts_filename",
        ),
        sa.CheckConstraint(
            "result_hash IS NULL OR length(result_hash) = 64",
            name="ck_local_weekly_export_attempts_result_hash",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id", "profile_id"],
            [
                "local_weekly_export_snapshots.id",
                "local_weekly_export_snapshots.profile_id",
            ],
            name="fk_local_weekly_export_attempts_snapshot",
        ),
        sa.ForeignKeyConstraint(
            ["token_id", "profile_id", "snapshot_id"],
            [
                "local_weekly_export_tokens.id",
                "local_weekly_export_tokens.profile_id",
                "local_weekly_export_tokens.snapshot_id",
            ],
            name="fk_local_weekly_export_attempts_token",
        ),
        sa.UniqueConstraint(
            "profile_id", "export_id_hash",
            name="uq_local_weekly_export_attempts_profile_export",
        ),
        sa.UniqueConstraint(
            "profile_id", "snapshot_id", "id",
            name="uq_local_weekly_export_attempts_profile_snapshot_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_weekly_export_attempts"),
    )
    op.create_table(
        "local_weekly_plan_operations",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("profile_id", sa.String(length=32), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("weekly_plan_id", sa.String(length=32), nullable=True),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("result_draft_id", sa.String(length=32), nullable=True),
        sa.Column("result_draft_version", sa.Integer(), nullable=True),
        sa.Column("result_confirmed_id", sa.String(length=32), nullable=True),
        sa.Column("result_confirmed_version", sa.Integer(), nullable=True),
        sa.Column("result_snapshot_id", sa.String(length=32), nullable=True),
        sa.Column("result_token_id", sa.String(length=32), nullable=True),
        sa.Column("launch_id", sa.String(length=36), nullable=True),
        sa.Column("session_scope_hash", sa.String(length=64), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "length(request_id) BETWEEN 1 AND 36",
            name="ck_local_weekly_plan_operations_request_id",
        ),
        sa.CheckConstraint(
            "length(input_fingerprint) = 64",
            name="ck_local_weekly_plan_operations_fingerprint",
        ),
        sa.CheckConstraint(
            "action IN ('create', 'save', 'refresh', 'confirm', "
            "'export_create', 'export_retry')",
            name="ck_local_weekly_plan_operations_action",
        ),
        sa.CheckConstraint(
            "result_draft_version IS NULL OR "
            "(typeof(result_draft_version) = 'integer' "
            "AND result_draft_version >= 1)",
            name="ck_local_weekly_plan_operations_draft_version",
        ),
        sa.CheckConstraint(
            "result_confirmed_version IS NULL OR "
            "(typeof(result_confirmed_version) = 'integer' "
            "AND result_confirmed_version >= 1)",
            name="ck_local_weekly_plan_operations_confirmed_version",
        ),
        sa.CheckConstraint(
            "(action IN ('create', 'save', 'refresh') "
            "AND weekly_plan_id IS NOT NULL "
            "AND result_draft_id IS NOT NULL "
            "AND result_draft_version IS NOT NULL "
            "AND result_confirmed_id IS NULL "
            "AND result_confirmed_version IS NULL "
            "AND result_snapshot_id IS NULL AND result_token_id IS NULL) "
            "OR (action = 'confirm' "
            "AND weekly_plan_id IS NOT NULL "
            "AND result_draft_id IS NOT NULL "
            "AND result_draft_version IS NOT NULL "
            "AND result_confirmed_id IS NOT NULL "
            "AND result_confirmed_version IS NOT NULL "
            "AND result_snapshot_id IS NULL AND result_token_id IS NULL) "
            "OR (action IN ('export_create', 'export_retry') "
            "AND weekly_plan_id IS NULL "
            "AND result_draft_id IS NULL AND result_draft_version IS NULL "
            "AND result_confirmed_id IS NULL "
            "AND result_confirmed_version IS NULL "
            "AND result_snapshot_id IS NOT NULL "
            "AND result_token_id IS NOT NULL "
            "AND launch_id IS NOT NULL "
            "AND session_scope_hash IS NOT NULL "
            "AND length(session_scope_hash) = 64)",
            name="ck_local_weekly_plan_operations_result_shape",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_weekly_plan_operations_profile",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id", "weekly_plan_id"],
            ["local_weekly_plans.profile_id", "local_weekly_plans.id"],
            name="fk_local_weekly_plan_operations_plan",
        ),
        sa.ForeignKeyConstraint(
            ["weekly_plan_id", "result_draft_id", "result_draft_version"],
            [
                "local_weekly_plan_contents.weekly_plan_id",
                "local_weekly_plan_contents.id",
                "local_weekly_plan_contents.version",
            ],
            name="fk_local_weekly_plan_operations_draft",
        ),
        sa.ForeignKeyConstraint(
            ["weekly_plan_id", "result_confirmed_id",
             "result_confirmed_version"],
            [
                "local_weekly_plan_confirmations.weekly_plan_id",
                "local_weekly_plan_confirmations.id",
                "local_weekly_plan_confirmations.version",
            ],
            name="fk_local_weekly_plan_operations_confirmed",
        ),
        sa.ForeignKeyConstraint(
            ["result_snapshot_id", "profile_id"],
            [
                "local_weekly_export_snapshots.id",
                "local_weekly_export_snapshots.profile_id",
            ],
            name="fk_local_weekly_plan_operations_snapshot",
        ),
        sa.ForeignKeyConstraint(
            ["result_token_id", "profile_id"],
            [
                "local_weekly_export_tokens.id",
                "local_weekly_export_tokens.profile_id",
            ],
            name="fk_local_weekly_plan_operations_token",
        ),
        sa.ForeignKeyConstraint(
            ["result_token_id", "profile_id", "result_snapshot_id"],
            [
                "local_weekly_export_tokens.id",
                "local_weekly_export_tokens.profile_id",
                "local_weekly_export_tokens.snapshot_id",
            ],
            name="fk_local_weekly_plan_operations_token_snapshot",
        ),
        sa.UniqueConstraint(
            "profile_id", "request_id",
            name="uq_local_weekly_plan_operations_profile_request",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_weekly_plan_operations"),
    )


def downgrade() -> None:
    raise RuntimeError(
        "local schema is forward-only; restore a verified backup instead"
    )
