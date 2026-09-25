"""No-DB unit tests for the I5 Word export mapping pure functions.

Covers the daily two-column mapping, the ``group_activity.process`` redline
(insert / replace / delete / pure move / format-only / no baseline), the weekly
confirmed-snapshot mapping (no_plan override kept, no_plan empty effective,
saved explicit-empty override, rest vs no_plan), zero-class-day weeks and the
header/week number rules. No MySQL, no HTTP, no docx bytes.
"""

import unittest
from datetime import date
from types import SimpleNamespace

from app.services import word_export_mapping as mapping


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
        adopted_content={},
        split_baseline=None,
        warnings=(),
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _det(
    day: date,
    *,
    day_state="teaching",
    plan_state="saved",
    source=None,
    override=None,
    effective=None,
):
    return {
        "date": day.isoformat(),
        "day_state": day_state,
        "plan_state": plan_state,
        "source": source or {},
        "override": override or {},
        "effective": effective or {},
    }


def _weekly_content(
    *,
    theme="主题",
    det=None,
    slots=None,
    focus=None,
    columns=None,
    materials=None,
):
    content = {
        "theme": theme,
        "deterministic": det or [],
        "outdoor_game_slots": {
            key: None for key in mapping.OUTDOOR_SLOT_KEYS
        },
        "focus_area": focus,
        "weekly_columns": {
            key: "" for key in mapping.WEEKLY_COLUMN_KEYS
        },
        "materials": materials,
    }
    if slots:
        content["outdoor_game_slots"].update(slots)
    if columns:
        content["weekly_columns"].update(columns)
    return content


def _weekly_item(**kw):
    defaults = dict(
        plan_id="wp1",
        term_id="ter1",
        week_number=1,
        confirmed_version=1,
        content=_weekly_content(),
        warnings=(),
        term_start=date(2026, 9, 1),
        term_end=date(2026, 9, 28),
        week_days={},
        school_name="阳光园",
        class_name="中一",
        grade="中班",
        header_teacher_names=["甲老师"],
        caregiver_name="王五",
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _red_text(result):
    return "".join(run["text"] for run in result["runs"] if run["red"])


def _plain_text(result):
    return "".join(run["text"] for run in result["runs"] if not run["red"])


class DiffProcessTests(unittest.TestCase):
    def test_no_baseline_outputs_final_without_red(self):
        result = mapping.diff_process(None, "最终过程")
        self.assertFalse(result["has_baseline"])
        self.assertEqual(_red_text(result), "")
        self.assertEqual(_plain_text(result), "最终过程")

    def test_inserted_sentence_is_red(self):
        base = "准备纸杯。\n观察变化。"
        final = "准备纸杯。\n观察变化。\n新增提醒：先检查纸杯边缘，再开始探索。"
        result = mapping.diff_process(base, final)
        self.assertTrue(result["has_baseline"])
        self.assertEqual(
            _red_text(result), "新增提醒：先检查纸杯边缘，再开始探索。"
        )
        self.assertNotIn("新增提醒", _plain_text(result))

    def test_replaced_text_is_red_and_unchanged_not(self):
        # No shared character: the whole replaced word is red.
        result = mapping.diff_process("慢慢倒入水。", "快速倒入水。")
        self.assertEqual(_red_text(result), "快速")
        self.assertEqual(_plain_text(result), "倒入水。")

    def test_replacement_sharing_a_character_reds_only_diff(self):
        # 慢慢 -> 缓慢 shares 慢; the diff must not redden the unchanged char.
        result = mapping.diff_process("慢慢倒入水。", "缓慢倒入水。")
        self.assertEqual(_red_text(result), "缓")
        self.assertIn("慢倒入水。", _plain_text(result))

    def test_pure_deletion_is_omitted(self):
        result = mapping.diff_process("保留。\n删除我。", "保留。")
        self.assertEqual(_red_text(result), "")
        self.assertEqual(_plain_text(result), "保留。")
        self.assertNotIn("删除我", _plain_text(result))

    def test_pure_move_is_not_red(self):
        base = "第一段。\n移动段。\n第三段。\n第四段。"
        final = "第一段。\n第三段。\n移动段。\n第四段。"
        result = mapping.diff_process(base, final)
        self.assertEqual(_red_text(result), "")
        self.assertEqual(
            _plain_text(result), "第一段。\n第三段。\n移动段。\n第四段。"
        )

    def test_format_only_whitespace_change_is_not_red(self):
        # Formatting is not represented in the text: identical text (even with
        # surrounding whitespace changes) must stay unred.
        result = mapping.diff_process("准备纸杯。", "  准备纸杯。  ")
        self.assertEqual(_red_text(result), "")
        self.assertEqual(_plain_text(result), "  准备纸杯。  ")

    def test_identical_text_is_not_red(self):
        result = mapping.diff_process("一模一样。", "一模一样。")
        self.assertEqual(_red_text(result), "")

    def test_split_baseline_process_extraction(self):
        self.assertEqual(
            mapping.split_baseline_process(
                {"group_activity_process": "基准"}
            ),
            "基准",
        )
        self.assertIsNone(mapping.split_baseline_process(None))
        self.assertIsNone(mapping.split_baseline_process({"other": 1}))
        self.assertIsNone(
            mapping.split_baseline_process({"group_activity_process": 3})
        )


class DailyMappingTests(unittest.TestCase):
    def test_fixed_label_and_fields(self):
        record = _daily_record(
            adopted_content={
                "morning_exercise_label": "别的字样",
                "morning_games": [
                    {
                        "group_id": "g1",
                        "group_kind": "collective",
                        "games": [{"game_id": "gm1", "name": "集体游戏"}],
                        "focus_guidance": "重点",
                        "shared_objectives": "目标",
                        "guidance_points": "要点",
                    },
                    {
                        "group_id": "g2",
                        "group_kind": "free_choice",
                        "games": [{"game_id": "gm2", "name": "自主游戏"}],
                    },
                ],
                "morning_talk": {"topic": "话题", "questions": "问题"},
                "group_activity": {"theme": "主题", "process": "过程正文"},
                "reflection": "反思",
            },
            split_baseline={"group_activity_process": "基准"},
        )
        view = mapping.map_daily_plan(record)
        self.assertEqual(view["morning_exercise_label"], "体能大循环")
        self.assertEqual(
            view["morning_games"]["collective"]["games"][0]["name"],
            "集体游戏",
        )
        self.assertEqual(
            view["morning_games"]["free_choice"]["games"][0]["name"],
            "自主游戏",
        )
        self.assertEqual(view["morning_talk"]["topic"], "话题")
        self.assertEqual(view["group_activity"]["theme"], "主题")
        self.assertEqual(view["reflection"], "反思")
        self.assertTrue(view["process"]["has_baseline"])
        # Baseline and final share no character: the final process is red and
        # the baseline text never appears.
        self.assertIn("过程正文", _red_text({"runs": view["process"]["runs"]}))
        self.assertNotIn("基准", _plain_text({"runs": view["process"]["runs"]}))

    def test_no_split_baseline_no_red(self):
        record = _daily_record(
            adopted_content={"group_activity": {"process": "最终"}},
            split_baseline=None,
        )
        view = mapping.map_daily_plan(record)
        self.assertFalse(view["process"]["has_baseline"])
        runs = view["process"]["runs"]
        self.assertEqual(
            "".join(run["text"] for run in runs if run["red"]), ""
        )
        self.assertEqual(
            "".join(run["text"] for run in runs), "最终"
        )


class WeekHeaderAndColumnsTests(unittest.TestCase):
    def test_normal_week_header_is_teaching_min_max(self):
        term_start = date(2026, 9, 1)
        term_end = date(2026, 9, 28)
        week_days = {
            date(2026, 9, 1): "teaching",
            date(2026, 9, 2): "teaching",
            date(2026, 9, 3): "rest",
            date(2026, 9, 4): "teaching",
            date(2026, 9, 5): "rest",
            date(2026, 9, 6): "rest",
        }
        start, end = mapping.compute_header_range(
            term_start, term_end, 1, week_days
        )
        self.assertEqual((start, end), (date(2026, 9, 1), date(2026, 9, 4)))

    def test_zero_class_day_week_header_is_term_intersect_week(self):
        term_start = date(2026, 9, 28)
        term_end = date(2026, 10, 18)
        week_days = {
            date(2026, 10, 5): "rest",
            date(2026, 10, 6): "rest",
            date(2026, 10, 7): "rest",
            date(2026, 10, 8): "rest",
            date(2026, 10, 9): "rest",
            date(2026, 10, 10): "rest",
            date(2026, 10, 11): "rest",
        }
        start, end = mapping.compute_header_range(
            term_start, term_end, 2, week_days
        )
        self.assertEqual((start, end), (date(2026, 10, 5), date(2026, 10, 11)))

    def test_columns_holiday_and_no_plan_cases(self):
        week_days = {
            date(2026, 9, 1): "teaching",
            date(2026, 9, 2): "teaching",
            date(2026, 9, 3): "rest",
            date(2026, 9, 4): "teaching",
        }
        content = _weekly_content(
            det=[
                # no_plan + non-empty effective: the confirmed manual text
                # must be kept (F1), and it is NOT a holiday.
                _det(
                    date(2026, 9, 1),
                    plan_state="no_plan",
                    effective={
                        "morning_talk_topic": "人工谈话",
                        "group_activity_theme": "人工活动",
                    },
                ),
                # no_plan + empty effective -> empty, still not holiday.
                _det(
                    date(2026, 9, 2),
                    plan_state="no_plan",
                    effective={
                        "morning_talk_topic": "",
                        "group_activity_theme": "",
                    },
                ),
                # rest is a holiday; any effective must not leak through.
                _det(
                    date(2026, 9, 3),
                    day_state="rest",
                    plan_state="none_required",
                    effective={"morning_talk_topic": "不应输出"},
                ),
                # saved + explicit empty-string override stays empty and is
                # not refilled from source.
                _det(
                    date(2026, 9, 4),
                    plan_state="saved",
                    source={
                        "morning_talk_topic": "源谈话",
                        "group_activity_theme": "源活动",
                    },
                    override={
                        "morning_talk_topic": "",
                        "group_activity_theme": "",
                    },
                    effective={
                        "morning_talk_topic": "",
                        "group_activity_theme": "",
                    },
                ),
            ]
        )
        columns = {
            c["date"]: c
            for c in mapping.build_week_columns(
                week_days, content, week_start=date(2026, 8, 31)
            )
        }
        # Fixed Mon-Fri only: Sat/Sun are rest and must not become columns.
        self.assertEqual(
            list(columns),
            [
                "2026-08-31",
                "2026-09-01",
                "2026-09-02",
                "2026-09-03",
                "2026-09-04",
            ],
        )
        # 08-31 is not in the clipped week_days -> out-of-term placeholder.
        self.assertTrue(columns["2026-08-31"]["holiday"])
        self.assertTrue(columns["2026-08-31"]["outside_term"])
        self.assertEqual(columns["2026-08-31"]["morning_talk_topic"], "")
        self.assertEqual(columns["2026-09-01"]["morning_talk_topic"], "人工谈话")
        self.assertEqual(
            columns["2026-09-01"]["group_activity_theme"], "人工活动"
        )
        self.assertFalse(columns["2026-09-01"]["holiday"])
        self.assertFalse(columns["2026-09-01"]["outside_term"])
        self.assertEqual(columns["2026-09-02"]["morning_talk_topic"], "")
        self.assertFalse(columns["2026-09-02"]["holiday"])
        self.assertEqual(columns["2026-09-02"]["plan_state"], "no_plan")
        self.assertTrue(columns["2026-09-03"]["holiday"])
        self.assertFalse(columns["2026-09-03"]["outside_term"])
        self.assertEqual(columns["2026-09-03"]["morning_talk_topic"], "")
        self.assertEqual(columns["2026-09-04"]["morning_talk_topic"], "")
        self.assertEqual(
            columns["2026-09-04"]["group_activity_theme"], ""
        )
        self.assertFalse(columns["2026-09-04"]["holiday"])

    def test_weekend_and_partial_week_columns(self):
        def cols(week_days, week_start):
            return [
                c["weekday"]
                for c in mapping.build_week_columns(
                    week_days, _weekly_content(), week_start=week_start
                )
            ]

        week_start = date(2026, 8, 31)
        # Ordinary week: Mon-Fri teaching, weekend rest -> five columns.
        self.assertEqual(
            cols(
                {
                    date(2026, 8, 31): "teaching",
                    date(2026, 9, 1): "teaching",
                    date(2026, 9, 2): "teaching",
                    date(2026, 9, 3): "teaching",
                    date(2026, 9, 4): "teaching",
                    date(2026, 9, 5): "rest",
                    date(2026, 9, 6): "rest",
                },
                week_start,
            ),
            [1, 2, 3, 4, 5],
        )
        # Saturday teaching -> six columns.
        self.assertEqual(
            cols(
                {
                    date(2026, 9, 1): "teaching",
                    date(2026, 9, 5): "teaching",
                    date(2026, 9, 6): "rest",
                },
                week_start,
            ),
            [1, 2, 3, 4, 5, 6],
        )
        # Sunday teaching -> six columns.
        self.assertEqual(
            cols(
                {
                    date(2026, 9, 1): "teaching",
                    date(2026, 9, 5): "rest",
                    date(2026, 9, 6): "teaching",
                },
                week_start,
            ),
            [1, 2, 3, 4, 5, 7],
        )
        # Both weekend days teaching -> seven columns.
        self.assertEqual(
            cols(
                {
                    date(2026, 9, 5): "teaching",
                    date(2026, 9, 6): "teaching",
                },
                week_start,
            ),
            [1, 2, 3, 4, 5, 6, 7],
        )
        # A resting weekday still keeps its fixed column.
        rest_monday = cols(
            {date(2026, 8, 31): "rest", date(2026, 9, 1): "teaching"}, week_start
        )
        self.assertEqual(rest_monday, [1, 2, 3, 4, 5])

        # Zero-teaching-day week -> five fixed holiday columns.
        zero_week_days = {
            date(2026, 10, 5): "rest",
            date(2026, 10, 6): "rest",
            date(2026, 10, 7): "rest",
            date(2026, 10, 8): "rest",
            date(2026, 10, 9): "rest",
            date(2026, 10, 10): "rest",
            date(2026, 10, 11): "rest",
        }
        zero_columns = mapping.build_week_columns(
            zero_week_days, _weekly_content(), week_start=date(2026, 10, 5)
        )
        self.assertEqual([c["weekday"] for c in zero_columns], [1, 2, 3, 4, 5])
        self.assertTrue(all(c["holiday"] for c in zero_columns))
        self.assertTrue(all(not c["outside_term"] for c in zero_columns))

    def test_term_start_partial_week_keeps_fixed_columns(self):
        # Term starts on a Thursday: Mon-Wed are outside the term but the fixed
        # weekday columns must still exist as empty placeholders.
        week_days = {
            date(2026, 9, 3): "teaching",
            date(2026, 9, 4): "teaching",
        }
        columns = mapping.build_week_columns(
            week_days, _weekly_content(), week_start=date(2026, 8, 31)
        )
        self.assertEqual([c["weekday"] for c in columns], [1, 2, 3, 4, 5])
        self.assertEqual(
            [c["outside_term"] for c in columns], [True, True, True, False, False]
        )
        for column in columns[:3]:
            self.assertTrue(column["holiday"])
            self.assertEqual(column["morning_talk_topic"], "")
            self.assertEqual(column["group_activity_theme"], "")

    def test_term_end_partial_week_keeps_fixed_columns(self):
        # Term ends on a Tuesday: Wed-Fri are outside the term placeholders.
        week_days = {
            date(2026, 12, 1): "teaching",
            date(2026, 12, 2): "teaching",
        }
        columns = mapping.build_week_columns(
            week_days, _weekly_content(), week_start=date(2026, 11, 30)
        )
        self.assertEqual([c["weekday"] for c in columns], [1, 2, 3, 4, 5])
        self.assertEqual(
            [c["outside_term"] for c in columns],
            [True, False, False, True, True],
        )
        self.assertTrue(all(c["holiday"] for c in columns[3:]))


class WeeklyMappingTests(unittest.TestCase):
    def test_zero_class_day_single_plan_view(self):
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
        item = _weekly_item(
            week_number=2,
            term_start=date(2026, 9, 28),
            term_end=date(2026, 10, 18),
            week_days=week_days,
            content=content,
        )
        view = mapping.map_weekly_plan(item)
        self.assertEqual(view["week_number"], 2)
        self.assertEqual(
            view["date_range"],
            {"start": date(2026, 10, 5), "end": date(2026, 10, 11)},
        )
        self.assertEqual(len(view["columns"]), 5)
        self.assertTrue(all(c["holiday"] for c in view["columns"]))
        self.assertEqual(
            [c["morning_talk_topic"] for c in view["columns"]], [""] * 5
        )

    def test_week_number_not_recomputed_from_columns(self):
        # Fewer display columns than the week number must not change the week.
        week_days = {date(2026, 9, 28): "teaching"}
        content = _weekly_content(
            det=[
                _det(
                    date(2026, 9, 28),
                    effective={
                        "morning_talk_topic": "谈话",
                        "group_activity_theme": "活动",
                    },
                )
            ]
        )
        item = _weekly_item(
            week_number=5,
            term_start=date(2026, 9, 1),
            term_end=date(2026, 9, 30),
            week_days=week_days,
            content=content,
        )
        view = mapping.map_weekly_plan(item)
        self.assertEqual(view["week_number"], 5)
        self.assertEqual(len(view["columns"]), 5)
        self.assertEqual(
            [c["date"] for c in view["columns"]],
            [
                "2026-09-28",
                "2026-09-29",
                "2026-09-30",
                "2026-10-01",
                "2026-10-02",
            ],
        )
        self.assertEqual(
            view["date_range"],
            {"start": date(2026, 9, 28), "end": date(2026, 9, 28)},
        )

    def test_confirmed_snapshot_mapping_of_manual_slots(self):
        week_days = {date(2026, 9, 1): "teaching"}
        content = _weekly_content(
            det=[
                _det(
                    date(2026, 9, 1),
                    effective={
                        "morning_talk_topic": "谈话",
                        "group_activity_theme": "活动",
                    },
                )
            ],
            slots={
                "collective_1": {
                    "source_kind": "manual",
                    "name": "手工集体",
                    "shared_objectives": "目标",
                    "guidance_points": "指导",
                    "focus_guidance": "重点",
                },
            },
            focus={
                "source_kind": "daily_plan",
                "context_kind": "area",
                "area": "建构区",
                "name": "重点区域",
                "objectives": "目标",
                "guidance": "指导",
                "support_strategy": "支持",
            },
            columns={"key_week_focus": "重点"},
            materials=None,
        )
        item = _weekly_item(week_days=week_days, content=content)
        view = mapping.map_weekly_plan(item)
        slot = view["outdoor_game_slots"]["collective_1"]
        self.assertEqual(slot["source_kind"], "manual")
        self.assertEqual(slot["name"], "手工集体")
        self.assertEqual(view["focus_area"]["name"], "重点区域")
        self.assertEqual(view["weekly_columns"]["key_week_focus"], "重点")
        self.assertIsNone(view["materials"])
        self.assertEqual(view["header"]["theme"], "主题")


if __name__ == "__main__":
    unittest.main()
