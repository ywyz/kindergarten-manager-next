"""FastAPI routes for the independent online collaboration service."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from .config import CollaborationSettings
from .errors import auth_required
from .schemas import (
    ClassmateOut,
    ClassOut,
    ClassSelectIn,
    ConfigConfirmIn,
    ConfigConfirmOut,
    ConfigCurrentOut,
    ConfigPreviewIn,
    ConfigPreviewOut,
    ConfigSaveIn,
    ConfigSaveOut,
    HealthOut,
    MembershipOut,
    OperationOut,
    TeacherOut,
)
from .security import TeacherPrincipal, authenticate
from .service import (
    confirm_import,
    current_membership,
    get_me,
    get_own_config,
    leave_current_class,
    list_classmates,
    list_classes,
    preview_import,
    query_operation,
    save_config,
    select_class,
)

router = APIRouter(prefix="/api/collaboration", tags=["collaboration"])


def get_settings(request: Request) -> CollaborationSettings:
    return request.app.state.collab_settings


def get_session(request: Request):
    factory = request.app.state.session_factory
    session: Session = factory()
    try:
        yield session
    finally:
        session.close()


def get_principal(
    request: Request,
    session: Session = Depends(get_session),
    settings: CollaborationSettings = Depends(get_settings),
) -> TeacherPrincipal:
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        raise auth_required()
    token = authorization[7:].strip()
    if not token:
        raise auth_required()
    return authenticate(session, token, settings.token_pepper)


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    # Liveness only: no database connection, identity or secret material.
    return HealthOut(status="ok", service="collaboration")


@router.get("/me", response_model=TeacherOut)
def me(
    principal: TeacherPrincipal = Depends(get_principal),
) -> TeacherOut:
    return get_me(principal)


@router.get("/classes", response_model=list[ClassOut])
def classes(
    session: Session = Depends(get_session),
    principal: TeacherPrincipal = Depends(get_principal),
) -> list[ClassOut]:
    return list_classes(session, principal)


@router.get("/me/class", response_model=MembershipOut | None)
def my_class(
    session: Session = Depends(get_session),
    principal: TeacherPrincipal = Depends(get_principal),
) -> MembershipOut | None:
    return current_membership(session, principal)


@router.put("/me/class", response_model=MembershipOut)
def set_my_class(
    data: ClassSelectIn,
    session: Session = Depends(get_session),
    principal: TeacherPrincipal = Depends(get_principal),
) -> MembershipOut:
    return select_class(session, principal, data.class_id)


@router.delete("/me/class", status_code=status.HTTP_204_NO_CONTENT)
def leave_my_class(
    session: Session = Depends(get_session),
    principal: TeacherPrincipal = Depends(get_principal),
) -> Response:
    leave_current_class(session, principal)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/classmates", response_model=list[ClassmateOut])
def classmates(
    session: Session = Depends(get_session),
    principal: TeacherPrincipal = Depends(get_principal),
) -> list[ClassmateOut]:
    return list_classmates(session, principal)


@router.get("/game-config", response_model=ConfigCurrentOut)
def game_config(
    session: Session = Depends(get_session),
    principal: TeacherPrincipal = Depends(get_principal),
) -> ConfigCurrentOut:
    return get_own_config(session, principal)


@router.put("/game-config", response_model=ConfigSaveOut)
def save_game_config(
    data: ConfigSaveIn,
    session: Session = Depends(get_session),
    principal: TeacherPrincipal = Depends(get_principal),
) -> ConfigSaveOut:
    return save_config(session, principal, data)


@router.post("/game-config/preview", response_model=ConfigPreviewOut)
def preview_game_config(
    data: ConfigPreviewIn,
    session: Session = Depends(get_session),
    principal: TeacherPrincipal = Depends(get_principal),
    settings: CollaborationSettings = Depends(get_settings),
) -> ConfigPreviewOut:
    return preview_import(session, principal, data, settings)


@router.post("/game-config/confirm", response_model=ConfigConfirmOut)
def confirm_game_config(
    data: ConfigConfirmIn,
    session: Session = Depends(get_session),
    principal: TeacherPrincipal = Depends(get_principal),
    settings: CollaborationSettings = Depends(get_settings),
) -> ConfigConfirmOut:
    return confirm_import(session, principal, data, settings)


@router.get(
    "/game-config/operations/{request_id}",
    response_model=OperationOut,
)
def game_config_operation(
    request_id: UUID,
    session: Session = Depends(get_session),
    principal: TeacherPrincipal = Depends(get_principal),
) -> OperationOut:
    return query_operation(session, principal, request_id)
