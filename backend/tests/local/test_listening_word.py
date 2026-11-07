"""Pure listening DOCX generator tests against the real controlled templates."""

from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import replace

import pytest
from lxml import etree
from PIL import Image

from app.local import listening_templates
from app.services.word_export_listening import (
    ListeningWordError,
    ListeningWordGroup,
    ListeningWordPhoto,
    ListeningWordUnit,
    generate_listening_docx,
)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
GRADE_LABELS = {"small": "小班", "middle": "中班", "large": "大班"}


def _image(fmt: str = "PNG", size: tuple[int, int] = (300, 200)) -> bytes:
    buffer = io.BytesIO()
    mode = "P" if fmt == "GIF" else "RGB"
    color = 3 if fmt == "GIF" else (120, 30, 200)
    Image.new(mode, size, color).save(buffer, format=fmt)
    return buffer.getvalue()


def _unit(
    template: listening_templates.ListeningTemplate,
    *,
    index: int = 0,
    name: str = "虚构甲",
    photos: tuple[ListeningWordPhoto | None, ...] = (None, None, None),
    stars: dict[str, int | None] | None = None,
    text_suffix: str = "",
) -> ListeningWordUnit:
    payload = listening_templates.read_template_bytes(template)
    chosen_stars = stars or {
        item.item_id: None for item in template.items
    }
    groups = tuple(
        ListeningWordGroup(
            group_id=f"group-{index}-{position}",
            position=position,
            work_date=f"11月{position + 1}日{text_suffix}",
            listening_text=f"倾听正文{index}-{position}\n第二段{text_suffix}",
            photo=photos[position],
        )
        for position in range(3)
    )
    return ListeningWordUnit(
        record_id=f"record-{index}",
        child_name=name,
        domain=template.domain,
        domain_label=listening_templates.DOMAIN_LABELS[template.domain],
        grade=template.grade,
        term_name="虚构秋季",
        class_name="中班合册联测",
        revision=1,
        observation_date="11月1—3日",
        adult_count="1名",
        child_age="5岁",
        goal=f"目标{text_suffix}",
        observation_area="阅读区",
        overall_evaluation="评价第一段\n评价第二段",
        support_strategy="支持第一段\n支持第二段",
        groups=groups,
        item_ids=tuple(item.item_id for item in template.items),
        stars=chosen_stars,
        template_version=template.version,
        template_sha256=template.sha256,
        template_bytes=payload,
    )


def _document(payload: bytes):
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = set(archive.namelist())
        for part in (
            "[Content_Types].xml",
            "word/document.xml",
            "word/styles.xml",
            "word/settings.xml",
            "word/fontTable.xml",
        ):
            assert part in names
        return etree.fromstring(archive.read("word/document.xml"))


def _parts(payload: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert archive.testzip() is None
        return {
            info.filename: archive.read(info.filename)
            for info in archive.infolist()
        }


def _canonical(element) -> bytes:
    return etree.tostring(element, method="c14n")


def _strip_rsid(element):
    for node in list(element.iter()):
        if etree.QName(node.tag).localname.lower().startswith("rsid"):
            parent = node.getparent()
            if parent is not None:
                parent.remove(node)
            continue
        for name in list(node.attrib):
            if etree.QName(name).localname.lower().startswith("rsid"):
                del node.attrib[name]
    return element


def _cell_text(cell) -> str:
    return "".join(node.text or "" for node in cell.iter(f"{W}t"))


def _assert_black(rpr) -> None:
    assert rpr is not None
    color = rpr.find(f"{W}color")
    assert color is not None and color.get(f"{W}val") == "000000"
    for node in rpr.iter():
        assert not any(
            etree.QName(name).localname.lower().startswith("theme")
            for name in node.attrib
        )


def _assert_songti_12_regular(rpr) -> None:
    _assert_black(rpr)
    fonts = rpr.find(f"{W}rFonts")
    assert fonts is not None
    for key in ("ascii", "hAnsi", "eastAsia", "cs"):
        assert fonts.get(f"{W}{key}") == "宋体"
    assert rpr.find(f"{W}b").get(f"{W}val") == "0"
    assert rpr.find(f"{W}bCs").get(f"{W}val") == "0"
    assert rpr.find(f"{W}sz").get(f"{W}val") == "24"
    assert rpr.find(f"{W}szCs").get(f"{W}val") == "24"


def test_every_controlled_template_uses_its_own_real_bytes() -> None:
    templates = listening_templates.list_templates()
    assert len(templates) == 15
    checked_rows = 0
    for position, template in enumerate(templates):
        output = generate_listening_docx((_unit(template, index=position),))
        members = _parts(output)
        root = etree.fromstring(members["word/document.xml"])
        body = root.find(f"{W}body")
        assert [etree.QName(child).localname for child in body] == [
            "p",
            "tbl",
            "p",
            "sectPr",
        ]
        title, table = body[0], body[1]
        title_text = "".join(title.itertext())
        assert f"    {listening_templates.DOMAIN_LABELS[template.domain]}领域     " in title_text
        assert f"{GRADE_LABELS[template.grade]}幼儿" in title_text
        runs = title.findall(f"{W}r")
        assert len(runs) == 3
        assert runs[1].find(f"{W}rPr/{W}u") is not None
        assert runs[0].find(f"{W}rPr/{W}u") is None
        assert runs[2].find(f"{W}rPr/{W}u") is None
        for run in runs:
            _assert_black(run.find(f"{W}rPr"))

        rows = table.findall(f"{W}tr")
        assert len(rows) == 10 + len(template.items) * 3
        header = "".join(rows[0].itertext())
        for expected in (
            "观察日期：11月1—3日",
            "幼儿姓名：虚构甲",
            "成人数目：1名",
            "幼儿年龄：5岁",
            "目标：目标",
            "观察区域：阅读区",
        ):
            assert expected in header
        for group_index in range(3):
            caption = _cell_text(rows[1 + group_index * 2].findall(f"{W}tc")[0])
            assert caption == f"幼儿绘画表征（11月{group_index + 1}日）"
            right = rows[2 + group_index * 2].findall(f"{W}tc")[1]
            paragraphs = right.findall(f"{W}p")
            assert [ "".join(p.itertext()) for p in paragraphs[:2] ] == [
                f"倾听正文{position}-{group_index}",
                f"第二段",
            ]
            for paragraph in paragraphs:
                ppr = paragraph.find(f"{W}pPr")
                _assert_songti_12_regular(ppr.find(f"{W}rPr"))
                for run in paragraph.findall(f"{W}r"):
                    _assert_songti_12_regular(run.find(f"{W}rPr"))

        evaluation_rows = rows[8 : 8 + len(template.items) * 3]
        for item_index, item in enumerate(template.items):
            item_rows = evaluation_rows[item_index * 3 : item_index * 3 + 3]
            assert len(item_rows) == 3
            assert "".join(item.requirement.split()) in "".join("".join(item_rows[0].itertext()).split())
            for level, standard in item.standards.items():
                assert "".join(standard.split()) in "".join(
                    "".join(item_rows[int(level) - 1].itertext()).split()
                )
            checked_rows += len(item_rows)
        checks = []
        for item_index, item in enumerate(template.items):
            for level in (1, 2, 3):
                cell = evaluation_rows[item_index * 3 + level - 1].findall(
                    f"{W}tc"
                )[5]
                if _cell_text(cell).strip() == "√":
                    checks.append((item.item_id, level))
        assert checks == [(item.item_id, None) for item in template.items][:0] or True
        # Each item has exactly one check only when the manifest star is set;
        # this test uses all-null stars, so all check cells stay blank.
        assert checks == []

        # Table grid, cell widths/merges and row heights are byte-identical to
        # the controlled template after removing only rsid attributes.
        with zipfile.ZipFile(
            io.BytesIO(listening_templates.read_template_bytes(template))
        ) as archive:
            source = etree.fromstring(archive.read("word/document.xml"))
        source_table = source.find(f"{W}body/{W}tbl")
        assert _canonical(_strip_rsid(source_table.find(f"{W}tblGrid"))) == _canonical(
            _strip_rsid(table.find(f"{W}tblGrid"))
        )
        assert _canonical(_strip_rsid(source_table.find(f"{W}tblPr"))) == _canonical(
            _strip_rsid(table.find(f"{W}tblPr"))
        )
        for source_row, row in zip(
            source_table.findall(f"{W}tr"), rows, strict=True
        ):
            source_trpr = source_row.find(f"{W}trPr")
            trpr = row.find(f"{W}trPr")
            if source_trpr is not None or trpr is not None:
                assert _canonical(_strip_rsid(source_trpr)) == _canonical(
                    _strip_rsid(trpr)
                )
            for source_cell, cell in zip(
                source_row.findall(f"{W}tc"), row.findall(f"{W}tc"), strict=True
            ):
                assert _canonical(
                    _strip_rsid(source_cell.find(f"{W}tcPr"))
                ) == _canonical(_strip_rsid(cell.find(f"{W}tcPr")))

        # Every non-drawing run has explicit black, including fixed text.
        for run in table.iter(f"{W}r"):
            if run.find(f"{W}drawing") is None:
                _assert_black(run.find(f"{W}rPr"))

        # The single shared section is the template's own section.
        source_sect = source.find(f"{W}body/{W}sectPr")
        assert _canonical(_strip_rsid(source_sect)) == _canonical(
            _strip_rsid(body.find(f"{W}sectPr"))
        )


def test_personal_order_page_breaks_and_unique_image_ids() -> None:
    templates = listening_templates.list_templates()
    by_domain = {
        template.domain: template
        for template in templates
        if template.grade == "middle"
    }
    photos = (
        ListeningWordPhoto("a", _image("PNG"), "image/png", 300, 200),
        ListeningWordPhoto("b", _image("JPEG"), "image/jpeg", 400, 800),
        ListeningWordPhoto("c", _image("WEBP"), "image/webp", 900, 300),
    )
    units = tuple(
        _unit(by_domain[domain], index=index, photos=photos)
        for index, domain in enumerate(
            ("language", "science", "health", "social", "art")
        )
    )
    output = generate_listening_docx(units)
    members = _parts(output)
    root = etree.fromstring(members["word/document.xml"])
    body = root.find(f"{W}body")
    assert [etree.QName(child).localname for child in body] == [
        "p",
        "tbl",
        "p",
        "tbl",
        "p",
        "tbl",
        "p",
        "tbl",
        "p",
        "tbl",
        "p",
        "sectPr",
    ]
    titles = [
        "".join(child.itertext())
        for child in body
        if etree.QName(child).localname == "p" and "".join(child.itertext())
    ]
    for title, label in zip(
        titles, ("语言", "科学", "健康", "社会", "艺术"), strict=True
    ):
        assert f"    {label}领域     " in title
    title_elements = [
        child
        for child in body
        if etree.QName(child).localname == "p" and "".join(child.itertext())
    ]
    assert title_elements[0].find(f"{W}pPr/{W}pageBreakBefore") is None
    for title in title_elements[1:]:
        assert title.find(f"{W}pPr/{W}pageBreakBefore") is not None
    assert len(body.findall(f".//{W}sectPr")) == 1
    assert len(body.findall(f"{W}tbl")) == 5

    rels = etree.fromstring(members["word/_rels/document.xml.rels"])
    image_targets = [
        node.get("Target")
        for node in rels
        if node.get("Type", "").endswith("/image")
    ]
    assert len(image_targets) == len(set(image_targets)) == 3
    media = [name for name in members if name.startswith("word/media/")]
    assert sorted(media) == sorted(f"word/{target}" for target in image_targets)
    ids = [
        node.get("id")
        for node in root.iter(f"{WP}docPr")
    ]
    assert len(ids) == 15
    assert len(ids) == len(set(ids))


def test_all_allowed_word_image_formats() -> None:
    template = next(
        item
        for item in listening_templates.list_templates()
        if item.grade == "middle" and item.domain == "language"
    )
    formats = (("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp"), ("GIF", "image/gif"), ("BMP", "image/bmp"))
    photos = tuple(
        ListeningWordPhoto(
            f"format-{index}",
            _image(fmt, (240 + index * 20, 160 + index * 10)),
            mime,
            240 + index * 20,
            160 + index * 10,
        )
        for index, (fmt, mime) in enumerate(formats[:3])
    )
    extra = tuple(
        ListeningWordPhoto(
            f"format-{index}",
            _image(fmt, (180, 320)),
            mime,
            180,
            320,
        )
        for index, (fmt, mime) in enumerate(formats[3:], start=3)
    )
    output = generate_listening_docx(
        (
            _unit(template, index=0, photos=photos),
            _unit(template, index=1, photos=(extra[0], extra[1], None)),
        )
    )
    members = _parts(output)
    media = [name for name in members if name.startswith("word/media/")]
    assert len(media) == 5
    extensions = {name.rsplit(".", 1)[-1] for name in media}
    assert extensions <= {"png", "jpg", "webp", "gif", "bmp"}
    assert {"png", "jpg", "webp", "gif", "bmp"} <= extensions
    content_types = members["[Content_Types].xml"].decode("utf-8")
    for extension in extensions:
        assert f'Extension="{extension}"' in content_types
    for name in media:
        source_name = None
        payload = members[name]
        for photo in photos + extra:
            if hashlib.sha256(photo.data).hexdigest()[:24] in name:
                source_name = photo.asset_id
                assert payload == photo.data
                break
        assert source_name is not None


def test_rejects_non_zip_or_changed_template_bytes() -> None:
    template = next(
        item
        for item in listening_templates.list_templates()
        if item.grade == "middle" and item.domain == "language"
    )
    unit = _unit(template)
    broken = replace(
        unit,
        template_bytes=b"<w:document/>",
        template_sha256=hashlib.sha256(b"<w:document/>").hexdigest(),
    )
    with pytest.raises(ListeningWordError, match="DOCX"):
        generate_listening_docx((broken,))

    members = _parts(unit.template_bytes)
    changed_root = etree.fromstring(members["word/document.xml"])
    margin = changed_root.find(f".//{W}sectPr/{W}pgMar")
    assert margin is not None
    margin.set(f"{W}top", "721")
    members["word/document.xml"] = etree.tostring(
        changed_root, xml_declaration=True, encoding="UTF-8", standalone=True
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    changed = buffer.getvalue()
    changed_unit = replace(
        unit,
        template_bytes=changed,
        template_sha256=hashlib.sha256(changed).hexdigest(),
    )
    with pytest.raises(ListeningWordError):
        generate_listening_docx((unit, changed_unit))


def test_rejects_grade_or_item_count_mismatch() -> None:
    template = next(
        item
        for item in listening_templates.list_templates()
        if item.grade == "middle" and item.domain == "language"
    )
    unit = _unit(template)
    with pytest.raises(ListeningWordError, match="年级"):
        generate_listening_docx((replace(unit, grade="large"),))
    with pytest.raises(ListeningWordError, match="评价项"):
        generate_listening_docx(
            (
                replace(
                    unit,
                    item_ids=unit.item_ids[:-1],
                    stars={unit.item_ids[0]: 1},
                ),
            )
        )
