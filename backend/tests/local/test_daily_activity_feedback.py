"""Daily feedback: isolated config, one morning focus/detail set and redline."""
import copy
import io
import json
import uuid
import zipfile
from datetime import date
from unittest import mock

from app.local import ai_candidates, ai_task_service, config_service, export_service
from app.local.base import utc_now
from tests.local.support import query_scalar
from tests.local.test_d2_w4_candidates import OTHER_CANDIDATE, SPLIT_CANDIDATE, W4Case


class DailyActivityFeedbackTests(W4Case):
    def setUp(self):
        super().setUp()
        self.configure_ai()
        self.plan = self.make_plan()

    def detail(self, candidate_id):
        return ai_candidates.get_candidate(
            self.session, plan_id=self.plan["id"], candidate_id=candidate_id,
        )["raw_candidate"]

    def export_text(self):
        from lxml import etree

        bundle = export_service.prepare_export(
            self.session, from_date=date(2026, 9, 2), to_date=date(2026, 9, 2),
            ack_missing=False, expected_context=None,
        )
        payload = export_service.generate_docx(bundle)
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            root = etree.fromstring(archive.read("word/document.xml"))
        return root

    def configure_locations(self, locations):
        current = config_service.read_class_games(self.session)
        change = {
            "kind": "class_games", "game_scope": None,
            "guidance": "按年级组织", "locations": locations,
        }
        preview = config_service.preview(
            self.session, expected_config_version=current["config_version"], change=change,
        )
        config_service.apply(
            self.session, request_id=str(uuid.uuid4()),
            expected_config_version=current["config_version"], change=change,
            preview_token=preview["preview_token"],
        )

    def test_either_morning_group_can_hold_the_only_focus(self):
        for selected in (0, 1):
            with self.subTest(selected=selected):
                candidate = copy.deepcopy(OTHER_CANDIDATE)
                for index, group in enumerate(candidate["morning_games"]):
                    group.pop("focus_guidance", None)
                    group["shared_objectives"] = f"第{index + 1}组游戏目标"
                    group["guidance_points"] = f"第{index + 1}组游戏指导"
                candidate["morning_games"][selected]["focus_guidance"] = "观察轮流与等待。"
                candidate_id = self.generate(self.plan["id"], "daily_other_activities", candidate)
                expected = copy.deepcopy(candidate)
                expected["morning_games"][selected]["focus_guidance"] = candidate["morning_games"][selected]["games"][0]["name"]
                other = expected["morning_games"][1 - selected]
                del other["shared_objectives"]
                del other["guidance_points"]
                normalized = self.detail(candidate_id)
                self.assertEqual(normalized, expected)
                preview = self.preview(self.plan["id"], candidate_id, ["morning_games"], normalized)
                self.adopt(self.plan["id"], candidate_id, preview["preview_token"])
                stored = self.plan_content(self.plan["id"])["adopted_content"]["morning_games"]
                self.assertEqual(
                    [[game["name"] for game in group["games"]] for group in stored],
                    [["阳光体育"], ["积木搭建"]],
                )
                self.assertEqual(stored[selected]["shared_objectives"], f"第{selected + 1}组游戏目标")
                self.assertEqual(stored[selected]["guidance_points"], f"第{selected + 1}组游戏指导")
                self.assertFalse(stored[1 - selected].get("shared_objectives"))
                self.assertFalse(stored[1 - selected].get("guidance_points"))

    def test_two_generated_focuses_become_one_through_adoption_and_word(self):
        candidate = copy.deepcopy(OTHER_CANDIDATE)
        candidate["morning_games"][0]["focus_guidance"] = "集体重点观察轮流。"
        candidate["morning_games"][1]["focus_guidance"] = "自选重点观察等待。"
        candidate_id = self.generate(self.plan["id"], "daily_other_activities", candidate)
        normalized = self.detail(candidate_id)
        expected = copy.deepcopy(candidate)
        expected["morning_games"][0]["focus_guidance"] = candidate["morning_games"][0]["games"][0]["name"]
        expected["morning_games"][1].pop("focus_guidance")
        expected["morning_games"][1].pop("guidance_points")
        self.assertEqual(normalized, expected)
        preview = self.preview(self.plan["id"], candidate_id, ["morning_games"], normalized)
        self.adopt(self.plan["id"], candidate_id, preview["preview_token"])
        root = self.export_text()
        namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        text = "".join(node.text or "" for node in root.iter(namespace + "t"))
        self.assertIn("重点指导：阳光体育", text)
        self.assertNotIn("集体重点观察轮流。", text)
        self.assertNotIn("自选重点观察等待。", text)

    def test_blank_focus_is_omitted_without_losing_the_other_group_focus(self):
        candidate = copy.deepcopy(OTHER_CANDIDATE)
        candidate["morning_games"][0]["focus_guidance"] = " \n\t "
        candidate["morning_games"][1]["focus_guidance"] = "观察自选活动中的轮流。"
        candidate_id = self.generate(self.plan["id"], "daily_other_activities", candidate)
        normalized = self.detail(candidate_id)
        self.assertNotIn("focus_guidance", normalized["morning_games"][0])
        self.assertNotIn("shared_objectives", normalized["morning_games"][0])
        self.assertEqual(normalized["morning_games"][1]["focus_guidance"], candidate["morning_games"][1]["games"][0]["name"])
        self.assertEqual(normalized["morning_games"][1]["guidance_points"], "指导要点")

    def test_missing_morning_focus_selects_one_real_game_name(self):
        candidate = copy.deepcopy(OTHER_CANDIDATE)
        for group in candidate["morning_games"]:
            group.pop("focus_guidance", None)
        candidate_id = self.generate(self.plan["id"], "daily_other_activities", candidate)
        groups = self.detail(candidate_id)["morning_games"]
        self.assertEqual(groups[0]["focus_guidance"], groups[0]["games"][0]["name"])
        self.assertEqual(groups[0]["shared_objectives"], "共同目标")
        self.assertNotIn("focus_guidance", groups[1])
        self.assertNotIn("guidance_points", groups[1])
        self.assertEqual(groups[1]["games"], candidate["morning_games"][1]["games"])

    def test_teacher_can_add_second_focus_when_editing_new_candidate(self):
        candidate_id = self.generate(self.plan["id"], "daily_other_activities", OTHER_CANDIDATE)
        edited = self.detail(candidate_id)
        edited["morning_games"][1]["focus_guidance"] = "教师自行增加的重点指导"
        edited["morning_games"][1]["shared_objectives"] = "教师补充自选游戏目标"
        edited["morning_games"][1]["guidance_points"] = "教师补充自选游戏指导"
        preview = self.preview(self.plan["id"], candidate_id, ["morning_games"], edited)
        self.adopt(self.plan["id"], candidate_id, preview["preview_token"])
        groups = self.plan_content(self.plan["id"])["adopted_content"]["morning_games"]
        self.assertEqual(groups[1]["focus_guidance"], "教师自行增加的重点指导")
        self.assertEqual(groups[1]["shared_objectives"], "教师补充自选游戏目标")
        self.assertEqual(groups[1]["guidance_points"], "教师补充自选游戏指导")

    def test_historical_second_focus_is_not_erased(self):
        candidate = copy.deepcopy(OTHER_CANDIDATE)
        candidate["morning_games"][1]["focus_guidance"] = "教师保留的第二份指导"
        candidate["morning_games"][1]["shared_objectives"] = "历史自选游戏目标"
        candidate["morning_games"][1]["guidance_points"] = "历史自选游戏指导"
        candidate["post_group_games"].append({
            "context_kind": "special_room", "area": "历史专用室",
            "games": [{"name": "历史游戏"}], "focus_guidance": "教师保留的详细指导。",
        })
        candidate["afternoon_outdoor"]["observation_focus"] = "教师保留的观察正文。"
        # Reconstruct an old result by bypassing only the new-result cleanup;
        # still use the task -> execution -> candidate chain and real hashes.
        with (
            mock.patch.object(ai_task_service, "_normalize_generated_morning_focus"),
            mock.patch.object(ai_task_service, "_normalize_generated_activity_regions"),
        ):
            candidate_id = self.generate(self.plan["id"], "daily_other_activities", candidate)
        self.assertEqual(self.detail(candidate_id), candidate)
        preview = self.preview(self.plan["id"], candidate_id, ["morning_games", "post_group_games", "afternoon_outdoor"], candidate)
        self.adopt(self.plan["id"], candidate_id, preview["preview_token"])
        stored = self.plan_content(self.plan["id"])["adopted_content"]
        self.assertEqual(stored["morning_games"][1]["focus_guidance"], "教师保留的第二份指导")
        self.assertEqual(stored["morning_games"][1]["shared_objectives"], "历史自选游戏目标")
        self.assertEqual(stored["morning_games"][1]["guidance_points"], "历史自选游戏指导")
        self.assertEqual(stored["post_group_games"][1]["context_kind"], "special_room")
        self.assertEqual(stored["post_group_games"][1]["focus_guidance"], "教师保留的详细指导。")
        self.assertEqual(stored["afternoon_outdoor"]["observation_focus"], "教师保留的观察正文。")

    def test_generated_regions_use_two_configured_names_and_keep_teaching_fields(self):
        self.configure_locations([
            {"kind": "area", "name": "美工区", "guidance": None},
            {"kind": "area", "name": "建构区", "guidance": None},
            {"kind": "area", "name": "阅读区", "guidance": None},
            {"kind": "outdoor", "name": "骑行", "guidance": "单向骑行"},
            {"kind": "outdoor", "name": "沙水池", "guidance": "分组操作"},
            {"kind": "special_room", "name": "音乐室", "guidance": None},
        ])
        candidate = copy.deepcopy(OTHER_CANDIDATE)
        primary = {
            "context_kind": "area", "area": "不存在区、美工区",
            "games": [{"name": "会动的小鸟"}], "focus_guidance": "建构区",
            "objectives": "比较并连接材料。", "guidance": "鼓励幼儿介绍作品。",
            "support_strategy": "提供不同连接材料。",
        }
        secondary = {
            "context_kind": "area", "area": "建构区",
            "games": [{"name": "会动的小鸟"}, {"name": "搭桥"}, {"name": "搭桥"}],
            "objectives": "尝试搭建稳定桥面。\n比较不同连接方式。",
            "guidance": "鼓励幼儿合作检验桥面。",
            "support_strategy": "提供不同长度的木板。",
        }
        candidate["post_group_games"] = [
            primary,
            secondary,
            {"context_kind": "special_room", "area": "音乐室", "games": [{"name": "节奏游戏"}]},
            {"context_kind": "outdoor", "area": "骑行", "games": [{"name": "接力骑行"}]},
        ]
        candidate["afternoon_outdoor"] = {
            "area": "不存在场地、沙水池", "games": [{"name": "水流探险"}],
            "observation_focus": "1. 观察动作。\n2. 记录合作。",
            "objectives": "尝试合作运水。", "guidance": "关注材料选择。",
            "support_strategy": "提供不同大小的容器。",
        }
        candidate_id = self.generate(self.plan["id"], "daily_other_activities", candidate)
        normalized = self.detail(candidate_id)
        self.assertEqual(len(normalized["post_group_games"]), 1)
        group = normalized["post_group_games"][0]
        self.assertEqual(group["area"], "美工区、建构区")
        self.assertEqual(group["focus_guidance"], "建构区", "retain a valid selected focus")
        self.assertEqual(group["context_kind"], "area")
        afternoon = normalized["afternoon_outdoor"]
        self.assertEqual(afternoon["area"], "沙水池、骑行")
        self.assertEqual(afternoon["observation_focus"], "沙水池")
        self.assertEqual(group["games"], [{"name": "会动的小鸟"}, {"name": "搭桥"}], "all indoor games survive, identical objects only once")
        for key in ("objectives", "guidance", "support_strategy"):
            self.assertEqual(group[key], primary[key] + "\n" + secondary[key], "preserve every paragraph in group order: " + key)
        for key in ("games", "objectives", "guidance", "support_strategy"):
            self.assertEqual(afternoon[key], candidate["afternoon_outdoor"][key], key)
        self.assertEqual(candidate["post_group_games"][0]["area"], "不存在区、美工区", "input fixture was not mutated")
        self.assertEqual(primary["games"], [{"name": "会动的小鸟"}])

        preview = self.preview(self.plan["id"], candidate_id, ["post_group_games"], normalized)
        self.adopt(self.plan["id"], candidate_id, preview["preview_token"])
        stored = self.plan_content(self.plan["id"])["adopted_content"]
        from app.local.weekly_plan_sources import _post_group_groups

        sources = _post_group_groups(stored)
        self.assertEqual(len(sources), 1)
        self.assertEqual([game["name"] for game in sources[0]["games"]], ["会动的小鸟", "搭桥"], "the second area's real game remains available to weekly source projection")
        game_ids = [game["game_id"] for game in sources[0]["games"]]
        self.assertTrue(all(game_ids))
        self.assertEqual(len(set(game_ids)), 2)
        for key in ("objectives", "guidance", "support_strategy"):
            self.assertEqual(sources[0][key], group[key], key)

    def test_only_available_configured_region_is_used_without_inventing_another(self):
        self.configure_locations([
            {"kind": "area", "name": "美工区", "guidance": None},
            {"kind": "outdoor", "name": "骑行", "guidance": None},
        ])
        candidate = copy.deepcopy(OTHER_CANDIDATE)
        candidate["post_group_games"][0].update(area="不存在区、重复区", focus_guidance="详细指导正文")
        candidate["afternoon_outdoor"].update(area="不存在场地", observation_focus="详细观察正文")
        candidate_id = self.generate(self.plan["id"], "daily_other_activities", candidate)
        normalized = self.detail(candidate_id)
        self.assertEqual(normalized["post_group_games"][0]["area"], "美工区")
        self.assertEqual(normalized["post_group_games"][0]["focus_guidance"], "美工区")
        self.assertEqual(normalized["afternoon_outdoor"]["area"], "骑行")
        self.assertEqual(normalized["afternoon_outdoor"]["observation_focus"], "骑行")

    def test_unconfigured_suggestions_keep_two_distinct_names_and_one_focus(self):
        candidate = copy.deepcopy(OTHER_CANDIDATE)
        candidate["post_group_games"][0].update(area="美工区、美工区、建构区、阅读区", focus_guidance="阅读区")
        candidate["afternoon_outdoor"].update(area="骑行、沙水池、草坪", observation_focus="沙水池")
        candidate_id = self.generate(self.plan["id"], "daily_other_activities", candidate)
        normalized = self.detail(candidate_id)
        self.assertEqual(normalized["post_group_games"][0]["area"], "美工区、建构区")
        self.assertEqual(normalized["post_group_games"][0]["focus_guidance"], "美工区")
        self.assertEqual(normalized["afternoon_outdoor"]["area"], "骑行、沙水池")
        self.assertEqual(normalized["afternoon_outdoor"]["observation_focus"], "沙水池")

    def test_generation_uses_frozen_location_config_after_later_config_change(self):
        self.configure_locations([
            {"kind": "area", "name": "原美工区", "guidance": None},
            {"kind": "area", "name": "原建构区", "guidance": None},
            {"kind": "outdoor", "name": "原骑行", "guidance": None},
            {"kind": "outdoor", "name": "原沙水池", "guidance": None},
        ])
        task, _ = ai_task_service.create_task(
            self.session, plan_id=self.plan["id"], task_type="daily_other_activities",
            expected_content_version=1, target_grade="middle", request_id=str(uuid.uuid4()),
        )
        claim = ai_task_service.claim_next(self.runtime, now=utc_now(), started_ticks=1)
        self.assertEqual(claim.task_id, task["id"])
        self.assertTrue(ai_task_service.commit_dispatch_mark(self.session, claim, utc_now()))
        self.configure_locations([
            {"kind": "area", "name": "新阅读区", "guidance": None},
            {"kind": "outdoor", "name": "新草坪", "guidance": None},
        ])
        self.assertTrue(ai_task_service.finalize_success(
            self.session, claim,
            {"kind": "success", "candidate_text": json.dumps(OTHER_CANDIDATE, ensure_ascii=False)},
            utc_now(),
        ))
        candidate_id = query_scalar(self.db, "SELECT id FROM local_ai_candidates WHERE execution_id = ?", (claim.execution_id,))
        normalized = self.detail(candidate_id)
        self.assertEqual(normalized["post_group_games"][0]["area"], "原美工区、原建构区")
        self.assertEqual(normalized["post_group_games"][0]["focus_guidance"], "原美工区")
        self.assertEqual(normalized["afternoon_outdoor"]["area"], "原骑行、原沙水池")
        self.assertEqual(normalized["afternoon_outdoor"]["observation_focus"], "原骑行")

    def test_teacher_region_edits_are_not_normalized_again_on_adoption(self):
        candidate_id = self.generate(self.plan["id"], "daily_other_activities", OTHER_CANDIDATE)
        edited = self.detail(candidate_id)
        edited["post_group_games"][0].update(area="教师自填区域", focus_guidance="教师自行填写的指导正文。")
        edited["afternoon_outdoor"].update(area="教师自填户外", observation_focus="教师自行填写的观察正文。")
        preview = self.preview(self.plan["id"], candidate_id, ["post_group_games", "afternoon_outdoor"], edited)
        self.adopt(self.plan["id"], candidate_id, preview["preview_token"])
        stored = self.plan_content(self.plan["id"])["adopted_content"]
        self.assertEqual(stored["post_group_games"][0]["area"], "教师自填区域")
        self.assertEqual(stored["post_group_games"][0]["focus_guidance"], "教师自行填写的指导正文。")
        self.assertEqual(stored["afternoon_outdoor"]["area"], "教师自填户外")
        self.assertEqual(stored["afternoon_outdoor"]["observation_focus"], "教师自行填写的观察正文。")

    def test_saved_outdoor_config_is_in_claim_payload_and_hard_rules(self):
        current = config_service.read_class_games(self.session)
        change = {
            "kind": "class_games", "game_scope": None, "guidance": "按年级组织",
            "locations": [
                {"kind": "area", "name": "测试阅读区", "guidance": None},
                {"kind": "outdoor", "name": "测试骑行道", "guidance": "单向骑行"},
                {"kind": "outdoor", "name": "测试沙水区", "guidance": "分组操作"},
            ],
        }
        preview = config_service.preview(self.session, expected_config_version=current["config_version"], change=change)
        config_service.apply(self.session, request_id=str(uuid.uuid4()), expected_config_version=current["config_version"], change=change, preview_token=preview["preview_token"])
        task, _ = ai_task_service.create_task(self.session, plan_id=self.plan["id"], task_type="daily_other_activities", expected_content_version=1, target_grade="middle", request_id=str(uuid.uuid4()))
        claim = ai_task_service.claim_next(self.runtime, now=utc_now(), started_ticks=1)
        self.assertEqual(claim.task_id, task["id"])
        self.assertEqual(claim.payload["game_config"]["locations"], change["locations"])
        system = json.loads(claim.system_text)
        rules = "\n".join(system["instructions"])
        self.assertIn("晨间只需要一份重点指导", rules)
        self.assertIn("仅重点指导所选游戏所在组填写活动目标 shared_objectives 和指导要点 guidance_points", rules)
        self.assertIn("另一组省略 focus_guidance、shared_objectives 和 guidance_points", rules)
        self.assertIn("两组 games 及游戏名称都保留", rules)
        self.assertNotIn("两组原有的共用目标、指导要点仍按要求填写", rules)
        self.assertIn("不得声称未收到户外配置", rules)
        self.assertIn("instructions 中的硬约束优先于 guidance", system["rule_precedence"])

    def test_split_then_explicit_adapt_preserves_baseline_and_exports_red(self):
        split_id = self.generate(self.plan["id"], "daily_lesson_split", SPLIT_CANDIDATE)
        preview = self.preview(self.plan["id"], split_id, ["group_activity"], SPLIT_CANDIDATE)
        self.adopt(self.plan["id"], split_id, preview["preview_token"])
        self.assertEqual(query_scalar(self.db, "SELECT count(*) FROM local_ai_tasks WHERE task_type='daily_process_adapt'"), 0)
        process = "1. 导入\n2. 观察\n师：请指一指颜色相同的叶子。"
        adapt_id = self.generate(self.plan["id"], "daily_process_adapt", {"operation": "replace", "step_index": 2, "text": "观察\n师：请指一指颜色相同的叶子。"})
        preview = self.preview(self.plan["id"], adapt_id, ["group_activity.process"], {"process": process})
        self.adopt(self.plan["id"], adapt_id, preview["preview_token"])
        self.assertEqual(self.plan_content(self.plan["id"])["split_baseline"]["group_activity_process"], SPLIT_CANDIDATE["group_activity"]["process"])
        namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        red = []
        for run in self.export_text().iter(namespace + "r"):
            color = run.find(namespace + "rPr/" + namespace + "color")
            if color is not None and color.get(namespace + "val") == "FF0000":
                red.extend(node.text or "" for node in run.iter(namespace + "t"))
        self.assertIn("请指一指颜色相同的叶子。", "".join(red))

    def test_new_identical_split_changes_baseline_but_repeated_adoption_does_not(self):
        # Automatic continuation relies on changed=true for a new split origin,
        # even when a newly selected target grade produces identical extraction.
        previous_version = self.content_version(self.plan["id"])
        for grade in ("middle", "small"):
            candidate_id = self.generate(self.plan["id"], "daily_lesson_split", SPLIT_CANDIDATE, grade=grade)
            preview = self.preview(self.plan["id"], candidate_id, ["group_activity"], SPLIT_CANDIDATE)
            result = self.adopt(self.plan["id"], candidate_id, preview["preview_token"])
            self.assertTrue(result["changed"])
            self.assertEqual(result["content_version"], previous_version + 1)
            previous_version = result["content_version"]
            detail = ai_candidates.get_candidate(self.session, plan_id=self.plan["id"], candidate_id=candidate_id)
            self.assertEqual(detail["source"]["target_grade"], grade)
            preview = self.preview(self.plan["id"], candidate_id, ["group_activity"], SPLIT_CANDIDATE)
            repeated = self.adopt(self.plan["id"], candidate_id, preview["preview_token"])
            self.assertFalse(repeated["changed"])
            self.assertEqual(repeated["content_version"], previous_version)
