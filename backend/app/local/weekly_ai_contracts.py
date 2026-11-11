"""Pure weekly AI contract, JSON, handle and candidate-output rules.

No database, runtime, network, filesystem or vendor imports.  This module is the
single parser/validator for model output and the frozen six weekly task bundle
definitions.  A maps these errors to HTTP; B never reads a DB or a prompt table.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

CONTRACT_VERSION = 1
AI_INPUT_SCHEMA_VERSION = 1
MAX_AI_OUTPUT_BYTES = 1_048_576
MAX_MANIFEST_BYTES = 1_048_576
MAX_AI_TEXT_CHARS = 100_000
MAX_AI_ARRAY_ITEMS = 100
MAX_HANDLE_CHARS = 6
MAX_BASIS_HANDLES = 100
MAX_MATERIAL_ITEMS = 100
MAX_MATERIAL_ITEM_TEXT = 300
MAX_MATERIAL_QUOTE = 2_000
MAX_MATERIAL_SYNTHESIS = 20_000
MAX_ID_CHARS = 32
MAX_NAME_CHARS = 80
MAX_HASH_CHARS = 64

TASK_TARGETS = {
    "weekly_games_select": "games",
    "weekly_key_week_focus": "key_week_focus",
    "weekly_environment_setup": "environment_setup",
    "weekly_habit_culture": "habit_culture",
    "weekly_home_cooperation": "home_cooperation",
    "weekly_materials_generate": "materials",
}
TASK_ORDER = tuple(TASK_TARGETS)
COLUMN_FIELDS = (
    "key_week_focus",
    "environment_setup",
    "habit_culture",
    "home_cooperation",
)
COLUMN_TASK = {field: f"weekly_{field}" for field in COLUMN_FIELDS}
TARGETS = ("games", *COLUMN_FIELDS, "materials")

HANDLE_RE = re.compile(r"^[a-z][0-9]{1,5}$")
HANDLE_PREFIX = {
    "morning_game": "m",
    "post_group_game": "p",
    "config_location": "c",
    "manual_outdoor": "h",
    "ai_outdoor": "a",
    "ai_focus": "f",
}
HANDLE_KINDS = frozenset(HANDLE_PREFIX)
SERVER_MANIFEST_KEYS = frozenset(
    {"schema_version", "task_type", "plan", "source_context_hash", "handles"}
)
PLAN_KEYS = frozenset(
    {
        "weekly_plan_id",
        "draft_id",
        "draft_version",
        "content_hash",
        "profile_id",
        "class_id",
        "term_id",
        "week_anchor_date",
        "week_number",
    }
)
HANDLE_KEYS = {
    "morning_game": frozenset(
        {
            "kind",
            "date",
            "daily_plan_id",
            "content_id",
            "content_version",
            "content_hash",
            "group_id",
            "group_kind",
            "game_id",
            "name",
            "shared_objectives",
            "guidance_points",
            "focus_guidance",
        }
    ),
    "post_group_game": frozenset(
        {
            "kind",
            "date",
            "daily_plan_id",
            "content_id",
            "content_version",
            "content_hash",
            "group_id",
            "context_kind",
            "area",
            "game_id",
            "name",
            "objectives",
            "guidance",
            "support_strategy",
        }
    ),
    "config_location": frozenset(
        {
            "kind",
            "revision_id",
            "revision_no",
            "location_kind",
            "name",
            "occurrence",
            "guidance",
            "game_scope",
            "config_guidance",
        }
    ),
    "manual_outdoor": frozenset(
        {
            "kind",
            "manual_item_id",
            "slot_key",
            "name",
            "shared_objectives",
            "guidance_points",
            "focus_guidance",
        }
    ),
    "ai_outdoor": frozenset(
        {
            "kind",
            "ai_item_id",
            "candidate_id",
            "input_id",
            "slot_key",
            "name",
            "shared_objectives",
            "guidance_points",
            "focus_guidance",
        }
    ),
    "ai_focus": frozenset(
        {
            "kind",
            "ai_item_id",
            "candidate_id",
            "input_id",
            "context_kind",
            "area",
            "name",
            "objectives",
            "guidance",
            "support_strategy",
        }
    ),
}
OUTDOOR_KEYS = ("collective_1", "collective_2", "free_choice_1")
FOCUS_CONTEXT_KINDS = ("area", "outdoor", "special_room")
EVIDENCE_FIELD_PATHS = {
    "morning_game": frozenset(
        {"name", "shared_objectives", "guidance_points", "focus_guidance"}
    ),
    "post_group_game": frozenset(
        {"name", "objectives", "guidance", "support_strategy", "area"}
    ),
    "manual_outdoor": frozenset(
        {"name", "shared_objectives", "guidance_points", "focus_guidance"}
    ),
    "ai_outdoor": frozenset(
        {"name", "shared_objectives", "guidance_points", "focus_guidance"}
    ),
    "ai_focus": frozenset(
        {"name", "objectives", "guidance", "support_strategy", "area"}
    ),
    "config_location": frozenset(
        {"name", "guidance", "game_scope", "config_guidance"}
    ),
}


class WeeklyAIContractError(ValueError):
    """Safe pure-contract error for A to map; never contains raw text."""

    code = "WEEKLY_AI_INPUT_INVALID"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        field_path: str = "",
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.field_path = field_path
        self.details = dict(details or {})
        if code is not None:
            self.code = code


def _fail(
    message: str,
    field_path: str = "",
    *,
    code: str = "WEEKLY_AI_INPUT_INVALID",
    details: Mapping[str, Any] | None = None,
) -> None:
    raise WeeklyAIContractError(
        message, code=code, field_path=field_path, details=details
    )


def _map(value: Any, path: str) -> dict:
    if not isinstance(value, Mapping):
        _fail("必须是对象", path)
    return dict(value)


def _exact(value: Mapping[str, Any], keys: frozenset[str] | tuple[str, ...], path: str) -> None:
    expected = set(keys)
    actual = set(value)
    if expected != actual:
        # Never echo arbitrary model/manifest keys: only schema counts.
        _fail(
            "键不匹配",
            path,
            details={
                "missing_count": len(expected - actual),
                "extra_count": len(actual - expected),
            },
        )


def _text(
    value: Any,
    path: str,
    *,
    allow_none: bool = False,
    strip: bool = False,
    maximum: int = MAX_AI_TEXT_CHARS,
    nonempty: bool = False,
) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str):
        _fail("必须是字符串", path)
    if "\x00" in value:
        _fail("字符串不得包含 NUL", path)
    result = value.strip() if strip else value
    if len(result) > maximum:
        _fail("文本超限", path, details={"max": maximum})
    if nonempty and not result.strip():
        _fail("文本不能为空", path)
    return result


def _id(value: Any, path: str) -> str:
    if not isinstance(value, str) or not (1 <= len(value) <= MAX_ID_CHARS):
        _fail("ID 不合法", path)
    if "\x00" in value:
        _fail("ID 不得包含 NUL", path)
    return value


def _hash(value: Any, path: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != MAX_HASH_CHARS
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        _fail("必须是 64 位小写十六进制", path)
    return value


def _positive_int(value: Any, path: str, *, maximum: int | None = None) -> int:
    if type(value) is not int or value < 1:
        _fail("必须是正整数", path)
    if maximum is not None and value > maximum:
        _fail("整数超限", path, details={"max": maximum})
    return value


def _bool(value: Any, path: str) -> bool:
    if type(value) is not bool:
        _fail("必须是布尔值", path)
    return value


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        _fail("值不可 canonical 序列化", "value")


def value_hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def candidate_hash(value: Mapping[str, Any]) -> str:
    return value_hash(value)


def strict_json_object(
    raw: str | bytes, *, max_bytes: int = MAX_AI_OUTPUT_BYTES
) -> dict:
    if isinstance(raw, bytes):
        if len(raw) > max_bytes:
            _fail("输出超限", "output", code="WEEKLY_AI_OUTPUT_INVALID")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            _fail("输出不是 UTF-8", "output", code="WEEKLY_AI_OUTPUT_INVALID")
    elif isinstance(raw, str):
        text = raw
        if len(text.encode("utf-8")) > max_bytes:
            _fail("输出超限", "output", code="WEEKLY_AI_OUTPUT_INVALID")
    else:
        _fail("输出必须是字符串或字节", "output", code="WEEKLY_AI_OUTPUT_INVALID")
    if text.startswith("\ufeff") or not text.strip():
        _fail("输出不得含 BOM 或为空", "output", code="WEEKLY_AI_OUTPUT_INVALID")
    text = text.strip()
    if not text.startswith("{") or not text.endswith("}"):
        _fail("输出必须是单个 JSON 对象", "output", code="WEEKLY_AI_OUTPUT_INVALID")

    def _pairs(items: list[tuple[str, Any]]) -> dict:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                _fail(
                    "输出含重复键",
                    "output",
                    code="WEEKLY_AI_OUTPUT_INVALID",
                    details={"reason": "duplicate_key"},
                )
            result[key] = value
        return result

    def _constant(value: str) -> Any:
        _fail(
            "输出含非有限数",
            "output",
            code="WEEKLY_AI_OUTPUT_INVALID",
            details={"reason": "nonfinite_number"},
        )

    try:
        parsed = json.loads(
            text, object_pairs_hook=_pairs, parse_constant=_constant
        )
    except WeeklyAIContractError:
        raise
    except (ValueError, TypeError):
        _fail("输出不是严格 JSON", "output", code="WEEKLY_AI_OUTPUT_INVALID")
    if not isinstance(parsed, dict):
        _fail("输出顶层必须是对象", "output", code="WEEKLY_AI_OUTPUT_INVALID")
    return parsed


def normalize_selected_fields(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        _fail("selected_fields 必须是数组", "selected_fields")
    selected: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or item not in COLUMN_FIELDS:
            _fail("selected_fields 含未知字段", f"selected_fields[{index}]")
        if item in selected:
            _fail("selected_fields 不得重复", f"selected_fields[{index}]")
        selected.append(item)
    if not selected:
        _fail("selected_fields 不能为空", "selected_fields")
    return tuple(field for field in COLUMN_FIELDS if field in selected)


def task_types_for_columns(value: object) -> tuple[tuple[str, str], ...]:
    return tuple((field, COLUMN_TASK[field]) for field in normalize_selected_fields(value))


def target_for_task(task_type: object) -> str:
    if not isinstance(task_type, str) or task_type not in TASK_TARGETS:
        _fail("不支持的周任务类型", "task_type")
    return TASK_TARGETS[task_type]


PROMPT_CONTRACT_CURRENT = {
    "weekly_games_select": 2,
    "weekly_key_week_focus": 1,
    "weekly_environment_setup": 1,
    "weekly_habit_culture": 1,
    "weekly_home_cooperation": 1,
    "weekly_materials_generate": 2,
}
PROMPT_CONTRACT_SUPPORTED = {
    "weekly_games_select": frozenset({1, 2}),
    "weekly_key_week_focus": frozenset({1}),
    "weekly_environment_setup": frozenset({1}),
    "weekly_habit_culture": frozenset({1}),
    "weekly_home_cooperation": frozenset({1}),
    "weekly_materials_generate": frozenset({1, 2}),
}


def prompt_contract_version(task_type: str) -> int:
    """Current prompt contract version for one exact weekly task."""
    if not isinstance(task_type, str) or task_type not in TASK_TARGETS:
        _fail("不支持的周任务类型", "task_type")
    return PROMPT_CONTRACT_CURRENT[task_type]


def supports_prompt_contract(task_type: str, contract_version: object) -> bool:
    """True only for the supported prompt contract version of a known task."""
    if not isinstance(task_type, str) or task_type not in TASK_TARGETS:
        return False
    if type(contract_version) is not int or contract_version < 1:
        return False
    return contract_version in PROMPT_CONTRACT_SUPPORTED[task_type]


def _validate_typed_handle(handle: str, value: object) -> dict:
    data = _map(value, f"handles.{handle}")
    kind = data.get("kind")
    if kind not in HANDLE_KINDS:
        _fail("handle kind 非法", f"handles.{handle}.kind")
    if not handle.startswith(HANDLE_PREFIX[kind]):
        _fail("handle 前缀与 kind 不匹配", f"handles.{handle}")
    _exact(data, HANDLE_KEYS[kind], f"handles.{handle}")
    for key in ("daily_plan_id", "content_id", "group_id", "game_id", "manual_item_id",
                "ai_item_id", "candidate_id", "input_id", "revision_id"):
        if key in data and data[key] is not None:
            _id(data[key], f"handles.{handle}.{key}")
    for key in ("content_version", "revision_no", "occurrence"):
        if key in data and data[key] is not None:
            _positive_int(data[key], f"handles.{handle}.{key}")
    for key in ("content_hash",):
        if key in data:
            _hash(data[key], f"handles.{handle}.{key}")
    for key in ("date",):
        if key in data and data[key] is not None:
            _text(data[key], f"handles.{handle}.{key}", maximum=10, nonempty=True)
    for key in ("group_kind", "context_kind", "location_kind"):
        if key in data and data[key] is not None:
            _text(data[key], f"handles.{handle}.{key}", maximum=32, nonempty=True)
    for key in ("name", "area", "shared_objectives", "guidance_points",
                "focus_guidance", "objectives", "guidance", "support_strategy",
                "config_guidance", "game_scope"):
        if key in data:
            if key == "name":
                _text(data[key], f"handles.{handle}.{key}", maximum=MAX_NAME_CHARS,
                      nonempty=kind in ("morning_game", "post_group_game", "manual_outdoor",
                                        "ai_outdoor", "ai_focus", "config_location"))
            else:
                _text(data[key], f"handles.{handle}.{key}", allow_none=True)
    if kind == "morning_game" and data["group_kind"] not in ("collective", "free_choice"):
        _fail("group_kind 非法", f"handles.{handle}.group_kind")
    if kind == "post_group_game" and data["context_kind"] not in FOCUS_CONTEXT_KINDS:
        _fail("context_kind 非法", f"handles.{handle}.context_kind")
    if kind == "config_location" and data["location_kind"] not in FOCUS_CONTEXT_KINDS:
        _fail("location_kind 非法", f"handles.{handle}.location_kind")
    if kind in ("morning_game", "post_group_game") and data.get("date") is not None:
        try:
            from datetime import date as _date
            if _date.fromisoformat(data["date"]).isoformat() != data["date"]:
                raise ValueError
        except ValueError:
            _fail("date 必须是 ISO 日期", f"handles.{handle}.date")
    if kind in ("manual_outdoor", "ai_outdoor") and data.get("slot_key") not in OUTDOOR_KEYS:
        _fail("slot_key 非法", f"handles.{handle}.slot_key")
    if kind in ("ai_outdoor", "ai_focus"):
        for key in ("ai_item_id", "candidate_id", "input_id"):
            _id(data.get(key), f"handles.{handle}.{key}")
    return copy.deepcopy(data)


def validate_typed_handle(handle: object, value: object) -> dict:
    """Validate one typed server-manifest handle without a surrounding manifest."""
    if not isinstance(handle, str) or not HANDLE_RE.fullmatch(handle):
        _fail("handle 语法非法", "handle")
    return _validate_typed_handle(handle, value)


def validate_handle_manifest(value: object) -> dict:
    data = _map(value, "server_manifest")
    _exact(data, SERVER_MANIFEST_KEYS, "server_manifest")
    if data.get("schema_version") != 1 or type(data.get("schema_version")) is not int:
        _fail("server_manifest schema_version 必须为 1", "server_manifest.schema_version")
    task_type = data.get("task_type")
    if task_type not in TASK_TARGETS:
        _fail("server_manifest task_type 非法", "server_manifest.task_type")
    plan = _map(data.get("plan"), "server_manifest.plan")
    _exact(plan, PLAN_KEYS, "server_manifest.plan")
    for key in ("weekly_plan_id", "draft_id", "profile_id", "class_id", "term_id"):
        _id(plan.get(key), f"server_manifest.plan.{key}")
    _positive_int(plan.get("draft_version"), "server_manifest.plan.draft_version")
    _hash(plan.get("content_hash"), "server_manifest.plan.content_hash")
    _text(plan.get("week_anchor_date"), "server_manifest.plan.week_anchor_date", maximum=10, nonempty=True)
    _positive_int(plan.get("week_number"), "server_manifest.plan.week_number")
    _hash(data.get("source_context_hash"), "server_manifest.source_context_hash")
    handles = _map(data.get("handles"), "server_manifest.handles")
    if len(handles) > MAX_AI_ARRAY_ITEMS:
        _fail("handles 数量超限", "server_manifest.handles")
    normalized: dict[str, dict] = {}
    for handle, handle_value in handles.items():
        if not isinstance(handle, str) or not HANDLE_RE.fullmatch(handle):
            _fail("handle 语法非法", "server_manifest.handles")
        normalized[handle] = _validate_typed_handle(handle, handle_value)
    result = {
        "schema_version": 1,
        "task_type": task_type,
        "plan": {
            "weekly_plan_id": plan["weekly_plan_id"],
            "draft_id": plan["draft_id"],
            "draft_version": plan["draft_version"],
            "content_hash": plan["content_hash"],
            "profile_id": plan["profile_id"],
            "class_id": plan["class_id"],
            "term_id": plan["term_id"],
            "week_anchor_date": plan["week_anchor_date"],
            "week_number": plan["week_number"],
        },
        "source_context_hash": data["source_context_hash"],
        "handles": {key: normalized[key] for key in sorted(normalized)},
    }
    if len(_canonical(result).encode("utf-8")) > MAX_MANIFEST_BYTES:
        _fail("server manifest 超过 1MiB", "server_manifest", code="WEEKLY_CONTENT_TOO_LARGE")
    return result


def _resolve_handle(manifest: Mapping[str, Any], handle: object, *, allowed: set[str] | None = None) -> tuple[str, dict]:
    if not isinstance(handle, str) or not HANDLE_RE.fullmatch(handle):
        _fail("source_handle 语法非法", "source_handle", code="WEEKLY_AI_OUTPUT_INVALID")
    entry = manifest["handles"].get(handle)
    if entry is None:
        _fail("source_handle 不存在", "source_handle", code="WEEKLY_AI_OUTPUT_INVALID")
    if allowed is not None and entry["kind"] not in allowed:
        _fail(
            "source_handle 类型不允许",
            "source_handle",
            code="WEEKLY_AI_OUTPUT_INVALID",
            details={"kind": entry["kind"]},
        )
    return handle, copy.deepcopy(entry)


def _resolved_outdoor(handle: str, entry: dict, slot_key: str) -> dict:
    required = "collective" if slot_key in ("collective_1", "collective_2") else "free_choice"
    if entry["group_kind"] != required:
        _fail(
            "日来源 group_kind 与槽位类别不符",
            f"outdoor_game_slots.{slot_key}",
            code="WEEKLY_AI_OUTPUT_INVALID",
        )
    return {
        "source_kind": "daily_plan",
        "manual_item_id": None,
        "daily_plan_id": entry["daily_plan_id"],
        "content_id": entry["content_id"],
        "content_version": entry["content_version"],
        "content_hash": entry["content_hash"],
        "section": "morning_games",
        "group_id": entry["group_id"],
        "game_id": entry["game_id"],
        "name": entry["name"],
        "shared_objectives": entry["shared_objectives"],
        "guidance_points": entry["guidance_points"],
        "focus_guidance": entry["focus_guidance"],
    }


def _resolved_focus(handle: str, entry: dict) -> dict:
    return {
        "source_kind": "daily_plan",
        "manual_item_id": None,
        "daily_plan_id": entry["daily_plan_id"],
        "content_id": entry["content_id"],
        "content_version": entry["content_version"],
        "content_hash": entry["content_hash"],
        "section": "post_group_games",
        "group_id": entry["group_id"],
        "game_id": entry["game_id"],
        "context_kind": entry["context_kind"],
        "area": entry["area"],
        "name": entry["name"],
        "objectives": entry["objectives"],
        "guidance": entry["guidance"],
        "support_strategy": entry["support_strategy"],
    }


def _basis_handles(value: object, manifest: Mapping[str, Any], path: str) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_BASIS_HANDLES:
        _fail("basis_handles 必须是有限数组", path, code="WEEKLY_AI_OUTPUT_INVALID")
    result: list[str] = []
    for index, handle in enumerate(value):
        if handle in result:
            _fail("basis_handles 不得重复", f"{path}[{index}]", code="WEEKLY_AI_OUTPUT_INVALID")
        _resolve_handle(manifest, handle, allowed={"config_location"})
        result.append(handle)
    return sorted(result)


def _parse_ai_outdoor(raw: Mapping[str, Any], manifest: Mapping[str, Any], path: str) -> dict:
    _exact(
        raw,
        frozenset(
            {"kind", "name", "shared_objectives", "guidance_points",
             "focus_guidance", "basis_handles"}
        ),
        path,
    )
    if raw.get("kind") != "ai_supplement":
        _fail("kind 非法", f"{path}.kind", code="WEEKLY_AI_OUTPUT_INVALID")
    return {
        "source_kind": "ai_supplement",
        "manual_item_id": None,
        "daily_plan_id": None,
        "content_id": None,
        "content_version": None,
        "content_hash": None,
        "section": None,
        "group_id": None,
        "game_id": None,
        "name": _text(raw.get("name"), f"{path}.name", maximum=MAX_NAME_CHARS, nonempty=True),
        "shared_objectives": _text(raw.get("shared_objectives"), f"{path}.shared_objectives", allow_none=True),
        "guidance_points": _text(raw.get("guidance_points"), f"{path}.guidance_points", allow_none=True),
        "focus_guidance": _text(raw.get("focus_guidance"), f"{path}.focus_guidance", allow_none=True),
        "basis_keys": _basis_handles(raw.get("basis_handles"), manifest, f"{path}.basis_handles"),
    }


def _parse_ai_focus(raw: Mapping[str, Any], manifest: Mapping[str, Any], path: str) -> dict:
    _exact(
        raw,
        frozenset(
            {"kind", "context_kind", "area", "name", "objectives", "guidance",
             "support_strategy", "basis_handles"}
        ),
        path,
    )
    context = _text(raw.get("context_kind"), f"{path}.context_kind", maximum=32, nonempty=True)
    if context not in FOCUS_CONTEXT_KINDS:
        _fail("context_kind 非法", f"{path}.context_kind", code="WEEKLY_AI_OUTPUT_INVALID")
    return {
        "source_kind": "ai_supplement",
        "manual_item_id": None,
        "daily_plan_id": None,
        "content_id": None,
        "content_version": None,
        "content_hash": None,
        "section": None,
        "group_id": None,
        "game_id": None,
        "context_kind": context,
        "area": _text(raw.get("area"), f"{path}.area", allow_none=True),
        "name": _text(raw.get("name"), f"{path}.name", maximum=MAX_NAME_CHARS, nonempty=True),
        "objectives": _text(raw.get("objectives"), f"{path}.objectives", allow_none=True),
        "guidance": _text(raw.get("guidance"), f"{path}.guidance", allow_none=True),
        "support_strategy": _text(raw.get("support_strategy"), f"{path}.support_strategy", allow_none=True),
        "basis_keys": _basis_handles(raw.get("basis_handles"), manifest, f"{path}.basis_handles"),
    }


def parse_games_candidate(raw: str | bytes, *, server_manifest: Mapping[str, Any]) -> dict:
    manifest = validate_handle_manifest(server_manifest)
    if manifest["task_type"] != "weekly_games_select":
        _fail("server manifest task_type 不是游戏任务", "server_manifest.task_type")
    data = strict_json_object(raw)
    _exact(data, frozenset({"outdoor_game_slots", "focus_area"}), "games")
    slots_raw = _map(data.get("outdoor_game_slots"), "games.outdoor_game_slots")
    _exact(slots_raw, frozenset(OUTDOOR_KEYS), "games.outdoor_game_slots")
    slots: dict[str, Any] = {}
    for key in OUTDOOR_KEYS:
        value = slots_raw.get(key)
        path = f"games.outdoor_game_slots.{key}"
        if value is None:
            slots[key] = None
            continue
        item = _map(value, path)
        if item.get("kind") == "source":
            _exact(item, frozenset({"kind", "source_handle"}), path)
            handle, entry = _resolve_handle(
                manifest, item.get("source_handle"), allowed={"morning_game"}
            )
            slots[key] = _resolved_outdoor(handle, entry, key)
        elif item.get("kind") == "ai_supplement":
            slots[key] = _parse_ai_outdoor(item, manifest, path)
        else:
            _fail("kind 必须是 source/ai_supplement", f"{path}.kind", code="WEEKLY_AI_OUTPUT_INVALID")
    focus_value = data.get("focus_area")
    if focus_value is None:
        focus = None
    else:
        focus_raw = _map(focus_value, "games.focus_area")
        if focus_raw.get("kind") == "source":
            _exact(focus_raw, frozenset({"kind", "source_handle"}), "games.focus_area")
            handle, entry = _resolve_handle(
                manifest, focus_raw.get("source_handle"), allowed={"post_group_game"}
            )
            focus = _resolved_focus(handle, entry)
        elif focus_raw.get("kind") == "ai_supplement":
            focus = _parse_ai_focus(focus_raw, manifest, "games.focus_area")
        else:
            _fail("kind 必须是 source/ai_supplement", "games.focus_area.kind", code="WEEKLY_AI_OUTPUT_INVALID")
    by_name: dict[str, str] = {}
    for key in ("collective_1", "collective_2"):
        slot = slots[key]
        if slot is None:
            continue
        name = str(slot.get("name") or "").strip()
        if not name:
            continue
        if name in by_name:
            _fail("同类别同名游戏不能占两个集体槽", f"games.outdoor_game_slots.{key}", code="WEEKLY_AI_OUTPUT_INVALID")
        by_name[name] = key
    return {"outdoor_game_slots": slots, "focus_area": focus}


def finalize_games_value(
    value: Mapping[str, Any],
    *,
    candidate_id: str,
    input_id: str,
    ai_item_ids: Mapping[str, str],
) -> dict:
    cid = _id(candidate_id, "candidate_id")
    iid = _id(input_id, "input_id")
    data = _map(value, "candidate_value")
    _exact(data, frozenset({"outdoor_game_slots", "focus_area"}), "candidate_value")
    slots = _map(data.get("outdoor_game_slots"), "candidate_value.outdoor_game_slots")
    _exact(slots, frozenset(OUTDOOR_KEYS), "candidate_value.outdoor_game_slots")
    used_ids: set[str] = set()

    def finalize(item: Any, key: str, *, focus: bool) -> Any:
        if item is None:
            return None
        entry = _map(item, f"candidate_value.{key}")
        if entry.get("source_kind") != "ai_supplement":
            return copy.deepcopy(entry)
        item_id = ai_item_ids.get(key)
        if not isinstance(item_id, str) or not (1 <= len(item_id) <= MAX_ID_CHARS):
            _fail("AI 项缺少稳定 ai_item_id", f"ai_item_ids.{key}", code="WEEKLY_AI_OUTPUT_INVALID")
        if item_id in used_ids:
            _fail("ai_item_id 重复", f"ai_item_ids.{key}", code="WEEKLY_AI_OUTPUT_INVALID")
        used_ids.add(item_id)
        result = copy.deepcopy(entry)
        result["ai_item_id"] = item_id
        result["candidate_id"] = cid
        result["input_id"] = iid
        return result

    finalized_slots = {
        key: finalize(slots.get(key), key, focus=False) for key in OUTDOOR_KEYS
    }
    focus = finalize(data.get("focus_area"), "focus_area", focus=True)
    extra_ids = set(ai_item_ids) - set(OUTDOOR_KEYS) - {"focus_area"}
    if extra_ids:
        _fail(
            "ai_item_ids 含未知目标",
            "ai_item_ids",
            code="WEEKLY_AI_OUTPUT_INVALID",
            details={"extra_count": len(extra_ids)},
        )
    return {"outdoor_game_slots": finalized_slots, "focus_area": focus}


def parse_column_candidate(raw: str | bytes, *, task_type: str) -> dict:
    if task_type not in COLUMN_TASK.values():
        _fail("不是周栏目任务", "task_type")
    data = strict_json_object(raw)
    _exact(data, frozenset({"text"}), "column")
    text = _text(
        data.get("text"), "column.text", maximum=MAX_AI_TEXT_CHARS, nonempty=True
    )
    return {"text": text}


def _source_text(entry: Mapping[str, Any], field_path: str) -> str:
    value = entry.get(field_path)
    text = _text(value, f"source.{field_path}", allow_none=True)
    return text or ""


def parse_materials_candidate(raw: str | bytes, *, server_manifest: Mapping[str, Any]) -> dict:
    manifest = validate_handle_manifest(server_manifest)
    if manifest["task_type"] != "weekly_materials_generate":
        _fail("server manifest task_type 不是材料任务", "server_manifest.task_type")
    data = strict_json_object(raw)
    _exact(data, frozenset({"items"}), "materials")
    items_raw = data.get("items")
    if not isinstance(items_raw, list) or len(items_raw) > MAX_MATERIAL_ITEMS:
        _fail("materials.items 必须是有限数组", "materials.items", code="WEEKLY_AI_OUTPUT_INVALID")
    items: list[dict] = []
    for index, raw_item in enumerate(items_raw):
        path = f"materials.items[{index}]"
        item = _map(raw_item, path)
        _exact(item, frozenset({"text", "origin", "evidence_refs"}), path)
        text = _text(item.get("text"), f"{path}.text", maximum=MAX_MATERIAL_ITEM_TEXT, nonempty=True)
        origin = item.get("origin")
        if origin not in ("extracted", "suggested"):
            _fail("origin 非法", f"{path}.origin", code="WEEKLY_AI_OUTPUT_INVALID")
        refs_raw = item.get("evidence_refs")
        if not isinstance(refs_raw, list) or len(refs_raw) > MAX_AI_ARRAY_ITEMS:
            _fail("evidence_refs 必须是有限数组", f"{path}.evidence_refs", code="WEEKLY_AI_OUTPUT_INVALID")
        if origin == "extracted" and not refs_raw:
            _fail("extracted 必须有证据", f"{path}.evidence_refs", code="WEEKLY_AI_OUTPUT_INVALID")
        if origin == "suggested" and refs_raw:
            _fail("suggested 不得有证据", f"{path}.evidence_refs", code="WEEKLY_AI_OUTPUT_INVALID")
        refs: list[dict] = []
        seen: set[tuple[Any, ...]] = set()
        for ref_index, raw_ref in enumerate(refs_raw):
            ref_path = f"{path}.evidence_refs[{ref_index}]"
            ref = _map(raw_ref, ref_path)
            _exact(
                ref,
                frozenset({"source_handle", "field_path", "start", "end", "quote"}),
                ref_path,
            )
            handle, entry = _resolve_handle(manifest, ref.get("source_handle"))
            field_path = _text(ref.get("field_path"), f"{ref_path}.field_path", maximum=64, nonempty=True)
            if field_path not in EVIDENCE_FIELD_PATHS[entry["kind"]]:
                _fail("field_path 不允许", f"{ref_path}.field_path", code="WEEKLY_AI_OUTPUT_INVALID")
            start = ref.get("start")
            end = ref.get("end")
            if type(start) is not int or type(end) is not int or start < 0 or end <= start:
                _fail("证据位置非法", ref_path, code="WEEKLY_AI_OUTPUT_INVALID")
            quote = _text(ref.get("quote"), f"{ref_path}.quote", maximum=MAX_MATERIAL_QUOTE, nonempty=True)
            source_text = _source_text(entry, field_path)
            if end > len(source_text) or source_text[start:end] != quote:
                _fail("证据位置与原文不匹配", ref_path, code="WEEKLY_AI_OUTPUT_INVALID")
            key = (handle, field_path, start, end, quote)
            if key in seen:
                _fail("证据重复", ref_path, code="WEEKLY_AI_OUTPUT_INVALID")
            seen.add(key)
            refs.append(
                {
                    "source_handle": handle,
                    "field_path": field_path,
                    "start": start,
                    "end": end,
                    "quote": quote,
                }
            )
        items.append({"text": text, "origin": origin, "evidence_refs": refs})
    synthesized = "\n".join(item["text"] for item in items)
    if len(synthesized) > MAX_MATERIAL_SYNTHESIS:
        _fail("材料正文超限", "materials.items", code="WEEKLY_AI_OUTPUT_INVALID")
    return {"items": items}


STORED_SOURCE_OUTDOOR_KEYS = frozenset(
    {
        "source_kind",
        "manual_item_id",
        "daily_plan_id",
        "content_id",
        "content_version",
        "content_hash",
        "section",
        "group_id",
        "game_id",
        "name",
        "shared_objectives",
        "guidance_points",
        "focus_guidance",
    }
)
STORED_AI_OUTDOOR_KEYS = STORED_SOURCE_OUTDOOR_KEYS | {"basis_keys"}
STORED_SOURCE_FOCUS_KEYS = frozenset(
    {
        "source_kind",
        "manual_item_id",
        "daily_plan_id",
        "content_id",
        "content_version",
        "content_hash",
        "section",
        "group_id",
        "game_id",
        "context_kind",
        "area",
        "name",
        "objectives",
        "guidance",
        "support_strategy",
    }
)
STORED_AI_FOCUS_KEYS = STORED_SOURCE_FOCUS_KEYS | {"basis_keys"}


def _stored_fail(reason: str, field_path: str = "candidate_value") -> None:
    _fail(
        "存储候选不合法",
        field_path,
        code="WEEKLY_AI_OUTPUT_INVALID",
        details={"reason": reason},
    )


def _stored_map(value: object, field_path: str) -> dict:
    if not isinstance(value, Mapping):
        _stored_fail("not_object", field_path)
    return dict(value)


def _rethrow_stored(exc: WeeklyAIContractError) -> None:
    raise WeeklyAIContractError(
        "存储候选不合法",
        code="WEEKLY_AI_OUTPUT_INVALID",
        field_path=exc.field_path or "candidate_value",
        details={"reason": "stored_candidate_invalid"},
    ) from None


def _stored_game_wire(
    item: object,
    manifest: Mapping[str, Any],
    key: str,
    *,
    focus: bool,
) -> dict | None:
    if item is None:
        return None
    if not isinstance(item, Mapping):
        _stored_fail("not_object", f"games.{key}")
    data = dict(item)
    if data.get("source_kind") == "daily_plan":
        source_keys = STORED_SOURCE_FOCUS_KEYS if focus else STORED_SOURCE_OUTDOOR_KEYS
        if set(data) != set(source_keys):
            _stored_fail("source_key_mismatch", f"games.{key}")
        allowed_kind = "post_group_game" if focus else "morning_game"
        matches: list[str] = []
        for handle, entry in manifest["handles"].items():
            if entry["kind"] != allowed_kind:
                continue
            try:
                expected = (
                    _resolved_focus(handle, entry)
                    if focus
                    else _resolved_outdoor(handle, entry, key)
                )
            except WeeklyAIContractError:
                continue
            if data == expected:
                matches.append(handle)
        if len(matches) != 1:
            _stored_fail("source_mismatch", f"games.{key}")
        return {"kind": "source", "source_handle": matches[0]}
    if data.get("source_kind") == "ai_supplement":
        expected_keys = STORED_AI_FOCUS_KEYS if focus else STORED_AI_OUTDOOR_KEYS
        if set(data) != set(expected_keys):
            _stored_fail("ai_key_mismatch", f"games.{key}")
        wire: dict[str, Any] = {
            "kind": "ai_supplement",
            "name": data["name"],
            "basis_handles": copy.deepcopy(data["basis_keys"]),
        }
        if focus:
            wire.update(
                {
                    "context_kind": data["context_kind"],
                    "area": data["area"],
                    "objectives": data["objectives"],
                    "guidance": data["guidance"],
                    "support_strategy": data["support_strategy"],
                }
            )
        else:
            wire.update(
                {
                    "shared_objectives": data["shared_objectives"],
                    "guidance_points": data["guidance_points"],
                    "focus_guidance": data["focus_guidance"],
                }
            )
        return wire
    _stored_fail("source_kind_invalid", f"games.{key}")
    return None


def validate_stored_candidate(
    task_type: object,
    value: object,
    *,
    server_manifest: Mapping[str, Any],
) -> dict:
    """Validate an already-parsed/stored candidate without repairing it."""
    if task_type not in TASK_TARGETS:
        _stored_fail("task_type_invalid", "task_type")
    try:
        manifest = validate_handle_manifest(server_manifest)
    except WeeklyAIContractError:
        raise WeeklyAIContractError(
            "存储候选不合法",
            code="WEEKLY_AI_OUTPUT_INVALID",
            field_path="server_manifest",
            details={"reason": "manifest_invalid"},
        ) from None
    if manifest["task_type"] != task_type:
        _stored_fail("task_type_mismatch", "task_type")
    if task_type == "weekly_games_select":
        data = _stored_map(value, "candidate_value")
        try:
            _exact(data, frozenset({"outdoor_game_slots", "focus_area"}), "candidate_value")
        except WeeklyAIContractError:
            _stored_fail("key_mismatch", "candidate_value")
        slots = _stored_map(data.get("outdoor_game_slots"), "candidate_value.outdoor_game_slots")
        try:
            _exact(slots, frozenset(OUTDOOR_KEYS), "candidate_value.outdoor_game_slots")
        except WeeklyAIContractError:
            _stored_fail("key_mismatch", "candidate_value.outdoor_game_slots")
        wire = {
            "outdoor_game_slots": {
                key: _stored_game_wire(slots.get(key), manifest, key, focus=False)
                for key in OUTDOOR_KEYS
            },
            "focus_area": _stored_game_wire(
                data.get("focus_area"), manifest, "focus_area", focus=True
            ),
        }
        try:
            raw = json.dumps(
                wire, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            )
        except (TypeError, ValueError):
            _stored_fail("not_json", "candidate_value")
        try:
            parsed = parse_games_candidate(raw, server_manifest=manifest)
        except WeeklyAIContractError as exc:
            _rethrow_stored(exc)
        if parsed != value:
            _stored_fail("candidate_changed", "candidate_value")
        return copy.deepcopy(parsed)
    if task_type in COLUMN_TASK.values():
        data = _stored_map(value, "column")
        try:
            _exact(data, frozenset({"text"}), "column")
            raw = json.dumps(
                {"text": data["text"]},
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
            parsed = parse_column_candidate(raw, task_type=task_type)
        except WeeklyAIContractError as exc:
            _rethrow_stored(exc)
        except (TypeError, ValueError):
            _stored_fail("not_json", "column")
        if parsed != value:
            _stored_fail("candidate_changed", "column")
        return copy.deepcopy(parsed)
    if task_type == "weekly_materials_generate":
        data = _stored_map(value, "materials")
        try:
            _exact(data, frozenset({"items"}), "materials")
            raw = json.dumps(
                {"items": data["items"]},
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
            parsed = parse_materials_candidate(raw, server_manifest=manifest)
        except WeeklyAIContractError as exc:
            _rethrow_stored(exc)
        except (TypeError, ValueError):
            _stored_fail("not_json", "materials")
        if parsed != value:
            _stored_fail("candidate_changed", "materials")
        return copy.deepcopy(parsed)
    _stored_fail("task_type_invalid", "task_type")
    return {}


def _schema_for(task_type: str) -> dict:
    target = TASK_TARGETS[task_type]
    common = {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "task_type"],
        "properties": {
            "schema_version": {"const": 1},
            "task_type": {"const": task_type},
        },
    }
    if task_type == "weekly_games_select":
        source_slot = {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "source_handle"],
            "properties": {
                "kind": {"const": "source"},
                "source_handle": {"type": "string", "pattern": "^m[0-9]{1,5}$"},
            },
        }
        source_focus = {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "source_handle"],
            "properties": {
                "kind": {"const": "source"},
                "source_handle": {"type": "string", "pattern": "^p[0-9]{1,5}$"},
            },
        }
        basis_handles = {
            "type": "array",
            "maxItems": MAX_BASIS_HANDLES,
            "uniqueItems": True,
            "items": {"type": "string", "pattern": "^c[0-9]{1,5}$"},
        }
        ai_outdoor = {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "kind",
                "name",
                "shared_objectives",
                "guidance_points",
                "focus_guidance",
                "basis_handles",
            ],
            "properties": {
                "kind": {"const": "ai_supplement"},
                "name": {"type": "string", "minLength": 1, "maxLength": MAX_NAME_CHARS},
                "shared_objectives": {"type": ["string", "null"], "maxLength": MAX_AI_TEXT_CHARS},
                "guidance_points": {"type": ["string", "null"], "maxLength": MAX_AI_TEXT_CHARS},
                "focus_guidance": {"type": ["string", "null"], "maxLength": MAX_AI_TEXT_CHARS},
                "basis_handles": basis_handles,
            },
        }
        ai_focus = {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "kind",
                "context_kind",
                "area",
                "name",
                "objectives",
                "guidance",
                "support_strategy",
                "basis_handles",
            ],
            "properties": {
                "kind": {"const": "ai_supplement"},
                "context_kind": {"enum": list(FOCUS_CONTEXT_KINDS)},
                "area": {"type": ["string", "null"], "maxLength": MAX_AI_TEXT_CHARS},
                "name": {"type": "string", "minLength": 1, "maxLength": MAX_NAME_CHARS},
                "objectives": {"type": ["string", "null"], "maxLength": MAX_AI_TEXT_CHARS},
                "guidance": {"type": ["string", "null"], "maxLength": MAX_AI_TEXT_CHARS},
                "support_strategy": {"type": ["string", "null"], "maxLength": MAX_AI_TEXT_CHARS},
                "basis_handles": basis_handles,
            },
        }
        output = {
            "type": "object",
            "additionalProperties": False,
            "required": ["outdoor_game_slots", "focus_area"],
            "properties": {
                "outdoor_game_slots": {
                    "type": "object",
                    "required": list(OUTDOOR_KEYS),
                    "additionalProperties": False,
                    "properties": {
                        key: {"oneOf": [{"type": "null"}, source_slot, ai_outdoor]}
                        for key in OUTDOOR_KEYS
                    },
                },
                "focus_area": {"oneOf": [{"type": "null"}, source_focus, ai_focus]},
            },
        }
    elif task_type in COLUMN_TASK.values():
        output = {
            "type": "object",
            "additionalProperties": False,
            "required": ["text"],
            "properties": {"text": {"type": "string", "minLength": 1}},
        }
    else:
        evidence = {
            "type": "object",
            "additionalProperties": False,
            "required": ["source_handle", "field_path", "start", "end", "quote"],
            "properties": {
                "source_handle": {"type": "string", "pattern": "^[a-z][0-9]{1,5}$"},
                "field_path": {
                    "enum": sorted(
                        {
                            path
                            for allowed in EVIDENCE_FIELD_PATHS.values()
                            for path in allowed
                        }
                    )
                },
                "start": {"type": "integer", "minimum": 0},
                "end": {"type": "integer", "minimum": 1},
                "quote": {"type": "string", "minLength": 1, "maxLength": MAX_MATERIAL_QUOTE},
            },
        }
        common_item = {
            "type": "object",
            "additionalProperties": False,
            "required": ["text", "origin", "evidence_refs"],
            "properties": {
                "text": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": MAX_MATERIAL_ITEM_TEXT,
                },
                "origin": {"type": "string", "enum": ["extracted", "suggested"]},
                "evidence_refs": {
                    "type": "array",
                    "maxItems": MAX_AI_ARRAY_ITEMS,
                    "items": evidence,
                },
            },
        }
        extracted_item = {
            **common_item,
            "properties": {
                **common_item["properties"],
                "origin": {"const": "extracted"},
                "evidence_refs": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": MAX_AI_ARRAY_ITEMS,
                    "items": evidence,
                },
            },
        }
        suggested_item = {
            **common_item,
            "properties": {
                **common_item["properties"],
                "origin": {"const": "suggested"},
                "evidence_refs": {
                    "type": "array",
                    "maxItems": 0,
                    "items": evidence,
                },
            },
        }
        output = {
            "type": "object",
            "additionalProperties": False,
            "required": ["items"],
            "properties": {
                "items": {
                    "type": "array",
                    "maxItems": MAX_MATERIAL_ITEMS,
                    "items": {"oneOf": [extracted_item, suggested_item]},
                }
            },
        }
    input_schema = common
    guidance = {
        "target": target,
        "language": "zh-CN",
        "strict_json": True,
        "no_fabricated_sources": True,
    }
    if task_type == "weekly_games_select":
        guidance["instructions"] = (
            "只输出一个 JSON 对象，顶层只含 outdoor_game_slots 和 focus_area。"
            " outdoor_game_slots 必须含 collective_1、collective_2、free_choice_1 三个键；"
            "每个槽及 focus_area 只能是 null、{kind:source, source_handle} 或 "
            "{kind:ai_supplement, ...}。source 只能引用输入中明确给出的 m 类日晨间游戏"
            "（focus 用 p 类集体后游戏）；ai_supplement 必须给出对应类别的完整文本和 "
            "basis_handles，basis_handles 只能引用输入中的 c 类配置上下文。"
            "不得编造 source_handle、不得把配置上下文当游戏来源；两个集体槽不能同名。"
        )
    elif task_type == "weekly_materials_generate":
        guidance["instructions"] = (
            "只输出一个 JSON 对象，顶层只含 items。items 可为空数组；每项只含 "
            "text、origin、evidence_refs。text 为具体材料或用品，1–300 字符；"
            "origin 只能是 extracted 或 suggested。extracted 至少一条证据，证据只含 "
            "source_handle、field_path、start、end、quote；suggested 的 evidence_refs "
            "必须为空数组。start/end 是 Unicode code point、0 起点、左闭右开，"
            "end 大于 start；quote 必须与原文切片逐字相同，不得伪造来源、拼接口径或"
            "把泛称材料猜成具体用品。所有 items 的正文按顺序以单个换行连接，"
            "总长不超过 20000 字符。当 selection.focus_area 为 null 时，"
            "所有 items 都必须是 origin=suggested 且 evidence_refs=[]；只能依据"
            " grade、weekly_context、theme、suggestion_context 和已保存的可靠已选"
            "上下文设计材料，不得输出 source_handle 或声称来自原文。"
        )
    elif task_type == "weekly_habit_culture":
        guidance["allowed_input_fields"] = [
            "date",
            "morning_talk_topic",
            "morning_groups.guidance_points",
            "morning_groups.focus_guidance",
            "post_support.support_strategy",
        ]
    if task_type == "weekly_habit_culture":
        input_schema = {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "schema_version",
                "task_type",
                "grade",
                "theme",
                "days",
                "teacher_text",
            ],
            "properties": {
                "schema_version": {"const": 1},
                "task_type": {"const": task_type},
                "grade": {"type": "string"},
                "theme": {"type": "string"},
                "days": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "date",
                            "morning_talk_topic",
                            "morning_groups",
                            "post_support",
                        ],
                        "properties": {
                            "date": {"type": "string"},
                            "morning_talk_topic": {"type": ["string", "null"]},
                            "morning_groups": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "required": [
                                        "guidance_points",
                                        "focus_guidance",
                                    ],
                                    "properties": {
                                        "guidance_points": {
                                            "type": ["string", "null"]
                                        },
                                        "focus_guidance": {
                                            "type": ["string", "null"]
                                        },
                                    },
                                },
                            },
                            "post_support": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "required": ["support_strategy"],
                                    "properties": {
                                        "support_strategy": {
                                            "type": ["string", "null"]
                                        }
                                    },
                                },
                            },
                        },
                    },
                },
                "teacher_text": {"type": "string"},
            },
        }
        guidance["allowed_input_fields"] = [
            "date",
            "morning_talk_topic",
            "morning_groups.guidance_points",
            "morning_groups.focus_guidance",
            "post_support.support_strategy",
        ]
    return {
        "task_type": task_type,
        "contract_version": prompt_contract_version(task_type),
        "default_revision": 1,
        "input_schema_json": input_schema,
        "output_schema_json": output,
        "guidance_defaults_json": guidance,
    }


def weekly_bundle_definitions() -> tuple[dict[str, Any], ...]:
    return tuple(copy.deepcopy(_schema_for(task_type)) for task_type in TASK_ORDER)


__all__ = [
    "CONTRACT_VERSION",
    "AI_INPUT_SCHEMA_VERSION",
    "TASK_TARGETS",
    "TASK_ORDER",
    "COLUMN_FIELDS",
    "COLUMN_TASK",
    "TARGETS",
    "HANDLE_RE",
    "WeeklyAIContractError",
    "value_hash",
    "candidate_hash",
    "strict_json_object",
    "normalize_selected_fields",
    "task_types_for_columns",
    "target_for_task",
    "prompt_contract_version",
    "supports_prompt_contract",
    "validate_typed_handle",
    "validate_handle_manifest",
    "parse_games_candidate",
    "finalize_games_value",
    "parse_column_candidate",
    "parse_materials_candidate",
    "validate_stored_candidate",
    "weekly_bundle_definitions",
]
