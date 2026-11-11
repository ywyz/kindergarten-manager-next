"""Source-only todo schema/migration checks.

No SQLite connection, database file, Alembic upgrade or application startup
is exercised here.  The test reads the registered shared metadata, the linear
revision graph and the migration source text only.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

from app.local.base import LocalBase
from app.local.migrate import alembic_config
from app.local.todo_models import LocalTodo, LocalTodoOperation

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations_local"
    / "versions"
    / "20261108_0013_local_todos.py"
)
PREVIOUS = "20261108_0012_local_listening_rotation"
REVISION = "20261108_0013_local_todos"
ARCHIVE_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations_local"
    / "versions"
    / "20261111_0020_local_todo_archive.py"
)
ARCHIVE_REVISION = "20261111_0020_local_todo_archive"
ARCHIVE_PREVIOUS = "20261110_0019_local_directional_revisions"


class TodoSchemaSourceTests(unittest.TestCase):
    def test_todo_models_join_shared_metadata(self) -> None:
        tables = LocalBase.metadata.tables
        self.assertIs(tables["local_todos"], LocalTodo.__table__)
        self.assertIs(
            tables["local_todo_operations"], LocalTodoOperation.__table__
        )
        self.assertEqual(
            [column.name for column in tables["local_todos"].columns],
            [
                "id", "profile_id", "title", "due_date", "completed",
                "version", "created_at", "updated_at", "archived_at",
            ],
        )
        self.assertEqual(
            [column.name for column in tables["local_todo_operations"].columns],
            [
                "profile_id", "request_id", "action", "todo_id",
                "input_fingerprint", "result_json", "created_at",
            ],
        )
        todo_checks = {
            constraint.name
            for constraint in tables["local_todos"].constraints
            if constraint.name and constraint.name.startswith("ck_")
        }
        operation_checks = {
            constraint.name
            for constraint in tables["local_todo_operations"].constraints
            if constraint.name and constraint.name.startswith("ck_")
        }
        self.assertEqual(
            todo_checks,
            {"ck_local_todos_title", "ck_local_todos_version"},
        )
        self.assertEqual(
            operation_checks,
            {"ck_local_todo_operations_action"},
        )
        self.assertEqual(
            {index.name for index in tables["local_todos"].indexes},
            {"ix_local_todos_profile_order", "ix_local_todos_profile_archive"},
        )
        self.assertEqual(
            {index.name for index in tables["local_todo_operations"].indexes},
            {"ix_local_todo_operations_todo"},
        )
        for table_name in ("local_todos", "local_todo_operations"):
            targets = {
                element.target_fullname
                for constraint in tables[table_name].foreign_key_constraints
                for element in constraint.elements
            }
            self.assertEqual(targets, {"local_profile.id"})

    def test_migration_calls_match_registered_metadata(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "todo_migration_0013_source", MIGRATION
        )
        assert spec is not None and spec.loader is not None
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)

        tables: dict[str, dict] = {}
        indexes: list[tuple] = []

        class Recorder:
            @staticmethod
            def create_table(name, *columns, **kwargs):
                constraints = list(kwargs.values()) + list(columns)
                tables[name] = {
                    "columns": [c for c in columns if isinstance(c, sa.Column)],
                    "constraints": [
                        c for c in constraints
                        if isinstance(
                            c,
                            (
                                sa.CheckConstraint,
                                sa.PrimaryKeyConstraint,
                                sa.ForeignKeyConstraint,
                            ),
                        )
                    ],
                }

            @staticmethod
            def create_index(name, table, columns):
                indexes.append((name, table, tuple(columns)))

        original = migration.op
        migration.op = Recorder
        try:
            migration.upgrade()
        finally:
            migration.op = original

        self.assertEqual(set(tables), {"local_todos", "local_todo_operations"})
        for table_name, recorded in tables.items():
            table = LocalBase.metadata.tables[table_name]
            recorded_columns = {
                column.name: (str(column.type), column.nullable)
                for column in recorded["columns"]
            }
            model_columns = {
                column.name: (str(column.type), column.nullable)
                for column in table.columns
                if column.name != "archived_at"
            }
            self.assertEqual(recorded_columns, model_columns)
            self.assertEqual(
                {
                    (type(c).__name__, c.name)
                    for c in recorded["constraints"]
                },
                {
                    (type(c).__name__, c.name)
                    for c in table.constraints
                },
            )
            recorded_targets = {
                element.target_fullname
                for constraint in recorded["constraints"]
                if isinstance(constraint, sa.ForeignKeyConstraint)
                for element in constraint.elements
            }
            model_targets = {
                element.target_fullname
                for constraint in table.foreign_key_constraints
                for element in constraint.elements
            }
            self.assertEqual(recorded_targets, model_targets)

        self.assertEqual(
            {(name, table, columns) for name, table, columns in indexes},
            {
                (index.name, index.table.name, tuple(c.name for c in index.columns))
                for table in LocalBase.metadata.tables.values()
                for index in table.indexes
                if table.name.startswith("local_todo")
                and index.name != "ix_local_todos_profile_archive"
            },
        )

    def test_archive_migration_keeps_old_rows_readable(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "todo_archive_migration_0020_source", ARCHIVE_MIGRATION
        )
        assert spec is not None and spec.loader is not None
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        engine = sa.create_engine("sqlite://")
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "CREATE TABLE local_todos ("
                    "id VARCHAR(32) NOT NULL PRIMARY KEY, "
                    "profile_id VARCHAR(32) NOT NULL, "
                    "title VARCHAR(200) NOT NULL, "
                    "due_date DATE NULL, completed BOOLEAN NOT NULL, "
                    "version INTEGER NOT NULL, created_at DATETIME NOT NULL, "
                    "updated_at DATETIME NOT NULL)"
                )
                connection.exec_driver_sql(
                    "INSERT INTO local_todos "
                    "(id, profile_id, title, due_date, completed, version, "
                    "created_at, updated_at) VALUES "
                    "('t1', 'p1', '旧待办', NULL, 1, 1, "
                    "'2026-11-01T00:00:00', '2026-11-01T00:00:00')"
                )
                operations = Operations(MigrationContext.configure(connection))
                original = migration.op
                migration.op = operations
                try:
                    migration.upgrade()
                finally:
                    migration.op = original
                columns = [
                    row[1]
                    for row in connection.exec_driver_sql(
                        "PRAGMA table_info(local_todos)"
                    )
                ]
                self.assertIn("archived_at", columns)
                row = connection.exec_driver_sql(
                    "SELECT title, archived_at FROM local_todos WHERE id='t1'"
                ).one()
                self.assertEqual(row[0], "旧待办")
                self.assertIsNone(row[1])
                indexes = {
                    item[1]
                    for item in connection.exec_driver_sql(
                        "PRAGMA index_list(local_todos)"
                    )
                }
                self.assertIn("ix_local_todos_profile_archive", indexes)
        finally:
            engine.dispose()

    def test_single_successor_migration_and_head(self) -> None:
        script = ScriptDirectory.from_config(alembic_config())
        self.assertEqual(len(script.get_heads()), 1)
        revisions = {
            revision.revision: revision
            for revision in script.walk_revisions()
        }
        self.assertIn(ARCHIVE_REVISION, revisions)
        self.assertEqual(
            revisions[ARCHIVE_REVISION].down_revision, ARCHIVE_PREVIOUS
        )
        children = [
            revision.revision
            for revision in revisions.values()
            if revision.down_revision == PREVIOUS
        ]
        self.assertEqual(children, [REVISION])
        archive_children = [
            revision.revision
            for revision in revisions.values()
            if revision.down_revision == ARCHIVE_REVISION
        ]
        self.assertEqual(len(archive_children), 1)

        source = MIGRATION.read_text(encoding="utf-8")
        self.assertIn(f'revision: str = "{REVISION}"', source)
        self.assertIn(
            f'down_revision: Union[str, None] = "{PREVIOUS}"', source
        )
        for marker in (
            'op.create_table(\n        "local_todos"',
            'op.create_table(\n        "local_todo_operations"',
            "ck_local_todos_title",
            "ck_local_todos_version",
            "fk_local_todos_profile",
            "ix_local_todos_profile_order",
            "ck_local_todo_operations_action",
            "fk_local_todo_operations_profile",
            "ix_local_todo_operations_todo",
            "pk_local_todo_operations",
        ):
            self.assertIn(marker, source)
        self.assertNotIn("drop_table", source)
        self.assertNotIn("create_all", source)
        archive_source = ARCHIVE_MIGRATION.read_text(encoding="utf-8")
        self.assertIn(f'revision: str = "{ARCHIVE_REVISION}"', archive_source)
        self.assertIn(
            f'down_revision: Union[str, None] = "{ARCHIVE_PREVIOUS}"', archive_source
        )
        self.assertIn('"archived_at"', archive_source)
        self.assertIn("ix_local_todos_profile_archive", archive_source)
        self.assertNotIn("drop_table", archive_source)
        self.assertNotIn("create_all", archive_source)


if __name__ == "__main__":
    unittest.main()
