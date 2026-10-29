"""Game observation DOCX generator (pure: frozen snapshot -> DOCX bytes).

Uses the three user-supplied blank templates (A4 portrait, six-column, eight
business rows) copied into the controlled asset directory.  The generator
never reads the database, the current draft, AI state or a filesystem path
outside the verified template/image bytes passed by the export service.

The template text cells are cleared at build time; only fixed labels remain in
the asset.  All child names, dates, counts, four columns, five domains and
photos come from the frozen snapshot.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
XML = "http://www.w3.org/XML/1998/namespace"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
IMAGE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "assets" / "word_templates"
TEMPLATES = {
    "public": (
        "observation_public.docx",
        "b2c17dd95f6bbea0acd5888695bb2b97813a32b4cb414456f1955f269f19ab46",
    ),
    "indoor": (
        "observation_indoor.docx",
        "32f396333f2a96e2eddf1880c0e02e5888c13b95f7f11f70b7b36a96ac722cb5",
    ),
    "outdoor": (
        "observation_outdoor.docx",
        "43b56ab506f56297689ed1edf21d29dfd810df41bfdc7719a3373d2a6c86c74d",
    ),
}
TYPE_LABELS = {"public": "公共", "indoor": "室内", "outdoor": "户外"}

EMU_PER_TWIP = 635
# OOXML's default table cell left/right margin when the template has no
# explicit tblCellMar/tcMar.  The value-cell budget is derived from the
# template grid/tcW, not a hard-coded page width.
DEFAULT_CELL_MARGIN_TWIPS = 108
PHOTO_GROUP_GAP_TWIPS = 120
MAX_IMAGE_HEIGHT_EMU = 6_500 * EMU_PER_TWIP


class ObservationWordError(Exception):
    code = "OBS_EXPORT_GENERATION_FAILED"


class ObservationWordTemplateError(ObservationWordError):
    code = "OBS_EXPORT_TEMPLATE_INVALID"


@dataclass(frozen=True)
class ObservationWordPhoto:
    data: bytes
    width: int
    height: int
    content_hash: str


@dataclass(frozen=True)
class ObservationWordRecord:
    payload: dict
    photos: tuple[ObservationWordPhoto, ...]


def _w(tag: str) -> str:
    return f"{{{W}}}{tag}"


def _qn(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def _read_template(record_type: str) -> bytes:
    name, expected = TEMPLATES[record_type]
    path = TEMPLATE_DIR / name
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ObservationWordTemplateError("观察 Word 模板不可用") from exc
    if hashlib.sha256(data).hexdigest() != expected:
        raise ObservationWordTemplateError("观察 Word 模板摘要不一致")
    return data


def _parse(data: bytes):
    try:
        return etree.fromstring(data)
    except etree.XMLSyntaxError as exc:
        raise ObservationWordTemplateError("观察 Word 模板 XML 损坏") from exc


def _clear_paragraph(paragraph) -> None:
    for child in list(paragraph):
        if child.tag != _w("pPr"):
            paragraph.remove(child)


def _run_props(size_half_points: int, *, bold: bool = False):
    rpr = etree.Element(_w("rPr"))
    fonts = etree.SubElement(rpr, _w("rFonts"))
    fonts.set(_w("ascii"), "宋体")
    fonts.set(_w("eastAsia"), "宋体")
    fonts.set(_w("hAnsi"), "宋体")
    if bold:
        etree.SubElement(rpr, _w("b"))
    size = etree.SubElement(rpr, _w("sz"))
    size.set(_w("val"), str(size_half_points))
    size_cs = etree.SubElement(rpr, _w("szCs"))
    size_cs.set(_w("val"), str(size_half_points))
    return rpr


def _add_text(paragraph, text: str, *, size: int = 22, bold: bool = False) -> None:
    run = etree.SubElement(paragraph, _w("r"))
    run.append(_run_props(size, bold=bold))
    parts = str(text).split("\n")
    for index, part in enumerate(parts):
        if index:
            etree.SubElement(run, _w("br"))
        node = etree.SubElement(run, _w("t"))
        node.set(_qn(XML, "space"), "preserve")
        node.text = part


def _set_cell_text(cell, text: str, *, size: int = 22, bold: bool = False) -> None:
    paragraphs = cell.findall(_w("p"))
    if not paragraphs:
        paragraphs = [etree.SubElement(cell, _w("p"))]
    paragraph = paragraphs[0]
    _clear_paragraph(paragraph)
    for extra in paragraphs[1:]:
        cell.remove(extra)
    if str(text):
        _add_text(paragraph, str(text), size=size, bold=bold)


def _set_title(root, title: str) -> None:
    body = root.find(_w("body"))
    first = body.find(_w("p"))
    if first is None:
        first = etree.SubElement(body, _w("p"))
    ppr = first.find(_w("pPr"))
    if ppr is None:
        ppr = etree.Element(_w("pPr"))
        first.insert(0, ppr)
    jc = ppr.find(_w("jc"))
    if jc is None:
        jc = etree.SubElement(ppr, _w("jc"))
    jc.set(_w("val"), "center")
    _clear_paragraph(first)
    _add_text(first, title, size=32, bold=True)


def _date_text(payload: dict) -> str:
    value = payload.get("observation_date")
    return str(value) if value else ""


def _time_text(payload: dict) -> str:
    start = payload.get("start_time") or ""
    end = payload.get("end_time") or ""
    if start and end:
        return f"{start}-{end}"
    return str(start or end or "")


def _count_text(value) -> str:
    return "" if value is None else str(value)


def _age_text(value) -> str:
    return "" if value is None else f"{value}岁"


def _subjects_text(payload: dict) -> str:
    subjects = payload.get("subjects") or []
    return "、".join(
        str(item.get("name"))
        for item in subjects
        if isinstance(item, dict) and item.get("name")
    )


def _evaluation_text(payload: dict) -> str:
    evaluation = payload.get("analysis_evaluation") or {}
    labels = (
        ("health", "健康"),
        ("language", "语言"),
        ("social", "社会"),
        ("science", "科学"),
        ("arts", "艺术"),
    )
    return "\n".join(
        f"{label}：{str(evaluation.get(key) or '')}" for key, label in labels
    )


def _fill_table(table, payload: dict) -> None:
    rows = table.findall(_w("tr"))
    if len(rows) != 8:
        raise ObservationWordTemplateError("观察 Word 模板行数不一致")
    cells = [row.findall(_w("tc")) for row in rows]
    if (
        any(len(row) != 6 for row in cells[:2])
        or any(len(row) != 4 for row in cells[2:3])
        or any(len(row) != 2 for row in cells[3:])
    ):
        raise ObservationWordTemplateError("观察 Word 模板单元格结构不一致")
    _set_cell_text(cells[0][1], str(payload.get("class_name") or ""))
    _set_cell_text(cells[0][3], _date_text(payload))
    _set_cell_text(cells[0][5], _time_text(payload))
    _set_cell_text(cells[1][1], _count_text(payload.get("adult_count")))
    _set_cell_text(cells[1][3], _count_text(payload.get("child_count")))
    _set_cell_text(cells[1][5], str(payload.get("observer_name") or ""))
    _set_cell_text(cells[2][1], _subjects_text(payload))
    _set_cell_text(cells[2][3], _age_text(payload.get("age_years")))
    _set_cell_text(cells[3][1], str(payload.get("environment") or ""))
    _set_cell_text(cells[4][1], str(payload.get("observation_goal") or ""), size=24)
    _set_cell_text(cells[5][1], str(payload.get("observation_process") or ""), size=24)
    _set_cell_text(cells[6][1], _evaluation_text(payload), size=24)
    _set_cell_text(cells[7][1], str(payload.get("support_strategy") or ""), size=24)


def _image_run(rid: str, cx: int, cy: int, image_id: int):
    """One run carrying exactly one inline drawing.

    The caller owns the surrounding ``w:p``: an inline image must be a run
    child, never a paragraph child (``w:p/w:p`` is not valid WordprocessingML
    and Word may silently drop the picture).
    """
    run = etree.Element(_w("r"))
    drawing = etree.SubElement(run, _w("drawing"))
    inline = etree.SubElement(drawing, _qn(WP, "inline"))
    for attr in ("distT", "distB", "distL", "distR"):
        inline.set(attr, "0")
    extent = etree.SubElement(inline, _qn(WP, "extent"))
    extent.set("cx", str(cx))
    extent.set("cy", str(cy))
    doc_pr = etree.SubElement(inline, _qn(WP, "docPr"))
    doc_pr.set("id", str(image_id))
    doc_pr.set("name", f"observation image {image_id}")
    graphic = etree.SubElement(inline, _qn(A, "graphic"))
    graphic_data = etree.SubElement(graphic, _qn(A, "graphicData"))
    graphic_data.set("uri", "http://schemas.openxmlformats.org/drawingml/2006/picture")
    pic = etree.SubElement(graphic_data, _qn(PIC, "pic"))
    nv = etree.SubElement(pic, _qn(PIC, "nvPicPr"))
    cnv = etree.SubElement(nv, _qn(PIC, "cNvPr"))
    cnv.set("id", str(image_id))
    cnv.set("name", f"observation image {image_id}")
    etree.SubElement(nv, _qn(PIC, "cNvPicPr"))
    blip_fill = etree.SubElement(pic, _qn(PIC, "blipFill"))
    blip = etree.SubElement(blip_fill, _qn(A, "blip"))
    blip.set(_qn(R, "embed"), rid)
    stretch = etree.SubElement(blip_fill, _qn(A, "stretch"))
    etree.SubElement(stretch, _qn(A, "fillRect"))
    sp_pr = etree.SubElement(pic, _qn(PIC, "spPr"))
    xfrm = etree.SubElement(sp_pr, _qn(A, "xfrm"))
    off = etree.SubElement(xfrm, _qn(A, "off"))
    off.set("x", "0")
    off.set("y", "0")
    ext = etree.SubElement(xfrm, _qn(A, "ext"))
    ext.set("cx", str(cx))
    ext.set("cy", str(cy))
    geom = etree.SubElement(sp_pr, _qn(A, "prstGeom"))
    geom.set("prst", "rect")
    etree.SubElement(geom, _qn(A, "avLst"))
    return run


def _scaled_size(width: int, height: int, max_width: int) -> tuple[int, int]:
    if width <= 0 or height <= 0:
        raise ObservationWordError("观察照片尺寸无效")
    scale = min(max_width / width, MAX_IMAGE_HEIGHT_EMU / height)
    return max(1, int(width * scale)), max(1, int(height * scale))


def _twips(node) -> int | None:
    if node is None:
        return None
    value = node.get(_w("w"))
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _value_cell_available_twips(table) -> int:
    """Available value-cell width from the controlled template itself.

    The value cell spans columns 2-6; its tcW (or the grid sum) includes the
    cell margins, so subtract explicit/default left/right cell margins and any
    paragraph indents.  Two-photo groups additionally reserve a small gap.
    """
    rows = table.findall(_w("tr"))
    if len(rows) < 6:
        raise ObservationWordTemplateError("观察 Word 模板行数不一致")
    cells = rows[5].findall(_w("tc"))
    if len(cells) != 2:
        raise ObservationWordTemplateError("观察 Word 模板观察记录结构不一致")
    value_cell = cells[1]
    tcw = value_cell.find(_w("tcPr") + "/" + _w("tcW"))
    width = _twips(tcw)
    if width is None:
        grid = table.find(_w("tblGrid"))
        columns = grid.findall(_w("gridCol")) if grid is not None else []
        widths = [_twips(column) for column in columns]
        span_node = value_cell.find(_w("tcPr") + "/" + _w("gridSpan"))
        span = int(span_node.get(_w("val"))) if span_node is not None else 5
        width = sum(item or 0 for item in widths[1 : 1 + span])
    if not width or width <= 0:
        raise ObservationWordTemplateError("观察 Word 模板值列宽度无效")
    margins = value_cell.find(_w("tcPr") + "/" + _w("tcMar"))
    if margins is None:
        margins = table.find(_w("tblPr") + "/" + _w("tblCellMar"))
    left = _twips(margins.find(_w("left"))) if margins is not None else None
    right = _twips(margins.find(_w("right"))) if margins is not None else None
    left = DEFAULT_CELL_MARGIN_TWIPS if left is None else left
    right = DEFAULT_CELL_MARGIN_TWIPS if right is None else right
    indent_left = 0
    indent_right = 0
    for paragraph in value_cell.findall(_w("p")):
        indent = paragraph.find(_w("pPr") + "/" + _w("ind"))
        if indent is None:
            continue
        indent_left = max(indent_left, _twips(indent.find(_w("left"))) or 0)
        indent_right = max(indent_right, _twips(indent.find(_w("right"))) or 0)
    available = width - left - right - indent_left - indent_right
    if available < 1_000:
        raise ObservationWordTemplateError("观察 Word 模板值列可用宽度不足")
    return available


def _append_photos(
    cell,
    photos: tuple[ObservationWordPhoto, ...],
    media,
    rels,
    image_state,
    available_twips: int,
) -> None:
    """Append one centered paragraph per group of at most two inline photos.

    Every picture is its own ``w:r/w:drawing/wp:inline`` run inside the same
    group paragraph. Repeated bytes reuse one media part/relationship but get
    a fresh, globally unique ``wp:docPr``/``pic:cNvPr`` id.
    """
    if not photos:
        return
    groups = [photos[index : index + 2] for index in range(0, len(photos), 2)]
    for group in groups:
        p = etree.Element(_w("p"))
        ppr = etree.SubElement(p, _w("pPr"))
        etree.SubElement(ppr, _w("jc")).set(_w("val"), "center")
        for photo in group:
            digest = hashlib.sha256(photo.data).hexdigest()
            media_name = f"observation_{digest[:24]}.jpg"
            media[media_name] = photo.data
            if digest not in rels:
                rels[digest] = f"rIdObservation{len(rels) + 100}"
            if len(group) == 1:
                max_width = available_twips * EMU_PER_TWIP
            else:
                budget = max(1_000, available_twips - PHOTO_GROUP_GAP_TWIPS)
                max_width = (budget // 2) * EMU_PER_TWIP
            cx, cy = _scaled_size(photo.width, photo.height, max_width)
            image_id = image_state["next_id"]
            image_state["next_id"] += 1
            p.append(_image_run(rels[digest], cx, cy, image_id))
        cell.append(p)


def _build_document(record_type: str, records: tuple[ObservationWordRecord, ...]) -> bytes:
    template = _read_template(record_type)
    with zipfile.ZipFile(io.BytesIO(template)) as zin:
        members = {info.filename: zin.read(info.filename) for info in zin.infolist()}
    media: dict[str, bytes] = {}
    rels: dict[str, str] = {}
    image_state = {"next_id": 1}
    body_out = etree.Element(_w("body"))
    root0 = _parse(members["word/document.xml"])
    body0 = root0.find(_w("body"))
    sect = body0.find(_w("sectPr")) if body0 is not None else None
    for index, record in enumerate(records):
        root = _parse(members["word/document.xml"])
        body = root.find(_w("body"))
        title = body.find(_w("p"))
        table = body.find(_w("tbl"))
        if title is None or table is None:
            raise ObservationWordTemplateError("观察 Word 模板缺少标题或表格")
        school = str(record.payload.get("school_name") or "")
        record_type_label = TYPE_LABELS.get(
            str(record.payload.get("record_type") or ""), ""
        )
        _set_title(root, f"{school}游戏观察记录（{record_type_label}）")
        _fill_table(table, record.payload)
        if index:
            ppr = title.find(_w("pPr"))
            if ppr is None:
                ppr = etree.Element(_w("pPr"))
                title.insert(0, ppr)
            if ppr.find(_w("pageBreakBefore")) is None:
                etree.SubElement(ppr, _w("pageBreakBefore"))
        _append_photos(
            table.findall(_w("tr"))[5].findall(_w("tc"))[1],
            record.photos,
            media,
            rels,
            image_state,
            _value_cell_available_twips(table),
        )
        body_out.append(title)
        body_out.append(table)
    if sect is not None:
        body_out.append(etree.fromstring(etree.tostring(sect)))
    root_out = etree.Element(_w("document"), nsmap=root0.nsmap)
    root_out.append(body_out)
    members["word/document.xml"] = etree.tostring(
        root_out, xml_declaration=True, encoding="UTF-8", standalone=True
    )
    if media:
        rels_root = etree.fromstring(members["word/_rels/document.xml.rels"])
        for digest, rid in rels.items():
            rel = etree.SubElement(rels_root, _qn(PKG_REL, "Relationship"))
            rel.set("Id", rid)
            rel.set("Type", IMAGE_REL)
            rel.set("Target", f"media/observation_{digest[:24]}.jpg")
        members["word/_rels/document.xml.rels"] = etree.tostring(
            rels_root, xml_declaration=True, encoding="UTF-8", standalone=True
        )
        content = etree.fromstring(members["[Content_Types].xml"])
        if not any(
            node.get("Extension", "").lower() == "jpg"
            for node in content.findall(_qn(CT, "Default"))
        ):
            default = etree.SubElement(content, _qn(CT, "Default"))
            default.set("Extension", "jpg")
            default.set("ContentType", "image/jpeg")
        members["[Content_Types].xml"] = etree.tostring(
            content, xml_declaration=True, encoding="UTF-8", standalone=True
        )
        for name, data in media.items():
            members[f"word/media/{name}"] = data
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in members.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            zout.writestr(info, data)
    return out.getvalue()


def generate_observation_export_docx(
    records: tuple[ObservationWordRecord, ...]
) -> bytes:
    if not records:
        raise ObservationWordError("没有可导出的观察记录")
    first_type = str(records[0].payload.get("record_type") or "")
    if first_type not in TEMPLATES:
        raise ObservationWordError("观察记录类型无效")
    # All three blank templates share the same eight-row/six-grid structure and
    # differ only in the title suffix; one package can carry mixed record types
    # with each record's own title.
    return _build_document(first_type, records)
