"""Read-only weekly pending-projection state (option A).

GET /weekly-plan-sync-states/{class_id}/{term_id}/{week_number} returns the
full projection: status (I3: only ``pending_projection``), deterministic
themes, the complete game source manifest, the complete current-week source
manifest and the last-trigger audit summary.

Permission is re-judged per request: teachers may read only their current
class (the path ``class_id`` must match their assignment), admins read with
the class context explicit in the path. When no projection row exists the
route answers 404 WEEKLY_PLAN_SYNC_NOT_FOUND — the chosen consistent
engineering semantics for an unreadable projection (never a silent empty
state).
"""

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_account
from app.models import Account, TeacherAssignment
from app.schemas import WeeklyPlanSyncStateOut
from app.services import daily_plan_service

router = APIRouter(tags=["weekly-plan-sync-states"])


@router.get(
    "/weekly-plan-sync-states/{class_id}/{term_id}/{week_number}",
    response_model=WeeklyPlanSyncStateOut,
)
def read_weekly_plan_sync_state(
    class_id: str,
    term_id: str,
    week_number: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    if account.role == "teacher":
        assignment = db.get(TeacherAssignment, account.id)
        if assignment is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="FORBIDDEN"
            )
        if assignment.class_id != class_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="FORBIDDEN"
            )
    elif account.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="FORBIDDEN"
        )

    row = daily_plan_service.get_sync_state(
        db, class_id, term_id, week_number
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WEEKLY_PLAN_SYNC_NOT_FOUND",
        )
    return {
        "id": row.id,
        "class_id": row.class_id,
        "term_id": row.term_id,
        "week_number": row.week_number,
        "status": row.status,
        "deterministic_themes": row.deterministic_themes,
        "game_source_manifest": row.game_source_manifest,
        "current_week_source_manifest": row.current_week_source_manifest,
        "last_trigger_daily_plan_id": row.last_trigger_daily_plan_id,
        "last_trigger_content_version": row.last_trigger_content_version,
        "last_trigger_event": row.last_trigger_event,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
