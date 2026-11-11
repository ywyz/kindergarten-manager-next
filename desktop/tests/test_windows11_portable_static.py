"""Independent Windows 11 portable archive/static contract tests.

These tests use real small ZIPs and the contract pure validators. They do not
build, execute the candidate/EXE/helper, extract an untrusted archive, run the
legacy verifier flow, or start the application.
"""

from __future__ import annotations

import hashlib
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
        "database_revision": str(
            __import__("verify_e14_package").discover_migration_chain(
                __import__("verify_e14_package").MIGRATIONS
            )["head_revision"]
        ),
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
                           product_extra=None, product_remove=None,
                           package_info_extra=None, identity_extra=None,
                           freeze_extra=None):
    import json
    import uuid
    import build_e14
    import verify_e14_package as package_verifier
    source_head = str(
        package_verifier.discover_migration_chain(package_verifier.MIGRATIONS)["head_revision"]
    )
    source_migrations = package_verifier.source_migration_files(
        package_verifier.MIGRATIONS
    )
    package = root / "package" / "KGNext-E14"
    package.mkdir(parents=True)
    product = {
        "KGNext-E14.exe": b"MZ",
        "_internal/certifi/cacert.pem":
            b"-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n",
        "licenses/Pillow-LICENSE.txt": b"synthetic license",
        "_internal/data.txt": b"synthetic data",
    }
    for path in sorted(package_verifier.MIGRATIONS.rglob("*")):
        if (
            path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix.lower() not in {".pyc", ".pyo"}
        ):
            relative = path.relative_to(package_verifier.MIGRATIONS).as_posix()
            product[f"_internal/migrations_local/{relative}"] = path.read_bytes()
    if private_text is not None:
        product["_internal/notes.txt"] = private_text
    if product_extra:
        product.update(product_extra)
    for relative in product_remove or ():
        product.pop(relative, None)
    for relative, data in product.items():
        _write_path(package, relative, data)
    freeze_files = [
        {
            "path": (
                "backend/migrations_local/"
                + path.relative_to(package_verifier.MIGRATIONS).as_posix()
            ),
            "size": path.stat().st_size,
            "sha256": _sha_bytes(path.read_bytes()),
        }
        for path in sorted(package_verifier.MIGRATIONS.rglob("*"))
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix.lower() not in {".pyc", ".pyo"}
    ]
    freeze_digest = _canonical_digest(freeze_files)
    freeze_commit = "e" * 40
    build_id = str(uuid.uuid4())
    package_info = {
        "app": "KGNext-E14",
        "package": "KGNext-E14",
        "version": "0.1.0",
        "channel": "stable",
        "build_id": build_id,
        "database_revision": source_head,
        "migrations": source_migrations,
        "listening_templates": list(build_e14.LISTENING_TEMPLATE_REQUIRED_FILES),
        "unsigned_internal_test": True,
        "source_commit": freeze_commit,
        "frontend_digest": "c" * 64,
        "frontend_file_count": 1,
        "source_freeze_digest": freeze_digest,
        "built_at": "2026-10-31T01:00:00+00:00",
    }
    if package_info_extra:
        package_info.update(package_info_extra)
    _write_path(package, "package-info.json",
                json.dumps(package_info, ensure_ascii=False, indent=2).encode("utf-8"))
    identity = {
        "app_id": "kindergarten-manager-next",
        "app_name": "KindergartenManager",
        "channel": package_info.get("channel", "stable"),
        "version": package_info.get("version"),
        "build_id": build_id,
        "package_format": "pyinstaller-onedir-zip-v1",
        "platform": "windows",
        "arch": "x64",
        "python": "3.14.10",
        "database_revision": package_info.get("database_revision"),
    }
    if identity_extra:
        identity.update(identity_extra)
    _write_path(package, "_internal/build_identity.json",
                json.dumps(identity, ensure_ascii=False, indent=2).encode("utf-8"))
    product_files = {
        path.relative_to(package).as_posix(): path.read_bytes()
        for path in package.rglob("*") if path.is_file()
    }
    manifest = {
        "schema_version": 1,
        "package": "KGNext-E14",
        "build_id": build_id,
        "database_revision": source_head,
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
        "commit": freeze_commit,
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
        "version": package_info.get("version", "0.1.0"),
        "channel": package_info.get("channel", "stable"),
        "package_tree_digest": "f" * 64,
    }
    if freeze_extra:
        freeze.update(freeze_extra)
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
    import build_e14
    import verify_e14_package
    modules = {
        "weekly_ai_adoption", "weekly_ai_api", "weekly_ai_candidates",
        "weekly_ai_contracts", "weekly_ai_inputs", "weekly_ai_service",
        "weekly_ai_sources", "weekly_materials",
    }
    required = set(verify_e14_package.ARCHIVE_REQUIRED_MODULES)
    for name in modules:
        assert f"app.local.{name}" in required
        assert (build_e14.d0_paths.BACKEND_ROOT / "app" / "local" / f"{name}.py").is_file()
    for index, old_revision in enumerate((
        "20261101_0007_local_weekly",
        "20261102_0008_local_weekly_ai",
        "20261107_0009_local_listening",
    )):
        old_root = tmp_path / f"old-revision-{index}"
        old_root.mkdir()
        old_rc, old_report = _run_archive_case(
            old_root,
            package_info_extra={"database_revision": old_revision},
        )
        assert old_rc != 0
        assert old_report["checks"]["package_info_metadata_exact"] is False
    assert report["mode"] == "static" and report["ok"] is True
    assert all(type(value) is bool for value in checks.values())
    assert checks["public_ca_and_licenses_preserved"] is True
    assert checks["no_private_material"] is True
    assert checks["package_dir_matches_zip"] is True
    assert checks["source_freeze_stable"] is True
    assert checks["zip_streamed_without_extract"] is True
    assert report["frozen_runtime"] == "not_run_static_only"

def test_archive_accepts_preview_identity(tmp_path):
    root = tmp_path / "preview-ok"
    root.mkdir()
    rc, report = _run_archive_case(
        root,
        package_info_extra={
            "version": "1.2.3-listening-test.1",
            "channel": "preview",
        },
        freeze_extra={
            "version": "1.2.3-listening-test.1",
            "channel": "preview",
        },
    )
    assert rc == 0, report["errors"]
    checks = report["checks"]
    assert checks["package_info_metadata_exact"] is True
    assert checks["package_info_identity_matches"] is True
    assert checks["package_info_matches_freeze_identity"] is True
    assert report["ok"] is True


def test_archive_rejects_wrong_identity_version_channel_and_head(tmp_path):
    import verify_e14_package

    cases = {
        "wrong-identity-version": {"identity_extra": {"version": "9.9.9"}},
        "wrong-identity-channel": {"identity_extra": {"channel": "preview"}},
        "wrong-version-shape": {"package_info_extra": {"version": "01.2.3"}},
        "wrong-channel": {"package_info_extra": {"channel": "beta"}},
        "stable-version-preview-channel": {
            "package_info_extra": {"channel": "preview"},
        },
        "preview-version-stable-channel": {
            "package_info_extra": {
                "version": "1.2.3-listening-test.1",
                "channel": "stable",
            },
        },
        "wrong-head": {
            "package_info_extra": {
                "database_revision": "20261107_0010_local_listening_ai",
            },
        },
        "coordinated-wrong-version": {
            "package_info_extra": {"version": "9.9.9"},
            "identity_extra": {"version": "9.9.9"},
            "freeze_extra": {"version": "0.1.0", "channel": "stable"},
        },
        "coordinated-wrong-preview": {
            "package_info_extra": {
                "version": "9.9.9-listening-test.1",
                "channel": "preview",
            },
            "identity_extra": {
                "version": "9.9.9-listening-test.1",
                "channel": "preview",
            },
            "freeze_extra": {"version": "0.1.0", "channel": "stable"},
        },
    }
    assert verify_e14_package.discover_migration_chain(
        verify_e14_package.MIGRATIONS
    )["head_revision"] == "20261112_0021_local_term_name_changes"
    reports = {}
    for name, mutation in cases.items():
        root = tmp_path / name
        root.mkdir()
        rc, report = _run_archive_case(root, **mutation)
        assert rc != 0, name
        assert report["ok"] is False, name
        reports[name] = report
    assert (
        reports["coordinated-wrong-version"]["checks"][
            "package_info_matches_freeze_identity"
        ]
        is False
    )
    assert (
        reports["coordinated-wrong-preview"]["checks"][
            "package_info_matches_freeze_identity"
        ]
        is False
    )


def test_archive_rejects_missing_or_extra_migration_source_entry(tmp_path):
    import verify_e14_package

    migrations = verify_e14_package.source_migration_files(
        verify_e14_package.MIGRATIONS
    )
    missing_name = "versions/20261108_0012_local_listening_rotation.py"
    assert missing_name in migrations
    without = [name for name in migrations if name != missing_name]
    assert len(without) == len(migrations) - 1

    missing_root = tmp_path / "missing-migration"
    missing_root.mkdir()
    rc, report = _run_archive_case(
        missing_root,
        package_info_extra={"migrations": without},
    )
    assert rc != 0
    assert report["checks"]["package_info_metadata_exact"] is False

    extra_root = tmp_path / "extra-migration"
    extra_root.mkdir()
    rc, report = _run_archive_case(
        extra_root,
        package_info_extra={"migrations": [*migrations, "versions/extra.py"]},
    )
    assert rc != 0
    assert report["checks"]["package_info_metadata_exact"] is False

    extra_file_root = tmp_path / "extra-migration-file"
    extra_file_root.mkdir()
    rc, report = _run_archive_case(
        extra_file_root,
        product_extra={
            "_internal/migrations_local/versions/20261108_0099_stale.py":
                b'revision = "20261108_0099_stale"\ndown_revision = None\n',
        },
    )
    assert rc != 0
    assert report["checks"]["package_info_metadata_exact"] is True
    assert report["checks"]["package_info_migration_files_exact"] is False
    assert report["checks"]["package_info_migration_tree_exact"] is False

    extra_non_py_root = tmp_path / "extra-non-py-migration-file"
    extra_non_py_root.mkdir()
    rc, report = _run_archive_case(
        extra_non_py_root,
        product_extra={
            "_internal/migrations_local/versions/stale.txt": b"synthetic stale\n",
        },
    )
    assert rc != 0
    assert report["checks"]["package_info_migration_files_exact"] is True
    assert report["checks"]["package_info_migration_tree_exact"] is False


def test_archive_rejects_tampered_migration_bytes_with_recomputed_digests(tmp_path):
    import verify_e14_package as package_verifier

    relative = "versions/20261108_0014_local_reflection_ai.py"
    source = (package_verifier.MIGRATIONS / relative).read_bytes()
    root = tmp_path / "tampered-bytes"
    root.mkdir()
    rc, report = _run_archive_case(
        root,
        product_extra={
            f"_internal/migrations_local/{relative}": source + b"\n# synthetic tamper\n",
        },
    )
    assert rc != 0
    checks = report["checks"]
    assert checks["package_info_migration_files_present"] is True
    assert checks["package_info_migration_files_exact"] is True
    assert checks["package_info_migration_tree_exact"] is True
    assert checks["package_info_migration_files_match_source"] is False
    assert checks["product_sizes_and_hashes_exact"] is True
    assert checks["package_info_matches_manifest"] is True


def test_archive_rejects_zero_version_migration_files(tmp_path):
    import verify_e14_package as package_verifier

    chain = package_verifier.discover_migration_chain(
        package_verifier.MIGRATIONS
    )
    remove = tuple(
        f"_internal/migrations_local/versions/{filename}"
        for filename in chain["files"]
    )
    root = tmp_path / "zero-versions"
    root.mkdir()
    rc, report = _run_archive_case(root, product_remove=remove)
    assert rc != 0
    checks = report["checks"]
    assert checks["package_info_metadata_exact"] is True
    assert checks["package_info_migration_files_present"] is False
    assert checks["package_info_migration_tree_exact"] is False
    assert checks["package_info_migration_files_match_source"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("platform", "linux"),
        ("arch", "arm64"),
        ("python", "3.12.0"),
        ("package_format", "zip-v0"),
    ),
)
def test_archive_rejects_wrong_app_identity_fields(tmp_path, field, value):
    root = tmp_path / f"wrong-{field}"
    root.mkdir()
    rc, report = _run_archive_case(root, identity_extra={field: value})
    assert rc != 0
    checks = report["checks"]
    assert checks["build_identity_valid"] is False
    assert checks["build_identity_fields_exact"] is False
    assert checks["product_sizes_and_hashes_exact"] is True


def test_archive_rejects_source_build_id(tmp_path):
    import update_identity

    root = tmp_path / "source-build-id"
    root.mkdir()
    rc, report = _run_archive_case(
        root,
        identity_extra={"build_id": update_identity.SOURCE_BUILD_ID},
    )
    assert rc != 0
    checks = report["checks"]
    assert checks["build_identity_uuid"] is True
    assert checks["build_identity_not_source_id"] is False
    assert checks["build_identity_valid"] is False
    assert checks["package_info_identity_matches"] is False


def test_archive_rejects_package_info_commit_not_matching_freeze(tmp_path):
    root = tmp_path / "wrong-freeze-commit"
    root.mkdir()
    rc, report = _run_archive_case(
        root,
        package_info_extra={"source_commit": "b" * 40},
    )
    assert rc != 0
    checks = report["checks"]
    assert checks["package_info_matches_freeze_commit"] is False
    assert checks["package_info_matches_freeze_identity"] is True
    assert checks["package_info_matches_manifest"] is True
    assert checks["product_sizes_and_hashes_exact"] is True


def test_archive_rejects_package_missing_a_source_migration_file(tmp_path):
    root = tmp_path / "missing-file"
    root.mkdir()
    rc, report = _run_archive_case(
        root,
        product_remove=(
            "_internal/migrations_local/versions/"
            "20261108_0012_local_listening_rotation.py",
        ),
    )
    assert rc != 0
    checks = report["checks"]
    assert checks["package_info_metadata_exact"] is True
    assert checks["package_info_migration_files_present"] is False
    assert checks["package_info_migration_files_exact"] is False
    assert report["ok"] is False


def test_archive_rejects_sqlalchemy_compiled_extension(tmp_path):
    rc, report = _run_archive_case(
        tmp_path,
        product_extra={
            "_internal/sqlalchemy/cyextension/util.cp314-win_amd64.pyd": b"policy-blocked",
        },
    )
    assert rc != 0
    assert report["ok"] is False
    assert report["checks"]["sqlalchemy_cyextension_absent"] is False


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
        "version": "0.1.0",
        "channel": "stable",
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


@pytest.mark.parametrize(
    "relative",
    (
        "desktop/renderer_recovery.py",
        "desktop/renderer_recovery_native.py",
        "desktop/verify_renderer_recovery_window.py",
        "desktop/tests/test_renderer_recovery_verifier.py",
    ),
)
def test_load_freeze_requires_renderer_recovery_sources(tmp_path, relative):
    import copy
    import json
    import verify_e14_package as package_verifier

    files = _actual_freeze_files()
    assert relative in {item["path"] for item in files}
    self_rel = "desktop/verify_e14_package.py"
    info = {"built_at": "2026-10-31T02:00:00+00:00"}

    missing_files = [item for item in files if item["path"] != relative]
    missing_doc = _freeze_document(missing_files)
    missing_path = tmp_path / "missing-renderer-freeze.json"
    missing_path.write_text(
        json.dumps(missing_doc, ensure_ascii=False), encoding="utf-8"
    )
    loaded_missing = package_verifier._load_freeze(missing_path, info, self_rel)
    assert relative in loaded_missing["required_missing"]
    assert loaded_missing["schema_ok"] is True

    stale_files = copy.deepcopy(files)
    for item in stale_files:
        if item["path"] == relative:
            item["sha256"] = "0" * 64
    stale_doc = _freeze_document(stale_files)
    stale_path = tmp_path / "stale-renderer-freeze.json"
    stale_path.write_text(
        json.dumps(stale_doc, ensure_ascii=False), encoding="utf-8"
    )
    loaded_stale = package_verifier._load_freeze(stale_path, info, self_rel)
    assert relative in loaded_stale["current_mismatches"]


def test_sqlalchemy_compiled_extension_gate_rejects_pyd(tmp_path):
    import verify_e14_package as package_verifier

    package = tmp_path / "KGNext-E14"
    extension = (
        package
        / "_internal"
        / "sqlalchemy"
        / "cyextension"
        / "util.cp314-win_amd64.pyd"
    )
    extension.parent.mkdir(parents=True)
    assert package_verifier._sqlalchemy_compiled_extensions(package) == []
    extension.write_bytes(b"policy-blocked")
    assert package_verifier._sqlalchemy_compiled_extensions(package) == [
        "_internal/sqlalchemy/cyextension/util.cp314-win_amd64.pyd"
    ]
    assert "sqlalchemy_cyextension_absent" in package_verifier.REQUIRED_STATIC_CHECKS
    assert "sqlalchemy_pure_python_present" in package_verifier.REQUIRED_STATIC_CHECKS


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
    root_abs = os.path.abspath(tmp_path)
    link_abs = os.path.abspath(link)
    nested_abs = os.path.abspath(nested)
    # The fixture and both raw absolute paths stay inside this fresh tmp_path;
    # their parents are ordinary directories before the link is created.
    assert link.parent == allowed
    assert os.path.commonpath([link_abs, root_abs]) == root_abs
    assert os.path.commonpath([nested_abs, root_abs]) == root_abs
    assert nested.is_dir() and not nested.is_symlink()
    assert not link.exists() and not link.is_symlink()
    assert not package_verifier._is_reparse(allowed)
    assert not package_verifier._is_reparse(tmp_path / "protected")
    assert not package_verifier._is_reparse(nested)

    if os.name == "nt":
        # A directory junction needs no symbolic-link privilege and is a real
        # NTFS reparse point wholly inside the pytest-owned temporary tree.
        import _winapi

        _winapi.CreateJunction(str(nested), str(link))
        link_stat = link.lstat()
        assert getattr(link_stat, "st_file_attributes", 0) & 0x400
        if hasattr(os.path, "isjunction"):
            assert os.path.isjunction(link)
        assert link.is_dir()
        assert link.resolve(strict=True) == nested.resolve(strict=True)
        reparse_tag = getattr(link_stat, "st_reparse_tag", None)
        if reparse_tag is not None:
            assert reparse_tag == 0xA0000003  # IO_REPARSE_TAG_MOUNT_POINT
    else:
        link.symlink_to(nested, target_is_directory=True)
        assert link.is_symlink()
        assert link.resolve(strict=True) == nested.resolve(strict=True)

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



def _synthetic_pyz(modules: dict[str, bytes]) -> bytes:
    import importlib.util
    import marshal
    import struct
    import zlib

    header = b"PYZ\0" + importlib.util.MAGIC_NUMBER + b"\0\0\0\0"
    body = bytearray()
    toc: dict[str, tuple[int, int, int]] = {}
    for name, marshalled in modules.items():
        payload = zlib.compress(marshalled)
        offset = len(header) + len(body)
        body.extend(payload)
        toc[name] = (0, offset, len(payload))
    toc_offset = len(header) + len(body)
    body.extend(marshal.dumps(toc))
    return header[:8] + struct.pack("!i", toc_offset) + bytes(body)


def _synthetic_carchive(path: Path, *, modules: dict[str, bytes] | None = None) -> None:
    import marshal
    import struct

    d1_code = compile("value = 1\n", "synthetic_d1.py", "exec")
    module_code = compile("answer = 42\n", "synthetic_module.py", "exec")
    pyz_modules = {"synthetic.module": marshal.dumps(module_code)}
    if modules:
        pyz_modules.update(modules)
    pyz = _synthetic_pyz(pyz_modules)
    entries = [
        ("d1_main", marshal.dumps(d1_code), "m"),
        ("PYZ.pyz", pyz, "z"),
    ]
    payload = bytearray()
    toc_entries = []
    for name, data, typecode in entries:
        offset = len(payload)
        payload.extend(data)
        encoded_name = name.encode("utf-8")
        encoded_name += b"\0" * ((-len(encoded_name)) % 16)
        toc_entries.append(
            struct.pack(
                "!IIIIBc",
                struct.calcsize("!IIIIBc") + len(encoded_name),
                offset,
                len(data),
                len(data),
                0,
                typecode.encode("ascii"),
            )
            + encoded_name
        )
    toc = b"".join(toc_entries)
    toc_offset = len(payload)
    payload.extend(toc)
    cookie_format = "!8sIIII64s"
    cookie_length = struct.calcsize(cookie_format)
    path.write_bytes(
        bytes(payload)
        + struct.pack(
            cookie_format,
            b"MEI\014\013\012\013\016",
            len(payload) + cookie_length,
            toc_offset,
            len(toc),
            314,
            b"python314.dll".ljust(64, b"\0"),
        )
    )


def test_archive_reader_uses_locked_leaf_without_host_probe_or_process(
    monkeypatch, tmp_path
):
    import marshal
    import os
    import platform
    import subprocess

    import verify_e14_package as package_verifier

    def forbidden(*args, **kwargs):
        raise AssertionError("host platform probe or process launch forbidden")

    for name in (
        "win32_ver",
        "system",
        "release",
        "version",
        "machine",
        "platform",
        "uname",
    ):
        if hasattr(platform, name):
            monkeypatch.setattr(platform, name, forbidden)
    if hasattr(os, "system"):
        monkeypatch.setattr(os, "system", forbidden)
    if hasattr(os, "startfile"):
        monkeypatch.setattr(os, "startfile", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    if hasattr(sys, "getwindowsversion"):
        monkeypatch.setattr(sys, "getwindowsversion", forbidden)

    reader_class = package_verifier._load_carchive_reader()
    assert reader_class.__module__ == "_kgm_pyinstaller_archive_reader"
    archive_path = tmp_path / "synthetic.exe"
    _synthetic_carchive(archive_path)
    reader = reader_class(str(archive_path))
    assert {"d1_main", "PYZ.pyz"} <= set(reader.toc)
    entry = marshal.loads(reader.extract("d1_main"))
    assert entry.co_filename == "synthetic_d1.py"
    pyz = reader.open_embedded_archive("PYZ.pyz")
    assert "synthetic.module" in pyz.toc
    module = pyz.extract("synthetic.module")
    assert module.co_filename == "synthetic_module.py"

    package = tmp_path / "KGNext-E14"
    package.mkdir()
    (package / "KGNext-E14.exe").write_bytes(b"MZ")
    report = package_verifier._archive_static_report(package, {})
    assert report["readable"] is False
    assert report["error"]


RENDERER_ARCHIVE_MODULES = ("renderer_recovery", "renderer_recovery_native")


def _marshalled_renderer_source(name: str) -> bytes:
    import marshal

    source = Path(__file__).resolve().parents[1] / f"{name}.py"
    code = compile(
        source.read_text(encoding="utf-8"),
        str(source),
        "exec",
        dont_inherit=True,
        optimize=sys.flags.optimize,
    )
    return marshal.dumps(code)


def _renderer_archive_freeze(*, tampered=()):
    before = {}
    for name in RENDERER_ARCHIVE_MODULES:
        relative = f"desktop/{name}.py"
        source = Path(__file__).resolve().parents[1] / f"{name}.py"
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        before[relative] = {
            "size": source.stat().st_size,
            "sha256": "0" * 64 if name in tampered else digest,
        }
    return {"before": before}


def _renderer_archive_package(tmp_path, modules):
    package = tmp_path / "KGNext-E14"
    package.mkdir()
    _synthetic_carchive(package / "KGNext-E14.exe", modules=modules)
    return package


def test_archive_static_report_accepts_matching_renderer_recovery_modules(tmp_path):
    import verify_e14_package as package_verifier

    modules = {
        name: _marshalled_renderer_source(name) for name in RENDERER_ARCHIVE_MODULES
    }
    package = _renderer_archive_package(tmp_path, modules)
    report = package_verifier._archive_static_report(
        package, _renderer_archive_freeze()
    )
    assert report["error"] is None
    assert report["readable"] is True
    assert report["production_mismatched"] == []
    assert report["production_unavailable"] == []
    assert report["production_all_match"] is True
    assert report["production_match_freeze"] is True
    assert not set(RENDERER_ARCHIVE_MODULES) & set(report["missing_required"])
    for name in RENDERER_ARCHIVE_MODULES:
        assert package_verifier._module_class(name) == "production"
    assert (
        package_verifier._module_class("verify_renderer_recovery_window")
        == "verification_support"
    )


@pytest.mark.parametrize("missing", RENDERER_ARCHIVE_MODULES)
def test_archive_static_report_rejects_missing_renderer_recovery_module(
    tmp_path, missing
):
    import verify_e14_package as package_verifier

    modules = {
        name: _marshalled_renderer_source(name)
        for name in RENDERER_ARCHIVE_MODULES
        if name != missing
    }
    package = _renderer_archive_package(tmp_path, modules)
    report = package_verifier._archive_static_report(
        package, _renderer_archive_freeze()
    )
    assert report["readable"] is True
    assert missing in report["missing_required"]


@pytest.mark.parametrize("changed", RENDERER_ARCHIVE_MODULES)
def test_archive_static_report_rejects_changed_renderer_recovery_code(
    tmp_path, changed
):
    import marshal
    import verify_e14_package as package_verifier

    modules = {
        name: _marshalled_renderer_source(name) for name in RENDERER_ARCHIVE_MODULES
    }
    modules[changed] = marshal.dumps(
        compile("answer = 42\n", "changed_renderer_recovery.py", "exec")
    )
    package = _renderer_archive_package(tmp_path, modules)
    report = package_verifier._archive_static_report(
        package, _renderer_archive_freeze()
    )
    assert report["readable"] is True
    assert changed in report["production_mismatched"]
    assert changed in report["unexpected_production"]
    assert report["production_all_match"] is False


@pytest.mark.parametrize("tampered", RENDERER_ARCHIVE_MODULES)
def test_archive_static_report_rejects_tampered_renderer_recovery_freeze_hash(
    tmp_path, tampered
):
    import verify_e14_package as package_verifier

    modules = {
        name: _marshalled_renderer_source(name) for name in RENDERER_ARCHIVE_MODULES
    }
    package = _renderer_archive_package(tmp_path, modules)
    report = package_verifier._archive_static_report(
        package, _renderer_archive_freeze(tampered=(tampered,))
    )
    assert report["readable"] is True
    assert tampered in report["production_unavailable"]
    assert report["production_all_match"] is False
    assert report["production_match_freeze"] is False



def test_archive_reader_fails_closed_without_distribution(monkeypatch):
    from importlib import metadata

    import verify_e14_package as package_verifier

    def missing(name):
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(metadata, "distribution", missing)
    with pytest.raises(RuntimeError, match="distribution unavailable"):
        package_verifier._load_carchive_reader()


def test_archive_reader_fails_closed_on_incompatible_leaf(monkeypatch, tmp_path):
    import verify_e14_package as package_verifier

    leaf = tmp_path / "pyimod01_archive.py"
    reader = tmp_path / "readers.py"
    leaf.write_text("VALUE = 1\n", encoding="utf-8")
    reader.write_text("VALUE = 2\n", encoding="utf-8")
    monkeypatch.setattr(
        package_verifier, "_pyinstaller_reader_paths", lambda: (leaf, reader)
    )
    with pytest.raises(RuntimeError, match="leaf incompatible"):
        package_verifier._load_carchive_reader()


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
    path = (Path(sysconfig.get_paths()["purelib"]) / "cryptography-50.0.2.dist-info" /
            "sboms" / "cryptography-rust.cyclonedx.json")
    assert path.is_file()
    return path.read_bytes()


def test_privacy_positive_actual_sbom_and_regex(tmp_path):
    sbom_name = "_internal/cryptography-50.0.2.dist-info/sboms/cryptography-rust.cyclonedx.json"
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
    sbom_name = "_internal/cryptography-50.0.2.dist-info/sboms/cryptography-rust.cyclonedx.json"
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


def test_listening_template_static_contract_is_current_and_complete():
    import build_e14
    import verify_e14_package

    chain = verify_e14_package.discover_migration_chain(build_e14.MIGRATIONS_DIR)
    assert chain["head_revision"] == "20261112_0021_local_term_name_changes"
    assert chain["head_file"] == "20261112_0021_local_term_name_changes.py"
    assert len(chain["files"]) == 21
    expected = verify_e14_package.source_migration_files(build_e14.MIGRATIONS_DIR)
    assert expected == sorted(expected)
    assert len(expected) == 22
    for filename in chain["files"]:
        assert (build_e14.MIGRATIONS_DIR / "versions" / filename).is_file()
    assert len(build_e14.LISTENING_TEMPLATE_DOCX) == 15
    assert set(build_e14.LISTENING_TEMPLATE_REQUIRED_FILES) == {
        "README.md",
        "manifest.json",
        *build_e14.LISTENING_TEMPLATE_DOCX,
    }
    for relative in build_e14.LISTENING_TEMPLATE_REQUIRED_FILES:
        assert (build_e14.LISTENING_TEMPLATE_DIR / relative).is_file()
    for relative in ("manifest.json", *build_e14.LISTENING_TEMPLATE_DOCX):
        assert (
            f"backend/app/assets/listening_templates/{relative}"
            in verify_e14_package.REQUIRED_FREEZE_PATHS
        )
    assert (
        "bundle_listening_templates_match"
        in verify_e14_package.REQUIRED_STATIC_CHECKS
    )
    assert "migration_0009" in verify_e14_package.REQUIRED_STATIC_CHECKS
    assert "migration_0010" in verify_e14_package.REQUIRED_STATIC_CHECKS
    assert "migration_head" in verify_e14_package.REQUIRED_STATIC_CHECKS
    assert (
        "package_info_matches_freeze_identity"
        in verify_e14_package.REQUIRED_STATIC_CHECKS
    )
    assert (
        "package_info_matches_freeze_commit"
        in verify_e14_package.REQUIRED_STATIC_CHECKS
    )
    assert (
        "build_identity_fields_exact"
        in verify_e14_package.REQUIRED_STATIC_CHECKS
    )
    import verify_e14_portable_archive as archive_verifier

    assert (
        "package_info_identity_matches"
        in archive_verifier.REQUIRED_ARCHIVE_CHECKS
    )
    assert (
        "package_info_migration_files_exact"
        in archive_verifier.REQUIRED_ARCHIVE_CHECKS
    )
    assert (
        "package_info_migration_tree_exact"
        in archive_verifier.REQUIRED_ARCHIVE_CHECKS
    )
    assert (
        "package_info_migration_tree_matches_source"
        in archive_verifier.REQUIRED_ARCHIVE_CHECKS
    )
    assert (
        "package_info_migration_files_match_source"
        in archive_verifier.REQUIRED_ARCHIVE_CHECKS
    )
    assert (
        "package_info_matches_freeze_identity"
        in archive_verifier.REQUIRED_ARCHIVE_CHECKS
    )
    assert (
        "package_info_matches_freeze_commit"
        in archive_verifier.REQUIRED_ARCHIVE_CHECKS
    )
    assert (
        "build_identity_fields_exact"
        in archive_verifier.REQUIRED_ARCHIVE_CHECKS
    )
    assert "build_identity_valid" in archive_verifier.REQUIRED_ARCHIVE_CHECKS
    assert "build_identity_not_source_id" in archive_verifier.REQUIRED_ARCHIVE_CHECKS
    assert (
        "build_identity_matches_package_info"
        in archive_verifier.REQUIRED_ARCHIVE_CHECKS
    )


def test_listening_installer_static_contract():
    repo = Path(__file__).resolve().parents[2]
    scripts = repo / ".github" / "scripts"
    iss_path = scripts / "windows11-listening-installer.iss"
    ps1_path = scripts / "build-windows11-listening-installer.ps1"
    workflow_path = (
        repo / ".github" / "workflows" / "windows11-weekly-validation.yml"
    )
    assert iss_path.is_file()
    assert ps1_path.is_file()
    assert workflow_path.is_file()
    iss_bytes = iss_path.read_bytes()
    assert iss_bytes.startswith(b"\xef\xbb\xbf"), "Inno script must be UTF-8 BOM"
    iss = iss_bytes.decode("utf-8-sig")
    ps1 = ps1_path.read_text(encoding="utf-8-sig")
    workflow = workflow_path.read_text(encoding="utf-8-sig")

    assert "AppId={{6F2B8E7A-5C4D-4A3E-9B1F-7D2C8A6E4F10}" in iss
    assert (
        "DefaultDirName={localappdata}\\Programs\\KindergartenManagerListeningTest"
        in iss
    )
    assert "AppName=幼儿园信息管理系统" in iss
    assert "AppVerName=幼儿园信息管理系统 {#MyAppVersion}" in iss
    assert "AppComments=一对一倾听测试版 - Unsigned test build {#MyBuildId}" in iss
    assert "DefaultGroupName=幼儿园信息管理系统" in iss
    assert "UninstallDisplayName=幼儿园信息管理系统" in iss
    assert "UninstallDisplayIcon={app}\\KGNext-E14.exe" in iss
    assert (
        'Name: "{userprograms}\\幼儿园信息管理系统\\幼儿园信息管理系统"; '
        'Filename: "{app}\\KGNext-E14.exe"'
    ) in iss
    assert "Kindergarten Manager 一对一倾听测试版" not in iss
    assert "一对一倾听测试版.lnk" not in iss
    assert "[InstallDelete]" not in iss
    assert "PrivilegesRequired=lowest" in iss
    assert "MinVersion=10.0" in iss
    assert "ArchitecturesAllowed=x64" in iss
    assert "Source: \"{#MyPackageDir}\\*\"" in iss
    assert "recursesubdirs createallsubdirs" in iss
    assert (
        '--data ""{localappdata}\\KindergartenManagerListeningTest\\data"" '
        '--credential-root ""{localappdata}\\KindergartenManagerListeningTest'
        '\\credentials"""'
    ) in iss
    assert "[Run]" not in iss
    assert "SignTool=" not in iss
    assert "WebView2" not in iss

    assert "GITHUB_EVENT_NAME" in ps1
    assert "refs/heads/codex/desktop-one-to-one-listening" in ps1
    assert "ISCC.exe" in ps1
    assert "KGNext-Listening-Win11-x64-Setup.exe" in ps1
    assert "VERYSILENT" in ps1
    assert "unins000.exe" in ps1
    assert "KGNext-E14.exe" in ps1
    assert "--credential-root" in ps1
    assert "$ShortcutFolder = '幼儿园信息管理系统'" in ps1
    assert "$ShortcutName = '幼儿园信息管理系统.lnk'" in ps1
    assert (
        "$userRoot = Join-Path $env:LOCALAPPDATA "
        "'KindergartenManagerListeningTest'"
    ) in ps1
    assert "$dataRoot = Join-Path $userRoot 'data'" in ps1
    assert "$credentialRoot = Join-Path $userRoot 'credentials'" in ps1
    assert (
        "$expectedTarget = [System.IO.Path]::GetFullPath("
        "(Join-Path $installDir 'KGNext-E14.exe'))"
    ) in ps1
    assert (
        '$expectedArguments = \'--data "{0}" --credential-root "{1}"\' '
        "-f $dataRoot, $credentialRoot"
    ) in ps1
    assert "Kindergarten Manager 一对一倾听测试版" not in ps1
    assert "一对一倾听测试版.lnk" not in ps1
    assert "installer-identity.json" in ps1
    assert "synthetic-keep" in ps1
    assert "data_preserved" in ps1
    assert "get-filehash" in ps1.lower()

    assert "workflow_dispatch" in workflow
    assert "refs/heads/codex/desktop-one-to-one-listening" in workflow
    assert (
        "if: ${{ !(github.event_name == 'workflow_dispatch' && "
        "github.ref == 'refs/heads/codex/desktop-one-to-one-listening') }}"
        in workflow
    )
    assert (
        "if: ${{ github.event_name == 'workflow_dispatch' && "
        "github.ref == 'refs/heads/codex/desktop-one-to-one-listening' }}"
        in workflow
    )
    assert "build-windows11-listening-installer.ps1" in workflow
    assert "KGNext-Listening-Win11-x64-Setup.exe" in workflow
    assert "archive: false" in workflow
    assert "SHA256SUMS.txt" not in workflow
    assert "installer-identity.json" not in workflow
    assert "retention-days: 14" in workflow


def test_installer_powershell_parses_and_derives_release_identity(tmp_path):
    import shutil

    repo = Path(__file__).resolve().parents[2]
    ps1_path = (
        repo / ".github" / "scripts" / "build-windows11-listening-installer.ps1"
    )
    validation_path = (
        repo / ".github" / "scripts" / "build-windows11-validation.ps1"
    )
    ps1 = ps1_path.read_text(encoding="utf-8-sig")
    validation = validation_path.read_text(encoding="utf-8-sig")
    assert "function Get-MigrationHead" in ps1
    assert "function Assert-ReleaseIdentity" in ps1
    assert "$ExpectedRevision = Get-MigrationHead $repo" in ps1
    assert "20261107_0010_local_listening_ai" not in ps1
    assert "20261108_0016_local_listening_goal_suggest" not in ps1
    assert "$packageInfo.version" in ps1
    assert "$buildIdentity.version" in ps1
    assert "$packageInfo.PSObject.Properties['channel']" in ps1
    assert "$buildIdentity.PSObject.Properties['channel']" in ps1
    assert "version = $expectedVersion" in ps1
    assert "channel = $expectedChannel" in ps1
    assert "buildIdentity.platform" in ps1
    assert "buildIdentity.arch" in ps1
    assert "buildIdentity.python" in ps1
    assert "buildIdentity.package_format" in ps1
    assert "buildIdentity.app_id" in ps1
    assert "buildIdentity.app_name" in ps1
    assert "summary.build.PSObject.Properties['source_freeze_commit']" in ps1
    assert "freeze_commit = $expectedFreezeCommit" in ps1

    assert "source_freeze_commit = [string]$freeze.commit" in validation
    assert (
        "packageInfo.source_commit -ne [string]$freeze.commit" in validation
    )
    assert "buildIdentity.app_id" in validation
    assert "buildIdentity.app_name" in validation
    assert "buildIdentity.package_format" in validation

    shell = shutil.which("pwsh") or shutil.which("powershell")
    assert shell, "PowerShell parser is required for the static installer check"
    parser_template = "\n".join(
        (
            "$tokens = $null",
            "$errors = $null",
            "[System.Management.Automation.Language.Parser]::ParseFile(",
            "    $env:KGM_INSTALLER_PS1, [ref]$tokens, [ref]$errors",
            ") | Out-Null",
            "if ($errors.Count -gt 0) {",
            "    $errors | ForEach-Object { Write-Output $_.Message }",
            "    exit 1",
            "}",
            "exit 0",
        )
    )
    for index, path in enumerate((ps1_path, validation_path)):
        parser = tmp_path / f"parse-powershell-{index}.ps1"
        parser.write_text(parser_template, encoding="utf-8")
        environment = os.environ.copy()
        environment["KGM_INSTALLER_PS1"] = str(path)
        completed = subprocess.run(
            [shell, "-NoProfile", "-NonInteractive", "-File", str(parser)],
            capture_output=True,
            text=True,
            timeout=120,
            env=environment,
        )
        assert completed.returncode == 0, (
            path.name,
            completed.stdout,
            completed.stderr,
        )


def test_product_display_title_contract():
    repo = Path(__file__).resolve().parents[2]
    main_source = (repo / "desktop" / "d1_main.py").read_text(encoding="utf-8")
    d1_source = (repo / "frontend" / "d1.html").read_text(encoding="utf-8")
    index_source = (repo / "frontend" / "index.html").read_text(encoding="utf-8")

    assert 'PRODUCT_TITLE = "幼儿园信息管理系统"' in main_source
    assert main_source.count("PRODUCT_TITLE,") == 2
    assert "幼儿园教师工作台（本地）" not in main_source
    assert 'f"D1 验证窗口（{args.phase}）"' in main_source
    assert "_apply_product_document_title" not in main_source
    assert "document.title = " not in main_source
    assert "window.events.loaded +=" not in main_source
    for source in (d1_source, index_source):
        assert "<title>幼儿园信息管理系统</title>" in source
    assert "幼儿园教师工作台（本地）" not in d1_source
    assert "幼儿园教育工作支持系统" not in index_source


