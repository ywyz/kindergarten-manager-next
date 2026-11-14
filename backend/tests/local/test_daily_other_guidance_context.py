"""Daily other-activities post-group guidance context (2026-11-14 report).

Synthetic only: no provider, database or real classroom material.  The report
requires the real saved collective activity to reach the payload and forbids
the generated text from explaining that the activity was "not provided".
"""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from app.local import ai_inputs, ai_task_service, prompt_bundles


class DailyOtherGuidanceContextTests(unittest.TestCase):
    def test_saved_collective_activity_reaches_the_snapshot_without_ids(self):
        content = SimpleNamespace(
            adopted_content={
                "group_activity": {
                    "theme": "合成主题",
                    "objectives": "合成目标",
                    "preparation": "合成准备",
                    "key_points": "合成重点",
                    "difficult_points": "合成难点",
                    "process": "1. 合成步骤一\n2. 合成步骤二",
                },
                "post_group_games": [
                    {
                        "group_id": "server-owned-post-id",
                        "context_kind": "area",
                        "area": "合成区域",
                        "games": [
                            {"game_id": "server-owned-game-id", "name": "合成游戏"}
                        ],
                    }
                ],
            }
        )
        snapshot, boards = ai_inputs._snapshot(content)
        self.assertEqual(snapshot["group_activity"]["theme"], "合成主题")
        self.assertIn("合成步骤二", snapshot["group_activity"]["process"])
        self.assertNotIn("group_id", snapshot["group_activity"])
        self.assertNotIn("game_id", snapshot["post_group_games"][0]["games"][0])
        self.assertEqual(boards["group_activity"]["theme"], "合成主题")

    def test_runtime_prompt_forbids_missing_activity_explanations(self):
        system = json.loads(
            ai_task_service._render_system_text(
                "daily_other_activities",
                1,
                {},
                prompt_bundles._OTHER_GUIDANCE_R3,
            )
        )
        text = "\n".join(system["instructions"])
        self.assertIn("daily_plan_snapshot.group_activity", text)
        self.assertIn("集体活动未提供", text)
        self.assertIn("以下是一般性建议", text)
        self.assertIn("即使集体活动正文为空", text)
        self.assertNotIn(
            "集体活动为空时，按现有信息给出一般性建议，并说明未结合班级游戏配置。",
            text,
        )

    def test_r3_guidance_keeps_the_same_fields_and_tightens_post_games(self):
        r2 = prompt_bundles._OTHER_GUIDANCE_R2
        r3 = prompt_bundles._OTHER_GUIDANCE_R3
        self.assertEqual(sorted(r2.keys()), sorted(r3.keys()))
        self.assertIn("集体活动未提供", r3["post_group_games"])
        self.assertIn("以下是一般性建议", r3["post_group_games"])
        self.assertIn("daily_plan_snapshot.group_activity", r3["post_group_games"])
        for key in ("morning_games", "morning_talk", "afternoon_outdoor"):
            self.assertEqual(r2[key], r3[key])


if __name__ == "__main__":
    unittest.main()
