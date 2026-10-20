"""D2 W1 frozen probe parent verifier (Windows-only).

End-to-end verification of the frozen credential probe:

1. build (optional) the onedir console package under ``build/desktop-d2-w1``;
2. copy the **whole package** to an out-of-repository synthetic directory whose
   path contains Chinese characters, spaces, ``%`` and ``#``, and prove every
   file hash is identical before and after the copy;
3. run the copied executable twice (``init`` then ``verify``) with the business
   root and credential root also out of the repository and equally special,
   a cleared environment (no ``PYTHONPATH``/``PYTHONHOME`` development source
   fallback, ``TEMP``/``TMP`` redirected into this synthetic root) and the
   package directory as the working directory;
4. feed a random synthetic secret to both processes **only through stdin** and
   assert the second process actually AES-GCM-decrypts the stored secret and
   matches it;
5. independently check the frozen head, the three default prompt bundle
   contents/hashes against the source migration, the DPAPI key file ACL, and
   that the secret plaintext appears nowhere in the database, logs, argv,
   environment or any generated file.

Robustness rules for the evidence itself: the secret is redacted from every
captured stream before it is stored; a stream that contained the secret still
fails the leak check (redaction never turns a leak into a pass); a scan that
cannot read a file is reported as a failure, never silently treated as clean;
and a failing child still leaves a redacted failure JSON so a later database
query error cannot destroy the evidence.

This is a verification helper, not a release builder, and never calls a real AI
provider.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parent
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

BUILD_ROOT = REPO_ROOT / "build" / "desktop-d2-w1"
PACKAGE_DIR = BUILD_ROOT / "package"
APP_NAME = "KGNext-D2W1Probe"
DEFAULT_EVIDENCE = BUILD_ROOT / "verify-evidence.json"

KEY_SOURCE_FILES = (
    "desktop/d2_w1_probe.py",
    "desktop/build_d2_w1_probe.py",
    "desktop/verify_d2_w1_probe.py",
    "backend/alembic-local.ini",
    "backend/migrations_local/versions/20261017_0004_local.py",
    "backend/app/local/runtime.py",
    "backend/app/local/credentials.py",
    "backend/app/local/ai_config_service.py",
    "backend/app/local/migrate.py",
)

CHILD_TIMEOUT = 600.0
REDACTED = "[REDACTED]"


def _secret_needles(secret: str) -> list[bytes]:
    """Both plain encodings a stray secret could appear as on disk/streams."""
    if not secret:
        return []
    return [secret.encode("utf-8"), secret.encode("utf-16-le")]


def _redact(text: str, secret: str) -> str:
    if not secret:
        return text
    return text.replace(secret, REDACTED)


def _redact_value(obj: object, secret: str) -> object:
    """Recursively redact the secret from a parsed JSON value."""
    if not secret:
        return obj
    if isinstance(obj, str):
        return obj.replace(secret, REDACTED)
    if isinstance(obj, dict):
        return {
            _redact_value(key, secret): _redact_value(value, secret)
            for key, value in obj.items()
        }
    if isinstance(obj, list):
        return [_redact_value(value, secret) for value in obj]
    return obj


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_tree(root: Path) -> list[dict]:
    entries: list[dict] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        entries.append(
            {
                "path": str(path.relative_to(root)),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return entries


def _canonical_manifest(entries: list[dict]) -> str:
    return hashlib.sha256(
        json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _load_source_bundles() -> dict:
    """Expected default bundle JSON/hash computed from the source migration."""
    path = (
        BACKEND_ROOT
        / "migrations_local"
        / "versions"
        / "20261017_0004_local.py"
    )
    spec = importlib.util.spec_from_file_location("d2w1_0004_source", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    mapping = {
        "daily_lesson_split": (
            module._SPLIT_INPUT_SCHEMA,
            module._SPLIT_OUTPUT_SCHEMA,
            module._SPLIT_GUIDANCE,
        ),
        "daily_process_adapt": (
            module._ADAPT_INPUT_SCHEMA,
            module._ADAPT_OUTPUT_SCHEMA,
            module._ADAPT_GUIDANCE,
        ),
        "daily_other_activities": (
            module._OTHER_INPUT_SCHEMA,
            module._OTHER_OUTPUT_SCHEMA,
            module._OTHER_GUIDANCE,
        ),
    }
    result: dict[str, dict] = {}
    for task_type, (in_schema, out_schema, guidance) in mapping.items():
        result[task_type] = {
            "input_schema_json": json.dumps(in_schema, ensure_ascii=False),
            "output_schema_json": json.dumps(out_schema, ensure_ascii=False),
            "guidance_defaults_json": json.dumps(guidance, ensure_ascii=False),
            "bundle_hash": module._bundle_hash(in_schema, out_schema, guidance),
        }
    return result


def _readonly_connect(db_path: Path) -> sqlite3.Connection:
    from app.local.sqlite import readonly_sqlite_uri

    return sqlite3.connect(readonly_sqlite_uri(db_path), uri=True)


def _frozen_head(db_path: Path) -> str | None:
    connection = _readonly_connect(db_path)
    try:
        row = connection.execute(
            "SELECT version_num FROM local_alembic_version"
        ).fetchone()
        return row[0] if row else None
    finally:
        connection.close()


def _frozen_bundles(db_path: Path) -> dict:
    connection = _readonly_connect(db_path)
    try:
        rows = connection.execute(
            "SELECT task_type, input_schema_json, output_schema_json, "
            "guidance_defaults_json, bundle_hash FROM local_prompt_bundles "
            "ORDER BY task_type"
        ).fetchall()
    finally:
        connection.close()
    return {
        row[0]: {
            "input_schema_json": row[1],
            "output_schema_json": row[2],
            "guidance_defaults_json": row[3],
            "bundle_hash": row[4],
        }
        for row in rows
    }


def _validate_credential_acl(path: Path) -> None:
    """Reuse the production fail-closed validator on the key-file handle."""
    from app.local import credentials as cred

    cred._validate_raw_aliases(path)
    owner_sid = cred._current_user_sid()
    handle = cred._open_verified_file(path, owner_sid, "冻结探针密钥文件")
    cred._kernel32.CloseHandle(handle)


def _scan_tree_for_secret(
    root: Path, needles: list[bytes]
) -> tuple[list[str], list[str]]:
    """Scan every file under ``root``; return (hits, unreadable-errors).

    Every needle encoding (UTF-8 and UTF-16LE) is checked. An unreadable file
    is reported as a scan error (never treated as clean).
    """
    hits: list[str] = []
    errors: list[str] = []

    def _onerror(exc: OSError) -> None:
        location = getattr(exc, "filename", None) or "?"
        errors.append(f"{location}: {type(exc).__name__}")

    for dirpath, _dirnames, filenames in os.walk(root, onerror=_onerror):
        for name in filenames:
            path = Path(dirpath) / name
            try:
                data = path.read_bytes()
            except OSError as exc:
                errors.append(f"{path}: {type(exc).__name__}")
                continue
            if any(needle and needle in data for needle in needles):
                hits.append(str(path))
    return hits, errors


def _frozen_integrity(db_path: Path) -> dict:
    """Frozen database integrity/FK plus the one-config/credential/receipt facts."""
    connection = _readonly_connect(db_path)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        configs = connection.execute(
            "SELECT count(*) FROM local_ai_config_versions"
        ).fetchone()[0]
        credentials = connection.execute(
            "SELECT count(*) FROM local_ai_credentials"
        ).fetchone()[0]
        receipts = connection.execute(
            "SELECT count(*) FROM local_ai_operations"
        ).fetchone()[0]
    finally:
        connection.close()
    return {
        "integrity_ok": integrity == "ok",
        "foreign_key_violations": len(foreign_keys),
        "config_versions": configs,
        "credentials": credentials,
        "receipts": receipts,
    }


def _build_package() -> Path:
    script = APP_DIR / "build_d2_w1_probe.py"
    subprocess.run(
        [sys.executable, str(script)], check=True, cwd=str(REPO_ROOT)
    )
    package_root = PACKAGE_DIR / APP_NAME
    if not (package_root / f"{APP_NAME}.exe").is_file():
        raise AssertionError(f"probe package missing: {package_root}")
    return package_root


def _clean_env(local_appdata: Path, temp_dir: Path) -> dict:
    """Minimal environment: no PYTHONPATH/PYTHONHOME source fallback.

    ``TEMP``/``TMP`` point inside this run's synthetic root so every temporary
    file the child writes stays inside the scanned area.
    """
    keep = (
        "SystemRoot",
        "windir",
        "PATH",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "COMSPEC",
        "PATHEXT",
    )
    env = {key: os.environ[key] for key in keep if key in os.environ}
    env["LOCALAPPDATA"] = str(local_appdata)
    env["TEMP"] = str(temp_dir)
    env["TMP"] = str(temp_dir)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONNOUSERSITE"] = "1"
    return env


def _run_child(
    exe: Path,
    mode: str,
    data_dir: Path,
    credential_root: Path,
    out_path: Path,
    secret: str,
    env: dict,
    cwd: Path,
    timeout: float,
) -> dict:
    """Run one child; always return redacted evidence, never raise on failure."""
    command = [
        str(exe),
        "--mode",
        mode,
        "--data-dir",
        str(data_dir),
        "--credential-root",
        str(credential_root),
        "--out",
        str(out_path),
    ]
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    timed_out = False
    try:
        stdout_bytes, stderr_bytes = process.communicate(
            input=secret.encode("utf-8"), timeout=timeout
        )
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        stdout_bytes, stderr_bytes = process.communicate()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=30)

    stdout_raw = stdout_bytes.decode("utf-8", "replace")
    stderr_raw = stderr_bytes.decode("utf-8", "replace")

    result_raw = ""
    result_error = None
    result: object = None
    if out_path.is_file():
        try:
            result_raw = out_path.read_text(encoding="utf-8")
            # Redact before parsing so a secret smuggled into the child result
            # JSON can never reach the evidence file; the raw hit is still
            # recorded below via ``result_leaked``.
            result = json.loads(_redact(result_raw, secret))
        except (OSError, ValueError) as exc:
            result_error = type(exc).__name__
    else:
        result_error = "NO_RESULT_FILE"
    if not isinstance(result, dict):
        result = {
            "ok": False,
            "mode": mode,
            "error": result_error or "NO_RESULT",
        }
    # Defence in depth: also redact any nested key/value of the parsed result.
    result = _redact_value(result, secret)

    needles = _secret_needles(secret)

    def _hit(raw: bytes) -> bool:
        return any(needle in raw for needle in needles)

    return {
        "returncode": process.returncode,
        "timed_out": timed_out,
        # Streams are redacted before they can reach the evidence file; a raw
        # hit is still recorded as a boolean so the leak check stays honest.
        "stdout": _redact(stdout_raw, secret),
        "stderr": _redact(stderr_raw, secret),
        "stdout_leaked": _hit(stdout_bytes),
        "stderr_leaked": _hit(stderr_bytes),
        "result_leaked": _hit(result_raw.encode("utf-8")),
        "argv": command,
        "result": result,
    }


def _verify(
    root: Path,
    package_root: Path,
    source_hashes: list[dict],
    source_manifest: str,
    head_revision,
) -> dict:
    copied_package = root / "冻结 探针包%#目录" / APP_NAME
    copied_package.parent.mkdir(parents=True)
    shutil.copytree(package_root, copied_package)
    copied_hashes = hash_tree(copied_package)
    copy_equal = source_hashes == copied_hashes

    data_dir = root / "业务 数据%#根" / "data"
    credential_root = root / "凭据 %#密钥根"
    data_dir.mkdir(parents=True)

    local_appdata = root / "合成 LOCALAPPDATA %#"
    local_appdata.mkdir(parents=True)
    temp_dir = root / "临时 TEMP %#"
    temp_dir.mkdir(parents=True)
    env = _clean_env(local_appdata, temp_dir)

    exe = copied_package / f"{APP_NAME}.exe"
    secret = "sk-" + secrets.token_urlsafe(32)

    init_out = root / "init-result.json"
    verify_out = root / "verify-result.json"
    init = _run_child(
        exe, "init", data_dir, credential_root, init_out, secret,
        env, copied_package, CHILD_TIMEOUT,
    )
    verify = _run_child(
        exe, "verify", data_dir, credential_root, verify_out, secret,
        env, copied_package, CHILD_TIMEOUT,
    )

    # Negative control: a *different* random secret must NOT match, proving the
    # decrypt-and-compare is a real check rather than a tautology.
    wrong_secret = "sk-" + secrets.token_urlsafe(32)
    negative_out = root / "negative-result.json"
    negative = _run_child(
        exe, "verify", data_dir, credential_root, negative_out, wrong_secret,
        env, copied_package, CHILD_TIMEOUT,
    )

    # -- source-side expectations (never fatal to the evidence) ------------
    db_errors: list[str] = []
    try:
        expected_head = head_revision()
    except Exception as exc:  # noqa: BLE001 - recorded, not fatal
        expected_head = None
        db_errors.append(f"source-head:{type(exc).__name__}")
    try:
        expected_bundles = _load_source_bundles()
    except Exception as exc:  # noqa: BLE001 - recorded, not fatal
        expected_bundles = {}
        db_errors.append(f"source-bundles:{type(exc).__name__}")

    # -- frozen database facts (guarded so a child failure still has evidence)
    db_path = data_dir / "kindergarten.db"
    frozen_head: str | None = None
    frozen_bundles: dict = {}
    frozen_integrity: dict = {}
    if db_path.is_file():
        try:
            frozen_head = _frozen_head(db_path)
        except Exception as exc:  # noqa: BLE001 - recorded, not fatal
            db_errors.append(f"frozen-head:{type(exc).__name__}")
        try:
            frozen_bundles = _frozen_bundles(db_path)
        except Exception as exc:  # noqa: BLE001 - recorded, not fatal
            db_errors.append(f"frozen-bundles:{type(exc).__name__}")
        try:
            frozen_integrity = _frozen_integrity(db_path)
        except Exception as exc:  # noqa: BLE001 - recorded, not fatal
            db_errors.append(f"frozen-integrity:{type(exc).__name__}")
    else:
        db_errors.append("db-missing")

    init_result = init["result"]
    verify_result = verify["result"]
    key_id = init_result.get("key_id")
    database_uuid = init_result.get("database_uuid")

    dpapi_file = None
    dpapi_acl_valid = False
    dpapi_blob_count = 0
    if key_id and database_uuid:
        key_dir = credential_root / database_uuid
        dpapi_file = key_dir / f"{key_id}.dpapi"
        if key_dir.is_dir():
            dpapi_blob_count = len(list(key_dir.glob("*.dpapi")))
        if dpapi_file.is_file():
            try:
                _validate_credential_acl(dpapi_file)
                dpapi_acl_valid = True
            except Exception as exc:  # noqa: BLE001 - recorded, not fatal
                db_errors.append(f"dpapi-acl:{type(exc).__name__}")

    # -- secret leak scan over the whole synthetic root --------------------
    needles = _secret_needles(secret)
    leak_hits, scan_errors = _scan_tree_for_secret(root, needles)
    stream_leaks = [
        f"{run_result['argv'][2]}:{stream}"
        for run_result in (init, verify)
        for stream, key in (
            ("stdout", "stdout_leaked"),
            ("stderr", "stderr_leaked"),
            ("result", "result_leaked"),
        )
        if run_result[key]
    ]

    key_source_hashes = {
        name: sha256_file(REPO_ROOT / name) for name in KEY_SOURCE_FILES
    }

    init_version = init_result.get("ai_config_version")
    verify_version = verify_result.get("ai_config_version")
    checks = {
        "package_copy_hash_equal": copy_equal,
        "package_file_count": len(source_hashes),
        "init_returncode_zero": init["returncode"] == 0
        and not init["timed_out"],
        "init_ok": bool(init_result.get("ok")),
        "init_frozen": bool(init_result.get("frozen")),
        "init_uses_bundled_migrations": bool(
            init_result.get("migrations_inside_bundle")
            and init_result.get("versions_present")
        ),
        "init_ready": bool(init_result.get("ready")),
        "init_has_secret": bool(init_result.get("has_secret")),
        "init_ai_config_version_1": init_version == 1,
        "verify_returncode_zero": verify["returncode"] == 0
        and not verify["timed_out"],
        "verify_ok": bool(verify_result.get("ok")),
        "verify_frozen": bool(verify_result.get("frozen")),
        "verify_uses_bundled_migrations": bool(
            verify_result.get("migrations_inside_bundle")
            and verify_result.get("versions_present")
        ),
        "verify_ready": bool(verify_result.get("ready")),
        "verify_decrypted_matches": bool(
            verify_result.get("decrypted_matches")
        ),
        "verify_ai_config_version_1": verify_version == 1,
        "config_version_stable": (
            init_version == verify_version and init_version == 1
        ),
        "database_uuid_stable": (
            bool(database_uuid)
            and database_uuid == verify_result.get("database_uuid")
        ),
        "key_id_stable": (
            bool(key_id) and key_id == verify_result.get("key_id")
        ),
        "head_matches_source": frozen_head is not None
        and frozen_head == expected_head,
        "bundles_match_source": bool(expected_bundles)
        and frozen_bundles == expected_bundles,
        "dpapi_blob_count": dpapi_blob_count,
        "dpapi_acl_valid": dpapi_acl_valid,
        "negative_returncode_zero": negative["returncode"] == 0
        and not negative["timed_out"],
        "negative_ok": bool(negative["result"].get("ok")),
        "negative_decrypted_mismatch": negative["result"].get(
            "decrypted_matches"
        )
        is False,
        "frozen_integrity_ok": bool(frozen_integrity.get("integrity_ok")),
        "frozen_fk_clean": frozen_integrity.get(
            "foreign_key_violations"
        )
        == 0,
        "one_config_one_credential_one_receipt": (
            frozen_integrity.get("config_versions") == 1
            and frozen_integrity.get("credentials") == 1
            and frozen_integrity.get("receipts") == 1
        ),
        "secret_scan_complete": not scan_errors,
        "no_secret_leak": not leak_hits
        and not scan_errors
        and not stream_leaks,
    }
    required = (
        "package_copy_hash_equal",
        "init_returncode_zero",
        "init_ok",
        "init_frozen",
        "init_uses_bundled_migrations",
        "init_ready",
        "init_has_secret",
        "init_ai_config_version_1",
        "verify_returncode_zero",
        "verify_ok",
        "verify_frozen",
        "verify_uses_bundled_migrations",
        "verify_ready",
        "verify_decrypted_matches",
        "verify_ai_config_version_1",
        "config_version_stable",
        "database_uuid_stable",
        "key_id_stable",
        "head_matches_source",
        "bundles_match_source",
        "dpapi_acl_valid",
        "negative_returncode_zero",
        "negative_ok",
        "negative_decrypted_mismatch",
        "frozen_integrity_ok",
        "frozen_fk_clean",
        "one_config_one_credential_one_receipt",
        "secret_scan_complete",
        "no_secret_leak",
    )
    overall_ok = all(checks[name] for name in required) and (
        checks["dpapi_blob_count"] == 1
    )

    return {
        "ok": overall_ok,
        "package_root": str(package_root),
        "copied_package_root": str(copied_package),
        "package_hash_manifest_sha256": source_manifest,
        "copied_hash_manifest_sha256": _canonical_manifest(copied_hashes),
        "package_files": source_hashes,
        "key_source_sha256": key_source_hashes,
        "data_dir": str(data_dir),
        "credential_root": str(credential_root),
        "temp_dir": str(temp_dir),
        "expected_head": expected_head,
        "frozen_head": frozen_head,
        "expected_bundles": expected_bundles,
        "frozen_bundles": frozen_bundles,
        "init": init,
        "verify": verify,
        "negative": negative,
        "frozen_integrity": frozen_integrity,
        "db_errors": db_errors,
        "checks": checks,
        "secret_leak_hits": leak_hits,
        "secret_stream_leaks": stream_leaks,
        "secret_scan_errors": scan_errors,
    }


def run(build: bool, keep: bool) -> dict:
    from app.local.migrate import head_revision

    package_root = PACKAGE_DIR / APP_NAME
    if build or not (package_root / f"{APP_NAME}.exe").is_file():
        package_root = _build_package()

    source_hashes = hash_tree(package_root)
    source_manifest = _canonical_manifest(source_hashes)

    root = Path(
        tempfile.mkdtemp(
            prefix="kgm-d2-w1-frozen-", dir=tempfile.gettempdir()
        )
    )
    try:
        return _verify(
            root, package_root, source_hashes, source_manifest, head_revision
        )
    except Exception as exc:  # noqa: BLE001 - still emit redacted evidence
        return {
            "ok": False,
            "fatal_error": type(exc).__name__,
            "package_root": str(package_root),
            "package_hash_manifest_sha256": source_manifest,
            "package_files": source_hashes,
            "checks": {},
        }
    finally:
        if not keep:
            shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the D2 W1 frozen probe")
    parser.add_argument(
        "--build", action="store_true", help="先构建 onedir 探针包"
    )
    parser.add_argument("--keep", action="store_true", help="保留仓外临时目录")
    parser.add_argument(
        "--out", help=f"证据 JSON 输出路径（默认 {DEFAULT_EVIDENCE}）"
    )
    args = parser.parse_args()
    evidence = run(build=args.build, keep=args.keep)
    out_path = Path(args.out) if args.out else DEFAULT_EVIDENCE
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(evidence["checks"], ensure_ascii=False, indent=2))
    print(f"证据已写入：{out_path}")
    return 0 if evidence["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
