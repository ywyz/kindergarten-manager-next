"""Minimal Nextcloud Tasks (CalDAV VTODO) client, standard library only.

The client is deliberately narrow and mirrors the WebDAV transport rules:

- HTTPS only (the URL is validated by :mod:`todo_sync_credentials`);
  certificate and hostname verification always stay on.  The bundled
  certifi public roots are loaded *on top of* the system trust store so a
  public Nextcloud host chaining to a root the Windows store lacks still
  verifies strictly.
- Redirects are never followed: a 3xx answer is a controlled refusal, so
  credentials cannot be forwarded to a different origin.
- Every response body is read with a hard byte cap; every request has
  connect/read timeouts.
- Fixed codes: ``SYNC_CONNECT_FAILED`` / ``SYNC_AUTH_FAILED`` /
  ``SYNC_TLS_FAILED`` / ``SYNC_RESPONSE_INVALID`` / ``SYNC_SERVER_ERROR`` /
  ``SYNC_NOT_FOUND`` / ``SYNC_PRECONDITION_FAILED``.  No URL with
  credentials, no password and no exception text is ever part of a
  message.

The transport is a seam: production uses :class:`HttpsTransport` while the
synthetic acceptance tests inject a loopback fake — no test ever reaches a
real Nextcloud service.
"""

from __future__ import annotations

import base64
import http.client
import re
import socket
import ssl
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

DAV_NS = "DAV:"
CALDAV_NS = "urn:ietf:params:xml:ns:caldav"
CS_NS = "http://calendarserver.org/ns/"
USER_AGENT = "KindergartenManager-TodoSync/1"

DEFAULT_CONNECT_TIMEOUT = 10.0
DEFAULT_IO_TIMEOUT = 20.0
DEFAULT_OPERATION_TIMEOUT = 60.0
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_TASKS_PER_LIST = 2000

DAV_ROOT_PATH = "/remote.php/dav/"

PROP_CURRENT_USER_PRINCIPAL = (
    b'<?xml version="1.0" encoding="utf-8"?>'
    b'<d:propfind xmlns:d="DAV:"><d:prop>'
    b"<d:current-user-principal/></d:prop></d:propfind>"
)
PROP_HOME_SET = (
    b'<?xml version="1.0" encoding="utf-8"?>'
    b'<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
    b"<d:prop><c:calendar-home-set/></d:prop></d:propfind>"
)
PROP_LISTS = (
    b'<?xml version="1.0" encoding="utf-8"?>'
    b'<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"'
    b"><d:prop><d:resourcetype/><d:displayname/>"
    b"<c:supported-calendar-component-set/></d:prop></d:propfind>"
)
PROP_TASKS = (
    b'<?xml version="1.0" encoding="utf-8"?>'
    b'<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
    b"<d:prop><d:getetag/><c:calendar-data/></d:prop></d:propfind>"
)


class TodoSyncError(RuntimeError):
    """Controlled CalDAV refusal with a stable public code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class TaskListInfo:
    href: str
    display_name: str
    supports_vtodo: bool


@dataclass(frozen=True)
class RemoteTask:
    href: str
    etag: str
    uid: str
    title: str
    due_date: str | None
    completed: bool
    # The raw calendar-data text: the edit path merges into this real remote
    # VCALENDAR so fields the local model does not carry (DESCRIPTION,
    # PRIORITY, VALARM, RELATED-TO, RRULE, a timed/zone DUE, unknown
    # properties) are preserved verbatim instead of being wiped by a fresh
    # minimal payload.
    raw_calendar: str = ""


class Transport(Protocol):
    """One CalDAV request/response round trip.

    ``path`` is the absolute request path (no host); the transport owns TLS
    and authentication.  Returns ``(status, headers, body)`` where headers
    is a case-insensitive dict-like mapping.
    """

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        depth: str | None = None,
    ) -> tuple[int, dict, bytes]: ...


class HttpsTransport:
    """Production transport: strict TLS + Basic auth, never follows redirects."""

    def __init__(
        self,
        url: str,
        username: str,
        password: str,
        *,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        io_timeout: float = DEFAULT_IO_TIMEOUT,
        ssl_context: ssl.SSLContext | None = None,
    ):
        parts = urllib.parse.urlsplit(url)
        self._host = parts.hostname or ""
        if not self._host:
            raise TodoSyncError("SYNC_URL_INVALID", "Nextcloud 地址缺少主机名")
        self._port = parts.port
        self._base_path = (parts.path or "").rstrip("/")
        self._auth = "Basic " + base64.b64encode(
            f"{username}:{password}".encode("utf-8")
        ).decode("ascii")
        self.connect_timeout = max(0.1, connect_timeout)
        self.io_timeout = max(0.1, io_timeout)
        self._ssl_context = ssl_context

    def _context(self) -> ssl.SSLContext:
        if self._ssl_context is not None:
            return self._ssl_context
        context = ssl.create_default_context()
        try:
            import certifi

            context.load_verify_locations(cafile=certifi.where())
        except (ImportError, OSError, ssl.SSLError):
            # The strict system trust store still applies without the bundle.
            pass
        return context

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        depth: str | None = None,
    ) -> tuple[int, dict, bytes]:
        if not path.startswith("/"):
            raise TodoSyncError("SYNC_RESPONSE_INVALID", "CalDAV 请求路径不合法")
        connection = http.client.HTTPSConnection(
            self._host,
            self._port,
            timeout=self.connect_timeout,
            context=self._context(),
        )
        try:
            connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            host_header = self._host
            if ":" in host_header:
                host_header = f"[{host_header}]"
            if self._port is not None:
                host_header = f"{host_header}:{self._port}"
            connection.putheader("Host", host_header)
            connection.putheader("User-Agent", USER_AGENT)
            connection.putheader("Authorization", self._auth)
            connection.putheader("Accept", "application/xml, text/calendar")
            if depth is not None:
                connection.putheader("Depth", depth)
            if body is not None:
                connection.putheader("Content-Type", "application/xml; charset=utf-8")
                connection.putheader("Content-Length", str(len(body)))
            for name, value in (headers or {}).items():
                connection.putheader(name, value)
            connection.endheaders(body if body is not None else b"")
            sock = connection.sock
            if sock is not None:
                sock.settimeout(self.io_timeout)
            response = connection.getresponse()
            status = response.status
            if status in (301, 302, 303, 307, 308):
                raise TodoSyncError(
                    "SYNC_RESPONSE_INVALID",
                    "Nextcloud 要求重定向，已拒绝以免把凭据发往其他地址",
                )
            collected: list[bytes] = []
            total = 0
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_RESPONSE_BYTES:
                    raise TodoSyncError(
                        "SYNC_RESPONSE_INVALID", "Nextcloud 响应超出上限"
                    )
                collected.append(chunk)
            headers = {name.lower(): value for name, value in response.getheaders()}
            return status, headers, b"".join(collected)
        except TodoSyncError:
            raise
        except ssl.SSLCertVerificationError as exc:
            raise TodoSyncError(
                "SYNC_TLS_FAILED", "无法验证 Nextcloud 服务器证书，已停止连接"
            ) from exc
        except ssl.SSLError as exc:
            raise TodoSyncError("SYNC_TLS_FAILED", "Nextcloud 安全连接失败") from exc
        except (socket.timeout, TimeoutError) as exc:
            raise TodoSyncError("SYNC_CONNECT_FAILED", "连接 Nextcloud 超时") from exc
        except OSError as exc:
            raise TodoSyncError("SYNC_CONNECT_FAILED", "无法连接 Nextcloud 服务器") from exc
        finally:
            try:
                connection.close()
            except Exception:  # noqa: BLE001 - cleanup only
                pass


def _text_or_none(element) -> str | None:
    if element is None:
        return None
    value = (element.text or "").strip()
    return value or None


def _parse_multistatus(body: bytes):
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise TodoSyncError("SYNC_RESPONSE_INVALID", "Nextcloud 响应格式不正确") from exc
    if root.tag != f"{{{DAV_NS}}}multistatus":
        raise TodoSyncError("SYNC_RESPONSE_INVALID", "Nextcloud 响应不是 multistatus")
    return root


def _propstat_value(response, prop_tag: str):
    for propstat in response.findall(f"{{{DAV_NS}}}propstat"):
        prop = propstat.find(f"{{{DAV_NS}}}prop")
        if prop is None:
            continue
        target = prop.find(prop_tag)
        if target is not None:
            return target
    return None


def _propstat_success(response, prop_tag: str):
    """Property from a *success* propstat: ``(element, state)``.

    ``state`` is True when a 200 propstat carried the property, False when
    every propstat carrying it reported a non-200 status (the server
    deliberately omits it), and None when the server never mentioned it.
    """
    seen_non_success = False
    for propstat in response.findall(f"{{{DAV_NS}}}propstat"):
        prop = propstat.find(f"{{{DAV_NS}}}prop")
        if prop is None:
            continue
        target = prop.find(prop_tag)
        if target is None:
            continue
        status = _text_or_none(propstat.find(f"{{{DAV_NS}}}status")) or ""
        if " 200 " in f" {status} ":
            return target, True
        seen_non_success = True
    if seen_non_success:
        return None, False
    return None, None


def _unescape_ical(text: str) -> str:
    return (
        text.replace("\\n", "\n")
        .replace("\\N", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
    )


def _escape_ical(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


_LINE_RE = re.compile(r"([A-Z\-]+)(?:;[^:]*)?:(.*)")


def parse_vtodo(raw: str) -> dict:
    """Parse one VTODO into the bounded local projection.

    Only the fields this feature syncs are read: UID, SUMMARY, DUE and the
    completion state (``STATUS:COMPLETED`` or ``PERCENT-COMPLETED:100``).
    Unknown properties are ignored.
    """
    task: dict = {
        "uid": "",
        "title": "",
        "due_date": None,
        "completed": False,
    }
    unfolded: list[str] = []
    for line in raw.replace("\r\n", "\n").split("\n"):
        if line[:1] in (" ", "\t") and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    inside = False
    for line in unfolded:
        stripped = line.strip()
        if stripped == "BEGIN:VTODO":
            inside = True
            continue
        if stripped == "END:VTODO":
            break
        if not inside:
            continue
        match = _LINE_RE.match(stripped)
        if match is None:
            continue
        name, value = match.group(1), match.group(2).strip()
        if name == "UID":
            task["uid"] = value
        elif name == "SUMMARY":
            task["title"] = _unescape_ical(value)
        elif name == "DUE" and value[:8].isdigit():
            task["due_date"] = f"{value[:4]}-{value[4:6]}-{value[6:8]}"
        elif name == "STATUS" and value.upper() == "COMPLETED":
            task["completed"] = True
        elif name in ("PERCENT-COMPLETE", "PERCENT-COMPLETED") and (
            value.isdigit() and int(value) >= 100
        ):
            task["completed"] = True
    return task


def build_vtodo(
    *,
    uid: str,
    title: str,
    due_date: str | None,
    completed: bool,
    dtstamp: str | None = None,
) -> bytes:
    """Build one RFC 5545 VTODO payload for a PUT.

    ``dtstamp`` pins the UTC ``YYYYMMDDTHHMMSSZ`` value (tests use a fixed
    stamp); production passes the current time so every revision carries a
    real timestamp.
    """
    stamp = dtstamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//KindergartenManager//TodoSync//CN",
        f"DTSTAMP:{stamp}",
        "BEGIN:VTODO",
        f"UID:{uid}",
        f"SUMMARY:{_escape_ical(title)}",
    ]
    if due_date:
        lines.append(f"DUE;VALUE=DATE:{due_date.replace('-', '')}")
    if completed:
        lines.append("STATUS:COMPLETED")
        lines.append("PERCENT-COMPLETE:100")
    else:
        lines.append("STATUS:NEEDS-ACTION")
        lines.append("PERCENT-COMPLETE:0")
    lines.append("END:VTODO")
    lines.append("END:VCALENDAR")
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


class NextcloudTasksClient:
    """One connected Nextcloud Tasks account over an injected transport."""

    def __init__(self, transport: Transport, *, base_path: str = ""):
        self.transport = transport
        # ``base_path`` allows installations served under a subpath.
        self._base = (base_path or "").rstrip("/")

    def _path(self, path: str) -> str:
        if self._base and not path.startswith(self._base + "/"):
            return self._base + path
        return path

    def _propfind(
        self, path: str, body: bytes, *, depth: str
    ) -> list:
        status, headers, raw = self.transport.request(
            "PROPFIND", self._path(path), body=body, depth=depth
        )
        if status in (301, 302, 303, 307, 308):
            # The production transport already refuses redirects; the client
            # keeps the same rule so credentials can never travel to a
            # different origin through any transport seam.
            raise TodoSyncError(
                "SYNC_RESPONSE_INVALID",
                "Nextcloud 要求重定向，已拒绝以免把凭据发往其他地址",
            )
        if status in (401, 403):
            raise TodoSyncError(
                "SYNC_AUTH_FAILED", "Nextcloud 用户名或密码不正确，或没有访问权限"
            )
        if status == 404:
            raise TodoSyncError("SYNC_NOT_FOUND", "Nextcloud 资源不存在")
        if status not in (200, 207):
            raise TodoSyncError(
                "SYNC_SERVER_ERROR", f"Nextcloud 返回错误（{status}）"
            )
        return list(_parse_multistatus(raw).findall(f"{{{DAV_NS}}}response"))

    def probe_connection(self) -> dict:
        """Verify the account with one bounded root PROPFIND.

        Returns the current-user principal href when the server answers it;
        ``None`` means the server is reachable and authenticated but did not
        report a principal (the caller then uses the fixed default home-set
        path instead of inventing one).
        """
        responses = self._propfind(DAV_ROOT_PATH, PROP_CURRENT_USER_PRINCIPAL, depth="0")
        principal = None
        for response in responses:
            href = _text_or_none(response.find(f"{{{DAV_NS}}}href"))
            prop = _propstat_value(response, f"{{{DAV_NS}}}current-user-principal")
            if prop is not None:
                principal = _text_or_none(prop.find(f"{{{DAV_NS}}}href"))
            if principal is None and href is not None and href.rstrip("/").endswith(
                "/principals"
            ):
                principal = href
        return {"ok": True, "principal": principal}

    def calendar_home(self, principal: str | None) -> str:
        """The calendar-home-set href (``/remote.php/dav/calendars/<user>/``).

        The principal PROPFIND is the authoritative answer; the fixed
        Nextcloud derivation (``principals/users/<name>`` →
        ``calendars/<name>``) is only a fallback for servers that omit the
        home-set property.  Redirects are never followed, so no fallback
        path ever depends on one.
        """
        if principal:
            try:
                responses = self._propfind(principal, PROP_HOME_SET, depth="0")
                for response in responses:
                    prop = _propstat_value(
                        response, f"{{{CALDAV_NS}}}calendar-home-set"
                    )
                    if prop is not None:
                        href = _text_or_none(prop.find(f"{{{DAV_NS}}}href"))
                        if href:
                            return urllib.parse.urlsplit(href).path or href
            except TodoSyncError as exc:
                if exc.code == "SYNC_NOT_FOUND":
                    raise
                # Fall through to the fixed derivation below.
            marker = "/principals/users/"
            index = principal.find(marker)
            if index >= 0:
                user = principal[index + len(marker):].strip("/")
                if user:
                    return DAV_ROOT_PATH + f"calendars/{user}/"
        raise TodoSyncError(
            "SYNC_RESPONSE_INVALID", "无法确定 Nextcloud 日历根，请稍后重试"
        )

    def list_lists(self, home: str) -> list[TaskListInfo]:
        """One bounded listing of task lists (VTODO-capable calendars)."""
        responses = self._propfind(home, PROP_LISTS, depth="1")
        home_prefix = home.rstrip("/") + "/"
        lists: list[TaskListInfo] = []
        for response in responses:
            href = _text_or_none(response.find(f"{{{DAV_NS}}}href"))
            if not href or not href.rstrip("/").startswith(home_prefix.rstrip("/")):
                # A server answer outside the requested home is ignored.
                continue
            if href.rstrip("/") == home.rstrip("/"):
                continue
            resource_type = _propstat_value(response, f"{{{DAV_NS}}}resourcetype")
            if resource_type is None or resource_type.find(
                f"{{{CALDAV_NS}}}calendar"
            ) is None:
                continue
            display = _text_or_none(
                _propstat_value(response, f"{{{DAV_NS}}}displayname")
            )
            components, state = _propstat_success(
                response, f"{{{CALDAV_NS}}}supported-calendar-component-set"
            )
            if state is False:
                # The server confirmed the component set in a 200 propstat
                # without VTODO: this list can never hold tasks.
                supports_vtodo = False
            elif components is not None:
                supports_vtodo = any(
                    (comp.get("name") or "").upper() == "VTODO"
                    for comp in components.findall(f"{{{CALDAV_NS}}}comp")
                )
            else:
                # Without any component declaration the list stays offered
                # (uncertain); the teacher decides by selecting it.
                supports_vtodo = True
            path = urllib.parse.urlsplit(href).path or href
            lists.append(
                TaskListInfo(
                    href=path,
                    display_name=display or path.rstrip("/").rsplit("/", 1)[-1],
                    supports_vtodo=supports_vtodo,
                )
            )
        lists.sort(key=lambda item: (not item.supports_vtodo, item.display_name))
        return lists[:MAX_TASKS_PER_LIST]

    def list_tasks(self, list_href: str) -> list[RemoteTask]:
        """One bounded listing of the list's VTODOs with their ETags."""
        responses = self._propfind(list_href, PROP_TASKS, depth="1")
        list_prefix = list_href.rstrip("/") + "/"
        tasks: list[RemoteTask] = []
        for response in responses:
            href = _text_or_none(response.find(f"{{{DAV_NS}}}href"))
            if not href or not href.rstrip("/").startswith(list_prefix):
                continue
            if href.rstrip("/") == list_href.rstrip("/"):
                continue
            etag = _text_or_none(_propstat_value(response, f"{{{DAV_NS}}}getetag"))
            data = _text_or_none(
                _propstat_value(response, f"{{{CALDAV_NS}}}calendar-data")
            )
            if etag is None or data is None:
                continue
            parsed = parse_vtodo(data)
            uid = parsed["uid"]
            if not uid:
                # An unfetchable UID cannot be linked stably; it is ignored
                # rather than guessed.
                continue
            path = urllib.parse.urlsplit(href).path or href
            tasks.append(
                RemoteTask(
                    href=path,
                    etag=etag.strip('"'),
                    uid=uid,
                    title=parsed["title"],
                    due_date=parsed["due_date"],
                    completed=bool(parsed["completed"]),
                    raw_calendar=data,
                )
            )
        if len(tasks) >= MAX_TASKS_PER_LIST:
            # A listing capped at the bound may be partial; a partial listing
            # must never look like mass remote deletion.
            raise TodoSyncError(
                "SYNC_LIST_TRUNCATED",
                "任务清单数量超过同步上限，已停止同步以避免误判删除",
            )
        return tasks

    def put_task(
        self, href: str, ical: bytes, *, etag: str | None
    ) -> str | None:
        """Create (``etag=None``) or conditionally edit one VTODO.

        Creation uses ``If-None-Match: *`` so a retry can never overwrite an
        existing task; an edit uses ``If-Match`` so a concurrent remote
        change is a controlled conflict instead of a blind overwrite.
        Returns the new ETag (or ``None`` when the server did not answer
        one).
        """
        headers = {"Content-Type": "text/calendar; charset=utf-8"}
        if etag is None:
            headers["If-None-Match"] = "*"
        else:
            headers["If-Match"] = f'"{etag}"'
        status, response_headers, _body = self.transport.request(
            "PUT", self._path(href), headers=headers, body=ical
        )
        if status in (301, 302, 303, 307, 308):
            raise TodoSyncError(
                "SYNC_RESPONSE_INVALID",
                "Nextcloud 要求重定向，已拒绝以免把凭据发往其他地址",
            )
        if status in (401, 403):
            raise TodoSyncError(
                "SYNC_AUTH_FAILED", "Nextcloud 用户名或密码不正确，或没有访问权限"
            )
        if status in (409,):
            raise TodoSyncError(
                "SYNC_NOT_FOUND", "Nextcloud 清单不存在，请重新选择清单"
            )
        if status == 412:
            raise TodoSyncError(
                "SYNC_PRECONDITION_FAILED",
                "远端任务已被其他设备修改，未覆盖；下次同步会按冲突处理",
            )
        if status not in (200, 201, 204):
            raise TodoSyncError(
                "SYNC_SERVER_ERROR", f"Nextcloud 保存任务失败（{status}）"
            )
        new_etag = response_headers.get("etag")
        return new_etag.strip('"') if new_etag else None


__all__ = [
    "DAV_ROOT_PATH",
    "HttpsTransport",
    "NextcloudTasksClient",
    "RemoteTask",
    "TaskListInfo",
    "TodoSyncError",
    "build_vtodo",
    "parse_vtodo",
]
