"""Administrator term-name maintenance on an isolated SQLite schema."""

from __future__ import annotations

import os
import unittest
import uuid
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable

from app.collaboration import admin_api, admin_service
from app.collaboration.admin_models import AdminSession, AdminUser
from app.collaboration.class_promotion_models import CollaborationTerm
from app.collaboration.class_promotion_service import _terms
from app.collaboration.config import CollaborationSettings
from app.collaboration.errors import CollaborationError
from app.collaboration.models import School


def _schema(engine) -> None:
    tables = (
        School.__table__,
        CollaborationTerm.__table__,
        AdminUser.__table__,
        AdminSession.__table__,
    )
    with engine.begin() as connection:
        for table in tables:
            ddl = str(CreateTable(table).compile(dialect=engine.dialect))
            ddl = ddl.replace("CURRENT_TIMESTAMP(6)", "CURRENT_TIMESTAMP")
            connection.exec_driver_sql(ddl)


class AdminTermTests(unittest.TestCase):
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
        self.term_id = uuid.uuid4()
        self.other_term_id = uuid.uuid4()
        self.admin_id = uuid.uuid4()
        with self.Session() as session:
            with session.begin():
                session.add_all(
                    [
                        School(id=self.school_id, name="合成幼儿园"),
                        School(id=self.other_school_id, name="其他幼儿园"),
                        CollaborationTerm(
                            id=self.term_id,
                            school_id=self.school_id,
                            name="2026 秋季学期",
                            start_date=date(2026, 9, 1),
                            end_date=date(2027, 1, 31),
                        ),
                        CollaborationTerm(
                            id=self.other_term_id,
                            school_id=self.other_school_id,
                            name="其他园学期",
                            start_date=date(2026, 9, 1),
                            end_date=date(2027, 1, 31),
                        ),
                        AdminUser(
                            id=self.admin_id,
                            username="admin-term",
                            password_hash=admin_service.hash_password(
                                "synthetic-admin-password-123"
                            ),
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
        self.app = FastAPI()

        @self.app.exception_handler(CollaborationError)
        async def _collaboration_error(
            _request: Request, exc: CollaborationError
        ) -> JSONResponse:
            payload = {
                "error": {"code": exc.code, "message": exc.message}
            }
            if exc.details:
                payload["error"]["details"] = exc.details
            return JSONResponse(
                status_code=exc.status_code,
                content=payload,
                headers=exc.headers,
            )

        self.app.include_router(admin_api.router)
        self.app.dependency_overrides[admin_api.get_session] = self._session_dep
        self.app.dependency_overrides[admin_api.get_settings] = lambda: self.settings
        self._secure = os.environ.get("KGM_COLLAB_ADMIN_COOKIE_SECURE")
        os.environ["KGM_COLLAB_ADMIN_COOKIE_SECURE"] = "0"
        self.addCleanup(self._restore_env)

    def _restore_env(self) -> None:
        if self._secure is None:
            os.environ.pop("KGM_COLLAB_ADMIN_COOKIE_SECURE", None)
        else:
            os.environ["KGM_COLLAB_ADMIN_COOKIE_SECURE"] = self._secure

    def _session_dep(self):
        session = self.Session()
        try:
            yield session
        finally:
            session.close()

    def _client(self) -> TestClient:
        return TestClient(self.app, base_url="http://testserver")

    def _login(self, client: TestClient) -> str:
        response = client.post(
            "/api/collaboration/admin/login",
            json={
                "username": "admin-term",
                "password": "synthetic-admin-password-123",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["csrf_token"]

    def test_list_and_rename_preserve_id_dates_and_conflict_semantics(self):
        client = self._client()
        csrf = self._login(client)
        listing = client.get(
            f"/api/collaboration/admin/schools/{self.school_id}/terms"
        )
        self.assertEqual(listing.status_code, 200, listing.text)
        before = listing.json()[0]
        self.assertEqual(before["term_id"], str(self.term_id))
        self.assertEqual(before["name"], "2026 秋季学期")
        self.assertEqual(before["start_date"], "2026-09-01")
        self.assertEqual(before["end_date"], "2027-01-31")

        path = (
            f"/api/collaboration/admin/schools/{self.school_id}/terms/"
            f"{self.term_id}"
        )
        changed = client.patch(
            path,
            json={
                "expected_name": "2026 秋季学期",
                "new_name": "2026 秋季学期（修订）",
            },
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(changed.json()["term_id"], str(self.term_id))
        self.assertEqual(changed.json()["start_date"], "2026-09-01")
        self.assertEqual(changed.json()["end_date"], "2027-01-31")
        self.assertEqual(changed.json()["name"], "2026 秋季学期（修订）")
        with self.Session() as session:
            overview_terms = _terms(session, self.school_id)
        self.assertEqual(overview_terms[0].name, "2026 秋季学期（修订）")
        self.assertEqual(overview_terms[0].start_date, date(2026, 9, 1))

        # A lost response may be retried with the original old-name baseline;
        # the current name already equals the requested new name.
        retried = client.patch(
            path,
            json={
                "expected_name": "2026 秋季学期",
                "new_name": "2026 秋季学期（修订）",
            },
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(retried.status_code, 200, retried.text)
        self.assertEqual(retried.json()["name"], "2026 秋季学期（修订）")

        conflict = client.patch(
            path,
            json={
                "expected_name": "2026 秋季学期",
                "new_name": "另一个名称",
            },
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertEqual(conflict.json()["error"]["code"], "TERM_NAME_CONFLICT")
        self.assertEqual(
            conflict.json()["error"]["details"]["current_name"],
            "2026 秋季学期（修订）",
        )

    def test_cross_school_id_invalid_name_and_auth_are_rejected(self):
        client = self._client()
        csrf = self._login(client)
        cross = client.patch(
            f"/api/collaboration/admin/schools/{self.school_id}/terms/"
            f"{self.other_term_id}",
            json={"expected_name": "其他园学期", "new_name": "改名"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(cross.status_code, 404, cross.text)
        self.assertEqual(cross.json()["error"]["code"], "TERM_NOT_FOUND")

        path = (
            f"/api/collaboration/admin/schools/{self.school_id}/terms/"
            f"{self.term_id}"
        )
        empty = client.patch(
            path,
            json={"expected_name": "2026 秋季学期", "new_name": "   "},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(empty.status_code, 422, empty.text)
        too_long = client.patch(
            path,
            json={"expected_name": "2026 秋季学期", "new_name": "名" * 81},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(too_long.status_code, 422, too_long.text)

        anonymous = self._client()
        denied = anonymous.patch(
            path,
            json={"expected_name": "2026 秋季学期", "new_name": "匿名改名"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(denied.status_code, 401, denied.text)
        teacher = self._client()
        denied_teacher = teacher.patch(
            path,
            json={"expected_name": "2026 秋季学期", "new_name": "教师改名"},
            headers={
                "X-CSRF-Token": csrf,
                "Authorization": "Bearer synthetic-teacher-token",
            },
        )
        self.assertEqual(denied_teacher.status_code, 401, denied_teacher.text)

    def test_school_with_no_terms_returns_explicit_empty_list(self):
        empty_school = uuid.uuid4()
        with self.Session() as session:
            with session.begin():
                session.add(School(id=empty_school, name="无学期幼儿园"))
        client = self._client()
        self._login(client)
        response = client.get(
            f"/api/collaboration/admin/schools/{empty_school}/terms"
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), [])

    def test_admin_page_has_minimal_term_name_entry(self):
        page = (
            Path(__file__).resolve().parents[2]
            / "app"
            / "collaboration"
            / "admin_page.html"
        ).read_text(encoding="utf-8")
        self.assertIn('id="term-school"', page)
        self.assertIn('id="term-list"', page)
        self.assertIn("已有学期名称", page)
        self.assertIn("该园所暂无学期", page)
        self.assertIn("/terms/", page)
        self.assertIn("保存名称", page)
