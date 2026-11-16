"""Update failure persistence and classification regressions.

All roots are synthetic.  These tests never use the real managed install root,
real data/credentials, a frozen helper, or a signed release package.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

import update_helper
import update_install
from update_identity import AppIdentity
from update_manifest import ManifestError

CURRENT = "0.1.0-listening-test.20261115"
FAILED_TARGET = "0.1.0-listening-test.20261116"
NEWER_TARGET = "0.1.0-listening-test.20261117"
PLAN_CREATED = "2026-11-15T00:00:00Z"
TIME_0900 = "2026-11-15T09:00:00Z"
TIME_1000 = "2026-11-15T10:00:00Z"
TIME_1100 = "2026-11-15T11:00:00Z"
TIME_1200 = "2026-11-15T12:00:00Z"
TIME_1300 = "2026-11-15T13:00:00Z"


def _pid(char: str) -> str:
    assert len(char) == 1 and char in "0123456789abcdef"
    return char * 32


def _identity(version: str) -> AppIdentity:
    return AppIdentity(
        app_id="kindergarten-manager-next",
        app_name="KindergartenManager",
        channel="preview",
        version=version,
        build_id="00000000-0000-4000-8000-000000000001",
        package_format="pyinstaller-onedir-zip-v1",
        platform="windows",
        arch="x64",
        python="3.14.10",
        database_revision="20261102_0008_local_weekly_ai",
    )


def _make_plan(
    root: Path,
    *,
    plan_id: str,
    target_version: str,
    created_at: str = PLAN_CREATED,
) -> update_install.InstallPlan:
    install_root = root / "program"
    state_dir = install_root / "install-state" / plan_id
    state_dir.mkdir(parents=True, exist_ok=True)
    plan = update_install.InstallPlan(
        schema_version=update_install.PLAN_SCHEMA,
        plan_id=plan_id,
        nonce=f"nonce-{plan_id}",
        created_at=created_at,
        current=_identity(CURRENT).as_dict(),
        target={
            "app_id": "kindergarten-manager-next",
            "channel": "preview",
            "version": target_version,
            "build_id": f"build-{plan_id}",
            "package_format": "pyinstaller-onedir-zip-v1",
            "database_revision": "20261102_0008_local_weekly_ai",
        },
        old_process={},
        data_dir=str(root / "data"),
        credential_root=str(root / "credentials"),
        install_root=str(install_root),
        install_app_dir=str(install_root / "app"),
        backup_dir=str(install_root / "backups" / plan_id),
        state_dir=str(state_dir),
        staging_dir=str(root / "updates" / "staging" / "download"),
        package_zip=str(
            root / "updates" / "staging" / "download" / "package.zip"
        ),
        metadata_path=str(state_dir / "update_metadata.json"),
        release_config="",
        helper_path=str(install_root / "updater" / "helper.exe"),
        new_app_path=str(install_root / "app" / "KindergartenManager.exe"),
        new_app_command=[],
    )
    _write_plan(plan)
    return plan


def _write_plan(plan: update_install.InstallPlan) -> None:
    plan.plan_path.write_text(
        json.dumps(plan.as_dict(), ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )


def _patch_plan(
    plan: update_install.InstallPlan, **changes: object
) -> update_install.InstallPlan:
    raw = json.loads(plan.plan_path.read_text(encoding="utf-8"))
    raw.update(changes)
    patched = update_install.InstallPlan(**raw)
    plan.plan_path.write_text(
        json.dumps(patched.as_dict(), ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    return patched


def _write_record(
    plan: update_install.InstallPlan,
    status: str,
    code: str | None,
    *,
    updated_at: str | None,
    **details: object,
) -> None:
    value = {
        "schema_version": update_install.RESULT_SCHEMA,
        "plan_id": plan.plan_id,
        "nonce": plan.nonce,
        "status": status,
        "code": code,
    }
    if updated_at is not None:
        value["updated_at"] = updated_at
    value.update(details)
    plan.result_path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )


def _write_failed(
    plan: update_install.InstallPlan,
    *,
    updated_at: str | None = TIME_1200,
    code: str = "INSTALL_PACKAGE_INVALID",
) -> None:
    _write_record(plan, "failed", code, updated_at=updated_at)


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


def _write_success(
    plan: update_install.InstallPlan,
    *,
    updated_at: str | None = TIME_0900,
    receipt: dict | None = None,
) -> None:
    if receipt is None:
        receipt = _success_receipt(plan)
    _write_record(
        plan,
        "success",
        None,
        updated_at=updated_at,
        receipt=receipt,
    )


def _set_result_mtime(plan: update_install.InstallPlan, timestamp: str) -> None:
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    value = parsed.timestamp()
    os.utime(plan.result_path, (value, value))


def _coordinator(root: Path, current_version: str = CURRENT):
    return update_install.InstallCoordinator(
        identity=_identity(current_version),
        data_dir=root / "data",
        credential_root=root / "credentials",
        install_root=root / "program",
        app_dir=root / "program" / "app",
        helper_command=["unused-helper"],
        release_config=None,
        test_only=True,
    )


def _snapshot(root: Path) -> dict[str, tuple[bool, int, int]]:
    result: dict[str, tuple[bool, int, int]] = {}
    for path in sorted(root.rglob("*")):
        stat = path.stat()
        result[str(path.relative_to(root))] = (
            path.is_dir(),
            stat.st_size,
            stat.st_mtime_ns,
        )
    return result


def _raiser(exc: BaseException):
    def fail(*_args, **_kwargs):
        raise exc

    return fail


def _package_inputs(root: Path, plan_id: str = _pid("b")):
    plan = _make_plan(
        root,
        plan_id=plan_id,
        target_version=FAILED_TARGET,
    )
    archive = Path(plan.package_zip)
    archive.parent.mkdir(parents=True, exist_ok=True)
    payload = b"synthetic package bytes"
    archive.write_bytes(payload)
    manifest = SimpleNamespace(
        package_size=len(payload),
        package_sha256=hashlib.sha256(payload).hexdigest(),
    )
    return plan, manifest


def test_state_without_install_records_has_null_failure(tmp_path):
    coordinator = _coordinator(tmp_path)
    state = coordinator.state()
    assert "last_install_failure" in state
    assert state["last_install_failure"] is None
    assert state["install_available"] is True


def test_legacy_package_invalid_failure_is_recovered_and_echoed(tmp_path):
    plan = _make_plan(
        tmp_path, plan_id=_pid("a"), target_version=FAILED_TARGET
    )
    _write_failed(
        plan,
        code="INSTALL_PACKAGE_INVALID",
        updated_at="2026-11-15T12:05:32Z",
    )
    update_install._append_phase(plan, "helper_started", pid=99999)
    coordinator = _coordinator(tmp_path)
    state = coordinator.state()
    assert state["install_available"] is True
    assert state["install_state"] == "idle"
    assert state["last_install_failure"] == {
        "plan_id": plan.plan_id,
        "target_version": FAILED_TARGET,
        "status": "failed",
        "code": "INSTALL_PACKAGE_INVALID",
        "updated_at": "2026-11-15T12:05:32Z",
    }


def test_winerror_206_is_classified_and_result_and_summary_are_safe(
    tmp_path, monkeypatch
):
    plan, manifest = _package_inputs(tmp_path)
    relative = (
        "KindergartenManager/_internal/app/assets/word_templates/"
        + "license-" + "x" * 70
    )
    absolute = str(Path(plan.state_dir) / "verified" / relative)
    exc = OSError(36, "file name too long", absolute)
    exc.winerror = 206
    monkeypatch.setattr(
        update_helper, "verify_package_zip", _raiser(exc)
    )
    with pytest.raises(update_install.InstallPlanError) as caught:
        update_helper._verify_saved_package(plan, manifest)
    error = caught.value
    assert error.code == "INSTALL_PACKAGE_PATH_TOO_LONG"
    assert error.diagnostic == {
        "type": "OSError",
        "winerror": 206,
        "errno": 36,
        "path_length": len(absolute),
        "relative_path": relative,
    }
    assert len(error.diagnostic["relative_path"]) <= 160

    update_helper._fail(
        plan,
        "failed",
        error.code,
        **update_helper._package_failure_details(error),
    )
    result = update_install.read_result(plan)
    assert result is not None
    assert result["code"] == "INSTALL_PACKAGE_PATH_TOO_LONG"
    assert result["diagnostic"]["winerror"] == 206

    coordinator = _coordinator(tmp_path)
    state = coordinator.state()
    summary = state["last_install_failure"]
    assert summary == {
        "plan_id": plan.plan_id,
        "target_version": FAILED_TARGET,
        "status": "failed",
        "code": "INSTALL_PACKAGE_PATH_TOO_LONG",
        "updated_at": result["updated_at"],
    }
    rendered = json.dumps(summary, ensure_ascii=False)
    assert set(summary) == {
        "plan_id",
        "target_version",
        "status",
        "code",
        "updated_at",
    }
    assert plan.nonce not in rendered
    assert str(tmp_path) not in rendered
    assert "license-" not in rendered


def test_general_package_oserror_uses_io_code_and_path_length(
    tmp_path, monkeypatch
):
    plan, manifest = _package_inputs(tmp_path, plan_id=_pid("c"))
    absolute = str(tmp_path / "outside" / "private" / "license.txt")
    exc = OSError(13, "permission denied", absolute)
    monkeypatch.setattr(
        update_helper, "verify_package_zip", _raiser(exc)
    )
    with pytest.raises(update_install.InstallPlanError) as caught:
        update_helper._verify_saved_package(plan, manifest)
    error = caught.value
    assert error.code == "INSTALL_PACKAGE_IO_ERROR"
    assert error.diagnostic["type"] == "PermissionError"
    assert error.diagnostic["errno"] == 13
    assert error.diagnostic["path_length"] == len(absolute)
    rendered = json.dumps(error.diagnostic, ensure_ascii=False)
    assert str(tmp_path) not in rendered
    assert "private" not in rendered
    assert "license.txt" not in rendered


def test_manifest_error_code_is_preserved_without_diagnostic(
    tmp_path, monkeypatch
):
    plan, manifest = _package_inputs(tmp_path, plan_id=_pid("d"))
    exc = ManifestError("UPDATE_PACKAGE_INVALID", "synthetic invalid package")
    monkeypatch.setattr(
        update_helper, "verify_package_zip", _raiser(exc)
    )
    with pytest.raises(ManifestError) as caught:
        update_helper._verify_saved_package(plan, manifest)
    error = caught.value
    assert error.code == "UPDATE_PACKAGE_INVALID"
    assert not hasattr(error, "diagnostic")


def test_restored_old_directory_failure_is_definite_and_echoed(tmp_path):
    plan = _make_plan(
        tmp_path, plan_id=_pid("a"), target_version=FAILED_TARGET
    )
    _write_failed(
        plan,
        code="INSTALL_SWITCH_FAILED",
        updated_at=TIME_1200,
    )
    update_install._append_phase(plan, "old_app_backed_up", backup="synthetic")
    update_install._append_phase(plan, "old_app_restored")
    coordinator = _coordinator(tmp_path)
    state = coordinator.state()
    assert state["install_available"] is True
    assert state["last_install_failure"]["plan_id"] == plan.plan_id
    assert state["last_install_failure"]["code"] == "INSTALL_SWITCH_FAILED"


def test_failed_after_switch_stays_protected_not_converted_to_failure(tmp_path):
    plan = _make_plan(
        tmp_path, plan_id=_pid("a"), target_version=FAILED_TARGET
    )
    _write_failed(
        plan,
        code="INSTALL_SWITCH_INTERRUPTED",
        updated_at=TIME_1200,
    )
    update_install._append_phase(plan, "old_app_backed_up", backup="synthetic")
    update_install._append_phase(plan, "new_app_moved")
    coordinator = _coordinator(tmp_path)
    state = coordinator.state()
    assert state["install_available"] is False
    assert state["install_state"] == "needs_review"
    assert state["last_install_failure"] is None


def test_latest_failed_record_is_selected_by_time_not_uuid(tmp_path):
    older = _make_plan(
        tmp_path,
        plan_id=_pid("f"),
        target_version=FAILED_TARGET,
        created_at=TIME_0900,
    )
    newer = _make_plan(
        tmp_path,
        plan_id=_pid("0"),
        target_version=NEWER_TARGET,
        created_at=TIME_1100,
    )
    _write_failed(older, updated_at=TIME_1000)
    _write_failed(newer, updated_at=TIME_1100)
    coordinator = _coordinator(tmp_path)
    summary = coordinator.state()["last_install_failure"]
    assert summary is not None
    assert summary["plan_id"] == newer.plan_id
    assert summary["target_version"] == NEWER_TARGET
    assert summary["updated_at"] == TIME_1100


def test_failure_chronology_ignores_uuid_created_at_and_file_mtime(tmp_path):
    older = _make_plan(
        tmp_path,
        plan_id=_pid("f"),
        target_version=FAILED_TARGET,
        created_at=TIME_1300,
    )
    newer = _make_plan(
        tmp_path,
        plan_id=_pid("0"),
        target_version=FAILED_TARGET,
        created_at="2026-11-15T08:00:00Z",
    )
    _write_failed(older, updated_at=TIME_1000)
    _write_failed(newer, updated_at=TIME_1100)
    _set_result_mtime(older, TIME_1300)
    _set_result_mtime(newer, TIME_0900)
    coordinator = _coordinator(tmp_path)
    summary = coordinator.state()["last_install_failure"]
    assert summary is not None
    assert summary["plan_id"] == newer.plan_id
    assert summary["updated_at"] == TIME_1100


def test_older_success_does_not_hide_later_failure(tmp_path):
    failed = _make_plan(
        tmp_path, plan_id=_pid("a"), target_version=FAILED_TARGET
    )
    success = _make_plan(
        tmp_path, plan_id=_pid("b"), target_version=FAILED_TARGET
    )
    _write_success(success, updated_at=TIME_0900)
    _write_failed(failed, updated_at=TIME_1200)
    coordinator = _coordinator(tmp_path)
    summary = coordinator.state()["last_install_failure"]
    assert summary is not None
    assert summary["plan_id"] == failed.plan_id
    assert summary["updated_at"] == TIME_1200


def test_timezone_aware_older_success_does_not_hide_later_failure(tmp_path):
    failed = _make_plan(
        tmp_path, plan_id=_pid("a"), target_version=FAILED_TARGET
    )
    success = _make_plan(
        tmp_path, plan_id=_pid("b"), target_version=FAILED_TARGET
    )
    # 17:00+08:00 is 09:00Z, strictly earlier than the 12:00Z failure.
    _write_success(success, updated_at="2026-11-15T17:00:00+08:00")
    _write_failed(failed, updated_at=TIME_1200)
    coordinator = _coordinator(tmp_path)
    summary = coordinator.state()["last_install_failure"]
    assert summary is not None
    assert summary["plan_id"] == failed.plan_id


@pytest.mark.parametrize("success_target", [FAILED_TARGET, NEWER_TARGET])
def test_later_success_hides_earlier_failure(tmp_path, success_target):
    failed = _make_plan(
        tmp_path, plan_id=_pid("a"), target_version=FAILED_TARGET
    )
    success = _make_plan(
        tmp_path, plan_id=_pid("b"), target_version=success_target
    )
    _write_failed(failed, updated_at=TIME_0900)
    _write_success(success, updated_at=TIME_1200)
    coordinator = _coordinator(tmp_path)
    state = coordinator.state()
    assert state["install_available"] is True
    assert state["last_install_failure"] is None


def test_later_lower_success_does_not_hide_higher_failure(tmp_path):
    failed = _make_plan(
        tmp_path, plan_id=_pid("a"), target_version=NEWER_TARGET
    )
    success = _make_plan(
        tmp_path, plan_id=_pid("b"), target_version=FAILED_TARGET
    )
    _write_failed(failed, updated_at=TIME_0900)
    _write_success(success, updated_at=TIME_1200)
    coordinator = _coordinator(tmp_path)
    summary = coordinator.state()["last_install_failure"]
    assert summary is not None
    assert summary["plan_id"] == failed.plan_id
    assert summary["target_version"] == NEWER_TARGET


def test_equal_success_and_failure_times_do_not_invent_chronology(tmp_path):
    failed = _make_plan(
        tmp_path, plan_id=_pid("a"), target_version=FAILED_TARGET
    )
    success = _make_plan(
        tmp_path, plan_id=_pid("b"), target_version=FAILED_TARGET
    )
    _write_failed(failed, updated_at=TIME_1200)
    _write_success(success, updated_at=TIME_1200)
    coordinator = _coordinator(tmp_path)
    summary = coordinator.state()["last_install_failure"]
    assert summary is not None
    assert summary["plan_id"] == failed.plan_id


@pytest.mark.parametrize("damage", ["missing", "wrong-nonce", "wrong-plan"])
def test_suspicious_success_receipt_is_not_used_for_suppression(
    tmp_path, damage
):
    failed = _make_plan(
        tmp_path, plan_id=_pid("a"), target_version=FAILED_TARGET
    )
    success = _make_plan(
        tmp_path, plan_id=_pid("b"), target_version=NEWER_TARGET
    )
    _write_failed(failed, updated_at=TIME_0900)
    receipt = _success_receipt(success)
    if damage == "missing":
        receipt = {}
    elif damage == "wrong-nonce":
        receipt["nonce"] = "wrong-nonce"
    else:
        receipt["plan_id"] = _pid("0")
    _write_success(success, updated_at=TIME_1200, receipt=receipt)
    coordinator = _coordinator(tmp_path)
    state = coordinator.state()
    assert state["install_available"] is False
    assert state["install_state"] == "needs_review"
    assert state["last_install_failure"] is None


@pytest.mark.parametrize("status", ["failed", "success"])
@pytest.mark.parametrize("updated_at", [None, "not-a-time", "2026-11-15T09:00:00"])
def test_missing_or_malformed_result_time_stays_protected(
    tmp_path, status, updated_at
):
    plan = _make_plan(
        tmp_path, plan_id=_pid("a"), target_version=FAILED_TARGET
    )
    if status == "failed":
        _write_failed(plan, updated_at=updated_at)
    else:
        _write_success(plan, updated_at=updated_at)
    # A valid creation time and a plausible file mtime must not become the
    # public result time for a damaged record.
    _set_result_mtime(plan, TIME_1300)
    coordinator = _coordinator(tmp_path)
    state = coordinator.state()
    assert state["install_available"] is False
    assert state["install_state"] == "needs_review"
    assert state["last_install_failure"] is None


@pytest.mark.parametrize("bad_id", ["A" * 32, "g" * 32, "a" * 33])
def test_nonproduction_plan_id_shape_is_protected(tmp_path, bad_id):
    plan = _make_plan(
        tmp_path, plan_id=bad_id, target_version=FAILED_TARGET
    )
    _write_failed(plan, updated_at=TIME_1200)
    coordinator = _coordinator(tmp_path)
    state = coordinator.state()
    assert state["install_available"] is False
    assert state["install_state"] == "needs_review"
    assert state["last_install_failure"] is None


@pytest.mark.parametrize(
    "bad_id",
    [
        "C:\\synthetic-private\\" + "x" * 200,
        "bad\nid",
        _pid("b"),
    ],
)
def test_plan_id_must_bind_to_exact_state_directory(tmp_path, bad_id):
    plan = _make_plan(
        tmp_path, plan_id=_pid("a"), target_version=FAILED_TARGET
    )
    patched = _patch_plan(plan, plan_id=bad_id)
    _write_failed(patched, updated_at=TIME_1200)
    coordinator = _coordinator(tmp_path)
    state = coordinator.state()
    assert state["install_available"] is False
    assert state["install_state"] == "needs_review"
    assert state["last_install_failure"] is None
    assert "synthetic-private" not in json.dumps(
        state["last_install_failure"], ensure_ascii=False
    )


@pytest.mark.parametrize("field", ["state_dir", "install_root"])
def test_plan_path_fields_must_bind_to_scanned_state(tmp_path, field):
    plan = _make_plan(
        tmp_path, plan_id=_pid("a"), target_version=FAILED_TARGET
    )
    if field == "state_dir":
        other = str(tmp_path / "other" / plan.plan_id)
    else:
        other = str(tmp_path / "other-program")
    _patch_plan(plan, **{field: other})
    _write_failed(plan, updated_at=TIME_1200)
    coordinator = _coordinator(tmp_path)
    state = coordinator.state()
    assert state["install_available"] is False
    assert state["install_state"] == "needs_review"
    assert state["last_install_failure"] is None


@pytest.mark.parametrize("current_version", [FAILED_TARGET, NEWER_TARGET])
def test_current_version_at_or_above_failed_target_hides_failure(
    tmp_path, current_version
):
    plan = _make_plan(
        tmp_path, plan_id=_pid("a"), target_version=FAILED_TARGET
    )
    _write_failed(plan, updated_at=TIME_1200)
    coordinator = _coordinator(tmp_path, current_version)
    assert coordinator.state()["last_install_failure"] is None


def test_current_version_does_not_waive_unknown_protection(tmp_path):
    failed = _make_plan(
        tmp_path, plan_id=_pid("a"), target_version=FAILED_TARGET
    )
    unknown = _make_plan(
        tmp_path, plan_id=_pid("b"), target_version=NEWER_TARGET
    )
    _write_failed(failed, updated_at=TIME_0900)
    _write_record(
        unknown,
        "unknown",
        "INSTALL_READY_TIMEOUT",
        updated_at=TIME_1000,
    )
    coordinator = _coordinator(tmp_path, NEWER_TARGET)
    state = coordinator.state()
    assert state["install_available"] is False
    assert state["install_state"] == "needs_review"
    assert state["last_install_failure"] is None


def test_revoked_record_is_not_a_failure(tmp_path):
    plan = _make_plan(
        tmp_path, plan_id=_pid("a"), target_version=FAILED_TARGET
    )
    _write_record(
        plan,
        "revoked",
        "INSTALL_AUTHORIZATION_REVOKED",
        updated_at=TIME_1200,
    )
    coordinator = _coordinator(tmp_path)
    state = coordinator.state()
    assert state["install_available"] is True
    assert state["last_install_failure"] is None


def test_revoked_after_switch_stays_protected_but_is_not_a_failure(tmp_path):
    plan = _make_plan(
        tmp_path, plan_id=_pid("a"), target_version=FAILED_TARGET
    )
    _write_record(
        plan,
        "revoked",
        "INSTALL_AUTHORIZATION_WITHDRAWN",
        updated_at=TIME_1200,
    )
    update_install._append_phase(plan, "old_app_backed_up", backup="synthetic")
    update_install._append_phase(plan, "new_app_moved")
    coordinator = _coordinator(tmp_path)
    state = coordinator.state()
    assert state["install_available"] is False
    assert state["install_state"] == "needs_review"
    assert state["last_install_failure"] is None


@pytest.mark.parametrize("damage", ["bad-json", "wrong-nonce"])
def test_corrupt_record_blocks_and_is_not_released(tmp_path, damage):
    plan = _make_plan(
        tmp_path, plan_id=_pid("a"), target_version=FAILED_TARGET
    )
    if damage == "bad-json":
        plan.result_path.write_text("{not-json", encoding="utf-8")
    else:
        _write_record(
            plan,
            "failed",
            "INSTALL_PACKAGE_INVALID",
            updated_at=TIME_1200,
            nonce="wrong-nonce",
        )
    coordinator = _coordinator(tmp_path)
    state = coordinator.state()
    assert state["install_available"] is False
    assert state["install_state"] == "needs_review"
    assert state["last_install_failure"] is None


def test_unknown_result_blocks_without_failure_digest(tmp_path):
    plan = _make_plan(
        tmp_path, plan_id=_pid("a"), target_version=FAILED_TARGET
    )
    _write_record(
        plan,
        "unknown",
        "INSTALL_READY_TIMEOUT",
        updated_at=TIME_1200,
    )
    coordinator = _coordinator(tmp_path)
    state = coordinator.state()
    assert state["install_available"] is False
    assert state["install_state"] == "needs_review"
    assert state["last_install_failure"] is None


def test_live_helper_blocks_and_suppresses_old_failure(tmp_path):
    plan = _make_plan(
        tmp_path, plan_id=_pid("a"), target_version=FAILED_TARGET
    )
    _write_failed(plan, updated_at=TIME_1200)
    update_install.write_helper_process(plan)
    coordinator = _coordinator(tmp_path)
    state = coordinator.state()
    assert state["install_available"] is False
    assert state["install_state"] == "needs_review"
    assert state["last_install_failure"] is None


def test_repeated_state_has_no_process_or_disk_side_effect(
    tmp_path, monkeypatch
):
    plan = _make_plan(
        tmp_path, plan_id=_pid("a"), target_version=FAILED_TARGET
    )
    _write_failed(plan, updated_at=TIME_1200)
    coordinator = _coordinator(tmp_path)
    assert coordinator.state()["last_install_failure"]["plan_id"] == plan.plan_id
    before = _snapshot(tmp_path)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("state() must not start a process")

    monkeypatch.setattr(update_install.subprocess, "Popen", forbidden)
    for _ in range(4):
        summary = coordinator.state()["last_install_failure"]
        assert summary is not None
        assert summary["plan_id"] == plan.plan_id
    assert _snapshot(tmp_path) == before


def test_normal_prepare_is_not_blocked_or_pinned_by_old_failure(
    tmp_path, monkeypatch
):
    old = _make_plan(
        tmp_path, plan_id=_pid("a"), target_version=FAILED_TARGET
    )
    _write_failed(old, updated_at=TIME_1200)
    coordinator = _coordinator(tmp_path)
    assert coordinator.install_available() is True
    assert coordinator.state()["last_install_failure"]["plan_id"] == old.plan_id

    new_plan = _make_plan(
        tmp_path / "prepared",
        plan_id=_pid("b"),
        target_version=NEWER_TARGET,
    )
    payload = {
        "manifest": object(),
        "metadata_raw": b"{}",
        "staging_dir": tmp_path / "updates" / "staging" / "download",
        "package_zip": tmp_path / "updates" / "staging" / "download" / "package.zip",
    }

    class Manager:
        def install_payload(self):
            return payload

    monkeypatch.setattr(
        update_install, "build_install_plan", lambda **_kwargs: new_plan
    )
    monkeypatch.setattr(coordinator, "_start_helper", lambda: None)
    result = coordinator.prepare_from_manager(Manager())
    assert result["accepted"] is True
    assert result["state"] == "pending"
    state = coordinator.state()
    assert state["install_plan_id"] == new_plan.plan_id
    assert state["last_install_failure"] is None
