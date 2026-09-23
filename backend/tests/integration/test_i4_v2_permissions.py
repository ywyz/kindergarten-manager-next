"""V2 — permission matrix over all 8 I4 routes on the real HTTP contract.

Every assertion is a real ASGI request through ``app.main``: real routing,
real auth dependencies, real exception handlers. Bodies are always
well-formed so a non-2xx answer reflects permission, not payload shape.
"""

from __future__ import annotations

from tests.integration.i4_support import (
    ADMIN,
    CLASS_ID,
    CROSS,
    FREE,
    OTHER_CLASS_ID,
    OWNER,
    SAME,
    TERM_ID,
    WEEK,
    AsgiClient,
    I4IntegrationTestCase,
)

CONFIRM_BODY = {
    "expected_draft_version": 1,
    "acknowledge_missing": True,
    "acknowledge_stale": False,
    "note": None,
}


class V2PermissionTests(I4IntegrationTestCase):
    # -- helpers ----------------------------------------------------------

    def _routes(self, plan_id: str) -> list[tuple[str, str, str, dict | None]]:
        """The 8 I4 routes in spec order, each with a well-formed body."""
        return [
            ("list", "GET", "/api/weekly-plans", None),
            (
                "create",
                "POST",
                "/api/weekly-plans",
                {"term_id": TERM_ID, "week_number": WEEK, "theme": "矩阵"},
            ),
            ("detail", "GET", f"/api/weekly-plans/{plan_id}", None),
            (
                "patch",
                "PATCH",
                f"/api/weekly-plans/{plan_id}",
                {"expected_draft_version": 1, "theme": "改一下"},
            ),
            (
                "refresh",
                "POST",
                f"/api/weekly-plans/{plan_id}/refresh-sources",
                {"expected_draft_version": 1},
            ),
            (
                "confirm",
                "POST",
                f"/api/weekly-plans/{plan_id}/confirm",
                dict(CONFIRM_BODY),
            ),
            ("history", "GET", f"/api/weekly-plans/{plan_id}/confirmations", None),
            (
                "version",
                "GET",
                f"/api/weekly-plans/{plan_id}/confirmations/1",
                None,
            ),
        ]

    def _with_class(self, path: str, class_id: str | None) -> str:
        if class_id is None:
            return path
        sep = "&" if "?" in path else "?"
        return f"{path}{sep}class_id={class_id}"

    def _hit(
        self,
        client: AsgiClient,
        plan_id: str,
        *,
        class_id: str | None = None,
    ) -> dict[str, tuple[int, str | None]]:
        """Hit all 8 routes, threading the current draft version forward.

        Each successful PATCH/refresh response advances the version the next
        write carries, so the sequence models a real client session instead
        of replaying a stale ``expected_draft_version``.
        """
        results: dict[str, tuple[int, str | None]] = {}
        expected = 1
        for name, method, path, body in self._routes(plan_id):
            if isinstance(body, dict) and "expected_draft_version" in body:
                body = dict(body)
                body["expected_draft_version"] = expected
            target = self._with_class(path, class_id)
            if method == "GET":
                response = client.get(target)
            elif method == "PATCH":
                response = client.patch(target, body)
            else:
                response = client.post(target, body)
            results[name] = (response.status_code, response.code)
            if (
                response.status_code == 200
                and isinstance(body, dict)
                and "expected_draft_version" in body
            ):
                payload = response.json()
                if isinstance(payload, dict) and payload.get("draft"):
                    expected = payload["draft"]["version"]
        return results

    def _create_and_confirm(self) -> str:
        """Owner creates (201) and confirms (201) a plan; returns its id."""
        created = self.owner_client.post(
            "/api/weekly-plans",
            {"term_id": TERM_ID, "week_number": WEEK, "theme": "种子主题"},
        )
        self.assertEqual(created.status_code, 201, created.content)
        plan_id = created.json()["id"]
        confirmed = self.owner_client.post(
            f"/api/weekly-plans/{plan_id}/confirm", dict(CONFIRM_BODY)
        )
        self.assertEqual(confirmed.status_code, 201, confirmed.content)
        return plan_id

    def _create_only(self) -> str:
        created = self.owner_client.post(
            "/api/weekly-plans",
            {"term_id": TERM_ID, "week_number": WEEK, "theme": "种子主题"},
        )
        self.assertEqual(created.status_code, 201, created.content)
        return created.json()["id"]

    # -- guests -----------------------------------------------------------

    def test_guest_is_401_on_all_eight_routes(self):
        plan_id = self._create_and_confirm()
        results = self._hit(AsgiClient(), plan_id)
        self.assertEqual(
            results,
            {name: (401, "AUTH_REQUIRED") for name in results},
            results,
        )

    # -- unassigned teacher ------------------------------------------------

    def test_unassigned_teacher_is_403_on_all_eight_routes(self):
        plan_id = self._create_and_confirm()
        results = self._hit(self.free_client, plan_id)
        self.assertEqual(
            results,
            {name: (403, "FORBIDDEN") for name in results},
            results,
        )

    # -- same-class non-owner teacher --------------------------------------

    def test_same_class_other_teacher_is_read_only(self):
        plan_id = self._create_and_confirm()
        results = self._hit(self.same_client, plan_id)
        self.assertEqual(
            results,
            {
                "list": (200, None),
                "create": (200, None),  # opens the existing plan
                "detail": (200, None),
                "patch": (403, "FORBIDDEN"),
                "refresh": (403, "FORBIDDEN"),
                "confirm": (403, "FORBIDDEN"),
                "history": (200, None),
                "version": (200, None),
            },
            results,
        )

        detail = self.same_client.get(f"/api/weekly-plans/{plan_id}").json()
        self.assertFalse(detail["can_edit"])
        self.assertFalse(detail["can_confirm"])

        listing = self.same_client.get("/api/weekly-plans").json()
        self.assertEqual([item["id"] for item in listing["items"]], [plan_id])

    def test_same_class_teacher_create_becomes_owner_when_absent(self):
        created = self.same_client.post(
            "/api/weekly-plans",
            {"term_id": TERM_ID, "week_number": WEEK},
        )
        self.assertEqual(created.status_code, 201, created.content)
        body = created.json()
        self.assertEqual(body["creator_id"], SAME["id"])
        self.assertEqual(body["owner_id"], SAME["id"])
        self.assertEqual(self.plan_count(), 1)

    # -- owner -------------------------------------------------------------

    def test_owner_can_do_every_route(self):
        plan_id = self._create_and_confirm()

        listing = self.owner_client.get(
            f"/api/weekly-plans?term_id={TERM_ID}"
        ).json()
        self.assertEqual(listing["total"], 1)
        self.assertEqual(listing["items"][0]["id"], plan_id)
        self.assertFalse(listing["items"][0]["needs_confirm"])

        reopened = self.owner_client.post(
            "/api/weekly-plans",
            {"term_id": TERM_ID, "week_number": WEEK},
        )
        self.assertEqual(reopened.status_code, 200, reopened.content)
        self.assertEqual(reopened.json()["id"], plan_id)

        detail = self.owner_client.get(f"/api/weekly-plans/{plan_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertTrue(detail.json()["can_edit"])
        self.assertTrue(detail.json()["can_confirm"])
        draft_version = detail.json()["draft"]["version"]

        patched = self.owner_client.patch(
            f"/api/weekly-plans/{plan_id}",
            {"expected_draft_version": draft_version, "theme": "负责人改"},
        )
        self.assertEqual(patched.status_code, 200, patched.content)
        draft_version = patched.json()["draft"]["version"]

        refreshed = self.owner_client.post(
            f"/api/weekly-plans/{plan_id}/refresh-sources",
            {"expected_draft_version": draft_version},
        )
        self.assertEqual(refreshed.status_code, 200, refreshed.content)
        draft_version = refreshed.json()["draft"]["version"]

        confirmed = self.owner_client.post(
            f"/api/weekly-plans/{plan_id}/confirm",
            {
                "expected_draft_version": draft_version,
                "acknowledge_missing": True,
                "acknowledge_stale": False,
            },
        )
        self.assertEqual(confirmed.status_code, 201, confirmed.content)

        history = self.owner_client.get(
            f"/api/weekly-plans/{plan_id}/confirmations"
        ).json()
        self.assertEqual(history["total"], 2)

        version = self.owner_client.get(
            f"/api/weekly-plans/{plan_id}/confirmations/1"
        )
        self.assertEqual(version.status_code, 200, version.content)
        self.assertEqual(version.json()["version"], 1)

    def test_owner_create_is_201_then_repeat_is_200(self):
        first = self.owner_client.post(
            "/api/weekly-plans",
            {"term_id": TERM_ID, "week_number": WEEK, "theme": "首次"},
        )
        self.assertEqual(first.status_code, 201, first.content)
        second = self.same_client.post(
            "/api/weekly-plans",
            {"term_id": TERM_ID, "week_number": WEEK, "theme": "重复"},
        )
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(second.json()["creator_id"], OWNER["id"])
        self.assertEqual(second.json()["owner_id"], OWNER["id"])
        self.assertEqual(self.plan_count(), 1)
        # The repeat request must not become a second draft version.
        self.assertEqual(second.json()["draft"]["version"], 1)

    def test_owner_cannot_smuggle_class_id(self):
        body_with_class = {
            "term_id": TERM_ID,
            "week_number": WEEK,
            "class_id": CLASS_ID,
        }
        response = self.owner_client.post("/api/weekly-plans", body_with_class)
        self.assertEqual(response.status_code, 422, response.content)
        self.assertEqual(response.code, "VALIDATION_ERROR")
        self.assertEqual(self.plan_count(), 0)

        query = self.owner_client.post(
            f"/api/weekly-plans?class_id={CLASS_ID}",
            {"term_id": TERM_ID, "week_number": WEEK},
        )
        self.assertEqual(query.status_code, 422, query.content)
        self.assertEqual(self.plan_count(), 0)

        null_body = {"term_id": TERM_ID, "week_number": WEEK, "class_id": None}
        null_response = self.owner_client.post("/api/weekly-plans", null_body)
        self.assertEqual(null_response.status_code, 422, null_response.content)

    def test_owner_write_routes_reject_class_id_query(self):
        plan_id = self._create_only()
        patched = self.owner_client.patch(
            f"/api/weekly-plans/{plan_id}?class_id={CLASS_ID}",
            {"expected_draft_version": 1, "theme": "x"},
        )
        self.assertEqual(patched.status_code, 422, patched.content)
        refreshed = self.owner_client.post(
            f"/api/weekly-plans/{plan_id}/refresh-sources?class_id={CLASS_ID}",
            {"expected_draft_version": 1},
        )
        self.assertEqual(refreshed.status_code, 422, refreshed.content)
        self.assertEqual(self.draft_count(plan_id), 1)

    # -- non-owner admin ---------------------------------------------------

    def test_admin_cannot_create_even_with_explicit_class(self):
        body = {
            "term_id": TERM_ID,
            "week_number": WEEK,
            "class_id": CLASS_ID,
        }
        response = self.admin_client.post("/api/weekly-plans", body)
        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(response.code, "FORBIDDEN")
        self.assertEqual(self.plan_count(), 0)

        query = self.admin_client.post(
            f"/api/weekly-plans?class_id={CLASS_ID}",
            {"term_id": TERM_ID, "week_number": WEEK},
        )
        self.assertEqual(query.status_code, 403, query.content)
        self.assertEqual(self.plan_count(), 0)

        bare = self.admin_client.post(
            "/api/weekly-plans",
            {"term_id": TERM_ID, "week_number": WEEK},
        )
        self.assertEqual(bare.status_code, 403, bare.content)

    def test_admin_can_edit_but_never_confirm(self):
        plan_id = self._create_and_confirm()
        confirmed_before = self.confirmed_count(plan_id)
        v1_content_before = self.rows(
            "SELECT content, facts FROM weekly_plan_confirmed_contents "
            "WHERE weekly_plan_id = :id AND version = 1",
            {"id": plan_id},
        )

        results = self._hit(self.admin_client, plan_id, class_id=CLASS_ID)
        self.assertEqual(
            results,
            {
                "list": (200, None),
                "create": (403, "FORBIDDEN"),
                "detail": (200, None),
                "patch": (200, None),   # admin edit allowed
                "refresh": (200, None),
                "confirm": (403, "FORBIDDEN"),
                "history": (200, None),
                "version": (200, None),
            },
            results,
        )

        detail = self.admin_client.get(
            f"/api/weekly-plans/{plan_id}?class_id={CLASS_ID}"
        ).json()
        self.assertTrue(detail["can_edit"])
        self.assertFalse(detail["can_confirm"])
        self.assertEqual(detail["draft"]["editor_role"], "admin")
        self.assertEqual(detail["confirmation_status"], "draft_ahead")
        self.assertTrue(detail["needs_confirm"])

        # Confirm immediately after editing must still be 403.
        again = self.admin_client.post(
            f"/api/weekly-plans/{plan_id}/confirm?class_id={CLASS_ID}",
            {
                "expected_draft_version": detail["draft"]["version"],
                "acknowledge_missing": True,
                "acknowledge_stale": False,
            },
        )
        self.assertEqual(again.status_code, 403, again.content)
        self.assertEqual(again.code, "FORBIDDEN")

        self.assertEqual(self.confirmed_count(plan_id), confirmed_before)
        v1_content_after = self.rows(
            "SELECT content, facts FROM weekly_plan_confirmed_contents "
            "WHERE weekly_plan_id = :id AND version = 1",
            {"id": plan_id},
        )
        self.assertEqual(v1_content_before, v1_content_after)

    def test_admin_read_requires_explicit_class_id(self):
        plan_id = self._create_and_confirm()
        list_no_class = self.admin_client.get("/api/weekly-plans")
        self.assertEqual(list_no_class.status_code, 422, list_no_class.content)

        detail_no_class = self.admin_client.get(f"/api/weekly-plans/{plan_id}")
        self.assertEqual(detail_no_class.status_code, 422, detail_no_class.content)

        history_no_class = self.admin_client.get(
            f"/api/weekly-plans/{plan_id}/confirmations"
        )
        self.assertEqual(history_no_class.status_code, 422)

        version_no_class = self.admin_client.get(
            f"/api/weekly-plans/{plan_id}/confirmations/1"
        )
        self.assertEqual(version_no_class.status_code, 422)

    def test_admin_wrong_class_id_is_404_on_by_id_routes(self):
        plan_id = self._create_and_confirm()
        wrong = OTHER_CLASS_ID
        cases = {
            "detail": self.admin_client.get(
                f"/api/weekly-plans/{plan_id}?class_id={wrong}"
            ),
            "history": self.admin_client.get(
                f"/api/weekly-plans/{plan_id}/confirmations?class_id={wrong}"
            ),
            "version": self.admin_client.get(
                f"/api/weekly-plans/{plan_id}/confirmations/1?class_id={wrong}"
            ),
            "patch": self.admin_client.patch(
                f"/api/weekly-plans/{plan_id}?class_id={wrong}",
                {"expected_draft_version": 1, "theme": "越权"},
            ),
            "refresh": self.admin_client.post(
                f"/api/weekly-plans/{plan_id}/refresh-sources?class_id={wrong}",
                {"expected_draft_version": 1},
            ),
        }
        for name, response in cases.items():
            self.assertEqual(
                response.status_code, 404, f"{name}: {response.content}"
            )
            self.assertEqual(response.code, "WEEKLY_PLAN_NOT_FOUND", name)

        # Admin confirmation is denied by role before class context is even
        # resolved, so a mismatched admin confirm stays 403 FORBIDDEN — the
        # spec's "管理员不能确认" rule, not a class-context leak.
        confirm = self.admin_client.post(
            f"/api/weekly-plans/{plan_id}/confirm?class_id={wrong}",
            dict(CONFIRM_BODY),
        )
        self.assertEqual(confirm.status_code, 403, confirm.content)
        self.assertEqual(confirm.code, "FORBIDDEN")

        # Nothing was written by the rejected attempts.
        self.assertEqual(self.draft_count(plan_id), 1)
        self.assertEqual(self.confirmed_count(plan_id), 1)

        # Listing under the foreign class context simply does not show it.
        listing = self.admin_client.get(
            f"/api/weekly-plans?class_id={wrong}"
        ).json()
        self.assertEqual(listing["items"], [])
        self.assertEqual(listing["total"], 0)

    # -- cross-class teacher ----------------------------------------------

    def test_cross_class_teacher_is_403_on_by_id_routes(self):
        plan_id = self._create_and_confirm()
        results = self._hit(self.cross_client, plan_id)
        self.assertEqual(results["list"], (200, None))
        self.assertEqual(results["create"], (201, None))
        for name in (
            "detail",
            "patch",
            "refresh",
            "confirm",
            "history",
            "version",
        ):
            self.assertEqual(results[name], (403, "FORBIDDEN"), name)

        # Their own create landed in their own class, not the owner's.
        rows = self.rows(
            "SELECT class_id FROM weekly_plans ORDER BY class_id"
        )
        self.assertEqual(
            rows, [(CLASS_ID,), (OTHER_CLASS_ID,)]
        )
        self.assertEqual(self.plan_count(), 2)

        listing = self.cross_client.get("/api/weekly-plans").json()
        self.assertEqual(listing["total"], 1)
        self.assertNotEqual(listing["items"][0]["id"], plan_id)

    def test_cross_class_create_does_not_touch_other_class_plan(self):
        plan_id = self._create_only()
        before = self.rows(
            "SELECT id, creator_id, owner_id, current_draft_version, "
            "current_confirmed_content_id FROM weekly_plans "
            "WHERE class_id = :cls",
            {"cls": CLASS_ID},
        )
        created = self.cross_client.post(
            "/api/weekly-plans",
            {"term_id": TERM_ID, "week_number": WEEK},
        )
        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(created.json()["class_id"], OTHER_CLASS_ID)
        after = self.rows(
            "SELECT id, creator_id, owner_id, current_draft_version, "
            "current_confirmed_content_id FROM weekly_plans "
            "WHERE class_id = :cls",
            {"cls": CLASS_ID},
        )
        self.assertEqual(before, after)
        self.assertNotEqual(created.json()["id"], plan_id)

    # -- extra status semantics -------------------------------------------

    def test_admin_list_wrong_class_is_not_404_but_detail_is(self):
        plan_id = self._create_and_confirm()
        self.assertEqual(
            self.admin_client.get(
                f"/api/weekly-plans?class_id={OTHER_CLASS_ID}"
            ).status_code,
            200,
        )
        self.assertEqual(
            self.admin_client.get(
                f"/api/weekly-plans/{plan_id}?class_id={OTHER_CLASS_ID}"
            ).status_code,
            404,
        )

    def test_unknown_plan_id_is_404_for_authorized_actors(self):
        missing = "doesnotexist000000000000000000"
        self.assertEqual(
            self.owner_client.get(f"/api/weekly-plans/{missing}").status_code,
            404,
        )
        self.assertEqual(
            self.owner_client.get(
                f"/api/weekly-plans/{missing}/confirmations"
            ).status_code,
            404,
        )
        self.assertEqual(
            self.owner_client.patch(
                f"/api/weekly-plans/{missing}",
                {"expected_draft_version": 1, "theme": "x"},
            ).status_code,
            404,
        )
        self.assertEqual(
            self.admin_client.get(
                f"/api/weekly-plans/{missing}?class_id={CLASS_ID}"
            ).status_code,
            404,
        )

    def test_teacher_routes_reject_unknown_term(self):
        response = self.owner_client.post(
            "/api/weekly-plans",
            {"term_id": "no-such-term", "week_number": 1},
        )
        self.assertEqual(response.status_code, 404, response.content)
        self.assertEqual(response.code, "TERM_NOT_FOUND")

    def test_week_number_out_of_range_is_422(self):
        response = self.owner_client.post(
            "/api/weekly-plans",
            {"term_id": TERM_ID, "week_number": 99},
        )
        self.assertEqual(response.status_code, 422, response.content)
        self.assertEqual(response.code, "VALIDATION_ERROR")
        self.assertEqual(self.plan_count(), 0)
