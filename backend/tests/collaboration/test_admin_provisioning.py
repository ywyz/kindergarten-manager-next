"""Administrator provisioning: schools, registered classes, teachers, terms.

The local suite uses only an in-memory SQLite schema with synthetic data.
Every create is replay-safe through an explicit client-supplied entity id:
the same id with the same input returns the committed row (``created=False``)
and never a duplicate, while a different id is a deliberate second row even
with the same display name — including a replacement cohort after promotion
moved the previous cohort up.  The end-to-end test walks the whole chain
from empty data: school, class, two teachers, code issuing, redemption,
same-class selection, the no-term weekly-plan block, term creation and the
shared weekly plan.
"""

from __future__ import annotations

import os
import sys
import threading
import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi import Response
from sqlalchemy import create_engine, delete, event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable

from app.collaboration import admin_api, admin_service, provision
from app.collaboration.admin_models import AdminCode, AdminUser
from app.collaboration.class_promotion_models import (
    ClassPromotionHistory,
    ClassPromotionState,
    CollaborationTerm,
    effective_class_name_now,
    effective_class_names_now,
)
from app.collaboration.class_promotion_service import get_promotion
from app.collaboration.config import CollaborationSettings
from app.collaboration.errors import CollaborationError
from app.collaboration.models import (
    Classroom,
    School,
    Teacher,
    TeacherClassMembership,
    TeacherGameConfig,
    TeacherToken,
)
from app.collaboration.security import authenticate
from app.collaboration.service import (
    get_own_config,
    list_classmates,
    list_classes,
    select_class,
)
from app.collaboration.weekly_plan_models import (
    WeeklyPlanConfirmation,
    WeeklyPlanOperation,
    WeeklyPlanWeek,
)
from app.collaboration.weekly_plan_service import (
    confirm_weekly_plan,
    get_weekly_plan,
    save_weekly_plan,
)

BACKEND = Path(__file__).resolve().parents[2]


def _create_sqlite_schema(engine) -> None:
    tables = (
        School.__table__,
        Classroom.__table__,
        Teacher.__table__,
        TeacherClassMembership.__table__,
        TeacherToken.__table__,
        TeacherGameConfig.__table__,
        CollaborationTerm.__table__,
        ClassPromotionState.__table__,
        ClassPromotionHistory.__table__,
        WeeklyPlanWeek.__table__,
        WeeklyPlanConfirmation.__table__,
        WeeklyPlanOperation.__table__,
        AdminUser.__table__,
        AdminCode.__table__,
    )
    with engine.begin() as connection:
        for table in tables:
            ddl = str(CreateTable(table).compile(dialect=engine.dialect))
            ddl = ddl.replace("CURRENT_TIMESTAMP(6)", "CURRENT_TIMESTAMP")
            connection.exec_driver_sql(ddl)


def _register_sqlite_helpers(dbapi_connection) -> None:
    dbapi_connection.create_function("char_length", 1, len)
    # Real foreign keys, exactly like the deployed MySQL 8.4 schema: a
    # composite child insert whose parent row is missing fails here too.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class AdminProvisioningTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.addCleanup(self.engine.dispose)

        @event.listens_for(self.engine, "connect")
        def _char_length(dbapi_connection, _record):
            _register_sqlite_helpers(dbapi_connection)

        _create_sqlite_schema(self.engine)
        self.Session = sessionmaker(
            bind=self.engine, autoflush=False, expire_on_commit=False
        )
        self.admin_id = uuid.uuid4()
        self.other_admin_id = uuid.uuid4()
        self.school_id = uuid.uuid4()
        self.other_school_id = uuid.uuid4()
        with self.Session() as session:
            with session.begin():
                session.add_all(
                    [
                        AdminUser(
                            id=self.admin_id,
                            username="provision-admin",
                            password_hash="synthetic-password-hash",
                            active=True,
                            failed_attempts=0,
                        ),
                        AdminUser(
                            id=self.other_admin_id,
                            username="provision-second",
                            password_hash="synthetic-password-hash",
                            active=True,
                            failed_attempts=0,
                        ),
                    ]
                )
        self.settings = CollaborationSettings(
            database_url="mysql+pymysql://unused/unused",
            token_pepper="T" * 32,
            preview_secret="P" * 32,
        )

    def _principal(self, admin_id=None) -> admin_service.AdminPrincipal:
        return admin_service.AdminPrincipal(
            admin_id=admin_id or self.admin_id,
            username="provision-admin",
            session_id=uuid.uuid4(),
            csrf_hash="C" * 64,
        )

    def _school(self, name: str) -> School:
        with self.Session() as session, session.begin():
            row = School(id=uuid.uuid4(), name=name)
            session.add(row)
            session.flush()
            return row


class AdminSchoolProvisioningTests(AdminProvisioningTestBase):
    def test_replay_returns_same_row_and_independent_same_name_is_kept(self):
        request_id = uuid.uuid4()
        with self.Session() as session:
            school, created = admin_service.create_school(
                session,
                self._principal(),
                school_id=request_id,
                name="  阳光实验幼儿园  ",
            )
            self.assertTrue(created)
            self.assertEqual(school.id, request_id)
            self.assertEqual(school.name, "阳光实验幼儿园")
        # A lost-response retry replays the SAME request id: same row, no
        # duplicate.
        with self.Session() as session:
            replay, created = admin_service.create_school(
                session,
                self._principal(),
                school_id=request_id,
                name="阳光实验幼儿园",
            )
            self.assertFalse(created)
            self.assertEqual(replay.id, request_id)
        # A different id is a deliberate second school even with the same
        # display name; nothing is silently merged.
        second_id = uuid.uuid4()
        with self.Session() as session:
            second, created = admin_service.create_school(
                session,
                self._principal(),
                school_id=second_id,
                name="阳光实验幼儿园",
            )
            self.assertTrue(created)
            self.assertEqual(second.id, second_id)
        with self.Session() as session:
            names = [
                row.name
                for row in session.scalars(
                    select(School).order_by(School.created_at, School.id)
                ).all()
            ]
            self.assertEqual(names.count("阳光实验幼儿园"), 2)

    def test_replay_with_different_input_is_rejected_not_merged(self):
        request_id = uuid.uuid4()
        with self.Session() as session:
            _school, created = admin_service.create_school(
                session,
                self._principal(),
                school_id=request_id,
                name="阳光实验幼儿园",
            )
            self.assertTrue(created)
        with self.Session() as session:
            with self.assertRaises(CollaborationError) as raised:
                admin_service.create_school(
                    session,
                    self._principal(),
                    school_id=request_id,
                    name="别的园所",
                )
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.code, "SCHOOL_CREATE_CONFLICT")

    def test_two_admin_sessions_replay_the_same_request_id_safely(self):
        request_id = uuid.uuid4()
        # Two independent admin sessions (two principals, two sessions) each
        # replay the same create request; the committed primary key keeps the
        # outcome one row, and the second replay reports created=False.
        with self.Session() as session:
            first, created = admin_service.create_school(
                session,
                self._principal(self.admin_id),
                school_id=request_id,
                name="并发园所",
            )
            self.assertTrue(created)
        with self.Session() as session:
            second, created = admin_service.create_school(
                session,
                self._principal(self.other_admin_id),
                school_id=request_id,
                name="并发园所",
            )
            self.assertFalse(created)
            self.assertEqual(second.id, first.id)
        with self.Session() as session:
            count = len(
                session.scalars(
                    select(School).where(School.id == request_id)
                ).all()
            )
            self.assertEqual(count, 1)

    def test_validation_and_unauthenticated_rejections(self):
        with self.Session() as session:
            with self.assertRaises(CollaborationError) as blank:
                admin_service.create_school(
                    session,
                    self._principal(),
                    school_id=uuid.uuid4(),
                    name="   ",
                )
            self.assertEqual(blank.exception.status_code, 422)
            with self.assertRaises(CollaborationError) as too_long:
                admin_service.create_school(
                    session,
                    self._principal(),
                    school_id=uuid.uuid4(),
                    name="名" * 121,
                )
            self.assertEqual(too_long.exception.status_code, 422)
            with self.assertRaises(CollaborationError) as non_string:
                admin_service.create_school(
                    session,
                    self._principal(),
                    school_id=uuid.uuid4(),
                    name=12345,
                )
            self.assertEqual(non_string.exception.status_code, 422)
            with self.assertRaises(CollaborationError) as unauthorized:
                admin_service.create_school(
                    session,
                    self._principal(uuid.uuid4()),
                    school_id=uuid.uuid4(),
                    name="无权园所",
                )
            self.assertEqual(unauthorized.exception.status_code, 401)
            self.assertEqual(
                unauthorized.exception.code, "ADMIN_AUTH_REQUIRED"
            )
        with self.Session() as session:
            self.assertEqual(
                session.scalars(select(School)).all(), []
            )


class AdminCreateConflictResolutionTests(AdminProvisioningTestBase):
    """A same-id create that loses a real insert race must resolve against
    the committed row: the same input returns a normal replay
    (``created=False``), a different input — including another school — is
    a controlled 409, and no driver error ever reaches the caller.

    The races are simulated deterministically: the committed winner row
    exists, and only this request's first pre-read is made to miss it, so
    the insert hits the real primary key and exercises the conflict
    resolution path itself.
    """

    def setUp(self) -> None:
        super().setUp()
        with self.Session() as session, session.begin():
            session.add_all(
                [
                    School(id=self.school_id, name="本园"),
                    School(id=self.other_school_id, name="他园"),
                ]
            )

    def _missing_first_read(self, session, model):
        """Patch ``session.get`` so the first ``model`` lookup misses while
        the committed row exists, like a concurrent winner committing after
        this request's pre-read."""
        real_get = session.get
        reads = {"count": 0}

        def get(entity, ident, *args, **kwargs):
            if entity is model:
                reads["count"] += 1
                if reads["count"] == 1:
                    return None
            return real_get(entity, ident, *args, **kwargs)

        return get

    def test_school_insert_race_replays_the_committed_row(self):
        request_id = uuid.uuid4()
        with self.Session() as session, session.begin():
            session.add(School(id=request_id, name="并发园"))
        with self.Session() as session:
            with patch.object(
                session, "get", new=self._missing_first_read(session, School)
            ):
                row, created = admin_service.create_school(
                    session,
                    self._principal(),
                    school_id=request_id,
                    name="并发园",
                )
            self.assertFalse(created)
            self.assertEqual(row.id, request_id)
            self.assertEqual(row.name, "并发园")
        with self.Session() as session:
            self.assertEqual(
                len(
                    session.scalars(
                        select(School).where(School.id == request_id)
                    ).all()
                ),
                1,
            )

    def test_school_insert_race_rejects_different_input_with_409(self):
        request_id = uuid.uuid4()
        with self.Session() as session, session.begin():
            session.add(School(id=request_id, name="并发园"))
        with self.Session() as session:
            with patch.object(
                session, "get", new=self._missing_first_read(session, School)
            ):
                with self.assertRaises(CollaborationError) as raised:
                    admin_service.create_school(
                        session,
                        self._principal(),
                        school_id=request_id,
                        name="不同名园",
                    )
            self.assertEqual(raised.exception.status_code, 409)
            self.assertEqual(
                raised.exception.code, "SCHOOL_CREATE_CONFLICT"
            )
        with self.Session() as session:
            row = session.get(School, request_id)
            self.assertEqual(row.name, "并发园")

    def test_teacher_insert_race_across_schools_is_controlled_409(self):
        teacher_id = uuid.uuid4()
        with self.Session() as session, session.begin():
            session.add(
                Teacher(
                    id=teacher_id,
                    school_id=self.other_school_id,
                    display_name="竞态教师",
                    active=True,
                )
            )
        with self.Session() as session:
            with patch.object(
                session, "get", new=self._missing_first_read(session, Teacher)
            ):
                with self.assertRaises(CollaborationError) as raised:
                    admin_service.create_teacher(
                        session,
                        self._principal(),
                        school_id=self.school_id,
                        teacher_id=teacher_id,
                        name="竞态教师",
                    )
            self.assertEqual(raised.exception.status_code, 409)
            self.assertEqual(
                raised.exception.code, "TEACHER_CREATE_CONFLICT"
            )
        with self.Session() as session:
            teacher = session.get(Teacher, teacher_id)
            self.assertEqual(teacher.school_id, self.other_school_id)
            self.assertEqual(len(admin_service.list_teachers(
                session, self.school_id
            )), 0)

    def test_class_insert_race_across_schools_is_controlled_409(self):
        class_id = uuid.uuid4()
        with self.Session() as session, session.begin():
            session.add(
                Classroom(
                    id=class_id,
                    school_id=self.other_school_id,
                    display_name="中三班",
                )
            )
            session.flush()
            session.add(
                ClassPromotionState(
                    class_id=class_id,
                    school_id=self.other_school_id,
                    class_number=3,
                    base_grade="middle",
                    version=1,
                )
            )
        with self.Session() as session:
            with patch.object(
                session,
                "get",
                new=self._missing_first_read(session, Classroom),
            ):
                with self.assertRaises(CollaborationError) as raised:
                    admin_service.create_class(
                        session,
                        self._principal(),
                        school_id=self.school_id,
                        class_id=class_id,
                        grade="middle",
                        class_number=3,
                    )
            self.assertEqual(raised.exception.status_code, 409)
            self.assertEqual(
                raised.exception.code, "CLASS_CREATE_CONFLICT"
            )
        with self.Session() as session:
            classroom = session.get(Classroom, class_id)
            self.assertEqual(classroom.school_id, self.other_school_id)

    def test_term_insert_race_across_schools_is_controlled_409(self):
        term_id = uuid.uuid4()
        with self.Session() as session, session.begin():
            session.add(
                CollaborationTerm(
                    id=term_id,
                    school_id=self.other_school_id,
                    name="竞态学期",
                    start_date=date(2026, 9, 1),
                    end_date=date(2026, 12, 31),
                )
            )
        with self.Session() as session:
            with patch.object(
                session,
                "get",
                new=self._missing_first_read(session, CollaborationTerm),
            ):
                with self.assertRaises(CollaborationError) as raised:
                    admin_service.create_term(
                        session,
                        self._principal(),
                        school_id=self.school_id,
                        term_id=term_id,
                        name="竞态学期",
                        start_date=date(2026, 9, 1),
                        end_date=date(2026, 12, 31),
                    )
            self.assertEqual(raised.exception.status_code, 409)
            self.assertEqual(
                raised.exception.code, "TERM_CREATE_CONFLICT"
            )
        with self.Session() as session:
            term = session.get(CollaborationTerm, term_id)
            self.assertEqual(term.school_id, self.other_school_id)
            self.assertEqual(
                len(admin_service.list_terms(session, self.school_id)), 0
            )

    def test_every_create_resolves_insert_conflicts_through_one_comparator(self):
        source = Path(admin_service.__file__).read_text(encoding="utf-8")
        for start, end, comparator, model in (
            (
                "def create_school(",
                "def list_teachers(",
                "_committed_school_or_conflict",
                "session.get(School, school_id)",
            ),
            (
                "def create_teacher(",
                "def update_teacher_name(",
                "_committed_teacher_or_conflict",
                "session.get(Teacher, teacher_id)",
            ),
            (
                "def create_class(",
                "def _valid_term_dates(",
                "_committed_class_or_conflict",
                "session.get(Classroom, class_id)",
            ),
            (
                "def create_term(",
                "def issue_code(",
                "_committed_term_or_conflict",
                "session.get(CollaborationTerm, term_id)",
            ),
        ):
            body = source[source.index(start):source.index(end)]
            self.assertIn("except IntegrityError", body)
            # Pre-read hit and insert-conflict path share one comparator, so
            # a replay resolved through either route behaves identically.
            self.assertEqual(body.count(comparator), 2)
            # The conflict path re-reads this request's committed id.
            self.assertEqual(body.count(model), 2)
            # Every create transaction is wrapped in the bounded InnoDB
            # deadlock retry.
            self.assertIn("_run_create_transaction(transaction)", body)


class AdminCreateDeadlockRetryTests(AdminProvisioningTestBase):
    """The confirmed pre-commit MySQL failure was pymysql OperationalError
    1213 (InnoDB deadlock; the server already rolled the transaction back).
    The same create request is replayed a bounded number of times; every
    unrelated database error propagates unchanged and a persistent deadlock
    re-raises after the last attempt."""

    def _deadlock(self) -> OperationalError:
        return OperationalError(
            "INSERT INTO terms",
            {},
            RuntimeError(1213, "Deadlock found when trying to get lock"),
        )

    def test_deadlocked_transaction_is_retried_as_the_same_request(self):
        attempts = []

        def transaction():
            attempts.append(1)
            if len(attempts) == 1:
                raise self._deadlock()
            return ("committed", True)

        self.assertEqual(
            admin_service._run_create_transaction(transaction),
            ("committed", True),
        )
        self.assertEqual(len(attempts), 2)

    def test_persistent_deadlock_reraises_after_bounded_attempts(self):
        attempts = []

        def transaction():
            attempts.append(1)
            raise self._deadlock()

        with self.assertRaises(OperationalError) as raised:
            admin_service._run_create_transaction(transaction)
        self.assertEqual(
            raised.exception.orig.args[0],
            admin_service._MYSQL_DEADLOCK_ERROR,
        )
        self.assertEqual(
            len(attempts), admin_service._CREATE_DEADLOCK_ATTEMPTS
        )

    def test_unrelated_database_errors_are_never_retried(self):
        for code in (1205, 2003, 1062, 1406):
            attempts = []

            def transaction():
                attempts.append(1)
                raise OperationalError(
                    "INSERT INTO terms",
                    {},
                    RuntimeError(code, "synthetic non-deadlock error"),
                )

            with self.assertRaises(OperationalError) as raised:
                admin_service._run_create_transaction(transaction)
            self.assertEqual(raised.exception.orig.args[0], code)
            self.assertEqual(len(attempts), 1)

    def test_non_database_errors_are_never_retried(self):
        attempts = []

        def transaction():
            attempts.append(1)
            raise ValueError("synthetic non-database failure")

        with self.assertRaises(ValueError):
            admin_service._run_create_transaction(transaction)
        self.assertEqual(len(attempts), 1)


class AdminClassProvisioningTests(AdminProvisioningTestBase):
    def setUp(self) -> None:
        super().setUp()
        with self.Session() as session, session.begin():
            session.add_all(
                [
                    School(id=self.school_id, name="合成园"),
                    School(id=self.other_school_id, name="另一园"),
                ]
            )

    def _seed_promoted_old_cohort(self) -> tuple[uuid.UUID, uuid.UUID]:
        """Register 小一班 and promote it to 中一班 for a past term."""
        old_class_id = uuid.uuid4()
        term_id = uuid.uuid4()
        with self.Session() as session, session.begin():
            # Parent rows first, then the children that reference them: the
            # real foreign keys stay enforced, so a shared flush must never
            # depend on unit-of-work ordering.
            session.add(
                CollaborationTerm(
                    id=term_id,
                    school_id=self.school_id,
                    name="2025 秋季学期",
                    start_date=date(2025, 9, 1),
                    end_date=date(2026, 1, 31),
                )
            )
            session.add(
                Classroom(
                    id=old_class_id,
                    school_id=self.school_id,
                    display_name="小一班",
                )
            )
            session.flush()
            session.add(
                ClassPromotionState(
                    class_id=old_class_id,
                    school_id=self.school_id,
                    class_number=1,
                    base_grade="small",
                    version=2,
                )
            )
            session.flush()
            session.add(
                ClassPromotionHistory(
                    id=uuid.uuid4(),
                    class_id=old_class_id,
                    school_id=self.school_id,
                    term_id=term_id,
                    grade="middle",
                    version_after=2,
                )
            )
        return old_class_id, term_id

    def test_replacement_cohort_after_promotion_is_created(self):
        # The regression: the old cohort still carries the (small, 1)
        # registration, but a fresh request id must create the new 小一班,
        # never silently return or reject against the old class.
        old_class_id, _term_id = self._seed_promoted_old_cohort()
        with self.Session() as session:
            old_name = effective_class_name_now(
                session, old_class_id, "fallback"
            )
        self.assertEqual(old_name, "中一班")

        new_class_id = uuid.uuid4()
        with self.Session() as session:
            result = admin_service.create_class(
                session,
                self._principal(),
                school_id=self.school_id,
                class_id=new_class_id,
                grade="small",
                class_number=1,
            )
            self.assertTrue(result.created)
            self.assertEqual(result.view.class_id, new_class_id)
            self.assertEqual(result.view.name, "小一班")
            self.assertEqual(result.grade, "small")
            self.assertEqual(result.class_number, 1)

        with self.Session() as session:
            # The old class keeps its own identity, history and name.
            self.assertEqual(
                effective_class_name_now(session, old_class_id, "fallback"),
                "中一班",
            )
            state = session.get(ClassPromotionState, old_class_id)
            self.assertEqual(state.base_grade, "small")
            self.assertEqual(state.class_number, 1)
            self.assertEqual(state.version, 2)
            history = session.scalars(
                select(ClassPromotionHistory).where(
                    ClassPromotionHistory.class_id == old_class_id
                )
            ).all()
            self.assertEqual(len(history), 1)
            new_state = session.get(ClassPromotionState, new_class_id)
            self.assertEqual(new_state.base_grade, "small")
            self.assertEqual(new_state.class_number, 1)
            self.assertEqual(new_state.version, 1)
            names = effective_class_names_now(
                session, [old_class_id, new_class_id]
            )
            self.assertEqual(names[old_class_id], "中一班")
            self.assertEqual(names[new_class_id], "小一班")

    def test_replay_conflict_and_cross_school_cases(self):
        request_id = uuid.uuid4()
        with self.Session() as session:
            result = admin_service.create_class(
                session,
                self._principal(),
                school_id=self.school_id,
                class_id=request_id,
                grade="middle",
                class_number=3,
            )
            self.assertTrue(result.created)
            self.assertEqual(result.view.name, "中三班")
        with self.Session() as session:
            replay = admin_service.create_class(
                session,
                self._principal(),
                school_id=self.school_id,
                class_id=request_id,
                grade="middle",
                class_number=3,
            )
            self.assertFalse(replay.created)
            self.assertEqual(replay.view.class_id, request_id)
            self.assertEqual(replay.grade, "middle")
            self.assertEqual(replay.class_number, 3)
        with self.Session() as session:
            with self.assertRaises(CollaborationError) as changed_grade:
                admin_service.create_class(
                    session,
                    self._principal(),
                    school_id=self.school_id,
                    class_id=request_id,
                    grade="large",
                    class_number=3,
                )
            self.assertEqual(changed_grade.exception.status_code, 409)
            self.assertEqual(
                changed_grade.exception.code, "CLASS_CREATE_CONFLICT"
            )
        with self.Session() as session:
            with self.assertRaises(CollaborationError) as other_school:
                admin_service.create_class(
                    session,
                    self._principal(),
                    school_id=self.other_school_id,
                    class_id=request_id,
                    grade="middle",
                    class_number=3,
                )
            self.assertEqual(other_school.exception.status_code, 409)
            self.assertEqual(
                other_school.exception.code, "CLASS_CREATE_CONFLICT"
            )
        with self.Session() as session:
            with self.assertRaises(CollaborationError) as unknown_school:
                admin_service.create_class(
                    session,
                    self._principal(),
                    school_id=uuid.uuid4(),
                    class_id=uuid.uuid4(),
                    grade="small",
                    class_number=2,
                )
            self.assertEqual(unknown_school.exception.status_code, 404)
            self.assertEqual(
                unknown_school.exception.code, "SCHOOL_NOT_FOUND"
            )
        with self.Session() as session:
            with self.assertRaises(CollaborationError) as bad_number:
                admin_service.create_class(
                    session,
                    self._principal(),
                    school_id=self.school_id,
                    class_id=uuid.uuid4(),
                    grade="middle",
                    class_number=0,
                )
            self.assertEqual(bad_number.exception.status_code, 422)
            with self.assertRaises(CollaborationError) as bad_grade:
                admin_service.create_class(
                    session,
                    self._principal(),
                    school_id=self.school_id,
                    class_id=uuid.uuid4(),
                    grade="huge",
                    class_number=1,
                )
            self.assertEqual(bad_grade.exception.status_code, 422)
        # Every refused or replayed attempt left the first successful create
        # as the only class of this school: no partial rows, no duplicates.
        with self.Session() as session:
            rows = session.scalars(
                select(Classroom).where(
                    Classroom.school_id == self.school_id
                )
            ).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].id, request_id)
            states = session.scalars(
                select(ClassPromotionState).where(
                    ClassPromotionState.school_id == self.school_id
                )
            ).all()
            self.assertEqual(len(states), 1)
            self.assertEqual(states[0].class_id, request_id)

    def test_registration_writes_parent_class_first_under_real_foreign_keys(self):
        # The deployed MySQL 8.4 schema enforces the composite
        # (class_id, school_id) -> classes(id, school_id) foreign key at
        # INSERT time, and this fixture enforces the same constraint on
        # SQLite.  create_class therefore writes the classroom row into the
        # transaction before the registration row; a combined flush that
        # emits the registration first fails here exactly like MySQL 1452.
        request_id = uuid.uuid4()
        with self.Session() as session:
            result = admin_service.create_class(
                session,
                self._principal(),
                school_id=self.school_id,
                class_id=request_id,
                grade="large",
                class_number=5,
            )
            self.assertTrue(result.created)
            self.assertEqual(result.view.name, "大五班")
        with self.Session() as session:
            classroom = session.get(Classroom, request_id)
            state = session.get(ClassPromotionState, request_id)
            self.assertIsNotNone(classroom)
            self.assertIsNotNone(state)
            self.assertEqual(state.school_id, classroom.school_id)
            self.assertEqual(state.class_number, 5)
            self.assertEqual(state.base_grade, "large")

        # Defense in depth: the source pins the flush order itself.
        source = (
            Path(admin_service.__file__).read_text(encoding="utf-8")
        )
        body = source[
            source.index("def create_class("):
            source.index("def _valid_term_dates(")
        ]
        classroom_add = body.index("session.add(classroom)")
        parent_flush = body.index("session.flush()", classroom_add)
        state_add = body.index("session.add(state)")
        self.assertLess(parent_flush, state_add)

    def test_registration_failure_rolls_back_the_flushed_classroom_row(self):
        # The classroom row is already flushed into the transaction when the
        # registration insert fails; both writes must still roll back
        # together, leaving no half-created class.
        request_id = uuid.uuid4()

        class ExplodingState:
            def __init__(self, *_args, **_kwargs):
                raise RuntimeError("synthetic registration failure")

        with patch.object(
            admin_service, "ClassPromotionState", ExplodingState
        ):
            with self.assertRaises(RuntimeError):
                with self.Session() as session:
                    admin_service.create_class(
                        session,
                        self._principal(),
                        school_id=self.school_id,
                        class_id=request_id,
                        grade="middle",
                        class_number=6,
                    )
        with self.Session() as session:
            self.assertIsNone(session.get(Classroom, request_id))
            self.assertIsNone(
                session.get(ClassPromotionState, request_id)
            )
            self.assertEqual(
                session.scalars(
                    select(Classroom).where(
                        Classroom.school_id == self.school_id
                    )
                ).all(),
                [],
            )

    def test_same_transaction_registration_and_existing_records_kept(self):
        old_class_id = uuid.uuid4()
        old_teacher_id = uuid.uuid4()
        term_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        with self.Session() as session, session.begin():
            # Parent rows first, then membership/config/state children under
            # the real enforced foreign keys.
            session.add(
                CollaborationTerm(
                    id=term_id,
                    school_id=self.school_id,
                    name="2026 秋季学期",
                    start_date=date(2026, 9, 1),
                    end_date=date(2027, 1, 31),
                )
            )
            session.add(
                Classroom(
                    id=old_class_id,
                    school_id=self.school_id,
                    display_name="大二班",
                )
            )
            session.flush()
            session.add(
                ClassPromotionState(
                    class_id=old_class_id,
                    school_id=self.school_id,
                    class_number=2,
                    base_grade="large",
                    version=1,
                )
            )
            session.add(
                Teacher(
                    id=old_teacher_id,
                    school_id=self.school_id,
                    display_name="旧配对教师",
                    active=True,
                )
            )
            session.flush()
            session.add(
                TeacherClassMembership(
                    teacher_id=old_teacher_id,
                    school_id=self.school_id,
                    class_id=old_class_id,
                    membership_generation=uuid.uuid4(),
                    selected_at=now,
                    updated_at=now,
                )
            )
            session.add(
                TeacherGameConfig(
                    teacher_id=old_teacher_id,
                    school_id=self.school_id,
                    class_id=old_class_id,
                    version=4,
                    payload={
                        "locations": ["益智区"],
                        "game_scope": None,
                        "guidance": None,
                    },
                    payload_hash="a" * 64,
                    updated_at=now,
                )
            )

        new_class_id = uuid.uuid4()
        with self.Session() as session:
            result = admin_service.create_class(
                session,
                self._principal(),
                school_id=self.school_id,
                class_id=new_class_id,
                grade="large",
                class_number=2,
            )
            self.assertTrue(result.created)
        with self.Session() as session:
            # The classroom row and its promotion registration commit in one
            # transaction: both exist for the new class, and neither a
            # membership nor a game configuration is pre-created.
            self.assertIsNotNone(session.get(Classroom, new_class_id))
            self.assertIsNotNone(session.get(ClassPromotionState, new_class_id))
            self.assertEqual(
                session.scalars(
                    select(TeacherClassMembership).where(
                        TeacherClassMembership.class_id == new_class_id
                    )
                ).all(),
                [],
            )
            self.assertEqual(
                session.scalars(
                    select(TeacherGameConfig).where(
                        TeacherGameConfig.class_id == new_class_id
                    )
                ).all(),
                [],
            )
            # Every existing class record keeps its exact values.
            old_state = session.get(ClassPromotionState, old_class_id)
            self.assertEqual(old_state.version, 1)
            self.assertEqual(old_state.class_number, 2)
            self.assertEqual(old_state.base_grade, "large")
            membership = session.get(TeacherClassMembership, old_teacher_id)
            self.assertEqual(membership.class_id, old_class_id)
            self.assertEqual(membership.selected_at, now)
            config = session.get(
                TeacherGameConfig,
                (old_teacher_id, self.school_id, old_class_id),
            )
            self.assertEqual(config.version, 4)
            term = session.get(CollaborationTerm, term_id)
            self.assertEqual(term.name, "2026 秋季学期")
            self.assertEqual(term.start_date, date(2026, 9, 1))

    def test_new_class_matches_provision_cli_bare_row_standard(self):
        with self.Session() as session:
            provision._create_class(session, self.school_id, "中五班")
        page_class_id = uuid.uuid4()
        with self.Session() as session:
            result = admin_service.create_class(
                session,
                self._principal(),
                school_id=self.school_id,
                class_id=page_class_id,
                grade="middle",
                class_number=5,
            )
            self.assertEqual(result.view.name, "中五班")
        with self.Session() as session:
            rows = session.scalars(
                select(Classroom).where(
                    Classroom.school_id == self.school_id
                )
            ).all()
            cli_row = next(
                row for row in rows if row.id != page_class_id
            )
            page_row = session.get(Classroom, page_class_id)
            # Both carry the same bare-row shape; the page create additionally
            # writes the promotion registration that the shared weekly plan
            # and the promotion read require, in the same transaction.
            self.assertEqual(cli_row.display_name, page_row.display_name)
            self.assertIsNone(page_row.display_name_override)
            self.assertIsNotNone(
                session.get(ClassPromotionState, page_class_id)
            )
            self.assertIsNone(session.get(ClassPromotionState, cli_row.id))


class AdminTeacherProvisioningTests(AdminProvisioningTestBase):
    def setUp(self) -> None:
        super().setUp()
        with self.Session() as session, session.begin():
            session.add_all(
                [
                    School(id=self.school_id, name="合成园"),
                    School(id=self.other_school_id, name="另一园"),
                ]
            )

    def test_same_name_distinct_ids_and_replay_safety(self):
        first_id = uuid.uuid4()
        second_id = uuid.uuid4()
        with self.Session() as session:
            first, created = admin_service.create_teacher(
                session,
                self._principal(),
                school_id=self.school_id,
                teacher_id=first_id,
                name=" 王老师 ",
            )
            self.assertTrue(created)
            self.assertEqual(first.display_name, "王老师")
            self.assertTrue(first.active)
        with self.Session() as session:
            # A different request id with the same display name is a second,
            # distinguishable teacher (the offline tool allows the same).
            second, created = admin_service.create_teacher(
                session,
                self._principal(),
                school_id=self.school_id,
                teacher_id=second_id,
                name="王老师",
            )
            self.assertTrue(created)
            self.assertEqual(second.id, second_id)
        with self.Session() as session:
            # The SAME request id replayed returns the committed row.
            replay, created = admin_service.create_teacher(
                session,
                self._principal(),
                school_id=self.school_id,
                teacher_id=first_id,
                name="王老师",
            )
            self.assertFalse(created)
            self.assertEqual(replay.id, first_id)
        with self.Session() as session:
            teachers = admin_service.list_teachers(session, self.school_id)
            self.assertEqual(len(teachers), 2)
            self.assertEqual(
                sorted(row.display_name for row in teachers),
                ["王老师", "王老师"],
            )
            self.assertEqual(
                sorted(str(row.id) for row in teachers),
                sorted([str(first_id), str(second_id)]),
            )

    def test_replay_with_different_input_and_cross_school(self):
        request_id = uuid.uuid4()
        with self.Session() as session:
            _teacher, created = admin_service.create_teacher(
                session,
                self._principal(),
                school_id=self.school_id,
                teacher_id=request_id,
                name="王老师",
            )
            self.assertTrue(created)
        with self.Session() as session:
            with self.assertRaises(CollaborationError) as renamed:
                admin_service.create_teacher(
                    session,
                    self._principal(),
                    school_id=self.school_id,
                    teacher_id=request_id,
                    name="李老师",
                )
            self.assertEqual(renamed.exception.status_code, 409)
            self.assertEqual(
                renamed.exception.code, "TEACHER_CREATE_CONFLICT"
            )
        with self.Session() as session:
            with self.assertRaises(CollaborationError) as other_school:
                admin_service.create_teacher(
                    session,
                    self._principal(),
                    school_id=self.other_school_id,
                    teacher_id=request_id,
                    name="王老师",
                )
            self.assertEqual(other_school.exception.status_code, 409)
        with self.Session() as session:
            with self.assertRaises(CollaborationError) as unknown_school:
                admin_service.create_teacher(
                    session,
                    self._principal(),
                    school_id=uuid.uuid4(),
                    teacher_id=uuid.uuid4(),
                    name="王老师",
                )
            self.assertEqual(unknown_school.exception.status_code, 404)
            self.assertEqual(
                unknown_school.exception.code, "SCHOOL_NOT_FOUND"
            )

    def test_inactive_teacher_replay_keeps_inactive_flag(self):
        request_id = uuid.uuid4()
        with self.Session() as session, session.begin():
            session.add(
                Teacher(
                    id=request_id,
                    school_id=self.school_id,
                    display_name="王老师",
                    active=False,
                )
            )
        with self.Session() as session:
            replay, created = admin_service.create_teacher(
                session,
                self._principal(),
                school_id=self.school_id,
                teacher_id=request_id,
                name="王老师",
            )
            self.assertFalse(created)
            self.assertFalse(replay.active)

    def test_created_teacher_feeds_issue_code_and_redeem_flow(self):
        teacher_id = uuid.uuid4()
        with self.Session() as session:
            _teacher, created = admin_service.create_teacher(
                session,
                self._principal(),
                school_id=self.school_id,
                teacher_id=teacher_id,
                name="签发教师",
            )
            self.assertTrue(created)
        with self.Session() as session:
            issued = admin_service.issue_code(
                session,
                self.settings,
                self._principal(),
                school_id=self.school_id,
                teacher_id=teacher_id,
                purpose="join",
            )
            self.assertEqual(issued.teacher_id, teacher_id)
            self.assertEqual(issued.teacher_name, "签发教师")
        with self.Session() as session:
            redeemed = admin_service.redeem_code(
                session, self.settings, issued.code
            )
            self.assertEqual(redeemed.teacher_id, teacher_id)
            self.assertEqual(redeemed.teacher_name, "签发教师")
            self.assertEqual(redeemed.school_id, self.school_id)
            self.assertIsNone(redeemed.membership)
            principal = authenticate(
                session, redeemed.token, self.settings.token_pepper
            )
            self.assertEqual(principal.teacher_id, teacher_id)

    def test_update_teacher_name_baseline_conflict_and_cross_school(self):
        teacher_id = uuid.uuid4()
        with self.Session() as session:
            _teacher, created = admin_service.create_teacher(
                session,
                self._principal(),
                school_id=self.school_id,
                teacher_id=teacher_id,
                name="王老师",
            )
            self.assertTrue(created)
        with self.Session() as session:
            updated = admin_service.update_teacher_name(
                session,
                self._principal(),
                school_id=self.school_id,
                teacher_id=teacher_id,
                expected_name="王老师",
                new_name="王老师（小班）",
            )
            self.assertEqual(updated.display_name, "王老师（小班）")
            self.assertTrue(updated.active)
        with self.Session() as session:
            retried = admin_service.update_teacher_name(
                session,
                self._principal(),
                school_id=self.school_id,
                teacher_id=teacher_id,
                expected_name="王老师",
                new_name="王老师（小班）",
            )
            self.assertEqual(retried.display_name, "王老师（小班）")
        with self.Session() as session:
            with self.assertRaises(CollaborationError) as conflict:
                admin_service.update_teacher_name(
                    session,
                    self._principal(),
                    school_id=self.school_id,
                    teacher_id=teacher_id,
                    expected_name="王老师",
                    new_name="第三个名字",
                )
            self.assertEqual(conflict.exception.status_code, 409)
            self.assertEqual(
                conflict.exception.code, "TEACHER_NAME_CONFLICT"
            )
            self.assertEqual(
                conflict.exception.details["current_name"],
                "王老师（小班）",
            )
        with self.Session() as session:
            with self.assertRaises(CollaborationError) as other_school:
                admin_service.update_teacher_name(
                    session,
                    self._principal(),
                    school_id=self.other_school_id,
                    teacher_id=teacher_id,
                    expected_name="王老师（小班）",
                    new_name="改名",
                )
            self.assertEqual(other_school.exception.status_code, 404)
            self.assertEqual(
                other_school.exception.code, "TEACHER_NOT_FOUND"
            )
        with self.Session() as session:
            teachers = admin_service.list_teachers(session, self.school_id)
            self.assertEqual(
                [row.display_name for row in teachers], ["王老师（小班）"]
            )


class AdminTermProvisioningTests(AdminProvisioningTestBase):
    def setUp(self) -> None:
        super().setUp()
        with self.Session() as session, session.begin():
            session.add_all(
                [
                    School(id=self.school_id, name="合成园"),
                    School(id=self.other_school_id, name="另一园"),
                ]
            )

    def test_explicit_dates_create_replay_and_overlap_rules(self):
        request_id = uuid.uuid4()
        with self.Session() as session:
            term, created = admin_service.create_term(
                session,
                self._principal(),
                school_id=self.school_id,
                term_id=request_id,
                name=" 2026 秋季学期 ",
                start_date=date(2026, 9, 1),
                end_date=date(2026, 12, 31),
            )
            self.assertTrue(created)
            self.assertEqual(term.name, "2026 秋季学期")
            self.assertEqual(term.start_date, date(2026, 9, 1))
        with self.Session() as session:
            replay, created = admin_service.create_term(
                session,
                self._principal(),
                school_id=self.school_id,
                term_id=request_id,
                name="2026 秋季学期",
                start_date=date(2026, 9, 1),
                end_date=date(2026, 12, 31),
            )
            self.assertFalse(created)
            self.assertEqual(replay.term_id, request_id)
        with self.Session() as session:
            with self.assertRaises(CollaborationError) as changed:
                admin_service.create_term(
                    session,
                    self._principal(),
                    school_id=self.school_id,
                    term_id=request_id,
                    name="2026 秋季学期",
                    start_date=date(2026, 9, 1),
                    end_date=date(2026, 11, 30),
                )
            self.assertEqual(changed.exception.status_code, 409)
            self.assertEqual(
                changed.exception.code, "TERM_CREATE_CONFLICT"
            )
        # A different request id that overlaps is a 409 naming the conflict —
        # even with identical name and dates, it is a second create, not a
        # silent merge.
        with self.Session() as session:
            with self.assertRaises(CollaborationError) as overlap:
                admin_service.create_term(
                    session,
                    self._principal(),
                    school_id=self.school_id,
                    term_id=uuid.uuid4(),
                    name="2026 秋季学期",
                    start_date=date(2026, 9, 1),
                    end_date=date(2026, 12, 31),
                )
            self.assertEqual(overlap.exception.status_code, 409)
            self.assertEqual(overlap.exception.code, "TERM_OVERLAP")
            self.assertEqual(
                overlap.exception.details["conflict_name"],
                "2026 秋季学期",
            )
        # A term of another school may overlap freely: rules stay per school.
        with self.Session() as session:
            other, created = admin_service.create_term(
                session,
                self._principal(),
                school_id=self.other_school_id,
                term_id=uuid.uuid4(),
                name="2026 秋季学期",
                start_date=date(2026, 9, 1),
                end_date=date(2026, 12, 31),
            )
            self.assertTrue(created)
        with self.Session() as session:
            terms = admin_service.list_terms(session, self.school_id)
            self.assertEqual(len(terms), 1)
            self.assertEqual(terms[0].name, "2026 秋季学期")

    def test_validation_rejects_guessed_or_unordered_dates(self):
        with self.Session() as session:
            for payload in (
                {"name": "   ", "start_date": date(2026, 9, 1), "end_date": date(2026, 12, 31)},
                {"name": "名" * 81, "start_date": date(2026, 9, 1), "end_date": date(2026, 12, 31)},
                {"name": "无日期学期", "start_date": None, "end_date": date(2026, 12, 31)},
                {"name": "乱序学期", "start_date": date(2026, 12, 31), "end_date": date(2026, 9, 1)},
            ):
                with self.assertRaises(CollaborationError) as raised:
                    admin_service.create_term(
                        session,
                        self._principal(),
                        school_id=self.school_id,
                        term_id=uuid.uuid4(),
                        **payload,
                    )
                self.assertEqual(raised.exception.status_code, 422)
            self.assertEqual(
                admin_service.list_terms(session, self.school_id), []
            )
        with self.Session() as session:
            with self.assertRaises(CollaborationError) as unknown_school:
                admin_service.create_term(
                    session,
                    self._principal(),
                    school_id=uuid.uuid4(),
                    term_id=uuid.uuid4(),
                    name="无园学期",
                    start_date=date(2026, 9, 1),
                    end_date=date(2026, 12, 31),
                )
            self.assertEqual(unknown_school.exception.status_code, 404)


class AdminProvisioningRouteTests(AdminProvisioningTestBase):
    def setUp(self) -> None:
        super().setUp()
        with self.Session() as session, session.begin():
            session.add(School(id=self.school_id, name="路由园"))

    def test_route_handlers_return_create_outputs(self):
        school_id = uuid.uuid4()
        with self.Session() as session:
            result = admin_api.admin_create_school(
                admin_api.AdminSchoolCreateIn(
                    school_id=school_id, name="路由新园"
                ),
                Response(),
                session,
                self._principal(),
            )
            self.assertEqual(result.school_id, school_id)
            self.assertEqual(result.name, "路由新园")
            self.assertTrue(result.created)
        class_id = uuid.uuid4()
        with self.Session() as session:
            result = admin_api.admin_create_class(
                self.school_id,
                admin_api.AdminClassCreateIn(
                    class_id=class_id, grade="middle", class_number=3
                ),
                Response(),
                session,
                self._principal(),
            )
            self.assertEqual(result.class_id, class_id)
            self.assertEqual(result.name, "中三班")
            self.assertEqual(result.grade, "middle")
            self.assertEqual(result.class_number, 3)
            self.assertTrue(result.created)
        teacher_id = uuid.uuid4()
        with self.Session() as session:
            result = admin_api.admin_create_teacher(
                self.school_id,
                admin_api.AdminTeacherCreateIn(teacher_id=teacher_id, name="路由教师"),
                Response(),
                session,
                self._principal(),
            )
            self.assertEqual(result.teacher_id, teacher_id)
            self.assertEqual(result.display_name, "路由教师")
            self.assertTrue(result.active)
            self.assertTrue(result.created)
        with self.Session() as session:
            renamed = admin_api.admin_update_teacher(
                self.school_id,
                teacher_id,
                admin_api.AdminTeacherUpdateIn(
                    expected_name="路由教师", new_name="路由教师（改名）"
                ),
                Response(),
                session,
                self._principal(),
            )
            self.assertEqual(renamed.display_name, "路由教师（改名）")
        term_id = uuid.uuid4()
        with self.Session() as session:
            result = admin_api.admin_create_term(
                self.school_id,
                admin_api.AdminTermCreateIn(
                    term_id=term_id,
                    name="路由学期",
                    start_date=date(2026, 9, 1),
                    end_date=date(2026, 12, 31),
                ),
                Response(),
                session,
                self._principal(),
            )
            self.assertEqual(result.term_id, term_id)
            self.assertEqual(result.name, "路由学期")
            self.assertEqual(result.start_date, date(2026, 9, 1))
            self.assertTrue(result.created)

    def test_write_routes_require_csrf_and_reads_do_not(self):
        source = Path(admin_api.__file__).read_text(encoding="utf-8")
        write_routes = [
            ("admin_create_school", "admin_classes"),
            ("admin_create_class", "admin_create_teacher"),
            ("admin_create_teacher", "admin_update_teacher"),
            ("admin_update_teacher", "admin_teachers"),
            ("admin_create_term", "admin_create_code"),
        ]
        for name, next_name in write_routes:
            route = source[
                source.index(f"def {name}("): source.index(f"def {next_name}(")
            ]
            self.assertIn("Depends(get_admin_csrf_principal)", route)
        for name, next_name in [
            ("admin_schools", "admin_update_school"),
            ("admin_teachers", "admin_terms"),
            ("admin_terms", "admin_update_term"),
        ]:
            route = source[
                source.index(f"def {name}("): source.index(f"def {next_name}(")
            ]
            self.assertIn("Depends(get_admin_principal)", route)
            self.assertNotIn("get_admin_csrf_principal", route)
        # Reads without an admin cookie stay refused before any data leaves.
        with self.Session() as session:
            with self.assertRaises(CollaborationError) as anonymous:
                admin_service.authenticate_admin(
                    session, self.settings, ""
                )
            self.assertEqual(anonymous.exception.status_code, 401)
            self.assertEqual(
                anonymous.exception.code, "ADMIN_AUTH_REQUIRED"
            )

    def test_admin_page_has_provisioning_entries_and_replay_wording(self):
        page = (
            BACKEND
            / "app"
            / "collaboration"
            / "admin_page.html"
        ).read_text(encoding="utf-8")
        for needle in (
            'id="create-school-button"',
            "新增园所",
            'id="create-class-button"',
            "新增班级",
            'id="create-teacher-button"',
            "新增教师",
            'id="create-term-button"',
            "新增学期",
            'id="teacher-list"',
            "保存教师名称",
            "稳定教师 ID",
            "该园所暂无教师",
            "系统不会代填日期",
            "function newRequestId",
            "pendingSchoolId",
            "pendingClassId",
            "pendingTeacherId",
            "pendingTermId",
            "同一创建请求返回",
            'id="issue-hint"',
            "function teacherIdTail",
            "（ID 尾号 ",
        ):
            self.assertIn(needle, page)


class AdminProvisioningEndToEndTests(AdminProvisioningTestBase):
    """From empty data to a shared weekly plan, through the real services."""

    def test_empty_data_to_shared_weekly_plan(self):
        principal_admin = self._principal()

        # 1. Admin creates the school from empty data.
        school_request = uuid.uuid4()
        with self.Session() as session:
            school, created = admin_service.create_school(
                session,
                principal_admin,
                school_id=school_request,
                name="端到端幼儿园",
            )
            self.assertTrue(created)
        school_id = school.id

        # 2. Admin creates the class with grade and number in one
        # transaction; a lost-response replay adds nothing.
        class_request = uuid.uuid4()
        with self.Session() as session:
            result = admin_service.create_class(
                session,
                principal_admin,
                school_id=school_id,
                class_id=class_request,
                grade="middle",
                class_number=3,
            )
            self.assertTrue(result.created)
            self.assertEqual(result.view.name, "中三班")
        class_id = result.view.class_id
        with self.Session() as session:
            replay = admin_service.create_class(
                session,
                principal_admin,
                school_id=school_id,
                class_id=class_request,
                grade="middle",
                class_number=3,
            )
            self.assertFalse(replay.created)
            self.assertEqual(replay.view.class_id, class_id)

        # 3. Admin creates two named teachers and issues both codes.
        teacher_ids = {}
        redeemed = {}
        for name in ("张老师", "李老师"):
            teacher_request = uuid.uuid4()
            with self.Session() as session:
                teacher, created = admin_service.create_teacher(
                    session,
                    principal_admin,
                    school_id=school_id,
                    teacher_id=teacher_request,
                    name=name,
                )
                self.assertTrue(created)
                issued = admin_service.issue_code(
                    session,
                    self.settings,
                    principal_admin,
                    school_id=school_id,
                    teacher_id=teacher.id,
                    purpose="join",
                )
                teacher_ids[name] = teacher.id
            with self.Session() as session:
                redeemed[name] = admin_service.redeem_code(
                    session, self.settings, issued.code
                )

        # 4. Both teachers independently pick the SAME class; the same-school
        # same-class pairing then lists each other as classmates.
        principals = {}
        with self.Session() as session:
            for name in ("张老师", "李老师"):
                principal = authenticate(
                    session,
                    redeemed[name].token,
                    self.settings.token_pepper,
                )
                principals[name] = principal
        for name in ("张老师", "李老师"):
            with self.Session() as session:
                membership = select_class(
                    session, principals[name], class_id
                )
                self.assertEqual(membership.class_id, class_id)
                self.assertEqual(membership.class_name, "中三班")
        with self.Session() as session:
            classes = list_classes(session, principals["张老师"])
            self.assertEqual(
                [(row.class_id, row.display_name) for row in classes],
                [(class_id, "中三班")],
            )
            classmates = list_classmates(session, principals["张老师"])
            self.assertEqual(
                [row.display_name for row in classmates], ["李老师"]
            )

        # 5. Without a school term the shared weekly plan stays blocked: the
        # promotion read offers no term to call with, and any direct save is
        # refused with TERM_NOT_FOUND.
        start = date(2026, 9, 1)
        week_start = start - timedelta(days=start.weekday())
        self.assertEqual(week_start.weekday(), 0)
        with self.Session() as session:
            promotion = get_promotion(session, principals["张老师"])
            self.assertEqual(promotion.class_name, "中三班")
            self.assertEqual(promotion.grade, "middle")
            self.assertEqual(promotion.terms, ())
        with self.Session() as session:
            with self.assertRaises(CollaborationError) as blocked:
                save_weekly_plan(
                    session,
                    principals["张老师"],
                    class_id,
                    uuid.uuid4(),
                    week_start.isoformat(),
                    request_id=uuid.uuid4(),
                    expected_version=0,
                    content={"days": [], "games": {}},
                )
            self.assertEqual(blocked.exception.status_code, 404)
            self.assertEqual(blocked.exception.code, "TERM_NOT_FOUND")

        # 6. Admin creates the term with explicitly supplied dates; the same
        # request replayed adds nothing.
        term_request = uuid.uuid4()
        end = date(2026, 12, 31)
        with self.Session() as session:
            term, created = admin_service.create_term(
                session,
                principal_admin,
                school_id=school_id,
                term_id=term_request,
                name="2026 秋季学期",
                start_date=start,
                end_date=end,
            )
            self.assertTrue(created)
        term_id = term.term_id
        with self.Session() as session:
            _term, created = admin_service.create_term(
                session,
                principal_admin,
                school_id=school_id,
                term_id=term_request,
                name="2026 秋季学期",
                start_date=start,
                end_date=end,
            )
            self.assertFalse(created)

        # 7. The shared weekly plan now saves, pairs and confirms between the
        # two same-class teachers.
        first_date = max(week_start, start)
        content = {
            "days": [
                {
                    "date": first_date.isoformat(),
                    "morning_talk_topic": "合成晨谈主题",
                    "group_activity_theme": "合成集体活动",
                }
            ],
            "games": {
                "collective_1": {
                    "name": "合成集体游戏",
                    "date": first_date.isoformat(),
                }
            },
        }
        # The service normalizes missing game slots to None; compare against
        # the normalized shape.
        normalized_content = {
            "days": content["days"],
            "games": {
                "collective_1": content["games"]["collective_1"],
                "collective_2": None,
                "free_choice_1": None,
                "focus_area": None,
            },
        }
        with self.Session() as session:
            saved = save_weekly_plan(
                session,
                principals["张老师"],
                class_id,
                term_id,
                week_start.isoformat(),
                request_id=uuid.uuid4(),
                expected_version=0,
                content=content,
            )
            self.assertEqual(saved["version"], 1)
            self.assertEqual(saved["content"], normalized_content)
        with self.Session() as session:
            read = get_weekly_plan(
                session,
                principals["李老师"],
                class_id,
                term_id,
                week_start.isoformat(),
            )
            self.assertEqual(read["version"], 1)
            self.assertEqual(read["content"], normalized_content)
            self.assertEqual(read["class_name"], "中三班")
        with self.Session() as session:
            confirmed = confirm_weekly_plan(
                session,
                principals["李老师"],
                class_id,
                term_id,
                week_start.isoformat(),
                request_id=uuid.uuid4(),
                expected_version=1,
            )
            self.assertEqual(confirmed["version"], 1)
            self.assertEqual(confirmed["content"], normalized_content)
            self.assertEqual(confirmed["grade"], "middle")
        with self.Session() as session:
            read_again = get_weekly_plan(
                session,
                principals["张老师"],
                class_id,
                term_id,
                week_start.isoformat(),
            )
            self.assertIsNotNone(read_again["confirmation"])
            self.assertEqual(read_again["confirmation"]["version"], 1)

        # 8. The own-config read stays lazy: no extra business record was
        # pre-created for the new class or the new teachers.
        with self.Session() as session:
            own = get_own_config(session, principals["张老师"])
            self.assertEqual(own.class_id, class_id)
            self.assertEqual(own.config_version, 0)


@unittest.skipUnless(
    os.environ.get("KGM_COLLAB_TEST_DATABASE_URL"),
    "requires explicit KGM_COLLAB_TEST_DATABASE_URL and an isolated MySQL schema",
)
class AdminProvisioningMySQLRaceTests(unittest.TestCase):
    """Real concurrency on the deployed engine against a committed schema.

    Two threads race the same create with independent sessions and
    transactions behind a barrier, so neither depends on the other's
    pre-read: the loser may only return through the insert-conflict
    resolution.  Any raw driver error fails the test.  The schema is
    created by the operator's committed migrations; this class never
    creates or migrates a database.
    """

    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            os.environ["KGM_COLLAB_TEST_DATABASE_URL"]
        )
        cls.Session = sessionmaker(
            bind=cls.engine, autoflush=False, expire_on_commit=False
        )

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        self.admin_id = uuid.uuid4()
        self.school_id = uuid.uuid4()
        self.other_school_id = uuid.uuid4()
        self.schools = [self.school_id, self.other_school_id]
        with self.Session() as session:
            with session.begin():
                session.add_all(
                    [
                        AdminUser(
                            id=self.admin_id,
                            username="race-admin",
                            password_hash="synthetic-password-hash",
                            active=True,
                            failed_attempts=0,
                        ),
                        School(id=self.school_id, name="竞态园甲"),
                        School(id=self.other_school_id, name="竞态园乙"),
                    ]
                )
        self.principal = admin_service.AdminPrincipal(
            admin_id=self.admin_id,
            username="race-admin",
            session_id=uuid.uuid4(),
            csrf_hash="C" * 64,
        )

    def tearDown(self):
        with self.Session() as session:
            with session.begin():
                for school_id in self.schools:
                    session.execute(
                        delete(ClassPromotionHistory).where(
                            ClassPromotionHistory.school_id == school_id
                        )
                    )
                    session.execute(
                        delete(ClassPromotionState).where(
                            ClassPromotionState.school_id == school_id
                        )
                    )
                    session.execute(
                        delete(Teacher).where(
                            Teacher.school_id == school_id
                        )
                    )
                    session.execute(
                        delete(Classroom).where(
                            Classroom.school_id == school_id
                        )
                    )
                    session.execute(
                        delete(CollaborationTerm).where(
                            CollaborationTerm.school_id == school_id
                        )
                    )
                    session.execute(
                        delete(School).where(School.id == school_id)
                    )
                session.execute(
                    delete(AdminUser).where(AdminUser.id == self.admin_id)
                )

    def _race(self, calls):
        self.assertEqual(len(calls), 2)
        barrier = threading.Barrier(2)
        outcomes = []

        def worker(call):
            session = self.Session()
            try:
                barrier.wait(timeout=30)
                outcomes.append(("ok", call(session)))
            except CollaborationError as exc:
                outcomes.append(("conflict", exc))
            except Exception as exc:  # noqa: BLE001 - reported as a failure
                outcomes.append(("driver", exc))
                # Keep the raw driver error visible in the failure report:
                # type, message and the DBAPI-level origin.
                origin = getattr(exc, "orig", None)
                print(
                    "RAW DRIVER ERROR: %s: %s | orig=%r"
                    % (
                        type(exc).__name__,
                        str(exc).splitlines()[0] if str(exc) else exc,
                        origin,
                    ),
                    file=sys.stderr,
                )
            finally:
                session.close()

        threads = [
            threading.Thread(target=worker, args=(call,))
            for call in calls
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        self.assertEqual(len(outcomes), 2)
        return outcomes

    def test_same_school_id_concurrent_same_payload_replays(self):
        request_id = uuid.uuid4()
        self.schools.append(request_id)
        outcomes = self._race(
            [
                lambda session: admin_service.create_school(
                    session,
                    self.principal,
                    school_id=request_id,
                    name="竞态同名园",
                ),
                lambda session: admin_service.create_school(
                    session,
                    self.principal,
                    school_id=request_id,
                    name="竞态同名园",
                ),
            ]
        )
        self.assertEqual(
            sorted(kind for kind, _ in outcomes), ["ok", "ok"]
        )
        ok_rows = [outcome for kind, outcome in outcomes if kind == "ok"]
        self.assertEqual(
            sorted(created for _row, created in ok_rows),
            [False, True],
        )
        self.assertEqual(
            {row.id for row, _created in ok_rows}, {request_id}
        )
        with self.Session() as session:
            rows = session.scalars(
                select(School).where(School.id == request_id)
            ).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].name, "竞态同名园")

    def test_same_school_id_concurrent_different_payload_keeps_409(self):
        request_id = uuid.uuid4()
        self.schools.append(request_id)
        outcomes = self._race(
            [
                lambda session: admin_service.create_school(
                    session,
                    self.principal,
                    school_id=request_id,
                    name="竞态园甲名",
                ),
                lambda session: admin_service.create_school(
                    session,
                    self.principal,
                    school_id=request_id,
                    name="竞态园乙名",
                ),
            ]
        )
        self.assertEqual(
            sorted(kind for kind, _ in outcomes), ["conflict", "ok"]
        )
        conflict = next(
            outcome for kind, outcome in outcomes if kind == "conflict"
        )
        row, created = next(
            outcome for kind, outcome in outcomes if kind == "ok"
        )
        self.assertTrue(created)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.code, "SCHOOL_CREATE_CONFLICT")
        self.assertIn(row.name, {"竞态园甲名", "竞态园乙名"})
        with self.Session() as session:
            rows = session.scalars(
                select(School).where(School.id == request_id)
            ).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].name, row.name)

    def test_same_teacher_id_concurrent_across_schools_keeps_409(self):
        teacher_id = uuid.uuid4()
        outcomes = self._race(
            [
                lambda session: admin_service.create_teacher(
                    session,
                    self.principal,
                    school_id=self.school_id,
                    teacher_id=teacher_id,
                    name="竞态教师",
                ),
                lambda session: admin_service.create_teacher(
                    session,
                    self.principal,
                    school_id=self.other_school_id,
                    teacher_id=teacher_id,
                    name="竞态教师",
                ),
            ]
        )
        self.assertEqual(
            sorted(kind for kind, _ in outcomes), ["conflict", "ok"]
        )
        conflict = next(
            outcome for kind, outcome in outcomes if kind == "conflict"
        )
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.code, "TEACHER_CREATE_CONFLICT")
        with self.Session() as session:
            rows = session.scalars(
                select(Teacher).where(Teacher.id == teacher_id)
            ).all()
            self.assertEqual(len(rows), 1)

    def test_same_class_id_concurrent_across_schools_keeps_409(self):
        class_id = uuid.uuid4()
        outcomes = self._race(
            [
                lambda session: admin_service.create_class(
                    session,
                    self.principal,
                    school_id=self.school_id,
                    class_id=class_id,
                    grade="middle",
                    class_number=3,
                ),
                lambda session: admin_service.create_class(
                    session,
                    self.principal,
                    school_id=self.other_school_id,
                    class_id=class_id,
                    grade="middle",
                    class_number=3,
                ),
            ]
        )
        self.assertEqual(
            sorted(kind for kind, _ in outcomes), ["conflict", "ok"]
        )
        conflict = next(
            outcome for kind, outcome in outcomes if kind == "conflict"
        )
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.code, "CLASS_CREATE_CONFLICT")
        with self.Session() as session:
            rows = session.scalars(
                select(Classroom).where(Classroom.id == class_id)
            ).all()
            self.assertEqual(len(rows), 1)
            states = session.scalars(
                select(ClassPromotionState).where(
                    ClassPromotionState.class_id == class_id
                )
            ).all()
            self.assertEqual(len(states), 1)

    def test_same_term_id_concurrent_across_schools_keeps_409(self):
        term_id = uuid.uuid4()
        outcomes = self._race(
            [
                lambda session: admin_service.create_term(
                    session,
                    self.principal,
                    school_id=self.school_id,
                    term_id=term_id,
                    name="竞态学期",
                    start_date=date(2026, 9, 1),
                    end_date=date(2026, 12, 31),
                ),
                lambda session: admin_service.create_term(
                    session,
                    self.principal,
                    school_id=self.other_school_id,
                    term_id=term_id,
                    name="竞态学期",
                    start_date=date(2026, 9, 1),
                    end_date=date(2026, 12, 31),
                ),
            ]
        )
        self.assertEqual(
            sorted(kind for kind, _ in outcomes), ["conflict", "ok"]
        )
        conflict = next(
            outcome for kind, outcome in outcomes if kind == "conflict"
        )
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.code, "TERM_CREATE_CONFLICT")
        with self.Session() as session:
            rows = session.scalars(
                select(CollaborationTerm).where(
                    CollaborationTerm.id == term_id
                )
            ).all()
            self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
