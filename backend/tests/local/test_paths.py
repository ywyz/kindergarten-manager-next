"""Special-character paths: data path URI encoding and migration resources (R3).

Two independent path dimensions are covered:

- the data directory (database file) may legally contain ``%``, ``#``, spaces
  and non-ASCII characters; the read-only inspection URI must address exactly
  the target file and never a URI fragment or a neighbouring path;
- the migration resources themselves (``alembic-local.ini`` plus
  ``migrations_local``) may live under such a path, for the programmatic
  entry and for the supported CLI run from the resource directory. ConfigParser
  re-interpolates a substituted ``%(here)s`` value containing a raw ``%``, so
  no INI option may reference the config file location; the programmatic
  entry overrides both options with absolute, escaped paths.

No side files may appear beside the database or the resources.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path

from app.local import migrate
from app.local.errors import LocalDatabaseStateError
from app.local.migrate import ensure_local_schema, head_revision
from app.local.profile_service import read_context
from app.local.sqlite import LOCAL_VERSION_TABLE
from tests.local.support import (
    BACKEND_DIR,
    LocalTestCase,
    execute_sql,
    query_scalar,
    worker_env,
)

SPECIAL_DIR_NAMES = (
    "teacher%name",
    "teacher#name",
    "中文 空格%号#目录",
)

FUTURE_REVISION = "20990101_9999_future"
# The copied resource tree rewrites its head revision to this sentinel so the
# tests prove the migrated conclusion actually came from the copied scripts.
RESOURCE_SENTINEL_HEAD = "20990101_0000_resource_sentinel"
# Exactly the files that may appear beside the database: the SQLite family
# plus the persistent runtime lock file. Anything else is an unexpected side
# file (the whitelist is exact, not a prefix/wildcard match).
DB_FILE_NAMES = {
    "kindergarten.db",
    "kindergarten.db-wal",
    "kindergarten.db-shm",
    ".app-runtime.lock",
}


def _resource_tree(root: Path) -> list[str]:
    """Snapshot of a resource directory; bytecode caches are ignored."""
    return sorted(
        str(path.relative_to(root))
        for path in root.rglob("*")
        if "__pycache__" not in path.parts
    )


@contextmanager
def _patched_migration_resources(ini_path: Path, migrations_dir: Path):
    previous = (migrate.ALEMBIC_INI_PATH, migrate.MIGRATIONS_DIR)
    migrate.ALEMBIC_INI_PATH = ini_path
    migrate.MIGRATIONS_DIR = migrations_dir
    try:
        yield
    finally:
        migrate.ALEMBIC_INI_PATH, migrate.MIGRATIONS_DIR = previous


def _copy_backend_resources(destination: Path) -> Path:
    """Copy INI, migrations and the minimal ``app`` package used by env.py.

    The copied *current head* revision ID (discovered from the real resources,
    never hard-coded) is rewritten to ``RESOURCE_SENTINEL_HEAD`` so a migrated
    database proves which resource tree was actually consumed. Only the test
    copy is edited; the real 0001-0003 revision files are never touched.
    """
    destination.mkdir(parents=True)
    shutil.copy2(
        BACKEND_DIR / "alembic-local.ini", destination / "alembic-local.ini"
    )
    shutil.copytree(
        BACKEND_DIR / "migrations_local",
        destination / "migrations_local",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    (destination / "app").mkdir()
    shutil.copy2(
        BACKEND_DIR / "app" / "__init__.py",
        destination / "app" / "__init__.py",
    )
    shutil.copytree(
        BACKEND_DIR / "app" / "local",
        destination / "app" / "local",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    head_id = head_revision()
    if not head_id:
        raise AssertionError("no current head revision discovered")
    marker = f'revision: str = "{head_id}"'
    versions_dir = destination / "migrations_local" / "versions"
    head_file = None
    for candidate in sorted(versions_dir.glob("*.py")):
        if marker in candidate.read_text(encoding="utf-8"):
            head_file = candidate
            break
    if head_file is None:
        raise AssertionError(f"copied head revision file not found: {head_id}")
    text = head_file.read_text(encoding="utf-8")
    sentinel = text.replace(
        marker, f'revision: str = "{RESOURCE_SENTINEL_HEAD}"'
    )
    if sentinel == text:
        raise AssertionError("copied head revision was not rewritten")
    head_file.write_text(sentinel, encoding="utf-8")
    return destination


class SpecialCharacterPathTests(LocalTestCase):
    def _tree_snapshot(self, root: Path) -> list[str]:
        entries: list[str] = []
        for path in sorted(root.rglob("*")):
            entries.append(str(path.relative_to(root)))
        return entries

    def _assert_only_database_files(self, data_dir: Path) -> None:
        entries = {entry.name for entry in data_dir.iterdir()}
        self.assertTrue(
            entries <= DB_FILE_NAMES,
            f"unexpected files beside the database: {entries - DB_FILE_NAMES}",
        )
        self.assertIn("kindergarten.db", entries)

    def test_special_character_dirs_initialize_and_restart(self):
        for name in SPECIAL_DIR_NAMES:
            with self.subTest(dir=name):
                holder = self.tmp_root / name
                data_dir = holder / "data"
                runtime = self.make_runtime(data_dir)
                server = self.start_server(runtime)
                client = server.client()
                payload = self.initialize(client)
                profile_id = payload["profile"]["id"]
                server.stop()
                runtime.dispose()

                self._assert_only_database_files(data_dir)
                self.assertEqual(
                    {entry.name for entry in holder.iterdir()}, {"data"}
                )

                # Restart (fresh runtime, fresh state inspection) reads the
                # same database from the same encoded path.
                runtime2 = self.make_runtime(data_dir)
                session = runtime2.session()
                try:
                    context = read_context(session)
                finally:
                    session.close()
                self.assertEqual(context["status"], "ready")
                self.assertEqual(context["profile"]["id"], profile_id)
                self._assert_only_database_files(data_dir)
                self.assertEqual(
                    {entry.name for entry in holder.iterdir()}, {"data"}
                )

    def test_special_character_dir_unknown_version_refused_without_side_files(self):
        for name in SPECIAL_DIR_NAMES:
            with self.subTest(dir=name):
                holder = self.tmp_root / name
                data_dir = holder / "data"
                runtime = self.make_runtime(data_dir)
                runtime.dispose()
                db = data_dir / "kindergarten.db"
                execute_sql(
                    db,
                    f"UPDATE {LOCAL_VERSION_TABLE} "
                    f"SET version_num = '{FUTURE_REVISION}'",
                )
                before = self._tree_snapshot(holder)

                with self.assertRaises(LocalDatabaseStateError) as caught:
                    ensure_local_schema(db)
                self.assertEqual(
                    caught.exception.code, "LOCAL_DB_VERSION_UNSUPPORTED"
                )

                self.assertEqual(self._tree_snapshot(holder), before)
                self.assertEqual(
                    query_scalar(db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"),
                    FUTURE_REVISION,
                )

    def _programmatic_sequence(
        self, resources: Path, data_dir: Path, holder: Path
    ) -> Path:
        """First migration + normal restart + unknown-version refusal."""
        db = data_dir / "kindergarten.db"
        with _patched_migration_resources(
            resources / "alembic-local.ini",
            resources / "migrations_local",
        ):
            # The sentinel head is discovered from the copied resources,
            # not from the repository tree.
            self.assertEqual(head_revision(), RESOURCE_SENTINEL_HEAD)

            inspection = ensure_local_schema(db)
            self.assertEqual(inspection.state, "current")
            self.assertEqual(
                inspection.current_revision, RESOURCE_SENTINEL_HEAD
            )
            self.assertEqual(
                query_scalar(
                    db,
                    f"SELECT version_num FROM {LOCAL_VERSION_TABLE}",
                ),
                RESOURCE_SENTINEL_HEAD,
            )

            # Normal restart: same file, still current, nothing new.
            restart = ensure_local_schema(db)
            self.assertEqual(restart.state, "current")
            self.assertEqual(restart.current_revision, RESOURCE_SENTINEL_HEAD)

            # Unknown version refusal keeps the original file.
            execute_sql(
                db,
                f"UPDATE {LOCAL_VERSION_TABLE} "
                f"SET version_num = '{FUTURE_REVISION}'",
            )
            before = _resource_tree(holder)
            with self.assertRaises(LocalDatabaseStateError) as caught:
                ensure_local_schema(db)
            self.assertEqual(
                caught.exception.code, "LOCAL_DB_VERSION_UNSUPPORTED"
            )
            self.assertEqual(_resource_tree(holder), before)
            self.assertEqual(
                query_scalar(
                    db,
                    f"SELECT version_num FROM {LOCAL_VERSION_TABLE}",
                ),
                FUTURE_REVISION,
            )
        self._assert_only_database_files(data_dir)
        return db

    def test_migration_resources_under_special_path_initialize_and_refuse(self):
        for index, name in enumerate(SPECIAL_DIR_NAMES):
            with self.subTest(dir=name):
                holder = self.tmp_root / name
                resources = _copy_backend_resources(holder / "backend 检出")

                # Migration resources special, data path plain.
                plain_data = self.tmp_root / f"plain-data-{index}"
                plain_data.mkdir(parents=True)
                self._programmatic_sequence(resources, plain_data, holder)

                # Migration resources and data path both special.
                special_data = holder / "数据 %#空格" / "data"
                special_data.mkdir(parents=True)
                special_db = self._programmatic_sequence(
                    resources, special_data, holder
                )

                self.assertEqual(
                    {entry.name for entry in holder.iterdir()},
                    {"backend 检出", "数据 %#空格"},
                )
                # No bypass database was created anywhere under the holder.
                self.assertEqual(
                    [str(path) for path in holder.rglob("kindergarten.db")],
                    [str(special_db)],
                )

    def _cli_upgrade(
        self, resources: Path, data_dir: Path, *, expect_success: bool = True
    ) -> subprocess.CompletedProcess:
        env = worker_env()
        env["KGM_LOCAL_DATA_DIR"] = str(data_dir)
        env["PYTHONPATH"] = str(resources)
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "alembic",
                "-c",
                "alembic-local.ini",
                "upgrade",
                "head",
            ],
            cwd=str(resources),
            env=env,
            capture_output=True,
            timeout=180,
        )
        stderr = completed.stderr.decode("utf-8", "replace")
        if expect_success:
            self.assertEqual(completed.returncode, 0, stderr)
        else:
            self.assertNotEqual(completed.returncode, 0, stderr)
        return completed

    def test_cli_migration_from_special_resource_path(self):
        for index, name in enumerate(SPECIAL_DIR_NAMES):
            with self.subTest(dir=name):
                holder = self.tmp_root / f"cli-{name}"
                resources = _copy_backend_resources(holder / "backend% 检出#")

                # Migration resources special, data path plain.
                plain_data = self.tmp_root / f"cli-plain-data-{index}"
                plain_data.mkdir(parents=True)
                self._cli_upgrade(resources, plain_data)
                self.assertEqual(
                    query_scalar(
                        plain_data / "kindergarten.db",
                        f"SELECT version_num FROM {LOCAL_VERSION_TABLE}",
                    ),
                    RESOURCE_SENTINEL_HEAD,
                )
                self._assert_only_database_files(plain_data)

                # Migration resources and data path both special.
                special_data = holder / "数据 %#cli" / "data"
                special_data.mkdir(parents=True)
                db = special_data / "kindergarten.db"
                self._cli_upgrade(resources, special_data)
                self._cli_upgrade(resources, special_data)  # restart
                self.assertEqual(
                    query_scalar(
                        db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"
                    ),
                    RESOURCE_SENTINEL_HEAD,
                )

                # An unknown revision must not be modified or cleaned up.
                execute_sql(
                    db,
                    f"UPDATE {LOCAL_VERSION_TABLE} "
                    f"SET version_num = '{FUTURE_REVISION}'",
                )
                before = _resource_tree(holder)
                self._cli_upgrade(resources, special_data, expect_success=False)
                self.assertEqual(_resource_tree(holder), before)
                self.assertEqual(
                    query_scalar(
                        db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"
                    ),
                    FUTURE_REVISION,
                )

                self._assert_only_database_files(special_data)
                self.assertEqual(
                    {entry.name for entry in holder.iterdir()},
                    {"backend% 检出#", "数据 %#cli"},
                )
                self.assertEqual(
                    [str(path) for path in holder.rglob("kindergarten.db")],
                    [str(db)],
                )

    def test_cli_migration_handles_special_character_path(self):
        holder = self.tmp_root / "cli 中文%#目录"
        data_dir = holder / "data"
        data_dir.mkdir(parents=True)
        env = worker_env()
        env["KGM_LOCAL_DATA_DIR"] = str(data_dir)
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "alembic",
                "-c",
                "alembic-local.ini",
                "upgrade",
                "head",
            ],
            cwd=str(BACKEND_DIR),
            env=env,
            capture_output=True,
            timeout=180,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stderr.decode("utf-8", "replace"),
        )
        db = data_dir / "kindergarten.db"
        self.assertEqual(
            query_scalar(db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"),
            head_revision(),
        )
        self._assert_only_database_files(data_dir)
        self.assertEqual({entry.name for entry in holder.iterdir()}, {"data"})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
