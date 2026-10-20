"""Effective-calendar reads: week numbering, exceptions, unknown years.

Week numbering follows the reviewed rules (Monday weeks, week 1 is the
week containing the term start, holidays count, cross-year never resets,
make-up days follow their real week). Creation eligibility and existing
plans are separate: an existing plan stays readable and savable when the
date is no longer teaching-eligible, while a missing persisted calendar row
is a data error (never a live recompute).
"""

from __future__ import annotations

import unittest
from datetime import date

from tests.local.support import (
    LocalTestCase,
    StaticCalendarProvider,
    calendar_provider,
    execute_sql,
    initialize_body,
    query_rows,
    query_scalar,
    term_dates,
)


class CalendarDateTests(LocalTestCase):
    def _start(self, start: date, end: date, provider: StaticCalendarProvider):
        self.enterContext(calendar_provider(provider))
        server = self.start_server()
        client = server.client()
        status, context = client.post(
            "/api/local/initialize",
            initialize_body(
                start_date=start.isoformat(), end_date=end.isoformat()
            ),
        )
        self.assertEqual(status, 201, context)
        return server, client

    def _calendar(self, client, start: date, end: date) -> dict[str, dict]:
        status, payload = client.get(
            f"/api/local/calendar?from={start.isoformat()}&to={end.isoformat()}"
        )
        self.assertEqual(status, 200, payload)
        return {item["date"]: item for item in payload["items"]}

    def test_week_numbering_holidays_and_cross_year(self):
        start, end = date(2026, 12, 28), date(2027, 1, 10)
        days = term_dates(start, end)
        workdays = {
            day
            for day in days
            if day.isoweekday() <= 5
            and day not in {date(2026, 12, 31), date(2027, 1, 1)}
        }
        provider = StaticCalendarProvider(workdays=workdays)
        _server, client = self._start(start, end, provider)
        calendar = self._calendar(client, start, end)
        self.assertEqual(len(calendar), 14)

        expectations = {
            "2026-12-28": (1, 1, "teaching", True),
            "2026-12-31": (1, 4, "non_teaching", False),
            "2027-01-01": (1, 5, "non_teaching", False),
            "2027-01-03": (1, 7, "non_teaching", False),
            "2027-01-04": (2, 1, "teaching", True),
            "2027-01-10": (2, 7, "non_teaching", False),
        }
        for day, (week, weekday, state, eligible) in expectations.items():
            with self.subTest(day=day):
                item = calendar[day]
                self.assertEqual(item["week_number"], week)
                self.assertEqual(item["weekday"], weekday)
                self.assertEqual(item["effective_state"], state)
                self.assertEqual(item["date_eligible"], eligible)
                self.assertIsNotNone(item["term_id"])
                self.assertIsNotNone(item["revision_id"])
                self.assertIsNone(item["existing_plan_id"])

    def test_makeup_workday_follows_its_real_week(self):
        start, end = date(2026, 9, 1), date(2026, 9, 30)
        provider = StaticCalendarProvider(
            weekend_workdays={date(2026, 9, 5)}
        )
        _server, client = self._start(start, end, provider)
        calendar = self._calendar(client, date(2026, 9, 1), date(2026, 9, 8))
        saturday = calendar["2026-09-05"]
        self.assertEqual(saturday["weekday"], 6)
        self.assertEqual(saturday["week_number"], 1)
        self.assertEqual(saturday["effective_state"], "teaching")
        self.assertTrue(saturday["date_eligible"])
        sunday = calendar["2026-09-06"]
        self.assertEqual(sunday["week_number"], 1)
        self.assertFalse(sunday["date_eligible"])

        status, plan = client.post(
            "/api/daily-plans", {"plan_date": "2026-09-05"}
        )
        self.assertEqual(status, 201, plan)
        self.assertEqual(plan["week_number"], 1)
        self.assertEqual(plan["weekday"], 6)

    def test_creation_eligibility_codes(self):
        start, end = date(2026, 9, 1), date(2026, 9, 30)
        _server, client = self._start(start, end, StaticCalendarProvider())
        cases = {
            "2026-08-31": "OUTSIDE_TERM",
            "2026-10-01": "OUTSIDE_TERM",
            "2026-09-05": "DATE_NOT_ELIGIBLE",
            "2026-09-06": "DATE_NOT_ELIGIBLE",
        }
        for day, code in cases.items():
            with self.subTest(day=day):
                status, payload = client.post(
                    "/api/daily-plans", {"plan_date": day}
                )
                self.assertEqual(status, 422, payload)
                self.assertEqual(payload["error"]["code"], code)

        calendar = self._calendar(client, date(2026, 8, 30), date(2026, 8, 31))
        for item in calendar.values():
            self.assertIsNone(item["term_id"])
            self.assertIsNone(item["week_number"])
            self.assertEqual(item["effective_state"], "outside_term")
            self.assertFalse(item["date_eligible"])
            self.assertIsNotNone(item["reason"])

    def test_max_date_boundary_does_not_overflow(self):
        start, end = date(2026, 9, 1), date(2026, 9, 30)
        _server, client = self._start(start, end, StaticCalendarProvider())

        # date.max itself must be iterated once (closed interval) without the
        # internal `+1 day` step raising OverflowError.
        status, payload = client.get(
            "/api/local/calendar?from=9999-12-31&to=9999-12-31"
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(len(payload["items"]), 1)
        item = payload["items"][0]
        self.assertEqual(item["date"], "9999-12-31")
        self.assertEqual(item["effective_state"], "outside_term")
        self.assertIsNone(item["term_id"])
        self.assertFalse(item["date_eligible"])

        status, payload = client.get(
            "/api/local/calendar?from=9999-12-30&to=9999-12-31"
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(
            [entry["date"] for entry in payload["items"]],
            ["9999-12-30", "9999-12-31"],
        )

        # Plan list bounds at the same boundary stay a normal empty result.
        status, listed = client.get(
            "/api/daily-plans?from=9999-12-31&to=9999-12-31"
        )
        self.assertEqual(status, 200, listed)
        self.assertEqual(listed["total"], 0)

    def test_missing_persisted_calendar_row_is_a_data_error(self):
        start, end = date(2026, 9, 1), date(2026, 9, 30)
        server, client = self._start(start, end, StaticCalendarProvider())
        execute_sql(
            server.runtime.db_path,
            "DELETE FROM local_calendar_days WHERE date = '2026-09-10'",
        )
        status, payload = client.get(
            "/api/local/calendar?from=2026-09-09&to=2026-09-11"
        )
        self.assertEqual(status, 503, payload)
        self.assertEqual(payload["error"]["code"], "LOCAL_STORAGE_ERROR")
        status, payload = client.post(
            "/api/daily-plans", {"plan_date": "2026-09-10"}
        )
        self.assertEqual(status, 503, payload)
        self.assertEqual(payload["error"]["code"], "LOCAL_STORAGE_ERROR")

    def test_stored_revision_not_recomputed_after_library_change(self):
        start, end = date(2026, 9, 1), date(2026, 9, 30)
        provider_v1 = StaticCalendarProvider(version="calendar-v1")
        server, client = self._start(start, end, provider_v1)
        db = server.runtime.db_path
        first_context = client.get("/api/local/context?date=2026-09-15")[1]
        first_states = query_rows(
            db, "SELECT date, effective_state FROM local_calendar_days ORDER BY date"
        )

        # Simulate a new library version that would classify every day as
        # non-teaching; stored revisions must not be recomputed.
        from app.services import calendar_service as cal

        provider_v2 = StaticCalendarProvider(version="calendar-v2", workdays=set())
        cal.register_provider(provider_v2, provider_v2.version)
        try:
            second_context = client.get("/api/local/context?date=2026-09-15")[1]
            self.assertEqual(
                second_context["calendar_revision"]["id"],
                first_context["calendar_revision"]["id"],
            )
            self.assertEqual(
                second_context["calendar_revision"]["library_version"],
                "calendar-v1",
            )
            self.assertEqual(
                query_scalar(db, "SELECT count(*) AS n FROM local_calendar_revisions"),
                1,
            )
            self.assertEqual(
                query_rows(
                    db,
                    "SELECT date, effective_state FROM local_calendar_days "
                    "ORDER BY date",
                ),
                first_states,
            )
        finally:
            cal.reset_provider()

        # A full restart reads the same stored revision: the first runtime is
        # disposed (releasing the exclusive root lock) before the next one
        # prepares.
        server.stop()
        server.runtime.dispose()
        runtime = self.make_runtime()
        session = runtime.session()
        try:
            from app.local.profile_service import read_context

            context = read_context(session, date(2026, 9, 15))
        finally:
            session.close()
        self.assertEqual(
            context["calendar_revision"]["id"],
            first_context["calendar_revision"]["id"],
        )
        self.assertEqual(
            context["calendar_revision"]["library_version"], "calendar-v1"
        )
        self.assertEqual(
            query_rows(
                db, "SELECT date, effective_state FROM local_calendar_days ORDER BY date"
            ),
            first_states,
        )

    def test_existing_plan_readable_when_no_longer_eligible(self):
        start, end = date(2026, 9, 1), date(2026, 9, 30)
        server, client = self._start(start, end, StaticCalendarProvider())
        status, plan = client.post("/api/daily-plans", {"plan_date": "2026-09-01"})
        self.assertEqual(status, 201, plan)

        execute_sql(
            server.runtime.db_path,
            "UPDATE local_calendar_days SET base_state = 'non_teaching', "
            "effective_state = 'non_teaching' WHERE date = '2026-09-01'",
        )
        calendar = self._calendar(client, date(2026, 9, 1), date(2026, 9, 1))
        item = calendar["2026-09-01"]
        self.assertFalse(item["date_eligible"])
        self.assertEqual(item["existing_plan_id"], plan["id"])

        status, by_date = client.get("/api/daily-plans/by-date?date=2026-09-01")
        self.assertEqual(status, 200, by_date)
        self.assertEqual(by_date["id"], plan["id"])
        status, listed = client.get(
            "/api/daily-plans?from=2026-09-01&to=2026-09-30"
        )
        self.assertEqual(status, 200)
        self.assertEqual(listed["total"], 1)

        # Creation on the same date opens the existing plan (200, no change),
        # and an explicit save still works on the stored record.
        status, opened = client.post("/api/daily-plans", {"plan_date": "2026-09-01"})
        self.assertEqual(status, 200, opened)
        self.assertEqual(opened["id"], plan["id"])
        status, saved = client.patch(
            f"/api/daily-plans/{plan['id']}",
            {"expected_content_version": 1, "raw_lesson_plan": "仍可保存"},
        )
        self.assertEqual(status, 200, saved)
        self.assertEqual(saved["current_content_version"], 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
