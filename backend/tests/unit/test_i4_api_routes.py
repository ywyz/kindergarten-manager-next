"""No-DB ASGI tests for I4 weekly plan routes (slice 2).

Drives the real FastAPI app (routing, middleware, validation, response
models) with ``get_db`` / ``get_current_account`` / ``get_auth_snapshot``
dependency overrides and mocked I4 services — no database, no MySQL, no
SQLite. Covers the spec permission matrix, the fixed status/code table
(201/200/401/403/404/409/422/503), create/open semantics, PATCH omitted vs
explicit-null handling, CONFIRM_ACK_REQUIRED carrying facts, and route
registration (8 routes, no delete/recover/AI/export entries).
"""

import asyncio
import json
import os

os.environ["APP_DISABLE_DOTENV"] = "1"
os.environ["ALLOWED_ORIGINS"] = "http://localhost:5173,http://127.0.0.1:5173"

import unittest
from datetime import datetime
from unittest import mock

from app.database import get_db
from app.deps import get_auth_snapshot, get_current_account
from app.main import app
from app.models import (
    Account,
    TeacherAssignment,
    WeeklyPlan,
    WeeklyPlanContent,
    WeeklyPlanConfirmedContent,
)
from app.services import auth_service, weekly_plan_read_service, weekly_plan_service
from app.services.auth_service import AuthSnapshot
from app.services.config_errors import ConfigServiceError
from app.services.weekly_plan_service import (
    WeeklyPlanConfirmAckRequired,
    WeeklyPlanDataError,
    WeeklyPlanForbidden,
    WeeklyPlanNotFound,
    WeeklyPlanTermNotFound,
    WeeklyPlanValidationError,
    WeeklyPlanVersionConflict,
    WeeklyPlanWriteResult,
)

_ORIGIN = "http://localhost:5173"
_NOW = datetime(2026, 9, 23, 8, 0, 0)


async def _asgi_request(
    method: str,
    path: str,
    *,
    query: str = "",
    headers: dict | None = None,
    body: bytes = b"",
) -> tuple[int, dict[str, list[str]], bytes]:
    headers = dict(headers or {})
    request_headers = []
    for k, v in headers.items():
        name = k.lower().encode("latin-1")
        value = v if isinstance(v, bytes) else v.encode("latin-1")
        request_headers.append((name, value))
    if body and not any(
        k.lower() == b"content-length" for k, _ in request_headers
    ):
        request_headers.append(
            (b"content-length", str(len(body)).encode("latin-1"))
        )

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": query.encode("utf-8"),
        "root_path": "",
        "headers": request_headers,
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8000),
        "scheme": "http",
    }
    request_iter = iter(
        [{"type": "http.request", "body": body, "more_body": False}]
    )

    async def receive():
        return next(request_iter)

    response_start: dict | None = None
    response_body = bytearray()

    async def send(message):
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


def api_request(
    method: str,
    path: str,
    *,
    query: str = "",
    payload: dict | None = None,
    origin: bool = True,
) -> tuple[int, dict[str, list[str]], bytes]:
    headers: dict[str, str] = {}
    body = b""
    if origin:
        headers["Origin"] = _ORIGIN
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    return asyncio.run(
        _asgi_request(method, path, query=query, headers=headers, body=body)
    )


def error_code(body: bytes) -> str:
    return json.loads(body)["error"]["code"]


def make_account(role: str = "teacher", account_id: str = "tch1") -> Account:
    return Account(
        id=account_id,
        username="user1",
        password_hash="x",
        display_name="甲老师",
        role=role,
        is_active=True,
        version=1,
        auth_version=1,
    )


def make_snapshot(
    role: str = "teacher", account_id: str = "tch1"
) -> AuthSnapshot:
    return AuthSnapshot(
        account_id=account_id,
        role=role,
        auth_version=1,
        session_id="ses1",
        is_active=True,
        password_hash="x",
    )


def make_assignment(
    class_id: str = "cls1", teacher_id: str = "tch1"
) -> TeacherAssignment:
    return TeacherAssignment(
        teacher_id=teacher_id,
        class_id=class_id,
        assigned_by="adm1",
        assigned_at=_NOW,
    )


def make_plan(**kw) -> WeeklyPlan:
    defaults = dict(
        id="wp1",
        class_id="cls1",
        term_id="ter1",
        week_number=3,
        creator_id="tch1",
        owner_id="tch1",
        current_draft_content_id="c2",
        current_draft_version=2,
        current_confirmed_content_id=None,
        current_confirmed_content_version=None,
        school_name="阳光园",
        class_name="中一",
        grade="中班",
        header_teacher_names=["甲老师"],
        caregiver_name="王五",
        projection_consumed_at=_NOW,
        deleted_at=None,
        deleted_by=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    defaults.update(kw)
    plan = WeeklyPlan()
    for key, value in defaults.items():
        setattr(plan, key, value)
    return plan


def make_draft(**kw) -> WeeklyPlanContent:
    defaults = dict(
        id="c2",
        weekly_plan_id="wp1",
        version=2,
        content={"theme": "秋", "_audit": {"action": "save"}},
        editor_id="tch1",
        editor_role="owner",
        created_at=_NOW,
    )
    defaults.update(kw)
    row = WeeklyPlanContent()
    for key, value in defaults.items():
        setattr(row, key, value)
    return row


def make_confirmed(**kw) -> WeeklyPlanConfirmedContent:
    defaults = dict(
        id="cf1",
        weekly_plan_id="wp1",
        version=1,
        draft_version=2,
        content={"theme": "秋"},
        facts={
            "missing": [{"kind": "empty_theme"}],
            "stale_sources": [],
            "ack_missing": True,
            "ack_stale": False,
            "note": None,
        },
        confirmed_by="tch1",
        created_at=_NOW,
    )
    defaults.update(kw)
    row = WeeklyPlanConfirmedContent()
    for key, value in defaults.items():
        setattr(row, key, value)
    return row


def make_write_result(*, created: bool = False, **kw) -> WeeklyPlanWriteResult:
    return WeeklyPlanWriteResult(
        plan=kw.get("plan", make_plan()),
        draft=kw.get("draft", make_draft()),
        confirmed=kw.get("confirmed"),
        created=created,
        refreshed_sources=kw.get("refreshed_sources"),
        facts=kw.get("facts"),
    )


def make_detail(**kw) -> dict:
    defaults = {
        "id": "wp1",
        "class_id": "cls1",
        "term_id": "ter1",
        "week_number": 3,
        "creator_id": "tch1",
        "owner_id": "tch1",
        "school_name": "阳光园",
        "class_name": "中一",
        "grade": "中班",
        "header_teacher_names": ["甲老师"],
        "caregiver_name": "王五",
        "confirmation_status": "never_confirmed",
        "needs_confirm": True,
        "draft": {
            "id": "c2",
            "version": 2,
            "content": {"theme": "秋"},
            "audit": {"action": "save"},
            "editor_id": "tch1",
            "editor_role": "owner",
            "created_at": _NOW,
        },
        "confirmed": None,
        "missing": [{"kind": "empty_theme"}],
        "stale_sources": [],
        "projection_pending": False,
        "source_candidates": [],
        "can_edit": True,
        "can_confirm": True,
        "refreshed_sources": None,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(kw)
    return defaults


def make_list_item(**kw) -> dict:
    defaults = {
        "id": "wp1",
        "term_id": "ter1",
        "week_number": 3,
        "creator_id": "tch1",
        "owner_id": "tch1",
        "draft_version": 2,
        "confirmed_version": 1,
        "needs_confirm": True,
        "updated_at": _NOW,
    }
    defaults.update(kw)
    return defaults


class RouteTestBase(unittest.TestCase):
    def setUp(self):
        self.db = mock.MagicMock()
        self.db.get.return_value = None
        app.dependency_overrides[get_db] = lambda: self.db

    def tearDown(self):
        app.dependency_overrides.clear()

    def login_account(self, account: Account) -> None:
        app.dependency_overrides[get_current_account] = lambda: account

    def login_snapshot(self, snapshot: AuthSnapshot) -> None:
        app.dependency_overrides[get_auth_snapshot] = lambda: snapshot

    def login_teacher(
        self, class_id: str | None = "cls1", account_id: str = "tch1"
    ) -> None:
        self.login_account(make_account("teacher", account_id))
        if class_id is not None:
            self.db.get.return_value = make_assignment(class_id, account_id)

    def login_admin(self) -> None:
        self.login_account(make_account("admin", "adm1"))

    def patch_read(self, name: str, **kw):
        patcher = mock.patch.object(weekly_plan_read_service, name, **kw)
        mocked = patcher.start()
        self.addCleanup(patcher.stop)
        return mocked

    def patch_write(self, name: str, **kw):
        patcher = mock.patch.object(weekly_plan_service, name, **kw)
        mocked = patcher.start()
        self.addCleanup(patcher.stop)
        return mocked


DETAIL_PATH = "/api/weekly-plans/wp1"
CONFIRM_PATH = "/api/weekly-plans/wp1/confirm"
REFRESH_PATH = "/api/weekly-plans/wp1/refresh-sources"
CONFIRMATIONS_PATH = "/api/weekly-plans/wp1/confirmations"
CONFIRMATION_PATH = "/api/weekly-plans/wp1/confirmations/1"
ALL_PATHS = (
    "GET /api/weekly-plans",
    "POST /api/weekly-plans",
    f"GET {DETAIL_PATH}",
    f"PATCH {DETAIL_PATH}",
    f"POST {REFRESH_PATH}",
    f"POST {CONFIRM_PATH}",
    f"GET {CONFIRMATIONS_PATH}",
    f"GET {CONFIRMATION_PATH}",
)

_CREATE_PAYLOAD = {"term_id": "ter1", "week_number": 3}
_CONFIRM_PAYLOAD = {
    "expected_draft_version": 2,
    "acknowledge_missing": True,
    "acknowledge_stale": True,
}


class AuthenticationTests(RouteTestBase):
    def test_all_eight_routes_without_session_are_401(self):
        bodies = {
            "POST /api/weekly-plans": _CREATE_PAYLOAD,
            f"PATCH {DETAIL_PATH}": {"expected_draft_version": 2},
            f"POST {REFRESH_PATH}": {"expected_draft_version": 2},
            f"POST {CONFIRM_PATH}": _CONFIRM_PAYLOAD,
        }
        for entry in ALL_PATHS:
            method, path = entry.split(" ", 1)
            payload = bodies.get(entry)
            if payload is None and method == "POST":
                payload = {}
            with self.subTest(entry=entry):
                status, _, body = api_request(method, path, payload=payload)
                self.assertEqual(status, 401)
                self.assertEqual(error_code(body), "AUTH_REQUIRED")


class ListPermissionTests(RouteTestBase):
    def test_pending_teacher_is_403(self):
        self.login_teacher(class_id=None)
        list_plans = self.patch_read("list_plans")
        status, _, body = api_request("GET", "/api/weekly-plans")
        self.assertEqual(status, 403)
        self.assertEqual(error_code(body), "FORBIDDEN")
        list_plans.assert_not_called()

    def test_teacher_reads_own_class_with_defaults(self):
        self.login_teacher(class_id="cls1")
        list_plans = self.patch_read(
            "list_plans", return_value=([make_list_item()], 1)
        )
        status, _, body = api_request("GET", "/api/weekly-plans")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["limit"], 20)
        self.assertEqual(data["items"][0]["id"], "wp1")
        kwargs = list_plans.call_args.kwargs
        self.assertEqual(kwargs["class_id"], "cls1")
        self.assertIsNone(kwargs["term_id"])
        self.assertEqual(kwargs["offset"], 0)
        self.assertEqual(kwargs["limit"], 20)

    def test_teacher_term_id_filter_passed_and_validated(self):
        self.login_teacher(class_id="cls1")
        list_plans = self.patch_read(
            "list_plans", return_value=([], 0)
        )
        status, _, _ = api_request(
            "GET", "/api/weekly-plans", query="term_id=ter1"
        )
        self.assertEqual(status, 200)
        self.assertEqual(list_plans.call_args.kwargs["term_id"], "ter1")
        list_plans.side_effect = WeeklyPlanTermNotFound()
        status, _, body = api_request(
            "GET", "/api/weekly-plans", query="term_id=nope"
        )
        self.assertEqual(status, 404)
        self.assertEqual(error_code(body), "TERM_NOT_FOUND")

    def test_teacher_must_not_pass_class_id(self):
        self.login_teacher(class_id="cls1")
        list_plans = self.patch_read("list_plans")
        status, _, body = api_request(
            "GET", "/api/weekly-plans", query="class_id=cls2"
        )
        self.assertEqual(status, 422)
        self.assertEqual(error_code(body), "VALIDATION_ERROR")
        list_plans.assert_not_called()

    def test_admin_must_pass_class_id(self):
        self.login_admin()
        list_plans = self.patch_read("list_plans")
        status, _, body = api_request("GET", "/api/weekly-plans")
        self.assertEqual(status, 422)
        self.assertEqual(error_code(body), "VALIDATION_ERROR")
        list_plans.assert_not_called()

    def test_admin_list_uses_explicit_class(self):
        self.login_admin()
        list_plans = self.patch_read(
            "list_plans", return_value=([make_list_item()], 1)
        )
        status, _, _ = api_request(
            "GET", "/api/weekly-plans", query="class_id=cls9"
        )
        self.assertEqual(status, 200)
        self.assertEqual(list_plans.call_args.kwargs["class_id"], "cls9")

    def test_paging_bounds_enforced(self):
        self.login_teacher(class_id="cls1")
        for query in ("limit=101", "limit=0", "offset=-1"):
            with self.subTest(query=query):
                status, _, body = api_request(
                    "GET", "/api/weekly-plans", query=query
                )
                self.assertEqual(status, 422)
                self.assertEqual(error_code(body), "VALIDATION_ERROR")


class DetailTests(RouteTestBase):
    def test_teacher_same_class_reads_detail(self):
        self.login_teacher(class_id="cls1")
        get_detail = self.patch_read("get_detail", return_value=make_detail())
        status, _, body = api_request("GET", DETAIL_PATH)
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["school_name"], "阳光园")
        self.assertEqual(data["confirmation_status"], "never_confirmed")
        self.assertTrue(data["can_confirm"])
        self.assertFalse(data["projection_pending"])
        self.assertNotIn("deleted_at", data)
        self.assertNotIn("_audit", data["draft"]["content"])
        kwargs = get_detail.call_args.kwargs
        self.assertEqual(kwargs["class_id"], "cls1")
        self.assertEqual(kwargs["account_id"], "tch1")
        self.assertEqual(kwargs["role"], "teacher")

    def test_teacher_cross_class_is_403(self):
        self.login_teacher(class_id="cls1")
        self.patch_read(
            "get_detail", side_effect=WeeklyPlanForbidden()
        )
        status, _, body = api_request("GET", DETAIL_PATH)
        self.assertEqual(status, 403)
        self.assertEqual(error_code(body), "FORBIDDEN")

    def test_pending_teacher_is_403(self):
        self.login_teacher(class_id=None)
        get_detail = self.patch_read("get_detail")
        status, _, body = api_request("GET", DETAIL_PATH)
        self.assertEqual(status, 403)
        self.assertEqual(error_code(body), "FORBIDDEN")
        get_detail.assert_not_called()

    def test_teacher_must_not_pass_class_id(self):
        self.login_teacher(class_id="cls1")
        get_detail = self.patch_read("get_detail")
        status, _, body = api_request("GET", DETAIL_PATH, query="class_id=cls1")
        self.assertEqual(status, 422)
        self.assertEqual(error_code(body), "VALIDATION_ERROR")
        get_detail.assert_not_called()

    def test_admin_without_class_id_is_422(self):
        self.login_admin()
        get_detail = self.patch_read("get_detail")
        status, _, body = api_request("GET", DETAIL_PATH)
        self.assertEqual(status, 422)
        self.assertEqual(error_code(body), "VALIDATION_ERROR")
        get_detail.assert_not_called()

    def test_admin_class_mismatch_is_404(self):
        self.login_admin()
        self.patch_read("get_detail", side_effect=WeeklyPlanNotFound())
        status, _, body = api_request("GET", DETAIL_PATH, query="class_id=cls1")
        self.assertEqual(status, 404)
        self.assertEqual(error_code(body), "WEEKLY_PLAN_NOT_FOUND")

    def test_unknown_id_is_404(self):
        self.login_teacher(class_id="cls1")
        self.patch_read("get_detail", side_effect=WeeklyPlanNotFound())
        status, _, body = api_request(
            "GET", "/api/weekly-plans/nope"
        )
        self.assertEqual(status, 404)
        self.assertEqual(error_code(body), "WEEKLY_PLAN_NOT_FOUND")

    def test_term_missing_on_detail_is_404(self):
        self.login_teacher(class_id="cls1")
        self.patch_read("get_detail", side_effect=WeeklyPlanTermNotFound())
        status, _, body = api_request("GET", DETAIL_PATH)
        self.assertEqual(status, 404)
        self.assertEqual(error_code(body), "TERM_NOT_FOUND")

    def test_broken_pointer_is_503(self):
        self.login_teacher(class_id="cls1")
        self.patch_read("get_detail", side_effect=WeeklyPlanDataError())
        status, _, body = api_request("GET", DETAIL_PATH)
        self.assertEqual(status, 503)
        self.assertEqual(error_code(body), "SERVICE_UNAVAILABLE")

    def test_config_gap_is_503(self):
        self.login_teacher(class_id="cls1")
        self.patch_read("get_detail", side_effect=ConfigServiceError())
        status, _, body = api_request("GET", DETAIL_PATH)
        self.assertEqual(status, 503)
        self.assertEqual(error_code(body), "SERVICE_UNAVAILABLE")

    def test_auth_required_from_service_is_401(self):
        self.login_teacher(class_id="cls1")
        self.patch_read("get_detail", side_effect=auth_service.AuthRequired())
        status, _, body = api_request("GET", DETAIL_PATH)
        self.assertEqual(status, 401)
        self.assertEqual(error_code(body), "AUTH_REQUIRED")


class CreateTests(RouteTestBase):
    def _create(
        self, payload: dict, *, query: str = ""
    ) -> tuple[int, dict | None, bytes]:
        status, _, body = api_request(
            "POST", "/api/weekly-plans", query=query, payload=payload
        )
        return status, json.loads(body) if body else None, body

    def test_teacher_create_returns_201_detail(self):
        self.login_snapshot(make_snapshot("teacher"))
        create = self.patch_write(
            "create_or_open_weekly_plan",
            return_value=make_write_result(created=True),
        )
        assemble = self.patch_read(
            "assemble_from_result", return_value=make_detail()
        )
        status, data, _ = self._create(
            {"term_id": "ter1", "week_number": 3, "theme": "秋"}
        )
        self.assertEqual(status, 201)
        self.assertEqual(data["id"], "wp1")
        kwargs = create.call_args.kwargs
        self.assertEqual(kwargs["term_id"], "ter1")
        self.assertEqual(kwargs["week_number"], 3)
        self.assertEqual(kwargs["theme"], "秋")
        self.assertIsNone(kwargs["class_id"])
        self.assertEqual(assemble.call_args.kwargs["account_id"], "tch1")
        self.assertEqual(assemble.call_args.kwargs["role"], "teacher")

    def test_duplicate_create_returns_200_opening_existing(self):
        self.login_snapshot(make_snapshot("teacher"))
        self.patch_write(
            "create_or_open_weekly_plan",
            return_value=make_write_result(created=False),
        )
        self.patch_read("assemble_from_result", return_value=make_detail())
        status, data, _ = self._create(_CREATE_PAYLOAD)
        self.assertEqual(status, 200)
        self.assertEqual(data["owner_id"], "tch1")

    def test_teacher_class_id_presence_matrix(self):
        """Teacher: omitted accepted; explicit null or value both 422."""
        self.login_snapshot(make_snapshot("teacher"))
        create = self.patch_write("create_or_open_weekly_plan")
        self.patch_read(
            "assemble_from_result", return_value=make_detail()
        )
        for payload in (
            {"term_id": "ter1", "week_number": 3, "class_id": None},
            {"term_id": "ter1", "week_number": 3, "class_id": "cls1"},
        ):
            with self.subTest(payload=payload):
                status, _, body = self._create(payload)
                self.assertEqual(status, 422)
                self.assertEqual(error_code(body), "VALIDATION_ERROR")
                create.assert_not_called()

    def test_admin_create_is_403_with_or_without_class_id(self):
        self.login_snapshot(make_snapshot("admin", account_id="adm1"))
        create = self.patch_write(
            "create_or_open_weekly_plan",
            side_effect=WeeklyPlanForbidden("管理员不能创建周计划"),
        )
        for payload in (_CREATE_PAYLOAD, {**_CREATE_PAYLOAD, "class_id": "cls1"}):
            with self.subTest(payload=payload):
                status, _, body = self._create(payload)
                self.assertEqual(status, 403)
                self.assertEqual(error_code(body), "FORBIDDEN")
        self.assertEqual(create.call_count, 2)

    def test_teacher_class_id_query_presence_is_422(self):
        """Teacher: ``?class_id=cls2`` and empty ``?class_id=`` both 422."""
        self.login_snapshot(make_snapshot("teacher"))
        create = self.patch_write("create_or_open_weekly_plan")
        for query in ("class_id=cls2", "class_id="):
            with self.subTest(query=query):
                status, _, body = self._create(_CREATE_PAYLOAD, query=query)
                self.assertEqual(status, 422)
                self.assertEqual(error_code(body), "VALIDATION_ERROR")
        create.assert_not_called()

    def test_admin_create_with_class_id_query_still_403(self):
        self.login_snapshot(make_snapshot("admin", account_id="adm1"))
        create = self.patch_write(
            "create_or_open_weekly_plan",
            side_effect=WeeklyPlanForbidden("管理员不能创建周计划"),
        )
        for query in ("class_id=cls1", "class_id="):
            with self.subTest(query=query):
                status, _, body = self._create(_CREATE_PAYLOAD, query=query)
                self.assertEqual(status, 403)
                self.assertEqual(error_code(body), "FORBIDDEN")
        self.assertEqual(create.call_count, 2)

    def test_extra_body_field_is_422(self):
        self.login_snapshot(make_snapshot("teacher"))
        create = self.patch_write("create_or_open_weekly_plan")
        status, _, body = self._create({**_CREATE_PAYLOAD, "owner_id": "x"})
        self.assertEqual(status, 422)
        self.assertEqual(error_code(body), "VALIDATION_ERROR")
        create.assert_not_called()

    def test_week_number_schema_bounds(self):
        self.login_snapshot(make_snapshot("teacher"))
        create = self.patch_write("create_or_open_weekly_plan")
        for week in (0, True, "3"):
            with self.subTest(week=week):
                status, _, body = self._create(
                    {"term_id": "ter1", "week_number": week}
                )
                self.assertEqual(status, 422)
                self.assertEqual(error_code(body), "VALIDATION_ERROR")
        create.assert_not_called()

    def test_empty_theme_is_not_422(self):
        self.login_snapshot(make_snapshot("teacher"))
        create = self.patch_write(
            "create_or_open_weekly_plan",
            return_value=make_write_result(created=True),
        )
        self.patch_read("assemble_from_result", return_value=make_detail())
        status, _, _ = self._create(
            {"term_id": "ter1", "week_number": 3, "theme": ""}
        )
        self.assertEqual(status, 201)
        self.assertEqual(create.call_args.kwargs["theme"], "")

    def test_term_not_found_maps_404(self):
        self.login_snapshot(make_snapshot("teacher"))
        self.patch_write(
            "create_or_open_weekly_plan",
            side_effect=WeeklyPlanTermNotFound(),
        )
        status, _, body = self._create(_CREATE_PAYLOAD)
        self.assertEqual(status, 404)
        self.assertEqual(error_code(body), "TERM_NOT_FOUND")

    def test_pending_teacher_forbidden_maps_403(self):
        self.login_snapshot(make_snapshot("teacher"))
        self.patch_write(
            "create_or_open_weekly_plan",
            side_effect=WeeklyPlanForbidden(),
        )
        status, _, body = self._create(_CREATE_PAYLOAD)
        self.assertEqual(status, 403)
        self.assertEqual(error_code(body), "FORBIDDEN")

    def test_week_out_of_term_maps_422(self):
        self.login_snapshot(make_snapshot("teacher"))
        self.patch_write(
            "create_or_open_weekly_plan",
            side_effect=WeeklyPlanValidationError("week_number 超出学期范围"),
        )
        status, _, body = self._create(_CREATE_PAYLOAD)
        self.assertEqual(status, 422)
        self.assertEqual(error_code(body), "VALIDATION_ERROR")

    def test_school_settings_gap_maps_503(self):
        self.login_snapshot(make_snapshot("teacher"))
        self.patch_write(
            "create_or_open_weekly_plan",
            side_effect=ConfigServiceError(),
        )
        status, _, body = self._create(_CREATE_PAYLOAD)
        self.assertEqual(status, 503)
        self.assertEqual(error_code(body), "SERVICE_UNAVAILABLE")


class PatchTests(RouteTestBase):
    def _patch(self, payload: dict, *, query: str = "") -> tuple[int, bytes]:
        status, _, body = api_request(
            "PATCH", DETAIL_PATH, query=query, payload=payload
        )
        return status, body

    def _mock_save(self, **kw):
        save = self.patch_write("save_weekly_plan", **kw)
        self.patch_read("assemble_from_result", return_value=make_detail())
        return save

    def test_omitted_optionals_produce_empty_patch(self):
        self.login_snapshot(make_snapshot("teacher"))
        save = self._mock_save(return_value=make_write_result())
        status, body = self._patch({"expected_draft_version": 2})
        self.assertEqual(status, 200)
        kwargs = save.call_args.kwargs
        self.assertEqual(kwargs["expected_draft_version"], 2)
        self.assertEqual(kwargs["patch"], {})
        self.assertIsNone(kwargs["class_id"])

    def test_explicit_null_theme_and_focus_pass_through(self):
        self.login_snapshot(make_snapshot("teacher"))
        save = self._mock_save(return_value=make_write_result())
        status, _ = self._patch(
            {
                "expected_draft_version": 2,
                "theme": None,
                "focus_area": None,
                "weekly_columns": {"key_week_focus": "重点"},
            }
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            save.call_args.kwargs["patch"],
            {
                "theme": None,
                "focus_area": None,
                "weekly_columns": {"key_week_focus": "重点"},
            },
        )

    def test_server_owned_layers_rejected_by_schema(self):
        self.login_snapshot(make_snapshot("teacher"))
        save = self.patch_write("save_weekly_plan")
        for extra in ("source", "effective", "materials"):
            with self.subTest(extra=extra):
                status, body = self._patch(
                    {"expected_draft_version": 2, extra: {}}
                )
                self.assertEqual(status, 422)
                self.assertEqual(error_code(body), "VALIDATION_ERROR")
        save.assert_not_called()

    def test_class_id_in_body_rejected(self):
        self.login_snapshot(make_snapshot("teacher"))
        save = self.patch_write("save_weekly_plan")
        status, body = self._patch(
            {"expected_draft_version": 2, "class_id": "cls1"}
        )
        self.assertEqual(status, 422)
        self.assertEqual(error_code(body), "VALIDATION_ERROR")
        save.assert_not_called()

    def test_expected_version_strict_bounds(self):
        self.login_snapshot(make_snapshot("teacher"))
        save = self.patch_write("save_weekly_plan")
        for bad in (True, False, 1.0, "2", 0):
            with self.subTest(bad=bad):
                status, body = self._patch({"expected_draft_version": bad})
                self.assertEqual(status, 422)
                self.assertEqual(error_code(body), "VALIDATION_ERROR")
        save.assert_not_called()

    def test_version_conflict_maps_409(self):
        self.login_snapshot(make_snapshot("teacher"))
        self._mock_save(side_effect=WeeklyPlanVersionConflict())
        status, body = self._patch({"expected_draft_version": 2})
        self.assertEqual(status, 409)
        self.assertEqual(error_code(body), "VERSION_CONFLICT")

    def test_same_class_non_owner_maps_403(self):
        self.login_snapshot(make_snapshot("teacher", account_id="tch2"))
        self._mock_save(side_effect=WeeklyPlanForbidden())
        status, body = self._patch({"expected_draft_version": 2})
        self.assertEqual(status, 403)
        self.assertEqual(error_code(body), "FORBIDDEN")

    def test_admin_save_requires_class_id_query(self):
        self.login_snapshot(make_snapshot("admin", account_id="adm1"))
        save = self.patch_write(
            "save_weekly_plan",
            side_effect=WeeklyPlanValidationError("管理员请求必须包含 class_id"),
        )
        self.patch_read("assemble_from_result", return_value=make_detail())
        status, body = self._patch({"expected_draft_version": 2})
        self.assertEqual(status, 422)
        self.assertEqual(error_code(body), "VALIDATION_ERROR")
        self.assertIsNone(save.call_args.kwargs["class_id"])

    def test_admin_save_with_class_id_passes_through_to_service(self):
        self.login_snapshot(make_snapshot("admin", account_id="adm1"))
        save = self._mock_save(return_value=make_write_result())
        status, _ = self._patch(
            {"expected_draft_version": 2, "theme": "新"},
            query="class_id=cls1",
        )
        self.assertEqual(status, 200)
        self.assertEqual(save.call_args.kwargs["class_id"], "cls1")

    def test_admin_class_mismatch_maps_404(self):
        self.login_snapshot(make_snapshot("admin", account_id="adm1"))
        self._mock_save(side_effect=WeeklyPlanNotFound())
        status, body = self._patch(
            {"expected_draft_version": 2}, query="class_id=cls9"
        )
        self.assertEqual(status, 404)
        self.assertEqual(error_code(body), "WEEKLY_PLAN_NOT_FOUND")

    def test_not_found_maps_404(self):
        self.login_snapshot(make_snapshot("teacher"))
        self._mock_save(side_effect=WeeklyPlanNotFound())
        status, body = self._patch({"expected_draft_version": 2})
        self.assertEqual(status, 404)
        self.assertEqual(error_code(body), "WEEKLY_PLAN_NOT_FOUND")

    def test_content_validation_maps_422(self):
        self.login_snapshot(make_snapshot("teacher"))
        from app.services.weekly_plan_content import ContentValidationError

        self._mock_save(side_effect=ContentValidationError("来源不存在"))
        status, body = self._patch({"expected_draft_version": 2})
        self.assertEqual(status, 422)
        self.assertEqual(error_code(body), "VALIDATION_ERROR")


class RefreshTests(RouteTestBase):
    def test_refresh_returns_detail_with_refreshed_sources(self):
        self.login_snapshot(make_snapshot("teacher"))
        refreshed = [
            {
                "slot": "collective_1",
                "kind": "refreshed",
                "from": {"content_id": "c1", "content_version": 1},
                "to": {"content_id": "c2", "content_version": 2},
            }
        ]
        refresh = self.patch_write(
            "refresh_weekly_sources",
            return_value=make_write_result(refreshed_sources=refreshed),
        )
        assemble = self.patch_read(
            "assemble_from_result",
            return_value=make_detail(refreshed_sources=refreshed),
        )
        status, _, body = api_request(
            "POST", REFRESH_PATH, payload={"expected_draft_version": 2}
        )
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["refreshed_sources"][0]["slot"], "collective_1")
        self.assertEqual(
            refresh.call_args.kwargs["expected_draft_version"], 2
        )
        self.assertEqual(
            assemble.call_args.kwargs["refreshed_sources"], refreshed
        )
        self.assertIsNone(assemble.call_args.kwargs.get("class_id", None))

    def test_refresh_version_conflict_maps_409(self):
        self.login_snapshot(make_snapshot("teacher"))
        self.patch_write(
            "refresh_weekly_sources",
            side_effect=WeeklyPlanVersionConflict(),
        )
        self.patch_read("assemble_from_result", return_value=make_detail())
        status, _, body = api_request(
            "POST", REFRESH_PATH, payload={"expected_draft_version": 2}
        )
        self.assertEqual(status, 409)
        self.assertEqual(error_code(body), "VERSION_CONFLICT")

    def test_refresh_forbidden_maps_403(self):
        self.login_snapshot(make_snapshot("teacher", account_id="tch2"))
        self.patch_write(
            "refresh_weekly_sources", side_effect=WeeklyPlanForbidden()
        )
        self.patch_read("assemble_from_result", return_value=make_detail())
        status, _, body = api_request(
            "POST", REFRESH_PATH, payload={"expected_draft_version": 2}
        )
        self.assertEqual(status, 403)
        self.assertEqual(error_code(body), "FORBIDDEN")

    def test_refresh_schema_rejects_extra_and_bad_version(self):
        self.login_snapshot(make_snapshot("teacher"))
        refresh = self.patch_write("refresh_weekly_sources")
        for payload in (
            {},
            {"expected_draft_version": 0},
            {"expected_draft_version": True},
            {"expected_draft_version": 2, "theme": "x"},
        ):
            with self.subTest(payload=payload):
                status, _, body = api_request(
                    "POST", REFRESH_PATH, payload=payload
                )
                self.assertEqual(status, 422)
                self.assertEqual(error_code(body), "VALIDATION_ERROR")
        refresh.assert_not_called()


class ConfirmTests(RouteTestBase):
    def _confirm(
        self, payload: dict, *, query: str = ""
    ) -> tuple[int, dict | None, bytes]:
        status, _, body = api_request(
            "POST", CONFIRM_PATH, query=query, payload=payload
        )
        return status, json.loads(body) if body else None, body

    def test_owner_confirm_returns_201_confirmation_resource(self):
        self.login_snapshot(make_snapshot("teacher"))
        confirm = self.patch_write(
            "confirm_weekly_plan",
            return_value=make_write_result(confirmed=make_confirmed()),
        )
        status, data, _ = self._confirm(
            dict(_CONFIRM_PAYLOAD, note="确认说明")
        )
        self.assertEqual(status, 201)
        self.assertEqual(data["version"], 1)
        self.assertEqual(data["draft_version"], 2)
        self.assertEqual(data["facts"]["ack_missing"], True)
        self.assertEqual(data["confirmed_by"], "tch1")
        self.assertNotIn("_audit", data["content"])
        kwargs = confirm.call_args.kwargs
        self.assertEqual(kwargs["expected_draft_version"], 2)
        self.assertTrue(kwargs["acknowledge_missing"])
        self.assertTrue(kwargs["acknowledge_stale"])
        self.assertEqual(kwargs["note"], "确认说明")

    def test_note_omitted_passes_none(self):
        self.login_snapshot(make_snapshot("teacher"))
        confirm = self.patch_write(
            "confirm_weekly_plan",
            return_value=make_write_result(confirmed=make_confirmed()),
        )
        status, data, _ = self._confirm(_CONFIRM_PAYLOAD)
        self.assertEqual(status, 201)
        self.assertIsNone(confirm.call_args.kwargs["note"])
        self.assertIsNone(data["facts"]["note"])

    def test_admin_confirm_is_403(self):
        self.login_snapshot(make_snapshot("admin", account_id="adm1"))
        self.patch_write(
            "confirm_weekly_plan",
            side_effect=WeeklyPlanForbidden("管理员不能确认周计划"),
        )
        status, _, body = self._confirm(
            _CONFIRM_PAYLOAD, query="class_id=cls1"
        )
        self.assertEqual(status, 403)
        self.assertEqual(error_code(body), "FORBIDDEN")

    def test_same_class_non_owner_confirm_is_403(self):
        self.login_snapshot(make_snapshot("teacher", account_id="tch2"))
        self.patch_write(
            "confirm_weekly_plan", side_effect=WeeklyPlanForbidden()
        )
        status, _, body = self._confirm(_CONFIRM_PAYLOAD)
        self.assertEqual(status, 403)
        self.assertEqual(error_code(body), "FORBIDDEN")

    def test_version_conflict_maps_409(self):
        self.login_snapshot(make_snapshot("teacher"))
        self.patch_write(
            "confirm_weekly_plan", side_effect=WeeklyPlanVersionConflict()
        )
        status, _, body = self._confirm(_CONFIRM_PAYLOAD)
        self.assertEqual(status, 409)
        self.assertEqual(error_code(body), "VERSION_CONFLICT")

    def test_ack_required_returns_409_with_system_facts(self):
        self.login_snapshot(make_snapshot("teacher"))
        facts = {
            "missing": [{"kind": "outdoor_slot", "slot": "collective_2"}],
            "stale_sources": [
                {
                    "slot": "collective_1",
                    "draft": {"content_id": "c1", "content_version": 1},
                    "current": {"content_id": "c9", "content_version": 9},
                }
            ],
            "ack_missing": False,
            "ack_stale": False,
            "note": None,
        }
        self.patch_write(
            "confirm_weekly_plan",
            side_effect=WeeklyPlanConfirmAckRequired(facts=facts),
        )
        status, data, _ = self._confirm(
            dict(_CONFIRM_PAYLOAD, acknowledge_missing=False)
        )
        self.assertEqual(status, 409)
        self.assertEqual(data["error"]["code"], "CONFIRM_ACK_REQUIRED")
        self.assertEqual(
            data["error"]["facts"]["missing"],
            [{"kind": "outdoor_slot", "slot": "collective_2"}],
        )
        self.assertEqual(
            data["error"]["facts"]["stale_sources"][0]["draft"][
                "content_version"
            ],
            1,
        )
        self.assertEqual(data["error"]["facts"]["stale_sources"][0]["current"]["content_version"], 9)

    def test_confirm_schema_matrix(self):
        self.login_snapshot(make_snapshot("teacher"))
        confirm = self.patch_write("confirm_weekly_plan")
        bad_payloads = [
            {"expected_draft_version": 2},
            {"expected_draft_version": 2, "acknowledge_missing": True},
            dict(_CONFIRM_PAYLOAD, acknowledge_missing=1),
            dict(_CONFIRM_PAYLOAD, acknowledge_stale="true"),
            dict(_CONFIRM_PAYLOAD, bogus=True),
            dict(_CONFIRM_PAYLOAD, expected_draft_version=0),
            dict(_CONFIRM_PAYLOAD, class_id="cls1"),
        ]
        for payload in bad_payloads:
            with self.subTest(payload=payload):
                status, _, body = self._confirm(payload)
                self.assertEqual(status, 422)
                self.assertEqual(error_code(body), "VALIDATION_ERROR")
        confirm.assert_not_called()


class ConfirmationHistoryTests(RouteTestBase):
    def test_list_returns_summaries(self):
        self.login_teacher(class_id="cls1")
        list_conf = self.patch_read(
            "list_confirmations",
            return_value={
                "items": [
                    {
                        "version": 1,
                        "draft_version": 2,
                        "confirmed_by": "tch1",
                        "facts": {"missing": [], "stale_sources": []},
                        "created_at": _NOW,
                    }
                ],
                "total": 1,
            },
        )
        status, _, body = api_request("GET", CONFIRMATIONS_PATH)
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["version"], 1)
        kwargs = list_conf.call_args.kwargs
        self.assertEqual(kwargs["class_id"], "cls1")
        self.assertEqual(kwargs["role"], "teacher")

    def test_get_single_confirmation_returns_content_and_facts(self):
        self.login_teacher(class_id="cls1")
        self.patch_read(
            "get_confirmation",
            return_value={
                "id": "cf1",
                "weekly_plan_id": "wp1",
                "version": 1,
                "draft_version": 2,
                "content": {"theme": "秋"},
                "facts": {"missing": [], "stale_sources": []},
                "confirmed_by": "tch1",
                "created_at": _NOW,
            },
        )
        status, _, body = api_request("GET", CONFIRMATION_PATH)
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["version"], 1)
        self.assertEqual(data["content"]["theme"], "秋")

    def test_admin_requires_class_context_on_reads(self):
        self.login_admin()
        list_conf = self.patch_read("list_confirmations")
        get_conf = self.patch_read("get_confirmation")
        for path in (CONFIRMATIONS_PATH, CONFIRMATION_PATH):
            with self.subTest(path=path):
                status, _, body = api_request("GET", path)
                self.assertEqual(status, 422)
                self.assertEqual(error_code(body), "VALIDATION_ERROR")
        list_conf.assert_not_called()
        get_conf.assert_not_called()

    def test_admin_mismatch_maps_404(self):
        self.login_admin()
        self.patch_read(
            "get_confirmation", side_effect=WeeklyPlanNotFound()
        )
        status, _, body = api_request(
            "GET", CONFIRMATION_PATH, query="class_id=cls9"
        )
        self.assertEqual(status, 404)
        self.assertEqual(error_code(body), "WEEKLY_PLAN_NOT_FOUND")

    def test_cross_class_teacher_maps_403(self):
        self.login_teacher(class_id="cls1")
        self.patch_read(
            "list_confirmations", side_effect=WeeklyPlanForbidden()
        )
        status, _, body = api_request("GET", CONFIRMATIONS_PATH)
        self.assertEqual(status, 403)
        self.assertEqual(error_code(body), "FORBIDDEN")

    def test_teacher_must_not_pass_class_id(self):
        self.login_teacher(class_id="cls1")
        get_conf = self.patch_read("get_confirmation")
        status, _, body = api_request(
            "GET", CONFIRMATION_PATH, query="class_id=cls1"
        )
        self.assertEqual(status, 422)
        self.assertEqual(error_code(body), "VALIDATION_ERROR")
        get_conf.assert_not_called()

    def test_unknown_version_is_404(self):
        self.login_teacher(class_id="cls1")
        self.patch_read(
            "get_confirmation", side_effect=WeeklyPlanNotFound()
        )
        status, _, body = api_request(
            "GET", "/api/weekly-plans/wp1/confirmations/9"
        )
        self.assertEqual(status, 404)
        self.assertEqual(error_code(body), "WEEKLY_PLAN_NOT_FOUND")

    def test_version_zero_is_422(self):
        self.login_teacher(class_id="cls1")
        get_conf = self.patch_read("get_confirmation")
        status, _, body = api_request(
            "GET", "/api/weekly-plans/wp1/confirmations/0"
        )
        self.assertEqual(status, 422)
        self.assertEqual(error_code(body), "VALIDATION_ERROR")
        get_conf.assert_not_called()


class RouteRegistrationTests(unittest.TestCase):
    def test_eight_routes_registered(self):
        paths = app.openapi()["paths"]
        expected = {
            "/api/weekly-plans": {"get", "post"},
            "/api/weekly-plans/{plan_id}": {"get", "patch"},
            "/api/weekly-plans/{plan_id}/refresh-sources": {"post"},
            "/api/weekly-plans/{plan_id}/confirm": {"post"},
            "/api/weekly-plans/{plan_id}/confirmations": {"get"},
            "/api/weekly-plans/{plan_id}/confirmations/{version}": {"get"},
        }
        for path, methods in expected.items():
            with self.subTest(path=path):
                self.assertIn(path, paths)
                self.assertEqual(set(paths[path]), methods)

    def test_no_delete_recover_ai_export_or_takeover_routes(self):
        paths = app.openapi()["paths"]
        for path, operations in paths.items():
            if "weekly-plans" not in path:
                continue
            with self.subTest(path=path):
                self.assertNotIn("delete", operations)
                self.assertNotIn("put", operations)
                self.assertFalse(path.endswith("/recover"))
                self.assertFalse(path.endswith("/export"))
                self.assertNotIn("/ai", path)
                self.assertNotIn("/takeover", path)


if __name__ == "__main__":
    unittest.main()
