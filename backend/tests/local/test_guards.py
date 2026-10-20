"""Session/Host/Origin guards, docs off, forged fields and legacy isolation.

The local API must be usable only from the single launch's loopback
origin with the in-memory session token; ownership is always server
derived; and importing the local package must not load legacy settings,
dotenv or MySQL drivers.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest

from tests.local.support import (
    BACKEND_DIR,
    LocalTestCase,
    StaticCalendarProvider,
    calendar_provider,
    execute_sql,
    initialize_body,
    worker_env,
)


class GuardTests(LocalTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(calendar_provider(StaticCalendarProvider()))
        self.server = self.start_server()
        self.client = self.server.client()

    def test_health_without_session_and_public_docs_disabled(self):
        status, payload = self.client.get("/api/local/health", token=None, origin=None)
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload, {"status": "ok"})
        status, payload = self.client.get("/api/local/health", token="wrong")
        self.assertEqual(status, 200)
        for path in ("/docs", "/redoc", "/openapi.json"):
            with self.subTest(path=path):
                status, payload = self.client.get(path)
                self.assertEqual(status, 404, path)

    def test_application_session_required_for_everything_else(self):
        paths = [
            "/api/local/context",
            "/api/local/calendar?from=2026-09-01&to=2026-09-02",
            "/api/daily-plans?from=2026-09-01&to=2026-09-30",
            "/api/daily-plans/by-date?date=2026-09-01",
            "/api/daily-plans/some-plan-id",
        ]
        for path in paths:
            for token in (None, "wrong-token"):
                with self.subTest(path=path, token=token):
                    status, payload = self.client.get(path, token=token)
                    self.assertEqual(status, 401, payload)
                    self.assertEqual(
                        payload["error"]["code"], "APP_SESSION_REQUIRED"
                    )
        status, payload = self.client.post(
            "/api/local/initialize", initialize_body(), token=None
        )
        self.assertEqual(status, 401)
        self.assertEqual(payload["error"]["code"], "APP_SESSION_REQUIRED")

    def test_origin_required_for_mutations_only(self):
        status, payload = self.client.get("/api/local/context", origin=None)
        self.assertEqual(status, 200, payload)

        status, payload = self.client.post(
            "/api/local/initialize", initialize_body(), origin=None
        )
        self.assertEqual(status, 403, payload)
        self.assertEqual(payload["error"]["code"], "FORBIDDEN_ORIGIN")

        status, payload = self.client.post(
            "/api/local/initialize",
            initialize_body(),
            origin="http://evil.example",
        )
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"]["code"], "FORBIDDEN_ORIGIN")

    def test_untrusted_host_is_rejected(self):
        for host in ("localhost:1234", "127.0.0.1", "127.0.0.1:1"):
            with self.subTest(host=host):
                status, payload = self.client.get(
                    "/api/local/context", host=host
                )
                self.assertEqual(status, 403, payload)
                self.assertEqual(payload["error"]["code"], "FORBIDDEN_HOST")

    def test_error_envelopes_for_unknown_routes_and_methods(self):
        status, payload = self.client.get("/api/unknown-route")
        self.assertEqual(status, 404, payload)
        self.assertEqual(payload["error"]["code"], "NOT_FOUND")
        # POST on a GET-only route: Origin is valid, method is not.
        status, payload = self.client.post("/api/local/context")
        self.assertEqual(status, 405, payload)
        self.assertEqual(payload["error"]["code"], "METHOD_NOT_ALLOWED")

    def test_profile_required_codes_before_initialization(self):
        for path in (
            "/api/local/calendar?from=2026-09-01&to=2026-09-02",
            "/api/daily-plans?from=2026-09-01&to=2026-09-30",
            "/api/daily-plans/by-date?date=2026-09-01",
            "/api/daily-plans/some-plan-id",
        ):
            with self.subTest(path=path):
                status, payload = self.client.get(path)
                self.assertEqual(status, 409, payload)
                self.assertEqual(
                    payload["error"]["code"], "LOCAL_PROFILE_REQUIRED"
                )
        for method, path, body in (
            ("POST", "/api/daily-plans", {"plan_date": "2026-09-01"}),
            ("PATCH", "/api/daily-plans/some-plan-id", {"expected_content_version": 1}),
        ):
            with self.subTest(method=method):
                status, payload = self.client.request(method, path, body)
                self.assertEqual(status, 409, payload)
                self.assertEqual(
                    payload["error"]["code"], "LOCAL_PROFILE_REQUIRED"
                )
        status, payload = self.client.get("/api/local/context")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "uninitialized")

    def test_ownership_and_forged_fields_rejected(self):
        for field in ("class_id", "term_id", "creator_id", "split_baseline"):
            with self.subTest(field=field):
                status, payload = self.client.post(
                    "/api/local/initialize",
                    initialize_body(**{field: "forged"}),
                )
                self.assertEqual(status, 422, payload)
                self.assertEqual(payload["error"]["code"], "VALIDATION_ERROR")

        self.initialize(self.client)
        for field in ("class_id", "term_id", "creator_id", "split_baseline"):
            with self.subTest(create_field=field):
                body = {"plan_date": "2026-09-01", field: "forged"}
                status, payload = self.client.post("/api/daily-plans", body)
                self.assertEqual(status, 422, payload)
                self.assertEqual(payload["error"]["code"], "VALIDATION_ERROR")

        _, plan = self.client.post("/api/daily-plans", {"plan_date": "2026-09-01"})
        for field in ("class_id", "term_id", "creator_id", "split_baseline"):
            with self.subTest(patch_field=field):
                status, payload = self.client.patch(
                    f"/api/daily-plans/{plan['id']}",
                    {"expected_content_version": 1, field: "forged"},
                )
                self.assertEqual(status, 422, payload)

        # Ownership query parameters are rejected on reads as well.
        for path in (
            "/api/daily-plans?from=2026-09-01&to=2026-09-30&class_id=x",
            "/api/daily-plans/by-date?date=2026-09-01&term_id=x",
            f"/api/daily-plans/{plan['id']}?creator_id=x",
        ):
            with self.subTest(read_path=path):
                status, payload = self.client.get(path)
                self.assertEqual(status, 422, payload)
                self.assertEqual(payload["error"]["code"], "VALIDATION_ERROR")

    def test_errors_do_not_leak_token_paths_or_sql(self):
        status, payload = self.client.get("/api/daily-plans/nope")
        body = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn(self.token, body)
        self.assertNotIn(str(self.data_dir), body)
        self.assertNotIn("SELECT", body.upper())

        # A real storage failure also stays generic.
        self.initialize(self.client)
        execute_sql(
            self.server.runtime.db_path,
            "CREATE TRIGGER leak_probe BEFORE INSERT ON local_operation_records "
            "BEGIN SELECT RAISE(ABORT, 'secret sql detail'); END",
        )
        try:
            status, payload = self.client.post(
                "/api/daily-plans", {"plan_date": "2026-09-01"}
            )
        finally:
            execute_sql(
                self.server.runtime.db_path,
                "DROP TRIGGER IF EXISTS leak_probe",
            )
        self.assertEqual(status, 503, payload)
        body = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("secret sql detail", body)
        self.assertNotIn(str(self.data_dir), body)

    def test_engine_is_sqlite_and_core_api_succeeds(self):
        self.assertEqual(
            self.server.runtime.engine.url.drivername, "sqlite+pysqlite"
        )
        status, payload = self.client.get("/api/local/context")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "uninitialized")
        status, payload = self.client.post(
            "/api/local/initialize", initialize_body()
        )
        self.assertEqual(status, 201, payload)
        status, calendar = self.client.get(
            "/api/local/calendar?from=2026-09-01&to=2026-09-02"
        )
        self.assertEqual(status, 200)

    def test_local_package_import_is_isolated_from_legacy_configuration(self):
        banned = (
            "app.config",
            "app.security",
            "app.database",
            "app.models",
            "app.main",
            "app.deps",
            "pymysql",
            "dotenv",
            "pydantic_settings",
        )
        script = (
            "import sys\n"
            "import app.local.app\n"
            "import app.services.daily_plan_content\n"
            f"banned = [name for name in {banned!r} if name in sys.modules]\n"
            "print(','.join(banned))\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(BACKEND_DIR),
            env=worker_env(),
            capture_output=True,
            timeout=120,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stderr.decode("utf-8", "replace"),
        )
        self.assertEqual(completed.stdout.decode("utf-8").strip(), "")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
