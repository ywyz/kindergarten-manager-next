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
import json
import os
import sys
import threading
import unittest
import unittest.mock
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

import sqlalchemy as sa
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
        self._admin_client()
        resp = self._register("teacher1", "teacher-password-1")
        self.assertEqual(resp.status, 201)
        resp = self._register("teacher1", "different-password-1")
        self.assertEqual(resp.status, 409)
        self.assertEqual(resp.json()["error"]["code"], "USERNAME_TAKEN")
        resp = self._register("teacher2", "teacher-password-2")
        self.assertEqual(resp.status, 201)
        self.assertEqual(resp.json()["account"]["role"], "teacher")

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

        original_record = auth_service.record_operation

        def failing_record(*args, **kwargs):
            original_record(*args, **kwargs)
            raise sa.exc.OperationalError("simulated flush failure", params=None, orig=None)

        with unittest.mock.patch.object(auth_service, "record_operation", failing_record):
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
        self.assertEqual(resp.status, 503)

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
            record = (
                db.query(OperationRecord)
                .filter(OperationRecord.target_account_id == row.id)
                .order_by(OperationRecord.created_at.desc())
                .first()
            )
            self.assertIsNotNone(record)
            self.assertEqual(record.operator_type, "server_operator")
            self.assertEqual(record.action, "cli_reset_admin_password")
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


if __name__ == "__main__":
    unittest.main()
