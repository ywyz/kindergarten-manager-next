"""Administrator web page, admin API, and teacher redemption API."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from .admin_service import (
    ADMIN_COOKIE,
    ADMIN_CSRF_COOKIE,
    ADMIN_CSRF_HEADER,
    AdminPrincipal,
    admin_cookie_secure,
    authenticate_admin,
    issue_code,
    list_schools,
    list_teachers,
    list_terms,
    login_admin,
    redeem_code,
    revoke_admin_session,
    update_school_name,
    update_term_name,
    verify_csrf,
)
from .api import get_session, get_settings
from .config import CollaborationSettings
from .schemas import MembershipOut


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AdminLoginIn(_StrictModel):
    username: str = Field(..., min_length=1, max_length=80)
    password: str = Field(..., min_length=1, max_length=4096)


class AdminLoginOut(_StrictModel):
    admin_id: UUID
    username: str
    csrf_token: str
    expires_at: datetime


class AdminSessionOut(_StrictModel):
    admin_id: UUID
    username: str


class AdminSchoolOut(_StrictModel):
    school_id: UUID
    name: str


class AdminSchoolUpdateIn(_StrictModel):
    expected_name: str = Field(..., min_length=1, max_length=120)
    new_name: str = Field(..., min_length=1, max_length=120)


class AdminTeacherOut(_StrictModel):
    teacher_id: UUID
    display_name: str
    active: bool


class AdminTermOut(_StrictModel):
    term_id: UUID
    school_id: UUID
    name: str
    start_date: date
    end_date: date


class AdminTermUpdateIn(_StrictModel):
    expected_name: str = Field(..., min_length=1, max_length=80)
    new_name: str = Field(..., min_length=1, max_length=80)


class AdminCodeIn(_StrictModel):
    school_id: UUID
    teacher_id: UUID
    purpose: Literal["join", "recovery"]


class AdminCodeOut(_StrictModel):
    code: str
    code_id: UUID
    purpose: str
    teacher_id: UUID
    teacher_name: str
    school_id: UUID
    expires_at: datetime


class RedeemIn(_StrictModel):
    code: str = Field(..., min_length=1, max_length=512)


class RedeemOut(_StrictModel):
    token: str
    token_id: UUID
    teacher_id: UUID
    teacher_name: str
    school_id: UUID
    school_name: str
    purpose: str
    membership: MembershipOut | None


router = APIRouter(tags=["collaboration-admin"])

_PAGE_PATH = Path(__file__).with_name("admin_page.html")


def _page_html() -> str:
    return _PAGE_PATH.read_text(encoding="utf-8")


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def _set_admin_cookies(response: Response, result) -> None:
    now = datetime.now(timezone.utc)
    max_age = max(1, int((result.expires_at - now).total_seconds()))
    secure = admin_cookie_secure()
    response.set_cookie(
        ADMIN_COOKIE,
        result.session_token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
    )
    # The CSRF value is intentionally readable by the same-origin admin page;
    # the session cookie itself remains HttpOnly.
    response.set_cookie(
        ADMIN_CSRF_COOKIE,
        result.csrf_token,
        max_age=max_age,
        httponly=False,
        secure=secure,
        samesite="strict",
        path="/",
    )


def _clear_admin_cookies(response: Response) -> None:
    secure = admin_cookie_secure()
    response.delete_cookie(
        ADMIN_COOKIE,
        path="/",
        secure=secure,
        httponly=True,
        samesite="strict",
    )
    response.delete_cookie(
        ADMIN_CSRF_COOKIE,
        path="/",
        secure=secure,
        httponly=False,
        samesite="strict",
    )


def get_admin_principal(
    request: Request,
    session: Session = Depends(get_session),
    settings: CollaborationSettings = Depends(get_settings),
) -> AdminPrincipal:
    return authenticate_admin(
        session,
        settings,
        request.cookies.get(ADMIN_COOKIE, ""),
    )


def get_admin_csrf_principal(
    request: Request,
    principal: AdminPrincipal = Depends(get_admin_principal),
    settings: CollaborationSettings = Depends(get_settings),
) -> AdminPrincipal:
    verify_csrf(settings, principal, request.headers.get(ADMIN_CSRF_HEADER, ""))
    return principal


@router.get("/admin", response_class=HTMLResponse, include_in_schema=False)
@router.get("/admin/", response_class=HTMLResponse, include_in_schema=False)
def admin_page() -> HTMLResponse:
    response = HTMLResponse(content=_page_html())
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'unsafe-inline'; "
        "style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"
    )
    return response


@router.post("/api/collaboration/admin/login", response_model=AdminLoginOut)
def admin_login(
    data: AdminLoginIn,
    response: Response,
    session: Session = Depends(get_session),
    settings: CollaborationSettings = Depends(get_settings),
) -> AdminLoginOut:
    result = login_admin(session, settings, data.username, data.password)
    _set_admin_cookies(response, result)
    _no_store(response)
    return AdminLoginOut(
        admin_id=result.principal.admin_id,
        username=result.principal.username,
        csrf_token=result.csrf_token,
        expires_at=result.expires_at,
    )


@router.post(
    "/api/collaboration/admin/logout",
    status_code=status.HTTP_204_NO_CONTENT,
)
def admin_logout(
    response: Response,
    session: Session = Depends(get_session),
    principal: AdminPrincipal = Depends(get_admin_csrf_principal),
) -> Response:
    revoke_admin_session(session, principal)
    _clear_admin_cookies(response)
    _no_store(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get(
    "/api/collaboration/admin/session",
    response_model=AdminSessionOut,
)
def admin_session(
    response: Response,
    principal: AdminPrincipal = Depends(get_admin_principal),
) -> AdminSessionOut:
    _no_store(response)
    return AdminSessionOut(
        admin_id=principal.admin_id,
        username=principal.username,
    )


@router.get(
    "/api/collaboration/admin/schools",
    response_model=list[AdminSchoolOut],
)
def admin_schools(
    response: Response,
    session: Session = Depends(get_session),
    _principal: AdminPrincipal = Depends(get_admin_principal),
) -> list[AdminSchoolOut]:
    _no_store(response)
    return [
        AdminSchoolOut(school_id=row.id, name=row.name)
        for row in list_schools(session)
    ]


@router.patch(
    "/api/collaboration/admin/schools/{school_id}",
    response_model=AdminSchoolOut,
)
def admin_update_school(
    school_id: UUID,
    data: AdminSchoolUpdateIn,
    response: Response,
    session: Session = Depends(get_session),
    principal: AdminPrincipal = Depends(get_admin_csrf_principal),
) -> AdminSchoolOut:
    updated = update_school_name(
        session,
        principal,
        school_id=school_id,
        expected_name=data.expected_name,
        new_name=data.new_name,
    )
    _no_store(response)
    return AdminSchoolOut(school_id=updated.id, name=updated.name)


@router.get(
    "/api/collaboration/admin/schools/{school_id}/teachers",
    response_model=list[AdminTeacherOut],
)
def admin_teachers(
    school_id: UUID,
    response: Response,
    session: Session = Depends(get_session),
    _principal: AdminPrincipal = Depends(get_admin_principal),
) -> list[AdminTeacherOut]:
    _no_store(response)
    return [
        AdminTeacherOut(
            teacher_id=row.id,
            display_name=row.display_name,
            active=bool(row.active),
        )
        for row in list_teachers(session, school_id)
    ]


@router.get(
    "/api/collaboration/admin/schools/{school_id}/terms",
    response_model=list[AdminTermOut],
)
def admin_terms(
    school_id: UUID,
    response: Response,
    session: Session = Depends(get_session),
    _principal: AdminPrincipal = Depends(get_admin_principal),
) -> list[AdminTermOut]:
    _no_store(response)
    return [
        AdminTermOut(
            term_id=row.term_id,
            school_id=row.school_id,
            name=row.name,
            start_date=row.start_date,
            end_date=row.end_date,
        )
        for row in list_terms(session, school_id)
    ]


@router.patch(
    "/api/collaboration/admin/schools/{school_id}/terms/{term_id}",
    response_model=AdminTermOut,
)
def admin_update_term(
    school_id: UUID,
    term_id: UUID,
    data: AdminTermUpdateIn,
    response: Response,
    session: Session = Depends(get_session),
    principal: AdminPrincipal = Depends(get_admin_csrf_principal),
) -> AdminTermOut:
    updated = update_term_name(
        session,
        principal,
        school_id=school_id,
        term_id=term_id,
        expected_name=data.expected_name,
        new_name=data.new_name,
    )
    _no_store(response)
    return AdminTermOut(
        term_id=updated.term_id,
        school_id=updated.school_id,
        name=updated.name,
        start_date=updated.start_date,
        end_date=updated.end_date,
    )


@router.post(
    "/api/collaboration/admin/codes",
    response_model=AdminCodeOut,
)
def admin_create_code(
    data: AdminCodeIn,
    response: Response,
    session: Session = Depends(get_session),
    settings: CollaborationSettings = Depends(get_settings),
    principal: AdminPrincipal = Depends(get_admin_csrf_principal),
) -> AdminCodeOut:
    issued = issue_code(
        session,
        settings,
        principal,
        school_id=data.school_id,
        teacher_id=data.teacher_id,
        purpose=data.purpose,
    )
    _no_store(response)
    return AdminCodeOut(
        code=issued.code,
        code_id=issued.code_id,
        purpose=issued.purpose,
        teacher_id=issued.teacher_id,
        teacher_name=issued.teacher_name,
        school_id=issued.school_id,
        expires_at=issued.expires_at,
    )


@router.post(
    "/api/collaboration/redeem",
    response_model=RedeemOut,
)
def teacher_redeem(
    data: RedeemIn,
    response: Response,
    session: Session = Depends(get_session),
    settings: CollaborationSettings = Depends(get_settings),
) -> RedeemOut:
    result = redeem_code(session, settings, data.code)
    _no_store(response)
    return RedeemOut(
        token=result.token,
        token_id=result.token_id,
        teacher_id=result.teacher_id,
        teacher_name=result.teacher_name,
        school_id=result.school_id,
        school_name=result.school_name,
        purpose=result.purpose,
        membership=result.membership,
    )
