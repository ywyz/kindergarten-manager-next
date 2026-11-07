"""Pure one-to-one listening DOCX generator (frozen payload + bytes only).

The generator never reads the database, current draft, AI candidates or a
filesystem path outside the controlled template/image bytes passed by the
export service.  Each unit carries the exact L1 controlled v1 DOCX bytes and
SHA-256 registered on the record; the full ZIP is verified before
``word/document.xml`` is read.

Tables, grids, cell widths, merges, row heights, page size and margins remain
the template's own.  The accepted L3 engineering decision for these controlled
bytes allows one shared section property plus a page break before each later
unit, provided every unit's section/docDefaults/table styles are verified
equivalent at generation time.  Incompatible template bytes are refused rather
than silently merged.
"""

from __future__ import annotations

import copy
import hashlib
import io
import re
import zipfile
from dataclasses import dataclass
from typing import Any, Iterable

from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
XML = "http://www.w3.org/XML/1998/namespace"
IMAGE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"

EMU_PER_TWIP = 635
EMU_PER_PIXEL = 9_525
DEFAULT_CELL_MARGIN_TWIPS = 108
MAX_IMAGE_HEIGHT_EMU = 6_500 * EMU_PER_TWIP
MAX_PACKAGE_BYTES = 40 * 1024 * 1024

GRADE_LABELS = {"small": "小班", "middle": "中班", "large": "大班"}
_REQUIRED_PARTS = (
    "[Content_Types].xml",
    "word/document.xml",
    "word/_rels/document.xml.rels",
    "word/styles.xml",
    "word/settings.xml",
    "word/fontTable.xml",
)
_MIME_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/bmp": "bmp",
    "image/webp": "webp",
}
_EXTENSION_CONTENT_TYPES = {
    "jpg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "webp": "image/webp",
}

# OOXML child order for the properties this generator touches.  Word accepts
# several orders in practice, but keeping the schema order avoids invalid
# documents after cloning template run/paragraph properties.
_RPR_ORDER = (
    "rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps",
    "strike", "dstrike", "outline", "shadow", "emboss", "imprint",
    "noProof", "snapToGrid", "vanish", "webHidden", "color", "spacing",
    "w", "kern", "position", "sz", "szCs", "highlight", "u", "effect",
    "bdr", "shd", "fitText", "vertAlign", "rtl", "cs", "em", "lang",
    "eastAsianLayout", "specVanish", "oMath", "rPrChange",
)
_PPR_ORDER = (
    "pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr",
    "widowControl", "numPr", "suppressLineNumbers", "pBdr", "shd", "tabs",
    "suppressAutoHyphens", "kinsoku", "wordWrap", "overflowPunct",
    "topLinePunct", "autoSpaceDE", "autoSpaceDN", "bidi", "adjustRightInd",
    "snapToGrid", "spacing", "ind", "contextualSpacing", "mirrorIndents",
    "suppressOverlap", "jc", "textDirection", "textAlignment",
    "textboxTightWrap", "outlineLvl", "divId", "cnfStyle", "rPr", "sectPr",
    "pPrChange",
)


class ListeningWordError(Exception):
    pass


def _q(uri: str, tag: str) -> str:
    return f"{{{uri}}}{tag}"


def _w(tag: str) -> str:
    return _q(W, tag)


def _local(tag: Any) -> str:
    try:
        return etree.QName(tag).localname
    except (TypeError, ValueError):
        return ""


def _canonical_children(parent, order: tuple[str, ...]) -> None:
    rank = {name: index for index, name in enumerate(order)}
    children = list(parent)
    indexed = list(enumerate(children))
    indexed.sort(
        key=lambda item: (
            rank.get(_local(item[1].tag), len(order)),
            item[0],
        )
    )
    for child in children:
        parent.remove(child)
    for _index, child in indexed:
        parent.append(child)


def _canonical_rpr(rpr) -> None:
    _canonical_children(rpr, _RPR_ORDER)


def _canonical_ppr(ppr) -> None:
    _canonical_children(ppr, _PPR_ORDER)


def _parse_xml(data: bytes, label: str):
    try:
        return etree.fromstring(data)
    except Exception as exc:  # noqa: BLE001 - template refusal
        raise ListeningWordError(f"{label} XML 无法解析") from exc


def _paragraph_text(paragraph) -> str:
    return "".join((node.text or "") for node in paragraph.iter(_w("t")))


def _cell_text(cell) -> str:
    return "".join((node.text or "") for node in cell.iter(_w("t")))


def _compact(value: str) -> str:
    return "".join(value.split())


def _strip_rsid(value):
    for node in list(value.iter()):
        if _local(node.tag).lower().startswith("rsid"):
            parent = node.getparent()
            if parent is not None:
                parent.remove(node)
            continue
        for name in list(node.attrib):
            if _local(name).lower().startswith("rsid"):
                del node.attrib[name]
    return value


def _signature(element) -> bytes:
    return etree.tostring(_strip_rsid(copy.deepcopy(element)), method="c14n")


def _zip_members(unit: "ListeningWordUnit") -> dict[str, bytes]:
    payload = bytes(unit.template_bytes)
    if hashlib.sha256(payload).hexdigest() != unit.template_sha256:
        raise ListeningWordError("Word 模板散列不一致")
    if not payload or len(payload) > MAX_PACKAGE_BYTES:
        raise ListeningWordError("Word 模板大小不受支持")
    if not zipfile.is_zipfile(io.BytesIO(payload)):
        raise ListeningWordError("Word 模板不是有效的 DOCX 包")
    members: dict[str, bytes] = {}
    total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            for info in archive.infolist():
                name = info.filename
                parts = name.rstrip("/").split("/") if name else []
                if (
                    not name
                    or name.startswith("/")
                    or "\\" in name
                    or not parts
                    or any(part in ("", ".", "..") for part in parts)
                ):
                    raise ListeningWordError("Word 模板包内路径不合法")
                if name in members:
                    raise ListeningWordError("Word 模板包内条目重复")
                data = archive.read(info.filename)
                total += len(data)
                if total > MAX_PACKAGE_BYTES:
                    raise ListeningWordError("Word 模板解压后过大")
                members[name] = data
    except zipfile.BadZipFile as exc:
        raise ListeningWordError("Word 模板不是有效的 DOCX 包") from exc
    missing = [name for name in _REQUIRED_PARTS if name not in members]
    if missing:
        raise ListeningWordError("Word 模板缺少必要部件")
    return members


def _document_parts(members: dict[str, bytes]):
    root = _parse_xml(members["word/document.xml"], "Word 模板主文档")
    body = root.find(_w("body"))
    if body is None:
        raise ListeningWordError("Word 模板缺少 body")
    children = list(body)
    tags = [_local(child.tag) for child in children]
    if tags != ["p", "tbl", "p", "sectPr"]:
        raise ListeningWordError("Word 模板 body 结构不一致")
    title, table, trailer, sect = children
    if _paragraph_text(trailer).strip():
        raise ListeningWordError("Word 模板表后段落结构不一致")
    return root, body, title, table, trailer, sect


def _sect_signature(sect) -> bytes:
    return _signature(sect)


def _styles_signature(members: dict[str, bytes]) -> bytes:
    root = _parse_xml(members["word/styles.xml"], "Word 模板样式")
    defaults = root.find(_w("docDefaults"))
    styles = {
        style.get(_w("styleId")): style
        for style in root.findall(_w("style"))
    }
    if defaults is None:
        raise ListeningWordError("Word 模板缺少 docDefaults")
    for needed in ("2", "3"):
        if needed not in styles:
            raise ListeningWordError("Word 模板缺少受控表格样式")
    payload = [_signature(defaults)]
    for needed in ("2", "3"):
        style = copy.deepcopy(styles[needed])
        for node in list(style.iter()):
            if _local(node.tag) == "qFormat":
                parent = node.getparent()
                if parent is not None:
                    parent.remove(node)
        payload.append(_signature(style))
    return b"\x00".join(payload)


def _settings_signature(members: dict[str, bytes]) -> bytes:
    root = _parse_xml(members["word/settings.xml"], "Word 模板设置")
    return _signature(root)


def _used_fonts(document) -> set[str]:
    fonts: set[str] = set()
    for node in document.iter(_w("rFonts")):
        for key in ("ascii", "hAnsi", "eastAsia", "cs"):
            value = node.get(_w(key))
            if value:
                fonts.add(value)
    return fonts


def _font_table_names(members: dict[str, bytes]) -> set[str]:
    root = _parse_xml(members["word/fontTable.xml"], "Word 模板字体表")
    return {
        node.get(_w("name"))
        for node in root.findall(_w("font"))
        if node.get(_w("name"))
    }


def _font_table_entries(members: dict[str, bytes]) -> dict[str, Any]:
    root = _parse_xml(members["word/fontTable.xml"], "Word 模板字体表")
    return {
        node.get(_w("name")): node
        for node in root.findall(_w("font"))
        if node.get(_w("name"))
    }


def _reject_unit_relationships(document, members: dict[str, bytes]) -> None:
    for node in document.iter():
        if _local(node.tag) in ("headerReference", "footerReference"):
            raise ListeningWordError("Word 模板包含未合并的页眉页脚引用")
        if _local(node.tag) in ("drawing", "pict", "object", "altChunk"):
            raise ListeningWordError("Word 模板包含未合并的嵌入对象或图片")
        for name in node.attrib:
            if etree.QName(name).namespace == R:
                raise ListeningWordError("Word 模板包含未合并的关系引用")
    for name in members:
        if name.startswith("word/media/") or name.startswith("word/embeddings/"):
            raise ListeningWordError("Word 模板包包含未合并的媒体附件")


def _clone_rpr(source) -> Any:
    if source is None:
        return etree.Element(_w("rPr"))
    return copy.deepcopy(source)


def _ensure(parent, tag: str, *, first: bool = False):
    node = parent.find(_w(tag))
    if node is not None:
        return node
    node = etree.Element(_w(tag))
    if first:
        parent.insert(0, node)
    else:
        parent.append(node)
    return node


def _set_black(rpr) -> None:
    color = _ensure(rpr, "color")
    for key in list(color.attrib):
        del color.attrib[key]
    color.set(_w("val"), "000000")
    _remove_theme_colors(rpr)
    _canonical_rpr(rpr)


def _remove_theme_colors(rpr) -> None:
    for node in rpr.iter():
        for name in list(node.attrib):
            if _local(name).lower().startswith("theme"):
                del node.attrib[name]


def _remove_properties(rpr, names: Iterable[str]) -> None:
    for name in names:
        node = rpr.find(_w(name))
        if node is not None:
            rpr.remove(node)


def _set_songti_12_regular(rpr) -> None:
    fonts = _ensure(rpr, "rFonts", first=True)
    for key in ("ascii", "hAnsi", "eastAsia", "cs"):
        fonts.set(_w(key), "宋体")
    for name in ("b", "bCs"):
        node = _ensure(rpr, name)
        node.set(_w("val"), "0")
    for name in ("sz", "szCs"):
        node = _ensure(rpr, name)
        node.set(_w("val"), "24")
    _remove_properties(
        rpr,
        (
            "i", "iCs", "caps", "smallCaps", "strike", "dstrike",
            "outline", "shadow", "emboss", "imprint", "u",
        ),
    )
    _set_black(rpr)


def _set_underline(rpr) -> None:
    node = _ensure(rpr, "u")
    for key in list(node.attrib):
        del node.attrib[key]
    node.set(_w("val"), "single")
    node.set(_w("color"), "000000")
    _canonical_rpr(rpr)


def _base_rpr(paragraph):
    run = paragraph.find(_w("r"))
    if run is not None:
        rpr = run.find(_w("rPr"))
        if rpr is not None:
            return copy.deepcopy(rpr)
    ppr = paragraph.find(_w("pPr"))
    if ppr is not None:
        rpr = ppr.find(_w("rPr"))
        if rpr is not None:
            return copy.deepcopy(rpr)
    return None


def _make_run(text: str, rpr) -> Any:
    run = etree.Element(_w("r"))
    if rpr is not None:
        run.append(copy.deepcopy(rpr))
    node = etree.SubElement(run, _w("t"))
    if text.startswith(" ") or text.endswith(" ") or "\n" in text:
        node.set(_q(XML, "space"), "preserve")
    node.text = text
    return run


def _clear_content(paragraph) -> None:
    for child in list(paragraph):
        if _local(child.tag) != "pPr":
            paragraph.remove(child)


def _write_paragraph(
    paragraph,
    text: str,
    rpr,
    *,
    paragraph_mark: bool = True,
) -> None:
    ppr = paragraph.find(_w("pPr"))
    if ppr is None:
        ppr = etree.Element(_w("pPr"))
        paragraph.insert(0, ppr)
    prepared = _clone_rpr(rpr)
    _canonical_rpr(prepared)
    if paragraph_mark:
        current = ppr.find(_w("rPr"))
        cloned = copy.deepcopy(prepared)
        if current is not None:
            ppr.replace(current, cloned)
        else:
            ppr.append(cloned)
        _canonical_ppr(ppr)
    _clear_content(paragraph)
    value = "" if text is None else str(text)
    if not value:
        return
    lines = value.split("\n")
    for index, line in enumerate(lines):
        if index:
            break_run = etree.SubElement(paragraph, _w("r"))
            if prepared is not None:
                break_run.append(copy.deepcopy(prepared))
            etree.SubElement(break_run, _w("br"))
        paragraph.append(_make_run(line, prepared))


def _ensure_paragraphs(cell, count: int) -> list[Any]:
    paragraphs = cell.findall(_w("p"))
    if not paragraphs:
        paragraphs = [etree.SubElement(cell, _w("p"))]
    while len(paragraphs) < count:
        extra = etree.Element(_w("p"))
        ppr = paragraphs[0].find(_w("pPr"))
        if ppr is not None:
            extra.append(copy.deepcopy(ppr))
        cell.append(extra)
        paragraphs.append(extra)
    return paragraphs


def _write_cell_lines(cell, text: str) -> None:
    value = "" if text is None else str(text)
    lines = value.split("\n") if value else [""]
    paragraphs = _ensure_paragraphs(cell, len(lines))
    base = _base_rpr(paragraphs[0])
    for index, paragraph in enumerate(paragraphs):
        rpr = _clone_rpr(base)
        _set_songti_12_regular(rpr)
        line = lines[index] if index < len(lines) else ""
        _write_paragraph(paragraph, line, rpr)


def _set_title(body, unit: "ListeningWordUnit") -> Any:
    title = body.find(_w("p"))
    if title is None:
        raise ListeningWordError("Word 模板缺少标题")
    text = _paragraph_text(title)
    grade_label = GRADE_LABELS.get(unit.grade)
    if grade_label is None:
        raise ListeningWordError("Word 模板年级不合法")
    if "的发展评价" not in text or "_" not in text:
        raise ListeningWordError("Word 模板标题结构不一致")
    prefix = text.split("的发展评价", 1)[0]
    prefix = re.split(r"_+", prefix, maxsplit=1)[0].rstrip()
    if not prefix.endswith(f"{grade_label}幼儿"):
        raise ListeningWordError("Word 模板年级与记录不一致")
    suffix = "的发展评价"
    base = _base_rpr(title)
    if base is None:
        base = etree.Element(_w("rPr"))
    _remove_properties(base, ("u",))
    _set_black(base)
    middle = _clone_rpr(base)
    _set_underline(middle)
    _clear_content(title)
    title.append(_make_run(prefix, base))
    title.append(_make_run(f"    {unit.domain_label}领域     ", middle))
    title.append(_make_run(suffix, base))
    return title


_HEADER_LABELS = (
    "观察日期：",
    "幼儿姓名：",
    "成人数目：",
    "幼儿年龄：",
    "目标：",
    "观察区域：",
)


def _fill_header(table, unit: "ListeningWordUnit") -> None:
    rows = table.findall(_w("tr"))
    if not rows:
        raise ListeningWordError("Word 模板缺少表头")
    cells = rows[0].findall(_w("tc"))
    if len(cells) != 1:
        raise ListeningWordError("Word 模板表头结构不一致")
    values = (
        unit.observation_date,
        unit.child_name,
        unit.adult_count,
        unit.child_age,
        unit.goal,
        unit.observation_area,
    )
    paragraphs = cells[0].findall(_w("p"))
    if len(paragraphs) != len(_HEADER_LABELS):
        raise ListeningWordError("Word 模板表头栏目数量不一致")
    for paragraph, label, value in zip(paragraphs, _HEADER_LABELS, values):
        text = _paragraph_text(paragraph)
        if not text.startswith(label):
            raise ListeningWordError("Word 模板表头栏目顺序不一致")
        cleaned = "" if value is None else str(value).replace("\r\n", " ")
        cleaned = cleaned.replace("\r", " ").replace("\n", " ")
        rpr = _clone_rpr(_base_rpr(paragraph))
        _set_songti_12_regular(rpr)
        _write_paragraph(paragraph, label + cleaned, rpr)


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


def _cell_available_emu(cell) -> int:
    tcw = cell.find(_w("tcPr") + "/" + _w("tcW"))
    width = _twips(tcw)
    if not width or width <= 0:
        raise ListeningWordError("Word 模板图片单元格宽度无效")
    margins = cell.find(_w("tcPr") + "/" + _w("tcMar"))
    left = _twips(margins.find(_w("left"))) if margins is not None else None
    right = _twips(margins.find(_w("right"))) if margins is not None else None
    left = DEFAULT_CELL_MARGIN_TWIPS if left is None else left
    right = DEFAULT_CELL_MARGIN_TWIPS if right is None else right
    available = width - left - right
    if available <= 0:
        raise ListeningWordError("Word 模板图片单元格宽度无效")
    return available * EMU_PER_TWIP


def _scaled_size(photo: "ListeningWordPhoto", max_width: int) -> tuple[int, int]:
    if photo.width <= 0 or photo.height <= 0:
        raise ListeningWordError("倾听照片尺寸无效")
    scale = min(
        max_width / photo.width,
        MAX_IMAGE_HEIGHT_EMU / photo.height,
        EMU_PER_PIXEL,
    )
    if scale <= 0:
        raise ListeningWordError("倾听照片尺寸无效")
    return max(1, int(photo.width * scale)), max(1, int(photo.height * scale))


def _image_run(rid: str, cx: int, cy: int, image_id: int) -> Any:
    run = etree.Element(_w("r"))
    drawing = etree.SubElement(run, _w("drawing"))
    inline = etree.SubElement(drawing, _q(WP, "inline"))
    for attr in ("distT", "distB", "distL", "distR"):
        inline.set(attr, "0")
    extent = etree.SubElement(inline, _q(WP, "extent"))
    extent.set("cx", str(cx))
    extent.set("cy", str(cy))
    doc_pr = etree.SubElement(inline, _q(WP, "docPr"))
    doc_pr.set("id", str(image_id))
    doc_pr.set("name", f"listening image {image_id}")
    graphic = etree.SubElement(inline, _q(A, "graphic"))
    graphic_data = etree.SubElement(graphic, _q(A, "graphicData"))
    graphic_data.set("uri", "http://schemas.openxmlformats.org/drawingml/2006/picture")
    pic = etree.SubElement(graphic_data, _q(PIC, "pic"))
    nv = etree.SubElement(pic, _q(PIC, "nvPicPr"))
    cnv = etree.SubElement(nv, _q(PIC, "cNvPr"))
    cnv.set("id", str(image_id))
    cnv.set("name", f"listening image {image_id}")
    etree.SubElement(nv, _q(PIC, "cNvPicPr"))
    blip_fill = etree.SubElement(pic, _q(PIC, "blipFill"))
    blip = etree.SubElement(blip_fill, _q(A, "blip"))
    blip.set(_q(R, "embed"), rid)
    stretch = etree.SubElement(blip_fill, _q(A, "stretch"))
    etree.SubElement(stretch, _q(A, "fillRect"))
    sp_pr = etree.SubElement(pic, _q(PIC, "spPr"))
    xfrm = etree.SubElement(sp_pr, _q(A, "xfrm"))
    off = etree.SubElement(xfrm, _q(A, "off"))
    off.set("x", "0")
    off.set("y", "0")
    ext = etree.SubElement(xfrm, _q(A, "ext"))
    ext.set("cx", str(cx))
    ext.set("cy", str(cy))
    geom = etree.SubElement(sp_pr, _q(A, "prstGeom"))
    geom.set("prst", "rect")
    etree.SubElement(geom, _q(A, "avLst"))
    return run


class _ImageSink:
    def __init__(self, members: dict[str, bytes]):
        self.members = members
        self.media: dict[str, bytes] = {}
        self.relationships: dict[str, str] = {}
        self.by_digest: dict[str, str] = {}
        self.used_ids: set[int] = set()
        self.next_image = 1
        rels = _parse_xml(
            members["word/_rels/document.xml.rels"], "Word 模板关系"
        )
        self.relationship_root = rels
        self.used_rids = {node.get("Id") for node in rels}
        self.next_relation = 1

    def add(self, photo: "ListeningWordPhoto", cell_width: int) -> Any:
        digest = hashlib.sha256(photo.data).hexdigest()
        extension = _MIME_EXTENSIONS.get(photo.mime_type)
        if extension is None:
            raise ListeningWordError("倾听照片格式不受支持")
        name = f"listening_{digest[:24]}.{extension}"
        media_name = f"word/media/{name}"
        if media_name in self.members and self.members[media_name] != photo.data:
            raise ListeningWordError("Word 模板媒体文件名冲突")
        rid = self.by_digest.get(digest)
        if rid is None:
            while True:
                candidate = f"rIdListening{self.next_relation}"
                self.next_relation += 1
                if candidate not in self.used_rids:
                    break
            rid = candidate
            self.used_rids.add(rid)
            self.by_digest[digest] = rid
            self.relationships[name] = rid
            self.media[media_name] = photo.data
        image_id = self.next_image
        while image_id in self.used_ids:
            image_id += 1
        self.used_ids.add(image_id)
        self.next_image = image_id + 1
        cx, cy = _scaled_size(photo, cell_width)
        return _image_run(rid, cx, cy, image_id)


def _group_caption(group: "ListeningWordGroup | None") -> str:
    if group is not None and group.work_date:
        cleaned = str(group.work_date).replace("\r", " ").replace("\n", " ")
        return f"幼儿绘画表征（{cleaned}）"
    return "幼儿绘画表征（    月    日）"


def _fill_groups(
    table, unit: "ListeningWordUnit", sink: _ImageSink
) -> None:
    rows = table.findall(_w("tr"))
    if len(rows) < 7:
        raise ListeningWordError("Word 模板图文行不足")
    if len(unit.groups) != 3:
        raise ListeningWordError("倾听图文组数量不是三组")
    for index in range(3):
        caption_row = rows[1 + index * 2]
        content_row = rows[2 + index * 2]
        caption_cells = caption_row.findall(_w("tc"))
        content_cells = content_row.findall(_w("tc"))
        if len(caption_cells) != 2 or len(content_cells) != 2:
            raise ListeningWordError("Word 模板图文单元格结构不一致")
        group = unit.groups[index] if index < len(unit.groups) else None
        caption_paragraph = caption_cells[0].find(_w("p"))
        if caption_paragraph is None:
            caption_paragraph = etree.SubElement(caption_cells[0], _w("p"))
        rpr = _clone_rpr(_base_rpr(caption_paragraph))
        _set_songti_12_regular(rpr)
        _write_paragraph(caption_paragraph, _group_caption(group), rpr)
        drawing_cell = content_cells[0]
        paragraphs = drawing_cell.findall(_w("p"))
        if not paragraphs:
            paragraphs = [etree.SubElement(drawing_cell, _w("p"))]
        paragraph = paragraphs[0]
        _clear_content(paragraph)
        ppr = paragraph.find(_w("pPr"))
        if ppr is None:
            ppr = etree.Element(_w("pPr"))
            paragraph.insert(0, ppr)
        jc = ppr.find(_w("jc"))
        if jc is None:
            jc = etree.Element(_w("jc"))
            ppr.append(jc)
        jc.set(_w("val"), "center")
        _canonical_ppr(ppr)
        if group is not None and group.photo is not None:
            paragraph.append(
                sink.add(group.photo, _cell_available_emu(drawing_cell))
            )
        _write_cell_lines(
            content_cells[1],
            group.listening_text if group is not None else "",
        )


def _find_row(rows, label: str):
    for index, row in enumerate(rows):
        cells = row.findall(_w("tc"))
        if cells and _compact(_cell_text(cells[0])) == label:
            return index
    return None


def _fill_evaluation(table, unit: "ListeningWordUnit") -> None:
    rows = table.findall(_w("tr"))
    header_index = _find_row(rows, "一级指标")
    overall_index = _find_row(rows, "综合评价")
    support_index = _find_row(rows, "支持策略")
    if header_index is None or overall_index is None or support_index is None:
        raise ListeningWordError("Word 模板评价或总结行缺失")
    if not (header_index < overall_index < support_index):
        raise ListeningWordError("Word 模板评价行顺序不一致")
    evaluation_rows = rows[header_index + 1 : overall_index]
    if len(evaluation_rows) != len(unit.item_ids) * 3:
        raise ListeningWordError("Word 模板评价项数量与记录模板不一致")
    for row in evaluation_rows:
        cells = row.findall(_w("tc"))
        if len(cells) != 6:
            raise ListeningWordError("Word 模板评价行结构不一致")
        _write_cell_lines(cells[5], "")
    for index, item_id in enumerate(unit.item_ids):
        stars = unit.stars.get(item_id)
        if stars not in (1, 2, 3):
            continue
        row = evaluation_rows[index * 3 + stars - 1]
        cells = row.findall(_w("tc"))
        _write_cell_lines(cells[5], "√")
    overall_cells = rows[overall_index].findall(_w("tc"))
    support_cells = rows[support_index].findall(_w("tc"))
    if len(overall_cells) < 2 or len(support_cells) < 2:
        raise ListeningWordError("Word 模板总结单元格结构不一致")
    _write_cell_lines(overall_cells[1], unit.overall_evaluation or "")
    _write_cell_lines(support_cells[1], unit.support_strategy or "")


def _force_black(table) -> None:
    for run in table.iter(_w("r")):
        if run.find(_w("drawing")) is not None:
            continue
        rpr = run.find(_w("rPr"))
        if rpr is None:
            rpr = etree.Element(_w("rPr"))
            run.insert(0, rpr)
        _set_black(rpr)
    for ppr in table.iter(_w("pPr")):
        rpr = ppr.find(_w("rPr"))
        if rpr is not None:
            _set_black(rpr)


def _add_page_break_before(paragraph) -> None:
    ppr = paragraph.find(_w("pPr"))
    if ppr is None:
        ppr = etree.Element(_w("pPr"))
        paragraph.insert(0, ppr)
    node = ppr.find(_w("pageBreakBefore"))
    if node is None:
        node = etree.SubElement(ppr, _w("pageBreakBefore"))
    node.set(_w("val"), "true")
    _canonical_ppr(ppr)


def _fill_unit(
    unit: "ListeningWordUnit",
    members: dict[str, bytes],
    root,
    body,
    title,
    table,
    sink: "_ImageSink",
) -> tuple[Any, Any]:
    if hashlib.sha256(unit.template_bytes).hexdigest() != unit.template_sha256:
        raise ListeningWordError("Word 模板散列不一致")
    if unit.template_version != unit.template_version.strip():
        raise ListeningWordError("Word 模板版本不合法")
    _set_title(body, unit)
    _fill_header(table, unit)
    _fill_groups(table, unit, sink)
    _fill_evaluation(table, unit)
    _force_black(table)
    return title, table


def _merge_font_tables(
    base_members: dict[str, bytes],
    packages: list[tuple["ListeningWordUnit", dict[str, bytes], Any]],
) -> None:
    base_root = _parse_xml(base_members["word/fontTable.xml"], "Word 模板字体表")
    names = {
        node.get(_w("name"))
        for node in base_root.findall(_w("font"))
        if node.get(_w("name"))
    }
    entries: dict[str, Any] = {}
    for _unit, members, _document in packages:
        for name, node in _font_table_entries(members).items():
            entries.setdefault(name, node)
    needed: set[str] = set()
    for _unit, members, document in packages:
        needed.update(_used_fonts(document))
        styles = _parse_xml(members["word/styles.xml"], "Word 模板样式")
        needed.update(_used_fonts(styles))
    missing = sorted(name for name in needed if name not in entries)
    if missing:
        raise ListeningWordError("Word 模板字体表缺少实际使用的字体")
    for name in sorted(needed):
        if name in names:
            continue
        base_root.append(copy.deepcopy(entries[name]))
        names.add(name)
    base_members["word/fontTable.xml"] = etree.tostring(
        base_root, xml_declaration=True, encoding="UTF-8", standalone=True
    )


def _write_package(
    members: dict[str, bytes],
    sink: _ImageSink,
) -> bytes:
    if sink.media:
        rels_root = sink.relationship_root
        for name, rid in sink.relationships.items():
            node = etree.SubElement(rels_root, _q(PKG_REL, "Relationship"))
            node.set("Id", rid)
            node.set("Type", IMAGE_REL)
            node.set("Target", f"media/{name}")
        members["word/_rels/document.xml.rels"] = etree.tostring(
            rels_root, xml_declaration=True, encoding="UTF-8", standalone=True
        )
        content = _parse_xml(members["[Content_Types].xml"], "Word 模板内容类型")
        defaults = {
            (node.get("Extension") or "").lower(): node
            for node in content.findall(_q(CT, "Default"))
        }
        for media_name, payload in sink.media.items():
            extension = media_name.rsplit(".", 1)[-1].lower()
            expected = _EXTENSION_CONTENT_TYPES.get(extension)
            if expected is None:
                raise ListeningWordError("Word 模板媒体扩展名不受支持")
            existing = defaults.get(extension)
            if existing is None:
                node = etree.SubElement(content, _q(CT, "Default"))
                node.set("Extension", extension)
                node.set("ContentType", expected)
                defaults[extension] = node
            elif (existing.get("ContentType") or "").lower() != expected:
                raise ListeningWordError("Word 模板媒体内容类型冲突")
            if media_name in members and members[media_name] != payload:
                raise ListeningWordError("Word 模板媒体文件名冲突")
            members[media_name] = payload
        members["[Content_Types].xml"] = etree.tostring(
            content, xml_declaration=True, encoding="UTF-8", standalone=True
        )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, data)
    return output.getvalue()


def generate_listening_docx(units: tuple[ListeningWordUnit, ...]) -> bytes:
    if not units:
        raise ListeningWordError("倾听导出没有可生成记录")
    packages: list[
        tuple[
            ListeningWordUnit,
            dict[str, bytes],
            Any,
            Any,
            Any,
            Any,
            Any,
            Any,
        ]
    ] = []
    signatures: list[tuple[bytes, bytes, bytes]] = []
    for unit in units:
        members = _zip_members(unit)
        root, body, title, table, trailer, sect = _document_parts(members)
        signature = (
            _sect_signature(sect),
            _styles_signature(members),
            _settings_signature(members),
        )
        if signatures and signature != signatures[0]:
            raise ListeningWordError("Word 模板共享版式或样式不一致")
        signatures.append(signature)
        if not isinstance(unit.template_version, str) or not unit.template_version:
            raise ListeningWordError("Word 模板版本缺失")
        _reject_unit_relationships(root, members)
        packages.append(
            (unit, members, root, body, title, table, trailer, sect)
        )
    base_members = dict(packages[0][1])
    _merge_font_tables(
        base_members,
        [(item[0], item[1], item[2]) for item in packages],
    )
    base_root = packages[0][2]
    base_sect = packages[0][7]
    sink = _ImageSink(base_members)
    new_body = etree.Element(_w("body"))
    for index, (
        _unit,
        _members,
        _root,
        _body,
        title,
        table,
        trailer,
        _sect,
    ) in enumerate(packages):
        _fill_unit(
            _unit, _members, _root, _body, title, table, sink
        )
        if index:
            _add_page_break_before(title)
        new_body.append(title)
        new_body.append(table)
        if index == len(packages) - 1:
            # The template's final empty paragraph belongs after the last
            # table.  Keeping an empty paragraph after every earlier table
            # can itself spill to a new page and then the next title's page
            # break would leave a blank page.
            new_body.append(trailer)
    new_body.append(copy.deepcopy(base_sect))
    root_out = etree.Element(_w("document"), nsmap=base_root.nsmap)
    root_out.append(new_body)
    base_members["word/document.xml"] = etree.tostring(
        root_out, xml_declaration=True, encoding="UTF-8", standalone=True
    )
    return _write_package(base_members, sink)


@dataclass(frozen=True)
class ListeningWordPhoto:
    asset_id: str
    data: bytes
    mime_type: str
    width: int
    height: int
    source_sha256: str | None = None
    source_byte_size: int | None = None
    source_mime_type: str | None = None
    source_width: int | None = None
    source_height: int | None = None
    orientation: int | None = None


@dataclass(frozen=True)
class ListeningWordGroup:
    group_id: str
    position: int
    work_date: str | None
    listening_text: str | None
    photo: ListeningWordPhoto | None


@dataclass(frozen=True)
class ListeningWordUnit:
    record_id: str
    child_name: str
    domain: str
    domain_label: str
    grade: str
    term_name: str
    class_name: str
    revision: int
    observation_date: str | None
    adult_count: str | None
    child_age: str | None
    goal: str | None
    observation_area: str | None
    overall_evaluation: str | None
    support_strategy: str | None
    groups: tuple[ListeningWordGroup, ...]
    item_ids: tuple[str, ...]
    stars: dict[str, int | None]
    template_version: str
    template_sha256: str
    template_bytes: bytes
