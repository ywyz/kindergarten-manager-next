"""N01: build_d2.py output-path protection (no Vite/PyInstaller runs).

All protected roots are redirected to temporary directories; no real old
frontend/package/human root is touched. The build steps are monkeypatched, so a
rejected run must be rejected *before* any frontend/work/spec/package/hash write.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import build_d2


def _run(monkeypatch, argv: list[str]):
    calls: list[tuple[str, str]] = []

    def fake_frontend(frontend_out: Path, *, reuse: bool) -> None:
        calls.append(("frontend", str(frontend_out)))

    def fake_package(dist_root: Path, frontend_out: Path, work_dir: Path, spec_dir: Path):
        calls.append(("package", f"{dist_root}|{frontend_out}|{work_dir}|{spec_dir}"))
        package_root = Path(dist_root) / build_d2.APP_NAME
        package_root.mkdir(parents=True, exist_ok=True)
        (package_root / "fake.txt").write_text("fake", encoding="utf-8")
        return package_root

    monkeypatch.setattr(build_d2, "build_frontend", fake_frontend)
    monkeypatch.setattr(build_d2, "build_package", fake_package)
    monkeypatch.setattr("sys.argv", ["build_d2.py", *argv])
    result = build_d2.main()
    return result, calls


def _layout(tmp_path: Path, monkeypatch):
    base = tmp_path / "build"
    normal = base / "desktop-d2"
    manual = base / "desktop-d2-manual-ai"
    r01 = base / "desktop-d2-manual-ai-h06-r01"
    for root in (normal, manual, r01):
        (root / "frontend").mkdir(parents=True, exist_ok=True)
        (root / "frontend" / "d1.html").write_text("old", encoding="utf-8")
    monkeypatch.setattr(
        build_d2, "PROTECTED_BUILD_ROOTS", (normal, manual, r01)
    )
    return base, normal, manual, r01


def test_rejects_old_build_root_and_children(tmp_path, monkeypatch):
    base, normal, manual, r01 = _layout(tmp_path, monkeypatch)
    for root in (normal, r01, normal / "sub"):
        with pytest.raises(SystemExit):
            _run(monkeypatch, ["--build-root", str(root)])


def test_rejects_ancestor_of_protected_root(tmp_path, monkeypatch):
    base, normal, manual, r01 = _layout(tmp_path, monkeypatch)
    with pytest.raises(SystemExit):
        _run(monkeypatch, ["--build-root", str(base)])


def test_rejects_old_dist_root_even_with_new_build_root(tmp_path, monkeypatch):
    base, normal, manual, r01 = _layout(tmp_path, monkeypatch)
    with pytest.raises(SystemExit):
        _run(
            monkeypatch,
            [
                "--build-root",
                str(base / "independent"),
                "--dist-root",
                str(r01 / "package"),
            ],
        )


def test_changing_dist_root_cannot_bypass_old_work_and_spec(tmp_path, monkeypatch):
    base, normal, manual, r01 = _layout(tmp_path, monkeypatch)
    with pytest.raises(SystemExit):
        _run(
            monkeypatch,
            [
                "--build-root",
                str(r01),
                "--dist-root",
                str(base / "independent-package"),
            ],
        )


def test_rejects_hash_out_inside_protected_root(tmp_path, monkeypatch):
    base, normal, manual, r01 = _layout(tmp_path, monkeypatch)
    hash_out = normal / "hashes.json"
    with pytest.raises(SystemExit):
        _run(
            monkeypatch,
            [
                "--build-root",
                str(base / "independent"),
                "--hash-out",
                str(hash_out),
            ],
        )
    assert not hash_out.exists()


def test_legal_sibling_build_root_is_allowed(tmp_path, monkeypatch):
    base, normal, manual, r01 = _layout(tmp_path, monkeypatch)
    independent = base / "desktop-d2-normal-r01"
    hash_out = independent / "hashes.json"
    result, calls = _run(
        monkeypatch,
        ["--build-root", str(independent), "--hash-out", str(hash_out)],
    )
    assert result == 0
    assert [kind for kind, _ in calls] == ["frontend", "package"]
    assert hash_out.is_file()


def test_explicit_read_only_old_frontend_is_allowed(tmp_path, monkeypatch):
    base, normal, manual, r01 = _layout(tmp_path, monkeypatch)
    independent = base / "desktop-d2-normal-r01"
    old_frontend = r01 / "frontend"
    result, calls = _run(
        monkeypatch,
        [
            "--build-root",
            str(independent),
            "--frontend-dir",
            str(old_frontend),
        ],
    )
    assert result == 0
    assert [kind for kind, _ in calls] == ["package"]
    assert str(old_frontend.resolve()) in calls[0][1]


def test_read_only_frontend_does_not_whitelist_protected_hash_out(tmp_path, monkeypatch):
    base, normal, manual, r01 = _layout(tmp_path, monkeypatch)
    with pytest.raises(SystemExit):
        _run(
            monkeypatch,
            [
                "--build-root",
                str(base / "independent"),
                "--frontend-dir",
                str(r01 / "frontend"),
                "--hash-out",
                str(r01 / "hashes.json"),
            ],
        )
