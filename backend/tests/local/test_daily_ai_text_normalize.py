"""#24 daily AI text newline normalization (pure, no database)."""

from __future__ import annotations

import unittest

from app.daily_process_contract import normalize_ai_text, normalize_daily_candidate


class NormalizeAiTextTests(unittest.TestCase):
    def test_real_multiline_is_unchanged(self):
        value = "1. 导入\n师：看看叶子。\n2. 探索\n师：说说颜色。"
        self.assertEqual(normalize_ai_text(value), value)

    def test_structural_literal_newlines_are_decoded(self):
        value = "1. 导入\\n师：看看叶子。\\n2. 探索\\n师：说说颜色。"
        self.assertEqual(
            normalize_ai_text(value),
            "1. 导入\n师：看看叶子。\n2. 探索\n师：说说颜色。",
        )

    def test_single_teacher_marker_at_start_is_decoded(self):
        self.assertEqual(
            normalize_ai_text("师：看看叶子。\\n幼：绿色。"),
            "师：看看叶子。\n幼：绿色。",
        )

    def test_double_escape_loses_only_one_layer(self):
        value = "1. 导入\\\\n师：看看叶子。\\\\n2. 探索"
        self.assertEqual(normalize_ai_text(value), "1. 导入\n师：看看叶子。\n2. 探索")

    def test_paths_filenames_english_and_ambiguous_text_stay(self):
        for value in (
            "C:\\new\\file.txt",
            "报告\\n1.txt",
            "line1\\nline2",
            "公式 a\\b 不变",
            "文件名：报告\\n1.txt",
        ):
            self.assertEqual(normalize_ai_text(value), value)

    def test_role_speech_paths_markers_and_english_stay(self):
        for value in (
            "师：请打开 D:\\教学\\new.txt。",
            "师：板书要保留 \\name 这个标记。",
            "师：请看 notes\\new.txt。",
        ):
            self.assertEqual(normalize_ai_text(value), value)

    def test_mixed_slash_and_preserved_word_keep_role_context(self):
        self.assertEqual(
            normalize_ai_text("师：比较 A/B 两张图。\\n幼：我喜欢第二张。"),
            "师：比较 A/B 两张图。\n幼：我喜欢第二张。",
        )
        self.assertEqual(
            normalize_ai_text("师：读 \\name 后停顿。\\n请幼儿开始。"),
            "师：读 \\name 后停顿。\n请幼儿开始。",
        )
        self.assertEqual(
            normalize_ai_text("师：请看 D:\\教学\\new.txt。\\n幼：看到了。"),
            "师：请看 D:\\教学\\new.txt。\n幼：看到了。",
        )

    def test_repeated_escapes_are_linear(self):
        import time

        value = "师：请看。" + "\\n师：继续。" * 5000
        started = time.perf_counter()
        actual = normalize_ai_text(value)
        self.assertLess(time.perf_counter() - started, 2.0)
        self.assertEqual(actual.count("\n"), 5000)
        self.assertNotIn("\\n", actual)

    def test_candidate_normalization_touches_only_daily_text_fields(self):
        raw = {
            "group_activity": {
                "theme": "主题",
                "process": "1. 导入\\n师：看看叶子。\\n2. 探索",
            }
        }
        normalized = normalize_daily_candidate("daily_lesson_split", raw)
        self.assertEqual(
            normalized["group_activity"]["process"],
            "1. 导入\n师：看看叶子。\n2. 探索",
        )
        self.assertEqual(normalized["group_activity"]["theme"], "主题")

        other = {
            "morning_talk": {"topic": "话题", "questions": "1. 问一\\n2. 问二"},
            "reflection": "1. 反思\\n2. 不变",
        }
        normalized = normalize_daily_candidate("daily_other_activities", other)
        self.assertEqual(normalized["morning_talk"]["questions"], "1. 问一\n2. 问二")
        self.assertEqual(normalized["reflection"], other["reflection"])

    def test_prompt_rule_requires_single_layer(self):
        import json
        from app.local.ai_task_service import _render_system_text

        for task_type in (
            "daily_lesson_split",
            "daily_process_adapt",
            "daily_other_activities",
        ):
            rules = json.loads(_render_system_text(task_type, 1, {}, {}))["instructions"]
            self.assertTrue(any("只转义一层" in rule for rule in rules))
        observation = json.loads(
            _render_system_text("game_observation_generate", 1, {}, {})
        )
        self.assertFalse(
            any("日计划 AI 文字的换行" in rule for rule in observation["instructions"])
        )


if __name__ == "__main__":
    unittest.main()
