"""Migration entry point. No models or database creation in the skeleton."""

from alembic import context
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import make_url

from app.config import Settings
from app.database import Base
from app import models  # noqa: F401

# Model metadata drives autogenerate once models are authorized.
target_metadata = Base.metadata


def migration_url():
    value = Settings().database_url.get_secret_value()
    if not value:
        raise RuntimeError("Set DATABASE_URL before running migrations.")
    try:
        url = make_url(value)
    except Exception:
        raise RuntimeError("DATABASE_URL must be a valid MySQL URL.") from None
    if url.drivername != "mysql+pymysql":
        raise RuntimeError("DATABASE_URL must use mysql+pymysql (MySQL 8.4 / InnoDB).")
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=migration_url(), target_metadata=target_metadata,
        literal_binds=True, dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(migration_url(), poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
