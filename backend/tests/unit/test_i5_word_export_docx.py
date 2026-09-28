"""Structure-only tests for the I5 docx generator (slice 2).

No MySQL, no HTTP, no LibreOffice, no browser. Fixtures reuse the real
``word_export_mapping`` view models; the only test helpers added here are for
OOXML structure inspection, never a second copy of the business mapping.
"""

import hashlib
import io
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from lxml import etree

from app.services import word_export_docx as docx
from app.services import word_export_mapping as mapping


W = docx.W


# ---------------------------------------------------------------------------
# OOXML inspection helpers (structure only)
# ---------------------------------------------------------------------------


def _open(data):
    self_ok = zipfile.is_zipfile(io.BytesIO(data))
    assert self_ok
    archive = zipfile.ZipFile(io.BytesIO(data))
    root = etree.fromstring(archive.read("word/document.xml"))
    return archive, root


def _text(root):
    return "".join(t.text or "" for t in root.iter(docx._w("t")))


def _tables(root):
    return root.findall(f".//{docx._w('tbl')}")


def _page_breaks(root):
    return root.findall(f".//{docx._w('br')}[@{docx._w('type')}='page']")


def _red_text(root):
    parts = []
    for run in root.iter(docx._w("r")):
        color = run.find(f"{docx._w('rPr')}/{docx._w('color')}")
        if color is not None and color.get(docx._w("val")) == "FF0000":
            parts.append("".join(t.text or "" for t in run.iter(docx._w("t"))))
    return "".join(parts)


def _grid_spans(row):
    spans = []
    for cell in row.findall(docx._w("tc")):
        grid_span = cell.find(f"{docx._w('tcPr')}/{docx._w('gridSpan')}")
        spans.append(int(grid_span.get(docx._w("val"))) if grid_span is not None else 1)
    return spans


def _assert_no_strikethrough(test, root):
    for tag in ("strike", "dstrike"):
        for element in root.iter(docx._w(tag)):
            value = element.get(docx._w("val"))
            test.assertIn(value, (None, "false", "0"))


# ---------------------------------------------------------------------------
# fixtures (reuse the mapping layer)
# ---------------------------------------------------------------------------


def _daily_content(**overrides):
    content = {
        "morning_games": [
            {
                "group_id": "g1",
                "group_kind": "collective",
                "games": [{"game_id": "x1", "name": "跳圈圈"}],
                "focus_guidance": "重点A",
                "shared_objectives": "目标A",
                "guidance_points": "要点A",
            },
            {
                "group_id": "g2",
                "group_kind": "free_choice",
                "games": [{"game_id": "x2", "name": "滚球"}],
                "focus_guidance": "重点B",
                "shared_objectives": "目标B",
                "guidance_points": "要点B",
            },
        ],
        "morning_talk": {"topic": "话题", "questions": "问题设计"},
        "group_activity": {
            "theme": "活动主题",
            "objectives": "活动目标文本",
            "preparation": "活动准备文本",
            "key_points": "活动重点文本",
            "difficult_points": "活动难点文本",
            "process": "第一步。\n第二步。",
        },
        "post_group_games": [
            {
                "group_id": "g3",
                "context_kind": "area",
                "area": "建构区",
                "games": [{"game_id": "x3", "name": "搭城堡"}],
                "focus_guidance": "区域重点",
                "objectives": "区域目标",
                "guidance": "区域指导",
                "support_strategy": "区域支持",
            }
        ],
        "afternoon_outdoor": {
            "group_id": "g4",
            "area": "操场",
            "games": [{"game_id": "x4", "name": "跑步"}],
            "observation_focus": "户外观察",
            "objectives": "户外目标",
            "guidance": "户外指导",
            "support_strategy": "户外支持",
        },
        "reflection": "一日反思文本",
    }
    content.update(overrides)
    return content


def _daily_record(**kw):
    defaults = dict(
        plan_id="dp1",
        class_id="cls1",
        term_id="ter1",
        plan_date=date(2026, 9, 1),
        week_number=1,
        weekday=2,
        creator_id="tch1",
        creator_display_name="甲老师",
        school_name="阳光园",
        class_name="中一",
        grade="中班",
        content_id="c1",
        content_version=1,
        adopted_content=_daily_content(),
        split_baseline=None,
        warnings=(),
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _daily_view(**kw):
    return mapping.map_daily_plan(_daily_record(**kw))


def _weekly_content(
    *,
    theme="我是中班小朋友",
    det=None,
    slots=None,
    focus=None,
    columns=None,
    materials="纸杯、托盘",
):
    content = {
        "theme": theme,
        "deterministic": det or [],
        "outdoor_game_slots": {
            "collective_1": {
                "source_kind": "manual",
                "name": "老狼",
                "shared_objectives": "目标1",
                "guidance_points": "指导1",
                "focus_guidance": "重点1",
            },
            "collective_2": None,
            "free_choice_1": {
                "source_kind": "manual",
                "name": "圈圈乐",
                "shared_objectives": "目标2",
                "guidance_points": "",
                "focus_guidance": "",
            },
        },
        "focus_area": focus
        if focus is not None
        else {
            "source_kind": "daily_plan",
            "context_kind": "area",
            "area": "攀爬区",
            "name": "攀爬",
            "objectives": "区域目标",
            "guidance": "区域指导",
            "support_strategy": "区域支持",
        },
        "weekly_columns": {
            "key_week_focus": "本周重点内容",
            "environment_setup": "环境创设内容",
            "habit_culture": "生活习惯内容",
            "home_cooperation": "家园共育内容",
        },
        "materials": materials,
    }
    if slots:
        content["outdoor_game_slots"].update(slots)
    if columns:
        content["weekly_columns"].update(columns)
    return content


def _det(day, *, day_state="teaching", plan_state="saved", effective=None):
    return {
        "date": day.isoformat(),
        "day_state": day_state,
        "plan_state": plan_state,
        "source": {},
        "override": {},
        "effective": effective or {},
    }


def _weekly_item(**kw):
    defaults = dict(
        plan_id="wp1",
        term_id="ter1",
        week_number=1,
        confirmed_version=1,
        content=_weekly_content(),
        warnings=(),
        term_start=date(2026, 9, 1),
        term_end=date(2026, 9, 30),
        week_days={
            date(2026, 9, 1): "teaching",
            date(2026, 9, 2): "teaching",
            date(2026, 9, 3): "teaching",
            date(2026, 9, 4): "teaching",
            date(2026, 9, 5): "rest",
            date(2026, 9, 6): "rest",
        },
        school_name="阳光园",
        class_name="中一",
        grade="中班",
        header_teacher_names=["甲老师", "乙老师"],
        caregiver_name="丙老师",
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _weekly_view(**kw):
    return mapping.map_weekly_plan(_weekly_item(**kw))


# ---------------------------------------------------------------------------
# controlled template baseline
# ---------------------------------------------------------------------------


class TemplateAssetTests(unittest.TestCase):
    def test_daily_template_registry_and_structure(self):
        digest = hashlib.sha256(docx.DAILY_TEMPLATE.read_bytes()).hexdigest()
        self.assertEqual(digest, docx.DAILY_TEMPLATE_SHA256)
        with zipfile.ZipFile(docx.DAILY_TEMPLATE) as archive:
            self.assertIn("word/document.xml", archive.namelist())
            root = etree.fromstring(archive.read("word/document.xml"))
        # 5 physical tables, canonical single-day block with 19 rows.
        tables = _tables(root)
        self.assertEqual(len(tables), 5)
        self.assertEqual(len(tables[0].findall(docx._w("tr"))), 19)
        text = _text(root)
        for label in ("晨间活动：", "晨间谈话：", "集体活动：", "室内区域游戏：", "一日活动反思："):
            self.assertIn(label, text)

    def test_weekly_template_registry_and_structure(self):
        digest = hashlib.sha256(docx.WEEKLY_TEMPLATE.read_bytes()).hexdigest()
        self.assertEqual(digest, docx.WEEKLY_TEMPLATE_SHA256)
        with zipfile.ZipFile(docx.WEEKLY_TEMPLATE) as archive:
            names = archive.namelist()
            self.assertIn("word/document.xml", names)
            self.assertIn("word/numbering.xml", names)
            root = etree.fromstring(archive.read("word/document.xml"))
        tables = _tables(root)
        self.assertEqual(len(tables), 5)
        first = tables[0]
        rows = first.findall(docx._w("tr"))
        self.assertEqual(len(rows), 9)
        # Header row: 2 label cells + 5 weekday columns; merged content rows.
        self.assertEqual(len(_grid_spans(rows[0])), 7)
        self.assertEqual(_grid_spans(rows[3]), [1, 1, 5])
        self.assertEqual(_grid_spans(rows[5]), [1, 6])
        text = _text(root)
        for label in ("本周重点", "环境创设", "生活习惯培养", "家园共育", "户外游戏", "区域游戏"):
            self.assertIn(label, text)

    def test_missing_template_raises(self):
        with self.assertRaises(docx.WordTemplateError):
            docx.generate_daily_export_docx(
                [_daily_view()], template_path=Path("/tmp/opencode/no-such-template.docx")
            )

    def test_hash_mismatch_raises(self):
        with self.assertRaises(docx.WordTemplateError):
            docx._read_template_bytes(str(docx.DAILY_TEMPLATE), "0" * 64)

    def test_non_zip_asset_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.docx"
            bad.write_bytes(b"not a zip")
            with self.assertRaises(docx.WordTemplateError):
                docx.generate_daily_export_docx([_daily_view()], template_path=bad)


# ---------------------------------------------------------------------------
# daily plan
# ---------------------------------------------------------------------------


class DailyDocxTests(unittest.TestCase):
    def test_w1_single_complete_structure_and_content(self):
        data = docx.generate_daily_export_docx([_daily_view()])
        _, root = _open(data)
        self.assertEqual(len(_tables(root)), 1)
        self.assertEqual(len(_page_breaks(root)), 0)
        text = _text(root)
        for expected in (
            "阳光园一日活动计划",
            "中班",
            "中一",
            "甲老师",
            "第 1 周",
            "9 月 1 日  周二",
            "体能大循环：",
            "集体游戏：跳圈圈",
            "自主游戏：滚球",
            "重点A",
            "目标B",
            "话题：话题",
            "问题设计：问题设计",
            "活动主题：活动主题",
            "活动准备文本",
            "活动难点文本",
            "第一步。",
            "第二步。",
            "建构区",
            "搭城堡",
            "区域支持",
            "操场",
            "户外观察",
            "户外支持",
            "一日反思文本",
        ):
            self.assertIn(expected, text, expected)
        # No template sample people / sample text survives.
        for residue in ("南通市崇川区樾府幼儿园", "岳炜", "暑假趣事多", "蜜雪冰城"):
            self.assertNotIn(residue, text, residue)

    def test_w1_empty_content_keeps_columns_without_sample(self):
        data = docx.generate_daily_export_docx([_daily_view(adopted_content={})])
        _, root = _open(data)
        text = _text(root)
        for label in (
            "晨间活动：",
            "晨间谈话：",
            "集体活动：",
            "室内区域游戏：",
            "下午：",
            "一日活动反思：",
            "体能大循环：",
            "重点指导：",
            "指导要点：",
            "支持策略：",
        ):
            self.assertIn(label, text, label)
        for residue in ("跳圈圈", "蜜雪冰城", "暑假趣事多", "岳炜", "南通市崇川区樾府幼儿园"):
            self.assertNotIn(residue, text, residue)

    def test_w2_redline_insert_replace_delete(self):
        baseline = "准备纸杯。\n观察变化。\n删除我。"
        final = "准备纸杯。\n缓慢变化。\n新增提醒：先检查纸杯边缘，再开始探索。"
        view = _daily_view(
            adopted_content=_daily_content(
                group_activity={
                    "theme": "主题",
                    "process": final,
                }
            ),
            split_baseline={"group_activity_process": baseline},
        )
        data = docx.generate_daily_export_docx([view])
        _, root = _open(data)
        red = _red_text(root)
        self.assertIn("缓", red)
        self.assertIn("新增提醒：先检查纸杯边缘，再开始探索", red)
        self.assertNotIn("准备纸杯。", red)
        self.assertIn("准备纸杯。", _text(root))
        self.assertNotIn("删除我", _text(root))
        _assert_no_strikethrough(self, root)

    def test_w2_no_baseline_has_no_red(self):
        view = _daily_view(
            adopted_content=_daily_content(
                group_activity={"theme": "主题", "process": "无基准最终过程"}
            ),
            split_baseline=None,
        )
        data = docx.generate_daily_export_docx([view])
        _, root = _open(data)
        self.assertEqual(_red_text(root), "")
        self.assertIn("无基准最终过程", _text(root))

    def test_w3_multi_day_order_and_page_breaks(self):
        views = [
            _daily_view(plan_id="a", plan_date=date(2026, 9, 4), weekday=5),
            _daily_view(plan_id="b", plan_date=date(2026, 9, 1), weekday=2),
            _daily_view(plan_id="c", plan_date=date(2026, 9, 2), weekday=3),
        ]
        data = docx.generate_daily_export_docx(views)
        _, root = _open(data)
        tables = _tables(root)
        self.assertEqual(len(tables), 3)
        self.assertEqual(len(_page_breaks(root)), 2)
        order = [_text(table).split("第")[1].split("周")[0].strip() for table in tables]
        self.assertEqual(order, ["1", "1", "1"])
        dates = [_text(table) for table in tables]
        self.assertIn("9 月 4 日", dates[0])
        self.assertIn("9 月 1 日", dates[1])
        self.assertIn("9 月 2 日", dates[2])

    def test_w3_single_and_merged_same_content(self):
        view = _daily_view()
        single = docx.generate_daily_export_docx([view])
        _, single_root = _open(single)
        merged = docx.generate_daily_export_docx(
            [
                _daily_view(plan_id="z", plan_date=date(2026, 9, 2), weekday=3),
                view,
            ]
        )
        _, merged_root = _open(merged)
        merged_tables = _tables(merged_root)
        self.assertEqual(len(merged_tables), 2)
        self.assertEqual(_text(_tables(single_root)[0]), _text(merged_tables[1]))

    def test_same_kind_post_groups_keep_both_blocks(self):
        content = _daily_content()
        second = dict(content["post_group_games"][0])
        second["context_kind"] = "special_room"
        second["area"] = "美工室"
        content["post_group_games"] = [content["post_group_games"][0], second]
        data = docx.generate_daily_export_docx([_daily_view(adopted_content=content)])
        _, root = _open(data)
        text = _text(root)
        self.assertIn("室内区域游戏：", text)
        self.assertIn("专用室游戏：", text)
        self.assertIn("美工室", text)

    def test_daily_header_replaces_school_and_no_sample_term_range(self):
        data = docx.generate_daily_export_docx([_daily_view(school_name="示范园")])
        _, root = _open(data)
        text = _text(root)
        self.assertIn("示范园一日活动计划", text)
        self.assertNotIn("2026.9-2027.1", text)

    def test_output_zip_preserves_other_members_and_template_hash(self):
        data = docx.generate_daily_export_docx([_daily_view()])
        with zipfile.ZipFile(io.BytesIO(data)) as out:
            with zipfile.ZipFile(docx.DAILY_TEMPLATE) as source:
                self.assertEqual(
                    sorted(out.namelist()), sorted(source.namelist())
                )
                for info in source.infolist():
                    if info.filename != "word/document.xml":
                        self.assertEqual(out.read(info.filename), source.read(info.filename))
        self.assertEqual(
            hashlib.sha256(docx.DAILY_TEMPLATE.read_bytes()).hexdigest(),
            docx.DAILY_TEMPLATE_SHA256,
        )


# ---------------------------------------------------------------------------
# weekly plan
# ---------------------------------------------------------------------------


class WeeklyDocxTests(unittest.TestCase):
    def test_w4_five_columns_holiday_and_missing_plan(self):
        week_days = {
            date(2026, 8, 31): "teaching",
            date(2026, 9, 1): "teaching",
            date(2026, 9, 2): "rest",
            date(2026, 9, 3): "teaching",
            date(2026, 9, 4): "teaching",
        }
        content = _weekly_content(
            theme="主题A",
            det=[
                _det(
                    date(2026, 9, 1),
                    effective={
                        "morning_talk_topic": "谈话一",
                        "group_activity_theme": "活动一",
                    },
                ),
                # no_plan + empty effective -> empty, never labelled holiday.
                _det(
                    date(2026, 9, 3),
                    plan_state="no_plan",
                    effective={
                        "morning_talk_topic": "",
                        "group_activity_theme": "",
                    },
                ),
            ],
        )
        view = _weekly_view(
            week_days=week_days,
            term_start=date(2026, 8, 31),
            term_end=date(2026, 9, 30),
            content=content,
        )
        data = docx.generate_weekly_export_docx([view])
        _, root = _open(data)
        table = _tables(root)[0]
        rows = table.findall(docx._w("tr"))
        self.assertEqual(len(_grid_spans(rows[0])), 7)  # 2 labels + 5 columns
        self.assertEqual(_grid_spans(rows[3]), [1, 1, 5])
        text = _text(table)
        self.assertIn("谈话一", text)
        self.assertIn("活动一", text)
        self.assertIn(docx._HOLIDAY_MARKER, text)
        # The missing-plan teaching day is empty, not a holiday.
        self.assertNotIn("假期", _cells_text(rows[1], 5))
        # Header range = first..last teaching day.
        self.assertIn("2026 年 8 月31日——9月4日", _text(root))

    def test_w4_six_and_seven_teaching_day_columns(self):
        for week_days, expected in (
            (
                {
                    date(2026, 8, 31): "teaching",
                    date(2026, 9, 1): "teaching",
                    date(2026, 9, 5): "teaching",
                },
                6,
            ),
            (
                {
                    date(2026, 9, 5): "teaching",
                    date(2026, 9, 6): "teaching",
                },
                7,
            ),
        ):
            view = _weekly_view(
                week_days=week_days,
                term_start=date(2026, 8, 31),
                term_end=date(2026, 10, 30),
            )
            self.assertEqual(len(view["columns"]), expected)
            data = docx.generate_weekly_export_docx([view])
            _, root = _open(data)
            grid = root.find(f".//{docx._w('tblGrid')}")
            self.assertEqual(len(grid.findall(docx._w("gridCol"))), expected + 2)
            for row in _tables(root)[0].findall(docx._w("tr")):
                self.assertEqual(sum(_grid_spans(row)), expected + 2)

    def test_w4_zero_class_day_week(self):
        week_days = {
            date(2026, 10, 5): "rest",
            date(2026, 10, 6): "rest",
            date(2026, 10, 7): "rest",
            date(2026, 10, 8): "rest",
            date(2026, 10, 9): "rest",
            date(2026, 10, 10): "rest",
            date(2026, 10, 11): "rest",
        }
        content = _weekly_content(
            theme="国庆周",
            det=[
                _det(day, day_state="rest", plan_state="none_required")
                for day in week_days
            ],
        )
        view = _weekly_view(
            week_number=2,
            term_start=date(2026, 9, 28),
            term_end=date(2026, 10, 18),
            week_days=week_days,
            content=content,
        )
        self.assertEqual(len(view["columns"]), 5)
        data = docx.generate_weekly_export_docx([view])
        _, root = _open(data)
        table = _tables(root)[0]
        rows = table.findall(docx._w("tr"))
        self.assertEqual(len(_grid_spans(rows[0])), 7)
        # 5 fixed holiday columns x (晨间谈话 + 集体活动) data cells.
        self.assertEqual(_text(table).count(docx._HOLIDAY_MARKER), 10)
        # Header = term range INTERSECT actual week (section 11.7 option 1).
        self.assertIn("2026 年 10 月5日——10月11日", _text(root))

    def test_w5_multi_week_order_page_breaks_and_numbering(self):
        views = [
            _weekly_view(plan_id="wa", week_number=1),
            _weekly_view(plan_id="wb", week_number=2),
            _weekly_view(plan_id="wc", week_number=3),
        ]
        data = docx.generate_weekly_export_docx(views)
        _, root = _open(data)
        self.assertEqual(len(_tables(root)), 3)
        self.assertEqual(len(_page_breaks(root)), 2)
        # Business content slots must not inherit the template auto-numbering.
        self.assertEqual(len(root.findall(f".//{docx._w('numPr')}")), 0)
        # Each week has its own header paragraph with its own week numeral.
        text = _text(root)
        for numeral in ("一", "二", "三"):
            self.assertIn(f"第（{numeral}）周", text)
        self.assertEqual(text.count("本周重点内容"), 3)
        for residue in ("戚甦甦", "朱维维", "老狼老狼几点了"):
            self.assertNotIn(residue, text, residue)

    def test_w4_outside_term_placeholder_empty_not_holiday(self):
        # Term starts on a Thursday: Mon-Wed are outside the term and must be
        # empty placeholders, never labelled as holidays.
        week_days = {date(2026, 9, 3): "teaching", date(2026, 9, 4): "teaching"}
        view = _weekly_view(
            week_days=week_days,
            term_start=date(2026, 9, 3),
            term_end=date(2026, 9, 30),
            content=_weekly_content(det=[]),
        )
        self.assertEqual(len(view["columns"]), 5)
        data = docx.generate_weekly_export_docx([view])
        _, root = _open(data)
        table = _tables(root)[0]
        rows = table.findall(docx._w("tr"))
        # Data cells 2..6 = Mon..Fri; Mon/Tue are outside the term.
        self.assertEqual(_cells_text(rows[1], 2), "")
        self.assertEqual(_cells_text(rows[1], 3), "")
        self.assertNotIn(docx._HOLIDAY_MARKER, _text(table))

    def test_w6_confirmed_snapshot_fields(self):
        data = docx.generate_weekly_export_docx([_weekly_view()])
        _, root = _open(data)
        table = _tables(root)[0]
        text = _text(table)
        # Two collective + one free choice slot from the confirmed snapshot.
        self.assertIn("集体游戏：1.《老狼》", text)
        self.assertIn("自主游戏：《圈圈乐》", text)
        self.assertIn("目标1", text)
        self.assertIn("指导1", text)
        self.assertIn("重点1", text)
        # Focus area, materials and weekly columns map field by field.
        self.assertIn("攀爬区", text)
        self.assertIn("区域目标", text)
        self.assertIn("区域指导", text)
        self.assertIn("区域支持", text)
        self.assertIn("纸杯、托盘", text)
        self.assertIn("本周重点内容", text)
        self.assertIn("环境创设内容", text)
        self.assertIn("生活习惯内容", text)
        self.assertIn("家园共育内容", text)
        # Header fields.
        self.assertIn("阳光园每周工作计划表", text + _text(root))
        self.assertIn("我是中班小朋友", _text(root))
        self.assertIn("甲老师", _text(root))
        self.assertIn("丙老师", _text(root))
        for residue in ("戚甦甦", "朱维维", "老狼老狼几点了", "我是班级小主人", "国庆放假"):
            self.assertNotIn(residue, _text(root), residue)

    def test_output_zip_preserves_other_members_and_template_hash(self):
        data = docx.generate_weekly_export_docx([_weekly_view()])
        with zipfile.ZipFile(io.BytesIO(data)) as out:
            with zipfile.ZipFile(docx.WEEKLY_TEMPLATE) as source:
                self.assertEqual(sorted(out.namelist()), sorted(source.namelist()))
                for info in source.infolist():
                    if info.filename != "word/document.xml":
                        self.assertEqual(out.read(info.filename), source.read(info.filename))
        self.assertEqual(
            hashlib.sha256(docx.WEEKLY_TEMPLATE.read_bytes()).hexdigest(),
            docx.WEEKLY_TEMPLATE_SHA256,
        )


# ---------------------------------------------------------------------------
# dispatch / guard rails
# ---------------------------------------------------------------------------


class DispatchTests(unittest.TestCase):
    def test_empty_views_rejected(self):
        with self.assertRaises(docx.WordExportError):
            docx.generate_daily_export_docx([])
        with self.assertRaises(docx.WordExportError):
            docx.generate_weekly_export_docx([])

    def test_dispatch_by_kind(self):
        daily = docx.generate_export_docx(mapping.KIND_DAILY, [_daily_view()])
        weekly = docx.generate_export_docx(mapping.KIND_WEEKLY, [_weekly_view()])
        self.assertTrue(zipfile.is_zipfile(io.BytesIO(daily)))
        self.assertTrue(zipfile.is_zipfile(io.BytesIO(weekly)))

    def test_unknown_kind_rejected(self):
        with self.assertRaises(docx.WordExportError):
            docx.generate_export_docx("nope", [_daily_view()])


def _cells_text(row, index):
    cells = row.findall(docx._w("tc"))
    return _text(cells[index])


if __name__ == "__main__":
    unittest.main()
