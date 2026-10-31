"""Host-side maintenance coordinator for backup and restore.

This module owns only the host-facing operation registry and background
threads.  The backup engine and restore core are injected; the host never
touches SQL, barrier leases, prepared paths or package internals.  Opaque
target/selection ids are registered by the native-dialog layer, and every
start/confirm request is idempotent by caller request id.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Callable


class MaintenanceHostError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


_TERMINAL = {"completed", "cancelled", "error", "recovery_required"}
_TOO_LATE = {"switching", "reopening"}

# Controlled progress keys from the core are mapped to teacher-facing text.
# Raw stages remain in the host operation for phase reasoning; they are never
# exposed as internal keys through the panel DTO.
_STAGE_TEXT = {
    "barrier": "准备备份",
    "db": "备份数据库",
    "resources": "复制资源",
    "verify": "校验数据",
    "commit": "完成备份",
    "prepare": "准备恢复文件",
    "install": "准备切换档案",
    "protection": "保留恢复前保护副本",
    "switch": "替换当前档案",
    "installed": "安装完成",
}
_MESSAGE_TEXT = {
    "准备备份": "准备备份",
    "数据库快照完成": "数据库快照完成",
    "校验备份": "校验备份",
    "备份完成": "备份完成",
    "复制数据库": "复制数据库",
    "复制受管资源": "复制受管资源",
    "校验完成": "校验完成",
    "copy_database": "复制数据库",
    "copy_resources": "复制资源",
    "intent": "准备恢复",
    "protection": "保留保护副本",
    "switch": "替换当前档案",
    "verify": "校验数据",
    "installed": "安装完成",
    "prepare": "准备恢复文件",
}


def _has_cjk(value: str) -> bool:
    return any("一" <= char <= "鿿" for char in value)


def _stage_text(raw: str) -> str:
    if raw in _STAGE_TEXT:
        return _STAGE_TEXT[raw]
    if raw and _has_cjk(raw):
        return raw
    return "维护操作进行中"


def _message_text(raw: str | None) -> str | None:
    if not raw:
        return None
    if raw in _MESSAGE_TEXT:
        return _MESSAGE_TEXT[raw]
    if _has_cjk(raw):
        return raw
    return "正在处理"


def _public(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    if isinstance(value, dict):
        return dict(value)
    return value


class _MaintenanceHooks:
    """Wrap the host hooks so the host can mark the irreversible boundary.

    ``stop_transport`` returning True means the old server is confirmed dead
    and the core is about to close the engine and switch live files.  From
    that point a cancel is too late: accepting it and showing "已取消" would
    lie while the switch continues.
    """

    def __init__(self, host, base):
        self.host = host
        self.base = base

    def wait_host_idle(self, cancel) -> bool:
        if self.base is None:
            return True
        return bool(self.base.wait_host_idle(cancel))

    def stop_transport(self) -> bool:
        if self.base is None:
            return True
        confirmed = bool(self.base.stop_transport())
        if confirmed:
            self.host._transport_stopped = True
            self.host._mark_switching()
        return confirmed


class MaintenanceHost:
    def __init__(
        self,
        *,
        backup_service: Any = None,
        restore_core: Any = None,
        hooks: Any = None,
        app_version: str = "",
        source_identity: dict[str, Any] | None = None,
        reopen_host: Callable[[], dict[str, Any] | None] | None = None,
        before_reopen: Callable[[], None] | None = None,
    ):
        self.backup_service = backup_service
        self.restore_core = restore_core
        self._base_hooks = hooks
        self.hooks = _MaintenanceHooks(self, hooks)
        self.app_version = app_version
        self.source_identity = dict(source_identity or {})
        # Host-owned continuation after the core reopened the engine: create
        # the new app/token/scope/executor/service/window and wait for the new
        # page to load business.  The core never performs this work.
        self.reopen_host = reopen_host
        # Host-owned retirement that must run BEFORE core.reopen() exposes the
        # new engine to a new window.  It must not block this operation's own
        # read-only status query.
        self.before_reopen = before_reopen
        self._transport_stopped = False
        # Display-only completion text for the new page after a successful
        # restore.  It contains the protection location and retention wording
        # only; it is never a path capability or credential.
        self._completion_notice: str | None = None
        self._lock = threading.RLock()
        self._ops: dict[str, dict[str, Any]] = {}
        self._by_request: dict[str, dict[str, Any]] = {}
        self._targets: dict[str, Path] = {}
        self._selections: dict[str, Path] = {}
        self._generation = 0
        self._retired = False
        # Set when the core reports that the on-disk journal/installation
        # state needs a restart before any new maintenance operation.  The
        # host never terminalizes or retries the core's journal itself.
        self._recovery_required = False

    # -- opaque native selections ---------------------------------------
    def register_target(self, path: str | Path, display_name: str) -> dict[str, str]:
        target_id = secrets.token_urlsafe(18)
        with self._lock:
            self._targets[target_id] = Path(path)
        return {"target_id": target_id, "display_name": display_name}

    def register_selection(
        self, path: str | Path, display_name: str, encrypted: bool
    ) -> dict[str, Any]:
        selection_id = secrets.token_urlsafe(18)
        with self._lock:
            self._selections[selection_id] = Path(path)
        return {
            "selection_id": selection_id,
            "display_name": display_name,
            "encrypted": bool(encrypted),
        }

    def startup_state(self) -> dict[str, Any]:
        if self._retired:
            return {"state": "ready"}
        core = self.restore_core
        recover = getattr(core, "recover", None)
        if callable(recover):
            try:
                result = _public(recover())
                state = result.get("state") if isinstance(result, dict) else None
                if state == "recovery_required":
                    return {
                        "state": "recovery_required",
                        "detail": "上次恢复需要处理，请重启应用并按提示处理",
                    }
            except Exception:
                return {
                    "state": "recovery_required",
                    "detail": "无法确认上次恢复状态，请重启应用",
                }
        return {"state": "ready"}

    def retire(self) -> None:
        with self._lock:
            self._retired = True

    def _require_operable(self) -> None:
        if self._recovery_required:
            raise MaintenanceHostError(
                "RECOVERY_REQUIRED", "上次恢复需要处理，请重启应用"
            )

    def _record_rejection(
        self,
        request_id: str,
        kind: str,
        fingerprint: str,
        exc: "MaintenanceHostError",
    ) -> None:
        """Make a rejected start/confirm queryable by the same request id.

        The page may lose the error reply; ``query`` must then resolve the
        request to the same terminal error instead of hanging or resending a
        side effect.  Rejection records never start a worker and never
        overwrite an existing operation.
        """
        if not request_id:
            return
        with self._lock:
            if request_id in self._by_request:
                return
            self._generation += 1
            committed = exc.code in {
                "RECOVERY_REQUIRED",
                "RESTORE_RECOVERY_REQUIRED",
            }
            op = {
                "request_id": request_id,
                "operation_id": secrets.token_hex(16),
                "generation": self._generation,
                "kind": kind,
                "phase": "error",
                "progress": None,
                "preview": None,
                "protection": None,
                "error": self._error(
                    exc.code, exc.message, committed=committed
                ),
                "cancel_requested": False,
                "stale": False,
                "reopened": False,
                "committed": committed,
                "_cancel": threading.Event(),
                "_preview_obj": None,
                "_prepared": None,
                "_fingerprint": fingerprint,
                "_rejected": True,
            }
            self._ops[op["operation_id"]] = op
            self._by_request[request_id] = op

    def recovery_required(self) -> bool:
        """True when the core journal requires a restart before new work."""
        with self._lock:
            return bool(self._recovery_required)

    def completion_notice(self) -> str | None:
        with self._lock:
            return self._completion_notice

    def _retire_superseded_password_ops(self) -> None:
        """Retire earlier wrong-password verifications via the core.

        A wrong-password preview is no longer an active worker and keeps no
        staging, but its host phase stays ``password`` so the panel can ask
        for a retry.  Starting a new verification or closing the window must
        not leave that superseded record looking active.  Only ``password``
        records are touched; preview/install operations are never cancelled
        by this cleanup.
        """
        if self.restore_core is None:
            return
        with self._lock:
            candidates = [
                op
                for op in self._ops.values()
                if op["kind"] == "restore"
                and op["phase"] == "password"
                and not op.get("_core_retired")
            ]
        for op in candidates:
            try:
                result = self.restore_core.cancel(op["operation_id"])
            except Exception:  # noqa: BLE001 - unknown is not success
                continue
            state = getattr(result, "state", None)
            accepted = bool(getattr(result, "accepted", False))
            if isinstance(result, dict):
                state = result.get("state")
                accepted = bool(result.get("accepted"))
            if state == "canceled" and accepted:
                with self._lock:
                    op["_core_retired"] = True

    def has_active_operation(self) -> bool:
        """True while any maintenance operation is not terminal.

        The window close path uses this to refuse a destroy while a backup or
        restore is still running.  ``wait_host_idle`` must NOT use it: the
        panel would otherwise wait for its own maintenance operation.
        """
        with self._lock:
            return any(
                op["phase"] not in _TERMINAL and not op.get("_core_retired")
                for op in self._ops.values()
            )

    # -- operation lifecycle --------------------------------------------
    @staticmethod
    def _fingerprint(kind: str, payload: dict[str, Any]) -> str:
        raw = json.dumps(
            {"kind": kind, "payload": payload},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def _check_request(
        self, request_id: str, kind: str, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        existing = self._by_request.get(request_id)
        if existing is None:
            return None
        if existing.get("_fingerprint") != self._fingerprint(kind, payload):
            raise MaintenanceHostError("REQUEST_CONFLICT", "同一请求 ID 对应了不同操作")
        return existing

    def _new_op(
        self, request_id: str, kind: str, phase: str, fingerprint: str
    ) -> dict[str, Any]:
        self._generation += 1
        operation_id = secrets.token_hex(16)
        op = {
            "request_id": request_id,
            "operation_id": operation_id,
            "generation": self._generation,
            "kind": kind,
            "phase": phase,
            "progress": None,
            "preview": None,
            "protection": None,
            "error": None,
            "cancel_requested": False,
            "stale": False,
            "reopened": False,
            "committed": False,
            "_cancel": threading.Event(),
            "_preview_obj": None,
            "_prepared": None,
            "_fingerprint": fingerprint,
        }
        self._ops[operation_id] = op
        self._by_request[request_id] = op
        return op

    def _ref(self, op: dict[str, Any]) -> dict[str, Any]:
        return {
            "request_id": op["request_id"],
            "operation_id": op["operation_id"],
            "generation": op["generation"],
        }

    def _status(self, op: dict[str, Any]) -> dict[str, Any]:
        return {
            "request_id": op["request_id"],
            "operation_id": op["operation_id"],
            "generation": op["generation"],
            "kind": op["kind"],
            "phase": op["phase"],
            "progress": op["progress"],
            "preview": op["preview"],
            "protection": op["protection"],
            "error": op["error"],
            "cancel_requested": op["cancel_requested"],
            "stale": op["stale"],
            "reopened": op["reopened"],
        }

    @staticmethod
    def _error(code: str, message: str, *, committed: bool = False) -> dict[str, Any]:
        return {
            "code": code,
            "message": message,
            "committed": committed,
            "next_action": "restart_app" if committed else "retry",
        }

    def _mark_switching(self) -> None:
        with self._lock:
            for op in self._ops.values():
                if op["kind"] == "restore" and op["phase"] in (
                    "waiting",
                    "protection",
                ):
                    op["phase"] = "switching"

    def _transition(self, op: dict[str, Any], phase: str, **fields: Any) -> bool:
        """Set a phase/fields under the lock unless the op is already terminal."""
        with self._lock:
            if op["phase"] in _TERMINAL:
                return False
            for key, value in fields.items():
                op[key] = value
            op["phase"] = phase
            return True

    def _progress(self, op: dict[str, Any], value: Any) -> None:
        raw = _public(value)
        if not isinstance(raw, dict):
            return
        stage = str(raw.get("stage") or "")
        message_key = raw.get("message_key") or raw.get("message")
        with self._lock:
            op["_progress_stage"] = stage
            op["_progress_message_key"] = message_key
            if stage == "protection":
                if op["phase"] == "waiting":
                    op["phase"] = "protection"
            elif stage in ("switch", "installed") and self._transport_stopped:
                # The authoritative irreversible boundary is the confirmed
                # stop_transport callback.  A nested protection/verification
                # "verify" before it must stay cancellable.
                if op["phase"] in ("waiting", "protection"):
                    op["phase"] = "switching"
        display_stage = _stage_text(stage)
        display_message = _message_text(
            str(message_key) if message_key else None
        )
        if display_message == display_stage:
            display_message = None
        op["progress"] = {
            "stage": display_stage,
            "message": display_message,
            "done": raw.get("done"),
            "total": raw.get("total"),
            "indeterminate": not (
                isinstance(raw.get("done"), int)
                and isinstance(raw.get("total"), int)
                and raw.get("total", 0) > 0
            ),
        }

    def start_backup(
        self,
        *,
        request_id: str,
        target_id: str,
        password: str | None,
        explicit_plaintext: bool,
    ) -> dict[str, Any]:
        with self._lock:
            fingerprint = self._fingerprint(
                "backup",
                {
                    "target_id": target_id,
                    "password": password,
                    "explicit_plaintext": bool(explicit_plaintext),
                },
            )
            existing = self._check_request(request_id, "backup", {
                "target_id": target_id,
                "password": password,
                "explicit_plaintext": bool(explicit_plaintext),
            })
            if existing is not None:
                return self._ref(existing)
            try:
                if self._retired:
                    raise MaintenanceHostError("HOST_RETIRED", "宿主已退休，请重新打开应用")
                self._require_operable()
                target = self._targets.get(target_id)
                if target is None:
                    raise MaintenanceHostError("TARGET_UNKNOWN", "备份目标已失效，请重新选择")
                if password is not None:
                    if not isinstance(password, str) or not password:
                        raise MaintenanceHostError("PASSWORD_REQUIRED", "请输入密码；不会自动降级为明文")
                elif not explicit_plaintext:
                    raise MaintenanceHostError("PLAINTEXT_NOT_ACKNOWLEDGED", "请确认明文备份包含可读业务和照片")
                if self.backup_service is None:
                    raise MaintenanceHostError("HOST_CORE_UNAVAILABLE", "备份引擎尚未就绪")
            except MaintenanceHostError as exc:
                self._record_rejection(request_id, "backup", fingerprint, exc)
                raise
            op = self._new_op(request_id, "backup", "creating", fingerprint)
            thread = threading.Thread(
                target=self._run_backup,
                args=(op, target, password),
                name=f"maintenance-backup-{op['operation_id'][:8]}",
                daemon=True,
            )
            thread.start()
            return self._ref(op)

    def _run_backup(self, op: dict[str, Any], target: Path, password: str | None) -> None:
        try:
            result = self.backup_service.create(
                target,
                password=password,
                cancel=op["_cancel"],
                progress=lambda value: self._progress(op, value),
            )
            # A returned create() is the published-success fact: a cancel
            # event set just before the return must never rewrite it to
            # cancelled or delete the already published file.
            if not self._transition(
                op,
                "completed",
                committed=True,
                progress=None,
                protection={"display_text": f"备份文件：{target.name}"},
            ):
                return
            _ = result
        except Exception as exc:  # noqa: BLE001 - host boundary
            code = str(getattr(exc, "code", ""))
            cancelled = code == "LOCAL_BACKUP_CANCELLED" or type(exc).__name__ == "SnapshotCancelled"
            with self._lock:
                if op["phase"] in _TERMINAL:
                    return
                if cancelled:
                    op["phase"] = "cancelled"
                    return
                op["phase"] = "error"
                op["error"] = self._error(
                    code or "BACKUP_FAILED", "备份失败，当前档案未更改"
                )

    def start_restore_verify(
        self,
        *,
        request_id: str,
        selection_id: str,
        password: str | None,
    ) -> dict[str, Any]:
        self._retire_superseded_password_ops()
        with self._lock:
            fingerprint = self._fingerprint(
                "restore-verify",
                {"selection_id": selection_id, "password": password},
            )
            existing = self._check_request(
                request_id,
                "restore-verify",
                {"selection_id": selection_id, "password": password},
            )
            if existing is not None:
                return self._ref(existing)
            try:
                if self._retired:
                    raise MaintenanceHostError("HOST_RETIRED", "宿主已退休，请重新打开应用")
                self._require_operable()
                selection = self._selections.get(selection_id)
                if selection is None:
                    raise MaintenanceHostError("SELECTION_UNKNOWN", "备份文件选择已失效，请重新选择")
                if self.restore_core is None:
                    raise MaintenanceHostError("HOST_CORE_UNAVAILABLE", "恢复核心尚未就绪")
                if password is not None and (not isinstance(password, str) or not password):
                    raise MaintenanceHostError("PASSWORD_REQUIRED", "请输入备份密码")
            except MaintenanceHostError as exc:
                self._record_rejection(request_id, "restore", fingerprint, exc)
                raise
            op = self._new_op(
                request_id, "restore", "verifying", fingerprint
            )
            thread = threading.Thread(
                target=self._run_preview,
                args=(op, selection, password),
                name=f"maintenance-verify-{op['operation_id'][:8]}",
                daemon=True,
            )
            thread.start()
            return self._ref(op)

    def _run_preview(self, op: dict[str, Any], path: Path, password: str | None) -> None:
        try:
            preview = self.restore_core.preview(
                path,
                password,
                operation_id=op["operation_id"],
                cancel=op["_cancel"],
                progress=lambda value: self._progress(op, value),
            )
            late_cancel = False
            with self._lock:
                cancelled = op["_cancel"].is_set() or op.get("_cancelling") is True
                if cancelled or op["phase"] in _TERMINAL:
                    if cancelled:
                        op["phase"] = "cancelled"
                        op["_preview_obj"] = None
                        op["preview"] = None
                        op["progress"] = None
                        late_cancel = True
                else:
                    op["_preview_obj"] = preview
                    op["preview"] = _public(preview)
                    op["phase"] = "preview"
                    op["progress"] = None
                    op["_cancelling"] = False
            if late_cancel:
                # The preview returned after the cancel request.  Ask the core
                # to release its detached verify staging; only a confirmed
                # core cancel may be reported as cancelled.
                result = None
                try:
                    result = self.restore_core.cancel(op["operation_id"])
                except Exception:  # noqa: BLE001 - unknown is never success
                    result = None
                state = getattr(result, "state", None)
                accepted = bool(getattr(result, "accepted", False))
                if isinstance(result, dict):
                    state = result.get("state")
                    accepted = bool(result.get("accepted"))
                with self._lock:
                    if op["phase"] in _TERMINAL:
                        return
                    op["_cancelling"] = False
                    if state == "canceled" and accepted:
                        op["phase"] = "cancelled"
                        op["_preview_obj"] = None
                        op["preview"] = None
                        op["progress"] = None
                    else:
                        # Cancel was not confirmed: the core still owns a
                        # valid preview.  Show it honestly instead of faking
                        # a cancel or discarding the DTO.
                        op["_preview_obj"] = preview
                        op["preview"] = _public(preview)
                        op["phase"] = "preview"
                        op["progress"] = None
                return
        except Exception as exc:  # noqa: BLE001 - host boundary
            code = str(getattr(exc, "code", "RESTORE_VERIFY_FAILED"))
            retire_wrong = False
            with self._lock:
                if op["phase"] in _TERMINAL:
                    return
                if code == "RESTORE_CANCELED" or op.get("_cancelling") is True:
                    op["phase"] = "cancelled"
                    op["_preview_obj"] = None
                    op["preview"] = None
                    op["progress"] = None
                    op["_cancelling"] = False
                    return
                if code == "WRONG_PASSWORD":
                    op["phase"] = "password"
                    op["error"] = self._error("WRONG_PASSWORD", "密码不正确，请重新输入")
                    retire_wrong = True
                else:
                    op["phase"] = "error"
                    op["error"] = self._error(code, "备份校验失败，当前档案未更改")
            if retire_wrong and self.restore_core is not None:
                try:
                    result = self.restore_core.cancel(op["operation_id"])
                except Exception:  # noqa: BLE001 - unknown is not success
                    result = None
                state = getattr(result, "state", None)
                accepted = bool(getattr(result, "accepted", False))
                if isinstance(result, dict):
                    state = result.get("state")
                    accepted = bool(result.get("accepted"))
                if state == "canceled" and accepted:
                    with self._lock:
                        op["_core_retired"] = True

    def confirm_restore(
        self,
        *,
        request_id: str,
        operation_id: str,
        generation: int,
        confirmation_token: str,
    ) -> dict[str, Any]:
        with self._lock:
            fingerprint = self._fingerprint(
                "restore-confirm",
                {
                    "operation_id": operation_id,
                    "generation": generation,
                    "confirmation_token": confirmation_token,
                },
            )
            existing = self._by_request.get(request_id)
            if existing is not None:
                if existing.get("_fingerprint") != fingerprint:
                    raise MaintenanceHostError("REQUEST_CONFLICT", "同一请求 ID 对应了不同操作")
                return self._ref(existing)
            try:
                if self._retired:
                    raise MaintenanceHostError("HOST_RETIRED", "宿主已退休，请重新打开应用")
                self._require_operable()
                op = self._ops.get(operation_id)
                if (
                    op is None
                    or op["kind"] != "restore"
                    or op["generation"] != generation
                    or op["phase"] != "preview"
                    or op.get("_cancelling") is True
                ):
                    raise MaintenanceHostError("PREVIEW_STALE", "预览已失效，请重新校验")
                preview = op.get("preview") or {}
                token = preview.get("preview_id") if isinstance(preview, dict) else None
                if not token or token != confirmation_token:
                    raise MaintenanceHostError("PREVIEW_STALE", "预览已失效，请重新校验")
                if self.restore_core is None:
                    raise MaintenanceHostError("HOST_CORE_UNAVAILABLE", "恢复核心尚未就绪")
            except MaintenanceHostError as exc:
                self._record_rejection(request_id, "restore", fingerprint, exc)
                raise
            op["request_id"] = request_id


            op["_fingerprint"] = fingerprint
            self._by_request[request_id] = op
            op["phase"] = "waiting"
            thread = threading.Thread(
                target=self._run_install,
                args=(op,),
                name=f"maintenance-install-{op['operation_id'][:8]}",
                daemon=True,
            )
            thread.start()
            return self._ref(op)

    def _run_install(self, op: dict[str, Any]) -> None:
        installed = False
        install_started = False
        with self._lock:
            self._transport_stopped = False
        try:
            prepared = self.restore_core.prepare(
                op["_preview_obj"],
                cancel=op["_cancel"],
                progress=lambda value: self._progress(op, value),
            )
            with self._lock:
                if op["phase"] in _TERMINAL:
                    return
                op["_prepared"] = prepared
                op["phase"] = "protection"
            install_started = True
            result = self.restore_core.install(
                prepared,
                hooks=self.hooks,
                cancel=op["_cancel"],
                progress=lambda value: self._progress(op, value),
            )
            public = _public(result)
            state = public.get("state") if isinstance(public, dict) else None
            transport_stopped = bool(self._transport_stopped)
            # The protection copy may already exist even when the install is
            # cancelled/failed after capture; keep its display-safe location
            # visible through the terminal state.
            display = (
                public.get("protection_display_path")
                if isinstance(public, dict)
                else None
            )
            if display:
                with self._lock:
                    if op["phase"] not in _TERMINAL:
                        text = (
                            f"恢复前保护副本：{display}。自动保留，不会自动删除。"
                        )
                        op["protection"] = {"display_text": text}
                        self._completion_notice = text
            if state == "canceled":
                if transport_stopped:
                    # The old server is confirmed dead; do not claim the
                    # teacher can continue on the old page.  The journal is
                    # the authority after restart.
                    with self._lock:
                        self._recovery_required = True
                    self._transition(
                        op,
                        "error",
                        committed=True,
                        progress=None,
                        error=self._error(
                            "RESTORE_RESTART_REQUIRED",
                            "恢复未完成，请重启应用核对当前档案",
                            committed=True,
                        ),
                    )
                else:
                    self._transition(op, "cancelled")
                return
            if state == "recovery_required":
                with self._lock:
                    self._recovery_required = True
                self._transition(
                    op,
                    "error",
                    committed=True,
                    progress=None,
                    error=self._error(
                        "RESTORE_RECOVERY_REQUIRED",
                        "恢复状态需要处理，请重启应用",
                        committed=True,
                    ),
                )
                return
            if state == "failed_keep_old":
                # The core reports whether it already closed the engine and
                # changed a live component.  After the transport was stopped
                # the old page cannot continue even when the data is old.
                restart_required = (
                    transport_stopped
                    or (
                        isinstance(public, dict)
                        and public.get("reopen_required") is True
                    )
                )
                if restart_required:
                    with self._lock:
                        self._recovery_required = True
                self._transition(
                    op,
                    "error",
                    committed=restart_required,
                    progress=None,
                    error=self._error(
                        "RESTORE_RESTART_REQUIRED"
                        if restart_required
                        else "RESTORE_FAILED",
                        "恢复未完成，请重启应用核对当前档案"
                        if restart_required
                        else "恢复未完成，当前档案未更改",
                        committed=restart_required,
                    ),
                )
                return
            if state != "installed_retired":
                # Only the explicit installed_retired result may reopen.
                # Unknown/None/malformed/future states are never success.
                with self._lock:
                    self._recovery_required = True
                self._transition(
                    op,
                    "error",
                    committed=True,
                    progress=None,
                    error=self._error(
                        "RESTORE_STATE_UNKNOWN",
                        "恢复状态无法确认，请重启应用核查",
                        committed=True,
                    ),
                )
                return
            installed = True
            with self._lock:
                if op["phase"] in _TERMINAL:
                    return
                op["phase"] = "reopening"
            # The old host must be retired BEFORE core.reopen() exposes the
            # new engine.  Its own read-only status query remains available.
            if self.before_reopen is not None:
                try:
                    self.before_reopen()
                except Exception as exc:  # noqa: BLE001 - host boundary
                    with self._lock:
                        self._recovery_required = True
                    self._transition(
                        op,
                        "error",
                        committed=True,
                        progress=None,
                        error=self._error(
                            "RESTORE_RESTART_REQUIRED",
                            "宿主退休失败，请重启应用",
                            committed=True,
                        ),
                    )
                    _ = exc
                    return
            reopen = self.restore_core.reopen()
            reopened = _public(reopen)
            if isinstance(reopened, dict) and reopened.get("state") == "reopened":
                if self.reopen_host is not None:
                    try:
                        outcome = _public(self.reopen_host())
                    except Exception as exc:  # noqa: BLE001 - host boundary
                        outcome = {
                            "state": "reopen_failed",
                            "code": str(
                                getattr(exc, "code", "REOPEN_SEQUENCE_FAILED")
                            ),
                        }
                    if not isinstance(outcome, dict) or outcome.get(
                        "state"
                    ) != "reopened":
                        with self._lock:
                            self._recovery_required = True
                        self._transition(
                            op,
                            "error",
                            committed=True,
                            progress=None,
                            error=self._error(
                                "REOPEN_FAILED",
                                "资料已恢复，重新打开失败，请重启应用",
                                committed=True,
                            ),
                        )
                        return
                self._transition(
                    op,
                    "completed",
                    committed=True,
                    reopened=True,
                    progress=None,
                )
                return
            with self._lock:
                self._recovery_required = True
            self._transition(
                op,
                "error",
                committed=True,
                progress=None,
                error=self._error(
                    "REOPEN_FAILED",
                    "资料已恢复，重新打开失败，请重启应用",
                    committed=True,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - host boundary
            code = str(getattr(exc, "code", "RESTORE_FAILED"))
            transport_stopped = bool(self._transport_stopped)
            with self._lock:
                if op["phase"] in _TERMINAL:
                    return
            if code == "RESTORE_CANCELED":
                if transport_stopped:
                    with self._lock:
                        self._recovery_required = True
                    self._transition(
                        op,
                        "error",
                        committed=True,
                        progress=None,
                        error=self._error(
                            "RESTORE_RESTART_REQUIRED",
                            "恢复未完成，请重启应用核对当前档案",
                            committed=True,
                        ),
                    )
                else:
                    self._transition(op, "cancelled")
                return
            if installed:
                # The switch already completed; only reopening failed.
                with self._lock:
                    self._recovery_required = True
                self._transition(
                    op,
                    "error",
                    committed=True,
                    progress=None,
                    error=self._error(
                        "REOPEN_FAILED",
                        "资料已恢复，重新打开失败，请重启应用",
                        committed=True,
                    ),
                )
                return
            if not install_started:
                # prepare failed before any protection/live change.
                self._transition(
                    op,
                    "error",
                    committed=False,
                    progress=None,
                    error=self._error(
                        code, "恢复未完成，当前档案未更改"
                    ),
                )
                return
            # An unexpected install exception may have changed live files
            # before the core could report a bounded state.  Restart is the
            # honest next action; the journal decides on startup.
            with self._lock:
                self._recovery_required = True
            self._transition(
                op,
                "error",
                committed=True,
                progress=None,
                error=self._error(
                    code, "恢复未完成，请重启应用核对当前档案", committed=True
                ),
            )

    # -- query / cancel --------------------------------------------------
    def _find(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        request_id = payload.get("request_id")
        if isinstance(request_id, str) and request_id:
            return self._by_request.get(request_id)
        operation_id = payload.get("operation_id")
        generation = payload.get("generation")
        op = self._ops.get(str(operation_id or ""))
        if op is None or not isinstance(generation, int) or op["generation"] != generation:
            return None
        return op

    def query(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            op = self._find(payload)
            if op is None:
                return {"state": "unknown"}
            return {"state": "found", "status": self._status(op)}

    def cancel(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            op = self._find(payload)
            if op is None:
                return {"accepted": False, "state": "unknown"}
            if op["phase"] in _TERMINAL or op.get("_core_retired"):
                return {"accepted": False, "state": "completed"}
            if op["phase"] in _TOO_LATE:
                return {"accepted": False, "state": "too_late"}
            op["cancel_requested"] = True
            kind = op["kind"]
            operation_id = op["operation_id"]
            phase = op["phase"]
            if kind != "restore" or self.restore_core is None:
                op["_cancel"].set()
                # A backup may already have published before returning; the
                # caller must wait for the real terminal fact.
                return {"accepted": True, "state": "unknown"}
            op["_cancelling"] = True
            op["_cancel"].set()

        try:
            result = self.restore_core.cancel(operation_id)
        except Exception:  # noqa: BLE001 - unknown is never success
            result = None
        state = getattr(result, "state", None)
        accepted = bool(getattr(result, "accepted", False))
        if isinstance(result, dict):
            state = result.get("state")
            accepted = bool(result.get("accepted"))

        with self._lock:
            if op["phase"] in _TERMINAL:
                op["_cancelling"] = False
                return {"accepted": False, "state": "completed"}
            op["_cancelling"] = False
            if state == "canceled" and accepted:
                # The core retired its preview/prepared staging (or accepted
                # the in-flight cancel).  Only now may the host say cancelled.
                op["phase"] = "cancelled"
                op["preview"] = None
                op["_preview_obj"] = None
                op["progress"] = None
                return {"accepted": True, "state": "cancelled"}
            if state == "switching":
                return {"accepted": False, "state": "too_late"}
            if state in {
                "installed_retired",
                "reopened",
                "failed_keep_old",
                "recovery_required",
                "failed",
                "canceled",
            }:
                return {"accepted": False, "state": "completed"}
            # requested / previewing / unknown: the worker or core still owns
            # the outcome.  Never fake a cancel; the page keeps polling.
            _ = phase
            return {"accepted": accepted, "state": "unknown"}
