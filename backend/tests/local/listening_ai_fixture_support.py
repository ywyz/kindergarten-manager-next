"""Synthetic real-0009 weekly AI fixture for the 0010 migration test.

The database is built by running the actual local Alembic chain to
``20261107_0009_local_listening`` and then inserting rows that are valid
under the 0009 constraints.  No external archive, private path or recorded
database is read, and the version row is never edited to fake an older
schema.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from alembic import command

from app.local.migrate import alembic_config

REVISION_0009 = "20261107_0009_local_listening"

_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64


def _now() -> str:
    return datetime(2026, 11, 7, 9, 0, 0).isoformat(sep=" ")


def create_0009_weekly_ai_fixture(db_path: Path) -> dict[str, str]:
    """Create a genuine 0009 database with one weekly AI chain/adoption row."""

    db_path = Path(db_path)
    if db_path.exists():
        raise FileExistsError(f"fixture database already exists: {db_path}")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(db_path), REVISION_0009)

    ids = {
        "profile": "fixturep" + "0" * 24,
        "class": "fixturec" + "0" * 24,
        "term": "fixturet" + "0" * 24,
        "revision": "fixturer" + "0" * 24,
        "plan": "fixturew" + "0" * 24,
        "draft": "fixtured" + "0" * 24,
        "operation": "fixtureo" + "0" * 24,
        "input": "fixturei" + "0" * 24,
        "task": "fixturek" + "0" * 24,
        "execution": "fixturee" + "0" * 24,
        "candidate": "fixturea" + "0" * 24,
        "adoption": "fixturel" + "0" * 24,
    }
    now = _now()
    connection = sqlite3.connect(str(db_path))
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        connection.execute(
            "INSERT INTO local_profile "
            "(id, singleton, display_name, created_at, updated_at) "
            "VALUES (?, 1, ?, ?, ?)",
            (ids["profile"], "合成教师", now, now),
        )
        connection.execute(
            "INSERT INTO local_classes "
            "(id, name, grade, created_at, updated_at, header_teacher_names, "
            "caregiver_name) VALUES (?, ?, 'middle', ?, ?, '[]', NULL)",
            (ids["class"], "合成中一班", now, now),
        )
        # The term and its current calendar revision reference each other;
        # the term-side foreign key is deferrable, so the pair commits together.
        connection.execute(
            "INSERT INTO local_terms "
            "(id, name, start_date, end_date, current_calendar_revision_id, "
            "created_at, updated_at) VALUES (?, ?, '2026-09-01', '2027-01-31', "
            "?, ?, ?)",
            (ids["term"], "2026 年秋季学期", ids["revision"], now, now),
        )
        connection.execute(
            "INSERT INTO local_calendar_revisions "
            "(id, term_id, revision_no, library_version, created_by, created_at) "
            "VALUES (?, ?, 1, 'synthetic-calendar-1.0', ?, ?)",
            (ids["revision"], ids["term"], ids["profile"], now),
        )
        # The plan's current-draft foreign key is deferrable.
        connection.execute(
            "INSERT INTO local_weekly_plans "
            "(id, profile_id, class_id, term_id, week_anchor_date, "
            "week_number_snapshot, term_start_date, term_end_date, "
            "calendar_revision_id, header_json, header_hash, current_draft_id, "
            "current_draft_version, current_confirmed_id, "
            "current_confirmed_version, created_at, updated_at) VALUES "
            "(?, ?, ?, ?, '2026-11-02', 10, '2026-09-01', '2027-01-31', ?, "
            "'{}', ?, ?, 1, NULL, NULL, ?, ?)",
            (
                ids["plan"],
                ids["profile"],
                ids["class"],
                ids["term"],
                ids["revision"],
                _HASH_A,
                ids["draft"],
                now,
                now,
            ),
        )
        connection.execute(
            "INSERT INTO local_weekly_plan_contents "
            "(id, weekly_plan_id, version, schema_version, content_json, "
            "content_hash, editor_profile_id, created_at) "
            "VALUES (?, ?, 1, 2, ?, ?, ?, ?)",
            (
                ids["draft"],
                ids["plan"],
                '{"games":"合成周计划内容"}',
                _HASH_B,
                ids["profile"],
                now,
            ),
        )
        connection.execute(
            "INSERT INTO local_ai_operations "
            "(id, profile_id, request_id, operation_kind, request_fingerprint, "
            "fingerprint_kind, fingerprint_key_id, result_json, created_at) "
            "VALUES (?, ?, ?, 'weekly_ai_create', ?, 'sha256', NULL, ?, ?)",
            (
                ids["operation"],
                ids["profile"],
                "synthetic-weekly-create",
                _HASH_C,
                '{"task_id":"' + ids["task"] + '"}',
                now,
            ),
        )
        connection.execute(
            "INSERT INTO local_ai_config_versions "
            "(profile_id, version, protocol_id, base_url, model, credential_id, "
            "created_at) VALUES (?, 1, 'chat_completions_v1', NULL, NULL, NULL, ?)",
            (ids["profile"], now),
        )
        connection.execute(
            "INSERT INTO local_prompt_bundles "
            "(task_type, contract_version, default_revision, input_schema_json, "
            "output_schema_json, guidance_defaults_json, bundle_hash, created_at) "
            "VALUES ('weekly_games_select', 1, 1, '{}', '{}', '{}', ?, ?)",
            (_HASH_A, now),
        )
        connection.execute(
            "INSERT INTO local_personal_prompt_versions "
            "(profile_id, task_type, revision, contract_version, "
            "based_default_revision, guidance_json, orphaned_guidance_json, "
            "action, rejected_default_revision, created_at) "
            "VALUES (?, 'weekly_games_select', 1, 1, 1, '{}', NULL, 'initial', "
            "NULL, ?)",
            (ids["profile"], now),
        )
        connection.execute(
            "INSERT INTO local_ai_inputs "
            "(id, profile_id, source_kind, source_id, observation_id, "
            "source_revision, daily_plan_id, content_id, content_version, "
            "weekly_plan_id, weekly_draft_id, create_operation_id, task_type, "
            "target_grade, input_schema_version, payload_json, "
            "dependencies_json, dependency_hash, target_hashes_json, created_at) "
            "VALUES (?, ?, 'weekly_plan', ?, NULL, 1, NULL, NULL, NULL, ?, ?, ?, "
            "'weekly_games_select', NULL, 1, ?, '{}', ?, '{}', ?)",
            (
                ids["input"],
                ids["profile"],
                ids["plan"],
                ids["plan"],
                ids["draft"],
                ids["operation"],
                '{"week":"2026-11-02"}',
                _HASH_C,
                now,
            ),
        )
        connection.execute(
            "INSERT INTO local_ai_tasks "
            "(id, profile_id, source_kind, source_id, observation_id, "
            "daily_plan_id, weekly_plan_id, task_type, input_id, status, reason, "
            "current_execution_id, generation, runtime_meta_json, created_at, "
            "updated_at) VALUES (?, ?, 'weekly_plan', ?, NULL, NULL, ?, "
            "'weekly_games_select', ?, 'succeeded', NULL, ?, 1, '{}', ?, ?)",
            (
                ids["task"],
                ids["profile"],
                ids["plan"],
                ids["plan"],
                ids["input"],
                ids["execution"],
                now,
                now,
            ),
        )
        connection.execute(
            "INSERT INTO local_ai_executions "
            "(id, task_id, source_kind, source_id, observation_id, "
            "daily_plan_id, weekly_plan_id, input_id, task_type, generation, "
            "launch_id, permit_id, config_version, profile_id, "
            "personal_revision, contract_version, default_revision, state, "
            "runtime_meta_json, started_at, created_at, ended_at) VALUES "
            "(?, ?, 'weekly_plan', ?, NULL, NULL, ?, ?, 'weekly_games_select', "
            "1, 'synthetic-launch-000000000000000000', "
            "'synthetic-permit-000000000000000000', 1, ?, 1, 1, 1, "
            "'succeeded', '{}', ?, ?, ?)",
            (
                ids["execution"],
                ids["task"],
                ids["plan"],
                ids["plan"],
                ids["input"],
                ids["profile"],
                now,
                now,
                now,
            ),
        )
        connection.execute(
            "INSERT INTO local_ai_candidates "
            "(id, profile_id, execution_id, task_id, source_kind, source_id, "
            "observation_id, daily_plan_id, weekly_plan_id, input_id, task_type, "
            "contract_version, schema_version, raw_candidate_json, "
            "candidate_hash, created_at) VALUES (?, ?, ?, ?, 'weekly_plan', ?, "
            "NULL, NULL, ?, ?, 'weekly_games_select', 1, 1, ?, ?, ?)",
            (
                ids["candidate"],
                ids["profile"],
                ids["execution"],
                ids["task"],
                ids["plan"],
                ids["plan"],
                ids["input"],
                '{"games":["合成游戏"]}',
                _HASH_B,
                now,
            ),
        )
        connection.execute(
            "INSERT INTO local_weekly_plan_ai_adoption "
            "(id, profile_id, source_kind, weekly_plan_id, draft_id, "
            "draft_version, candidate_id, target_key, before_hash, after_hash, "
            "operation_id, created_at) VALUES (?, ?, 'weekly_plan', ?, ?, 1, ?, "
            "'games', ?, ?, ?, ?)",
            (
                ids["adoption"],
                ids["profile"],
                ids["plan"],
                ids["draft"],
                ids["candidate"],
                _HASH_A,
                _HASH_C,
                ids["operation"],
                now,
            ),
        )
        connection.commit()
    finally:
        connection.close()
    return ids
