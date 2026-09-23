from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app import security
from app.database import get_db
from app.deps import get_auth_snapshot, require_admin
from app.models import (
    Account,
    Class,
    ConfigurationChange,
    SchoolSettings,
)
from app.schemas import (
    ApplyIn,
    ApplyOut,
    AssignmentIn,
    AssignmentOut,
    ClassDetailOut,
    ClassListOut,
    ConfigurationChangeOut,
    PasswordResetIn,
    PasswordResetOut,
    Proposal,
    SchoolSettingsOut,
    TeacherWithAssignmentListOut,
)
from app.services import auth_service, config_service

router = APIRouter(prefix="/admin", tags=["admin"])


def _escape_like(value: str) -> str:
    """Escape SQL LIKE wildcards so % and _ are matched literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _validate_paging(offset: int, limit: int) -> None:
    if limit < 1 or limit > 100 or offset < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="VALIDATION_ERROR",
        )


def _mysql_error_code(exc: Exception) -> int | None:
    orig = getattr(exc, "orig", None)
    args = getattr(orig, "args", ())
    if args and isinstance(args[0], int):
        return args[0]
    return None


def _is_class_name_duplicate(exc: IntegrityError) -> bool:
    if _mysql_error_code(exc) != 1062:
        return False
    orig = getattr(exc, "orig", None)
    message = str(getattr(orig, "args", ("", ""))[1:])
    return "uq_classes_name" in message


def _conflict_or_503(exc: OperationalError) -> HTTPException:
    """Map deadlock (1213) and lock-wait timeout (1205) to retryable 409."""
    if _mysql_error_code(exc) in (1205, 1213):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="VERSION_CONFLICT",
        )
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="SERVICE_UNAVAILABLE",
    )


# ---------------------------------------------------------------------------
# Teachers (extended list + first assignment + I1 password reset)
# ---------------------------------------------------------------------------


@router.get("/teachers", response_model=TeacherWithAssignmentListOut)
def list_teachers(
    request: Request,
    offset: int = 0,
    limit: int = 20,
    q: str | None = None,
    assignment_status: str | None = None,
    db: Session = Depends(get_db),
    admin: Account = Depends(require_admin),
):
    _validate_paging(offset, limit)
    if assignment_status not in (None, "assigned", "pending_assignment"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="VALIDATION_ERROR",
        )

    from app.models import TeacherAssignment

    stmt = select(Account).where(Account.role == "teacher")
    if q:
        escaped = _escape_like(q.strip().lower())
        pattern = f"%{escaped}%"
        stmt = stmt.where(
            (Account.username.like(pattern, escape="\\"))
            | (Account.display_name.ilike(pattern, escape="\\"))
        )
    if assignment_status is not None:
        if assignment_status == "assigned":
            stmt = stmt.where(
                Account.id.in_(select(TeacherAssignment.teacher_id))
            )
        else:
            stmt = stmt.where(
                Account.id.not_in(select(TeacherAssignment.teacher_id))
            )

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = (
        db.execute(
            stmt.order_by(Account.created_at, Account.id)
            .offset(offset)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    assignments = auth_service.assignment_map(db, [a.id for a in items])
    result_items = []
    for account in items:
        assignment = assignments.get(account.id)
        result_items.append(
            {
                **auth_service.account_to_out(account),
                "class_id": assignment.class_id if assignment else None,
                "assignment_status": (
                    "assigned" if assignment else "pending_assignment"
                ),
            }
        )
    return {
        "items": result_items,
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.post(
    "/teachers/{teacher_id}/assignment",
    response_model=AssignmentOut,
)
def assign_teacher(
    request: Request,
    teacher_id: str,
    data: AssignmentIn,
    db: Session = Depends(get_db),
    admin_snapshot: auth_service.AuthSnapshot = Depends(get_auth_snapshot),
):
    try:
        target, class_id = auth_service.assign_teacher(
            db,
            admin_snapshot,
            teacher_id,
            data.class_id,
            data.expected_version,
            data.expected_class_version,
        )
    except auth_service.Forbidden:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="FORBIDDEN",
        )
    except auth_service.AccountNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ACCOUNT_NOT_FOUND",
        )
    except auth_service.ClassNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="CLASS_NOT_FOUND",
        )
    except auth_service.AlreadyAssigned:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="ALREADY_ASSIGNED",
        )
    except auth_service.VersionConflict:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="VERSION_CONFLICT",
        )
    except auth_service.AuthRequired:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AUTH_REQUIRED",
        )
    return {
        "account": auth_service.account_to_out(target),
        "class_id": class_id,
        "assignment_status": "assigned",
    }


@router.post(
    "/teachers/{teacher_id}/password-reset",
    response_model=PasswordResetOut,
)
def reset_teacher_password(
    request: Request,
    teacher_id: str,
    data: PasswordResetIn,
    db: Session = Depends(get_db),
    admin_snapshot: auth_service.AuthSnapshot = Depends(get_auth_snapshot),
):
    new_password_hash = security.hash_password(data.new_password)
    try:
        target = auth_service.admin_reset_password(
            db,
            admin_snapshot,
            teacher_id,
            new_password_hash,
            data.expected_version,
        )
    except auth_service.Forbidden:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="FORBIDDEN",
        )
    except auth_service.AccountNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ACCOUNT_NOT_FOUND",
        )
    except auth_service.VersionConflict:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="VERSION_CONFLICT",
        )
    except auth_service.InvalidCredentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AUTH_REQUIRED",
        )
    except auth_service.AuthRequired:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AUTH_REQUIRED",
        )
    return {"account": auth_service.account_to_out(target), "sessions_revoked": True}


# ---------------------------------------------------------------------------
# School settings
# ---------------------------------------------------------------------------


@router.get("/school-settings", response_model=SchoolSettingsOut)
def get_school_settings(
    db: Session = Depends(get_db),
    admin: Account = Depends(require_admin),
):
    school = db.scalar(
        select(SchoolSettings).where(SchoolSettings.id == "singleton")
    )
    if school is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SERVICE_UNAVAILABLE",
        )
    return school


# ---------------------------------------------------------------------------
# Classes
# ---------------------------------------------------------------------------


@router.get("/classes", response_model=ClassListOut)
def list_classes(
    offset: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
    admin: Account = Depends(require_admin),
):
    _validate_paging(offset, limit)
    total = db.scalar(select(func.count()).select_from(Class)) or 0
    items = (
        db.execute(
            select(Class).order_by(Class.created_at, Class.id)
            .offset(offset)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return {"items": items, "total": total, "offset": offset, "limit": limit}


@router.get("/classes/{class_id}", response_model=ClassDetailOut)
def get_class(
    class_id: str,
    db: Session = Depends(get_db),
    admin: Account = Depends(require_admin),
):
    school_class = db.get(Class, class_id)
    if school_class is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="CLASS_NOT_FOUND",
        )
    assigned = _assigned_teachers(db, class_id)
    return {
        "id": school_class.id,
        "name": school_class.name,
        "grade": school_class.grade,
        "header_teacher_names": school_class.header_teacher_names,
        "caregiver_name": school_class.caregiver_name,
        "version": school_class.version,
        "assigned_teachers": [
            {
                "id": teacher.id,
                "username": teacher.username,
                "display_name": teacher.display_name,
                "version": teacher.version,
            }
            for teacher in assigned
        ],
    }


def _assigned_teachers(db: Session, class_id: str):
    from app.models import TeacherAssignment

    rows = db.scalars(
        select(TeacherAssignment).where(TeacherAssignment.class_id == class_id)
    ).all()
    return [db.get(Account, row.teacher_id) for row in rows]


# ---------------------------------------------------------------------------
# Configuration change preview / apply
# ---------------------------------------------------------------------------


def _proposal_payload(data: Proposal) -> tuple[str, dict]:
    return data.kind, data.model_dump(exclude={"kind"}, exclude_unset=True)


@router.post(
    "/configuration-changes/preview",
    response_model=ConfigurationChangeOut,
    status_code=status.HTTP_201_CREATED,
)
def create_preview(
    request: Request,
    data: Proposal,
    db: Session = Depends(get_db),
    admin_snapshot: auth_service.AuthSnapshot = Depends(get_auth_snapshot),
):
    kind, payload = _proposal_payload(data)
    try:
        row = config_service.create_preview(
            db, admin_snapshot, kind, payload
        )
    except config_service.NoChanges:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="NO_CHANGES",
        )
    except config_service.ClassNameTaken:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="CLASS_NAME_TAKEN",
        )
    except config_service.TermOverlap:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="TERM_OVERLAP",
        )
    except config_service.CalendarError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SERVICE_UNAVAILABLE",
        )
    except config_service.PreviewForbidden:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="FORBIDDEN",
        )
    except config_service.PreviewStale:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="VERSION_CONFLICT",
        )
    except IntegrityError as exc:
        if _is_class_name_duplicate(exc):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="CLASS_NAME_TAKEN")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="SERVICE_UNAVAILABLE")
    except OperationalError as exc:
        raise _conflict_or_503(exc)
    except auth_service.AuthRequired:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AUTH_REQUIRED",
        )
    except (config_service.ValidationError, ValueError):
        # Must come after AuthRequired (ValidationError is also a ValueError)
        # and after the narrower service exceptions.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="VALIDATION_ERROR",
        )
    return _change_out(row)


@router.get(
    "/configuration-changes/{change_id}",
    response_model=ConfigurationChangeOut,
)
def get_preview(
    change_id: str,
    db: Session = Depends(get_db),
    admin_snapshot: auth_service.AuthSnapshot = Depends(get_auth_snapshot),
):
    try:
        row = config_service.get_preview(db, admin_snapshot, change_id)
    except config_service.PreviewNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="CHANGE_NOT_FOUND",
        )
    except config_service.PreviewForbidden:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="FORBIDDEN",
        )
    return _change_out(row)


@router.post(
    "/configuration-changes/{change_id}/apply",
    response_model=ApplyOut,
)
def apply_preview(
    change_id: str,
    data: ApplyIn,
    db: Session = Depends(get_db),
    admin_snapshot: auth_service.AuthSnapshot = Depends(get_auth_snapshot),
):
    try:
        row = config_service.apply_preview(db, admin_snapshot, change_id)
    except config_service.PreviewNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="CHANGE_NOT_FOUND",
        )
    except config_service.PreviewForbidden:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="FORBIDDEN",
        )
    except config_service.PreviewExpired:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PREVIEW_EXPIRED",
        )
    except config_service.PreviewStale:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PREVIEW_STALE",
        )
    except IntegrityError as exc:
        if _is_class_name_duplicate(exc):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="CLASS_NAME_TAKEN")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="SERVICE_UNAVAILABLE")
    except OperationalError as exc:
        raise _conflict_or_503(exc)
    except config_service.ClassNameTaken:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="CLASS_NAME_TAKEN",
        )
    except config_service.TermOverlap:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="TERM_OVERLAP",
        )
    except config_service.CalendarError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SERVICE_UNAVAILABLE",
        )
    except config_service.DependencyNotReady:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="DEPENDENCY_NOT_READY",
        )
    except auth_service.AuthRequired:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AUTH_REQUIRED",
        )
    return {
        "status": "applied",
        "result_reference": row.result_reference,
        "versions": row.result_versions or {},
    }


def _change_out(row: ConfigurationChange) -> dict:
    summary = row.impact_summary
    return {
        "id": row.id,
        "kind": row.kind,
        "target_id": row.target_id,
        "base_versions": row.base_versions,
        "candidate": row.normalized_proposal if row.status == "pending" else None,
        "changes": summary.get("changes", []),
        "impact": summary.get("impact", {}),
        "blockers": summary.get("blockers", []),
        "expires_at": row.expires_at.isoformat(),
        "status": row.status,
        "applied_at": row.applied_at.isoformat() if row.applied_at else None,
        "result_reference": row.result_reference,
    }
