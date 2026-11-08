"""Protected local HTTP routes for desktop weekly plans."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.local import weekly_plan_service
from app.local.api import _launch_id, _session_scope, get_session
from app.local.errors import LocalValidationError
from app.local.observation_api import _profile_id
from app.local.schemas import (
    WeeklyConfirmIn,
    WeeklyConfirmPreviewIn,
    WeeklyCreateIn,
    WeeklyCreatePreviewIn,
    WeeklyRefreshIn,
    WeeklyRefreshPreviewIn,
    WeeklySaveIn,
)
from app.local.tx import storage_errors

weekly_plans_router = APIRouter(
    prefix="/api/weekly-plans", tags=["weekly-plans"]
)


@weekly_plans_router.post(
    "/create-preview", response_model=dict[str, Any]
)
def weekly_create_preview(
    data: WeeklyCreatePreviewIn,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        return weekly_plan_service.create_preview(
            session,
            runtime=request.app.state.runtime,
            profile_id=_profile_id(session),
            launch_id=_launch_id(request),
            session_scope_hash=_session_scope_hash(request),
            term_id=data.term_id,
            week_anchor_date=data.week_anchor_date,
        )


@weekly_plans_router.post(
    "", response_model=dict[str, Any], status_code=status.HTTP_201_CREATED
)
def weekly_create(
    response: Response,
    data: WeeklyCreateIn,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        result, created = weekly_plan_service.create_or_open(
            session,
            runtime=request.app.state.runtime,
            profile_id=_profile_id(session),
            launch_id=_launch_id(request),
            session_scope_hash=_session_scope_hash(request),
            request_id=data.request_id,
            term_id=data.term_id,
            week_anchor_date=data.week_anchor_date,
            expected_config_version=data.expected_config_version,
            context_token=data.context_token,
        )
    if not created:
        response.status_code = status.HTTP_200_OK
    return result


def _query_date(value: str | None, label: str) -> date | None:
    if value is None:
        return None
    if len(value) != 10:
        raise LocalValidationError(f"{label} 必须是规范 ISO 日期")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise LocalValidationError(f"{label} 必须是规范 ISO 日期") from None
    if parsed.isoformat() != value:
        raise LocalValidationError(f"{label} 必须是规范 ISO 日期")
    return parsed


@weekly_plans_router.get("", response_model=dict[str, Any])
def weekly_list(
    term_id: str | None = None,
    week_number: int | None = Query(default=None, ge=1),
    from_date: str | None = Query(default=None, alias="from"),
    to_date: str | None = Query(default=None, alias="to"),
    cursor: str | None = None,
    limit: int = Query(default=weekly_plan_service.DEFAULT_LIST_LIMIT),
    session: Session = Depends(get_session),
):
    with storage_errors():
        return weekly_plan_service.list_plans(
            session,
            profile_id=_profile_id(session),
            term_id=term_id,
            week_number=week_number,
            from_date=_query_date(from_date, "from"),
            to_date=_query_date(to_date, "to"),
            cursor=cursor,
            limit=limit,
        )


# Static path registered before the dynamic plan id.
@weekly_plans_router.get(
    "/operations/{request_id}", response_model=dict[str, Any]
)
def weekly_operation(
    request_id: str,
    session: Session = Depends(get_session),
):
    with storage_errors():
        return weekly_plan_service.get_business_operation(
            session,
            profile_id=_profile_id(session),
            request_id=request_id,
        )


@weekly_plans_router.get("/{plan_id}", response_model=dict[str, Any])
def weekly_detail(
    plan_id: str,
    session: Session = Depends(get_session),
):
    with storage_errors():
        return weekly_plan_service.get_detail(
            session, profile_id=_profile_id(session), plan_id=plan_id
        )


@weekly_plans_router.patch("/{plan_id}", response_model=dict[str, Any])
def weekly_save(
    plan_id: str,
    data: WeeklySaveIn,
    session: Session = Depends(get_session),
):
    with storage_errors():
        return weekly_plan_service.save_draft(
            session,
            profile_id=_profile_id(session),
            request_id=data.request_id,
            plan_id=plan_id,
            expected_draft_version=data.expected_draft_version,
            patch=data.patch,
        )


@weekly_plans_router.post(
    "/{plan_id}/refresh-preview", response_model=dict[str, Any]
)
def weekly_refresh_preview(
    plan_id: str,
    data: WeeklyRefreshPreviewIn,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        return weekly_plan_service.refresh_preview(
            session,
            runtime=request.app.state.runtime,
            profile_id=_profile_id(session),
            launch_id=_launch_id(request),
            session_scope_hash=_session_scope_hash(request),
            plan_id=plan_id,
            expected_draft_version=data.expected_draft_version,
        )


@weekly_plans_router.post(
    "/{plan_id}/refresh-sources", response_model=dict[str, Any]
)
def weekly_refresh(
    plan_id: str,
    data: WeeklyRefreshIn,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        return weekly_plan_service.refresh_sources(
            session,
            runtime=request.app.state.runtime,
            profile_id=_profile_id(session),
            launch_id=_launch_id(request),
            session_scope_hash=_session_scope_hash(request),
            request_id=data.request_id,
            plan_id=plan_id,
            expected_draft_version=data.expected_draft_version,
            preview_token=data.preview_token,
        )


@weekly_plans_router.post(
    "/{plan_id}/confirmation-preview", response_model=dict[str, Any]
)
def weekly_confirmation_preview(
    plan_id: str,
    data: WeeklyConfirmPreviewIn,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        return weekly_plan_service.confirmation_preview(
            session,
            runtime=request.app.state.runtime,
            profile_id=_profile_id(session),
            launch_id=_launch_id(request),
            session_scope_hash=_session_scope_hash(request),
            plan_id=plan_id,
            expected_draft_version=data.expected_draft_version,
        )


@weekly_plans_router.post(
    "/{plan_id}/confirm", response_model=dict[str, Any]
)
def weekly_confirm(
    plan_id: str,
    data: WeeklyConfirmIn,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        return weekly_plan_service.confirm(
            session,
            runtime=request.app.state.runtime,
            profile_id=_profile_id(session),
            launch_id=_launch_id(request),
            session_scope_hash=_session_scope_hash(request),
            request_id=data.request_id,
            plan_id=plan_id,
            expected_draft_version=data.expected_draft_version,
            context_token=data.context_token,
            ack_missing=data.ack_missing,
            ack_stale=data.ack_stale,
            note=data.note,
        )


@weekly_plans_router.get(
    "/{plan_id}/confirmations", response_model=dict[str, Any]
)
def weekly_confirmations(
    plan_id: str,
    session: Session = Depends(get_session),
):
    with storage_errors():
        return weekly_plan_service.list_confirmations(
            session, profile_id=_profile_id(session), plan_id=plan_id
        )


@weekly_plans_router.get(
    "/{plan_id}/confirmations/{confirmation_id}",
    response_model=dict[str, Any],
)
def weekly_confirmation(
    plan_id: str,
    confirmation_id: str,
    session: Session = Depends(get_session),
):
    with storage_errors():
        return weekly_plan_service.get_confirmation(
            session,
            profile_id=_profile_id(session),
            plan_id=plan_id,
            confirmation_id=confirmation_id,
        )


def _session_scope_hash(request: Request) -> str:
    from app.local.weekly_plan_tokens import scope_hash

    return scope_hash(_session_scope(request))
