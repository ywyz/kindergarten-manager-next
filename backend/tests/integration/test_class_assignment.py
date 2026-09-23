"""Integration tests for I2 phase 1: classes, school settings, assignment.

These tests require an isolated MySQL 8.4 / InnoDB database with the I2
migrations applied (``alembic upgrade head``). They do not run migrations
themselves. Set the environment before running:

    export APP_DISABLE_DOTENV=1
    export I2_TEST_ALLOW_DESTRUCTIVE=yes
    export I2_TEST_DATABASE_URL=mysql+pymysql://user:pass@127.0.0.1:3306/kindergarten_test_i2

The test database is reset to an empty state at the start of the run.
"""

from __future__ import annotations

import os
import unittest

os.environ["APP_DISABLE_DOTENV"] = "1"

from sqlalchemy import text  # noqa: E402

from tests.integration.i2_guard import (
    AsgiClient,
    HEADERS,
    _json_body,
    check_environment,
    ensure_schema,
    make_engine,
    register_and_login,
    require_authorized_url,
    reset_i2_tables,
    skip_unless_enabled,
)


@skip_unless_enabled
class ClassAssignmentIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = make_engine()
        require_authorized_url(str(cls.engine.url))
        check_environment(cls.engine)
        ensure_schema(cls.engine)

    def setUp(self):
        reset_i2_tables(self.engine)
        self.client = AsgiClient()
        self.admin, self.admin_cookie = register_and_login(
            self.client, "headadmin"
        )
        self.teacher, self.teacher_cookie = register_and_login(
            self.client, "teacher_one"
        )

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def _as(self, cookie: dict[str, str]) -> None:
        self.client.cookies = cookie

    def _create_class(self, name: str, grade: str = "small") -> dict:
        self._as(self.admin_cookie)
        preview = self.client.request(
            "POST",
            "/api/admin/configuration-changes/preview",
            headers=HEADERS,
            body=_json_body(
                {"kind": "class_create", "name": name, "grade": grade}
            ),
        )
        self.assertEqual(preview.status, 201, preview.body)
        target_id = preview.json()["target_id"]
        applied = self.client.request(
            "POST",
            f"/api/admin/configuration-changes/{preview.json()['id']}/apply",
            headers=HEADERS,
            body=_json_body({"confirm": True}),
        )
        self.assertEqual(applied.status, 200, applied.body)
        detail = self.client.request("GET", f"/api/admin/classes/{target_id}")
        self.assertEqual(detail.status, 200, detail.body)
        result = detail.json()
        self.assertEqual(result["name"], name)
        return result

    # -- V2/V4: school settings read & access control ----------------------

    def test_teacher_cannot_read_admin_school_settings(self):
        self._as(self.teacher_cookie)
        resp = self.client.request("GET", "/api/admin/school-settings")
        self.assertEqual(resp.status, 403)

    def test_admin_reads_school_settings(self):
        self._as(self.admin_cookie)
        resp = self.client.request("GET", "/api/admin/school-settings")
        self.assertEqual(resp.status, 200)
        body = resp.json()
        self.assertIsNone(body["school_name"])
        self.assertEqual(body["version"], 1)
        self.assertEqual(body["schedule_version"], 1)

    # -- V2: school update preview -> apply --------------------------------

    def test_school_update_preview_and_apply(self):
        self._as(self.admin_cookie)
        resp = self.client.request(
            "POST",
            "/api/admin/configuration-changes/preview",
            headers=HEADERS,
            body=_json_body(
                {
                    "kind": "school_update",
                    "school_name": "阳光幼儿园",
                    "expected_version": 1,
                }
            ),
        )
        self.assertEqual(resp.status, 201, resp.body)
        preview = resp.json()
        self.assertEqual(preview["status"], "pending")
        self.assertEqual(preview["changes"][0]["new"], "阳光幼儿园")
        self.assertEqual(
            preview["impact"]["plan_impact_status"],
            "not_applicable_before_first_plan",
        )
        # Proposal alone must not change live config.
        settings = self.client.request(
            "GET", "/api/admin/school-settings"
        ).json()
        self.assertIsNone(settings["school_name"])

        applied = self.client.request(
            "POST",
            f"/api/admin/configuration-changes/{preview['id']}/apply",
            headers=HEADERS,
            body=_json_body({"confirm": True}),
        )
        self.assertEqual(applied.status, 200, applied.body)
        self.assertEqual(
            applied.json()["result_reference"],
            "school_settings:singleton",
        )

        settings = self.client.request(
            "GET", "/api/admin/school-settings"
        ).json()
        self.assertEqual(settings["school_name"], "阳光幼儿园")
        self.assertEqual(settings["version"], 2)

        # Idempotent re-apply: no extra write.
        second = self.client.request(
            "POST",
            f"/api/admin/configuration-changes/{preview['id']}/apply",
            headers=HEADERS,
            body=_json_body({"confirm": True}),
        )
        self.assertEqual(second.status, 200)
        settings = self.client.request(
            "GET", "/api/admin/school-settings"
        ).json()
        self.assertEqual(settings["version"], 2)

    # -- V2: no changes -> 422 ---------------------------------------------

    def test_school_update_no_changes(self):
        self._as(self.admin_cookie)
        resp = self.client.request(
            "POST",
            "/api/admin/configuration-changes/preview",
            headers=HEADERS,
            body=_json_body(
                {
                    "kind": "school_update",
                    "school_name": None,
                    "expected_version": 1,
                }
            ),
        )
        self.assertEqual(resp.status, 422)
        self.assertIn(b"NO_CHANGES", resp.body)

    # -- V2: class create preview -> apply ---------------------------------

    def test_class_create_illegal_grade_rejected(self):
        self._as(self.admin_cookie)
        resp = self.client.request(
            "POST",
            "/api/admin/configuration-changes/preview",
            headers=HEADERS,
            body=_json_body(
                {
                    "kind": "class_create",
                    "name": "托一班",
                    "grade": "baby",
                }
            ),
        )
        self.assertEqual(resp.status, 422)

    def test_class_create_preview_and_apply(self):
        self._as(self.admin_cookie)
        resp = self.client.request(
            "POST",
            "/api/admin/configuration-changes/preview",
            headers=HEADERS,
            body=_json_body(
                {
                    "kind": "class_create",
                    "name": "小一班",
                    "grade": "small",
                    "header_teacher_names": ["张老师", "李老师"],
                    "caregiver_name": "王阿姨",
                }
            ),
        )
        self.assertEqual(resp.status, 201, resp.body)
        preview = resp.json()
        self.assertTrue(preview["target_id"])

        # Before apply, class list is empty.
        listing = self.client.request("GET", "/api/admin/classes").json()
        self.assertEqual(listing["total"], 0)

        applied = self.client.request(
            "POST",
            f"/api/admin/configuration-changes/{preview['id']}/apply",
            headers=HEADERS,
            body=_json_body({"confirm": True}),
        )
        self.assertEqual(applied.status, 200, applied.body)

        listing = self.client.request("GET", "/api/admin/classes").json()
        self.assertEqual(listing["total"], 1)
        self.assertEqual(listing["items"][0]["name"], "小一班")

        # P3: duplicate name rejected.
        dup = self.client.request(
            "POST",
            "/api/admin/configuration-changes/preview",
            headers=HEADERS,
            body=_json_body(
                {
                    "kind": "class_create",
                    "name": "小一班",
                    "grade": "small",
                }
            ),
        )
        self.assertEqual(dup.status, 409)
        self.assertIn(b"CLASS_NAME_TAKEN", dup.body)

    # -- V2/V4: first assignment -------------------------------------------

    def test_teacher_pending_in_me(self):
        self._as(self.teacher_cookie)
        resp = self.client.request("GET", "/api/auth/me")
        self.assertEqual(resp.status, 200)
        body = resp.json()
        self.assertIsNone(body["class_id"])
        self.assertEqual(body["assignment_status"], "pending_assignment")
        self.assertFalse(body["can_prepare"])

    def test_first_assignment(self):
        self._as(self.admin_cookie)
        self._create_class("小一班", "small")
        classes = self.client.request("GET", "/api/admin/classes").json()
        class_id = classes["items"][0]["id"]
        class_version = classes["items"][0]["version"]

        teachers = self.client.request(
            "GET",
            "/api/admin/teachers?assignment_status=pending_assignment",
        ).json()
        target = next(
            t for t in teachers["items"] if t["username"] == "teacher_one"
        )

        resp = self.client.request(
            "POST",
            f"/api/admin/teachers/{target['id']}/assignment",
            headers=HEADERS,
            body=_json_body(
                {
                    "class_id": class_id,
                    "expected_version": target["version"],
                    "expected_class_version": class_version,
                }
            ),
        )
        self.assertEqual(resp.status, 200, resp.body)
        body = resp.json()
        self.assertEqual(body["class_id"], class_id)
        self.assertEqual(body["assignment_status"], "assigned")
        self.assertEqual(body["account"]["version"], target["version"] + 1)

        # Teacher's existing session immediately sees the assignment;
        # auth_version is unchanged (no session revocation).
        self._as(self.teacher_cookie)
        me = self.client.request("GET", "/api/auth/me").json()
        self.assertEqual(me["class_id"], class_id)
        self.assertEqual(me["assignment_status"], "assigned")
        self.assertTrue(me["can_prepare"])

        # Teacher can read class context, without admin teacher list.
        ctx = self.client.request("GET", "/api/class-context")
        self.assertEqual(ctx.status, 200)
        ctx_body = ctx.json()
        self.assertEqual(ctx_body["class"]["name"], "小一班")
        self.assertNotIn("assigned_teachers", ctx_body["class"])

        # Second assignment attempt -> ALREADY_ASSIGNED.
        self._as(self.admin_cookie)
        retry = self.client.request(
            "POST",
            f"/api/admin/teachers/{target['id']}/assignment",
            headers=HEADERS,
            body=_json_body(
                {
                    "class_id": class_id,
                    "expected_version": body["account"]["version"],
                    "expected_class_version": class_version,
                }
            ),
        )
        self.assertEqual(retry.status, 409)
        self.assertIn(b"ALREADY_ASSIGNED", retry.body)

    # -- V4: teachers cannot manage classes --------------------------------

    def test_assigned_teacher_cannot_create_class_preview(self):
        self._as(self.teacher_cookie)
        resp = self.client.request(
            "POST",
            "/api/admin/configuration-changes/preview",
            headers=HEADERS,
            body=_json_body(
                {
                    "kind": "class_create",
                    "name": "中一班",
                    "grade": "middle",
                }
            ),
        )
        self.assertEqual(resp.status, 403)

    def test_visitor_rejected(self):
        self.client.cookies = {}
        resp = self.client.request("GET", "/api/admin/classes")
        self.assertEqual(resp.status, 401)
        resp = self.client.request("GET", "/api/class-context")
        self.assertEqual(resp.status, 401)

    def test_teacher_cannot_see_other_class_context(self):
        class_a = self._create_class("小一班", "small")
        class_b = self._create_class("小二班", "small")
        # Assign teacher_one to class A.
        teachers = self.client.request(
            "GET",
            "/api/admin/teachers?assignment_status=pending_assignment",
        ).json()
        target = next(
            t for t in teachers["items"] if t["username"] == "teacher_one"
        )
        resp = self.client.request(
            "POST",
            f"/api/admin/teachers/{target['id']}/assignment",
            headers=HEADERS,
            body=_json_body(
                {
                    "class_id": class_a["id"],
                    "expected_version": target["version"],
                    "expected_class_version": class_a["version"],
                }
            ),
        )
        self.assertEqual(resp.status, 200, resp.body)

        # Teacher can read own class context.
        self._as(self.teacher_cookie)
        ctx = self.client.request("GET", "/api/class-context")
        self.assertEqual(ctx.status, 200)
        self.assertEqual(ctx.json()["class"]["id"], class_a["id"])

        # No API exposes other classes' account data to teachers.
        admin_list = self.client.request("GET", "/api/admin/classes")
        self.assertEqual(admin_list.status, 403)

    def test_assignment_rejects_admin_target(self):
        class_a = self._create_class("小一班", "small")
        admin_id = self.admin["account"]["id"]
        resp = self.client.request(
            "POST",
            f"/api/admin/teachers/{admin_id}/assignment",
            headers=HEADERS,
            body=_json_body(
                {
                    "class_id": class_a["id"],
                    "expected_version": self.admin["account"]["version"],
                    "expected_class_version": class_a["version"],
                }
            ),
        )
        self.assertEqual(resp.status, 404)

    def test_assignment_rejects_disabled_teacher(self):
        class_a = self._create_class("小一班", "small")
        target_id = self.teacher["account"]["id"]
        with self.engine.begin() as conn:
            conn.execute(
                text("UPDATE accounts SET is_active = 0 WHERE id = :id"),
                {"id": target_id},
            )
        resp = self.client.request(
            "POST",
            f"/api/admin/teachers/{target_id}/assignment",
            headers=HEADERS,
            body=_json_body(
                {
                    "class_id": class_a["id"],
                    "expected_version": self.teacher["account"]["version"],
                    "expected_class_version": class_a["version"],
                }
            ),
        )
        self.assertEqual(resp.status, 404)

    def test_assignment_rejects_nonexistent_class(self):
        self._as(self.admin_cookie)
        target_id = self.teacher["account"]["id"]
        resp = self.client.request(
            "POST",
            f"/api/admin/teachers/{target_id}/assignment",
            headers=HEADERS,
            body=_json_body(
                {
                    "class_id": "nonexistentclass",
                    "expected_version": self.teacher["account"]["version"],
                    "expected_class_version": 1,
                }
            ),
        )
        self.assertEqual(resp.status, 404)

    def test_assignment_rejects_fake_version(self):
        class_a = self._create_class("小一班", "small")
        target_id = self.teacher["account"]["id"]
        resp = self.client.request(
            "POST",
            f"/api/admin/teachers/{target_id}/assignment",
            headers=HEADERS,
            body=_json_body(
                {
                    "class_id": class_a["id"],
                    "expected_version": 999,
                    "expected_class_version": class_a["version"],
                }
            ),
        )
        self.assertEqual(resp.status, 409)
        self.assertIn(b"VERSION_CONFLICT", resp.body)

    # -- V13: dependency gate ----------------------------------------------

    def _set_plans_started(self):
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE school_settings SET plans_started_at = UTC_TIMESTAMP()"
                )
            )

    def test_dependency_gate_blocks_school_update(self):
        self._set_plans_started()
        self._as(self.admin_cookie)
        settings = self.client.request(
            "GET", "/api/admin/school-settings"
        ).json()
        resp = self.client.request(
            "POST",
            "/api/admin/configuration-changes/preview",
            headers=HEADERS,
            body=_json_body(
                {
                    "kind": "school_update",
                    "school_name": "新名称",
                    "expected_version": settings["version"],
                }
            ),
        )
        self.assertEqual(resp.status, 201, resp.body)
        preview = resp.json()
        self.assertIn("DEPENDENCY_NOT_READY", preview["blockers"])

        applied = self.client.request(
            "POST",
            f"/api/admin/configuration-changes/{preview['id']}/apply",
            headers=HEADERS,
            body=_json_body({"confirm": True}),
        )
        self.assertEqual(applied.status, 409)
        self.assertIn(b"DEPENDENCY_NOT_READY", applied.body)

    def test_dependency_gate_blocks_class_update_but_allows_class_create(self):
        class_a = self._create_class("小一班", "small")
        self._set_plans_started()

        self._as(self.admin_cookie)
        # class_update blocked.
        resp = self.client.request(
            "POST",
            "/api/admin/configuration-changes/preview",
            headers=HEADERS,
            body=_json_body(
                {
                    "kind": "class_update",
                    "target_id": class_a["id"],
                    "name": "小一班改",
                    "expected_version": class_a["version"],
                }
            ),
        )
        self.assertEqual(resp.status, 201, resp.body)
        preview = resp.json()
        self.assertIn("DEPENDENCY_NOT_READY", preview["blockers"])

        # class_create still allowed.
        create_resp = self.client.request(
            "POST",
            "/api/admin/configuration-changes/preview",
            headers=HEADERS,
            body=_json_body(
                {"kind": "class_create", "name": "中一班", "grade": "middle"}
            ),
        )
        self.assertEqual(create_resp.status, 201, create_resp.body)
        apply_resp = self.client.request(
            "POST",
            f"/api/admin/configuration-changes/{create_resp.json()['id']}/apply",
            headers=HEADERS,
            body=_json_body({"confirm": True}),
        )
        self.assertEqual(apply_resp.status, 200, apply_resp.body)

    def test_first_assignment_still_allowed_after_plans_started(self):
        class_a = self._create_class("小一班", "small")
        self._set_plans_started()

        teachers = self.client.request(
            "GET",
            "/api/admin/teachers?assignment_status=pending_assignment",
        ).json()
        target = next(
            t for t in teachers["items"] if t["username"] == "teacher_one"
        )
        resp = self.client.request(
            "POST",
            f"/api/admin/teachers/{target['id']}/assignment",
            headers=HEADERS,
            body=_json_body(
                {
                    "class_id": class_a["id"],
                    "expected_version": target["version"],
                    "expected_class_version": class_a["version"],
                }
            ),
        )
        self.assertEqual(resp.status, 200, resp.body)

    # -- Me / teacher list / audit compatibility (I1 impact) ---------------

    def test_me_and_teacher_list_reflect_assignment(self):
        # Pending teacher Me.
        self._as(self.teacher_cookie)
        me = self.client.request("GET", "/api/auth/me").json()
        self.assertIsNone(me["class_id"])
        self.assertEqual(me["assignment_status"], "pending_assignment")
        self.assertFalse(me["can_prepare"])

        # Admin list with assignment filter.
        self._as(self.admin_cookie)
        pending = self.client.request(
            "GET", "/api/admin/teachers?assignment_status=pending_assignment"
        ).json()
        self.assertEqual(pending["total"], 1)
        self.assertEqual(pending["items"][0]["username"], "teacher_one")
        self.assertEqual(pending["items"][0]["assignment_status"], "pending_assignment")

        class_a = self._create_class("小一班", "small")
        target = pending["items"][0]
        self.client.request(
            "POST",
            f"/api/admin/teachers/{target['id']}/assignment",
            headers=HEADERS,
            body=_json_body(
                {
                    "class_id": class_a["id"],
                    "expected_version": target["version"],
                    "expected_class_version": class_a["version"],
                }
            ),
        )

        # Teacher Me now shows assignment.
        self._as(self.teacher_cookie)
        me = self.client.request("GET", "/api/auth/me").json()
        self.assertEqual(me["class_id"], class_a["id"])
        self.assertEqual(me["assignment_status"], "assigned")
        self.assertTrue(me["can_prepare"])

        # Admin list filters assigned.
        self._as(self.admin_cookie)
        assigned = self.client.request(
            "GET", "/api/admin/teachers?assignment_status=assigned"
        ).json()
        self.assertEqual(assigned["total"], 1)
        self.assertEqual(assigned["items"][0]["class_id"], class_a["id"])
        self.assertEqual(assigned["items"][0]["assignment_status"], "assigned")

    def test_assignment_audit_record_has_generic_and_legacy_columns(self):
        class_a = self._create_class("小一班", "small")
        target = self.client.request(
            "GET", "/api/admin/teachers?assignment_status=pending_assignment"
        ).json()["items"][0]
        self.client.request(
            "POST",
            f"/api/admin/teachers/{target['id']}/assignment",
            headers=HEADERS,
            body=_json_body(
                {
                    "class_id": class_a["id"],
                    "expected_version": target["version"],
                    "expected_class_version": class_a["version"],
                }
            ),
        )

        with self.engine.connect() as conn:
            record = conn.execute(
                text(
                    "SELECT operator_id, action, target_type, target_id, "
                    "target_version_after, target_account_id, account_version_after "
                    "FROM operation_records WHERE action = 'assign_teacher'"
                )
            ).fetchone()
            self.assertIsNotNone(record)
            self.assertEqual(record.action, "assign_teacher")
            self.assertEqual(record.target_type, "account")
            self.assertEqual(record.target_id, target["id"])
            self.assertEqual(record.target_version_after, target["version"] + 1)
            self.assertEqual(record.target_account_id, target["id"])
            self.assertEqual(record.account_version_after, target["version"] + 1)


if __name__ == "__main__":
    unittest.main()
