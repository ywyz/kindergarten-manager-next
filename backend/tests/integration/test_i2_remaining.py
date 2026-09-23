"""I2 remaining integration tests for closure gaps A-E.

These tests require an isolated MySQL 8.4 / InnoDB database with the I2
migrations applied. They use the real database and, where specified, the
real ``chinesecalendar`` package or real subprocess restart.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import unittest
from datetime import date, datetime, timedelta

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
    unclaim_first_admin,
)


class _DeterministicProvider:
    version = "fixture-1"

    def __init__(self, workdays: set[date], covered_years: set[int] | None = None):
        self.workdays = workdays
        self.covered_years = covered_years or {d.year for d in workdays}

    def is_workday(self, day: date) -> bool:
        if day.year not in self.covered_years:
            raise NotImplementedError(f"year {day.year} not covered")
        return day in self.workdays


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


class _RaisingProvider:
    version = "raising"

    def is_workday(self, day: date) -> bool:
        raise RuntimeError("provider must not be called")


@skip_unless_enabled
class I2RemainingTests(unittest.TestCase):
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
        calendar_service.reset_provider()

    def tearDown(self):
        calendar_service.reset_provider()

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def _as(self, cookie: dict[str, str]) -> None:
        self.client.cookies = cookie

    def _create_class(self, name: str, grade: str = "small") -> dict:
        self._as(self.admin_cookie)
        preview = self.client.request(
            "POST",
            "/api/admin/configuration-changes/preview",
            headers=HEADERS,
            body=_json_body({"kind": "class_create", "name": name, "grade": grade}),
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
        return detail.json()

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
        return detail.json()

    def _preview(self, payload: dict) -> dict:
        self._as(self.admin_cookie)
        return self.client.request(
            "POST",
            "/api/admin/configuration-changes/preview",
            headers=HEADERS,
            body=_json_body(payload),
        )

    def _apply(self, change_id: str) -> dict:
        self._as(self.admin_cookie)
        return self.client.request(
            "POST",
            f"/api/admin/configuration-changes/{change_id}/apply",
            headers=HEADERS,
            body=_json_body({"confirm": True}),
        )

    def _read_calendar(self, from_date: str, to_date: str) -> dict:
        self._as(self.admin_cookie)
        resp = self.client.request(
            "GET",
            f"/api/admin/calendar?from={from_date}&to={to_date}",
        )
        self.assertEqual(resp.status, 200, resp.body)
        return resp.json()

    def _school_settings(self) -> dict:
        self._as(self.admin_cookie)
        resp = self.client.request("GET", "/api/admin/school-settings")
        self.assertEqual(resp.status, 200, resp.body)
        return resp.json()

    def _term(self, term_id: str) -> dict:
        self._as(self.admin_cookie)
        resp = self.client.request("GET", f"/api/admin/terms/{term_id}")
        self.assertEqual(resp.status, 200, resp.body)
        return resp.json()

    # -- A: real chinese calendar library ------------------------------------

    def test_real_chinese_calendar_2026_makeup_and_holiday(self):
        """2026-09-20 (Sun makeup) is teaching, 2026-09-25 (Fri holiday) is rest."""
        # Use the real installed library; do not register a fixture provider.
        calendar_service.reset_provider()
        self._create_term("2026秋", "2026-09-01", "2026-09-30")

        cal = self._read_calendar("2026-09-20", "2026-09-25")
        by_date = {item["date"]: item for item in cal["items"]}
        self.assertEqual(by_date["2026-09-20"]["effective_state"], "teaching")
        self.assertEqual(by_date["2026-09-25"]["effective_state"], "non_teaching")

        # Persisted rows in the active revision reflect the same states.
        with self.engine.connect() as conn:
            revision_id = conn.execute(
                text("SELECT id FROM calendar_revisions LIMIT 1")
            ).scalar()
            rows = conn.execute(
                text(
                    "SELECT date, effective_state, base_library_version "
                    "FROM calendar_days "
                    "WHERE revision_id = :rev AND date IN ('2026-09-20', '2026-09-25')"
                ),
                {"rev": revision_id},
            ).fetchall()
        persisted = {r.date.isoformat(): r for r in rows}
        self.assertEqual(persisted["2026-09-20"].effective_state, "teaching")
        self.assertEqual(persisted["2026-09-25"].effective_state, "non_teaching")
        self.assertEqual(persisted["2026-09-20"].base_library_version, "1.11.0")
        self.assertEqual(persisted["2026-09-25"].base_library_version, "1.11.0")

    def test_provider_runtime_error_returns_503_and_writes_nothing(self):
        calendar_service.register_provider(_RaisingProvider(), "raising")
        settings = self._school_settings()
        resp = self._preview(
            {
                "kind": "term_create",
                "name": "2026秋",
                "start_date": "2026-09-01",
                "end_date": "2026-09-30",
                "expected_schedule_version": settings["schedule_version"],
            }
        )
        self.assertEqual(resp.status, 503, resp.body)
        self.assertIn(b"SERVICE_UNAVAILABLE", resp.body)

        with self.engine.connect() as conn:
            preview_count = conn.execute(
                text("SELECT COUNT(*) FROM configuration_changes")
            ).scalar()
            term_count = conn.execute(text("SELECT COUNT(*) FROM terms")).scalar()
            rev_count = conn.execute(
                text("SELECT COUNT(*) FROM calendar_revisions")
            ).scalar()
        self.assertEqual(preview_count, 0)
        self.assertEqual(term_count, 0)
        self.assertEqual(rev_count, 0)

    # -- B: term update preserves in-range days -----------------------------

    def test_term_expand_keeps_old_defaults_and_exceptions(self):
        # Old range 09-01..09-15: 09-05 is a workday by default.
        self._install_provider({date(2026, 9, 5)})
        term = self._create_term("2026秋", "2026-09-01", "2026-09-15")

        # Make 09-05 a non-teaching exception.
        settings = self._school_settings()
        override = self._preview(
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
        self.assertEqual(override.status, 201, override.body)
        self._apply(override.json()["id"])

        # New library version for expanded dates.
        self._install_provider(
            {date(2026, 9, 10), date(2026, 9, 20)}, {2026}
        )
        term = self._term(term["id"])
        settings = self._school_settings()
        expand = self._preview(
            {
                "kind": "term_update",
                "target_id": term["id"],
                "end_date": "2026-09-30",
                "expected_version": term["version"],
                "expected_schedule_version": settings["schedule_version"],
            }
        )
        self.assertEqual(expand.status, 201, expand.body)
        self._apply(expand.json()["id"])

        cal = self._read_calendar("2026-09-01", "2026-09-30")
        by_date = {item["date"]: item for item in cal["items"]}
        # Old range keeps the exception and old defaults.
        self.assertEqual(by_date["2026-09-05"]["effective_state"], "non_teaching")
        self.assertEqual(by_date["2026-09-05"]["source"], "admin_exception")
        # A date in the old range keeps the old default (non-teaching here).
        self.assertEqual(by_date["2026-09-10"]["effective_state"], "non_teaching")
        # New dates use the new library input.
        self.assertEqual(by_date["2026-09-20"]["effective_state"], "teaching")

    def test_term_shrink_lists_removed_exceptions_and_keeps_old_revision(self):
        workdays = {date(2026, 9, d) for d in range(1, 31)}
        self._install_provider(workdays)
        term = self._create_term("2026秋", "2026-09-01", "2026-09-30")

        settings = self._school_settings()
        override = self._preview(
            {
                "kind": "calendar_override",
                "target_id": term["id"],
                "expected_term_version": term["version"],
                "expected_calendar_revision_id": term["calendar_revision_id"],
                "expected_schedule_version": settings["schedule_version"],
                "dates": [
                    {
                        "date": "2026-09-20",
                        "state": "non_teaching",
                        "reason": "活动",
                    }
                ],
            }
        )
        self._apply(override.json()["id"])
        term = self._term(term["id"])
        old_revision_id = term["calendar_revision_id"]

        settings = self._school_settings()
        shrink = self._preview(
            {
                "kind": "term_update",
                "target_id": term["id"],
                "end_date": "2026-09-15",
                "expected_version": term["version"],
                "expected_schedule_version": settings["schedule_version"],
            }
        )
        self.assertEqual(shrink.status, 201, shrink.body)
        preview = shrink.json()
        self.assertIn("2026-09-20", preview["impact"]["removed_override_dates"])
        self._apply(preview["id"])

        # Old revision is still complete (all 30 days including the exception).
        with self.engine.connect() as conn:
            old_day_count = conn.execute(
                text(
                    "SELECT COUNT(*) FROM calendar_days WHERE revision_id = :rev"
                ),
                {"rev": old_revision_id},
            ).scalar()
            old_exception = conn.execute(
                text(
                    "SELECT effective_state FROM calendar_days "
                    "WHERE revision_id = :rev AND date = '2026-09-20'"
                ),
                {"rev": old_revision_id},
            ).scalar()
        self.assertEqual(old_day_count, 30)
        self.assertEqual(old_exception, "non_teaching")

        # New revision only covers the shrunk range.
        new_term = self._term(term["id"])
        new_revision_id = new_term["calendar_revision_id"]
        self.assertNotEqual(new_revision_id, old_revision_id)
        with self.engine.connect() as conn:
            new_day_count = conn.execute(
                text(
                    "SELECT COUNT(*) FROM calendar_days WHERE revision_id = :rev"
                ),
                {"rev": new_revision_id},
            ).scalar()
        self.assertEqual(new_day_count, 15)

    def test_term_start_move_updates_week_number(self):
        workdays = {date(2026, 9, d) for d in range(1, 31)}
        self._install_provider(workdays)
        term = self._create_term("2026秋", "2026-09-01", "2026-09-30")

        term = self._term(term["id"])
        settings = self._school_settings()
        move = self._preview(
            {
                "kind": "term_update",
                "target_id": term["id"],
                "start_date": "2026-09-07",
                "expected_version": term["version"],
                "expected_schedule_version": settings["schedule_version"],
            }
        )
        self.assertEqual(move.status, 201, move.body)
        preview = move.json()
        week_shift = preview["impact"]["week_shift_count"]
        self.assertGreater(week_shift, 0)
        self._apply(preview["id"])

        # With start on 2026-09-07 (Monday), 2026-09-07 itself is week 1.
        cal = self._read_calendar("2026-09-07", "2026-09-14")
        by_date = {item["date"]: item for item in cal["items"]}
        self.assertEqual(by_date["2026-09-07"]["week_number"], 1)
        self.assertEqual(by_date["2026-09-13"]["week_number"], 1)
        self.assertEqual(by_date["2026-09-14"]["week_number"], 2)

    # -- C: preview expiry and password-reset/assignment race ----------------

    def test_preview_expired_returns_409_and_writes_nothing(self):
        settings = self._school_settings()
        preview = self._preview(
            {
                "kind": "school_update",
                "school_name": "新园名",
                "expected_version": settings["version"],
            }
        )
        self.assertEqual(preview.status, 201, preview.body)
        preview_id = preview.json()["id"]

        # Roll the expiration back in the database.
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE configuration_changes SET expires_at = :past "
                    "WHERE id = :id"
                ),
                {"past": datetime(2000, 1, 1, 0, 0, 0), "id": preview_id},
            )

        applied = self._apply(preview_id)
        self.assertEqual(applied.status, 409, applied.body)
        self.assertIn(b"PREVIEW_EXPIRED", applied.body)

        # School settings are unchanged and no operation record was written.
        settings = self._school_settings()
        self.assertIsNone(settings["school_name"])
        with self.engine.connect() as conn:
            audit_count = conn.execute(
                text(
                    "SELECT COUNT(*) FROM operation_records WHERE action = 'school_update'"
                )
            ).scalar()
            applied_count = conn.execute(
                text(
                    "SELECT COUNT(*) FROM configuration_changes "
                    "WHERE id = :id AND status = 'applied'"
                ),
                {"id": preview_id},
            ).scalar()
        self.assertEqual(audit_count, 0)
        self.assertEqual(applied_count, 0)

    def test_password_reset_and_assignment_race(self):
        class_a = self._create_class("小一班", "small")
        teachers = self.client.request(
            "GET",
            "/api/admin/teachers?assignment_status=pending_assignment",
        ).json()
        target = next(
            t for t in teachers["items"] if t["username"] == "teacher_one"
        )

        with self.engine.connect() as conn:
            baseline = conn.execute(
                text("SELECT version, auth_version FROM accounts WHERE id = :id"),
                {"id": target["id"]},
            ).fetchone()

        unclaim_first_admin(self.engine)
        other_client = AsgiClient()
        _, other_admin_cookie = register_and_login(other_client, "admin_b")

        barrier = threading.Barrier(2)
        results: list[tuple[str, int]] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def reset_worker():
            client = AsgiClient()
            client.cookies = self.admin_cookie.copy()
            barrier.wait(timeout=5)
            resp = client.request(
                "POST",
                f"/api/admin/teachers/{target['id']}/password-reset",
                headers=HEADERS,
                body=_json_body(
                    {
                        "new_password": "newpass123456",
                        "expected_version": baseline.version,
                    }
                ),
            )
            with lock:
                results.append(("reset", resp.status))

        def assign_worker():
            client = AsgiClient()
            client.cookies = other_admin_cookie.copy()
            barrier.wait(timeout=5)
            resp = client.request(
                "POST",
                f"/api/admin/teachers/{target['id']}/assignment",
                headers=HEADERS,
                body=_json_body(
                    {
                        "class_id": class_a["id"],
                        "expected_version": baseline.version,
                        "expected_class_version": class_a["version"],
                    }
                ),
            )
            with lock:
                results.append(("assign", resp.status))

        def capture_errors(fn):
            def wrapper():
                try:
                    fn()
                except Exception as exc:
                    with lock:
                        errors.append(exc)
            return wrapper

        t1 = threading.Thread(target=capture_errors(reset_worker))
        t2 = threading.Thread(target=capture_errors(assign_worker))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        self.assertEqual(errors, [])
        self.assertFalse(t1.is_alive())
        self.assertFalse(t2.is_alive())
        self.assertEqual(len(results), 2, f"results={results}")
        statuses = {name: status for name, status in results}
        self.assertIn("reset", statuses)
        self.assertIn("assign", statuses)
        self.assertTrue(
            (statuses["reset"] == 200 and statuses["assign"] == 409)
            or (statuses["reset"] == 409 and statuses["assign"] == 200),
            f"results={results}",
        )

        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT version, auth_version FROM accounts WHERE id = :id"),
                {"id": target["id"]},
            ).fetchone()

        if statuses["reset"] == 200:
            # Password reset bumps both versions and revokes sessions.
            self.assertGreater(row.version, baseline.version)
            self.assertGreater(row.auth_version, baseline.auth_version)
            self._as(self.teacher_cookie)
            me = self.client.request("GET", "/api/auth/me")
            self.assertEqual(me.status, 401, me.body)
        else:
            # Assignment only bumps the account version.
            self.assertGreater(row.version, baseline.version)
            self.assertEqual(row.auth_version, baseline.auth_version)
            self._as(self.teacher_cookie)
            me = self.client.request("GET", "/api/auth/me")
            self.assertEqual(me.status, 200, me.body)

    # -- D: subprocess restart reads persisted calendar ----------------------

    def test_subprocess_restart_reads_same_calendar_without_provider(self):
        workdays = {date(2026, 9, d) for d in range(1, 31)}
        self._install_provider(workdays)
        term = self._create_term("2026秋", "2026-09-01", "2026-09-30")

        main_cal = self._read_calendar("2026-09-01", "2026-09-30")
        main_revision = main_cal["items"][0]["calendar_revision_id"]

        script = (
            "import json, os\n"
            "os.environ['APP_DISABLE_DOTENV'] = '1'\n"
            "from app.services import calendar_service\n"
            "calendar_service.register_provider("
            "type('P', (), {'version': 'raising', "
            "'is_workday': staticmethod(lambda d: (_ for _ in ()).throw(RuntimeError('no provider')))})(), "
            "'raising')\n"
            "from tests.integration.test_identity import AsgiClient\n"
            "from tests.integration.i2_guard import HEADERS\n"
            "client = AsgiClient()\n"
            "client.cookies = json.loads(os.environ['_TEST_COOKIE'])\n"
            "resp = client.request('GET', '/api/admin/calendar?from=2026-09-01&to=2026-09-30')\n"
            "print(json.dumps({'status': resp.status, 'body': resp.body.decode('utf-8')}))\n"
        )
        env = os.environ.copy()
        env["DATABASE_URL"] = os.environ["DATABASE_URL"]
        env["_TEST_COOKIE"] = json.dumps(self.admin_cookie)

        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, f"stderr={result.stderr}")
        output = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(output["status"], 200, output["body"])
        sub_cal = json.loads(output["body"])
        sub_revision = sub_cal["items"][0]["calendar_revision_id"]
        self.assertEqual(sub_revision, main_revision)
        self.assertEqual(
            {item["date"]: item["effective_state"] for item in sub_cal["items"]},
            {item["date"]: item["effective_state"] for item in main_cal["items"]},
        )

    # -- E: plans_started_at gate --------------------------------------------

    def test_after_plans_started_new_non_overlapping_term_allowed(self):
        workdays = {date(2026, 9, d) for d in range(1, 31)}
        self._install_provider(workdays)
        self._create_term("2026秋", "2026-09-01", "2026-09-30")

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE school_settings SET plans_started_at = UTC_TIMESTAMP()"
                )
            )

        settings = self._school_settings()
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
        self._apply(resp.json()["id"])
        terms = self.client.request("GET", "/api/admin/terms").json()["items"]
        self.assertEqual(len(terms), 2)

    def test_after_plans_started_existing_term_changes_blocked(self):
        workdays = {date(2026, 9, d) for d in range(1, 31)}
        self._install_provider(workdays)
        term = self._create_term("2026秋", "2026-09-01", "2026-09-30")

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE school_settings SET plans_started_at = UTC_TIMESTAMP()"
                )
            )

        settings = self._school_settings()

        # term_update
        update = self._preview(
            {
                "kind": "term_update",
                "target_id": term["id"],
                "name": "改名",
                "expected_version": term["version"],
                "expected_schedule_version": settings["schedule_version"],
            }
        )
        self.assertEqual(update.status, 201, update.body)
        applied = self._apply(update.json()["id"])
        self.assertEqual(applied.status, 409, applied.body)
        self.assertIn(b"DEPENDENCY_NOT_READY", applied.body)

        # calendar_override
        override = self._preview(
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
        self.assertEqual(override.status, 201, override.body)
        applied = self._apply(override.json()["id"])
        self.assertEqual(applied.status, 409, applied.body)
        self.assertIn(b"DEPENDENCY_NOT_READY", applied.body)

        # calendar_reimport with a different library version so changes exist.
        calendar_service.register_provider(
            _FixtureProvider2(workdays - {date(2026, 9, 15)}, {2026}), "fixture-2"
        )
        reimport = self._preview(
            {
                "kind": "calendar_reimport",
                "target_id": term["id"],
                "expected_term_version": term["version"],
                "expected_calendar_revision_id": term["calendar_revision_id"],
                "expected_schedule_version": settings["schedule_version"],
            }
        )
        self.assertEqual(reimport.status, 201, reimport.body)
        applied = self._apply(reimport.json()["id"])
        self.assertEqual(applied.status, 409, applied.body)
        self.assertIn(b"DEPENDENCY_NOT_READY", applied.body)

        # No new revision was created.
        term = self._term(term["id"])
        self.assertEqual(term["version"], 1)
        with self.engine.connect() as conn:
            rev_count = conn.execute(
                text(
                    "SELECT COUNT(*) FROM calendar_revisions WHERE term_id = :id"
                ),
                {"id": term["id"]},
            ).scalar()
        self.assertEqual(rev_count, 1)

    def test_plans_started_between_preview_and_apply_blocks_apply(self):
        workdays = {date(2026, 9, d) for d in range(1, 31)}
        self._install_provider(workdays)
        term = self._create_term("2026秋", "2026-09-01", "2026-09-30")
        settings = self._school_settings()

        # Preview before plans start.
        preview = self._preview(
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
        self.assertEqual(preview.status, 201, preview.body)
        preview_id = preview.json()["id"]
        base_revision_id = preview.json()["base_versions"]["calendar_revision_id"]

        # Plans start before apply.
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE school_settings SET plans_started_at = UTC_TIMESTAMP()"
                )
            )

        applied = self._apply(preview_id)
        self.assertEqual(applied.status, 409, applied.body)
        self.assertIn(b"DEPENDENCY_NOT_READY", applied.body)

        # No override was written and term state is unchanged.
        cal = self._read_calendar("2026-09-10", "2026-09-10")
        self.assertEqual(cal["items"][0]["effective_state"], "teaching")
        term = self._term(term["id"])
        self.assertEqual(term["version"], 1)
        self.assertEqual(term["calendar_revision_id"], base_revision_id)

    def _install_provider(self, workdays: set[date], covered_years: set[int] | None = None):
        provider = _DeterministicProvider(workdays, covered_years)
        calendar_service.register_provider(provider, "fixture-1")


if __name__ == "__main__":
    unittest.main()
