"""Synthetic HTTPS WebDAV transport tests (real sockets, real TLS).

The server is a small in-process WebDAV implementation over a loopback TLS
socket with a freshly generated self-signed certificate.  Production paths
always use ``ssl.create_default_context()``; only these tests inject an
isolated trust context built from the synthetic certificate, so the default
certificate rejection is itself exercised.

No real teacher directory, credential, WebDAV host or product AI is used.
"""

from __future__ import annotations

import base64
import http.server
import io
import ipaddress
import os
import socket
import ssl
import threading
import urllib.parse
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

import webdav_backup as wb
from app.local import backup_format
from webdav_credentials import WebdavEndpoint

DAV = "{DAV:}"


# ---------------------------------------------------------------------------
# Synthetic TLS material and WebDAV server
# ---------------------------------------------------------------------------


def _create_self_signed(directory: Path) -> tuple[Path, Path]:
    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.now(timezone.utc)
    name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "kgm-webdav-synthetic")]
    )
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=2))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path = directory / "synthetic-cert.pem"
    key_path = directory / "synthetic-key.pem"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


class WebdavState:
    def __init__(self, root: Path, *, username="teacher", password="dav-pass"):
        self.root = root
        self.username = username
        self.password = password
        self.username = username
        self.requests: list[dict] = []
        self.lock = threading.Lock()
        self.fail_put_mid_body = False
        self.truncate_download = False
        self.redirect: tuple[int, str] | None = None

    def record(self, method: str, path: str, headers) -> None:
        with self.lock:
            self.requests.append(
                {
                    "method": method,
                    "path": path,
                    "authorization": headers.get("Authorization"),
                }
            )

    def local_path(self, request_path: str) -> Path | None:
        decoded = urllib.parse.unquote(request_path.split("?", 1)[0])
        relative = decoded.lstrip("/")
        parts = [part for part in relative.split("/") if part]
        if any(part in (".", "..") for part in parts):
            return None
        return self.root.joinpath(*parts)


class WebdavHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "SyntheticWebdav/1"

    def log_message(self, *args):  # noqa: A003 - silence test output
        pass

    # -- helpers ---------------------------------------------------------
    @property
    def state(self) -> WebdavState:
        return self.server.state  # type: ignore[attr-defined]

    def _authorized(self) -> bool:
        expected = "Basic " + base64.b64encode(
            f"{self.state.username}:{self.state.password}".encode("utf-8")
        ).decode("ascii")
        return self.headers.get("Authorization") == expected

    def _send(self, status, body=b"", headers=None) -> None:
        self.send_response(status)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        if body:
            self.wfile.write(body)
        self.close_connection = True

    def _redirect_or_auth(self) -> bool:
        state = self.state
        if state.redirect is not None:
            status, location = state.redirect
            self._send(status, b"", {"Location": location})
            return True
        if not self._authorized():
            self._send(401, b"", {"WWW-Authenticate": 'Basic realm="kgm"'})
            return True
        return False

    def _abort(self) -> None:
        self.close_connection = True
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    # -- methods ---------------------------------------------------------
    def do_PROPFIND(self):  # noqa: N802
        self.state.record("PROPFIND", self.path, self.headers)
        if self._redirect_or_auth():
            return
        target = self.state.local_path(self.path)
        if target is None or not target.exists():
            self._send(404)
            return
        depth = (self.headers.get("Depth") or "1").strip()
        entries = [target]
        if depth != "0" and target.is_dir():
            entries.extend(sorted(target.iterdir()))
        multistatus = ET.Element(f"{DAV}multistatus")
        for entry in entries:
            response = ET.SubElement(multistatus, f"{DAV}response")
            relative = entry.relative_to(self.state.root).as_posix()
            href = "/" + urllib.parse.quote(relative, safe="/")
            if entry.is_dir() and not href.endswith("/"):
                href += "/"
            ET.SubElement(response, f"{DAV}href").text = href
            propstat = ET.SubElement(response, f"{DAV}propstat")
            prop = ET.SubElement(propstat, f"{DAV}prop")
            resource_type = ET.SubElement(prop, f"{DAV}resourcetype")
            if entry.is_dir():
                ET.SubElement(resource_type, f"{DAV}collection")
            else:
                ET.SubElement(prop, f"{DAV}getcontentlength").text = str(
                    entry.stat().st_size
                )
                ET.SubElement(prop, f"{DAV}getlastmodified").text = (
                    "Wed, 19 Nov 2026 12:00:00 GMT"
                )
            ET.SubElement(propstat, f"{DAV}status").text = "HTTP/1.1 200 OK"
        body = ET.tostring(multistatus, encoding="utf-8", xml_declaration=True)
        self._send(207, body, {"Content-Type": "application/xml; charset=utf-8"})

    def do_MKCOL(self):  # noqa: N802
        self.state.record("MKCOL", self.path, self.headers)
        if self._redirect_or_auth():
            return
        target = self.state.local_path(self.path)
        if target is None:
            self._send(403)
            return
        if target.exists():
            self._send(405)
            return
        try:
            target.mkdir(parents=False)
        except FileNotFoundError:
            self._send(409)
            return
        except OSError:
            self._send(403)
            return
        self._send(201)

    def do_PUT(self):  # noqa: N802
        self.state.record("PUT", self.path, self.headers)
        if self._redirect_or_auth():
            return
        length = int(self.headers.get("Content-Length") or 0)
        if self.state.fail_put_mid_body:
            self.rfile.read(max(1, length // 2))
            self._abort()
            return
        data = self.rfile.read(length)
        if len(data) != length:
            self._abort()
            return
        target = self.state.local_path(self.path)
        if target is None:
            self._send(403)
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        self._send(201)

    def do_MOVE(self):  # noqa: N802
        self.state.record("MOVE", self.path, self.headers)
        if self._redirect_or_auth():
            return
        source = self.state.local_path(self.path)
        destination_path = urllib.parse.urlsplit(
            self.headers.get("Destination") or ""
        ).path
        destination = self.state.local_path(destination_path)
        if source is None or destination is None or not source.is_file():
            self._send(404)
            return
        overwrite = (self.headers.get("Overwrite") or "T").strip().upper()
        if destination.exists() and overwrite == "F":
            self._send(412)
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, destination)
        self._send(201)

    def do_GET(self):  # noqa: N802
        self.state.record("GET", self.path, self.headers)
        if self._redirect_or_auth():
            return
        target = self.state.local_path(self.path)
        if target is None or not target.is_file():
            self._send(404)
            return
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        if self.state.truncate_download:
            self.wfile.write(data[: max(1, len(data) // 2)])
            self.wfile.flush()
            self._abort()
            return
        self.wfile.write(data)
        self.close_connection = True

    def do_HEAD(self):  # noqa: N802
        self.state.record("HEAD", self.path, self.headers)
        if self._redirect_or_auth():
            return
        target = self.state.local_path(self.path)
        if target is None or not target.is_file():
            self._send(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(target.stat().st_size))
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

    def do_DELETE(self):  # noqa: N802
        self.state.record("DELETE", self.path, self.headers)
        if self._redirect_or_auth():
            return
        target = self.state.local_path(self.path)
        if target is None or not target.is_file():
            self._send(404)
            return
        try:
            target.unlink()
        except OSError:
            self._send(403)
            return
        self._send(204)


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True


@contextmanager
def running_server(tmp_path: Path, *, tls=None, path="dav/", collection=True):
    cert, key = tls or _create_self_signed(tmp_path)
    state = WebdavState(tmp_path / "server-root")
    state.root.mkdir(parents=True, exist_ok=True)
    if collection:
        state.root.joinpath(*[p for p in path.split("/") if p]).mkdir(
            parents=True, exist_ok=True
        )
    server = _Server(("127.0.0.1", 0), WebdavHandler)
    server.state = state  # type: ignore[attr-defined]
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert), str(key))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state, cert, server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5.0)


def make_client(
    state: WebdavState,
    cert: Path,
    port: int,
    *,
    trust=True,
    path="dav/",
    **kwargs,
):
    endpoint = WebdavEndpoint(
        url=f"https://127.0.0.1:{port}/{path}",
        username=state.username,
        password=state.password,
    )
    context = ssl.create_default_context(cafile=str(cert)) if trust else None
    options = {
        "connect_timeout": 5.0,
        "io_timeout": 5.0,
        "operation_timeout": 30.0,
        "rate_bytes_per_second": 0,
    }
    options.update(kwargs)
    return wb.WebdavClient(endpoint, ssl_context=context, **options)


def build_password_package(path: Path, payload: bytes = b"synthetic-business-bytes") -> bytes:
    salt = bytes(range(backup_format.SALT_LEN))
    nonce = bytes(range(backup_format.NONCE_LEN))
    header = backup_format.encode_header(
        mode=backup_format.MODE_PASSWORD,
        payload_len=len(payload),
        salt=salt,
        nonce=nonce,
    )
    key = backup_format.derive_key("synthetic-passphrase", salt)
    with path.open("wb") as out:
        out.write(header)
        tag = backup_format.encrypt_payload(
            io.BytesIO(payload),
            out,
            key=key,
            nonce=nonce,
            aad=header,
            length=len(payload),
        )
        out.write(tag)
    return header


def build_plaintext_package(path: Path, payload: bytes = b"readable-business") -> None:
    header = backup_format.encode_header(
        mode=backup_format.MODE_PLAINTEXT, payload_len=len(payload)
    )
    path.write_bytes(header + payload)


def snapshot_id(seed: int) -> str:
    return f"{seed:032x}"


FIXED_STAMP = datetime(2026, 11, 19, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_remote_name_rules():
    name = wb.remote_name_for(snapshot_id(7))
    assert wb.FINAL_PATTERN.fullmatch(name)
    with pytest.raises(wb.WebdavError):
        wb.remote_name_for("../../evil")
    with pytest.raises(wb.WebdavError):
        wb.remote_name_for("A" * 32)


def test_collection_created_once_and_versions_listed(tmp_path):
    with running_server(tmp_path, collection=False) as (state, cert, port):
        client = make_client(state, cert, port)
        first = client.ensure_collection()
        assert first == {"ok": True, "created": True}
        second = client.ensure_collection()
        assert second == {"ok": True, "created": False}
        assert (state.root / "dav").is_dir()
        assert client.list_versions() == []


def test_encrypted_package_upload_list_download_roundtrip(tmp_path):
    with running_server(tmp_path) as (state, cert, port):
        client = make_client(state, cert, port)
        package = tmp_path / "source.kgmbackup"
        build_password_package(package)
        result = client.upload(package, snapshot_id(1))
        assert result.already_published is False
        assert result.verified is True
        assert wb.FINAL_PATTERN.fullmatch(result.name)
        versions = client.list_versions()
        assert [entry.name for entry in versions] == [result.name]
        assert versions[0].size == package.stat().st_size

        target = tmp_path / "download.kgmbackup"
        downloaded = client.download(result.name, target)
        assert downloaded.size == package.stat().st_size
        assert target.read_bytes() == package.read_bytes()
        assert downloaded.sha256 == backup_format.sha256_file(package)


def test_partial_and_foreign_entries_never_listed(tmp_path):
    with running_server(tmp_path) as (state, cert, port):
        client = make_client(state, cert, port)
        client.ensure_collection()
        collection = state.root / "dav"
        (collection / ("kgm-partial-" + snapshot_id(9) + ".kgmbackup.partial")).write_bytes(
            b"unfinished"
        )
        (collection / "teacher-notes.txt").write_bytes(b"nope")
        (
            collection
            / ("kgm-backup-20260101T000000Z-" + snapshot_id(8) + ".kgmbackup")
        ).write_bytes(b"final-but-not-a-package")
        versions = client.list_versions()
        assert [entry.name for entry in versions] == [
            f"kgm-backup-20260101T000000Z-{snapshot_id(8)}.kgmbackup"
        ]


def test_listing_ignores_hrefs_outside_collection():
    body = (
        b'<?xml version="1.0"?><d:multistatus xmlns:d="DAV:">'
        b"<d:response><d:href>/outside/kgm-backup-20260101T000000Z-"
        + snapshot_id(3).encode()
        + b".kgmbackup</d:href><d:propstat><d:prop>"
        b"<d:getcontentlength>10</d:getcontentlength></d:prop></d:propstat></d:response>"
        b"<d:response><d:href>/dav/kgm-backup-20260101T000000Z-"
        + snapshot_id(4).encode()
        + b".kgmbackup</d:href><d:propstat><d:prop>"
        b"<d:getcontentlength>12</d:getcontentlength></d:prop></d:propstat></d:response>"
        b"</d:multistatus>"
    )
    entries = wb._parse_version_entries(body, "/dav/")
    assert [entry.name for entry in entries] == [
        f"kgm-backup-20260101T000000Z-{snapshot_id(4)}.kgmbackup"
    ]


def test_duplicate_same_bytes_is_verified_already_published(tmp_path):
    with running_server(tmp_path) as (state, cert, port):
        client = make_client(state, cert, port)
        package = tmp_path / "source.kgmbackup"
        build_password_package(package)
        first = client.upload(package, snapshot_id(2), created_at=FIXED_STAMP)
        remote = state.root / "dav" / first.name
        before = remote.read_bytes()

        second = client.upload(package, snapshot_id(2), created_at=FIXED_STAMP)
        assert second.already_published is True
        assert second.name == first.name
        assert remote.read_bytes() == before
        assert len(client.list_versions()) == 1


def test_same_size_different_bytes_is_collision_and_original_kept(tmp_path):
    with running_server(tmp_path) as (state, cert, port):
        client = make_client(state, cert, port)
        package = tmp_path / "source.kgmbackup"
        build_password_package(package, payload=b"first-payload-000")
        first = client.upload(package, snapshot_id(3), created_at=FIXED_STAMP)
        remote = state.root / "dav" / first.name
        before = remote.read_bytes()
        assert len(before) == package.stat().st_size

        # Same size, different bytes (payload length is unchanged).
        build_password_package(package, payload=b"second-payload-00")
        assert package.stat().st_size == len(before)
        with pytest.raises(wb.WebdavError) as caught:
            client.upload(package, snapshot_id(3), created_at=FIXED_STAMP)
        assert caught.value.code == "WEBDAV_VERSION_COLLISION"
        assert remote.read_bytes() == before
        assert len(client.list_versions()) == 1


def test_interrupted_upload_keeps_existing_versions_and_leaves_no_final(tmp_path):
    with running_server(tmp_path) as (state, cert, port):
        client = make_client(state, cert, port)
        package = tmp_path / "source.kgmbackup"
        build_password_package(package)
        first = client.upload(package, snapshot_id(4))
        before = (state.root / "dav" / first.name).read_bytes()

        state.fail_put_mid_body = True
        with pytest.raises(wb.WebdavError) as caught:
            client.upload(package, snapshot_id(5))
        assert caught.value.code in {
            "WEBDAV_CONNECT_FAILED",
            "WEBDAV_TRANSFER_INCOMPLETE",
        }
        state.fail_put_mid_body = False
        # The published version is unchanged and no final name appeared.
        names = [entry.name for entry in client.list_versions()]
        assert names == [first.name]
        assert (state.root / "dav" / first.name).read_bytes() == before
        assert not (state.root / "dav" / wb.remote_name_for(snapshot_id(5))).exists()


def test_truncated_download_fails_and_leaves_no_partial(tmp_path):
    with running_server(tmp_path) as (state, cert, port):
        client = make_client(state, cert, port)
        package = tmp_path / "source.kgmbackup"
        build_password_package(package)
        uploaded = client.upload(package, snapshot_id(6))
        state.truncate_download = True
        target = tmp_path / "download.kgmbackup"
        with pytest.raises(wb.WebdavError) as caught:
            client.download(uploaded.name, target)
        assert caught.value.code in {
            "WEBDAV_TRANSFER_INCOMPLETE",
            "WEBDAV_CONNECT_FAILED",
        }
        assert not target.exists()
        # The remote version is still listed and intact for a later retry.
        state.truncate_download = False
        assert [entry.name for entry in client.list_versions()] == [uploaded.name]


def test_redirect_is_rejected_and_credentials_not_forwarded(tmp_path):
    attacker_requests: list[dict] = []

    class AttackerHandler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # noqa: A003
            pass

        def do_PROPFIND(self):  # noqa: N802
            attacker_requests.append(
                {"path": self.path, "authorization": self.headers.get("Authorization")}
            )
            self.send_response(207)
            self.send_header("Content-Length", "0")
            self.end_headers()

    attacker = _Server(("127.0.0.1", 0), AttackerHandler)
    attacker_thread = threading.Thread(target=attacker.serve_forever, daemon=True)
    attacker_thread.start()
    try:
        with running_server(tmp_path) as (state, cert, port):
            state.redirect = (
                302,
                f"https://127.0.0.1:{attacker.server_address[1]}/dav/",
            )
            client = make_client(state, cert, port)
            with pytest.raises(wb.WebdavError) as caught:
                client.ensure_collection()
            assert caught.value.code == "WEBDAV_REDIRECT_REJECTED"
        assert attacker_requests == []
    finally:
        attacker.shutdown()
        attacker.server_close()
        attacker_thread.join(timeout=5.0)


def test_production_default_rejects_untrusted_certificate(tmp_path):
    with running_server(tmp_path) as (state, cert, port):
        client = make_client(state, cert, port, trust=False)
        with pytest.raises(wb.WebdavError) as caught:
            client.ensure_collection()
        assert caught.value.code == "WEBDAV_CERTIFICATE_INVALID"
        assert "127.0.0.1" not in caught.value.message


def test_plaintext_package_is_never_uploaded(tmp_path):
    with running_server(tmp_path) as (state, cert, port):
        client = make_client(state, cert, port)
        package = tmp_path / "plain.kgmbackup"
        build_plaintext_package(package)
        with pytest.raises(wb.WebdavError) as caught:
            client.upload(package, snapshot_id(10))
        assert caught.value.code == "WEBDAV_ENCRYPTION_REQUIRED"
        assert client.list_versions() == []
        assert not any(
            request["method"] == "PUT" for request in state.requests
        )


def test_plaintext_remote_package_is_rejected_on_download(tmp_path):
    with running_server(tmp_path) as (state, cert, port):
        client = make_client(state, cert, port)
        client.ensure_collection()
        name = f"kgm-backup-20260101T000000Z-{snapshot_id(11)}.kgmbackup"
        build_plaintext_package(state.root / "dav" / name)
        with pytest.raises(wb.WebdavError) as caught:
            client.download(name, tmp_path / "out.kgmbackup")
        assert caught.value.code == "WEBDAV_FORMAT_MISMATCH"
        assert not (tmp_path / "out.kgmbackup").exists()


def test_wrong_password_is_auth_error(tmp_path):
    with running_server(tmp_path) as (state, cert, port):
        endpoint = WebdavEndpoint(
            url=f"https://127.0.0.1:{port}/dav/",
            username=state.username,
            password="wrong",
        )
        context = ssl.create_default_context(cafile=str(cert))
        client = wb.WebdavClient(
            endpoint, ssl_context=context, connect_timeout=5, io_timeout=5
        )
        with pytest.raises(wb.WebdavError) as caught:
            client.ensure_collection()
        assert caught.value.code == "WEBDAV_AUTH_FAILED"


def test_cancel_between_chunks_leaves_no_final(tmp_path):
    with running_server(tmp_path) as (state, cert, port):
        client = make_client(state, cert, port)
        package = tmp_path / "source.kgmbackup"
        build_password_package(package, payload=b"x" * 300_000)
        cancel = threading.Event()

        def progress(_value):
            cancel.set()

        with pytest.raises(wb.WebdavCancelled):
            client.upload(package, snapshot_id(12), progress=progress, cancel=cancel)
        assert client.list_versions() == []
        assert not (state.root / "dav" / wb.remote_name_for(snapshot_id(12))).exists()


def test_download_path_escape_and_existing_target_are_refused(tmp_path):
    with running_server(tmp_path) as (state, cert, port):
        client = make_client(state, cert, port)
        with pytest.raises(wb.WebdavError) as caught:
            client.download("../../evil.kgmbackup", tmp_path / "x.kgmbackup")
        assert caught.value.code == "WEBDAV_NAME_INVALID"
        with pytest.raises(wb.WebdavError) as caught:
            client._remote_path("../escape")
        assert caught.value.code == "WEBDAV_PATH_ESCAPE"

        package = tmp_path / "source.kgmbackup"
        build_password_package(package)
        uploaded = client.upload(package, snapshot_id(13))
        existing = tmp_path / "existing.kgmbackup"
        existing.write_bytes(b"keep-me")
        with pytest.raises(wb.WebdavError) as caught:
            client.download(uploaded.name, existing)
        assert caught.value.code == "WEBDAV_LOCAL_TARGET_EXISTS"
        assert existing.read_bytes() == b"keep-me"


def test_caller_owned_fd_is_not_deleted_on_failure(tmp_path):
    with running_server(tmp_path) as (state, cert, port):
        client = make_client(state, cert, port)
        package = tmp_path / "source.kgmbackup"
        build_password_package(package)
        uploaded = client.upload(package, snapshot_id(14))
        target = tmp_path / "owned.kgmbackup"
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        state.truncate_download = True
        with pytest.raises(wb.WebdavError):
            client.download(uploaded.name, target, fd=fd)
        # The caller created (and therefore owns) the file; the client must not
        # unlink it behind the caller's back.
        assert target.exists()


def test_rate_limit_paces_transfers(monkeypatch):
    endpoint = WebdavEndpoint(
        url="https://example.com/dav/", username="u", password="p"
    )
    client = wb.WebdavClient(endpoint, rate_bytes_per_second=1024 * 1024)
    sleeps: list[float] = []
    monkeypatch.setattr(wb.time, "sleep", lambda value: sleeps.append(value))
    now = wb.time.monotonic()
    client._pace(now, 512 * 1024)
    assert sleeps and 0 < sleeps[0] <= 1.0
    sleeps.clear()
    client._pace(now - 10.0, 512 * 1024)
    assert sleeps == []


def test_utf8_collection_path_is_percent_encoded(tmp_path):
    with running_server(tmp_path, path="备份/资料/") as (state, cert, port):
        client = make_client(state, cert, port, path="备份/资料/")
        result = client.ensure_collection()
        assert result == {"ok": True, "created": False}
        package = tmp_path / "source.kgmbackup"
        build_password_package(package)
        uploaded = client.upload(package, snapshot_id(15))
        assert (state.root / "备份" / "资料" / uploaded.name).is_file()
        request_paths = [request["path"] for request in state.requests]
        assert any(path.startswith("/%E5%A4%87") for path in request_paths)
