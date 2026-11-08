"""Administrator login and one-time code tests.

Pure tests run without a database.  The MySQL class only starts when
``KGM_COLLAB_TEST_DATABASE_URL`` is explicitly supplied by the operator and a
committed base collaboration schema is already present.  It never creates or
migrates a database and never falls back to SQLite.
"""

from __future__ import annotations

import os
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.collaboration import admin_service


class PureAdminCodeTests(unittest.TestCase):
    def test_password_hash_is_scrypt_and_verifies(self):
        password = "synthetic-admin-password-123"
        encoded = admin_service.hash_password(password)
        self.assertTrue(encoded.startswith("scrypt$"))
        self.assertNotIn(password, encoded)
        self.assertTrue(admin_service.verify_password(password, encoded))
        self.assertFalse(admin_service.verify_password("wrong-password-123", encoded))

    def test_short_password_and_bad_username_are_rejected(self):
        with self.assertRaises(ValueError):
            admin_service.hash_password("short")
        with self.assertRaises(ValueError):
            admin_service.validate_admin_username("a!")
        self.assertEqual(
            admin_service.validate_admin_username("ops.admin-1"), "ops.admin-1"
        )

    def test_code_and_session_digests_are_keyed(self):
        class Settings:
            token_pepper = "A" * 32

        first = admin_service.digest_code(Settings(), "one-time-code")
        second = admin_service.digest_code(Settings(), "one-time-code")
        self.assertEqual(first, second)
        self.assertNotIn("one-time-code", first)
        self.assertEqual(len(first), 64)
        self.assertNotEqual(
            admin_service.digest_session_token(Settings(), "session-value"),
            admin_service.digest_csrf_token(Settings(), "session-value"),
        )

    def test_migration_stores_only_digests_and_is_mysql_default_database(self):
        root = Path(__file__).resolve().parents[2]
        sql = (
            root
            / "migrations_collaboration"
            / "mysql"
            / "0002_admin_codes.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE admin_users", sql)
        self.assertIn("CREATE TABLE admin_sessions", sql)
        self.assertIn("CREATE TABLE admin_codes", sql)
        self.assertIn("code_hash CHAR(64)", sql)
        self.assertIn(
            "teacher_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin", sql
        )
        self.assertIn(
            "school_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin", sql
        )
        self.assertIn(
            "FOREIGN KEY (teacher_id, school_id)\n"
            "        REFERENCES teachers(id, school_id)",
            sql,
        )
        self.assertNotIn("fk_admin_codes_teacher FOREIGN KEY", sql)
        self.assertNotIn("code_plaintext", sql)
        self.assertNotIn("password VARCHAR", sql)
        self.assertNotIn("collaboration.", sql)

    def test_admin_page_keeps_credentials_out_of_urls(self):
        page = (
            Path(__file__).resolve().parents[2]
            / "app"
            / "collaboration"
            / "admin_page.html"
        ).read_text(encoding="utf-8")
        self.assertIn(
            '<form id="login-form" method="post" action="/admin"', page
        )
        self.assertIn('type="password"', page)
        self.assertNotIn("?password=", page)
        self.assertNotIn("console.log", page)
        self.assertIn("kgm_admin_csrf", page)

    def test_login_and_redeem_lock_before_reading_volatile_state(self):
        service = (
            Path(__file__).resolve().parents[2]
            / "app"
            / "collaboration"
            / "admin_service.py"
        ).read_text(encoding="utf-8")
        login = service.index("def login_admin")
        redeem = service.index("def redeem_code")
        self.assertIn(".with_for_update()", service[login:redeem])
        locked = service.index(".with_for_update()", redeem)
        now_after_lock = service.index("now = _utcnow()", redeem)
        self.assertGreater(now_after_lock, locked)


@unittest.skipUnless(
    os.environ.get("KGM_COLLAB_TEST_DATABASE_URL"),
    "requires explicit KGM_COLLAB_TEST_DATABASE_URL and an isolated MySQL schema",
)
class MySQLAdminCodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from sqlalchemy import delete
        from sqlalchemy.orm import sessionmaker

        from app.collaboration.admin_models import AdminCode, AdminSession, AdminUser
        from app.collaboration.app import create_collaboration_app
        from app.collaboration.config import CollaborationSettings
        from app.collaboration.models import (
            Classroom,
            School,
            Teacher,
            TeacherClassMembership,
            TeacherToken,
        )

        cls.delete = delete
        cls.AdminCode = AdminCode
        cls.AdminSession = AdminSession
        cls.AdminUser = AdminUser
        cls.Classroom = Classroom
        cls.School = School
        cls.Teacher = Teacher
        cls.TeacherClassMembership = TeacherClassMembership
        cls.TeacherToken = TeacherToken
        cls.TestClient = TestClient

        os.environ["KGM_COLLAB_ADMIN_COOKIE_SECURE"] = "0"
        settings = CollaborationSettings(
            database_url=os.environ["KGM_COLLAB_TEST_DATABASE_URL"],
            token_pepper=os.environ.get(
                "KGM_COLLAB_TEST_TOKEN_PEPPER", "T" * 32
            ),
            preview_secret=os.environ.get(
                "KGM_COLLAB_TEST_PREVIEW_SECRET", "P" * 32
            ),
            preview_ttl_seconds=600,
        )
        cls.app = create_collaboration_app(settings)
        cls.factory = sessionmaker(
            bind=cls.app.state.engine,
            autoflush=False,
            expire_on_commit=False,
        )
        cls.school_ids = []
        cls.teacher_ids = []
        cls.admin_ids = []
        cls.classroom_ids = []

        with cls.factory() as session:
            cls.school = cls._make_school(session, "Admin test school")
            cls.school2 = cls._make_school(session, "Admin other school")
            cls.teacher = cls._make_teacher(session, cls.school.id, "Synthetic Teacher")
            cls.teacher2 = cls._make_teacher(session, cls.school.id, "Synthetic Teacher 2")
            cls.classroom = cls._make_classroom(session, cls.school.id, "中一班")
            cls.admin = cls._make_admin(session, "admin-primary")
            cls.admin_locked = cls._make_admin(session, "admin-locked")
            cls.admin_expiry = cls._make_admin(session, "admin-expiry")
            cls.admin_logout = cls._make_admin(session, "admin-logout")

    @classmethod
    def tearDownClass(cls):
        with cls.factory() as session:
            session.execute(
                cls.delete(cls.AdminCode).where(
                    cls.AdminCode.created_by_admin_id.in_(cls.admin_ids)
                )
            )
            session.execute(
                cls.delete(cls.AdminSession).where(
                    cls.AdminSession.admin_id.in_(cls.admin_ids)
                )
            )
            session.execute(
                cls.delete(cls.TeacherToken).where(
                    cls.TeacherToken.teacher_id.in_(cls.teacher_ids)
                )
            )
            session.execute(
                cls.delete(cls.TeacherClassMembership).where(
                    cls.TeacherClassMembership.teacher_id.in_(cls.teacher_ids)
                )
            )
            session.execute(
                cls.delete(cls.Classroom).where(
                    cls.Classroom.id.in_(cls.classroom_ids)
                )
            )
            session.execute(
                cls.delete(cls.Teacher).where(cls.Teacher.id.in_(cls.teacher_ids))
            )
            session.execute(
                cls.delete(cls.School).where(cls.School.id.in_(cls.school_ids))
            )
            session.execute(
                cls.delete(cls.AdminUser).where(cls.AdminUser.id.in_(cls.admin_ids))
            )
            session.commit()

    @classmethod
    def _make_school(cls, session, name):
        row = cls.School(id=uuid.uuid4(), name=name)
        session.add(row)
        session.commit()
        cls.school_ids.append(row.id)
        return row

    @classmethod
    def _make_teacher(cls, session, school_id, name):
        row = cls.Teacher(
            id=uuid.uuid4(), school_id=school_id, display_name=name, active=True
        )
        session.add(row)
        session.commit()
        cls.teacher_ids.append(row.id)
        return row

    @classmethod
    def _make_classroom(cls, session, school_id, name):
        row = cls.Classroom(
            id=uuid.uuid4(), school_id=school_id, display_name=name
        )
        session.add(row)
        session.commit()
        cls.classroom_ids.append(row.id)
        return row

    @classmethod
    def _make_admin(cls, session, username):
        row = admin_service.bootstrap_admin(
            session, username, "synthetic-admin-password-123"
        )
        cls.admin_ids.append(row.id)
        return row

    def _login(self, username="admin-primary", password="synthetic-admin-password-123"):
        client = self.TestClient(self.app)
        response = client.post(
            "/api/collaboration/admin/login",
            json={"username": username, "password": password},
        )
        return client, response

    def _csrf(self, response):
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["csrf_token"]

    def _issue(self, client, csrf, teacher, school=None, purpose="join"):
        return client.post(
            "/api/collaboration/admin/codes",
            headers={"X-CSRF-Token": csrf},
            json={
                "school_id": str((school or self.school).id),
                "teacher_id": str(teacher.id),
                "purpose": purpose,
            },
        )

    def test_login_cookie_flags_and_no_store(self):
        client, response = self._login()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("cache-control"), "no-store")
        cookies = response.headers.get_list("set-cookie")
        session_cookie = next(c for c in cookies if c.startswith("kgm_admin_session="))
        csrf_cookie = next(c for c in cookies if c.startswith("kgm_admin_csrf="))
        self.assertIn("HttpOnly", session_cookie)
        self.assertIn("SameSite=strict", session_cookie)
        self.assertIn("Path=/", session_cookie)
        self.assertNotIn("HttpOnly", csrf_cookie)
        self.assertTrue(client.get("/api/collaboration/admin/session").status_code == 200)
        page = client.get("/admin")
        self.assertEqual(page.status_code, 200)
        self.assertIn("管理员登录", page.text)

    def test_anonymous_and_teacher_bearer_cannot_issue(self):
        anonymous = self.TestClient(self.app)
        self.assertEqual(
            anonymous.post(
                "/api/collaboration/admin/codes",
                json={
                    "school_id": str(self.school.id),
                    "teacher_id": str(self.teacher.id),
                    "purpose": "join",
                },
            ).status_code,
            401,
        )
        joined = self.TestClient(self.app).post(
            "/api/collaboration/redeem", json={"code": "not-a-real-code"}
        )
        self.assertEqual(joined.status_code, 400)
        # A teacher bearer is not an administrator even when supplied.
        teacher_client = self.TestClient(self.app)
        teacher_client.headers["Authorization"] = "Bearer " + "x" * 43
        self.assertEqual(
            teacher_client.post(
                "/api/collaboration/admin/codes",
                json={
                    "school_id": str(self.school.id),
                    "teacher_id": str(self.teacher.id),
                    "purpose": "join",
                },
            ).status_code,
            401,
        )

    def test_issue_requires_csrf_and_wrong_school_is_rejected(self):
        client, response = self._login()
        csrf = self._csrf(response)
        missing = client.post(
            "/api/collaboration/admin/codes",
            json={
                "school_id": str(self.school.id),
                "teacher_id": str(self.teacher.id),
                "purpose": "join",
            },
        )
        self.assertEqual(missing.status_code, 403)
        wrong = self._issue(client, csrf, self.teacher, school=self.school2)
        self.assertEqual(wrong.status_code, 422)
        self.assertIn("不属于", wrong.text)

    def test_join_code_is_hashed_and_redeems_once(self):
        client, response = self._login()
        csrf = self._csrf(response)
        issued = self._issue(client, csrf, self.teacher)
        self.assertEqual(issued.status_code, 200, issued.text)
        self.assertEqual(issued.headers.get("cache-control"), "no-store")
        body = issued.json()
        self.assertEqual(body["purpose"], "join")
        code = body["code"]
        self.assertGreaterEqual(len(code), 40)
        with self.factory() as session:
            row = session.get(self.AdminCode, uuid.UUID(body["code_id"]))
            self.assertIsNotNone(row)
            self.assertNotEqual(row.code_hash, code)
            self.assertEqual(len(row.code_hash), 64)
        redeemed = self.TestClient(self.app).post(
            "/api/collaboration/redeem", json={"code": code}
        )
        self.assertEqual(redeemed.status_code, 200, redeemed.text)
        self.assertEqual(redeemed.headers.get("cache-control"), "no-store")
        result = redeemed.json()
        self.assertEqual(result["purpose"], "join")
        self.assertIsNone(result["membership"])
        me = self.TestClient(self.app).get(
            "/api/collaboration/me",
            headers={"Authorization": "Bearer " + result["token"]},
        )
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["teacher_id"], str(self.teacher.id))
        replay = self.TestClient(self.app).post(
            "/api/collaboration/redeem", json={"code": code}
        )
        self.assertEqual(replay.status_code, 400)

    def test_concurrent_redemption_commits_once(self):
        client, response = self._login()
        issued = self._issue(client, self._csrf(response), self.teacher2)
        self.assertEqual(issued.status_code, 200, issued.text)
        code = issued.json()["code"]

        def redeem_once():
            return self.TestClient(self.app).post(
                "/api/collaboration/redeem", json={"code": code}
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = sorted(pool.map(lambda _: redeem_once(), range(2)))
        self.assertEqual(statuses, [200, 400])

    def test_recovery_returns_only_current_membership(self):
        with self.factory() as session:
            session.add(
                self.TeacherClassMembership(
                    teacher_id=self.teacher.id,
                    school_id=self.school.id,
                    class_id=self.classroom.id,
                    membership_generation=uuid.uuid4(),
                    selected_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            )
            session.commit()
        client, response = self._login()
        issued = self._issue(
            client, self._csrf(response), self.teacher, purpose="recovery"
        )
        self.assertEqual(issued.status_code, 200, issued.text)
        result = self.TestClient(self.app).post(
            "/api/collaboration/redeem", json={"code": issued.json()["code"]}
        ).json()
        self.assertEqual(result["membership"]["class_id"], str(self.classroom.id))
        with self.factory() as session:
            membership = session.get(self.TeacherClassMembership, self.teacher.id)
            session.delete(membership)
            session.commit()
        issued = self._issue(
            client, self._csrf(response), self.teacher, purpose="recovery"
        )
        self.assertEqual(issued.status_code, 200, issued.text)
        result = self.TestClient(self.app).post(
            "/api/collaboration/redeem", json={"code": issued.json()["code"]}
        ).json()
        self.assertIsNone(result["membership"])

    def test_disabled_teacher_and_expired_code_are_rejected(self):
        with self.factory() as session:
            teacher = session.get(self.Teacher, self.teacher2.id)
            teacher.active = False
            session.commit()
        client, response = self._login()
        disabled = self._issue(client, self._csrf(response), self.teacher2)
        self.assertEqual(disabled.status_code, 409)
        with self.factory() as session:
            teacher = session.get(self.Teacher, self.teacher2.id)
            teacher.active = True
            session.commit()
        issued = self._issue(client, self._csrf(response), self.teacher2)
        self.assertEqual(issued.status_code, 200, issued.text)
        with self.factory() as session:
            row = session.get(self.AdminCode, uuid.UUID(issued.json()["code_id"]))
            row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            session.commit()
        expired = self.TestClient(self.app).post(
            "/api/collaboration/redeem", json={"code": issued.json()["code"]}
        )
        self.assertEqual(expired.status_code, 400)

    def test_logout_invalidates_session_and_requires_csrf(self):
        client, response = self._login("admin-logout")
        csrf = self._csrf(response)
        missing = client.post("/api/collaboration/admin/logout")
        self.assertEqual(missing.status_code, 403)
        self.assertEqual(
            client.post(
                "/api/collaboration/admin/logout",
                headers={"X-CSRF-Token": csrf},
            ).status_code,
            204,
        )
        self.assertEqual(
            client.get("/api/collaboration/admin/session").status_code, 401
        )

    def test_login_lockout_and_session_expiry(self):
        client = self.TestClient(self.app)
        for _ in range(5):
            response = client.post(
                "/api/collaboration/admin/login",
                json={"username": "admin-locked", "password": "wrong-password-123"},
            )
            self.assertEqual(response.status_code, 401)
        locked = client.post(
            "/api/collaboration/admin/login",
            json={
                "username": "admin-locked",
                "password": "synthetic-admin-password-123",
            },
        )
        self.assertEqual(locked.status_code, 429)
        with self.factory() as session:
            user = session.get(self.AdminUser, self.admin_locked.id)
            user.locked_until = datetime.now(timezone.utc) - timedelta(seconds=1)
            session.commit()
        recovered = client.post(
            "/api/collaboration/admin/login",
            json={
                "username": "admin-locked",
                "password": "synthetic-admin-password-123",
            },
        )
        self.assertEqual(recovered.status_code, 200)

        client2, response = self._login("admin-expiry")
        self.assertEqual(response.status_code, 200)
        with self.factory() as session:
            rows = session.query(self.AdminSession).filter_by(
                admin_id=self.admin_expiry.id
            ).all()
            for row in rows:
                row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            session.commit()
        self.assertEqual(
            client2.get("/api/collaboration/admin/session").status_code, 401
        )


if __name__ == "__main__":
    unittest.main()
