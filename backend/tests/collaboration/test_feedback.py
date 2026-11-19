"""In-app feedback slice: migration contract, settings wiring and service.

Service-level tests run against an in-memory SQLite database (the ORM is
dialect-agnostic; the production database remains MySQL 8.4 and its
authoritative DDL is the migration file).  Nothing here touches a real
secret, the real teacher data or the network.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.dialects.mysql import dialect as mysql_dialect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateTable

from app.collaboration.config import CollaborationSettings
from app.collaboration.errors import CollaborationError
from app.collaboration.feedback_models import (
    FEEDBACK_STATUSES,
    FeedbackSubmission,
)
from app.collaboration.feedback_service import (
    FeedbackRateLimiter,
    content_fingerprint,
    digest_feedback_code,
    list_feedback,
    rate_limiter,
    submit_feedback,
    update_feedback_status,
)

BACKEND = Path(__file__).resolve().parents[2]
MIGRATION = BACKEND / "migrations_collaboration" / "mysql" / "0007_online_feedback.sql"

SYNTHETIC_PEPPER = "synthetic-feedback-pepper-0123456789abcdef"
SYNTHETIC_PREVIEW = "synthetic-feedback-preview-0123456789abcdef"
SYNTHETIC_CODE = "synthetic-feedback-code-2026"


def _settings(code: str = SYNTHETIC_CODE) -> CollaborationSettings:
    return CollaborationSettings(
        database_url="mysql+pymysql://u:p@localhost:3306/collab_test",
        token_pepper=SYNTHETIC_PEPPER,
        preview_secret=SYNTHETIC_PREVIEW,
        feedback_code=code,
    )


class FeedbackStaticContractTests(unittest.TestCase):
    def test_migration_is_explicit_and_bounded(self):
        sql = MIGRATION.read_text(encoding="utf-8")
        upper = sql.upper()
        self.assertNotIn("CREATE DATABASE", upper)
        self.assertNotIn("CREATE SCHEMA", upper)
        self.assertNotIn("DROP TABLE", upper)
        self.assertNotRegex(sql, r"(?im)^\s*USE\s+")
        self.assertEqual(sql.count("CREATE TABLE"), 1)
        self.assertEqual(sql.count("ENGINE=InnoDB"), 1)
        for marker in (
            "CHAR(32)",
            "CHAR_LENGTH",
            "DATETIME(6)",
            "UNIQUE KEY uq_feedback_request_id (request_id)",
            "CONSTRAINT fk_feedback_handled_by_admin FOREIGN KEY (handled_by_admin_id)",
            "REFERENCES admin_users(id)",
            "status IN ('new', 'processing', 'resolved')",
            "CURRENT_TIMESTAMP(6)",
            # The apply notes must name the deployment's feedback-code
            # environment variable and the required database privileges.
            "KGM_COLLAB_FEEDBACK_CODE",
            "privileges",
        ):
            self.assertIn(marker, sql)

    def test_model_ddl_targets_mysql(self):
        dialect = mysql_dialect()
        ddl = str(
            CreateTable(FeedbackSubmission.__table__).compile(dialect=dialect)
        )
        self.assertIn("ENGINE=InnoDB", ddl)
        self.assertIn("DATETIME(6)", ddl)
        self.assertIn("ascii_bin", ddl)
        self.assertIn("UNIQUE", ddl)

    def test_settings_feedback_code_is_optional_and_hidden_from_repr(self):
        settings = _settings(code="")
        settings.validate()
        self.assertEqual(settings.feedback_code, "")
        with_code = _settings()
        self.assertNotIn(SYNTHETIC_CODE, repr(with_code))

    def test_from_env_reads_feedback_code(self):
        import os

        clean = {
            key: ""
            for key in (
                "KGM_COLLAB_DATABASE_URL",
                "KGM_COLLAB_TOKEN_PEPPER",
                "KGM_COLLAB_PREVIEW_SECRET",
                "KGM_COLLAB_FEEDBACK_CODE",
            )
        }
        with patch.dict(os.environ, clean, clear=False):
            os.environ["KGM_COLLAB_DATABASE_URL"] = (
                "mysql+pymysql://u:p@localhost/db"
            )
            os.environ["KGM_COLLAB_TOKEN_PEPPER"] = SYNTHETIC_PEPPER
            os.environ["KGM_COLLAB_PREVIEW_SECRET"] = SYNTHETIC_PREVIEW
            os.environ["KGM_COLLAB_FEEDBACK_CODE"] = "  spaced-code  "
            settings = CollaborationSettings.from_env()
            self.assertEqual(settings.feedback_code, "spaced-code")


class FeedbackServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
        )
        self.addCleanup(engine.dispose)
        # Only the two tables the feedback slice touches are created, from
        # their ORM definitions (dialect-agnostic by design); the rest of the
        # collaboration metadata stays MySQL-only and is never created here.
        from app.collaboration.admin_models import AdminUser

        AdminUser.__table__.create(engine)
        FeedbackSubmission.__table__.create(engine)
        self.session_factory = sessionmaker(
            bind=engine, autoflush=False, expire_on_commit=False
        )
        self.settings = _settings()
        # One isolated limiter per test: the module-level singleton is never
        # shared across test cases or with a running service.
        self._original_limiter = rate_limiter
        self.limiter = FeedbackRateLimiter(max_per_window=5)
        import app.collaboration.feedback_service as feedback_service

        feedback_service.rate_limiter = self.limiter

    def tearDown(self) -> None:
        import app.collaboration.feedback_service as feedback_service

        feedback_service.rate_limiter = self._original_limiter

    def submit(self, **overrides):
        payload = {
            "request_id": uuid4(),
            "code": SYNTHETIC_CODE,
            "content": "游戏观察导出在周五崩溃了",
            "contact": None,
            "app_version": "0.1.0-test",
            "client_ip": "127.0.0.1",
        }
        payload.update(overrides)
        with self.session_factory() as session:
            return submit_feedback(session, self.settings, **payload)

    def list_items(self, **kwargs):
        with self.session_factory() as session:
            return list_feedback(session, **kwargs)

    def test_submit_creates_one_row_and_returns_receipt(self):
        receipt = self.submit()
        self.assertFalse(receipt.replayed)
        with self.session_factory() as session:
            rows = list(session.scalars(select(FeedbackSubmission)).all())
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.request_id, receipt.request_id)
        self.assertEqual(row.status, "new")
        self.assertEqual(row.app_version, "0.1.0-test")
        self.assertIsNone(row.contact)
        # The plaintext code is never stored.
        self.assertEqual(
            row.feedback_code_hash,
            digest_feedback_code(self.settings, SYNTHETIC_CODE),
        )
        self.assertNotIn(SYNTHETIC_CODE, row.feedback_code_hash)

    def test_same_request_id_replays_without_duplicate(self):
        request_id = uuid4()
        first = self.submit(request_id=request_id)
        replay = self.submit(request_id=request_id)
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.submission_id, first.submission_id)
        self.assertEqual(replay.received_at, first.received_at)
        with self.session_factory() as session:
            count = len(list(session.scalars(select(FeedbackSubmission)).all()))
        self.assertEqual(count, 1)

    def test_same_request_id_with_other_content_conflicts(self):
        request_id = uuid4()
        self.submit(request_id=request_id)
        with self.assertRaises(CollaborationError) as conflict:
            self.submit(request_id=request_id, content="不同的内容")
        self.assertEqual(conflict.exception.code, "REQUEST_CONFLICT")

    def test_invalid_code_is_rejected_uniformly(self):
        for code in ("wrong-code", "", "x" * 600):
            with self.subTest(code=code[:8]):
                with self.assertRaises(CollaborationError) as invalid:
                    self.submit(code=code)
                self.assertEqual(invalid.exception.code, "FEEDBACK_CODE_INVALID")

    def test_unconfigured_code_disables_the_entry(self):
        with self.session_factory() as session:
            with self.assertRaises(CollaborationError) as disabled:
                submit_feedback(
                    session,
                    _settings(code=""),
                    request_id=uuid4(),
                    code=SYNTHETIC_CODE,
                    content="内容",
                    contact=None,
                    app_version=None,
                    client_ip="127.0.0.1",
                )
        self.assertEqual(disabled.exception.code, "FEEDBACK_NOT_CONFIGURED")

    def test_input_bounds_are_enforced(self):
        # Each case uses its own client IP so the shared per-IP rate limit
        # never masks the validation error under test.
        cases = [
            {"content": "   "},
            {"content": "x" * 4001},
            {"content": "a\x00b"},
            {"contact": "x" * 201},
            {"contact": "a\x00b"},
            {"app_version": "x" * 101},
        ]
        for index, overrides in enumerate(cases):
            with self.subTest(**overrides):
                with self.assertRaises(CollaborationError) as invalid:
                    self.submit(client_ip=f"10.1.0.{index}", **overrides)
                self.assertEqual(invalid.exception.code, "FEEDBACK_INVALID")

    def test_contact_and_version_are_trimmed_and_optional(self):
        receipt = self.submit(
            contact="  王老师 wl@example.com  ", app_version=" 0.1.0-test "
        )
        with self.session_factory() as session:
            row = session.scalars(
                select(FeedbackSubmission).where(
                    FeedbackSubmission.id == receipt.submission_id
                )
            ).one()
        self.assertEqual(row.contact, "王老师 wl@example.com")
        self.assertEqual(row.app_version, "0.1.0-test")

    def test_rate_limit_counts_attempts_before_code_check(self):
        # Invalid-code attempts are counted first: five uniform rejections,
        # then the same-shaped sixth attempt is rate limited.
        for index in range(5):
            with self.subTest(index=index):
                with self.assertRaises(CollaborationError) as invalid:
                    self.submit(code=f"wrong-{index}")
                self.assertEqual(invalid.exception.code, "FEEDBACK_CODE_INVALID")
        with self.assertRaises(CollaborationError) as limited:
            self.submit(code="wrong-6")
        self.assertEqual(limited.exception.code, "FEEDBACK_RATE_LIMITED")
        self.assertGreaterEqual(
            limited.exception.details.get("retry_after_seconds", 0), 1
        )

    def test_rate_limiter_is_bounded_in_memory(self):
        # A new IP beyond the tracking cap evicts the oldest entry: memory
        # stays bounded and the limiter never locks out brand-new clients.
        limiter = FeedbackRateLimiter(
            window_seconds=60,
            max_per_window=1,
            max_tracked_ips=2,
            clock=lambda: 0.0,
        )
        limiter.check("ip-1")
        limiter.check("ip-2")
        limiter.check("ip-3")  # evicts ip-1, allowed
        limiter.check("ip-1")  # re-tracked fresh after eviction, allowed
        self.assertLessEqual(len(limiter._hits), 2)

    def test_rate_limiter_window_expiry(self):
        now = [100.0]
        limiter = FeedbackRateLimiter(
            window_seconds=60,
            max_per_window=1,
            clock=lambda: now[0],
        )
        limiter.check("ip-1")
        now[0] = 160.0
        limiter.check("ip-1")  # window expired: allowed again

    def test_fingerprint_covers_all_submitted_fields(self):
        request_id = uuid4()
        base = content_fingerprint(
            self.settings, request_id, "内容", None, "0.1.0"
        )
        variants = [
            content_fingerprint(self.settings, request_id, "内容二", None, "0.1.0"),
            content_fingerprint(self.settings, request_id, "内容", "联系", "0.1.0"),
            content_fingerprint(self.settings, request_id, "内容", None, "0.1.1"),
            content_fingerprint(self.settings, uuid4(), "内容", None, "0.1.0"),
        ]
        for variant in variants:
            with self.subTest():
                self.assertNotEqual(base, variant)

    def test_admin_list_orders_and_filters(self):
        self.submit(content="一条反馈")
        self.submit(content="另一条反馈")
        page = self.list_items()
        self.assertEqual(len(page.items), 2)
        self.assertEqual(page.total, 2)
        # Newest first: the head item carries the latest created_at.
        self.assertGreaterEqual(page.items[0].created_at, page.items[-1].created_at)
        self.assertEqual(len(self.list_items(status="new").items), 2)
        self.assertEqual(len(self.list_items(status="resolved").items), 0)
        first_page = self.list_items(limit=1)
        self.assertEqual(len(first_page.items), 1)
        self.assertEqual(first_page.total, 2)
        self.assertEqual(first_page.offset, 0)
        second_page = self.list_items(offset=1, limit=1)
        self.assertEqual(len(second_page.items), 1)
        self.assertEqual(second_page.total, 2)
        self.assertNotEqual(
            first_page.items[0].submission_id, second_page.items[0].submission_id
        )

    def test_admin_status_update_flow_and_conflicts(self):
        receipt = self.submit()
        admin_id = uuid4()
        with self.session_factory() as session:
            item = update_feedback_status(
                session,
                admin_id=admin_id,
                submission_id=receipt.submission_id,
                expected_status="new",
                new_status="processing",
            )
        self.assertEqual(item.status, "processing")
        self.assertIsNotNone(item.handled_at)
        # Same-target retry after a lost response is idempotent.
        with self.session_factory() as session:
            again = update_feedback_status(
                session,
                admin_id=admin_id,
                submission_id=receipt.submission_id,
                expected_status="new",
                new_status="processing",
            )
        self.assertEqual(again.status, "processing")
        with self.session_factory() as session:
            resolved = update_feedback_status(
                session,
                admin_id=admin_id,
                submission_id=receipt.submission_id,
                expected_status="processing",
                new_status="resolved",
            )
        self.assertEqual(resolved.status, "resolved")
        # Stale baseline is a controlled conflict.
        with self.session_factory() as session:
            with self.assertRaises(CollaborationError) as conflict:
                update_feedback_status(
                    session,
                    admin_id=admin_id,
                    submission_id=receipt.submission_id,
                    expected_status="new",
                    new_status="processing",
                )
        self.assertEqual(conflict.exception.code, "FEEDBACK_STATUS_CONFLICT")
        self.assertEqual(
            conflict.exception.details.get("current_status"), "resolved"
        )
        with self.session_factory() as session:
            with self.assertRaises(CollaborationError) as unknown_status:
                update_feedback_status(
                    session,
                    admin_id=admin_id,
                    submission_id=receipt.submission_id,
                    expected_status="resolved",
                    new_status="closed",
                )
        self.assertEqual(unknown_status.exception.code, "FEEDBACK_INVALID")
        with self.session_factory() as session:
            with self.assertRaises(CollaborationError) as missing:
                update_feedback_status(
                    session,
                    admin_id=admin_id,
                    submission_id=uuid4(),
                    expected_status="new",
                    new_status="processing",
                )
        self.assertEqual(
            missing.exception.code, "FEEDBACK_SUBMISSION_NOT_FOUND"
        )


if __name__ == "__main__":
    unittest.main()
