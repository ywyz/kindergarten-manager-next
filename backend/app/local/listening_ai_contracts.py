"""Pure one-to-one listening AI contracts and candidate validation.

The model only sees de-identified, server-projected listening material.  The
stable evaluation item ids and bound template standards are the sole id-like
values allowed in output.  This module has no DB, runtime, network or vendor
dependency.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, ValidationError

CONTRACT_VERSION = 1
INPUT_SCHEMA_VERSION = 1
TASK_NOTE = "listening_note_draft"
TASK_DOMAIN = "listening_domain_evaluate"
TASK_GROUP = "listening_group_notes"
TASK_GOAL = "listening_goal_suggest"
TASK_TYPES = (TASK_NOTE, TASK_DOMAIN, TASK_GROUP, TASK_GOAL)
MAX_TEXT = 20_000
MAX_GOAL = 4_000
MAX_BASIS = 2_000
MAX_UNCERTAINTIES = 10
MAX_ITEM_COUNT = 100


class ListeningAIContractError(ValueError):
    code = "LISTENING_AI_CONTRACT_INVALID"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _NoteOut(_Strict):
    text: StrictStr = Field(..., max_length=MAX_TEXT)
    uncertainties: list[StrictStr] = Field(..., max_length=MAX_UNCERTAINTIES)


class _ItemOut(_Strict):
    item_id: StrictStr = Field(..., min_length=1, max_length=40)
    stars: StrictInt | None
    basis: StrictStr = Field(..., max_length=MAX_BASIS)


class _DomainOut(_Strict):
    overall_evaluation: StrictStr = Field(..., max_length=MAX_TEXT)
    support_strategy: StrictStr = Field(..., max_length=MAX_TEXT)
    items: list[_ItemOut] = Field(..., max_length=MAX_ITEM_COUNT)


class _PhotoIn(_Strict):
    work_hash: StrictStr = Field(..., min_length=64, max_length=64)
    format: StrictStr = Field(..., min_length=1, max_length=20)
    width: StrictInt = Field(..., ge=1)
    height: StrictInt = Field(..., ge=1)
    orientation: StrictInt | None


class _NoteInput(_Strict):
    schema_version: StrictInt
    mode: StrictStr
    domain: StrictStr
    domain_label: StrictStr
    grade: StrictStr
    grade_label: StrictStr
    template_version: StrictStr
    template_sha256: StrictStr
    group_position: StrictInt
    work_date: StrictStr | None
    listening_text: StrictStr | None
    photo: _PhotoIn | None
    photo_only: StrictBool


class _DomainGroup(_Strict):
    position: StrictInt
    work_date: StrictStr | None
    listening_text: StrictStr | None
    photo: _PhotoIn | None


class _DomainItem(_Strict):
    item_id: StrictStr
    level1: StrictStr
    level2: StrictStr
    requirement: StrictStr
    standards: dict[StrictStr, StrictStr]


class _GroupNoteOut(_Strict):
    position: StrictInt = Field(..., ge=0, le=2)
    text: StrictStr = Field(..., max_length=MAX_TEXT)
    uncertainties: list[StrictStr] = Field(..., max_length=MAX_UNCERTAINTIES)


class _GroupNotesOut(_Strict):
    mode: StrictStr
    groups: list[_GroupNoteOut] = Field(..., min_length=1, max_length=3)


class _GroupNoteInputGroup(_Strict):
    position: StrictInt = Field(..., ge=0, le=2)
    work_date: StrictStr | None
    listening_text: StrictStr | None
    photo: _PhotoIn


class _GroupNotesInput(_Strict):
    schema_version: StrictInt
    mode: StrictStr
    domain: StrictStr
    domain_label: StrictStr
    grade: StrictStr
    grade_label: StrictStr
    template_version: StrictStr
    template_sha256: StrictStr
    groups: list[_GroupNoteInputGroup] = Field(..., min_length=1, max_length=3)


class _GoalInput(_Strict):
    schema_version: StrictInt
    mode: StrictStr
    domain: StrictStr
    domain_label: StrictStr
    grade: StrictStr
    grade_label: StrictStr
    template_version: StrictStr
    template_sha256: StrictStr
    goal: StrictStr | None = Field(None, max_length=MAX_GOAL)
    groups: list[_DomainGroup] = Field(..., max_length=3)
    items: list[_DomainItem] = Field(..., max_length=MAX_ITEM_COUNT)


class _GoalOut(_Strict):
    mode: StrictStr
    goal: StrictStr = Field(..., max_length=MAX_GOAL)
    uncertainties: list[StrictStr] = Field(..., max_length=MAX_UNCERTAINTIES)


class _DomainInput(_Strict):
    schema_version: StrictInt
    mode: StrictStr
    domain: StrictStr
    domain_label: StrictStr
    grade: StrictStr
    grade_label: StrictStr
    template_version: StrictStr
    template_sha256: StrictStr
    goal: StrictStr | None
    observation_date: StrictStr | None
    adult_count: StrictStr | None
    child_age: StrictStr | None
    observation_area: StrictStr | None
    groups: list[_DomainGroup] = Field(..., max_length=3)
    items: list[_DomainItem] = Field(..., max_length=MAX_ITEM_COUNT)


_NOTE_INPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "schema_version": {"type": "integer", "const": 1},
        "mode": {"type": "string", "const": "group_note"},
        "domain": {"type": "string"},
        "domain_label": {"type": "string"},
        "grade": {"type": "string", "enum": ["small", "middle", "large"]},
        "grade_label": {"type": "string"},
        "template_version": {"type": "string"},
        "template_sha256": {"type": "string"},
        "group_position": {"type": "integer", "minimum": 0, "maximum": 2},
        "work_date": {"type": ["string", "null"]},
        "listening_text": {"type": ["string", "null"]},
        "photo": {"type": ["object", "null"]},
        "photo_only": {"type": "boolean"},
    },
    "required": [
        "schema_version",
        "mode",
        "domain",
        "domain_label",
        "grade",
        "grade_label",
        "template_version",
        "template_sha256",
        "group_position",
        "work_date",
        "listening_text",
        "photo",
        "photo_only",
    ],
    "additionalProperties": False,
}
_NOTE_OUTPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "uncertainties": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["text", "uncertainties"],
    "additionalProperties": False,
}
_DOMAIN_INPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "schema_version": {"type": "integer", "const": 1},
        "mode": {"type": "string", "const": "domain_evaluate"},
        "domain": {"type": "string"},
        "domain_label": {"type": "string"},
        "grade": {"type": "string", "enum": ["small", "middle", "large"]},
        "grade_label": {"type": "string"},
        "template_version": {"type": "string"},
        "template_sha256": {"type": "string"},
        "goal": {"type": ["string", "null"]},
        "observation_date": {"type": ["string", "null"]},
        "adult_count": {"type": ["string", "null"]},
        "child_age": {"type": ["string", "null"]},
        "observation_area": {"type": ["string", "null"]},
        "groups": {"type": "array"},
        "items": {"type": "array"},
    },
    "required": [
        "schema_version",
        "mode",
        "domain",
        "domain_label",
        "grade",
        "grade_label",
        "template_version",
        "template_sha256",
        "goal",
        "observation_date",
        "adult_count",
        "child_age",
        "observation_area",
        "groups",
        "items",
    ],
    "additionalProperties": False,
}
_DOMAIN_OUTPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "overall_evaluation": {"type": "string"},
        "support_strategy": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "string"},
                    "stars": {"type": ["integer", "null"], "enum": [1, 2, 3, None]},
                    "basis": {"type": "string"},
                },
                "required": ["item_id", "stars", "basis"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["overall_evaluation", "support_strategy", "items"],
    "additionalProperties": False,
}
_GROUP_NOTES_INPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "schema_version": {"type": "integer", "const": 1},
        "mode": {"type": "string", "const": "group_notes"},
        "domain": {"type": "string"},
        "domain_label": {"type": "string"},
        "grade": {"type": "string", "enum": ["small", "middle", "large"]},
        "grade_label": {"type": "string"},
        "template_version": {"type": "string"},
        "template_sha256": {"type": "string"},
        "groups": {"type": "array", "minItems": 1, "maxItems": 3},
    },
    "required": [
        "schema_version",
        "mode",
        "domain",
        "domain_label",
        "grade",
        "grade_label",
        "template_version",
        "template_sha256",
        "groups",
    ],
    "additionalProperties": False,
}
_GROUP_NOTES_OUTPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "mode": {"type": "string", "const": "group_notes"},
        "groups": {
            "type": "array",
            "minItems": 1,
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "position": {"type": "integer", "minimum": 0, "maximum": 2},
                    "text": {"type": "string"},
                    "uncertainties": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["position", "text", "uncertainties"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["mode", "groups"],
    "additionalProperties": False,
}
_GOAL_INPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "schema_version": {"type": "integer", "const": 1},
        "mode": {"type": "string", "const": "goal_suggest"},
        "domain": {"type": "string"},
        "domain_label": {"type": "string"},
        "grade": {"type": "string", "enum": ["small", "middle", "large"]},
        "grade_label": {"type": "string"},
        "template_version": {"type": "string"},
        "template_sha256": {"type": "string"},
        "goal": {"type": ["string", "null"]},
        "groups": {"type": "array", "minItems": 1, "maxItems": 3},
        "items": {"type": "array"},
    },
    "required": [
        "schema_version",
        "mode",
        "domain",
        "domain_label",
        "grade",
        "grade_label",
        "template_version",
        "template_sha256",
        "goal",
        "groups",
        "items",
    ],
    "additionalProperties": False,
}
_GOAL_OUTPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "mode": {"type": "string", "const": "goal_suggest"},
        "goal": {"type": "string"},
        "uncertainties": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["mode", "goal", "uncertainties"],
    "additionalProperties": False,
}
_GUIDANCE_NOTE = {
    "text": (
        "根据教师已保存的本组倾听记录和/或作品照片，起草可直接放回“一对一倾听记录”栏的正文。"
        "只写材料中可见的幼儿表达、动作、画面事实和教师可直接核实的观察；不得虚构幼儿引语、现场问答或未出现的经过。"
        "若只有照片，正文须明确以照片可见内容为限，并在 uncertainties 中用简短问题列出需要教师核实的线索；"
        "不得把不确定内容写成已发生事实。保留教师原文中已有的字词与语气，不扩写无关背景。"
    ),
    "uncertainties": "列出需要教师向幼儿或现场核实的简短问题；没有则返回空数组。不要输出材料中不存在的姓名、文件名、记录编号或图片编号。",
}
_GUIDANCE_DOMAIN = {
    "overall_evaluation": (
        "依据本领域已保存目标、实际图文与绑定模板标准，写一段供教师预览修改的综合评价。"
        "只引用材料中可见的表现，不补造未出现的幼儿行为、引语或家庭情况；材料不足时写空字符串。"
    ),
    "support_strategy": "写一段与当前表现直接对应的支持策略，供教师预览修改；不虚构已实施的活动或结果，材料不足时写空字符串。",
    "items": (
        "对每个 item_id 依据对应逐档标准给出 1、2、3 或 null 的建议星级，并在 basis 中简短说明可见依据。"
        "不得改动 item_id 集合，不得输出材料之外的编号；没有足够依据时 stars 返回 null，basis 说明缺什么。"
        "建议只是候选，教师会逐项确认或跳过。"
    ),
}


_GUIDANCE_GOAL = {
    "goal": (
        "依据当前领域已保存的教师文字、作品照片、已知年级和绑定模板要求，起草一条可直接放回“目标”栏的观察目标。"
        "只使用输入材料中可见或已保存的事实，不得推断幼儿原话、观察时长、现场问答、因果关系或未出现的经过。"
        "目标应具体、可观察、适合教师后续核实；材料不足时写空字符串并在 uncertainties 中提出简短核实问题。"
    ),
    "uncertainties": "列出需要教师核实的简短问题；没有则返回空数组。不要输出姓名、文件名、记录编号或图片编号。",
}


_GUIDANCE_GROUP = {
    "mode": "group_notes",
    "groups": (
        "按输入 groups 的实际 position 逐图位返回，不增加、遗漏、重复或重排图位。"
        "每组只写照片中可见的画面事实和教师已保存的日期/文字，不得推断幼儿原话、观察时长、"
        "现场问答、因果关系或未出现的经过；信息不足时写空字符串并在 uncertainties 中列出需要教师核实的简短问题。"
        "空槽不会出现在输入中，也不得为未发送图位返回内容。"
    ),
}


def bundle_definitions() -> list[dict[str, Any]]:
    return [
        {
            "task_type": TASK_NOTE,
            "input_schema_json": _NOTE_INPUT_SCHEMA,
            "output_schema_json": _NOTE_OUTPUT_SCHEMA,
            "guidance_defaults_json": _GUIDANCE_NOTE,
        },
        {
            "task_type": TASK_DOMAIN,
            "input_schema_json": _DOMAIN_INPUT_SCHEMA,
            "output_schema_json": _DOMAIN_OUTPUT_SCHEMA,
            "guidance_defaults_json": _GUIDANCE_DOMAIN,
        },
        {
            "task_type": TASK_GROUP,
            "input_schema_json": _GROUP_NOTES_INPUT_SCHEMA,
            "output_schema_json": _GROUP_NOTES_OUTPUT_SCHEMA,
            "guidance_defaults_json": _GUIDANCE_GROUP,
        },
        {
            "task_type": TASK_GOAL,
            "input_schema_json": _GOAL_INPUT_SCHEMA,
            "output_schema_json": _GOAL_OUTPUT_SCHEMA,
            "guidance_defaults_json": _GUIDANCE_GOAL,
        },
    ]


def group_notes_bundle_definition() -> dict[str, Any]:
    """Focused helper for the group-note bundle (also in bundle_definitions)."""
    return {
        "task_type": TASK_GROUP,
        "input_schema_json": _GROUP_NOTES_INPUT_SCHEMA,
        "output_schema_json": _GROUP_NOTES_OUTPUT_SCHEMA,
        "guidance_defaults_json": _GUIDANCE_GROUP,
    }


def _safe_summary(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors(include_url=False, include_input=False):
        parts.append(
            f"{'.'.join(str(x) for x in error.get('loc', ()))}:{error.get('type', 'invalid')}"
        )
    return "; ".join(parts[:24]) or "invalid"


def validate_candidate(
    task_type: str,
    candidate: dict[str, Any],
    *,
    expected_positions: tuple[int, ...] | None = None,
) -> dict[str, Any]:
    if task_type not in TASK_TYPES:
        raise ListeningAIContractError("未知倾听 AI 任务类型")
    if not isinstance(candidate, dict):
        raise ListeningAIContractError("候选必须是 JSON 对象")
    model = {
        TASK_NOTE: _NoteOut,
        TASK_DOMAIN: _DomainOut,
        TASK_GROUP: _GroupNotesOut,
        TASK_GOAL: _GoalOut,
    }[task_type]
    try:
        parsed = model.model_validate(candidate)
    except ValidationError as exc:
        raise ListeningAIContractError("候选结构无效：" + _safe_summary(exc)) from None
    value = parsed.model_dump(mode="json")
    if task_type == TASK_DOMAIN:
        ids = []
        for item in value["items"]:
            if isinstance(item["stars"], bool) or (
                item["stars"] is not None and item["stars"] not in (1, 2, 3)
            ):
                raise ListeningAIContractError("候选星级不合法")
            ids.append(item["item_id"])
        if len(ids) != len(set(ids)):
            raise ListeningAIContractError("候选评价项重复")
    if task_type == TASK_GROUP:
        if value.get("mode") != "group_notes":
            raise ListeningAIContractError("多图位候选模式不合法")
        positions = [item["position"] for item in value["groups"]]
        if not positions or len(positions) != len(set(positions)):
            raise ListeningAIContractError("多图位候选图位重复或为空")
        if any(position < 0 or position > 2 for position in positions):
            raise ListeningAIContractError("多图位候选图位不合法")
        if expected_positions is not None and tuple(positions) != tuple(
            expected_positions
        ):
            raise ListeningAIContractError("多图位候选图位与发送图位不一致")
    if task_type == TASK_GOAL and value.get("mode") != "goal_suggest":
        raise ListeningAIContractError("观察目标候选模式不合法")
    return value


def validate_input(task_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if task_type not in TASK_TYPES or not isinstance(payload, dict):
        raise ListeningAIContractError("倾听 AI 输入不合法")
    model = {
        TASK_NOTE: _NoteInput,
        TASK_DOMAIN: _DomainInput,
        TASK_GROUP: _GroupNotesInput,
        TASK_GOAL: _GoalInput,
    }[task_type]
    try:
        parsed = model.model_validate(payload)
    except ValidationError as exc:
        raise ListeningAIContractError("倾听 AI 输入结构无效：" + _safe_summary(exc)) from None
    payload = parsed.model_dump(mode="json")
    if payload.get("schema_version") != INPUT_SCHEMA_VERSION:
        raise ListeningAIContractError("倾听 AI 输入版本不合法")
    expected_mode = {
        TASK_NOTE: "group_note",
        TASK_DOMAIN: "domain_evaluate",
        TASK_GROUP: "group_notes",
        TASK_GOAL: "goal_suggest",
    }[task_type]
    if payload.get("mode") != expected_mode:
        raise ListeningAIContractError("倾听 AI 输入模式不合法")
    for key in ("domain", "domain_label", "grade", "grade_label", "template_version", "template_sha256"):
        if not isinstance(payload.get(key), str) or not payload[key]:
            raise ListeningAIContractError(f"倾听 AI 输入缺少 {key}")
    if task_type == TASK_NOTE:
        if payload.get("group_position") not in (0, 1, 2):
            raise ListeningAIContractError("倾听组位置不合法")
        photo = payload.get("photo")
        if not payload.get("listening_text") and photo is None:
            raise ListeningAIContractError("本组没有可发送的材料")
        if bool(payload.get("photo_only")) != bool(photo is not None and not payload.get("listening_text")):
            raise ListeningAIContractError("仅图草案标记不一致")
    elif task_type == TASK_GROUP:
        groups = payload.get("groups") or []
        if not 1 <= len(groups) <= 3:
            raise ListeningAIContractError("多图位输入必须包含 1～3 个图位")
        positions = [group["position"] for group in groups]
        if positions != sorted(set(positions)):
            raise ListeningAIContractError("多图位输入图位必须唯一并保持顺序")
        for group in groups:
            if group.get("photo") is None:
                raise ListeningAIContractError("空图位不得发送")
    elif task_type == TASK_GOAL:
        groups = payload.get("groups") or []
        if not 1 <= len(groups) <= 3:
            raise ListeningAIContractError("观察目标输入必须包含 1～3 个有效材料图位")
        positions = [group["position"] for group in groups]
        if positions != sorted(set(positions)):
            raise ListeningAIContractError("观察目标输入图位必须唯一并保持顺序")
        if any(
            not (group.get("listening_text") or group.get("photo"))
            for group in groups
        ):
            raise ListeningAIContractError("观察目标输入包含空材料图位")
        photos = sum(1 for group in groups if group.get("photo") is not None)
        if photos > 3:
            raise ListeningAIContractError("观察目标图片超过三张")
        item_ids = []
        for item in payload.get("items") or []:
            item_id = item["item_id"]
            if not item_id or item_id in item_ids:
                raise ListeningAIContractError("观察目标模板项不合法")
            item_ids.append(item_id)
            if set(item["standards"]) != {"1", "2", "3"}:
                raise ListeningAIContractError("观察目标标准不合法")
    else:
        groups = payload["groups"]
        items = payload["items"]
        for index, group in enumerate(groups):
            if group["position"] != index:
                raise ListeningAIContractError("领域图文顺序不合法")
        item_ids = []
        for item in items:
            item_id = item["item_id"]
            if not item_id or item_id in item_ids:
                raise ListeningAIContractError("领域评价项不合法")
            item_ids.append(item_id)
            if set(item["standards"]) != {"1", "2", "3"}:
                raise ListeningAIContractError("领域标准不合法")
        photos = sum(1 for group in groups if group.get("photo") is not None)
        if photos > 3:
            raise ListeningAIContractError("领域图片超过三张")
        if not any(
            (group.get("listening_text") or group.get("work_date") or group.get("photo"))
            for group in groups
            if isinstance(group, dict)
        ) and not payload.get("goal"):
            raise ListeningAIContractError("领域没有可发送的材料")
    return payload


def group_note_target_key(domain: str, position: int) -> str:
    return f"{domain}_{position}"


def target_keys(task_type: str, item_ids: list[str]) -> tuple[str, ...]:
    if task_type == TASK_NOTE:
        return ("listening_text",)
    if task_type == TASK_GROUP:
        return ()
    if task_type == TASK_GOAL:
        return ("goal",)
    return ("overall_evaluation", "support_strategy", *item_ids)


def target_projection(
    task_type: str,
    *,
    group_text: str | None,
    overall: str | None,
    support: str | None,
    stars: dict[str, int | None],
    target: str,
) -> Any:
    if task_type == TASK_NOTE:
        return (group_text or "").strip()
    if target == "overall_evaluation":
        return (overall or "").strip()
    if target == "support_strategy":
        return (support or "").strip()
    return stars.get(target)


def value_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
