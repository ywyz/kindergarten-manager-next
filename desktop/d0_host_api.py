"""Minimal, restricted pywebview JS host API for the D0 probe.

Surface (deliberately tiny):
- ``get_session()``  -> per-launch session token supplied to the window in
  memory only. Never written to the URL, the database or any log.
- ``save_docx(payload)`` -> native save dialog + a single strictly typed
  bytes write of the already-generated DOCX. Accepts only ``.docx`` targets,
  reads no other files and exposes no command execution. Distinguishes
  saved / canceled / failed, so a closed dialog or an unwritable target can
  never be reported as a success.

Drivers may set ``KGM_D0_AUTOSAVE_DIR``: then ``save_docx`` accepts an
``autosave_target`` inside that pre-authorized directory so the automated
D0 window run can exercise real writes without a human dialog selection.
The manual dialog path stays the default for every other call.

Write discipline (D0-6 / R2 / R7): every save goes through
``write_docx_file``, which first enforces the ``.docx`` suffix, then writes a
sibling temporary file, flushes and fsyncs it, verifies the byte count and
only then atomically ``os.replace``s it onto the target. A failure at any
step removes this call's temporary file and leaves an existing target
untouched, so a partial or failed save cannot corrupt the previous file or
leave a misleading half-written product.
"""

import base64
import binascii
import os
import tempfile
from pathlib import Path

import webview

MAX_DOCX_BYTES = 30 * 1024 * 1024
_SAVE_DIALOG = getattr(
    getattr(webview, "FileDialog", None), "SAVE", getattr(webview, "SAVE_DIALOG", 2)
)
_WORD_TYPES = ("Word 文档 (*.docx)",)
_ALLOWED_SUFFIX = ".docx"


def _base_name(name: str) -> str:
    """Strip any path component inside a suggested filename."""
    return os.path.basename(name.replace("\\", "/"))


def os_error_message(exc: OSError) -> str:
    # Common Windows cases get plain-Chinese wording; everything else keeps
    # the OS text so the review can see the real failure.
    message = str(exc)
    return f"保存失败：{message}"


def validate_docx_target(path: str) -> tuple[bool, str]:
    """The unified suffix rule, applied before any file is created.

    Comparison is case-insensitive (Windows file-system semantics, so
    ``报告.DOCX`` is accepted), while a missing or different extension is
    rejected instead of being silently renamed. This is the single boundary
    the manual dialog path and the automated autosave path both pass through.
    """
    if not isinstance(path, str) or not path.strip():
        return False, "保存目标为空"
    suffix = Path(path).suffix.lower()
    if suffix != _ALLOWED_SUFFIX:
        shown = suffix or "（无后缀）"
        return False, f"保存目标必须是 .docx 文件（当前后缀：{shown}）"
    return True, ""


def _write_payload(handle, data: bytes) -> None:
    """Seam for the partial-write regression test; writes the whole payload."""
    handle.write(data)


def _fsync_dir(directory: Path) -> None:
    """Best-effort directory fsync; not available on Windows (ignored)."""
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def write_docx_file(path: str, data: bytes) -> dict:
    """Atomic, verified ``.docx`` write (D0-6 / R2 / R7)."""
    result: dict = {"status": "failed", "path": path}
    suffix_ok, reason = validate_docx_target(path)
    result["suffix_ok"] = suffix_ok
    if not suffix_ok:
        result["message"] = reason
        return result
    if not isinstance(data, (bytes, bytearray)) or len(data) == 0:
        result["message"] = "落盘文件为空"
        return result

    target = Path(path)
    directory = target.parent
    tmp_path: Path | None = None
    try:
        if not directory.is_dir():
            raise OSError(f"目标目录不存在：{directory}")
        expected = len(data)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=str(directory)
        )
        tmp_path = Path(tmp_name)
        with os.fdopen(fd, "wb") as handle:
            _write_payload(handle, bytes(data))
            handle.flush()
            os.fsync(handle.fileno())
        written = tmp_path.stat().st_size
        if written != expected:
            raise OSError(f"临时文件字节数不符（{written} != {expected}）")
        os.replace(str(tmp_path), str(target))
        tmp_path = None
        _fsync_dir(directory)
        result.update(status="saved", bytes=expected)
        return result
    except OSError as exc:
        result["message"] = os_error_message(exc)
        return result
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass


class D0HostApi:
    """Object exposed to the window as ``window.pywebview.api``."""

    def __init__(self, launch_token: str):
        # The token leaves this object only via get_session(); it must never
        # be logged or persisted.
        self._launch_token = launch_token
        self._autosave_dir = os.environ.get("KGM_D0_AUTOSAVE_DIR") or ""

    # -- session ------------------------------------------------------------
    def get_session(self) -> dict:
        return {"launch_token": self._launch_token}

    # -- Word save ----------------------------------------------------------
    def save_docx(self, payload: dict) -> dict:
        """Never raises to the JS bridge: any failure is a failed result."""
        try:
            return self._save_docx_inner(payload)
        except Exception as exc:
            return {"status": "failed", "message": f"保存失败: {exc}"}

    def _save_docx_inner(self, payload: dict) -> dict:
        data = self._decode_payload(payload)
        if isinstance(data, str):
            return {"status": "failed", "message": data}
        default_name = _base_name(payload.get("filename") or "D0验证.docx")
        if not default_name.lower().endswith(_ALLOWED_SUFFIX):
            default_name = default_name + _ALLOWED_SUFFIX

        target = None
        autosave_target = payload.get("autosave_target")
        if self._autosave_dir and isinstance(autosave_target, str) and autosave_target:
            if os.path.basename(autosave_target.replace("\\", "/")) != autosave_target:
                return {
                    "status": "failed",
                    "message": "自动保存目标超出预授权目录",
                }
            base = Path(self._autosave_dir).resolve()
            base.mkdir(parents=True, exist_ok=True)
            candidate = (base / os.path.basename(autosave_target)).resolve()
            if candidate.parent != base:
                return {
                    "status": "failed",
                    "message": "自动保存目标超出预授权目录",
                }
            target = str(candidate)
        else:
            window = self._window()
            try:
                chosen = window.create_file_dialog(
                    _SAVE_DIALOG,
                    save_filename=default_name,
                    file_types=_WORD_TYPES,
                )
            except Exception as exc:  # a dialog host failure is a failure
                return {"status": "failed", "message": f"保存窗口失败: {exc}"}
            if chosen:
                if isinstance(chosen, (list, tuple)):
                    target = chosen[0]
                else:
                    target = chosen
            if not target:
                return {"status": "canceled"}
        # Unified suffix + atomic write boundary (manual and autosave alike).
        return write_docx_file(target, data)

    # -- internals ----------------------------------------------------------
    @staticmethod
    def _window():
        windows = webview.windows
        if not windows:
            raise RuntimeError("no active window")
        return windows[0]

    @staticmethod
    def _decode_payload(payload: dict) -> bytes | str:
        if not isinstance(payload, dict):
            return "保存数据格式不正确"
        raw = payload.get("payload_base64")
        if not isinstance(raw, str):
            return "缺少 DOCX 数据"
        try:
            data = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError):
            return "DOCX 数据解码失败"
        if not data:
            return "DOCX 数据为空"
        if len(data) > MAX_DOCX_BYTES:
            return "DOCX 数据过大，已拒绝保存"
        return data
