"""Focused tests for the source verifier's pure state/boundary helpers."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import verify_renderer_recovery_window as verifier


class GuardedLock:
    def __init__(self, host) -> None:
        self._host = host
        self._lock = threading.RLock()

    def __enter__(self):
        self._lock.acquire()
        object.__setattr__(self._host, "_lock_owner", threading.get_ident())
        return self

    def __exit__(self, exc_type, exc, tb):
        object.__setattr__(self._host, "_lock_owner", None)
        self._lock.release()
        return False


class GuardedEvent:
    def __init__(self, host) -> None:
        self._host = host
        self._set = False

    def set(self) -> None:
        self._set = True

    def is_set(self) -> bool:
        if object.__getattribute__(self._host, "_lock_owner") != threading.get_ident():
            raise AssertionError("business_ready read without page lock")
        return self._set


class GuardedHost:
    _GUARDED = frozenset(
        {
            "_retired",
            "_page_ready",
            "_page_ticket_bound",
            "_business_ready",
            "_page_ticket",
            "_launch_token",
            "_maintenance_notice",
            "_document_generation",
            "_page_busy",
        }
    )

    def __init__(self) -> None:
        object.__setattr__(self, "_lock_owner", None)
        object.__setattr__(self, "_page_lock", GuardedLock(self))
        object.__setattr__(self, "_business_ready", GuardedEvent(self))
        object.__setattr__(self, "_retired", False)
        object.__setattr__(self, "_page_ready", True)
        object.__setattr__(self, "_page_ticket_bound", True)
        object.__setattr__(self, "_page_ticket", "ticket-old")
        object.__setattr__(self, "_launch_token", "launch-old")
        object.__setattr__(self, "_maintenance_notice", "notice")
        object.__setattr__(self, "_document_generation", 2)
        object.__setattr__(self, "_page_busy", False)

    def __getattribute__(self, name):
        if name in object.__getattribute__(self, "_GUARDED"):
            owner = object.__getattribute__(self, "_lock_owner")
            if owner != threading.get_ident():
                raise AssertionError(f"{name} read without page lock")
        return object.__getattribute__(self, name)

    def set_business_ready(self) -> None:
        with self._page_lock:
            self._business_ready.set()

    def raw_state(self) -> dict:
        with self._page_lock:
            return {
                "retired": self._retired,
                "page_ready": self._page_ready,
                "ticket_bound": self._page_ticket_bound,
                "business_ready": self._business_ready.is_set(),
                "ticket": self._page_ticket,
                "launch_token": self._launch_token,
                "maintenance_notice": self._maintenance_notice,
                "document_generation": self._document_generation,
                "page_busy": self._page_busy,
            }

    def get_bootstrap(self):
        raise AssertionError("get_bootstrap must not be called")


def test_host_page_state_reads_under_lock_without_bootstrap_mutation():
    host = GuardedHost()
    host.set_business_ready()
    before = host.raw_state()
    state = verifier._host_page_state(host)
    after = host.raw_state()
    assert state == before == after
    assert verifier._active_page(state) is True
    with pytest.raises(AssertionError):
        host.get_bootstrap()
    public = verifier._public_host_state(state)
    assert "ticket" not in public and "launch_token" not in public
    assert public["ticket_fingerprint"] is not None
    assert public["launch_fingerprint"] is not None
    assert public["ticket_fingerprint"] != public["launch_fingerprint"]


def test_host_page_state_requires_lock_bound_business_ready_and_not_retired():
    with pytest.raises(RuntimeError):
        verifier._host_page_state(SimpleNamespace())
    host = GuardedHost()
    assert verifier._active_page(verifier._host_page_state(host)) is False
    host.set_business_ready()
    host._page_ticket_bound = False
    assert verifier._active_page(verifier._host_page_state(host)) is False
    host._page_ticket_bound = True
    host._retired = True
    assert verifier._active_page(verifier._host_page_state(host)) is False


def _persist_cli(tmp_path: Path) -> SimpleNamespace:
    tmp_path.mkdir(parents=True, exist_ok=True)
    data = tmp_path / "data"
    data.mkdir()
    (data / "kindergarten.db").write_bytes(b"")
    credential = tmp_path / "credentials"
    credential.mkdir()
    expected = tmp_path / "out" / "expected.json"
    expected.parent.mkdir()
    expected.write_text("{}", encoding="utf-8")
    output = tmp_path / "out" / "child.json"
    return SimpleNamespace(
        data=str(data),
        credential_root=str(credential),
        expected_fingerprint=str(expected),
        persist_out=str(output),
    )


def test_persist_path_validation_rejects_missing_raw_nonfresh_and_overlap(tmp_path):
    cli = _persist_cli(tmp_path / "base")
    paths = verifier._validate_persist_paths(cli)
    assert paths["db"] == Path(cli.data) / "kindergarten.db"

    missing = tmp_path / "missing"
    with pytest.raises(ValueError, match="data root"):
        verifier._validate_persist_paths(
            SimpleNamespace(
                data=str(missing),
                credential_root=cli.credential_root,
                expected_fingerprint=cli.expected_fingerprint,
                persist_out=cli.persist_out,
            )
        )

    no_db = tmp_path / "no-db"
    no_db.mkdir()
    with pytest.raises(ValueError, match="kindergarten.db"):
        verifier._validate_persist_paths(
            SimpleNamespace(
                data=str(no_db),
                credential_root=cli.credential_root,
                expected_fingerprint=cli.expected_fingerprint,
                persist_out=cli.persist_out,
            )
        )

    with pytest.raises(ValueError, match="credential"):
        verifier._validate_persist_paths(
            SimpleNamespace(
                data=cli.data,
                credential_root=str(tmp_path / "missing-credentials"),
                expected_fingerprint=cli.expected_fingerprint,
                persist_out=cli.persist_out,
            )
        )

    with pytest.raises(ValueError, match="expected fingerprint"):
        verifier._validate_persist_paths(
            SimpleNamespace(
                data=cli.data,
                credential_root=cli.credential_root,
                expected_fingerprint=str(tmp_path / "missing-expected.json"),
                persist_out=cli.persist_out,
            )
        )

    with pytest.raises(ValueError, match="raw parent"):
        verifier._validate_persist_paths(
            SimpleNamespace(
                data=str(Path(cli.data) / ".." / "data"),
                credential_root=cli.credential_root,
                expected_fingerprint=cli.expected_fingerprint,
                persist_out=cli.persist_out,
            )
        )

    Path(cli.persist_out).write_text("existing", encoding="utf-8")
    with pytest.raises(ValueError, match="fresh"):
        verifier._validate_persist_paths(cli)

    overlap_root = tmp_path / "overlap"
    overlap_root.mkdir()
    overlap = _persist_cli(overlap_root)
    overlap_out = Path(overlap.data) / "child.json"
    with pytest.raises(ValueError, match="overlap"):
        verifier._validate_persist_paths(
            SimpleNamespace(
                data=overlap.data,
                credential_root=overlap.credential_root,
                expected_fingerprint=overlap.expected_fingerprint,
                persist_out=str(overlap_out),
            )
        )


def test_persist_path_validation_rejects_reparse_component(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)
    cli = _persist_cli(tmp_path)
    with pytest.raises(ValueError, match="reparse"):
        verifier._validate_persist_paths(
            SimpleNamespace(
                data=str(link / "data"),
                credential_root=cli.credential_root,
                expected_fingerprint=cli.expected_fingerprint,
                persist_out=cli.persist_out,
            )
        )


def test_main_output_directory_rejects_sidecars_unknown_files_and_collision(tmp_path):
    parent = tmp_path / "window"
    parent.mkdir()
    verifier._validate_output_directory(parent / "result.json")
    (parent / "unknown.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="fresh and empty"):
        verifier._validate_output_directory(parent / "result.json")

    sidecar_parent = tmp_path / "sidecar-window"
    sidecar_parent.mkdir()
    (sidecar_parent / "recovery-persist-expected.json").write_text(
        "old", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="fresh and empty"):
        verifier._validate_output_directory(sidecar_parent / "result.json")

    collision_parent = tmp_path / "collision-window"
    collision_parent.mkdir()
    with pytest.raises(ValueError, match="collides"):
        verifier._validate_output_directory(
            collision_parent / "recovery-persist-child.json"
        )
    assert (parent / "unknown.txt").read_text(encoding="utf-8") == "keep"


def test_fingerprint_summary_is_compact_and_complete():
    fingerprint = {
        "combined_sha256": "combined",
        "database": {
            "fingerprint_sha256": "database",
            "schema_revision": "revision",
            "tables": {"a": {}, "b": {}},
            "counts": {"rows": 3},
        },
        "resources": {
            "fingerprint_sha256": "resources",
            "file_count": 2,
            "total_bytes": 42,
        },
    }
    summary = verifier._fingerprint_summary(fingerprint)
    assert summary == {
        "combined_sha256": "combined",
        "database_sha256": "database",
        "resources_sha256": "resources",
        "schema_revision": "revision",
        "table_count": 2,
        "resource_count": 2,
        "resource_total_bytes": 42,
        "semantic_counts": {"rows": 3},
    }
