"""HTTP surface for local personal todos.

The API is intentionally small: list, create, partial update (edit/complete),
delete and read one operation receipt.  Ownership comes only from the local
profile context; the client cannot choose a class or term.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.local import todo_domain as domain
from app.local import todo_repository, todo_service
from app.local.api import get_session
from app.local.profile_service import require_context
from app.local.tx import read_scope, storage_errors

todos_router = APIRouter(prefix="/api/local/todos", tags=["todos"])


class TodoOut(BaseModel):
    todo_id: str
    title: str
    due_date: str | None = None
    completed: bool
    archived_at: str | None = None
    version: int
    created_at: str
    updated_at: str


class TodoListOut(BaseModel):
    items: list[TodoOut]


class TodoOperationOut(BaseModel):
    todo: TodoOut | None = None
    deleted: bool = False
    action: str | None = None
    items: list[TodoOut] | None = None


class TodoCreateIn(BaseModel):
    request_id: str
    title: str
    due_date: date | None = None


class TodoUpdateIn(BaseModel):
    request_id: str
    expected_version: int
    title: str | None = None
    due_date: date | None = None
    completed: bool | None = None


class TodoDeleteIn(BaseModel):
    request_id: str
    expected_version: int


class TodoUnarchiveIn(BaseModel):
    request_id: str
    expected_version: int


class TodoBatchItemIn(BaseModel):
    todo_id: str
    expected_version: int


class TodoBatchIn(BaseModel):
    request_id: str
    action: str
    items: list[TodoBatchItemIn]


def _error_response(exc: domain.TodoError) -> JSONResponse:
    error: dict[str, Any] = {"code": exc.code, "message": exc.message}
    if exc.details:
        error["details"] = exc.details
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": error},
        headers={"Cache-Control": "no-store"},
    )


def _handle(fn: Callable[[], Any]) -> Any:
    try:
        with storage_errors():
            return fn()
    except domain.TodoError as exc:
        return _error_response(exc)


def _profile_id(session: Session) -> str:
    with read_scope(session):
        context = require_context(session, date.today())
    if context.profile is None:  # pragma: no cover - require_context guards
        raise domain.TodoStorageNotReady("本地档案未就绪")
    return context.profile.id


def _repository(session: Session) -> todo_repository.SqlTodoRepository:
    profile_id = _profile_id(session)
    if not todo_repository.storage_ready(session):
        raise domain.TodoStorageNotReady()
    return todo_repository.SqlTodoRepository(session, profile_id)


@todos_router.get("", response_model=TodoListOut)
def list_todos(
    archived: bool = Query(default=False),
    session: Session = Depends(get_session),
):
    def action():
        repo = _repository(session)
        return {"items": todo_service.list_todos(repo, archived=archived)}

    return _handle(action)


@todos_router.post("/batch", response_model=TodoOperationOut)
def batch_todos(data: TodoBatchIn, session: Session = Depends(get_session)):
    def action():
        repo = _repository(session)
        return todo_service.batch_todos(
            repo,
            request_id=data.request_id,
            action=data.action,
            items=[item.model_dump() for item in data.items],
        )

    return _handle(action)


@todos_router.get("/operations/{request_id}", response_model=TodoOperationOut)
def read_operation(request_id: str, session: Session = Depends(get_session)):
    def action():
        repo = _repository(session)
        return todo_service.get_operation(repo, request_id=request_id)

    return _handle(action)


@todos_router.post("", response_model=TodoOut)
def create_todo(data: TodoCreateIn, session: Session = Depends(get_session)):
    def action():
        repo = _repository(session)
        return todo_service.create_todo(
            repo,
            request_id=data.request_id,
            title=data.title,
            due_date=data.due_date,
        )

    return _handle(action)


@todos_router.patch("/{todo_id}", response_model=TodoOut)
def update_todo(
    todo_id: str,
    data: TodoUpdateIn,
    session: Session = Depends(get_session),
):
    def action():
        fields: dict[str, Any] = {}
        if "title" in data.model_fields_set:
            if data.title is None:
                raise domain.TodoInputError("待办标题不能为 null")
            fields["title"] = data.title
        if "due_date" in data.model_fields_set:
            fields["due_date"] = data.due_date
        if "completed" in data.model_fields_set:
            if data.completed is None:
                raise domain.TodoInputError("completed 不能为 null")
            fields["completed"] = data.completed
        repo = _repository(session)
        return todo_service.update_todo(
            repo,
            todo_id=todo_id,
            request_id=data.request_id,
            expected_version=data.expected_version,
            fields=fields,
        )

    return _handle(action)


@todos_router.post("/{todo_id}/unarchive", response_model=TodoOut)
def unarchive_todo(
    todo_id: str,
    data: TodoUnarchiveIn,
    session: Session = Depends(get_session),
):
    def action():
        repo = _repository(session)
        return todo_service.unarchive_todo(
            repo,
            todo_id=todo_id,
            request_id=data.request_id,
            expected_version=data.expected_version,
        )

    return _handle(action)


@todos_router.delete("/{todo_id}", response_model=TodoOperationOut)
def delete_todo(
    todo_id: str,
    data: TodoDeleteIn,
    session: Session = Depends(get_session),
):
    def action():
        repo = _repository(session)
        return todo_service.delete_todo(
            repo,
            todo_id=todo_id,
            request_id=data.request_id,
            expected_version=data.expected_version,
        )

    return _handle(action)


__all__ = ["todos_router"]
