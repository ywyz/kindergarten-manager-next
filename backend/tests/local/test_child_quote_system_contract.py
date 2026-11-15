"""2026-11-15 child-quote system contract (synthetic, no provider/network).

The fixed task instructions must allow a small, clearly unverified amount of
AI-drafted child speech for listening notes and observation records, while
keeping teacher-authored quotes, evidence boundaries and evaluation/stars
authority intact.  These tests render the real system JSON only.
"""

from __future__ import annotations

import json
import unittest

from app.local import ai_task_service
from app.local import directional_revision_contracts
from app.local import listening_ai_contracts


def _bundle(task_type: str, module) -> dict:
    for item in module.bundle_definitions():
        if item["task_type"] == task_type:
            return item
    raise AssertionError(f"missing bundle {task_type}")


def _rendered(task_type: str, schema: dict, guidance: dict) -> dict:
    return json.loads(
        ai_task_service._render_system_text(
            task_type,
            1,
            schema,
            guidance,
        )
    )


def _instructions(payload: dict) -> str:
    return "\n".join(payload["instructions"])


class ListeningChildQuoteTests(unittest.TestCase):
    def test_note_old_r1_guidance_is_kept_but_hard_rule_allows_drafted_quotes(self):
        bundle = _bundle(
            listening_ai_contracts.TASK_NOTE,
            listening_ai_contracts,
        )
        old_guidance = dict(bundle["guidance_defaults_json"])
        self.assertIn("不得虚构幼儿引语", old_guidance["text"])
        payload = _rendered(
            listening_ai_contracts.TASK_NOTE,
            bundle["output_schema_json"],
            old_guidance,
        )
        self.assertEqual(payload["guidance"]["text"], old_guidance["text"])
        instructions = _instructions(payload)
        self.assertIn("本轮固定协议", instructions)
        self.assertIn("拟写少量幼儿话语", instructions)
        self.assertIn("已有的幼儿原话", instructions)
        self.assertIn("顺序和语气必须原样保留", instructions)
        self.assertIn("不得声称从照片或录音听到了真实原话", instructions)
        self.assertIn("不作为已核实评价、星级或支持策略的事实依据", instructions)
        self.assertIn("以本固定协议为准", instructions)
        self.assertIn("instructions 中的硬约束优先于 guidance", payload["rule_precedence"])

    def test_group_notes_r1_guidance_keeps_positions_and_allows_drafted_quotes(self):
        bundle = _bundle(
            listening_ai_contracts.TASK_GROUP,
            listening_ai_contracts,
        )
        old_guidance = dict(bundle["guidance_defaults_json"])
        self.assertIn("不得推断幼儿原话", old_guidance["groups"])
        payload = _rendered(
            listening_ai_contracts.TASK_GROUP,
            bundle["output_schema_json"],
            old_guidance,
        )
        self.assertEqual(payload["guidance"]["groups"], old_guidance["groups"])
        instructions = _instructions(payload)
        self.assertIn("实际 position 逐图位返回", instructions)
        self.assertIn("允许依据教师已保存的倾听记录", instructions)
        self.assertIn("拟写少量幼儿话语", instructions)
        self.assertIn("不得声称从照片或录音听到了真实原话", instructions)
        self.assertIn("不作为已核实评价、星级或支持策略的事实依据", instructions)
        self.assertIn("空槽不生成内容", instructions)


class ObservationChildQuoteTests(unittest.TestCase):
    def _assert_observation_rules(self, task_type: str) -> None:
        payload = _rendered(task_type, {}, {})
        instructions = _instructions(payload)
        self.assertIn("观察记录栏允许这类少量AI拟写", instructions)
        self.assertIn("匿名/共同情境幼儿话语", instructions)
        self.assertIn("教师明确给出的原话、人物对应、时间和顺序优先保留", instructions)
        self.assertIn("不得改写、替换或调换", instructions)
        self.assertIn("不声称从静态照片听到原话", instructions)
        self.assertIn("不声称从录音听到了真实原话", instructions)
        self.assertIn("不作为已核实的评价依据，也不作为星级依据", instructions)
        self.assertNotIn("不自行给幼儿分配角色、台词或动作", instructions)
        self.assertIn("不自行把新的角色、台词或动作归到具体姓名", instructions)

    def test_generate_allows_anonymous_drafted_speech_with_evidence_boundary(self):
        self._assert_observation_rules("game_observation_generate")

    def test_rewrite_uses_the_same_child_quote_boundary(self):
        self._assert_observation_rules("game_observation_rewrite")


class DirectionalChildQuoteTests(unittest.TestCase):
    def test_listening_text_condition_is_explicit_and_weekly_and_evaluations_stay_closed(self):
        bundle = _bundle(
            directional_revision_contracts.TASK_TYPE,
            directional_revision_contracts,
        )
        payload = _rendered(
            directional_revision_contracts.TASK_TYPE,
            bundle["output_schema_json"],
            dict(bundle["guidance_defaults_json"]),
        )
        instructions = _instructions(payload)
        self.assertIn("source='listening'", instructions)
        self.assertIn("target='listening_text'", instructions)
        self.assertIn("拟写少量幼儿话语", instructions)
        self.assertIn("不得声称从照片或录音听到真实原话", instructions)
        self.assertIn("source='weekly'", instructions)
        for target in ("weekly_column", "weekly_game", "weekly_material", "goal", "overall_evaluation", "support_strategy"):
            self.assertIn(target, instructions)
        self.assertIn("不得新增或推断幼儿原话", instructions)
        self.assertIn("不改变星级", instructions)
        self.assertIn("没有授权证据的整段现场经历、动作时长、心理结论或因果关系不得编造成事实", instructions)

    def test_other_tasks_do_not_gain_the_fixed_quote_rule(self):
        for task_type in (
            "listening_domain_evaluate",
            "listening_goal_suggest",
            "weekly_games_select",
            "weekly_key_week_focus",
        ):
            payload = _rendered(task_type, {}, {})
            self.assertNotIn("本轮固定协议", _instructions(payload), task_type)
            self.assertNotIn("观察记录栏允许这类少量AI拟写", _instructions(payload), task_type)


if __name__ == "__main__":
    unittest.main()
