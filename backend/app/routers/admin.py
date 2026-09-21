from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import security
from app.database import get_db
from app.deps import get_auth_snapshot, require_admin
from app.models import Account
from app.schemas import PasswordResetIn, PasswordResetOut, TeacherListOut
from app.services import auth_service

router = APIRouter(prefix="/admin", tags=["admin"])


def _escape_like(value: str) -> str:
    """Escape SQL LIKE wildcards so % and _ are matched literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/teachers", response_model=TeacherListOut)
def list_teachers(
    request: Request,
    offset: int = 0,
    limit: int = 20,
    q: str | None = None,
    db: Session = Depends(get_db),
    admin: Account = Depends(require_admin),
):
    if limit < 1 or limit > 100 or offset < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="VALIDATION_ERROR",
        )

    stmt = select(Account).where(Account.role == "teacher")
    if q:
        escaped = _escape_like(q.strip().lower())
        pattern = f"%{escaped}%"
        stmt = stmt.where(
            (Account.username.like(pattern, escape="\\"))
            | (Account.display_name.ilike(pattern, escape="\\"))
        )
    total_stmt = select(func.count()).select_from(stmt.subquery())
    total = db.scalar(total_stmt) or 0

    stmt = stmt.order_by(Account.created_at, Account.id).offset(offset).limit(limit)
    items = db.execute(stmt).scalars().all()
    return {
        "items": [auth_service.account_to_out(a) for a in items],
        "total": total,
        "offset": offset,
        "limit": limit,
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
