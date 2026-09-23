"""V3 / V4 / V6 / V7 / V7b — empty weeks, empty content, same-name sources,
draft version conflicts and the "plain PATCH never re-stamps" rule.

Everything runs against the real HTTP contract plus real I3 daily plan
writes; no content assertion is mocked.
"""

from __future__ import annotations

import time

from tests.integration.i4_support import (
    DAY_MON,
    DAY_SAT,
    DAY_TUE,
    DAY_WED,
    EMPTY_WEEK,
    OWNER,
    TERM_ID,
    WEEK,
    ZERO_TEACHING_WEEK,
    AsgiClient,
    I4IntegrationTestCase,
    create_daily,
    day_content,
    pick_candidate,
    ref_payload,
    save_daily,
)

FULL_ACK = {
    "acknowledge_missing": True,
    "acknowledge_stale": True,
}


class V3EmptyWeekTests(I4IntegrationTestCase):
    def test_zero_daily_plan_week_creates_with_no_plan_days(self):
        created = self.owner_client.post(
            "/api/weekly-plans",
            {"term_id": TERM_ID, "week_number": EMPTY_WEEK, "theme": "空周主题"},
        )
        self.assertEqual(created.status_code, 201, created.content)
        content = created.json()["draft"]["content"]

        rows = {row["date"]: row for row in content["deterministic"]}
        self.assertEqual(
            sorted(rows),
            [
                "2026-09-21",
                "2026-09-22",
                "2026-09-23",
                "2026-09-24",
                "2026-09-25",
                "2026-09-26",
                "2026-09-27",
            ],
        )
        for day in ("2026-09-21", "2026-09-22", "2026-09-23"):
            self.assertEqual(rows[day]["day_state"], "teaching")
            self.assertEqual(rows[day]["plan_state"], "no_plan")
            self.assertEqual(
                rows[day]["source"],
                {
                    "daily_plan_id": None,
                    "content_id": None,
                    "content_version": None,
                    "morning_talk_topic": None,
                    "group_activity_theme": None,
                },
            )
            self.assertEqual(
                rows[day]["override"],
                {"morning_talk_topic": None, "group_activity_theme": None},
            )
            self.assertEqual(
                rows[day]["effective"],
                {"morning_talk_topic": None, "group_activity_theme": None},
            )
        for day in ("2026-09-26", "2026-09-27"):
            self.assertEqual(rows[day]["day_state"], "rest")
            self.assertEqual(rows[day]["plan_state"], "none_required")

        # Distinct expressions for the three cases, no auto-fill anywhere.
        self.assertEqual(rows["2026-09-21"]["plan_state"], "no_plan")
        self.assertEqual(rows["2026-09-26"]["plan_state"], "none_required")
        self.assertEqual(
            content["outdoor_game_slots"],
            {
                "collective_1": None,
                "collective_2": None,
                "free_choice_1": None,
            },
        )
        self.assertIsNone(content["focus_area"])
        self.assertIsNone(content["materials"])
        self.assertEqual(
            content["weekly_columns"],
            {
                "key_week_focus": "",
                "environment_setup": "",
                "habit_culture": "",
                "home_cooperation": "",
            },
        )

        detail = created.json()
        kinds = {item["kind"] for item in detail["missing"]}
        self.assertIn("missing_daily_plan_date", kinds)
        self.assertIn("outdoor_slot", kinds)
        self.assertIn("materials", kinds)
        self.assertNotIn("empty_theme", kinds)  # theme was provided
        missing_dates = {
            item["date"]
            for item in detail["missing"]
            if item["kind"] == "missing_daily_plan_date"
        }
        self.assertEqual(
            missing_dates,
            {
                "2026-09-21",
                "2026-09-22",
                "2026-09-23",
                "2026-09-24",
                "2026-09-25",
            },
        )
        self.assertEqual(detail["stale_sources"], [])
        self.assertFalse(detail["projection_pending"])

    def test_zero_teaching_day_week_is_allowed(self):
        created = self.owner_client.post(
            "/api/weekly-plans",
            {"term_id": TERM_ID, "week_number": ZERO_TEACHING_WEEK},
        )
        self.assertEqual(created.status_code, 201, created.content)
        content = created.json()["draft"]["content"]
        rows = content["deterministic"]
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row["day_state"], "rest")
            self.assertEqual(row["plan_state"], "none_required")
        kinds = {item["kind"] for item in created.json()["missing"]}
        self.assertNotIn("missing_daily_plan_date", kinds)
        self.assertIn("empty_theme", kinds)

    def test_partial_days_distinguish_saved_no_plan_and_rest(self):
        create_daily(
            self.SessionLocal,
            OWNER,
            DAY_MON,
            adopted_content=day_content(talk="周一话题", theme="周一主题"),
        )
        created = self.owner_client.post(
            "/api/weekly-plans",
            {"term_id": TERM_ID, "week_number": WEEK, "theme": "部分缺日"},
        )
        self.assertEqual(created.status_code, 201, created.content)
        content = created.json()["draft"]["content"]
        rows = {row["date"]: row for row in content["deterministic"]}

        saved = rows[DAY_MON.isoformat()]
        self.assertEqual(saved["day_state"], "teaching")
        self.assertEqual(saved["plan_state"], "saved")
        self.assertIsNotNone(saved["source"]["daily_plan_id"])
        self.assertEqual(saved["source"]["morning_talk_topic"], "周一话题")
        self.assertEqual(saved["source"]["group_activity_theme"], "周一主题")
        self.assertEqual(saved["source"]["content_version"], 1)
        self.assertEqual(saved["override"], {
            "morning_talk_topic": None,
            "group_activity_theme": None,
        })
        self.assertEqual(saved["effective"], {
            "morning_talk_topic": "周一话题",
            "group_activity_theme": "周一主题",
        })

        no_plan = rows[DAY_TUE.isoformat()]
        self.assertEqual(no_plan["plan_state"], "no_plan")
        self.assertIsNone(no_plan["source"]["daily_plan_id"])

        rest = rows[DAY_SAT.isoformat()]
        self.assertEqual(rest["day_state"], "rest")
        self.assertEqual(rest["plan_state"], "none_required")

        self.assertEqual(
            {saved["plan_state"], no_plan["plan_state"], rest["plan_state"]},
            {"saved", "no_plan", "none_required"},
        )

        detail = created.json()
        missing_dates = {
            item["date"]
            for item in detail["missing"]
            if item["kind"] == "missing_daily_plan_date"
        }
        self.assertEqual(
            missing_dates,
            {
                DAY_TUE.isoformat(),
                DAY_WED.isoformat(),
                "2026-09-10",
                "2026-09-11",
            },
        )
        self.assertNotIn(DAY_MON.isoformat(), missing_dates)


class V4EmptyContentTests(I4IntegrationTestCase):
    def test_empty_content_saves_and_confirms_only_with_ack(self):
        created = self.owner_client.post(
            "/api/weekly-plans",
            {"term_id": TERM_ID, "week_number": WEEK},
        )
        self.assertEqual(created.status_code, 201, created.content)
        plan_id = created.json()["id"]
        content = created.json()["draft"]["content"]
        self.assertEqual(content["theme"], "")
        self.assertEqual(
            content["outdoor_game_slots"],
            {
                "collective_1": None,
                "collective_2": None,
                "free_choice_1": None,
            },
        )
        self.assertTrue(all(v == "" for v in content["weekly_columns"].values()))

        # Saving empty content is valid (theme empty is not a 422).
        patched = self.owner_client.patch(
            f"/api/weekly-plans/{plan_id}",
            {
                "expected_draft_version": 1,
                "theme": "",
                "weekly_columns": {
                    "key_week_focus": "",
                    "environment_setup": "",
                    "habit_culture": "",
                    "home_cooperation": "",
                },
            },
        )
        self.assertEqual(patched.status_code, 200, patched.content)
        version = patched.json()["draft"]["version"]
        self.assertEqual(version, 2)

        # No ack -> 409 with the recomputed facts.
        blocked = self.owner_client.post(
            f"/api/weekly-plans/{plan_id}/confirm",
            {
                "expected_draft_version": version,
                "acknowledge_missing": False,
                "acknowledge_stale": False,
            },
        )
        self.assertEqual(blocked.status_code, 409, blocked.content)
        self.assertEqual(blocked.code, "CONFIRM_ACK_REQUIRED")
        facts = blocked.facts
        self.assertIsNotNone(facts)
        kinds = {item["kind"] for item in facts["missing"]}
        self.assertIn("empty_theme", kinds)
        self.assertIn("outdoor_slot", kinds)
        self.assertIn("materials", kinds)
        self.assertIn("empty_field", kinds)
        self.assertIn("missing_daily_plan_date", kinds)
        self.assertEqual(facts["stale_sources"], [])
        self.assertFalse(facts["ack_missing"])
        self.assertEqual(self.confirmed_count(plan_id), 0)

        # Correct ack -> 201, and the stored content stays empty.
        confirmed = self.owner_client.post(
            f"/api/weekly-plans/{plan_id}/confirm",
            {
                "expected_draft_version": version,
                "acknowledge_missing": True,
                "acknowledge_stale": False,
                "note": "按空内容确认",
            },
        )
        self.assertEqual(confirmed.status_code, 201, confirmed.content)
        body = confirmed.json()
        self.assertEqual(body["version"], 1)
        self.assertEqual(body["draft_version"], 2)
        stored = body["content"]
        self.assertEqual(stored["theme"], "")
        self.assertTrue(
            all(v is None for v in stored["outdoor_game_slots"].values())
        )
        self.assertTrue(all(v == "" for v in stored["weekly_columns"].values()))
        self.assertIsNone(stored["materials"])
        self.assertIsNone(stored["focus_area"])
        self.assertTrue(body["facts"]["ack_missing"])
        self.assertEqual(body["facts"]["note"], "按空内容确认")
        empty_theme_items = [
            item for item in body["facts"]["missing"]
            if item["kind"] == "empty_theme"
        ]
        self.assertEqual(empty_theme_items, [{"kind": "empty_theme"}])

        # Partial ack still fails: missing without ack_missing.
        second = self.owner_client.patch(
            f"/api/weekly-plans/{plan_id}",
            {"expected_draft_version": version, "theme": "再来一次"},
        )
        self.assertEqual(second.status_code, 200, second.content)
        still_missing = self.owner_client.post(
            f"/api/weekly-plans/{plan_id}/confirm",
            {
                "expected_draft_version": second.json()["draft"]["version"],
                "acknowledge_missing": False,
                "acknowledge_stale": True,
            },
        )
        self.assertEqual(still_missing.status_code, 409, still_missing.content)
        self.assertEqual(still_missing.code, "CONFIRM_ACK_REQUIRED")
        self.assertEqual(self.confirmed_count(plan_id), 1)


class V6SameNameSourceTests(I4IntegrationTestCase):
    def _seed_same_name_plans(self) -> tuple[object, object]:
        mon_plan, mon_content, _ = create_daily(
            self.SessionLocal,
            OWNER,
            DAY_MON,
            adopted_content=day_content(
                talk="周一谈话",
                theme="周一活动",
                collective={
                    "names": ["跳圈圈"],
                    "shared_objectives": "甲组目标",
                    "guidance_points": "甲组指导",
                    "focus_guidance": "甲组聚焦",
                },
            ),
        )
        tue_plan, tue_content, _ = create_daily(
            self.SessionLocal,
            OWNER,
            DAY_TUE,
            adopted_content=day_content(
                talk="周二谈话",
                theme="周二活动",
                collective={
                    "names": ["跳圈圈"],
                    "shared_objectives": "乙组目标",
                    "guidance_points": "乙组指导",
                    "focus_guidance": "乙组聚焦",
                },
            ),
        )
        return mon_content, tue_content

    def test_same_name_game_is_one_slot_with_switchable_full_binding(self):
        mon_content, tue_content = self._seed_same_name_plans()

        created = self.owner_client.post(
            "/api/weekly-plans",
            {"term_id": TERM_ID, "week_number": WEEK, "theme": "同名游戏"},
        )
        self.assertEqual(created.status_code, 201, created.content)
        plan_id = created.json()["id"]

        candidates = [
            c
            for c in created.json()["source_candidates"]
            if c["name"] == "跳圈圈" and c["category"] == "collective"
        ]
        self.assertEqual(len(candidates), 2)
        self.assertEqual(
            sorted(c["date"] for c in candidates),
            ["2026-09-07", "2026-09-08"],
        )
        source_a = next(c for c in candidates if c["date"] == "2026-09-07")
        source_b = next(c for c in candidates if c["date"] == "2026-09-08")
        self.assertNotEqual(source_a["content_id"], source_b["content_id"])

        # Pick source A.
        picked = self.owner_client.patch(
            f"/api/weekly-plans/{plan_id}",
            {
                "expected_draft_version": 1,
                "outdoor_game_slots": {"collective_1": ref_payload(source_a)},
            },
        )
        self.assertEqual(picked.status_code, 200, picked.content)
        slot = picked.json()["draft"]["content"]["outdoor_game_slots"][
            "collective_1"
        ]
        self.assertEqual(slot["source_kind"], "daily_plan")
        self.assertEqual(slot["daily_plan_id"], source_a["daily_plan_id"])
        self.assertEqual(slot["content_id"], source_a["content_id"])
        self.assertEqual(slot["content_version"], source_a["content_version"])
        self.assertEqual(slot["group_id"], source_a["group_id"])
        self.assertEqual(slot["game_id"], source_a["game_id"])
        self.assertEqual(slot["shared_objectives"], "甲组目标")
        self.assertEqual(slot["guidance_points"], "甲组指导")
        self.assertEqual(slot["focus_guidance"], "甲组聚焦")
        self.assertEqual(slot["name"], "跳圈圈")
        # One slot occupied: the same-named game takes a single seat.
        occupied = [
            key
            for key, value in picked.json()["draft"]["content"][
                "outdoor_game_slots"
            ].items()
            if value is not None
        ]
        self.assertEqual(occupied, ["collective_1"])

        # A second collective seat cannot take the same name.
        clash = self.owner_client.patch(
            f"/api/weekly-plans/{plan_id}",
            {
                "expected_draft_version": 2,
                "outdoor_game_slots": {"collective_2": ref_payload(source_a)},
            },
        )
        self.assertEqual(clash.status_code, 422, clash.content)
        self.assertEqual(clash.code, "VALIDATION_ERROR")

        # Confirm with source A bound in full.
        confirmed_a = self.owner_client.post(
            f"/api/weekly-plans/{plan_id}/confirm",
            {
                "expected_draft_version": 2,
                **FULL_ACK,
            },
        )
        self.assertEqual(confirmed_a.status_code, 201, confirmed_a.content)
        confirmed_slot = confirmed_a.json()["content"]["outdoor_game_slots"][
            "collective_1"
        ]
        self.assertEqual(confirmed_slot["content_id"], source_a["content_id"])
        self.assertEqual(confirmed_slot["shared_objectives"], "甲组目标")
        self.assertEqual(
            confirmed_slot["daily_plan_id"], source_a["daily_plan_id"]
        )
        self.assertEqual(confirmed_slot["group_id"], source_a["group_id"])
        self.assertEqual(confirmed_slot["game_id"], source_a["game_id"])

        # Switch to source B: references and the whole group text move together.
        # Draft is still version 2 — the rejected clash never appended a row.
        switched = self.owner_client.patch(
            f"/api/weekly-plans/{plan_id}",
            {
                "expected_draft_version": 2,
                "outdoor_game_slots": {"collective_1": ref_payload(source_b)},
            },
        )
        self.assertEqual(switched.status_code, 200, switched.content)
        slot_b = switched.json()["draft"]["content"]["outdoor_game_slots"][
            "collective_1"
        ]
        self.assertEqual(slot_b["daily_plan_id"], source_b["daily_plan_id"])
        self.assertEqual(slot_b["content_id"], source_b["content_id"])
        self.assertEqual(slot_b["content_version"], source_b["content_version"])
        self.assertEqual(slot_b["group_id"], source_b["group_id"])
        self.assertEqual(slot_b["game_id"], source_b["game_id"])
        self.assertEqual(slot_b["shared_objectives"], "乙组目标")
        self.assertEqual(slot_b["guidance_points"], "乙组指导")
        self.assertEqual(slot_b["focus_guidance"], "乙组聚焦")
        self.assertNotEqual(slot_b["shared_objectives"], "甲组目标")
        self.assertNotEqual(slot_b["guidance_points"], "甲组指导")
        self.assertNotIn("甲组", str(slot_b))

        # The confirmed A snapshot is untouched by the switch.
        history_a = self.owner_client.get(
            f"/api/weekly-plans/{plan_id}/confirmations/1"
        )
        self.assertEqual(history_a.status_code, 200)
        old_slot = history_a.json()["content"]["outdoor_game_slots"][
            "collective_1"
        ]
        self.assertEqual(old_slot["content_id"], source_a["content_id"])
        self.assertEqual(old_slot["shared_objectives"], "甲组目标")

        # Source identity really came from the stored I3 rows.
        self.assertEqual(
            mon_content.adopted_content["morning_games"][0]["games"][0]["name"],
            "跳圈圈",
        )
        self.assertEqual(
            tue_content.adopted_content["morning_games"][0]["games"][0]["name"],
            "跳圈圈",
        )


class V7VersionConflictTests(I4IntegrationTestCase):
    def test_two_tabs_patch_refresh_and_confirm_conflicts(self):
        created = self.owner_client.post(
            "/api/weekly-plans",
            {"term_id": TERM_ID, "week_number": WEEK, "theme": "冲突基线"},
        )
        self.assertEqual(created.status_code, 201, created.content)
        plan_id = created.json()["id"]

        tab_a = self.owner_client
        tab_b = AsgiClient()
        tab_b.login_as(OWNER)

        first = tab_a.patch(
            f"/api/weekly-plans/{plan_id}",
            {"expected_draft_version": 1, "theme": "标签A胜出"},
        )
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(first.json()["draft"]["version"], 2)

        stale_patch = tab_b.patch(
            f"/api/weekly-plans/{plan_id}",
            {"expected_draft_version": 1, "theme": "标签B被拒"},
        )
        self.assertEqual(stale_patch.status_code, 409, stale_patch.content)
        self.assertEqual(stale_patch.code, "VERSION_CONFLICT")

        stale_refresh = tab_b.post(
            f"/api/weekly-plans/{plan_id}/refresh-sources",
            {"expected_draft_version": 1},
        )
        self.assertEqual(stale_refresh.status_code, 409, stale_refresh.content)
        self.assertEqual(stale_refresh.code, "VERSION_CONFLICT")

        stale_confirm = tab_b.post(
            f"/api/weekly-plans/{plan_id}/confirm",
            {
                "expected_draft_version": 1,
                "acknowledge_missing": True,
                "acknowledge_stale": True,
            },
        )
        self.assertEqual(stale_confirm.status_code, 409, stale_confirm.content)
        self.assertEqual(stale_confirm.code, "VERSION_CONFLICT")

        # Server state was not overwritten by the losing requests.
        self.assertEqual(self.draft_count(plan_id), 2)
        self.assertEqual(self.confirmed_count(plan_id), 0)
        detail = tab_a.get(f"/api/weekly-plans/{plan_id}").json()
        self.assertEqual(detail["draft"]["version"], 2)
        self.assertEqual(detail["draft"]["content"]["theme"], "标签A胜出")

        # Retrying with the server version succeeds.
        retry = tab_b.patch(
            f"/api/weekly-plans/{plan_id}",
            {"expected_draft_version": 2, "theme": "标签B改用最新版本"},
        )
        self.assertEqual(retry.status_code, 200, retry.content)
        self.assertEqual(retry.json()["draft"]["version"], 3)
        self.assertEqual(
            retry.json()["draft"]["content"]["theme"], "标签B改用最新版本"
        )

    def test_invalid_expected_version_is_422(self):
        created = self.owner_client.post(
            "/api/weekly-plans",
            {"term_id": TERM_ID, "week_number": WEEK},
        )
        plan_id = created.json()["id"]
        for bad in (0, -1, "1", True, None):
            response = self.owner_client.patch(
                f"/api/weekly-plans/{plan_id}",
                {"expected_draft_version": bad, "theme": "x"},
            )
            self.assertEqual(
                response.status_code, 422, f"{bad!r}: {response.content}"
            )
        self.assertEqual(self.draft_count(plan_id), 1)


class V7bNoRestampTests(I4IntegrationTestCase):
    def _seed_source(self):
        plan, content, _ = create_daily(
            self.SessionLocal,
            OWNER,
            DAY_MON,
            adopted_content=day_content(
                talk="原始话题",
                theme="原始主题",
                collective={
                    "names": ["跳圈圈"],
                    "shared_objectives": "原始目标",
                    "guidance_points": "原始指导",
                    "focus_guidance": "原始聚焦",
                },
            ),
        )
        group = content.adopted_content["morning_games"][0]
        return plan, group["group_id"], group["games"][0]["game_id"]

    def test_plain_patch_keeps_stale_slot_but_refresh_updates_it(self):
        daily_plan, group_id, game_id = self._seed_source()

        created = self.owner_client.post(
            "/api/weekly-plans",
            {"term_id": TERM_ID, "week_number": WEEK, "theme": "不重盖章"},
        )
        self.assertEqual(created.status_code, 201, created.content)
        plan_id = created.json()["id"]

        candidate = pick_candidate(
            created.json(), category="collective", name="跳圈圈"
        )
        picked = self.owner_client.patch(
            f"/api/weekly-plans/{plan_id}",
            {
                "expected_draft_version": 1,
                "outdoor_game_slots": {"collective_1": ref_payload(candidate)},
                "deterministic_overrides": {
                    DAY_MON.isoformat(): {
                        "morning_talk_topic": "人工谈话覆盖",
                        "group_activity_theme": None,
                    }
                },
            },
        )
        self.assertEqual(picked.status_code, 200, picked.content)
        version = picked.json()["draft"]["version"]
        stamped_slot = picked.json()["draft"]["content"]["outdoor_game_slots"][
            "collective_1"
        ]
        stamped_content_id = stamped_slot["content_id"]
        stamped_version = stamped_slot["content_version"]
        stamped_objectives = stamped_slot["shared_objectives"]
        self.assertEqual(stamped_version, 1)
        self.assertEqual(stamped_objectives, "原始目标")

        # I3 writes a new daily plan content version (real save).
        # ``projection_consumed_at`` / ``updated_at`` are MySQL DATETIME
        # (second precision), so cross a real second boundary first — the
        # banner compares whole seconds by design.
        time.sleep(1.05)
        _, daily_content_v1 = (
            self._daily_content_row(daily_plan.id)
        )
        save_daily(
            self.SessionLocal,
            OWNER,
            daily_plan.id,
            daily_content_v1.version,
            adopted_content=day_content(
                talk="新话题",
                theme="新主题",
                collective={
                    "group_id": group_id,
                    "names": [{"name": "跳圈圈", "game_id": game_id}],
                    "shared_objectives": "更新后目标",
                    "guidance_points": "更新后指导",
                    "focus_guidance": "更新后聚焦",
                },
            ),
        )
        _, daily_content_v2 = self._daily_content_row(daily_plan.id)
        self.assertEqual(daily_content_v2.version, 2)

        # Live facts now report the slot as stale.
        stale_detail = self.owner_client.get(f"/api/weekly-plans/{plan_id}").json()
        stale_slots = [
            item
            for item in stale_detail["stale_sources"]
            if item["slot"] == "collective_1"
        ]
        self.assertEqual(len(stale_slots), 1)
        self.assertEqual(stale_slots[0]["draft"]["content_version"], 1)
        self.assertEqual(stale_slots[0]["current"]["content_version"], 2)
        self.assertTrue(stale_detail["projection_pending"])

        # Plain PATCH (theme + manual columns only) must not re-stamp.
        plain = self.owner_client.patch(
            f"/api/weekly-plans/{plan_id}",
            {
                "expected_draft_version": version,
                "theme": "只改主题",
                "weekly_columns": {
                    "key_week_focus": "本周重点",
                    "environment_setup": "环境",
                    "habit_culture": "习惯",
                    "home_cooperation": "家园",
                },
            },
        )
        self.assertEqual(plain.status_code, 200, plain.content)
        plain_content = plain.json()["draft"]["content"]
        plain_slot = plain_content["outdoor_game_slots"]["collective_1"]
        self.assertEqual(plain_slot["content_id"], stamped_content_id)
        self.assertEqual(plain_slot["content_version"], stamped_version)
        self.assertEqual(plain_slot["shared_objectives"], stamped_objectives)
        self.assertEqual(plain_slot["guidance_points"], "原始指导")
        self.assertEqual(plain_slot["group_id"], group_id)
        self.assertEqual(plain_slot["game_id"], game_id)
        self.assertEqual(plain_content["theme"], "只改主题")
        self.assertEqual(
            plain_content["weekly_columns"]["key_week_focus"], "本周重点"
        )

        # Deterministic source DID move to the new version, override stayed.
        plain_row = next(
            row
            for row in plain_content["deterministic"]
            if row["date"] == DAY_MON.isoformat()
        )
        self.assertEqual(plain_row["source"]["content_version"], 2)
        self.assertEqual(plain_row["source"]["morning_talk_topic"], "新话题")
        self.assertEqual(
            plain_row["override"]["morning_talk_topic"], "人工谈话覆盖"
        )
        self.assertEqual(
            plain_row["effective"]["morning_talk_topic"], "人工谈话覆盖"
        )
        self.assertEqual(
            plain_row["effective"]["group_activity_theme"], "新主题"
        )

        # Explicit refresh re-resolves the slot, override/theme/columns keep.
        refreshed = self.owner_client.post(
            f"/api/weekly-plans/{plan_id}/refresh-sources",
            {"expected_draft_version": plain.json()["draft"]["version"]},
        )
        self.assertEqual(refreshed.status_code, 200, refreshed.content)
        refreshed_content = refreshed.json()["draft"]["content"]
        refreshed_slot = refreshed_content["outdoor_game_slots"]["collective_1"]
        self.assertEqual(refreshed_slot["content_id"], daily_content_v2.id)
        self.assertEqual(refreshed_slot["content_version"], 2)
        self.assertEqual(refreshed_slot["shared_objectives"], "更新后目标")
        self.assertEqual(refreshed_slot["guidance_points"], "更新后指导")
        self.assertEqual(refreshed_slot["focus_guidance"], "更新后聚焦")
        self.assertEqual(refreshed_slot["group_id"], group_id)
        self.assertEqual(refreshed_slot["game_id"], game_id)
        self.assertEqual(refreshed_content["theme"], "只改主题")
        self.assertEqual(
            refreshed_content["weekly_columns"]["key_week_focus"], "本周重点"
        )
        refreshed_row = next(
            row
            for row in refreshed_content["deterministic"]
            if row["date"] == DAY_MON.isoformat()
        )
        self.assertEqual(
            refreshed_row["override"]["morning_talk_topic"], "人工谈话覆盖"
        )
        self.assertEqual(
            refreshed_row["effective"]["morning_talk_topic"], "人工谈话覆盖"
        )
        self.assertFalse(refreshed.json()["projection_pending"])

        # The refresh audit records the from -> to movement.
        audit = refreshed.json()["draft"]["audit"]
        self.assertEqual(audit["action"], "refresh")
        entries = audit["refreshed_sources"]
        slot_entries = [
            entry for entry in entries if entry.get("slot") == "collective_1"
        ]
        self.assertEqual(len(slot_entries), 1)
        self.assertEqual(slot_entries[0]["from"]["content_version"], 1)
        self.assertEqual(slot_entries[0]["to"]["content_version"], 2)

    def _daily_content_row(self, plan_id: str):
        rows = self.rows(
            "SELECT id, version FROM daily_plan_contents "
            "WHERE daily_plan_id = :id ORDER BY version DESC LIMIT 1",
            {"id": plan_id},
        )
        row_id, version = rows[0]

        class _Row:
            def __init__(self, ident, ver):
                self.id = ident
                self.version = ver

        return plan_id, _Row(row_id, version)
