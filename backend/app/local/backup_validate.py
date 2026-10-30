"""Business-level validation for Format 1 backup snapshots.

Only local SQLite and managed files are inspected.  Validation is read-only
for the caller's live data; an old database is upgraded only in the isolated
copy supplied by the verifier.  The trusted schema is compared with a canonical
database built from the same Alembic revision, so a table that merely has the
same column names but no primary key, foreign key, CHECK or unique constraint
cannot pass.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import threading
import unicodedata
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from alembic import command

from app.local import backup_format, backup_fs, observation_assets
from app.local.errors import LocalError
from app.local.migrate import alembic_config, head_revision
from app.local.sqlite import LOCAL_VERSION_TABLE

_CHUNK = 1024 * 1024
_DEVICE_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SNAPSHOT_ID = re.compile(r"^[0-9a-f]{32}$")
_OPAQUE_ID = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_SCHEMA_CACHE: dict[str, dict[str, Any]] = {}
_SCHEMA_LOCK = threading.Lock()


class BackupValidationError(LocalError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _connect_readonly(path: Path) -> sqlite3.Connection:
    try:
        return sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    except (OSError, sqlite3.Error) as exc:
        raise BackupValidationError(
            "BACKUP_DB_UNREADABLE", "备份数据库无法读取"
        ) from exc


def _known_revisions() -> set[str]:
    config = alembic_config()
    from alembic.script import ScriptDirectory

    return {
        revision.revision
        for revision in ScriptDirectory.from_config(config).walk_revisions()
    }


def _revision(connection: sqlite3.Connection) -> str | None:
    try:
        rows = connection.execute(
            f'SELECT version_num FROM "{LOCAL_VERSION_TABLE}"'
        ).fetchall()
    except sqlite3.Error:
        return None
    if len(rows) != 1 or not isinstance(rows[0][0], str) or not rows[0][0]:
        return None
    return rows[0][0]


def _normalize_sql(value: str | None) -> str:
    """Normalize formatting outside SQL quoted values, preserving semantics.

    SQLite stores the original ``CREATE`` text.  Case-folding or whitespace
    collapsing the whole text would make ``state <> 'active'`` equivalent to
    ``state <> 'ACTIVE'``; that changes a CHECK constraint.  This scanner
    therefore normalizes only unquoted text (keywords/identifiers) and keeps
    single-quoted strings, double-quoted identifiers, backtick identifiers and
    bracket identifiers byte-for-byte, including escapes and whitespace.
    """

    if not value:
        return ""
    output: list[str] = []
    index = 0
    length = len(value)
    pending_space = False
    while index < length:
        char = value[index]
        if char in ("'", '"', "`", "["):
            if pending_space and output and output[-1] != " ":
                output.append(" ")
            pending_space = False
            closing = "]" if char == "[" else char
            output.append(char)
            index += 1
            while index < length:
                current = value[index]
                output.append(current)
                if current == closing:
                    if index + 1 < length and value[index + 1] == closing:
                        output.append(value[index + 1])
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            continue
        if char.isspace():
            pending_space = True
            index += 1
            continue
        if pending_space and output and output[-1] != " ":
            output.append(" ")
        pending_space = False
        output.append(char.lower())
        index += 1
    result = "".join(output).strip()
    if result.endswith(";"):
        result = result[:-1].rstrip()
    return result


def _schema_snapshot(connection: sqlite3.Connection) -> dict[str, Any]:
    """Capture every user object plus its PRAGMA structure.

    SQLite stores the exact ``CREATE`` text it executed, so canonical and
    backup schemas produced by the same migration revision have identical
    normalized text.  The PRAGMA view catches a forged table whose text was
    copied but whose actual constraints differ, and makes missing PK/FK/
    CHECK/unique or a substituted column type visible.
    """

    rows = connection.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master"
    ).fetchall()
    tables: dict[str, str] = {}
    indexes: dict[str, str] = {}
    for kind, name, _table, sql in rows:
        lowered = str(name).casefold()
        if lowered == "sqlite_sequence" and kind == "table":
            # Only the two SQLite-internal object families this schema can
            # legitimately contain are skipped.  A trigger named
            # ``sqliteXprobe`` does not start with ``sqlite_``; an unknown
            # ``sqlite_evil`` object is rejected rather than hidden.
            continue
        if (
            lowered.startswith("sqlite_autoindex_")
            and kind == "index"
            and sql is None
        ):
            continue
        if lowered.startswith("sqlite_"):
            raise BackupValidationError(
                "BACKUP_DB_SCHEMA_UNTRUSTED", "备份数据库含未知内部对象"
            )
        if kind == "table":
            tables[name] = _normalize_sql(sql)
        elif kind == "index":
            indexes[name] = _normalize_sql(sql)
        else:
            raise BackupValidationError(
                "BACKUP_DB_SCHEMA_UNTRUSTED", "备份数据库含未知对象类型"
            )
    result: dict[str, Any] = {"tables": {}, "indexes": indexes}
    for name, sql in tables.items():
        quoted = '"' + name.replace('"', '""') + '"'
        info = connection.execute(f"PRAGMA table_info({quoted})").fetchall()
        xinfo = connection.execute(f"PRAGMA table_xinfo({quoted})").fetchall()
        fks = connection.execute(f"PRAGMA foreign_key_list({quoted})").fetchall()
        index_rows = connection.execute(f"PRAGMA index_list({quoted})").fetchall()
        index_details: dict[str, Any] = {}
        for index_row in index_rows:
            index_name = index_row[1]
            if str(index_name).casefold().startswith("sqlite_autoindex_"):
                continue
            index_quoted = '"' + str(index_name).replace('"', '""') + '"'
            columns = connection.execute(
                f"PRAGMA index_info({index_quoted})"
            ).fetchall()
            index_details[str(index_name)] = (
                tuple(index_row),
                tuple(columns),
            )
        result["tables"][name] = {
            "sql": sql,
            "info": tuple(info),
            "xinfo": tuple(xinfo),
            "foreign_keys": tuple(sorted(fks)),
            "indexes": index_details,
        }
    return result


def _canonical_schema(revision: str, scratch_dir: Path | None) -> dict[str, Any]:
    with _SCHEMA_LOCK:
        cached = _SCHEMA_CACHE.get(revision)
        if cached is not None:
            return cached
        base = Path(tempfile.mkdtemp(prefix="kgm-schema-", dir=scratch_dir))
        db_path = base / "canonical.db"
        base_identity: tuple[int, int] | None = None
        try:
            info = os.stat(base)
            base_identity = (int(info.st_dev), int(info.st_ino))
            command.upgrade(alembic_config(db_path), revision)
            connection = _connect_readonly(db_path)
            try:
                snapshot = _schema_snapshot(connection)
            finally:
                connection.close()
        except BackupValidationError:
            raise
        except Exception as exc:  # noqa: BLE001 - canonical schema refusal
            raise BackupValidationError(
                "BACKUP_DB_SCHEMA_UNTRUSTED", "无法构建该版本的可信结构"
            ) from exc
        finally:
            active = sys.exc_info()[1]
            try:
                backup_fs.remove_tree(
                    base, expected_identity=base_identity
                )
            except Exception as cleanup:  # noqa: BLE001 - preserve primary
                if active is not None:
                    active.add_note(
                        f"canonical schema cleanup failed: {cleanup}"
                    )
                else:
                    raise
        _SCHEMA_CACHE[revision] = snapshot
        return snapshot


def _validate_schema(
    connection: sqlite3.Connection, revision: str, scratch_dir: Path | None
) -> None:
    actual = _schema_snapshot(connection)
    expected = _canonical_schema(revision, scratch_dir)
    if actual != expected:
        raise BackupValidationError(
            "BACKUP_DB_SCHEMA_UNTRUSTED", "备份数据库结构与可信版本不一致"
        )


def _ai_contracts(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    try:
        rows = connection.execute(
            "SELECT DISTINCT task_type, contract_version, default_revision "
            "FROM local_prompt_bundles "
            "ORDER BY task_type, contract_version, default_revision"
        ).fetchall()
    except sqlite3.Error as exc:
        raise BackupValidationError(
            "BACKUP_DB_LOGICAL_INVALID", "备份数据库 AI 契约无法读取"
        ) from exc
    return [
        {
            "task_type": row[0],
            "contract_version": row[1],
            "default_revision": row[2],
        }
        for row in rows
    ]


def _file_hash(path: Path, *, limit: int, cancel=None) -> tuple[int, str]:
    try:
        with backup_fs.FileLease(path) as lease:
            if lease.size > limit:
                raise BackupValidationError(
                    "BACKUP_RESOURCE_INVALID", "备份资源超过上限"
                )
            hasher = hashlib.sha256()
            total = 0
            while True:
                if cancel is not None and cancel.is_set():
                    raise BackupValidationError("BACKUP_CANCELLED", "备份已取消")
                chunk = lease.read(_CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise BackupValidationError(
                        "BACKUP_RESOURCE_INVALID", "备份资源超过上限"
                    )
                hasher.update(chunk)
            if total != lease.size:
                raise BackupValidationError(
                    "BACKUP_RESOURCE_INVALID", "备份资源在读取期间发生变化"
                )
            return total, hasher.hexdigest()
    except BackupValidationError:
        raise
    except LocalError as exc:
        raise BackupValidationError(
            "BACKUP_RESOURCE_UNREADABLE", "备份资源无法读取"
        ) from exc
    except OSError as exc:
        raise BackupValidationError(
            "BACKUP_RESOURCE_UNREADABLE", "备份资源无法读取"
        ) from exc


def _count(connection: sqlite3.Connection, sql: str) -> int:
    try:
        row = connection.execute(sql).fetchone()
    except sqlite3.Error as exc:
        raise BackupValidationError(
            "BACKUP_DB_LOGICAL_INVALID", "备份数据库业务校验无法执行"
        ) from exc
    return int(row[0] if row is not None else 0)


def _logical_checks(connection: sqlite3.Connection) -> None:
    checks = {
        "observation_current_draft": """
            SELECT COUNT(*) FROM local_observation_records r
            LEFT JOIN local_observation_drafts d ON d.observation_id = r.id
            WHERE d.observation_id IS NULL OR d.revision != r.current_draft_revision
        """,
        "observation_current_version": """
            SELECT COUNT(*) FROM local_observation_records r
            LEFT JOIN local_observation_versions v
              ON v.observation_id = r.id AND v.version = r.current_version
            WHERE r.current_version IS NOT NULL AND v.id IS NULL
        """,
        "draft_photo_asset": """
            SELECT COUNT(*) FROM local_observation_draft_photos p
            LEFT JOIN local_observation_assets a
              ON a.observation_id = p.observation_id AND a.id = p.asset_id
            WHERE a.id IS NULL
        """,
        "version_photo_asset": """
            SELECT COUNT(*) FROM local_observation_version_photos p
            LEFT JOIN local_observation_versions v
              ON v.observation_id = p.observation_id AND v.id = p.version_id
            LEFT JOIN local_observation_assets a
              ON a.observation_id = p.observation_id AND a.id = p.asset_id
            WHERE v.id IS NULL OR a.id IS NULL
        """,
        "ai_input_photo": """
            SELECT COUNT(*) FROM local_observation_ai_input_photos p
            LEFT JOIN local_ai_inputs i ON i.id = p.input_id
            LEFT JOIN local_observation_assets a
              ON a.observation_id = p.observation_id AND a.id = p.asset_id
            LEFT JOIN local_observation_asset_derivatives d
              ON d.observation_id = p.observation_id
             AND d.asset_id = p.asset_id AND d.id = p.derivative_id
            WHERE i.id IS NULL OR a.id IS NULL OR d.id IS NULL
        """,
        "daily_current_content": """
            SELECT COUNT(*) FROM local_daily_plans p
            LEFT JOIN local_daily_plan_contents c
              ON c.daily_plan_id = p.id AND c.id = p.current_content_id
             AND c.version = p.current_content_version
            WHERE c.id IS NULL
        """,
        "term_current_calendar": """
            SELECT COUNT(*) FROM local_terms t
            LEFT JOIN local_calendar_revisions r
              ON r.term_id = t.id AND r.id = t.current_calendar_revision_id
            WHERE r.id IS NULL
        """,
        "settings_current_class": """
            SELECT COUNT(*) FROM local_settings s
            LEFT JOIN local_classes c ON c.id = s.current_class_id
            WHERE c.id IS NULL
        """,
        "game_current_revision": """
            SELECT COUNT(*) FROM local_class_game_heads h
            LEFT JOIN local_class_game_revisions r
              ON r.class_id = h.class_id AND r.id = h.current_revision_id
            WHERE r.id IS NULL
        """,
        "prompt_current_revision": """
            SELECT COUNT(*) FROM local_personal_prompt_heads h
            LEFT JOIN local_personal_prompt_versions v
              ON v.profile_id = h.profile_id AND v.task_type = h.task_type
             AND v.revision = h.current_revision
            WHERE v.profile_id IS NULL
        """,
        "ai_current_config": """
            SELECT COUNT(*) FROM local_ai_state s
            LEFT JOIN local_ai_config_versions c
              ON c.profile_id = s.profile_id
             AND c.version = s.current_config_version
            WHERE s.current_config_version IS NOT NULL AND c.profile_id IS NULL
        """,
        "ai_blocked_config": """
            SELECT COUNT(*) FROM local_ai_state s
            LEFT JOIN local_ai_config_versions c
              ON c.profile_id = s.profile_id
             AND c.version = s.blocked_config_version
            WHERE s.blocked_config_version IS NOT NULL AND c.profile_id IS NULL
        """,
        "ai_task_execution": """
            SELECT COUNT(*) FROM local_ai_tasks t
            LEFT JOIN local_ai_executions e
              ON e.task_id = t.id AND e.id = t.current_execution_id
            WHERE t.current_execution_id IS NOT NULL AND e.id IS NULL
        """,
        "ai_execution_task": """
            SELECT COUNT(*) FROM local_ai_executions e
            LEFT JOIN local_ai_tasks t ON t.id = e.task_id
            WHERE t.id IS NULL
        """,
        "ai_candidate_execution": """
            SELECT COUNT(*) FROM local_ai_candidates c
            LEFT JOIN local_ai_executions e ON e.id = c.execution_id
            LEFT JOIN local_ai_tasks t ON t.id = c.task_id
            WHERE e.id IS NULL OR t.id IS NULL
        """,
        "ai_attempt_execution": """
            SELECT COUNT(*) FROM local_ai_attempts a
            LEFT JOIN local_ai_executions e ON e.id = a.execution_id
            WHERE e.id IS NULL
        """,
        "observation_restore_source": """
            SELECT COUNT(*) FROM local_observation_restores r
            LEFT JOIN local_observation_versions v
              ON v.observation_id = r.observation_id
             AND v.version = r.source_version
            WHERE v.id IS NULL
        """,
        "observation_restore_result": """
            SELECT COUNT(*) FROM local_observation_restores r
            LEFT JOIN local_observation_versions v
              ON v.observation_id = r.observation_id
             AND v.version = r.result_version
            WHERE v.id IS NULL
        """,
        "restore_preview_source": """
            SELECT COUNT(*) FROM local_observation_restore_previews p
            LEFT JOIN local_observation_versions v
              ON v.observation_id = p.observation_id
             AND v.version = p.source_version
            WHERE v.id IS NULL
        """,
        "export_token_snapshot": """
            SELECT COUNT(*) FROM local_observation_export_tokens t
            LEFT JOIN local_observation_export_snapshots s ON s.id = t.snapshot_id
            WHERE s.id IS NULL
        """,
        "export_attempt_snapshot": """
            SELECT COUNT(*) FROM local_observation_export_attempts a
            LEFT JOIN local_observation_export_snapshots s ON s.id = a.snapshot_id
            WHERE s.id IS NULL
        """,
    }
    for name, sql in checks.items():
        if _count(connection, sql):
            raise BackupValidationError(
                "BACKUP_DB_LOGICAL_INVALID", f"备份数据库逻辑指针不一致：{name}"
            )
    order_checks = {
        "draft_photo_order": """
            SELECT COUNT(*) FROM (
              SELECT observation_id FROM local_observation_draft_photos
              GROUP BY observation_id
              HAVING MAX(sort_order) + 1 != COUNT(*)
            )
        """,
        "version_photo_order": """
            SELECT COUNT(*) FROM (
              SELECT version_id FROM local_observation_version_photos
              GROUP BY version_id
              HAVING MAX(sort_order) + 1 != COUNT(*)
            )
        """,
        "ai_input_photo_order": """
            SELECT COUNT(*) FROM (
              SELECT input_id FROM local_observation_ai_input_photos
              GROUP BY input_id
              HAVING MAX(sort_order) + 1 != COUNT(*)
            )
        """,
    }
    for name, sql in order_checks.items():
        if _count(connection, sql):
            raise BackupValidationError(
                "BACKUP_DB_LOGICAL_INVALID", f"备份数据库照片顺序不一致：{name}"
            )


def _inspect_source_database(
    path: Path, *, scratch_dir: Path | None
) -> dict[str, Any]:
    connection = _connect_readonly(path)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise BackupValidationError(
                "BACKUP_DB_INTEGRITY", "备份数据库完整性失败"
            )
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise BackupValidationError(
                "BACKUP_DB_FOREIGN_KEY", "备份数据库外键失败"
            )
        revision = _revision(connection)
        if revision is None:
            raise BackupValidationError(
                "BACKUP_DB_REVISION", "备份数据库版本缺失或不唯一"
            )
        if revision not in _known_revisions():
            raise BackupValidationError(
                "BACKUP_DB_REVISION_UNSUPPORTED", "备份数据库版本未知"
            )
        _validate_schema(connection, revision, scratch_dir)
        contracts = _ai_contracts(connection)
    finally:
        connection.close()
    size, digest = _file_hash(
        path, limit=backup_format.MAX_DATABASE_BYTES
    )
    return {
        "source_revision": revision,
        "source_bytes": size,
        "source_sha256": digest,
        "source_ai_contracts": contracts,
    }


def inspect_source_database(
    path: Path, *, scratch_dir: Path | None = None
) -> dict[str, Any]:
    """Validate a source database without migrating it."""
    return _inspect_source_database(path, scratch_dir=scratch_dir)


def validate_database(
    path: Path,
    *,
    migrate_old: bool,
    require_current: bool = False,
    scratch_dir: Path | None = None,
) -> dict[str, Any]:
    facts = _inspect_source_database(path, scratch_dir=scratch_dir)
    source_revision = facts["source_revision"]
    head = head_revision()
    if source_revision != head:
        if require_current:
            raise BackupValidationError(
                "BACKUP_DB_REVISION_UNSUPPORTED", "快照数据库不是当前版本"
            )
        if not migrate_old:
            raise BackupValidationError(
                "BACKUP_DB_REVISION_UNSUPPORTED", "备份数据库版本不是当前版本"
            )
        try:
            command.upgrade(alembic_config(path), "head")
        except Exception as exc:  # noqa: BLE001 - isolated copy migration refusal
            raise BackupValidationError(
                "BACKUP_DB_MIGRATION_FAILED", "旧备份数据库迁移失败"
            ) from exc
        try:
            checkpoint = sqlite3.connect(str(path))
            try:
                checkpoint.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                checkpoint.close()
        except sqlite3.Error as exc:
            raise BackupValidationError(
                "BACKUP_DB_MIGRATION_FAILED", "迁移后数据库检查点失败"
            ) from exc
    connection = _connect_readonly(path)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise BackupValidationError(
                "BACKUP_DB_INTEGRITY", "迁移后数据库完整性失败"
            )
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise BackupValidationError(
                "BACKUP_DB_FOREIGN_KEY", "迁移后数据库外键失败"
            )
        if _revision(connection) != head:
            raise BackupValidationError(
                "BACKUP_DB_REVISION_UNSUPPORTED", "迁移后数据库版本不匹配"
            )
        _validate_schema(connection, head, scratch_dir)
        _logical_checks(connection)
    finally:
        connection.close()
    target_size, target_digest = _file_hash(
        path, limit=backup_format.MAX_DATABASE_BYTES
    )
    facts.update(
        {
            "revision": head,
            "head_revision": head,
            "database_bytes": target_size,
            "database_sha256": target_digest,
        }
    )
    return facts


def safe_relative_path(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 500
        or "\x00" in value
    ):
        raise BackupValidationError("BACKUP_PATH_INVALID", "备份资源路径不合法")
    if (
        value.startswith(("/", "\\"))
        or "\\" in value
        or ":" in value
        or "//" in value
        or value.endswith("/")
    ):
        raise BackupValidationError("BACKUP_PATH_INVALID", "备份资源路径不合法")
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in ("", ".", "..") for part in pure.parts):
        raise BackupValidationError("BACKUP_PATH_INVALID", "备份资源路径不合法")
    if any(len(part) > 255 for part in pure.parts):
        raise BackupValidationError("BACKUP_PATH_INVALID", "备份资源路径不合法")
    if any(part.endswith((".", " ")) for part in pure.parts):
        raise BackupValidationError("BACKUP_PATH_INVALID", "备份资源路径不合法")
    if any(part.split(".", 1)[0].lower() in _DEVICE_NAMES for part in pure.parts):
        raise BackupValidationError("BACKUP_PATH_INVALID", "备份资源路径不合法")
    if not value.startswith("observations/assets/"):
        raise BackupValidationError("BACKUP_PATH_INVALID", "备份资源不在受管目录")
    return pure.as_posix()


def iter_registered_resources(db_path: Path) -> Iterator[dict[str, Any]]:
    connection = _connect_readonly(db_path)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "local_observation_assets" not in tables:
            return
        has_derivatives = "local_observation_asset_derivatives" in tables
        sql = """
            SELECT relative_path, 'original' AS kind, observation_id,
                   id AS asset_id, NULL AS derivative_id, content_hash,
                   mime_type, width, height, orientation, byte_size
              FROM local_observation_assets
        """
        if has_derivatives:
            sql += """
            UNION ALL
            SELECT relative_path, purpose AS kind, observation_id,
                   asset_id, id AS derivative_id, content_hash,
                   mime_type, width, height, NULL AS orientation, NULL AS byte_size
              FROM local_observation_asset_derivatives
            """
        sql += " ORDER BY relative_path"
        rows = connection.execute(sql)
        seen: set[str] = set()
        folded: set[str] = set()
        prefixes: set[str] = set()
        for row in rows:
            path = safe_relative_path(row[0])
            folded_path = unicodedata.normalize("NFC", path).casefold()
            if path in seen or folded_path in folded:
                raise BackupValidationError(
                    "BACKUP_DB_RESOURCE_DUPLICATE", "备份数据库资源路径重复"
                )
            parts = path.split("/")
            for index in range(1, len(parts)):
                prefix = "/".join(parts[:index])
                if prefix in seen:
                    raise BackupValidationError(
                        "BACKUP_DB_RESOURCE_DUPLICATE", "备份数据库资源路径冲突"
                    )
                prefixes.add(prefix)
            if path in prefixes:
                raise BackupValidationError(
                    "BACKUP_DB_RESOURCE_DUPLICATE", "备份数据库资源路径冲突"
                )
            seen.add(path)
            folded.add(folded_path)
            yield {
                "path": path,
                "kind": row[1],
                "observation_id": row[2],
                "asset_id": row[3],
                "derivative_id": row[4],
                "sha256": row[5],
                "mime_type": row[6],
                "width": row[7],
                "height": row[8],
                "orientation": row[9],
                "byte_size": row[10],
            }
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# Strict manifest parsing / validation
# ---------------------------------------------------------------------------

class _DuplicateKey(ValueError):
    pass


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON number: {value}")


def parse_manifest_json(raw: bytes) -> Any:
    if not isinstance(raw, (bytes, bytearray)) or len(raw) > backup_format.MAX_MANIFEST_BYTES:
        raise BackupValidationError("BACKUP_MANIFEST_TOO_LARGE", "备份清单超过上限")
    try:
        text = bytes(raw).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BackupValidationError(
            "BACKUP_MANIFEST_INVALID", "备份清单编码不合法"
        ) from exc
    if text.startswith("\ufeff"):
        raise BackupValidationError("BACKUP_MANIFEST_INVALID", "备份清单不得含 BOM")
    try:
        return json.loads(
            text,
            object_pairs_hook=_no_duplicates,
            parse_constant=_reject_constant,
        )
    except (ValueError, RecursionError) as exc:
        raise BackupValidationError(
            "BACKUP_MANIFEST_INVALID", "备份清单不是严格 JSON"
        ) from exc


def _exact_keys(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise BackupValidationError(
            "BACKUP_MANIFEST_INVALID", f"备份清单字段不合法：{label}"
        )
    return value


def _int(value: Any, *, minimum: int, maximum: int, label: str) -> int:
    if type(value) is not int or value < minimum or value > maximum:
        raise BackupValidationError(
            "BACKUP_MANIFEST_INVALID", f"备份清单字段类型或范围不合法：{label}"
        )
    return value


def _str(value: Any, *, minimum: int, maximum: int, label: str) -> str:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        raise BackupValidationError(
            "BACKUP_MANIFEST_INVALID", f"备份清单字段类型或长度不合法：{label}"
        )
    if "\x00" in value:
        raise BackupValidationError(
            "BACKUP_MANIFEST_INVALID", f"备份清单字段含 NUL：{label}"
        )
    return value


def _hex64(value: Any, label: str) -> str:
    text = _str(value, minimum=64, maximum=64, label=label)
    if not _HEX64.fullmatch(text):
        raise BackupValidationError(
            "BACKUP_MANIFEST_INVALID", f"备份清单 hash 不合法：{label}"
        )
    return text


def _validate_manifest_schema(manifest: Any) -> dict[str, Any]:
    manifest = _exact_keys(
        manifest,
        {
            "format_version",
            "snapshot_id",
            "created_at",
            "app_version",
            "database_revision",
            "ai_contracts",
            "database",
            "resources",
            "counts",
            "source_identity",
        },
        "root",
    )
    if _int(
        manifest["format_version"], minimum=1, maximum=1, label="format_version"
    ) != backup_format.FORMAT_VERSION:
        raise BackupValidationError(
            "BACKUP_MANIFEST_INVALID", "备份清单格式版本不匹配"
        )
    if not _SNAPSHOT_ID.fullmatch(
        _str(manifest["snapshot_id"], minimum=32, maximum=32, label="snapshot_id")
    ):
        raise BackupValidationError(
            "BACKUP_MANIFEST_INVALID", "备份清单 snapshot_id 不合法"
        )
    created = _str(
        manifest["created_at"], minimum=1, maximum=64, label="created_at"
    )
    try:
        parsed = datetime.fromisoformat(created)
    except ValueError as exc:
        raise BackupValidationError(
            "BACKUP_MANIFEST_INVALID", "备份清单 created_at 不合法"
        ) from exc
    if parsed.tzinfo is None:
        raise BackupValidationError(
            "BACKUP_MANIFEST_INVALID", "备份清单 created_at 必须含时区"
        )
    _str(manifest["app_version"], minimum=1, maximum=128, label="app_version")
    _str(
        manifest["database_revision"],
        minimum=1,
        maximum=128,
        label="database_revision",
    )
    contracts = manifest["ai_contracts"]
    if not isinstance(contracts, list) or len(contracts) > 64:
        raise BackupValidationError(
            "BACKUP_MANIFEST_INVALID", "备份清单 AI 契约列表不合法"
        )
    for index, item in enumerate(contracts):
        item = _exact_keys(
            item,
            {"task_type", "contract_version", "default_revision"},
            f"ai_contracts[{index}]",
        )
        _str(item["task_type"], minimum=1, maximum=64, label="task_type")
        _int(
            item["contract_version"],
            minimum=1,
            maximum=2_147_483_647,
            label="contract_version",
        )
        _int(
            item["default_revision"],
            minimum=1,
            maximum=2_147_483_647,
            label="default_revision",
        )
    database = _exact_keys(
        manifest["database"], {"path", "bytes", "sha256"}, "database"
    )
    if database["path"] != backup_format.DATABASE_NAME:
        raise BackupValidationError(
            "BACKUP_MANIFEST_INVALID", "备份清单数据库成员不合法"
        )
    _int(
        database["bytes"],
        minimum=0,
        maximum=backup_format.MAX_DATABASE_BYTES,
        label="database.bytes",
    )
    _hex64(database["sha256"], "database.sha256")
    resources = manifest["resources"]
    if not isinstance(resources, list) or len(resources) > backup_format.MAX_MEMBERS:
        raise BackupValidationError(
            "BACKUP_MANIFEST_INVALID", "备份清单资源数量不合法"
        )
    paths: list[str] = []
    folded_paths: set[str] = set()
    for index, entry in enumerate(resources):
        entry = _exact_keys(
            entry,
            {
                "asset_id",
                "bytes",
                "derivative_id",
                "kind",
                "observation_id",
                "path",
                "sha256",
            },
            f"resources[{index}]",
        )
        if not _OPAQUE_ID.fullmatch(
            _str(entry["asset_id"], minimum=1, maximum=32, label="asset_id")
        ):
            raise BackupValidationError(
                "BACKUP_MANIFEST_INVALID", "备份清单资源 asset_id 不合法"
            )
        if not _OPAQUE_ID.fullmatch(
            _str(
                entry["observation_id"],
                minimum=1,
                maximum=32,
                label="observation_id",
            )
        ):
            raise BackupValidationError(
                "BACKUP_MANIFEST_INVALID", "备份清单资源 observation_id 不合法"
            )
        derivative = entry["derivative_id"]
        if derivative is not None and not _OPAQUE_ID.fullmatch(
            _str(derivative, minimum=1, maximum=32, label="derivative_id")
        ):
            raise BackupValidationError(
                "BACKUP_MANIFEST_INVALID", "备份清单资源 derivative_id 不合法"
            )
        kind = _str(entry["kind"], minimum=1, maximum=20, label="kind")
        if kind not in ("original", "ai", "export"):
            raise BackupValidationError(
                "BACKUP_MANIFEST_INVALID", "备份清单资源 kind 不合法"
            )
        path = safe_relative_path(entry["path"])
        folded_path = unicodedata.normalize("NFC", path).casefold()
        if folded_path in folded_paths:
            raise BackupValidationError(
                "BACKUP_MANIFEST_INVALID", "备份清单资源路径大小写或 Unicode 冲突"
            )
        folded_paths.add(folded_path)
        paths.append(path)
        _int(
            entry["bytes"],
            minimum=0,
            maximum=backup_format.MAX_RESOURCE_BYTES,
            label="resources.bytes",
        )
        _hex64(entry["sha256"], "resources.sha256")
    if paths != sorted(paths) or len(set(paths)) != len(paths):
        raise BackupValidationError(
            "BACKUP_MANIFEST_INVALID", "备份清单资源路径未排序或重复"
        )
    counts = _exact_keys(
        manifest["counts"],
        {"database_bytes", "resources", "resources_bytes"},
        "counts",
    )
    _int(
        counts["database_bytes"],
        minimum=0,
        maximum=backup_format.MAX_DATABASE_BYTES,
        label="counts.database_bytes",
    )
    _int(
        counts["resources"],
        minimum=0,
        maximum=backup_format.MAX_MEMBERS,
        label="counts.resources",
    )
    _int(
        counts["resources_bytes"],
        minimum=0,
        maximum=backup_format.MAX_EXPANDED_BYTES,
        label="counts.resources_bytes",
    )
    identity = manifest["source_identity"]
    if not isinstance(identity, dict) or len(identity) > 32:
        raise BackupValidationError(
            "BACKUP_MANIFEST_INVALID", "备份清单 source_identity 不合法"
        )
    for key, value in identity.items():
        _str(key, minimum=1, maximum=64, label="source_identity key")
        if type(value) is bool:
            continue
        if type(value) is int:
            continue
        if not isinstance(value, str) or len(value) > 256:
            raise BackupValidationError(
                "BACKUP_MANIFEST_INVALID", "备份清单 source_identity 值不合法"
            )
    return manifest


def _validate_image_resource(
    path: Path,
    *,
    resources_root: Path,
    entry: dict[str, Any],
    cancel=None,
) -> None:
    if cancel is not None and cancel.is_set():
        raise BackupValidationError("BACKUP_CANCELLED", "备份已取消")
    try:
        inspection = observation_assets.inspect_managed_asset(
            path, resources_root, max_bytes=backup_format.MAX_RESOURCE_BYTES
        )
    except LocalError as exc:
        raise BackupValidationError(
            "BACKUP_RESOURCE_IMAGE_INVALID", "备份图片无法解码或格式不受支持"
        ) from exc
    if inspection.content_hash != entry["sha256"]:
        raise BackupValidationError(
            "BACKUP_RESOURCE_HASH", "备份图片 hash 与清单不一致"
        )
    if inspection.byte_size != entry["bytes"]:
        raise BackupValidationError(
            "BACKUP_RESOURCE_SIZE", "备份图片大小与清单不一致"
        )
    expected_mime = observation_assets._MIME_BY_FORMAT.get(  # noqa: SLF001
        inspection.image_format
    )
    if expected_mime != entry["mime_type"]:
        raise BackupValidationError(
            "BACKUP_RESOURCE_IMAGE_INVALID", "备份图片格式与登记不一致"
        )
    if entry.get("width") is not None and entry["width"] != inspection.width:
        raise BackupValidationError(
            "BACKUP_RESOURCE_IMAGE_INVALID", "备份图片宽度与登记不一致"
        )
    if entry.get("height") is not None and entry["height"] != inspection.height:
        raise BackupValidationError(
            "BACKUP_RESOURCE_IMAGE_INVALID", "备份图片高度与登记不一致"
        )
    if entry.get("orientation") is not None and entry["orientation"] != inspection.orientation:
        raise BackupValidationError(
            "BACKUP_RESOURCE_IMAGE_INVALID", "备份图片方向与登记不一致"
        )


def validate_manifest(
    manifest: Any,
    *,
    source_db_path: Path,
    resources_root: Path,
    facts: dict[str, Any],
    cancel=None,
) -> dict[str, Any]:
    manifest = _validate_manifest_schema(manifest)
    if manifest["database_revision"] != facts["source_revision"]:
        raise BackupValidationError(
            "BACKUP_MANIFEST_INVALID", "备份清单数据库版本不匹配"
        )
    if manifest["ai_contracts"] != facts["source_ai_contracts"]:
        raise BackupValidationError(
            "BACKUP_MANIFEST_INVALID", "备份清单 AI 契约不匹配"
        )
    database = manifest["database"]
    if (
        database["bytes"] != facts["source_bytes"]
        or database["sha256"] != facts["source_sha256"]
    ):
        raise BackupValidationError(
            "BACKUP_MANIFEST_INVALID", "备份清单数据库 hash 不匹配原始字节"
        )
    db_resources = {
        item["path"]: item for item in iter_registered_resources(source_db_path)
    }
    resources = manifest["resources"]
    if len(resources) != len(db_resources):
        raise BackupValidationError(
            "BACKUP_MANIFEST_INVALID", "备份清单资源数量不匹配"
        )
    seen: set[str] = set()
    total_bytes = 0
    for entry in resources:
        path = entry["path"]
        if path in seen:
            raise BackupValidationError(
                "BACKUP_MANIFEST_INVALID", "备份清单资源重复"
            )
        seen.add(path)
        db_entry = db_resources.get(path)
        if db_entry is None:
            raise BackupValidationError(
                "BACKUP_MANIFEST_INVALID", "备份清单含未登记资源"
            )
        for key in (
            "kind",
            "observation_id",
            "asset_id",
            "derivative_id",
        ):
            if entry.get(key) != db_entry.get(key):
                raise BackupValidationError(
                    "BACKUP_MANIFEST_INVALID", "备份清单资源身份不匹配"
                )
        target = resources_root.joinpath(*PurePosixPath(path).parts)
        try:
            target.relative_to(resources_root)
        except ValueError:
            raise BackupValidationError(
                "BACKUP_MANIFEST_INVALID", "备份资源路径越界"
            ) from None
        size, digest = _file_hash(
            target,
            limit=backup_format.MAX_RESOURCE_BYTES,
            cancel=cancel,
        )
        if entry["bytes"] != size or entry["sha256"] != digest:
            raise BackupValidationError(
                "BACKUP_MANIFEST_INVALID", "备份资源字节或 hash 不匹配"
            )
        if db_entry["sha256"] != digest:
            raise BackupValidationError(
                "BACKUP_MANIFEST_INVALID", "备份资源与数据库 hash 不匹配"
            )
        if (
            db_entry.get("byte_size") is not None
            and db_entry["byte_size"] != size
        ):
            raise BackupValidationError(
                "BACKUP_MANIFEST_INVALID", "备份资源与数据库大小不匹配"
            )
        image_entry = dict(db_entry)
        image_entry["bytes"] = entry["bytes"]
        image_entry["sha256"] = entry["sha256"]
        _validate_image_resource(
            target,
            resources_root=resources_root,
            entry=image_entry,
            cancel=cancel,
        )
        total_bytes += size
        if total_bytes > backup_format.MAX_EXPANDED_BYTES:
            raise BackupValidationError(
                "BACKUP_SIZE_INVALID", "备份展开体积超过上限"
            )
    if set(seen) != set(db_resources):
        raise BackupValidationError(
            "BACKUP_MANIFEST_INVALID", "备份清单漏登记资源"
        )
    counts = manifest["counts"]
    if (
        counts["resources"] != len(resources)
        or counts["resources_bytes"] != total_bytes
        or counts["database_bytes"] != facts["source_bytes"]
    ):
        raise BackupValidationError(
            "BACKUP_MANIFEST_INVALID", "备份清单计数不匹配"
        )
    return {"resources": len(resources), "resources_bytes": total_bytes}
