"""HTTPS WebDAV transport for the complete backup package.

Only the standard library is used (``http.client`` + ``ssl``); no new
dependency is introduced.  The client is deliberately narrow:

- HTTPS only (the URL is validated by ``webdav_credentials``); TLS
  certificate and hostname verification is always on by default.  Tests may
  inject an isolated ``ssl.SSLContext`` built from a synthetic CA; the
  production default is ``ssl.create_default_context()`` with the bundled
  certifi public roots loaded on top of the system trust store.
- Redirects are never followed.  Any 3xx answer is a controlled error, so
  credentials cannot be forwarded to a different origin.
- Every remote path is built strictly below the configured collection; upload
  names are generated from a random snapshot id, and only final
  ``kgm-backup-<utc>-<snapshot>.kgmbackup`` names are listable.  Partial
  uploads (``*.partial``) and foreign files never enter the version list.
- Upload is immutable: a unique partial name is PUT, then MOVE with
  ``Overwrite: F`` publishes it.  An existing final name is never replaced;
  a repeat of the same snapshot is verified (HEAD size) and reported as
  already published, a different file is a collision.
- Size, whole-operation time and transfer-rate limits are enforced; cancel is
  checked between chunks.  All failures map to stable ``WEBDAV_*`` codes with
  teacher-facing text; no URL with credentials, password or absolute local
  path is included in a message.
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import os
import re
import socket
import ssl
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.local import backup_format
from webdav_credentials import WebdavEndpoint

DAV_NS = "DAV:"
USER_AGENT = "KindergartenManager-WebDAV/1"
NAME_PREFIX = "kgm-backup-"
PARTIAL_PREFIX = "kgm-partial-"
FINAL_PATTERN = re.compile(
    r"^kgm-backup-(\d{8}T\d{6}Z)-([0-9a-f]{32})\.kgmbackup$"
)
PARTIAL_PATTERN = re.compile(r"^kgm-partial-([0-9a-f]{32})\.kgmbackup\.partial$")
SNAPSHOT_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")

MAX_LIST_VERSIONS = 200
MAX_MULTISTATUS_BYTES = 2 * 1024 * 1024
MAX_SMALL_RESPONSE_BYTES = 64 * 1024

DEFAULT_CONNECT_TIMEOUT = 10.0
DEFAULT_IO_TIMEOUT = 30.0
DEFAULT_OPERATION_TIMEOUT = 1800.0
DEFAULT_RATE_BYTES_PER_SECOND = 8 * 1024 * 1024
DEFAULT_MAX_PACKAGE_BYTES = 8 * 1024 * 1024 * 1024
DEFAULT_CHUNK_BYTES = 256 * 1024


class WebdavError(RuntimeError):
    """Controlled WebDAV refusal with a stable public code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class WebdavCancelled(WebdavError):
    def __init__(self, message: str = "WebDAV 操作已取消"):
        super().__init__("WEBDAV_CANCELLED", message)


@dataclass(frozen=True)
class WebdavVersion:
    name: str
    size: int
    modified_at: str | None


@dataclass(frozen=True)
class UploadResult:
    name: str
    size: int
    already_published: bool
    verified: bool = True


@dataclass(frozen=True)
class DownloadResult:
    name: str
    size: int
    sha256: str


def remote_name_for(snapshot_id: str, *, now: datetime | None = None) -> str:
    """Final immutable remote name for one snapshot id."""
    if not SNAPSHOT_ID_PATTERN.fullmatch(snapshot_id or ""):
        raise WebdavError("WEBDAV_NAME_INVALID", "备份标识不合法")
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = moment.strftime("%Y%m%dT%H%M%SZ")
    return f"{NAME_PREFIX}{stamp}-{snapshot_id}.kgmbackup"


class _DeadlineGuard:
    """Close the socket at a monotonic whole-operation deadline.

    A per-read socket timeout alone lets a trickling server exceed the total
    budget forever; the timer shuts the socket down so the blocked read fails.
    """

    def __init__(self, connection: http.client.HTTPSConnection, seconds: float):
        self.connection = connection
        self.deadline = time.monotonic() + max(0.001, seconds)
        self.expired = threading.Event()
        self._response = None
        self._response_sock = None
        self._timer = threading.Timer(max(0.001, seconds), self._expire)
        self._timer.daemon = True
        self._timer.start()

    def attach_response(self, response) -> None:
        self._response = response
        sock = getattr(self.connection, "sock", None)
        if sock is None:
            fp = getattr(response, "fp", None)
            raw = getattr(fp, "raw", None)
            sock = getattr(raw, "_sock", None) or getattr(fp, "_sock", None)
        self._response_sock = sock

    def _expire(self) -> None:
        self.expired.set()
        sock = self._response_sock or getattr(self.connection, "sock", None)
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if self._response is not None:
            try:
                self._response.close()
            except Exception:  # noqa: BLE001 - deadline cleanup
                pass
        try:
            self.connection.close()
        except Exception:  # noqa: BLE001
            pass

    def cancel(self) -> None:
        self._timer.cancel()

    def remaining(self) -> float:
        return self.deadline - time.monotonic()


def _check_cancel(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise WebdavCancelled()


def _basic_auth(username: str, password: str) -> str:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _load_bundled_public_roots(context: ssl.SSLContext) -> None:
    """Add the bundled certifi public roots on top of the system trust.

    A public WebDAV host can chain to a root the Windows system store lacks
    (observed for the CFCA chain of data.cstcloud.cn).  certifi ships with
    the locked package and is loaded in addition to, never instead of, the
    system roots; certificate and hostname verification stays strict.
    """
    import certifi

    context.load_verify_locations(cafile=certifi.where())


def _read_body_bounded(response, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(min(65536, limit - total + 1))
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise WebdavError("WEBDAV_RESPONSE_INVALID", "WebDAV 服务器响应超出上限")
        chunks.append(chunk)
    return b"".join(chunks)


def _parse_version_entries(body: bytes, collection_path: str) -> list[WebdavVersion]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise WebdavError("WEBDAV_RESPONSE_INVALID", "WebDAV 版本列表格式不正确") from exc
    entries: list[WebdavVersion] = []
    for response in root.iter(f"{{{DAV_NS}}}response"):
        href = response.findtext(f"{{{DAV_NS}}}href")
        if not href:
            continue
        path = urllib.parse.urlsplit(href).path
        if not path.startswith(collection_path):
            # A server answer outside the configured collection is ignored,
            # never used as a download path.
            continue
        name = urllib.parse.unquote(path[len(collection_path):])
        if "/" in name or "\\" in name or name in ("", ".", ".."):
            continue
        if not FINAL_PATTERN.fullmatch(name):
            continue
        prop = response.find(f"{{{DAV_NS}}}propstat/{{{DAV_NS}}}prop")
        if prop is None:
            continue
        resource_type = prop.find(f"{{{DAV_NS}}}resourcetype")
        if resource_type is not None and resource_type.find(f"{{{DAV_NS}}}collection") is not None:
            continue
        size_text = prop.findtext(f"{{{DAV_NS}}}getcontentlength")
        try:
            size = int(size_text) if size_text is not None else -1
        except ValueError:
            size = -1
        modified = prop.findtext(f"{{{DAV_NS}}}getlastmodified")
        entries.append(
            WebdavVersion(
                name=name,
                size=max(size, 0) if size >= 0 else 0,
                modified_at=modified.strip() if modified else None,
            )
        )
    entries.sort(key=lambda item: item.name, reverse=True)
    return entries


def _coerce_utc(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise WebdavError("WEBDAV_NAME_INVALID", "备份创建时间不合法") from exc
        value = parsed
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class WebdavClient:
    """One configured WebDAV collection, one bounded operation at a time."""

    def __init__(
        self,
        endpoint: WebdavEndpoint,
        *,
        ssl_context: ssl.SSLContext | None = None,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        io_timeout: float = DEFAULT_IO_TIMEOUT,
        operation_timeout: float = DEFAULT_OPERATION_TIMEOUT,
        rate_bytes_per_second: float = DEFAULT_RATE_BYTES_PER_SECOND,
        max_package_bytes: int = DEFAULT_MAX_PACKAGE_BYTES,
        chunk_bytes: int = DEFAULT_CHUNK_BYTES,
    ):
        self.endpoint = endpoint
        self._ssl_context = ssl_context
        self.connect_timeout = max(0.1, float(connect_timeout))
        self.io_timeout = max(0.1, float(io_timeout))
        self.operation_timeout = max(0.1, float(operation_timeout))
        self.rate_bytes_per_second = max(0.0, float(rate_bytes_per_second))
        self.max_package_bytes = min(
            max(1, int(max_package_bytes)), backup_format.MAX_TOTAL_BYTES
        )
        self.chunk_bytes = max(4096, int(chunk_bytes))
        parts = urllib.parse.urlsplit(endpoint.url)
        self._collection_path = parts.path or "/"
        if not self._collection_path.endswith("/"):
            self._collection_path += "/"
        self._collection_path_quoted = urllib.parse.quote(self._collection_path, safe="/")
        self._host = parts.hostname or ""
        if not self._host:
            raise WebdavError("WEBDAV_URL_INVALID", "WebDAV 地址缺少主机名")
        self._port = parts.port
        self._auth_header = _basic_auth(endpoint.username, endpoint.password)
        if ":" in self._host:
            # IPv6 literal: http.client accepts it as-is; Host uses brackets.
            self._connect_host = self._host
            self._host_header_name = f"[{self._host}]"
        else:
            try:
                self._connect_host = self._host.encode("idna").decode("ascii")
            except UnicodeError as exc:
                raise WebdavError("WEBDAV_URL_INVALID", "WebDAV 主机名不正确") from exc
            self._host_header_name = self._connect_host.lower()

    # -- TLS / connection ------------------------------------------------
    def _context(self) -> ssl.SSLContext:
        # Production default: full certificate + hostname verification over
        # the system trust store plus the bundled certifi public roots.
        # Tests pass their own isolated context, which is returned untouched.
        if self._ssl_context is not None:
            return self._ssl_context
        context = ssl.create_default_context()
        try:
            _load_bundled_public_roots(context)
        except (ImportError, OSError, ssl.SSLError):
            # The strict system trust store still applies without the bundle.
            pass
        return context

    def _connect(self) -> http.client.HTTPSConnection:
        context = self._context()
        try:
            return http.client.HTTPSConnection(
                self._connect_host,
                self._port,
                timeout=self.connect_timeout,
                context=context,
            )
        except (ssl.SSLError, OSError) as exc:
            raise WebdavError("WEBDAV_CONNECT_FAILED", "无法连接 WebDAV 服务器") from exc

    @staticmethod
    def _map_transport_error(exc: BaseException, guard: _DeadlineGuard | None) -> WebdavError:
        if guard is not None and guard.expired.is_set():
            return WebdavError("WEBDAV_TIMEOUT", "WebDAV 操作超时，请稍后重试")
        if isinstance(exc, http.client.IncompleteRead):
            return WebdavError("WEBDAV_TRANSFER_INCOMPLETE", "WebDAV 传输不完整，已停止")
        if isinstance(exc, ssl.SSLCertVerificationError):
            return WebdavError(
                "WEBDAV_CERTIFICATE_INVALID", "无法验证 WebDAV 服务器证书，已停止连接"
            )
        if isinstance(exc, ssl.SSLError):
            return WebdavError("WEBDAV_TLS_FAILED", "WebDAV 安全连接失败，已停止连接")
        if isinstance(exc, (socket.timeout, TimeoutError)):
            return WebdavError("WEBDAV_TIMEOUT", "WebDAV 操作超时，请稍后重试")
        return WebdavError("WEBDAV_CONNECT_FAILED", "无法连接 WebDAV 服务器")

    def _remote_path(self, name: str) -> str:
        """Build and re-check one request path strictly below the collection."""
        if not name or "/" in name or "\\" in name or name in (".", ".."):
            raise WebdavError("WEBDAV_PATH_ESCAPE", "拒绝越出配置集合的 WebDAV 路径")
        path = self._collection_path_quoted + urllib.parse.quote(name, safe="")
        if not path.startswith(self._collection_path_quoted):
            raise WebdavError("WEBDAV_PATH_ESCAPE", "拒绝越出配置集合的 WebDAV 路径")
        return path

    def _absolute_url(self, path: str) -> str:
        return f"https://{self._host_header_name}{self._format_port()}{path}"

    def _format_port(self) -> str:
        if self._port is None or self._port == 443:
            return ""
        return f":{self._port}"

    def _open(
        self, method: str, name: str | None, *, deadline: float | None = None
    ) -> tuple[http.client.HTTPSConnection, http.client.HTTPResponse, _DeadlineGuard]:
        budget = self.operation_timeout if deadline is None else min(
            self.operation_timeout, max(0.1, deadline)
        )
        connection = self._connect()
        guard = _DeadlineGuard(connection, budget)
        path = self._collection_path_quoted if name is None else self._remote_path(name)
        try:
            connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            connection.putheader("Host", self._host_header())
            connection.putheader("User-Agent", USER_AGENT)
            connection.putheader("Authorization", self._auth_header)
        except Exception as exc:  # noqa: BLE001 - transport boundary
            guard.cancel()
            connection.close()
            raise self._map_transport_error(exc, guard) from exc
        return connection, path, guard

    def _host_header(self) -> str:
        if self._port is None:
            return self._host_header_name
        return f"{self._host_header_name}:{self._port}"

    def _finish(
        self,
        connection: http.client.HTTPSConnection,
        response: http.client.HTTPResponse | None,
        guard: _DeadlineGuard,
    ) -> None:
        guard.cancel()
        if response is not None:
            try:
                response.close()
            except Exception:  # noqa: BLE001 - cleanup only
                pass
        try:
            connection.close()
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _reject_redirect(status: int) -> None:
        if status in (301, 302, 303, 307, 308):
            raise WebdavError(
                "WEBDAV_REDIRECT_REJECTED",
                "WebDAV 服务器要求重定向，已拒绝以免把凭据发往其他地址",
            )

    @staticmethod
    def _auth_error(status: int) -> bool:
        return status in (401, 403)

    # -- collection / versions ------------------------------------------
    def ensure_collection(self, *, timeout: float | None = None) -> dict:
        """Verify the collection; create it once with MKCOL when missing."""
        deadline = self.operation_timeout if timeout is None else timeout
        body = (
            b'<?xml version="1.0" encoding="utf-8"?>'
            b'<d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/></d:prop></d:propfind>'
        )
        status = self._propfind_status(body, depth="0", deadline=deadline)
        if status in (200, 207):
            return {"ok": True, "created": False}
        if self._auth_error(status):
            raise WebdavError(
                "WEBDAV_AUTH_FAILED", "WebDAV 用户名或密码不正确，或没有访问权限"
            )
        if status != 404:
            raise WebdavError(
                "WEBDAV_COLLECTION_FAILED", "无法访问 WebDAV 备份目录，请检查地址"
            )
        mkcol_status = self._simple_status("MKCOL", None, deadline=deadline)
        if self._auth_error(mkcol_status):
            raise WebdavError(
                "WEBDAV_AUTH_FAILED", "WebDAV 用户名或密码不正确，或没有访问权限"
            )
        if mkcol_status not in (200, 201, 204, 405):
            raise WebdavError(
                "WEBDAV_COLLECTION_FAILED", "无法创建 WebDAV 备份目录，请检查路径"
            )
        return {"ok": True, "created": True}

    def list_versions(self, *, cancel: threading.Event | None = None) -> list[WebdavVersion]:
        body = (
            b'<?xml version="1.0" encoding="utf-8"?>'
            b'<d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/>'
            b"<d:getcontentlength/><d:getlastmodified/></d:prop></d:propfind>"
        )
        _check_cancel(cancel)
        connection, path, guard = self._open("PROPFIND", None)
        response = None
        try:
            connection.putheader("Depth", "1")
            connection.putheader("Content-Type", "application/xml; charset=utf-8")
            connection.putheader("Content-Length", str(len(body)))
            connection.endheaders(body)
            response = connection.getresponse()
            guard.attach_response(response)
            status = response.status
            self._reject_redirect(status)
            if self._auth_error(status):
                raise WebdavError(
                    "WEBDAV_AUTH_FAILED", "WebDAV 用户名或密码不正确，或没有访问权限"
                )
            if status == 404:
                raise WebdavError("WEBDAV_COLLECTION_FAILED", "远端备份目录不存在")
            if status not in (200, 207):
                raise WebdavError(
                    "WEBDAV_HTTP_ERROR", f"WebDAV 服务器返回错误（{status}）"
                )
            raw = _read_body_bounded(response, MAX_MULTISTATUS_BYTES)
        except WebdavError:
            raise
        except Exception as exc:  # noqa: BLE001 - transport boundary
            raise self._map_transport_error(exc, guard) from exc
        finally:
            self._finish(connection, response, guard)
        _check_cancel(cancel)
        entries = _parse_version_entries(raw, self._collection_path_quoted)
        return entries[:MAX_LIST_VERSIONS]

    def _propfind_status(
        self, body: bytes, *, depth: str, deadline: float
    ) -> int:
        connection, _path, guard = self._open("PROPFIND", None, deadline=deadline)
        response = None
        try:
            connection.putheader("Depth", depth)
            connection.putheader("Content-Type", "application/xml; charset=utf-8")
            connection.putheader("Content-Length", str(len(body)))
            connection.endheaders(body)
            response = connection.getresponse()
            guard.attach_response(response)
            self._reject_redirect(response.status)
            try:
                _read_body_bounded(response, MAX_SMALL_RESPONSE_BYTES)
            except WebdavError:
                pass
            return response.status
        except WebdavError:
            raise
        except Exception as exc:  # noqa: BLE001 - transport boundary
            raise self._map_transport_error(exc, guard) from exc
        finally:
            self._finish(connection, response, guard)

    def _simple_status(
        self, method: str, name: str | None, *, deadline: float
    ) -> int:
        connection, _path, guard = self._open(method, name, deadline=deadline)
        response = None
        try:
            connection.putheader("Content-Length", "0")
            connection.endheaders()
            response = connection.getresponse()
            guard.attach_response(response)
            self._reject_redirect(response.status)
            try:
                _read_body_bounded(response, MAX_SMALL_RESPONSE_BYTES)
            except WebdavError:
                pass
            return response.status
        except WebdavError:
            raise
        except Exception as exc:  # noqa: BLE001 - transport boundary
            raise self._map_transport_error(exc, guard) from exc
        finally:
            self._finish(connection, response, guard)

    def head_size(self, name: str, *, deadline: float) -> int | None:
        connection, _path, guard = self._open("HEAD", name, deadline=deadline)
        response = None
        try:
            connection.endheaders()
            response = connection.getresponse()
            guard.attach_response(response)
            self._reject_redirect(response.status)
            if self._auth_error(response.status):
                raise WebdavError(
                    "WEBDAV_AUTH_FAILED", "WebDAV 用户名或密码不正确，或没有访问权限"
                )
            if response.status != 200:
                return None
            length = response.getheader("Content-Length")
            try:
                return int(length) if length is not None else None
            except ValueError:
                return None
        except WebdavError:
            raise
        except Exception as exc:  # noqa: BLE001 - transport boundary
            raise self._map_transport_error(exc, guard) from exc
        finally:
            self._finish(connection, response, guard)

    # -- upload ----------------------------------------------------------
    @staticmethod
    def _peek_local_header(package: Path) -> backup_format.BackupHeader:
        """Parse the standard Format 1 header without trusting an extension."""
        try:
            size = package.stat().st_size
            with package.open("rb") as handle:
                raw = handle.read(backup_format.HEADER_LEN)
        except OSError as exc:
            raise WebdavError("WEBDAV_LOCAL_PACKAGE_MISSING", "本地备份文件不可读取") from exc
        try:
            return backup_format.parse_header(raw, file_size=size)
        except backup_format.BackupFormatError as exc:
            raise WebdavError(
                "WEBDAV_LOCAL_PACKAGE_INVALID", "本地备份文件格式不正确"
            ) from exc

    def upload(
        self,
        package_path: str | Path,
        snapshot_id: str,
        *,
        created_at: datetime | str | None = None,
        progress=None,
        cancel: threading.Event | None = None,
    ) -> UploadResult:
        package = Path(package_path)
        if not package.is_file():
            raise WebdavError("WEBDAV_LOCAL_PACKAGE_MISSING", "本地备份文件不存在")
        size = package.stat().st_size
        if size <= 0 or size > self.max_package_bytes:
            raise WebdavError("WEBDAV_SIZE_LIMIT", "备份文件大小超出 WebDAV 上传上限")
        header = self._peek_local_header(package)
        if header.mode != backup_format.MODE_PASSWORD:
            # A remote copy must never contain readable business/photos.
            raise WebdavError(
                "WEBDAV_ENCRYPTION_REQUIRED",
                "上传到 WebDAV 的备份必须使用密码加密；请重新创建加密备份",
            )

        # The remote name is bound to the snapshot's own creation time, so a
        # repeated/unknown earlier request targets the same immutable version.
        final_name = remote_name_for(snapshot_id, now=_coerce_utc(created_at))
        partial_name = f"{PARTIAL_PREFIX}{snapshot_id}.kgmbackup.partial"
        self.ensure_collection()
        _check_cancel(cancel)
        self._put_file(partial_name, package, size, progress=progress, cancel=cancel)
        _check_cancel(cancel)
        moved = self._move_immutable(partial_name, final_name)
        if not moved:
            # The final name already exists (a repeated/unknown earlier request
            # or another device with the same snapshot id).  Never replace or
            # delete it: confirm the bytes or report the unverified state.
            local_sha = backup_format.sha256_file(package)
            remote_sha = self._remote_sha256(final_name, cancel=cancel)
            if remote_sha is not None and remote_sha == local_sha:
                return UploadResult(
                    name=final_name, size=size, already_published=True
                )
            if remote_sha is not None:
                raise WebdavError(
                    "WEBDAV_VERSION_COLLISION",
                    "远端已存在同名备份且内容不一致，已保留原版本，未覆盖",
                )
            raise WebdavError(
                "WEBDAV_VERSION_UNVERIFIED",
                "远端已存在同名备份，未能核对内容；请刷新版本列表确认，未覆盖原文件",
            )
        remote_size = self._remote_size(final_name, cancel=cancel)
        if remote_size is None:
            # The MOVE itself succeeded; size confirmation was not offered by
            # this server.  Report the upload without claiming byte verification.
            return UploadResult(
                name=final_name,
                size=size,
                already_published=False,
                verified=False,
            )
        if remote_size != size:
            # Never delete the published final name here: another answer may
            # already reference it.  Report the unconfirmed state honestly.
            raise WebdavError(
                "WEBDAV_VERIFY_FAILED",
                "上传已提交，但未能核对远端备份大小；请刷新版本列表确认",
            )
        return UploadResult(name=final_name, size=size, already_published=False)

    def _remote_size(
        self, name: str, *, cancel: threading.Event | None = None
    ) -> int | None:
        _check_cancel(cancel)
        try:
            size = self.head_size(name, deadline=self.io_timeout)
        except WebdavCancelled:
            raise
        except WebdavError:
            size = None
        if size is not None:
            return size
        _check_cancel(cancel)
        # Some WebDAV servers do not answer HEAD; ask for the single entry.
        body = (
            b'<?xml version="1.0" encoding="utf-8"?>'
            b'<d:propfind xmlns:d="DAV:"><d:prop><d:getcontentlength/>'
            b"</d:prop></d:propfind>"
        )
        connection, _path, guard = self._open("PROPFIND", name)
        response = None
        try:
            connection.putheader("Depth", "0")
            connection.putheader("Content-Type", "application/xml; charset=utf-8")
            connection.putheader("Content-Length", str(len(body)))
            connection.endheaders(body)
            response = connection.getresponse()
            guard.attach_response(response)
            self._reject_redirect(response.status)
            if response.status not in (200, 207):
                return None
            raw = _read_body_bounded(response, MAX_SMALL_RESPONSE_BYTES)
        except WebdavCancelled:
            raise
        except Exception:  # noqa: BLE001 - size confirmation is best effort
            return None
        finally:
            self._finish(connection, response, guard)
        entries = _parse_version_entries(raw, self._collection_path_quoted)
        for entry in entries:
            if entry.name == name:
                return entry.size
        return None

    def _remote_sha256(
        self, name: str, *, cancel: threading.Event | None = None
    ) -> str | None:
        """Hash one remote final file; ``None`` means "could not verify"."""
        _check_cancel(cancel)
        try:
            connection, _path, guard = self._open("GET", name)
        except WebdavCancelled:
            raise
        except WebdavError:
            return None
        response = None
        hasher = hashlib.sha256()
        total = 0
        try:
            connection.endheaders()
            response = connection.getresponse()
            guard.attach_response(response)
            self._reject_redirect(response.status)
            if response.status != 200:
                return None
            while True:
                _check_cancel(cancel)
                if guard.remaining() <= 0:
                    return None
                chunk = response.read(self.chunk_bytes)
                if not chunk:
                    break
                total += len(chunk)
                if total > self.max_package_bytes:
                    return None
                hasher.update(chunk)
        except WebdavCancelled:
            raise
        except Exception:  # noqa: BLE001 - verification is best effort
            return None
        finally:
            self._finish(connection, response, guard)
        return hasher.hexdigest()

    def _put_file(
        self,
        name: str,
        package: Path,
        size: int,
        *,
        progress,
        cancel: threading.Event | None,
    ) -> None:
        connection, _path, guard = self._open("PUT", name)
        response = None
        sent = 0
        started = time.monotonic()
        try:
            connection.putheader("Content-Type", "application/octet-stream")
            connection.putheader("Content-Length", str(size))
            connection.endheaders()
            with package.open("rb") as source:
                while sent < size:
                    _check_cancel(cancel)
                    if guard.remaining() <= 0:
                        raise WebdavError("WEBDAV_TIMEOUT", "WebDAV 上传超时，请稍后重试")
                    chunk = source.read(min(self.chunk_bytes, size - sent))
                    if not chunk:
                        raise WebdavError(
                            "WEBDAV_LOCAL_PACKAGE_CHANGED", "本地备份文件在上传期间被改动"
                        )
                    connection.send(chunk)
                    sent += len(chunk)
                    if progress is not None:
                        progress(
                            {
                                "stage": "upload",
                                "done": sent,
                                "total": size,
                                "message": "上传备份",
                            }
                        )
                    self._pace(started, sent)
                trailing = source.read(1)
            if trailing:
                raise WebdavError(
                    "WEBDAV_LOCAL_PACKAGE_CHANGED", "本地备份文件在上传期间被改动"
                )
            response = connection.getresponse()
            guard.attach_response(response)
            self._reject_redirect(response.status)
            if self._auth_error(response.status):
                raise WebdavError(
                    "WEBDAV_AUTH_FAILED", "WebDAV 用户名或密码不正确，或没有访问权限"
                )
            if response.status not in (200, 201, 204):
                raise WebdavError(
                    "WEBDAV_UPLOAD_FAILED",
                    f"WebDAV 上传失败（服务器返回 {response.status}）",
                )
        except WebdavError:
            raise
        except Exception as exc:  # noqa: BLE001 - transport boundary
            raise self._map_transport_error(exc, guard) from exc
        finally:
            self._finish(connection, response, guard)

    def _move_immutable(self, partial_name: str, final_name: str) -> bool:
        connection, _path, guard = self._open("MOVE", partial_name)
        response = None
        try:
            connection.putheader("Destination", self._absolute_url(self._remote_path(final_name)))
            connection.putheader("Overwrite", "F")
            connection.putheader("Content-Length", "0")
            connection.endheaders()
            response = connection.getresponse()
            guard.attach_response(response)
            self._reject_redirect(response.status)
            if self._auth_error(response.status):
                raise WebdavError(
                    "WEBDAV_AUTH_FAILED", "WebDAV 用户名或密码不正确，或没有访问权限"
                )
            try:
                _read_body_bounded(response, MAX_SMALL_RESPONSE_BYTES)
            except WebdavError:
                pass
            if response.status in (201, 204):
                return True
            if response.status in (412, 409):
                return False
            raise WebdavError(
                "WEBDAV_UPLOAD_FAILED", f"WebDAV 发布备份失败（服务器返回 {response.status}）"
            )
        except WebdavError:
            raise
        except Exception as exc:  # noqa: BLE001 - transport boundary
            raise self._map_transport_error(exc, guard) from exc
        finally:
            self._finish(connection, response, guard)

    def _delete_quietly(self, name: str) -> None:
        try:
            self._simple_status("DELETE", name, deadline=min(self.io_timeout, 15.0))
        except Exception:  # noqa: BLE001 - cleanup never masks the real result
            pass

    # -- download --------------------------------------------------------
    def download(
        self,
        name: str,
        destination: str | Path,
        *,
        fd: int | None = None,
        progress=None,
        cancel: threading.Event | None = None,
    ) -> DownloadResult:
        """Stream one remote final file into a private staging file.

        ``fd`` may be an already-created exclusive restricted file descriptor
        owned by the caller (preferred: the host creates it with the private
        DACL).  Without ``fd`` this call creates the target exclusively and
        never truncates an existing file; a failure only removes a file this
        call itself created.
        """
        if not FINAL_PATTERN.fullmatch(name or ""):
            raise WebdavError("WEBDAV_NAME_INVALID", "所选远端备份名称不合法")
        target = Path(destination)
        created = False
        if fd is None:
            try:
                fd = os.open(
                    target,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_BINARY", 0),
                )
            except FileExistsError as exc:
                raise WebdavError(
                    "WEBDAV_LOCAL_TARGET_EXISTS", "下载暂存目标已存在，拒绝覆盖"
                ) from exc
            except OSError as exc:
                raise WebdavError(
                    "WEBDAV_STAGING_FAILED", "无法创建下载暂存文件"
                ) from exc
            created = True
        connection = None
        guard = None
        response = None
        total = 0
        hasher = hashlib.sha256()
        started = time.monotonic()
        sink = os.fdopen(fd, "wb")
        try:
            connection, _path, guard = self._open("GET", name)
            connection.endheaders()
            response = connection.getresponse()
            guard.attach_response(response)
            self._reject_redirect(response.status)
            if self._auth_error(response.status):
                raise WebdavError(
                    "WEBDAV_AUTH_FAILED", "WebDAV 用户名或密码不正确，或没有访问权限"
                )
            if response.status == 404:
                raise WebdavError("WEBDAV_VERSION_MISSING", "远端备份已不存在，请刷新版本列表")
            if response.status != 200:
                raise WebdavError(
                    "WEBDAV_DOWNLOAD_FAILED", f"WebDAV 下载失败（服务器返回 {response.status}）"
                )
            declared = response.getheader("Content-Length")
            declared_size: int | None
            try:
                declared_size = int(declared) if declared is not None else None
            except ValueError:
                declared_size = None
            if declared_size is not None and declared_size > self.max_package_bytes:
                raise WebdavError("WEBDAV_SIZE_LIMIT", "远端备份超过下载大小上限")
            if declared_size is not None and declared_size < backup_format.HEADER_LEN:
                raise WebdavError("WEBDAV_TRANSFER_INCOMPLETE", "远端备份不完整，已停止下载")
            while True:
                _check_cancel(cancel)
                if guard.remaining() <= 0:
                    raise WebdavError("WEBDAV_TIMEOUT", "WebDAV 下载超时，请稍后重试")
                chunk = response.read(self.chunk_bytes)
                if not chunk:
                    break
                total += len(chunk)
                if total > self.max_package_bytes:
                    raise WebdavError("WEBDAV_SIZE_LIMIT", "远端备份超过下载大小上限")
                hasher.update(chunk)
                sink.write(chunk)
                if progress is not None:
                    progress(
                        {
                            "stage": "download",
                            "done": total,
                            "total": declared_size if declared_size else total,
                            "message": "下载备份",
                        }
                    )
                self._pace(started, total)
            sink.flush()
            os.fsync(sink.fileno())
            sink.close()
            sink = None
            if declared_size is not None and total != declared_size:
                raise WebdavError("WEBDAV_TRANSFER_INCOMPLETE", "远端备份下载不完整")
            if total < backup_format.HEADER_LEN:
                raise WebdavError("WEBDAV_TRANSFER_INCOMPLETE", "远端备份不完整")
            header = self._peek_local_header(target)
            if header.mode != backup_format.MODE_PASSWORD:
                raise WebdavError(
                    "WEBDAV_FORMAT_MISMATCH",
                    "远端备份未加密，已拒绝作为恢复来源",
                )
            return DownloadResult(name=name, size=total, sha256=hasher.hexdigest())
        except WebdavError:
            if sink is not None:
                try:
                    sink.close()
                except Exception:  # noqa: BLE001 - cleanup only
                    pass
            if created:
                self._discard_partial_download(target)
            raise
        except Exception as exc:  # noqa: BLE001 - transport boundary
            if sink is not None:
                try:
                    sink.close()
                except Exception:  # noqa: BLE001 - cleanup only
                    pass
            if created:
                self._discard_partial_download(target)
            raise self._map_transport_error(exc, guard) from exc
        finally:
            if connection is not None and guard is not None:
                self._finish(connection, response, guard)

    @staticmethod
    def _discard_partial_download(target: Path) -> None:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass

    # -- pacing ----------------------------------------------------------
    def _pace(self, started: float, transferred: int) -> None:
        if self.rate_bytes_per_second <= 0 or transferred <= 0:
            return
        expected = transferred / self.rate_bytes_per_second
        elapsed = time.monotonic() - started
        if expected > elapsed:
            time.sleep(min(expected - elapsed, 1.0))
