"""Real-file concurrency: two connections, two processes, busy, snapshots.

Same-day creation must yield exactly one effective row even when two
connections or two processes race; two saves with the same expected
version admit exactly one winner; a held write lock times out with
``LOCAL_DATABASE_BUSY`` and succeeds after release; and one explicit read
transaction sees one consistent snapshot across multiple SELECTs.
"""

from __future__ import annotations

import threading
import time
import unittest
from datetime import date
from pathlib import Path

from app.local import daily_plan_service, profile_service
from app.local.errors import LocalDatabaseBusy, LocalError
from app.local.normalize import normalize_initialization
from app.local.runtime import LocalRuntime
from app.local.tx import storage_errors
from tests.local.support import (
    LocalTestCase,
    StaticCalendarProvider,
    calendar_provider,
    initialize_body,
    query_rows,
    query_scalar,
    wait_for_file,
)

PLAN_DATE = date(2026, 9, 1)


class ConcurrencyTests(LocalTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.provider = StaticCalendarProvider()
        self.enterContext(calendar_provider(self.provider))
        self.runtime = self.make_runtime()
        session = self.runtime.session()
        try:
            payload, created = profile_service.initialize(
                session, normalize_initialization(**initialize_body())
            )
        finally:
            session.close()
        self.assertTrue(created)
        self.db = self.runtime.db_path

    def _create(self, runtime: LocalRuntime, raw=None, plan_date=PLAN_DATE):
        session = runtime.session()
        try:
            kwargs = {}
            if raw is not None:
                kwargs["raw_lesson_plan"] = raw
            payload, created = daily_plan_service.create_or_open(
                session, plan_date=plan_date, **kwargs
            )
            return payload, created
        finally:
            session.close()

    def _save(self, runtime: LocalRuntime, plan_id: str, raw: str):
        session = runtime.session()
        try:
            return daily_plan_service.save(
                session,
                plan_id=plan_id,
                expected_content_version=1,
                raw_lesson_plan=raw,
            )
        finally:
            session.close()

    # -- two connections --------------------------------------------------
    def test_two_connections_create_one_effective_plan(self):
        # A single real owner runtime holds the exclusive root lock; each
        # thread uses an independent session (its own DBAPI connection) from
        # that one runtime, so the race is still two real connections.
        results: dict[str, dict] = {}
        barrier = threading.Barrier(2)

        def run(name: str) -> None:
            try:
                barrier.wait(timeout=30)
                payload, created = self._create(self.runtime)
                results[name] = {"created": created, "id": payload["id"]}
            except LocalError as exc:  # pragma: no cover - failure evidence
                results[name] = {"error": exc.code}

        threads = [
            threading.Thread(target=run, args=("a",)),
            threading.Thread(target=run, args=("b",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        self.assertEqual(len(results), 2, results)
        self.assertFalse([r for r in results.values() if "error" in r], results)
        self.assertEqual(sum(1 for r in results.values() if r["created"]), 1)
        self.assertEqual(len({r["id"] for r in results.values()}), 1)
        self.assertEqual(
            query_scalar(self.db, "SELECT count(*) AS n FROM local_daily_plans"),
            1,
        )
        self.assertEqual(
            query_scalar(
                self.db,
                "SELECT count(*) AS n FROM local_operation_records "
                "WHERE action = 'create_daily_plan'",
            ),
            1,
        )

    # -- two processes ----------------------------------------------------
    def test_two_processes_create_one_effective_plan(self):
        spec_a = self.worker_spec("create_plan")
        spec_a["plan_date"] = PLAN_DATE.isoformat()
        spec_b = self.worker_spec("create_plan")
        spec_b["plan_date"] = PLAN_DATE.isoformat()
        proc_a = self.spawn_worker(spec_a)
        proc_b = self.spawn_worker(spec_b)
        result_a = self.collect_worker(proc_a, spec_a)
        result_b = self.collect_worker(proc_b, spec_b)

        results = [result_a, result_b]
        self.assertFalse([r for r in results if "error" in r], results)
        self.assertEqual(sum(1 for r in results if r["created"]), 1)
        self.assertEqual(len({r["payload"]["id"] for r in results}), 1)
        self.assertEqual(
            query_scalar(self.db, "SELECT count(*) AS n FROM local_daily_plans"),
            1,
        )
        self.assertEqual(
            query_scalar(
                self.db,
                "SELECT count(*) AS n FROM local_daily_plan_contents",
            ),
            1,
        )

    def test_two_processes_same_expected_version_one_winner(self):
        payload, _ = self._create(self.runtime, raw="v1")
        plan_id = payload["id"]

        spec_a = self.worker_spec("save_plan")
        spec_a.update({"plan_id": plan_id, "expected": 1, "raw": "A"})
        spec_b = self.worker_spec("save_plan")
        spec_b.update({"plan_id": plan_id, "expected": 1, "raw": "B"})
        proc_a = self.spawn_worker(spec_a)
        proc_b = self.spawn_worker(spec_b)
        result_a = self.collect_worker(proc_a, spec_a)
        result_b = self.collect_worker(proc_b, spec_b)

        winners = [r for r in (result_a, result_b) if "payload" in r]
        losers = [
            r
            for r in (result_a, result_b)
            if r.get("error", {}).get("code") == "VERSION_CONFLICT"
        ]
        self.assertEqual(len(winners), 1, (result_a, result_b))
        self.assertEqual(len(losers), 1, (result_a, result_b))
        self.assertEqual(winners[0]["payload"]["current_content_version"], 2)
        self.assertEqual(
            query_scalar(
                self.db, "SELECT count(*) AS n FROM local_daily_plan_contents"
            ),
            2,
        )
        self.assertEqual(
            query_scalar(
                self.db,
                "SELECT count(*) AS n FROM local_operation_records "
                "WHERE action = 'update_daily_plan'",
            ),
            1,
        )
        self.assertEqual(
            query_scalar(
                self.db,
                "SELECT current_content_version FROM local_daily_plans WHERE id = ?",
                (plan_id,),
            ),
            2,
        )
        raws = [
            row["raw_lesson_plan"]
            for row in query_rows(
                self.db,
                "SELECT raw_lesson_plan FROM local_daily_plan_contents "
                "WHERE daily_plan_id = ? ORDER BY version",
                (plan_id,),
            )
        ]
        self.assertEqual(raws[0], "v1")
        self.assertIn(raws[1], {"A", "B"})

    # -- busy + retry -----------------------------------------------------
    def _hold_write_lock_process(self, hold_seconds: float = 15.0):
        spec = self.worker_spec("hold_write_lock")
        spec["signal_file"] = str(self.tmp_root / "locked.flag")
        spec["release_file"] = str(self.tmp_root / "release.flag")
        spec["hold_seconds"] = hold_seconds
        process = self.spawn_worker(spec)
        self.addCleanup(self._release_lock_process, process, spec)
        wait_for_file(spec["signal_file"], timeout=60)
        return process, spec

    def _release_lock_process(self, process, spec) -> None:
        if process.poll() is None:
            Path(spec["release_file"]).write_text("go", encoding="utf-8")
            try:
                self.collect_worker(process, spec, timeout=60)
            except AssertionError:
                process.kill()
                process.wait(timeout=30)

    def test_write_lock_busy_then_release_allows_retry(self):
        process, spec = self._hold_write_lock_process()
        started = time.monotonic()
        session = self.runtime.session()
        try:
            with self.assertRaises(LocalDatabaseBusy):
                with storage_errors():
                    daily_plan_service.create_or_open(
                        session, plan_date=PLAN_DATE
                    )
        finally:
            session.close()
        elapsed = time.monotonic() - started
        self.assertGreaterEqual(elapsed, 4.0, elapsed)
        self.assertLess(elapsed, 30.0, elapsed)

        Path(spec["release_file"]).write_text("go", encoding="utf-8")
        released = self.collect_worker(process, spec, timeout=60)
        self.assertEqual(released, {"released": True})

        # After release the same write succeeds normally.
        payload, created = self._create(self.runtime)
        self.assertTrue(created)
        self.assertEqual(
            query_scalar(self.db, "SELECT count(*) AS n FROM local_daily_plans"),
            1,
        )

    def test_locked_write_rejects_invalid_structure_without_busy_wait(self):
        payload, _ = self._create(self.runtime, raw="v1")
        plan_id = payload["id"]
        server = self.start_server(self.runtime)
        client = server.client()

        process, spec = self._hold_write_lock_process()
        started = time.monotonic()
        status, result = client.patch(
            f"/api/daily-plans/{plan_id}",
            {"expected_content_version": 1, "adopted_content": {"unsupported_field": "x"}},
        )
        elapsed = time.monotonic() - started
        # Lock-free structure validation answers 422 immediately; it never
        # waits for (or takes) the write lock.
        self.assertEqual(status, 422, result)
        self.assertEqual(result["error"]["code"], "VALIDATION_ERROR")
        self.assertLess(elapsed, 2.0, elapsed)

        # The failed request changed nothing.
        self.assertEqual(
            query_scalar(
                self.db, "SELECT count(*) AS n FROM local_daily_plan_contents"
            ),
            1,
        )
        self.assertEqual(
            query_scalar(
                self.db, "SELECT count(*) AS n FROM local_operation_records "
                "WHERE action = 'update_daily_plan'",
            ),
            0,
        )

        Path(spec["release_file"]).write_text("go", encoding="utf-8")
        released = self.collect_worker(process, spec, timeout=60)
        self.assertEqual(released, {"released": True})

        # A valid save still succeeds after release; the lock protection is
        # unchanged (the busy path is covered by the test above).
        status, saved = client.patch(
            f"/api/daily-plans/{plan_id}",
            {"expected_content_version": 1, "raw_lesson_plan": "v2"},
        )
        self.assertEqual(status, 200, saved)
        self.assertEqual(saved["current_content_version"], 2)

    # -- consistent production read snapshots -----------------------------
    def test_list_read_uses_one_snapshot_under_concurrent_commit(self):
        first, _ = self._create(self.runtime, raw="v1")

        spec = self.worker_spec("read_list_snapshot")
        spec.update(
            {
                "from_date": PLAN_DATE.isoformat(),
                "to_date": "2026-09-30",
                "first_file": str(self.tmp_root / "list-first.json"),
                "proceed_file": str(self.tmp_root / "list-go.flag"),
            }
        )
        process = self.spawn_worker(spec)
        try:
            wait_for_file(spec["first_file"], timeout=60)
            # The reader already executed its count(*) inside the explicit
            # read transaction; committing a second plan now must not leak
            # into the items SELECT of the same read.
            self._create(
                self.runtime, plan_date=date(2026, 9, 2), raw="committed-later"
            )
            Path(spec["proceed_file"]).write_text("go", encoding="utf-8")
            result = self.collect_worker(process, spec, timeout=60)
        finally:
            if process.poll() is None:
                Path(spec["proceed_file"]).write_text("go", encoding="utf-8")
                process.kill()
                process.wait(timeout=30)

        payload = result["payload"]
        self.assertEqual(payload["total"], 1, payload)
        self.assertEqual(len(payload["items"]), 1, payload)
        self.assertEqual(payload["items"][0]["id"], first["id"])
        # A fresh read after the reader ended sees the committed plan.
        session = self.runtime.session()
        try:
            fresh = daily_plan_service.list_plans(
                session,
                from_date=PLAN_DATE,
                to_date=date(2026, 9, 30),
                offset=0,
                limit=100,
            )
        finally:
            session.close()
        self.assertEqual(fresh["total"], 2)

    def test_detail_read_stays_internally_consistent_under_concurrent_save(self):
        payload, _ = self._create(self.runtime, raw="v1")
        plan_id = payload["id"]

        spec = self.worker_spec("read_detail_snapshot")
        spec.update(
            {
                "plan_date": PLAN_DATE.isoformat(),
                "first_file": str(self.tmp_root / "detail-first.json"),
                "proceed_file": str(self.tmp_root / "detail-go.flag"),
            }
        )
        process = self.spawn_worker(spec)
        try:
            wait_for_file(spec["first_file"], timeout=60)
            # The header SELECT already ran; commit a new version before the
            # content read completes.
            self._save(self.runtime, plan_id, "v2")
            Path(spec["proceed_file"]).write_text("go", encoding="utf-8")
            result = self.collect_worker(process, spec, timeout=60)
        finally:
            if process.poll() is None:
                Path(spec["proceed_file"]).write_text("go", encoding="utf-8")
                process.kill()
                process.wait(timeout=30)

        detail = result["payload"]
        self.assertEqual(detail["id"], plan_id)
        # One complete version: pointer, version and content agree.
        self.assertEqual(
            detail["current_content_version"], detail["content"]["version"]
        )
        self.assertEqual(detail["current_content_id"], detail["content"]["id"])
        # The header was read before the save committed, so the whole
        # response is the old version, never a header/content mix.
        self.assertEqual(detail["current_content_version"], 1)
        self.assertEqual(detail["content"]["raw_lesson_plan"], "v1")
        # A fresh read after the reader ended sees the committed save.
        session = self.runtime.session()
        try:
            fresh = daily_plan_service.get_by_date(session, plan_date=PLAN_DATE)
        finally:
            session.close()
        self.assertEqual(fresh["current_content_version"], 2)
        self.assertEqual(fresh["content"]["raw_lesson_plan"], "v2")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
