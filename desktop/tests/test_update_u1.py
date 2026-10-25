"""D3-U U1 discovery/download/verification tests (real controlled TLS).

All program/data/credential roots are pytest temporary directories. The TLS
certificate and Ed25519 keys are throwaway test identities; no real release
key, URL, teacher data or credential is used.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import ssl
import subprocess
import threading
import time
import uuid
import zipfile
from pathlib import Path

import pytest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from tests.local import w3_tls

import d1_host_api
import update_fs
from update_identity import AppIdentity
from update_manifest import canonical_json, parse_signed_manifest
from update_service import UpdateManager
from update_trust import ReleaseConfigError, ReleaseSource, load_release_source


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


def _http(body: bytes, *, status: str = "200 OK", content_type: str = "application/json") -> bytes:
    return (
        f"HTTP/1.1 {status}\r\nContent-Type: {content_type}\r\n"
        f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
    ).encode("ascii") + body


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_package(
    tmp_path: Path,
    *,
    bad_member: str | None = None,
    extra_members: list[tuple[str, bytes]] | None = None,
    symlink_member: str | None = None,
    identity_arch: str = "x64",
    unrelated_directory: bool = False,
    manifest_schema_bool: bool = False,
    duplicate_manifest_key: bool = False,
) -> tuple[Path, str, str, int]:
    build_id = str(uuid.uuid4())
    root = "KindergartenManager"
    tmp_path.mkdir(parents=True, exist_ok=True)
    files: dict[str, bytes] = {
        "KindergartenManager.exe": b"MZ synthetic exe",
        "_internal/frontend/d1.html": b"<!doctype html><title>test</title>",
        "_internal/migrations_local/env.py": b"# synthetic migration\n",
        "_internal/app/assets/word_templates/daily_plan.docx": b"PK synthetic template",
    }
    identity = {
        "app_id": CURRENT.app_id,
        "app_name": CURRENT.app_name,
        "channel": CURRENT.channel,
        "version": "0.2.0",
        "build_id": build_id,
        "package_format": CURRENT.package_format,
        "platform": CURRENT.platform,
        "arch": identity_arch,
        "python": CURRENT.python,
        "database_revision": "20261024_0006_local_update",
    }
    files["_internal/build_identity.json"] = json.dumps(identity, ensure_ascii=False).encode("utf-8")
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
        "platform": CURRENT.platform,
        "arch": CURRENT.arch,
        "database_revision": "20261024_0006_local_update",
        "files": entries,
    }
    manifest_text = json.dumps(package_manifest, ensure_ascii=False, indent=2)
    if manifest_schema_bool:
        manifest_text = manifest_text.replace('"schema_version": 1', '"schema_version": true', 1)
    if duplicate_manifest_key:
        manifest_text = manifest_text.replace(
            '"schema_version": 1',
            '"schema_version": 1, "schema_version": 1',
            1,
        )
    files["_internal/package_manifest.json"] = manifest_text.encode("utf-8")
    if bad_member:
        files[bad_member] = b"bad"
    for name, data in extra_members or []:
        files[name] = data
    package = tmp_path / "package.zip"
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            archive.writestr(f"{root}/{name}", data)
        if unrelated_directory:
            archive.writestr("Other/", b"")
            archive.writestr("Other/evil.txt", b"evil")
        if symlink_member:
            info = zipfile.ZipInfo(f"{root}/{symlink_member}")
            info.create_system = 3
            info.external_attr = (0o120777 << 16)
            archive.writestr(info, b"target")
    raw = package.read_bytes()
    return package, build_id, _sha(raw), len(raw)


def _metadata(
    package_sha: str,
    package_size: int,
    build_id: str,
    private_key: Ed25519PrivateKey,
    *,
    version: str = "0.2.0",
    key_id: str = "test-key",
    platform: str = "windows",
) -> bytes:
    payload = {
        "app_id": CURRENT.app_id,
        "channel": CURRENT.channel,
        "version": version,
        "build_id": build_id,
        "platform": platform,
        "arch": CURRENT.arch,
        "package_format": CURRENT.package_format,
        "package_root": "KindergartenManager",
        "executable": "KindergartenManager.exe",
        "package_url": "/releases/package.zip",
        "package_size": package_size,
        "package_sha256": package_sha,
        "database_revision": "20261024_0006_local_update",
        "supported_source_revisions": [CURRENT.database_revision],
        "release_notes": "U1 合成更新说明\n第二行",
        "published_at": "2026-10-24T00:00:00Z",
    }
    signature = private_key.sign(canonical_json(payload))
    envelope = {
        "schema_version": 1,
        "key_id": key_id,
        "payload": payload,
        "signature": base64.b64encode(signature).decode("ascii"),
    }
    return json.dumps(envelope, ensure_ascii=False).encode("utf-8")


class TlsFixture:
    def __init__(self, tmp_path: Path):
        ca_dir = tmp_path / "ca"
        _cert, _key, pem = w3_tls.create_ca(ca_dir)
        leaf_cert, leaf_key = w3_tls.create_leaf(ca_dir, tmp_path / "leaf")
        self.ca_pem = pem.decode("ascii")
        self.leaf_cert = leaf_cert
        self.leaf_key = leaf_key
        self.ca_dir = ca_dir

    def source(self, port: int) -> ReleaseSource:
        return ReleaseSource(
            origin=f"https://api.example.com:{port}",
            metadata_path="/stable/windows-x64/manifest.json",
            public_keys={"test-key": _public_bytes(self.private_key)},
            ca_pem=self.ca_pem,
            connect_host="127.0.0.1",
            server_hostname="api.example.com",
            test_only=True,
        )

    def make_key(self) -> Ed25519PrivateKey:
        self.private_key = Ed25519PrivateKey.generate()
        return self.private_key


def _public_bytes(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )


class BarrierTlsServer:
    """A real TLS server that holds the remaining body behind an Event."""

    def __init__(
        self,
        cert: Path,
        key: Path,
        metadata: bytes,
        package: bytes,
        *,
        hold_metadata: bool = False,
    ):
        self.metadata = metadata
        self.package = package
        self.hold_metadata = hold_metadata
        self.metadata_started = threading.Event()
        self.package_started = threading.Event()
        self.release = threading.Event()
        self.requests: list[bytes] = []
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=str(cert), keyfile=str(key))
        self._context = context
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(4)
        self._sock.settimeout(0.2)
        self.port = int(self._sock.getsockname()[1])
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except (socket.timeout, TimeoutError):
                continue
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        tls = None
        try:
            tls = self._context.wrap_socket(conn, server_side=True)
            tls.settimeout(10)
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = tls.recv(65536)
                if not chunk:
                    return
                data += chunk
            self.requests.append(data)
            if b"/stable/windows-x64/manifest.json" in data:
                body = self.metadata
                header = (
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                    b"Connection: close\r\nContent-Length: "
                    + str(len(body)).encode()
                    + b"\r\n\r\n"
                )
                first = max(1, min(64, len(body) // 2))
                tls.sendall(header + body[:first])
                if self.hold_metadata:
                    self.metadata_started.set()
                    self.release.wait(10)
                    try:
                        tls.sendall(body[first:])
                    except OSError:
                        pass
                else:
                    tls.sendall(body[first:])
                return
            body = self.package
            header = (
                b"HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\n"
                b"Connection: close\r\nContent-Length: "
                + str(len(body)).encode()
                + b"\r\n\r\n"
            )
            first = max(1, len(body) // 2)
            tls.sendall(header + body[:first])
            self.package_started.set()
            # Hold the remaining bytes until the test releases the barrier.
            self.release.wait(10)
            try:
                tls.sendall(body[first:])
            except OSError:
                pass
        except Exception:
            pass
        finally:
            for obj in (tls, conn):
                if obj is not None:
                    try:
                        obj.close()
                    except Exception:
                        pass

    def stop(self):
        self._stop.set()
        self.release.set()
        try:
            self._sock.close()
        except OSError:
            pass


def _wait(manager: UpdateManager, states: set[str], timeout: float = 8.0) -> dict:
    deadline = time.monotonic() + timeout
    last = manager.state()
    while time.monotonic() < deadline:
        last = manager.state()
        if last["state"] in states:
            return last
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {states}; last={last}")


def test_unconfigured_and_source_run_are_offline(tmp_path):
    disabled = UpdateManager(CURRENT, source=None, enabled=False, staging_root=tmp_path / "u")
    assert disabled.state()["state"] == "disabled"
    assert disabled.check()["state"] == "disabled"
    unconfigured = UpdateManager(CURRENT, source=None, enabled=True, staging_root=tmp_path / "u")
    assert unconfigured.state()["state"] == "unconfigured"
    assert unconfigured.check()["state"] == "unconfigured"
    assert load_release_source(tmp_path / "missing.json") is None


def test_release_config_contract_loads_fixed_public_source(tmp_path):
    key = Ed25519PrivateKey.generate()
    public = base64.b64encode(_public_bytes(key)).decode("ascii")
    config = tmp_path / "update_release.json"
    config.write_text(
        json.dumps(
            {
                "origin": "https://updates.example.com",
                "metadata_path": "/stable/windows-x64/manifest.json",
                "channel": "stable",
                "public_keys": {"release-key": public},
            }
        ),
        encoding="utf-8",
    )
    source = load_release_source(config)
    assert source is not None
    assert source.configured
    assert source.origin == "https://updates.example.com"
    assert source.metadata_path.endswith("/manifest.json")


def test_private_product_source_is_rejected_before_network(tmp_path):
    source = ReleaseSource(
        origin="https://127.0.0.1:9",
        metadata_path="/stable/windows-x64/manifest.json",
        public_keys={"k": b"0" * 32},
    )
    with pytest.raises(ReleaseConfigError):
        source.validate()
    manager = UpdateManager(CURRENT, source=source, staging_root=tmp_path / "u")
    assert manager.state()["state"] == "unconfigured"
    assert manager.state()["error_code"] == "UPDATE_CONFIG_INVALID"
    assert manager.check()["state"] == "unconfigured"


def test_invalid_source_performs_zero_network_calls(tmp_path):
    fixture = TlsFixture(tmp_path)
    key = fixture.make_key()
    requests: list[bytes] = []

    def factory(request: bytes):
        requests.append(request)
        return _http(b"{}")

    server = w3_tls.TlsServer(
        cert=fixture.leaf_cert, key=fixture.leaf_key, reply_factory=factory
    ).start()
    source = ReleaseSource(
        origin=f"https://api.example.com:{server.port}",
        metadata_path="/bad?query",
        public_keys={"test-key": _public_bytes(key)},
        ca_pem=fixture.ca_pem,
        connect_host="127.0.0.1",
        server_hostname="api.example.com",
        test_only=True,
    )
    manager = UpdateManager(CURRENT, source=source, staging_root=tmp_path / "updates")
    try:
        assert manager.state()["state"] == "unconfigured"
        assert manager.check()["state"] == "unconfigured"
        assert requests == []
    finally:
        assert manager.shutdown() is True
        server.stop()


def test_staging_root_file_reports_explicit_failure(tmp_path):
    package, build_id, package_sha, package_size = _make_package(tmp_path)
    fixture = TlsFixture(tmp_path)
    key = fixture.make_key()
    metadata = _metadata(package_sha, package_size, build_id, key)
    requests: list[bytes] = []

    def factory(request: bytes):
        requests.append(request)
        if b"/manifest.json" in request:
            return _http(metadata)
        return _http(package.read_bytes(), content_type="application/octet-stream")

    server = w3_tls.TlsServer(
        cert=fixture.leaf_cert, key=fixture.leaf_key, reply_factory=factory
    ).start()
    staging_file = tmp_path / "staging-is-a-file"
    staging_file.write_bytes(b"not a directory")
    manager = UpdateManager(
        CURRENT,
        source=fixture.source(server.port),
        staging_root=staging_file,
    )
    try:
        manager.check()
        _wait(manager, {"available"})
        manager.download()
        failed = manager.state()
        assert failed["error_code"] == "UPDATE_STAGING_UNAVAILABLE"
        assert failed["install_available"] is False
        assert all(b"/manifest.json" in request for request in requests)
    finally:
        assert manager.shutdown() is True
        server.stop()


def test_real_tls_check_and_download(tmp_path):
    package, build_id, package_sha, package_size = _make_package(tmp_path)
    fixture = TlsFixture(tmp_path)
    key = fixture.make_key()
    metadata = _metadata(package_sha, package_size, build_id, key)
    requests: list[bytes] = []

    def factory(request: bytes):
        requests.append(request)
        if b"/stable/windows-x64/manifest.json" in request:
            return _http(metadata)
        if b"/releases/package.zip" in request:
            return _http(package.read_bytes(), content_type="application/octet-stream")
        return _http(b"{}", status="404 Not Found")

    server = w3_tls.TlsServer(
        cert=fixture.leaf_cert, key=fixture.leaf_key, reply_factory=factory
    ).start()
    manager = UpdateManager(
        CURRENT,
        source=fixture.source(server.port),
        staging_root=tmp_path / "updates",
    )
    try:
        manager.check()
        available = _wait(manager, {"available"})
        assert available["target"]["version"] == "0.2.0"
        assert available["target"]["release_notes"].startswith("U1 合成更新说明")
        assert available["install_available"] is False
        manager.download()
        ready = _wait(manager, {"ready"})
        assert ready["install_available"] is False
        assert ready["progress"]["percent"] == 100
        assert (tmp_path / "updates" / ready["download_id"] / "package.zip").is_file()
        assert len(requests) == 2
    finally:
        manager.shutdown()
        server.stop()


def test_manual_check_deduplicates(tmp_path):
    package, build_id, package_sha, package_size = _make_package(tmp_path)
    fixture = TlsFixture(tmp_path)
    key = fixture.make_key()
    metadata = _metadata(package_sha, package_size, build_id, key)
    requests: list[bytes] = []

    def segments(request: bytes):
        requests.append(request)
        if b"/stable/windows-x64/manifest.json" in request:
            return [(_http(metadata), 0.3)]
        return [_http(package.read_bytes(), content_type="application/octet-stream")]

    server = w3_tls.TlsServer(
        cert=fixture.leaf_cert, key=fixture.leaf_key, segment_factory=segments
    ).start()
    manager = UpdateManager(
        CURRENT,
        source=fixture.source(server.port),
        staging_root=tmp_path / "updates",
    )
    try:
        first = manager.check()
        second = manager.check()
        assert first["state"] == "checking"
        assert second["state"] == "checking"
        _wait(manager, {"available"})
        assert len(requests) == 1
    finally:
        manager.shutdown()
        server.stop()


def test_up_to_date_and_bad_signature(tmp_path):
    package, build_id, package_sha, package_size = _make_package(tmp_path)
    fixture = TlsFixture(tmp_path)
    key = fixture.make_key()
    same = _metadata(package_sha, package_size, build_id, key, version="0.1.0")
    wrong = _metadata(package_sha, package_size, build_id, Ed25519PrivateKey.generate())

    for body, expected in ((same, "up_to_date"), (wrong, "failed")):
        def factory(request: bytes, body=body):
            if b"/manifest.json" in request:
                return _http(body)
            return _http(b"{}", status="404 Not Found")

        server = w3_tls.TlsServer(
            cert=fixture.leaf_cert, key=fixture.leaf_key, reply_factory=factory
        ).start()
        manager = UpdateManager(
            CURRENT,
            source=fixture.source(server.port),
            staging_root=tmp_path / f"updates-{expected}",
        )
        try:
            manager.check()
            state = _wait(manager, {expected})
            if expected == "failed":
                assert state["error_code"] == "UPDATE_METADATA_UNTRUSTED"
        finally:
            manager.shutdown()
            server.stop()


def test_wrong_platform_metadata_rejected(tmp_path):
    package, build_id, package_sha, package_size = _make_package(tmp_path)
    fixture = TlsFixture(tmp_path)
    key = fixture.make_key()
    metadata = _metadata(package_sha, package_size, build_id, key, platform="linux")

    def factory(request: bytes):
        if b"/manifest.json" in request:
            return _http(metadata)
        return _http(b"{}", status="404 Not Found")

    server = w3_tls.TlsServer(
        cert=fixture.leaf_cert, key=fixture.leaf_key, reply_factory=factory
    ).start()
    manager = UpdateManager(
        CURRENT,
        source=fixture.source(server.port),
        staging_root=tmp_path / "updates",
    )
    try:
        manager.check()
        failed = _wait(manager, {"failed"})
        assert failed["error_code"] == "UPDATE_METADATA_INVALID"
        assert failed["install_available"] is False
    finally:
        manager.shutdown()
        server.stop()


def test_package_size_and_hash_mismatch_preserve_failure(tmp_path):
    package, build_id, package_sha, package_size = _make_package(tmp_path)
    fixture = TlsFixture(tmp_path)
    key = fixture.make_key()
    cases = [
        ("size", _metadata(package_sha, package_size + 1, build_id, key)),
        ("hash", _metadata("0" * 64, package_size, build_id, key)),
    ]
    for name, metadata in cases:
        case_root = tmp_path / name
        case_root.mkdir(parents=True, exist_ok=True)
        fixture_case = TlsFixture(case_root)
        key_case = fixture_case.make_key()
        # Re-sign for this case's fixture key with the same payload values.
        if name == "size":
            metadata = _metadata(package_sha, package_size + 1, build_id, key_case)
        else:
            metadata = _metadata("0" * 64, package_size, build_id, key_case)

        def factory(request: bytes, metadata=metadata):
            if b"/manifest.json" in request:
                return _http(metadata)
            return _http(package.read_bytes(), content_type="application/octet-stream")

        server = w3_tls.TlsServer(
            cert=fixture_case.leaf_cert,
            key=fixture_case.leaf_key,
            reply_factory=factory,
        ).start()
        manager = UpdateManager(
            CURRENT,
            source=fixture_case.source(server.port),
            staging_root=case_root / "updates",
        )
        try:
            manager.check()
            _wait(manager, {"available"})
            manager.download()
            failed = _wait(manager, {"failed"})
            assert failed["error_code"] == "UPDATE_PACKAGE_MISMATCH", (name, failed)
            assert (case_root / "updates" / failed["download_id"] / "failure.json").is_file()
        finally:
            manager.shutdown()
            server.stop()


def test_zip_ads_path_rejected_and_failure_preserved(tmp_path):
    package, build_id, package_sha, package_size = _make_package(
        tmp_path, bad_member="file:ads.txt"
    )
    fixture = TlsFixture(tmp_path)
    key = fixture.make_key()
    metadata = _metadata(package_sha, package_size, build_id, key)

    def factory(request: bytes):
        if b"/manifest.json" in request:
            return _http(metadata)
        return _http(package.read_bytes(), content_type="application/octet-stream")

    server = w3_tls.TlsServer(
        cert=fixture.leaf_cert, key=fixture.leaf_key, reply_factory=factory
    ).start()
    manager = UpdateManager(
        CURRENT,
        source=fixture.source(server.port),
        staging_root=tmp_path / "updates",
    )
    try:
        manager.check()
        _wait(manager, {"available"})
        manager.download()
        failed = _wait(manager, {"failed"})
        assert failed["error_code"] == "UPDATE_PACKAGE_INVALID"
        assert failed["install_available"] is False
        download_dir = tmp_path / "updates" / failed["download_id"]
        assert (download_dir / "failure.json").is_file()
        assert (download_dir / "package.zip").is_file()
    finally:
        manager.shutdown()
        server.stop()


def test_zip_windows_path_alias_variants_rejected(tmp_path):
    variants = [
        ("device", {"bad_member": "CON.txt"}),
        ("tail", {"bad_member": "name. "}),
        ("case", {"extra_members": [("A.txt", b"a"), ("a.txt", b"b")]}),
        ("symlink", {"symlink_member": "link.txt"}),
    ]
    for name, kwargs in variants:
        case_root = tmp_path / name
        case_root.mkdir(parents=True, exist_ok=True)
        package, build_id, package_sha, package_size = _make_package(case_root, **kwargs)
        fixture = TlsFixture(case_root)
        key = fixture.make_key()
        metadata = _metadata(package_sha, package_size, build_id, key)

        def factory(request: bytes, metadata=metadata, package=package):
            if b"/manifest.json" in request:
                return _http(metadata)
            return _http(package.read_bytes(), content_type="application/octet-stream")

        server = w3_tls.TlsServer(
            cert=fixture.leaf_cert, key=fixture.leaf_key, reply_factory=factory
        ).start()
        manager = UpdateManager(
            CURRENT,
            source=fixture.source(server.port),
            staging_root=case_root / "updates",
        )
        try:
            manager.check()
            _wait(manager, {"available"})
            manager.download()
            failed = _wait(manager, {"failed"})
            assert failed["error_code"] == "UPDATE_PACKAGE_INVALID", (name, failed)
            assert failed["install_available"] is False
        finally:
            manager.shutdown()
            server.stop()


def test_package_manifest_duplicate_and_bool_schema_rejected(tmp_path):
    for name, kwargs in (
        ("duplicate", {"duplicate_manifest_key": True}),
        ("bool", {"manifest_schema_bool": True}),
    ):
        case_root = tmp_path / name
        case_root.mkdir(parents=True, exist_ok=True)
        package, build_id, package_sha, package_size = _make_package(case_root, **kwargs)
        fixture = TlsFixture(case_root)
        key = fixture.make_key()
        metadata = _metadata(package_sha, package_size, build_id, key)

        def factory(request: bytes, metadata=metadata, package=package):
            if b"/manifest.json" in request:
                return _http(metadata)
            return _http(package.read_bytes(), content_type="application/octet-stream")

        server = w3_tls.TlsServer(
            cert=fixture.leaf_cert, key=fixture.leaf_key, reply_factory=factory
        ).start()
        manager = UpdateManager(
            CURRENT,
            source=fixture.source(server.port),
            staging_root=case_root / "updates",
        )
        try:
            manager.check()
            _wait(manager, {"available"})
            manager.download()
            failed = _wait(manager, {"failed"})
            assert failed["error_code"] == "UPDATE_PACKAGE_INVALID", (name, failed)
        finally:
            assert manager.shutdown() is True
            server.stop()


def test_staging_overlap_with_data_or_credentials_rejected(tmp_path):
    package, build_id, package_sha, package_size = _make_package(tmp_path / "pkg")
    fixture = TlsFixture(tmp_path / "tls")
    key = fixture.make_key()
    metadata = _metadata(package_sha, package_size, build_id, key)
    requests: list[bytes] = []

    def factory(request: bytes):
        requests.append(request)
        if b"/manifest.json" in request:
            return _http(metadata)
        return _http(package.read_bytes(), content_type="application/octet-stream")

    server = w3_tls.TlsServer(
        cert=fixture.leaf_cert, key=fixture.leaf_key, reply_factory=factory
    ).start()
    data_dir = tmp_path / "data-root"
    credential_root = tmp_path / "credential-root"
    data_dir.mkdir()
    credential_root.mkdir()
    sentinel = data_dir / "kindergarten.db"
    sentinel.write_bytes(b"database-sentinel")
    cred_sentinel = credential_root / "key.dpapi"
    cred_sentinel.write_bytes(b"credential-sentinel")
    before = (hashlib.sha256(sentinel.read_bytes()).hexdigest(), hashlib.sha256(cred_sentinel.read_bytes()).hexdigest())

    for staging in (data_dir / "updates", credential_root / "updates"):
        manager = UpdateManager(
            CURRENT,
            source=fixture.source(server.port),
            staging_root=staging,
            data_dir=data_dir,
            credential_root=credential_root,
        )
        try:
            manager.check()
            _wait(manager, {"available"})
            manager.download()
            failed = manager.state()
            assert failed["error_code"] == "UPDATE_STAGING_OVERLAP"
            assert failed["install_available"] is False
            assert not staging.exists()
        finally:
            assert manager.shutdown() is True
    after = (hashlib.sha256(sentinel.read_bytes()).hexdigest(), hashlib.sha256(cred_sentinel.read_bytes()).hexdigest())
    assert before == after
    assert not any(b"/releases/package.zip" in request for request in requests)
    server.stop()


def test_frozen_identity_missing_or_damaged_is_not_source_fallback(tmp_path):
    from update_identity import load_app_identity

    missing = tmp_path / "missing.json"
    assert (
        load_app_identity(path=missing, require_packaged=True)
        is None
    )
    damaged = tmp_path / "build_identity.json"
    damaged.write_text('{"app_id":"x","app_id":"y"}', encoding="utf-8")
    assert load_app_identity(path=damaged, require_packaged=True) is None
    base = {
        "app_id": "kindergarten-manager-next",
        "app_name": "KindergartenManager",
        "channel": "stable",
        "version": "0.1.0",
        "build_id": str(uuid.uuid4()),
        "package_format": "pyinstaller-onedir-zip-v1",
        "platform": "windows",
        "arch": "x64",
        "python": "3.14.7",
        "database_revision": CURRENT.database_revision,
    }
    variants = [
        {"app_id": "another-application"},
        {"arch": "arm64"},
        {"version": "0.1"},
        {"build_id": "not-a-uuid"},
        {"python": "3.12.0"},
        {"database_revision": "another-revision"},
    ]
    for variant in variants:
        data = dict(base)
        data.update(variant)
        path = tmp_path / f"invalid-{uuid.uuid4().hex}.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        assert (
            load_app_identity(
                database_revision=CURRENT.database_revision,
                path=path,
                require_packaged=True,
            )
            is None
        ), variant
    valid_path = tmp_path / "valid.json"
    valid_path.write_text(json.dumps(base), encoding="utf-8")
    valid = load_app_identity(
        database_revision=CURRENT.database_revision,
        path=valid_path,
        require_packaged=True,
    )
    assert valid is not None and valid.app_id == base["app_id"]
    source = load_app_identity(path=missing, require_packaged=False)
    assert source is not None and source.version == "0.1.0"


def test_strict_json_rejects_duplicate_and_bool_schema(tmp_path):
    package, build_id, package_sha, package_size = _make_package(tmp_path)
    fixture = TlsFixture(tmp_path)
    key = fixture.make_key()
    source = fixture.source(9999)
    raw = _metadata(package_sha, package_size, build_id, key).decode("utf-8")
    duplicate = raw.replace(
        '"schema_version": 1', '"schema_version": 1, "schema_version": 1', 1
    ).encode("utf-8")
    bool_schema = raw.replace(
        '"schema_version": 1', '"schema_version": true', 1
    ).encode("utf-8")
    for body in (duplicate, bool_schema):
        with pytest.raises(Exception) as exc:
            parse_signed_manifest(body, source, CURRENT.version, CURRENT.database_revision)
        assert getattr(exc.value, "code", None) == "UPDATE_METADATA_INVALID"


def test_package_internal_arm64_identity_rejected(tmp_path):
    package, build_id, package_sha, package_size = _make_package(
        tmp_path, identity_arch="arm64"
    )
    fixture = TlsFixture(tmp_path)
    key = fixture.make_key()
    metadata = _metadata(package_sha, package_size, build_id, key)

    def factory(request: bytes):
        if b"/manifest.json" in request:
            return _http(metadata)
        return _http(package.read_bytes(), content_type="application/octet-stream")

    server = w3_tls.TlsServer(
        cert=fixture.leaf_cert, key=fixture.leaf_key, reply_factory=factory
    ).start()
    manager = UpdateManager(
        CURRENT,
        source=fixture.source(server.port),
        staging_root=tmp_path / "updates",
    )
    try:
        manager.check()
        _wait(manager, {"available"})
        manager.download()
        failed = _wait(manager, {"failed"})
        assert failed["error_code"] == "UPDATE_PACKAGE_INVALID"
    finally:
        assert manager.shutdown() is True
        server.stop()


def test_junction_staging_root_rejected_without_write(tmp_path):
    outside = tmp_path / "outside-stage"
    outside.mkdir()
    junction = tmp_path / "managed-stage"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        capture_output=True,
        text=True,
    )
    assert created.returncode == 0, created.stderr
    package, build_id, package_sha, package_size = _make_package(tmp_path / "pkg")
    fixture = TlsFixture(tmp_path / "tls")
    key = fixture.make_key()
    metadata = _metadata(package_sha, package_size, build_id, key)

    def factory(request: bytes):
        if b"/manifest.json" in request:
            return _http(metadata)
        return _http(package.read_bytes(), content_type="application/octet-stream")

    server = w3_tls.TlsServer(
        cert=fixture.leaf_cert, key=fixture.leaf_key, reply_factory=factory
    ).start()
    manager = UpdateManager(
        CURRENT,
        source=fixture.source(server.port),
        staging_root=junction,
    )
    try:
        manager.check()
        _wait(manager, {"available"})
        manager.download()
        failed = manager.state()
        assert failed["error_code"] == "UPDATE_STAGING_UNSAFE"
        assert not (outside / "KindergartenManager").exists()
        assert not any(outside.iterdir())
    finally:
        assert manager.shutdown() is True
        server.stop()


def test_hardlink_tree_rejected(tmp_path):
    root = tmp_path / "tree"
    root.mkdir()
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    os.link(outside, root / "linked.bin")
    with pytest.raises(update_fs.PathSafetyError):
        update_fs.ensure_safe_tree(root)


def test_unrelated_zip_directory_rejected(tmp_path):
    package, build_id, package_sha, package_size = _make_package(
        tmp_path, unrelated_directory=True
    )
    fixture = TlsFixture(tmp_path)
    key = fixture.make_key()
    metadata = _metadata(package_sha, package_size, build_id, key)

    def factory(request: bytes):
        if b"/manifest.json" in request:
            return _http(metadata)
        return _http(package.read_bytes(), content_type="application/octet-stream")

    server = w3_tls.TlsServer(
        cert=fixture.leaf_cert, key=fixture.leaf_key, reply_factory=factory
    ).start()
    manager = UpdateManager(
        CURRENT,
        source=fixture.source(server.port),
        staging_root=tmp_path / "updates",
    )
    try:
        manager.check()
        _wait(manager, {"available"})
        manager.download()
        failed = _wait(manager, {"failed"})
        assert failed["error_code"] == "UPDATE_PACKAGE_INVALID"
    finally:
        assert manager.shutdown() is True
        server.stop()


def test_shutdown_during_check_does_not_publish_available(tmp_path):
    package, build_id, package_sha, package_size = _make_package(tmp_path)
    fixture = TlsFixture(tmp_path)
    key = fixture.make_key()
    metadata = _metadata(package_sha, package_size, build_id, key)
    requests: list[bytes] = []

    def segments(request: bytes):
        requests.append(request)
        return [(_http(metadata).replace(b"Connection: close", b"Connection: close"), 0.8)]

    server = w3_tls.TlsServer(
        cert=fixture.leaf_cert, key=fixture.leaf_key, segment_factory=segments
    ).start()
    manager = UpdateManager(
        CURRENT,
        source=fixture.source(server.port),
        staging_root=tmp_path / "updates",
    )
    try:
        manager.check()
        _wait(manager, {"checking"})
        deadline = time.monotonic() + 3
        while not requests and time.monotonic() < deadline:
            time.sleep(0.01)
        assert requests, "check request did not reach the TLS server"
        assert manager.shutdown() is True
        assert manager.state()["state"] == "closed"
        time.sleep(0.3)
        assert manager.state()["state"] == "closed"
        assert manager.check()["state"] == "closed"
        assert len(requests) == 1
    finally:
        server.stop()


def test_actual_read_timeout_and_total_deadline(tmp_path):
    package, build_id, package_sha, package_size = _make_package(tmp_path)
    fixture = TlsFixture(tmp_path)
    key = fixture.make_key()
    metadata = _metadata(package_sha, package_size, build_id, key)
    package_bytes = package.read_bytes()

    for name, read_timeout, total_timeout in (
        ("read", 0.2, 5.0),
        ("total", 5.0, 0.2),
    ):
        case_root = tmp_path / name
        case_root.mkdir(parents=True, exist_ok=True)
        fixture_case = TlsFixture(case_root / "tls")
        key_case = fixture_case.make_key()
        metadata_case = _metadata(package_sha, package_size, build_id, key_case)
        half = package_bytes[: max(1, len(package_bytes) // 2)]

        def segments(request: bytes, metadata=metadata_case, half=half):
            if b"/manifest.json" in request:
                return [(_http(metadata), 0.0)]
            header = (
                b"HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\n"
                b"Content-Length: " + str(len(package_bytes)).encode() + b"\r\n\r\n"
            )
            return [(header + half, 0.0), (b"", 1.0)]

        server = w3_tls.TlsServer(
            cert=fixture_case.leaf_cert,
            key=fixture_case.leaf_key,
            segment_factory=segments,
        ).start()
        manager = UpdateManager(
            CURRENT,
            source=fixture_case.source(server.port),
            staging_root=case_root / "updates",
            read_timeout=read_timeout,
            total_timeout=total_timeout,
        )
        try:
            manager.check()
            _wait(manager, {"available"})
            started = time.monotonic()
            manager.download()
            failed = _wait(manager, {"failed"}, timeout=5.0)
            assert failed["error_code"] == "UPDATE_DOWNLOAD_TIMEOUT", (name, failed)
            if name == "total":
                assert time.monotonic() - started < 0.6, "total deadline did not bound the blocking read"
        finally:
            assert manager.shutdown() is True
            server.stop()


def test_connection_close_metadata_deadline(tmp_path):
    package, build_id, package_sha, package_size = _make_package(tmp_path)
    fixture = TlsFixture(tmp_path)
    key = fixture.make_key()
    metadata = _metadata(package_sha, package_size, build_id, key)
    full = _http(metadata)
    head, _, body = full.partition(b"\r\n\r\n")
    assert b"Connection: close" in head

    def segments(request: bytes):
        return [
            (head + b"\r\n\r\n" + body[:10], 0.0),
            (body[10:], 0.8),
        ]

    server = w3_tls.TlsServer(
        cert=fixture.leaf_cert, key=fixture.leaf_key, segment_factory=segments
    ).start()
    manager = UpdateManager(
        CURRENT,
        source=fixture.source(server.port),
        staging_root=tmp_path / "updates",
        read_timeout=2.0,
        total_timeout=0.1,
    )
    try:
        manager.check()
        started = time.monotonic()
        failed = _wait(manager, {"failed"}, timeout=5.0)
        assert failed["error_code"] == "UPDATE_DOWNLOAD_TIMEOUT"
        assert time.monotonic() - started < 0.6
        assert failed["state"] != "available"
    finally:
        assert manager.shutdown() is True
        server.stop()


def test_connection_close_download_deadline(tmp_path):
    package, build_id, package_sha, package_size = _make_package(tmp_path)
    fixture = TlsFixture(tmp_path)
    key = fixture.make_key()
    metadata = _metadata(package_sha, package_size, build_id, key)
    package_bytes = package.read_bytes()

    def segments(request: bytes):
        if b"/manifest.json" in request:
            return [(_http(metadata), 0.0)]
        header = (
            b"HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\n"
            b"Connection: close\r\nContent-Length: "
            + str(len(package_bytes)).encode()
            + b"\r\n\r\n"
        )
        return [(header + package_bytes[: max(1, len(package_bytes) // 2)], 0.0), (b"", 0.8)]

    server = w3_tls.TlsServer(
        cert=fixture.leaf_cert, key=fixture.leaf_key, segment_factory=segments
    ).start()
    manager = UpdateManager(
        CURRENT,
        source=fixture.source(server.port),
        staging_root=tmp_path / "updates",
        read_timeout=2.0,
        total_timeout=0.1,
    )
    try:
        manager.check()
        _wait(manager, {"available"})
        started = time.monotonic()
        manager.download()
        failed = _wait(manager, {"failed"}, timeout=5.0)
        assert failed["error_code"] == "UPDATE_DOWNLOAD_TIMEOUT"
        assert time.monotonic() - started < 0.6
    finally:
        assert manager.shutdown() is True
        server.stop()


def test_cancel_download_releases_partial(tmp_path):
    package, build_id, package_sha, package_size = _make_package(tmp_path)
    fixture = TlsFixture(tmp_path)
    key = fixture.make_key()
    metadata = _metadata(package_sha, package_size, build_id, key)
    package_bytes = package.read_bytes()

    def segments(request: bytes):
        if b"/manifest.json" in request:
            return [(_http(metadata), 0.0)]
        last_block = min(1849, max(1, len(package_bytes) - 1))
        prefix = package_bytes[:-last_block]
        header = (
            b"HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\n"
            b"Connection: close\r\n"
            b"Content-Length: " + str(len(package_bytes)).encode() + b"\r\n\r\n"
        )
        return [(header + prefix, 0.0), (b"", 5.0)]

    server = w3_tls.TlsServer(
        cert=fixture.leaf_cert, key=fixture.leaf_key, segment_factory=segments
    ).start()
    manager = UpdateManager(
        CURRENT,
        source=fixture.source(server.port),
        staging_root=tmp_path / "updates",
    )
    try:
        manager.check()
        _wait(manager, {"available"})
        manager.download()
        expected_prefix = len(package_bytes) - min(1849, max(1, len(package_bytes) - 1))
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = manager.state()
            if state["state"] == "downloading" and state["progress"]["downloaded"] >= expected_prefix:
                break
            time.sleep(0.02)
        else:
            raise AssertionError("download did not reach the last-block barrier")
        manager.cancel()
        terminal = _wait(manager, {"cancelled", "ready", "failed"})
        assert terminal["state"] == "cancelled"
        assert terminal["install_available"] is False
        assert not (tmp_path / "updates" / terminal["download_id"]).exists()
        # Explicit retry is a fresh check, not a parallel/auto retry.
        manager.check()
        _wait(manager, {"available"})
        assert manager.shutdown() is True
    finally:
        assert manager.shutdown() is True
        server.stop()


def test_metadata_twenty_chunk_drip_respects_total_deadline(tmp_path):
    package, build_id, package_sha, package_size = _make_package(tmp_path)
    fixture = TlsFixture(tmp_path)
    key = fixture.make_key()
    metadata = _metadata(package_sha, package_size, build_id, key)
    body = metadata
    parts = [body[i::20] for i in range(20)]

    for name, close in (("close", True), ("keepalive", False)):
        case_root = tmp_path / name
        case_root.mkdir(parents=True, exist_ok=True)
        fixture_case = TlsFixture(case_root / "tls")
        key_case = fixture_case.make_key()
        metadata_case = _metadata(package_sha, package_size, build_id, key_case)
        chunks = [metadata_case[i::20] for i in range(20)]

        def segments(request: bytes, chunks=chunks, close=close):
            header = (
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                + (b"Connection: close\r\n" if close else b"")
                + b"Content-Length: " + str(sum(len(c) for c in chunks)).encode() + b"\r\n\r\n"
            )
            out = [(header + chunks[0], 0.0)]
            out.extend((chunk, 0.04) for chunk in chunks[1:])
            return out

        server = w3_tls.TlsServer(
            cert=fixture_case.leaf_cert,
            key=fixture_case.leaf_key,
            segment_factory=segments,
        ).start()
        manager = UpdateManager(
            CURRENT,
            source=fixture_case.source(server.port),
            staging_root=case_root / "updates",
            read_timeout=2.0,
            total_timeout=0.1,
        )
        try:
            manager.check()
            started = time.monotonic()
            failed = _wait(manager, {"failed"}, timeout=5.0)
            assert failed["error_code"] == "UPDATE_DOWNLOAD_TIMEOUT", (name, failed)
            assert time.monotonic() - started < 0.5, (name, "drip exceeded total deadline")
        finally:
            assert manager.shutdown() is True
            server.stop()


def test_cancel_and_shutdown_interrupt_server_barrier(tmp_path):
    package, build_id, package_sha, package_size = _make_package(tmp_path)
    fixture = TlsFixture(tmp_path)
    key = fixture.make_key()
    metadata = _metadata(package_sha, package_size, build_id, key)
    package_bytes = package.read_bytes()

    for action in ("cancel", "shutdown"):
        case_root = tmp_path / action
        case_root.mkdir(parents=True, exist_ok=True)
        fixture_case = TlsFixture(case_root / "tls")
        key_case = fixture_case.make_key()
        metadata_case = _metadata(package_sha, package_size, build_id, key_case)
        server = BarrierTlsServer(
            fixture_case.leaf_cert,
            fixture_case.leaf_key,
            metadata_case,
            package_bytes,
        ).start()
        manager = UpdateManager(
            CURRENT,
            source=fixture_case.source(server.port),
            staging_root=case_root / "updates",
            read_timeout=2.0,
            total_timeout=5.0,
        )
        try:
            manager.check()
            _wait(manager, {"available"})
            manager.download()
            assert server.package_started.wait(5), f"{action}: package did not start"
            started = time.monotonic()
            if action == "cancel":
                manager.cancel()
                elapsed = time.monotonic() - started
                assert elapsed < 0.5, f"cancel waited for server release: {elapsed}"
                assert manager.state()["state"] in ("cancelled", "downloading")
                final = _wait(manager, {"cancelled"})
                assert final["state"] == "cancelled"
            else:
                assert manager.shutdown() is True
                elapsed = time.monotonic() - started
                assert elapsed < 0.5, f"shutdown waited for server release: {elapsed}"
                assert manager.state()["state"] == "closed"
            assert server.release.is_set() is False
            time.sleep(0.15)
            assert manager.state()["state"] != "available"
        finally:
            server.release.set()
            assert manager.shutdown() is True
            server.stop()


def test_metadata_body_shutdown_interrupts_barrier(tmp_path):
    package, build_id, package_sha, package_size = _make_package(tmp_path)
    fixture = TlsFixture(tmp_path)
    key = fixture.make_key()
    metadata = _metadata(package_sha, package_size, build_id, key)
    server = BarrierTlsServer(
        fixture.leaf_cert,
        fixture.leaf_key,
        metadata,
        package.read_bytes(),
        hold_metadata=True,
    ).start()
    manager = UpdateManager(
        CURRENT,
        source=fixture.source(server.port),
        staging_root=tmp_path / "updates",
        read_timeout=10.0,
        total_timeout=20.0,
    )
    action_result = {}
    try:
        manager.check()
        assert server.metadata_started.wait(5), "metadata body did not start"
        deadline = time.monotonic() + 3
        while manager._active_response is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert manager._active_response is not None
        action = threading.Thread(
            target=lambda: action_result.setdefault("value", manager.shutdown()),
            daemon=True,
        )
        action.start()
        action.join(1.0)
        assert not action.is_alive(), "shutdown did not interrupt the blocked metadata body"
        assert action_result["value"] is True
        assert manager.state()["state"] == "closed"
        assert manager._thread.is_alive() is False
        assert server.release.is_set() is False
        time.sleep(0.1)
        assert manager.state()["state"] == "closed"
        assert manager.state()["state"] != "available"
    finally:
        server.release.set()
        action_result.setdefault("cleanup", manager.shutdown())
        server.stop()


def test_download_body_cancel_interrupts_barrier(tmp_path):
    package, build_id, package_sha, package_size = _make_package(tmp_path)
    fixture = TlsFixture(tmp_path)
    key = fixture.make_key()
    metadata = _metadata(package_sha, package_size, build_id, key)
    server = BarrierTlsServer(
        fixture.leaf_cert,
        fixture.leaf_key,
        metadata,
        package.read_bytes(),
    ).start()
    manager = UpdateManager(
        CURRENT,
        source=fixture.source(server.port),
        staging_root=tmp_path / "updates",
        read_timeout=10.0,
        total_timeout=20.0,
    )
    action_result = {}
    try:
        manager.check()
        _wait(manager, {"available"})
        manager.download()
        assert server.package_started.wait(5), "package body did not start"
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            state = manager.state()
            if (
                manager._active_response is not None
                and state["progress"]["downloaded"] > 0
            ):
                break
            time.sleep(0.01)
        else:
            raise AssertionError("client did not consume the first body block")
        action = threading.Thread(
            target=lambda: action_result.setdefault("value", manager.cancel()),
            daemon=True,
        )
        action.start()
        action.join(1.0)
        assert not action.is_alive(), "cancel did not interrupt the blocked download body"
        final = _wait(manager, {"cancelled"})
        assert final["state"] == "cancelled"
        assert final["state"] not in ("ready", "failed")
        assert manager._thread.is_alive() is False
        assert server.release.is_set() is False
        assert not (tmp_path / "updates" / final["download_id"]).exists()
        time.sleep(0.1)
        assert manager.state()["state"] == "cancelled"
        assert manager.state()["state"] != "ready"
    finally:
        server.release.set()
        action_result.setdefault("cleanup", manager.shutdown())
        server.stop()


def test_bridge_guards_and_no_install_endpoint():
    class FakeManager:
        identity = CURRENT

        def state(self):
            return {"state": "idle", "install_available": False}

        def check(self):
            return {"state": "checking", "install_available": False}

        def download(self):
            return {"state": "downloading", "install_available": False}

        def cancel(self):
            return {"state": "cancelled", "install_available": False}

    host = d1_host_api.D1HostApi(launch_token="t", update_manager=FakeManager())
    assert host.get_update_state()["error_code"] == "BRIDGE_NOT_READY"
    assert host.page_ready({"bridge_protocol": d1_host_api.BRIDGE_PROTOCOL})["accepted"] is True
    assert host.get_app_identity()["version"] == "0.1.0"
    assert host.check_for_update()["state"] == "checking"
    assert host.start_update_download()["state"] == "downloading"
    assert host.cancel_update_download()["state"] == "cancelled"
    assert "request_update_install" not in d1_host_api.BRIDGE_ALLOWED_ENDPOINTS
