"""Personal todo service: profile-owned creates/edits/completes/deletes.

Every write owns one ``BEGIN IMMEDIATE`` transaction and one immutable
operation receipt keyed by ``(profile_id, request_id)``.  A duplicate request
returns the original receipt; a different fingerprint on the same request is
a conflict.  The repository protocol keeps the domain testable without a
database, while the SQL repository is the only DB-aware layer.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol

from app.ids import new_opaque_id
from app.local import todo_domain as domain
from app.local.base import utc_now
from app.local.normalize import normalize_request_id


class TodoRepository(Protocol):
    profile_id: str

    def list_todos(self, archived: bool = False) -> list[dict[str, Any]]: ...
    def read_operation(self, request_id: str) -> dict[str, Any] | None: ...
    def begin_write(self) -> None: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def get_operation(self, request_id: str) -> dict[str, Any] | None: ...
    def get_todo(self, todo_id: str) -> dict[str, Any] | None: ...
    def insert_todo(self, row: Mapping[str, Any]) -> None: ...
    def update_todo(self, todo_id: str, fields: Mapping[str, Any]) -> None: ...
    def delete_todo(self, todo_id: str) -> None: ...
    def insert_operation(self, row: Mapping[str, Any]) -> None: ...


def _safe_rollback(repo: TodoRepository) -> None:
    """Best-effort cleanup; a rollback failure must not mask the real result."""
    try:
        repo.rollback()
    except Exception:  # noqa: BLE001 - preserve the primary exception
        pass


def _commit(repo: TodoRepository) -> None:
    """Commit exactly once; a commit-phase exception is always uncertain."""
    try:
        repo.commit()
    except Exception as exc:
        # The caller performs the single safe rollback attempt below.
        raise domain.TodoCommitUncertain(
            "待办提交结果不确定，请用原请求核对回执"
        ) from exc


def _replay(
    repo: TodoRepository,
    request_id: str,
    action: str,
    fingerprint: str,
) -> dict[str, Any] | None:
    operation = repo.get_operation(request_id)
    if operation is None:
        return None
    if (
        operation.get("action") != action
        or operation.get("input_fingerprint") != fingerprint
    ):
        raise domain.TodoRequestConflict("该请求已用于不同待办内容")
    result = operation.get("result_json")
    if not isinstance(result, dict):
        raise domain.TodoRequestConflict("原请求回执不可用")
    return dict(result)


def list_todos(
    repo: TodoRepository, *, archived: bool = False
) -> list[dict[str, Any]]:
    return domain.sort_todos(repo.list_todos(archived=archived))


def create_todo(
    repo: TodoRepository,
    *,
    request_id: object,
    title: object,
    due_date: object,
) -> dict[str, Any]:
    rid = normalize_request_id(request_id)
    clean_title = domain.normalize_title(title)
    clean_due = domain.normalize_due_date(due_date)
    fingerprint = domain.todo_fingerprint(
        "create", {"title": clean_title, "due_date": clean_due}
    )
    repo.begin_write()
    try:
        replay = _replay(repo, rid, "create", fingerprint)
        if replay is not None:
            _safe_rollback(repo)
            return replay["todo"]
        now = utc_now()
        row = {
            "todo_id": new_opaque_id(),
            "profile_id": repo.profile_id,
            "title": clean_title,
            "due_date": clean_due,
            "completed": False,
            "version": 1,
            "created_at": now,
            "updated_at": now,
        }
        repo.insert_todo(row)
        result = {"todo": domain.todo_to_dict(row)}
        repo.insert_operation(
            {
                "profile_id": repo.profile_id,
                "request_id": rid,
                "action": "create",
                "todo_id": row["todo_id"],
                "input_fingerprint": fingerprint,
                "result_json": result,
                "created_at": now,
            }
        )
        _commit(repo)
        return result["todo"]
    except BaseException:
        _safe_rollback(repo)
        raise


def update_todo(
    repo: TodoRepository,
    *,
    todo_id: str,
    request_id: object,
    expected_version: object,
    fields: Mapping[str, Any],
) -> dict[str, Any]:
    rid = normalize_request_id(request_id)
    expected = domain.normalize_expected_version(expected_version)
    if not isinstance(fields, Mapping) or not fields:
        raise domain.TodoInputError("至少提供一个待办修改字段")
    unknown = set(fields) - {"title", "due_date", "completed"}
    if unknown:
        raise domain.TodoInputError("待办修改字段不合法")
    normalized: dict[str, Any] = {}
    if "title" in fields:
        normalized["title"] = domain.normalize_title(fields["title"])
    if "due_date" in fields:
        normalized["due_date"] = domain.normalize_due_date(fields["due_date"])
    if "completed" in fields:
        normalized["completed"] = domain.normalize_completed(fields["completed"])
    fingerprint = domain.todo_fingerprint(
        "update", {"todo_id": todo_id, "expected_version": expected, **normalized}
    )
    repo.begin_write()
    try:
        replay = _replay(repo, rid, "update", fingerprint)
        if replay is not None:
            _safe_rollback(repo)
            return replay["todo"]
        current = repo.get_todo(todo_id)
        if current is None:
            raise domain.TodoNotFound()
        if int(current["version"]) != expected:
            raise domain.TodoVersionConflict(
                "待办已在其他窗口更新",
                details={"todo": domain.todo_to_dict(current)},
            )
        if current.get("archived_at") is not None and normalized.get("completed") is False:
            raise domain.TodoInputError(
                "已归档待办不能改回未完成",
                details={"todo": domain.todo_to_dict(current)},
            )
        now = utc_now()
        repo.update_todo(
            todo_id,
            {**normalized, "version": expected + 1, "updated_at": now},
        )
        updated = {
            **current,
            **normalized,
            "version": expected + 1,
            "updated_at": now,
        }
        result = {"todo": domain.todo_to_dict(updated)}
        repo.insert_operation(
            {
                "profile_id": repo.profile_id,
                "request_id": rid,
                "action": "update",
                "todo_id": todo_id,
                "input_fingerprint": fingerprint,
                "result_json": result,
                "created_at": now,
            }
        )
        _commit(repo)
        return result["todo"]
    except BaseException:
        _safe_rollback(repo)
        raise


def delete_todo(
    repo: TodoRepository,
    *,
    todo_id: str,
    request_id: object,
    expected_version: object,
) -> dict[str, Any]:
    rid = normalize_request_id(request_id)
    expected = domain.normalize_expected_version(expected_version)
    fingerprint = domain.todo_fingerprint(
        "delete", {"todo_id": todo_id, "expected_version": expected}
    )
    repo.begin_write()
    try:
        replay = _replay(repo, rid, "delete", fingerprint)
        if replay is not None:
            _safe_rollback(repo)
            return replay
        current = repo.get_todo(todo_id)
        if current is None:
            raise domain.TodoNotFound()
        if int(current["version"]) != expected:
            raise domain.TodoVersionConflict(
                "待办已在其他窗口更新",
                details={"todo": domain.todo_to_dict(current)},
            )
        now = utc_now()
        result = {"deleted": True, "todo": domain.todo_to_dict(current)}
        repo.delete_todo(todo_id)
        repo.insert_operation(
            {
                "profile_id": repo.profile_id,
                "request_id": rid,
                "action": "delete",
                "todo_id": todo_id,
                "input_fingerprint": fingerprint,
                "result_json": result,
                "created_at": now,
            }
        )
        _commit(repo)
        return result
    except BaseException:
        _safe_rollback(repo)
        raise


def batch_todos(
    repo: TodoRepository,
    *,
    request_id: object,
    action: object,
    items: object,
) -> dict[str, Any]:
    rid = normalize_request_id(request_id)
    batch_action = domain.normalize_batch_action(action)
    normalized = domain.normalize_batch_items(items)
    internal_action = "update" if batch_action == "archive" else "delete"
    fingerprint = domain.batch_fingerprint(batch_action, normalized)
    repo.begin_write()
    try:
        replay = _replay(repo, rid, internal_action, fingerprint)
        if replay is not None:
            _safe_rollback(repo)
            return replay
        current_rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for item in normalized:
            current = repo.get_todo(item["todo_id"])
            if current is None:
                raise domain.TodoNotFound(
                    "待办不存在或不属于当前档案",
                    details={"todo_id": item["todo_id"]},
                )
            expected = item["expected_version"]
            if int(current["version"]) != expected:
                raise domain.TodoVersionConflict(
                    "待办已在其他窗口更新",
                    details={"todo": domain.todo_to_dict(current), **item},
                )
            if batch_action == "archive":
                if not bool(current.get("completed")):
                    raise domain.TodoInputError(
                        "只能归档已完成的待办",
                        details={"todo_id": item["todo_id"]},
                    )
                if current.get("archived_at") is not None:
                    raise domain.TodoInputError(
                        "待办已归档",
                        details={"todo_id": item["todo_id"]},
                    )
            current_rows.append((current, item))
        now = utc_now()
        result_items: list[dict[str, Any]] = []
        for current, item in current_rows:
            if batch_action == "archive":
                updated = {
                    **current,
                    "archived_at": now,
                    "version": int(current["version"]) + 1,
                    "updated_at": now,
                }
                repo.update_todo(
                    item["todo_id"],
                    {
                        "archived_at": now,
                        "version": updated["version"],
                        "updated_at": now,
                    },
                )
                result_items.append(domain.todo_to_dict(updated))
            else:
                repo.delete_todo(item["todo_id"])
                result_items.append(domain.todo_to_dict(current))
        result = {
            "action": batch_action,
            "items": result_items,
            "deleted": batch_action == "delete",
        }
        repo.insert_operation(
            {
                "profile_id": repo.profile_id,
                "request_id": rid,
                "action": internal_action,
                "todo_id": None,
                "input_fingerprint": fingerprint,
                "result_json": result,
                "created_at": now,
            }
        )
        _commit(repo)
    except BaseException:
        _safe_rollback(repo)
        raise
    return result


def get_operation(repo: TodoRepository, *, request_id: object) -> dict[str, Any]:
    rid = normalize_request_id(request_id)
    operation = repo.read_operation(rid)
    if operation is None:
        raise domain.TodoOperationNotFound()
    result = operation.get("result_json")
    if not isinstance(result, dict):
        raise domain.TodoOperationNotFound()
    return dict(result)


__all__ = [
    "TodoRepository",
    "batch_todos",
    "create_todo",
    "delete_todo",
    "get_operation",
    "list_todos",
    "update_todo",
]
