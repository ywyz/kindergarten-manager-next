"""G2 close/maintenance integration for a real weekly AI claim."""
from __future__ import annotations

import d1_host_api
from app.local import ai_task_service
from app.local.models import LocalAITask
from app.local.runtime import LocalRuntime
from tests.local.test_weekly_ai_backup import (
    _copy_old_tree, _pending_weekly_claim, create_old_0007_fixture,
)


class _Executor:
    def __init__(self):
        self.frozen = 0
        self.unfrozen = 0
        self.notified = 0

    def freeze(self):
        self.frozen += 1

    def unfreeze(self):
        self.unfrozen += 1

    def notify(self):
        self.notified += 1


def _runtime(tmp_path):
    old = tmp_path / "old"
    create_old_0007_fixture(old / "kindergarten.db", old)
    data = tmp_path / "data"
    _copy_old_tree(old, data)
    runtime = LocalRuntime(data, credential_root=tmp_path / "cred")
    runtime.prepare()
    return runtime
def _coordinator(runtime, executor, destroyed):
    events = []

    def snapshot():
        session = runtime.session()
        try:
            counts = ai_task_service.active_task_snapshot(session)
        finally:
            session.close()
        return {"live": counts["live"], "in_flight": False}

    def drain():
        session = runtime.session()
        try:
            result = ai_task_service.recover_on_start(
                session, now=ai_task_service._now())
            events.append(("drain", result))
        finally:
            session.close()
        return True

    def final(request_id, generation):
        events.append(("final", request_id, generation))

    coordinator = d1_host_api.CloseCoordinator(
        notify_page=lambda rid, generation=None: events.append(("notify", rid)),
        destroy_window=lambda: destroyed.append("destroy"),
        notify_aborted=lambda rid, reason: events.append(("abort", reason)),
        task_snapshot=snapshot,
        on_close_intent=executor.freeze,
        on_close_canceled=lambda: (executor.unfreeze(), executor.notify()),
        on_install_final=final,
        drain_tasks=drain,
    )
    return coordinator, events
def test_real_weekly_claim_stop_and_exit_freezes_drains_and_acks(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        claim, task_id = _pending_weekly_claim(runtime, False)
        executor = _Executor()
        destroyed = []
        coordinator, events = _coordinator(runtime, executor, destroyed)
        coordinator.handle_closing()
        request_id = coordinator._current_id
        result = coordinator.complete(request_id, True, "stop_and_exit")
        assert result == {"accepted": True, "state": "closing"}
        assert destroyed == ["destroy"]
        assert executor.frozen == 1
        assert any(event[0] == "drain" for event in events)
        assert any(event[0] == "final" and event[2] >= 1 for event in events)
        session = runtime.session()
        try:
            task = session.get(LocalAITask, task_id)
            assert task.status in ("paused", "outcome_unknown")
            assert claim.task_id == task_id
        finally:
            session.close()
    finally:
        runtime.dispose()
def test_cancelled_close_does_not_revive_generation_or_old_ack(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        claim, _task_id = _pending_weekly_claim(runtime, False)
        executor = _Executor()
        destroyed = []
        coordinator, _events = _coordinator(runtime, executor, destroyed)
        coordinator.handle_closing()
        old_one = coordinator._current_id
        old_generation = coordinator._current_generation
        assert coordinator.complete(old_one, False)["state"] == "canceled"
        assert executor.frozen == 1 and executor.unfrozen >= 1
        assert coordinator.complete(old_one, True, "stop_and_exit")["accepted"] is False
        coordinator.handle_closing()
        new_id = coordinator._current_id
        assert new_id != old_one
        assert coordinator._current_generation > old_generation
        assert coordinator.complete(old_one, True, "stop_and_exit")["accepted"] is False
        assert coordinator.complete(new_id, True, "stop_and_exit")["accepted"] is True
        assert destroyed == ["destroy"]
        assert claim.task_id
    finally:
        runtime.dispose()