"""Verify an E14 portable archive without private audit material.

The portable layout is deliberately flat at the archive root:

* ``KGNext-E14/`` — product files only (exactly the package directory);
* ``README-E14-r03.txt`` — portable readme;
* ``package-files.json`` — relative path/size/SHA-256 manifest;
* ``SHA256SUMS.txt`` — relative checksum list for product files/readme/manifest.

The verifier unpacks to a temporary directory and compares the product file
set, sizes and hashes exactly with the manifest. It also rejects private audit
entries (EVIDENCE, source-hash/real-ai/old-upgrade/source-freeze, logs,
databases, credential blobs) and an absolute ``package-info.package`` value.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
import zipfile
from pathlib import Path

PRODUCT = "KGNext-E14"
README = "README-E14-r03.txt"
MANIFEST = "package-files.json"
SUMS = "SHA256SUMS.txt"
FORBIDDEN = (
    "evidence/",
    "source-hash",
    "real-ai",
    "old-upgrade",
    "source-freeze",
    ".dpapi",
    ".log",
    ".db",
    "credentials",
)
CHECKSUM_RE = re.compile(r"^([0-9a-f]{64})  (.+)$")


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _norm(name: str) -> str:
    return name.replace("\\", "/").lstrip("./")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    archive = Path(args.archive).resolve()
    out = Path(args.out).resolve()
    checks: dict[str, bool] = {}
    details: dict = {"archive": str(archive), "checks": checks}
    with tempfile.TemporaryDirectory(prefix="kgm-e14-portable-") as raw:
        root = Path(raw)
        with zipfile.ZipFile(archive) as zf:
            names = [name for name in zf.namelist() if not name.endswith("/")]
            details["entries"] = len(names)
            checks["archive_not_empty"] = bool(names)
            checks["no_private_audit_entries"] = not any(
                token in name.lower() for name in names for token in FORBIDDEN
            )
            checks["only_allowed_top_level"] = all(
                name.startswith(PRODUCT + "/")
                or name in (README, MANIFEST, SUMS)
                for name in names
            )
            checks["product_dir_only"] = all(
                name.startswith(PRODUCT + "/")
                for name in names
                if name not in (README, MANIFEST, SUMS)
            )
            zf.extractall(root)
        product = root / PRODUCT
        checks["product_dir_present"] = product.is_dir()
        checks["readme_present"] = (root / README).is_file()
        checks["manifest_present"] = (root / MANIFEST).is_file()
        checks["checksums_present"] = (root / SUMS).is_file()

        manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
        checks["manifest_package_relative"] = (
            manifest.get("package") == PRODUCT
            and not Path(str(manifest.get("package"))).is_absolute()
        )
        expected = {
            _norm(item["path"]): (int(item["size"]), str(item["sha256"]).lower())
            for item in manifest.get("files", [])
        }
        actual_files = {
            _norm(str(path.relative_to(product))): path
            for path in product.rglob("*")
            if path.is_file()
        }
        checks["product_file_set_exact"] = set(expected) == set(actual_files)
        missing = sorted(set(expected) - set(actual_files))
        extra = sorted(set(actual_files) - set(expected))
        details["missing"] = missing
        details["extra"] = extra
        mismatched = []
        total_bytes = 0
        for relative, path in actual_files.items():
            total_bytes += path.stat().st_size
            size, digest = expected.get(relative, (None, None))
            if size != path.stat().st_size or digest != _sha(path):
                mismatched.append(relative)
        details["mismatched"] = mismatched
        details["product_files"] = len(actual_files)
        details["product_bytes"] = total_bytes
        checks["product_sizes_and_hashes_exact"] = not mismatched
        checks["manifest_files_nonempty"] = bool(expected)
        checks["manifest_paths_relative"] = all(
            not Path(path).is_absolute() and ".." not in Path(path).parts
            for path in expected
        )

        info_path = product / "package-info.json"
        package_info = (
            json.loads(info_path.read_text(encoding="utf-8"))
            if info_path.is_file()
            else {}
        )
        package_value = package_info.get("package")
        details["package_info_package"] = package_value
        checks["package_info_portable"] = (
            package_value == PRODUCT
            and not Path(str(package_value)).is_absolute()
        )

        sums = {}
        for line in (root / SUMS).read_text(encoding="utf-8").splitlines():
            match = CHECKSUM_RE.match(line.strip())
            if match:
                sums[_norm(match.group(2))] = match.group(1)
        expected_sums = {
            f"{PRODUCT}/{relative}": digest
            for relative, (_size, digest) in expected.items()
        }
        expected_sums[README] = _sha(root / README)
        expected_sums[MANIFEST] = _sha(root / MANIFEST)
        checks["checksums_cover_product_and_outer"] = sums == expected_sums
        details["checksum_entries"] = len(sums)

    details["archive_sha256"] = _sha(archive)
    details["archive_bytes"] = archive.stat().st_size
    details["ok"] = all(checks.values())
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(details, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": details["ok"], "report": str(out)}, ensure_ascii=False))
    return 0 if details["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
