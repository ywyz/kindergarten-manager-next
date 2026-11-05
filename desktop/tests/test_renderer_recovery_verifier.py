"""Focused tests for the source verifier's pure state/boundary helpers."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import verify_renderer_recovery_window as verifier


class GuardedLock:
    def __init__(self, host) -> None:
        self._host = host
        self._lock = threading.RLock()

    def __enter__(self):
        self._lock.acquire()
        object.__setattr__(self._host, "_lock_owner", threading.get_ident())
        return self

    def __exit__(self, exc_type, exc, tb):
        object.__setattr__(self._host, "_lock_owner", None)
        self._lock.release()
        return False


class GuardedEvent:
    def __init__(self, host) -> None:
        self._host = host
        self._set = False

    def set(self) -> None:
        self._set = True

    def is_set(self) -> bool:
        if object.__getattribute__(self._host, "_lock_owner") != threading.get_ident():
            raise AssertionError("business_ready read without page lock")
        return self._set


class GuardedHost:
    _GUARDED = frozenset(
        {
            "_retired",
            "_page_ready",
            "_page_ticket_bound",
            "_business_ready",
            "_page_ticket",
            "_launch_token",
            "_maintenance_notice",
            "_document_generation",
            "_page_busy",
        }
    )

    def __init__(self) -> None:
        object.__setattr__(self, "_lock_owner", None)
        object.__setattr__(self, "_page_lock", GuardedLock(self))
        object.__setattr__(self, "_business_ready", GuardedEvent(self))
        object.__setattr__(self, "_retired", False)
        object.__setattr__(self, "_page_ready", True)
        object.__setattr__(self, "_page_ticket_bound", True)
        object.__setattr__(self, "_page_ticket", "ticket-old")
        object.__setattr__(self, "_launch_token", "launch-old")
        object.__setattr__(self, "_maintenance_notice", "notice")
        object.__setattr__(self, "_document_generation", 2)
        object.__setattr__(self, "_page_busy", False)

    def __getattribute__(self, name):
        if name in object.__getattribute__(self, "_GUARDED"):
            owner = object.__getattribute__(self, "_lock_owner")
            if owner != threading.get_ident():
                raise AssertionError(f"{name} read without page lock")
        return object.__getattribute__(self, name)

    def set_business_ready(self) -> None:
        with self._page_lock:
            self._business_ready.set()

    def raw_state(self) -> dict:
        with self._page_lock:
            return {
                "retired": self._retired,
                "page_ready": self._page_ready,
                "ticket_bound": self._page_ticket_bound,
                "business_ready": self._business_ready.is_set(),
                "ticket": self._page_ticket,
                "launch_token": self._launch_token,
                "maintenance_notice": self._maintenance_notice,
                "document_generation": self._document_generation,
                "page_busy": self._page_busy,
            }

    def get_bootstrap(self):
        raise AssertionError("get_bootstrap must not be called")


def test_host_page_state_reads_under_lock_without_bootstrap_mutation():
    host = GuardedHost()
    host.set_business_ready()
    before = host.raw_state()
    state = verifier._host_page_state(host)
    after = host.raw_state()
    assert state == before == after
    assert verifier._active_page(state) is True
    with pytest.raises(AssertionError):
        host.get_bootstrap()
    public = verifier._public_host_state(state)
    assert "ticket" not in public and "launch_token" not in public
    assert public["ticket_fingerprint"] is not None
    assert public["launch_fingerprint"] is not None
    assert public["ticket_fingerprint"] != public["launch_fingerprint"]


def test_host_page_state_requires_lock_bound_business_ready_and_not_retired():
    with pytest.raises(RuntimeError):
        verifier._host_page_state(SimpleNamespace())
    host = GuardedHost()
    assert verifier._active_page(verifier._host_page_state(host)) is False
    host.set_business_ready()
    host._page_ticket_bound = False
    assert verifier._active_page(verifier._host_page_state(host)) is False
    host._page_ticket_bound = True
    host._retired = True
    assert verifier._active_page(verifier._host_page_state(host)) is False


def _persist_cli(tmp_path: Path) -> SimpleNamespace:
    tmp_path.mkdir(parents=True, exist_ok=True)
    data = tmp_path / "data"
    data.mkdir()
    (data / "kindergarten.db").write_bytes(b"")
    credential = tmp_path / "credentials"
    credential.mkdir()
    expected = tmp_path / "out" / "expected.json"
    expected.parent.mkdir()
    expected.write_text("{}", encoding="utf-8")
    output = tmp_path / "out" / "child.json"
    return SimpleNamespace(
        data=str(data),
        credential_root=str(credential),
        expected_fingerprint=str(expected),
        persist_out=str(output),
    )


def test_persist_path_validation_rejects_missing_raw_nonfresh_and_overlap(tmp_path):
    cli = _persist_cli(tmp_path / "base")
    paths = verifier._validate_persist_paths(cli)
    assert paths["db"] == Path(cli.data) / "kindergarten.db"

    missing = tmp_path / "missing"
    with pytest.raises(ValueError, match="data root"):
        verifier._validate_persist_paths(
            SimpleNamespace(
                data=str(missing),
                credential_root=cli.credential_root,
                expected_fingerprint=cli.expected_fingerprint,
                persist_out=cli.persist_out,
            )
        )

    no_db = tmp_path / "no-db"
    no_db.mkdir()
    with pytest.raises(ValueError, match="kindergarten.db"):
        verifier._validate_persist_paths(
            SimpleNamespace(
                data=str(no_db),
                credential_root=cli.credential_root,
                expected_fingerprint=cli.expected_fingerprint,
                persist_out=cli.persist_out,
            )
        )

    with pytest.raises(ValueError, match="credential"):
        verifier._validate_persist_paths(
            SimpleNamespace(
                data=cli.data,
                credential_root=str(tmp_path / "missing-credentials"),
                expected_fingerprint=cli.expected_fingerprint,
                persist_out=cli.persist_out,
            )
        )

    with pytest.raises(ValueError, match="expected fingerprint"):
        verifier._validate_persist_paths(
            SimpleNamespace(
                data=cli.data,
                credential_root=cli.credential_root,
                expected_fingerprint=str(tmp_path / "missing-expected.json"),
                persist_out=cli.persist_out,
            )
        )

    with pytest.raises(ValueError, match="raw parent"):
        verifier._validate_persist_paths(
            SimpleNamespace(
                data=str(Path(cli.data) / ".." / "data"),
                credential_root=cli.credential_root,
                expected_fingerprint=cli.expected_fingerprint,
                persist_out=cli.persist_out,
            )
        )

    Path(cli.persist_out).write_text("existing", encoding="utf-8")
    with pytest.raises(ValueError, match="fresh"):
        verifier._validate_persist_paths(cli)

    overlap_root = tmp_path / "overlap"
    overlap_root.mkdir()
    overlap = _persist_cli(overlap_root)
    overlap_out = Path(overlap.data) / "child.json"
    with pytest.raises(ValueError, match="overlap"):
        verifier._validate_persist_paths(
            SimpleNamespace(
                data=overlap.data,
                credential_root=overlap.credential_root,
                expected_fingerprint=overlap.expected_fingerprint,
                persist_out=str(overlap_out),
            )
        )


def test_persist_path_validation_rejects_reparse_component(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)
    cli = _persist_cli(tmp_path)
    with pytest.raises(ValueError, match="reparse"):
        verifier._validate_persist_paths(
            SimpleNamespace(
                data=str(link / "data"),
                credential_root=cli.credential_root,
                expected_fingerprint=cli.expected_fingerprint,
                persist_out=cli.persist_out,
            )
        )


def test_main_output_directory_rejects_sidecars_unknown_files_and_collision(tmp_path):
    parent = tmp_path / "window"
    parent.mkdir()
    verifier._validate_output_directory(parent / "result.json")
    (parent / "unknown.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="fresh and empty"):
        verifier._validate_output_directory(parent / "result.json")

    sidecar_parent = tmp_path / "sidecar-window"
    sidecar_parent.mkdir()
    (sidecar_parent / "recovery-persist-expected.json").write_text(
        "old", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="fresh and empty"):
        verifier._validate_output_directory(sidecar_parent / "result.json")

    collision_parent = tmp_path / "collision-window"
    collision_parent.mkdir()
    with pytest.raises(ValueError, match="collides"):
        verifier._validate_output_directory(
            collision_parent / "recovery-persist-child.json"
        )
    assert (parent / "unknown.txt").read_text(encoding="utf-8") == "keep"


def test_fingerprint_summary_is_compact_and_complete():
    fingerprint = {
        "combined_sha256": "combined",
        "database": {
            "fingerprint_sha256": "database",
            "schema_revision": "revision",
            "tables": {"a": {}, "b": {}},
            "counts": {"rows": 3},
        },
        "resources": {
            "fingerprint_sha256": "resources",
            "file_count": 2,
            "total_bytes": 42,
        },
    }
    summary = verifier._fingerprint_summary(fingerprint)
    assert summary == {
        "combined_sha256": "combined",
        "database_sha256": "database",
        "resources_sha256": "resources",
        "schema_revision": "revision",
        "table_count": 2,
        "resource_count": 2,
        "resource_total_bytes": 42,
        "semantic_counts": {"rows": 3},
    }


class _FakeButton(SimpleNamespace):
    pass


def _fake_prompt(owner):
    keep = _FakeButton(
        Text=verifier.KEEP_TEXT,
        DialogResult="Cancel",
        PerformClick=lambda: None,
    )
    reopen = _FakeButton(
        Text=verifier.REOPEN_TEXT,
        DialogResult="OK",
        PerformClick=lambda: None,
    )
    form = SimpleNamespace(
        Text=verifier.PROMPT_TITLE,
        Owner=owner,
        Controls=[keep, reopen],
        AcceptButton=keep,
        CancelButton=keep,
        ActiveControl=keep,
    )
    return form, keep, reopen


def test_prompt_form_match_requires_exact_owner_buttons_and_default():
    owner = SimpleNamespace(Handle=1)
    form, keep, reopen = _fake_prompt(owner)
    assert verifier._prompt_form_matches(form, owner) is True
    assert verifier._find_prompt_form([form], owner) is form

    wrong_owner = SimpleNamespace(Handle=2)
    assert verifier._prompt_form_matches(form, wrong_owner) is False
    form.Owner = wrong_owner
    assert verifier._prompt_form_matches(form, wrong_owner) is True
    form.Owner = owner

    form.Text = "other"
    assert verifier._prompt_form_matches(form, owner) is False
    form.Text = verifier.PROMPT_TITLE

    form.Controls = [
        keep,
        reopen,
        _FakeButton(Text="extra", DialogResult="OK", PerformClick=lambda: None),
    ]
    assert verifier._prompt_form_matches(form, owner) is False
    form.Controls = [keep, reopen]

    form.AcceptButton = reopen
    assert verifier._prompt_form_matches(form, owner) is True
    form.AcceptButton = keep
    form.CancelButton = reopen
    assert verifier._prompt_form_matches(form, owner) is True
    form.CancelButton = keep
    form.ActiveControl = reopen
    assert verifier._prompt_form_matches(form, owner) is True
    form.ActiveControl = keep

    duplicate, _keep, _reopen = _fake_prompt(owner)
    assert verifier._find_prompt_form([form, duplicate], owner) is None


def test_prompt_input_gate_rejects_each_unreliable_capability():
    identity = {
        "pid_match": True,
        "owner_pid_match": True,
        "thread_match": True,
        "owner_match": True,
        "managed_owner": True,
        "buttons_exact": True,
        "managed_default_keep": True,
        "visible": True,
        "enabled": True,
        "handle_created": True,
        "modal": True,
        "handles_nonzero": True,
        "button_handles_distinct": True,
        "foreground": True,
        "focus_keep": True,
        "focus_matches_keep": True,
    }
    assert verifier._prompt_input_gate(identity) is None
    for key in tuple(identity):
        broken = dict(identity)
        broken[key] = False
        assert verifier._prompt_input_gate(broken) == key
    broken = dict(identity)
    broken["focus_keep"] = False
    assert verifier._prompt_input_gate(broken) == "focus_keep"
    zero = dict(
        identity,
        keep_hwnd=0,
        focus_hwnd=0,
        focus_keep=True,
        handles_nonzero=False,
        focus_matches_keep=False,
    )
    assert verifier._prompt_input_gate(zero) == "handles_nonzero"
    same_button = dict(
        identity,
        keep_hwnd=100,
        reopen_hwnd=100,
        button_handles_distinct=False,
    )
    assert verifier._prompt_input_gate(same_button) == "button_handles_distinct"


def test_keyboard_events_are_real_sendinput_keydown_and_keyup():
    assert verifier.ctypes.sizeof(verifier._INPUT) == 40
    enter = verifier._keyboard_input_events(verifier._VK_RETURN)
    assert len(enter) == 2
    assert [event.type for event in enter] == [
        verifier._INPUT_KEYBOARD,
        verifier._INPUT_KEYBOARD,
    ]
    assert [event.ki.wVk for event in enter] == [0x0D, 0x0D]
    assert [event.ki.dwFlags for event in enter] == [
        0,
        verifier._KEYEVENTF_KEYUP,
    ]
    escape = verifier._keyboard_input_events(verifier._VK_ESCAPE)
    assert [event.ki.wVk for event in escape] == [0x1B, 0x1B]


def test_click_coordinates_require_button_inside_prompt_and_screen():
    button = (10, 20, 30, 40)
    prompt = (0, 0, 100, 100)
    screen = (0, 0, 100, 100)
    coordinates = verifier._absolute_click_coordinates(button, prompt, screen)
    assert coordinates is not None
    assert all(0 <= value <= 65535 for value in coordinates)
    assert verifier._absolute_click_coordinates(
        (90, 90, 110, 110), prompt, screen
    ) is None
    assert verifier._absolute_click_coordinates(
        button, prompt, (0, 0, 1, 1)
    ) is None
    assert verifier._absolute_click_coordinates(
        button, prompt, (200, 200, 100, 100)
    ) is None
    assert verifier._absolute_click_coordinates(
        (10, 20, 10, 40), prompt, screen
    ) is None


class _FakeThread:
    def __init__(self, alive: bool) -> None:
        self._alive = alive

    def is_alive(self) -> bool:
        return self._alive


class _FakeIdle:
    def __init__(self, value: bool) -> None:
        self._value = value

    def is_set(self) -> bool:
        return self._value


class _FakeExecutor:
    def __init__(self, *, alive: bool, clean: bool) -> None:
        self._gate = threading.RLock()
        self._thread = _FakeThread(alive) if alive else None
        self._idle = _FakeIdle(clean)
        self._active = None if clean else object()
        self._pending_results = {} if clean else {"execution": object()}
        self._unconfirmed = not clean
        self._unconfirmed_slots = [] if clean else [object()]


def test_executor_gate_negative_controls_cover_each_leftover():
    clean = verifier._executor_gate_snapshot(
        _FakeExecutor(alive=False, clean=True)
    )
    assert verifier._executor_gate_ok(clean) is True
    dirty_cases = (
        {"alive": True, "clean": True},
        {"alive": False, "clean": False},
    )
    for case in dirty_cases:
        snapshot = verifier._executor_gate_snapshot(_FakeExecutor(**case))
        assert verifier._executor_gate_ok(snapshot) is False
    for field in (
        "thread_present",
        "thread_alive",
        "active_none",
        "pending_empty",
        "unconfirmed",
        "slots_empty",
        "idle",
    ):
        broken = dict(clean)
        broken[field] = not broken[field]
        assert verifier._executor_gate_ok(broken) is False, field


class _FakeRuntime:
    def __init__(self) -> None:
        self._lock_handle = object()
        self._owns_lock = True

    def _validate_lock_handle(self) -> None:
        return None


def test_lock_snapshot_requires_same_valid_owned_handle():
    runtime = _FakeRuntime()
    expected = runtime._lock_handle
    snapshot = verifier._lock_snapshot(runtime, expected)
    assert verifier._lock_ok(snapshot) is True
    for field, value in (
        ("owns", False),
        ("handle_present", False),
        ("same_handle", False),
        ("valid", False),
    ):
        broken = dict(snapshot)
        broken[field] = value
        assert verifier._lock_ok(broken) is False, field
    runtime._lock_handle = object()
    assert verifier._lock_snapshot(runtime, expected)["same_handle"] is False


def test_old_callback_probe_keeps_new_state_freeze_and_close_unchanged():
    host = GuardedHost()
    host.set_business_ready()
    executor = SimpleNamespace(
        _freeze_owners={"new-owner"}, _gate=threading.RLock()
    )
    before = host.raw_state()
    recovery = SimpleNamespace(
        _on_native_failure=lambda kind: None,
        intercept_native_close=lambda: True,
    )
    probe = verifier._old_callback_probe(recovery, host, executor)
    assert probe["intercept_result"] is True
    assert probe["state_unchanged"] is True
    assert probe["freeze_owners_unchanged"] is True
    assert probe["freeze_owner_count_before"] == 1
    assert probe["freeze_owner_count_after"] == 1
    assert probe["close_state_unchanged"] is True
    assert host.raw_state() == before
    assert executor._freeze_owners == {"new-owner"}


def test_managed_handle_and_reference_equality_real_interop():
    from System import IntPtr, Object
    from System.Windows.Forms import Button, Form

    assert verifier._managed_handle(IntPtr(123)) == 123
    assert verifier._managed_handle(123) == 123
    with pytest.raises(verifier.PromptHandleError):
        verifier._managed_handle(object())

    owner = Form()
    other = Form()
    dialog = Form()
    keep = Button()
    other_button = Button()
    try:
        dialog.Owner = owner
        dialog.Text = verifier.PROMPT_TITLE
        keep.Text = verifier.KEEP_TEXT
        other_button.Text = verifier.REOPEN_TEXT
        dialog.Controls.Add(keep)
        dialog.Controls.Add(other_button)
        dialog.AcceptButton = keep
        dialog.CancelButton = keep
        dialog.ActiveControl = keep

        assert (dialog.Owner is owner) is False
        assert Object.ReferenceEquals(dialog.Owner, owner) is True
        assert (dialog.AcceptButton is keep) is False
        assert Object.ReferenceEquals(dialog.AcceptButton, keep) is True
        assert verifier._managed_reference_equal(dialog.Owner, owner) is True
        assert verifier._managed_reference_equal(dialog.Owner, other) is False
        assert verifier._managed_reference_equal(dialog.AcceptButton, keep) is True
        assert (
            verifier._managed_reference_equal(dialog.AcceptButton, other_button)
            is False
        )
        assert verifier._managed_reference_equal(dialog.ActiveControl, keep) is True
        assert (
            verifier._managed_reference_equal(dialog.ActiveControl, other_button)
            is False
        )
        assert verifier._prompt_form_matches(dialog, owner) is True
    finally:
        for item in (dialog, keep, other_button, owner, other):
            try:
                item.Dispose()
            except Exception:
                pass


def _event(phase, seq, *, label, generation, uid, detail=None):
    return {
        "seq": seq,
        "monotonic_ns": seq * 100,
        "thread": 123,
        "phase": phase,
        "host_label": label,
        "bundle_label": "old-bundle" if label == "old-host" else "new-bundle",
        "generation": generation,
        "window_uid": uid,
        "detail": detail or {},
    }


def _event_sequence():
    old_phases = (
        "old_stop_if_idle.enter",
        "old_stop_if_idle.return",
        "old_service_stop.enter",
        "old_service_stop.return",
        "old_host_retire.enter",
        "old_host_retire.return",
        "engine_close.enter",
        "engine_close.return",
        "engine_reopen.enter",
        "engine_reopen.return",
        "old_host_retire_idempotent.enter",
        "old_host_retire_idempotent.return",
    )
    new_phases = (
        "new_bundle.install_cas.enter",
        "new_bundle.install_cas.return",
        "new_service.start.enter",
        "new_service.start.return",
        "new_business_ready.enter",
        "new_business_ready.return",
    )
    events = []
    seq = 0
    for phase in old_phases:
        seq += 1
        detail = {}
        if phase == "old_stop_if_idle.return":
            detail = {
                "return": True,
                "thread_alive_after": False,
                "gate_ok": True,
            }
        elif phase == "old_service_stop.return":
            detail = {"return": True, "thread_alive_after": False}
        elif phase == "old_host_retire.return":
            detail = {"retired": True}
        elif phase == "old_host_retire_idempotent.return":
            detail = {"first": False, "retired": True, "page_ready": False}
        elif phase in ("engine_close.return", "engine_reopen.return"):
            detail = {"lock_ok": True}
        events.append(
            _event(
                phase,
                seq,
                label="old-host",
                generation=1,
                uid="old",
                detail=detail,
            )
        )
    for phase in new_phases:
        seq += 1
        uid = "new" if phase.startswith("new_business") else None
        detail = {}
        if phase == "new_bundle.install_cas.enter":
            detail = {"expected_is_old": True}
        elif phase == "new_bundle.install_cas.return":
            detail = {"installed": True}
        elif phase == "new_service.start.return":
            detail = {"started": True}
        elif phase == "new_business_ready.return":
            detail = {"ready": True, "business_ready": True}
        events.append(
            _event(phase, seq, label="new-host", generation=2, uid=uid, detail=detail)
        )
    seq += 1
    events.append(
        _event(
            "old_destroy.enter",
            seq,
            label="old-host",
            generation=1,
            uid="old",
            detail={
                "old_form_alive_before": True,
                "new_business_ready": True,
                "new_window_visible": True,
                "new_document_generation": 2,
                "fresh_executor_ok": True,
            },
        )
    )
    seq += 1
    events.append(
        _event(
            "old_window.closed",
            seq,
            label="old-host",
            generation=1,
            uid="old",
            detail={"closed": True},
        )
    )
    seq += 1
    events.append(
        _event(
            "old_destroy.return",
            seq,
            label="old-host",
            generation=1,
            uid="old",
            detail={"old_form_alive_after": False},
        )
    )
    return events


def test_event_sequence_requires_order_labels_generations_and_destroy_snapshot():
    events = _event_sequence()
    assert verifier._event_sequence_ok(
        events,
        old_generation=1,
        new_generation=2,
        old_uid="old",
        new_uid="new",
        worker_thread=123,
    ) is True
    wrong_order = list(events)
    wrong_order[0], wrong_order[1] = wrong_order[1], wrong_order[0]
    assert verifier._event_sequence_ok(
        wrong_order,
        old_generation=1,
        new_generation=2,
        old_uid="old",
        new_uid="new",
        worker_thread=123,
    ) is False
    wrong_label = list(events)
    wrong_label[0] = dict(wrong_label[0], host_label="new-host")
    assert verifier._event_sequence_ok(
        wrong_label,
        old_generation=1,
        new_generation=2,
        old_uid="old",
        new_uid="new",
        worker_thread=123,
    ) is False
    wrong_generation = list(events)
    wrong_generation[0] = dict(wrong_generation[0], generation=99)
    assert verifier._event_sequence_ok(
        wrong_generation,
        old_generation=1,
        new_generation=2,
        old_uid="old",
        new_uid="new",
        worker_thread=123,
    ) is False
    missing = [event for event in events if event["phase"] != "old_destroy.return"]
    assert verifier._event_sequence_ok(
        missing,
        old_generation=1,
        new_generation=2,
        old_uid="old",
        new_uid="new",
        worker_thread=123,
    ) is False
    bad_snapshot = list(events)
    for index, event in enumerate(bad_snapshot):
        if event["phase"] == "old_destroy.enter":
            bad_snapshot[index] = dict(
                event, detail=dict(event["detail"], new_business_ready=False)
            )
    assert verifier._event_sequence_ok(
        bad_snapshot,
        old_generation=1,
        new_generation=2,
        old_uid="old",
        new_uid="new",
        worker_thread=123,
    ) is False
    idempotent = [event for event in events if "idempotent" in event["phase"]]
    reordered = [event for event in events if "idempotent" not in event["phase"]]
    insert_at = next(
        index
        for index, event in enumerate(reordered)
        if event["phase"] == "new_bundle.install_cas.return"
    )
    reordered[insert_at:insert_at] = idempotent
    assert verifier._event_sequence_ok(
        reordered,
        old_generation=1,
        new_generation=2,
        old_uid="old",
        new_uid="new",
        worker_thread=123,
    ) is False
    wrong_thread = list(events)
    wrong_thread[0] = dict(wrong_thread[0], thread=999)
    assert verifier._event_sequence_ok(
        wrong_thread,
        old_generation=1,
        new_generation=2,
        old_uid="old",
        new_uid="new",
        worker_thread=123,
    ) is False
    assert verifier._event_sequence_ok(
        events,
        old_generation=1,
        new_generation=2,
        old_uid=None,
        new_uid="new",
        worker_thread=123,
    ) is False
    assert verifier._event_sequence_ok(
        events,
        old_generation=1,
        new_generation=2,
        old_uid="new",
        new_uid="new",
        worker_thread=123,
    ) is False
    duplicate_seq = list(events)
    duplicate_seq[1] = dict(duplicate_seq[1], seq=duplicate_seq[0]["seq"])
    assert verifier._event_sequence_ok(
        duplicate_seq,
        old_generation=1,
        new_generation=2,
        old_uid="old",
        new_uid="new",
        worker_thread=123,
    ) is False


def test_wait_prompt_missing_waits_and_duplicate_fails(monkeypatch):
    calls = []

    def missing_then_ready(owner):
        calls.append(1)
        if len(calls) == 1:
            return {"ready": False, "reason": "prompt_missing"}
        return {"ready": True, "reason": None, "identity": {}}

    monkeypatch.setattr(verifier, "_prompt_observe", missing_then_ready)
    assert verifier._wait_for_prompt_identity(object(), 0.2)["ready"] is True
    assert len(calls) >= 2

    monkeypatch.setattr(
        verifier,
        "_prompt_observe",
        lambda owner: {"ready": False, "reason": "prompt_duplicate"},
    )
    result = verifier._wait_for_prompt_identity(object(), 0.2)
    assert result["ready"] is False
    assert result["reason"] == "prompt_duplicate"


def test_adoption_store_identities_issue_get_and_reset():
    from app.local import ai_adoption, weekly_ai_adoption

    try:
        identities, before = verifier._issue_adoption_store_identities()
        assert before is True
        live = verifier._adoption_store_identities_retired(identities)
        assert live == {"daily_retired": False, "weekly_retired": False}
        ai_adoption.reset_tokens()
        weekly_ai_adoption.reset_tokens()
        retired = verifier._adoption_store_identities_retired(identities)
        assert retired == {"daily_retired": True, "weekly_retired": True}
    finally:
        ai_adoption.reset_tokens()
        weekly_ai_adoption.reset_tokens()


def test_fault_evidence_reads_actual_kind_and_generation_without_nonce():
    recovery = SimpleNamespace(
        _lock=threading.RLock(),
        _fault=SimpleNamespace(
            kind="RenderProcessExited", generation=7, nonce="secret-nonce"
        ),
    )
    evidence = verifier._fault_evidence(recovery)
    assert evidence == {"kind": "RenderProcessExited", "generation": 7}
    assert "nonce" not in evidence


def test_wait_prompt_handle_failure_is_distinct(monkeypatch):
    def boom(owner):
        raise verifier.PromptHandleError("conversion")

    monkeypatch.setattr(verifier, "_prompt_observe", boom)
    result = verifier._wait_for_prompt_identity(object(), 0.2)
    assert result == {"ready": False, "reason": "handle_conversion_failed"}


def test_owner_native_close_uses_sc_close_not_keyboard(monkeypatch):
    calls = []

    class _FakeUser32:
        def GetWindowThreadProcessId(self, hwnd, pid_ref):
            pid_ref._obj.value = os.getpid()
            return 1

        def PostMessageW(self, hwnd, message, wparam, lparam):
            calls.append((hwnd, message, wparam, lparam))
            return 1

    monkeypatch.setattr(verifier, "_user32", _FakeUser32())
    result = verifier._owner_native_close(SimpleNamespace(Handle=123))
    assert result == {
        "ok": True,
        "reason": None,
        "method": "owner_wm_syscommand_sc_close",
        "keyboard": False,
        "native_close": True,
        "hwnd": 123,
        "pid": os.getpid(),
    }
    assert calls == [(123, verifier._WM_SYSCOMMAND, verifier._SC_CLOSE, 0)]

    class _RejectedUser32(_FakeUser32):
        def PostMessageW(self, hwnd, message, wparam, lparam):
            return 0

    monkeypatch.setattr(verifier, "_user32", _RejectedUser32())
    rejected = verifier._owner_native_close(SimpleNamespace(Handle=123))
    assert rejected["ok"] is False
    assert rejected["reason"] == "postmessage_failed"

    class _WrongPidUser32(_FakeUser32):
        def GetWindowThreadProcessId(self, hwnd, pid_ref):
            pid_ref._obj.value = os.getpid() + 1
            return 1

    monkeypatch.setattr(verifier, "_user32", _WrongPidUser32())
    mismatch = verifier._owner_native_close(SimpleNamespace(Handle=123))
    assert mismatch["ok"] is False
    assert mismatch["reason"] == "owner_pid_mismatch"


def test_prompt_wait_activates_at_most_once_then_read_only(monkeypatch):
    calls = []

    class _FakeUser32:
        def SetForegroundWindow(self, hwnd):
            calls.append(hwnd)
            return 0

    monkeypatch.setattr(verifier, "_user32", _FakeUser32())
    monkeypatch.setattr(
        verifier,
        "_prompt_observe",
        lambda owner: {
            "ready": False,
            "reason": "foreground",
            "identity": {"hwnd": 123},
        },
    )
    result = verifier._wait_for_prompt_identity(object(), 0.12)
    assert calls == [123]
    assert result["activation"]["attempted"] is True
    assert result["activation"]["before"] == {"hwnd": 123}
    assert result["activation"]["after"] == {"hwnd": 123}


def test_controlled_failure_retire_orders_private_cleanup():
    calls = []

    class _Recovery:
        def mark_expected_close(self):
            calls.append("mark_expected_close")

    class _Host:
        def _request_retire_destroy(self):
            calls.append("request_retire_destroy")

    class _Window:
        def destroy(self):
            calls.append("destroy")

    bundle = SimpleNamespace(host_api=_Host())
    cleanup = verifier._controlled_retire_failure(
        _Recovery(), bundle, _Window()
    )
    assert cleanup["steps"] == [
        "mark_expected_close",
        "request_retire_destroy",
        "destroy",
    ]
    assert calls == [
        "mark_expected_close",
        "request_retire_destroy",
        "destroy",
    ]

    class _BrokenRecovery:
        def mark_expected_close(self):
            raise RuntimeError("synthetic")

    calls.clear()
    cleanup = verifier._controlled_retire_failure(
        _BrokenRecovery(), bundle, _Window()
    )
    assert cleanup["steps"][0] == "mark_expected_close_failed"
    assert calls == ["request_retire_destroy", "destroy"]


class _FakeEvent:
    def __init__(self) -> None:
        self._items = []
        self._set = False

    def __iadd__(self, item):
        self._items.append(item)
        return self

    def set(self) -> None:
        self._set = True
        for item in list(self._items):
            item()

    def is_set(self) -> bool:
        return self._set


class _FakeWindow:
    def __init__(self, uid: str) -> None:
        self.uid = uid
        self.native = SimpleNamespace(IsDisposed=False, Visible=True)
        self.events = SimpleNamespace(closed=_FakeEvent())
        self.destroyed = False

    def destroy(self) -> None:
        self.destroyed = True
        self.native.IsDisposed = True
        self.native.Visible = False
        self.events.closed.set()


class _FakeAdapter:
    def __init__(self) -> None:
        self.prompts = 0

    def install_renderer_watcher(self, window, on_failure, log=None):
        return SimpleNamespace(close=lambda: None)

    def prompt_reopen(self, window) -> bool:
        self.prompts += 1
        return self.prompts >= 2

    def notify_reopen_blocked(self, window, code) -> None:
        return None


def _context_get(port: int, token: str):
    import http.client
    import json

    connection = http.client.HTTPConnection("127.0.0.1", int(port), timeout=3)
    try:
        connection.request(
            "GET",
            "/api/local/context",
            headers={
                "Host": f"127.0.0.1:{int(port)}",
                "Origin": f"http://127.0.0.1:{int(port)}",
                "X-App-Session": token,
            },
        )
        response = connection.getresponse()
        body = response.read()
        return int(response.status), json.loads(body)
    finally:
        connection.close()


def test_real_coordinator_reopen_sequencer_contract_without_window(tmp_path):
    """Source-service/coordinator contract only.

    The native adapter and both windows are explicit test doubles; this test
    never creates a real window, WebView, prompt, page or UI input.  It does
    not claim GUI, pixel, keyboard or frozen-package evidence.
    """
    import json
    import secrets
    import uuid

    from app.local.ai_executor import AiExecutor
    from app.local.runtime import LocalRuntime
    from sqlalchemy import text
    from tests.local import backup_fixture_support as fixture

    import d1_host_api
    import d1_main
    import d1_server
    import maintenance_lifecycle
    import renderer_recovery

    report_path = tmp_path / "headless-report.json"
    assert not report_path.exists()
    assert report_path.parent == tmp_path
    assert not report_path.is_relative_to(tmp_path / "data")
    assert not report_path.is_relative_to(tmp_path / "credentials")

    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "d1.html").write_text("<!doctype html><html></html>", encoding="utf-8")
    runtime = LocalRuntime(
        str(tmp_path / "data"), credential_root=str(tmp_path / "credentials")
    )
    runtime.prepare()
    runtime.launch_id = str(uuid.uuid4())
    evidence = fixture.seed_existing_runtime(runtime)
    old_executor = AiExecutor(runtime)
    assert old_executor.start() is True
    runtime.ai_executor = old_executor
    old_port = d1_main.free_loopback_port()
    old_token = secrets.token_urlsafe(32)
    old_app = d1_server.build_d1_app(
        runtime=runtime,
        port=old_port,
        session_token=old_token,
        frontend_dir=frontend,
        executor=old_executor,
    )
    old_service = d1_main.ServiceRun(old_app, old_port)
    assert old_service.start_and_wait() is True
    old_host = d1_host_api.D1HostApi(
        launch_token=old_token,
        service_port=old_port,
        document_generation=1,
        maintenance_notice=None,
        weekly_export_manager=getattr(old_app.state, "weekly_export_manager", None),
    )
    old_window = _FakeWindow("old-window")
    old_host._bind_window(old_window)
    lifecycle = maintenance_lifecycle.LifecycleManager()
    old_generation = lifecycle.next_generation()
    old_bundle = maintenance_lifecycle.LifecycleBundle(
        generation=old_generation,
        service=old_service,
        host_api=old_host,
        runtime=runtime,
        window=old_window,
        executor=old_executor,
    )
    old_bundle.retire_destroy = old_window.destroy
    lifecycle.install(old_bundle)
    old_bootstrap = old_host.get_bootstrap()
    old_ticket = old_bootstrap["page_ticket"]
    old_launch = old_bootstrap["launch_token"]
    assert old_host.page_ready(
        {
            "bridge_protocol": d1_host_api.BRIDGE_PROTOCOL,
            "page_ticket": old_ticket,
        }
    )["accepted"] is True
    assert old_host.page_business_ready({"page_ticket": old_ticket})[
        "accepted"
    ] is True
    assert old_host._wait_business_ready(1.0) is True
    old_state = verifier._host_page_state(old_host)
    assert verifier._active_page(old_state) is True
    assert old_launch
    old_port_status = verifier._readonly_status(old_port, old_launch)
    assert old_port_status == 200
    old_snapshot = old_executor.active_snapshot()
    worker_was_absent = bool(
        not old_snapshot["attempt_in_flight"]
        and not old_snapshot["pending_persist"]
        and not old_snapshot["unconfirmed"]
    )
    assert worker_was_absent is True

    before_default = fixture.runtime_fingerprint(runtime)
    before_full = fixture.runtime_fingerprint(runtime, include_runtime_fields=True)
    assert len(before_default["database"]["tables"]) == 49
    assert before_default["resources"]["file_count"] == 12
    weekly_token, weekly_kwargs = verifier._issue_weekly_identity(
        runtime, evidence.profile_id
    )
    adoption_identities, adoption_before = (
        verifier._issue_adoption_store_identities()
    )
    assert adoption_before is True
    old_engine = runtime.engine
    held_session = runtime.session()
    held_session.execute(text("SELECT 1")).scalar_one()
    old_lock_handle = runtime._lock_handle
    second_before = verifier._second_runtime_refused(runtime)
    assert second_before["refused"] is True
    assert second_before["error_code"] == "LOCAL_APP_ALREADY_RUNNING"

    observer = verifier._RecoveryObserver()
    old_uid = "old-window"
    new_state: dict = {}

    def record_old_closed():
        observer.record(
            "old_window.closed",
            window_uid=old_uid,
            host_label="old-host",
            bundle_label="old-bundle",
            generation=old_generation,
            detail={"closed": True},
        )

    old_window.events.closed += record_old_closed

    original_stop = old_executor.stop_if_idle

    def observed_stop(*, owner, timeout=5.0):
        thread = old_executor._thread
        was_alive = bool(thread is not None and thread.is_alive())
        before = verifier._executor_gate_snapshot(old_executor)
        observer.record(
            "old_stop_if_idle.enter",
            window_uid=old_uid,
            host_label="old-host",
            bundle_label="old-bundle",
            generation=old_generation,
            detail={"thread_was_alive": was_alive},
        )
        returned = original_stop(owner=owner, timeout=timeout)
        after = verifier._executor_gate_snapshot(old_executor)
        observer.record(
            "old_stop_if_idle.return",
            window_uid=old_uid,
            host_label="old-host",
            bundle_label="old-bundle",
            generation=old_generation,
            detail={
                "return": bool(returned),
                "thread_alive_after": bool(
                    thread is not None and thread.is_alive()
                ),
                "gate_ok": verifier._executor_gate_ok(after),
            },
        )
        return returned

    old_executor.stop_if_idle = observed_stop

    original_stop_service = old_service.stop_and_confirm
    service_thread = old_service.thread

    def observed_stop_service(timeout=10.0):
        was_alive = bool(
            service_thread is not None and service_thread.is_alive()
        )
        observer.record(
            "old_service_stop.enter",
            window_uid=old_uid,
            host_label="old-host",
            bundle_label="old-bundle",
            generation=old_generation,
            detail={"thread_was_alive": was_alive},
        )
        returned = original_stop_service(timeout)
        observer.record(
            "old_service_stop.return",
            window_uid=old_uid,
            host_label="old-host",
            bundle_label="old-bundle",
            generation=old_generation,
            detail={
                "return": bool(returned),
                "thread_alive_after": bool(
                    service_thread is not None and service_thread.is_alive()
                ),
            },
        )
        return returned

    old_service.stop_and_confirm = observed_stop_service

    original_retire = old_host._retire
    retire_calls = {"count": 0}

    def observed_retire():
        retire_calls["count"] += 1
        first = retire_calls["count"] == 1
        phase = "old_host_retire" if first else "old_host_retire_idempotent"
        before_state = verifier._host_page_state(old_host)
        observer.record(
            f"{phase}.enter",
            window_uid=old_uid,
            host_label="old-host",
            bundle_label="old-bundle",
            generation=old_generation,
            detail={
                "call_index": retire_calls["count"],
                "first": first,
                "retired": bool(before_state.get("retired")),
            },
        )
        returned = original_retire()
        after_state = verifier._host_page_state(old_host)
        observer.record(
            f"{phase}.return",
            window_uid=old_uid,
            host_label="old-host",
            bundle_label="old-bundle",
            generation=old_generation,
            detail={
                "call_index": retire_calls["count"],
                "first": first,
                "retired": bool(after_state.get("retired")),
                "page_ready": bool(after_state.get("page_ready")),
            },
        )
        return returned

    old_host._retire = observed_retire

    original_close_engine = runtime.close_engine_keep_lock

    def observed_close_engine():
        observer.record(
            "engine_close.enter",
            window_uid=old_uid,
            host_label="old-host",
            bundle_label="old-bundle",
            generation=old_generation,
        )
        returned = original_close_engine()
        observer.record(
            "engine_close.return",
            window_uid=old_uid,
            host_label="old-host",
            bundle_label="old-bundle",
            generation=old_generation,
            detail={
                "lock_ok": verifier._lock_ok(
                    verifier._lock_snapshot(runtime, old_lock_handle)
                )
            },
        )
        return returned

    runtime.close_engine_keep_lock = observed_close_engine
    original_reopen_engine = runtime.reopen_after_restore

    def observed_reopen_engine():
        observer.record(
            "engine_reopen.enter",
            window_uid=old_uid,
            host_label="old-host",
            bundle_label="old-bundle",
            generation=old_generation,
        )
        returned = original_reopen_engine()
        observer.record(
            "engine_reopen.return",
            window_uid=old_uid,
            host_label="old-host",
            bundle_label="old-bundle",
            generation=old_generation,
            detail={
                "lock_ok": verifier._lock_ok(
                    verifier._lock_snapshot(runtime, old_lock_handle)
                )
            },
        )
        return returned

    runtime.reopen_after_restore = observed_reopen_engine

    def build_bundle(_old):
        generation = lifecycle.next_generation()
        port = d1_main.free_loopback_port()
        token = secrets.token_urlsafe(32)
        new_executor = AiExecutor(runtime)
        assert new_executor.start() is True
        runtime.ai_executor = new_executor
        app = d1_server.build_d1_app(
            runtime=runtime,
            port=port,
            session_token=token,
            frontend_dir=frontend,
            executor=new_executor,
        )
        host = d1_host_api.D1HostApi(
            launch_token=token,
            service_port=port,
            document_generation=generation,
            maintenance_notice=renderer_recovery.RECOVERY_NOTICE,
            weekly_export_manager=getattr(
                app.state, "weekly_export_manager", None
            ),
        )
        service = d1_main.ServiceRun(app, port)
        new_state["token"] = token
        return maintenance_lifecycle.LifecycleBundle(
            generation=generation,
            service=service,
            host_api=host,
            runtime=runtime,
            executor=new_executor,
        )

    def create_window(bundle):
        window = _FakeWindow("new-window")
        bundle.window = window
        bundle.host_api._bind_window(window)
        bundle.retire_destroy = window.destroy

    def wait_business_ready(bundle, timeout):
        status, body = _context_get(
            bundle.service.port, bundle.host_api._launch_token
        )
        assert status == 200
        assert isinstance(body, dict) and body
        bootstrap = bundle.host_api.get_bootstrap()
        ticket = bootstrap["page_ticket"]
        assert bundle.host_api.page_ready(
            {
                "bridge_protocol": d1_host_api.BRIDGE_PROTOCOL,
                "page_ticket": ticket,
            }
        )["accepted"] is True
        assert bundle.host_api.page_business_ready(
            {"page_ticket": ticket}
        )["accepted"] is True
        return bool(bundle.host_api._wait_business_ready(timeout))

    original_install = lifecycle.install_if_current

    def wrap_new_service(bundle):
        original_start = bundle.service.start_and_wait

        def observed_start():
            observer.record(
                "new_service.start.enter",
                window_uid=None,
                host_label="new-host",
                bundle_label="new-bundle",
                generation=bundle.generation,
            )
            started = bool(original_start())
            observer.record(
                "new_service.start.return",
                window_uid=None,
                host_label="new-host",
                bundle_label="new-bundle",
                generation=bundle.generation,
                detail={"started": started},
            )
            return started

        bundle.service.start_and_wait = observed_start

    def wrap_new_wait(bundle):
        original_wait = bundle.host_api._wait_business_ready

        def observed_wait(timeout):
            observer.record(
                "new_business_ready.enter",
                window_uid=verifier._window_uid(bundle.window),
                host_label="new-host",
                bundle_label="new-bundle",
                generation=bundle.generation,
            )
            ready = bool(original_wait(timeout))
            state = verifier._host_page_state(bundle.host_api)
            observer.record(
                "new_business_ready.return",
                window_uid=verifier._window_uid(bundle.window),
                host_label="new-host",
                bundle_label="new-bundle",
                generation=bundle.generation,
                detail={
                    "ready": ready,
                    "business_ready": bool(state.get("business_ready")),
                },
            )
            return ready

        bundle.host_api._wait_business_ready = observed_wait

    def observed_install(expected, current_bundle):
        observer.record(
            "new_bundle.install_cas.enter",
            window_uid=None,
            host_label="new-host",
            bundle_label="new-bundle",
            generation=current_bundle.generation,
            detail={"expected_is_old": expected is old_bundle},
        )
        installed = bool(original_install(expected, current_bundle))
        observer.record(
            "new_bundle.install_cas.return",
            window_uid=None,
            host_label="new-host",
            bundle_label="new-bundle",
            generation=current_bundle.generation,
            detail={"installed": installed},
        )
        if installed:
            wrap_new_service(current_bundle)
            wrap_new_wait(current_bundle)
        return installed

    lifecycle.install_if_current = observed_install

    original_old_destroy = old_bundle.retire_destroy

    def observed_old_destroy():
        current = lifecycle.current()
        current_host = getattr(current, "host_api", None)
        current_executor = getattr(current, "executor", None)
        state = verifier._host_page_state(current_host)
        observer.record(
            "old_destroy.enter",
            window_uid=old_uid,
            host_label="old-host",
            bundle_label="old-bundle",
            generation=old_generation,
            detail={
                "old_form_alive_before": not old_window.native.IsDisposed,
                "new_business_ready": bool(state.get("business_ready")),
                "new_window_visible": verifier._window_visible(current.window),
                "new_document_generation": state.get("document_generation"),
                "fresh_executor_ok": verifier._fresh_executor_ok(
                    current_executor, old_executor, current, runtime
                ),
            },
        )
        original_old_destroy()
        observer.record(
            "old_destroy.return",
            window_uid=old_uid,
            host_label="old-host",
            bundle_label="old-bundle",
            generation=old_generation,
            detail={"old_form_alive_after": not old_window.native.IsDisposed},
        )

    old_bundle.retire_destroy = observed_old_destroy

    sequencer = maintenance_lifecycle.ReopenSequencer(
        manager=lifecycle,
        old_bundle=old_bundle,
        build_bundle=build_bundle,
        create_window=create_window,
        wait_business_ready=wait_business_ready,
        timeout=5.0,
        expected_current=old_bundle,
        manual_reopen=True,
    )

    recovery = renderer_recovery.install_renderer_recovery(
        window=old_window,
        host_api=old_host,
        lifecycle=lifecycle,
        bundle=old_bundle,
        runtime=runtime,
        reopen_sequence=lambda: sequencer.run(),
        adapter=_FakeAdapter(),
    )
    report = None
    try:
        recovery._on_native_failure("RenderProcessExited")
        assert recovery._worker_done.wait(5.0) is True
        assert recovery.state == recovery.KEPT
        assert recovery.intercept_native_close() is True
        recovery_worker = recovery._worker
        assert recovery_worker is not None
        assert recovery_worker.ident is not None
        assert recovery_worker.is_alive() is True
        recovery_worker_thread = int(recovery_worker.ident)
        assert recovery._worker_done.wait(10.0) is True
        assert recovery.state == recovery.RECOVERED
        new_bundle = lifecycle.current()
        assert new_bundle is not old_bundle
        new_executor = getattr(new_bundle, "executor", None)
        fresh_executor_ok = verifier._fresh_executor_ok(
            new_executor, old_executor, new_bundle, runtime
        )
        assert fresh_executor_ok is True
        assert new_executor is not old_executor
        new_host = new_bundle.host_api
        new_state_page = verifier._host_page_state(new_host)
        assert verifier._active_page(new_state_page) is True
        assert old_window.destroyed is True
        assert old_window.native.IsDisposed is True

        before_submission = verifier._host_page_state(new_host)
        submission = new_host.page_business_ready({"page_ticket": old_ticket})
        after_submission = verifier._host_page_state(new_host)
        assert submission["accepted"] is False
        assert before_submission == after_submission

        new_port = int(new_bundle.service.port)
        new_old_status = verifier._readonly_status(new_port, old_launch)
        new_new_status = verifier._readonly_status(
            new_port, new_state["token"]
        )
        assert new_old_status == 401
        assert new_new_status == 200

        old_engine_rejected = False
        try:
            old_engine.connect()
        except RuntimeError:
            old_engine_rejected = True
        else:
            raise AssertionError("old engine reconnect unexpectedly succeeded")
        old_session_rejected = False
        try:
            held_session.execute(text("SELECT 1"))
        except RuntimeError:
            old_session_rejected = True
        else:
            raise AssertionError("old session unexpectedly remained usable")
        new_engine_select_ok = False
        with runtime.engine.connect() as connection:
            connection.execute(text("SELECT 1")).scalar_one()
            new_engine_select_ok = True
        new_session_select_ok = False
        new_session = runtime.session()
        try:
            new_session.execute(text("SELECT 1")).scalar_one()
            new_session_select_ok = True
        finally:
            new_session.close()

        lock_after = verifier._lock_snapshot(runtime, old_lock_handle)
        assert verifier._lock_ok(lock_after) is True
        second_after = verifier._second_runtime_refused(runtime)
        assert second_after["refused"] is True
        assert second_after["error_code"] == "LOCAL_APP_ALREADY_RUNNING"

        weekly_after = verifier._weekly_identity_rejected(
            runtime, weekly_token, weekly_kwargs
        )
        assert weekly_after["rejected"] is True
        assert weekly_after["error_type"] == "LocalWeeklyPreviewStale"
        adoption_after = verifier._adoption_store_identities_retired(
            adoption_identities
        )
        assert adoption_after == {
            "daily_retired": True,
            "weekly_retired": True,
        }

        after_default = fixture.runtime_fingerprint(runtime)
        after_full = fixture.runtime_fingerprint(
            runtime, include_runtime_fields=True
        )
        assert after_default == before_default == evidence.fingerprint
        assert after_full == before_full
        fixture.validate_fixture(runtime, evidence)
        assert (
            after_default["database"]["tables"]
            == before_default["database"]["tables"]
        )
        for count_name in (
            "local_ai_tasks",
            "local_ai_executions",
            "local_ai_attempts",
        ):
            assert evidence.counts[count_name] == 4
            assert before_default["database"]["counts"][count_name] == 4
            assert after_default["database"]["counts"][count_name] == 4

        events = observer.snapshot()
        event_sequence_ok = verifier._event_sequence_ok(
            events,
            old_generation=old_generation,
            new_generation=new_bundle.generation,
            old_uid=old_uid,
            new_uid=verifier._window_uid(new_bundle.window),
            worker_thread=recovery_worker_thread,
        )
        assert event_sequence_ok is True

        by_phase = {event["phase"]: event for event in events}
        old_stop_enter = by_phase["old_stop_if_idle.enter"]["detail"]
        old_stop_return = by_phase["old_stop_if_idle.return"]["detail"]
        old_service_enter = by_phase["old_service_stop.enter"]["detail"]
        old_service_return = by_phase["old_service_stop.return"]["detail"]
        assert old_stop_enter["thread_was_alive"] is True
        assert old_stop_return["return"] is True
        assert old_stop_return["thread_alive_after"] is False
        assert old_stop_return["gate_ok"] is True
        assert old_service_enter["thread_was_alive"] is True
        assert old_service_return["return"] is True
        assert old_service_return["thread_alive_after"] is False

        report = {
            "format": 1,
            "kind": "renderer_recovery_headless_coordinator_contract",
            "headless_only": True,
            "real_window": False,
            "real_webview": False,
            "real_ui_input": False,
            "old_window_double": True,
            "new_window_double": True,
            "adapter_double": True,
            "old_window_label": old_uid,
            "new_window_label": verifier._window_uid(new_bundle.window),
            "old_generation": old_generation,
            "new_generation": int(new_bundle.generation),
            "recovery_worker_thread": recovery_worker_thread,
            "old_port": old_port,
            "old_port_token_status": old_port_status,
            "new_port": new_port,
            "new_port_old_token_status": new_old_status,
            "new_port_new_token_status": new_new_status,
            "old_executor_thread_was_alive": old_stop_enter[
                "thread_was_alive"
            ],
            "old_executor_thread_alive_after": old_stop_return[
                "thread_alive_after"
            ],
            "old_executor_stop_return": old_stop_return["return"],
            "old_executor_gate_ok": old_stop_return["gate_ok"],
            "old_service_thread_was_alive": old_service_enter[
                "thread_was_alive"
            ],
            "old_service_thread_alive_after": old_service_return[
                "thread_alive_after"
            ],
            "old_service_stop_return": old_service_return["return"],
            "fresh_executor_ok": fresh_executor_ok,
            "old_engine_rejected": old_engine_rejected,
            "old_session_rejected": old_session_rejected,
            "new_engine_select_ok": new_engine_select_ok,
            "new_session_select_ok": new_session_select_ok,
            "root_lock_ok_after_recovery": verifier._lock_ok(lock_after),
            "root_second_refused_before_recovery": second_before["refused"],
            "root_second_code_before_recovery": second_before["error_code"],
            "root_second_refused_after_recovery": second_after["refused"],
            "root_second_code_after_recovery": second_after["error_code"],
            "weekly_identity_rejected": weekly_after["rejected"],
            "weekly_error_type": weekly_after["error_type"],
            "adoption_store_retired": adoption_after,
            "worker_absent_before_fault": worker_was_absent,
            "fixture_counts": {
                "local_ai_tasks": evidence.counts["local_ai_tasks"],
                "local_ai_executions": evidence.counts[
                    "local_ai_executions"
                ],
                "local_ai_attempts": evidence.counts["local_ai_attempts"],
            },
            "fixture_fingerprint_default_before": before_default,
            "fixture_fingerprint_default_after": after_default,
            "fixture_fingerprint_runtime_before": before_full,
            "fixture_fingerprint_runtime_after": after_full,
            "default_fingerprint_equal": (
                after_default == before_default == evidence.fingerprint
            ),
            "runtime_fingerprint_equal": after_full == before_full,
            "events": events,
            "event_sequence_ok": event_sequence_ok,
            "completed": True,
            "held_session_closed": None,
            "close_latest_confirmed": None,
            "close_latest_error_type": None,
            "root_lock_released_after_close": None,
            "ownership_preserved_on_failure": None,
        }
    finally:
        held_session_closed = False
        try:
            held_session.close()
            held_session_closed = True
        except Exception:
            held_session_closed = False
        close_latest_confirmed = False
        close_latest_error_type = None
        try:
            close_latest_confirmed = bool(lifecycle.close_latest(timeout=10.0))
        except Exception as exc:  # noqa: BLE001 - safe type only
            close_latest_error_type = type(exc).__name__
        root_lock_released_after_close = bool(
            getattr(runtime, "_lock_handle", None) is None
            and getattr(runtime, "_owns_lock", False) is False
        )
        if report is not None:
            report["held_session_closed"] = held_session_closed
            report["close_latest_confirmed"] = close_latest_confirmed
            report["close_latest_error_type"] = close_latest_error_type
            report["root_lock_released_after_close"] = (
                root_lock_released_after_close
            )
            report["ownership_preserved_on_failure"] = (
                not close_latest_confirmed
            )
            report_path.write_text(
                json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2),
                encoding="utf-8",
            )
        assert close_latest_confirmed is True, (
            "lifecycle.close_latest did not confirm resource closure"
        )
        assert root_lock_released_after_close is True, (
            "runtime root lock remained held after confirmed close"
        )


def test_fresh_executor_gate_rejects_same_or_wrong_owner():
    old = object()
    new = object()
    runtime = SimpleNamespace(ai_executor=new)
    bundle = SimpleNamespace(executor=new)
    assert verifier._fresh_executor_ok(new, old, bundle, runtime) is True
    assert verifier._fresh_executor_ok(None, old, bundle, runtime) is False
    assert verifier._fresh_executor_ok(old, old, bundle, runtime) is False
    assert verifier._fresh_executor_ok(
        new, old, SimpleNamespace(executor=old), runtime
    ) is False
    assert verifier._fresh_executor_ok(
        new, old, bundle, SimpleNamespace(ai_executor=old)
    ) is False


def test_synthetic_output_inside_data_is_rejected_before_mkdir(tmp_path):
    data = tmp_path / "data"
    credential = tmp_path / "credentials"
    output = data / "result.json"
    with pytest.raises(ValueError, match="overlap"):
        verifier._validate_synthetic_paths(data, credential, output)
    assert not data.exists()
    assert not credential.exists()
