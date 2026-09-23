"""No-DB ASGI tests for I3 daily plan / weekly sync routes.

Drives the real FastAPI app (routing, middleware, validation, response
models) with ``get_db`` / ``get_current_account`` / ``get_auth_snapshot``
dependency overrides and mocked I3 services — no database, no MySQL, no
SQLite. Covers the spec permission matrix, error codes, 201/200 create
semantics and serialization rules for slice 3.
"""

import asyncio
import json
import os

os.environ["APP_DISABLE_DOTENV"] = "1"
os.environ["ALLOWED_ORIGINS"] = "http://localhost:5173,http://127.0.0.1:5173"

import unittest
from datetime import date, datetime
from unittest import mock

from app.database import get_db
from app.deps import get_auth_snapshot, get_current_account
from app.main import app
from app.models import (
    Account,
    DailyPlan,
    DailyPlanContent,
    TeacherAssignment,
    WeeklyPlanSyncState,
)
from app.services import auth_service, daily_plan_service
from app.services.auth_service import AuthSnapshot
from app.services.daily_plan_content import ContentValidationError
from app.services.daily_plan_service import UNSET

_ORIGIN = "http://localhost:5173"
_NOW = datetime(2026, 9, 7, 8, 0, 0)


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


def make_plan(**kw) -> DailyPlan:
    defaults = dict(
        id="plan1",
        class_id="cls1",
        term_id="ter1",
        plan_date=date(2026, 9, 7),
        creator_id="tch1",
        week_number=2,
        weekday=1,
        current_content_id="cnt1",
        current_content_version=2,
        creator_display_name="甲老师",
        school_name="阳光园",
        class_name="小班甲",
        grade="small",
        deleted_at=None,
        deleted_by=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    defaults.update(kw)
    return DailyPlan(**defaults)


def make_content(**kw) -> DailyPlanContent:
    defaults = dict(
        id="cnt1",
        daily_plan_id="plan1",
        version=2,
        raw_lesson_plan="教案",
        split_baseline=None,
        adopted_content={
            "morning_games": [
                {
                    "group_id": "grp1",
                    "group_kind": "collective",
                    "games": [{"game_id": "gam1", "name": "跳绳"}],
                }
            ]
        },
        editor_id="tch1",
        created_at=_NOW,
    )
    defaults.update(kw)
    return DailyPlanContent(**defaults)


def make_summary(**kw) -> dict:
    defaults = {
        "status": "pending_projection",
        "has_pending_projection": True,
        "saved_dates": ["2026-09-07"],
        "missing_dates": ["2026-09-08", "2026-09-09"],
    }
    defaults.update(kw)
    return defaults


def make_sync_row(**kw) -> WeeklyPlanSyncState:
    defaults = dict(
        id="wss1",
        class_id="cls1",
        term_id="ter1",
        week_number=2,
        status="pending_projection",
        deterministic_themes=[
            {
                "date": "2026-09-07",
                "morning_talk_topic": "问好",
                "group_activity_theme": "主题",
            }
        ],
        game_source_manifest=[
            {
                "daily_plan_id": "plan1",
                "content_version": 2,
                "date": "2026-09-07",
                "group_id": "grp1",
                "game_id": "gam1",
                "context_kind": None,
            }
        ],
        current_week_source_manifest=[
            {
                "daily_plan_id": "plan1",
                "current_content_id": "cnt1",
                "current_content_version": 2,
                "date": "2026-09-07",
            }
        ],
        last_trigger_daily_plan_id="plan1",
        last_trigger_content_version=2,
        last_trigger_event="update",
        created_at=_NOW,
        updated_at=_NOW,
    )
    defaults.update(kw)
    return WeeklyPlanSyncState(**defaults)


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

    def patch_service(self, name: str, **kw):
        patcher = mock.patch.object(daily_plan_service, name, **kw)
        mocked = patcher.start()
        self.addCleanup(patcher.stop)
        return mocked


class AuthenticationTests(RouteTestBase):
    def test_get_list_without_session_is_401(self):
        status, _, body = api_request("GET", "/api/daily-plans")
        self.assertEqual(status, 401)
        self.assertEqual(error_code(body), "AUTH_REQUIRED")

    def test_post_without_session_is_401(self):
        status, _, body = api_request(
            "POST",
            "/api/daily-plans",
            payload={"plan_date": "2026-09-07"},
        )
        self.assertEqual(status, 401)
        self.assertEqual(error_code(body), "AUTH_REQUIRED")

    def test_patch_without_session_is_401(self):
        status, _, body = api_request(
            "PATCH",
            "/api/daily-plans/plan1",
            payload={"expected_content_version": 1},
        )
        self.assertEqual(status, 401)
        self.assertEqual(error_code(body), "AUTH_REQUIRED")

    def test_sync_state_without_session_is_401(self):
        status, _, body = api_request(
            "GET", "/api/weekly-plan-sync-states/cls1/ter1/2"
        )
        self.assertEqual(status, 401)
        self.assertEqual(error_code(body), "AUTH_REQUIRED")


class ListPermissionTests(RouteTestBase):
    def test_pending_teacher_is_403(self):
        self.login_teacher(class_id=None)
        list_plans = self.patch_service("list_plans")
        status, _, body = api_request("GET", "/api/daily-plans")
        self.assertEqual(status, 403)
        self.assertEqual(error_code(body), "FORBIDDEN")
        list_plans.assert_not_called()

    def test_teacher_reads_own_class_with_defaults(self):
        self.login_teacher(class_id="cls1")
        list_plans = self.patch_service(
            "list_plans", return_value=([make_plan()], 1)
        )
        status, _, body = api_request("GET", "/api/daily-plans")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["limit"], 20)
        self.assertEqual(data["items"][0]["id"], "plan1")
        kwargs = list_plans.call_args.kwargs
        self.assertEqual(kwargs["class_id"], "cls1")
        self.assertEqual(kwargs["offset"], 0)
        self.assertEqual(kwargs["limit"], 20)

    def test_teacher_must_not_pass_class_id(self):
        self.login_teacher(class_id="cls1")
        list_plans = self.patch_service("list_plans")
        status, _, body = api_request(
            "GET", "/api/daily-plans", query="class_id=cls2"
        )
        self.assertEqual(status, 422)
        self.assertEqual(error_code(body), "VALIDATION_ERROR")
        list_plans.assert_not_called()

    def test_teacher_must_not_pass_term_id(self):
        self.login_teacher(class_id="cls1")
        list_plans = self.patch_service("list_plans")
        status, _, body = api_request(
            "GET", "/api/daily-plans", query="term_id=ter1"
        )
        self.assertEqual(status, 422)
        self.assertEqual(error_code(body), "VALIDATION_ERROR")
        list_plans.assert_not_called()

    def test_admin_must_pass_class_id(self):
        self.login_admin()
        list_plans = self.patch_service("list_plans")
        status, _, body = api_request("GET", "/api/daily-plans")
        self.assertEqual(status, 422)
        self.assertEqual(error_code(body), "VALIDATION_ERROR")
        list_plans.assert_not_called()

    def test_admin_list_uses_explicit_class(self):
        self.login_admin()
        list_plans = self.patch_service(
            "list_plans", return_value=([make_plan()], 1)
        )
        status, _, _ = api_request(
            "GET", "/api/daily-plans", query="class_id=cls9"
        )
        self.assertEqual(status, 200)
        self.assertEqual(list_plans.call_args.kwargs["class_id"], "cls9")

    def test_paging_bounds_enforced(self):
        self.login_teacher(class_id="cls1")
        for query in ("limit=101", "limit=0", "offset=-1"):
            with self.subTest(query=query):
                status, _, body = api_request(
                    "GET", "/api/daily-plans", query=query
                )
                self.assertEqual(status, 422)
                self.assertEqual(error_code(body), "VALIDATION_ERROR")

    def test_invalid_date_range_maps_to_422(self):
        self.login_teacher(class_id="cls1")
        self.patch_service(
            "list_plans",
            side_effect=daily_plan_service.DailyPlanValidationError(
                "from 不能晚于 to"
            ),
        )
        status, _, body = api_request(
            "GET",
            "/api/daily-plans",
            query="from=2026-09-10&to=2026-09-01",
        )
        self.assertEqual(status, 422)
        self.assertEqual(error_code(body), "VALIDATION_ERROR")


class ByDateTests(RouteTestBase):
    def test_teacher_by_date_returns_full_out_with_summary(self):
        self.login_teacher(class_id="cls1")
        self.patch_service(
            "get_by_date", return_value=(make_plan(), make_content())
        )
        self.patch_service(
            "weekly_sync_summary", return_value=make_summary()
        )
        status, _, body = api_request(
            "GET", "/api/daily-plans/by-date", query="plan_date=2026-09-07"
        )
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["id"], "plan1")
        self.assertEqual(data["plan_date"], "2026-09-07")
        self.assertEqual(
            data["weekly_sync_state"]["saved_dates"], ["2026-09-07"]
        )
        self.assertNotIn("deleted_at", data)
        self.assertNotIn("deleted_by", data)

    def test_missing_plan_is_404(self):
        self.login_teacher(class_id="cls1")
        self.patch_service(
            "get_by_date",
            side_effect=daily_plan_service.DailyPlanNotFound(),
        )
        status, _, body = api_request(
            "GET", "/api/daily-plans/by-date", query="plan_date=2026-09-07"
        )
        self.assertEqual(status, 404)
        self.assertEqual(error_code(body), "DAILY_PLAN_NOT_FOUND")

    def test_admin_requires_class_context(self):
        self.login_admin()
        get_by_date = self.patch_service("get_by_date")
        status, _, body = api_request(
            "GET", "/api/daily-plans/by-date", query="plan_date=2026-09-07"
        )
        self.assertEqual(status, 422)
        self.assertEqual(error_code(body), "VALIDATION_ERROR")
        get_by_date.assert_not_called()

    def test_admin_by_date_uses_explicit_class(self):
        self.login_admin()
        get_by_date = self.patch_service(
            "get_by_date", return_value=(make_plan(), make_content())
        )
        self.patch_service(
            "weekly_sync_summary", return_value=make_summary()
        )
        status, _, _ = api_request(
            "GET",
            "/api/daily-plans/by-date",
            query="plan_date=2026-09-07&class_id=cls1",
        )
        self.assertEqual(status, 200)
        self.assertEqual(get_by_date.call_args.args[1], "cls1")


class GetByIdTests(RouteTestBase):
    def test_teacher_same_class_reads_and_keeps_game_ids(self):
        self.login_teacher(class_id="cls1")
        self.patch_service(
            "get", return_value=(make_plan(), make_content())
        )
        self.patch_service(
            "weekly_sync_summary", return_value=make_summary()
        )
        status, _, body = api_request("GET", "/api/daily-plans/plan1")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["school_name"], "阳光园")
        self.assertEqual(data["class_name"], "小班甲")
        self.assertEqual(data["grade"], "small")
        self.assertEqual(data["creator_display_name"], "甲老师")
        self.assertEqual(data["current_content_version"], 2)
        self.assertEqual(
            data["content"]["adopted_content"]["morning_games"][0]["games"][
                0
            ]["game_id"],
            "gam1",
        )
        self.assertNotIn("deleted_at", data)
        self.assertNotIn("deleted_by", data)

    def test_teacher_other_class_is_403_even_with_id(self):
        self.login_teacher(class_id="cls1")
        self.patch_service(
            "get",
            return_value=(
                make_plan(class_id="cls2"),
                make_content(),
            ),
        )
        summary = self.patch_service(
            "weekly_sync_summary", return_value=make_summary()
        )
        status, _, body = api_request("GET", "/api/daily-plans/plan1")
        self.assertEqual(status, 403)
        self.assertEqual(error_code(body), "FORBIDDEN")
        summary.assert_not_called()

    def test_admin_without_class_id_is_422(self):
        self.login_admin()
        get_plan = self.patch_service("get")
        status, _, body = api_request("GET", "/api/daily-plans/plan1")
        self.assertEqual(status, 422)
        self.assertEqual(error_code(body), "VALIDATION_ERROR")
        get_plan.assert_not_called()

    def test_admin_class_mismatch_is_404_not_cross_class_read(self):
        self.login_admin()
        self.patch_service(
            "get", return_value=(make_plan(class_id="cls2"), make_content())
        )
        summary = self.patch_service(
            "weekly_sync_summary", return_value=make_summary()
        )
        status, _, body = api_request(
            "GET", "/api/daily-plans/plan1", query="class_id=cls1"
        )
        self.assertEqual(status, 404)
        self.assertEqual(error_code(body), "DAILY_PLAN_NOT_FOUND")
        summary.assert_not_called()

    def test_admin_explicit_matching_class_reads(self):
        self.login_admin()
        self.patch_service(
            "get", return_value=(make_plan(), make_content())
        )
        self.patch_service(
            "weekly_sync_summary", return_value=make_summary()
        )
        status, _, body = api_request(
            "GET", "/api/daily-plans/plan1", query="class_id=cls1"
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["id"], "plan1")

    def test_unknown_id_is_404(self):
        self.login_teacher(class_id="cls1")
        self.patch_service(
            "get", side_effect=daily_plan_service.DailyPlanNotFound()
        )
        status, _, body = api_request("GET", "/api/daily-plans/nope")
        self.assertEqual(status, 404)
        self.assertEqual(error_code(body), "DAILY_PLAN_NOT_FOUND")

    def test_broken_pointer_is_503(self):
        self.login_teacher(class_id="cls1")
        self.patch_service(
            "get", side_effect=daily_plan_service.DailyPlanDataError()
        )
        status, _, body = api_request("GET", "/api/daily-plans/plan1")
        self.assertEqual(status, 503)
        self.assertEqual(error_code(body), "SERVICE_UNAVAILABLE")

    def test_teacher_must_not_pass_class_id_by_id(self):
        self.login_teacher(class_id="cls1")
        get_plan = self.patch_service("get")
        status, _, _ = api_request(
            "GET", "/api/daily-plans/plan1", query="class_id=cls1"
        )
        self.assertEqual(status, 422)
        get_plan.assert_not_called()


class CreateTests(RouteTestBase):
    def _create(
        self, payload: dict, *, query: str = ""
    ) -> tuple[int, dict | None, bytes]:
        status, _, body = api_request(
            "POST", "/api/daily-plans", query=query, payload=payload
        )
        return status, json.loads(body) if body else None, body

    def test_teacher_create_returns_201_with_week_summary(self):
        self.login_snapshot(make_snapshot("teacher"))
        create = self.patch_service(
            "create_or_open", return_value=(make_plan(), make_content(), True)
        )
        self.patch_service(
            "weekly_sync_summary", return_value=make_summary()
        )
        status, data, _ = self._create(
            {
                "plan_date": "2026-09-07",
                "raw_lesson_plan": "教案",
                "adopted_content": {"reflection": "反思"},
            }
        )
        self.assertEqual(status, 201)
        self.assertEqual(data["id"], "plan1")
        self.assertEqual(
            data["weekly_sync_state"]["missing_dates"],
            ["2026-09-08", "2026-09-09"],
        )
        kwargs = create.call_args.kwargs
        self.assertIsNone(kwargs["class_id"])
        self.assertEqual(kwargs["raw_lesson_plan"], "教案")
        self.assertEqual(kwargs["adopted_content"], {"reflection": "反思"})

    def test_duplicate_create_returns_200_opening_existing(self):
        self.login_snapshot(make_snapshot("teacher"))
        self.patch_service(
            "create_or_open",
            return_value=(
                make_plan(creator_id="tch1"),
                make_content(),
                False,
            ),
        )
        self.patch_service(
            "weekly_sync_summary", return_value=make_summary()
        )
        status, data, _ = self._create({"plan_date": "2026-09-07"})
        self.assertEqual(status, 200)
        self.assertEqual(data["creator_id"], "tch1")
        self.assertEqual(data["content"]["version"], 2)

    def test_teacher_body_with_class_id_is_422(self):
        self.login_snapshot(make_snapshot("teacher"))
        create = self.patch_service("create_or_open")
        status, _, body = self._create(
            {"plan_date": "2026-09-07", "class_id": "cls1"}
        )
        self.assertEqual(status, 422)
        self.assertEqual(error_code(body), "VALIDATION_ERROR")
        create.assert_not_called()

    def test_teacher_class_id_presence_matrix(self):
        """Teacher: omitted accepted; explicit null or value both 422."""
        self.login_snapshot(make_snapshot("teacher"))
        create = self.patch_service(
            "create_or_open",
            return_value=(make_plan(), make_content(), True),
        )
        self.patch_service(
            "weekly_sync_summary", return_value=make_summary()
        )
        # Omitted -> accepted, reaches the service with class_id None.
        status, _, _ = self._create({"plan_date": "2026-09-07"})
        self.assertEqual(status, 201)
        create.assert_called_once()
        self.assertIsNone(create.call_args.kwargs["class_id"])
        # Explicit null -> rejected before the service.
        create.reset_mock()
        status, _, body = self._create(
            {"plan_date": "2026-09-07", "class_id": None}
        )
        self.assertEqual(status, 422)
        self.assertEqual(error_code(body), "VALIDATION_ERROR")
        create.assert_not_called()
        # Non-null value -> rejected before the service.
        status, _, body = self._create(
            {"plan_date": "2026-09-07", "class_id": "cls1"}
        )
        self.assertEqual(status, 422)
        self.assertEqual(error_code(body), "VALIDATION_ERROR")
        create.assert_not_called()

    def test_admin_class_id_presence_matrix(self):
        """Admin: omitted/null/empty rejected; non-empty value accepted."""
        self.login_snapshot(make_snapshot("admin"))
        create = self.patch_service(
            "create_or_open",
            return_value=(make_plan(), make_content(), True),
        )
        self.patch_service(
            "weekly_sync_summary", return_value=make_summary()
        )
        for payload in (
            {"plan_date": "2026-09-07"},
            {"plan_date": "2026-09-07", "class_id": None},
            {"plan_date": "2026-09-07", "class_id": ""},
        ):
            with self.subTest(payload=payload):
                status, _, body = self._create(payload)
                self.assertEqual(status, 422)
                self.assertEqual(error_code(body), "VALIDATION_ERROR")
                create.assert_not_called()
        status, _, _ = self._create(
            {"plan_date": "2026-09-07", "class_id": "cls1"}
        )
        self.assertEqual(status, 201)
        create.assert_called_once()
        self.assertEqual(create.call_args.kwargs["class_id"], "cls1")

    def test_admin_body_without_class_id_is_422(self):
        self.login_snapshot(make_snapshot("admin"))
        create = self.patch_service("create_or_open")
        status, _, body = self._create({"plan_date": "2026-09-07"})
        self.assertEqual(status, 422)
        self.assertEqual(error_code(body), "VALIDATION_ERROR")
        create.assert_not_called()

    def test_admin_create_uses_body_class_id(self):
        self.login_snapshot(make_snapshot("admin"))
        create = self.patch_service(
            "create_or_open", return_value=(make_plan(), make_content(), True)
        )
        self.patch_service(
            "weekly_sync_summary", return_value=make_summary()
        )
        status, _, _ = self._create(
            {"plan_date": "2026-09-07", "class_id": "cls1"}
        )
        self.assertEqual(status, 201)
        self.assertEqual(create.call_args.kwargs["class_id"], "cls1")

    def test_body_term_id_is_422(self):
        self.login_snapshot(make_snapshot("teacher"))
        create = self.patch_service("create_or_open")
        status, _, body = self._create(
            {"plan_date": "2026-09-07", "term_id": "ter1"}
        )
        self.assertEqual(status, 422)
        self.assertEqual(error_code(body), "VALIDATION_ERROR")
        create.assert_not_called()

    def test_unknown_body_field_is_422(self):
        self.login_snapshot(make_snapshot("teacher"))
        create = self.patch_service("create_or_open")
        status, _, body = self._create(
            {"plan_date": "2026-09-07", "split_baseline": {}}
        )
        self.assertEqual(status, 422)
        self.assertEqual(error_code(body), "VALIDATION_ERROR")
        create.assert_not_called()

    def test_date_error_codes_map_to_422(self):
        cases = (
            (daily_plan_service.DailyPlanOutsideTerm(), "OUTSIDE_TERM"),
            (
                daily_plan_service.DailyPlanDateNotEligible(),
                "DATE_NOT_ELIGIBLE",
            ),
            (
                daily_plan_service.DailyPlanYearNotCovered(),
                "YEAR_NOT_COVERED",
            ),
            (ContentValidationError("结构错误"), "VALIDATION_ERROR"),
        )
        for exc, code in cases:
            with self.subTest(code=code):
                self.login_snapshot(make_snapshot("teacher"))
                self.patch_service("create_or_open", side_effect=exc)
                status, _, body = self._create({"plan_date": "2026-09-07"})
                self.assertEqual(status, 422)
                self.assertEqual(error_code(body), code)
                app.dependency_overrides.pop(get_auth_snapshot, None)

    def test_pending_teacher_reaches_service_and_maps_403(self):
        self.login_snapshot(make_snapshot("teacher"))
        self.patch_service(
            "create_or_open",
            side_effect=daily_plan_service.DailyPlanForbidden(),
        )
        status, _, body = self._create({"plan_date": "2026-09-07"})
        self.assertEqual(status, 403)
        self.assertEqual(error_code(body), "FORBIDDEN")

    def test_admin_unknown_class_maps_404(self):
        self.login_snapshot(make_snapshot("admin"))
        self.patch_service(
            "create_or_open",
            side_effect=auth_service.ClassNotFound(),
        )
        status, _, body = self._create(
            {"plan_date": "2026-09-07", "class_id": "missing"}
        )
        self.assertEqual(status, 404)
        self.assertEqual(error_code(body), "CLASS_NOT_FOUND")

    def test_version_conflict_on_save_maps_409(self):
        self.login_snapshot(make_snapshot("teacher"))
        self.patch_service(
            "create_or_open",
            side_effect=daily_plan_service.DailyPlanVersionConflict(),
        )
        status, _, body = self._create({"plan_date": "2026-09-07"})
        self.assertEqual(status, 409)
        self.assertEqual(error_code(body), "VERSION_CONFLICT")


class PatchTests(RouteTestBase):
    def _patch(self, payload: dict) -> tuple[int, bytes]:
        status, _, body = api_request(
            "PATCH", "/api/daily-plans/plan1", payload=payload
        )
        return status, body

    def test_omitted_optional_fields_sent_as_unset(self):
        self.login_snapshot(make_snapshot("teacher"))
        save = self.patch_service(
            "save",
            return_value=(
                make_plan(current_content_id="cnt3", current_content_version=3),
                make_content(id="cnt3", version=3),
            ),
        )
        self.patch_service(
            "weekly_sync_summary", return_value=make_summary()
        )
        status, body = self._patch({"expected_content_version": 2})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["current_content_version"], 3)
        kwargs = save.call_args.kwargs
        self.assertEqual(kwargs["expected_content_version"], 2)
        self.assertIs(kwargs["raw_lesson_plan"], UNSET)
        self.assertIs(kwargs["adopted_content"], UNSET)

    def test_explicit_null_raw_and_content_pass_through(self):
        self.login_snapshot(make_snapshot("teacher"))
        save = self.patch_service(
            "save", return_value=(make_plan(), make_content())
        )
        self.patch_service(
            "weekly_sync_summary", return_value=make_summary()
        )
        status, _ = self._patch(
            {
                "expected_content_version": 2,
                "raw_lesson_plan": None,
                "adopted_content": {"reflection": "新"},
            }
        )
        self.assertEqual(status, 200)
        kwargs = save.call_args.kwargs
        self.assertIsNone(kwargs["raw_lesson_plan"])
        self.assertEqual(kwargs["adopted_content"], {"reflection": "新"})

    def test_non_creator_teacher_maps_403(self):
        self.login_snapshot(make_snapshot("teacher"))
        self.patch_service(
            "save", side_effect=daily_plan_service.DailyPlanForbidden()
        )
        status, body = self._patch({"expected_content_version": 2})
        self.assertEqual(status, 403)
        self.assertEqual(error_code(body), "FORBIDDEN")

    def test_version_conflict_maps_409(self):
        self.login_snapshot(make_snapshot("teacher"))
        self.patch_service(
            "save",
            side_effect=daily_plan_service.DailyPlanVersionConflict(),
        )
        status, body = self._patch({"expected_content_version": 1})
        self.assertEqual(status, 409)
        self.assertEqual(error_code(body), "VERSION_CONFLICT")

    def test_split_baseline_rejected_by_schema(self):
        self.login_snapshot(make_snapshot("teacher"))
        save = self.patch_service("save")
        status, body = self._patch(
            {"expected_content_version": 2, "split_baseline": {}}
        )
        self.assertEqual(status, 422)
        self.assertEqual(error_code(body), "VALIDATION_ERROR")
        save.assert_not_called()

    def test_expected_version_bounds_enforced(self):
        self.login_snapshot(make_snapshot("teacher"))
        save = self.patch_service("save")
        for payload in (
            {"expected_content_version": 0},
            {"raw_lesson_plan": "x"},
            {"expected_content_version": 2, "class_id": "cls1"},
        ):
            with self.subTest(payload=payload):
                status, body = self._patch(payload)
                self.assertEqual(status, 422)
                self.assertEqual(error_code(body), "VALIDATION_ERROR")
        save.assert_not_called()

    def test_expected_version_strict_integer_boundary(self):
        """bool / float / numeric string must 422; positive int accepted."""
        self.login_snapshot(make_snapshot("teacher"))
        save = self.patch_service(
            "save", return_value=(make_plan(), make_content())
        )
        self.patch_service(
            "weekly_sync_summary", return_value=make_summary()
        )
        for bad in (True, False, 1.0, "1"):
            with self.subTest(bad=bad):
                status, body = self._patch(
                    {"expected_content_version": bad}
                )
                self.assertEqual(status, 422)
                self.assertEqual(error_code(body), "VALIDATION_ERROR")
        save.assert_not_called()
        status, body = self._patch({"expected_content_version": 1})
        self.assertEqual(status, 200)
        save.assert_called_once()
        self.assertEqual(save.call_args.kwargs["expected_content_version"], 1)

    def test_not_found_maps_404(self):
        self.login_snapshot(make_snapshot("admin"))
        self.patch_service(
            "save", side_effect=daily_plan_service.DailyPlanNotFound()
        )
        status, body = self._patch({"expected_content_version": 1})
        self.assertEqual(status, 404)
        self.assertEqual(error_code(body), "DAILY_PLAN_NOT_FOUND")

    def test_date_ineligibility_during_save_maps_422(self):
        self.login_snapshot(make_snapshot("teacher"))
        self.patch_service(
            "save",
            side_effect=daily_plan_service.DailyPlanDateNotEligible(),
        )
        status, body = self._patch({"expected_content_version": 2})
        self.assertEqual(status, 422)
        self.assertEqual(error_code(body), "DATE_NOT_ELIGIBLE")


class WeeklySyncStateTests(RouteTestBase):
    PATH = "/api/weekly-plan-sync-states"

    def test_teacher_own_class_returns_full_projection(self):
        self.login_teacher(class_id="cls1")
        get_state = self.patch_service(
            "get_sync_state", return_value=make_sync_row()
        )
        status, _, body = api_request("GET", f"{self.PATH}/cls1/ter1/2")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["status"], "pending_projection")
        self.assertEqual(data["deterministic_themes"][0]["date"], "2026-09-07")
        self.assertEqual(
            data["game_source_manifest"][0]["game_id"], "gam1"
        )
        self.assertEqual(
            data["current_week_source_manifest"][0][
                "current_content_version"
            ],
            2,
        )
        self.assertEqual(data["last_trigger_event"], "update")
        self.assertEqual(data["last_trigger_content_version"], 2)
        self.assertEqual(data["last_trigger_daily_plan_id"], "plan1")
        get_state.assert_called_once()

    def test_teacher_other_class_is_403(self):
        self.login_teacher(class_id="cls1")
        get_state = self.patch_service("get_sync_state")
        status, _, body = api_request("GET", f"{self.PATH}/cls2/ter1/2")
        self.assertEqual(status, 403)
        self.assertEqual(error_code(body), "FORBIDDEN")
        get_state.assert_not_called()

    def test_pending_teacher_is_403(self):
        self.login_teacher(class_id=None)
        get_state = self.patch_service("get_sync_state")
        status, _, body = api_request("GET", f"{self.PATH}/cls1/ter1/2")
        self.assertEqual(status, 403)
        self.assertEqual(error_code(body), "FORBIDDEN")
        get_state.assert_not_called()

    def test_missing_projection_is_404(self):
        self.login_admin()
        self.patch_service("get_sync_state", return_value=None)
        status, _, body = api_request("GET", f"{self.PATH}/cls1/ter1/2")
        self.assertEqual(status, 404)
        self.assertEqual(error_code(body), "WEEKLY_PLAN_SYNC_NOT_FOUND")

    def test_admin_reads_with_explicit_path_class(self):
        self.login_admin()
        get_state = self.patch_service(
            "get_sync_state", return_value=make_sync_row()
        )
        status, _, body = api_request("GET", f"{self.PATH}/cls9/ter1/3")
        self.assertEqual(status, 200)
        get_state.assert_called_once_with(self.db, "cls9", "ter1", 3)

    def test_week_number_must_be_positive(self):
        self.login_admin()
        status, _, body = api_request("GET", f"{self.PATH}/cls1/ter1/0")
        self.assertEqual(status, 422)
        self.assertEqual(error_code(body), "VALIDATION_ERROR")


class RouteRegistrationTests(unittest.TestCase):
    def test_expected_routes_registered(self):
        # This FastAPI version stores include_router results as wrapper
        # objects on app.routes, so assert against the generated OpenAPI
        # operation table instead of raw route attributes.
        paths = app.openapi()["paths"]
        for path in (
            "/api/daily-plans",
            "/api/daily-plans/by-date",
            "/api/daily-plans/{plan_id}",
            "/api/weekly-plan-sync-states/{class_id}/{term_id}/{week_number}",
        ):
            with self.subTest(path=path):
                self.assertIn(path, paths)
        self.assertEqual(
            set(paths["/api/daily-plans"]), {"get", "post"}
        )
        self.assertEqual(
            set(paths["/api/daily-plans/by-date"]), {"get"}
        )
        self.assertEqual(
            set(paths["/api/daily-plans/{plan_id}"]), {"get", "patch"}
        )

    def test_no_delete_or_recover_routes(self):
        paths = app.openapi()["paths"]
        for path, operations in paths.items():
            with self.subTest(path=path):
                if "daily-plans" in path:
                    self.assertNotIn("delete", operations)
                self.assertFalse(path.endswith("/recover"))


if __name__ == "__main__":
    unittest.main()
