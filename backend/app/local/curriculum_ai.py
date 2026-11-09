"""Curriculum deliberation AI projection, document linkage and validation.

The module owns only the curriculum-specific business boundary.  The shared
task service still owns receipts, credentials, executor claim/finalize,
concurrency and recovery.  Model payloads never include institution, class
display name, organiser, recorder or activity date.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.local import curriculum_ai_contracts as contracts
from app.local import curriculum_content
from app.local.errors import (
    LocalAiInputEmpty,
    LocalAiSourceChanged,
    LocalStorageError,
    LocalValidationError,
)
from app.local.models import (
    LocalAICandidate,
    LocalAIExecution,
    LocalAIInput,
    LocalAITask,
    LocalCurriculumDeliberation,
)
from app.local.prompt_bundles import CandidateInvalid

SOURCE_KIND = "curriculum_deliberation"
_LIST_PREFIX = re.compile(
    r"^\s*(?:[0-9]+(?:[、)]|[.．](?![0-9０-９]))"
    r"|[一二三四五六七八九十百]+(?:、|[.．](?![0-9０-９])))\s*"
)
_HEADER_LINE = re.compile(
    r"^\s*(?:执教|授课教师|指导教师|组织教师|记录人|实施单位|班级|"
    r"活动时间|日期|署名|设计者)\s*[:：]"
)


def _content_signature(value: object) -> str:
    """Whitespace/numbering-normalized signature; punctuation stays content."""
    lines = []
    for line in _clean(value).splitlines():
        line = _LIST_PREFIX.sub("", line.strip())
        chars = [char for char in line if not char.isspace()]
        if chars:
            lines.append("".join(chars))
    return "".join(lines)


@dataclass(frozen=True)
class ProjectedCurriculum:
    task_type: str
    payload: dict[str, Any]
    dependencies: dict[str, Any]
    dependency_hash: str
    target_hashes: dict[str, str]
    source_excerpt: dict[str, Any]
    target_grade: str | None


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _clean(value: object) -> str:
    return curriculum_content.sanitize_export_text(value)


def _nonempty(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise LocalValidationError(f"{label} 必须是字符串")
    text = value.strip()
    if not text:
        raise LocalValidationError(f"{label}不能为空")
    return text


def _record_id(value: object) -> str:
    if not isinstance(value, str):
        raise LocalValidationError("记录 ID 必须是 UUID")
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError):
        raise LocalValidationError("记录 ID 必须是 UUID") from None


def _task_id_or_none(value: object, label: str) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 64
    ):
        raise LocalValidationError(f"{label} 不合法")
    return value


def default_age_group(grade: object) -> str:
    return {
        "small": "小班",
        "middle": "中班",
        "large": "大班",
    }.get(str(grade or ""), "")


def _activity(content: Mapping[str, str], age_group: str) -> dict[str, str]:
    form = content.get("activity_form", "")
    return {
        "name": content.get("activity_name", ""),
        "form": form,
        "form_other": (
            content.get("activity_form_other", "") if form == "other" else ""
        ),
        "child_count": content.get("child_count", ""),
        "age_group": age_group,
    }


def _redactions_from_values(values: Any) -> dict[str, str]:
    unique = []
    for value in sorted(
        {item for item in values if isinstance(item, str) and item.strip()},
        key=len,
        reverse=True,
    ):
        if value not in unique:
            unique.append(value)
    return {f"[[LOCAL{i + 1}]]": value for i, value in enumerate(unique)}


def _header_redactions(content: Mapping[str, str]) -> dict[str, str]:
    values = []
    for field in (
        "organizer",
        "recorder",
        "institution",
        "class_name",
        "activity_date",
    ):
        value = content.get(field, "")
        if not isinstance(value, str) or not value.strip():
            continue
        values.append(value)
        if field == "activity_date":
            values.append(value.replace("-", "."))
    for field in ("lesson_original", "lesson_revised"):
        for line in _clean(content.get(field, "")).splitlines():
            text = line.strip()
            if _HEADER_LINE.match(text):
                values.append(text)
    return _redactions_from_values(values)


def _redact_for_model(value: str, mapping: Mapping[str, str]) -> str:
    text = value
    for token, original in mapping.items():
        text = text.replace(original, token)
    return text


def _restore_tokens(value: str, mapping: Mapping[str, str]) -> str:
    text = value
    for token, original in mapping.items():
        text = text.replace(token, original)
    return text


def _restore_structure(value: Any, mapping: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        return _restore_tokens(value, mapping)
    if isinstance(value, list):
        return [_restore_structure(item, mapping) for item in value]
    if isinstance(value, dict):
        return {
            key: _restore_structure(item, mapping)
            for key, item in value.items()
        }
    return value


def _redact_structure(value: Any, mapping: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        return _redact_for_model(value, mapping)
    if isinstance(value, list):
        return [_redact_structure(item, mapping) for item in value]
    if isinstance(value, dict):
        return {
            key: _redact_structure(item, mapping)
            for key, item in value.items()
        }
    return value


def _python_index(value: str, units: int) -> int:
    return len(value.encode("utf-16-le")[: units * 2].decode("utf-16-le"))


def _source_blocks(
    lesson: str, mapping: Mapping[str, str]
) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    for line in _clean(lesson).splitlines():
        if not curriculum_content.is_substantive(line):
            continue
        blocks.append(
            {
                "source_id": f"s{len(blocks) + 1}",
                "text": _redact_for_model(line, mapping),
            }
        )
    if not blocks:
        raise LocalAiInputEmpty("原始教案为空，无法发起整理任务")
    return blocks


def _normalized_lesson(value: object) -> str:
    return "\n".join(
        line
        for line in _clean(value).splitlines()
        if curriculum_content.is_substantive(line)
    )


def _selection_section(field: str) -> str:
    return contracts.SECTION_FIELD.get(field, "other")


def _validate_selection(
    content: Mapping[str, str], selection: object
) -> dict[str, Any]:
    if selection is None:
        raise LocalValidationError("edit 需要 selection")
    if not isinstance(selection, dict):
        raise LocalValidationError("selection 必须是对象")
    field = selection.get("field")
    if not isinstance(field, str) or field not in contracts.EDITABLE_FIELDS:
        raise LocalValidationError("selection.field 不是可编辑正文栏")
    value = content.get(field, "")
    start = selection.get("start")
    end = selection.get("end")
    text = selection.get("text")
    if (
        isinstance(start, bool)
        or not isinstance(start, int)
        or isinstance(end, bool)
        or not isinstance(end, int)
        or start < 0
        or end < start
        or end > contracts.utf16_length(value)
    ):
        raise LocalValidationError("selection 范围不合法")
    if start == end and value != "":
        raise LocalValidationError("非空正文的选区不能为空")
    if not isinstance(text, str):
        raise LocalValidationError("selection.text 必须是字符串")
    try:
        selected = contracts.utf16_slice(value, start, end)
    except UnicodeDecodeError:
        raise LocalValidationError("selection 范围切断了字符") from None
    if selected != text:
        raise LocalValidationError("selection.text 与当前正文选区不一致")
    if contracts.utf16_length(text) > contracts.MAX_SELECTION_UNITS:
        raise LocalValidationError("selection 超过长度上限")
    return {
        "field": field,
        "start": start,
        "end": end,
        "text": text,
        "section": _selection_section(field),
    }


def _normalize_resolutions(
    split_questions: list[dict[str, Any]], resolutions: object
) -> list[dict[str, str]]:
    if resolutions is None:
        resolutions = []
    if not isinstance(resolutions, list):
        raise LocalValidationError("resolutions 必须是数组")
    expected = {
        question.get("id"): question
        for question in split_questions
        if isinstance(question, dict) and isinstance(question.get("id"), str)
    }
    seen: dict[str, str] = {}
    for item in resolutions:
        if not isinstance(item, dict):
            raise LocalValidationError("resolution 必须是对象")
        question_id = item.get("id")
        section = item.get("section")
        if not isinstance(question_id, str) or question_id not in expected:
            raise LocalValidationError("resolution 引用了未知核对项")
        if question_id in seen:
            raise LocalValidationError("resolution 重复")
        if section not in contracts.SECTIONS:
            raise LocalValidationError("resolution.section 不合法")
        seen[question_id] = section
    if expected:
        if set(seen) != set(expected):
            raise LocalValidationError("拆分归属疑问必须逐项核对")
    elif seen:
        raise LocalValidationError("没有待核对项时不能提交 resolution")
    by_source: dict[str, str] = {}
    for question_id, section in seen.items():
        source_id = expected[question_id].get("source_id")
        if not isinstance(source_id, str) or not source_id:
            raise LocalValidationError("拆分核对项缺少来源")
        previous = by_source.get(source_id)
        if previous is not None and previous != section:
            raise LocalValidationError("同一来源的归属核对互相冲突")
        by_source[source_id] = section
    return [
        {"id": key, "section": value} for key, value in seen.items()
    ]


def _split_source(
    session: Session,
    *,
    profile_id: str,
    record_id: str,
    split_task_id: str,
) -> tuple[
    LocalAITask,
    LocalAIInput,
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
    str,
]:
    task = session.get(LocalAITask, split_task_id)
    if (
        task is None
        or task.profile_id != profile_id
        or task.source_kind != SOURCE_KIND
        or task.source_id != record_id
        or task.task_type != contracts.TASK_SPLIT
        or task.status != "succeeded"
    ):
        raise LocalValidationError("拆分任务不可用或不属于当前记录")
    candidate = session.scalars(
        select(LocalAICandidate)
        .where(
            LocalAICandidate.task_id == task.id,
            LocalAICandidate.source_kind == SOURCE_KIND,
        )
        .order_by(LocalAICandidate.created_at.desc())
    ).first()
    inp = session.get(LocalAIInput, task.input_id)
    if candidate is None or inp is None:
        raise LocalStorageError("拆分候选或输入缺失")
    raw = candidate.raw_candidate_json
    if not isinstance(raw, dict) or raw.get("kind") != "split":
        raise LocalStorageError("拆分候选结构损坏")
    document = raw.get("document")
    questions = raw.get("questions")
    if not isinstance(document, dict) or not isinstance(questions, list):
        raise LocalStorageError("拆分候选文档或核对项损坏")
    return (
        task,
        inp,
        copy.deepcopy(raw),
        copy.deepcopy(document),
        copy.deepcopy(questions),
        candidate.id,
    )


def _blocks(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        raise LocalStorageError("课程审议联动文档损坏")
    original = value.get("original")
    if not isinstance(original, dict) or not isinstance(original.get("blocks"), list):
        raise LocalStorageError("课程审议联动文档缺少原稿结构")
    result = []
    for block in original["blocks"]:
        if (
            not isinstance(block, dict)
            or not isinstance(block.get("id"), str)
            or not isinstance(block.get("text"), str)
            or block.get("section") not in contracts.SECTIONS
            or block.get("kind") not in ("heading", "body")
        ):
            raise LocalStorageError("课程审议联动文档块损坏")
        result.append(
            {
                "id": block["id"],
                "source_id": str(block.get("source_id") or ""),
                "quote": str(block.get("quote") or ""),
                "section": block["section"],
                "kind": block["kind"],
                "text": block["text"],
            }
        )
    return result


def _insertion_anchors(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    last_by_section: dict[str, str] = {}
    for block in blocks:
        section = block.get("section")
        if section in contracts.SECTIONS:
            last_by_section[section] = block["id"]
    anchors = []
    previous: str | None = None
    for section in contracts.SECTIONS:
        after = last_by_section.get(section, previous)
        anchors.append(
            {
                "target_id": f"anchor:{section}",
                "section": section,
                "after_block_id": after,
            }
        )
        if after is not None:
            previous = after
    return anchors


def _rebuild_columns(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    columns = {
        section: {"original_ids": [], "revised_ids": []}
        for section in contracts.SECTIONS
    }
    for block in blocks:
        section = block.get("section")
        if section in columns:
            columns[section]["original_ids"].append(block["id"])
    return columns


def _build_document(
    *,
    record_id: str,
    base_version: int,
    source_hash: str,
    original_blocks: list[dict[str, Any]],
    revised_blocks: list[dict[str, Any]],
    kind: str,
) -> dict[str, Any]:
    columns = _rebuild_columns(original_blocks)
    for block in revised_blocks:
        section = block.get("section")
        if section in columns:
            columns[section]["revised_ids"].append(block["id"])
    document = {
        "schema_version": contracts.DOCUMENT_SCHEMA_VERSION,
        "kind": kind,
        "record_id": record_id,
        "base_version": base_version,
        "source_hash": source_hash,
        "original": {"blocks": original_blocks},
        "revised": {"blocks": revised_blocks},
        "columns": columns,
    }
    return document


def _section_text(blocks: list[dict[str, Any]], section: str) -> str:
    return "\n".join(
        block["text"] for block in blocks if block.get("section") == section
    )


def _column_text(blocks: list[dict[str, Any]], section: str) -> str:
    return "\n".join(
        block["text"]
        for block in blocks
        if block.get("section") == section and block.get("kind") == "body"
    )


def _full_text(blocks: list[dict[str, Any]]) -> str:
    return "\n".join(block["text"] for block in blocks)


def _questions(
    value: object, *, source_texts: Mapping[str, str] | None = None
) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise CandidateInvalid("questions 必须是数组")
    result = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise CandidateInvalid("question 必须是对象")
        question = item.get("question")
        if not isinstance(question, str) or not question.strip():
            raise CandidateInvalid("question 不能为空")
        if len(question) > contracts.MAX_QUESTION:
            raise CandidateInvalid("question 太长")
        source_id = item.get("source_id")
        quote = item.get("quote", "")
        section = item.get("section", "")
        if source_id is None:
            source_id = ""
        if not isinstance(source_id, str):
            raise CandidateInvalid("question.source_id 不合法")
        if not isinstance(quote, str):
            raise CandidateInvalid("question.quote 不合法")
        if section not in ("", *contracts.SECTIONS):
            raise CandidateInvalid("question.section 不合法")
        if source_texts is not None and not source_id:
            raise CandidateInvalid("question.source_id 不能为空")
        if source_texts is not None and source_id:
            source_text = source_texts.get(source_id)
            if source_text is None:
                raise CandidateInvalid("question 引用了未知来源")
            if quote and quote not in source_text:
                raise CandidateInvalid("question.quote 不在来源原文中")
        result.append(
            {
                "id": f"q{index + 1}",
                "source_id": source_id,
                "quote": quote,
                "question": question.strip(),
                "section": section,
            }
        )
    return result


def _split_output(
    parsed: Any,
    payload: Mapping[str, Any],
    dependencies: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(parsed, dict):
        raise CandidateInvalid("候选必须是对象")
    source_blocks = payload.get("source_blocks")
    if not isinstance(source_blocks, list):
        raise CandidateInvalid("输入来源块缺失")
    source_texts = {
        str(block.get("source_id")): str(block.get("text"))
        for block in source_blocks
        if isinstance(block, dict)
    }
    source_order = {
        source_id: index for index, source_id in enumerate(source_texts)
    }
    raw_blocks = parsed.get("blocks")
    if not isinstance(raw_blocks, list) or not raw_blocks:
        raise CandidateInvalid("blocks 不能为空")
    last_source = -1
    cursor: dict[str, int] = {}
    covered: dict[str, set[int]] = {key: set() for key in source_texts}
    blocks = []
    for item in raw_blocks:
        if not isinstance(item, dict):
            raise CandidateInvalid("block 必须是对象")
        source_id = item.get("source_id")
        quote = item.get("quote")
        section = item.get("section")
        kind = item.get("kind")
        text = item.get("text")
        if source_id not in source_texts:
            raise CandidateInvalid("block 引用了未知 source_id")
        if not isinstance(quote, str) or not quote:
            raise CandidateInvalid("block.quote 不能为空")
        if section not in contracts.SECTIONS:
            raise CandidateInvalid("block.section 不合法")
        if kind not in ("heading", "body"):
            raise CandidateInvalid("block.kind 不合法")
        if not isinstance(text, str) or not text.strip():
            raise CandidateInvalid("block.text 不能为空")
        if _content_signature(quote) != _content_signature(text):
            raise CandidateInvalid("block.text 改变了原文教学意思")
        source_text = source_texts[source_id]
        start = source_text.find(quote, cursor.get(source_id, 0))
        if start < 0:
            raise CandidateInvalid("block.quote 与来源顺序或原文不一致")
        end = start + len(quote)
        cursor[source_id] = end
        source_index = source_order[source_id]
        if source_index < last_source:
            raise CandidateInvalid("blocks 未按来源顺序返回")
        last_source = source_index
        covered[source_id].update(range(start, end))
        blocks.append(
            {
                "id": f"b{len(blocks) + 1}",
                "source_id": source_id,
                "quote": quote,
                "section": section,
                "kind": kind,
                "text": text,
            }
        )
    for source_id, source_text in source_texts.items():
        missing = [
            index
            for index, char in enumerate(source_text)
            if not char.isspace() and index not in covered[source_id]
        ]
        if missing:
            raise CandidateInvalid("blocks 未逐字覆盖来源原文")
    questions = _questions(parsed.get("questions"), source_texts=source_texts)
    mapping = dict(dependencies.get("header_redactions") or {})
    for question in questions:
        question["quote"] = _restore_tokens(question["quote"], mapping)
        question["question"] = _restore_tokens(question["question"], mapping)
    original_blocks = [
        {
            "id": block["id"],
            "source_id": block["source_id"],
            "quote": _restore_tokens(block["quote"], mapping),
            "section": block["section"],
            "kind": block["kind"],
            "text": _restore_tokens(block["text"], mapping),
        }
        for block in blocks
    ]
    original_full = _full_text(original_blocks)
    patch = {
        "lesson_original": original_full,
        "goals_original": _column_text(original_blocks, "goals"),
        "preparation_original": _column_text(
            original_blocks, "preparation"
        ),
        "process_original": _column_text(original_blocks, "process"),
    }
    document = _build_document(
        record_id=str(dependencies["record_id"]),
        base_version=int(dependencies["base_version"]),
        source_hash=_digest(_normalized_lesson(original_full)),
        original_blocks=original_blocks,
        revised_blocks=[],
        kind="split",
    )
    return {
        "kind": "split",
        "patch": patch,
        "document": document,
        "questions": questions,
        "status": "proposed",
        "reason_suggestion": "",
    }


def _edit_items(
    value: object,
    *,
    section: str,
    original_by_id: Mapping[str, dict[str, Any]],
    anchors_by_id: Mapping[str, dict[str, Any]],
    seen_targets: set[str],
) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise CandidateInvalid("edits 必须是数组")
    result = []
    for item in value:
        if not isinstance(item, dict):
            raise CandidateInvalid("edit 必须是对象")
        op = item.get("op")
        target_id = item.get("target_id")
        text = item.get("text")
        note = item.get("note", "")
        if op not in ("replace", "insert_after", "delete"):
            raise CandidateInvalid("edit.op 不合法")
        anchor = anchors_by_id.get(target_id)
        if not isinstance(target_id, str):
            raise CandidateInvalid("edit.target_id 不存在")
        if target_id in original_by_id:
            target = original_by_id[target_id]
            if op in ("replace", "delete") and target["kind"] != "body":
                raise CandidateInvalid("标题只能作为插入位置，不能替换或删除")
        elif anchor is not None and op == "insert_after":
            target = {
                "id": target_id,
                "section": anchor["section"],
                "kind": "body",
                "text": "",
            }
        else:
            raise CandidateInvalid("edit.target_id 不存在")
        if target["section"] != section:
            raise CandidateInvalid("edit 跨越了栏目")
        if target_id in seen_targets:
            raise CandidateInvalid("同一目标重复修改")
        seen_targets.add(target_id)
        if not isinstance(text, str):
            raise CandidateInvalid("edit.text 必须是字符串")
        if not isinstance(note, str):
            raise CandidateInvalid("edit.note 必须是字符串")
        if op == "delete":
            if text != "":
                raise CandidateInvalid("删除操作的 text 必须为空")
        else:
            if not text.strip():
                raise CandidateInvalid("修改或新增内容不能为空")
            if op == "replace" and text == target["text"]:
                raise CandidateInvalid("替换内容与原稿完全相同")
        result.append(
            {
                "op": op,
                "target_id": target_id,
                "text": text,
                "note": note,
            }
        )
    return result


def _review_output(
    parsed: Any,
    payload: Mapping[str, Any],
    dependencies: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(parsed, dict):
        raise CandidateInvalid("候选必须是对象")
    mapping = dict(dependencies.get("header_redactions") or {})
    parsed = _restore_structure(parsed, mapping)
    original_blocks = _blocks(payload.get("document"))
    for block in original_blocks:
        block["text"] = _restore_tokens(block["text"], mapping)
        block["quote"] = _restore_tokens(block["quote"], mapping)
    original_by_id = {block["id"]: block for block in original_blocks}
    anchors = payload.get("insertion_anchors")
    if not isinstance(anchors, list):
        anchors = _insertion_anchors(original_blocks)
    anchors_by_id = {
        anchor["target_id"]: anchor
        for anchor in anchors
        if isinstance(anchor, dict)
        and isinstance(anchor.get("target_id"), str)
        and anchor.get("section") in contracts.SECTIONS
    }
    seen: set[str] = set()
    groups: dict[str, list[dict[str, str]]] = {}
    decisions: dict[str, str] = {}
    for section in ("goals", "preparation"):
        value = parsed.get(section)
        if not isinstance(value, dict):
            raise CandidateInvalid(f"{section} 缺失")
        decision = value.get("decision")
        if decision not in ("unchanged", "adjusted"):
            raise CandidateInvalid(f"{section}.decision 不合法")
        edits = _edit_items(
            value.get("edits"),
            section=section,
            original_by_id=original_by_id,
            anchors_by_id=anchors_by_id,
            seen_targets=seen,
        )
        if decision == "unchanged" and edits:
            raise CandidateInvalid(f"{section} 不变时不能有修改")
        if decision == "adjusted" and not edits:
            raise CandidateInvalid(f"{section} 调整时必须给出修改")
        decisions[section] = decision
        groups[section] = edits
    process = parsed.get("process")
    if not isinstance(process, dict):
        raise CandidateInvalid("process 缺失")
    groups["process"] = _edit_items(
        process.get("edits"),
        section="process",
        original_by_id=original_by_id,
        anchors_by_id=anchors_by_id,
        seen_targets=seen,
    )
    reason = parsed.get("reason")
    if not isinstance(reason, str):
        raise CandidateInvalid("reason 必须是字符串")
    questions = _questions(parsed.get("questions"))

    ops = {
        edit["target_id"]: edit
        for group in groups.values()
        for edit in group
    }
    inserts: dict[str, list[dict[str, str]]] = {}
    anchor_inserts: dict[str | None, list[dict[str, Any]]] = {}
    for edit in ops.values():
        if edit["op"] != "insert_after":
            continue
        if edit["target_id"] in anchors_by_id:
            anchor = anchors_by_id[edit["target_id"]]
            after = anchor.get("after_block_id")
            if after is not None and after not in original_by_id:
                raise CandidateInvalid("插入锚点不存在")
            if after is not None and ops.get(after, {}).get("op") == "delete":
                raise CandidateInvalid("不能在删除的目标后插入")
            anchor_inserts.setdefault(after, []).append(
                {"target_id": edit["target_id"], "text": edit["text"]}
            )
        else:
            inserts.setdefault(edit["target_id"], []).append(edit)
    for target_id, items in inserts.items():
        if len(items) > 1:
            raise CandidateInvalid("同一插入位置只能新增一项")

    revised_blocks: list[dict[str, Any]] = []

    def append_inserted(
        text: str, section: str, source_block_id: str
    ) -> None:
        revised_blocks.append(
            {
                "id": f"r{len(revised_blocks) + 1}",
                "source_id": "",
                "quote": "",
                "section": section,
                "kind": "body",
                "text": text,
                "source_block_id": source_block_id,
                "inserted": True,
            }
        )

    for item in anchor_inserts.get(None, []):
        anchor = anchors_by_id[item["target_id"]]
        append_inserted(item["text"], str(anchor["section"]), item["target_id"])

    for block in original_blocks:
        op = ops.get(block["id"])
        if op is not None and op["op"] == "delete":
            continue
        text = op["text"] if op is not None and op["op"] == "replace" else block["text"]
        revised_blocks.append(
            {
                "id": f"r{len(revised_blocks) + 1}",
                "source_id": block["source_id"],
                "quote": "",
                "section": block["section"],
                "kind": block["kind"],
                "text": text,
                "source_block_id": block["id"],
                "inserted": False,
            }
        )
        for insert in inserts.get(block["id"], []):
            append_inserted(insert["text"], block["section"], block["id"])
        for item in anchor_inserts.get(block["id"], []):
            anchor = anchors_by_id[item["target_id"]]
            append_inserted(
                item["text"], str(anchor["section"]), item["target_id"]
            )

    original_goals = _column_text(original_blocks, "goals")
    original_preparation = _column_text(original_blocks, "preparation")
    original_process = _column_text(original_blocks, "process")
    revised_goals = _column_text(revised_blocks, "goals")
    revised_preparation = _column_text(revised_blocks, "preparation")
    revised_process = _column_text(revised_blocks, "process")
    goals_status = (
        "adjusted" if revised_goals != original_goals else "unchanged"
    )
    preparation_status = (
        "adjusted"
        if revised_preparation != original_preparation
        else "unchanged"
    )
    if goals_status != decisions["goals"]:
        raise CandidateInvalid("目标调整决定与实际文字不一致")
    if preparation_status != decisions["preparation"]:
        raise CandidateInvalid("准备调整决定与实际文字不一致")

    patch: dict[str, str] = {
        "lesson_original": _full_text(original_blocks),
        "goals_original": original_goals,
        "preparation_original": original_preparation,
        "process_original": original_process,
        "goals_status": goals_status,
        "preparation_status": preparation_status,
        "goals_adjustment": revised_goals if goals_status == "adjusted" else "",
        "preparation_adjustment": (
            revised_preparation if preparation_status == "adjusted" else ""
        ),
        "reason": reason.strip(),
    }
    if groups["process"]:
        patch["process_adjustment"] = revised_process
    if any(group for group in groups.values()):
        patch["lesson_revised"] = _full_text(revised_blocks)
    else:
        revised_blocks = []
    document = _build_document(
        record_id=str(dependencies["record_id"]),
        base_version=int(dependencies["base_version"]),
        source_hash=_digest(
            _normalized_lesson(_full_text(original_blocks))
        ),
        original_blocks=original_blocks,
        revised_blocks=revised_blocks,
        kind="review",
    )
    document["split_task_id"] = dependencies.get("split_task_id")
    document["split_candidate_id"] = dependencies.get("split_candidate_id")
    return {
        "kind": "review",
        "patch": patch,
        "document": document,
        "questions": questions,
        "status": "proposed",
        "reason_suggestion": "",
    }


def _replace_utf16(value: str, start: int, end: int, replacement: str) -> str:
    raw = value.encode("utf-16-le")
    prefix = raw[: start * 2].decode("utf-16-le")
    suffix = raw[end * 2 :].decode("utf-16-le")
    return prefix + replacement + suffix


def _local_question(
    number: int, question: str, section: str, quote: str
) -> dict[str, Any]:
    return {
        "id": f"q{number}",
        "source_id": "",
        "quote": quote,
        "question": question,
        "section": section,
    }


def _linked_field(
    field: str, selection_text: str, content: Mapping[str, str]
) -> tuple[str | None, str | None]:
    if not selection_text:
        return None, None
    if field in ("goals_adjustment", "preparation_adjustment", "process_adjustment"):
        return "lesson_revised", contracts.SECTION_FIELD[field]
    if field == "lesson_revised":
        found = [
            candidate
            for candidate in (
                "goals_adjustment",
                "preparation_adjustment",
                "process_adjustment",
            )
            if content.get(candidate, "").count(selection_text) == 1
        ]
        if len(found) == 1:
            return found[0], contracts.SECTION_FIELD[found[0]]
        return None, "other"
    if field in ("goals_original", "preparation_original", "process_original"):
        return "lesson_original", contracts.SECTION_FIELD[field]
    if field == "lesson_original":
        found = [
            candidate
            for candidate in (
                "goals_original",
                "preparation_original",
                "process_original",
            )
            if content.get(candidate, "").count(selection_text) == 1
        ]
        if len(found) == 1:
            return found[0], contracts.SECTION_FIELD[found[0]]
        return None, "other"
    return None, None


def _update_document_text(
    document: dict[str, Any], part: str, old: str, new: str
) -> tuple[bool, dict[str, Any]]:
    updated = copy.deepcopy(document)
    section = updated.get(part)
    if not isinstance(section, dict) or not isinstance(section.get("blocks"), list):
        return False, updated
    hits = [
        block
        for block in section["blocks"]
        if isinstance(block, dict)
        and isinstance(block.get("text"), str)
        and block["text"].count(old) == 1
    ]
    if len(hits) != 1:
        return False, updated
    hits[0]["text"] = hits[0]["text"].replace(old, new, 1)
    return True, updated


def _field_part(field: str) -> str | None:
    if field in contracts.ORIGINAL_FIELDS:
        return "original"
    if field in contracts.REVISED_FIELDS:
        return "revised"
    return None


def _field_document_blocks(
    document: Mapping[str, Any], field: str
) -> list[dict[str, Any]] | None:
    part = _field_part(field)
    if part is None:
        return None
    section = document.get(part)
    if not isinstance(section, dict) or not isinstance(section.get("blocks"), list):
        return None
    blocks = [
        block
        for block in section["blocks"]
        if isinstance(block, dict)
        and isinstance(block.get("id"), str)
        and isinstance(block.get("text"), str)
    ]
    if field in ("lesson_original", "lesson_revised"):
        return blocks
    wanted = contracts.SECTION_FIELD.get(field)
    if wanted is None:
        return None
    return [
        block
        for block in blocks
        if block.get("section") == wanted and block.get("kind") == "body"
    ]


def _assembled_blocks(
    blocks: list[dict[str, Any]],
) -> tuple[str, list[tuple[dict[str, Any], int, int]]]:
    pieces: list[str] = []
    spans: list[tuple[dict[str, Any], int, int]] = []
    offset = 0
    for block in blocks:
        if pieces:
            pieces.append("\n")
            offset += 1
        start = offset
        text = str(block["text"])
        pieces.append(text)
        offset += len(text)
        spans.append((block, start, offset))
    return "".join(pieces), spans


def _document_usable(
    document: Mapping[str, Any], content: Mapping[str, str]
) -> bool:
    return (
        isinstance(document, dict)
        and document.get("schema_version") == contracts.DOCUMENT_SCHEMA_VERSION
        and document.get("source_hash")
        == _digest(_normalized_lesson(content.get("lesson_original", "")))
    )


def _locate_edit_blocks(
    document: Mapping[str, Any],
    field: str,
    selection: Mapping[str, Any],
    content: Mapping[str, str],
) -> dict[str, Any] | None:
    blocks = _field_document_blocks(document, field)
    if not blocks:
        return None
    text, spans = _assembled_blocks(blocks)
    if text != content.get(field, ""):
        return None
    try:
        start = _python_index(text, int(selection["start"]))
        end = _python_index(text, int(selection["end"]))
    except (KeyError, ValueError, TypeError, UnicodeDecodeError):
        return None
    if start >= end or text[start:end] != selection["text"]:
        return None
    selected = [
        (block, block_start, block_end)
        for block, block_start, block_end in spans
        if block_start < end and block_end > start
    ]
    if not selected:
        return None
    indexes = [
        spans.index(item) for item in selected if item in spans
    ]
    if len(indexes) != len(selected) or indexes != list(
        range(indexes[0], indexes[0] + len(indexes))
    ):
        return None
    return {
        "text": text,
        "spans": spans,
        "blocks": selected,
        "start": start,
        "end": end,
        "part": _field_part(field),
    }


def _linked_field_for_blocks(
    field: str, located: Mapping[str, Any]
) -> str | None:
    selected = located["blocks"]
    sections = {block.get("section") for block, _s, _e in selected}
    if field in (
        "goals_original",
        "preparation_original",
        "process_original",
    ):
        return "lesson_original"
    if field in (
        "goals_adjustment",
        "preparation_adjustment",
        "process_adjustment",
    ):
        return "lesson_revised"
    if field in ("lesson_original", "lesson_revised"):
        if len(sections) != 1:
            return None
        section = next(iter(sections))
        if section not in ("goals", "preparation", "process"):
            return None
        if any(block.get("kind") != "body" for block, _s, _e in selected):
            return None
        return (
            f"{section}_original"
            if field == "lesson_original"
            else f"{section}_adjustment"
        )
    return None


def _replace_linked_text(
    document: Mapping[str, Any],
    linked_field: str,
    located: Mapping[str, Any],
    replacement: str,
    selected_text: str,
    content: Mapping[str, str],
) -> str | None:
    blocks = _field_document_blocks(document, linked_field)
    if not blocks:
        return None
    text, spans = _assembled_blocks(blocks)
    # Never reconstruct an old field over teacher edits made after the saved
    # document.  The current counterpart must still equal the trusted copy.
    if text != content.get(linked_field, ""):
        return None
    span_by_id = {block["id"]: (block, start, end) for block, start, end in spans}
    selected_ids = [block["id"] for block, _s, _e in located["blocks"]]
    if any(block_id not in span_by_id for block_id in selected_ids):
        return None
    ordered = [span_by_id[block_id] for block_id in selected_ids]
    indexes = [spans.index(item) for item in ordered if item in spans]
    if len(indexes) != len(ordered) or indexes != list(
        range(indexes[0], indexes[0] + len(indexes))
    ):
        return None
    first_block, first_start, _first_end = ordered[0]
    last_block, last_start, _last_end = ordered[-1]
    relative_start = located["start"] - located["blocks"][0][1]
    relative_end = located["end"] - located["blocks"][-1][1]
    if not (
        0 <= relative_start <= len(first_block["text"])
        and 0 <= relative_end <= len(last_block["text"])
    ):
        return None
    start = first_start + relative_start
    end = last_start + relative_end
    if text[start:end] != selected_text:
        return None
    return text[:start] + replacement + text[end:]


def _update_document_from_located(
    document: Mapping[str, Any],
    located: Mapping[str, Any],
    replacement: str,
    field: str,
    content: Mapping[str, str],
) -> tuple[bool, dict[str, Any]]:
    updated = copy.deepcopy(document)
    part = _field_part(field)
    if part is None:
        return False, updated
    section = updated.get(part)
    if not isinstance(section, dict) or not isinstance(section.get("blocks"), list):
        return False, updated
    selected = located["blocks"]
    if len(selected) != 1:
        return False, updated
    block, span_start, _span_end = selected[0]
    target = None
    for item in section["blocks"]:
        if isinstance(item, dict) and item.get("id") == block["id"]:
            target = item
            break
    if target is None or not isinstance(target.get("text"), str):
        return False, updated
    start = located["start"] - span_start
    end = located["end"] - span_start
    target["text"] = target["text"][:start] + replacement + target["text"][end:]
    return True, updated


def _edit_output(
    parsed: Any,
    payload: Mapping[str, Any],
    dependencies: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(parsed, dict):
        raise CandidateInvalid("候选必须是对象")
    mapping = dict(dependencies.get("header_redactions") or {})
    parsed = _restore_structure(parsed, mapping)
    status = parsed.get("status")
    if status not in ("proposed", "clarify", "no_change"):
        raise CandidateInvalid("edit.status 不合法")
    reason = parsed.get("reason_suggestion", "")
    if not isinstance(reason, str):
        raise CandidateInvalid("reason_suggestion 必须是字符串")
    question = parsed.get("question")
    if question is not None and not isinstance(question, str):
        raise CandidateInvalid("question 必须是字符串或 null")
    edit = parsed.get("edit")
    field = str(payload["field"])
    selection = dependencies.get("selection") or payload["selection"]
    content = {
        key: str(value)
        for key, value in dict(dependencies.get("content") or {}).items()
    }
    if field not in content:
        raise CandidateInvalid("编辑字段不在提交内容中")
    old_value = content[field]
    selected_text = str(selection["text"])
    section = str(selection.get("section") or _selection_section(field))
    questions: list[dict[str, Any]] = []
    patch: dict[str, str] = {}
    document = dependencies.get("document")
    document = copy.deepcopy(document) if isinstance(document, dict) else None

    if status == "proposed":
        if not isinstance(edit, dict):
            raise CandidateInvalid("proposed 必须提供 edit")
        target_id = edit.get("target_id")
        replacement = edit.get("replacement")
        expected_target = payload.get("target_id")
        if target_id != expected_target:
            raise CandidateInvalid("edit.target_id 与本次选区标识不一致")
        if not isinstance(replacement, str):
            raise CandidateInvalid("edit.replacement 必须是字符串")
        if replacement == selected_text:
            raise CandidateInvalid("替换内容与选区完全相同")
        if not selected_text and not replacement:
            raise CandidateInvalid("空选区没有产生修改")
        if field in contracts.ORIGINAL_FIELDS and (
            _content_signature(selected_text)
            != _content_signature(replacement)
        ):
            raise CandidateInvalid("原稿侧只允许格式整理，不得改变教学安排")
        new_value = _replace_utf16(
            old_value,
            int(selection["start"]),
            int(selection["end"]),
            replacement,
        )
        patch[field] = new_value

        document_usable = (
            document is not None and _document_usable(document, content)
        )
        located = (
            _locate_edit_blocks(document, field, selection, content)
            if document_usable
            else None
        )
        linked = None
        if located is not None:
            linked = _linked_field_for_blocks(field, located)
            if linked is not None:
                linked_value = _replace_linked_text(
                    document,
                    linked,
                    located,
                    replacement,
                    selected_text,
                    content,
                )
                if linked_value is None:
                    questions.append(
                        _local_question(
                            len(questions) + 1,
                            "另一处联动内容无法按结构确定，请核对后手动同步。",
                            contracts.SECTION_FIELD.get(linked, "other"),
                            selected_text,
                        )
                    )
                else:
                    patch[linked] = linked_value
            elif field in ("lesson_original", "lesson_revised"):
                questions.append(
                    _local_question(
                        len(questions) + 1,
                        "无法确定对应的原稿或修订栏，请核对后手动同步。",
                        section,
                        selected_text,
                    )
                )
        elif field != "reason":
            questions.append(
                _local_question(
                    len(questions) + 1,
                    "文档联动结构不可用，已保留当前文字，请核对后手动同步。",
                    section,
                    selected_text,
                )
            )

        if (
            document is not None
            and located is not None
            and (
                field in ("lesson_original", "lesson_revised")
                or (linked is not None and linked in patch)
            )
        ):
            changed, document = _update_document_from_located(
                document, located, replacement, field, content
            )
            if not changed:
                questions.append(
                    _local_question(
                        len(questions) + 1,
                        "文档联动跨度无法唯一更新，请核对后再保存。",
                        section,
                        selected_text,
                    )
                )

        touched_goals = (
            field in ("goals_original", "goals_adjustment")
            or (
                linked in ("goals_original", "goals_adjustment")
                and linked in patch
            )
        )
        touched_preparation = (
            field in ("preparation_original", "preparation_adjustment")
            or (
                linked in (
                    "preparation_original",
                    "preparation_adjustment",
                )
                and linked in patch
            )
        )
        new_content = dict(content)
        new_content.update(patch)
        if touched_goals:
            adjustment = new_content.get("goals_adjustment", "")
            original = new_content.get("goals_original", "")
            if (
                not adjustment.strip()
                or adjustment.strip() == original.strip()
            ):
                patch["goals_adjustment"] = ""
                patch["goals_status"] = "unchanged"
            else:
                patch["goals_status"] = "adjusted"
        if touched_preparation:
            adjustment = new_content.get("preparation_adjustment", "")
            original = new_content.get("preparation_original", "")
            if (
                not adjustment.strip()
                or adjustment.strip() == original.strip()
            ):
                patch["preparation_adjustment"] = ""
                patch["preparation_status"] = "unchanged"
            else:
                patch["preparation_status"] = "adjusted"
        if document is not None and "lesson_original" in patch:
            document["source_hash"] = _digest(
                _normalized_lesson(new_content.get("lesson_original", ""))
            )
    else:
        if edit is not None:
            raise CandidateInvalid("clarify/no_change 不能返回 edit")
        if status == "clarify" and (
            not isinstance(question, str) or not question.strip()
        ):
            raise CandidateInvalid("clarify 必须给出确认问题")
        if isinstance(question, str) and question.strip():
            questions.append(
                _local_question(
                    1, question.strip(), section, selected_text
                )
            )
    if patch:
        bad = set(patch) - set(contracts.PATCH_FIELDS)
        if bad:
            raise CandidateInvalid("patch 包含不可编辑字段")
    return {
        "kind": "edit",
        "patch": patch,
        "document": document,
        "questions": questions,
        "status": status,
        "reason_suggestion": (
            "" if field == "reason" else reason.strip()
        ),
    }


def validate_candidate_for_input(
    task_type: str, candidate: Any, input_row: LocalAIInput
) -> dict[str, Any]:
    payload = dict(input_row.payload_json or {})
    dependencies = dict(input_row.dependencies_json or {})
    try:
        if task_type == contracts.TASK_SPLIT:
            result = _split_output(candidate, payload, dependencies)
        elif task_type == contracts.TASK_REVIEW:
            result = _review_output(candidate, payload, dependencies)
        elif task_type == contracts.TASK_EDIT:
            result = _edit_output(candidate, payload, dependencies)
        else:
            raise CandidateInvalid("未知课程审议任务")
    except CandidateInvalid:
        raise
    except (KeyError, TypeError, ValueError, LocalStorageError) as exc:
        raise CandidateInvalid("课程审议候选结构无效") from exc
    if result.get("kind") not in KIND_TASKS:
        raise CandidateInvalid("候选 kind 不合法")
    # The final gate: generated patches never touch the local header.
    patch = result.get("patch")
    if not isinstance(patch, dict):
        raise CandidateInvalid("patch 必须是对象")
    if set(patch) - set(contracts.PATCH_FIELDS):
        raise CandidateInvalid("patch 触及了表头或不可编辑字段")
    return result


def normalize_request(
    *,
    kind: object,
    version: object,
    content: object,
    age_group: object = None,
    instruction: object = None,
    document: object = None,
    split_task_id: object = None,
    resolutions: object = None,
    selection: object = None,
) -> dict[str, Any]:
    if kind not in contracts.KIND_TASKS:
        raise LocalValidationError("kind 必须是 split/review/edit")
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version < 0
    ):
        raise LocalValidationError("version 必须是非负整数")
    canonical_content = curriculum_content.normalize_content(content)
    normalized_document = curriculum_content.normalize_document(document)
    age_text = ""
    if isinstance(age_group, str):
        age_text = age_group.strip()
    if len(age_text) > 40:
        raise LocalValidationError("age_group 超过长度上限")
    instruction_text = ""
    if instruction is not None:
        if not isinstance(instruction, str):
            raise LocalValidationError("instruction 必须是字符串")
        instruction_text = instruction.strip()
        if len(instruction_text) > contracts.MAX_INSTRUCTION:
            raise LocalValidationError("instruction 超过长度上限")
    split = _task_id_or_none(split_task_id, "split_task_id")
    if kind == "split":
        if instruction_text or split is not None or resolutions not in (None, []) or selection is not None:
            raise LocalValidationError("split 不接受 instruction、split_task_id、resolutions 或 selection")
        normalized_selection = None
        normalized_resolutions = []
    elif kind == "review":
        if split is None:
            raise LocalValidationError("review 需要 split_task_id")
        if selection is not None:
            raise LocalValidationError("review 不接受 selection")
        normalized_selection = None
        normalized_resolutions = resolutions if resolutions is not None else []
    else:
        if instruction_text == "":
            raise LocalValidationError("edit 需要 instruction")
        if split is not None or resolutions not in (None, []):
            raise LocalValidationError("edit 不接受 split_task_id 或 resolutions")
        normalized_selection = _validate_selection(
            canonical_content, selection
        )
        normalized_resolutions = []
    return {
        "kind": kind,
        "version": version,
        "content": canonical_content,
        "age_group": age_text,
        "instruction": instruction_text,
        "document": normalized_document,
        "split_task_id": split,
        "resolutions": normalized_resolutions,
        "selection": normalized_selection,
    }


def project_create(
    session: Session,
    *,
    profile_id: str,
    class_id: str,
    grade: str,
    record_id: object,
    request: Mapping[str, Any],
) -> ProjectedCurriculum:
    rid = _record_id(record_id)
    kind = str(request["kind"])
    version = int(request["version"])
    content = dict(request["content"])
    row = session.get(LocalCurriculumDeliberation, rid)
    if version == 0:
        if row is not None:
            from app.local.curriculum_service import CurriculumVersionConflict

            raise CurriculumVersionConflict(details={"version": row.version})
    else:
        if row is None or row.profile_id != profile_id or row.class_id != class_id:
            from app.local.curriculum_service import CurriculumNotFound

            raise CurriculumNotFound()
        if row.version != version:
            from app.local.curriculum_service import CurriculumVersionConflict

            raise CurriculumVersionConflict(details={"version": row.version})
    if row is not None and (
        row.profile_id != profile_id or row.class_id != class_id
    ):
        from app.local.curriculum_service import CurriculumNotFound

        raise CurriculumNotFound()
    age_group = request.get("age_group") or default_age_group(grade)
    activity = _activity(content, str(age_group))
    dependencies: dict[str, Any] = {
        "record_id": rid,
        "base_version": version,
        "kind": kind,
        "class_id": class_id,
        "content_hash": curriculum_content.content_hash(content),
        "age_group": str(age_group),
    }
    task_type = contracts.KIND_TASKS[kind]
    source_excerpt: dict[str, Any] = {"activity_name": content["activity_name"]}
    target_hashes: dict[str, str] = {}
    redactions = _header_redactions(content)

    if kind == "split":
        source_blocks = _source_blocks(content["lesson_original"], redactions)
        payload = {"activity": activity, "source_blocks": source_blocks}
        dependencies["source_blocks_hash"] = _digest(source_blocks)
        dependencies["lesson_source_hash"] = _digest(
            _normalized_lesson(content["lesson_original"])
        )
        dependencies["header_redactions"] = redactions
        target_hashes["lesson_original"] = dependencies["lesson_source_hash"]
    elif kind == "review":
        split_id = str(request["split_task_id"])
        (
            split_task,
            split_input,
            split_candidate,
            split_document,
            split_questions,
            split_candidate_id,
        ) = _split_source(
            session,
            profile_id=profile_id,
            record_id=rid,
            split_task_id=split_id,
        )
        stored_redactions = dict(
            (split_input.dependencies_json or {}).get("header_redactions")
            or {}
        )
        redactions = _redactions_from_values(
            list(redactions.values()) + list(stored_redactions.values())
        )
        split_payload = dict(split_input.payload_json or {})
        source_text = "\n".join(
            str(block.get("text"))
            for block in split_payload.get("source_blocks") or []
            if isinstance(block, dict)
        )
        source_text = _restore_tokens(source_text, stored_redactions)
        split_patch = split_candidate.get("patch") or {}
        split_lesson = (
            split_patch.get("lesson_original")
            if isinstance(split_patch, dict)
            else ""
        )
        current_lesson = _normalized_lesson(content["lesson_original"])
        if current_lesson not in {
            _normalized_lesson(source_text),
            _normalized_lesson(split_lesson),
        }:
            raise LocalAiSourceChanged("原稿在拆分后已变化，请重新拆分")
        resolutions = _normalize_resolutions(
            split_questions, request.get("resolutions")
        )
        by_source = {
            question["source_id"]: resolution["section"]
            for question in split_questions
            for resolution in resolutions
            if resolution["id"] == question.get("id")
        }
        original_blocks = _blocks(split_document)
        for block in original_blocks:
            if block["source_id"] in by_source:
                block["section"] = by_source[block["source_id"]]
        payload_blocks = [
            {
                **block,
                "quote": _redact_for_model(block["quote"], redactions),
                "text": _redact_for_model(block["text"], redactions),
            }
            for block in original_blocks
        ]
        review_document = {
            "schema_version": contracts.DOCUMENT_SCHEMA_VERSION,
            "original": {"blocks": payload_blocks},
            "columns": _rebuild_columns(payload_blocks),
        }
        anchors = _insertion_anchors(payload_blocks)
        payload = {
            "activity": activity,
            "document": review_document,
            "resolutions": resolutions,
            "instruction": request.get("instruction", ""),
            "questions": _redact_structure(split_questions, redactions),
            "insertion_anchors": anchors,
        }
        dependencies.update(
            {
                "split_task_id": split_id,
                "split_candidate_id": split_candidate_id,
                "split_document_hash": _digest(split_document),
                "resolutions": resolutions,
                "instruction": request.get("instruction", ""),
                "header_redactions": redactions,
                "lesson_source_hash": _digest(
                    _normalized_lesson(split_lesson or source_text)
                ),
            }
        )
        target_hashes["document"] = _digest(review_document)
    else:
        selection = dict(request["selection"])
        field_text = content[selection["field"]]
        pstart = _python_index(field_text, selection["start"])
        pend = _python_index(field_text, selection["end"])
        selected_original = field_text[pstart:pend]
        redacted_prefix = _redact_for_model(field_text[:pstart], redactions)
        redacted_selected = _redact_for_model(selected_original, redactions)
        redacted_start = contracts.utf16_length(redacted_prefix)
        redacted_end = redacted_start + contracts.utf16_length(redacted_selected)
        redacted_field = _redact_for_model(field_text, redactions)
        redacted_py_start = _python_index(redacted_field, redacted_start)
        redacted_py_end = _python_index(redacted_field, redacted_end)
        if (
            redacted_field[redacted_py_start:redacted_py_end]
            != redacted_selected
        ):
            raise LocalValidationError("selection 无法安全脱敏")
        context_before = redacted_field[
            max(0, redacted_py_start - 240) : redacted_py_start
        ]
        context_after = redacted_field[
            redacted_py_end : redacted_py_end + 240
        ]
        target_id = (
            f"sel:{selection['field']}:{redacted_start}:{redacted_end}"
        )
        payload = {
            "activity": activity,
            "field": selection["field"],
            "target_id": target_id,
            "context_before": context_before,
            "context_after": context_after,
            "selection": {
                "start": redacted_start,
                "end": redacted_end,
                "text": redacted_selected,
            },
            "instruction": request["instruction"],
        }
        document = request.get("document")
        dependencies.update(
            {
                "field": selection["field"],
                "target_id": target_id,
                "selection": selection,
                "instruction": request["instruction"],
                "document": document,
                "document_hash": _digest(document) if document is not None else None,
                "content": content,
                "header_redactions": redactions,
                "lesson_source_hash": _digest(
                    _normalized_lesson(content["lesson_original"])
                ),
            }
        )
        target_hashes["selection"] = _digest(selection)
    dependencies["dependency_hash"] = _digest(
        {k: v for k, v in dependencies.items() if k != "dependency_hash"}
    )
    dependency_hash = dependencies.pop("dependency_hash")
    return ProjectedCurriculum(
        task_type=task_type,
        payload=payload,
        dependencies=dependencies,
        dependency_hash=dependency_hash,
        target_hashes=target_hashes,
        source_excerpt=source_excerpt,
        target_grade=grade if grade in ("small", "middle", "large") else None,
    )


def revalidate_source(session: Session, task: LocalAITask) -> bool:
    if (
        task.source_kind != SOURCE_KIND
        or task.task_type not in contracts.TASK_TYPES
        or not isinstance(task.source_id, str)
    ):
        return False
    inp = session.get(LocalAIInput, task.input_id)
    if inp is None or inp.source_kind != SOURCE_KIND:
        return False
    dependencies = dict(inp.dependencies_json or {})
    row = session.get(LocalCurriculumDeliberation, task.source_id)
    if row is not None:
        if (
            row.profile_id != task.profile_id
            or row.class_id != dependencies.get("class_id")
        ):
            return False
    elif dependencies.get("base_version") != 0:
        return False
    if task.task_type == contracts.TASK_REVIEW:
        split_id = dependencies.get("split_task_id")
        if not isinstance(split_id, str):
            return False
        try:
            _split_source(
                session,
                profile_id=task.profile_id,
                record_id=task.source_id,
                split_task_id=split_id,
            )
        except (LocalValidationError, LocalStorageError):
            return False
    return True


def get_candidate(
    session: Session, task: LocalAITask
) -> dict[str, Any] | None:
    if task.status != "succeeded" or not task.current_execution_id:
        return None
    execution = session.get(LocalAIExecution, task.current_execution_id)
    if execution is None:
        return None
    candidate = session.scalars(
        select(LocalAICandidate).where(
            LocalAICandidate.execution_id == execution.id,
            LocalAICandidate.source_kind == SOURCE_KIND,
        )
    ).first()
    if candidate is None:
        return None
    raw = candidate.raw_candidate_json
    return copy.deepcopy(raw) if isinstance(raw, dict) else None


def task_payload(session: Session, task: LocalAITask) -> dict[str, Any]:
    return {
        "id": task.id,
        "status": task.status,
        "reason": task.reason,
        "candidate": get_candidate(session, task),
    }


KIND_TASKS = contracts.KIND_TASKS

__all__ = [
    "KIND_TASKS",
    "SOURCE_KIND",
    "ProjectedCurriculum",
    "default_age_group",
    "get_candidate",
    "normalize_request",
    "project_create",
    "revalidate_source",
    "task_payload",
    "validate_candidate_for_input",
]
