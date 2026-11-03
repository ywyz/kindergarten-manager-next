"""Desktop weekly-plan AI tables, task branches and adoption ledger.

Revision ID: 20261102_0008_local_weekly_ai
Revises: 20261101_0007_local_weekly
Create Date: 2026-11-02

This revision is intentionally a DDL/CHECK rebuild only.  It never rewrites
old weekly JSON/hashes, never inserts prompt bundle or personal-prompt rows
(the runtime sync does that after the D1 digest guard has committed), and
never changes old daily/observation values.  All rebuilt AI/weekly-content
tables copy only the previously existing columns; the new weekly reference
columns stay NULL for old rows.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261102_0008_local_weekly_ai"
down_revision: Union[str, None] = "20261101_0007_local_weekly"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


WEEKLY_TASKS = (
    "'weekly_games_select', 'weekly_key_week_focus', "
    "'weekly_environment_setup', 'weekly_habit_culture', "
    "'weekly_home_cooperation', 'weekly_materials_generate'"
)
ALL_TASKS = (
    "'daily_lesson_split', 'daily_process_adapt', 'daily_other_activities', "
    "'game_observation_generate', 'game_observation_rewrite', " + WEEKLY_TASKS
)


def _count(bind, table: str) -> int:
    return int(bind.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar())


def _assert_count(bind, before: int, after: int, label: str) -> None:
    if before != after:
        raise RuntimeError(f"{label} copy row-count mismatch")


def _rebuild_ai_inputs() -> None:
    op.execute(
        f"""
        CREATE TABLE local_ai_inputs_new (
            id VARCHAR(32) NOT NULL,
            profile_id VARCHAR(32) NOT NULL,
            source_kind VARCHAR(20) NOT NULL,
            source_id VARCHAR(32) NOT NULL,
            observation_id VARCHAR(32),
            source_revision INTEGER,
            daily_plan_id VARCHAR(32),
            content_id VARCHAR(32),
            content_version INTEGER,
            weekly_plan_id VARCHAR(32),
            weekly_draft_id VARCHAR(32),
            create_operation_id VARCHAR(32),
            task_type VARCHAR(40) NOT NULL,
            target_grade VARCHAR(20),
            input_schema_version INTEGER NOT NULL,
            payload_json JSON NOT NULL,
            dependencies_json JSON NOT NULL,
            dependency_hash VARCHAR(64) NOT NULL,
            target_hashes_json JSON NOT NULL,
            created_at DATETIME NOT NULL,
            CONSTRAINT pk_local_ai_inputs PRIMARY KEY (id),
            CONSTRAINT ck_local_ai_inputs_input_schema_version CHECK (
                typeof(input_schema_version) = 'integer' AND input_schema_version >= 1
            ),
            CONSTRAINT ck_local_ai_inputs_task_type CHECK (
                task_type IN ({ALL_TASKS})
            ),
            CONSTRAINT ck_local_ai_inputs_source_kind CHECK (
                source_kind IN ('daily_plan', 'game_observation', 'weekly_plan')
            ),
            CONSTRAINT ck_local_ai_inputs_source_match CHECK (
                (source_kind = 'daily_plan'
                 AND task_type IN ('daily_lesson_split', 'daily_process_adapt',
                                   'daily_other_activities')
                 AND daily_plan_id IS NOT NULL AND content_id IS NOT NULL
                 AND content_version IS NOT NULL AND target_grade IS NOT NULL
                 AND target_grade IN ('small', 'middle', 'large')
                 AND observation_id IS NULL AND source_id = daily_plan_id
                 AND source_revision IS NULL AND weekly_plan_id IS NULL
                 AND weekly_draft_id IS NULL AND create_operation_id IS NULL)
                OR
                (source_kind = 'game_observation'
                 AND task_type IN ('game_observation_generate',
                                   'game_observation_rewrite')
                 AND daily_plan_id IS NULL AND content_id IS NULL
                 AND content_version IS NULL AND target_grade IS NULL
                 AND observation_id IS NOT NULL AND source_id = observation_id
                 AND source_revision IS NOT NULL
                 AND typeof(source_revision) = 'integer' AND source_revision >= 1
                 AND weekly_plan_id IS NULL AND weekly_draft_id IS NULL
                 AND create_operation_id IS NULL)
                OR
                (source_kind = 'weekly_plan'
                 AND task_type IN ({WEEKLY_TASKS})
                 AND daily_plan_id IS NULL AND content_id IS NULL
                 AND content_version IS NULL AND target_grade IS NULL
                 AND observation_id IS NULL AND source_id = weekly_plan_id
                 AND weekly_plan_id IS NOT NULL AND weekly_draft_id IS NOT NULL
                 AND source_revision IS NOT NULL
                 AND typeof(source_revision) = 'integer' AND source_revision >= 1
                 AND create_operation_id IS NOT NULL)
            ),
            CONSTRAINT fk_local_ai_inputs_content_triple FOREIGN KEY
                (daily_plan_id, content_id, content_version)
                REFERENCES local_daily_plan_contents
                    (daily_plan_id, id, version),
            CONSTRAINT fk_local_ai_inputs_profile_id FOREIGN KEY (profile_id)
                REFERENCES local_profile (id),
            CONSTRAINT fk_local_ai_inputs_observation FOREIGN KEY
                (profile_id, observation_id)
                REFERENCES local_observation_records (creator_profile_id, id),
            CONSTRAINT fk_local_ai_inputs_weekly_plan FOREIGN KEY
                (profile_id, weekly_plan_id)
                REFERENCES local_weekly_plans (profile_id, id),
            CONSTRAINT fk_local_ai_inputs_weekly_draft FOREIGN KEY
                (weekly_plan_id, weekly_draft_id, source_revision)
                REFERENCES local_weekly_plan_contents (weekly_plan_id, id, version),
            CONSTRAINT fk_local_ai_inputs_create_operation FOREIGN KEY
                (profile_id, create_operation_id)
                REFERENCES local_ai_operations (profile_id, id),
            CONSTRAINT uq_local_ai_inputs_plan_id_task UNIQUE
                (daily_plan_id, id, task_type),
            CONSTRAINT uq_local_ai_inputs_source_task UNIQUE
                (profile_id, source_kind, source_id, id, task_type),
            CONSTRAINT uq_local_ai_inputs_source_id UNIQUE
                (profile_id, source_kind, source_id, id)
        )
        """
    )
    bind = op.get_bind()
    before = _count(bind, "local_ai_inputs")
    bind.exec_driver_sql(
        "INSERT INTO local_ai_inputs_new ("
        "id, profile_id, source_kind, source_id, observation_id, "
        "source_revision, daily_plan_id, content_id, content_version, "
        "weekly_plan_id, weekly_draft_id, create_operation_id, task_type, "
        "target_grade, input_schema_version, payload_json, dependencies_json, "
        "dependency_hash, target_hashes_json, created_at) "
        "SELECT id, profile_id, source_kind, source_id, observation_id, "
        "source_revision, daily_plan_id, content_id, content_version, "
        "NULL, NULL, NULL, task_type, target_grade, input_schema_version, "
        "payload_json, dependencies_json, dependency_hash, "
        "target_hashes_json, created_at FROM local_ai_inputs"
    )
    after = _count(bind, "local_ai_inputs_new")
    _assert_count(bind, before, after, "ai_inputs")
    op.drop_table("local_ai_inputs")
    op.rename_table("local_ai_inputs_new", "local_ai_inputs")
    op.create_index(
        "ix_local_ai_inputs_source_task",
        "local_ai_inputs",
        ["profile_id", "source_kind", "source_id", "task_type"],
    )


def _rebuild_ai_tasks() -> None:
    op.execute(
        f"""
        CREATE TABLE local_ai_tasks_new (
            id VARCHAR(32) NOT NULL,
            profile_id VARCHAR(32) NOT NULL,
            source_kind VARCHAR(20) NOT NULL,
            source_id VARCHAR(32) NOT NULL,
            observation_id VARCHAR(32),
            daily_plan_id VARCHAR(32),
            weekly_plan_id VARCHAR(32),
            task_type VARCHAR(40) NOT NULL,
            input_id VARCHAR(32) NOT NULL,
            status VARCHAR(20) NOT NULL,
            reason VARCHAR(200),
            current_execution_id VARCHAR(32),
            generation INTEGER NOT NULL,
            runtime_meta_json JSON NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            CONSTRAINT pk_local_ai_tasks PRIMARY KEY (id),
            CONSTRAINT ck_local_ai_tasks_generation CHECK (
                typeof(generation) = 'integer' AND generation >= 0
            ),
            CONSTRAINT ck_local_ai_tasks_status CHECK (
                status IN ('pending', 'claimed', 'dispatching', 'retry_wait',
                           'paused', 'succeeded', 'failed', 'outcome_unknown',
                           'cancelled')
            ),
            CONSTRAINT ck_local_ai_tasks_source_kind CHECK (
                source_kind IN ('daily_plan', 'game_observation', 'weekly_plan')
            ),
            CONSTRAINT ck_local_ai_tasks_source_match CHECK (
                (source_kind = 'daily_plan'
                 AND task_type IN ('daily_lesson_split', 'daily_process_adapt',
                                   'daily_other_activities')
                 AND daily_plan_id IS NOT NULL AND observation_id IS NULL
                 AND weekly_plan_id IS NULL AND source_id = daily_plan_id)
                OR
                (source_kind = 'game_observation'
                 AND task_type IN ('game_observation_generate',
                                   'game_observation_rewrite')
                 AND daily_plan_id IS NULL AND observation_id IS NOT NULL
                 AND weekly_plan_id IS NULL AND source_id = observation_id)
                OR
                (source_kind = 'weekly_plan'
                 AND task_type IN ({WEEKLY_TASKS})
                 AND daily_plan_id IS NULL AND observation_id IS NULL
                 AND weekly_plan_id IS NOT NULL AND source_id = weekly_plan_id)
            ),
            CONSTRAINT fk_local_ai_tasks_input FOREIGN KEY
                (daily_plan_id, input_id, task_type)
                REFERENCES local_ai_inputs (daily_plan_id, id, task_type),
            CONSTRAINT fk_local_ai_tasks_source_input FOREIGN KEY
                (profile_id, source_kind, source_id, input_id, task_type)
                REFERENCES local_ai_inputs
                    (profile_id, source_kind, source_id, id, task_type),
            CONSTRAINT fk_local_ai_tasks_profile_id FOREIGN KEY (profile_id)
                REFERENCES local_profile (id),
            CONSTRAINT fk_local_ai_tasks_weekly_plan FOREIGN KEY
                (profile_id, weekly_plan_id)
                REFERENCES local_weekly_plans (profile_id, id),
            CONSTRAINT fk_local_ai_tasks_current_execution FOREIGN KEY
                (id, current_execution_id)
                REFERENCES local_ai_executions (task_id, id)
                DEFERRABLE INITIALLY DEFERRED,
            CONSTRAINT uq_local_ai_tasks_plan_input UNIQUE
                (daily_plan_id, id, input_id, task_type),
            CONSTRAINT uq_local_ai_tasks_source_input UNIQUE
                (profile_id, source_kind, source_id, id, input_id, task_type)
        )
        """
    )
    bind = op.get_bind()
    before = _count(bind, "local_ai_tasks")
    bind.exec_driver_sql(
        "INSERT INTO local_ai_tasks_new ("
        "id, profile_id, source_kind, source_id, observation_id, daily_plan_id, "
        "weekly_plan_id, task_type, input_id, status, reason, "
        "current_execution_id, generation, runtime_meta_json, created_at, "
        "updated_at) "
        "SELECT id, profile_id, source_kind, source_id, observation_id, "
        "daily_plan_id, NULL, task_type, input_id, status, reason, "
        "current_execution_id, generation, runtime_meta_json, created_at, "
        "updated_at FROM local_ai_tasks"
    )
    after = _count(bind, "local_ai_tasks_new")
    _assert_count(bind, before, after, "ai_tasks")
    op.drop_table("local_ai_tasks")
    op.rename_table("local_ai_tasks_new", "local_ai_tasks")
    for name, cols in (
        ("ix_local_ai_tasks_status_created", ["status", "created_at", "id"]),
        ("ix_local_ai_tasks_plan_created", ["daily_plan_id", "created_at", "id"]),
        (
            "ix_local_ai_tasks_source_status",
            ["profile_id", "source_kind", "source_id", "status", "updated_at"],
        ),
    ):
        op.create_index(name, "local_ai_tasks", cols)
    op.create_index(
        "uq_local_ai_tasks_active_per_plan_type",
        "local_ai_tasks",
        ["daily_plan_id", "task_type"],
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
    op.create_index(
        "uq_local_ai_tasks_active_per_weekly_type",
        "local_ai_tasks",
        ["profile_id", "weekly_plan_id", "task_type"],
        unique=True,
        sqlite_where=sa.text(
            "source_kind = 'weekly_plan' AND status IN "
            "('pending', 'claimed', 'dispatching', 'retry_wait')"
        ),
    )


def _rebuild_ai_executions() -> None:
    op.execute(
        f"""
        CREATE TABLE local_ai_executions_new (
            id VARCHAR(32) NOT NULL,
            task_id VARCHAR(32) NOT NULL,
            source_kind VARCHAR(20) NOT NULL,
            source_id VARCHAR(32) NOT NULL,
            observation_id VARCHAR(32),
            daily_plan_id VARCHAR(32),
            weekly_plan_id VARCHAR(32),
            input_id VARCHAR(32) NOT NULL,
            task_type VARCHAR(40) NOT NULL,
            generation INTEGER NOT NULL,
            launch_id VARCHAR(36) NOT NULL,
            permit_id VARCHAR(36) NOT NULL,
            config_version INTEGER NOT NULL,
            profile_id VARCHAR(32) NOT NULL,
            personal_revision INTEGER NOT NULL,
            contract_version INTEGER NOT NULL,
            default_revision INTEGER NOT NULL,
            state VARCHAR(20) NOT NULL,
            runtime_meta_json JSON NOT NULL,
            started_at DATETIME NOT NULL,
            created_at DATETIME NOT NULL,
            ended_at DATETIME,
            CONSTRAINT pk_local_ai_executions PRIMARY KEY (id),
            CONSTRAINT ck_local_ai_executions_generation CHECK (
                typeof(generation) = 'integer' AND generation >= 1
            ),
            CONSTRAINT ck_local_ai_executions_config_version_check CHECK (
                typeof(config_version) = 'integer' AND config_version >= 1
            ),
            CONSTRAINT ck_local_ai_executions_personal_revision_check CHECK (
                typeof(personal_revision) = 'integer' AND personal_revision >= 1
            ),
            CONSTRAINT ck_local_ai_executions_contract_version_check CHECK (
                typeof(contract_version) = 'integer' AND contract_version >= 1
            ),
            CONSTRAINT ck_local_ai_executions_default_revision_check CHECK (
                typeof(default_revision) = 'integer' AND default_revision >= 1
            ),
            CONSTRAINT ck_local_ai_executions_state CHECK (
                state IN ('pending', 'claimed', 'dispatching', 'retry_wait',
                           'paused', 'succeeded', 'failed', 'outcome_unknown',
                           'cancelled')
            ),
            CONSTRAINT ck_local_ai_executions_source_kind CHECK (
                source_kind IN ('daily_plan', 'game_observation', 'weekly_plan')
            ),
            CONSTRAINT ck_local_ai_executions_source_match CHECK (
                (source_kind = 'daily_plan'
                 AND task_type IN ('daily_lesson_split', 'daily_process_adapt',
                                   'daily_other_activities')
                 AND daily_plan_id IS NOT NULL AND observation_id IS NULL
                 AND weekly_plan_id IS NULL AND source_id = daily_plan_id)
                OR
                (source_kind = 'game_observation'
                 AND task_type IN ('game_observation_generate',
                                   'game_observation_rewrite')
                 AND daily_plan_id IS NULL AND observation_id IS NOT NULL
                 AND weekly_plan_id IS NULL AND source_id = observation_id)
                OR
                (source_kind = 'weekly_plan'
                 AND task_type IN ({WEEKLY_TASKS})
                 AND daily_plan_id IS NULL AND observation_id IS NULL
                 AND weekly_plan_id IS NOT NULL AND source_id = weekly_plan_id)
            ),
            CONSTRAINT fk_local_ai_executions_task FOREIGN KEY
                (daily_plan_id, task_id, input_id, task_type)
                REFERENCES local_ai_tasks (daily_plan_id, id, input_id, task_type),
            CONSTRAINT fk_local_ai_executions_source_task FOREIGN KEY
                (profile_id, source_kind, source_id, task_id, input_id, task_type)
                REFERENCES local_ai_tasks
                    (profile_id, source_kind, source_id, id, input_id, task_type),
            CONSTRAINT fk_local_ai_executions_profile_id FOREIGN KEY (profile_id)
                REFERENCES local_profile (id),
            CONSTRAINT fk_local_ai_executions_weekly_plan FOREIGN KEY
                (profile_id, weekly_plan_id)
                REFERENCES local_weekly_plans (profile_id, id),
            CONSTRAINT fk_local_ai_executions_config_version FOREIGN KEY
                (profile_id, config_version)
                REFERENCES local_ai_config_versions (profile_id, version)
                DEFERRABLE INITIALLY DEFERRED,
            CONSTRAINT fk_local_ai_executions_personal_revision FOREIGN KEY
                (profile_id, task_type, personal_revision)
                REFERENCES local_personal_prompt_versions
                    (profile_id, task_type, revision)
                DEFERRABLE INITIALLY DEFERRED,
            CONSTRAINT fk_local_ai_executions_default_bundle FOREIGN KEY
                (task_type, contract_version, default_revision)
                REFERENCES local_prompt_bundles
                    (task_type, contract_version, default_revision)
                DEFERRABLE INITIALLY DEFERRED,
            CONSTRAINT uq_local_ai_executions_task_generation UNIQUE
                (task_id, generation),
            CONSTRAINT uq_local_ai_executions_task_id UNIQUE (task_id, id),
            CONSTRAINT uq_local_ai_executions_plan_task_input_id UNIQUE
                (daily_plan_id, task_id, input_id, task_type, id),
            CONSTRAINT uq_local_ai_executions_source_task_input_id UNIQUE
                (profile_id, source_kind, source_id, id, task_id, input_id,
                 task_type)
        )
        """
    )
    bind = op.get_bind()
    before = _count(bind, "local_ai_executions")
    bind.exec_driver_sql(
        "INSERT INTO local_ai_executions_new ("
        "id, task_id, source_kind, source_id, observation_id, daily_plan_id, "
        "weekly_plan_id, input_id, task_type, generation, launch_id, permit_id, "
        "config_version, profile_id, personal_revision, contract_version, "
        "default_revision, state, runtime_meta_json, started_at, created_at, "
        "ended_at) "
        "SELECT id, task_id, source_kind, source_id, observation_id, "
        "daily_plan_id, NULL, input_id, task_type, generation, launch_id, "
        "permit_id, config_version, profile_id, personal_revision, "
        "contract_version, default_revision, state, runtime_meta_json, "
        "started_at, created_at, ended_at FROM local_ai_executions"
    )
    after = _count(bind, "local_ai_executions_new")
    _assert_count(bind, before, after, "ai_executions")
    op.drop_table("local_ai_executions")
    op.rename_table("local_ai_executions_new", "local_ai_executions")
    op.create_index(
        "ix_local_ai_executions_source_task",
        "local_ai_executions",
        ["profile_id", "source_kind", "source_id", "task_id", "generation"],
    )


def _rebuild_ai_candidates() -> None:
    op.execute(
        f"""
        CREATE TABLE local_ai_candidates_new (
            id VARCHAR(32) NOT NULL,
            profile_id VARCHAR(32) NOT NULL,
            execution_id VARCHAR(32) NOT NULL,
            task_id VARCHAR(32) NOT NULL,
            source_kind VARCHAR(20) NOT NULL,
            source_id VARCHAR(32) NOT NULL,
            observation_id VARCHAR(32),
            daily_plan_id VARCHAR(32),
            weekly_plan_id VARCHAR(32),
            input_id VARCHAR(32) NOT NULL,
            task_type VARCHAR(40) NOT NULL,
            contract_version INTEGER NOT NULL,
            schema_version INTEGER NOT NULL,
            raw_candidate_json JSON NOT NULL,
            candidate_hash VARCHAR(64) NOT NULL,
            created_at DATETIME NOT NULL,
            CONSTRAINT pk_local_ai_candidates PRIMARY KEY (id),
            CONSTRAINT ck_local_ai_candidates_contract_version CHECK (
                typeof(contract_version) = 'integer' AND contract_version >= 1
            ),
            CONSTRAINT ck_local_ai_candidates_schema_version CHECK (
                typeof(schema_version) = 'integer' AND schema_version >= 1
            ),
            CONSTRAINT ck_local_ai_candidates_source_kind CHECK (
                source_kind IN ('daily_plan', 'game_observation', 'weekly_plan')
            ),
            CONSTRAINT ck_local_ai_candidates_source_match CHECK (
                (source_kind = 'daily_plan'
                 AND task_type IN ('daily_lesson_split', 'daily_process_adapt',
                                   'daily_other_activities')
                 AND daily_plan_id IS NOT NULL AND observation_id IS NULL
                 AND weekly_plan_id IS NULL AND source_id = daily_plan_id)
                OR
                (source_kind = 'game_observation'
                 AND task_type IN ('game_observation_generate',
                                   'game_observation_rewrite')
                 AND daily_plan_id IS NULL AND observation_id IS NOT NULL
                 AND weekly_plan_id IS NULL AND source_id = observation_id)
                OR
                (source_kind = 'weekly_plan'
                 AND task_type IN ({WEEKLY_TASKS})
                 AND daily_plan_id IS NULL AND observation_id IS NULL
                 AND weekly_plan_id IS NOT NULL AND source_id = weekly_plan_id)
            ),
            CONSTRAINT fk_local_ai_candidates_execution FOREIGN KEY
                (execution_id, task_id, daily_plan_id, input_id, task_type)
                REFERENCES local_ai_executions
                    (id, task_id, daily_plan_id, input_id, task_type),
            CONSTRAINT fk_local_ai_candidates_source_execution FOREIGN KEY
                (profile_id, source_kind, source_id, execution_id, task_id,
                 input_id, task_type)
                REFERENCES local_ai_executions
                    (profile_id, source_kind, source_id, id, task_id, input_id,
                     task_type),
            CONSTRAINT fk_local_ai_candidates_profile_id FOREIGN KEY (profile_id)
                REFERENCES local_profile (id),
            CONSTRAINT fk_local_ai_candidates_weekly_plan FOREIGN KEY
                (profile_id, weekly_plan_id)
                REFERENCES local_weekly_plans (profile_id, id),
            CONSTRAINT uq_local_ai_candidates_execution UNIQUE (execution_id),
            CONSTRAINT uq_local_ai_candidates_plan_id UNIQUE (daily_plan_id, id),
            CONSTRAINT uq_local_ai_candidates_source_id UNIQUE
                (profile_id, source_kind, source_id, id)
        )
        """
    )
    bind = op.get_bind()
    before = _count(bind, "local_ai_candidates")
    bind.exec_driver_sql(
        "INSERT INTO local_ai_candidates_new ("
        "id, profile_id, execution_id, task_id, source_kind, source_id, "
        "observation_id, daily_plan_id, weekly_plan_id, input_id, task_type, "
        "contract_version, schema_version, raw_candidate_json, candidate_hash, "
        "created_at) "
        "SELECT id, profile_id, execution_id, task_id, source_kind, source_id, "
        "observation_id, daily_plan_id, NULL, input_id, task_type, "
        "contract_version, schema_version, raw_candidate_json, candidate_hash, "
        "created_at FROM local_ai_candidates"
    )
    after = _count(bind, "local_ai_candidates_new")
    _assert_count(bind, before, after, "ai_candidates")
    op.drop_table("local_ai_candidates")
    op.rename_table("local_ai_candidates_new", "local_ai_candidates")
    op.create_index(
        "ix_local_ai_candidates_plan_created",
        "local_ai_candidates",
        ["daily_plan_id", "created_at", "id"],
    )
    op.create_index(
        "ix_local_ai_candidates_source_created",
        "local_ai_candidates",
        ["profile_id", "source_kind", "source_id", "created_at"],
    )


def _rebuild_prompt_bundles() -> None:
    op.execute(
        f"""
        CREATE TABLE local_prompt_bundles_new (
            task_type VARCHAR(40) NOT NULL,
            contract_version INTEGER NOT NULL,
            default_revision INTEGER NOT NULL,
            input_schema_json JSON NOT NULL,
            output_schema_json JSON NOT NULL,
            guidance_defaults_json JSON NOT NULL,
            bundle_hash VARCHAR(64) NOT NULL,
            created_at DATETIME NOT NULL,
            CONSTRAINT pk_local_prompt_bundles PRIMARY KEY
                (task_type, contract_version, default_revision),
            CONSTRAINT ck_local_prompt_bundles_task_type CHECK (
                task_type IN ({ALL_TASKS})
            ),
            CONSTRAINT ck_local_prompt_bundles_contract_version CHECK (
                typeof(contract_version) = 'integer' AND contract_version >= 1
            ),
            CONSTRAINT ck_local_prompt_bundles_default_revision CHECK (
                typeof(default_revision) = 'integer' AND default_revision >= 1
            )
        )
        """
    )
    bind = op.get_bind()
    before = _count(bind, "local_prompt_bundles")
    bind.exec_driver_sql(
        "INSERT INTO local_prompt_bundles_new ("
        "task_type, contract_version, default_revision, input_schema_json, "
        "output_schema_json, guidance_defaults_json, bundle_hash, created_at) "
        "SELECT task_type, contract_version, default_revision, input_schema_json, "
        "output_schema_json, guidance_defaults_json, bundle_hash, created_at "
        "FROM local_prompt_bundles"
    )
    after = _count(bind, "local_prompt_bundles_new")
    _assert_count(bind, before, after, "prompt_bundles")
    op.drop_table("local_prompt_bundles")
    op.rename_table("local_prompt_bundles_new", "local_prompt_bundles")


def _rebuild_weekly_contents() -> None:
    op.execute(
        """
        CREATE TABLE local_weekly_plan_contents_new (
            id VARCHAR(32) NOT NULL,
            weekly_plan_id VARCHAR(32) NOT NULL,
            version INTEGER NOT NULL,
            schema_version INTEGER NOT NULL,
            content_json JSON NOT NULL,
            content_hash VARCHAR(64) NOT NULL,
            editor_profile_id VARCHAR(32) NOT NULL,
            created_at DATETIME NOT NULL,
            CONSTRAINT pk_local_weekly_plan_contents PRIMARY KEY (id),
            CONSTRAINT ck_local_weekly_plan_contents_version CHECK (
                typeof(version) = 'integer' AND version >= 1
            ),
            CONSTRAINT ck_local_weekly_plan_contents_schema_version CHECK (
                typeof(schema_version) = 'integer' AND schema_version IN (1, 2)
            ),
            CONSTRAINT ck_local_weekly_plan_contents_hash CHECK (
                length(content_hash) = 64
            ),
            CONSTRAINT fk_local_weekly_plan_contents_plan FOREIGN KEY
                (weekly_plan_id) REFERENCES local_weekly_plans (id),
            CONSTRAINT fk_local_weekly_plan_contents_editor FOREIGN KEY
                (editor_profile_id) REFERENCES local_profile (id),
            CONSTRAINT uq_local_weekly_plan_contents_plan_version UNIQUE
                (weekly_plan_id, version),
            CONSTRAINT uq_local_weekly_plan_contents_plan_id_version UNIQUE
                (weekly_plan_id, id, version)
        )
        """
    )
    bind = op.get_bind()
    before = _count(bind, "local_weekly_plan_contents")
    bind.exec_driver_sql(
        "INSERT INTO local_weekly_plan_contents_new ("
        "id, weekly_plan_id, version, schema_version, content_json, "
        "content_hash, editor_profile_id, created_at) "
        "SELECT id, weekly_plan_id, version, schema_version, content_json, "
        "content_hash, editor_profile_id, created_at "
        "FROM local_weekly_plan_contents"
    )
    after = _count(bind, "local_weekly_plan_contents_new")
    _assert_count(bind, before, after, "weekly_contents")
    op.drop_table("local_weekly_plan_contents")
    op.rename_table("local_weekly_plan_contents_new", "local_weekly_plan_contents")


def _create_adoption_table() -> None:
    op.execute(
        """
        CREATE TABLE local_weekly_plan_ai_adoption (
            id VARCHAR(32) NOT NULL,
            profile_id VARCHAR(32) NOT NULL,
            source_kind VARCHAR(20) NOT NULL,
            weekly_plan_id VARCHAR(32) NOT NULL,
            draft_id VARCHAR(32) NOT NULL,
            draft_version INTEGER NOT NULL,
            candidate_id VARCHAR(32) NOT NULL,
            target_key VARCHAR(32) NOT NULL,
            before_hash VARCHAR(64) NOT NULL,
            after_hash VARCHAR(64) NOT NULL,
            operation_id VARCHAR(32) NOT NULL,
            created_at DATETIME NOT NULL,
            CONSTRAINT pk_local_weekly_plan_ai_adoption PRIMARY KEY (id),
            CONSTRAINT ck_local_weekly_plan_ai_adoption_source CHECK (
                source_kind = 'weekly_plan'
            ),
            CONSTRAINT ck_local_weekly_plan_ai_adoption_target CHECK (
                target_key IN ('games', 'key_week_focus', 'environment_setup',
                               'habit_culture', 'home_cooperation', 'materials')
            ),
            CONSTRAINT ck_local_weekly_plan_ai_adoption_version CHECK (
                typeof(draft_version) = 'integer' AND draft_version >= 1
            ),
            CONSTRAINT ck_local_weekly_plan_ai_adoption_hash CHECK (
                length(before_hash) = 64 AND length(after_hash) = 64
            ),
            CONSTRAINT fk_local_weekly_plan_ai_adoption_plan FOREIGN KEY
                (profile_id, weekly_plan_id)
                REFERENCES local_weekly_plans (profile_id, id),
            CONSTRAINT fk_local_weekly_plan_ai_adoption_draft FOREIGN KEY
                (weekly_plan_id, draft_id, draft_version)
                REFERENCES local_weekly_plan_contents (weekly_plan_id, id, version),
            CONSTRAINT fk_local_weekly_plan_ai_adoption_candidate FOREIGN KEY
                (profile_id, source_kind, weekly_plan_id, candidate_id)
                REFERENCES local_ai_candidates
                    (profile_id, source_kind, source_id, id),
            CONSTRAINT fk_local_weekly_plan_ai_adoption_operation FOREIGN KEY
                (profile_id, operation_id)
                REFERENCES local_ai_operations (profile_id, id),
            CONSTRAINT uq_local_weekly_plan_ai_adoption_draft_target UNIQUE
                (draft_id, target_key)
        )
        """
    )


def upgrade() -> None:
    bind = op.get_bind()
    # The immediate create_operation_id FK needs this parent key before the AI
    # input table is rebuilt.  The index is additive and does not change rows.
    op.create_index(
        "uq_local_ai_operations_profile_id",
        "local_ai_operations",
        ["profile_id", "id"],
        unique=True,
    )
    _rebuild_weekly_contents()
    _rebuild_ai_inputs()
    _rebuild_ai_tasks()
    _rebuild_ai_executions()
    _rebuild_ai_candidates()
    _rebuild_prompt_bundles()
    _create_adoption_table()
    # old tables are rebuilt with foreign_keys=OFF in env.py; the caller runs
    # PRAGMA foreign_key_check before COMMIT.


def downgrade() -> None:
    raise RuntimeError(
        "local schema is forward-only; restore a verified backup instead"
    )
