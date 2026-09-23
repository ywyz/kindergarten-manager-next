"""No-DB mock tests for the I4 weekly plan service transaction core.

Covers lock-chain order, permission branches, version/ack conflicts,
rollback-on-any-failure, unique-conflict reopen, header deep copy and the
sources/sync locking-read contract. No database, no SQLite, no HTTP.
"""

import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest import mock

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Account,
    CalendarDay,
    CalendarRevision,
    DailyPlan,
    DailyPlanContent,
    TeacherAssignment,
    Term,
    WeeklyPlan,
    WeeklyPlanContent,
    WeeklyPlanConfirmedContent,
    WeeklyPlanSyncState,
)
from app.services import auth_service, weekly_plan_content, weekly_plan_service
from app.services.auth_service import AuthSnapshot
from app.services.weekly_plan_service import (
    WeeklyPlanConfirmAckRequired,
    WeeklyPlanForbidden,
    WeeklyPlanServiceError,
    WeeklyPlanValidationError,
    WeeklyPlanVersionConflict,
    _HeaderIdentity,
    create_or_open_weekly_plan,
    confirm_weekly_plan,
    is_weekly_effective_unique_violation,
    refresh_weekly_sources,
    save_weekly_plan,
)


def _snapshot(role: str, *, account_id: str = "tch1") -> AuthSnapshot:
    return AuthSnapshot(
        account_id=account_id,
        role=role,
        auth_version=1,
        session_id="ses1",
        is_active=True,
        password_hash="x",
    )


def _account(role: str, *, account_id: str = "tch1") -> Account:
    return Account(
        id=account_id,
        username="user1",
        password_hash="x",
        display_name=None,
        role=role,
        is_active=True,
        version=1,
        auth_version=1,
    )


def _orm(cls):
    return cls()


def _term(*, revision_id: str | None = "rev1") -> Term:
    term = _orm(Term)
    term.id = "ter1"
    term.name = "秋"
    term.start_date = date(2026, 9, 1)
    term.end_date = date(2026, 9, 28)
    term.current_calendar_revision_id = revision_id
    return term


def _header(plan_id: str = "wp1", **kw) -> _HeaderIdentity:
    base = dict(
        plan_id=plan_id, class_id="cls1", term_id="ter1", week_number=1
    )
    base.update(kw)
    return _HeaderIdentity(**base)


def _plan(*, owner_id: str = "tch1", class_id: str = "cls1") -> WeeklyPlan:
    plan = _orm(WeeklyPlan)
    plan.id = "wp1"
    plan.class_id = class_id
    plan.term_id = "ter1"
    plan.week_number = 1
    plan.owner_id = owner_id
    plan.creator_id = "tch0"
    plan.current_draft_content_id = "c1"
    plan.current_draft_version = 1
    plan.current_confirmed_content_id = None
    plan.current_confirmed_content_version = None
    plan.deleted_at = None
    return plan


def _draft(version: int = 1) -> WeeklyPlanContent:
    row = _orm(WeeklyPlanContent)
    row.id = f"c{version}"
    row.weekly_plan_id = "wp1"
    row.version = version
    row.content = {"theme": "x", "_audit": {"action": "save"}}
    row.editor_id = "tch1"
    row.editor_role = "owner"
    return row


def _assignment(class_id: str = "cls1") -> TeacherAssignment:
    row = _orm(TeacherAssignment)
    row.teacher_id = "tch1"
    row.class_id = class_id
    return row


def _sync_row(updated_at=None) -> WeeklyPlanSyncState:
    row = _orm(WeeklyPlanSyncState)
    row.id = "sy1"
    row.class_id = "cls1"
    row.term_id = "ter1"
    row.week_number = 1
    row.status = "pending_projection"
    row.updated_at = updated_at or datetime(2026, 9, 20, 12, 0, 0)
    return row


def _daily_plan() -> DailyPlan:
    row = _orm(DailyPlan)
    row.id = "d1"
    row.class_id = "cls1"
    row.term_id = "ter1"
    row.week_number = 1
    row.plan_date = date(2026, 9, 7)
    row.current_content_id = "dc1"
    row.current_content_version = 2
    row.deleted_at = None
    return row


def _daily_content() -> DailyPlanContent:
    row = _orm(DailyPlanContent)
    row.id = "dc1"
    row.daily_plan_id = "d1"
    row.version = 2
    row.adopted_content = {"morning_talk": {"topic": "t"}}
    return row


def _school_class() -> SimpleNamespace:
    return SimpleNamespace(
        name="中一",
        grade="中班",
        header_teacher_names=["张三", {"raw": ["李四"]}],
        caregiver_name="王五",
    )


class _StubSession:
    """Minimal Session stand-in: scalars/execute/get/tx bookkeeping."""

    def __init__(self):
        self.events: list[tuple] = []
        self.added: list = []
        self._tx = False
        self.scalars_map: dict[str, list] = {}
        self.execute_map: dict[str, object] = {}
        self.get_map: dict[tuple, object] = {}
        self.commit_error: Exception | None = None
        self.flush_error: Exception | None = None

    def in_transaction(self) -> bool:
        return self._tx

    def begin(self) -> None:
        self._tx = True
        self.events.append(("begin",))

    def rollback(self) -> None:
        self._tx = False
        self.events.append(("rollback",))

    def commit(self) -> None:
        if self.commit_error is not None:
            raise self.commit_error
        self._tx = False
        self.events.append(("commit",))

    def flush(self) -> None:
        if self.flush_error is not None:
            raise self.flush_error
        self.events.append(("flush",))

    def add(self, obj) -> None:
        self.added.append(obj)

    def get(self, entity, key):
        self.events.append(("get", getattr(entity, "__name__", str(entity)), key))
        return self.get_map.get((getattr(entity, "__name__", str(entity)), key))

    def scalars(self, stmt):
        label = type(stmt).__name__
        # Resolve by entity table name for model selects.
        try:
            entities = stmt.column_descriptions
            label = entities[0]["type"].__name__ if entities else label
        except Exception:
            pass
        result = SimpleNamespace()
        rows = self.scalars_map.get(label, [])
        for i, row in enumerate(rows):
            # apply_for_each not used; expose all() directly below
            pass
        result.all = lambda: list(self.scalars_map.get(label, []))
        self.events.append(("scalars", label, _stmt_flags(stmt)))
        return result

    def execute(self, stmt):
        try:
            entities = getattr(stmt, "column_descriptions", None)
            if entities:
                label = entities[0]["type"].__name__
            else:
                # Multi-column scalar pre-read (WeeklyPlan.id, ...)
                label = "HeaderRow"
        except Exception:
            label = "HeaderRow"
        self.events.append(("execute", label, _stmt_flags(stmt)))
        if label == "HeaderRow":
            row = self.execute_map.get("HeaderRow")
            result = SimpleNamespace()
            result.one_or_none = lambda: row
            return result
        value = self.execute_map.get(label, None)
        if value is _MISSING:
            value = None
        result = SimpleNamespace()
        result.scalar_one_or_none = lambda: value
        return result

    def __getattr__(self, name):
        raise AttributeError(name)


_MISS_INNER = object()
_MISSING = object()


def _stmt_flags(stmt) -> tuple[bool, bool]:
    """(for_update, populate_existing) best-effort from a Select/ClauseElement."""
    for_update = False
    populate = False
    try:
        if getattr(stmt, "_for_update_arg", None) is not None:
            for_update = True
    except Exception:
        pass
    opts = getattr(stmt, "_execution_options", None) or {}
    if opts.get("populate_existing"):
        populate = True
    return for_update, populate


def _labels_for(entity) -> str:
    return entity.__name__


class CreatePermissionTests(unittest.TestCase):
    def test_admin_create_forbidden(self):
        with self.assertRaises(WeeklyPlanForbidden) as ctx:
            create_or_open_weekly_plan(
                mock.MagicMock(),
                _snapshot("admin", account_id="adm1"),
                term_id="ter1",
                week_number=1,
            )
        self.assertEqual(ctx.exception.code, "FORBIDDEN")

    def test_teacher_class_id_rejected(self):
        with self.assertRaises(WeeklyPlanValidationError) as ctx:
            create_or_open_weekly_plan(
                mock.MagicMock(),
                _snapshot("teacher"),
                term_id="ter1",
                week_number=1,
                class_id="cls9",
            )
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_unassigned_teacher_forbidden_in_locked_prefix(self):
        db = mock.MagicMock()
        db.in_transaction.return_value = False
        with mock.patch.object(
            weekly_plan_service, "_lock_operator", return_value=_account("teacher")
        ), mock.patch.object(
            weekly_plan_service,
            "_resolve_create_class",
            side_effect=WeeklyPlanForbidden(),
        ):
            with self.assertRaises(WeeklyPlanForbidden):
                create_or_open_weekly_plan(
                    db, _snapshot("teacher"), term_id="ter1", week_number=1
                )
        db.rollback.assert_called()


class OpenExistingCreateTests(unittest.TestCase):
    def _run(self, owner="tch0", account_id="tch1"):
        plan = _plan(owner_id=owner)
        draft = _draft(1)
        confirmed = None
        db = mock.MagicMock()
        db.in_transaction.return_value = False

        def fake_get(entity, key):
            name = getattr(entity, "__name__", "")
            if name == "WeeklyPlanConfirmedContent":
                return None
            if name == "WeeklyPlanContent":
                return draft
            if name == "WeeklyPlan":
                return plan if key == plan.id else None
            if name == "TeacherAssignment":
                return _assignment()
            return None

        db.get.side_effect = fake_get
        events = []

        with mock.patch.object(
            weekly_plan_service, "_lock_operator", return_value=_account("teacher")
        ), mock.patch.object(
            weekly_plan_service,
            "_resolve_create_class",
            return_value="cls1",
        ), mock.patch.object(
            weekly_plan_service, "lock_school", return_value=SimpleNamespace()
        ), mock.patch.object(
            weekly_plan_service,
            "lock_class",
            return_value=SimpleNamespace(
                name="中一",
                grade="中班",
                header_teacher_names=["张"],
                caregiver_name=None,
            ),
        ), mock.patch.object(
            weekly_plan_service, "_require_term", return_value=_term()
        ), mock.patch.object(
            weekly_plan_service,
            "_load_week_days",
            side_effect=lambda *a, **k: events.append("days") or {},
        ), mock.patch.object(
            weekly_plan_service,
            "_find_effective_weekly",
            return_value=plan,
        ), mock.patch.object(
            weekly_plan_service,
            "_lock_draft",
            return_value=draft,
        ), mock.patch.object(
            weekly_plan_service, "_lock_confirmed_pointer"
        ), mock.patch.object(
            weekly_plan_service,
            "_load_confirmed_unlocked",
            return_value=confirmed,
        ), mock.patch.object(
            weekly_plan_service,
            "weekly_plan_content",
            mock.MagicMock(
                ContentValidationError=weekly_plan_content.ContentValidationError,
            ),
        ) as content_mod:
            content_mod.new_content.return_value = {"theme": "x"}
            with mock.patch.object(
                weekly_plan_service.security, "generate_id", return_value="nid"
            ), mock.patch.object(
                weekly_plan_service.auth_service,
                "utc_now",
                return_value=datetime(2026, 9, 21, 0, 0, 0),
            ), mock.patch.object(
                weekly_plan_service.auth_service, "record_operation"
            ) as rec:
                result = create_or_open_weekly_plan(
                    db,
                    _snapshot("teacher", account_id=account_id),
                    term_id="ter1",
                    week_number=1,
                    theme="秋",
                )
        self.assertFalse(result.created)
        self.assertIs(result.plan, plan)
        self.assertIs(result.draft, draft)
        self.assertIs(result.confirmed, confirmed)
        db.commit.assert_called_once()
        self.assertEqual(events, ["days"])
        rec.assert_not_called()
        return result, db

    def test_existing_open_keeps_owner(self):
        plan = _plan(owner_id="tch0")
        self._run(owner="tch0", account_id="tch1")

    def test_create_success_builds_snapshot_and_pointer(self):
        plan = _plan()
        draft = _draft(1)
        db = mock.MagicMock()
        db.in_transaction.return_value = False
        school = SimpleNamespace(school_name="园")
        school_class = _school_class()

        def fake_get(entity, key):
            name = getattr(entity, "__name__", "")
            if name == "WeeklyPlanConfirmedContent":
                return None
            if name == "TeacherAssignment":
                return _assignment()
            return None

        db.get.side_effect = fake_get

        with mock.patch.object(
            weekly_plan_service, "_lock_operator", return_value=_account("teacher")
        ), mock.patch.object(
            weekly_plan_service, "_resolve_create_class", return_value="cls1"
        ), mock.patch.object(
            weekly_plan_service, "lock_school", return_value=school
        ), mock.patch.object(
            weekly_plan_service, "lock_class", return_value=school_class
        ), mock.patch.object(
            weekly_plan_service, "_require_term", return_value=_term()
        ), mock.patch.object(
            weekly_plan_service, "_load_week_days", return_value={}
        ), mock.patch.object(
            weekly_plan_service,
            "_find_effective_weekly",
            return_value=None,
        ), mock.patch.object(
            weekly_plan_service,
            "_load_week_sources_by_key",
            return_value=([], datetime(2026, 9, 20, 12, 0, 0)),
        ), mock.patch.object(
            weekly_plan_service,
            "weekly_plan_content",
            mock.MagicMock(
                new_content=mock.MagicMock(return_value={"theme": ""}),
                ContentValidationError=weekly_plan_content.ContentValidationError,
            ),
        ), mock.patch.object(
            weekly_plan_service.security, "generate_id", return_value="nid"
        ), mock.patch.object(
            weekly_plan_service.auth_service,
            "utc_now",
            return_value=datetime(2026, 9, 21, 0, 0, 0),
        ), mock.patch.object(
            weekly_plan_service.auth_service, "record_operation"
        ) as rec:
            result = create_or_open_weekly_plan(
                db,
                _snapshot("teacher"),
                term_id="ter1",
                week_number=1,
                theme="主题",
            )
        self.assertTrue(result.created)
        plan_row = result.plan
        self.assertEqual(plan_row.owner_id, "tch1")
        self.assertEqual(plan_row.creator_id, "tch1")
        self.assertIsNot(
            plan_row.header_teacher_names, school_class.header_teacher_names
        )
        # Nested dict inside JSON list must be deep-copied (fix D).
        self.assertEqual(
            plan_row.header_teacher_names[1], {"raw": ["李四"]}
        )
        plan_row.header_teacher_names[1]["raw"].append("mutated")
        self.assertEqual(
            school_class.header_teacher_names[1], {"raw": ["李四"]}
        )
        self.assertEqual(plan_row.current_draft_version, 1)
        self.assertEqual(plan_row.current_draft_content_id, "nid")
        rec.assert_called_once()
        self.assertEqual(rec.call_args.kwargs["action"], "create_weekly_plan")
        db.commit.assert_called_once()


class LockPrefixPermissionTests(unittest.TestCase):
    def test_teacher_class_id_rejected(self):
        db = mock.MagicMock()
        with mock.patch.object(
            weekly_plan_service, "_lock_operator", return_value=_account("teacher")
        ):
            with self.assertRaises(WeeklyPlanValidationError):
                weekly_plan_service._lock_write_prefix(
                    db, _snapshot("teacher"), _header(), "cls9"
                )

    def test_teacher_missing_assignment_forbidden(self):
        db = mock.MagicMock()
        with mock.patch.object(
            weekly_plan_service, "_lock_operator", return_value=_account("teacher")
        ), mock.patch.object(
            weekly_plan_service, "_lock_teacher_assignment", return_value=None
        ), mock.patch.object(weekly_plan_service, "lock_school") as school:
            with self.assertRaises(WeeklyPlanForbidden):
                weekly_plan_service._lock_write_prefix(
                    db, _snapshot("teacher"), _header(), None
                )
            school.assert_not_called()

    def test_teacher_assignment_class_mismatch_forbidden(self):
        db = mock.MagicMock()
        with mock.patch.object(
            weekly_plan_service, "_lock_operator", return_value=_account("teacher")
        ), mock.patch.object(
            weekly_plan_service,
            "_lock_teacher_assignment",
            return_value=_assignment("cls9"),
        ):
            with self.assertRaises(WeeklyPlanForbidden):
                weekly_plan_service._lock_write_prefix(
                    db, _snapshot("teacher"), _header(), None
                )

    def test_admin_requires_explicit_matching_class(self):
        db = mock.MagicMock()
        with mock.patch.object(
            weekly_plan_service, "_lock_operator", return_value=_account("admin", account_id="adm1")
        ):
            with self.assertRaises(WeeklyPlanValidationError):
                weekly_plan_service._lock_write_prefix(
                    db, _snapshot("admin", account_id="adm1"), _header(), None
                )
        with mock.patch.object(
            weekly_plan_service, "_lock_operator", return_value=_account("admin", account_id="adm1")
        ):
            with self.assertRaises(weekly_plan_service.WeeklyPlanNotFound) as ctx:
                weekly_plan_service._lock_write_prefix(
                    db, _snapshot("admin", account_id="adm1"), _header(), "cls9"
                )
        self.assertEqual(ctx.exception.code, "WEEKLY_PLAN_NOT_FOUND")

    def test_admin_explicit_match_locks_school_class_term(self):
        db = mock.MagicMock()
        term = _term()
        with mock.patch.object(
            weekly_plan_service, "_lock_operator", return_value=_account("admin", account_id="adm1")
        ), mock.patch.object(weekly_plan_service, "lock_school") as school, mock.patch.object(
            weekly_plan_service, "lock_class"
        ) as klass, mock.patch.object(
            weekly_plan_service, "lock_term", return_value=term
        ):
            out_term, out_class = weekly_plan_service._lock_write_prefix(
                db, _snapshot("admin", account_id="adm1"), _header(), "cls1"
            )
        self.assertIs(out_term, term)
        self.assertEqual(out_class, "cls1")
        school.assert_called_once()
        klass.assert_called_once_with(db, "cls1")


class SavePermissionAndVersionTests(unittest.TestCase):
    def _prefix(self, role: str, account_id: str = "tch1"):
        return mock.patch.multiple(
            weekly_plan_service,
        )

    def _base_patches(self, *, owner_id="tch1", role="teacher", account_id="tch1", version=1):
        plan = _plan(owner_id=owner_id)
        draft = _draft(version)
        plan.current_draft_version = version
        plan.current_draft_content_id = draft.id
        stack = [
            mock.patch.object(weekly_plan_service, "_preload_header", return_value=_header()),
            mock.patch.object(
                weekly_plan_service,
                "_lock_write_prefix",
                return_value=(_term(), "cls1"),
            ),
            mock.patch.object(
                weekly_plan_service, "_lock_weekly_plan", return_value=plan
            ),
            mock.patch.object(weekly_plan_service, "_assert_identity"),
            mock.patch.object(
                weekly_plan_service, "_load_week_days", return_value={}
            ),
            mock.patch.object(
                weekly_plan_service,
                "_load_week_sources",
                return_value=([], datetime(2026, 9, 20, 12, 0, 0)),
            ),
            mock.patch.object(
                weekly_plan_service, "_lock_draft", return_value=draft
            ),
            mock.patch.object(weekly_plan_service, "_lock_confirmed_pointer"),
            mock.patch.object(
                weekly_plan_service, "_load_confirmed_unlocked", return_value=None
            ),
            mock.patch.object(
                weekly_plan_service.auth_service, "record_operation"
            ),
            mock.patch.object(
                weekly_plan_service.security, "generate_id", return_value="n2"
            ),
            mock.patch.object(
                weekly_plan_service.auth_service,
                "utc_now",
                return_value=datetime(2026, 9, 21, 0, 0, 0),
            ),
            mock.patch.object(
                weekly_plan_service,
                "weekly_plan_content",
                mock.MagicMock(
                    prepare_patch=mock.MagicMock(return_value={"theme": "y"}),
                    ContentValidationError=weekly_plan_content.ContentValidationError,
                ),
            ),
        ]
        return plan, draft, stack

    def test_non_owner_same_class_save_forbidden(self):
        plan, _draft_row, stack = self._base_patches(owner_id="owner9")
        with stack[0], stack[1], stack[2], stack[3], stack[4], stack[5], stack[6], stack[7]:
            with self.assertRaises(WeeklyPlanForbidden) as ctx:
                save_weekly_plan(
                    mock.MagicMock(in_transaction=lambda: True),
                    _snapshot("teacher"),
                    plan_id="wp1",
                    expected_draft_version=1,
                    patch={"theme": "x"},
                )
        self.assertEqual(ctx.exception.code, "FORBIDDEN")

    def test_owner_save_appends_version_pointer_and_audit(self):
        plan, draft_row, stack = self._base_patches(owner_id="tch1")
        db = mock.MagicMock()
        db.in_transaction.return_value = True
        # db.get for confirmed pointer: None
        db.get.return_value = None
        with stack[0], stack[1], stack[2], stack[3], stack[4], stack[5], stack[6], stack[7], stack[8], stack[9] as record_operation_mock, stack[10], stack[11], stack[12]:
            result = save_weekly_plan(
                db,
                _snapshot("teacher"),
                plan_id="wp1",
                expected_draft_version=1,
                patch={"theme": "y"},
            )
        self.assertEqual(result.draft.version, 2)
        self.assertEqual(plan.current_draft_version, 2)
        self.assertEqual(plan.current_draft_content_id, "n2")
        self.assertIn("_audit", result.draft.content)
        record_operation_mock.assert_called_once()
        self.assertEqual(
            record_operation_mock.call_args.kwargs["action"], "save_weekly_plan"
        )
        db.commit.assert_called_once()

    def test_admin_save_forbidden_without_class_id(self):
        with mock.patch.object(
            weekly_plan_service, "_preload_header", return_value=_header()
        ), mock.patch.object(
            weekly_plan_service, "_lock_operator", return_value=_account("admin", account_id="adm1")
        ):
            with self.assertRaises(WeeklyPlanValidationError):
                save_weekly_plan(
                    mock.MagicMock(in_transaction=lambda: True),
                    _snapshot("admin", account_id="adm1"),
                    plan_id="wp1",
                    expected_draft_version=1,
                    patch={},
                    class_id=None,
                )

    def test_version_conflict(self):
        plan, draft_row, stack = self._base_patches(version=3)
        db = mock.MagicMock()
        db.in_transaction.return_value = True
        db.get.return_value = None
        with stack[0], stack[1], stack[2], stack[3], stack[4], stack[5], stack[6], stack[7]:
            with self.assertRaises(WeeklyPlanVersionConflict) as ctx:
                save_weekly_plan(
                    db,
                    _snapshot("teacher"),
                    plan_id="wp1",
                    expected_draft_version=1,
                    patch={},
                )
        self.assertEqual(ctx.exception.code, "VERSION_CONFLICT")
        db.rollback.assert_called()


class SaveLockOrderTests(unittest.TestCase):
    def test_days_before_weekly_before_sources(self):
        plan = _plan()
        draft_row = _draft(1)
        header = _header()
        term = _term()
        events: list[str] = []
        db = mock.MagicMock()
        db.in_transaction.return_value = True
        db.get.return_value = None

        with mock.patch.object(
            weekly_plan_service, "_preload_header", return_value=header
        ), mock.patch.object(
            weekly_plan_service,
            "_lock_write_prefix",
            return_value=(term, "cls1"),
        ), mock.patch.object(
            weekly_plan_service, "_validate_week_in_term",
            side_effect=lambda *a: events.append("week_validate"),
        ), mock.patch.object(
            weekly_plan_service,
            "_lock_weekly_plan",
            side_effect=lambda *a: events.append("weekly_lock") or plan,
        ), mock.patch.object(
            weekly_plan_service, "_assert_identity"
        ), mock.patch.object(
            weekly_plan_service,
            "_load_week_days",
            side_effect=lambda *a: events.append("days") or {},
        ), mock.patch.object(
            weekly_plan_service,
            "_load_week_sources",
            side_effect=lambda *a: events.append("sources")
            or ([], datetime(2026, 9, 20, 12, 0, 0)),
        ), mock.patch.object(
            weekly_plan_service, "_lock_draft",
            side_effect=lambda *a: events.append("draft_lock") or draft_row,
        ), mock.patch.object(
            weekly_plan_service,
            "_load_confirmed_unlocked", return_value=None
        ), mock.patch.object(
            weekly_plan_service, "_assert_pointer_complete"
        ), mock.patch.object(
            weekly_plan_service.auth_service, "record_operation"
        ), mock.patch.object(
            weekly_plan_service.security, "generate_id", return_value="n3"
        ), mock.patch.object(
            weekly_plan_service.auth_service,
            "utc_now",
            return_value=datetime(2026, 9, 21, 0, 0, 0),
        ), mock.patch.object(
            weekly_plan_service,
            "weekly_plan_content",
            mock.MagicMock(
                prepare_patch=mock.MagicMock(return_value={"theme": ""}),
                ContentValidationError=weekly_plan_content.ContentValidationError,
            ),
        ):
            save_weekly_plan(
                db,
                _snapshot("teacher"),
                plan_id="wp1",
                expected_draft_version=1,
                patch={},
            )
        self.assertEqual(
            events,
            [
                "week_validate",
                "days",
                "weekly_lock",
                "draft_lock",
                "sources",
            ],
        )


class RefreshPermissionTests(unittest.TestCase):
    def test_non_owner_refresh_forbidden(self):
        plan = _plan(owner_id="owner9")
        draft_row = _draft(1)
        db = mock.MagicMock()
        db.in_transaction.return_value = True
        with mock.patch.object(
            weekly_plan_service, "_preload_header", return_value=_header()
        ), mock.patch.object(
            weekly_plan_service,
            "_lock_write_prefix",
            return_value=(_term(), "cls1"),
        ), mock.patch.object(
            weekly_plan_service, "_lock_weekly_plan", return_value=plan
        ), mock.patch.object(weekly_plan_service, "_assert_identity"), mock.patch.object(
            weekly_plan_service, "_load_week_days", return_value={}
        ), mock.patch.object(
            weekly_plan_service,
            "_load_week_sources",
            return_value=([], datetime(2026, 9, 20)),
        ), mock.patch.object(
            weekly_plan_service, "_lock_draft", return_value=draft_row
        ), mock.patch.object(weekly_plan_service, "_lock_confirmed_pointer"):
            with self.assertRaises(WeeklyPlanForbidden):
                refresh_weekly_sources(
                    db,
                    _snapshot("teacher"),
                    plan_id="wp1",
                    expected_draft_version=1,
                )
        db.rollback.assert_called()


class ConfirmPermissionAndAckTests(unittest.TestCase):
    def _confirm(self, db, snapshot, **kw):
        defaults = dict(
            plan_id="wp1",
            expected_draft_version=1,
            acknowledge_missing=True,
            acknowledge_stale=True,
        )
        defaults.update(kw)
        return confirm_weekly_plan(db, snapshot, **defaults)

    def test_admin_confirm_forbidden(self):
        with self.assertRaises(WeeklyPlanForbidden) as ctx:
            self._confirm(
                mock.MagicMock(in_transaction=lambda: True),
                _snapshot("admin", account_id="adm1"),
            )
        self.assertEqual(ctx.exception.code, "FORBIDDEN")

    def test_non_owner_confirm_forbidden(self):
        plan = _plan(owner_id="owner9")
        db = mock.MagicMock()
        db.in_transaction.return_value = True
        with mock.patch.object(
            weekly_plan_service, "_preload_header", return_value=_header()
        ), mock.patch.object(
            weekly_plan_service,
            "_lock_write_prefix",
            return_value=(_term(), "cls1"),
        ), mock.patch.object(
            weekly_plan_service, "_lock_weekly_plan", return_value=plan
        ), mock.patch.object(weekly_plan_service, "_assert_identity"), mock.patch.object(
            weekly_plan_service, "_load_week_days", return_value={}
        ):
            with self.assertRaises(WeeklyPlanForbidden):
                self._confirm(db, _snapshot("teacher"))
        db.rollback.assert_called()

    def test_ack_required_missing_and_stale(self):
        plan = _plan(owner_id="tch1")
        draft_row = _draft(1)
        db = mock.MagicMock()
        db.in_transaction.return_value = True
        facts = {
            "missing": [{"kind": "empty_theme"}],
            "stale_sources": [{"slot": "collective_1"}],
        }
        with mock.patch.object(
            weekly_plan_service, "_preload_header", return_value=_header()
        ), mock.patch.object(
            weekly_plan_service,
            "_lock_write_prefix",
            return_value=(_term(), "cls1"),
        ), mock.patch.object(
            weekly_plan_service, "_lock_weekly_plan", return_value=plan
        ), mock.patch.object(weekly_plan_service, "_assert_identity"), mock.patch.object(
            weekly_plan_service, "_load_week_days", return_value={}
        ), mock.patch.object(
            weekly_plan_service,
            "_load_week_sources",
            return_value=([], datetime(2026, 9, 20)),
        ), mock.patch.object(
            weekly_plan_service, "_lock_draft", return_value=draft_row
        ), mock.patch.object(weekly_plan_service, "_lock_confirmed_pointer"), mock.patch.object(
            weekly_plan_service,
            "weekly_plan_content",
            mock.MagicMock(
                build_facts=mock.MagicMock(return_value=facts),
                ContentValidationError=weekly_plan_content.ContentValidationError,
            ),
        ):
            with self.assertRaises(WeeklyPlanConfirmAckRequired) as ctx:
                self._confirm(
                    db,
                    _snapshot("teacher"),
                    acknowledge_missing=False,
                    acknowledge_stale=False,
                )
        self.assertEqual(ctx.exception.code, "CONFIRM_ACK_REQUIRED")
        self.assertEqual(ctx.exception.facts["missing"], facts["missing"])
        db.rollback.assert_called()

    def test_confirm_note_empty_and_optional(self):
        plan = _plan(owner_id="tch1")
        draft_row = _draft(1)
        db = mock.MagicMock()
        db.in_transaction.return_value = True
        db.get.return_value = None
        facts = {"missing": [], "stale_sources": []}
        with mock.patch.object(
            weekly_plan_service, "_preload_header", return_value=_header()
        ), mock.patch.object(
            weekly_plan_service,
            "_lock_write_prefix",
            return_value=(_term(), "cls1"),
        ), mock.patch.object(
            weekly_plan_service, "_lock_weekly_plan", return_value=plan
        ), mock.patch.object(weekly_plan_service, "_assert_identity"), mock.patch.object(
            weekly_plan_service, "_load_week_days", return_value={}
        ), mock.patch.object(
            weekly_plan_service,
            "_load_week_sources",
            return_value=([], datetime(2026, 9, 20)),
        ), mock.patch.object(
            weekly_plan_service, "_lock_draft", return_value=draft_row
        ), mock.patch.object(weekly_plan_service, "_lock_confirmed_pointer"), mock.patch.object(
            weekly_plan_service,
            "weekly_plan_content",
            mock.MagicMock(
                build_facts=mock.MagicMock(return_value=facts),
                ContentValidationError=weekly_plan_content.ContentValidationError,
            ),
        ), mock.patch.object(
            weekly_plan_service.security, "generate_id", return_value="conf1"
        ), mock.patch.object(
            weekly_plan_service.auth_service,
            "utc_now",
            return_value=datetime(2026, 9, 21, 0, 0, 0),
        ), mock.patch.object(
            weekly_plan_service.auth_service, "record_operation"
        ) as rec:
            result = self._confirm(
                db, _snapshot("teacher"), note=""
            )
        self.assertIsNone(result.facts["note"])
        self.assertEqual(result.confirmed.version, 1)
        db.commit.assert_called_once()
        self.assertEqual(
            rec.call_args.kwargs["action"], "confirm_weekly_plan"
        )

    def test_confirm_content_deepcopy_keeps_old_version(self):
        plan = _plan(owner_id="tch1")
        nested = {"theme": "old", "cols": {"a": ["keep"]}}
        draft_row = _draft(1)
        draft_row.content = nested
        db = mock.MagicMock()
        db.in_transaction.return_value = True
        db.get.return_value = None
        facts = {"missing": [], "stale_sources": []}
        with mock.patch.object(
            weekly_plan_service, "_preload_header", return_value=_header()
        ), mock.patch.object(
            weekly_plan_service,
            "_lock_write_prefix",
            return_value=(_term(), "cls1"),
        ), mock.patch.object(
            weekly_plan_service, "_lock_weekly_plan", return_value=plan
        ), mock.patch.object(weekly_plan_service, "_assert_identity"), mock.patch.object(
            weekly_plan_service, "_load_week_days", return_value={}
        ), mock.patch.object(
            weekly_plan_service,
            "_load_week_sources",
            return_value=([], datetime(2026, 9, 20)),
        ), mock.patch.object(
            weekly_plan_service, "_lock_draft", return_value=draft_row
        ), mock.patch.object(weekly_plan_service, "_lock_confirmed_pointer"), mock.patch.object(
            weekly_plan_service,
            "weekly_plan_content",
            mock.MagicMock(
                build_facts=mock.MagicMock(return_value=facts),
                ContentValidationError=weekly_plan_content.ContentValidationError,
            ),
        ), mock.patch.object(
            weekly_plan_service.security, "generate_id", return_value="conf1"
        ), mock.patch.object(
            weekly_plan_service.auth_service,
            "utc_now",
            return_value=datetime(2026, 9, 21, 0, 0, 0),
        ), mock.patch.object(
            weekly_plan_service.auth_service, "record_operation"
        ):
            result = self._confirm(db, _snapshot("teacher"))
        self.assertIsNot(result.confirmed.content, nested)
        self.assertEqual(result.confirmed.content, nested)
        result.confirmed.content["cols"]["a"].append("later")
        self.assertEqual(nested["cols"]["a"], ["keep"])
        self.assertEqual(plan.current_confirmed_content_version, 1)
        self.assertEqual(plan.current_confirmed_content_id, "conf1")


class AdminSaveKeepsConfirmedTests(unittest.TestCase):
    def test_admin_save_does_not_change_confirmed_pointer(self):
        plan = _plan(owner_id="tch1")
        plan.current_confirmed_content_id = "cf1"
        plan.current_confirmed_content_version = 2
        confirmed_row = _orm(WeeklyPlanConfirmedContent)
        confirmed_row.id = "cf1"
        confirmed_row.weekly_plan_id = "wp1"
        confirmed_row.version = 2
        draft_row = _draft(1)
        db = mock.MagicMock()
        db.in_transaction.return_value = True
        db.get.return_value = confirmed_row

        with mock.patch.object(
            weekly_plan_service, "_preload_header", return_value=_header()
        ), mock.patch.object(
            weekly_plan_service,
            "_lock_write_prefix",
            return_value=(_term(), "cls1"),
        ), mock.patch.object(
            weekly_plan_service, "_lock_weekly_plan", return_value=plan
        ), mock.patch.object(weekly_plan_service, "_assert_identity"), mock.patch.object(
            weekly_plan_service, "_load_week_days", return_value={}
        ), mock.patch.object(
            weekly_plan_service,
            "_load_week_sources",
            return_value=([], datetime(2026, 9, 20)),
        ), mock.patch.object(
            weekly_plan_service, "_lock_draft", return_value=draft_row
        ), mock.patch.object(weekly_plan_service, "_lock_confirmed_pointer"), mock.patch.object(
            weekly_plan_service, "_load_confirmed_unlocked", return_value=confirmed_row
        ), mock.patch.object(
            weekly_plan_service.auth_service, "record_operation"
        ), mock.patch.object(
            weekly_plan_service.security, "generate_id", return_value="n4"
        ), mock.patch.object(
            weekly_plan_service.auth_service,
            "utc_now",
            return_value=datetime(2026, 9, 21, 0, 0, 0),
        ), mock.patch.object(
            weekly_plan_service,
            "weekly_plan_content",
                mock.MagicMock(
                    prepare_patch=mock.MagicMock(return_value={"theme": "z"}),
                    ContentValidationError=weekly_plan_content.ContentValidationError,
                ),
        ):
            result = save_weekly_plan(
                db,
                _snapshot("admin", account_id="adm1"),
                plan_id="wp1",
                expected_draft_version=1,
                patch={"theme": "z"},
                class_id="cls1",
            )
        self.assertIs(result.confirmed, confirmed_row)
        self.assertEqual(plan.current_confirmed_content_version, 2)
        self.assertEqual(plan.current_confirmed_content_id, "cf1")
        self.assertEqual(result.draft.editor_role, "admin")
        db.commit.assert_called_once()


class RollbackOnAnyFailureTests(unittest.TestCase):
    def test_save_commit_failure_rolls_back(self):
        plan = _plan(owner_id="tch1")
        draft_row = _draft(1)
        db = mock.MagicMock()
        db.in_transaction.return_value = True
        db.get.return_value = None
        db.commit.side_effect = RuntimeError("commit failed")

        with mock.patch.object(
            weekly_plan_service, "_preload_header", return_value=_header()
        ), mock.patch.object(
            weekly_plan_service,
            "_lock_write_prefix",
            return_value=(_term(), "cls1"),
        ), mock.patch.object(
            weekly_plan_service, "_lock_weekly_plan", return_value=plan
        ), mock.patch.object(weekly_plan_service, "_assert_identity"), mock.patch.object(
            weekly_plan_service, "_load_week_days", return_value={}
        ), mock.patch.object(
            weekly_plan_service,
            "_load_week_sources",
            return_value=([], datetime(2026, 9, 20)),
        ), mock.patch.object(
            weekly_plan_service, "_lock_draft", return_value=draft_row
        ), mock.patch.object(weekly_plan_service, "_lock_confirmed_pointer"), mock.patch.object(
            weekly_plan_service, "_load_confirmed_unlocked", return_value=None
        ), mock.patch.object(
            weekly_plan_service.auth_service, "record_operation"
        ), mock.patch.object(
            weekly_plan_service.security, "generate_id", return_value="n5"
        ), mock.patch.object(
            weekly_plan_service.auth_service,
            "utc_now",
            return_value=datetime(2026, 9, 21, 0, 0, 0),
        ), mock.patch.object(
            weekly_plan_service,
            "weekly_plan_content",
            mock.MagicMock(
                prepare_patch=mock.MagicMock(return_value={"theme": ""}),
                ContentValidationError=weekly_plan_content.ContentValidationError,
            ),
        ):
            with self.assertRaises(RuntimeError):
                save_weekly_plan(
                    db,
                    _snapshot("teacher"),
                    plan_id="wp1",
                    expected_draft_version=1,
                    patch={},
                )
        db.rollback.assert_called_once()

    def test_confirm_runtime_failure_rolls_back(self):
        plan = _plan(owner_id="tch1")
        draft_row = _draft(1)
        db = mock.MagicMock()
        db.in_transaction.return_value = True
        with mock.patch.object(
            weekly_plan_service, "_preload_header", return_value=_header()
        ), mock.patch.object(
            weekly_plan_service,
            "_lock_write_prefix",
            return_value=(_term(), "cls1"),
        ), mock.patch.object(
            weekly_plan_service, "_lock_weekly_plan", return_value=plan
        ), mock.patch.object(weekly_plan_service, "_assert_identity"), mock.patch.object(
            weekly_plan_service, "_load_week_days", return_value={}
        ), mock.patch.object(
            weekly_plan_service,
            "_load_week_sources",
            side_effect=RuntimeError("boom"),
        ), mock.patch.object(
            weekly_plan_service, "_lock_draft", return_value=draft_row
        ), mock.patch.object(weekly_plan_service, "_lock_confirmed_pointer"):
            with self.assertRaises(RuntimeError):
                confirm_weekly_plan(
                    db,
                    _snapshot("teacher"),
                    plan_id="wp1",
                    expected_draft_version=1,
                    acknowledge_missing=True,
                    acknowledge_stale=True,
                )
        db.rollback.assert_called_once()

    def test_content_validation_maps_to_422(self):
        plan = _plan(owner_id="tch1")
        draft_row = _draft(1)
        db = mock.MagicMock()
        db.in_transaction.return_value = True
        with mock.patch.object(
            weekly_plan_service, "_preload_header", return_value=_header()
        ), mock.patch.object(
            weekly_plan_service,
            "_lock_write_prefix",
            return_value=(_term(), "cls1"),
        ), mock.patch.object(
            weekly_plan_service, "_lock_weekly_plan", return_value=plan
        ), mock.patch.object(weekly_plan_service, "_assert_identity"), mock.patch.object(
            weekly_plan_service, "_load_week_days", return_value={}
        ), mock.patch.object(
            weekly_plan_service,
            "_load_week_sources",
            return_value=([], datetime(2026, 9, 20)),
        ), mock.patch.object(
            weekly_plan_service, "_lock_draft", return_value=draft_row
        ), mock.patch.object(weekly_plan_service, "_lock_confirmed_pointer"), mock.patch.object(
            weekly_plan_service,
            "weekly_plan_content",
                mock.MagicMock(
                    prepare_patch=mock.MagicMock(
                        side_effect=weekly_plan_content.ContentValidationError("bad")
                    ),
                    ContentValidationError=weekly_plan_content.ContentValidationError,
                ),
        ):
            with self.assertRaises(WeeklyPlanValidationError) as ctx:
                save_weekly_plan(
                    db,
                    _snapshot("teacher"),
                    plan_id="wp1",
                    expected_draft_version=1,
                    patch={},
                )
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
        db.rollback.assert_called_once()


class UniqueConflictReopenTests(unittest.TestCase):
    def _unique_exc(self) -> IntegrityError:
        return IntegrityError(
            "INSERT",
            {},
            Exception(
                1062,
                "Duplicate entry 'x' for key "
                "'weekly_plans.uq_weekly_plans_class_term_effective_week'",
            ),
        )

    def test_classifier(self):
        self.assertTrue(
            is_weekly_effective_unique_violation(self._unique_exc())
        )
        other = IntegrityError(
            "INSERT", {}, Exception(1452, "foreign key constraint fails")
        )
        self.assertFalse(is_weekly_effective_unique_violation(other))

    def test_non_unique_integrity_not_swallowed(self):
        exc = IntegrityError("INSERT", {}, Exception(1452, "fk"))
        db = mock.MagicMock()
        db.in_transaction.return_value = False
        with mock.patch.object(
            weekly_plan_service,
            "_create_or_open_locked",
            side_effect=exc,
        ), mock.patch.object(
            weekly_plan_service, "_open_existing_after_conflict"
        ) as reopen:
            with self.assertRaises(IntegrityError) as ctx:
                create_or_open_weekly_plan(
                    db, _snapshot("teacher"), term_id="ter1", week_number=1
                )
        self.assertIs(ctx.exception, exc)
        reopen.assert_not_called()
        db.rollback.assert_called_once()

    def test_unique_conflict_reopens_winner_and_commits(self):
        exc = self._unique_exc()
        winner = _plan(owner_id="tch0")
        draft_row = _draft(1)
        db = mock.MagicMock()
        db.in_transaction.return_value = False

        with mock.patch.object(
            weekly_plan_service,
            "_create_or_open_locked",
            side_effect=exc,
        ), mock.patch.object(
            weekly_plan_service,
            "_open_existing_after_conflict",
            return_value=weekly_plan_service.WeeklyPlanWriteResult(
                plan=winner, draft=draft_row, confirmed=None, created=False
            ),
        ) as reopen:
            result = create_or_open_weekly_plan(
                db, _snapshot("teacher"), term_id="ter1", week_number=1
            )
        self.assertFalse(result.created)
        self.assertIs(result.plan, winner)
        reopen.assert_called_once()
        db.rollback.assert_called()

    def test_reopen_permission_failure_rolls_back_and_reraises(self):
        exc = self._unique_exc()
        db = mock.MagicMock()
        db.in_transaction.return_value = False
        forbidden = WeeklyPlanForbidden("lost assignment")
        with mock.patch.object(
            weekly_plan_service,
            "_create_or_open_locked",
            side_effect=exc,
        ), mock.patch.object(
            weekly_plan_service,
            "_open_existing_after_conflict",
            side_effect=forbidden,
        ):
            with self.assertRaises(WeeklyPlanForbidden) as ctx:
                create_or_open_weekly_plan(
                    db, _snapshot("teacher"), term_id="ter1", week_number=1
                )
        self.assertIs(ctx.exception, forbidden)
        self.assertGreaterEqual(db.rollback.call_count, 1)


class SourcesLockQueryTests(unittest.TestCase):
    def test_daily_plan_query_ordered_and_locked_with_populate(self):
        db = mock.MagicMock()
        db.scalars.return_value.all.return_value = []
        db.execute.return_value.scalar_one_or_none.return_value = _sync_row()

        weekly_plan_service._load_week_sources_by_key(
            db, class_id="cls1", term_id="ter1", week_number=1
        )
        stmt = db.scalars.call_args[0][0]
        self.assertIsNotNone(getattr(stmt, "_for_update_arg", None))
        opts = stmt._execution_options
        self.assertTrue(opts.get("populate_existing"))
        order_by = stmt._order_by_clauses
        self.assertTrue(order_by)
        rendered = str(stmt)
        self.assertIn("plan_date", rendered)
        # sync read is also FOR UPDATE + populate_existing
        sync_stmt = db.execute.call_args[0][0]
        self.assertIsNotNone(getattr(sync_stmt, "_for_update_arg", None))
        self.assertTrue(sync_stmt._execution_options.get("populate_existing"))
        self.assertEqual(len(db.scalars.call_args_list), 1)

    def test_sync_row_never_written_and_status_checked(self):
        db = mock.MagicMock()
        db.scalars.return_value.all.return_value = []
        bad = _sync_row()
        bad.status = "other"
        db.execute.return_value.scalar_one_or_none.return_value = bad
        with self.assertRaises(weekly_plan_service.WeeklyPlanDataError) as ctx:
            weekly_plan_service._load_week_sources_by_key(
                db, class_id="cls1", term_id="ter1", week_number=1
            )
        self.assertEqual(ctx.exception.code, "SERVICE_UNAVAILABLE")
        self.assertFalse(hasattr(db, "add") and db.add.called)
        self.assertFalse(hasattr(db, "commit") and db.commit.called)

    def test_missing_sync_with_entries_is_503(self):
        db = mock.MagicMock()
        plan_row = _daily_plan()
        content_row = _daily_content()
        db.scalars.side_effect = [
            SimpleNamespace(all=lambda: [plan_row]),
            SimpleNamespace(all=lambda: [content_row]),
        ]
        db.execute.return_value.scalar_one_or_none.return_value = None
        with self.assertRaises(weekly_plan_service.WeeklyPlanDataError):
            weekly_plan_service._load_week_sources_by_key(
                db, class_id="cls1", term_id="ter1", week_number=1
            )

    def test_empty_week_without_sync_uses_now(self):
        db = mock.MagicMock()
        db.scalars.return_value.all.return_value = []
        db.execute.return_value.scalar_one_or_none.return_value = None
        entries, consumed = weekly_plan_service._load_week_sources_by_key(
            db, class_id="cls1", term_id="ter1", week_number=1
        )
        self.assertEqual(entries, [])
        self.assertIsInstance(consumed, datetime)


class LockOrderCreateTests(unittest.TestCase):
    def test_calendar_days_before_weekly_lookup(self):
        events: list[str] = []
        db = mock.MagicMock()
        db.in_transaction.return_value = False
        existing = _plan(owner_id="tch0")
        draft_row = _draft(1)

        with mock.patch.object(
            weekly_plan_service, "_lock_operator", return_value=_account("teacher")
        ), mock.patch.object(
            weekly_plan_service, "_resolve_create_class", return_value="cls1"
        ), mock.patch.object(
            weekly_plan_service, "lock_school", return_value=SimpleNamespace()
        ), mock.patch.object(
            weekly_plan_service,
            "lock_class",
            return_value=_school_class(),
        ), mock.patch.object(
            weekly_plan_service, "_require_term", return_value=_term()
        ), mock.patch.object(
            weekly_plan_service, "_validate_week_in_term"
        ), mock.patch.object(
            weekly_plan_service,
            "_load_week_days",
            side_effect=lambda *a: events.append("days") or {},
        ), mock.patch.object(
            weekly_plan_service,
            "_find_effective_weekly",
            side_effect=lambda *a, **k: events.append("weekly_find") or existing,
        ), mock.patch.object(
            weekly_plan_service, "_lock_draft", return_value=draft_row
        ), mock.patch.object(weekly_plan_service, "_lock_confirmed_pointer"), mock.patch.object(
            weekly_plan_service, "_load_confirmed_unlocked", return_value=None
        ):
            result = create_or_open_weekly_plan(
                db,
                _snapshot("teacher"),
                term_id="ter1",
                week_number=1,
            )
        self.assertEqual(events, ["days", "weekly_find"])
        self.assertFalse(result.created)


if __name__ == "__main__":
    unittest.main()
