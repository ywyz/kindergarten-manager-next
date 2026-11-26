"""Administrator entity deletion (2026-11-26) service tests.

Synthetic in-memory SQLite with the ORM schema.  Covers the three delete
outcomes: hard delete when the entity has no referencing rows, 409
DELETE_BLOCKED with counts when history exists, and deactivation (hidden +
unusable) after the explicit confirmation.  Deactivated entities cannot be
listed, renamed, issued codes or authenticated, and empty entities are gone.
No MySQL, network or real secret is involved.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import timedelta, timezone

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.collaboration import admin_service
from app.collaboration.admin_models import AdminCode, AdminUser
from app.collaboration.class_promotion_models import (
    ClassPromotionHistory,
    ClassPromotionOperation,
    ClassPromotionState,
    CollaborationTerm,
)
from app.collaboration.errors import CollaborationError
from app.collaboration.models import (
    Classroom,
    CollaborationOperation,
    School,
    Teacher,
    TeacherClassMembership,
    TeacherGameConfig,
    TeacherToken,
)
from app.collaboration.weekly_plan_models import (
    WeeklyPlanConfirmation,
    WeeklyPlanOperation,
    WeeklyPlanWeek,
)


def _utcnow():
    from app.collaboration.models import _utcnow

    return _utcnow()


class AdminDeletionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.addCleanup(self.engine.dispose)

        @event.listens_for(self.engine, "connect")
        def _char_length(dbapi_connection, _record):
            dbapi_connection.create_function("char_length", 1, len)

        with self.engine.begin() as connection:
            for table in (
                School.__table__,
                Classroom.__table__,
                Teacher.__table__,
                TeacherClassMembership.__table__,
                TeacherToken.__table__,
                TeacherGameConfig.__table__,
                CollaborationOperation.__table__,
                CollaborationTerm.__table__,
                ClassPromotionState.__table__,
                ClassPromotionHistory.__table__,
                ClassPromotionOperation.__table__,
                WeeklyPlanWeek.__table__,
                WeeklyPlanConfirmation.__table__,
                WeeklyPlanOperation.__table__,
                AdminCode.__table__,
                AdminUser.__table__,
            ):
                from sqlalchemy.schema import CreateTable

                ddl = str(
                    CreateTable(table).compile(dialect=self.engine.dialect)
                )
                ddl = ddl.replace("CURRENT_TIMESTAMP(6)", "CURRENT_TIMESTAMP")
                connection.exec_driver_sql(ddl)

        self.Session = sessionmaker(
            bind=self.engine, autoflush=False, expire_on_commit=False
        )
        self.admin_id = uuid.uuid4()
        with self.Session() as session:
            with session.begin():
                session.add(
                    AdminUser(
                        id=self.admin_id,
                        username="admin-delete",
                        password_hash="synthetic-password-hash",
                        active=True,
                        failed_attempts=0,
                    )
                )

    def _principal(self) -> admin_service.AdminPrincipal:
        return admin_service.AdminPrincipal(
            admin_id=self.admin_id,
            username="admin-delete",
            session_id=uuid.uuid4(),
            csrf_hash="C" * 64,
        )

    def _add_school(self, name="合成幼儿园") -> uuid.UUID:
        school_id = uuid.uuid4()
        with self.Session() as session:
            with session.begin():
                session.add(School(id=school_id, name=name))
        return school_id

    def _add_teacher(self, school_id: uuid.UUID, name="王老师") -> uuid.UUID:
        teacher_id = uuid.uuid4()
        with self.Session() as session:
            with session.begin():
                session.add(
                    Teacher(
                        id=teacher_id,
                        school_id=school_id,
                        display_name=name,
                        active=True,
                    )
                )
        return teacher_id

    def _add_class(self, school_id: uuid.UUID, name="中一班") -> uuid.UUID:
        class_id = uuid.uuid4()
        with self.Session() as session:
            with session.begin():
                session.add(
                    Classroom(
                        id=class_id,
                        school_id=school_id,
                        display_name=name,
                    )
                )
        return class_id

    def _rows(self, model):
        with self.Session() as session:
            return list(session.scalars(select(model)).all())

    def test_empty_school_is_deleted_outright(self):
        school_id = self._add_school()
        with self.Session() as session:
            result = admin_service.delete_school(
                session, self._principal(), school_id=school_id
            )
        self.assertEqual(result["outcome"], "deleted")
        self.assertEqual(self._rows(School), [])

    def test_school_with_history_blocks_then_deactivates(self):
        school_id = self._add_school()
        self._add_teacher(school_id)
        self._add_class(school_id)
        with self.Session() as session:
            with self.assertRaises(CollaborationError) as ctx:
                admin_service.delete_school(
                    session, self._principal(), school_id=school_id
                )
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.code, "SCHOOL_DELETE_BLOCKED")
        self.assertEqual(len(self._rows(School)), 1)
        self.assertEqual(len(self._rows(Teacher)), 1)

        with self.Session() as session:
            result = admin_service.delete_school(
                session,
                self._principal(),
                school_id=school_id,
                confirm_deactivate=True,
            )
        self.assertEqual(result["outcome"], "deactivated")
        with self.Session() as session:
            self.assertIsNotNone(session.get(School, school_id).deleted_at)
            self.assertEqual(admin_service.list_schools(session), [])
            self.assertEqual(
                admin_service.list_teachers(session, school_id), []
            )
            session.rollback()
            with self.assertRaises(CollaborationError):
                admin_service.update_school_name(
                    session,
                    self._principal(),
                    school_id=school_id,
                    expected_name="合成幼儿园",
                    new_name="新名",
                )
            with self.assertRaises(CollaborationError) as ctx:
                admin_service.delete_school(
                    session, self._principal(), school_id=school_id
                )
            self.assertEqual(ctx.exception.status_code, 404)

    def test_teacher_with_history_deactivates_and_revokes_tokens(self):
        school_id = self._add_school()
        teacher_id = self._add_teacher(school_id)
        class_id = self._add_class(school_id)
        with self.Session() as session:
            with session.begin():
                session.add(
                    TeacherClassMembership(
                        teacher_id=teacher_id,
                        school_id=school_id,
                        class_id=class_id,
                    )
                )
                session.add(
                    TeacherToken(
                        id=uuid.uuid4(),
                        teacher_id=teacher_id,
                        token_hash="a" * 64,
                    )
                )
        with self.Session() as session:
            with self.assertRaises(CollaborationError) as ctx:
                admin_service.delete_teacher(
                    session,
                    self._principal(),
                    school_id=school_id,
                    teacher_id=teacher_id,
                )
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.code, "TEACHER_DELETE_BLOCKED")

        with self.Session() as session:
            result = admin_service.delete_teacher(
                session,
                self._principal(),
                school_id=school_id,
                teacher_id=teacher_id,
                confirm_deactivate=True,
            )
        self.assertEqual(result["outcome"], "deactivated")
        with self.Session() as session:
            teacher = session.get(Teacher, teacher_id)
            self.assertFalse(teacher.active)
            self.assertIsNotNone(teacher.deleted_at)
            token = session.scalars(select(TeacherToken)).one()
            self.assertIsNotNone(token.revoked_at)
            self.assertEqual(
                admin_service.list_teachers(session, school_id), []
            )
            session.rollback()
            with self.assertRaises(CollaborationError):
                admin_service.delete_teacher(
                    session,
                    self._principal(),
                    school_id=school_id,
                    teacher_id=teacher_id,
                )


class ArchivedEntityOrdinaryFlowsTests(AdminDeletionTests):
    """Ordinary teacher/weekly/promotion routes refuse archived entities.

    History stays shared (rows untouched); the teacher reselects a listed
    (live) class and every ordinary read/write works again.
    """

    def _archived_setup(self):
        from app.collaboration.class_promotion_models import ClassPromotionState

        school_id = self._add_school()
        teacher_id = self._add_teacher(school_id)
        class_id = self._add_class(school_id)
        with self.Session() as session:
            with session.begin():
                session.add(
                    TeacherClassMembership(
                        teacher_id=teacher_id,
                        school_id=school_id,
                        class_id=class_id,
                    ),
                    ClassPromotionState(
                        class_id=class_id,
                        school_id=school_id,
                        class_number=1,
                        base_grade="middle",
                        version=1,
                    ),
                )
        with self.Session() as session:
            admin_service.delete_class(
                session,
                self._principal(),
                school_id=school_id,
                class_id=class_id,
                confirm_deactivate=True,
            )
        return school_id, teacher_id, class_id

    def _principal_for(self, teacher_id) -> object:
        from app.collaboration.security import TeacherPrincipal

        return TeacherPrincipal(
            teacher_id=teacher_id,
            school_id=self._school_id_for(teacher_id),
            display_name="王老师",
            school_name="合成幼儿园",
            token_id=uuid.uuid4(),
        )

    def _school_id_for(self, teacher_id) -> object:
        with self.Session() as session:
            return session.get(Teacher, teacher_id).school_id

    def test_list_classmates_refuses_archived_class(self):
        from app.collaboration import service as collaboration_service
        from app.collaboration.errors import CollaborationError

        _school_id, teacher_id, _class_id = self._archived_setup()
        with self.Session() as session:
            with self.assertRaises(CollaborationError) as ctx:
                collaboration_service.list_classmates(
                    session, self._principal_for(teacher_id)
                )
        self.assertEqual(ctx.exception.code, "MEMBERSHIP_CHANGED")

    def test_get_promotion_refuses_archived_class(self):
        from app.collaboration import class_promotion_service
        from app.collaboration.errors import CollaborationError

        _school_id, teacher_id, _class_id = self._archived_setup()
        with self.Session() as session:
            with self.assertRaises(CollaborationError) as ctx:
                class_promotion_service.get_promotion(
                    session, self._principal_for(teacher_id)
                )
        self.assertEqual(ctx.exception.code, "MEMBERSHIP_CHANGED")

    def test_weekly_read_route_refuses_archived_class(self):
        from app.collaboration import weekly_plan_service
        from app.collaboration.errors import CollaborationError

        school_id, teacher_id, class_id = self._archived_setup()
        with self.Session() as session:
            with self.assertRaises(CollaborationError) as ctx:
                weekly_plan_service.get_weekly_plan(
                    session,
                    self._principal_for(teacher_id),
                    class_id,
                    uuid.uuid4(),
                    "2026-11-23",
                )
        self.assertEqual(ctx.exception.code, "CLASS_NOT_FOUND")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_admin_classes_under_archived_school_are_hidden(self):
        school_id, _teacher_id, class_id = self._archived_setup()
        with self.Session() as session:
            self.assertEqual(admin_service.list_classes(session, school_id), [])
        # History is untouched: the archived rows remain in place.
        self.assertEqual(len(self._rows(Classroom)), 1)

    def test_reselect_live_class_restores_ordinary_flows(self):
        from app.collaboration import service as collaboration_service
        from app.collaboration.class_promotion_models import ClassPromotionState
        from app.collaboration.class_promotion_service import get_promotion

        school_id, teacher_id, _archived = self._archived_setup()
        live_class_id = self._add_class(school_id, name="大二班")
        with self.Session() as session:
            with session.begin():
                session.add(
                    ClassPromotionState(
                        class_id=live_class_id,
                        school_id=school_id,
                        class_number=2,
                        base_grade="large",
                        version=1,
                    )
                )
        with self.Session() as session:
            membership = collaboration_service.select_class(
                session, self._principal_for(teacher_id), live_class_id
            )
            self.assertEqual(membership.class_id, live_class_id)
            view = get_promotion(session, self._principal_for(teacher_id))
            self.assertEqual(view.class_id, live_class_id)
            self.assertEqual(view.grade, "large")
