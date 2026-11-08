"""Class game-configuration AI extraction contract.

This is a purpose-built task type: it is not one of the three daily-plan tasks
and it is deliberately not exposed in the daily AI task panel or the daily
prompt editor.  The model receives only the teacher's pasted configuration
text and returns the same structured ``class_games`` shape the manual editor
already uses.  The result is a candidate only; the existing configuration
preview/apply path remains the sole writer.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError, field_validator

TASK_TYPE = "class_game_config_extract"
SOURCE_KIND = "class_game_config"
TASK_TYPES: tuple[str, ...] = (TASK_TYPE,)
INPUT_SCHEMA_VERSION = 1

MAX_SOURCE_TEXT_CHARS = 20_000
MAX_LOCATIONS = 90
MAX_LOCATIONS_PER_KIND = 30
MAX_NAME_CHARS = 80
MAX_LOCATION_GUIDANCE_CHARS = 2_000
MAX_TEXT_CHARS = 8_000

_LOCATION_KINDS = ("area", "special_room", "outdoor")


class ConfigAIInputError(ValueError):
    """The pasted text or request shape is not admissible."""


class ConfigAICandidateError(ValueError):
    """The model output does not match the frozen candidate contract."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class InputModel(_StrictModel):
    source_text: StrictStr = Field(..., min_length=1, max_length=MAX_SOURCE_TEXT_CHARS)

    @field_validator("source_text")
    @classmethod
    def _source_text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source_text 不能只包含空白")
        return value


class LocationCandidate(_StrictModel):
    kind: Literal["area", "special_room", "outdoor"]
    name: StrictStr = Field(..., min_length=1, max_length=MAX_NAME_CHARS)
    guidance: StrictStr | None = Field(default=None, max_length=MAX_LOCATION_GUIDANCE_CHARS)


class CandidateModel(_StrictModel):
    locations: list[LocationCandidate] = Field(default_factory=list, max_length=MAX_LOCATIONS)
    game_scope: StrictStr | None = Field(default=None, max_length=MAX_TEXT_CHARS)
    guidance: StrictStr | None = Field(default=None, max_length=MAX_TEXT_CHARS)

    def per_kind_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.locations:
            counts[item.kind] = counts.get(item.kind, 0) + 1
        return counts

    def validate_limits(self) -> "CandidateModel":
        for kind, count in self.per_kind_counts().items():
            if count > MAX_LOCATIONS_PER_KIND:
                raise ValueError(f"每类地点最多 {MAX_LOCATIONS_PER_KIND} 个（{kind}）")
        return self


INPUT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "source_text": {"type": "string", "minLength": 1, "maxLength": MAX_SOURCE_TEXT_CHARS},
    },
    "required": ["source_text"],
    "additionalProperties": False,
}

OUTPUT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "locations": {
            "type": "array",
            "maxItems": MAX_LOCATIONS,
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": list(_LOCATION_KINDS)},
                    "name": {"type": "string", "minLength": 1, "maxLength": MAX_NAME_CHARS},
                    "guidance": {"type": ["string", "null"], "maxLength": MAX_LOCATION_GUIDANCE_CHARS},
                },
                "required": ["kind", "name"],
                "additionalProperties": False,
            },
        },
        "game_scope": {"type": ["string", "null"], "maxLength": MAX_TEXT_CHARS},
        "guidance": {"type": ["string", "null"], "maxLength": MAX_TEXT_CHARS},
    },
    "required": ["locations", "game_scope", "guidance"],
    "additionalProperties": False,
}

GUIDANCE = {
    "extract": (
        "只从教师粘贴的班级游戏配置文字中提取区域、专用室、户外场地及其限制/指导。"
        "不得补写、猜测或把未出现的星期排班、材料库存当成配置。"
        "返回一个 JSON 对象；locations 只列出原文中有名称的地点，kind 只能是 "
        "area/special_room/outdoor，name 保留原文，guidance 可空；"
        "game_scope 与 guidance 分别对应游戏范围和通用限制/指导，未提到的返回 null。"
        "无法判断地点类型或名称时不要输出该地点，交给教师手工补充。"
    )
}


def validate_input(value: Any) -> dict[str, Any]:
    try:
        parsed = InputModel.model_validate(value)
    except ValidationError as exc:
        raise ConfigAIInputError(str(exc)) from None
    return {"source_text": parsed.source_text}


def validate_candidate(value: Any) -> dict[str, Any]:
    try:
        parsed = CandidateModel.model_validate(value).validate_limits()
    except (ValidationError, ValueError) as exc:
        raise ConfigAICandidateError(str(exc)) from None
    return {
        "locations": [item.model_dump() for item in parsed.locations],
        "game_scope": parsed.game_scope,
        "guidance": parsed.guidance,
    }


__all__ = [
    "TASK_TYPE",
    "SOURCE_KIND",
    "TASK_TYPES",
    "INPUT_SCHEMA_VERSION",
    "INPUT_SCHEMA",
    "OUTPUT_SCHEMA",
    "GUIDANCE",
    "MAX_SOURCE_TEXT_CHARS",
    "MAX_LOCATIONS",
    "MAX_LOCATIONS_PER_KIND",
    "MAX_NAME_CHARS",
    "MAX_LOCATION_GUIDANCE_CHARS",
    "MAX_TEXT_CHARS",
    "ConfigAIInputError",
    "ConfigAICandidateError",
    "validate_input",
    "validate_candidate",
]
