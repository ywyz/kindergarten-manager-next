"""Local (desktop) Alembic environment: SQLite only, own version table.

Never reads the legacy ``DATABASE_URL``/``.env`` configuration and never
touches the historical MySQL revisions in ``backend/migrations``. DDL and
data changes run inside one explicit ``BEGIN IMMEDIATE`` transaction so a
failed migration leaves the database file unchanged. Foreign keys are
disabled only for the migration connection (SQLite's documented
table-rebuild procedure for the cyclic local tables) and the transaction
must pass ``PRAGMA foreign_key_check`` before it commits; application
connections always keep ``foreign_keys=ON``.
"""

from pathlib import Path

from alembic import context
from sqlalchemy.engine import make_url

from app.local.base import LocalBase
from app.local import models as local_models  # noqa: F401  (registers tables)
from app.local.sqlite import (
    LOCAL_VERSION_TABLE,
    create_local_engine,
    resolve_db_path,
    sqlite_url,
)

config = context.config

# Model metadata drives future autogenerate; the baseline is hand-written.
target_metadata = LocalBase.metadata


def _database_url() -> str:
    supplied = config.attributes.get("sqlalchemy_url") or config.get_main_option(
        "sqlalchemy.url"
    )
    if supplied:
        return supplied
    return sqlite_url(resolve_db_path()).render_as_string(hide_password=False)


def _local_db_path() -> Path:
    url = make_url(_database_url())
    if url.drivername != "sqlite+pysqlite":
        raise RuntimeError("local migrations only support sqlite+pysqlite")
    if not url.database:
        raise RuntimeError("local migrations require an explicit database file")
    return Path(url.database)


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table=LOCAL_VERSION_TABLE,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    guard = config.attributes.get("d1_guard")
    engine = create_local_engine(_local_db_path(), autocommit_driver=True)
    try:
        with engine.connect() as connection:
            # SQLite's documented table-rebuild procedure runs with foreign
            # keys disabled and verifies with foreign_key_check before COMMIT.
            # The cyclic references (local_terms <-> local_calendar_revisions
            # and the daily-plan pointers) cannot be rebuilt safely while
            # immediate enforcement is on, and toggling the pragma inside an
            # open transaction is a no-op.
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            # One real transaction for the whole migration chain: SQLite
            # supports transactional DDL, so a failure rolls the schema
            # completely back instead of leaving a half-created baseline.
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                # Cold-upgrade guard (runtime path only): the source revision
                # and the pre-upgrade D1 digest must still match the verified
                # backup before any migration runs.
                if guard is not None:
                    guard.before_migrations(connection)
                context.configure(
                    connection=connection,
                    target_metadata=target_metadata,
                    version_table=LOCAL_VERSION_TABLE,
                )
                # Alembic sees the caller's transaction and will not
                # start/commit one of its own.
                with context.begin_transaction():
                    context.run_migrations()
                # Post-migration, pre-COMMIT: existing D1 tables/columns must
                # be byte-for-byte unchanged and the database must be sound.
                if guard is not None:
                    guard.after_migrations(connection)
                violations = connection.exec_driver_sql(
                    "PRAGMA foreign_key_check"
                ).fetchall()
                if violations:
                    raise RuntimeError(
                        "local migration left foreign key violations: "
                        f"{violations[:5]!r}"
                    )
                connection.exec_driver_sql("COMMIT")
            except BaseException:
                connection.exec_driver_sql("ROLLBACK")
                raise
            finally:
                try:
                    connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                except Exception:  # noqa: BLE001 - must not mask the real cause
                    pass
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
