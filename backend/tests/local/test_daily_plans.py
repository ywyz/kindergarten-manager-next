"""Daily plan API: content rules, versioning, shapes and read endpoints."""

from __future__ import annotations

import json
import logging
import unittest
from datetime import datetime

from tests.local.support import (
    LocalTestCase,
    StaticCalendarProvider,
    calendar_provider,
    capture_server_logs,
    execute_sql,
    query_rows,
    query_scalar,
)

CORRUPT_STORED_VALUES = (
    "not-json",
    '{"bogus": "stored-invalid-content"}',
    "[1, 2]",
    '{"morning_games": [{"group_kind": "collective", "games": []}]}',
    '{"morning_games": ['
    '{"group_kind": "collective", "group_id": "dup-group", '
    '"games": [{"name": "a", "game_id": "dup-game"}]}, '
    '{"group_kind": "free_choice", "group_id": "dup-group", "games": []}]}',
)

ADOPTED_FULL = {
    "morning_exercise_label": "早操活动",
    "morning_games": [
        {
            "group_kind": "collective",
            "games": [{"name": "切西瓜"}],
            "focus_guidance": "关注合作",
            "shared_objectives": "目标",
            "guidance_points": "要点",
        },
        {
            "group_kind": "free_choice",
            "games": [{"name": "积木搭建"}],
        },
    ],
    "morning_talk": {"topic": "周末见闻", "questions": "你去了哪里？"},
    "group_activity": {
        "theme": "秋天的树",
        "objectives": "观察树叶",
        "preparation": "树叶",
        "key_points": "重点",
        "difficult_points": "难点",
        "process": "一、导入\n二、观察",
    },
    "post_group_games": [
        {"context_kind": "area", "area": "美工区", "games": [{"name": "树叶贴画"}]},
        {"context_kind": "outdoor", "games": [{"name": "接力跑"}]},
        {"context_kind": "special_room", "area": "阅览室", "games": [{"name": "看图书"}]},
    ],
    "afternoon_outdoor": {
        "area": "操场",
        "games": [{"name": "滑梯"}],
        "observation_focus": "运动安全",
    },
    "reflection": "今天的活动很顺利",
}

DETAIL_KEYS = {
    "id",
    "class_id",
    "term_id",
    "plan_date",
    "week_number",
    "weekday",
    "calendar_revision_id",
    "creator_id",
    "creator_display_name",
    "current_content_id",
    "current_content_version",
    "content",
    "school_name",
    "class_name",
    "grade",
    "created_at",
    "updated_at",
}

CONTENT_KEYS = {
    "id",
    "version",
    "raw_lesson_plan",
    "split_baseline",
    "adopted_content",
    "editor_id",
    "created_at",
}


class DailyPlanApiTests(LocalTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.provider = StaticCalendarProvider()
        self.enterContext(calendar_provider(self.provider))
        self.server = self.start_server()
        self.client = self.server.client()
        self.context = self.initialize(self.client)
        self.db = self.server.runtime.db_path

    def create(self, plan_date: str = "2026-09-01", body: dict | None = None):
        payload = {"plan_date": plan_date}
        if body:
            payload.update(body)
        status, result = self.client.post("/api/daily-plans", payload)
        return status, result

    # -- create / open ----------------------------------------------------
    def test_create_empty_content_and_open_existing(self):
        status, plan = self.create()
        self.assertEqual(status, 201, plan)
        self.assertEqual(plan["current_content_version"], 1)
        self.assertIsNone(plan["content"]["raw_lesson_plan"])
        self.assertEqual(plan["content"]["adopted_content"], {})
        self.assertIsNone(plan["content"]["split_baseline"])
        self.assertEqual(plan["content"]["version"], 1)
        self.assertEqual(plan["plan_date"], "2026-09-01")
        self.assertEqual(plan["week_number"], 1)
        self.assertEqual(plan["weekday"], 2)

        counts_before = self.counts(self.db)
        status, opened = self.create()
        self.assertEqual(status, 200, opened)
        self.assertEqual(opened["id"], plan["id"])
        self.assertEqual(opened, plan)
        self.assertEqual(self.counts(self.db), counts_before)

        audit = query_rows(
            self.db,
            "SELECT action, target_id, target_version_after "
            "FROM local_operation_records WHERE target_type = 'daily_plan'",
        )
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["action"], "create_daily_plan")
        self.assertEqual(audit[0]["target_id"], plan["id"])
        self.assertEqual(audit[0]["target_version_after"], 1)

    def test_create_with_all_real_sections_and_stable_ids(self):
        status, plan = self.create(body={"raw_lesson_plan": "完整教案原文\n第二行",
                                         "adopted_content": ADOPTED_FULL})
        self.assertEqual(status, 201, plan)
        content = plan["content"]["adopted_content"]
        self.assertEqual(content["reflection"], "今天的活动很顺利")
        collective = content["morning_games"][0]
        self.assertTrue(collective["group_id"])
        self.assertTrue(collective["games"][0]["game_id"])
        self.assertTrue(content["post_group_games"][1]["group_id"])
        self.assertTrue(content["afternoon_outdoor"]["group_id"])
        self.assertEqual(content["afternoon_outdoor"]["observation_focus"], "运动安全")

        first_ids = {
            "group": collective["group_id"],
            "game": collective["games"][0]["game_id"],
            "outdoor_group": content["post_group_games"][1]["group_id"],
        }

        # Save keeps existing IDs (client submits the server-normalized
        # content) and assigns IDs to new objects only.
        updated = dict(plan["content"]["adopted_content"])
        morning = [dict(updated["morning_games"][0])]
        morning[0]["games"] = [dict(morning[0]["games"][0]), {"name": "新游戏"}]
        updated["morning_games"] = morning + [updated["morning_games"][1]]
        updated["reflection"] = "更新后的反思"
        status, saved = self.client.patch(
            f"/api/daily-plans/{plan['id']}",
            {"expected_content_version": 1, "adopted_content": updated},
        )
        self.assertEqual(status, 200, saved)
        saved_content = saved["content"]["adopted_content"]
        self.assertEqual(saved_content["morning_games"][0]["group_id"], first_ids["group"])
        self.assertEqual(
            saved_content["morning_games"][0]["games"][0]["game_id"],
            first_ids["game"],
        )
        new_game_id = saved_content["morning_games"][0]["games"][1]["game_id"]
        self.assertTrue(new_game_id)
        self.assertNotEqual(new_game_id, first_ids["game"])
        self.assertEqual(
            saved_content["post_group_games"][1]["group_id"], first_ids["outdoor_group"]
        )

    # -- identity rules ---------------------------------------------------
    def test_unknown_duplicate_and_cross_plan_ids_rejected(self):
        _, plan = self.create(body={"adopted_content": ADOPTED_FULL})
        group_id = plan["content"]["adopted_content"]["morning_games"][0]["group_id"]
        game_id = plan["content"]["adopted_content"]["morning_games"][0]["games"][0]["game_id"]

        _, other = self.create("2026-09-02", {"adopted_content": ADOPTED_FULL})
        other_group = other["content"]["adopted_content"]["morning_games"][0]["group_id"]

        cases = [
            {"adopted_content": {"morning_games": [{"group_kind": "collective", "group_id": "zzzzzzzzzzzzzzzzzzzzzz", "games": []}]}},
            {"adopted_content": {"morning_games": [{"group_kind": "collective", "games": [{"game_id": "yyyyyyyyyyyyyyyyyyyyyy", "name": "x"}]}]}},
            {"adopted_content": {"morning_games": [{"group_kind": "collective", "group_id": other_group, "games": []}]}},
            {"adopted_content": {"morning_games": [
                {"group_kind": "collective", "group_id": group_id, "games": [{"game_id": game_id, "name": "a"}]},
                {"group_kind": "free_choice", "group_id": group_id, "games": []},
            ]}},
            {"adopted_content": {"morning_games": [{"group_kind": "collective", "games": [
                {"game_id": game_id, "name": "a"}, {"game_id": game_id, "name": "b"}]}]}},
        ]
        for body in cases:
            with self.subTest(body=body):
                payload = {"expected_content_version": 1}
                payload.update(body)
                status, result = self.client.patch(
                    f"/api/daily-plans/{plan['id']}", payload
                )
                self.assertEqual(status, 422, result)
                self.assertEqual(result["error"]["code"], "VALIDATION_ERROR")

        # Nothing was appended by any rejected save.
        version = query_scalar(
            self.db,
            "SELECT current_content_version FROM local_daily_plans WHERE id = ?",
            (plan["id"],),
        )
        self.assertEqual(version, 1)

    def test_split_baseline_is_rejected_everywhere(self):
        status, result = self.create(body={"split_baseline": {"x": 1}})
        self.assertEqual(status, 422, result)
        self.assertEqual(result["error"]["code"], "VALIDATION_ERROR")
        _, plan = self.create()
        status, result = self.client.patch(
            f"/api/daily-plans/{plan['id']}",
            {"expected_content_version": 1, "split_baseline": None},
        )
        self.assertEqual(status, 422, result)
        self.assertEqual(result["error"]["code"], "VALIDATION_ERROR")

    # -- save semantics ---------------------------------------------------
    def test_omitted_fields_inherit_and_explicit_null_clears(self):
        _, plan = self.create(
            body={"raw_lesson_plan": "原始教案", "adopted_content": {"reflection": "一"}}
        )
        status, saved = self.client.patch(
            f"/api/daily-plans/{plan['id']}", {"expected_content_version": 1}
        )
        self.assertEqual(status, 200, saved)
        self.assertEqual(saved["current_content_version"], 2)
        self.assertEqual(saved["content"]["raw_lesson_plan"], "原始教案")
        self.assertEqual(
            saved["content"]["adopted_content"], {"reflection": "一"}
        )

        status, cleared = self.client.patch(
            f"/api/daily-plans/{plan['id']}",
            {"expected_content_version": 2, "raw_lesson_plan": None},
        )
        self.assertEqual(status, 200, cleared)
        self.assertIsNone(cleared["content"]["raw_lesson_plan"])
        self.assertEqual(cleared["content"]["adopted_content"], {"reflection": "一"})

        status, result = self.client.patch(
            f"/api/daily-plans/{plan['id']}",
            {"expected_content_version": 3, "adopted_content": None},
        )
        self.assertEqual(status, 422, result)
        self.assertEqual(result["error"]["code"], "VALIDATION_ERROR")

        # History is append-only: one row per version, all preserved.
        rows = query_rows(
            self.db,
            "SELECT version, raw_lesson_plan FROM local_daily_plan_contents "
            "WHERE daily_plan_id = ? ORDER BY version",
            (plan["id"],),
        )
        self.assertEqual([row["version"] for row in rows], [1, 2, 3])
        self.assertEqual(rows[0]["raw_lesson_plan"], "原始教案")
        self.assertIsNone(rows[2]["raw_lesson_plan"])

    def test_expected_version_is_a_strict_integer(self):
        _, plan = self.create()
        for bad in (True, 1.5, "1", 0, -1, None):
            with self.subTest(bad=bad):
                status, result = self.client.patch(
                    f"/api/daily-plans/{plan['id']}",
                    {"expected_content_version": bad},
                )
                self.assertEqual(status, 422, (bad, result))
                self.assertEqual(result["error"]["code"], "VALIDATION_ERROR")

    def test_stale_save_conflicts_without_extra_history(self):
        _, plan = self.create()
        status, saved = self.client.patch(
            f"/api/daily-plans/{plan['id']}",
            {"expected_content_version": 1, "raw_lesson_plan": "v2"},
        )
        self.assertEqual(status, 200)

        counts = {
            "contents": query_scalar(
                self.db, "SELECT count(*) AS n FROM local_daily_plan_contents"
            ),
            "audit": query_scalar(
                self.db, "SELECT count(*) AS n FROM local_operation_records"
            ),
        }
        status, conflict = self.client.patch(
            f"/api/daily-plans/{plan['id']}",
            {"expected_content_version": 1, "raw_lesson_plan": "v2-late"},
        )
        self.assertEqual(status, 409, conflict)
        self.assertEqual(conflict["error"]["code"], "VERSION_CONFLICT")
        self.assertEqual(
            query_scalar(
                self.db, "SELECT count(*) AS n FROM local_daily_plan_contents"
            ),
            counts["contents"],
        )
        self.assertEqual(
            query_scalar(
                self.db, "SELECT count(*) AS n FROM local_operation_records"
            ),
            counts["audit"],
        )
        self.assertEqual(
            query_scalar(
                self.db,
                "SELECT current_content_version FROM local_daily_plans WHERE id = ?",
                (plan["id"],),
            ),
            2,
        )

    # -- persisted content corruption -------------------------------------
    def _plan_state(self, plan: dict) -> dict:
        return {
            "version": query_scalar(
                self.db,
                "SELECT current_content_version FROM local_daily_plans WHERE id = ?",
                (plan["id"],),
            ),
            "pointer": query_scalar(
                self.db,
                "SELECT current_content_id FROM local_daily_plans WHERE id = ?",
                (plan["id"],),
            ),
            "contents": query_scalar(
                self.db, "SELECT count(*) AS n FROM local_daily_plan_contents"
            ),
            "audit": query_scalar(
                self.db, "SELECT count(*) AS n FROM local_operation_records"
            ),
        }

    def _corrupt_current_content(self, plan: dict, raw: str) -> None:
        execute_sql(
            self.db,
            "UPDATE local_daily_plan_contents SET adopted_content = ? "
            "WHERE id = ?",
            (raw, plan["current_content_id"]),
        )

    def test_persisted_content_corruption_answers_storage_error_on_reads(self):
        _, plan = self.create(body={"raw_lesson_plan": "r1"})
        for corrupt in CORRUPT_STORED_VALUES:
            with self.subTest(corrupt=corrupt):
                self._corrupt_current_content(plan, corrupt)
                status, body = self.client.get(f"/api/daily-plans/{plan['id']}")
                self.assertEqual(status, 503, body)
                self.assertEqual(body["error"]["code"], "LOCAL_STORAGE_ERROR")
                status, body = self.client.get(
                    "/api/daily-plans/by-date?date=2026-09-01"
                )
                self.assertEqual(status, 503, body)
                self.assertEqual(body["error"]["code"], "LOCAL_STORAGE_ERROR")
                # Re-create on the same date opens the existing record and
                # must not treat the damaged stored value as valid content.
                status, body = self.client.post(
                    "/api/daily-plans", {"plan_date": "2026-09-01"}
                )
                self.assertEqual(status, 503, body)
                self.assertEqual(body["error"]["code"], "LOCAL_STORAGE_ERROR")
                # List reads do not load content and keep working from the
                # header rows only.
                status, listed = self.client.get(
                    "/api/daily-plans?from=2026-09-01&to=2026-09-30"
                )
                self.assertEqual(status, 200, listed)
                self.assertEqual(listed["total"], 1)

    def test_persisted_content_corruption_blocks_saves_without_side_effects(self):
        _, plan = self.create(
            body={"raw_lesson_plan": "original", "adopted_content": {"reflection": "ok"}}
        )
        marker = "stored-invalid-content"
        self._corrupt_current_content(plan, '{"bogus": "' + marker + '"}')
        before = self._plan_state(plan)
        for body in (
            {"expected_content_version": 1},
            {"expected_content_version": 1, "raw_lesson_plan": "changed"},
            {"expected_content_version": 1, "adopted_content": {"reflection": "new"}},
        ):
            with self.subTest(body=body):
                status, result = self.client.patch(
                    f"/api/daily-plans/{plan['id']}", body
                )
                self.assertEqual(status, 503, result)
                self.assertEqual(result["error"]["code"], "LOCAL_STORAGE_ERROR")
                response_text = json.dumps(result, ensure_ascii=False)
                self.assertNotIn(marker, response_text)
                self.assertNotIn(str(self.db), response_text)
                self.assertEqual(self._plan_state(plan), before)

        # Client-supplied invalid structure is still its own 422 path.
        status, result = self.client.patch(
            f"/api/daily-plans/{plan['id']}",
            {"expected_content_version": 1, "adopted_content": {"bogus": "x"}},
        )
        self.assertEqual(status, 422, result)
        self.assertEqual(result["error"]["code"], "VALIDATION_ERROR")

    def test_persisted_split_baseline_corruption_is_storage_error_matrix(self):
        """Any persisted non-null baseline is corruption, never copied (R4).

        Legal JSON array/string/object baselines all failed only at the
        response model before; the shared read boundary must refuse them as
        ``LOCAL_STORAGE_ERROR`` before a detail is returned or a new version
        is appended, with every failure leaving version, pointer, content
        history and audit untouched. Server logs must not leak the synthetic
        content, paths or session material either.
        """
        logs = capture_server_logs()
        self.addCleanup(logs.close)
        corrupted = {
            "2026-09-01": (
                "not-json synthetic-baseline-marker",
                "synthetic-baseline-marker",
            ),
            "2026-09-02": (
                '["synthetic-baseline-array-marker"]',
                "synthetic-baseline-array-marker",
            ),
            "2026-09-03": (
                '"synthetic-baseline-string-marker"',
                "synthetic-baseline-string-marker",
            ),
            "2026-09-04": (
                '{"bogus": "synthetic-baseline-object-marker"}',
                "synthetic-baseline-object-marker",
            ),
        }
        for plan_date, (stored, marker) in corrupted.items():
            with self.subTest(value=marker):
                _, plan = self.create(plan_date=plan_date)
                self.assertIsNone(plan["content"]["split_baseline"])
                execute_sql(
                    self.db,
                    "UPDATE local_daily_plan_contents SET split_baseline = ? "
                    "WHERE id = ?",
                    (stored, plan["current_content_id"]),
                )
                before = self._plan_state(plan)
                requests = (
                    ("GET", f"/api/daily-plans/{plan['id']}", None),
                    (
                        "GET",
                        f"/api/daily-plans/by-date?date={plan_date}",
                        None,
                    ),
                    ("POST", "/api/daily-plans", {"plan_date": plan_date}),
                    (
                        "PATCH",
                        f"/api/daily-plans/{plan['id']}",
                        {"expected_content_version": 1},
                    ),
                    (
                        "PATCH",
                        f"/api/daily-plans/{plan['id']}",
                        {
                            "expected_content_version": 1,
                            "raw_lesson_plan": "只改原文",
                        },
                    ),
                    (
                        "PATCH",
                        f"/api/daily-plans/{plan['id']}",
                        {
                            "expected_content_version": 1,
                            "adopted_content": {"reflection": "合法新内容"},
                        },
                    ),
                )
                for method, path, body in requests:
                    status, result = self.client.request(method, path, body)
                    self.assertEqual(status, 503, (method, path, result))
                    self.assertEqual(
                        result["error"]["code"], "LOCAL_STORAGE_ERROR"
                    )
                    response_text = json.dumps(result, ensure_ascii=False)
                    self.assertNotIn(marker, response_text)
                    self.assertNotIn(str(self.db), response_text)
                    self.assertNotIn(self.token, response_text)
                    # Failure must never append a version, move the pointer,
                    # grow the history or add audit records.
                    self.assertEqual(self._plan_state(plan), before)

                # Client-supplied invalid structure is still its own 422
                # path even while the stored baseline is corrupt.
                status, result = self.client.patch(
                    f"/api/daily-plans/{plan['id']}",
                    {
                        "expected_content_version": 1,
                        "adopted_content": {"bogus": "x"},
                    },
                )
                self.assertEqual(status, 422, result)
                self.assertEqual(result["error"]["code"], "VALIDATION_ERROR")
                self.assertEqual(self._plan_state(plan), before)

        # Sanity-check the capture itself: a direct record must be collected
        # so the absences below are meaningful.
        logging.getLogger("uvicorn.error").warning("log-capture-sanity")
        captured_logs = logs.text()
        self.assertIn("log-capture-sanity", captured_logs)
        for _, marker in corrupted.values():
            self.assertNotIn(marker, captured_logs)
        self.assertNotIn(str(self.db), captured_logs)
        self.assertNotIn(self.token, captured_logs)
        self.assertNotIn("ResponseValidationError", captured_logs)

    def test_null_split_baseline_still_reads_and_saves(self):
        """A healthy plan keeps the legal null baseline around corruption."""
        _, corrupt_plan = self.create(
            plan_date="2026-09-01", body={"raw_lesson_plan": "r1"}
        )
        execute_sql(
            self.db,
            "UPDATE local_daily_plan_contents SET split_baseline = ? "
            "WHERE id = ?",
            (
                '["synthetic-baseline-array-marker"]',
                corrupt_plan["current_content_id"],
            ),
        )

        status, plan = self.create(
            plan_date="2026-09-02", body={"raw_lesson_plan": "r2"}
        )
        self.assertEqual(status, 201, plan)
        self.assertIsNone(plan["content"]["split_baseline"])
        status, detail = self.client.get(f"/api/daily-plans/{plan['id']}")
        self.assertEqual(status, 200, detail)
        self.assertIsNone(detail["content"]["split_baseline"])

        status, saved = self.client.patch(
            f"/api/daily-plans/{plan['id']}",
            {"expected_content_version": 1, "raw_lesson_plan": "r2-v2"},
        )
        self.assertEqual(status, 200, saved)
        self.assertEqual(saved["current_content_version"], 2)
        self.assertIsNone(saved["content"]["split_baseline"])

        # The corrupt neighbour still answers 503 and was not repaired by
        # the healthy plan's traffic.
        status, result = self.client.get(
            f"/api/daily-plans/{corrupt_plan['id']}"
        )
        self.assertEqual(status, 503, result)
        self.assertEqual(result["error"]["code"], "LOCAL_STORAGE_ERROR")

    # -- shape / immutability --------------------------------------------
    def test_detail_shape_and_header_snapshot_immutable(self):
        _, plan = self.create()
        self.assertEqual(set(plan), DETAIL_KEYS)
        self.assertEqual(set(plan["content"]), CONTENT_KEYS)
        self.assertNotIn("weekly_sync_state", plan)
        datetime.fromisoformat(plan["created_at"])
        datetime.fromisoformat(plan["content"]["created_at"])

        header = {
            key: plan[key]
            for key in (
                "id",
                "class_id",
                "term_id",
                "plan_date",
                "week_number",
                "weekday",
                "calendar_revision_id",
                "creator_id",
                "creator_display_name",
                "school_name",
                "class_name",
                "grade",
                "created_at",
            )
        }
        status, saved = self.client.patch(
            f"/api/daily-plans/{plan['id']}",
            {"expected_content_version": 1, "raw_lesson_plan": "改", "adopted_content": {"reflection": "改"}},
        )
        self.assertEqual(status, 200)
        for key, value in header.items():
            self.assertEqual(saved[key], value, key)
        self.assertEqual(saved["calendar_revision_id"], plan["calendar_revision_id"])

        # The stored header row itself still matches the creation snapshot.
        row = query_rows(
            self.db,
            "SELECT class_name, grade, school_name, creator_display_name, plan_date, "
            "week_number, weekday, calendar_revision_id, current_content_version "
            "FROM local_daily_plans WHERE id = ?",
            (plan["id"],),
        )[0]
        self.assertEqual(row["class_name"], "中一班")
        self.assertEqual(row["grade"], "middle")
        self.assertEqual(row["school_name"], "示范幼儿园")
        self.assertEqual(row["creator_display_name"], "王老师")
        self.assertEqual(row["plan_date"], "2026-09-01")
        self.assertEqual(row["week_number"], 1)
        self.assertEqual(row["weekday"], 2)
        self.assertEqual(row["current_content_version"], 2)

    def test_raw_lesson_plan_preserved_exactly(self):
        raw = "第一行  \n第二行 含全角空格　\n\n第四行"
        _, plan = self.create(body={"raw_lesson_plan": raw})
        self.assertEqual(plan["content"]["raw_lesson_plan"], raw)
        status, fetched = self.client.get(f"/api/daily-plans/{plan['id']}")
        self.assertEqual(fetched["content"]["raw_lesson_plan"], raw)

    # -- reads ------------------------------------------------------------
    def test_list_shape_range_and_pagination(self):
        self.create("2026-09-01")
        self.create("2026-09-02")
        status, listed = self.client.get(
            "/api/daily-plans?from=2026-08-31&to=2026-09-03"
        )
        self.assertEqual(status, 200, listed)
        self.assertEqual(set(listed), {"items", "total", "offset", "limit"})
        self.assertEqual(listed["total"], 2)
        self.assertEqual(
            [item["plan_date"] for item in listed["items"]],
            ["2026-09-01", "2026-09-02"],
        )
        self.assertEqual(listed["limit"], 100)
        item_keys = {
            "id",
            "plan_date",
            "week_number",
            "weekday",
            "creator_id",
            "creator_display_name",
            "current_content_version",
            "created_at",
            "updated_at",
        }
        self.assertEqual(set(listed["items"][0]), item_keys)

        status, limited = self.client.get(
            "/api/daily-plans?from=2026-09-01&to=2026-09-30&offset=1&limit=1"
        )
        self.assertEqual(status, 200)
        self.assertEqual(limited["total"], 2)
        self.assertEqual([i["plan_date"] for i in limited["items"]], ["2026-09-02"])

        for query in (
            "from=2026-09-01&to=2026-09-30&limit=200",
        ):
            status, _ = self.client.get(f"/api/daily-plans?{query}")
            self.assertEqual(status, 200, query)
        for query in (
            "from=2026-09-01&to=2026-09-30&limit=201",
            "from=2026-09-01&to=2026-09-30&limit=0",
            "from=2026-09-01&to=2026-09-30&offset=-1",
            "from=2026-09-05&to=2026-09-01",
            "from=2026-09-01",
            "to=2026-09-30",
            "from=2026-09-01&to=2026-09-30&class_id=zzz",
        ):
            with self.subTest(query=query):
                status, result = self.client.get(f"/api/daily-plans?{query}")
                self.assertEqual(status, 422, (query, result))
                self.assertEqual(result["error"]["code"], "VALIDATION_ERROR")

    def test_by_date_get_by_id_and_soft_deleted(self):
        _, plan = self.create("2026-09-03")
        status, by_date = self.client.get("/api/daily-plans/by-date?date=2026-09-03")
        self.assertEqual(status, 200)
        self.assertEqual(by_date["id"], plan["id"])

        status, missing = self.client.get("/api/daily-plans/by-date?date=2026-09-04")
        self.assertEqual(status, 404, missing)
        self.assertEqual(missing["error"]["code"], "DAILY_PLAN_NOT_FOUND")
        status, missing = self.client.get("/api/daily-plans/no-such-plan-id")
        self.assertEqual(status, 404)
        self.assertEqual(missing["error"]["code"], "DAILY_PLAN_NOT_FOUND")

        # Soft-deleted rows behave as not found (no delete API in D1A).
        execute_sql(
            self.db,
            "UPDATE local_daily_plans SET deleted_at = '2026-10-01 00:00:00' WHERE id = ?",
            (plan["id"],),
        )
        status, gone = self.client.get(f"/api/daily-plans/{plan['id']}")
        self.assertEqual(status, 404, gone)
        self.assertEqual(gone["error"]["code"], "DAILY_PLAN_NOT_FOUND")
        status, gone = self.client.get("/api/daily-plans/by-date?date=2026-09-03")
        self.assertEqual(status, 404)
        status, listed = self.client.get(
            "/api/daily-plans?from=2026-09-01&to=2026-09-30"
        )
        self.assertEqual(listed["total"], 0)

        # The date becomes creatable again as a fresh plan.
        status, recreated = self.create("2026-09-03")
        self.assertEqual(status, 201, recreated)
        self.assertNotEqual(recreated["id"], plan["id"])

    def test_no_weekly_projection_tables_or_fields(self):
        names = [
            row["name"]
            for row in query_rows(
                self.db, "SELECT name FROM sqlite_master WHERE type='table'"
            )
        ]
        self.assertFalse([name for name in names if "weekly" in name.lower()], names)
        status, plan = self.create()
        self.assertEqual(status, 201)
        self.assertNotIn("weekly_sync_state", plan)
        status, saved = self.client.patch(
            f"/api/daily-plans/{plan['id']}", {"expected_content_version": 1}
        )
        self.assertEqual(status, 200)
        self.assertNotIn("weekly_sync_state", saved)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
