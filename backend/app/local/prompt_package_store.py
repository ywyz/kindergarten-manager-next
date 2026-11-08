"""File-backed prompt package cache and accepted-sequence ledger.

Deliberately outside the SQLite database: restoring an older business archive
must not forget that a higher package release was already accepted and then
replay an older package.  The restore path replaces only the database family
and assets; this cache directory stays in the data root.

Writes are atomic (same-directory temp file + ``os.replace``).  A package is
first written as ``pending.package.json`` and its metadata recorded; only after
the database registration/head update succeeds does it become
``active.package.json`` and the accepted ledger advance.  A crash at any point
therefore leaves either the old active package or a pending package that the
next startup can verify and apply again.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from app.local.base import utc_now
from app.local.prompt_package import MAX_PACKAGE_BYTES, VerifiedPackage

STATE_VERSION = 1
STATE_NAME = "state.json"
ACTIVE_NAME = "active.package.json"
PENDING_NAME = "pending.package.json"


def _empty_state() -> dict[str, Any]:
    return {
        "state_version": STATE_VERSION,
        "accepted": None,
        "active": None,
        "pending": None,
        "last_check": None,
    }


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError:
        return None
    if len(raw) > MAX_PACKAGE_BYTES:
        return None
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="wb",
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
        delete=False,
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        # Windows virus scanners/indexers can briefly hold the target open;
        # retry only this atomic replace, never the package parse/verify.
        for attempt in range(6):
            try:
                os.replace(temp_path, path)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.02)
    except BaseException:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def package_metadata(package: VerifiedPackage) -> dict[str, Any]:
    return {
        "release_sequence": package.release_sequence,
        "content_sha256": package.content_sha256,
        "raw_sha256": package.raw_sha256,
        "published_at": package.published_at,
        "notes": package.notes,
        "key_id": package.key_id,
        "min_client_version": package.min_client_version,
        "max_client_version": package.max_client_version,
        "bundles": [
            {
                "task_type": bundle.task_type,
                "contract_version": bundle.contract_version,
                "default_revision": bundle.default_revision,
                "guidance_sha256": bundle.guidance_hash(),
            }
            for bundle in package.bundles
        ],
    }


class PromptPackageStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.state_path = self.root / STATE_NAME
        self.active_path = self.root / ACTIVE_NAME
        self.pending_path = self.root / PENDING_NAME

    def read_state(self) -> dict[str, Any]:
        value = _read_json(self.state_path)
        if value is None or value.get("state_version") != STATE_VERSION:
            return _empty_state()
        state = _empty_state()
        for key in state:
            if key in value:
                state[key] = value[key]
        if not isinstance(state["accepted"], (dict, type(None))):
            state["accepted"] = None
        if not isinstance(state["active"], (dict, type(None))):
            state["active"] = None
        if not isinstance(state["pending"], (dict, type(None))):
            state["pending"] = None
        if not isinstance(state["last_check"], (dict, type(None))):
            state["last_check"] = None
        return state

    def write_state(self, state: dict[str, Any]) -> None:
        _atomic_write(
            self.state_path,
            (json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )

    def load_active_raw(self) -> bytes | None:
        return self._load_raw(self.active_path)

    def load_pending_raw(self) -> bytes | None:
        return self._load_raw(self.pending_path)

    @staticmethod
    def _load_raw(path: Path) -> bytes | None:
        try:
            data = path.read_bytes()
        except (FileNotFoundError, OSError):
            return None
        if len(data) > MAX_PACKAGE_BYTES:
            return None
        return data

    def stage_pending(self, raw: bytes, package: VerifiedPackage) -> None:
        _atomic_write(self.pending_path, raw)
        state = self.read_state()
        state["pending"] = package_metadata(package)
        self.write_state(state)

    def clear_pending(self) -> None:
        try:
            self.pending_path.unlink(missing_ok=True)
        except OSError:
            pass
        state = self.read_state()
        if state["pending"] is not None:
            state["pending"] = None
            self.write_state(state)

    def activate(
        self,
        raw: bytes,
        package: VerifiedPackage,
        *,
        clear_pending: bool = True,
    ) -> None:
        _atomic_write(self.active_path, raw)
        state = self.read_state()
        meta = package_metadata(package)
        state["active"] = meta
        state["accepted"] = {
            "release_sequence": package.release_sequence,
            "content_sha256": package.content_sha256,
            "accepted_at": utc_now().isoformat(),
            "bundles": meta["bundles"],
        }
        if clear_pending:
            state["pending"] = None
        self.write_state(state)
        if clear_pending:
            try:
                self.pending_path.unlink(missing_ok=True)
            except OSError:
                pass

    def record_check(self, result: dict[str, Any]) -> None:
        state = self.read_state()
        state["last_check"] = result
        self.write_state(state)
