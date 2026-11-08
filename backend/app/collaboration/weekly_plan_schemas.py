"""Strict wire schemas for the first shared weekly-plan slice.

Only the shared morning-talk, group-activity and game-slot fields cross this
boundary.  Local lesson bodies, source IDs, objectives, materials, photos and
other local weekly fields are deliberately absent.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Grade = Literal["small", "middle", "large"]
OperationKind = Literal["save", "confirm"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WeeklyDayIn(_StrictModel):
    date: date_type
    morning_talk_topic: str | None = Field(default=None, max_length=2000)
    group_activity_theme: str | None = Field(default=None, max_length=2000)


class WeeklyGameSlot(_StrictModel):
    name: str = Field(..., min_length=1, max_length=200)
    date: date_type | None = None


class WeeklyGames(_StrictModel):
    collective_1: WeeklyGameSlot | None = None
    collective_2: WeeklyGameSlot | None = None
    free_choice_1: WeeklyGameSlot | None = None
    focus_area: WeeklyGameSlot | None = None


class WeeklyContent(_StrictModel):
    days: list[WeeklyDayIn] = Field(default_factory=list, max_length=7)
    games: WeeklyGames


class WeeklyReadOut(_StrictModel):
    class_id: UUID
    term_id: UUID
    week_start: date_type
    class_name: str
    term_name: str
    version: int
    content: WeeklyContent
    confirmation: "WeeklyConfirmationOut | None" = None


class WeeklySaveIn(_StrictModel):
    request_id: UUID
    expected_version: int = Field(..., ge=0, strict=True)
    content: WeeklyContent


class WeeklySaveOut(WeeklyReadOut):
    request_id: UUID
    replayed: bool


class WeeklyConfirmIn(_StrictModel):
    request_id: UUID
    expected_version: int = Field(..., ge=0, strict=True)


class WeeklyConfirmationOut(_StrictModel):
    confirmation_id: UUID
    confirmation_version: int
    version: int
    class_id: UUID
    term_id: UUID
    week_start: date_type
    class_name: str
    grade: Grade
    term_name: str
    content: WeeklyContent
    confirmed_by: UUID
    confirmed_at: datetime


class WeeklyConfirmOut(WeeklyConfirmationOut):
    request_id: UUID
    replayed: bool


class WeeklyOperationOut(_StrictModel):
    request_id: UUID
    kind: OperationKind
    result: dict[str, Any]


WeeklyReadOut.model_rebuild()
WeeklyConfirmationOut.model_rebuild()
