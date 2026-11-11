"""#23 daily process contract: split cleanup and one-step adapt changes.

Pure text rules shared by the local AI candidate validation and the Word
mapping. No database, no model calls, no I/O.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Any


class DailyProcessContractError(ValueError):
    """A candidate violates the #23 process contract."""


_NUMBER_RE = re.compile(
    r"^[ \t\u3000]*(?:[（(](?:[一二三四五六七八九十百]+|\d{1,3})[)）]|"
    r"(?:[一二三四五六七八九十百]+|\d{1,3})(?:[、)）]|[.．](?!\d)))[ \t\u3000]*",
    re.MULTILINE,
)
_CLEANUP_DROP = re.compile(r"[\s，。、；：！？,.;:!?()（）\[\]【】“”\"'‘’·…—-]")
# Structural numbering is normalized only at the start of a line.  This lets a
# split candidate change 一、 to 1. (or （一） to (1)) while preserving the
# level/order, but never touches digits inside the body text.
_CN_OR_AR_NUMBER = r"(?:[一二三四五六七八九十百]+|\d{1,3})"
_PAREN_NUMBER_RE = re.compile(
    rf"^[ \t\u3000]*[（(]{_CN_OR_AR_NUMBER}[)）]", re.MULTILINE
)
_LINE_NUMBER_RE = re.compile(
    rf"^[ \t\u3000]*{_CN_OR_AR_NUMBER}(?:[、)）]|[.．](?!\d))",
    re.MULTILINE,
)
# Numeric/unit/letter characters are fact-bearing.  A typo-only cleanup may
# change other characters, but these must stay in the same order and count.
_SENSITIVE_RE = re.compile(
    r"[0-9０-９A-Za-z一二三四五六七八九十百千万两"
    r"厘米毫米分秒时岁个张把块条只片次遍组人]"
)


def _normalize_structural_numbers(text: str) -> str:
    if not isinstance(text, str):
        return text
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = _PAREN_NUMBER_RE.sub("@2@", normalized)
    normalized = _LINE_NUMBER_RE.sub("@1@", normalized)
    return normalized


def _sensitive(text: str) -> str:
    return "".join(_SENSITIVE_RE.findall(_normalize_structural_numbers(text)))



@dataclass(frozen=True)
class ProcessStep:
    number: str | None
    body: str
    raw: str


@dataclass(frozen=True)
class _Span:
    start: int
    prefix_end: int
    content_end: int
    next_start: int
    prefix: str
    body: str
    number: str | None
    level: int


def _number_value(number: str | None) -> int:
    if number is None:
        return 0
    if number.isdigit():
        return int(number)
    values = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    if number in values:
        return values[number]
    if len(number) == 2 and number[0] == "十":
        return 10 + values.get(number[1], 0)
    if len(number) == 2 and number[1] == "十":
        return values.get(number[0], 0) * 10
    if len(number) == 3 and number[1] == "十":
        return values.get(number[0], 0) * 10 + values.get(number[2], 0)
    return 0


def _split_spans(text: str) -> list[_Span]:
    """Ordered line-start spans; preserve original offsets, blanks and CRLF."""
    if not isinstance(text, str) or not text.strip():
        return []
    matches = list(_NUMBER_RE.finditer(text))
    spans: list[_Span] = []
    if not matches:
        body = text.rstrip()
        return [
            _Span(0, 0, len(body), len(text), "", body, None, 0)
        ] if body else []
    first = matches[0]
    leading = text[: first.start()].rstrip()
    if leading:
        spans.append(_Span(0, 0, len(leading), first.start(), "", leading, None, 0))
    for position, match in enumerate(matches):
        next_start = matches[position + 1].start() if position + 1 < len(matches) else len(text)
        body_start = match.end()
        body = text[body_start:next_start].rstrip()
        content_end = body_start + len(body)
        prefix = match.group(0)
        number_match = re.search(r"\d{1,3}|[一二三四五六七八九十百]+", prefix)
        number = number_match.group(0) if number_match else None
        level = 2 if ("（" in prefix or "(" in prefix) else 1
        spans.append(
            _Span(
                match.start(),
                match.end(),
                content_end,
                next_start,
                prefix,
                body,
                number,
                level,
            )
        )
    return spans


def adapt_step_index(process: str) -> list[dict[str, Any]]:
    """Stable provider-facing index for the same spans used by the expander."""
    spans = _split_spans(process)
    result: list[dict[str, Any]] = []
    for index, span in enumerate(spans, start=1):
        first_line = span.body.splitlines()[0].strip() if span.body else ""
        next_level = spans[index].level if index < len(spans) else 0
        result.append(
            {
                "index": index,
                "level": span.level,
                "title": first_line[:40],
                "has_children": next_level > span.level,
                "editable": span.level > 0,
            }
        )
    return result


def _reject_embedded_step_numbers(text: str) -> None:
    for line in text.splitlines():
        if _NUMBER_RE.match(line):
            raise DailyProcessContractError(
                "年龄适配补丁 text 只能包含一个环节，不能包含其他编号环节"
            )


def _newline_for(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _normalize_body_newlines(text: str, newline: str) -> str:
    return newline.join(text.splitlines())


def _apply_prefix_renumber(text: str, spans: list[tuple[_Span, int]]) -> str:
    """Replace only the numeral token inside each ordered span's existing prefix."""
    for span, new_number in sorted(spans, key=lambda item: item[0].start, reverse=True):
        prefix = _replace_number(span.prefix, new_number)
        text = text[: span.start] + prefix + text[span.prefix_end :]
    return text


def split_process_steps(text: str) -> list[ProcessStep]:
    if not text or not text.strip():
        return []
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    starts = [index for index, line in enumerate(lines) if _NUMBER_RE.match(line)]
    if not starts:
        blocks: list[str] = []
        current: list[str] = []
        for line in lines:
            if line.strip() == "":
                if current:
                    blocks.append("\n".join(current).strip())
                    current = []
            else:
                current.append(line)
        if current:
            blocks.append("\n".join(current).strip())
        return [ProcessStep(None, block, block) for block in blocks if block.strip()]
    steps: list[ProcessStep] = []
    if starts[0] > 0:
        leading = "\n".join(lines[: starts[0]]).strip()
        if leading:
            steps.append(ProcessStep(None, leading, leading))
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        raw = "\n".join(lines[start:end]).strip()
        body = _NUMBER_RE.sub("", raw).strip()
        number_match = re.search(
            r"\d{1,3}|[一二三四五六七八九十百]+",
            _NUMBER_RE.match(raw).group(0),
        )
        number = number_match.group(0) if number_match else None
        steps.append(ProcessStep(number, body, raw))
    return steps


def _identity(step: ProcessStep) -> str:
    # Internal line breaks are content: only CRLF/LF representation and the
    # numbering prefix (already removed from body) are ignored.
    return step.body.replace("\r\n", "\n").replace("\r", "\n").strip()


def _content(text: str) -> str:
    return _CLEANUP_DROP.sub("", _normalize_structural_numbers(text))


def _best_local_ratio(needle: str, haystack: str) -> float:
    ratio, _window = _best_local_match(needle, haystack)
    return ratio


def _best_local_match(needle: str, haystack: str) -> tuple[float, str]:
    best = 0.0
    best_window = ""
    length = len(needle)
    for size in range(max(1, length - 2), length + 3):
        if size > len(haystack):
            continue
        for start in range(0, len(haystack) - size + 1):
            window = haystack[start : start + size]
            ratio = difflib.SequenceMatcher(
                None, needle, window, autojunk=False
            ).ratio()
            if ratio > best:
                best = ratio
                best_window = window
                if best >= 0.99:
                    return best, best_window
    return best, best_window


_NUMBER_AFTER = re.compile(
    r"^[ \t]*(?:(?:[一二三四五六七八九十百]+|\d{1,3})(?:[、)）]|[.．](?![0-9A-Za-z]))|"
    r"[（(](?:[一二三四五六七八九十百]+|\d{1,3})[)）])"
)
_ROLE_AFTER = re.compile(r"^[ \t]*(?:师|幼|教师|幼儿)[:：]")
_ROLE_LINE = re.compile(r"^[ \t]*(?:师|幼|教师|幼儿)[:：]")
_ESCAPED_BREAK = re.compile(r"\\+n")
_PATH_TOKEN = re.compile(r"(?:[A-Za-z]:[\\/][^\s，。；：！？、]*|\\\\[^\s，。；：！？、\\]+\\[^\s，。；：！？、]*|[^\s\\/，。；：！？、]+\\[^\s\\/，。；：！？、]+\.[A-Za-z0-9]{1,8}|[^\s\\/，。；：！？、]+\\[^\s\\/，。；：！？、]+\\[^\s\\/，。；：！？、]+)")


def _escape_inside_path(value: str, position: int) -> bool:
    start = max(0, position - 256)
    window = value[start : position + 64]
    if "\\" not in window and "/" not in window:
        return False
    offset = position - start
    return any(
        match.start() < offset < match.end()
        for match in _PATH_TOKEN.finditer(window)
    )


def normalize_ai_text(value: str) -> str:
    """Decode only structurally escaped newlines in an AI text field."""
    if not isinstance(value, str) or ("\\n" not in value and "\\\\n" not in value):
        return value
    if not _ESCAPED_BREAK.search(value):
        return value
    starts_marker = bool(
        _NUMBER_AFTER.match(value[:16]) or _ROLE_AFTER.match(value[:16])
    )
    numbered = 0
    line_start = 0
    scan = 0
    for match in _ESCAPED_BREAK.finditer(value):
        chunk = value[scan : match.start()]
        newline = chunk.rfind("\n")
        if newline >= 0:
            line_start = scan + newline + 1
        after = value[match.end() : match.end() + 64]
        next_char = value[match.end() : match.end() + 1]
        path_internal = _escape_inside_path(value, match.start())
        internal_word = bool(next_char) and next_char.isascii() and next_char.isalpha()
        if _NUMBER_AFTER.match(after) and not path_internal and not internal_word:
            numbered += 1
        scan = match.end()
    parts = []
    cursor = 0
    line_start = 0
    scan = 0
    for match in _ESCAPED_BREAK.finditer(value):
        chunk = value[scan : match.start()]
        newline = chunk.rfind("\n")
        if newline >= 0:
            line_start = scan + newline + 1
        after = value[match.end() : match.end() + 64]
        next_char = value[match.end() : match.end() + 1]
        path_internal = _escape_inside_path(value, match.start())
        internal_word = bool(next_char) and next_char.isascii() and next_char.isalpha()
        role_line = _ROLE_LINE.match(value[line_start : line_start + 16])
        convert = False
        if not path_internal and not internal_word:
            if _ROLE_AFTER.match(after):
                convert = True
            elif role_line:
                convert = True
            elif _NUMBER_AFTER.match(after) and (numbered >= 2 or starts_marker):
                convert = True
        parts.append(value[cursor : match.start()])
        parts.append("\n" if convert else match.group(0))
        cursor = match.end()
        if convert:
            line_start = match.end()
        scan = match.end()
    parts.append(value[cursor:])
    return "".join(parts)


def _normalize_fields(record: dict, keys: tuple[str, ...]) -> None:
    for key in keys:
        if isinstance(record.get(key), str):
            record[key] = normalize_ai_text(record[key])


def normalize_daily_candidate(task_type: str, candidate: dict) -> dict:
    """Normalize only the known text fields of one daily AI candidate."""
    if task_type not in (
        "daily_lesson_split",
        "daily_process_adapt",
        "daily_other_activities",
        "daily_reflection_generate",
    ):
        return candidate
    import copy

    normalized = copy.deepcopy(candidate)
    if task_type == "daily_lesson_split":
        group = normalized.get("group_activity")
        if isinstance(group, dict):
            _normalize_fields(
                group,
                (
                    "theme",
                    "objectives",
                    "preparation",
                    "key_points",
                    "difficult_points",
                    "process",
                ),
            )
        return normalized
    if task_type == "daily_process_adapt":
        _normalize_fields(normalized, ("process",))
        return normalized
    if task_type == "daily_reflection_generate":
        _normalize_fields(normalized, ("reflection",))
        return normalized
    return _normalize_other(normalized)


def _normalize_other(normalized: dict) -> dict:
    for group in normalized.get("morning_games") or []:
        if not isinstance(group, dict):
            continue
        _normalize_fields(group, ("focus_guidance", "shared_objectives", "guidance_points"))
        for game in group.get("games") or []:
            if isinstance(game, dict):
                _normalize_fields(game, ("name",))
    talk = normalized.get("morning_talk")
    if isinstance(talk, dict):
        _normalize_fields(talk, ("topic", "questions"))
    for group in normalized.get("post_group_games") or []:
        if not isinstance(group, dict):
            continue
        _normalize_fields(
            group,
            ("area", "focus_guidance", "objectives", "guidance", "support_strategy"),
        )
        for game in group.get("games") or []:
            if isinstance(game, dict):
                _normalize_fields(game, ("name",))
    afternoon = normalized.get("afternoon_outdoor")
    if isinstance(afternoon, dict):
        _normalize_fields(
            afternoon,
            ("area", "observation_focus", "objectives", "guidance", "support_strategy"),
        )
        for game in afternoon.get("games") or []:
            if isinstance(game, dict):
                _normalize_fields(game, ("name",))
    return normalized


ADAPT_PATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "operation": {
            "type": "string",
            "enum": ["replace", "insert", "no_change"],
        },
        "step_index": {"type": "integer", "minimum": 1},
        "after_step_index": {"type": "integer", "minimum": 0},
        "text": {"type": "string", "minLength": 1},
    },
    "required": ["operation"],
    "additionalProperties": False,
    "allOf": [
        {
            "if": {"properties": {"operation": {"const": "replace"}}},
            "then": {"required": ["step_index", "text"]},
        },
        {
            "if": {"properties": {"operation": {"const": "insert"}}},
            "then": {"required": ["after_step_index", "text"]},
        },
        {
            "if": {"properties": {"operation": {"const": "no_change"}}},
            "then": {"maxProperties": 1},
        },
    ],
}

_PATCH_KEYS = frozenset({"operation", "step_index", "after_step_index", "text"})
_CN_DIGITS = "零一二三四五六七八九"


def _chinese_number(value: int) -> str:
    if value <= 0:
        return str(value)
    if value < 10:
        return _CN_DIGITS[value]
    if value < 20:
        return "十" + (_CN_DIGITS[value - 10] if value > 10 else "")
    if value < 100:
        tens, ones = divmod(value, 10)
        return _CN_DIGITS[tens] + "十" + (_CN_DIGITS[ones] if ones else "")
    return str(value)


def _replace_number(prefix: str, value: int) -> str:
    return re.sub(
        r"[一二三四五六七八九十百]+|\d{1,3}",
        _chinese_number(value) if re.search(r"[一二三四五六七八九十百]", prefix) else str(value),
        prefix,
        count=1,
    )


def _strip_leading_step_number(text: str) -> str:
    match = _NUMBER_RE.match(text)
    if match is not None:
        text = text[match.end() :]
    return text.strip()


def expand_adapt_patch(
    candidate: Any,
    saved_process: str,
    baseline_process: str | None = None,
) -> dict[str, str]:
    """Expand the local one-step adapt patch into the existing ``{process}``.

    A historical/full ``{"process": ...}`` candidate is returned unchanged.  The
    new provider protocol is exactly one of ``replace`` / ``insert`` /
    ``no_change`` with no extra keys; all other source steps are copied from the
    teacher's saved process, then the existing one-step validator is applied.
    """
    if not isinstance(candidate, dict):
        raise DailyProcessContractError("年龄适配候选必须是 JSON 对象")
    if "operation" not in candidate:
        return candidate  # old full-process protocol remains readable
    if set(candidate) - _PATCH_KEYS:
        raise DailyProcessContractError("年龄适配补丁包含额外字段")
    operation = candidate.get("operation")
    spans = _split_spans(saved_process)
    if not spans:
        raise DailyProcessContractError("教师已保存过程为空，无法应用年龄适配补丁")
    if operation == "no_change":
        if set(candidate) != {"operation"}:
            raise DailyProcessContractError("no_change 不得携带索引或文字")
        return {"process": saved_process}
    if operation == "replace":
        if set(candidate) != {"operation", "step_index", "text"}:
            raise DailyProcessContractError("replace 补丁字段不完整或包含额外字段")
        index = candidate.get("step_index")
        text = candidate.get("text")
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or index < 1
            or index > len(spans)
        ):
            raise DailyProcessContractError("replace 的 step_index 越界")
        if not isinstance(text, str) or not text.strip():
            raise DailyProcessContractError("replace 的 text 不能为空")
        body = _strip_leading_step_number(text)
        if not body:
            raise DailyProcessContractError("replace 的 text 不能为空")
        _reject_embedded_step_numbers(body)
        body = _normalize_body_newlines(body, _newline_for(saved_process))
        span = spans[index - 1]
        # Splice only this step's body.  Its original prefix, following blank
        # lines, CRLF and every other line remain byte-for-byte untouched.
        replacement = saved_process[span.start : span.prefix_end] + body
        final = (
            saved_process[: span.start]
            + replacement
            + saved_process[span.content_end :]
        )
    elif operation == "insert":
        if set(candidate) != {"operation", "after_step_index", "text"}:
            raise DailyProcessContractError("insert 补丁字段不完整或包含额外字段")
        index = candidate.get("after_step_index")
        text = candidate.get("text")
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or index < 0
            or index > len(spans)
        ):
            raise DailyProcessContractError("insert 的 after_step_index 越界")
        if not isinstance(text, str) or not text.strip():
            raise DailyProcessContractError("insert 的 text 不能为空")
        body = _strip_leading_step_number(text)
        if not body:
            raise DailyProcessContractError("insert 的 text 不能为空")
        _reject_embedded_step_numbers(body)
        newline = _newline_for(saved_process)
        body = _normalize_body_newlines(body, newline)
        numbered = [span for span in spans if span.level > 0]
        if not numbered:
            style = _Span(0, 0, 0, 0, "1. ", "", "1", 1)
        elif index == 0:
            style = numbered[0]
        else:
            style = spans[index - 1]
            if style.level == 0:
                style = next(
                    (span for span in spans[index:] if span.level > 0),
                    numbered[0],
                )
        if index == 0:
            insert_at = spans[0].start
            new_number = 1
            renumber = [
                (span, 2 + offset)
                for offset, span in enumerate(
                    span for span in spans if span.level == style.level
                )
            ]
            final = (
                saved_process[:insert_at]
                + _replace_number(style.prefix, new_number)
                + body
                + newline
                + _apply_prefix_renumber(saved_process, renumber)[insert_at:]
            )
        else:
            anchor_index = index - 1
            anchor = spans[anchor_index]
            if anchor.level == 1:
                group_end = anchor_index
                while (
                    group_end + 1 < len(spans)
                    and spans[group_end + 1].level > anchor.level
                ):
                    group_end += 1
                insert_span = spans[group_end]
                new_number = _number_value(anchor.number) + 1
                renumber = []
                shift = 1
                for span in spans[group_end + 1 :]:
                    if span.level == 1:
                        renumber.append((span, _number_value(span.number) + shift))
            elif anchor.level == 2:
                insert_span = anchor
                new_number = _number_value(anchor.number) + 1
                renumber = []
                shift = 1
                for span in spans[anchor_index + 1 :]:
                    if span.level != 2:
                        break
                    renumber.append((span, _number_value(span.number) + shift))
            else:
                insert_span = anchor
                new_number = 1
                renumber = [
                    (span, 2 + offset)
                    for offset, span in enumerate(
                        span for span in spans[anchor_index + 1 :]
                        if span.level == style.level
                    )
                ]
            insert_at = insert_span.content_end
            text_after_renumber = _apply_prefix_renumber(saved_process, renumber)
            final = (
                text_after_renumber[:insert_at]
                + newline
                + _replace_number(style.prefix, new_number)
                + body
                + text_after_renumber[insert_at:]
            )
    else:
        raise DailyProcessContractError("未知的年龄适配补丁 operation")
    if baseline_process:
        validate_adapt_change(baseline_process, saved_process, final)
    return {"process": final}


def validate_split_cleanup(raw_lesson: str, fields: list[str]) -> None:
    """Field-by-field split extraction check (order-independent).

    Structural numbering at the start of a line may be normalized between
    Chinese and Arabic forms (and between full-width/half-width parentheses) as
    long as the level and order are preserved.  Body digits, units, letters,
    facts and step order still have to match.
    """
    if not isinstance(raw_lesson, str) or not raw_lesson.strip():
        raise DailyProcessContractError("原始教案为空，无法校验拆分清理")
    raw_norm = _content(raw_lesson)
    raw_for_runs = _normalize_structural_numbers(raw_lesson)
    for value in fields:
        if not isinstance(value, str) or not value.strip():
            continue
        norm = _content(value)
        if not norm:
            continue
        value_for_runs = _normalize_structural_numbers(value)
        for run in re.findall(r"[A-Za-z0-9]+", value_for_runs):
            if run not in raw_for_runs:
                raise DailyProcessContractError(
                    "拆分结果包含原文没有的字母或数字，交教师核对"
                )
        if norm in raw_norm:
            continue
        if len(norm) <= 32:
            ratio, window = _best_local_match(norm, raw_norm)
            minimum = 0.5 if len(norm) <= 4 else 0.85
            if ratio < minimum:
                raise DailyProcessContractError(
                    "拆分字段缺少原文依据：只允许明显错字、标点和误入字母清理，请交教师核对"
                )
            if _sensitive(norm) != _sensitive(window):
                raise DailyProcessContractError(
                    "拆分字段的数字、单位或事实与原文不一致，交教师核对"
                )
        else:
            anchor = min(64, len(norm))
            position = raw_norm.find(norm[:anchor])
            if position < 0:
                matcher = difflib.SequenceMatcher(None, norm, raw_norm, autojunk=False)
                match = matcher.find_longest_match(0, len(norm), 0, len(raw_norm))
                if match.size < max(8, min(24, len(norm) // 10)):
                    raise DailyProcessContractError(
                        "拆分字段缺少原文依据：只允许明显错字、标点和误入字母清理，请交教师核对"
                    )
                position = max(0, match.b - match.a)
            window = raw_norm[position : position + len(norm) + 16]
            prefix = 0
            while (
                prefix < len(norm)
                and prefix < len(window)
                and norm[prefix] == window[prefix]
            ):
                prefix += 1
            suffix = 0
            while (
                suffix < len(norm) - prefix
                and suffix < len(window) - prefix
                and norm[len(norm) - 1 - suffix] == window[len(window) - 1 - suffix]
            ):
                suffix += 1
            if prefix + suffix < len(norm) - 4:
                raise DailyProcessContractError(
                    "拆分字段缺少原文依据：只允许明显错字、标点和误入字母清理，请交教师核对"
                )
            if _sensitive(norm) != _sensitive(window[: len(norm)]):
                raise DailyProcessContractError(
                    "拆分字段的数字、单位或事实与原文不一致，交教师核对"
                )


def validate_adapt_change(
    baseline_process: str | None,
    saved_process: str,
    candidate_process: str,
) -> None:
    """Only one saved step may change or one new step may be added."""
    if not isinstance(baseline_process, str) or not baseline_process.strip():
        raise DailyProcessContractError("缺少已保存的拆分基准，无法校验单环节调整")
    saved = split_process_steps(saved_process)
    final = split_process_steps(candidate_process)
    if not saved or not final:
        raise DailyProcessContractError("活动过程结构无法安全识别，请交教师核对")
    if (len(saved) < 2 or len(final) < 2) and not all(
        step.number is not None for step in saved + final
    ):
        raise DailyProcessContractError("活动过程结构无法安全识别，请交教师核对")
    if len(final) < len(saved):
        raise DailyProcessContractError("适龄调整不得删除活动环节")
    if len(final) > len(saved) + 1:
        raise DailyProcessContractError("适龄调整仅可新增一个环节")
    matcher = difflib.SequenceMatcher(
        None,
        [_identity(step) for step in saved],
        [_identity(step) for step in final],
        autojunk=False,
    )
    modified = added = removed = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "delete":
            removed += i2 - i1
        elif tag == "insert":
            added += j2 - j1
        else:
            paired = min(i2 - i1, j2 - j1)
            modified += paired
            removed += (i2 - i1) - paired
            added += (j2 - j1) - paired
    if removed:
        raise DailyProcessContractError("适龄调整不得删除或重排活动环节")
    if modified + added > 1:
        raise DailyProcessContractError("适龄调整仅可修改或新增一个环节")
