"""A G1: 0007 -> 0008 preserves every old table/column raw value."""

from __future__ import annotations

import sqlite3

from alembic import command

from app.local.migrate import alembic_config
from tests.local.backup_fixture_support import old_0007_data_sql
from tests.local.support import LocalTestCase


def _business_tables(con: sqlite3.Connection) -> list[str]:
    return [
        row[0]
        for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' AND name != 'local_alembic_version' "
            "ORDER BY name"
        )
    ]


def _columns(con: sqlite3.Connection, table: str) -> tuple[str, ...]:
    return tuple(row[1] for row in con.execute(f'PRAGMA table_info("{table}")'))


class WeeklyAIMigrationTests(LocalTestCase):
    def test_all_48_old_tables_preserved_and_new_constraints(self):
        db = self.tmp_root / "old-0007.db"
        command.upgrade(alembic_config(db), "20261101_0007_local_weekly")
        con = sqlite3.connect(db)
        try:
            con.execute("PRAGMA foreign_keys=OFF")
            for table in _business_tables(con):
                con.execute(f'DELETE FROM "{table}"')
            # Keep the real Alembic-created 0007 version row.  The frozen dump
            # contains its own version INSERT; skip that identity statement and
            # restore only the frozen business rows.
            sql = "\n".join(
                line
                for line in old_0007_data_sql().splitlines()
                if "local_alembic_version" not in line
            )
            con.executescript(sql)
            con.commit()
        finally:
            con.close()
        con = sqlite3.connect(db)
        try:
            self.assertEqual(
                con.execute("SELECT version_num FROM local_alembic_version").fetchall(),
                [("20261101_0007_local_weekly",)],
            )
            old_tables = _business_tables(con)
            self.assertEqual(len(old_tables), 48)
            old: dict[str, tuple[tuple[str, ...], list[tuple]]] = {}
            for table in old_tables:
                cols = _columns(con, table)
                rows = con.execute(
                    f'SELECT {", ".join(chr(34) + c + chr(34) for c in cols)} '
                    f'FROM "{table}" ORDER BY rowid'
                ).fetchall()
                old[table] = (cols, rows)
        finally:
            con.close()

        command.upgrade(alembic_config(db), "head")
        con = sqlite3.connect(db)
        try:
            self.assertEqual(
                con.execute("SELECT version_num FROM local_alembic_version").fetchall(),
                [("20261102_0008_local_weekly_ai",)],
            )
            new_tables = set(_business_tables(con))
            self.assertEqual(set(old) | {"local_weekly_plan_ai_adoption"}, new_tables)
            for table, (cols, rows) in old.items():
                live = _columns(con, table)
                self.assertTrue(set(cols) <= set(live), table)
                actual = con.execute(
                    f'SELECT {", ".join(chr(34) + c + chr(34) for c in cols)} '
                    f'FROM "{table}" ORDER BY rowid'
                ).fetchall()
                self.assertEqual(actual, rows, table)
            self.assertEqual(
                con.execute("SELECT count(*) FROM local_weekly_plan_ai_adoption").fetchone()[0],
                0,
            )
            for table in (
                "local_ai_inputs",
                "local_ai_tasks",
                "local_ai_executions",
                "local_ai_candidates",
            ):
                self.assertEqual(
                    con.execute(
                        f"SELECT count(*) FROM {table} WHERE weekly_plan_id IS NOT NULL"
                    ).fetchone()[0],
                    0,
                    table,
                )
            self.assertEqual(
                con.execute(
                    "SELECT count(*) FROM local_ai_inputs "
                    "WHERE create_operation_id IS NOT NULL"
                ).fetchone()[0],
                0,
            )
            self.assertIn(
                "schema_version IN (1, 2)",
                con.execute(
                    "SELECT sql FROM sqlite_master WHERE name='local_weekly_plan_contents'"
                ).fetchone()[0],
            )
            self.assertIn(
                "uq_local_ai_tasks_active_per_weekly_type",
                {
                    row[0]
                    for row in con.execute(
                        "SELECT name FROM sqlite_master WHERE type='index'"
                    ).fetchall()
                },
            )
            self.assertEqual(con.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            con.close()
