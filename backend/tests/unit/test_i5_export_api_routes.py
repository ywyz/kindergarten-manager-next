"""No-DB ASGI tests for the I5 export routes (slice 3).

Drives the real FastAPI app (routing, middleware, validation, dependency
overrides, response construction) with mocked slice-1 read service / slice-2
generation and mocked audit writes — no database, no MySQL, no SQLite. Mock
results never claim to verify database consistency; that layer belongs to the
integration suite.

Covers spec §8 error semantics end-to-end: the permission matrix with
presence-based class_id semantics, the fact-preserving 409 ack loop,
EXPORT_NO_MATCH / EXPORT_RANGE_TOO_LARGE ordering, weekly dual modes,
generation/audit failure mapping, and the §7 response headers, filenames and
warning carriers.
"""

import asyncio
import json
import os
from datetime import date, datetime

os.environ["APP_DISABLE_DOTENV"] = "1"
os.environ["ALLOWED_ORIGINS"] = "http://localhost:5173,http://127.0.0.1:5173"

import unittest
from unittest import mock

from app.database import get_db
from app.deps import get_auth_snapshot
from app.main import app
from app.models import TeacherAssignment
from app.routers import exports as export_router
from app.services import export_read_service
from app.services.auth_service import AuthSnapshot
from app.services.word_export_docx import WordExportError, WordTemplateError

_ORIGIN = "http://localhost:5173"
_NOW = datetime(2026, 9, 7, 8, 0, 0)
_DOCX_BYTES = b"PK-SENTINEL-DOCX"


# -- ASGI driver (same shape as the I3/I4 route tests) ----------------------


async def _asgi_request(
    method: str,
    path: str,
    *,
    headers: dict | None = None,
    body: bytes = b"",
) -> tuple[int, dict[str, list[str]], bytes]:
    request_headers = []
    for k, v in (headers or {}).items():
        request_headers.append((k.lower().encode("latin-1"), v.encode("latin-1")))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": request_headers,
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8000),
        "scheme": "http",
    }

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

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
        grouped.setdefault(name.decode("latin-1").lower(), []).append(
            value.decode("latin-1")
        )
    return response_start["status"], grouped, bytes(response_body)


def api_request(
    method: str,
    path: str,
    *,
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
    return asyncio.run(_asgi_request(method, path, headers=headers, body=body))


def json_body(body: bytes) -> dict:
    return json.loads(body)


def error_code(body: bytes) -> str:
    return json_body(body)["error"]["code"]


# -- fabricated slice-1 result objects --------------------------------------


def make_record(**kw):
    defaults = dict(
        plan_id="plan1",
        class_id="cls1",
        term_id="ter1",
        plan_date=date(2026, 9, 7),
        week_number=2,
        weekday=1,
        creator_id="tch1",
        creator_display_name="甲老师",
        school_name="阳光园",
        class_name="小班甲",
        grade="small",
        content_id="cnt1",
        content_version=3,
        adopted_content={},
        split_baseline=None,
        warnings=(),
    )
    defaults.update(kw)
    return export_read_service.DailyPlanExportRecord(**defaults)


def make_weekly_item(**kw):
    defaults = dict(
        plan_id="wp1",
        class_id="cls1",
        term_id="ter1",
        week_number=2,
        week_start=date(2026, 9, 7),
        first_teaching_day=date(2026, 9, 7),
        confirmed_version=1,
        confirmed_content_id="cf1",
        content={"theme": "秋"},
        facts={},
        warnings=(),
        term_start=date(2026, 9, 1),
        term_end=date(2026, 9, 30),
        week_days={date(2026, 9, 7): "teaching", date(2026, 9, 8): "teaching"},
        school_name="阳光园",
        class_name="小班甲",
        grade="small",
        header_teacher_names=["甲老师"],
        caregiver_name="李保育",
    )
    defaults.update(kw)
    return export_read_service.WeeklyExportItem(**defaults)


def make_bundle(**kw):
    defaults = dict(
        items=(),
        missing=(),
        warnings=(),
        ack_required=False,
        ack_reason=None,
        expected_context={},
    )
    defaults.update(kw)
    return export_read_service.DailyExportBundle(**defaults)


class ExportRouteTestBase(unittest.TestCase):
    def setUp(self):
        self.db = mock.MagicMock()
        self.db.get.return_value = TeacherAssignment(
            teacher_id="tch1", class_id="cls1", assigned_by="adm1", assigned_at=_NOW
        )
        app.dependency_overrides[get_db] = lambda: self.db
        self.record_operation = mock.patch.object(
            export_router.auth_service,
            "record_operation",
            wraps=mock.MagicMock(return_value=mock.MagicMock()),
        ).start()
        self.addCleanup(mock.patch.stopall)

    def tearDown(self):
        app.dependency_overrides.clear()

    def login(self, role="teacher", account_id="tch1", assignment_cls="cls1"):
        snapshot = AuthSnapshot(
            account_id=account_id,
            role=role,
            auth_version=1,
            session_id=f"ses_{role}",
            is_active=True,
            password_hash="x",
        )
        app.dependency_overrides[get_auth_snapshot] = lambda: snapshot
        if role == "teacher" and assignment_cls is not None:
            self.db.get.return_value = TeacherAssignment(
                teacher_id=account_id,
                class_id=assignment_cls,
                assigned_by="adm1",
                assigned_at=_NOW,
            )
        else:
            self.db.get.return_value = None
        return snapshot

    # -- patch helpers (each returns the created mock) -------------------

    def patch_prepare(self, **kw):
        patcher = mock.patch.object(
            export_router.export_read, "prepare_daily_export", **kw
        )
        mocked = patcher.start()
        self.addCleanup(patcher.stop)
        return mocked

    def patch_select_range(self, **kw):
        patcher = mock.patch.object(
            export_router.export_read, "select_weekly_plans_range", **kw
        )
        mocked = patcher.start()
        self.addCleanup(patcher.stop)
        return mocked

    def patch_load_single(self, **kw):
        patcher = mock.patch.object(
            export_router.export_read, "load_weekly_single", **kw
        )
        mocked = patcher.start()
        self.addCleanup(patcher.stop)
        return mocked

    def patch_generate(self, data=None, side_effect=None):
        patcher = mock.patch.object(
            export_router.word_export_docx,
            "generate_export_docx",
            return_value=(data if data is not None else _DOCX_BYTES) if not side_effect else None,
            side_effect=side_effect,
        )
        mocked = patcher.start()
        self.addCleanup(patcher.stop)
        return mocked


class AuthenticationTests(ExportRouteTestBase):
    def test_no_session_is_401(self):
        for path, payload in (
            ("/api/exports/daily-plans", {"from": "2026-09-01", "to": "2026-09-02"}),
            ("/api/exports/weekly-plans", {"from": "2026-09-01", "to": "2026-09-02"}),
        ):
            with self.subTest(path=path):
                status, _, body = api_request("POST", path, payload=payload)
                self.assertEqual(status, 401)
                self.assertEqual(error_code(body), "AUTH_REQUIRED")

    def test_unknown_role_is_403(self):
        # Only admin/teacher may export; every other role is forbidden.
        self.login(role="missing_role")
        prepared = self.patch_prepare()
        status, _, body = api_request(
            "POST",
            "/api/exports/daily-plans",
            payload={"from": "2026-09-01", "to": "2026-09-01"},
        )
        self.assertEqual(status, 403)
        self.assertEqual(error_code(body), "FORBIDDEN")
        prepared.assert_not_called()

    def test_content_type_and_origin_are_enforced_by_middleware(self):
        status, headers, body = asyncio.run(
            _asgi_request(
                "POST",
                "/api/exports/daily-plans",
                headers={"Content-Type": "text/plain"},
                body=b"{}",
            )
        )
        self.assertEqual(status, 422)
        status, _, body = asyncio.run(
            _asgi_request(
                "POST",
                "/api/exports/daily-plans",
                headers={"Content-Type": "application/json"},
                body=b"{}",
            )
        )
        self.assertEqual(status, 403)  # missing exact Origin


class TeacherClassScopeTests(ExportRouteTestBase):
    def test_teacher_omitting_class_id_uses_assignment(self):
        self.login(assignment_cls="clsX")
        prepared = self.patch_prepare(
            return_value=make_bundle(items=(make_record(),))
        )
        self.patch_generate()
        status, _, _ = api_request(
            "POST",
            "/api/exports/daily-plans",
            payload={"from": "2026-09-01", "to": "2026-09-01"},
        )
        self.assertEqual(status, 200)
        kwargs = prepared.call_args.kwargs
        self.assertEqual(kwargs["class_id"], "clsX")

    def test_teacher_explicit_null_class_id_is_422(self):
        self.login(assignment_cls="cls1")
        prepared = self.patch_prepare()
        status, _, body = api_request(
            "POST",
            "/api/exports/daily-plans",
            payload={"from": "2026-09-01", "to": "2026-09-01", "class_id": None},
        )
        self.assertEqual(status, 422)
        self.assertEqual(error_code(body), "VALIDATION_ERROR")
        prepared.assert_not_called()

    def test_teacher_any_class_id_value_is_422(self):
        self.login(assignment_cls="cls1")
        prepared = self.patch_prepare()
        status, _, _ = api_request(
            "POST",
            "/api/exports/daily-plans",
            payload={"from": "2026-09-01", "to": "2026-09-01", "class_id": "cls2"},
        )
        self.assertEqual(status, 422)
        prepared.assert_not_called()

    def test_pending_teacher_is_403(self):
        self.login(assignment_cls=None)
        prepared = self.patch_prepare()
        status, _, body = api_request(
            "POST",
            "/api/exports/daily-plans",
            payload={"from": "2026-09-01", "to": "2026-09-01"},
        )
        self.assertEqual(status, 403)
        self.assertEqual(error_code(body), "FORBIDDEN")
        prepared.assert_not_called()

    def test_teacher_never_exists_for_team_other_roles(self):
        pass  # covered by AuthenticationTests.test_unknown_role_is_403


class AdminClassScopeTests(ExportRouteTestBase):
    def test_admin_must_send_class_id(self):
        self.login(role="admin")
        prepared = self.patch_prepare()
        status, _, body = api_request(
            "POST",
            "/api/exports/daily-plans",
            payload={"from": "2026-09-01", "to": "2026-09-01"},
        )
        self.assertEqual(status, 422)
        self.assertEqual(error_code(body), "VALIDATION_ERROR")
        prepared.assert_not_called()

    def test_admin_null_or_empty_class_id_is_422(self):
        self.login(role="admin")
        prepared = self.patch_prepare()
        for bad in (None, ""):
            with self.subTest(bad=bad):
                status, _, body = api_request(
                    "POST",
                    "/api/exports/daily-plans",
                    payload={
                        "from": "2026-09-01",
                        "to": "2026-09-01",
                        "class_id": bad,
                    },
                )
                self.assertEqual(status, 422)
                self.assertEqual(error_code(body), "VALIDATION_ERROR")
        prepared.assert_not_called()

    def test_admin_explicit_class_is_used(self):
        self.login(role="admin")
        prepared = self.patch_prepare(
            return_value=make_bundle(items=(make_record(),))
        )
        self.patch_generate()
        status, _, _ = api_request(
            "POST",
            "/api/exports/daily-plans",
            payload={
                "from": "2026-09-01",
                "to": "2026-09-01",
                "class_id": "clsADM",
            },
        )
        self.assertEqual(status, 200)
        kwargs = prepared.call_args.kwargs
        self.assertEqual(kwargs["class_id"], "clsADM")

    def test_admin_assignment_row_is_not_consulted(self):
        # Admin context comes from the explicit class_id only.
        self.login(role="admin")
        self.patch_prepare(return_value=make_bundle(items=(make_record(),)))
        self.patch_generate()
        api_request(
            "POST",
            "/api/exports/daily-plans",
            payload={"from": "2026-09-01", "to": "2026-09-01", "class_id": "clsADM"},
        )
        self.db.get.assert_not_called()


class DailyExportFlowTests(ExportRouteTestBase):
    def payload(self, **overrides) -> dict:
        payload = {"from": "2026-09-01", "to": "2026-09-02"}
        payload.update(overrides)
        return payload

    def test_first_409_carries_facts_context_and_reason(self):
        self.login()
        bundle = make_bundle(
            items=(make_record(),),
            missing=(
                {
                    "daily_plan_id": "plan1",
                    "plan_date": "2026-09-07",
                    "facts": [{"kind": "empty_field", "field": "group_activity.theme"}],
                },
            ),
            ack_required=True,
            ack_reason="missing",
            expected_context={"probe": 1},
        )
        prepared = self.patch_prepare(return_value=bundle)
        generate = self.patch_generate()
        status, headers, body = api_request(
            "POST", "/api/exports/daily-plans", payload=self.payload()
        )
        self.assertEqual(status, 409)
        error = json_body(body)["error"]
        self.assertEqual(error["code"], "EXPORT_ACK_REQUIRED")
        self.assertEqual(error["reason"], "missing")
        self.assertEqual(error["expected_context"], {"probe": 1})
        self.assertEqual(len(error["facts"]), 1)
        self.assertEqual(
            error["facts"][0]["facts"],
            [{"kind": "empty_field", "field": "group_activity.theme"}],
        )
        self.assertIn("no-store", headers.get("cache-control", []))
        generate.assert_not_called()
        self.record_operation.assert_not_called()
        # The strict schema echo is relayed untouched (call kwarg).
        self.assertIsNone(prepared.call_args.kwargs["expected_context"])

    def test_matching_context_continues(self):
        self.login()
        context = {"from": "2026-09-01", "missing_fingerprint": "x"}
        prepared = self.patch_prepare(
            return_value=make_bundle(items=(make_record(),), expected_context=context)
        )
        self.patch_generate()
        status, _, _ = api_request(
            "POST",
            "/api/exports/daily-plans",
            payload=self.payload(ack_missing=True, expected_context=context),
        )
        self.assertEqual(status, 200)
        kwargs = prepared.call_args.kwargs
        self.assertTrue(kwargs["ack_missing"])
        self.assertEqual(kwargs["expected_context"], context)

    def test_context_changed_is_409_with_new_facts_even_when_zero(self):
        self.login()
        # Server says: object changed; even the latest missing set is empty,
        # so a fresh confirmation is required before exporting.
        self.patch_prepare(
            return_value=make_bundle(
                items=(make_record(),),
                missing=(),
                ack_required=True,
                ack_reason="context_changed",
                expected_context={"new": 2},
            )
        )
        self.patch_generate()
        status, _, body = api_request(
            "POST",
            "/api/exports/daily-plans",
            payload=self.payload(
                ack_missing=True, expected_context={"stale": 1}
            ),
        )
        self.assertEqual(status, 409)
        error = json_body(body)["error"]
        self.assertEqual(error["reason"], "context_changed")
        self.assertEqual(error["facts"], [])
        self.assertEqual(error["expected_context"], {"new": 2})

    def test_second_40k_then_success_uses_fresh_context(self):
        self.login()
        old = {"stale": 1}
        new = {"fresh": 2}
        prepared = self.patch_prepare(
            side_effect=[
                make_bundle(
                    items=(make_record(),),
                    missing=({"plan": 1},),
                    ack_required=True,
                    ack_reason="context_changed",
                    expected_context=new,
                ),
                make_bundle(items=(make_record(),), expected_context=new),
            ]
        )
        generate = self.patch_generate()
        status, _, body = api_request(
            "POST",
            "/api/exports/daily-plans",
            payload=self.payload(ack_missing=True, expected_context=old),
        )
        self.assertEqual(status, 409)
        self.assertEqual(json_body(body)["error"]["expected_context"], new)
        status, _, _ = api_request(
            "POST",
            "/api/exports/daily-plans",
            payload=self.payload(ack_missing=True, expected_context=new),
        )
        self.assertEqual(status, 200)
        # Two independent calls; the second relays the fresh context.
        self.assertEqual(prepared.call_count, 2)
        self.assertEqual(prepared.call_args.kwargs["expected_context"], new)
        generate.assert_called_once()

    def test_facts_are_never_taken_from_client(self):
        """Client facts shape is ignored; server recomputation decides."""
        self.login()
        # The payload includes a forged facts block; unknown to the schema, so
        # it is rejected (422) — facts can never ride along.
        status, _, body = api_request(
            "POST",
            "/api/exports/daily-plans",
            payload=self.payload(facts=[{"kind": "empty_field"}]),
        )
        self.assertEqual(status, 422)
        self.assertEqual(error_code(body), "VALIDATION_ERROR")

    def test_first_clean_request_exports_directly(self):
        self.login()
        prepared = self.patch_prepare(
            return_value=make_bundle(items=(make_record(),))
        )
        generate = self.patch_generate()
        status, _, _ = api_request(
            "POST", "/api/exports/daily-plans", payload=self.payload()
        )
        self.assertEqual(status, 200)
        self.assertFalse(prepared.call_args.kwargs["ack_missing"])
        self.assertIsNone(prepared.call_args.kwargs["expected_context"])
        generate.assert_called_once()

    def test_no_match_404_before_everything(self):
        self.login()
        self.patch_prepare(return_value=make_bundle(items=()))
        generate = self.patch_generate()
        status, _, body = api_request(
            "POST", "/api/exports/daily-plans", payload=self.payload()
        )
        self.assertEqual(status, 404)
        self.assertEqual(error_code(body), "EXPORT_NO_MATCH")
        generate.assert_not_called()
        self.record_operation.assert_not_called()

    def test_limit_422_details(self):
        self.login()
        item = make_record()
        self.patch_prepare(return_value=make_bundle(items=(item,) * 32))
        generate = self.patch_generate()
        status, _, body = api_request(
            "POST", "/api/exports/daily-plans", payload=self.payload()
        )
        self.assertEqual(status, 422)
        error = json_body(body)["error"]
        self.assertEqual(error["code"], "EXPORT_RANGE_TOO_LARGE")
        self.assertEqual(error["limit"], 31)
        self.assertEqual(error["selected_count"], 32)
        self.assertEqual(error["plan_kind"], "daily_plans")
        generate.assert_not_called()
        self.record_operation.assert_not_called()

    def test_limit_boundary_31_passes(self):
        self.login()
        item = make_record()
        self.patch_prepare(return_value=make_bundle(items=(item,) * 31))
        generate = self.patch_generate()
        status, _, _ = api_request(
            "POST", "/api/exports/daily-plans", payload=self.payload()
        )
        self.assertEqual(status, 200)
        generate.assert_called_once()

    def test_read_validation_error_maps_to_422(self):
        self.login()
        self.patch_prepare(
            side_effect=export_read_service.ExportReadValidationError("from 不能晚于 to")
        )
        status, _, body = api_request(
            "POST", "/api/exports/daily-plans", payload=self.payload()
        )
        self.assertEqual(status, 422)
        self.assertEqual(error_code(body), "VALIDATION_ERROR")

    def test_pointer_data_error_maps_to_503_service_unavailable(self):
        self.login()
        self.patch_prepare(
            side_effect=export_read_service.ExportReadDataError("指针不一致")
        )
        status, _, body = api_request(
            "POST", "/api/exports/daily-plans", payload=self.payload()
        )
        self.assertEqual(status, 503)
        self.assertEqual(error_code(body), "SERVICE_UNAVAILABLE")


class WeeklyExportFlowTests(ExportRouteTestBase):
    def range_payload(self, **overrides) -> dict:
        payload = {"from": "2026-09-01", "to": "2026-09-14"}
        payload.update(overrides)
        return payload

    def single_payload(self, **overrides) -> dict:
        payload = {"plan_id": "wp1"}
        payload.update(overrides)
        return payload

    def test_single_mode_uses_current_pointer(self):
        self.login()
        single = self.patch_load_single(return_value=make_weekly_item())
        generate = self.patch_generate()
        status, _, _ = api_request(
            "POST", "/api/exports/weekly-plans", payload=self.single_payload()
        )
        self.assertEqual(status, 200)
        kwargs = single.call_args.kwargs
        self.assertEqual(kwargs["plan_id"], "wp1")
        self.assertIsNone(kwargs["confirmed_version"])
        self.assertEqual(kwargs["class_id"], "cls1")
        self.assertEqual(kwargs["role"], "teacher")
        generate.assert_called_once()

    def test_single_mode_explicit_version(self):
        self.login()
        single = self.patch_load_single(return_value=make_weekly_item())
        api_request(
            "POST",
            "/api/exports/weekly-plans",
            payload=self.single_payload(confirmed_version=2),
        )
        self.assertEqual(single.call_args.kwargs["confirmed_version"], 2)

    def test_teacher_single_mode_cross_class_is_403(self):
        self.login(assignment_cls="clsZ")
        single = self.patch_load_single(
            side_effect=export_read_service.ExportReadForbidden()
        )
        generate = self.patch_generate()
        status, _, body = api_request(
            "POST", "/api/exports/weekly-plans", payload=self.single_payload()
        )
        self.assertEqual(status, 403)
        self.assertEqual(error_code(body), "FORBIDDEN")
        generate.assert_not_called()
        self.record_operation.assert_not_called()

    def test_single_plan_not_found_is_404(self):
        self.login()
        self.patch_load_single(
            side_effect=export_read_service.ExportReadNotFound("不存在")
        )
        status, _, body = api_request(
            "POST", "/api/exports/weekly-plans", payload=self.single_payload()
        )
        self.assertEqual(status, 404)
        self.assertEqual(error_code(body), "WEEKLY_PLAN_NOT_FOUND")

    def test_admin_mismatch_class_context_maps_to_404(self):
        self.login(role="admin")
        self.patch_load_single(
            side_effect=export_read_service.ExportReadNotFound("不符")
        )
        status, _, body = api_request(
            "POST",
            "/api/exports/weekly-plans",
            payload=self.single_payload(class_id="clsWRONG"),
        )
        self.assertEqual(status, 404)
        self.assertEqual(error_code(body), "WEEKLY_PLAN_NOT_FOUND")

    def test_unconfirmed_single_plan_is_404_confirmation(self):
        self.login()
        self.patch_load_single(
            side_effect=export_read_service.ExportConfirmationNotFound("未确认")
        )
        status, _, body = api_request(
            "POST", "/api/exports/weekly-plans", payload=self.single_payload()
        )
        self.assertEqual(status, 404)
        self.assertEqual(error_code(body), "CONFIRMATION_NOT_FOUND")

    def test_range_mode_selects_and_pins_service_side(self):
        self.login()
        items = (
            make_weekly_item(plan_id="w1", class_name="小班甲"),
            make_weekly_item(plan_id="w2", class_name="小班甲"),
        )
        range_mock = self.patch_select_range(return_value=list(items))
        generate = self.patch_generate()
        status, _, _ = api_request(
            "POST", "/api/exports/weekly-plans", payload=self.range_payload()
        )
        self.assertEqual(status, 200)
        kwargs = range_mock.call_args.kwargs
        self.assertEqual(kwargs["class_id"], "cls1")
        generate.assert_called_once()

    def test_range_empty_is_404_no_match(self):
        self.login()
        self.patch_select_range(return_value=[])
        generate = self.patch_generate()
        status, _, body = api_request(
            "POST", "/api/exports/weekly-plans", payload=self.range_payload()
        )
        self.assertEqual(status, 404)
        self.assertEqual(error_code(body), "EXPORT_NO_MATCH")
        generate.assert_not_called()
        self.record_operation.assert_not_called()

    def test_range_excludes_unconfirmed_plans_by_service_answer(self):
        """The service already excludes unconfirmed candidates; the empty
        result after exclusion surfaces as 404 EXPORT_NO_MATCH."""
        self.login()
        self.patch_select_range(return_value=[])
        status, _, body = api_request(
            "POST", "/api/exports/weekly-plans", payload=self.range_payload()
        )
        self.assertEqual(status, 404)
        self.assertEqual(error_code(body), "EXPORT_NO_MATCH")

    def test_weekly_limit_9_is_422_with_count(self):
        self.login()
        items = [
            make_weekly_item(plan_id=f"w{i}", class_name=f"班{i}")
            for i in range(9)
        ]
        self.patch_select_range(return_value=items)
        generate = self.patch_generate()
        status, _, body = api_request(
            "POST", "/api/exports/weekly-plans", payload=self.range_payload()
        )
        self.assertEqual(status, 422)
        error = json_body(body)["error"]
        self.assertEqual(error["limit"], 8)
        self.assertEqual(error["selected_count"], 9)
        self.assertEqual(error["plan_kind"], "weekly_plans")
        generate.assert_not_called()
        self.record_operation.assert_not_called()

    def test_weekly_boundary_8_passes(self):
        self.login()
        items = [
            make_weekly_item(plan_id=f"w{i}", class_name=f"班{i}")
            for i in range(8)
        ]
        self.patch_select_range(return_value=items)
        generate = self.patch_generate()
        status, _, _ = api_request(
            "POST", "/api/exports/weekly-plans", payload=self.range_payload()
        )
        self.assertEqual(status, 200)
        generate.assert_called_once()

    def test_no_limit_check_when_single_mode(self):
        self.login()
        # Single mode bypasses the plan-count limit by design (spec §11.1).
        self.patch_load_single(return_value=make_weekly_item())
        self.patch_generate()
        status, _, _ = api_request(
            "POST", "/api/exports/weekly-plans", payload=self.single_payload()
        )
        self.assertEqual(status, 200)

    def test_schema_mode_conflicts_are_422(self):
        self.login()
        generate = self.patch_generate()
        for payload in (
            self.range_payload(plan_id="wp1"),  # both modes
            {"class_id": "cls1"},  # no mode
            {"from": "2026-09-01"},
            self.single_payload(**{"from": "2026-09-01"}),
            self.range_payload(confirmed_version=1),
        ):
            with self.subTest(payload=payload):
                status, _, body = api_request(
                    "POST", "/api/exports/weekly-plans", payload=payload
                )
                self.assertEqual(status, 422)
                self.assertEqual(error_code(body), "VALIDATION_ERROR")
        generate.assert_not_called()


class GenerationAndHeaderTests(ExportRouteTestBase):
    def test_success_body_equals_generator_result(self):
        self.login()
        marker = b"PK\x03\x04unique-generator-bytes"
        generate = self.patch_generate(data=marker)
        self.patch_prepare(return_value=make_bundle(items=(make_record(),)))
        status, _, body = api_request(
            "POST",
            "/api/exports/daily-plans",
            payload={"from": "2026-09-01", "to": "2026-09-02"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body, marker)
        self.assertEqual(generate.call_args.args[0], "daily_plan")

    def test_success_headers(self):
        self.login()
        self.patch_prepare(return_value=make_bundle(items=(make_record(),)))
        self.patch_generate()
        status, headers, _ = api_request(
            "POST",
            "/api/exports/daily-plans",
            payload={"from": "2026-09-07", "to": "2026-09-08"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            headers["content-type"],
            ["application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
        )
        self.assertIn("no-store", headers.get("cache-control", []))
        self.assertEqual(headers.get("x-content-type-options"), ["nosniff"])
        disposition = headers["content-disposition"][0]
        self.assertTrue(disposition.startswith("attachment"))
        self.assertIn("filename*=", disposition)
        self.assertIn("daily-plans_2026-09-07_2026-09-08", disposition)

    def test_no_split_baseline_warning_header(self):
        self.login()
        warnings = ({"code": "no_split_baseline"},)
        self.patch_prepare(
            return_value=make_bundle(
                items=(make_record(),), warnings=warnings
            )
        )
        self.patch_generate()
        _, headers, _ = api_request(
            "POST",
            "/api/exports/daily-plans",
            payload={"from": "2026-09-07", "to": "2026-09-08"},
        )
        self.assertEqual(headers["x-export-warnings"], ['[{"code":"no_split_baseline"}]'])

    def test_warning_header_deduplicates_across_plans(self):
        self.login()
        many = ({"code": "no_split_baseline"},) * 40
        self.patch_prepare(
            return_value=make_bundle(
                items=(make_record(), make_record(plan_id="p2")), warnings=many
            )
        )
        self.patch_generate()
        _, headers, _ = api_request(
            "POST",
            "/api/exports/daily-plans",
            payload={"from": "2026-09-07", "to": "2026-09-08"},
        )
        self.assertEqual(headers["x-export-warnings"], ['[{"code":"no_split_baseline"}]'])

    def test_confirmed_not_latest_header_with_reasons(self):
        self.login()
        items = [
            make_weekly_item(
                warnings=(
                    {"code": "confirmed_not_latest", "reason": "draft_ahead"},
                    {"code": "confirmed_not_latest", "reason": "superseded"},
                )
            ),
            make_weekly_item(
                plan_id="w2",
                warnings=(
                    {"code": "confirmed_not_latest", "reason": "draft_ahead"},
                    {"code": "confirmed_not_latest", "reason": "stale_sources"},
                ),
            ),
        ]
        self.patch_select_range(return_value=items)
        self.patch_generate()
        _, headers, _ = api_request(
            "POST",
            "/api/exports/weekly-plans",
            payload={"from": "2026-09-01", "to": "2026-09-14"},
        )
        header = json.loads(headers["x-export-warnings"][0])
        self.assertEqual(
            header,
            [
                {"code": "confirmed_not_latest", "reason": "draft_ahead"},
                {"code": "confirmed_not_latest", "reason": "stale_sources"},
                {"code": "confirmed_not_latest", "reason": "superseded"},
            ],
        )

    def test_clean_warning_success_has_no_warning_header(self):
        self.login()
        self.patch_prepare(
            return_value=make_bundle(
                items=(make_record(),), warnings=()
            )
        )
        self.patch_generate()
        _, headers, _ = api_request(
            "POST",
            "/api/exports/daily-plans",
            payload={"from": "2026-09-07", "to": "2026-09-08"},
        )
        self.assertNotIn("x-export-warnings", headers)

    def test_chinese_class_name_filename(self):
        self.login()
        record = make_record(class_name="小班甲")
        self.patch_prepare(return_value=make_bundle(items=(record,)))
        self.patch_generate()
        _, headers, _ = api_request(
            "POST",
            "/api/exports/daily-plans",
            payload={"from": "2026-09-07", "to": "2026-09-08"},
        )
        disposition = headers["content-disposition"][0]
        # ASCII fallback is stable and does not contain the Chinese name.
        self.assertIn('filename="daily-plans_2026-09-07_2026-09-08.docx"', disposition)
        self.assertIn("filename*=UTF-8''", disposition)
        # The Chinese class name only reaches the header percent-encoded.
        self.assertNotIn("小班甲", disposition)
        self.assertIn("%E5%B0%8F%E7%8F%AD%E7%94%B2", disposition)


class FilenameSafetyTests(ExportRouteTestBase):
    def payload(self):
        return {"from": "2026-09-07", "to": "2026-09-08"}

    def export_with_class(self, class_name, plan_kind="daily"):
        self.login(role="teacher", assignment_cls="cls1")
        record = make_record(class_name=class_name)
        item = make_weekly_item(class_name=class_name)
        if plan_kind == "daily":
            self.patch_prepare(return_value=make_bundle(items=(record,)))
            path_payload = self.payload()
        else:
            self.patch_load_single(return_value=item)
            path_payload = {"plan_id": "wp1"}
        self.patch_generate()
        path = (
            "/api/exports/daily-plans"
            if plan_kind == "daily"
            else "/api/exports/weekly-plans"
        )
        return api_request("POST", path, payload=path_payload)

    def test_dangerous_class_name_is_sanitized(self):
        for evil in ("a\nb\"c/d\\e", "x\r\ny", "quote\"slash/pipe|", "../evil"):
            with self.subTest(evil=evil):
                status, headers, _ = self.export_with_class(evil)
                self.assertEqual(status, 200)
                disposition = headers["content-disposition"][0]
                # No header injection: CR/LF cannot appear in a header value.
                self.assertNotIn("\n", disposition)
                self.assertNotIn("\r", disposition)
                ascii_name = disposition.split('filename="', 1)[1].split('"', 1)[0]
                for char in ('"', "/", "\\", "|", "\n", "\r"):
                    self.assertNotIn(char, ascii_name)
                # The filename* parameter is fully percent-encoded (safe=''):
                quoted = disposition.split("filename*=UTF-8''", 1)[1]
                self.assertNotIn("/", quoted)
                self.assertNotIn('"', quoted.split("%22")[0])

    def test_ascii_class_name_used_directly(self):
        _, headers, _ = self.export_with_class("K-Bee-2")
        disposition = headers["content-disposition"][0]
        self.assertIn(
            'filename="K-Bee-2_daily-plans_2026-09-07_2026-09-08.docx"',
            disposition,
        )
        self.assertIn("K-Bee-2_%E6%97%A5%E8%AE%A1%E5%88%92", disposition)

    def test_single_weekly_filename_has_week_and_dates(self):
        self.login(role="teacher", assignment_cls="cls1")
        item = make_weekly_item(
            class_name="K-2",
            week_number=3,
            term_start=date(2026, 9, 14),  # Monday
            week_days={date(2026, 9, 14): "teaching", date(2026, 9, 15): "teaching"},
        )
        self.patch_load_single(return_value=item)
        self.patch_generate()
        _, headers, _ = api_request(
            "POST", "/api/exports/weekly-plans", payload={"plan_id": "wp1"}
        )
        disposition = headers["content-disposition"][0]
        self.assertIn("weekly-plans_w3_2026-09-14_2026-09-15", disposition)


class FailurePathTests(ExportRouteTestBase):
    def login_and_prepare(self, **kw):
        self.login()
        self.patch_prepare(return_value=make_bundle(items=(make_record(),), **kw))
        return self.patch_generate()

    def test_template_error_maps_to_503_export_unavailable(self):
        generate = self.login_and_prepare()
        generate.side_effect = WordTemplateError("模板资产哈希不符")
        status, _, body = api_request(
            "POST",
            "/api/exports/daily-plans",
            payload={"from": "2026-09-07", "to": "2026-09-08"},
        )
        self.assertEqual(status, 503)
        body_error = json_body(body)["error"]
        self.assertEqual(body_error["code"], "EXPORT_UNAVAILABLE")
        self.record_operation.assert_not_called()
        self.db.commit.assert_not_called()

    def test_other_generation_error_maps_to_500_export_failed(self):
        generate = self.login_and_prepare()
        generate.side_effect = WordExportError("周计划列集合不受支持: 3")
        status, _, body = api_request(
            "POST",
            "/api/exports/daily-plans",
            payload={"from": "2026-09-07", "to": "2026-09-08"},
        )
        self.assertEqual(status, 500)
        self.assertEqual(error_code(body), "EXPORT_FAILED")
        self.record_operation.assert_not_called()
        self.db.commit.assert_not_called()

    def test_generation_failure_emits_no_docx_bytes(self):
        generate = self.login_and_prepare()
        generate.side_effect = WordTemplateError("模板缺失")
        status, headers, body = api_request(
            "POST",
            "/api/exports/daily-plans",
            payload={"from": "2026-09-07", "to": "2026-09-08"},
        )
        self.assertTrue(body.startswith(b'{"error"'))  # JSON only, never DOCX bytes
        self.assertIn("application/json", headers["content-type"][0])

    def test_markup_and_audit_never_run_after_generation_failure(self):
        self.login_and_prepare()
        self.patch_generate(side_effect=WordTemplateError("模板缺失"))
        api_request(
            "POST",
            "/api/exports/daily-plans",
            payload={"from": "2026-09-07", "to": "2026-09-08"},
        )
        self.record_operation.assert_not_called()

    def test_audit_write_failure_breaks_the_file_gate(self):
        generate = self.login_and_prepare()
        self.record_operation.side_effect = RuntimeError("audit write boom")
        status, _, body = api_request(
            "POST",
            "/api/exports/daily-plans",
            payload={"from": "2026-09-07", "to": "2026-09-08"},
        )
        self.assertEqual(status, 503)
        self.assertEqual(error_code(body), "SERVICE_UNAVAILABLE")
        generate.assert_called()  # generated, but nothing was delivered

    def test_commit_failure_breaks_the_file_gate(self):
        generate = self.login_and_prepare()
        self.db.commit.side_effect = RuntimeError("commit boom")
        status, _, body = api_request(
            "POST",
            "/api/exports/daily-plans",
            payload={"from": "2026-09-07", "to": "2026-09-08"},
        )
        self.assertEqual(status, 503)
        self.assertEqual(error_code(body), "SERVICE_UNAVAILABLE")
        # The record was appended, but commit failed and no file was returned.
        self.record_operation.assert_called_once()
        self.assertTrue(body.startswith(b'{"error"'))  # JSON only, never DOCX bytes

    def test_success_briefly_audits_correctly_and_commits(self):
        self.login()
        self.patch_prepare(return_value=make_bundle(items=(make_record(),)))
        self.patch_generate()
        status, _, _ = api_request(
            "POST",
            "/api/exports/daily-plans",
            payload={"from": "2026-09-07", "to": "2026-09-08"},
        )
        self.assertEqual(status, 200)
        kwargs = self.record_operation.call_args.kwargs
        self.assertEqual(kwargs["operator_id"], "tch1")
        self.assertEqual(kwargs["operator_type"], "account")
        self.assertEqual(kwargs["action"], "export_word")
        self.assertEqual(kwargs["target_type"], "class")
        self.assertEqual(kwargs["target_id"], "cls1")
        self.assertIsNone(kwargs["target_version_after"])
        self.db.commit.assert_called_once()

    def test_repeated_requests_re_authenticate_and_audit_each_time(self):
        self.login()
        self.patch_prepare(return_value=make_bundle(items=(make_record(),)))
        self.patch_generate()
        for _ in range(2):
            status, _, _ = api_request(
                "POST",
                "/api/exports/daily-plans",
                payload={"from": "2026-09-07", "to": "2026-09-08"},
            )
            self.assertEqual(status, 200)
        self.assertEqual(self.record_operation.call_count, 2)
        self.assertEqual(self.db.commit.call_count, 2)

    def test_failed_request_leaves_no_audit(self):
        self.login()
        self.patch_prepare(return_value=make_bundle(items=()))
        self.patch_generate()
        api_request(
            "POST",
            "/api/exports/daily-plans",
            payload={"from": "2026-09-07", "to": "2026-09-08"},
        )
        self.record_operation.assert_not_called()
        self.db.commit.assert_not_called()


class RouteRegistrationTests(unittest.TestCase):
    def test_both_export_routes_are_registered_as_post(self):
        paths = app.openapi()["paths"]
        self.assertEqual(set(paths.get("/api/exports/daily-plans", {})), {"post"})
        self.assertEqual(set(paths.get("/api/exports/weekly-plans", {})), {"post"})

    def test_export_routes_are_under_api_prefix(self):
        paths = app.openapi()["paths"]
        self.assertIn("/api/exports/daily-plans", paths)
        self.assertIn("/api/exports/weekly-plans", paths)

    def test_no_delete_or_put_on_export_routes(self):
        for path, operations in app.openapi()["paths"].items():
            if path.startswith("/api/exports/"):
                self.assertNotIn("delete", operations)
                self.assertNotIn("put", operations)
                self.assertNotIn("get", operations)


if __name__ == "__main__":
    unittest.main()
