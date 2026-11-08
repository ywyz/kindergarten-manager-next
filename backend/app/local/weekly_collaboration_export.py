"""Local Word export for a frozen online weekly-plan confirmation.

The online confirmation is the sole authority for shared days, game slots,
class name, grade and confirmation identity.  This module never accepts shared
content from the browser and never sends local weekly-plan content to the
collaboration service.  A local saved draft may only supplement theme, the four
local weekly columns and materials, and only when both query parameters are
present and the local plan belongs to the current profile on the same Monday.
"""

from __future__ import annotations

import datetime as dt
import re
from datetime import date, timedelta
from typing import Any, Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.local.api import get_session
from app.local.errors import (
    LocalError,
    LocalValidationError,
    LocalWeeklyExportNotFound,
    LocalWeeklyExportUnavailable,
)
from app.local.models import LocalWeeklyPlan, LocalWeeklyPlanContent
from app.local.profile_service import require_context
from app.local.tx import storage_errors
from app.services import word_export_mapping as mapping
from app.services.word_export_docx import (
    WordExportError,
    generate_weekly_export_docx,
)

DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
MAX_DOCX_BYTES = 128 * 1024 * 1024
_ASCII_SAFE = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
_UNSAFE_FILENAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


class WeeklyCollaborationExportInvalid(LocalError):
    code = "WEEKLY_COLLABORATION_EXPORT_INVALID"
    status_code = 422
    message = "在线确认版周计划数据无效，不能生成 Word"


class WeeklyCollaborationExportUnavailable(LocalError):
    code = "WEEKLY_COLLABORATION_EXPORT_UNAVAILABLE"
    status_code = 503
    message = "在线确认版周计划暂时无法导出"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _SharedGameItem(_StrictModel):
    name: str = Field(..., min_length=1, max_length=200)
    date: dt.date | None = None


class _SharedGames(_StrictModel):
    collective_1: _SharedGameItem | None = None
    collective_2: _SharedGameItem | None = None
    free_choice_1: _SharedGameItem | None = None
    focus_area: _SharedGameItem | None = None


class _SharedDay(_StrictModel):
    date: dt.date
    morning_talk_topic: str | None = Field(default=None, max_length=2000)
    group_activity_theme: str | None = Field(default=None, max_length=2000)


class _SharedContent(_StrictModel):
    days: list[_SharedDay] = Field(..., max_length=7)
    games: _SharedGames


class _WeeklyConfirmation(_StrictModel):
    confirmation_id: UUID
    confirmation_version: int = Field(..., ge=1)
    version: int = Field(..., ge=1)
    class_id: UUID
    term_id: UUID
    week_start: dt.date
    class_name: str
    grade: Literal["small", "middle", "large"]
    term_name: str
    content: _SharedContent
    confirmed_by: str
    confirmed_at: dt.datetime


router = APIRouter(prefix="/api/local/collaboration", tags=["weekly-export"])


def _safe_text(value: Any, *, maximum: int) -> str:
    if not isinstance(value, str):
        return ""
    value = _UNSAFE_FILENAME.sub("_", value).strip().strip(".")
    return value[:maximum]


def _content_disposition(filename: str) -> str:
    ascii_fallback = "".join(
        char if char in _ASCII_SAFE else "_" for char in filename
    )
    return (
        f'attachment; filename="{ascii_fallback}"; '
        f"filename*=UTF-8''{quote(filename, safe='')}"
    )


def _local_supplement(
    session: Session,
    *,
    profile_id: str,
    week_start: date,
    weekly_plan_id: str,
    local_draft_version: int,
) -> tuple[str, dict[str, str], str | None]:
    plan = session.get(LocalWeeklyPlan, weekly_plan_id)
    if plan is None or plan.profile_id != profile_id:
        raise LocalWeeklyExportNotFound(
            details={"weekly_plan_id": "not_found"}
        )
    if plan.week_anchor_date != week_start:
        raise WeeklyCollaborationExportInvalid(
            "本地周计划与在线确认版不是同一周一"
        )
    content = session.scalars(
        select(LocalWeeklyPlanContent).where(
            LocalWeeklyPlanContent.weekly_plan_id == weekly_plan_id,
            LocalWeeklyPlanContent.version == local_draft_version,
        )
    ).first()
    if content is None:
        raise LocalWeeklyExportNotFound(
            details={
                "weekly_plan_id": weekly_plan_id,
                "local_draft_version": local_draft_version,
            }
        )
    body = content.content_json if isinstance(content.content_json, dict) else {}
    theme = body.get("theme") if isinstance(body.get("theme"), str) else ""
    raw_columns = body.get("weekly_columns")
    raw_columns = raw_columns if isinstance(raw_columns, dict) else {}
    columns = {
        key: (
            raw_columns.get(key)
            if isinstance(raw_columns.get(key), str)
            else ""
        )
        for key in mapping.WEEKLY_COLUMN_KEYS
    }
    materials = body.get("materials")
    if not isinstance(materials, str):
        materials = None
    return theme, columns, materials


def _game_slot(slot: Any) -> dict[str, Any] | None:
    if slot is None:
        return None
    name = slot.name
    if slot.date is not None:
        name = f"{name}（{slot.date.isoformat()}）"
    return {
        "source_kind": "collaboration_confirmation",
        "name": name,
        "shared_objectives": "",
        "guidance_points": "",
        "focus_guidance": "",
    }


def _focus_slot(slot: Any) -> dict[str, Any] | None:
    if slot is None:
        return None
    name = slot.name
    if slot.date is not None:
        name = f"{name}（{slot.date.isoformat()}）"
    return {
        "source_kind": "collaboration_confirmation",
        "context_kind": "outdoor",
        "area": name,
        "name": name,
        "objectives": "",
        "guidance": "",
        "support_strategy": "",
    }


def _build_view(
    confirmation: _WeeklyConfirmation,
    *,
    week_start: date,
    local: tuple[str, dict[str, str], str | None] | None,
) -> dict[str, Any]:
    week_end = week_start + timedelta(days=6)
    by_date: dict[date, Any] = {}
    for item in confirmation.content.days:
        if item.date < week_start or item.date > week_end:
            raise WeeklyCollaborationExportInvalid("确认版共享日期不在该周")
        if item.date in by_date:
            raise WeeklyCollaborationExportInvalid("确认版共享日期重复")
        by_date[item.date] = item
    for key in mapping.OUTDOOR_SLOT_KEYS:
        slot = getattr(confirmation.content.games, key, None)
        if (
            slot is not None
            and slot.date is not None
            and (slot.date < week_start or slot.date > week_end)
        ):
            raise WeeklyCollaborationExportInvalid("确认版游戏日期不在该周")
    focus = confirmation.content.games.focus_area
    if (
        focus is not None
        and focus.date is not None
        and (focus.date < week_start or focus.date > week_end)
    ):
        raise WeeklyCollaborationExportInvalid("确认版重点区域日期不在该周")
    if not confirmation.class_name.strip():
        raise WeeklyCollaborationExportInvalid("确认版缺少班名")

    # The Word template has fixed Monday-Friday columns.  A missing weekday is
    # a blank placeholder, never a fabricated activity or day state.  Weekend
    # columns appear only when the frozen snapshot explicitly contains them.
    column_dates = [week_start + timedelta(days=offset) for offset in range(5)]
    if week_start + timedelta(days=5) in by_date:
        column_dates.append(week_start + timedelta(days=5))
    if week_start + timedelta(days=6) in by_date:
        column_dates.append(week_start + timedelta(days=6))

    def column(item_date: date) -> dict[str, Any]:
        item = by_date.get(item_date)
        return {
            "date": item_date.isoformat(),
            "weekday": item_date.isoweekday(),
            "day_state": "teaching",
            "holiday": False,
            "outside_term": False,
            "morning_talk_topic": (
                (item.morning_talk_topic or "") if item is not None else ""
            ),
            "group_activity_theme": (
                (item.group_activity_theme or "") if item is not None else ""
            ),
            "plan_state": None,
            "source_missing": False,
        }

    theme, weekly_columns, materials = local or ("", {}, None)
    games = confirmation.content.games
    view = {
        "kind": mapping.KIND_WEEKLY,
        "plan_id": None,
        "term_id": str(confirmation.term_id),
        "week_number": week_start.isocalendar().week,
        "confirmed_version": confirmation.confirmation_version,
        "header": {
            # Shared authority only for class/grade.  The local plan does not
            # supplement school/teacher identity in this slice.
            "school_name": None,
            "class_name": confirmation.class_name,
            "grade": mapping.grade_display(confirmation.grade),
            "header_teacher_names": [],
            "caregiver_name": None,
            "theme": theme,
        },
        "date_range": {"start": week_start, "end": week_end},
        "columns": [column(item_date) for item_date in column_dates],
        "outdoor_game_slots": {
            key: _game_slot(getattr(games, key, None))
            for key in mapping.OUTDOOR_SLOT_KEYS
        },
        "focus_area": _focus_slot(games.focus_area),
        "weekly_columns": weekly_columns,
        "materials": materials,
        "warnings": [],
    }
    return view

@router.get(
    "/classes/{class_id}/weekly/{term_id}/{week_start}/"
    "confirmations/{confirmation_id}/word"
)
def weekly_collaboration_word(
    class_id: str,
    term_id: str,
    week_start: date,
    confirmation_id: str,
    request: Request,
    weekly_plan_id: str | None = Query(
        default=None, min_length=1, max_length=64
    ),
    local_draft_version: int | None = Query(default=None, ge=1),
    session: Session = Depends(get_session),
):
    """Generate a local DOCX from a frozen online confirmation."""
    try:
        class_uuid = UUID(class_id)
        term_uuid = UUID(term_id)
        confirmation_uuid = UUID(confirmation_id)
    except (ValueError, TypeError):
        raise LocalValidationError("班级、学期或确认标识不合法") from None
    if week_start.isoweekday() != 1:
        raise WeeklyCollaborationExportInvalid("周起始日期必须是周一")
    if (weekly_plan_id is None) != (local_draft_version is None):
        raise LocalValidationError(
            "weekly_plan_id 与 local_draft_version 必须同时提供"
        )

    proxy = getattr(request.app.state, "collaboration_proxy", None)
    reader = getattr(proxy, "weekly_confirmation", None)
    if not callable(reader):
        raise WeeklyCollaborationExportUnavailable()

    try:
        raw = reader(class_uuid, term_uuid, week_start, confirmation_uuid)
    except LocalError:
        raise
    except Exception:  # noqa: BLE001 - never expose proxy internals
        raise WeeklyCollaborationExportUnavailable() from None

    try:
        confirmation = _WeeklyConfirmation.model_validate(raw)
    except ValidationError:
        raise WeeklyCollaborationExportInvalid(
            "在线确认版返回结构无效"
        ) from None
    if (
        confirmation.class_id != class_uuid
        or confirmation.term_id != term_uuid
        or confirmation.week_start != week_start
        or confirmation.confirmation_id != confirmation_uuid
    ):
        raise WeeklyCollaborationExportInvalid(
            "在线确认版与请求的班级、学期、周或确认标识不一致"
        )

    local = None
    if weekly_plan_id is not None:
        with storage_errors():
            context = require_context(session, date.today())
            profile = context.profile
            if profile is None:
                raise LocalWeeklyExportNotFound()
            local = _local_supplement(
                session,
                profile_id=profile.id,
                week_start=week_start,
                weekly_plan_id=weekly_plan_id,
                local_draft_version=local_draft_version,
            )

    view = _build_view(confirmation, week_start=week_start, local=local)
    try:
        docx = generate_weekly_export_docx([view])
    except WordExportError:
        raise LocalWeeklyExportUnavailable() from None
    if not docx or len(docx) > MAX_DOCX_BYTES:
        raise LocalWeeklyExportUnavailable()

    filename = _safe_text(
        f"周计划_{confirmation.class_name}_{week_start.isoformat()}_"
        f"确认版v{confirmation.confirmation_version}.docx",
        maximum=180,
    )
    if not filename.lower().endswith(".docx"):
        filename = "周工作计划.docx"
    return Response(
        content=docx,
        media_type=DOCX_MEDIA_TYPE,
        headers={
            "Content-Disposition": _content_disposition(filename),
            "Cache-Control": "no-store",
            "X-Weekly-Confirmation-Id": str(confirmation.confirmation_id),
            "X-Weekly-Confirmation-Version": str(
                confirmation.confirmation_version
            ),
        },
    )
