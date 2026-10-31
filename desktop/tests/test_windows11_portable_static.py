"""Independent Windows 11 portable archive/static contract tests.

These tests use real small ZIPs and the contract pure validators. They do not
build, execute the candidate/EXE/helper, extract an untrusted archive, run the
legacy verifier flow, or start the application.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


def _api():
    import verify_e14_portable_archive as archive
    return archive


def _member(name, *, external_attr=0o100644 << 16, flag_bits=0,
            compress_type=zipfile.ZIP_STORED, file_size=1, compress_size=1):
    return {
        "name": name,
        "external_attr": external_attr,
        "flag_bits": flag_bits,
        "compress_type": compress_type,
        "file_size": file_size,
        "compress_size": compress_size,
    }


def test_manifest_path_is_canonical_or_rejected():
    api = _api()
    assert api.validate_manifest_path("a/b.txt") == "a/b.txt"
    for raw in (
        "", ".", "..", "../a", "/abs", "C:/a", "\\\\server\\share",
        "a\\b", "a//b", "a/./b", "a/../b", "a/", "CON", "a./b", "a /b",
        "a:stream", "\x01a",
    ):
        assert api.validate_manifest_path(raw) is None, raw


def test_required_status_rejects_missing_nonbool_and_unknown():
    api = _api()
    required = {"a", "b"}
    ok = api.required_status({"a": True, "b": True}, required, {})
    assert ok["ok"] is True
    assert ok["missing"] == [] and ok["non_bool"] == [] and ok["unknown"] == []
    missing = api.required_status({"a": True}, required, {})
    assert missing["ok"] is False and missing["missing"] == ["b"]
    nonbool = api.required_status({"a": 1, "b": True}, required, {})
    assert nonbool["ok"] is False and nonbool["non_bool"] == ["a"]
    unknown = api.required_status({"a": True, "b": False}, required, {"b": "unreadable"})
    assert unknown["ok"] is False and unknown["unknown"] == ["b"]
    extra = api.required_status({"a": True, "b": True, "z": "unknown"}, required, {})
    assert extra["ok"] is False and extra["non_bool"] == ["z"]

def test_member_names_reject_unsafe_paths_and_collisions():
    api = _api()
    for name in (
        "", ".", "..", "../a", "/abs", "C:/a", "\\\\server\\share",
        "a\\b", "a//b", "a/./b", "a/../b", "a/", "CON", "a./b", "a /b",
        "a:stream", "\x01a",
    ):
        assert api.validate_member_names([_member(name)]), name
    safe = [
        _member("KGNext-E14/KGNext-E14.exe"),
        _member("KGNext-E14/_internal/certifi/cacert.pem"),
        _member("KGNext-E14/licenses/Pillow-LICENSE.txt"),
        _member("README-KGNext-E14-win11-r01.txt"),
    ]
    assert not api.validate_member_names(safe)
    assert api.validate_member_names([
        _member("KGNext-E14/a.txt"), _member("KGNext-E14/A.TXT")
    ])
    assert api.validate_member_names([
        _member("KGNext-E14/a.txt"), _member("KGNext-E14/a.txt")
    ])
    assert api.validate_member_names([
        _member("KGNext-E14/\u00e9.txt"), _member("KGNext-E14/e\u0301.txt")
    ])


def _static_required(api):
    import verify_e14_package as package_verifier
    for module in (api, package_verifier):
        value = getattr(module, "REQUIRED_STATIC_CHECKS", None)
        if value:
            return set(value)
    raise AssertionError("REQUIRED_STATIC_CHECKS is not exported")


def test_required_sets_cover_contract_security_names():
    api = _api()
    archive = set(api.REQUIRED_ARCHIVE_CHECKS)
    exact = {
        "static_no_execution", "zip_no_absolute_paths", "zip_no_backslash",
        "zip_no_duplicate_names", "zip_no_symlinks", "zip_streamed_without_extract",
        "manifest_no_duplicate_keys", "manifest_no_duplicate_paths",
        "archive_sha256_recorded",
    }
    assert exact <= archive
    alternatives = [
        {"zip_no_parent_traversal", "zip_no_parent_segments"},
        {"zip_no_case_collisions", "zip_no_casefold_collisions"},
        {"zip_no_unicode_collisions", "zip_no_normalized_collisions"},
        {"zip_no_encrypted_entries", "zip_no_encrypted_members"},
        {"zip_member_size_bounds", "zip_single_file_limit_ok"},
        {"zip_total_size_bounds", "zip_total_size_limit_ok"},
        {"zip_ratio_bounds", "zip_ratio_limit_ok"},
        {"checksum_lines_valid", "checksums_schema_exact"},
        {"privacy_no_forbidden_entries", "no_private_audit_entries"},
        {"privacy_no_private_keys", "no_private_material"},
    ]
    for names in alternatives:
        assert archive & names, names
    static = _static_required(api)
    assert {
        "static_no_execution", "static_no_production_imports",
        "archive_required_modules_present", "source_freeze_stable",
        "verifier_matches_freeze", "privacy_no_private_keys",
        "signature_not_claimed",
    } <= static
    assert static & {"source_freeze_current_matches", "source_current_matches_freeze"}

def _make_zip(path, entries):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries:
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o100644 << 16
            zf.writestr(info, data)


def test_real_micro_zip_public_ca_positive_and_unsafe_paths(tmp_path):
    api = _api()
    archive = tmp_path / "micro.zip"
    _make_zip(archive, [
        ("KGNext-E14/KGNext-E14.exe", b"MZ"),
        ("KGNext-E14/_internal/certifi/cacert.pem",
         b"-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"),
        ("KGNext-E14/licenses/Pillow-LICENSE.txt", b"license"),
        ("README-KGNext-E14-win11-r01.txt", b"readme"),
        ("package-files.json", b"{}"),
        ("SHA256SUMS.txt", b""),
    ])
    with zipfile.ZipFile(archive) as zf:
        assert not api.validate_member_names(zf.infolist())
    bad = tmp_path / "bad.zip"
    _make_zip(bad, [
        ("KGNext-E14/../escape", b"x"),
        ("/absolute", b"x"),
        ("C:/drive", b"x"),
        ("KGNext-E14/a\\b", b"x"),
    ])
    with zipfile.ZipFile(bad) as zf:
        assert api.validate_member_names(zf.infolist())

def test_portable_writer_real_micro_package_manifest_and_sums(tmp_path):
    import hashlib
    import uuid
    import build_e14
    package = tmp_path / "KGNext-E14"
    (package / "_internal" / "certifi").mkdir(parents=True)
    (package / "KGNext-E14.exe").write_bytes(b"MZ")
    (package / "_internal" / "certifi" / "cacert.pem").write_bytes(
        b"-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"
    )
    (package / "_internal" / "data.txt").write_text("synthetic", encoding="utf-8")
    portable = tmp_path / "dist"
    info = {
        "build_id": str(uuid.uuid4()),
        "database_revision": build_e14.DATABASE_REVISION,
        "source_freeze_digest": "a" * 64,
        "built_at": "2026-10-31T00:00:00+00:00",
        "source_commit": "b" * 40,
        "frontend_digest": "c" * 64,
        "version": "0.1.0",
    }
    result = build_e14.write_portable_archive(package, portable, info)
    archive = portable / build_e14.ARCHIVE_NAME
    assert archive.is_file() and result["archive_sha256"] == hashlib.sha256(
        archive.read_bytes()
    ).hexdigest()
    manifest = json.loads(
        (portable / build_e14.MANIFEST_NAME).read_text(encoding="utf-8")
    )
    assert manifest["schema_version"] == 1
    assert manifest["package"] == "KGNext-E14"
    assert manifest["build_id"] == info["build_id"]
    assert manifest["database_revision"] == info["database_revision"]
    assert manifest["source_freeze_digest"] == info["source_freeze_digest"]
    paths = [item["path"] for item in manifest["files"]]
    assert paths == sorted(paths) and len(paths) == len(set(paths))
    assert "KGNext-E14.exe" in paths
    actual = {
        path.relative_to(package).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in package.rglob("*") if path.is_file()
    }
    assert {item["path"]: item["sha256"] for item in manifest["files"]} == actual
    for item in manifest["files"]:
        assert type(item["size"]) is int and item["size"] >= 0
        assert len(item["sha256"]) == 64 and item["sha256"] == item["sha256"].lower()

    sums_path = portable / build_e14.SUMS_NAME
    parsed = {}
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        assert len(digest) == 64 and digest == digest.lower()
        assert name not in parsed
        parsed[name] = digest
    expected = {f"KGNext-E14/{path}" for path in paths}
    expected |= {build_e14.README_NAME, build_e14.MANIFEST_NAME}
    assert set(parsed) == expected
    assert build_e14.SUMS_NAME not in parsed
    assert parsed[build_e14.MANIFEST_NAME] == hashlib.sha256(
        (portable / build_e14.MANIFEST_NAME).read_bytes()
    ).hexdigest()
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        assert names == sorted(names) and len(names) == len(set(names))
        assert not any(name.startswith(("/", "\\")) or "\\" in name for name in names)
        assert not any(name.endswith("/") for name in names)
        assert {name.split("/", 1)[0] for name in names} == {
            "KGNext-E14", build_e14.README_NAME,
            build_e14.MANIFEST_NAME, build_e14.SUMS_NAME,
        }
        for member in zf.infolist():
            assert member.date_time == (1980, 1, 1, 0, 0, 0)
            assert member.compress_type == zipfile.ZIP_DEFLATED
            assert (member.external_attr >> 16) & 0o170000 == 0o100000
        for item in manifest["files"]:
            data = zf.read(f"KGNext-E14/{item['path']}")
            assert hashlib.sha256(data).hexdigest() == item["sha256"]
        readme = zf.read(build_e14.README_NAME).decode("utf-8")
        assert "C:\\Users" not in readme and "/Users/" not in readme
        assert "PRIVATE KEY" not in readme


def test_member_entries_reject_links_encryption_compression_and_limits():
    api = _api()
    assert "symlink" in api.validate_member_names([
        _member("KGNext-E14/link", external_attr=0o120777 << 16)
    ])
    assert "encrypted" in api.validate_member_names([
        _member("KGNext-E14/a", flag_bits=1)
    ])
    assert "unsupported_compression" in api.validate_member_names([
        _member("KGNext-E14/a", compress_type=zipfile.ZIP_BZIP2)
    ])
    assert "member_too_large" in api.validate_member_names([
        _member("KGNext-E14/large", file_size=(1 << 30) + 1, compress_size=1)
    ])
    assert "ratio_exceeded" in api.validate_member_names([
        _member("KGNext-E14/ratio", file_size=201, compress_size=1)
    ])
    many_unique = [
        _member(f"KGNext-E14/count-{index:05d}.txt", file_size=1, compress_size=1)
        for index in range(20001)
    ]
    assert "too_many_entries" in api.validate_member_names(many_unique)
    total_unique = [
        _member(f"KGNext-E14/total-{index}.bin", file_size=800 * 1024 * 1024,
                compress_size=800 * 1024 * 1024)
        for index in range(4)
    ]
    assert "total_too_large" in api.validate_member_names(total_unique)

def _sha_bytes(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


def _canonical_digest(files):
    import hashlib
    import json
    payload = [
        {"path": item["path"], "sha256": item["sha256"]}
        for item in sorted(files, key=lambda item: item["path"])
    ]
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _write_path(root: Path, relative: str, data: bytes) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _build_archive_fixture(root: Path, *, manifest_mutator=None, sums_mutator=None,
                           zip_extra=None, zip_remove=None, private_text=None,
                           product_extra=None, package_info_extra=None):
    import json
    import uuid
    package = root / "package" / "KGNext-E14"
    package.mkdir(parents=True)
    product = {
        "KGNext-E14.exe": b"MZ",
        "_internal/certifi/cacert.pem":
            b"-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n",
        "licenses/Pillow-LICENSE.txt": b"synthetic license",
        "_internal/data.txt": b"synthetic data",
    }
    if private_text is not None:
        product["_internal/notes.txt"] = private_text
    if product_extra:
        product.update(product_extra)
    for relative, data in product.items():
        _write_path(package, relative, data)
    freeze_files = [{"path": "desktop/d1_main.py", "size": 1, "sha256": "d" * 64}]
    freeze_digest = _canonical_digest(freeze_files)
    build_id = str(uuid.uuid4())
    package_info = {
        "app": "KGNext-E14",
        "package": "KGNext-E14",
        "version": "0.1.0",
        "build_id": build_id,
        "database_revision": "20261025_0006_local_game_observations",
        "unsigned_internal_test": True,
        "source_commit": "b" * 40,
        "frontend_digest": "c" * 64,
        "frontend_file_count": 1,
        "source_freeze_digest": freeze_digest,
        "built_at": "2026-10-31T01:00:00+00:00",
    }
    if package_info_extra:
        package_info.update(package_info_extra)
    _write_path(package, "package-info.json",
                json.dumps(package_info, ensure_ascii=False, indent=2).encode("utf-8"))
    product_files = {
        path.relative_to(package).as_posix(): path.read_bytes()
        for path in package.rglob("*") if path.is_file()
    }
    manifest = {
        "schema_version": 1,
        "package": "KGNext-E14",
        "build_id": build_id,
        "database_revision": "20261025_0006_local_game_observations",
        "source_freeze_digest": freeze_digest,
        "generated_at": "2026-10-31T01:00:00+00:00",
        "files": [
            {"path": relative, "size": len(data), "sha256": _sha_bytes(data)}
            for relative, data in sorted(product_files.items())
        ],
    }
    if manifest_mutator is not None:
        changed = manifest_mutator(manifest)
        if isinstance(changed, (bytes, bytearray)):
            manifest_bytes = bytes(changed)
        else:
            manifest_bytes = json.dumps(changed, ensure_ascii=False, indent=2).encode("utf-8")
    else:
        manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    readme_name = "README-KGNext-E14-win11-r01.txt"
    manifest_name = "package-files.json"
    sums_name = "SHA256SUMS.txt"
    readme_bytes = b"internal candidate\n"
    sums_map = {f"KGNext-E14/{relative}": _sha_bytes(data)
                for relative, data in product_files.items()}
    sums_map[readme_name] = _sha_bytes(readme_bytes)
    sums_map[manifest_name] = _sha_bytes(manifest_bytes)
    if sums_mutator is not None:
        changed = sums_mutator(dict(sums_map))
        if isinstance(changed, (bytes, bytearray)):
            sums_bytes = bytes(changed)
        else:
            sums_bytes = b"".join(
                f"{digest}  {name}\n".encode("utf-8")
                for name, digest in sorted(changed.items())
            )
    else:
        sums_bytes = b"".join(
            f"{digest}  {name}\n".encode("utf-8")
            for name, digest in sorted(sums_map.items())
        )
    freeze = {
        "commit": "e" * 40,
        "before": {
            "files": freeze_files,
            "digest": freeze_digest,
            "file_count": len(freeze_files),
            "generated_at": "2026-10-31T00:00:00+00:00",
        },
        "after": {
            "files": freeze_files,
            "digest": freeze_digest,
            "file_count": len(freeze_files),
            "generated_at": "2026-10-31T00:00:00+00:00",
        },
        "changes": {"stable": True, "changed": [], "added": [], "removed": []},
        "stable": True,
        "package_tree_digest": "f" * 64,
    }
    freeze_path = root / "freeze.json"
    freeze_path.write_text(json.dumps(freeze, ensure_ascii=False, indent=2), encoding="utf-8")
    archive_path = root / "candidate.zip"
    entries = {f"KGNext-E14/{relative}": data for relative, data in product_files.items()}
    entries[readme_name] = readme_bytes
    entries[manifest_name] = manifest_bytes
    entries[sums_name] = sums_bytes
    for name in zip_remove or ():
        entries.pop(name, None)
    for name, data in zip_extra or ():
        entries[name] = data
    _make_zip(archive_path, sorted(entries.items()))
    return package, archive_path, freeze_path, root / "report.json"

def _run_archive_case(root: Path, **mutations):
    import verify_e14_portable_archive as archive_verifier
    package, archive, freeze, out = _build_archive_fixture(root, **mutations)
    rc = archive_verifier.main([
        "--archive", str(archive), "--out", str(out),
        "--source-freeze", str(freeze), "--package", str(package),
    ])
    report = json.loads(out.read_text(encoding="utf-8"))
    return rc, report


def test_archive_positive_coherent_tiny_candidate(tmp_path):
    rc, report = _run_archive_case(tmp_path)
    checks = report["checks"]
    assert rc == 0
    assert report["mode"] == "static" and report["ok"] is True
    assert all(type(value) is bool for value in checks.values())
    assert checks["public_ca_and_licenses_preserved"] is True
    assert checks["no_private_material"] is True
    assert checks["package_dir_matches_zip"] is True
    assert checks["source_freeze_stable"] is True
    assert checks["zip_streamed_without_extract"] is True
    assert report["frozen_runtime"] == "not_run_static_only"

def _dup_manifest_keys(base):
    import json
    raw = json.dumps(base, ensure_ascii=False, indent=2).rstrip()
    return (raw[:-1] + ',"files":[]}').encode("utf-8")


def _dup_manifest_paths(base):
    import copy
    changed = copy.deepcopy(base)
    changed["files"].append(copy.deepcopy(changed["files"][0]))
    return changed


def _nonint_manifest_size(base):
    import copy
    changed = copy.deepcopy(base)
    changed["files"][0]["size"] = "2"
    return changed


def _bad_manifest_sha(base):
    import copy
    changed = copy.deepcopy(base)
    changed["files"][0]["sha256"] = "Z" * 64
    return changed


def _duplicate_sums(values):
    lines = [f"{digest}  {name}" for name, digest in sorted(values.items())]
    return ("\n".join(lines + [lines[0]]) + "\n").encode("utf-8")


def _malformed_sums(values):
    lines = [f"{digest}  {name}" for name, digest in sorted(values.items())]
    lines[0] = "not-a-digest  " + lines[0].split("  ", 1)[1]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _wrong_readme_sha(values):
    values["README-KGNext-E14-win11-r01.txt"] = "0" * 64
    return values

def test_archive_mutations_fail_intended_checks(tmp_path):
    cases = [
        ("duplicate-keys", {"manifest_mutator": _dup_manifest_keys},
         "manifest_no_duplicate_keys"),
        ("duplicate-paths", {"manifest_mutator": _dup_manifest_paths},
         "manifest_no_duplicate_paths"),
        ("nonint-size", {"manifest_mutator": _nonint_manifest_size},
         "manifest_schema_exact"),
        ("bad-sha", {"manifest_mutator": _bad_manifest_sha},
         "manifest_schema_exact"),
        ("missing-member", {"zip_remove": ["KGNext-E14/_internal/data.txt"]},
         "product_file_set_exact"),
        ("extra-member", {"zip_extra": [("KGNext-E14/_internal/extra.txt", b"extra")]},
         "product_file_set_exact"),
        ("duplicate-sums", {"sums_mutator": _duplicate_sums},
         "checksums_no_duplicates"),
        ("malformed-sums", {"sums_mutator": _malformed_sums},
         "checksums_schema_exact"),
        ("wrong-readme-sha", {"sums_mutator": _wrong_readme_sha},
         "checksums_cover_product_and_outer"),
        ("private-content", {"private_text": b"-----BEGIN PRIVATE KEY-----\nMIIB\n"},
         "no_private_material"),
    ]
    for name, mutations, target in cases:
        case_root = tmp_path / name
        case_root.mkdir()
        rc, report = _run_archive_case(case_root, **mutations)
        checks = report["checks"]
        assert rc == 1, (name, rc, report.get("errors"))
        assert report["ok"] is False, name
        assert all(type(value) is bool for value in checks.values()), name
        assert checks[target] is False, (name, target, checks.get(target))
        if name == "private-content":
            assert checks["public_ca_and_licenses_preserved"] is True
            assert checks["no_private_audit_entries"] is True

def _actual_freeze_files():
    import hashlib
    import verify_e14_package as package_verifier
    files = []
    for relative in package_verifier.REQUIRED_FREEZE_PATHS:
        path = package_verifier.REPO / relative
        data = path.read_bytes()
        files.append({"path": relative, "size": len(data),
                      "sha256": hashlib.sha256(data).hexdigest()})
    return files


def _freeze_document(files, *, after_files=None, changes=None, stable=True):
    import copy
    after_files = copy.deepcopy(files) if after_files is None else after_files
    before_digest = _canonical_digest(files)
    after_digest = _canonical_digest(after_files)
    generated = "2026-10-31T00:00:00+00:00"
    return {
        "commit": "a" * 40,
        "before": {"files": files, "digest": before_digest,
                   "file_count": len(files), "generated_at": generated},
        "after": {"files": after_files, "digest": after_digest,
                  "file_count": len(after_files), "generated_at": generated},
        "changes": changes or {"stable": True, "changed": [], "added": [], "removed": []},
        "stable": stable,
        "package_tree_digest": "f" * 64,
    }

def test_load_freeze_actual_baseline_and_counterexamples(tmp_path):
    import copy
    import json
    import verify_e14_package as package_verifier
    files = _actual_freeze_files()
    self_rel = "desktop/verify_e14_package.py"
    info = {"built_at": "2026-10-31T02:00:00+00:00"}
    base = tmp_path / "base-freeze.json"
    base.write_text(json.dumps(_freeze_document(files), ensure_ascii=False), encoding="utf-8")
    loaded = package_verifier._load_freeze(base, info, self_rel)
    assert loaded["present"] is True and loaded["schema_ok"] is True
    assert loaded["stable"] is True and loaded["digest_ok"] is True
    assert loaded["changes_ok"] is True and loaded["before_build"] is True
    assert loaded["current_mismatches"] == [] and loaded["required_missing"] == []
    assert loaded["self_matches"] is True
    empty = tmp_path / "empty-freeze.json"
    empty.write_text("{}", encoding="utf-8")
    loaded_empty = package_verifier._load_freeze(empty, info, self_rel)
    assert loaded_empty["present"] is True
    assert loaded_empty["schema_ok"] is False and loaded_empty["stable"] is False
    missing = tmp_path / "missing-freeze.json"
    loaded_missing = package_verifier._load_freeze(missing, info, self_rel)
    assert loaded_missing["present"] is False and loaded_missing["schema_ok"] is False
    first = files[0]["path"]
    stale_files = copy.deepcopy(files)
    stale_files[0]["sha256"] = "0" * 64
    stale = tmp_path / "stale-freeze.json"
    stale.write_text(json.dumps(_freeze_document(stale_files), ensure_ascii=False),
                     encoding="utf-8")
    loaded_stale = package_verifier._load_freeze(stale, info, self_rel)
    assert first in loaded_stale["current_mismatches"]
    after_files = copy.deepcopy(files)
    after_files[0]["sha256"] = "1" * 64
    after_changes = {"stable": False, "changed": [first], "added": [], "removed": []}
    changed_doc = _freeze_document(
        files, after_files=after_files, changes=after_changes, stable=False
    )
    changed = tmp_path / "changed-freeze.json"
    changed.write_text(json.dumps(changed_doc, ensure_ascii=False), encoding="utf-8")
    loaded_changed = package_verifier._load_freeze(changed, info, self_rel)
    assert loaded_changed["digest_ok"] is False
    assert loaded_changed["changes_ok"] is False
    assert loaded_changed["stable"] is False
    missing_files = [item for item in files if item["path"] != first]
    missing_doc = _freeze_document(missing_files)
    missing_required = tmp_path / "missing-required.json"
    missing_required.write_text(json.dumps(missing_doc, ensure_ascii=False), encoding="utf-8")
    loaded_required = package_verifier._load_freeze(missing_required, info, self_rel)
    assert first in loaded_required["required_missing"]
    assert loaded_required["schema_ok"] is True

def test_resource_and_archive_negative_checks_use_real_parsers(tmp_path):
    import verify_e14_package as package_verifier
    package = tmp_path / "missing-package"
    resources = package_verifier._resource_checks(package)
    assert resources["templates_match"] is False
    assert resources["migrations_match"] is False
    assert resources["alembic_match"] is False
    assert resources["observation_templates"] is False
    assert resources["migration_0006"] is False
    assert resources["license_present"] is False
    assert resources["license_matches"] is False
    archive = package_verifier._archive_static_report(package, {})
    assert archive["error"] == "package EXE missing"
    assert archive["readable"] is False
    info = package_verifier._package_info_checks({}, "KGNext-E14")
    assert info["portable"] is False and info["metadata_exact"] is False
    assert set(package_verifier.REQUIRED_MAINTENANCE_MODULES) <= set(
        package_verifier.ARCHIVE_REQUIRED_MODULES
    )
    assert set(package_verifier.REQUIRED_BACKUP_RESTORE_MODULES) <= set(
        package_verifier.ARCHIVE_REQUIRED_MODULES
    )

def test_report_path_guard_rejects_raw_parent_and_reparse(tmp_path):
    import verify_e14_package as package_verifier
    import verify_e14_portable_archive as archive_verifier
    allowed = tmp_path / "allowed"
    nested = tmp_path / "protected" / "nested"
    allowed.mkdir()
    nested.mkdir(parents=True)
    link = allowed / "link"
    try:
        link.symlink_to(nested, target_is_directory=True)
    except OSError as exc:
        pytest.fail(f"cannot create synthetic reparse point: {exc}")
    raw_parent = allowed / ".." / "leak.json"
    for module in (package_verifier, archive_verifier):
        accepted, reason = module._report_path_ok(raw_parent, [tmp_path / "protected"])
        assert accepted is False and reason is not None and "parent" in reason.lower()
        resolved, reason = module._plain_input(raw_parent, "out")
        assert resolved is None and reason is not None and "parent" in reason.lower()
        accepted, reason = module._report_path_ok(link / "new.json", [tmp_path / "protected"])
        assert accepted is False and reason is not None and "reparse" in reason.lower()
        resolved, reason = module._plain_input(link / "new.json", "out")
        assert resolved is None and reason is not None and "reparse" in reason.lower()
        accepted, reason = module._report_path_ok(allowed / "safe.json", [link])
        assert accepted is False and reason is not None and "reparse" in reason.lower()
    assert not (nested / "new.json").exists()
    assert not (allowed / "leak.json").exists()
    assert not (allowed / "safe.json").exists()

STATIC_HARNESS = r'''
import json
import os
import subprocess
import sys
import traceback

calls = []
def forbidden(*args, **kwargs):
    calls.append("|".join(traceback.format_stack()))
    raise AssertionError("process start forbidden")
subprocess.run = forbidden
subprocess.Popen = forbidden
for name in ("system", "startfile", "execv", "execve", "spawnv", "spawnve",
             "posix_spawn"):
    if hasattr(os, name):
        setattr(os, name, forbidden)
PACKAGE = sys.argv[1]
sys.path.insert(0, PACKAGE)
before = set(sys.modules)
import verify_e14_package as verifier
result = verifier.main(sys.argv[2:])
new_modules = sorted(name for name in sys.modules if name not in before)
print(json.dumps({"rc": result, "calls": calls, "new_modules": new_modules}))
'''


def _run_static_harness(tmp_path):
    desktop = Path(__file__).resolve().parents[1]
    script = tmp_path / "static_harness.py"
    script.write_text(STATIC_HARNESS, encoding="utf-8")
    package = tmp_path / "KGNext-E14"
    package.mkdir()
    (package / "KGNext-E14.exe").write_bytes(b"MZ")
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    freeze = tmp_path / "freeze.json"
    freeze.write_text("{}", encoding="utf-8")
    out = tmp_path / "report.json"
    completed = subprocess.run([
        sys.executable, str(script), str(desktop),
        "--package", str(package), "--mode", "static", "--static-only",
        "--source-freeze", str(freeze), "--frontend-build", str(frontend),
        "--out", str(out),
    ], cwd=desktop, capture_output=True, text=True, timeout=120)
    assert completed.returncode == 0, (completed.stdout, completed.stderr)
    return json.loads(completed.stdout.strip().splitlines()[-1]), out

def test_static_package_fresh_harness_no_process_and_fail_closed(tmp_path):
    import verify_e14_package as package_verifier
    result, out = _run_static_harness(tmp_path)
    assert result["calls"] == []
    forbidden_modules = [
        name for name in result["new_modules"]
        if name in ("webview", "uvicorn", "d1_main", "d1_host_api", "d1_server",
                    "d1_paths", "maintenance_host", "maintenance_lifecycle",
                    "verify_d2_w6_common", "verify_d2_w6_package")
        or name.startswith(("app.", "tests.local"))
    ]
    assert forbidden_modules == []
    report = json.loads(out.read_text(encoding="utf-8"))
    checks = report["checks"]
    assert result["rc"] == 1
    assert report["mode"] == "static" and report["ok"] is False
    assert report["frozen_runtime"] == "not_run_static_only"
    assert report["real_ai"] == "not_run"
    assert report["signatures"]["checked"] is False
    assert all(type(value) is bool for value in checks.values())
    assert set(report["required_checks"]) == set(package_verifier.REQUIRED_STATIC_CHECKS)
    assert checks["static_no_execution"] is True
    assert checks["static_no_production_imports"] is True
    assert checks["source_freeze_stable"] is False
    assert checks["archive_required_modules_present"] is False
    assert checks["archive_maintenance_modules_present"] is False
    assert checks["archive_backup_restore_modules_present"] is False
    assert checks["bundle_templates_match"] is False
    assert checks["pillow_license_present"] is False
    assert checks["migration_0006"] is False
    assert report["missing_checks"] or report["failed_checks"]



def _wrong_manifest_sha(values):
    values["package-files.json"] = "0" * 64
    return values


def test_report_path_guard_rejects_existing_file_and_overlap(tmp_path):
    import verify_e14_package as package_verifier
    import verify_e14_portable_archive as archive_verifier
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    existing = allowed / "existing.txt"
    existing.write_text("keep", encoding="utf-8")
    package = allowed / "package"
    package.mkdir()
    for module in (package_verifier, archive_verifier):
        for target in (existing, existing / "report.json"):
            accepted, reason = module._report_path_ok(target, [])
            assert accepted is False and reason is not None
        accepted, reason = module._report_path_ok(package / "report.json", [package])
        assert accepted is False and reason is not None
        accepted, reason = module._report_path_ok(allowed / "report.json", [package])
        assert accepted is True and reason is None
    assert existing.read_text(encoding="utf-8") == "keep"
    assert not (package / "report.json").exists()
    assert not (allowed / "report.json").exists()



def _installed_sbom_bytes() -> bytes:
    import sysconfig
    path = (Path(sysconfig.get_paths()["purelib"]) / "cryptography-50.0.1.dist-info" /
            "sboms" / "cryptography-rust.cyclonedx.json")
    assert path.is_file()
    return path.read_bytes()


def test_privacy_positive_actual_sbom_and_regex(tmp_path):
    sbom_name = "_internal/cryptography-50.0.1.dist-info/sboms/cryptography-rust.cyclonedx.json"
    regex_name = "_internal/frontend/assets/index-test.js"
    regex_literal = b'ye=/"(?:[^"\\\\]|\\\\[^])*"/\n'
    rc, report = _run_archive_case(tmp_path, product_extra={
        sbom_name: _installed_sbom_bytes(),
        regex_name: regex_literal,
    })
    checks = report["checks"]
    assert rc == 0 and report["ok"] is True
    assert checks["no_absolute_paths_in_text"] is True
    assert checks["privacy_text_scan_complete"] is True
    assert checks["no_private_material"] is True
    assert checks["public_ca_and_licenses_preserved"] is True

def test_privacy_true_leaks_in_frontend_sbom_and_text(tmp_path):
    sbom_name = "_internal/cryptography-50.0.1.dist-info/sboms/cryptography-rust.cyclonedx.json"
    sbom = _installed_sbom_bytes()
    cases = [
        ("frontend-home", "_internal/frontend/assets/index-leak.js",
         b'const p = "C:/Users/teacher/private";\n'),
        ("sbom-modified", sbom_name, sbom + b"\n// C:/Users/teacher/private\n"),
        ("ordinary-windows", "_internal/notes.txt",
         b"C:\\Users\\teacher\\private\n"),
        ("ordinary-users", "_internal/notes.txt", b"/Users/name/private\n"),
        ("ordinary-home", "_internal/notes.txt", b"/home/name/private\n"),
        ("ordinary-unc", "_internal/notes.txt", b"\\\\server\\share\\private\n"),
    ]
    for name, relative, data in cases:
        case_root = tmp_path / name
        case_root.mkdir()
        rc, report = _run_archive_case(case_root, product_extra={relative: data})
        checks = report["checks"]
        assert rc == 1, name
        assert report["ok"] is False, name
        assert checks["no_absolute_paths_in_text"] is False, name
        assert checks["privacy_text_scan_complete"] is True, name
        hits = report.get("absolute_text_hits") or []
        assert any(str(hit.get("path", "")).endswith(relative) for hit in hits), (name, hits)


def test_privacy_metadata_absolute_path_fails(tmp_path):
    rc, report = _run_archive_case(
        tmp_path, package_info_extra={"note": "C:/Users/teacher/private"}
    )
    checks = report["checks"]
    assert rc == 1 and report["ok"] is False
    assert checks["no_absolute_paths_in_text"] is False
    hits = report.get("absolute_text_hits") or []
    assert any(str(hit.get("path", "")).endswith("package-info.json") for hit in hits)

def test_privacy_scanner_discriminates_regex_sbom_and_true_leaks():
    import verify_e14_package as package_verifier
    import verify_e14_portable_archive as archive_verifier
    sbom_text = _installed_sbom_bytes().decode("utf-8")
    known = archive_verifier._known_sbom_info(sbom_text.encode("utf-8"))
    assert known["matches_source"] is True
    regex_text = 'ye=/"(?:[^"\\\\]|\\\\[^])*"/'
    for module in (package_verifier, archive_verifier):
        positive = module.scan_text_private_paths(
            sbom_text, source_path=known["path"], known_sbom=known
        )
        assert positive["violations"] == []
        assert len(positive["allowed_build_references"]) == 8
        assert module.scan_text_private_paths(regex_text, source_path="frontend/x.js")[
            "violations"
        ] == []
        for text, kind in (
            ("C:/Users/teacher/private", "drive-path"),
            ("C:\\\\Users\\\\teacher\\\\private", "user-home"),
            ("/Users/name/private", "user-home"),
            ("/home/name/private", "user-home"),
            (r"\\server\share\private", "unc"),
        ):
            result = module.scan_text_private_paths(text, source_path="notes.txt")
            assert any(item["kind"] == kind for item in result["violations"]), (text, result)
        modified = module.scan_text_private_paths(
            sbom_text + "\nC:/Users/teacher/private\n",
            source_path=known["path"],
            known_sbom={**known, "matches_source": False},
        )
        assert any(item["kind"] == "known-sbom-modified"
                   for item in modified["violations"])
        non_sbom = module.scan_text_private_paths(
            "D:/a/other/wheelhouse/build", source_path="notes.txt"
        )
        assert any(item["kind"] == "drive-path" for item in non_sbom["violations"])
        metadata = module.scan_text_private_paths(
            "C:/Users/teacher/private", source_path="package-info.json", metadata=True
        )
        assert any(item["kind"] == "drive-path" for item in metadata["violations"])


