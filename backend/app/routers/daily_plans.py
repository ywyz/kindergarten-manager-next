"""I3 daily plan routes: list / by-date / create-or-open / get / patch.

Every request re-derives permission on the backend from the authenticated
session; nothing is trusted from the client. Teachers operate only on their
current class assignment, admins must pass an explicit ``class_id`` class
context (list, by-date, create and get), and ``term_id`` is always
server-derived. Knowing a plan id never grants cross-class reads. DELETE /
recover / list-deleted routes are intentionally absent (I3 decision B).
"""

from contextlib import contextmanager
from datetime import date
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_auth_snapshot, get_current_account
from app.models import Account, DailyPlan, DailyPlanContent, TeacherAssignment
from app.schemas import (
    DailyPlanCreateIn,
    DailyPlanListItemOut,
    DailyPlanListOut,
    DailyPlanOut,
    DailyPlanPatchIn,
)
from app.services import auth_service, daily_plan_service
from app.services.auth_service import AuthSnapshot
from app.services.config_errors import ConfigServiceError
from app.services.daily_plan_content import ContentValidationError
from app.services.daily_plan_service import (
    UNSET,
    DailyPlanDataError,
    DailyPlanDateNotEligible,
    DailyPlanForbidden,
    DailyPlanNotFound,
    DailyPlanOutsideTerm,
    DailyPlanServiceError,
    DailyPlanValidationError,
    DailyPlanVersionConflict,
    DailyPlanYearNotCovered,
)

router = APIRouter(tags=["daily-plans"])


def _validation_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail="VALIDATION_ERROR",
    )


def _forbidden() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="FORBIDDEN"
    )


@contextmanager
def _service_errors() -> Iterator[None]:
    """Map I3 service exceptions onto the spec's {error:{code}} HTTP errors."""
    try:
        yield
    except DailyPlanNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="DAILY_PLAN_NOT_FOUND",
        ) from None
    except DailyPlanVersionConflict:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="VERSION_CONFLICT"
        ) from None
    except DailyPlanForbidden:
        raise _forbidden() from None
    except DailyPlanOutsideTerm:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="OUTSIDE_TERM",
        ) from None
    except DailyPlanDateNotEligible:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="DATE_NOT_ELIGIBLE",
        ) from None
    except DailyPlanYearNotCovered:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="YEAR_NOT_COVERED",
        ) from None
    except (DailyPlanValidationError, ContentValidationError):
        raise _validation_error() from None
    except auth_service.AuthRequired:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="AUTH_REQUIRED"
        ) from None
    except auth_service.ClassNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="CLASS_NOT_FOUND"
        ) from None
    except auth_service.Forbidden:
        raise _forbidden() from None
    except DailyPlanDataError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SERVICE_UNAVAILABLE",
        ) from None
    except ConfigServiceError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SERVICE_UNAVAILABLE",
        ) from None
    except DailyPlanServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.code
        ) from None


def _reject_term_id(term_id: str | None) -> None:
    """term_id is always server-derived; clients may never supply it."""
    if term_id is not None:
        raise _validation_error()


def _resolve_read_class_id(
    db: Session, account: Account, class_id: str | None
) -> str:
    """Backend re-judged class context for a read request."""
    if account.role == "admin":
        if not class_id:
            raise _validation_error()
        return class_id
    if account.role != "teacher":
        raise _forbidden()
    if class_id is not None:
        raise _validation_error()
    assignment = db.get(TeacherAssignment, account.id)
    if assignment is None:
        raise _forbidden()
    return assignment.class_id


def _check_create_shape(snapshot: AuthSnapshot, data: DailyPlanCreateIn) -> None:
    # Presence is judged on model_fields_set, not on the value: a teacher
    # sending class_id even as explicit null is rejected, and an admin must
    # both include class_id and supply a non-empty value.
    if snapshot.role == "admin":
        if "class_id" not in data.model_fields_set or not data.class_id:
            raise _validation_error()
    elif snapshot.role == "teacher":
        if "class_id" in data.model_fields_set:
            raise _validation_error()
    else:
        raise _forbidden()


def _optional(data, field: str, sentinel):
    """Distinguish an omitted optional field from an explicit null."""
    return getattr(data, field) if field in data.model_fields_set else sentinel


def _list_item(plan: DailyPlan) -> dict:
    return {
        "id": plan.id,
        "plan_date": plan.plan_date,
        "week_number": plan.week_number,
        "weekday": plan.weekday,
        "creator_id": plan.creator_id,
        "creator_display_name": plan.creator_display_name,
        "current_content_version": plan.current_content_version,
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
    }


def _plan_out(plan: DailyPlan, content: DailyPlanContent, summary: dict) -> dict:
    # Immutable identity snapshot + current content version only; soft-delete
    # columns are never serialized (I3 decision B), game ids stay intact
    # because adopted_content is passed through as stored.
    return {
        "id": plan.id,
        "class_id": plan.class_id,
        "term_id": plan.term_id,
        "plan_date": plan.plan_date,
        "week_number": plan.week_number,
        "weekday": plan.weekday,
        "creator_id": plan.creator_id,
        "creator_display_name": plan.creator_display_name,
        "current_content_id": plan.current_content_id,
        "current_content_version": plan.current_content_version,
        "content": {
            "id": content.id,
            "version": content.version,
            "raw_lesson_plan": content.raw_lesson_plan,
            "split_baseline": content.split_baseline,
            "adopted_content": content.adopted_content,
            "editor_id": content.editor_id,
            "created_at": content.created_at,
        },
        "school_name": plan.school_name,
        "class_name": plan.class_name,
        "grade": plan.grade,
        "weekly_sync_state": summary,
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
    }


@router.get("/daily-plans", response_model=DailyPlanListOut)
def list_daily_plans(
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    class_id: str | None = None,
    term_id: str | None = None,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    _reject_term_id(term_id)
    resolved_class_id = _resolve_read_class_id(db, account, class_id)
    with _service_errors():
        rows, total = daily_plan_service.list_plans(
            db,
            class_id=resolved_class_id,
            from_date=from_date,
            to_date=to_date,
            offset=offset,
            limit=limit,
        )
    return {
        "items": [_list_item(row) for row in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


# Registered before /daily-plans/{plan_id} so "by-date" is not captured
# as a path parameter.
@router.get("/daily-plans/by-date", response_model=DailyPlanOut)
def get_daily_plan_by_date(
    plan_date: date = Query(...),
    class_id: str | None = None,
    term_id: str | None = None,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    _reject_term_id(term_id)
    resolved_class_id = _resolve_read_class_id(db, account, class_id)
    with _service_errors():
        plan, content = daily_plan_service.get_by_date(
            db, resolved_class_id, plan_date
        )
        summary = daily_plan_service.weekly_sync_summary(db, plan)
    return _plan_out(plan, content, summary)


@router.post(
    "/daily-plans",
    response_model=DailyPlanOut,
    status_code=status.HTTP_201_CREATED,
)
def create_or_open_daily_plan(
    response: Response,
    data: DailyPlanCreateIn,
    db: Session = Depends(get_db),
    snapshot: AuthSnapshot = Depends(get_auth_snapshot),
):
    _check_create_shape(snapshot, data)
    with _service_errors():
        plan, content, created = daily_plan_service.create_or_open(
            db,
            snapshot,
            plan_date=data.plan_date,
            class_id=data.class_id,
            raw_lesson_plan=_optional(data, "raw_lesson_plan", UNSET),
            adopted_content=_optional(data, "adopted_content", UNSET),
        )
        summary = daily_plan_service.weekly_sync_summary(db, plan)
    if not created:
        # Duplicate create opens the existing row: 200, creator and content
        # untouched. A fresh create returns the decorator's 201.
        response.status_code = status.HTTP_200_OK
    return _plan_out(plan, content, summary)


@router.get("/daily-plans/{plan_id}", response_model=DailyPlanOut)
def get_daily_plan(
    plan_id: str,
    class_id: str | None = None,
    term_id: str | None = None,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    _reject_term_id(term_id)
    resolved_class_id = _resolve_read_class_id(db, account, class_id)
    with _service_errors():
        plan, content = daily_plan_service.get(db, plan_id)
        if plan.class_id != resolved_class_id:
            # Teachers may never read another class (403). Admins read only
            # inside the explicit class context they passed: a mismatched id
            # is not found there (404), never a cross-class leak.
            if account.role == "admin":
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="DAILY_PLAN_NOT_FOUND",
                )
            raise _forbidden()
        summary = daily_plan_service.weekly_sync_summary(db, plan)
    return _plan_out(plan, content, summary)


@router.patch("/daily-plans/{plan_id}", response_model=DailyPlanOut)
def patch_daily_plan(
    plan_id: str,
    data: DailyPlanPatchIn,
    db: Session = Depends(get_db),
    snapshot: AuthSnapshot = Depends(get_auth_snapshot),
):
    # Creator-or-admin permission is re-judged inside the locked service
    # transaction; split_baseline never reaches the service from here.
    with _service_errors():
        plan, content = daily_plan_service.save(
            db,
            snapshot,
            plan_id=plan_id,
            expected_content_version=data.expected_content_version,
            raw_lesson_plan=_optional(data, "raw_lesson_plan", UNSET),
            adopted_content=_optional(data, "adopted_content", UNSET),
        )
        summary = daily_plan_service.weekly_sync_summary(db, plan)
    return _plan_out(plan, content, summary)
