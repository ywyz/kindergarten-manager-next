"""Synthetic daily Word detail-field semantics (2026-11-14 teacher report).

No real export sample was supplied.  These tests build a synthetic stored
content snapshot, map it through the production view model and inspect the
real OOXML: morning collective/free-choice values stay independent, numbered
teacher text is not numbered twice by the template, and each post-group block
keeps its own area/game/guidance values.
"""

from __future__ import annotations

import copy
import hashlib
import io
import unittest
import zipfile
from datetime import date
from types import SimpleNamespace
from xml.etree import ElementTree as ET

from app.services.word_export_docx import generate_daily_export_docx
from app.services.word_export_docx import DAILY_TEMPLATE, DAILY_TEMPLATE_SHA256
from app.services.word_export_mapping import map_daily_plan

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}


def _record(content: dict):
    return SimpleNamespace(
        plan_id="synthetic-plan",
        plan_date=date(2026, 11, 6),
        week_number=1,
        weekday=5,
        content_id="synthetic-content",
        content_version=1,
        school_name="合成园",
        class_name="中一班",
        grade="middle",
        creator_display_name="合成教师",
        adopted_content=content,
        split_baseline=None,
    )


def _payload(content: dict) -> bytes:
    return generate_daily_export_docx(
        [map_daily_plan(_record(content), single_afternoon_outdoor=True)]
    )


def _root(payload: bytes):
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        return ET.fromstring(archive.read("word/document.xml"))


def _rows(payload: bytes) -> list[list[list[str]]]:
    """Rows -> cells -> paragraphs (never collapse paragraph boundaries)."""
    return [
        [
            [
                "".join(node.text or "" for node in paragraph.findall(".//w:t", NS))
                for paragraph in cell.findall("w:p", NS)
            ]
            for cell in row.findall("w:tc", NS)
        ]
        for row in _root(payload).findall(".//w:tbl/w:tr", NS)
    ]


def _cell_paragraphs(rows, label: str) -> list[str]:
    for row in rows:
        if row and row[0] and row[0][0].strip() == label:
            return row[1]
    raise AssertionError(f"row {label!r} not found")


def _morning_detail_paragraphs(rows) -> list[str]:
    """Return the shared-detail cell's real paragraphs, in document order."""
    for index, row in enumerate(rows):
        if row and row[0] and row[0][0].strip() == "晨间活动：":
            return rows[index + 1][1]
    raise AssertionError("morning detail row not found")


def _all_paragraphs(rows) -> list[str]:
    return [text for row in rows for cell in row for text in cell if text]


def _block_rows(rows, label: str, count: int):
    for index, row in enumerate(rows):
        if row and row[0] and row[0][0].strip() == label:
            return rows[index : index + count]
    raise AssertionError(f"block {label!r} not found")


def _block_text(rows, label: str, count: int) -> str:
    return "\n".join(
        text
        for block_row in _block_rows(rows, label, count)
        for cell in block_row
        for text in cell
        if text
    )


class DailyWordDetailSemanticsTests(unittest.TestCase):
    def test_morning_only_selected_group_objectives_and_guidance_are_displayed(self):
        content = {
            "morning_games": [
                {
                    "group_id": "c1",
                    "group_kind": "collective",
                    "games": [{"game_id": "g1", "name": "集体游戏甲"}],
                    "focus_guidance": "集体重点甲",
                    "shared_objectives": "集体目标甲",
                    "guidance_points": "集体要点甲",
                },
                {
                    "group_id": "f1",
                    "group_kind": "free_choice",
                    "games": [{"game_id": "g2", "name": "自选游戏乙"}],
                    "focus_guidance": "自选重点乙",
                    "shared_objectives": "自选目标乙",
                    "guidance_points": "自选要点乙",
                },
            ]
        }
        rows = _rows(_payload(content))
        paragraphs = _cell_paragraphs(rows, "晨间活动：")
        # The second row carries the shared detail fields.
        detail = _cell_paragraphs(rows, "")
        text = "\n".join(paragraphs + detail)
        self.assertIn("重点指导：集体游戏甲", detail)
        self.assertNotIn("集体游戏：集体重点甲", detail)
        self.assertNotIn("自主游戏：自选重点乙", detail)
        self.assertIn("活动目标：集体目标甲", detail)
        self.assertIn("指导要点：集体要点甲", detail)
        self.assertNotIn("自选目标乙", text)
        self.assertNotIn("自选要点乙", text)
        self.assertIn("集体游戏：集体游戏甲", paragraphs)
        self.assertIn("自主游戏：自选游戏乙", paragraphs)
        # No merged ambiguous value and no cross-group text.
        self.assertNotIn("集体重点甲；自选重点乙", text)
        self.assertNotIn("自选重点乙；集体重点甲", text)
        self.assertEqual(text.count("重点指导："), 1)

    def test_morning_shared_multiline_values_use_separate_paragraphs(self):
        content = {
            "morning_games": [
                {
                    "group_id": "c1",
                    "group_kind": "collective",
                    "games": [{"game_id": "g1", "name": "集体游戏甲"}],
                    "focus_guidance": "1. 集体重点一\n2. 集体重点二",
                    "shared_objectives": "1. 集体目标一\n2. 集体目标二",
                    "guidance_points": "1. 集体要点一\n2. 集体要点二",
                },
                {
                    "group_id": "f1",
                    "group_kind": "free_choice",
                    "games": [{"game_id": "g2", "name": "自选游戏乙"}],
                    "focus_guidance": "1. 自选重点一\n2. 自选重点二",
                    "shared_objectives": "1. 自选目标一\n2. 自选目标二",
                    "guidance_points": "1. 自选要点一\n2. 自选要点二",
                },
            ]
        }
        detail = _morning_detail_paragraphs(_rows(_payload(content)))
        expected = [
            "重点指导：集体游戏甲",
            "活动目标：1. 集体目标一",
            "2. 集体目标二",
            "指导要点：1. 集体要点一",
            "2. 集体要点二",
        ]
        # Only the selected group's numbered text is exported, with real
        # paragraphs and without an additional group-name prefix.
        self.assertEqual(detail, expected)
        for paragraph in detail:
            self.assertNotIn("\n", paragraph)
            self.assertNotIn("\r", paragraph)

    def test_numbered_text_is_not_numbered_again_by_template_paragraphs(self):
        content = {
            "morning_talk": {
                "topic": "合成话题",
                "questions": "1. 第一问\n2. 第二问",
            },
            "group_activity": {
                "theme": "合成主题",
                "objectives": "1. 目标一\n2. 目标二",
                "preparation": "准备",
                "key_points": "重点",
                "difficult_points": "难点",
                "process": "1. 第一步\n2. 第二步",
            },
        }
        payload = _payload(content)
        root = _root(payload)
        # The writer strips template numbering; teacher/AI numbering stays
        # exactly as the stored text (once), never doubled by Word.
        self.assertEqual(len(root.findall(".//w:numPr", NS)), 0)
        paragraphs = _all_paragraphs(_rows(payload))
        self.assertIn("问题设计：1. 第一问", paragraphs)
        self.assertIn("2. 第二问", paragraphs)
        self.assertIn("活动目标：1. 目标一", paragraphs)
        self.assertIn("2. 目标二", paragraphs)
        self.assertIn("1. 第一步", paragraphs)
        self.assertIn("2. 第二步", paragraphs)
        self.assertNotIn("1. 1. 第一问", "\n".join(paragraphs))
        self.assertNotIn("1. 1. 第一步", "\n".join(paragraphs))

    def test_post_group_blocks_keep_area_game_and_fields_in_their_own_block(self):
        content = {
            "group_activity": {
                "theme": "合成集体活动",
                "objectives": "合成目标",
                "preparation": "合成准备",
                "key_points": "合成重点",
                "difficult_points": "合成难点",
                "process": "合成过程",
            },
            "post_group_games": [
                {
                    "group_id": "area-1",
                    "context_kind": "area",
                    "area": "合成建构区",
                    "games": [{"game_id": "a1", "name": "合成区域游戏甲"}],
                    "focus_guidance": "区域重点甲",
                    "objectives": "区域目标甲",
                    "guidance": "区域指导甲",
                    "support_strategy": "区域支持甲",
                },
                {
                    "group_id": "room-1",
                    "context_kind": "special_room",
                    "area": "合成美工室",
                    "games": [{"game_id": "s1", "name": "合成专用室游戏乙"}],
                    "focus_guidance": "专用室重点乙",
                    "objectives": "专用室目标乙",
                    "guidance": "专用室指导乙",
                    "support_strategy": "专用室支持乙",
                },
            ],
            "afternoon_outdoor": {
                "group_id": "out-1",
                "area": "合成操场",
                "games": [{"game_id": "o1", "name": "合成户外游戏丙"}],
                "observation_focus": "合成户外观察丙",
                "objectives": "合成户外目标丙",
                "guidance": "合成户外指导丙",
                "support_strategy": "合成户外支持丙",
            },
        }
        rows = _rows(_payload(content))
        area_text = _block_text(rows, "室内区域游戏：", 3)
        afternoon_rows = _block_rows(rows, "下午：", 3)
        afternoon_text = _block_text(rows, "下午：", 3)

        self.assertIn("游戏区域：合成建构区", area_text)
        self.assertNotIn("游戏：合成区域游戏甲", area_text)
        self.assertIn("重点指导：合成建构区", area_text)
        self.assertNotIn("区域重点甲", area_text)
        self.assertNotIn("合成专用室", area_text)
        self.assertNotIn("专用室游戏：", "\n".join(_all_paragraphs(rows)))
        self.assertEqual(afternoon_rows[0][1], ["游戏区域：合成操场"])
        self.assertEqual(
            afternoon_rows[1][1],
            [
                "重点观察：合成操场",
                "活动目标：合成户外目标丙",
                "指导要点：合成户外指导丙",
            ],
        )
        self.assertEqual(afternoon_rows[2][1], ["支持策略：合成户外支持丙"])
        self.assertNotIn("合成建构区", afternoon_text)
        self.assertNotIn("合成美工室", afternoon_text)

    def test_afternoon_outdoor_focus_and_points_follow_existing_values(self):
        cases = (
            (
                "area_game_points",
                {
                    "area": "合成操场",
                    "games": [{"game_id": "o1", "name": "合成户外游戏丙"}],
                    "observation_focus": "1. 合成观察甲\n2. 合成观察乙",
                    "objectives": "合成户外目标丙",
                    "guidance": "合成户外指导丙",
                    "support_strategy": "合成户外支持丙",
                },
                ["游戏区域：合成操场"],
                [
                    "重点观察：合成操场",
                    "活动目标：合成户外目标丙",
                    "指导要点：合成户外指导丙",
                ],
                ["支持策略：合成户外支持丙"],
            ),
            (
                "area_without_game",
                {"area": "只有区域的操场"},
                ["游戏区域：只有区域的操场"],
                [
                    "重点观察：只有区域的操场",
                    "活动目标：",
                    "指导要点：",
                ],
                ["支持策略："],
            ),
            (
                "points_without_game_name",
                {
                    "area": "有要点的操场",
                    "observation_focus": "独立观察要点",
                },
                ["游戏区域：有要点的操场"],
                [
                    "重点观察：有要点的操场",
                    "活动目标：",
                    "指导要点：",
                ],
                ["支持策略："],
            ),
            (
                "multiple_games_keep_order",
                {
                    "area": "多游戏操场",
                    "games": [
                        {"game_id": "o3", "name": "合成游戏乙"},
                        {"game_id": "o4", "name": "合成游戏甲"},
                    ],
                },
                ["游戏区域：多游戏操场"],
                [
                    "重点观察：多游戏操场",
                    "活动目标：",
                    "指导要点：",
                ],
                ["支持策略："],
            ),
            (
                "game_without_points",
                {
                    "area": "有游戏的操场",
                    "games": [{"game_id": "o2", "name": "合成户外游戏丁"}],
                },
                ["游戏区域：有游戏的操场"],
                [
                    "重点观察：有游戏的操场",
                    "活动目标：",
                    "指导要点：",
                ],
                ["支持策略："],
            ),
        )
        for name, afternoon, area_lines, detail_lines, support_lines in cases:
            with self.subTest(name=name):
                rows = _block_rows(
                    _rows(_payload({"afternoon_outdoor": afternoon})),
                    "下午：",
                    3,
                )
                # Only one stored area name is shown as the focus. Legacy
                # prose and game names remain stored but are not this field.
                self.assertEqual(rows[0][1], area_lines)
                self.assertEqual(rows[1][1], detail_lines)
                self.assertEqual(rows[2][1], support_lines)
                for paragraph in rows[0][1] + rows[1][1] + rows[2][1]:
                    self.assertFalse(paragraph.startswith("游戏："))
                    self.assertNotIn("\n", paragraph)
                    self.assertNotIn("\r", paragraph)
                self.assertFalse(any(line.startswith("观察要点：") for line in rows[1][1]))

    def test_morning_selects_one_actual_game_name_with_legacy_fallback(self):
        groups = [
            {"group_kind": "collective", "games": [{"name": "集体甲"}, {"name": "集体乙"}], "shared_objectives": "集体目标", "guidance_points": "集体要点"},
            {"group_kind": "free_choice", "games": [{"name": "自选甲"}, {"name": "自选乙"}], "shared_objectives": "自选目标", "guidance_points": "自选要点"},
        ]
        for focus, expected in (("自选乙", "自选乙"), ("1. 教师旧指导\n2. 继续观察", "自选甲"), ("", "集体甲")):
            with self.subTest(focus=focus):
                content = {"morning_games": copy.deepcopy(groups)}
                content["morning_games"][1]["focus_guidance"] = focus
                before = copy.deepcopy(content)
                detail = _morning_detail_paragraphs(_rows(_payload(content)))
                self.assertEqual([line for line in detail if line.startswith("重点指导：")], ["重点指导：" + expected])
                selected = "自选" if focus else "集体"
                other = "集体" if focus else "自选"
                self.assertIn(f"活动目标：{selected}目标", detail)
                self.assertIn(f"指导要点：{selected}要点", detail)
                self.assertNotIn(f"{other}目标", "\n".join(detail))
                self.assertNotIn(f"{other}要点", "\n".join(detail))
                self.assertEqual(content, before)
                self.assertNotIn("教师旧指导", "\n".join(detail))

    def test_same_game_name_in_two_groups_keeps_selected_group_identity(self):
        content = {"morning_games": [
            {"group_kind": "collective", "games": [{"name": "滚球"}], "shared_objectives": "集体目标", "guidance_points": "集体要点"},
            {"group_kind": "free_choice", "games": [{"name": "滚球"}], "focus_guidance": "滚球", "shared_objectives": "自选目标", "guidance_points": "自选要点"},
        ]}
        before = copy.deepcopy(content)
        detail = _morning_detail_paragraphs(_rows(_payload(content)))
        self.assertEqual(detail, ["重点指导：滚球", "活动目标：自选目标", "指导要点：自选要点"])
        self.assertEqual(content, before)
        # The legacy/web path still exports both sets of stored detail text.
        web = _morning_detail_paragraphs(_rows(generate_daily_export_docx([map_daily_plan(_record(content))])))
        self.assertIn("集体游戏：集体目标", web)
        self.assertIn("自主游戏：自选目标", web)

    def test_two_areas_choose_one_name_and_keep_objectives_guidance_support(self):
        content = {
            "post_group_games": [{
                "context_kind": "area", "area": "美工区、建构区",
                "games": [{"name": "会动的小鸟"}], "focus_guidance": "建构区",
                "objectives": "1. 室内目标甲\n2. 室内目标乙", "guidance": "室内指导", "support_strategy": "室内支持",
            }],
            "afternoon_outdoor": {
                "area": "沙水区、攀爬区", "games": [{"name": "户外游戏"}],
                "observation_focus": "攀爬区", "objectives": "户外目标", "guidance": "户外指导", "support_strategy": "户外支持",
            },
        }
        before = copy.deepcopy(content)
        rows = _rows(_payload(content))
        indoor = _block_text(rows, "室内区域游戏：", 3)
        outdoor = _block_text(rows, "下午：", 3)
        self.assertIn("游戏区域：美工区、建构区", indoor)
        self.assertIn("重点指导：建构区", indoor)
        self.assertNotIn("会动的小鸟", indoor)
        self.assertIn("游戏区域：沙水区、攀爬区", outdoor)
        self.assertIn("重点观察：攀爬区", outdoor)
        for value in ("1. 室内目标甲", "2. 室内目标乙", "室内指导", "室内支持"):
            self.assertIn(value, indoor)
        for value in ("户外目标", "户外指导", "户外支持"):
            self.assertIn(value, outdoor)
        self.assertEqual(content, before)
        for separator in ("、", "，", ",", "；", ";", "\n", "\r\n"):
            for explicit_selection in (True, False):
                with self.subTest(separator=separator, explicit_selection=explicit_selection):
                    manual = copy.deepcopy(content)
                    post = manual["post_group_games"][0]
                    afternoon = manual["afternoon_outdoor"]
                    post["area"] = "美工区" + separator + "建构区"
                    afternoon["area"] = "沙水区" + separator + "攀爬区"
                    if not explicit_selection:
                        post["focus_guidance"] = "1. 教师旧重点\n2. 继续指导"
                        afternoon["observation_focus"] = "1. 教师旧观察\n2. 继续观察"
                    original = copy.deepcopy(manual)
                    view = map_daily_plan(_record(manual), single_afternoon_outdoor=True)
                    self.assertEqual(view["post_group_games"][0]["area"], post["area"])
                    self.assertEqual(view["afternoon_outdoor"]["area"], afternoon["area"])
                    actual = _rows(generate_daily_export_docx([view]))
                    indoor_detail = _block_rows(actual, "室内区域游戏：", 3)[1][1]
                    outdoor_detail = _block_rows(actual, "下午：", 3)[1][1]
                    self.assertEqual(
                        [line for line in indoor_detail if line.startswith("重点指导：")],
                        ["重点指导：" + ("建构区" if explicit_selection else "美工区")],
                    )
                    self.assertEqual(
                        [line for line in outdoor_detail if line.startswith("重点观察：")],
                        ["重点观察：" + ("攀爬区" if explicit_selection else "沙水区")],
                    )
                    self.assertNotIn("建构区", indoor_detail)
                    self.assertNotIn("攀爬区", outdoor_detail)
                    self.assertEqual(manual, original)

    def test_legacy_focus_prose_is_hidden_locally_but_default_web_is_unchanged(self):
        content = {
            "post_group_games": [{"context_kind": "area", "area": "美工区、建构区", "games": [{"name": "旧游戏"}], "focus_guidance": "1. 旧重点甲\n2. 旧重点乙"}],
            "afternoon_outdoor": {"area": "沙水区、攀爬区", "games": [{"name": "旧户外游戏"}], "observation_focus": "1. 旧观察甲\n2. 旧观察乙"},
        }
        before = copy.deepcopy(content)
        local = "\n".join(_all_paragraphs(_rows(_payload(content))))
        self.assertIn("重点指导：美工区", local)
        self.assertIn("重点观察：沙水区", local)
        for value in ("旧重点甲", "旧重点乙", "旧观察甲", "旧观察乙", "游戏：旧游戏"):
            self.assertNotIn(value, local)
        web = "\n".join(_all_paragraphs(_rows(generate_daily_export_docx([map_daily_plan(_record(content))]))))
        for value in ("旧重点甲", "旧重点乙", "旧观察甲", "旧观察乙", "游戏：旧游戏"):
            self.assertIn(value, web)
        self.assertEqual(content, before)

    def test_manual_and_historical_text_is_not_rewritten(self):
        content = {
            "morning_talk": {
                "topic": "教师手工话题",
                "questions": "教师手工问题\n保留原文标点，不改成列表。",
            },
            "group_activity": {
                "theme": "手工主题",
                "objectives": "手工目标：保留原文。",
                "preparation": "手工准备",
                "key_points": "手工重点",
                "difficult_points": "手工难点",
                "process": "教师手写步骤一。\n教师手写步骤二。",
            },
            "reflection": "教师手工反思原文。",
        }
        rows = _rows(_payload(content))
        text = "\n".join(_all_paragraphs(rows))
        for value in (
            "教师手工话题",
            "教师手工问题",
            "保留原文标点，不改成列表。",
            "手工目标：保留原文。",
            "教师手写步骤一。",
            "教师手写步骤二。",
            "教师手工反思原文。",
        ):
            self.assertIn(value, text)
        self.assertEqual(text.count("教师手工反思原文。"), 1)

    def test_missing_facts_only_require_fields_used_in_local_word(self):
        from app.local.export_service import collect_daily_missing_facts

        content = {
            "morning_games": [
                {"group_kind": kind, "games": [{"name": kind}], "shared_objectives": "目标", "guidance_points": "指导"}
                for kind in ("collective", "free_choice")
            ],
            "post_group_games": [
                {"context_kind": "special_room", "games": []},
                {"context_kind": "outdoor", "games": []},
                {"context_kind": "area", "area": "美工区、建构区", "games": [], "objectives": "目标", "guidance": "指导", "support_strategy": "支持"},
            ],
            "afternoon_outdoor": {"area": "沙水区、攀爬区", "games": [], "objectives": "目标", "guidance": "指导", "support_strategy": "支持"},
        }
        before = copy.deepcopy(content)
        relevant = [fact for fact in collect_daily_missing_facts(content)
                    if fact["section"] in ("morning_games", "post_group_games", "afternoon_outdoor")]
        self.assertEqual(relevant, [])
        content["post_group_games"][2]["guidance"] = ""
        facts = collect_daily_missing_facts(content)
        fact = next(f for f in facts if f["field"] == "post_group_games[2].guidance")
        self.assertEqual(fact["group_index"], 2)
        content["post_group_games"][2]["guidance"] = "指导"
        self.assertEqual(content, before)

    def test_morning_missing_details_are_only_checked_for_selected_group(self):
        from app.local.export_service import collect_daily_missing_facts

        content = {"morning_games": [
            {"group_id": "collective-id", "group_kind": "collective", "games": [{"name": "集体游戏"}]},
            {"group_id": "selected-id", "group_kind": "free_choice", "games": [{"name": "自选游戏"}], "focus_guidance": "旧重点正文", "shared_objectives": "自选目标", "guidance_points": "自选要点"},
        ]}
        original = copy.deepcopy(content)
        facts = collect_daily_missing_facts(content)
        self.assertFalse(any(f["section"] == "morning_games" for f in facts))
        self.assertEqual(content, original)
        del content["morning_games"][1]["guidance_points"]
        facts = [f for f in collect_daily_missing_facts(content) if f["section"] == "morning_games"]
        self.assertEqual(facts, [{"kind": "empty_field", "field": "morning_games[1].guidance_points", "section": "morning_games", "group_kind": "free_choice", "group_index": 1, "group_id": "selected-id"}])

    def test_legacy_afternoon_missing_facts_point_to_original_group(self):
        from app.local.export_service import collect_daily_missing_facts

        content = {"post_group_games": [
            {"context_kind": "area", "area": "美工区", "objectives": "目标", "guidance": "指导", "support_strategy": "支持"},
            {"group_id": "old-outdoor", "context_kind": "outdoor", "area": "沙水区", "guidance": "指导", "support_strategy": "支持"},
        ]}
        facts = collect_daily_missing_facts(content)
        self.assertFalse(any(f["field"].startswith("afternoon_outdoor") for f in facts))
        relevant = [f for f in facts if f["section"] == "post_group_games"]
        self.assertEqual(relevant, [{"kind": "empty_field", "field": "post_group_games[1].objectives", "section": "post_group_games", "group_index": 1, "group_id": "old-outdoor"}])

    def test_local_reflection_matches_support_paragraph_and_character_format(self):
        prose = "观察幼儿协商材料的方法，提供适当支持。ABC 123，保持原有文字。"
        content = {
            "afternoon_outdoor": {"area": "沙水区", "support_strategy": prose},
            "reflection": prose + "\n" + prose,
        }
        payload = _payload(content)
        root = _root(payload)
        rows = root.findall(".//w:tbl/w:tr", NS)
        support = rows[-2].findall("w:tc", NS)[1]
        reflection = rows[-1].findall("w:tc", NS)[1]
        support_p = support.find("w:p", NS)
        reference_ppr = ET.tostring(support_p.find("w:pPr", NS))
        reference_rpr = ET.tostring(support_p.find("w:r/w:rPr", NS))
        paragraphs = reflection.findall("w:p", NS)
        self.assertEqual(len(paragraphs), 2)
        for paragraph in paragraphs:
            self.assertEqual(ET.tostring(paragraph.find("w:pPr", NS)), reference_ppr)
            self.assertIsNone(paragraph.find("w:pPr/w:spacing", NS))
            for run in paragraph.findall("w:r", NS):
                self.assertEqual(ET.tostring(run.find("w:rPr", NS)), reference_rpr)
                self.assertEqual(run.find("w:rPr/w:sz", NS).get(f"{{{W}}}val"), "24")
                self.assertEqual(run.find("w:rPr/w:rFonts", NS).get(f"{{{W}}}eastAsia"), "仿宋")
        self.assertEqual(ET.tostring(support.find("w:tcPr", NS)), ET.tostring(reflection.find("w:tcPr", NS)))
        self.assertEqual(rows[-1].find("w:trPr/w:trHeight", NS).get(f"{{{W}}}val"), "3084")
        self.assertEqual(root.find(".//w:sectPr/w:docGrid", NS).get(f"{{{W}}}linePitch"), "312")
        template = DAILY_TEMPLATE.read_bytes()
        self.assertEqual(hashlib.sha256(template).hexdigest(), DAILY_TEMPLATE_SHA256)
        with zipfile.ZipFile(io.BytesIO(template)) as original, zipfile.ZipFile(io.BytesIO(payload)) as rendered:
            for member in original.namelist():
                if member != "word/document.xml":
                    self.assertEqual(rendered.read(member), original.read(member), member)

    def test_web_reflection_keeps_original_exact_spacing(self):
        content = {"reflection": "原有网页导出正文。"}
        root = _root(generate_daily_export_docx([map_daily_plan(_record(content))]))
        rows = root.findall(".//w:tbl/w:tr", NS)
        reflection = rows[-1].findall("w:tc", NS)[1]
        spacing = reflection.find("w:p/w:pPr/w:spacing", NS)
        self.assertEqual(spacing.get(f"{{{W}}}line"), "400")
        self.assertEqual(spacing.get(f"{{{W}}}lineRule"), "exact")

    def test_legacy_empty_support_still_provides_body_format_for_reflection(self):
        content = {
            "post_group_games": [{"context_kind": "outdoor", "area": "旧操场"}],
            "reflection": "保留反思文字，不从空支持策略继承默认字体。",
        }
        rows = _root(_payload(content)).findall(".//w:tbl/w:tr", NS)
        reflection = rows[-1].findall("w:tc", NS)[1]
        paragraph = reflection.find("w:p", NS)
        self.assertIsNone(paragraph.find("w:pPr/w:spacing", NS))
        self.assertEqual(paragraph.find("w:r/w:rPr/w:rFonts", NS).get(f"{{{W}}}eastAsia"), "仿宋")
        self.assertEqual(paragraph.find("w:r/w:rPr/w:sz", NS).get(f"{{{W}}}val"), "24")


if __name__ == "__main__":
    unittest.main()
