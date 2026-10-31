"""B2 restore core: preview, prepared group, switch, journal retirement.

The module is backend-only.  It never imports desktop, FastAPI, webview or UI
code; the host supplies only ``wait_host_idle`` and ``stop_transport`` through
``MaintenanceHooks``.  The core owns the maintenance lease and releases it only
after the active journal has been durably retired.
"""

from __future__ import annotations

import os
import secrets
import shutil
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from datetime import datetime, timezone
from typing import Any, Callable

from app.local import (
    ai_adoption,
    ai_task_service,
    backup_barrier,
    backup_fs,
    backup_validate,
    config_tokens,
    credentials,
    daily_plan_history_service,
    observation_ai_service,
)
from app.local.backup_snapshot import SnapshotService, VerifiedSnapshot
from app.local.restore_fs import (
    RestorePathSet,
    cleanup_own_operation,
    copy_file,
    credential_overlap,
    directory_identity,
    ensure_private_dir,
    file_identity,
    operation_paths,
    path_is_within,
    probe_database_family,
    tree_manifest,
)
from app.local import restore_group, restore_journal
from app.local.restore_types import (
    CancelResult,
    InstallResult,
    MaintenanceHooks,
    PreparedDTO,
    PreviewDTO,
    RecoveryResult,
    ReopenResult,
    RestoreFailure,
    RestoreProgress,
)

_ASSET_PREFIX = "observations/assets/"
_RESOURCE_LIMIT = 64 * 1024 * 1024 * 1024
_AI_TIMEOUT = 60.0
_EXECUTOR_TIMEOUT = 10.0


@dataclass
class _PreviewRecord:
    dto: PreviewDTO
    package_path: Path
    verified: VerifiedSnapshot
    package_sha256: str


@dataclass
class _PreparedRecord:
    dto: PreparedDTO
    paths: RestorePathSet
    new_group: dict[str, Any]
    operation_identity: tuple[int, int]
    snapshot_id: str


def _utc_text() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ")


def _remove_empty_sidecars(db_path: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        side = db_path.with_name(db_path.name + suffix)
        try:
            if side.exists() and side.stat().st_size == 0:
                side.unlink()
        except OSError:
            pass


def _read_preview_meta(db_path: Path, credential_root: Path) -> dict[str, Any]:
    connection = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        profile = connection.execute(
            "SELECT display_name FROM local_profile LIMIT 1"
        ).fetchone()
        class_row = connection.execute(
            "SELECT name FROM local_classes WHERE id = "
            "(SELECT current_class_id FROM local_settings LIMIT 1)"
        ).fetchone()
        term_rows = connection.execute(
            "SELECT name FROM local_terms ORDER BY start_date, name"
        ).fetchall()
        counts: dict[str, int] = {}
        for key, table in (
            ("daily_plans", "local_daily_plans"),
            ("observations", "local_observation_records"),
            ("assets", "local_observation_assets"),
        ):
            try:
                value = connection.execute(
                    f'SELECT COUNT(*) FROM "{table}"'
                ).fetchone()[0]
            except sqlite3.Error:
                value = 0
            counts[key] = int(value)
        configured = False
        ready = False
        state = connection.execute(
            "SELECT profile_id, database_uuid, current_config_version "
            "FROM local_ai_state LIMIT 1"
        ).fetchone()
        if state is not None and state["current_config_version"]:
            profile_id = str(state["profile_id"])
            database_uuid = str(state["database_uuid"])
            version = connection.execute(
                "SELECT credential_id, base_url, model "
                "FROM local_ai_config_versions WHERE profile_id = ? AND version = ?",
                (profile_id, int(state["current_config_version"])),
            ).fetchone()
            if version is not None and version["credential_id"]:
                configured = bool(version["base_url"] and version["model"])
                credential = connection.execute(
                    "SELECT key_id, nonce, ciphertext, state "
                    "FROM local_ai_credentials WHERE id = ? AND profile_id = ?",
                    (str(version["credential_id"]), profile_id),
                ).fetchone()
                if (
                    credential is not None
                    and credential["key_id"]
                    and credential["state"] == "active"
                    and credential["nonce"] is not None
                    and credential["ciphertext"] is not None
                ):
                    try:
                        store = credentials.CredentialStore(
                            credential_root, database_uuid
                        )
                        master = store.load_master_key(str(credential["key_id"]))
                        saved = credentials.SavedSecret(
                            key_id=str(credential["key_id"]),
                            nonce=bytes(credential["nonce"]),
                            ciphertext=bytes(credential["ciphertext"]),
                        )
                        store.decrypt_secret(
                            master, saved, profile_id, str(version["credential_id"])
                        )
                        ready = True
                    except Exception:  # noqa: BLE001 - preview is advisory
                        ready = False
        return {
            "profile_present": profile is not None,
            "profile_name": str(profile["display_name"]) if profile else None,
            "class_name": str(class_row["name"]) if class_row else None,
            "term_names": tuple(str(row["name"]) for row in term_rows),
            "counts": counts,
            "credential_configured": configured,
            "credential_ready": ready,
        }
    finally:
        connection.close()


def _apply_auth_cleanup(db_path: Path) -> int:
    """Expire one-time observation restore previews in the prepared copy."""
    connection = sqlite3.connect(str(db_path))
    try:
        exists = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='local_observation_restore_previews'"
        ).fetchone()
        if exists is None:
            return 0
        cursor = connection.execute(
            "UPDATE local_observation_restore_previews "
            "SET consumed_at = ? WHERE consumed_at IS NULL",
            (_utc_text(),),
        )
        count = int(cursor.rowcount or 0)
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.commit()
        return count
    finally:
        connection.close()


class RestoreCore:
    def __init__(
        self,
        runtime,
        *,
        app_version: str = "",
        source_identity: dict[str, Any] | None = None,
        fault_injector: Callable[[str], None] | None = None,
    ):
        self.runtime = runtime
        self.app_version = str(app_version or "")
        self.source_identity = dict(source_identity or {})
        self._fault_injector = fault_injector
        self._lock = threading.RLock()
        self._previews: dict[str, _PreviewRecord] = {}
        self._prepared: dict[str, _PreparedRecord] = {}
        self._completed: dict[str, tuple[str, InstallResult]] = {}
        self._states: dict[str, str] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._active_operation: str | None = None
        self._active_phase = "idle"
        self._first_live_change = False
        self._install_lock = threading.Lock()

    # -- helpers ---------------------------------------------------------
    def _service(self) -> SnapshotService:
        return SnapshotService(
            self.runtime,
            app_version=self.app_version,
            source_identity=self.source_identity,
            executor=getattr(self.runtime, "ai_executor", None),
        )

    def _snap_progress(
        self, callback: Callable[[RestoreProgress], None] | None
    ):
        if callback is None:
            return None

        def emit(value) -> None:
            self._progress(
                callback,
                str(getattr(value, "stage", "")),
                int(getattr(value, "done", 0) or 0),
                int(getattr(value, "total", 0) or 0),
                getattr(value, "message", None),
            )

        return emit

    @staticmethod
    def _progress(
        callback: Callable[[RestoreProgress], None] | None,
        stage: str,
        done: int = 0,
        total: int = 0,
        message_key: str | None = None,
    ) -> None:
        if callback is None:
            return
        try:
            callback(RestoreProgress(stage, done, total, message_key))
        except Exception:  # noqa: BLE001 - progress must not change state
            pass

    @staticmethod
    def _check_cancel(cancel: threading.Event) -> None:
        if cancel.is_set():
            raise RestoreFailure("RESTORE_CANCELED", "cancel", "恢复已取消")

    def _fault(self, stage: str) -> None:
        """Test-only controlled stop seam; production leaves it None."""
        if self._fault_injector is not None:
            self._fault_injector(stage)

    @staticmethod
    def _map_backup_error(exc: BaseException) -> RestoreFailure:
        code = getattr(exc, "code", "")
        if code == "BACKUP_CANCELLED":
            return RestoreFailure("RESTORE_CANCELED", "verify", "恢复已取消")
        if code == "BACKUP_PASSWORD_REQUIRED":
            return RestoreFailure(
                "RESTORE_PASSWORD_REQUIRED", "verify", "加密备份需要密码"
            )
        if code == "BACKUP_AUTH_FAILED":
            return RestoreFailure(
                "WRONG_PASSWORD",
                "verify",
                "密码不正确或备份认证失败",
                retryable=True,
                details={"restore_code": "RESTORE_PASSWORD_INVALID"},
            )
        if code in (
            "BACKUP_MAGIC_INVALID",
            "BACKUP_FORMAT_UNSUPPORTED",
            "BACKUP_MODE_INVALID",
            "BACKUP_HEADER_INVALID",
            "BACKUP_HEADER_DIGEST",
            "BACKUP_KDF_INVALID",
            "BACKUP_SIZE_INVALID",
            "BACKUP_TRUNCATED",
            "BACKUP_PAYLOAD_INVALID",
            "BACKUP_MANIFEST_INVALID",
            "BACKUP_DB_REVISION_UNSUPPORTED",
            "BACKUP_DB_SCHEMA_UNTRUSTED",
            "BACKUP_DB_INTEGRITY",
            "BACKUP_DB_FOREIGN_KEY",
            "BACKUP_DB_LOGICAL_INVALID",
            "BACKUP_DB_RESOURCE_DUPLICATE",
            "BACKUP_RESOURCE_HASH",
            "BACKUP_RESOURCE_SIZE",
            "BACKUP_RESOURCE_IMAGE_INVALID",
            "BACKUP_PATH_INVALID",
        ):
            return RestoreFailure(
                "RESTORE_PACKAGE_INVALID",
                "verify",
                "备份文件无效或不受支持",
                details={"backup_code": str(code)},
            )
        if code in ("BACKUP_DB_MIGRATION_FAILED",):
            return RestoreFailure(
                "RESTORE_PACKAGE_INVALID",
                "verify",
                "旧版备份迁移失败",
                details={"backup_code": str(code)},
            )
        return RestoreFailure(
            "RESTORE_PACKAGE_INVALID", "verify", "备份文件无法校验"
        )

    def _wait_ai_terminal(self, cancel: threading.Event) -> None:
        deadline = time.monotonic() + _AI_TIMEOUT
        executor = getattr(self.runtime, "ai_executor", None)
        while True:
            self._check_cancel(cancel)
            session = self.runtime.session()
            try:
                snapshot = ai_task_service.active_task_snapshot(session)
            finally:
                session.close()
            if int(snapshot.get("live") or 0) == 0:
                return
            if executor is None or not executor.is_runnable():
                raise RestoreFailure(
                    "RESTORE_AI_ACTIVE", "quiesce", "仍有 AI 任务且执行器不可用"
                )
            if time.monotonic() >= deadline:
                raise RestoreFailure(
                    "RESTORE_AI_ACTIVE", "quiesce", "等待 AI 任务完成超时"
                )
            time.sleep(0.05)

    def _wait_executor_idle(self, owner: str, cancel: threading.Event) -> None:
        executor = getattr(self.runtime, "ai_executor", None)
        if executor is None:
            return
        executor.freeze(owner=owner)
        deadline = time.monotonic() + _EXECUTOR_TIMEOUT
        while time.monotonic() < deadline:
            self._check_cancel(cancel)
            if executor.is_snapshot_idle():
                return
            time.sleep(0.05)
        raise RestoreFailure(
            "RESTORE_AI_ACTIVE", "quiesce", "AI 执行器仍有活动或待持久化结果"
        )

    def _reset_authorizations(self) -> None:
        config_tokens.rotate_key()
        for module in (
            ai_adoption,
            daily_plan_history_service,
            observation_ai_service,
        ):
            reset = getattr(module, "reset_tokens", None)
            if callable(reset):
                reset()

    # -- public API ------------------------------------------------------
    def preview(
        self,
        package_path: str | Path,
        password: str | None,
        *,
        operation_id: str,
        cancel: threading.Event,
        progress: Callable[[RestoreProgress], None] | None = None,
    ) -> PreviewDTO:
        path = Path(os.path.abspath(str(package_path)))
        if path_is_within(path, Path(self.runtime.data_dir)) or path_is_within(
            path, Path(self.runtime.credential_root)
        ):
            raise RestoreFailure(
                "RESTORE_SOURCE_INSIDE_DATA",
                "verify",
                "备份文件不得位于数据根或凭据根内",
            )
        if password is not None and not isinstance(password, str):
            raise RestoreFailure(
                "RESTORE_PASSWORD_REQUIRED", "verify", "密码格式不合法"
            )
        with self._lock:
            state = self._states.get(operation_id)
            if state in ("canceled", "failed", "failed_keep_old", "recovery_required"):
                raise RestoreFailure(
                    "RESTORE_OPERATION_CANCELED",
                    "verify",
                    "该恢复操作已结束，请重新选择备份",
                )
            existing = self._previews.get(operation_id)
            if existing is not None:
                if existing.package_path != path:
                    raise RestoreFailure(
                        "RESTORE_OPERATION_CONFLICT",
                        "verify",
                        "同一恢复操作使用了不同备份文件",
                    )
                return existing.dto
            if self._active_operation not in (None, operation_id):
                raise RestoreFailure(
                    "RESTORE_BUSY", "verify", "已有恢复操作正在进行"
                )
            self._states[operation_id] = "previewing"
            self._cancel_events[operation_id] = cancel
        service = self._service()
        verified = None
        try:
            before = file_identity(path)
            verified = service.verify(
                path,
                password=password,
                cancel=cancel,
                progress=self._snap_progress(progress),
            )
            after = file_identity(path)
            if not before.present or before != after:
                raise RestoreFailure(
                    "RESTORE_PREVIEW_STALE", "verify", "备份文件在校验期间发生变化"
                )
            package_sha = after.sha256
            self._check_cancel(cancel)
        except RestoreFailure as exc:
            if verified is not None:
                try:
                    service.discard_verified(verified)
                except Exception:  # noqa: BLE001
                    pass
            with self._lock:
                if cancel.is_set():
                    self._states[operation_id] = "canceled"
                elif exc.code == "WRONG_PASSWORD":
                    self._states[operation_id] = "preview"
                else:
                    self._states[operation_id] = "failed"
            raise
        except Exception as exc:  # noqa: BLE001 - controlled package refusal
            if verified is not None:
                try:
                    service.discard_verified(verified)
                except Exception:  # noqa: BLE001
                    pass
            mapped = self._map_backup_error(exc)
            with self._lock:
                if cancel.is_set():
                    self._states[operation_id] = "canceled"
                elif mapped.code == "WRONG_PASSWORD":
                    self._states[operation_id] = "preview"
                else:
                    self._states[operation_id] = "failed"
            raise mapped from exc
        meta = _read_preview_meta(
            verified.database_path, Path(self.runtime.credential_root)
        )
        manifest = verified.manifest
        counts = dict(manifest.get("counts") or {})
        counts.update(
            {
                "daily_plans": int(meta["counts"].get("daily_plans", 0)),
                "observations": int(meta["counts"].get("observations", 0)),
                "assets": int(meta["counts"].get("assets", 0)),
            }
        )
        warnings: list[str] = []
        if verified.source_revision != verified.target_revision:
            warnings.append("legacy_schema_migrated")
        if not meta["profile_present"]:
            warnings.append("empty_profile")
        if meta["credential_configured"] and not meta["credential_ready"]:
            warnings.append("credential_unavailable")
        dto = PreviewDTO(
            operation_id=operation_id,
            preview_id=secrets.token_urlsafe(24),
            package_name=path.name,
            package_bytes=int(path.stat().st_size),
            package_sha256=package_sha,
            snapshot_id=str(manifest["snapshot_id"]),
            created_at=str(manifest["created_at"]),
            app_version=str(manifest["app_version"]),
            source_revision=verified.source_revision,
            target_revision=verified.target_revision,
            counts=counts,
            profile_present=bool(meta["profile_present"]),
            profile_name=meta["profile_name"],
            class_name=meta["class_name"],
            term_names=tuple(meta["term_names"]),
            credential_configured=bool(meta["credential_configured"]),
            credential_ready=bool(meta["credential_ready"]),
            warnings=tuple(warnings),
        )
        with self._lock:
            self._previews[operation_id] = _PreviewRecord(
                dto=dto,
                package_path=path,
                verified=verified,
                package_sha256=package_sha,
            )
            self._states[operation_id] = "preview"
        return dto

    def prepare(
        self,
        preview: PreviewDTO,
        *,
        cancel: threading.Event,
        progress: Callable[[RestoreProgress], None] | None = None,
    ) -> PreparedDTO:
        canceled_record = None
        with self._lock:
            state = self._states.get(preview.operation_id)
            if state in ("canceled", "failed", "failed_keep_old", "recovery_required"):
                raise RestoreFailure(
                    "RESTORE_OPERATION_CANCELED",
                    "prepare",
                    "该恢复操作已结束，请重新选择备份",
                )
            if state == "preparing":
                raise RestoreFailure(
                    "RESTORE_BUSY", "prepare", "恢复准备已在进行"
                )
            existing = self._prepared.get(preview.operation_id)
            if existing is not None:
                return existing.dto
            record = self._previews.get(preview.operation_id)
            if record is None or record.dto.preview_id != preview.preview_id:
                raise RestoreFailure(
                    "RESTORE_PREVIEW_EXPIRED", "prepare", "恢复预览已失效"
                )
            if self._active_operation not in (None, preview.operation_id):
                raise RestoreFailure(
                    "RESTORE_BUSY", "prepare", "已有恢复操作正在进行"
                )
            stored_cancel = self._cancel_events.get(preview.operation_id)
            if cancel.is_set() or (stored_cancel is not None and stored_cancel.is_set()):
                self._states[preview.operation_id] = "canceled"
                self._previews.pop(preview.operation_id, None)
                canceled_record = record
            else:
                self._states[preview.operation_id] = "preparing"
        if canceled_record is not None:
            try:
                self._service().discard_verified(canceled_record.verified)
            except Exception:  # noqa: BLE001
                pass
            raise RestoreFailure("RESTORE_CANCELED", "prepare", "恢复已取消")
        record = self._previews.get(preview.operation_id)
        if record is None:  # pragma: no cover - lock/state race guard
            raise RestoreFailure(
                "RESTORE_PREVIEW_EXPIRED", "prepare", "恢复预览已失效"
            )
        try:
            current = file_identity(record.package_path)
        except RestoreFailure:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RestoreFailure(
                "RESTORE_PACKAGE_MISSING", "prepare", "备份文件已不可读取"
            ) from exc
        if not current.present or current.sha256 != record.package_sha256:
            raise RestoreFailure(
                "RESTORE_PREVIEW_STALE", "prepare", "备份文件在预览后发生变化"
            )
        current_sha = current.sha256
        try:
            paths = operation_paths(
                self.runtime, preview.operation_id, create=True
            )
            operation_identity = directory_identity(paths.operation_dir)
        except BaseException:
            with self._lock:
                self._states[preview.operation_id] = (
                    "canceled" if cancel.is_set() else "failed"
                )
                self._previews.pop(preview.operation_id, None)
            try:
                self._service().discard_verified(record.verified)
            except Exception:  # noqa: BLE001
                pass
            raise
        created = False
        try:
            if paths.prepared_dir.joinpath("db", "kindergarten.db").exists():
                raise RestoreFailure(
                    "RESTORE_PREPARED_EXISTS",
                    "prepare",
                    "该恢复操作已有 prepared 组",
                )
            created = True
            ensure_private_dir(paths.prepared_dir / "db")
            ensure_private_dir(paths.prepared_dir / "assets")
            verified = record.verified
            db_bytes = int(verified.database_path.stat().st_size)
            resource_bytes = sum(
                int(item.get("bytes") or 0)
                for item in (verified.manifest.get("resources") or [])
            )
            required = db_bytes + resource_bytes + 32 * 1024 * 1024
            if shutil.disk_usage(paths.work_root).free < required:
                raise RestoreFailure(
                    "RESTORE_STORAGE_UNAVAILABLE",
                    "prepare",
                    "恢复工作区可用空间不足",
                )
            db_target = paths.prepared_dir / "db" / "kindergarten.db"
            self._progress(progress, "prepare", 0, 1, "copy_database")
            copied_db = copy_file(
                verified.database_path,
                db_target,
                expected_sha256=verified.target_sha256,
                cancel=cancel,
            )
            auth_count = _apply_auth_cleanup(db_target)
            _remove_empty_sidecars(db_target)
            copied_db = file_identity(db_target)
            resources = list(verified.manifest.get("resources") or [])
            target_bytes = 0
            for index, entry in enumerate(resources, start=1):
                self._check_cancel(cancel)
                raw_path = str(entry["path"])
                if not raw_path.startswith(_ASSET_PREFIX):
                    raise RestoreFailure(
                        "RESTORE_ASSETS_UNSAFE", "prepare", "资源路径不在受管目录"
                    )
                relative = PurePosixPath(raw_path[len(_ASSET_PREFIX):])
                if relative.is_absolute() or ".." in relative.parts:
                    raise RestoreFailure(
                        "RESTORE_ASSETS_UNSAFE", "prepare", "资源路径越界"
                    )
                source = verified.resources_root.joinpath(*PurePosixPath(raw_path).parts)
                target = paths.prepared_dir / "assets" / Path(*relative.parts)
                copy_file(
                    source,
                    target,
                    expected_size=int(entry["bytes"]),
                    expected_sha256=str(entry["sha256"]),
                    cancel=cancel,
                )
                target_bytes += int(entry["bytes"])
                if index == 1 or index % 50 == 0:
                    self._progress(
                        progress,
                        "prepare",
                        index,
                        len(resources),
                        "copy_resources",
                    )
            if target_bytes > _RESOURCE_LIMIT:
                raise RestoreFailure(
                    "RESTORE_STORAGE_UNAVAILABLE", "prepare", "资源总量超过上限"
                )
            assets = tree_manifest(
                paths.prepared_dir / "assets", strict_regular=True
            )
            file_entries = [
                item for item in (assets.get("entries") or []) if item.get("kind") == "file"
            ]
            if len(file_entries) != len(resources):
                raise RestoreFailure(
                    "RESTORE_ASSETS_MISMATCH",
                    "prepare",
                    "prepared 资产数量与清单不一致",
                )
            new_group = {
                "db": copied_db.as_dict(),
                "assets": assets,
            }
            self._check_cancel(cancel)
            dto = PreparedDTO(
                operation_id=preview.operation_id,
                prepared_id=secrets.token_urlsafe(24),
                package_sha256=current_sha,
                db_sha256=copied_db.sha256,
                assets_manifest_hash=str(assets["digest"]),
                resource_count=len(resources),
                resource_bytes=target_bytes,
                auth_change_count=auth_count,
                profile_present=preview.profile_present,
            )
            with self._lock:
                self._prepared[preview.operation_id] = _PreparedRecord(
                    dto=dto,
                    paths=paths,
                    new_group=new_group,
                    operation_identity=operation_identity,
                    snapshot_id=str(record.verified.manifest.get("snapshot_id") or ""),
                )
                self._states[preview.operation_id] = "prepared"
            return dto
        except BaseException:
            with self._lock:
                self._states[preview.operation_id] = (
                    "canceled" if cancel.is_set() else "failed"
                )
                self._previews.pop(preview.operation_id, None)
            if created:
                try:
                    cleanup_own_operation(paths, operation_identity)
                except Exception:  # noqa: BLE001 - preserve primary
                    pass
            raise
        finally:
            try:
                self._service().discard_verified(record.verified)
            except Exception:  # noqa: BLE001 - cleanup is reported by caller
                pass

    # -- install ---------------------------------------------------------
    def install(
        self,
        prepared: PreparedDTO,
        *,
        hooks: MaintenanceHooks,
        cancel: threading.Event,
        progress: Callable[[RestoreProgress], None] | None = None,
    ) -> InstallResult:
        with self._lock:
            done = self._completed.get(prepared.operation_id)
            if done is not None:
                if done[0] != prepared.prepared_id:
                    raise RestoreFailure(
                        "RESTORE_OPERATION_CONFLICT",
                        "install",
                        "同一恢复操作使用了不同 prepared 组",
                    )
                return done[1]
            record = self._prepared.get(prepared.operation_id)
            state = self._states.get(prepared.operation_id)
            if state in ("canceled", "failed", "failed_keep_old", "recovery_required"):
                raise RestoreFailure(
                    "RESTORE_OPERATION_CANCELED",
                    "install",
                    "该恢复操作已结束，请重新选择备份",
                )
            if record is None or record.dto.prepared_id != prepared.prepared_id:
                raise RestoreFailure(
                    "RESTORE_PREPARED_MISSING", "install", "恢复 prepared 组已失效"
                )
            if state == "installing":
                raise RestoreFailure(
                    "RESTORE_BUSY", "install", "恢复安装已在进行"
                )
            if self._active_operation not in (None, prepared.operation_id):
                raise RestoreFailure(
                    "RESTORE_BUSY", "install", "已有恢复操作正在进行"
                )
        if not self._install_lock.acquire(blocking=False):
            raise RestoreFailure(
                "RESTORE_BUSY", "install", "已有恢复操作正在进行"
            )
        operation_id = prepared.operation_id
        owner = f"restore:{operation_id}"
        paths = record.paths
        new_group = record.new_group
        journal: dict[str, Any] | None = None
        lease = None
        fenced = False
        engine_closed = False
        first_change = False
        terminal_done = False
        released = False
        guards: list[Any] = []
        warnings: list[str] = []
        failure: RestoreFailure | None = None
        try:
            with self._lock:
                self._active_operation = operation_id
                self._active_phase = "install"
                self._first_live_change = False
                self._states[operation_id] = "installing"
                self._cancel_events[operation_id] = cancel
            if credential_overlap(self.runtime, paths):
                raise RestoreFailure(
                    "RESTORE_CREDENTIAL_OVERLAP",
                    "quiesce",
                    "凭据根与恢复组重叠，拒绝切换",
                )
            if any(
                [
                    not paths.protection_path.parent.is_dir(),
                    not paths.prepared_dir.is_dir(),
                ]
            ):
                raise RestoreFailure(
                    "RESTORE_PREPARED_MISSING", "install", "恢复工作目录缺失"
                )
            ensure_private_dir(paths.guard_dir)
            journal = restore_journal.new_journal(
                operation_id=operation_id,
                package={
                    "sha256": prepared.package_sha256,
                    "snapshot_id": record.snapshot_id,
                },
            )
            journal = restore_journal.write_journal(paths, journal)
            self._progress(progress, "install", 0, 1, "intent")
            barrier = backup_barrier.get_barrier(self.runtime.data_dir)
            lease = barrier.begin_intent(owner, cancel=cancel)
            barrier.wait_idle(lease, timeout=60.0, cancel=cancel)
            self._wait_ai_terminal(cancel)
            self._wait_executor_idle(owner, cancel)
            fenced = True
            barrier.acquire_exclusive(lease, cancel=cancel)
            barrier.validate_exclusive_lease(lease)
            old_assets_manifest = tree_manifest(
                restore_group.live_assets_path(paths), strict_regular=False
            )
            old_bytes = sum(
                int(item.get("size") or 0)
                for item in old_assets_manifest.get("entries") or []
                if item.get("kind") == "file"
            )
            for name in restore_group.DB_COMPONENTS:
                candidate = restore_group.live_db_path(paths, name)
                if candidate.exists():
                    old_bytes += int(candidate.stat().st_size)
            if shutil.disk_usage(paths.guard_root).free < old_bytes + 32 * 1024 * 1024:
                raise RestoreFailure(
                    "RESTORE_STORAGE_UNAVAILABLE",
                    "protection",
                    "保护副本可用空间不足",
                )
            self._progress(progress, "protection", 0, 1, "protection")
            protection = self._service().capture_maintenance_protection(
                lease=lease,
                output=paths.protection_path,
                cancel=cancel,
                progress=self._snap_progress(progress),
            )
            protection_verified = self._service().verify(
                paths.protection_path,
                password=None,
                cancel=cancel,
                progress=self._snap_progress(progress),
            )
            journal = restore_journal.set_phase(
                paths,
                journal,
                "protection_ready",
                protection={
                    "path_name": paths.protection_path.name,
                    "sha256": protection.sha256,
                    "snapshot_id": protection.snapshot_id,
                    "source_revision": protection_verified.source_revision,
                    "target_revision": protection_verified.target_revision,
                },
            )
            self._check_cancel(cancel)
            if not bool(hooks.wait_host_idle(cancel)):
                raise RestoreFailure(
                    "RESTORE_QUIESCE_FAILED", "quiesce", "宿主保存未能静止"
                )
            if not bool(hooks.stop_transport()):
                raise RestoreFailure(
                    "RESTORE_QUIESCE_FAILED", "quiesce", "本地服务未能确认停止"
                )
            executor = getattr(self.runtime, "ai_executor", None)
            if executor is not None and not bool(executor.dispose()):
                raise RestoreFailure(
                    "RESTORE_AI_ACTIVE", "quiesce", "AI 执行器未能确认退出"
                )
            self.runtime.close_engine_keep_lock()
            engine_closed = True
            if not probe_database_family(self.runtime.db_path):
                raise RestoreFailure(
                    "RESTORE_FILE_IN_USE", "quiesce", "数据库家族仍被占用"
                )
            assets_capture_guard = None
            data_capture_guard = backup_fs.DirectoryGuard(paths.data_dir)
            data_capture_guard.__enter__()
            if restore_group.live_assets_path(paths).exists():
                assets_capture_guard = backup_fs.DirectoryGuard(
                    restore_group.live_assets_path(paths)
                )
                assets_capture_guard.__enter__()
            try:
                old_group = restore_group.capture_old_group(paths)
            finally:
                if assets_capture_guard is not None:
                    assets_capture_guard.close()
                data_capture_guard.close()
            journal = restore_journal.set_phase(
                paths, journal, "quiesced", old=old_group, new=new_group
            )
            self._fault("after_quiesced")
            self._check_cancel(cancel)
            journal = restore_journal.set_phase(paths, journal, "switching")
            data_guard = backup_fs.DirectoryGuard(paths.data_dir)
            data_guard.__enter__()
            guards.append(data_guard)
            observations_dir = paths.data_dir / "observations"
            if not observations_dir.is_dir():
                observations_dir.mkdir(parents=True, exist_ok=True)
            observations_guard = backup_fs.DirectoryGuard(observations_dir)
            observations_guard.__enter__()
            guards.append(observations_guard)
            work_guard = backup_fs.DirectoryGuard(paths.work_root)
            work_guard.__enter__()
            guards.append(work_guard)
            old_guard = backup_fs.DirectoryGuard(paths.old_dir)
            old_guard.__enter__()
            guards.append(old_guard)
            prepared_guard = backup_fs.DirectoryGuard(paths.prepared_dir)
            prepared_guard.__enter__()
            guards.append(prepared_guard)
            self._progress(progress, "switch", 0, 1, "switch")
            for name in restore_group.DB_COMPONENTS:
                if not first_change:
                    self._check_cancel(cancel)
                source = restore_group.live_db_path(paths, name)
                if source.exists():
                    restore_group.move_live_component_to_old(paths, name)
                    if not first_change:
                        first_change = True
                        with self._lock:
                            self._first_live_change = True
                        if name == restore_group.DB_COMPONENTS[0]:
                            self._fault("after_old_db_main")
                        journal = restore_journal.set_phase(
                            paths,
                            journal,
                            "switching",
                            first_live_change_at=_utc_text(),
                        )
                    else:
                        if name == restore_group.DB_COMPONENTS[0]:
                            self._fault("after_old_db_main")
                        journal = restore_journal.write_journal(paths, journal)
                else:
                    journal = restore_journal.write_journal(paths, journal)
            if not first_change:
                self._check_cancel(cancel)
            restore_group.move_live_assets_to_old(paths)
            self._fault("after_old_assets")
            if not first_change:
                first_change = True
                with self._lock:
                    self._first_live_change = True
                journal = restore_journal.set_phase(
                    paths,
                    journal,
                    "switching",
                    first_live_change_at=_utc_text(),
                )
            journal = restore_journal.write_journal(paths, journal)
            if not first_change:
                self._check_cancel(cancel)
            restore_group.move_prepared_assets_to_live(paths)
            live_assets_guard = backup_fs.DirectoryGuard(
                restore_group.live_assets_path(paths)
            )
            live_assets_guard.__enter__()
            guards.append(live_assets_guard)
            self._fault("after_new_assets")
            if not first_change:
                first_change = True
                with self._lock:
                    self._first_live_change = True
                journal = restore_journal.set_phase(
                    paths,
                    journal,
                    "switching",
                    first_live_change_at=_utc_text(),
                )
            journal = restore_journal.write_journal(paths, journal)
            restore_group.move_prepared_db_to_live(paths)
            self._fault("after_new_db")
            journal = restore_journal.write_journal(paths, journal)
            self._progress(progress, "verify", 0, 1, "verify")
            schema_scratch = paths.operation_dir / "verify-schema"
            ensure_private_dir(schema_scratch)
            restore_group.verify_installed_group(
                paths, new_group, schema_scratch
            )
            journal = restore_journal.set_phase(
                paths, journal, "installed", new=new_group
            )
            self._fault("after_installed_journal")
            self._reset_authorizations()
            journal = restore_journal.terminal_journal(paths, journal)
            terminal_done = True
            self._fault("after_terminal_journal")
            try:
                restore_journal.write_receipt(paths, journal)
                restore_journal.archive_terminal(paths, journal)
            except Exception:  # noqa: BLE001 - terminal journal remains authority
                warnings.append("receipt_archive_pending")
            lease.release()
            released = True
            with self._lock:
                self._active_phase = "installed_retired"
                self._states[operation_id] = "installed_retired"
            self._progress(progress, "installed", 1, 1, "installed")
            result = InstallResult(
                operation_id=operation_id,
                state="installed_retired",
                protection_display_path=str(paths.protection_path),
                receipt_id=operation_id,
                old_group_preserved=True,
                lease_released=True,
                reopen_required=True,
                warnings=tuple(warnings),
            )
            with self._lock:
                self._completed[operation_id] = (prepared.prepared_id, result)
            return result
        except RestoreFailure as exc:
            failure = exc
        except backup_barrier.SnapshotCancelled:
            failure = RestoreFailure("RESTORE_CANCELED", "install", "恢复已取消")
        except backup_barrier.SnapshotBusy as exc:
            failure = RestoreFailure(
                "RESTORE_BUSY", "install", str(exc) or "恢复维护忙碌"
            )
        except Exception as exc:  # noqa: BLE001 - controlled storage failure
            failure = RestoreFailure(
                "RESTORE_SWITCH_FAILED",
                "switch",
                "恢复切换失败",
                details={"reason": type(exc).__name__},
            )
        finally:
            for guard in reversed(guards):
                try:
                    guard.close()
                except Exception:  # noqa: BLE001
                    pass
            failure_state = (
                "canceled"
                if failure is not None and failure.code == "RESTORE_CANCELED"
                else "failed_keep_old"
            )
            failure_receipt: str | None = None
            failure_reopen = False
            if failure is not None:
                journal_old = (journal or {}).get("old") or {}
                journal_new = (journal or {}).get("new") or {}
                actual_changed = first_change
                if journal_old or journal_new:
                    try:
                        state = restore_group.live_group_state(
                            paths, journal_old, journal_new
                        )
                        actual_changed = actual_changed or bool(
                            state.get("changed")
                        )
                    except Exception:  # noqa: BLE001 - cannot prove untouched
                        actual_changed = True
                if actual_changed:
                    rollback_ok = False
                    try:
                        restore_group.rollback_to_old(paths, journal_new)
                        after = restore_group.live_group_state(
                            paths, journal_old, journal_new
                        )
                        rollback_ok = bool(
                            after.get("old_live")
                            and not after.get("new_live")
                        )
                    except Exception:  # noqa: BLE001
                        rollback_ok = False
                    if not rollback_ok:
                        if journal is not None:
                            try:
                                journal = restore_journal.set_phase(
                                    paths, journal, "recovery_required"
                                )
                            except Exception:  # noqa: BLE001
                                pass
                        # Keep the exclusive lease: the process must not write
                        # or open a normal engine over an incomplete group.
                        failure_state = "recovery_required"
                    else:
                        if journal is not None:
                            try:
                                journal = restore_journal.set_phase(
                                    paths, journal, "rolled_back"
                                )
                                terminal = restore_journal.terminal_journal(
                                    paths, journal
                                )
                                restore_journal.write_receipt(paths, terminal)
                                restore_journal.archive_terminal(paths, terminal)
                                failure_receipt = operation_id
                            except Exception:  # noqa: BLE001
                                # The rolled-back journal remains active and
                                # startup can verify it again.
                                pass
                        if lease is not None and not released:
                            lease.release()
                            released = True
                        if engine_closed:
                            try:
                                self.runtime.reopen_after_restore()
                            except Exception:  # noqa: BLE001
                                failure_reopen = True
                else:
                    if engine_closed:
                        if lease is not None and not released:
                            lease.release()
                            released = True
                        try:
                            self.runtime.reopen_after_restore()
                        except Exception:  # noqa: BLE001
                            failure_state = "recovery_required"
                    if failure_state != "recovery_required" and journal is not None:
                        try:
                            journal = restore_journal.set_phase(
                                paths,
                                journal,
                                "canceled"
                                if failure.code == "RESTORE_CANCELED"
                                else "failed_keep_old",
                            )
                            terminal = restore_journal.terminal_journal(
                                paths, journal
                            )
                            restore_journal.write_receipt(paths, terminal)
                            restore_journal.archive_terminal(paths, terminal)
                            failure_receipt = operation_id
                        except Exception:  # noqa: BLE001 - startup resolves
                            pass
                    if lease is not None and not released:
                        lease.release()
                        released = True
                executor = getattr(self.runtime, "ai_executor", None)
                if fenced and not engine_closed and executor is not None:
                    try:
                        executor.unfreeze(owner)
                    except Exception:  # noqa: BLE001
                        pass
                if failure_state != "recovery_required" and lease is not None and not released:
                    lease.release()
                    released = True
                with self._lock:
                    self._active_phase = failure_state
                    self._states[operation_id] = failure_state
                    self._active_operation = None
                failure_result = InstallResult(
                    operation_id=operation_id,
                    state=failure_state,
                    protection_display_path=str(paths.protection_path)
                    if paths.protection_path.exists()
                    else "",
                    receipt_id=failure_receipt,
                    old_group_preserved=True,
                    lease_released=released,
                    reopen_required=failure_reopen,
                    warnings=tuple([failure.code]),
                )
                with self._lock:
                    self._completed[operation_id] = (
                        prepared.prepared_id,
                        failure_result,
                    )
                failure = failure_result  # type: ignore[assignment]
            elif not released and lease is not None:
                lease.release()
                released = True
            self._install_lock.release()
        if isinstance(failure, InstallResult):
            return failure
        if failure is not None:
            state = "canceled" if failure.code == "RESTORE_CANCELED" else "failed_keep_old"
            result = InstallResult(
                operation_id=operation_id,
                state=state,
                protection_display_path=str(paths.protection_path)
                if paths.protection_path.exists()
                else "",
                receipt_id=None,
                old_group_preserved=True,
                lease_released=released,
                reopen_required=engine_closed and first_change,
                warnings=tuple([failure.code]),
            )
            with self._lock:
                self._completed[operation_id] = (prepared.prepared_id, result)
            return result
        raise AssertionError("install returned without result")

    def reopen(self) -> ReopenResult:
        operation_id = self._active_operation or ""
        try:
            self.runtime.reopen_after_restore()
            with self._lock:
                self._active_phase = "reopened"
                self._active_operation = None
            return ReopenResult(
                operation_id=operation_id,
                state="reopened",
                prompt_sync_error=getattr(self.runtime, "prompt_sync_error", None),
                notice={
                    "message_key": "restore.reopened",
                    "prompt_sync_error": getattr(
                        self.runtime, "prompt_sync_error", None
                    ),
                },
            )
        except Exception as exc:  # noqa: BLE001 - data is already installed
            code = getattr(exc, "code", "RESTORE_REOPEN_FAILED")
            with self._lock:
                self._active_phase = "reopen_failed"
            return ReopenResult(
                operation_id=operation_id,
                state="reopen_failed",
                prompt_sync_error=getattr(self.runtime, "prompt_sync_error", None),
                notice={
                    "message_key": "restore.reopen_failed",
                    "code": str(code),
                },
                error_code=str(code),
            )

    def recover(self) -> RecoveryResult:
        from app.local.restore_recovery import resolve_startup_restore

        notice = resolve_startup_restore(self.runtime)
        if notice is None:
            notice = getattr(self.runtime, "restore_notice", None)
        return RecoveryResult(
            state=str((notice or {}).get("state", "none")),
            operation_id=(notice or {}).get("operation_id"),
            notice=notice,
            receipt_id=(notice or {}).get("receipt_id"),
        )

    def cancel(self, operation_id: str) -> CancelResult:
        discard = None
        cleanup = None
        with self._lock:
            state = self._states.get(operation_id)
            event = self._cancel_events.get(operation_id)
            if state in (
                "canceled",
                "failed",
                "failed_keep_old",
                "recovery_required",
                "installed_retired",
                "reopened",
            ) or operation_id in self._completed:
                return CancelResult(operation_id, state or "terminal", False)
            if event is None:
                return CancelResult(operation_id, "unknown", False)
            if state == "installing" or self._active_operation == operation_id:
                if self._first_live_change:
                    return CancelResult(operation_id, "switching", False)
                event.set()
                return CancelResult(operation_id, "requested", True)
            if state == "preview":
                event.set()
                record = self._previews.pop(operation_id, None)
                self._states[operation_id] = "canceled"
                if record is not None:
                    discard = record.verified
                result = CancelResult(operation_id, "canceled", True)
            elif state == "prepared":
                event.set()
                prepared = self._prepared.pop(operation_id, None)
                self._previews.pop(operation_id, None)
                self._states[operation_id] = "canceled"
                cleanup = prepared
                result = CancelResult(operation_id, "canceled", True)
            else:
                event.set()
                result = CancelResult(operation_id, "requested", True)
        if discard is not None:
            try:
                self._service().discard_verified(discard)
            except Exception:  # noqa: BLE001 - cleanup is best effort
                pass
        if cleanup is not None:
            try:
                cleanup_own_operation(cleanup.paths, cleanup.operation_identity)
            except Exception:  # noqa: BLE001 - never delete protection/old
                pass
        return result
