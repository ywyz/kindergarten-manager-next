"""D4-E observation model, source-chain and attribution data foundation.

Revision ID: 20261025_0006_local_game_observations
Revises: 20261023_0005_local_history
Create Date: 2026-10-25

This is a DDL/new-column backfill revision only.  It creates the observation
tables and rebuilds the four AI source tables plus the prompt-bundle task CHECK.
It deliberately does not insert observation prompt seeds: the existing cold
upgrade guard hashes every pre-upgrade business table, and a seed in this
revision would change the old row set before the guard can verify it.  The
startup prompt sync registers observation bundles only after both guard phases
have passed.

The revision does not commit, toggle PRAGMA or disable d1_digest.  ``env.py``
owns foreign_keys=OFF, BEGIN IMMEDIATE, foreign_key_check, COMMIT and the
post-commit guard.  Existing daily columns, values, row counts, FK chains and
parent UNIQUE constraints are preserved; only new columns are backfilled.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261025_0006_local_game_observations"
down_revision: Union[str, None] = "20261023_0005_local_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _fail(message: str) -> None:
    raise RuntimeError(f"0006 observation migration refused: {message}")


def _preflight() -> None:
    bind = op.get_bind()
    # The migration connection has foreign_keys=OFF, but foreign_key_check still
    # inspects existing rows.  Refuse any pre-existing violation before DDL;
    # INNER JOIN alone would silently drop missing parents.
    if bind.exec_driver_sql("PRAGMA foreign_key_check").fetchall():
        _fail("pre-existing foreign key violation")

    # Every old input must have a plan creator, all old daily columns and the
    # exact content triple.
    bad_input = bind.exec_driver_sql(
        "SELECT i.id FROM local_ai_inputs i "
        "LEFT JOIN local_daily_plans p ON p.id = i.daily_plan_id "
        "LEFT JOIN local_daily_plan_contents c "
        "ON c.daily_plan_id = i.daily_plan_id AND c.id = i.content_id "
        "AND c.version = i.content_version "
        "WHERE i.daily_plan_id IS NULL OR i.content_id IS NULL "
        "OR i.content_version IS NULL OR i.target_grade IS NULL "
        "OR p.creator_id IS NULL OR c.id IS NULL LIMIT 1"
    ).fetchone()
    if bad_input is not None:
        _fail("input missing daily source/profile/content")

    bad_task = bind.exec_driver_sql(
        "SELECT t.id FROM local_ai_tasks t "
        "LEFT JOIN local_ai_inputs i ON i.id = t.input_id "
        "LEFT JOIN local_daily_plans p ON p.id = i.daily_plan_id "
        "WHERE i.id IS NULL OR p.creator_id IS NULL "
        "OR t.profile_id != p.creator_id OR t.daily_plan_id != i.daily_plan_id "
        "OR t.task_type != i.task_type LIMIT 1"
    ).fetchone()
    if bad_task is not None:
        _fail("task/input/profile mismatch")

    bad_exec = bind.exec_driver_sql(
        "SELECT e.id FROM local_ai_executions e "
        "LEFT JOIN local_ai_tasks t ON t.id = e.task_id "
        "LEFT JOIN local_ai_inputs i ON i.id = e.input_id "
        "WHERE t.id IS NULL OR i.id IS NULL "
        "OR e.profile_id != t.profile_id OR e.input_id != t.input_id "
        "OR e.task_id != t.id OR e.daily_plan_id != t.daily_plan_id "
        "OR e.task_type != t.task_type LIMIT 1"
    ).fetchone()
    if bad_exec is not None:
        _fail("execution/task/input mismatch")

    bad_candidate = bind.exec_driver_sql(
        "SELECT c.id FROM local_ai_candidates c "
        "LEFT JOIN local_ai_executions e ON e.id = c.execution_id "
        "WHERE e.id IS NULL OR c.task_id != e.task_id OR c.input_id != e.input_id "
        "OR c.daily_plan_id != e.daily_plan_id OR c.task_type != e.task_type "
        "LIMIT 1"
    ).fetchone()
    if bad_candidate is not None:
        _fail("candidate/execution mismatch")


def _create_observation_tables() -> None:
    op.create_table(
        "local_observation_records",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("creator_profile_id", sa.String(32), nullable=False),
        sa.Column("observation_date", sa.Date(), nullable=True),
        sa.Column("record_type", sa.String(20), nullable=False),
        sa.Column("start_time", sa.String(5), nullable=True),
        sa.Column("end_time", sa.String(5), nullable=True),
        sa.Column("term_id", sa.String(32), nullable=True),
        sa.Column("term_snapshot_json", sa.JSON(), nullable=True),
        sa.Column("school_name", sa.String(120), nullable=True),
        sa.Column("class_name", sa.String(80), nullable=True),
        sa.Column("observer_name", sa.String(80), nullable=True),
        sa.Column("adult_count", sa.Integer(), nullable=True),
        sa.Column("child_count", sa.Integer(), nullable=True),
        sa.Column("age_years", sa.Integer(), nullable=True),
        sa.Column("subjects_json", sa.JSON(), nullable=False),
        sa.Column("environment", sa.Text(), nullable=True),
        sa.Column("current_draft_revision", sa.Integer(), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "record_type IN ('public', 'indoor', 'outdoor')",
            name="ck_local_observation_records_type",
        ),
        sa.CheckConstraint(
            "typeof(current_draft_revision) = 'integer' "
            "AND current_draft_revision >= 1",
            name="ck_local_observation_records_draft_revision",
        ),
        sa.CheckConstraint(
            "current_version IS NULL OR "
            "(typeof(current_version) = 'integer' AND current_version >= 1)",
            name="ck_local_observation_records_version",
        ),
        sa.CheckConstraint(
            "adult_count IS NULL OR "
            "(typeof(adult_count) = 'integer' AND adult_count >= 0)",
            name="ck_local_observation_records_adult_count",
        ),
        sa.CheckConstraint(
            "child_count IS NULL OR "
            "(typeof(child_count) = 'integer' AND child_count >= 0)",
            name="ck_local_observation_records_child_count",
        ),
        sa.CheckConstraint(
            "age_years IS NULL OR "
            "(typeof(age_years) = 'integer' AND age_years >= 0)",
            name="ck_local_observation_records_age",
        ),
        sa.ForeignKeyConstraint(
            ["creator_profile_id"], ["local_profile.id"],
            name="fk_local_observation_records_profile",
        ),
        sa.ForeignKeyConstraint(
            ["term_id"], ["local_terms.id"],
            name="fk_local_observation_records_term",
        ),
        sa.ForeignKeyConstraint(
            ["id", "current_version"],
            ["local_observation_versions.observation_id",
             "local_observation_versions.version"],
            name="fk_local_observation_records_current_version",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_observation_records"),
        sa.UniqueConstraint(
            "creator_profile_id", "id",
            name="uq_local_observation_records_profile_id",
        ),
    )
    op.create_index(
        "ix_local_observation_records_profile_date",
        "local_observation_records",
        ["creator_profile_id", "observation_date", "id"],
    )
    op.create_index(
        "ix_local_observation_records_term_date",
        "local_observation_records",
        ["term_id", "observation_date", "id"],
    )
    op.create_index(
        "ix_local_observation_records_type_date",
        "local_observation_records",
        ["record_type", "observation_date", "id"],
    )

    op.create_table(
        "local_observation_drafts",
        sa.Column("observation_id", sa.String(32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "typeof(revision) = 'integer' AND revision >= 1",
            name="ck_local_observation_drafts_revision",
        ),
        sa.ForeignKeyConstraint(
            ["observation_id"], ["local_observation_records.id"],
            name="fk_local_observation_drafts_record",
        ),
        sa.PrimaryKeyConstraint(
            "observation_id", name="pk_local_observation_drafts"
        ),
    )

    op.create_table(
        "local_observation_versions",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("observation_id", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("source_kind", sa.String(20), nullable=False),
        sa.Column("creator_profile_id", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "typeof(version) = 'integer' AND version >= 1",
            name="ck_local_observation_versions_version",
        ),
        sa.CheckConstraint(
            "source_kind IN ('manual', 'restore', 'adopt', 'retain')",
            name="ck_local_observation_versions_source_kind",
        ),
        sa.ForeignKeyConstraint(
            ["observation_id"], ["local_observation_records.id"],
            name="fk_local_observation_versions_record",
        ),
        sa.ForeignKeyConstraint(
            ["creator_profile_id"], ["local_profile.id"],
            name="fk_local_observation_versions_profile",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_observation_versions"),
        sa.UniqueConstraint(
            "observation_id", "version",
            name="uq_local_observation_versions_record_version",
        ),
        sa.UniqueConstraint(
            "observation_id", "id",
            name="uq_local_observation_versions_record_id",
        ),
    )

    op.create_table(
        "local_observation_assets",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("observation_id", sa.String(32), nullable=False),
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
            "typeof(byte_size) = 'integer' AND byte_size >= 0",
            name="ck_local_observation_assets_size",
        ),
        sa.CheckConstraint(
            "typeof(width) = 'integer' AND typeof(height) = 'integer' "
            "AND width >= 0 AND height >= 0",
            name="ck_local_observation_assets_dimensions",
        ),
        sa.ForeignKeyConstraint(
            ["observation_id"], ["local_observation_records.id"],
            name="fk_local_observation_assets_record",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_observation_assets"),
        sa.UniqueConstraint(
            "observation_id", "id",
            name="uq_local_observation_assets_record_id",
        ),
    )

    op.create_table(
        "local_observation_asset_derivatives",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("observation_id", sa.String(32), nullable=False),
        sa.Column("asset_id", sa.String(32), nullable=False),
        sa.Column("purpose", sa.String(20), nullable=False),
        sa.Column("params_version", sa.String(50), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("relative_path", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "purpose IN ('ai', 'export')",
            name="ck_local_observation_asset_derivatives_purpose",
        ),
        sa.CheckConstraint(
            "typeof(width) = 'integer' AND typeof(height) = 'integer' "
            "AND width >= 0 AND height >= 0",
            name="ck_local_observation_asset_derivatives_dimensions",
        ),
        sa.ForeignKeyConstraint(
            ["observation_id", "asset_id"],
            ["local_observation_assets.observation_id",
             "local_observation_assets.id"],
            name="fk_local_observation_asset_derivatives_asset",
        ),
        sa.PrimaryKeyConstraint(
            "id", name="pk_local_observation_asset_derivatives"
        ),
        sa.UniqueConstraint(
            "observation_id", "id",
            name="uq_local_observation_asset_derivatives_record_id",
        ),
        sa.UniqueConstraint(
            "observation_id", "asset_id", "id",
            name="uq_local_observation_asset_derivatives_asset_id",
        ),
    )

    op.create_table(
        "local_observation_draft_photos",
        sa.Column("observation_id", sa.String(32), nullable=False),
        sa.Column("asset_id", sa.String(32), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "typeof(sort_order) = 'integer' AND sort_order >= 0",
            name="ck_local_observation_draft_photos_order",
        ),
        sa.ForeignKeyConstraint(
            ["observation_id", "asset_id"],
            ["local_observation_assets.observation_id",
             "local_observation_assets.id"],
            name="fk_local_observation_draft_photos_asset",
        ),
        sa.PrimaryKeyConstraint(
            "observation_id", "asset_id",
            name="pk_local_observation_draft_photos",
        ),
        sa.UniqueConstraint(
            "observation_id", "sort_order",
            name="uq_local_observation_draft_photos_order",
        ),
    )

    op.create_table(
        "local_observation_version_photos",
        sa.Column("version_id", sa.String(32), nullable=False),
        sa.Column("asset_id", sa.String(32), nullable=False),
        sa.Column("observation_id", sa.String(32), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "typeof(sort_order) = 'integer' AND sort_order >= 0",
            name="ck_local_observation_version_photos_order",
        ),
        sa.ForeignKeyConstraint(
            ["observation_id", "version_id"],
            ["local_observation_versions.observation_id",
             "local_observation_versions.id"],
            name="fk_local_observation_version_photos_version",
        ),
        sa.ForeignKeyConstraint(
            ["observation_id", "asset_id"],
            ["local_observation_assets.observation_id",
             "local_observation_assets.id"],
            name="fk_local_observation_version_photos_asset",
        ),
        sa.PrimaryKeyConstraint(
            "version_id", "asset_id",
            name="pk_local_observation_version_photos",
        ),
        sa.UniqueConstraint(
            "version_id", "sort_order",
            name="uq_local_observation_version_photos_order",
        ),
    )

    op.create_table(
        "local_observation_operations",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("profile_id", sa.String(32), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("operation_kind", sa.String(40), nullable=False),
        sa.Column("observation_id", sa.String(32), nullable=True),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "length(request_id) BETWEEN 1 AND 36",
            name="ck_local_observation_operations_request_id",
        ),
        sa.CheckConstraint(
            "length(request_fingerprint) = 64",
            name="ck_local_observation_operations_fingerprint",
        ),
        sa.CheckConstraint(
            "status IN ('committed', 'failed')",
            name="ck_local_observation_operations_status",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["local_profile.id"],
            name="fk_local_observation_operations_profile",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id", "observation_id"],
            ["local_observation_records.creator_profile_id",
             "local_observation_records.id"],
            name="fk_local_observation_operations_record",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_observation_operations"),
        sa.UniqueConstraint(
            "profile_id", "request_id",
            name="uq_local_observation_operations_profile_request",
        ),
    )

    op.create_table(
        "local_observation_restores",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("operation_id", sa.String(32), nullable=False),
        sa.Column("profile_id", sa.String(32), nullable=False),
        sa.Column("observation_id", sa.String(32), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("result_version", sa.Integer(), nullable=False),
        sa.Column("before_draft_revision", sa.Integer(), nullable=False),
        sa.Column("before_version", sa.Integer(), nullable=True),
        sa.Column("changed", sa.Integer(), nullable=False),
        sa.Column("term_decision", sa.String(20), nullable=False),
        sa.Column("effective_term_id", sa.String(32), nullable=True),
        sa.Column("effective_payload_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "typeof(source_version) = 'integer' AND source_version >= 1 "
            "AND typeof(result_version) = 'integer' AND result_version >= 1 "
            "AND typeof(before_draft_revision) = 'integer' "
            "AND before_draft_revision >= 1",
            name="ck_local_observation_restores_versions",
        ),
        sa.CheckConstraint(
            "before_version IS NULL OR "
            "(typeof(before_version) = 'integer' AND before_version >= 1)",
            name="ck_local_observation_restores_before_version",
        ),
        sa.CheckConstraint(
            "changed IN (0, 1)",
            name="ck_local_observation_restores_changed",
        ),
        sa.CheckConstraint(
            "term_decision IN ('keep_history', 'keep_current', "
            "'assign_selected', 'unassigned')",
            name="ck_local_observation_restores_term_decision",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"], ["local_observation_operations.id"],
            name="fk_local_observation_restores_operation",
        ),
        sa.ForeignKeyConstraint(
            ["observation_id", "source_version"],
            ["local_observation_versions.observation_id",
             "local_observation_versions.version"],
            name="fk_local_observation_restores_source_version",
        ),
        sa.ForeignKeyConstraint(
            ["observation_id", "result_version"],
            ["local_observation_versions.observation_id",
             "local_observation_versions.version"],
            name="fk_local_observation_restores_result_version",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_observation_restores"),
        sa.UniqueConstraint(
            "operation_id",
            name="uq_local_observation_restores_operation",
        ),
    )

    op.create_table(
        "local_observation_restore_previews",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("profile_id", sa.String(32), nullable=False),
        sa.Column("observation_id", sa.String(32), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("base_draft_revision", sa.Integer(), nullable=False),
        sa.Column("base_draft_hash", sa.String(64), nullable=False),
        sa.Column("effective_term_id", sa.String(32), nullable=True),
        sa.Column("term_snapshot_hash", sa.String(64), nullable=True),
        sa.Column("effective_payload_hash", sa.String(64), nullable=False),
        sa.Column("material_hash", sa.String(64), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "typeof(source_version) = 'integer' AND source_version >= 1 "
            "AND typeof(base_draft_revision) = 'integer' "
            "AND base_draft_revision >= 1",
            name="ck_local_observation_restore_previews_versions",
        ),
        sa.ForeignKeyConstraint(
            ["observation_id", "source_version"],
            ["local_observation_versions.observation_id",
             "local_observation_versions.version"],
            name="fk_local_observation_restore_previews_source",
        ),
        sa.PrimaryKeyConstraint(
            "id", name="pk_local_observation_restore_previews"
        ),
        sa.UniqueConstraint(
            "token_hash",
            name="uq_local_observation_restore_previews_token",
        ),
    )

    op.create_table(
        "local_observation_export_snapshots",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("profile_id", sa.String(32), nullable=False),
        sa.Column("launch_id", sa.String(36), nullable=False),
        sa.Column("session_scope_hash", sa.String(64), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=False), nullable=False),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["local_profile.id"],
            name="fk_local_observation_export_snapshots_profile",
        ),
        sa.PrimaryKeyConstraint(
            "id", name="pk_local_observation_export_snapshots"
        ),
    )

    op.create_table(
        "local_observation_export_tokens",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("snapshot_id", sa.String(32), nullable=False),
        sa.Column("profile_id", sa.String(32), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.ForeignKeyConstraint(
            ["snapshot_id"], ["local_observation_export_snapshots.id"],
            name="fk_local_observation_export_tokens_snapshot",
        ),
        sa.PrimaryKeyConstraint(
            "id", name="pk_local_observation_export_tokens"
        ),
        sa.UniqueConstraint(
            "token_hash", name="uq_local_observation_export_tokens_hash"
        ),
    )

    op.create_table(
        "local_observation_export_attempts",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("profile_id", sa.String(32), nullable=False),
        sa.Column("snapshot_id", sa.String(32), nullable=False),
        sa.Column("export_id_hash", sa.String(64), nullable=False),
        sa.Column("filename_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("result_hash", sa.String(64), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "status IN ('in_progress', 'saved', 'cancelled', 'failed', "
            "'indeterminate')",
            name="ck_local_observation_export_attempts_status",
        ),
        sa.CheckConstraint(
            "byte_size IS NULL OR "
            "(typeof(byte_size) = 'integer' AND byte_size >= 0)",
            name="ck_local_observation_export_attempts_size",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"], ["local_observation_export_snapshots.id"],
            name="fk_local_observation_export_attempts_snapshot",
        ),
        sa.PrimaryKeyConstraint(
            "id", name="pk_local_observation_export_attempts"
        ),
        sa.UniqueConstraint(
            "profile_id", "export_id_hash",
            name="uq_local_observation_export_attempts_profile_export",
        ),
    )


def _rebuild_ai_inputs() -> None:
    op.create_table(
        "local_ai_inputs_new",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("profile_id", sa.String(32), nullable=False),
        sa.Column("source_kind", sa.String(20), nullable=False),
        sa.Column("source_id", sa.String(32), nullable=False),
        sa.Column("observation_id", sa.String(32), nullable=True),
        sa.Column("source_revision", sa.Integer(), nullable=True),
        sa.Column("daily_plan_id", sa.String(32), nullable=True),
        sa.Column("content_id", sa.String(32), nullable=True),
        sa.Column("content_version", sa.Integer(), nullable=True),
        sa.Column("task_type", sa.String(40), nullable=False),
        sa.Column("target_grade", sa.String(20), nullable=True),
        sa.Column("input_schema_version", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("dependencies_json", sa.JSON(), nullable=False),
        sa.Column("dependency_hash", sa.String(64), nullable=False),
        sa.Column("target_hashes_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "typeof(input_schema_version) = 'integer' AND input_schema_version >= 1",
            name="ck_local_ai_inputs_input_schema_version",
        ),
        sa.CheckConstraint(
            "task_type IN ('daily_lesson_split', 'daily_process_adapt', "
            "'daily_other_activities', 'game_observation_generate', "
            "'game_observation_rewrite')",
            name="ck_local_ai_inputs_task_type",
        ),
        sa.CheckConstraint(
            "source_kind IN ('daily_plan', 'game_observation')",
            name="ck_local_ai_inputs_source_kind",
        ),
        sa.CheckConstraint(
            "(source_kind = 'daily_plan' "
            "AND task_type IN ('daily_lesson_split', 'daily_process_adapt', "
            "'daily_other_activities') "
            "AND daily_plan_id IS NOT NULL AND content_id IS NOT NULL "
            "AND content_version IS NOT NULL AND target_grade IS NOT NULL "
            "AND target_grade IN ('small', 'middle', 'large') "
            "AND observation_id IS NULL AND source_id = daily_plan_id "
            "AND source_revision IS NULL) "
            "OR "
            "(source_kind = 'game_observation' "
            "AND task_type IN ('game_observation_generate', "
            "'game_observation_rewrite') "
            "AND daily_plan_id IS NULL AND content_id IS NULL "
            "AND content_version IS NULL AND target_grade IS NULL "
            "AND observation_id IS NOT NULL AND source_id = observation_id "
            "AND source_revision IS NOT NULL "
            "AND typeof(source_revision) = 'integer' "
            "AND source_revision >= 1)",
            name="ck_local_ai_inputs_source_match",
        ),
        sa.ForeignKeyConstraint(
            ["daily_plan_id", "content_id", "content_version"],
            ["local_daily_plan_contents.daily_plan_id",
             "local_daily_plan_contents.id",
             "local_daily_plan_contents.version"],
            name="fk_local_ai_inputs_content_triple",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["local_profile.id"],
            name="fk_local_ai_inputs_profile_id",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id", "observation_id"],
            ["local_observation_records.creator_profile_id",
             "local_observation_records.id"],
            name="fk_local_ai_inputs_observation",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_ai_inputs"),
        sa.UniqueConstraint(
            "daily_plan_id", "id", "task_type",
            name="uq_local_ai_inputs_plan_id_task",
        ),
        sa.UniqueConstraint(
            "profile_id", "source_kind", "source_id", "id", "task_type",
            name="uq_local_ai_inputs_source_task",
        ),
        sa.UniqueConstraint(
            "profile_id", "source_kind", "source_id", "id",
            name="uq_local_ai_inputs_source_id",
        ),
    )
    bind = op.get_bind()
    bind.exec_driver_sql(
        "INSERT INTO local_ai_inputs_new ("
        "id, profile_id, source_kind, source_id, observation_id, source_revision, "
        "daily_plan_id, content_id, content_version, task_type, target_grade, "
        "input_schema_version, payload_json, dependencies_json, dependency_hash, "
        "target_hashes_json, created_at) "
        "SELECT i.id, p.creator_id, 'daily_plan', i.daily_plan_id, NULL, NULL, "
        "i.daily_plan_id, i.content_id, i.content_version, i.task_type, i.target_grade, "
        "i.input_schema_version, i.payload_json, i.dependencies_json, i.dependency_hash, "
        "i.target_hashes_json, i.created_at "
        "FROM local_ai_inputs i JOIN local_daily_plans p ON p.id = i.daily_plan_id"
    )
    before = bind.exec_driver_sql("SELECT count(*) FROM local_ai_inputs").scalar()
    after = bind.exec_driver_sql("SELECT count(*) FROM local_ai_inputs_new").scalar()
    if before != after:
        _fail("input copy row-count mismatch")
    op.drop_table("local_ai_inputs")
    op.rename_table("local_ai_inputs_new", "local_ai_inputs")
    op.create_index(
        "ix_local_ai_inputs_source_task",
        "local_ai_inputs",
        ["profile_id", "source_kind", "source_id", "task_type"],
    )


def _rebuild_ai_tasks() -> None:
    op.create_table(
        "local_ai_tasks_new",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("profile_id", sa.String(32), nullable=False),
        sa.Column("source_kind", sa.String(20), nullable=False),
        sa.Column("source_id", sa.String(32), nullable=False),
        sa.Column("observation_id", sa.String(32), nullable=True),
        sa.Column("daily_plan_id", sa.String(32), nullable=True),
        sa.Column("task_type", sa.String(40), nullable=False),
        sa.Column("input_id", sa.String(32), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(200), nullable=True),
        sa.Column("current_execution_id", sa.String(32), nullable=True),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("runtime_meta_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "typeof(generation) = 'integer' AND generation >= 0",
            name="ck_local_ai_tasks_generation",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'claimed', 'dispatching', 'retry_wait', "
            "'paused', 'succeeded', 'failed', 'outcome_unknown', 'cancelled')",
            name="ck_local_ai_tasks_status",
        ),
        sa.CheckConstraint(
            "source_kind IN ('daily_plan', 'game_observation')",
            name="ck_local_ai_tasks_source_kind",
        ),
        sa.CheckConstraint(
            "(source_kind = 'daily_plan' "
            "AND task_type IN ('daily_lesson_split', 'daily_process_adapt', "
            "'daily_other_activities') "
            "AND daily_plan_id IS NOT NULL AND observation_id IS NULL "
            "AND source_id = daily_plan_id) "
            "OR "
            "(source_kind = 'game_observation' "
            "AND task_type IN ('game_observation_generate', "
            "'game_observation_rewrite') "
            "AND daily_plan_id IS NULL AND observation_id IS NOT NULL "
            "AND source_id = observation_id)",
            name="ck_local_ai_tasks_source_match",
        ),
        sa.ForeignKeyConstraint(
            ["daily_plan_id", "input_id", "task_type"],
            ["local_ai_inputs.daily_plan_id", "local_ai_inputs.id",
             "local_ai_inputs.task_type"],
            name="fk_local_ai_tasks_input",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id", "source_kind", "source_id", "input_id", "task_type"],
            ["local_ai_inputs.profile_id", "local_ai_inputs.source_kind",
             "local_ai_inputs.source_id", "local_ai_inputs.id",
             "local_ai_inputs.task_type"],
            name="fk_local_ai_tasks_source_input",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["local_profile.id"],
            name="fk_local_ai_tasks_profile_id",
        ),
        sa.ForeignKeyConstraint(
            ["id", "current_execution_id"],
            ["local_ai_executions.task_id", "local_ai_executions.id"],
            name="fk_local_ai_tasks_current_execution",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_ai_tasks"),
        sa.UniqueConstraint(
            "daily_plan_id", "id", "input_id", "task_type",
            name="uq_local_ai_tasks_plan_input",
        ),
        sa.UniqueConstraint(
            "profile_id", "source_kind", "source_id", "id", "input_id",
            "task_type",
            name="uq_local_ai_tasks_source_input",
        ),
    )
    bind = op.get_bind()
    bind.exec_driver_sql(
        "INSERT INTO local_ai_tasks_new ("
        "id, profile_id, source_kind, source_id, observation_id, daily_plan_id, "
        "task_type, input_id, status, reason, current_execution_id, generation, "
        "runtime_meta_json, created_at, updated_at) "
        "SELECT t.id, t.profile_id, i.source_kind, i.source_id, NULL, t.daily_plan_id, "
        "t.task_type, t.input_id, t.status, t.reason, t.current_execution_id, "
        "t.generation, t.runtime_meta_json, t.created_at, t.updated_at "
        "FROM local_ai_tasks t JOIN local_ai_inputs i ON i.id = t.input_id"
    )
    before = bind.exec_driver_sql("SELECT count(*) FROM local_ai_tasks").scalar()
    after = bind.exec_driver_sql("SELECT count(*) FROM local_ai_tasks_new").scalar()
    if before != after:
        _fail("task copy row-count mismatch")
    op.drop_table("local_ai_tasks")
    op.rename_table("local_ai_tasks_new", "local_ai_tasks")
    op.create_index(
        "ix_local_ai_tasks_status_created",
        "local_ai_tasks", ["status", "created_at", "id"],
    )
    op.create_index(
        "ix_local_ai_tasks_plan_created",
        "local_ai_tasks", ["daily_plan_id", "created_at", "id"],
    )
    op.create_index(
        "ix_local_ai_tasks_source_status",
        "local_ai_tasks",
        ["profile_id", "source_kind", "source_id", "status", "updated_at"],
    )
    op.create_index(
        "uq_local_ai_tasks_active_per_plan_type",
        "local_ai_tasks", ["daily_plan_id", "task_type"],
        unique=True,
        sqlite_where=sa.text(
            "status IN ('pending', 'claimed', 'dispatching', 'retry_wait')"
        ),
    )
    op.create_index(
        "uq_local_ai_tasks_active_per_source_type",
        "local_ai_tasks",
        ["profile_id", "source_kind", "source_id", "task_type"],
        unique=True,
        sqlite_where=sa.text(
            "source_kind = 'game_observation' AND status IN "
            "('pending', 'claimed', 'dispatching', 'retry_wait')"
        ),
    )


def _rebuild_ai_executions() -> None:
    op.create_table(
        "local_ai_executions_new",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("task_id", sa.String(32), nullable=False),
        sa.Column("source_kind", sa.String(20), nullable=False),
        sa.Column("source_id", sa.String(32), nullable=False),
        sa.Column("observation_id", sa.String(32), nullable=True),
        sa.Column("daily_plan_id", sa.String(32), nullable=True),
        sa.Column("input_id", sa.String(32), nullable=False),
        sa.Column("task_type", sa.String(40), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("launch_id", sa.String(36), nullable=False),
        sa.Column("permit_id", sa.String(36), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.String(32), nullable=False),
        sa.Column("personal_revision", sa.Integer(), nullable=False),
        sa.Column("contract_version", sa.Integer(), nullable=False),
        sa.Column("default_revision", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("runtime_meta_json", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=False), nullable=True),
        sa.CheckConstraint(
            "typeof(generation) = 'integer' AND generation >= 1",
            name="ck_local_ai_executions_generation",
        ),
        sa.CheckConstraint(
            "typeof(config_version) = 'integer' AND config_version >= 1",
            name="ck_local_ai_executions_config_version_check",
        ),
        sa.CheckConstraint(
            "typeof(personal_revision) = 'integer' AND personal_revision >= 1",
            name="ck_local_ai_executions_personal_revision_check",
        ),
        sa.CheckConstraint(
            "typeof(contract_version) = 'integer' AND contract_version >= 1",
            name="ck_local_ai_executions_contract_version_check",
        ),
        sa.CheckConstraint(
            "typeof(default_revision) = 'integer' AND default_revision >= 1",
            name="ck_local_ai_executions_default_revision_check",
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'claimed', 'dispatching', 'retry_wait', "
            "'paused', 'succeeded', 'failed', 'outcome_unknown', 'cancelled')",
            name="ck_local_ai_executions_state",
        ),
        sa.CheckConstraint(
            "source_kind IN ('daily_plan', 'game_observation')",
            name="ck_local_ai_executions_source_kind",
        ),
        sa.CheckConstraint(
            "(source_kind = 'daily_plan' "
            "AND task_type IN ('daily_lesson_split', 'daily_process_adapt', "
            "'daily_other_activities') "
            "AND daily_plan_id IS NOT NULL AND observation_id IS NULL "
            "AND source_id = daily_plan_id) "
            "OR "
            "(source_kind = 'game_observation' "
            "AND task_type IN ('game_observation_generate', "
            "'game_observation_rewrite') "
            "AND daily_plan_id IS NULL AND observation_id IS NOT NULL "
            "AND source_id = observation_id)",
            name="ck_local_ai_executions_source_match",
        ),
        sa.ForeignKeyConstraint(
            ["daily_plan_id", "task_id", "input_id", "task_type"],
            ["local_ai_tasks.daily_plan_id", "local_ai_tasks.id",
             "local_ai_tasks.input_id", "local_ai_tasks.task_type"],
            name="fk_local_ai_executions_task",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id", "source_kind", "source_id", "task_id", "input_id",
             "task_type"],
            ["local_ai_tasks.profile_id", "local_ai_tasks.source_kind",
             "local_ai_tasks.source_id", "local_ai_tasks.id",
             "local_ai_tasks.input_id", "local_ai_tasks.task_type"],
            name="fk_local_ai_executions_source_task",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["local_profile.id"],
            name="fk_local_ai_executions_profile_id",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id", "config_version"],
            ["local_ai_config_versions.profile_id",
             "local_ai_config_versions.version"],
            name="fk_local_ai_executions_config_version",
            deferrable=True, initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id", "task_type", "personal_revision"],
            ["local_personal_prompt_versions.profile_id",
             "local_personal_prompt_versions.task_type",
             "local_personal_prompt_versions.revision"],
            name="fk_local_ai_executions_personal_revision",
            deferrable=True, initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["task_type", "contract_version", "default_revision"],
            ["local_prompt_bundles.task_type", "local_prompt_bundles.contract_version",
             "local_prompt_bundles.default_revision"],
            name="fk_local_ai_executions_default_bundle",
            deferrable=True, initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_ai_executions"),
        sa.UniqueConstraint(
            "task_id", "generation",
            name="uq_local_ai_executions_task_generation",
        ),
        sa.UniqueConstraint(
            "task_id", "id", name="uq_local_ai_executions_task_id",
        ),
        sa.UniqueConstraint(
            "daily_plan_id", "task_id", "input_id", "task_type", "id",
            name="uq_local_ai_executions_plan_task_input_id",
        ),
        sa.UniqueConstraint(
            "profile_id", "source_kind", "source_id", "id", "task_id",
            "input_id", "task_type",
            name="uq_local_ai_executions_source_task_input_id",
        ),
    )
    bind = op.get_bind()
    bind.exec_driver_sql(
        "INSERT INTO local_ai_executions_new ("
        "id, task_id, source_kind, source_id, observation_id, daily_plan_id, "
        "input_id, task_type, generation, launch_id, permit_id, config_version, "
        "profile_id, personal_revision, contract_version, default_revision, state, "
        "runtime_meta_json, started_at, created_at, ended_at) "
        "SELECT e.id, e.task_id, i.source_kind, i.source_id, NULL, e.daily_plan_id, "
        "e.input_id, e.task_type, e.generation, e.launch_id, e.permit_id, "
        "e.config_version, e.profile_id, e.personal_revision, e.contract_version, "
        "e.default_revision, e.state, e.runtime_meta_json, e.started_at, "
        "e.created_at, e.ended_at "
        "FROM local_ai_executions e JOIN local_ai_inputs i ON i.id = e.input_id"
    )
    before = bind.exec_driver_sql("SELECT count(*) FROM local_ai_executions").scalar()
    after = bind.exec_driver_sql("SELECT count(*) FROM local_ai_executions_new").scalar()
    if before != after:
        _fail("execution copy row-count mismatch")
    op.drop_table("local_ai_executions")
    op.rename_table("local_ai_executions_new", "local_ai_executions")
    op.create_index(
        "ix_local_ai_executions_source_task",
        "local_ai_executions",
        ["profile_id", "source_kind", "source_id", "task_id", "generation"],
    )


def _rebuild_ai_candidates() -> None:
    op.create_table(
        "local_ai_candidates_new",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("profile_id", sa.String(32), nullable=False),
        sa.Column("execution_id", sa.String(32), nullable=False),
        sa.Column("task_id", sa.String(32), nullable=False),
        sa.Column("source_kind", sa.String(20), nullable=False),
        sa.Column("source_id", sa.String(32), nullable=False),
        sa.Column("observation_id", sa.String(32), nullable=True),
        sa.Column("daily_plan_id", sa.String(32), nullable=True),
        sa.Column("input_id", sa.String(32), nullable=False),
        sa.Column("task_type", sa.String(40), nullable=False),
        sa.Column("contract_version", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("raw_candidate_json", sa.JSON(), nullable=False),
        sa.Column("candidate_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "typeof(contract_version) = 'integer' AND contract_version >= 1",
            name="ck_local_ai_candidates_contract_version",
        ),
        sa.CheckConstraint(
            "typeof(schema_version) = 'integer' AND schema_version >= 1",
            name="ck_local_ai_candidates_schema_version",
        ),
        sa.CheckConstraint(
            "source_kind IN ('daily_plan', 'game_observation')",
            name="ck_local_ai_candidates_source_kind",
        ),
        sa.CheckConstraint(
            "(source_kind = 'daily_plan' "
            "AND task_type IN ('daily_lesson_split', 'daily_process_adapt', "
            "'daily_other_activities') "
            "AND daily_plan_id IS NOT NULL AND observation_id IS NULL "
            "AND source_id = daily_plan_id) "
            "OR "
            "(source_kind = 'game_observation' "
            "AND task_type IN ('game_observation_generate', "
            "'game_observation_rewrite') "
            "AND daily_plan_id IS NULL AND observation_id IS NOT NULL "
            "AND source_id = observation_id)",
            name="ck_local_ai_candidates_source_match",
        ),
        sa.ForeignKeyConstraint(
            ["execution_id", "task_id", "daily_plan_id", "input_id", "task_type"],
            ["local_ai_executions.id", "local_ai_executions.task_id",
             "local_ai_executions.daily_plan_id", "local_ai_executions.input_id",
             "local_ai_executions.task_type"],
            name="fk_local_ai_candidates_execution",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id", "source_kind", "source_id", "execution_id",
             "task_id", "input_id", "task_type"],
            ["local_ai_executions.profile_id", "local_ai_executions.source_kind",
             "local_ai_executions.source_id", "local_ai_executions.id",
             "local_ai_executions.task_id", "local_ai_executions.input_id",
             "local_ai_executions.task_type"],
            name="fk_local_ai_candidates_source_execution",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["local_profile.id"],
            name="fk_local_ai_candidates_profile_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_ai_candidates"),
        sa.UniqueConstraint(
            "execution_id", name="uq_local_ai_candidates_execution"
        ),
        sa.UniqueConstraint(
            "daily_plan_id", "id", name="uq_local_ai_candidates_plan_id",
        ),
        sa.UniqueConstraint(
            "profile_id", "source_kind", "source_id", "id",
            name="uq_local_ai_candidates_source_id",
        ),
    )
    bind = op.get_bind()
    bind.exec_driver_sql(
        "INSERT INTO local_ai_candidates_new ("
        "id, profile_id, execution_id, task_id, source_kind, source_id, "
        "observation_id, daily_plan_id, input_id, task_type, contract_version, "
        "schema_version, raw_candidate_json, candidate_hash, created_at) "
        "SELECT c.id, e.profile_id, c.execution_id, c.task_id, e.source_kind, "
        "e.source_id, NULL, c.daily_plan_id, c.input_id, c.task_type, "
        "c.contract_version, c.schema_version, c.raw_candidate_json, "
        "c.candidate_hash, c.created_at "
        "FROM local_ai_candidates c JOIN local_ai_executions e "
        "ON e.id = c.execution_id"
    )
    before = bind.exec_driver_sql("SELECT count(*) FROM local_ai_candidates").scalar()
    after = bind.exec_driver_sql("SELECT count(*) FROM local_ai_candidates_new").scalar()
    if before != after:
        _fail("candidate copy row-count mismatch")
    op.drop_table("local_ai_candidates")
    op.rename_table("local_ai_candidates_new", "local_ai_candidates")
    op.create_index(
        "ix_local_ai_candidates_plan_created",
        "local_ai_candidates", ["daily_plan_id", "created_at", "id"],
    )
    op.create_index(
        "ix_local_ai_candidates_source_created",
        "local_ai_candidates",
        ["profile_id", "source_kind", "source_id", "created_at"],
    )


def _rebuild_prompt_bundles() -> None:
    op.create_table(
        "local_prompt_bundles_new",
        sa.Column("task_type", sa.String(40), nullable=False),
        sa.Column("contract_version", sa.Integer(), nullable=False),
        sa.Column("default_revision", sa.Integer(), nullable=False),
        sa.Column("input_schema_json", sa.JSON(), nullable=False),
        sa.Column("output_schema_json", sa.JSON(), nullable=False),
        sa.Column("guidance_defaults_json", sa.JSON(), nullable=False),
        sa.Column("bundle_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "task_type IN ('daily_lesson_split', 'daily_process_adapt', "
            "'daily_other_activities', 'game_observation_generate', "
            "'game_observation_rewrite')",
            name="ck_local_prompt_bundles_task_type",
        ),
        sa.CheckConstraint(
            "typeof(contract_version) = 'integer' AND contract_version >= 1",
            name="ck_local_prompt_bundles_contract_version",
        ),
        sa.CheckConstraint(
            "typeof(default_revision) = 'integer' AND default_revision >= 1",
            name="ck_local_prompt_bundles_default_revision",
        ),
        sa.PrimaryKeyConstraint(
            "task_type", "contract_version", "default_revision",
            name="pk_local_prompt_bundles",
        ),
    )
    bind = op.get_bind()
    bind.exec_driver_sql(
        "INSERT INTO local_prompt_bundles_new ("
        "task_type, contract_version, default_revision, input_schema_json, "
        "output_schema_json, guidance_defaults_json, bundle_hash, created_at) "
        "SELECT task_type, contract_version, default_revision, input_schema_json, "
        "output_schema_json, guidance_defaults_json, bundle_hash, created_at "
        "FROM local_prompt_bundles"
    )
    before = bind.exec_driver_sql("SELECT count(*) FROM local_prompt_bundles").scalar()
    after = bind.exec_driver_sql(
        "SELECT count(*) FROM local_prompt_bundles_new"
    ).scalar()
    if before != after:
        _fail("prompt bundle copy row-count mismatch")
    op.drop_table("local_prompt_bundles")
    op.rename_table("local_prompt_bundles_new", "local_prompt_bundles")


def _create_observation_ai_links() -> None:
    op.create_table(
        "local_observation_ai_provenance",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("profile_id", sa.String(32), nullable=False),
        sa.Column("source_kind", sa.String(20), nullable=False),
        sa.Column("source_id", sa.String(32), nullable=False),
        sa.Column("observation_id", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("candidate_id", sa.String(32), nullable=False),
        sa.Column("adopted_targets_json", sa.JSON(), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("output_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "source_kind = 'game_observation' AND source_id = observation_id",
            name="ck_local_observation_ai_provenance_source",
        ),
        sa.CheckConstraint(
            "typeof(version) = 'integer' AND version >= 1",
            name="ck_local_observation_ai_provenance_version",
        ),
        sa.ForeignKeyConstraint(
            ["observation_id", "version"],
            ["local_observation_versions.observation_id",
             "local_observation_versions.version"],
            name="fk_local_observation_ai_provenance_version",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id", "source_kind", "source_id", "candidate_id"],
            ["local_ai_candidates.profile_id", "local_ai_candidates.source_kind",
             "local_ai_candidates.source_id", "local_ai_candidates.id"],
            name="fk_local_observation_ai_provenance_candidate",
        ),
        sa.PrimaryKeyConstraint(
            "id", name="pk_local_observation_ai_provenance"
        ),
        sa.UniqueConstraint(
            "observation_id", "version", "candidate_id",
            name="uq_local_observation_ai_provenance_version_candidate",
        ),
    )
    op.create_table(
        "local_observation_ai_input_photos",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("profile_id", sa.String(32), nullable=False),
        sa.Column("source_kind", sa.String(20), nullable=False),
        sa.Column("source_id", sa.String(32), nullable=False),
        sa.Column("observation_id", sa.String(32), nullable=True),
        sa.Column("input_id", sa.String(32), nullable=False),
        sa.Column("asset_id", sa.String(32), nullable=False),
        sa.Column("derivative_id", sa.String(32), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("original_hash", sa.String(64), nullable=False),
        sa.Column("work_hash", sa.String(64), nullable=False),
        sa.CheckConstraint(
            "source_kind = 'game_observation' "
            "AND observation_id IS NOT NULL AND source_id = observation_id",
            name="ck_local_observation_ai_input_photos_source",
        ),
        sa.CheckConstraint(
            "typeof(sort_order) = 'integer' AND sort_order >= 0",
            name="ck_local_observation_ai_input_photos_order",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id", "source_kind", "source_id", "input_id"],
            ["local_ai_inputs.profile_id", "local_ai_inputs.source_kind",
             "local_ai_inputs.source_id", "local_ai_inputs.id"],
            name="fk_local_observation_ai_input_photos_input",
        ),
        sa.ForeignKeyConstraint(
            ["observation_id", "asset_id"],
            ["local_observation_assets.observation_id",
             "local_observation_assets.id"],
            name="fk_local_observation_ai_input_photos_asset",
        ),
        sa.ForeignKeyConstraint(
            ["observation_id", "asset_id", "derivative_id"],
            ["local_observation_asset_derivatives.observation_id",
             "local_observation_asset_derivatives.asset_id",
             "local_observation_asset_derivatives.id"],
            name="fk_local_observation_ai_input_photos_derivative",
        ),
        sa.PrimaryKeyConstraint(
            "id", name="pk_local_observation_ai_input_photos"
        ),
        sa.UniqueConstraint(
            "input_id", "sort_order",
            name="uq_local_observation_ai_input_photos_order",
        ),
        sa.UniqueConstraint(
            "input_id", "asset_id",
            name="uq_local_observation_ai_input_photos_asset",
        ),
    )


def upgrade() -> None:
    _preflight()
    _create_observation_tables()
    _rebuild_ai_inputs()
    _rebuild_ai_tasks()
    _rebuild_ai_executions()
    _rebuild_ai_candidates()
    _rebuild_prompt_bundles()
    _create_observation_ai_links()


def downgrade() -> None:
    raise RuntimeError(
        "0006 never drops observation or source-chain tables: downgrade is "
        "not supported"
    )
