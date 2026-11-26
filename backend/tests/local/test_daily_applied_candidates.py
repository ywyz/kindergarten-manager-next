"""Applied-candidate adoptability and one-day reflection gate regression.

2026-11-26: a targeted-modification (or direct-fill) candidate whose saved
target now equals the candidate's own output must stay adoptable — the
adoption then recognises identical content and commits no new version. A
concurrently edited target or a real source change stays view-only. The
one-day reflection may only be generated when every activity board of the day
has content; the backend refuses incomplete days.

Real temp SQLite through ``LocalRuntime``; candidates are produced through
the normal W3 chain. No network, no provider call, synthetic data only.
"""

from __future__ import annotations

import json
import uuid
from datetime import date

from app.local import (
    ai_adoption,
    ai_candidates,
    ai_config_service,
    ai_task_service,
    daily_plan_service,
    profile_service,
)
from app.local.base import utc_now
from app.local.errors import (
    LocalAiSourceChanged,
    LocalValidationError,
)
from app.local.normalize import normalize_initialization
from tests.local.support import (
    LocalTestCase,
    initialize_body,
    query_scalar,
)

PROCESS = "1. 导入\n2. 观察"

TALK_BEFORE = {"topic": "旧话题", "questions": "旧问题"}
TALK_CANDIDATE = {"topic": "新话题", "questions": "新问题"}
TALK_EDITED = {"topic": "教师话题", "questions": "教师问题"}

FULL_BOARDS = {
    "morning_games": [
        {
            "group_kind": "collective",
            "games": [{"name": "圈圈乐"}],
            "focus_guidance": "圈圈乐",
            "shared_objectives": "集体目标",
            "guidance_points": "集体指导",
        }
    ],
    "morning_talk": {"topic": "晨谈话题", "questions": "晨谈问题"},
    "group_activity": {
        "theme": "主题",
        "objectives": "目标",
        "preparation": "准备",
        "key_points": "重点",
        "difficult_points": "难点",
        "process": PROCESS,
    },
    "post_group_games": [
        {
            "context_kind": "area",
            "area": "美工区、建构区",
            "games": [{"name": "搭桥"}],
            "focus_guidance": "美工区",
            "objectives": "目标",
            "guidance": "指导",
            "support_strategy": "支持",
        }
    ],
    "afternoon_outdoor": {
        "area": "骑行、沙水池",
        "games": [{"name": "骑行"}],
        "observation_focus": "骑行",
        "objectives": "目标",
        "guidance": "指导",
        "support_strategy": "支持",
    },
}

RAW = (
    "活动主题：主题\n活动目标：目标\n活动准备：准备\n活动重点：重点\n"
    "活动难点：难点\n活动过程：1. 导入\n2. 观察"
)


class AppliedCase(LocalTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.runtime = self.make_runtime()
        self.runtime.launch_id = str(uuid.uuid4())
        self.db = self.runtime.db_path
        self.session = self.runtime.session()
        self.addCleanup(self.session.close)
        profile_service.initialize(
            self.session, normalize_initialization(**initialize_body())
        )
        self.session.commit()
        ai_adoption.reset_tokens()
        version = query_scalar(self.db, "SELECT current_config_version FROM local_ai_state")
        ai_config_service.patch_config(
            self.session,
            expected_ai_config_version=version or 0,
            base_url="https://api.example.com/v1",
            model="test-model",
            secret="s3cret",
            secret_provided=True,
            request_id=str(uuid.uuid4()),
            credential_root=self.runtime.credential_root,
        )

    def content_version(self, plan_id: str) -> int:
        return int(
            query_scalar(
                self.db,
                "SELECT current_content_version FROM local_daily_plans WHERE id = ?",
                (plan_id,),
            )
        )

    def make_plan(self, adopted) -> dict:
        payload, _created = daily_plan_service.create_or_open(
            self.session,
            plan_date=date(2026, 9, 2),
            raw_lesson_plan=RAW,
            adopted_content=adopted,
        )
        return payload

    def generate(
        self,
        plan_id: str,
        candidate: dict,
        *,
        task_type: str = "daily_other_activities",
        target_section: str | None = None,
        revision_instruction: str | None = None,
        implementation_materials: str | None = None,
    ) -> str:
        result, _created = ai_task_service.create_task(
            self.session,
            plan_id=plan_id,
            task_type=task_type,
            expected_content_version=self.content_version(plan_id),
            target_grade="middle",
            request_id=str(uuid.uuid4()),
            target_section=target_section,
            revision_instruction=revision_instruction,
            implementation_materials=implementation_materials,
        )
        claim = ai_task_service.claim_next(
            self.runtime, now=utc_now(), started_ticks=1
        )
        self.assertIsNotNone(claim, result)
        self.assertTrue(
            ai_task_service.commit_dispatch_mark(self.session, claim, utc_now())
        )
        self.assertTrue(
            ai_task_service.finalize_success(
                self.session,
                claim,
                {
                    "kind": "success",
                    "candidate_text": json.dumps(candidate, ensure_ascii=False),
                },
                utc_now(),
            )
        )
        candidate_id = query_scalar(
            self.db,
            "SELECT id FROM local_ai_candidates WHERE execution_id = ?",
            (claim.execution_id,),
        )
        self.assertIsNotNone(candidate_id)
        return candidate_id

    def preview(self, plan_id, candidate_id, selected, edited):
        self.session.expire_all()
        return ai_adoption.preview_adoption(
            self.session,
            plan_id=plan_id,
            candidate_id=candidate_id,
            expected_content_version=self.content_version(plan_id),
            selected_targets=selected,
            edited_candidate=edited,
        )

    def adopt(self, plan_id, candidate_id, token):
        self.session.expire_all()
        return ai_adoption.adopt(
            self.session,
            plan_id=plan_id,
            candidate_id=candidate_id,
            expected_content_version=self.content_version(plan_id),
            preview_token=token,
            request_id=str(uuid.uuid4()),
        )

    def plan_content(self, plan_id: str) -> dict:
        payload = daily_plan_service.get_plan(self.session, plan_id=plan_id)
        return payload["content"]


class TargetedSectionAppliedTests(AppliedCase):
    """定向修改候选：候选内容已保存且教师无编辑时仍可采用（no-op）。"""

    def setUp(self):
        super().setUp()
        self.group = {
            "theme": "主题",
            "objectives": "目标",
            "preparation": "准备",
            "key_points": "重点",
            "difficult_points": "难点",
            "process": PROCESS,
        }
        self.plan = self.make_plan(
            {"group_activity": dict(self.group), "morning_talk": dict(TALK_BEFORE)}
        )
        self.plan_id = self.plan["id"]
        self.candidate_id = self.generate(
            self.plan_id,
            {"morning_talk": dict(TALK_CANDIDATE)},
            target_section="morning_talk",
            revision_instruction="更贴近本周主题",
        )

    def test_applied_candidate_stays_adoptable_as_noop(self):
        # The direct-fill flow saved the candidate's own talk as a new version.
        daily_plan_service.save(
            self.session,
            plan_id=self.plan_id,
            expected_content_version=self.content_version(self.plan_id),
            adopted_content={
                "group_activity": dict(self.group),
                "morning_talk": dict(TALK_CANDIDATE),
            },
        )
        detail = ai_candidates.get_candidate(
            self.session, plan_id=self.plan_id, candidate_id=self.candidate_id
        )
        self.assertEqual(detail["adoption_state"], "eligible")
        preview = self.preview(
            self.plan_id, self.candidate_id, ["morning_talk"], {"morning_talk": dict(TALK_CANDIDATE)}
        )
        self.assertEqual(preview["before"], preview["after"])
        result = self.adopt(self.plan_id, self.candidate_id, preview["preview_token"])
        self.assertFalse(result["changed"])
        self.assertEqual(
            self.plan_content(self.plan_id)["adopted_content"]["morning_talk"],
            dict(TALK_CANDIDATE),
        )

    def test_concurrent_target_edit_stays_view_only(self):
        daily_plan_service.save(
            self.session,
            plan_id=self.plan_id,
            expected_content_version=self.content_version(self.plan_id),
            adopted_content={
                "group_activity": dict(self.group),
                "morning_talk": dict(TALK_EDITED),
            },
        )
        detail = ai_candidates.get_candidate(
            self.session, plan_id=self.plan_id, candidate_id=self.candidate_id
        )
        self.assertEqual(detail["adoption_state"], "source_changed")
        with self.assertRaises(LocalAiSourceChanged):
            self.preview(
                self.plan_id, self.candidate_id, ["morning_talk"], {"morning_talk": dict(TALK_CANDIDATE)}
            )

    def test_real_source_change_stays_view_only(self):
        # The collective activity is a genuine generation input: changing it
        # must never be relabelled as "already applied".
        changed_group = dict(self.group)
        changed_group["process"] = "1. 导入\n2. 观察\n3. 新环节"
        daily_plan_service.save(
            self.session,
            plan_id=self.plan_id,
            expected_content_version=self.content_version(self.plan_id),
            adopted_content={
                "group_activity": changed_group,
                "morning_talk": dict(TALK_CANDIDATE),
            },
        )
        detail = ai_candidates.get_candidate(
            self.session, plan_id=self.plan_id, candidate_id=self.candidate_id
        )
        self.assertEqual(detail["adoption_state"], "source_changed")
        with self.assertRaises(LocalAiSourceChanged):
            self.preview(
                self.plan_id, self.candidate_id, ["morning_talk"], {"morning_talk": dict(TALK_CANDIDATE)}
            )


class TargetedReflectionAppliedTests(AppliedCase):
    """定向修改反思：候选反思已保存且教师无编辑时仍可采用（no-op）。"""

    def setUp(self):
        super().setUp()
        boards = dict(FULL_BOARDS)
        boards["reflection"] = "旧反思"
        self.plan = self.make_plan(boards)
        self.plan_id = self.plan["id"]
        self.materials = "幼儿分成四组搭纸杯桥；两组成功，一组反复倒塌后改用宽底座。"
        self.candidate_id = self.generate(
            self.plan_id,
            {"reflection": "新反思"},
            task_type="daily_reflection_generate",
            revision_instruction="突出教师支持",
            implementation_materials=self.materials,
        )

    def save_reflection(self, reflection: str) -> None:
        save_boards = dict(FULL_BOARDS)
        save_boards["reflection"] = reflection
        daily_plan_service.save(
            self.session,
            plan_id=self.plan_id,
            expected_content_version=self.content_version(self.plan_id),
            adopted_content=save_boards,
        )

    def test_applied_reflection_stays_adoptable_as_noop(self):
        self.save_reflection("新反思")
        detail = ai_candidates.get_candidate(
            self.session, plan_id=self.plan_id, candidate_id=self.candidate_id
        )
        self.assertEqual(detail["adoption_state"], "eligible")
        preview = self.preview(
            self.plan_id, self.candidate_id, ["reflection"], {"reflection": "新反思"}
        )
        result = self.adopt(self.plan_id, self.candidate_id, preview["preview_token"])
        self.assertFalse(result["changed"])

    def test_edited_reflection_stays_view_only(self):
        self.save_reflection("教师改过的反思")
        detail = ai_candidates.get_candidate(
            self.session, plan_id=self.plan_id, candidate_id=self.candidate_id
        )
        self.assertEqual(detail["adoption_state"], "source_changed")
        with self.assertRaises(LocalAiSourceChanged):
            self.preview(
                self.plan_id, self.candidate_id, ["reflection"], {"reflection": "新反思"}
            )


class ReflectionGateTests(AppliedCase):
    """生成反思要求当日所有活动均有内容（后端保护）。"""

    def test_incomplete_day_is_rejected_with_board_names(self):
        plan = self.make_plan(
            {
                "group_activity": {
                    "theme": "主题",
                    "objectives": "目标",
                    "preparation": "准备",
                    "key_points": "重点",
                    "difficult_points": "难点",
                    "process": PROCESS,
                },
                "reflection": "反思",
            }
        )
        with self.assertRaises(LocalValidationError) as ctx:
            self.generate(
                plan["id"],
                {"reflection": "反思"},
                task_type="daily_reflection_generate",
                implementation_materials="实施材料",
            )
        message = str(ctx.exception)
        self.assertIn("晨间活动", message)
        self.assertIn("晨间谈话", message)
        self.assertIn("活动后游戏", message)
        self.assertIn("下午户外", message)
        self.assertEqual(
            query_scalar(
                self.db,
                "SELECT count(*) FROM local_ai_tasks WHERE task_type='daily_reflection_generate'",
            ),
            0,
        )

    def test_complete_day_with_materials_creates_the_task(self):
        plan = self.make_plan(dict(FULL_BOARDS))
        candidate_id = self.generate(
            plan["id"],
            {"reflection": "反思"},
            task_type="daily_reflection_generate",
            implementation_materials="实施材料",
        )
        self.assertTrue(candidate_id)

    def test_implementation_materials_are_still_required(self):
        plan = self.make_plan(dict(FULL_BOARDS))
        with self.assertRaises(LocalValidationError):
            self.generate(
                plan["id"],
                {"reflection": "反思"},
                task_type="daily_reflection_generate",
            )


if __name__ == "__main__":
    unittest.main()


class FirstFillAppliedTests(AppliedCase):
    """首填场景：生成前该板块为空，保存候选自身输出后仍可采用（no-op）。"""

    def setUp(self):
        super().setUp()
        self.group = {
            "theme": "主题",
            "objectives": "目标",
            "preparation": "准备",
            "key_points": "重点",
            "difficult_points": "难点",
            "process": PROCESS,
        }

    def _save(self, plan_id, adopted):
        daily_plan_service.save(
            self.session,
            plan_id=plan_id,
            expected_content_version=self.content_version(plan_id),
            adopted_content=adopted,
        )

    def test_first_fill_of_blank_targeted_board_keeps_candidate_adoptable(self):
        plan = self.make_plan({"group_activity": dict(self.group)})
        plan_id = plan["id"]
        candidate_id = self.generate(
            plan_id,
            {"morning_talk": dict(TALK_CANDIDATE)},
            target_section="morning_talk",
            revision_instruction="更贴近本周主题",
        )
        self._save(
            plan_id,
            {
                "group_activity": dict(self.group),
                "morning_talk": dict(TALK_CANDIDATE),
            },
        )
        detail = ai_candidates.get_candidate(
            self.session, plan_id=plan_id, candidate_id=candidate_id
        )
        self.assertEqual(detail["adoption_state"], "eligible")
        preview = self.preview(
            plan_id,
            candidate_id,
            ["morning_talk"],
            {"morning_talk": dict(TALK_CANDIDATE)},
        )
        self.assertEqual(preview["before"], preview["after"])
        result = self.adopt(plan_id, candidate_id, preview["preview_token"])
        self.assertFalse(result["changed"])

    def test_teacher_change_after_first_fill_is_view_only(self):
        plan = self.make_plan({"group_activity": dict(self.group)})
        plan_id = plan["id"]
        candidate_id = self.generate(
            plan_id,
            {"morning_talk": dict(TALK_CANDIDATE)},
            target_section="morning_talk",
            revision_instruction="更贴近本周主题",
        )
        self._save(
            plan_id,
            {
                "group_activity": dict(self.group),
                "morning_talk": dict(TALK_CANDIDATE),
            },
        )
        self._save(
            plan_id,
            {
                "group_activity": dict(self.group),
                "morning_talk": dict(TALK_EDITED),
            },
        )
        detail = ai_candidates.get_candidate(
            self.session, plan_id=plan_id, candidate_id=candidate_id
        )
        self.assertEqual(detail["adoption_state"], "source_changed")
        with self.assertRaises(LocalAiSourceChanged):
            self.preview(
                plan_id,
                candidate_id,
                ["morning_talk"],
                {"morning_talk": dict(TALK_CANDIDATE)},
            )

    def test_full_four_board_first_fill_stays_adoptable(self):
        # A plan without any of the four boards; the full generation (no
        # target_section) provides all four and the direct fill saves them.
        plan = self.make_plan({"group_activity": dict(self.group)})
        plan_id = plan["id"]
        boards = {
            "morning_games": [
                {
                    "group_kind": "collective",
                    "games": [{"name": "圈圈乐"}],
                    "focus_guidance": "圈圈乐",
                    "shared_objectives": "集体目标",
                    "guidance_points": "集体指导",
                },
                {
                    "group_kind": "free_choice",
                    "games": [{"name": "积木搭建"}],
                    "guidance_points": "自选指导",
                },
            ],
            "morning_talk": dict(TALK_CANDIDATE),
            "post_group_games": [
                {
                    "context_kind": "area",
                    "area": "美工区、建构区",
                    "games": [{"name": "搭桥"}],
                    "focus_guidance": "美工区",
                    "objectives": "目标",
                    "guidance": "指导",
                    "support_strategy": "支持",
                }
            ],
            "afternoon_outdoor": {
                "area": "骑行、沙水池",
                "games": [{"name": "骑行"}],
                "observation_focus": "骑行",
                "objectives": "目标",
                "guidance": "指导",
                "support_strategy": "支持",
            },
        }
        candidate_id = self.generate(plan_id, boards)
        # The real direct-fill uses the persisted (normalized) candidate body.
        detail = ai_candidates.get_candidate(
            self.session, plan_id=plan_id, candidate_id=candidate_id
        )
        normalized = dict(detail["raw_candidate"])
        filled = dict(normalized)
        filled["group_activity"] = dict(self.group)
        self._save(plan_id, filled)
        detail = ai_candidates.get_candidate(
            self.session, plan_id=plan_id, candidate_id=candidate_id
        )
        self.assertEqual(detail["adoption_state"], "eligible")
        preview = self.preview(
            plan_id, candidate_id, list(boards.keys()), dict(normalized)
        )
        self.assertEqual(preview["before"], preview["after"])
        result = self.adopt(plan_id, candidate_id, preview["preview_token"])
        self.assertFalse(result["changed"])
