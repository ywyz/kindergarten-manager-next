"""D2 W2 class game configuration: preview/apply, limits, atomicity, receipts.

Real temp SQLite via ``LocalRuntime`` and a real local Uvicorn server through
the standard-library client. The D1 preview -> apply contract is exercised
end-to-end: the preview's ``normalized_change`` is fed back into apply.
"""

from __future__ import annotations

import unittest
import uuid
from unittest import mock

from app.local import config_service, daily_plan_service
from app.local.errors import LocalError, LocalStorageError
from tests.local.support import LocalTestCase, query_rows, query_scalar


def location(kind: str, name: str, guidance=None) -> dict:
    return {"kind": kind, "name": name, "guidance": guidance}


def change(locations=None, game_scope=None, guidance=None) -> dict:
    return {
        "kind": "class_games",
        "locations": locations if locations is not None else [],
        "game_scope": game_scope,
        "guidance": guidance,
    }


class GameCase(LocalTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.runtime = self.make_runtime()
        self.db = self.runtime.db_path
        self.initialize_profile()

    def initialize_profile(self) -> None:
        from app.local import profile_service
        from app.local.normalize import normalize_initialization
        from tests.local.support import initialize_body

        session = self.runtime.session()
        try:
            profile_service.initialize(
                session, normalize_initialization(**initialize_body())
            )
        finally:
            session.close()

    def session(self):
        return self.runtime.session()

    def preview(self, expected: int, change_obj: dict) -> dict:
        session = self.session()
        try:
            return config_service.preview(
                session, expected_config_version=expected, change=change_obj
            )
        finally:
            session.close()

    def apply(self, expected: int, preview_obj: dict, *, request_id=None) -> dict:
        session = self.session()
        try:
            return config_service.apply(
                session,
                request_id=request_id or str(uuid.uuid4()),
                expected_config_version=expected,
                change=preview_obj["normalized_change"],
                preview_token=preview_obj["preview_token"],
            )
        finally:
            session.close()

    def config_version(self) -> int:
        return query_scalar(
            self.db, "SELECT config_version FROM local_settings WHERE id='singleton'"
        )

    def game_head(self) -> dict:
        rows = query_rows(
            self.db,
            "SELECT h.current_revision_id, r.revision_no, r.payload_json "
            "FROM local_class_game_heads h "
            "JOIN local_class_game_revisions r ON r.id = h.current_revision_id",
        )
        return rows[0]


class GameReadTests(GameCase):
    def test_read_class_games_is_read_only_and_apply_ready(self):
        revisions_before = query_scalar(
            self.db, "SELECT count(*) FROM local_class_game_revisions"
        )
        head_before = self.game_head()
        session = self.session()
        try:
            out = config_service.read_class_games(session)
        finally:
            session.close()
        self.assertEqual(out["revision_no"], 1)
        self.assertEqual(out["config_version"], 1)
        self.assertEqual(
            out["change"],
            {"kind": "class_games", "locations": [], "game_scope": None, "guidance": None},
        )
        self.assertEqual(
            query_scalar(self.db, "SELECT count(*) FROM local_class_game_revisions"),
            revisions_before,
        )
        self.assertEqual(self.game_head(), head_before)

    def test_read_change_seeds_modified_preview(self):
        session = self.session()
        try:
            current = config_service.read_class_games(session)
        finally:
            session.close()
        preview = self.preview(
            current["config_version"],
            {**current["change"], "guidance": "新增通用指导"},
        )
        self.assertTrue(preview["changed"])
        applied = self.apply(current["config_version"], preview)
        self.assertEqual(applied["config_version"], 2)
        session = self.session()
        try:
            reread = config_service.read_class_games(session)
        finally:
            session.close()
        self.assertEqual(reread["revision_no"], 2)
        self.assertEqual(reread["change"]["guidance"], "新增通用指导")


class GameInitialTests(GameCase):
    def test_empty_initial_revision_and_preview_writes_nothing(self):
        head = self.game_head()
        self.assertEqual(head["revision_no"], 1)
        import json

        payload = head["payload_json"]
        payload = json.loads(payload) if isinstance(payload, str) else payload
        self.assertEqual(payload, {"locations": [], "game_scope": None, "guidance": None})
        before_revisions = query_scalar(
            self.db, "SELECT count(*) FROM local_class_game_revisions"
        )
        out = self.preview(1, change(locations=[location("area", "积木区")]))
        self.assertTrue(out["changed"])
        # Preview never writes a revision or bumps the configuration version.
        self.assertEqual(
            query_scalar(self.db, "SELECT count(*) FROM local_class_game_revisions"),
            before_revisions,
        )
        self.assertEqual(self.config_version(), 1)


class GameValidationTests(GameCase):
    def test_per_kind_limit_30(self):
        # 30 of one kind is fine.
        ok = self.preview(
            1, change(locations=[location("area", f"区{i}") for i in range(30)])
        )
        self.assertTrue(ok["changed"])
        # 31 of one kind is refused.
        with self.assertRaises(LocalError) as ctx:
            self.preview(
                1,
                change(locations=[location("area", f"区{i}") for i in range(31)]),
            )
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
        # 30 per each of the three kinds (90 total) is accepted.
        three = (
            [location("area", f"区{i}") for i in range(30)]
            + [location("special_room", f"室{i}") for i in range(30)]
            + [location("outdoor", f"场{i}") for i in range(30)]
        )
        self.assertTrue(self.preview(1, change(locations=three))["changed"])

    def test_text_and_name_limits(self):
        with self.assertRaises(LocalError):
            self.preview(1, change(locations=[location("area", "x" * 81)]))
        with self.assertRaises(LocalError):
            self.preview(1, change(locations=[location("area", "")]))
        with self.assertRaises(LocalError):
            self.preview(
                1, change(locations=[location("area", "区", "g" * 2001)])
            )
        with self.assertRaises(LocalError):
            self.preview(1, change(game_scope="s" * 8001))
        with self.assertRaises(LocalError):
            self.preview(1, change(guidance="g" * 8001))
        # Boundary limits are accepted.
        accepted = self.preview(
            1,
            change(
                locations=[location("area", "区", "g" * 2000)],
                game_scope="s" * 8000,
                guidance="g" * 8000,
            ),
        )
        self.assertTrue(accepted["changed"])

    def test_unknown_nested_field_and_class_id_rejected(self):
        with self.assertRaises(LocalError):
            self.preview(
                1,
                change(locations=[{**location("area", "区"), "id": "x"}]),
            )
        with self.assertRaises(LocalError):
            self.preview(1, {"kind": "class_games", "locations": [], "class_id": "c"})


class GameApplyTests(GameCase):
    def test_apply_bumps_version_and_revision_atomically(self):
        preview = self.preview(
            1,
            change(
                locations=[location("area", "积木区", "轻拿轻放")],
                game_scope="室内外结合",
                guidance="注意安全",
            ),
        )
        result = self.apply(1, preview)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["config_version"], 2)
        self.assertTrue(result["game_revision_id"])
        self.assertEqual(self.config_version(), 2)
        head = self.game_head()
        self.assertEqual(head["revision_no"], 2)
        self.assertEqual(head["current_revision_id"], result["game_revision_id"])

    def test_old_plan_header_unchanged(self):
        session = self.session()
        try:
            plan, _created = daily_plan_service.create_or_open(
                session, plan_date=__import__("datetime").date(2026, 9, 2)
            )
            plan_id = plan["id"]
        finally:
            session.close()
        before = query_rows(
            self.db,
            "SELECT plan_date, term_id, week_number, weekday, "
            "current_content_version, calendar_revision_id FROM local_daily_plans "
            "WHERE id = ?",
            (plan_id,),
        )[0]
        preview = self.preview(
            1, change(locations=[location("outdoor", "操场")], guidance="安全")
        )
        self.apply(1, preview)
        after = query_rows(
            self.db,
            "SELECT plan_date, term_id, week_number, weekday, "
            "current_content_version, calendar_revision_id FROM local_daily_plans "
            "WHERE id = ?",
            (plan_id,),
        )[0]
        self.assertEqual(before, after)

    def test_noop_only_receipt_no_version(self):
        preview = self.preview(1, change(locations=[location("area", "积木区")]))
        self.apply(1, preview, request_id=str(uuid.uuid4()))
        self.assertEqual(self.config_version(), 2)
        revisions = query_scalar(
            self.db, "SELECT count(*) FROM local_class_game_revisions"
        )
        # Same content and the empty string / null equivalence are no-ops.
        same = self.preview(2, preview["normalized_change"])
        self.assertFalse(same["changed"])
        noop = self.apply(2, same, request_id=str(uuid.uuid4()))
        self.assertEqual(noop["status"], "unchanged")
        self.assertEqual(self.config_version(), 2)
        self.assertEqual(
            query_scalar(self.db, "SELECT count(*) FROM local_class_game_revisions"),
            revisions,
        )
        # "" and null both mean empty text: guidance "" equals null.
        empty = self.preview(
            2,
            {
                "kind": "class_games",
                "locations": preview["normalized_change"]["locations"],
                "game_scope": None,
                "guidance": "",
            },
        )
        self.assertFalse(empty["changed"])

    def test_replayed_receipt_after_success(self):
        rid = str(uuid.uuid4())
        preview = self.preview(1, change(locations=[location("area", "积木区")]))
        first = self.apply(1, preview, request_id=rid)
        self.assertEqual(first["config_version"], 2)
        # Resend the same request id with a now-stale expected version: the
        # committed receipt replays instead of a version conflict.
        session = self.session()
        try:
            replay = config_service.apply(
                session,
                request_id=rid,
                expected_config_version=1,
                change=preview["normalized_change"],
                preview_token=preview["preview_token"],
            )
        finally:
            session.close()
        self.assertEqual(replay["config_version"], 2)
        self.assertTrue(replay.get("replayed"))

    def test_different_body_same_request_id_conflict(self):
        rid = str(uuid.uuid4())
        preview = self.preview(1, change(locations=[location("area", "积木区")]))
        self.apply(1, preview, request_id=rid)
        other = self.preview(2, change(locations=[location("outdoor", "操场")]))
        session = self.session()
        try:
            with self.assertRaises(LocalError) as ctx:
                config_service.apply(
                    session,
                    request_id=rid,
                    expected_config_version=2,
                    change=other["normalized_change"],
                    preview_token=other["preview_token"],
                )
            self.assertEqual(ctx.exception.code, "CONFIG_REQUEST_CONFLICT")
        finally:
            session.close()

    def test_stale_expected_version_conflict(self):
        first = self.preview(1, change(locations=[location("area", "积木区")]))
        # Another committed change moves the configuration version before the
        # first preview is applied.
        self.apply(1, self.preview(1, change(locations=[location("outdoor", "操场")])))
        session = self.session()
        try:
            with self.assertRaises(LocalError) as ctx:
                config_service.apply(
                    session,
                    request_id=str(uuid.uuid4()),
                    expected_config_version=1,
                    change=first["normalized_change"],
                    preview_token=first["preview_token"],
                )
            self.assertEqual(ctx.exception.code, "CONFIG_VERSION_CONFLICT")
        finally:
            session.close()

    def test_commit_failure_rolls_back(self):
        preview = self.preview(1, change(locations=[location("area", "积木区")]))
        head_before = self.game_head()
        with mock.patch.object(
            config_service, "_store_receipt", side_effect=LocalStorageError()
        ):
            with self.assertRaises(LocalStorageError):
                self.apply(1, preview)
        self.assertEqual(self.config_version(), 1)
        self.assertEqual(self.game_head(), head_before)


class GameHttpTests(GameCase):
    def setUp(self) -> None:
        super().setUp()
        self.client = self.start_server(self.runtime).client()

    def test_preview_normalized_change_applies_over_http(self):
        norm = change(
            locations=[location("area", "积木区", "轻拿轻放")],
            game_scope="室内",
            guidance="注意安全",
        )
        status, preview = self.client.post(
            "/api/local/config/preview",
            {"expected_config_version": 1, "change": norm},
        )
        self.assertEqual(status, 200, preview)
        self.assertTrue(preview["changed"])
        # The preview's normalized change is a valid apply body (D1 contract).
        status, applied = self.client.post(
            "/api/local/config/apply",
            {
                "request_id": str(uuid.uuid4()),
                "expected_config_version": 1,
                "change": preview["normalized_change"],
                "preview_token": preview["preview_token"],
            },
        )
        self.assertEqual(status, 200, applied)
        self.assertEqual(applied["config_version"], 2)
        self.assertTrue(applied["game_revision_id"])
        # The game revision is readable again via preview.
        status, again = self.client.post(
            "/api/local/config/preview",
            {
                "expected_config_version": 2,
                "change": preview["normalized_change"],
            },
        )
        self.assertEqual(status, 200, again)
        self.assertFalse(again["changed"])

    def test_class_id_and_total_schema_bound_over_http(self):
        status, body = self.client.post(
            "/api/local/config/preview",
            {
                "expected_config_version": 1,
                "change": {**change(), "class_id": "c"},
            },
        )
        self.assertEqual(status, 422, body)
        status, body = self.client.post(
            "/api/local/config/preview",
            {
                "expected_config_version": 1,
                "change": change(
                    locations=[location("area", f"区{i}") for i in range(91)]
                ),
            },
        )
        self.assertEqual(status, 422, body)

    def test_session_and_origin_protection(self):
        status, body = self.client.get("/api/local/context", token=None)
        self.assertEqual(status, 401, body)
        status, body = self.client.post(
            "/api/local/config/preview",
            {"expected_config_version": 1, "change": change()},
            origin="http://evil.example",
        )
        self.assertEqual(status, 403, body)

    def test_class_games_read_over_http(self):
        status, body = self.client.get("/api/local/config/class-games")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["change"]["kind"], "class_games")
        self.assertEqual(body["revision_no"], 1)
        self.assertEqual(body["config_version"], 1)
        self.assertEqual(body["change"]["locations"], [])
        # After an apply the read reflects the new immutable revision.
        preview = self.client.post(
            "/api/local/config/preview",
            {
                "expected_config_version": body["config_version"],
                "change": {
                    "kind": "class_games",
                    "locations": [location("area", "积木区")],
                    "game_scope": None,
                    "guidance": None,
                },
            },
        )[1]
        applied = self.client.post(
            "/api/local/config/apply",
            {
                "request_id": str(uuid.uuid4()),
                "expected_config_version": 1,
                "change": preview["normalized_change"],
                "preview_token": preview["preview_token"],
            },
        )[1]
        status, reread = self.client.get("/api/local/config/class-games")
        self.assertEqual(status, 200, reread)
        self.assertEqual(reread["revision_no"], 2)
        self.assertEqual(reread["game_revision_id"], applied["game_revision_id"])
        self.assertEqual(reread["change"]["locations"][0]["name"], "积木区")


if __name__ == "__main__":
    unittest.main()
