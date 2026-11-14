"""Weekly AI progress identity regression.

The progress endpoint must always project the task's *current* execution and
must never turn a snapshot from a previous execution into this task's live
progress.  The frontend refreshes a lagging task identity once, but the backend
identity remains the source of truth.
"""

from __future__ import annotations

import unittest
from unittest import mock

from app.local import ai_progress, ai_task_service, api


def _task(execution_id: str, status: str = "dispatching", attempt_no: int = 2) -> dict:
    return {
        "status": status,
        "execution": {"id": execution_id, "attempt_no": attempt_no},
    }


def _snapshot(execution_id: str, attempt_no: int = 2) -> dict:
    return {
        "task_id": "t1",
        "execution_id": execution_id,
        "attempt_id": "a1",
        "attempt_no": attempt_no,
        "seq": 3,
        "phase": "thinking",
        "reasoning": "当前执行",
        "truncated": False,
        "content_chars": 0,
        "started_ticks": 1000,
        "last_data_ticks": 1200,
        "ended": False,
        "ended_at_ticks": 0,
        "final_kind": None,
        "final_reason": None,
    }


class WeeklyProgressIdentityTests(unittest.TestCase):
    def test_progress_uses_the_current_task_execution(self) -> None:
        with (
            mock.patch.object(
                ai_task_service, "get_task", return_value=_task("exec-current")
            ),
            mock.patch.object(
                ai_progress,
                "snapshot",
                return_value=_snapshot("exec-current"),
            ) as snapshot,
        ):
            out = api._task_progress(
                None,
                "t1",
                source_kind="weekly_plan",
                weekly_plan_id="p1",
            )
        snapshot.assert_called_once_with("t1", "exec-current")
        self.assertEqual(out["execution_id"], "exec-current")
        self.assertEqual(out["attempt_no"], 2)
        self.assertEqual(out["phase"], "thinking")

    def test_progress_for_an_old_execution_is_never_projected_as_current(self) -> None:
        with (
            mock.patch.object(
                ai_task_service,
                "get_task",
                return_value=_task("exec-new", attempt_no=3),
            ),
            mock.patch.object(
                ai_progress,
                "snapshot",
                return_value=_snapshot("exec-old", attempt_no=2),
            ),
        ):
            out = api._task_progress(
                None,
                "t1",
                source_kind="weekly_plan",
                weekly_plan_id="p1",
            )
        self.assertEqual(out["execution_id"], "exec-new")
        self.assertTrue(out["available"] is False)
        self.assertEqual(out["phase"], "unavailable")

    def test_pending_retry_keeps_the_execution_identity_but_reports_waiting(self) -> None:
        with (
            mock.patch.object(
                ai_task_service,
                "get_task",
                return_value=_task("exec-history", status="pending", attempt_no=2),
            ),
            mock.patch.object(ai_progress, "snapshot") as snapshot,
        ):
            out = api._task_progress(
                None,
                "t1",
                source_kind="weekly_plan",
                weekly_plan_id="p1",
            )
        snapshot.assert_not_called()
        self.assertEqual(out["execution_id"], "exec-history")
        self.assertEqual(out["phase"], "waiting")
        self.assertFalse(out["available"])


if __name__ == "__main__":
    unittest.main()
