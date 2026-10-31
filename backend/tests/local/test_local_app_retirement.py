"""A restored launch never accepts the previous launch's HTTP session token.

The host creates a new local app (new token, new session scope, new page
ticket) after a restore.  These checks use two real loopback servers on the
same synthetic runtime: the old token must answer 401 on the new server and
the old server must never accept the new token.  No restore package or UI is
involved; this pins the request-retirement seam the host relies on.
"""

from __future__ import annotations

import secrets
import unittest

from tests.local.support import LocalServer, LocalTestCase


class LocalAppRetirementTest(LocalTestCase):
    def test_new_app_token_is_required_and_old_token_is_refused(self):
        runtime = self.make_runtime()
        old_token = secrets.token_urlsafe(32)
        new_token = secrets.token_urlsafe(32)
        old = LocalServer(runtime, old_token)
        old.start()
        self.addCleanup(old.stop)
        new = LocalServer(runtime, new_token)
        new.start()
        self.addCleanup(new.stop)
        self.assertNotEqual(old.port, new.port)

        # Health is a liveness probe only and stays token-free on both apps.
        for server in (old, new):
            status, payload = server.client().get("/api/local/health", token=None)
            self.assertEqual(status, 200, payload)

        # The old token is not a credential for the new app instance.
        status, payload = new.client().get("/api/local/context", token=old_token)
        self.assertEqual(status, 401, payload)
        self.assertEqual(payload["error"]["code"], "APP_SESSION_REQUIRED")

        # And the new token cannot reach the old app instance either.
        status, payload = old.client().get("/api/local/context", token=new_token)
        self.assertEqual(status, 401, payload)
        self.assertEqual(payload["error"]["code"], "APP_SESSION_REQUIRED")

        # The matching token still reads the same runtime through each app.
        status, payload = new.client().get("/api/local/context")
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["status"], "uninitialized")

        # Stopping the old transport is independent of the new one.
        old.stop()
        self.assertFalse(old.thread.is_alive())
        status, payload = new.client().get("/api/local/context")
        self.assertEqual(status, 200, payload)

    def test_mutating_request_with_old_token_is_refused_before_body_use(self):
        runtime = self.make_runtime()
        old_token = secrets.token_urlsafe(32)
        new_token = secrets.token_urlsafe(32)
        old = LocalServer(runtime, old_token)
        old.start()
        self.addCleanup(old.stop)
        new = LocalServer(runtime, new_token)
        new.start()
        self.addCleanup(new.stop)

        body = {
            "request_id": "synthetic-retirement-request",
            "display_name": "王老师",
            "class_name": "中一班",
            "grade": "middle",
            "term_name": "2026 年秋季学期",
            "start_date": "2026-09-01",
            "end_date": "2026-09-30",
            "school_name": "",
        }
        status, payload = new.client().post(
            "/api/local/initialize", body, token=old_token
        )
        self.assertEqual(status, 401, payload)
        self.assertEqual(payload["error"]["code"], "APP_SESSION_REQUIRED")
        # The refused request did not initialize the shared runtime.
        status, payload = new.client().get("/api/local/context")
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["status"], "uninitialized")


if __name__ == "__main__":
    unittest.main()
