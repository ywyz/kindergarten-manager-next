"""Focused regression tests for desktop curriculum deliberations.

Covers the real loopback API, atomic versioned saves, the 0017 migration and
the pure OOXML generator for all four appendix combinations.
"""

from __future__ import annotations

import io
import unittest
import uuid
import zipfile
from datetime import date
from unittest import mock

from lxml import etree

from app.local import curriculum_content, curriculum_service
from app.local.base import utc_now
from app.local.models import LocalClass, LocalCurriculumDeliberation
from app.local.runtime import LocalRuntime
from app.services.word_export_curriculum import render_curriculum_docx
from tests.local.support import LocalTestCase, query_rows, query_scalar

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML = "http://www.w3.org/XML/1998/namespace"
NS = {"w": W}


def _q(tag: str) -> str:
    return f"{{{W}}}{tag}"


def _content(**overrides: str) -> dict[str, str]:
    content = curriculum_content.empty_content()
    content.update(
        {
            "activity_name": "纸桥怎样更稳",
            "activity_form": "small_group",
            "activity_form_other": "",
            "institution": "示范幼儿园",
            "class_name": "中一班",
            "child_count": "18",
            "organizer": "教师甲",
            "recorder": "教师乙",
            "activity_date": "2026-11-09",
            "goals_original": (
                "1. 比较平放与折过的桥面。\n"
                "2. 和同伴轮流搭桥，说出一次发现。"
            ),
            "goals_status": "unchanged",
            "goals_adjustment": "",
            "preparation_original": (
                "1. 每组准备卡纸、积木和木片。\n"
                "2. 每组一张记录卡。"
            ),
            "preparation_status": "adjusted",
            "preparation_adjustment": "加上桌面定位线，并把记录卡分成两栏。",
            "process_original": (
                "一、试搭纸桥\n"
                "请幼儿在两个积木之间平放卡纸。\n"
                "二、折一折再比较\n"
                "记录者用圆点记下结果。"
            ),
            "process_adjustment": "两轮试搭使用同一距离。",
            "reason": "统一间距，便于幼儿比较桥面形状带来的变化。",
            "lesson_original": (
                "活动名称  纸桥怎样更稳\n\n"
                "一、活动目标\n1. 比较不同桥面。\n"
                "二、活动过程\n1. 平放卡纸。"
            ),
            "lesson_revised": (
                "活动名称  纸桥怎样更稳\n\n"
                "一、活动目标\n1. 比较不同桥面。\n"
                "二、活动过程\n1. 对准定位线。"
            ),
        }
    )
    content.update(overrides)
    return content


def _document(payload: bytes):
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        return etree.fromstring(archive.read("word/document.xml"))


def _paragraph_text(paragraph) -> str:
    pieces: list[str] = []
    for node in paragraph.iter():
        if node.tag == _q("t"):
            pieces.append(node.text or "")
        elif node.tag == _q("tab"):
            pieces.append("\t")
    return "".join(pieces)


def _all_paragraphs(root):
    return root.findall(".//w:p", NS)


def _paragraph_with_text(root, text: str):
    for paragraph in _all_paragraphs(root):
        if _paragraph_text(paragraph) == text:
            return paragraph
    raise AssertionError(f"paragraph not found: {text!r}")


def _run_size(paragraph) -> int:
    run = paragraph.find("w:r", NS)
    assert run is not None
    size = run.find("w:rPr/w:sz", NS)
    assert size is not None
    return int(size.get(_q("val")))


def _grid_spans(row) -> list[int]:
    spans = []
    for cell in row.findall("w:tc", NS):
        span = cell.find("w:tcPr/w:gridSpan", NS)
        spans.append(int(span.get(_q("val"))) if span is not None else 1)
    return spans


def _table(root):
    table = root.find(".//w:tbl", NS)
    assert table is not None
    return table


class CurriculumWordLayoutTests(unittest.TestCase):
    def _render(self, **overrides: str) -> bytes:
        return render_curriculum_docx(_content(**overrides))

    def test_all_four_appendix_combinations_and_section_rules(self) -> None:
        cases = (
            ("none", "", "", 1, False, False),
            ("original", "原稿正文", "", 1, True, False),
            ("revised", "", "修改正文", 2, False, True),
            ("both", "原稿正文", "修改正文", 2, True, True),
        )
        for name, original, revised, sections, has_original, has_revised in cases:
            with self.subTest(case=name):
                root = _document(
                    self._render(
                        lesson_original=original,
                        lesson_revised=revised,
                    )
                )
                section_props = root.findall(".//w:sectPr", NS)
                self.assertEqual(len(section_props), sections)
                expected_cols = [720] if sections == 1 else [720, 425]
                for section, cols in zip(section_props, expected_cols):
                    size = section.find("w:pgSz", NS)
                    margin = section.find("w:pgMar", NS)
                    grid = section.find("w:docGrid", NS)
                    self.assertIsNotNone(size)
                    self.assertIsNotNone(margin)
                    self.assertIsNotNone(grid)
                    self.assertIsNone(section.find("w:type", NS))
                    self.assertEqual(size.get(_q("w")), "11906")
                    self.assertEqual(size.get(_q("h")), "16838")
                    self.assertEqual(margin.get(_q("top")), "1440")
                    self.assertEqual(margin.get(_q("bottom")), "1440")
                    self.assertEqual(margin.get(_q("left")), "1800")
                    self.assertEqual(margin.get(_q("right")), "1800")
                    self.assertEqual(margin.get(_q("header")), "851")
                    self.assertEqual(margin.get(_q("footer")), "992")
                    self.assertEqual(grid.get(_q("type")), "lines")
                    self.assertEqual(grid.get(_q("linePitch")), "312")
                    self.assertEqual(
                        section.find("w:cols", NS).get(_q("space")),
                        str(cols),
                    )

                titles = {
                    _paragraph_text(paragraph)
                    for paragraph in _all_paragraphs(root)
                    if _paragraph_text(paragraph)
                    in {"附教案：原稿", "二次修改"}
                }
                self.assertEqual(
                    titles,
                    (
                        {"附教案：原稿", "二次修改"}
                        if has_original and has_revised
                        else {"附教案：原稿"}
                        if has_original
                        else {"二次修改"}
                        if has_revised
                        else set()
                    ),
                )
                if has_original:
                    original_title = _paragraph_with_text(
                        root, "附教案：原稿"
                    )
                    self.assertIsNone(
                        original_title.find("w:pPr/w:pageBreakBefore", NS)
                    )
                    break_run = original_title.find("w:r/w:br", NS)
                    self.assertIsNotNone(break_run)
                    self.assertEqual(break_run.get(_q("type")), "page")
                if has_revised:
                    revised_title = _paragraph_with_text(root, "二次修改")
                    self.assertIsNone(
                        revised_title.find("w:pPr/w:pageBreakBefore", NS)
                    )
                    self.assertIsNone(revised_title.find("w:r/w:br", NS))
                if has_revised:
                    break_paragraphs = [
                        paragraph
                        for paragraph in _all_paragraphs(root)
                        if paragraph.find("w:pPr/w:sectPr", NS) is not None
                    ]
                    self.assertEqual(len(break_paragraphs), 1)
                    break_props = break_paragraphs[0].find("w:pPr", NS)
                    self.assertEqual(
                        break_props.find("w:spacing", NS).get(_q("line")),
                        "460",
                    )
                    self.assertEqual(
                        break_props.find("w:spacing", NS).get(
                            _q("lineRule")
                        ),
                        "exact",
                    )
                    self.assertEqual(
                        break_props.find("w:ind", NS).get(
                            _q("firstLine")
                        ),
                        "480",
                    )
                    self.assertEqual(
                        break_props.find("w:jc", NS).get(_q("val")), "left"
                    )
                    self.assertIsNotNone(
                        break_props.find("w:adjustRightInd", NS)
                    )
                    self.assertIsNotNone(
                        break_props.find("w:snapToGrid", NS)
                    )
                    break_index = _all_paragraphs(root).index(
                        break_paragraphs[0]
                    )
                    revised_index = _all_paragraphs(root).index(
                        _paragraph_with_text(root, "二次修改")
                    )
                    self.assertLess(break_index, revised_index)

    def test_fixed_grid_merges_and_row_baselines(self) -> None:
        root = _document(self._render())
        table = _table(root)
        table_width = table.find("w:tblPr/w:tblW", NS)
        self.assertEqual(table_width.get(_q("w")), "0")
        self.assertEqual(table_width.get(_q("type")), "auto")
        self.assertEqual(
            table.find("w:tblPr/w:tblInd", NS).get(_q("w")), "-302"
        )
        self.assertEqual(
            table.find("w:tblPr/w:tblLayout", NS).get(_q("type")),
            "fixed",
        )
        self.assertEqual(
            table.find("w:tblPr/w:tblLook", NS).get(_q("val")), "0000"
        )
        widths = [
            int(node.get(_q("w")))
            for node in table.findall("w:tblGrid/w:gridCol", NS)
        ]
        self.assertEqual(widths, [1188, 2438, 1644, 1661, 1392, 1104])
        rows = table.findall("w:tr", NS)
        self.assertEqual(len(rows), 8)
        self.assertEqual(
            [_grid_spans(row) for row in rows],
            [
                [1, 1, 1, 3],
                [1, 1, 1, 1, 1, 1],
                [1, 1, 1, 1, 1, 1],
                [4, 2],
                [1, 3, 2],
                [1, 3, 2],
                [1, 3, 2],
                [1, 5],
            ],
        )
        self.assertEqual(
            [
                int(row.find("w:trPr/w:trHeight", NS).get(_q("val")))
                for row in rows
            ],
            [459, 459, 459, 459, 2360, 2190, 2542, 1859],
        )
        for row in rows:
            height = row.find("w:trPr/w:trHeight", NS)
            self.assertIsNotNone(height)
            self.assertIsNone(height.get(_q("hRule")))
            self.assertIsNone(row.find("w:trPr/w:cantSplit", NS))

    def test_title_and_font_contract(self) -> None:
        content = _content(
            activity_form="other",
            activity_form_other="远足",
        )
        root = _document(render_curriculum_docx(content))
        title = _paragraph_with_text(root, "课程审议记录表")
        title_props = title.find("w:pPr", NS)
        self.assertEqual(
            title_props.find("w:jc", NS).get(_q("val")), "center"
        )
        spacing = title_props.find("w:spacing", NS)
        self.assertEqual(spacing.get(_q("line")), "460")
        self.assertEqual(spacing.get(_q("lineRule")), "exact")
        self.assertEqual(_run_size(title), 32)
        self.assertIsNotNone(title.find(".//w:r/w:rPr/w:b", NS))

        label = _paragraph_with_text(root, "活动名称")
        self.assertEqual(_run_size(label), 24)
        label_props = label.find("w:pPr", NS)
        self.assertEqual(
            label_props.find("w:spacing", NS).get(_q("line")), "460"
        )
        self.assertEqual(
            label_props.find("w:spacing", NS).get(_q("lineRule")),
            "exact",
        )
        self.assertEqual(label_props.find("w:jc", NS).get(_q("val")), "center")

        class_label = _paragraph_with_text(root, "班级（年龄段）")
        self.assertIsNone(class_label.find("w:pPr/w:jc", NS))
        self.assertEqual(
            class_label.find("w:pPr/w:spacing", NS).get(_q("line")), "460"
        )

        activity = _paragraph_with_text(root, "纸桥怎样更稳")
        self.assertEqual(_run_size(activity), 22)
        self.assertIsNone(activity.find("w:pPr/w:jc", NS))
        self.assertIsNone(activity.find("w:pPr/w:spacing", NS))
        institution = _paragraph_with_text(root, "示范幼儿园")
        self.assertEqual(_run_size(institution), 24)
        self.assertEqual(
            institution.find("w:pPr/w:jc", NS).get(_q("val")), "center"
        )
        self.assertEqual(
            institution.find("w:pPr/w:spacing", NS).get(_q("line")), "460"
        )
        goal = _paragraph_with_text(root, "1. 比较平放与折过的桥面。")
        self.assertEqual(_run_size(goal), 22)
        date_cell = _paragraph_with_text(root, "2026.11.09")
        self.assertEqual(_run_size(date_cell), 22)
        self.assertIsNone(date_cell.find("w:pPr/w:jc", NS))
        original_title = _paragraph_with_text(root, "附教案：原稿")
        self.assertEqual(_run_size(original_title), 24)
        revised_title = _paragraph_with_text(root, "二次修改")
        self.assertEqual(_run_size(revised_title), 24)

        form_text = ""
        form_paragraph = None
        for paragraph in _all_paragraphs(root):
            text = _paragraph_text(paragraph)
            if text.startswith("集体、区域、亲子、小组、其他"):
                form_text = text
                form_paragraph = paragraph
                break
        self.assertEqual(form_text, "集体、区域、亲子、小组、其他√远足")
        self.assertIsNone(form_paragraph.find("w:pPr/w:jc", NS))
        self.assertEqual(
            form_paragraph.find("w:pPr/w:spacing", NS).get(_q("line")),
            "460",
        )
        underlined = root.xpath(
            ".//w:r[w:rPr/w:u]/w:t", namespaces=NS
        )
        self.assertTrue(underlined)
        self.assertEqual(underlined[0].text, "远足")

    def test_checks_tabs_special_characters_and_line_spacing(self) -> None:
        special = '第一段 & < > " \'\n\t缩进 行\n\n  保留 空格  '
        root = _document(
            self._render(
                process_original=special,
                goals_status="unchanged",
                preparation_status="adjusted",
                lesson_original="原稿正文",
                lesson_revised="修改正文",
            )
        )
        table = _table(root)
        rows = table.findall("w:tr", NS)
        process_paragraphs = [
            _paragraph_text(paragraph)
            for paragraph in rows[6].findall("w:tc", NS)[1].findall(
                "w:p", NS
            )
        ]
        self.assertEqual(
            process_paragraphs,
            [
                '第一段 & < > " \'',
                "\t缩进 行",
                "",
                "  保留 空格  ",
            ],
        )
        preserved = rows[6].findall("w:tc", NS)[1].findall(
            "w:p", NS
        )[-1].find(".//w:t", NS)
        self.assertEqual(preserved.get(f"{{{XML}}}space"), "preserve")
        tab = rows[6].findall("w:tc", NS)[1].find(
            ".//w:r/w:tab", NS
        )
        self.assertIsNotNone(tab)

        self.assertIsNotNone(
            _paragraph_with_text(root, "（结合实际情况对目标的调整）")
        )
        goals_status = _paragraph_with_text(root, "保持原设计不变（√）")
        self.assertEqual(_run_size(goals_status), 22)
        self.assertIsNotNone(
            _paragraph_with_text(root, "有所调整（√）")
        )
        self.assertIsNotNone(
            _paragraph_with_text(root, "保持原设计，不变（）")
        )
        goals_cell = rows[4].findall("w:tc", NS)[2]
        self.assertEqual(
            [
                _paragraph_text(paragraph)
                for paragraph in goals_cell.findall("w:p", NS)
            ],
            [
                "（结合实际情况对目标的调整）",
                "保持原设计不变（√）",
                "有所调整（）",
                "调整内容：",
                "",
            ],
        )

        original_body = _paragraph_with_text(root, "原稿正文")
        self.assertEqual(
            original_body.find("w:pPr/w:spacing", NS).get(_q("line")),
            "360",
        )
        self.assertIsNone(original_body.find("w:pPr/w:jc", NS))
        revised_body = _paragraph_with_text(root, "修改正文")
        self.assertIsNone(revised_body.find("w:pPr/w:spacing", NS))
        self.assertEqual(
            revised_body.find("w:pPr/w:jc", NS).get(_q("val")), "left"
        )
        self.assertIsNotNone(
            revised_body.find("w:pPr/w:widowControl", NS)
        )

    def test_empty_and_whitespace_appendix_are_omitted(self) -> None:
        for original, revised in (
            ("", ""),
            (" \t\n", ""),
            ("", " \t\n"),
            (" \n\t ", " \n\t "),
            ("\u3000\n", "\u3000"),
        ):
            with self.subTest(original=original, revised=revised):
                root = _document(
                    self._render(
                        lesson_original=original,
                        lesson_revised=revised,
                    )
                )
                text = "".join(
                    (node.text or "") for node in root.iter(_q("t"))
                )
                self.assertNotIn("附教案：原稿", text)
                self.assertNotIn("二次修改", text)
                self.assertEqual(len(root.findall(".//w:sectPr", NS)), 1)

    def test_long_process_body_is_not_split_forbidden(self) -> None:
        long_text = "\n".join(f"{index}. 第{index}段活动过程" for index in range(1, 81))
        root = _document(self._render(process_original=long_text))
        rows = _table(root).findall("w:tr", NS)
        self.assertEqual(
            len(rows[6].findall("w:tc", NS)[1].findall("w:p", NS)),
            80,
        )
        for row in rows:
            self.assertIsNone(row.find("w:trPr/w:cantSplit", NS))

    def test_other_description_is_ignored_unless_other_is_selected(self) -> None:
        content = _content(
            activity_form="small_group",
            activity_form_other="不应出现的旧说明",
        )
        root = _document(render_curriculum_docx(content))
        form_text = ""
        underline_text = ""
        for paragraph in _all_paragraphs(root):
            text = _paragraph_text(paragraph)
            if text.startswith("集体、区域、亲子、小组"):
                form_text = text
                underlined = paragraph.xpath(
                    ".//w:r[w:rPr/w:u]/w:t", namespaces=NS
                )
                if underlined:
                    underline_text = underlined[0].text or ""
                break
        self.assertEqual(form_text, "集体、区域、亲子、小组√、其他 ")
        self.assertNotIn("不应出现的旧说明", form_text)
        self.assertEqual(underline_text, " ")

    def test_main_table_vertical_alignment_matches_approved_form(self) -> None:
        rows = _table(_document(self._render())).findall("w:tr", NS)
        for row_index in (4, 5, 6):
            cells = rows[row_index].findall("w:tc", NS)
            self.assertEqual(
                cells[1].find("w:tcPr/w:vAlign", NS).get(_q("val")),
                "center",
            )
            self.assertIsNone(cells[2].find("w:tcPr/w:vAlign", NS))
        reason_cells = rows[7].findall("w:tc", NS)
        self.assertEqual(
            reason_cells[1].find("w:tcPr/w:vAlign", NS).get(_q("val")),
            "center",
        )

    def test_appendix_edges_trim_but_internal_blank_lines_remain(self) -> None:
        value = "\n \n第一段\n\n第二段\n\t\n"
        root = _document(
            self._render(lesson_original=value, lesson_revised="")
        )
        body = root.find("w:body", NS)
        paragraphs = body.findall("w:p", NS)
        title_index = next(
            index
            for index, paragraph in enumerate(paragraphs)
            if _paragraph_text(paragraph) == "附教案：原稿"
        )
        self.assertEqual(
            [_paragraph_text(paragraph) for paragraph in paragraphs[title_index + 1 :]],
            ["第一段", "", "第二段"],
        )
        self.assertEqual(
            curriculum_content.appendix_lines(
                "\ufeff一、开始\n\n2. 继续\x00\n\u200b"
            ),
            ["一、开始", "", "2. 继续"],
        )
        self.assertEqual(
            curriculum_content.sanitize_export_text(
                "\ufeff一、开始\x00\n\n2. 继续\u200b"
            ),
            "一、开始\n\n2. 继续",
        )

    def test_bom_format_and_illegal_xml_only_appendix_is_omitted(self) -> None:
        for value in (
            "\ufeff",
            "\x00",
            "\u200b",
            "\ufeff\u200b\x00\n\t",
        ):
            with self.subTest(value=repr(value)):
                content = _content(
                    lesson_original=value,
                    lesson_revised=value,
                )
                self.assertEqual(
                    curriculum_content.appendices(content), []
                )
                self.assertEqual(
                    curriculum_content.appendix_lines(value), []
                )
                root = _document(render_curriculum_docx(content))
                text = "".join(
                    (node.text or "") for node in root.iter(_q("t"))
                )
                self.assertNotIn("附教案：原稿", text)
                self.assertNotIn("二次修改", text)
                self.assertEqual(
                    len(root.findall(".//w:sectPr", NS)), 1
                )

    def test_compat_adjust_line_height_in_table_precedes_compat_setting(self) -> None:
        payload = self._render()
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            settings = etree.fromstring(archive.read("word/settings.xml"))
        compat = settings.find("w:compat", NS)
        self.assertIsNotNone(compat)
        children = [child.tag.split("}", 1)[-1] for child in compat]
        self.assertIn("adjustLineHeightInTable", children)
        self.assertIn("compatSetting", children)
        self.assertEqual(
            children.index("adjustLineHeightInTable") + 1,
            children.index("compatSetting"),
        )

    def test_ffff_fffe_filtered_and_valid_cf_retained(self) -> None:
        body = "第一段 👩\u200d🔬\n\nक्\u200cष"
        value = "\uffff\ufffe" + body + "\uffff"
        self.assertEqual(
            curriculum_content.sanitize_export_text(value), body
        )
        self.assertTrue(curriculum_content.is_substantive(body))
        content = _content(lesson_original=value, lesson_revised="\uffff")
        self.assertEqual(
            curriculum_content.appendices(content), ["original"]
        )
        root = _document(render_curriculum_docx(content))
        text = "".join((node.text or "") for node in root.iter(_q("t")))
        self.assertIn("👩\u200d🔬", text)
        self.assertIn("\u200c", text)
        self.assertNotIn("\uffff", text)
        self.assertNotIn("\ufffe", text)

    def test_presence_ignores_cf_and_trims_only_exterior_lines(self) -> None:
        self.assertFalse(
            curriculum_content.is_substantive("\ufeff\u200b\u200c")
        )
        self.assertTrue(
            curriculum_content.is_substantive("👩\u200d🔬")
        )
        value = (
            "\ufeff\n\u200b \n第一段\n\n\u200d\n"
            "👩\u200d🔬\n\n第二段\n\u200c\n"
        )
        self.assertEqual(
            curriculum_content.appendix_lines(value),
            ["第一段", "", "\u200d", "👩\u200d🔬", "", "第二段"],
        )

    def test_missing_labels_cover_core_fields_and_status_conflicts(self) -> None:
        empty = curriculum_content.empty_content()
        missing = curriculum_content.missing_fields(empty)
        for label in (
            "活动名称",
            "活动形式",
            "实施单位",
            "班级（年龄段）",
            "幼儿人数",
            "组织教师",
            "记录人",
            "活动时间",
            "活动目标",
            "活动准备",
            "活动过程记录",
            "调整理由",
        ):
            self.assertIn(label, missing)
        self.assertNotIn("活动目标修订状态", missing)

        ambiguous = _content(
            goals_status="",
            goals_adjustment="保留了调整文字",
        )
        self.assertIn(
            "活动目标修订状态",
            curriculum_content.missing_fields(ambiguous),
        )
        adjusted_empty = _content(
            goals_status="adjusted",
            goals_adjustment="",
        )
        self.assertIn(
            "活动目标调整内容",
            curriculum_content.missing_fields(adjusted_empty),
        )


class CurriculumApiTests(LocalTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.runtime = self.make_runtime()
        self.server = self.start_server(self.runtime)
        self.client = self.server.client()
        self.context = self.initialize(self.client)
        self.profile_id = self.context["profile"]["id"]
        self.class_id = self.context["class"]["id"]

    def _url(self, record_id: str) -> str:
        return f"/api/local/curriculum-deliberations/{record_id}"

    def test_defaults_create_read_retry_and_conflict(self) -> None:
        status, root = self.client.get(
            "/api/local/curriculum-deliberations"
        )
        self.assertEqual(status, 200, root)
        self.assertEqual(root["records"], [])
        self.assertEqual(root["defaults"]["institution"], "示范幼儿园")
        self.assertEqual(root["defaults"]["class_name"], "中一班")
        self.assertEqual(root["defaults"]["recorder"], "王老师")
        self.assertEqual(
            set(root["defaults"]), set(curriculum_content.FIELDS)
        )

        record_id = str(uuid.uuid4())
        content = _content()
        status, saved = self.client.post(
            self._url(record_id) + "/save",
            {"expected_version": 0, "content": content},
        )
        self.assertEqual(status, 200, saved)
        self.assertEqual(saved["version"], 1)
        self.assertEqual(saved["content"], content)
        self.assertEqual(saved["id"], record_id)

        status, listed = self.client.get(
            "/api/local/curriculum-deliberations"
        )
        self.assertEqual(status, 200, listed)
        self.assertEqual(len(listed["records"]), 1)
        self.assertEqual(
            listed["records"][0],
            {
                "id": record_id,
                "version": 1,
                "activity_name": "纸桥怎样更稳",
                "activity_date": "2026-11-09",
                "updated_at": saved["updated_at"],
            },
        )

        changed = dict(content)
        changed["activity_name"] = "折一折再比较"
        status, second = self.client.post(
            self._url(record_id) + "/save",
            {"expected_version": 1, "content": changed},
        )
        self.assertEqual(status, 200, second)
        self.assertEqual(second["version"], 2)
        self.assertEqual(second["content"]["activity_name"], "折一折再比较")

        # The same pending save can be retried with the same id and content.
        status, replay = self.client.post(
            self._url(record_id) + "/save",
            {"expected_version": 1, "content": changed},
        )
        self.assertEqual(status, 200, replay)
        self.assertEqual(replay, second)

        different = dict(changed)
        different["activity_name"] = "不同内容"
        status, conflict = self.client.post(
            self._url(record_id) + "/save",
            {"expected_version": 1, "content": different},
        )
        self.assertEqual(status, 409, conflict)
        self.assertEqual(
            conflict["error"]["code"], "CURRICULUM_VERSION_CONFLICT"
        )
        self.assertEqual(conflict["error"]["details"]["version"], 2)
        status, still = self.client.get(self._url(record_id))
        self.assertEqual(status, 200, still)
        self.assertEqual(still["content"]["activity_name"], "折一折再比较")

        status, missing = self.client.get(
            self._url(str(uuid.uuid4()))
        )
        self.assertEqual(status, 404, missing)
        status, invalid_id = self.client.get(self._url("not-a-uuid"))
        self.assertEqual(status, 422, invalid_id)

    def test_concurrent_saves_compare_the_same_version_atomically(self) -> None:
        from concurrent.futures import ThreadPoolExecutor

        record_id = str(uuid.uuid4())
        base = _content()
        status, saved = self.client.post(
            self._url(record_id) + "/save",
            {"expected_version": 0, "content": base},
        )
        self.assertEqual(status, 200, saved)

        first = dict(base)
        first["activity_name"] = "并发甲"
        second = dict(base)
        second["activity_name"] = "并发乙"
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda content: self.client.post(
                        self._url(record_id) + "/save",
                        {"expected_version": 1, "content": content},
                    ),
                    (first, second),
                )
            )
        self.assertEqual(
            sorted(status for status, _payload in results), [200, 409]
        )
        status, current = self.client.get(self._url(record_id))
        self.assertEqual(status, 200, current)
        self.assertEqual(current["version"], 2)
        self.assertIn(
            current["content"]["activity_name"], {"并发甲", "并发乙"}
        )

    def test_invalid_content_is_rejected_without_persisting(self) -> None:
        content = _content()
        invalid_values = (
            {"activity_form": "unknown"},
            {"goals_status": "unknown"},
            {"activity_date": "2026-1-1"},
            {"child_count": "-1"},
            {"activity_name": 5},
            {"goals_status": "unchanged", "goals_adjustment": "这里还有字"},
            {"preparation_status": "unchanged", "preparation_adjustment": "冲突"},
            {"unexpected": "字段"},
        )
        for index, change in enumerate(invalid_values):
            record_id = str(uuid.uuid4())
            bad = dict(content)
            bad.update(change)
            status, payload = self.client.post(
                self._url(record_id) + "/save",
                {"expected_version": 0, "content": bad},
            )
            self.assertEqual(status, 422, (index, change, payload))
            status, _missing = self.client.get(self._url(record_id))
            self.assertEqual(status, 404)

        status, payload = self.client.post(
            self._url(str(uuid.uuid4())) + "/save",
            {"expected_version": 0, "content": []},
        )
        self.assertEqual(status, 422, payload)

    def test_saved_record_is_scoped_to_profile_and_stable_class(self) -> None:
        record_id = str(uuid.uuid4())
        content = _content()
        status, _saved = self.client.post(
            self._url(record_id) + "/save",
            {"expected_version": 0, "content": content},
        )
        self.assertEqual(status, 200)

        other_class_id = "class-other-curriculum-01"
        session = self.runtime.session()
        try:
            session.add(
                LocalClass(
                    id=other_class_id,
                    name="另一个班",
                    grade="small",
                    header_teacher_names=[],
                    caregiver_name=None,
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
            )
            session.add(
                LocalCurriculumDeliberation(
                    id=str(uuid.uuid4()),
                    profile_id=self.profile_id,
                    class_id=other_class_id,
                    version=1,
                    activity_name="别班活动",
                    activity_date=date(2026, 11, 9),
                    content_json=_content(activity_name="别班活动"),
                    content_hash=curriculum_content.content_hash(
                        _content(activity_name="别班活动")
                    ),
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
            )
            session.commit()
            other_id = session.query(LocalCurriculumDeliberation).filter_by(
                class_id=other_class_id
            ).one().id
        finally:
            session.close()

        status, listed = self.client.get(
            "/api/local/curriculum-deliberations"
        )
        self.assertEqual(status, 200, listed)
        self.assertEqual(
            [item["id"] for item in listed["records"]], [record_id]
        )
        status, hidden = self.client.get(self._url(other_id))
        self.assertEqual(status, 404, hidden)

    def test_export_preview_and_word_for_both_appendices(self) -> None:
        record_id = str(uuid.uuid4())
        content = _content()
        status, saved = self.client.post(
            self._url(record_id) + "/save",
            {"expected_version": 0, "content": content},
        )
        self.assertEqual(status, 200, saved)

        status, preview = self.client.get(
            self._url(record_id) + "/export-preview?version=1"
        )
        self.assertEqual(status, 200, preview)
        self.assertEqual(preview["missing"], [])
        self.assertEqual(
            preview["appendices"], ["original", "revised"]
        )
        self.assertEqual(preview["activity_name"], "纸桥怎样更稳")
        self.assertEqual(preview["activity_date"], "2026-11-09")

        status, stale = self.client.get(
            self._url(record_id) + "/export-preview?version=0"
        )
        self.assertEqual(status, 409, stale)
        status, stale_word = self.client.get(
            self._url(record_id) + "/word?version=0"
        )
        self.assertEqual(status, 409, stale_word)

        status, payload, headers = _get_bytes(
            self.client, self._url(record_id) + "/word?version=1"
        )
        self.assertEqual(status, 200)
        self.assertIn(
            "wordprocessingml.document", headers.get("content-type", "")
        )
        self.assertTrue(payload.startswith(b"PK\x03\x04"))
        self.assertIn(
            "attachment", headers.get("content-disposition", "")
        )
        root = _document(payload)
        text = "".join((node.text or "") for node in root.iter(_q("t")))
        self.assertIn("课程审议记录表", text)
        self.assertIn("附教案：原稿", text)
        self.assertIn("二次修改", text)

        empty_lessons = dict(content)
        empty_lessons["lesson_original"] = " \t\n"
        empty_lessons["lesson_revised"] = ""
        status, second = self.client.post(
            self._url(record_id) + "/save",
            {"expected_version": 1, "content": empty_lessons},
        )
        self.assertEqual(status, 200, second)
        status, preview2 = self.client.get(
            self._url(record_id) + "/export-preview?version=2"
        )
        self.assertEqual(status, 200, preview2)
        self.assertEqual(preview2["appendices"], [])
        status, payload2, _headers = _get_bytes(
            self.client, self._url(record_id) + "/word?version=2"
        )
        self.assertEqual(status, 200)
        text2 = "".join(
            (node.text or "")
            for node in _document(payload2).iter(_q("t"))
        )
        self.assertNotIn("附教案：原稿", text2)
        self.assertNotIn("二次修改", text2)
        self.assertEqual(
            len(_document(payload2).findall(".//w:sectPr", NS)), 1
        )

        artifact_lessons = dict(empty_lessons)
        artifact_lessons["lesson_original"] = "\ufeff"
        artifact_lessons["lesson_revised"] = "\x00"
        status, third = self.client.post(
            self._url(record_id) + "/save",
            {"expected_version": 2, "content": artifact_lessons},
        )
        self.assertEqual(status, 200, third)
        status, preview3 = self.client.get(
            self._url(record_id) + "/export-preview?version=3"
        )
        self.assertEqual(status, 200, preview3)
        self.assertEqual(preview3["appendices"], [])
        status, payload3, _headers = _get_bytes(
            self.client, self._url(record_id) + "/word?version=3"
        )
        self.assertEqual(status, 200)
        text3 = "".join(
            (node.text or "")
            for node in _document(payload3).iter(_q("t"))
        )
        self.assertNotIn("附教案：原稿", text3)
        self.assertNotIn("二次修改", text3)

    def test_word_renders_after_leaving_the_read_transaction(self) -> None:
        record_id = str(uuid.uuid4())
        status, saved = self.client.post(
            self._url(record_id) + "/save",
            {"expected_version": 0, "content": _content()},
        )
        self.assertEqual(status, 200, saved)
        session = self.runtime.session()
        observed: dict[str, bool] = {}

        def fake_renderer(content):
            observed["in_transaction"] = session.in_transaction()
            return b"PK-frozen"

        try:
            with mock.patch.object(
                curriculum_service,
                "render_curriculum_docx",
                side_effect=fake_renderer,
            ):
                payload, content = curriculum_service.word_bytes(
                    session,
                    profile_id=self.profile_id,
                    record_id=record_id,
                    version=1,
                )
        finally:
            session.close()
        self.assertEqual(payload, b"PK-frozen")
        self.assertEqual(content["activity_name"], "纸桥怎样更稳")
        self.assertFalse(observed["in_transaction"])

    def test_saved_record_survives_cold_runtime_reopen(self) -> None:
        record_id = str(uuid.uuid4())
        status, saved = self.client.post(
            self._url(record_id) + "/save",
            {"expected_version": 0, "content": _content()},
        )
        self.assertEqual(status, 200, saved)
        self.server.stop()
        self.runtime.dispose()
        reopened = LocalRuntime(
            data_dir=self.runtime.data_dir,
            credential_root=self.runtime.credential_root,
        )
        reopened.prepare()
        self.addCleanup(reopened.dispose)
        server = self.start_server(reopened)
        client = server.client()
        status, again = client.get(self._url(record_id))
        self.assertEqual(status, 200, again)
        self.assertEqual(again["version"], 1)
        self.assertEqual(again["content"]["activity_name"], "纸桥怎样更稳")


def _get_bytes(client, path: str):
    import http.client

    connection = http.client.HTTPConnection(client.host, client.port, timeout=60)
    try:
        headers = {
            "Host": f"{client.host}:{client.port}",
            "Origin": client.origin,
            "X-App-Session": client.token,
        }
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        body = response.read()
        return response.status, body, {key.lower(): value for key, value in response.getheaders()}
    finally:
        connection.close()


class CurriculumMigrationTests(LocalTestCase):
    def test_head_and_curriculum_table_constraints(self) -> None:
        runtime = self.make_runtime()
        self.assertEqual(
            runtime.current_revision,
            "20261109_0017_local_curriculum_deliberations",
        )
        db = runtime.db_path
        tables = {
            row["name"]
            for row in query_rows(
                db, "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        self.assertIn("local_curriculum_deliberations", tables)
        columns = {
            row["name"]: row
            for row in query_rows(
                db, "PRAGMA table_info('local_curriculum_deliberations')"
            )
        }
        self.assertEqual(
            list(columns),
            [
                "id",
                "profile_id",
                "class_id",
                "version",
                "activity_name",
                "activity_date",
                "content_json",
                "content_hash",
                "created_at",
                "updated_at",
            ],
        )
        self.assertEqual(columns["id"]["pk"], 1)
        foreign_keys = {
            row["table"]
            for row in query_rows(
                db, "PRAGMA foreign_key_list('local_curriculum_deliberations')"
            )
        }
        self.assertEqual(
            foreign_keys, {"local_profile", "local_classes"}
        )
        ddl = query_scalar(
            db,
            "SELECT sql FROM sqlite_master "
            "WHERE type='table' AND name='local_curriculum_deliberations'",
        )
        for name in (
            "ck_local_curriculum_deliberations_id",
            "ck_local_curriculum_deliberations_version",
            "ck_local_curriculum_deliberations_hash",
            "fk_local_curriculum_deliberations_profile",
            "fk_local_curriculum_deliberations_class",
        ):
            self.assertIn(name, ddl)
        index_sql = query_scalar(
            db,
            "SELECT sql FROM sqlite_master WHERE type='index' "
            "AND name='ix_local_curriculum_deliberations_profile_class_updated'",
        )
        self.assertIsNotNone(index_sql)
        self.assertIn("profile_id", index_sql)
        self.assertIn("class_id", index_sql)
        self.assertEqual(query_rows(db, "PRAGMA foreign_key_check"), [])
