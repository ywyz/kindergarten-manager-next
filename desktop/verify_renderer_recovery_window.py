"""Source-only verifier: native renderer fault -> explicit same-database reopen.

Run with the repository venv, a fresh synthetic data/credential root, the
reviewed frontend directory and an output path:

    python desktop/verify_renderer_recovery_window.py \
        --data <temp>/data --credential-root <temp>/credentials \
        --frontend <round>/recovery-frontend --out <round>/result.json

It is never a normal product switch and is not packaged.  It uses the real
d1_main runtime/service/window wiring, the fixture's full saved archive, and
B's native prompt; it never calls a real AI supplier.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import http.client
import json
import os
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path
from types import SimpleNamespace

import webview
import webview.platforms.edgechromium  # noqa: F401 - load WebView2 CLR
from System import Action, Func, Object
from System.Windows.Forms import Application, Button

import d1_host_api
import d1_main
import maintenance_lifecycle
import renderer_recovery
from sqlalchemy import text


PROMPT_TITLE = "页面已停止"
REOPEN_TEXT = "重新打开最后保存的档案"
KEEP_TEXT = "保留当前窗口"

_VK_RETURN = 0x0D
_VK_ESCAPE = 0x1B
_INPUT_KEYBOARD = 1
_INPUT_MOUSE = 0
_KEYEVENTF_KEYUP = 0x0002
_MOUSEEVENTF_MOVE = 0x0001
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_MOUSEEVENTF_ABSOLUTE = 0x8000
_MOUSEEVENTF_VIRTUALDESK = 0x4000
_WM_SYSCOMMAND = 0x0112
_SC_CLOSE = 0xF060
_GW_OWNER = 4
_SM_XVIRTUALSCREEN = 76
_SM_YVIRTUALSCREEN = 77
_SM_CXVIRTUALSCREEN = 78
_SM_CYVIRTUALSCREEN = 79


class VerifierArgs(SimpleNamespace):
    def __getattr__(self, name):  # noqa: D105 - optional d1_main CLI fields
        return None


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class _GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", _RECT),
    ]


_user32 = ctypes.WinDLL("user32.dll", use_last_error=True)
_user32.GetWindowThreadProcessId.argtypes = [
    wintypes.HWND,
    ctypes.POINTER(wintypes.DWORD),
]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
_user32.GetWindow.restype = wintypes.HWND
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetGUIThreadInfo.argtypes = [
    wintypes.DWORD,
    ctypes.POINTER(_GUITHREADINFO),
]
_user32.GetGUIThreadInfo.restype = wintypes.BOOL
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(_RECT)]
_user32.GetWindowRect.restype = wintypes.BOOL
_user32.SetForegroundWindow.argtypes = [wintypes.HWND]
_user32.SetForegroundWindow.restype = wintypes.BOOL
_user32.PostMessageW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
_user32.PostMessageW.restype = wintypes.BOOL
_user32.SendInput.argtypes = [
    wintypes.UINT,
    ctypes.POINTER(_INPUT),
    ctypes.c_int,
]
_user32.SendInput.restype = wintypes.UINT
_user32.GetSystemMetrics.argtypes = [ctypes.c_int]
_user32.GetSystemMetrics.restype = ctypes.c_int


class PromptHandleError(RuntimeError):
    """A managed handle could not be converted without guessing."""


def _managed_handle(value) -> int:
    to_int64 = getattr(value, "ToInt64", None)
    if callable(to_int64):
        try:
            return int(to_int64())
        except Exception as exc:  # noqa: BLE001 - distinct capability failure
            raise PromptHandleError("managed handle conversion failed") from exc
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise PromptHandleError("managed handle conversion failed")


def _managed_reference_equal(left, right) -> bool:
    """Use real .NET reference identity; pure Python fakes use ``is``."""
    if not (hasattr(left, "GetType") and hasattr(right, "GetType")):
        return left is right
    return bool(Object.ReferenceEquals(left, right))


class _RecoveryObserver:
    """Private source observer with ordered, lock-protected events."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seq = 0
        self._events: list[dict] = []

    def record(
        self,
        phase: str,
        *,
        window_uid: str | None = None,
        host_label: str | None = None,
        bundle_label: str | None = None,
        generation: int | None = None,
        detail: dict | None = None,
    ) -> dict:
        with self._lock:
            self._seq += 1
            event = {
                "seq": self._seq,
                "monotonic_ns": time.monotonic_ns(),
                "thread": threading.get_ident(),
                "phase": phase,
                "window_uid": window_uid,
                "host_label": host_label,
                "bundle_label": bundle_label,
                "generation": generation,
                "detail": dict(detail or {}),
            }
            self._events.append(event)
            return dict(event)

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [dict(event) for event in self._events]


def _window_uid(window) -> str | None:
    value = getattr(window, "uid", None)
    return str(value) if value else None


def _window_visible(window) -> bool:
    native = getattr(window, "native", None)
    return bool(
        native is not None
        and not bool(getattr(native, "IsDisposed", False))
        and bool(getattr(native, "Visible", False))
    )


def _fault_evidence(recovery) -> dict:
    lock = getattr(recovery, "_lock", None)
    if lock is None:
        raise RuntimeError("recovery lock missing")
    with lock:
        fault = getattr(recovery, "_fault", None)
        return {
            "kind": getattr(fault, "kind", None),
            "generation": getattr(fault, "generation", None),
        }


def _event_sequence_ok(
    events: list[dict],
    *,
    old_generation: int,
    new_generation: int,
    old_uid: str | None,
    new_uid: str | None,
    worker_thread: int,
) -> bool:
    if not old_uid or not new_uid or old_uid == new_uid:
        return False
    if not worker_thread:
        return False
    required = (
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
        "new_bundle.install_cas.enter",
        "new_bundle.install_cas.return",
        "new_service.start.enter",
        "new_service.start.return",
        "new_business_ready.enter",
        "new_business_ready.return",
        "old_destroy.enter",
        "old_destroy.return",
    )
    by_phase = {}
    for event in events:
        phase = event.get("phase")
        if phase in required:
            if phase in by_phase:
                return False
            by_phase[phase] = event
    if any(phase not in by_phase for phase in required):
        return False
    seqs = [event.get("seq") for event in events]
    if (
        any(not isinstance(seq, int) or isinstance(seq, bool) or seq <= 0 for seq in seqs)
        or seqs != sorted(seqs)
        or len(set(seqs)) != len(seqs)
    ):
        return False
    if any(
        events[index].get("monotonic_ns", 0)
        > events[index + 1].get("monotonic_ns", 0)
        for index in range(len(events) - 1)
    ):
        return False
    positions = [events.index(by_phase[phase]) for phase in required]
    if positions != sorted(positions):
        return False
    old_phases = {
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
        "old_destroy.enter",
        "old_destroy.return",
    }
    new_phases = set(required) - old_phases
    for phase in old_phases:
        event = by_phase[phase]
        if (
            event.get("thread") != worker_thread
            or event.get("host_label") != "old-host"
            or event.get("bundle_label") != "old-bundle"
            or event.get("generation") != old_generation
            or event.get("window_uid") != old_uid
        ):
            return False
    for phase in new_phases:
        event = by_phase[phase]
        uid_ok = event.get("window_uid") == new_uid
        if phase in (
            "new_bundle.install_cas.enter",
            "new_bundle.install_cas.return",
            "new_service.start.enter",
            "new_service.start.return",
        ):
            uid_ok = event.get("window_uid") in (None, new_uid)
        if (
            event.get("thread") != worker_thread
            or event.get("host_label") != "new-host"
            or event.get("bundle_label") != "new-bundle"
            or event.get("generation") != new_generation
            or not uid_ok
        ):
            return False
    if by_phase["new_bundle.install_cas.return"]["detail"].get("installed") is not True:
        return False
    if (
        by_phase["new_bundle.install_cas.enter"]["detail"].get("expected_is_old")
        is not True
    ):
        return False
    if by_phase["new_service.start.return"]["detail"].get("started") is not True:
        return False
    if by_phase["new_business_ready.return"]["detail"].get("ready") is not True:
        return False
    if (
        by_phase["new_business_ready.return"]["detail"].get("business_ready")
        is not True
    ):
        return False
    old_stop = by_phase["old_stop_if_idle.return"]["detail"]
    if (
        old_stop.get("return") is not True
        or old_stop.get("thread_alive_after") is not False
        or old_stop.get("gate_ok") is not True
    ):
        return False
    old_service = by_phase["old_service_stop.return"]["detail"]
    if (
        old_service.get("return") is not True
        or old_service.get("thread_alive_after") is not False
    ):
        return False
    if by_phase["old_host_retire.return"]["detail"].get("retired") is not True:
        return False
    idempotent = by_phase["old_host_retire_idempotent.return"]["detail"]
    if (
        idempotent.get("first") is not False
        or idempotent.get("retired") is not True
        or idempotent.get("page_ready") is not False
    ):
        return False
    if by_phase["engine_close.return"]["detail"].get("lock_ok") is not True:
        return False
    if by_phase["engine_reopen.return"]["detail"].get("lock_ok") is not True:
        return False
    destroy_enter = by_phase["old_destroy.enter"]["detail"]
    if (
        destroy_enter.get("old_form_alive_before") is not True
        or destroy_enter.get("new_business_ready") is not True
        or destroy_enter.get("new_window_visible") is not True
        or destroy_enter.get("new_document_generation") != new_generation
        or destroy_enter.get("fresh_executor_ok") is not True
    ):
        return False
    closed_events = [
        event for event in events if event.get("phase") == "old_window.closed"
    ]
    if len(closed_events) != 1:
        return False
    closed = closed_events[0]
    if (
        closed.get("window_uid") != old_uid
        or closed.get("generation") != old_generation
        or closed.get("detail", {}).get("closed") is not True
        or not closed.get("thread")
    ):
        return False
    closed_index = events.index(closed)
    if closed_index <= events.index(by_phase["new_business_ready.return"]):
        return False
    if closed_index <= events.index(by_phase["old_destroy.enter"]):
        return False
    return True



def _is_prompt_button(control) -> bool:
    return isinstance(control, Button) or (
        hasattr(control, "Text")
        and hasattr(control, "DialogResult")
        and hasattr(control, "PerformClick")
    )


def _prompt_buttons(form) -> list:
    return [
        control
        for control in getattr(form, "Controls", ())
        if _is_prompt_button(control)
    ]


def _prompt_button_by_text(form, text: str):
    for control in _prompt_buttons(form):
        if str(getattr(control, "Text", "")) == text:
            return control
    return None


def _prompt_form_matches(form, owner) -> bool:
    """Exact owned prompt + two buttons; default/focus are a separate gate."""
    if _managed_reference_equal(form, owner):
        return False
    if str(getattr(form, "Text", "")) != PROMPT_TITLE:
        return False
    if not _managed_reference_equal(getattr(form, "Owner", None), owner):
        return False
    buttons = _prompt_buttons(form)
    if len(buttons) != 2:
        return False
    keep = _prompt_button_by_text(form, KEEP_TEXT)
    reopen = _prompt_button_by_text(form, REOPEN_TEXT)
    if keep is None or reopen is None:
        return False
    if _managed_reference_equal(keep, reopen):
        return False
    return True


def _find_prompt_form(forms, owner):
    matches = [form for form in forms if _prompt_form_matches(form, owner)]
    return matches[0] if len(matches) == 1 else None


def _select_prompt(owner):
    forms = list(Application.OpenForms)
    matches = [form for form in forms if _prompt_form_matches(form, owner)]
    if not matches:
        return None, "prompt_missing", len(forms)
    if len(matches) > 1:
        return None, "prompt_duplicate", len(forms)
    return matches[0], None, len(forms)


def _prompt_identity(form, owner, keep, reopen) -> dict:
    hwnd = _managed_handle(getattr(form, "Handle", None))
    owner_hwnd = _managed_handle(getattr(owner, "Handle", None))
    keep_hwnd = _managed_handle(getattr(keep, "Handle", None))
    reopen_hwnd = _managed_handle(getattr(reopen, "Handle", None))
    pid = wintypes.DWORD()
    owner_pid = wintypes.DWORD()
    thread = int(
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)) or 0
    )
    owner_thread = int(
        _user32.GetWindowThreadProcessId(
            owner_hwnd, ctypes.byref(owner_pid)
        )
        or 0
    )
    owner_native = int(_user32.GetWindow(hwnd, _GW_OWNER) or 0)
    foreground = int(_user32.GetForegroundWindow() or 0)
    info = _GUITHREADINFO()
    info.cbSize = ctypes.sizeof(_GUITHREADINFO)
    focus_ok = bool(
        thread and _user32.GetGUIThreadInfo(thread, ctypes.byref(info))
    )
    focus_hwnd = int(info.hwndFocus or 0) if focus_ok else 0
    buttons = _prompt_buttons(form)
    texts = sorted(str(getattr(control, "Text", "")) for control in buttons)
    managed_default = bool(
        _managed_reference_equal(getattr(form, "AcceptButton", None), keep)
        and _managed_reference_equal(getattr(form, "CancelButton", None), keep)
        and _managed_reference_equal(getattr(form, "ActiveControl", None), keep)
    )
    handles = (hwnd, owner_hwnd, keep_hwnd, reopen_hwnd, focus_hwnd)
    button_handles_distinct = bool(
        keep_hwnd != reopen_hwnd
        and keep_hwnd not in (hwnd, owner_hwnd)
        and reopen_hwnd not in (hwnd, owner_hwnd)
    )
    return {
        "hwnd": hwnd,
        "owner_hwnd": owner_hwnd,
        "keep_hwnd": keep_hwnd,
        "reopen_hwnd": reopen_hwnd,
        "focus_hwnd": focus_hwnd,
        "pid": int(pid.value),
        "owner_pid": int(owner_pid.value),
        "thread": thread,
        "owner_thread": owner_thread,
        "foreground": foreground == hwnd,
        "focus_keep": focus_hwnd == keep_hwnd,
        "owner_match": owner_native == owner_hwnd,
        "pid_match": int(pid.value) == os.getpid(),
        "owner_pid_match": int(owner_pid.value) == os.getpid(),
        "thread_match": bool(thread and thread == owner_thread),
        "managed_owner": _managed_reference_equal(
            getattr(form, "Owner", None), owner
        ),
        "buttons_exact": texts == sorted([KEEP_TEXT, REOPEN_TEXT]),
        "managed_default_keep": managed_default,
        "visible": bool(getattr(form, "Visible", False)),
        "enabled": bool(getattr(form, "Enabled", False)),
        "handle_created": bool(getattr(form, "IsHandleCreated", False)),
        "modal": bool(getattr(form, "Modal", False)),
        "handles_nonzero": all(handle != 0 for handle in handles),
        "button_handles_distinct": button_handles_distinct,
        "focus_matches_keep": bool(
            focus_hwnd != 0
            and keep_hwnd != 0
            and focus_hwnd == keep_hwnd
        ),
        "texts": texts,
    }


def _prompt_input_gate(identity: dict) -> str | None:
    """Return the first capability reason; no input is sent unless all pass."""
    for key in (
        "pid_match",
        "owner_pid_match",
        "thread_match",
        "owner_match",
        "managed_owner",
        "buttons_exact",
        "managed_default_keep",
        "modal",
        "handles_nonzero",
        "button_handles_distinct",
        "visible",
        "enabled",
        "handle_created",
        "foreground",
        "focus_keep",
        "focus_matches_keep",
    ):
        if not identity.get(key):
            return key
    return None


def _inspect_prompt(owner) -> dict:
    form, reason, form_count = _select_prompt(owner)
    if form is None:
        return {
            "ready": False,
            "reason": reason,
            "form_count": form_count,
        }
    keep = _prompt_button_by_text(form, KEEP_TEXT)
    reopen = _prompt_button_by_text(form, REOPEN_TEXT)
    if keep is None or reopen is None:
        return {"ready": False, "reason": "prompt_buttons_missing"}
    identity = _prompt_identity(form, owner, keep, reopen)
    reason = _prompt_input_gate(identity)
    return {
        "ready": reason is None,
        "reason": reason,
        "identity": identity,
    }


def _prompt_observe(owner) -> dict:
    raw = owner.Invoke(
        Func[Object](
            lambda: json.dumps(_inspect_prompt(owner), ensure_ascii=False)
        )
    )
    return json.loads(str(raw))


def _activate_prompt_once(owner, observation: dict) -> dict:
    identity = observation.get("identity") or {}
    hwnd = int(identity.get("hwnd") or 0)
    if not hwnd:
        return {"attempted": False, "reason": "handle_missing"}
    before = dict(identity)
    returned = bool(_user32.SetForegroundWindow(hwnd))
    after_observation = _prompt_observe(owner)
    after = after_observation.get("identity") or {}
    return {
        "attempted": True,
        "hwnd": hwnd,
        "set_foreground_return": returned,
        "before": before,
        "after": dict(after),
        "after_ready": bool(after_observation.get("ready")),
        "after_reason": after_observation.get("reason"),
    }


def _wait_for_prompt_identity(owner, timeout: float = 20.0) -> dict:
    deadline = time.monotonic() + timeout
    last: dict = {"ready": False, "reason": "prompt_timeout"}
    activation: dict | None = None
    activated = False
    fail_closed = {
        "prompt_duplicate",
        "prompt_buttons_missing",
        "prompt_invoke_failed",
        "handle_conversion_failed",
        "pid_match",
        "owner_pid_match",
        "thread_match",
        "owner_match",
        "managed_owner",
        "buttons_exact",
        "managed_default_keep",
        "modal",
        "button_handles_distinct",
    }
    while time.monotonic() < deadline:
        try:
            last = _prompt_observe(owner)
        except PromptHandleError:
            return {"ready": False, "reason": "handle_conversion_failed"}
        except Exception:  # noqa: BLE001 - unavailable UI is not a capability
            return {"ready": False, "reason": "prompt_invoke_failed"}
        if last.get("ready"):
            if activation is not None:
                last["activation"] = activation
            return last
        if last.get("reason") in fail_closed:
            return last
        if last.get("reason") == "foreground" and not activated:
            activated = True
            activation = _activate_prompt_once(owner, last)
            if activation.get("after_ready"):
                ready_observation = _prompt_observe(owner)
                ready_observation["activation"] = activation
                if ready_observation.get("ready"):
                    return ready_observation
        time.sleep(0.05)
    if activation is not None:
        last["activation"] = activation
    return last


def _keyboard_input_events(vk: int) -> list[_INPUT]:
    events = []
    for flags in (0, _KEYEVENTF_KEYUP):
        event = _INPUT()
        event.type = _INPUT_KEYBOARD
        event.ki.wVk = vk
        event.ki.wScan = 0
        event.ki.dwFlags = flags
        event.ki.time = 0
        event.ki.dwExtraInfo = 0
        events.append(event)
    return events


def _send_key(vk: int) -> bool:
    events = _keyboard_input_events(vk)
    array = (_INPUT * len(events))(*events)
    sent = int(
        _user32.SendInput(len(events), array, ctypes.sizeof(_INPUT))
    )
    return sent == len(events)


def _absolute_click_coordinates(
    button_rect: tuple[int, int, int, int],
    prompt_rect: tuple[int, int, int, int],
    screen: tuple[int, int, int, int],
) -> tuple[int, int] | None:
    left, top, right, bottom = button_rect
    pleft, ptop, pright, pbottom = prompt_rect
    vx, vy, width, height = screen
    if right <= left or bottom <= top:
        return None
    if width <= 1 or height <= 1:
        return None
    if left < pleft or right > pright or top < ptop or bottom > pbottom:
        return None
    x = (left + right) // 2
    y = (top + bottom) // 2
    if not (vx <= x < vx + width and vy <= y < vy + height):
        return None
    absolute_x = int(round((x - vx) * 65535 / (width - 1)))
    absolute_y = int(round((y - vy) * 65535 / (height - 1)))
    if not (0 <= absolute_x <= 65535 and 0 <= absolute_y <= 65535):
        return None
    return absolute_x, absolute_y


def _mouse_click_events(
    button_hwnd: int, prompt_hwnd: int
) -> list[_INPUT] | None:
    button = _RECT()
    prompt = _RECT()
    if not _user32.GetWindowRect(int(button_hwnd), ctypes.byref(button)):
        return None
    if not _user32.GetWindowRect(int(prompt_hwnd), ctypes.byref(prompt)):
        return None
    coords = _absolute_click_coordinates(
        (button.left, button.top, button.right, button.bottom),
        (prompt.left, prompt.top, prompt.right, prompt.bottom),
        (
            int(_user32.GetSystemMetrics(_SM_XVIRTUALSCREEN)),
            int(_user32.GetSystemMetrics(_SM_YVIRTUALSCREEN)),
            int(_user32.GetSystemMetrics(_SM_CXVIRTUALSCREEN)),
            int(_user32.GetSystemMetrics(_SM_CYVIRTUALSCREEN)),
        ),
    )
    if coords is None:
        return None
    x, y = coords
    events = []
    for flags, dx, dy in (
        (_MOUSEEVENTF_MOVE | _MOUSEEVENTF_ABSOLUTE | _MOUSEEVENTF_VIRTUALDESK, x, y),
        (_MOUSEEVENTF_LEFTDOWN, 0, 0),
        (_MOUSEEVENTF_LEFTUP, 0, 0),
    ):
        event = _INPUT()
        event.type = _INPUT_MOUSE
        event.mi.dx = dx
        event.mi.dy = dy
        event.mi.mouseData = 0
        event.mi.dwFlags = flags
        event.mi.time = 0
        event.mi.dwExtraInfo = 0
        events.append(event)
    return events


def _prompt_action_on_ui(owner, action: str) -> dict:
    form, reason, _form_count = _select_prompt(owner)
    if form is None:
        return {"ok": False, "reason": reason}
    keep = _prompt_button_by_text(form, KEEP_TEXT)
    reopen = _prompt_button_by_text(form, REOPEN_TEXT)
    if keep is None or reopen is None:
        return {"ok": False, "reason": "prompt_buttons_missing"}
    identity = _prompt_identity(form, owner, keep, reopen)
    reason = _prompt_input_gate(identity)
    if reason is not None:
        return {"ok": False, "reason": reason, "identity": identity}
    if action == "enter":
        sent = _send_key(_VK_RETURN)
        return {
            "ok": sent,
            "reason": None if sent else "sendinput_failed",
            "method": "SendInput",
            "key": "VK_RETURN",
            "keyboard": True,
            "identity": identity,
        }
    if action == "escape":
        sent = _send_key(_VK_ESCAPE)
        return {
            "ok": sent,
            "reason": None if sent else "sendinput_failed",
            "method": "SendInput",
            "key": "VK_ESCAPE",
            "keyboard": True,
            "identity": identity,
        }
    if action == "x":
        posted = bool(
            _user32.PostMessageW(
                identity["hwnd"], _WM_SYSCOMMAND, _SC_CLOSE, 0
            )
        )
        return {
            "ok": posted,
            "reason": None if posted else "postmessage_failed",
            "method": "WM_SYSCOMMAND_SC_CLOSE",
            "keyboard": False,
            "native_close": True,
            "identity": identity,
        }
    if action == "reopen_click":
        events = _mouse_click_events(
            identity["reopen_hwnd"], identity["hwnd"]
        )
        if events is None:
            return {
                "ok": False,
                "reason": "click_geometry_unreliable",
                "identity": identity,
            }
        array = (_INPUT * len(events))(*events)
        sent = int(
            _user32.SendInput(len(events), array, ctypes.sizeof(_INPUT))
        )
        return {
            "ok": sent == len(events),
            "reason": None if sent == len(events) else "sendinput_failed",
            "method": "SendInput mouse",
            "keyboard": False,
            "native_close": False,
            "identity": identity,
        }
    return {"ok": False, "reason": "unknown_prompt_action"}


def _prompt_action(owner, action: str, timeout: float = 20.0) -> dict:
    observation = _wait_for_prompt_identity(owner, timeout)
    if not observation.get("ready"):
        return {
            "ok": False,
            "reason": observation.get("reason") or "prompt_not_ready",
            "observation": observation,
        }
    try:
        raw = owner.Invoke(
            Func[Object](
                lambda: json.dumps(
                    _prompt_action_on_ui(owner, action), ensure_ascii=False
                )
            )
        )
        result = json.loads(str(raw))
    except PromptHandleError:
        return {"ok": False, "reason": "handle_conversion_failed"}
    except Exception:  # noqa: BLE001 - unavailable UI is not a capability
        return {"ok": False, "reason": "prompt_invoke_failed"}
    result["prompt"] = observation
    return result


def _owner_native_close(owner, *, expected_pid: int | None = None) -> dict:
    try:
        hwnd = _managed_handle(getattr(owner, "Handle", None))
    except PromptHandleError:
        return {"ok": False, "reason": "handle_conversion_failed"}
    pid = wintypes.DWORD()
    thread = int(
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)) or 0
    )
    expected = os.getpid() if expected_pid is None else int(expected_pid)
    if not thread or int(pid.value) != expected:
        return {
            "ok": False,
            "reason": "owner_pid_mismatch",
            "hwnd": hwnd,
            "pid": int(pid.value),
        }
    posted = bool(
        _user32.PostMessageW(hwnd, _WM_SYSCOMMAND, _SC_CLOSE, 0)
    )
    return {
        "ok": posted,
        "reason": None if posted else "postmessage_failed",
        "method": "owner_wm_syscommand_sc_close",
        "keyboard": False,
        "native_close": True,
        "hwnd": hwnd,
        "pid": int(pid.value),
    }


def _controlled_retire_failure(recovery, bundle, window) -> dict:
    """Ordered private cleanup for this verifier's failed synthetic window."""
    steps: list[str] = []
    if recovery is not None:
        try:
            recovery.mark_expected_close()
            steps.append("mark_expected_close")
        except Exception:  # noqa: BLE001 - cleanup must continue
            steps.append("mark_expected_close_failed")
    host = getattr(bundle, "host_api", None) if bundle is not None else None
    if host is not None:
        try:
            host._request_retire_destroy()
            steps.append("request_retire_destroy")
        except Exception:  # noqa: BLE001 - cleanup must continue
            steps.append("request_retire_destroy_failed")
    if window is not None:
        try:
            window.destroy()
            steps.append("destroy")
        except Exception:  # noqa: BLE001 - cleanup must continue
            steps.append("destroy_failed")
    return {"steps": steps}


def _is_link_like(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        stat = path.stat(follow_symlinks=False)
    except OSError:
        return False
    return bool(getattr(stat, "st_file_attributes", 0) & 0x400)


def _has_raw_parent(path: Path) -> bool:
    raw = str(path).replace("\\", "/")
    return any(part == ".." for part in raw.split("/"))


def _check_existing_chain(path: Path) -> None:
    current = Path(os.path.abspath(str(path)))
    while True:
        if current.exists() or current.is_symlink():
            if _is_link_like(current):
                raise ValueError(f"reparse point in path: {current.name}")
        if current.parent == current:
            break
        current = current.parent


def _validate_synthetic_paths(
    data_root: Path, credential_root: Path, out: Path
) -> dict[str, str]:
    """Fail closed on the verifier's synthetic roots/output boundaries."""
    paths = {
        "data": data_root,
        "credential": credential_root,
        "output": out,
    }
    for label, path in paths.items():
        if _has_raw_parent(path):
            raise ValueError(f"{label}: raw parent segment")
        _check_existing_chain(path)
        if path.exists() or path.is_symlink():
            raise ValueError(f"{label}: path must be fresh")
    resolved = {
        label: Path(os.path.abspath(str(path))).resolve(strict=False)
        for label, path in paths.items()
    }
    for left_label, left in resolved.items():
        for right_label, right in resolved.items():
            if left_label >= right_label:
                continue
            if left == right or left in right.parents or right in left.parents:
                raise ValueError(
                    f"{left_label}/{right_label}: paths overlap"
                )
    return {label: str(path) for label, path in resolved.items()}


def _validate_persist_paths(cli) -> dict[str, Path]:
    """Fail closed before the cold child can create/read a wrong archive."""
    if not cli.expected_fingerprint or not cli.persist_out:
        raise ValueError("expected/output arguments are required")
    data_root = Path(cli.data)
    credential_root = Path(cli.credential_root)
    expected = Path(cli.expected_fingerprint)
    output = Path(cli.persist_out)
    for label, path in (
        ("data", data_root),
        ("credential", credential_root),
        ("expected", expected),
        ("output", output),
    ):
        if _has_raw_parent(path):
            raise ValueError(f"{label}: raw parent segment")
        _check_existing_chain(path)
    if not data_root.is_dir():
        raise ValueError("data root missing or not a directory")
    db_path = data_root / "kindergarten.db"
    if not db_path.is_file():
        raise ValueError("data root has no kindergarten.db")
    _check_existing_chain(db_path)
    if not credential_root.is_dir():
        raise ValueError("credential root missing or not a directory")
    if not expected.is_file():
        raise ValueError("expected fingerprint file missing")
    if output.exists() or output.is_symlink():
        raise ValueError("persist output must be fresh")
    if not output.parent.is_dir():
        raise ValueError("persist output parent missing")
    resolved = {
        "data": data_root.resolve(strict=False),
        "credential": credential_root.resolve(strict=False),
        "expected": expected.resolve(strict=False),
        "output": output.resolve(strict=False),
    }
    for label in ("expected", "output"):
        target = resolved[label]
        for root_label in ("data", "credential"):
            root = resolved[root_label]
            if target == root or target in root.parents or root in target.parents:
                raise ValueError(f"{label}/{root_label}: paths overlap")
    if resolved["expected"] == resolved["output"]:
        raise ValueError("expected/output paths overlap")
    return {
        "data": data_root,
        "credential": credential_root,
        "expected": expected,
        "output": output,
        "db": db_path,
    }


def _validate_output_directory(out: Path) -> dict[str, Path]:
    """Require one fresh per-window output directory and no stale sidecars."""
    parent = out.parent
    if out.name.casefold() in (
        "recovery-persist-expected.json",
        "recovery-persist-child.json",
    ):
        raise ValueError("main output collides with a fixed sidecar")
    if parent.exists() or parent.is_symlink():
        if _is_link_like(parent) or not parent.is_dir():
            raise ValueError("output parent must be a plain directory")
        if any(parent.iterdir()):
            raise ValueError("output directory must be fresh and empty")
    return {
        "expected": parent / "recovery-persist-expected.json",
        "child": parent / "recovery-persist-child.json",
    }


def _host_page_state(host) -> dict:
    """Read the exact bound page state under the host's own page lock."""
    lock = getattr(host, "_page_lock", None)
    if lock is None:
        raise RuntimeError("host page lock missing")
    with lock:
        business_ready = getattr(host, "_business_ready", None)
        return {
            "retired": bool(getattr(host, "_retired", False)),
            "page_ready": bool(getattr(host, "_page_ready", False)),
            "ticket_bound": bool(getattr(host, "_page_ticket_bound", False)),
            "business_ready": bool(
                business_ready.is_set()
                if business_ready is not None
                and callable(getattr(business_ready, "is_set", None))
                else False
            ),
            "ticket": getattr(host, "_page_ticket", None),
            "launch_token": getattr(host, "_launch_token", None),
            "maintenance_notice": getattr(host, "_maintenance_notice", None),
            "document_generation": getattr(host, "_document_generation", None),
            "page_busy": bool(getattr(host, "_page_busy", False)),
        }


def _fingerprint(value) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _public_host_state(state: dict) -> dict:
    return {
        "retired": bool(state.get("retired")),
        "page_ready": bool(state.get("page_ready")),
        "ticket_bound": bool(state.get("ticket_bound")),
        "business_ready": bool(state.get("business_ready")),
        "ticket_fingerprint": _fingerprint(state.get("ticket")),
        "launch_fingerprint": _fingerprint(state.get("launch_token")),
        "maintenance_notice": state.get("maintenance_notice"),
        "document_generation": state.get("document_generation"),
        "page_busy": bool(state.get("page_busy")),
    }


def _active_page(state: dict) -> bool:
    return bool(
        state.get("page_ready")
        and state.get("ticket_bound")
        and state.get("business_ready")
        and state.get("ticket")
        and state.get("launch_token")
        and not state.get("retired")
    )


def _readonly_status(port: int, token: str) -> int:
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
        response.read()
        return int(response.status)
    finally:
        connection.close()


def _close_state(host) -> str | None:
    coordinator = getattr(host, "_close_coordinator", None)
    if coordinator is None:
        return None
    lock = getattr(coordinator, "_lock", None)
    if lock is None:
        raise RuntimeError("close coordinator lock missing")
    with lock:
        return str(getattr(coordinator, "_state", None))


def _executor_gate_snapshot(executor) -> dict:
    gate = getattr(executor, "_gate", None)
    if gate is None:
        raise RuntimeError("executor gate missing")
    with gate:
        thread = getattr(executor, "_thread", None)
        idle = getattr(executor, "_idle", None)
        return {
            "thread_present": thread is not None,
            "thread_alive": bool(thread is not None and thread.is_alive()),
            "active_none": getattr(executor, "_active", None) is None,
            "pending_empty": not bool(getattr(executor, "_pending_results", {})),
            "unconfirmed": bool(getattr(executor, "_unconfirmed", False)),
            "slots_empty": not bool(getattr(executor, "_unconfirmed_slots", [])),
            "idle": bool(
                idle is not None
                and callable(getattr(idle, "is_set", None))
                and idle.is_set()
            ),
        }


def _executor_gate_ok(snapshot: dict) -> bool:
    return bool(
        not snapshot.get("thread_present")
        and not snapshot.get("thread_alive")
        and snapshot.get("active_none")
        and snapshot.get("pending_empty")
        and not snapshot.get("unconfirmed")
        and snapshot.get("slots_empty")
        and snapshot.get("idle")
    )


def _lock_snapshot(runtime, expected_handle) -> dict:
    handle = getattr(runtime, "_lock_handle", None)
    valid = False
    error_type = None
    try:
        runtime._validate_lock_handle()
        valid = True
    except Exception as exc:  # noqa: BLE001 - safe type only
        error_type = type(exc).__name__
    return {
        "owns": bool(getattr(runtime, "_owns_lock", False)),
        "handle_present": handle is not None,
        "same_handle": bool(expected_handle is not None and handle is expected_handle),
        "valid": valid,
        "error_type": error_type,
    }


def _lock_ok(snapshot: dict) -> bool:
    return bool(
        snapshot.get("owns")
        and snapshot.get("handle_present")
        and snapshot.get("same_handle")
        and snapshot.get("valid")
    )


def _second_runtime_refused(runtime) -> dict:
    from app.local.runtime import LocalRuntime

    other = None
    try:
        other = LocalRuntime(
            str(runtime.data_dir),
            credential_root=str(runtime.credential_root),
        )
        other.prepare()
    except Exception as exc:  # noqa: BLE001 - fixed safe code/type only
        return {
            "refused": True,
            "error_type": type(exc).__name__,
            "error_code": getattr(exc, "code", None),
        }
    finally:
        if other is not None:
            try:
                other.dispose()
            except Exception:  # noqa: BLE001 - cleanup only
                pass
    return {"refused": False, "error_type": None, "error_code": None}


def _safe_exception_type(call) -> str | None:
    try:
        call()
    except Exception as exc:  # noqa: BLE001 - safe type only
        return type(exc).__name__
    return None


def _issue_weekly_identity(runtime, profile_id: str):
    from sqlalchemy import text

    from app.local import weekly_plan_tokens

    session = runtime.session()
    try:
        plan_id = session.execute(
            text("SELECT id FROM local_weekly_plans LIMIT 1")
        ).scalar()
    finally:
        session.close()
    kwargs = {
        "purpose": "confirm",
        "profile_id": profile_id,
        "launch_id": str(getattr(runtime, "launch_id", "") or ""),
        "session_scope_hash": weekly_plan_tokens.scope_hash(
            "renderer-recovery-verifier"
        ),
        "object_id": str(plan_id or "weekly-plan"),
        "expected_version": 1,
    }
    token = weekly_plan_tokens.issue_token(runtime, **kwargs)
    weekly_plan_tokens.verify_token(runtime, token, **kwargs)
    return token, kwargs


def _weekly_identity_rejected(runtime, token: str, kwargs: dict) -> dict:
    from app.local import weekly_plan_tokens

    error_type = _safe_exception_type(
        lambda: weekly_plan_tokens.verify_token(runtime, token, **kwargs)
    )
    return {"rejected": error_type is not None, "error_type": error_type}


def _issue_adoption_store_identities():
    from app.local import ai_adoption, weekly_ai_adoption

    payload = {"verifier": "renderer-recovery"}
    daily_token, _daily_expiry = ai_adoption._TOKENS.issue(
        payload, time.time()
    )
    weekly_token, _weekly_expiry = weekly_ai_adoption._TOKENS.issue(
        payload, time.time()
    )
    daily_payload = ai_adoption._TOKENS.get(daily_token)
    weekly_payload = weekly_ai_adoption._TOKENS.get(weekly_token)
    return (
        {
            "daily": (daily_token, payload),
            "weekly": (weekly_token, payload),
        },
        bool(
            isinstance(daily_payload, dict)
            and daily_payload.get("verifier") == "renderer-recovery"
            and isinstance(weekly_payload, dict)
            and weekly_payload.get("verifier") == "renderer-recovery"
        ),
    )


def _adoption_store_identities_retired(identities: dict) -> dict:
    from app.local import ai_adoption, weekly_ai_adoption

    daily_token, _daily_payload = identities["daily"]
    weekly_token, _weekly_payload = identities["weekly"]
    return {
        "daily_retired": ai_adoption._TOKENS.get(daily_token) is None,
        "weekly_retired": weekly_ai_adoption._TOKENS.get(weekly_token) is None,
    }


def _old_host_call_probe(old_host, old_ticket: str) -> dict:
    before = _host_page_state(old_host)
    business = old_host.page_business_ready({"page_ticket": old_ticket})
    ready = old_host.page_ready(
        {
            "bridge_protocol": d1_host_api.BRIDGE_PROTOCOL,
            "page_ticket": old_ticket,
        }
    )
    busy = old_host.set_page_busy(
        {"page_ticket": old_ticket, "seq": 1, "busy": True}
    )
    guard = old_host._maintenance_guard()
    after = _host_page_state(old_host)
    accepted_false = bool(
        business.get("accepted") is False
        and ready.get("accepted") is False
        and busy.get("accepted") is False
    )
    retired_guard = bool(
        isinstance(guard, dict)
        and (guard.get("error") or {}).get("code") == "HOST_RETIRED"
    )
    return {
        "accepted_false": accepted_false,
        "retired_guard": retired_guard,
        "state_unchanged": before == after,
        "business_generation": business.get("document_generation"),
        "ready_generation": ready.get("document_generation"),
        "busy_generation": busy.get("document_generation"),
    }


def _fresh_executor_ok(current_executor, old_executor, current_bundle, runtime) -> bool:
    return bool(
        current_executor is not None
        and old_executor is not None
        and current_executor is not old_executor
        and current_executor is getattr(current_bundle, "executor", None)
        and current_executor is getattr(runtime, "ai_executor", None)
    )


def _executor_freeze_owners(executor) -> frozenset:
    if executor is None:
        return frozenset()
    gate = getattr(executor, "_gate", None)
    if gate is None:
        raise RuntimeError("executor gate missing")
    with gate:
        return frozenset(getattr(executor, "_freeze_owners", ()))


def _old_callback_probe(old_recovery, new_host, new_executor) -> dict:
    before_state = _host_page_state(new_host)
    before_owners = _executor_freeze_owners(new_executor)
    before_close = _close_state(new_host)
    old_recovery._on_native_failure("RenderProcessExited")
    intercept = bool(old_recovery.intercept_native_close())
    after_state = _host_page_state(new_host)
    after_owners = _executor_freeze_owners(new_executor)
    after_close = _close_state(new_host)
    return {
        "intercept_result": intercept,
        "state_unchanged": before_state == after_state,
        "freeze_owners_unchanged": before_owners == after_owners,
        "freeze_owner_count_before": len(before_owners),
        "freeze_owner_count_after": len(after_owners),
        "close_state_unchanged": before_close == after_close,
        "close_state_before": before_close,
        "close_state_after": after_close,
    }



def _fingerprint_summary(fingerprint: dict) -> dict:
    database = fingerprint.get("database") or {}
    resources = fingerprint.get("resources") or {}
    return {
        "combined_sha256": fingerprint.get("combined_sha256"),
        "database_sha256": database.get("fingerprint_sha256"),
        "resources_sha256": resources.get("fingerprint_sha256"),
        "schema_revision": database.get("schema_revision"),
        "table_count": len(database.get("tables") or {}),
        "resource_count": resources.get("file_count"),
        "resource_total_bytes": resources.get("total_bytes"),
        "semantic_counts": database.get("counts"),
    }


def _query_counts(runtime) -> dict[str, int]:
    import sqlite3

    connection = sqlite3.connect(str(runtime.db_path))
    try:
        names = (
            "local_ai_tasks",
            "local_ai_executions",
            "local_ai_attempts",
            "local_daily_plan_contents",
            "local_observation_records",
            "local_observation_assets",
        )
        result = {}
        for name in names:
            try:
                result[name] = int(
                    connection.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
                )
            except sqlite3.Error:
                result[name] = -1
        return result
    finally:
        connection.close()


def _ui_form_alive(form) -> bool:
    try:
        return bool(form) and not bool(form.IsDisposed)
    except Exception:
        return False


def _persist_check(cli) -> int:
    """Child-process full persistence readback; no window, JS, provider or AI."""
    import sqlite3

    from app.local.runtime import LocalRuntime
    from tests.local import backup_fixture_support as fixture

    try:
        paths = _validate_persist_paths(cli)
        expected = json.loads(
            paths["expected"].read_text(encoding="utf-8")
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary is fail-closed
        print(f"PERSIST_INVALID: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    data_root = paths["data"]
    out = paths["output"]
    try:
        expected_fingerprint = expected["fingerprint"]
        expected_counts = expected["table_counts"]
        expected_runtime_fingerprint = expected["runtime_fingerprint"]
    except Exception as exc:  # noqa: BLE001 - malformed expected file
        print(f"PERSIST_INVALID: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    runtime = LocalRuntime(
        str(data_root), credential_root=str(paths["credential"])
    )
    try:
        runtime.prepare()
        fingerprint = fixture.runtime_fingerprint(runtime)
        runtime_fingerprint = fixture.runtime_fingerprint(
            runtime, include_runtime_fields=True
        )
        counts = _query_counts(runtime)
        connection = sqlite3.connect(str(runtime.db_path))
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            foreign = connection.execute("PRAGMA foreign_key_check").fetchall()
        finally:
            connection.close()
        result = {
            "counts": counts,
            "expected_counts": expected_counts,
            "counts_match": counts == expected_counts,
            "fingerprint_match": fingerprint == expected_fingerprint,
            "runtime_fingerprint_match": (
                runtime_fingerprint == expected_runtime_fingerprint
            ),
            "combined_sha256": fingerprint.get("combined_sha256"),
            "runtime_combined_sha256": runtime_fingerprint.get("combined_sha256"),
            "database_sha256": (
                fingerprint.get("database") or {}
            ).get("fingerprint_sha256"),
            "resources_sha256": (
                fingerprint.get("resources") or {}
            ).get("fingerprint_sha256"),
            "integrity_check": integrity,
            "foreign_key_ok": not foreign,
        }
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if (
            result["fingerprint_match"]
            and result["runtime_fingerprint_match"]
            and result["counts_match"]
            and integrity == "ok"
            and not foreign
        ) else 1
    finally:
        runtime.dispose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--credential-root", required=True)
    parser.add_argument("--frontend")
    parser.add_argument("--out")
    parser.add_argument("--persist-check", action="store_true")
    parser.add_argument("--expected-fingerprint")
    parser.add_argument("--persist-out")
    parser.add_argument(
        "--fault-kind",
        choices=("Page.crash", "Browser.crash"),
        default="Page.crash",
    )
    cli = parser.parse_args()
    if cli.persist_check:
        return _persist_check(cli)
    if not cli.frontend or not cli.out:
        parser.error("--frontend and --out are required for the window mode")

    data_root = Path(cli.data)
    credential_root = Path(cli.credential_root)
    frontend = Path(cli.frontend)
    out = Path(cli.out)
    try:
        boundary = _validate_synthetic_paths(data_root, credential_root, out)
        sidecars = _validate_output_directory(out)
    except ValueError as exc:
        print(f"BOUNDARY_INVALID: {exc}", file=sys.stderr)
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)

    args = VerifierArgs(
        data=str(data_root),
        credential_root=str(credential_root),
        frontend=str(frontend),
        selftest=False,
        phase="",
        out=str(out),
        screenshot_dir=None,
        word_out=None,
        b3_config=None,
        u3_config=None,
        u3_source_identity=None,
        u3_verify_stop=None,
        u3_close_cancel=False,
        synthetic_executor_fail=None,
        synthetic_provider_port=None,
        synthetic_provider_ip=None,
        synthetic_provider_ca=None,
    )

    result: dict = {
        "stage": "start",
        "fault_kind": cli.fault_kind,
        "boundary": boundary,
        "prompt_keep": None,
        "prompt_reopen": None,
        "normal_close": None,
        "persist": None,
        "errors": [],
    }
    service = None
    runtime = None
    lifecycle = None
    old_window = None
    old_form = None
    recovery = None
    evidence = None
    before_counts = None
    before_fingerprint = None
    old_ticket = None
    old_host = None
    old_launch_token = None
    old_state = None
    new_host = None
    finished = threading.Event()

    def fail(code: str, exc: BaseException | None = None) -> None:
        result["stage"] = code
        if exc is not None:
            result["errors"].append({"code": code, "type": type(exc).__name__})
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        from tests.local import backup_fixture_support as fixture

        service, host_api, runtime = d1_main.build_runtime(args)
        old_executor = runtime.ai_executor
        # Seed only while the production executor is briefly frozen: the
        # fixture creates terminal/paused receipts, never a real provider call.
        # Unfreeze immediately after seeding so recovery must perform the real
        # owner freeze/atomic stop; verification must not mask ownership.
        if old_executor is not None:
            old_executor.freeze(owner="verifier:seed")
        evidence = fixture.seed_existing_runtime(runtime)
        if old_executor is not None:
            old_executor.unfreeze(owner="verifier:seed")
        if not service.start_and_wait():
            raise RuntimeError(f"service start failed: {service.error}")

        lifecycle = maintenance_lifecycle.LifecycleManager()
        old_window = webview.create_window(
            "幼儿园教师工作台（本地）",
            url=f"http://127.0.0.1:{service.port}/",
            js_api=host_api,
            width=1180,
            height=820,
            min_size=(760, 560),
            text_select=True,
        )
        old_form = old_window.native if old_window is not None else None
        host_api._bind_window(old_window)
        recovery_holder: dict = {}
        d1_main._install_close_handlers(
            old_window,
            host_api,
            runtime,
            weekly_export_manager=getattr(service, "weekly_export_manager", None),
            recovery_holder=recovery_holder,
        )
        bundle = maintenance_lifecycle.LifecycleBundle(
            generation=lifecycle.next_generation(),
            service=service,
            host_api=host_api,
            runtime=runtime,
            window=old_window,
            executor=old_executor,
        )
        lifecycle.install(bundle)
        bundle.retire_destroy = lambda: d1_main._retire_destroy_window(bundle)
        host_api._bind_maintenance(
            d1_main._build_maintenance_host(args, runtime, lifecycle, bundle)
        )
        recovery = d1_main._install_renderer_recovery(
            old_window, host_api, lifecycle, bundle, runtime, args, recovery_holder
        )
        if recovery is None:
            raise RuntimeError("renderer recovery was not installed")

        observation: dict = {}
        runtime_evidence: dict = {}
        observer = _RecoveryObserver()
        old_uid = _window_uid(old_window)
        old_generation = int(getattr(bundle, "generation", 0) or 0)
        old_lock_handle = getattr(runtime, "_lock_handle", None)

        def record_old_window_closed():
            observer.record(
                "old_window.closed",
                window_uid=old_uid,
                host_label="old-host",
                bundle_label="old-bundle",
                generation=old_generation,
                detail={"closed": True},
            )

        try:
            old_window.events.closed += record_old_window_closed
        except Exception:
            pass

        if old_executor is not None:
            original_stop_if_idle = old_executor.stop_if_idle
            stop_calls = {"count": 0}

            def observed_stop_if_idle(*, owner, timeout=5.0):
                stop_calls["count"] += 1
                thread = getattr(old_executor, "_thread", None)
                thread_was_alive = bool(
                    thread is not None and thread.is_alive()
                )
                before = _executor_gate_snapshot(old_executor)
                worker_absent = bool(
                    before.get("active_none")
                    and before.get("pending_empty")
                    and before.get("slots_empty")
                )
                observer.record(
                    "old_stop_if_idle.enter",
                    window_uid=old_uid,
                    host_label="old-host",
                    bundle_label="old-bundle",
                    generation=old_generation,
                    detail={
                        "thread_was_alive": thread_was_alive,
                        "worker_was_absent": worker_absent,
                    },
                )
                try:
                    returned = original_stop_if_idle(
                        owner=owner, timeout=timeout
                    )
                except Exception as exc:  # noqa: BLE001 - preserve original
                    observation["old_executor_stop"] = {
                        "calls": stop_calls["count"],
                        "error_type": type(exc).__name__,
                        "thread_was_present": thread is not None,
                        "thread_was_alive": thread_was_alive,
                        "worker_was_absent": worker_absent,
                    }
                    observer.record(
                        "old_stop_if_idle.return",
                        window_uid=old_uid,
                        host_label="old-host",
                        bundle_label="old-bundle",
                        generation=old_generation,
                        detail={
                            "return": False,
                            "error_type": type(exc).__name__,
                            "worker_was_absent": worker_absent,
                        },
                    )
                    raise
                after = _executor_gate_snapshot(old_executor)
                gate_ok = _executor_gate_ok(after)
                observation["old_executor_stop"] = {
                    "calls": stop_calls["count"],
                    "return": bool(returned),
                    "thread_was_present": thread is not None,
                    "thread_was_alive": thread_was_alive,
                    "thread_alive_after": bool(
                        thread is not None and thread.is_alive()
                    ),
                    "worker_was_absent": worker_absent,
                    "worker_exit_verified": bool(
                        not worker_absent and gate_ok
                    ),
                    "gate_before": before,
                    "gate_after": after,
                    "gate_ok": gate_ok,
                }
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
                        "gate_ok": gate_ok,
                        "worker_was_absent": worker_absent,
                    },
                )
                return returned

            old_executor.stop_if_idle = observed_stop_if_idle

        service_thread = getattr(service, "thread", None)
        original_stop_service = service.stop_and_confirm
        service_calls = {"count": 0}

        def observed_stop_service(timeout=10.0):
            service_calls["count"] += 1
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
            try:
                returned = original_stop_service(timeout)
            except Exception as exc:  # noqa: BLE001 - preserve original
                observation["old_service_stop"] = {
                    "calls": service_calls["count"],
                    "error_type": type(exc).__name__,
                    "thread_was_alive": was_alive,
                }
                observer.record(
                    "old_service_stop.return",
                    window_uid=old_uid,
                    host_label="old-host",
                    bundle_label="old-bundle",
                    generation=old_generation,
                    detail={"return": False, "error_type": type(exc).__name__},
                )
                raise
            observation["old_service_stop"] = {
                "calls": service_calls["count"],
                "return": bool(returned),
                "thread_was_alive": was_alive,
                "thread_alive_after": bool(
                    service_thread is not None and service_thread.is_alive()
                ),
            }
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

        service.stop_and_confirm = observed_stop_service

        original_retire_host = host_api._retire
        retire_calls = {"count": 0}

        def observed_retire_host():
            retire_calls["count"] += 1
            first = retire_calls["count"] == 1
            phase = "old_host_retire" if first else "old_host_retire_idempotent"
            before_state = _host_page_state(host_api)
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
            returned = original_retire_host()
            after_state = _host_page_state(host_api)
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

        host_api._retire = observed_retire_host

        original_close_engine = runtime.close_engine_keep_lock

        def observed_close_engine():
            observer.record(
                "engine_close.enter",
                window_uid=old_uid,
                host_label="old-host",
                bundle_label="old-bundle",
                generation=old_generation,
            )
            observation["lock_before_close"] = _lock_snapshot(
                runtime, old_lock_handle
            )
            returned = original_close_engine()
            observation["lock_after_close"] = _lock_snapshot(
                runtime, old_lock_handle
            )
            observer.record(
                "engine_close.return",
                window_uid=old_uid,
                host_label="old-host",
                bundle_label="old-bundle",
                generation=old_generation,
                detail={"lock_ok": _lock_ok(observation["lock_after_close"])},
            )
            return returned

        runtime.close_engine_keep_lock = observed_close_engine
        original_reopen_after_restore = runtime.reopen_after_restore

        def observed_reopen_after_restore():
            observer.record(
                "engine_reopen.enter",
                window_uid=old_uid,
                host_label="old-host",
                bundle_label="old-bundle",
                generation=old_generation,
            )
            returned = original_reopen_after_restore()
            observation["lock_after_reopen"] = _lock_snapshot(
                runtime, old_lock_handle
            )
            observer.record(
                "engine_reopen.return",
                window_uid=old_uid,
                host_label="old-host",
                bundle_label="old-bundle",
                generation=old_generation,
                detail={"lock_ok": _lock_ok(observation["lock_after_reopen"])},
            )
            return returned

        runtime.reopen_after_restore = observed_reopen_after_restore

        original_install_if_current = lifecycle.install_if_current

        def observed_install_if_current(expected, current_bundle):
            observer.record(
                "new_bundle.install_cas.enter",
                window_uid=_window_uid(getattr(current_bundle, "window", None)),
                host_label="new-host",
                bundle_label="new-bundle",
                generation=int(getattr(current_bundle, "generation", 0) or 0),
                detail={"expected_is_old": expected is bundle},
            )
            installed = bool(original_install_if_current(expected, current_bundle))
            observer.record(
                "new_bundle.install_cas.return",
                window_uid=_window_uid(getattr(current_bundle, "window", None)),
                host_label="new-host",
                bundle_label="new-bundle",
                generation=int(getattr(current_bundle, "generation", 0) or 0),
                detail={"installed": installed},
            )
            if installed:
                _wrap_new_service(current_bundle)
                _wrap_new_business_ready(current_bundle)
            return installed

        lifecycle.install_if_current = observed_install_if_current

        def _wrap_new_service(current_bundle):
            new_service = getattr(current_bundle, "service", None)
            if new_service is None:
                return
            original_start = new_service.start_and_wait

            def observed_start():
                before_start = _second_runtime_refused(runtime)
                observation["second_runtime_before_new_service"] = before_start
                observer.record(
                    "new_service.lock_probe",
                    window_uid=_window_uid(getattr(current_bundle, "window", None)),
                    host_label="new-host",
                    bundle_label="new-bundle",
                    generation=int(getattr(current_bundle, "generation", 0) or 0),
                    detail={
                        "refused": bool(before_start.get("refused")),
                        "error_code": before_start.get("error_code"),
                    },
                )
                observer.record(
                    "new_service.start.enter",
                    window_uid=_window_uid(getattr(current_bundle, "window", None)),
                    host_label="new-host",
                    bundle_label="new-bundle",
                    generation=int(getattr(current_bundle, "generation", 0) or 0),
                )
                started = bool(original_start())
                observer.record(
                    "new_service.start.return",
                    window_uid=_window_uid(getattr(current_bundle, "window", None)),
                    host_label="new-host",
                    bundle_label="new-bundle",
                    generation=int(getattr(current_bundle, "generation", 0) or 0),
                    detail={"started": started},
                )
                return started

            new_service.start_and_wait = observed_start

        def _wrap_new_business_ready(current_bundle):
            new_host = getattr(current_bundle, "host_api", None)
            if new_host is None:
                return
            original_wait = new_host._wait_business_ready

            def observed_wait(timeout):
                observer.record(
                    "new_business_ready.enter",
                    window_uid=_window_uid(getattr(current_bundle, "window", None)),
                    host_label="new-host",
                    bundle_label="new-bundle",
                    generation=int(getattr(current_bundle, "generation", 0) or 0),
                )
                ready = bool(original_wait(timeout))
                state = _host_page_state(new_host)
                observer.record(
                    "new_business_ready.return",
                    window_uid=_window_uid(getattr(current_bundle, "window", None)),
                    host_label="new-host",
                    bundle_label="new-bundle",
                    generation=int(getattr(current_bundle, "generation", 0) or 0),
                    detail={
                        "ready": ready,
                        "business_ready": bool(state.get("business_ready")),
                    },
                )
                return ready

            new_host._wait_business_ready = observed_wait

        original_retire_destroy = bundle.retire_destroy

        def observed_retire_destroy():
            current = lifecycle.current()
            current_service = getattr(current, "service", None)
            current_host = getattr(current, "host_api", None)
            current_executor = getattr(current, "executor", None)
            current_state = (
                _host_page_state(current_host) if current_host is not None else {}
            )
            current_thread = getattr(current_service, "thread", None)
            current_server = getattr(current_service, "server", None)
            native = getattr(old_window, "native", None)
            observation["old_destroy"] = {
                "called": True,
                "old_form_alive_before": _ui_form_alive(native),
                "current_is_new": bool(
                    current is not None and current is not bundle
                ),
                "new_window_distinct": bool(
                    current is not None
                    and getattr(current, "window", None) is not old_window
                ),
                "new_host_distinct": bool(
                    current_host is not None and current_host is not host_api
                ),
                "new_service_distinct": bool(
                    current_service is not None and current_service is not service
                ),
                "current_executor_present": current_executor is not None,
                "current_executor_distinct": bool(
                    current_executor is not None
                    and current_executor is not old_executor
                ),
                "current_executor_is_bundle": bool(
                    current_executor is getattr(current, "executor", None)
                ),
                "current_executor_is_runtime": bool(
                    current_executor is getattr(runtime, "ai_executor", None)
                ),
                "fresh_executor_ok": _fresh_executor_ok(
                    current_executor, old_executor, current, runtime
                ),
                "new_generation": getattr(current, "generation", None),
                "new_service_started": bool(
                    current_thread is not None
                    and current_thread.is_alive()
                    and getattr(current_server, "started", False)
                ),
                "new_page_ready": bool(current_state.get("page_ready")),
                "new_ticket_bound": bool(current_state.get("ticket_bound")),
                "new_business_ready": bool(current_state.get("business_ready")),
                "new_window_visible": _window_visible(
                    getattr(current, "window", None)
                ),
                "new_document_generation": current_state.get(
                    "document_generation"
                ),
            }
            observer.record(
                "old_destroy.enter",
                window_uid=old_uid,
                host_label="old-host",
                bundle_label="old-bundle",
                generation=old_generation,
                detail={
                    "old_form_alive_before": observation["old_destroy"][
                        "old_form_alive_before"
                    ],
                    "new_business_ready": observation["old_destroy"][
                        "new_business_ready"
                    ],
                    "new_window_visible": observation["old_destroy"][
                        "new_window_visible"
                    ],
                    "new_document_generation": observation["old_destroy"][
                        "new_document_generation"
                    ],
                    "fresh_executor_ok": observation["old_destroy"][
                        "fresh_executor_ok"
                    ],
                },
            )
            original_retire_destroy()
            old_form_alive_after = _ui_form_alive(
                getattr(old_window, "native", None)
            )
            observation["old_destroy"]["old_form_alive_after"] = (
                old_form_alive_after
            )
            observer.record(
                "old_destroy.return",
                window_uid=old_uid,
                host_label="old-host",
                bundle_label="old-bundle",
                generation=old_generation,
                detail={"old_form_alive_after": old_form_alive_after},
            )

        bundle.retire_destroy = observed_retire_destroy

        def driver():
            nonlocal old_form, old_ticket, old_host, before_counts, recovery
            nonlocal before_fingerprint, old_launch_token, old_state, new_host
            try:
                if not old_window.events.loaded.wait(30):
                    fail("page_not_loaded")
                    return
                old_form = old_window.native
                if old_form is None:
                    fail("native_form_missing")
                    return
                if not host_api._wait_business_ready(60):
                    fail("business_not_ready")
                    return
                old_host = host_api
                old_state = _host_page_state(old_host)
                result["old_page_state"] = _public_host_state(old_state)
                if not _active_page(old_state):
                    fail("old_page_not_bound_business_ready")
                    return
                old_ticket = old_state["ticket"]
                old_launch_token = str(old_state["launch_token"] or "")
                old_port = int(getattr(service, "port", 0) or 0)
                old_status = _readonly_status(old_port, old_launch_token)
                result["old_port"] = old_port
                result["old_port_token_status"] = old_status
                if old_status != 200:
                    fail("old_port_token_baseline_failed")
                    return
                before_counts = _query_counts(runtime)
                before_fingerprint = fixture.runtime_fingerprint(runtime)
                if before_fingerprint != evidence.fingerprint:
                    fail("fixture_fingerprint_mismatch_before")
                    return
                fixture.validate_fixture(runtime, evidence)
                result["fixture_validation_before"] = "ok"
                result["before_counts"] = before_counts
                result["before_archive_fingerprint"] = _fingerprint_summary(
                    before_fingerprint
                )
                result["fixture_fingerprint"] = before_fingerprint["combined_sha256"]
                before_runtime_fingerprint = fixture.runtime_fingerprint(
                    runtime, include_runtime_fields=True
                )
                runtime_evidence["before"] = before_runtime_fingerprint
                result["before_runtime_fingerprint"] = _fingerprint_summary(
                    before_runtime_fingerprint
                )
                result["before_runtime_fingerprint_sha256"] = (
                    before_runtime_fingerprint.get("combined_sha256")
                )

                old_engine = runtime.engine
                held_session = runtime.session()
                held_session.execute(text("SELECT 1")).scalar_one()
                old_engine_connect_before = False
                old_engine_connect_before_error = None
                try:
                    with old_engine.connect() as connection:
                        connection.execute(text("SELECT 1")).scalar_one()
                    old_engine_connect_before = True
                except Exception as exc:  # noqa: BLE001 - safe type only
                    old_engine_connect_before_error = type(exc).__name__
                observation["old_engine_initial"] = {
                    "present": old_engine is not None,
                    "engine_connect_ok": old_engine_connect_before,
                    "engine_connect_error_type": old_engine_connect_before_error,
                    "session_select_ok": True,
                }
                if not old_engine_connect_before:
                    fail("old_engine_connect_before_failed")
                    return
                weekly_token, weekly_kwargs = _issue_weekly_identity(
                    runtime, evidence.profile_id
                )
                observation["weekly_identity_issued"] = True
                adoption_identities, adoption_before = (
                    _issue_adoption_store_identities()
                )
                observation["adoption_store_issued"] = bool(adoption_before)
                if not adoption_before:
                    fail("adoption_store_issue_failed")
                    return
                observation["second_runtime_before"] = _second_runtime_refused(
                    runtime
                )

                def crash_on_ui():
                    form = old_window.native
                    browser = getattr(form, "browser", None)
                    control = getattr(browser, "webview", None)
                    core = getattr(control, "CoreWebView2", None)
                    ownership = {
                        "form_current": form is not None
                        and _managed_reference_equal(form, old_form),
                        "form_owns_window": (
                            form is not None
                            and getattr(form, "pywebview_window", None)
                            is old_window
                        ),
                        "browser_owns_window": (
                            browser is not None
                            and getattr(browser, "pywebview_window", None)
                            is old_window
                        ),
                        "webview_identity": (
                            control is not None
                            and _managed_reference_equal(
                                control, getattr(form, "webview", None)
                            )
                            and _managed_reference_equal(
                                control, getattr(browser, "webview", None)
                            )
                        ),
                        "core_present": core is not None,
                    }
                    result["crash_ownership"] = ownership
                    if not all(ownership.values()):
                        return "ownership"
                    result["crash_browser_pid"] = int(core.BrowserProcessId)
                    result["crash_kind"] = cli.fault_kind
                    core.CallDevToolsProtocolMethodAsync(cli.fault_kind, "{}")
                    return "sent"

                sent = old_form.Invoke(Func[Object](crash_on_ui))
                result["crash_send"] = str(sent)
                if sent != "sent":
                    fail("crash_not_sent")
                    return
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline and not recovery.faulted:
                    time.sleep(0.05)
                if not recovery.faulted:
                    fail("fault_not_observed")
                    return
                fault_evidence = _fault_evidence(recovery)
                result["observed_fault"] = fault_evidence
                expected_fault_kind = (
                    "RenderProcessExited"
                    if cli.fault_kind == "Page.crash"
                    else "BrowserProcessExited"
                )
                if (
                    fault_evidence.get("kind") != expected_fault_kind
                    or fault_evidence.get("generation") != old_generation
                ):
                    fail("fault_evidence_mismatch")
                    return
                observer.record(
                    "recovery.fault",
                    window_uid=old_uid,
                    host_label="old-host",
                    bundle_label="old-bundle",
                    generation=old_generation,
                    detail=fault_evidence,
                )

                prompt_enter = _prompt_action(old_form, "enter", 20)
                result["prompt_keep"] = prompt_enter
                result["prompt_actions"] = {"enter": prompt_enter}
                if not prompt_enter.get("ok"):
                    fail("prompt_enter_" + str(prompt_enter.get("reason") or "failed"))
                    return
                if not recovery._worker_done.wait(15):
                    fail("keep_worker_timeout")
                    return
                result["keep_enter_state"] = recovery.state
                if recovery.state != recovery.KEPT:
                    fail("keep_state_wrong")
                    return
                if not _ui_form_alive(old_form):
                    fail("old_window_lost_after_keep")
                    return

                owner_close_escape = _owner_native_close(old_form)
                result["owner_close_escape"] = owner_close_escape
                if not owner_close_escape.get("ok"):
                    fail(
                        "owner_native_close_"
                        + str(owner_close_escape.get("reason") or "failed")
                    )
                    return
                prompt_escape = _prompt_action(old_form, "escape", 20)
                result["prompt_actions"]["escape"] = prompt_escape
                if not prompt_escape.get("ok"):
                    fail("prompt_escape_" + str(prompt_escape.get("reason") or "failed"))
                    return
                if not recovery._worker_done.wait(15):
                    fail("escape_worker_timeout")
                    return
                result["keep_escape_state"] = recovery.state
                if recovery.state != recovery.KEPT:
                    fail("escape_keep_state_wrong")
                    return
                if not _ui_form_alive(old_form):
                    fail("old_window_lost_after_escape")
                    return

                owner_close_x = _owner_native_close(old_form)
                result["owner_close_x"] = owner_close_x
                if not owner_close_x.get("ok"):
                    fail(
                        "owner_native_close_"
                        + str(owner_close_x.get("reason") or "failed")
                    )
                    return
                prompt_x = _prompt_action(old_form, "x", 20)
                result["prompt_actions"]["x"] = prompt_x
                if not prompt_x.get("ok"):
                    fail("prompt_x_" + str(prompt_x.get("reason") or "failed"))
                    return
                if not recovery._worker_done.wait(15):
                    fail("x_worker_timeout")
                    return
                result["keep_x_state"] = recovery.state
                if recovery.state != recovery.KEPT:
                    fail("x_keep_state_wrong")
                    return
                if not _ui_form_alive(old_form):
                    fail("old_window_lost_after_x")
                    return

                owner_close_reopen = _owner_native_close(old_form)
                result["owner_close_reopen"] = owner_close_reopen
                if not owner_close_reopen.get("ok"):
                    fail(
                        "owner_native_close_"
                        + str(owner_close_reopen.get("reason") or "failed")
                    )
                    return
                prompt_reopen = _prompt_action(old_form, "reopen_click", 20)
                result["prompt_reopen"] = prompt_reopen
                result["prompt_actions"]["reopen_click"] = prompt_reopen
                if not prompt_reopen.get("ok"):
                    fail(
                        "prompt_reopen_"
                        + str(prompt_reopen.get("reason") or "failed")
                    )
                    return
                recovery_worker = recovery._worker
                if (
                    recovery_worker is None
                    or recovery_worker.ident is None
                    or not recovery_worker.is_alive()
                ):
                    fail("recovery_worker_unavailable")
                    return
                recovery_worker_thread = int(recovery_worker.ident)
                result["recovery_worker_thread"] = recovery_worker_thread
                if not recovery._worker_done.wait(90):
                    fail("reopen_worker_timeout")
                    return
                result["reopen_state"] = recovery.state
                if recovery.state != recovery.RECOVERED:
                    fail("reopen_failed")
                    return

                new_bundle = lifecycle.current()
                new_window = getattr(new_bundle, "window", None)
                if new_window is None or new_window is old_window:
                    fail("new_window_missing")
                    return
                if not new_window.events.loaded.wait(30):
                    fail("new_window_not_loaded")
                    return
                result["new_window_uid"] = str(getattr(new_window, "uid", ""))
                result["old_window_alive_after_reopen"] = _ui_form_alive(old_form)
                if _ui_form_alive(old_form):
                    fail("old_window_still_alive")
                    return
                closed_events = [
                    event
                    for event in observer.snapshot()
                    if event.get("phase") == "old_window.closed"
                ]
                old_window_closed = bool(closed_events)
                result["old_window_closed_event"] = old_window_closed
                if not old_window_closed:
                    fail("old_window_closed_event_missing")
                    return

                new_host = getattr(new_bundle, "host_api", None)
                if new_host is None:
                    fail("new_host_missing")
                    return
                new_state = _host_page_state(new_host)
                result["new_page_state"] = _public_host_state(new_state)
                if not _active_page(new_state):
                    fail("new_page_not_bound_business_ready")
                    return

                new_executor = getattr(new_bundle, "executor", None)
                observation["second_runtime_after"] = _second_runtime_refused(
                    runtime
                )
                old_engine_connection = None
                old_engine_error = None
                try:
                    old_engine_connection = old_engine.connect()
                except Exception as exc:  # noqa: BLE001 - safe type only
                    old_engine_error = type(exc).__name__
                finally:
                    if old_engine_connection is not None:
                        try:
                            old_engine_connection.close()
                        except Exception:  # noqa: BLE001 - cleanup only
                            pass
                old_session_error = _safe_exception_type(
                    lambda: held_session.execute(text("SELECT 1"))
                )
                new_engine_error = None
                new_session_error = None
                try:
                    with runtime.engine.connect() as connection:
                        connection.execute(text("SELECT 1")).scalar_one()
                except Exception as exc:  # noqa: BLE001 - safe type only
                    new_engine_error = type(exc).__name__
                if new_engine_error is None:
                    try:
                        new_session = runtime.session()
                        try:
                            new_session.execute(text("SELECT 1")).scalar_one()
                        finally:
                            new_session.close()
                    except Exception as exc:  # noqa: BLE001 - safe type only
                        new_session_error = type(exc).__name__
                observation["engine_session"] = {
                    "old_engine_rejected": old_engine_error is not None,
                    "old_engine_error_type": old_engine_error,
                    "old_session_rejected": old_session_error is not None,
                    "old_session_error_type": old_session_error,
                    "new_engine_session_ok": (
                        new_engine_error is None and new_session_error is None
                    ),
                    "new_engine_session_error_type": new_engine_error
                    or new_session_error,
                }
                observation["weekly_identity_rejected"] = _weekly_identity_rejected(
                    runtime, weekly_token, weekly_kwargs
                )
                observation["adoption_store_retired"] = (
                    _adoption_store_identities_retired(adoption_identities)
                )
                observation["old_callback_isolation"] = _old_callback_probe(
                    recovery, new_host, new_executor
                )

                after_counts = _query_counts(runtime)
                after_fingerprint = fixture.runtime_fingerprint(runtime)
                result["after_counts"] = after_counts
                result["after_archive_fingerprint"] = _fingerprint_summary(
                    after_fingerprint
                )
                archive_unchanged = bool(
                    after_fingerprint == before_fingerprint == evidence.fingerprint
                )
                result["archive_fingerprint_unchanged"] = archive_unchanged
                if after_counts != before_counts:
                    fail("task_or_attempt_delta")
                    return
                if not archive_unchanged:
                    fail("archive_fingerprint_changed")
                    return
                after_runtime_fingerprint = fixture.runtime_fingerprint(
                    runtime, include_runtime_fields=True
                )
                runtime_evidence["after"] = after_runtime_fingerprint
                runtime_fingerprint_unchanged = bool(
                    after_runtime_fingerprint == before_runtime_fingerprint
                )
                result["after_runtime_fingerprint"] = _fingerprint_summary(
                    after_runtime_fingerprint
                )
                result["after_runtime_fingerprint_sha256"] = (
                    after_runtime_fingerprint.get("combined_sha256")
                )
                result["runtime_fingerprint_unchanged"] = (
                    runtime_fingerprint_unchanged
                )
                if not runtime_fingerprint_unchanged:
                    fail("runtime_fingerprint_changed")
                    return
                old_executor_stop = observation.get("old_executor_stop") or {}
                old_stopped = bool(
                    old_executor is not None
                    and old_executor_stop.get("calls") == 1
                    and old_executor_stop.get("return") is True
                    and old_executor_stop.get("thread_was_present") is True
                    and old_executor_stop.get("thread_was_alive") is True
                    and old_executor_stop.get("thread_alive_after") is False
                    and old_executor_stop.get("gate_ok") is True
                )
                result["old_executor_stopped"] = old_stopped
                result["old_executor_stop"] = old_executor_stop
                result["worker_was_absent"] = bool(
                    old_executor_stop.get("worker_was_absent")
                )
                result["worker_exit_verified"] = bool(
                    old_executor_stop.get("worker_exit_verified")
                )
                if not old_stopped:
                    fail("old_executor_not_stopped")
                    return
                old_service_stop = observation.get("old_service_stop") or {}
                service_stopped = bool(
                    old_service_stop.get("calls") == 1
                    and old_service_stop.get("return") is True
                    and old_service_stop.get("thread_was_alive") is True
                    and old_service_stop.get("thread_alive_after") is False
                )
                result["old_service_stopped"] = service_stopped
                if not service_stopped:
                    fail("old_service_not_stopped")
                    return
                lock_after_reopen = observation.get("lock_after_reopen") or {}
                result["lock_after_reopen"] = lock_after_reopen
                lock_checks = {
                    key: _lock_ok(observation.get(key) or {})
                    for key in (
                        "lock_before_close",
                        "lock_after_close",
                        "lock_after_reopen",
                    )
                }
                result["lock_checks"] = lock_checks
                if not all(lock_checks.values()):
                    fail("runtime_lock_not_preserved")
                    return
                if not (
                    observation.get("second_runtime_before", {}).get("refused")
                    and observation.get("second_runtime_after", {}).get("refused")
                ):
                    fail("second_runtime_acquired_lock")
                    return
                engine_session = observation.get("engine_session") or {}
                if not (
                    engine_session.get("old_engine_rejected")
                    and engine_session.get("old_session_rejected")
                    and engine_session.get("new_engine_session_ok")
                ):
                    fail("engine_session_handoff_incomplete")
                    return
                if (
                    engine_session.get("old_engine_error_type") != "RuntimeError"
                    or engine_session.get("old_session_error_type")
                    != "RuntimeError"
                ):
                    fail("engine_retirement_type_unexpected")
                    return
                second_before = observation.get("second_runtime_before") or {}
                second_after = observation.get("second_runtime_after") or {}
                second_before_new_service = (
                    observation.get("second_runtime_before_new_service") or {}
                )
                if not (
                    second_before.get("refused")
                    and second_before.get("error_code")
                    == "LOCAL_APP_ALREADY_RUNNING"
                    and second_after.get("refused")
                    and second_after.get("error_code")
                    == "LOCAL_APP_ALREADY_RUNNING"
                    and second_before_new_service.get("refused")
                    and second_before_new_service.get("error_code")
                    == "LOCAL_APP_ALREADY_RUNNING"
                ):
                    fail("second_runtime_lock_not_proven")
                    return
                weekly_rejected = observation.get("weekly_identity_rejected") or {}
                if (
                    not weekly_rejected.get("rejected")
                    or weekly_rejected.get("error_type")
                    != "LocalWeeklyPreviewStale"
                ):
                    fail("weekly_identity_reused")
                    return
                adoption_retired = observation.get("adoption_store_retired") or {}
                if not (
                    adoption_retired.get("daily_retired")
                    and adoption_retired.get("weekly_retired")
                ):
                    fail("adoption_store_identity_not_retired")
                    return
                try:
                    fixture.validate_fixture(runtime, evidence)
                except Exception as exc:  # noqa: BLE001 - fixture is authoritative
                    result["fixture_validation_error"] = type(exc).__name__
                    fail("saved_data_validation_failed", exc)
                    return
                result["saved_data"] = "ok"
                result["fixture_validation_after"] = "ok"
                result["task_attempt_ai_receipts_unchanged"] = bool(
                    after_fingerprint["database"]["tables"]
                    == before_fingerprint["database"]["tables"]
                )

                old_after = _host_page_state(old_host)
                result["old_host_state_after"] = _public_host_state(old_after)
                result["old_host_retired"] = bool(
                    old_after.get("retired")
                    and not old_after.get("page_ready")
                )
                if not result["old_host_retired"]:
                    fail("old_host_not_retired")
                    return
                old_host_calls = _old_host_call_probe(old_host, old_ticket)
                result["old_host_calls"] = old_host_calls
                if not (
                    old_host_calls.get("accepted_false")
                    and old_host_calls.get("retired_guard")
                    and old_host_calls.get("state_unchanged")
                ):
                    fail("old_host_calls_not_rejected")
                    return
                old_destroy = observation.get("old_destroy") or {}
                result["old_destroy_observation"] = old_destroy
                old_destroy_ok = bool(
                    old_destroy.get("called") is True
                    and old_destroy.get("old_form_alive_before") is True
                    and old_destroy.get("current_is_new") is True
                    and old_destroy.get("new_window_distinct") is True
                    and old_destroy.get("new_host_distinct") is True
                    and old_destroy.get("new_service_distinct") is True
                    and old_destroy.get("fresh_executor_ok") is True
                    and old_destroy.get("current_executor_distinct") is True
                    and old_destroy.get("new_service_started") is True
                    and old_destroy.get("new_page_ready") is True
                    and old_destroy.get("new_ticket_bound") is True
                    and old_destroy.get("new_business_ready") is True
                    and old_destroy.get("new_window_visible") is True
                    and int(old_destroy.get("new_generation") or 0)
                    > int(getattr(bundle, "generation", 0) or 0)
                )
                if not old_destroy_ok:
                    fail("old_destroy_order_or_ownership_wrong")
                    return
                events = observer.snapshot()
                result["events"] = events
                event_sequence_ok = _event_sequence_ok(
                    events,
                    old_generation=old_generation,
                    new_generation=int(getattr(new_bundle, "generation", 0) or 0),
                    old_uid=old_uid,
                    new_uid=_window_uid(new_window),
                    worker_thread=recovery_worker_thread,
                )
                result["event_sequence_ok"] = event_sequence_ok
                if not event_sequence_ok:
                    fail("event_sequence_invalid")
                    return
                old_callback = observation.get("old_callback_isolation") or {}
                result["old_callback_isolation"] = old_callback
                if not (
                    old_callback.get("state_unchanged")
                    and old_callback.get("freeze_owners_unchanged")
                    and old_callback.get("close_state_unchanged")
                ):
                    fail("old_callback_changed_new_generation")
                    return
                result["recovery_notice"] = new_state.get("maintenance_notice")
                if result["recovery_notice"] != renderer_recovery.RECOVERY_NOTICE:
                    fail("recovery_notice_missing")
                    return
                new_ticket = new_state.get("ticket")
                new_launch_token = new_state.get("launch_token")
                result["new_ticket_changed"] = bool(
                    old_ticket and new_ticket and new_ticket != old_ticket
                )
                result["launch_token_changed"] = bool(
                    old_launch_token
                    and new_launch_token
                    and new_launch_token != old_launch_token
                )
                result["old_ticket_fingerprint"] = _fingerprint(old_ticket)
                result["new_ticket_fingerprint"] = _fingerprint(new_ticket)
                result["old_launch_fingerprint"] = _fingerprint(old_launch_token)
                result["new_launch_fingerprint"] = _fingerprint(new_launch_token)
                if not result["new_ticket_changed"]:
                    fail("page_ticket_reused")
                    return
                if not result["launch_token_changed"]:
                    fail("launch_token_reused")
                    return

                before_ticket_submission = _host_page_state(new_host)
                result["old_ticket_submission_before"] = _public_host_state(
                    before_ticket_submission
                )
                submission = new_host.page_business_ready(
                    {"page_ticket": old_ticket}
                )
                after_ticket_submission = _host_page_state(new_host)
                submission_state_unchanged = bool(
                    before_ticket_submission == after_ticket_submission
                )
                result["old_ticket_submission"] = {
                    "accepted": submission.get("accepted"),
                    "state_unchanged": submission_state_unchanged,
                    "after": _public_host_state(after_ticket_submission),
                }
                if (
                    submission.get("accepted") is not False
                    or not submission_state_unchanged
                ):
                    fail("old_ticket_not_rejected_cleanly")
                    return
                result["old_ticket_rejected"] = True

                new_port = int(new_bundle.service.port)
                old_status = _readonly_status(new_port, old_launch_token)
                new_status = _readonly_status(new_port, new_launch_token)
                result["new_port_old_token_status"] = old_status
                result["new_port_new_token_status"] = new_status
                if old_status != 401 or new_status != 200:
                    fail("new_port_token_auth_failed")
                    return
                result["new_port_auth"] = "ok"

                new_form = getattr(new_window, "native", None)
                if new_form is None:
                    fail("new_form_missing")
                    return
                result["normal_close"] = "issued"
                result["normal_close_method"] = "Form.Close"
                new_form.Invoke(Action(lambda: new_form.Close()))
                if not new_window.events.closed.wait(45):
                    fail("new_window_close_timeout")
                    return
                result["normal_close"] = "closed"
                closed_runtime_fingerprint = fixture.runtime_fingerprint(
                    runtime, include_runtime_fields=True
                )
                runtime_evidence["closed"] = closed_runtime_fingerprint
                closed_runtime_unchanged = bool(
                    closed_runtime_fingerprint == before_runtime_fingerprint
                )
                result["closed_runtime_fingerprint"] = _fingerprint_summary(
                    closed_runtime_fingerprint
                )
                result["closed_runtime_fingerprint_sha256"] = (
                    closed_runtime_fingerprint.get("combined_sha256")
                )
                result["closed_runtime_fingerprint_unchanged"] = (
                    closed_runtime_unchanged
                )
                if not closed_runtime_unchanged:
                    fail("closed_runtime_fingerprint_changed")
                    return
                result["stage"] = "reopened"
            except Exception as exc:  # noqa: BLE001 - verifier boundary
                fail("driver_exception", exc)
            finally:
                if result.get("stage") != "reopened":
                    result["cleanup"] = "controlled_retire_after_failure"
                    out.write_text(
                        json.dumps(result, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    cleanup = _controlled_retire_failure(
                        recovery, bundle, old_window
                    )
                    result["cleanup_steps"] = cleanup["steps"]
                finished.set()
                out.write_text(
                    json.dumps(result, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

        def watchdog():
            if not finished.wait(180):
                fail("watchdog_timeout")
                os._exit(3)

        threading.Thread(target=watchdog, daemon=True).start()
        result["stage"] = "window_start"
        webview.start(gui="edgechromium", func=driver, debug=False)
        finished.set()
        result["webview_start_returned"] = True

        try:
            if lifecycle is not None:
                result["close_latest"] = bool(lifecycle.close_latest(timeout=10.0))
        except Exception as exc:  # noqa: BLE001 - report only
            result["close_latest_error"] = type(exc).__name__

        # True child-process full fingerprint readback after a cold LocalRuntime
        # prepare; no window, JS, provider or AI, and no data copy.
        try:
            expected_path = sidecars["expected"]
            child_path = sidecars["child"]
            if before_fingerprint is None:
                raise RuntimeError("before fingerprint missing")
            if "before" not in runtime_evidence:
                raise RuntimeError("before runtime fingerprint missing")
            expected_path.write_text(
                json.dumps(
                    {
                        "fingerprint": before_fingerprint,
                        "table_counts": before_counts,
                        "runtime_fingerprint": runtime_evidence["before"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["APP_DISABLE_DOTENV"] = "1"
            child = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--persist-check",
                    "--data",
                    str(data_root),
                    "--credential-root",
                    str(credential_root),
                    "--expected-fingerprint",
                    str(expected_path),
                    "--persist-out",
                    str(child_path),
                ],
                cwd=str(Path(__file__).resolve().parent.parent),
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            child_result = (
                json.loads(child_path.read_text(encoding="utf-8"))
                if child_path.is_file()
                else {}
            )
            result["persist_subprocess"] = {
                "exit": child.returncode,
                "fingerprint_match": bool(child_result.get("fingerprint_match")),
                "runtime_fingerprint_match": bool(
                    child_result.get("runtime_fingerprint_match")
                ),
                "counts_match": bool(child_result.get("counts_match")),
                "combined_sha256": child_result.get("combined_sha256"),
                "runtime_combined_sha256": child_result.get(
                    "runtime_combined_sha256"
                ),
                "database_sha256": child_result.get("database_sha256"),
                "resources_sha256": child_result.get("resources_sha256"),
                "integrity_check": child_result.get("integrity_check"),
                "foreign_key_ok": bool(child_result.get("foreign_key_ok")),
            }
            if (
                child.returncode == 0
                and child_result.get("fingerprint_match")
                and child_result.get("runtime_fingerprint_match")
                and child_result.get("counts_match")
                and child_result.get("integrity_check") == "ok"
                and child_result.get("foreign_key_ok")
            ):
                result["persist"] = "ok"
            else:
                result["persist"] = "failed"
                result["persist_error"] = "PERSIST_SUBPROCESS"
        except Exception as exc:  # noqa: BLE001 - persistent evidence
            result["persist"] = "failed"
            result["persist_error"] = type(exc).__name__

        result["observations"] = observation
        prompt_actions = result.get("prompt_actions") or {}
        observation_ok = bool(
            result.get("old_executor_stopped") is True
            and result.get("old_service_stopped") is True
            and result.get("runtime_fingerprint_unchanged") is True
            and result.get("closed_runtime_fingerprint_unchanged") is True
            and (result.get("persist_subprocess") or {}).get(
                "runtime_fingerprint_match"
            )
            is True
            and (result.get("observed_fault") or {}).get("kind")
            in ("RenderProcessExited", "BrowserProcessExited")
            and (
                result.get("worker_was_absent") is True
                or result.get("worker_exit_verified") is True
            )
            and all((result.get("lock_checks") or {}).values())
            and observation.get("second_runtime_before", {}).get("refused")
            and observation.get("second_runtime_after", {}).get("refused")
            and (observation.get("engine_session") or {}).get(
                "old_engine_rejected"
            )
            and (observation.get("engine_session") or {}).get(
                "old_session_rejected"
            )
            and (observation.get("engine_session") or {}).get(
                "new_engine_session_ok"
            )
            and (observation.get("engine_session") or {}).get(
                "old_engine_error_type"
            )
            == "RuntimeError"
            and (observation.get("engine_session") or {}).get(
                "old_session_error_type"
            )
            == "RuntimeError"
            and (observation.get("weekly_identity_rejected") or {}).get(
                "error_type"
            )
            == "LocalWeeklyPreviewStale"
            and (observation.get("adoption_store_retired") or {}).get(
                "daily_retired"
            )
            and (observation.get("adoption_store_retired") or {}).get(
                "weekly_retired"
            )
            and observation.get("adoption_store_issued") is True
            and (observation.get("second_runtime_before") or {}).get(
                "error_code"
            )
            == "LOCAL_APP_ALREADY_RUNNING"
            and (observation.get("second_runtime_after") or {}).get(
                "error_code"
            )
            == "LOCAL_APP_ALREADY_RUNNING"
            and (observation.get("second_runtime_before_new_service") or {}).get(
                "error_code"
            )
            == "LOCAL_APP_ALREADY_RUNNING"
            and (observation.get("weekly_identity_rejected") or {}).get(
                "rejected"
            )
            and (observation.get("old_destroy") or {}).get("called")
            and (observation.get("old_destroy") or {}).get("new_business_ready")
            and (observation.get("old_destroy") or {}).get("new_window_visible")
            and result.get("event_sequence_ok") is True
            and result.get("old_window_closed_event") is True
            and (result.get("old_host_calls") or {}).get("accepted_false")
            and (result.get("old_host_calls") or {}).get("retired_guard")
            and (result.get("old_host_calls") or {}).get("state_unchanged")
            and (observation.get("old_callback_isolation") or {}).get(
                "state_unchanged"
            )
            and (observation.get("old_callback_isolation") or {}).get(
                "freeze_owners_unchanged"
            )
            and (observation.get("old_callback_isolation") or {}).get(
                "close_state_unchanged"
            )
            and all(
                (prompt_actions.get(action) or {}).get("ok")
                for action in ("enter", "escape", "x", "reopen_click")
            )
        )
        result["observation_ok"] = observation_ok
        success = bool(
            result.get("stage") == "reopened"
            and result.get("normal_close") == "closed"
            and result.get("close_latest") is True
            and result.get("persist") == "ok"
            and result.get("archive_fingerprint_unchanged") is True
            and result.get("task_attempt_ai_receipts_unchanged") is True
            and result.get("fixture_validation_before") == "ok"
            and result.get("fixture_validation_after") == "ok"
            and result.get("old_host_retired") is True
            and result.get("old_ticket_rejected") is True
            and result.get("new_ticket_changed") is True
            and result.get("launch_token_changed") is True
            and result.get("new_port_auth") == "ok"
            and observation_ok is True
        )
        result["success"] = success
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if success else 1
    except Exception as exc:  # noqa: BLE001 - verifier boundary
        fail("top_level_exception", exc)
        return 1
    finally:
        # Never leave this verifier's own windows/services behind on failure.
        # A failed fault window is retired explicitly; never run its normal
        # Close path again, which would reopen the prompt and hang cleanup.
        if (
            result.get("stage") != "reopened"
            and "cleanup_steps" not in result
        ):
            result["cleanup"] = "controlled_retire_after_failure"
            cleanup = _controlled_retire_failure(
                recovery, locals().get("bundle"), old_window
            )
            result["cleanup_steps"] = cleanup["steps"]
        try:
            if lifecycle is not None and lifecycle.current() is not None:
                lifecycle.close_latest(timeout=10.0)
        except Exception:
            pass
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
