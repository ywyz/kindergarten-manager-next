"""Deterministic logical digest of the pre-upgrade (D1) database state.

Only used by the cold-upgrade guard (engineering spec §2.3). The schema
(tables and columns) is captured from the verified backup *before* the 0004
migration runs, so newly added D2 tables and columns are excluded by
construction and the digest over the pre-existing columns stays stable across
the 0004 DDL.

The digest is fully deterministic:

- tables are sorted by name and columns by name (never SQLite's physical order);
- rows are sorted by their canonical encoded bytes, so the result is
  independent of the order rows happen to be returned in;
- every value is type-tagged, so ``NULL`` / integer / real / text / blob can
  never collide (``NULL`` != ``''`` != ``0`` != ``b''``).

SQLite's double-quoted-string (DQS) compatibility would silently turn a
missing column such as ``SELECT "name" FROM t`` into the *string literal*
``'name'``, so a renamed/dropped column would not change the digest. Every
captured table **and** column is therefore verified against the live schema
before the rows are read (added columns are allowed), and the read uses
table-qualified identifiers so an unresolved name can never fall back to a
literal. A mismatch raises ``DigestSchemaError`` and the migration rolls back.

Only the hex digest and booleans leave this module: no business row, material,
path or content is ever logged.
"""

from __future__ import annotations

import hashlib
import struct

from app.local.sqlite import LOCAL_VERSION_TABLE

DIGEST_DOMAIN = b"kgm-local-d1-digest-v1\x00"


class DigestSchemaError(RuntimeError):
    """A captured table/column no longer exists (schema changed unexpectedly)."""


def _execute(connection, sql):  # noqa: ANN001
    """Run one statement on a raw sqlite3 connection or a SQLAlchemy one."""
    if hasattr(connection, "exec_driver_sql"):
        return connection.exec_driver_sql(sql)
    return connection.execute(sql)


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _live_columns(connection, table: str) -> set[str] | None:  # noqa: ANN001
    """Return the live column names of ``table``, or ``None`` if it is gone."""
    rows = _execute(
        connection, f"PRAGMA table_info({_quote(table)})"
    ).fetchall()
    if not rows:
        return None
    return {row[1] for row in rows}


def capture_schema(connection) -> dict[str, tuple[str, ...]]:  # noqa: ANN001
    """Return ``{table: sorted column names}`` for the current schema.

    The Alembic version table and SQLite internals are excluded. Call this on
    the verified backup (pre-upgrade) so upgrade-added columns/tables are not
    part of the captured set.
    """
    rows = _execute(
        connection,
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name",
    ).fetchall()
    schema: dict[str, tuple[str, ...]] = {}
    for row in rows:
        name = row[0]
        if name == LOCAL_VERSION_TABLE:
            continue
        columns = _execute(
            connection, f"PRAGMA table_info({_quote(name)})"
        ).fetchall()
        schema[name] = tuple(sorted(column[1] for column in columns))
    return schema


def _encode_value(value) -> bytes:  # noqa: ANN001
    if value is None:
        return b"\x00"
    if isinstance(value, bool):
        # sqlite3 never returns bool, but keep the tag space unambiguous.
        return b"\x01" + (b"1" if value else b"0")
    if isinstance(value, int):
        return b"\x01" + str(value).encode("ascii")
    if isinstance(value, float):
        return b"\x02" + struct.pack(">d", value)
    if isinstance(value, str):
        return b"\x03" + value.encode("utf-8")
    if isinstance(value, (bytes, bytearray, memoryview)):
        return b"\x04" + bytes(value)
    raise TypeError(f"unsupported column value type: {type(value)!r}")


def _frame(payload: bytes) -> bytes:
    return len(payload).to_bytes(8, "big") + payload


def _resolve_rows(connection, table: str, columns: tuple[str, ...]):  # noqa: ANN001
    if not columns:
        return []
    quoted_table = _quote(table)
    # Table-qualified identifiers: an unknown name can never fall back to a
    # double-quoted string literal.
    column_list = ", ".join(
        f"{quoted_table}.{_quote(column)}" for column in columns
    )
    rows = _execute(
        connection,
        f"SELECT {column_list} FROM {quoted_table}",  # noqa: S608 - quoted identifiers
    ).fetchall()
    return sorted(
        b"".join(_frame(_encode_value(value)) for value in row) for row in rows
    )


def digest(connection, schema: dict[str, tuple[str, ...]]) -> str:  # noqa: ANN001
    """Return the hex digest of every row of every captured table/column."""
    hasher = hashlib.sha256()
    hasher.update(DIGEST_DOMAIN)
    for table in sorted(schema):
        columns = schema[table]
        live = _live_columns(connection, table)
        if live is None:
            raise DigestSchemaError(f"captured table is missing: {table}")
        missing = [column for column in columns if column not in live]
        if missing:
            raise DigestSchemaError(
                f"captured columns are missing from {table}: {missing!r}"
            )
        hasher.update(_frame(table.encode("utf-8")))
        hasher.update(len(columns).to_bytes(8, "big"))
        for column in columns:
            hasher.update(_frame(column.encode("utf-8")))
        rows = _resolve_rows(connection, table, columns)
        hasher.update(len(rows).to_bytes(8, "big"))
        for encoded in rows:
            hasher.update(_frame(encoded))
    return hasher.hexdigest()


def single_revision(connection) -> str | None:  # noqa: ANN001
    """Return the single ``version_num``, or ``None`` unless exactly one."""
    try:
        rows = _execute(
            connection,
            f"SELECT version_num FROM {_quote(LOCAL_VERSION_TABLE)}",
        ).fetchall()
    except Exception:  # noqa: BLE001 - an unreadable/absent table means "no single"
        return None
    if len(rows) != 1:
        return None
    value = rows[0][0]
    return value if isinstance(value, str) and value else None
