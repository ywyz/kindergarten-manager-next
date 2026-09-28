"""I5 Word export docx generator (pure: view model -> complete docx bytes).

Slice 2 of the I5 Word export. This module consumes **only** the mapping-layer
view models produced by :mod:`app.services.word_export_mapping` (already
selected, pinned, immutable snapshots) and returns complete ``.docx`` bytes.
It never touches a Session, permissions, HTTP, business queries, version
selection or the filesystem at request time.

Design (user-confirmed 2026-09-28):
  * generation is fully in memory: the controlled template ZIP is read, the
    ``word/document.xml`` member is point-edited with ``lxml`` and every other
    ZIP member is copied byte-for-byte; nothing is written to disk;
  * standard-library ``zipfile`` + ``lxml`` are used (not ``python-docx``);
  * the two controlled assets live in ``app/assets/word_templates/`` and are
    validated by SHA-256 before use; a missing, unreadable, non-ZIP or
    hash-mismatched asset raises :class:`WordTemplateError` so a later slice
    can map it to ``EXPORT_UNAVAILABLE``. No fallback template is ever sought;
  * the current ``weekly_plan.docx`` bytes differ from the 2026-09-20
    prototype file, so its anchors, tables, merges and dynamic columns are
    derived from the current bytes only.

The parser is configured without external entity/DTD resolution and without
network access; only the trusted, repository-controlled assets are parsed.
"""

import hashlib
import io
import zipfile
from copy import deepcopy
from datetime import date
from functools import lru_cache
from pathlib import Path

from lxml import etree

# ---------------------------------------------------------------------------
# namespaces / template registry
# ---------------------------------------------------------------------------

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML = "http://www.w3.org/XML/1998/namespace"

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "assets" / "word_templates"

DAILY_TEMPLATE = TEMPLATE_DIR / "daily_plan.docx"
DAILY_TEMPLATE_SHA256 = (
    "99008f92ae42cc87da7e42e84009ffcd8bbefdf43602f09a59ae4027e5ddc9bd"
)
WEEKLY_TEMPLATE = TEMPLATE_DIR / "weekly_plan.docx"
WEEKLY_TEMPLATE_SHA256 = (
    "24ccaa9e557522c40a653643381e31f319ea6ae5e9f3e30e9dfa41da21986aed"
)

_DOCUMENT_MEMBER = "word/document.xml"

# Fixed labels of the controlled templates. These are structural markers, not
# business data; they come from the template and are not read from content.
_DAILY_TITLE_SUFFIX = "一日活动计划"
_WEEKLY_TITLE_SUFFIX = "每周工作计划表"
_WEEKLY_OUTDOOR_HEADING = "体能大循环"
_HOLIDAY_MARKER = "假期"

_DailyPostLabels = {
    "area": "室内区域游戏：",
    "outdoor": "户外游戏：",
    "special_room": "专用室游戏：",
}


class WordExportError(Exception):
    """Base generation-layer error (future slice maps to 500/503)."""

    code = "EXPORT_FAILED"

    def __init__(self, message: str = ""):
        super().__init__(message or self.code)
        self.message = message or self.code


class WordTemplateError(WordExportError):
    """Missing/unreadable/non-ZIP/hash-mismatched controlled template."""

    code = "EXPORT_UNAVAILABLE"


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def _w(tag: str) -> str:
    return f"{{{W}}}{tag}"


def _text(element) -> str:
    return "".join(t.text or "" for t in element.iter(_w("t")))


def _xml_space(element) -> None:
    element.set(f"{{{XML}}}space", "preserve")


_CN_DIGITS = "零一二三四五六七八九"


def _cn_number(value: int) -> str:
    """Chinese numeral for the week header (1 -> 一, 11 -> 十一)."""
    if value <= 0:
        raise ValueError("week number must be positive")
    if value < 10:
        return _CN_DIGITS[value]
    if value < 20:
        return "十" + (_CN_DIGITS[value % 10] if value % 10 else "")
    tens, ones = divmod(value, 10)
    return _CN_DIGITS[tens] + "十" + (_CN_DIGITS[ones] if ones else "")


_WEEKDAY_CN = ("一", "二", "三", "四", "五", "六", "日")


def _weekday_cn(day: date) -> str:
    return "周" + _WEEKDAY_CN[day.isoweekday() - 1]


def _daily_date_line(day: date) -> str:
    return f"{day.month} 月 {day.day} 日  {_weekday_cn(day)}"


def _weekly_date_range(start: date, end: date) -> str:
    if start.year == end.year:
        return (
            f"{start.year} 年 {start.month} 月{start.day}日"
            f"——{end.month}月{end.day}日"
        )
    return (
        f"{start.year} 年 {start.month} 月{start.day}日"
        f"——{end.year} 年 {end.month} 月{end.day}日"
    )


def _joined(values) -> str:
    return "；".join(v for v in values if isinstance(v, str) and v)


def _game_names(group) -> str:
    if not isinstance(group, dict):
        return ""
    names = [
        g.get("name")
        for g in (group.get("games") or [])
        if isinstance(g, dict) and isinstance(g.get("name"), str) and g["name"]
    ]
    return "、".join(names)


# ---------------------------------------------------------------------------
# controlled template loading (validated; no fallback)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=4)
def _read_template_bytes(path_str: str, expected_sha256: str) -> bytes:
    path = Path(path_str)
    if not path.is_file():
        raise WordTemplateError(f"模板资产缺失: {path.name}")
    try:
        data = path.read_bytes()
    except OSError as exc:  # unreadable
        raise WordTemplateError(f"模板资产不可读: {path.name}") from exc
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected_sha256:
        raise WordTemplateError(
            f"模板资产哈希不符: {path.name} ({digest})"
        )
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
    except zipfile.BadZipFile as exc:
        raise WordTemplateError(f"模板资产不是合法 docx zip: {path.name}") from exc
    if _DOCUMENT_MEMBER not in names:
        raise WordTemplateError(f"模板资产缺少 {_DOCUMENT_MEMBER}: {path.name}")
    return data


def _parse_document(data: bytes):
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        recover=False,
        huge_tree=False,
    )
    try:
        return etree.fromstring(data, parser=parser)
    except etree.XMLSyntaxError as exc:
        raise WordTemplateError("模板 document.xml 解析失败") from exc


def _load_template(path: Path, expected_sha256: str):
    """Return ``(raw_zip_bytes, parsed_document_root)`` for a controlled asset."""
    data = _read_template_bytes(str(path), expected_sha256)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        document = archive.read(_DOCUMENT_MEMBER)
    root = _parse_document(document)
    if root is None or root.tag != _w("document"):
        raise WordTemplateError("模板 document.xml 根节点异常")
    return data, root


def _serialize(root) -> bytes:
    return etree.tostring(
        root,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
    )


def _rebuild_zip(template_bytes: bytes, document_bytes: bytes) -> bytes:
    """Copy every ZIP member verbatim except ``word/document.xml``."""
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(template_bytes)) as source:
        with zipfile.ZipFile(output, "w") as target:
            for info in source.infolist():
                payload = (
                    document_bytes
                    if info.filename == _DOCUMENT_MEMBER
                    else source.read(info.filename)
                )
                target.writestr(info, payload)
    return output.getvalue()


# ---------------------------------------------------------------------------
# cell / paragraph writing
# ---------------------------------------------------------------------------


def _capture_templates(cell):
    """Capture (pPr, rPr) formatting templates from an existing cell."""
    pPr = None
    rPr = None
    for paragraph in cell.findall(_w("p")):
        candidate_pPr = paragraph.find(_w("pPr"))
        if pPr is None and candidate_pPr is not None:
            pPr = deepcopy(candidate_pPr)
        for run in paragraph.findall(_w("r")):
            candidate_rPr = run.find(_w("rPr"))
            if rPr is None and candidate_rPr is not None:
                rPr = deepcopy(candidate_rPr)
        if pPr is not None and rPr is not None:
            break
    return pPr, rPr


def _strip_numbering(pPr) -> None:
    if pPr is None:
        return
    numPr = pPr.find(_w("numPr"))
    if numPr is not None:
        pPr.remove(numPr)


def _make_run(text: str, red: bool, rPr_template):
    run = etree.Element(_w("r"))
    rPr = deepcopy(rPr_template) if rPr_template is not None else etree.Element(_w("rPr"))
    for color in rPr.findall(_w("color")):
        rPr.remove(color)
    if red:
        color = etree.SubElement(rPr, _w("color"))
        color.set(_w("val"), "FF0000")
    run.append(rPr)
    t = etree.SubElement(run, _w("t"))
    _xml_space(t)
    t.text = text
    return run


class _CellWriter:
    """Clears a table cell and writes deterministic paragraphs into it.

    Formatting (paragraph and run properties) is cloned from the cell's own
    template so the fixed layout is preserved while all sample text is
    replaced. Paragraph auto-numbering is stripped so business content slots
    never inherit the template's numbering (spec slice-2 item 7).
    """

    def __init__(self, cell):
        self.cell = cell
        self.pPr, self.rPr = _capture_templates(cell)
        _strip_numbering(self.pPr)
        tcPr = cell.find(_w("tcPr"))
        for child in list(cell):
            if child is not tcPr:
                cell.remove(child)

    def _paragraph(self, runs):
        paragraph = etree.SubElement(self.cell, _w("p"))
        if self.pPr is not None:
            paragraph.append(deepcopy(self.pPr))
        for text, red in runs:
            paragraph.append(_make_run(text, red, self.rPr))
        return paragraph

    def line(self, text: str, *, red: bool = False):
        return self._paragraph([(text, red)])

    def field(self, label: str, value) -> None:
        text = value if isinstance(value, str) else ""
        lines = text.split("\n")
        self.line(f"{label}{lines[0]}")
        for extra in lines[1:]:
            self.line(extra)

    def runs_lines(self, runs) -> None:
        current: list[tuple[str, bool]] = []
        for run in runs or []:
            if not isinstance(run, dict):
                continue
            parts = (run.get("text") or "").split("\n")
            red = bool(run.get("red"))
            for index, part in enumerate(parts):
                if index > 0:
                    self._paragraph(current)
                    current = []
                if part:
                    current.append((part, red))
        self._paragraph(current)


def _cells(row):
    return row.findall(_w("tc"))


def _set_cell_text(cell, text: str) -> None:
    _CellWriter(cell).line(text)


def _replace_block(table, start: int, end: int, new_rows) -> None:
    rows = table.findall(_w("tr"))
    position = list(table).index(rows[start])
    for row in rows[start:end]:
        table.remove(row)
    for offset, row in enumerate(new_rows):
        table.insert(position + offset, row)


def _page_break_paragraph():
    paragraph = etree.Element(_w("p"))
    run = etree.SubElement(paragraph, _w("r"))
    br = etree.SubElement(run, _w("br"))
    br.set(_w("type"), "page")
    return paragraph


def _set_paragraph_text(paragraph, text: str) -> None:
    pPr = paragraph.find(_w("pPr"))
    rPr = None
    for run in paragraph.findall(_w("r")):
        candidate = run.find(_w("rPr"))
        if candidate is not None:
            rPr = deepcopy(candidate)
            break
    for child in list(paragraph):
        if child is not pPr:
            paragraph.remove(child)
    paragraph.append(_make_run(text, False, rPr))


# ---------------------------------------------------------------------------
# daily plan table
# ---------------------------------------------------------------------------


def _morning_group_field(group, field_name: str) -> str:
    if not isinstance(group, dict):
        return ""
    return group.get(field_name) if isinstance(group.get(field_name), str) else ""


def _fill_daily_morning(row_body, morning_games):
    collective = morning_games.get("collective")
    free_choice = morning_games.get("free_choice")
    writer = _CellWriter(_cells(row_body)[1])
    writer.line("体能大循环：")
    writer.line("集体游戏：" + _game_names(collective))
    writer.line("自主游戏：" + _game_names(free_choice))


def _fill_daily_morning_shared(row_group, morning_games):
    collective = morning_games.get("collective")
    free_choice = morning_games.get("free_choice")
    writer = _CellWriter(_cells(row_group)[1])
    writer.field(
        "重点指导：",
        _joined(
            [
                _morning_group_field(collective, "focus_guidance"),
                _morning_group_field(free_choice, "focus_guidance"),
            ]
        ),
    )
    writer.field(
        "活动目标：",
        _joined(
            [
                _morning_group_field(collective, "shared_objectives"),
                _morning_group_field(free_choice, "shared_objectives"),
            ]
        ),
    )
    writer.field(
        "指导要点：",
        _joined(
            [
                _morning_group_field(collective, "guidance_points"),
                _morning_group_field(free_choice, "guidance_points"),
            ]
        ),
    )


def _fill_daily_talk(rows, talk):
    _CellWriter(_cells(rows[0])[1]).field("话题：", talk.get("topic"))
    _CellWriter(_cells(rows[1])[1]).field("问题设计：", talk.get("questions"))


def _fill_daily_activity(rows, activity, process):
    ordered = [
        ("活动主题：", "theme"),
        ("活动目标：", "objectives"),
        ("活动准备：", "preparation"),
        ("活动重点：", "key_points"),
        ("活动难点：", "difficult_points"),
    ]
    for row, (label, key) in zip(rows, ordered):
        _CellWriter(_cells(row)[1]).field(label, activity.get(key))
    process_row = rows[len(ordered)]
    writer = _CellWriter(_cells(process_row)[1])
    writer.line("活动过程：")
    writer.runs_lines(process.get("runs"))


def _fill_daily_post_block(block_rows, group):
    label = _DailyPostLabels.get(
        (group or {}).get("context_kind"), _DailyPostLabels["area"]
    )
    _set_cell_text(_cells(block_rows[0])[0], label)

    area = group.get("area") if isinstance(group, dict) else None
    games = _game_names(group)
    area_text = "、".join(part for part in [area, games] if part)
    writer = _CellWriter(_cells(block_rows[0])[1])
    writer.field("游戏区域：", area_text)

    writer = _CellWriter(_cells(block_rows[1])[1])
    writer.field("重点指导：", group.get("focus_guidance") if group else None)
    writer.field("活动目标：", group.get("objectives") if group else None)
    writer.field("指导要点：", group.get("guidance") if group else None)

    writer = _CellWriter(_cells(block_rows[2])[1])
    writer.field("支持策略：", group.get("support_strategy") if group else None)


def _fill_daily_afternoon(block_rows, afternoon):
    area = afternoon.get("area") if isinstance(afternoon, dict) else None
    games = _game_names(afternoon)
    area_text = "、".join(part for part in [area, games] if part)
    _CellWriter(_cells(block_rows[0])[1]).field("游戏区域：", area_text)
    writer = _CellWriter(_cells(block_rows[1])[1])
    writer.field("重点观察：", afternoon.get("observation_focus") if afternoon else None)
    writer.field("活动目标：", afternoon.get("objectives") if afternoon else None)
    writer.field("指导要点：", afternoon.get("guidance") if afternoon else None)
    _CellWriter(_cells(block_rows[2])[1]).field(
        "支持策略：", afternoon.get("support_strategy") if afternoon else None
    )


_DAILY_POST_BLOCK = (12, 15)
_DAILY_AFTERNOON_BLOCK = (15, 18)


def _build_daily_table(canonical_table, view):
    table = deepcopy(canonical_table)
    rows = table.findall(_w("tr"))

    _set_cell_text(_cells(rows[0])[0], f"第 {view['week_number']} 周")
    _set_cell_text(_cells(rows[1])[0], _daily_date_line(view["plan_date"]))

    morning = view.get("morning_games") or {}
    _fill_daily_morning(rows[2], morning)
    _fill_daily_morning_shared(rows[3], morning)
    _fill_daily_talk([rows[4], rows[5]], view.get("morning_talk") or {})
    _fill_daily_activity(
        [rows[6], rows[7], rows[8], rows[9], rows[10], rows[11]],
        view.get("group_activity") or {},
        view.get("process") or {},
    )

    # One post-group block per group (area / outdoor / special_room). The
    # canonical block is reused for the first group; extra groups clone it.
    post_groups = view.get("post_group_games") or []
    start, end = _DAILY_POST_BLOCK
    canonical_block = [deepcopy(row) for row in rows[start:end]]
    new_blocks = []
    for index in range(max(1, len(post_groups))):
        block = [deepcopy(row) for row in canonical_block]
        group = post_groups[index] if index < len(post_groups) else None
        _fill_daily_post_block(block, group)
        new_blocks.extend(block)
    _replace_block(table, start, end, new_blocks)

    rows = table.findall(_w("tr"))
    # Afternoon block always keeps its structure (empty when absent).
    offset = len(new_blocks) - (end - start)
    afternoon_start = _DAILY_AFTERNOON_BLOCK[0] + offset
    afternoon_rows = rows[afternoon_start:afternoon_start + 3]
    _fill_daily_afternoon(afternoon_rows, view.get("afternoon_outdoor"))
    # The fixed label "一日活动反思：" already lives in the template's left
    # cell; the right cell only carries the reflection value (empty stays
    # empty, no label, no sample text backfilled).
    _CellWriter(_cells(rows[afternoon_start + 3])[1]).field(
        "", view.get("reflection")
    )
    return table


# ---------------------------------------------------------------------------
# weekly plan table
# ---------------------------------------------------------------------------


def _data_widths(count: int) -> list[int]:
    total = 11052 - 933 - 920
    base, remainder = divmod(total, count)
    widths = [base] * count
    widths[-1] += remainder
    return widths


def _set_grid_span(cell, span: int, width: int) -> None:
    tcPr = cell.find(_w("tcPr"))
    if tcPr is None:
        tcPr = etree.SubElement(cell, _w("tcPr"))
        cell.insert(0, tcPr)
    grid_span = tcPr.find(_w("gridSpan"))
    if span == 1:
        if grid_span is not None:
            tcPr.remove(grid_span)
    else:
        if grid_span is None:
            grid_span = etree.SubElement(tcPr, _w("gridSpan"))
        grid_span.set(_w("val"), str(span))
    tc_w = tcPr.find(_w("tcW"))
    if tc_w is None:
        tc_w = etree.SubElement(tcPr, _w("tcW"))
    tc_w.set(_w("w"), str(width))
    tc_w.set(_w("type"), "dxa")


def _resize_data_cells(row, count: int, widths, template_cell, *, header=False):
    cells = _cells(row)
    data_cells = cells[2:]
    while len(data_cells) < count:
        clone = deepcopy(template_cell)
        last = cells[-1]
        last.addnext(clone)
        cells.append(clone)
        data_cells = cells[2:]
    while len(data_cells) > count:
        extra = data_cells.pop()
        row.remove(extra)
    for index, cell in enumerate(data_cells):
        _set_grid_span(cell, 1, widths[index])
    return data_cells


def _weekly_cell_text(column, field_name: str) -> str:
    if column.get("day_state") == "teaching":
        return column.get(field_name) or ""
    if column.get("outside_term"):
        return ""
    return _HOLIDAY_MARKER


def _fill_weekly_outdoor(cell, slots):
    writer = _CellWriter(cell)
    writer.line(_WEEKLY_OUTDOOR_HEADING)

    collective_1 = slots.get("collective_1")
    collective_2 = slots.get("collective_2")
    free_choice = slots.get("free_choice_1")

    def slot_line(prefix, slot):
        if not isinstance(slot, dict):
            writer.line(prefix)
            return
        name = slot.get("name") or ""
        objectives = slot.get("shared_objectives") or ""
        writer.line(f"{prefix}《{name}》（目标：{objectives}）")
        if slot.get("guidance_points"):
            writer.field("指导要点：", slot.get("guidance_points"))
        if slot.get("focus_guidance"):
            writer.field("重点指导：", slot.get("focus_guidance"))

    slot_line("集体游戏：1.", collective_1)
    slot_line("2.", collective_2)
    slot_line("自主游戏：", free_choice)


def _fill_weekly_focus(cell, focus, materials):
    writer = _CellWriter(cell)
    name = ""
    if isinstance(focus, dict):
        name = focus.get("area") or focus.get("name") or ""
    writer.field("本周重点指导区域：", name)
    writer.field("目标：", focus.get("objectives") if focus else None)
    writer.field("材料：", materials)
    writer.field("指导：", focus.get("guidance") if focus else None)
    writer.field("支持策略：", focus.get("support_strategy") if focus else None)


def _fill_weekly_column(cell, span: int, width: int, value) -> None:
    _set_grid_span(cell, span, width)
    _CellWriter(cell).field("", value)


def _build_weekly_table(canonical_table, view):
    table = deepcopy(canonical_table)
    columns = view.get("columns") or []
    count = len(columns)
    if count not in (5, 6, 7):
        raise WordExportError(f"周计划列集合不受支持: {count}")
    widths = _data_widths(count)

    grid = table.find(_w("tblGrid"))
    for grid_col in grid.findall(_w("gridCol")):
        grid.remove(grid_col)
    for width in (933, 920):
        grid_col = etree.SubElement(grid, _w("gridCol"))
        grid_col.set(_w("w"), str(width))
    for width in widths:
        grid_col = etree.SubElement(grid, _w("gridCol"))
        grid_col.set(_w("w"), str(width))

    rows = table.findall(_w("tr"))
    header_template = deepcopy(_cells(rows[0])[2])
    data_template = deepcopy(_cells(rows[1])[2])

    header_cells = _resize_data_cells(
        rows[0], count, widths, header_template, header=True
    )
    for index, cell in enumerate(header_cells):
        _set_cell_text(cell, "周" + _WEEKDAY_CN[columns[index]["weekday"] - 1])

    talk_cells = _resize_data_cells(rows[1], count, widths, data_template)
    activity_cells = _resize_data_cells(rows[2], count, widths, data_template)
    for index, column in enumerate(columns):
        _set_cell_text(talk_cells[index], _weekly_cell_text(column, "morning_talk_topic"))
        _set_cell_text(
            activity_cells[index],
            _weekly_cell_text(column, "group_activity_theme"),
        )

    merged_width = sum(widths)
    outdoor_cell = _cells(rows[3])[2]
    _set_grid_span(outdoor_cell, count, merged_width)
    _fill_weekly_outdoor(outdoor_cell, view.get("outdoor_game_slots") or {})

    focus_cell = _cells(rows[4])[2]
    _set_grid_span(focus_cell, count, merged_width)
    _fill_weekly_focus(
        focus_cell, view.get("focus_area"), view.get("materials")
    )

    column_keys = (
        "key_week_focus",
        "environment_setup",
        "habit_culture",
        "home_cooperation",
    )
    weekly_columns = view.get("weekly_columns") or {}
    label_width = 933 + 920
    for row, key in zip(rows[5:9], column_keys):
        _fill_weekly_column(
            _cells(row)[1],
            count + 1,
            label_width + merged_width,
            weekly_columns.get(key),
        )
    return table


# ---------------------------------------------------------------------------
# document assembly
# ---------------------------------------------------------------------------


def _require_views(views, kind: str):
    views = list(views)
    if not views:
        raise WordExportError(f"{kind} 导出至少需要一份计划")
    return views


def _body_of(root):
    body = root.find(_w("body"))
    if body is None:
        raise WordExportError("模板缺少 document body")
    return body


def _reset_body(body):
    sectPr = body.find(_w("sectPr"))
    for child in list(body):
        if child is not sectPr:
            body.remove(child)
    return sectPr


def _append_body(body, elements, sectPr):
    for element in elements:
        if sectPr is not None:
            sectPr.addprevious(element)
        else:
            body.append(element)


def generate_daily_export_docx(views, *, template_path=None) -> bytes:
    """Generate one docx for the ordered daily-plan view models."""
    views = _require_views(views, "日计划")
    path = Path(template_path) if template_path else DAILY_TEMPLATE
    template_bytes, root = _load_template(path, DAILY_TEMPLATE_SHA256)
    body = _body_of(root)

    header_templates = [
        deepcopy(p) for p in body.findall(_w("p"))[:2]
    ]
    if len(header_templates) < 2:
        raise WordTemplateError("日模板缺少表头段落")
    canonical_table = body.find(_w("tbl"))
    if canonical_table is None:
        raise WordTemplateError("日模板缺少计划表格")

    # Every plan is a complete block with its own title, subtitle and table.
    # A range export can mix creators, so the header must never be shared or
    # reused across plans (spec 5.1/5.3: header comes from that plan's own
    # snapshot, never re-queried or re-derived in the generation layer).
    elements = []
    for index, view in enumerate(views):
        if index > 0:
            elements.append(_page_break_paragraph())
        header = view.get("header") or {}
        title = deepcopy(header_templates[0])
        subtitle = deepcopy(header_templates[1])
        _set_paragraph_text(
            title,
            f"{header.get('school_name') or ''}{_DAILY_TITLE_SUFFIX}",
        )
        parts = [
            header.get("grade"),
            header.get("class_name"),
            header.get("creator_display_name"),
        ]
        _set_paragraph_text(
            subtitle, " ".join(p for p in parts if isinstance(p, str) and p)
        )
        elements.extend([title, subtitle])
        elements.append(_build_daily_table(canonical_table, view))

    sectPr = _reset_body(body)
    _append_body(body, elements, sectPr)
    return _rebuild_zip(template_bytes, _serialize(root))


def generate_weekly_export_docx(views, *, template_path=None) -> bytes:
    """Generate one docx for the ordered weekly-plan view models."""
    views = _require_views(views, "周计划")
    path = Path(template_path) if template_path else WEEKLY_TEMPLATE
    template_bytes, root = _load_template(path, WEEKLY_TEMPLATE_SHA256)
    body = _body_of(root)

    header_templates = [
        deepcopy(p) for p in body.findall(_w("p"))[:3]
    ]
    if len(header_templates) < 3:
        raise WordTemplateError("周模板缺少表头段落")
    canonical_table = body.find(_w("tbl"))
    if canonical_table is None:
        raise WordTemplateError("周模板缺少计划表格")

    elements = []
    for index, view in enumerate(views):
        if index > 0:
            elements.append(_page_break_paragraph())
        title = deepcopy(header_templates[0])
        theme_line = deepcopy(header_templates[1])
        staff_line = deepcopy(header_templates[2])
        header = view.get("header") or {}
        _set_paragraph_text(
            title,
            f"{header.get('school_name') or ''}{_WEEKLY_TITLE_SUFFIX}",
        )
        date_range = view.get("date_range") or {}
        # Class header carries both the creation-time snapshots ``grade`` and
        # ``class_name`` (spec 5.2/5.3), joined like the daily subtitle with a
        # single space, empty parts filtered. Never backfilled from the
        # current class profile.
        class_parts = [header.get("grade"), header.get("class_name")]
        class_text = " ".join(
            part for part in class_parts if isinstance(part, str) and part
        )
        _set_paragraph_text(
            theme_line,
            (
                f"主题名称：《{header.get('theme') or ''}》 "
                f"班级：{class_text} "
                f"第（{_cn_number(view['week_number'])}）周"
                f"（{_weekly_date_range(date_range['start'], date_range['end'])}）"
            ),
        )
        teacher_names = [
            name
            for name in (header.get("header_teacher_names") or [])
            if isinstance(name, str) and name
        ]
        _set_paragraph_text(
            staff_line,
            f"教师：{' '.join(teacher_names)}  "
            f"保育员：{header.get('caregiver_name') or ''}",
        )
        elements.extend([title, theme_line, staff_line])
        elements.append(_build_weekly_table(canonical_table, view))

    sectPr = _reset_body(body)
    _append_body(body, elements, sectPr)
    return _rebuild_zip(template_bytes, _serialize(root))


def generate_export_docx(kind: str, views, *, template_path=None) -> bytes:
    """Dispatch by mapping-layer ``kind`` (``daily_plan`` / ``weekly_plan``)."""
    from app.services import word_export_mapping as mapping

    if kind == mapping.KIND_DAILY:
        return generate_daily_export_docx(views, template_path=template_path)
    if kind == mapping.KIND_WEEKLY:
        return generate_weekly_export_docx(views, template_path=template_path)
    raise WordExportError(f"未知导出类型: {kind}")
