"""Bounded parallel Range download of the large package ZIP (2026-11-26).

All servers are real controlled-TLS loopback listeners with throwaway
synthetic CA/leaf identities and synthetic Ed25519 release keys; no real
release, URL, teacher data or credential is involved.

These tests pin the teacher-requested updater acceleration:

- the bounded parallel Range transport reaches ``ready`` with verified
  package bytes and provably overlapping segment requests;
- a server that ignores Range (answers 200) falls back to the consistent
  whole-package download;
- a server that answers 206 with a foreign Content-Range makes the
  segments fail their bounded retries and the whole-package download takes
  over;
- a segment with a correct Content-Range but wrong bytes is never silently
  accepted: the assembled digest mismatch fails with UPDATE_PACKAGE_MISMATCH
  and keeps the failure evidence;
- a truncated segment falls back to the whole-package download;
- a teacher cancel during the parallel download cleans the staging tree.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import ssl
import threading
import time
import uuid
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import update_github
import update_service
from tests.local import w3_tls
from update_identity import AppIdentity
from update_manifest import canonical_json
from update_service import UpdateManager

CURRENT = AppIdentity(
    app_id="kindergarten-manager-next",
    app_name="KindergartenManager",
    channel="stable",
    version="0.1.0",
    build_id=str(uuid.uuid4()),
    package_format="pyinstaller-onedir-zip-v1",
    platform="windows",
    arch="x64",
    python="3.14.7",
    database_revision="20261023_0005_local_history",
)

KEY = Ed25519PrivateKey.generate()
PUBLIC = KEY.public_key().public_bytes(
    serialization.Encoding.Raw, serialization.PublicFormat.Raw
)

_RANGE_RE = re.compile(rb"(?im)^range: bytes=([0-9]+)-([0-9]+)\r?$")

# Larger than one PARALLEL_MIN_SEGMENT_BYTES so the planner produces several
# segments and several workers truly overlap.
LARGE_MEMBER_BYTES = 10 * 1024 * 1024


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_package(tmp_path: Path, *, large_member: int = 0) -> tuple[bytes, str]:
    """A synthetic onedir package zip plus its build id."""
    build_id = str(uuid.uuid4())
    root = "KindergartenManager"
    identity = {
        "app_id": CURRENT.app_id,
        "app_name": CURRENT.app_name,
        "channel": CURRENT.channel,
        "version": "0.2.0",
        "build_id": build_id,
        "package_format": CURRENT.package_format,
        "platform": CURRENT.platform,
        "arch": "x64",
        "python": CURRENT.python,
        "database_revision": "20261024_0006_local_update",
    }
    files: dict[str, bytes] = {
        "KindergartenManager.exe": b"MZ synthetic exe",
        "_internal/frontend/d1.html": b"<!doctype html><title>test</title>",
        "_internal/migrations_local/env.py": b"# synthetic migration\n",
        "_internal/app/assets/word_templates/daily_plan.docx": b"PK synthetic template",
        "_internal/build_identity.json": json.dumps(
            identity, ensure_ascii=False
        ).encode("utf-8"),
    }
    if large_member:
        # Incompressible synthetic payload: the ratio guard in the package
        # verifier rejects extreme compression ratios, so use random bytes.
        files["_internal/synthetic/payload.bin"] = os.urandom(large_member)
    entries = [
        {"path": name, "size": len(data), "sha256": _sha(data)}
        for name, data in sorted(files.items())
    ]
    package_manifest = {
        "schema_version": 1,
        "app_id": CURRENT.app_id,
        "app_name": CURRENT.app_name,
        "channel": CURRENT.channel,
        "version": "0.2.0",
        "build_id": build_id,
        "package_format": CURRENT.package_format,
        "platform": "windows",
        "arch": "x64",
        "database_revision": "20261024_0006_local_update",
        "files": entries,
    }
    files["_internal/package_manifest.json"] = json.dumps(
        package_manifest, ensure_ascii=False, indent=2
    ).encode("utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            archive.writestr(f"{root}/{name}", data)
    return buffer.getvalue(), build_id


def _manifest_bytes(
    *, package_sha: str, package_size: int, build_id: str
) -> bytes:
    payload = {
        "app_id": CURRENT.app_id,
        "channel": CURRENT.channel,
        "version": "0.2.0",
        "build_id": build_id,
        "platform": "windows",
        "arch": "x64",
        "package_format": CURRENT.package_format,
        "package_root": "KindergartenManager",
        "executable": "KindergartenManager.exe",
        "package_url": (
            f"/{update_github.GITHUB_REPO}/releases/download/v0.2.0/"
            f"{update_github.PACKAGE_ASSET}"
        ),
        "package_size": package_size,
        "package_sha256": package_sha,
        "database_revision": "20261024_0006_local_update",
        "supported_source_revisions": [CURRENT.database_revision],
        "release_notes": "并行下载合成更新说明",
        "published_at": "2026-11-26T00:00:00Z",
    }
    envelope = {
        "schema_version": 1,
        "key_id": "test-key",
        "payload": payload,
        "signature": base64.b64encode(KEY.sign(canonical_json(payload))).decode(
            "ascii"
        ),
    }
    return json.dumps(envelope, ensure_ascii=False).encode("utf-8")


def _release() -> dict:
    names = (update_github.MANIFEST_ASSET, update_github.PACKAGE_ASSET)
    return {
        "tag_name": "v0.2.0",
        "draft": False,
        "prerelease": False,
        "published_at": "2026-11-26T00:00:00Z",
        "body": "并行下载合成更新说明",
        "assets": [
            {
                "name": name,
                "browser_download_url": (
                    f"https://github.com/{update_github.GITHUB_REPO}/releases/"
                    f"download/v0.2.0/{name}"
                ),
            }
            for name in names
        ],
    }


def _http(
    body: bytes,
    *,
    status: str = "200 OK",
    content_type: str = "application/json",
    extra_headers: list[str] | None = None,
) -> bytes:
    headers = "".join(f"{line}\r\n" for line in (extra_headers or []))
    return (
        f"HTTP/1.1 {status}\r\nContent-Type: {content_type}\r\n"
        f"{headers}Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
    ).encode("ascii") + body


def _partial(start: int, end: int, total: int, body: bytes) -> bytes:
    return _http(
        body,
        status="206 Partial Content",
        content_type="application/octet-stream",
        extra_headers=[f"Content-Range: bytes {start}-{end}/{total}"],
    )


def _wait_state(manager: UpdateManager, expected: str, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    last = manager.state()
    while time.monotonic() < deadline:
        last = manager.state()
        if last["state"] == expected:
            return last
        time.sleep(0.02)
    raise AssertionError(f"state {expected} not reached; last={last}")


class RangeGitHubTls:
    """A controlled-TLS GitHub mirror/API server with scripted Range behaviour.

    Modes:

    - ``range``: strict 206 answers with exact Content-Range slices (and a
      partner wait so overlapping segment requests are provable);
    - ``ignore``: every package request answers 200 with the full body;
    - ``bad-range``: the 0-0 probe answers correctly, every real segment
      answers 206 with a foreign Content-Range;
    - ``corrupt``: exact Content-Range but the slice bytes are corrupted;
    - ``truncate``: the segment body ends early (connection closed);
    - ``hold``: the segment headers plus a first chunk arrive, the rest is
      held so a teacher cancel can interrupt the transfer.
    """

    MANIFEST_PATH = (
        f"/{update_github.GITHUB_REPO}/releases/download/v0.2.0/"
        f"{update_github.MANIFEST_ASSET}"
    )
    PACKAGE_PATH = (
        f"/{update_github.GITHUB_REPO}/releases/download/v0.2.0/"
        f"{update_github.PACKAGE_ASSET}"
    )

    def __init__(
        self,
        tmp_path: Path,
        *,
        manifest: bytes,
        package: bytes,
        mode: str = "range",
        partner_wait: float = 5.0,
    ):
        self.manifest = manifest
        self.package = package
        self.mode = mode
        self.partner_wait = partner_wait
        self.range_requests = 0
        self.whole_requests = 0
        self.probe_requests = 0
        self.max_concurrent = 0
        self._active = 0
        self._lock = threading.Lock()
        ca_dir = tmp_path / "ca"
        _cert, _key, pem = w3_tls.create_ca(ca_dir)
        leaf_cert, leaf_key = w3_tls.create_leaf(
            ca_dir,
            tmp_path / "leaf",
            hostnames=[
                "api.github.com",
                "github.com",
                update_github.GITHUB_MIRROR_HOST,
            ],
        )
        self.ca_pem = pem.decode("ascii")
        self.server = w3_tls.TlsServer(
            cert=leaf_cert,
            key=leaf_key,
            segment_factory=self._segments,
        ).start()
        self.port = self.server.port

    def source(self) -> update_github.ReleaseSource:
        return update_github.api_source(
            {"test-key": PUBLIC},
            test_only=True,
            ca_pem=self.ca_pem,
            connect_host="127.0.0.1",
            connect_port=self.port,
        )

    def stop(self) -> None:
        self.server.stop()

    def _segments(self, request: bytes):
        head = request.split(b"\r\n\r\n", 1)[0].decode("ascii", "replace")
        parts = head.split(" ")
        path = parts[1] if len(parts) > 1 else ""
        mirror_prefix = "/https://github.com"
        if path.startswith(mirror_prefix + "/"):
            path = path[len(mirror_prefix):]
        if path == update_github.GITHUB_API_PATH:
            return [(_http(json.dumps(_release()).encode()), 0)]
        if path == self.MANIFEST_PATH:
            return [(_http(self.manifest), 0)]
        if path == self.PACKAGE_PATH:
            match = _RANGE_RE.search(request)
            if match is None:
                with self._lock:
                    self.whole_requests += 1
                return [
                    (
                        _http(
                            self.package,
                            content_type="application/octet-stream",
                        ),
                        0,
                    )
                ]
            start = int(match.group(1))
            end = int(match.group(2))
            total = len(self.package)
            is_probe = start == 0 and end == 0
            with self._lock:
                self.range_requests += 1
                if self.mode == "ignore":
                    # The server ignores the Range header entirely.
                    pass
                elif is_probe:
                    self.probe_requests += 1
                else:
                    self._active += 1
                    self.max_concurrent = max(self.max_concurrent, self._active)
            if self.mode == "ignore":
                return [
                    (
                        _http(
                            self.package,
                            content_type="application/octet-stream",
                        ),
                        0,
                    )
                ]
            if is_probe:
                return [(_partial(0, 0, total, self.package[:1]), 0)]
            if self.mode == "bad-range":
                return [(_partial(0, 0, total, self.package[:1]), 0)]
            body = self.package[start : end + 1]
            if self.mode == "corrupt":
                body = bytes(value ^ 0xFF for value in body)
            if self.mode == "truncate":
                return [
                    (
                        _partial(
                            start, end, total, body[: max(1, len(body) // 2)]
                        ),
                        0,
                    )
                ]
            if self.mode == "hold":
                first = max(1, min(64, len(body)))
                return [
                    (_partial(start, end, total, body[:first]), 0),
                    (body[first:], 30.0),
                ]
            # Strict mode: wait for a partner segment so real concurrency is
            # provable; a serial implementation would stall to the timeout.
            deadline = time.monotonic() + self.partner_wait
            while True:
                with self._lock:
                    if self._active >= 2:
                        break
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.01)
            with self._lock:
                self._active -= 1
            return [(_partial(start, end, total, body), 0)]
        return [(_http(b"{}", status="404 Not Found"), 0)]


def _manager(fixture: RangeGitHubTls, tmp_path: Path) -> UpdateManager:
    return UpdateManager(
        CURRENT,
        source=fixture.source(),
        enabled=True,
        staging_root=tmp_path / "staging",
        allow_install=True,
    )


def _check_and_download(manager: UpdateManager) -> dict:
    manager.check()
    available = _wait_state(manager, "available")
    assert available["target"]["version"] == "0.2.0"
    manager.download()
    return available


def test_plan_ranges_covers_total_with_bounded_segments():
    from update_service import (
        PARALLEL_MAX_SEGMENTS,
        PARALLEL_MIN_SEGMENT_BYTES,
        _plan_ranges,
    )

    for total in (1, 100, PARALLEL_MIN_SEGMENT_BYTES, 10 * 1024 * 1024):
        ranges = _plan_ranges(total)
        assert ranges, total
        assert len(ranges) <= PARALLEL_MAX_SEGMENTS
        assert ranges[0][0] == 0
        assert ranges[-1][1] == total - 1
        covered = 0
        previous_end = -1
        for start, end in ranges:
            assert start <= end
            assert start == previous_end + 1
            previous_end = end
            covered += end - start + 1
        assert covered == total
    assert _plan_ranges(0) == []
    # A huge total stays bounded by the segment cap.
    huge = _plan_ranges(PARALLEL_MIN_SEGMENT_BYTES * (PARALLEL_MAX_SEGMENTS + 10))
    assert len(huge) == PARALLEL_MAX_SEGMENTS


def test_content_range_matcher_is_strict():
    from update_service import _content_range_matches

    assert _content_range_matches("bytes 0-0/120", 0, 0, 120)
    assert _content_range_matches("bytes 119-119/120", 119, 119, 120)
    # Optional surrounding whitespace (legal in HTTP header values) is
    # tolerated; every number stays strictly validated.
    assert _content_range_matches(" bytes 4-9/120 ", 4, 9, 120)
    assert _content_range_matches("bytes 4-9/121", 4, 9, 120) is False
    assert _content_range_matches("bytes 5-9/120", 4, 9, 120) is False
    assert _content_range_matches("bytes 4-8/120", 4, 9, 120) is False
    assert _content_range_matches("bytes 4-*/120", 4, 9, 120) is False
    assert _content_range_matches(None, 4, 9, 120) is False
    assert _content_range_matches("bytes 4-9/*", 4, 9, 120) is False


def test_parallel_range_download_reaches_ready_with_real_overlap(tmp_path):
    package, build_id = _make_package(tmp_path, large_member=LARGE_MEMBER_BYTES)
    manifest = _manifest_bytes(
        package_sha=_sha(package),
        package_size=len(package),
        build_id=build_id,
    )
    fixture = RangeGitHubTls(tmp_path, manifest=manifest, package=package)
    manager = _manager(fixture, tmp_path)
    try:
        _check_and_download(manager)
        ready = _wait_state(manager, "ready", timeout=60.0)
        assert ready["progress"]["percent"] == 100
        assert fixture.probe_requests == 1
        assert fixture.whole_requests == 0
        assert fixture.range_requests >= 2
        # The bounded parallel transport really overlapped segment requests.
        assert fixture.max_concurrent >= 2
        payload = manager.install_payload()
        assert payload["package_zip"].read_bytes() == package
        assert (
            payload["staging_dir"] / "KindergartenManager" / "KindergartenManager.exe"
        ).is_file()
        # No segment splice leftovers survive the assembly.
        leftovers = list(payload["staging_dir"].glob("package.zip.seg-*"))
        assert leftovers == []
    finally:
        manager.shutdown()
        fixture.stop()


def test_range_ignored_server_falls_back_to_whole_file(tmp_path):
    package, build_id = _make_package(tmp_path, large_member=LARGE_MEMBER_BYTES)
    manifest = _manifest_bytes(
        package_sha=_sha(package),
        package_size=len(package),
        build_id=build_id,
    )
    fixture = RangeGitHubTls(
        tmp_path, manifest=manifest, package=package, mode="ignore"
    )
    manager = _manager(fixture, tmp_path)
    try:
        _check_and_download(manager)
        ready = _wait_state(manager, "ready", timeout=60.0)
        assert ready["progress"]["percent"] == 100
        # The probe saw a 200 (no strict 206) and requested the whole file.
        assert fixture.whole_requests == 1
        assert fixture.probe_requests == 0
        payload = manager.install_payload()
        assert payload["package_zip"].read_bytes() == package
    finally:
        manager.shutdown()
        fixture.stop()


def test_foreign_content_range_falls_back_to_whole_file(tmp_path):
    package, build_id = _make_package(tmp_path)
    manifest = _manifest_bytes(
        package_sha=_sha(package),
        package_size=len(package),
        build_id=build_id,
    )
    fixture = RangeGitHubTls(
        tmp_path, manifest=manifest, package=package, mode="bad-range"
    )
    manager = _manager(fixture, tmp_path)
    try:
        _check_and_download(manager)
        ready = _wait_state(manager, "ready", timeout=60.0)
        assert ready["progress"]["percent"] == 100
        # The probe passed but the real segment answered a foreign range;
        # bounded retries were exhausted and the whole file decided.
        assert fixture.probe_requests == 1
        assert fixture.whole_requests == 1
        assert fixture.range_requests >= update_service.SEGMENT_ATTEMPTS
        payload = manager.install_payload()
        assert payload["package_zip"].read_bytes() == package
    finally:
        manager.shutdown()
        fixture.stop()


def test_truncated_segment_falls_back_to_whole_file(tmp_path):
    package, build_id = _make_package(tmp_path)
    manifest = _manifest_bytes(
        package_sha=_sha(package),
        package_size=len(package),
        build_id=build_id,
    )
    fixture = RangeGitHubTls(
        tmp_path, manifest=manifest, package=package, mode="truncate"
    )
    manager = _manager(fixture, tmp_path)
    try:
        _check_and_download(manager)
        ready = _wait_state(manager, "ready", timeout=60.0)
        assert ready["progress"]["percent"] == 100
        assert fixture.whole_requests == 1
        assert fixture.range_requests >= update_service.SEGMENT_ATTEMPTS
        payload = manager.install_payload()
        assert payload["package_zip"].read_bytes() == package
    finally:
        manager.shutdown()
        fixture.stop()


def test_corrupt_segment_bytes_are_never_silently_accepted(tmp_path):
    package, build_id = _make_package(tmp_path)
    manifest = _manifest_bytes(
        package_sha=_sha(package),
        package_size=len(package),
        build_id=build_id,
    )
    fixture = RangeGitHubTls(
        tmp_path, manifest=manifest, package=package, mode="corrupt"
    )
    manager = _manager(fixture, tmp_path)
    try:
        _check_and_download(manager)
        failed = _wait_state(manager, "failed", timeout=60.0)
        assert failed["error_code"] == "UPDATE_PACKAGE_MISMATCH"
        assert fixture.whole_requests == 0
        assert fixture.probe_requests == 1
        # The failure evidence is preserved for the maintainer, and no
        # verified package was ever published from the mis-spliced bytes.
        staging_root = tmp_path / "staging"
        failure_files = list(staging_root.rglob("failure.json"))
        assert failure_files, "expected preserved failure evidence"
        assert not list(staging_root.rglob("package.zip"))
    finally:
        manager.shutdown()
        fixture.stop()


def test_parallel_cancel_cleans_staging(tmp_path):
    package, build_id = _make_package(tmp_path, large_member=LARGE_MEMBER_BYTES)
    manifest = _manifest_bytes(
        package_sha=_sha(package),
        package_size=len(package),
        build_id=build_id,
    )
    fixture = RangeGitHubTls(
        tmp_path, manifest=manifest, package=package, mode="hold"
    )
    manager = _manager(fixture, tmp_path)
    try:
        _check_and_download(manager)
        cancelled = manager.cancel()
        assert cancelled["state"] == "downloading"
        final = _wait_state(manager, "cancelled", timeout=30.0)
        assert final["state"] == "cancelled"
        staging_root = tmp_path / "staging"
        assert not list(staging_root.rglob("package.zip.part"))
        assert not list(staging_root.rglob("package.zip.seg-*"))
        assert not list(staging_root.rglob("package.zip"))
    finally:
        manager.shutdown()
        fixture.stop()
