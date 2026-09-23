"""I3 service-layer transaction tests on isolated MySQL 8.4 / InnoDB.

These tests require an isolated whitelisted I3 database with the I3
migrations applied and never run migrations themselves. HTTP routes exist
since slice 3, but this suite still exercises the daily plan transactional
core (and the plan-create vs config-confirm lock order of spec section 8.4)
directly against the service layer. Prepared for slice 5 (real MySQL
verification): the suite — including the V9 restart-persistence case and
both submission-order lock cases — is delivered ready for the authorized
MySQL run and has NOT been executed yet. SQLite is never used.
"""

from __future__ import annotations

import os
import threading
import unittest
from datetime import date, datetime, timedelta

os.environ["APP_DISABLE_DOTENV"] = "1"

from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from unittest import mock  # noqa: E402

# Guard first: it injects the authorized I3 DATABASE_URL before any app
# module loads app.config settings.
from tests.integration.i3_guard import (  # noqa: E402
    check_environment,
    ensure_schema,
    make_engine,
    require_authorized_url,
    reset_i3_tables,
    skip_unless_enabled,
)

from app import database as app_database  # noqa: E402
from app.database import get_sessionlocal  # noqa: E402
from app.models import WeeklyPlanSyncState  # noqa: E402
from app.services import auth_service  # noqa: E402
from app.services import config_service  # noqa: E402
from app.services import daily_plan_service  # noqa: E402
from app.services.auth_service import AuthSnapshot  # noqa: E402
from app.services.daily_plan_content import ContentValidationError  # noqa: E402


_ADMIN = ("adm01", "head_i3", "admin", "管理员", "sesadm01", "a" * 64)
_TEACHER_A = ("tch01", "teach_i3a", "teacher", "甲老师", "sestch01", "b" * 64)
_TEACHER_B = ("tch02", "teach_i3b", "teacher", "乙老师", "sestch02", "c" * 64)
_TEACHER_FREE = ("tch03", "teach_i3c", "teacher", "丙老师", "sestch03", "d" * 64)

_CLASS_ID = "cls01"
_TERM_ID = "ter01"
_REVISION_ID = "rev001"
_TERM_START = date(2026, 9, 1)
_TERM_END = date(2026, 9, 30)
_NON_TEACHING = date(2026, 9, 13)
_UNKNOWN_DAY = date(2026, 9, 14)
_PLAN_DAY_1 = date(2026, 9, 7)
_PLAN_DAY_2 = date(2026, 9, 8)
_OUTSIDE_DAY = date(2026, 10, 5)


def _snap(account: tuple, role: str | None = None) -> AuthSnapshot:
    account_id, _username, default_role, _name, session_id, _hash = account
    return AuthSnapshot(
        account_id=account_id,
        role=role or default_role,
        auth_version=1,
        session_id=session_id,
        is_active=True,
        password_hash="x",
    )


def _seed_world(engine) -> None:
    stamp = datetime(2026, 9, 1, 0, 0, 0)
    with engine.begin() as conn:
        for account in (_ADMIN, _TEACHER_A, _TEACHER_B, _TEACHER_FREE):
            account_id, username, role, display, session_id, token_hash = account
            conn.execute(
                text(
                    "INSERT INTO accounts (id, username, password_hash, "
                    "display_name, role, is_active, version, auth_version, "
                    "created_at, updated_at) VALUES "
                    "(:id, :username, 'x', :display, :role, 1, 1, 1, "
                    ":ts, :ts)"
                ),
                {
                    "id": account_id,
                    "username": username,
                    "display": display,
                    "role": role,
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
                    "id": session_id,
                    "hash": token_hash,
                    "account": account_id,
                    "ts": stamp,
                    "expires": datetime(2100, 1, 1, 0, 0, 0),
                },
            )

        conn.execute(
            text(
                "INSERT INTO classes (id, name, grade, header_teacher_names, "
                "caregiver_name, version, created_at, updated_at) VALUES "
                "(:id, '小班甲', 'small', JSON_ARRAY(), NULL, 1, :ts, :ts)"
            ),
            {"id": _CLASS_ID, "ts": stamp},
        )
        for teacher_id in (_TEACHER_A[0], _TEACHER_B[0]):
            conn.execute(
                text(
                    "INSERT INTO teacher_assignments (teacher_id, class_id, "
                    "assigned_by, assigned_at) VALUES "
                    "(:teacher, :cls, :admin, :ts)"
                ),
                {"teacher": teacher_id, "cls": _CLASS_ID,
                 "admin": _ADMIN[0], "ts": stamp},
            )

        # terms.current_calendar_revision_id and calendar_revisions.term_id
        # form a composite FK cycle: insert the term with a NULL pointer,
        # insert the revision, then point the term at the revision.
        conn.execute(
            text(
                "INSERT INTO terms (id, name, start_date, end_date, version, "
                "current_calendar_revision_id, created_at, updated_at) "
                "VALUES (:id, '2026秋', :start, :end, 1, NULL, :ts, :ts)"
            ),
            {
                "id": _TERM_ID,
                "start": _TERM_START,
                "end": _TERM_END,
                "ts": stamp,
            },
        )
        conn.execute(
            text(
                "INSERT INTO calendar_revisions (id, term_id, revision_no, "
                "term_version, start_date, end_date, library_version, "
                "created_by, created_at) VALUES "
                "(:id, :term, 1, 1, :start, :end, 'fixture-1', :admin, :ts)"
            ),
            {
                "id": _REVISION_ID,
                "term": _TERM_ID,
                "start": _TERM_START,
                "end": _TERM_END,
                "admin": _ADMIN[0],
                "ts": stamp,
            },
        )
        conn.execute(
            text(
                "UPDATE terms SET current_calendar_revision_id = :rev, "
                "updated_at = :ts WHERE id = :id"
            ),
            {"rev": _REVISION_ID, "ts": stamp, "id": _TERM_ID},
        )
        current = _TERM_START
        while current <= _TERM_END:
            if current == _NON_TEACHING:
                base_state = "non_teaching"
            elif current == _UNKNOWN_DAY:
                base_state = "unknown"
            else:
                base_state = "teaching"
            conn.execute(
                text(
                    "INSERT INTO calendar_days (revision_id, date, base_state, "
                    "base_library_version, override_state, override_reason, "
                    "effective_state) VALUES "
                    "(:rev, :day, :state, 'fixture-1', NULL, NULL, :state)"
                ),
                {"rev": _REVISION_ID, "day": current, "state": base_state},
            )
            current += timedelta(days=1)


@skip_unless_enabled
class DailyPlanServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = make_engine()
        require_authorized_url(str(cls.engine.url))
        check_environment(cls.engine)
        ensure_schema(cls.engine)
        cls.SessionLocal = None

    def setUp(self):
        reset_i3_tables(self.engine)
        _seed_world(self.engine)
        self.SessionLocal = get_sessionlocal()

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    # -- helpers ----------------------------------------------------------

    def _run(self, fn, snapshot, **kwargs):
        db = self.SessionLocal()
        try:
            return fn(db, snapshot, **kwargs)
        finally:
            db.close()

    def _scalar(self, sql: str, params: dict | None = None):
        with self.engine.connect() as conn:
            return conn.execute(text(sql), params or {}).scalar()

    def _plans_started_at(self):
        return self._scalar("SELECT plans_started_at FROM school_settings")

    def _plan_count(self) -> int:
        return int(self._scalar("SELECT COUNT(*) FROM daily_plans") or 0)

    def _sync_row(self) -> WeeklyPlanSyncState | None:
        db = self.SessionLocal()
        try:
            row = daily_plan_service.get_sync_state(
                db, _CLASS_ID, _TERM_ID, 2
            )
            if row is not None:
                db.commit()
            return row
        finally:
            db.close()

    # -- helpers for restart / lock-order cases ----------------------------

    _PERSISTENCE_QUERIES = {
        "plans": (
            "SELECT id, class_id, term_id, plan_date, creator_id, "
            "week_number, weekday, current_content_id, "
            "current_content_version, creator_display_name, school_name, "
            "class_name, grade, deleted_at, deleted_by, created_at, "
            "updated_at FROM daily_plans ORDER BY id"
        ),
        "contents": (
            "SELECT id, daily_plan_id, version, raw_lesson_plan, "
            "split_baseline, adopted_content, editor_id, created_at "
            "FROM daily_plan_contents ORDER BY daily_plan_id, version"
        ),
        "sync": (
            "SELECT id, class_id, term_id, week_number, status, "
            "deterministic_themes, game_source_manifest, "
            "current_week_source_manifest, last_trigger_daily_plan_id, "
            "last_trigger_content_version, last_trigger_event, "
            "created_at, updated_at FROM weekly_plan_sync_states ORDER BY id"
        ),
        "school": (
            "SELECT id, school_name, version, schedule_version, "
            "plans_started_at, created_at, updated_at "
            "FROM school_settings ORDER BY id"
        ),
        "terms": (
            "SELECT id, name, start_date, end_date, version, "
            "current_calendar_revision_id, created_at, updated_at "
            "FROM terms ORDER BY id"
        ),
        "revisions": (
            "SELECT id, term_id, revision_no, term_version, start_date, "
            "end_date, library_version, created_by, created_at "
            "FROM calendar_revisions ORDER BY id"
        ),
        "calendar_days": (
            "SELECT revision_id, date, base_state, base_library_version, "
            "override_state, override_reason, effective_state "
            "FROM calendar_days ORDER BY revision_id, date"
        ),
        "records": (
            "SELECT id, action, target_type, target_id, "
            "target_version_after, created_at "
            "FROM operation_records ORDER BY id"
        ),
    }

    def _persistent_snapshot(self, engine) -> dict[str, list[tuple]]:
        snapshot: dict[str, list[tuple]] = {}
        with engine.connect() as conn:
            for key, sql in self._PERSISTENCE_QUERIES.items():
                snapshot[key] = [
                    tuple(row)
                    for row in conn.execute(text(sql)).fetchall()
                ]
        return snapshot

    def _restart_engine_and_factory(self):
        """Dispose current engine/session singletons; build fresh ones.

        Simulates a process restart: the old pooled engine and the app
        session-factory singletons are dropped, then a brand-new engine and
        sessionmaker are created against the same authorized DSN.
        """
        self.engine.dispose()
        if app_database._engine is not None:
            app_database._engine.dispose()
        app_database._engine = None
        app_database._SessionLocal = None
        restarted_engine = make_engine()
        require_authorized_url(str(restarted_engine.url))
        type(self).engine = restarted_engine
        restarted_factory = sessionmaker(
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
            bind=restarted_engine,
        )
        self.SessionLocal = restarted_factory
        return restarted_factory

    @staticmethod
    def _thread_session(engine):
        """Independent session factory/session for one worker thread."""
        factory = sessionmaker(
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
            bind=engine,
        )
        return factory()

    @staticmethod
    def _observing_lock_school(module, original, attempting, acquired):
        """Wrap ``module.lock_school`` with real-lock attempt/acquire events.

        ``attempting`` fires immediately before the untouched original
        ``lock_school`` runs; ``acquired`` fires only after it returns.
        The original function is never replaced by a stub, so the wrapper
        still executes the real ``FOR UPDATE`` row lock.
        """

        def observing(sess):
            attempting.set()
            row = original(sess)
            acquired.set()
            return row

        return mock.patch.object(module, "lock_school", observing)

    def _create_school_preview(
        self, school_name: str
    ) -> tuple[str, list[str], object]:
        version = int(self._scalar("SELECT version FROM school_settings"))
        db = self.SessionLocal()
        try:
            row = config_service.create_preview(
                db,
                _snap(_ADMIN),
                "school_update",
                {"school_name": school_name, "expected_version": version},
            )
            change_id = row.id
            blockers = list(row.impact_summary.get("blockers") or [])
            plans_started = row.base_versions.get("plans_started")
            return change_id, blockers, plans_started
        finally:
            db.close()

    def _create_calendar_override_preview(
        self,
    ) -> tuple[str, list[str], object]:
        schedule_version = int(
            self._scalar("SELECT schedule_version FROM school_settings")
        )
        term_version = int(
            self._scalar(
                "SELECT version FROM terms WHERE id = :id",
                {"id": _TERM_ID},
            )
        )
        db = self.SessionLocal()
        try:
            row = config_service.create_preview(
                db,
                _snap(_ADMIN),
                "calendar_override",
                {
                    "target_id": _TERM_ID,
                    "expected_term_version": term_version,
                    "expected_calendar_revision_id": _REVISION_ID,
                    "expected_schedule_version": schedule_version,
                    "dates": [
                        {
                            "date": _PLAN_DAY_1.isoformat(),
                            "state": "non_teaching",
                            "reason": "锁序验证",
                        }
                    ],
                },
            )
            change_id = row.id
            blockers = list(row.impact_summary.get("blockers") or [])
            plans_started = row.base_versions.get("plans_started")
            return change_id, blockers, plans_started
        finally:
            db.close()

    def _change_row(self, change_id: str) -> tuple[str, bool, bool]:
        # SQLAlchemy JSON binds Python None as JSON null (not SQL NULL), so
        # treat only a real result object as "result_versions present".
        with self.engine.connect() as conn:
            status, applied_at, result_versions = conn.execute(
                text(
                    "SELECT status, applied_at IS NOT NULL, "
                    "result_versions IS NOT NULL AND "
                    "JSON_TYPE(result_versions) = 'OBJECT' "
                    "FROM configuration_changes WHERE id = :id"
                ),
                {"id": change_id},
            ).one()
        return status, bool(applied_at), bool(result_versions)

    # -- create / open ----------------------------------------------------

    def test_create_writes_plan_content_projection_and_stage_marker(self):
        plan, content, created = self._run(
            daily_plan_service.create_or_open,
            _snap(_TEACHER_A),
            plan_date=_PLAN_DAY_1,
            raw_lesson_plan="完整教案",
            adopted_content={
                "morning_talk": {"topic": "问好"},
                "post_group_games": [
                    {
                        "context_kind": "area",
                        "area": "建构区",
                        "games": [{"name": "积木"}],
                    }
                ],
                "afternoon_outdoor": {
                    "area": "操场",
                    "observation_focus": "排队安全",
                    "games": [{"name": "皮球"}],
                },
            },
        )
        self.assertTrue(created)
        self.assertEqual(plan.class_id, _CLASS_ID)
        self.assertEqual(plan.term_id, _TERM_ID)
        self.assertEqual(plan.week_number, 2)
        self.assertEqual(plan.weekday, 1)
        self.assertEqual(plan.creator_id, _TEACHER_A[0])
        self.assertEqual(plan.creator_display_name, "甲老师")
        self.assertEqual(plan.class_name, "小班甲")
        self.assertEqual(plan.grade, "small")
        self.assertEqual(content.version, 1)
        self.assertEqual(content.raw_lesson_plan, "完整教案")
        self.assertIsNone(content.split_baseline)
        self.assertEqual(plan.current_content_id, content.id)
        self.assertEqual(plan.current_content_version, 1)
        self.assertEqual(
            content.adopted_content["post_group_games"][0]["context_kind"],
            "area",
        )
        self.assertEqual(
            content.adopted_content["afternoon_outdoor"]["observation_focus"],
            "排队安全",
        )
        self.assertNotIn(
            "focus_guidance", content.adopted_content["afternoon_outdoor"]
        )

        self.assertIsNotNone(self._plans_started_at())
        row = self._sync_row()
        self.assertIsNotNone(row)
        self.assertEqual(row.status, "pending_projection")
        self.assertEqual(row.last_trigger_event, "create")
        self.assertEqual(row.last_trigger_content_version, 1)
        self.assertEqual(
            row.current_week_source_manifest,
            [
                {
                    "daily_plan_id": plan.id,
                    "current_content_id": content.id,
                    "current_content_version": 1,
                    "date": _PLAN_DAY_1.isoformat(),
                }
            ],
        )
        self.assertEqual(
            row.deterministic_themes[0]["morning_talk_topic"], "问好"
        )
        self.assertEqual(
            [m["context_kind"] for m in row.game_source_manifest],
            ["area", None],
        )

        record = self._scalar(
            "SELECT action FROM operation_records "
            "WHERE target_type = 'daily_plan' AND target_id = :id",
            {"id": plan.id},
        )
        self.assertEqual(record, "create_daily_plan")
        version_after = self._scalar(
            "SELECT target_version_after FROM operation_records "
            "WHERE target_type = 'daily_plan' AND target_id = :id",
            {"id": plan.id},
        )
        self.assertEqual(int(version_after), 1)

    def test_repeat_create_opens_existing_without_second_row(self):
        plan_a, content_a, created_a = self._run(
            daily_plan_service.create_or_open,
            _snap(_TEACHER_A),
            plan_date=_PLAN_DAY_1,
            adopted_content={"reflection": "第一"},
        )
        plan_b, content_b, created_b = self._run(
            daily_plan_service.create_or_open,
            _snap(_TEACHER_B),
            plan_date=_PLAN_DAY_1,
            adopted_content={"reflection": "第二"},
        )
        self.assertTrue(created_a)
        self.assertFalse(created_b)
        self.assertEqual(plan_a.id, plan_b.id)
        self.assertEqual(plan_b.creator_id, _TEACHER_A[0])
        self.assertEqual(content_b.id, content_a.id)
        self.assertEqual(content_b.adopted_content, {"reflection": "第一"})
        self.assertEqual(self._plan_count(), 1)
        records = self._scalar(
            "SELECT COUNT(*) FROM operation_records "
            "WHERE target_type = 'daily_plan'"
        )
        self.assertEqual(int(records), 1)

    def test_create_empty_content_allowed_without_fill_in(self):
        plan, content, created = self._run(
            daily_plan_service.create_or_open,
            _snap(_TEACHER_A),
            plan_date=_PLAN_DAY_1,
        )
        self.assertTrue(created)
        self.assertEqual(content.adopted_content, {})
        self.assertIsNone(content.raw_lesson_plan)

    def test_admin_must_pass_class_id_and_teacher_must_not(self):
        with self.assertRaises(daily_plan_service.DailyPlanValidationError):
            self._run(
                daily_plan_service.create_or_open,
                _snap(_ADMIN),
                plan_date=_PLAN_DAY_1,
            )
        with self.assertRaises(daily_plan_service.DailyPlanValidationError):
            self._run(
                daily_plan_service.create_or_open,
                _snap(_TEACHER_A),
                plan_date=_PLAN_DAY_1,
                class_id=_CLASS_ID,
            )
        self.assertEqual(self._plan_count(), 0)
        self.assertIsNone(self._plans_started_at())

    def test_unassigned_teacher_is_forbidden(self):
        with self.assertRaises(daily_plan_service.DailyPlanForbidden):
            self._run(
                daily_plan_service.create_or_open,
                _snap(_TEACHER_FREE),
                plan_date=_PLAN_DAY_1,
            )
        self.assertEqual(self._plan_count(), 0)

    def test_admin_can_create_with_explicit_class(self):
        plan, _content, created = self._run(
            daily_plan_service.create_or_open,
            _snap(_ADMIN),
            plan_date=_PLAN_DAY_1,
            class_id=_CLASS_ID,
        )
        self.assertTrue(created)
        self.assertEqual(plan.class_id, _CLASS_ID)

    # -- date eligibility -------------------------------------------------

    def test_outside_term_rejected_without_partial_writes(self):
        with self.assertRaises(daily_plan_service.DailyPlanOutsideTerm):
            self._run(
                daily_plan_service.create_or_open,
                _snap(_TEACHER_A),
                plan_date=_OUTSIDE_DAY,
            )
        self.assertEqual(self._plan_count(), 0)
        self.assertIsNone(self._plans_started_at())
        self.assertIsNone(self._sync_row())
        records = self._scalar(
            "SELECT COUNT(*) FROM operation_records "
            "WHERE target_type = 'daily_plan'"
        )
        self.assertEqual(int(records), 0)

    def test_non_teaching_day_rejected(self):
        with self.assertRaises(daily_plan_service.DailyPlanDateNotEligible):
            self._run(
                daily_plan_service.create_or_open,
                _snap(_TEACHER_A),
                plan_date=_NON_TEACHING,
            )
        self.assertEqual(self._plan_count(), 0)
        self.assertIsNone(self._plans_started_at())

    def test_unknown_year_day_rejected(self):
        with self.assertRaises(daily_plan_service.DailyPlanYearNotCovered):
            self._run(
                daily_plan_service.create_or_open,
                _snap(_TEACHER_A),
                plan_date=_UNKNOWN_DAY,
            )
        self.assertEqual(self._plan_count(), 0)

    # -- save / versions --------------------------------------------------

    def test_save_appends_version_and_updates_pointer(self):
        plan, v1, _ = self._run(
            daily_plan_service.create_or_open,
            _snap(_TEACHER_A),
            plan_date=_PLAN_DAY_1,
            adopted_content={"reflection": "v1"},
        )
        saved_plan, v2 = self._run(
            daily_plan_service.save,
            _snap(_TEACHER_A),
            plan_id=plan.id,
            expected_content_version=1,
            adopted_content={"reflection": "v2"},
        )
        self.assertEqual(v2.version, 2)
        self.assertEqual(saved_plan.current_content_version, 2)
        self.assertEqual(saved_plan.current_content_id, v2.id)
        self.assertEqual(v1.version, 1)
        with self.engine.connect() as conn:
            versions = [
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT version FROM daily_plan_contents "
                        "WHERE daily_plan_id = :id ORDER BY version"
                    ),
                    {"id": plan.id},
                )
            ]
        self.assertEqual(versions, [1, 2])
        row = self._sync_row()
        self.assertEqual(row.last_trigger_event, "update")
        self.assertEqual(row.last_trigger_content_version, 2)
        self.assertEqual(
            row.current_week_source_manifest[0]["current_content_version"], 2
        )

    def test_version_conflict_is_rejected_without_overwrite(self):
        plan, _v1, _ = self._run(
            daily_plan_service.create_or_open,
            _snap(_TEACHER_A),
            plan_date=_PLAN_DAY_1,
            adopted_content={"reflection": "original"},
        )
        self._run(
            daily_plan_service.save,
            _snap(_TEACHER_A),
            plan_id=plan.id,
            expected_content_version=1,
            adopted_content={"reflection": "winner"},
        )
        with self.assertRaises(daily_plan_service.DailyPlanVersionConflict):
            self._run(
                daily_plan_service.save,
                _snap(_TEACHER_A),
                plan_id=plan.id,
                expected_content_version=1,
                adopted_content={"reflection": "loser"},
            )
        db = self.SessionLocal()
        try:
            _plan, content = daily_plan_service.get(db, plan.id)
        finally:
            db.close()
        self.assertEqual(content.version, 2)
        self.assertEqual(content.adopted_content, {"reflection": "winner"})

    def test_save_inherits_omitted_fields_and_replaces_when_provided(self):
        plan, _v1, _ = self._run(
            daily_plan_service.create_or_open,
            _snap(_TEACHER_A),
            plan_date=_PLAN_DAY_1,
            raw_lesson_plan="教案X",
            adopted_content={
                "reflection": "a",
                "morning_talk": {"topic": "t"},
            },
        )
        _p, inherited = self._run(
            daily_plan_service.save,
            _snap(_TEACHER_A),
            plan_id=plan.id,
            expected_content_version=1,
            raw_lesson_plan="教案Y",
        )
        self.assertEqual(inherited.raw_lesson_plan, "教案Y")
        self.assertEqual(
            inherited.adopted_content,
            {"reflection": "a", "morning_talk": {"topic": "t"}},
        )

        _p, replaced = self._run(
            daily_plan_service.save,
            _snap(_TEACHER_A),
            plan_id=plan.id,
            expected_content_version=2,
            adopted_content={"reflection": "b"},
        )
        self.assertEqual(replaced.adopted_content, {"reflection": "b"})
        self.assertEqual(replaced.raw_lesson_plan, "教案Y")
        self.assertIsNone(replaced.split_baseline)

    def test_save_preserves_group_and_game_ids_across_versions(self):
        plan, v1, _ = self._run(
            daily_plan_service.create_or_open,
            _snap(_TEACHER_A),
            plan_date=_PLAN_DAY_1,
            adopted_content={
                "morning_games": [
                    {
                        "group_kind": "collective",
                        "games": [{"name": "跳绳"}],
                    }
                ]
            },
        )
        group_id = v1.adopted_content["morning_games"][0]["group_id"]
        game_id = v1.adopted_content["morning_games"][0]["games"][0]["game_id"]

        _p, v2 = self._run(
            daily_plan_service.save,
            _snap(_TEACHER_A),
            plan_id=plan.id,
            expected_content_version=1,
            adopted_content={
                "morning_games": [
                    {
                        "group_id": group_id,
                        "group_kind": "collective",
                        "games": [
                            {"game_id": game_id, "name": "跳绳加急"},
                            {"name": "新游戏"},
                        ],
                    }
                ]
            },
        )
        groups = v2.adopted_content["morning_games"]
        self.assertEqual(groups[0]["group_id"], group_id)
        self.assertEqual(groups[0]["games"][0]["game_id"], game_id)
        self.assertNotEqual(groups[0]["games"][1]["game_id"], game_id)

    def test_save_rejects_client_supplied_new_ids(self):
        plan, _v1, _ = self._run(
            daily_plan_service.create_or_open,
            _snap(_TEACHER_A),
            plan_date=_PLAN_DAY_1,
        )
        with self.assertRaises(ContentValidationError):
            self._run(
                daily_plan_service.save,
                _snap(_TEACHER_A),
                plan_id=plan.id,
                expected_content_version=1,
                adopted_content={
                    "morning_games": [
                        {
                            "group_id": "forged-group",
                            "group_kind": "collective",
                            "games": [],
                        }
                    ]
                },
            )

    def test_non_creator_teacher_cannot_save(self):
        plan, _v1, _ = self._run(
            daily_plan_service.create_or_open,
            _snap(_TEACHER_A),
            plan_date=_PLAN_DAY_1,
        )
        with self.assertRaises(daily_plan_service.DailyPlanForbidden):
            self._run(
                daily_plan_service.save,
                _snap(_TEACHER_B),
                plan_id=plan.id,
                expected_content_version=1,
                adopted_content={"reflection": "x"},
            )
        with self.assertRaises(daily_plan_service.DailyPlanForbidden):
            self._run(
                daily_plan_service.save,
                _snap(_TEACHER_FREE),
                plan_id=plan.id,
                expected_content_version=1,
                adopted_content={"reflection": "x"},
            )

    def test_admin_can_save_any_plan(self):
        plan, _v1, _ = self._run(
            daily_plan_service.create_or_open,
            _snap(_TEACHER_A),
            plan_date=_PLAN_DAY_1,
        )
        _p, v2 = self._run(
            daily_plan_service.save,
            _snap(_ADMIN),
            plan_id=plan.id,
            expected_content_version=1,
            adopted_content={"reflection": "admin"},
        )
        self.assertEqual(v2.version, 2)

    # -- weekly projection covers the whole week --------------------------

    def test_projection_recomputes_all_days_not_only_last_source(self):
        plan_1, _v1a, _ = self._run(
            daily_plan_service.create_or_open,
            _snap(_TEACHER_A),
            plan_date=_PLAN_DAY_1,
            adopted_content={"morning_talk": {"topic": "周一话题"}},
        )
        plan_2, _v1b, _ = self._run(
            daily_plan_service.create_or_open,
            _snap(_TEACHER_B),
            plan_date=_PLAN_DAY_2,
            adopted_content={"group_activity": {"theme": "周二主题"}},
        )
        row = self._sync_row()
        self.assertEqual(len(row.current_week_source_manifest), 2)
        self.assertEqual(
            [item["daily_plan_id"] for item in row.current_week_source_manifest],
            [plan_1.id, plan_2.id],
        )
        self.assertEqual(
            [item["morning_talk_topic"] for item in row.deterministic_themes],
            ["周一话题", ""],
        )

        self._run(
            daily_plan_service.save,
            _snap(_TEACHER_A),
            plan_id=plan_1.id,
            expected_content_version=1,
            adopted_content={"morning_talk": {"topic": "周一话题改"}},
        )
        row = self._sync_row()
        self.assertEqual(len(row.current_week_source_manifest), 2)
        by_id = {
            item["daily_plan_id"]: item
            for item in row.current_week_source_manifest
        }
        self.assertEqual(by_id[plan_1.id]["current_content_version"], 2)
        self.assertEqual(by_id[plan_2.id]["current_content_version"], 1)
        self.assertEqual(
            [item["morning_talk_topic"] for item in row.deterministic_themes],
            ["周一话题改", ""],
        )
        self.assertEqual(row.last_trigger_daily_plan_id, plan_1.id)

    # -- reads ------------------------------------------------------------

    def test_get_and_list_and_by_date(self):
        plan, _content, _ = self._run(
            daily_plan_service.create_or_open,
            _snap(_TEACHER_A),
            plan_date=_PLAN_DAY_1,
        )
        db = self.SessionLocal()
        try:
            got_plan, got_content = daily_plan_service.get(db, plan.id)
            self.assertEqual(got_plan.id, plan.id)
            self.assertEqual(got_content.version, 1)

            by_date_plan, _ = daily_plan_service.get_by_date(
                db, _CLASS_ID, _PLAN_DAY_1
            )
            self.assertEqual(by_date_plan.id, plan.id)

            rows, total = daily_plan_service.list_plans(
                db, class_id=_CLASS_ID, offset=0, limit=20
            )
            self.assertEqual(total, 1)
            self.assertEqual(rows[0].id, plan.id)

            with self.assertRaises(daily_plan_service.DailyPlanNotFound):
                daily_plan_service.get_by_date(db, _CLASS_ID, _PLAN_DAY_2)
            with self.assertRaises(daily_plan_service.DailyPlanValidationError):
                daily_plan_service.list_plans(
                    db, class_id=_CLASS_ID, offset=0, limit=0
                )
            with self.assertRaises(daily_plan_service.DailyPlanValidationError):
                daily_plan_service.list_plans(
                    db,
                    class_id=_CLASS_ID,
                    from_date=_PLAN_DAY_2,
                    to_date=_PLAN_DAY_1,
                )
        finally:
            db.close()

    # -- atomicity --------------------------------------------------------

    def test_mysql_error_rolls_back_every_partial_write(self):
        original = auth_service.record_operation

        def failing_record(db, **kwargs):
            original(db, **kwargs)
            db.flush()
            # Valid MySQL syntax; fails because the table does not exist.
            db.execute(
                text("INSERT INTO no_such_table_i3 (id) VALUES ('x')")
            )

        db = self.SessionLocal()
        try:
            with mock.patch.object(
                auth_service, "record_operation", failing_record
            ):
                with self.assertRaises(SQLAlchemyError):
                    daily_plan_service.create_or_open(
                        db,
                        _snap(_TEACHER_A),
                        plan_date=_PLAN_DAY_1,
                        adopted_content={"reflection": "partial"},
                    )
            db.rollback()
        finally:
            db.close()

        with self.engine.connect() as conn:
            plans = conn.execute(text("SELECT COUNT(*) FROM daily_plans")).scalar()
            contents = conn.execute(
                text("SELECT COUNT(*) FROM daily_plan_contents")
            ).scalar()
            syncs = conn.execute(
                text("SELECT COUNT(*) FROM weekly_plan_sync_states")
            ).scalar()
            records = conn.execute(
                text(
                    "SELECT COUNT(*) FROM operation_records "
                    "WHERE target_type = 'daily_plan'"
                )
            ).scalar()
            started = conn.execute(
                text("SELECT plans_started_at FROM school_settings")
            ).scalar()
        self.assertEqual(plans, 0)
        self.assertEqual(contents, 0)
        self.assertEqual(syncs, 0)
        self.assertEqual(records, 0)
        self.assertIsNone(started)

        # A later clean create must still succeed and set the marker once.
        _plan, _content, created = self._run(
            daily_plan_service.create_or_open,
            _snap(_TEACHER_A),
            plan_date=_PLAN_DAY_1,
        )
        self.assertTrue(created)
        self.assertIsNotNone(self._plans_started_at())

    # -- restart persistence (V9) -----------------------------------------

    def test_restart_read_keeps_plan_projection_marker_and_calendar(self):
        plan, _v1, created = self._run(
            daily_plan_service.create_or_open,
            _snap(_TEACHER_A),
            plan_date=_PLAN_DAY_1,
            raw_lesson_plan="重启前教案",
            adopted_content={"morning_talk": {"topic": "重启前话题"}},
        )
        self.assertTrue(created)
        saved_plan, v2 = self._run(
            daily_plan_service.save,
            _snap(_TEACHER_A),
            plan_id=plan.id,
            expected_content_version=1,
            adopted_content={"morning_talk": {"topic": "重启前话题改"}},
        )
        self.assertEqual(saved_plan.current_content_version, 2)
        plan_id = plan.id
        v2_id = v2.id
        plan_school_name = plan.school_name
        started_before = self._plans_started_at()
        self.assertIsNotNone(started_before)
        pre = self._persistent_snapshot(self.engine)

        # Dispose the current engine/session singletons and read through a
        # brand-new engine + session factory, as a process restart would.
        RestartSession = self._restart_engine_and_factory()

        db = RestartSession()
        try:
            got_plan, got_content = daily_plan_service.get(db, plan_id)
            self.assertEqual(got_plan.id, plan_id)
            self.assertEqual(got_plan.current_content_version, 2)
            self.assertEqual(got_plan.current_content_id, v2_id)
            self.assertEqual(got_plan.creator_id, _TEACHER_A[0])
            self.assertEqual(got_plan.school_name, plan_school_name)
            self.assertEqual(got_content.id, v2_id)
            self.assertEqual(got_content.version, 2)
            self.assertEqual(got_content.raw_lesson_plan, "重启前教案")
            self.assertEqual(
                got_content.adopted_content,
                {"morning_talk": {"topic": "重启前话题改"}},
            )

            by_date_plan, _ = daily_plan_service.get_by_date(
                db, _CLASS_ID, _PLAN_DAY_1
            )
            self.assertEqual(by_date_plan.id, plan_id)

            sync = daily_plan_service.get_sync_state(
                db, _CLASS_ID, _TERM_ID, 2
            )
            self.assertIsNotNone(sync)
            self.assertEqual(sync.status, "pending_projection")
            self.assertEqual(sync.last_trigger_event, "update")
            self.assertEqual(sync.last_trigger_content_version, 2)
            self.assertEqual(
                sync.current_week_source_manifest,
                [
                    {
                        "daily_plan_id": plan_id,
                        "current_content_id": v2_id,
                        "current_content_version": 2,
                        "date": _PLAN_DAY_1.isoformat(),
                    }
                ],
            )

            # Read path that consumes the persisted I2 calendar; it must
            # stay read-only (no library call, no calendar rewrite).
            summary = daily_plan_service.weekly_sync_summary(db, got_plan)
            self.assertIn(_PLAN_DAY_1.isoformat(), summary["saved_dates"])
        finally:
            db.close()

        post = self._persistent_snapshot(self.engine)
        for key, before in pre.items():
            self.assertEqual(
                before, post.get(key), f"{key} changed across restart"
            )
        started_after = self._plans_started_at()
        self.assertIsNotNone(started_after)
        self.assertEqual(started_after, started_before)

        # A second read round must not recompute or overwrite the I2
        # calendar / plan state either.
        db = RestartSession()
        try:
            daily_plan_service.get_by_date(db, _CLASS_ID, _PLAN_DAY_1)
            again_plan, _ = daily_plan_service.get(db, plan_id)
            daily_plan_service.weekly_sync_summary(db, again_plan)
        finally:
            db.close()
        post_read = self._persistent_snapshot(self.engine)
        self.assertEqual(
            post,
            post_read,
            "reads recomputed or overwrote plan/calendar state after restart",
        )
        self.assertEqual(
            len(post_read["revisions"]), 1, "read must not add a revision"
        )
        states = {row[1]: row[6] for row in post_read["calendar_days"]}
        self.assertEqual(states.get(_NON_TEACHING), "non_teaching")
        self.assertEqual(states.get(_UNKNOWN_DAY), "unknown")
        self.assertEqual(states.get(_PLAN_DAY_1), "teaching")

    # -- concurrency ------------------------------------------------------

    def test_concurrent_create_yields_single_effective_row(self):
        barrier = threading.Barrier(2)
        results: dict[int, tuple] = {}

        def worker(index: int, account: tuple):
            session_factory = get_sessionlocal()
            db = session_factory()
            try:
                barrier.wait(timeout=10)
                plan, _content, created = daily_plan_service.create_or_open(
                    db,
                    _snap(account),
                    plan_date=_PLAN_DAY_1,
                    adopted_content={"reflection": f"writer-{index}"},
                )
                results[index] = ("ok", plan.id, created)
            except Exception as exc:  # noqa: BLE001 - collected for assertion
                results[index] = ("err", type(exc).__name__, str(exc))
            finally:
                db.close()

        threads = [
            threading.Thread(target=worker, args=(0, _TEACHER_A)),
            threading.Thread(target=worker, args=(1, _TEACHER_B)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.assertEqual(len(results), 2)
        for index in (0, 1):
            self.assertEqual(results[index][0], "ok", results[index])
        plan_ids = {results[0][1], results[1][1]}
        self.assertEqual(len(plan_ids), 1)
        created_flags = [results[0][2], results[1][2]]
        self.assertEqual(created_flags.count(True), 1)
        self.assertEqual(self._plan_count(), 1)

        db = self.SessionLocal()
        try:
            plan_id = next(iter(plan_ids))
            _plan, content = daily_plan_service.get(db, plan_id)
            self.assertEqual(content.version, 1)
        finally:
            db.close()
        self.assertIsNotNone(self._plans_started_at())

    # -- spec 8.4: first plan create vs config confirm lock order ----------

    def test_create_commits_school_lock_first_then_config_confirm_rejected(
        self,
    ):
        """Order 1: create wins school_settings; confirm hits the live gate.

        The school_update preview exists BEFORE any plan (no saved
        blockers). The create thread takes the real school_settings row lock
        through daily_plan_service.create_or_open and is paused while
        holding it; the confirm thread runs the real config_service.
        apply_preview concurrently, and its wrapped config_service.
        lock_school must attempt the real ``FOR UPDATE`` lock but not
        return while create still holds the row (attempting observed,
        acquired withheld). After create commits, apply re-reads
        plans_started_at under the locking read and must raise
        DependencyNotReady: the plan, the stage marker survive and the
        configuration change is NOT applied.
        """
        change_id, blockers, plans_started = self._create_school_preview(
            "锁序园名"
        )
        self.assertNotIn("DEPENDENCY_NOT_READY", blockers)
        self.assertFalse(plans_started)

        engine = self.engine
        reached = threading.Event()
        release = threading.Event()
        apply_started = threading.Event()
        attempting = threading.Event()
        acquired = threading.Event()
        results: dict[str, tuple] = {}
        original_create_lock_school = daily_plan_service.lock_school
        original_config_lock_school = config_service.lock_school

        def create_worker():
            db = self._thread_session(engine)
            try:
                def pausing_lock_school(sess):
                    row = original_create_lock_school(sess)
                    reached.set()
                    if not release.wait(timeout=20):
                        raise TimeoutError("release not set within 20s")
                    return row

                with mock.patch.object(
                    daily_plan_service, "lock_school", pausing_lock_school
                ):
                    plan, _content, created = (
                        daily_plan_service.create_or_open(
                            db,
                            _snap(_TEACHER_A),
                            plan_date=_PLAN_DAY_1,
                            adopted_content={"reflection": "create-first"},
                        )
                    )
                results["create"] = ("ok", plan.id, created)
            except Exception as exc:  # noqa: BLE001 - kept as evidence
                results["create"] = ("err", type(exc).__name__, str(exc))
            finally:
                db.close()

        def apply_worker():
            db = self._thread_session(engine)
            try:
                apply_started.set()
                with self._observing_lock_school(
                    config_service,
                    original_config_lock_school,
                    attempting,
                    acquired,
                ):
                    change = config_service.apply_preview(
                        db, _snap(_ADMIN), change_id
                    )
                results["apply"] = ("ok", change.status)
            except config_service.DependencyNotReady as exc:
                results["apply"] = (
                    "rejected",
                    type(exc).__name__,
                    str(exc),
                )
            except Exception as exc:  # noqa: BLE001 - kept as evidence
                results["apply"] = ("err", type(exc).__name__, str(exc))
            finally:
                db.close()

        t_create = threading.Thread(target=create_worker, name="i3-create")
        t_apply = threading.Thread(target=apply_worker, name="i3-apply")
        try:
            t_create.start()
            self.assertTrue(
                reached.wait(timeout=15),
                f"create did not take school_settings lock within 15s; "
                f"attempting={attempting.is_set()}; "
                f"acquired={acquired.is_set()}; results={results}",
            )
            t_apply.start()
            self.assertTrue(
                apply_started.wait(timeout=5),
                f"apply thread did not start within 5s; "
                f"attempting={attempting.is_set()}; "
                f"acquired={acquired.is_set()}; results={results}",
            )
            self.assertTrue(
                attempting.wait(timeout=15),
                f"apply never entered the real lock_school within 15s; "
                f"attempting={attempting.is_set()}; "
                f"acquired={acquired.is_set()}; results={results}",
            )
            self.assertFalse(
                acquired.wait(timeout=2),
                f"apply acquired the school_settings lock while create "
                f"still held it; attempting={attempting.is_set()}; "
                f"acquired={acquired.is_set()}; results={results}",
            )
        finally:
            release.set()
            t_create.join(timeout=30)
            if t_apply.ident is not None:
                t_apply.join(timeout=30)

        self.assertTrue(
            acquired.wait(timeout=15),
            f"apply never acquired the school_settings lock after release; "
            f"attempting={attempting.is_set()}; "
            f"acquired={acquired.is_set()}; results={results}",
        )
        self.assertFalse(
            t_create.is_alive(),
            f"create thread still alive after 30s (deadlock?); "
            f"attempting={attempting.is_set()}; "
            f"acquired={acquired.is_set()}; results={results}",
        )
        if t_apply.ident is not None:
            self.assertFalse(
                t_apply.is_alive(),
                f"apply thread still alive after 30s (deadlock?); "
                f"attempting={attempting.is_set()}; "
                f"acquired={acquired.is_set()}; results={results}",
            )

        self.assertIn("create", results, results)
        self.assertEqual(results["create"][0], "ok", results)
        self.assertTrue(results["create"][2], results)
        self.assertIn("apply", results, results)
        self.assertEqual(results["apply"][0], "rejected", results)
        self.assertEqual(results["apply"][1], "DependencyNotReady", results)

        # Plan and stage marker survive; the config change is not applied.
        self.assertEqual(self._plan_count(), 1)
        self.assertIsNotNone(self._plans_started_at())
        self.assertIsNone(
            self._scalar("SELECT school_name FROM school_settings")
        )
        self.assertEqual(
            int(self._scalar("SELECT version FROM school_settings")), 1
        )
        self.assertEqual(
            self._change_row(change_id), ("pending", False, False)
        )
        school_updates = int(
            self._scalar(
                "SELECT COUNT(*) FROM operation_records "
                "WHERE action = 'school_settings_update'"
            )
            or 0
        )
        self.assertEqual(school_updates, 0)
        create_records = int(
            self._scalar(
                "SELECT COUNT(*) FROM operation_records "
                "WHERE action = 'create_daily_plan'"
            )
            or 0
        )
        self.assertEqual(create_records, 1)

    def test_config_confirm_commits_calendar_first_then_create_rejected(
        self,
    ):
        """Order 2: confirm wins school_settings; create re-verifies calendar.

        The calendar_override preview (plan date -> non_teaching) is applied
        through the real config_service.apply_preview while holding the real
        school_settings row lock; the create thread enters its wrapped
        daily_plan_service.lock_school through create_or_open and must
        attempt the real ``FOR UPDATE`` lock but not return while apply
        still holds the row (attempting observed, acquired withheld).
        After apply commits, create current-reads the committed new
        revision/day under the lock and must reject with
        DATE_NOT_ELIGIBLE (no partial writes, no deadlock).
        """
        change_id, blockers, plans_started = (
            self._create_calendar_override_preview()
        )
        self.assertNotIn("DEPENDENCY_NOT_READY", blockers)
        self.assertFalse(plans_started)

        engine = self.engine
        reached = threading.Event()
        release = threading.Event()
        attempting = threading.Event()
        acquired = threading.Event()
        results: dict[str, tuple] = {}
        original_config_lock_school = config_service.lock_school
        original_create_lock_school = daily_plan_service.lock_school

        def apply_worker():
            db = self._thread_session(engine)
            try:
                def pausing_lock_school(sess):
                    row = original_config_lock_school(sess)
                    reached.set()
                    if not release.wait(timeout=20):
                        raise TimeoutError("release not set within 20s")
                    return row

                with mock.patch.object(
                    config_service, "lock_school", pausing_lock_school
                ):
                    change = config_service.apply_preview(
                        db, _snap(_ADMIN), change_id
                    )
                results["apply"] = ("ok", change.status)
            except Exception as exc:  # noqa: BLE001 - kept as evidence
                results["apply"] = ("err", type(exc).__name__, str(exc))
            finally:
                db.close()

        def create_worker():
            db = self._thread_session(engine)
            try:
                with self._observing_lock_school(
                    daily_plan_service,
                    original_create_lock_school,
                    attempting,
                    acquired,
                ):
                    plan, _content, created = (
                        daily_plan_service.create_or_open(
                            db,
                            _snap(_TEACHER_A),
                            plan_date=_PLAN_DAY_1,
                            adopted_content={"reflection": "confirm-first"},
                        )
                    )
                results["create"] = ("ok", plan.id, created)
            except daily_plan_service.DailyPlanDateNotEligible as exc:
                results["create"] = (
                    "rejected",
                    type(exc).__name__,
                    str(exc),
                )
            except Exception as exc:  # noqa: BLE001 - kept as evidence
                results["create"] = ("err", type(exc).__name__, str(exc))
            finally:
                db.close()

        t_apply = threading.Thread(target=apply_worker, name="i3-apply")
        t_create = threading.Thread(target=create_worker, name="i3-create")
        try:
            t_apply.start()
            self.assertTrue(
                reached.wait(timeout=15),
                f"apply did not take school_settings lock within 15s; "
                f"attempting={attempting.is_set()}; "
                f"acquired={acquired.is_set()}; results={results}",
            )
            t_create.start()
            self.assertTrue(
                attempting.wait(timeout=15),
                f"create never entered the real lock_school within 15s; "
                f"attempting={attempting.is_set()}; "
                f"acquired={acquired.is_set()}; results={results}",
            )
            self.assertFalse(
                acquired.wait(timeout=2),
                f"create acquired the school_settings lock while apply "
                f"still held it; attempting={attempting.is_set()}; "
                f"acquired={acquired.is_set()}; results={results}",
            )
        finally:
            release.set()
            t_apply.join(timeout=30)
            t_create.join(timeout=30)

        self.assertTrue(
            acquired.wait(timeout=15),
            f"create never acquired the school_settings lock after release; "
            f"attempting={attempting.is_set()}; "
            f"acquired={acquired.is_set()}; results={results}",
        )
        self.assertFalse(
            t_apply.is_alive(),
            f"apply thread still alive after 30s (deadlock?); "
            f"attempting={attempting.is_set()}; "
            f"acquired={acquired.is_set()}; results={results}",
        )
        self.assertFalse(
            t_create.is_alive(),
            f"create thread still alive after 30s (deadlock?); "
            f"attempting={attempting.is_set()}; "
            f"acquired={acquired.is_set()}; results={results}",
        )

        self.assertIn("apply", results, results)
        self.assertEqual(results["apply"][0], "ok", results)
        self.assertEqual(results["apply"][1], "applied", results)
        self.assertIn("create", results, results)
        self.assertEqual(results["create"][0], "rejected", results)
        self.assertEqual(
            results["create"][1], "DailyPlanDateNotEligible", results
        )
        self.assertEqual(results["create"][2], "DATE_NOT_ELIGIBLE", results)

        # The confirm committed fully; create left no partial writes.
        self.assertEqual(
            self._change_row(change_id), ("applied", True, True)
        )
        self.assertEqual(self._plan_count(), 0)
        self.assertIsNone(self._plans_started_at())
        self.assertEqual(
            int(
                self._scalar(
                    "SELECT COUNT(*) FROM daily_plan_contents"
                )
                or 0
            ),
            0,
        )
        self.assertEqual(
            int(
                self._scalar(
                    "SELECT COUNT(*) FROM weekly_plan_sync_states"
                )
                or 0
            ),
            0,
        )
        create_records = int(
            self._scalar(
                "SELECT COUNT(*) FROM operation_records "
                "WHERE action = 'create_daily_plan'"
            )
            or 0
        )
        self.assertEqual(create_records, 0)
        override_records = int(
            self._scalar(
                "SELECT COUNT(*) FROM operation_records "
                "WHERE action = 'calendar_override'"
            )
            or 0
        )
        self.assertEqual(override_records, 1)

        with self.engine.connect() as conn:
            revision_count = conn.execute(
                text("SELECT COUNT(*) FROM calendar_revisions")
            ).scalar()
            term_version, new_revision_id = conn.execute(
                text(
                    "SELECT version, current_calendar_revision_id "
                    "FROM terms WHERE id = :id"
                ),
                {"id": _TERM_ID},
            ).one()
            schedule_version = conn.execute(
                text("SELECT schedule_version FROM school_settings")
            ).scalar()
            day = conn.execute(
                text(
                    "SELECT override_state, effective_state, override_reason "
                    "FROM calendar_days "
                    "WHERE revision_id = :rev AND date = :day"
                ),
                {"rev": new_revision_id, "day": _PLAN_DAY_1},
            ).one()
        self.assertEqual(int(revision_count), 2)
        self.assertEqual(int(term_version), 2)
        self.assertNotEqual(new_revision_id, _REVISION_ID)
        self.assertEqual(int(schedule_version), 2)
        self.assertEqual(tuple(day), ("non_teaching", "non_teaching", "锁序验证"))


@skip_unless_enabled
class DailyPlanSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = make_engine()
        require_authorized_url(str(cls.engine.url))
        check_environment(cls.engine)
        ensure_schema(cls.engine)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def test_generated_column_and_unique_index_exist(self):
        with self.engine.connect() as conn:
            expr = conn.execute(
                text(
                    "SELECT generation_expression FROM information_schema.columns "
                    "WHERE table_schema = DATABASE() AND table_name = 'daily_plans' "
                    "AND column_name = 'effective_date'"
                )
            ).scalar()
            index_rows = conn.execute(
                text(
                    "SELECT column_name FROM information_schema.statistics "
                    "WHERE table_schema = DATABASE() AND table_name = 'daily_plans' "
                    "AND index_name = 'uq_daily_plans_class_effective_date' "
                    "ORDER BY seq_in_index"
                )
            ).fetchall()
        self.assertIsNotNone(expr)
        self.assertIn("deleted_at", expr)
        self.assertIn("plan_date", expr)
        self.assertEqual([row[0] for row in index_rows], ["class_id", "effective_date"])

    def test_composite_pointer_foreign_key_exists(self):
        with self.engine.connect() as conn:
            fk = conn.execute(
                text(
                    "SELECT constraint_name FROM information_schema.table_constraints "
                    "WHERE table_schema = DATABASE() AND table_name = 'daily_plans' "
                    "AND constraint_name = 'fk_daily_plans_current_content' "
                    "AND constraint_type = 'FOREIGN KEY'"
                )
            ).scalar()
        self.assertEqual(fk, "fk_daily_plans_current_content")

    def test_operation_record_check_allows_daily_plan(self):
        with self.engine.connect() as conn:
            clause = conn.execute(
                text(
                    "SELECT cc.check_clause "
                    "FROM information_schema.check_constraints cc "
                    "JOIN information_schema.table_constraints tc "
                    "ON cc.constraint_schema = tc.constraint_schema "
                    "AND cc.constraint_name = tc.constraint_name "
                    "WHERE tc.table_schema = DATABASE() "
                    "AND tc.table_name = 'operation_records' "
                    "AND tc.constraint_name = 'ck_operation_record_target_type'"
                )
            ).scalar()
        self.assertIsNotNone(clause)
        self.assertIn("daily_plan", clause)

    def test_weekly_sync_has_unique_key_and_no_weekly_plan_fk(self):
        with self.engine.connect() as conn:
            unique_cols = conn.execute(
                text(
                    "SELECT column_name FROM information_schema.statistics "
                    "WHERE table_schema = DATABASE() "
                    "AND table_name = 'weekly_plan_sync_states' "
                    "AND index_name = 'uq_weekly_plan_sync_states_class_term_week' "
                    "ORDER BY seq_in_index"
                )
            ).fetchall()
            weekly_refs = conn.execute(
                text(
                    "SELECT referenced_table_name "
                    "FROM information_schema.key_column_usage "
                    "WHERE table_schema = DATABASE() "
                    "AND table_name = 'weekly_plan_sync_states' "
                    "AND referenced_table_name IS NOT NULL"
                )
            ).fetchall()
        self.assertEqual(
            [row[0] for row in unique_cols],
            ["class_id", "term_id", "week_number"],
        )
        referenced = {row[0] for row in weekly_refs}
        self.assertIn("classes", referenced)
        self.assertIn("terms", referenced)
        self.assertIn("daily_plans", referenced)
        self.assertNotIn("weekly_plans", referenced)


if __name__ == "__main__":
    unittest.main()
