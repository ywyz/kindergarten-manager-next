"""Pure synthetic contract for the daily Word outdoor position (#25).

No database, server, host or filesystem fixture is used.  The test builds
stored-content snapshots, maps them through the production view model and
inspects the real generated OOXML.
"""

from __future__ import annotations

import io
import unittest
import zipfile
from datetime import date
from types import SimpleNamespace
from xml.etree import ElementTree as ET

from app.services.word_export_docx import generate_daily_export_docx
from app.services.word_export_mapping import (
    legacy_outdoor_groups,
    legacy_outdoor_warning,
    map_daily_plan,
)

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}


def _record(content: dict, *, plan_date: date = date(2026, 11, 6)):
    return SimpleNamespace(
        plan_id="p1",
        plan_date=plan_date,
        week_number=1,
        weekday=5,
        content_id="c1",
        content_version=1,
        school_name="合成园",
        class_name="中一班",
        grade="middle",
        creator_display_name="合成教师",
        adopted_content=content,
        split_baseline=None,
    )


def _generate(content: dict):
    view = map_daily_plan(
        _record(content), single_afternoon_outdoor=True
    )
    return view, generate_daily_export_docx([view])


def _rows(payload: bytes) -> list[list[str]]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    return [
        [
            "".join(node.text or "" for node in cell.findall(".//w:t", NS))
            for cell in row.findall("w:tc", NS)
        ]
        for row in root.findall(".//w:tbl/w:tr", NS)
    ]


def _text(rows: list[list[str]]) -> str:
    return "\n".join("\t".join(cells) for cells in rows)


def _labels(rows: list[list[str]], label: str) -> list[list[str]]:
    return [row for row in rows if row and row[0].strip() == label]


class DailyOutdoorExportContractTests(unittest.TestCase):
    def test_real_afternoon_suppresses_the_independent_upper_outdoor_block(self):
        content = {
            "post_group_games": [
                {
                    "group_id": "area1",
                    "context_kind": "area",
                    "area": "合成室内区域",
                    "games": [{"game_id": "a1", "name": "合成室内游戏"}],
                },
                {
                    "group_id": "old-outdoor",
                    "context_kind": "outdoor",
                    "area": "旧上方操场",
                    "games": [{"game_id": "o1", "name": "旧上方户外游戏"}],
                    "focus_guidance": "旧上方重点",
                    "objectives": "旧上方目标",
                    "guidance": "旧上方指导",
                    "support_strategy": "旧上方支持",
                },
                {
                    "group_id": "special1",
                    "context_kind": "special_room",
                    "area": "合成专用室",
                    "games": [{"game_id": "s1", "name": "合成专用室游戏"}],
                },
            ],
            "afternoon_outdoor": {
                "group_id": "afternoon1",
                "area": "合成下午操场",
                "games": [{"game_id": "p1", "name": "合成下午户外游戏"}],
                "observation_focus": "下午重点观察",
                "objectives": "下午目标",
                "guidance": "下午指导",
                "support_strategy": "下午支持",
            },
        }
        view, payload = _generate(content)
        self.assertEqual(
            [group["context_kind"] for group in view["post_group_games"]],
            ["area", "special_room"],
        )
        self.assertEqual(view["afternoon_outdoor_legacy"], [])
        self.assertEqual(view["afternoon_outdoor"]["area"], "合成下午操场")
        self.assertIsNone(legacy_outdoor_warning(content, date(2026, 11, 6)))

        rows = _rows(payload)
        text = _text(rows)
        self.assertEqual(len(_labels(rows, "户外游戏：")), 0)
        self.assertEqual(len(_labels(rows, "下午：户外游戏")), 1)
        self.assertEqual(len(_labels(rows, "室内区域游戏：")), 1)
        self.assertEqual(len(_labels(rows, "专用室游戏：")), 1)
        self.assertIn("合成下午户外游戏", text)
        self.assertNotIn("旧上方户外游戏", text)
        self.assertNotIn("旧上方操场", text)

    def test_only_old_upper_outdoor_migrates_to_the_afternoon_position(self):
        content = {
            "post_group_games": [
                {
                    "group_id": "old-outdoor",
                    "context_kind": "outdoor",
                    "area": "旧上方操场",
                    "games": [{"game_id": "o1", "name": "旧上方户外游戏"}],
                    "focus_guidance": "旧上方重点",
                    "objectives": "旧上方目标",
                    "guidance": "旧上方指导",
                    "support_strategy": "旧上方支持",
                }
            ]
        }
        groups = legacy_outdoor_groups(content)
        self.assertEqual([group["group_id"] for group in groups], ["old-outdoor"])
        warning = legacy_outdoor_warning(content, date(2026, 11, 6))
        self.assertIsNotNone(warning)
        self.assertEqual(warning["code"], "legacy_outdoor_moved_to_afternoon")
        self.assertIn("旧版日计划上方「户外游戏」", warning["message"])
        self.assertIn("下午户外栏", warning["message"])
        self.assertIn("核对或补录", warning["message"])

        view, payload = _generate(content)
        self.assertEqual(view["post_group_games"], [])
        self.assertIsNone(view["afternoon_outdoor"])
        self.assertEqual(len(view["afternoon_outdoor_legacy"]), 1)
        rows = _rows(payload)
        text = _text(rows)
        self.assertEqual(len(_labels(rows, "户外游戏：")), 0)
        self.assertEqual(len(_labels(rows, "下午：户外游戏")), 1)
        self.assertIn("来源：旧版日计划上方「户外游戏」栏", text)
        for value in (
            "旧上方操场",
            "旧上方户外游戏",
            "旧上方重点",
            "旧上方目标",
            "旧上方指导",
            "旧上方支持",
        ):
            self.assertIn(value, text)

    def test_multiple_old_outdoor_groups_keep_their_order(self):
        content = {
            "post_group_games": [
                {
                    "group_id": "old-1",
                    "context_kind": "outdoor",
                    "area": "旧操场一",
                    "games": [{"name": "旧组一游戏"}],
                    "focus_guidance": "旧组一重点",
                    "objectives": "旧组一目标",
                    "guidance": "旧组一指导",
                    "support_strategy": "旧组一支持",
                },
                {
                    "group_id": "old-2",
                    "context_kind": "outdoor",
                    "area": "旧操场二",
                    "games": [{"name": "旧组二游戏"}],
                    "focus_guidance": "旧组二重点",
                    "objectives": "旧组二目标",
                    "guidance": "旧组二指导",
                    "support_strategy": "旧组二支持",
                },
            ]
        }
        warning = legacy_outdoor_warning(content, date(2026, 11, 6))
        self.assertIn("2 组", warning["message"])
        _view, payload = _generate(content)
        text = _text(_rows(payload))
        self.assertIn("下午：户外游戏", text)
        self.assertIn("旧组一游戏", text)
        self.assertIn("旧组二游戏", text)
        self.assertLess(text.index("旧组一游戏"), text.index("旧组二游戏"))
        self.assertLess(text.index("旧组一目标"), text.index("旧组二目标"))
        self.assertLess(text.index("旧组一支持"), text.index("旧组二支持"))

    def test_placeholder_only_old_upper_outdoor_is_not_migrated(self):
        content = {
            "post_group_games": [
                {
                    "group_id": "placeholder",
                    "context_kind": "outdoor",
                    "area": "户外场地（一般建议）",
                    "games": [],
                }
            ],
            "afternoon_outdoor": {},
        }
        self.assertEqual(legacy_outdoor_groups(content), [])
        self.assertIsNone(legacy_outdoor_warning(content, date(2026, 11, 6)))
        _view, payload = _generate(content)
        text = _text(_rows(payload))
        self.assertIn("下午：户外游戏", text)
        self.assertNotIn("来源：旧版日计划上方", text)
        self.assertEqual(len(_labels(_rows(payload), "户外游戏：")), 0)



    def test_known_type_matched_area_placeholders_are_removed_locally(self):
        content = {
            "post_group_games": [
                {
                    "group_id": "area1",
                    "context_kind": "area",
                    "area": "室内区域（一般建议）",
                    "games": [{"name": "室内游戏"}],
                },
                {
                    "group_id": "special1",
                    "context_kind": "special_room",
                    "area": "合成专用室",
                    "games": [{"name": "专用室游戏"}],
                },
            ],
            "afternoon_outdoor": {
                "area": "户外场地（一般建议）",
                "games": [{"name": "下午游戏"}],
                "observation_focus": "下午观察",
            },
        }
        view, payload = _generate(content)
        self.assertEqual(view["post_group_games"][0]["area"], "")
        self.assertEqual(view["post_group_games"][1]["area"], "合成专用室")
        self.assertEqual(view["afternoon_outdoor"]["area"], "")
        text = _text(_rows(payload))
        self.assertNotIn("室内区域（一般建议）", text)
        self.assertNotIn("户外场地（一般建议）", text)
        self.assertIn("室内游戏", text)
        self.assertIn("专用室游戏", text)
        self.assertIn("下午游戏", text)
        self.assertEqual(len(_labels(_rows(payload), "室内区域游戏：")), 1)
        self.assertEqual(len(_labels(_rows(payload), "下午：户外游戏")), 1)

    def test_similar_and_wrong_context_strings_are_preserved(self):
        content = {
            "post_group_games": [
                {
                    "group_id": "teacher-area",
                    "context_kind": "area",
                    "area": "小操场（一般建议）",
                    "games": [{"name": "教师游戏"}],
                    "guidance": "教师补充：一般建议注意安全",
                },
                {
                    "group_id": "wrong-type",
                    "context_kind": "area",
                    "area": "户外场地（一般建议）",
                    "games": [{"name": "室内区域（一般建议）"}],
                },
                {
                    "group_id": "special",
                    "context_kind": "special_room",
                    "area": "室内区域（一般建议）",
                    "games": [{"name": "专用室游戏"}],
                },
            ],
            "afternoon_outdoor": {
                "area": "小操场（一般建议）",
                "games": [{"name": "下午游戏"}],
                "guidance": "下午教师补充：一般建议保留",
            },
        }
        view, payload = _generate(content)
        self.assertEqual(view["post_group_games"][0]["area"], "小操场（一般建议）")
        self.assertEqual(view["post_group_games"][1]["area"], "户外场地（一般建议）")
        self.assertEqual(view["post_group_games"][2]["area"], "室内区域（一般建议）")
        self.assertEqual(view["afternoon_outdoor"]["area"], "小操场（一般建议）")
        text = _text(_rows(payload))
        for value in (
            "小操场（一般建议）",
            "户外场地（一般建议）",
            "室内区域（一般建议）",
            "教师补充：一般建议注意安全",
            "下午教师补充：一般建议保留",
        ):
            self.assertIn(value, text)

    def test_legacy_migration_removes_its_exact_outdoor_placeholder(self):
        content = {
            "post_group_games": [
                {
                    "group_id": "old-outdoor",
                    "context_kind": "outdoor",
                    "area": "户外场地（一般建议）",
                    "games": [{"name": "旧户外游戏"}],
                    "focus_guidance": "旧重点",
                }
            ]
        }
        view, payload = _generate(content)
        self.assertEqual(view["afternoon_outdoor_legacy"][0]["area"], "")
        text = _text(_rows(payload))
        self.assertNotIn("户外场地（一般建议）", text)
        self.assertIn("旧户外游戏", text)
        self.assertIn("旧重点", text)
        self.assertIn("来源：旧版日计划上方「户外游戏」栏", text)
        self.assertIsNotNone(legacy_outdoor_warning(content, date(2026, 11, 6)))

    def test_default_legacy_contract_keeps_exact_placeholders(self):
        content = {
            "post_group_games": [
                {
                    "group_id": "area1",
                    "context_kind": "area",
                    "area": "室内区域（一般建议）",
                    "games": [{"name": "室内游戏"}],
                }
            ],
            "afternoon_outdoor": {
                "area": "户外场地（一般建议）",
                "games": [{"name": "下午游戏"}],
            },
        }
        view = map_daily_plan(_record(content))
        self.assertEqual(view["post_group_games"][0]["area"], "室内区域（一般建议）")
        self.assertEqual(view["afternoon_outdoor"]["area"], "户外场地（一般建议）")
        text = _text(_rows(generate_daily_export_docx([view])))
        self.assertIn("室内区域（一般建议）", text)
        self.assertIn("户外场地（一般建议）", text)

    def test_empty_labels_keep_the_existing_structure(self):
        _view, payload = _generate({})
        rows = _rows(payload)
        self.assertEqual(len(_labels(rows, "室内区域游戏：")), 1)
        self.assertEqual(len(_labels(rows, "下午：户外游戏")), 1)
        text = _text(rows)
        self.assertNotIn("室内区域（一般建议）", text)
        self.assertNotIn("户外场地（一般建议）", text)

    def test_default_mapping_keeps_the_legacy_web_contract(self):
        content = {
            "post_group_games": [
                {
                    "group_id": "area1",
                    "context_kind": "area",
                    "area": "合成室内区域",
                    "games": [{"name": "室内游戏"}],
                },
                {
                    "group_id": "old-outdoor",
                    "context_kind": "outdoor",
                    "area": "旧上方操场",
                    "games": [{"name": "旧上方户外游戏"}],
                },
            ],
            "afternoon_outdoor": {
                "area": "合成下午操场",
                "games": [{"name": "下午游戏"}],
            },
        }
        view = map_daily_plan(_record(content))
        self.assertEqual(
            [group["context_kind"] for group in view["post_group_games"]],
            ["area", "outdoor"],
        )
        self.assertNotIn("afternoon_outdoor_legacy", view)
        rows = _rows(generate_daily_export_docx([view]))
        self.assertEqual(len(_labels(rows, "户外游戏：")), 1)
        self.assertEqual(len(_labels(rows, "下午：户外游戏")), 1)
        self.assertIn("旧上方户外游戏", _text(rows))
        self.assertIn("下午游戏", _text(rows))

    def test_ordinary_area_and_special_room_blocks_keep_their_layout(self):
        content = {
            "post_group_games": [
                {
                    "group_id": "area1",
                    "context_kind": "area",
                    "area": "合成室内区域",
                    "games": [{"name": "室内游戏"}],
                },
                {
                    "group_id": "special1",
                    "context_kind": "special_room",
                    "area": "合成专用室",
                    "games": [{"name": "专用室游戏"}],
                },
            ],
            "afternoon_outdoor": {
                "area": "下午操场",
                "games": [{"name": "下午游戏"}],
            },
        }
        view, payload = _generate(content)
        self.assertEqual(
            [group["context_kind"] for group in view["post_group_games"]],
            ["area", "special_room"],
        )
        rows = _rows(payload)
        self.assertEqual(len(_labels(rows, "室内区域游戏：")), 1)
        self.assertEqual(len(_labels(rows, "专用室游戏：")), 1)
        self.assertEqual(len(_labels(rows, "户外游戏：")), 0)
        self.assertIn("室内游戏", _text(rows))
        self.assertIn("专用室游戏", _text(rows))
        self.assertIn("下午游戏", _text(rows))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
