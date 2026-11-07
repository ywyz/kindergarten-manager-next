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
from datetime import date, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from alembic import command

from app.local import backup_format, backup_fs, observation_assets
from app.local.errors import LocalError, LocalWeeklyInvalid
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


_WEEKLY_MAX_CONTENT_BYTES = 1_048_576


def _weekly_canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _weekly_hash(value: Any) -> str:
    return hashlib.sha256(_weekly_canonical(value).encode("utf-8")).hexdigest()


def _weekly_json(value: Any, label: str) -> Any:
    if isinstance(value, (str, bytes, bytearray)):
        try:
            return json.loads(value)
        except (ValueError, UnicodeDecodeError) as exc:
            raise BackupValidationError(
                "BACKUP_DB_LOGICAL_INVALID", f"备份数据库周计划 JSON 损坏：{label}"
            ) from exc
    return value


def _weekly_require(condition: bool, label: str) -> None:
    if not condition:
        raise BackupValidationError(
            "BACKUP_DB_LOGICAL_INVALID", f"备份数据库周计划校验失败：{label}"
        )


def _weekly_content(
    value: Any, expected_hash: str, schema_version: int, label: str
) -> dict:
    from app.local import weekly_plan_content

    content = _weekly_json(value, label)
    try:
        content = weekly_plan_content.validate_content(
            content, expected_schema=schema_version
        )
        actual = weekly_plan_content.content_hash(content)
    except weekly_plan_content.WeeklyContentError as exc:
        raise BackupValidationError(
            "BACKUP_DB_LOGICAL_INVALID",
            f"备份数据库周计划内容不合法：{label}",
        ) from exc
    _weekly_require(actual == expected_hash, f"{label} content hash")
    _weekly_require(
        type(content.get("schema_version")) is int
        and content["schema_version"] == schema_version,
        f"{label} schema version",
    )
    _weekly_require(
        len(_weekly_canonical(content).encode("utf-8"))
        <= _WEEKLY_MAX_CONTENT_BYTES,
        f"{label} size",
    )
    return content


def _daily_contents(connection: sqlite3.Connection) -> dict[tuple[str, str], dict]:
    from app.services.daily_plan_content import (
        ContentValidationError,
        parse_adopted_content,
    )

    result: dict[tuple[str, str], dict] = {}
    rows = connection.execute(
        "SELECT c.daily_plan_id, c.id, c.version, c.adopted_content, "
        "p.creator_id, p.class_id, p.term_id, p.plan_date, p.deleted_at "
        "FROM local_daily_plan_contents c "
        "JOIN local_daily_plans p ON p.id = c.daily_plan_id"
    ).fetchall()
    for row in rows:
        try:
            adopted = parse_adopted_content(
                _weekly_json(row[3], f"daily content {row[1]}")
            ).model_dump(exclude_none=True)
        except (ContentValidationError, ValueError, TypeError) as exc:
            raise BackupValidationError(
                "BACKUP_DB_LOGICAL_INVALID", "备份数据库日计划内容损坏"
            ) from exc
        result[(row[0], row[1])] = {
            "version": row[2],
            "adopted": adopted,
            "hash": _weekly_hash(adopted),
            "profile_id": row[4],
            "class_id": row[5],
            "term_id": row[6],
            "plan_date": row[7],
        }
    return result


def _weekly_source_row(
    daily_contents: dict[tuple[str, str], dict],
    source: dict,
    *,
    plan: dict,
    day_date: str,
    label: str,
    check_text: bool,
) -> dict:
    row = daily_contents.get(
        (source.get("daily_plan_id"), source.get("content_id"))
    )
    _weekly_require(row is not None, f"{label} missing daily content")
    _weekly_require(row["version"] == source.get("content_version"), label)
    _weekly_require(row["hash"] == source.get("content_hash"), label)
    _weekly_require(
        row["profile_id"] == plan["profile_id"]
        and row["class_id"] == plan["class_id"]
        and row["term_id"] == plan["term_id"]
        and row["plan_date"] == day_date,
        f"{label} daily ownership/date",
    )
    adopted = row["adopted"]
    if check_text:
        talk = adopted.get("morning_talk") or {}
        activity = adopted.get("group_activity") or {}
        _weekly_require(
            (source.get("morning_talk_topic") or "") == (talk.get("topic") or "")
            and (source.get("group_activity_theme") or "")
            == (activity.get("theme") or ""),
            f"{label} deterministic text",
        )
    return adopted


def _weekly_game_name(group: dict, game_id: str) -> str | None:
    for game in group.get("games") or []:
        if game.get("game_id") == game_id:
            return game.get("name")
    return None


def _weekly_slot_source_date(
    slot: dict,
    daily_contents: dict[tuple[str, str], dict],
    week_dates: set[str],
) -> str | None:
    row = daily_contents.get(
        (slot.get("daily_plan_id"), slot.get("content_id"))
    )
    if row is None:
        return None
    day = row["plan_date"]
    return day if day in week_dates else None


def _weekly_validate_sources(
    content: dict,
    plan: dict,
    daily_contents: dict[tuple[str, str], dict],
) -> None:
    week_dates = {
        (date.fromisoformat(plan["anchor"]) + timedelta(days=offset)).isoformat()
        for offset in range(7)
    }
    manifest = content["source_manifest"]
    for item in manifest.get("sources") or []:
        if not isinstance(item, dict) or item.get("daily_plan_id") is None:
            continue
        _weekly_source_row(
            daily_contents,
            item,
            plan=plan,
            day_date=item["date"],
            label="manifest source",
            check_text=False,
        )
    for row in content["deterministic"]:
        source = row.get("source")
        if source is not None:
            _weekly_source_row(
                daily_contents,
                source,
                plan=plan,
                day_date=row["date"],
                label="deterministic source",
                check_text=True,
            )
    for key, slot in content["outdoor_game_slots"].items():
        if slot is None or slot.get("source_kind") != "daily_plan":
            continue
        source_date = _weekly_slot_source_date(slot, daily_contents, week_dates)
        _weekly_require(source_date is not None, f"outdoor slot {key} source date")
        adopted = _weekly_source_row(
            daily_contents,
            slot,
            plan=plan,
            day_date=source_date,
            label=f"outdoor slot {key}",
            check_text=False,
        )
        group = next(
            (
                item
                for item in adopted.get("morning_games") or []
                if item.get("group_id") == slot.get("group_id")
            ),
            None,
        )
        _weekly_require(group is not None, f"outdoor slot {key} group")
        name = _weekly_game_name(group, slot.get("game_id"))
        _weekly_require(name is not None, f"outdoor slot {key} game")
        _weekly_require(slot.get("name") == name, f"outdoor slot {key} text")
        for field in ("shared_objectives", "guidance_points", "focus_guidance"):
            _weekly_require(
                (slot.get(field) or "") == (group.get(field) or ""),
                f"outdoor slot {key} {field}",
            )
    focus = content.get("focus_area")
    if focus is not None and focus.get("source_kind") == "daily_plan":
        source_date = _weekly_slot_source_date(focus, daily_contents, week_dates)
        _weekly_require(source_date is not None, "focus area source date")
        adopted = _weekly_source_row(
            daily_contents,
            focus,
            plan=plan,
            day_date=source_date,
            label="focus area",
            check_text=False,
        )
        group = next(
            (
                item
                for item in adopted.get("post_group_games") or []
                if item.get("group_id") == focus.get("group_id")
            ),
            None,
        )
        _weekly_require(group is not None, "focus area group")
        name = _weekly_game_name(group, focus.get("game_id"))
        _weekly_require(name is not None, "focus area game")
        _weekly_require(focus.get("name") == name, "focus area text")
        _weekly_require(
            focus.get("context_kind") == group.get("context_kind"),
            "focus area context_kind",
        )
        for field in ("area", "objectives", "guidance", "support_strategy"):
            _weekly_require(
                (focus.get(field) or "") == (group.get(field) or ""),
                f"focus area {field}",
            )


def _weekly_validate_export_manifest(
    manifest: Any,
    *,
    contents: dict[tuple[str, str], dict],
    confirmation_rows: dict[tuple[str, str], dict],
) -> dict:
    from app.local import weekly_plan_snapshot

    try:
        manifest = weekly_plan_snapshot.validate_export_manifest(manifest)
    except LocalWeeklyInvalid as exc:
        raise BackupValidationError(
            "BACKUP_DB_LOGICAL_INVALID", "备份数据库导出 manifest 不合法"
        ) from exc
    for item in manifest["items"]:
        plan_id = item["weekly_plan_id"]
        draft_id = item["draft_id"]
        confirmation_id = item["confirmation_id"]
        row = confirmation_rows.get((plan_id, confirmation_id))
        snapshot = row.get("snapshot") if row else None
        if (
            row is None
            or row.get("version") != item["confirmation_version"]
            or row.get("hash") != item["confirmation_hash"]
            or snapshot is None
            or snapshot.get("draft_id") != draft_id
            or snapshot.get("draft_version") != item["draft_version"]
            or snapshot.get("content_hash") != item["content_hash"]
            or snapshot.get("weekly_plan_id") != plan_id
        ):
            raise BackupValidationError(
                "BACKUP_DB_LOGICAL_INVALID", "备份数据库导出确认引用不合法"
            )
        projection = {
            key: item[key]
            for key in weekly_plan_snapshot.SNAPSHOT_KEYS
        }
        if projection != snapshot:
            raise BackupValidationError(
                "BACKUP_DB_LOGICAL_INVALID", "备份数据库导出 item 快照投影不匹配"
            )
        content = contents.get((plan_id, draft_id))
        if content is None or content["hash"] != item["content_hash"]:
            raise BackupValidationError(
                "BACKUP_DB_LOGICAL_INVALID", "备份数据库导出草稿引用不合法"
            )
    return manifest


def _weekly_reconstruct_adoption(connection: sqlite3.Connection, plans: dict[str, dict],
                                 contents: dict[tuple[str, str], dict],
                                 candidates: dict[str, tuple], provenance: dict,
                                 origin_id: str, origin_version: int,
                                 target: str) -> None:
    from app.local import weekly_ai_contracts, weekly_ai_inputs
    from app.local import weekly_plan_content
    candidate = candidates.get(provenance.get("candidate_id"))
    _weekly_require(candidate is not None, "weekly origin candidate row")
    _weekly_require(candidate[7] == provenance.get("input_id"),
                    "weekly origin candidate input")
    _weekly_require(candidate[6] == provenance.get("execution_id"),
                    "weekly origin candidate execution")
    task = connection.execute(
        "SELECT id, profile_id, source_kind, source_id, weekly_plan_id, "
        "input_id, task_type FROM local_ai_tasks WHERE id=?", (candidate[5],)
    ).fetchone()
    execution = connection.execute(
        "SELECT task_id, profile_id, source_kind, source_id, weekly_plan_id, "
        "input_id, contract_version FROM local_ai_executions WHERE id=?",
        (candidate[6],),
    ).fetchone()
    _weekly_require(
        task is not None and task[1] == provenance.get("adopter_profile_id")
        and task[2] == "weekly_plan" and task[4] == plans[candidate[4]]["id"]
        and task[5] == candidate[7] and task[6] == candidate[8],
        "weekly origin task binding",
    )
    _weekly_require(
        execution is not None and execution[0] == candidate[5]
        and execution[1] == provenance.get("adopter_profile_id")
        and execution[2] == "weekly_plan" and execution[4] == plans[candidate[4]]["id"]
        and execution[5] == candidate[7]
        and execution[6] == candidate[12] == provenance.get("contract_version"),
        "weekly origin execution binding",
    )
    input_row = connection.execute(
        "SELECT profile_id, source_kind, source_id, weekly_plan_id, "
        "weekly_draft_id, source_revision, dependency_hash, task_type, "
        "dependencies_json FROM local_ai_inputs WHERE id=?", (candidate[7],)
    ).fetchone()
    _weekly_require(
        input_row is not None and input_row[0] == provenance.get("adopter_profile_id")
        and input_row[1] == "weekly_plan" and input_row[2] == plans[candidate[4]]["id"]
        and input_row[3] == plans[candidate[4]]["id"]
        and input_row[7] == candidate[8]
        and input_row[6] == provenance.get("dependency_hash"),
        "weekly origin actual input binding",
    )
    _weekly_require(
        weekly_ai_contracts.target_for_task(candidate[8]) == target,
        "weekly origin candidate target",
    )
    deps = _weekly_json(input_row[8], "weekly origin dependencies")
    business = weekly_ai_inputs.build_business_dependency_view(deps)
    basis = {key: business[key] for key in (
        "schema_version", "target", "grade", "theme", "manual_text",
        "daily_sources", "selected", "config", "calendar")}
    _weekly_require(basis["target"] == target, "weekly origin basis target")
    _weekly_require(_weekly_canonical(basis) == _weekly_canonical(provenance["basis"]),
                    "weekly origin actual basis")
    manifest = weekly_ai_inputs.server_manifest_from_dependencies(deps)
    try:
        raw = _weekly_json(candidate[10], "weekly origin candidate value")
        candidate_value = weekly_ai_contracts.validate_stored_candidate(
            candidate[8], raw, server_manifest=manifest
        )
    except Exception as exc:  # noqa: BLE001 - pure candidate refusal
        raise BackupValidationError(
            "BACKUP_DB_LOGICAL_INVALID", "备份数据库周计划采用候选原点无法规范化"
        ) from exc
    meta = {key: provenance[key] for key in (
        "candidate_id", "candidate_hash", "input_id", "execution_id",
        "contract_version", "dependency_hash", "adopter_profile_id",
        "adopted_draft_id", "adopted_draft_version", "adopted_at")}
    before = next(
        (item for (plan_key, _content_key), item in contents.items()
         if plan_key == plans[candidate[4]]["id"]
         and item["version"] == origin_version - 1), None)
    _weekly_require(before is not None, "weekly origin before draft")
    ai_ids = None
    if target == "games":
        ai_ids = {}
        value = provenance["adopted_value"]
        for slot_key in ("collective_1", "collective_2", "free_choice_1"):
            item = (value.get("outdoor_game_slots") or {}).get(slot_key)
            if isinstance(item, dict) and item.get("source_kind") == "ai_supplement":
                ai_ids[slot_key] = item["ai_item_id"]
        focus = value.get("focus_area")
        if isinstance(focus, dict) and focus.get("source_kind") == "ai_supplement":
            ai_ids["focus_area"] = focus["ai_item_id"]
    try:
        expected = weekly_plan_content.apply_weekly_ai_adoption(
            before["content"], target=target, candidate_value=candidate_value,
            adoption=meta, basis=basis,
            server_manifest=manifest if target == "materials" else None,
            ai_item_ids=ai_ids if target == "games" else None,
        )
    except Exception as exc:  # noqa: BLE001 - pure reconstruction refusal
        raise BackupValidationError(
            "BACKUP_DB_LOGICAL_INVALID", "备份数据库周计划采用目标无法重建"
        ) from exc
    origin_content = contents[(plans[candidate[4]]["id"], origin_id)]["content"]
    if target == "games":
        _weekly_require(
            expected["outdoor_game_slots"] == origin_content["outdoor_game_slots"]
            and expected["focus_area"] == origin_content["focus_area"]
            and expected["ai_provenance"]["games"]
            == origin_content["ai_provenance"]["games"]
            and expected["ai_provenance"]["games"].get("manual_edited") is False,
            "weekly origin games value",
        )
    elif target == "materials":
        _weekly_require(
            expected["materials"] == origin_content["materials"]
            and expected["materials_provenance"]
            == origin_content["materials_provenance"]
            and expected["materials_provenance"].get("edited") is False,
            "weekly origin materials value",
        )
    else:
        _weekly_require(
            expected["weekly_columns"][target]
            == origin_content["weekly_columns"][target]
            and expected["ai_provenance"][target]
            == origin_content["ai_provenance"][target]
            and expected["ai_provenance"][target].get("manual_edited") is False,
            "weekly origin column value",
        )
    expected_hash = weekly_ai_inputs.target_hash(expected, target)
    _weekly_require(
        weekly_ai_inputs.target_hash(origin_content, target) == expected_hash,
        "weekly origin target hash",
    )

def _weekly_ai_origin_chain(connection: sqlite3.Connection, plan: dict,
                            candidates: dict[str, tuple], provenance: dict,
                            origin_id: str, origin_version: int) -> None:
    profile_id = plan["profile_id"]
    candidate = candidates.get(provenance.get("candidate_id"))
    _weekly_require(candidate is not None and candidate[1] == profile_id
                    and candidate[4] == plan["id"], "weekly origin candidate")
    _weekly_require(candidate[9] == provenance.get("candidate_hash"),
                    "weekly origin candidate hash")
    input_row = connection.execute(
        "SELECT profile_id, source_kind, source_id, weekly_plan_id, "
        "weekly_draft_id, source_revision, dependency_hash, task_type "
        "FROM local_ai_inputs WHERE id=?", (provenance.get("input_id"),)
    ).fetchone()
    _weekly_require(
        input_row is not None and input_row[0] == profile_id
        and input_row[1] == "weekly_plan" and input_row[2] == plan["id"]
        and input_row[3] == plan["id"]
        and input_row[6] == provenance.get("dependency_hash"),
        "weekly origin input",
    )
    input_draft = connection.execute(
        "SELECT version FROM local_weekly_plan_contents "
        "WHERE weekly_plan_id=? AND id=?", (plan["id"], input_row[4])
    ).fetchone()
    _weekly_require(input_draft is not None and input_draft[0] == input_row[5],
                    "weekly origin input draft")
    execution = connection.execute(
        "SELECT task_id, profile_id, source_kind, source_id, weekly_plan_id, "
        "input_id, contract_version FROM local_ai_executions WHERE id=?",
        (provenance.get("execution_id"),),
    ).fetchone()
    _weekly_require(
        execution is not None and execution[1] == profile_id
        and execution[2] == "weekly_plan" and execution[3] == plan["id"]
        and execution[4] == plan["id"] and execution[5] == provenance.get("input_id")
        and execution[6] == provenance.get("contract_version"),
        "weekly origin execution",
    )
    _weekly_require(
        provenance.get("adopted_draft_id") == origin_id
        and provenance.get("adopted_draft_version") == origin_version
        and provenance.get("adopter_profile_id") == profile_id,
        "weekly origin draft/owner",
    )

def _weekly_ai_provenance(connection: sqlite3.Connection, plans: dict[str, dict],
                          contents: dict[tuple[str, str], dict],
                          candidates: dict[str, tuple]) -> None:
    for (plan_id, content_id), item in contents.items():
        body = item["content"]
        if body.get("schema_version") != 2:
            continue
        for target, key in (
            ("games", "games"), ("key_week_focus", "key_week_focus"),
            ("environment_setup", "environment_setup"),
            ("habit_culture", "habit_culture"),
            ("home_cooperation", "home_cooperation"),
        ):
            provenance = (body.get("ai_provenance") or {}).get(target)
            if provenance is None:
                continue
            origin_id = provenance.get("adopted_draft_id")
            origin = contents.get((plan_id, origin_id)) if isinstance(origin_id, str) else None
            _weekly_require(
                origin is not None
                and origin["version"] == provenance.get("adopted_draft_version"),
                f"weekly provenance draft {target}",
            )
            origin_value = (origin["content"].get("ai_provenance") or {}).get(target)
            _weekly_require(origin_value is not None,
                            f"weekly provenance origin {target}")
            for immutable_key in _ADOPTION_IMMUTABLE:
                _weekly_require(provenance.get(immutable_key) == origin_value.get(immutable_key),
                                f"weekly provenance immutable {target}.{immutable_key}")
            _weekly_ai_origin_chain(connection, plans[plan_id], candidates,
                                    origin_value, origin_id,
                                    provenance.get("adopted_draft_version"))
            _weekly_reconstruct_adoption(
                connection, plans, contents, candidates, origin_value,
                origin_id, provenance.get("adopted_draft_version"), target
            )
            candidate = candidates.get(provenance.get("candidate_id"))
            _weekly_require(
                candidate is not None and candidate[1] == plans[plan_id]["profile_id"]
                and candidate[4] == plan_id, f"weekly provenance candidate {target}",
            )
            adoption = connection.execute(
                "SELECT 1 FROM local_weekly_plan_ai_adoption "
                "WHERE draft_id=? AND target_key=? AND candidate_id=?",
                (origin_id, target, provenance.get("candidate_id")),
            ).fetchone()
            _weekly_require(adoption is not None, f"weekly provenance adoption {target}")
        materials = body.get("materials_provenance")
        if materials is not None:
            origin_id = materials.get("adopted_draft_id")
            origin = contents.get((plan_id, origin_id)) if isinstance(origin_id, str) else None
            _weekly_require(
                origin is not None
                and origin["version"] == materials.get("adopted_draft_version"),
                "weekly materials provenance draft",
            )
            origin_materials = origin["content"].get("materials_provenance")
            _weekly_require(origin_materials is not None,
                            "weekly materials provenance origin")
            origin_candidate = candidates.get(origin_materials.get("candidate_id"))
            _weekly_require(origin_candidate is not None,
                            "weekly materials candidate")
            material_input = connection.execute(
                "SELECT dependencies_json FROM local_ai_inputs WHERE id=?",
                (origin_materials.get("input_id"),),
            ).fetchone()
            _weekly_require(material_input is not None, "weekly materials input")
            from app.local import weekly_ai_inputs, weekly_materials
            material_raw = _weekly_json(
                origin_candidate[10], "weekly materials candidate value"
            )
            material_deps = _weekly_json(
                material_input[0], "weekly materials dependencies"
            )
            material_manifest = weekly_ai_inputs.server_manifest_from_dependencies(
                material_deps
            )
            try:
                material_items = weekly_materials.materialize_materials_items(
                    material_raw.get("items"), server_manifest=material_manifest
                )
            except Exception as exc:  # noqa: BLE001 - pure evidence refusal
                raise BackupValidationError(
                    "BACKUP_DB_LOGICAL_INVALID", "备份数据库材料证据无法规范化"
                ) from exc
            _weekly_require(
                _weekly_canonical(material_items)
                == _weekly_canonical(origin_materials.get("items")),
                "weekly materials candidate evidence",
            )
            for key in _MATERIAL_IMMUTABLE:
                _weekly_require(materials.get(key) == origin_materials.get(key),
                                f"weekly materials provenance immutable {key}")
            _weekly_ai_origin_chain(connection, plans[plan_id], candidates,
                                    origin_materials, origin_id,
                                    materials.get("adopted_draft_version"))
            _weekly_reconstruct_adoption(
                connection, plans, contents, candidates, origin_materials,
                origin_id, materials.get("adopted_draft_version"), "materials"
            )
            candidate = candidates.get(materials.get("candidate_id"))
            _weekly_require(
                candidate is not None and candidate[1] == plans[plan_id]["profile_id"]
                and candidate[4] == plan_id, "weekly materials provenance candidate",
            )
            adoption = connection.execute(
                "SELECT 1 FROM local_weekly_plan_ai_adoption "
                "WHERE draft_id=? AND target_key='materials' AND candidate_id=?",
                (origin_id, materials.get("candidate_id")),
            ).fetchone()
            _weekly_require(adoption is not None, "weekly materials provenance adoption")

def _weekly_ai_adoptions(connection: sqlite3.Connection, plans: dict[str, dict],
                         contents: dict[tuple[str, str], dict],
                         candidates: dict[str, tuple]) -> list[tuple]:
    rows = connection.execute(
        "SELECT profile_id, source_kind, weekly_plan_id, draft_id, draft_version, "
        "candidate_id, target_key, before_hash, after_hash, operation_id "
        "FROM local_weekly_plan_ai_adoption"
    ).fetchall()
    for profile_id, source_kind, plan_id, draft_id, draft_version, candidate_id, \
            target_key, before_hash, after_hash, operation_id in rows:
        _weekly_require(
            source_kind == "weekly_plan" and plan_id in plans
            and plans[plan_id]["profile_id"] == profile_id,
            "weekly adoption plan",
        )
        content = contents.get((plan_id, draft_id))
        _weekly_require(content is not None and content["version"] == draft_version,
                        "weekly adoption draft")
        candidate = candidates.get(candidate_id)
        _weekly_require(
            candidate is not None and candidate[1] == profile_id
            and candidate[4] == plan_id, "weekly adoption candidate",
        )
        operation = connection.execute(
            "SELECT operation_kind, result_json, request_id FROM local_ai_operations "
            "WHERE id=? AND profile_id=?", (operation_id, profile_id)
        ).fetchone()
        _weekly_require(operation is not None and operation[0] == "weekly_ai_adopt",
                        "weekly adoption operation")
        _weekly_require(target_key in _WEEKLY_AI_TARGETS, "weekly adoption target")
        _weekly_require(
            isinstance(before_hash, str) and len(before_hash) == 64
            and isinstance(after_hash, str) and len(after_hash) == 64,
            "weekly adoption hash",
        )
        try:
            from app.local import weekly_ai_inputs
            expected_after = weekly_ai_inputs.target_hash(
                content["content"], target_key
            )
            previous = [
                item for (plan_key, _content_key), item in contents.items()
                if plan_key == plan_id and item["version"] < draft_version
            ]
            expected_before = (
                weekly_ai_inputs.target_hash(max(
                    previous, key=lambda item: item["version"]
                )["content"], target_key)
                if previous else None
            )
            result = _weekly_json(operation[1], "weekly adoption operation result")
        except Exception as exc:  # noqa: BLE001 - pure target refusal
            raise BackupValidationError(
                "BACKUP_DB_LOGICAL_INVALID", "备份数据库周计划采用无法规范化"
            ) from exc
        _weekly_require(expected_after == after_hash, "weekly adoption after hash")
        if expected_before is not None:
            _weekly_require(expected_before == before_hash,
                            "weekly adoption before hash")
        _weekly_require(isinstance(result, dict), "weekly adoption result")
        _weekly_require(result.get("operation_id") == operation_id,
                        "weekly adoption result operation")
        _weekly_require(result.get("request_id") == operation[2],
                        "weekly adoption result request")
        _weekly_require(result.get("status") == "committed",
                        "weekly adoption result status")
        _weekly_require(result.get("weekly_plan_id") == plan_id,
                        "weekly adoption result plan")
        draft = result.get("draft")
        _weekly_require(
            isinstance(draft, dict) and draft.get("id") == draft_id
            and draft.get("version") == draft_version
            and draft.get("content_hash") == content["hash"],
            "weekly adoption result draft",
        )
        selections = result.get("selections")
        _weekly_require(isinstance(selections, list), "weekly adoption selections")
        _weekly_require(
            any(isinstance(item, dict) and item.get("target") == target_key
                and item.get("candidate_id") == candidate_id for item in selections),
            "weekly adoption result selection",
        )
    return rows

def _weekly_ai_candidates(connection: sqlite3.Connection, plans: dict[str, dict],
                          tasks: dict[str, tuple],
                          executions: dict[str, tuple]) -> dict[str, tuple]:
    candidates = {
        row[0]: row
        for row in connection.execute(
            "SELECT id, profile_id, source_kind, source_id, weekly_plan_id, "
            "task_id, execution_id, input_id, task_type, candidate_hash, "
            "raw_candidate_json, schema_version, contract_version "
            "FROM local_ai_candidates WHERE source_kind='weekly_plan'"
        ).fetchall()
    }
    for candidate_id, profile_id, source_kind, source_id, plan_id, task_id, \
            execution_id, input_id, task_type, candidate_hash, raw_candidate_json, \
            schema_version, contract_version in candidates.values():
        _weekly_require(
            source_kind == "weekly_plan" and source_id == plan_id
            and plan_id in plans and plans[plan_id]["profile_id"] == profile_id,
            "weekly candidate plan",
        )
        _weekly_require(
            task_id in tasks and execution_id in executions,
            "weekly candidate chain",
        )
        _weekly_require(
            tasks[task_id][1] == profile_id and tasks[task_id][4] == plan_id
            and executions[execution_id][2] == profile_id
            and executions[execution_id][4] == plan_id
            and executions[execution_id][6] == tasks[task_id][5],
            "weekly candidate identity",
        )
        _weekly_require(isinstance(candidate_hash, str) and len(candidate_hash) == 64,
                        "weekly candidate hash")
        _weekly_require(schema_version == 1, "weekly candidate schema")
        try:
            from app.local import weekly_ai_contracts
            contract_ok = weekly_ai_contracts.supports_prompt_contract(
                task_type, contract_version)
        except Exception:  # noqa: BLE001 - unknown/invalid contract is unsafe
            contract_ok = False
        _weekly_require(contract_ok, "weekly candidate contract")
        try:
            from app.local import weekly_ai_contracts, weekly_ai_inputs
            input_row = connection.execute(
                "SELECT dependencies_json FROM local_ai_inputs WHERE id=?",
                (input_id,),
            ).fetchone()
            _weekly_require(input_row is not None, "weekly candidate input")
            dependencies = _weekly_json(input_row[0], "weekly candidate dependencies")
            manifest = weekly_ai_inputs.server_manifest_from_dependencies(
                dependencies
            )
            raw_value = _weekly_json(raw_candidate_json, "weekly candidate value")
            validated = weekly_ai_contracts.validate_stored_candidate(
                task_type, raw_value, server_manifest=manifest
            )
            expected = weekly_ai_contracts.candidate_hash(validated)
        except Exception as exc:  # noqa: BLE001 - pure contract refusal
            raise BackupValidationError(
                "BACKUP_DB_LOGICAL_INVALID", "备份数据库周计划候选无法规范化"
            ) from exc
        _weekly_require(_weekly_canonical(validated) == _weekly_canonical(raw_value),
                        "weekly candidate normalized value")
        _weekly_require(expected == candidate_hash, "weekly candidate normalized hash")
    return candidates

def _weekly_ai_executions(connection: sqlite3.Connection, plans: dict[str, dict],
                          tasks: dict[str, tuple]) -> dict[str, tuple]:
    executions = {
        row[0]: row
        for row in connection.execute(
            "SELECT id, task_id, profile_id, source_kind, source_id, weekly_plan_id, "
            "input_id, task_type FROM local_ai_executions "
            "WHERE source_kind='weekly_plan'"
        ).fetchall()
    }
    for execution_id, task_id, profile_id, source_kind, source_id, plan_id, \
            input_id, task_type in executions.values():
        _weekly_require(
            source_kind == "weekly_plan" and source_id == plan_id
            and plan_id in plans and plans[plan_id]["profile_id"] == profile_id
            and task_id in tasks and input_id == tasks[task_id][5],
            "weekly execution chain",
        )
        _weekly_require(
            tasks[task_id][1] == profile_id and tasks[task_id][4] == plan_id
            and tasks[task_id][6] == task_type,
            "weekly execution task identity",
        )
    for task_id, task in tasks.items():
        pointer = task[7] if len(task) > 7 else None
        if pointer is not None:
            execution = executions.get(pointer)
            _weekly_require(execution is not None, "weekly task execution")
            _weekly_require(
                execution[1] == task_id and execution[2] == task[1]
                and execution[4] == task[4] and execution[6] == task[5],
                "weekly task execution identity",
            )
    return executions

def _weekly_ai_inputs(connection: sqlite3.Connection, plans: dict[str, dict],
                      contents: dict[tuple[str, str], dict]) -> dict[str, tuple]:
    tasks = {
        row[0]: row
        for row in connection.execute(
            "SELECT id, profile_id, source_kind, source_id, weekly_plan_id, "
            "input_id, task_type, current_execution_id FROM local_ai_tasks "
            "WHERE source_kind='weekly_plan'"
        ).fetchall()
    }
    inputs = {
        row[0]: row
        for row in connection.execute(
            "SELECT id, profile_id, source_kind, source_id, weekly_plan_id, "
            "weekly_draft_id, source_revision, create_operation_id, task_type, "
            "payload_json, dependencies_json, dependency_hash, target_hashes_json, "
            "input_schema_version FROM local_ai_inputs WHERE source_kind='weekly_plan'"
        ).fetchall()
    }
    for input_id, profile_id, source_kind, source_id, plan_id, draft_id, \
            source_revision, operation_id, task_type, payload_json, \
            dependencies_json, dependency_hash, target_hashes_json, input_schema_version \
            in inputs.values():
        _weekly_require(source_kind == "weekly_plan", "weekly input source")
        _weekly_require(source_id == plan_id and plan_id in plans, "weekly input plan")
        plan = plans.get(plan_id)
        _weekly_require(plan is not None and plan["profile_id"] == profile_id,
                        "weekly input profile")
        content = contents.get((plan_id, draft_id))
        _weekly_require(content is not None and content["version"] == source_revision,
                        "weekly input draft")
        _weekly_require(task_type in _WEEKLY_AI_TASKS, "weekly input task type")
        _weekly_require(input_schema_version == 1, "weekly input schema")
        operation = connection.execute(
            "SELECT operation_kind FROM local_ai_operations "
            "WHERE id=? AND profile_id=?", (operation_id, profile_id)
        ).fetchone()
        _weekly_require(operation is not None and operation[0] in _WEEKLY_AI_CREATE_KINDS,
                        "weekly input operation")
        try:
            from app.local import weekly_ai_contracts, weekly_ai_inputs
            dependencies = _weekly_json(dependencies_json, "weekly input dependencies")
            payload = _weekly_json(payload_json, "weekly input payload")
            target_hashes = _weekly_json(target_hashes_json, "weekly target hashes")
            standby = weekly_ai_inputs.build_business_dependency_view(dependencies)
            expected_dependency = weekly_ai_inputs.dependency_hash(dependencies)
            expected_manifest = weekly_ai_inputs.server_manifest_from_dependencies(
                dependencies
            )
            target = weekly_ai_contracts.target_for_task(task_type)
            expected_target = weekly_ai_inputs.target_hash(content["content"], target)
            plan_identity = {
                "weekly_plan_id": plan_id,
                "draft_id": draft_id,
                "draft_version": source_revision,
                "content_hash": content["hash"],
                "profile_id": plan["profile_id"],
                "class_id": plan["class_id"],
                "term_id": plan["term_id"],
                "week_anchor_date": plan["anchor"],
                "week_number": plan["week_number"],
            }
            projected = weekly_ai_inputs.validate_stored_weekly_input(
                task_type, payload, dependencies, content["content"],
                plan_identity=plan_identity,
            )
        except Exception as exc:  # noqa: BLE001 - pure contract refusal
            raise BackupValidationError(
                "BACKUP_DB_LOGICAL_INVALID", "备份数据库周计划输入无法规范化"
            ) from exc
        _weekly_require(isinstance(standby, dict), "weekly input dependencies")
        _weekly_require(expected_dependency == dependency_hash, "weekly input hash")
        _weekly_require(isinstance(expected_manifest, dict), "weekly input manifest")
        _weekly_require(isinstance(payload, dict), "weekly input payload")
        _weekly_require(
            isinstance(target_hashes, dict)
            and set(target_hashes) == {target}
            and target_hashes[target] == expected_target,
            "weekly input target hashes",
        )
        _weekly_require(projected.dependency_hash == dependency_hash,
                        "weekly input stored hash")
        _weekly_require(projected.target_hashes == target_hashes,
                        "weekly input stored target hashes")
        _weekly_require(_weekly_canonical(projected.payload) == _weekly_canonical(payload),
                        "weekly input stored payload")
        linked = [task for task in tasks.values() if task[5] == input_id]
        _weekly_require(bool(linked), "weekly input task")
        for task in linked:
            _weekly_require(
                task[1] == profile_id and task[2] == "weekly_plan"
                and task[3] == plan_id and task[4] == plan_id
                and task[6] == task_type, "weekly task identity",
            )
    return tasks


def _listening_ai_chain(connection: sqlite3.Connection) -> None:
    """Validate typed listening AI source, frozen evidence, candidates and ledger."""
    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "local_listening_ai_adoption" not in tables:
        return
    from app.local import listening_ai_contracts, listening_templates
    from app.local.prompt_bundles import canonical_json

    def digest(value: Any) -> str:
        return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()

    def require(condition: Any, label: str) -> None:
        if not condition:
            raise BackupValidationError(
                "BACKUP_DB_LOGICAL_INVALID", f"备份数据库{label}校验失败"
            )

    input_rows = connection.execute(
        "SELECT id, profile_id, source_id, listening_record_id, listening_domain, "
        "listening_group_id, task_type, input_schema_version, payload_json, "
        "dependencies_json, dependency_hash, target_hashes_json, create_operation_id "
        "FROM local_ai_inputs WHERE source_kind='one_to_one_listening'"
    ).fetchall()
    inputs = {row[0]: row for row in input_rows}
    for row in input_rows:
        require(
            row[2] == row[3]
            and (
                (row[6] == "listening_note_draft" and row[5] is not None)
                or (row[6] == "listening_domain_evaluate" and row[5] is None)
            ),
            "倾听输入归属",
        )
        try:
            payload = json.loads(row[8])
            deps = json.loads(row[9])
            targets = json.loads(row[11])
        except (TypeError, ValueError):
            require(False, "倾听输入 JSON")
        try:
            listening_ai_contracts.validate_input(row[6], payload)
        except Exception:
            require(False, "倾听输入合同")
        require(
            isinstance(deps, dict)
            and deps.get("wire_schema_version") == 1
            and deps.get("record_id") == row[3]
            and deps.get("domain") == row[4]
            and deps.get("group_id") == row[5]
            and isinstance(targets, dict)
            and isinstance(row[10], str)
            and len(row[10]) == 64,
            "倾听输入依赖",
        )
        photos = deps.get("photos")
        require(isinstance(photos, list), "倾听输入图片")
        require(
            len(photos) <= (1 if row[6] == "listening_note_draft" else 3),
            "倾听输入图片数",
        )
        expected_dep = digest(
            {
                "payload": payload,
                "photos": [
                    {
                        "group_id": item.get("group_id"),
                        "position": item.get("position"),
                        "work_hash": item.get("work_hash"),
                    }
                    for item in photos
                ],
            }
        )
        require(expected_dep == row[10], "倾听依赖散列")
        if row[5] is not None:
            group = connection.execute(
                "SELECT record_id, domain, position FROM local_listening_photo_groups "
                "WHERE id=?",
                (row[5],),
            ).fetchone()
            require(
                group is not None
                and group[0] == row[3]
                and group[1] == row[4]
                and group[2] == payload.get("group_position"),
                "倾听输入小组归属",
            )
        for item in photos:
            require(
                isinstance(item, dict)
                and isinstance(item.get("asset_id"), str)
                and isinstance(item.get("source_hash"), str)
                and (row[5] is None or item.get("group_id") == row[5]),
                "倾听输入图片归属",
            )
            asset = connection.execute(
                "SELECT record_id, content_hash FROM local_listening_assets WHERE id=?",
                (item.get("asset_id"),),
            ).fetchone()
            require(
                asset is not None
                and asset[0] == row[3]
                and asset[1] == item.get("source_hash"),
                "倾听历史图片散列",
            )
        try:
            template = listening_templates.get_template(
                str(payload.get("grade")), row[4], str(payload.get("template_version"))
            )
        except Exception:
            require(False, "倾听模板")
        require(template.sha256 == payload.get("template_sha256"), "倾听模板散列")
        item_ids = [item.item_id for item in template.items]
        expected_targets = (
            {"listening_text"}
            if row[6] == "listening_note_draft"
            else {"overall_evaluation", "support_strategy", *item_ids}
        )
        require(
            set(targets) == expected_targets
            and all(isinstance(value, str) and len(value) == 64 for value in targets.values()),
            "倾听目标散列",
        )
        if row[6] == "listening_domain_evaluate":
            require(
                [item.get("item_id") for item in payload.get("items") or []]
                == item_ids,
                "倾听领域项目集",
            )
        wire_photos = (
            [payload.get("photo")]
            if row[6] == "listening_note_draft"
            else [group.get("photo") for group in payload.get("groups") or []]
        )
        require(
            sorted(item.get("work_hash") for item in wire_photos if item is not None)
            == sorted(item.get("work_hash") for item in photos),
            "倾听输入图片散列",
        )
    tasks = {
        row[0]: row
        for row in connection.execute(
            "SELECT id, profile_id, source_id, listening_record_id, listening_domain, "
            "listening_group_id, input_id, task_type, status, current_execution_id "
            "FROM local_ai_tasks WHERE source_kind='one_to_one_listening'"
        ).fetchall()
    }
    for row in tasks.values():
        inp = inputs.get(row[6])
        require(
            inp is not None
            and inp[1] == row[1]
            and inp[2] == row[2] == row[3]
            and inp[4] == row[4]
            and inp[5] == row[5]
            and inp[6] == row[7],
            "倾听任务输入",
        )
    executions = {
        row[0]: row
        for row in connection.execute(
            "SELECT id, task_id, profile_id, source_id, listening_record_id, "
            "listening_domain, listening_group_id, input_id, task_type, generation, "
            "state, contract_version, default_revision, personal_revision "
            "FROM local_ai_executions WHERE source_kind='one_to_one_listening'"
        ).fetchall()
    }
    for row in executions.values():
        task = tasks.get(row[1])
        require(
            task is not None
            and task[1] == row[2]
            and task[2] == row[3] == row[4]
            and task[4] == row[5]
            and task[5] == row[6]
            and task[6] == row[7]
            and task[7] == row[8],
            "倾听执行归属",
        )
    candidates = {
        row[0]: row
        for row in connection.execute(
            "SELECT id, profile_id, execution_id, task_id, source_id, "
            "listening_record_id, listening_domain, listening_group_id, input_id, "
            "task_type, contract_version, raw_candidate_json, candidate_hash "
            "FROM local_ai_candidates WHERE source_kind='one_to_one_listening'"
        ).fetchall()
    }
    for row in candidates.values():
        task = tasks.get(row[3])
        execution = executions.get(row[2])
        require(
            task is not None
            and execution is not None
            and task[1] == row[1]
            and task[2] == row[4] == row[5]
            and task[4] == row[6]
            and task[5] == row[7]
            and task[6] == row[8]
            and task[7] == row[9],
            "倾听候选归属",
        )
        try:
            raw = json.loads(row[11])
            validated = listening_ai_contracts.validate_candidate(row[9], raw)
        except Exception:
            require(False, "倾听候选合同")
        require(digest(raw) == row[12], "倾听候选散列")
        inp = inputs.get(row[8])
        if row[9] == "listening_domain_evaluate":
            payload = json.loads(inp[8])
            expected_ids = [item.get("item_id") for item in payload.get("items") or []]
            actual_ids = [item.get("item_id") for item in validated.get("items") or []]
            require(
                len(actual_ids) == len(set(actual_ids))
                and set(actual_ids) == set(expected_ids)
                and len(actual_ids) == len(expected_ids),
                "倾听候选项目集",
            )
    adoption_rows = connection.execute(
        "SELECT id, profile_id, record_id, domain, group_id, scope_key, target_key, "
        "candidate_id, input_id, before_hash, after_hash, revision_before, "
        "revision_after, operation_id FROM local_listening_ai_adoption "
        "ORDER BY record_id, domain, scope_key, target_key, revision_after"
    ).fetchall()
    by_target: dict[tuple[str, str, str, str], list[Any]] = {}
    for row in adoption_rows:
        candidate = candidates.get(row[7])
        require(
            candidate is not None
            and candidate[1] == row[1]
            and candidate[4] == row[2]
            and candidate[5] == row[2]
            and candidate[6] == row[3]
            and candidate[7] == row[4]
            and candidate[8] == row[8]
            and len(row[9]) == 64
            and len(row[10]) == 64
            and type(row[11]) is int
            and type(row[12]) is int
            and row[11] >= 1
            and row[12] >= row[11]
            and row[5] == (row[4] if row[4] is not None else "__domain__"),
            "倾听采用归属",
        )
        operation = connection.execute(
            "SELECT operation_kind, result_json FROM local_ai_operations "
            "WHERE profile_id=? AND id=?",
            (row[1], row[13]),
        ).fetchone()
        require(operation is not None, "倾听采用操作")
        require(operation[0] == "listening_ai_adopt", "倾听采用操作类型")
        try:
            result = json.loads(operation[1])
        except (TypeError, ValueError):
            require(False, "倾听采用回执 JSON")
        require(
            result.get("listening_record_id") == row[2]
            and result.get("domain") == row[3]
            and result.get("group_id") == row[4]
            and result.get("revision_after") == row[12],
            "倾听采用回执绑定",
        )
        adopted_values = {
            str(item.get("target")): item for item in result.get("adopted") or []
        }
        require(row[6] in adopted_values, "倾听采用目标回执")
        value = adopted_values[row[6]]
        expected_hash = listening_ai_contracts.value_hash(
            value.get("value") if "value" in value else value.get("stars")
        )
        require(expected_hash == row[10], "倾听采用值散列")
        by_target.setdefault((row[2], row[3], row[5], row[6]), []).append(row)
    for rows in by_target.values():
        rows.sort(key=lambda item: item[12])
        input_row = inputs.get(rows[0][8])
        target_hashes = json.loads(input_row[11])
        require(
            rows[0][9] == target_hashes.get(rows[0][6]),
            "倾听采用前向链",
        )
        for previous, current in zip(rows, rows[1:]):
            require(current[9] == previous[10], "倾听采用后向链")

def _weekly_ai_chain(connection: sqlite3.Connection, plans: dict[str, dict],
                     contents: dict[tuple[str, str], dict]) -> None:
    tables = {
        str(row[0]) for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "local_weekly_plan_ai_adoption" not in tables:
        return
    tasks = _weekly_ai_inputs(connection, plans, contents)
    executions = _weekly_ai_executions(connection, plans, tasks)
    candidates = _weekly_ai_candidates(connection, plans, tasks, executions)
    _weekly_ai_adoptions(connection, plans, contents, candidates)
    _weekly_ai_provenance(connection, plans, contents, candidates)

_ADOPTION_IMMUTABLE = (
    "candidate_id", "candidate_hash", "input_id", "execution_id",
    "contract_version", "dependency_hash", "adopted_draft_id",
    "adopted_draft_version", "adopter_profile_id", "adopted_at",
    "adopted_value", "adopted_value_hash", "basis",
)
_MATERIAL_IMMUTABLE = (
    "candidate_id", "candidate_hash", "input_id", "execution_id",
    "contract_version", "dependency_hash", "basis", "basis_hash", "items",
    "original_text", "adopter_profile_id", "adopted_draft_id",
    "adopted_draft_version", "adopted_at",
)
_WEEKLY_AI_TASKS = (
    "weekly_games_select", "weekly_key_week_focus",
    "weekly_environment_setup", "weekly_habit_culture",
    "weekly_home_cooperation", "weekly_materials_generate",
)
_WEEKLY_AI_CREATE_KINDS = (
    "weekly_ai_games_create", "weekly_ai_columns_create",
    "weekly_ai_materials_create",
)
_WEEKLY_AI_TARGETS = (
    "games", "key_week_focus", "environment_setup",
    "habit_culture", "home_cooperation", "materials",
)

def _listening_checks(connection: sqlite3.Connection) -> None:
    """Validate listening ownership, templates, groups, stars and paths.

    This is deliberately more than resource enumeration: a backup whose
    listening tables have a missing domain/group, an unknown template item or
    a path that does not match its record/asset identity must be refused.
    """
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "local_listening_records" not in tables:
            return
        from app.local import listening_templates

        records = connection.execute(
            "SELECT id, profile_id, class_id, term_id, grade, child_name, "
            "revision FROM local_listening_records"
        ).fetchall()
        record_meta: dict[str, dict[str, Any]] = {}
        domain_meta: dict[tuple[str, str], dict[str, Any]] = {}
        group_meta: dict[tuple[str, str], dict[str, int]] = {}
        asset_meta: dict[str, dict[str, dict[str, Any]]] = {}
        for (
            record_id,
            profile_id,
            class_id,
            term_id,
            grade,
            child_name,
            revision,
        ) in records:
            if (
                grade not in listening_templates.GRADES
                or not isinstance(child_name, str)
                or not 1 <= len(child_name) <= 80
                or type(revision) is not int
                or revision < 1
            ):
                raise BackupValidationError(
                    "BACKUP_DB_LOGICAL_INVALID",
                    "备份数据库倾听记录字段不合法",
                )
            record_meta[record_id] = {
                "profile_id": profile_id,
                "class_id": class_id,
                "term_id": term_id,
                "grade": grade,
                "child_name": child_name,
                "revision": revision,
            }
            domain_rows = connection.execute(
                "SELECT domain, template_version, template_sha256 "
                "FROM local_listening_domains WHERE record_id = ?",
                (record_id,),
            ).fetchall()
            if len(domain_rows) != 5 or {
                row[0] for row in domain_rows
            } != set(listening_templates.DOMAINS):
                raise BackupValidationError(
                    "BACKUP_DB_LOGICAL_INVALID",
                    "备份数据库倾听领域不完整",
                )
            for domain, template_version, template_sha in domain_rows:
                try:
                    template = listening_templates.get_template(
                        grade, domain, template_version
                    )
                except LocalError as exc:
                    raise BackupValidationError(
                        "BACKUP_DB_LOGICAL_INVALID",
                        "备份数据库倾听模板不可用",
                    ) from exc
                if template.sha256 != template_sha:
                    raise BackupValidationError(
                        "BACKUP_DB_LOGICAL_INVALID",
                        "备份数据库倾听模板散列不一致",
                    )
                domain_meta[(record_id, domain)] = {
                    "version": template_version,
                    "sha256": template_sha,
                }
                groups = connection.execute(
                    "SELECT id, position, work_date_text, listening_text, "
                    "asset_id FROM local_listening_photo_groups "
                    "WHERE record_id = ? AND domain = ?",
                    (record_id, domain),
                ).fetchall()
                if len(groups) != 3:
                    raise BackupValidationError(
                        "BACKUP_DB_LOGICAL_INVALID",
                        "备份数据库倾听图文组数量不合法",
                    )
                group_ids: set[str] = set()
                positions: list[int] = []
                for (
                    group_id,
                    position,
                    work_date_text,
                    listening_text,
                    asset_id,
                ) in groups:
                    if group_id in group_ids:
                        raise BackupValidationError(
                            "BACKUP_DB_LOGICAL_INVALID",
                            "备份数据库倾听图文组重复",
                        )
                    group_ids.add(group_id)
                    if (
                        type(position) is not int
                        or position not in (0, 1, 2)
                    ):
                        raise BackupValidationError(
                            "BACKUP_DB_LOGICAL_INVALID",
                            "备份数据库倾听图文组位置不合法",
                        )
                    positions.append(position)
                    if work_date_text is not None and len(work_date_text) > 120:
                        raise BackupValidationError(
                            "BACKUP_DB_LOGICAL_INVALID",
                            "备份数据库倾听作品日期过长",
                        )
                    if listening_text is not None and len(listening_text) > 20000:
                        raise BackupValidationError(
                            "BACKUP_DB_LOGICAL_INVALID",
                            "备份数据库倾听正文过长",
                        )
                    if asset_id is not None:
                        asset = connection.execute(
                            "SELECT id FROM local_listening_assets "
                            "WHERE record_id = ? AND id = ?",
                            (record_id, asset_id),
                        ).fetchone()
                        if asset is None:
                            raise BackupValidationError(
                                "BACKUP_DB_LOGICAL_INVALID",
                                "备份数据库倾听照片归属不合法",
                            )
                if sorted(positions) != [0, 1, 2]:
                    raise BackupValidationError(
                        "BACKUP_DB_LOGICAL_INVALID",
                        "备份数据库倾听图文组顺序不合法",
                    )
                group_meta[(record_id, domain)] = {
                    row[0]: row[1] for row in groups
                }
                choices = connection.execute(
                    "SELECT item_id, stars FROM local_listening_evaluation_choices "
                    "WHERE record_id = ? AND domain = ?",
                    (record_id, domain),
                ).fetchall()
                expected_items = {item.item_id for item in template.items}
                if (
                    len(choices) != len(expected_items)
                    or {row[0] for row in choices} != expected_items
                ):
                    raise BackupValidationError(
                        "BACKUP_DB_LOGICAL_INVALID",
                        "备份数据库倾听评价项不完整",
                    )
                for item_id, stars in choices:
                    if stars is not None and (
                        type(stars) is not int or stars not in (1, 2, 3)
                    ):
                        raise BackupValidationError(
                            "BACKUP_DB_LOGICAL_INVALID",
                            "备份数据库倾听星级不合法",
                        )
            assets = connection.execute(
                "SELECT id, relative_path, content_hash, byte_size, width, "
                "height, orientation, mime_type FROM local_listening_assets "
                "WHERE record_id = ?",
                (record_id,),
            ).fetchall()
            for (
                asset_id,
                relative_path,
                content_hash,
                byte_size,
                width,
                height,
                orientation,
                mime_type,
            ) in assets:
                prefix = (
                    f"observations/assets/listening/{record_id}/{asset_id}/"
                    "original."
                )
                if not isinstance(relative_path, str) or not relative_path.startswith(
                    prefix
                ):
                    raise BackupValidationError(
                        "BACKUP_DB_LOGICAL_INVALID",
                        "备份数据库倾听照片路径不合法",
                    )
                extension = relative_path[len(prefix):]
                if extension not in ("jpg", "png", "webp", "gif", "bmp"):
                    raise BackupValidationError(
                        "BACKUP_DB_LOGICAL_INVALID",
                        "备份数据库倾听照片扩展名不合法",
                    )
                if (
                    not isinstance(content_hash, str)
                    or _HEX64.fullmatch(content_hash) is None
                ):
                    raise BackupValidationError(
                        "BACKUP_DB_LOGICAL_INVALID",
                        "备份数据库倾听照片散列不合法",
                    )
                if (
                    type(byte_size) is not int
                    or byte_size < 0
                    or type(width) is not int
                    or width < 1
                    or type(height) is not int
                    or height < 1
                ):
                    raise BackupValidationError(
                        "BACKUP_DB_LOGICAL_INVALID",
                        "备份数据库倾听照片尺寸不合法",
                    )
                if orientation is not None and (
                    type(orientation) is not int or orientation not in range(1, 9)
                ):
                    raise BackupValidationError(
                        "BACKUP_DB_LOGICAL_INVALID",
                        "备份数据库倾听照片方向不合法",
                    )
                if mime_type not in (
                    "image/jpeg",
                    "image/png",
                    "image/webp",
                    "image/gif",
                    "image/bmp",
                ):
                    raise BackupValidationError(
                        "BACKUP_DB_LOGICAL_INVALID",
                        "备份数据库倾听照片格式不合法",
                    )
                asset_meta.setdefault(record_id, {})[asset_id] = {
                    "content_hash": content_hash,
                    "byte_size": byte_size,
                }

        # Operation receipts are the retry identity.  A forged result that
        # names another same-name record (or a domain/group/asset that does
        # not belong to the receipt's record) must not survive restore, or a
        # same request id could replay the wrong child's data.
        known_kinds = {
            "listening_create",
            "listening_record_patch",
            "listening_domain_save",
            "listening_asset_import",
            "listening_asset_remove",
            "listening_photo_reorder",
        }
        operations = connection.execute(
            "SELECT id, profile_id, request_id, operation_kind, record_id, "
            "request_fingerprint, status, result_json FROM "
            "local_listening_operations"
        ).fetchall()
        for (
            operation_id,
            profile_id,
            request_id,
            operation_kind,
            record_id,
            request_fingerprint,
            status,
            result_json,
        ) in operations:
            if (
                not isinstance(request_id, str)
                or not 1 <= len(request_id) <= 36
                or not isinstance(request_fingerprint, str)
                or _HEX64.fullmatch(request_fingerprint) is None
                or status != "committed"
                or operation_kind not in known_kinds
                or not isinstance(record_id, str)
                or record_id not in record_meta
            ):
                raise BackupValidationError(
                    "BACKUP_DB_LOGICAL_INVALID",
                    "备份数据库倾听回执字段不合法",
                )
            meta = record_meta[record_id]
            if meta["profile_id"] != profile_id:
                raise BackupValidationError(
                    "BACKUP_DB_LOGICAL_INVALID",
                    "备份数据库倾听回执档案归属不合法",
                )
            try:
                result = (
                    json.loads(result_json)
                    if isinstance(result_json, (str, bytes, bytearray))
                    else result_json
                )
            except (ValueError, UnicodeDecodeError) as exc:
                raise BackupValidationError(
                    "BACKUP_DB_LOGICAL_INVALID",
                    "备份数据库倾听回执 JSON 不合法",
                ) from exc
            if not isinstance(result, dict):
                raise BackupValidationError(
                    "BACKUP_DB_LOGICAL_INVALID",
                    "备份数据库倾听回执结果不合法",
                )
            if result.get("record_id") != record_id:
                raise BackupValidationError(
                    "BACKUP_DB_LOGICAL_INVALID",
                    "备份数据库倾听回执记录身份不匹配",
                )
            result_revision = result.get("revision")
            if (
                type(result_revision) is not int
                or result_revision < 1
                or result_revision > meta["revision"]
            ):
                raise BackupValidationError(
                    "BACKUP_DB_LOGICAL_INVALID",
                    "备份数据库倾听回执修订不合法",
                )
            if "changed" in result and not isinstance(result["changed"], bool):
                raise BackupValidationError(
                    "BACKUP_DB_LOGICAL_INVALID",
                    "备份数据库倾听回执 changed 不合法",
                )
            if operation_kind == "listening_create":
                if (
                    result_revision != 1
                    or result.get("class_id") != meta["class_id"]
                    or result.get("term_id") != meta["term_id"]
                    or result.get("grade") != meta["grade"]
                    or not isinstance(result.get("child_name"), str)
                    or not 1 <= len(result["child_name"]) <= 80
                ):
                    raise BackupValidationError(
                        "BACKUP_DB_LOGICAL_INVALID",
                        "备份数据库倾听新建回执身份不匹配",
                    )
                templates = result.get("templates")
                if not isinstance(templates, dict) or set(templates) != set(
                    listening_templates.DOMAINS
                ):
                    raise BackupValidationError(
                        "BACKUP_DB_LOGICAL_INVALID",
                        "备份数据库倾听新建回执模板不完整",
                    )
                for domain, template_entry in templates.items():
                    expected = domain_meta.get((record_id, domain))
                    if (
                        not isinstance(template_entry, dict)
                        or template_entry.get("version")
                        != (expected or {}).get("version")
                        or template_entry.get("sha256")
                        != (expected or {}).get("sha256")
                    ):
                        raise BackupValidationError(
                            "BACKUP_DB_LOGICAL_INVALID",
                            "备份数据库倾听新建回执模板不匹配",
                        )
            elif operation_kind == "listening_record_patch":
                if (
                    not isinstance(result.get("child_name"), str)
                    or not 1 <= len(result["child_name"]) <= 80
                ):
                    raise BackupValidationError(
                        "BACKUP_DB_LOGICAL_INVALID",
                        "备份数据库倾听改名回执不合法",
                    )
            elif operation_kind == "listening_domain_save":
                if result.get("domain") not in listening_templates.DOMAINS:
                    raise BackupValidationError(
                        "BACKUP_DB_LOGICAL_INVALID",
                        "备份数据库倾听领域保存回执领域不合法",
                    )
                if (
                    record_id,
                    result["domain"],
                ) not in domain_meta:
                    raise BackupValidationError(
                        "BACKUP_DB_LOGICAL_INVALID",
                        "备份数据库倾听领域保存回执归属不合法",
                    )
            elif operation_kind == "listening_asset_import":
                domain = result.get("domain")
                group_id = result.get("group_id")
                asset_id = result.get("asset_id")
                if (
                    domain not in listening_templates.DOMAINS
                    or not isinstance(group_id, str)
                    or group_id not in group_meta.get((record_id, domain), {})
                    or not isinstance(asset_id, str)
                    or asset_id not in asset_meta.get(record_id, {})
                    or result.get("content_hash")
                    != asset_meta[record_id][asset_id]["content_hash"]
                    or (
                        result.get("old_asset_id") is not None
                        and result.get("old_asset_id")
                        not in asset_meta.get(record_id, {})
                    )
                ):
                    raise BackupValidationError(
                        "BACKUP_DB_LOGICAL_INVALID",
                        "备份数据库倾听照片导入回执归属不合法",
                    )
            elif operation_kind == "listening_asset_remove":
                domain = result.get("domain")
                group_id = result.get("group_id")
                if (
                    domain not in listening_templates.DOMAINS
                    or not isinstance(group_id, str)
                    or group_id not in group_meta.get((record_id, domain), {})
                    or result.get("asset_id") is not None
                    or (
                        result.get("old_asset_id") is not None
                        and result.get("old_asset_id")
                        not in asset_meta.get(record_id, {})
                    )
                ):
                    raise BackupValidationError(
                        "BACKUP_DB_LOGICAL_INVALID",
                        "备份数据库倾听照片移除回执归属不合法",
                    )
            elif operation_kind == "listening_photo_reorder":
                domain = result.get("domain")
                group_ids = result.get("group_ids")
                expected_groups = group_meta.get((record_id, domain))
                if (
                    domain not in listening_templates.DOMAINS
                    or expected_groups is None
                    or not isinstance(group_ids, list)
                    or len(group_ids) != 3
                    or any(not isinstance(item, str) for item in group_ids)
                    or len(set(group_ids)) != 3
                    or set(group_ids) != set(expected_groups)
                ):
                    raise BackupValidationError(
                        "BACKUP_DB_LOGICAL_INVALID",
                        "备份数据库倾听排序回执归属不合法",
                    )
    except BackupValidationError:
        raise
    except Exception as exc:  # noqa: BLE001 - controlled backup refusal
        raise BackupValidationError(
            "BACKUP_DB_LOGICAL_INVALID", "备份数据库倾听校验失败"
        ) from exc


def _weekly_checks(connection: sqlite3.Connection) -> None:
    """Strict historical weekly validation, including real daily history."""
    daily_contents = _daily_contents(connection)
    try:
        rows = connection.execute(
            "SELECT id, week_anchor_date, term_start_date, term_end_date, "
            "calendar_revision_id, header_json, header_hash, current_draft_id, "
            "current_draft_version, current_confirmed_id, "
            "current_confirmed_version, profile_id, class_id, term_id, "
            "week_number_snapshot FROM local_weekly_plans"
        ).fetchall()
    except sqlite3.Error as exc:
        raise BackupValidationError(
            "BACKUP_DB_LOGICAL_INVALID", "备份数据库周计划无法读取"
        ) from exc
    plans: dict[str, dict] = {}
    for row in rows:
        plan_id = row[0]
        header = _weekly_json(row[5], f"plan {plan_id} header")
        _weekly_require(isinstance(header, dict), "plan header")
        _weekly_require(_weekly_hash(header) == row[6], "plan header hash")
        plans[plan_id] = {
            "id": plan_id,
            "anchor": row[1],
            "term_start": row[2],
            "term_end": row[3],
            "revision": row[4],
            "draft_id": row[7],
            "draft_version": row[8],
            "confirmed_id": row[9],
            "confirmed_version": row[10],
            "profile_id": row[11],
            "class_id": row[12],
            "term_id": row[13],
            "week_number": row[14],
            "header": header,
        }
    contents: dict[tuple[str, str], dict] = {}
    for row in connection.execute(
        "SELECT id, weekly_plan_id, version, schema_version, content_json, "
        "content_hash FROM local_weekly_plan_contents"
    ).fetchall():
        plan_id, content_id, version = row[1], row[0], row[2]
        _weekly_require(plan_id in plans, "content plan")
        plan = plans[plan_id]
        _weekly_require(type(row[3]) is int and row[3] in (1, 2), "content schema_version")
        content = _weekly_content(row[4], row[5], row[3], f"content {content_id}")
        manifest = content["source_manifest"]
        _weekly_require(
            manifest.get("profile_id") == plan["profile_id"]
            and manifest.get("class_id") == plan["class_id"]
            and manifest.get("term_id") == plan["term_id"]
            and manifest.get("week_anchor_date") == plan["anchor"]
            and manifest.get("week_number") == plan["week_number"]
            and manifest.get("header") == plan["header"],
            "source manifest identity",
        )
        _weekly_validate_sources(content, plan, daily_contents)
        contents[(plan_id, content_id)] = {
            "version": version,
            "hash": row[5],
            "content": content,
        }
    _weekly_ai_chain(connection, plans, contents)
    _listening_ai_chain(connection)
    for plan_id, plan in plans.items():
        _weekly_require(
            (plan_id, plan["draft_id"]) in contents, "current draft pointer"
        )
        _weekly_require(
            contents[(plan_id, plan["draft_id"])]["version"]
            == plan["draft_version"],
            "current draft version",
        )
    confirmations: dict[tuple[str, str], int] = {}
    confirmation_hashes: dict[tuple[str, str], str] = {}
    confirmation_rows: dict[tuple[str, str], dict] = {}
    for row in connection.execute(
        "SELECT id, weekly_plan_id, version, draft_id, draft_version, "
        "schema_version, snapshot_json, snapshot_hash, facts_json, facts_hash "
        "FROM local_weekly_plan_confirmations"
    ).fetchall():
        confirmation_id, plan_id, draft_id, draft_version = (
            row[0], row[1], row[3], row[4]
        )
        _weekly_require(plan_id in plans, "confirmation plan")
        _weekly_require((plan_id, draft_id) in contents, "confirmation draft")
        draft = contents[(plan_id, draft_id)]
        _weekly_require(draft["version"] == draft_version, "confirmation version")
        _weekly_require(row[5] == 1, "confirmation schema_version")
        snapshot = _weekly_json(row[6], f"confirmation {confirmation_id}")
        facts = _weekly_json(row[8], f"confirmation {confirmation_id} facts")
        from app.local import weekly_plan_snapshot

        try:
            snapshot = weekly_plan_snapshot.validate_confirmation_snapshot(snapshot)
        except LocalWeeklyInvalid as exc:
            raise BackupValidationError(
                "BACKUP_DB_LOGICAL_INVALID",
                f"备份数据库确认快照不合法：{confirmation_id}",
            ) from exc
        _weekly_require(
            snapshot.get("weekly_plan_id") == plan_id
            and snapshot.get("profile_id") == plans[plan_id]["profile_id"]
            and snapshot.get("class_id") == plans[plan_id]["class_id"]
            and snapshot.get("term_id") == plans[plan_id]["term_id"]
            and snapshot.get("draft_id") == draft_id
            and snapshot.get("draft_version") == draft_version
            and snapshot.get("content") == draft["content"]
            and snapshot.get("content_hash") == draft["hash"]
            and snapshot.get("header") == plans[plan_id]["header"]
            and snapshot.get("creation_context")
            == {
                "week_anchor_date": plans[plan_id]["anchor"],
                "week_number_snapshot": plans[plan_id]["week_number"],
                "term_start": plans[plan_id]["term_start"],
                "term_end": plans[plan_id]["term_end"],
                "calendar_revision_id": plans[plan_id]["revision"],
            },
            "confirmation snapshot identity",
        )
        _weekly_require(snapshot.get("facts") == facts, "confirmation facts copy")
        _weekly_require(_weekly_hash(snapshot) == row[7], "snapshot hash")
        _weekly_require(_weekly_hash(facts) == row[9], "facts hash")
        confirmations[(plan_id, confirmation_id)] = row[2]
        confirmation_hashes[(plan_id, confirmation_id)] = row[7]
        confirmation_rows[(plan_id, confirmation_id)] = {
            "version": row[2],
            "hash": row[7],
            "snapshot": snapshot,
        }
    _weekly_ai_chain(connection, plans, contents)
    _listening_ai_chain(connection)
    for plan_id, plan in plans.items():
        if plan["confirmed_id"] is not None:
            _weekly_require(
                (plan_id, plan["confirmed_id"]) in confirmations,
                "current confirmed pointer",
            )
            _weekly_require(
                confirmations[(plan_id, plan["confirmed_id"])]
                == plan["confirmed_version"],
                "current confirmed version",
            )
    from app.local import weekly_plan_operations

    for row in connection.execute(
        "SELECT id, profile_id, weekly_plan_id, action, result_draft_id, "
        "result_draft_version, result_confirmed_id, result_confirmed_version, "
        "result_snapshot_id, result_token_id, result_json FROM "
        "local_weekly_plan_operations"
    ).fetchall():
        operation_id = row[0]
        result = _weekly_json(row[10], f"operation {operation_id}")
        try:
            metadata = weekly_plan_operations.validate_metadata(
                result,
                weekly_plan_id=row[2],
                draft_id=row[4],
                draft_version=row[5],
                confirmation_id=row[6],
                confirmation_version=row[7],
                snapshot_id=row[8],
                token_id=row[9],
            )
        except LocalWeeklyInvalid as exc:
            raise BackupValidationError(
                "BACKUP_DB_LOGICAL_INVALID",
                f"备份数据库回执 metadata 不合法：{operation_id}",
            ) from exc
        if metadata["weekly_plan_id"] is not None:
            _weekly_require(row[2] in plans, "operation plan")
            plan = plans[row[2]]
            _weekly_require(plan["profile_id"] == row[1], "operation profile")
            if metadata["draft_id"] is not None:
                _weekly_require(
                    (row[2], metadata["draft_id"]) in contents
                    and contents[(row[2], metadata["draft_id"])]["version"]
                    == metadata["draft_version"],
                    "operation draft reference",
                )
            if metadata["confirmation_id"] is not None:
                _weekly_require(
                    (row[2], metadata["confirmation_id"]) in confirmations
                    and confirmations[(row[2], metadata["confirmation_id"])]
                    == metadata["confirmation_version"],
                    "operation confirmation reference",
                )
    for row in connection.execute(
        "SELECT id, profile_id, manifest_json, manifest_hash FROM "
        "local_weekly_export_snapshots"
    ).fetchall():
        manifest = _weekly_json(row[2], f"export snapshot {row[0]}")
        manifest = _weekly_validate_export_manifest(
            manifest,
            contents=contents,
            confirmation_rows=confirmation_rows,
        )
        _weekly_require(manifest.get("profile_id") == row[1], "export profile")
        _weekly_require(_weekly_hash(manifest) == row[3], "export manifest hash")
    for row in connection.execute(
        "SELECT t.id, t.snapshot_id, t.profile_id, s.profile_id "
        "FROM local_weekly_export_tokens t "
        "LEFT JOIN local_weekly_export_snapshots s ON s.id = t.snapshot_id"
    ).fetchall():
        _weekly_require(
            row[3] is not None and row[2] == row[3], "export token profile"
        )
    for row in connection.execute(
        "SELECT a.id, a.snapshot_id, a.profile_id, a.token_id, a.status, "
        "a.byte_size, a.result_hash, t.snapshot_id, t.profile_id "
        "FROM local_weekly_export_attempts a "
        "LEFT JOIN local_weekly_export_tokens t ON t.id = a.token_id"
    ).fetchall():
        _weekly_require(
            row[7] == row[1] and row[8] == row[2], "export attempt token"
        )
        if row[4] == "saved":
            _weekly_require(
                row[5] > 0 and row[6] is not None, "export saved result"
            )
        else:
            _weekly_require(
                row[5] == 0 and row[6] is None, "export non-saved result"
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
        _listening_checks(connection)
        _weekly_checks(connection)
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
        items: list[dict[str, Any]] = []
        if "local_observation_assets" in tables:
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
                       mime_type, width, height, NULL AS orientation,
                       NULL AS byte_size
                  FROM local_observation_asset_derivatives
                """
            for row in connection.execute(sql):
                items.append(
                    {
                        "path": row[0],
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
                )
        if "local_listening_assets" in tables:
            for row in connection.execute(
                """
                SELECT relative_path, 'original' AS kind, record_id,
                       id AS asset_id, NULL AS derivative_id, content_hash,
                       mime_type, width, height, orientation, byte_size
                  FROM local_listening_assets
                """
            ):
                items.append(
                    {
                        "owner_kind": "listening",
                        "path": row[0],
                        "kind": row[1],
                        "listening_record_id": row[2],
                        "asset_id": row[3],
                        "derivative_id": row[4],
                        "sha256": row[5],
                        "mime_type": row[6],
                        "width": row[7],
                        "height": row[8],
                        "orientation": row[9],
                        "byte_size": row[10],
                    }
                )
        items.sort(key=lambda item: item["path"])
        seen: set[str] = set()
        folded: set[str] = set()
        prefixes: set[str] = set()
        for item in items:
            path = safe_relative_path(item["path"])
            item["path"] = path
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
            yield item
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
        if not isinstance(entry, dict):
            raise BackupValidationError(
                "BACKUP_MANIFEST_INVALID", "备份清单资源项不合法"
            )
        listening = "owner_kind" in entry
        if listening:
            entry = _exact_keys(
                entry,
                {
                    "asset_id",
                    "bytes",
                    "derivative_id",
                    "kind",
                    "listening_record_id",
                    "owner_kind",
                    "path",
                    "sha256",
                },
                f"resources[{index}]",
            )
            if entry["owner_kind"] != "listening":
                raise BackupValidationError(
                    "BACKUP_MANIFEST_INVALID", "备份清单资源 owner_kind 不合法"
                )
            listening_record_id = _str(
                entry["listening_record_id"],
                minimum=1,
                maximum=32,
                label="listening_record_id",
            )
            if not _OPAQUE_ID.fullmatch(listening_record_id):
                raise BackupValidationError(
                    "BACKUP_MANIFEST_INVALID",
                    "备份清单资源 listening_record_id 不合法",
                )
        else:
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
                _str(
                    entry["observation_id"],
                    minimum=1,
                    maximum=32,
                    label="observation_id",
                )
            ):
                raise BackupValidationError(
                    "BACKUP_MANIFEST_INVALID",
                    "备份清单资源 observation_id 不合法",
                )
        asset_id = _str(
            entry["asset_id"], minimum=1, maximum=32, label="asset_id"
        )
        if not _OPAQUE_ID.fullmatch(asset_id):
            raise BackupValidationError(
                "BACKUP_MANIFEST_INVALID", "备份清单资源 asset_id 不合法"
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
        if listening:
            if not path.startswith("observations/assets/listening/"):
                raise BackupValidationError(
                    "BACKUP_MANIFEST_INVALID", "备份清单倾听资源路径不合法"
                )
            parts = path.split("/")
            if (
                len(parts) < 6
                or parts[3] != listening_record_id
                or parts[4] != asset_id
            ):
                raise BackupValidationError(
                    "BACKUP_MANIFEST_INVALID", "备份清单倾听资源归属不合法"
                )
            if kind == "original":
                if (
                    derivative is not None
                    or len(parts) != 6
                    or not parts[5].startswith("original.")
                    or "." not in parts[5]
                    or parts[5].split(".", 1)[1]
                    not in ("jpg", "png", "webp", "gif", "bmp")
                ):
                    raise BackupValidationError(
                        "BACKUP_MANIFEST_INVALID",
                        "备份清单倾听原图路径不合法",
                    )
            else:
                if (
                    derivative is None
                    or len(parts) != 7
                    or parts[5] != "derivatives"
                    or parts[6] != f"{derivative}.jpg"
                ):
                    raise BackupValidationError(
                        "BACKUP_MANIFEST_INVALID",
                        "备份清单倾听派生图路径不合法",
                    )
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
        if entry.get("owner_kind") == "listening":
            if db_entry.get("owner_kind") != "listening":
                raise BackupValidationError(
                    "BACKUP_MANIFEST_INVALID", "备份清单资源身份不匹配"
                )
            for key in (
                "kind",
                "listening_record_id",
                "asset_id",
                "derivative_id",
            ):
                if entry.get(key) != db_entry.get(key):
                    raise BackupValidationError(
                        "BACKUP_MANIFEST_INVALID", "备份清单资源身份不匹配"
                    )
        else:
            if db_entry.get("owner_kind") == "listening":
                raise BackupValidationError(
                    "BACKUP_MANIFEST_INVALID", "备份清单资源身份不匹配"
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
