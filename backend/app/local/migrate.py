"""Local database state inspection and real Alembic upgrades.

Startup rules (D1A spec §2): only an empty database is baselined and an
existing known revision is upgraded to head. An unknown/newer revision, a
multi-row version state the single linear chain cannot describe, or a
database with tables but no local version record refuses startup: the file
is preserved and no clean/downgrade/stamp is ever performed.

Path rules (D1A review R3): the Alembic config value is ``%``-escaped for
ConfigParser interpolation, and the read-only inspection URI is built with
``Path.as_uri`` so ``#``/``%``/space/非 ASCII characters address exactly the
target file instead of a URI fragment or a neighbouring path. The INI
itself carries no ``%(here)s`` token because ConfigParser re-interpolates a
substituted value containing ``%`` (a legal character in Windows install
paths); the programmatic entry overrides ``script_location`` and
``prepend_sys_path`` with absolute, escaped paths.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.local import d1_digest as _d1_digest
from app.local.errors import LocalDatabaseStateError
from app.local.sqlite import LOCAL_VERSION_TABLE, readonly_sqlite_uri, sqlite_url

BACKEND_DIR = Path(__file__).resolve().parents[2]
ALEMBIC_INI_PATH = BACKEND_DIR / "alembic-local.ini"
MIGRATIONS_DIR = BACKEND_DIR / "migrations_local"

STATE_EMPTY = "empty"
STATE_CURRENT = "current"
STATE_UPGRADE = "upgrade"
STATE_UNMANAGED = "unmanaged"
STATE_UNKNOWN_VERSION = "unknown_version"
STATE_UNREADABLE = "unreadable"


@dataclass(frozen=True)
class DatabaseInspection:
    state: str
    current_revision: str | None
    detail: str | None = None


def _escape_ini_value(value: str) -> str:
    """Escape ``%`` for ConfigParser; ``get`` restores the literal text."""
    return value.replace("%", "%%")


def alembic_config(db_path: Path | None = None) -> Config:
    """Build the local Alembic config; never reads legacy configuration.

    ``script_location`` and ``prepend_sys_path`` are overridden with
    absolute, escaped paths: programmatic runs may start from any working
    directory (the INI values are relative for the documented CLI runs),
    and neither value may reach ConfigParser with a raw ``%`` when the
    checkout directory contains one (R3).
    """
    if not ALEMBIC_INI_PATH.is_file() or not MIGRATIONS_DIR.is_dir():
        raise LocalDatabaseStateError(
            "LOCAL_DB_MIGRATION_MISSING", "本地数据库迁移脚本缺失"
        )
    config = Config(str(ALEMBIC_INI_PATH))
    config.set_main_option(
        "script_location", _escape_ini_value(str(MIGRATIONS_DIR))
    )
    config.set_main_option(
        "prepend_sys_path", _escape_ini_value(str(BACKEND_DIR))
    )
    if db_path is not None:
        url = sqlite_url(db_path).render_as_string(hide_password=False)
        # env.py prefers this attribute; it never goes through ConfigParser.
        config.attributes["sqlalchemy_url"] = url
        # Keep the INI option in sync as well; ``%`` must be doubled because
        # ConfigParser interpolates ``%(name)s`` patterns on read.
        config.set_main_option("sqlalchemy.url", _escape_ini_value(url))
    return config


def head_revision(config: Config | None = None) -> str | None:
    config = config or alembic_config()
    return ScriptDirectory.from_config(config).get_current_head()


def _known_revisions(config: Config) -> set[str]:
    script = ScriptDirectory.from_config(config)
    return {revision.revision for revision in script.walk_revisions()}


def _remove_created_wal_side_files(
    db_path: Path, *, wal_existed: bool, shm_existed: bool
) -> None:
    """Best-effort cleanup of empty WAL side files a read-only open created.

    A read-only connection to a WAL database without a live writer creates a
    zero-length ``-wal`` and a ``-shm`` file. Existence was recorded before
    the connect, so whenever any side file pre-existed (possibly belonging
    to a live or unclean session) nothing is touched; only empty files this
    exact inspection created are removed.
    """
    if wal_existed or shm_existed:
        return
    wal = db_path.with_name(db_path.name + "-wal")
    shm = db_path.with_name(db_path.name + "-shm")
    try:
        if wal.exists() and wal.stat().st_size == 0:
            wal.unlink()
            shm.unlink(missing_ok=True)
    except OSError:
        # Side files must never turn an inspection into a startup failure.
        pass


def inspect_database(db_path: Path, config: Config) -> DatabaseInspection:
    """Classify the database file without modifying it."""
    if not db_path.exists() or db_path.stat().st_size == 0:
        return DatabaseInspection(STATE_EMPTY, None)

    wal = db_path.with_name(db_path.name + "-wal")
    shm = db_path.with_name(db_path.name + "-shm")
    wal_existed = wal.exists()
    shm_existed = shm.exists()
    uri = readonly_sqlite_uri(db_path)
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        return DatabaseInspection(STATE_UNREADABLE, None, "cannot open file")

    try:
        try:
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        except sqlite3.DatabaseError:
            return DatabaseInspection(STATE_UNREADABLE, None, "not a sqlite database")
        tables = [row[0] for row in rows]

        if LOCAL_VERSION_TABLE not in tables:
            if not tables:
                return DatabaseInspection(STATE_EMPTY, None)
            return DatabaseInspection(
                STATE_UNMANAGED, None, f"unmanaged tables: {', '.join(tables[:8])}"
            )

        try:
            rows = connection.execute(
                f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"  # noqa: S608
            ).fetchall()
        except sqlite3.DatabaseError:
            return DatabaseInspection(
                STATE_UNMANAGED, None, "version table unreadable"
            )
        versions = [row[0] for row in rows]
        other_tables = [name for name in tables if name != LOCAL_VERSION_TABLE]
        if not versions:
            if not other_tables:
                return DatabaseInspection(STATE_EMPTY, None)
            return DatabaseInspection(
                STATE_UNMANAGED, None, "missing local version record"
            )
        # The single linear chain can only describe exactly one head row;
        # any multi-row state (known+unknown in either insert order, or
        # duplicated known rows) is ambiguous and must refuse startup
        # instead of silently picking one row.
        if len(versions) > 1:
            return DatabaseInspection(
                STATE_UNKNOWN_VERSION,
                None,
                f"ambiguous multi-row version state ({len(versions)} rows)",
            )
        version = versions[0]
        if not isinstance(version, str) or not version:
            return DatabaseInspection(
                STATE_UNKNOWN_VERSION, None, "empty version record"
            )

        script = ScriptDirectory.from_config(config)
        known = _known_revisions(config)
        if version not in known:
            return DatabaseInspection(
                STATE_UNKNOWN_VERSION, version, "unrecognized revision"
            )
        current_head = script.get_current_head()
        state = STATE_CURRENT if version == current_head else STATE_UPGRADE
        return DatabaseInspection(state, version, current_head)
    finally:
        connection.close()
        _remove_created_wal_side_files(
            db_path, wal_existed=wal_existed, shm_existed=shm_existed
        )


class D1UpgradeGuard:
    """In-transaction consistency guard for a cold upgrade (spec §2.3.4).

    Built from the verified pre-upgrade backup (captured schema + digest). The
    local Alembic ``env.py`` calls ``before_migrations`` right after
    ``BEGIN IMMEDIATE`` and ``after_migrations`` right after ``run_migrations``
    but before ``COMMIT``. It is used only for a known non-empty upgrade; a
    plain migration never receives one.
    """

    def __init__(
        self,
        source_revision: str,
        schema: dict[str, tuple[str, ...]],
        expected_digest: str,
    ):
        self.source_revision = source_revision
        self.schema = schema
        self.expected_digest = expected_digest

    def _current_digest(self, connection) -> str:  # noqa: ANN001
        try:
            return _d1_digest.digest(connection, self.schema)
        except _d1_digest.DigestSchemaError as exc:
            raise LocalDatabaseStateError(
                "LOCAL_DB_MIGRATION_FAILED",
                "升级事务内旧 D1 表/列结构发生变化",
            ) from exc

    def before_migrations(self, connection) -> None:  # noqa: ANN001
        """Refuse if the source changed between the backup and the transaction."""
        if _d1_digest.single_revision(connection) != self.source_revision:
            raise LocalDatabaseStateError(
                "LOCAL_DB_MIGRATION_FAILED",
                "升级事务开始时源库版本与备份不一致",
            )
        if self._current_digest(connection) != self.expected_digest:
            raise LocalDatabaseStateError(
                "LOCAL_DB_MIGRATION_FAILED",
                "升级事务开始时旧 D1 数据摘要与备份不一致",
            )

    def after_migrations(self, connection) -> None:  # noqa: ANN001
        """Refuse if the migration altered existing D1 rows or broke the DB."""
        integrity = connection.exec_driver_sql(
            "PRAGMA integrity_check"
        ).fetchone()[0]
        if integrity != "ok":
            raise LocalDatabaseStateError(
                "LOCAL_DB_MIGRATION_FAILED", "升级事务内完整性检查失败"
            )
        if connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall():
            raise LocalDatabaseStateError(
                "LOCAL_DB_MIGRATION_FAILED", "升级事务内外键检查失败"
            )
        if self._current_digest(connection) != self.expected_digest:
            raise LocalDatabaseStateError(
                "LOCAL_DB_MIGRATION_FAILED", "升级事务内旧 D1 数据摘要发生变化"
            )


def ensure_local_schema(
    db_path: Path, *, d1_guard: "D1UpgradeGuard | None" = None
) -> DatabaseInspection:
    """Baseline an empty database or upgrade a known revision to head.

    ``d1_guard`` is an optional internal consistency guard used only by the
    runtime cold-upgrade path (engineering spec §2.3.4). It is forwarded to
    ``env.py`` through the Alembic config attributes and invoked *inside* the
    migration transaction so a change between the backup and the transaction,
    or a migration that alters existing D1 rows, is refused and rolled back.
    A plain migration (tests/CLI) passes ``None`` and behaves exactly as before.
    """
    config = alembic_config(db_path)
    if d1_guard is not None:
        config.attributes["d1_guard"] = d1_guard
    inspection = inspect_database(db_path, config)
    if inspection.state in (STATE_EMPTY, STATE_UPGRADE):
        try:
            command.upgrade(config, "head")
        except Exception as exc:  # noqa: BLE001 - reported as a startup refusal
            raise LocalDatabaseStateError(
                "LOCAL_DB_MIGRATION_FAILED", "本地数据库初始化或升级失败"
            ) from exc
        inspection = inspect_database(db_path, config)
        if inspection.state != STATE_CURRENT:
            raise LocalDatabaseStateError(
                "LOCAL_DB_MIGRATION_FAILED", "本地数据库初始化或升级失败"
            )
        return inspection
    if inspection.state == STATE_CURRENT:
        return inspection
    if inspection.state == STATE_UNMANAGED:
        raise LocalDatabaseStateError(
            "LOCAL_DB_NOT_MANAGED",
            "数据库文件包含无法识别的数据且没有本地版本记录",
        )
    if inspection.state == STATE_UNKNOWN_VERSION:
        raise LocalDatabaseStateError(
            "LOCAL_DB_VERSION_UNSUPPORTED",
            "数据库版本无法识别或来自更新的程序版本",
        )
    raise LocalDatabaseStateError("LOCAL_DB_UNREADABLE", "数据库文件无法读取")
