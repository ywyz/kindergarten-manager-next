"""V1 — I4 migration chain and schema on the isolated MySQL 8.4 / InnoDB DB.

The suite never runs migrations itself: the authorized I4 run applies
``alembic upgrade head`` first (empty library, and an I3 library carrying
I1/I2/I3 rows). These tests verify the resulting structure and that the I3
``weekly_plan_sync_states`` contract is untouched by the I4 revision.
"""

from __future__ import annotations

import os

from sqlalchemy import text

from tests.integration.i4_support import I4IntegrationTestCase

_HERE = os.path.dirname(__file__)
_ALEMBIC_INI = os.path.abspath(os.path.join(_HERE, "..", "..", "alembic.ini"))

I4_HEAD = "20260924_i4_weekly_plans"

EXPECTED_SYNC_COLUMNS = [
    ("id", "varchar(32)", "NO"),
    ("class_id", "varchar(32)", "NO"),
    ("term_id", "varchar(32)", "NO"),
    ("week_number", "int", "NO"),
    ("status", "varchar(20)", "NO"),
    ("deterministic_themes", "json", "NO"),
    ("game_source_manifest", "json", "NO"),
    ("current_week_source_manifest", "json", "NO"),
    ("last_trigger_daily_plan_id", "varchar(32)", "YES"),
    ("last_trigger_content_version", "int", "YES"),
    ("last_trigger_event", "varchar(20)", "YES"),
    ("created_at", "datetime", "NO"),
    ("updated_at", "datetime", "NO"),
]


class MigrationChainTests(I4IntegrationTestCase):
    def test_mysql_84_and_innodb_default(self):
        version = self.scalar("SELECT VERSION()")
        self.assertTrue(version.startswith("8.4"), version)
        engine = self.scalar("SELECT @@GLOBAL.default_storage_engine")
        self.assertEqual(str(engine).lower(), "innodb")

    def test_three_i4_tables_exist_innodb(self):
        rows = self.rows(
            "SELECT table_name, engine FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND table_name IN "
            "('weekly_plans', 'weekly_plan_contents', "
            "'weekly_plan_confirmed_contents')"
        )
        found = {name: str(engine).lower() for name, engine in rows}
        self.assertEqual(
            found,
            {
                "weekly_plans": "innodb",
                "weekly_plan_contents": "innodb",
                "weekly_plan_confirmed_contents": "innodb",
            },
        )

    def test_composite_pointer_foreign_keys(self):
        rows = self.rows(
            "SELECT constraint_name, column_name, referenced_table_name "
            "FROM information_schema.key_column_usage "
            "WHERE table_schema = DATABASE() AND constraint_name IN "
            "('fk_weekly_plans_current_draft_content', "
            "'fk_weekly_plans_current_confirmed_content') "
            "ORDER BY constraint_name, ordinal_position"
        )
        draft = [(col, ref) for name, col, ref in rows
                 if name == "fk_weekly_plans_current_draft_content"]
        confirmed = [(col, ref) for name, col, ref in rows
                     if name == "fk_weekly_plans_current_confirmed_content"]
        self.assertEqual(
            draft,
            [
                ("id", "weekly_plan_contents"),
                ("current_draft_content_id", "weekly_plan_contents"),
                ("current_draft_version", "weekly_plan_contents"),
            ],
        )
        self.assertEqual(
            confirmed,
            [
                ("id", "weekly_plan_confirmed_contents"),
                (
                    "current_confirmed_content_id",
                    "weekly_plan_confirmed_contents",
                ),
                (
                    "current_confirmed_content_version",
                    "weekly_plan_confirmed_contents",
                ),
            ],
        )

    def test_effective_week_unique_key(self):
        rows = self.rows(
            "SELECT column_name FROM information_schema.key_column_usage "
            "WHERE table_schema = DATABASE() AND constraint_name = "
            "'uq_weekly_plans_class_term_effective_week' "
            "ORDER BY ordinal_position"
        )
        self.assertEqual(
            [col for (col,) in rows],
            ["class_id", "term_id", "effective_week"],
        )

    def test_operation_records_check_includes_weekly_plan(self):
        clause = self.scalar(
            "SELECT check_clause FROM information_schema.check_constraints "
            "WHERE constraint_schema = DATABASE() AND constraint_name = "
            "'ck_operation_record_target_type'"
        )
        self.assertIsNotNone(clause)
        self.assertIn("weekly_plan", clause)
        # Existing I1/I2/I3 values must survive.
        for legacy in (
            "account",
            "class",
            "school",
            "term",
            "calendar",
            "daily_plan",
        ):
            self.assertIn(legacy, clause)

    def test_alembic_current_equals_single_head(self):
        current = self.scalar("SELECT version_num FROM alembic_version")
        self.assertEqual(current, I4_HEAD)

        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config(_ALEMBIC_INI)
        script = ScriptDirectory.from_config(cfg)
        heads = set(script.get_heads())
        self.assertEqual(heads, {I4_HEAD})
        self.assertEqual(heads, {current})

    def test_weekly_plan_sync_states_schema_untouched(self):
        rows = self.rows(
            "SELECT column_name, column_type, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = "
            "'weekly_plan_sync_states' ORDER BY ordinal_position"
        )
        self.assertEqual(
            [(name, ctype, nullable) for name, ctype, nullable in rows],
            EXPECTED_SYNC_COLUMNS,
        )

        constraints = {
            name
            for (name,) in self.rows(
                "SELECT constraint_name FROM information_schema.table_constraints "
                "WHERE table_schema = DATABASE() AND table_name = "
                "'weekly_plan_sync_states'"
            )
        }
        self.assertIn("uq_weekly_plan_sync_states_class_term_week", constraints)
        self.assertIn("ck_weekly_plan_sync_states_status", constraints)
        self.assertIn(
            "ck_weekly_plan_sync_states_last_trigger_event", constraints
        )

        status_clause = self.scalar(
            "SELECT check_clause FROM information_schema.check_constraints "
            "WHERE constraint_schema = DATABASE() AND constraint_name = "
            "'ck_weekly_plan_sync_states_status'"
        )
        self.assertIn("pending_projection", status_clause)

    def test_pointer_columns_and_check_constraints(self):
        rows = self.rows(
            "SELECT constraint_name FROM information_schema.check_constraints "
            "WHERE constraint_schema = DATABASE() AND constraint_name IN "
            "('ck_weekly_plans_week_number', "
            "'ck_weekly_plans_current_draft_version', "
            "'ck_weekly_plans_current_confirmed_content_version', "
            "'ck_weekly_plan_contents_version', "
            "'ck_weekly_plan_contents_editor_role', "
            "'ck_weekly_plan_confirmed_contents_version')"
        )
        self.assertEqual(
            {name for (name,) in rows},
            {
                "ck_weekly_plans_week_number",
                "ck_weekly_plans_current_draft_version",
                "ck_weekly_plans_current_confirmed_content_version",
                "ck_weekly_plan_contents_version",
                "ck_weekly_plan_contents_editor_role",
                "ck_weekly_plan_confirmed_contents_version",
            },
        )

    def test_generated_effective_week_column_exists(self):
        # MySQL 8.4 exposes generated columns via a non-empty
        # GENERATION_EXPRESSION (there is no IS_GENERATED column).
        rows = self.rows(
            "SELECT column_name, generation_expression "
            "FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = 'weekly_plans' "
            "AND column_name = 'effective_week'"
        )
        self.assertEqual(len(rows), 1)
        name, expression = rows[0]
        self.assertEqual(name, "effective_week")
        self.assertTrue(str(expression or "").strip())
        self.assertIn("deleted_at", expression)
        self.assertIn("week_number", expression)

    def test_downgrade_is_blocked(self):
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config(_ALEMBIC_INI)
        script = ScriptDirectory.from_config(cfg)
        module = script.get_revision(I4_HEAD).module
        with self.assertRaisesRegex(RuntimeError, "intentionally blocked"):
            module.downgrade()

    def test_sync_state_rows_created_by_i3_survive_i4_reads(self):
        """I4 read paths must not delete or rewrite an I3 projection row."""
        from tests.integration.i4_support import (
            CLASS_ID,
            DAY_MON,
            OWNER,
            TERM_ID,
            WEEK,
            create_daily,
            day_content,
        )

        create_daily(
            self.SessionLocal,
            OWNER,
            DAY_MON,
            adopted_content=day_content(talk="存活话题", theme="存活主题"),
        )
        before = self.rows(
            "SELECT id, class_id, term_id, week_number, status, "
            "deterministic_themes, game_source_manifest, "
            "current_week_source_manifest, last_trigger_daily_plan_id, "
            "last_trigger_content_version, last_trigger_event, created_at, "
            "updated_at FROM weekly_plan_sync_states"
        )
        self.assertEqual(len(before), 1)
        self.assertEqual(before[0][1], CLASS_ID)
        self.assertEqual(before[0][2], TERM_ID)
        self.assertEqual(before[0][3], WEEK)

        result = self.create_weekly(OWNER, week=WEEK, theme="读取不写投影")
        self.assertTrue(result.created)

        after = self.rows(
            "SELECT id, class_id, term_id, week_number, status, "
            "deterministic_themes, game_source_manifest, "
            "current_week_source_manifest, last_trigger_daily_plan_id, "
            "last_trigger_content_version, last_trigger_event, created_at, "
            "updated_at FROM weekly_plan_sync_states"
        )
        self.assertEqual(before, after)
