"""#23 daily process contract and Word redline tests (pure, no database)."""

from __future__ import annotations

import unittest

from app.daily_process_contract import (
    ADAPT_PATCH_SCHEMA,
    DailyProcessContractError,
    expand_adapt_patch,
    validate_adapt_change,
    validate_split_cleanup,
)
from app.services.word_export_mapping import diff_process

BASE = "1. 导入\n师：说说颜色。\n2. 探索\n师：比较两片叶子。\n3. 回顾\n师：分享发现。"
SAVED = BASE
TWO = "1. 导入\n师：指一指红色。\n2. 探索\n师：拿着同色叶子。\n3. 回顾\n师：分享发现。"


def changed(index: int, text: str, process: str = BASE) -> str:
    steps = process.split("\n")
    lines = process.split("\n")
    starts = [i for i, line in enumerate(lines) if line[:1].isdigit()]
    start = starts[index]
    end = starts[index + 1] if index + 1 < len(starts) else len(lines)
    lines[start:end] = text.split("\n")
    return "\n".join(lines)


class SplitCleanupTests(unittest.TestCase):
    def test_equivalent_line_numbering_is_allowed_but_body_numbers_are_not(self):
        raw = (
            "一、开始部分\n1. 导入\n师：拿3张卡纸。\n"
            "二、基本部分\n（1）探索\n师：比较两片叶子。\n"
            "三、放松活动\n师：分享发现。"
        )
        validate_split_cleanup(
            raw,
            [
                "1. 开始部分\n1. 导入\n师：拿3张卡纸。\n"
                "2. 基本部分\n(1) 探索\n师：比较两片叶子。\n"
                "3. 放松活动\n师：分享发现。"
            ],
        )
        with self.assertRaises(DailyProcessContractError):
            validate_split_cleanup(
                raw,
                ["1. 开始部分\n1. 导入\n师：拿4张卡纸。\n2. 基本部分\n(1) 探索\n师：比较两片叶子。"],
            )
        with self.assertRaises(DailyProcessContractError):
            validate_split_cleanup(
                raw,
                ["1. 开始部分\n1. 导入\n师：拿三张卡纸。\n2. 基本部分\n(1) 探索\n师：比较两片叶子。"],
            )

    def test_step_deletion_reorder_and_unit_change_are_rejected(self):
        raw = "1. 导入\n师：拿50cm绳子。\n2. 探索\n师：比较两片叶子。\n3. 回顾\n师：分享发现。"
        with self.assertRaises(DailyProcessContractError):
            validate_split_cleanup(raw, ["1. 导入\n师：拿50cm绳子。\n3. 回顾\n师：分享发现。"])
        with self.assertRaises(DailyProcessContractError):
            validate_split_cleanup(raw, ["1. 探索\n师：比较两片叶子。\n2. 导入\n师：拿50cm绳子。\n3. 回顾\n师：分享发现。"])
        with self.assertRaises(DailyProcessContractError):
            validate_split_cleanup(raw, ["1. 导入\n师：拿50米绳子。\n2. 探索\n师：比较两片叶子。\n3. 回顾\n师：分享发现。"])

    def test_number_that_appears_elsewhere_in_raw_is_still_a_change(self):
        raw = (
            "热身：第7次练习。\n"
            "1. 导入\n师：第10次练习。\n2. 探索\n师：比较两片叶子。\n3. 回顾\n师：分享发现。"
        )
        with self.assertRaises(DailyProcessContractError):
            validate_split_cleanup(
                raw,
                ["1. 导入\n师：第7次练习。\n2. 探索\n师：比较两片叶子。\n3. 回顾\n师：分享发现。"],
            )

    def test_activity_theme_is_limited_to_256_utf8_bytes(self):
        from app.local.prompt_bundles import CandidateInvalid, validate_candidate

        base = {
            "group_activity": {
                "theme": "汉" * 86,
                "objectives": "",
                "preparation": "",
                "key_points": "",
                "difficult_points": "",
                "process": "",
            }
        }
        with self.assertRaises(CandidateInvalid):
            validate_candidate("daily_lesson_split", base)
        base["group_activity"]["theme"] = "汉" * 85
        self.assertEqual(
            validate_candidate("daily_lesson_split", base)["group_activity"]["theme"],
            "汉" * 85,
        )

    def test_obvious_typo_punctuation_and_stray_letter_pass(self):
        fields = [
            "导入",
            "说说颜色",
            "探索",
            "比较两片叶子",
            "回顾",
            "分享发现",
        ]
        validate_split_cleanup(
            "1. 导入\n师：说说颜色。\n2. 探锁\n师：比较两片叶子。abc\n3. 回顾\n师：分享发现。",
            fields,
        )

    def test_semantic_rewrite_is_rejected(self):
        with self.assertRaises(DailyProcessContractError):
            validate_split_cleanup(
                "1. 导入\n师：说说颜色。\n2. 探索\n师：比较两片叶子。",
                ["导入", "请幼儿观察并讨论秋天的树叶颜色和形状", "探索", "完全不同的新活动"],
            )

    def test_field_order_and_unrelated_material_pass(self):
        extra = "设计意图：通过树叶比较感知秋天颜色变化，鼓励同伴分享观察结果。" * 8
        raw = (
            extra
            + "\n活动过程：1. 导入\n师：看看树叶。\n2. 探索\n师：说说颜色。\n"
            + "活动目标：认识树叶颜色。\n活动主题：秋天的树叶\n活动准备：落叶、卡纸。"
        )
        validate_split_cleanup(
            raw,
            [
                "秋天的树叶",
                "认识树叶颜色。",
                "落叶、卡纸。",
                "",
                "",
                "1. 导入\n师：看看树叶。\n2. 探索\n师：说说颜色。",
            ],
        )

    def test_legitimate_letters_kept_and_new_ones_rejected(self):
        raw = "活动主题：认识 ABC 卡\n活动准备：3 张卡纸。"
        validate_split_cleanup(raw, ["认识 ABC 卡", "3 张卡纸。"])
        with self.assertRaises(DailyProcessContractError):
            validate_split_cleanup(raw, ["认识 XYZ 卡"])


class AdaptOneStepTests(unittest.TestCase):
    def test_chinese_line_numbering_one_step_change_passes(self):
        baseline = "一、导入\n师：说说颜色。\n二、探索\n师：比较两片叶子。"
        validate_adapt_change(
            baseline,
            baseline,
            "1. 导入\n师：说说颜色。\n2. 探索\n师：请找相同形状的叶子。",
        )

    def test_one_modified_step_passes(self):
        final = changed(1, "2. 探索\n师：请找两片相同形状的叶子。")
        validate_adapt_change(BASE, SAVED, final)

    def test_one_added_step_passes(self):
        final = (
            "1. 导入\n师：说说颜色。\n2. 新增安全提示\n师：先摸一摸再拿。\n"
            "3. 探索\n师：比较两片叶子。\n4. 回顾\n师：分享发现。"
        )
        validate_adapt_change(BASE, SAVED, final)

    def test_two_modified_steps_are_rejected(self):
        final = (
            "1. 导入\n师：指一指红色。\n2. 探索\n师：拿着同色叶子。\n"
            "3. 回顾\n师：分享发现。"
        )
        with self.assertRaises(DailyProcessContractError):
            validate_adapt_change(BASE, SAVED, final)

    def test_pure_renumber_is_not_a_change(self):
        renumbered = "2. 导入\n师：说说颜色。\n3. 探索\n师：比较两片叶子。\n4. 回顾\n师：分享发现。"
        validate_adapt_change(BASE, SAVED, renumbered)

    def test_removal_or_reorder_is_rejected(self):
        with self.assertRaises(DailyProcessContractError):
            validate_adapt_change(BASE, SAVED, "1. 导入\n师：说说颜色。")
        with self.assertRaises(DailyProcessContractError):
            validate_adapt_change(
                BASE,
                SAVED,
                "1. 探索\n师：比较两片叶子。\n2. 导入\n师：说说颜色。\n3. 回顾\n师：分享发现。",
            )

    def test_unidentifiable_structure_fails(self):
        with self.assertRaises(DailyProcessContractError):
            validate_adapt_change(BASE, "只有一个环节", "只改一个环节")

class ProductionGateTests(unittest.TestCase):
    def test_gate_rejects_two_changes_and_accepts_one(self):
        from app.local.ai_task_service import validate_daily_candidate_contract
        from app.local.prompt_bundles import CandidateInvalid

        payload = {
            "process_source": SAVED,
            "split_baseline_process": BASE,
        }
        with self.assertRaises(CandidateInvalid):
            validate_daily_candidate_contract(
                "daily_process_adapt", {"process": TWO}, payload, {}
            )

        validate_daily_candidate_contract(
            "daily_process_adapt",
            {"process": changed(1, "2. 探索\n师：请找相同形状的叶子。")},
            payload,
            {},
        )


class AdaptPatchTests(unittest.TestCase):
    SAVED = "1. 导入\n师：说说颜色。\n2. 探索\n师：比较两片叶子。\n3. 回顾\n师：分享发现。"

    def test_replace_keeps_other_steps_and_returns_full_process(self):
        result = expand_adapt_patch(
            {"operation": "replace", "step_index": 2, "text": "探索\n师：请找相同形状的叶子。"},
            self.SAVED,
            self.SAVED,
        )
        self.assertEqual(
            result["process"],
            "1. 导入\n师：说说颜色。\n2. 探索\n师：请找相同形状的叶子。\n3. 回顾\n师：分享发现。",
        )

    def test_insert_after_step_and_no_change(self):
        inserted = expand_adapt_patch(
            {"operation": "insert", "after_step_index": 1, "text": "安全提示\n师：先摸一摸再拿。"},
            self.SAVED,
            self.SAVED,
        )
        self.assertEqual(
            inserted["process"],
            "1. 导入\n师：说说颜色。\n2. 安全提示\n师：先摸一摸再拿。\n3. 探索\n师：比较两片叶子。\n4. 回顾\n师：分享发现。",
        )
        self.assertEqual(
            expand_adapt_patch({"operation": "no_change"}, self.SAVED, self.SAVED),
            {"process": self.SAVED},
        )

    def test_invalid_patch_variants_are_rejected(self):
        for patch in (
            {"operation": "replace", "step_index": 0, "text": "x"},
            {"operation": "replace", "step_index": 9, "text": "x"},
            {"operation": "replace", "step_index": 2},
            {"operation": "replace", "step_index": 2, "text": "  "},
            {"operation": "replace", "step_index": 2, "text": "x", "extra": 1},
            {"operation": "insert", "after_step_index": 9, "text": "x"},
            {"operation": "insert", "after_step_index": 1},
            {"operation": "no_change", "text": "x"},
            {"operation": "unknown"},
        ):
            with self.subTest(patch=patch):
                with self.assertRaises(DailyProcessContractError):
                    expand_adapt_patch(patch, self.SAVED, self.SAVED)

    def test_patch_cannot_smuggle_multiple_steps(self):
        with self.assertRaises(DailyProcessContractError):
            expand_adapt_patch(
                {
                    "operation": "replace",
                    "step_index": 2,
                    "text": "探索\n师：新内容。\n3. 另一个环节\n师：又一段。",
                },
                self.SAVED,
                self.SAVED,
            )

    def test_old_full_process_protocol_still_passes_through(self):
        old = {"process": self.SAVED}
        self.assertEqual(expand_adapt_patch(old, self.SAVED, self.SAVED), old)

    MIXED = (
        "一、导入\r\n\r\n二、探索\r\n（1）铺纸板\r\n（2）摆纸杯\r\n\r\n三、结束\r\n"
    )

    def test_replace_preserves_mixed_hierarchy_crlf_and_blanks(self):
        result = expand_adapt_patch(
            {
                "operation": "replace",
                "step_index": 3,
                "text": "铺纸板\r\n师：请把纸板铺平。",
            },
            self.MIXED,
            self.MIXED,
        )
        expected = (
            "一、导入\r\n\r\n二、探索\r\n（1）铺纸板\r\n师：请把纸板铺平。\r\n"
            "（2）摆纸杯\r\n\r\n三、结束\r\n"
        )
        self.assertEqual(result["process"], expected)
        self.assertNotIn("\n", result["process"].replace("\r\n", ""))

    def test_insert_after_parent_preserves_children_and_shifts_only_siblings(self):
        result = expand_adapt_patch(
            {
                "operation": "insert",
                "after_step_index": 2,
                "text": "三、新环节\r\n师：一起试一试。",
            },
            self.MIXED,
            self.MIXED,
        )
        expected = (
            "一、导入\r\n\r\n二、探索\r\n（1）铺纸板\r\n（2）摆纸杯\r\n"
            "三、新环节\r\n师：一起试一试。\r\n\r\n四、结束\r\n"
        )
        self.assertEqual(result["process"], expected)
        self.assertNotIn("\n", result["process"].replace("\r\n", ""))

    def test_insert_after_child_shifts_only_same_level_siblings(self):
        result = expand_adapt_patch(
            {
                "operation": "insert",
                "after_step_index": 3,
                "text": "（2）新子项\r\n师：先摆一个。",
            },
            self.MIXED,
            self.MIXED,
        )
        expected = (
            "一、导入\r\n\r\n二、探索\r\n（1）铺纸板\r\n（2）新子项\r\n"
            "师：先摆一个。\r\n（3）摆纸杯\r\n\r\n三、结束\r\n"
        )
        self.assertEqual(result["process"], expected)
        self.assertNotIn("\n", result["process"].replace("\r\n", ""))

    def test_mixed_hierarchy_patch_cannot_inject_extra_steps(self):
        with self.assertRaises(DailyProcessContractError):
            expand_adapt_patch(
                {
                    "operation": "replace",
                    "step_index": 3,
                    "text": "铺纸板\r\n（2）注入的子项\r\n师：不应出现。",
                },
                self.MIXED,
                self.MIXED,
            )


class AdaptWireTests(unittest.TestCase):
    MIXED = (
        "一、导入\r\n\r\n二、探索\r\n（1）铺纸板\r\n（2）摆纸杯\r\n\r\n三、结束\r\n"
    )

    def test_step_index_matches_expander_and_marks_parents(self):
        from app.daily_process_contract import adapt_step_index

        steps = adapt_step_index(self.MIXED)
        self.assertEqual([item["index"] for item in steps], [1, 2, 3, 4, 5])
        self.assertEqual([item["level"] for item in steps], [1, 1, 2, 2, 1])
        self.assertTrue(steps[1]["has_children"])
        self.assertFalse(steps[2]["has_children"])
        self.assertEqual(steps[2]["title"], "铺纸板")

    def test_wire_payload_index_is_counted_in_real_serialized_size(self):
        import json

        from app.local import ai_task_service, ai_transport

        payload = {
            "process_source": self.MIXED,
            "grade": "middle",
            "split_baseline_process": self.MIXED,
        }
        enriched = ai_task_service.adapt_wire_payload(payload)
        self.assertIn("adapt_steps", enriched)
        self.assertNotIn("adapt_steps", payload)
        size = ai_task_service.serialized_request_bytes(
            task_type="daily_process_adapt",
            contract_version=1,
            output_schema={},
            guidance={},
            payload=payload,
            model="m",
        )
        body = ai_transport.build_request(
            model="m",
            system_text=ai_task_service._render_system_text(
                "daily_process_adapt", 1, {}, {}
            ),
            user_text=json.dumps(
                enriched, ensure_ascii=False, separators=(",", ":")
            ),
        )
        self.assertEqual(size, len(body))

    def test_adapt_system_text_has_no_full_process_conflict(self):
        import json

        from app.local import ai_task_service

        payload = json.loads(
            ai_task_service._render_system_text(
                "daily_process_adapt",
                1,
                {},
                {},
            )
        )
        contract = payload["output_contract"]
        self.assertEqual(
            contract["properties"]["operation"]["enum"],
            ["replace", "insert", "no_change"],
        )
        instructions = "\n".join(payload["instructions"])
        self.assertNotIn("输出完整过程，按", instructions)
        self.assertNotIn("按实际步骤真实换行并编号", instructions)
        self.assertIn("adapt_steps", instructions)
        self.assertIn("只写一个实际步骤", instructions)
        self.assertIn("个人指导只决定当前这一个环节", instructions)


class NewlineAndSingleStepTests(unittest.TestCase):
    def test_single_numbered_step_can_change(self):
        validate_adapt_change(
            "1. 探索\n师：看看叶子的颜色。",
            "1. 探索\n师：看看叶子的颜色。",
            "1. 探索\n师：指一指绿色叶子。",
        )

    def test_internal_line_break_change_is_a_change(self):
        with self.assertRaises(DailyProcessContractError):
            validate_adapt_change(
                BASE,
                SAVED,
                "1. 热身\n师：站起来做示范。\n2. 探索 师：看一看。\n3. 回顾\n师：说一说。",
            )

    def test_crlf_and_lf_are_the_same(self):
        validate_adapt_change(BASE, SAVED, BASE.replace("\n", "\r\n"))


class WordWholeStepRedlineTests(unittest.TestCase):
    def test_modified_and_added_steps_are_red_as_whole_steps(self):
        final = (
            "1. 导入\n师：说说颜色。\n2. 探索\n师：请找相同形状的叶子。\n"
            "3. 新增安全提示\n师：先摸一摸。\n4. 回顾\n师：分享发现。"
        )
        result = diff_process(BASE, final, step_aware=True)
        red = "".join(run["text"] for run in result["runs"] if run["red"])
        plain = "".join(run["text"] for run in result["runs"] if not run["red"])
        self.assertIn("2. 探索\n师：请找相同形状的叶子。", red)
        self.assertIn("3. 新增安全提示\n师：先摸一摸。", red)
        self.assertNotIn("导入", red)
        self.assertIn("1. 导入\n师：说说颜色。", plain)
        self.assertIn("4. 回顾\n师：分享发现。", plain)

    def test_word_runs_are_exact_text_with_real_newlines(self):
        final = "1. 热身\n师：站起来做示范。\n2. 探索\n师：看一看。\n3. 回顾\n师：说一说。"
        result = diff_process(BASE, final, step_aware=True)
        flat = "".join(run["text"] for run in result["runs"])
        self.assertEqual(flat, final)
        self.assertNotIn("\\n", flat)

    def test_pure_renumber_has_no_red(self):
        renumbered = "2. 导入\n师：说说颜色。\n3. 探索\n师：比较两片叶子。\n4. 回顾\n师：分享发现。"
        result = diff_process(BASE, renumbered, step_aware=True)
        self.assertFalse(any(run["red"] for run in result["runs"]))

    def test_unnumbered_legacy_path_is_unchanged(self):
        result = diff_process("慢慢倒入水。", "快速倒入水。")
        red = "".join(run["text"] for run in result["runs"] if run["red"])
        self.assertEqual(red, "快速")


class DefaultWebAndBoundsTests(unittest.TestCase):
    def test_default_web_diff_keeps_old_character_behavior(self):
        final = "1. 导入\n师：指一指绿叶。\n2. 探索\n师：说说颜色。"
        result = diff_process(BASE, final)
        red = "".join(run["text"] for run in result["runs"] if run["red"])
        self.assertIn("指一指绿", red)
        self.assertNotEqual(red, "1. 导入\n师：指一指绿叶。")

    def test_step_aware_single_step_reds_the_whole_step(self):
        base = "1. 探索\n师：看看叶子的颜色。"
        final = "1. 探索\n师：指一指绿色叶子。"
        result = diff_process(base, final, step_aware=True)
        red = "".join(run["text"] for run in result["runs"] if run["red"])
        self.assertEqual(red, "1. 探索\n师：指一指绿色叶子。")

    def test_long_field_check_is_bounded(self):
        import time

        intro = "教学背景环境课程目标支架主题材料准备叙事帮助幼儿讨论交往" * 45
        field = "观察过程教师提问幼儿仔细比较秋天叶子" * 90
        teacher = field[:400] + "数" + field[401:]
        started = time.perf_counter()
        validate_split_cleanup(intro + "活动过程：" + field, [teacher])
        self.assertLess(time.perf_counter() - started, 2.0)

    def test_new_adapt_without_baseline_is_blocked_before_send(self):
        from app.local.ai_task_service import require_adapt_baseline
        from app.local.errors import LocalValidationError

        with self.assertRaises(LocalValidationError):
            require_adapt_baseline({"process_source": SAVED})


class ModelRuleTests(unittest.TestCase):
    def test_task_rules_contain_23_constraints(self):
        import json
        from app.local.ai_task_service import _render_system_text

        split = json.loads(_render_system_text("daily_lesson_split", 1, {}, {}))
        adapt = json.loads(_render_system_text("daily_process_adapt", 1, {}, {}))
        self.assertTrue(
            any("只清理常见的明显错字" in rule for rule in split["instructions"])
        )
        self.assertTrue(
            any("只允许修改一个已有环节" in rule for rule in adapt["instructions"])
        )
        self.assertTrue(
            any("仅编号顺延不算修改" in rule for rule in adapt["instructions"])
        )


if __name__ == "__main__":
    unittest.main()
