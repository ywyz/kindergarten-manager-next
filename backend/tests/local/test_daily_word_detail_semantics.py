"""Synthetic daily Word detail-field semantics (2026-11-14 teacher report).

No real export sample was supplied.  These tests build a synthetic stored
content snapshot, map it through the production view model and inspect the
real OOXML: morning collective/free-choice values stay independent, numbered
teacher text is not numbered twice by the template, and each post-group block
keeps its own area/game/guidance values.
"""

from __future__ import annotations

import io
import unittest
import zipfile
from datetime import date
from types import SimpleNamespace
from xml.etree import ElementTree as ET

from app.services.word_export_docx import generate_daily_export_docx
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
    def test_morning_collective_and_free_choice_values_stay_separate(self):
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
        self.assertIn("重点指导：", detail)
        self.assertIn("集体游戏：集体重点甲", detail)
        self.assertIn("自主游戏：自选重点乙", detail)
        self.assertIn("活动目标：", detail)
        self.assertIn("指导要点：", detail)
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
            "重点指导：",
            "集体游戏：1. 集体重点一",
            "2. 集体重点二",
            "自主游戏：1. 自选重点一",
            "2. 自选重点二",
            "活动目标：",
            "集体游戏：1. 集体目标一",
            "2. 集体目标二",
            "自主游戏：1. 自选目标一",
            "2. 自选目标二",
            "指导要点：",
            "集体游戏：1. 集体要点一",
            "2. 集体要点二",
            "自主游戏：1. 自选要点一",
            "2. 自选要点二",
        ]
        # Both groups number their own entries 1./2.; each numbered line must
        # be its own paragraph, never merged into one w:t or duplicated.
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
        room_text = _block_text(rows, "专用室游戏：", 3)
        afternoon_rows = _block_rows(rows, "下午：", 3)
        afternoon_text = _block_text(rows, "下午：", 3)

        self.assertIn("游戏区域：合成建构区", area_text)
        self.assertIn("游戏：合成区域游戏甲", area_text)
        self.assertNotIn("合成专用室", area_text)
        self.assertIn("游戏区域：合成美工室", room_text)
        self.assertIn("游戏：合成专用室游戏乙", room_text)
        self.assertNotIn("合成建构区", room_text)
        self.assertEqual(afternoon_rows[0][1], ["游戏区域：合成操场"])
        self.assertEqual(
            afternoon_rows[1][1],
            [
                "重点观察：合成户外游戏丙",
                "观察要点：合成户外观察丙",
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
                    "重点观察：合成户外游戏丙",
                    "观察要点：1. 合成观察甲",
                    "2. 合成观察乙",
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
                    "重点观察：",
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
                    "重点观察：",
                    "观察要点：独立观察要点",
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
                    "重点观察：合成游戏乙、合成游戏甲",
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
                    "重点观察：合成户外游戏丁",
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
                # ``重点观察`` only carries selected game names; no selected
                # name stays empty instead of falling back to the area.
                self.assertEqual(rows[0][1], area_lines)
                self.assertEqual(rows[1][1], detail_lines)
                self.assertEqual(rows[2][1], support_lines)
                for paragraph in rows[0][1] + rows[1][1] + rows[2][1]:
                    self.assertFalse(paragraph.startswith("游戏："))
                    self.assertNotIn("\n", paragraph)
                    self.assertNotIn("\r", paragraph)
                # ``观察要点`` appears only when stored observation text exists.
                self.assertEqual(
                    any(line.startswith("观察要点：") for line in rows[1][1]),
                    bool(afternoon.get("observation_focus")),
                )

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


if __name__ == "__main__":
    unittest.main()
