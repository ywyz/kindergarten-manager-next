"""E14 build guard / freeze order / identity / licence regressions.

All write-plan tests are side-effect free: rejected plans must exit before
``build_frontend``/``build_package`` are called. The order/mid-change tests
monkeypatch the real build steps and use a temporary repository root, so no
frontend, package, old build root or source file is written.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import build_e14
import update_identity
import verify_e14_package
import verify_e14_portable_archive

REPO = build_e14.d0_paths.REPO_ROOT

RENDERER_PRODUCT_SOURCES = (
    "desktop/renderer_recovery.py",
    "desktop/renderer_recovery_native.py",
)
RENDERER_VERIFICATION_SOURCES = (
    "desktop/verify_renderer_recovery_window.py",
    "desktop/tests/test_renderer_recovery_verifier.py",
)


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


_HOOK_PROBE_BODY = """
import json
import os
from pathlib import Path

import e14_online_integration_test_hook
import app.local.prompt_package as prompt_package
import app.local.runtime as runtime
import app.local.sqlite as sqlite

result = {
    "dotenv": os.environ.get("APP_DISABLE_DOTENV"),
    "origin": os.environ.get("APP_COLLABORATION_API_ORIGIN"),
    "data": os.environ.get("KGM_LOCAL_DATA_DIR"),
    "d0": os.environ.get("KGM_D0_DATA_DIR"),
    "db_path": os.environ.get("KGM_LOCAL_DB_PATH"),
    "frontend": os.environ.get("KGM_D1_FRONTEND_DIR"),
    "source": prompt_package.PACKAGED_SOURCE_URL,
    "key_id": prompt_package.PACKAGED_KEY_ID,
    "public_key": prompt_package.PACKAGED_PUBLIC_KEY_B64,
    "channel": prompt_package.PACKAGED_CHANNEL,
    "default_data": str(sqlite.default_data_dir()),
    "credential": str(runtime._default_credential_root()),
}
print(json.dumps(result, ensure_ascii=False, sort_keys=True))
"""


_HOOK_EXPLICIT_ROOTS_BODY = """
import json
import os
from pathlib import Path

import e14_online_integration_test_hook
from app.local.runtime import LocalRuntime

runtime = LocalRuntime(
    Path(os.environ["EXPLICIT_DATA"]),
    credential_root=Path(os.environ["EXPLICIT_CREDENTIAL"]),
)
print(json.dumps({
    "data": str(runtime.data_dir),
    "credential": str(runtime.credential_root),
}, ensure_ascii=False, sort_keys=True))
"""


def _hook_probe(
    tmp_path: Path,
    body: str,
    *,
    updates: dict[str, str | None],
) -> dict:
    env = os.environ.copy()
    for name in (
        "LOCALAPPDATA",
        "USERPROFILE",
        "HOME",
        "KGM_LOCAL_DATA_DIR",
        "KGM_LOCAL_DB_PATH",
        "KGM_D0_DATA_DIR",
        "KGM_D1_FRONTEND_DIR",
        "APP_DISABLE_DOTENV",
        "APP_COLLABORATION_API_ORIGIN",
    ):
        env.pop(name, None)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(REPO / "backend"), str(REPO / "desktop")]
    )
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["USERPROFILE"] = str(tmp_path / "home")
    env["HOME"] = str(tmp_path / "home")
    for name, value in updates.items():
        if value is None:
            env.pop(name, None)
        else:
            env[name] = value
    completed = subprocess.run(
        [sys.executable, "-c", body],
        cwd=REPO,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


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


def _fake_main_env(
    monkeypatch,
    tmp_path,
    *,
    change_mid_build: bool,
    package_kwargs: list[dict] | None = None,
):
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

    def fake_package(dist_root, frontend, work_dir, spec_dir, **kwargs):
        calls.append("package")
        if package_kwargs is not None:
            package_kwargs.append(dict(kwargs))
        package = Path(dist_root) / build_e14.APP_NAME
        package.mkdir(parents=True)
        return package

    def fake_metadata(package, build_id, digest, pruned=0, **kwargs):
        calls.append("metadata")
        return {
            "build_id": build_id,
            "version": kwargs.get("release_version", "0.1.0"),
            "channel": kwargs.get("release_channel", "stable"),
            "database_revision": kwargs.get("migration_head", "m"),
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


def test_main_accepts_preview_release_identity(monkeypatch, tmp_path):
    paths, calls = _fake_main_env(monkeypatch, tmp_path, change_mid_build=False)
    version = "1.2.3-listening-test.4"
    rc = _run(
        monkeypatch,
        [
            "--build-root",
            str(paths["build_root"]),
            "--hash-out",
            str(tmp_path / "out" / "hash.json"),
            "--source-freeze-out",
            str(tmp_path / "out" / "freeze.json"),
            "--version",
            version,
            "--channel",
            "preview",
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
    freeze = json.loads(
        (tmp_path / "out" / "freeze.json").read_text(encoding="utf-8")
    )
    assert freeze["version"] == version
    assert freeze["channel"] == "preview"
    assert (
        freeze["database_revision"]
        == verify_e14_package.discover_migration_chain(
            build_e14.MIGRATIONS_DIR
        )["head_revision"]
    )


@pytest.mark.parametrize(
    "argv",
    (
        [],
        ["--version", "1.2.3"],
        ["--channel", "preview"],
        ["--version", "1.2.3", "--channel", "stable"],
        ["--version", "1.2.3-listening-test.1", "--channel", "stable"],
        ["--version", "1.2.3", "--channel", "preview"],
    ),
)
def test_online_integration_test_requires_explicit_preview_identity(
    monkeypatch, tmp_path, argv
):
    repo = tmp_path / "repo"
    monkeypatch.setattr(build_e14.d0_paths, "REPO_ROOT", repo)
    paths = _plan_paths(repo)
    calls: list[str] = []
    monkeypatch.setattr(
        build_e14, "build_frontend", lambda *a, **k: calls.append("frontend")
    )
    monkeypatch.setattr(
        build_e14, "build_package", lambda *a, **k: calls.append("package")
    )
    assert (
        _run(
            monkeypatch,
            [
                "--build-root",
                str(paths["build_root"]),
                "--online-integration-test",
                *argv,
            ],
        )
        == 2
    )
    assert calls == []


def test_online_integration_test_passes_fixed_runtime_hook(
    monkeypatch, tmp_path
):
    package_kwargs: list[dict] = []
    paths, calls = _fake_main_env(
        monkeypatch,
        tmp_path,
        change_mid_build=False,
        package_kwargs=package_kwargs,
    )
    version = "1.2.3-listening-test.4"
    rc = _run(
        monkeypatch,
        [
            "--build-root",
            str(paths["build_root"]),
            "--hash-out",
            str(tmp_path / "out" / "hash.json"),
            "--source-freeze-out",
            str(tmp_path / "out" / "freeze.json"),
            "--online-integration-test",
            "--version",
            version,
            "--channel",
            "preview",
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
    assert package_kwargs == [
        {"runtime_hook": build_e14.ONLINE_INTEGRATION_TEST_HOOK}
    ]
    freeze = json.loads(
        (tmp_path / "out" / "freeze.json").read_text(encoding="utf-8")
    )
    assert freeze["version"] == version
    assert freeze["channel"] == "preview"


def test_normal_build_passes_no_runtime_hook(monkeypatch, tmp_path):
    package_kwargs: list[dict] = []
    paths, calls = _fake_main_env(
        monkeypatch,
        tmp_path,
        change_mid_build=False,
        package_kwargs=package_kwargs,
    )
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
    assert package_kwargs == [{"runtime_hook": None}]
    assert calls == [
        "freeze_before",
        "frontend",
        "package",
        "metadata",
        "freeze_after",
    ]


def test_online_integration_hook_environment_and_default_roots(tmp_path):
    localappdata = tmp_path / "localappdata"
    bait = tmp_path / "bait" / "KindergartenManager"
    result = _hook_probe(
        tmp_path,
        _HOOK_PROBE_BODY,
        updates={
            "LOCALAPPDATA": str(localappdata),
            "KGM_LOCAL_DATA_DIR": str(bait / "data"),
            "KGM_LOCAL_DB_PATH": str(bait / "kindergarten.db"),
            "KGM_D1_FRONTEND_DIR": str(bait / "frontend"),
        },
    )
    root = localappdata / "KGNextOnlineIntegrationTest"
    assert result["dotenv"] == "1"
    assert result["origin"] == "https://manager-next.ywyz.tech"
    assert result["source"] == "https://manager-next.ywyz.tech"
    assert result["key_id"] == "kgm-it-prompt-20261108"
    assert result["public_key"] == (
        "GOOfY/r1qhE8nxlkEq0OWKuTqyLMiuOSEloTFIAm59U="
    )
    assert result["channel"] == "stable"
    assert Path(result["data"]).resolve() == (root / "data").resolve()
    assert Path(result["d0"]).resolve() == root.resolve()
    assert Path(result["default_data"]).resolve() == (root / "data").resolve()
    assert Path(result["credential"]).resolve() == (
        root / "credentials"
    ).resolve()
    assert result["db_path"] is None
    assert result["frontend"] is None
    for value in (
        result["data"],
        result["d0"],
        result["default_data"],
        result["credential"],
    ):
        assert "KindergartenManager" not in Path(value).parts


def test_online_integration_hook_without_localappdata_stays_isolated(tmp_path):
    result = _hook_probe(
        tmp_path,
        _HOOK_PROBE_BODY,
        updates={"LOCALAPPDATA": None},
    )
    for value in (result["data"], result["default_data"]):
        parts = Path(value).parts
        assert parts[-4:] == (
            "AppData",
            "Local",
            "KGNextOnlineIntegrationTest",
            "data",
        )
        assert "KindergartenManager" not in parts
    assert Path(result["credential"]).parts[-3:] == (
        "Local",
        "KGNextOnlineIntegrationTest",
        "credentials",
    )
    assert "KindergartenManager" not in Path(result["credential"]).parts


def test_online_integration_hook_keeps_explicit_roots_authoritative(tmp_path):
    explicit_data = tmp_path / "explicit-data"
    explicit_credential = tmp_path / "explicit-credentials"
    explicit_data.mkdir()
    explicit_credential.mkdir()
    result = _hook_probe(
        tmp_path,
        _HOOK_EXPLICIT_ROOTS_BODY,
        updates={
            "LOCALAPPDATA": str(tmp_path / "localappdata"),
            "EXPLICIT_DATA": str(explicit_data),
            "EXPLICIT_CREDENTIAL": str(explicit_credential),
        },
    )
    assert Path(result["data"]).resolve() == explicit_data.resolve()
    assert Path(result["credential"]).resolve() == explicit_credential.resolve()


@pytest.mark.parametrize(
    "argv",
    (
        ["--version", "0.1.0"],
        ["--channel", "stable"],
        ["--version", "0.1.0", "--channel", "preview"],
        ["--version", "1.2.3-listening-test.1", "--channel", "stable"],
        ["--version", "01.2.3", "--channel", "stable"],
    ),
)
def test_main_rejects_partial_or_mismatched_release_identity(
    monkeypatch, tmp_path, argv
):
    repo = tmp_path / "repo"
    monkeypatch.setattr(build_e14.d0_paths, "REPO_ROOT", repo)
    paths = _plan_paths(repo)
    calls: list[str] = []
    monkeypatch.setattr(
        build_e14, "build_frontend", lambda *a, **k: calls.append("frontend")
    )
    monkeypatch.setattr(
        build_e14, "build_package", lambda *a, **k: calls.append("package")
    )
    assert (
        _run(monkeypatch, ["--build-root", str(paths["build_root"]), *argv])
        == 2
    )
    assert calls == []


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
    assert info["channel"] == "stable"
    head = verify_e14_package.discover_migration_chain(
        build_e14.MIGRATIONS_DIR
    )["head_revision"]
    assert info["database_revision"] == head
    assert info["migrations"] == verify_e14_package.source_migration_files(
        build_e14.MIGRATIONS_DIR
    )
    assert info["package"] == "KGNext-E14"
    assert info["listening_templates"]
    for relative in build_e14.LISTENING_TEMPLATE_REQUIRED_FILES:
        assert relative in info["listening_templates"]
    identity_path = package / "_internal" / "build_identity.json"
    assert identity_path.is_file()
    identity = update_identity.load_app_identity(
        database_revision=head,
        path=identity_path,
        require_packaged=True,
    )
    assert identity is not None
    assert identity.build_id == build_id
    assert identity.build_id != update_identity.SOURCE_BUILD_ID
    assert identity.channel == "stable"
    assert identity.version == "0.1.0"
    assert identity.database_revision == head
    payload = json.loads(identity_path.read_text(encoding="utf-8"))
    assert payload["app_id"] == update_identity.APP_ID
    assert payload["package_format"] == update_identity.PACKAGE_FORMAT

    info_for_verifier = dict(info)
    info_for_verifier.update({
        "frontend_digest": "c" * 64,
        "frontend_file_count": 1,
        "source_commit": "b" * 40,
    })
    checks = verify_e14_package._package_info_checks(
        info_for_verifier, "KGNext-E14"
    )
    assert checks["metadata_exact"] is True
    without_listening = dict(info_for_verifier)
    without_listening.pop("listening_templates")
    assert (
        verify_e14_package._package_info_checks(
            without_listening, "KGNext-E14"
        )["metadata_exact"]
        is False
    )


def test_release_identity_accepts_default_and_explicit_pairs():
    resolve = verify_e14_package.resolve_release_identity
    assert resolve() == ("0.1.0", "stable")
    assert resolve("0.1.0", "stable") == ("0.1.0", "stable")
    assert resolve("1.2.3", "stable") == ("1.2.3", "stable")
    preview = "1.2.3-listening-test.1"
    assert resolve(preview, "preview") == (preview, "preview")
    assert resolve("1.2.3-listening-test.0", "preview") == (
        "1.2.3-listening-test.0",
        "preview",
    )


@pytest.mark.parametrize(
    ("version", "channel"),
    (
        ("0.1.0", "preview"),
        ("1.2.3-listening-test.1", "stable"),
        ("0.1.0", None),
        (None, "stable"),
        ("", "stable"),
        ("01.2.3", "stable"),
        ("1.0", "stable"),
        ("1.0.0.0", "stable"),
        ("1.0.0-beta", "stable"),
        ("1.2.3-listening-test.01", "preview"),
        ("1.2.3-listening-test", "preview"),
        ("1.2.3", "beta"),
        (123, "stable"),
    ),
)
def test_release_identity_rejects_partial_mismatched_or_illegal(version, channel):
    with pytest.raises(ValueError):
        verify_e14_package.resolve_release_identity(version, channel)


def test_migration_chain_covers_full_linear_history_and_has_one_head():
    chain = verify_e14_package.discover_migration_chain(build_e14.MIGRATIONS_DIR)
    assert chain["files"] == [
        "20261012_0001_local_baseline.py",
        "20261012_0002_local_require_first_revision.py",
        "20261014_0003_local_config_maintenance.py",
        "20261017_0004_local.py",
        "20261023_0005_local_history.py",
        "20261025_0006_local_game_observations.py",
        "20261101_0007_local_weekly_plans.py",
        "20261102_0008_local_weekly_ai.py",
        "20261107_0009_local_listening.py",
        "20261107_0010_local_listening_ai.py",
        "20261108_0011_local_config_ai.py",
        "20261108_0012_local_listening_rotation.py",
        "20261108_0013_local_todos.py",
        "20261108_0014_local_reflection_ai.py",
        "20261108_0015_local_listening_group_notes.py",
        "20261108_0016_local_listening_goal_suggest.py",
        "20261109_0017_local_curriculum_deliberations.py",
        "20261110_0018_local_curriculum_ai.py",
        "20261110_0019_local_directional_revisions.py",
    ]
    assert chain["head_revision"] == "20261110_0019_local_directional_revisions"
    assert chain["head_file"] == "20261110_0019_local_directional_revisions.py"
    assert chain["revisions"][-1] == chain["head_revision"]
    source_files = verify_e14_package.source_migration_files(
        build_e14.MIGRATIONS_DIR
    )
    assert source_files == [
        "env.py",
        *[f"versions/{name}" for name in chain["files"]],
    ]
    assert len(source_files) == 20


def test_source_freeze_contains_every_migration_and_env():
    freeze = build_e14.source_freeze()
    paths = {item["path"].replace("\\", "/") for item in freeze["files"]}
    chain = verify_e14_package.discover_migration_chain(
        build_e14.MIGRATIONS_DIR
    )
    source_files = verify_e14_package.source_migration_files(
        build_e14.MIGRATIONS_DIR
    )
    for relative in source_files:
        assert f"backend/migrations_local/{relative}" in paths
    for filename in chain["files"]:
        assert f"backend/migrations_local/versions/{filename}" in paths
    assert "backend/migrations_local/env.py" in paths
    assert "backend/migrations_local/versions/20261108_0011_local_config_ai.py" in paths
    assert (
        "backend/migrations_local/versions/"
        "20261108_0016_local_listening_goal_suggest.py"
    ) in paths


def _write_synthetic_migration(path: Path, revision: str, down: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"revision = {revision!r}\ndown_revision = {down!r}\n",
        encoding="utf-8",
    )


def test_migration_chain_rejects_missing_middle_fork_and_duplicate(tmp_path):
    versions = tmp_path / "migrations" / "versions"
    _write_synthetic_migration(versions / "a.py", "001", None)
    _write_synthetic_migration(versions / "b.py", "002", "001")
    chain = verify_e14_package.discover_migration_chain(tmp_path / "migrations")
    assert chain["revisions"] == ["001", "002"]
    (versions / "b.py").unlink()
    _write_synthetic_migration(versions / "c.py", "003", "002")
    with pytest.raises(ValueError):
        verify_e14_package.discover_migration_chain(tmp_path / "migrations")

    fork_root = tmp_path / "fork"
    fork_versions = fork_root / "versions"
    _write_synthetic_migration(fork_versions / "a.py", "001", None)
    _write_synthetic_migration(fork_versions / "b.py", "002", "001")
    _write_synthetic_migration(fork_versions / "c.py", "003", "001")
    with pytest.raises(ValueError):
        verify_e14_package.discover_migration_chain(fork_root)

    duplicate_root = tmp_path / "duplicate"
    duplicate_versions = duplicate_root / "versions"
    _write_synthetic_migration(duplicate_versions / "a.py", "001", None)
    _write_synthetic_migration(duplicate_versions / "b.py", "001", None)
    with pytest.raises(ValueError):
        verify_e14_package.discover_migration_chain(duplicate_root)


def _metadata_package(
    tmp_path: Path,
    name: str,
    *,
    version: str | None = None,
    channel: str | None = None,
) -> tuple[Path, dict, str]:
    package = tmp_path / name
    plugin_dir = package / "_internal" / "PIL"
    plugin_dir.mkdir(parents=True)
    for plugin in build_e14.PILLOW_REQUIRED_PLUGINS:
        (plugin_dir / plugin).write_bytes(b"fake-plugin")
    license_file = tmp_path / f"{name}-LICENSE"
    license_file.write_text("synthetic license", encoding="utf-8")
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(build_e14, "PILLOW_LICENSE", license_file)
    build_id = str(uuid.uuid4())
    try:
        info = build_e14.install_package_metadata(
            package,
            build_id,
            "f" * 64,
            release_version=version,
            release_channel=channel,
        )
    finally:
        monkeypatch.undo()
    info = dict(info)
    info.update(
        {
            "frontend_digest": "c" * 64,
            "frontend_file_count": 1,
            "source_commit": "b" * 40,
        }
    )
    return package, info, build_id


def test_preview_metadata_identity_and_directory_checks_agree(tmp_path):
    package, info, _ = _metadata_package(
        tmp_path,
        "preview",
        version="1.2.3-listening-test.1",
        channel="preview",
    )
    assert info["version"] == "1.2.3-listening-test.1"
    assert info["channel"] == "preview"
    checks = verify_e14_package._package_info_checks(info, "KGNext-E14")
    assert checks["metadata_exact"] is True
    identity = verify_e14_package._identity_checks(package, info)
    assert identity["present"] is True
    assert identity["valid"] is True
    assert identity["version"] is True
    assert identity["revision"] is True
    assert identity["matches_package_info"] is True

    stable_package, stable_info, _ = _metadata_package(tmp_path, "stable")
    assert stable_info["version"] == "0.1.0"
    assert stable_info["channel"] == "stable"
    assert (
        verify_e14_package._package_info_checks(stable_info, "KGNext-E14")[
            "metadata_exact"
        ]
        is True
    )
    assert (
        verify_e14_package._identity_checks(stable_package, stable_info)["valid"]
        is True
    )


def test_directory_checks_reject_wrong_identity_version_channel_and_head(tmp_path):
    package, info, _ = _metadata_package(tmp_path, "wrong")
    head = verify_e14_package.discover_migration_chain(
        build_e14.MIGRATIONS_DIR
    )["head_revision"]
    for mutation in (
        {"channel": "preview"},
        {"database_revision": "20261107_0010_local_listening_ai"},
        {"migrations": ["env.py"]},
        {"version": "01.2.3"},
    ):
        changed = dict(info)
        changed.update(mutation)
        assert (
            verify_e14_package._package_info_checks(changed, "KGNext-E14")[
                "metadata_exact"
            ]
            is False
        ), mutation

    for mutation in (
        {"version": "9.9.9"},
        {"version": "1.2.3-listening-test.1", "channel": "preview"},
    ):
        changed = dict(info)
        changed.update(mutation)
        assert (
            verify_e14_package._package_info_checks(changed, "KGNext-E14")[
                "metadata_exact"
            ]
            is True
        ), mutation
        assert (
            verify_e14_package._identity_checks(package, changed)[
                "matches_package_info"
            ]
            is False
        ), mutation

    identity_path = package / "_internal" / "build_identity.json"
    original = json.loads(identity_path.read_text(encoding="utf-8"))
    payload = dict(original)
    payload["version"] = "9.9.9"
    identity_path.write_text(json.dumps(payload), encoding="utf-8")
    identity = verify_e14_package._identity_checks(package, info)
    assert identity["valid"] is False
    assert identity["version"] is False
    assert identity["matches_package_info"] is False
    payload["version"] = info["version"]
    payload["channel"] = "preview"
    identity_path.write_text(json.dumps(payload), encoding="utf-8")
    assert (
        verify_e14_package._identity_checks(package, info)["matches_package_info"]
        is False
    )
    payload["channel"] = info["channel"]
    payload["database_revision"] = "20261107_0010_local_listening_ai"
    identity_path.write_text(json.dumps(payload), encoding="utf-8")
    identity = verify_e14_package._identity_checks(package, info)
    assert identity["revision"] is False
    assert identity["matches_package_info"] is False

    payload = dict(original)
    payload["platform"] = "linux"
    identity_path.write_text(json.dumps(payload), encoding="utf-8")
    identity = verify_e14_package._identity_checks(package, info)
    assert identity["fields_exact"] is False
    assert identity["fields"]["platform"] is False
    assert identity["valid"] is False

    payload = dict(original)
    payload["build_id"] = update_identity.SOURCE_BUILD_ID
    identity_path.write_text(json.dumps(payload), encoding="utf-8")
    identity = verify_e14_package._identity_checks(package, info)
    assert identity["uuid"] is True
    assert identity["not_source_id"] is False
    assert identity["valid"] is False
    assert head == "20261110_0019_local_directional_revisions"


def test_package_info_freeze_commit_contract():
    matches = verify_e14_package.package_info_matches_freeze_commit
    assert matches({"commit": "a" * 40}, {"source_commit": "a" * 40}) is True
    assert matches({"commit": "a" * 40}, {"source_commit": "b" * 40}) is False
    assert matches({"commit": "a" * 40}, {"source_commit": "A" * 40}) is False
    assert matches({"commit": "a" * 40}, {"source_commit": "short"}) is False
    assert matches({}, {"source_commit": "a" * 40}) is False


def test_install_metadata_rejects_partial_or_mismatched_release_identity(tmp_path):
    package = tmp_path / "pkg"
    (package / "_internal" / "PIL").mkdir(parents=True)
    for plugin in build_e14.PILLOW_REQUIRED_PLUGINS:
        (package / "_internal" / "PIL" / plugin).write_bytes(b"fake-plugin")
    license_file = tmp_path / "LICENSE"
    license_file.write_text("synthetic license", encoding="utf-8")
    build_id = str(uuid.uuid4())
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(build_e14, "PILLOW_LICENSE", license_file)
        with pytest.raises(SystemExit):
            build_e14.install_package_metadata(
                package, build_id, "f" * 64, release_version="0.1.0"
            )
        with pytest.raises(SystemExit):
            build_e14.install_package_metadata(
                package,
                build_id,
                "f" * 64,
                release_version="0.1.0",
                release_channel="preview",
            )
        with pytest.raises(SystemExit):
            build_e14.install_package_metadata(
                package,
                build_id,
                "f" * 64,
                release_version="01.2.3",
                release_channel="stable",
            )


def test_directory_freeze_identity_is_stable_and_preview(tmp_path):
    source = Path(verify_e14_package.__file__)
    data = source.read_bytes()
    entry = {
        "path": "desktop/verify_e14_package.py",
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    digest = verify_e14_package._freeze_digest([entry])
    base = {
        "commit": "a" * 40,
        "before": {
            "files": [entry],
            "digest": digest,
            "file_count": 1,
            "generated_at": "2026-11-08T00:00:00+00:00",
        },
        "after": {
            "files": [entry],
            "digest": digest,
            "file_count": 1,
            "generated_at": "2026-11-08T00:10:00+00:00",
        },
        "changes": {"stable": True, "changed": [], "added": [], "removed": []},
        "stable": True,
    }
    package_info = {"built_at": "2026-11-08T01:00:00+00:00"}
    for version, channel in (
        ("0.1.0", "stable"),
        ("1.2.3-listening-test.1", "preview"),
    ):
        report = dict(base, version=version, channel=channel)
        path = tmp_path / f"freeze-{channel}.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        loaded = verify_e14_package._load_freeze(
            path, package_info, "desktop/verify_e14_package.py"
        )
        assert loaded["identity_ok"] is True
        assert loaded["version"] == version
        assert loaded["channel"] == channel
        assert loaded["schema_ok"] is True
        assert verify_e14_package.package_info_matches_freeze_identity(
            loaded, {"version": version, "channel": channel}
        )
        assert not verify_e14_package.package_info_matches_freeze_identity(
            loaded, {"version": "9.9.9", "channel": channel}
        )

    invalid = dict(base, version="01.2.3", channel="stable")
    path = tmp_path / "freeze-invalid.json"
    path.write_text(json.dumps(invalid), encoding="utf-8")
    loaded = verify_e14_package._load_freeze(
        path, package_info, "desktop/verify_e14_package.py"
    )
    assert loaded["identity_ok"] is False
    assert loaded["schema_ok"] is False


def test_directory_resource_checks_require_head_and_exact_migration_tree(tmp_path):
    package = tmp_path / "package"
    bundled = package / "_internal" / "migrations_local"
    shutil.copytree(
        build_e14.MIGRATIONS_DIR,
        bundled,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    resources = verify_e14_package._resource_checks(package)
    assert resources["migrations_match"] is True
    assert resources["migration_0010"] is True
    assert resources["migration_head"] is True

    (bundled / "versions" / "20261108_0012_local_listening_rotation.py").unlink()
    resources = verify_e14_package._resource_checks(package)
    assert resources["migrations_match"] is False
    assert resources["migration_head"] is True

    (
        bundled
        / "versions"
        / verify_e14_package.discover_migration_chain(build_e14.MIGRATIONS_DIR)[
            "head_file"
        ]
    ).unlink()
    resources = verify_e14_package._resource_checks(package)
    assert resources["migration_head"] is False


def test_missing_middle_migration_fails_before_any_build(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    monkeypatch.setattr(build_e14.d0_paths, "REPO_ROOT", repo)
    paths = _portable_plan(repo)
    migrations = tmp_path / "migrations"
    _write_synthetic_migration(migrations / "versions" / "a.py", "001", None)
    _write_synthetic_migration(migrations / "versions" / "c.py", "003", "002")
    monkeypatch.setattr(build_e14, "MIGRATIONS_DIR", migrations)
    monkeypatch.setattr(build_e14, "require_pillow_license", lambda: None)
    calls: list[str] = []
    monkeypatch.setattr(
        build_e14, "build_frontend", lambda *a, **k: calls.append("frontend")
    )
    monkeypatch.setattr(
        build_e14, "build_package", lambda *a, **k: calls.append("package")
    )
    assert _run(monkeypatch, ["--build-root", str(paths["build_root"])]) == 2
    assert calls == []


def test_build_package_excludes_optional_sqlalchemy_cyextensions(monkeypatch, tmp_path):
    commands = []

    def fake_run(command, **kwargs):
        commands.append(list(command))
        package = tmp_path / "dist" / build_e14.APP_NAME
        package.mkdir(parents=True)
        (package / f"{build_e14.APP_NAME}.exe").write_bytes(b"MZ")

    monkeypatch.setattr(build_e14.subprocess, "run", fake_run)
    package = build_e14.build_package(
        tmp_path / "dist",
        tmp_path / "frontend",
        tmp_path / "work",
        tmp_path / "spec",
    )
    assert package == tmp_path / "dist" / build_e14.APP_NAME
    command = commands[0]
    pairs = set(zip(command, command[1:]))
    for module in build_e14.SQLALCHEMY_CYEXTENSION_MODULES:
        assert ("--exclude-module", module) in pairs, module
    separator = build_e14.os_sep()
    assert (
        "--add-data",
        f"{build_e14.LISTENING_TEMPLATE_DIR}{separator}"
        "app/assets/listening_templates",
    ) in pairs
    for module in (
        "app.local.listening_ai_contracts",
        "app.local.listening_ai_inputs",
        "app.local.listening_ai_service",
        "app.local.listening_ai_adoption",
        "app.local.listening_ai_api",
        "app.local.listening_export_service",
        "app.local.listening_export_api",
        "app.local.ai_executor",
        "app.local.ai_worker",
        "app.services.word_export_listening",
    ):
        assert ("--hidden-import", module) in pairs, module


def test_build_package_adds_runtime_hook_only_when_requested(monkeypatch, tmp_path):
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(list(command))
        dist_root = Path(command[command.index("--distpath") + 1])
        package = dist_root / build_e14.APP_NAME
        package.mkdir(parents=True, exist_ok=True)
        (package / f"{build_e14.APP_NAME}.exe").write_bytes(b"MZ")

    monkeypatch.setattr(build_e14.subprocess, "run", fake_run)
    hooked = tmp_path / "dist-hooked"
    normal = tmp_path / "dist-normal"
    build_e14.build_package(
        hooked,
        tmp_path / "frontend",
        tmp_path / "work-hooked",
        tmp_path / "spec-hooked",
        runtime_hook=build_e14.ONLINE_INTEGRATION_TEST_HOOK,
    )
    build_e14.build_package(
        normal,
        tmp_path / "frontend",
        tmp_path / "work-normal",
        tmp_path / "spec-normal",
    )
    hooked_pairs = set(zip(commands[0], commands[0][1:]))
    normal_pairs = set(zip(commands[1], commands[1][1:]))
    assert (
        "--runtime-hook",
        str(build_e14.ONLINE_INTEGRATION_TEST_HOOK.resolve()),
    ) in hooked_pairs
    assert "--runtime-hook" not in normal_pairs
    assert (
        "--runtime-hook",
        str(build_e14.ONLINE_INTEGRATION_TEST_HOOK.resolve()),
    ) not in normal_pairs


def test_source_freeze_covers_online_integration_hook():
    relative = "desktop/e14_online_integration_test_hook.py"
    assert relative in build_e14.SOURCE_GROUPS["build"]
    freeze = build_e14.source_freeze()
    paths = {item["path"].replace("\\", "/") for item in freeze["files"]}
    assert relative in paths


def test_online_integration_readme_is_limited_to_test_build(tmp_path):
    info = {
        "version": "1.2.3-listening-test.4",
        "channel": "preview",
        "build_id": "synthetic-build",
        "database_revision": "synthetic-head",
        "source_commit": "a" * 40,
        "frontend_digest": "b" * 64,
    }
    normal = tmp_path / "normal.txt"
    test = tmp_path / "test.txt"
    build_e14.write_portable_readme(normal, info)
    build_e14.write_portable_readme(
        test, info, online_integration_test=True
    )
    normal_text = normal.read_text(encoding="utf-8")
    test_text = test.read_text(encoding="utf-8")
    assert "KGNextOnlineIntegrationTest" not in normal_text
    assert "KGNextOnlineIntegrationTest" in test_text
    assert (
        "%LOCALAPPDATA%\\KGNextOnlineIntegrationTest\\data" in test_text
    )
    assert (
        "%LOCALAPPDATA%\\KGNextOnlineIntegrationTest\\credentials"
        in test_text
    )
    assert "教师无需填写地址、公钥或切换渠道" in test_text
    assert "不得用于真实教师资料" in test_text


def test_build_package_rejects_reintroduced_sqlalchemy_compiled_extension(monkeypatch, tmp_path):
    def fake_run(command, **kwargs):
        package = tmp_path / "dist" / build_e14.APP_NAME
        extension = (
            package
            / "_internal"
            / "sqlalchemy"
            / "cyextension"
            / "util.cp314-win_amd64.pyd"
        )
        extension.parent.mkdir(parents=True)
        extension.write_bytes(b"policy-blocked")
        (package / f"{build_e14.APP_NAME}.exe").write_bytes(b"MZ")

    monkeypatch.setattr(build_e14.subprocess, "run", fake_run)
    with pytest.raises(SystemExit):
        build_e14.build_package(
            tmp_path / "dist",
            tmp_path / "frontend",
            tmp_path / "work",
            tmp_path / "spec",
        )


def test_sqlalchemy_pure_python_sqlite_crud_fallback(tmp_path):
    script = tmp_path / "pure_sqlalchemy.py"
    script.write_text(
        """
import os
import sys
from pathlib import Path

import sqlalchemy
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.util._has_cy import HAS_CYEXTENSION

assert HAS_CYEXTENSION is False
assert not any(name.startswith("sqlalchemy.cyextension") for name in sys.modules)
db = Path(sys.argv[1])
engine = create_engine(f"sqlite:///{db.as_posix()}")


class Base(DeclarativeBase):
    pass


class Item(Base):
    __tablename__ = "items"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


Base.metadata.create_all(engine)
with Session(engine) as session:
    session.add(Item(name="pure-python"))
    session.commit()
    assert session.scalars(select(Item)).one().name == "pure-python"
with engine.begin() as connection:
    assert connection.execute(text("select count(*) from items")).scalar_one() == 1
print("sqlalchemy", sqlalchemy.__version__)
print("HAS_CYEXTENSION", HAS_CYEXTENSION)
print("sqlite_crud_ok", True)
""",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["DISABLE_SQLALCHEMY_CEXT_RUNTIME"] = "1"
    environment["APP_DISABLE_DOTENV"] = "1"
    completed = subprocess.run(
        [sys.executable, str(script), str(tmp_path / "pure.db")],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, (completed.stdout, completed.stderr)
    assert "HAS_CYEXTENSION False" in completed.stdout
    assert "sqlite_crud_ok True" in completed.stdout


def test_source_freeze_and_archive_cover_github_update_module():
    assert "desktop/update_github.py" in build_e14.SOURCE_GROUPS["product"]
    freeze = build_e14.source_freeze()
    normalized = {item["path"].replace("\\", "/") for item in freeze["files"]}
    assert "desktop/update_github.py" in normalized

    assert "update_github" in verify_e14_package.ARCHIVE_REQUIRED_MODULES


def test_source_freeze_and_archive_cover_renderer_recovery_modules():

    freeze = build_e14.source_freeze()
    by_path = {item["path"]: item["group"] for item in freeze["files"]}
    for relative in RENDERER_PRODUCT_SOURCES:
        assert relative in by_path
        assert by_path[relative] == "product"
    for relative in RENDERER_VERIFICATION_SOURCES:
        assert relative in by_path
        assert by_path[relative] == "verification"

    for name in ("renderer_recovery", "renderer_recovery_native"):
        assert name in verify_e14_package.ARCHIVE_REQUIRED_MODULES
        assert f"desktop/{name}.py" in verify_e14_package.REQUIRED_FREEZE_PATHS
        assert verify_e14_package._module_class(name) == "production"
    assert "verify_renderer_recovery_window" not in verify_e14_package.ARCHIVE_REQUIRED_MODULES
    assert (
        "desktop/verify_renderer_recovery_window.py"
        in verify_e14_package.REQUIRED_FREEZE_PATHS
    )
    assert (
        verify_e14_package._module_class("verify_renderer_recovery_window")
        == "verification_support"
    )


@pytest.mark.parametrize(
    "relative",
    (*RENDERER_PRODUCT_SOURCES, *RENDERER_VERIFICATION_SOURCES),
)
def test_source_freeze_fails_closed_when_renderer_recovery_source_missing(
    tmp_path, monkeypatch, relative
):
    repo = tmp_path / "repo"
    monkeypatch.setattr(build_e14.d0_paths, "REPO_ROOT", repo)
    monkeypatch.setattr(build_e14, "SOURCE_GROUPS", {"product": (relative,)})
    with pytest.raises(SystemExit, match="配置来源缺失"):
        build_e14.source_freeze()


@pytest.mark.parametrize(
    "relative",
    (*RENDERER_PRODUCT_SOURCES, *RENDERER_VERIFICATION_SOURCES),
)
def test_freeze_changes_detects_renderer_recovery_source_change(relative):
    before = _freeze(
        [{"path": relative, "sha256": "a" * 64, "size": 1}], "a"
    )
    after = _freeze(
        [{"path": relative, "sha256": "b" * 64, "size": 1}], "b"
    )
    change = build_e14._freeze_changes(before, after)
    assert change["stable"] is False
    assert change["changed"] == [relative]
    assert change["before_digest"] != change["after_digest"]


# --- C: Windows 11 portable build/static additions ---

def _portable_plan(root: Path) -> dict:
    build_root = root / "build" / "desktop-e14-win11-r01"
    return {
        "build_root": build_root,
        "dist_root": build_root / "package",
        "work_dir": build_root / "pyinstaller-work",
        "spec_dir": build_root / "spec",
        "package_root": build_root / "package" / build_e14.APP_NAME,
        "frontend": build_root / "frontend",
    }


def _portable_required_paths() -> set[str]:
    required = {
        "desktop/maintenance_host.py",
        "desktop/maintenance_lifecycle.py",
        "desktop/renderer_recovery.py",
        "desktop/renderer_recovery_native.py",
        "desktop/verify_renderer_recovery_window.py",
        "desktop/tests/test_renderer_recovery_verifier.py",
        "desktop/d0_db.py",
        "desktop/d0_driver.py",
        "desktop/d0_host_api.py",
        "desktop/d0_server.py",
        "desktop/d0_word.py",
        "frontend/d1.html",
        "frontend/tsconfig.json",
        "desktop/verify_e14_package.py",
        "desktop/verify_e14_portable_archive.py",
        "desktop/tests/test_e14_build_guard.py",
        "desktop/tests/test_windows11_portable_static.py",
        "desktop/check_windows11_target.ps1",
        "backend/app/local/backup_snapshot.py",
        "backend/app/local/backup_barrier.py",
        "backend/app/local/backup_format.py",
        "backend/app/local/backup_fs.py",
        "backend/app/local/backup_validate.py",
        "backend/app/local/backup_zip.py",
        "backend/app/local/restore_service.py",
        "backend/app/local/restore_fs.py",
        "backend/app/local/restore_group.py",
        "backend/app/local/restore_journal.py",
        "backend/app/local/restore_recovery.py",
        "backend/app/local/restore_types.py",
        "backend/app/local/runtime.py",
        "backend/app/local/credentials.py",
        "backend/app/local/config_tokens.py",
    }
    if (REPO / "desktop/requirements-d1.in").is_file():
        required.add("desktop/requirements-d1.in")
    return required


def test_source_freeze_covers_portable_production_inputs():
    freeze = build_e14.source_freeze()
    paths = {item["path"].replace("\\", "/") for item in freeze["files"]}
    missing = sorted(_portable_required_paths() - paths)
    assert not missing, f"source freeze missing portable inputs: {missing}"
    assert all(item["group"] for item in freeze["files"])
    assert all(freeze["groups"].values())
    assert not any("__pycache__" in p or p.endswith((".pyc", ".pyo")) for p in paths)
    assert all("\\" not in item["path"] for item in freeze["files"])
    assert [item["path"] for item in freeze["files"]] == sorted(item["path"] for item in freeze["files"])
    assert freeze["file_count"] == len(freeze["files"])
    assert freeze["digest"] == build_e14._freeze_digest(freeze["files"])

def test_write_plan_requires_fresh_root_and_rejects_existing_output(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    monkeypatch.setattr(build_e14.d0_paths, "REPO_ROOT", repo)
    paths = _portable_plan(repo)
    paths["build_root"].mkdir(parents=True)
    sentinel = paths["build_root"] / "unknown-sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")
    with pytest.raises(SystemExit):
        build_e14.validate_write_plan(
            build_root=paths["build_root"],
            frontend=paths["frontend"],
            dist_root=paths["dist_root"],
            work_dir=paths["work_dir"],
            spec_dir=paths["spec_dir"],
            hash_out=None,
            source_freeze_out=None,
            frontend_is_input=False,
            require_fresh_root=True,
        )
    assert sentinel.read_text(encoding="utf-8") == "keep"

    repo2 = tmp_path / "repo2"
    monkeypatch.setattr(build_e14.d0_paths, "REPO_ROOT", repo2)
    paths2 = _portable_plan(repo2)
    out = tmp_path / "out" / "hash.json"
    out.parent.mkdir(parents=True)
    out.write_text("keep", encoding="utf-8")
    with pytest.raises(SystemExit):
        build_e14.validate_write_plan(
            build_root=paths2["build_root"],
            frontend=paths2["frontend"],
            dist_root=paths2["dist_root"],
            work_dir=paths2["work_dir"],
            spec_dir=paths2["spec_dir"],
            hash_out=out,
            source_freeze_out=None,
            frontend_is_input=False,
            require_fresh_root=True,
        )
    assert out.read_text(encoding="utf-8") == "keep"

def test_invalid_plan_starts_no_process_or_cleanup(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    monkeypatch.setattr(build_e14.d0_paths, "REPO_ROOT", repo)
    paths = _portable_plan(repo)
    calls: list[str] = []
    def forbidden(*args, **kwargs):
        calls.append("forbidden")
        raise AssertionError("forbidden external action")
    monkeypatch.setattr(build_e14.subprocess, "run", forbidden)
    monkeypatch.setattr(build_e14.shutil, "rmtree", forbidden)
    monkeypatch.setattr(build_e14, "build_frontend", lambda *a, **k: calls.append("frontend"))
    monkeypatch.setattr(build_e14, "build_package", lambda *a, **k: calls.append("package"))
    monkeypatch.setattr(build_e14, "source_freeze", lambda: calls.append("freeze"))
    with pytest.raises(SystemExit):
        _run(
            monkeypatch,
            [
                "--build-root",
                str(paths["build_root"]),
                "--dist-root",
                str(tmp_path / "outside"),
            ],
        )
    assert calls == []

def test_freeze_changes_tracks_added_removed_and_empty():
    base = _freeze([{"path": "desktop/a.py", "sha256": "a" * 64, "size": 1}], "a")
    same = _freeze([{"path": "desktop/a.py", "sha256": "a" * 64, "size": 1}], "a")
    assert build_e14._freeze_changes(base, same)["stable"] is True
    added = _freeze(
        [
            {"path": "desktop/a.py", "sha256": "a" * 64, "size": 1},
            {"path": "desktop/b.py", "sha256": "b" * 64, "size": 1},
        ],
        "b",
    )
    change = build_e14._freeze_changes(base, added)
    assert change["stable"] is False and change["added"] == ["desktop/b.py"]
    removed = _freeze([], "c")
    change = build_e14._freeze_changes(base, removed)
    assert change["stable"] is False and change["removed"] == ["desktop/a.py"]
    changed = _freeze([{"path": "desktop/a.py", "sha256": "b" * 64, "size": 1}], "d")
    change = build_e14._freeze_changes(base, changed)
    assert change["stable"] is False and change["changed"] == ["desktop/a.py"]


def test_prune_caches_only_inside_package(tmp_path):
    package = tmp_path / "pkg"
    cache = package / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "x.pyc").write_bytes(b"cache")
    outside = tmp_path / "source-sentinel.txt"
    outside.write_text("keep", encoding="utf-8")
    removed = build_e14.prune_package_caches(package)
    assert not cache.exists()
    assert outside.read_text(encoding="utf-8") == "keep"
    assert all("__pycache__" in item.replace("\\", "/") for item in removed)

def test_missing_migration_fails_before_any_build(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    monkeypatch.setattr(build_e14.d0_paths, "REPO_ROOT", repo)
    paths = _portable_plan(repo)
    monkeypatch.setattr(build_e14, "MIGRATIONS_DIR", tmp_path / "missing-migrations")
    monkeypatch.setattr(build_e14, "require_pillow_license", lambda: None)
    calls: list[str] = []
    monkeypatch.setattr(build_e14, "build_frontend", lambda *a, **k: calls.append("frontend"))
    monkeypatch.setattr(build_e14, "build_package", lambda *a, **k: calls.append("package"))
    assert _run(monkeypatch, ["--build-root", str(paths["build_root"])]) == 2
    assert calls == []


def test_missing_listening_template_fails_before_any_build(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    monkeypatch.setattr(build_e14.d0_paths, "REPO_ROOT", repo)
    paths = _portable_plan(repo)
    monkeypatch.setattr(build_e14, "LISTENING_TEMPLATE_DIR", tmp_path / "missing")
    with pytest.raises(SystemExit):
        build_e14.require_listening_templates()


def test_e14_current_head_listening_and_weekly_modules_are_real_requirements():
    chain = verify_e14_package.discover_migration_chain(build_e14.MIGRATIONS_DIR)
    assert chain["head_revision"] == "20261110_0019_local_directional_revisions"
    assert chain["head_file"] == "20261110_0019_local_directional_revisions.py"
    assert len(chain["files"]) == 19
    assert len(verify_e14_package.source_migration_files(build_e14.MIGRATIONS_DIR)) == 20
    new_modules = {
        "weekly_ai_adoption", "weekly_ai_api", "weekly_ai_candidates",
        "weekly_ai_contracts", "weekly_ai_inputs", "weekly_ai_service",
        "weekly_ai_sources", "weekly_materials",
        "listening_service", "listening_templates", "listening_assets",
        "listening_api", "listening_export_service", "listening_export_api",
        "listening_ai_contracts", "listening_ai_inputs", "listening_ai_service",
        "listening_ai_adoption", "listening_ai_api",
        "ai_executor", "ai_worker", "ai_transport", "ai_spawn",
        "ai_task_service",
    }
    local_modules = {
        name for name in verify_e14_package.ARCHIVE_REQUIRED_MODULES
        if name.startswith("app.local.")
    }
    for name in new_modules:
        assert f"app.local.{name}" in local_modules
        source = REPO / "backend" / "app" / "local" / f"{name}.py"
        assert source.is_file(), name
        assert f"backend/app/local/{name}.py" in verify_e14_package.REQUIRED_FREEZE_PATHS
    assert "app.services.word_export_listening" in verify_e14_package.ARCHIVE_REQUIRED_MODULES
    assert (
        "backend/app/services/word_export_listening.py"
        in verify_e14_package.REQUIRED_FREEZE_PATHS
    )
    for filename in (
        "20261101_0007_local_weekly_plans.py",
        "20261102_0008_local_weekly_ai.py",
        "20261107_0009_local_listening.py",
        "20261107_0010_local_listening_ai.py",
    ):
        assert f"backend/migrations_local/versions/{filename}" in verify_e14_package.REQUIRED_FREEZE_PATHS
    for relative in build_e14.LISTENING_TEMPLATE_REQUIRED_FILES:
        assert (
            f"backend/app/assets/listening_templates/{relative}"
            in verify_e14_package.REQUIRED_FREEZE_PATHS
        )
    for relative in ("manifest.json", *build_e14.LISTENING_TEMPLATE_DOCX):
        assert relative in verify_e14_package.LISTENING_TEMPLATE_REQUIRED_FILES
    assert verify_e14_portable_archive.discover_migration_chain(
        verify_e14_portable_archive.SOURCE_MIGRATIONS
    )["head_revision"] == "20261110_0019_local_directional_revisions"
    freeze = build_e14.source_freeze()
    paths = {item["path"] for item in freeze["files"]}
    for name in new_modules:
        assert f"backend/app/local/{name}.py" in paths
    for relative in build_e14.LISTENING_TEMPLATE_REQUIRED_FILES:
        assert f"backend/app/assets/listening_templates/{relative}" in paths
    for filename in (
        "20261101_0007_local_weekly_plans.py",
        "20261102_0008_local_weekly_ai.py",
        "20261107_0009_local_listening.py",
        "20261107_0010_local_listening_ai.py",
    ):
        assert f"backend/migrations_local/versions/{filename}" in paths