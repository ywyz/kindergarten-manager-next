"""B1 complete local snapshot and verification.

The service captures one SQLite online backup plus every database-registered
managed image, builds a Format 1 container, and verifies the final bytes before
publishing.  It never restores into the live data root and never reads the
Windows credential master-key directory.

All plaintext staging (database, resources, manifest, payload ZIP and the
decrypted verification copy) lives under ``data_root/.backup-work`` with the
restricted current-user DACL used by the credential store.  The user-selected
output volume only receives the final container bytes; in password mode those
bytes are already ciphertext.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import sys
import tempfile
import threading
import time
import uuid
import warnings
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from app.local import (
    ai_task_service,
    backup_barrier,
    backup_format,
    backup_fs,
    backup_validate,
    backup_zip,
)

_CHUNK = 1024 * 1024
_SNAPSHOT_TIMEOUT = 60.0
_AI_IDLE_POLL = 0.05
_ZIP_DATE = (1980, 1, 1, 0, 0, 0)
_DEVICE_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


@dataclass(frozen=True)
class SnapshotProgress:
    stage: str
    done: int
    total: int
    message: str | None = None


@dataclass(frozen=True)
class SnapshotResult:
    path: Path
    snapshot_id: str
    size: int
    sha256: str
    manifest: dict[str, Any]
    verified: bool


@dataclass(frozen=True)
class VerifiedSnapshot:
    path: Path
    manifest: dict[str, Any]
    database_path: Path
    source_database_path: Path
    resources_root: Path
    staging_root: Path
    source_sha256: str
    target_sha256: str
    source_revision: str
    target_revision: str
    staging_identity: tuple[int, int] | None = None


class SnapshotService:
    def __init__(
        self,
        runtime,
        *,
        app_version: str,
        source_identity: dict[str, Any],
        executor=None,
        external_quiesce: Callable[[threading.Event], bool] | None = None,
    ):
        self.runtime = runtime
        self.app_version = str(app_version)
        self.source_identity = dict(source_identity)
        self.executor = (
            executor if executor is not None else getattr(runtime, "ai_executor", None)
        )
        self.external_quiesce = external_quiesce

    # -- public API ------------------------------------------------------
    def create(
        self,
        output: str | Path,
        *,
        password: str | None,
        cancel: threading.Event,
        progress: Callable[[SnapshotProgress], None] | None = None,
    ) -> SnapshotResult:
        output = Path(output)
        if output.suffix.lower() != backup_format.EXTENSION:
            raise backup_format.BackupFormatError(
                "BACKUP_EXTENSION_INVALID", "备份文件必须使用 .kgmbackup 扩展名"
            )
        if password is not None and (not isinstance(password, str) or not password):
            raise backup_format.BackupFormatError(
                "BACKUP_PASSWORD_REQUIRED", "加密备份必须提供非空密码"
            )
        raw_output = str(output)
        upper_output = raw_output.upper()
        if raw_output.startswith("\\\\.\\") or upper_output.startswith(
            ("\\\\?\\GLOBALROOT", "\\\\?\\VOLUME", "\\\\?\\PIPE\\")
        ):
            raise backup_format.BackupFormatError(
                "BACKUP_TARGET_INVALID", "备份目标不得是设备路径"
            )
        if not output.name or output.name in (".", ".."):
            raise backup_format.BackupFormatError(
                "BACKUP_TARGET_INVALID", "备份目标文件名不合法"
            )
        if (
            ":" in output.name
            or output.name.endswith((".", " "))
            or output.name.split(".", 1)[0].lower() in _DEVICE_NAMES
        ):
            raise backup_format.BackupFormatError(
                "BACKUP_TARGET_INVALID", "备份目标文件名不合法"
            )

        parent_guard = backup_fs.DirectoryGuard(output.parent)
        parent_guard.__enter__()
        work = None
        try:
            work = backup_fs.PrivateWorkArea(
                self._snapshot_work_root(), "snapshot"
            )
            work.__enter__()
        except BaseException:
            parent_guard.close()
            raise
        snapshot_id = uuid.uuid4().hex
        lease = None
        frozen = False
        verified: VerifiedSnapshot | None = None
        committed = False
        primary: BaseException | None = None
        try:
            self._assert_output_safe(output, parent_guard)
            barrier = backup_barrier.get_barrier(self.runtime.data_dir)
            lease = barrier.begin_intent(snapshot_id, cancel=cancel)
            self._progress(progress, "barrier", 0, 1, "准备备份")
            barrier.wait_idle(lease, timeout=_SNAPSHOT_TIMEOUT, cancel=cancel)
            self._wait_ai_terminal(cancel)
            if self.executor is not None:
                frozen = True
                self.executor.freeze(owner=snapshot_id)
                if not self._wait_executor_idle(cancel):
                    raise backup_barrier.SnapshotBusy(
                        "AI 执行器未能静止，拒绝快照"
                    )
            barrier.acquire_exclusive(lease, cancel=cancel)
            if self.executor is not None and not self.executor.is_snapshot_idle():
                raise backup_barrier.SnapshotBusy("AI 执行器仍有待持久化结果")
            if self.external_quiesce is not None:
                if not bool(self.external_quiesce(cancel)):
                    raise backup_barrier.SnapshotBusy("宿主保存未能静止，拒绝快照")
            self._check_cancel(cancel)

            schema_dir = work.subdir("schema")
            db_path = work.subdir("db") / "kindergarten.db"
            fd = work.create_file(db_path)
            os.close(fd)
            self._copy_database(db_path, cancel, progress)
            facts = backup_validate.validate_database(
                db_path,
                migrate_old=False,
                require_current=True,
                scratch_dir=schema_dir,
            )
            self._progress(progress, "db", 1, 1, "数据库快照完成")

            resources_root = work.subdir("resources")
            resource_count, resource_bytes = self._copy_resources(
                db_path,
                resources_root,
                work.path / "resources.jsonl",
                work,
                cancel,
                progress,
            )
            manifest_path = work.path / "manifest.json"
            fd = work.create_file(manifest_path)
            os.close(fd)
            manifest = self._build_manifest(
                manifest_path,
                db_path=db_path,
                resources_jsonl=work.path / "resources.jsonl",
                facts=facts,
                snapshot_id=snapshot_id,
                resource_count=resource_count,
                resource_bytes=resource_bytes,
                database_bytes=db_path.stat().st_size,
            )
            payload_path = work.path / "payload.zip"
            fd = work.create_file(payload_path)
            os.close(fd)
            self._write_payload_zip(
                payload_path,
                manifest_path=manifest_path,
                db_path=db_path,
                resources_root=resources_root,
                resources_jsonl=work.path / "resources.jsonl",
                cancel=cancel,
            )
            # The writer itself must satisfy the same bounded central-directory
            # precheck used by verify.
            backup_zip.precheck_payload_zip(payload_path, cancel=cancel)
            container_path = work.path / "container.kgmbackup"
            fd = work.create_file(container_path)
            os.close(fd)
            self._write_container(
                container_path, payload_path, password, cancel, progress
            )
            size, digest = self._size_and_hash(container_path, cancel)
            self._progress(progress, "verify", 0, 1, "校验备份")
            verified = self.verify(
                container_path,
                password=password,
                cancel=cancel,
                progress=progress,
            )
            # No cancel check after the atomic publish.  The final bytes and
            # their hash were computed before this point.
            self._check_cancel(cancel)
            self._publish(container_path, output, parent_guard, size, digest, cancel)
            committed = True
            result = SnapshotResult(
                path=output,
                snapshot_id=snapshot_id,
                size=size,
                sha256=digest,
                manifest=verified.manifest,
                verified=True,
            )
            try:
                self._progress(progress, "commit", 1, 1, "备份完成")
            except Exception:  # noqa: BLE001 - committed result is monotonic
                warnings.warn(
                    "backup progress callback failed after commit",
                    RuntimeWarning,
                    stacklevel=2,
                )
            return result
        except BaseException as exc:
            primary = exc
            raise
        finally:
            if frozen and self.executor is not None:
                try:
                    self.executor.unfreeze(owner=snapshot_id)
                except Exception as exc:  # noqa: BLE001 - lease release still runs
                    warnings.warn(
                        f"AI executor unfreeze failed: {exc}",
                        RuntimeWarning,
                        stacklevel=2,
                    )
            if lease is not None:
                lease.release()
            cleanup_error: BaseException | None = None
            if verified is not None:
                try:
                    self.discard_verified(verified)
                except Exception as exc:  # noqa: BLE001 - cleanup is reported
                    cleanup_error = exc
            try:
                if work is not None:
                    work.cleanup()
            except Exception as exc:  # noqa: BLE001 - cleanup is reported
                if cleanup_error is None:
                    cleanup_error = exc
                elif primary is not None:
                    primary.add_note(f"snapshot staging cleanup failed: {exc}")
            parent_guard.close()
            if cleanup_error is not None:
                if committed:
                    warnings.warn(
                        f"backup staging cleanup failed: {cleanup_error}",
                        RuntimeWarning,
                        stacklevel=2,
                    )
                elif primary is None:
                    raise cleanup_error
                else:
                    primary.add_note(
                        f"backup staging cleanup failed: {cleanup_error}"
                    )

    def verify(
        self,
        path: str | Path,
        *,
        password: str | None,
        cancel: threading.Event,
        progress: Callable[[SnapshotProgress], None] | None = None,
    ) -> VerifiedSnapshot:
        path = Path(path)
        if password is not None and (not isinstance(password, str) or not password):
            raise backup_format.BackupFormatError(
                "BACKUP_PASSWORD_REQUIRED", "加密备份必须提供非空密码"
            )
        raw_path = str(path)
        upper_path = raw_path.upper()
        if raw_path.startswith("\\\\.\\") or upper_path.startswith(
            ("\\\\?\\GLOBALROOT", "\\\\?\\VOLUME", "\\\\?\\PIPE\\")
        ):
            raise backup_format.BackupFormatError(
                "BACKUP_TARGET_INVALID", "备份文件不得是设备路径"
            )
        if not path.name or path.name in (".", ".."):
            raise backup_format.BackupFormatError(
                "BACKUP_TARGET_INVALID", "备份文件名不合法"
            )
        if (
            ":" in path.name
            or path.name.endswith((".", " "))
            or path.name.split(".", 1)[0].lower() in _DEVICE_NAMES
        ):
            raise backup_format.BackupFormatError(
                "BACKUP_TARGET_INVALID", "备份文件名不合法"
            )
        work = backup_fs.PrivateWorkArea(self._snapshot_work_root(), "verify")
        work.__enter__()
        lease = backup_fs.FileLease(path)
        success = False
        try:
            lease.__enter__()
            lease.seek(0)
            raw_header = lease.read(backup_format.HEADER_LEN)
            header = backup_format.parse_header(
                raw_header, file_size=lease.size
            )
            zip_path = work.path / "payload.zip"
            fd = work.create_file(zip_path)
            os.close(fd)
            self._read_payload(
                lease,
                header,
                raw_header,
                zip_path,
                password,
                cancel,
                progress,
            )
            members = backup_zip.precheck_payload_zip(zip_path, cancel=cancel)
            extracted = work.subdir("extracted")
            manifest = self._extract_payload(
                zip_path, extracted, members, work, cancel
            )
            db_path = extracted / backup_format.DATABASE_NAME
            source_path = work.subdir("source") / "kindergarten.db"
            fd = work.create_file(source_path)
            with os.fdopen(fd, "wb") as out, db_path.open("rb") as source:
                while True:
                    chunk = source.read(_CHUNK)
                    if not chunk:
                        break
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
            schema_dir = work.subdir("schema")
            facts = backup_validate.validate_database(
                db_path,
                migrate_old=True,
                require_current=False,
                scratch_dir=schema_dir,
            )
            backup_validate.validate_manifest(
                manifest,
                source_db_path=source_path,
                resources_root=extracted,
                facts=facts,
                cancel=cancel,
            )
            self._progress(progress, "verify", 1, 1, "校验完成")
            result = VerifiedSnapshot(
                path=path,
                manifest=manifest,
                database_path=db_path,
                source_database_path=source_path,
                resources_root=extracted,
                staging_root=work.path,
                source_sha256=facts["source_sha256"],
                target_sha256=facts["database_sha256"],
                source_revision=facts["source_revision"],
                target_revision=facts["revision"],
                staging_identity=work.path_identity,
            )
            work.detach()
            success = True
            return result
        finally:
            lease.close()
            if not success:
                active = sys.exc_info()[1]
                try:
                    work.cleanup()
                except Exception as cleanup:  # noqa: BLE001 - preserve primary
                    if active is not None:
                        active.add_note(f"verify staging cleanup failed: {cleanup}")
                    else:
                        raise

    @staticmethod
    def _overlaps(left: Path, right: Path) -> bool:
        return (
            left == right
            or left in right.parents
            or right in left.parents
        )

    def _snapshot_work_root(self) -> Path:
        try:
            data_root = Path(self.runtime.data_dir).resolve(strict=False)
            credential = getattr(self.runtime, "credential_root", None)
            credential_root = (
                Path(credential).resolve(strict=False)
                if credential is not None
                else None
            )
        except OSError as exc:
            raise backup_fs.BackupPathError(
                "BACKUP_WORK_ROOT_UNSAFE",
                "无法核验备份工作区与现用数据根/凭据根的隔离",
            ) from exc
        temp_root = Path(tempfile.gettempdir())
        digest = hashlib.sha256(
            os.path.normcase(str(data_root)).encode("utf-8")
        ).hexdigest()[:16]
        candidates: list[Path] = []
        if credential is not None:
            candidates.append(Path(credential).parent / "backup-work")
        candidates.append(temp_root / "KindergartenManager-backup-work")
        candidates.append(
            temp_root / f"KindergartenManager-backup-work-{digest}"
        )
        seen: set[str] = set()
        for candidate in candidates:
            try:
                resolved = candidate.resolve(strict=False)
            except OSError:
                continue
            key = os.path.normcase(os.path.abspath(str(resolved)))
            if key in seen:
                continue
            seen.add(key)
            if self._overlaps(resolved, data_root):
                continue
            if credential_root is not None and self._overlaps(
                resolved, credential_root
            ):
                continue
            return resolved
        raise backup_fs.BackupPathError(
            "BACKUP_WORK_ROOT_UNSAFE",
            "没有与现用数据根及凭据根隔离的备份工作区",
        )

    def discard_verified(self, snapshot: VerifiedSnapshot) -> None:
        root = self._snapshot_work_root().absolute()
        target = Path(snapshot.staging_root).absolute()
        if target.parent != root or not target.name.startswith("verify-"):
            raise backup_fs.BackupPathError(
                "BACKUP_CLEANUP_UNSAFE", "拒绝清理非本次隔离区路径"
            )
        with backup_fs.DirectoryGuard(root):
            backup_fs.remove_tree(
                target, expected_identity=snapshot.staging_identity
            )

    # -- barrier helpers -------------------------------------------------
    @staticmethod
    def _check_cancel(cancel: threading.Event) -> None:
        if cancel.is_set():
            raise backup_barrier.SnapshotCancelled("备份已取消")

    @staticmethod
    def _progress(
        progress: Callable[[SnapshotProgress], None] | None,
        stage: str,
        done: int,
        total: int,
        message: str,
    ) -> None:
        if progress is not None:
            progress(SnapshotProgress(stage, done, total, message))

    def _wait_ai_terminal(self, cancel: threading.Event) -> None:
        deadline = time.monotonic() + _SNAPSHOT_TIMEOUT
        while True:
            self._check_cancel(cancel)
            session = self.runtime.session()
            try:
                snapshot = ai_task_service.active_task_snapshot(session)
            finally:
                session.close()
            live = int(snapshot.get("live") or 0)
            if live == 0:
                return
            if self.executor is None or not self.executor.is_runnable():
                raise backup_barrier.SnapshotBusy(
                    "存在未完成 AI 任务且执行器不可用"
                )
            if time.monotonic() >= deadline:
                raise backup_barrier.SnapshotBusy("等待 AI 任务完成超时")
            time.sleep(_AI_IDLE_POLL)

    def _wait_executor_idle(self, cancel: threading.Event) -> bool:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            self._check_cancel(cancel)
            if self.executor is None or self.executor.is_snapshot_idle():
                return True
            time.sleep(_AI_IDLE_POLL)
        return False

    # -- database --------------------------------------------------------
    def _copy_database(
        self,
        destination: Path,
        cancel: threading.Event,
        progress: Callable[[SnapshotProgress], None] | None,
    ) -> None:
        self._check_cancel(cancel)
        db_path = Path(self.runtime.db_path)
        if not db_path.is_file():
            raise backup_format.BackupFormatError(
                "BACKUP_DB_COPY_FAILED", "当前数据库文件不存在"
            )
        source = sqlite3.connect(f"{db_path.as_uri()}?mode=rw", uri=True)
        target = None
        try:
            target = sqlite3.connect(str(destination))

            def backup_progress(status, remaining, total):
                self._check_cancel(cancel)
                if progress is not None and total:
                    self._progress(
                        progress,
                        "db",
                        max(0, int(total) - int(remaining)),
                        int(total),
                        "复制数据库",
                    )

            source.backup(
                target,
                pages=256,
                progress=backup_progress,
                sleep=0.01,
            )
        except backup_barrier.SnapshotCancelled:
            raise
        except sqlite3.Error as exc:
            if cancel.is_set():
                raise backup_barrier.SnapshotCancelled("备份已取消") from exc
            raise backup_format.BackupFormatError(
                "BACKUP_DB_COPY_FAILED", "SQLite 在线备份失败"
            ) from exc
        finally:
            if target is not None:
                target.close()
            source.close()

    # -- resources -------------------------------------------------------
    def _copy_resources(
        self,
        db_path: Path,
        resources_root: Path,
        jsonl_path: Path,
        work: backup_fs.PrivateWorkArea,
        cancel: threading.Event,
        progress: Callable[[SnapshotProgress], None] | None,
    ) -> tuple[int, int]:
        count = 0
        total_bytes = 0
        fd = work.create_file(jsonl_path)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as jsonl:
            for entry in backup_validate.iter_registered_resources(db_path):
                self._check_cancel(cancel)
                source_path = (
                    Path(self.runtime.data_dir)
                    .joinpath(*PurePosixPath(entry["path"]).parts)
                )
                target = resources_root.joinpath(
                    *PurePosixPath(entry["path"]).parts
                )
                work.subdir(*target.parent.relative_to(work.path).parts)
                size, digest = self._copy_managed_file(
                    source_path, target, work, cancel
                )
                if size > backup_format.MAX_RESOURCE_BYTES:
                    raise backup_format.BackupFormatError(
                        "BACKUP_RESOURCE_TOO_LARGE", "备份资源超过单资源上限"
                    )
                if digest != entry["sha256"]:
                    raise backup_format.BackupFormatError(
                        "BACKUP_RESOURCE_HASH", "受管资源与数据库 hash 不一致"
                    )
                item = {
                    "asset_id": entry["asset_id"],
                    "bytes": size,
                    "derivative_id": entry["derivative_id"],
                    "kind": entry["kind"],
                    "observation_id": entry["observation_id"],
                    "path": entry["path"],
                    "sha256": digest,
                }
                jsonl.write(
                    json.dumps(
                        item,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
                jsonl.write("\n")
                count += 1
                total_bytes += size
                if (
                    count > backup_format.MAX_MEMBERS
                    or total_bytes > backup_format.MAX_EXPANDED_BYTES
                ):
                    raise backup_format.BackupFormatError(
                        "BACKUP_SIZE_INVALID", "备份资源数量或展开体积超过上限"
                    )
                if count == 1 or count % 50 == 0:
                    self._progress(
                        progress, "resources", count, 0, "复制受管资源"
                    )
            jsonl.flush()
            os.fsync(jsonl.fileno())
        return count, total_bytes

    @staticmethod
    def _copy_managed_file(
        source: Path,
        target: Path,
        work: backup_fs.PrivateWorkArea,
        cancel: threading.Event,
    ) -> tuple[int, str]:
        hasher = hashlib.sha256()
        total = 0
        with backup_fs.FileLease(source) as lease:
            fd = work.create_file(target)
            with os.fdopen(fd, "wb") as out:
                while True:
                    if cancel.is_set():
                        raise backup_barrier.SnapshotCancelled("备份已取消")
                    chunk = lease.read(_CHUNK)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > backup_format.MAX_RESOURCE_BYTES:
                        raise backup_format.BackupFormatError(
                            "BACKUP_RESOURCE_TOO_LARGE", "备份资源超过单资源上限"
                        )
                    hasher.update(chunk)
                    out.write(chunk)
                if total != lease.size:
                    raise backup_format.BackupFormatError(
                        "BACKUP_RESOURCE_CHANGED", "受管资源在复制期间发生变化"
                    )
                out.flush()
                os.fsync(out.fileno())
        return total, hasher.hexdigest()

    # -- manifest --------------------------------------------------------
    def _build_manifest(
        self,
        manifest_path: Path,
        *,
        db_path: Path,
        resources_jsonl: Path,
        facts: dict[str, Any],
        snapshot_id: str,
        resource_count: int,
        resource_bytes: int,
        database_bytes: int,
    ) -> dict[str, Any]:
        created_at = datetime.now(timezone.utc).isoformat()
        database = {
            "path": backup_format.DATABASE_NAME,
            "bytes": database_bytes,
            "sha256": backup_format.sha256_file(db_path),
        }
        counts = {
            "database_bytes": database_bytes,
            "resources": resource_count,
            "resources_bytes": resource_bytes,
        }
        prefix_values = {
            "app_version": self.app_version,
            "ai_contracts": facts["source_ai_contracts"],
            "counts": counts,
            "created_at": created_at,
            "database": database,
            "database_revision": facts["source_revision"],
            "format_version": backup_format.FORMAT_VERSION,
        }
        prefix = (
            "{"
            + ",".join(
                f"{json.dumps(key)}:"
                f"{json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}"
                for key, value in prefix_values.items()
            )
            + ',"resources":['
        )
        suffix = (
            '],"snapshot_id":'
            + json.dumps(snapshot_id)
            + ',"source_identity":'
            + json.dumps(
                self.source_identity,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "}"
        )
        with manifest_path.open("wb") as out:
            out.write(prefix.encode("utf-8"))
            first = True
            with resources_jsonl.open("rb") as source:
                for line in source:
                    if not line.strip():
                        continue
                    if not first:
                        out.write(b",")
                    first = False
                    out.write(line.rstrip(b"\r\n"))
            out.write(suffix.encode("utf-8"))
            out.flush()
            os.fsync(out.fileno())
        if manifest_path.stat().st_size > backup_format.MAX_MANIFEST_BYTES:
            raise backup_format.BackupFormatError(
                "BACKUP_MANIFEST_TOO_LARGE", "备份清单超过上限"
            )
        return backup_validate.parse_manifest_json(manifest_path.read_bytes())

    # -- ZIP / container -------------------------------------------------
    def _write_payload_zip(
        self,
        payload: Path,
        *,
        manifest_path: Path,
        db_path: Path,
        resources_root: Path,
        resources_jsonl: Path,
        cancel: threading.Event,
    ) -> None:
        with zipfile.ZipFile(
            payload, "w", compression=zipfile.ZIP_STORED
        ) as archive:
            self._zip_add(archive, backup_format.MANIFEST_NAME, manifest_path, cancel)
            self._zip_add(archive, backup_format.DATABASE_NAME, db_path, cancel)
            with resources_jsonl.open("r", encoding="utf-8") as source:
                for line in source:
                    if not line.strip():
                        continue
                    entry = json.loads(line)
                    path = entry["path"]
                    self._zip_add(
                        archive,
                        path,
                        resources_root.joinpath(*PurePosixPath(path).parts),
                        cancel,
                    )

    @staticmethod
    def _zip_add(
        archive: zipfile.ZipFile,
        name: str,
        source: Path,
        cancel: threading.Event,
    ) -> None:
        size = source.stat().st_size
        info = zipfile.ZipInfo(name, date_time=_ZIP_DATE)
        info.compress_type = zipfile.ZIP_STORED
        info.external_attr = 0o600 << 16
        info.file_size = size
        with source.open("rb") as handle, archive.open(info, "w") as target:
            while True:
                if cancel.is_set():
                    raise backup_barrier.SnapshotCancelled("备份已取消")
                chunk = handle.read(_CHUNK)
                if not chunk:
                    break
                target.write(chunk)

    def _write_container(
        self,
        destination: Path,
        payload: Path,
        password: str | None,
        cancel: threading.Event,
        progress: Callable[[SnapshotProgress], None] | None,
    ) -> None:
        payload_size = payload.stat().st_size
        overhead = backup_format.HEADER_LEN + (
            backup_format.TAG_LEN if password is not None else 0
        )
        if payload_size + overhead > backup_format.MAX_TOTAL_BYTES:
            raise backup_format.BackupFormatError(
                "BACKUP_SIZE_INVALID", "备份载荷超过上限"
            )
        if password is None:
            mode = backup_format.MODE_PLAINTEXT
            salt = b""
            nonce = b""
        else:
            mode = backup_format.MODE_PASSWORD
            salt = secrets.token_bytes(backup_format.SALT_LEN)
            nonce = secrets.token_bytes(backup_format.NONCE_LEN)
        header = backup_format.encode_header(
            mode=mode, payload_len=payload_size, salt=salt, nonce=nonce
        )
        with destination.open("wb") as out, payload.open("rb") as source:
            out.write(header)
            if mode == backup_format.MODE_PLAINTEXT:
                while True:
                    if cancel.is_set():
                        raise backup_barrier.SnapshotCancelled("备份已取消")
                    chunk = source.read(_CHUNK)
                    if not chunk:
                        break
                    out.write(chunk)
            else:
                key = backup_format.derive_key(password or "", salt)
                try:
                    tag = backup_format.encrypt_payload(
                        source,
                        out,
                        key=key,
                        nonce=nonce,
                        aad=header,
                        length=payload_size,
                        cancel=cancel,
                        progress=lambda done, total: self._progress(
                            progress, "encrypt", done, total, "加密备份"
                        ),
                    )
                except backup_format.BackupFormatError as exc:
                    if exc.code == "BACKUP_CANCELLED":
                        raise backup_barrier.SnapshotCancelled("备份已取消") from exc
                    raise
                out.write(tag)
            out.flush()
            os.fsync(out.fileno())

    def _read_payload(
        self,
        source: backup_fs.FileLease,
        header: backup_format.BackupHeader,
        raw_header: bytes,
        destination: Path,
        password: str | None,
        cancel: threading.Event,
        progress: Callable[[SnapshotProgress], None] | None,
    ) -> None:
        source.seek(backup_format.HEADER_LEN)
        with destination.open("wb") as out:
            if header.mode == backup_format.MODE_PLAINTEXT:
                remaining = header.payload_len
                while remaining:
                    if cancel.is_set():
                        raise backup_barrier.SnapshotCancelled("备份已取消")
                    chunk = source.read(min(_CHUNK, remaining))
                    if not chunk:
                        raise backup_format.BackupFormatError(
                            "BACKUP_TRUNCATED", "备份载荷提前结束"
                        )
                    out.write(chunk)
                    remaining -= len(chunk)
            else:
                if password is None or not password:
                    raise backup_format.BackupFormatError(
                        "BACKUP_PASSWORD_REQUIRED", "加密备份需要密码"
                    )
                key = backup_format.derive_key(password, header.salt)
                source.seek(backup_format.HEADER_LEN + header.payload_len)
                tag = source.read(backup_format.TAG_LEN)
                if len(tag) != backup_format.TAG_LEN:
                    raise backup_format.BackupFormatError(
                        "BACKUP_TRUNCATED", "认证标签缺失"
                    )
                source.seek(backup_format.HEADER_LEN)
                try:
                    backup_format.decrypt_payload(
                        source,
                        out,
                        key=key,
                        nonce=header.nonce,
                        aad=raw_header,
                        length=header.payload_len,
                        tag=tag,
                        cancel=cancel,
                        progress=lambda done, total: self._progress(
                            progress, "decrypt", done, total, "解密备份"
                        ),
                    )
                except backup_format.BackupFormatError as exc:
                    if exc.code == "BACKUP_CANCELLED":
                        raise backup_barrier.SnapshotCancelled("备份已取消") from exc
                    raise
            out.flush()
            os.fsync(out.fileno())
        if destination.stat().st_size != header.payload_len:
            raise backup_format.BackupFormatError(
                "BACKUP_SIZE_INVALID", "解密载荷长度不匹配"
            )

    def _extract_payload(
        self,
        payload: Path,
        destination: Path,
        members: list[backup_zip.ZipMember],
        work: backup_fs.PrivateWorkArea,
        cancel: threading.Event,
    ) -> dict[str, Any]:
        names = [member.name for member in members]
        if len(names) < 2 or names[0] != backup_format.MANIFEST_NAME:
            raise backup_format.BackupFormatError(
                "BACKUP_PAYLOAD_INVALID", "备份成员顺序不合法"
            )
        if names[1] != backup_format.DATABASE_NAME:
            raise backup_format.BackupFormatError(
                "BACKUP_PAYLOAD_INVALID", "备份成员顺序不合法"
            )
        if names[2:] != sorted(names[2:]):
            raise backup_format.BackupFormatError(
                "BACKUP_PAYLOAD_INVALID", "备份资源顺序不合法"
            )
        try:
            archive = zipfile.ZipFile(payload)
        except (OSError, zipfile.BadZipFile) as exc:
            raise backup_format.BackupFormatError(
                "BACKUP_PAYLOAD_INVALID", "备份载荷不是有效 ZIP"
            ) from exc
        with archive:
            infos = archive.infolist()
            if [info.filename for info in infos] != names:
                raise backup_format.BackupFormatError(
                    "BACKUP_PAYLOAD_INVALID", "备份成员列表不一致"
                )
            for index, (info, member) in enumerate(zip(infos, members)):
                if cancel.is_set():
                    raise backup_barrier.SnapshotCancelled("备份已取消")
                if info.flag_bits & 0x1:
                    raise backup_format.BackupFormatError(
                        "BACKUP_PAYLOAD_INVALID", "备份含加密 ZIP 成员"
                    )
                if info.compress_type != zipfile.ZIP_STORED:
                    raise backup_format.BackupFormatError(
                        "BACKUP_PAYLOAD_INVALID", "备份 ZIP 必须为 STORED"
                    )
                if info.is_dir() or (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise backup_format.BackupFormatError(
                        "BACKUP_PAYLOAD_INVALID", "备份含目录或符号链接"
                    )
                if info.file_size != member.size:
                    raise backup_format.BackupFormatError(
                        "BACKUP_PAYLOAD_INVALID", "备份成员大小伪造"
                    )
                if index == 0:
                    if info.file_size > backup_format.MAX_MANIFEST_BYTES:
                        raise backup_format.BackupFormatError(
                            "BACKUP_MANIFEST_TOO_LARGE", "备份清单超过上限"
                        )
                    target = destination / backup_format.MANIFEST_NAME
                elif index == 1:
                    if info.file_size > backup_format.MAX_DATABASE_BYTES:
                        raise backup_format.BackupFormatError(
                            "BACKUP_DB_TOO_LARGE", "备份数据库超过上限"
                        )
                    target = destination / backup_format.DATABASE_NAME
                else:
                    backup_validate.safe_relative_path(member.name)
                    if info.file_size > backup_format.MAX_RESOURCE_BYTES:
                        raise backup_format.BackupFormatError(
                            "BACKUP_RESOURCE_TOO_LARGE", "备份资源超过上限"
                        )
                    target = destination.joinpath(
                        *PurePosixPath(member.name).parts
                    )
                work.subdir(*target.parent.relative_to(work.path).parts)
                written = 0
                with archive.open(info) as source:
                    fd = work.create_file(target)
                    with os.fdopen(fd, "wb") as out:
                        while True:
                            if cancel.is_set():
                                raise backup_barrier.SnapshotCancelled("备份已取消")
                            chunk = source.read(_CHUNK)
                            if not chunk:
                                break
                            written += len(chunk)
                            if written > info.file_size:
                                raise backup_format.BackupFormatError(
                                    "BACKUP_PAYLOAD_INVALID", "备份成员大小伪造"
                                )
                            out.write(chunk)
                        out.flush()
                        os.fsync(out.fileno())
                if written != info.file_size:
                    raise backup_format.BackupFormatError(
                        "BACKUP_PAYLOAD_INVALID", "备份成员截断"
                    )
        try:
            manifest = backup_validate.parse_manifest_json(
                (destination / backup_format.MANIFEST_NAME).read_bytes()
            )
        except OSError as exc:
            raise backup_format.BackupFormatError(
                "BACKUP_MANIFEST_INVALID", "备份清单无法读取"
            ) from exc
        if not isinstance(manifest, dict) or not isinstance(
            manifest.get("resources"), list
        ):
            raise backup_format.BackupFormatError(
                "BACKUP_MANIFEST_INVALID", "备份清单不是对象或资源列表"
            )
        if len(manifest["resources"]) > backup_format.MAX_MEMBERS:
            raise backup_format.BackupFormatError(
                "BACKUP_MANIFEST_INVALID", "备份清单资源数量超过上限"
            )
        resource_names = []
        for entry in manifest["resources"]:
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                raise backup_format.BackupFormatError(
                    "BACKUP_MANIFEST_INVALID", "备份清单资源项不合法"
                )
            resource_names.append(entry["path"])
        if names[2:] != resource_names:
            raise backup_format.BackupFormatError(
                "BACKUP_PAYLOAD_INVALID", "ZIP 成员与清单资源不一一对应"
            )
        return manifest

    # -- output ----------------------------------------------------------
    def _assert_output_safe(
        self, output: Path, parent_guard: backup_fs.DirectoryGuard
    ) -> None:
        final_parent = parent_guard.final_path
        if final_parent is None:
            raise backup_format.BackupFormatError(
                "BACKUP_TARGET_INVALID", "备份目标目录无法核验"
            )
        data_root = Path(self.runtime.data_dir).resolve(strict=False)
        target_parent = final_parent.resolve(strict=False)
        if target_parent == data_root or data_root in target_parent.parents:
            raise backup_format.BackupFormatError(
                "BACKUP_TARGET_INVALID", "备份目标不得位于数据根内"
            )
        credential = getattr(self.runtime, "credential_root", None)
        if credential is not None:
            credential = Path(credential).resolve(strict=False)
            if target_parent == credential or credential in target_parent.parents:
                raise backup_format.BackupFormatError(
                    "BACKUP_TARGET_INVALID", "备份目标不得位于凭据根内"
                )
        work_root = self._snapshot_work_root().resolve(strict=False)
        if target_parent == work_root or work_root in target_parent.parents:
            raise backup_format.BackupFormatError(
                "BACKUP_TARGET_INVALID", "备份目标不得位于备份隔离工作区"
            )

    def _publish(
        self,
        container: Path,
        output: Path,
        parent_guard: backup_fs.DirectoryGuard,
        expected_size: int,
        expected_sha256: str,
        cancel: threading.Event,
    ) -> None:
        fd, temp = backup_fs.create_output_temp(
            output.parent, "kgm-backup"
        )
        published = False
        try:
            hasher = hashlib.sha256()
            total = 0
            with os.fdopen(fd, "wb") as out, container.open("rb") as source:
                while True:
                    if cancel.is_set():
                        raise backup_barrier.SnapshotCancelled("备份已取消")
                    chunk = source.read(_CHUNK)
                    if not chunk:
                        break
                    total += len(chunk)
                    hasher.update(chunk)
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
            if total != expected_size or hasher.hexdigest() != expected_sha256:
                raise backup_format.BackupFormatError(
                    "BACKUP_TARGET_INVALID", "备份临时输出与已校验容器不一致"
                )
            self._check_cancel(cancel)
            self._publish_no_replace(temp, output)
            published = True
        finally:
            if not published:
                try:
                    os.unlink(temp)
                except OSError as exc:
                    warnings.warn(
                        f"backup temp output cleanup failed: {exc}",
                        RuntimeWarning,
                        stacklevel=2,
                    )

    @staticmethod
    def _publish_no_replace(temp: Path, target: Path) -> None:
        """Compatibility seam used by independent probes and tests."""
        backup_fs.publish_no_replace(temp, target)

    @staticmethod
    def _size_and_hash(
        path: Path, cancel: threading.Event
    ) -> tuple[int, str]:
        return (
            path.stat().st_size,
            backup_format.sha256_file(path, cancel=cancel),
        )
