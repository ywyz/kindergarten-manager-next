"""Integration tests for I2 phase 2: terms, persisted calendar, preview/apply.

These tests require an isolated MySQL 8.4 / InnoDB database with the I2
migrations applied. They never run migrations themselves. Calendar library
input is replaced by deterministic fixtures so the tests do not depend on
whether ``chinesecalendar`` is installed.
"""

from __future__ import annotations

import os
import unittest
from datetime import date, timedelta

os.environ["APP_DISABLE_DOTENV"] = "1"

from sqlalchemy import text  # noqa: E402

from app.services import calendar_service  # noqa: E402
from tests.integration.i2_guard import (  # noqa: E402
    AsgiClient,
    HEADERS,
    _json_body,
    check_environment,
    ensure_schema,
    make_engine,
    register_and_login,
    require_authorized_url,
    reset_i2_tables,
    skip_unless_enabled,
)


class _DeterministicProvider:
    """Fixture calendar provider: exact workdays/restdays by ISO date.

    Years not explicitly covered raise ``NotImplementedError`` so the builder
    marks them as ``unknown`` instead of guessing.
    """

    version = "fixture-1"

    def __init__(self, workdays: set[date], covered_years: set[int] | None = None):
        self.workdays = workdays
        self.covered_years = covered_years or {d.year for d in workdays}

    def is_workday(self, day: date) -> bool:
        if day.year not in self.covered_years:
            raise NotImplementedError(f"year {day.year} not covered")
        return day in self.workdays

    def is_holiday(self, day: date) -> bool:
        return not self.is_workday(day)


class _FixtureProvider2:
    """Second fixture version to simulate a library upgrade."""

    version = "fixture-2"

    def __init__(self, workdays: set[date], covered_years: set[int] | None = None):
        self.workdays = workdays
        self.covered_years = covered_years or {d.year for d in workdays}

    def is_workday(self, day: date) -> bool:
        if day.year not in self.covered_years:
            raise NotImplementedError(f"year {day.year} not covered")
        return day in self.workdays

    def is_holiday(self, day: date) -> bool:
        return not self.is_workday(day)


@skip_unless_enabled
class TermsCalendarIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = make_engine()
        require_authorized_url(str(cls.engine.url))
        check_environment(cls.engine)
        ensure_schema(cls.engine)

    def setUp(self):
        reset_i2_tables(self.engine)
        self.client = AsgiClient()
        self.admin, self.admin_cookie = register_and_login(
            self.client, "headadmin"
        )
        self.teacher, self.teacher_cookie = register_and_login(
            self.client, "teacher_one"
        )
        self._provider: _DeterministicProvider | None = None

    def tearDown(self):
        calendar_service.reset_provider()

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def _as(self, cookie: dict[str, str]) -> None:
        self.client.cookies = cookie

    def _install_provider(self, workdays: set[date]):
        self._provider = _DeterministicProvider(workdays)
        calendar_service.register_provider(self._provider, "fixture-1")

    def _install_provider_v2(self, workdays: set[date], covered_years: set[int] | None = None):
        provider = _FixtureProvider2(workdays, covered_years)
        calendar_service.register_provider(provider, "fixture-2")

    def _create_class(self, name: str, grade: str = "small") -> dict:
        self._as(self.admin_cookie)
        preview = self.client.request(
            "POST",
            "/api/admin/configuration-changes/preview",
            headers=HEADERS,
            body=_json_body(
                {"kind": "class_create", "name": name, "grade": grade}
            ),
        )
        self.assertEqual(preview.status, 201, preview.body)
        target_id = preview.json()["target_id"]
        applied = self.client.request(
            "POST",
            f"/api/admin/configuration-changes/{preview.json()['id']}/apply",
            headers=HEADERS,
            body=_json_body({"confirm": True}),
        )
        self.assertEqual(applied.status, 200, applied.body)
        detail = self.client.request("GET", f"/api/admin/classes/{target_id}")
        self.assertEqual(detail.status, 200, detail.body)
        result = detail.json()
        self.assertEqual(result["name"], name)
        return result

    def _create_term(self, name: str, start: str, end: str) -> dict:
        self._as(self.admin_cookie)
        settings = self.client.request(
            "GET", "/api/admin/school-settings"
        ).json()
        preview = self.client.request(
            "POST",
            "/api/admin/configuration-changes/preview",
            headers=HEADERS,
            body=_json_body(
                {
                    "kind": "term_create",
                    "name": name,
                    "start_date": start,
                    "end_date": end,
                    "expected_schedule_version": settings["schedule_version"],
                }
            ),
        )
        self.assertEqual(preview.status, 201, preview.body)
        target_id = preview.json()["target_id"]
        applied = self.client.request(
            "POST",
            f"/api/admin/configuration-changes/{preview.json()['id']}/apply",
            headers=HEADERS,
            body=_json_body({"confirm": True}),
        )
        self.assertEqual(applied.status, 200, applied.body)
        detail = self.client.request("GET", f"/api/admin/terms/{target_id}")
        self.assertEqual(detail.status, 200, detail.body)
        result = detail.json()
        self.assertEqual(result["name"], name)
        return result

    def _preview(self, payload: dict) -> dict:
        self._as(self.admin_cookie)
        resp = self.client.request(
            "POST",
            "/api/admin/configuration-changes/preview",
            headers=HEADERS,
            body=_json_body(payload),
        )
        return resp

    def _apply(self, change_id: str) -> dict:
        self._as(self.admin_cookie)
        resp = self.client.request(
            "POST",
            f"/api/admin/configuration-changes/{change_id}/apply",
            headers=HEADERS,
            body=_json_body({"confirm": True}),
        )
        return resp

    def _read_calendar(self, from_date: str, to_date: str) -> dict:
        self._as(self.admin_cookie)
        return self.client.request(
            "GET",
            f"/api/admin/calendar?from={from_date}&to={to_date}",
        ).json()

    # -- V5: term overlap (P1) ---------------------------------------------

    def test_adjacent_terms_do_not_overlap(self):
        self._install_provider({date(2026, 9, 1)})
        t1 = self._create_term("2026秋", "2026-09-01", "2026-09-30")
        self.assertEqual(t1["version"], 1)

        settings = self.client.request(
            "GET", "/api/admin/school-settings"
        ).json()
        resp = self._preview(
            {
                "kind": "term_create",
                "name": "2026冬",
                "start_date": "2026-10-01",
                "end_date": "2026-10-31",
                "expected_schedule_version": settings["schedule_version"],
            }
        )
        self.assertEqual(resp.status, 201, resp.body)

    def test_terms_sharing_endpoint_overlap(self):
        self._install_provider({date(2026, 9, 1)})
        self._create_term("2026秋", "2026-09-01", "2026-09-30")
        settings = self.client.request(
            "GET", "/api/admin/school-settings"
        ).json()
        resp = self._preview(
            {
                "kind": "term_create",
                "name": "2026冬",
                "start_date": "2026-09-30",
                "end_date": "2026-10-31",
                "expected_schedule_version": settings["schedule_version"],
            }
        )
        self.assertEqual(resp.status, 409)
        self.assertIn(b"TERM_OVERLAP", resp.body)

    def test_terms_partially_overlap_rejected(self):
        self._install_provider({date(2026, 9, 1)})
        self._create_term("2026秋", "2026-09-01", "2026-09-30")
        settings = self.client.request(
            "GET", "/api/admin/school-settings"
        ).json()
        resp = self._preview(
            {
                "kind": "term_create",
                "name": "2026冬",
                "start_date": "2026-09-15",
                "end_date": "2026-10-15",
                "expected_schedule_version": settings["schedule_version"],
            }
        )
        self.assertEqual(resp.status, 409)
        self.assertIn(b"TERM_OVERLAP", resp.body)

    # -- V6: week numbering --------------------------------------------------

    def test_week_numbering(self):
        # 2026-09-01 is Tuesday; week starts Monday 2026-08-31.
        workdays = {date(2026, 9, d) for d in range(1, 30)}
        self._install_provider(workdays)
        self._create_term("2026秋", "2026-09-01", "2026-09-30")

        cal = self._read_calendar("2026-09-01", "2026-09-07")
        items = {item["date"]: item for item in cal["items"]}
        # 09-01 (Tue) and 09-06 (Sun) are in week 1 because the week contains
        # the term start date and starts on Monday 08-31.
        self.assertEqual(items["2026-09-01"]["week_number"], 1)
        self.assertEqual(items["2026-09-06"]["week_number"], 1)
        self.assertEqual(items["2026-09-07"]["week_number"], 2)

    def test_week_numbering_cross_year(self):
        workdays = {date(2026, 9, 1), date(2027, 1, 1)}
        self._install_provider(workdays)
        self._create_term("跨年期", "2026-09-01", "2027-01-31")
        cal = self._read_calendar("2027-01-01", "2027-01-01")
        item = cal["items"][0]
        self.assertGreater(item["week_number"], 1)

    # -- V7: default vs override ---------------------------------------------

    def test_exception_overrides_default(self):
        d = date(2026, 9, 5)  # Saturday
        workdays = {d}  # library says workday
        self._install_provider(workdays)
        term = self._create_term("2026秋", "2026-09-01", "2026-09-30")

        # Without exception the day is teaching.
        cal = self._read_calendar("2026-09-05", "2026-09-05")
        self.assertEqual(cal["items"][0]["effective_state"], "teaching")

        # Admin exception: non_teaching.
        resp = self._preview(
            {
                "kind": "calendar_override",
                "target_id": term["id"],
                "expected_term_version": term["version"],
                "expected_calendar_revision_id": term["calendar_revision_id"],
                "expected_schedule_version": self.client.request(
                    "GET", "/api/admin/school-settings"
                ).json()["schedule_version"],
                "dates": [
                    {
                        "date": "2026-09-05",
                        "state": "non_teaching",
                        "reason": "园所活动",
                    }
                ],
            }
        )
        self.assertEqual(resp.status, 201, resp.body)
        applied = self._apply(resp.json()["id"])
        self.assertEqual(applied.status, 200, applied.body)

        cal = self._read_calendar("2026-09-05", "2026-09-05")
        item = cal["items"][0]
        self.assertEqual(item["effective_state"], "non_teaching")
        self.assertEqual(item["source"], "admin_exception")
        self.assertEqual(item["reason"], "园所活动")

    # -- V8: uncovered year / unknown ----------------------------------------

    def test_uncovered_year_stays_unknown(self):
        # Provider covers nothing -> every default is unknown.
        self._install_provider(set())
        term = self._create_term("未知年", "2099-01-01", "2099-01-07")
        cal = self._read_calendar("2099-01-01", "2099-01-07")
        for item in cal["items"]:
            self.assertEqual(item["base_state"], "unknown")
            self.assertEqual(item["effective_state"], "unknown")
            self.assertEqual(item["reason_code"], "YEAR_NOT_COVERED")

        # Admin can explicitly mark a single day as teaching.
        resp = self._preview(
            {
                "kind": "calendar_override",
                "target_id": term["id"],
                "expected_term_version": term["version"],
                "expected_calendar_revision_id": term["calendar_revision_id"],
                "expected_schedule_version": self.client.request(
                    "GET", "/api/admin/school-settings"
                ).json()["schedule_version"],
                "dates": [
                    {
                        "date": "2099-01-03",
                        "state": "teaching",
                        "reason": "手动安排",
                    }
                ],
            }
        )
        self.assertEqual(resp.status, 201, resp.body)
        self._apply(resp.json()["id"])

        cal = self._read_calendar("2099-01-01", "2099-01-07")
        by_date = {item["date"]: item for item in cal["items"]}
        self.assertEqual(by_date["2099-01-03"]["effective_state"], "teaching")
        self.assertEqual(by_date["2099-01-02"]["effective_state"], "unknown")

        # Remove the exception -> back to unknown.
        term = self.client.request("GET", "/api/admin/terms").json()["items"][0]
        resp = self._preview(
            {
                "kind": "calendar_override",
                "target_id": term["id"],
                "expected_term_version": term["version"],
                "expected_calendar_revision_id": term["calendar_revision_id"],
                "expected_schedule_version": self.client.request(
                    "GET", "/api/admin/school-settings"
                ).json()["schedule_version"],
                "dates": [{"date": "2099-01-03", "state": None}],
            }
        )
        self.assertEqual(resp.status, 201, resp.body)
        self._apply(resp.json()["id"])
        cal = self._read_calendar("2099-01-03", "2099-01-03")
        self.assertEqual(cal["items"][0]["effective_state"], "unknown")

    # -- V9: reimport keeps exceptions ---------------------------------------

    def test_reimport_preserves_exceptions(self):
        d = date(2026, 9, 5)
        self._install_provider({d})
        term = self._create_term("2026秋", "2026-09-01", "2026-09-30")

        # Add an exception that makes 09-05 non-teaching.
        settings = self.client.request(
            "GET", "/api/admin/school-settings"
        ).json()
        resp = self._preview(
            {
                "kind": "calendar_override",
                "target_id": term["id"],
                "expected_term_version": term["version"],
                "expected_calendar_revision_id": term["calendar_revision_id"],
                "expected_schedule_version": settings["schedule_version"],
                "dates": [
                    {
                        "date": "2026-09-05",
                        "state": "non_teaching",
                        "reason": "活动",
                    }
                ],
            }
        )
        self._apply(resp.json()["id"])

        # Upgrade the library fixture: 09-05 is now a holiday (non-teaching)
        # by default. The exception should still mask it.
        self._install_provider_v2(set(), {2026})
        term = self.client.request("GET", "/api/admin/terms").json()["items"][0]
        settings = self.client.request(
            "GET", "/api/admin/school-settings"
        ).json()
        resp = self._preview(
            {
                "kind": "calendar_reimport",
                "target_id": term["id"],
                "expected_term_version": term["version"],
                "expected_calendar_revision_id": term["calendar_revision_id"],
                "expected_schedule_version": settings["schedule_version"],
            }
        )
        self.assertEqual(resp.status, 201, resp.body)
        preview = resp.json()
        self.assertEqual(preview["impact"]["changed_day_count"], 1)

        self._apply(preview["id"])
        cal = self._read_calendar("2026-09-05", "2026-09-05")
        item = cal["items"][0]
        self.assertEqual(item["effective_state"], "non_teaching")
        self.assertEqual(item["source"], "admin_exception")

    # -- V10: preview staleness / expiry -------------------------------------

    def test_preview_becomes_stale_after_term_modified(self):
        self._install_provider({date(2026, 9, 1)})
        term = self._create_term("2026秋", "2026-09-01", "2026-09-30")

        settings = self.client.request(
            "GET", "/api/admin/school-settings"
        ).json()
        resp = self._preview(
            {
                "kind": "calendar_override",
                "target_id": term["id"],
                "expected_term_version": term["version"],
                "expected_calendar_revision_id": term["calendar_revision_id"],
                "expected_schedule_version": settings["schedule_version"],
                "dates": [
                    {
                        "date": "2026-09-10",
                        "state": "non_teaching",
                        "reason": "测试",
                    }
                ],
            }
        )
        self.assertEqual(resp.status, 201, resp.body)
        preview_id = resp.json()["id"]

        # Another admin operation changes term version / schedule_version.
        update_resp = self._preview(
            {
                "kind": "term_update",
                "target_id": term["id"],
                "name": "2026秋季",
                "expected_version": term["version"],
                "expected_schedule_version": settings["schedule_version"],
            }
        )
        self.assertEqual(update_resp.status, 201, update_resp.body)
        self._apply(update_resp.json()["id"])

        # Old preview can no longer apply.
        applied = self._apply(preview_id)
        self.assertEqual(applied.status, 409)
        self.assertIn(b"PREVIEW_STALE", applied.body)

    def test_other_admin_cannot_apply_preview(self):
        self._install_provider({date(2026, 9, 1)})
        term = self._create_term("2026秋", "2026-09-01", "2026-09-30")
        settings = self.client.request(
            "GET", "/api/admin/school-settings"
        ).json()
        resp = self._preview(
            {
                "kind": "calendar_override",
                "target_id": term["id"],
                "expected_term_version": term["version"],
                "expected_calendar_revision_id": term["calendar_revision_id"],
                "expected_schedule_version": settings["schedule_version"],
                "dates": [
                    {
                        "date": "2026-09-10",
                        "state": "non_teaching",
                        "reason": "测试",
                    }
                ],
            }
        )
        preview_id = resp.json()["id"]

        # Create a genuine second admin account by resetting the control row.
        from tests.integration.i2_guard import unclaim_first_admin
        unclaim_first_admin(self.engine)
        other_client = AsgiClient()
        register_and_login(other_client, "otheradmin")
        other_resp = other_client.request(
            "POST",
            f"/api/admin/configuration-changes/{preview_id}/apply",
            headers=HEADERS,
            body=_json_body({"confirm": True}),
        )
        self.assertEqual(other_resp.status, 403)

    def test_teacher_cannot_apply_preview(self):
        self._install_provider({date(2026, 9, 1)})
        term = self._create_term("2026秋", "2026-09-01", "2026-09-30")
        settings = self.client.request(
            "GET", "/api/admin/school-settings"
        ).json()
        resp = self._preview(
            {
                "kind": "calendar_override",
                "target_id": term["id"],
                "expected_term_version": term["version"],
                "expected_calendar_revision_id": term["calendar_revision_id"],
                "expected_schedule_version": settings["schedule_version"],
                "dates": [
                    {
                        "date": "2026-09-10",
                        "state": "non_teaching",
                        "reason": "测试",
                    }
                ],
            }
        )
        preview_id = resp.json()["id"]

        self._as(self.teacher_cookie)
        teacher_resp = self.client.request(
            "POST",
            f"/api/admin/configuration-changes/{preview_id}/apply",
            headers=HEADERS,
            body=_json_body({"confirm": True}),
        )
        self.assertEqual(teacher_resp.status, 403)

    # -- V11: transaction rollback after real MySQL error --------------------

    def test_calendar_apply_rolls_back_on_mysql_error(self):
        from app.services import config_apply_pipeline

        # Make every day in the term a workday so 2026-09-10 starts as teaching.
        workdays = {date(2026, 9, d) for d in range(1, 31)}
        self._install_provider(workdays)
        term = self._create_term("2026秋", "2026-09-01", "2026-09-30")
        settings = self.client.request(
            "GET", "/api/admin/school-settings"
        ).json()
        resp = self._preview(
            {
                "kind": "calendar_override",
                "target_id": term["id"],
                "expected_term_version": term["version"],
                "expected_calendar_revision_id": term["calendar_revision_id"],
                "expected_schedule_version": settings["schedule_version"],
                "dates": [
                    {
                        "date": "2026-09-10",
                        "state": "non_teaching",
                        "reason": "测试",
                    }
                ],
            }
        )
        preview_id = resp.json()["id"]
        original = config_apply_pipeline.write_operation_record

        def failing_write(db, *, preview, result, operator_id, now):
            # First write the real operation record inside the transaction,
            # then flush everything to MySQL, then force a genuine server-side
            # statement error. This proves the whole transaction rolls back.
            original(db, preview=preview, result=result, operator_id=operator_id, now=now)
            db.flush()
            db.execute(text("INSERT INTO kg_i2_missing_table (id) VALUES ('x')"))

        try:
            config_apply_pipeline.write_operation_record = failing_write
            applied = self._apply(preview_id)
        finally:
            config_apply_pipeline.write_operation_record = original

        self.assertEqual(applied.status, 503, applied.body)

        # Use an independent connection to verify nothing persisted.
        with self.engine.connect() as conn:
            term_row = conn.execute(
                text("SELECT version, current_calendar_revision_id FROM terms WHERE id = :id"),
                {"id": term["id"]},
            ).fetchone()
            self.assertEqual(term_row.version, term["version"])
            self.assertEqual(term_row.current_calendar_revision_id, term["calendar_revision_id"])

            rev_count = conn.execute(
                text("SELECT COUNT(*) FROM calendar_revisions WHERE term_id = :id"),
                {"id": term["id"]},
            ).scalar()
            self.assertEqual(rev_count, 1)

            day_count = conn.execute(
                text(
                    "SELECT COUNT(*) FROM calendar_days d "
                    "JOIN calendar_revisions r ON d.revision_id = r.id "
                    "WHERE r.term_id = :id AND d.effective_state = 'non_teaching'"
                ),
                {"id": term["id"]},
            ).scalar()
            self.assertEqual(day_count, 0)

            applied_count = conn.execute(
                text(
                    "SELECT COUNT(*) FROM configuration_changes "
                    "WHERE id = :id AND status = 'applied'"
                ),
                {"id": preview_id},
            ).scalar()
            self.assertEqual(applied_count, 0)

            audit_count = conn.execute(
                text(
                    "SELECT COUNT(*) FROM operation_records WHERE action = 'calendar_override'"
                )
            ).scalar()
            self.assertEqual(audit_count, 0)

        cal = self._read_calendar("2026-09-10", "2026-09-10")
        self.assertEqual(cal["items"][0]["effective_state"], "teaching")

    # -- V12: read consistency -----------------------------------------------

    def test_calendar_read_is_consistent_for_single_revision(self):
        self._install_provider({date(2026, 9, 1)})
        self._create_term("2026秋", "2026-09-01", "2026-09-30")
        cal = self._read_calendar("2026-09-01", "2026-09-30")
        revision_ids = {item["calendar_revision_id"] for item in cal["items"]}
        self.assertEqual(len(revision_ids), 1)

    # -- V13: plans-started gate ---------------------------------------------

    def test_plans_started_blocks_term_update(self):
        self._install_provider({date(2026, 9, 1)})
        term = self._create_term("2026秋", "2026-09-01", "2026-09-30")

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE school_settings SET plans_started_at = UTC_TIMESTAMP()"
                )
            )

        settings = self.client.request(
            "GET", "/api/admin/school-settings"
        ).json()
        resp = self._preview(
            {
                "kind": "term_update",
                "target_id": term["id"],
                "name": "改名",
                "expected_version": term["version"],
                "expected_schedule_version": settings["schedule_version"],
            }
        )
        self.assertEqual(resp.status, 201, resp.body)
        preview = resp.json()
        self.assertIn("DEPENDENCY_NOT_READY", preview["blockers"])

        applied = self._apply(preview["id"])
        self.assertEqual(applied.status, 409)
        self.assertIn(b"DEPENDENCY_NOT_READY", applied.body)


if __name__ == "__main__":
    unittest.main()
