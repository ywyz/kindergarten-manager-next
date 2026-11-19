"""Machine-local WebDAV endpoint configuration and DPAPI password storage.

The teacher explicitly configures an HTTPS WebDAV collection, a user name and
a password.  Only that endpoint is stored here; nothing about it is written
into a backup package, the database or the logs:

- the collection URL and user name live in a small JSON file;
- the password is protected with Windows DPAPI (current user, UI forbidden)
  before it is written, so copying the file to another machine/Windows user
  degrades to "password unavailable, re-enter it" instead of leaking a usable
  credential;
- the store directory and file are created with the same restricted
  current-user DACL used by the AI credential store, and the final file is
  written through a restricted temp file + write-through atomic replace;
- reading never creates or modifies anything.  A missing config is simply
  "not configured"; a corrupt/foreign one is a controlled
  ``WEBDAV_CREDENTIAL_UNAVAILABLE``.

The store deliberately does not depend on a database UUID or profile: first
setup (before any teacher profile exists) must be able to connect and restore.
"""

from __future__ import annotations

import base64
import binascii
import ctypes
import json
import secrets
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from app.local import credentials

STORE_DIR_NAME = "webdav-store"
CONFIG_FILE_NAME = "webdav.json"
CONFIG_VERSION = 1
MAX_URL_LENGTH = 2048
MAX_USERNAME_LENGTH = 256
MAX_PASSWORD_LENGTH = 1024
MAX_CONFIG_BYTES = 64 * 1024
DPAPI_DESCRIPTION = "KindergartenManager WebDAV credential"

MOVE_REPLACE_EXISTING = 0x00000001

_ALLOWED_SCHEME = "https"


class WebdavCredentialError(RuntimeError):
    """Controlled credential-store refusal with a stable public code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class WebdavEndpoint:
    url: str
    username: str
    # Never render the connection password in repr/log/debug output.
    password: str = field(repr=False)


def normalize_collection_url(raw: object) -> str:
    """Validate and normalize an HTTPS WebDAV collection URL.

    Accepted form: ``https://host[:port]/literal/path/``.  The path is treated
    as a literal UTF-8 path (percent-encoded input is refused to avoid
    double-encoding ambiguity), must not contain ``..``/backslash/control
    characters and always ends with exactly one ``/`` so every later request
    is built strictly below this collection.
    """
    if not isinstance(raw, str):
        raise WebdavCredentialError("WEBDAV_URL_INVALID", "WebDAV 地址格式不正确")
    text = raw.strip()
    if not text or len(text) > MAX_URL_LENGTH:
        raise WebdavCredentialError("WEBDAV_URL_INVALID", "WebDAV 地址为空或过长")
    # Reject control characters *before* urlsplit: it silently strips
    # TAB/CR/LF and would otherwise accept a mangled URL.
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise WebdavCredentialError("WEBDAV_URL_INVALID", "WebDAV 地址包含控制字符")
    try:
        parts = urllib.parse.urlsplit(text)
    except ValueError as exc:
        raise WebdavCredentialError("WEBDAV_URL_INVALID", "WebDAV 地址格式不正确") from exc
    if parts.scheme.lower() != _ALLOWED_SCHEME:
        raise WebdavCredentialError(
            "WEBDAV_URL_NOT_HTTPS", "WebDAV 地址必须使用 HTTPS"
        )
    if "@" in parts.netloc:
        raise WebdavCredentialError(
            "WEBDAV_URL_INVALID", "地址中不得包含用户名或密码，请单独填写凭据"
        )
    try:
        host = parts.hostname
        port = parts.port
    except ValueError as exc:
        raise WebdavCredentialError("WEBDAV_URL_INVALID", "WebDAV 端口不正确") from exc
    if not host:
        raise WebdavCredentialError("WEBDAV_URL_INVALID", "WebDAV 地址缺少主机名")
    if port is not None and not 1 <= port <= 65535:
        raise WebdavCredentialError("WEBDAV_URL_INVALID", "WebDAV 端口不正确")
    if parts.query or parts.fragment:
        raise WebdavCredentialError(
            "WEBDAV_URL_INVALID", "WebDAV 地址不得包含查询参数或片段"
        )
    path = parts.path or "/"
    if not path.startswith("/"):
        raise WebdavCredentialError("WEBDAV_URL_INVALID", "WebDAV 路径必须以 / 开头")
    if "%" in path:
        raise WebdavCredentialError(
            "WEBDAV_URL_INVALID", "请使用未编码的路径（不要包含 %）"
        )
    segments: list[str] = []
    for segment in path.split("/"):
        if segment == "":
            continue
        if segment in (".", ".."):
            raise WebdavCredentialError(
                "WEBDAV_URL_INVALID", "WebDAV 路径不得包含 . 或 .."
            )
        if "\\" in segment or segment.endswith((".", " ")):
            raise WebdavCredentialError("WEBDAV_URL_INVALID", "WebDAV 路径不合法")
        if any(ord(char) < 32 or ord(char) == 127 for char in segment):
            raise WebdavCredentialError("WEBDAV_URL_INVALID", "WebDAV 路径不合法")
        segments.append(segment)
    host_text = host.lower()
    if ":" in host_text:
        host_text = f"[{host_text}]"
    netloc = f"{host_text}:{port}" if port is not None else host_text
    normalized_path = "/" + "".join(f"{segment}/" for segment in segments)
    return f"https://{netloc}{normalized_path}"


def _validate_username(raw: object) -> str:
    if not isinstance(raw, str):
        raise WebdavCredentialError("WEBDAV_USERNAME_REQUIRED", "请填写 WebDAV 用户名")
    username = raw.strip()
    if not username or len(username) > MAX_USERNAME_LENGTH:
        raise WebdavCredentialError("WEBDAV_USERNAME_REQUIRED", "请填写 WebDAV 用户名")
    if ":" in username:
        # Basic credentials are ``user:password``; a colon would silently
        # change the user name / password split on the server.
        raise WebdavCredentialError("WEBDAV_USERNAME_REQUIRED", "WebDAV 用户名不能包含冒号")
    if any(ord(char) < 32 or ord(char) == 127 for char in username):
        raise WebdavCredentialError("WEBDAV_USERNAME_REQUIRED", "WebDAV 用户名不合法")
    return username


def _validate_password(raw: object) -> str:
    if not isinstance(raw, str) or not raw:
        raise WebdavCredentialError("WEBDAV_PASSWORD_REQUIRED", "请填写 WebDAV 密码")
    if len(raw) > MAX_PASSWORD_LENGTH:
        raise WebdavCredentialError("WEBDAV_PASSWORD_REQUIRED", "WebDAV 密码过长")
    return raw


# Public validators used by the host to build the connection-test endpoint
# before anything is persisted.
def validate_username(raw: object) -> str:
    return _validate_username(raw)


def validate_password(raw: object) -> str:
    return _validate_password(raw)


class WebdavCredentialStore:
    """Persist one WebDAV endpoint under a restricted local directory.

    ``credential_root`` is the same injected AI credential root used by the
    runtime; the store lives strictly *inside* it (``<credential_root>/webdav-
    store``).  Two runs with different explicit credential roots therefore
    never share a store, and a restore preserves the credential root as a
    whole instead of replacing it.
    """

    def __init__(self, credential_root: str | Path):
        root = Path(credential_root)
        if not root.is_absolute():
            raise WebdavCredentialError(
                "WEBDAV_STORE_INVALID", "WebDAV 凭据根必须是绝对路径"
            )
        self.credential_root = root
        self.store_dir = root / STORE_DIR_NAME
        self.config_path = self.store_dir / CONFIG_FILE_NAME

    # -- reading ---------------------------------------------------------
    def status(self) -> dict:
        """Display-safe state.  Never returns the password; never raises."""
        try:
            data = self._read_config()
        except WebdavCredentialError as exc:
            if exc.code == "WEBDAV_NOT_CONFIGURED":
                return {"configured": False}
            return {
                "configured": True,
                "password_available": False,
                "reason": exc.code,
                "detail": exc.message,
            }
        except Exception:  # noqa: BLE001 - status must stay a value
            return {
                "configured": True,
                "password_available": False,
                "reason": "WEBDAV_CREDENTIAL_UNAVAILABLE",
                "detail": "本机 WebDAV 配置不可读取，请重新填写",
            }
        url = data.get("url")
        username = data.get("username")
        if not isinstance(url, str) or not isinstance(username, str):
            return {
                "configured": True,
                "password_available": False,
                "reason": "WEBDAV_CREDENTIAL_UNAVAILABLE",
                "detail": "本机 WebDAV 配置不完整，请重新填写",
            }
        result = {
            "configured": True,
            "url": url,
            "username": username,
            "password_available": False,
        }
        try:
            self._decode_password(data)
        except Exception:  # noqa: BLE001 - unprotect failure is expected cross-user
            result["reason"] = "WEBDAV_CREDENTIAL_UNAVAILABLE"
            result["detail"] = "本机保存的 WebDAV 密码不可用，请重新输入"
            return result
        result["password_available"] = True
        return result

    def load(self) -> WebdavEndpoint:
        """Return the configured endpoint or a controlled refusal."""
        try:
            data = self._read_config()
        except WebdavCredentialError:
            raise
        url = normalize_collection_url(data.get("url"))
        username = _validate_username(data.get("username"))
        password = self._decode_password(data)
        return WebdavEndpoint(url=url, username=username, password=password)

    def _read_config(self) -> dict:
        path = self.config_path
        if credentials._raw_attributes(path) is None:  # noqa: SLF001 - shared primitive
            raise WebdavCredentialError("WEBDAV_NOT_CONFIGURED", "尚未配置 WebDAV")
        owner_sid = credentials._validate_raw_aliases(path)  # noqa: SLF001
        try:
            root_handle = credentials._open_managed_dir(  # noqa: SLF001
                self.credential_root, owner_sid
            )
            try:
                dir_handle = credentials._open_managed_dir(  # noqa: SLF001
                    self.store_dir, owner_sid
                )
            except BaseException:
                credentials._kernel32.CloseHandle(root_handle)  # noqa: SLF001
                raise
        except Exception as exc:  # noqa: BLE001 - unsafe dir is a refusal
            raise WebdavCredentialError(
                "WEBDAV_CREDENTIAL_UNAVAILABLE", "本机 WebDAV 配置目录不可用"
            ) from exc
        try:
            handle = credentials._open_verified_file(  # noqa: SLF001
                path, owner_sid, "WebDAV 配置"
            )
            try:
                raw = credentials._read_file_bounded(  # noqa: SLF001
                    handle, "WebDAV 配置"
                )
            finally:
                credentials._kernel32.CloseHandle(handle)  # noqa: SLF001
        except Exception as exc:  # noqa: BLE001 - unreadable config is a refusal
            raise WebdavCredentialError(
                "WEBDAV_CREDENTIAL_UNAVAILABLE", "本机 WebDAV 配置不可读取"
            ) from exc
        finally:
            credentials._kernel32.CloseHandle(dir_handle)  # noqa: SLF001
            credentials._kernel32.CloseHandle(root_handle)  # noqa: SLF001
        if len(raw) > MAX_CONFIG_BYTES:
            raise WebdavCredentialError(
                "WEBDAV_CREDENTIAL_UNAVAILABLE", "本机 WebDAV 配置超出上限"
            )
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WebdavCredentialError(
                "WEBDAV_CREDENTIAL_UNAVAILABLE", "本机 WebDAV 配置格式不正确"
            ) from exc
        if not isinstance(data, dict) or data.get("version") != CONFIG_VERSION:
            raise WebdavCredentialError(
                "WEBDAV_CREDENTIAL_UNAVAILABLE", "本机 WebDAV 配置版本不支持"
            )
        return data

    def _decode_password(self, data: dict) -> str:
        encoded = data.get("secret")
        if not isinstance(encoded, str):
            raise WebdavCredentialError(
                "WEBDAV_CREDENTIAL_UNAVAILABLE", "本机保存的 WebDAV 密码不可用"
            )
        try:
            blob = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (binascii.Error, UnicodeEncodeError) as exc:
            raise WebdavCredentialError(
                "WEBDAV_CREDENTIAL_UNAVAILABLE", "本机保存的 WebDAV 密码不可用"
            ) from exc
        try:
            plain = credentials._dpapi_unprotect(blob)  # noqa: SLF001
            return plain.decode("utf-8")
        except Exception as exc:  # noqa: BLE001 - DPAPI refusal crosses machines
            raise WebdavCredentialError(
                "WEBDAV_CREDENTIAL_UNAVAILABLE", "本机保存的 WebDAV 密码不可用"
            ) from exc

    # -- writing ---------------------------------------------------------
    def save(self, *, url: object, username: object, password: object) -> dict:
        """Validate, protect and persist one endpoint, then verify the readback."""
        normalized = normalize_collection_url(url)
        user = _validate_username(username)
        secret = _validate_password(password)
        protected = credentials._dpapi_protect(  # noqa: SLF001
            secret.encode("utf-8"), DPAPI_DESCRIPTION
        )
        payload = json.dumps(
            {
                "version": CONFIG_VERSION,
                "url": normalized,
                "username": user,
                "secret": base64.b64encode(protected).decode("ascii"),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self._write_atomic(payload)
        endpoint = self.load()
        if (
            endpoint.url != normalized
            or endpoint.username != user
            or endpoint.password != secret
        ):
            raise WebdavCredentialError(
                "WEBDAV_CREDENTIAL_WRITE_FAILED", "WebDAV 配置读回校验失败，请重试"
            )
        return self.status()

    def clear(self) -> None:
        """Remove only this module's own config file.

        The raw path is alias-checked and both managed directories are opened
        and verified before the exact file (itself opened and verified on the
        same handle) is removed.  Never deletes a directory or another file.
        """
        path = self.config_path
        if credentials._raw_attributes(path) is None:  # noqa: SLF001
            return
        try:
            owner_sid = credentials._validate_raw_aliases(path)  # noqa: SLF001
            root_handle = credentials._open_managed_dir(  # noqa: SLF001
                self.credential_root, owner_sid
            )
            try:
                dir_handle = credentials._open_managed_dir(  # noqa: SLF001
                    self.store_dir, owner_sid
                )
                try:
                    handle = credentials._open_verified_file(  # noqa: SLF001
                        path, owner_sid, "WebDAV 配置"
                    )
                    credentials._kernel32.CloseHandle(handle)  # noqa: SLF001
                    if not credentials._kernel32.DeleteFileW(str(path)):  # noqa: SLF001
                        raise WebdavCredentialError(
                            "WEBDAV_CREDENTIAL_WRITE_FAILED",
                            "无法清除本机 WebDAV 配置",
                        )
                finally:
                    credentials._kernel32.CloseHandle(dir_handle)  # noqa: SLF001
            finally:
                credentials._kernel32.CloseHandle(root_handle)  # noqa: SLF001
        except WebdavCredentialError:
            raise
        except Exception as exc:  # noqa: BLE001 - unsafe path is a refusal
            raise WebdavCredentialError(
                "WEBDAV_CREDENTIAL_WRITE_FAILED", "无法清除本机 WebDAV 配置"
            ) from exc

    def _write_atomic(self, data: bytes) -> None:
        owner_sid = credentials._validate_raw_aliases(self.config_path)  # noqa: SLF001
        credentials._ensure_unmanaged_parents(self.credential_root)  # noqa: SLF001
        root_handle = credentials._ensure_managed_dir(  # noqa: SLF001
            self.credential_root, owner_sid
        )
        try:
            dir_handle = credentials._ensure_managed_dir(  # noqa: SLF001
                self.store_dir, owner_sid
            )
        except BaseException:
            credentials._kernel32.CloseHandle(root_handle)  # noqa: SLF001
            raise
        tmp_path = self.store_dir / f".tmp-{secrets.token_hex(8)}.json"
        sa = credentials._make_security_attributes(owner_sid)  # noqa: SLF001
        handle = credentials.INVALID_HANDLE_VALUE
        created = False
        moved = False
        try:
            handle = credentials._kernel32.CreateFileW(  # noqa: SLF001
                str(tmp_path),
                credentials.GENERIC_WRITE,
                0,
                ctypes.byref(sa),
                credentials.CREATE_NEW,
                credentials.FILE_ATTRIBUTE_NORMAL,
                None,
            )
            if handle == credentials.INVALID_HANDLE_VALUE:
                raise WebdavCredentialError(
                    "WEBDAV_CREDENTIAL_WRITE_FAILED", "无法创建本机 WebDAV 临时配置"
                )
            created = True
            view = memoryview(data)
            written_total = 0
            while written_total < len(view):
                chunk = bytes(view[written_total:])
                written = ctypes.c_ulong(0)
                if not credentials._kernel32.WriteFile(  # noqa: SLF001
                    handle, chunk, len(chunk), ctypes.byref(written), None
                ):
                    raise WebdavCredentialError(
                        "WEBDAV_CREDENTIAL_WRITE_FAILED", "本机 WebDAV 配置写入失败"
                    )
                if written.value == 0:
                    raise WebdavCredentialError(
                        "WEBDAV_CREDENTIAL_WRITE_FAILED", "本机 WebDAV 配置写入未完成"
                    )
                written_total += written.value
            if not credentials._kernel32.FlushFileBuffers(handle):  # noqa: SLF001
                raise WebdavCredentialError(
                    "WEBDAV_CREDENTIAL_WRITE_FAILED", "本机 WebDAV 配置刷盘失败"
                )
            credentials._kernel32.CloseHandle(handle)  # noqa: SLF001
            handle = credentials.INVALID_HANDLE_VALUE
            check = credentials._open_verified_file(  # noqa: SLF001
                tmp_path, owner_sid, "WebDAV 临时配置"
            )
            credentials._kernel32.CloseHandle(check)  # noqa: SLF001
            if not credentials._kernel32.MoveFileExW(  # noqa: SLF001
                str(tmp_path),
                str(self.config_path),
                credentials.MOVEFILE_WRITE_THROUGH | MOVE_REPLACE_EXISTING,
            ):
                raise WebdavCredentialError(
                    "WEBDAV_CREDENTIAL_WRITE_FAILED", "本机 WebDAV 配置原子替换失败"
                )
            moved = True
        finally:
            if handle != credentials.INVALID_HANDLE_VALUE:
                credentials._kernel32.CloseHandle(handle)  # noqa: SLF001
            credentials._free_sa(sa)  # noqa: SLF001
            credentials._kernel32.CloseHandle(dir_handle)  # noqa: SLF001
            credentials._kernel32.CloseHandle(root_handle)  # noqa: SLF001
            if created and not moved:
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
