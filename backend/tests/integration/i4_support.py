"""Shared fixtures and a dependency-free ASGI client for I4 integration tests.

The guard is imported first so ``I4_TEST_DATABASE_URL`` becomes the process
``DATABASE_URL`` before any ``app.config`` consumer is loaded. Nothing here
runs migrations, touches non-whitelisted schemas or reads a project ``.env``.

``AsgiClient`` drives the real FastAPI ASGI application in-process: real
routing, real dependency injection, real exception handlers, real cookies.
Only the socket is missing, so status codes and bodies are genuine HTTP
responses from the deployed router contract.
"""

from __future__ import annotations

import asyncio
import json
import os
import unittest
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlsplit

os.environ["APP_DISABLE_DOTENV"] = "1"

from tests.integration.i4_guard import (  # noqa: E402,F401  (must come first)
    INTEGRATION_ENABLED,
    check_environment,
    ensure_schema,
    make_engine,
    require_authorized_url,
    reset_i4_tables,
    skip_unless_enabled,
)

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app import security  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import get_sessionlocal  # noqa: E402
from app.services import daily_plan_service  # noqa: E402
from app.services.auth_service import AuthSnapshot  # noqa: E402

# ---------------------------------------------------------------------------
# World identity
# ---------------------------------------------------------------------------

ADMIN = {
    "id": "adm_i4",
    "username": "adm_i4",
    "display": "管理员",
    "role": "admin",
    "session": "sesadm_i4",
    "token": "tok-i4-admin",
}
OWNER = {
    "id": "tow_i4",
    "username": "tow_i4",
    "display": "甲老师",
    "role": "teacher",
    "session": "sesown_i4",
    "token": "tok-i4-owner",
}
SAME = {
    "id": "tsw_i4",
    "username": "tsw_i4",
    "display": "乙老师",
    "role": "teacher",
    "session": "sessam_i4",
    "token": "tok-i4-same",
}
CROSS = {
    "id": "tcr_i4",
    "username": "tcr_i4",
    "display": "丙老师",
    "role": "teacher",
    "session": "sescrs_i4",
    "token": "tok-i4-cross",
}
FREE = {
    "id": "tfr_i4",
    "username": "tfr_i4",
    "display": "丁老师",
    "role": "teacher",
    "session": "sesfrd_i4",
    "token": "tok-i4-free",
}

ACCOUNTS = (ADMIN, OWNER, SAME, CROSS, FREE)

CLASS_ID = "clsi4"
OTHER_CLASS_ID = "clsi4b"
TERM_ID = "teri4"
REVISION_ID = "revi4"
TERM_START = date(2026, 9, 1)
TERM_END = date(2026, 9, 30)

# Week 2 of the fixture term: Mon 2026-09-07 .. Sun 2026-09-13.
WEEK = 2
DAY_MON = date(2026, 9, 7)
DAY_TUE = date(2026, 9, 8)
DAY_WED = date(2026, 9, 9)
DAY_THU = date(2026, 9, 10)
DAY_FRI = date(2026, 9, 11)
DAY_SAT = date(2026, 9, 12)  # rest
DAY_SUN = date(2026, 9, 13)  # rest
# Week 4 (Mon 2026-09-21 .. Sun 2026-09-27): teaching days but no plans.
EMPTY_WEEK = 4
# Week 5 (Mon 2026-09-28 .. Wed 2026-09-30): calendar marks every in-term
# day non-teaching, i.e. a zero-teaching-day "empty week" (spec §5.1).
ZERO_TEACHING_WEEK = 5
ZERO_TEACHING_START = date(2026, 9, 28)

ROLLBACK_MARKER = "I4_ROLLBACK_MARKER"


def snap(account: dict) -> AuthSnapshot:
    return AuthSnapshot(
        account_id=account["id"],
        role=account["role"],
        auth_version=1,
        session_id=account["session"],
        is_active=True,
        password_hash="x",
    )


def seed_world(engine) -> None:
    """I1/I2/I3 shaped world: accounts, sessions, classes, term, calendar."""
    stamp = datetime(2026, 9, 1, 0, 0, 0)
    with engine.begin() as conn:
        for account in ACCOUNTS:
            conn.execute(
                text(
                    "INSERT INTO accounts (id, username, password_hash, "
                    "display_name, role, is_active, version, auth_version, "
                    "created_at, updated_at) VALUES "
                    "(:id, :username, 'x', :display, :role, 1, 1, 1, :ts, :ts)"
                ),
                {
                    "id": account["id"],
                    "username": account["username"],
                    "display": account["display"],
                    "role": account["role"],
                    "ts": stamp,
                },
            )
            conn.execute(
                text(
                    "INSERT INTO sessions (id, token_hash, account_id, "
                    "auth_version, created_at, expires_at, revoked_at) "
                    "VALUES (:id, :hash, :account, 1, :ts, :expires, NULL)"
                ),
                {
                    "id": account["session"],
                    "hash": security.hash_token(account["token"]),
                    "account": account["id"],
                    "ts": stamp,
                    "expires": datetime(2100, 1, 1, 0, 0, 0),
                },
            )

        conn.execute(
            text(
                "UPDATE school_settings SET school_name = '阳光园', "
                "updated_at = :ts WHERE id = 'singleton'"
            ),
            {"ts": stamp},
        )

        for class_id, name, grade, teachers, caregiver in (
            (
                CLASS_ID,
                "小班甲",
                "small",
                ["甲老师", "乙老师"],
                "李保育",
            ),
            (OTHER_CLASS_ID, "中班乙", "middle", ["丙老师"], None),
        ):
            conn.execute(
                text(
                    "INSERT INTO classes (id, name, grade, "
                    "header_teacher_names, caregiver_name, version, "
                    "created_at, updated_at) VALUES "
                    "(:id, :name, :grade, CAST(:teachers AS JSON), :caregiver, "
                    "1, :ts, :ts)"
                ),
                {
                    "id": class_id,
                    "name": name,
                    "grade": grade,
                    "teachers": json.dumps(teachers, ensure_ascii=False),
                    "caregiver": caregiver,
                    "ts": stamp,
                },
            )

        for teacher_id, class_id in (
            (OWNER["id"], CLASS_ID),
            (SAME["id"], CLASS_ID),
            (CROSS["id"], OTHER_CLASS_ID),
            # FREE stays unassigned on purpose.
        ):
            conn.execute(
                text(
                    "INSERT INTO teacher_assignments (teacher_id, class_id, "
                    "assigned_by, assigned_at) VALUES "
                    "(:teacher, :cls, :admin, :ts)"
                ),
                {"teacher": teacher_id, "cls": class_id,
                 "admin": ADMIN["id"], "ts": stamp},
            )

        conn.execute(
            text(
                "INSERT INTO terms (id, name, start_date, end_date, version, "
                "current_calendar_revision_id, created_at, updated_at) VALUES "
                "(:id, '2026秋', :start, :end, 1, NULL, :ts, :ts)"
            ),
            {"id": TERM_ID, "start": TERM_START, "end": TERM_END, "ts": stamp},
        )
        conn.execute(
            text(
                "INSERT INTO calendar_revisions (id, term_id, revision_no, "
                "term_version, start_date, end_date, library_version, "
                "created_by, created_at) VALUES "
                "(:id, :term, 1, 1, :start, :end, 'fixture-1', :admin, :ts)"
            ),
            {
                "id": REVISION_ID,
                "term": TERM_ID,
                "start": TERM_START,
                "end": TERM_END,
                "admin": ADMIN["id"],
                "ts": stamp,
            },
        )
        conn.execute(
            text(
                "UPDATE terms SET current_calendar_revision_id = :rev, "
                "updated_at = :ts WHERE id = :id"
            ),
            {"rev": REVISION_ID, "ts": stamp, "id": TERM_ID},
        )
        current = TERM_START
        while current <= TERM_END:
            if current.isoweekday() >= 6:
                state = "non_teaching"
            elif current >= ZERO_TEACHING_START:
                state = "non_teaching"
            else:
                state = "teaching"
            conn.execute(
                text(
                    "INSERT INTO calendar_days (revision_id, date, base_state, "
                    "base_library_version, override_state, override_reason, "
                    "effective_state) VALUES "
                    "(:rev, :day, :state, 'fixture-1', NULL, NULL, :state)"
                ),
                {"rev": REVISION_ID, "day": current, "state": state},
            )
            current += timedelta(days=1)


# ---------------------------------------------------------------------------
# Daily plan content builders (real I3 payload shape)
# ---------------------------------------------------------------------------


def _game_list(specs) -> list[dict]:
    """``names`` items may be plain strings or ``{name, game_id}`` dicts."""
    games: list[dict] = []
    for spec in specs:
        if isinstance(spec, str):
            games.append({"name": spec})
        else:
            item: dict[str, Any] = {"name": spec["name"]}
            if spec.get("game_id"):
                item["game_id"] = spec["game_id"]
            games.append(item)
    return games


def _group_body(spec: dict) -> dict:
    body: dict[str, Any] = {"games": _game_list(spec["names"])}
    if spec.get("group_id"):
        body["group_id"] = spec["group_id"]
    for key in ("shared_objectives", "guidance_points", "focus_guidance"):
        if key in spec:
            body[key] = spec[key]
    return body


def day_content(
    *,
    talk: str | None = "问好",
    theme: str | None = "主题活动",
    collective: dict | None = None,
    free: dict | None = None,
    focus: dict | None = None,
) -> dict:
    """Build an ``adopted_content`` payload accepted by I3 validation.

    Pass ``group_id`` / ``game_id`` inside the group spec when a later
    version must keep the same identities (I3 only preserves ids the client
    sends back).
    """
    out: dict[str, Any] = {}
    if talk is not None:
        out["morning_talk"] = {"topic": talk}
    if theme is not None:
        out["group_activity"] = {"theme": theme}

    morning: list[dict] = []
    if collective is not None:
        body = _group_body(collective)
        body["group_kind"] = "collective"
        morning.append(body)
    if free is not None:
        body = _group_body(free)
        body["group_kind"] = "free_choice"
        morning.append(body)
    if morning:
        out["morning_games"] = morning

    if focus is not None:
        body = _group_body(focus)
        body.update(
            {
                "context_kind": focus.get("context_kind", "area"),
                "area": focus.get("area", "建构区"),
                "objectives": focus.get("objectives", "区域目标"),
                "guidance": focus.get("guidance", "教师指导"),
                "support_strategy": focus.get("support_strategy", "支持策略"),
            }
        )
        out["post_group_games"] = [body]
    return out


def create_daily(
    session_factory,
    account: dict,
    plan_date: date,
    *,
    adopted_content: dict | None = None,
    raw_lesson_plan: str | None = None,
):
    db = session_factory()
    try:
        kwargs: dict[str, Any] = {"plan_date": plan_date}
        if adopted_content is not None:
            kwargs["adopted_content"] = adopted_content
        if raw_lesson_plan is not None:
            kwargs["raw_lesson_plan"] = raw_lesson_plan
        return daily_plan_service.create_or_open(db, snap(account), **kwargs)
    finally:
        db.close()


def save_daily(
    session_factory,
    account: dict,
    plan_id: str,
    expected_content_version: int,
    *,
    adopted_content: dict | None = None,
    raw_lesson_plan: str | None = None,
):
    db = session_factory()
    try:
        kwargs: dict[str, Any] = {
            "plan_id": plan_id,
            "expected_content_version": expected_content_version,
        }
        if adopted_content is not None:
            kwargs["adopted_content"] = adopted_content
        if raw_lesson_plan is not None:
            kwargs["raw_lesson_plan"] = raw_lesson_plan
        return daily_plan_service.save(db, snap(account), **kwargs)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Candidate helpers
# ---------------------------------------------------------------------------


def pick_candidate(
    detail: dict,
    *,
    category: str,
    name: str,
    on_date: str | None = None,
) -> dict:
    matches = [
        candidate
        for candidate in detail["source_candidates"]
        if candidate["category"] == category
        and candidate["name"] == name
        and (on_date is None or candidate["date"] == on_date)
    ]
    if len(matches) != 1:
        raise AssertionError(
            f"expected exactly one {category} candidate named {name!r} on "
            f"{on_date}, found {len(matches)}"
        )
    return matches[0]


def ref_payload(candidate: dict) -> dict:
    return {
        "source_kind": candidate["source_kind"],
        "daily_plan_id": candidate["daily_plan_id"],
        "content_id": candidate["content_id"],
        "content_version": candidate["content_version"],
        "group_id": candidate["group_id"],
        "game_id": candidate["game_id"],
    }


def slot_names(detail: dict) -> dict:
    slots = detail["draft"]["content"]["outdoor_game_slots"]
    return {
        key: (slot or {}).get("name")
        for key, slot in slots.items()
    }


def missing_kinds(detail_or_facts: dict) -> set[str]:
    facts = detail_or_facts.get("facts", detail_or_facts)
    return {item.get("kind") for item in facts.get("missing") or []}


# ---------------------------------------------------------------------------
# Minimal in-process ASGI HTTP client
# ---------------------------------------------------------------------------


class AsgiResponse:
    def __init__(self, status: int, headers: list[tuple[bytes, bytes]], body: bytes):
        self.status_code = status
        self.headers = headers
        self.content = body

    def header(self, name: str) -> str | None:
        target = name.lower().encode()
        for key, value in self.headers:
            if key.lower() == target:
                return value.decode("utf-8", "replace")
        return None

    @property
    def headers_list(self) -> list[tuple[str, str]]:
        return [(k.decode("latin-1"), v.decode("latin-1")) for k, v in self.headers]

    def json(self) -> Any:
        if not self.content:
            return None
        return json.loads(self.content.decode("utf-8"))

    @property
    def code(self) -> str | None:
        body = self.json()
        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict):
                return error.get("code")
        return None

    @property
    def facts(self) -> dict | None:
        body = self.json()
        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict):
                return error.get("facts")
        return None


class AsgiClient:
    """Drives ``app.main.app`` in-process with a real cookie jar."""

    def __init__(self, app=None, *, origin: str | None = None):
        if app is None:
            from app.main import app as fastapi_app

            app = fastapi_app
        self.app = app
        self.origin = origin or settings.allowed_origin_list()[0]
        self.cookies: dict[str, str] = {}

    def login_as(self, account: dict | None) -> None:
        """Attach the seeded session cookie (``None`` = anonymous)."""
        self.cookies = {}
        if account is not None:
            self.cookies["session"] = account["token"]

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> AsgiResponse:
        split = urlsplit(path)
        raw_path = split.path.encode("utf-8")
        query = split.query.encode("utf-8")

        body_bytes = b""
        out_headers: list[tuple[bytes, bytes]] = [
            (b"host", b"testserver"),
            (b"origin", self.origin.encode("utf-8")),
            (b"user-agent", b"i4-integration"),
            (b"connection", b"close"),
        ]
        if json_body is not None:
            body_bytes = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            out_headers.append((b"content-type", b"application/json"))
            out_headers.append(
                (b"content-length", str(len(body_bytes)).encode("ascii"))
            )
        if self.cookies:
            cookie = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
            out_headers.append((b"cookie", cookie.encode("utf-8")))
        if headers:
            for key, value in headers.items():
                out_headers.append((key.lower().encode(), value.encode("utf-8")))

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method.upper(),
            "scheme": "http",
            "path": split.path,
            "raw_path": raw_path,
            "query_string": query,
            "root_path": "",
            "headers": out_headers,
            "client": ("127.0.0.1", 40123),
            "server": ("testserver", 80),
        }

        received = {"body": body_bytes, "consumed": False}

        async def receive() -> dict:
            if not received["consumed"]:
                received["consumed"] = True
                return {
                    "type": "http.request",
                    "body": received["body"],
                    "more_body": False,
                }
            return {"type": "http.request", "body": b"", "more_body": False}

        collected: list[dict] = []

        async def send(message: dict) -> None:
            collected.append(message)

        async def run() -> None:
            await asyncio.wait_for(self.app(scope, receive, send), timeout=timeout)

        asyncio.run(run())

        status_code = 500
        response_headers: list[tuple[bytes, bytes]] = []
        body_parts: list[bytes] = []
        for message in collected:
            if message["type"] == "http.response.start":
                status_code = message["status"]
                response_headers = list(message.get("headers") or [])
            elif message["type"] == "http.response.body":
                body_parts.append(message.get("body") or b"")
                if message.get("more_body"):
                    continue

        response = AsgiResponse(status_code, response_headers, b"".join(body_parts))
        self._update_cookies(response)
        return response

    def get(self, path: str, **kwargs) -> AsgiResponse:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, json_body: Any = None, **kwargs) -> AsgiResponse:
        return self.request("POST", path, json_body=json_body, **kwargs)

    def patch(self, path: str, json_body: Any = None, **kwargs) -> AsgiResponse:
        return self.request("PATCH", path, json_body=json_body, **kwargs)

    def _update_cookies(self, response: AsgiResponse) -> None:
        for key, value in response.headers:
            if key.lower() != b"set-cookie":
                continue
            pair = value.decode("utf-8", "replace").split(";", 1)[0]
            if "=" not in pair:
                continue
            name, raw = pair.split("=", 1)
            name = name.strip()
            raw = raw.strip()
            lowered = value.decode("utf-8", "replace").lower()
            if raw == "" or "max-age=0" in lowered or "expires=thu, 01 jan 1970" in lowered:
                self.cookies.pop(name, None)
            else:
                self.cookies[name] = raw


# ---------------------------------------------------------------------------
# Shared test case base
# ---------------------------------------------------------------------------


@skip_unless_enabled
class I4IntegrationTestCase(unittest.TestCase):
    """Reset + reseed the whitelisted I4 database for every test."""

    engine = None
    SessionLocal = None

    @classmethod
    def setUpClass(cls):
        cls.engine = make_engine()
        require_authorized_url(str(cls.engine.url))
        check_environment(cls.engine)
        ensure_schema(cls.engine)

    @classmethod
    def tearDownClass(cls):
        if cls.engine is not None:
            cls.engine.dispose()
            cls.engine = None

    def setUp(self):
        reset_i4_tables(self.engine)
        seed_world(self.engine)
        self.SessionLocal = get_sessionlocal()
        self.client = AsgiClient()
        self.owner_client = AsgiClient()
        self.owner_client.login_as(OWNER)
        self.same_client = AsgiClient()
        self.same_client.login_as(SAME)
        self.admin_client = AsgiClient()
        self.admin_client.login_as(ADMIN)
        self.cross_client = AsgiClient()
        self.cross_client.login_as(CROSS)
        self.free_client = AsgiClient()
        self.free_client.login_as(FREE)

    # -- service-layer helpers -------------------------------------------

    def run_service(self, fn, account, **kwargs):
        db = self.SessionLocal()
        try:
            return fn(db, snap(account), **kwargs)
        finally:
            db.close()

    def session(self):
        return self.SessionLocal()

    # -- SQL helpers ------------------------------------------------------

    def scalar(self, sql: str, params: dict | None = None):
        with self.engine.connect() as conn:
            return conn.execute(text(sql), params or {}).scalar()

    def rows(self, sql: str, params: dict | None = None) -> list[tuple]:
        with self.engine.connect() as conn:
            return [tuple(r) for r in conn.execute(text(sql), params or {}).fetchall()]

    def plan_count(self) -> int:
        return int(self.scalar("SELECT COUNT(*) FROM weekly_plans") or 0)

    def draft_count(self, plan_id: str) -> int:
        return int(
            self.scalar(
                "SELECT COUNT(*) FROM weekly_plan_contents "
                "WHERE weekly_plan_id = :id",
                {"id": plan_id},
            )
            or 0
        )

    def confirmed_count(self, plan_id: str) -> int:
        return int(
            self.scalar(
                "SELECT COUNT(*) FROM weekly_plan_confirmed_contents "
                "WHERE weekly_plan_id = :id",
                {"id": plan_id},
            )
            or 0
        )

    def operation_records(self, plan_id: str, action: str | None = None) -> int:
        sql = (
            "SELECT COUNT(*) FROM operation_records "
            "WHERE target_type = 'weekly_plan' AND target_id = :id"
        )
        params: dict = {"id": plan_id}
        if action is not None:
            sql += " AND action = :action"
            params["action"] = action
        return int(self.scalar(sql, params) or 0)

    # -- weekly plan convenience -----------------------------------------

    def create_weekly(
        self, account: dict, *, week: int = WEEK, theme: str | None = None
    ):
        from app.services import weekly_plan_service

        return self.run_service(
            weekly_plan_service.create_or_open_weekly_plan,
            account,
            term_id=TERM_ID,
            week_number=week,
            theme=theme,
        )

    def detail(self, plan_id: str, *, account: dict | None = None) -> dict:
        """Read the current draft detail through the read service."""
        from app.services import weekly_plan_read_service

        account = account or OWNER
        db = self.SessionLocal()
        try:
            return weekly_plan_read_service.get_detail(
                db,
                plan_id,
                account_id=account["id"],
                role=account["role"],
                class_id=(
                    CLASS_ID
                    if account["role"] == "teacher"
                    else account.get("class_id", CLASS_ID)
                ),
            )
        finally:
            db.close()


__all__ = [
    "ACCOUNTS",
    "ADMIN",
    "AsgiClient",
    "AsgiResponse",
    "CLASS_ID",
    "CROSS",
    "DAY_FRI",
    "DAY_MON",
    "DAY_SAT",
    "DAY_SUN",
    "DAY_THU",
    "DAY_TUE",
    "DAY_WED",
    "EMPTY_WEEK",
    "FREE",
    "I4IntegrationTestCase",
    "INTEGRATION_ENABLED",
    "OTHER_CLASS_ID",
    "OWNER",
    "REVISION_ID",
    "ROLLBACK_MARKER",
    "SAME",
    "TERM_END",
    "TERM_ID",
    "TERM_START",
    "WEEK",
    "ZERO_TEACHING_WEEK",
    "check_environment",
    "create_daily",
    "create_engine",
    "day_content",
    "ensure_schema",
    "make_engine",
    "missing_kinds",
    "pick_candidate",
    "ref_payload",
    "require_authorized_url",
    "reset_i4_tables",
    "save_daily",
    "seed_world",
    "skip_unless_enabled",
    "snap",
    "slot_names",
]
