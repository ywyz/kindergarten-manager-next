"""Pure domain rules for local personal todos.

No database, HTTP or FastAPI imports.  This module owns title/date validation,
idempotency fingerprints and the teacher-facing JSON shape; the service and
SQL repository stay thin around it.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any, Mapping

MAX_TITLE = 200
ACTIONS = ("create", "update", "delete")


class TodoError(Exception):
    code = "TODO_ERROR"
    status_code = 500

    def __init__(
        self,
        message: str = "待办操作失败",
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = dict(details or {})


class TodoInputError(TodoError):
    code = "TODO_INVALID"
    status_code = 422


class TodoNotFound(TodoError):
    code = "TODO_NOT_FOUND"
    status_code = 404


class TodoOperationNotFound(TodoError):
    code = "TODO_OPERATION_NOT_FOUND"
    status_code = 404


class TodoVersionConflict(TodoError):
    code = "TODO_VERSION_CONFLICT"
    status_code = 409


class TodoRequestConflict(TodoError):
    code = "TODO_REQUEST_CONFLICT"
    status_code = 409


class TodoCommitUncertain(TodoError):
    code = "TODO_COMMIT_UNCERTAIN"
    status_code = 503


class TodoStorageNotReady(TodoError):
    code = "TODO_STORAGE_NOT_READY"
    status_code = 503


def normalize_title(value: object) -> str:
    if not isinstance(value, str):
        raise TodoInputError("待办标题必须是字符串")
    title = value.strip()
    if not title or len(title) > MAX_TITLE:
        raise TodoInputError("待办标题长度应为 1–200 个字符")
    return title


def normalize_due_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            raise TodoInputError("截止日必须是 ISO 日期") from None
        if parsed.isoformat() != value:
            raise TodoInputError("截止日必须是 ISO 日期")
        return parsed
    raise TodoInputError("截止日必须是 ISO 日期或 null")


def normalize_completed(value: object) -> bool:
    if type(value) is not bool:
        raise TodoInputError("completed 必须是布尔值")
    return value


def normalize_expected_version(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise TodoInputError("expected_version 必须是正整数")
    return value


def todo_fingerprint(action: str, fields: Mapping[str, Any]) -> str:
    if action not in ACTIONS:
        raise TodoInputError("待办操作不合法")
    payload = {"action": action, **dict(fields)}
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda value: value.isoformat()
        if isinstance(value, date)
        else (_ for _ in ()).throw(TypeError("不可序列化的待办字段")),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _iso(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def normalize_batch_action(value: object) -> str:
    if value not in ("archive", "delete"):
        raise TodoInputError("批量操作只能是 archive 或 delete")
    return str(value)


def normalize_batch_items(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise TodoInputError("批量操作至少选择一个待办")
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping):
            raise TodoInputError("批量项目必须是对象")
        todo_id = item.get("todo_id")
        if not isinstance(todo_id, str) or not todo_id or len(todo_id) > 32:
            raise TodoInputError("批量待办 ID 不合法")
        if todo_id in seen:
            raise TodoInputError("批量待办 ID 不能重复")
        seen.add(todo_id)
        items.append(
            {
                "todo_id": todo_id,
                "expected_version": normalize_expected_version(
                    item.get("expected_version")
                ),
            }
        )
    return items


def batch_fingerprint(action: str, items: list[dict[str, Any]]) -> str:
    internal = "update" if action == "archive" else "delete"
    return todo_fingerprint(
        internal,
        {"batch_action": action, "items": items},
    )


def todo_to_dict(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "todo_id": str(row.get("todo_id") or row.get("id")),
        "title": str(row["title"]),
        "due_date": _iso(row.get("due_date")),
        "completed": bool(row.get("completed")),
        "archived_at": _iso(row.get("archived_at")),
        "version": int(row["version"]),
        "created_at": _iso(row.get("created_at")) or "",
        "updated_at": _iso(row.get("updated_at")) or "",
    }


def todo_order_key(item: Mapping[str, Any]) -> tuple:
    due = item.get("due_date")
    return (
        1 if item.get("completed") else 0,
        1 if due is None else 0,
        "" if due is None else _iso(due),
        _iso(item.get("created_at")) or "",
        str(item.get("todo_id") or item.get("id")),
    )


def sort_todos(items: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [todo_to_dict(item) for item in sorted(items, key=todo_order_key)]


__all__ = [
    "ACTIONS",
    "MAX_TITLE",
    "TodoCommitUncertain",
    "TodoError",
    "TodoInputError",
    "TodoNotFound",
    "TodoOperationNotFound",
    "TodoRequestConflict",
    "TodoStorageNotReady",
    "TodoVersionConflict",
    "batch_fingerprint",
    "normalize_batch_action",
    "normalize_batch_items",
    "normalize_completed",
    "normalize_due_date",
    "normalize_expected_version",
    "normalize_title",
    "sort_todos",
    "todo_fingerprint",
    "todo_order_key",
    "todo_to_dict",
]
