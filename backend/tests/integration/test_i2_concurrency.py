"""I2 concurrency and database-constraint tests.

These tests require an isolated MySQL 8.4 / InnoDB database with the I2
migrations applied. They use real concurrent requests against the ASGI app;
static reads are not used as evidence for concurrency.
"""

from __future__ import annotations

import os
import threading
import unittest
from datetime import date

os.environ["APP_DISABLE_DOTENV"] = "1"

from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import IntegrityError, OperationalError  # noqa: E402

from app.services import calendar_service  # noqa: E402
from app.services import config_effect_term  # noqa: E402
from unittest import mock  # noqa: E402

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


class _WorkdayProvider:
    version = "fixture-1"

    def __init__(self, workdays: set[date]):
        self.workdays = workdays
        self.covered_years = {d.year for d in workdays}

    def is_workday(self, day: date) -> bool:
        if day.year not in self.covered_years:
            raise NotImplementedError(f"year {day.year} not covered")
        return day in self.workdays


@skip_unless_enabled
class I2ConcurrencyTests(unittest.TestCase):
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
        workdays = {date.fromisoformat(start)}
        calendar_service.register_provider(_WorkdayProvider(workdays), "fixture-1")
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
        calendar_service.reset_provider()
        detail = self.client.request("GET", f"/api/admin/terms/{target_id}")
        self.assertEqual(detail.status, 200, detail.body)
        result = detail.json()
        self.assertEqual(result["name"], name)
        return result

    # -- V3: first-assignment races ----------------------------------------

    def test_concurrent_assignment_to_different_classes_only_one_wins(self):
        class_a = self._create_class("小一班", "small")
        class_b = self._create_class("小二班", "small")
        self.assertNotEqual(class_a["id"], class_b["id"])

        teachers = self.client.request(
            "GET",
            "/api/admin/teachers?assignment_status=pending_assignment",
        ).json()
        target = next(
            t for t in teachers["items"] if t["username"] == "teacher_one"
        )

        # Use two independent admin login sessions; sharing one cookie would
        # serialize through the single session lock and hide real races.
        unclaim_first_admin(self.engine)
        other_client = AsgiClient()
        _, other_admin_cookie = register_and_login(other_client, "admin_b")

        barrier = threading.Barrier(2)
        results: list[tuple[int, bytes]] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def worker(class_id: str, class_version: int, cookie: dict[str, str]):
            try:
                client = AsgiClient()
                client.cookies = cookie.copy()
                barrier.wait(timeout=5)
                resp = client.request(
                    "POST",
                    f"/api/admin/teachers/{target['id']}/assignment",
                    headers=HEADERS,
                    body=_json_body(
                        {
                            "class_id": class_id,
                            "expected_version": target["version"],
                            "expected_class_version": class_version,
                        }
                    ),
                )
                with lock:
                    results.append((resp.status, resp.body))
            except Exception as exc:
                with lock:
                    errors.append(exc)

        t1 = threading.Thread(
            target=worker,
            args=(class_a["id"], class_a["version"], self.admin_cookie),
        )
        t2 = threading.Thread(
            target=worker,
            args=(class_b["id"], class_b["version"], other_admin_cookie),
        )
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        self.assertEqual(errors, [])
        self.assertFalse(t1.is_alive())
        self.assertFalse(t2.is_alive())
        self.assertEqual(len(results), 2, f"results={results}")
        successes = [r for r in results if r[0] == 200]
        failures = [r for r in results if r[0] != 200]
        self.assertEqual(len(successes), 1, f"results={results}")
        self.assertEqual(len(failures), 1, f"results={results}")
        self.assertIn(failures[0][0], (409,))

        # Exactly one assignment row exists.
        with self.engine.connect() as conn:
            count = conn.execute(
                text("SELECT COUNT(*) FROM teacher_assignments WHERE teacher_id = :tid"),
                {"tid": target["id"]},
            ).scalar()
            self.assertEqual(count, 1)

    def test_assignment_races_with_profile_update(self):
        class_a = self._create_class("小一班", "small")
        teachers = self.client.request(
            "GET",
            "/api/admin/teachers?assignment_status=pending_assignment",
        ).json()
        target = next(
            t for t in teachers["items"] if t["username"] == "teacher_one"
        )

        barrier = threading.Barrier(2)
        results: list[tuple[str, int]] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def assign_worker():
            client = AsgiClient()
            client.cookies = self.admin_cookie.copy()
            barrier.wait(timeout=5)
            resp = client.request(
                "POST",
                f"/api/admin/teachers/{target['id']}/assignment",
                headers=HEADERS,
                body=_json_body(
                    {
                        "class_id": class_a["id"],
                        "expected_version": target["version"],
                        "expected_class_version": class_a["version"],
                    }
                ),
            )
            with lock:
                results.append(("assign", resp.status))

        def profile_worker():
            client = AsgiClient()
            client.cookies = self.teacher_cookie.copy()
            barrier.wait(timeout=5)
            resp = client.request(
                "PATCH",
                "/api/settings/profile",
                headers=HEADERS,
                body=_json_body(
                    {"display_name": "张老师", "expected_version": target["version"]}
                ),
            )
            with lock:
                results.append(("profile", resp.status))

        def capture_errors(fn):
            def wrapper():
                try:
                    fn()
                except Exception as exc:
                    with lock:
                        errors.append(exc)
            return wrapper

        t1 = threading.Thread(target=capture_errors(assign_worker))
        t2 = threading.Thread(target=capture_errors(profile_worker))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        self.assertEqual(errors, [])
        self.assertFalse(t1.is_alive())
        self.assertFalse(t2.is_alive())
        self.assertEqual(len(results), 2, f"results={results}")
        statuses = {name: status for name, status in results}
        # One of them must win; the other sees a version conflict.
        self.assertIn("assign", statuses)
        self.assertIn("profile", statuses)
        self.assertTrue(
            (statuses["assign"] == 200 and statuses["profile"] == 409)
            or (statuses["assign"] == 409 and statuses["profile"] == 200),
            f"results={results}",
        )

    # -- V3 / V2: class-name uniqueness race --------------------------------

    def test_concurrent_class_create_same_name_only_one_succeeds(self):
        # Independent admin sessions: both have admin rights but different
        # accounts/sessions, so the race exercises the real DB constraint.
        unclaim_first_admin(self.engine)
        other_client = AsgiClient()
        _, other_admin_cookie = register_and_login(other_client, "admin_b")

        barrier = threading.Barrier(2)
        results: list[int] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def worker(cookie: dict[str, str]):
            client = AsgiClient()
            client.cookies = cookie.copy()
            barrier.wait(timeout=5)
            resp = client.request(
                "POST",
                "/api/admin/configuration-changes/preview",
                headers=HEADERS,
                body=_json_body(
                    {"kind": "class_create", "name": "小一班", "grade": "small"}
                ),
            )
            if resp.status == 201:
                preview_id = resp.json()["id"]
                apply_resp = client.request(
                    "POST",
                    f"/api/admin/configuration-changes/{preview_id}/apply",
                    headers=HEADERS,
                    body=_json_body({"confirm": True}),
                )
                with lock:
                    results.append(apply_resp.status)
            else:
                with lock:
                    results.append(resp.status)

        def capture_errors(fn, *args, **kwargs):
            def wrapper():
                try:
                    fn(*args, **kwargs)
                except Exception as exc:
                    with lock:
                        errors.append(exc)
            return wrapper

        t1 = threading.Thread(
            target=capture_errors(worker, self.admin_cookie)
        )
        t2 = threading.Thread(
            target=capture_errors(worker, other_admin_cookie)
        )
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        self.assertEqual(errors, [])
        self.assertFalse(t1.is_alive())
        self.assertFalse(t2.is_alive())
        self.assertEqual(len(results), 2, f"results={results}")
        self.assertEqual(results.count(200), 1, f"results={results}")
        self.assertEqual(results.count(409), 1, f"results={results}")

    # -- V5: concurrent term overlap apply ----------------------------------

    def test_concurrent_term_create_overlap_only_one_succeeds(self):
        workdays = {date(2026, 9, 1)}
        calendar_service.register_provider(_WorkdayProvider(workdays), "fixture-1")

        unclaim_first_admin(self.engine)
        other_client = AsgiClient()
        _, other_admin_cookie = register_and_login(other_client, "admin_b")

        barrier = threading.Barrier(2)
        results: list[int] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def worker(name: str, cookie: dict[str, str]):
            client = AsgiClient()
            client.cookies = cookie.copy()
            settings = client.request(
                "GET", "/api/admin/school-settings"
            ).json()
            barrier.wait(timeout=5)
            resp = client.request(
                "POST",
                "/api/admin/configuration-changes/preview",
                headers=HEADERS,
                body=_json_body(
                    {
                        "kind": "term_create",
                        "name": name,
                        "start_date": "2026-09-01",
                        "end_date": "2026-09-30",
                        "expected_schedule_version": settings["schedule_version"],
                    }
                ),
            )
            if resp.status == 201:
                preview_id = resp.json()["id"]
                apply_resp = client.request(
                    "POST",
                    f"/api/admin/configuration-changes/{preview_id}/apply",
                    headers=HEADERS,
                    body=_json_body({"confirm": True}),
                )
                with lock:
                    results.append(apply_resp.status)
            else:
                with lock:
                    results.append(resp.status)

        def capture_errors(fn, *args, **kwargs):
            def wrapper():
                try:
                    fn(*args, **kwargs)
                except Exception as exc:
                    with lock:
                        errors.append(exc)
            return wrapper

        t1 = threading.Thread(
            target=capture_errors(worker, "2026秋A", self.admin_cookie)
        )
        t2 = threading.Thread(
            target=capture_errors(worker, "2026秋B", other_admin_cookie)
        )
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        calendar_service.reset_provider()
        self.assertEqual(errors, [])
        self.assertFalse(t1.is_alive())
        self.assertFalse(t2.is_alive())
        self.assertEqual(len(results), 2, f"results={results}")
        self.assertEqual(results.count(200), 1, f"results={results}")
        self.assertEqual(results.count(409), 1, f"results={results}")

        with self.engine.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM terms")).scalar()
            self.assertEqual(count, 1)

    # -- V10: preview staleness on member change / expiry / idempotency -----

    def test_preview_stale_after_teacher_assigned(self):
        class_a = self._create_class("小一班", "small")
        settings = self.client.request(
            "GET", "/api/admin/school-settings"
        ).json()
        preview = self.client.request(
            "POST",
            "/api/admin/configuration-changes/preview",
            headers=HEADERS,
            body=_json_body(
                {
                    "kind": "school_update",
                    "school_name": "新园名",
                    "expected_version": settings["version"],
                }
            ),
        )
        self.assertEqual(preview.status, 201, preview.body)
        preview_id = preview.json()["id"]

        # A teacher assignment changes the member_summary baseline.
        teachers = self.client.request(
            "GET",
            "/api/admin/teachers?assignment_status=pending_assignment",
        ).json()
        target = next(
            t for t in teachers["items"] if t["username"] == "teacher_one"
        )
        resp = self.client.request(
            "POST",
            f"/api/admin/teachers/{target['id']}/assignment",
            headers=HEADERS,
            body=_json_body(
                {
                    "class_id": class_a["id"],
                    "expected_version": target["version"],
                    "expected_class_version": class_a["version"],
                }
            ),
        )
        self.assertEqual(resp.status, 200, resp.body)

        apply_resp = self.client.request(
            "POST",
            f"/api/admin/configuration-changes/{preview_id}/apply",
            headers=HEADERS,
            body=_json_body({"confirm": True}),
        )
        self.assertEqual(apply_resp.status, 409)
        self.assertIn(b"PREVIEW_STALE", apply_resp.body)

    def test_applied_preview_is_idempotent(self):
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
                    "kind": "school_update",
                    "school_name": "阳光幼儿园",
                    "expected_version": settings["version"],
                }
            ),
        )
        self.assertEqual(preview.status, 201, preview.body)
        preview_id = preview.json()["id"]

        first = self.client.request(
            "POST",
            f"/api/admin/configuration-changes/{preview_id}/apply",
            headers=HEADERS,
            body=_json_body({"confirm": True}),
        )
        self.assertEqual(first.status, 200, first.body)
        first_versions = first.json()["versions"]

        second = self.client.request(
            "POST",
            f"/api/admin/configuration-changes/{preview_id}/apply",
            headers=HEADERS,
            body=_json_body({"confirm": True}),
        )
        self.assertEqual(second.status, 200, second.body)
        self.assertEqual(second.json()["versions"], first_versions)

        settings = self.client.request(
            "GET", "/api/admin/school-settings"
        ).json()
        self.assertEqual(settings["version"], 2)

    # -- V11: assignment rollback on real MySQL error ------------------------

    def test_assignment_rolls_back_on_mysql_error(self):
        from app.services import auth_service

        class_a = self._create_class("小一班", "small")
        teachers = self.client.request(
            "GET",
            "/api/admin/teachers?assignment_status=pending_assignment",
        ).json()
        target = next(
            t for t in teachers["items"] if t["username"] == "teacher_one"
        )

        original = auth_service.record_operation

        def failing_record(db, *, operator_id, operator_type, action, **kwargs):
            original(
                db,
                operator_id=operator_id,
                operator_type=operator_type,
                action=action,
                **kwargs,
            )
            db.flush()
            from sqlalchemy import text
            db.execute(text("INSERT INTO kg_i2_missing_table (id) VALUES ('x')"))

        try:
            auth_service.record_operation = failing_record
            resp = self.client.request(
                "POST",
                f"/api/admin/teachers/{target['id']}/assignment",
                headers=HEADERS,
                body=_json_body(
                    {
                        "class_id": class_a["id"],
                        "expected_version": target["version"],
                        "expected_class_version": class_a["version"],
                    }
                ),
            )
        finally:
            auth_service.record_operation = original

        self.assertEqual(resp.status, 503, resp.body)

        # Independent connection verifies complete rollback.
        with self.engine.connect() as conn:
            assign_count = conn.execute(
                text(
                    "SELECT COUNT(*) FROM teacher_assignments WHERE teacher_id = :tid"
                ),
                {"tid": target["id"]},
            ).scalar()
            self.assertEqual(assign_count, 0)

            version = conn.execute(
                text("SELECT version FROM accounts WHERE id = :id"),
                {"id": target["id"]},
            ).scalar()
            self.assertEqual(version, target["version"])

            audit_count = conn.execute(
                text("SELECT COUNT(*) FROM operation_records WHERE action = 'assign_teacher'")
            ).scalar()
            self.assertEqual(audit_count, 0)

    # -- V12: read/write concurrency and persistence -------------------------

    def test_calendar_read_does_not_mix_revisions_during_apply(self):
        workdays = {date(2026, 9, d) for d in range(1, 31)}
        calendar_service.register_provider(_WorkdayProvider(workdays), "fixture-1")
        term = self._create_term("2026秋", "2026-09-01", "2026-09-30")
        old_revision_id = term["calendar_revision_id"]
        settings = self.client.request(
            "GET", "/api/admin/school-settings"
        ).json()

        preview = self.client.request(
            "POST",
            "/api/admin/configuration-changes/preview",
            headers=HEADERS,
            body=_json_body(
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
            ),
        )
        self.assertEqual(preview.status, 201, preview.body)
        preview_id = preview.json()["id"]

        # Patch the in-transaction calendar effect so the writer pauses after
        # flushing the new revision but before committing. Reads during the
        # pause must see only the old complete revision; after release they
        # see only the new complete revision.
        reached = threading.Event()
        release = threading.Event()
        reader_started = threading.Event()
        from app.services import config_apply_pipeline

        original = config_apply_pipeline.new_calendar_revision

        def blocking_new_calendar_revision(db, preview, school, *, now, operator_id, change_id):
            result = original(
                db, preview, school,
                now=now, operator_id=operator_id, change_id=change_id,
            )
            db.flush()
            reached.set()
            release.wait(timeout=10)
            return result

        read_revision_ids: list[set[str]] = []
        read_errors: list[tuple[int, bytes]] = []
        writer_result: list[tuple[int, bytes]] = []
        lock = threading.Lock()

        def reader():
            client = AsgiClient()
            client.cookies = self.admin_cookie.copy()
            while True:
                resp = client.request(
                    "GET", "/api/admin/calendar?from=2026-09-01&to=2026-09-30"
                )
                if resp.status == 200:
                    items = resp.json()["items"]
                    with lock:
                        read_revision_ids.append(
                            {item["calendar_revision_id"] for item in items}
                        )
                    reader_started.set()
                else:
                    with lock:
                        read_errors.append((resp.status, resp.body))
                if release.is_set():
                    break

        def writer():
            client = AsgiClient()
            client.cookies = self.admin_cookie.copy()
            with mock.patch.object(
                config_apply_pipeline, "new_calendar_revision", blocking_new_calendar_revision
            ):
                resp = client.request(
                    "POST",
                    f"/api/admin/configuration-changes/{preview_id}/apply",
                    headers=HEADERS,
                    body=_json_body({"confirm": True}),
                )
            with lock:
                writer_result.append((resp.status, resp.body))

        def capture_errors(fn, *args, **kwargs):
            def wrapper():
                try:
                    fn(*args, **kwargs)
                except Exception as exc:
                    with lock:
                        read_errors.append((0, str(exc).encode()))
            return wrapper

        t_reader = threading.Thread(target=capture_errors(reader))
        t_writer = threading.Thread(target=capture_errors(writer))
        t_reader.start()
        t_writer.start()

        try:
            self.assertTrue(
                reached.wait(timeout=10),
                "writer did not reach the mid-transaction hold point",
            )
            self.assertTrue(
                reader_started.wait(timeout=10),
                "reader did not produce at least one successful response while held",
            )
        finally:
            release.set()

        t_reader.join(timeout=15)
        t_writer.join(timeout=15)

        calendar_service.reset_provider()
        self.assertFalse(t_reader.is_alive())
        self.assertFalse(t_writer.is_alive())
        self.assertEqual(read_errors, [])
        self.assertEqual(len(writer_result), 1, f"writer_result={writer_result}")
        self.assertEqual(writer_result[0][0], 200, writer_result[0][1])

        # Every successful response must contain exactly one revision id.
        self.assertGreater(len(read_revision_ids), 0)
        for rev_ids in read_revision_ids:
            self.assertEqual(len(rev_ids), 1, f"mixed revisions: {rev_ids}")

        # Final state is the new revision.
        final = self.client.request(
            "GET", f"/api/admin/terms/{term['id']}"
        ).json()
        new_revision_id = final["calendar_revision_id"]
        self.assertNotEqual(new_revision_id, old_revision_id)

        # Every observed revision id is either the old or the new complete
        # revision; no partial/mixed snapshot was ever returned.
        observed = set().union(*read_revision_ids)
        self.assertTrue(
            observed.issubset({old_revision_id, new_revision_id}),
            f"unexpected revision set: {observed}",
        )

        final_cal = self.client.request(
            "GET", "/api/admin/calendar?from=2026-09-10&to=2026-09-10"
        ).json()
        self.assertEqual(
            final_cal["items"][0]["calendar_revision_id"],
            new_revision_id,
        )
        self.assertEqual(final_cal["items"][0]["effective_state"], "non_teaching")

    # -- Database constraints ------------------------------------------------

    @staticmethod
    def _mysql_code(exc: Exception) -> int | None:
        orig = getattr(exc, "orig", None)
        args = getattr(orig, "args", ())
        if args and isinstance(args[0], int):
            return args[0]
        return None

    def test_composite_fk_rejects_cross_term_revision_pointer(self):
        term1 = self._create_term("2026秋", "2026-09-01", "2026-09-15")
        term2 = self._create_term("2026冬", "2026-10-01", "2026-10-15")
        self.assertNotEqual(term1["id"], term2["id"])

        with self.engine.connect() as conn:
            rev1_id = conn.execute(
                text("SELECT id FROM calendar_revisions WHERE term_id = :id"),
                {"id": term1["id"]},
            ).scalar()
        self.assertIsNotNone(rev1_id)

        with self.assertRaises(IntegrityError) as ctx:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE terms SET current_calendar_revision_id = :rev "
                        "WHERE id = :tid"
                    ),
                    {"rev": rev1_id, "tid": term2["id"]},
                )
        self.assertEqual(self._mysql_code(ctx.exception), 1452)

    def test_unique_class_name_rejected_at_database(self):
        created = self._create_class("小一班", "small")
        self.assertIsNotNone(created["id"])

        with self.assertRaises(IntegrityError) as ctx:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO classes (id, name, grade, header_teacher_names, "
                        "version, created_at, updated_at) "
                        "VALUES (:id, '小一班', 'small', '[]', 1, NOW(), NOW())"
                    ),
                    {"id": "duplicateid"},
                )
        self.assertEqual(self._mysql_code(ctx.exception), 1062)

    def test_check_constraints_reject_invalid_states(self):
        # Invalid grade: each assertion runs in its own transaction so a
        # failure rolls back cleanly and does not close a reused connection.
        with self.assertRaises(OperationalError) as ctx:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO classes (id, name, grade, header_teacher_names, "
                        "version, created_at, updated_at) "
                        "VALUES (:id, 'x', 'baby', '[]', 1, NOW(), NOW())"
                    ),
                    {"id": "badgrade"},
                )
        self.assertEqual(self._mysql_code(ctx.exception), 3819)

        # Effective state must equal COALESCE(override_state, base_state).
        # Update an existing calendar day (the row already covers the date)
        # so the failure proves the CHECK constraint, not the PK.
        term = self._create_term("2026秋", "2026-09-01", "2026-09-02")
        with self.engine.connect() as conn:
            rev_id = conn.execute(
                text("SELECT id FROM calendar_revisions WHERE term_id = :id"),
                {"id": term["id"]},
            ).scalar()
        self.assertIsNotNone(rev_id)

        with self.assertRaises(OperationalError) as ctx:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE calendar_days SET effective_state = 'non_teaching' "
                        "WHERE revision_id = :rev AND date = :day"
                    ),
                    {"rev": rev_id, "day": date(2026, 9, 1)},
                )
        self.assertEqual(self._mysql_code(ctx.exception), 3819)


if __name__ == "__main__":
    unittest.main()
