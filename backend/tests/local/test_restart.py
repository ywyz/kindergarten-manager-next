"""Real process restart: identity, calendar, history and pointer survive."""

from __future__ import annotations

import json
import unittest

from tests.local.support import (
    LocalTestCase,
    StaticCalendarProvider,
    calendar_provider,
    initialize_body,
    query_rows,
)


class RestartTests(LocalTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(calendar_provider(StaticCalendarProvider()))

    def test_process_restart_keeps_identity_calendar_and_history(self):
        # Every worker here is a *true* restart: no parent runtime owns the
        # root, each worker fully prepares (migrates, takes the lock) and then
        # disposes before the next one starts (connect_only=False).
        # Phase 1: a separate process initializes and writes versions.
        spec_init = self.worker_spec("initialize", connect_only=False)
        spec_init["input"] = initialize_body()
        init = self.run_worker(spec_init)
        self.assertTrue(init["created"])
        profile_id = init["payload"]["profile"]["id"]
        # D1B: term/revision identities come from the full term list; the
        # default as-of date resolves against the host local date.
        term_view = init["payload"]["terms"][0]
        revision_id = term_view["current_calendar_revision_id"]
        class_id = init["payload"]["class"]["id"]
        term_id = term_view["id"]
        self.assertNotEqual(profile_id, self.token)

        spec_create = self.worker_spec("create_plan", connect_only=False)
        spec_create.update({"plan_date": "2026-09-01", "raw": "原始教案"})
        created = self.run_worker(spec_create)
        self.assertTrue(created["created"])
        plan_id = created["payload"]["id"]
        self.assertEqual(created["payload"]["current_content_version"], 1)

        spec_save1 = self.worker_spec("save_plan", connect_only=False)
        spec_save1.update({"plan_id": plan_id, "expected": 1, "raw": "第二版"})
        saved1 = self.run_worker(spec_save1)
        self.assertEqual(saved1["payload"]["current_content_version"], 2)

        spec_save2 = self.worker_spec("save_plan", connect_only=False)
        spec_save2.update(
            {
                "plan_id": plan_id,
                "expected": 2,
                "adopted": {"reflection": "第三版反思"},
            }
        )
        saved2 = self.run_worker(spec_save2)
        self.assertEqual(saved2["payload"]["current_content_version"], 3)

        # Phase 2: a new process reads everything back unchanged.
        spec_context = self.worker_spec("read_context", connect_only=False)
        spec_context["as_of_date"] = "2026-09-15"
        context = self.run_worker(spec_context)["payload"]
        self.assertEqual(context["status"], "ready")
        self.assertEqual(context["profile"]["id"], profile_id)
        self.assertEqual(context["calendar_revision"]["id"], revision_id)
        self.assertEqual(context["class"]["id"], class_id)
        self.assertEqual(context["term"]["id"], term_id)

        spec_counts = self.worker_spec("counts", connect_only=False)
        spec_counts["plan_id"] = plan_id
        counts = self.run_worker(spec_counts)
        self.assertEqual(
            counts,
            {
                "profile": 1,
                "plans": 1,
                "contents": 3,
                "audit": 4,  # init + create + two saves
                "current_version": 3,
            },
        )

        db = self.data_dir / "kindergarten.db"
        contents = query_rows(
            db,
            "SELECT id, version, raw_lesson_plan, adopted_content "
            "FROM local_daily_plan_contents WHERE daily_plan_id = ? "
            "ORDER BY version",
            (plan_id,),
        )
        self.assertEqual([row["version"] for row in contents], [1, 2, 3])
        self.assertEqual(contents[0]["raw_lesson_plan"], "原始教案")
        self.assertEqual(contents[1]["raw_lesson_plan"], "第二版")
        self.assertEqual(
            json.loads(contents[2]["adopted_content"])["reflection"],
            "第三版反思",
        )

        header = query_rows(
            db,
            "SELECT current_content_id, current_content_version, plan_date, "
            "week_number, weekday, calendar_revision_id FROM local_daily_plans",
        )[0]
        self.assertEqual(header["current_content_version"], 3)
        self.assertEqual(header["current_content_id"], contents[2]["id"])
        self.assertEqual(header["plan_date"], "2026-09-01")
        self.assertEqual(header["week_number"], 1)
        self.assertEqual(header["weekday"], 2)
        self.assertEqual(header["calendar_revision_id"], revision_id)

        day_count = query_rows(
            db, "SELECT count(*) AS n FROM local_calendar_days"
        )[0]["n"]
        self.assertEqual(day_count, 30)

        # Phase 3: a third process can save again on the same history.
        spec_save3 = self.worker_spec("save_plan", connect_only=False)
        spec_save3.update({"plan_id": plan_id, "expected": 3, "raw": "第四版"})
        saved3 = self.run_worker(spec_save3)
        self.assertEqual(saved3["payload"]["current_content_version"], 4)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
