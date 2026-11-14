"""One-time code school binding and explicit class selection boundary."""

from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable

from app.collaboration import admin_service
from app.collaboration.admin_models import AdminCode, AdminUser
from app.collaboration.class_promotion_models import ClassPromotionState
from app.collaboration.config import CollaborationSettings
from app.collaboration.errors import CollaborationError
from app.collaboration.models import (
    Classroom,
    School,
    Teacher,
    TeacherClassMembership,
    TeacherToken,
)


def _schema(engine) -> None:
    tables = (
        School.__table__,
        Classroom.__table__,
        Teacher.__table__,
        TeacherClassMembership.__table__,
        TeacherToken.__table__,
        ClassPromotionState.__table__,
        AdminUser.__table__,
        AdminCode.__table__,
    )
    with engine.begin() as connection:
        for table in tables:
            ddl = str(CreateTable(table).compile(dialect=engine.dialect))
            ddl = ddl.replace("CURRENT_TIMESTAMP(6)", "CURRENT_TIMESTAMP")
            connection.exec_driver_sql(ddl)

class AdminBindingTests(unittest.TestCase):
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

        _schema(self.engine)
        self.Session = sessionmaker(
            bind=self.engine, autoflush=False, expire_on_commit=False
        )
        self.school_id = uuid.uuid4()
        self.other_school_id = uuid.uuid4()
        self.teacher_id = uuid.uuid4()
        self.classroom_id = uuid.uuid4()
        self.admin_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        with self.Session() as session:
            with session.begin():
                session.add_all(
                    [
                        School(id=self.school_id, name="合成绑定幼儿园"),
                        School(id=self.other_school_id, name="其他绑定幼儿园"),
                        Classroom(
                            id=self.classroom_id,
                            school_id=self.school_id,
                            display_name="中二班",
                        ),
                        Teacher(
                            id=self.teacher_id,
                            school_id=self.school_id,
                            display_name="合成教师",
                            active=True,
                        ),
                        TeacherClassMembership(
                            teacher_id=self.teacher_id,
                            school_id=self.school_id,
                            class_id=self.classroom_id,
                            membership_generation=uuid.uuid4(),
                            selected_at=now,
                            updated_at=now,
                        ),
                        AdminUser(
                            id=self.admin_id,
                            username="admin-binding",
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

    def _principal(self) -> admin_service.AdminPrincipal:
        return admin_service.AdminPrincipal(
            admin_id=self.admin_id,
            username="admin-binding",
            session_id=uuid.uuid4(),
            csrf_hash="C" * 64,
        )

    def _membership_count(self) -> int:
        with self.Session() as session:
            return int(
                session.scalar(
                    select(func.count()).select_from(TeacherClassMembership)
                )
                or 0
            )

    def test_join_code_binds_school_without_auto_selecting_class(self):
        with self.Session() as session:
            issued = admin_service.issue_code(
                session,
                self.settings,
                self._principal(),
                school_id=self.school_id,
                teacher_id=self.teacher_id,
                purpose="join",
            )
        with self.Session() as session:
            code = session.get(AdminCode, issued.code_id)
            self.assertEqual(code.school_id, self.school_id)
            self.assertEqual(code.teacher_id, self.teacher_id)
        before = self._membership_count()
        with self.Session() as session:
            result = admin_service.redeem_code(
                session, self.settings, issued.code
            )
        self.assertEqual(result.school_id, self.school_id)
        self.assertEqual(result.school_name, "合成绑定幼儿园")
        self.assertIsNone(result.membership)
        self.assertEqual(self._membership_count(), before)
        with self.Session() as session:
            membership = session.get(TeacherClassMembership, self.teacher_id)
            self.assertEqual(membership.class_id, self.classroom_id)
            self.assertEqual(membership.school_id, self.school_id)
            self.assertEqual(
                session.get(Teacher, self.teacher_id).school_id, self.school_id
            )

    def test_recovery_reads_current_membership_without_creating_one(self):
        before = self._membership_count()
        with self.Session() as session:
            issued = admin_service.issue_code(
                session,
                self.settings,
                self._principal(),
                school_id=self.school_id,
                teacher_id=self.teacher_id,
                purpose="recovery",
            )
        with self.Session() as session:
            result = admin_service.redeem_code(
                session, self.settings, issued.code
            )
        self.assertIsNotNone(result.membership)
        self.assertEqual(result.membership.class_id, self.classroom_id)
        self.assertEqual(self._membership_count(), before)

    def test_code_requires_teacher_in_selected_school(self):
        with self.Session() as session:
            with self.assertRaises(CollaborationError) as raised:
                admin_service.issue_code(
                    session,
                    self.settings,
                    self._principal(),
                    school_id=self.other_school_id,
                    teacher_id=self.teacher_id,
                    purpose="join",
                )
        self.assertEqual(raised.exception.status_code, 422)
        self.assertIn("不属于", raised.exception.message)


if __name__ == "__main__":
    unittest.main()
