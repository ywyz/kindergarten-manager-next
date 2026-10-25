"""D3-U U1 update discovery, download and complete-package verification.

No install or process handoff is implemented here. The service is a host-side
state machine; the page only sees bounded state through the restricted bridge.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import secrets
import shutil
import socket
import ssl
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from update_identity import AppIdentity
from update_fs import PathSafetyError, ensure_safe_path
from update_manifest import (
    MAX_PACKAGE_BYTES,
    ManifestError,
    UpdateManifest,
    parse_signed_manifest,
    verify_package_zip,
)
from update_trust import ReleaseConfigError, ReleaseSource

CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 30.0
TOTAL_DOWNLOAD_SECONDS = 30 * 60.0
CHUNK = 64 * 1024
MAX_REDIRECTS = 0


class UpdateError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class UpdateCancelled(UpdateError):
    def __init__(self):
        super().__init__("UPDATE_CANCELLED", "更新下载已取消")


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection with a fixed TLS hostname and optional test address.

    Product calls pass the same host for both. Controlled tests may resolve the
    fixed test hostname to a loopback listener while keeping strict certificate
    and hostname validation for the fixed hostname.
    """

    def __init__(
        self,
        connect_host: str,
        port: int,
        *,
        server_hostname: str,
        context: ssl.SSLContext,
        timeout: float,
    ):
        super().__init__(server_hostname, port, timeout=timeout, context=context)
        self._connect_host = connect_host
        self._server_hostname = server_hostname

    def connect(self) -> None:
        sock = socket.create_connection(
            (self._connect_host, self.port), self.timeout
        )
        self.sock = self._context.wrap_socket(
            sock, server_hostname=self._server_hostname
        )


def _source_connection(
    source: ReleaseSource,
    read_timeout: float = READ_TIMEOUT,
    *,
    deadline: float | None = None,
):
    parts = urlsplit(source.origin)
    host = parts.hostname or ""
    port = parts.port or 443
    context = ssl.create_default_context()
    if source.test_only and source.ca_pem:
        context.load_verify_locations(cadata=source.ca_pem)
    connect_host = source.connect_host or host
    server_hostname = source.server_hostname or host
    timeout = CONNECT_TIMEOUT
    if deadline is not None:
        timeout = max(0.05, min(timeout, deadline - time.monotonic()))
    conn = _PinnedHTTPSConnection(
        connect_host,
        port,
        server_hostname=server_hostname,
        context=context,
        timeout=timeout,
    )
    conn._update_read_timeout = read_timeout  # type: ignore[attr-defined]
    return conn


def _remaining(deadline: float | None) -> float | None:
    if deadline is None:
        return None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return 0.0
    return remaining


def _set_socket_timeout(sock, read_timeout: float, deadline: float | None) -> None:
    remaining = _remaining(deadline)
    if remaining is not None and remaining <= 0:
        raise UpdateError("UPDATE_DOWNLOAD_TIMEOUT", "超过总期限")
    if sock is not None:
        sock.settimeout(
            min(read_timeout, remaining) if remaining is not None else read_timeout
        )


def _response_socket(response, conn):
    """The actual socket owned by the response (close/None conn.sock case)."""
    fp = getattr(response, "fp", None)
    raw = getattr(fp, "raw", None)
    sock = getattr(raw, "_sock", None)
    if sock is None:
        sock = getattr(conn, "sock", None)
    return sock


def _request(
    source: ReleaseSource,
    path: str,
    read_timeout: float = READ_TIMEOUT,
    *,
    deadline: float | None = None,
):
    conn = _source_connection(source, read_timeout, deadline=deadline)
    host = urlsplit(source.origin).netloc
    conn.putrequest(
        "GET",
        path,
        skip_host=True,
        skip_accept_encoding=True,
    )
    conn.putheader("Host", host)
    conn.putheader("Accept", "application/json, application/octet-stream")
    conn.putheader("Accept-Encoding", "identity")
    conn.putheader("Connection", "close")
    conn.endheaders()
    _set_socket_timeout(conn.sock, read_timeout, deadline)
    return conn


def _read_exact(
    response,
    limit: int,
    *,
    sock=None,
    deadline: float | None = None,
    read_timeout: float | None = None,
) -> bytes:
    length = response.getheader("Content-Length")
    if length is None:
        raise UpdateError("UPDATE_DOWNLOAD_INVALID", "响应缺少 Content-Length")
    try:
        size = int(length)
    except ValueError:
        raise UpdateError("UPDATE_DOWNLOAD_INVALID", "响应 Content-Length 不合法") from None
    if size < 0 or size > limit:
        raise UpdateError("UPDATE_DOWNLOAD_INVALID", "响应超过大小上限")
    chunks: list[bytes] = []
    total = 0
    while total < size:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise UpdateError("UPDATE_DOWNLOAD_TIMEOUT", "响应超过总期限")
            if sock is not None:
                sock.settimeout(min(read_timeout or remaining, remaining))
        chunk = response.read1(min(CHUNK, size - total))
        if not chunk:
            raise UpdateError("UPDATE_DOWNLOAD_INVALID", "响应提前结束")
        chunks.append(chunk)
        total += len(chunk)
        if deadline is not None and time.monotonic() > deadline:
            raise UpdateError("UPDATE_DOWNLOAD_TIMEOUT", "响应超过总期限")
    if deadline is not None and time.monotonic() > deadline:
        raise UpdateError("UPDATE_DOWNLOAD_TIMEOUT", "响应超过总期限")
    return b"".join(chunks)


def _interrupt_socket(sock) -> None:
    """Interrupt a blocking recv through the socket's own close path.

    ``SSLSocket.shutdown`` checks the Python closed flag while a ``SocketIO``
    still owns a live descriptor. Pointing the base shutdown at the instance
    is not enough here: on Windows the worker can remain inside SSL_read and
    ``response.close()`` then waits for that reader. Use the socket's own
    ``_real_close`` (the standard library's descriptor-closing path), which
    closes the handle and leaves fd=-1; later response/socket closes are
    no-ops. This avoids duplicating or double-closing the raw handle.
    """
    if sock is None:
        return
    try:
        fd = sock.fileno()
    except Exception:  # noqa: BLE001
        return
    if fd < 0:
        return
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except Exception:  # noqa: BLE001
        pass
    try:
        sock._real_close()
    except Exception:  # noqa: BLE001 - already closed or non-standard wrapper
        pass


def _close_io(response=None, sock=None, conn=None) -> None:
    """Interrupt the underlying socket before closing buffered response objects.

    ``response.close()`` can wait for a response file read lock; the actual
    socket close interrupt makes an in-progress recv return, then the wrappers
    are closed in a safe order. All failures are best-effort.
    """
    _interrupt_socket(sock)
    _interrupt_socket(getattr(conn, "sock", None))
    for candidate in (sock, response, conn):
        if candidate is None:
            continue
        try:
            candidate.close()
        except Exception:  # noqa: BLE001
            pass


class UpdateManager:
    def __init__(
        self,
        identity: AppIdentity,
        *,
        source: ReleaseSource | None = None,
        staging_root: str | Path | None = None,
        enabled: bool = True,
        read_timeout: float = READ_TIMEOUT,
        total_timeout: float = TOTAL_DOWNLOAD_SECONDS,
        disabled_reason: str = "UPDATE_DISABLED_SOURCE_RUN",
        data_dir: str | Path | None = None,
        credential_root: str | Path | None = None,
    ):
        self.identity = identity
        self.source = source
        self.enabled = enabled
        self.read_timeout = read_timeout
        self.total_timeout = total_timeout
        self.disabled_reason = disabled_reason
        self.data_dir = Path(data_dir) if data_dir is not None else None
        self.credential_root = (
            Path(credential_root) if credential_root is not None else None
        )
        self.staging_root = (
            Path(staging_root) if staging_root is not None else _default_staging_root()
        )
        self._lock = threading.RLock()
        self._state = "idle"
        self._reason: str | None = None
        self._error_code: str | None = None
        self._error_message: str | None = None
        self._manifest: UpdateManifest | None = None
        self._metadata_raw: bytes | None = None
        self._progress_downloaded = 0
        self._progress_total = 0
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._download_id: str | None = None
        self._staging_dir: Path | None = None
        self._active_connection = None
        self._active_response = None
        self._active_socket = None
        self._closed = False
        self._generation = 0
        self._validate_initial_state()

    def _validate_initial_state(self) -> None:
        if not self.enabled:
            self._state = "disabled"
            self._reason = self.disabled_reason
            return
        if self.source is None:
            self._state = "unconfigured"
            self._reason = "UPDATE_CHANNEL_UNCONFIGURED"
            return
        try:
            self.source.validate()
        except ReleaseConfigError as exc:
            self._state = "unconfigured"
            self._reason = "UPDATE_CONFIG_INVALID"
            self._error_code = "UPDATE_CONFIG_INVALID"
            self._error_message = str(exc)
            return
        if not self.source.configured:
            self._state = "unconfigured"
            self._reason = "UPDATE_CHANNEL_UNCONFIGURED"

    @staticmethod
    def _paths_overlap(left: Path, right: Path) -> bool:
        try:
            a = left.resolve(strict=False)
            b = right.resolve(strict=False)
        except OSError:
            return True
        return a == b or a in b.parents or b in a.parents

    def _isolation_error(self) -> str | None:
        if self.data_dir is not None and self._paths_overlap(
            self.staging_root, self.data_dir
        ):
            return "UPDATE_STAGING_OVERLAP"
        if self.credential_root is not None and self._paths_overlap(
            self.staging_root, self.credential_root
        ):
            return "UPDATE_STAGING_OVERLAP"
        return None

    def _snapshot(self) -> dict[str, Any]:
        with self._lock:
            target = self._manifest.as_public_dict() if self._manifest else None
            total = self._progress_total
            downloaded = self._progress_downloaded
            percent = int(downloaded * 100 / total) if total > 0 else 0
            return {
                "state": self._state,
                "reason": self._reason,
                "current": self.identity.as_dict(),
                "target": target,
                "progress": {
                    "downloaded": downloaded,
                    "total": total,
                    "percent": max(0, min(100, percent)),
                },
                "release_notes": target["release_notes"] if target else "",
                "error_code": self._error_code,
                "error_message": self._error_message,
                "install_available": False,
                "download_id": self._download_id,
            }

    def state(self) -> dict[str, Any]:
        return self._snapshot()

    def install_payload(self) -> dict[str, Any]:
        """Return the already verified inputs for one host-generated U2 plan.

        This is an internal host API: the page receives only the bounded
        snapshot below and never any path, digest or command.
        """
        with self._lock:
            if self._state != "ready" or self._manifest is None:
                raise UpdateError("UPDATE_NOT_READY", "更新包尚未准备好")
            if self._staging_dir is None or self._metadata_raw is None:
                raise UpdateError("UPDATE_NOT_READY", "更新包暂存信息缺失")
            package_zip = self._staging_dir / "package.zip"
            if not package_zip.is_file():
                raise UpdateError("UPDATE_PACKAGE_INVALID", "完整包 ZIP 缺失")
            return {
                "manifest": self._manifest,
                "metadata_raw": self._metadata_raw,
                "staging_dir": self._staging_dir,
                "package_zip": package_zip,
            }

    def _set(
        self,
        state: str,
        *,
        reason: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        with self._lock:
            self._state = state
            self._reason = reason
            self._error_code = error_code
            self._error_message = error_message

    def _is_current(self, generation: int) -> bool:
        with self._lock:
            return not self._closed and generation == self._generation

    def _publish(
        self,
        generation: int,
        state: str,
        *,
        reason: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        manifest: UpdateManifest | None = None,
        downloaded: int | None = None,
        total: int | None = None,
        staging_dir: Path | None = None,
    ) -> bool:
        with self._lock:
            if self._closed or generation != self._generation:
                return False
            self._state = state
            self._reason = reason
            self._error_code = error_code
            self._error_message = error_message
            if manifest is not None:
                self._manifest = manifest
            if downloaded is not None:
                self._progress_downloaded = downloaded
            if total is not None:
                self._progress_total = total
            if staging_dir is not None:
                self._staging_dir = staging_dir
            return True

    def check(self) -> dict[str, Any]:
        if not self.enabled:
            return self._snapshot()
        if self.source is None:
            return self._snapshot()
        with self._lock:
            if self._closed or self._state in ("unconfigured", "disabled", "closed"):
                return self._snapshot()
            if self._state in ("checking", "downloading", "verifying"):
                return self._snapshot()
            self._state = "checking"
            self._reason = None
            self._error_code = None
            self._error_message = None
            self._generation += 1
            generation = self._generation
            self._thread = threading.Thread(
                target=self._check_worker,
                args=(generation,),
                daemon=True,
            )
            self._thread.start()
        return self._snapshot()

    def _check_worker(self, generation: int) -> None:
        conn = None
        response = None
        sock = None
        deadline = time.monotonic() + self.total_timeout
        try:
            assert self.source is not None
            conn = _request(
                self.source,
                self.source.metadata_path,
                self.read_timeout,
                deadline=deadline,
            )
            with self._lock:
                if self._closed or generation != self._generation:
                    conn.close()
                    return
                self._active_connection = conn
            _set_socket_timeout(conn.sock, self.read_timeout, deadline)
            response = conn.getresponse()
            sock = _response_socket(response, conn)
            with self._lock:
                if self._closed or generation != self._generation:
                    return
                self._active_response = response
                self._active_socket = sock
            _set_socket_timeout(sock, self.read_timeout, deadline)
            if response.status != 200:
                raise UpdateError("UPDATE_METADATA_UNAVAILABLE", f"更新元数据 HTTP {response.status}")
            raw = _read_exact(
                response,
                64 * 1024,
                sock=sock,
                deadline=deadline,
                read_timeout=self.read_timeout,
            )
            if not self._is_current(generation):
                return
            manifest = parse_signed_manifest(
                raw,
                self.source,
                self.identity.version,
                self.identity.database_revision,
            )
            with self._lock:
                if self._closed or generation != self._generation:
                    return
                self._manifest = manifest
                self._metadata_raw = raw
                self._state = "available"
                self._reason = None
                self._error_code = None
                self._error_message = None
                self._progress_downloaded = 0
                self._progress_total = 0
        except ManifestError as exc:
            if not self._is_current(generation):
                return
            if exc.code == "UPDATE_NO_NEW_VERSION":
                with self._lock:
                    if self._closed or generation != self._generation:
                        return
                    self._manifest = None
                    self._state = "up_to_date"
                    self._reason = None
                    self._error_code = None
                    self._error_message = None
            else:
                self._set("failed", error_code=exc.code, error_message=exc.message)
        except (TimeoutError, socket.timeout):
            if self._is_current(generation):
                self._set(
                    "failed",
                    error_code="UPDATE_DOWNLOAD_TIMEOUT",
                    error_message="检查响应超过总期限",
                )
        except UpdateError as exc:
            if self._is_current(generation):
                self._set("failed", error_code=exc.code, error_message=exc.message)
        except Exception:  # noqa: BLE001 - bounded user-facing failure
            if self._is_current(generation):
                if time.monotonic() > deadline:
                    self._set(
                        "failed",
                        error_code="UPDATE_DOWNLOAD_TIMEOUT",
                        error_message="检查响应超过总期限",
                    )
                else:
                    self._set("failed", error_code="UPDATE_CHECK_FAILED", error_message="检查更新失败")
        finally:
            _close_io(response=response, sock=sock, conn=conn)
            with self._lock:
                if self._active_connection is conn:
                    self._active_connection = None
                if self._active_response is response:
                    self._active_response = None
                if self._active_socket is sock:
                    self._active_socket = None

    def download(self) -> dict[str, Any]:
        with self._lock:
            if self._closed or self._state != "available" or self._manifest is None:
                return self._snapshot()
            self._download_id = secrets.token_hex(12)
            self._staging_dir = self.staging_root / self._download_id
            isolation_error = self._isolation_error()
            if isolation_error is not None:
                self._staging_dir = None
                self._state = "failed"
                self._error_code = isolation_error
                self._error_message = "更新暂存目录与数据或凭据根重叠，已拒绝下载"
                self._reason = None
                return self._snapshot()
            try:
                ensure_safe_path(self.staging_root)
                ensure_safe_path(self._staging_dir)
                self._staging_dir.mkdir(parents=True, exist_ok=True)
            except PathSafetyError as exc:
                self._staging_dir = None
                self._state = "failed"
                self._error_code = "UPDATE_STAGING_UNSAFE"
                self._error_message = "更新暂存路径包含链接或重解析点，已拒绝写入"
                self._reason = None
                return self._snapshot()
            except OSError:
                self._staging_dir = None
                self._state = "failed"
                self._error_code = "UPDATE_STAGING_UNAVAILABLE"
                self._error_message = "更新暂存目录不可用，已拒绝下载"
                self._reason = None
                return self._snapshot()
            self._cancel.clear()
            self._progress_downloaded = 0
            self._progress_total = self._manifest.package_size
            self._state = "downloading"
            self._reason = None
            self._error_code = None
            self._error_message = None
            self._generation += 1
            generation = self._generation
            self._thread = threading.Thread(
                target=self._download_worker,
                args=(generation, self._manifest, self._staging_dir),
                daemon=True,
            )
            self._thread.start()
        return self._snapshot()

    def _download_worker(
        self, generation: int, manifest: UpdateManifest, staging_dir: Path
    ) -> None:
        part = staging_dir / "package.zip.part"
        package = staging_dir / "package.zip"
        conn = None
        response = None
        sock = None
        try:
            assert self.source is not None
            deadline = time.monotonic() + self.total_timeout
            conn = _request(
                self.source,
                manifest.package_url,
                self.read_timeout,
                deadline=deadline,
            )
            with self._lock:
                if self._closed or generation != self._generation:
                    conn.close()
                    return
                self._active_connection = conn
            _set_socket_timeout(conn.sock, self.read_timeout, deadline)
            response = conn.getresponse()
            sock = _response_socket(response, conn)
            with self._lock:
                if self._closed or generation != self._generation:
                    return
                self._active_response = response
                self._active_socket = sock
            _set_socket_timeout(sock, self.read_timeout, deadline)
            if response.status != 200:
                raise UpdateError("UPDATE_DOWNLOAD_FAILED", f"下载 HTTP {response.status}")
            length = response.getheader("Content-Length")
            if length is None:
                raise UpdateError("UPDATE_DOWNLOAD_INVALID", "下载响应缺少 Content-Length")
            try:
                size = int(length)
            except ValueError:
                raise UpdateError("UPDATE_DOWNLOAD_INVALID", "下载大小不合法") from None
            if size != manifest.package_size or size > MAX_PACKAGE_BYTES:
                raise UpdateError("UPDATE_PACKAGE_MISMATCH", "下载大小与发行元数据不符")
            digest = hashlib.sha256()
            downloaded = 0
            with part.open("xb") as handle:
                while downloaded < size:
                    if self._cancel.is_set() or not self._is_current(generation):
                        raise UpdateCancelled()
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise UpdateError("UPDATE_DOWNLOAD_TIMEOUT", "下载超过总期限")
                    if sock is not None:
                        sock.settimeout(min(self.read_timeout, remaining))
                    chunk = response.read1(min(CHUNK, size - downloaded))
                    if not chunk:
                        if time.monotonic() > deadline:
                            raise UpdateError("UPDATE_DOWNLOAD_TIMEOUT", "下载超过总期限")
                        raise UpdateError("UPDATE_DOWNLOAD_INVALID", "下载提前结束")
                    if time.monotonic() > deadline:
                        raise UpdateError("UPDATE_DOWNLOAD_TIMEOUT", "下载超过总期限")
                    handle.write(chunk)
                    digest.update(chunk)
                    downloaded += len(chunk)
                    with self._lock:
                        if self._closed or generation != self._generation:
                            raise UpdateCancelled()
                        self._progress_downloaded = downloaded
                handle.flush()
                os.fsync(handle.fileno())
            if self._cancel.is_set() or not self._is_current(generation):
                raise UpdateCancelled()
            if digest.hexdigest() != manifest.package_sha256:
                raise UpdateError("UPDATE_PACKAGE_MISMATCH", "下载 SHA-256 与发行元数据不符")
            if self._cancel.is_set() or not self._is_current(generation):
                raise UpdateCancelled()
            part.replace(package)
            if self._cancel.is_set() or not self._is_current(generation):
                raise UpdateCancelled()
            if not self._publish(generation, "verifying"):
                raise UpdateCancelled()
            verified = verify_package_zip(package, manifest, staging_dir)
            if self._cancel.is_set() or not self._is_current(generation):
                raise UpdateCancelled()
            if not self._publish(
                generation,
                "ready",
                downloaded=manifest.package_size,
                total=manifest.package_size,
                staging_dir=verified.root.parent,
            ):
                raise UpdateCancelled()
        except UpdateCancelled:
            if not self._closed and generation == self._generation:
                self._clean_cancel(staging_dir)
                self._publish(generation, "cancelled", reason="UPDATE_CANCELLED")
        except (TimeoutError, socket.timeout):
            if not self._is_current(generation):
                return
            if self._cancel.is_set():
                self._clean_cancel(staging_dir)
                self._publish(generation, "cancelled", reason="UPDATE_CANCELLED")
                return
            self._preserve_failure(staging_dir, "UPDATE_DOWNLOAD_TIMEOUT", "下载读取超时")
            self._publish(
                generation,
                "failed",
                error_code="UPDATE_DOWNLOAD_TIMEOUT",
                error_message="下载读取超时",
            )
        except ManifestError as exc:
            if not self._is_current(generation):
                return
            self._preserve_failure(staging_dir, exc.code, exc.message)
            self._publish(generation, "failed", error_code=exc.code, error_message=exc.message)
        except UpdateError as exc:
            if not self._is_current(generation):
                return
            if self._cancel.is_set():
                self._clean_cancel(staging_dir)
                self._publish(generation, "cancelled", reason="UPDATE_CANCELLED")
                return
            self._preserve_failure(staging_dir, exc.code, exc.message)
            self._publish(generation, "failed", error_code=exc.code, error_message=exc.message)
        except Exception:  # noqa: BLE001 - bounded user-facing failure
            if not self._is_current(generation):
                return
            if self._cancel.is_set():
                self._clean_cancel(staging_dir)
                self._publish(generation, "cancelled", reason="UPDATE_CANCELLED")
                return
            if time.monotonic() > deadline:
                self._preserve_failure(staging_dir, "UPDATE_DOWNLOAD_TIMEOUT", "下载超过总期限")
                self._publish(
                    generation,
                    "failed",
                    error_code="UPDATE_DOWNLOAD_TIMEOUT",
                    error_message="下载超过总期限",
                )
                return
            self._preserve_failure(staging_dir, "UPDATE_DOWNLOAD_FAILED", "下载或校验失败")
            self._publish(
                generation,
                "failed",
                error_code="UPDATE_DOWNLOAD_FAILED",
                error_message="下载或校验失败",
            )
        finally:
            _close_io(response=response, sock=sock, conn=conn)
            with self._lock:
                if self._active_connection is conn:
                    self._active_connection = None
                if self._active_response is response:
                    self._active_response = None
                if self._active_socket is sock:
                    self._active_socket = None

    def cancel(self) -> dict[str, Any]:
        with self._lock:
            if self._state != "downloading":
                return self._snapshot()
            self._cancel.set()
            conn = self._active_connection
            response = self._active_response
            sock = self._active_socket
        _close_io(response=response, sock=sock, conn=conn)
        return self._snapshot()

    def _clean_cancel(self, staging_dir: Path) -> None:
        shutil.rmtree(staging_dir, ignore_errors=True)

    def _preserve_failure(self, staging_dir: Path, code: str, message: str) -> None:
        # Keep the first failed download evidence; never delete it as a
        # generic startup cleanup. The page only receives the sanitized code.
        try:
            ensure_safe_path(staging_dir)
            staging_dir.mkdir(parents=True, exist_ok=True)
            (staging_dir / "failure.json").write_text(
                json.dumps(
                    {"code": code, "message": message, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError:
            pass

    def shutdown(self) -> bool:
        with self._lock:
            self._closed = True
            self._generation += 1
            self._cancel.set()
            self._state = "closed"
            self._reason = "UPDATE_SHUTDOWN"
            self._error_code = None
            self._error_message = None
            thread = self._thread
            conn = self._active_connection
            response = self._active_response
            sock = self._active_socket
        _close_io(response=response, sock=sock, conn=conn)
        if thread is not None:
            thread.join(timeout=5.0)
            return not thread.is_alive()
        return True


def _default_staging_root() -> Path:
    import update_paths

    return update_paths.staging_root()
