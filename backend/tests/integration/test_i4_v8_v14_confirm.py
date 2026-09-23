"""V8 / V9 / V10 / V13 / V14 — source change before confirm, admin edit
after confirmation, incomplete confirmation, immutable history and the I3
projection contract.

All source mutations are real I3 daily plan writes; projection immutability
is proven with whole-row before/after comparisons around every I4 write.
"""

from __future__ import annotations

import json
import time

from tests.integration.i4_support import (
    ADMIN,
    CLASS_ID,
    DAY_MON,
    DAY_TUE,
    OWNER,
    TERM_ID,
    WEEK,
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

SYNC_ROW_SQL = (
    "SELECT id, class_id, term_id, week_number, status, "
    "deterministic_themes, game_source_manifest, "
    "current_week_source_manifest, last_trigger_daily_plan_id, "
    "last_trigger_content_version, last_trigger_event, created_at, updated_at "
    "FROM weekly_plan_sync_states ORDER BY id"
)


class V8SourceChangeBeforeConfirmTests(I4IntegrationTestCase):
    def _setup_draft_with_slot(self) -> tuple[str, dict, dict]:
        daily_plan, daily_content, _ = create_daily(
            self.SessionLocal,
            OWNER,
            DAY_MON,
            adopted_content=day_content(
                talk="原话题",
                theme="原主题",
                collective={
                    "names": ["跳圈圈"],
                    "shared_objectives": "原目标",
                    "guidance_points": "原指导",
                    "focus_guidance": "原聚焦",
                },
            ),
        )
        group = daily_content.adopted_content["morning_games"][0]
        group_id = group["group_id"]
        game_id = group["games"][0]["game_id"]

        created = self.owner_client.post(
            "/api/weekly-plans",
            {"term_id": TERM_ID, "week_number": WEEK, "theme": "来源变化"},
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
                    DAY_MON.isoformat(): {"morning_talk_topic": "人工保留话题"}
                },
            },
        )
        self.assertEqual(picked.status_code, 200, picked.content)
        slot = picked.json()["draft"]["content"]["outdoor_game_slots"][
            "collective_1"
        ]
        return plan_id, slot, {"group_id": group_id, "game_id": game_id,
                               "plan": daily_plan}

    def _change_source_daily(self, identities: dict) -> None:
        """Another session (admin) rewrites the source daily plan."""
        plan = identities["plan"]
        current = self.rows(
            "SELECT id, version FROM daily_plan_contents "
            "WHERE daily_plan_id = :id ORDER BY version DESC LIMIT 1",
            {"id": plan.id},
        )[0]
        save_daily(
            self.SessionLocal,
            ADMIN,
            plan.id,
            current[1],
            adopted_content=day_content(
                talk="新话题",
                theme="新主题",
                collective={
                    "group_id": identities["group_id"],
                    "names": [
                        {"name": "跳圈圈", "game_id": identities["game_id"]}
                    ],
                    "shared_objectives": "新目标",
                    "guidance_points": "新指导",
                    "focus_guidance": "新聚焦",
                },
            ),
        )

    def test_confirm_without_ack_returns_409_with_latest_facts(self):
        plan_id, old_slot, identities = self._setup_draft_with_slot()
        self._change_source_daily(identities)

        response = self.owner_client.post(
            f"/api/weekly-plans/{plan_id}/confirm",
            {
                "expected_draft_version": 2,
                "acknowledge_missing": False,
                "acknowledge_stale": False,
            },
        )
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.code, "CONFIRM_ACK_REQUIRED")
        facts = response.facts
        self.assertTrue(facts["missing"])
        self.assertTrue(facts["stale_sources"])

        slot_stale = next(
            item
            for item in facts["stale_sources"]
            if item["slot"] == "collective_1"
        )
        self.assertEqual(
            slot_stale["draft"]["content_id"], old_slot["content_id"]
        )
        self.assertEqual(slot_stale["draft"]["content_version"], 1)
        self.assertEqual(slot_stale["current"]["content_version"], 2)
        self.assertNotEqual(
            slot_stale["draft"]["content_id"],
            slot_stale["current"]["content_id"],
        )
        self.assertTrue(slot_stale["current_item_exists"])

        det_stale = [
            item
            for item in facts["stale_sources"]
            if item["slot"] == "deterministic"
        ]
        self.assertTrue(det_stale)
        self.assertEqual(det_stale[0]["date"], DAY_MON.isoformat())
        self.assertEqual(det_stale[0]["draft"]["content_version"], 1)
        self.assertEqual(det_stale[0]["current"]["content_version"], 2)

        # Nothing was confirmed.
        self.assertEqual(self.confirmed_count(plan_id), 0)

    def test_path_r_refresh_then_confirm_uses_new_sources(self):
        plan_id, old_slot, identities = self._setup_draft_with_slot()
        self._change_source_daily(identities)

        refreshed = self.owner_client.post(
            f"/api/weekly-plans/{plan_id}/refresh-sources",
            {"expected_draft_version": 2},
        )
        self.assertEqual(refreshed.status_code, 200, refreshed.content)
        body = refreshed.json()
        self.assertEqual(body["stale_sources"], [])
        slot = body["draft"]["content"]["outdoor_game_slots"]["collective_1"]
        self.assertEqual(slot["content_version"], 2)
        self.assertEqual(slot["shared_objectives"], "新目标")
        self.assertEqual(slot["guidance_points"], "新指导")
        self.assertNotEqual(slot["content_id"], old_slot["content_id"])
        row = next(
            r
            for r in body["draft"]["content"]["deterministic"]
            if r["date"] == DAY_MON.isoformat()
        )
        # Manual override survives the refresh; source moved on.
        self.assertEqual(
            row["override"]["morning_talk_topic"], "人工保留话题"
        )
        self.assertEqual(
            row["effective"]["morning_talk_topic"], "人工保留话题"
        )
        self.assertEqual(row["source"]["content_version"], 2)
        self.assertEqual(body["draft"]["content"]["theme"], "来源变化")

        confirmed = self.owner_client.post(
            f"/api/weekly-plans/{plan_id}/confirm",
            {
                "expected_draft_version": body["draft"]["version"],
                "acknowledge_missing": True,
                "acknowledge_stale": False,
            },
        )
        self.assertEqual(confirmed.status_code, 201, confirmed.content)
        facts = confirmed.json()["facts"]
        self.assertEqual(facts["stale_sources"], [])
        self.assertTrue(facts["ack_missing"])
        self.assertFalse(facts["ack_stale"])
        confirmed_slot = confirmed.json()["content"]["outdoor_game_slots"][
            "collective_1"
        ]
        self.assertEqual(confirmed_slot["content_version"], 2)
        self.assertEqual(confirmed_slot["shared_objectives"], "新目标")

    def test_path_c_confirm_keeps_old_sources_with_two_sided_facts(self):
        plan_id, old_slot, identities = self._setup_draft_with_slot()
        self._change_source_daily(identities)

        confirmed = self.owner_client.post(
            f"/api/weekly-plans/{plan_id}/confirm",
            {
                "expected_draft_version": 2,
                **FULL_ACK,
                "note": "按当前草稿确认",
            },
        )
        self.assertEqual(confirmed.status_code, 201, confirmed.content)
        body = confirmed.json()

        # Snapshot keeps the OLD ids / version / text.
        slot = body["content"]["outdoor_game_slots"]["collective_1"]
        self.assertEqual(slot["content_id"], old_slot["content_id"])
        self.assertEqual(slot["content_version"], 1)
        self.assertEqual(slot["shared_objectives"], "原目标")
        self.assertEqual(slot["guidance_points"], "原指导")
        self.assertEqual(slot["focus_guidance"], "原聚焦")
        self.assertNotIn("新目标", json.dumps(slot, ensure_ascii=False))

        # Facts record BOTH sides; the old side is never marked as current.
        stale = next(
            item
            for item in body["facts"]["stale_sources"]
            if item["slot"] == "collective_1"
        )
        self.assertEqual(stale["draft"]["content_id"], slot["content_id"])
        self.assertEqual(stale["draft"]["content_version"], 1)
        self.assertEqual(stale["current"]["content_version"], 2)
        self.assertNotEqual(
            stale["draft"]["content_id"], stale["current"]["content_id"]
        )
        self.assertTrue(stale["current_item_exists"])
        det = next(
            item
            for item in body["facts"]["stale_sources"]
            if item["slot"] == "deterministic"
        )
        self.assertEqual(det["draft"]["content_version"], 1)
        self.assertEqual(det["current"]["content_version"], 2)
        self.assertTrue(body["facts"]["ack_stale"])
        self.assertTrue(body["facts"]["ack_missing"])
        self.assertEqual(body["facts"]["note"], "按当前草稿确认")

        # Live detail still reports the source as stale after confirming.
        detail = self.owner_client.get(f"/api/weekly-plans/{plan_id}").json()
        live_slot_stale = [
            item
            for item in detail["stale_sources"]
            if item["slot"] == "collective_1"
        ]
        self.assertEqual(len(live_slot_stale), 1)
        self.assertEqual(
            live_slot_stale[0]["current"]["content_version"], 2
        )
        self.assertEqual(
            detail["draft"]["content"]["outdoor_game_slots"]["collective_1"][
                "content_version"
            ],
            1,
        )


class V9AdminEditAfterConfirmTests(I4IntegrationTestCase):
    def test_admin_patch_creates_draft_ahead_without_touching_v1(self):
        created = self.owner_client.post(
            "/api/weekly-plans",
            {"term_id": TERM_ID, "week_number": WEEK, "theme": "确认前主题"},
        )
        self.assertEqual(created.status_code, 201, created.content)
        plan_id = created.json()["id"]

        confirmed = self.owner_client.post(
            f"/api/weekly-plans/{plan_id}/confirm",
            {
                "expected_draft_version": 1,
                "acknowledge_missing": True,
                "acknowledge_stale": False,
            },
        )
        self.assertEqual(confirmed.status_code, 201, confirmed.content)
        self.assertEqual(confirmed.json()["version"], 1)

        before = self.rows(
            "SELECT content, facts, draft_version, confirmed_by FROM "
            "weekly_plan_confirmed_contents WHERE weekly_plan_id = :id "
            "AND version = 1",
            {"id": plan_id},
        )
        self.assertEqual(len(before), 1)

        patched = self.admin_client.patch(
            f"/api/weekly-plans/{plan_id}?class_id={CLASS_ID}",
            {"expected_draft_version": 1, "theme": "管理员改后主题"},
        )
        self.assertEqual(patched.status_code, 200, patched.content)
        body = patched.json()
        self.assertEqual(body["draft"]["version"], 2)
        self.assertEqual(body["draft"]["editor_role"], "admin")
        self.assertEqual(body["confirmation_status"], "draft_ahead")
        self.assertTrue(body["needs_confirm"])
        self.assertEqual(body["confirmed"]["version"], 1)
        self.assertEqual(body["confirmed"]["draft_version"], 1)
        self.assertTrue(body["can_edit"])
        self.assertFalse(body["can_confirm"])

        # Admin confirm is 403 no matter how recently it edited.
        denied = self.admin_client.post(
            f"/api/weekly-plans/{plan_id}/confirm?class_id={CLASS_ID}",
            {
                "expected_draft_version": 2,
                "acknowledge_missing": True,
                "acknowledge_stale": True,
            },
        )
        self.assertEqual(denied.status_code, 403, denied.content)
        self.assertEqual(denied.code, "FORBIDDEN")

        after = self.rows(
            "SELECT content, facts, draft_version, confirmed_by FROM "
            "weekly_plan_confirmed_contents WHERE weekly_plan_id = :id "
            "AND version = 1",
            {"id": plan_id},
        )
        self.assertEqual(before, after)
        self.assertEqual(self.confirmed_count(plan_id), 1)

        # Owner still sees it as waiting for their confirmation.
        owner_detail = self.owner_client.get(
            f"/api/weekly-plans/{plan_id}"
        ).json()
        self.assertEqual(owner_detail["confirmation_status"], "draft_ahead")
        self.assertTrue(owner_detail["needs_confirm"])
        self.assertTrue(owner_detail["can_confirm"])


class V10IncompleteConfirmTests(I4IntegrationTestCase):
    def test_missing_collective_slot_requires_ack_and_stays_visible(self):
        create_daily(
            self.SessionLocal,
            OWNER,
            DAY_MON,
            adopted_content=day_content(
                talk="周一话",
                theme="周一活",
                collective={
                    "names": ["跳圈圈"],
                    "shared_objectives": "集体目标",
                    "guidance_points": "集体指导",
                },
                free={
                    "names": ["滚球"],
                    "shared_objectives": "自选目标",
                    "guidance_points": "自选指导",
                },
                focus={
                    "names": ["轨道车"],
                    "area": "建构区",
                    "objectives": "搭建目标",
                    "guidance": "搭建指导",
                },
            ),
        )
        created = self.owner_client.post(
            "/api/weekly-plans",
            {"term_id": TERM_ID, "week_number": WEEK, "theme": "缺一项"},
        )
        self.assertEqual(created.status_code, 201, created.content)
        plan_id = created.json()["id"]

        detail = created.json()
        c1 = pick_candidate(detail, category="collective", name="跳圈圈")
        fc = pick_candidate(detail, category="free_choice", name="滚球")
        focus = pick_candidate(detail, category="focus", name="轨道车")

        patched = self.owner_client.patch(
            f"/api/weekly-plans/{plan_id}",
            {
                "expected_draft_version": 1,
                "outdoor_game_slots": {
                    "collective_1": ref_payload(c1),
                    "free_choice_1": ref_payload(fc),
                },
                "focus_area": ref_payload(focus),
            },
        )
        self.assertEqual(patched.status_code, 200, patched.content)
        version = patched.json()["draft"]["version"]
        slots = patched.json()["draft"]["content"]["outdoor_game_slots"]
        self.assertIsNotNone(slots["collective_1"])
        self.assertIsNone(slots["collective_2"])
        self.assertIsNotNone(slots["free_choice_1"])

        # Live detail already reports the hole.
        live = self.owner_client.get(f"/api/weekly-plans/{plan_id}").json()
        self.assertIn(
            {"kind": "outdoor_slot", "slot": "collective_2"},
            live["missing"],
        )
        self.assertNotIn(
            {"kind": "outdoor_slot", "slot": "collective_1"},
            live["missing"],
        )
        self.assertNotIn(
            {"kind": "outdoor_slot", "slot": "free_choice_1"},
            live["missing"],
        )

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
        blocked_missing = [
            item for item in blocked.facts["missing"]
            if item["kind"] == "outdoor_slot"
        ]
        self.assertEqual(
            blocked_missing, [{"kind": "outdoor_slot", "slot": "collective_2"}]
        )
        self.assertEqual(self.confirmed_count(plan_id), 0)

        confirmed = self.owner_client.post(
            f"/api/weekly-plans/{plan_id}/confirm",
            {
                "expected_draft_version": version,
                **FULL_ACK,
            },
        )
        self.assertEqual(confirmed.status_code, 201, confirmed.content)
        facts_missing = [
            item
            for item in confirmed.json()["facts"]["missing"]
            if item["kind"] == "outdoor_slot"
        ]
        self.assertEqual(
            facts_missing, [{"kind": "outdoor_slot", "slot": "collective_2"}]
        )

        # Orthogonal dimensions: confirmed, but still incomplete.
        after = self.owner_client.get(f"/api/weekly-plans/{plan_id}").json()
        self.assertEqual(after["confirmation_status"], "draft_current")
        self.assertFalse(after["needs_confirm"])
        self.assertIn(
            {"kind": "outdoor_slot", "slot": "collective_2"},
            after["missing"],
        )
        self.assertTrue(after["missing"])


class V13ImmutableHistoryTests(I4IntegrationTestCase):
    def test_v1_confirmation_never_changes_after_later_writes(self):
        create_daily(
            self.SessionLocal,
            OWNER,
            DAY_MON,
            adopted_content=day_content(talk="话题甲", theme="主题甲"),
        )
        created = self.owner_client.post(
            "/api/weekly-plans",
            {"term_id": TERM_ID, "week_number": WEEK, "theme": "历史主题"},
        )
        self.assertEqual(created.status_code, 201, created.content)
        plan_id = created.json()["id"]

        first = self.owner_client.post(
            f"/api/weekly-plans/{plan_id}/confirm",
            {
                "expected_draft_version": 1,
                "acknowledge_missing": True,
                "acknowledge_stale": False,
                "note": "第一版",
            },
        )
        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(first.json()["version"], 1)

        # Freeze V1 exactly as the history endpoint serves it, then prove
        # later draft writes and the second confirmation never change it.
        v1_initial = self.owner_client.get(
            f"/api/weekly-plans/{plan_id}/confirmations/1"
        )
        self.assertEqual(v1_initial.status_code, 200, v1_initial.content)
        v1_frozen = json.dumps(
            v1_initial.json(), sort_keys=True, ensure_ascii=False
        )
        v1_row_before = self.rows(
            "SELECT id, content, facts, draft_version, confirmed_by, "
            "created_at FROM weekly_plan_confirmed_contents "
            "WHERE weekly_plan_id = :id AND version = 1",
            {"id": plan_id},
        )

        # Draft writes + source changes + refresh between the two confirms.
        self.owner_client.patch(
            f"/api/weekly-plans/{plan_id}",
            {"expected_draft_version": 1, "theme": "第二稿主题"},
        )
        create_daily(
            self.SessionLocal,
            OWNER,
            DAY_TUE,
            adopted_content=day_content(talk="话题乙", theme="主题乙"),
        )
        refreshed = self.owner_client.post(
            f"/api/weekly-plans/{plan_id}/refresh-sources",
            {"expected_draft_version": 2},
        )
        self.assertEqual(refreshed.status_code, 200, refreshed.content)
        self.owner_client.patch(
            f"/api/weekly-plans/{plan_id}",
            {
                "expected_draft_version": refreshed.json()["draft"]["version"],
                "weekly_columns": {"key_week_focus": "第二稿重点"},
            },
        )

        second_version = self.owner_client.get(
            f"/api/weekly-plans/{plan_id}"
        ).json()["draft"]["version"]
        second = self.owner_client.post(
            f"/api/weekly-plans/{plan_id}/confirm",
            {
                "expected_draft_version": second_version,
                "acknowledge_missing": True,
                "acknowledge_stale": True,
                "note": "第二版",
            },
        )
        self.assertEqual(second.status_code, 201, second.content)
        self.assertEqual(second.json()["version"], 2)

        # V1 through the history endpoints is byte-identical.
        history = self.owner_client.get(
            f"/api/weekly-plans/{plan_id}/confirmations"
        ).json()
        self.assertEqual(history["total"], 2)
        self.assertEqual(
            [item["version"] for item in history["items"]], [1, 2]
        )

        read_v1 = self.owner_client.get(
            f"/api/weekly-plans/{plan_id}/confirmations/1"
        )
        self.assertEqual(read_v1.status_code, 200, read_v1.content)
        v1_now = json.dumps(read_v1.json(), sort_keys=True, ensure_ascii=False)
        self.assertEqual(v1_now, v1_frozen)

        read_v2 = self.owner_client.get(
            f"/api/weekly-plans/{plan_id}/confirmations/2"
        )
        self.assertEqual(read_v2.status_code, 200, read_v2.content)
        self.assertNotEqual(
            json.dumps(read_v2.json(), sort_keys=True, ensure_ascii=False),
            v1_frozen,
        )

        v1_row_after = self.rows(
            "SELECT id, content, facts, draft_version, confirmed_by, "
            "created_at FROM weekly_plan_confirmed_contents "
            "WHERE weekly_plan_id = :id AND version = 1",
            {"id": plan_id},
        )
        self.assertEqual(v1_row_before, v1_row_after)
        self.assertEqual(self.confirmed_count(plan_id), 2)

        # The detail points at V2 while V1 remains readable.
        detail = self.owner_client.get(f"/api/weekly-plans/{plan_id}").json()
        self.assertEqual(detail["confirmed"]["version"], 2)


class V14ProjectionContractTests(I4IntegrationTestCase):
    def test_i3_projection_is_consumed_but_never_rewritten(self):
        daily_plan, daily_content, _ = create_daily(
            self.SessionLocal,
            OWNER,
            DAY_MON,
            adopted_content=day_content(
                talk="投影话题",
                theme="投影主题",
                collective={
                    "names": ["跳圈圈"],
                    "shared_objectives": "投影目标",
                    "guidance_points": "投影指导",
                },
            ),
        )

        r0 = self.rows(SYNC_ROW_SQL)
        self.assertEqual(len(r0), 1)
        manifest_before = r0[0][7]
        if isinstance(manifest_before, str):
            manifest_before = json.loads(manifest_before)

        # I3 read-only projection route works before any I4 write.
        sync_route = self.owner_client.get(
            f"/api/weekly-plan-sync-states/{CLASS_ID}/{TERM_ID}/{WEEK}"
        )
        self.assertEqual(sync_route.status_code, 200, sync_route.content)
        self.assertEqual(sync_route.json()["status"], "pending_projection")
        self.assertEqual(
            sync_route.json()["current_week_source_manifest"],
            manifest_before,
        )

        created = self.owner_client.post(
            "/api/weekly-plans",
            {"term_id": TERM_ID, "week_number": WEEK, "theme": "投影消费"},
        )
        self.assertEqual(created.status_code, 201, created.content)
        plan_id = created.json()["id"]
        self.assertFalse(created.json()["projection_pending"])

        r1 = self.rows(SYNC_ROW_SQL)
        self.assertEqual(r0, r1, "I4 create must not write weekly_plan_sync_states")

        # I3 saves a new daily plan content version (cross a real second).
        time.sleep(1.05)
        group = daily_content.adopted_content["morning_games"][0]
        saved = self.owner_client.patch(
            f"/api/daily-plans/{daily_plan.id}",
            {
                "expected_content_version": 1,
                "adopted_content": day_content(
                    talk="投影话题改",
                    theme="投影主题改",
                    collective={
                        "group_id": group["group_id"],
                        "names": [
                            {
                                "name": group["games"][0]["name"],
                                "game_id": group["games"][0]["game_id"],
                            }
                        ],
                        "shared_objectives": group.get("shared_objectives"),
                        "guidance_points": group.get("guidance_points"),
                    },
                ),
            },
        )
        self.assertEqual(saved.status_code, 200, saved.content)
        summary = saved.json()["weekly_sync_state"]
        self.assertEqual(summary["status"], "pending_projection")
        self.assertTrue(summary["has_pending_projection"])
        self.assertEqual(summary["saved_dates"], [DAY_MON.isoformat()])
        self.assertIn(DAY_TUE.isoformat(), summary["missing_dates"])

        r2 = self.rows(SYNC_ROW_SQL)
        self.assertEqual(len(r2), 1)
        self.assertNotEqual(r1[0][12], r2[0][12], "I3 must refresh updated_at")
        self.assertNotEqual(r1[0][7], r2[0][7], "I3 must refresh the manifest")

        # I4 now sees the projection as pending.
        pending = self.owner_client.get(f"/api/weekly-plans/{plan_id}").json()
        self.assertTrue(pending["projection_pending"])
        slot_stale = pending["stale_sources"]
        self.assertTrue(
            any(item["slot"] == "deterministic" for item in slot_stale)
        )

        # Explicit refresh consumes the banner.
        refreshed = self.owner_client.post(
            f"/api/weekly-plans/{plan_id}/refresh-sources",
            {"expected_draft_version": 1},
        )
        self.assertEqual(refreshed.status_code, 200, refreshed.content)
        self.assertFalse(refreshed.json()["projection_pending"])

        r3 = self.rows(SYNC_ROW_SQL)
        self.assertEqual(
            r2, r3, "I4 refresh must not write weekly_plan_sync_states"
        )

        # Confirmation must not touch the row either.
        confirmed = self.owner_client.post(
            f"/api/weekly-plans/{plan_id}/confirm",
            {
                "expected_draft_version": refreshed.json()["draft"]["version"],
                **FULL_ACK,
            },
        )
        self.assertEqual(confirmed.status_code, 201, confirmed.content)
        r4 = self.rows(SYNC_ROW_SQL)
        self.assertEqual(r3, r4, "I4 confirm must not write weekly_plan_sync_states")

        # The row still exists and both I3 read surfaces behave normally.
        self.assertEqual(len(r4), 1)
        sync_route_after = self.owner_client.get(
            f"/api/weekly-plan-sync-states/{CLASS_ID}/{TERM_ID}/{WEEK}"
        )
        self.assertEqual(sync_route_after.status_code, 200)
        self.assertEqual(sync_route_after.json()["status"], "pending_projection")
        self.assertEqual(
            sync_route_after.json()["current_week_source_manifest"][0][
                "current_content_version"
            ],
            2,
        )

        daily_route = self.owner_client.get(
            f"/api/daily-plans/{daily_plan.id}"
        )
        self.assertEqual(daily_route.status_code, 200, daily_route.content)
        daily_summary = daily_route.json()["weekly_sync_state"]
        self.assertEqual(daily_summary["status"], "pending_projection")
        self.assertTrue(daily_summary["has_pending_projection"])
        self.assertEqual(
            daily_summary["saved_dates"], [DAY_MON.isoformat()]
        )

        # A later I3 save re-opens the banner while the confirmed version
        # stays exactly where it was.
        time.sleep(1.05)
        self.owner_client.patch(
            f"/api/daily-plans/{daily_plan.id}",
            {
                "expected_content_version": 2,
                "adopted_content": day_content(
                    talk="投影话题三", theme="投影主题三"
                ),
            },
        )
        r5 = self.rows(SYNC_ROW_SQL)
        self.assertNotEqual(r4[0][12], r5[0][12])
        again = self.owner_client.get(f"/api/weekly-plans/{plan_id}").json()
        self.assertTrue(again["projection_pending"])
        self.assertEqual(again["confirmed"]["version"], 1)
