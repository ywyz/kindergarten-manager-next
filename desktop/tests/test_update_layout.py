"""Managed layout regressions for the signed-preview updater.

These are source-level synthetic tests: no installer, product package, registry
write, real signature or network is used.  The registry reader is replaced with
an in-memory location so the actual HKCU record is never touched.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import update_helper
import update_install
import update_paths
import test_update_u2 as u2


def _layout(root: Path, *, helper: bool = True) -> Path:
    (root / "app").mkdir(parents=True, exist_ok=True)
    (root / "app" / "KindergartenManager.exe").write_bytes(b"MZ app")
    (root / "updates" / "staging").mkdir(parents=True, exist_ok=True)
    if helper:
        (root / "updater").mkdir(parents=True, exist_ok=True)
        (root / "updater" / "KindergartenManagerUpdater.exe").write_bytes(b"MZ helper")
    return root


def _plan(root: Path, **overrides) -> update_install.InstallPlan:
    values = {
        "schema_version": update_install.PLAN_SCHEMA,
        "plan_id": "p1",
        "nonce": "n1",
        "created_at": "2026-11-11T00:00:00Z",
        "current": {},
        "target": {},
        "old_process": {},
        "data_dir": str(root / "data"),
        "credential_root": str(root / "credentials"),
        "install_root": str(root),
        "install_app_dir": str(root / "app"),
        "backup_dir": str(root / "backups" / "p1"),
        "state_dir": str(root / "install-state" / "p1"),
        "staging_dir": str(root / "updates" / "staging"),
        "package_zip": str(root / "updates" / "staging" / "package.zip"),
        "metadata_path": str(root / "install-state" / "p1" / "metadata.json"),
        "release_config": "",
        "helper_path": str(root / "updater" / "KindergartenManagerUpdater.exe"),
        "new_app_path": str(root / "app" / "KindergartenManager.exe"),
        "new_app_command": [],
    }
    values.update(overrides)
    return update_install.InstallPlan(**values)


def test_registered_custom_root_resolves_and_exposes_managed_layout(monkeypatch, tmp_path):
    root = _layout(tmp_path / "Custom Install")
    monkeypatch.setattr(update_paths, "_registered_location", lambda: root)
    assert update_paths.registered_install_root() == root
    assert update_paths.resolve_install_root(root / "app") == root
    install, app, helper, staging = update_paths.managed_layout(root)
    assert install == root
    assert app == root / "app"
    assert helper == root / "updater" / "KindergartenManagerUpdater.exe"
    assert staging == root / "updates" / "staging"


def test_arbitrary_copied_root_is_not_trusted(monkeypatch, tmp_path):
    root = _layout(tmp_path / "Copied")
    monkeypatch.setattr(update_paths, "_registered_location", lambda: None)
    monkeypatch.setattr(update_paths, "programs_root", lambda: tmp_path / "NoPrograms")
    assert update_paths.resolve_install_root(root / "app") is None


def test_legacy_fixed_root_is_accepted_without_registry(monkeypatch, tmp_path):
    programs = tmp_path / "Programs"
    root = _layout(programs / "KindergartenManager")
    monkeypatch.setattr(update_paths, "_registered_location", lambda: None)
    monkeypatch.setattr(update_paths, "programs_root", lambda: programs)
    assert update_paths.resolve_install_root(root / "app") == root


def test_preview_registration_does_not_steal_legacy_path(monkeypatch, tmp_path):
    programs = tmp_path / "Programs"
    legacy = _layout(programs / "KindergartenManager")
    preview = _layout(programs / "KindergartenManagerSignedPreview")
    monkeypatch.setattr(update_paths, "_registered_location", lambda: preview)
    monkeypatch.setattr(update_paths, "programs_root", lambda: programs)
    assert update_paths.resolve_install_root(legacy / "app") == legacy
    assert update_paths.resolve_install_root(preview / "app") == preview


def _frozen_helper(monkeypatch, root: Path) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        sys, "executable", str(root / "updater" / "KindergartenManagerUpdater.exe")
    )


def test_product_helper_accepts_registered_custom_root(monkeypatch, tmp_path):
    root = _layout(tmp_path / "Custom Install")
    monkeypatch.setattr(update_paths, "_registered_location", lambda: root)
    _frozen_helper(monkeypatch, root)
    update_helper._check_product_layout(_plan(root))


def test_product_helper_rejects_unregistered_or_wrong_entries(monkeypatch, tmp_path):
    root = _layout(tmp_path / "Custom Install")
    monkeypatch.setattr(update_paths, "_registered_location", lambda: None)
    monkeypatch.setattr(update_paths, "programs_root", lambda: tmp_path / "NoPrograms")
    with pytest.raises(update_install.InstallPlanError) as wrong_root:
        update_helper._check_product_layout(_plan(root))
    assert wrong_root.value.code == "INSTALL_PRODUCT_LAYOUT"

    registered = _layout(tmp_path / "Registered")
    monkeypatch.setattr(update_paths, "_registered_location", lambda: registered)
    _frozen_helper(monkeypatch, registered)
    wrong_helper = _plan(
        registered,
        helper_path=str(registered / "app" / "KindergartenManagerUpdater.exe"),
    )
    with pytest.raises(update_install.InstallPlanError) as helper_error:
        update_helper._check_product_layout(wrong_helper)
    assert helper_error.value.code == "INSTALL_PRODUCT_LAYOUT"

    wrong_staging = _plan(
        registered,
        staging_dir=str(tmp_path / "OtherVolume" / "staging"),
    )
    with pytest.raises(update_install.InstallPlanError) as staging_error:
        update_helper._check_product_layout(wrong_staging)
    assert staging_error.value.code == "INSTALL_PRODUCT_LAYOUT"

    copied = _layout(tmp_path / "Copied Helper")
    _frozen_helper(monkeypatch, copied)
    with pytest.raises(update_install.InstallPlanError) as copied_error:
        update_helper._check_product_layout(_plan(registered))
    assert copied_error.value.code == "INSTALL_PRODUCT_LAYOUT"


def test_product_helper_rejects_unsafe_helper_self(monkeypatch, tmp_path):
    root = _layout(tmp_path / "Custom Install")
    monkeypatch.setattr(update_paths, "_registered_location", lambda: root)
    _frozen_helper(monkeypatch, root)
    original = update_paths.is_safe_existing

    def unsafe(path):
        if "KindergartenManagerUpdater.exe" in str(path):
            return False
        return original(path)

    monkeypatch.setattr(update_paths, "is_safe_existing", unsafe)
    with pytest.raises(update_install.InstallPlanError) as error:
        update_helper._check_product_layout(_plan(root))
    assert error.value.code == "INSTALL_PRODUCT_LAYOUT"


def test_custom_root_plan_uses_same_volume_managed_staging(monkeypatch, tmp_path):
    root = _layout(tmp_path / "Custom Install")
    monkeypatch.setattr(update_paths, "_registered_location", lambda: root)
    staging = root / "updates" / "staging"
    archive, metadata, _key, _build = u2._make_package(
        staging, target_revision=u2.HEAD_REV, target_version="0.2.0"
    )
    config = staging / "release.json"
    source = u2._source(config)
    current = u2._identity(u2.HEAD_REV)
    manifest = u2.parse_signed_manifest(
        metadata, source, current.version, current.database_revision
    )
    plan = update_install.build_install_plan(
        identity=current,
        manifest=manifest,
        metadata_raw=metadata,
        staging_dir=staging,
        package_zip=archive,
        data_dir=tmp_path / "data",
        credential_root=tmp_path / "credentials",
        install_root=root,
        app_dir=root / "app",
        helper_command=[str(root / "updater" / "KindergartenManagerUpdater.exe")],
        release_config=config,
        test_only=False,
    )
    assert Path(plan.install_root) == root
    assert Path(plan.install_app_dir) == root / "app"
    assert Path(plan.helper_path) == root / "updater" / "KindergartenManagerUpdater.exe"
    assert Path(plan.staging_dir) == staging


def test_other_volume_staging_is_rejected(monkeypatch, tmp_path):
    root = _layout(tmp_path / "Custom Install")
    monkeypatch.setattr(update_paths, "_registered_location", lambda: root)
    staging = root / "updates" / "staging"
    archive, metadata, _key, _build = u2._make_package(
        staging, target_revision=u2.HEAD_REV, target_version="0.2.0"
    )
    config = staging / "release.json"
    source = u2._source(config)
    current = u2._identity(u2.HEAD_REV)
    manifest = u2.parse_signed_manifest(
        metadata, source, current.version, current.database_revision
    )
    monkeypatch.setattr(update_install, "_same_volume", lambda _left, _right: False)
    with pytest.raises(update_install.InstallPlanError) as error:
        update_install.build_install_plan(
            identity=current,
            manifest=manifest,
            metadata_raw=metadata,
            staging_dir=staging,
            package_zip=archive,
            data_dir=tmp_path / "data",
            credential_root=tmp_path / "credentials",
            install_root=root,
            app_dir=root / "app",
            helper_command=[str(root / "updater" / "KindergartenManagerUpdater.exe")],
            release_config=config,
            test_only=False,
        )
    assert error.value.code == "INSTALL_VOLUME_MISMATCH"


def test_old_preview_without_helper_reports_specific_error(monkeypatch, tmp_path):
    root = _layout(tmp_path / "Old Preview", helper=False)
    monkeypatch.setattr(update_paths, "_registered_location", lambda: root)
    staging = root / "updates" / "staging"
    archive, metadata, _key, _build = u2._make_package(
        staging, target_revision=u2.HEAD_REV, target_version="0.2.0"
    )
    config = staging / "release.json"
    source = u2._source(config)
    current = u2._identity(u2.HEAD_REV)
    manifest = u2.parse_signed_manifest(
        metadata, source, current.version, current.database_revision
    )
    with pytest.raises(update_install.InstallPlanError) as error:
        update_install.build_install_plan(
            identity=current,
            manifest=manifest,
            metadata_raw=metadata,
            staging_dir=staging,
            package_zip=archive,
            data_dir=tmp_path / "data",
            credential_root=tmp_path / "credentials",
            install_root=root,
            app_dir=root / "app",
            release_config=config,
            test_only=False,
        )
    assert error.value.code == "INSTALL_HELPER_MISSING"
