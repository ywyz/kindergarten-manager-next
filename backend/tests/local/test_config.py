"""D1B configuration maintenance: context, preview/apply, terms and overrides.

Real temp file databases, real Uvicorn HTTP and real subprocess workers —
no mocks or in-memory databases. Covers spec §10: multi-term context and
date resolution, old-term entry, preview tokens and staleness, idempotent
receipts, atomic apply with rollback, calendar revision rules (intersection
kept, expansion re-based, overrides never restored), and the
``expected_config_version`` contract on plan creation.
"""

from __future__ import annotations

import time
import unittest
import uuid
from datetime import date

from app.local import config_tokens
from app.services import calendar_service as cal
from tests.local.support import (
    LocalTestCase,
    StaticCalendarProvider,
    calendar_provider,
    execute_sql,
    query_rows,
    query_scalar,
)

SEP_START = "2026-09-01"
SEP_END = "2026-09-30"
OCT_START = "2026-10-01"
OCT_END = "2026-10-31"


def change_profile(display_name="李老师", school_name=None) -> dict:
    return {
        "kind": "profile",
        "display_name": display_name,
        "school_name": school_name,
    }


def change_class(name="大一班", grade="large") -> dict:
    return {"kind": "current_class", "name": name, "grade": grade}


def change_term_create(name="十月学期", start=OCT_START, end=OCT_END) -> dict:
    return {"kind": "term_create", "name": name, "start_date": start, "end_date": end}


def change_term_update(term_id, **overrides) -> dict:
    change = {
        "kind": "term_update",
        "term_id": term_id,
        "name": "2026 年秋季学期",
        "start_date": SEP_START,
        "end_date": SEP_END,
    }
    change.update(overrides)
    return change


def change_override(term_id, day, state, reason=None) -> dict:
    return {
        "kind": "calendar_override",
        "term_id": term_id,
        "date": day,
        "state": state,
        "reason": reason,
    }


class ConfigTestBase(LocalTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.provider = StaticCalendarProvider()
        self.enterContext(calendar_provider(self.provider))
        self.server = self.start_server()
        self.client = self.server.client()
        self.init_payload = self.initialize(self.client)
        self.term_id = self.init_payload["terms"][0]["id"]
        self.revision_id = self.init_payload["terms"][0][
            "current_calendar_revision_id"
        ]

    # -- HTTP helpers ------------------------------------------------------
    def preview(self, expected: int, change: dict):
        return self.client.post(
            "/api/local/config/preview",
            {"expected_config_version": expected, "change": change},
        )

    def apply(self, request_id: str, expected: int, change: dict, token: str):
        return self.client.post(
            "/api/local/config/apply",
            {
                "request_id": request_id,
                "expected_config_version": expected,
                "change": change,
                "preview_token": token,
            },
        )

    def apply_change(self, expected: int, change: dict, *, request_id=None):
        status, preview = self.preview(expected, change)
        self.assertEqual(status, 200, preview)
        return self.apply(
            request_id or str(uuid.uuid4()),
            expected,
            change,
            preview["preview_token"],
        )

    def config_version(self) -> int:
        status, payload = self.client.get("/api/local/context")
        self.assertEqual(status, 200, payload)
        return payload["config_version"]

    def context_for(self, day: str) -> dict:
        status, payload = self.client.get(f"/api/local/context?date={day}")
        self.assertEqual(status, 200, payload)
        return payload


# ---------------------------------------------------------------------------
# Context, date resolution and history entry
# ---------------------------------------------------------------------------


class ContextTests(ConfigTestBase):
    def test_context_defaults_to_local_today_and_lists_terms(self):
        status, payload = self.client.get("/api/local/context")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["as_of_date"], date.today().isoformat())
        self.assertEqual(payload["config_version"], 1)
        self.assertIsNone(payload["term"])
        self.assertEqual(len(payload["terms"]), 1)

    def test_multi_term_context_and_date_resolution(self):
        # Add a second, non-overlapping term.
        status, applied = self.apply_change(1, change_term_create())
        self.assertEqual(status, 200, applied)
        self.assertEqual(applied["status"], "applied")
        self.assertIsNotNone(applied["calendar_revision_id"])

        status, payload = self.client.get("/api/local/context")
        self.assertEqual(status, 200)
        self.assertEqual(payload["config_version"], 2)
        self.assertEqual(len(payload["terms"]), 2)
        # Sorted by start_date, id.
        self.assertEqual(
            [term["start_date"] for term in payload["terms"]],
            [SEP_START, OCT_START],
        )

        inside_sep = self.context_for("2026-09-15")
        self.assertEqual(inside_sep["term"]["name"], "2026 年秋季学期")
        inside_oct = self.context_for("2026-10-15")
        self.assertEqual(inside_oct["term"]["name"], "十月学期")
        outside = self.context_for("2026-11-15")
        self.assertIsNone(outside["term"])
        self.assertIsNone(outside["calendar_revision"])
        # Ready with a date outside every term is never "uninitialized".
        self.assertEqual(outside["status"], "ready")
        self.assertEqual(outside["profile"]["display_name"], "王老师")

    def test_initialize_retry_after_maintenance_reads_current_config(self):
        apply_status, applied = self.apply_change(1, change_profile("李老师", None))
        self.assertEqual(apply_status, 200, applied)
        self.assertEqual(self.config_version(), 2)

        # Same request_id and identical input retries read the *current*
        # configuration back: maintenance is never rolled back.
        status, payload = self.client.post(
            "/api/local/initialize",
            {**self._initialization_input(), "request_id": self._init_request_id},
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["profile"]["display_name"], "李老师")
        self.assertIsNone(payload["school_name"])
        self.assertEqual(payload["config_version"], 2)
        # No rows were re-created or rolled back.
        self.assertEqual(
            query_scalar(self.server.runtime.db_path, "SELECT count(*) AS n FROM local_terms"),
            1,
        )

    def _initialization_input(self) -> dict:
        # Rebuild the exact normalized input used in setUp.
        return {
            "display_name": "王老师",
            "class_name": "中一班",
            "grade": "middle",
            "term_name": "2026 年秋季学期",
            "start_date": SEP_START,
            "end_date": SEP_END,
            "school_name": "示范幼儿园",
        }

    @property
    def _init_request_id(self) -> str:
        # LocalTestCase.initialize used initialize_body(); recover its
        # request id from the persisted settings row (same normalized input).
        return query_scalar(
            self.server.runtime.db_path,
            "SELECT init_request_id FROM local_settings",
        )


# ---------------------------------------------------------------------------
# Profile and class maintenance
# ---------------------------------------------------------------------------


class ProfileAndClassTests(ConfigTestBase):
    def test_profile_preview_apply_keeps_plan_headers_and_versions(self):
        status, plan = self.client.post(
            "/api/daily-plans",
            {"plan_date": "2026-09-01", "raw_lesson_plan": "第一版"},
        )
        self.assertEqual(status, 201, plan)
        status, plan = self.client.patch(
            f"/api/daily-plans/{plan['id']}",
            {"expected_content_version": 1, "raw_lesson_plan": "第二版"},
        )
        self.assertEqual(status, 200, plan)

        change = change_profile("李老师", None)
        status, preview = self.preview(1, change)
        self.assertEqual(status, 200, preview)
        self.assertTrue(preview["changed"])
        self.assertEqual(
            preview["before"],
            {"display_name": "王老师", "school_name": "示范幼儿园"},
        )
        self.assertEqual(
            preview["after"], {"display_name": "李老师", "school_name": None}
        )
        self.assertEqual(preview["calendar_diff"], [])
        impact = preview["impact"]
        self.assertEqual(impact["retained_header_count"], 1)
        self.assertEqual(impact["counts"]["affected_plan_count"], 1)
        item = impact["affected_plans"][0]
        self.assertEqual(item["id"], plan["id"])
        self.assertEqual(item["reasons"], ["header_retained"])
        self.assertEqual(item["content_version"], 2)
        self.assertEqual(item["stored_week_number"], plan["week_number"])

        status, applied = self.apply(
            str(uuid.uuid4()), 1, change, preview["preview_token"]
        )
        self.assertEqual(status, 200, applied)
        self.assertEqual(applied["status"], "applied")
        self.assertEqual(applied["config_version"], 2)
        self.assertEqual(applied["affected_plan_ids"], [plan["id"]])
        self.assertIsNone(applied["calendar_revision_id"])

        # Context reflects the new profile; the saved plan keeps its
        # immutable header snapshot and content version.
        context = self.context_for("2026-09-15")
        self.assertEqual(context["profile"]["display_name"], "李老师")
        self.assertIsNone(context["school_name"])
        self.assertEqual(context["config_version"], 2)
        status, detail = self.client.get(f"/api/daily-plans/{plan['id']}")
        self.assertEqual(status, 200, detail)
        self.assertEqual(detail["creator_display_name"], "王老师")
        self.assertEqual(detail["school_name"], "示范幼儿园")
        self.assertEqual(detail["current_content_version"], 2)
        # No calendar revision was created for a profile change.
        self.assertEqual(
            query_scalar(
                self.server.runtime.db_path,
                "SELECT count(*) AS n FROM local_calendar_revisions",
            ),
            1,
        )

    def test_new_plan_after_profile_change_uses_current_header(self):
        status, applied = self.apply_change(1, change_profile("李老师", "新幼儿园"))
        self.assertEqual(status, 200, applied)
        status, plan = self.client.post(
            "/api/daily-plans", {"plan_date": "2026-09-02"}
        )
        self.assertEqual(status, 201, plan)
        self.assertEqual(plan["creator_display_name"], "李老师")
        self.assertEqual(plan["school_name"], "新幼儿园")

    def test_profile_no_change_preview_unchanged_receipt_before_and_after(self):
        change = change_profile("王老师", "示范幼儿园")  # identical values
        status, preview = self.preview(1, change)
        self.assertEqual(status, 200, preview)
        self.assertFalse(preview["changed"])
        self.assertEqual(preview["calendar_diff"], [])

        request_id = str(uuid.uuid4())
        status, applied = self.apply(
            request_id, 1, change, preview["preview_token"]
        )
        self.assertEqual(status, 200, applied)
        self.assertEqual(applied["status"], "unchanged")
        self.assertEqual(applied["config_version"], 1)
        self.assertEqual(applied["affected_plan_ids"], [])

        audit_before = query_scalar(
            self.server.runtime.db_path,
            "SELECT count(*) AS n FROM local_operation_records",
        )
        # No configuration version, revision or audit was added.
        self.assertEqual(self.config_version(), 1)
        self.assertEqual(
            query_scalar(
                self.server.runtime.db_path,
                "SELECT count(*) AS n FROM local_operation_records",
            ),
            audit_before,
        )

        # A later real change commits v2; the same request id + same input
        # retry still returns the original unchanged receipt (never suddenly
        # applies the old request).
        status, real = self.apply_change(1, change_profile("李老师", None))
        self.assertEqual(status, 200, real)
        self.assertEqual(self.config_version(), 2)
        status, replay = self.apply(
            request_id, 1, change, preview["preview_token"]
        )
        self.assertEqual(status, 200, replay)
        self.assertEqual(replay["status"], "unchanged")
        self.assertEqual(replay["config_version"], 1)
        self.assertTrue(replay.get("replayed"))
        self.assertEqual(self.config_version(), 2)

    def test_class_rename_and_upgrade_keeps_id_and_old_headers(self):
        status, plan = self.client.post(
            "/api/daily-plans", {"plan_date": "2026-09-01"}
        )
        self.assertEqual(status, 201, plan)
        class_id = plan["class_id"]

        status, applied = self.apply_change(1, change_class("大一班", "large"))
        self.assertEqual(status, 200, applied)
        self.assertEqual(applied["affected_plan_ids"], [plan["id"]])
        context = self.context_for("2026-09-15")
        self.assertEqual(context["class"]["id"], class_id)
        self.assertEqual(context["class"]["name"], "大一班")
        self.assertEqual(context["class"]["grade"], "large")

        status, detail = self.client.get(f"/api/daily-plans/{plan['id']}")
        self.assertEqual(status, 200, detail)
        self.assertEqual(detail["class_id"], class_id)
        self.assertEqual(detail["class_name"], "中一班")
        self.assertEqual(detail["grade"], "middle")

        # The upgrade keeps the class id for new plans too.
        status, upgraded = self.client.post(
            "/api/daily-plans", {"plan_date": "2026-09-02"}
        )
        self.assertEqual(status, 201, upgraded)
        self.assertEqual(upgraded["class_id"], class_id)
        self.assertEqual(upgraded["class_name"], "大一班")
        self.assertEqual(upgraded["grade"], "large")


# ---------------------------------------------------------------------------
# Terms: create/update, revisions and calendar rules
# ---------------------------------------------------------------------------


class TermTests(ConfigTestBase):
    def test_term_create_overlap_and_endpoint_share_rejected(self):
        cases = [
            change_term_create(start="2026-09-15", end="2026-10-15"),
            change_term_create(start="2026-09-30", end="2026-10-15"),  # shared endpoint
            change_term_create(start="2026-08-01", end="2026-09-01"),  # shared endpoint
            change_term_create(start="2026-09-01", end="2026-09-30"),  # identical
        ]
        for change in cases:
            with self.subTest(change=change):
                status, payload = self.preview(1, change)
                self.assertEqual(status, 422, payload)
                self.assertEqual(payload["error"]["code"], "TERM_OVERLAP")
        self.assertEqual(
            query_scalar(
                self.server.runtime.db_path,
                "SELECT count(*) AS n FROM local_terms",
            ),
            1,
        )

    def test_term_create_applies_and_calendar_explains_new_term(self):
        status, applied = self.apply_change(1, change_term_create())
        self.assertEqual(status, 200, applied)
        revision_id = applied["calendar_revision_id"]
        self.assertIsNotNone(revision_id)

        # New term's revision is complete for its full range with no
        # overrides; the old revision is untouched.
        days = query_rows(
            self.server.runtime.db_path,
            "SELECT date, base_state, override_state, effective_state, "
            "base_library_version FROM local_calendar_days "
            "WHERE revision_id = ? ORDER BY date",
            (revision_id,),
        )
        self.assertEqual(len(days), 31)
        self.assertEqual(days[0]["date"], OCT_START)
        self.assertTrue(
            all(row["override_state"] is None for row in days)
        )
        self.assertTrue(
            all(row["effective_state"] == row["base_state"] for row in days)
        )
        self.assertTrue(
            all(row["base_library_version"] == self.provider.version for row in days)
        )

        status, payload = self.client.get(
            "/api/local/calendar?from=2026-10-05&to=2026-10-05"
        )
        self.assertEqual(status, 200, payload)
        item = payload["items"][0]
        oct_context = self.context_for("2026-10-15")
        self.assertEqual(item["term_id"], oct_context["term"]["id"])
        self.assertEqual(item["effective_state"], "teaching")
        self.assertTrue(item["date_eligible"])
        self.assertEqual(item["revision_id"], revision_id)

        # A plan on the new term's date resolves to the new term.
        status, plan = self.client.post(
            "/api/daily-plans", {"plan_date": "2026-10-05"}
        )
        self.assertEqual(status, 201, plan)
        self.assertNotEqual(plan["term_id"], self.term_id)
        self.assertEqual(plan["calendar_revision_id"], revision_id)

    def test_term_update_rename_only_adds_no_revision(self):
        status, preview = self.preview(
            1, change_term_update(self.term_id, name="秋季学期（改名）")
        )
        self.assertEqual(status, 200, preview)
        self.assertEqual(preview["calendar_diff"], [])
        self.assertEqual(
            preview["before"]["name"], "2026 年秋季学期"
        )
        self.assertEqual(preview["after"]["name"], "秋季学期（改名）")
        status, applied = self.apply(
            str(uuid.uuid4()), 1, change_term_update(self.term_id, name="秋季学期（改名）"),
            preview["preview_token"],
        )
        self.assertEqual(status, 200, applied)
        self.assertIsNone(applied["calendar_revision_id"])
        self.assertEqual(
            query_scalar(
                self.server.runtime.db_path,
                "SELECT count(*) AS n FROM local_calendar_revisions",
            ),
            1,
        )
        context = self.context_for("2026-09-15")
        self.assertEqual(context["term"]["name"], "秋季学期（改名）")
        self.assertEqual(context["calendar_revision"]["id"], self.revision_id)

    def test_term_rename_and_noop_with_plans_use_existing_interpretation(self):
        # R7: rename-only / no-op previews on a term that already has saved
        # plans must complete normally (no revision, no fake date changes);
        # the no-op apply only records the idempotent receipt.
        db = self.server.runtime.db_path
        status, plan = self.client.post(
            "/api/daily-plans", {"plan_date": "2026-09-15"}
        )
        self.assertEqual(status, 201, plan)

        rename = change_term_update(self.term_id, name="秋季学期（改名）")
        status, preview = self.preview(1, rename)
        self.assertEqual(status, 200, preview)
        self.assertTrue(preview["changed"])
        self.assertEqual(preview["calendar_diff"], [])
        self.assertEqual(preview["impact"]["retained_header_count"], 1)
        self.assertEqual(preview["impact"]["affected_plans"], [])
        revisions_before = query_scalar(
            db, "SELECT count(*) AS n FROM local_calendar_revisions"
        )
        status, applied = self.apply(
            str(uuid.uuid4()), 1, rename, preview["preview_token"]
        )
        self.assertEqual(status, 200, applied)
        self.assertIsNone(applied["calendar_revision_id"])
        self.assertEqual(
            query_scalar(
                db, "SELECT count(*) AS n FROM local_calendar_revisions"
            ),
            revisions_before,
        )
        status, detail = self.client.get(f"/api/daily-plans/{plan['id']}")
        self.assertEqual(status, 200, detail)
        self.assertEqual(detail["term_id"], self.term_id)
        self.assertEqual(detail["current_content_version"], 1)

        # No-op: same name and range as the current state.
        noop = change_term_update(self.term_id, name="秋季学期（改名）")
        status, preview = self.preview(2, noop)
        self.assertEqual(status, 200, preview)
        self.assertFalse(preview["changed"])
        self.assertEqual(preview["calendar_diff"], [])
        receipts_before = query_scalar(
            db, "SELECT count(*) AS n FROM local_config_operations"
        )
        audit_before = query_scalar(
            db, "SELECT count(*) AS n FROM local_operation_records"
        )
        status, applied = self.apply(
            str(uuid.uuid4()), 2, noop, preview["preview_token"]
        )
        self.assertEqual(status, 200, applied)
        self.assertEqual(applied["status"], "unchanged")
        self.assertEqual(applied["affected_plan_ids"], [])
        self.assertEqual(
            query_scalar(db, "SELECT config_version FROM local_settings"), 2
        )
        self.assertEqual(
            query_scalar(
                db, "SELECT count(*) AS n FROM local_config_operations"
            ),
            receipts_before + 1,
        )
        self.assertEqual(
            query_scalar(
                db, "SELECT count(*) AS n FROM local_operation_records"
            ),
            audit_before,
        )

    def test_move_term_across_intermediate_term_has_no_false_impact(self):
        # R8: moving a term across another unchanged term must not report
        # storage corruption nor invent diffs/impact facts for the middle
        # term; saved plans keep their ownership, week numbers and versions.
        db = self.server.runtime.db_path
        status, created = self.apply_change(1, change_term_create())
        self.assertEqual(status, 200, created)
        oct_revision = created["calendar_revision_id"]
        oct_context = self.context_for("2026-10-15")
        oct_term_id = oct_context["term"]["id"]

        status, sep_plan = self.client.post(
            "/api/daily-plans", {"plan_date": "2026-09-15"}
        )
        self.assertEqual(status, 201, sep_plan)
        status, oct_plan = self.client.post(
            "/api/daily-plans", {"plan_date": "2026-10-15"}
        )
        self.assertEqual(status, 201, oct_plan)

        move = change_term_update(
            self.term_id,
            start_date="2026-11-01",
            end_date="2026-11-30",
        )
        status, preview = self.preview(2, move)
        self.assertEqual(status, 200, preview)

        diff_dates = [item["date"] for item in preview["calendar_diff"]]
        self.assertTrue(
            all(not day.startswith("2026-10") for day in diff_dates)
        )
        self.assertIn("2026-09-15", diff_dates)
        self.assertIn("2026-11-15", diff_dates)

        affected = {
            item["id"]: item for item in preview["impact"]["affected_plans"]
        }
        self.assertEqual(list(affected), [sep_plan["id"]])
        self.assertIn("outside_new_range", affected[sep_plan["id"]]["reasons"])

        status, applied = self.apply(
            str(uuid.uuid4()), 2, move, preview["preview_token"]
        )
        self.assertEqual(status, 200, applied)
        new_revision = applied["calendar_revision_id"]
        days = query_rows(
            db,
            "SELECT date FROM local_calendar_days WHERE revision_id = ? "
            "ORDER BY date",
            (new_revision,),
        )
        self.assertEqual(len(days), 30)
        self.assertEqual(days[0]["date"], "2026-11-01")
        self.assertEqual(days[-1]["date"], "2026-11-30")

        # The intermediate (October) term keeps its revision untouched.
        oct_after = self.context_for("2026-10-15")
        self.assertEqual(oct_after["term"]["id"], oct_term_id)
        self.assertEqual(oct_after["calendar_revision"]["id"], oct_revision)
        self.assertEqual(
            query_scalar(
                db,
                "SELECT count(*) AS n FROM local_calendar_days "
                "WHERE revision_id = ?",
                (oct_revision,),
            ),
            31,
        )
        for plan in (sep_plan, oct_plan):
            status, detail = self.client.get(f"/api/daily-plans/{plan['id']}")
            self.assertEqual(status, 200, detail)
            self.assertEqual(detail["term_id"], plan["term_id"])
            self.assertEqual(detail["plan_date"], plan["plan_date"])
            self.assertEqual(detail["week_number"], plan["week_number"])
            self.assertEqual(detail["current_content_version"], 1)

    def test_term_update_expansion_copies_intersection_and_builds_new_days(self):
        db = self.server.runtime.db_path
        # Put an override on an intersection date so preservation is visible.
        status, override = self.apply_change(
            1, change_override(self.term_id, "2026-09-05", "teaching", "调休")
        )
        self.assertEqual(status, 200, override)
        override_revision = override["calendar_revision_id"]

        status, plan = self.client.post(
            "/api/daily-plans", {"plan_date": "2026-09-01"}
        )
        self.assertEqual(status, 201, plan)

        # Expand the start to 2026-08-24: intersection keeps the override and
        # stored library versions; new dates get the library base.
        change = change_term_update(self.term_id, start_date="2026-08-24")
        status, preview = self.preview(2, change)
        self.assertEqual(status, 200, preview)
        diff_dates = {item["date"] for item in preview["calendar_diff"]}
        self.assertIn("2026-08-24", diff_dates)
        self.assertIn("2026-09-05", diff_dates)  # week numbers shift
        item = preview["impact"]["affected_plans"][0]
        self.assertEqual(item["id"], plan["id"])
        self.assertIn("week_changed", item["reasons"])
        self.assertEqual(item["stored_week_number"], 1)
        self.assertEqual(item["proposed_week_number"], 2)

        status, applied = self.apply(
            str(uuid.uuid4()), 2, change, preview["preview_token"]
        )
        self.assertEqual(status, 200, applied)
        new_revision = applied["calendar_revision_id"]
        self.assertIsNotNone(new_revision)
        self.assertEqual(
            query_scalar(
                db,
                "SELECT revision_no FROM local_calendar_revisions WHERE id = ?",
                (new_revision,),
            ),
            3,
        )
        # Intersection rows copied (override kept, stored versions kept).
        copied = query_rows(
            db,
            "SELECT base_state, base_library_version, override_state, "
            "override_reason, effective_state FROM local_calendar_days "
            "WHERE revision_id = ? AND date = '2026-09-05'",
            (new_revision,),
        )[0]
        self.assertEqual(copied["base_state"], "non_teaching")
        self.assertEqual(copied["override_state"], "teaching")
        self.assertEqual(copied["override_reason"], "调休")
        self.assertEqual(copied["effective_state"], "teaching")
        self.assertEqual(copied["base_library_version"], self.provider.version)
        # New dates built fresh with no override.
        fresh = query_rows(
            db,
            "SELECT base_state, override_state, effective_state FROM "
            "local_calendar_days WHERE revision_id = ? AND date = '2026-08-24'",
            (new_revision,),
        )[0]
        self.assertEqual(fresh["base_state"], "teaching")
        self.assertIsNone(fresh["override_state"])
        # Old revisions keep their own rows (no retroactive rewrite).
        self.assertEqual(
            query_scalar(
                db,
                "SELECT override_state FROM local_calendar_days "
                "WHERE revision_id = ? AND date = '2026-09-05'",
                (override_revision,),
            ),
            "teaching",
        )
        # Plan headers: stored week/date/revision untouched by the change.
        status, detail = self.client.get(f"/api/daily-plans/{plan['id']}")
        self.assertEqual(status, 200, detail)
        self.assertEqual(detail["week_number"], 1)
        self.assertEqual(detail["calendar_revision_id"], plan["calendar_revision_id"])
        self.assertEqual(detail["plan_date"], "2026-09-01")

    def test_moved_out_plan_stays_readable_listable_and_savable(self):
        status, plan = self.client.post(
            "/api/daily-plans", {"plan_date": "2026-09-30"}
        )
        self.assertEqual(status, 201, plan)

        # Shrink the term so the plan date is outside the current range.
        change = change_term_update(self.term_id, end_date="2026-09-15")
        status, preview = self.preview(1, change)
        self.assertEqual(status, 200, preview)
        item = preview["impact"]["affected_plans"][0]
        self.assertEqual(item["id"], plan["id"])
        self.assertIn("outside_new_range", item["reasons"])
        self.assertFalse(item["creation_eligible_after"])
        status, applied = self.apply(
            str(uuid.uuid4()), 1, change, preview["preview_token"]
        )
        self.assertEqual(status, 200, applied)

        # Calendar: outside term but the existing plan entry stays.
        status, payload = self.client.get(
            "/api/local/calendar?from=2026-09-30&to=2026-09-30"
        )
        self.assertEqual(status, 200, payload)
        item = payload["items"][0]
        self.assertIsNone(item["term_id"])
        self.assertFalse(item["date_eligible"])
        self.assertEqual(item["existing_plan_id"], plan["id"])

        # Repeated create opens the original plan (no migration, no second).
        status, reopened = self.client.post(
            "/api/daily-plans", {"plan_date": "2026-09-30"}
        )
        self.assertEqual(status, 200, reopened)
        self.assertEqual(reopened["id"], plan["id"])
        self.assertEqual(reopened["term_id"], self.term_id)

        # Term-scoped list returns the moved-out record with stored ownership.
        status, listed = self.client.get(
            f"/api/local/terms/{self.term_id}/daily-plans"
        )
        self.assertEqual(status, 200, listed)
        self.assertEqual(listed["total"], 1)
        entry = listed["items"][0]
        self.assertEqual(entry["id"], plan["id"])
        self.assertEqual(entry["class_id"], plan["class_id"])
        self.assertEqual(entry["term_id"], self.term_id)

        # PATCH keeps editing regardless of the current creation eligibility.
        status, saved = self.client.patch(
            f"/api/daily-plans/{plan['id']}",
            {"expected_content_version": 1, "raw_lesson_plan": "移出后仍可编辑"},
        )
        self.assertEqual(status, 200, saved)
        self.assertEqual(saved["current_content_version"], 2)

    def test_term_list_endpoint_404_and_pagination_validation(self):
        status, payload = self.client.get(
            "/api/local/terms/missing-term/daily-plans"
        )
        self.assertEqual(status, 404, payload)
        self.assertEqual(payload["error"]["code"], "TERM_NOT_FOUND")
        status, payload = self.client.get(
            f"/api/local/terms/{self.term_id}/daily-plans?limit=0"
        )
        self.assertEqual(status, 422, payload)
        self.assertEqual(payload["error"]["code"], "VALIDATION_ERROR")

    def test_shrink_then_expand_does_not_restore_removed_override(self):
        db = self.server.runtime.db_path
        status, applied = self.apply_change(
            1, change_override(self.term_id, "2026-09-05", "teaching", "曾经例外")
        )
        self.assertEqual(status, 200, applied)
        override_revision = applied["calendar_revision_id"]

        # Shrink to exclude 2026-09-05.
        status, applied = self.apply_change(
            2, change_term_update(self.term_id, end_date="2026-09-04")
        )
        self.assertEqual(status, 200, applied)
        # Expand back: the re-included date uses the library base again; the
        # old override stays only in the historical revision.
        status, applied = self.apply_change(
            3, change_term_update(self.term_id)
        )
        self.assertEqual(status, 200, applied)
        current = query_scalar(
            db,
            "SELECT current_calendar_revision_id FROM local_terms",
        )
        row = query_rows(
            db,
            "SELECT base_state, override_state, effective_state FROM "
            "local_calendar_days WHERE revision_id = ? AND date = '2026-09-05'",
            (current,),
        )[0]
        self.assertEqual(row["base_state"], "non_teaching")
        self.assertIsNone(row["override_state"])
        self.assertEqual(row["effective_state"], "non_teaching")
        # The historical revision still holds the old override.
        historical = query_rows(
            db,
            "SELECT override_state, override_reason FROM local_calendar_days "
            "WHERE revision_id = ? AND date = '2026-09-05'",
            (override_revision,),
        )[0]
        self.assertEqual(historical["override_state"], "teaching")
        self.assertEqual(historical["override_reason"], "曾经例外")


# ---------------------------------------------------------------------------
# Calendar overrides
# ---------------------------------------------------------------------------


class OverrideTests(ConfigTestBase):
    def test_override_set_change_revoke_builds_revisions(self):
        db = self.server.runtime.db_path
        status, applied = self.apply_change(
            1, change_override(self.term_id, "2026-09-05", "teaching", "调休上课")
        )
        self.assertEqual(status, 200, applied)
        rev2 = applied["calendar_revision_id"]
        status, payload = self.client.get(
            "/api/local/calendar?from=2026-09-05&to=2026-09-05"
        )
        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["items"][0]["date_eligible"])
        self.assertEqual(payload["items"][0]["revision_id"], rev2)

        # Same state, different reason: still a real change.
        status, preview = self.preview(
            2, change_override(self.term_id, "2026-09-05", "teaching", "调整说明")
        )
        self.assertEqual(status, 200, preview)
        self.assertTrue(preview["changed"])
        diff = preview["calendar_diff"][0]
        self.assertEqual(diff["override_before"]["reason"], "调休上课")
        self.assertEqual(diff["override_after"]["reason"], "调整说明")
        status, applied = self.apply(
            str(uuid.uuid4()),
            2,
            change_override(self.term_id, "2026-09-05", "teaching", "调整说明"),
            preview["preview_token"],
        )
        self.assertEqual(status, 200, applied)
        self.assertEqual(
            query_scalar(
                db,
                "SELECT revision_no FROM local_calendar_revisions WHERE id = ?",
                (applied["calendar_revision_id"],),
            ),
            3,
        )

        # Revoking falls back to the persisted base (non_teaching Saturday).
        status, preview = self.preview(
            3, change_override(self.term_id, "2026-09-05", None, None)
        )
        self.assertEqual(status, 200, preview)
        self.assertTrue(preview["changed"])
        status, applied = self.apply(
            str(uuid.uuid4()),
            3,
            change_override(self.term_id, "2026-09-05", None, None),
            preview["preview_token"],
        )
        self.assertEqual(status, 200, applied)
        status, payload = self.client.get(
            "/api/local/calendar?from=2026-09-05&to=2026-09-05"
        )
        self.assertEqual(payload["items"][0]["effective_state"], "non_teaching")
        self.assertFalse(payload["items"][0]["date_eligible"])

    def test_override_validation_and_location_rules(self):
        bad_cases = [
            (change_override(self.term_id, "2026-09-05", "teaching", None), "reason"),
            (change_override(self.term_id, "2026-09-05", None, "不该有原因"), "reason"),
            (
                {
                    "kind": "calendar_override",
                    "term_id": self.term_id,
                    "date": "2026-09-05",
                    "state": "invalid",
                    "reason": "x",
                },
                "state",
            ),
            (change_override(self.term_id, "2026-09-05", "teaching", "x" * 201), "reason"),
            (change_override(self.term_id, "2026-10-05", "teaching", "范围外"), "range"),
        ]
        for change, label in bad_cases:
            with self.subTest(label=label):
                status, payload = self.preview(1, change)
                self.assertEqual(status, 422, payload)
                self.assertEqual(payload["error"]["code"], "VALIDATION_ERROR")
        # Unknown term is 404.
        status, payload = self.preview(
            1, change_override("missing-term", "2026-09-05", "teaching", "x")
        )
        self.assertEqual(status, 404, payload)
        self.assertEqual(payload["error"]["code"], "TERM_NOT_FOUND")

    def test_unknown_year_accepts_manual_override(self):
        # Initialize never happened for 2027; add an unknown-year term.
        unknown_provider = StaticCalendarProvider(
            version="calendar-unknown", unknown_years={2027}
        )
        cal.register_provider(unknown_provider, unknown_provider.version)
        try:
            status, applied = self.apply_change(
                1,
                change_term_create(
                    name="2027 春季学期", start="2027-01-04", end="2027-01-15"
                ),
            )
            self.assertEqual(status, 200, applied)
            term_id = query_scalar(
                self.server.runtime.db_path,
                "SELECT id FROM local_terms WHERE name = '2027 春季学期'",
            )
            status, override = self.apply_change(
                2, change_override(term_id, "2027-01-05", "teaching", "手工开课")
            )
            self.assertEqual(status, 200, override)
        finally:
            cal.register_provider(self.provider, self.provider.version)
        status, payload = self.client.get(
            "/api/local/calendar?from=2027-01-05&to=2027-01-05"
        )
        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["items"][0]["date_eligible"])
        # A plan can now be created on the manually opened unknown day.
        status, plan = self.client.post(
            "/api/daily-plans", {"plan_date": "2027-01-05"}
        )
        self.assertEqual(status, 201, plan)

    def test_incomplete_current_revision_rejects_preview_and_apply(self):
        # R9: a current revision missing days is corrupt storage. Preview and
        # apply (even with a valid pre-corruption token) must refuse instead
        # of cloning an incomplete revision or silently rebuilding the
        # missing day; no version, pointer, days, audit or receipt changes.
        db = self.server.runtime.db_path
        change = change_override(self.term_id, "2026-09-05", "teaching", "调休")
        status, preview = self.preview(1, change)
        self.assertEqual(status, 200, preview)
        request_id = str(uuid.uuid4())

        execute_sql(
            db, "DELETE FROM local_calendar_days WHERE date = '2026-09-10'"
        )
        before = {
            "config_version": query_scalar(
                db, "SELECT config_version FROM local_settings"
            ),
            "revisions": query_scalar(
                db, "SELECT count(*) AS n FROM local_calendar_revisions"
            ),
            "days": query_scalar(
                db, "SELECT count(*) AS n FROM local_calendar_days"
            ),
            "audit": query_scalar(
                db, "SELECT count(*) AS n FROM local_operation_records"
            ),
            "receipts": query_scalar(
                db, "SELECT count(*) AS n FROM local_config_operations"
            ),
            "pointer": query_scalar(
                db,
                "SELECT current_calendar_revision_id FROM local_terms "
                "WHERE id = ?",
                (self.term_id,),
            ),
        }

        status, payload = self.apply(
            request_id, 1, change, preview["preview_token"]
        )
        self.assertEqual(status, 503, payload)
        self.assertEqual(payload["error"]["code"], "LOCAL_STORAGE_ERROR")

        status, payload = self.preview(1, change)
        self.assertEqual(status, 503, payload)
        self.assertEqual(payload["error"]["code"], "LOCAL_STORAGE_ERROR")

        # A range change on the same incomplete revision is refused too
        # (never silently rebuilt from today's library).
        status, payload = self.preview(
            1, change_term_update(self.term_id, start_date="2026-08-24")
        )
        self.assertEqual(status, 503, payload)
        self.assertEqual(payload["error"]["code"], "LOCAL_STORAGE_ERROR")

        after = {
            "config_version": query_scalar(
                db, "SELECT config_version FROM local_settings"
            ),
            "revisions": query_scalar(
                db, "SELECT count(*) AS n FROM local_calendar_revisions"
            ),
            "days": query_scalar(
                db, "SELECT count(*) AS n FROM local_calendar_days"
            ),
            "audit": query_scalar(
                db, "SELECT count(*) AS n FROM local_operation_records"
            ),
            "receipts": query_scalar(
                db, "SELECT count(*) AS n FROM local_config_operations"
            ),
            "pointer": query_scalar(
                db,
                "SELECT current_calendar_revision_id FROM local_terms "
                "WHERE id = ?",
                (self.term_id,),
            ),
        }
        self.assertEqual(after, before)

    def test_override_does_not_call_library(self):
        # Once data exists, override-only configuration works even while the
        # library is failing (no default-state calls on that path).
        failing = StaticCalendarProvider(version="calendar-fail", fail=True)
        cal.register_provider(failing, failing.version)
        try:
            status, applied = self.apply_change(
                1, change_override(self.term_id, "2026-09-05", "teaching", "离线调休")
            )
        finally:
            cal.register_provider(self.provider, self.provider.version)
        self.assertEqual(status, 200, applied)
        status, payload = self.client.get(
            "/api/local/calendar?from=2026-09-05&to=2026-09-05"
        )
        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["items"][0]["date_eligible"])

    def test_library_failure_on_new_dates_is_calendar_unavailable(self):
        failing = StaticCalendarProvider(
            version="calendar-fail-2027", fail_years={2027}
        )
        cal.register_provider(failing, failing.version)
        try:
            status, payload = self.preview(
                1,
                change_term_create(
                    name="2027 春季学期", start="2027-02-01", end="2027-02-10"
                ),
            )
        finally:
            cal.register_provider(self.provider, self.provider.version)
        self.assertEqual(status, 503, payload)
        self.assertEqual(payload["error"]["code"], "CALENDAR_UNAVAILABLE")
        # Nothing was written.
        self.assertEqual(
            query_scalar(
                self.server.runtime.db_path,
                "SELECT count(*) AS n FROM local_terms",
            ),
            1,
        )


# ---------------------------------------------------------------------------
# Protocol: tokens, staleness, conflicts, receipts, rollback
# ---------------------------------------------------------------------------


class ProtocolTests(ConfigTestBase):
    def test_version_conflict_details_on_preview_and_create(self):
        status, payload = self.preview(5, change_profile("新名字", None))
        self.assertEqual(status, 409, payload)
        self.assertEqual(payload["error"]["code"], "CONFIG_VERSION_CONFLICT")
        self.assertEqual(payload["error"]["details"], {"config_version": 1})

        # POST /daily-plans: wrong expected version conflicts with details
        # and creates nothing; omitting keeps the D1A contract; a matching
        # version creates.
        status, payload = self.client.post(
            "/api/daily-plans",
            {"plan_date": "2026-09-01", "expected_config_version": 5},
        )
        self.assertEqual(status, 409, payload)
        self.assertEqual(payload["error"]["code"], "CONFIG_VERSION_CONFLICT")
        self.assertEqual(payload["error"]["details"]["config_version"], 1)
        self.assertEqual(
            query_scalar(
                self.server.runtime.db_path,
                "SELECT count(*) AS n FROM local_daily_plans",
            ),
            0,
        )
        status, plan = self.client.post(
            "/api/daily-plans",
            {"plan_date": "2026-09-01", "expected_config_version": 1},
        )
        self.assertEqual(status, 201, plan)
        # An existing record opens even when the page's version is stale.
        status, reopened = self.client.post(
            "/api/daily-plans",
            {"plan_date": "2026-09-01", "expected_config_version": 9},
        )
        self.assertEqual(status, 200, reopened)
        self.assertEqual(reopened["id"], plan["id"])

    def test_token_tamper_expiry_and_mismatch(self):
        # Missing/garbage token.
        status, payload = self.apply(
            str(uuid.uuid4()), 1, change_profile("李老师", None), "garbage"
        )
        self.assertEqual(status, 422, payload)
        self.assertEqual(payload["error"]["code"], "VALIDATION_ERROR")

        status, payload = self.client.post(
            "/api/local/config/apply",
            {
                "request_id": str(uuid.uuid4()),
                "expected_config_version": 1,
                "change": change_profile("李老师", None),
            },
        )
        self.assertEqual(status, 422, payload)

        # Tampered signature.
        status, preview = self.preview(1, change_profile("李老师", None))
        self.assertEqual(status, 200, preview)
        token = preview["preview_token"]
        body, signature = token.split(".")
        tampered = f"{body}.{'0' * len(signature)}"
        status, payload = self.apply(
            str(uuid.uuid4()), 1, change_profile("李老师", None), tampered
        )
        self.assertEqual(status, 422, payload)
        self.assertEqual(payload["error"]["code"], "VALIDATION_ERROR")

        # Expired token (signed with the live key, expiry in the past).
        expired = config_tokens.sign_preview_token(
            {
                "v": 1,
                "exp": int(time.time()) - 5,
                "config_version": 1,
                "change": change_profile("李老师", None),
                "changed": True,
                "premise_digest": "0",
                "candidate_digest": "0",
                "impact_digest": "0",
            }
        )
        status, payload = self.apply(
            str(uuid.uuid4()), 1, change_profile("李老师", None), expired
        )
        self.assertEqual(status, 409, payload)
        self.assertEqual(payload["error"]["code"], "CONFIG_PREVIEW_EXPIRED")

        # Valid token, different change: mismatch is refused.
        status, payload = self.apply(
            str(uuid.uuid4()), 1, change_profile("另一个名字", None), token
        )
        self.assertEqual(status, 409, payload)
        self.assertEqual(payload["error"]["code"], "CONFIG_PREVIEW_STALE")
        self.assertEqual(self.config_version(), 1)

    def test_unicode_and_malformed_tokens_are_validation_errors(self):
        # R10: unicode / malformed preview tokens are a predictable 422, not
        # an internal error; a valid preview/apply still works afterwards.
        change = change_profile("李老师", None)
        for token in ("中文.abcd", "e30.中文", "中文.中文", "e30.e30"):
            with self.subTest(token=token):
                status, payload = self.apply(
                    str(uuid.uuid4()), 1, change, token
                )
                self.assertEqual(status, 422, payload)
                self.assertEqual(payload["error"]["code"], "VALIDATION_ERROR")
        self.assertEqual(self.config_version(), 1)

        status, preview = self.preview(1, change)
        self.assertEqual(status, 200, preview)
        status, applied = self.apply(
            str(uuid.uuid4()), 1, change, preview["preview_token"]
        )
        self.assertEqual(status, 200, applied)
        self.assertEqual(applied["status"], "applied")
        self.assertEqual(self.config_version(), 2)

    def test_stale_when_plan_set_changes_after_preview(self):
        status, preview = self.preview(1, change_profile("李老师", None))
        self.assertEqual(status, 200, preview)
        # A new plan changes the retained-header facts (0 -> 1).
        status, plan = self.client.post(
            "/api/daily-plans", {"plan_date": "2026-09-01"}
        )
        self.assertEqual(status, 201, plan)
        status, payload = self.apply(
            str(uuid.uuid4()), 1, change_profile("李老师", None),
            preview["preview_token"],
        )
        self.assertEqual(status, 409, payload)
        self.assertEqual(payload["error"]["code"], "CONFIG_PREVIEW_STALE")
        self.assertEqual(self.config_version(), 1)

    def test_stale_same_impact_count_different_versions(self):
        status, plan = self.client.post(
            "/api/daily-plans", {"plan_date": "2026-09-01"}
        )
        self.assertEqual(status, 201, plan)
        change = change_term_update(self.term_id, start_date="2026-08-24")
        status, preview = self.preview(1, change)
        self.assertEqual(status, 200, preview)
        self.assertEqual(len(preview["impact"]["affected_plans"]), 1)

        # A content save changes only the plan's version: the impact count is
        # identical, yet the preview must be refused.
        status, saved = self.client.patch(
            f"/api/daily-plans/{plan['id']}",
            {"expected_content_version": 1, "raw_lesson_plan": "改了内容"},
        )
        self.assertEqual(status, 200, saved)
        status, payload = self.apply(
            str(uuid.uuid4()), 1, change, preview["preview_token"]
        )
        self.assertEqual(status, 409, payload)
        self.assertEqual(payload["error"]["code"], "CONFIG_PREVIEW_STALE")

    def test_apply_after_another_config_conflicts_with_latest_version(self):
        status, preview = self.preview(1, change_profile("李老师", None))
        self.assertEqual(status, 200, preview)
        status, other = self.apply_change(1, change_class("大一班", "large"))
        self.assertEqual(status, 200, other)
        self.assertEqual(self.config_version(), 2)
        status, payload = self.apply(
            str(uuid.uuid4()), 1, change_profile("李老师", None),
            preview["preview_token"],
        )
        self.assertEqual(status, 409, payload)
        self.assertEqual(payload["error"]["code"], "CONFIG_VERSION_CONFLICT")
        self.assertEqual(payload["error"]["details"], {"config_version": 2})

    def test_receipt_replay_conflicts_and_operations_endpoint(self):
        change = change_profile("李老师", None)
        request_id = str(uuid.uuid4())
        status, applied = self.apply_change(1, change, request_id=request_id)
        self.assertEqual(status, 200, applied)
        self.assertEqual(applied["status"], "applied")
        self.assertEqual(applied["config_version"], 2)

        # Same request id + same normalized input replays the result without
        # another version.
        status, replay = self.apply(
            request_id, 1, change, "any-token-not-consulted-on-replay"
        )
        self.assertEqual(status, 200, replay)
        self.assertTrue(replay.get("replayed"))
        self.assertEqual(replay["config_version"], 2)
        self.assertEqual(self.config_version(), 2)

        # Same key, different input: explicit conflict.
        status, payload = self.apply(
            request_id, 1, change_profile("不同名字", None), "x"
        )
        self.assertEqual(status, 409, payload)
        self.assertEqual(payload["error"]["code"], "CONFIG_REQUEST_CONFLICT")

        # Same key, same change but different expected version: the
        # fingerprint differs, so it is also a request conflict.
        status, payload = self.apply(
            request_id, 2, change, "x"
        )
        self.assertEqual(status, 409, payload)
        self.assertEqual(payload["error"]["code"], "CONFIG_REQUEST_CONFLICT")

        # Receipt lookup returns the same committed result; unknown ids 404.
        status, stored = self.client.get(
            f"/api/local/config/operations/{request_id}"
        )
        self.assertEqual(status, 200, stored)
        self.assertEqual(stored["status"], "applied")
        self.assertEqual(stored["config_version"], 2)
        self.assertIsNone(stored.get("replayed"))
        status, missing = self.client.get(
            f"/api/local/config/operations/{uuid.uuid4()}"
        )
        self.assertEqual(status, 404, missing)
        self.assertEqual(missing["error"]["code"], "CONFIG_OPERATION_NOT_FOUND")

    def test_apply_requires_profile_and_session(self):
        # Uninitialized database: configuration endpoints refuse with 409.
        server = self.start_server(self.make_runtime(self.tmp_root / "fresh-data"))
        client = server.client()
        status, payload = client.post(
            "/api/local/config/preview",
            {"expected_config_version": 1, "change": change_profile()},
        )
        self.assertEqual(status, 409, payload)
        self.assertEqual(payload["error"]["code"], "LOCAL_PROFILE_REQUIRED")
        # Session guard still applies first for a bad token.
        status, payload = client.post(
            "/api/local/config/preview",
            {"expected_config_version": 1, "change": change_profile()},
            token="wrong",
        )
        self.assertEqual(status, 401, payload)
        self.assertEqual(payload["error"]["code"], "APP_SESSION_REQUIRED")

    def test_extra_fields_are_rejected(self):
        status, payload = self.client.post(
            "/api/local/config/preview",
            {
                "expected_config_version": 1,
                "change": {**change_profile(), "extra": True},
            },
        )
        self.assertEqual(status, 422, payload)
        self.assertEqual(payload["error"]["code"], "VALIDATION_ERROR")
        status, payload = self.client.post(
            "/api/local/config/preview",
            {"expected_config_version": 1, "change": change_profile(), "extra": 1},
        )
        self.assertEqual(status, 422, payload)

    def test_apply_failure_rolls_back_everything(self):
        db = self.server.runtime.db_path
        before = {
            "config_version": query_scalar(
                db, "SELECT config_version FROM local_settings"
            ),
            "revisions": query_scalar(
                db, "SELECT count(*) AS n FROM local_calendar_revisions"
            ),
            "days": query_scalar(
                db, "SELECT count(*) AS n FROM local_calendar_days"
            ),
            "audit": query_scalar(
                db, "SELECT count(*) AS n FROM local_operation_records"
            ),
            "receipts": query_scalar(
                db, "SELECT count(*) AS n FROM local_config_operations"
            ),
        }
        # The receipt insert is the last write: fail there to prove the whole
        # configuration transaction rolls back.
        execute_sql(
            db,
            "CREATE TRIGGER fail_config_receipt BEFORE INSERT ON "
            "local_config_operations BEGIN SELECT RAISE(ABORT, 'injected'); END",
        )
        change = change_override(self.term_id, "2026-09-05", "teaching", "注入")
        status, preview = self.preview(1, change)
        self.assertEqual(status, 200, preview)
        request_id = str(uuid.uuid4())
        status, payload = self.apply(
            request_id, 1, change, preview["preview_token"]
        )
        self.assertEqual(status, 503, payload)
        self.assertEqual(payload["error"]["code"], "LOCAL_STORAGE_ERROR")
        after = {
            "config_version": query_scalar(
                db, "SELECT config_version FROM local_settings"
            ),
            "revisions": query_scalar(
                db, "SELECT count(*) AS n FROM local_calendar_revisions"
            ),
            "days": query_scalar(
                db, "SELECT count(*) AS n FROM local_calendar_days"
            ),
            "audit": query_scalar(
                db, "SELECT count(*) AS n FROM local_operation_records"
            ),
            "receipts": query_scalar(
                db, "SELECT count(*) AS n FROM local_config_operations"
            ),
        }
        self.assertEqual(after, before)

        # After the fault is removed the same request id and token succeed.
        execute_sql(db, "DROP TRIGGER fail_config_receipt")
        status, applied = self.apply(
            request_id, 1, change, preview["preview_token"]
        )
        self.assertEqual(status, 200, applied)
        self.assertEqual(applied["status"], "applied")

    def test_config_version_check_constraint(self):
        db = self.server.runtime.db_path
        import sqlite3

        with self.assertRaises(sqlite3.IntegrityError):
            execute_sql(db, "UPDATE local_settings SET config_version = 0")
        self.assertEqual(self.config_version(), 1)


# ---------------------------------------------------------------------------
# Concurrent applies (one real server process, two simultaneous requests)
# ---------------------------------------------------------------------------


class ConcurrencyTests(ConfigTestBase):
    def _both(self, request_a, request_b):
        """Fire two real HTTP requests simultaneously; return both results."""
        import threading

        barrier = threading.Barrier(2)
        results: list = [None, None]

        def run(index: int, fn):
            barrier.wait(timeout=30)
            results[index] = fn()

        threads = [
            threading.Thread(target=run, args=(0, request_a)),
            threading.Thread(target=run, args=(1, request_b)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
        self.assertIsNotNone(results[0])
        self.assertIsNotNone(results[1])
        return results

    def test_two_simultaneous_applies_same_request_replay(self):
        change = change_profile("李老师", None)
        status, preview = self.preview(1, change)
        self.assertEqual(status, 200, preview)
        request_id = str(uuid.uuid4())

        def submit():
            return self.apply(request_id, 1, change, preview["preview_token"])

        (status_a, payload_a), (status_b, payload_b) = self._both(
            submit, submit
        )
        self.assertEqual(status_a, 200, payload_a)
        self.assertEqual(status_b, 200, payload_b)
        payloads = [payload_a, payload_b]
        self.assertEqual(
            sorted(bool(payload.get("replayed")) for payload in payloads),
            [False, True],
        )
        self.assertEqual(
            sorted(payload["config_version"] for payload in payloads), [2, 2]
        )
        self.assertEqual(self.config_version(), 2)
        self.assertEqual(
            query_scalar(
                self.server.runtime.db_path,
                "SELECT count(*) AS n FROM local_config_operations",
            ),
            1,
        )

    def test_two_simultaneous_applies_different_configs_one_wins(self):
        first = change_profile("李老师", None)
        second = change_class("大一班", "large")
        status, preview1 = self.preview(1, first)
        status2, preview2 = self.preview(1, second)
        self.assertEqual(status, 200, preview1)
        self.assertEqual(status2, 200, preview2)

        def submit(preview, change):
            return self.apply(
                str(uuid.uuid4()), 1, change, preview["preview_token"]
            )

        (status_a, payload_a), (status_b, payload_b) = self._both(
            lambda: submit(preview1, first), lambda: submit(preview2, second)
        )
        outcomes = []
        for status, payload in ((status_a, payload_a), (status_b, payload_b)):
            if payload.get("error"):
                self.assertEqual(status, 409, payload)
                outcomes.append(payload["error"]["code"])
            else:
                self.assertEqual(status, 200, payload)
                outcomes.append(payload["status"])
        self.assertEqual(outcomes.count("applied"), 1, outcomes)
        self.assertEqual(
            [code for code in outcomes if code != "applied"],
            ["CONFIG_VERSION_CONFLICT"],
            outcomes,
        )
        self.assertEqual(self.config_version(), 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
