"""D1 close-handshake coordinator: state machine, timeout and revoke rules."""

import threading

import d1_host_api
from d1_host_api import CloseCoordinator


class FakeTimer:
    def __init__(self, seconds, fn):
        self.seconds = seconds
        self.fn = fn
        self.canceled = False
        self.started = False
        self.daemon = False

    def start(self):
        self.started = True

    def cancel(self):
        self.canceled = True


class Harness:
    def __init__(self):
        self.notified = []
        self.notified_generations = []
        self.aborted = []
        self.destroyed = 0
        self.destroy_error = None
        self.timers = []
        self.busy = False

    def make(self, timeout=30.0, busy_probe=None, destroy=None):
        def timer_factory(seconds, fn):
            timer = FakeTimer(seconds, fn)
            self.timers.append(timer)
            return timer

        def default_destroy():
            self.destroyed += 1
            if self.destroy_error is not None:
                raise self.destroy_error

        def notify_page(request_id, generation=None):
            self.notified.append(request_id)
            self.notified_generations.append((request_id, generation))

        self.coordinator = CloseCoordinator(
            notify_page=notify_page,
            destroy_window=destroy or default_destroy,
            notify_aborted=lambda rid, reason: self.aborted.append((rid, reason)),
            timeout=timeout,
            timer_factory=timer_factory,
            busy_probe=busy_probe,
        )
        return self.coordinator

    def wait_notified(self, count=1):
        # The notification is delivered from a thread that re-checks the
        # request state under the coordinator lock; wait for the expected
        # count deterministically instead of assuming an immediate append.
        for _ in range(200):
            if len(self.notified) >= count:
                return
            threading.Event().wait(0.01)
        raise AssertionError(
            f"page was notified {len(self.notified)} time(s), expected {count}"
        )


def test_closing_is_canceled_then_completed():
    harness = Harness()
    coordinator = harness.make()
    # First closing: immediately canceled, page notified with a request id.
    assert coordinator.handle_closing() is False
    assert coordinator.handle_closing() is False  # no duplicate request
    harness.wait_notified()
    assert len(harness.notified) == 1
    request_id = harness.notified[0]
    assert coordinator.state(request_id) == "pending"
    assert harness.timers[-1].started and not harness.timers[-1].canceled

    # The page allows: destroy is called and the flag is armed.
    result = coordinator.complete(request_id, True)
    assert result == {"accepted": True, "state": "closing"}
    assert harness.destroyed == 1
    # Re-entered closing consumes the one-shot allow.
    assert coordinator.handle_closing() is True
    # Consumed exactly once; after that the closing state never allows again
    # (the window is being destroyed).
    assert coordinator.handle_closing() is False
    assert harness.destroyed == 1


def test_deny_cancels_and_allows_retry():
    harness = Harness()
    coordinator = harness.make()
    assert coordinator.handle_closing() is False
    harness.wait_notified()
    request_id = harness.notified[0]
    result = coordinator.complete(request_id, False)
    assert result == {"accepted": True, "state": "canceled"}
    assert harness.destroyed == 0
    assert coordinator.state(request_id) == "canceled"
    # A new closing starts a fresh request.
    assert coordinator.handle_closing() is False
    harness.wait_notified(2)
    assert len(harness.notified) == 2
    assert harness.notified[1] != request_id


def test_stale_and_wrong_ids_are_rejected():
    harness = Harness()
    coordinator = harness.make()
    assert coordinator.handle_closing() is False
    harness.wait_notified()
    request_id = harness.notified[0]
    stale = coordinator.complete("someone-else", True)
    assert stale == {"accepted": False, "state": "pending"}
    assert harness.destroyed == 0
    assert coordinator.state("someone-else") == "unknown"


def test_timeout_only_cancels_unallowed_requests():
    harness = Harness()
    coordinator = harness.make()
    assert coordinator.handle_closing() is False
    harness.wait_notified()
    request_id = harness.notified[0]
    # Fire the timeout: pending -> canceled + page notified.
    harness.timers[-1].fn()
    assert coordinator.state(request_id) == "canceled"
    assert harness.aborted == [(request_id, "timeout")]
    # A late allow is refused.
    late = coordinator.complete(request_id, True)
    assert late["accepted"] is False
    assert harness.destroyed == 0


def test_timeout_after_final_allow_keeps_closing():
    harness = Harness()
    coordinator = harness.make()
    assert coordinator.handle_closing() is False
    harness.wait_notified()
    request_id = harness.notified[0]
    result = coordinator.complete(request_id, True)
    assert result == {"accepted": True, "state": "closing"}
    # The timer was canceled on the final allow; even a stray timeout call
    # must not change the state nor unlock the page.
    harness.timers[-1].fn()
    assert coordinator.state(request_id) == "closing"
    assert harness.aborted == []
    assert harness.timers[-1].canceled is True


def test_destroy_failure_revokes_allow_and_notifies():
    harness = Harness()
    coordinator = harness.make()
    harness.destroy_error = RuntimeError("destroy failed")
    assert coordinator.handle_closing() is False
    harness.wait_notified()
    request_id = harness.notified[0]
    result = coordinator.complete(request_id, True)
    assert result == {"accepted": False, "state": "canceled"}
    assert coordinator.state(request_id) == "canceled"
    assert harness.aborted == [(request_id, "destroy_failed")]
    # The allow flag was revoked: closing again must not be allowed.
    assert coordinator.handle_closing() is False


def test_public_state_unknown_before_any_request():
    harness = Harness()
    coordinator = harness.make()
    assert coordinator.state("anything") == "unknown"


def test_page_notification_uses_json_serializable_id():
    # The id flows into evaluate_js via json.dumps; keep it a plain string.
    harness = Harness()
    coordinator = harness.make()
    assert coordinator.handle_closing() is False
    harness.wait_notified()
    assert isinstance(harness.notified[0], str)
    assert harness.notified[0]


# ---------------------------------------------------------------------------
# R1 §14.3: a superseded or resolved request is never re-announced
# ---------------------------------------------------------------------------


def test_superseded_and_resolved_requests_are_not_notified():
    harness = Harness()
    coordinator = harness.make()
    # Request A is denied, a fresh request B begins.
    assert coordinator.handle_closing() is False
    harness.wait_notified()
    request_a = harness.notified[0]
    generation_a = harness.notified_generations[0][1]
    coordinator.complete(request_a, False)
    assert coordinator.handle_closing() is False
    harness.wait_notified(2)
    request_b = harness.notified[1]
    generation_b = harness.notified_generations[1][1]
    before = len(harness.notified)
    # A late delivery attempt for the superseded A is skipped: the host
    # re-checks the current id/state before announcing (R1 §14.3).
    coordinator._safe_notify_page(request_a, generation_a)
    assert len(harness.notified) == before
    # The same holds after the current request itself is resolved.
    coordinator.complete(request_b, False)
    coordinator._safe_notify_page(request_b, generation_b)
    assert len(harness.notified) == before


# ---------------------------------------------------------------------------
# R14: the timeout callback is bound to its own request id
# ---------------------------------------------------------------------------


def test_stale_timeout_callback_cannot_cancel_new_request():
    harness = Harness()
    coordinator = harness.make()
    # Request A starts and is denied; its (already started) timer outlives it.
    assert coordinator.handle_closing() is False
    harness.wait_notified()
    request_a = harness.notified[0]
    stale_timer = harness.timers[-1]
    assert coordinator.complete(request_a, False) == {
        "accepted": True,
        "state": "canceled",
    }
    # Request B starts; A's late callback must not cancel B.
    assert coordinator.handle_closing() is False
    harness.wait_notified(2)
    request_b = harness.notified[1]
    assert request_b != request_a
    stale_timer.fn()
    assert coordinator.state(request_b) == "pending"
    assert harness.aborted == []
    assert coordinator.complete(request_b, True) == {
        "accepted": True,
        "state": "closing",
    }
    assert harness.destroyed == 1


def test_stale_timeout_cannot_unlock_a_final_closing():
    harness = Harness()
    coordinator = harness.make()
    # A denied, B finally allowed and closing.
    assert coordinator.handle_closing() is False
    harness.wait_notified()
    request_a = harness.notified[0]
    timer_a = harness.timers[-1]
    coordinator.complete(request_a, False)
    assert coordinator.handle_closing() is False
    harness.wait_notified(2)
    request_b = harness.notified[1]
    result = coordinator.complete(request_b, True)
    assert result == {"accepted": True, "state": "closing"}
    # Both the stale callback of A and the canceled callback of B are inert.
    timer_a.fn()
    harness.timers[-1].fn()
    assert coordinator.state(request_b) == "closing"
    assert harness.aborted == []
    assert harness.destroyed == 1


# ---------------------------------------------------------------------------
# R11: a native save in flight blocks the final allow and the destroy
# ---------------------------------------------------------------------------


def test_final_allow_refused_while_save_in_flight():
    harness = Harness()
    coordinator = harness.make(busy_probe=lambda: harness.busy)
    assert coordinator.handle_closing() is False
    harness.wait_notified()
    request_id = harness.notified[0]
    # The page allowed the close while the native save is still running: the
    # host refuses, cancels the request and notifies the page.
    harness.busy = True
    result = coordinator.complete(request_id, True)
    assert result == {"accepted": False, "state": "canceled"}
    assert harness.destroyed == 0
    assert harness.aborted == [(request_id, "save_in_flight")]
    assert coordinator.state(request_id) == "canceled"
    # After the save finishes the user can close again.
    harness.busy = False
    assert coordinator.handle_closing() is False
    harness.wait_notified(2)
    request_retry = harness.notified[1]
    assert coordinator.complete(request_retry, True) == {
        "accepted": True,
        "state": "closing",
    }
    assert harness.destroyed == 1


def test_flag_consumption_refused_while_save_in_flight():
    harness = Harness()
    coordinator = harness.make(busy_probe=lambda: harness.busy)
    assert coordinator.handle_closing() is False
    harness.wait_notified()
    request_id = harness.notified[0]
    # Arm the allow while no save runs; a save starts before the re-entered
    # closing consumes the flag and must revoke it instead of destroying.
    assert coordinator.complete(request_id, True) == {
        "accepted": True,
        "state": "closing",
    }
    harness.busy = True
    assert coordinator.handle_closing() is False
    assert coordinator.state(request_id) == "canceled"
    assert harness.aborted == [(request_id, "save_in_flight")]
    # No second destroy; a later close after the save works.
    assert harness.destroyed == 1
    harness.busy = False
    assert coordinator.handle_closing() is False
    harness.wait_notified(2)
    retry = harness.notified[1]
    assert coordinator.complete(retry, True) == {"accepted": True, "state": "closing"}
    assert harness.destroyed == 2


def test_busy_probe_exception_fails_safe():
    def broken_probe():
        raise RuntimeError("probe failed")

    harness = Harness()
    coordinator = harness.make(busy_probe=broken_probe)
    assert coordinator.handle_closing() is False
    harness.wait_notified()
    request_id = harness.notified[0]
    result = coordinator.complete(request_id, True)
    assert result == {"accepted": False, "state": "canceled"}
    assert harness.destroyed == 0
    assert harness.aborted == [(request_id, "save_in_flight")]


# ---------------------------------------------------------------------------
# R11 follow-up: the receipt reflects the real post-destroy state and the
# revoke notification never runs inside the synchronous closing callback
# ---------------------------------------------------------------------------


def test_destroy_reentry_revocation_returns_canceled_not_closing():
    harness = Harness()
    main_thread = threading.current_thread()
    deliveries = []
    coordinator = None

    def destroy():
        # `destroy` synchronously re-enters the closing event and a native
        # save starts exactly between the allow and the re-entry: the
        # re-entry revokes the allow and returns False (no destruction).
        harness.destroyed += 1
        if harness.destroyed == 1:
            harness.busy = True
            assert coordinator.handle_closing() is False
        else:
            # The retry after the save finished consumes the allow normally.
            assert coordinator.handle_closing() is True

    def notify_aborted(request_id, reason):
        deliveries.append(
            (request_id, reason, threading.current_thread() is main_thread)
        )

    coordinator = harness.make(
        busy_probe=lambda: harness.busy,
        destroy=destroy,
    )
    coordinator._notify_aborted = notify_aborted
    assert coordinator.handle_closing() is False
    harness.wait_notified()
    request_id = harness.notified[0]
    result = coordinator.complete(request_id, True)
    # The preset success is gone: the real state for this request id is
    # reported instead of accepted=true/closing.
    assert result == {"accepted": False, "state": "canceled"}
    assert coordinator.state(request_id) == "canceled"
    # The close_aborted notification is delivered from outside the
    # synchronous closing callback (a different thread), never via a
    # same-thread evaluate_js wait inside FormClosing.
    for _ in range(200):
        if deliveries:
            break
        threading.Event().wait(0.01)
    assert deliveries == [(request_id, "save_in_flight", False)]
    # No second destroy; a later close after the save finishes works.
    harness.busy = False
    assert coordinator.handle_closing() is False
    harness.wait_notified(2)
    retry = harness.notified[1]
    assert coordinator.complete(retry, True) == {
        "accepted": True,
        "state": "closing",
    }
    assert harness.destroyed == 2


def test_destroy_reentry_consumption_still_reports_closing():
    harness = Harness()
    coordinator = None

    def destroy():
        # The re-entered closing consumes the one-shot allow normally.
        harness.destroyed += 1
        assert coordinator.handle_closing() is True

    coordinator = harness.make(destroy=destroy)
    assert coordinator.handle_closing() is False
    harness.wait_notified()
    request_id = harness.notified[0]
    result = coordinator.complete(request_id, True)
    assert result == {"accepted": True, "state": "closing"}
    assert harness.aborted == []
    assert coordinator.state(request_id) == "closing"


def test_destroy_without_reentry_keeps_armed_allow():
    harness = Harness()
    coordinator = harness.make()
    assert coordinator.handle_closing() is False
    harness.wait_notified()
    request_id = harness.notified[0]
    result = coordinator.complete(request_id, True)
    assert result == {"accepted": True, "state": "closing"}
    # destroy returned without a re-entry: the armed one-shot allow is still
    # consumed by the next closing.
    assert coordinator.handle_closing() is True
    assert harness.destroyed == 1


# ---------------------------------------------------------------------------
# R1 §15.3: request generations bind a confirmation to the host authority
# ---------------------------------------------------------------------------


def test_request_generations_increase_and_track_the_current_request():
    harness = Harness()
    coordinator = harness.make()
    assert coordinator.handle_closing() is False
    harness.wait_notified()
    request_a = harness.notified[0]
    answer_a = coordinator.state_answer(request_a)
    assert answer_a["state"] == "pending"
    generation_a = answer_a["generation"]
    assert isinstance(generation_a, int) and generation_a > 0
    # Stable while the request stays current.
    assert coordinator.state_answer(request_a) == answer_a
    # A canceled request stays bound to its generation while it is still the
    # host's current id; a superseded one becomes plain unknown.
    coordinator._on_timeout(request_a)
    assert coordinator.state_answer(request_a) == {
        "state": "canceled",
        "generation": generation_a,
    }
    assert coordinator.handle_closing() is False
    harness.wait_notified(2)
    request_b = harness.notified[1]
    assert coordinator.state_answer(request_a) == {"state": "unknown"}
    answer_b = coordinator.state_answer(request_b)
    assert answer_b["state"] == "pending"
    assert answer_b["generation"] > generation_a
    assert coordinator.complete(request_b, True) == {
        "accepted": True,
        "state": "closing",
    }
    assert coordinator.state_answer(request_b) == {
        "state": "closing",
        "generation": answer_b["generation"],
    }


def test_request_notification_carries_the_host_generation():
    harness = Harness()
    coordinator = harness.make()
    assert coordinator.handle_closing() is False
    harness.wait_notified()
    request_id = harness.notified[0]
    generation = coordinator.state_answer(request_id)["generation"]
    assert harness.notified_generations == [(request_id, generation)]
    # A superseded request is never re-announced (same under-lock re-check).
    coordinator._on_timeout(request_id)
    before = len(harness.notified_generations)
    coordinator._safe_notify_page(request_id, generation)
    assert len(harness.notified_generations) == before


def test_host_api_get_close_state_exposes_the_generation():
    coordinator = CloseCoordinator(
        notify_page=lambda request_id, generation=None: None,
        destroy_window=lambda: None,
        notify_aborted=lambda request_id, reason: None,
    )
    api = d1_host_api.D1HostApi(launch_token="synthetic")
    api._close_coordinator = coordinator
    api.page_ready({"bridge_protocol": 1})
    assert coordinator.handle_closing() is False
    request_id = coordinator._current_id
    generation = coordinator.state_answer(request_id)["generation"]
    assert api.get_close_state({"close_request_id": request_id}) == {
        "state": "pending",
        "generation": generation,
    }
    # Another id is still plain unknown (no generation binding).
    assert api.get_close_state({"close_request_id": "someone-else"}) == {
        "state": "unknown"
    }


# ---------------------------------------------------------------------------
# D2 §4.3: the AI task barrier at close time (spec W5 requirement 5)
# ---------------------------------------------------------------------------


class TaskBarrier:
    """Records the host-side AI task barrier calls (freeze / drain / unfreeze)."""

    def __init__(self, live=0, in_flight=False, drain_result=True, live_after_drain=None):
        self.live = live
        self.in_flight = in_flight
        self.drain_result = drain_result
        self.live_after_drain = live_after_drain
        self.intents = 0
        self.canceled = 0
        self.drains = 0
        self.drained = False

    def snapshot(self):
        if self.drained:
            live = self.live_after_drain if self.live_after_drain is not None else 0
            return {"live": live, "in_flight": False}
        return {"live": self.live, "in_flight": self.in_flight}

    def on_intent(self):
        self.intents += 1

    def on_canceled(self):
        self.canceled += 1

    def drain(self):
        self.drains += 1
        self.drained = True
        return self.drain_result


def _barrier_coordinator(barrier):
    destroyed = {"count": 0}
    aborted = []
    notified = []

    def timer_factory(seconds, fn):
        timer = FakeTimer(seconds, fn)
        return timer

    coordinator = CloseCoordinator(
        notify_page=lambda rid, generation=None: notified.append(rid),
        destroy_window=lambda: destroyed.__setitem__("count", destroyed["count"] + 1),
        notify_aborted=lambda rid, reason: aborted.append((rid, reason)),
        timer_factory=timer_factory,
        task_snapshot=barrier.snapshot,
        on_close_intent=barrier.on_intent,
        on_close_canceled=barrier.on_canceled,
        drain_tasks=barrier.drain,
    )
    return coordinator, destroyed, aborted, notified


def _begin(coordinator, notified, count=1):
    assert coordinator.handle_closing() is False
    for _ in range(200):
        if len(notified) >= count:
            break
        threading.Event().wait(0.01)
    assert len(notified) >= count
    return notified[count - 1]


def test_ai_close_intent_freezes_new_claims():
    barrier = TaskBarrier(live=1)
    coordinator, _destroyed, _aborted, notified = _barrier_coordinator(barrier)
    _begin(coordinator, notified)
    assert barrier.intents == 1, "the close intent must freeze the AI executor"


def test_ai_active_tasks_require_an_explicit_task_choice():
    barrier = TaskBarrier(live=1)
    coordinator, destroyed, aborted, notified = _barrier_coordinator(barrier)
    request = _begin(coordinator, notified)
    # An unconfirmed allow (no task_choice) must never destroy the window.
    assert coordinator.complete(request, True) == {
        "accepted": False,
        "state": "canceled",
    }
    assert destroyed["count"] == 0
    assert aborted == [(request, "ai_tasks_active")]
    assert barrier.canceled == 1, "a refused close releases the AI freeze"
    # keep_waiting cancels this close without touching in-flight tasks.
    request = _begin(coordinator, notified, count=2)
    assert coordinator.complete(request, True, "keep_waiting") == {
        "accepted": False,
        "state": "canceled",
    }
    assert destroyed["count"] == 0
    assert aborted[-1] == (request, "ai_keep_waiting")
    assert barrier.drains == 0


def test_ai_stop_and_exit_drains_then_destroys():
    barrier = TaskBarrier(live=1)
    coordinator, destroyed, aborted, notified = _barrier_coordinator(barrier)
    request = _begin(coordinator, notified)
    assert coordinator.complete(request, True, "stop_and_exit") == {
        "accepted": True,
        "state": "closing",
    }
    assert barrier.drains == 1
    assert destroyed["count"] == 1
    assert aborted == []


def test_ai_drain_failure_refuses_close():
    barrier = TaskBarrier(live=1, drain_result=False)
    coordinator, destroyed, aborted, notified = _barrier_coordinator(barrier)
    request = _begin(coordinator, notified)
    assert coordinator.complete(request, True, "stop_and_exit") == {
        "accepted": False,
        "state": "canceled",
    }
    assert destroyed["count"] == 0
    assert aborted == [(request, "ai_drain_failed")]
    assert barrier.canceled == 1


def test_ai_tasks_still_live_after_drain_refuses_close():
    barrier = TaskBarrier(live=1, live_after_drain=1)
    coordinator, destroyed, aborted, notified = _barrier_coordinator(barrier)
    request = _begin(coordinator, notified)
    assert coordinator.complete(request, True, "stop_and_exit") == {
        "accepted": False,
        "state": "canceled",
    }
    assert destroyed["count"] == 0
    assert aborted == [(request, "ai_tasks_active")]


def test_ai_task_snapshot_exception_fails_safe():
    def broken():
        raise RuntimeError("task db unavailable")

    destroyed = {"count": 0}
    coordinator = CloseCoordinator(
        notify_page=lambda rid, generation=None: None,
        destroy_window=lambda: destroyed.__setitem__("count", destroyed["count"] + 1),
        notify_aborted=lambda rid, reason: None,
        timer_factory=FakeTimer,
        task_snapshot=broken,
    )
    assert coordinator.handle_closing() is False
    request = coordinator._current_id
    assert coordinator.complete(request, True) == {
        "accepted": False,
        "state": "canceled",
    }
    assert destroyed["count"] == 0


def test_ai_timeout_releases_the_freeze():
    barrier = TaskBarrier(live=1)
    coordinator, _destroyed, aborted, notified = _barrier_coordinator(barrier)
    request = _begin(coordinator, notified)
    coordinator._on_timeout(request)
    assert aborted == [(request, "timeout")]
    assert barrier.canceled == 1, "an abandoned close releases the AI freeze"


def test_host_api_forwards_task_choice():
    recorded = {}

    class RecordingCoordinator:
        def complete(self, request_id, allow, task_choice=None):
            recorded["request_id"] = request_id
            recorded["allow"] = allow
            recorded["task_choice"] = task_choice
            return {"accepted": True, "state": "closing"}

        def state(self, request_id):
            return "pending"

    api = d1_host_api.D1HostApi(launch_token="synthetic")
    api._close_coordinator = RecordingCoordinator()
    api.page_ready({"bridge_protocol": 1})
    assert api.complete_close(
        {"close_request_id": "r1", "allow": True, "task_choice": "stop_and_exit"}
    ) == {"accepted": True, "state": "closing"}
    assert recorded == {
        "request_id": "r1",
        "allow": True,
        "task_choice": "stop_and_exit",
    }
    # An unrecognised choice is dropped (the coordinator then refuses a live
    # close rather than guessing).
    api.complete_close(
        {"close_request_id": "r2", "allow": True, "task_choice": "nonsense"}
    )
    assert recorded["task_choice"] is None



def test_late_second_confirmation_across_real_bridge_threads():
    """R1 §15.3, host side: A's second ``pending`` answer can really be
    produced while A is the current request (under the coordinator lock) and
    be delivered only after the host moved on to B. The answer is bound to
    A's generation; the late allow for A is refused and B stays pending. Uses
    pywebview's real ``js_bridge_call`` worker threads and a gated fake window
    (delivery held, like a lost-in-transit reply); no GUI and no wall-clock
    wait. The page-side generation rejection of exactly this late answer is
    covered by the component suite (``d1.components.test.mjs``)."""

    from webview.util import js_bridge_call

    trace = {}
    notices = []
    note = threading.Event()
    held = threading.Event()
    release = threading.Event()
    done = {label: threading.Event() for label in ("a1", "a2", "b1", "b2")}

    def notify(request_id, generation=None):
        notices.append((request_id, generation))
        note.set()

    coordinator = CloseCoordinator(
        notify_page=notify,
        destroy_window=lambda: None,
        notify_aborted=lambda request_id, reason: None,
        timer_factory=FakeTimer,
    )
    api = d1_host_api.D1HostApi(launch_token="synthetic")
    api._close_coordinator = coordinator
    api.page_ready({"bridge_protocol": 1})

    class FakeWindow:
        _functions = {}
        _js_api = api

        def evaluate_js(self, script):
            label = next(name for name in done if f'["{name}"]' in script)
            trace[label] = script
            if label == "a2":
                held.set()
                assert release.wait(10)
            done[label].set()

    window = FakeWindow()
    assert coordinator.handle_closing() is False
    assert note.wait(5)
    request_a = notices[-1][0]
    generation_a = notices[-1][1]

    def query(identifier, label):
        js_bridge_call(
            window, "get_close_state", [{"close_request_id": identifier}], label
        )

    query(request_a, "a1")
    assert done["a1"].wait(5)
    # The second answer is produced while A is still current and pending.
    query(request_a, "a2")
    assert held.wait(5)
    assert '"pending"' in trace["a2"]
    assert f'"generation": {generation_a}' in trace["a2"]

    # A times out; a new request B begins and is fully confirmed.
    coordinator._on_timeout(request_a)
    note.clear()
    assert coordinator.handle_closing() is False
    assert note.wait(5)
    request_b = notices[-1][0]
    generation_b = notices[-1][1]
    assert request_a != request_b
    assert generation_b > generation_a
    query(request_b, "b1")
    assert done["b1"].wait(5)
    query(request_b, "b2")
    assert done["b2"].wait(5)

    # The held stale answer is delivered only now; the host knows A is
    # unknown and refuses a late allow while B stays pending.
    release.set()
    assert done["a2"].wait(5)
    assert api.get_close_state({"close_request_id": request_a}) == {
        "state": "unknown"
    }
    assert api.complete_close(
        {"close_request_id": request_a, "allow": True}
    ) == {"accepted": False, "state": "pending"}
    assert api.get_close_state({"close_request_id": request_b}) == {
        "state": "pending",
        "generation": generation_b,
    }


def test_page_busy_probe_is_page_scoped_and_requires_ready():
    api = d1_host_api.D1HostApi(launch_token="x")
    # Before the page handshake the bridge refuses the state change.
    ticket = api.get_bootstrap()["page_ticket"]
    assert api.set_page_busy(
        {"busy": True, "seq": 1, "page_ticket": ticket}
    ) == {
        "accepted": False,
        "busy": False,
        "seq": 0,
    }
    assert api.page_ready(
        {"bridge_protocol": d1_host_api.BRIDGE_PROTOCOL, "page_ticket": ticket}
    )["accepted"] is True
    assert api.set_page_busy(
        {"busy": True, "seq": 2, "page_ticket": ticket}
    ) == {
        "accepted": True,
        "busy": True,
        "seq": 2,
    }
    assert api._page_busy_probe() is True
    # A duplicate page_ready from the same page must not clear the barrier.
    assert api.page_ready(
        {"bridge_protocol": d1_host_api.BRIDGE_PROTOCOL, "page_ticket": ticket}
    )["accepted"] is True
    assert api._page_busy_probe() is True
    assert api.set_page_busy(
        {"busy": False, "seq": 0, "page_ticket": ticket}
    ) == {
        "accepted": False,
        "busy": True,
        "seq": 2,
    }
    # A late older notification must not clear the newer busy state.
    assert api.set_page_busy(
        {"busy": False, "seq": 1, "page_ticket": ticket}
    ) == {
        "accepted": True,
        "busy": True,
        "seq": 2,
    }
    assert api._page_busy_probe() is True
    assert api.set_page_busy(
        {"busy": False, "seq": 3, "page_ticket": ticket}
    ) == {
        "accepted": True,
        "busy": False,
        "seq": 3,
    }
    assert api._page_busy_probe() is False


def test_page_ticket_isolates_old_page_ready_and_busy():
    api = d1_host_api.D1HostApi(launch_token="x")
    ticket_a = api.get_bootstrap()["page_ticket"]
    assert api.page_ready(
        {"bridge_protocol": d1_host_api.BRIDGE_PROTOCOL, "page_ticket": ticket_a}
    )["accepted"] is True
    assert api.set_page_busy(
        {"busy": True, "seq": 20, "page_ticket": ticket_a}
    )["busy"] is True
    # A new page handshake retires A; B starts its own barrier.
    ticket_b = api.get_bootstrap()["page_ticket"]
    assert api.page_ready(
        {"bridge_protocol": d1_host_api.BRIDGE_PROTOCOL, "page_ticket": ticket_b}
    )["accepted"] is True
    assert api.set_page_busy(
        {"busy": True, "seq": 1, "page_ticket": ticket_b}
    )["busy"] is True
    # A late old busy false and a late old page_ready are both refused and
    # must not clear B's barrier.
    assert api.set_page_busy(
        {"busy": False, "seq": 21, "page_ticket": ticket_a}
    )["accepted"] is False
    assert api.page_ready(
        {"bridge_protocol": d1_host_api.BRIDGE_PROTOCOL, "page_ticket": ticket_a}
    )["accepted"] is False
    assert api._page_busy_probe() is True
    # A duplicate current ready is idempotent and keeps the barrier.
    assert api.page_ready(
        {"bridge_protocol": d1_host_api.BRIDGE_PROTOCOL, "page_ticket": ticket_b}
    )["accepted"] is True
    assert api._page_busy_probe() is True
    # A missing/invalid ticket cannot change the barrier.
    assert api.set_page_busy({"busy": False, "seq": 2})["accepted"] is False
    assert api.set_page_busy(
        {"busy": False, "seq": 2, "page_ticket": "wrong"}
    )["accepted"] is False
    assert api.set_page_busy(
        {"busy": False, "seq": 2, "page_ticket": ticket_b}
    )["busy"] is False


def test_page_ready_validates_ticket_before_ready_receipt_confirm():
    class Receipt:
        def __init__(self):
            self.calls = 0

        def public_bootstrap(self):
            return {"plan_id": "p", "nonce": "n"}

        def confirm(self, payload, *, page_ready=False):
            self.calls += 1
            return {"accepted": True}

    receipt = Receipt()
    api = d1_host_api.D1HostApi(launch_token="x", ready_receipt=receipt)
    ticket_a = api.get_bootstrap()["page_ticket"]
    # Invalid ticket: refused before any ready-receipt side effect.
    assert api.page_ready(
        {
            "bridge_protocol": d1_host_api.BRIDGE_PROTOCOL,
            "page_ticket": "wrong",
            "update_install": {"plan_id": "p", "nonce": "n"},
        }
    )["accepted"] is False
    assert receipt.calls == 0
    # Valid ticket: confirmation happens once; duplicate ready is idempotent.
    assert api.page_ready(
        {
            "bridge_protocol": d1_host_api.BRIDGE_PROTOCOL,
            "page_ticket": ticket_a,
            "update_install": {"plan_id": "p", "nonce": "n"},
        }
    )["accepted"] is True
    assert receipt.calls == 1
    assert api.page_ready(
        {
            "bridge_protocol": d1_host_api.BRIDGE_PROTOCOL,
            "page_ticket": ticket_a,
            "update_install": {"plan_id": "p", "nonce": "n"},
        }
    )["accepted"] is True
    assert receipt.calls == 1
    # While the next page's ticket is pending, a ticketless legacy ready is
    # not allowed to re-enter and does not call confirm.
    api.get_bootstrap()
    assert api.page_ready(
        {
            "bridge_protocol": d1_host_api.BRIDGE_PROTOCOL,
            "update_install": {"plan_id": "p", "nonce": "n"},
        }
    )["accepted"] is False
    assert receipt.calls == 1
