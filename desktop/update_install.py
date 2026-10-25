"""D3-U U2 install plan, authorization and result records.

The page never supplies a URL, path, PID, command or digest.  The old host
builds a plan from the already verified U1 package, binds it to one close
generation, and starts a small updater helper.  The helper independently
re-verifies the signed metadata and the original ZIP before touching the
program directory.  A later ordinary close can never revive a revoked plan.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import update_paths
from update_fs import PathSafetyError, ensure_safe_path, ensure_safe_tree
from update_identity import AppIdentity
from update_manifest import (
    MAX_PACKAGE_BYTES,
    ManifestError,
    UpdateManifest,
    parse_signed_manifest,
    strict_json_loads,
    verify_package_zip,
)
from update_process import (
    InstallLockError,
    ProcessIdentity,
    current_process_identity,
    identity_from_dict,
    process_identity,
    process_matches,
    wait_for_process_exit,
)
from update_trust import ReleaseConfigError, ReleaseSource, load_release_source

PLAN_SCHEMA = 1
AUTH_SCHEMA = 1
RECEIPT_SCHEMA = 1
RESULT_SCHEMA = 1
PLAN_ENV = "KGM_UPDATE_PLAN_FILE"
READY_ENV = "KGM_UPDATE_READY_FILE"
DEFAULT_HELPER_NAME = "KindergartenManagerUpdater.exe"
DEFAULT_AUTH_TIMEOUT = 300.0
DEFAULT_OLD_EXIT_TIMEOUT = 60.0
DEFAULT_READY_TIMEOUT = 120.0
ARM_GRACE_SECONDS = 5.0


class InstallPlanError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    """Write a private JSON record atomically; never overwrite a directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode(
        "utf-8"
    )
    try:
        with tmp.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def _safe_json(path: Path) -> dict[str, Any]:
    try:
        data = strict_json_loads(path.read_bytes(), package=True)
    except (OSError, ManifestError) as exc:
        raise InstallPlanError("INSTALL_RECORD_INVALID", "安装记录无法读取") from exc
    if not isinstance(data, dict):
        raise InstallPlanError("INSTALL_RECORD_INVALID", "安装记录不是对象")
    return data


def _same_volume(left: Path, right: Path) -> bool:
    left_drive = os.path.splitdrive(str(left.absolute()))[0].casefold()
    right_drive = os.path.splitdrive(str(right.absolute()))[0].casefold()
    if not left_drive or not right_drive:
        return False
    return left_drive == right_drive


def _overlaps(left: Path, right: Path) -> bool:
    try:
        a = left.resolve(strict=False)
        b = right.resolve(strict=False)
    except OSError:
        return True
    return a == b or a in b.parents or b in a.parents


def _assert_separate(paths: list[tuple[str, Path]], *, data: Path, credential: Path) -> None:
    for label, path in paths:
        if _overlaps(path, data) or _overlaps(path, credential):
            raise InstallPlanError(
                "INSTALL_PATH_OVERLAP",
                f"{label}不得与数据或凭据根重叠",
            )


@dataclass(frozen=True)
class InstallPlan:
    schema_version: int
    plan_id: str
    nonce: str
    created_at: str
    current: dict[str, Any]
    target: dict[str, Any]
    old_process: dict[str, Any]
    data_dir: str
    credential_root: str
    install_root: str
    install_app_dir: str
    backup_dir: str
    state_dir: str
    staging_dir: str
    package_zip: str
    metadata_path: str
    release_config: str
    helper_path: str
    new_app_path: str
    new_app_command: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def plan_path(self) -> Path:
        return Path(self.state_dir) / "install-plan.json"

    @property
    def auth_path(self) -> Path:
        return Path(self.state_dir) / "authorization.json"

    @property
    def ready_path(self) -> Path:
        return Path(self.state_dir) / "ready.json"

    @property
    def result_path(self) -> Path:
        return Path(self.state_dir) / "install-result.json"

    @property
    def phases_dir(self) -> Path:
        return Path(self.state_dir) / "phases"

    @property
    def helper_process_path(self) -> Path:
        return Path(self.state_dir) / "helper-process.json"


def _target_from_manifest(manifest: UpdateManifest) -> dict[str, Any]:
    return {
        "app_id": manifest.app_id,
        "channel": manifest.channel,
        "version": manifest.version,
        "build_id": manifest.build_id,
        "platform": manifest.platform,
        "arch": manifest.arch,
        "package_format": manifest.package_format,
        "package_root": manifest.package_root,
        "executable": manifest.executable,
        "package_size": manifest.package_size,
        "package_sha256": manifest.package_sha256,
        "database_revision": manifest.database_revision,
        "supported_source_revisions": list(manifest.supported_source_revisions),
        "key_id": manifest.key_id,
    }


def build_install_plan(
    *,
    identity: AppIdentity,
    manifest: UpdateManifest,
    metadata_raw: bytes,
    staging_dir: str | Path,
    package_zip: str | Path,
    data_dir: str | Path,
    credential_root: str | Path,
    install_root: str | Path | None = None,
    app_dir: str | Path | None = None,
    helper_command: list[str] | None = None,
    release_config: str | Path | None = None,
    old_process: ProcessIdentity | None = None,
    new_app_command: list[str] | None = None,
    test_only: bool = False,
) -> InstallPlan:
    """Create and persist a fresh plan from already U1-verified inputs."""
    data = Path(data_dir)
    credential = Path(credential_root)
    staging = Path(staging_dir)
    archive = Path(package_zip)
    install = Path(install_root) if install_root is not None else update_paths.install_root()
    app = Path(app_dir) if app_dir is not None else update_paths.install_app_dir()
    state_root = install / "install-state"
    backup_root = install / "backups"
    plan_id = uuid.uuid4().hex
    nonce = secrets.token_urlsafe(32)
    state_dir = state_root / plan_id
    backup_dir = backup_root / plan_id
    try:
        ensure_safe_path(staging)
        ensure_safe_path(archive)
        ensure_safe_path(install)
        ensure_safe_path(state_dir)
        ensure_safe_path(backup_dir)
    except PathSafetyError as exc:
        raise InstallPlanError("INSTALL_PATH_UNSAFE", str(exc)) from exc
    if not staging.is_dir():
        raise InstallPlanError("INSTALL_STAGING_MISSING", "更新暂存目录不存在")
    if not archive.is_file() or archive.stat().st_size != manifest.package_size:
        raise InstallPlanError("INSTALL_PACKAGE_MISMATCH", "原 ZIP 大小不符")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != manifest.package_sha256:
        raise InstallPlanError("INSTALL_PACKAGE_MISMATCH", "原 ZIP 摘要不符")
    if not _same_volume(staging, install):
        raise InstallPlanError("INSTALL_VOLUME_MISMATCH", "暂存与程序目录不在同一卷")
    _assert_separate(
        [("暂存目录", staging), ("程序目录", install), ("程序", app)],
        data=data,
        credential=credential,
    )
    if _overlaps(app, install / "updater"):
        raise InstallPlanError("INSTALL_HELPER_IN_APP", "更新器不得位于待切换程序目录")
    if helper_command is None:
        candidate = install / "updater" / DEFAULT_HELPER_NAME
        helper_command = [str(candidate)]
    helper = Path(helper_command[0])
    if not test_only:
        if not helper.is_file():
            raise InstallPlanError("INSTALL_HELPER_MISSING", "独立更新器不存在")
        if _overlaps(helper, app):
            raise InstallPlanError("INSTALL_HELPER_IN_APP", "更新器不得位于待切换程序目录")
    old = old_process or current_process_identity()
    new_command = list(new_app_command or [])
    if new_command and not test_only:
        raise InstallPlanError("INSTALL_TEST_COMMAND", "产品安装计划不接受测试命令")
    plan = InstallPlan(
        schema_version=PLAN_SCHEMA,
        plan_id=plan_id,
        nonce=nonce,
        created_at=_now(),
        current=identity.as_dict(),
        target=_target_from_manifest(manifest),
        old_process=old.as_dict(),
        data_dir=str(data.absolute()),
        credential_root=str(credential.absolute()),
        install_root=str(install.absolute()),
        install_app_dir=str(app.absolute()),
        backup_dir=str(backup_dir.absolute()),
        state_dir=str(state_dir.absolute()),
        staging_dir=str(staging.absolute()),
        package_zip=str(archive.absolute()),
        metadata_path=str((state_dir / "update_metadata.json").absolute()),
        release_config=str(Path(release_config).absolute()) if release_config else "",
        helper_path=str(helper.absolute()),
        new_app_path=str((app / manifest.executable).absolute()),
        new_app_command=new_command,
    )
    state_dir.mkdir(parents=True, exist_ok=False)
    backup_dir.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json(state_dir / "update_metadata.json", {"raw": metadata_raw.decode("utf-8")})
    _atomic_json(plan.plan_path, plan.as_dict())
    write_authorization(
        plan,
        state="pending",
        close_request_id=None,
        close_generation=None,
    )
    return plan


def load_plan(path: str | Path) -> InstallPlan:
    raw = _safe_json(Path(path))
    if raw.get("schema_version") != PLAN_SCHEMA:
        raise InstallPlanError("INSTALL_PLAN_INVALID", "安装计划 schema 不支持")
    required = {
        "schema_version",
        "plan_id",
        "nonce",
        "created_at",
        "current",
        "target",
        "old_process",
        "data_dir",
        "credential_root",
        "install_root",
        "install_app_dir",
        "backup_dir",
        "state_dir",
        "staging_dir",
        "package_zip",
        "metadata_path",
        "release_config",
        "helper_path",
        "new_app_path",
        "new_app_command",
    }
    if set(raw) != required:
        raise InstallPlanError("INSTALL_PLAN_INVALID", "安装计划字段不合法")
    if not all(isinstance(raw.get(key), str) and raw.get(key) for key in (
        "plan_id",
        "nonce",
        "created_at",
        "data_dir",
        "credential_root",
        "install_root",
        "install_app_dir",
        "backup_dir",
        "state_dir",
        "staging_dir",
        "package_zip",
        "metadata_path",
        "helper_path",
        "new_app_path",
    )):
        raise InstallPlanError("INSTALL_PLAN_INVALID", "安装计划路径字段为空")
    if not isinstance(raw.get("new_app_command"), list):
        raise InstallPlanError("INSTALL_PLAN_INVALID", "安装命令不合法")
    return InstallPlan(**raw)


def write_authorization(
    plan: InstallPlan,
    *,
    state: str,
    close_request_id: str | None,
    close_generation: int | None,
    reason: str | None = None,
) -> None:
    if state not in ("pending", "authorized", "revoked"):
        raise InstallPlanError("INSTALL_AUTH_INVALID", "授权状态不合法")
    _atomic_json(
        plan.auth_path,
        {
            "schema_version": AUTH_SCHEMA,
            "plan_id": plan.plan_id,
            "nonce": plan.nonce,
            "state": state,
            "close_request_id": close_request_id,
            "close_generation": close_generation,
            "reason": reason,
            "updated_at": _now(),
        },
    )


def read_authorization(plan: InstallPlan) -> dict[str, Any]:
    data = _safe_json(plan.auth_path)
    if (
        data.get("schema_version") != AUTH_SCHEMA
        or data.get("plan_id") != plan.plan_id
        or data.get("nonce") != plan.nonce
        or data.get("state") not in ("pending", "authorized", "revoked")
    ):
        raise InstallPlanError("INSTALL_AUTH_INVALID", "安装授权记录不匹配")
    return data


def _append_phase(plan: InstallPlan, phase: str, **details: Any) -> None:
    """Append one phase as its own file.

    Multiple helpers/recorders may operate on the same plan; a shared JSON
    read-modify-replace would lose one writer's records.  A unique immutable
    file per record is cross-process safe.
    """
    directory = plan.phases_dir
    directory.mkdir(parents=True, exist_ok=True)
    name = (
        f"{time.time_ns():020d}-{os.getpid()}-"
        f"{secrets.token_hex(6)}.json"
    )
    _atomic_json(
        directory / name,
        {"at": _now(), "phase": phase, **details},
    )


def read_phases_at(directory: Path) -> list[dict[str, Any]]:
    if not directory.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            value = strict_json_loads(path.read_bytes(), package=True)
        except (OSError, ManifestError) as exc:
            raise InstallPlanError(
                "INSTALL_PHASE_RECORD_INVALID", "安装阶段记录损坏"
            ) from exc
        if not isinstance(value, dict) or not isinstance(value.get("phase"), str):
            raise InstallPlanError(
                "INSTALL_PHASE_RECORD_INVALID", "安装阶段记录不合法"
            )
        records.append(value)
    return records


def read_phases(plan: InstallPlan) -> list[dict[str, Any]]:
    """Read every complete phase record; a corrupt record is not discarded."""
    return read_phases_at(plan.phases_dir)


def write_result(plan: InstallPlan, status: str, code: str | None = None, **details: Any) -> dict[str, Any]:
    if status not in ("success", "failed", "unknown", "revoked"):
        raise InstallPlanError("INSTALL_RESULT_INVALID", "安装结果状态不合法")
    value = {
        "schema_version": RESULT_SCHEMA,
        "plan_id": plan.plan_id,
        "nonce": plan.nonce,
        "status": status,
        "code": code,
        "updated_at": _now(),
        **details,
    }
    _atomic_json(plan.result_path, value)
    return value


def read_result(plan: InstallPlan) -> dict[str, Any] | None:
    if not plan.result_path.is_file():
        return None
    try:
        data = _safe_json(plan.result_path)
    except InstallPlanError:
        return None
    if data.get("schema_version") != RESULT_SCHEMA:
        return None
    return data


def write_helper_process(plan: InstallPlan, identity: ProcessIdentity | None = None) -> None:
    identity = identity or current_process_identity()
    _atomic_json(
        plan.helper_process_path,
        {
            "schema_version": 1,
            "plan_id": plan.plan_id,
            "nonce": plan.nonce,
            "pid": identity.pid,
            "creation_time": identity.creation_time,
            "executable": identity.executable,
        },
    )


def read_launch_plan_from_env() -> InstallPlan | None:
    value = os.environ.get(PLAN_ENV)
    if not value:
        return None
    return load_plan(value)


class ReadyReceiptWriter:
    """Write the new process's page-ready receipt for the updater.

    The page only echoes opaque plan identifiers from bootstrap; the actual
    process identity and runtime state are recorded by the host.
    """

    def __init__(
        self,
        plan: InstallPlan,
        *,
        identity: AppIdentity,
        runtime,
        service,
        service_port: int,
        ready_path: str | Path | None = None,
        verification_context: bool = False,
    ):
        self.plan = plan
        self.identity = identity
        self.runtime = runtime
        self.service = service
        self.service_port = int(service_port)
        self.verification_context = verification_context
        self.ready_path = (
            Path(ready_path)
            if ready_path is not None
            else Path(os.environ.get(READY_ENV, plan.ready_path))
        )
        self._lock = threading.Lock()
        self._written = False

    def public_bootstrap(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan.plan_id,
            "nonce": self.plan.nonce,
            "version": self.plan.target["version"],
            "build_id": self.plan.target["build_id"],
        }

    def confirm(
        self,
        payload: object,
        *,
        page_ready: bool = False,
    ) -> dict[str, Any]:
        if page_ready is not True:
            return {"accepted": False, "code": "READY_PAGE_NOT_CONFIRMED"}
        if not isinstance(payload, dict):
            return {"accepted": False, "code": "READY_PAYLOAD_INVALID"}
        for key in ("plan_id", "nonce", "version", "build_id"):
            if payload.get(key) != self.public_bootstrap()[key]:
                return {"accepted": False, "code": "READY_IDENTITY_MISMATCH"}
        expected = self.plan.target
        if (
            self.identity.app_id != expected["app_id"]
            or self.identity.version != expected["version"]
            or self.identity.build_id != expected["build_id"]
            or self.identity.package_format != expected["package_format"]
            or self.identity.database_revision != expected["database_revision"]
        ):
            return {"accepted": False, "code": "READY_TARGET_IDENTITY_MISMATCH"}
        if not getattr(self.runtime, "prepared", False):
            return {"accepted": False, "code": "READY_RUNTIME_NOT_READY"}
        revision = getattr(self.runtime, "current_revision", None)
        if revision != expected["database_revision"]:
            return {"accepted": False, "code": "READY_MIGRATION_MISMATCH"}
        try:
            data_dir = Path(self.runtime.data_dir).resolve()
            credential_root = Path(self.runtime.credential_root).resolve()
        except Exception:
            return {"accepted": False, "code": "READY_PATHS_UNKNOWN"}
        if data_dir != Path(self.plan.data_dir).resolve():
            return {"accepted": False, "code": "READY_DATA_ROOT_MISMATCH"}
        if credential_root != Path(self.plan.credential_root).resolve():
            return {"accepted": False, "code": "READY_CREDENTIAL_ROOT_MISMATCH"}
        try:
            service_alive = bool(self.service.alive())
        except Exception:
            service_alive = False
        if not service_alive:
            return {"accepted": False, "code": "READY_SERVICE_NOT_READY"}
        try:
            process = current_process_identity()
        except Exception:
            return {"accepted": False, "code": "READY_PROCESS_UNKNOWN"}
        expected_exe = Path(self.plan.new_app_path).resolve()
        if not self.verification_context:
            if Path(process.executable).resolve() != expected_exe:
                return {"accepted": False, "code": "READY_PROCESS_TARGET_MISMATCH"}
        with self._lock:
            if self._written:
                return {"accepted": False, "code": "READY_ALREADY_WRITTEN"}
            value = {
                "schema_version": RECEIPT_SCHEMA,
                "plan_id": self.plan.plan_id,
                "nonce": self.plan.nonce,
                "version": self.identity.version,
                "build_id": self.identity.build_id,
                "app_id": self.identity.app_id,
                "package_format": self.identity.package_format,
                "database_revision": revision,
                "data_dir": str(data_dir),
                "credential_root": str(credential_root),
                "identity": self.identity.as_dict(),
                "pid": process.pid,
                "creation_time": process.creation_time,
                "executable": process.executable,
                "runtime_ready": True,
                "service_ready": True,
                "page_ready": True,
                "service_port": self.service_port,
                "written_at": _now(),
            }
            try:
                _atomic_json(self.ready_path, value)
            except OSError:
                return {"accepted": False, "code": "READY_WRITE_FAILED"}
            self._written = True
        return {"accepted": True, "plan_id": self.plan.plan_id}


class InstallCoordinator:
    """Old-host side of U2: one plan bound to one close request."""

    def __init__(
        self,
        *,
        identity: AppIdentity,
        data_dir: str | Path,
        credential_root: str | Path,
        install_root: str | Path | None = None,
        app_dir: str | Path | None = None,
        helper_command: list[str] | None = None,
        release_config: str | Path | None = None,
        test_only: bool = False,
        new_app_command: list[str] | None = None,
    ):
        self.identity = identity
        self.data_dir = Path(data_dir)
        self.credential_root = Path(credential_root)
        self.install_root = (
            Path(install_root) if install_root is not None else update_paths.install_root()
        )
        self.app_dir = (
            Path(app_dir) if app_dir is not None else update_paths.install_app_dir()
        )
        self.helper_command = list(helper_command or [])
        self.release_config = release_config
        self.test_only = test_only
        self.new_app_command = list(new_app_command or [])
        self._lock = threading.RLock()
        self._plan: InstallPlan | None = None
        self._awaiting_close = False
        self._arm_deadline = 0.0
        self._helper: subprocess.Popen | None = None
        self._state = "idle"
        self._reason: str | None = None
        self._destroyer = None
        self._recovery_checked = False
        self._recovery_reason: str | None = None
        self._recovery_check()

    def set_destroyer(self, destroyer) -> None:
        with self._lock:
            self._destroyer = destroyer

    # -- persistent recovery ---------------------------------------------
    def _recovery_check(self) -> None:
        with self._lock:
            # While this coordinator owns no plan it is an observer of the
            # persistent install state.  Re-scan on every state/prepare call:
            # a helper that was alive when first seen may later have completed
            # successfully, and the same coordinator must recover without a
            # restart.  An active own plan is guarded by the in-memory busy
            # state instead of being reclassified from its own incomplete
            # files.
            if self._plan is None:
                self._recovery_checked = True
                self._recovery_reason = self._scan_persistent_state()
                return
            if self._recovery_checked:
                return
            self._recovery_checked = True
            self._recovery_reason = self._scan_persistent_state()

    @staticmethod
    def _valid_success_receipt(plan: InstallPlan, result: dict[str, Any]) -> bool:
        receipt = result.get("receipt")
        if not isinstance(receipt, dict):
            return False
        target = plan.target
        checks = (
            ("schema_version", RECEIPT_SCHEMA),
            ("plan_id", plan.plan_id),
            ("nonce", plan.nonce),
            ("version", target.get("version")),
            ("build_id", target.get("build_id")),
            ("app_id", target.get("app_id")),
            ("package_format", target.get("package_format")),
            ("database_revision", target.get("database_revision")),
            ("runtime_ready", True),
            ("service_ready", True),
            ("page_ready", True),
        )
        if any(receipt.get(key) != value for key, value in checks):
            return False
        try:
            if Path(str(receipt.get("data_dir"))).resolve() != Path(plan.data_dir).resolve():
                return False
            if Path(str(receipt.get("credential_root"))).resolve() != Path(
                plan.credential_root
            ).resolve():
                return False
        except (OSError, TypeError):
            return False
        return (
            isinstance(receipt.get("pid"), int)
            and not isinstance(receipt.get("pid"), bool)
            and receipt.get("pid") > 0
            and isinstance(receipt.get("creation_time"), int)
            and not isinstance(receipt.get("creation_time"), bool)
            and receipt.get("creation_time") > 0
        )

    def _scan_persistent_state(self) -> str | None:
        root = self.install_root / "install-state"
        if not root.is_dir():
            return None
        for state in sorted(root.iterdir()):
            if not state.is_dir():
                continue
            try:
                plan = load_plan(state / "install-plan.json")
            except InstallPlanError:
                return "INSTALL_RECOVERY_RECORD_INVALID"
            result_path = state / "install-result.json"
            result: dict[str, Any] | None = None
            if result_path.is_file():
                try:
                    result = _safe_json(result_path)
                except InstallPlanError:
                    return "INSTALL_RECOVERY_RECORD_INVALID"
                if (
                    result.get("schema_version") != RESULT_SCHEMA
                    or result.get("plan_id") != plan.plan_id
                    or result.get("nonce") != plan.nonce
                ):
                    return "INSTALL_RECOVERY_RECORD_INVALID"
            helper_path = state / "helper-process.json"
            if helper_path.is_file():
                try:
                    helper_raw = _safe_json(helper_path)
                    helper = identity_from_dict(helper_raw)
                except InstallPlanError:
                    return "INSTALL_RECOVERY_RECORD_INVALID"
                if helper is None:
                    return "INSTALL_RECOVERY_RECORD_INVALID"
                if process_matches(helper):
                    return "INSTALL_HELPER_ALIVE"
            if result is not None and result.get("status") == "success":
                if not self._valid_success_receipt(plan, result):
                    return "INSTALL_RECOVERY_RECEIPT_INVALID"
                # A completed install is a legal terminal state and must not
                # block a future update forever.  Validate against its own
                # historical plan/target, never against the current app.
                continue
            try:
                phases = read_phases_at(state / "phases")
            except InstallPlanError:
                return "INSTALL_PHASE_RECORD_INVALID"
            if result is None:
                return "INSTALL_RESULT_MISSING"
            if result.get("status") == "unknown":
                return "INSTALL_RESULT_UNKNOWN"
            if result.get("status") in ("failed", "revoked"):
                unsafe = {
                    "old_app_backed_up",
                    "new_app_moved",
                    "new_process_started",
                }
                if any(item.get("phase") in unsafe for item in phases):
                    return "INSTALL_RESULT_NEEDS_REVIEW"
                # A definite pre-switch failure/revocation is terminal and
                # does not block a later, separate install.
                continue
            return "INSTALL_RECOVERY_RECORD_INVALID"
        return None

    # -- public state -----------------------------------------------------
    def _busy_locked(self) -> bool:
        self._recovery_check()
        if self._recovery_reason is not None:
            return True
        if self._state in ("pending", "bound", "authorized", "unknown"):
            return True
        if self._helper is not None and self._helper.poll() is None:
            return True
        if self._plan is not None:
            result = read_result(self._plan)
            if result is not None and result.get("status") == "unknown":
                # An unknown result must be checked by the user/maintenance
                # path; never silently start a second plan over it.
                return True
        return False

    def install_available(self) -> bool:
        with self._lock:
            return not self._busy_locked()

    def state(self) -> dict[str, Any]:
        with self._lock:
            self._recovery_check()
            result = read_result(self._plan) if self._plan is not None else None
            state = "needs_review" if self._recovery_reason else self._state
            return {
                "install_state": state,
                "install_plan_id": self._plan.plan_id if self._plan else None,
                "install_result": result,
                "install_reason": self._recovery_reason or self._reason,
                "install_available": not self._busy_locked(),
            }

    # -- close lifecycle --------------------------------------------------
    def prepare_from_manager(self, manager) -> dict[str, Any]:
        with self._lock:
            if self._busy_locked():
                return {
                    "accepted": False,
                    "state": "needs_review" if self._recovery_reason else self._state,
                    "reason": self._recovery_reason or "INSTALL_BUSY",
                }
            try:
                payload = manager.install_payload()
            except Exception as exc:
                self._state = "failed"
                self._reason = getattr(exc, "code", "INSTALL_NOT_READY")
                return {
                    "accepted": False,
                    "state": self._state,
                    "reason": self._reason,
                }
            try:
                plan = build_install_plan(
                    identity=self.identity,
                    manifest=payload["manifest"],
                    metadata_raw=payload["metadata_raw"],
                    staging_dir=payload["staging_dir"],
                    package_zip=payload["package_zip"],
                    data_dir=self.data_dir,
                    credential_root=self.credential_root,
                    install_root=self.install_root,
                    app_dir=self.app_dir,
                    helper_command=self.helper_command or None,
                    release_config=self.release_config,
                    new_app_command=self.new_app_command,
                    test_only=self.test_only,
                )
            except InstallPlanError as exc:
                self._state = "failed"
                self._reason = exc.code
                return {
                    "accepted": False,
                    "state": self._state,
                    "reason": exc.code,
                    "message": exc.message,
                }
            self._plan = plan
            self._state = "pending"
            self._awaiting_close = True
            self._arm_deadline = time.monotonic() + ARM_GRACE_SECONDS
            try:
                self._start_helper()
            except Exception:
                self._state = "failed"
                self._reason = "INSTALL_HELPER_START_FAILED"
                write_result(plan, "failed", "INSTALL_HELPER_START_FAILED")
                return {
                    "accepted": False,
                    "state": self._state,
                    "reason": self._reason,
                }
            return {
                "accepted": True,
                "state": self._state,
                "plan_id": plan.plan_id,
                "target": {
                    "version": plan.target["version"],
                    "build_id": plan.target["build_id"],
                },
            }

    def _start_helper(self) -> None:
        assert self._plan is not None
        command = list(self.helper_command)
        if not command:
            command = [self._plan.helper_path]
        command.extend(["--plan", str(self._plan.plan_path)])
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        self._helper = subprocess.Popen(
            command,
            cwd=str(self._plan.state_dir),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=creationflags,
        )
        _append_phase(self._plan, "helper_started", pid=self._helper.pid)
        try:
            identity = process_identity(self._helper.pid)
            if identity is not None:
                write_helper_process(self._plan, identity)
        except Exception:
            pass

    def bind_close(self, request_id: str, generation: int | None) -> None:
        with self._lock:
            if self._plan is None:
                return
            if self._state == "bound":
                # A newer close cannot inherit an older install authorization.
                try:
                    auth = read_authorization(self._plan)
                except InstallPlanError:
                    auth = {}
                if auth.get("close_request_id") != request_id:
                    self._revoke_locked(request_id, "INSTALL_CLOSE_SUPERSEDED")
                return
            if self._state != "pending":
                return
            if not self._awaiting_close:
                return
            if time.monotonic() > self._arm_deadline:
                self._revoke_locked(None, "INSTALL_CLOSE_NOT_STARTED")
                return
            self._awaiting_close = False
            write_authorization(
                self._plan,
                state="pending",
                close_request_id=request_id,
                close_generation=generation,
            )
            self._state = "bound"
            _append_phase(
                self._plan,
                "close_bound",
                close_request_id=request_id,
                close_generation=generation,
            )

    def finalize_close(self, request_id: str, generation: int | None) -> None:
        with self._lock:
            if self._plan is None or self._state not in ("pending", "bound"):
                return
            auth = None
            try:
                auth = read_authorization(self._plan)
            except InstallPlanError:
                self._revoke_locked(request_id, "INSTALL_AUTH_INVALID")
                return
            if auth.get("close_request_id") != request_id:
                return
            write_authorization(
                self._plan,
                state="authorized",
                close_request_id=request_id,
                close_generation=generation,
            )
            self._state = "authorized"
            _append_phase(
                self._plan,
                "close_finalized",
                close_request_id=request_id,
                close_generation=generation,
            )

    def cancel_close(self, request_id: str | None, reason: str) -> None:
        with self._lock:
            if self._plan is None:
                return
            try:
                auth = read_authorization(self._plan)
            except InstallPlanError:
                auth = {}
            bound = auth.get("close_request_id")
            if request_id is not None and bound not in (None, request_id):
                return
            if self._state == "authorized" and request_id is None:
                return
            self._revoke_locked(request_id, reason)

    def _revoke_locked(self, request_id: str | None, reason: str) -> None:
        if self._plan is None:
            return
        write_authorization(
            self._plan,
            state="revoked",
            close_request_id=request_id,
            close_generation=None,
            reason=reason,
        )
        self._state = "revoked"
        self._reason = reason
        self._awaiting_close = False
        _append_phase(self._plan, "authorization_revoked", reason=reason)
        write_result(self._plan, "revoked", reason)

    def close_failed(self, request_id: str | None, reason: str) -> None:
        self.cancel_close(request_id, reason)

    def shutdown(self) -> None:
        with self._lock:
            if self._state in ("pending", "bound"):
                self._revoke_locked(None, "APP_SHUTDOWN")

    # -- window trigger ---------------------------------------------------
    def request_close(self) -> None:
        destroyer = self._destroyer
        if destroyer is None:
            return
        try:
            destroyer()
        except Exception:
            self.cancel_close(None, "INSTALL_DESTROY_FAILED")
