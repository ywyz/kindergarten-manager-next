"""Administrator school-name maintenance and prompt display labels."""

from __future__ import annotations

import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi import Response
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable

from app.collaboration import admin_api, admin_service, prompt_release_api
from app.collaboration.admin_models import AdminSession, AdminUser
from app.collaboration.errors import CollaborationError
from app.collaboration.models import Classroom, School

def _schema(engine) -> None:
    tables = (
        School.__table__,
        Classroom.__table__,
        AdminUser.__table__,
        AdminSession.__table__,
    )
    with engine.begin() as connection:
        for table in tables:
            ddl = str(CreateTable(table).compile(dialect=engine.dialect))
            ddl = ddl.replace("CURRENT_TIMESTAMP(6)", "CURRENT_TIMESTAMP")
            connection.exec_driver_sql(ddl)


class AdminSchoolTests(unittest.TestCase):
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
        self.classroom_id = uuid.uuid4()
        self.admin_id = uuid.uuid4()
        with self.Session() as session:
            with session.begin():
                session.add_all(
                    [
                        School(id=self.school_id, name="合成幼儿园"),
                        School(id=self.other_school_id, name="其他幼儿园"),
                        Classroom(
                            id=self.classroom_id,
                            school_id=self.school_id,
                            display_name="中一班",
                        ),
                        AdminUser(
                            id=self.admin_id,
                            username="admin-school",
                            password_hash="synthetic-password-hash",
                            active=True,
                            failed_attempts=0,
                        ),
                    ]
                )

    def _principal(self) -> admin_service.AdminPrincipal:
        return admin_service.AdminPrincipal(
            admin_id=self.admin_id,
            username="admin-school",
            session_id=uuid.uuid4(),
            csrf_hash="C" * 64,
        )

    def test_rename_preserves_ids_and_conflict_semantics(self):
        with self.Session() as session:
            updated = admin_service.update_school_name(
                session,
                self._principal(),
                school_id=self.school_id,
                expected_name="合成幼儿园",
                new_name="合成幼儿园（新名）",
            )
            self.assertEqual(updated.id, self.school_id)
            self.assertEqual(updated.name, "合成幼儿园（新名）")
        with self.Session() as session:
            classroom = session.get(Classroom, self.classroom_id)
            self.assertIsNotNone(classroom)
            self.assertEqual(classroom.school_id, self.school_id)
            self.assertEqual(classroom.display_name, "中一班")
            self.assertEqual(
                session.get(School, self.school_id).name, "合成幼儿园（新名）"
            )

        with self.Session() as session:
            retried = admin_service.update_school_name(
                session,
                self._principal(),
                school_id=self.school_id,
                expected_name="合成幼儿园",
                new_name="合成幼儿园（新名）",
            )
            self.assertEqual(retried.name, "合成幼儿园（新名）")

        with self.Session() as session:
            with self.assertRaises(CollaborationError) as raised:
                admin_service.update_school_name(
                    session,
                    self._principal(),
                    school_id=self.school_id,
                    expected_name="合成幼儿园",
                    new_name="另一个名称",
                )
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.code, "SCHOOL_NAME_CONFLICT")
        self.assertEqual(
            raised.exception.details["current_name"], "合成幼儿园（新名）"
        )

    def test_validation_unknown_school_and_route_csrf_dependency(self):
        with self.Session() as session:
            with self.assertRaises(CollaborationError) as empty:
                admin_service.update_school_name(
                    session,
                    self._principal(),
                    school_id=self.school_id,
                    expected_name="合成幼儿园",
                    new_name="   ",
                )
            self.assertEqual(empty.exception.status_code, 422)
            with self.assertRaises(CollaborationError) as too_long:
                admin_service.update_school_name(
                    session,
                    self._principal(),
                    school_id=self.school_id,
                    expected_name="合成幼儿园",
                    new_name="名" * 121,
                )
            self.assertEqual(too_long.exception.status_code, 422)
            with self.assertRaises(CollaborationError) as unknown:
                admin_service.update_school_name(
                    session,
                    self._principal(),
                    school_id=uuid.uuid4(),
                    expected_name="不存在",
                    new_name="新名",
                )
            self.assertEqual(unknown.exception.status_code, 404)
            self.assertEqual(unknown.exception.code, "SCHOOL_NOT_FOUND")

        source = Path(admin_api.__file__).read_text(encoding="utf-8")
        route = source[
            source.index("def admin_update_school("):
            source.index("def admin_teachers(")
        ]
        self.assertIn("Depends(get_admin_csrf_principal)", route)

    def test_route_returns_school_out(self):
        with self.Session() as session:
            result = admin_api.admin_update_school(
                self.school_id,
                admin_api.AdminSchoolUpdateIn(
                    expected_name="合成幼儿园",
                    new_name="路由改名",
                ),
                Response(),
                session,
                self._principal(),
            )
        self.assertEqual(result.school_id, self.school_id)
        self.assertEqual(result.name, "路由改名")

    def test_admin_page_has_school_name_entry(self):
        page = (
            Path(__file__).resolve().parents[2]
            / "app"
            / "collaboration"
            / "admin_page.html"
        ).read_text(encoding="utf-8")
        self.assertIn('id="school-list"', page)
        self.assertIn("已有园所名称", page)
        self.assertIn("保存园所名称", page)
        self.assertIn("稳定园所 ID", page)

    def test_prompt_labels_cover_catalogue_and_unknown_fallback(self):
        from app.local.prompt_package import (
            PACKAGE_OPEN_GUIDANCE_FIELDS,
            PACKAGE_OPEN_TASK_TYPES,
        )

        for task_type in PACKAGE_OPEN_TASK_TYPES:
            self.assertNotEqual(
                prompt_release_api.task_display_label(task_type), "其他任务"
            )
            for field_name in PACKAGE_OPEN_GUIDANCE_FIELDS[task_type]:
                label = prompt_release_api.field_display_label(field_name)
                self.assertNotEqual(label, "其他字段")
                self.assertNotEqual(label, field_name)
        self.assertEqual(
            prompt_release_api.task_display_label("legacy_task"), "其他任务"
        )
        self.assertEqual(
            prompt_release_api.field_display_label("legacy_field"), "其他字段"
        )

    def test_workspace_response_adds_labels_without_changing_ids(self):
        workspace = {
            "editable": [
                {
                    "task_type": "daily_lesson_split",
                    "fields": {"theme": "主题文字", "legacy_key": "旧字段"},
                }
            ],
            "drafts": [],
            "releases": [],
            "latest": {"preview": None, "stable": None},
        }
        with patch.object(
            prompt_release_api, "_require_configured", return_value=None
        ), patch.object(
            prompt_release_api, "get_workspace", return_value=workspace
        ):
            result = prompt_release_api.read_prompt_releases(
                Response(), session=None, _principal=None
            )
        item = result.editable[0]
        self.assertEqual(item.task_type, "daily_lesson_split")
        self.assertEqual(item.task_label, "日计划·教案拆分")
        self.assertEqual(item.fields["theme"], "主题文字")
        self.assertEqual(item.field_labels["theme"], "活动主题")
        self.assertEqual(item.field_labels["legacy_key"], "其他字段")


if __name__ == "__main__":
    unittest.main()
