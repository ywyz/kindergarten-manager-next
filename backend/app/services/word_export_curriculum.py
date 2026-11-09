"""Pure curriculum-deliberation DOCX generator.

The teacher-confirmed paper form is reconstructed here in code from OOXML; no
reference DOCX or teacher file is read at generation time.  Only the editable
text strings saved in the record are written into the document.

Layout contract (2026-11-09 teacher confirmation):
  * A4 portrait, 11906 x 16838 twips, 1440 top/bottom, 1800 left/right;
  * title ``课程审议记录表`` in 宋体 16 pt bold, centred, exact 23 pt line;
  * fixed six-column table with the confirmed widths and -302 twip indent;
  * main table in section 1; the original appendix starts with a page break;
    the revised appendix, when present, starts a new section; the empty
    appendix is omitted completely.
"""

from __future__ import annotations

import io
import zipfile
from typing import Any, Iterable, Mapping

from lxml import etree

from app.local import curriculum_content

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML = "http://www.w3.org/XML/1998/namespace"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
CP = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
DC = "http://purl.org/dc/elements/1.1/"
DCTERMS = "http://purl.org/dc/terms/"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
EP = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
VT = "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"

_PAGE_WIDTH = 11906
_PAGE_HEIGHT = 16838
_MARGIN_TOP_BOTTOM = 1440
_MARGIN_LEFT_RIGHT = 1800
_COLUMN_WIDTHS = (1188, 2438, 1644, 1661, 1392, 1104)
_TABLE_INDENT = -302
_ROW_HEIGHTS = (459, 459, 459, 459, 2360, 2190, 2542, 1859)

_SIZE_TITLE = 16
_SIZE_LABEL = 12
_SIZE_HEADER_VALUE = 11
_SIZE_INSTITUTION = 12
_SIZE_FORM = 12
_SIZE_BODY = 11
_SIZE_APPENDIX = 12

_FONT = "宋体"
_FORM_OPTIONS = (
    ("collective", "集体"),
    ("area", "区域"),
    ("parent_child", "亲子"),
    ("small_group", "小组"),
    ("other", "其他"),
)
_GOALS_PROMPT = "（结合实际情况对目标的调整）"
_GOALS_STATUS_PROMPTS = (
    ("unchanged", "保持原设计不变"),
    ("adjusted", "有所调整"),
)
_PREPARATION_STATUS_PROMPTS = (
    ("unchanged", "保持原设计，不变"),
    ("adjusted", "有所调整"),
)


def _w(tag: str) -> str:
    return f"{{{W}}}{tag}"


def _q(uri: str, tag: str) -> str:
    return f"{{{uri}}}{tag}"


def _el(tag: str, **attrs: str):
    element = etree.Element(tag)
    for name, value in attrs.items():
        element.set(_w(name), value)
    return element


def _sub(parent, tag: str, **attrs: str):
    element = etree.SubElement(parent, tag)
    for name, value in attrs.items():
        element.set(_w(name), value)
    return element


def _clean_text(value: object) -> str:
    return curriculum_content.sanitize_export_text(value)


def _text_lines(value: object) -> list[str]:
    text = _clean_text(value)
    return text.split("\n") if text != "" else [""]


def _run_props(size: int, *, bold: bool, underline: bool):
    props = _el(_w("rPr"))
    fonts = _sub(props, _w("rFonts"))
    for role in ("ascii", "hAnsi", "eastAsia", "cs"):
        fonts.set(_w(role), _FONT)
    if bold:
        _sub(props, _w("b"))
        _sub(props, _w("bCs"))
    _sub(props, _w("color"), val="000000")
    _sub(props, _w("sz"), val=str(size * 2))
    _sub(props, _w("szCs"), val=str(size * 2))
    if underline:
        _sub(props, _w("u"), val="single")
    return props


def _text_run(text: str, size: int, *, bold: bool = False, underline: bool = False):
    run = _el(_w("r"))
    run.append(_run_props(size, bold=bold, underline=underline))
    value = _sub(run, _w("t"))
    value.set(f"{{{XML}}}space", "preserve")
    value.text = text
    return run


def _tab_run(size: int):
    run = _el(_w("r"))
    run.append(_run_props(size, bold=False, underline=False))
    _sub(run, _w("tab"))
    return run


def _add_text(
    paragraph,
    value: object,
    size: int,
    *,
    bold: bool = False,
    underline: bool = False,
) -> None:
    text = _clean_text(value)
    parts = text.split("\t")
    for index, part in enumerate(parts):
        if index:
            paragraph.append(_tab_run(size))
        if part:
            paragraph.append(
                _text_run(part, size, bold=bold, underline=underline)
            )


def _paragraph(
    *,
    align: str | None = None,
    page_break_before: bool = False,
    widow_control: bool = False,
    adjust_right_ind: bool = False,
    snap_to_grid: bool = False,
    first_line_indent: int | None = None,
    line: int | None = None,
    line_rule: str = "auto",
):
    paragraph = _el(_w("p"))
    props = _el(_w("pPr"))
    paragraph.append(props)
    if page_break_before:
        _sub(props, _w("pageBreakBefore"))
    if widow_control:
        _sub(props, _w("widowControl"))
    if adjust_right_ind:
        _sub(props, _w("adjustRightInd"), val="0")
    if snap_to_grid:
        _sub(props, _w("snapToGrid"), val="0")
    if line is not None:
        _sub(
            props,
            _w("spacing"),
            line=str(line),
            lineRule=line_rule,
        )
    if first_line_indent is not None:
        _sub(props, _w("ind"), firstLine=str(first_line_indent))
    if align is not None:
        _sub(props, _w("jc"), val=align)
    return paragraph


def _line_paragraphs(
    value: object,
    size: int,
    *,
    align: str | None = None,
    widow_control: bool = False,
    line: int | None = None,
    line_rule: str = "auto",
) -> list:
    paragraphs = []
    for text_line in _text_lines(value):
        paragraph = _paragraph(
            align=align,
            widow_control=widow_control,
            line=line,
            line_rule=line_rule,
        )
        _add_text(paragraph, text_line, size)
        paragraphs.append(paragraph)
    return paragraphs


def _label_cell(width: int, text: str, *, span: int = 1, align: str | None = "center"):
    paragraph = _paragraph(
        align=align, line=460, line_rule="exact"
    )
    _add_text(paragraph, text, _SIZE_LABEL)
    return _cell(width, [paragraph], span=span, v_align="center")


def _value_cell(
    width: int,
    value: object,
    size: int,
    *,
    span: int = 1,
    align: str | None = None,
    v_align: str | None = "center",
    line: int | None = None,
    line_rule: str = "auto",
):
    paragraphs = _line_paragraphs(
        value, size, align=align, line=line, line_rule=line_rule
    )
    return _cell(width, paragraphs, span=span, v_align=v_align)


def _cell(
    width: int,
    paragraphs: Iterable,
    *,
    span: int = 1,
    v_align: str | None = "center",
):
    cell = _el(_w("tc"))
    props = _el(_w("tcPr"))
    cell.append(props)
    _sub(props, _w("tcW"), w=str(width), type="dxa")
    if span > 1:
        _sub(props, _w("gridSpan"), val=str(span))
    if v_align is not None:
        _sub(props, _w("vAlign"), val=v_align)
    content = list(paragraphs)
    if not content:
        content = [_paragraph()]
    for paragraph in content:
        cell.append(paragraph)
    return cell


def _row(cells: Iterable, height: int):
    row = _el(_w("tr"))
    props = _el(_w("trPr"))
    row.append(props)
    _sub(props, _w("trHeight"), val=str(height))
    for cell in cells:
        row.append(cell)
    return row


def _status_check(status: str, expected: str) -> str:
    return "√" if status == expected else ""


def _status_paragraphs(
    status: str, adjustment: str, *, group: str
) -> list:
    paragraphs = []
    if group == "goals":
        paragraph = _paragraph()
        _add_text(paragraph, _GOALS_PROMPT, _SIZE_BODY)
        paragraphs.append(paragraph)
        prompts = _GOALS_STATUS_PROMPTS
    elif group == "preparation":
        prompts = _PREPARATION_STATUS_PROMPTS
    else:
        prompts = ()
    for value, label in prompts:
        paragraph = _paragraph()
        _add_text(
            paragraph,
            f"{label}（{_status_check(status, value)}）",
            _SIZE_BODY,
        )
        paragraphs.append(paragraph)
    heading = _paragraph()
    _add_text(heading, "调整内容：", _SIZE_BODY)
    paragraphs.append(heading)
    if curriculum_content.is_substantive(adjustment):
        paragraphs.extend(_line_paragraphs(adjustment, _SIZE_BODY))
    elif group == "goals":
        paragraphs.append(_paragraph())
    return paragraphs


def _form_paragraph(content: Mapping[str, str]):
    paragraph = _paragraph(line=460, line_rule="exact")
    selected = content.get("activity_form", "")
    for index, (value, label) in enumerate(_FORM_OPTIONS):
        _add_text(paragraph, label, _SIZE_FORM)
        if selected == value:
            _add_text(paragraph, "√", _SIZE_FORM)
        if index != len(_FORM_OPTIONS) - 1:
            _add_text(paragraph, "、", _SIZE_FORM)
    other = ""
    if selected == "other":
        other = _clean_text(content.get("activity_form_other", "")).replace(
            "\n", " "
        )
    under_line = other if other else " "
    _add_text(paragraph, under_line, _SIZE_FORM, underline=True)
    return paragraph


def _main_table(content: Mapping[str, str]):
    table = _el(_w("tbl"))
    props = _el(_w("tblPr"))
    table.append(props)
    _sub(props, _w("tblW"), w="0", type="auto")
    _sub(props, _w("tblInd"), w=str(_TABLE_INDENT), type="dxa")
    borders = _sub(props, _w("tblBorders"))
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        _sub(
            borders,
            _w(edge),
            val="single",
            sz="4",
            space="0",
            color="auto",
        )
    _sub(props, _w("tblLayout"), type="fixed")
    _sub(
        props,
        _w("tblLook"),
        val="0000",
        firstRow="0",
        lastRow="0",
        firstColumn="0",
        lastColumn="0",
        noHBand="0",
        noVBand="0",
    )

    grid = _sub(table, _w("tblGrid"))
    for width in _COLUMN_WIDTHS:
        _sub(grid, _w("gridCol"), w=str(width))

    # Row 1: activity name, activity form (value spans three columns).
    table.append(
        _row(
            (
                _label_cell(_COLUMN_WIDTHS[0], "活动名称"),
                _value_cell(
                    _COLUMN_WIDTHS[1],
                    content.get("activity_name", ""),
                    _SIZE_HEADER_VALUE,
                ),
                _label_cell(_COLUMN_WIDTHS[2], "活动形式"),
                _cell(
                    sum(_COLUMN_WIDTHS[3:]),
                    [_form_paragraph(content)],
                    span=3,
                    v_align="center",
                ),
            ),
            _ROW_HEIGHTS[0],
        )
    )

    # Row 2: institution, class, child count.
    table.append(
        _row(
            (
                _label_cell(_COLUMN_WIDTHS[0], "实施单位"),
                _value_cell(
                    _COLUMN_WIDTHS[1],
                    content.get("institution", ""),
                    _SIZE_INSTITUTION,
                    align="center",
                    line=460,
                    line_rule="exact",
                ),
                _label_cell(
                    _COLUMN_WIDTHS[2], "班级（年龄段）", align=None
                ),
                _value_cell(
                    _COLUMN_WIDTHS[3],
                    content.get("class_name", ""),
                    _SIZE_HEADER_VALUE,
                ),
                _label_cell(_COLUMN_WIDTHS[4], "幼儿人数"),
                _value_cell(
                    _COLUMN_WIDTHS[5],
                    content.get("child_count", ""),
                    _SIZE_HEADER_VALUE,
                ),
            ),
            _ROW_HEIGHTS[1],
        )
    )

    # Row 3: organiser, recorder, date.
    table.append(
        _row(
            (
                _label_cell(_COLUMN_WIDTHS[0], "组织教师"),
                _value_cell(
                    _COLUMN_WIDTHS[1],
                    content.get("organizer", ""),
                    _SIZE_HEADER_VALUE,
                ),
                _label_cell(_COLUMN_WIDTHS[2], "记录人"),
                _value_cell(
                    _COLUMN_WIDTHS[3],
                    content.get("recorder", ""),
                    _SIZE_HEADER_VALUE,
                ),
                _label_cell(_COLUMN_WIDTHS[4], "活动时间"),
                _value_cell(
                    _COLUMN_WIDTHS[5],
                    _display_date(content.get("activity_date", "")),
                    _SIZE_HEADER_VALUE,
                ),
            ),
            _ROW_HEIGHTS[2],
        )
    )

    # Row 4: original and revised column headings (4 + 2 columns).
    table.append(
        _row(
            (
                _label_cell(
                    sum(_COLUMN_WIDTHS[:4]), "原稿", span=4
                ),
                _label_cell(
                    sum(_COLUMN_WIDTHS[4:]), "修订", span=2
                ),
            ),
            _ROW_HEIGHTS[3],
        )
    )

    grouped = (
        (
            "活动目标",
            "goals_original",
            "goals_status",
            "goals_adjustment",
            "goals",
        ),
        (
            "活动准备",
            "preparation_original",
            "preparation_status",
            "preparation_adjustment",
            "preparation",
        ),
        (
            "活动过程记录",
            "process_original",
            None,
            "process_adjustment",
            "process",
        ),
    )
    for index, (
        label,
        original_key,
        status_key,
        adjustment_key,
        group,
    ) in enumerate(grouped):
        status = content.get(status_key, "") if status_key else ""
        table.append(
            _row(
                (
                    _label_cell(_COLUMN_WIDTHS[0], label),
                    _value_cell(
                        sum(_COLUMN_WIDTHS[1:4]),
                        content.get(original_key, ""),
                        _SIZE_BODY,
                        span=3,
                        v_align="center",
                    ),
                    _cell(
                        sum(_COLUMN_WIDTHS[4:]),
                        _status_paragraphs(
                            status,
                            content.get(adjustment_key, ""),
                            group=group,
                        ),
                        span=2,
                        v_align=None,
                    ),
                ),
                _ROW_HEIGHTS[4 + index],
            )
        )

    # Last row: reason, value spans the remaining five columns.
    table.append(
        _row(
            (
                _label_cell(
                    _COLUMN_WIDTHS[0], "简要说明课程审议后调整的理由"
                ),
                _value_cell(
                    sum(_COLUMN_WIDTHS[1:]),
                    content.get("reason", ""),
                    _SIZE_BODY,
                    span=5,
                    v_align="center",
                ),
            ),
            _ROW_HEIGHTS[7],
        )
    )
    return table


def _display_date(value: str) -> str:
    if not value:
        return ""
    return value.replace("-", ".")


def _sect_pr(*, cols_space: int = 720):
    section = _el(_w("sectPr"))
    _sub(
        section,
        _w("pgSz"),
        w=str(_PAGE_WIDTH),
        h=str(_PAGE_HEIGHT),
    )
    _sub(
        section,
        _w("pgMar"),
        top=str(_MARGIN_TOP_BOTTOM),
        right=str(_MARGIN_LEFT_RIGHT),
        bottom=str(_MARGIN_TOP_BOTTOM),
        left=str(_MARGIN_LEFT_RIGHT),
        header="851",
        footer="992",
        gutter="0",
    )
    _sub(section, _w("cols"), space=str(cols_space))
    _sub(section, _w("docGrid"), type="lines", linePitch="312")
    return section


def _section_break_paragraph():
    paragraph = _paragraph(
        align="left",
        adjust_right_ind=True,
        snap_to_grid=True,
        first_line_indent=480,
        line=460,
        line_rule="exact",
    )
    props = paragraph.find(_w("pPr"))
    if props is None:  # pragma: no cover - _paragraph always creates it
        props = _el(_w("pPr"))
        paragraph.append(props)
    props.append(_sect_pr(cols_space=720))
    return paragraph


def _page_break_run(size: int):
    run = _el(_w("r"))
    run.append(_run_props(size, bold=False, underline=False))
    _sub(run, _w("br"), type="page")
    return run


def _appendix_title(text: str, *, page_break: bool):
    paragraph = _paragraph(
        align="left",
        adjust_right_ind=True,
        snap_to_grid=True,
        line=460,
        line_rule="exact",
    )
    if page_break:
        paragraph.append(_page_break_run(_SIZE_APPENDIX))
    _add_text(paragraph, text, _SIZE_APPENDIX)
    return paragraph


def _appendix_paragraphs(value: object, *, original: bool):
    paragraphs = []
    for text_line in curriculum_content.appendix_lines(value):
        paragraph = _paragraph(
            align=None if original else "left",
            widow_control=not original,
            line=360 if original else None,
            line_rule="auto",
        )
        _add_text(paragraph, text_line, _SIZE_APPENDIX)
        paragraphs.append(paragraph)
    return paragraphs


def _document_xml(content: Mapping[str, str]) -> bytes:
    document = etree.Element(
        _w("document"), nsmap={"w": W, "r": R}
    )
    body = _sub(document, _w("body"))

    title = _paragraph(
        align="center", line=460, line_rule="exact"
    )
    _add_text(title, "课程审议记录表", _SIZE_TITLE, bold=True)
    body.append(title)
    body.append(_main_table(content))

    original = curriculum_content.is_substantive(
        content.get("lesson_original", "")
    )
    revised = curriculum_content.is_substantive(
        content.get("lesson_revised", "")
    )
    if original:
        body.append(
            _appendix_title("附教案：原稿", page_break=True)
        )
        body.extend(
            _appendix_paragraphs(
                content.get("lesson_original", ""), original=True
            )
        )
    if revised:
        body.append(_section_break_paragraph())
        body.append(
            _appendix_title("二次修改", page_break=False)
        )
        body.extend(
            _appendix_paragraphs(
                content.get("lesson_revised", ""), original=False
            )
        )
    body.append(_sect_pr(cols_space=425 if revised else 720))
    return etree.tostring(
        document,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
    )


def _styles_xml() -> bytes:
    styles = etree.Element(_w("styles"), nsmap={"w": W})
    defaults = _sub(styles, _w("docDefaults"))
    run_defaults = _sub(defaults, _w("rPrDefault"))
    run_props = _sub(run_defaults, _w("rPr"))
    fonts = _sub(run_props, _w("rFonts"))
    fonts.set(_w("ascii"), "Times New Roman")
    fonts.set(_w("hAnsi"), "Times New Roman")
    fonts.set(_w("eastAsia"), _FONT)
    fonts.set(_w("cs"), "Times New Roman")
    _sub(
        run_props,
        _w("lang"),
        val="en-US",
        eastAsia="zh-CN",
        bidi="ar-SA",
    )
    _sub(defaults, _w("pPrDefault"))

    style = _sub(
        styles,
        _w("style"),
        type="paragraph",
        default="1",
        styleId="Normal",
    )
    _sub(style, _w("name"), val="Normal")
    _sub(style, _w("qFormat"))
    style_ppr = _sub(style, _w("pPr"))
    _sub(style_ppr, _w("widowControl"), val="0")
    _sub(style_ppr, _w("jc"), val="both")
    style_rpr = _sub(style, _w("rPr"))
    _sub(style_rpr, _w("kern"), val="2")
    _sub(style_rpr, _w("sz"), val="21")
    _sub(style_rpr, _w("szCs"), val="24")

    table_style = _sub(
        styles,
        _w("style"),
        type="table",
        default="1",
        styleId="TableNormal",
    )
    _sub(table_style, _w("name"), val="Normal Table")
    _sub(table_style, _w("uiPriority"), val="99")
    _sub(table_style, _w("semiHidden"))
    _sub(table_style, _w("unhideWhenUsed"))
    table_ppr = _sub(table_style, _w("tblPr"))
    _sub(table_ppr, _w("tblInd"), w="0", type="dxa")
    cell_margins = _sub(table_ppr, _w("tblCellMar"))
    _sub(cell_margins, _w("top"), w="0", type="dxa")
    _sub(cell_margins, _w("left"), w="108", type="dxa")
    _sub(cell_margins, _w("bottom"), w="0", type="dxa")
    _sub(cell_margins, _w("right"), w="108", type="dxa")
    return etree.tostring(
        styles,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
    )


def _settings_xml() -> bytes:
    settings = etree.Element(_w("settings"), nsmap={"w": W})
    _sub(settings, _w("zoom"), percent="100")
    _sub(settings, _w("defaultTabStop"), val="420")
    _sub(
        settings,
        _w("characterSpacingControl"),
        val="compressPunctuation",
    )
    compat = _sub(settings, _w("compat"))
    _sub(compat, _w("adjustLineHeightInTable"))
    _sub(
        compat,
        _w("compatSetting"),
        name="compatibilityMode",
        uri="http://schemas.microsoft.com/office/word",
        val="15",
    )
    return etree.tostring(
        settings,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
    )


def _font_table_xml() -> bytes:
    fonts = etree.Element(_w("fonts"), nsmap={"w": W})
    _sub(fonts, _w("font"), name=_FONT)
    return etree.tostring(
        fonts,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
    )


def _content_types_xml() -> bytes:
    types = etree.Element(
        _q(CT, "Types"), nsmap={None: CT}
    )
    for extension, content_type in (
        ("rels", "application/vnd.openxmlformats-package.relationships+xml"),
        ("xml", "application/xml"),
    ):
        etree.SubElement(
            types,
            _q(CT, "Default"),
            Extension=extension,
            ContentType=content_type,
        )
    for part, content_type in (
        (
            "/word/document.xml",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
        ),
        (
            "/word/styles.xml",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml",
        ),
        (
            "/word/settings.xml",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml",
        ),
        (
            "/word/fontTable.xml",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.fontTable+xml",
        ),
        (
            "/docProps/core.xml",
            "application/vnd.openxmlformats-package.core-properties+xml",
        ),
        (
            "/docProps/app.xml",
            "application/vnd.openxmlformats-officedocument.extended-properties+xml",
        ),
    ):
        etree.SubElement(
            types,
            _q(CT, "Override"),
            PartName=part,
            ContentType=content_type,
        )
    return etree.tostring(
        types,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
    )


def _package_rels_xml() -> bytes:
    rels = etree.Element(
        _q(PKG_REL, "Relationships"), nsmap={None: PKG_REL}
    )
    for rel_id, rel_type, target in (
        (
            "rId1",
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
            "word/document.xml",
        ),
        (
            "rId2",
            "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties",
            "docProps/core.xml",
        ),
        (
            "rId3",
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties",
            "docProps/app.xml",
        ),
    ):
        etree.SubElement(
            rels,
            _q(PKG_REL, "Relationship"),
            Id=rel_id,
            Type=rel_type,
            Target=target,
        )
    return etree.tostring(
        rels,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
    )


def _document_rels_xml() -> bytes:
    rels = etree.Element(
        _q(PKG_REL, "Relationships"), nsmap={None: PKG_REL}
    )
    for rel_id, rel_type, target in (
        (
            "rId1",
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles",
            "styles.xml",
        ),
        (
            "rId2",
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings",
            "settings.xml",
        ),
        (
            "rId3",
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/fontTable",
            "fontTable.xml",
        ),
    ):
        etree.SubElement(
            rels,
            _q(PKG_REL, "Relationship"),
            Id=rel_id,
            Type=rel_type,
            Target=target,
        )
    return etree.tostring(
        rels,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
    )


def _core_xml() -> bytes:
    core = etree.Element(
        _q(CP, "coreProperties"),
        nsmap={
            "cp": CP,
            "dc": DC,
            "dcterms": DCTERMS,
            "xsi": XSI,
        },
    )
    etree.SubElement(core, _q(DC, "title")).text = "课程审议记录表"
    etree.SubElement(core, _q(DC, "creator")).text = "Kindergarten Manager"
    etree.SubElement(core, _q(CP, "lastModifiedBy")).text = (
        "Kindergarten Manager"
    )
    return etree.tostring(
        core,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
    )


def _app_xml() -> bytes:
    app = etree.Element(
        _q(EP, "Properties"), nsmap={None: EP, "vt": VT}
    )
    etree.SubElement(app, _q(EP, "Application")).text = (
        "Kindergarten Manager"
    )
    return etree.tostring(
        app,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
    )


def render_curriculum_docx(content: Mapping[str, Any]) -> bytes:
    """Return a complete editable DOCX for one saved content object."""
    parts = {
        "[Content_Types].xml": _content_types_xml(),
        "_rels/.rels": _package_rels_xml(),
        "docProps/core.xml": _core_xml(),
        "docProps/app.xml": _app_xml(),
        "word/document.xml": _document_xml(content),
        "word/_rels/document.xml.rels": _document_rels_xml(),
        "word/styles.xml": _styles_xml(),
        "word/settings.xml": _settings_xml(),
        "word/fontTable.xml": _font_table_xml(),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(
        buffer, "w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        for name, payload in parts.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


# Alias kept for callers that use "build" terminology.
build_curriculum_docx = render_curriculum_docx

__all__ = [
    "build_curriculum_docx",
    "render_curriculum_docx",
]
