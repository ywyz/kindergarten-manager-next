"""Controlled-TLS helpers for the D2 W3 transport/executor tests.

These are *synthetic verification* utilities: they generate a throwaway CA and
a leaf certificate for ``api.example.com`` and run a real TLS server on a
loopback port. The production transport only accepts private/loopback
addresses when a synthetic resolver + test CA are explicitly supplied by such
an entry; nothing here is reachable from an ordinary HTTP request or the
environment.
"""

from __future__ import annotations

import datetime
import ipaddress
import socket
import ssl
import threading
import time
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

TEST_HOST = "api.example.com"


def _key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _name(common_name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def make_ca(directory: Path) -> tuple[Path, bytes]:
    cert_path, _key_path, pem = create_ca(directory)
    return cert_path, pem


# The CA key is generated once per directory and kept beside the cert so a leaf
# can be signed without re-parsing it from the certificate.
_CA_KEYS: dict[str, object] = {}


def create_ca(directory: Path) -> tuple[Path, Path, bytes]:
    """A throwaway CA with the extensions strict verification requires.

    Python 3.14's default ``ssl.create_default_context`` enables
    ``VERIFY_X509_STRICT``, so the CA carries ``BasicConstraints`` (critical),
    ``KeyUsage`` (keyCertSign/crlSign, critical) and a Subject Key Identifier;
    the leaf then carries an Authority Key Identifier pointing back at it.
    Validation is never weakened for the test.
    """
    key = _key()
    subject = _name("KGM W3 Test CA")
    now = datetime.datetime.now(datetime.timezone.utc)
    public_key = key.public_key()
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=30))
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None), critical=True
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(public_key), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    directory.mkdir(parents=True, exist_ok=True)
    cert_path = directory / "ca.pem"
    key_path = directory / "ca.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path, cert.public_bytes(serialization.Encoding.PEM)


def ca_key_for(ca_dir: Path):
    key = _CA_KEYS.get(str(ca_dir))
    if key is None:
        key = serialization.load_pem_private_key(
            (ca_dir / "ca.key").read_bytes(), password=None
        )
        _CA_KEYS[str(ca_dir)] = key
    return key


def create_leaf(ca_dir: Path, out_dir: Path, hostname: str = TEST_HOST) -> tuple[Path, Path]:
    """A leaf signed by the test CA, valid for ``hostname`` under strict rules."""
    ca_cert = x509.load_pem_x509_certificate((ca_dir / "ca.pem").read_bytes())
    key = _key()
    now = datetime.datetime.now(datetime.timezone.utc)
    public_key = key.public_key()
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name(hostname))
        .issuer_name(ca_cert.subject)
        .public_key(public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=30))
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None), critical=True
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(public_key), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_cert.public_key()),
            critical=False,
        )
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False
        )
        .sign(ca_key_for(ca_dir), hashes.SHA256())
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    cert_path = out_dir / "leaf.pem"
    key_path = out_dir / "leaf.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


class TlsServer:
    """A real TLS server that records request bytes and returns a scripted reply.

    ``reply`` is a fixed response; ``reply_factory`` (when given) receives the
    full request bytes and returns the response bytes for that request (used to
    answer the three D2 tasks from their real inputs). Both preserve the same
    recording/timeout behaviour.
    """

    def __init__(
        self,
        *,
        cert: Path,
        key: Path,
        reply: bytes | None = None,
        hang_after_request: bool = False,
        reply_factory=None,
        segment_factory=None,
    ):
        self._reply = reply
        self._reply_factory = reply_factory
        self._segment_factory = segment_factory
        self._hang = hang_after_request
        self.requests: list[bytes] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=str(cert), keyfile=str(key))
        self._context = context
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self._sock.settimeout(0.2)
        self.port = int(self._sock.getsockname()[1])
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self) -> "TlsServer":
        self._thread.start()
        return self

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except (socket.timeout, TimeoutError):
                continue
            except OSError:
                break
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn: socket.socket) -> None:
        try:
            tls = self._context.wrap_socket(conn, server_side=True)
        except Exception:  # noqa: BLE001
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
            return
        try:
            tls.settimeout(10)
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = tls.recv(65536)
                if not chunk:
                    break
                data += chunk
            head, _, rest = data.partition(b"\r\n\r\n")
            length = 0
            for line in head.split(b"\r\n"):
                if line.lower().startswith(b"content-length:"):
                    length = int(line.split(b":", 1)[1].strip())
            while len(rest) < length:
                chunk = tls.recv(65536)
                if not chunk:
                    break
                rest += chunk
            with self._lock:
                self.requests.append(head + b"\r\n\r\n" + rest)
            if self._hang:
                # Keep the connection open without replying (timeout case).
                while not self._stop.is_set():
                    try:
                        if tls.recv(1) == b"":
                            break
                    except Exception:  # noqa: BLE001
                        break
                return
            reply = self._reply
            if self._segment_factory is not None:
                segments = self._segment_factory(head + b"\r\n\r\n" + rest)
                if segments is None:
                    while not self._stop.is_set():
                        try:
                            if tls.recv(1) == b"":
                                break
                        except Exception:  # noqa: BLE001
                            break
                    return
                for segment, delay in segments:
                    if delay:
                        time.sleep(delay)
                    tls.sendall(segment)
                return
            if self._reply_factory is not None:
                reply = self._reply_factory(head + b"\r\n\r\n" + rest)
            if reply is None:
                # The factory asked to hang (still-open task case).
                while not self._stop.is_set():
                    try:
                        if tls.recv(1) == b"":
                            break
                    except Exception:  # noqa: BLE001
                        break
                return
            tls.sendall(reply)
        except Exception:  # noqa: BLE001
            pass
        finally:
            try:
                tls.close()
            except Exception:  # noqa: BLE001
                pass

    def stop(self) -> None:
        self._stop.set()
        try:
            self._sock.close()
        except Exception:  # noqa: BLE001
            pass


def envelope(content_json: str, *, model: str = "test-model", usage: dict | None = None) -> bytes:
    import json

    payload = {
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content_json},
                "finish_reason": "stop",
            }
        ],
        "model": model,
    }
    if usage is not None:
        payload["usage"] = usage
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body
