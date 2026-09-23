"""No-DB mock tests for the I4 read-only weekly plan query service (slice 2).

Covers class-access judgements, confirmation status / needs_confirm,
can_edit / can_confirm, projection_pending comparison, live fact/candidate
assembly with ``_audit`` stripping, pointer guards and the list/confirmation
queries — all against a stub session, no MySQL, no SQLite, no HTTP.
"""

import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest import mock

from sqlalchemy.engine import ScalarResult

from app.models import (
    Term,
    WeeklyPlan,
    WeeklyPlanContent,
    WeeklyPlanConfirmedContent,
)
from app.services import weekly_plan_read_service as read_svc
from app.services.weekly_plan_service import (
    WeeklyPlanDataError,
    WeeklyPlanForbidden,
    WeeklyPlanNotFound,
    WeeklyPlanTermNotFound,
)

_NOW = datetime(2026, 9, 23, 8, 0, 0)


def _term() -> Term:
    term = Term()
    term.id = "ter1"
    term.name = "秋"
    term.start_date = date(2026, 9, 1)
    term.end_date = date(2026, 9, 28)
    term.current_calendar_revision_id = "rev1"
    return term


def _plan(**kw) -> WeeklyPlan:
    defaults = dict(
        id="wp1",
        class_id="cls1",
        term_id="ter1",
        week_number=2,
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
        projection_consumed_at=datetime(2026, 9, 20, 0, 0, 0),
        deleted_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    defaults.update(kw)
    plan = WeeklyPlan()
    for key, value in defaults.items():
        setattr(plan, key, value)
    return plan


def _draft(**kw) -> WeeklyPlanContent:
    defaults = dict(
        id="c2",
        weekly_plan_id="wp1",
        version=2,
        content={"theme": "", "_audit": {"action": "save"}},
        editor_id="tch1",
        editor_role="owner",
        created_at=_NOW,
    )
    defaults.update(kw)
    row = WeeklyPlanContent()
    for key, value in defaults.items():
        setattr(row, key, value)
    return row


def _confirmed(**kw) -> WeeklyPlanConfirmedContent:
    defaults = dict(
        id="cf1",
        weekly_plan_id="wp1",
        version=1,
        draft_version=2,
        content={"theme": "秋", "_audit": {"action": "confirm"}},
        facts={"missing": [], "stale_sources": []},
        confirmed_by="tch1",
        created_at=_NOW,
    )
    defaults.update(kw)
    row = WeeklyPlanConfirmedContent()
    for key, value in defaults.items():
        setattr(row, key, value)
    return row


def _week2_days() -> list:
    # Mon 2026-09-07 .. Sun 2026-09-13 (inside term 09-01..09-28).
    states = [
        (date(2026, 9, 7), "teaching"),
        (date(2026, 9, 8), "teaching"),
        (date(2026, 9, 9), "non_teaching"),
        (date(2026, 9, 10), "teaching"),
        (date(2026, 9, 11), "teaching"),
        (date(2026, 9, 12), "non_teaching"),
        (date(2026, 9, 13), "non_teaching"),
    ]
    return [
        SimpleNamespace(date=day, effective_state=state)
        for day, state in states
    ]


class _StubSession:
    def __init__(self):
        self.get_map: dict[str, object] = {}
        self.scalars_rows: list = []
        self.scalar_value: object = 0

    def get(self, entity, key):
        name = getattr(entity, "__name__", str(entity))
        return self.get_map.get((name, key))

    def scalars(self, stmt):
        result = mock.Mock(spec_set=ScalarResult)
        result.all.return_value = list(self.scalars_rows)
        result.one_or_none.return_value = (
            self.scalars_rows[0] if self.scalars_rows else None
        )
        return result

    def scalar(self, stmt):
        return self.scalar_value

    def begin(self):
        raise AssertionError("read service must not open a transaction")

    def commit(self):
        raise AssertionError("read service must not commit")

    def rollback(self):
        raise AssertionError("read service must not roll back")

    def flush(self):
        raise AssertionError("read service must not flush")

    def add(self, obj):
        raise AssertionError("read service must not write")


class PublicContentTests(unittest.TestCase):
    def test_strips_audit_and_keeps_structure(self):
        body = read_svc.public_content(
            {"theme": "秋", "materials": None, "_audit": {"action": "save"}}
        )
        self.assertEqual(body, {"theme": "秋", "materials": None})
        self.assertNotIn("_audit", body)

    def test_non_dict_becomes_empty(self):
        self.assertEqual(read_svc.public_content(None), {})
        self.assertEqual(read_svc.public_content(["x"]), {})


class StatusAndPermissionTests(unittest.TestCase):
    def test_confirmation_status_transitions(self):
        self.assertEqual(
            read_svc._confirmation_status(None, 2), "never_confirmed"
        )
        self.assertEqual(
            read_svc._confirmation_status(_confirmed(draft_version=1), 2),
            "draft_ahead",
        )
        self.assertEqual(
            read_svc._confirmation_status(_confirmed(draft_version=2), 2),
            "draft_current",
        )

    def test_permissions_owner_admin_non_owner(self):
        plan = _plan(owner_id="tch1")
        self.assertEqual(
            read_svc._permissions(plan, account_id="tch1", role="teacher"),
            (True, True),
        )
        self.assertEqual(
            read_svc._permissions(plan, account_id="tch2", role="teacher"),
            (False, False),
        )
        # Admin can edit but never confirms (spec §5.2).
        self.assertEqual(
            read_svc._permissions(plan, account_id="adm1", role="admin"),
            (True, False),
        )

    def test_class_access_matrix(self):
        plan = _plan(class_id="cls1")
        read_svc._assert_class_access(plan, role="teacher", class_id="cls1")
        read_svc._assert_class_access(plan, role="admin", class_id="cls1")
        with self.assertRaises(WeeklyPlanForbidden):
            read_svc._assert_class_access(
                plan, role="teacher", class_id="cls2"
            )
        with self.assertRaises(WeeklyPlanNotFound):
            read_svc._assert_class_access(plan, role="admin", class_id="cls2")

    def test_unknown_and_deleted_plan_are_not_found(self):
        db = _StubSession()
        with self.assertRaises(WeeklyPlanNotFound):
            read_svc._load_plan(db, "missing")
        db.get_map[("WeeklyPlan", "wp1")] = _plan(
            deleted_at=datetime(2026, 9, 22, 0, 0, 0)
        )
        with self.assertRaises(WeeklyPlanNotFound):
            read_svc._load_plan(db, "wp1")


class PointerGuardTests(unittest.TestCase):
    def test_empty_and_inconsistent_draft_pointers_are_503(self):
        db = _StubSession()
        with self.assertRaises(WeeklyPlanDataError):
            read_svc._load_draft(
                db,
                _plan(
                    current_draft_content_id=None,
                    current_draft_version=None,
                ),
            )
        with self.assertRaises(WeeklyPlanDataError):
            read_svc._load_draft(db, _plan())
        db.get_map[("WeeklyPlanContent", "c2")] = _draft(version=9)
        with self.assertRaises(WeeklyPlanDataError):
            read_svc._load_draft(db, _plan())

    def test_partial_confirmed_pointer_is_503(self):
        db = _StubSession()
        with self.assertRaises(WeeklyPlanDataError):
            read_svc._load_confirmed(
                db, _plan(current_confirmed_content_id="cf1")
            )
        self.assertIsNone(read_svc._load_confirmed(db, _plan()))

    def test_missing_term_is_term_not_found(self):
        db = _StubSession()
        with self.assertRaises(WeeklyPlanTermNotFound):
            read_svc._load_term(db, "ter1")


class GetDetailAssemblyTests(unittest.TestCase):
    def _db(self) -> _StubSession:
        db = _StubSession()
        db.get_map[("WeeklyPlan", "wp1")] = _plan()
        db.get_map[("WeeklyPlanContent", "c2")] = _draft()
        db.get_map[("Term", "ter1")] = _term()
        db.get_map[("CalendarRevision", "rev1")] = SimpleNamespace(id="rev1")
        db.scalars_rows = _week2_days()
        return db

    def test_detail_assembles_header_facts_flags_without_writes(self):
        db = self._db()
        result_log = []

        def fake_entries(*args, **kwargs):
            result_log.append("entries")
            return []

        def fake_sync(*args, **kwargs):
            result_log.append("sync")
            return None

        with mock.patch.object(
            read_svc.weekly_plan_sync_service,
            "load_week_entries",
            side_effect=fake_entries,
        ), mock.patch.object(
            read_svc.weekly_plan_sync_service,
            "get_weekly_sync_state",
            side_effect=fake_sync,
        ):
            payload = read_svc.get_detail(
                db, "wp1", account_id="tch1", role="teacher",
                class_id="cls1",
            )

        self.assertEqual(result_log, ["entries", "sync"])
        self.assertEqual(payload["school_name"], "阳光园")
        self.assertEqual(payload["confirmation_status"], "never_confirmed")
        self.assertTrue(payload["needs_confirm"])
        self.assertTrue(payload["can_edit"])
        self.assertTrue(payload["can_confirm"])
        self.assertFalse(payload["projection_pending"])
        self.assertIsNone(payload["confirmed"])
        self.assertNotIn("_audit", payload["draft"]["content"])
        self.assertEqual(payload["draft"]["audit"], {"action": "save"})
        kinds = {item["kind"] for item in payload["missing"]}
        self.assertIn("empty_theme", kinds)
        self.assertIn("materials", kinds)
        self.assertEqual(payload["stale_sources"], [])
        self.assertEqual(payload["source_candidates"], [])

    def test_admin_assembly_edits_but_never_confirms(self):
        db = self._db()
        with mock.patch.object(
            read_svc.weekly_plan_sync_service,
            "load_week_entries",
            return_value=[],
        ), mock.patch.object(
            read_svc.weekly_plan_sync_service,
            "get_weekly_sync_state",
            return_value=None,
        ):
            payload = read_svc.get_detail(
                db, "wp1", account_id="adm1", role="admin",
                class_id="cls1",
            )
        self.assertTrue(payload["can_edit"])
        self.assertFalse(payload["can_confirm"])

    def test_confirmed_summary_and_draft_ahead(self):
        db = self._db()
        confirmed = _confirmed(draft_version=1)
        db.get_map[("WeeklyPlan", "wp1")] = _plan(
            current_confirmed_content_id="cf1",
            current_confirmed_content_version=1,
        )
        db.get_map[("WeeklyPlanConfirmedContent", "cf1")] = confirmed
        with mock.patch.object(
            read_svc.weekly_plan_sync_service,
            "load_week_entries",
            return_value=[],
        ), mock.patch.object(
            read_svc.weekly_plan_sync_service,
            "get_weekly_sync_state",
            return_value=None,
        ):
            payload = read_svc.get_detail(
                db, "wp1", account_id="tch1", role="teacher",
                class_id="cls1",
            )
        self.assertEqual(payload["confirmation_status"], "draft_ahead")
        self.assertTrue(payload["needs_confirm"])
        self.assertEqual(payload["confirmed"]["version"], 1)
        self.assertEqual(payload["confirmed"]["draft_version"], 1)

    def test_projection_pending_when_sync_newer_than_consumed(self):
        db = self._db()
        sync = SimpleNamespace(
            status="pending_projection",
            updated_at=datetime(2026, 9, 22, 12, 0, 0),
        )
        with mock.patch.object(
            read_svc.weekly_plan_sync_service,
            "load_week_entries",
            return_value=[],
        ), mock.patch.object(
            read_svc.weekly_plan_sync_service,
            "get_weekly_sync_state",
            return_value=sync,
        ):
            payload = read_svc.get_detail(
                db, "wp1", account_id="tch1", role="teacher",
                class_id="cls1",
            )
        self.assertTrue(payload["projection_pending"])

        # Sync older than consumption -> banner off.
        sync.updated_at = datetime(2026, 9, 19, 0, 0, 0)
        with mock.patch.object(
            read_svc.weekly_plan_sync_service,
            "load_week_entries",
            return_value=[],
        ), mock.patch.object(
            read_svc.weekly_plan_sync_service,
            "get_weekly_sync_state",
            return_value=sync,
        ):
            payload = read_svc.get_detail(
                db, "wp1", account_id="tch1", role="teacher",
                class_id="cls1",
            )
        self.assertFalse(payload["projection_pending"])

    def test_entries_without_sync_row_are_503(self):
        db = self._db()
        entry = SimpleNamespace()
        with mock.patch.object(
            read_svc.weekly_plan_sync_service,
            "load_week_entries",
            return_value=[entry],
        ), mock.patch.object(
            read_svc.weekly_plan_sync_service,
            "get_weekly_sync_state",
            return_value=None,
        ):
            with self.assertRaises(WeeklyPlanDataError):
                read_svc.get_detail(
                    db, "wp1", account_id="tch1", role="teacher",
                    class_id="cls1",
                )

    def test_teacher_cross_class_detail_is_403(self):
        db = self._db()
        with self.assertRaises(WeeklyPlanForbidden):
            read_svc.get_detail(
                db, "wp1", account_id="tch1", role="teacher",
                class_id="cls9",
            )

    def test_admin_wrong_class_detail_is_404(self):
        db = self._db()
        with self.assertRaises(WeeklyPlanNotFound):
            read_svc.get_detail(
                db, "wp1", account_id="adm1", role="admin",
                class_id="cls9",
            )


class ListPlansTests(unittest.TestCase):
    def test_unknown_term_filter_is_term_not_found(self):
        db = _StubSession()
        with self.assertRaises(WeeklyPlanTermNotFound):
            read_svc.list_plans(
                db, class_id="cls1", term_id="nope", offset=0, limit=20
            )

    def test_empty_draft_pointer_is_503(self):
        db = _StubSession()
        db.scalars_rows = [
            _plan(current_draft_content_id=None, current_draft_version=None)
        ]
        with self.assertRaises(WeeklyPlanDataError):
            read_svc.list_plans(
                db, class_id="cls1", term_id=None, offset=0, limit=20
            )

    def test_never_confirmed_item_needs_confirm(self):
        db = _StubSession()
        db.scalar_value = 1
        db.scalars_rows = [_plan()]
        items, total = read_svc.list_plans(
            db, class_id="cls1", term_id=None, offset=0, limit=20
        )
        self.assertEqual(total, 1)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["draft_version"], 2)
        self.assertIsNone(item["confirmed_version"])
        self.assertTrue(item["needs_confirm"])
        for field in (
            "id",
            "term_id",
            "week_number",
            "creator_id",
            "owner_id",
            "updated_at",
        ):
            self.assertIn(field, item)
        self.assertNotIn("class_name", item)

    def test_confirmed_states_drive_needs_confirm(self):
        db = _StubSession()
        db.scalar_value = 2
        plan = _plan(
            current_confirmed_content_id="cf1",
            current_confirmed_content_version=1,
        )
        db.scalars_rows = [plan]
        # Confirmed at an older draft -> still pending.
        db.get_map[("WeeklyPlanConfirmedContent", "cf1")] = _confirmed(
            draft_version=1
        )
        items, _ = read_svc.list_plans(
            db, class_id="cls1", term_id=None, offset=0, limit=20
        )
        self.assertEqual(items[0]["confirmed_version"], 1)
        self.assertTrue(items[0]["needs_confirm"])

        # Confirmation matches current draft -> settled.
        db.get_map[("WeeklyPlanConfirmedContent", "cf1")] = _confirmed(
            draft_version=2
        )
        items, _ = read_svc.list_plans(
            db, class_id="cls1", term_id=None, offset=0, limit=20
        )
        self.assertFalse(items[0]["needs_confirm"])

    def test_inconsistent_confirmed_pointer_is_503(self):
        db = _StubSession()
        db.scalars_rows = [
            _plan(
                current_confirmed_content_id="cf1",
                current_confirmed_content_version=1,
            )
        ]
        with self.assertRaises(WeeklyPlanDataError):
            read_svc.list_plans(
                db, class_id="cls1", term_id=None, offset=0, limit=20
            )


class ConfirmationQueryTests(unittest.TestCase):
    def _db(self) -> _StubSession:
        db = _StubSession()
        db.get_map[("WeeklyPlan", "wp1")] = _plan()
        return db

    def test_list_confirmations_class_access_and_summary_shape(self):
        db = self._db()
        db.scalars_rows = [_confirmed()]
        result = read_svc.list_confirmations(
            db, "wp1", role="teacher", class_id="cls1"
        )
        self.assertEqual(result["total"], 1)
        item = result["items"][0]
        self.assertEqual(item["version"], 1)
        self.assertEqual(item["confirmed_by"], "tch1")
        self.assertNotIn("content", item)

        with self.assertRaises(WeeklyPlanForbidden):
            read_svc.list_confirmations(
                db, "wp1", role="teacher", class_id="cls9"
            )
        with self.assertRaises(WeeklyPlanNotFound):
            read_svc.list_confirmations(
                db, "wp1", role="admin", class_id="cls9"
            )

    def test_get_confirmation_strips_audit_and_404s_unknown_version(self):
        db = self._db()
        db.scalars_rows = [_confirmed()]
        payload = read_svc.get_confirmation(
            db, "wp1", 1, role="teacher", class_id="cls1"
        )
        self.assertEqual(payload["version"], 1)
        self.assertNotIn("_audit", payload["content"])
        self.assertEqual(payload["content"], {"theme": "秋"})
        self.assertEqual(payload["weekly_plan_id"], "wp1")

        db.scalars_rows = []
        with self.assertRaises(WeeklyPlanNotFound):
            read_svc.get_confirmation(
                db, "wp1", 9, role="teacher", class_id="cls1"
            )


if __name__ == "__main__":
    unittest.main()
