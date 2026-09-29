"""Isolated MySQL 8.4/InnoDB integration tests for the I5 export slice 3.

Runs only against the whitelisted I5 databases via ``i5_guard``. This layer
is the authoritative one for transaction/isolation semantics: the
concurrency tests drive the real ASGI app while a real second connection
commits a business write in the middle of an export request, then assert the
delivered file still equals the request-time pinned versions (MySQL
REPEATABLE READ inside one consistent view). Mock/unit tests never claim
this.

Also verified on the real schema: the permission matrix, the daily 409 ack
loop across real requests, range/single weekly selection with immutable
confirmations, the 31/32 and 8/9 plan-count limits on real selections, the
audit transaction order (one class-level ``export_word`` row on success,
none on failure, no file until commit) and DOCX/ZIP validity without
LibreOffice.
"""

import io
import json
import unittest
import zipfile
from datetime import date, timedelta
from unittest import mock

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_sessionlocal
from app.models import DailyPlan
from app.routers import exports as export_router
from app.services import auth_service, export_read_service, word_export_docx
from app.services.word_export_docx import WordTemplateError

from tests.integration.i5_guard import (
    check_environment,
    ensure_schema,
    make_engine,
    require_authorized_url,
    reset_i5_tables,
    skip_unless_enabled,
)
from tests.integration.i5_support import (
    ADMIN,
    AsgiClient,
    CLASS_ID,
    CROSS,
    FREE,
    OTHER_CLASS_ID,
    OWNER,
    REVISION_ID,
    SAME,
    TERM_END,
    TERM_ID,
    TERM_START,
    confirm_weekly,
    create_daily,
    create_weekly,
    full_day_content,
    save_daily,
    save_weekly,
    seed_world,
    snap,
)


class _ResultHeaders:
    """Case-insensitive single-value header view."""

    def __init__(self, pairs):
        self._forward = {}
        for key, value in pairs:
            self._forward.setdefault(key.lower(), value)

    def header(self, name: str):
        return self._forward.get(name.lower())


class _Result(tuple):
    """``(status, headers, body)`` triple for direct unpacking."""

    @property
    def status(self):
        return self[0]

    @property
    def headers(self):
        return self[1]

    @property
    def body(self):
        return self[2]

    @property
    def error(self):
        return (json.loads(self[2].decode("utf-8")) or {}).get("error") or {}


class _PostingClient:
    """Wraps the shared AsgiClient with an unpackable post() result."""

    def __init__(self, inner: AsgiClient):
        self._inner = inner

    def post(self, path, payload):
        response = self._inner.post(path, payload)
        return _Result(
            (
                response.status_code,
                _ResultHeaders(response.headers_list),
                response.content,
            )
        )


def unzip_document(payload: bytes) -> str:
    """Decode ``word/document.xml`` of a produced DOCX (no LibreOffice)."""
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert archive.testzip() is None
        return archive.read("word/document.xml").decode("utf-8")


@skip_unless_enabled
class I5ExportIntegrationTestCase(unittest.TestCase):
    """Reset + reseed the whitelisted I5 database for every test."""

    version_reported: str | None = None
    database_reported: str | None = None
    revision_reported: str | None = None

    @classmethod
    def setUpClass(cls):
        cls.engine = make_engine()
        require_authorized_url(str(cls.engine.url))
        version, database = check_environment(cls.engine)
        cls.version_reported, cls.database_reported = version, database
        cls.revision_reported = ensure_schema(cls.engine)
        print(
            f"[i5-guard] host=127.0.0.1 port=13386 db={database} "
            f"mysql={version} alembic_head={cls.revision_reported}"
        )

    @classmethod
    def tearDownClass(cls):
        if cls.engine is not None:
            cls.engine.dispose()
            cls.engine = None

    def setUp(self):
        print(
            f"[i5-guard] host=127.0.0.1 port=13386 db={self.database_reported} "
            f"mysql={self.version_reported} "
            f"alembic_head={self.revision_reported}"
        )
        reset_i5_tables(self.engine)
        seed_world(self.engine)
        self.SessionLocal = get_sessionlocal()
        self.owner = self.client_for(OWNER)
        self.same = self.client_for(SAME)
        self.cross = self.client_for(CROSS)
        self.free = self.client_for(FREE)
        self.admin = self.client_for(ADMIN)

    # -- helpers -----------------------------------------------------------

    def client_for(self, account: dict) -> _PostingClient:
        client = AsgiClient()
        client.login_as(account)
        return _PostingClient(client)

    def session(self) -> Session:
        return self.SessionLocal()

    def count(self, table: str) -> int:
        with self.engine.connect() as conn:
            return int(
                conn.execute(text(f"SELECT COUNT(*) FROM `{table}`")).scalar()
                or 0
            )

    def teaching_days(self, count: int) -> list[date]:
        """First ``count`` teaching days of the fixture term from 2026-08-03."""
        days: list[date] = []
        day = TERM_START
        while len(days) < count:
            if self.effective_state(day) == "teaching":
                days.append(day)
            day += timedelta(days=1)
        return days

    def effective_state(self, day: date) -> str:
        with self.engine.connect() as conn:
            return conn.execute(
                text(
                    "SELECT effective_state FROM calendar_days "
                    "WHERE revision_id = :rev AND date = :day"
                ),
                {"rev": REVISION_ID, "day": day},
            ).scalar_one()

    def daily_plan_row(self, plan_date: date) -> DailyPlan:
        return (
            self.session()
            .query(DailyPlan)
            .filter_by(plan_date=plan_date, class_id=CLASS_ID)
            .one()
        )

    def export_records(self, *, action="export_word", class_id=None):
        sql = (
            "SELECT operator_id, operator_type, action, target_type, "
            "target_id, target_version_after, target_account_id, "
            "account_version_after "
            "FROM operation_records WHERE action = :action"
        )
        params: dict = {"action": action}
        if class_id is not None:
            sql += " AND target_type = 'class' AND target_id = :cls"
            params["cls"] = class_id
        with self.engine.connect() as conn:
            return [
                tuple(r) for r in conn.execute(text(sql), params).fetchall()
            ]

    def doc_document(self, payload: bytes) -> str:
        return unzip_document(payload)


# ---------------------------------------------------------------------------
# permission matrix on the real schema
# ---------------------------------------------------------------------------


class PermissionMatrixTests(I5ExportIntegrationTestCase):
    def setUp(self):
        super().setUp()
        dates = self.teaching_days(2)
        content = full_day_content("矩阵主题")
        for day in dates:
            create_daily(self.SessionLocal, OWNER, day, adopted_content=content)
        self.day_from = dates[0].isoformat()
        self.day_to = dates[-1].isoformat()

    def test_daily_teacher_own_class_exports_valid_docx(self):
        status, headers, payload = self.owner.post(
            "/api/exports/daily-plans",
            {"from": self.day_from, "to": self.day_to},
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            headers.header("Content-Type"),
            "application/vnd.openxmlformats-officedocument.wordprocessingml."
            "document",
        )
        self.assertEqual(headers.header("Cache-Control"), "no-store")
        self.assertEqual(headers.header("X-Content-Type-Options"), "nosniff")
        document = self.doc_document(payload)
        self.assertIn("矩阵主题", document)
        self.assertIn("小班甲", document)
        self.assertIn("甲老师", document)

    def test_daily_same_class_non_creator_can_export(self):
        status, _, payload = self.same.post(
            "/api/exports/daily-plans",
            {"from": self.day_from, "to": self.day_to},
        )
        self.assertEqual(status, 200)
        self.assertIn("矩阵主题", self.doc_document(payload))
        self.assertEqual(len(self.export_records(class_id=CLASS_ID)), 1)

    def test_daily_unassigned_teacher_is_403_without_file_or_audit(self):
        status, _, payload = self.free.post(
            "/api/exports/daily-plans",
            {"from": self.day_from, "to": self.day_to},
        )
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(payload)["error"]["code"], "FORBIDDEN")
        self.assertTrue(payload.startswith(b'{"error"'))
        self.assertEqual(self.export_records(), [])

    def test_weekly_single_cross_class_plan_id_is_403(self):
        """A CROSS-assigned teacher cannot reach OWNER's plan id."""
        result = create_weekly(self.SessionLocal, OWNER, week=2)
        confirm_weekly(
            self.SessionLocal,
            OWNER,
            result.plan.id,
            expected_draft_version=result.draft.version,
        )
        status, _, payload = self.cross.post(
            "/api/exports/weekly-plans", {"plan_id": result.plan.id}
        )
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(payload)["error"]["code"], "FORBIDDEN")
        self.assertEqual(self.export_records(), [])

    def test_weekly_single_unconfirmed_is_404_confirmation_not_found(self):
        result = create_weekly(self.SessionLocal, OWNER, week=2)
        status, _, payload = self.owner.post(
            "/api/exports/weekly-plans", {"plan_id": result.plan.id}
        )
        self.assertEqual(status, 404)
        self.assertEqual(
            json.loads(payload)["error"]["code"], "CONFIRMATION_NOT_FOUND"
        )
        self.assertEqual(self.export_records(), [])

    def test_weekly_single_unknown_plan_id_is_404(self):
        status, _, payload = self.owner.post(
            "/api/exports/weekly-plans", {"plan_id": "no-such-plan"}
        )
        self.assertEqual(status, 404)
        self.assertEqual(
            json.loads(payload)["error"]["code"], "WEEKLY_PLAN_NOT_FOUND"
        )

    def test_admin_missing_class_is_422(self):
        for path, payload in (
            (
                "/api/exports/daily-plans",
                {"from": self.day_from, "to": self.day_to},
            ),
            (
                "/api/exports/weekly-plans",
                {"from": "2026-08-10", "to": "2026-08-14"},
            ),
        ):
            with self.subTest(path=path):
                status, _, body = self.admin.post(path, payload)
                self.assertEqual(status, 422)
                self.assertEqual(
                    json.loads(body)["error"]["code"], "VALIDATION_ERROR"
                )
        self.assertEqual(self.export_records(), [])

    def test_admin_range_export_with_explicit_class(self):
        status, _, payload = self.admin.post(
            "/api/exports/daily-plans",
            {"from": self.day_from, "to": self.day_to, "class_id": CLASS_ID},
        )
        self.assertEqual(status, 200)
        self.assertIn("矩阵主题", self.doc_document(payload))

    def test_admin_wrong_class_daily_range_is_404_no_match(self):
        status, _, payload = self.admin.post(
            "/api/exports/daily-plans",
            {"from": self.day_from, "to": self.day_to,
             "class_id": OTHER_CLASS_ID},
        )
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(payload)["error"]["code"], "EXPORT_NO_MATCH")
        self.assertEqual(self.export_records(), [])

    def test_admin_wrong_class_weekly_single_is_404_plan_not_found(self):
        result = create_weekly(self.SessionLocal, OWNER, week=2)
        confirm_weekly(
            self.SessionLocal,
            OWNER,
            result.plan.id,
            expected_draft_version=result.draft.version,
        )
        status, _, payload = self.admin.post(
            "/api/exports/weekly-plans",
            {"plan_id": result.plan.id, "class_id": OTHER_CLASS_ID},
        )
        self.assertEqual(status, 404)
        self.assertEqual(
            json.loads(payload)["error"]["code"], "WEEKLY_PLAN_NOT_FOUND"
        )


# ---------------------------------------------------------------------------
# daily 409 ack loop across real requests and real concurrent saves
# ---------------------------------------------------------------------------


class DailyAckLoopTests(I5ExportIntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.days = self.teaching_days(2)
        for day in self.days:
            create_daily(self.SessionLocal, OWNER, day, adopted_content={})

    def payload(self):
        return {"from": self.days[0].isoformat(), "to": self.days[-1].isoformat()}

    def test_missing_plan_first_request_is_409_with_facts(self):
        status, _, body = self.owner.post(
            "/api/exports/daily-plans", self.payload()
        )
        error = json.loads(body)["error"]
        self.assertEqual(status, 409)
        self.assertEqual(error["code"], "EXPORT_ACK_REQUIRED")
        self.assertEqual(error["reason"], "missing")
        self.assertTrue(error["facts"])
        self.assertIn("expected_context", error)
        dates = {entry["plan_date"] for entry in error["facts"]}
        self.assertEqual(dates, {day.isoformat() for day in self.days})
        self.assertEqual(self.export_records(), [])

    def test_matching_context_then_success(self):
        first = self.owner.post("/api/exports/daily-plans", self.payload())
        error = json.loads(first[2])["error"]
        retry = dict(self.payload())
        retry.update(ack_missing=True, expected_context=error["expected_context"])
        status, _, payload = self.owner.post("/api/exports/daily-plans", retry)
        self.assertEqual(status, 200)
        document = self.doc_document(payload)
        self.assertIn("小班甲", document)
        # Exactly one audit record, and no plan rows touched by the loop.
        self.assertEqual(len(self.export_records(class_id=CLASS_ID)), 1)
        self.assertEqual(self.count("daily_plans"), 2)

    def test_retry_after_version_change_reprompts_even_when_missing_shrinks(self):
        first = self.owner.post("/api/exports/daily-plans", self.payload())
        error = json.loads(first[2])["error"]
        plan_row = self.daily_plan_row(self.days[0])
        # Fill everything in the first plan: the missing list shrinks for
        # that date, but the pinned versions advanced -> the old echo must
        # be rejected with context_changed (spec §11.8 option B).
        save_daily(
            self.SessionLocal,
            OWNER,
            plan_row.id,
            plan_row.current_content_version,
            adopted_content=full_day_content("补全后的主题"),
        )
        stale = dict(self.payload())
        stale.update(ack_missing=True, expected_context=error["expected_context"])
        status, _, body = self.owner.post("/api/exports/daily-plans", stale)
        error = json.loads(body)["error"]
        self.assertEqual(status, 409)
        self.assertEqual(error["reason"], "context_changed")
        self.assertNotIn(
            self.days[0].isoformat(),
            [entry["plan_date"] for entry in error["facts"]],
        )
        self.assertEqual(self.export_records(), [])

        fresh = dict(self.payload())
        fresh.update(ack_missing=True, expected_context=error["expected_context"])
        status, _, payload = self.owner.post("/api/exports/daily-plans", fresh)
        self.assertEqual(status, 200)
        self.assertEqual(len(self.export_records(class_id=CLASS_ID)), 1)

    def test_client_forged_facts_are_not_authority(self):
        first = self.owner.post("/api/exports/daily-plans", self.payload())
        error = json.loads(first[2])["error"]
        tampered = dict(error["expected_context"])
        tampered["missing_count"] = 0
        retry = dict(self.payload())
        retry.update(ack_missing=True, expected_context=tampered)
        status, _, body = self.owner.post("/api/exports/daily-plans", retry)
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body)["error"]["reason"], "context_changed")


# ---------------------------------------------------------------------------
# weekly export: range / single selection semantics
# ---------------------------------------------------------------------------


class WeeklySelectionTests(I5ExportIntegrationTestCase):
    def test_range_excludes_unconfirmed_and_maps_whole_weeks(self):
        for week, theme in ((2, "第2周主题"), (3, None), (4, "第4周主题")):
            result = create_weekly(
                self.SessionLocal, OWNER, week=week, theme=theme
            )
            if theme is not None:
                confirm_weekly(
                    self.SessionLocal,
                    OWNER,
                    result.plan.id,
                    expected_draft_version=result.draft.version,
                )
        # Weeks 2-4 intersect the range; only the two confirmed survive.
        status, _, payload = self.owner.post(
            "/api/exports/weekly-plans",
            {"from": "2026-08-10", "to": "2026-08-28"},
        )
        self.assertEqual(status, 200)
        document = self.doc_document(payload)
        self.assertIn("第2周主题", document)
        self.assertIn("第4周主题", document)
        self.assertNotIn("第3周主题", document)  # unconfirmed excluded
        self.assertEqual(len(self.export_records(class_id=CLASS_ID)), 1)

    def test_range_no_match_when_only_unconfirmed_plans(self):
        create_weekly(self.SessionLocal, OWNER, week=2)
        status, _, payload = self.owner.post(
            "/api/exports/weekly-plans",
            {"from": "2026-08-10", "to": "2026-08-14"},
        )
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(payload)["error"]["code"], "EXPORT_NO_MATCH")
        self.assertEqual(self.export_records(), [])

    def test_single_never_downloads_an_unconfirmed_draft(self):
        result = create_weekly(self.SessionLocal, OWNER, week=2)
        save_weekly(
            self.SessionLocal,
            OWNER,
            result.plan.id,
            result.draft.version,
            patch={"weekly_columns": {"key_week_focus": "未确认草稿重点"}},
        )
        status, _, payload = self.owner.post(
            "/api/exports/weekly-plans", {"plan_id": result.plan.id}
        )
        self.assertEqual(status, 404)
        self.assertEqual(
            json.loads(payload)["error"]["code"], "CONFIRMATION_NOT_FOUND"
        )
        self.assertNotIn("未确认草稿重点".encode("utf-8"), payload)


class WeeklyPinnedCopyTests(I5ExportIntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.confirmed = create_weekly(
            self.SessionLocal, OWNER, week=2, theme="确认时主题"
        )
        confirm_weekly(
            self.SessionLocal,
            OWNER,
            self.confirmed.plan.id,
            expected_draft_version=self.confirmed.draft.version,
        )

    def test_single_current_pointer_ignores_recorded_draft_change(self):
        save_weekly(
            self.SessionLocal,
            OWNER,
            self.confirmed.plan.id,
            self.confirmed.draft.version,
            patch={"weekly_columns": {"key_week_focus": "草稿新重点"}},
        )
        status, headers, payload = self.owner.post(
            "/api/exports/weekly-plans", {"plan_id": self.confirmed.plan.id}
        )
        self.assertEqual(status, 200)
        document = self.doc_document(payload)
        self.assertIn("确认时主题", document)
        self.assertNotIn("草稿新重点", document)
        self.assertIn(
            "draft_ahead", headers.header("X-Export-Warnings") or ""
        )

    def test_single_explicit_history_version_warns_superseded(self):
        save_weekly(
            self.SessionLocal,
            OWNER,
            self.confirmed.plan.id,
            self.confirmed.draft.version,
            patch={"weekly_columns": {"key_week_focus": "V2 重点"}},
        )
        confirm_weekly(
            self.SessionLocal,
            OWNER,
            self.confirmed.plan.id,
            expected_draft_version=self.confirmed.draft.version + 1,
        )
        status, headers, payload = self.owner.post(
            "/api/exports/weekly-plans",
            {"plan_id": self.confirmed.plan.id, "confirmed_version": 1},
        )
        self.assertEqual(status, 200)
        document = self.doc_document(payload)
        self.assertIn("确认时主题", document)
        self.assertNotIn("V2 重点", document)
        header = headers.header("X-Export-Warnings") or ""
        self.assertIn("confirmed_not_latest", header)
        self.assertIn("superseded", header)
        # The warning set is bounded/deduplicated even with many reasons.
        self.assertLessEqual(len(header), 200)

    def test_files_are_time_point_copies_between_exports(self):
        first = self.owner.post(
            "/api/exports/weekly-plans", {"plan_id": self.confirmed.plan.id}
        )
        self.assertEqual(first[0], 200)
        save_weekly(
            self.SessionLocal,
            OWNER,
            self.confirmed.plan.id,
            self.confirmed.draft.version,
            patch={"weekly_columns": {"key_week_focus": "后到的草稿"}},
        )
        second = self.owner.post(
            "/api/exports/weekly-plans", {"plan_id": self.confirmed.plan.id}
        )
        self.assertEqual(second[0], 200)
        for document in (self.doc_document(first[2]), self.doc_document(second[2])):
            self.assertIn("确认时主题", document)
            self.assertNotIn("后到的草稿", document)


# ---------------------------------------------------------------------------
# consistency during export (real concurrent writes on a second connection)
# ---------------------------------------------------------------------------


class ConsistencyDuringExportTests(I5ExportIntegrationTestCase):
    def test_daily_export_pins_the_read_snapshot(self):
        days = self.teaching_days(2)
        for day in days:
            create_daily(
                self.SessionLocal,
                OWNER,
                day,
                adopted_content=full_day_content("导出前主题"),
            )
        plan_row = self.daily_plan_row(days[0])

        original = export_read_service.prepare_daily_export

        def racing(db, **kwargs):
            bundle = original(db, **kwargs)
            save_daily(
                self.SessionLocal,
                OWNER,
                plan_row.id,
                plan_row.current_content_version,
                adopted_content=full_day_content("并发赶来的新主题"),
            )
            return bundle

        with mock.patch.object(
            export_router.export_read, "prepare_daily_export", new=racing
        ):
            status, _, payload = self.owner.post(
                "/api/exports/daily-plans",
                {"from": days[0].isoformat(), "to": days[-1].isoformat()},
            )
        self.assertEqual(status, 200)
        document = self.doc_document(payload)
        self.assertIn("导出前主题", document)
        self.assertNotIn("并发赶来的新主题", document)
        # The concurrent save itself really happened.
        fresh = self.daily_plan_row(days[0])
        self.assertEqual(
            fresh.current_content_version,
            plan_row.current_content_version + 1,
        )

    def test_single_weekly_export_pins_the_confirmation_snapshot(self):
        confirmed = create_weekly(
            self.SessionLocal, OWNER, week=2, theme="并发前主题"
        )
        confirm_weekly(
            self.SessionLocal,
            OWNER,
            confirmed.plan.id,
            expected_draft_version=confirmed.draft.version,
        )

        original = export_read_service.read_week_days

        def racing(db, term, week_number):
            # Mid-request: another writer advances the draft and confirms V2.
            save_weekly(
                self.SessionLocal,
                OWNER,
                confirmed.plan.id,
                confirmed.draft.version,
                patch={"weekly_columns": {"key_week_focus": "并发草稿重点"}},
            )
            confirm_weekly(
                self.SessionLocal,
                OWNER,
                confirmed.plan.id,
                expected_draft_version=confirmed.draft.version + 1,
            )
            return original(db, term, week_number)

        with mock.patch.object(
            export_router.export_read, "read_week_days", new=racing
        ):
            status, headers, payload = self.owner.post(
                "/api/exports/weekly-plans", {"plan_id": confirmed.plan.id}
            )
        self.assertEqual(status, 200)
        document = self.doc_document(payload)
        self.assertIn("并发前主题", document)
        self.assertNotIn("并发草稿重点", document)
        # The whole request still read the pre-commit consistent view: the
        # request-time pointer never produced the new superseded reason.
        warnings = headers.header("X-Export-Warnings") or "[]"
        self.assertNotIn("superseded", warnings)
        self.assertNotIn("并发赶来的新主题", document)


# ---------------------------------------------------------------------------
# plan-count limits on real selections
# ---------------------------------------------------------------------------


class PlanLimitTests(I5ExportIntegrationTestCase):
    def test_daily_32_plans_is_422_and_31_plans_export(self):
        days = self.teaching_days(32)
        for index, day in enumerate(days):
            create_daily(
                self.SessionLocal,
                OWNER,
                day,
                adopted_content=full_day_content(f"主题第{index + 1}天"),
            )
        status, _, payload = self.owner.post(
            "/api/exports/daily-plans",
            {"from": days[0].isoformat(), "to": days[31].isoformat()},
        )
        self.assertEqual(status, 422)
        error = json.loads(payload)["error"]
        self.assertEqual(error["code"], "EXPORT_RANGE_TOO_LARGE")
        self.assertEqual(error["limit"], 31)
        self.assertEqual(error["selected_count"], 32)
        self.assertEqual(self.export_records(), [])

        status, _, payload = self.owner.post(
            "/api/exports/daily-plans",
            {"from": days[0].isoformat(), "to": days[30].isoformat()},
        )
        self.assertEqual(status, 200)
        self.assertIn("主题第", self.doc_document(payload))
        self.assertEqual(len(self.export_records(class_id=CLASS_ID)), 1)

    def test_weekly_9_confirmed_plans_is_422(self):
        for week in range(1, 10):
            result = create_weekly(self.SessionLocal, OWNER, week=week)
            confirm_weekly(
                self.SessionLocal,
                OWNER,
                result.plan.id,
                expected_draft_version=result.draft.version,
            )
        status, _, payload = self.owner.post(
            "/api/exports/weekly-plans",
            {"from": TERM_START.isoformat(), "to": TERM_END.isoformat()},
        )
        self.assertEqual(status, 422)
        error = json.loads(payload)["error"]
        self.assertEqual(error["code"], "EXPORT_RANGE_TOO_LARGE")
        self.assertEqual(error["limit"], 8)
        self.assertEqual(error["selected_count"], 9)
        self.assertEqual(self.export_records(), [])


# ---------------------------------------------------------------------------
# audit ordering / zero business writes
# ---------------------------------------------------------------------------


class AuditOrderingTests(I5ExportIntegrationTestCase):
    BUSINESS_TABLES = (
        "daily_plans",
        "daily_plan_contents",
        "weekly_plans",
        "weekly_plan_contents",
        "weekly_plan_confirmed_contents",
        "weekly_plan_sync_states",
    )

    def setUp(self):
        super().setUp()
        self.day = self.teaching_days(1)[0]
        create_daily(
            self.SessionLocal,
            OWNER,
            self.day,
            adopted_content=full_day_content("审计主题"),
        )

    def business_counts(self):
        return {t: self.count(t) for t in self.BUSINESS_TABLES}

    def one_daily(self, **payload):
        base = {"from": self.day.isoformat(), "to": self.day.isoformat()}
        base.update(payload)
        return self.owner.post("/api/exports/daily-plans", base)

    def test_success_writes_one_class_record_zero_business_rows(self):
        before = self.business_counts()
        status, _, payload = self.one_daily()
        self.assertEqual(status, 200)
        self.assertEqual(self.business_counts(), before)
        records = self.export_records(class_id=CLASS_ID)
        self.assertEqual(len(records), 1)
        record = records[0]
        operator_id, operator_type, action, target_type, target_id = record[:5]
        version_after, account_id, account_version = record[5:]
        self.assertEqual(operator_id, OWNER["id"])
        self.assertEqual(operator_type, "account")
        self.assertEqual(action, "export_word")
        self.assertEqual(target_type, "class")
        self.assertEqual(target_id, CLASS_ID)
        self.assertIsNone(version_after)
        self.assertIsNone(account_id)
        self.assertIsNone(account_version)

    def test_generation_failure_writes_no_record(self):
        before = self.business_counts()
        with mock.patch.object(
            word_export_docx,
            "generate_export_docx",
            side_effect=WordTemplateError("被阻断的模板资产"),
        ):
            status, _, payload = self.one_daily()
        self.assertEqual(status, 503)
        self.assertEqual(
            json.loads(payload)["error"]["code"], "EXPORT_UNAVAILABLE"
        )
        self.assertEqual(self.export_records(), [])
        self.assertEqual(self.business_counts(), before)

    def test_audit_record_failure_leaves_no_file_and_no_record(self):
        before = self.business_counts()
        with mock.patch.object(
            auth_service,
            "record_operation",
            side_effect=RuntimeError("审计写入被阻断"),
        ):
            status, _, payload = self.one_daily()
        self.assertEqual(status, 503)
        self.assertEqual(
            json.loads(payload)["error"]["code"], "SERVICE_UNAVAILABLE"
        )
        self.assertEqual(self.export_records(), [])
        self.assertEqual(self.business_counts(), before)

    def test_commit_failure_leaves_no_file_and_no_record(self):
        before = self.business_counts()
        with mock.patch.object(
            Session, "commit", side_effect=RuntimeError("提交被阻断")
        ):
            status, _, payload = self.one_daily()
        self.assertEqual(status, 503)
        self.assertEqual(
            json.loads(payload)["error"]["code"], "SERVICE_UNAVAILABLE"
        )
        self.assertEqual(self.export_records(), [])
        self.assertEqual(self.business_counts(), before)

    def test_repeated_exports_each_write_their_own_record(self):
        first = self.one_daily()
        self.assertEqual(first[0], 200)
        second = self.one_daily()
        self.assertEqual(second[0], 200)
        self.assertEqual(len(self.export_records(class_id=CLASS_ID)), 2)

    def test_delivered_bytes_are_a_valid_zip_with_content(self):
        status, _, payload = self.one_daily()
        self.assertEqual(status, 200)
        document = self.doc_document(payload)  # testzip + member read
        self.assertIn("审计主题", document)
        self.assertIn("小班甲", document)


if __name__ == "__main__":
    unittest.main()
