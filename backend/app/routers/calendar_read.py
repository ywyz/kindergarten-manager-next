"""Admin read endpoints for terms and the persisted effective calendar."""

from datetime import date

from fastapi import APIRouter, Depends, Query, status
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_admin
from app.models import Account, Term
from app.schemas import CalendarOut, TermListOut, TermOut
from app.services import calendar_read_service
from app.services.config_errors import ValidationError

router = APIRouter(prefix="/admin", tags=["admin", "calendar"])


def _validate_paging(offset: int, limit: int) -> None:
    if limit < 1 or limit > 100 or offset < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="VALIDATION_ERROR",
        )


@router.get("/terms", response_model=TermListOut)
def list_terms(
    offset: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
    admin: Account = Depends(require_admin),
):
    _validate_paging(offset, limit)
    rows, total = calendar_read_service.list_terms(
        db, offset=offset, limit=limit
    )
    return {
        "items": [TermOut.model_validate(row) for row in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/terms/{term_id}", response_model=TermOut)
def get_term(
    term_id: str,
    db: Session = Depends(get_db),
    admin: Account = Depends(require_admin),
):
    row = db.get(Term, term_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="TERM_NOT_FOUND",
        )
    return TermOut.model_validate(row)


@router.get("/calendar", response_model=CalendarOut)
def read_calendar(
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    db: Session = Depends(get_db),
    admin: Account = Depends(require_admin),
):
    try:
        items, schedule_version = calendar_read_service.explain_range(
            db, from_date, to_date
        )
    except calendar_read_service.CalendarDataError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SERVICE_UNAVAILABLE",
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="VALIDATION_ERROR",
        )

    # explain_range uses the single request snapshot; schedule_version is
    # taken from school_settings within that snapshot for freshness.
    return {
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
        "schedule_version": schedule_version or 0,
        "items": items,
    }
