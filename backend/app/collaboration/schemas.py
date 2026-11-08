"""Strict request/response models for the collaboration HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.local.schemas import ConfigClassGamesChangeIn


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TeacherOut(_StrictModel):
    teacher_id: UUID
    display_name: str
    school_id: UUID
    school_name: str


class ClassOut(_StrictModel):
    class_id: UUID
    display_name: str


class MembershipOut(_StrictModel):
    teacher_id: UUID
    school_id: UUID
    class_id: UUID
    class_name: str
    selected_at: datetime


class ClassmateOut(_StrictModel):
    teacher_id: UUID
    display_name: str
    config_version: int
    config_updated_at: datetime | None


class GameLocationOut(_StrictModel):
    kind: Literal["area", "special_room", "outdoor"]
    name: str
    guidance: str | None


class GameConfigPayload(_StrictModel):
    locations: list[GameLocationOut]
    game_scope: str | None
    guidance: str | None


class TextFieldDiff(_StrictModel):
    source: str | None
    target: str | None
    changed: bool


class LocationsDiff(_StrictModel):
    source: list[GameLocationOut]
    target: list[GameLocationOut]
    changed: bool


class GameConfigDiff(_StrictModel):
    locations: LocationsDiff
    game_scope: TextFieldDiff
    guidance: TextFieldDiff
    changed: bool


class ConfigSaveIn(_StrictModel):
    request_id: UUID
    # The class the UI read before editing.  It is a binding condition, not
    # an authority: the server still derives the teacher/school from the
    # bearer and rechecks this class against the current membership.
    class_id: UUID
    expected_version: int = Field(..., ge=0, strict=True)
    change: ConfigClassGamesChangeIn


class ConfigCurrentOut(_StrictModel):
    class_id: UUID
    config_version: int
    payload: GameConfigPayload


class ConfigSaveOut(_StrictModel):
    request_id: UUID
    class_id: UUID
    config_version: int
    changed: bool
    payload: GameConfigPayload
    replayed: bool = False


class ClassSelectIn(_StrictModel):
    class_id: UUID


class ConfigPreviewIn(_StrictModel):
    request_id: UUID
    class_id: UUID
    source_teacher_id: UUID


class ConfigPreviewOut(_StrictModel):
    request_id: UUID
    preview_token: str
    expires_at: datetime
    class_id: UUID
    source_teacher_id: UUID
    source_teacher_name: str
    source_version: int
    target_version: int
    source_payload: GameConfigPayload
    target_payload: GameConfigPayload
    diff: GameConfigDiff


class ConfigConfirmIn(_StrictModel):
    request_id: UUID
    preview_token: str
    source_teacher_id: UUID
    source_version: int = Field(..., ge=1, strict=True)
    target_version: int = Field(..., ge=0, strict=True)


class ConfigConfirmOut(_StrictModel):
    request_id: UUID
    class_id: UUID
    source_teacher_id: UUID
    source_version: int
    target_version: int
    config_version: int
    changed: bool
    payload: GameConfigPayload
    replayed: bool = False


class OperationOut(_StrictModel):
    request_id: UUID
    kind: Literal["save", "import"]
    result: ConfigSaveOut | ConfigConfirmOut


class HealthOut(_StrictModel):
    status: Literal["ok"]
    service: Literal["collaboration"]
