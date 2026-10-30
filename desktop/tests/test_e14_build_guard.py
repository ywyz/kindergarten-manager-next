"""E14 build guard / freeze order / identity / licence regressions.

All write-plan tests are side-effect free: rejected plans must exit before
``build_frontend``/``build_package`` are called. The order/mid-change tests
monkeypatch the real build steps and use a temporary repository root, so no
frontend, package, old build root or source file is written.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

import build_e14
import update_identity

REPO = build_e14.d0_paths.REPO_ROOT


def _run(monkeypatch, argv: list[str]):
    monkeypatch.setattr(sys, "argv", ["build_e14.py", *argv])
    return build_e14.main()


def _freeze(files: list[dict], digest: str) -> dict:
    return {
        "commit": "synthetic",
        "generated_at": "2026-10-28T00:00:00+00:00",
        "python": "3.14.7",
        "groups": {},
        "file_count": len(files),
        "digest": digest,
        "files": files,
    }


def _plan_paths(root: Path) -> dict:
    build_root = root / "build" / "desktop-e14-r03-test"
    return {
        "build_root": build_root,
        "dist_root": build_root / "package",
        "work_dir": build_root / "pyinstaller-work",
        "spec_dir": build_root / "spec",
        "package_root": build_root / "package" / build_e14.APP_NAME,
    }


def test_check_paths_accepts_independent_root(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    monkeypatch.setattr(build_e14.d0_paths, "REPO_ROOT", repo)
    paths = _plan_paths(repo)
    assert (
        _run(monkeypatch, ["--check-paths", "--build-root", str(paths["build_root"])])
        == 0
    )


@pytest.mark.parametrize(
    "argv",
    [
        ["--build-root", str(REPO)],
        ["--build-root", str(REPO / "build")],
        ["--build-root", str(REPO / "build" / "desktop-e14")],
        ["--build-root", str(REPO / "build" / "desktop-e14-r02")],
        ["--build-root", str(REPO / "build" / "desktop-d2-manual-ai")],
        ["--build-root", str(REPO / "frontend")],
        ["--dist-root", str(REPO / "build" / "desktop-e14-r03" / ".." / "outside")],
        ["--hash-out", str(REPO / "frontend" / "guard.json")],
        ["--hash-out", str(REPO)],
        ["--source-freeze-out", str(REPO / "backend" / "guard.json")],
        ["--hash-out", str(REPO / "build" / "desktop-e14-r03" / "guard.json")],
    ],
)
def test_rejects_bad_write_plan_before_any_build(monkeypatch, argv):
    calls: list[str] = []

    def fake_frontend(*args, **kwargs):
        calls.append("frontend")

    def fake_package(*args, **kwargs):
        calls.append("package")

    monkeypatch.setattr(build_e14, "build_frontend", fake_frontend)
    monkeypatch.setattr(build_e14, "build_package", fake_package)
    with pytest.raises(SystemExit):
        _run(monkeypatch, argv)
    assert calls == []


@pytest.mark.parametrize("target", ["dist-root", "work-dir", "spec-dir", "package-root"])
def test_rejects_read_only_frontend_overlapping_write_root(monkeypatch, tmp_path, target):
    repo = tmp_path / "repo"
    monkeypatch.setattr(build_e14.d0_paths, "REPO_ROOT", repo)
    paths = _plan_paths(repo)
    frontend = {
        "dist-root": paths["dist_root"] / "input-frontend",
        "work-dir": paths["work_dir"] / "input-frontend",
        "spec-dir": paths["spec_dir"] / "input-frontend",
        "package-root": paths["package_root"] / "_internal" / "frontend",
    }[target]
    with pytest.raises(SystemExit):
        build_e14.validate_write_plan(
            build_root=paths["build_root"],
            frontend=frontend,
            dist_root=paths["dist_root"],
            work_dir=paths["work_dir"],
            spec_dir=paths["spec_dir"],
            hash_out=None,
            source_freeze_out=None,
            frontend_is_input=True,
        )


def test_rejects_existing_candidate_package_without_writing(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    monkeypatch.setattr(build_e14.d0_paths, "REPO_ROOT", repo)
    paths = _plan_paths(repo)
    paths["package_root"].mkdir(parents=True)
    before = sorted(str(path.relative_to(repo)) for path in repo.rglob("*"))
    with pytest.raises(SystemExit):
        build_e14.validate_write_plan(
            build_root=paths["build_root"],
            frontend=paths["build_root"] / "frontend",
            dist_root=paths["dist_root"],
            work_dir=paths["work_dir"],
            spec_dir=paths["spec_dir"],
            hash_out=None,
            source_freeze_out=None,
            frontend_is_input=False,
        )
    after = sorted(str(path.relative_to(repo)) for path in repo.rglob("*"))
    assert before == after
    plan = build_e14.validate_write_plan(
        build_root=paths["build_root"],
        frontend=paths["build_root"] / "frontend",
        dist_root=paths["dist_root"],
        work_dir=paths["work_dir"],
        spec_dir=paths["spec_dir"],
        hash_out=None,
        source_freeze_out=None,
        frontend_is_input=False,
        refuse_existing_package=False,
    )
    assert plan["package_exists"] is True


def test_main_rejects_read_only_frontend_overlap_before_any_build(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    monkeypatch.setattr(build_e14.d0_paths, "REPO_ROOT", repo)
    paths = _plan_paths(repo)
    calls: list[str] = []
    monkeypatch.setattr(build_e14, "build_frontend", lambda *a, **k: calls.append("frontend"))
    monkeypatch.setattr(build_e14, "build_package", lambda *a, **k: calls.append("package"))
    with pytest.raises(SystemExit):
        _run(
            monkeypatch,
            [
                "--build-root",
                str(paths["build_root"]),
                "--frontend-dir",
                str(paths["package_root"] / "_internal" / "frontend"),
            ],
        )
    assert calls == []
    assert not paths["build_root"].exists()


def test_main_rejects_existing_package_before_any_build(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    monkeypatch.setattr(build_e14.d0_paths, "REPO_ROOT", repo)
    paths = _plan_paths(repo)
    paths["package_root"].mkdir(parents=True)
    input_frontend = tmp_path / "input-frontend"
    input_frontend.mkdir()
    (input_frontend / "d1.html").write_text("synthetic", encoding="utf-8")
    calls: list[str] = []
    monkeypatch.setattr(build_e14, "build_frontend", lambda *a, **k: calls.append("frontend"))
    monkeypatch.setattr(build_e14, "build_package", lambda *a, **k: calls.append("package"))
    with pytest.raises(SystemExit):
        _run(
            monkeypatch,
            [
                "--build-root",
                str(paths["build_root"]),
                "--frontend-dir",
                str(input_frontend),
            ],
        )
    assert calls == []
    assert (paths["package_root"]).is_dir()


def test_rejects_same_hash_and_freeze_output(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    monkeypatch.setattr(build_e14.d0_paths, "REPO_ROOT", repo)
    paths = _plan_paths(repo)
    target = tmp_path / "out" / "same.json"
    with pytest.raises(SystemExit):
        _run(
            monkeypatch,
            [
                "--build-root",
                str(paths["build_root"]),
                "--hash-out",
                str(target),
                "--source-freeze-out",
                str(target),
            ],
        )


def _fake_main_env(monkeypatch, tmp_path, *, change_mid_build: bool):
    repo = tmp_path / "repo"
    monkeypatch.setattr(build_e14.d0_paths, "REPO_ROOT", repo)
    paths = _plan_paths(repo)
    calls: list[str] = []
    before_files = [{"path": "desktop/product.py", "sha256": "a" * 64, "size": 1}]
    after_files = [
        {
            "path": "desktop/product.py",
            "sha256": ("b" if change_mid_build else "a") * 64,
            "size": 1,
        }
    ]
    freezes = [_freeze(before_files, "before"), _freeze(after_files, "after")]

    def fake_freeze():
        calls.append("freeze_before" if len(calls) == 0 else "freeze_after")
        return freezes.pop(0)

    def fake_frontend(frontend):
        calls.append("frontend")

    def fake_package(dist_root, frontend, work_dir, spec_dir):
        calls.append("package")
        package = Path(dist_root) / build_e14.APP_NAME
        package.mkdir(parents=True)
        return package

    def fake_metadata(package, build_id, digest, pruned=0):
        calls.append("metadata")
        return {
            "build_id": build_id,
            "version": "0.1.0",
            "database_revision": build_e14.DATABASE_REVISION,
        }

    monkeypatch.setattr(build_e14, "source_freeze", fake_freeze)
    monkeypatch.setattr(build_e14, "build_frontend", fake_frontend)
    monkeypatch.setattr(build_e14, "build_package", fake_package)
    monkeypatch.setattr(build_e14, "install_package_metadata", fake_metadata)
    monkeypatch.setattr(build_e14, "require_pillow_license", lambda: None)
    return paths, calls


def test_freeze_runs_before_vite_and_after_metadata(monkeypatch, tmp_path):
    paths, calls = _fake_main_env(monkeypatch, tmp_path, change_mid_build=False)
    rc = _run(
        monkeypatch,
        [
            "--build-root",
            str(paths["build_root"]),
            "--hash-out",
            str(tmp_path / "out" / "hash.json"),
            "--source-freeze-out",
            str(tmp_path / "out" / "freeze.json"),
        ],
    )
    assert rc == 0
    assert calls == [
        "freeze_before",
        "frontend",
        "package",
        "metadata",
        "freeze_after",
    ]
    freeze = json.loads((tmp_path / "out" / "freeze.json").read_text(encoding="utf-8"))
    assert freeze["stable"] is True


def test_source_change_mid_build_is_rejected(monkeypatch, tmp_path):
    paths, calls = _fake_main_env(monkeypatch, tmp_path, change_mid_build=True)
    with pytest.raises(SystemExit):
        _run(
            monkeypatch,
            [
                "--build-root",
                str(paths["build_root"]),
                "--hash-out",
                str(tmp_path / "out" / "hash.json"),
                "--source-freeze-out",
                str(tmp_path / "out" / "freeze.json"),
            ],
        )
    assert calls == [
        "freeze_before",
        "frontend",
        "package",
        "metadata",
        "freeze_after",
    ]
    freeze = json.loads((tmp_path / "out" / "freeze.json").read_text(encoding="utf-8"))
    assert freeze["stable"] is False
    assert not (tmp_path / "out" / "hash.json").exists()


def test_missing_pillow_license_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(build_e14, "PILLOW_LICENSE", tmp_path / "missing-LICENSE")
    with pytest.raises(SystemExit):
        build_e14.require_pillow_license()


def test_missing_pillow_plugin_fails(monkeypatch, tmp_path):
    package = tmp_path / "KGNext-E14"
    (package / "_internal" / "PIL").mkdir(parents=True)
    license_file = tmp_path / "LICENSE"
    license_file.write_text("synthetic license", encoding="utf-8")
    monkeypatch.setattr(build_e14, "PILLOW_LICENSE", license_file)
    with pytest.raises(SystemExit):
        build_e14.install_package_metadata(package, str(uuid.uuid4()), "d" * 64)


def test_build_identity_and_package_info_are_portable(monkeypatch, tmp_path):
    package = tmp_path / "KGNext-E14"
    plugin_dir = package / "_internal" / "PIL"
    plugin_dir.mkdir(parents=True)
    for name in build_e14.PILLOW_REQUIRED_PLUGINS:
        (plugin_dir / name).write_bytes(b"fake-plugin")
    license_file = tmp_path / "LICENSE"
    license_file.write_text("synthetic license", encoding="utf-8")
    monkeypatch.setattr(build_e14, "PILLOW_LICENSE", license_file)

    build_id = str(uuid.uuid4())
    info = build_e14.install_package_metadata(package, build_id, "f" * 64)
    assert info["build_id"] == build_id
    assert info["version"] == "0.1.0"
    assert info["database_revision"] == build_e14.DATABASE_REVISION
    assert info["package"] == "KGNext-E14"
    identity_path = package / "_internal" / "build_identity.json"
    assert identity_path.is_file()
    identity = update_identity.load_app_identity(
        database_revision=build_e14.DATABASE_REVISION,
        path=identity_path,
        require_packaged=True,
    )
    assert identity is not None
    assert identity.build_id == build_id
    assert identity.build_id != update_identity.SOURCE_BUILD_ID
    assert identity.database_revision == "20261025_0006_local_game_observations"
    payload = json.loads(identity_path.read_text(encoding="utf-8"))
    assert payload["app_id"] == update_identity.APP_ID
    assert payload["package_format"] == update_identity.PACKAGE_FORMAT


def test_source_freeze_and_archive_cover_github_update_module():
    assert "desktop/update_github.py" in build_e14.SOURCE_GROUPS["product"]
    freeze = build_e14.source_freeze()
    normalized = {item["path"].replace("\\", "/") for item in freeze["files"]}
    assert "desktop/update_github.py" in normalized
    import verify_e14_package

    assert "update_github" in verify_e14_package.ARCHIVE_REQUIRED_MODULES
