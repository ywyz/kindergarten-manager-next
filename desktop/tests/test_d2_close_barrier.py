"""D2 close-time AI task barrier: the real ``d1_main`` host wiring.

Engineering spec §4.3 / product spec Q6. These tests drive the *actual*
``_install_close_handlers`` wiring (CloseCoordinator ← executor freeze /
``active_snapshot`` / ``stop_and_drain``) with a stub executor and a stubbed
plan-task snapshot, so the freeze/drain/refuse paths are exercisable without a
GUI or a real database. The real Windows source window interleaving stays a
separate manual/verification phase.
"""

import threading

import pytest

import d1_host_api


class EventList(list):
    """A list that lets tests wait deterministically for an append."""

    def __init__(self):
        super().__init__()
        self._condition = threading.Condition()

    def append(self, item):
        with self._condition:
            super().append(item)
            self._condition.notify_all()

    def wait_for_count(self, count=1, timeout=5.0):
        with self._condition:
            return self._condition.wait_for(
                lambda: len(self) >= count, timeout
            )


class FakeExecutor:
    def __init__(self):
        self.frozen = 0
        self.unfrozen = 0
        self.notified = 0
        self.drain_calls = 0
        self.drain_result = True

    def freeze(self):
        self.frozen += 1

    def unfreeze(self):
        self.unfrozen += 1

    def notify(self):
        self.notified += 1

    def active_snapshot(self):
        return {
            "attempt_in_flight": False,
            "unconfirmed": False,
            "pending_persist": False,
        }

    def stop_and_drain(self, deadline=5.0):
        self.drain_calls += 1
        return self.drain_result


class FakeSession:
    def close(self):
        return None


class FakeRuntime:
    def __init__(self, executor):
        self.ai_executor = executor

    def session(self):
        return FakeSession()


class Signal:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def __call__(self):
        result = None
        for handler in self.handlers:
            result = handler()
        return result


class FakeEvents:
    def __init__(self):
        self.closing = Signal()

    def fire(self):
        return self.closing()


class FakeWindow:
    def __init__(self):
        self.events = FakeEvents()
        self.destroyed = 0

    def destroy(self):
        self.destroyed += 1


def _install(monkeypatch, live_counts):
    from app.local import ai_task_service
    import d1_main

    sequence = list(live_counts)

    def snapshot(_session):
        value = sequence[0] if len(sequence) == 1 else sequence.pop(0)
        return {"live": value, "in_flight": 0}

    monkeypatch.setattr(ai_task_service, "active_task_snapshot", snapshot)

    executor = FakeExecutor()
    runtime = FakeRuntime(executor)
    window = FakeWindow()
    host_api = d1_host_api.D1HostApi(launch_token="synthetic")
    notifications = EventList()
    aborts = EventList()
    host_api._notify_request_close = lambda rid, generation=None: notifications.append(
        (rid, generation)
    )
    host_api._notify_close_aborted = lambda rid, reason: aborts.append((rid, reason))
    d1_main._install_close_handlers(window, host_api, runtime)
    host_api.page_ready({"bridge_protocol": 1})
    return window, host_api, executor, notifications, aborts


def _begin(window, notifications, count=1):
    assert window.events.fire() is False
    assert notifications.wait_for_count(count)
    return notifications[count - 1][0]


def test_close_intent_freezes_the_executor_and_no_tasks_allows(monkeypatch):
    window, host_api, executor, notifications, _aborts = _install(monkeypatch, [0])
    request = _begin(window, notifications)
    assert executor.frozen == 1
    assert host_api.complete_close({"close_request_id": request, "allow": True}) == {
        "accepted": True,
        "state": "closing",
    }
    assert executor.drain_calls == 0
    assert window.destroyed == 1


def test_live_tasks_require_task_choice_through_the_real_host(monkeypatch):
    window, host_api, executor, notifications, aborts = _install(monkeypatch, [1])
    request = _begin(window, notifications)
    # No task_choice: the host refuses and releases the freeze.
    assert host_api.complete_close({"close_request_id": request, "allow": True}) == {
        "accepted": False,
        "state": "canceled",
    }
    assert window.destroyed == 0
    assert aborts.wait_for_count(1)
    assert aborts == [(request, "ai_tasks_active")]
    assert executor.unfrozen == 1
    # keep_waiting cancels the close.
    request = _begin(window, notifications, count=2)
    assert host_api.complete_close(
        {"close_request_id": request, "allow": True, "task_choice": "keep_waiting"}
    ) == {"accepted": False, "state": "canceled"}
    assert aborts.wait_for_count(2)
    assert aborts[-1] == (request, "ai_keep_waiting")
    assert executor.drain_calls == 0


def test_stop_and_exit_drains_through_the_real_host(monkeypatch):
    window, host_api, executor, notifications, aborts = _install(monkeypatch, [1, 0])
    request = _begin(window, notifications)
    assert host_api.complete_close(
        {"close_request_id": request, "allow": True, "task_choice": "stop_and_exit"}
    ) == {"accepted": True, "state": "closing"}
    assert executor.drain_calls == 1
    assert window.destroyed == 1
    assert aborts == []
