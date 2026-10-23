"""D3-A H1: daily-plan history reads and whole-plan restore over real SQLite/API.

Synthetic temporary database and real local Uvicorn HTTP only; no supplier,
real teacher database or credential root. Content versions are created through
the normal service/adoption paths.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import unittest
import uuid
from datetime import date
from unittest import mock

from alembic import command
from sqlalchemy.orm import Session

from app.local import daily_plan_history_service, daily_plan_service, profile_service
from app.local.ai_provenance import BASELINE_KEY
from app.local.migrate import alembic_config
from app.local.normalize import normalize_initialization
from tests.local.support import (
    execute_sql,
    initialize_body,
    query_rows,
    query_scalar,
)
from tests.local.test_d2_w4_api import W4ApiCase
from tests.local.test_d2_w4_candidates import OTHER_CANDIDATE, SPLIT_CANDIDATE


class D3HistoryCase(W4ApiCase):
    def _db_snapshot(self, db=None):
        path = db or self.db
        tables = (
            "local_daily_plan_contents",
            "local_daily_plan_ai_provenance",
            "local_daily_plan_restores",
            "local_operation_records",
        )
        return {
            "tables": {
                table: query_rows(path, f"SELECT * FROM {table} ORDER BY rowid")
                for table in tables
            },
            "plans": query_rows(
                path,
                "SELECT id, current_content_id, current_content_version "
                "FROM local_daily_plans ORDER BY id",
            ),
        }

    def history(self, version):
        return self.client.get(
            f"/api/daily-plans/{self.plan['id']}/history/{version}"
        )

    def preview_restore(self, source, expected):
        return self.client.post(
            f"/api/daily-plans/{self.plan['id']}/history/preview-restore",
            {
                "source_content_version": source,
                "expected_content_version": expected,
            },
        )

    def restore(self, token, expected, request_id=None):
        return self.client.post(
            f"/api/daily-plans/{self.plan['id']}/history/restore",
            {
                "request_id": request_id or str(uuid.uuid4()),
                "preview_token": token,
                "expected_content_version": expected,
            },
        )

    def test_list_get_preview_restore_receipt_and_idempotency(self):
        plan_id = self.plan["id"]
        v1_content = self.plan_content(plan_id)
        v1_raw = v1_content["raw_lesson_plan"]
        v1_adopted = v1_content["adopted_content"]
        self.save_content(
            plan_id,
            1,
            {"reflection": "v2 反思"},
            raw="v2 原文",
        )

        status, history = self.client.get(
            f"/api/daily-plans/{plan_id}/history?limit=1"
        )
        self.assertEqual(status, 200, history)
        self.assertEqual(history["current_content_version"], 2)
        self.assertEqual([item["version"] for item in history["items"]], [2])
        self.assertTrue(history["items"][0]["is_current"])
        self.assertEqual(history["next_before_version"], 2)

        status, page2 = self.client.get(
            f"/api/daily-plans/{plan_id}/history?limit=1&before_version=2"
        )
        self.assertEqual(status, 200, page2)
        self.assertEqual([item["version"] for item in page2["items"]], [1])
        self.assertEqual(page2["next_before_version"], None)

        status, old = self.history(1)
        self.assertEqual(status, 200, old)
        self.assertEqual(old["content"]["version"], 1)
        self.assertEqual(old["content"]["raw_lesson_plan"], v1_raw)
        self.assertEqual(old["content"]["adopted_content"], v1_adopted)
        self.assertFalse(old["is_current"])
        self.assertIsNone(old["restored_from_version"])

        status, preview = self.preview_restore(1, 2)
        self.assertEqual(status, 200, preview)
        self.assertEqual(preview["source_version"], 1)
        self.assertEqual(preview["current_version"], 2)
        self.assertEqual(preview["after"]["adopted_content"], v1_adopted)
        self.assertEqual(preview["before"]["version"], 2)
        token = preview["preview_token"]
        request_id = str(uuid.uuid4())
        status, restored = self.restore(token, 2, request_id=request_id)
        self.assertEqual(status, 200, restored)
        self.assertEqual(restored["source_content_version"], 1)
        self.assertEqual(restored["before_content_version"], 2)
        self.assertEqual(restored["content_version"], 3)

        status, current = self.client.get(f"/api/daily-plans/{plan_id}")
        self.assertEqual(status, 200, current)
        self.assertEqual(current["current_content_version"], 3)
        self.assertEqual(current["content"]["raw_lesson_plan"], v1_raw)
        self.assertEqual(current["content"]["adopted_content"], v1_adopted)

        status, history3 = self.client.get(f"/api/daily-plans/{plan_id}/history")
        self.assertEqual(status, 200, history3)
        by_version = {item["version"]: item for item in history3["items"]}
        self.assertEqual(by_version[3]["restored_from_version"], 1)
        self.assertTrue(by_version[3]["is_current"])
        self.assertFalse(by_version[2]["is_current"])
        self.assertEqual(
            {item["version"] for item in history3["items"]}, {1, 2, 3}
        )

        status, receipt = self.client.get(
            f"/api/daily-plans/{plan_id}/history/restore-operations/{request_id}"
        )
        self.assertEqual(status, 200, receipt)
        self.assertEqual(receipt, restored)

        # Same request/token replays the committed result even after the
        # in-memory preview store is gone (process restart equivalent).
        daily_plan_history_service.reset_tokens()
        status, replay = self.restore(token, 2, request_id=request_id)
        self.assertEqual(status, 200, replay)
        self.assertEqual(replay, restored)

        # A different request id with the same token cannot apply again.
        status, expired = self.restore(token, 3, request_id=str(uuid.uuid4()))
        self.assertEqual(status, 409, expired)
        self.assertEqual(expired["error"]["code"], "HISTORY_PREVIEW_EXPIRED")

        # Current version cannot be a restore source.
        status, current_preview = self.preview_restore(3, 3)
        self.assertEqual(status, 422, current_preview)
        self.assertEqual(current_preview["error"]["code"], "VALIDATION_ERROR")

        # A same key with a different request body is a conflict, not a second
        # version.
        status, preview2 = self.preview_restore(2, 3)
        self.assertEqual(status, 200, preview2)
        status, conflict = self.restore(
            preview2["preview_token"], 3, request_id=request_id
        )
        self.assertEqual(status, 409, conflict)
        self.assertEqual(conflict["error"]["code"], "HISTORY_REQUEST_CONFLICT")
        status, still = self.client.get(f"/api/daily-plans/{plan_id}")
        self.assertEqual(still["current_content_version"], 3)

        # Old rows remain readable and unchanged.
        for version, expected in ((1, v1_adopted), (2, {"reflection": "v2 反思"})):
            status, row = self.history(version)
            self.assertEqual(status, 200, row)
            self.assertEqual(row["content"]["adopted_content"], expected)

    def test_baseline_and_provenance_survive_restore(self):
        plan_id = self.plan["id"]
        split_id = self.generate(plan_id, "daily_lesson_split", SPLIT_CANDIDATE)
        status, preview = self.preview_http(
            split_id, ["group_activity"], SPLIT_CANDIDATE
        )
        self.assertEqual(status, 200, preview)
        status, adopted = self.adopt_http(
            split_id, preview["preview_token"], request_id=str(uuid.uuid4())
        )
        self.assertEqual(status, 200, adopted)
        content_v2 = self.plan_content(plan_id)
        baseline = content_v2["split_baseline"]
        self.assertEqual(baseline, {BASELINE_KEY: SPLIT_CANDIDATE["group_activity"]["process"]})
        adopted_v2 = content_v2["adopted_content"]

        self.save_content(
            plan_id,
            2,
            adopted_v2,
            raw="v3 原文",
        )
        status, preview = self.preview_restore(2, 3)
        self.assertEqual(status, 200, preview)
        self.assertEqual(preview["after"]["split_baseline"], baseline)
        status, restored = self.restore(
            preview["preview_token"], 3, request_id=str(uuid.uuid4())
        )
        self.assertEqual(status, 200, restored)
        content_v4 = self.plan_content(plan_id)
        self.assertEqual(content_v4["version"], 4)
        self.assertEqual(content_v4["split_baseline"], baseline)
        self.assertEqual(content_v4["adopted_content"], adopted_v2)

        self.session.expire_all()
        row = self.session.execute(
            __import__("sqlalchemy").text(
                "SELECT baseline_candidate_id, adopted_candidate_id, selected_targets_json "
                "FROM local_daily_plan_ai_provenance WHERE content_id = :id"
            ),
            {"id": restored["content_id"]},
        ).mappings().one()
        self.assertEqual(row["baseline_candidate_id"], split_id)
        self.assertIsNone(row["adopted_candidate_id"])
        self.assertEqual(json.loads(row["selected_targets_json"]), {})

    def test_history_is_scoped_and_missing_versions_are_not_empty(self):
        plan_id = self.plan["id"]
        status, missing = self.history(99)
        self.assertEqual(status, 404, missing)
        self.assertEqual(missing["error"]["code"], "HISTORY_NOT_FOUND")
        status, missing_plan = self.client.get(
            "/api/daily-plans/not-a-plan/history"
        )
        self.assertEqual(status, 404, missing_plan)
        status, bad_limit = self.client.get(
            f"/api/daily-plans/{plan_id}/history?limit=201"
        )
        self.assertEqual(status, 422, bad_limit)

        other = self.make_plan(plan_date=date(2026, 9, 3), raw="另一份计划")
        status, other_history = self.client.get(
            f"/api/daily-plans/{other['id']}/history"
        )
        self.assertEqual(status, 200, other_history)
        self.assertEqual(other_history["current_content_version"], 1)
        status, wrong_plan_receipt = self.client.get(
            f"/api/daily-plans/{other['id']}/history/restore-operations/{uuid.uuid4()}"
        )
        self.assertEqual(status, 404, wrong_plan_receipt)


    def test_restore_historical_group_ids_and_stale_receipt(self):
        plan_id = self.plan["id"]
        other_id = self.generate(
            plan_id, "daily_other_activities", OTHER_CANDIDATE
        )
        status, preview = self.preview_http(
            other_id, ["morning_games", "morning_talk"], OTHER_CANDIDATE
        )
        self.assertEqual(status, 200, preview)
        status, adopted = self.adopt_http(
            other_id, preview["preview_token"], request_id=str(uuid.uuid4())
        )
        self.assertEqual(status, 200, adopted)
        v2 = self.plan_content(plan_id)
        adopted_v2 = v2["adopted_content"]
        group_ids = [g["group_id"] for g in adopted_v2["morning_games"]]
        self.assertTrue(all(group_ids))

        self.save_content(
            plan_id,
            2,
            {"reflection": "v3 已移除历史游戏"},
            raw="v3 原文",
        )
        v3 = self.plan_content(plan_id)
        self.assertNotIn("morning_games", v3["adopted_content"])
        status, preview = self.preview_restore(2, 3)
        self.assertEqual(status, 200, preview)
        status, restored = self.restore(
            preview["preview_token"], 3, request_id=str(uuid.uuid4())
        )
        self.assertEqual(status, 200, restored)
        v4 = self.plan_content(plan_id)
        self.assertEqual(v4["adopted_content"], adopted_v2)
        self.assertEqual(
            [g["group_id"] for g in v4["adopted_content"]["morning_games"]],
            group_ids,
        )

        # A later save does not change the historical receipt result.
        self.save_content(plan_id, 4, adopted_v2, raw="v5 原文")
        status, receipt = self.client.get(
            f"/api/daily-plans/{plan_id}/history/restore-operations/"
            f"{restored['request_id']}"
        )
        self.assertEqual(status, 200, receipt)
        self.assertEqual(receipt["content_version"], 4)
        status, current = self.client.get(f"/api/daily-plans/{plan_id}")
        self.assertEqual(current["current_content_version"], 5)

    def test_preview_binds_plan_and_current_snapshot(self):
        plan_id = self.plan["id"]
        self.save_content(plan_id, 1, {"reflection": "v2"}, raw="v2 原文")
        status, preview = self.preview_restore(1, 2)
        self.assertEqual(status, 200, preview)
        other = self.make_plan(plan_date=date(2026, 9, 3), raw="另一份")
        status, cross = self.client.post(
            f"/api/daily-plans/{other['id']}/history/restore",
            {
                "request_id": str(uuid.uuid4()),
                "preview_token": preview["preview_token"],
                "expected_content_version": 1,
            },
        )
        self.assertEqual(status, 409, cross)
        self.assertEqual(cross["error"]["code"], "HISTORY_PREVIEW_EXPIRED")

        # A save after preview invalidates the token's current snapshot.
        self.save_content(plan_id, 2, {"reflection": "v3"}, raw="v3 原文")
        status, stale = self.restore(
            preview["preview_token"], 2, request_id=str(uuid.uuid4())
        )
        self.assertEqual(status, 409, stale)
        self.assertEqual(stale["error"]["code"], "VERSION_CONFLICT")
        status, current = self.client.get(f"/api/daily-plans/{plan_id}")
        self.assertEqual(current["current_content_version"], 3)

    def test_corrupt_source_and_expired_preview_do_not_write(self):
        plan_id = self.plan["id"]
        self.save_content(plan_id, 1, {"reflection": "v2"}, raw="v2 原文")
        execute_sql(
            self.db,
            "UPDATE local_daily_plan_contents SET adopted_content = ? "
            "WHERE daily_plan_id = ? AND version = 1",
            ("{not-json", plan_id),
        )
        status, corrupt = self.preview_restore(1, 2)
        self.assertEqual(status, 503, corrupt)
        self.assertEqual(corrupt["error"]["code"], "LOCAL_STORAGE_ERROR")
        status, current = self.client.get(f"/api/daily-plans/{plan_id}")
        self.assertEqual(current["current_content_version"], 2)

        # Use a clean source in a fresh runtime state for the expiry case.
        self.save_content(plan_id, 2, {"reflection": "v3"}, raw="v3 原文")
        daily_plan_history_service.reset_tokens()
        with mock.patch.object(
            daily_plan_history_service, "_now", return_value=1000.0
        ):
            status, preview = self.preview_restore(2, 3)
        self.assertEqual(status, 200, preview)
        with mock.patch.object(
            daily_plan_history_service, "_now", return_value=2000.0
        ):
            status, expired = self.restore(
                preview["preview_token"], 3, request_id=str(uuid.uuid4())
            )
        self.assertEqual(status, 409, expired)
        self.assertEqual(expired["error"]["code"], "HISTORY_PREVIEW_EXPIRED")
        status, current = self.client.get(f"/api/daily-plans/{plan_id}")
        self.assertEqual(current["current_content_version"], 3)
        daily_plan_history_service.reset_tokens()


    def test_soft_deleted_plan_blocks_receipt_and_replay(self):
        plan_id = self.plan["id"]
        self.save_content(plan_id, 1, {"reflection": "v2"}, raw="v2 原文")
        status, preview = self.preview_restore(1, 2)
        self.assertEqual(status, 200, preview)
        request_id = str(uuid.uuid4())
        status, restored = self.restore(
            preview["preview_token"], 2, request_id=request_id
        )
        self.assertEqual(status, 200, restored)
        profile_id = query_scalar(self.db, "SELECT id FROM local_profile")
        execute_sql(
            self.db,
            "UPDATE local_daily_plans SET deleted_at = ?, deleted_by = ? WHERE id = ?",
            ("2026-10-23 12:00:00", profile_id, plan_id),
        )
        status, receipt = self.client.get(
            f"/api/daily-plans/{plan_id}/history/restore-operations/{request_id}"
        )
        self.assertEqual(status, 404, receipt)
        self.assertEqual(receipt["error"]["code"], "DAILY_PLAN_NOT_FOUND")
        status, replay = self.restore(
            preview["preview_token"], 2, request_id=request_id
        )
        self.assertEqual(status, 404, replay)
        self.assertEqual(replay["error"]["code"], "DAILY_PLAN_NOT_FOUND")

    def test_restore_audit_failure_is_storage_error_and_rolls_back(self):
        plan_id = self.plan["id"]
        self.save_content(plan_id, 1, {"reflection": "v2"}, raw="v2 原文")
        status, preview = self.preview_restore(1, 2)
        self.assertEqual(status, 200, preview)
        before = self._db_snapshot()
        execute_sql(
            self.db,
            "CREATE TRIGGER fail_restore_audit "
            "BEFORE INSERT ON local_operation_records "
            "WHEN NEW.action = 'restore_daily_plan' "
            "BEGIN SELECT RAISE(ABORT, 'synthetic audit failure'); END",
        )
        try:
            status, failed = self.restore(
                preview["preview_token"], 2, request_id=str(uuid.uuid4())
            )
            self.assertEqual(status, 503, failed)
            self.assertEqual(failed["error"]["code"], "LOCAL_STORAGE_ERROR")
        finally:
            execute_sql(self.db, "DROP TRIGGER fail_restore_audit")
        self.assertEqual(self._db_snapshot(), before)
        status, current = self.client.get(f"/api/daily-plans/{plan_id}")
        self.assertEqual(current["current_content_version"], 2)
        self.assertEqual(
            query_scalar(
                self.db,
                "SELECT count(*) FROM local_daily_plan_restores WHERE daily_plan_id = ?",
                (plan_id,),
            ),
            0,
        )
        self.assertEqual(
            query_scalar(
                self.db,
                "SELECT count(*) FROM local_daily_plan_contents WHERE daily_plan_id = ?",
                (plan_id,),
            ),
            2,
        )

    def test_history_rejects_malformed_page_and_missing_current_pointer(self):
        plan_id = self.plan["id"]
        self.save_content(plan_id, 1, {"reflection": "v2"}, raw="v2 原文")
        execute_sql(
            self.db,
            "UPDATE local_daily_plan_contents SET adopted_content = ? "
            "WHERE daily_plan_id = ? AND version = 1",
            ("{not-json", plan_id),
        )
        status, malformed = self.client.get(
            f"/api/daily-plans/{plan_id}/history"
        )
        self.assertEqual(status, 503, malformed)
        self.assertEqual(malformed["error"]["code"], "LOCAL_STORAGE_ERROR")

        execute_sql(
            self.db,
            "UPDATE local_daily_plan_contents SET adopted_content = ? "
            "WHERE daily_plan_id = ? AND version = 1",
            ('{"unexpected": true}', plan_id),
        )
        status, wrong_shape = self.client.get(
            f"/api/daily-plans/{plan_id}/history"
        )
        self.assertEqual(status, 503, wrong_shape)
        self.assertEqual(wrong_shape["error"]["code"], "LOCAL_STORAGE_ERROR")

        conn = sqlite3.connect(self.db)
        try:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute(
                "UPDATE local_daily_plans SET current_content_id = ? WHERE id = ?",
                ("missing-content", plan_id),
            )
            conn.commit()
        finally:
            conn.close()
        status, missing = self.client.get(f"/api/daily-plans/{plan_id}/history")
        self.assertEqual(status, 503, missing)
        self.assertEqual(missing["error"]["code"], "LOCAL_STORAGE_ERROR")

    def test_preview_binds_baseline_candidate_identity(self):
        plan_id = self.plan["id"]
        split_a = self.generate(plan_id, "daily_lesson_split", SPLIT_CANDIDATE)
        status, preview = self.preview_http(
            split_a, ["group_activity"], SPLIT_CANDIDATE
        )
        self.assertEqual(status, 200, preview)
        status, adopted = self.adopt_http(
            split_a, preview["preview_token"], request_id=str(uuid.uuid4())
        )
        self.assertEqual(status, 200, adopted)
        self.save_content(plan_id, 2, self.plan_content(plan_id)["adopted_content"], raw="v3")
        status, restore_preview = self.preview_restore(2, 3)
        self.assertEqual(status, 200, restore_preview)
        split_b = self.generate(plan_id, "daily_lesson_split", SPLIT_CANDIDATE)
        v2_content_id = query_scalar(
            self.db,
            "SELECT id FROM local_daily_plan_contents "
            "WHERE daily_plan_id = ? AND version = 2",
            (plan_id,),
        )
        execute_sql(
            self.db,
            "UPDATE local_daily_plan_ai_provenance SET baseline_candidate_id = ? "
            "WHERE content_id = ?",
            (split_b, v2_content_id),
        )
        status, stale = self.restore(
            restore_preview["preview_token"], 3, request_id=str(uuid.uuid4())
        )
        self.assertEqual(status, 409, stale)
        self.assertEqual(stale["error"]["code"], "HISTORY_PREVIEW_EXPIRED")
        status, current = self.client.get(f"/api/daily-plans/{plan_id}")
        self.assertEqual(current["current_content_version"], 3)

    def test_history_rejects_unsupported_baseline_contract(self):
        plan_id = self.plan["id"]
        split = self.generate(plan_id, "daily_lesson_split", SPLIT_CANDIDATE)
        status, preview = self.preview_http(
            split, ["group_activity"], SPLIT_CANDIDATE
        )
        self.assertEqual(status, 200, preview)
        status, adopted = self.adopt_http(
            split, preview["preview_token"], request_id=str(uuid.uuid4())
        )
        self.assertEqual(status, 200, adopted)
        self.save_content(plan_id, 2, self.plan_content(plan_id)["adopted_content"], raw="v3")
        execution_id = query_scalar(
            self.db,
            "SELECT execution_id FROM local_ai_candidates WHERE id = ?",
            (split,),
        )
        execute_sql(
            self.db,
            "INSERT INTO local_prompt_bundles "
            "(task_type, contract_version, default_revision, input_schema_json, "
            "output_schema_json, guidance_defaults_json, bundle_hash, created_at) "
            "SELECT 'daily_lesson_split', 2, 2, input_schema_json, output_schema_json, "
            "guidance_defaults_json, bundle_hash, created_at "
            "FROM local_prompt_bundles WHERE task_type = 'daily_lesson_split' "
            "AND contract_version = 1 AND default_revision = 2",
        )
        execute_sql(
            self.db,
            "UPDATE local_ai_candidates SET contract_version = 2 WHERE id = ?",
            (split,),
        )
        execute_sql(
            self.db,
            "UPDATE local_ai_executions SET contract_version = 2 WHERE id = ?",
            (execution_id,),
        )
        status, rejected = self.preview_restore(2, 3)
        self.assertEqual(status, 503, rejected)
        self.assertEqual(rejected["error"]["code"], "LOCAL_STORAGE_ERROR")
        status, current = self.client.get(f"/api/daily-plans/{plan_id}")
        self.assertEqual(current["current_content_version"], 3)

    def test_concurrent_same_key_and_different_key_restores(self):
        plan_id = self.plan["id"]
        self.save_content(plan_id, 1, {"reflection": "v2"}, raw="v2 原文")
        self.session.expire_all()
        preview = daily_plan_history_service.preview_restore(
            self.session,
            plan_id=plan_id,
            source_content_version=1,
            expected_content_version=2,
        )
        token = preview["preview_token"]
        request_id = str(uuid.uuid4())
        barrier = threading.Barrier(2)
        results = []

        def worker(rid, tok):
            session = self.runtime.session()
            try:
                barrier.wait()
                results.append(
                    (
                        "ok",
                        daily_plan_history_service.restore(
                            session,
                            plan_id=plan_id,
                            expected_content_version=2,
                            preview_token=tok,
                            request_id=rid,
                        ),
                    )
                )
            except Exception as exc:  # noqa: BLE001 - test records the class
                results.append(("error", exc))
            finally:
                session.close()

        threads = [
            threading.Thread(target=worker, args=(request_id, token))
            for _ in range(2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        self.assertEqual(len([r for r in results if r[0] == "ok"]), 2, results)
        self.assertEqual(
            query_scalar(
                self.db,
                "SELECT current_content_version FROM local_daily_plans WHERE id = ?",
                (plan_id,),
            ),
            3,
        )
        self.assertEqual(
            query_scalar(
                self.db,
                "SELECT count(*) FROM local_daily_plan_restores WHERE daily_plan_id = ?",
                (plan_id,),
            ),
            1,
        )

    def test_concurrent_different_keys_only_one_restore(self):
        plan_id = self.plan["id"]
        self.save_content(plan_id, 1, {"reflection": "v2"}, raw="v2 原文")
        self.session.expire_all()
        preview1 = daily_plan_history_service.preview_restore(
            self.session,
            plan_id=plan_id,
            source_content_version=1,
            expected_content_version=2,
        )
        preview2 = daily_plan_history_service.preview_restore(
            self.session,
            plan_id=plan_id,
            source_content_version=1,
            expected_content_version=2,
        )
        token1 = preview1["preview_token"]
        token2 = preview2["preview_token"]
        barrier = threading.Barrier(2)
        results = []

        def worker(tok):
            session = self.runtime.session()
            try:
                barrier.wait()
                results.append(
                    (
                        "ok",
                        daily_plan_history_service.restore(
                            session,
                            plan_id=plan_id,
                            expected_content_version=2,
                            preview_token=tok,
                            request_id=str(uuid.uuid4()),
                        ),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                results.append(("error", exc))
            finally:
                session.close()

        threads = [threading.Thread(target=worker, args=(tok,)) for tok in (token1, token2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        successes = [r for r in results if r[0] == "ok"]
        errors = [r for r in results if r[0] == "error"]
        self.assertEqual(len(successes), 1, results)
        self.assertEqual(len(errors), 1, results)
        self.assertEqual(
            query_scalar(
                self.db,
                "SELECT current_content_version FROM local_daily_plans WHERE id = ?",
                (plan_id,),
            ),
            3,
        )
        self.assertEqual(
            query_scalar(
                self.db,
                "SELECT count(*) FROM local_daily_plan_restores WHERE daily_plan_id = ?",
                (plan_id,),
            ),
            1,
        )

    def test_each_restore_write_failure_rolls_back(self):
        plan_id = self.plan["id"]
        self.save_content(plan_id, 1, {"reflection": "v2"}, raw="v2 原文")
        triggers = {
            "content": "CREATE TRIGGER fail_restore_content "
            "BEFORE INSERT ON local_daily_plan_contents "
            "WHEN NEW.version > 1 BEGIN SELECT RAISE(ABORT, 'fail'); END",
            "provenance": "CREATE TRIGGER fail_restore_provenance "
            "BEFORE INSERT ON local_daily_plan_ai_provenance "
            "WHEN NEW.content_version > 1 BEGIN SELECT RAISE(ABORT, 'fail'); END",
            "restore": "CREATE TRIGGER fail_restore_record "
            "BEFORE INSERT ON local_daily_plan_restores "
            "BEGIN SELECT RAISE(ABORT, 'fail'); END",
            "pointer": "CREATE TRIGGER fail_restore_pointer "
            "BEFORE UPDATE ON local_daily_plans "
            "WHEN NEW.current_content_version > OLD.current_content_version "
            "BEGIN SELECT RAISE(ABORT, 'fail'); END",
            "audit": "CREATE TRIGGER fail_restore_audit "
            "BEFORE INSERT ON local_operation_records "
            "WHEN NEW.action = 'restore_daily_plan' "
            "BEGIN SELECT RAISE(ABORT, 'fail'); END",
        }
        for name, create in triggers.items():
            self.session.expire_all()
            preview = daily_plan_history_service.preview_restore(
                self.session,
                plan_id=plan_id,
                source_content_version=1,
                expected_content_version=2,
            )
            token = preview["preview_token"]
            before = self._db_snapshot()
            execute_sql(self.db, create)
            session = self.runtime.session()
            try:
                with self.assertRaises(Exception) as ctx:
                    daily_plan_history_service.restore(
                        session,
                        plan_id=plan_id,
                        expected_content_version=2,
                        preview_token=token,
                        request_id=str(uuid.uuid4()),
                    )
                self.assertEqual(getattr(ctx.exception, "code", None), "LOCAL_STORAGE_ERROR")
            finally:
                session.close()
                execute_sql(self.db, f"DROP TRIGGER fail_restore_{name if name != 'restore' else 'record'}")
            self.assertEqual(self._db_snapshot(), before)

    def test_commit_failure_rolls_back(self):
        plan_id = self.plan["id"]
        self.save_content(plan_id, 1, {"reflection": "v2"}, raw="v2 原文")
        self.session.expire_all()
        preview = daily_plan_history_service.preview_restore(
            self.session,
            plan_id=plan_id,
            source_content_version=1,
            expected_content_version=2,
        )
        token = preview["preview_token"]
        before = self._db_snapshot()
        session = self.runtime.session()
        try:
            with mock.patch.object(Session, "commit", side_effect=RuntimeError("commit")):
                with self.assertRaises(RuntimeError):
                    daily_plan_history_service.restore(
                        session,
                        plan_id=plan_id,
                        expected_content_version=2,
                        preview_token=token,
                        request_id=str(uuid.uuid4()),
                    )
        finally:
            session.close()
        self.assertEqual(self._db_snapshot(), before)

    def test_restore_composite_fk_rejects_cross_plan_content(self):
        plan_id = self.plan["id"]
        self.save_content(plan_id, 1, {"reflection": "v2"}, raw="v2 原文")
        other = self.make_plan(plan_date=date(2026, 9, 3), raw="另一份")
        other_content_id = query_scalar(
            self.db,
            "SELECT current_content_id FROM local_daily_plans WHERE id = ?",
            (other["id"],),
        )
        profile_id = query_scalar(self.db, "SELECT id FROM local_profile")
        before_id = query_scalar(
            self.db,
            "SELECT current_content_id FROM local_daily_plans WHERE id = ?",
            (plan_id,),
        )
        conn = sqlite3.connect(self.db)
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO local_daily_plan_restores "
                    "(id, profile_id, request_id, request_fingerprint, daily_plan_id, "
                    "source_content_id, source_content_version, before_content_id, "
                    "before_content_version, result_content_id, result_content_version, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, 1, ?, 2, ?, 2, ?)",
                    (
                        "restore-cross-plan",
                        profile_id,
                        str(uuid.uuid4()),
                        "a" * 64,
                        plan_id,
                        other_content_id,
                        before_id,
                        before_id,
                        "2026-10-23 00:00:00",
                    ),
                )
        finally:
            conn.close()

    def test_restore_does_not_increment_ai_counts(self):
        plan_id = self.plan["id"]
        self.save_content(plan_id, 1, {"reflection": "v2"}, raw="v2 原文")
        before = {
            table: query_scalar(self.db, f"SELECT count(*) FROM {table}")
            for table in ("local_ai_tasks", "local_ai_attempts", "local_ai_operations")
        }
        status, preview = self.preview_restore(1, 2)
        self.assertEqual(status, 200, preview)
        status, restored = self.restore(
            preview["preview_token"], 2, request_id=str(uuid.uuid4())
        )
        self.assertEqual(status, 200, restored)
        after = {
            table: query_scalar(self.db, f"SELECT count(*) FROM {table}")
            for table in before
        }
        self.assertEqual(after, before)

    def test_old_term_calendar_change_keeps_existing_history_restorable(self):
        plan_id = self.plan["id"]
        self.save_content(plan_id, 1, {"reflection": "v2"}, raw="v2 原文")
        term_id = query_scalar(
            self.db,
            "SELECT term_id FROM local_daily_plans WHERE id = ?",
            (plan_id,),
        )
        execute_sql(
            self.db,
            "UPDATE local_terms SET end_date = ? WHERE id = ?",
            ("2026-09-01", term_id),
        )
        status, history = self.client.get(f"/api/daily-plans/{plan_id}/history")
        self.assertEqual(status, 200, history)
        self.assertEqual(history["current_content_version"], 2)
        status, preview = self.preview_restore(1, 2)
        self.assertEqual(status, 200, preview)
        status, restored = self.restore(
            preview["preview_token"], 2, request_id=str(uuid.uuid4())
        )
        self.assertEqual(status, 200, restored)
        self.assertEqual(restored["content_version"], 3)

    def test_history_route_strict_body_session_and_origin(self):
        plan_id = self.plan["id"]
        path = f"/api/daily-plans/{plan_id}/history/preview-restore"
        body = {"source_content_version": 1, "expected_content_version": 1}
        status, bad_field = self.client.post(
            path, {**body, "unexpected": True}
        )
        self.assertEqual(status, 422, bad_field)
        status, no_session = self.client.post(path, body, token=None)
        self.assertEqual(status, 401, no_session)
        status, bad_origin = self.client.post(
            path, body, origin="http://evil.example"
        )
        self.assertEqual(status, 403, bad_origin)
        status, bad_host = self.client.post(path, body, host="evil.example")
        self.assertIn(status, (400, 403, 421), bad_host)

    def test_restore_invalidates_old_adoption_preview_but_allows_new(self):
        plan_id = self.plan["id"]
        v1 = self.plan_content(plan_id)
        self.save_content(plan_id, 1, v1["adopted_content"], raw=v1["raw_lesson_plan"])
        split_id = self.generate(plan_id, "daily_lesson_split", SPLIT_CANDIDATE)
        status, adoption_preview = self.preview_http(
            split_id, ["group_activity"], SPLIT_CANDIDATE
        )
        self.assertEqual(status, 200, adoption_preview)
        status, restore_preview = self.preview_restore(1, 2)
        self.assertEqual(status, 200, restore_preview)
        status, restored = self.restore(
            restore_preview["preview_token"], 2, request_id=str(uuid.uuid4())
        )
        self.assertEqual(status, 200, restored)
        status, stale = self.adopt_http(
            split_id,
            adoption_preview["preview_token"],
            request_id=str(uuid.uuid4()),
        )
        self.assertEqual(status, 409, stale)
        status, fresh = self.preview_http(
            split_id, ["group_activity"], SPLIT_CANDIDATE
        )
        self.assertEqual(status, 200, fresh)

    def test_empty_and_long_newline_content_restore_exact(self):
        plan_id = self.plan["id"]
        long_process = "1. " + "长" * 5000 + "\n2. 第二行"
        v2_content = {
            "group_activity": {
                "theme": "",
                "objectives": "",
                "preparation": "",
                "key_points": "",
                "difficult_points": "",
                "process": long_process,
            },
            "reflection": "",
        }
        self.save_content(plan_id, 1, v2_content, raw="")
        self.save_content(plan_id, 2, {"reflection": "v3"}, raw="v3")
        status, preview = self.preview_restore(2, 3)
        self.assertEqual(status, 200, preview)
        status, restored = self.restore(
            preview["preview_token"], 3, request_id=str(uuid.uuid4())
        )
        self.assertEqual(status, 200, restored)
        content = self.plan_content(plan_id)
        self.assertEqual(content["adopted_content"], v2_content)
        self.assertEqual(content["raw_lesson_plan"], "")

    def test_all_three_composite_fks_reject_cross_plan_content(self):
        plan_id = self.plan["id"]
        self.save_content(plan_id, 1, {"reflection": "v2"}, raw="v2 原文")
        other = self.make_plan(plan_date=date(2026, 9, 3), raw="另一份")
        profile_id = query_scalar(self.db, "SELECT id FROM local_profile")
        a_id = query_scalar(
            self.db, "SELECT current_content_id FROM local_daily_plans WHERE id = ?", (plan_id,)
        )
        b_id = query_scalar(
            self.db, "SELECT current_content_id FROM local_daily_plans WHERE id = ?", (other["id"],)
        )
        cases = [
            ("source", b_id, 1, a_id, 2, a_id, 2),
            ("before", a_id, 2, b_id, 1, a_id, 2),
            ("result", a_id, 2, a_id, 2, b_id, 1),
        ]
        for name, source_id, source_v, before_id, before_v, result_id, result_v in cases:
            conn = sqlite3.connect(self.db)
            try:
                conn.execute("PRAGMA foreign_keys=ON")
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(
                        "INSERT INTO local_daily_plan_restores "
                        "(id, profile_id, request_id, request_fingerprint, daily_plan_id, "
                        "source_content_id, source_content_version, before_content_id, "
                        "before_content_version, result_content_id, result_content_version, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            f"restore-cross-{name}",
                            profile_id,
                            str(uuid.uuid4()),
                            "b" * 64,
                            plan_id,
                            source_id,
                            source_v,
                            before_id,
                            before_v,
                            result_id,
                            result_v,
                            "2026-10-23 00:00:00",
                        ),
                    )
            finally:
                conn.close()

    def test_orphan_future_content_rejected_everywhere(self):
        plan_id = self.plan["id"]
        self.save_content(plan_id, 1, {"reflection": "v2"}, raw="v2 原文")
        status, preview = self.preview_restore(1, 2)
        self.assertEqual(status, 200, preview)
        profile_id = query_scalar(self.db, "SELECT id FROM local_profile")
        execute_sql(
            self.db,
            "INSERT INTO local_daily_plan_contents "
            "(id, daily_plan_id, version, raw_lesson_plan, split_baseline, "
            "adopted_content, editor_id, created_at) "
            "VALUES (?, ?, 5, ?, NULL, '{}', ?, ?)",
            (
                "orphan-future-content-0000000000",
                plan_id,
                "孤立未来内容",
                profile_id,
                "2026-10-23 00:00:00",
            ),
        )
        before = self._db_snapshot()
        status, listing = self.client.get(f"/api/daily-plans/{plan_id}/history")
        self.assertEqual(status, 503, listing)
        self.assertEqual(listing["error"]["code"], "LOCAL_STORAGE_ERROR")
        status, detail = self.history(1)
        self.assertEqual(status, 503, detail)
        status, future_preview = self.preview_restore(5, 2)
        self.assertEqual(status, 503, future_preview)
        self.assertEqual(future_preview["error"]["code"], "LOCAL_STORAGE_ERROR")
        status, restore = self.restore(
            preview["preview_token"], 2, request_id=str(uuid.uuid4())
        )
        self.assertEqual(status, 503, restore)
        self.assertEqual(restore["error"]["code"], "LOCAL_STORAGE_ERROR")
        self.assertEqual(self._db_snapshot(), before)

    def test_cold_restart_reads_receipt_and_restored_content(self):
        plan_id = self.plan["id"]
        self.save_content(plan_id, 1, {"reflection": "v2"}, raw="v2 原文")
        status, preview = self.preview_restore(1, 2)
        self.assertEqual(status, 200, preview)
        request_id = str(uuid.uuid4())
        status, restored = self.restore(
            preview["preview_token"], 2, request_id=request_id
        )
        self.assertEqual(status, 200, restored)
        expected_content = self.plan_content(plan_id)

        daily_plan_history_service.reset_tokens()
        self.server.stop()
        try:
            self.session.close()
        except Exception:  # noqa: BLE001
            pass
        self.runtime.dispose()
        self.runtime = self.make_runtime(self.data_dir)
        self.session = self.runtime.session()
        self.start_api()

        status, current = self.client.get(f"/api/daily-plans/{plan_id}")
        self.assertEqual(status, 200, current)
        self.assertEqual(current["current_content_version"], 3)
        self.assertEqual(current["content"]["version"], expected_content["version"])
        self.assertEqual(
            current["content"]["raw_lesson_plan"],
            expected_content["raw_lesson_plan"],
        )
        self.assertEqual(
            current["content"]["adopted_content"],
            expected_content["adopted_content"],
        )
        status, receipt = self.client.get(
            f"/api/daily-plans/{plan_id}/history/restore-operations/{request_id}"
        )
        self.assertEqual(status, 200, receipt)
        self.assertEqual(receipt, restored)

    def test_0005_upgrade_preserves_existing_content_and_provenance(self):
        plan_id = self.plan["id"]
        split_id = self.generate(plan_id, "daily_lesson_split", SPLIT_CANDIDATE)
        status, preview = self.preview_http(
            split_id, ["group_activity"], SPLIT_CANDIDATE
        )
        self.assertEqual(status, 200, preview)
        status, adopted = self.adopt_http(
            split_id, preview["preview_token"], request_id=str(uuid.uuid4())
        )
        self.assertEqual(status, 200, adopted)
        self.save_content(
            plan_id,
            2,
            self.plan_content(plan_id)["adopted_content"],
            raw="迁移前第三版",
        )

        counts_before = {
            table: query_scalar(self.db, f"SELECT count(*) FROM {table}")
            for table in (
                "local_daily_plan_contents",
                "local_daily_plan_ai_provenance",
                "local_ai_operations",
                "local_ai_candidates",
            )
        }
        baseline_row = query_scalar(
            self.db,
            "SELECT baseline_candidate_id FROM local_daily_plan_ai_provenance "
            "WHERE content_id = (SELECT current_content_id FROM local_daily_plans WHERE id = ?)",
            (plan_id,),
        )
        self.assertEqual(baseline_row, split_id)
        self.assertGreater(counts_before["local_ai_operations"], 0)
        row_tables = (
            "local_daily_plan_contents",
            "local_daily_plan_ai_provenance",
            "local_ai_tasks",
            "local_ai_executions",
            "local_ai_attempts",
            "local_ai_candidates",
            "local_ai_operations",
        )
        rows_before = {
            table: query_rows(self.db, f"SELECT * FROM {table} ORDER BY rowid")
            for table in row_tables
        }

        old_db = self.tmp_root / "migration-old.db"
        source = sqlite3.connect(self.runtime.db_path)
        target = sqlite3.connect(old_db)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()

        conn = sqlite3.connect(old_db)
        try:
            conn.execute("DROP TABLE local_daily_plan_restores")
            conn.execute(
                "UPDATE local_alembic_version SET version_num = ?",
                ("20261017_0004_local",),
            )
            conn.commit()
        finally:
            conn.close()
        command.upgrade(alembic_config(old_db), "head")

        tables = {
            row["name"]
            for row in query_rows(
                old_db, "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        self.assertIn("local_daily_plan_restores", tables)
        counts_after = {
            table: query_scalar(old_db, f"SELECT count(*) FROM {table}")
            for table in counts_before
        }
        self.assertEqual(counts_after, counts_before)
        rows_after = {
            table: query_rows(old_db, f"SELECT * FROM {table} ORDER BY rowid")
            for table in row_tables
        }
        self.assertEqual(rows_after, rows_before)
        self.assertEqual(
            query_scalar(
                old_db,
                "SELECT baseline_candidate_id FROM local_daily_plan_ai_provenance "
                "WHERE content_id = (SELECT current_content_id FROM local_daily_plans WHERE id = ?)",
                (plan_id,),
            ),
            split_id,
        )
        self.assertEqual(
            query_scalar(old_db, "SELECT count(*) FROM local_daily_plan_restores"),
            0,
        )
        self.assertEqual(
            query_rows(old_db, "PRAGMA foreign_key_check"),
            [],
        )

if __name__ == "__main__":
    unittest.main()
