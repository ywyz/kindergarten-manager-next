"""0010 listening AI columns, typed checks and adoption ledger schema."""

from __future__ import annotations

import json
import sqlite3

from app.local.migrate import ensure_local_schema
from tests.local.listening_ai_fixture_support import create_0009_weekly_ai_fixture
from tests.local.support import LocalTestCase


class ListeningAIMigrationTests(LocalTestCase):
    def test_current_head_has_listening_columns_and_mixed_source_checks(self) -> None:
        runtime = self.make_runtime()
        connection = sqlite3.connect(runtime.db_path)
        try:
            revision = connection.execute(
                "SELECT version_num FROM local_alembic_version"
            ).fetchone()[0]
            self.assertEqual(revision, "20261107_0010_local_listening_ai")
            for table in (
                "local_ai_inputs",
                "local_ai_tasks",
                "local_ai_executions",
                "local_ai_candidates",
            ):
                columns = {
                    row[1] for row in connection.execute(f"PRAGMA table_info({table})")
                }
                self.assertTrue(
                    {"listening_record_id", "listening_domain", "listening_group_id"}
                    <= columns
                )
                sql = connection.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone()[0]
                self.assertIn(
                    f"ck_local_ai_{table.removeprefix('local_ai_')}_listening_columns",
                    sql,
                )
            adoption = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' "
                "AND name='local_listening_ai_adoption'"
            ).fetchone()
            self.assertIsNotNone(adoption)
            self.assertIn("fk_local_listening_ai_adoption_candidate", adoption[0])
            self.assertEqual(
                connection.execute("PRAGMA foreign_key_check").fetchall(), []
            )
        finally:
            connection.close()

    def test_real_0009_weekly_ai_rows_survive_0010_upgrade(self) -> None:
        """Build a genuine 0009 schema and synthetic weekly AI rows, then upgrade.

        The fixture runs the real migration chain to 0009 and inserts rows
        valid under the 0009 constraints; no archive, external path or
        version-number edit is involved. This covers the copy of
        ``weekly_plan_id``/``weekly_draft_id``/``create_operation_id`` that
        the listening 0010 rebuild must retain for pre-existing weekly rows.
        """

        db = self.tmp_root / "real-0009" / "kindergarten.db"
        ids = create_0009_weekly_ai_fixture(db)
        connection = sqlite3.connect(str(db))
        try:
            self.assertEqual(
                connection.execute(
                    "SELECT version_num FROM local_alembic_version"
                ).fetchone(),
                ("20261107_0009_local_listening",),
            )
            for table in (
                "local_ai_inputs",
                "local_ai_tasks",
                "local_ai_executions",
                "local_ai_candidates",
            ):
                columns = {
                    row[1] for row in connection.execute(f"PRAGMA table_info({table})")
                }
                self.assertNotIn("listening_record_id", columns)
                self.assertNotIn("listening_domain", columns)
                self.assertNotIn("listening_group_id", columns)
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%'"
                )
            }
            self.assertEqual(len(tables - {"local_alembic_version"}), 55)
            self.assertTrue(
                {
                    "local_listening_records",
                    "local_listening_domains",
                    "local_listening_evaluation_choices",
                    "local_listening_photo_groups",
                    "local_listening_assets",
                    "local_listening_operations",
                }
                <= tables
            )
            self.assertNotIn("local_listening_ai_adoption", tables)
            self.assertNotIn(
                "one_to_one_listening",
                connection.execute(
                    "SELECT sql FROM sqlite_master "
                    "WHERE type='table' AND name='local_ai_inputs'"
                ).fetchone()[0],
            )
            before = self._old_column_snapshot(connection)
            weekly_input = connection.execute(
                "SELECT weekly_plan_id, weekly_draft_id, create_operation_id "
                "FROM local_ai_inputs WHERE id = ?",
                (ids["input"],),
            ).fetchone()
            self.assertEqual(
                weekly_input,
                (ids["plan"], ids["draft"], ids["operation"]),
            )
        finally:
            connection.close()

        ensure_local_schema(db)

        connection = sqlite3.connect(str(db))
        try:
            self.assertEqual(
                connection.execute(
                    "SELECT version_num FROM local_alembic_version"
                ).fetchone(),
                ("20261107_0010_local_listening_ai",),
            )
            old_columns = {
                table: columns for table, (columns, _rows) in before.items()
            }
            self.assertEqual(
                self._old_column_snapshot(connection, old_columns),
                before,
                "0010 must not rewrite any pre-existing column value",
            )
            for table in (
                "local_ai_inputs",
                "local_ai_tasks",
                "local_ai_executions",
                "local_ai_candidates",
            ):
                columns = {
                    row[1] for row in connection.execute(f"PRAGMA table_info({table})")
                }
                self.assertTrue(
                    {
                        "listening_record_id",
                        "listening_domain",
                        "listening_group_id",
                    }
                    <= columns
                )
                self.assertEqual(
                    connection.execute(
                        f"SELECT COUNT(*) FROM {table} "
                        "WHERE listening_record_id IS NOT NULL "
                        "OR listening_domain IS NOT NULL "
                        "OR listening_group_id IS NOT NULL"
                    ).fetchone()[0],
                    0,
                    table,
                )
            self.assertIn(
                "one_to_one_listening",
                connection.execute(
                    "SELECT sql FROM sqlite_master "
                    "WHERE type='table' AND name='local_ai_inputs'"
                ).fetchone()[0],
            )
            self.assertEqual(
                connection.execute(
                    "SELECT weekly_plan_id, weekly_draft_id, "
                    "create_operation_id, source_kind FROM local_ai_inputs "
                    "WHERE id = ?",
                    (ids["input"],),
                ).fetchone(),
                (ids["plan"], ids["draft"], ids["operation"], "weekly_plan"),
            )
            adoption = connection.execute(
                "SELECT source_kind, weekly_plan_id, draft_id, draft_version, "
                "candidate_id, target_key, operation_id "
                "FROM local_weekly_plan_ai_adoption WHERE id = ?",
                (ids["adoption"],),
            ).fetchone()
            self.assertEqual(
                adoption,
                (
                    "weekly_plan",
                    ids["plan"],
                    ids["draft"],
                    1,
                    ids["candidate"],
                    "games",
                    ids["operation"],
                ),
            )
            self.assertEqual(
                connection.execute("PRAGMA foreign_key_check").fetchall(), []
            )
            self.assertEqual(
                connection.execute("PRAGMA integrity_check").fetchone(),
                ("ok",),
            )
        finally:
            connection.close()

    @staticmethod
    def _old_column_snapshot(
        connection: sqlite3.Connection,
        columns_by_table: dict[str, tuple[str, ...]] | None = None,
    ) -> dict:
        """Snapshot rows over the pre-0010 columns only."""

        tables = (
            "local_ai_inputs",
            "local_ai_tasks",
            "local_ai_executions",
            "local_ai_candidates",
            "local_prompt_bundles",
            "local_weekly_plan_ai_adoption",
            "local_ai_operations",
            "local_ai_config_versions",
            "local_personal_prompt_versions",
            "local_weekly_plans",
            "local_weekly_plan_contents",
            "local_listening_records",
            "local_listening_domains",
            "local_listening_evaluation_choices",
            "local_listening_photo_groups",
            "local_listening_assets",
            "local_listening_operations",
        )
        result: dict[str, tuple] = {}
        for table in tables:
            columns = (
                columns_by_table[table]
                if columns_by_table is not None
                else tuple(
                    row[1]
                    for row in connection.execute(f"PRAGMA table_info({table})")
                )
            )
            selected = ", ".join(f'"{column}"' for column in columns)
            rows = [
                json.dumps(row, ensure_ascii=False, default=repr)
                for row in connection.execute(
                    f'SELECT {selected} FROM "{table}"'
                ).fetchall()
            ]
            result[table] = (columns, tuple(sorted(rows)))
        return result
