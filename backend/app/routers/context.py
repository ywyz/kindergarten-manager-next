"""Read-only endpoints for teachers with a real class assignment.

Teachers can read their own class configuration and school-wide information.
No other class's account data is exposed. Term/calendar reads are added in a
later phase.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_account
from app.models import Account, Class, SchoolSettings, TeacherAssignment
from datetime import date

from fastapi import Query

from app.models import Term
from app.schemas import (
    CalendarOut,
    ClassContextOut,
    TermListOut,
    TermOut,
)
from app.services import calendar_read_service

router = APIRouter(tags=["class-context"])


@router.get("/class-context", response_model=ClassContextOut)
def get_class_context(
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    if account.role != "teacher":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="FORBIDDEN",
        )
    assignment = db.get(TeacherAssignment, account.id)
    if assignment is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="FORBIDDEN",
        )
    school_class = db.get(Class, assignment.class_id)
    if school_class is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SERVICE_UNAVAILABLE",
        )
    school = db.scalar(
        select(SchoolSettings).where(SchoolSettings.id == "singleton")
    )
    if school is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SERVICE_UNAVAILABLE",
        )
    return {
        "class": school_class,
        "school_name": school.school_name,
        "school_version": school.version,
    }


def _require_assigned_teacher(db, account):
    if account.role != "teacher":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="FORBIDDEN")
    if db.get(TeacherAssignment, account.id) is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="FORBIDDEN")


@router.get("/terms", response_model=TermListOut)
def read_terms(
    offset: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    _require_assigned_teacher(db, account)
    if limit < 1 or limit > 100 or offset < 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail="VALIDATION_ERROR")
    rows, total = calendar_read_service.list_terms(
        db, offset=offset, limit=limit
    )
    return {
        "items": [TermOut.model_validate(row) for row in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/calendar", response_model=CalendarOut)
def read_calendar(
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    _require_assigned_teacher(db, account)
    try:
        items, schedule_version = calendar_read_service.explain_range(
            db, from_date, to_date
        )
    except calendar_read_service.CalendarDataError:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="SERVICE_UNAVAILABLE")
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail="VALIDATION_ERROR")
    return {
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
        "schedule_version": schedule_version or 0,
        "items": items,
    }
