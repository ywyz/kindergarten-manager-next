"""Same-class promotion contract tests without a real database.

The local suite uses an isolated in-memory SQLite schema only to exercise
service transactions and name resolution.  A separate opt-in MySQL class
runs the same service on an explicit ``KGM_COLLAB_TEST_DATABASE_URL`` after
0001-0003 have been applied; it never creates a database or tables.
"""

from __future__ import annotations

import os
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.dialects.mysql import dialect as mysql_dialect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable

from app.collaboration.app import create_collaboration_app
from app.collaboration.class_promotion_models import (
    ClassPromotionHistory,
    ClassPromotionOperation,
    ClassPromotionState,
    CollaborationTerm,
    make_class_name,
    resolve_class_name_at_term,
    resolve_grade_at_term,
    shanghai_today,
)
from app.collaboration.class_promotion_service import (
    get_promotion,
    query_promotion_operation,
    submit_promotion,
)
from app.collaboration.config import CollaborationSettings
from app.collaboration.db import create_collaboration_engine
from app.collaboration.errors import CollaborationError
from app.collaboration.models import (
    Classroom,
    School,
    Teacher,
    TeacherClassMembership,
)
from app.collaboration.provision import _create_term, _register_class
from app.collaboration.security import TeacherPrincipal
from app.collaboration.service import current_membership, list_classes, select_class

PEPPER = "synthetic-promotion-pepper-0123456789"
PREVIEW = "synthetic-promotion-preview-0123456789"


def _settings(url: str) -> CollaborationSettings:
    return CollaborationSettings(
        database_url=url,
        token_pepper=PEPPER,
        preview_secret=PREVIEW,
    )


def _principal(
    teacher_id: UUID, school_id: UUID, name: str = "合成教师"
) -> TeacherPrincipal:
    return TeacherPrincipal(
        teacher_id=teacher_id,
        school_id=school_id,
        display_name=name,
        school_name="合成幼儿园",
        token_id=uuid4(),
    )


def _create_sqlite_schema(engine) -> None:
    tables = (
        School.__table__,
        Classroom.__table__,
        Teacher.__table__,
        TeacherClassMembership.__table__,
        CollaborationTerm.__table__,
        ClassPromotionState.__table__,
        ClassPromotionHistory.__table__,
        ClassPromotionOperation.__table__,
    )
    with engine.begin() as connection:
        for table in tables:
            ddl = str(CreateTable(table).compile(dialect=engine.dialect))
            # SQLite has no CURRENT_TIMESTAMP(6) spelling; business values in
            # these tests are supplied explicitly by the service/session.
            ddl = ddl.replace("CURRENT_TIMESTAMP(6)", "CURRENT_TIMESTAMP")
            connection.exec_driver_sql(ddl)


class PromotionSQLiteUnitTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.addCleanup(self.engine.dispose)

        @event.listens_for(self.engine, "connect")
        def _register_char_length(dbapi_connection, _record):
            dbapi_connection.create_function("char_length", 1, len)

        _create_sqlite_schema(self.engine)
        self.Session = sessionmaker(
            bind=self.engine, autoflush=False, expire_on_commit=False
        )
        self.school_id = uuid4()
        self.class_id = uuid4()
        self.teacher_id = uuid4()
        self.other_class_id = uuid4()
        self.other_teacher_id = uuid4()
        self.outsider_id = uuid4()
        today = shanghai_today()
        self.current_term_id = uuid4()
        self.future_term_id = uuid4()
        with self.Session() as session:
            with session.begin():
                session.add(School(id=self.school_id, name="合成幼儿园"))
                session.flush()
                session.add_all(
                    [
                        Classroom(
                            id=self.class_id,
                            school_id=self.school_id,
                            display_name="同名班",
                        ),
                        Classroom(
                            id=self.other_class_id,
                            school_id=self.school_id,
                            display_name="同名班",
                        ),
                        Teacher(
                            id=self.teacher_id,
                            school_id=self.school_id,
                            display_name="合成教师甲",
                            active=True,
                        ),
                        Teacher(
                            id=self.other_teacher_id,
                            school_id=self.school_id,
                            display_name="合成教师乙",
                            active=True,
                        ),
                        Teacher(
                            id=self.outsider_id,
                            school_id=self.school_id,
                            display_name="合成教师丙",
                            active=True,
                        ),
                    ]
                )
                session.flush()
                session.add_all(
                    [
                        TeacherClassMembership(
                            teacher_id=self.teacher_id,
                            school_id=self.school_id,
                            class_id=self.class_id,
                            membership_generation=uuid4(),
                            selected_at=datetime.now(timezone.utc),
                            updated_at=datetime.now(timezone.utc),
                        ),
                        TeacherClassMembership(
                            teacher_id=self.other_teacher_id,
                            school_id=self.school_id,
                            class_id=self.other_class_id,
                            membership_generation=uuid4(),
                            selected_at=datetime.now(timezone.utc),
                            updated_at=datetime.now(timezone.utc),
                        ),
                        CollaborationTerm(
                            id=self.current_term_id,
                            school_id=self.school_id,
                            name="当前学期",
                            start_date=today - timedelta(days=10),
                            end_date=today + timedelta(days=10),
                        ),
                        CollaborationTerm(
                            id=self.future_term_id,
                            school_id=self.school_id,
                            name="将来学期",
                            start_date=today + timedelta(days=30),
                            end_date=today + timedelta(days=120),
                        ),
                        ClassPromotionState(
                            class_id=self.class_id,
                            school_id=self.school_id,
                            class_number=1,
                            base_grade="small",
                            version=1,
                        ),
                        ClassPromotionState(
                            class_id=self.other_class_id,
                            school_id=self.school_id,
                            class_number=2,
                            base_grade="small",
                            version=1,
                        ),
                    ]
                )

    def test_current_name_is_generated_but_future_term_name_is_not_active(self):
        principal = _principal(self.teacher_id, self.school_id)
        with self.Session() as session:
            current = get_promotion(session, principal)
        self.assertEqual(current.class_id, self.class_id)
        self.assertEqual(current.class_name, "小一班")
        self.assertEqual(current.grade, "small")
        self.assertEqual(current.version, 1)
        self.assertEqual(
            [term.term_id for term in current.terms],
            [self.current_term_id, self.future_term_id],
        )

        with self.Session() as session:
            receipt = submit_promotion(
                session,
                principal,
                request_id=uuid4(),
                class_id=self.class_id,
                expected_version=1,
                target_grade="middle",
                effective_term_id=self.future_term_id,
            )
        self.assertEqual(receipt.class_name, "中一班")
        self.assertEqual(receipt.grade, "middle")
        self.assertEqual(receipt.version, 2)
        self.assertFalse(receipt.replayed)

        with self.Session() as session:
            current = get_promotion(session, principal)
            self.assertEqual(current.class_name, "小一班")
            self.assertEqual(current.grade, "small")
            self.assertEqual(current.version, 2)
            self.assertEqual(
                resolve_class_name_at_term(
                    session, self.class_id, self.future_term_id
                ),
                "中一班",
            )
            self.assertEqual(
                resolve_grade_at_term(
                    session, self.class_id, self.future_term_id
                ),
                "middle",
            )
            self.assertEqual(
                resolve_class_name_at_term(
                    session, self.class_id, self.current_term_id
                ),
                "小一班",
            )
            self.assertEqual(
                [item.display_name for item in list_classes(session, principal)],
                ["小一班", "小二班"],
            )
            self.assertEqual(
                current_membership(session, principal).class_name, "小一班"
            )

    def test_current_term_promotion_changes_catalog_and_membership_name(self):
        principal = _principal(self.teacher_id, self.school_id)
        with self.Session() as session:
            receipt = submit_promotion(
                session,
                principal,
                request_id=uuid4(),
                class_id=self.class_id,
                expected_version=1,
                target_grade="middle",
                effective_term_id=self.current_term_id,
            )
        self.assertEqual(receipt.class_name, "中一班")
        with self.Session() as session:
            self.assertEqual(
                get_promotion(session, principal).class_name, "中一班"
            )
        with self.Session() as session:
            membership = select_class(session, principal, self.class_id)
            self.assertEqual(membership.class_name, "中一班")
        with self.Session() as session:
            self.assertEqual(
                current_membership(session, principal).class_name, "中一班"
            )
        with self.Session() as session:
            self.assertEqual(
                [item.display_name for item in list_classes(session, principal)],
                ["中一班", "小二班"],
            )

    def test_same_named_classes_use_stable_id_and_are_not_cross_updated(self):
        principal = _principal(self.teacher_id, self.school_id)
        other_principal = _principal(
            self.other_teacher_id, self.school_id, "合成教师乙"
        )
        with self.Session() as session:
            submit_promotion(
                session,
                principal,
                request_id=uuid4(),
                class_id=self.class_id,
                expected_version=1,
                target_grade="middle",
                effective_term_id=self.current_term_id,
            )
        with self.Session() as session:
            first = get_promotion(session, principal)
            second = get_promotion(session, other_principal)
        self.assertEqual(first.class_id, self.class_id)
        self.assertEqual(second.class_id, self.other_class_id)
        self.assertEqual(first.class_name, "中一班")
        self.assertEqual(second.class_name, "小二班")
        self.assertEqual(first.version, 2)
        self.assertEqual(second.version, 1)

    def test_replay_and_version_conflict_use_request_id_and_class_version(self):
        principal = _principal(self.teacher_id, self.school_id)
        request_id = uuid4()
        with self.Session() as session:
            first = submit_promotion(
                session,
                principal,
                request_id=request_id,
                class_id=self.class_id,
                expected_version=1,
                target_grade="middle",
                effective_term_id=self.current_term_id,
            )
        with self.Session() as session:
            replay = submit_promotion(
                session,
                principal,
                request_id=request_id,
                class_id=self.class_id,
                expected_version=1,
                target_grade="middle",
                effective_term_id=self.current_term_id,
            )
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.version, first.version)
        with self.Session() as session:
            with self.assertRaises(CollaborationError) as stale:
                submit_promotion(
                    session,
                    principal,
                    request_id=uuid4(),
                    class_id=self.class_id,
                    expected_version=1,
                    target_grade="large",
                    effective_term_id=self.future_term_id,
                )
        self.assertEqual(stale.exception.code, "CLASS_PROMOTION_VERSION_CONFLICT")
        self.assertEqual(stale.exception.details["current_version"], 2)
        with self.Session() as session:
            with self.assertRaises(CollaborationError) as conflict:
                submit_promotion(
                    session,
                    principal,
                    request_id=request_id,
                    class_id=self.class_id,
                    expected_version=1,
                    target_grade="large",
                    effective_term_id=self.future_term_id,
                )
        self.assertEqual(conflict.exception.code, "REQUEST_CONFLICT")

    def test_membership_permission_and_invalid_targets(self):
        outsider = _principal(self.outsider_id, self.school_id, "合成教师丙")
        principal = _principal(self.teacher_id, self.school_id)
        with self.Session() as session:
            with self.assertRaises(CollaborationError) as missing:
                get_promotion(session, outsider)
        self.assertEqual(missing.exception.code, "CLASS_NOT_SELECTED")
        with self.Session() as session:
            with self.assertRaises(CollaborationError) as same_grade:
                submit_promotion(
                    session,
                    principal,
                    request_id=uuid4(),
                    class_id=self.class_id,
                    expected_version=1,
                    target_grade="small",
                    effective_term_id=self.current_term_id,
                )
        self.assertEqual(same_grade.exception.code, "INVALID_CLASS_PROMOTION")
        with self.Session() as session:
            with self.assertRaises(CollaborationError) as missing_term:
                submit_promotion(
                    session,
                    principal,
                    request_id=uuid4(),
                    class_id=self.class_id,
                    expected_version=1,
                    target_grade="middle",
                    effective_term_id=uuid4(),
                )
        self.assertEqual(missing_term.exception.code, "TERM_NOT_FOUND")

    def test_get_promotion_reads_state_grade_and_version_in_one_statement(self):
        statements: list[str] = []

        def capture(_conn, _cursor, statement, _parameters, _context, _many):
            statements.append(statement)

        event.listen(self.engine, "before_cursor_execute", capture)
        self.addCleanup(
            event.remove, self.engine, "before_cursor_execute", capture
        )
        with patch(
            "app.collaboration.class_promotion_service.shanghai_today",
            return_value=shanghai_today(),
        ) as today_mock:
            with self.Session() as session:
                current = get_promotion(
                    session,
                    _principal(self.teacher_id, self.school_id),
                )
        self.assertEqual(today_mock.call_count, 1)
        self.assertEqual(current.class_name, "小一班")
        self.assertEqual(current.grade, "small")
        self.assertEqual(current.version, 1)
        snapshot = [
            statement
            for statement in statements
            if "class_promotion_states" in statement.lower()
            and "class_promotion_history" in statement.lower()
        ]
        self.assertEqual(len(snapshot), 1, statements)
        sql = snapshot[0].lower()
        for marker in (
            "teacher_class_memberships",
            "classes",
            "class_promotion_states",
            "class_promotion_history",
            "base_grade",
            "version",
            "start_date",
        ):
            self.assertIn(marker, sql)

    def test_provisioning_commands_register_term_and_fixed_class_number(self):
        today = shanghai_today()
        new_class_id = uuid4()
        with self.Session() as session:
            with session.begin():
                session.add(
                    Classroom(
                        id=new_class_id,
                        school_id=self.school_id,
                        display_name="待登记班",
                    )
                )
        with self.Session() as session:
            term = _create_term(
                session,
                self.school_id,
                "毕业学期",
                (today + timedelta(days=200)).isoformat(),
                (today + timedelta(days=300)).isoformat(),
            )
        self.assertEqual(term["name"], "毕业学期")
        with self.Session() as session:
            registered = _register_class(
                session, new_class_id, "large", 6
            )
        self.assertEqual(registered["class_name"], "大六班")
        self.assertFalse(registered["already_registered"])
        with self.Session() as session:
            again = _register_class(session, new_class_id, "large", 6)
        self.assertTrue(again["already_registered"])
        self.assertEqual(again["class_number"], 6)

    def test_receipt_query_is_read_only_and_unknown_receipt_is_404(self):
        principal = _principal(self.teacher_id, self.school_id)
        request_id = uuid4()
        with self.Session() as session:
            submit_promotion(
                session,
                principal,
                request_id=request_id,
                class_id=self.class_id,
                expected_version=1,
                target_grade="middle",
                effective_term_id=self.current_term_id,
            )
        with self.Session() as session:
            receipt = query_promotion_operation(session, principal, request_id)
        self.assertEqual(receipt.request_id, request_id)
        self.assertFalse(receipt.replayed)
        with self.Session() as session:
            with self.assertRaises(CollaborationError) as missing:
                query_promotion_operation(session, principal, uuid4())
        self.assertEqual(missing.exception.code, "OPERATION_NOT_FOUND")


class PromotionSchemaAndRouteTests(unittest.TestCase):
    def test_0003_is_additive_and_matches_mysql_models(self):
        backend = Path(__file__).resolve().parents[2]
        sql = (
            backend
            / "migrations_collaboration"
            / "mysql"
            / "0003_class_promotion.sql"
        ).read_text(encoding="utf-8")
        upper = sql.upper()
        self.assertEqual(sql.count("CREATE TABLE"), 4)
        self.assertEqual(sql.count("ENGINE=InnoDB"), 4)
        self.assertNotIn("CREATE DATABASE", upper)
        self.assertNotIn("ALTER TABLE", upper)
        self.assertNotIn("DROP TABLE", upper)
        for marker in (
            "terms",
            "class_promotion_states",
            "class_promotion_history",
            "class_promotion_operations",
            "CHAR(32)",
            "DATETIME(6)",
            "ascii_bin",
            "CHAR_LENGTH",
            "STOP",
        ):
            self.assertIn(marker, sql)
        dialect = mysql_dialect()
        for model in (
            CollaborationTerm,
            ClassPromotionState,
            ClassPromotionHistory,
            ClassPromotionOperation,
        ):
            ddl = str(CreateTable(model.__table__).compile(dialect=dialect))
            self.assertIsNone(model.__table__.schema)
            self.assertIn("CHAR(32)", ddl)
            self.assertIn("ENGINE=InnoDB", ddl)

    def test_three_promotion_routes_are_registered(self):
        app = create_collaboration_app(
            _settings(
                "mysql+pymysql://synthetic:synthetic@127.0.0.1:3306/synthetic_collab"
            )
        )
        self.addCleanup(app.state.engine.dispose)
        paths = set(app.openapi()["paths"])
        self.assertIn("/api/collaboration/me/class/promotion", paths)
        self.assertIn(
            "/api/collaboration/me/class/promotion/operations/{request_id}",
            paths,
        )

    def test_name_numbering_is_stable(self):
        self.assertEqual(make_class_name("small", 1), "小一班")
        self.assertEqual(make_class_name("middle", 4), "中四班")
        self.assertEqual(make_class_name("large", 10), "大十班")
        self.assertEqual(make_class_name("large", 21), "大二十一班")


@unittest.skipUnless(
    os.environ.get("KGM_COLLAB_TEST_DATABASE_URL", "").strip(),
    "set KGM_COLLAB_TEST_DATABASE_URL after applying 0001-0003",
)
class PromotionMySQLIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = os.environ["KGM_COLLAB_TEST_DATABASE_URL"].strip()
        cls.settings = _settings(url)
        cls.engine = create_collaboration_engine(cls.settings)
        cls.addClassCleanup(cls.engine.dispose)
        names = set(inspect(cls.engine).get_table_names())
        required = {
            "schools",
            "classes",
            "teachers",
            "teacher_class_memberships",
            "terms",
            "class_promotion_states",
            "class_promotion_history",
            "class_promotion_operations",
        }
        if not required.issubset(names):
            raise AssertionError(
                "apply MySQL 0001-0003 before running promotion integration"
            )
        with cls.engine.connect() as connection:
            version = connection.exec_driver_sql("SELECT VERSION()").scalar_one()
            database = connection.exec_driver_sql("SELECT DATABASE()").scalar_one()
        print(
            f"KGM_PROMOTION_MYSQL_VERSION={version} "
            f"KGM_PROMOTION_MYSQL_DATABASE={database}"
        )
        cls.Session = sessionmaker(
            bind=cls.engine, autoflush=False, expire_on_commit=False
        )

    def test_two_teachers_concurrent_submissions_only_one_advances(self):
        today = shanghai_today()
        school_id = uuid4()
        class_id = uuid4()
        teacher_a = uuid4()
        teacher_b = uuid4()
        term_id = uuid4()
        with self.Session() as session:
            with session.begin():
                session.add(School(id=school_id, name="并发合成园"))
                session.flush()
                session.add(
                    Classroom(
                        id=class_id,
                        school_id=school_id,
                        display_name="并发班",
                    )
                )
                session.add_all(
                    [
                        Teacher(
                            id=teacher_a,
                            school_id=school_id,
                            display_name="并发甲",
                            active=True,
                        ),
                        Teacher(
                            id=teacher_b,
                            school_id=school_id,
                            display_name="并发乙",
                            active=True,
                        ),
                    ]
                )
                session.flush()
                session.add_all(
                    [
                        TeacherClassMembership(
                            teacher_id=teacher_a,
                            school_id=school_id,
                            class_id=class_id,
                            membership_generation=uuid4(),
                            selected_at=datetime.now(timezone.utc),
                            updated_at=datetime.now(timezone.utc),
                        ),
                        TeacherClassMembership(
                            teacher_id=teacher_b,
                            school_id=school_id,
                            class_id=class_id,
                            membership_generation=uuid4(),
                            selected_at=datetime.now(timezone.utc),
                            updated_at=datetime.now(timezone.utc),
                        ),
                        CollaborationTerm(
                            id=term_id,
                            school_id=school_id,
                            name="并发学期",
                            start_date=today - timedelta(days=1),
                            end_date=today + timedelta(days=60),
                        ),
                        ClassPromotionState(
                            class_id=class_id,
                            school_id=school_id,
                            class_number=3,
                            base_grade="small",
                            version=1,
                        ),
                    ]
                )
        principals = [
            _principal(teacher_a, school_id, "并发甲"),
            _principal(teacher_b, school_id, "并发乙"),
        ]
        barrier = threading.Barrier(2)
        results: list[tuple[str, object]] = []

        def worker(principal: TeacherPrincipal) -> None:
            with self.Session() as session:
                barrier.wait()
                try:
                    value = submit_promotion(
                        session,
                        principal,
                        request_id=uuid4(),
                        class_id=class_id,
                        expected_version=1,
                        target_grade="middle",
                        effective_term_id=term_id,
                    )
                    results.append(("ok", value.version))
                except CollaborationError as exc:
                    results.append(("error", exc.code))
                except Exception as exc:  # noqa: BLE001 - diagnostic only
                    results.append(("error", type(exc).__name__))

        threads = [
            threading.Thread(target=worker, args=(principal,))
            for principal in principals
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(len(results), 2, results)
        self.assertEqual(sum(1 for kind, _ in results if kind == "ok"), 1, results)
        self.assertIn(("error", "CLASS_PROMOTION_VERSION_CONFLICT"), results)
