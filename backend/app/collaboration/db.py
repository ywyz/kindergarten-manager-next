"""Single engine factory for the optional online collaboration service.

The target database is selected by the URL and is never hard-coded.  MySQL
8.4 connections use PyMySQL, ``READ COMMITTED`` transaction isolation and a
UTC session time zone so the application keeps the collaboration slice's
statement-level snapshot and timestamp semantics.  Only ``mysql+pymysql`` is
accepted; the historical PostgreSQL SQL is retained as a record, not as a
runtime fallback.  Bound SQL parameters are hidden from logs and exception
text; the application never creates tables.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from .config import CollaborationSettings

_MYSQL_INIT_COMMAND = (
    "SET SESSION time_zone = '+00:00', "
    "SESSION sql_mode = "
    "'STRICT_ALL_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION'"
)


def create_collaboration_engine(settings: CollaborationSettings) -> Engine:
    """Create the configured engine without connecting or creating tables."""
    scheme = urlsplit(settings.database_url).scheme
    options: dict[str, object] = {
        "pool_pre_ping": True,
        "pool_size": 5,
        "max_overflow": 0,
        "pool_recycle": 1800,
        "isolation_level": "READ COMMITTED",
        "echo": False,
        "hide_parameters": True,
    }
    if scheme != "mysql+pymysql":
        raise ValueError(
            "collaboration database URL must use mysql+pymysql://"
        )
    options["connect_args"] = {
        "charset": "utf8mb4",
        "init_command": _MYSQL_INIT_COMMAND,
    }
    return create_engine(settings.database_url, **options)
