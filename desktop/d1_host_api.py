"""D1 restricted pywebview host API and the close-handshake coordinator.

Close protocol (D1 spec §11.3), host side:

- the pywebview ``closing`` event immediately returns ``False`` and, outside
  the synchronous UI callback, asks the page to complete the close with a
  ``close_request_id``;
- ``complete_close(allow=true)`` only sets a one-shot allow flag and calls
  ``destroy``; the re-entered ``closing`` event consumes the flag exactly
  once and lets the window close; if the re-entry revokes the allow (a save
  started in between), ``complete_close`` reports the real canceled state
  instead of a preset success;
- the 30s timeout only cancels a request whose final closing was never
  allowed; after the final closing is allowed the state stays ``closing``
  and waiting timeouts never unlock the page;
- a failed ``destroy`` revokes the flag and notifies the page.

Save protocol (§12.3): ``save_docx`` binds one operation id to the
filename + payload SHA256 fingerprint, uses the native Save As dialog (or
the verification-only pre-authorized directory), writes via a sibling
temporary file + atomic replace, and distinguishes
saved/canceled/failed/unknown; ``get_save_result`` answers by operation id
without ever writing again.
"""

from __future__ import annotations

import base64
import binascii
import errno
import hashlib
import hmac
import io
import json
import os
import secrets
import tempfile
import threading
import time
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import webview

import d1_paths

BRIDGE_PROTOCOL = 1
CLOSE_TIMEOUT_SECONDS = 30.0
MAX_DOCX_BYTES = 30 * 1024 * 1024

# The complete set of bridge endpoints exposed to the page. Every other
# attribute (coordinators, notification helpers) stays private (``_``) so
# pywebview's recursive js_api exposure cannot reach it.
BRIDGE_ALLOWED_ENDPOINTS = frozenset(
    {
        "get_bootstrap",
        "get_app_identity",
        "check_for_update",
        "start_update_download",
        "cancel_update_download",
        "install_update",
        "get_update_state",
        "page_ready",
        "set_page_busy",
        "complete_close",
        "get_close_state",
        "save_docx",
        "get_save_result",
    }
)

# Required Word parts for a file to be accepted as a DOCX payload (spec
# §12.3: non-empty DOCX, invalid ZIP / missing parts refused before the
# atomic replace commit point). Each required part must also be non-empty,
# parse as XML and carry the correct root element (R13): a ZIP member that
# merely exists is not a valid DOCX.
_DOCX_REQUIRED_PARTS = (
    "[Content_Types].xml",
    "word/document.xml",
)
_XML_ROOTS = {
    "[Content_Types].xml": (
        "{http://schemas.openxmlformats.org/package/2006/content-types}Types"
    ),
    "word/document.xml": (
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}document"
    ),
}
_SAVE_DIALOG = getattr(
    getattr(webview, "FileDialog", None), "SAVE", getattr(webview, "SAVE_DIALOG", 2)
)
_WORD_TYPES = ("Word 文档 (*.docx)",)
_ALLOWED_SUFFIX = ".docx"

# Optional startup diagnostics (verification only; same file as d1_main).
_STARTUP_LOG_ENV = "KGM_D1_STARTUP_LOG"


def _host_log(message: str) -> None:
    target = os.environ.get(_STARTUP_LOG_ENV)
    if not target:
        return
    try:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%H:%M:%S')} [host] {message}\n")
            handle.flush()
    except OSError:
        pass


class _SaveDialogError(RuntimeError):
    """The native save dialog could not be opened (R16).

    A dedicated marker so the save path can return a fixed, desensitized
    ``SAVE_DIALOG_FAILED`` reason instead of the original dialog exception
    (which may carry absolute paths).
    """


class CloseCoordinator:
    """Host-side close state machine (unit-tested without a real window)."""

    PENDING = "pending"
    CLOSING = "closing"
    CANCELED = "canceled"
    IDLE = "idle"

    def __init__(
        self,
        *,
        notify_page,
        destroy_window,
        notify_aborted,
        timeout: float = CLOSE_TIMEOUT_SECONDS,
        timer_factory=None,
        busy_probe=None,
        task_snapshot=None,
        on_close_intent=None,
        on_close_canceled=None,
        on_install_intent=None,
        on_install_canceled=None,
        on_install_final=None,
        drain_tasks=None,
    ):
        self._notify_page = notify_page
        self._destroy = destroy_window
        self._notify_aborted = notify_aborted
        self._timeout_seconds = timeout
        self._timer_factory = timer_factory or (
            lambda seconds, fn: threading.Timer(seconds, fn)
        )
        # Optional probe returning True while a native file operation (Word
        # save dialog/write) is in flight: the close must never overtake it.
        self._busy_probe = busy_probe or (lambda: False)
        # AI task barrier (D2 §4.3): a close intent freezes new claims/SEND,
        # and the final allow must resolve active tasks explicitly.
        self._task_snapshot = task_snapshot or (lambda: {"live": 0, "in_flight": False})
        self._on_close_intent = on_close_intent or (lambda: None)
        self._on_close_canceled = on_close_canceled or (lambda: None)
        self._on_install_intent = on_install_intent or (
            lambda request_id, generation: None
        )
        self._on_install_canceled = on_install_canceled or (
            lambda request_id, reason: None
        )
        self._on_install_final = on_install_final or (
            lambda request_id, generation: None
        )
        self._drain_tasks = drain_tasks or (lambda: True)
        self._lock = threading.RLock()
        self._state = self.IDLE
        self._current_id: str | None = None
        # Monotonic request generation, assigned under the lock when a
        # request begins (R1 §15.3). Bind it to the notification and to every
        # state answer so the page can tell an answer produced for an older
        # request apart from the current one, no matter when it is delivered.
        self._generation = 0
        self._current_generation = 0
        self._allow_once = False
        self._timer = None

    def _save_busy(self) -> bool:
        try:
            return bool(self._busy_probe())
        except Exception:
            # If the probe cannot answer, fail safe: never allow a destroy
            # while a file operation may still be running.
            return True

    def _task_state(self) -> dict:
        try:
            snapshot = self._task_snapshot() or {}
        except Exception:
            # A probe that cannot answer must not let the close proceed.
            return {"live": 1, "in_flight": True, "unknown": True}
        return snapshot

    def _safe_task_state(self) -> dict:
        return self._task_state()

    def _safe_on_intent(self) -> None:
        try:
            self._on_close_intent()
        except Exception:
            pass

    def _safe_on_canceled(self, request_id: str | None) -> None:
        """Release the AI freeze only if this request still owns the close.

        The identity check and the (short, in-memory) unfreeze run under the
        same lock hold so a new close request cannot slip into the gap and be
        unfrozen by a stale cancel. No DB or network work happens here.
        """
        with self._lock:
            if request_id is not None and self._current_id != request_id:
                return
            try:
                self._on_close_canceled()
            except Exception:
                pass

    def _safe_on_install_intent(self, request_id: str, generation: int) -> None:
        try:
            self._on_install_intent(request_id, generation)
        except Exception:
            pass

    def _safe_on_install_canceled(
        self, request_id: str | None, reason: str
    ) -> None:
        try:
            self._on_install_canceled(request_id, reason)
        except Exception:
            pass

    def _safe_on_install_final(self, request_id: str, generation: int) -> None:
        try:
            self._on_install_final(request_id, generation)
        except Exception:
            pass

    # -- events -----------------------------------------------------------
    def handle_closing(self) -> bool:
        """Return True only to consume the one-shot allow for this request."""
        revoke: tuple[str, str] | None = None
        revoked_id: str | None = None
        begun = False
        with self._lock:
            if self._state == self.CLOSING and self._allow_once:
                if self._save_busy():
                    # Never destroy the window while a native save is in
                    # flight; revoke the allow and notify the page.
                    self._allow_once = False
                    self._state = self.CANCELED
                    self._cancel_timer()
                    if self._current_id:
                        revoke = (self._current_id, "save_in_flight")
                        revoked_id = self._current_id
                    _host_log("closing revoked (save in flight)")
                else:
                    self._allow_once = False
                    _host_log("closing allowed (flag consumed)")
                    return True
            elif self._state in (self.PENDING, self.CLOSING):
                # A close is already in flight; re-entrant closing never
                # starts a second request or allows implicitly.
                _host_log(f"closing canceled (state={self._state})")
                return False
            else:
                self._begin_request()
                begun = True
        if begun:
            # The freeze already happened inside _begin_request (before the
            # page notification could run).
            return False
        if revoke is not None:
            # Never call evaluate_js from inside the synchronous FormClosing
            # callback: the page notification runs on its own thread after
            # this callback has returned False (R11).
            threading.Thread(
                target=self._safe_notify_aborted, args=revoke, daemon=True
            ).start()
        if revoked_id is not None:
            # The revoke canceled this request: release the AI freeze (only if
            # this request still owns the close) and revoke any install plan
            # bound to it.
            self._safe_on_canceled(revoked_id)
            self._safe_on_install_canceled(revoked_id, "save_in_flight")
        return False

    def _begin_request(self) -> None:
        self._current_id = uuid.uuid4().hex
        self._state = self.PENDING
        self._allow_once = False
        self._generation += 1
        self._current_generation = self._generation
        request_id = self._current_id
        generation = self._current_generation
        _host_log(f"close request begun {request_id[:8]} gen {generation}")
        # The timeout callback is bound to this request id: a stale callback
        # that already started before cancel() can never cancel a newer
        # request or a finally allowed closing.
        self._timer = self._timer_factory(
            self._timeout_seconds, lambda: self._on_timeout(request_id)
        )
        self._timer.daemon = True
        self._timer.start()
        # Freeze new AI claims/SEND synchronously, BEFORE the page notification
        # can run: a fast deny must never be followed by this intent freezing
        # again. The freeze is a short in-memory operation (no DB, no network).
        self._safe_on_intent()
        self._safe_on_install_intent(request_id, generation)
        # Notify the page outside the synchronous UI callback; the generation
        # assigned under this lock is bound to the announcement (R1 §15.3).
        threading.Thread(
            target=self._safe_notify_page,
            args=(request_id, generation),
            daemon=True,
        ).start()

    def _on_timeout(self, bound_request_id: str) -> None:
        with self._lock:
            if self._state != self.PENDING or self._current_id != bound_request_id:
                # Belongs to a superseded request (or a final closing that
                # must never be unlocked by waiting timeouts).
                return
            self._state = self.CANCELED
            request_id = self._current_id
        _host_log(f"close timeout for {request_id[:8] if request_id else '?'}")
        # The close was abandoned: release the AI freeze (only if this request
        # still owns the close).
        self._safe_on_canceled(request_id)
        self._safe_on_install_canceled(request_id, "timeout")
        if request_id:
            self._safe_notify_aborted(request_id, "timeout")

    # -- page calls --------------------------------------------------------
    def complete(self, close_request_id: str, allow: bool, task_choice: str | None = None) -> dict:
        _host_log(
            f"complete_close({close_request_id[:8] if close_request_id else '?'}, "
            f"allow={allow}, tasks={task_choice})"
        )
        refuse_busy = False
        refuse_reason: str | None = None
        drain_required = False
        denied = False
        superseded = False
        aborted_reason: str | None = None
        with self._lock:
            if close_request_id != self._current_id or self._state == self.IDLE:
                return {"accepted": False, "state": self._public_state()}
            if self._state != self.PENDING:
                # A late or duplicate ack (already canceled by timeout/deny,
                # or closing) is refused; only a fresh pending request may be
                # completed once.
                return {"accepted": False, "state": self._public_state()}
            if not allow:
                self._state = self.CANCELED
                self._cancel_timer()
                denied = True
            elif self._save_busy():
                self._state = self.CANCELED
                self._cancel_timer()
                refuse_busy = True
            else:
                snapshot = self._safe_task_state()
                live = bool(snapshot.get("live") or snapshot.get("in_flight"))
                if live and task_choice not in ("keep_waiting", "stop_and_exit"):
                    # The page cannot silently drop in-flight tasks: refuse the
                    # close (an old page with no task confirmation included).
                    self._state = self.CANCELED
                    self._cancel_timer()
                    refuse_reason = "ai_tasks_active"
                elif live and task_choice == "keep_waiting":
                    self._state = self.CANCELED
                    self._cancel_timer()
                    refuse_reason = "ai_keep_waiting"
                elif live and task_choice == "stop_and_exit":
                    drain_required = True
                else:
                    # No active task: the reviewed D1 close path is unchanged.
                    self._allow_once = True
                    self._state = self.CLOSING
                    self._cancel_timer()
        if denied:
            self._safe_on_canceled(close_request_id)
            self._safe_on_install_canceled(close_request_id, "close_denied")
            return {"accepted": True, "state": self.CANCELED}
        if refuse_busy:
            _host_log("final allow refused (save in flight)")
            self._safe_notify_aborted(close_request_id, "save_in_flight")
            self._safe_on_canceled(close_request_id)
            self._safe_on_install_canceled(close_request_id, "save_in_flight")
            return {"accepted": False, "state": self.CANCELED}
        if refuse_reason is not None:
            _host_log(f"final allow refused ({refuse_reason})")
            self._safe_notify_aborted(close_request_id, refuse_reason)
            # A refused close releases the freeze so normal work continues.
            self._safe_on_canceled(close_request_id)
            self._safe_on_install_canceled(close_request_id, refuse_reason)
            return {"accepted": False, "state": self.CANCELED}
        if drain_required:
            confirmed = False
            try:
                confirmed = bool(self._drain_tasks())
            except Exception:
                confirmed = False
            with self._lock:
                if self._current_id != close_request_id or self._state != self.PENDING:
                    # Superseded/canceled while draining: do not destroy.
                    superseded = True
                elif not confirmed:
                    self._state = self.CANCELED
                    self._cancel_timer()
                    aborted_reason = "ai_drain_failed"
                else:
                    # Re-check after the drain: nothing may be live any more.
                    snapshot = self._safe_task_state()
                    if snapshot.get("live") or snapshot.get("in_flight"):
                        self._state = self.CANCELED
                        self._cancel_timer()
                        aborted_reason = "ai_tasks_active"
                    else:
                        self._allow_once = True
                        self._state = self.CLOSING
                        self._cancel_timer()
                        superseded = False
                        aborted_reason = None
            if superseded:
                self._safe_on_canceled(close_request_id)
                self._safe_on_install_canceled(close_request_id, "superseded")
                return {"accepted": False, "state": self._public_state()}
            if aborted_reason is not None:
                self._safe_notify_aborted(close_request_id, aborted_reason)
                self._safe_on_canceled(close_request_id)
                self._safe_on_install_canceled(close_request_id, aborted_reason)
                return {"accepted": False, "state": self.CANCELED}
        try:
            self._destroy()
        except Exception:
            with self._lock:
                self._state = self.CANCELED
                self._allow_once = False
            self._safe_notify_aborted(close_request_id, "destroy_failed")
            self._safe_on_canceled(close_request_id)
            self._safe_on_install_canceled(close_request_id, "destroy_failed")
            return {"accepted": False, "state": self.CANCELED}
        # ``destroy`` may synchronously re-enter the closing event: the
        # re-entry either consumes the one-shot allow (state stays closing)
        # or revokes it because a native save started in between (state
        # canceled). Never report a preset success: read the real state for
        # this request id and answer with it (R11).
        with self._lock:
            final = (
                self._current_id == close_request_id
                and self._state == self.CLOSING
            )
            generation = self._current_generation
            state = self._public_state()
        if final:
            self._safe_on_install_final(close_request_id, generation)
            return {"accepted": True, "state": self.CLOSING}
        self._safe_on_install_canceled(close_request_id, "destroy_revoked")
        return {"accepted": False, "state": state}

    def state(self, close_request_id: str) -> str:
        with self._lock:
            if close_request_id != self._current_id:
                return "unknown"
            if self._state == self.IDLE:
                return "unknown"
            return self._public_state()

    def state_answer(self, close_request_id: str) -> dict:
        """The bridge answer for ``get_close_state`` (R1 §15.3).

        A matching current request carries its generation so the page can
        bind its confirmation to the exact host request instance: an answer
        produced while an older request was still current can never pass as
        a confirmation for the newer one. Any other id stays a plain
        ``unknown`` without a generation.
        """
        with self._lock:
            if close_request_id != self._current_id or self._state == self.IDLE:
                return {"state": "unknown"}
            return {
                "state": self._public_state(),
                "generation": self._current_generation,
            }

    def _public_state(self) -> str:
        return self._state

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    # -- notification helpers ---------------------------------------------
    def _safe_notify_page(self, request_id: str, generation: int) -> None:
        with self._lock:
            if self._current_id != request_id or self._state != self.PENDING:
                # This request was superseded or resolved before its
                # notification could run: never deliver a stale request
                # announcement (R1 §14.3). Delivery order is still not
                # guaranteed once the callback runs, so the page additionally
                # confirms the host's current request id and generation with
                # ``get_close_state`` before acting on a notification.
                return
        try:
            self._notify_page(request_id, generation)
        except Exception:
            # Notification failure leaves the request pending; the timeout
            # cancels it and notifies the aborted side.
            pass

    def _safe_notify_aborted(self, request_id: str, reason: str) -> None:
        try:
            self._notify_aborted(request_id, reason)
        except Exception:
            pass


def _base_name(name: str) -> str:
    return os.path.basename(name.replace("\\", "/"))


def validate_docx_target(path: str) -> tuple[bool, str]:
    """The unified .docx suffix rule (case-insensitive on Windows)."""
    if not isinstance(path, str) or not path.strip():
        return False, "保存目标为空"
    suffix = Path(path).suffix.lower()
    if suffix != _ALLOWED_SUFFIX:
        shown = suffix or "（无后缀）"
        return False, f"保存目标必须是 .docx 文件（当前后缀：{shown}）"
    return True, ""


def _validate_docx_part(part: str, data: bytes) -> str | None:
    """Non-empty, parseable XML with the required root element."""
    if not data or not data.strip():
        return f"DOCX 必要部件为空：{part}"
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        # No original parser detail: it adds no user value and must not leak
        # internal exception text (R16).
        return f"DOCX 必要部件不是有效 XML：{part}"
    if root.tag != _XML_ROOTS[part]:
        return f"DOCX 必要部件根元素不正确：{part}"
    return None


def validate_docx_bytes(data: bytes) -> str | None:
    """Validate a non-empty DOCX payload before any file write.

    Returns ``None`` when the bytes are a readable ZIP archive carrying the
    required Word parts as non-empty, parseable XML with the expected roots;
    otherwise a human-readable refusal reason. A file that only starts with
    ``PK`` — or a ZIP whose members are empty/corrupt XML — is not accepted
    (spec §12.3 / R13). This is a bounded structural check, not a full OOXML
    schema validation.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
            for part in _DOCX_REQUIRED_PARTS:
                if part not in names:
                    return f"DOCX 缺少必要部件：{part}"
            # Force a real decode (and CRC check) of each required part so a
            # corrupted entry cannot pass as a valid DOCX.
            for part in _DOCX_REQUIRED_PARTS:
                problem = _validate_docx_part(part, archive.read(part))
                if problem is not None:
                    return problem
    except zipfile.BadZipFile:
        return "DOCX 数据不是有效的 ZIP 容器"
    except (OSError, RuntimeError, ValueError, NotImplementedError):
        # Fixed reason: the original exception text is never returned (R16).
        return "DOCX 数据无法读取"
    return None


def _probe_target_in_use(target: Path) -> bool:
    """Best-effort occupancy probe after an access-denied ``os.replace`` (R16).

    Windows reports both "target is held open by another handle" and
    "read-only attribute / ACL denied" as ERROR_ACCESS_DENIED for
    ``os.replace``. Opening the target read-write distinguishes them: when
    that succeeds (or fails with a sharing violation) the rename is blocked
    by an open handle. When the read-write open is refused, the Windows
    read-only attribute (``os.access`` W_OK) tells a permission denial apart
    from a handle that only shares read access on a writable file. Never
    raises and never includes the path in a message.
    """
    try:
        with open(target, "r+b"):
            return True
    except OSError as exc:
        if getattr(exc, "winerror", None) == 32:
            return True
        return os.access(target, os.W_OK)


def _classify_write_failure(exc: OSError, target: Path) -> tuple[str, str]:
    """Stable, desensitized reason for a failed atomic write (R16).

    The original exception text carries absolute paths and random temporary
    names; it is never returned. Sharing/access/disk/path problems map to
    fixed, user-understandable reasons instead.
    """
    winerror = getattr(exc, "winerror", None)
    errno_value = getattr(exc, "errno", None)
    if winerror == 32 or errno_value == errno.EBUSY:
        return (
            "SAVE_TARGET_IN_USE",
            "目标文件正被其他程序占用，无法保存；请关闭占用该文件的程序后重试",
        )
    if winerror == 5 or errno_value in (errno.EACCES, errno.EPERM):
        if _probe_target_in_use(target):
            return (
                "SAVE_TARGET_IN_USE",
                "目标文件正被其他程序占用，无法保存；请关闭占用该文件的程序后重试",
            )
        return (
            "SAVE_PERMISSION_DENIED",
            "没有保存到该位置的权限；请检查文件权限或选择其他保存位置",
        )
    if winerror == 112 or errno_value == errno.ENOSPC:
        return (
            "SAVE_IO_ERROR",
            "磁盘空间不足，文件未能写入；请清理磁盘空间或选择其他保存位置",
        )
    if isinstance(exc, FileNotFoundError) or winerror in (2, 3) or errno_value == errno.ENOENT:
        return (
            "SAVE_IO_ERROR",
            "保存位置不存在或已被移动；请重新选择保存位置",
        )
    return (
        "SAVE_IO_ERROR",
        "文件写入失败（I/O 错误）；请重试或选择其他保存位置",
    )


def write_docx_atomic(target: str, data: bytes) -> dict:
    """Atomic verified write with an explicit commit point (os.replace).

    Before the commit point any failure cleans this call's temporary file and
    leaves an existing target untouched (``failed``). After the commit point
    a verification failure returns ``unknown`` (the target may have been
    replaced) instead of claiming either outcome. Every failure reason is
    stable and desensitized: no absolute path, temporary name or original
    exception detail is ever returned (R16).
    """
    suffix_ok, reason = validate_docx_target(target)
    if not suffix_ok:
        return {"status": "failed", "code": "INVALID_TARGET", "message": reason}
    if not isinstance(data, (bytes, bytearray)) or len(data) == 0:
        return {"status": "failed", "code": "EMPTY_PAYLOAD", "message": "落盘文件为空"}

    file_path = Path(target)
    directory = file_path.parent
    tmp_path: Path | None = None
    try:
        if not directory.is_dir():
            raise FileNotFoundError("目标目录不存在")
        expected = len(data)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{file_path.name}.", suffix=".tmp", dir=str(directory)
        )
        tmp_path = Path(tmp_name)
        with os.fdopen(fd, "wb") as handle:
            handle.write(bytes(data))
            handle.flush()
            os.fsync(handle.fileno())
        written = tmp_path.stat().st_size
        if written != expected:
            raise OSError("临时文件字节数不符")
        os.replace(str(tmp_path), str(file_path))
        tmp_path = None  # commit point passed
        try:
            final_size = file_path.stat().st_size
            if final_size != expected:
                raise OSError("替换后字节数不符")
        except OSError:
            return {
                "status": "unknown",
                "code": "SAVE_RESULT_UNKNOWN",
                "message": "替换已执行但结果无法确认：文件可能已写入，请核对保存位置后再决定下一步",
            }
        return {"status": "saved", "bytes": expected}
    except OSError as exc:
        code, message = _classify_write_failure(exc, file_path)
        return {"status": "failed", "code": code, "message": message}
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass


class D1HostApi:
    """Object exposed to the window as ``window.pywebview.api``."""

    def __init__(
        self,
        *,
        launch_token: str,
        window_getter=None,
        verify_save_dir: Path | None = None,
        update_manager=None,
        install_coordinator=None,
        ready_receipt=None,
    ):
        self._launch_token = launch_token
        self._window_getter = window_getter or self._default_window
        self._verify_save_dir = verify_save_dir or d1_paths.verify_save_dir()
        self._update_manager = update_manager
        self._install_coordinator = install_coordinator
        self._ready_receipt = ready_receipt
        self._save_lock = threading.Lock()
        # One native save (dialog + write) at a time across *all* operation
        # ids; the in-flight count lets the close path refuse to destroy the
        # window while any save is still running.
        self._save_mutex = threading.Lock()
        self._save_inflight = 0
        self._save_records: dict[str, dict] = {}
        self._page_ready = False
        self._page_busy = False
        self._page_busy_seq = 0
        self._page_ticket: str | None = None
        self._page_ticket_bound = False
        self._page_ticket_mode = False
        self._page_lock = threading.RLock()
        self._close_coordinator: CloseCoordinator | None = None

    # -- window plumbing ---------------------------------------------------
    @staticmethod
    def _default_window():
        windows = list(getattr(webview, "windows", []) or [])
        return windows[0] if windows else None

    def _window(self):
        window = self._window_getter()
        if window is None:
            raise RuntimeError("no active window")
        return window

    # -- session / bridge --------------------------------------------------
    def get_bootstrap(self) -> dict:
        with self._page_lock:
            # A fresh bootstrap ticket identifies this page instance. The
            # previous ticket is retired; a late ready/busy from it is refused.
            self._page_ticket = secrets.token_urlsafe(24)
            self._page_ticket_bound = False
            result = {
                "bridge_protocol": BRIDGE_PROTOCOL,
                "launch_token": self._launch_token,
                "page_ticket": self._page_ticket,
            }
        if self._ready_receipt is not None:
            result["update_install"] = self._ready_receipt.public_bootstrap()
        return result

    def page_ready(self, payload: object = None) -> dict:
        protocol = None
        if isinstance(payload, dict):
            protocol = payload.get("bridge_protocol")
        if protocol != BRIDGE_PROTOCOL:
            return {"accepted": False, "host_protocol": BRIDGE_PROTOCOL}
        ticket = None
        install_payload = None
        if isinstance(payload, dict):
            raw_ticket = payload.get("page_ticket")
            if isinstance(raw_ticket, str) and raw_ticket:
                ticket = raw_ticket
            install_payload = payload.get("update_install")
        with self._page_lock:
            # Validate page identity/legacy eligibility BEFORE any update
            # readiness side effect. An invalid/old ticket must never call
            # ready_receipt.confirm, even once.
            if ticket is None:
                if self._page_ticket_mode:
                    return {"accepted": False, "host_protocol": BRIDGE_PROTOCOL}
                if self._page_ready:
                    # Legacy duplicate ready is idempotent.
                    return {"accepted": True, "host_protocol": BRIDGE_PROTOCOL}
            else:
                if ticket != self._page_ticket:
                    return {"accepted": False, "host_protocol": BRIDGE_PROTOCOL}
                if self._page_ready and self._page_ticket_bound:
                    # Duplicate ready for the current accepted page.
                    return {"accepted": True, "host_protocol": BRIDGE_PROTOCOL}
            if self._ready_receipt is not None:
                confirmed = self._ready_receipt.confirm(
                    install_payload, page_ready=True
                )
                if not confirmed.get("accepted"):
                    return {
                        "accepted": False,
                        "host_protocol": BRIDGE_PROTOCOL,
                        "update_install_error": confirmed.get("code")
                        or "READY_CONFIRM_FAILED",
                    }
            if ticket is None:
                self._page_ready = True
                return {"accepted": True, "host_protocol": BRIDGE_PROTOCOL}
            # Re-check under the same lock (confirm is held inside it); a new
            # bootstrap cannot swap the ticket between validation and commit.
            if ticket != self._page_ticket:
                return {"accepted": False, "host_protocol": BRIDGE_PROTOCOL}
            if not self._page_ready or not self._page_ticket_bound:
                # First ready for this exact ticket: a new page starts clean.
                self._page_busy = False
                self._page_busy_seq = 0
            self._page_ticket_bound = True
            self._page_ticket_mode = True
            self._page_ready = True
            return {"accepted": True, "host_protocol": BRIDGE_PROTOCOL}

    def set_page_busy(self, payload: object = None) -> dict:
        """Versioned, page-bound write barrier (create/import/adopt/…).

        The close/update barrier treats an in-flight/unknown write like a
        native save; a persisted AI execution is not page-busy (the close
        choice remains reachable). The ticket issued by ``get_bootstrap`` and
        the positive sequence are checked and updated under one lock, so an
        old page can never clear a newer page's barrier.
        """
        with self._page_lock:
            if not self._page_ready or not self._page_ticket_bound:
                return {
                    "accepted": False,
                    "busy": self._page_busy,
                    "seq": self._page_busy_seq,
                }
            ticket = None
            seq = 0
            busy = False
            if isinstance(payload, dict):
                raw_ticket = payload.get("page_ticket")
                if isinstance(raw_ticket, str) and raw_ticket:
                    ticket = raw_ticket
                raw_seq = payload.get("seq")
                if isinstance(raw_seq, int) and not isinstance(raw_seq, bool):
                    seq = raw_seq
                busy = payload.get("busy") is True
            if ticket is None or ticket != self._page_ticket:
                return {
                    "accepted": False,
                    "busy": self._page_busy,
                    "seq": self._page_busy_seq,
                }
            if seq <= 0:
                return {
                    "accepted": False,
                    "busy": self._page_busy,
                    "seq": self._page_busy_seq,
                }
            if seq <= self._page_busy_seq:
                return {
                    "accepted": True,
                    "busy": self._page_busy,
                    "seq": self._page_busy_seq,
                }
            self._page_busy_seq = seq
            self._page_busy = busy
            return {
                "accepted": True,
                "busy": self._page_busy,
                "seq": self._page_busy_seq,
            }

    def _page_busy_probe(self) -> bool:
        with self._page_lock:
            return bool(self._page_busy)

    # -- update discovery/download/install --------------------------------
    def _merge_install_state(self, value: dict) -> dict:
        result = dict(value)
        coordinator = self._install_coordinator
        if (
            coordinator is not None
            and self._update_manager is not None
            and result.get("state") == "ready"
        ):
            result["install_available"] = bool(coordinator.install_available())
        else:
            result["install_available"] = False
        if coordinator is not None:
            result.update(coordinator.state())
            # ``install_available`` from the coordinator is authoritative only
            # for a ready U1 package; never advertise install for another state.
            if result.get("state") != "ready":
                result["install_available"] = False
        return result

    def _update_state_or_error(self) -> dict:
        if not self._page_ready:
            return {
                "state": "failed",
                "reason": "BRIDGE_NOT_READY",
                "error_code": "BRIDGE_NOT_READY",
                "error_message": "页面尚未完成桥接握手",
                "install_available": False,
            }
        if self._update_manager is None:
            return {
                "state": "disabled",
                "reason": "UPDATE_NOT_AVAILABLE",
                "error_code": None,
                "error_message": None,
                "install_available": False,
            }
        return self._merge_install_state(self._update_manager.state())

    def get_app_identity(self) -> dict:
        if not self._page_ready or self._update_manager is None:
            return {}
        return self._update_manager.identity.as_dict()

    def check_for_update(self) -> dict:
        if not self._page_ready or self._update_manager is None:
            return self._update_state_or_error()
        try:
            return self._merge_install_state(self._update_manager.check())
        except Exception:  # noqa: BLE001 - bridge never raises
            return {
                "state": "failed",
                "reason": "UPDATE_CHECK_FAILED",
                "error_code": "UPDATE_CHECK_FAILED",
                "error_message": "检查更新失败",
                "install_available": False,
            }

    def start_update_download(self) -> dict:
        if not self._page_ready or self._update_manager is None:
            return self._update_state_or_error()
        try:
            return self._merge_install_state(self._update_manager.download())
        except Exception:  # noqa: BLE001 - bridge never raises
            return {
                "state": "failed",
                "reason": "UPDATE_DOWNLOAD_FAILED",
                "error_code": "UPDATE_DOWNLOAD_FAILED",
                "error_message": "下载更新失败",
                "install_available": False,
            }

    def cancel_update_download(self) -> dict:
        if not self._page_ready or self._update_manager is None:
            return self._update_state_or_error()
        try:
            return self._merge_install_state(self._update_manager.cancel())
        except Exception:  # noqa: BLE001 - bridge never raises
            return self._update_state_or_error()

    def install_update(self) -> dict:
        """Confirm installation; the page supplies no path, URL, PID or command.

        The host creates the plan from its own verified U1 state and asks the
        window to start the existing close handshake.  If that close is
        canceled, the plan authorization is revoked before any switch.
        """
        if not self._page_ready or self._update_manager is None:
            return self._update_state_or_error()
        coordinator = self._install_coordinator
        if coordinator is None:
            return {
                "accepted": False,
                "state": "failed",
                "reason": "UPDATE_INSTALL_UNAVAILABLE",
                "install_available": False,
            }
        try:
            coordinator.set_destroyer(self._window().destroy)
            result = coordinator.prepare_from_manager(self._update_manager)
        except Exception:  # noqa: BLE001 - bridge never raises
            return {
                "accepted": False,
                "state": "failed",
                "reason": "UPDATE_INSTALL_FAILED",
                "install_available": False,
            }
        if result.get("accepted"):
            # Return the accepted result first; the close request must go
            # through the existing page/host handshake rather than bypassing it.
            timer = threading.Timer(0.05, coordinator.request_close)
            timer.daemon = True
            timer.start()
        result["update_state"] = self._update_state_or_error()
        return result

    def get_update_state(self) -> dict:
        return self._update_state_or_error()

    # -- close protocol ----------------------------------------------------
    def complete_close(self, payload: object = None) -> dict:
        coordinator = self._close_coordinator
        if coordinator is None or not self._page_ready:
            return {"accepted": False, "state": "unknown"}
        request_id = ""
        allow = False
        task_choice = None
        if isinstance(payload, dict):
            request_id = str(payload.get("close_request_id") or "")
            allow = payload.get("allow") is True
            raw_choice = payload.get("task_choice")
            if raw_choice in ("keep_waiting", "stop_and_exit"):
                task_choice = raw_choice
        if not request_id:
            return {"accepted": False, "state": coordinator.state("")}
        return coordinator.complete(request_id, allow, task_choice)

    def get_close_state(self, payload: object = None) -> dict:
        coordinator = self._close_coordinator
        if coordinator is None:
            return {"state": "unknown"}
        request_id = ""
        if isinstance(payload, dict):
            request_id = str(payload.get("close_request_id") or "")
        return coordinator.state_answer(request_id)

    # -- restricted Word save ----------------------------------------------
    def save_docx(self, payload: object = None) -> dict:
        if not self._page_ready:
            # Business bridge entries only accept calls from the trusted page
            # that completed the protocol handshake (spec §12.3).
            return {
                "status": "failed",
                "code": "BRIDGE_NOT_READY",
                "message": "页面尚未完成桥接握手，已拒绝保存",
            }
        try:
            return self._save_docx_inner(payload)
        except Exception as exc:  # never raise across the JS bridge
            # Fixed reason: the original exception text may carry absolute
            # paths or temporary names and is never returned (R16).
            _host_log(f"save_docx outer failure: {type(exc).__name__}")
            return {
                "status": "failed",
                "code": "SAVE_FAILED",
                "message": "保存失败：发生未预期的错误，请重试",
            }

    def _save_in_progress(self) -> bool:
        """True while any save (including a blocked one) is not terminal."""
        with self._save_lock:
            return self._save_inflight > 0

    def _decode_docx(self, payload: dict) -> tuple[bytes | None, dict | None]:
        raw = payload.get("payload_base64")
        if not isinstance(raw, str) or not raw:
            return None, {
                "status": "failed",
                "code": "INVALID_PAYLOAD",
                "message": "缺少 DOCX 数据",
            }
        # Reject obviously oversized base64 before decoding (30 MiB cap ->
        # ~40 MiB of base64 text).
        if len(raw) > MAX_DOCX_BYTES * 4 // 3 + 1024:
            return None, {
                "status": "failed",
                "code": "PAYLOAD_TOO_LARGE",
                "message": "DOCX 数据过大，已拒绝保存",
            }
        try:
            data = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError):
            return None, {
                "status": "failed",
                "code": "INVALID_PAYLOAD",
                "message": "DOCX 数据解码失败",
            }
        if not data:
            return None, {
                "status": "failed",
                "code": "INVALID_PAYLOAD",
                "message": "DOCX 数据为空",
            }
        if len(data) > MAX_DOCX_BYTES:
            return None, {
                "status": "failed",
                "code": "PAYLOAD_TOO_LARGE",
                "message": "DOCX 数据过大，已拒绝保存",
            }
        problem = validate_docx_bytes(data)
        if problem is not None:
            return None, {
                "status": "failed",
                "code": "INVALID_PAYLOAD",
                "message": problem,
            }
        return data, None

    def _save_docx_inner(self, payload: object) -> dict:
        if not isinstance(payload, dict):
            return {
                "status": "failed",
                "code": "INVALID_PAYLOAD",
                "message": "保存数据格式不正确",
            }
        request_id = payload.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            return {
                "status": "failed",
                "code": "INVALID_PAYLOAD",
                "message": "缺少操作 ID",
            }
        filename = _base_name(str(payload.get("filename") or ""))
        data, error = self._decode_docx(payload)
        if error is not None:
            # Record the failed result for the operation id as well; a retry
            # with the same id and same payload returns the same conclusion.
            self._record(request_id, fingerprint=None, result=error)
            return error
        assert data is not None
        if not filename:
            filename = "日计划.docx"
        if not filename.lower().endswith(_ALLOWED_SUFFIX):
            filename = filename + _ALLOWED_SUFFIX
        fingerprint = hashlib.sha256(
            filename.encode("utf-8") + b"\x00" + data
        ).hexdigest()

        with self._save_lock:
            existing = self._save_records.get(request_id)
            if existing is not None:
                if existing.get("fingerprint") == fingerprint:
                    result = dict(existing.get("result") or {})
                    if existing.get("in_flight"):
                        result = {"status": "pending"}
                    return result
                return {
                    "status": "failed",
                    "code": "SAVE_REQUEST_CONFLICT",
                    "message": "同一操作 ID 使用了不同文件内容，拒绝覆盖",
                }
            self._save_records[request_id] = {
                "fingerprint": fingerprint,
                "result": None,
                "in_flight": True,
            }
            self._save_inflight += 1
        try:
            # Cross-id global exclusion: only one native dialog/write may run
            # at a time; a different operation id waits here instead of
            # opening a second dialog (R11).
            with self._save_mutex:
                result = self._perform_save(filename, data)
        except Exception as exc:
            # Fixed reason: never surface the original exception (R16).
            _host_log(f"save failed: {type(exc).__name__}")
            result = {
                "status": "failed",
                "code": "SAVE_FAILED",
                "message": "保存失败：发生未预期的错误，请重试",
            }
        with self._save_lock:
            self._save_inflight -= 1
            record = self._save_records.get(request_id) or {}
            record["in_flight"] = False
            record["result"] = result
            record["fingerprint"] = fingerprint
            self._save_records[request_id] = record
        return result

    def _perform_save(self, filename: str, data: bytes) -> dict:
        try:
            target = self._choose_target(filename)
        except _SaveDialogError:
            # Fixed reason: the dialog failure detail (which may contain
            # paths) is never returned (R16).
            return {
                "status": "failed",
                "code": "SAVE_DIALOG_FAILED",
                "message": "无法打开保存对话框，请重试",
            }
        if target is None:
            return {"status": "canceled"}
        result = write_docx_atomic(target, data)
        if result.get("status") == "saved":
            result["filename"] = Path(target).name
        return result

    def _choose_target(self, filename: str) -> str | None:
        if self._verify_save_dir is not None:
            # Verification-only: pre-authorized directory, no dialog.
            base = Path(self._verify_save_dir)
            base.mkdir(parents=True, exist_ok=True)
            return str(base / _base_name(filename))
        window = self._window()
        try:
            chosen = window.create_file_dialog(
                _SAVE_DIALOG,
                save_filename=filename,
                file_types=_WORD_TYPES,
            )
        except Exception as exc:
            _host_log(f"save dialog call failed: {type(exc).__name__}")
            raise _SaveDialogError from exc
        if not chosen:
            return None
        if isinstance(chosen, (list, tuple)):
            return str(chosen[0]) if chosen else None
        return str(chosen)

    def get_save_result(self, payload: object = None) -> dict:
        if not self._page_ready:
            return {"status": "unknown", "code": "BRIDGE_NOT_READY"}
        request_id = ""
        if isinstance(payload, dict):
            request_id = str(payload.get("request_id") or "")
        if not request_id:
            return {"status": "unknown", "code": "UNKNOWN_REQUEST"}
        with self._save_lock:
            record = self._save_records.get(request_id)
            if record is None:
                return {"status": "unknown", "code": "UNKNOWN_REQUEST"}
            if record.get("in_flight"):
                return {"status": "pending"}
            return dict(record.get("result") or {"status": "unknown"})

    def _record(self, request_id: str, *, fingerprint: str | None, result: dict) -> None:
        with self._save_lock:
            existing = self._save_records.get(request_id)
            if existing is not None and existing.get("fingerprint") not in (
                None,
                fingerprint,
            ):
                return
            self._save_records[request_id] = {
                "fingerprint": fingerprint,
                "result": result,
                "in_flight": False,
            }

    # -- host -> page notifications (private: never exposed as bridge) -----
    def _notify_request_close(
        self, close_request_id: str, generation: int | None = None
    ) -> None:
        # The generation assigned to this request travels with the
        # announcement (R1 §15.3); the page still confirms it against
        # ``get_close_state`` before acting.
        script = (
            "window.__kgmHandlers && window.__kgmHandlers.onRequestClose"
            f"({json.dumps(close_request_id)}, {json.dumps(generation)})"
        )
        _host_log("notify page onRequestClose ...")
        try:
            self._window().evaluate_js(script)
            _host_log("notify page onRequestClose returned")
        except Exception as exc:  # noqa: BLE001
            _host_log(f"notify page onRequestClose failed: {exc}")
            raise

    def _notify_close_aborted(self, close_request_id: str, reason: str) -> None:
        script = (
            "window.__kgmHandlers && window.__kgmHandlers.onCloseAborted"
            f"({json.dumps(close_request_id)}, {json.dumps(reason)})"
        )
        try:
            self._window().evaluate_js(script)
            _host_log(f"notified close_aborted {reason}")
        except Exception as exc:  # noqa: BLE001
            _host_log(f"notify close_aborted failed: {exc}")
            raise
