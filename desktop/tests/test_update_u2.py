"""D3-U U2 install handoff tests.

The tests use real independent processes, a real LocalRuntime/SQLite database
and the real D1 FastAPI service in the synthetic new-process fixture.  They
never touch the real ``KGNext-G17`` roots, real credentials, real AI or a
frozen package.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
import zipfile
from pathlib import Path

import pytest
from alembic import command
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import update_helper
import update_install
import update_process
from update_process import ProcessIdentity
from app.local.migrate import alembic_config
from app.local.runtime import LocalRuntime
from update_identity import AppIdentity
from update_manifest import canonical_json, parse_signed_manifest
from update_trust import ReleaseSource

DESKTOP = Path(__file__).resolve().parents[1]
BACKEND = DESKTOP.parent / "backend"
OLD_FIXTURE = DESKTOP / "tests" / "update_old_app_fixture.py"
NEW_FIXTURE = DESKTOP / "tests" / "update_new_app_fixture.py"
HELPER = DESKTOP / "update_helper.py"
OLD_REV = "20261017_0004_local"
HEAD_REV = "20261025_0006_local_game_observations"


def _identity(revision: str = HEAD_REV) -> AppIdentity:
    return AppIdentity(
        app_id="kindergarten-manager-next",
        app_name="KindergartenManager",
        channel="stable",
        version="0.1.0",
        build_id=str(uuid.uuid4()),
        package_format="pyinstaller-onedir-zip-v1",
        platform="windows",
        arch="x64",
        python="3.14.7",
        database_revision=revision,
    )


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_package(
    root: Path,
    *,
    target_revision: str,
    target_version: str = "0.2.0",
    tag: bytes = b"new",
) -> tuple[Path, bytes, Ed25519PrivateKey, str]:
    build_id = str(uuid.uuid4())
    package_root = "KindergartenManager"
    files = {
        "KindergartenManager.exe": b"MZ " + tag,
        "_internal/frontend/d1.html": b"<!doctype html><html><body>new app</body></html>",
        "_internal/migrations_local/env.py": b"# synthetic migration\n",
        "_internal/app/assets/word_templates/daily_plan.docx": b"PK synthetic template",
    }
    files["_internal/build_identity.json"] = json.dumps(
        {
            "app_id": "kindergarten-manager-next",
            "app_name": "KindergartenManager",
            "channel": "stable",
            "version": target_version,
            "build_id": build_id,
            "package_format": "pyinstaller-onedir-zip-v1",
            "platform": "windows",
            "arch": "x64",
            "python": "3.14.7",
            "database_revision": target_revision,
        }
    ).encode("utf-8")
    entries = [
        {"path": name, "size": len(data), "sha256": _sha(data)}
        for name, data in sorted(files.items())
    ]
    files["_internal/package_manifest.json"] = json.dumps(
        {
            "schema_version": 1,
            "app_id": "kindergarten-manager-next",
            "app_name": package_root,
            "channel": "stable",
            "version": target_version,
            "build_id": build_id,
            "package_format": "pyinstaller-onedir-zip-v1",
            "platform": "windows",
            "arch": "x64",
            "database_revision": target_revision,
            "files": entries,
        },
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")
    archive = root / "package.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in sorted(files.items()):
            zf.writestr(f"{package_root}/{name}", data)
    raw = archive.read_bytes()
    key = Ed25519PrivateKey.generate()
    payload = {
        "app_id": "kindergarten-manager-next",
        "channel": "stable",
        "version": target_version,
        "build_id": build_id,
        "platform": "windows",
        "arch": "x64",
        "package_format": "pyinstaller-onedir-zip-v1",
        "package_root": package_root,
        "executable": "KindergartenManager.exe",
        "package_url": "/releases/package.zip",
        "package_size": len(raw),
        "package_sha256": _sha(raw),
        "database_revision": target_revision,
        "supported_source_revisions": [HEAD_REV, OLD_REV],
        "release_notes": "U2 合成更新",
        "published_at": "2026-10-24T00:00:00Z",
    }
    signature = key.sign(canonical_json(payload))
    metadata = json.dumps(
        {
            "schema_version": 1,
            "key_id": "test-key",
            "payload": payload,
            "signature": base64.b64encode(signature).decode("ascii"),
        },
        ensure_ascii=False,
    ).encode("utf-8")
    public = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    config = root / "release.json"
    config.write_text(
        json.dumps(
            {
                "origin": "https://updates.example.test",
                "metadata_path": "/stable/windows-x64/manifest.json",
                "channel": "stable",
                "public_keys": {"test-key": base64.b64encode(public).decode("ascii")},
            }
        ),
        encoding="utf-8",
    )
    return archive, metadata, key, build_id


def _source(config: Path) -> ReleaseSource:
    return ReleaseSource(
        origin="https://updates.example.test",
        metadata_path="/stable/windows-x64/manifest.json",
        public_keys={
            "test-key": base64.b64decode(
                json.loads(config.read_text(encoding="utf-8"))["public_keys"]["test-key"]
            )
        },
    )


def _make_current_db(data: Path, cred: Path, revision: str = HEAD_REV) -> None:
    data.mkdir(parents=True, exist_ok=True)
    db = data / "kindergarten.db"
    if revision == HEAD_REV:
        runtime = LocalRuntime(data, credential_root=cred)
        runtime.prepare()
        runtime.dispose()
        return
    command.upgrade(alembic_config(db), revision)


def _start_old(data: Path, cred: Path, ready: Path, stop: Path, *, db_only: bool = False):
    args = [
        sys.executable,
        str(OLD_FIXTURE),
        "--data",
        str(data),
        "--credential-root",
        str(cred),
        "--ready",
        str(ready),
        "--stop",
        str(stop),
    ]
    if db_only:
        args.append("--db-only")
    env = dict(os.environ)
    env["APP_DISABLE_DOTENV"] = "1"
    return subprocess.Popen(
        args,
        cwd=str(BACKEND),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_ready(path: Path, timeout: float = 20.0) -> dict:
    """Wait for a complete, parseable ready record, not just a file."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            value = None
        if (
            isinstance(value, dict)
            and isinstance(value.get("pid"), int)
            and not isinstance(value.get("pid"), bool)
            and value.get("pid", 0) > 0
            and isinstance(value.get("revision"), str)
            and value.get("revision")
        ):
            return value
        time.sleep(0.02)
    raise AssertionError(f"timeout waiting for complete ready record: {path}")


def _wait_process_exit(process: subprocess.Popen, timeout: float = 10.0) -> None:
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _plan(
    root: Path,
    *,
    target_revision: str,
    old_revision: str,
    target_version: str = "0.2.0",
):
    staging = root / "updates" / "staging" / "download"
    staging.mkdir(parents=True, exist_ok=True)
    archive, metadata, _key, _build = _make_package(
        staging, target_revision=target_revision, target_version=target_version
    )
    config = staging / "release.json"
    source = _source(config)
    current = _identity(old_revision)
    manifest = parse_signed_manifest(
        metadata, source, current.version, current.database_revision
    )
    data = root / "data"
    cred = root / "credentials"
    cred.mkdir(parents=True, exist_ok=True)
    old_app = root / "program" / "app"
    old_app.mkdir(parents=True, exist_ok=True)
    (old_app / "old-marker.txt").write_text("old", encoding="utf-8")
    (old_app / "KindergartenManager.exe").write_bytes(b"old exe")
    plan = update_install.build_install_plan(
        identity=current,
        manifest=manifest,
        metadata_raw=metadata,
        staging_dir=staging,
        package_zip=archive,
        data_dir=data,
        credential_root=cred,
        install_root=root / "program",
        app_dir=old_app,
        helper_command=[sys.executable, str(HELPER)],
        release_config=config,
        old_process=update_process.current_process_identity(),
        new_app_command=[
            sys.executable,
            str(NEW_FIXTURE),
            "--data",
            str(data),
            "--credential-root",
            str(cred),
            "--stop",
            str(root / "new-stop"),
        ],
        test_only=True,
    )
    return plan, data, cred, old_app


def _start_helper(
    plan: update_install.InstallPlan,
    *extra: str,
    verification_context: bool = True,
):
    env = dict(os.environ)
    env["APP_DISABLE_DOTENV"] = "1"
    command = [
        sys.executable,
        str(HELPER),
        "--plan",
        str(plan.plan_path),
        *extra,
    ]
    if verification_context:
        command.append("--verification-context")
    return subprocess.Popen(
        command,
        cwd=str(DESKTOP),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _result(plan: update_install.InstallPlan, timeout: float = 30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = update_install.read_result(plan)
        if value is not None:
            return value
        time.sleep(0.05)
    raise AssertionError("timeout waiting for install result")


def _stop_new(plan: update_install.InstallPlan, result: dict) -> None:
    command = list(plan.new_app_command)
    stop = Path(command[command.index("--stop") + 1]) if "--stop" in command else (
        Path(plan.install_root) / "new-stop"
    )
    stop.write_text("stop", encoding="utf-8")
    pid = result.get("pid")
    if isinstance(pid, int) and pid > 0:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if update_process.process_identity(pid) is None:
                return
            time.sleep(0.05)


def test_plan_rejects_program_data_overlap(tmp_path):
    root = tmp_path
    staging = root / "staging"
    staging.mkdir()
    archive, metadata, _key, _build = _make_package(
        staging, target_revision=HEAD_REV
    )
    config = staging / "release.json"
    source = _source(config)
    current = _identity(HEAD_REV)
    manifest = parse_signed_manifest(
        metadata, source, current.version, current.database_revision
    )
    data = root / "data"
    data.mkdir()
    cred = root / "credentials"
    cred.mkdir()
    with pytest.raises(update_install.InstallPlanError):
        update_install.build_install_plan(
            identity=current,
            manifest=manifest,
            metadata_raw=metadata,
            staging_dir=staging,
            package_zip=archive,
            data_dir=data,
            credential_root=cred,
            install_root=data,
            app_dir=data / "app",
            test_only=True,
        )


def test_install_lock_is_exclusive(tmp_path):
    lock_path = tmp_path / ".update-install.lock"
    first = update_process.ExclusiveFileLock(lock_path)
    second = update_process.ExclusiveFileLock(lock_path)
    first.acquire()
    try:
        with pytest.raises(update_process.InstallLockError):
            second.acquire()
    finally:
        first.release()
    second.acquire()
    second.release()


def test_helper_revocations_do_not_touch_program(tmp_path):
    plan, _data, _cred, old_app = _plan(
        tmp_path, target_revision=HEAD_REV, old_revision=HEAD_REV
    )
    # The plan's old process is the test process (still alive); revocation must
    # win before any wait/switch.
    update_install.write_authorization(
        plan,
        state="revoked",
        close_request_id="close-1",
        close_generation=1,
    )
    process = _start_helper(plan, "--auth-timeout", "1")
    try:
        process.wait(timeout=10)
    finally:
        if process.poll() is None:
            process.terminate()
    result = _result(plan, timeout=5)
    assert result["status"] == "revoked"
    assert (old_app / "old-marker.txt").read_text(encoding="utf-8") == "old"
    assert not (old_app / "KindergartenManager.exe").read_bytes().startswith(b"MZ new")


def test_revocation_after_authorized_blocks_real_switch(tmp_path):
    plan, data, _cred, old_app = _plan(
        tmp_path, target_revision=HEAD_REV, old_revision=HEAD_REV
    )
    _make_current_db(data, Path(plan.credential_root), HEAD_REV)
    ready = tmp_path / "old-ready"
    stop = tmp_path / "old-stop"
    old = _start_old(data, Path(plan.credential_root), ready, stop)
    try:
        old_pid = _wait_ready(ready)["pid"]
        plan = _replace_old_process(plan, old_pid)
        update_install.write_authorization(
            plan,
            state="authorized",
            close_request_id="close-revoke-late",
            close_generation=1,
        )
        helper = _start_helper(plan, "--old-timeout", "20")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if any(
                item.get("phase") == "authorized"
                for item in update_install.read_phases(plan)
            ):
                break
            time.sleep(0.02)
        else:
            raise AssertionError("helper did not reach authorized stage")
        # The host's destroy failed / close was revoked after the helper had
        # already observed authorized; the switch must still be refused.
        update_install.write_authorization(
            plan,
            state="revoked",
            close_request_id="close-revoke-late",
            close_generation=1,
            reason="destroy_failed",
        )
        stop.write_text("stop", encoding="utf-8")
        helper.wait(timeout=30)
        result = _result(plan, timeout=5)
        assert result["status"] == "revoked"
        assert result["code"] == "INSTALL_AUTHORIZATION_WITHDRAWN"
        assert (old_app / "old-marker.txt").is_file()
        assert not (old_app / "_internal").exists()
    finally:
        if old.poll() is None:
            old.terminate()
        _wait_process_exit(old)


def test_ordinary_helper_rejects_plan_command_and_does_not_execute(tmp_path):
    plan, _data, _cred, old_app = _plan(
        tmp_path, target_revision=HEAD_REV, old_revision=HEAD_REV
    )
    marker = tmp_path / "ordinary-helper-marker"
    raw = json.loads(plan.plan_path.read_text(encoding="utf-8"))
    raw["new_app_command"] = [
        sys.executable,
        "-c",
        f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')",
    ]
    plan = update_install.InstallPlan(**raw)
    plan.plan_path.write_text(
        json.dumps(plan.as_dict(), ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    update_install.write_authorization(
        plan,
        state="authorized",
        close_request_id="ordinary-close",
        close_generation=1,
    )
    helper = _start_helper(
        plan,
        "--old-timeout",
        "0.1",
        verification_context=False,
    )
    try:
        helper.wait(timeout=10)
    finally:
        if helper.poll() is None:
            helper.terminate()
    result = _result(plan, timeout=5)
    assert result["status"] == "failed"
    assert result["code"] in (
        "INSTALL_PRODUCT_LAYOUT",
        "INSTALL_SOURCE_MISSING",
        "INSTALL_SOURCE_UNCONFIGURED",
    )
    assert not marker.exists()
    assert (old_app / "old-marker.txt").is_file()


def test_frozen_helper_rejects_verification_context(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert (
        update_helper.main(
            ["--plan", "unused", "--verification-context"]
        )
        == 2
    )


def test_live_process_wrong_exe_or_missing_exe_is_not_gone(tmp_path):
    current = update_process.current_process_identity()
    wrong_exe = ProcessIdentity(
        pid=current.pid,
        creation_time=current.creation_time,
        executable=str(tmp_path / "not-the-current-exe.exe"),
    )
    missing_exe = ProcessIdentity(
        pid=current.pid,
        creation_time=current.creation_time,
        executable="",
    )
    assert update_process.process_matches(wrong_exe) is True
    assert update_process.wait_for_process_exit(wrong_exe, 0.1) is False
    assert update_process.process_matches(missing_exe) is True
    assert update_process.wait_for_process_exit(missing_exe, 0.1) is False


def test_helper_old_process_timeout_does_not_switch(tmp_path):
    plan, _data, _cred, old_app = _plan(
        tmp_path, target_revision=HEAD_REV, old_revision=HEAD_REV
    )
    update_install.write_authorization(
        plan,
        state="authorized",
        close_request_id="close-2",
        close_generation=1,
    )
    process = _start_helper(plan, "--old-timeout", "0.3")
    try:
        process.wait(timeout=10)
    finally:
        if process.poll() is None:
            process.terminate()
    result = _result(plan, timeout=5)
    assert result["status"] == "failed"
    assert result["code"] == "INSTALL_OLD_PROCESS_TIMEOUT"
    assert (old_app / "old-marker.txt").exists()


def test_helper_reverifies_original_zip_and_switches_directory(tmp_path):
    plan, data, _cred, old_app = _plan(
        tmp_path, target_revision=HEAD_REV, old_revision=HEAD_REV
    )
    _make_current_db(data, Path(plan.credential_root), HEAD_REV)
    (data / "history-marker.txt").write_text("history", encoding="utf-8")
    (Path(plan.credential_root) / "ai-marker.txt").write_text(
        "credential", encoding="utf-8"
    )
    # Start the real old process holding the runtime lock.
    ready = tmp_path / "old-ready"
    stop = tmp_path / "old-stop"
    old = _start_old(data, Path(plan.credential_root), ready, stop)
    try:
        old_pid = _wait_ready(ready)["pid"]
        plan = _replace_old_process(plan, old_pid)
        update_install.write_authorization(
            plan,
            state="authorized",
            close_request_id="close-3",
            close_generation=1,
        )
        helper = _start_helper(plan, "--ready-timeout", "20", "--allow-launcher")
        # Observe the persistent state while the helper is still alive, then
        # re-check the same coordinator after the real success.  This is the
        # restart-refresh regression, not a new-instance shortcut.
        observer = update_install.InstallCoordinator(
            identity=_identity(HEAD_REV),
            data_dir=data,
            credential_root=Path(plan.credential_root),
            install_root=plan.install_root,
            app_dir=old_app,
            helper_command=[sys.executable, str(HELPER)],
            release_config=Path(plan.release_config),
            test_only=True,
        )
        assert observer.install_available() is False
        # Let the helper wait; then close the old process normally.
        time.sleep(0.3)
        stop.write_text("stop", encoding="utf-8")
        helper.wait(timeout=40)
        result = _result(plan, timeout=5)
        assert result["status"] == "success", result
        assert observer.install_available() is True
        assert observer.state()["install_state"] == "idle"
        assert (old_app / "old-marker.txt").exists() is False
        assert (old_app / "_internal" / "build_identity.json").is_file()
        assert (Path(plan.backup_dir) / "old-marker.txt").is_file()
        assert (Path(plan.state_dir) / "ready.json").is_file()
        assert (Path(plan.state_dir) / "install-result.json").is_file()
        assert (data / "history-marker.txt").read_text(encoding="utf-8") == "history"
        assert (Path(plan.credential_root) / "ai-marker.txt").read_text(
            encoding="utf-8"
        ) == "credential"
        _stop_new(plan, result)
    finally:
        if old.poll() is None:
            old.terminate()
        _wait_process_exit(old)


def _patch_new_command(plan: update_install.InstallPlan, *extra: str):
    raw = json.loads(plan.plan_path.read_text(encoding="utf-8"))
    raw["new_app_command"] = list(raw["new_app_command"]) + list(extra)
    updated = update_install.InstallPlan(**raw)
    updated.plan_path.write_text(
        json.dumps(updated.as_dict(), ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    return updated


def _replace_old_process(plan: update_install.InstallPlan, pid: int):
    identity = update_process.process_identity(pid)
    assert identity is not None
    raw = json.loads(plan.plan_path.read_text(encoding="utf-8"))
    raw["old_process"] = identity.as_dict()
    plan = update_install.InstallPlan(**raw)
    plan.plan_path.write_text(
        json.dumps(plan.as_dict(), ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    return plan


def test_real_0004_to_0006_cold_migration_after_old_handles_release(tmp_path):
    plan, data, _cred, old_app = _plan(
        tmp_path, target_revision=HEAD_REV, old_revision=OLD_REV
    )
    _make_current_db(data, Path(plan.credential_root), OLD_REV)
    ready = tmp_path / "old-ready"
    stop = tmp_path / "old-stop"
    old = _start_old(data, Path(plan.credential_root), ready, stop, db_only=True)
    try:
        old_pid = _wait_ready(ready)["pid"]
        plan = _replace_old_process(plan, old_pid)
        update_install.write_authorization(
            plan,
            state="authorized",
            close_request_id="close-migration",
            close_generation=1,
        )
        helper = _start_helper(plan, "--ready-timeout", "30", "--allow-launcher")
        time.sleep(0.3)
        stop.write_text("stop", encoding="utf-8")
        helper.wait(timeout=60)
        result = _result(plan, timeout=5)
        assert result["status"] == "success", result
        _stop_new(plan, result)
        # The real new LocalRuntime performed the 0004 -> 0006 migration.
        runtime = LocalRuntime(data, credential_root=Path(plan.credential_root))
        try:
            runtime.prepare()
            assert runtime.current_revision == HEAD_REV
        finally:
            runtime.dispose()
        assert (Path(plan.backup_dir) / "old-marker.txt").is_file()
    finally:
        if old.poll() is None:
            old.terminate()
        _wait_process_exit(old)


def test_prepare_while_bound_is_single_install(tmp_path):
    plan, data, cred, old_app = _plan(
        tmp_path, target_revision=HEAD_REV, old_revision=HEAD_REV
    )
    coordinator = update_install.InstallCoordinator(
        identity=_identity(HEAD_REV),
        data_dir=data,
        credential_root=cred,
        install_root=tmp_path / "program",
        app_dir=old_app,
        helper_command=[sys.executable, str(HELPER)],
        release_config=Path(plan.release_config),
        test_only=True,
    )
    coordinator._plan = plan
    coordinator._state = "bound"
    calls = {"payload": 0}

    class Manager:
        def install_payload(self):
            calls["payload"] += 1
            raise AssertionError("a bound plan must not create a second plan")

    result = coordinator.prepare_from_manager(Manager())
    assert result["accepted"] is False
    assert result["reason"] in ("INSTALL_BUSY", "INSTALL_RESULT_MISSING")
    assert calls["payload"] == 0
    assert coordinator._plan.plan_id == plan.plan_id


def test_unknown_install_result_keeps_single_install(tmp_path):
    plan, data, cred, old_app = _plan(
        tmp_path, target_revision=HEAD_REV, old_revision=HEAD_REV
    )
    update_install.write_result(plan, "unknown", "INSTALL_READY_TIMEOUT")
    coordinator = update_install.InstallCoordinator(
        identity=_identity(HEAD_REV),
        data_dir=data,
        credential_root=cred,
        install_root=tmp_path / "program",
        app_dir=old_app,
        helper_command=[sys.executable, str(HELPER)],
        release_config=Path(plan.release_config),
        test_only=True,
    )
    coordinator._plan = plan
    coordinator._state = "revoked"
    result = coordinator.prepare_from_manager(object())
    assert result["accepted"] is False
    assert result["reason"] == "INSTALL_RESULT_UNKNOWN"


def test_live_helper_keeps_install_busy_until_exit(tmp_path):
    plan, data, cred, old_app = _plan(
        tmp_path, target_revision=HEAD_REV, old_revision=HEAD_REV
    )
    helper = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(2)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        identity = update_process.process_identity(helper.pid)
        assert identity is not None
        update_install.write_helper_process(plan, identity)
        coordinator = update_install.InstallCoordinator(
            identity=_identity(HEAD_REV),
            data_dir=data,
            credential_root=cred,
            install_root=tmp_path / "program",
            app_dir=old_app,
            helper_command=[sys.executable, str(HELPER)],
            release_config=Path(plan.release_config),
            test_only=True,
        )
        coordinator._plan = plan
        coordinator._state = "revoked"
        result = coordinator.prepare_from_manager(object())
        assert result["accepted"] is False
        assert result["reason"] == "INSTALL_HELPER_ALIVE"
    finally:
        if helper.poll() is None:
            helper.terminate()
            helper.wait(timeout=5)


def test_unknown_install_blocks_after_real_coordinator_restart(tmp_path):
    plan, data, cred, old_app = _plan(
        tmp_path, target_revision=HEAD_REV, old_revision=HEAD_REV
    )
    update_install.write_result(plan, "unknown", "INSTALL_READY_TIMEOUT")
    update_install._append_phase(plan, "new_process_started", pid=99999)
    code = (
        "import json, sys, update_install\n"
        "from update_identity import AppIdentity\n"
        f"p=update_install.load_plan({str(plan.plan_path)!r})\n"
        f"c=update_install.InstallCoordinator(identity=AppIdentity(**p.current), data_dir={str(data)!r}, credential_root={str(cred)!r}, install_root={str(plan.install_root)!r}, app_dir={str(old_app)!r}, helper_command=[{sys.executable!r}, {str(HELPER)!r}], release_config={str(plan.release_config)!r}, test_only=True)\n"
        "class M:\n"
        "    def install_payload(self): raise AssertionError('must not prepare')\n"
        "print(json.dumps(c.prepare_from_manager(M())))\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(DESKTOP) + os.pathsep + str(BACKEND)
    env["APP_DISABLE_DOTENV"] = "1"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(DESKTOP),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip())
    assert payload["accepted"] is False
    assert payload["reason"] == "INSTALL_RESULT_UNKNOWN"


def test_bad_success_receipts_are_not_treated_as_completed(tmp_path):
    for mutate in ("missing", "wrong_nonce", "wrong_plan"):
        plan, data, cred, old_app = _plan(
            tmp_path / mutate, target_revision=HEAD_REV, old_revision=HEAD_REV
        )
        receipt = _success_receipt(plan)
        if mutate == "missing":
            receipt = {}
        elif mutate == "wrong_nonce":
            receipt["nonce"] = "wrong-nonce"
        else:
            receipt["plan_id"] = "wrong-plan"
        update_install.write_result(plan, "success", None, receipt=receipt)
        coordinator = update_install.InstallCoordinator(
            identity=_identity(HEAD_REV),
            data_dir=data,
            credential_root=cred,
            install_root=plan.install_root,
            app_dir=old_app,
            helper_command=[sys.executable, str(HELPER)],
            release_config=Path(plan.release_config),
            test_only=True,
        )
        assert coordinator.install_available() is False
        assert coordinator.state()["install_state"] == "needs_review"


def test_confirmed_pre_switch_failure_does_not_block_later_install(tmp_path):
    plan, data, cred, old_app = _plan(
        tmp_path, target_revision=HEAD_REV, old_revision=HEAD_REV
    )
    update_install.write_result(plan, "failed", "INSTALL_PACKAGE_MISMATCH")
    update_install._append_phase(plan, "helper_started", pid=99999)
    coordinator = update_install.InstallCoordinator(
        identity=_identity(HEAD_REV),
        data_dir=data,
        credential_root=cred,
        install_root=tmp_path / "program",
        app_dir=old_app,
        helper_command=[sys.executable, str(HELPER)],
        release_config=Path(plan.release_config),
        test_only=True,
    )
    assert coordinator.install_available() is True
    assert coordinator.state()["install_available"] is True


def _success_receipt(plan: update_install.InstallPlan) -> dict:
    return {
        "schema_version": update_install.RECEIPT_SCHEMA,
        "plan_id": plan.plan_id,
        "nonce": plan.nonce,
        "version": plan.target["version"],
        "build_id": plan.target["build_id"],
        "app_id": plan.target["app_id"],
        "package_format": plan.target["package_format"],
        "database_revision": plan.target["database_revision"],
        "data_dir": plan.data_dir,
        "credential_root": plan.credential_root,
        "runtime_ready": True,
        "service_ready": True,
        "page_ready": True,
        "pid": 1234,
        "creation_time": 134000000000000000,
    }


def test_completed_install_does_not_block_future_install(tmp_path):
    plan, data, cred, old_app = _plan(
        tmp_path, target_revision=HEAD_REV, old_revision=HEAD_REV
    )
    update_install.write_result(
        plan, "success", None, receipt=_success_receipt(plan)
    )
    coordinator = update_install.InstallCoordinator(
        identity=_identity(HEAD_REV),
        data_dir=data,
        credential_root=cred,
        install_root=tmp_path / "program",
        app_dir=old_app,
        helper_command=[sys.executable, str(HELPER)],
        release_config=Path(plan.release_config),
        test_only=True,
    )
    assert coordinator.install_available() is True


def test_bad_phase_record_is_not_silently_discarded(tmp_path):
    plan, _data, _cred, _old_app = _plan(
        tmp_path, target_revision=HEAD_REV, old_revision=HEAD_REV
    )
    update_install._append_phase(plan, "good")
    bad = plan.phases_dir / "99999999999999999999-bad.json"
    bad.write_text("{not-json", encoding="utf-8")
    with pytest.raises(update_install.InstallPlanError):
        update_install.read_phases(plan)
    assert bad.is_file()


def test_real_helper_exception_after_launch_writes_unknown(tmp_path):
    plan, data, _cred, old_app = _plan(
        tmp_path, target_revision=HEAD_REV, old_revision=HEAD_REV
    )
    _make_current_db(data, Path(plan.credential_root), HEAD_REV)
    ready = tmp_path / "old-ready"
    stop = tmp_path / "old-stop"
    old = _start_old(data, Path(plan.credential_root), ready, stop)
    try:
        old_pid = _wait_ready(ready)["pid"]
        plan = _replace_old_process(plan, old_pid)
        update_install.write_authorization(
            plan,
            state="authorized",
            close_request_id="worker-exception",
            close_generation=1,
        )
        bad = plan.phases_dir
        bad.mkdir(parents=True, exist_ok=True)
        damaged = bad / "99999999999999999999-damaged.json"
        damaged.write_text("{damaged", encoding="utf-8")
        helper = _start_helper(
            plan,
            "--old-timeout",
            "10",
            "--test-raise-after-launch",
            verification_context=True,
        )
        time.sleep(0.3)
        stop.write_text("stop", encoding="utf-8")
        helper.wait(timeout=20)
        result = _result(plan, timeout=5)
        assert result["status"] == "unknown"
        assert result["code"] == "INSTALL_HELPER_EXCEPTION"
        assert damaged.is_file()
        assert (Path(plan.backup_dir) / "old-marker.txt").is_file()
    finally:
        if old.poll() is None:
            old.terminate()
        _wait_process_exit(old)


def test_helper_exception_with_damaged_phases_records_unknown(monkeypatch, tmp_path):
    plan, _data, _cred, _old_app = _plan(
        tmp_path, target_revision=HEAD_REV, old_revision=HEAD_REV
    )
    update_install._append_phase(plan, "new_process_started", pid=99999)
    bad = plan.phases_dir / "99999999999999999999-bad.json"
    bad.write_text("{damaged", encoding="utf-8")

    def boom(*args, **kwargs):
        raise OSError("controlled helper exception")

    monkeypatch.setattr(update_helper, "run", boom)
    assert (
        update_helper.main(
            ["--plan", str(plan.plan_path), "--verification-context"]
        )
        == 1
    )
    result = update_install.read_result(plan)
    assert result is not None
    assert result["status"] == "unknown"
    assert result["code"] == "INSTALL_HELPER_EXCEPTION"
    assert bad.is_file()


def test_phase_records_survive_two_real_writer_processes(tmp_path):
    plan, _data, _cred, _old_app = _plan(
        tmp_path, target_revision=HEAD_REV, old_revision=HEAD_REV
    )
    code = (
        "import sys, update_install\n"
        f"p=update_install.load_plan({str(plan.plan_path)!r})\n"
        "for i in range(31): update_install._append_phase(p, 'writer', i=i)\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(DESKTOP) + os.pathsep + str(BACKEND)
    env["APP_DISABLE_DOTENV"] = "1"
    writers = [
        subprocess.Popen(
            [sys.executable, "-c", code],
            cwd=str(DESKTOP),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _ in range(2)
    ]
    try:
        for process in writers:
            stdout, stderr = process.communicate(timeout=20)
            assert process.returncode == 0, (stdout, stderr)
    finally:
        for process in writers:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
    records = update_install.read_phases(plan)
    assert len(records) == 62
    assert sum(1 for item in records if item.get("phase") == "writer") == 62


def test_helper_tampered_zip_leaves_old_program(tmp_path):
    plan, data, _cred, old_app = _plan(
        tmp_path, target_revision=HEAD_REV, old_revision=HEAD_REV
    )
    _make_current_db(data, Path(plan.credential_root), HEAD_REV)
    ready = tmp_path / "old-ready"
    stop = tmp_path / "old-stop"
    old = _start_old(data, Path(plan.credential_root), ready, stop)
    try:
        old_pid = _wait_ready(ready)["pid"]
        plan = _replace_old_process(plan, old_pid)
        archive = Path(plan.package_zip)
        archive.write_bytes(archive.read_bytes() + b"tamper")
        update_install.write_authorization(
            plan,
            state="authorized",
            close_request_id="close-4",
            close_generation=1,
        )
        helper = _start_helper(plan, "--old-timeout", "10")
        time.sleep(0.3)
        stop.write_text("stop", encoding="utf-8")
        helper.wait(timeout=20)
        result = _result(plan, timeout=5)
        assert result["status"] == "failed"
        assert result["code"] == "INSTALL_PACKAGE_MISMATCH"
        assert (old_app / "old-marker.txt").exists()
    finally:
        if old.poll() is None:
            old.terminate()
        _wait_process_exit(old)


def test_occupied_or_non_directory_target_leaves_old_program_untouched(tmp_path):
    plan, data, _cred, old_app = _plan(
        tmp_path, target_revision=HEAD_REV, old_revision=HEAD_REV
    )
    _make_current_db(data, Path(plan.credential_root), HEAD_REV)
    shutil.rmtree(old_app)
    old_app.write_text("occupied target", encoding="utf-8")
    ready = tmp_path / "old-ready"
    stop = tmp_path / "old-stop"
    old = _start_old(data, Path(plan.credential_root), ready, stop)
    try:
        old_pid = _wait_ready(ready)["pid"]
        plan = _replace_old_process(plan, old_pid)
        update_install.write_authorization(
            plan,
            state="authorized",
            close_request_id="close-occupied",
            close_generation=1,
        )
        helper = _start_helper(plan, "--old-timeout", "10")
        time.sleep(0.3)
        stop.write_text("stop", encoding="utf-8")
        helper.wait(timeout=20)
        result = _result(plan, timeout=5)
        assert result["status"] == "failed"
        assert result["code"] == "INSTALL_APP_MISSING"
        assert old_app.read_text(encoding="utf-8") == "occupied target"
    finally:
        if old.poll() is None:
            old.terminate()
        _wait_process_exit(old)


def test_interrupted_directory_switch_keeps_old_backup_without_new_process(tmp_path):
    plan, data, _cred, old_app = _plan(
        tmp_path, target_revision=HEAD_REV, old_revision=HEAD_REV
    )
    _make_current_db(data, Path(plan.credential_root), HEAD_REV)
    ready = tmp_path / "old-ready"
    stop = tmp_path / "old-stop"
    old = _start_old(data, Path(plan.credential_root), ready, stop)
    try:
        old_pid = _wait_ready(ready)["pid"]
        plan = _replace_old_process(plan, old_pid)
        update_install.write_authorization(
            plan,
            state="authorized",
            close_request_id="close-switch",
            close_generation=1,
        )
        helper = _start_helper(
            plan, "--old-timeout", "10", "--fail-after-old-move"
        )
        time.sleep(0.3)
        stop.write_text("stop", encoding="utf-8")
        helper.wait(timeout=20)
        result = _result(plan, timeout=5)
        assert result["status"] == "failed"
        assert result["code"] == "INSTALL_SWITCH_INTERRUPTED"
        assert (Path(plan.backup_dir) / "old-marker.txt").is_file()
        assert not old_app.exists()
    finally:
        if old.poll() is None:
            old.terminate()
        _wait_process_exit(old)


def test_missing_page_ready_is_unknown_and_keeps_backup(tmp_path):
    plan, data, _cred, _old_app = _plan(
        tmp_path, target_revision=HEAD_REV, old_revision=HEAD_REV
    )
    _make_current_db(data, Path(plan.credential_root), HEAD_REV)
    plan = _patch_new_command(plan, "--skip-page-ready")
    ready = tmp_path / "old-ready"
    stop = tmp_path / "old-stop"
    old = _start_old(data, Path(plan.credential_root), ready, stop)
    try:
        old_pid = _wait_ready(ready)["pid"]
        plan = _replace_old_process(plan, old_pid)
        update_install.write_authorization(
            plan,
            state="authorized",
            close_request_id="close-5",
            close_generation=1,
        )
        helper = _start_helper(
            plan, "--old-timeout", "10", "--ready-timeout", "2", "--allow-launcher"
        )
        time.sleep(0.3)
        stop.write_text("stop", encoding="utf-8")
        helper.wait(timeout=20)
        result = _result(plan, timeout=5)
        assert result["status"] == "unknown"
        assert result["code"] == "INSTALL_READY_TIMEOUT"
        assert (Path(plan.backup_dir) / "old-marker.txt").is_file()
        _stop_new(plan, result)
    finally:
        if old.poll() is None:
            old.terminate()
        _wait_process_exit(old)


def test_new_process_migration_failure_is_unknown_and_not_rolled_back(tmp_path):
    plan, data, _cred, old_app = _plan(
        tmp_path, target_revision=HEAD_REV, old_revision=HEAD_REV
    )
    _make_current_db(data, Path(plan.credential_root), HEAD_REV)
    # Make the database revision unrecognisable to the new runtime.  The
    # helper must report unknown after starting the new process and must not
    # roll back the program or restore a database.
    db = data / "kindergarten.db"
    connection = sqlite3.connect(db)
    try:
        connection.execute(
            "UPDATE local_alembic_version SET version_num='20990101_9999_unknown'"
        )
        connection.commit()
    finally:
        connection.close()
    ready = tmp_path / "old-ready"
    stop = tmp_path / "old-stop"
    old = _start_old(data, Path(plan.credential_root), ready, stop, db_only=True)
    try:
        old_pid = _wait_ready(ready)["pid"]
        plan = _replace_old_process(plan, old_pid)
        update_install.write_authorization(
            plan,
            state="authorized",
            close_request_id="close-migration-fail",
            close_generation=1,
        )
        helper = _start_helper(plan, "--old-timeout", "10", "--ready-timeout", "10")
        time.sleep(0.3)
        stop.write_text("stop", encoding="utf-8")
        helper.wait(timeout=20)
        result = _result(plan, timeout=5)
        assert result["status"] == "unknown"
        assert result["code"] in (
            "INSTALL_PROCESS_EXITED",
            "INSTALL_READY_TIMEOUT",
        )
        assert (Path(plan.backup_dir) / "old-marker.txt").is_file()
        assert Path(plan.install_app_dir).is_dir()
    finally:
        if old.poll() is None:
            old.terminate()
        _wait_process_exit(old)


class _ServiceStub:
    def __init__(self, alive: bool):
        self._alive = alive

    def alive(self) -> bool:
        return self._alive


def _target_identity(plan: update_install.InstallPlan) -> AppIdentity:
    return AppIdentity(
        app_id=plan.target["app_id"],
        app_name="KindergartenManager",
        channel=plan.target["channel"],
        version=plan.target["version"],
        build_id=plan.target["build_id"],
        package_format=plan.target["package_format"],
        platform=plan.target["platform"],
        arch=plan.target["arch"],
        python="3.14.7",
        database_revision=plan.target["database_revision"],
    )


def test_ready_receipt_requires_real_identity_service_and_page(tmp_path):
    plan, data, _cred, _old_app = _plan(
        tmp_path, target_revision=HEAD_REV, old_revision=HEAD_REV
    )
    _make_current_db(data, Path(plan.credential_root), HEAD_REV)
    runtime = LocalRuntime(data, credential_root=Path(plan.credential_root))
    runtime.prepare()
    try:
        identity = _target_identity(plan)
        service = _ServiceStub(True)
        writer = update_install.ReadyReceiptWriter(
            plan,
            identity=identity,
            runtime=runtime,
            service=service,
            service_port=12345,
            ready_path=tmp_path / "ready.json",
            verification_context=True,
        )
        payload = writer.public_bootstrap()
        assert writer.confirm({**payload, "nonce": "wrong"}, page_ready=True)[
            "accepted"
        ] is False
        # No page_ready confirmation must never write a receipt.
        assert writer.confirm(payload)["accepted"] is False
        service._alive = False
        assert writer.confirm(payload, page_ready=True)["accepted"] is False
        service._alive = True
        assert writer.confirm(payload, page_ready=True)["accepted"] is True
        assert (tmp_path / "ready.json").is_file()
        receipt = json.loads((tmp_path / "ready.json").read_text(encoding="utf-8"))
        assert receipt["identity"]["version"] == plan.target["version"]
        assert receipt["data_dir"] == str(runtime.data_dir.resolve())
        product_writer = update_install.ReadyReceiptWriter(
            plan,
            identity=identity,
            runtime=runtime,
            service=service,
            service_port=12345,
            ready_path=tmp_path / "product-ready.json",
        )
        assert product_writer.confirm(payload, page_ready=True)["code"] == (
            "READY_PROCESS_TARGET_MISMATCH"
        )
        assert not (tmp_path / "product-ready.json").exists()
    finally:
        runtime.dispose()


def test_stale_close_revokes_bound_install_plan(tmp_path):
    plan, data, cred, old_app = _plan(
        tmp_path, target_revision=HEAD_REV, old_revision=HEAD_REV
    )
    coordinator = update_install.InstallCoordinator(
        identity=_identity(HEAD_REV),
        data_dir=data,
        credential_root=cred,
        install_root=tmp_path / "program",
        app_dir=old_app,
        helper_command=[sys.executable, str(HELPER)],
        release_config=Path(plan.release_config),
        test_only=True,
    )
    coordinator._plan = plan
    coordinator._state = "bound"
    update_install.write_authorization(
        plan,
        state="pending",
        close_request_id="old-close",
        close_generation=1,
    )
    coordinator.bind_close("new-close", 2)
    auth = update_install.read_authorization(plan)
    assert auth["state"] == "revoked"
    assert auth["reason"] == "INSTALL_CLOSE_SUPERSEDED"
    # A later ordinary close has no authorization to revive.
    coordinator.bind_close("ordinary-close", 3)
    assert update_install.read_authorization(plan)["state"] == "revoked"


def test_close_install_hooks_cancel_on_save_and_destroy_failures():
    from d1_host_api import CloseCoordinator

    events = []
    busy = {"value": True}
    fail_destroy = {"value": False}

    def destroy():
        if fail_destroy["value"]:
            raise RuntimeError("destroy failed")

    coordinator = CloseCoordinator(
        notify_page=lambda *args: None,
        destroy_window=destroy,
        notify_aborted=lambda *args: None,
        busy_probe=lambda: busy["value"],
        on_install_intent=lambda request_id, generation: events.append(
            ("intent", request_id)
        ),
        on_install_canceled=lambda request_id, reason: events.append(
            ("cancel", request_id, reason)
        ),
        on_install_final=lambda request_id, generation: events.append(
            ("final", request_id)
        ),
    )
    assert coordinator.handle_closing() is False
    request_id = coordinator._current_id
    busy["value"] = True
    result = coordinator.complete(request_id, True)
    assert result["state"] == "canceled"
    assert any(event[0] == "cancel" and event[2] == "save_in_flight" for event in events)
    # A new close after the save refusal must not inherit the old install.
    events.clear()
    busy["value"] = False
    fail_destroy["value"] = True
    assert coordinator.handle_closing() is False
    second = coordinator._current_id
    result = coordinator.complete(second, True)
    assert result["state"] == "canceled"
    assert any(event[0] == "cancel" and event[2] == "destroy_failed" for event in events)
    assert not any(event[0] == "final" for event in events)


def test_close_coordinator_install_callbacks_are_bound_and_revoked():
    from d1_host_api import CloseCoordinator

    events = []
    destroyed = {"ok": True}

    def destroy():
        if not destroyed["ok"]:
            raise RuntimeError("destroy failed")

    coordinator = CloseCoordinator(
        notify_page=lambda *args: None,
        destroy_window=destroy,
        notify_aborted=lambda *args: None,
        on_install_intent=lambda request_id, generation: events.append(
            ("intent", request_id, generation)
        ),
        on_install_canceled=lambda request_id, reason: events.append(
            ("cancel", request_id, reason)
        ),
        on_install_final=lambda request_id, generation: events.append(
            ("final", request_id, generation)
        ),
    )
    assert coordinator.handle_closing() is False
    request_id = coordinator._current_id
    assert request_id
    assert events and events[0][0] == "intent"
    assert coordinator.complete(request_id, False)["state"] == "canceled"
    assert any(event[0] == "cancel" for event in events)
    # A later ordinary close must not become an install final.
    events.clear()
    assert coordinator.handle_closing() is False
    second = coordinator._current_id
    assert coordinator.complete(second, True)["state"] == "closing"
    assert any(event[0] == "final" for event in events)
