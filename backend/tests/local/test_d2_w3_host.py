"""D2 W3 host close coordination: freeze, task barrier and cancel branches.

Imports the real ``desktop/d1_host_api`` close state machine (no window) and a
real ``AiExecutor`` with real spawned workers, so the freeze/unfreeze and the
stop-and-exit drain are exercised end to end.
"""

from __future__ import annotations

import sys
import time
import unittest
import uuid
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
DESKTOP = BACKEND.parent / "desktop"
for candidate in (str(BACKEND), str(DESKTOP)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import d1_host_api  # noqa: E402
from app.local import ai_task_service  # noqa: E402
from app.local.ai_executor import AiExecutor  # noqa: E402
from app.local.base import utc_now  # noqa: E402

from tests.local.support import LocalTestCase, query_scalar  # noqa: E402


class CloseCoordinatorTests(unittest.TestCase):
    """Pure state-machine branches (no window, no DB)."""

    def _coordinator(self, **kwargs):
        destroyed = {"count": 0}
        aborted: list[tuple[str, str]] = []
        coordinator = d1_host_api.CloseCoordinator(
            notify_page=lambda *_a: None,
            destroy_window=lambda: destroyed.__setitem__("count", destroyed["count"] + 1),
            notify_aborted=lambda request_id, reason: aborted.append((request_id, reason)),
            **kwargs,
        )
        return coordinator, destroyed, aborted

    def _open_request(self, coordinator):
        self.assertFalse(coordinator.handle_closing())
        return coordinator._current_id

    def test_close_intent_freezes_and_deny_releases(self):
        intents = {"froze": 0, "released": 0}
        coordinator, _destroyed, _aborted = self._coordinator(
            on_close_intent=lambda: intents.__setitem__("froze", intents["froze"] + 1),
            on_close_canceled=lambda: intents.__setitem__("released", intents["released"] + 1),
        )
        request_id = self._open_request(coordinator)
        self.assertEqual(intents["froze"], 1)
        result = coordinator.complete(request_id, False)
        self.assertTrue(result["accepted"])
        self.assertEqual(intents["released"], 1)

    def test_busy_refusal_releases_freeze(self):
        released = {"n": 0}
        coordinator, _destroyed, aborted = self._coordinator(
            busy_probe=lambda: True,
            on_close_canceled=lambda: released.__setitem__("n", released["n"] + 1),
        )
        request_id = self._open_request(coordinator)
        result = coordinator.complete(request_id, True)
        self.assertFalse(result["accepted"])
        self.assertEqual(released["n"], 1)
        self.assertEqual(aborted[-1][1], "save_in_flight")

    def test_destroy_failure_releases_freeze(self):
        released = {"n": 0}

        def boom():
            raise RuntimeError("destroy failed")

        coordinator = d1_host_api.CloseCoordinator(
            notify_page=lambda *_a: None,
            destroy_window=boom,
            notify_aborted=lambda *_a: None,
            on_close_canceled=lambda: released.__setitem__("n", released["n"] + 1),
        )
        request_id = self._open_request(coordinator)
        result = coordinator.complete(request_id, True)
        self.assertFalse(result["accepted"])
        self.assertEqual(released["n"], 1)

    def test_existing_task_requires_choice_and_keep_waiting_releases(self):
        released = {"n": 0}
        coordinator, destroyed, aborted = self._coordinator(
            task_snapshot=lambda: {"live": 1, "in_flight": False},
            on_close_canceled=lambda: released.__setitem__("n", released["n"] + 1),
        )
        request_id = self._open_request(coordinator)
        # An old page with no task confirmation must be refused, not silently
        # cancel the in-flight task.
        refused = coordinator.complete(request_id, True)
        self.assertFalse(refused["accepted"])
        self.assertEqual(destroyed["count"], 0)
        self.assertEqual(aborted[-1][1], "ai_tasks_active")
        self.assertEqual(released["n"], 1)
        # A fresh close with "keep waiting" also stays open.
        request_id = self._open_request(coordinator)
        kept = coordinator.complete(request_id, True, "keep_waiting")
        self.assertFalse(kept["accepted"])
        self.assertEqual(aborted[-1][1], "ai_keep_waiting")

    def test_stop_and_exit_requires_drain_confirmation(self):
        coordinator, destroyed, aborted = self._coordinator(
            task_snapshot=lambda: {"live": 1, "in_flight": True},
            drain_tasks=lambda: False,
        )
        request_id = self._open_request(coordinator)
        result = coordinator.complete(request_id, True, "stop_and_exit")
        self.assertFalse(result["accepted"])
        self.assertEqual(destroyed["count"], 0)
        self.assertEqual(aborted[-1][1], "ai_drain_failed")

    def test_stale_cancel_does_not_release_newer_freeze(self):
        released = {"n": 0}
        coordinator, _destroyed, _aborted = self._coordinator(
            on_close_canceled=lambda: released.__setitem__("n", released["n"] + 1),
        )
        first = self._open_request(coordinator)
        # A newer request supersedes the first (deny/cancel the first).
        coordinator.complete(first, False)
        second = self._open_request(coordinator)
        self.assertNotEqual(first, second)
        # A stale timeout callback for the old id must not unfreeze.
        coordinator._on_timeout(first)
        self.assertEqual(released["n"], 1)  # only the explicit deny

    def test_threaded_barrier_interleave_keeps_new_freeze(self):
        """A real interleave: denying an old request must never unfreeze a new one."""
        import threading

        violations = 0
        for _ in range(200):
            state = {"frozen": 0}
            observed: list[str | None] = []
            coordinator_holder: dict = {}
            barrier = threading.Barrier(2, timeout=5)

            def on_canceled() -> None:
                # Read the current id at the moment of the unfreeze (racy by
                # design): with the fix this always runs under the lock, so the
                # id still belongs to the request being denied.
                observed.append(coordinator_holder["coordinator"]._current_id)
                state["frozen"] -= 1

            coordinator, _destroyed, _aborted = self._coordinator(
                on_close_intent=lambda: state.__setitem__("frozen", state["frozen"] + 1),
                on_close_canceled=on_canceled,
            )
            coordinator_holder["coordinator"] = coordinator
            first = self._open_request(coordinator)

            def deny_old() -> None:
                barrier.wait()
                coordinator.complete(first, False)

            def begin_new() -> None:
                barrier.wait()
                # Only begins when the deny already set CANCELED.
                coordinator.handle_closing()

            threads = [threading.Thread(target=deny_old), threading.Thread(target=begin_new)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)

            # The unfreeze was always for the denied request, never for a
            # request that became current in between.
            if any(observed_id != first for observed_id in observed):
                violations += 1
            live = coordinator._state in (coordinator.PENDING, coordinator.CLOSING)
            if live and state["frozen"] < 1:
                violations += 1
        self.assertEqual(violations, 0)

    def test_timeout_releases_freeze(self):
        released = {"n": 0}
        coordinator, _destroyed, aborted = self._coordinator(
            on_close_canceled=lambda: released.__setitem__("n", released["n"] + 1),
        )
        request_id = self._open_request(coordinator)
        coordinator._on_timeout(request_id)
        self.assertEqual(released["n"], 1)
        self.assertEqual(aborted[-1][1], "timeout")


class ExecutorCloseBarrierTests(LocalTestCase):
    """Real executor + spawned worker under the stop-and-exit drain."""

    def setUp(self) -> None:
        super().setUp()
        self.runtime = self.make_runtime()
        self.runtime.launch_id = str(uuid.uuid4())
        self.db = self.runtime.db_path
        self.session = self.runtime.session()
        self.addCleanup(self.session.close)
        from app.local import profile_service
        from app.local.normalize import normalize_initialization

        profile_service.initialize(
            self.session,
            normalize_initialization(
                request_id=str(uuid.uuid4()),
                display_name="王老师",
                class_name="中一班",
                grade="middle",
                term_name="2026 年秋季学期",
                start_date="2026-09-01",
                end_date="2026-12-31",
                school_name="示范幼儿园",
            ),
        )
        self.session.commit()

    def _configure(self):
        from app.local import ai_config_service

        ai_config_service.patch_config(
            self.session,
            expected_ai_config_version=0,
            base_url="https://api.example.com/v1",
            model="w3fake|ready_delay:2|ready_then_result:0",
            secret="s3cret",
            secret_provided=True,
            request_id=str(uuid.uuid4()),
            credential_root=self.runtime.credential_root,
        )

    def _plan(self):
        from app.local import daily_plan_service

        payload, _ = daily_plan_service.create_or_open(
            self.session,
            plan_date=date(2026, 9, 2),
            raw_lesson_plan="原始教案正文",
            adopted_content={"group_activity": {"process": "一、导入"}, "reflection": "反思"},
        )
        return payload

    def test_revoke_db_failure_keeps_worker_and_no_send(self):
        from tests.local.w3_workers import fake_worker_entry

        self._configure()
        executor = AiExecutor(self.runtime, worker_target=fake_worker_entry)
        executor.start()
        try:
            plan = self._plan()
            task = ai_task_service.create_task(
                self.session,
                plan_id=plan["id"],
                task_type="daily_lesson_split",
                expected_content_version=1,
                target_grade="middle",
                request_id=str(uuid.uuid4()),
                runtime=self.runtime,
            )[0]
            executor.notify()
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline and not executor.active_snapshot()["attempt_in_flight"]:
                time.sleep(0.02)
            self.assertTrue(executor.active_snapshot()["attempt_in_flight"])
            generation = query_scalar(
                self.db, "SELECT generation FROM local_ai_tasks WHERE id = ?", (task["id"],)
            )
            # Hold a write lock so the revoke transaction cannot commit.
            import sqlite3

            blocker = sqlite3.connect(str(self.db), timeout=30)
            blocker.execute("PRAGMA busy_timeout=1000")
            blocker.execute("BEGIN IMMEDIATE")
            try:
                confirmed = executor.stop_and_drain(deadline=5.0)
            finally:
                blocker.rollback()
                blocker.close()
            self.assertFalse(confirmed)
            # The worker is still alive and nothing was killed or sent.
            self.assertTrue(executor.active_snapshot()["attempt_in_flight"])
            self.assertEqual(
                query_scalar(
                    self.db,
                    "SELECT count(*) FROM local_ai_candidates WHERE task_id = ?",
                    (task["id"],),
                ),
                0,
            )
            # Cancelling the close lets the same generation continue.
            executor.unfreeze()
            executor.notify()
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                status = query_scalar(
                    self.db, "SELECT status FROM local_ai_tasks WHERE id = ?", (task["id"],)
                )
                if status in ("succeeded", "failed", "outcome_unknown"):
                    break
                time.sleep(0.05)
            self.assertEqual(
                query_scalar(self.db, "SELECT status FROM local_ai_tasks WHERE id = ?", (task["id"],)),
                "succeeded",
            )
            self.assertEqual(
                query_scalar(self.db, "SELECT generation FROM local_ai_tasks WHERE id = ?", (task["id"],)),
                generation,
            )
            self.assertEqual(
                query_scalar(
                    self.db,
                    "SELECT count(*) FROM local_ai_candidates WHERE task_id = ?",
                    (task["id"],),
                ),
                1,
            )
        finally:
            executor.dispose()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
