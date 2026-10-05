"""No-DB ASGI tests for the 1B AI settings API (slice 1B).

Drives the real FastAPI app (routing, middleware, validation, response
serialization) with mocked business services and identity dependency
overrides — no MySQL. Real-cookie, real-service permission/transaction
coverage lives in tests/integration/test_ai1b_settings_api.py.

Covers B1 (registration/identity/headers), B2 (strict input), B3 (fixed
response whitelist + synthetic secret/master-key/DSN markers absent from
HTTP bodies AND the application log), B4 (DTO shapes) and the 1B repair
R4 (out-of-contract service values must map to the fixed JSON error,
never a 200 passthrough or an unhandled traceback).

Each test installs only its own mocks/overrides/log handlers and tears
them down in cleanup; synthetic markers are asserted on, never printed.
"""

import asyncio
import json
import logging
import os

os.environ["APP_DISABLE_DOTENV"] = "1"
os.environ["ALLOWED_ORIGINS"] = "http://localhost:5173,http://127.0.0.1:5173"

import unittest
from contextlib import contextmanager
from typing import Any
from unittest import mock

from app.database import get_db
from app.deps import get_auth_snapshot
from app.main import app
from app.services import ai_config_service, auth_service, prompt_service
from app.services.ai_config_service import (
    AiConfigValidationError,
    AiConfigView,
)
from app.services.auth_service import AuthSnapshot
from app.schemas import _READY_REASON_VALUES  # 定稿五个固定 reason

_ORIGIN = "http://localhost:5173"
SECRET_MARKER = "sk-unit-test-synthetic-secret-1b"
KEY_MARKER = "ai1b-unit-synthetic-master-key-1b"
DSN_MARKER = "ai1b-unit-synthetic-dsn-host-1b"
ALL_MARKERS = (SECRET_MARKER, KEY_MARKER, DSN_MARKER)

TASK = "daily_lesson_split"

ROUTES = [
    ("GET", "/api/settings/ai-config"),
    ("PATCH", "/api/settings/ai-config"),
    ("DELETE", "/api/settings/ai-config"),
    ("GET", "/api/settings/prompts"),
    ("GET", "/api/settings/prompts/{task_type}"),
    ("POST", "/api/settings/prompts/{task_type}/initialize"),
    ("PATCH", "/api/settings/prompts/{task_type}"),
    ("POST", "/api/settings/prompts/{task_type}/accept-default"),
    ("POST", "/api/settings/prompts/{task_type}/reject-default"),
    ("POST", "/api/settings/prompts/{task_type}/adapt"),
    ("GET", "/api/admin/prompt-defaults/{task_type}"),
    ("PATCH", "/api/admin/prompt-defaults/{task_type}"),
]

# The 8 real write endpoints under the 1B prefixes (method, concrete path).
WRITE_ROUTES = [
    ("PATCH", "/api/settings/ai-config"),
    ("DELETE", "/api/settings/ai-config"),
    ("POST", f"/api/settings/prompts/{TASK}/initialize"),
    ("PATCH", f"/api/settings/prompts/{TASK}"),
    ("POST", f"/api/settings/prompts/{TASK}/accept-default"),
    ("POST", f"/api/settings/prompts/{TASK}/reject-default"),
    ("POST", f"/api/settings/prompts/{TASK}/adapt"),
    ("PATCH", f"/api/admin/prompt-defaults/{TASK}"),
]

_MISSING = object()


# ---------------------------------------------------------------------------
# ASGI plumbing
# ---------------------------------------------------------------------------


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
    payload: Any = None,
    raw_body: bytes | None = None,
    origin: str | None = _ORIGIN,
    content_type: str | None = "application/json",
) -> tuple[int, dict[str, list[str]], bytes]:
    headers: dict[str, str] = {}
    body = b""
    if origin is not None:
        headers["Origin"] = origin
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
    elif raw_body is not None:
        body = raw_body
    if content_type is not None and (payload is not None or raw_body is not None):
        headers["Content-Type"] = content_type
    return asyncio.run(_asgi_request(method, path, headers=headers, body=body))


def json_body(body: bytes) -> dict:
    return json.loads(body)


@contextmanager
def capture_root_log():
    """Attach a temporary handler to the root logger and fully restore."""
    records: list[logging.LogRecord] = []

    class _Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    root = logging.getLogger()
    collector = _Collector(level=logging.DEBUG)
    previous_level = root.level
    root.addHandler(collector)
    root.setLevel(logging.DEBUG)
    try:
        yield records
    finally:
        root.removeHandler(collector)
        root.setLevel(previous_level)


def collected_text(records) -> str:
    return "\n".join(str(r.getMessage()) for r in records)


def snap(role: str = "teacher", account_id: str = "tch1") -> AuthSnapshot:
    return AuthSnapshot(
        account_id=account_id,
        role=role,
        auth_version=1,
        session_id="sess1",
        is_active=True,
        password_hash="x",
    )


def config_view(**kw) -> AiConfigView:
    base = dict(
        account_id="tch1",
        head_exists=False,
        version=None,
        protocol_id=None,
        base_url=None,
        model=None,
        has_secret=False,
        ready=False,
        ready_reason="NOT_CONFIGURED",
    )
    base.update(kw)
    return AiConfigView(**base)


def task_status(**kw) -> prompt_service.TaskStatus:
    base = dict(
        task_type=TASK,
        initialized=False,
        adaptation_state="current",
        required_contract_version=None,
        pending_default_update=False,
        latest_default_revision=1,
        latest_contract_version=1,
    )
    base.update(kw)
    return prompt_service.TaskStatus(**base)


def detail_view(**kw) -> dict:
    base = {
        "task_type": TASK,
        "state": "not_initialized",
        "latest_contract_version": 1,
        "latest_default_revision": 1,
        "guidance_fields": ["a"],
        "latest_default": {
            "default_revision": 1,
            "contract_version": 1,
            "guidance_map": {"a": "x"},
        },
        "personal_revision": None,
        "guidance_map": None,
        "based_contract_version": None,
        "accepted_default_revision": None,
        "based_guidance_fields": [],
        "adaptation_state": "current",
        "required_contract_version": None,
        "pending_default_update": False,
        "last_rejected_default_revision": None,
    }
    base.update(kw)
    return base


def default_view(**kw) -> dict:
    base = {
        "task_type": TASK,
        "default_revision": 1,
        "contract_version": 1,
        "guidance_fields": ["a"],
        "guidance_map": {"a": "x"},
    }
    base.update(kw)
    return base


def init_result(**kw) -> dict:
    base = {
        "state": "initialized",
        "idempotent": False,
        "task_type": TASK,
        "personal_revision": 1,
        "guidance_map": {"a": "x"},
        "based_contract_version": 1,
        "accepted_default_revision": 1,
    }
    base.update(kw)
    return base


def write_result(**kw) -> dict:
    base = {
        "state": "initialized",
        "task_type": TASK,
        "personal_revision": 2,
        "guidance_map": {"a": "b"},
        "based_contract_version": 1,
        "accepted_default_revision": 1,
        "adaptation_state": "current",
    }
    base.update(kw)
    return base


def reject_result(**kw) -> dict:
    base = {
        "state": "unchanged",
        "idempotent": False,
        "task_type": TASK,
        "personal_revision": 2,
        "last_rejected_default_revision": 2,
    }
    base.update(kw)
    return base


def use_legal_services() -> None:
    """Start patches so every 1B route returns a legal in-contract result.

    Stopped together by the base class ``mock.patch.stopall`` cleanup."""
    mock.patch.object(
        ai_config_service,
        "get_config",
        return_value=config_view(),
    ).start()
    mock.patch.object(
        ai_config_service, "save_config", return_value=config_view()
    ).start()
    mock.patch.object(
        ai_config_service, "clear_secret", return_value=config_view()
    ).start()
    mock.patch.object(
        prompt_service, "list_tasks", return_value=[task_status()]
    ).start()
    mock.patch.object(
        prompt_service, "read_task", return_value=detail_view()
    ).start()
    mock.patch.object(
        prompt_service, "initialize_task", return_value=init_result()
    ).start()
    mock.patch.object(
        prompt_service, "save_guidance", return_value=write_result()
    ).start()
    mock.patch.object(
        prompt_service,
        "accept_default",
        return_value=write_result(accepted_default_revision=2),
    ).start()
    mock.patch.object(
        prompt_service, "reject_default", return_value=reject_result()
    ).start()
    mock.patch.object(
        prompt_service,
        "adapt",
        return_value=write_result(
            based_contract_version=2, accepted_default_revision=2
        ),
    ).start()
    mock.patch.object(
        prompt_service, "read_default", return_value=default_view()
    ).start()
    mock.patch.object(
        prompt_service, "update_default", return_value=default_view()
    ).start()


def legal_body(path: str) -> dict:
    """A structurally legal body for the concrete write path."""
    if path.endswith("/accept-default"):
        return {
            "expected_personal_revision": 1,
            "target_default_revision": 1,
            "accepted_fields": ["a"],
        }
    if path.endswith("/reject-default"):
        return {
            "expected_personal_revision": 1,
            "target_default_revision": 1,
        }
    if path.endswith("/adapt"):
        return {
            "expected_personal_revision": 1,
            "target_contract_version": 2,
            "guidance_map": {"a": "b"},
        }
    if path.endswith(f"/prompts/{TASK}"):
        return {"expected_personal_revision": 1, "guidance_map": {"a": "b"}}
    if path.endswith(f"/prompt-defaults/{TASK}"):
        return {"expected_default_revision": 1, "guidance_map": {"a": "b"}}
    # /api/settings/ai-config (PATCH 与 DELETE)
    return {
        "expected_version": 1,
        "protocol_id": "chat_completions_v1",
        "base_url": "https://api.example.com/v1",
        "model": "m",
    }


class Ai1bApiTestBase(unittest.TestCase):
    role = "teacher"

    def setUp(self):
        app.dependency_overrides[get_db] = lambda: mock.MagicMock()
        app.dependency_overrides[get_auth_snapshot] = lambda: snap(self.role)
        self.addCleanup(app.dependency_overrides.clear)
        self.addCleanup(mock.patch.stopall)

    def _role(self, role: str) -> None:
        app.dependency_overrides[get_auth_snapshot] = lambda: snap(role)


class RouteRegistrationTests(Ai1bApiTestBase):
    def test_all_twelve_routes_registered(self):
        registered = set()
        for route in app.routes:
            inner = getattr(route, "original_router", None)
            if inner is not None:
                prefix = getattr(route.include_context, "prefix", "")
                for r in inner.routes:
                    methods = getattr(r, "methods", None) or ()
                    for m in methods:
                        if m in ("HEAD", "OPTIONS"):
                            continue
                        registered.add((m, prefix + r.path))
            else:
                methods = getattr(route, "methods", None) or ()
                for m in methods:
                    if m in ("HEAD", "OPTIONS"):
                        continue
                    registered.add((m, getattr(route, "path", "")))
        for method, path in ROUTES:
            self.assertIn((method, path), registered)

    def test_all_twelve_routes_succeed_table_driven(self):
        """B1: each of the 12 routes answers 200 with a legal request."""
        for method, path in ROUTES:
            effective = path.replace("{task_type}", TASK)
            if path.startswith("/api/admin"):
                self._role("admin")
            use_legal_services()
            if method == "GET":
                status, headers, body = api_request("GET", effective)
            elif method == "POST" and effective.endswith("/initialize"):
                status, headers, body = api_request(
                    "POST", effective, payload={}
                )
            elif method == "POST":
                status, headers, body = api_request(
                    "POST", effective, payload=legal_body(effective)
                )
            elif method == "DELETE":
                status, headers, body = api_request(
                    method, effective, payload={"expected_version": 1}
                )
            else:
                status, headers, body = api_request(
                    method, effective, payload=legal_body(effective)
                )
            self.assertEqual(
                status, 200, f"{method} {effective}: {body[:200]!r}"
            )
            self.assertIn("no-store", headers.get("cache-control", [""])[0])
            parsed = json_body(body)
            self.assertNotIn("error", parsed)


class IdentityAndHeadersTests(Ai1bApiTestBase):
    def test_get_requires_no_origin_and_returns_no_store(self):
        with mock.patch.object(
            ai_config_service,
            "get_config",
            return_value=config_view(
                version=3,
                protocol_id="chat_completions_v1",
                base_url="https://api.example.com/v1",
                model="gpt-test",
                has_secret=True,
                ready=True,
                ready_reason=None,
            ),
        ):
            status, headers, body = api_request(
                "GET", "/api/settings/ai-config", origin=None
            )
        self.assertEqual(status, 200)
        self.assertIn("no-store", headers.get("cache-control", [""])[0])
        out = json_body(body)
        self.assertEqual(
            set(out.keys()),
            {
                "version", "protocol_id", "base_url", "model",
                "has_secret", "secret_mask", "ready", "ready_reason",
            },
        )
        self.assertEqual(out["secret_mask"], "********")

    def test_write_routes_reject_origin_and_ctype_table(self):
        """B1 表驱动：8 个写接口 × 缺/错 Origin = 403、非 JSON = 422，
        错误响应均 no-store。"""
        for method, path in WRITE_ROUTES:
            use_legal_services()
            for origin in (None, "http://evil.example"):
                status, headers, _ = api_request(
                    method, path, payload=legal_body(path), origin=origin
                )
                self.assertEqual(
                    status, 403, f"{method} {path} origin={origin!r}"
                )
                self.assertIn(
                    "no-store", headers.get("cache-control", [""])[0]
                )
            status, headers, body = api_request(
                method,
                path,
                raw_body=json.dumps(legal_body(path)).encode("utf-8"),
                content_type="text/plain",
            )
            self.assertEqual(status, 422, f"{method} {path} wrong ctype")
            self.assertEqual(
                json_body(body)["error"]["code"], "VALIDATION_ERROR"
            )
            self.assertIn("no-store", headers.get("cache-control", [""])[0])

    def test_unauthenticated_shape_is_401_no_store(self):
        """HTTP 形状层面：身份依赖 401 时错误体固定且 no-store
        （真实 cookie 身份矩阵在集成层覆盖）。"""

        def _unauthorized():
            from fastapi import HTTPException

            raise HTTPException(status_code=401, detail="AUTH_REQUIRED")

        app.dependency_overrides[get_auth_snapshot] = lambda: _unauthorized()
        status, headers, body = api_request(
            "GET", "/api/settings/ai-config", origin=None
        )
        self.assertEqual(status, 401)
        self.assertEqual(json_body(body)["error"]["code"], "AUTH_REQUIRED")
        self.assertIn("no-store", headers.get("cache-control", [""])[0])

    def test_unknown_task_type_is_404(self):
        status, _, body = api_request(
            "GET", "/api/settings/prompts/not_a_real_task"
        )
        self.assertEqual(status, 404)
        self.assertEqual(
            json_body(body)["error"]["code"], "TASK_TYPE_NOT_FOUND"
        )

    def test_teacher_forbidden_on_admin_read_even_unknown_task(self):
        status, _, body = api_request(
            "GET", "/api/admin/prompt-defaults/not_a_real_task"
        )
        self.assertEqual(status, 403)
        self.assertEqual(json_body(body)["error"]["code"], "FORBIDDEN")

    def test_teacher_forbidden_on_admin_patch(self):
        status, _, body = api_request(
            "PATCH",
            f"/api/admin/prompt-defaults/{TASK}",
            payload=legal_body(f"/api/admin/prompt-defaults/{TASK}"),
        )
        self.assertEqual(status, 403)


class AdminRoleTests(Ai1bApiTestBase):
    role = "admin"

    def test_admin_unknown_task_is_404(self):
        status, _, body = api_request(
            "GET", "/api/admin/prompt-defaults/not_a_real_task"
        )
        self.assertEqual(status, 404)
        self.assertEqual(
            json_body(body)["error"]["code"], "TASK_TYPE_NOT_FOUND"
        )


class StrictInputTests(Ai1bApiTestBase):
    """B2 表驱动：每 DTO 每字段独立的必填/类型/null/extra；所有版本字段
    拒 bool/浮点/字符串（含 DELETE 与管理员默认）。

    S2(re-review 修复)：每种请求 DTO 有独立合法 builder —— DELETE 只含
    expected_version；管理员 PATCH 只含 expected_default_revision /
    guidance_map 且以 admin 身份请求。每个 case 先用合法输入经真实路由
    与合法服务 mock 确认 200，再单独制造 missing/null/type/extra 目标
    错误，避免多余字段、缺另一必填或角色 403 掩盖目标验证。"""

    # --- payload builders -------------------------------------------------

    @staticmethod
    def config_payload(**over) -> dict:
        base = {
            "expected_version": 1,
            "protocol_id": "chat_completions_v1",
            "base_url": "https://api.example.com/v1",
            "model": "m",
        }
        base.update(over)
        return base

    @staticmethod
    def delete_payload(**over) -> dict:
        """DELETE /settings/ai-config 的独立 builder：仅 expected_version。
        （S1-review 前 DELETE 复用了配置 builder，多余元信息字段先触发
        extra 校验，掩盖了版本字段的类型负例。）"""
        base = {"expected_version": 1}
        base.update(over)
        return base

    @staticmethod
    def admin_payload(**over) -> dict:
        """管理员默认发布 builder：仅 expected_default_revision +
        guidance_map，使用真实字段名（不再使用内部别名 default）。"""
        base = {"expected_default_revision": 1, "guidance_map": {"a": "b"}}
        base.update(over)
        return base

    @staticmethod
    def edit_payload(**over) -> dict:
        base = {"expected_personal_revision": 1, "guidance_map": {"a": "b"}}
        base.update(over)
        return base

    @staticmethod
    def accept_payload(**over) -> dict:
        base = {
            "expected_personal_revision": 1,
            "target_default_revision": 1,
            "accepted_fields": ["a"],
        }
        base.update(over)
        return base

    @staticmethod
    def reject_payload(**over) -> dict:
        base = {
            "expected_personal_revision": 1,
            "target_default_revision": 1,
        }
        base.update(over)
        return base

    @staticmethod
    def adapt_payload(**over) -> dict:
        base = {
            "expected_personal_revision": 1,
            "target_contract_version": 2,
            "guidance_map": {"a": "b"},
        }
        base.update(over)
        return base

    def cases(self):
        return [
            ("PATCH", "/api/settings/ai-config", self.config_payload,
             "expected_version"),
            ("PATCH", "/api/settings/ai-config", self.config_payload,
             "protocol_id"),
            ("PATCH", "/api/settings/ai-config", self.config_payload,
             "base_url"),
            ("PATCH", "/api/settings/ai-config", self.config_payload,
             "model"),
            # S2: DELETE 使用独立 builder（仅 expected_version）。
            ("DELETE", "/api/settings/ai-config", self.delete_payload,
             "expected_version"),
            ("PATCH", f"/api/settings/prompts/{TASK}", self.edit_payload,
             "expected_personal_revision"),
            ("PATCH", f"/api/settings/prompts/{TASK}", self.edit_payload,
             "guidance_map"),
            ("POST", f"/api/settings/prompts/{TASK}/accept-default",
             self.accept_payload, "expected_personal_revision"),
            ("POST", f"/api/settings/prompts/{TASK}/accept-default",
             self.accept_payload, "target_default_revision"),
            ("POST", f"/api/settings/prompts/{TASK}/accept-default",
             self.accept_payload, "accepted_fields"),
            ("POST", f"/api/settings/prompts/{TASK}/reject-default",
             self.reject_payload, "expected_personal_revision"),
            ("POST", f"/api/settings/prompts/{TASK}/reject-default",
             self.reject_payload, "target_default_revision"),
            ("POST", f"/api/settings/prompts/{TASK}/adapt",
             self.adapt_payload, "expected_personal_revision"),
            ("POST", f"/api/settings/prompts/{TASK}/adapt",
             self.adapt_payload, "target_contract_version"),
            ("POST", f"/api/settings/prompts/{TASK}/adapt",
             self.adapt_payload, "guidance_map"),
        ]

    def admin_case(self):
        """S2：管理员 case 用真实字段 expected_default_revision +
        独立 admin builder（旧别名 default 曾使 VERSION_FIELDS 空迭代、
        管理员版本负例数为 0）。"""
        return ("PATCH", f"/api/admin/prompt-defaults/{TASK}",
                self.admin_payload, "expected_default_revision")

    def admin_map_case(self):
        """S2：管理员 guidance_map 必须列入严格输入矩阵（旧实现 0 例）。"""
        return ("PATCH", f"/api/admin/prompt-defaults/{TASK}",
                self.admin_payload, "guidance_map")

    def _payload_for(self, build, field, value):
        """只改目标字段；value==_MISSING 表示删除该键。"""
        payload = build()
        if value is _MISSING:
            payload.pop(field, None)
        else:
            payload[field] = value
        return payload

    def _assert_baseline_200(self, method, path, builder):
        """每个 case 的合法基线：真实路由 + 合法服务 mock 必须 200。
        保证此后的 422 只能来自本 case 单独制造的目标错误。"""
        self._role("admin" if path.startswith("/api/admin") else "teacher")
        use_legal_services()
        status, _, body = api_request(method, path, payload=builder())
        self.assertEqual(
            status, 200, f"{method} {path} baseline {builder.__name__}: "
            f"{body[:200]!r}"
        )

    def _all_cases(self):
        """全部 (method, path, builder, field) case，含管理员两个 case。"""
        return self.cases() + [self.admin_case(), self.admin_map_case()]

    # --- 字段严格类型清单（含 bool/浮点/字符串） ----------------------------

    VERSION_FIELDS = {
        "expected_version": (True, "3", 3.0, -1),
        "expected_personal_revision": (True, "1", 1.0, 0),
        "target_default_revision": (True, "1", 1.0, 0),
        "target_contract_version": (True, "2", 2.0, 0),
        "expected_default_revision": (True, "1", 1.0, 0),
    }

    STRING_FIELDS = {
        "protocol_id": (9, True, []),
        "base_url": (9, True, []),
        "model": (9, True, []),
    }

    MAP_FIELDS = {
        "guidance_map": (
            "x", ["a"], {"a": ["x"]}, {"a": {"k": "v"}},
            {"a": "x" * 8001}, {"a": 5}, {"a": None},
        ),
        "accepted_fields": (5, {"a": 1}, [5], [None], [], ["a", "a"]),
    }

    def test_each_field_missing_is_422(self):
        for method, path, build, field in self._all_cases():
            payload = self._payload_for(build, field, _MISSING)
            self._assert_baseline_200(method, path, build)
            status, _, body = api_request(method, path, payload=payload)
            self.assertEqual(status, 422, f"{method} {path} {field} missing")
            self.assertEqual(
                json_body(body)["error"]["code"], "VALIDATION_ERROR"
            )

    def test_each_field_null_is_422(self):
        for method, path, build, field in self._all_cases():
            payload = self._payload_for(build, field, None)
            self._assert_baseline_200(method, path, build)
            status, _, body = api_request(method, path, payload=payload)
            self.assertEqual(status, 422, f"{method} {path} {field}=null")
            self.assertEqual(
                json_body(body)["error"]["code"], "VALIDATION_ERROR"
            )

    def test_each_version_field_rejects_bool_float_string(self):
        for method, path, build, field in self._all_cases():
            for bad in self.VERSION_FIELDS.get(field, ()):
                payload = self._payload_for(build, field, bad)
                self._assert_baseline_200(method, path, build)
                status, _, body = api_request(method, path, payload=payload)
                self.assertEqual(
                    status, 422, f"{method} {path} {field}={bad!r}"
                )
                self.assertEqual(
                    json_body(body)["error"]["code"], "VALIDATION_ERROR"
                )

    def test_each_string_field_rejects_off_type(self):
        for method, path, build, field in self._all_cases():
            for bad in self.STRING_FIELDS.get(field, ()):
                payload = self._payload_for(build, field, bad)
                self._assert_baseline_200(method, path, build)
                status, _, body = api_request(method, path, payload=payload)
                self.assertEqual(422, status, f"{method} {path} {field}={bad!r}")

    def test_each_map_field_rejects_off_type_and_nested(self):
        for method, path, build, field in self._all_cases():
            for bad in self.MAP_FIELDS.get(field, ()):
                payload = self._payload_for(build, field, bad)
                self._assert_baseline_200(method, path, build)
                status, _, body = api_request(method, path, payload=payload)
                self.assertEqual(422, status, f"{method} {path} {field}={bad!r}")

    # --- 每个请求 DTO 的合法形状（extra 负例的唯一来源） -------------------

    @classmethod
    def _dto_legal_payloads(cls) -> list[tuple[str, str, dict]]:
        """每个请求 DTO 一个合法 payload：(method, path, payload)。
        extra 负例 = 合法 payload 复制后仅增加一个未知顶层键。"""
        return [
            ("PATCH", "/api/settings/ai-config", cls.config_payload()),
            ("DELETE", "/api/settings/ai-config", cls.delete_payload()),
            ("POST", f"/api/settings/prompts/{TASK}/initialize", {}),
            ("PATCH", f"/api/settings/prompts/{TASK}",
             cls.edit_payload()),
            ("POST", f"/api/settings/prompts/{TASK}/accept-default",
             cls.accept_payload()),
            ("POST", f"/api/settings/prompts/{TASK}/reject-default",
             cls.reject_payload()),
            ("POST", f"/api/settings/prompts/{TASK}/adapt",
             cls.adapt_payload()),
            ("PATCH", f"/api/admin/prompt-defaults/{TASK}",
             cls.admin_payload()),
        ]

    def _assert_baseline_200_for_payload(self, method, path, payload):
        """给定完整合法 payload 的 200 基线（身份按路径选择）。"""
        self._role("admin" if path.startswith("/api/admin") else "teacher")
        use_legal_services()
        status, _, body = api_request(method, path, payload=payload)
        self.assertEqual(
            status, 200, f"{method} {path} baseline payload: "
            f"{body[:200]!r}"
        )

    def test_extra_field_rejected_for_each_dto(self):
        """S2：每个请求 DTO 的 extra 拒绝单独构造：合法 payload 复制后
        仅多一个未知顶层键；8 个请求 DTO 逐一覆盖（含 initialize、
        管理员默认与 DELETE）。"""
        for method, path, payload in self._dto_legal_payloads():
            self._assert_baseline_200_for_payload(method, path, payload)
            status, _, body = api_request(
                method, path,
                payload={**payload, "unexpected_extra": "x"},
            )
            self.assertEqual(status, 422, f"{method} {path} extra")
            self.assertEqual(
                json_body(body)["error"]["code"], "VALIDATION_ERROR"
            )

    def test_initialize_body_shapes(self):
        use_legal_services()
        self._assert_baseline_200(
            "POST", f"/api/settings/prompts/{TASK}/initialize", lambda: {}
        )
        for payload in (None, ["a"], {"account_id": "x"}):
            status, _, body = api_request(
                "POST", f"/api/settings/prompts/{TASK}/initialize",
                payload=payload,
            )
            self.assertEqual(status, 422, f"payload={payload!r}")
        for raw in (b"null", b"[]"):
            status, _, body = api_request(
                "POST", f"/api/settings/prompts/{TASK}/initialize",
                raw_body=raw,
            )
            self.assertEqual(status, 422, f"raw={raw!r}")

    def test_secret_presence_matrix(self):
        use_legal_services()
        for bad in (None, "", 12345):
            payload = self.config_payload(secret=bad)
            status, _, body = api_request(
                "PATCH", "/api/settings/ai-config", payload=payload
            )
            self.assertEqual(status, 422, f"secret={bad!r}")
            self.assertEqual(
                json_body(body)["error"]["code"], "VALIDATION_ERROR"
            )
        # 省略 -> 服务收到 SECRET_UNSET
        with mock.patch.object(
            ai_config_service, "save_config", return_value=config_view()
        ) as save:
            payload = {
                k: v for k, v in self.config_payload().items()
                if k != "secret"
            }
            status, _, _ = api_request(
                "PATCH", "/api/settings/ai-config", payload=payload
            )
        self.assertEqual(status, 200)
        self.assertIs(save.call_args.args[6], ai_config_service.SECRET_UNSET)

    def test_guidance_length_boundary(self):
        ok_value = "x" * 8000
        success = write_result(guidance_map={"theme": ok_value})
        with mock.patch.object(
            prompt_service, "save_guidance", return_value=success
        ) as edited:
            status, _, body = api_request(
                "PATCH",
                f"/api/settings/prompts/{TASK}",
                payload={
                    "expected_personal_revision": 1,
                    "guidance_map": {"theme": ok_value},
                },
            )
        self.assertEqual(status, 200, body[:200])
        self.assertEqual(json_body(body)["personal_revision"], 2)
        self.assertEqual(edited.call_args.args[4], {"theme": ok_value})
        # 8001 字符在 schema 层拒绝，服务不被调用。
        with mock.patch.object(prompt_service, "save_guidance") as sp:
            status, _, body = api_request(
                "PATCH",
                f"/api/settings/prompts/{TASK}",
                payload={
                    "expected_personal_revision": 1,
                    "guidance_map": {"theme": "x" * 8001},
                },
            )
        self.assertEqual(status, 422)
        sp.assert_not_called()

    def test_empty_patch_and_duplicate_accepted_fields(self):
        use_legal_services()
        status, _, _ = api_request(
            "PATCH",
            f"/api/settings/prompts/{TASK}",
            payload={"expected_personal_revision": 1, "guidance_map": {}},
        )
        self.assertEqual(status, 422)
        status, _, _ = api_request(
            "POST",
            f"/api/settings/prompts/{TASK}/accept-default",
            payload={
                "expected_personal_revision": 1,
                "target_default_revision": 1,
                "accepted_fields": ["a", "a"],
            },
        )
        self.assertEqual(status, 422)

    def test_validation_error_body_is_fixed(self):
        status, _, body = api_request(
            "PATCH",
            f"/api/settings/prompts/{TASK}",
            payload={
                "expected_personal_revision": True,
                "guidance_map": {"a": "b", 5: "x"},
            },
        )
        self.assertEqual(status, 422)
        parsed = json_body(body)
        self.assertEqual(
            parsed,
            {
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "请求参数校验失败",
                }
            },
        )

    def test_invalid_json_body_fixed_422(self):
        status, _, body = api_request(
            "PATCH", f"/api/settings/prompts/{TASK}", raw_body=b"{not json",
        )
        self.assertEqual(status, 422)
        self.assertEqual(
            json_body(body)["error"]["code"], "VALIDATION_ERROR"
        )


class LeakSafetyTests(Ai1bApiTestBase):
    """B3：合成 secret／主密钥／DSN 标记在成功与错误 HTTP body 及应用日志
    中均不出现；分别构造非法 URL userinfo/query（无 extra 干扰）、恶意
    未知键、嵌套 guidance 键值、含标记非法 JSON、validator ctx、typed
    服务异常。"""

    @staticmethod
    def config_payload(**over) -> dict:
        base = {
            "expected_version": 1,
            "protocol_id": "chat_completions_v1",
            "base_url": "https://api.example.com/v1",
            "model": "m",
        }
        base.update(over)
        return base

    def _assert_no_markers(self, body: bytes, records) -> None:
        body_text = body.decode("utf-8", "replace")
        log_text = collected_text(records)
        for marker in ALL_MARKERS:
            self.assertNotIn(marker, body_text, body_text[:300])
            self.assertNotIn(marker, log_text, log_text[:300])

    def _drive(self, calls):
        """calls: list[(method, path, kwargs)] -> [(status, body)]；
        全程采集应用日志并逐响应断言无标记。"""
        sent = []
        with capture_root_log() as records:
            for method, path, kwargs in calls:
                status, _headers, body = api_request(method, path, **kwargs)
                sent.append((status, body))
                self._assert_no_markers(body, records)
        return sent

    def test_invalid_url_userinfo_and_query(self):
        """非法 URL（userinfo／query，不含 extra 键）：服务 422；
        secret 与原始 URL 均不回显（body 与应用日志）。"""
        bad_urls = [
            "https://user:pass4@evil.example/v1",
            "https://api.example.com/v1?q=search",
        ]
        for bad in bad_urls:
            sent = self._drive([
                ("PATCH", "/api/settings/ai-config",
                 {"payload": dict(self.config_payload(base_url=bad),
                                  secret=SECRET_MARKER)}),
            ])
            self.assertEqual(sent[0][0], 422)
            self.assertEqual(
                json_body(sent[0][1])["error"]["code"], "VALIDATION_ERROR"
            )
            self.assertNotIn(b"evil.example", sent[0][1])
            self.assertNotIn(b"q=search", sent[0][1])

    def test_malicious_unknown_key_and_nested_guidance(self):
        hostile_key = "<script>+" + DSN_MARKER + "+</script>"
        sent = self._drive([
            ("PATCH", "/api/settings/ai-config",
             {"payload": dict(self.config_payload(secret=SECRET_MARKER),
                              **{hostile_key: KEY_MARKER})}),
            ("PATCH", f"/api/settings/prompts/{TASK}",
             {"payload": {
                 "expected_personal_revision": 1,
                 "guidance_map": {"a": {"nested": {"deep": KEY_MARKER}}},
             }}),
            ("POST", f"/api/settings/prompts/{TASK}/adapt",
             {"payload": dict(
                 legal_body(f"/api/settings/prompts/{TASK}/adapt"),
                 guidance_map={"a": [SECRET_MARKER]}),
             }),
        ])
        self.assertEqual([s for s, _ in sent], [422, 422, 422])

    def test_invalid_json_with_markers(self):
        raw = '{"model": "' + KEY_MARKER + '", "x": "' + SECRET_MARKER + '"}'
        raw2 = "{" + DSN_MARKER + " 残缺"
        sent = self._drive([
            ("PATCH", "/api/settings/ai-config", {"raw_body": raw.encode()}),
            ("PATCH", f"/api/settings/prompts/{TASK}",
             {"raw_body": raw2.encode()}),
        ])
        self.assertEqual([s for s, _ in sent], [422, 422])
        self.assertEqual(
            json_body(sent[0][1])["error"]["code"], "VALIDATION_ERROR"
        )

    def test_validator_ctx_is_not_echoed(self):
        """pydantic 错误对象（loc/msg/input/ctx）不进入响应或日志。"""
        for bad in ("x", 3.5, True):
            with capture_root_log() as records:
                status, _, body = api_request(
                    "PATCH",
                    "/api/settings/ai-config",
                    payload=dict(self.config_payload(), expected_version=bad),
                )
            self.assertEqual(status, 422, f"bad={bad!r}")
            parsed = json_body(body)
            self.assertEqual(
                set(parsed["error"].keys()), {"code", "message"}
            )
            self._assert_no_markers(body, records)

    def test_typed_service_exception_messages_never_leak(self):
        table = [
            (auth_service.AuthRequired, 401, "AUTH_REQUIRED"),
            (auth_service.VersionConflict, 409, "VERSION_CONFLICT"),
            (prompt_service.PromptNotInitialized, 409,
             "PROMPT_NOT_INITIALIZED"),
            (prompt_service.PromptAdaptationRequired, 409,
             "PROMPT_ADAPTATION_REQUIRED"),
            (prompt_service.ContractAdvanced, 409, "PROMPT_CONTRACT_CHANGED"),
            (prompt_service.DefaultContractMismatch, 409,
             "PROMPT_DEFAULT_CONTRACT_MISMATCH"),
        ]
        for exc_type, status_code, code in table:
            with mock.patch.object(
                prompt_service,
                "adapt",
                side_effect=exc_type(f"leak? {SECRET_MARKER}"),
            ):
                sent = self._drive([
                    ("POST", f"/api/settings/prompts/{TASK}/adapt",
                     {"payload": legal_body(
                         f"/api/settings/prompts/{TASK}/adapt")}),
                ])
            self.assertEqual(sent[0][0], status_code)
            self.assertEqual(json_body(sent[0][1])["error"]["code"], code)

    def test_success_and_error_paths_clean(self):
        use_legal_services()
        sent = self._drive([
            ("PATCH", "/api/settings/ai-config",
             {"payload": dict(self.config_payload(secret=SECRET_MARKER))}),
        ])
        self.assertEqual(sent[0][0], 200)
        with capture_root_log() as records:
            with mock.patch.object(
                prompt_service, "save_guidance", return_value=write_result()
            ):
                status, _headers, body = api_request(
                    "PATCH",
                    f"/api/settings/prompts/{TASK}",
                    payload={
                        "expected_personal_revision": 1,
                        "guidance_map": {"a": SECRET_MARKER},
                    },
                )
            self.assertEqual(status, 200)
            self._assert_no_markers(body, records)
            with mock.patch.object(
                ai_config_service,
                "save_config",
                side_effect=AiConfigValidationError(f"leak? {SECRET_MARKER}"),
            ):
                status, _headers, body = api_request(
                    "PATCH", "/api/settings/ai-config",
                    payload=dict(self.config_payload(secret=SECRET_MARKER)),
                )
            self.assertEqual(status, 422)
            self.assertEqual(
                json_body(body)["error"]["code"], "VALIDATION_ERROR"
            )
            self._assert_no_markers(body, records)


class OutOfContractResponseBoundaryTests(Ai1bApiTestBase):
    """R4：服务产出超出响应 DTO 契约的数据时映射为固定 JSON 503；不允许
    200 透传，也不允许测试收到未处理 traceback。"""

    def test_config_unknown_ready_reason_gets_fixed_503(self):
        with mock.patch.object(
            ai_config_service,
            "get_config",
            return_value=config_view(ready=False, ready_reason="MYSTERY"),
        ):
            status, _, body = api_request(
                "GET", "/api/settings/ai-config", origin=None
            )
        self.assertEqual(status, 503)
        self.assertEqual(
            json_body(body)["error"]["code"], "SERVICE_UNAVAILABLE"
        )
        self.assertNotIn(b"MYSTERY", body)

    def test_config_unknown_protocol_gets_fixed_503(self):
        with mock.patch.object(
            ai_config_service,
            "get_config",
            return_value=config_view(protocol_id="other_protocol_v9"),
        ):
            status, _, body = api_request(
                "GET", "/api/settings/ai-config", origin=None
            )
        self.assertEqual(status, 503)
        self.assertNotIn(b"other_protocol_v9", body)

    def test_config_legal_reasons_table(self):
        for reason in _READY_REASON_VALUES:
            with mock.patch.object(
                ai_config_service,
                "get_config",
                return_value=config_view(ready=False, ready_reason=reason),
            ):
                status, _, body = api_request(
                    "GET", "/api/settings/ai-config", origin=None
                )
            self.assertEqual(status, 200, reason)
            self.assertEqual(json_body(body)["ready_reason"], reason)
        with mock.patch.object(
            ai_config_service,
            "get_config",
            return_value=config_view(
                version=1,
                protocol_id="chat_completions_v1",
                base_url="https://api.example.com/v1",
                model="m",
                has_secret=True,
                ready=True,
                ready_reason=None,
            ),
        ):
            status, _, body = api_request(
                "GET", "/api/settings/ai-config", origin=None
            )
        self.assertEqual(status, 200)
        self.assertIsNone(json_body(body)["ready_reason"])

    def test_task_status_zero_latest_versions_get_fixed_503(self):
        with mock.patch.object(
            prompt_service,
            "list_tasks",
            return_value=[task_status(latest_default_revision=0,
                                      latest_contract_version=0)],
        ):
            status, _, body = api_request(
                "GET", "/api/settings/prompts", origin=None
            )
        self.assertEqual(status, 503)
        self.assertEqual(
            json_body(body)["error"]["code"], "SERVICE_UNAVAILABLE"
        )

    def test_task_status_legal_positive_versions_table(self):
        for rev, contract in ((1, 1), (7, 2)):
            with mock.patch.object(
                prompt_service,
                "list_tasks",
                return_value=[task_status(latest_default_revision=rev,
                                          latest_contract_version=contract)],
            ):
                status, _, body = api_request(
                    "GET", "/api/settings/prompts", origin=None
                )
            self.assertEqual(status, 200)
            out = json_body(body)
            self.assertEqual(
                out["items"][0]["latest_default_revision"], rev
            )
            self.assertEqual(
                out["items"][0]["latest_contract_version"], contract
            )


class ResponseWhitelistTests(Ai1bApiTestBase):
    def test_version_conflict_maps_409(self):
        with mock.patch.object(
            prompt_service,
            "save_guidance",
            side_effect=auth_service.VersionConflict("x"),
        ):
            status, _, body = api_request(
                "PATCH",
                f"/api/settings/prompts/{TASK}",
                payload={"expected_personal_revision": 1,
                         "guidance_map": {"a": "b"}},
            )
        self.assertEqual(status, 409)
        self.assertEqual(
            json_body(body)["error"]["code"], "VERSION_CONFLICT"
        )

    def test_prompt_not_initialized_maps_409(self):
        with mock.patch.object(
            prompt_service,
            "save_guidance",
            side_effect=prompt_service.PromptNotInitialized("x"),
        ):
            status, _, body = api_request(
                "PATCH",
                f"/api/settings/prompts/{TASK}",
                payload={"expected_personal_revision": 1,
                         "guidance_map": {"a": "b"}},
            )
        self.assertEqual(status, 409)
        self.assertEqual(
            json_body(body)["error"]["code"], "PROMPT_NOT_INITIALIZED"
        )

    def test_adaptation_required_maps_409(self):
        with mock.patch.object(
            prompt_service,
            "accept_default",
            side_effect=prompt_service.PromptAdaptationRequired(),
        ):
            status, _, body = api_request(
                "POST",
                f"/api/settings/prompts/{TASK}/accept-default",
                payload={
                    "expected_personal_revision": 1,
                    "target_default_revision": 1,
                    "accepted_fields": ["a"],
                },
            )
        self.assertEqual(status, 409)
        self.assertEqual(
            json_body(body)["error"]["code"],
            "PROMPT_ADAPTATION_REQUIRED",
        )

    def test_contract_advanced_and_mismatch_map_409(self):
        with mock.patch.object(
            prompt_service,
            "adapt",
            side_effect=prompt_service.ContractAdvanced(),
        ):
            status, _, body = api_request(
                "POST",
                f"/api/settings/prompts/{TASK}/adapt",
                payload=legal_body(f"/api/settings/prompts/{TASK}/adapt"),
            )
        self.assertEqual(status, 409)
        self.assertEqual(
            json_body(body)["error"]["code"], "PROMPT_CONTRACT_CHANGED"
        )
        with mock.patch.object(
            prompt_service,
            "adapt",
            side_effect=prompt_service.DefaultContractMismatch(),
        ):
            status, _, body = api_request(
                "POST",
                f"/api/settings/prompts/{TASK}/adapt",
                payload=legal_body(f"/api/settings/prompts/{TASK}/adapt"),
            )
        self.assertEqual(status, 409)
        self.assertEqual(
            json_body(body)["error"]["code"],
            "PROMPT_DEFAULT_CONTRACT_MISMATCH",
        )

    def test_missing_key_material_maps_503(self):
        from app.services import ai_crypto

        with mock.patch.object(
            ai_config_service,
            "save_config",
            side_effect=ai_crypto.KeyMaterialMissing(),
        ):
            status, _, body = api_request(
                "PATCH",
                "/api/settings/ai-config",
                payload=dict(
                    StrictInputTests.config_payload(secret=SECRET_MARKER)
                ),
            )
        self.assertEqual(status, 503)
        self.assertEqual(
            json_body(body)["error"]["code"], "AI_CONFIG_UNAVAILABLE"
        )
        self.assertNotIn(SECRET_MARKER.encode(), body)

    def test_unknown_task_service_error_maps_503(self):
        from app.services.ai_prompt_registry import UnknownTaskType

        with mock.patch.object(
            prompt_service,
            "read_task",
            side_effect=UnknownTaskType("missing seed"),
        ):
            status, _, body = api_request(
                "GET", f"/api/settings/prompts/{TASK}"
            )
        self.assertEqual(status, 503)
        self.assertEqual(
            json_body(body)["error"]["code"], "SERVICE_UNAVAILABLE"
        )

    def test_detail_dto_shape_initialized(self):
        view = {
            "task_type": TASK,
            "state": "initialized",
            "latest_contract_version": 2,
            "latest_default_revision": 5,
            "guidance_fields": ["a"],
            "latest_default": {
                "default_revision": 5,
                "contract_version": 2,
                "guidance_map": {"a": "x"},
            },
            "personal_revision": 3,
            "guidance_map": {"a": "y"},
            "based_contract_version": 1,
            "accepted_default_revision": 4,
            "based_guidance_fields": ["a"],
            "adaptation_state": "adaptation_required",
            "required_contract_version": 2,
            "pending_default_update": True,
            "last_rejected_default_revision": None,
        }
        with mock.patch.object(
            prompt_service, "read_task", return_value=view
        ):
            status, _, body = api_request(
                "GET", f"/api/settings/prompts/{TASK}"
            )
        self.assertEqual(status, 200)
        out = json_body(body)
        self.assertEqual(out["state"], "initialized")
        self.assertEqual(out["based_guidance_fields"], ["a"])
        self.assertEqual(out["latest_default"]["guidance_map"], {"a": "x"})

    def test_reject_out_shape(self):
        result = {
            "state": "unchanged",
            "idempotent": True,
            "task_type": TASK,
            "personal_revision": 2,
            "last_rejected_default_revision": 4,
        }
        with mock.patch.object(
            prompt_service, "reject_default", return_value=result
        ):
            status, _, body = api_request(
                "POST",
                f"/api/settings/prompts/{TASK}/reject-default",
                payload={
                    "expected_personal_revision": 2,
                    "target_default_revision": 4,
                },
            )
        self.assertEqual(status, 200)
        self.assertEqual(json_body(body)["state"], "unchanged")


class ExistingRouteValidationRegression(Ai1bApiTestBase):
    def test_existing_routes_keep_fields_error_shape(self):
        status, _, body = api_request(
            "PATCH", "/api/settings/profile", payload={"bad": 1}
        )
        self.assertEqual(status, 422)
        parsed = json_body(body)
        self.assertEqual(parsed["error"]["code"], "VALIDATION_ERROR")
        self.assertIn("fields", parsed["error"])


if __name__ == "__main__":
    unittest.main()
