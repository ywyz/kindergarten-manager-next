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
from alembic.script import ScriptDirectory

from app.local.base import LocalBase
from app.local.migrate import alembic_config, head_revision
from app.local.todo_models import LocalTodo, LocalTodoOperation

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations_local"
    / "versions"
    / "20261108_0013_local_todos.py"
)
PREVIOUS = "20261108_0012_local_listening_rotation"
REVISION = "20261108_0013_local_todos"


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
                "version", "created_at", "updated_at",
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
            {"ix_local_todos_profile_order"},
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
            },
        )

    def test_single_successor_migration_and_head(self) -> None:
        self.assertEqual(head_revision(alembic_config()), REVISION)
        script = ScriptDirectory.from_config(alembic_config())
        children = [
            revision.revision
            for revision in script.walk_revisions()
            if revision.down_revision == PREVIOUS
        ]
        self.assertEqual(children, [REVISION])
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


if __name__ == "__main__":
    unittest.main()
