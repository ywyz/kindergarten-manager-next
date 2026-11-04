"""Focused tests for the native renderer-failure adapter.

No WinForms/WebView2 window is created here.  The fake form/control/core event
objects exercise the adapter's exact identity, UI marshalling, filtering,
deduplication, close, prompt and safe-error branches deterministically.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import renderer_recovery_native as mod

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Fake native objects
# ---------------------------------------------------------------------------


class FakeEvent:
    def __init__(self) -> None:
        self.handlers: list = []
        self._set = False

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def __isub__(self, handler):
        self.handlers.remove(handler)
        return self

    def fire(self, *args) -> None:
        for handler in list(self.handlers):
            handler(*args)

    def set(self, *args) -> None:
        self._set = True

    def clear(self) -> None:
        self._set = False

    def is_set(self) -> bool:
        return self._set


class FakeCore:
    def __init__(self) -> None:
        self.ProcessFailed = FakeEvent()


class FakeWebView:
    def __init__(self, core: FakeCore | None = None) -> None:
        self.CoreWebView2 = core
        self.CoreWebView2InitializationCompleted = FakeEvent()


class FakeForm:
    def __init__(self, webview: FakeWebView | None = None) -> None:
        self.webview = webview
        self.browser = SimpleNamespace(webview=webview)
        self.FormClosed = FakeEvent()
        self.InvokeRequired = False
        self.IsDisposed = False
        self.Disposing = False
        self.IsHandleCreated = True
        self.invoke_calls: list = []
        self.begin_calls: list = []

    def Invoke(self, delegate):
        self.invoke_calls.append(delegate)
        return delegate()

    def BeginInvoke(self, delegate):
        self.begin_calls.append(delegate)
        return delegate()


class FakeWindow:
    def __init__(self) -> None:
        self.native = None
        self.events = SimpleNamespace(
            shown=FakeEvent(),
            initialized=FakeEvent(),
            closing=FakeEvent(),
            closed=FakeEvent(),
        )


class FakeKind:
    def __init__(self, name: str) -> None:
        self.name = name

    def ToString(self) -> str:
        return self.name


class FakeProcessArgs:
    def __init__(self, kind: str) -> None:
        self.ProcessFailedKind = FakeKind(kind)


class FakeInitArgs:
    def __init__(self, success: bool) -> None:
        self.IsSuccess = success


def ready_window():
    core = FakeCore()
    webview = FakeWebView(core)
    form = FakeForm(webview)
    window = FakeWindow()
    window.native = form
    return window, form, webview, core


@pytest.fixture
def native_fakes(monkeypatch):
    """Keep the adapter on pure Python delegates and fake events."""
    monkeypatch.setattr(mod, "_make_event_handler", lambda _kind, callback: callback)
    monkeypatch.setattr(mod, "_make_action", lambda callback: callback)
    monkeypatch.setattr(mod, "_make_func_bool", lambda callback: callback)


# ---------------------------------------------------------------------------
# Watcher: binding, filtering, dedupe, identity
# ---------------------------------------------------------------------------


def test_ready_core_filters_nonfatal_and_deduplicates(native_fakes):
    window, form, _webview, core = ready_window()
    seen: list[str] = []
    fired = threading.Event()

    def callback(kind: str) -> None:
        seen.append(kind)
        fired.set()

    watcher = mod.install_renderer_watcher(window, callback)
    try:
        assert len(core.ProcessFailed.handlers) == 1
        assert len(form.FormClosed.handlers) == 1

        for kind in (
            "GpuProcessExited",
            "FrameRenderProcessExited",
            "RenderProcessUnresponsive",
            "UnknownProcessExited",
        ):
            core.ProcessFailed.fire(core, FakeProcessArgs(kind))
            assert not fired.is_set()

        core.ProcessFailed.fire(core, FakeProcessArgs("RenderProcessExited"))
        assert fired.wait(5)
        assert seen == ["RenderProcessExited"]

        core.ProcessFailed.fire(core, FakeProcessArgs("BrowserProcessExited"))
        assert seen == ["RenderProcessExited"]

        watcher.close()
        assert core.ProcessFailed.handlers == []
        assert form.FormClosed.handlers == []
    finally:
        watcher.close()


def test_browser_process_exit_is_fatal_when_window_is_alive(native_fakes):
    window, _form, _webview, core = ready_window()
    seen: list[str] = []
    fired = threading.Event()
    watcher = mod.install_renderer_watcher(
        window, lambda kind: (seen.append(kind), fired.set())
    )
    try:
        core.ProcessFailed.fire(core, FakeProcessArgs("BrowserProcessExited"))
        assert fired.wait(5)
        assert seen == ["BrowserProcessExited"]
    finally:
        watcher.close()


def test_latched_closing_after_denied_close_does_not_suppress_fatal(native_fakes):
    window, _form, _webview, core = ready_window()
    seen: list[str] = []
    fired = threading.Event()
    watcher = mod.install_renderer_watcher(
        window, lambda kind: (seen.append(kind), fired.set())
    )
    try:
        # A prior close was denied; pywebview's Event remains latched.  That
        # must not turn a later real renderer fault into an ignored event.
        window.events.closing.set()
        core.ProcessFailed.fire(core, FakeProcessArgs("RenderProcessExited"))
        assert fired.wait(5)
        assert seen == ["RenderProcessExited"]
        core.ProcessFailed.fire(core, FakeProcessArgs("RenderProcessExited"))
        assert seen == ["RenderProcessExited"]
    finally:
        watcher.close()


def test_closed_event_and_disposed_form_suppress_fatal(native_fakes):
    window, form, _webview, core = ready_window()
    seen: list[str] = []
    watcher = mod.install_renderer_watcher(window, lambda kind: seen.append(kind))
    try:
        window.events.closed.set()
        core.ProcessFailed.fire(core, FakeProcessArgs("RenderProcessExited"))
        assert seen == []

        window.events.closed.clear()
        form.IsDisposed = True
        core.ProcessFailed.fire(core, FakeProcessArgs("BrowserProcessExited"))
        assert seen == []

        form.IsDisposed = False
        core.ProcessFailed.fire(core, FakeProcessArgs("RenderProcessExited"))
        assert seen == ["RenderProcessExited"]
    finally:
        watcher.close()


def test_rcw_distinct_sender_on_exact_event_is_accepted(native_fakes):
    window, _form, _webview, core = ready_window()
    seen: list[str] = []
    fired = threading.Event()
    watcher = mod.install_renderer_watcher(
        window, lambda kind: (seen.append(kind), fired.set())
    )
    try:
        # WinForms/WebView2 may hand the event a different RCW wrapper for the
        # same managed CoreWebView2.  The exact event subscription is identity.
        core.ProcessFailed.fire(FakeCore(), FakeProcessArgs("RenderProcessExited"))
        assert fired.wait(5)
        assert seen == ["RenderProcessExited"]
    finally:
        watcher.close()


def test_other_core_event_does_not_reach_watcher(native_fakes):
    window, _form, _webview, core = ready_window()
    other = FakeCore()
    other_seen: list = []
    other.ProcessFailed += lambda *args: other_seen.append(args)
    seen: list[str] = []
    fired = threading.Event()
    watcher = mod.install_renderer_watcher(
        window, lambda kind: (seen.append(kind), fired.set())
    )
    try:
        other.ProcessFailed.fire(other, FakeProcessArgs("RenderProcessExited"))
        assert not fired.is_set()
        assert other_seen and len(other_seen) == 1
        core.ProcessFailed.fire(core, FakeProcessArgs("RenderProcessExited"))
        assert fired.wait(5)
        assert seen == ["RenderProcessExited"]
    finally:
        watcher.close()


# ---------------------------------------------------------------------------
# Watcher: init/shown races and marshalling
# ---------------------------------------------------------------------------


def test_init_before_shown_attaches_after_success(native_fakes):
    window = FakeWindow()
    seen: list[str] = []
    fired = threading.Event()
    watcher = mod.install_renderer_watcher(
        window, lambda kind: (seen.append(kind), fired.set())
    )
    try:
        assert len(window.events.shown.handlers) == 1
        assert len(window.events.initialized.handlers) == 1

        webview = FakeWebView(None)
        form = FakeForm(webview)
        window.native = form
        window.events.shown.fire()
        assert len(webview.CoreWebView2InitializationCompleted.handlers) == 1

        core = FakeCore()
        webview.CoreWebView2 = core
        # The init event sender may be a different RCW wrapper; bind through
        # the exact captured control rather than Python object identity.
        webview.CoreWebView2InitializationCompleted.fire(
            object(), FakeInitArgs(True)
        )
        assert len(core.ProcessFailed.handlers) == 1
        assert webview.CoreWebView2InitializationCompleted.handlers == []

        core.ProcessFailed.fire(core, FakeProcessArgs("RenderProcessExited"))
        assert fired.wait(5)
        assert seen == ["RenderProcessExited"]
    finally:
        watcher.close()


def test_core_already_ready_binds_without_waiting_for_shown(native_fakes):
    window, _form, webview, core = ready_window()
    watcher = mod.install_renderer_watcher(window, lambda _kind: None)
    try:
        assert len(core.ProcessFailed.handlers) == 1
        assert webview.CoreWebView2InitializationCompleted.handlers == []
        assert window.events.shown.handlers == []
    finally:
        watcher.close()


def test_initialization_failure_is_safe_and_not_a_fault(native_fakes):
    window = FakeWindow()
    webview = FakeWebView(None)
    form = FakeForm(webview)
    window.native = form
    logs: list[str] = []
    seen: list[str] = []
    watcher = mod.install_renderer_watcher(
        window, lambda kind: seen.append(kind), log=logs.append
    )
    try:
        assert len(webview.CoreWebView2InitializationCompleted.handlers) == 1
        webview.CoreWebView2InitializationCompleted.fire(
            webview, FakeInitArgs(False)
        )
        assert seen == []
        assert mod._LOG_INIT_FAILED in logs
        assert all("Exception" not in item for item in logs)
    finally:
        watcher.close()


def test_missing_handle_fails_closed_then_shown_retries(native_fakes):
    window, form, _webview, core = ready_window()
    form.IsHandleCreated = False
    watcher = mod.install_renderer_watcher(window, lambda _kind: None)
    try:
        assert core.ProcessFailed.handlers == []
        assert form.invoke_calls == []
        form.IsHandleCreated = True
        window.events.shown.fire()
        assert len(core.ProcessFailed.handlers) == 1
    finally:
        watcher.close()


def test_background_install_and_close_marshal_to_ui(native_fakes):
    window, form, _webview, core = ready_window()
    form.InvokeRequired = True
    watcher = mod.install_renderer_watcher(window, lambda _kind: None)
    try:
        assert len(form.invoke_calls) == 1
        assert len(core.ProcessFailed.handlers) == 1
        watcher.close()
        assert len(form.begin_calls) == 1
        assert core.ProcessFailed.handlers == []
        assert form.FormClosed.handlers == []
    finally:
        watcher.close()


# ---------------------------------------------------------------------------
# Watcher: callback and close edge cases
# ---------------------------------------------------------------------------


def test_callback_exception_is_contained_and_safe(native_fakes):
    window, _form, _webview, core = ready_window()
    logs: list[str] = []

    def callback(_kind: str) -> None:
        raise RuntimeError("SECRET C:/path/stack")

    watcher = mod.install_renderer_watcher(window, callback, log=logs.append)
    try:
        core.ProcessFailed.fire(core, FakeProcessArgs("RenderProcessExited"))
        assert mod._LOG_CALLBACK_FAILED in logs
        assert all("SECRET" not in item and "C:/path" not in item for item in logs)
        assert watcher.faulted is True
    finally:
        watcher.close()


def test_callback_reentry_can_close_without_deadlock(native_fakes):
    window, form, _webview, core = ready_window()
    holder: dict[str, object] = {}
    called = threading.Event()

    def callback(kind: str) -> None:
        holder["kind"] = kind
        holder["watcher"].close()
        called.set()

    watcher = mod.install_renderer_watcher(window, callback)
    holder["watcher"] = watcher
    try:
        core.ProcessFailed.fire(core, FakeProcessArgs("RenderProcessExited"))
        assert called.wait(5)
        assert holder["kind"] == "RenderProcessExited"
        assert watcher.closed is True
        assert core.ProcessFailed.handlers == []
        assert form.FormClosed.handlers == []
    finally:
        watcher.close()


def test_close_unsubscribes_exact_core_and_is_idempotent(native_fakes):
    window, form, _webview, core = ready_window()
    other = FakeCore()
    sentinel = lambda *args: None
    other.ProcessFailed += sentinel
    seen: list[str] = []
    watcher = mod.install_renderer_watcher(window, lambda kind: seen.append(kind))
    try:
        watcher.close()
        watcher.close()
        assert core.ProcessFailed.handlers == []
        assert form.FormClosed.handlers == []
        assert other.ProcessFailed.handlers == [sentinel]
        core.ProcessFailed.fire(core, FakeProcessArgs("RenderProcessExited"))
        assert seen == []
    finally:
        watcher.close()


def test_close_while_initializing_detaches_init_handler(native_fakes):
    window = FakeWindow()
    watcher = mod.install_renderer_watcher(window, lambda _kind: None)
    try:
        webview = FakeWebView(None)
        form = FakeForm(webview)
        window.native = form
        window.events.shown.fire()
        assert len(webview.CoreWebView2InitializationCompleted.handlers) == 1
        watcher.close()
        assert webview.CoreWebView2InitializationCompleted.handlers == []
        assert window.events.shown.handlers == []
        assert window.events.initialized.handlers == []

        core = FakeCore()
        webview.CoreWebView2 = core
        webview.CoreWebView2InitializationCompleted.fire(
            webview, FakeInitArgs(True)
        )
        assert core.ProcessFailed.handlers == []
    finally:
        watcher.close()


def test_invalid_window_is_a_safe_noop(native_fakes):
    logs: list[str] = []
    watcher = mod.install_renderer_watcher(None, lambda _kind: None, log=logs.append)
    try:
        assert mod._LOG_BIND_FAILED in logs
        assert watcher.closed is False
    finally:
        watcher.close()
    assert watcher.closed is True

    with pytest.raises(TypeError):
        mod.install_renderer_watcher(FakeWindow(), None)


# ---------------------------------------------------------------------------
# Fake WinForms prompt/notice layer
# ---------------------------------------------------------------------------


class FakePoint:
    def __init__(self, x: int, y: int) -> None:
        self.X = x
        self.Y = y


class FakeSize:
    def __init__(self, width: int, height: int) -> None:
        self.Width = width
        self.Height = height


class FakeControl:
    def __init__(self) -> None:
        self.Text = ""
        self.AccessibleName = ""
        self.AccessibleDescription = ""
        self.AutoSize = True
        self.Size = FakeSize(0, 0)
        self.bounds = None

    def SetBounds(self, x: int, y: int, width: int, height: int) -> None:
        self.bounds = (x, y, width, height)

    @property
    def ClientSize(self):
        return self.Size

    @ClientSize.setter
    def ClientSize(self, value):
        self.Size = value


class FakeLabel(FakeControl):
    pass


class FakeButton(FakeControl):
    def __init__(self) -> None:
        super().__init__()
        self.DialogResult = None


class FakeControlCollection:
    def __init__(self) -> None:
        self.items: list = []

    def Add(self, control) -> None:
        self.items.append(control)


class FakeDialog(FakeControl):
    instances: list["FakeDialog"] = []
    result = "OK"
    raise_error = False
    shown_owner = None

    def __init__(self) -> None:
        super().__init__()
        self.Controls = FakeControlCollection()
        self.ClientSize = None
        self.FormBorderStyle = None
        self.StartPosition = None
        self.MinimizeBox = True
        self.MaximizeBox = True
        self.ShowInTaskbar = True
        self.AcceptButton = None
        self.CancelButton = None
        self.ActiveControl = None
        FakeDialog.instances.append(self)

    def ShowDialog(self, owner):
        FakeDialog.shown_owner = owner
        if FakeDialog.raise_error:
            raise RuntimeError("SECRET /path/stack")
        return FakeDialog.result


class FakeMessageBox:
    calls: list = []
    raise_error = False

    @staticmethod
    def Show(owner, text, title, buttons, icon):
        FakeMessageBox.calls.append((owner, text, title, buttons, icon))
        if FakeMessageBox.raise_error:
            raise RuntimeError("SECRET /path/stack")
        return None


FakeWinForms = SimpleNamespace(
    Form=FakeDialog,
    Label=FakeLabel,
    Button=FakeButton,
    DialogResult=SimpleNamespace(OK="OK", Cancel="CANCEL", Yes="YES"),
    FormBorderStyle=SimpleNamespace(FixedDialog="FixedDialog"),
    FormStartPosition=SimpleNamespace(CenterParent="CenterParent"),
    MessageBoxButtons=SimpleNamespace(OK="OK"),
    MessageBoxIcon=SimpleNamespace(Information="Information"),
    MessageBox=FakeMessageBox,
)


@pytest.fixture
def fake_winforms(monkeypatch):
    FakeDialog.instances = []
    FakeDialog.result = FakeWinForms.DialogResult.OK
    FakeDialog.raise_error = False
    FakeDialog.shown_owner = None
    FakeMessageBox.calls = []
    FakeMessageBox.raise_error = False
    monkeypatch.setattr(
        mod, "_load_winforms", lambda: (FakeWinForms, FakePoint, FakeSize)
    )

    def measured(_control, text):
        if text == mod.REOPEN_TEXT:
            return 300, 24
        if text == mod.KEEP_TEXT:
            return 180, 24
        return 470, 24

    monkeypatch.setattr(mod, "_measure_text_size", measured)
    return FakeWinForms


def make_prompt_window():
    webview = FakeWebView(FakeCore())
    form = FakeForm(webview)
    window = FakeWindow()
    window.native = form
    return window, form


def test_prompt_only_first_button_true_and_exact_labels(fake_winforms):
    window, form = make_prompt_window()
    FakeDialog.result = fake_winforms.DialogResult.OK
    assert mod.prompt_reopen(window) is True
    assert FakeDialog.shown_owner is form
    snapshot = mod._last_prompt_snapshot()
    assert snapshot is not None
    assert snapshot["owner_present"] is True
    assert snapshot["owner_type"] == "FakeForm"
    assert "owner" not in snapshot
    assert snapshot["warning_text"] == mod.WARNING_TEXT
    assert snapshot["button_texts"] == (mod.REOPEN_TEXT, mod.KEEP_TEXT)
    assert snapshot["accessible_name"] == "页面已停止"
    assert snapshot["button_accessible_names"] == (
        mod.REOPEN_TEXT,
        mod.KEEP_TEXT,
    )
    assert snapshot["accept_button_text"] == mod.KEEP_TEXT
    assert snapshot["cancel_button_text"] == mod.KEEP_TEXT
    assert snapshot["active_control_text"] == mod.KEEP_TEXT
    assert snapshot["default_button_is_keep"] is True
    assert snapshot["cancel_button_is_keep"] is True
    assert snapshot["active_control_is_keep"] is True
    assert snapshot["default_button_text"] == mod.KEEP_TEXT
    assert len(FakeDialog.instances[-1].Controls.items) == 3
    dialog = FakeDialog.instances[-1]
    warning = dialog.Controls.items[0]
    reopen = next(
        control for control in dialog.Controls.items if control.Text == mod.REOPEN_TEXT
    )
    keep = next(
        control for control in dialog.Controls.items if control.Text == mod.KEEP_TEXT
    )
    # The approved long label must fit the actual text measurement; exact
    # hard-coded 250/190 sizes are deliberately not asserted.
    assert reopen.ClientSize.Width >= 300
    assert keep.ClientSize.Width >= 180
    assert reopen.Size.Width >= 300 + 40
    assert keep.Size.Width >= 180 + 40
    assert warning.bounds[2] >= 470
    assert dialog.ClientSize.Width >= 24 + reopen.Size.Width + 20 + keep.Size.Width + 24
    assert snapshot["button_sizes"] == (
        (reopen.Size.Width, reopen.Size.Height),
        (keep.Size.Width, keep.Size.Height),
    )


def test_prompt_keep_x_and_unknown_results_are_false(fake_winforms):
    window, _form = make_prompt_window()
    for result in (
        fake_winforms.DialogResult.Cancel,
        fake_winforms.DialogResult.Yes,
        "NOT_A_CHOICE",
    ):
        FakeDialog.result = result
        assert mod.prompt_reopen(window) is False


def test_prompt_unavailable_and_error_are_false(fake_winforms, monkeypatch, caplog):
    window = FakeWindow()
    assert mod.prompt_reopen(window) is False
    assert FakeDialog.instances == []

    window, form = make_prompt_window()
    form.IsDisposed = True
    assert mod.prompt_reopen(window) is False

    form.IsDisposed = False
    form.IsHandleCreated = False
    before = len(FakeDialog.instances)
    assert mod.prompt_reopen(window) is False
    assert len(FakeDialog.instances) == before

    form.IsHandleCreated = True
    FakeDialog.result = FakeWinForms.DialogResult.OK
    FakeDialog.raise_error = True
    with caplog.at_level(logging.WARNING, logger="renderer_recovery_native"):
        assert mod.prompt_reopen(window) is False
    assert any(mod._LOG_PROMPT_FAILED in record.message for record in caplog.records)
    assert all("SECRET" not in record.message for record in caplog.records)

    FakeDialog.raise_error = False
    monkeypatch.setattr(
        mod, "_load_winforms", lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    assert mod.prompt_reopen(window) is False


def test_prompt_background_marshals_to_ui(fake_winforms, native_fakes):
    window, form = make_prompt_window()
    form.InvokeRequired = True
    FakeDialog.result = fake_winforms.DialogResult.OK
    assert mod.prompt_reopen(window) is True
    assert len(form.invoke_calls) == 1
    assert FakeDialog.shown_owner is form


def test_notify_maps_fixed_text_and_hides_unknown_code(fake_winforms):
    window, form = make_prompt_window()
    mod.notify_reopen_blocked(window, "BUSY")
    assert len(FakeMessageBox.calls) == 1
    owner, text, title, _buttons, _icon = FakeMessageBox.calls[-1]
    assert owner is form
    assert title == mod.BLOCKED_TITLE
    assert text == mod._BLOCKED_TEXT["BUSY"]
    assert "BUSY" not in text

    mod.notify_reopen_blocked(window, "C:/secret/token")
    assert FakeMessageBox.calls[-1][1] == mod._BLOCKED_GENERIC
    assert "C:/secret" not in FakeMessageBox.calls[-1][1]
    assert "token" not in FakeMessageBox.calls[-1][1]

    mod.notify_reopen_blocked(window, 123)
    assert FakeMessageBox.calls[-1][1] == mod._BLOCKED_GENERIC

    mod.notify_reopen_blocked(window, "REOPEN_FAILED")
    failed_text = FakeMessageBox.calls[-1][1]
    assert failed_text == "重新打开失败，当前窗口已保留。"
    assert "稍后重试" not in failed_text
    assert "正常关闭" not in failed_text

    before = len(FakeMessageBox.calls)
    mod.notify_reopen_blocked(FakeWindow(), "BUSY")
    assert len(FakeMessageBox.calls) == before


def test_notify_background_marshals_and_error_is_safe(fake_winforms, native_fakes, caplog):
    window, form = make_prompt_window()
    form.InvokeRequired = True
    mod.notify_reopen_blocked(window, "AI_BUSY")
    assert len(form.invoke_calls) == 1
    assert FakeMessageBox.calls[-1][1] == mod._BLOCKED_TEXT["AI_BUSY"]

    FakeMessageBox.raise_error = True
    with caplog.at_level(logging.WARNING, logger="renderer_recovery_native"):
        mod.notify_reopen_blocked(window, "BUSY")
    assert any(mod._LOG_NOTIFY_FAILED in record.message for record in caplog.records)
    assert all("SECRET" not in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# Lazy native delegate construction (no window created)
# ---------------------------------------------------------------------------


def test_native_delegate_factories_are_constructible():
    pytest.importorskip("clr")
    import webview.platforms.edgechromium  # noqa: F401 - loads the fixed refs

    assert mod._make_action(lambda: None) is not None
    assert mod._make_func_bool(lambda: True) is not None
    for kind in ("process", "init", "form_closed"):
        assert mod._make_event_handler(kind, lambda *_: None) is not None
    form_closed = mod._make_event_handler("form_closed", lambda *_: None)
    assert type(form_closed).__name__ == "FormClosedEventHandler"


# ---------------------------------------------------------------------------
# Pure import boundary
# ---------------------------------------------------------------------------


def test_pure_import_does_not_load_native_assemblies():
    code = (
        "import sys\n"
        "import renderer_recovery_native\n"
        "bad = [name for name in ('System', 'System.Windows.Forms', "
        "'Microsoft.Web.WebView2.Core', 'webview', 'clr') if name in sys.modules]\n"
        "assert not bad, bad\n"
    )
    env = os.environ.copy()
    path_entries = [str(REPO_ROOT / "desktop"), str(REPO_ROOT / "backend")]
    existing = env.get("PYTHONPATH")
    if existing:
        path_entries.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(path_entries)
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
