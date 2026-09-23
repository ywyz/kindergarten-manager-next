"""I4 weekly plan routes: list / create-open / detail / patch / refresh /
confirm / confirmation history (8 routes).

Every request re-judges permission on the backend from the authenticated
session. Teachers derive their class from the current assignment and never
send ``class_id`` (create body presence — including explicit null — and
create query presence — including ``?class_id=`` — are 422); admins must
pass an explicit ``class_id`` on reads and writes, can
never create or confirm (403), and a mismatched admin class context is 404
WEEKLY_PLAN_NOT_FOUND. Same-class non-owner teachers are read-only (403 on
writes); cross-class teachers are 403.

Routes never open a transaction or bypass the locked permission prefix:
all four write paths delegate to the slice-1 service entries, all reads to
the read-only query service (GET never writes, never rebuilds drafts,
never touches the projection). CONFIRM_ACK_REQUIRED answers 409 with the
recomputed system facts in the error body; VERSION_CONFLICT is 409 and
never silently overwrites.
"""

from contextlib import contextmanager
from typing import Iterator

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_auth_snapshot, get_current_account
from app.models import Account, TeacherAssignment
from app.schemas import (
    WeeklyPlanConfirmationListOut,
    WeeklyPlanConfirmationOut,
    WeeklyPlanCreateIn,
    WeeklyPlanDetailOut,
    WeeklyPlanListOut,
    WeeklyPlanPatchIn,
    WeeklyPlanRefreshIn,
    WeeklyPlanConfirmIn,
)
from app.services import (
    auth_service,
    weekly_plan_read_service,
    weekly_plan_service,
)
from app.services.auth_service import AuthSnapshot
from app.services.config_errors import ConfigServiceError
from app.services.weekly_plan_content import ContentValidationError
from app.services.weekly_plan_service import (
    WeeklyPlanConfirmAckRequired,
    WeeklyPlanDataError,
    WeeklyPlanForbidden,
    WeeklyPlanNotFound,
    WeeklyPlanServiceError,
    WeeklyPlanTermNotFound,
    WeeklyPlanValidationError,
    WeeklyPlanVersionConflict,
)

router = APIRouter(tags=["weekly-plans"])

# Patch body fields the client may edit; ``source``/``effective`` are not
# among them and ``extra="forbid"`` rejects any attempt to send them.
_PATCH_BODY_FIELDS = (
    "theme",
    "deterministic_overrides",
    "outdoor_game_slots",
    "focus_area",
    "weekly_columns",
)


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
    """Map I4 service exceptions onto the spec's status/code table.

    ``CONFIRM_ACK_REQUIRED`` is re-raised so the confirm route can attach
    the recomputed facts to the 409 body (the shared HTTP handler only
    forwards code/message).
    """
    try:
        yield
    except WeeklyPlanConfirmAckRequired:
        raise
    except WeeklyPlanNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WEEKLY_PLAN_NOT_FOUND",
        ) from None
    except WeeklyPlanTermNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="TERM_NOT_FOUND"
        ) from None
    except WeeklyPlanVersionConflict:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="VERSION_CONFLICT"
        ) from None
    except WeeklyPlanForbidden:
        raise _forbidden() from None
    except (WeeklyPlanValidationError, ContentValidationError):
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
    except WeeklyPlanDataError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SERVICE_UNAVAILABLE",
        ) from None
    except ConfigServiceError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SERVICE_UNAVAILABLE",
        ) from None
    except WeeklyPlanServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.code
        ) from None


def _resolve_read_class_id(
    db: Session, account: Account, class_id: str | None
) -> str:
    """Backend re-judged class context for a read request (no locks)."""
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


def _check_create_shape(
    snapshot: AuthSnapshot, data: WeeklyPlanCreateIn, request: Request
) -> None:
    # Teacher: class_id presence is judged on model_fields_set (body, even
    # explicit null) and on raw query params (including ``?class_id=``), so
    # both are a 422. Admin: creation is always 403 (permission first), with
    # or without a class_id in the body or query.
    if snapshot.role == "teacher":
        if (
            "class_id" in data.model_fields_set
            or "class_id" in request.query_params
        ):
            raise _validation_error()
    elif snapshot.role != "admin":
        raise _forbidden()


def _patch_body(data: WeeklyPlanPatchIn) -> dict:
    """Only fields present in the payload; omitted vs explicit null kept."""
    return {
        name: getattr(data, name)
        for name in _PATCH_BODY_FIELDS
        if name in data.model_fields_set
    }


def _confirmation_out(row) -> dict:
    return {
        "id": row.id,
        "weekly_plan_id": row.weekly_plan_id,
        "version": row.version,
        "draft_version": row.draft_version,
        "content": weekly_plan_read_service.public_content(row.content),
        "facts": row.facts,
        "confirmed_by": row.confirmed_by,
        "created_at": row.created_at,
    }


@router.get("/weekly-plans", response_model=WeeklyPlanListOut)
def list_weekly_plans(
    term_id: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    class_id: str | None = None,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    resolved_class_id = _resolve_read_class_id(db, account, class_id)
    with _service_errors():
        items, total = weekly_plan_read_service.list_plans(
            db,
            class_id=resolved_class_id,
            term_id=term_id,
            offset=offset,
            limit=limit,
        )
    return {"items": items, "total": total, "offset": offset, "limit": limit}


@router.post(
    "/weekly-plans",
    response_model=WeeklyPlanDetailOut,
    status_code=status.HTTP_201_CREATED,
)
def create_or_open_weekly_plan(
    response: Response,
    data: WeeklyPlanCreateIn,
    request: Request,
    db: Session = Depends(get_db),
    snapshot: AuthSnapshot = Depends(get_auth_snapshot),
):
    _check_create_shape(snapshot, data, request)
    with _service_errors():
        result = weekly_plan_service.create_or_open_weekly_plan(
            db,
            snapshot,
            term_id=data.term_id,
            week_number=data.week_number,
            theme=data.theme,
            class_id=data.class_id,
        )
        detail = weekly_plan_read_service.assemble_from_result(
            db,
            result,
            account_id=snapshot.account_id,
            role=snapshot.role,
        )
    if not result.created:
        # Duplicate create opens the existing row: 200, creator/owner kept.
        response.status_code = status.HTTP_200_OK
    return detail


@router.get("/weekly-plans/{plan_id}", response_model=WeeklyPlanDetailOut)
def get_weekly_plan(
    plan_id: str,
    class_id: str | None = None,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    resolved_class_id = _resolve_read_class_id(db, account, class_id)
    with _service_errors():
        return weekly_plan_read_service.get_detail(
            db,
            plan_id,
            account_id=account.id,
            role=account.role,
            class_id=resolved_class_id,
        )


@router.patch("/weekly-plans/{plan_id}", response_model=WeeklyPlanDetailOut)
def patch_weekly_plan(
    plan_id: str,
    data: WeeklyPlanPatchIn,
    class_id: str | None = None,
    db: Session = Depends(get_db),
    snapshot: AuthSnapshot = Depends(get_auth_snapshot),
):
    # Owner/admin permission, class context and version checks are all
    # re-judged inside the locked service transaction (teacher class_id
    # smuggling -> 422, admin missing class_id -> 422, admin mismatch -> 404).
    with _service_errors():
        result = weekly_plan_service.save_weekly_plan(
            db,
            snapshot,
            plan_id=plan_id,
            expected_draft_version=data.expected_draft_version,
            patch=_patch_body(data),
            class_id=class_id,
        )
        return weekly_plan_read_service.assemble_from_result(
            db,
            result,
            account_id=snapshot.account_id,
            role=snapshot.role,
        )


@router.post(
    "/weekly-plans/{plan_id}/refresh-sources",
    response_model=WeeklyPlanDetailOut,
)
def refresh_weekly_plan_sources(
    plan_id: str,
    data: WeeklyPlanRefreshIn,
    class_id: str | None = None,
    db: Session = Depends(get_db),
    snapshot: AuthSnapshot = Depends(get_auth_snapshot),
):
    with _service_errors():
        result = weekly_plan_service.refresh_weekly_sources(
            db,
            snapshot,
            plan_id=plan_id,
            expected_draft_version=data.expected_draft_version,
            class_id=class_id,
        )
        return weekly_plan_read_service.assemble_from_result(
            db,
            result,
            account_id=snapshot.account_id,
            role=snapshot.role,
            refreshed_sources=result.refreshed_sources,
        )


@router.post(
    "/weekly-plans/{plan_id}/confirm",
    response_model=WeeklyPlanConfirmationOut,
    status_code=status.HTTP_201_CREATED,
)
def confirm_weekly_plan(
    plan_id: str,
    data: WeeklyPlanConfirmIn,
    class_id: str | None = None,
    db: Session = Depends(get_db),
    snapshot: AuthSnapshot = Depends(get_auth_snapshot),
):
    try:
        with _service_errors():
            result = weekly_plan_service.confirm_weekly_plan(
                db,
                snapshot,
                plan_id=plan_id,
                expected_draft_version=data.expected_draft_version,
                acknowledge_missing=data.acknowledge_missing,
                acknowledge_stale=data.acknowledge_stale,
                note=data.note,
                class_id=class_id,
            )
    except WeeklyPlanConfirmAckRequired as exc:
        # Facts recomputed under lock ride along; never confirm silently.
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error": {
                    "code": "CONFIRM_ACK_REQUIRED",
                    "message": "需要确认缺失或陈旧事实",
                    "facts": exc.facts,
                }
            },
            headers={"Cache-Control": "no-store"},
        )
    return _confirmation_out(result.confirmed)


@router.get(
    "/weekly-plans/{plan_id}/confirmations",
    response_model=WeeklyPlanConfirmationListOut,
)
def list_weekly_plan_confirmations(
    plan_id: str,
    class_id: str | None = None,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    resolved_class_id = _resolve_read_class_id(db, account, class_id)
    with _service_errors():
        return weekly_plan_read_service.list_confirmations(
            db, plan_id, role=account.role, class_id=resolved_class_id
        )


@router.get(
    "/weekly-plans/{plan_id}/confirmations/{version}",
    response_model=WeeklyPlanConfirmationOut,
)
def get_weekly_plan_confirmation(
    plan_id: str,
    version: int = Path(..., ge=1),
    class_id: str | None = None,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    resolved_class_id = _resolve_read_class_id(db, account, class_id)
    with _service_errors():
        return weekly_plan_read_service.get_confirmation(
            db,
            plan_id,
            version,
            role=account.role,
            class_id=resolved_class_id,
        )
