"""Pure weekly-materials basis, evidence and synthesis rules.

No database, runtime, network or vendor imports.  This module builds the
selected/material basis from an already validated weekly content value,
materialises model evidence against one input-local typed handle manifest, and
constructs the frozen ``materials_provenance`` object.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from app.local import weekly_ai_contracts as contracts
from app.local import weekly_plan_content as content_mod

MAX_MATERIAL_ITEMS = 100
MAX_MATERIAL_ITEM_TEXT = 300
MAX_MATERIAL_QUOTE = 2_000
MAX_MATERIAL_SYNTHESIS = 20_000
MAX_BASIS_HANDLES = 100

EVIDENCE_KEYS = frozenset(
    {"source_handle", "field_path", "start", "end", "quote"}
)
STORED_EVIDENCE_KEYS = frozenset(
    {"source_handle", "field_path", "start", "end", "quote", "source"}
)
ITEM_KEYS = frozenset({"text", "origin", "evidence_refs"})
BASIS_KEYS = frozenset(
    {
        "schema_version",
        "target",
        "grade",
        "theme",
        "manual_text",
        "daily_sources",
        "selected",
        "config",
        "calendar",
    }
)
PROVENANCE_KEYS = frozenset(
    {
        "candidate_id",
        "candidate_hash",
        "input_id",
        "execution_id",
        "contract_version",
        "dependency_hash",
        "basis",
        "basis_hash",
        "items",
        "original_text",
        "edited",
        "adopter_profile_id",
        "adopted_draft_id",
        "adopted_draft_version",
        "adopted_at",
    }
)
CONFIG_REF_KEYS = frozenset(
    {"revision_id", "revision_no", "kind", "name", "occurrence"}
)


def _fail(
    message: str,
    field_path: str = "",
    *,
    code: str = "WEEKLY_CONTENT_INVALID",
    details: Mapping[str, Any] | None = None,
) -> None:
    raise content_mod.WeeklyContentError(
        message, field_path=field_path, code=code, details=details
    )


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
        _fail("值不可规范序列化", "value")


def _hash(value: Any, field_path: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        ch not in "0123456789abcdef" for ch in value
    ):
        _fail("必须是 64 位小写十六进制", field_path)
    return value


def _id(value: Any, field_path: str) -> str:
    if not isinstance(value, str) or not (1 <= len(value) <= 32) or "\x00" in value:
        _fail("ID 不合法", field_path)
    return value


def _positive_int(value: Any, field_path: str) -> int:
    if type(value) is not int or value < 1:
        _fail("必须是正整数", field_path)
    return value


def _text(
    value: Any,
    field_path: str,
    *,
    allow_none: bool = False,
    maximum: int = 100_000,
    nonempty: bool = False,
) -> str | None:
    if value is None:
        if allow_none:
            return None
        _fail("必须是字符串", field_path)
    if not isinstance(value, str):
        _fail("必须是字符串", field_path)
    if "\x00" in value:
        _fail("字符串不得包含 NUL", field_path)
    if len(value) > maximum:
        _fail("文本超限", field_path, details={"max": maximum})
    if nonempty and not value.strip():
        _fail("文本不能为空", field_path)
    return value


def _utc_timestamp(value: Any, field_path: str) -> str:
    text = _text(value, field_path, maximum=64, nonempty=True)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        _fail("必须是 ISO 时间", field_path)
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        _fail("必须是 UTC 时间", field_path)
    return text


def _source_text(source: Mapping[str, Any], field_path: str) -> str:
    value = source.get(field_path)
    if value is None:
        return ""
    if not isinstance(value, str):
        _fail("来源文本必须是字符串", f"source.{field_path}")
    return value


def _config_refs_from_basis(config: Any) -> list[dict]:
    if not isinstance(config, list):
        _fail("basis.config 必须是数组", "basis.config")
    refs: list[dict] = []
    seen: set[tuple[Any, ...]] = set()
    for index, item in enumerate(config):
        if not isinstance(item, Mapping):
            _fail("basis.config 项必须是对象", f"basis.config[{index}]")
        for loc_index, location in enumerate(item.get("locations") or []):
            if not isinstance(location, Mapping):
                _fail("配置地点必须是对象", f"basis.config[{index}].locations[{loc_index}]")
            ref = {
                "revision_id": item.get("revision_id"),
                "revision_no": item.get("revision_no"),
                "kind": location.get("kind"),
                "name": location.get("name"),
                "occurrence": location.get("occurrence"),
            }
            key = (
                ref["revision_id"],
                ref["revision_no"],
                ref["kind"],
                ref["name"],
                ref["occurrence"],
            )
            if key in seen:
                continue
            seen.add(key)
            refs.append(ref)
    refs.sort(
        key=lambda item: (
            str(item.get("kind")),
            str(item.get("name")),
            int(item.get("occurrence") or 0),
        )
    )
    return refs


def _ai_basis(item: Mapping[str, Any], content: Mapping[str, Any]) -> dict:
    provenance = (content.get("ai_provenance") or {}).get("games")
    if provenance is None:
        _fail("AI 项缺少 games provenance", "ai_provenance.games")
    basis = provenance.get("basis") or {}
    if basis.get("target") != "games":
        _fail("games provenance basis 目标不匹配", "ai_provenance.games.basis.target")
    candidate_id = item.get("candidate_id")
    input_id = item.get("input_id")
    ai_item_id = item.get("ai_item_id")
    if (
        candidate_id != provenance.get("candidate_id")
        or input_id != provenance.get("input_id")
        or ai_item_id is None
    ):
        _fail("AI 项身份与 games provenance 不一致", "ai_provenance.games")
    basis_keys = item.get("basis_keys") or []
    if not isinstance(basis_keys, list) or len(basis_keys) > MAX_BASIS_HANDLES:
        _fail("basis_keys 必须是有限数组", "ai_basis.basis_keys")
    flattened: list[dict] = []
    for config_entry in basis.get("config") or []:
        if not isinstance(config_entry, Mapping):
            continue
        for location in config_entry.get("locations") or []:
            if not isinstance(location, Mapping):
                continue
            flattened.append(
                {
                    "revision_id": config_entry.get("revision_id"),
                    "revision_no": config_entry.get("revision_no"),
                    "kind": location.get("kind"),
                    "name": location.get("name"),
                    "occurrence": location.get("occurrence"),
                }
            )
    config_refs: list[dict] = []
    for handle in basis_keys:
        if not isinstance(handle, str) or not handle.startswith("c"):
            _fail("AI 项 basis_keys 必须是配置句柄", "ai_basis.basis_keys")
        try:
            index = int(handle[1:]) - 1
        except ValueError:
            _fail("AI 项 basis_keys 非法", "ai_basis.basis_keys")
        if index < 0 or index >= len(flattened):
            _fail("AI 项 basis_keys 超出配置依据", "ai_basis.basis_keys")
        config_refs.append(copy.deepcopy(flattened[index]))
    config_refs.sort(
        key=lambda ref: (
            str(ref.get("kind")),
            str(ref.get("name")),
            int(ref.get("occurrence") or 0),
        )
    )
    return {
        "candidate_id": _id(candidate_id, "ai_basis.candidate_id"),
        "candidate_hash": _hash(provenance.get("candidate_hash"), "ai_basis.candidate_hash"),
        "input_id": _id(input_id, "ai_basis.input_id"),
        "execution_id": _id(provenance.get("execution_id"), "ai_basis.execution_id"),
        "contract_version": _positive_int(
            provenance.get("contract_version"), "ai_basis.contract_version"
        ),
        "dependency_hash": _hash(
            provenance.get("dependency_hash"), "ai_basis.dependency_hash"
        ),
        "adopted_value_hash": _hash(
            provenance.get("adopted_value_hash"), "ai_basis.adopted_value_hash"
        ),
        "ai_item_id": _id(ai_item_id, "ai_basis.ai_item_id"),
        "source_ref": None,
        "config_refs": config_refs,
    }


def build_selected_basis(*, grade: str, content: Mapping[str, Any]) -> dict:
    """Build SelectedBasisV1 from the saved draft's explicit selection."""
    fixed = content_mod.validate_content(content)
    if grade not in content_mod.GRADES:
        _fail("年级非法", "grade")
    if fixed["source_manifest"]["header"]["grade"] != grade:
        _fail("grade 与周稿表头不一致", "grade")
    slots: dict[str, Any] = {}
    for key in content_mod.OUTDOOR_SLOT_KEYS:
        slot = fixed["outdoor_game_slots"].get(key)
        if slot is None:
            slots[key] = None
            continue
        item = {"value": copy.deepcopy(slot), "ai_basis": None}
        if slot.get("source_kind") == "ai_supplement":
            item["ai_basis"] = _ai_basis(slot, fixed)
        slots[key] = item
    focus = fixed["focus_area"]
    if focus is None:
        focus_item = None
    else:
        focus_item = {"value": copy.deepcopy(focus), "ai_basis": None}
        if focus.get("source_kind") == "ai_supplement":
            focus_item["ai_basis"] = _ai_basis(focus, fixed)
    return {"outdoor_game_slots": slots, "focus_area": focus_item}


def _filter_configs(
    content: Mapping[str, Any], refs: Sequence[Mapping[str, Any]]
) -> list[dict]:
    if not refs:
        return []
    provenance = (content.get("ai_provenance") or {}).get("games")
    if provenance is None:
        return []
    config = (provenance.get("basis") or {}).get("config") or []
    wanted = {
        (
            ref.get("revision_id"),
            ref.get("revision_no"),
            ref.get("kind"),
            ref.get("name"),
            ref.get("occurrence"),
        )
        for ref in refs
    }
    result: list[dict] = []
    for entry in config:
        if not isinstance(entry, Mapping):
            continue
        locations: list[dict] = []
        for location in entry.get("locations") or []:
            if not isinstance(location, Mapping):
                continue
            key = (
                entry.get("revision_id"),
                entry.get("revision_no"),
                location.get("kind"),
                location.get("name"),
                location.get("occurrence"),
            )
            if key not in wanted:
                continue
            locations.append(copy.deepcopy(dict(location)))
        if not locations:
            continue
        result.append(
            {
                "revision_id": entry.get("revision_id"),
                "revision_no": entry.get("revision_no"),
                "game_scope": entry.get("game_scope"),
                "guidance": entry.get("guidance"),
                "locations": locations,
            }
        )
    result.sort(key=lambda item: (item.get("revision_no") or 0, str(item.get("revision_id"))))
    return result


def build_materials_basis(*, grade: str, content: Mapping[str, Any]) -> dict:
    """Build BasisV1 for target ``materials`` from the saved selection."""
    fixed = content_mod.validate_content(content)
    # With no saved focus area the task remains valid: the provider may return
    # only ``suggested`` items (empty evidence) from grade/theme/selected
    # context, and the teacher still previews/adopts through the normal flow.
    selected = build_selected_basis(grade=grade, content=fixed)
    refs: list[dict] = []
    for item in selected["outdoor_game_slots"].values():
        if item is not None and item["ai_basis"] is not None:
            refs.extend(item["ai_basis"]["config_refs"])
    if selected["focus_area"] is not None and selected["focus_area"]["ai_basis"] is not None:
        refs.extend(selected["focus_area"]["ai_basis"]["config_refs"])
    return {
        "schema_version": 1,
        "target": "materials",
        "grade": grade,
        "theme": None,
        "manual_text": None,
        "daily_sources": [],
        "selected": selected,
        "config": _filter_configs(fixed, refs),
        "calendar": None,
    }


def _validate_wire_items(items: object, manifest: Mapping[str, Any]) -> list[dict]:
    if not isinstance(items, list) or len(items) > MAX_MATERIAL_ITEMS:
        _fail("items 必须是有限数组", "items", code="WEEKLY_AI_OUTPUT_INVALID")
    result: list[dict] = []
    for index, raw_item in enumerate(items):
        path = f"items[{index}]"
        if not isinstance(raw_item, Mapping):
            _fail("材料项必须是对象", path, code="WEEKLY_AI_OUTPUT_INVALID")
        item = dict(raw_item)
        if set(item) != set(ITEM_KEYS):
            _fail("材料项键不匹配", path, code="WEEKLY_AI_OUTPUT_INVALID")
        text = _text(
            item.get("text"),
            f"{path}.text",
            maximum=MAX_MATERIAL_ITEM_TEXT,
            nonempty=True,
        )
        origin = item.get("origin")
        if origin not in ("extracted", "suggested"):
            _fail("origin 非法", f"{path}.origin", code="WEEKLY_AI_OUTPUT_INVALID")
        refs_raw = item.get("evidence_refs")
        if not isinstance(refs_raw, list) or len(refs_raw) > MAX_MATERIAL_ITEMS:
            _fail("evidence_refs 必须是有限数组", f"{path}.evidence_refs", code="WEEKLY_AI_OUTPUT_INVALID")
        if origin == "extracted" and not refs_raw:
            _fail("extracted 必须有证据", f"{path}.evidence_refs", code="WEEKLY_AI_OUTPUT_INVALID")
        if origin == "suggested" and refs_raw:
            _fail("suggested 不得有证据", f"{path}.evidence_refs", code="WEEKLY_AI_OUTPUT_INVALID")
        refs: list[dict] = []
        seen: set[tuple[Any, ...]] = set()
        for ref_index, raw_ref in enumerate(refs_raw):
            ref_path = f"{path}.evidence_refs[{ref_index}]"
            if not isinstance(raw_ref, Mapping):
                _fail("证据必须是对象", ref_path, code="WEEKLY_AI_OUTPUT_INVALID")
            ref = dict(raw_ref)
            if set(ref) != set(EVIDENCE_KEYS):
                _fail("证据键不匹配", ref_path, code="WEEKLY_AI_OUTPUT_INVALID")
            handle = ref.get("source_handle")
            if not isinstance(handle, str) or not contracts.HANDLE_RE.fullmatch(handle):
                _fail("source_handle 语法非法", f"{ref_path}.source_handle", code="WEEKLY_AI_OUTPUT_INVALID")
            entry = manifest["handles"].get(handle)
            if entry is None:
                _fail("source_handle 不存在", f"{ref_path}.source_handle", code="WEEKLY_AI_OUTPUT_INVALID")
            field_path = _text(
                ref.get("field_path"),
                f"{ref_path}.field_path",
                maximum=64,
                nonempty=True,
            )
            if field_path not in contracts.EVIDENCE_FIELD_PATHS[entry["kind"]]:
                _fail("field_path 不允许", f"{ref_path}.field_path", code="WEEKLY_AI_OUTPUT_INVALID")
            start = ref.get("start")
            end = ref.get("end")
            if type(start) is not int or type(end) is not int or start < 0 or end <= start:
                _fail("证据位置非法", ref_path, code="WEEKLY_AI_OUTPUT_INVALID")
            quote = _text(
                ref.get("quote"),
                f"{ref_path}.quote",
                maximum=MAX_MATERIAL_QUOTE,
                nonempty=True,
            )
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
        result.append({"text": text, "origin": origin, "evidence_refs": refs})
    return result


def materialize_materials_items(
    items: object, *, server_manifest: Mapping[str, Any]
) -> list[dict]:
    """Attach the trusted typed handle to each already-validated wire item."""
    manifest = contracts.validate_handle_manifest(server_manifest)
    if manifest["task_type"] != "weekly_materials_generate":
        _fail("server manifest task_type 不是材料任务", "server_manifest.task_type")
    wire = _validate_wire_items(items, manifest)
    stored: list[dict] = []
    for item in wire:
        refs: list[dict] = []
        for ref in item["evidence_refs"]:
            entry = manifest["handles"][ref["source_handle"]]
            refs.append({**copy.deepcopy(ref), "source": copy.deepcopy(entry)})
        stored.append(
            {
                "text": item["text"],
                "origin": item["origin"],
                "evidence_refs": refs,
            }
        )
    return stored


def synthesize_materials_text(items: Sequence[Mapping[str, Any]]) -> str:
    """Join item texts with one newline; never append a trailing newline."""
    if not isinstance(items, (list, tuple)):
        _fail("items 必须是数组", "items")
    if len(items) > MAX_MATERIAL_ITEMS:
        _fail("items 数量超限", "items", details={"max": MAX_MATERIAL_ITEMS})
    texts: list[str] = []
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            _fail("材料项必须是对象", f"items[{index}]")
        text = _text(
            item.get("text"),
            f"items[{index}].text",
            maximum=MAX_MATERIAL_ITEM_TEXT,
            nonempty=True,
        )
        texts.append(text)
    result = "\n".join(texts)
    if len(result) > MAX_MATERIAL_SYNTHESIS:
        _fail(
            "材料正文超限",
            "materials",
            code="WEEKLY_CONTENT_TOO_LARGE",
            details={"max": MAX_MATERIAL_SYNTHESIS},
        )
    return result


def _validate_stored_item(value: Any, field_path: str) -> dict:
    if not isinstance(value, Mapping):
        _fail("材料项必须是对象", field_path)
    data = dict(value)
    if set(data) != set(ITEM_KEYS):
        _fail("材料项键不匹配", field_path)
    text = _text(
        data.get("text"),
        f"{field_path}.text",
        maximum=MAX_MATERIAL_ITEM_TEXT,
        nonempty=True,
    )
    origin = data.get("origin")
    if origin not in ("extracted", "suggested"):
        _fail("origin 非法", f"{field_path}.origin")
    refs_raw = data.get("evidence_refs")
    if not isinstance(refs_raw, list) or len(refs_raw) > MAX_MATERIAL_ITEMS:
        _fail("evidence_refs 必须是有限数组", f"{field_path}.evidence_refs")
    if origin == "extracted" and not refs_raw:
        _fail("extracted 必须有证据", f"{field_path}.evidence_refs")
    if origin == "suggested" and refs_raw:
        _fail("suggested 不得有证据", f"{field_path}.evidence_refs")
    refs: list[dict] = []
    seen: set[tuple[Any, ...]] = set()
    for index, raw_ref in enumerate(refs_raw):
        ref_path = f"{field_path}.evidence_refs[{index}]"
        if not isinstance(raw_ref, Mapping):
            _fail("证据必须是对象", ref_path)
        ref = dict(raw_ref)
        if set(ref) != set(STORED_EVIDENCE_KEYS):
            _fail("证据键不匹配", ref_path)
        handle = ref.get("source_handle")
        if not isinstance(handle, str) or not contracts.HANDLE_RE.fullmatch(handle):
            _fail("source_handle 语法非法", f"{ref_path}.source_handle")
        source = contracts.validate_typed_handle(handle, ref.get("source"))
        field_path_value = _text(
            ref.get("field_path"),
            f"{ref_path}.field_path",
            maximum=64,
            nonempty=True,
        )
        if field_path_value not in contracts.EVIDENCE_FIELD_PATHS[source["kind"]]:
            _fail("field_path 不允许", f"{ref_path}.field_path")
        start = ref.get("start")
        end = ref.get("end")
        if type(start) is not int or type(end) is not int or start < 0 or end <= start:
            _fail("证据位置非法", ref_path)
        quote = _text(
            ref.get("quote"),
            f"{ref_path}.quote",
            maximum=MAX_MATERIAL_QUOTE,
            nonempty=True,
        )
        source_text = _source_text(source, field_path_value)
        if end > len(source_text) or source_text[start:end] != quote:
            _fail("证据位置与原文不匹配", ref_path)
        key = (handle, field_path_value, start, end, quote)
        if key in seen:
            _fail("证据重复", ref_path)
        seen.add(key)
        refs.append(
            {
                "source_handle": handle,
                "field_path": field_path_value,
                "start": start,
                "end": end,
                "quote": quote,
                "source": source,
            }
        )
    return {"text": text, "origin": origin, "evidence_refs": refs}


def _normalize_basis(value: Any) -> dict:
    if not isinstance(value, Mapping):
        _fail("basis 必须是对象", "basis")
    data = dict(value)
    if set(data) != set(BASIS_KEYS):
        _fail("basis 键不匹配", "basis")
    if data.get("schema_version") != 1 or type(data.get("schema_version")) is not int:
        _fail("basis schema_version 必须为 1", "basis.schema_version")
    if data.get("target") != "materials":
        _fail("basis target 必须为 materials", "basis.target")
    grade = data.get("grade")
    if grade not in content_mod.GRADES:
        _fail("basis grade 非法", "basis.grade")
    if data.get("theme") is not None or data.get("manual_text") is not None:
        _fail("materials basis 不使用 theme/manual_text", "basis")
    if data.get("daily_sources") != []:
        _fail("materials basis 不使用 daily_sources", "basis.daily_sources")
    if data.get("calendar") is not None:
        _fail("materials basis 不使用 calendar", "basis.calendar")
    selected = data.get("selected")
    if not isinstance(selected, Mapping):
        _fail("materials basis 必须有 selected", "basis.selected")
    normalized = content_mod._normalize_basis(
        data, "basis", expected_target="materials", grade=grade
    )
    return normalized


def _basis_hash(basis: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(basis).encode("utf-8")).hexdigest()


def build_materials_provenance(
    *,
    candidate_id: str,
    candidate_hash: str,
    input_id: str,
    execution_id: str,
    contract_version: int,
    dependency_hash: str,
    basis: Mapping[str, Any],
    items: Sequence[Mapping[str, Any]],
    original_text: str,
    adopter_profile_id: str,
    adopted_draft_id: str,
    adopted_draft_version: int,
    adopted_at: str,
) -> dict:
    """Construct the exact frozen 15-key materials provenance object."""
    normalized_basis = _normalize_basis(basis)
    stored_items = [
        _validate_stored_item(item, f"items[{index}]")
        for index, item in enumerate(items)
    ]
    content_mod._validate_materials_evidence_basis(stored_items, normalized_basis)
    selected = normalized_basis.get("selected") or {}
    if selected.get("focus_area") is None:
        for item in stored_items:
            if item.get("origin") != "suggested" or item.get("evidence_refs"):
                _fail(
                    "无重点区域时材料只能为 suggested 且不得有证据",
                    "items",
                    code="WEEKLY_AI_OUTPUT_INVALID",
                )
    if not isinstance(original_text, str):
        _fail("original_text 必须是字符串", "original_text")
    expected_text = synthesize_materials_text(stored_items)
    if original_text != expected_text:
        _fail("original_text 与 items 合成不一致", "original_text")
    if len(original_text) > MAX_MATERIAL_SYNTHESIS:
        _fail("材料正文超限", "original_text", code="WEEKLY_CONTENT_TOO_LARGE")
    return {
        "candidate_id": _id(candidate_id, "candidate_id"),
        "candidate_hash": _hash(candidate_hash, "candidate_hash"),
        "input_id": _id(input_id, "input_id"),
        "execution_id": _id(execution_id, "execution_id"),
        "contract_version": _positive_int(contract_version, "contract_version"),
        "dependency_hash": _hash(dependency_hash, "dependency_hash"),
        "basis": normalized_basis,
        "basis_hash": _basis_hash(normalized_basis),
        "items": stored_items,
        "original_text": original_text,
        "edited": False,
        "adopter_profile_id": _id(adopter_profile_id, "adopter_profile_id"),
        "adopted_draft_id": _id(adopted_draft_id, "adopted_draft_id"),
        "adopted_draft_version": _positive_int(
            adopted_draft_version, "adopted_draft_version"
        ),
        "adopted_at": _utc_timestamp(adopted_at, "adopted_at"),
    }


def validate_materials_provenance(
    value: object, *, materials: object, content: Mapping[str, Any]
) -> dict | None:
    """Validate stored materials provenance against the current content."""
    fixed = content_mod.validate_content(content)
    if fixed["schema_version"] != content_mod.SCHEMA2_VERSION:
        if value is None and materials is None:
            return None
        _fail("schema1 不允许 materials provenance", "materials_provenance")
    if value is None:
        if materials is not None:
            _fail("无 provenance 时 materials 必须为 null", "materials")
        return None
    if fixed["materials"] != materials:
        _fail("materials 参数与 content 不一致", "materials")
    grade = fixed["source_manifest"]["header"]["grade"]
    normalized = content_mod._normalize_materials_provenance(
        value, "materials_provenance", materials=materials, grade=grade
    )
    if normalized is not None:
        selected = normalized.get("basis", {}).get("selected") or {}
        if selected.get("focus_area") is None:
            for item in normalized.get("items") or []:
                if item.get("origin") != "suggested" or item.get("evidence_refs"):
                    _fail(
                        "无重点区域时材料只能为 suggested 且不得有证据",
                        "materials_provenance.items",
                        code="WEEKLY_AI_OUTPUT_INVALID",
                    )
    return normalized


__all__ = [
    "MAX_MATERIAL_ITEMS",
    "MAX_MATERIAL_ITEM_TEXT",
    "MAX_MATERIAL_QUOTE",
    "MAX_MATERIAL_SYNTHESIS",
    "build_selected_basis",
    "build_materials_basis",
    "materialize_materials_items",
    "synthesize_materials_text",
    "build_materials_provenance",
    "validate_materials_provenance",
]
