"""#23 daily process contract: split cleanup and one-step adapt changes.

Pure text rules shared by the local AI candidate validation and the Word
mapping. No database, no model calls, no I/O.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass


class DailyProcessContractError(ValueError):
    """A candidate violates the #23 process contract."""


_NUMBER_RE = re.compile(
    r"^[ \t\u3000]*(?:[（(]\d{1,3}[)）]|\d{1,3}(?:[、)）]|[.．](?!\d)))[ \t\u3000]*"
)
_CLEANUP_DROP = re.compile(r"[\s，。、；：！？,.;:!?()（）\[\]【】“”\"'‘’·…—-]")


@dataclass(frozen=True)
class ProcessStep:
    number: str | None
    body: str
    raw: str

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
        number_match = re.search(r"\d{1,3}", _NUMBER_RE.match(raw).group(0))
        number = number_match.group(0) if number_match else None
        steps.append(ProcessStep(number, body, raw))
    return steps


def _identity(step: ProcessStep) -> str:
    # Internal line breaks are content: only CRLF/LF representation and the
    # numbering prefix (already removed from body) are ignored.
    return step.body.replace("\r\n", "\n").replace("\r", "\n").strip()


def _content(text: str) -> str:
    return _CLEANUP_DROP.sub("", text)

def _best_local_ratio(needle: str, haystack: str) -> float:
    best = 0.0
    length = len(needle)
    for size in range(max(1, length - 2), length + 3):
        if size > len(haystack):
            continue
        for start in range(0, len(haystack) - size + 1):
            ratio = difflib.SequenceMatcher(
                None, needle, haystack[start : start + size], autojunk=False
            ).ratio()
            if ratio > best:
                best = ratio
                if best >= 0.99:
                    return best
    return best


_NUMBER_AFTER = re.compile(
    r"^[ \t]*(?:\d{1,3}(?:[、)）]|[.．](?![0-9A-Za-z]))|[（(]\d{1,3}[)）])"
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


def validate_split_cleanup(raw_lesson: str, fields: list[str]) -> None:
    """Field-by-field split extraction check (order-independent)."""
    if not isinstance(raw_lesson, str) or not raw_lesson.strip():
        raise DailyProcessContractError("原始教案为空，无法校验拆分清理")
    raw_norm = _content(raw_lesson)
    for value in fields:
        if not isinstance(value, str) or not value.strip():
            continue
        norm = _content(value)
        if not norm:
            continue
        for run in re.findall(r"[A-Za-z0-9]+", value):
            if run not in raw_lesson:
                raise DailyProcessContractError(
                    "拆分结果包含原文没有的字母或数字，交教师核对"
                )
        if norm in raw_norm:
            continue
        if len(norm) <= 32:
            ratio = _best_local_ratio(norm, raw_norm)
            minimum = 0.5 if len(norm) <= 4 else 0.85
            if ratio < minimum:
                raise DailyProcessContractError(
                    "拆分字段缺少原文依据：只允许明显错字、标点和误入字母清理，请交教师核对"
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
