"""Shared fixtures for the I5 export MySQL integration tests.

Imports the dedicated I5 guard first (which installs the whitelisted DSN
before any ``app.config`` consumer runs), then reuses the generic
in-process ASGI HTTP client from ``i4_support`` — the I4 guard module
evaluates only its own environment switch and stays fully inert when I4
variables are absent, so no I4 DSN can leak into an I5 run.

The world mirrors the I3/I4 fixture shape (admin / owner / same-class /
cross-class / unassigned teachers, two classes, one term with a real
calendar) but uses a 12-week term (2026-08-03 .. 2026-10-25) so range
selection and the 8/9 weekly limit tests have enough distinct weeks.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from typing import Any

os.environ["APP_DISABLE_DOTENV"] = "1"

from tests.integration.i5_guard import (  # noqa: E402,F401 (guard must come first)
    ALL_TABLES,
    ALLOWED_DATABASES,
    INTEGRATION_ENABLED,
    check_environment,
    ensure_schema,
    make_engine,
    require_authorized_url,
    reset_i5_tables,
    skip_unless_enabled,
)

from tests.integration.i4_support import (  # noqa: E402  (generic ASGI client)
    AsgiClient,
    AsgiResponse,
)

from sqlalchemy import text  # noqa: E402

from app import security  # noqa: E402
from app.services.auth_service import AuthSnapshot  # noqa: E402

# ---------------------------------------------------------------------------
# world identity (distinct ids from the I4 suite; same class-role matrix)
# ---------------------------------------------------------------------------

ADMIN = {
    "id": "adm_i5",
    "username": "adm_i5",
    "display": "管理员",
    "role": "admin",
    "session": "sesadm_i5",
    "token": "tok-i5-admin",
}
OWNER = {
    "id": "tow_i5",
    "username": "tow_i5",
    "display": "甲老师",
    "role": "teacher",
    "session": "sesown_i5",
    "token": "tok-i5-owner",
}
SAME = {
    "id": "tsw_i5",
    "username": "tsw_i5",
    "display": "乙老师",
    "role": "teacher",
    "session": "sessam_i5",
    "token": "tok-i5-same",
}
CROSS = {
    "id": "tcr_i5",
    "username": "tcr_i5",
    "display": "丙老师",
    "role": "teacher",
    "session": "sescrs_i5",
    "token": "tok-i5-cross",
}
FREE = {
    "id": "tfr_i5",
    "username": "tfr_i5",
    "display": "丁老师",
    "role": "teacher",
    "session": "sesfrd_i5",
    "token": "tok-i5-free",
}

ACCOUNTS = (ADMIN, OWNER, SAME, CROSS, FREE)

CLASS_ID = "clsi5"
OTHER_CLASS_ID = "clsi5b"
TERM_ID = "teri5"
REVISION_ID = "revi5"

# Twelve full Monday-Sunday weeks: 2026-08-03 .. 2026-10-25.
TERM_START = date(2026, 8, 3)
TERM_END = date(2026, 10, 25)

WEEK = 2
DAY_MON = date(2026, 8, 10)


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
    """I1/I2/I3-shaped world with a 12-week teaching calendar."""
    stamp = datetime(2026, 8, 1, 0, 0, 0)
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
            (CLASS_ID, "小班甲", "small", ["甲老师", "乙老师"], "李保育"),
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
            # FREE stays unassigned; FREE_CLASS teacher owns THIRD class.
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
                "(:id, '2026夏秋', :start, :end, 1, NULL, :ts, :ts)"
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
            state = "teaching" if current.isoweekday() <= 5 else "non_teaching"
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


THIRD_CLASS_ID = "clsi5c"


# ---------------------------------------------------------------------------
# daily / weekly content builders
# ---------------------------------------------------------------------------


def full_day_content(theme: str = "主题活动") -> dict:
    """An ``adopted_content`` that satisfies every daily missing-fact check."""
    return {
        "morning_games": [
            {
                "group_kind": "collective",
                "games": [{"name": "老狼老狼几点了"}],
                "shared_objectives": "集体活动目标",
                "guidance_points": "集体指导要点",
                "focus_guidance": "集体重点指导",
            },
            {
                "group_kind": "free_choice",
                "games": [{"name": "沙包投准"}],
                "shared_objectives": "自主活动目标",
                "guidance_points": "自主指导要点",
                "focus_guidance": "自主重点指导",
            },
        ],
        "morning_talk": {"topic": "天气问候", "questions": "今天天气怎么样？"},
        "group_activity": {
            "theme": theme,
            "objectives": "活动目标",
            "preparation": "活动准备",
            "key_points": "活动重点",
            "difficult_points": "活动难点",
            "process": "活动过程",
        },
        "post_group_games": [
            {
                "context_kind": "area",
                "area": "建构区",
                "games": [{"name": "搭高楼"}],
                "focus_guidance": "区域重点指导",
                "objectives": "区域组目标",
                "guidance": "区域指导",
                "support_strategy": "区域支持策略",
            }
        ],
        "afternoon_outdoor": {
            "area": "操场",
            "games": [{"name": "踩影子"}],
            "observation_focus": "观察点",
            "objectives": "下午活动目标",
            "guidance": "下午指导",
            "support_strategy": "下午支持策略",
        },
        "reflection": "一日反思",
    }


def create_daily(session_factory, account: dict, plan_date: date, **kwargs):
    from app.services import daily_plan_service

    db = session_factory()
    try:
        return daily_plan_service.create_or_open(
            db, snap(account), plan_date=plan_date, **kwargs
        )
    finally:
        db.close()


def save_daily(
    session_factory, account: dict, plan_id: str, expected_content_version: int, **kwargs
):
    from app.services import daily_plan_service

    db = session_factory()
    try:
        return daily_plan_service.save(
            db,
            snap(account),
            plan_id=plan_id,
            expected_content_version=expected_content_version,
            **kwargs,
        )
    finally:
        db.close()


def create_weekly(session_factory, account: dict, *, week: int, theme: str | None = None):
    from app.services import weekly_plan_service

    db = session_factory()
    try:
        return weekly_plan_service.create_or_open_weekly_plan(
            db, snap(account), term_id=TERM_ID, week_number=week, theme=theme
        )
    finally:
        db.close()


def confirm_weekly(
    session_factory,
    account: dict,
    plan_id: str,
    *,
    expected_draft_version: int,
):
    from app.services import weekly_plan_service

    db = session_factory()
    try:
        return weekly_plan_service.confirm_weekly_plan(
            db,
            snap(account),
            plan_id=plan_id,
            expected_draft_version=expected_draft_version,
            acknowledge_missing=True,
            acknowledge_stale=True,
            note=None,
            class_id=None,
        )
    finally:
        db.close()


def save_weekly(
    session_factory,
    account: dict,
    plan_id: str,
    expected_draft_version: int,
    *,
    patch: dict | None = None,
):
    from app.services import weekly_plan_service

    db = session_factory()
    try:
        return weekly_plan_service.save_weekly_plan(
            db,
            snap(account),
            plan_id=plan_id,
            expected_draft_version=expected_draft_version,
            patch=patch or {},
            class_id=None,
        )
    finally:
        db.close()


def make_confirmed_weekly(session_factory, account: dict, *, week: int):
    """Create + confirm a weekly plan (empty snapshot is fine)."""
    result = create_weekly(session_factory, account, week=week)
    confirmed = confirm_weekly(
        session_factory, account, result.plan.id,
        expected_draft_version=result.draft.version,
    )

    class Res:  # minimal return value
        pass

    res = Res()
    res.plan = result.plan
    res.created_version = confirmed.confirmed.version
    return res


__all__ = [
    "ACCOUNTS",
    "ADMIN",
    "AsgiClient",
    "AsgiResponse",
    "CLASS_ID",
    "CROSS",
    "DAY_MON",
    "FREE",
    "INTEGRATION_ENABLED",
    "OWNER",
    "OTHER_CLASS_ID",
    "REVISION_ID",
    "SAME",
    "TERM_END",
    "TERM_ID",
    "TERM_START",
    "THIRD_CLASS_ID",
    "WEEK",
    "check_environment",
    "confirm_weekly",
    "create_daily",
    "create_weekly",
    "ensure_schema",
    "full_day_content",
    "make_confirmed_weekly",
    "make_engine",
    "reset_i5_tables",
    "require_authorized_url",
    "save_daily",
    "save_weekly",
    "seed_world",
    "skip_unless_enabled",
    "snap",
]
