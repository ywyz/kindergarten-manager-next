"""SQLAlchemy repository for the personal todo service.

The todo models share ``LocalBase`` metadata and are added by the forward-only
0013 migration; this repository is the only place that knows the physical
table names.  It never auto-creates tables: an old archive without the tables
is reported as storage-not-ready until the normal startup upgrade runs.
"""

from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy import case, inspect, select
from sqlalchemy.orm import Session

from app.local import todo_domain as domain
from app.local.todo_models import LocalTodo, LocalTodoOperation
from app.local.tx import begin_immediate, read_scope, rollback as tx_rollback


def storage_ready(session: Session) -> bool:
    bind = session.get_bind()
    if bind is None:
        return False
    inspector = inspect(bind)
    return (
        inspector.has_table("local_todos")
        and inspector.has_table("local_todo_operations")
    )


def _row(todo: LocalTodo) -> dict[str, Any]:
    return {
        "todo_id": todo.id,
        "title": todo.title,
        "due_date": todo.due_date,
        "completed": todo.completed,
        "archived_at": todo.archived_at,
        "version": todo.version,
        "created_at": todo.created_at,
        "updated_at": todo.updated_at,
    }


class SqlTodoRepository:
    def __init__(self, session: Session, profile_id: str) -> None:
        self.session = session
        self.profile_id = profile_id

    def list_todos(self, archived: bool = False) -> list[dict[str, Any]]:
        with read_scope(self.session):
            archive_filter = (
                LocalTodo.archived_at.is_not(None)
                if archived
                else LocalTodo.archived_at.is_(None)
            )
            rows = self.session.scalars(
                select(LocalTodo)
                .where(LocalTodo.profile_id == self.profile_id, archive_filter)
                .order_by(
                    LocalTodo.completed.asc(),
                    case((LocalTodo.due_date.is_(None), 1), else_=0),
                    LocalTodo.due_date.asc(),
                    LocalTodo.created_at.asc(),
                    LocalTodo.id.asc(),
                )
            ).all()
            return [_row(row) for row in rows]

    def read_operation(self, request_id: str) -> dict[str, Any] | None:
        with read_scope(self.session):
            return self._operation(request_id)

    def _operation(self, request_id: str) -> dict[str, Any] | None:
        row = self.session.get(LocalTodoOperation, (self.profile_id, request_id))
        if row is None:
            return None
        return {
            "action": row.action,
            "input_fingerprint": row.input_fingerprint,
            "result_json": row.result_json,
        }

    def get_operation(self, request_id: str) -> dict[str, Any] | None:
        return self._operation(request_id)

    def begin_write(self) -> None:
        begin_immediate(self.session)

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        # Reuse the shared best-effort rollback: cleanup failures must never
        # replace the service's definite error or TODO_COMMIT_UNCERTAIN.
        tx_rollback(self.session)

    def get_todo(self, todo_id: str) -> dict[str, Any] | None:
        row = self.session.get(LocalTodo, todo_id)
        if row is None or row.profile_id != self.profile_id:
            return None
        return _row(row)

    def insert_todo(self, row: Mapping[str, Any]) -> None:
        self.session.add(
            LocalTodo(
                id=row["todo_id"],
                profile_id=self.profile_id,
                title=row["title"],
                due_date=row["due_date"],
                completed=row["completed"],
                version=row["version"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
        )
        self.session.flush()

    def update_todo(self, todo_id: str, fields: Mapping[str, Any]) -> None:
        row = self.session.get(LocalTodo, todo_id)
        if row is None or row.profile_id != self.profile_id:
            raise domain.TodoNotFound()
        for key in ("title", "due_date", "completed", "archived_at", "version", "updated_at"):
            if key in fields:
                setattr(row, key, fields[key])
        self.session.flush()

    def delete_todo(self, todo_id: str) -> None:
        row = self.session.get(LocalTodo, todo_id)
        if row is None or row.profile_id != self.profile_id:
            raise domain.TodoNotFound()
        self.session.delete(row)
        self.session.flush()

    def insert_operation(self, row: Mapping[str, Any]) -> None:
        self.session.add(
            LocalTodoOperation(
                profile_id=self.profile_id,
                request_id=row["request_id"],
                action=row["action"],
                todo_id=row["todo_id"],
                input_fingerprint=row["input_fingerprint"],
                result_json=row["result_json"],
                created_at=row["created_at"],
            )
        )
        self.session.flush()


__all__ = ["SqlTodoRepository", "storage_ready"]
