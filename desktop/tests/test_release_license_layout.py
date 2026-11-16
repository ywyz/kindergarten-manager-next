"""Compact license layout and managed Windows path-budget regressions.

All writes stay in pytest temporary directories. No real stage, signing,
installer, EXE, Git or network operation is used.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import release_license_layout as layout


def _source(tmp_path: Path, relative: str, data: bytes, *, package: str = "pkg",
            version: str = "1.0.0", ecosystem: str = "python",
            source_url: str = "https://pypi.org/project/pkg/1.0.0/"):
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return layout.LicenseTextSource(
        ecosystem=ecosystem,
        package=package,
        version=version,
        source_relative_path=f"python/{package}-{version}/{Path(relative).name}",
        source_path=path,
        source_url=source_url,
    )


def test_fixed_length_id_is_deterministic_and_path_sensitive():
    first = layout.canonical_text_id("python", "pkg", "1.0.0", "python/pkg-1.0.0/LICENSE")
    second = layout.canonical_text_id("python", "pkg", "1.0.0", "python/pkg-1.0.0/COPYING")
    assert len(first) == layout.TEXT_ID_LENGTH == 32
    assert first == layout.canonical_text_id("python", "pkg", "1.0.0", "python/pkg-1.0.0/LICENSE")
    assert first != second


def test_multi_text_and_duplicate_basenames_are_all_preserved(tmp_path):
    sources = [
        _source(tmp_path, "a/LICENSE", b"alpha\n", package="alpha"),
        _source(tmp_path, "b/LICENSE", b"beta\n", package="beta"),
        _source(tmp_path, "a/LICENSE.txt", b"alpha extra\n", package="alpha"),
    ]
    built = layout.build_compact_layout(sources)
    assert len(built["texts"]) == 3
    assert len({item["id"] for item in built["texts"]}) == 3
    assert len({item["target_relative_path"] for item in built["texts"]}) == 3
    assert {item["source_relative_path"] for item in built["texts"]} == {
        "python/alpha-1.0.0/LICENSE",
        "python/beta-1.0.0/LICENSE",
        "python/alpha-1.0.0/LICENSE.txt",
    }


def test_id_collision_fails_explicitly(tmp_path, monkeypatch):
    sources = [
        _source(tmp_path, "a/LICENSE", b"a", package="alpha"),
        _source(tmp_path, "b/LICENSE", b"b", package="beta"),
    ]
    monkeypatch.setattr(layout, "canonical_text_id", lambda *args: "a" * 32)
    with pytest.raises(layout.LicenseLayoutError, match="collision"):
        layout.build_compact_layout(sources)


def test_missing_and_illegal_sources_fail(tmp_path):
    missing = layout.LicenseTextSource(
        ecosystem="python",
        package="pkg",
        version="1.0.0",
        source_relative_path="python/pkg-1.0.0/LICENSE",
        source_path=tmp_path / "absent" / "LICENSE",
    )
    with pytest.raises(layout.LicenseLayoutError, match="missing"):
        layout.build_compact_layout([missing])
    for rel in ("C:/abs", "\\abs", "/abs", "../escape", "a/./b", "a//b", "a:b"):
        with pytest.raises(layout.LicenseLayoutError):
            layout.canonical_text_id("python", "pkg", "1.0.0", rel)


def test_materialize_roundtrip_is_tamper_evident(tmp_path):
    data = b"\x00\xfflicense\x00bytes\n"
    source = _source(tmp_path, "src/LICENSE", data)
    root = tmp_path / "redistribution"
    built = layout.materialize_compact_layout([source], root)
    report = layout.verify_compact_layout(root, built)
    assert report["text_count"] == 1
    assert report["total_bytes"] == len(data)
    index = json.loads((root / layout.INDEX_NAME).read_text(encoding="utf-8"))
    entry = index["texts"][0]
    assert entry["sha256"] == hashlib.sha256(data).hexdigest()
    assert entry["size"] == len(data)
    assert entry["target_relative_path"] == f"texts/{entry['id']}.txt"
    assert "C:\\" not in json.dumps(index)
    assert index["components"][0]["texts"] == [entry["id"]]

    text_path = root / entry["target_relative_path"]
    text_path.write_bytes(b"tampered")
    with pytest.raises(layout.LicenseLayoutError, match="content differs"):
        layout.verify_compact_layout(root, built)


def test_extra_and_missing_texts_are_rejected(tmp_path):
    source = _source(tmp_path, "src/LICENSE", b"legal")
    root = tmp_path / "redistribution"
    built = layout.materialize_compact_layout([source], root)
    extra = root / "texts" / ("f" * 32 + ".txt")
    extra.write_bytes(b"extra")
    with pytest.raises(layout.LicenseLayoutError, match="extra="):
        layout.verify_compact_layout(root, built)
    extra.unlink()
    (root / built["texts"][0]["target_relative_path"]).unlink()
    with pytest.raises(layout.LicenseLayoutError, match="missing="):
        layout.verify_compact_layout(root, built)


def test_index_one_to_one_and_duplicate_id_rejected(tmp_path):
    source = _source(tmp_path, "src/LICENSE", b"legal")
    root = tmp_path / "redistribution"
    built = layout.materialize_compact_layout([source], root)
    index_path = root / layout.INDEX_NAME
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["texts"].append(dict(index["texts"][0]))
    index_path.write_text(json.dumps(index), encoding="utf-8")
    with pytest.raises(layout.LicenseLayoutError, match="duplicate compact"):
        layout.verify_compact_layout(root)


def test_materialize_rejects_unsafe_output_before_write(tmp_path):
    source = _source(tmp_path, "src/LICENSE", b"legal")
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        link = None
    if link is not None:
        with pytest.raises(layout.LicenseLayoutError, match="reparse"):
            layout.materialize_compact_layout([source], link / "redistribution")
        assert not (real / "redistribution").exists()
    with pytest.raises(layout.LicenseLayoutError, match="'\\.\\.'"):
        layout.materialize_compact_layout(
            [source], tmp_path / "nested" / ".." / "redistribution"
        )
    assert not (tmp_path / "redistribution").exists()


def test_tampered_index_provenance_is_rejected(tmp_path):
    source = _source(tmp_path, "src/LICENSE", b"legal")
    root = tmp_path / "redistribution"
    layout.materialize_compact_layout([source], root)
    index_path = root / layout.INDEX_NAME
    original = json.loads(index_path.read_text(encoding="utf-8"))

    tampered = json.loads(json.dumps(original))
    tampered["texts"][0]["package"] = "evil"
    index_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(layout.LicenseLayoutError, match="provenance"):
        layout.verify_compact_layout(root)

    tampered = json.loads(json.dumps(original))
    tampered["components"][0]["source"] = "https://evil.invalid/pkg"
    index_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(layout.LicenseLayoutError, match="component metadata"):
        layout.verify_compact_layout(root)

    tampered = json.loads(json.dumps(original))
    tampered["texts"][0]["source_url"] = "C:\\secret\\LICENSE"
    index_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(layout.LicenseLayoutError, match="HTTPS"):
        layout.verify_compact_layout(root)


def test_materialize_rejects_lstat_attribute_errors_before_write(tmp_path, monkeypatch):
    source = _source(tmp_path, "src/LICENSE", b"legal")
    target = tmp_path / "redistribution"

    def denied(path):
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(layout.os, "lstat", denied)
    with pytest.raises(layout.LicenseLayoutError, match="cannot inspect path attributes"):
        layout.materialize_compact_layout([source], target)
    assert not target.exists()


def test_materialize_rejects_lstat_io_error_before_write(tmp_path, monkeypatch):
    source = _source(tmp_path, "src/LICENSE", b"legal")
    target = tmp_path / "redistribution"

    def io_error(path):
        raise OSError(5, "I/O error", str(path))

    monkeypatch.setattr(layout.os, "lstat", io_error)
    with pytest.raises(layout.LicenseLayoutError, match="cannot inspect path attributes"):
        layout.materialize_compact_layout([source], target)
    assert not target.exists()


def test_materialize_allows_genuinely_missing_target(tmp_path):
    source = _source(tmp_path, "src/LICENSE", b"legal")
    target = tmp_path / "not-created-yet" / "redistribution"
    layout.materialize_compact_layout([source], target)
    assert (target / layout.INDEX_NAME).is_file()


def test_materialize_refuses_existing_output_and_absolute_index(tmp_path):
    root = tmp_path / "redistribution"
    source = _source(tmp_path, "src/LICENSE", b"legal")
    layout.materialize_compact_layout([source], root)
    with pytest.raises(layout.LicenseLayoutError, match="already exists"):
        layout.materialize_compact_layout([source], root)
    index = json.loads((root / layout.INDEX_NAME).read_text(encoding="utf-8"))
    for item in index["texts"]:
        assert item["source_relative_path"].startswith("python/")
        assert not item["target_relative_path"].startswith(("/", "\\"))
    assert "C:\\" not in json.dumps(index)
    assert "/Users/" not in json.dumps(index)


def test_reparse_ancestor_is_rejected(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")
    with pytest.raises(layout.LicenseLayoutError, match="reparse"):
        layout.assert_no_reparse_ancestors(link / "LICENSE")


def test_roots_98_and_126_cover_compact_tree_and_managed_layouts(tmp_path):
    sources = [
        _source(tmp_path, "app/LICENSE", b"app", ecosystem="application", package="KGM", version="0.1.0"),
        _source(tmp_path, "cpython/LICENSE", b"cpython", ecosystem="cpython", package="CPython", version="3.14.10"),
        _source(tmp_path, "python/LICENSE", b"python", package="pkg", version="1.0.0"),
        _source(tmp_path, "npm/LICENSE", b"npm", ecosystem="npm", package="@scope/pkg", version="1.2.3"),
    ]
    root = tmp_path / "redistribution"
    built = layout.materialize_compact_layout(sources, root)
    relative_files = [
        "licenses/redistribution/components.json",
        *(
            f"licenses/redistribution/{entry['target_relative_path']}"
            for entry in built["texts"]
        ),
        "licenses/Pillow-LICENSE.txt",
        "KindergartenManager.exe",
        "_internal/update_release.json",
        "_internal/build_identity.json",
        "package-info.json",
    ]

    supported = layout.assert_managed_paths(layout.synthetic_install_root(98), relative_files)
    assert supported["ok"] is True
    assert supported["checked_files"] == len(relative_files) * len(layout.MANAGED_LAYOUTS)
    assert supported["within_supported_root_budget"] is True
    assert supported["violations"] == []

    regression = layout.assert_verify_prefix(layout.synthetic_install_root(126), relative_files)
    assert regression["ok"] is True
    assert regression["verify_prefix_units"] == 126
    assert "not a ZIP extraction result" in regression["support_note"]


def test_old_license_path_is_rejected_at_126_verify_prefix():
    old_relative = (
        "licenses/redistribution/python/pyinstaller-hooks-contrib-2026.9/"
        "pyinstaller_hooks_contrib-2026.9.dist-info/licenses/LICENSE"
    )
    report = layout.audit_verify_prefix(layout.synthetic_install_root(126), [old_relative])
    assert report["ok"] is False
    file_violations = [item for item in report["violations"] if item["kind"] == "file"]
    assert file_violations
    assert file_violations[0]["units"] >= 260


def test_reproduces_old_270_and_accepts_compact_at_126_verify_prefix():
    entry_143 = "x" * 143
    old = layout.audit_managed_paths(
        layout.synthetic_install_root(126),
        [entry_143],
        layouts=(("verify-prefix", ""),),
    )
    old_files = [item for item in old["violations"] if item["kind"] == "file"]
    assert old_files and old_files[0]["units"] == 270
    compact_relative = "licenses/redistribution/texts/" + "a" * 32 + ".txt"
    compact = layout.assert_verify_prefix(
        layout.synthetic_install_root(126), [compact_relative]
    )
    assert compact["ok"] is True


def test_view_limits_use_utf16_units():
    assert layout.utf16_units("abc") == 3
    assert layout.utf16_units("😀") == 2
    assert layout.utf16_units("中文") == 2


def test_directory_exact_247_248_boundary_and_parent_logic():
    allowed = layout.audit_managed_paths(
        layout.synthetic_install_root(247),
        ["a"],
        layouts=(("boundary", ""),),
    )
    assert allowed["ok"] is True
    rejected = layout.audit_managed_paths(
        layout.synthetic_install_root(248),
        ["a"],
        layouts=(("boundary", ""),),
    )
    assert rejected["ok"] is False
    assert any(item["kind"] == "directory" for item in rejected["violations"])
    assert not any(item["kind"] == "file" for item in rejected["violations"])
    parent_rejected = layout.audit_managed_paths(
        layout.synthetic_install_root(246),
        ["b"],
        layouts=(("parent-directory", "a/"),),
    )
    assert parent_rejected["ok"] is False
    assert any(item["kind"] == "directory" for item in parent_rejected["violations"])
    assert not any(item["kind"] == "file" for item in parent_rejected["violations"])
    assert layout.MAX_DIRECTORY_UTF16_UNITS == 247


def test_100_unit_install_root_is_explicitly_unsupported():
    with pytest.raises(layout.PathBudgetError, match="supported"):
        layout.assert_root_supported(layout.synthetic_install_root(100))
    migration = (
        "_internal/migrations_local/versions/"
        "20261109_0017_local_curriculum_deliberations.py"
    )
    at_100 = layout.audit_managed_paths(layout.synthetic_install_root(100), [migration])
    assert at_100["ok"] is False
    assert any(item["kind"] == "file" for item in at_100["violations"])
    at_98 = layout.assert_managed_paths(layout.synthetic_install_root(98), [migration])
    assert at_98["ok"] is True
    long_root = layout.synthetic_install_root(127)
    assert layout.audit_managed_paths(long_root, ["a.txt"])["within_supported_root_budget"] is False
    with pytest.raises(layout.PathBudgetError, match="beyond the supported"):
        layout.assert_root_supported(long_root)
    with pytest.raises(layout.PathBudgetError, match="beyond the supported"):
        layout.assert_root_supported(layout.synthetic_install_root(100))
