"""Native WebView2 renderer-failure watcher and modal reopen prompt.

This is the host-private adapter described by
``docs/specs/desktop-renderer-recovery.md``.  It deliberately owns no
business policy: it only reports the two fatal ``CoreWebView2.ProcessFailed``
kinds, asks the user an explicit reopen question, and displays fixed safe
blocked notices.

Importing this module is pure Python.  WinForms / pythonnet / WebView2 types
are imported lazily inside adapter functions so unit tests and headless
imports never load platform assemblies.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

_LOGGER = logging.getLogger(__name__)

WARNING_TEXT = "页面已停止，未保存的输入可能丢失"
REOPEN_TEXT = "重新打开最后保存的档案"
KEEP_TEXT = "保留当前窗口"
BLOCKED_TITLE = "无法重新打开"

_FATAL_KINDS = frozenset({"RenderProcessExited", "BrowserProcessExited"})
_LOG_CALLBACK_FAILED = "renderer watcher: failure callback raised"
_LOG_PROCESS_FAILED = "renderer watcher: process event handling failed"
_LOG_INIT_FAILED = "renderer watcher: CoreWebView2 initialization failed"
_LOG_BIND_FAILED = "renderer watcher: native window is unavailable"
_LOG_PROMPT_FAILED = "renderer recovery: reopen prompt is unavailable"
_LOG_NOTIFY_FAILED = "renderer recovery: blocked notice is unavailable"

_BLOCKED_TEXT = {
    "BUSY": "当前有正在进行的操作，暂时无法安全重新打开。请等待操作完成后再试。",
    "AI_BUSY": "AI 任务仍在进行，暂时无法安全重新打开。请等待任务完成后再试。",
    "MAINTENANCE_BUSY": "维护或恢复操作仍在进行，暂时无法安全重新打开。请等待完成后再试。",
    "STALE": "当前窗口状态已过期，暂时无法安全重新打开。请保留当前窗口。",
    "REOPEN_FAILED": "重新打开失败，当前窗口已保留。",
}
_BLOCKED_GENERIC = "暂时无法安全重新打开，当前窗口已保留。"

_PROMPT_LOCK = threading.Lock()
_LAST_PROMPT: dict[str, Any] | None = None


def _log_safe(log: Any, message: str) -> None:
    """Emit one fixed diagnostic; never include raw exception/state text."""
    if log is None:
        return
    try:
        if callable(log):
            log(message)
            return
        warning = getattr(log, "warning", None)
        if callable(warning):
            warning(message)
    except Exception:  # noqa: BLE001 - diagnostics must never break the host
        pass


def _event_is_set(events: Any, name: str) -> bool:
    try:
        event = getattr(events, name, None)
        checker = getattr(event, "is_set", None)
        return bool(checker()) if callable(checker) else False
    except Exception:  # noqa: BLE001 - unknown lifecycle state is not a fault
        return False


def _form_gone(form: Any) -> bool:
    try:
        return bool(getattr(form, "IsDisposed", False)) or bool(
            getattr(form, "Disposing", False)
        )
    except Exception:  # noqa: BLE001 - a disposed native form is gone
        return True


def _enum_name(value: Any) -> str:
    try:
        to_string = getattr(value, "ToString", None)
        if callable(to_string):
            return str(to_string())
        return str(value)
    except Exception:  # noqa: BLE001 - unknown enum is simply not fatal
        return ""


def _same_managed(left: Any, right: Any) -> bool:
    """Compare .NET-managed identity even when RCW wrappers differ."""
    try:
        from System import Object

        if bool(Object.ReferenceEquals(left, right)):
            return True
    except Exception:  # noqa: BLE001 - pure/fake test fallback
        pass
    return left is right


def _make_action(callback: Callable[[], Any]) -> Any:
    """Create the WinForms delegate used for synchronous marshalling."""
    from System import Action

    return Action(callback)


def _make_func_bool(callback: Callable[[], bool]) -> Any:
    """Create the WinForms delegate used for a synchronous bool result."""
    from System import Func

    return Func[bool](callback)


def _make_event_handler(kind: str, callback: Callable[..., Any]) -> Any:
    """Create an exact .NET delegate for one event subscription."""
    from System import EventHandler

    if kind == "process":
        from Microsoft.Web.WebView2.Core import (
            CoreWebView2ProcessFailedEventArgs as Args,
        )
        return EventHandler[Args](callback)
    if kind == "init":
        from Microsoft.Web.WebView2.Core import (
            CoreWebView2InitializationCompletedEventArgs as Args,
        )
        return EventHandler[Args](callback)
    if kind == "form_closed":
        from System.Windows.Forms import FormClosedEventHandler

        return FormClosedEventHandler(callback)
    raise ValueError("unsupported native event kind")


def _load_winforms() -> tuple[Any, Any, Any]:
    """Lazy WinForms import used only by prompt/notice helpers."""
    import clr

    clr.AddReference("System.Windows.Forms")
    import System.Windows.Forms as WinForms
    from System.Drawing import Point, Size

    return WinForms, Point, Size


def _ui_call_value(form: Any, callback: Callable[[], bool]) -> bool:
    """Run a bool-returning callback on the form's UI thread."""
    if form is None or _form_gone(form):
        return False
    try:
        if not bool(getattr(form, "IsHandleCreated", True)):
            return False
        if not bool(getattr(form, "InvokeRequired", False)):
            return bool(callback())
        delegate = _make_func_bool(callback)
        return bool(form.Invoke(delegate))
    except Exception:  # noqa: BLE001 - unavailable UI is a false result
        return False


def _ui_call(form: Any, callback: Callable[[], Any], *, wait: bool) -> bool:
    """Run a callback on the form's UI thread, without forcing a handle."""
    if form is None or _form_gone(form):
        return False
    try:
        if not bool(getattr(form, "IsHandleCreated", True)):
            return False
        if not bool(getattr(form, "InvokeRequired", False)):
            callback()
            return True
        delegate = _make_action(callback)
        if wait:
            form.Invoke(delegate)
        else:
            form.BeginInvoke(delegate)
        return True
    except Exception:  # noqa: BLE001 - unavailable UI is a no-op
        return False


def _remove_pywebview_event(events: Any, name: str, handler: Any) -> None:
    if events is None or handler is None:
        return
    try:
        event = getattr(events, name, None)
        if event is not None:
            event -= handler
    except Exception:  # noqa: BLE001 - already detached or closing
        pass


class _RendererWatcher:
    """One exact window/generation observation; at most one fault callback."""

    def __init__(self, window: Any, on_failure: Callable[[str], Any], log: Any) -> None:
        if not callable(on_failure):
            raise TypeError("on_failure must be callable")
        self._window = window
        self._on_failure = on_failure
        self._log = log
        self._lock = threading.RLock()
        self._closed = False
        self._faulted = False
        self._form: Any = None
        self._webview: Any = None
        self._core: Any = None
        self._init_handler: Any = None
        self._fault_handler: Any = None
        self._form_closed_handler: Any = None
        self._shown_handler: Any = None
        self._initialized_handler: Any = None
        self._install()

    # -- installation / lazy binding ------------------------------------

    def _install(self) -> None:
        form = getattr(self._window, "native", None)
        if form is not None and _ui_call_value(form, self._bind_on_ui):
            return
        self._listen_for_window()

    def _listen_for_window(self) -> None:
        events = getattr(self._window, "events", None)
        if events is None:
            _log_safe(self._log, _LOG_BIND_FAILED)
            return
        with self._lock:
            if self._closed:
                return
            if self._shown_handler is None:
                handler = self._on_shown
                try:
                    events.shown += handler
                    self._shown_handler = handler
                except Exception:  # noqa: BLE001 - wait for initialized instead
                    pass
            if self._initialized_handler is None:
                handler = self._on_initialized
                try:
                    events.initialized += handler
                    self._initialized_handler = handler
                except Exception:  # noqa: BLE001 - wait for shown instead
                    pass
        if _event_is_set(events, "shown") or _event_is_set(events, "initialized"):
            self._schedule_bind()

    def _on_shown(self) -> None:
        self._schedule_bind()

    def _on_initialized(self) -> None:
        self._schedule_bind()

    def _schedule_bind(self) -> None:
        with self._lock:
            if self._closed:
                return
            form = getattr(self._window, "native", None)
        if form is None:
            return
        if not _ui_call_value(form, self._bind_on_ui):
            # A later shown/initialized notification can retry; do not spin.
            return

    def _bind_on_ui(self) -> bool:
        """Bind to the exact BrowserForm + its WebView2 control + Core."""
        with self._lock:
            if self._closed:
                return True
            window = self._window
        form = getattr(window, "native", None)
        if form is None or _form_gone(form):
            return False
        webview = getattr(form, "webview", None)
        browser = getattr(form, "browser", None)
        browser_webview = getattr(browser, "webview", None)
        if webview is None or browser_webview is not webview:
            return False
        core = getattr(webview, "CoreWebView2", None)
        with self._lock:
            if self._closed:
                return True
            self._form = form
            self._webview = webview
        if core is None:
            return self._attach_initialization(form, webview)
        return self._attach_core(form, webview, core)

    def _attach_initialization(self, form: Any, webview: Any) -> bool:
        with self._lock:
            if self._closed:
                return True
            if self._init_handler is not None:
                return True
            handler = _make_event_handler("init", self._on_core_initialized)
            self._init_handler = handler
            self._form = form
            self._webview = webview
        try:
            webview.CoreWebView2InitializationCompleted += handler
            return True
        except Exception:  # noqa: BLE001 - no unconfirmed fault claim
            with self._lock:
                if self._init_handler is handler:
                    self._init_handler = None
            _log_safe(self._log, _LOG_BIND_FAILED)
            return False

    def _attach_core(self, form: Any, webview: Any, core: Any) -> bool:
        with self._lock:
            if self._closed:
                return True
            if self._core is not None and self._core is not core:
                return False
            if self._fault_handler is not None:
                return True
            fault_handler = _make_event_handler("process", self._on_process_failed)
            form_closed_handler = _make_event_handler(
                "form_closed", self._on_form_closed
            )
            init_handler = self._init_handler
            self._form = form
            self._webview = webview
            self._core = core
            self._fault_handler = fault_handler
            self._form_closed_handler = form_closed_handler
            self._init_handler = None
        try:
            core.ProcessFailed += fault_handler
            try:
                form.FormClosed += form_closed_handler
            except Exception:  # noqa: BLE001 - close watcher explicitly instead
                self._form_closed_handler = None
                form_closed_handler = None
            if init_handler is not None:
                try:
                    webview.CoreWebView2InitializationCompleted -= init_handler
                except Exception:  # noqa: BLE001 - already detached
                    pass
            return True
        except Exception:  # noqa: BLE001 - rollback partial subscription
            with self._lock:
                self._core = None
                self._fault_handler = None
                self._form_closed_handler = None
            try:
                core.ProcessFailed -= fault_handler
            except Exception:  # noqa: BLE001 - best effort rollback
                pass
            if form_closed_handler is not None:
                try:
                    form.FormClosed -= form_closed_handler
                except Exception:  # noqa: BLE001 - best effort rollback
                    pass
            if init_handler is not None:
                try:
                    webview.CoreWebView2InitializationCompleted -= init_handler
                except Exception:  # noqa: BLE001 - best effort rollback
                    pass
            _log_safe(self._log, _LOG_BIND_FAILED)
            return False

    # -- native events ---------------------------------------------------

    def _on_core_initialized(self, sender: Any, args: Any) -> None:
        # The subscription is on the exact captured WebView2 control.  The
        # .NET event may hand us a different RCW wrapper for the same managed
        # control, so never use Python ``is`` against the event sender.
        with self._lock:
            if self._closed:
                return
            form = self._form
            webview = self._webview
        try:
            if not bool(getattr(args, "IsSuccess", False)):
                _log_safe(self._log, _LOG_INIT_FAILED)
                return
            core = getattr(webview, "CoreWebView2", None)
            if core is None:
                _log_safe(self._log, _LOG_INIT_FAILED)
                return
            self._attach_core(form, webview, core)
        except Exception:  # noqa: BLE001 - safe diagnostic only
            _log_safe(self._log, _LOG_INIT_FAILED)

    def _on_form_closed(self, sender: Any, args: Any) -> None:
        self.close()

    def _on_process_failed(self, sender: Any, args: Any) -> None:
        # This handler is subscribed only to the exact captured CoreWebView2's
        # ProcessFailed event.  The sender is commonly a different CoreWebView2
        # RCW for the same managed object; Python ``is`` must not be used.
        # Identity is the exact event subscription plus the current form and
        # format generation, not the sender wrapper or a possibly-dead PID.
        with self._lock:
            if self._closed or self._faulted:
                return
            form = self._form
        if form is None:
            return
        try:
            if getattr(self._window, "native", None) is not form:
                return
            if _form_gone(form):
                return
            events = getattr(self._window, "events", None)
            # pywebview's Event.set latches even when a closing handler denied
            # the close, so ``closing`` is not a final-close proof.  A closes
            # the watcher or marks expected close when a final allow/retire
            # destroy is actually accepted; only the terminal closed event is
            # a safe suppression here.
            if _event_is_set(events, "closed"):
                return
            kind = _enum_name(getattr(args, "ProcessFailedKind", None))
            if kind not in _FATAL_KINDS:
                return
            with self._lock:
                if self._closed or self._faulted:
                    return
                self._faulted = True
                callback = self._on_failure
            try:
                callback(kind)
            except Exception:  # noqa: BLE001 - never propagate a callback error
                _log_safe(self._log, _LOG_CALLBACK_FAILED)
        except Exception:  # noqa: BLE001 - fixed diagnostic, no raw details
            _log_safe(self._log, _LOG_PROCESS_FAILED)

    # -- detach ----------------------------------------------------------

    def close(self) -> None:
        """Idempotently detach; safe while initializing or after a fault."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            window = self._window
            form = self._form
            webview = self._webview
            core = self._core
            init_handler = self._init_handler
            fault_handler = self._fault_handler
            form_closed_handler = self._form_closed_handler
            shown_handler = self._shown_handler
            initialized_handler = self._initialized_handler
            self._init_handler = None
            self._fault_handler = None
            self._form_closed_handler = None
            self._shown_handler = None
            self._initialized_handler = None
        events = getattr(window, "events", None)
        _remove_pywebview_event(events, "shown", shown_handler)
        _remove_pywebview_event(events, "initialized", initialized_handler)

        def detach() -> None:
            try:
                if core is not None and fault_handler is not None:
                    core.ProcessFailed -= fault_handler
            except Exception:  # noqa: BLE001 - closing/already detached
                pass
            try:
                if webview is not None and init_handler is not None:
                    webview.CoreWebView2InitializationCompleted -= init_handler
            except Exception:  # noqa: BLE001 - closing/already detached
                pass
            try:
                if form is not None and form_closed_handler is not None:
                    form.FormClosed -= form_closed_handler
            except Exception:  # noqa: BLE001 - closing/already detached
                pass

        if form is not None and not _form_gone(form):
            _ui_call(form, detach, wait=False)
        else:
            detach()
        with self._lock:
            self._form = None
            self._webview = None
            self._core = None

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    @property
    def faulted(self) -> bool:
        with self._lock:
            return self._faulted


def install_renderer_watcher(
    window: Any, on_failure: Callable[[str], Any], *, log: Any = None
) -> _RendererWatcher:
    """Observe one window's exact CoreWebView2; return an idempotent watcher."""
    return _RendererWatcher(window, on_failure, log)


# ---------------------------------------------------------------------------
# Native modal prompts
# ---------------------------------------------------------------------------


def _record_prompt(dialog: Any, warning: Any, reopen: Any, keep: Any, owner: Any) -> None:
    global _LAST_PROMPT
    # Store only immutable/pure data.  Never retain the dialog, its controls,
    # event delegates or the owner form after the modal returns.
    accept_button = getattr(dialog, "AcceptButton", None)
    cancel_button = getattr(dialog, "CancelButton", None)
    active_control = getattr(dialog, "ActiveControl", None)
    keep_text = getattr(keep, "Text", "")
    default_is_keep = _same_managed(accept_button, keep)
    cancel_is_keep = _same_managed(cancel_button, keep)
    active_is_keep = _same_managed(active_control, keep)
    snapshot = {
        "owner_present": owner is not None,
        "owner_type": type(owner).__name__ if owner is not None else "",
        "warning_text": getattr(warning, "Text", ""),
        "accessible_name": getattr(warning, "AccessibleName", ""),
        "accessible_description": getattr(warning, "AccessibleDescription", ""),
        "button_texts": (
            getattr(reopen, "Text", ""),
            keep_text,
        ),
        "button_accessible_names": (
            getattr(reopen, "AccessibleName", ""),
            getattr(keep, "AccessibleName", ""),
        ),
        "button_sizes": (
            (
                int(getattr(reopen.Size, "Width", 0)),
                int(getattr(reopen.Size, "Height", 0)),
            ),
            (
                int(getattr(keep.Size, "Width", 0)),
                int(getattr(keep.Size, "Height", 0)),
            ),
        ),
        "accept_button_text": keep_text
        if default_is_keep
        else getattr(accept_button, "Text", ""),
        "cancel_button_text": keep_text
        if cancel_is_keep
        else getattr(cancel_button, "Text", ""),
        "active_control_text": keep_text
        if active_is_keep
        else getattr(active_control, "Text", ""),
        "default_button_is_keep": default_is_keep,
        "cancel_button_is_keep": cancel_is_keep,
        "active_control_is_keep": active_is_keep,
        "default_button_text": keep_text,
    }
    with _PROMPT_LOCK:
        _LAST_PROMPT = snapshot


def _last_prompt_snapshot() -> dict[str, Any] | None:
    """Private test seam; not a normal runtime debug switch."""
    with _PROMPT_LOCK:
        return dict(_LAST_PROMPT) if _LAST_PROMPT is not None else None


def _measure_text_size(control: Any, text: str) -> tuple[int, int]:
    """Measure the actual current font/DPI; pure fallback for fake tests."""
    try:
        from System.Drawing import Size
        from System.Windows.Forms import TextFormatFlags, TextRenderer

        measured = TextRenderer.MeasureText(
            text,
            getattr(control, "Font", None),
            Size.Empty,
            TextFormatFlags.SingleLine | TextFormatFlags.NoPadding,
        )
        return int(measured.Width), int(measured.Height)
    except Exception:  # noqa: BLE001 - caller uses bounded fallback
        return 0, 0


def _button_layout_size(
    button: Any, text: str, minimum_width: int
) -> tuple[int, int]:
    measured_width, measured_height = _measure_text_size(button, text)
    preferred = getattr(button, "PreferredSize", None)
    preferred_width = int(getattr(preferred, "Width", 0) or 0)
    preferred_height = int(getattr(preferred, "Height", 0) or 0)
    # Extra room covers button border/focus/padding; never rely on a fixed
    # 250/190px assertion that can clip the approved long label at high DPI.
    return (
        max(minimum_width, measured_width + 40, preferred_width),
        max(42, measured_height + 18, preferred_height),
    )


def _layout_reopen_dialog(
    dialog: Any,
    warning: Any,
    reopen: Any,
    keep: Any,
    Point: Any,
    Size: Any,
) -> None:
    warning_width_measured, warning_height_measured = _measure_text_size(
        warning, WARNING_TEXT
    )
    reopen_width, reopen_height = _button_layout_size(reopen, REOPEN_TEXT, 250)
    keep_width, keep_height = _button_layout_size(keep, KEEP_TEXT, 190)
    margin = 24
    gap = 20
    warning_width = max(492, warning_width_measured + 8)
    warning_height = max(56, warning_height_measured + 8)
    button_row_width = reopen_width + gap + keep_width
    dialog_width = max(540, warning_width + 2 * margin, button_row_width + 2 * margin)
    button_y = margin + warning_height + gap
    dialog_height = max(
        176, button_y + max(reopen_height, keep_height) + margin
    )
    dialog.ClientSize = Size(dialog_width, dialog_height)
    warning.SetBounds(
        margin, margin, dialog_width - 2 * margin, warning_height
    )
    reopen.AutoSize = False
    reopen.Size = Size(reopen_width, reopen_height)
    reopen.Location = Point(margin, button_y)
    keep.AutoSize = False
    keep.Size = Size(keep_width, keep_height)
    keep.Location = Point(margin + reopen_width + gap, button_y)
    layout = getattr(dialog, "PerformLayout", None)
    if callable(layout):
        layout()


def _show_reopen_dialog(form: Any) -> bool:
    try:
        WinForms, Point, Size = _load_winforms()
    except Exception:  # noqa: BLE001 - platform unavailable means no consent
        _log_safe(_LOGGER, _LOG_PROMPT_FAILED)
        return False

    dialog = None
    try:
        dialog = WinForms.Form()
        dialog.Text = "页面已停止"
        dialog.AccessibleName = "页面已停止"
        dialog.AccessibleDescription = WARNING_TEXT
        dialog.FormBorderStyle = WinForms.FormBorderStyle.FixedDialog
        dialog.StartPosition = WinForms.FormStartPosition.CenterParent
        dialog.MinimizeBox = False
        dialog.MaximizeBox = False
        dialog.ShowInTaskbar = False

        warning = WinForms.Label()
        warning.Text = WARNING_TEXT
        warning.AutoSize = False
        warning.AccessibleName = "页面已停止"
        warning.AccessibleDescription = WARNING_TEXT

        reopen = WinForms.Button()
        reopen.Text = REOPEN_TEXT
        reopen.AutoSize = False
        reopen.AccessibleName = REOPEN_TEXT
        reopen.TabIndex = 1
        reopen.DialogResult = WinForms.DialogResult.OK

        keep = WinForms.Button()
        keep.Text = KEEP_TEXT
        keep.AutoSize = False
        keep.AccessibleName = KEEP_TEXT
        keep.TabIndex = 0
        keep.DialogResult = WinForms.DialogResult.Cancel

        dialog.Controls.Add(warning)
        dialog.Controls.Add(reopen)
        dialog.Controls.Add(keep)
        _layout_reopen_dialog(dialog, warning, reopen, keep, Point, Size)
        # Unsaved input may be lost: Enter/default activation must keep the
        # current window unless the operator explicitly activates reopen.
        dialog.AcceptButton = keep
        dialog.CancelButton = keep
        dialog.ActiveControl = keep
        _record_prompt(dialog, warning, reopen, keep, form)
        result = dialog.ShowDialog(form)
        return bool(result == WinForms.DialogResult.OK)
    except Exception:  # noqa: BLE001 - unavailable/error means keep
        _log_safe(_LOGGER, _LOG_PROMPT_FAILED)
        return False
    finally:
        if dialog is not None:
            dispose = getattr(dialog, "Dispose", None)
            if callable(dispose):
                try:
                    dispose()
                except Exception:  # noqa: BLE001 - dialog already gone
                    pass


def prompt_reopen(window: Any) -> bool:
    """Ask for explicit consent to reopen; only the first button returns True."""
    form = getattr(window, "native", None)
    if form is None or _form_gone(form):
        return False
    return _ui_call_value(form, lambda: _show_reopen_dialog(form))


def _show_blocked_notice(form: Any, text: str) -> None:
    try:
        WinForms, _Point, _Size = _load_winforms()
    except Exception:  # noqa: BLE001 - no notice is safer than a raw error
        _log_safe(_LOGGER, _LOG_NOTIFY_FAILED)
        return
    try:
        WinForms.MessageBox.Show(
            form,
            text,
            BLOCKED_TITLE,
            WinForms.MessageBoxButtons.OK,
            WinForms.MessageBoxIcon.Information,
        )
    except Exception:  # noqa: BLE001 - notice failure is a no-op
        _log_safe(_LOGGER, _LOG_NOTIFY_FAILED)


def notify_reopen_blocked(window: Any, code: Any) -> None:
    """Display one fixed safe reason; unknown codes use the generic text."""
    form = getattr(window, "native", None)
    if form is None or _form_gone(form):
        return
    text = _BLOCKED_TEXT.get(code, _BLOCKED_GENERIC) if isinstance(code, str) else _BLOCKED_GENERIC
    _ui_call(form, lambda: _show_blocked_notice(form, text), wait=True)


__all__ = [
    "install_renderer_watcher",
    "prompt_reopen",
    "notify_reopen_blocked",
]
