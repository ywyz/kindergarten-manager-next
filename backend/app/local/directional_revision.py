"""Directional revision projection, candidate validation and source checks.

The teacher-facing operation only changes the exact selected substring of one
current editor field.  The model sees a de-identified snippet, limited context,
the teacher's instruction and a target category; it never receives photos,
names, dates, school/class text, or record/group/candidate identifiers.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.local import (
    ai_config_service,
    ai_task_service,
    ai_transport,
    directional_revision_contracts as contracts,
    listening_ai_contracts,
    listening_ai_inputs,
    listening_ai_service,
    listening_service,
    profile_service,
    weekly_ai_candidates,
    weekly_ai_contracts,
    weekly_plan_content,
)
from app.local.errors import (
    LocalAiInputTooLarge,
    LocalAiNotConfigured,
    LocalAiNotFound,
    LocalStorageError,
    LocalValidationError,
    LocalVersionConflict,
)
from app.local.models import (
    LocalAICandidate,
    LocalAIInput,
    LocalAITask,
    LocalListeningAIAdoption,
    LocalPromptBundle,
    LocalWeeklyPlan,
    LocalWeeklyPlanContent,
)
from app.local.prompt_bundles import CandidateInvalid, canonical_json
from app.local.tx import read_scope

SOURCE_KIND = "directional_revision"
TASK_TYPE = contracts.TASK_TYPE
MAX_CONTEXT_UNITS = 160
_SCOPE_KEYS = frozenset(
    {
        "kind",
        "record_id",
        "version",
        "candidate_id",
        "task_id",
        "domain",
        "group_id",
        "field",
    }
)
_SELECTION_KEYS = frozenset({"start", "end", "text"})
_ITEM_FIELD = re.compile(r"^item\.(0|[1-9][0-9]{0,3})\.text$")
_SLOT_FIELD = re.compile(
    r"^slot\.(collective_1|collective_2|free_choice_1)\.(name|shared_objectives|guidance_points|focus_guidance)$"
)
_FOCUS_FIELD = re.compile(
    r"^focus\.(name|objectives|guidance|support_strategy)$"
)
_SIGNATURE = re.compile(
    r"^(?P<prefix>[ \t]*(?:执教|授课教师|指导教师|组织教师|记录人|实施单位|"
    r"班级|活动时间|日期|署名|设计者|观察者|教师|幼儿姓名|姓名)"
    r"[ \t]*[:：][ \t]*)(?P<value>.+?)[ \t]*$",
    re.MULTILINE,
)
_DATE = re.compile(
    r"[0-9]{4}[ \t]*[-/.年][ \t]*[0-9]{1,2}[ \t]*[-/.月][ \t]*[0-9]{1,2}[ \t]*日?"
    r"|[0-9]{1,2}[ \t]*月[ \t]*[0-9]{1,2}[ \t]*日"
)
_SOURCE_CLAIMS = re.compile(
    r"来源一致|证据一致|原证据匹配|已核对来源|已验证来源|匹配原(?:文|来源)|"
    r"与原(?:文|来源)一致"
)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass(frozen=True)
class Projection:
    task_type: str
    payload: dict[str, Any]
    dependencies: dict[str, Any]
    dependency_hash: str
    target_hashes: dict[str, str]
    source_revision: int
    listening_record_id: str | None
    listening_domain: str | None
    listening_group_id: str | None
    weekly_plan_id: str | None
    weekly_draft_id: str | None


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _ensure_unicode(value: str, field: str) -> None:
    if _CONTROL.search(value):
        raise LocalValidationError(f"{field} 包含非法控制字符")
    try:
        value.encode("utf-16-le")
    except UnicodeEncodeError:
        raise LocalValidationError(f"{field} 包含无效的 Unicode 字符") from None


def utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _slice_utf16(value: str, start: int, end: int) -> str:
    try:
        raw = value.encode("utf-16-le")
    except UnicodeEncodeError:
        raise LocalValidationError("文字包含无效的 Unicode 字符") from None
    if start < 0 or end < start or end * 2 > len(raw):
        raise LocalValidationError("选区超出当前文字范围")
    try:
        # Decoding both boundaries rejects a split surrogate pair.
        raw[: start * 2].decode("utf-16-le")
        return raw[start * 2 : end * 2].decode("utf-16-le")
    except UnicodeDecodeError:
        raise LocalValidationError("选区不能截断字符") from None


def _is_utf16_boundary(value: str, offset: int) -> bool:
    try:
        raw = value.encode("utf-16-le")
    except UnicodeEncodeError:
        return False
    if offset < 0 or offset * 2 > len(raw):
        return False
    try:
        raw[: offset * 2].decode("utf-16-le")
        return True
    except UnicodeDecodeError:
        return False


def _validate_selection(
    field_text: str, selection: object
) -> dict[str, Any]:
    if not isinstance(selection, Mapping) or set(selection) != _SELECTION_KEYS:
        raise LocalValidationError("selection 字段不合法")
    start = selection.get("start")
    end = selection.get("end")
    text = selection.get("text")
    if (
        isinstance(start, bool)
        or not isinstance(start, int)
        or isinstance(end, bool)
        or not isinstance(end, int)
        or not isinstance(text, str)
    ):
        raise LocalValidationError("selection 类型不合法")
    units = utf16_length(field_text)
    if start < 0 or end < start or end > units:
        raise LocalValidationError("选区超出当前文字范围")
    if end - start > contracts.MAX_SELECTION_UNITS:
        raise LocalValidationError("选区超过长度上限")
    if field_text == "":
        if start != 0 or end != 0 or text != "":
            raise LocalValidationError("空栏只能选择 0..0")
    elif end <= start:
        raise LocalValidationError("非空栏必须选择实际文字")
    if _slice_utf16(field_text, start, end) != text:
        raise LocalValidationError("选区原文与当前文字不一致")
    return {"start": start, "end": end, "text": text}


def _optional_text(value: object, field: str, maximum: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise LocalValidationError(f"{field} 必须是字符串")
    text = value.strip()
    if not text:
        return None
    if len(text) > maximum:
        raise LocalValidationError(f"{field} 超过长度上限")
    return text


def _weekly_field_shape(field: str) -> bool:
    return bool(
        field == contracts.WEEKLY_COLUMN_FIELD
        or _ITEM_FIELD.fullmatch(field)
        or _SLOT_FIELD.fullmatch(field)
        or _FOCUS_FIELD.fullmatch(field)
    )


def normalize_request(
    *,
    scope: object,
    field_text: object,
    selection: object,
    instruction: object,
) -> dict[str, Any]:
    if not isinstance(scope, Mapping):
        raise LocalValidationError("scope 必须是对象")
    if set(scope) - _SCOPE_KEYS:
        raise LocalValidationError("scope 字段不合法")
    if not {"kind", "record_id", "version", "field"}.issubset(scope):
        raise LocalValidationError("scope 缺少必要字段")
    kind = scope.get("kind")
    if kind not in (
        "listening_record",
        "listening_candidate",
        "weekly_candidate",
    ):
        raise LocalValidationError("scope.kind 不合法")
    record_id = _optional_text(scope.get("record_id"), "record_id", 64)
    if record_id is None:
        raise LocalValidationError("record_id 不能为空")
    version = scope.get("version")
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version < 1
    ):
        raise LocalValidationError("version 必须是正整数")
    field = _optional_text(scope.get("field"), "field", 80)
    if field is None:
        raise LocalValidationError("field 不能为空")
    candidate_id = _optional_text(scope.get("candidate_id"), "candidate_id", 64)
    task_id = _optional_text(scope.get("task_id"), "task_id", 64)
    domain = _optional_text(scope.get("domain"), "domain", 20)
    group_id = _optional_text(scope.get("group_id"), "group_id", 64)

    if not isinstance(field_text, str):
        raise LocalValidationError("field_text 必须是字符串")
    if len(field_text) > contracts.MAX_FIELD_TEXT:
        raise LocalValidationError("field_text 超过长度上限")
    _ensure_unicode(field_text, "field_text")
    if "[[KGM" in field_text:
        raise LocalValidationError("文字包含保留占位符，无法安全投影")
    selected = _validate_selection(field_text, selection)

    if not isinstance(instruction, str):
        raise LocalValidationError("instruction 必须是字符串")
    instruction_text = instruction.strip()
    if not instruction_text:
        raise LocalValidationError("instruction 不能为空")
    if len(instruction_text) > contracts.MAX_INSTRUCTION:
        raise LocalValidationError("instruction 超过长度上限")
    _ensure_unicode(instruction_text, "instruction")
    if "[[KGM" in instruction_text:
        raise LocalValidationError("意见包含保留占位符，无法安全投影")

    if kind.startswith("listening"):
        if field not in contracts.LISTENING_FIELDS:
            raise LocalValidationError("倾听字段不合法")
        if domain not in listening_service.DOMAINS:
            raise LocalValidationError("domain 不合法")
        if field == "listening_text":
            if group_id is None:
                raise LocalValidationError("倾听正文必须指定 group_id")
        elif group_id is not None:
            raise LocalValidationError("该倾听字段不接受 group_id")
        if kind == "listening_record" and (
            candidate_id is not None or task_id is not None
        ):
            raise LocalValidationError("已保存倾听记录不接受候选或任务标识")
        if kind == "listening_candidate" and (
            candidate_id is None and task_id is None
        ):
            raise LocalValidationError("倾听候选必须指定 candidate_id 或 task_id")
    else:
        if domain is not None or group_id is not None:
            raise LocalValidationError("周计划候选不接受 domain 或 group_id")
        if candidate_id is None:
            raise LocalValidationError("周计划候选必须指定 candidate_id")
        if task_id is not None:
            raise LocalValidationError("周计划候选不接受 task_id")
        if not _weekly_field_shape(field):
            raise LocalValidationError("周计划字段不合法")

    return {
        "scope": {
            "kind": kind,
            "record_id": record_id,
            "version": version,
            "candidate_id": candidate_id,
            "task_id": task_id,
            "domain": domain,
            "group_id": group_id,
            "field": field,
        },
        "field_text": field_text,
        "selection": selected,
        "instruction": instruction_text,
    }


def _sensitive_values(
    context: Any,
    *,
    record_dto: Mapping[str, Any] | None = None,
    identifiers: Sequence[str | None] = (),
) -> list[str]:
    values: list[str] = []

    def add(value: object) -> None:
        if isinstance(value, str) and value.strip():
            values.append(value.strip())

    if context.profile is not None:
        add(context.profile.display_name)
    if context.settings is not None:
        add(context.settings.school_name)
    if context.school_class is not None:
        add(context.school_class.name)
        for name in context.school_class.header_teacher_names or ():
            add(name)
        add(context.school_class.caregiver_name)
    add(context.as_of_date.isoformat())
    for term in context.terms:
        add(term.start_date.isoformat())
        add(term.end_date.isoformat())
    if record_dto is not None:
        add(record_dto.get("child_name"))
    for value in identifiers:
        add(value)
    return values


def _find_spans(
    text: str, sensitive: Sequence[str]
) -> list[tuple[int, int, str]]:
    """Sensitive spans in UTF-16 offsets, merged when they overlap."""
    for value in sensitive:
        _ensure_unicode(value, "身份信息")
    raw: list[tuple[int, int]] = []

    def add_py_span(start: int, end: int) -> None:
        if end <= start:
            return
        raw.append(
            (
                utf16_length(text[:start]),
                utf16_length(text[:end]),
            )
        )

    for value in {item for item in sensitive if item}:
        position = 0
        while True:
            found = text.find(value, position)
            if found < 0:
                break
            add_py_span(found, found + len(value))
            position = found + len(value)
    for match in _DATE.finditer(text):
        add_py_span(match.start(), match.end())
    for match in _SIGNATURE.finditer(text):
        add_py_span(match.start("value"), match.end("value"))
    if not raw:
        return []
    raw.sort()
    merged: list[tuple[int, int, str]] = []
    for start, end in raw:
        if merged and start < merged[-1][1]:
            old_start, old_end, _value = merged[-1]
            merged[-1] = (
                old_start,
                max(old_end, end),
                _slice_utf16(text, old_start, max(old_end, end)),
            )
        else:
            merged.append((start, end, _slice_utf16(text, start, end)))
    return merged


def _token_factory(reserved: str):
    tokens: dict[str, str] = {}
    used: set[str] = set()
    mapping: list[list[str]] = []
    next_index = 1

    def token_for(value: str) -> str:
        nonlocal next_index
        if value in tokens:
            return tokens[value]
        while True:
            token = f"[[KGM{next_index}]]"
            next_index += 1
            if token not in reserved and token not in used:
                break
        used.add(token)
        tokens[value] = token
        mapping.append([token, value])
        return token

    return token_for, mapping


def _crosses_spans(
    spans: Sequence[tuple[int, int, str]], start: int, end: int
) -> bool:
    return any(
        span_start < start < span_end or span_start < end < span_end
        for span_start, span_end, _value in spans
    )


def _redact_range(
    text: str,
    spans: Sequence[tuple[int, int, str]],
    start: int,
    end: int,
    token_for,
) -> str:
    if start >= end:
        return ""
    parts: list[str] = []
    cursor = start
    for span_start, span_end, value in spans:
        if span_end <= start or span_start >= end:
            continue
        if span_start < start or span_end > end:
            # Only a partial span can reach here when a selection or context
            # boundary cuts through a name/date/signature.  Never emit a
            # fragment that could be recombined into the original value.
            raise LocalValidationError("选区或邻文截断身份信息")
        if span_start > cursor:
            parts.append(_slice_utf16(text, cursor, span_start))
        parts.append(token_for(value))
        cursor = span_end
    if cursor < end:
        parts.append(_slice_utf16(text, cursor, end))
    return "".join(parts)


def _context_before(
    text: str,
    end: int,
    limit: int,
    spans: Sequence[tuple[int, int, str]],
    token_for,
) -> str:
    start = max(0, end - limit)
    changed = True
    while changed:
        changed = False
        for span_start, span_end, _value in spans:
            if span_start < start < span_end:
                start = span_end
                changed = True
        if start < end and not _is_utf16_boundary(text, start):
            # A fixed 160-unit window can fall inside an astral character;
            # move inward to the next legal code-point boundary.
            start += 1
            changed = True
    if start >= end:
        return ""
    return _redact_range(text, spans, start, end, token_for)


def _context_after(
    text: str,
    start: int,
    limit: int,
    spans: Sequence[tuple[int, int, str]],
    token_for,
) -> str:
    end = min(utf16_length(text), start + limit)
    changed = True
    while changed:
        changed = False
        for span_start, span_end, _value in spans:
            if span_start < end < span_end:
                end = span_start
                changed = True
        if end > start and not _is_utf16_boundary(text, end):
            end -= 1
            changed = True
    if end <= start:
        return ""
    return _redact_range(text, spans, start, end, token_for)


def _redact_field(
    field_text: str,
    selection: Mapping[str, Any],
    instruction: str,
    sensitive: Sequence[str],
) -> tuple[list[str], list[list[str]]]:
    start = int(selection["start"])
    end = int(selection["end"])
    spans = _find_spans(field_text, sensitive)
    if _crosses_spans(spans, start, end):
        raise LocalValidationError("选区穿过姓名、日期或署名，请调整选区")
    token_for, mapping = _token_factory(field_text + instruction)
    selected = _redact_range(field_text, spans, start, end, token_for)
    before = _context_before(field_text, start, MAX_CONTEXT_UNITS, spans, token_for)
    after = _context_after(field_text, end, MAX_CONTEXT_UNITS, spans, token_for)
    instruction_spans = _find_spans(instruction, sensitive)
    instruction_redacted = _redact_range(
        instruction,
        instruction_spans,
        0,
        utf16_length(instruction),
        token_for,
    )
    return [selected, before, after, instruction_redacted], mapping


def _restore(text: str, mapping: Sequence[Sequence[str]]) -> str:
    for pair in mapping:
        token, value = pair
        text = text.replace(str(token), str(value))
    if "[[KGM" in text:
        raise CandidateInvalid("候选包含未知占位符")
    try:
        text.encode("utf-16-le")
    except UnicodeEncodeError:
        raise CandidateInvalid("候选包含无效的 Unicode 字符") from None
    return text


def _splice_utf16(
    value: str, start: int, end: int, replacement: str
) -> str:
    try:
        raw = value.encode("utf-16-le")
        before = raw[: start * 2].decode("utf-16-le")
        after = raw[end * 2 :].decode("utf-16-le")
    except (UnicodeEncodeError, UnicodeDecodeError):
        raise CandidateInvalid("候选拼接字段包含无效的 Unicode 字符") from None
    return before + replacement + after


def _validate_full_field(target: str, field: str, value: str) -> None:
    """Apply the existing saved-field limits before the teacher sees a patch."""
    if target == "listening_text":
        maximum, nonempty, strip = contracts.MAX_LISTENING_TEXT, False, True
    elif target == "goal":
        maximum, nonempty, strip = contracts.MAX_LISTENING_GOAL, False, True
    elif target in ("overall_evaluation", "support_strategy"):
        maximum, nonempty, strip = contracts.MAX_LISTENING_TEXT, False, True
    elif target == "weekly_column":
        maximum, nonempty, strip = (
            weekly_ai_contracts.MAX_AI_TEXT_CHARS,
            True,
            False,
        )
    elif target == "weekly_material":
        maximum, nonempty, strip = (
            weekly_ai_contracts.MAX_MATERIAL_ITEM_TEXT,
            True,
            False,
        )
    elif target == "weekly_game":
        if field == "focus.name" or (
            field.startswith("slot.") and field.endswith(".name")
        ):
            maximum, nonempty, strip = (
                weekly_ai_contracts.MAX_NAME_CHARS,
                True,
                False,
            )
        else:
            maximum, nonempty, strip = (
                weekly_ai_contracts.MAX_AI_TEXT_CHARS,
                False,
                False,
            )
    else:
        raise CandidateInvalid("候选目标不合法")
    checked = value.strip() if strip else value
    if len(checked) > maximum:
        raise CandidateInvalid("候选拼接后的字段超过原有长度上限")
    if nonempty and not value.strip():
        raise CandidateInvalid("候选拼接后的必填字段不能为空")


def _domain(dto: Mapping[str, Any], domain: str) -> dict[str, Any]:
    item = next(
        (row for row in dto.get("domains") or [] if row.get("domain") == domain),
        None,
    )
    if item is None:
        raise LocalStorageError("倾听领域缺失")
    return item


def _saved_listening_field(
    dto: Mapping[str, Any], domain: str, group_id: str | None, field: str
) -> tuple[str, dict[str, Any] | None]:
    domain_dto = _domain(dto, domain)
    if field != "listening_text":
        return str(domain_dto.get(field) or ""), None
    group = next(
        (
            item
            for item in domain_dto.get("groups") or []
            if item.get("group_id") == group_id
        ),
        None,
    )
    if group is None:
        raise LocalAiNotFound("未找到该倾听图文组")
    return str(group.get("listening_text") or ""), group


def _candidate_field(task_type: str, field: str) -> bool:
    if task_type in (
        listening_ai_contracts.TASK_NOTE,
        listening_ai_contracts.TASK_GROUP,
    ):
        return field == "listening_text"
    if task_type == listening_ai_contracts.TASK_GOAL:
        return field == "goal"
    if task_type == listening_ai_contracts.TASK_DOMAIN:
        return field in ("overall_evaluation", "support_strategy")
    return False


def _candidate_text(
    raw: Mapping[str, Any],
    task_type: str,
    field: str,
    *,
    group_position: int | None = None,
) -> str:
    if task_type == listening_ai_contracts.TASK_NOTE:
        return str(raw.get("text") or "")
    if task_type == listening_ai_contracts.TASK_GOAL:
        return str(raw.get("goal") or "")
    if task_type == listening_ai_contracts.TASK_DOMAIN:
        return str(raw.get(field) or "")
    if task_type == listening_ai_contracts.TASK_GROUP:
        if group_position is None:
            raise LocalStorageError("倾听图文组位置缺失")
        group = next(
            (
                item
                for item in raw.get("groups") or []
                if int(item.get("position")) == group_position
            ),
            None,
        )
        if group is None:
            raise LocalStorageError("倾听候选图文组缺失")
        return str(group.get("text") or "")
    raise LocalStorageError("倾听候选类型未知")


def _listening_candidate(
    session: Session,
    *,
    profile_id: str,
    record_id: str,
    domain: str,
    group_id: str | None,
    field: str,
    candidate_id: str | None,
    task_id: str | None,
    saved_text: str,
    saved_position: int | None,
    dto: Mapping[str, Any],
) -> tuple[
    LocalAICandidate,
    LocalAITask,
    LocalAIInput,
    str,
    str,
]:
    candidate: LocalAICandidate | None = None
    if candidate_id is not None:
        candidate = session.get(LocalAICandidate, candidate_id)
        if (
            candidate is None
            or candidate.profile_id != profile_id
            or candidate.source_kind != listening_ai_service.SOURCE_KIND
            or candidate.listening_record_id != record_id
        ):
            raise LocalAiNotFound("未找到该倾听 AI 候选")
        if task_id is not None and candidate.task_id != task_id:
            raise LocalAiNotFound("倾听候选与任务不一致")
    else:
        if task_id is None:
            raise LocalValidationError("倾听候选必须指定 candidate_id 或 task_id")
        task = ai_task_service.require_task(
            session,
            task_id,
            source_kind=listening_ai_service.SOURCE_KIND,
            source_id=record_id,
        )
        if (
            task.profile_id != profile_id
            or task.listening_record_id != record_id
            or task.status != "succeeded"
            or task.current_execution_id is None
        ):
            raise LocalAiNotFound("该倾听 AI 任务尚无候选")
        candidate = session.scalars(
            select(LocalAICandidate).where(
                LocalAICandidate.profile_id == profile_id,
                LocalAICandidate.source_kind == listening_ai_service.SOURCE_KIND,
                LocalAICandidate.source_id == record_id,
                LocalAICandidate.task_id == task.id,
                LocalAICandidate.execution_id == task.current_execution_id,
            )
        ).first()
        if candidate is None:
            raise LocalAiNotFound("该倾听 AI 任务尚无候选")
    candidate, task, inp, _execution = listening_ai_service.require_candidate_chain(
        session,
        profile_id=profile_id,
        record_id=record_id,
        candidate_id=candidate.id,
    )
    if candidate.listening_domain != domain or not _candidate_field(
        candidate.task_type, field
    ):
        raise LocalValidationError("倾听候选与本次领域或字段不一致")
    group_position: int | None = None
    if candidate.task_type == listening_ai_contracts.TASK_NOTE:
        if candidate.listening_group_id != group_id:
            raise LocalValidationError("倾听候选与本次图文组不一致")
        group_position = saved_position
        target_key = "listening_text"
    elif candidate.task_type == listening_ai_contracts.TASK_GROUP:
        if saved_position is None:
            raise LocalAiNotFound("未找到该倾听图文组")
        group_position = saved_position
        target_key = listening_ai_contracts.group_note_target_key(
            domain, group_position
        )
    elif group_id is not None:
        raise LocalValidationError("该倾听候选不接受 group_id")
    else:
        target_key = field
    if not listening_ai_inputs.revalidate_source(session, task):
        raise LocalVersionConflict(details={"reason": "candidate_source_changed"})
    target_hashes = dict(inp.target_hashes_json or {})
    expected = target_hashes.get(target_key)
    if expected != listening_ai_contracts.value_hash(saved_text.strip()):
        raise LocalValidationError("候选目标已被修改，请重新生成")
    adopted = session.scalars(
        select(LocalListeningAIAdoption).where(
            LocalListeningAIAdoption.candidate_id == candidate.id,
            LocalListeningAIAdoption.input_id == inp.id,
            LocalListeningAIAdoption.target_key == target_key,
        )
    ).first()
    if adopted is not None:
        raise LocalValidationError("该候选目标已经采用")
    text_value = _candidate_text(
        dict(candidate.raw_candidate_json or {}),
        candidate.task_type,
        field,
        group_position=group_position,
    )
    return candidate, task, inp, text_value, target_key


def _weekly_content(
    session: Session, plan: LocalWeeklyPlan
) -> LocalWeeklyPlanContent:
    content = session.get(
        LocalWeeklyPlanContent, plan.current_draft_id, populate_existing=True
    )
    if (
        content is None
        or content.weekly_plan_id != plan.id
        or content.version != plan.current_draft_version
    ):
        raise LocalStorageError("周计划草稿指针不一致")
    return content


def _weekly_candidate(
    session: Session,
    *,
    profile_id: str,
    plan_id: str,
    candidate_id: str,
    version: int,
    field: str,
) -> tuple[
    LocalAICandidate,
    LocalAIInput,
    LocalWeeklyPlan,
    LocalWeeklyPlanContent,
    str,
    str,
    dict[str, Any],
]:
    plan = session.get(LocalWeeklyPlan, plan_id, populate_existing=True)
    if plan is None or plan.profile_id != profile_id:
        raise LocalAiNotFound("未找到该周计划")
    content = _weekly_content(session, plan)
    if content.version != version:
        raise LocalVersionConflict(details={"draft_version": content.version})
    candidate = session.get(LocalAICandidate, candidate_id)
    if (
        candidate is None
        or candidate.profile_id != profile_id
        or candidate.source_kind != "weekly_plan"
        or candidate.weekly_plan_id != plan.id
    ):
        raise LocalAiNotFound("未找到该周计划 AI 候选")
    raw, _execution, inp = weekly_ai_candidates.require_chain(
        session, plan=plan, candidate=candidate
    )
    if (
        weekly_ai_candidates.eligibility(
            session,
            plan=plan,
            content=content,
            candidate=candidate,
            input_row=inp,
        )
        != "eligible"
    ):
        raise LocalVersionConflict(details={"reason": "candidate_source_changed"})
    target = weekly_ai_candidates.TARGETS[candidate.task_type]
    text_value, metadata = _weekly_field_value(raw, target, field)
    return candidate, inp, plan, content, target, text_value, metadata


def _weekly_field_value(
    raw: Mapping[str, Any], target: str, field: str
) -> tuple[str, dict[str, Any]]:
    if target in weekly_ai_contracts.COLUMN_FIELDS:
        if field != contracts.WEEKLY_COLUMN_FIELD:
            raise LocalValidationError("周栏目候选字段不合法")
        return str(raw.get("text") or ""), {}
    if target == "materials":
        match = _ITEM_FIELD.fullmatch(field)
        if match is None:
            raise LocalValidationError("材料候选字段不合法")
        items = raw.get("items")
        index = int(match.group(1))
        if not isinstance(items, list) or index >= len(items):
            raise LocalValidationError("材料候选条目不存在")
        item = items[index]
        if not isinstance(item, Mapping):
            raise LocalStorageError("材料候选条目损坏")
        return str(item.get("text") or ""), {
            "origin": item.get("origin"),
            "item_index": index,
        }
    if target != "games":
        raise LocalStorageError("周计划候选目标未知")
    slot_match = _SLOT_FIELD.fullmatch(field)
    if slot_match is not None:
        slot, name = slot_match.groups()
        if name not in contracts.WEEKLY_GAME_SLOT_FIELDS[slot]:
            raise LocalValidationError("周游戏字段不合法")
        item = (raw.get("outdoor_game_slots") or {}).get(slot)
        if not isinstance(item, Mapping):
            raise LocalValidationError("周游戏槽位没有可修改内容")
        return str(item.get(name) or ""), {
            "source_kind": item.get("source_kind"),
            "slot": slot,
            "field": name,
        }
    focus_match = _FOCUS_FIELD.fullmatch(field)
    if focus_match is not None:
        name = focus_match.group(1)
        if name not in contracts.WEEKLY_FOCUS_FIELDS:
            raise LocalValidationError("周游戏重点区域字段不合法")
        item = raw.get("focus_area")
        if not isinstance(item, Mapping):
            raise LocalValidationError("周游戏重点区域没有可修改内容")
        return str(item.get(name) or ""), {
            "source_kind": item.get("source_kind"),
            "slot": "focus_area",
            "field": name,
        }
    raise LocalValidationError("周游戏字段不合法")


def project_create(
    session: Session,
    *,
    profile_id: str,
    request: Mapping[str, Any],
) -> Projection:
    """Build one de-identified model input and the local source baseline."""
    scope = dict(request["scope"])
    kind = str(scope["kind"])
    field = str(scope["field"])
    field_text = str(request["field_text"])
    selection = dict(request["selection"])
    instruction = str(request["instruction"])
    version = int(scope["version"])
    context = profile_service.require_context(session, date.today())
    if context.profile is None or context.profile.id != profile_id:
        raise LocalStorageError("本地档案上下文不一致")

    candidate_id: str | None = None
    candidate_hash: str | None = None
    candidate_task_id: str | None = None
    candidate_input_id: str | None = None
    candidate_source_revision: int | None = None
    candidate_source_draft_id: str | None = None
    saved_text = ""
    candidate_text = ""
    source_identity: dict[str, Any] = {}
    draft_id: str | None = None
    draft_content_hash: str | None = None
    listening_record_id: str | None = None
    listening_domain: str | None = None
    listening_group_id: str | None = None
    weekly_plan_id: str | None = None
    record_dto: Mapping[str, Any] | None = None

    if kind == "listening_record":
        listening_record_id = str(scope["record_id"])
        listening_domain = str(scope["domain"])
        listening_group_id = scope["group_id"]
        record_dto = listening_service.read_record_no_tx(
            session, profile_id=profile_id, record_id=listening_record_id
        )
        if int(record_dto["revision"]) != version:
            raise LocalVersionConflict(
                details={"current_revision": int(record_dto["revision"])}
            )
        saved_text, _group = _saved_listening_field(
            record_dto, listening_domain, listening_group_id, field
        )
    elif kind == "listening_candidate":
        listening_record_id = str(scope["record_id"])
        listening_domain = str(scope["domain"])
        listening_group_id = scope["group_id"]
        record_dto = listening_service.read_record_no_tx(
            session, profile_id=profile_id, record_id=listening_record_id
        )
        if int(record_dto["revision"]) != version:
            raise LocalVersionConflict(
                details={"current_revision": int(record_dto["revision"])}
            )
        saved_text, saved_group = _saved_listening_field(
            record_dto, listening_domain, listening_group_id, field
        )
        candidate, _task, inp, candidate_text, target_key = _listening_candidate(
            session,
            profile_id=profile_id,
            record_id=listening_record_id,
            domain=listening_domain,
            group_id=listening_group_id,
            field=field,
            candidate_id=scope["candidate_id"],
            task_id=scope["task_id"],
            saved_text=saved_text,
            saved_position=(
                int(saved_group["position"]) if saved_group is not None else None
            ),
            dto=record_dto,
        )
        candidate_id = candidate.id
        candidate_hash = candidate.candidate_hash
        candidate_task_id = candidate.task_id
        candidate_input_id = inp.id
        candidate_source_revision = inp.source_revision
        source_identity["candidate_target_key"] = target_key
    elif kind == "weekly_candidate":
        weekly_plan_id = str(scope["record_id"])
        candidate, inp, plan, content, target, candidate_text, metadata = (
            _weekly_candidate(
                session,
                profile_id=profile_id,
                plan_id=weekly_plan_id,
                candidate_id=str(scope["candidate_id"]),
                version=version,
                field=field,
            )
        )
        if target in weekly_ai_contracts.COLUMN_FIELDS:
            field_target = "weekly_column"
        elif target == "materials":
            field_target = "weekly_material"
        else:
            field_target = "weekly_game"
        candidate_id = candidate.id
        candidate_hash = candidate.candidate_hash
        candidate_task_id = candidate.task_id
        candidate_input_id = inp.id
        candidate_source_revision = inp.source_revision
        candidate_source_draft_id = inp.weekly_draft_id
        saved_text = candidate_text
        draft_id = content.id
        draft_content_hash = content.content_hash
        source_identity = dict(metadata)
    else:  # pragma: no cover - normalize_request already rejects
        raise LocalValidationError("scope.kind 不合法")

    if kind.startswith("listening"):
        target = field
    else:
        target = field_target

    selected_text = str(selection["text"])
    sensitive = _sensitive_values(
        context,
        record_dto=record_dto,
        identifiers=(
            scope["record_id"],
            scope["group_id"],
            scope["candidate_id"],
            scope["task_id"],
            candidate_id,
            candidate_task_id,
            candidate_input_id,
            weekly_plan_id,
            draft_id,
        ),
    )
    redacted, redactions = _redact_field(
        field_text, selection, instruction, sensitive
    )
    payload = {
        "schema_version": contracts.INPUT_SCHEMA_VERSION,
        "source": "listening" if kind.startswith("listening") else "weekly",
        "target": target,
        "target_label": contracts.TARGET_LABELS[target],
        "selected_text": redacted[0],
        "context_before": redacted[1],
        "context_after": redacted[2],
        "instruction": redacted[3],
    }
    dependencies = {
        "schema_version": contracts.INPUT_SCHEMA_VERSION,
        "source": payload["source"],
        "scope_kind": kind,
        "record_id": str(scope["record_id"]),
        "version": version,
        "domain": scope["domain"],
        "group_id": scope["group_id"],
        "field": field,
        "candidate_id": candidate_id,
        "candidate_hash": candidate_hash,
        "candidate_task_id": candidate_task_id,
        "candidate_input_id": candidate_input_id,
        "candidate_source_revision": candidate_source_revision,
        "candidate_source_draft_id": candidate_source_draft_id,
        "weekly_draft_id": draft_id,
        "draft_content_hash": draft_content_hash,
        "field_text": field_text,
        "saved_text": saved_text,
        "candidate_text": candidate_text,
        "selection": selection,
        "instruction": instruction,
        "target": target,
        "target_label": contracts.TARGET_LABELS[target],
        "source_identity": source_identity,
        "redactions": redactions,
    }
    target_hashes = {
        "field_text": _digest(field_text),
        "selection_text": _digest(selected_text),
        "saved_text": _digest(saved_text),
        "candidate": candidate_hash or _digest(""),
    }
    return Projection(
        task_type=TASK_TYPE,
        payload=payload,
        dependencies=dependencies,
        dependency_hash=_digest(dependencies),
        target_hashes=target_hashes,
        source_revision=version,
        listening_record_id=listening_record_id,
        listening_domain=listening_domain,
        listening_group_id=listening_group_id,
        weekly_plan_id=weekly_plan_id,
        weekly_draft_id=draft_id,
    )


def _notice(target: str, source_identity: Mapping[str, Any]) -> str:
    if target == "listening_text":
        return "AI 建议：请对照幼儿原话与照片证据核对。"
    if target == "goal":
        return "AI 建议：请核对已保存的观察目标与证据。"
    if target == "overall_evaluation":
        return "AI 建议：请核对评价依据；评价星级仍按现有条目逐项确认。"
    if target == "support_strategy":
        return "AI 建议：请核对支持策略与已保存证据。"
    if target == "weekly_column":
        return "AI 建议：请核对本周来源。"
    if target == "weekly_game":
        if source_identity.get("source_kind") == "ai_supplement":
            return "AI 建议；请核对游戏内容，原候选来源标记不变。"
        return (
            "AI 建议，不是原引用；原游戏来源和版本保持不变，"
            "预览仍以候选卡原来源为准。"
        )
    if target == "weekly_material":
        if source_identity.get("origin") == "extracted":
            return (
                "AI 建议；改写后不再作为原提取证据，已标为建议；"
                "其他材料项证据保持不变。"
            )
        return "AI 建议；其他材料项证据保持不变。"
    return "AI 建议：请核对后采用。"


def validate_candidate(candidate: Any, input_row: LocalAIInput) -> dict[str, Any]:
    if not isinstance(candidate, Mapping):
        raise CandidateInvalid("候选必须是对象")
    if set(candidate) != {"status", "replacement", "question"}:
        raise CandidateInvalid("候选字段不合法")
    status = candidate.get("status")
    replacement = candidate.get("replacement")
    question = candidate.get("question")
    if status not in ("proposed", "clarify", "no_change"):
        raise CandidateInvalid("候选状态不合法")
    if not isinstance(question, str):
        raise CandidateInvalid("候选问题必须是字符串")
    if len(question) > contracts.MAX_QUESTION:
        raise CandidateInvalid("候选问题超过长度上限")
    deps = dict(input_row.dependencies_json or {})
    mapping = list(deps.get("redactions") or [])
    question = _restore(question, mapping)
    if status == "proposed":
        if not isinstance(replacement, str):
            raise CandidateInvalid("proposed 必须提供 replacement")
        if len(replacement) > contracts.MAX_REPLACEMENT:
            raise CandidateInvalid("replacement 超过长度上限")
        replacement = _restore(replacement, mapping)
        if _CONTROL.search(replacement):
            raise CandidateInvalid("replacement 包含非法控制字符")
        if replacement == str((deps.get("selection") or {}).get("text") or ""):
            raise CandidateInvalid("候选没有产生修改")
        target = str(deps.get("target") or "")
        if target in ("weekly_game", "weekly_material") and _SOURCE_CLAIMS.search(
            replacement
        ):
            raise CandidateInvalid("候选不得声称改写内容与原证据匹配")
        field_text = deps.get("field_text")
        selection = deps.get("selection")
        if not isinstance(field_text, str) or not isinstance(selection, Mapping):
            raise CandidateInvalid("候选缺少原字段基准")
        try:
            full_value = _splice_utf16(
                field_text,
                int(selection["start"]),
                int(selection["end"]),
                replacement,
            )
        except (KeyError, TypeError, ValueError):
            raise CandidateInvalid("候选原字段基准无效") from None
        _validate_full_field(
            target, str(deps.get("field") or ""), full_value
        )
        notice = _notice(target, dict(deps.get("source_identity") or {}))
    else:
        if replacement is not None:
            raise CandidateInvalid("非 proposed 不得提供 replacement")
        if status == "clarify" and not question.strip():
            raise CandidateInvalid("clarify 必须给出确认问题")
        notice = ""
    return {
        "status": status,
        "replacement": replacement,
        "question": question,
        "notice": notice,
    }


def _candidate_for_task(
    session: Session, task: LocalAITask
) -> dict[str, Any] | None:
    if task.status != "succeeded":
        return None
    query = select(LocalAICandidate).where(
        LocalAICandidate.profile_id == task.profile_id,
        LocalAICandidate.source_kind == SOURCE_KIND,
        LocalAICandidate.task_id == task.id,
    )
    if task.current_execution_id is not None:
        query = query.where(
            LocalAICandidate.execution_id == task.current_execution_id
        )
    candidate = session.scalars(
        query.order_by(LocalAICandidate.created_at.desc())
    ).first()
    if candidate is None:
        return None
    raw = dict(candidate.raw_candidate_json or {})
    if (
        raw.get("status") not in ("proposed", "clarify", "no_change")
        or not isinstance(raw.get("question"), str)
        or not isinstance(raw.get("notice"), str)
        or (
            raw.get("status") == "proposed"
            and not isinstance(raw.get("replacement"), str)
        )
        or (
            raw.get("status") != "proposed"
            and raw.get("replacement") is not None
        )
    ):
        raise LocalStorageError("定向修改候选损坏")
    return {
        "status": raw["status"],
        "replacement": raw.get("replacement"),
        "question": raw["question"],
        "notice": raw["notice"],
    }


def task_payload(session: Session, task: LocalAITask) -> dict[str, Any]:
    return {
        "id": task.id,
        "status": task.status,
        "reason": task.reason,
        "candidate": _candidate_for_task(session, task),
    }


def revalidate_source(session: Session, task: LocalAITask) -> bool:
    inp = session.get(LocalAIInput, task.input_id)
    if (
        inp is None
        or inp.profile_id != task.profile_id
        or inp.source_kind != SOURCE_KIND
        or inp.source_id != task.source_id
        or inp.task_type != TASK_TYPE
    ):
        return False
    deps = dict(inp.dependencies_json or {})
    if deps.get("schema_version") != contracts.INPUT_SCHEMA_VERSION:
        return False
    try:
        if deps.get("source") == "listening":
            dto = listening_service.read_record_no_tx(
                session,
                profile_id=task.profile_id,
                record_id=str(deps["record_id"]),
            )
            if int(dto["revision"]) != int(inp.source_revision or 0):
                return False
            saved, _group = _saved_listening_field(
                dto,
                str(deps["domain"]),
                deps.get("group_id"),
                str(deps["field"]),
            )
            if saved != str(deps.get("saved_text") or ""):
                return False
            if deps.get("scope_kind") == "listening_candidate":
                candidate = session.get(
                    LocalAICandidate, str(deps.get("candidate_id"))
                )
                if (
                    candidate is None
                    or candidate.candidate_hash != deps.get("candidate_hash")
                ):
                    return False
                candidate, candidate_task, candidate_input, _execution = (
                    listening_ai_service.require_candidate_chain(
                        session,
                        profile_id=task.profile_id,
                        record_id=str(deps["record_id"]),
                        candidate_id=candidate.id,
                    )
                )
                if (
                    candidate_input.source_revision
                    != deps.get("candidate_source_revision")
                    or not _candidate_field(
                        candidate.task_type, str(deps["field"])
                    )
                    or not listening_ai_inputs.revalidate_source(
                        session, candidate_task
                    )
                ):
                    return False
                target_key = str(
                    dict(deps.get("source_identity") or {}).get(
                        "candidate_target_key", ""
                    )
                )
                expected = dict(candidate_input.target_hashes_json or {}).get(
                    target_key
                )
                if expected is None or expected != listening_ai_contracts.value_hash(
                    saved.strip()
                ):
                    return False
                adopted = session.scalars(
                    select(LocalListeningAIAdoption).where(
                        LocalListeningAIAdoption.candidate_id == candidate.id,
                        LocalListeningAIAdoption.input_id == candidate_input.id,
                        LocalListeningAIAdoption.target_key == target_key,
                    )
                ).first()
                if adopted is not None:
                    return False
            return True
        if deps.get("source") == "weekly":
            plan = session.get(
                LocalWeeklyPlan, str(deps.get("record_id")), populate_existing=True
            )
            if plan is None or plan.profile_id != task.profile_id:
                return False
            content = session.get(
                LocalWeeklyPlanContent,
                plan.current_draft_id,
                populate_existing=True,
            )
            if (
                content is None
                or content.weekly_plan_id != plan.id
                or content.version != inp.source_revision
                or content.content_hash != deps.get("draft_content_hash")
                or content.id != deps.get("weekly_draft_id")
            ):
                return False
            candidate = session.get(
                LocalAICandidate, str(deps.get("candidate_id"))
            )
            if (
                candidate is None
                or candidate.profile_id != task.profile_id
                or candidate.source_kind != "weekly_plan"
                or candidate.weekly_plan_id != plan.id
                or candidate.candidate_hash != deps.get("candidate_hash")
            ):
                return False
            _raw, _execution, candidate_input = weekly_ai_candidates.require_chain(
                session, plan=plan, candidate=candidate
            )
            if (
                candidate_input.source_revision
                != deps.get("candidate_source_revision")
                or candidate_input.weekly_draft_id
                != deps.get("candidate_source_draft_id")
            ):
                return False
            return (
                weekly_ai_candidates.eligibility(
                    session,
                    plan=plan,
                    content=content,
                    candidate=candidate,
                    input_row=candidate_input,
                )
                == "eligible"
            )
    except Exception:  # noqa: BLE001 - any unreadable source is not claimable
        return False
    return False


def preflight_size(session: Session, projected: Projection) -> None:
    with read_scope(session):
        state, config, _credential = ai_config_service._read_config(session)
        if state is None or config is None:
            raise LocalAiNotConfigured()
        head, version = ai_task_service._current_prompt(
            session, state.profile_id, TASK_TYPE
        )
        if version is None:
            raise LocalStorageError("个人指导缺失")
        bundle = session.get(
            LocalPromptBundle,
            (TASK_TYPE, version.contract_version, version.based_default_revision),
        )
        if bundle is None:
            raise LocalStorageError("提示词包缺失")
        guidance = dict(version.guidance_json or {})
        output_schema = dict(bundle.output_schema_json or {})
    size = ai_task_service.serialized_request_bytes(
        task_type=TASK_TYPE,
        contract_version=version.contract_version,
        output_schema=output_schema,
        guidance=guidance,
        payload=projected.payload,
        model=config.model or "",
    )
    if size > ai_transport.REQUEST_MAX_BYTES:
        raise LocalAiInputTooLarge(
            details={
                "serialized_bytes": size,
                "limit": ai_transport.REQUEST_MAX_BYTES,
            }
        )


__all__ = [
    "SOURCE_KIND",
    "TASK_TYPE",
    "Projection",
    "normalize_request",
    "preflight_size",
    "project_create",
    "revalidate_source",
    "task_payload",
    "utf16_length",
    "validate_candidate",
]
