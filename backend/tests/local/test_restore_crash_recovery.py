"""B2 restore file-group crash and controlled-failure matrix.

The heavy synthetic business fixture is reused read-only.  This module adds:

* one independent source root whose package contains an unconsumed
  observation-restore preview (so the prepared auth cleanup has a precise,
  single-column delta), and one independent target root with an extra real
  decodable photo plus a new daily-plan save, making old/new DB rows and image
  bytes materially different;
* real parent-driven process termination at every group-rename boundary where
  the move has already happened but the journal phase has not been updated;
* one-shot controlled failures of the journal flush/write, each old/new group
  move, the terminal journal and the receipt;
* exact field-by-field fingerprints (including runtime fields), full resource
  path/size/SHA-256 comparison, retained protection/old groups, credential
  material hashes and same-machine synthetic DPAPI decryptability;
* a socket guard that counts and refuses every outbound attempt.

No production module is modified.  A failing test preserves only its own
synthetic workspace under a private evidence root for later Codex review.
The root is dynamic (``KGM_CRASH_SITE_ROOT`` or a tool-specific directory under
the system temp), never a hardcoded user profile path; the evidence root and
site are created/verified with ``ensure_private_dir`` and are not auto-deleted.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import sysconfig
import tempfile
import threading
import time
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
from sqlalchemy import text

from app.local import (
    ai_config_service,
    credentials,
    daily_plan_service,
    observation_assets,
    observation_history_service,
    observation_service,
    restore_group,
    restore_journal,
)
from app.local.backup_snapshot import SnapshotService
from app.local.restore_fs import (
    copy_file,
    ensure_private_dir,
    operation_paths,
    tree_manifest,
)
from app.local.restore_recovery import resolve_startup_restore
from app.local.restore_service import RestoreCore
from app.local.restore_types import MaintenanceHooks, RestoreFailure
from app.local.runtime import LocalRuntime
from tests.local.backup_fixture_support import (
    SYNTHETIC_SECRET,
    database_fingerprint,
    resource_fingerprint,
    seed_existing_runtime,
    staging_report,
)
from tests.local.restore_crash_worker import NetworkGuard
from tests.local.support import BACKEND_DIR, LocalTestCase, worker_env


APP_VERSION = "restore-crash-test"
PREVIEWS_TABLE = "local_observation_restore_previews"
WORKER_MODULE = "tests.local.restore_crash_worker"


def _private_site_root() -> Path:
    """Portable evidence root: explicit env override or system temp."""
    override = os.environ.get("KGM_CRASH_SITE_ROOT")
    default = (
        Path(tempfile.gettempdir())
        / "kgm-source-backup-20261030"
        / "command-code-b2-crash"
    )
    root = (
        Path(override).expanduser() if override else default
    ).absolute()
    repository = Path(__file__).resolve().parents[3]
    if root == repository or repository in root.parents:
        raise ValueError(
            "KGM_CRASH_SITE_ROOT must not point inside the repository"
        )
    return root


def _require_evidence_root_outside(root: Path, protected) -> None:
    for candidate in protected:
        candidate = Path(candidate).absolute()
        if root == candidate or candidate in root.parents:
            raise ValueError(
                "evidence root must not be inside the test's synthetic roots"
            )


class _Hooks(MaintenanceHooks):
    def wait_host_idle(self, cancel) -> bool:
        return not cancel.is_set()

    def stop_transport(self) -> bool:
        return True


def _sha256_file(path: str | Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _tree_hashes(root: str | Path) -> list[tuple[str, int, str]]:
    root = Path(root)
    if not root.is_dir():
        return []
    results: list[tuple[str, int, str]] = []
    for current, directories, filenames in os.walk(root):
        directories.sort()
        filenames.sort()
        current_path = Path(current)
        for name in filenames:
            path = current_path / name
            results.append(
                (
                    path.relative_to(root).as_posix(),
                    int(path.stat().st_size),
                    _sha256_file(path),
                )
            )
    return results


def _write_json(path: str | Path, data: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, target)


def _connect_read(db_path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _table_rows_by_id(db_path: str | Path, table: str) -> dict[str, dict]:
    connection = _connect_read(db_path)
    try:
        rows = connection.execute(
            f'SELECT * FROM "{table}"'
        ).fetchall()
        return {str(row["id"]): dict(row) for row in rows}
    finally:
        connection.close()


def _table_ids(db_path: str | Path, table: str) -> set[str]:
    connection = _connect_read(db_path)
    try:
        return {
            str(row[0])
            for row in connection.execute(f'SELECT id FROM "{table}"').fetchall()
        }
    finally:
        connection.close()


def _db_has_id(db_path: str | Path, table: str, row_id: str) -> bool:
    connection = _connect_read(db_path)
    try:
        row = connection.execute(
            f'SELECT 1 FROM "{table}" WHERE id = ?', (row_id,)
        ).fetchone()
        return row is not None
    finally:
        connection.close()


def _preview_null_count(db_path: str | Path) -> int:
    connection = _connect_read(db_path)
    try:
        return int(
            connection.execute(
                f"SELECT COUNT(*) FROM {PREVIEWS_TABLE} WHERE consumed_at IS NULL"
            ).fetchone()[0]
        )
    finally:
        connection.close()


def _db_fp(db_path: str | Path) -> dict:
    return database_fingerprint(db_path, include_runtime_fields=True)


def _resource_paths(resources: dict) -> list[str]:
    return [str(item["path"]) for item in resources["files"]]


def _sorted_files(files) -> list[dict]:
    return sorted(
        [
            {
                "path": str(item["path"]),
                "size": int(item["size"]),
                "sha256": str(item["sha256"]),
            }
            for item in files
        ],
        key=lambda item: item["path"],
    )


def _manifest_files(manifest: dict) -> list[dict]:
    return _sorted_files(
        item
        for item in manifest.get("entries") or []
        if item.get("kind") == "file"
    )


def _jpeg_bytes(size: tuple[int, int] = (160, 120), seed: int = 20261031) -> bytes:
    image = Image.new("RGB", size, (30, 120, 200))
    for x in range(0, size[0], 16):
        for y in range(0, size[1], 16):
            image.putpixel(
                (x, y),
                ((seed + x) % 256, (seed + y) % 256, (seed + x + y) % 256),
            )
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=90)
    return output.getvalue()


def _decrypt_credential(db_path: str | Path, credential_root: str | Path) -> str:
    connection = _connect_read(db_path)
    try:
        state = connection.execute(
            "SELECT profile_id, database_uuid FROM local_ai_state LIMIT 1"
        ).fetchone()
        if state is None:
            raise AssertionError("synthetic database has no local_ai_state")
        rows = connection.execute(
            "SELECT id, key_id, nonce, ciphertext FROM local_ai_credentials "
            "WHERE profile_id = ? AND state = 'active'",
            (state["profile_id"],),
        ).fetchall()
        if len(rows) != 1:
            raise AssertionError(
                f"expected one active synthetic credential, found {len(rows)}"
            )
        row = rows[0]
        store = credentials.CredentialStore(
            credential_root, str(state["database_uuid"])
        )
        master = store.load_master_key(str(row["key_id"]))
        return store.decrypt_secret(
            master,
            credentials.SavedSecret(
                key_id=str(row["key_id"]),
                nonce=bytes(row["nonce"]),
                ciphertext=bytes(row["ciphertext"]),
            ),
            str(state["profile_id"]),
            str(row["id"]),
        )
    finally:
        connection.close()


def _copy_credential_root(source: Path, target: Path) -> None:
    """Copy synthetic DPAPI material into a new restricted-DACL root.

    A plain ``copytree`` would inherit the temporary directory's broader DACL
    and the credential store would (correctly) refuse it.  The restore core's
    public file primitive creates every directory and file with the restricted
    DACL and verifies its own read/write identity; the final SHA-256 set must
    equal the source.
    """
    source = Path(source)
    target = Path(target)
    ensure_private_dir(target)
    for source_dir in sorted(item for item in source.iterdir() if item.is_dir()):
        target_dir = target / source_dir.name
        ensure_private_dir(target_dir)
        for source_file in sorted(
            item for item in source_dir.iterdir() if item.is_file()
        ):
            copy_file(source_file, target_dir / source_file.name)
    if _tree_hashes(source) != _tree_hashes(target):
        raise AssertionError("copied synthetic credential material differs")


def _add_unconsumed_preview(runtime, evidence) -> None:
    session = runtime.session()
    try:
        observation_id = evidence.observation_ids["indoor"]
        current = observation_service.read_current(
            session,
            profile_id=evidence.profile_id,
            observation_id=observation_id,
        )
        preview = observation_history_service.preview_restore(
            session,
            runtime,
            profile_id=evidence.profile_id,
            observation_id=observation_id,
            source_version=1,
            request_id=uuid.uuid4().hex,
            base_draft_revision=current["revision"],
            base_draft_hash=current["payload_hash"],
            term_decision="keep_current",
        )
        if not preview.get("restore_token"):
            raise AssertionError("synthetic restore preview produced no token")
    finally:
        session.close()


def _add_target_content(runtime, evidence) -> dict:
    """Add one real decodable photo and one saved daily plan to the target."""
    session = runtime.session()
    try:
        created = observation_service.create_observation(
            session,
            profile_id=evidence.profile_id,
            request_id=uuid.uuid4().hex,
            record_type="outdoor",
            payload={
                "observation_date": "2026-09-18",
                "record_type": "outdoor",
                "start_time": "09:10",
                "end_time": "09:40",
                "subjects": [{"name": "旧档案幼儿"}],
                "age_years": 5,
                "adult_count": 1,
                "child_count": 12,
                "environment": "沙水区",
                "observation_goal": "旧档案独有观察",
                "observation_process": "旧档案独有的合成观察过程。",
                "support_strategy": "",
            },
        )
        observation_id = created["observation_id"]
        current = observation_service.read_current(
            session,
            profile_id=evidence.profile_id,
            observation_id=observation_id,
        )
        imported = observation_assets.import_asset(
            session,
            runtime,
            profile_id=evidence.profile_id,
            observation_id=observation_id,
            request_id=uuid.uuid4().hex,
            expected_revision=current["revision"],
            stream=io.BytesIO(_jpeg_bytes()),
            display_name="target-only.jpg",
            caption="旧档案独有照片",
        )
        asset_id = imported["asset_id"]
        current = observation_service.read_current(
            session,
            profile_id=evidence.profile_id,
            observation_id=observation_id,
        )
        observation_service.save_observation(
            session,
            profile_id=evidence.profile_id,
            observation_id=observation_id,
            request_id=uuid.uuid4().hex,
            expected_revision=current["revision"],
            payload={
                "observation_goal": "旧档案独有观察",
                "observation_process": "旧档案独有的合成观察过程。",
                "support_strategy": "",
            },
            photos=[{"asset_id": asset_id, "caption": "旧档案独有照片"}],
            save_reason="manual",
        )
        plan, created_plan = daily_plan_service.create_or_open(
            session,
            plan_date=date(2026, 9, 3),
            raw_lesson_plan="旧档案独有教案（2026-10-31 合成）。",
            adopted_content={
                "group_activity": {"process": "旧档案独有活动过程"},
                "reflection": "旧档案独有反思",
            },
        )
        if not created_plan:
            raise AssertionError("the target-only daily plan already existed")
        daily_plan_service.save(
            session,
            plan_id=plan["id"],
            expected_content_version=1,
            adopted_content={
                "group_activity": {"process": "旧档案独有活动过程（已保存）"},
                "reflection": "旧档案独有反思（已保存）",
            },
        )
        session.commit()
    finally:
        session.close()

    asset_root = (
        runtime.data_dir
        / "observations"
        / "assets"
        / observation_id
        / asset_id
    )
    originals = sorted(asset_root.glob("original.*"))
    if len(originals) != 1:
        raise AssertionError("target-only asset has no single managed original")
    with Image.open(originals[0]) as image:
        image.verify()
    with Image.open(originals[0]) as image:
        image_format = image.format
        image_size = image.size
    if image_format != "JPEG" or image_size != (160, 120):
        raise AssertionError("target-only photo is not the expected decodable JPEG")
    files = sorted(
        item.relative_to(runtime.data_dir / "observations" / "assets").as_posix()
        for item in asset_root.rglob("*")
        if item.is_file()
    )
    return {
        "observation_id": observation_id,
        "asset_id": asset_id,
        "asset_prefix": f"{observation_id}/{asset_id}/",
        "plan_id": plan["id"],
        "files": files,
        "decodable": True,
        "format": image_format,
        "size": list(image_size),
    }


class RestoreCrashRecoveryCase(LocalTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls._template = Path(tempfile.mkdtemp(prefix="kgm-restore-crash-template-"))
        cls.addClassCleanup(shutil.rmtree, cls._template, True)
        source = None
        target = None
        guard = NetworkGuard()
        try:
            with guard:
                source = LocalRuntime(
                    cls._template / "source-data",
                    credential_root=cls._template / "source-credentials",
                )
                source.prepare()
                cls.source_evidence = seed_existing_runtime(source)
                _add_unconsumed_preview(source, cls.source_evidence)
                cls.source_credential_hashes = _tree_hashes(source.credential_root)
                cls.source_credential_ok = (
                    _decrypt_credential(source.db_path, source.credential_root)
                    == SYNTHETIC_SECRET
                )
                cls.package = cls._template / "source-package.kgmbackup"
                service = SnapshotService(
                    source,
                    app_version=APP_VERSION,
                    source_identity={"app_version": APP_VERSION},
                )
                service.create(
                    cls.package,
                    password=None,
                    cancel=threading.Event(),
                )
                cls.source_package_sha = _sha256_file(cls.package)
                verified = service.verify(
                    cls.package,
                    password=None,
                    cancel=threading.Event(),
                )
                service.discard_verified(verified)
                cls.source_verified = True
                cls.source_db_path = source.db_path
                source.dispose()
                source = None
                cls.source_fp = _db_fp(cls.source_db_path)
                cls.source_resources = resource_fingerprint(
                    cls.source_db_path.parent
                )
                cls.source_preview_nulls = _preview_null_count(cls.source_db_path)

                target = LocalRuntime(
                    cls._template / "target-data",
                    credential_root=cls._template / "target-credentials",
                )
                target.prepare()
                cls.target_evidence = seed_existing_runtime(target)
                facts = _add_target_content(target, cls.target_evidence)
                cls.target_extra_observation_id = facts["observation_id"]
                cls.target_extra_asset_id = facts["asset_id"]
                cls.target_extra_asset_prefix = facts["asset_prefix"]
                cls.target_extra_plan_id = facts["plan_id"]
                cls.target_extra_files = tuple(facts["files"])
                cls.target_extra_decodable = bool(facts["decodable"])
                wal = target.db_path.with_name(target.db_path.name + "-wal")
                shm = target.db_path.with_name(target.db_path.name + "-shm")
                cls.wal_live = {
                    "wal_exists": wal.is_file(),
                    "wal_bytes": int(wal.stat().st_size) if wal.is_file() else 0,
                    "shm_exists": shm.is_file(),
                }
                cls.target_credential_hashes = _tree_hashes(
                    target.credential_root
                )
                cls.target_credential_ok = (
                    _decrypt_credential(target.db_path, target.credential_root)
                    == SYNTHETIC_SECRET
                )
                cls.target_db_path = (
                    cls._template / "target-data" / "kindergarten.db"
                )
                target.dispose()
                target = None
                cls.wal_after_close = {
                    "wal_exists": wal.exists(),
                    "shm_exists": shm.exists(),
                    "journal_exists": cls.target_db_path.with_name(
                        cls.target_db_path.name + "-journal"
                    ).exists(),
                }
                cls.target_fp = _db_fp(cls.target_db_path)
                cls.target_resources = resource_fingerprint(
                    cls._template / "target-data"
                )
                cls.target_main_sha = _sha256_file(cls.target_db_path)
                cls.target_preview_nulls = _preview_null_count(cls.target_db_path)
            cls.setup_network_attempts = list(guard.attempts)
            if cls.setup_network_attempts:
                raise AssertionError(
                    f"fixture setup attempted network access: {cls.setup_network_attempts}"
                )
            if not cls.source_credential_ok or not cls.target_credential_ok:
                raise AssertionError("synthetic DPAPI material is not decryptable")
        except BaseException:
            if source is not None:
                try:
                    source.dispose()
                except Exception:  # noqa: BLE001 - preserve the setup failure
                    pass
            if target is not None:
                try:
                    target.dispose()
                except Exception:  # noqa: BLE001
                    pass
            try:
                root = _private_site_root()
                _require_evidence_root_outside(root, (cls._template,))
                ensure_private_dir(root)
                site = root / (
                    f"command-code-b2-crash-template-{uuid.uuid4().hex}"
                )
                ensure_private_dir(site)
                shutil.copytree(cls._template, site / "template", dirs_exist_ok=True)
                print(f"PRESERVED TEMPLATE SITE: {site}", file=sys.stderr)
            except Exception as exc:  # noqa: BLE001
                print(f"FAILED TEMPLATE PRESERVATION: {exc}", file=sys.stderr)
            raise
        cls.addClassCleanup(cls._verify_template_unchanged)

    @classmethod
    def _verify_template_unchanged(cls) -> None:
        if _sha256_file(cls.package) != cls.source_package_sha:
            raise AssertionError("source package changed during the crash matrix")
        if _tree_hashes(cls._template / "source-credentials") != (
            cls.source_credential_hashes
        ):
            raise AssertionError("source credential material changed")
        if _tree_hashes(cls._template / "target-credentials") != (
            cls.target_credential_hashes
        ):
            raise AssertionError("target credential material changed")
        if resource_fingerprint(cls._template / "source-data") != (
            cls.source_resources
        ):
            raise AssertionError("source resources changed")
        if resource_fingerprint(cls._template / "target-data") != (
            cls.target_resources
        ):
            raise AssertionError("target resources changed")
        if _db_fp(cls.source_db_path) != cls.source_fp:
            raise AssertionError("source database changed")
        if _db_fp(cls.target_db_path) != cls.target_fp:
            raise AssertionError("target database changed")

    def setUp(self) -> None:
        self._test_failed = False
        try:
            super().setUp()
            cls = type(self)
            self.package = self.tmp_root / "source-package.kgmbackup"
            shutil.copy2(cls.package, self.package)
            self.assertEqual(_sha256_file(self.package), cls.source_package_sha)
            self.target_data = self.tmp_root / "target-data"
            shutil.copytree(cls._template / "target-data", self.target_data)
            self.target_cred = self.tmp_root / "target-credentials"
            _copy_credential_root(
                cls._template / "target-credentials", self.target_cred
            )
            self.assertEqual(
                _tree_hashes(self.target_cred), cls.target_credential_hashes
            )
            self._worker_executable = getattr(
                sys, "_base_executable", sys.executable
            )
            self._my_workers: list[subprocess.Popen] = []
            self.addCleanup(self._reap_my_workers)
            self.addCleanup(self._preserve_site_on_failure)
            self._refresh_old_facts()
        except BaseException:
            self._test_failed = True
            raise

    def tearDown(self) -> None:
        try:
            super().tearDown()
        except BaseException:
            self._test_failed = True
            raise

    def _callTestMethod(self, method) -> None:
        # pytest's unittest adapter records the failure after cleanups and
        # leaves _outcome.success True here, so record it at the call site.
        try:
            super()._callTestMethod(method)
        except BaseException:
            self._test_failed = True
            raise

    def _refresh_old_facts(self) -> None:
        cls = type(self)
        self.target_evidence = cls.target_evidence
        self.source_evidence = cls.source_evidence
        self.source_db_path = cls.source_db_path
        self.source_fp = cls.source_fp
        self.source_resources = cls.source_resources
        self.old_fp = _db_fp(self.target_data / "kindergarten.db")
        self.old_resources = resource_fingerprint(self.target_data)
        self.old_main_sha = _sha256_file(self.target_data / "kindergarten.db")
        self.old_credentials = _tree_hashes(self.target_cred)
        self.assertEqual(self.old_credentials, cls.target_credential_hashes)
        self.assertTrue(
            _decrypt_credential(
                self.target_data / "kindergarten.db", self.target_cred
            )
            == SYNTHETIC_SECRET,
            "copied same-machine synthetic DPAPI material must remain usable",
        )

    # -- worker process plumbing -----------------------------------------
    def _spawn_worker(self, spec: dict) -> tuple[subprocess.Popen, Path]:
        spec_path = self.tmp_root / f"worker-spec-{uuid.uuid4().hex}.json"
        _write_json(spec_path, spec)
        # The uv venv's Scripts/python.exe is a trampoline: Popen.pid would be
        # the trampoline, not the worker.  Spawn the base CPython of the same
        # 3.14 installation with the venv's site-packages on PYTHONPATH so the
        # Popen PID is exactly the worker PID that the parent terminates.
        base_executable = getattr(sys, "_base_executable", sys.executable)
        purelib = sysconfig.get_paths()["purelib"]
        env = worker_env()
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            os.pathsep.join([purelib, existing]) if existing else purelib
        )
        process = subprocess.Popen(
            [base_executable, "-m", WORKER_MODULE, str(spec_path)],
            cwd=str(BACKEND_DIR),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._my_workers.append(process)
        return process, Path(spec["result_file"])

    def _reap_my_workers(self) -> None:
        for process in self._my_workers:
            try:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=30)
            except Exception:  # noqa: BLE001 - cleanup must not hide the test
                try:
                    process.kill()
                except Exception:  # noqa: BLE001
                    pass
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
        self._my_workers.clear()

    @staticmethod
    def _decode(raw: bytes | None) -> str:
        return (raw or b"").decode("utf-8", "replace")

    def _run_kill_worker(self, stage: str, operation_id: str) -> dict:
        marker_path = self.tmp_root / f"marker-{stage}-{uuid.uuid4().hex}.json"
        result_path = self.tmp_root / f"kill-result-{stage}-{uuid.uuid4().hex}.json"
        spec = {
            "mode": "restore_kill",
            "app_version": APP_VERSION,
            "data_dir": str(self.target_data),
            "credential_root": str(self.target_cred),
            "package": str(self.package),
            "operation_id": operation_id,
            "kill_stage": stage,
            "marker_file": str(marker_path),
            "result_file": str(result_path),
        }
        process, _ = self._spawn_worker(spec)
        deadline = time.monotonic() + 180.0
        marker: dict | None = None
        while time.monotonic() < deadline:
            if marker_path.is_file():
                try:
                    marker = json.loads(marker_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    marker = None
                if marker is not None:
                    break
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                result = (
                    result_path.read_text(encoding="utf-8")
                    if result_path.is_file()
                    else "<no result>"
                )
                self.fail(
                    f"worker exited before marker at {stage}: rc={process.returncode}\n"
                    f"stdout={self._decode(stdout)}\nstderr={self._decode(stderr)}\n"
                    f"result={result}"
                )
            time.sleep(0.05)
        if marker is None:
            process.kill()
            stdout, stderr = process.communicate()
            self.fail(
                f"worker never reached marker {stage}\n"
                f"stdout={self._decode(stdout)}\nstderr={self._decode(stderr)}"
            )
        self.assertEqual(marker["pid"], process.pid)
        self.assertEqual(marker["stage"], stage)
        self.assertEqual(marker["operation_id"], operation_id)
        self.assertEqual(marker["python_executable"], self._worker_executable)
        self.assertIsNone(
            process.poll(),
            f"worker had already exited at marker {stage}: {marker}",
        )
        process.kill()
        stdout, stderr = process.communicate(timeout=60)
        self.assertNotEqual(
            process.returncode,
            0,
            f"TerminateProcess expected a non-zero exit\n"
            f"stdout={self._decode(stdout)}\nstderr={self._decode(stderr)}",
        )
        self.assertTrue(marker_path.is_file())
        self.assertEqual(marker.get("network_attempts"), [])
        return marker

    def _run_resume_worker(
        self,
        operation_id: str,
        *,
        write: bool = False,
        expect_observation_id: str | None = None,
    ) -> dict:
        result_path = self.tmp_root / f"resume-{uuid.uuid4().hex}.json"
        spec = {
            "mode": "resume",
            "data_dir": str(self.target_data),
            "credential_root": str(self.target_cred),
            "operation_id": operation_id,
            "result_file": str(result_path),
            "write": bool(write),
        }
        if expect_observation_id:
            spec["expect_observation_id"] = expect_observation_id
        process, _ = self._spawn_worker(spec)
        try:
            stdout, stderr = process.communicate(timeout=180)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            self.fail(
                f"resume worker timed out\nstdout={self._decode(stdout)}\n"
                f"stderr={self._decode(stderr)}"
            )
        result = (
            json.loads(result_path.read_text(encoding="utf-8"))
            if result_path.is_file()
            else None
        )
        self.assertEqual(
            process.returncode,
            0,
            f"resume worker failed rc={process.returncode}\n"
            f"stdout={self._decode(stdout)}\nstderr={self._decode(stderr)}\n"
            f"result={result}",
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.get("network_attempts"), [])
        self.assertEqual(
            result.get("python_executable"), self._worker_executable, result
        )
        if result.get("ok"):
            self.assertFalse(result.get("ai_executor_present"))
        return result

    # -- restore helpers --------------------------------------------------
    def _open_target(self) -> LocalRuntime:
        runtime = self.make_runtime(
            data_dir=self.target_data, credential_root=self.target_cred
        )
        self.assertIsNone(getattr(runtime, "ai_executor", None))
        return runtime

    def _paths(self, operation_id: str):
        return operation_paths(
            SimpleNamespace(
                data_dir=self.target_data, credential_root=self.target_cred
            ),
            operation_id,
            create=False,
        )

    def _journal(self, operation_id: str) -> dict | None:
        return restore_journal.read_journal(self._paths(operation_id))

    def _receipt(self, operation_id: str) -> dict | None:
        return restore_journal.read_receipt(self._paths(operation_id), operation_id)

    def _core_preview_prepare(self, runtime):
        core = RestoreCore(runtime, app_version=APP_VERSION)
        operation_id = uuid.uuid4().hex
        guard = NetworkGuard()
        with guard:
            preview = core.preview(
                self.package,
                None,
                operation_id=operation_id,
                cancel=threading.Event(),
            )
            self.assertEqual(preview.operation_id, operation_id)
            self.assertTrue(preview.profile_present)
            self.assertTrue(preview.profile_name)
            self.assertTrue(preview.credential_configured)
            self.assertFalse(preview.credential_ready)
            source_counts = self.source_fp["counts"]
            self.assertEqual(
                preview.counts["daily_plans"], source_counts["local_daily_plans"]
            )
            self.assertEqual(
                preview.counts["observations"],
                source_counts["local_observation_records"],
            )
            self.assertEqual(
                preview.counts["assets"],
                source_counts["local_observation_assets"],
            )
            prepared = core.prepare(preview, cancel=threading.Event())
        self.assertEqual(guard.attempts, [])
        self.assertEqual(prepared.auth_change_count, 1)
        self.assertEqual(
            prepared.resource_count, self.source_resources["file_count"]
        )
        self.assertEqual(
            prepared.resource_bytes, self.source_resources["total_bytes"]
        )
        return core, preview, prepared, operation_id

    def _install(self, core, prepared, cancel=None):
        guard = NetworkGuard()
        with guard:
            result = core.install(
                prepared,
                hooks=_Hooks(),
                cancel=cancel or threading.Event(),
            )
        self.assertEqual(guard.attempts, [])
        return result

    def _add_new_observation(self, runtime, label: str) -> str:
        guard = NetworkGuard()
        observation_id = None
        with guard:
            session = runtime.session()
            try:
                profile_id = session.execute(
                    text("SELECT id FROM local_profile LIMIT 1")
                ).scalar_one()
                created = observation_service.create_observation(
                    session,
                    profile_id=profile_id,
                    request_id=uuid.uuid4().hex,
                    record_type="public",
                    payload={
                        "observation_date": "2026-09-24",
                        "record_type": "public",
                        "subjects": [{"name": label}],
                        "environment": "积木区",
                        "observation_goal": label,
                        "observation_process": f"{label}：恢复后的正常新写入。",
                        "support_strategy": "",
                    },
                )
                session.commit()
                observation_id = created["observation_id"]
            finally:
                session.close()
        self.assertEqual(guard.attempts, [])
        self.assertIsNotNone(observation_id)
        return observation_id

    # -- assertions -------------------------------------------------------
    def _assert_fp_equal(self, expected: dict, actual: dict, label: str) -> None:
        self.assertEqual(expected["format"], actual["format"], label)
        self.assertEqual(
            expected["schema_revision"], actual["schema_revision"], label
        )
        self.assertEqual(expected["counts"], actual["counts"], label)
        self.assertEqual(expected["excluded_fields"], actual["excluded_fields"], label)
        self.assertEqual(set(expected["tables"]), set(actual["tables"]), label)
        for table in sorted(expected["tables"]):
            self.assertEqual(
                expected["tables"][table],
                actual["tables"][table],
                f"{label}: table {table}",
            )
        self.assertEqual(
            expected["fingerprint_sha256"],
            actual["fingerprint_sha256"],
            label,
        )

    def _assert_resources_equal(
        self, expected: dict, actual: dict, data_dir: Path, label: str
    ) -> None:
        self.assertEqual(expected["file_count"], actual["file_count"], label)
        self.assertEqual(expected["total_bytes"], actual["total_bytes"], label)
        self.assertEqual(expected["files"], actual["files"], label)
        self.assertEqual(
            expected["fingerprint_sha256"],
            actual["fingerprint_sha256"],
            label,
        )
        self.assertEqual(staging_report(data_dir)["files"], [], label)

    def _assert_installed_matches_source(
        self,
        source_db: str | Path,
        installed_db: str | Path,
        source_fp: dict,
        installed_fp: dict,
        label: str,
    ) -> None:
        self.assertEqual(source_fp["excluded_fields"], [], label)
        self.assertEqual(installed_fp["excluded_fields"], [], label)
        self.assertEqual(source_fp["format"], installed_fp["format"], label)
        self.assertEqual(
            source_fp["schema_revision"], installed_fp["schema_revision"], label
        )
        self.assertEqual(source_fp["counts"], installed_fp["counts"], label)
        self.assertEqual(set(source_fp["tables"]), set(installed_fp["tables"]), label)
        for table in sorted(source_fp["tables"]):
            if table == PREVIEWS_TABLE:
                continue
            self.assertEqual(
                source_fp["tables"][table],
                installed_fp["tables"][table],
                f"{label}: table {table}",
            )
        source_meta = source_fp["tables"][PREVIEWS_TABLE]
        installed_meta = installed_fp["tables"][PREVIEWS_TABLE]
        for key in (
            "sql_sha256",
            "columns",
            "metadata_only_columns",
            "db_only_columns",
            "row_count",
        ):
            self.assertEqual(
                source_meta[key], installed_meta[key], f"{label}: previews {key}"
            )
        source_rows = _table_rows_by_id(source_db, PREVIEWS_TABLE)
        installed_rows = _table_rows_by_id(installed_db, PREVIEWS_TABLE)
        self.assertEqual(set(source_rows), set(installed_rows), label)
        null_rows = 0
        changed_rows = 0
        for row_id in sorted(source_rows):
            source_row = source_rows[row_id]
            installed_row = installed_rows[row_id]
            for column in sorted(source_row):
                if column == "consumed_at":
                    continue
                self.assertEqual(
                    source_row[column],
                    installed_row[column],
                    f"{label}: previews row {row_id} column {column}",
                )
            if source_row["consumed_at"] is None:
                null_rows += 1
                self.assertIsNotNone(
                    installed_row["consumed_at"],
                    f"{label}: unconsumed preview {row_id} was not retired",
                )
                changed_rows += 1
            else:
                self.assertEqual(
                    source_row["consumed_at"],
                    installed_row["consumed_at"],
                    f"{label}: previews row {row_id} consumed_at",
                )
        self.assertGreaterEqual(
            null_rows, 1, f"{label}: fixture must contain an unconsumed preview"
        )
        self.assertEqual(changed_rows, null_rows, label)

    def _assert_failure_archive(
        self, operation_id: str, label: str, *, rollback: bool
    ) -> tuple[dict | None, dict | None]:
        """A failed operation must not leave an installed claim.

        The core may keep a non-terminal journal for startup resolution or
        archive the failure into a terminal receipt.  Either shape is accepted,
        but no surviving record may say the new group was installed, and a
        pre-live failure must not claim a live change.
        """
        journal = self._journal(operation_id)
        receipt = self._receipt(operation_id)
        if journal is not None:
            self.assertFalse(journal["terminal"], label)
            self.assertNotEqual(journal.get("phase"), "installed", label)
            if rollback:
                self.assertEqual(journal.get("phase"), "rolled_back", label)
                self.assertIsNotNone(journal.get("first_live_change_at"), label)
            else:
                self.assertIn(
                    journal.get("phase"),
                    ("preparing", "protection_ready", "quiesced"),
                    label,
                )
                self.assertIsNone(journal.get("first_live_change_at"), label)
        if receipt is not None:
            self.assertTrue(receipt["terminal"], label)
            self.assertNotEqual(receipt.get("phase"), "installed", label)
            phases = [
                entry.get("phase") for entry in receipt.get("history") or []
            ]
            self.assertNotIn("installed", phases, label)
            if rollback:
                self.assertIn("rolled_back", phases, label)
                self.assertIsNotNone(
                    receipt.get("first_live_change_at"), label
                )
                self.assertTrue(receipt.get("old"), label)
                self.assertTrue(receipt.get("new"), label)
            else:
                self.assertIsNone(receipt.get("first_live_change_at"), label)
        return journal, receipt

    def _assert_old_exact(self, label: str) -> None:
        live_db = self.target_data / "kindergarten.db"
        self.assertEqual(_sha256_file(live_db), self.old_main_sha, label)
        self._assert_fp_equal(self.old_fp, _db_fp(live_db), label)
        self._assert_resources_equal(
            self.old_resources,
            resource_fingerprint(self.target_data),
            self.target_data,
            label,
        )
        self.assertTrue(
            _db_has_id(live_db, "local_daily_plans", type(self).target_extra_plan_id),
            label,
        )
        self.assertTrue(
            _db_has_id(
                live_db,
                "local_observation_records",
                type(self).target_extra_observation_id,
            ),
            label,
        )
        self.assertTrue(
            any(
                path.startswith(type(self).target_extra_asset_prefix)
                for path in _resource_paths(self.old_resources)
            ),
            label,
        )
        self.assertFalse(
            _db_has_id(live_db, "local_profile", type(self).source_evidence.profile_id),
            label,
        )
        self.assertEqual(_tree_hashes(self.target_cred), self.old_credentials, label)
        self.assertTrue(
            _decrypt_credential(live_db, self.target_cred) == SYNTHETIC_SECRET,
            f"{label}: same-machine synthetic credential must remain usable",
        )

    def _assert_prepared_new_group(self, operation_id: str, label: str) -> None:
        paths = self._paths(operation_id)
        prepared_db = paths.prepared_dir / "db" / "kindergarten.db"
        prepared_assets = paths.prepared_dir / "assets"
        self.assertTrue(prepared_db.is_file(), f"{label}: prepared database missing")
        self.assertTrue(prepared_assets.is_dir(), f"{label}: prepared assets missing")
        self._assert_installed_matches_source(
            self.source_db_path,
            prepared_db,
            self.source_fp,
            _db_fp(prepared_db),
            f"{label}: prepared group",
        )
        self.assertEqual(
            _manifest_files(tree_manifest(prepared_assets, strict_regular=True)),
            _sorted_files(self.source_resources["files"]),
            f"{label}: prepared resources",
        )

    def _assert_old_group_preserved(
        self, operation_id: str, label: str, *, check_credential: bool = False
    ) -> None:
        paths = self._paths(operation_id)
        old_main = paths.old_dir / "db" / "kindergarten.db"
        old_assets = restore_group.old_assets_path(paths)
        self.assertTrue(old_main.is_file(), f"{label}: old main database missing")
        self.assertEqual(_sha256_file(old_main), self.old_main_sha, label)
        self.assertTrue(old_assets.is_dir(), f"{label}: old assets missing")
        self.assertEqual(
            _manifest_files(tree_manifest(old_assets, strict_regular=False)),
            _sorted_files(self.old_resources["files"]),
            f"{label}: old assets",
        )
        self.assertTrue(
            paths.protection_path.is_file(), f"{label}: protection package missing"
        )
        if check_credential:
            self.assertTrue(
                _decrypt_credential(old_main, self.target_cred) == SYNTHETIC_SECRET,
                f"{label}: old encrypted credential/material must remain usable",
            )

    def _assert_protection_matches_old(self, operation_id: str, label: str) -> None:
        paths = self._paths(operation_id)
        self.assertTrue(
            paths.protection_path.is_file(), f"{label}: protection package missing"
        )
        proxy = SimpleNamespace(
            data_dir=self.target_data, credential_root=self.target_cred
        )
        service = SnapshotService(proxy, app_version=APP_VERSION, source_identity={})
        guard = NetworkGuard()
        with guard:
            verified = service.verify(
                paths.protection_path,
                password=None,
                cancel=threading.Event(),
            )
        self.assertEqual(guard.attempts, [])
        try:
            self._assert_fp_equal(
                self.old_fp, _db_fp(verified.database_path), f"{label}: protection"
            )
            protection_assets = (
                Path(verified.resources_root) / "observations" / "assets"
            )
            self.assertEqual(
                _manifest_files(
                    tree_manifest(protection_assets, strict_regular=True)
                ),
                _sorted_files(self.old_resources["files"]),
                f"{label}: protection resources",
            )
        finally:
            service.discard_verified(verified)

    def _assert_new_live(self, operation_id: str, label: str) -> None:
        live_db = self.target_data / "kindergarten.db"
        self._assert_installed_matches_source(
            self.source_db_path,
            live_db,
            self.source_fp,
            _db_fp(live_db),
            label,
        )
        self._assert_resources_equal(
            self.source_resources,
            resource_fingerprint(self.target_data),
            self.target_data,
            label,
        )
        self.assertFalse(
            _db_has_id(
                live_db, "local_daily_plans", type(self).target_extra_plan_id
            ),
            label,
        )
        self.assertFalse(
            _db_has_id(
                live_db,
                "local_observation_records",
                type(self).target_extra_observation_id,
            ),
            label,
        )
        self.assertFalse(
            any(
                path.startswith(type(self).target_extra_asset_prefix)
                for path in _resource_paths(
                    resource_fingerprint(self.target_data)
                )
            ),
            label,
        )
        self.assertTrue(
            _db_has_id(
                live_db, "local_daily_plans", type(self).source_evidence.daily_plan_id
            ),
            label,
        )
        self.assertTrue(
            _db_has_id(
                live_db, "local_profile", type(self).source_evidence.profile_id
            ),
            label,
        )
        self.assertEqual(_tree_hashes(self.target_cred), self.old_credentials, label)

    # -- failure preservation ---------------------------------------------
    def _preserve_site_on_failure(self) -> None:
        failed = bool(getattr(self, "_test_failed", False))
        outcome = getattr(self, "_outcome", None)
        if not failed and outcome is not None:
            if not getattr(outcome, "success", True):
                failed = True
            result = getattr(outcome, "result", None)
            if result is not None:
                for test, _trace in (
                    list(getattr(result, "failures", []))
                    + list(getattr(result, "errors", []))
                ):
                    if getattr(test, "id", lambda: None)() == self.id():
                        failed = True
                        break
        if not failed:
            return
        self._reap_my_workers()
        protected = [
            getattr(self, "tmp_root", None),
            getattr(self, "target_data", None),
            getattr(self, "target_cred", None),
            getattr(type(self), "_template", None),
        ]
        protected = [item for item in protected if item is not None]
        errors: list[str] = []

        def copy(source: Path, destination: Path) -> None:
            try:
                if source.is_dir():
                    shutil.copytree(source, destination, dirs_exist_ok=True)
                elif source.is_file():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
            except BaseException as exc:  # noqa: BLE001 - best effort only
                errors.append(f"{source.name}: {type(exc).__name__}: {exc}")

        try:
            root = _private_site_root()
            _require_evidence_root_outside(root, protected)
            ensure_private_dir(root)
            site = root / (
                f"command-code-b2-crash-site-{uuid.uuid4().hex}"
            )
            ensure_private_dir(site)
            data_site = site / "data"
            data_site.mkdir()
            for item in sorted(self.target_data.iterdir()):
                if item.is_file():
                    copy(item, data_site / item.name)
                elif item.name == ".restore-receipts":
                    copy(item, data_site / ".restore-receipts")
                elif item.name == "observations":
                    assets = item / "assets"
                    if assets.is_dir():
                        copy(assets, site / "assets")
            work = Path(str(self.target_data) + ".restore-work")
            if work.is_dir():
                for op_dir in sorted(item for item in work.iterdir() if item.is_dir()):
                    prepared_db = (
                        op_dir / "prepared" / "db" / "kindergarten.db"
                    )
                    if prepared_db.is_file():
                        copy(
                            prepared_db,
                            site / "prepared" / "db" / "kindergarten.db",
                        )
                    prepared_assets = op_dir / "prepared" / "assets"
                    if prepared_assets.is_dir():
                        copy(prepared_assets, site / "prepared" / "assets")
                    old_db_dir = op_dir / "old" / "db"
                    if old_db_dir.is_dir():
                        for item in sorted(old_db_dir.iterdir()):
                            copy(item, site / "old" / "db" / item.name)
                    old_assets = op_dir / "old" / "assets"
                    if old_assets.is_dir():
                        copy(old_assets, site / "old" / "assets")
            guard = Path(str(self.target_data) + ".restore-guard")
            if guard.is_dir():
                for op_dir in sorted(item for item in guard.iterdir() if item.is_dir()):
                    package = op_dir / "pre-restore.kgmbackup"
                    if package.is_file():
                        copy(
                            package,
                            site / "guard" / f"{op_dir.name}-pre-restore.kgmbackup",
                        )
            copy(self.target_cred, site / "credentials")
            copy(self.package, site / "source-package.kgmbackup")
            _write_json(
                site / "site.json",
                {
                    "test": self.id(),
                    "layout": (
                        "data/: live DB family, receipts, lock; assets/: live "
                        "managed assets; prepared/: prepared DB/assets; old/: "
                        "old DB/assets; guard/: protection package; "
                        "credentials/; source-package.kgmbackup"
                    ),
                    "copy_errors": errors[:8],
                    "note": (
                        "Synthetic crash site only, copied to short mapped "
                        "paths to avoid the WinError 206 long-root boundary. "
                        "No real teacher data or real credentials are included."
                    ),
                },
            )
            print(f"PRESERVED CRASH SITE: {site}", file=sys.stderr)
        except BaseException as exc:  # noqa: BLE001 - never hide the test failure
            print(
                f"FAILED TO PRESERVE CRASH SITE: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )

    # -- tests ------------------------------------------------------------
    def test_old_and_new_synthetic_roots_are_materially_different(self):
        cls = type(self)
        self.assertEqual(cls.setup_network_attempts, [])
        self.assertTrue(cls.source_verified)
        self.assertTrue(cls.source_credential_ok)
        self.assertTrue(cls.target_credential_ok)
        self.assertNotEqual(
            cls.source_evidence.profile_id, cls.target_evidence.profile_id
        )
        source_counts = cls.source_fp["counts"]
        old_counts = cls.target_fp["counts"]
        self.assertGreater(
            old_counts["local_daily_plans"], source_counts["local_daily_plans"]
        )
        self.assertGreater(
            old_counts["local_daily_plan_contents"],
            source_counts["local_daily_plan_contents"],
        )
        self.assertGreater(
            old_counts["local_observation_records"],
            source_counts["local_observation_records"],
        )
        self.assertGreater(
            old_counts["local_observation_assets"],
            source_counts["local_observation_assets"],
        )
        self.assertGreaterEqual(
            cls.target_resources["file_count"],
            cls.source_resources["file_count"] + 3,
        )
        self.assertTrue(cls.target_extra_decodable)
        self.assertTrue(
            any(
                path.startswith(cls.target_extra_asset_prefix)
                for path in _resource_paths(cls.target_resources)
            )
        )
        self.assertFalse(
            any(
                path.startswith(cls.target_extra_asset_prefix)
                for path in _resource_paths(cls.source_resources)
            )
        )
        self.assertTrue(
            _db_has_id(
                cls.target_db_path,
                "local_daily_plans",
                cls.target_extra_plan_id,
            )
        )
        self.assertFalse(
            _db_has_id(
                cls.source_db_path,
                "local_daily_plans",
                cls.target_extra_plan_id,
            )
        )
        self.assertTrue(
            _db_has_id(
                cls.source_db_path,
                "local_daily_plans",
                cls.source_evidence.daily_plan_id,
            )
        )
        self.assertFalse(
            _db_has_id(
                cls.target_db_path,
                "local_daily_plans",
                cls.source_evidence.daily_plan_id,
            )
        )
        self.assertEqual(cls.source_preview_nulls, 1)
        self.assertEqual(cls.target_preview_nulls, 0)
        self.assertTrue(cls.wal_live["wal_exists"])
        self.assertGreater(cls.wal_live["wal_bytes"], 0)
        self.assertTrue(cls.wal_live["shm_exists"])
        self.assertFalse(cls.wal_after_close["wal_exists"])
        self.assertFalse(cls.wal_after_close["shm_exists"])
        self.assertFalse(cls.wal_after_close["journal_exists"])
        self.assertNotEqual(cls.source_fp["fingerprint_sha256"], cls.target_fp["fingerprint_sha256"])
        self.assertNotEqual(
            cls.source_credential_hashes, cls.target_credential_hashes
        )

    def test_journal_flush_failure_before_first_journal_keeps_old(self):
        runtime = self._open_target()
        try:
            core, _preview, prepared, operation_id = self._core_preview_prepare(
                runtime
            )
            original = os.fsync
            state = {"failed": False}

            def fail_once(fd):  # noqa: ANN001
                if not state["failed"]:
                    state["failed"] = True
                    raise OSError(28, "注入：恢复日志刷盘失败")
                return original(fd)

            os.fsync = fail_once
            try:
                result = self._install(core, prepared)
            finally:
                os.fsync = original
            self.assertEqual(result.state, "failed_keep_old", result)
            self.assertIn("RESTORE_SWITCH_FAILED", result.warnings)
        finally:
            runtime.dispose()
        self.assertTrue(state["failed"])
        paths = self._paths(operation_id)
        self._assert_failure_archive(
            operation_id, "journal flush failure", rollback=False
        )
        self.assertFalse(paths.protection_path.exists())
        self._assert_old_exact("journal flush failure")
        self._assert_prepared_new_group(operation_id, "journal flush failure")
        resume = self._run_resume_worker(operation_id)
        self.assertTrue(resume["ok"], resume)
        self._assert_old_exact("journal flush failure after restart")
        self._assert_prepared_new_group(
            operation_id, "journal flush failure after restart"
        )
        self.assertNotEqual(
            resume["notice_state"],
            "installed",
            "a pre-journal failure must not be reported as a completed install",
        )
        self.assertIn(resume["notice_state"], (None, "failed_keep_old"))

    def test_journal_write_failure_in_switching_keeps_old_and_protection(self):
        runtime = self._open_target()
        try:
            core, _preview, prepared, operation_id = self._core_preview_prepare(
                runtime
            )
            original = restore_journal.write_journal

            def fail_switching(paths, journal):  # noqa: ANN001
                if (
                    journal.get("phase") == "switching"
                    and not journal.get("first_live_change_at")
                ):
                    raise RestoreFailure(
                        "RESTORE_JOURNAL_FAILED",
                        "switch",
                        "注入：恢复阶段日志写入失败",
                    )
                return original(paths, journal)

            restore_journal.write_journal = fail_switching
            try:
                result = self._install(core, prepared)
            finally:
                restore_journal.write_journal = original
            self.assertEqual(result.state, "failed_keep_old", result)
            self.assertIn("RESTORE_JOURNAL_FAILED", result.warnings)
        finally:
            runtime.dispose()
        self._assert_failure_archive(
            operation_id, "switching journal failure", rollback=False
        )
        self._assert_old_exact("switching journal failure")
        self._assert_prepared_new_group(operation_id, "switching journal failure")
        self._assert_protection_matches_old(
            operation_id, "switching journal failure"
        )
        resume = self._run_resume_worker(operation_id)
        self.assertTrue(resume["ok"], resume)
        self._assert_old_exact("switching journal failure after restart")
        self._assert_prepared_new_group(
            operation_id, "switching journal failure after restart"
        )
        self.assertNotEqual(
            resume["notice_state"],
            "installed",
            "a journal failure before any live change must not report installed",
        )
        self.assertIn(resume["notice_state"], (None, "failed_keep_old"))

    def test_old_asset_move_failure_rolls_back_complete_old_group(self):
        runtime = self._open_target()
        try:
            core, _preview, prepared, operation_id = self._core_preview_prepare(
                runtime
            )
            original = restore_group.move_live_assets_to_old

            def fail_move(paths):  # noqa: ANN001
                raise RestoreFailure(
                    "RESTORE_SWITCH_FAILED", "switch", "注入：旧资产移动失败"
                )

            restore_group.move_live_assets_to_old = fail_move
            try:
                result = self._install(core, prepared)
            finally:
                restore_group.move_live_assets_to_old = original
            self.assertEqual(result.state, "failed_keep_old", result)
        finally:
            runtime.dispose()
        paths = self._paths(operation_id)
        self._assert_failure_archive(
            operation_id, "old asset move failure", rollback=True
        )
        self._assert_old_exact("old asset move failure")
        self._assert_prepared_new_group(operation_id, "old asset move failure")
        self.assertFalse((paths.old_dir / "assets").exists())
        self.assertTrue(paths.protection_path.is_file())
        resume = self._run_resume_worker(operation_id)
        self.assertTrue(resume["ok"], resume)
        self._assert_old_exact("old asset move failure after restart")
        self._assert_prepared_new_group(
            operation_id, "old asset move failure after restart"
        )
        self.assertNotEqual(
            resume["notice_state"],
            "installed",
            "a rolled-back restore receipt must not be reported as installed",
        )
        self.assertIn(resume["notice_state"], (None, "rolled_back", "failed_keep_old"))

    def test_new_asset_move_failure_rolls_back_complete_old_group(self):
        runtime = self._open_target()
        try:
            core, _preview, prepared, operation_id = self._core_preview_prepare(
                runtime
            )
            original = restore_group.move_prepared_assets_to_live

            def fail_move(paths):  # noqa: ANN001
                raise RestoreFailure(
                    "RESTORE_SWITCH_FAILED", "switch", "注入：新资产安装失败"
                )

            restore_group.move_prepared_assets_to_live = fail_move
            try:
                result = self._install(core, prepared)
            finally:
                restore_group.move_prepared_assets_to_live = original
            self.assertEqual(result.state, "failed_keep_old", result)
        finally:
            runtime.dispose()
        paths = self._paths(operation_id)
        self._assert_failure_archive(
            operation_id, "new asset move failure", rollback=True
        )
        self._assert_old_exact("new asset move failure")
        self._assert_prepared_new_group(
            operation_id, "new asset move failure"
        )
        self.assertFalse((paths.old_dir / "db" / "kindergarten.db").exists())
        self.assertFalse((paths.old_dir / "assets").exists())
        self.assertTrue(paths.protection_path.is_file())
        resume = self._run_resume_worker(operation_id)
        self.assertTrue(resume["ok"], resume)
        self._assert_old_exact("new asset move failure after restart")
        self._assert_prepared_new_group(
            operation_id, "new asset move failure after restart"
        )
        self.assertNotEqual(resume["notice_state"], "installed")
        self.assertIn(
            resume["notice_state"], (None, "rolled_back", "failed_keep_old")
        )

    def test_new_db_move_failure_rolls_back_complete_old_group(self):
        runtime = self._open_target()
        try:
            core, _preview, prepared, operation_id = self._core_preview_prepare(
                runtime
            )
            original = restore_group.move_prepared_db_to_live

            def fail_move(paths):  # noqa: ANN001
                raise RestoreFailure(
                    "RESTORE_SWITCH_FAILED", "switch", "注入：新数据库安装失败"
                )

            restore_group.move_prepared_db_to_live = fail_move
            try:
                result = self._install(core, prepared)
            finally:
                restore_group.move_prepared_db_to_live = original
            self.assertEqual(result.state, "failed_keep_old", result)
        finally:
            runtime.dispose()
        paths = self._paths(operation_id)
        self._assert_failure_archive(
            operation_id, "new db move failure", rollback=True
        )
        self._assert_old_exact("new db move failure")
        self._assert_prepared_new_group(operation_id, "new db move failure")
        self.assertFalse((paths.old_dir / "db" / "kindergarten.db").exists())
        self.assertFalse((paths.old_dir / "assets").exists())
        self.assertTrue(paths.protection_path.is_file())
        resume = self._run_resume_worker(operation_id)
        self.assertTrue(resume["ok"], resume)
        self._assert_old_exact("new db move failure after restart")
        self._assert_prepared_new_group(
            operation_id, "new db move failure after restart"
        )
        self.assertNotEqual(resume["notice_state"], "installed")
        self.assertIn(
            resume["notice_state"], (None, "rolled_back", "failed_keep_old")
        )

    def test_terminal_journal_failure_does_not_reopen_new_and_keeps_old(self):
        runtime = self._open_target()
        try:
            core, _preview, prepared, operation_id = self._core_preview_prepare(
                runtime
            )
            original = restore_journal.terminal_journal

            def fail_terminal(paths, journal):  # noqa: ANN001
                raise RestoreFailure(
                    "RESTORE_JOURNAL_FAILED",
                    "switch",
                    "注入：terminal 日志落盘失败",
                )

            restore_journal.terminal_journal = fail_terminal
            try:
                result = self._install(core, prepared)
            finally:
                restore_journal.terminal_journal = original
            self.assertIn(
                result.state, ("failed_keep_old", "recovery_required"), result
            )
            self.assertNotEqual(result.state, "installed_retired")
            self.assertIsNone(result.receipt_id)
            if result.state == "recovery_required":
                self.assertFalse(result.lease_released)
                self.assertFalse(result.reopen_required)
            else:
                self.assertTrue(result.lease_released)
        finally:
            runtime.dispose()
        paths = self._paths(operation_id)
        journal = self._journal(operation_id)
        self.assertIsNotNone(journal)
        self.assertFalse(journal["terminal"])
        self.assertNotEqual(journal["phase"], "installed")
        self.assertIn(journal["phase"], ("rolled_back", "recovery_required"))
        self.assertIsNone(self._receipt(operation_id))
        live_db = self.target_data / "kindergarten.db"
        self.assertEqual(
            _sha256_file(live_db),
            self.old_main_sha,
            "terminal failure must not leave the new database live",
        )
        self._assert_resources_equal(
            self.old_resources,
            resource_fingerprint(self.target_data),
            self.target_data,
            "terminal failure live group",
        )
        self.assertTrue(
            _db_has_id(
                live_db,
                "local_observation_records",
                type(self).target_extra_observation_id,
            )
        )
        self._assert_prepared_new_group(
            operation_id, "terminal journal failure"
        )
        self.assertTrue(paths.protection_path.is_file())
        for sidecar in ("-wal", "-shm", "-journal"):
            self.assertFalse(
                live_db.with_name(live_db.name + sidecar).exists(),
                "terminal failure left a new-group "
                f"{sidecar} next to the old database; the old group is not "
                "clean/verifiable",
            )
        resume = self._run_resume_worker(operation_id)
        self.assertTrue(resume["ok"], resume)
        self.assertEqual(resume["notice_state"], "rolled_back")
        self.assertTrue(resume["receipt_exists"])
        self._assert_old_exact("terminal journal failure after restart")
        self._assert_prepared_new_group(
            operation_id, "terminal journal failure after restart"
        )

    def test_receipt_failure_after_terminal_continues_then_new_work_survives(self):
        runtime = self._open_target()
        new_observation_id = None
        try:
            core, _preview, prepared, operation_id = self._core_preview_prepare(
                runtime
            )
            paths = self._paths(operation_id)
            original = restore_journal.write_receipt

            def fail_receipt(paths_arg, journal):  # noqa: ANN001
                raise RestoreFailure(
                    "RESTORE_RECEIPT_FAILED",
                    "recovery",
                    "注入：恢复回执写入失败",
                )

            restore_journal.write_receipt = fail_receipt
            try:
                result = self._install(core, prepared)
            finally:
                restore_journal.write_receipt = original
            self.assertEqual(result.state, "installed_retired", result)
            self.assertIn("receipt_archive_pending", result.warnings)
            journal = self._journal(operation_id)
            self.assertIsNotNone(journal)
            self.assertTrue(journal["terminal"])
            self.assertEqual(journal["phase"], "terminal")
            self.assertIsNone(self._receipt(operation_id))
            self._assert_new_live(operation_id, "receipt failure")
            self._assert_old_group_preserved(
                operation_id, "receipt failure", check_credential=True
            )
            self.assertTrue(paths.protection_path.is_file())
            reopened = core.reopen()
            self.assertEqual(reopened.state, "reopened", reopened)
            session = runtime.session()
            try:
                config = ai_config_service.get_config(
                    session, credential_root=self.target_cred
                )
                self.assertTrue(config.configured)
                self.assertFalse(config.ready)
            finally:
                session.close()
            new_observation_id = self._add_new_observation(
                runtime, "恢复后新写"
            )
        finally:
            runtime.dispose()

        self.assertIsNotNone(new_observation_id)
        live_db = self.target_data / "kindergarten.db"
        self.assertTrue(
            _db_has_id(live_db, "local_observation_records", new_observation_id)
        )
        resume_one = self._run_resume_worker(
            operation_id, expect_observation_id=new_observation_id
        )
        self.assertTrue(resume_one["ok"], resume_one)
        self.assertEqual(resume_one["notice_state"], "installed")
        self.assertTrue(resume_one["expected_observation_present"])
        self.assertFalse(resume_one["journal_exists"])
        self.assertTrue(resume_one["receipt_exists"])
        self.assertTrue(resume_one["receipt_terminal"])
        archived_receipt = self._receipt(operation_id)
        self.assertIsNotNone(archived_receipt)
        self.assertIn(
            "installed",
            [
                entry.get("phase")
                for entry in archived_receipt.get("history") or []
            ],
            "the archived receipt must still describe the installed operation",
        )
        self.assertIn(
            archived_receipt.get("result_state"),
            (None, "installed"),
            "the archived receipt must preserve the successful terminal result",
        )
        self._assert_old_group_preserved(
            operation_id, "receipt failure after first restart"
        )
        self.assertFalse(
            _db_has_id(
                live_db, "local_daily_plans", type(self).target_extra_plan_id
            )
        )

        before_replay = _db_fp(live_db)
        stale = dict(self._receipt(operation_id))
        stale["terminal"] = False
        stale["rollback_authority"] = True
        stale["phase"] = "switching"
        restore_journal.write_journal(paths, stale)
        self.assertTrue(paths.journal_path.is_file())
        proxy = SimpleNamespace(
            data_dir=self.target_data, credential_root=self.target_cred
        )
        first = resolve_startup_restore(proxy)
        self.assertIsNotNone(first)
        self.assertEqual(first["state"], "installed")
        self.assertFalse(paths.journal_path.is_file())
        second = resolve_startup_restore(proxy)
        self.assertIsNone(second)
        self._assert_fp_equal(before_replay, _db_fp(live_db), "stale replay")
        self.assertTrue(
            _db_has_id(live_db, "local_observation_records", new_observation_id)
        )
        self.assertTrue(self._receipt(operation_id)["terminal"])

        resume_two = self._run_resume_worker(
            operation_id, expect_observation_id=new_observation_id
        )
        self.assertTrue(resume_two["ok"], resume_two)
        self.assertIsNone(resume_two["notice_state"])
        self.assertTrue(resume_two["expected_observation_present"])
        self.assertTrue(resume_two["receipt_exists"])
        self.assertFalse(resume_two["journal_exists"])
        self.assertEqual(resume_one["counts"], resume_two["counts"])
        self.assertTrue(
            _db_has_id(live_db, "local_observation_records", new_observation_id)
        )
        self.assertFalse(
            _db_has_id(
                live_db, "local_daily_plans", type(self).target_extra_plan_id
            )
        )
        self.assertTrue(
            _db_has_id(
                live_db,
                "local_daily_plans",
                type(self).source_evidence.daily_plan_id,
            )
        )
        self.assertEqual(_tree_hashes(self.target_cred), self.old_credentials)

    def test_parent_kill_after_old_db_rename_with_real_wal_and_post_close_identity(self):
        runtime = self._open_target()
        try:
            wal_observation_id = self._add_new_observation(runtime, "WAL 写后关闭")
            wal = runtime.db_path.with_name(runtime.db_path.name + "-wal")
            shm = runtime.db_path.with_name(runtime.db_path.name + "-shm")
            self.assertTrue(wal.is_file())
            self.assertGreater(wal.stat().st_size, 0)
            self.assertTrue(shm.is_file())
        finally:
            runtime.dispose()
        wal = self.target_data / "kindergarten.db-wal"
        shm = self.target_data / "kindergarten.db-shm"
        journal_side = self.target_data / "kindergarten.db-journal"
        self.assertFalse(wal.exists())
        self.assertFalse(shm.exists())
        self.assertFalse(journal_side.exists())
        self.assertTrue(
            _db_has_id(
                self.target_data / "kindergarten.db",
                "local_observation_records",
                wal_observation_id,
            )
        )
        self._refresh_old_facts()

        operation_id = uuid.uuid4().hex
        marker = self._run_kill_worker("after_old_db_main", operation_id)
        journal = marker["journal"]
        self.assertEqual(journal["phase"], "switching")
        self.assertIsNone(journal["first_live_change_at"])
        self.assertFalse(journal["terminal"])
        self.assertFalse(marker["live_main"])
        self.assertTrue(marker["old_main"])
        self.assertTrue(marker["prepared_main"])
        self.assertTrue(marker["live_assets"])
        self.assertFalse(marker["old_assets"])
        self.assertTrue(marker["prepared_assets"])
        self.assertFalse(marker["receipt_exists"])

        resume = self._run_resume_worker(operation_id)
        self.assertTrue(resume["ok"], resume)
        self.assertEqual(resume["notice_state"], "rolled_back")
        self.assertEqual(
            resume["counts"]["observation_records"],
            self.old_fp["counts"]["local_observation_records"],
        )
        self._assert_old_exact("WAL kill after old db rename")
        self._assert_prepared_new_group(
            operation_id, "WAL kill after old db rename"
        )
        self._assert_protection_matches_old(
            operation_id, "WAL kill after old db rename"
        )
        receipt = self._receipt(operation_id)
        self.assertIsNotNone(receipt)
        self.assertTrue(receipt["terminal"])
        old_db = receipt["old"]["db"]
        self.assertTrue(old_db["kindergarten.db"]["present"])
        self.assertEqual(old_db["kindergarten.db"]["sha256"], self.old_main_sha)
        for sidecar in (
            "kindergarten.db-wal",
            "kindergarten.db-shm",
            "kindergarten.db-journal",
        ):
            self.assertFalse(
                old_db[sidecar]["present"],
                f"post-close old identity must record {sidecar} as absent",
            )
        self.assertTrue(
            _db_has_id(
                self.target_data / "kindergarten.db",
                "local_observation_records",
                wal_observation_id,
            )
        )

    def test_parent_kill_after_old_assets_rename_rolls_back_old(self):
        operation_id = uuid.uuid4().hex
        marker = self._run_kill_worker("after_old_assets", operation_id)
        journal = marker["journal"]
        self.assertEqual(journal["phase"], "switching")
        self.assertIsNotNone(journal["first_live_change_at"])
        self.assertFalse(journal["terminal"])
        self.assertFalse(marker["live_main"])
        self.assertTrue(marker["old_main"])
        self.assertTrue(marker["prepared_main"])
        self.assertFalse(marker["live_assets"])
        self.assertTrue(marker["old_assets"])
        self.assertTrue(marker["prepared_assets"])

        resume = self._run_resume_worker(operation_id)
        self.assertTrue(resume["ok"], resume)
        self.assertEqual(resume["notice_state"], "rolled_back")
        self.assertTrue(resume["receipt_exists"])
        self.assertFalse(resume["journal_exists"])
        self._assert_old_exact("kill after old assets rename")
        self._assert_prepared_new_group(
            operation_id, "kill after old assets rename"
        )
        self.assertTrue(self._paths(operation_id).protection_path.is_file())

    def test_parent_kill_after_new_assets_install_rolls_back_old(self):
        operation_id = uuid.uuid4().hex
        marker = self._run_kill_worker("after_new_assets", operation_id)
        journal = marker["journal"]
        self.assertEqual(journal["phase"], "switching")
        self.assertIsNotNone(journal["first_live_change_at"])
        self.assertFalse(marker["live_main"])
        self.assertTrue(marker["old_main"])
        self.assertTrue(marker["prepared_main"])
        self.assertTrue(marker["live_assets"])
        self.assertTrue(marker["old_assets"])
        self.assertFalse(marker["prepared_assets"])

        resume = self._run_resume_worker(operation_id)
        self.assertTrue(resume["ok"], resume)
        self.assertEqual(resume["notice_state"], "rolled_back")
        self._assert_old_exact("kill after new assets install")
        self._assert_prepared_new_group(
            operation_id, "kill after new assets install"
        )
        self.assertTrue(self._paths(operation_id).protection_path.is_file())

    def test_parent_kill_after_new_db_install_rolls_back_old(self):
        operation_id = uuid.uuid4().hex
        marker = self._run_kill_worker("after_new_db", operation_id)
        journal = marker["journal"]
        self.assertEqual(journal["phase"], "switching")
        self.assertIsNotNone(journal["first_live_change_at"])
        self.assertTrue(marker["live_main"])
        self.assertTrue(marker["old_main"])
        self.assertFalse(marker["prepared_main"])
        self.assertTrue(marker["live_assets"])
        self.assertTrue(marker["old_assets"])
        self.assertFalse(marker["prepared_assets"])

        resume = self._run_resume_worker(operation_id)
        self.assertTrue(resume["ok"], resume)
        self.assertEqual(resume["notice_state"], "rolled_back")
        self._assert_old_exact("kill after new db install")
        self._assert_prepared_new_group(
            operation_id, "kill after new db install"
        )
        self.assertTrue(self._paths(operation_id).protection_path.is_file())

    def test_parent_kill_after_installed_journal_keeps_new_and_preserves_old(self):
        operation_id = uuid.uuid4().hex
        marker = self._run_kill_worker("after_installed_journal", operation_id)
        journal = marker["journal"]
        self.assertEqual(journal["phase"], "installed")
        self.assertFalse(journal["terminal"])
        self.assertFalse(marker["receipt_exists"])
        self.assertTrue(marker["live_main"])
        self.assertTrue(marker["old_main"])
        self.assertTrue(marker["live_assets"])
        self.assertTrue(marker["old_assets"])

        resume = self._run_resume_worker(operation_id)
        self.assertTrue(resume["ok"], resume)
        self.assertEqual(resume["notice_state"], "installed")
        self.assertTrue(resume["receipt_exists"])
        self.assertFalse(resume["journal_exists"])
        self._assert_new_live(operation_id, "kill after installed journal")
        self._assert_old_group_preserved(
            operation_id,
            "kill after installed journal",
            check_credential=True,
        )
        self.assertTrue(self._paths(operation_id).protection_path.is_file())
        reopened = self._open_target()
        try:
            session = reopened.session()
            try:
                config = ai_config_service.get_config(
                    session, credential_root=self.target_cred
                )
                self.assertTrue(config.configured)
                self.assertFalse(config.ready)
            finally:
                session.close()
        finally:
            reopened.dispose()

    def test_parent_kill_after_terminal_journal_archives_receipt_and_keeps_new(self):
        operation_id = uuid.uuid4().hex
        marker = self._run_kill_worker("after_terminal_journal", operation_id)
        journal = marker["journal"]
        self.assertTrue(journal["terminal"])
        self.assertEqual(journal["phase"], "terminal")
        self.assertFalse(marker["receipt_exists"])
        self.assertTrue(marker["live_main"])
        self.assertTrue(marker["old_main"])

        resume = self._run_resume_worker(operation_id)
        self.assertTrue(resume["ok"], resume)
        self.assertEqual(resume["notice_state"], "installed")
        self.assertTrue(resume["receipt_exists"])
        self.assertTrue(resume["receipt_terminal"])
        self.assertFalse(resume["journal_exists"])
        self._assert_new_live(operation_id, "kill after terminal journal")
        self._assert_old_group_preserved(
            operation_id, "kill after terminal journal"
        )
        self.assertTrue(self._paths(operation_id).protection_path.is_file())

    def test_missing_new_component_uses_complete_old_group(self):
        operation_id = uuid.uuid4().hex
        marker = self._run_kill_worker("after_old_assets", operation_id)
        self.assertTrue(marker["old_main"])
        self.assertTrue(marker["old_assets"])
        paths = self._paths(operation_id)
        prepared_db = paths.prepared_dir / "db" / "kindergarten.db"
        self.assertTrue(prepared_db.is_file())
        prepared_assets = tree_manifest(
            paths.prepared_dir / "assets", strict_regular=True
        )
        prepared_db.unlink()

        resume = self._run_resume_worker(operation_id)
        self.assertTrue(resume["ok"], resume)
        self.assertEqual(resume["notice_state"], "rolled_back")
        self.assertTrue(resume["receipt_exists"])
        self._assert_old_exact("missing prepared database")
        self.assertFalse(paths.prepared_dir.joinpath("db", "kindergarten.db").exists())
        self.assertTrue(paths.prepared_dir.joinpath("assets").is_dir())
        self.assertEqual(
            _manifest_files(
                tree_manifest(paths.prepared_dir / "assets", strict_regular=True)
            ),
            _sorted_files(self.source_resources["files"]),
        )
        self.assertTrue(paths.protection_path.is_file())

    def test_corrupt_journal_refuses_write_and_keeps_both_groups(self):
        operation_id = uuid.uuid4().hex
        marker = self._run_kill_worker("after_old_db_main", operation_id)
        self.assertFalse(marker["live_main"])
        self.assertTrue(marker["old_main"])
        self.assertTrue(marker["prepared_main"])
        paths = self._paths(operation_id)
        old_main = paths.old_dir / "db" / "kindergarten.db"
        prepared_main = paths.prepared_dir / "db" / "kindergarten.db"
        old_assets = tree_manifest(
            self.target_data / "observations" / "assets", strict_regular=False
        )
        old_main_sha = _sha256_file(old_main)
        prepared_main_sha = _sha256_file(prepared_main)
        original_bytes = paths.journal_path.read_bytes()
        corrupted = original_bytes.replace(
            b'"phase":"switching"', b'"phase":"switchinG"'
        )
        self.assertNotEqual(corrupted, original_bytes)
        paths.journal_path.write_bytes(corrupted)

        resume = self._run_resume_worker(operation_id)
        self.assertFalse(resume["ok"], resume)
        self.assertEqual(
            resume.get("error_code"), "LOCAL_RESTORE_RECOVERY_REQUIRED", resume
        )
        self.assertTrue(paths.journal_path.is_file())
        self.assertEqual(paths.journal_path.read_bytes(), corrupted)
        self.assertFalse(restore_journal.receipt_path(paths, operation_id).exists())
        self.assertFalse((self.target_data / "kindergarten.db").exists())
        self.assertTrue(old_main.is_file())
        self.assertEqual(_sha256_file(old_main), old_main_sha)
        self.assertTrue(prepared_main.is_file())
        self.assertEqual(_sha256_file(prepared_main), prepared_main_sha)
        self.assertEqual(
            _manifest_files(
                tree_manifest(
                    self.target_data / "observations" / "assets",
                    strict_regular=False,
                )
            ),
            _manifest_files(old_assets),
            "unknown journal must keep the live old assets untouched",
        )
        self.assertTrue(paths.protection_path.is_file())
        self.assertEqual(_tree_hashes(self.target_cred), self.old_credentials)
