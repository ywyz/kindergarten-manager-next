"""Teacher routes for the shared weekly-plan slice."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .api import get_principal, get_session
from .security import TeacherPrincipal
from .weekly_plan_schemas import (
    WeeklyConfirmIn,
    WeeklyConfirmOut,
    WeeklyConfirmationOut,
    WeeklyOperationOut,
    WeeklyReadOut,
    WeeklySaveIn,
    WeeklySaveOut,
)
from .weekly_plan_service import (
    confirm_weekly_plan,
    get_confirmation,
    get_operation,
    get_weekly_plan,
    save_weekly_plan,
)

router = APIRouter(prefix="/api/collaboration", tags=["collaboration"])

_BASE = "/classes/{class_id}/weekly/{term_id}/{week_start}"


@router.get(_BASE, response_model=WeeklyReadOut)
def read_weekly_plan(
    class_id: UUID,
    term_id: UUID,
    week_start: date,
    session: Session = Depends(get_session),
    principal: TeacherPrincipal = Depends(get_principal),
) -> WeeklyReadOut:
    return WeeklyReadOut.model_validate(
        get_weekly_plan(
            session, principal, class_id, term_id, week_start
        )
    )


@router.post(_BASE + "/save", response_model=WeeklySaveOut)
def save_weekly_plan_route(
    class_id: UUID,
    term_id: UUID,
    week_start: date,
    data: WeeklySaveIn,
    session: Session = Depends(get_session),
    principal: TeacherPrincipal = Depends(get_principal),
) -> WeeklySaveOut:
    return WeeklySaveOut.model_validate(
        save_weekly_plan(
            session,
            principal,
            class_id,
            term_id,
            week_start,
            request_id=data.request_id,
            expected_version=data.expected_version,
            content=data.content.model_dump(mode="json"),
        )
    )


@router.post(_BASE + "/confirm", response_model=WeeklyConfirmOut)
def confirm_weekly_plan_route(
    class_id: UUID,
    term_id: UUID,
    week_start: date,
    data: WeeklyConfirmIn,
    session: Session = Depends(get_session),
    principal: TeacherPrincipal = Depends(get_principal),
) -> WeeklyConfirmOut:
    return WeeklyConfirmOut.model_validate(
        confirm_weekly_plan(
            session,
            principal,
            class_id,
            term_id,
            week_start,
            request_id=data.request_id,
            expected_version=data.expected_version,
        )
    )


@router.get(
    _BASE + "/confirmations/{confirmation_id}",
    response_model=WeeklyConfirmationOut,
)
def read_weekly_confirmation(
    class_id: UUID,
    term_id: UUID,
    week_start: date,
    confirmation_id: UUID,
    session: Session = Depends(get_session),
    principal: TeacherPrincipal = Depends(get_principal),
) -> WeeklyConfirmationOut:
    return WeeklyConfirmationOut.model_validate(
        get_confirmation(
            session,
            principal,
            class_id,
            term_id,
            week_start,
            confirmation_id,
        )
    )


@router.get(_BASE + "/operations/{request_id}", response_model=WeeklyOperationOut)
def read_weekly_operation(
    class_id: UUID,
    term_id: UUID,
    week_start: date,
    request_id: UUID,
    session: Session = Depends(get_session),
    principal: TeacherPrincipal = Depends(get_principal),
) -> WeeklyOperationOut:
    return WeeklyOperationOut.model_validate(
        get_operation(
            session,
            principal,
            class_id,
            term_id,
            week_start,
            request_id,
        )
    )
