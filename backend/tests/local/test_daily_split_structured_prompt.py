"""Daily split provider contract (2026-11-14 report).

Synthetic only.  The request carries one JSON-mode flag, and the system message
explicitly puts the final JSON in assistant content rather than reasoning.
Strict parsing and no automatic retry remain the transport/task behavior tested
elsewhere.
"""

from __future__ import annotations

import json
import unittest

from app.local import ai_task_service, ai_transport, prompt_bundles


class DailySplitStructuredPromptTests(unittest.TestCase):
    def test_split_system_message_separates_reasoning_from_final_content(self):
        system = json.loads(
            ai_task_service._render_system_text(
                "daily_lesson_split",
                1,
                prompt_bundles._SPLIT_OUTPUT_SCHEMA,
                prompt_bundles._SPLIT_GUIDANCE_R2,
            )
        )
        text = "\n".join(system["instructions"])
        self.assertIn("只返回一个 JSON 对象", text)
        self.assertIn("content", text)
        self.assertIn("reasoning_content", text)
        self.assertIn("Final answer", text)
        self.assertIn("只收到推理内容不算完成", text)
        self.assertIn("rule_precedence", system)
        self.assertIn("优先于 guidance", system["rule_precedence"])
        self.assertEqual(system["task_type"], "daily_lesson_split")
        self.assertEqual(system["output_contract"], prompt_bundles._SPLIT_OUTPUT_SCHEMA)

    def test_split_request_uses_one_json_mode_flag(self):
        body = ai_transport.build_request(
            model="synthetic-model",
            system_text="synthetic-system",
            user_text='{"raw_lesson_plan":"合成原文","grade":"middle"}',
            json_mode=ai_transport.text_json_mode("daily_lesson_split"),
        )
        payload = json.loads(body)
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertEqual(payload["messages"][1]["role"], "user")
        self.assertIs(payload["stream"], True)
        self.assertNotIn("max_tokens", payload)

    def test_json_mode_stays_out_of_listening_and_weekly_requests(self):
        self.assertTrue(ai_transport.text_json_mode("daily_lesson_split"))
        self.assertTrue(ai_transport.text_json_mode("daily_other_activities"))
        self.assertTrue(ai_transport.text_json_mode("curriculum_split"))
        self.assertFalse(ai_transport.text_json_mode("weekly_games_select"))
        self.assertFalse(ai_transport.text_json_mode("listening_note_draft"))
        self.assertFalse(
            ai_transport.text_json_mode(
                "daily_lesson_split", source_kind="weekly_plan"
            )
        )


if __name__ == "__main__":
    unittest.main()
