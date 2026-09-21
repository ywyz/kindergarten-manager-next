"""Integration tests for I1 identity flows.

These tests require an isolated MySQL 8.4 / InnoDB database named
``kindergarten_test_i1`` reachable on 127.0.0.1 or localhost. They do **not**
run migrations automatically; apply ``alembic upgrade head`` separately.

Set both environment variables before running:

    export APP_DISABLE_DOTENV=1
    export I1_TEST_ALLOW_DESTRUCTIVE=yes
    export I1_TEST_DATABASE_URL=mysql+pymysql://user:pass@127.0.0.1:3306/kindergarten_test_i1
"""

import asyncio
import hashlib
import json
import os
import sys
import threading
import unittest
import unittest.mock
from datetime import timedelta
from io import StringIO
from urllib.parse import urlsplit

os.environ["APP_DISABLE_DOTENV"] = "1"

_test_database_url = os.environ.get("I1_TEST_DATABASE_URL") or os.environ.get("MYSQL_TEST_URL")
_integration_enabled = (
    os.environ.get("I1_TEST_ALLOW_DESTRUCTIVE") == "yes"
    and bool(_test_database_url)
)

if _integration_enabled:
    os.environ["DATABASE_URL"] = _test_database_url

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.config import settings
from app.main import app
from app.models import Account, AccountSession, FirstAdminControl, OperationRecord
from app.rate_limit import limiter
from app.services import auth_service


_ORIGIN = "http://localhost:5173"


def _json_body(obj: dict) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


# Captured once: when record_operation is patched with the helper below, the
# global lookup in auth_service is already patched, so the helper must close
# over the genuine implementation explicitly.
_ORIGINAL_RECORD_OPERATION = auth_service.record_operation


def _fail_with_real_mysql_error(
    db,
    *,
    operator_id,
    operator_type,
    action,
    target_account_id,
    account_version_after,
):
    """Fault injection scheduled at the audit-write point of a transaction.

    Step 1 calls the genuine record_operation so the real audit row is added
    to the open transaction, then db.flush() sends every pending write to the
    database: account rows, the first-admin control row, session revocation
    UPDATEs and this audit record are all written inside the transaction.

    Step 2 executes SQL against a table that does not exist, which makes the
    real MySQL server reject the statement (error 1146). The caller rolls the
    whole transaction back, proving all previously flushed writes are undone.

    The database is the real authorized MySQL/InnoDB instance; mocks are used
    only to schedule the failure (and to feed CLI input).
    """
    _ORIGINAL_RECORD_OPERATION(
        db,
        operator_id=operator_id,
        operator_type=operator_type,
        action=action,
        target_account_id=target_account_id,
        account_version_after=account_version_after,
    )
    db.flush()
    db.execute(text("INSERT INTO kg_i1_injected_missing_table (id) VALUES ('x')"))


class AsgiResponse:
    def __init__(self, status: int, headers: dict[str, list[str]], body: bytes):
        self.status = status
        self.headers = headers
        self.body = body

    @property
    def set_cookie_headers(self) -> list[str]:
        return self.headers.get("set-cookie", [])

    def cookie_value(self, name: str) -> str | None:
        for header in self.set_cookie_headers:
            if header.startswith(f"{name}="):
                return header.split(";", 1)[0].split("=", 1)[1].strip('"')
        return None

    def json(self) -> dict:
        return json.loads(self.body)


class AsgiClient:
    """Minimal ASGI client with path/query splitting and a robust receive channel."""

    def __init__(self):
        self.cookies: dict[str, str] = {}

    def request(
        self,
        method: str,
        path: str,
        headers: dict[str, str | bytes] | None = None,
        body: bytes = b"",
    ) -> AsgiResponse:
        headers = dict(headers or {})
        if self.cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())

        is_mutating = method in ("POST", "PATCH", "PUT", "DELETE")
        has_json_body = bool(body) and (
            headers.get("Content-Type", "application/json").split(";")[0].strip().lower()
            == "application/json"
        )
        if is_mutating and has_json_body and "Origin" not in headers:
            headers["Origin"] = _ORIGIN
        if body and "Content-Type" not in headers:
            headers["Content-Type"] = "application/json"

        status, hdrs, resp_body = asyncio.run(
            self._asgi_request(method, path, headers, body)
        )
        for cookie_header in hdrs.get("set-cookie", []):
            if "Max-Age=0" in cookie_header or '=""' in cookie_header:
                name = cookie_header.split("=", 1)[0]
                self.cookies.pop(name, None)
            else:
                name = cookie_header.split("=", 1)[0]
                value = cookie_header.split(";", 1)[0].split("=", 1)[1].strip('"')
                self.cookies[name] = value
        return AsgiResponse(status, hdrs, resp_body)

    async def _asgi_request(
        self,
        method: str,
        path: str,
        headers: dict[str, str | bytes],
        body: bytes,
    ) -> tuple[int, dict[str, list[str]], bytes]:
        parsed = urlsplit(path)
        request_headers: list[tuple[bytes, bytes]] = []
        for k, v in headers.items():
            name = k.lower().encode("latin-1")
            value = v if isinstance(v, bytes) else v.encode("latin-1")
            request_headers.append((name, value))
        if body and not any(name == b"content-length" for name, _ in request_headers):
            request_headers.append((b"content-length", str(len(body)).encode("latin-1")))

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "path": parsed.path,
            "raw_path": parsed.path.encode("ascii"),
            "query_string": parsed.query.encode("utf-8"),
            "root_path": "",
            "headers": request_headers,
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 8000),
            "scheme": "http",
        }

        events: list[dict] = [
            {"type": "http.request", "body": body, "more_body": False},
        ]
        event_index = 0

        async def receive() -> dict:
            nonlocal event_index
            if event_index < len(events):
                event = events[event_index]
                event_index += 1
                return event
            return {"type": "http.disconnect"}

        response_start: dict | None = None
        response_body = bytearray()

        async def send(message: dict) -> None:
            nonlocal response_start
            if message["type"] == "http.response.start":
                response_start = message
            elif message["type"] == "http.response.body":
                response_body.extend(message.get("body", b""))

        await app(scope, receive, send)
        assert response_start is not None
        grouped: dict[str, list[str]] = {}
        for name, value in response_start["headers"]:
            key = name.decode("latin-1").lower()
            grouped.setdefault(key, []).append(value.decode("latin-1"))
        return response_start["status"], grouped, bytes(response_body)


@unittest.skipUnless(
    _integration_enabled,
    "Set APP_DISABLE_DOTENV=1, I1_TEST_ALLOW_DESTRUCTIVE=yes and I1_TEST_DATABASE_URL.",
)
class IdentityIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_url = settings.database_url.get_secret_value()
        cls._require_authorized_url(cls.db_url)
        cls.engine = create_engine(cls.db_url, poolclass=NullPool)
        cls.Session = sessionmaker(bind=cls.engine, expire_on_commit=False)
        cls._check_environment()
        cls._ensure_schema()

    @classmethod
    def _require_authorized_url(cls, raw_url: str) -> None:
        url = make_url(raw_url)
        if url.drivername != "mysql+pymysql":
            raise AssertionError("Only mysql+pymysql URLs are supported")
        if url.host not in ("127.0.0.1", "localhost"):
            raise AssertionError("Integration tests only run against 127.0.0.1/localhost")
        if url.database != "kindergarten_test_i1":
            raise AssertionError("Integration tests require database kindergarten_test_i1")

    @classmethod
    def _check_environment(cls) -> None:
        with cls.engine.connect() as conn:
            version = conn.execute(text("SELECT VERSION()")).scalar()
            engine_var = conn.execute(
                text("SHOW VARIABLES LIKE 'default_storage_engine'")
            ).fetchone()

        if not version or not version.startswith("8.4"):
            raise AssertionError(f"MySQL 8.4 required, found {version}")
        if not engine_var or engine_var[1].lower() != "innodb":
            raise AssertionError("MySQL default storage engine must be InnoDB")

    @classmethod
    def _ensure_schema(cls) -> None:
        required_tables = ("accounts", "first_admin_control", "sessions", "operation_records")
        with cls.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT table_name, engine FROM information_schema.tables "
                    "WHERE table_schema = DATABASE() AND table_name IN :names"
                ),
                {"names": required_tables},
            ).fetchall()
        found = {row[0]: row[1] for row in rows}
        missing = set(required_tables) - set(found)
        if missing:
            raise AssertionError(
                f"Schema missing tables {missing}; run 'alembic upgrade head' first."
            )
        non_innodb = [t for t, e in found.items() if e.lower() != "innodb"]
        if non_innodb:
            raise AssertionError(f"Tables must use InnoDB: {non_innodb}")

    def setUp(self):
        limiter.reset()
        self._admin_client_cache: AsgiClient | None = None
        with self.engine.connect() as conn:
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            for table in (
                "operation_records",
                "sessions",
                "first_admin_control",
                "accounts",
            ):
                conn.execute(text(f"TRUNCATE TABLE {table}"))
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
            conn.execute(
                text(
                    "INSERT INTO first_admin_control (id, claimed, first_admin_id) "
                    "VALUES ('singleton', 0, NULL)"
                )
            )
            conn.commit()

    def _register(self, username: str, password: str) -> AsgiResponse:
        client = AsgiClient()
        return client.request(
            "POST",
            "/api/auth/register",
            body=_json_body({"username": username, "password": password}),
        )

    def _login(self, client: AsgiClient, username: str, password: str) -> AsgiResponse:
        return client.request(
            "POST",
            "/api/auth/login",
            body=_json_body({"username": username, "password": password}),
        )

    def _create_admin(self, username: str = "admin1", password: str = "admin-password-1") -> AsgiClient:
        client = AsgiClient()
        resp = client.request(
            "POST",
            "/api/auth/register",
            body=_json_body({"username": username, "password": password}),
        )
        self.assertEqual(resp.status, 201, resp.body)
        return client

    def _admin_client(self) -> AsgiClient:
        if self._admin_client_cache is None:
            client = self._create_admin()
            resp = self._login(client, "admin1", "admin-password-1")
            self.assertEqual(resp.status, 200, resp.body)
            self._admin_client_cache = client
        return self._admin_client_cache

    def _create_teacher(
        self, username: str, password: str, login: bool = True
    ) -> AsgiClient:
        # The first admin must exist so subsequent registrations become teachers.
        self._admin_client()
        client = AsgiClient()
        resp = client.request(
            "POST",
            "/api/auth/register",
            body=_json_body({"username": username, "password": password}),
        )
        self.assertEqual(resp.status, 201, resp.body)
        self.assertEqual(resp.json()["account"]["role"], "teacher")
        if login:
            resp = self._login(client, username, password)
            self.assertEqual(resp.status, 200, resp.body)
        return client

    def _account_row(self, username: str) -> Account:
        with self.Session() as db:
            return db.query(Account).filter(Account.username == username).one()

    def _snapshot_account(self, username: str) -> dict:
        with self.Session() as db:
            account = db.query(Account).filter(Account.username == username).one()
            sessions = (
                db.query(AccountSession)
                .filter(AccountSession.account_id == account.id)
                .all()
            )
            records = (
                db.query(OperationRecord)
                .filter(OperationRecord.target_account_id == account.id)
                .all()
            )
            return {
                "id": account.id,
                "password_hash": account.password_hash,
                "version": account.version,
                "auth_version": account.auth_version,
                "is_active": account.is_active,
                "revoked_sessions": [s.revoked_at for s in sessions],
                "audit_actions": [r.action for r in records],
            }

    def test_control_row_initialized(self):
        with self.Session() as db:
            control = db.get(FirstAdminControl, "singleton")
            self.assertIsNotNone(control)
            self.assertFalse(control.claimed)

    def test_first_register_becomes_admin(self):
        resp = self._register("admin1", "admin-password-1")
        self.assertEqual(resp.status, 201)
        self.assertEqual(resp.json()["account"]["role"], "admin")
        with self.Session() as db:
            control = db.get(FirstAdminControl, "singleton")
            self.assertTrue(control.claimed)
            self.assertEqual(control.first_admin_id, resp.json()["account"]["id"])

    def test_first_admin_race_only_one_admin(self):
        results = []
        errors = []
        lock = threading.Lock()
        barrier = threading.Barrier(2)

        def worker(username: str):
            barrier.wait(timeout=5)
            client = AsgiClient()
            try:
                resp = client.request(
                    "POST",
                    "/api/auth/register",
                    body=_json_body({"username": username, "password": "race-password-123"}),
                )
                with lock:
                    if resp.status == 201:
                        results.append((username, resp.json()["account"]["role"]))
                    else:
                        errors.append((username, resp.status, resp.body))
            except Exception as exc:
                with lock:
                    errors.append((username, exc))

        t1 = threading.Thread(target=worker, args=("racer1",))
        t2 = threading.Thread(target=worker, args=("racer2",))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        roles = [r[1] for r in results]
        self.assertEqual(sorted(roles), ["admin", "teacher"], f"errors={errors}")
        self.assertEqual(len(errors), 0)

    def test_same_username_race_only_one_succeeds(self):
        successes = []
        errors = []
        lock = threading.Lock()
        barrier = threading.Barrier(2)

        def worker():
            barrier.wait(timeout=5)
            client = AsgiClient()
            try:
                resp = client.request(
                    "POST",
                    "/api/auth/register",
                    body=_json_body({"username": "racer", "password": "race-password-123"}),
                )
                with lock:
                    if resp.status == 201:
                        successes.append(resp.json()["account"]["id"])
                    else:
                        errors.append(resp.status)
            except Exception as exc:
                with lock:
                    errors.append(exc)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        self.assertEqual(len(successes), 1, f"successes={successes}, errors={errors}")
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0], 409)

    def test_failed_registration_does_not_consume_first_admin(self):
        # First transaction: the account, first-admin control row and audit
        # record are all genuinely flushed to MySQL inside the transaction,
        # then a real MySQL statement error (missing table) forces the server
        # to reject the statement and the app rolls every flushed row back.
        with unittest.mock.patch.object(
            auth_service, "record_operation", _fail_with_real_mysql_error
        ):
            resp = self._register("first", "first-password-123")
        self.assertEqual(resp.status, 503, resp.body)

        with self.Session() as db:
            control = db.get(FirstAdminControl, "singleton")
            self.assertFalse(control.claimed)
            self.assertIsNone(control.first_admin_id)
            self.assertEqual(db.query(Account).count(), 0)
            self.assertEqual(db.query(OperationRecord).count(), 0)

        # The failed first transaction must not consume the first-admin claim:
        # a subsequent registration still becomes the administrator.
        resp = self._register("first", "first-password-123")
        self.assertEqual(resp.status, 201, resp.body)
        self.assertEqual(resp.json()["account"]["role"], "admin")

        with self.Session() as db:
            control = db.get(FirstAdminControl, "singleton")
            self.assertTrue(control.claimed)
            self.assertEqual(control.first_admin_id, resp.json()["account"]["id"])

        # A later duplicate username still fails and changes nothing.
        resp = self._register("first", "different-password-1")
        self.assertEqual(resp.status, 409)
        self.assertEqual(resp.json()["error"]["code"], "USERNAME_TAKEN")
        first_row = self._account_row("first")
        with self.Session() as db:
            self.assertEqual(db.query(Account).count(), 1)
            self.assertEqual(
                db.get(FirstAdminControl, "singleton").first_admin_id,
                first_row.id,
            )

    def test_login_me_logout_lifecycle(self):
        self._create_teacher("teacher1", "teacher-password-1")
        client = AsgiClient()
        resp = self._login(client, "teacher1", "teacher-password-1")
        self.assertEqual(resp.status, 200)
        self.assertIsNotNone(resp.cookie_value("session"))
        self.assertIn("HttpOnly", "; ".join(resp.set_cookie_headers))

        me = client.request("GET", "/api/auth/me")
        self.assertEqual(me.status, 200)
        self.assertEqual(me.json()["account"]["username"], "teacher1")

        logout = client.request("POST", "/api/auth/logout", body=b"{}")
        self.assertEqual(logout.status, 204)
        self.assertIn('session=""', "; ".join(logout.set_cookie_headers))

        me = client.request("GET", "/api/auth/me")
        self.assertEqual(me.status, 401)

    def test_invalid_credentials_unified(self):
        self._create_teacher("teacher1", "teacher-password-1")
        client = AsgiClient()
        for payload in (
            {"username": "teacher1", "password": "wrong-password-12"},
            {"username": "nosuchuser", "password": "any-password-12"},
        ):
            resp = client.request(
                "POST",
                "/api/auth/login",
                body=_json_body(payload),
            )
            self.assertEqual(resp.status, 401)
            self.assertEqual(resp.json()["error"]["code"], "INVALID_CREDENTIALS")

    def test_change_password_revokes_all_sessions_and_old_password_fails(self):
        teacher = self._create_teacher("teacher1", "teacher-password-1")
        other = AsgiClient()
        self._login(other, "teacher1", "teacher-password-1")

        resp = teacher.request(
            "POST",
            "/api/settings/password",
            body=_json_body(
                {
                    "current_password": "teacher-password-1",
                    "new_password": "new-password-123",
                    "expected_version": 1,
                }
            ),
        )
        self.assertEqual(resp.status, 204)
        self.assertIn('session=""', "; ".join(resp.set_cookie_headers))

        self.assertEqual(teacher.request("GET", "/api/auth/me").status, 401)
        self.assertEqual(other.request("GET", "/api/auth/me").status, 401)

        new_client = AsgiClient()
        self.assertEqual(
            self._login(new_client, "teacher1", "new-password-123").status, 200
        )
        bad = AsgiClient()
        self.assertEqual(
            self._login(bad, "teacher1", "teacher-password-1").status, 401
        )

    def test_profile_update_version_conflict(self):
        self._create_teacher("teacher1", "teacher-password-1")
        client = AsgiClient()
        self._login(client, "teacher1", "teacher-password-1")
        resp = client.request(
            "PATCH",
            "/api/settings/profile",
            body=_json_body({"display_name": "张老师", "expected_version": 99}),
        )
        self.assertEqual(resp.status, 409)
        self.assertEqual(resp.json()["error"]["code"], "VERSION_CONFLICT")
        with self.Session() as db:
            account = db.query(Account).filter(Account.username == "teacher1").one()
            self.assertIsNone(account.display_name)
            self.assertEqual(account.version, 1)

    def test_teacher_http_overreach(self):
        self._admin_client()
        self._create_teacher("teacher1", "teacher-password-1")
        self._create_teacher("teacher2", "teacher-password-2")

        teacher1 = AsgiClient()
        self._login(teacher1, "teacher1", "teacher-password-1")
        self.assertEqual(teacher1.request("GET", "/api/admin/teachers").status, 403)

        teacher2 = self._account_row("teacher2")
        resp = teacher1.request(
            "POST",
            f"/api/admin/teachers/{teacher2.id}/password-reset",
            body=_json_body({"new_password": "hacked-password-1", "expected_version": 1}),
        )
        self.assertEqual(resp.status, 403)

    def test_admin_can_reset_teacher_password_and_revoke_sessions(self):
        self._admin_client()
        teacher = self._create_teacher("teacher1", "teacher-password-1")
        account = self._account_row("teacher1")

        admin = self._admin_client()
        resp = admin.request(
            "POST",
            f"/api/admin/teachers/{account.id}/password-reset",
            body=_json_body({"new_password": "reset-password-1", "expected_version": 1}),
        )
        self.assertEqual(resp.status, 200)
        self.assertTrue(resp.json()["sessions_revoked"])

        self.assertEqual(teacher.request("GET", "/api/auth/me").status, 401)
        # Resetting another account must not revoke the operator's session.
        self.assertEqual(admin.request("GET", "/api/auth/me").status, 200)

        new_client = AsgiClient()
        self.assertEqual(
            self._login(new_client, "teacher1", "reset-password-1").status, 200
        )

    def test_admin_reset_on_non_teacher_is_forbidden(self):
        self._admin_client()
        account = self._account_row("admin1")
        admin = self._admin_client()
        resp = admin.request(
            "POST",
            f"/api/admin/teachers/{account.id}/password-reset",
            body=_json_body({"new_password": "any-password-12", "expected_version": 1}),
        )
        self.assertEqual(resp.status, 403)

    def test_version_conflict_leaves_target_unchanged(self):
        self._admin_client()
        self._create_teacher("teacher1", "teacher-password-1")
        account = self._account_row("teacher1")

        other = AsgiClient()
        self._login(other, "teacher1", "teacher-password-1")
        other.request(
            "PATCH",
            "/api/settings/profile",
            body=_json_body({"display_name": "已改", "expected_version": 1}),
        )

        admin = self._admin_client()
        resp = admin.request(
            "POST",
            f"/api/admin/teachers/{account.id}/password-reset",
            body=_json_body({"new_password": "hacked-password-1", "expected_version": 1}),
        )
        self.assertEqual(resp.status, 409)

        with self.Session() as db:
            row = db.get(Account, account.id)
            self.assertEqual(row.display_name, "已改")
            self.assertEqual(row.version, 2)
            self.assertTrue(
                auth_service.security.verify_password("teacher-password-1", row.password_hash)
            )

    def test_password_write_failure_rolls_back_everything(self):
        self._create_teacher("teacher1", "teacher-password-1")
        teacher = AsgiClient()
        self._login(teacher, "teacher1", "teacher-password-1")
        before = self._snapshot_account("teacher1")

        with unittest.mock.patch.object(
            auth_service, "record_operation", _fail_with_real_mysql_error
        ):
            resp = teacher.request(
                "POST",
                "/api/settings/password",
                body=_json_body(
                    {
                        "current_password": "teacher-password-1",
                        "new_password": "new-password-123",
                        "expected_version": 1,
                    }
                ),
            )
        # The response is driven by a genuine MySQL 1146 error from the real
        # database, not by an exception fabricated inside the test.
        self.assertEqual(resp.status, 503, resp.body)

        after = self._snapshot_account("teacher1")
        self.assertEqual(after["password_hash"], before["password_hash"])
        self.assertEqual(after["version"], before["version"])
        self.assertEqual(after["auth_version"], before["auth_version"])
        self.assertEqual(after["revoked_sessions"], before["revoked_sessions"])
        self.assertEqual(after["audit_actions"], before["audit_actions"])

    def test_login_verify_then_reset_race_rejects_stale_session(self):
        self._admin_client()
        self._create_teacher("teacher1", "teacher-password-1")
        account = self._account_row("teacher1")
        admin = self._admin_client()

        original_verify = auth_service.security.verify_password
        verified = threading.Event()
        reset_done = threading.Event()
        worker_exc: list[Exception] = []
        login_result: list[tuple[int, str | None]] = []

        def patched_verify(password: str, phc: str) -> bool:
            result = original_verify(password, phc)
            if result and password == "teacher-password-1":
                verified.set()
                reset_done.wait(timeout=10)
            return result

        def login_worker():
            try:
                client = AsgiClient()
                resp = client.request(
                    "POST",
                    "/api/auth/login",
                    body=_json_body(
                        {"username": "teacher1", "password": "teacher-password-1"}
                    ),
                )
                login_result.append((resp.status, resp.cookie_value("session")))
            except Exception as exc:
                worker_exc.append(exc)

        with unittest.mock.patch.object(
            auth_service.security, "verify_password", patched_verify
        ):
            t1 = threading.Thread(target=login_worker)
            t1.start()
            try:
                # Wait until the worker has verified the password, then reset.
                self.assertTrue(verified.wait(timeout=10))
                resp = admin.request(
                    "POST",
                    f"/api/admin/teachers/{account.id}/password-reset",
                    body=_json_body(
                        {"new_password": "reset-password-1", "expected_version": 1}
                    ),
                )
                self.assertEqual(resp.status, 200)
            finally:
                reset_done.set()
                t1.join(timeout=15)
                self.assertFalse(t1.is_alive())

        if worker_exc:
            raise worker_exc[0]

        self.assertEqual(len(login_result), 1)
        status, token = login_result[0]
        if status == 200 and token:
            client = AsgiClient()
            client.cookies["session"] = token
            self.assertEqual(client.request("GET", "/api/auth/me").status, 401)
        else:
            self.assertIn(status, (401,))

    def test_permission_revoked_after_dependency_resolution(self):
        self._admin_client()
        self._create_teacher("teacher1", "teacher-password-1")
        account = self._account_row("teacher1")
        admin = self._admin_client()

        original_reset = auth_service.admin_reset_password

        def revoke_then_call(db, admin_snapshot, *args, **kwargs):
            # After the dependency snapshot was built, revoke the admin session
            # from an independent transaction.
            with self.Session() as inner:
                inner.execute(
                    text(
                        "UPDATE sessions SET revoked_at = UTC_TIMESTAMP() "
                        "WHERE id = :sid AND revoked_at IS NULL"
                    ),
                    {"sid": admin_snapshot.session_id},
                )
                inner.commit()
            return original_reset(db, admin_snapshot, *args, **kwargs)

        with unittest.mock.patch.object(auth_service, "admin_reset_password", revoke_then_call):
            resp = admin.request(
                "POST",
                f"/api/admin/teachers/{account.id}/password-reset",
                body=_json_body({"new_password": "hacked-password-1", "expected_version": 1}),
            )
        self.assertEqual(resp.status, 401)

        with self.Session() as db:
            row = db.get(Account, account.id)
            self.assertEqual(row.version, 1)
            self.assertTrue(
                auth_service.security.verify_password("teacher-password-1", row.password_hash)
            )

    def test_normalized_username_collision_and_login(self):
        resp = self._register("Teacher.A", "teacher-password-1")
        self.assertEqual(resp.status, 201)
        self.assertEqual(resp.json()["account"]["username"], "teacher.a")

        # Different case and surrounding whitespace normalize to the same name.
        for variant in ("  Teacher.A  ", "TEACHER.A", "\tteacher.a\n"):
            resp = self._register(variant, "another-password-1")
            self.assertEqual(resp.status, 409, resp.body)
            self.assertEqual(resp.json()["error"]["code"], "USERNAME_TAKEN")

        # Login applies the exact same normalization rules.
        client = AsgiClient()
        self.assertEqual(
            self._login(client, "  TEACHER.A ", "teacher-password-1").status,
            200,
        )
        self.assertEqual(client.request("GET", "/api/auth/me").status, 200)

    def test_disabled_account_login_rejected_and_sessions_dead(self):
        self._create_teacher("teacher1", "teacher-password-1")
        client = AsgiClient()
        self.assertEqual(
            self._login(client, "teacher1", "teacher-password-1").status, 200
        )

        with self.Session() as db:
            row = db.query(Account).filter(Account.username == "teacher1").one()
            row.is_active = False
            db.commit()

        # Existing session stops working immediately.
        self.assertEqual(client.request("GET", "/api/auth/me").status, 401)
        # Disabled login is indistinguishable from bad credentials.
        other = AsgiClient()
        resp = self._login(other, "teacher1", "teacher-password-1")
        self.assertEqual(resp.status, 401)
        self.assertEqual(resp.json()["error"]["code"], "INVALID_CREDENTIALS")

    def test_expired_session_is_rejected(self):
        self._create_teacher("teacher1", "teacher-password-1")
        client = AsgiClient()
        resp = self._login(client, "teacher1", "teacher-password-1")
        self.assertEqual(resp.status, 200)
        raw_token = client.cookies["session"]

        with self.Session() as db:
            session = db.scalar(
                select(AccountSession)
                .where(
                    AccountSession.token_hash
                    == hashlib.sha256(raw_token.encode("ascii")).hexdigest()
                )
            )
            self.assertIsNotNone(session)
            session.expires_at = auth_service.utc_now() - timedelta(seconds=1)
            db.commit()

        self.assertEqual(client.request("GET", "/api/auth/me").status, 401)

        # Re-login mints a fresh valid session.
        new_client = AsgiClient()
        self.assertEqual(
            self._login(new_client, "teacher1", "teacher-password-1").status, 200
        )
        self.assertEqual(
            new_client.request("GET", "/api/auth/me").status, 200
        )

    def test_admin_reset_failure_rolls_back_everything(self):
        self._admin_client()
        teacher = self._create_teacher("teacher1", "teacher-password-1")
        account = self._account_row("teacher1")
        before = self._snapshot_account("teacher1")

        with unittest.mock.patch.object(
            auth_service, "record_operation", _fail_with_real_mysql_error
        ):
            resp = self._admin_client().request(
                "POST",
                f"/api/admin/teachers/{account.id}/password-reset",
                body=_json_body(
                    {"new_password": "reset-password-1", "expected_version": 1}
                ),
            )
        self.assertEqual(resp.status, 503, resp.body)

        after = self._snapshot_account("teacher1")
        self.assertEqual(after["password_hash"], before["password_hash"])
        self.assertEqual(after["version"], before["version"])
        self.assertEqual(after["auth_version"], before["auth_version"])
        self.assertEqual(after["revoked_sessions"], before["revoked_sessions"])
        self.assertEqual(after["audit_actions"], before["audit_actions"])

        # Old session and old password still work; new password does not.
        self.assertEqual(teacher.request("GET", "/api/auth/me").status, 200)
        bad = AsgiClient()
        self.assertEqual(
            self._login(bad, "teacher1", "reset-password-1").status, 401
        )

    def test_cli_reset_failure_rolls_back_everything(self):
        admin = self._create_admin("cliadmin", "cli-admin-pass-1")
        self._login(admin, "cliadmin", "cli-admin-pass-1")
        before = self._snapshot_account("cliadmin")

        stderr_buf = StringIO()
        with (
            unittest.mock.patch("sys.stdin.isatty", return_value=True),
            unittest.mock.patch(
                "app.cli.getpass.getpass",
                side_effect=["cli-new-password-123", "cli-new-password-123"],
            ),
            unittest.mock.patch("builtins.input", return_value="y"),
            unittest.mock.patch("sys.stderr", stderr_buf),
            unittest.mock.patch.object(
                auth_service, "record_operation", _fail_with_real_mysql_error
            ),
        ):
            from app import cli

            with self.assertRaises(SystemExit) as cm:
                cli._reset_admin_password("cliadmin")
        self.assertEqual(cm.exception.code, 1)

        after = self._snapshot_account("cliadmin")
        self.assertEqual(after["password_hash"], before["password_hash"])
        self.assertEqual(after["version"], before["version"])
        self.assertEqual(after["auth_version"], before["auth_version"])
        self.assertEqual(after["revoked_sessions"], before["revoked_sessions"])
        self.assertEqual(after["audit_actions"], before["audit_actions"])

        with self.Session() as db:
            active = (
                db.query(AccountSession)
                .filter(
                    AccountSession.account_id == self._account_row("cliadmin").id,
                    AccountSession.revoked_at.is_(None),
                )
                .count()
            )
            self.assertEqual(active, 1)
        # Old password still works; new password does not.
        old = AsgiClient()
        self.assertEqual(
            self._login(old, "cliadmin", "cli-admin-pass-1").status, 200
        )
        new = AsgiClient()
        self.assertEqual(
            self._login(new, "cliadmin", "cli-new-password-123").status, 401
        )

    def test_persistence_contains_no_raw_secrets(self):
        admin_pw = "admin-password-12345"
        resp = self._register("admin1", admin_pw)
        self.assertEqual(resp.status, 201, resp.body)
        self.assertEqual(resp.json()["account"]["role"], "admin")
        admin_client = AsgiClient()
        resp = self._login(admin_client, "admin1", admin_pw)
        self.assertEqual(resp.status, 200, resp.body)
        # Raw session tokens captured only as local test variables so the
        # test can prove they never appear in any persisted column. They are
        # never printed.
        admin_raw_token = admin_client.cookies["session"]

        teacher_pw = "teacher-password-12345"
        resp = self._register("teacher1", teacher_pw)
        self.assertEqual(resp.status, 201, resp.body)
        self.assertEqual(resp.json()["account"]["role"], "teacher")
        teacher = AsgiClient()
        resp = self._login(teacher, "teacher1", teacher_pw)
        self.assertEqual(resp.status, 200, resp.body)
        teacher_raw_token = teacher.cookies["session"]

        # Real password hashes as persisted by the accounts table. Capturing
        # them before and after every password mutation covers every hash the
        # accounts ever held; none of these hashes may appear in audit rows.
        hashes_initial = {
            self._account_row("admin1").password_hash,
            self._account_row("teacher1").password_hash,
        }

        # Update every audited action type so masking is checked for all rows.
        resp = teacher.request(
            "PATCH",
            "/api/settings/profile",
            body=_json_body({"display_name": "王老师", "expected_version": 1}),
        )
        self.assertEqual(resp.status, 200, resp.body)

        resp = teacher.request(
            "POST",
            "/api/settings/password",
            body=_json_body(
                {
                    "current_password": teacher_pw,
                    "new_password": "teacher-new-pass-1",
                    "expected_version": 2,
                }
            ),
        )
        self.assertEqual(resp.status, 204, resp.body)
        hashes_after_self_change = {self._account_row("teacher1").password_hash}

        account = self._account_row("teacher1")
        resp = admin_client.request(
            "POST",
            f"/api/admin/teachers/{account.id}/password-reset",
            body=_json_body(
                {"new_password": "teacher-reset-pass-1", "expected_version": 3}
            ),
        )
        self.assertEqual(resp.status, 200, resp.body)

        with (
            unittest.mock.patch("sys.stdin.isatty", return_value=True),
            unittest.mock.patch(
                "app.cli.getpass.getpass",
                side_effect=["admin-new-pass-123", "admin-new-pass-123"],
            ),
            unittest.mock.patch("builtins.input", return_value="y"),
        ):
            from app import cli

            cli._reset_admin_password("admin1")

        hashes_final = {
            self._account_row("admin1").password_hash,
            self._account_row("teacher1").password_hash,
        }
        forbidden_password_hashes = (
            hashes_initial | hashes_after_self_change | hashes_final
        )

        # Raw secrets: every plaintext password and every original session
        # token minted during the test.
        raw_secrets = [
            admin_pw,
            "admin-new-pass-123",
            teacher_pw,
            "teacher-new-pass-1",
            "teacher-reset-pass-1",
            admin_raw_token,
            teacher_raw_token,
        ]

        # Physical columns of the audit and session tables.
        def columns(table_name: str) -> set[str]:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = DATABASE() AND table_name = :t"
                    ),
                    {"t": table_name},
                ).fetchall()
            return {r[0] for r in rows}

        record_columns = columns("operation_records")
        self.assertEqual(
            record_columns,
            {
                "id",
                "created_at",
                "operator_id",
                "operator_type",
                "action",
                "target_account_id",
                "account_version_after",
            },
        )
        session_columns = columns("sessions")
        self.assertEqual(
            session_columns,
            {
                "id",
                "token_hash",
                "account_id",
                "auth_version",
                "created_at",
                "expires_at",
                "revoked_at",
            },
        )

        # Serialize EVERY physical column of both tables straight from the
        # database and assert no raw password, no original session token and
        # no account password hash leaks into either table.
        with self.engine.connect() as conn:
            records_blob = json.dumps(
                [
                    dict(row._mapping)
                    for row in conn.execute(text("SELECT * FROM operation_records"))
                ],
                default=str,
                ensure_ascii=False,
            )
            sessions_blob = json.dumps(
                [
                    dict(row._mapping)
                    for row in conn.execute(text("SELECT * FROM sessions"))
                ],
                default=str,
                ensure_ascii=False,
            )
        for blob in (records_blob, sessions_blob):
            for secret in raw_secrets:
                self.assertNotIn(secret, blob)
        for password_hash in forbidden_password_hashes:
            self.assertNotIn(password_hash, records_blob)

        with self.Session() as db:
            records = db.query(OperationRecord).all()
            expected = {
                "register": (1, "account"),
                "update_profile": (2, "account"),
                "change_password": (3, "account"),
                "admin_password_reset": (4, "account"),
                "cli_reset_admin_password": (2, "server_operator"),
            }
            by_action = {r.action: r for r in records}
            self.assertEqual(set(by_action), set(expected))
            for action, (version, operator_type) in expected.items():
                self.assertEqual(
                    by_action[action].account_version_after, version, action
                )
                self.assertEqual(
                    by_action[action].operator_type, operator_type, action
                )

            # Sessions persist only SHA-256 hashes: every token_hash is a
            # 64-char hex digest and equals, explicitly, the SHA-256 of the
            # corresponding original session token captured right after
            # login (admin token -> its row, teacher token -> its row).
            sessions = db.query(AccountSession).all()
            self.assertGreater(len(sessions), 0)
            for session in sessions:
                self.assertRegex(session.token_hash, r"^[0-9a-f]{64}$")
                # Every session created above precedes a later password
                # change for its account, so each one must be revoked.
                self.assertIsNotNone(session.revoked_at)
            stored_token_hashes = {s.token_hash for s in sessions}
            for raw_token in (admin_raw_token, teacher_raw_token):
                expected_hash = hashlib.sha256(raw_token.encode("ascii")).hexdigest()
                self.assertIn(expected_hash, stored_token_hashes)
                matching = next(
                    s for s in sessions if s.token_hash == expected_hash
                )
                self.assertEqual(matching.token_hash, expected_hash)

    def test_cli_resets_disabled_admin_password(self):
        admin = self._create_admin("cliadmin", "cli-admin-pass-1")
        self._login(admin, "cliadmin", "cli-admin-pass-1")
        with self.Session() as db:
            row = db.query(Account).filter(Account.username == "cliadmin").one()
            row.is_active = False
            db.commit()

        new_password = "cli-new-password-123"
        stderr_buf = StringIO()
        with (
            unittest.mock.patch("sys.stdin.isatty", return_value=True),
            unittest.mock.patch("app.cli.getpass.getpass", side_effect=[new_password, new_password]),
            unittest.mock.patch("builtins.input", return_value="y"),
            unittest.mock.patch("sys.stderr", stderr_buf),
        ):
            from app import cli

            cli._reset_admin_password("cliadmin")

        with self.Session() as db:
            row = db.query(Account).filter(Account.username == "cliadmin").one()
            self.assertFalse(row.is_active)
            self.assertEqual(row.version, 2)
            self.assertTrue(auth_service.security.verify_password(new_password, row.password_hash))
            # Identify the reset record by action + post-change version rather
            # than created_at ordering: MySQL DATETIME has 1-second precision,
            # so the register and reset records may share a timestamp.
            record = (
                db.query(OperationRecord)
                .filter(
                    OperationRecord.target_account_id == row.id,
                    OperationRecord.action == "cli_reset_admin_password",
                    OperationRecord.account_version_after == row.version,
                )
                .one()
            )
            self.assertEqual(record.operator_type, "server_operator")
            self.assertIsNotNone(
                db.query(OperationRecord)
                .filter(
                    OperationRecord.target_account_id == row.id,
                    OperationRecord.action == "register",
                )
                .one()
            )
            active_sessions = (
                db.query(AccountSession)
                .filter(
                    AccountSession.account_id == row.id,
                    AccountSession.revoked_at.is_(None),
                )
                .count()
            )
            self.assertEqual(active_sessions, 0)

    def test_cli_rejects_nonexistent_teacher_and_cancel(self):
        self._admin_client()
        self._create_teacher("cliteacher", "cli-teacher-pass-1")

        # Non-existent admin target.
        stderr_buf = StringIO()
        with (
            unittest.mock.patch("sys.stdin.isatty", return_value=True),
            unittest.mock.patch("sys.stderr", stderr_buf),
        ):
            with self.assertRaises(SystemExit) as cm:
                from app import cli

                cli._reset_admin_password("nosuchadmin")
        self.assertEqual(cm.exception.code, 1)

        # Teacher target is rejected.
        stderr_buf = StringIO()
        with (
            unittest.mock.patch("sys.stdin.isatty", return_value=True),
            unittest.mock.patch("sys.stderr", stderr_buf),
        ):
            with self.assertRaises(SystemExit) as cm:
                cli._reset_admin_password("cliteacher")
        self.assertEqual(cm.exception.code, 1)

        # Cancel at confirmation leaves the admin account unchanged.
        before = self._snapshot_account("admin1")
        stdout_buf = StringIO()
        stderr_buf = StringIO()
        with (
            unittest.mock.patch("sys.stdin.isatty", return_value=True),
            unittest.mock.patch(
                "app.cli.getpass.getpass",
                side_effect=["cli-new-password-123", "cli-new-password-123"],
            ),
            unittest.mock.patch("builtins.input", return_value="n"),
            unittest.mock.patch("sys.stdout", stdout_buf),
            unittest.mock.patch("sys.stderr", stderr_buf),
        ):
            with self.assertRaises(SystemExit) as cm:
                from app import cli

                cli._reset_admin_password("admin1")
        self.assertEqual(cm.exception.code, 0)
        after = self._snapshot_account("admin1")
        self.assertEqual(after["password_hash"], before["password_hash"])
        self.assertEqual(after["version"], before["version"])

        # Mismatched password inputs write nothing.
        before = self._snapshot_account("admin1")
        stderr_buf = StringIO()
        with (
            unittest.mock.patch("sys.stdin.isatty", return_value=True),
            unittest.mock.patch(
                "app.cli.getpass.getpass",
                side_effect=["cli-new-password-123", "other-password-123"],
            ),
            unittest.mock.patch("sys.stderr", stderr_buf),
        ):
            with self.assertRaises(SystemExit) as cm:
                from app import cli

                cli._reset_admin_password("admin1")
        self.assertEqual(cm.exception.code, 1)
        after = self._snapshot_account("admin1")
        self.assertEqual(after["password_hash"], before["password_hash"])
        self.assertEqual(after["version"], before["version"])
        self.assertEqual(after["audit_actions"], before["audit_actions"])


if __name__ == "__main__":
    unittest.main()
