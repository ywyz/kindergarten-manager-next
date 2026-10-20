"""Atomic local initialization, retry semantics and calendar-library faults."""

from __future__ import annotations

import unittest
from datetime import date

from app.local.migrate import ensure_local_schema
from app.services import calendar_service as cal
from tests.local.support import (
    LocalTestCase,
    StaticCalendarProvider,
    calendar_provider,
    execute_sql,
    initialize_body,
    query_rows,
    query_scalar,
)

ZERO_COUNTS = {
    "local_profile": 0,
    "local_settings": 0,
    "local_classes": 0,
    "local_terms": 0,
    "local_calendar_revisions": 0,
    "local_calendar_days": 0,
    "local_daily_plans": 0,
    "local_daily_plan_contents": 0,
    "local_operation_records": 0,
}


class InitializeTests(LocalTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.provider = StaticCalendarProvider()
        self.enterContext(calendar_provider(self.provider))

    # -- happy path -------------------------------------------------------
    def test_uninitialized_then_ready_context(self):
        server = self.start_server()
        client = server.client()
        status, payload = client.get("/api/local/context")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "uninitialized")
        self.assertIsNone(payload["profile"])

        status, payload = client.post("/api/local/initialize", initialize_body())
        self.assertEqual(status, 201, payload)
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["profile"]["display_name"], "王老师")
        self.assertEqual(len(payload["profile"]["id"]), 22)
        self.assertEqual(payload["school_name"], "示范幼儿园")
        self.assertEqual(payload["class"]["name"], "中一班")
        self.assertEqual(payload["class"]["grade"], "middle")
        # D1B context increments: global configuration version + full terms.
        self.assertEqual(payload["config_version"], 1)
        self.assertEqual(payload["as_of_date"], date.today().isoformat())
        self.assertEqual(len(payload["terms"]), 1)
        term_view = payload["terms"][0]
        self.assertEqual(term_view["name"], "2026 年秋季学期")
        self.assertEqual(term_view["start_date"], "2026-09-01")
        self.assertEqual(term_view["end_date"], "2026-09-30")

        # as_of interpretation: an explicit in-term date resolves the term
        # and its persisted revision (the default date uses today).
        status, view = client.get("/api/local/context?date=2026-09-15")
        self.assertEqual(status, 200, view)
        self.assertEqual(view["term"]["id"], term_view["id"])
        self.assertEqual(view["term"]["name"], "2026 年秋季学期")
        self.assertEqual(view["calendar_revision"]["revision_no"], 1)
        self.assertEqual(
            view["calendar_revision"]["library_version"],
            self.provider.version,
        )
        self.assertEqual(
            view["calendar_revision"]["id"],
            term_view["current_calendar_revision_id"],
        )

        status, again = client.get("/api/local/context")
        self.assertEqual(status, 200)
        self.assertEqual(again, payload)

    def test_initialize_creates_complete_profile_atomically(self):
        server = self.start_server()
        client = server.client()
        self.initialize(client)
        db = server.runtime.db_path

        counts = self.counts(db)
        expected = dict(ZERO_COUNTS)
        expected.update(
            {
                "local_profile": 1,
                "local_settings": 1,
                "local_classes": 1,
                "local_terms": 1,
                "local_calendar_revisions": 1,
                "local_calendar_days": 30,
                "local_operation_records": 1,
            }
        )
        self.assertEqual(counts, expected)

        day_rows = query_rows(
            db, "SELECT date, base_state, effective_state FROM local_calendar_days"
        )
        self.assertEqual(len(day_rows), 30)
        states = {row["effective_state"] for row in day_rows}
        self.assertTrue(states <= {"teaching", "non_teaching", "unknown"})
        self.assertIn("teaching", states)

        term = query_rows(
            db, "SELECT id, current_calendar_revision_id FROM local_terms"
        )[0]
        revision = query_rows(
            db, "SELECT id, term_id, revision_no, created_by FROM local_calendar_revisions"
        )[0]
        self.assertEqual(term["current_calendar_revision_id"], revision["id"])
        self.assertEqual(revision["term_id"], term["id"])
        profile = query_rows(db, "SELECT id, display_name, singleton FROM local_profile")[0]
        self.assertEqual(revision["created_by"], profile["id"])
        self.assertEqual(profile["singleton"], 1)

        audit = query_rows(
            db,
            "SELECT action, target_type, target_id, target_version_after, actor_id "
            "FROM local_operation_records",
        )[0]
        self.assertEqual(audit["action"], "initialize_local_profile")
        self.assertEqual(audit["target_id"], profile["id"])
        self.assertEqual(audit["actor_id"], profile["id"])
        self.assertIsNone(audit["target_version_after"])

    def test_school_name_optional(self):
        server = self.start_server()
        client = server.client()
        body = initialize_body()
        del body["school_name"]
        status, payload = client.post("/api/local/initialize", body)
        self.assertEqual(status, 201, payload)
        self.assertIsNone(payload["school_name"])

    # -- validation -------------------------------------------------------
    def test_initialize_validation_errors(self):
        server = self.start_server()
        client = server.client()
        cases = [
            {"display_name": ""},
            {"display_name": "  "},
            {"display_name": "x" * 81},
            {"class_name": ""},
            {"term_name": "   "},
            {"grade": "big"},
            {"school_name": "x" * 121},
            {"start_date": "2026-10-01", "end_date": "2026-09-01"},
            {"request_id": "not-a-uuid"},
            {"request_id": None},
            {"display_name": 123},
            {"extra_owner_field": "x"},
        ]
        for overrides in cases:
            with self.subTest(overrides=overrides):
                body = initialize_body(**overrides)
                status, payload = client.post("/api/local/initialize", body)
                self.assertEqual(status, 422, payload)
                self.assertEqual(payload["error"]["code"], "VALIDATION_ERROR")
        body = initialize_body()
        del body["display_name"]
        status, payload = client.post("/api/local/initialize", body)
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "VALIDATION_ERROR")

    # -- retry rules ------------------------------------------------------
    def test_same_key_retry_reads_back_without_new_rows(self):
        server = self.start_server()
        client = server.client()
        body = initialize_body()
        status1, payload1 = client.post("/api/local/initialize", body)
        self.assertEqual(status1, 201)
        db = server.runtime.db_path
        counts_before = self.counts(db)

        status2, payload2 = client.post("/api/local/initialize", body)
        self.assertEqual(status2, 200, payload2)
        self.assertEqual(payload1, payload2)
        self.assertEqual(self.counts(db), counts_before)

    def test_same_key_different_input_conflicts(self):
        server = self.start_server()
        client = server.client()
        body = initialize_body()
        self.assertEqual(client.post("/api/local/initialize", body)[0], 201)
        db = server.runtime.db_path
        counts_before = self.counts(db)

        changed = dict(body)
        changed["display_name"] = "李老师"
        status, payload = client.post("/api/local/initialize", changed)
        self.assertEqual(status, 409, payload)
        self.assertEqual(
            payload["error"]["code"], "INITIALIZATION_REQUEST_CONFLICT"
        )
        self.assertEqual(self.counts(db), counts_before)

    def test_other_key_after_initialized_is_already_initialized(self):
        server = self.start_server()
        client = server.client()
        first = self.initialize(client)
        db = server.runtime.db_path
        counts_before = self.counts(db)

        status, payload = client.post("/api/local/initialize", initialize_body())
        self.assertEqual(status, 409, payload)
        self.assertEqual(payload["error"]["code"], "ALREADY_INITIALIZED")
        self.assertEqual(self.counts(db), counts_before)
        status, context = client.get("/api/local/context")
        self.assertEqual(context["profile"]["id"], first["profile"]["id"])

    def test_retry_survives_calendar_library_failure(self):
        server = self.start_server()
        client = server.client()
        body = initialize_body()
        status, first = client.post("/api/local/initialize", body)
        self.assertEqual(status, 201)

        cal.register_provider(StaticCalendarProvider(fail=True), "failing")
        try:
            status, payload = client.post("/api/local/initialize", body)
            self.assertEqual(status, 200, payload)
            self.assertEqual(payload, first)
            status, payload = client.post(
                "/api/local/initialize", initialize_body()
            )
            self.assertEqual(status, 409, payload)
            self.assertEqual(payload["error"]["code"], "ALREADY_INITIALIZED")
        finally:
            cal.reset_provider()

    # -- failure paths ----------------------------------------------------
    def test_library_runtime_failure_fails_initialization_cleanly(self):
        server = self.start_server()
        client = server.client()
        cal.register_provider(StaticCalendarProvider(fail=True), "failing")
        try:
            status, payload = client.post(
                "/api/local/initialize", initialize_body()
            )
        finally:
            cal.reset_provider()
        self.assertEqual(status, 503, payload)
        self.assertEqual(payload["error"]["code"], "CALENDAR_UNAVAILABLE")
        db = server.runtime.db_path
        self.assertEqual(self.counts(db), ZERO_COUNTS)
        status, context = client.get("/api/local/context")
        self.assertEqual(context["status"], "uninitialized")

        # A later retry with a healthy provider succeeds.
        status, payload = client.post("/api/local/initialize", initialize_body())
        self.assertEqual(status, 201, payload)

    def test_mid_transaction_failure_leaves_no_partial_profile(self):
        server = self.start_server()
        client = server.client()
        db = server.runtime.db_path
        execute_sql(
            db,
            "CREATE TRIGGER fault_calendar_days BEFORE INSERT ON local_calendar_days "
            "BEGIN SELECT RAISE(ABORT, 'injected calendar day failure'); END",
        )
        try:
            status, payload = client.post(
                "/api/local/initialize", initialize_body()
            )
            self.assertEqual(status, 503, payload)
            self.assertEqual(payload["error"]["code"], "LOCAL_STORAGE_ERROR")
            self.assertEqual(self.counts(db), ZERO_COUNTS)
            status, context = client.get("/api/local/context")
            self.assertEqual(context["status"], "uninitialized")
        finally:
            execute_sql(db, "DROP TRIGGER IF EXISTS fault_calendar_days")

        status, payload = client.post("/api/local/initialize", initialize_body())
        self.assertEqual(status, 201, payload)
        self.assertEqual(self.counts(db)["local_profile"], 1)

    # -- unknown years ----------------------------------------------------
    def test_unknown_year_days_are_saved_as_unknown(self):
        cal.register_provider(
            StaticCalendarProvider(unknown_years={2026}), "unknown-year"
        )
        try:
            server = self.start_server()
            client = server.client()
            status, payload = client.post(
                "/api/local/initialize", initialize_body()
            )
            self.assertEqual(status, 201, payload)
            db = server.runtime.db_path
            states = {
                row["effective_state"]
                for row in query_rows(db, "SELECT effective_state FROM local_calendar_days")
            }
            self.assertEqual(states, {"unknown"})

            status, calendar = client.get(
                "/api/local/calendar?from=2026-09-01&to=2026-09-02"
            )
            self.assertEqual(status, 200)
            for item in calendar["items"]:
                self.assertEqual(item["effective_state"], "unknown")
                self.assertFalse(item["date_eligible"])
                self.assertIsNotNone(item["reason"])

            status, plan = client.post(
                "/api/daily-plans", {"plan_date": "2026-09-01"}
            )
            self.assertEqual(status, 422, plan)
            self.assertEqual(plan["error"]["code"], "YEAR_NOT_COVERED")
        finally:
            cal.reset_provider()

    # -- cross-process races ---------------------------------------------
    def test_two_processes_same_key_create_one_profile(self):
        self.make_runtime()
        body = initialize_body()
        spec_a = self.worker_spec("initialize")
        spec_a["input"] = body
        spec_b = self.worker_spec("initialize")
        spec_b["input"] = dict(body)
        proc_a = self.spawn_worker(spec_a)
        proc_b = self.spawn_worker(spec_b)
        result_a = self.collect_worker(proc_a, spec_a)
        result_b = self.collect_worker(proc_b, spec_b)

        created = [r for r in (result_a, result_b) if r.get("created") is True]
        self.assertEqual(len(created), 1, (result_a, result_b))
        other = [r for r in (result_a, result_b) if r.get("created") is not True][0]
        self.assertIn("payload", other)
        self.assertEqual(
            created[0]["payload"]["profile"]["id"],
            other["payload"]["profile"]["id"],
        )
        self.assertEqual(self.counts(self.data_dir / "kindergarten.db"), {
            **ZERO_COUNTS,
            "local_profile": 1,
            "local_settings": 1,
            "local_classes": 1,
            "local_terms": 1,
            "local_calendar_revisions": 1,
            "local_calendar_days": 30,
            "local_operation_records": 1,
        })

    def test_two_processes_different_keys_produce_one_setup(self):
        self.make_runtime()
        spec_a = self.worker_spec("initialize")
        spec_a["input"] = initialize_body()
        spec_b = self.worker_spec("initialize")
        spec_b["input"] = initialize_body()
        proc_a = self.spawn_worker(spec_a)
        proc_b = self.spawn_worker(spec_b)
        result_a = self.collect_worker(proc_a, spec_a)
        result_b = self.collect_worker(proc_b, spec_b)

        created = [r for r in (result_a, result_b) if r.get("created") is True]
        self.assertEqual(len(created), 1, (result_a, result_b))
        loser = [r for r in (result_a, result_b) if r.get("created") is not True][0]
        self.assertEqual(loser["error"]["code"], "ALREADY_INITIALIZED")
        db = self.data_dir / "kindergarten.db"
        self.assertEqual(query_scalar(db, "SELECT count(*) AS n FROM local_profile"), 1)
        self.assertEqual(
            query_scalar(db, "SELECT count(*) AS n FROM local_operation_records"), 1
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
