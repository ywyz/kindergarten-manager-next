"""D3-U U2 small standalone updater.

It is intentionally independent of the application package: it only waits for
the old process, checks the final close authorization, re-verifies the signed
metadata and original ZIP, switches the complete application directory, starts
the new executable with the original data/credential roots, and confirms a
page-ready receipt from the actual new process.  It never kills the old
process, never rolls back a database, and never retries a parallel install.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

import update_github
import update_identity
import update_install
import update_paths
import update_process
from update_fs import (
    PathSafetyError,
    ensure_safe_path,
    ensure_safe_tree,
    has_multiple_hard_links,
)
from update_manifest import (
    ManifestError,
    parse_signed_manifest,
    strict_json_loads,
    verify_package_zip,
)
from update_trust import ReleaseConfigError, load_release_source


def _record(plan: update_install.InstallPlan, phase: str, **details: Any) -> None:
    update_install._append_phase(plan, phase, **details)


def _fail(
    plan: update_install.InstallPlan,
    status: str,
    code: str,
    **details: Any,
) -> int:
    _record(plan, status, code=code, **details)
    update_install.write_result(plan, status, code, **details)
    return 0


def _trusted_release_config_path() -> Path:
    """The product source/key config belongs to the trusted updater itself."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "update_release.json"
    return update_paths.updater_dir() / "update_release.json"


def _check_product_layout(plan: update_install.InstallPlan) -> None:
    """Bind the frozen helper to its own registered/fixed managed root.

    The plan is never trusted on its own.  The helper's actual executable path
    (raw, reparse-checked) must be ``{root}/updater/KindergartenManagerUpdater.exe``
    for a root that is the HKCU-registered install root or a fixed legacy root.
    A copied helper, alias, different root or missing entry is refused.
    """
    if not getattr(sys, "frozen", False):
        raise update_install.InstallPlanError(
            "INSTALL_PRODUCT_LAYOUT", "源码更新器不能使用产品布局"
        )
    helper_exe = update_paths.raw_path(sys.executable)
    if not update_paths.is_safe_existing(helper_exe):
        raise update_install.InstallPlanError(
            "INSTALL_PRODUCT_LAYOUT", "更新器自身路径不安全或不存在"
        )
    try:
        if has_multiple_hard_links(helper_exe):
            raise update_install.InstallPlanError(
                "INSTALL_PRODUCT_LAYOUT", "更新器自身存在硬链接"
            )
    except PathSafetyError as exc:
        raise update_install.InstallPlanError(
            "INSTALL_PRODUCT_LAYOUT", "无法核对更新器自身链接属性"
        ) from exc
    if helper_exe.name != "KindergartenManagerUpdater.exe" or helper_exe.parent.name != "updater":
        raise update_install.InstallPlanError(
            "INSTALL_PRODUCT_LAYOUT", "更新器不是受管 updater 入口"
        )
    own_root = helper_exe.parent.parent
    resolved = update_paths.resolve_install_root(own_root / "app")
    if resolved is None or not update_paths.same_path(resolved, own_root):
        raise update_install.InstallPlanError(
            "INSTALL_PRODUCT_LAYOUT", "更新器自身不在注册或稳定版受管根"
        )
    plan_install = update_paths.raw_path(plan.install_root)
    if not update_paths.same_path(plan_install, own_root):
        raise update_install.InstallPlanError(
            "INSTALL_PRODUCT_LAYOUT", "安装根与更新器自身受管根不一致"
        )
    install, app, helper, staging = update_paths.managed_layout(own_root)
    if not update_paths.same_path(plan.install_app_dir, app):
        raise update_install.InstallPlanError(
            "INSTALL_PRODUCT_LAYOUT", "程序目录不是受管布局的 app 目录"
        )
    if not update_paths.same_path(plan.helper_path, helper):
        raise update_install.InstallPlanError(
            "INSTALL_PRODUCT_LAYOUT", "更新器不是受管布局的固定入口"
        )
    plan_staging = update_paths.raw_path(plan.staging_dir)
    if not update_paths.same_path(plan_staging, staging) and not str(
        plan_staging
    ).lower().startswith(str(staging).lower() + "\\"):
        raise update_install.InstallPlanError(
            "INSTALL_PRODUCT_LAYOUT", "暂存目录不是受管布局的同卷暂存目录"
        )
    if plan.new_app_command:
        raise update_install.InstallPlanError(
            "INSTALL_PRODUCT_LAYOUT", "产品安装计划不接受测试启动命令"
        )
    if not update_paths.same_path(
        plan.new_app_path, app / "KindergartenManager.exe"
    ):
        raise update_install.InstallPlanError(
            "INSTALL_PRODUCT_LAYOUT", "新版主入口不是受管 app 入口"
        )


_INSTALLED_IDENTITY_FIELDS = (
    "app_id",
    "app_name",
    "channel",
    "version",
    "build_id",
    "package_format",
    "platform",
    "arch",
    "python",
    "database_revision",
)


def _read_installed_identity(plan: update_install.InstallPlan) -> dict[str, str]:
    """Read the actual old package identity from its managed program tree."""
    app = Path(plan.install_app_dir)
    try:
        ensure_safe_path(app)
        install_root = getattr(plan, "install_root", "")
        if install_root:
            app.resolve().relative_to(Path(install_root).resolve())
    except (PathSafetyError, OSError, ValueError) as exc:
        raise update_install.InstallPlanError(
            "INSTALL_OLD_IDENTITY_UNSAFE", "旧程序身份路径越出受管安装根"
        ) from exc
    if not app.is_dir():
        raise update_install.InstallPlanError(
            "INSTALL_APP_MISSING", "旧程序目录缺失或不是目录"
        )
    identity_path = app / "_internal" / "build_identity.json"
    try:
        ensure_safe_path(identity_path)
    except PathSafetyError as exc:
        raise update_install.InstallPlanError(
            "INSTALL_OLD_IDENTITY_UNSAFE", "旧程序身份路径包含链接或重解析点"
        ) from exc
    if identity_path.is_symlink() or not identity_path.is_file():
        raise update_install.InstallPlanError(
            "INSTALL_OLD_IDENTITY_INVALID", "旧程序 build_identity.json 缺失或不是普通文件"
        )
    try:
        if has_multiple_hard_links(identity_path):
            raise update_install.InstallPlanError(
                "INSTALL_OLD_IDENTITY_UNSAFE", "旧程序身份文件存在硬链接"
            )
    except PathSafetyError as exc:
        raise update_install.InstallPlanError(
            "INSTALL_OLD_IDENTITY_UNSAFE", "无法核对旧程序身份文件链接"
        ) from exc
    try:
        data = strict_json_loads(identity_path.read_bytes(), package=True)
    except (OSError, ManifestError) as exc:
        raise update_install.InstallPlanError(
            "INSTALL_OLD_IDENTITY_INVALID", "旧程序 build_identity.json 无法读取"
        ) from exc
    if (
        not isinstance(data, dict)
        or set(data) != set(_INSTALLED_IDENTITY_FIELDS)
        or not all(isinstance(data.get(key), str) and data.get(key) for key in _INSTALLED_IDENTITY_FIELDS)
    ):
        raise update_install.InstallPlanError(
            "INSTALL_OLD_IDENTITY_INVALID", "旧程序 build_identity.json 字段不合法"
        )
    actual = {key: data[key] for key in _INSTALLED_IDENTITY_FIELDS}
    if (
        actual["app_id"] != "kindergarten-manager-next"
        or actual["app_name"] != "KindergartenManager"
        or actual["package_format"] != "pyinstaller-onedir-zip-v1"
        or actual["platform"] != "windows"
        or actual["arch"] != "x64"
    ):
        raise update_install.InstallPlanError(
            "INSTALL_OLD_IDENTITY_INVALID", "旧程序固定身份字段不匹配"
        )
    if actual["channel"] not in ("stable", "preview"):
        raise update_install.InstallPlanError(
            "INSTALL_OLD_IDENTITY_INVALID", "旧程序渠道不合法"
        )
    try:
        if (
            update_identity.is_preview_version(actual["version"])
            != (actual["channel"] == "preview")
        ):
            raise ValueError
        update_identity.version_key(actual["version"])
        if str(uuid.UUID(actual["build_id"])) != actual["build_id"].lower():
            raise ValueError
    except (ValueError, AttributeError):
        raise update_install.InstallPlanError(
            "INSTALL_OLD_IDENTITY_INVALID", "旧程序版本或 build ID 不合法"
        ) from None
    current = plan.current
    if not isinstance(current, dict):
        raise update_install.InstallPlanError(
            "INSTALL_CURRENT_IDENTITY_INVALID", "安装计划的当前身份不合法"
        )
    for key in _INSTALLED_IDENTITY_FIELDS:
        if current.get(key) != actual[key]:
            raise update_install.InstallPlanError(
                "INSTALL_CURRENT_IDENTITY_MISMATCH",
                f"安装计划当前身份与旧程序实际身份不一致：{key}",
            )
    return actual


def _load_manifest(
    plan: update_install.InstallPlan,
    *,
    verification_context: bool,
):
    config = (
        plan.release_config
        if verification_context
        else str(_trusted_release_config_path())
    )
    if not config:
        raise update_install.InstallPlanError(
            "INSTALL_SOURCE_MISSING", "更新器缺少发行信任配置"
        )
    source = load_release_source(config)
    if source is None or not source.configured:
        raise update_install.InstallPlanError(
            "INSTALL_SOURCE_UNCONFIGURED", "发行信任配置未配置"
        )
    target_channel = plan.target.get("channel")
    if target_channel not in ("stable", "preview"):
        raise update_install.InstallPlanError(
            "INSTALL_METADATA_INVALID", "安装目标渠道不合法"
        )
    if source.provider == "github":
        # Only the fixed GitHub trust path may select stable/preview in the
        # updater config; the signed manifest is still checked below.
        source = replace(source, channel=target_channel)
    elif target_channel != source.channel:
        raise update_install.InstallPlanError(
            "INSTALL_METADATA_MISMATCH", "固定更新源只接受其配置渠道"
        )
    actual = _read_installed_identity(plan)
    raw = strict_json_loads(Path(plan.metadata_path).read_bytes(), package=True)
    if not isinstance(raw, dict) or set(raw) != {"raw"} or not isinstance(
        raw.get("raw"), str
    ):
        raise update_install.InstallPlanError(
            "INSTALL_METADATA_INVALID", "保存的签名元数据不合法"
        )
    metadata = raw["raw"].encode("utf-8")
    manifest = parse_signed_manifest(
        metadata,
        source,
        actual["version"],
        actual["database_revision"],
    )
    if source.provider == "github":
        # The embedded updater config is the authority; the selected tag is
        # derived from the signature-verified manifest version, never from a
        # mutable plan field or the data directory.
        update_github.validate_github_manifest_for_version(
            manifest, str(plan.target.get("version", ""))
        )
    expected = plan.target
    for key, value in (
        ("app_id", manifest.app_id),
        ("channel", manifest.channel),
        ("version", manifest.version),
        ("build_id", manifest.build_id),
        ("platform", manifest.platform),
        ("arch", manifest.arch),
        ("package_format", manifest.package_format),
        ("package_root", manifest.package_root),
        ("executable", manifest.executable),
        ("package_size", manifest.package_size),
        ("package_sha256", manifest.package_sha256),
        ("database_revision", manifest.database_revision),
    ):
        if expected.get(key) != value:
            raise update_install.InstallPlanError(
                "INSTALL_METADATA_MISMATCH", f"签名元数据与安装计划不一致：{key}"
            )
    return manifest


def _verify_saved_package(plan: update_install.InstallPlan, manifest):
    """Re-verify the saved ZIP against the signed manifest and package list."""
    archive = Path(plan.package_zip)
    if archive.stat().st_size != manifest.package_size:
        raise update_install.InstallPlanError(
            "INSTALL_PACKAGE_MISMATCH", "保存的完整包大小与签名元数据不一致"
        )
    import hashlib

    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != manifest.package_sha256:
        raise update_install.InstallPlanError(
            "INSTALL_PACKAGE_MISMATCH", "保存的完整包 SHA-256 与签名元数据不一致"
        )
    verify_dir = Path(plan.state_dir) / "verified"
    if verify_dir.exists():
        raise update_install.InstallPlanError(
            "INSTALL_VERIFY_DIR_EXISTS", "校验目录已存在"
        )
    ensure_safe_path(verify_dir)
    verified = verify_package_zip(archive, manifest, verify_dir)
    ensure_safe_tree(verified.root)
    return verified


def _wait_for_authorization(
    plan: update_install.InstallPlan,
    *,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    old = update_process.identity_from_dict(plan.old_process)
    if old is None:
        raise update_install.InstallPlanError(
            "INSTALL_OLD_PROCESS_INVALID", "旧进程身份不合法"
        )
    while time.monotonic() < deadline:
        try:
            auth = update_install.read_authorization(plan)
        except update_install.InstallPlanError:
            auth = {"state": "pending", "close_request_id": None}
        state = auth.get("state")
        if state == "revoked":
            return auth
        if state == "authorized":
            return auth
        if not update_process.process_matches(old):
            # The old process exited before the close was finally allowed.
            # Give the host a short moment to publish its final authorization,
            # but never treat an unexplained exit as permission to install.
            grace = time.monotonic() + 1.0
            while time.monotonic() < grace:
                auth = update_install.read_authorization(plan)
                if auth.get("state") == "authorized":
                    return auth
                if auth.get("state") == "revoked":
                    return auth
                time.sleep(0.05)
            return {"state": "missing"}
        time.sleep(0.05)
    return {"state": "timeout"}


def _authorization_matches(
    plan: update_install.InstallPlan,
    expected: dict[str, Any],
) -> tuple[bool, dict[str, Any] | None]:
    try:
        current = update_install.read_authorization(plan)
    except update_install.InstallPlanError:
        return False, None
    keys = (
        "state",
        "plan_id",
        "nonce",
        "close_request_id",
        "close_generation",
    )
    if any(current.get(key) != expected.get(key) for key in keys):
        return False, current
    return current.get("state") == "authorized", current


def _require_same_authorization(
    plan: update_install.InstallPlan,
    expected: dict[str, Any],
) -> bool:
    valid, current = _authorization_matches(plan, expected)
    if valid:
        return True
    if current is not None and current.get("state") == "revoked":
        _fail(
            plan,
            "revoked",
            "INSTALL_AUTHORIZATION_WITHDRAWN",
            reason=current.get("reason"),
        )
    else:
        _fail(
            plan,
            "failed",
            "INSTALL_AUTHORIZATION_CHANGED",
        )
    return False


def _rename_with_retry(source: Path, target: Path, timeout: float = 2.0) -> None:
    """Retry a directory rename through a short Windows sharing transient.

    The final failure is still a refusal; this only prevents a scanner or a
    just-closed handle from turning a valid switch into a false failure.
    """
    deadline = time.monotonic() + timeout
    while True:
        try:
            source.rename(target)
            return
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


def _check_layout(
    plan: update_install.InstallPlan,
    *,
    verification_context: bool,
) -> None:
    data = Path(plan.data_dir)
    credential = Path(plan.credential_root)
    install = Path(plan.install_root)
    staging = Path(plan.staging_dir)
    app = Path(plan.install_app_dir)
    backup = Path(plan.backup_dir)
    state = Path(plan.state_dir)
    archive = Path(plan.package_zip)
    metadata = Path(plan.metadata_path)
    helper = Path(plan.helper_path)
    for label, path in (
        ("数据根", data),
        ("凭据根", credential),
        ("程序根", install),
        ("暂存", staging),
        ("备份", backup),
        ("安装状态", state),
        ("原 ZIP", archive),
        ("签名元数据", metadata),
        ("更新器", helper),
    ):
        try:
            ensure_safe_path(path)
        except PathSafetyError as exc:
            raise update_install.InstallPlanError(
                "INSTALL_PATH_UNSAFE", f"{label}路径不安全"
            ) from exc
    if not update_install._same_volume(staging, install):
        raise update_install.InstallPlanError(
            "INSTALL_VOLUME_MISMATCH", "暂存与程序目录不在同一卷"
        )
    update_install._assert_separate(
        [("暂存目录", staging), ("程序目录", install), ("程序", app)],
        data=data,
        credential=credential,
    )
    try:
        app.relative_to(install)
        backup.relative_to(install)
        state.relative_to(install)
        archive.relative_to(staging)
        metadata.relative_to(state)
    except ValueError:
        raise update_install.InstallPlanError(
            "INSTALL_PATH_OUTSIDE", "安装路径越出受管根"
        ) from None
    if update_install._overlaps(helper, app):
        raise update_install.InstallPlanError(
            "INSTALL_HELPER_IN_APP", "更新器不得位于待切换程序目录"
        )
    if not verification_context:
        _check_product_layout(plan)


def _check_released(plan: update_install.InstallPlan) -> None:
    data = Path(plan.data_dir)
    db = data / "kindergarten.db"
    lock = data / ".app-runtime.lock"
    deadline = time.monotonic() + 3.0
    while True:
        lock_busy = lock.exists() and not update_process.probe_file_not_occupied(lock)
        db_busy = db.exists() and not update_process.probe_file_not_occupied(db)
        if not lock_busy and not db_busy:
            return
        if time.monotonic() >= deadline:
            if lock_busy:
                raise update_install.InstallPlanError(
                    "INSTALL_DATA_LOCK_BUSY", "数据根运行锁仍被占用"
                )
            raise update_install.InstallPlanError(
                "INSTALL_DATABASE_BUSY", "数据库句柄尚未释放"
            )
        time.sleep(0.05)


def _new_app_command(
    plan: update_install.InstallPlan,
    *,
    verification_context: bool,
) -> tuple[list[str], dict[str, str]]:
    env = dict(os.environ)
    env[update_install.PLAN_ENV] = str(plan.plan_path)
    env[update_install.READY_ENV] = str(plan.ready_path)
    env["APP_DISABLE_DOTENV"] = "1"
    if verification_context:
        env["KGM_UPDATE_VERIFICATION_CONTEXT"] = "1"
    else:
        # A product helper must never inherit a source-test mode from its
        # parent environment; the new app performs the target-exe check.
        env.pop("KGM_UPDATE_VERIFICATION_CONTEXT", None)
    if plan.new_app_command:
        if not verification_context:
            raise update_install.InstallPlanError(
                "INSTALL_PRODUCT_LAYOUT", "产品安装计划不接受测试启动命令"
            )
        return list(plan.new_app_command), env
    return (
        [
            plan.new_app_path,
            "--data",
            plan.data_dir,
            "--credential-root",
            plan.credential_root,
        ],
        env,
    )


def _capture_new_identity(process: subprocess.Popen, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        identity = update_process.process_identity(process.pid)
        if identity is not None:
            return identity
        if process.poll() is not None:
            return None
        time.sleep(0.02)
    return None


def _wait_for_receipt(
    plan: update_install.InstallPlan,
    process: subprocess.Popen,
    identity,
    timeout: float,
    *,
    allow_launcher: bool = False,
    verification_context: bool = False,
) -> tuple[str, str | None, dict[str, Any] | None]:
    ready = Path(plan.ready_path)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ready.is_file():
            if identity is None and not allow_launcher:
                return "unknown", "INSTALL_PROCESS_UNVERIFIED", None
            try:
                data = strict_json_loads(ready.read_bytes(), package=True)
            except (OSError, ManifestError):
                return "unknown", "INSTALL_RECEIPT_INVALID", None
            if not isinstance(data, dict):
                return "unknown", "INSTALL_RECEIPT_INVALID", None
            expected = plan.target
            checks = (
                ("schema_version", update_install.RECEIPT_SCHEMA),
                ("plan_id", plan.plan_id),
                ("nonce", plan.nonce),
                ("version", expected["version"]),
                ("build_id", expected["build_id"]),
                ("app_id", expected["app_id"]),
                ("package_format", expected["package_format"]),
                ("database_revision", expected["database_revision"]),
                ("data_dir", plan.data_dir),
                ("credential_root", plan.credential_root),
                ("runtime_ready", True),
                ("service_ready", True),
                ("page_ready", True),
            )
            for key, value in checks:
                if data.get(key) != value:
                    return "unknown", f"INSTALL_RECEIPT_{key.upper()}", data
            actual_pid = data.get("pid")
            if not isinstance(actual_pid, int) or isinstance(actual_pid, bool):
                return "unknown", "INSTALL_RECEIPT_PID_MISMATCH", data
            if actual_pid != process.pid:
                if not allow_launcher:
                    return "unknown", "INSTALL_RECEIPT_PID_MISMATCH", data
                # Dedicated source-test launcher only: verify the actual child
                # process identity from the receipt, not the launcher PID.
                identity = update_process.process_identity(actual_pid)
                if identity is None:
                    return "unknown", "INSTALL_RECEIPT_PID_MISMATCH", data
            if identity is not None:
                if data.get("creation_time") != identity.creation_time:
                    return "unknown", "INSTALL_RECEIPT_PROCESS_MISMATCH", data
                if data.get("executable") and identity.executable:
                    if os.path.normcase(os.path.abspath(str(data["executable"]))) != os.path.normcase(
                        os.path.abspath(identity.executable)
                    ):
                        return "unknown", "INSTALL_RECEIPT_EXE_MISMATCH", data
            if not verification_context:
                expected_exe = os.path.normcase(
                    os.path.abspath(str(plan.new_app_path))
                )
                if os.path.normcase(os.path.abspath(str(data.get("executable")))) != expected_exe:
                    return "unknown", "INSTALL_RECEIPT_TARGET_EXE_MISMATCH", data
            if not allow_launcher and process.poll() is not None:
                return "unknown", "INSTALL_PROCESS_EXITED", data
            return "success", None, data
        if process.poll() is not None:
            return "unknown", "INSTALL_PROCESS_EXITED", None
        time.sleep(0.1)
    return "unknown", "INSTALL_READY_TIMEOUT", None


def run(
    plan_path: str | Path,
    *,
    auth_timeout: float = update_install.DEFAULT_AUTH_TIMEOUT,
    old_timeout: float = update_install.DEFAULT_OLD_EXIT_TIMEOUT,
    ready_timeout: float = update_install.DEFAULT_READY_TIMEOUT,
    allow_launcher: bool = False,
    fail_after_old_move: bool = False,
    verification_context: bool = False,
    test_raise_after_launch: bool = False,
) -> int:
    plan = update_install.load_plan(plan_path)
    lock = update_process.ExclusiveFileLock(Path(plan.install_root) / ".update-install.lock")
    try:
        lock.acquire()
    except update_process.InstallLockError as exc:
        # The caller can inspect the plan result; never touch the program.
        update_install.write_result(plan, "failed", "INSTALL_LOCK_BUSY", message=str(exc))
        return 2
    try:
        try:
            update_install.write_helper_process(plan)
        except Exception:
            pass
        _record(plan, "helper_started", pid=os.getpid())
        try:
            _check_layout(plan, verification_context=verification_context)
        except update_install.InstallPlanError as exc:
            return _fail(plan, "failed", exc.code)
        auth = _wait_for_authorization(plan, timeout=auth_timeout)
        if auth.get("state") == "revoked":
            return _fail(plan, "revoked", "INSTALL_AUTHORIZATION_REVOKED", reason=auth.get("reason"))
        if auth.get("state") != "authorized":
            return _fail(
                plan,
                "failed",
                "INSTALL_AUTHORIZATION_MISSING",
                reason=auth.get("state"),
            )
        authorized = dict(auth)
        _record(
            plan,
            "authorized",
            close_request_id=auth.get("close_request_id"),
            close_generation=auth.get("close_generation"),
        )
        old = update_process.identity_from_dict(plan.old_process)
        assert old is not None
        if not update_process.wait_for_process_exit(old, old_timeout):
            return _fail(plan, "failed", "INSTALL_OLD_PROCESS_TIMEOUT")
        _record(plan, "old_process_exited")
        if not _require_same_authorization(plan, authorized):
            return 0
        try:
            _check_released(plan)
        except update_install.InstallPlanError as exc:
            return _fail(plan, "failed", exc.code)
        _record(plan, "data_released")
        try:
            manifest = _load_manifest(
                plan, verification_context=verification_context
            )
        except (update_install.InstallPlanError, ReleaseConfigError, ManifestError) as exc:
            code = getattr(exc, "code", "INSTALL_METADATA_INVALID")
            return _fail(plan, "failed", code)
        try:
            verified = _verify_saved_package(plan, manifest)
        except (
            OSError,
            PathSafetyError,
            ManifestError,
            update_install.InstallPlanError,
        ) as exc:
            return _fail(
                plan,
                "failed",
                getattr(exc, "code", "INSTALL_PACKAGE_INVALID"),
            )
        _record(plan, "package_reverified")
        if not _require_same_authorization(plan, authorized):
            return 0
        app = Path(plan.install_app_dir)
        backup = Path(plan.backup_dir)
        try:
            ensure_safe_path(app)
            ensure_safe_path(backup)
            if backup.exists():
                return _fail(plan, "failed", "INSTALL_BACKUP_EXISTS")
            if not app.is_dir():
                return _fail(plan, "failed", "INSTALL_APP_MISSING")
            backup.parent.mkdir(parents=True, exist_ok=True)
            _rename_with_retry(app, backup)
        except (OSError, PathSafetyError):
            return _fail(plan, "failed", "INSTALL_SWITCH_FAILED", step="old")
        _record(plan, "old_app_backed_up", backup=str(backup))
        if fail_after_old_move:
            return _fail(plan, "failed", "INSTALL_SWITCH_INTERRUPTED", step="new")
        try:
            _rename_with_retry(verified.root, app)
        except OSError:
            # Nothing was started; put the unchanged old directory back.  The
            # backup directory is retained as the failure record if this
            # restoration itself cannot complete.
            try:
                _rename_with_retry(backup, app)
            except OSError:
                return _fail(plan, "unknown", "INSTALL_SWITCH_UNKNOWN", step="new")
            return _fail(plan, "failed", "INSTALL_SWITCH_FAILED", step="new")
        _record(plan, "new_app_moved")
        if test_raise_after_launch:
            raise OSError("controlled post-launch helper failure")
        command, env = _new_app_command(
            plan, verification_context=verification_context
        )
        try:
            creationflags = 0
            if os.name == "nt":
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
            process = subprocess.Popen(
                command,
                cwd=str(app),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                creationflags=creationflags,
            )
        except OSError:
            return _fail(plan, "unknown", "INSTALL_NEW_START_FAILED", step="start")
        _record(plan, "new_process_started", pid=process.pid)
        identity = _capture_new_identity(process)
        status, code, receipt = _wait_for_receipt(
            plan,
            process,
            identity,
            ready_timeout,
            allow_launcher=allow_launcher,
            verification_context=verification_context,
        )
        if status == "success":
            actual_pid = receipt.get("pid") if isinstance(receipt, dict) else process.pid
            update_install.write_result(
                plan,
                "success",
                None,
                pid=actual_pid,
                creation_time=(
                    receipt.get("creation_time")
                    if isinstance(receipt, dict)
                    else (identity.creation_time if identity else None)
                ),
                receipt=receipt,
            )
            _record(plan, "success", pid=actual_pid)
            return 0
        update_install.write_result(
            plan,
            "unknown",
            code,
            pid=process.pid,
            process_alive=process.poll() is None,
        )
        _record(plan, "unknown", code=code)
        return 0
    finally:
        lock.release()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="KindergartenManager independent updater")
    parser.add_argument("--plan", required=True, help="host-generated install plan")
    parser.add_argument("--auth-timeout", type=float, default=update_install.DEFAULT_AUTH_TIMEOUT)
    parser.add_argument("--old-timeout", type=float, default=update_install.DEFAULT_OLD_EXIT_TIMEOUT)
    parser.add_argument("--ready-timeout", type=float, default=update_install.DEFAULT_READY_TIMEOUT)
    parser.add_argument(
        "--allow-launcher",
        action="store_true",
        help="source-test only: verify the receipt child identity behind the venv launcher",
    )
    parser.add_argument(
        "--fail-after-old-move",
        action="store_true",
        help="source-test only: inject an interrupted directory switch before starting new",
    )
    parser.add_argument(
        "--verification-context",
        action="store_true",
        help="source-test only: explicit isolated release/launch context",
    )
    parser.add_argument(
        "--test-raise-after-launch",
        action="store_true",
        help="source-test only: forced unhandled helper exception for result classification",
    )
    args = parser.parse_args(argv)
    if getattr(sys, "frozen", False) and (
        args.allow_launcher
        or args.fail_after_old_move
        or args.verification_context
        or args.test_raise_after_launch
    ):
        if sys.stderr is not None:
            print("frozen updater refuses verification-only arguments", file=sys.stderr)
        return 2
    try:
        return run(
            args.plan,
            auth_timeout=args.auth_timeout,
            old_timeout=args.old_timeout,
            ready_timeout=args.ready_timeout,
            allow_launcher=args.allow_launcher,
            fail_after_old_move=args.fail_after_old_move,
            verification_context=args.verification_context,
            test_raise_after_launch=args.test_raise_after_launch,
        )
    except Exception as exc:  # noqa: BLE001 - the updater must leave a result
        # An unhandled helper exception leaves the phase history ambiguous.
        # Never interpret a failed/corrupt phase read as proof that no new
        # process started: keep the damaged records and write unknown.
        try:
            plan = update_install.load_plan(args.plan)
            update_install.write_result(
                plan,
                "unknown",
                "INSTALL_HELPER_EXCEPTION",
                message=type(exc).__name__,
            )
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
