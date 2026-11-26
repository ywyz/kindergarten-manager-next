"""Machine-local DPAPI storage for the Nextcloud Tasks account password.

The optional todo sync stores the server URL and user name in the local
SQLite settings row (they are ordinary display settings), but the
*password* is protected with Windows DPAPI (current user, UI forbidden)
and written only under ``<credential_root>/todo-sync-store/nextcloud.json``:

- the store directory and file use the same restricted current-user DACL
  primitives as the AI credential store;
- the final file is written through a restricted temp file plus a
  write-through atomic replace, and reading never creates anything;
- a missing file is simply "not connected"; a corrupt/foreign one is a
  controlled ``SYNC_CREDENTIAL_UNAVAILABLE`` refusal;
- the password is never returned to the frontend, never written into
  SQLite, never included in a backup package and never logged.
"""

from __future__ import annotations

import base64
import binascii
import ctypes
import dataclasses
import json
import secrets
import urllib.parse
from dataclasses import field
from pathlib import Path

from app.local import credentials

STORE_DIR_NAME = "todo-sync-store"
CONFIG_FILE_NAME = "nextcloud.json"
CONFIG_VERSION = 1
MAX_URL_LENGTH = 2048
MAX_USERNAME_LENGTH = 256
MAX_PASSWORD_LENGTH = 1024
MAX_CONFIG_BYTES = 64 * 1024
DPAPI_DESCRIPTION = "KindergartenManager Nextcloud Tasks credential"

MOVE_REPLACE_EXISTING = 0x0000000001


class TodoSyncCredentialError(RuntimeError):
    """Controlled credential-store refusal with a stable public code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclasses.dataclass(frozen=True)
class NextcloudAccount:
    url: str
    username: str
    # Never render the connection password in repr/log/debug output.
    password: str = field(repr=False)


def validate_server_url(raw: object) -> str:
    """Validate an HTTPS Nextcloud base URL (no credentials in the URL).

    Accepted form: ``https://host[:port][/optional/base]`` with no userinfo,
    no query, no fragment, no ``..``, and no percent-encoded path.  The
    result keeps a single trailing ``/`` so the fixed DAV path can be
    appended verbatim.
    """
    if not isinstance(raw, str):
        raise TodoSyncCredentialError("SYNC_URL_INVALID", "Nextcloud 地址格式不正确")
    text = raw.strip()
    if not text or len(text) > MAX_URL_LENGTH:
        raise TodoSyncCredentialError("SYNC_URL_INVALID", "Nextcloud 地址为空或过长")
    if "://" not in text:
        raise TodoSyncCredentialError(
            "SYNC_URL_INVALID", "请输入完整的 https:// 开头地址"
        )
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise TodoSyncCredentialError("SYNC_URL_INVALID", "Nextcloud 地址包含控制字符")
    try:
        parts = urllib.parse.urlsplit(text)
    except ValueError as exc:
        raise TodoSyncCredentialError("SYNC_URL_INVALID", "Nextcloud 地址格式不正确") from exc
    if parts.scheme.lower() != "https":
        raise TodoSyncCredentialError("SYNC_URL_NOT_HTTPS", "Nextcloud 地址必须使用 HTTPS")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise TodoSyncCredentialError(
            "SYNC_URL_INVALID", "地址中不得包含用户名或密码，请单独填写凭据"
        )
    if parts.query or parts.fragment:
        raise TodoSyncCredentialError(
            "SYNC_URL_INVALID", "Nextcloud 地址不得包含查询参数或片段"
        )
    host = parts.hostname
    try:
        port = parts.port
    except ValueError as exc:
        raise TodoSyncCredentialError("SYNC_URL_INVALID", "Nextcloud 端口不正确") from exc
    if not host:
        raise TodoSyncCredentialError("SYNC_URL_INVALID", "Nextcloud 地址缺少主机名")
    if port is not None and not 1 <= port <= 65535:
        raise TodoSyncCredentialError("SYNC_URL_INVALID", "Nextcloud 端口不正确")
    # A bare origin (https://host[:port], no path) is a legal Nextcloud
    # root; treat the empty path as "/" instead of refusing it.
    path = parts.path or "/"
    if not path.startswith("/"):
        raise TodoSyncCredentialError("SYNC_URL_INVALID", "Nextcloud 路径必须以 / 开头")
    if "%" in path or ".." in path.split("/") or "\\" in path:
        raise TodoSyncCredentialError("SYNC_URL_INVALID", "Nextcloud 路径不合法")
    for segment in path.split("/"):
        if segment == "":
            continue
        if segment in (".", "..") or any(ord(c) < 32 for c in segment):
            raise TodoSyncCredentialError("SYNC_URL_INVALID", "Nextcloud 路径不合法")
    base = path.rstrip("/")
    host_text = host.lower()
    if ":" in host_text:
        host_text = f"[{host_text}]"
    netloc = f"{host_text}:{port}" if port is not None else host_text
    return f"https://{netloc}{base}/"


def validate_username(raw: object) -> str:
    if not isinstance(raw, str):
        raise TodoSyncCredentialError("SYNC_USERNAME_REQUIRED", "请填写 Nextcloud 用户名")
    username = raw.strip()
    if not username or len(username) > MAX_USERNAME_LENGTH:
        raise TodoSyncCredentialError("SYNC_USERNAME_REQUIRED", "请填写 Nextcloud 用户名")
    if any(ord(char) < 32 or ord(char) == 127 for char in username):
        raise TodoSyncCredentialError("SYNC_USERNAME_REQUIRED", "Nextcloud 用户名不合法")
    return username


def validate_password(raw: object) -> str:
    if not isinstance(raw, str) or not raw:
        raise TodoSyncCredentialError("SYNC_PASSWORD_REQUIRED", "请填写 Nextcloud 应用密码")
    if len(raw) > MAX_PASSWORD_LENGTH:
        raise TodoSyncCredentialError("SYNC_PASSWORD_REQUIRED", "Nextcloud 密码过长")
    return raw


class NextcloudCredentialStore:
    """One DPAPI-protected account under the injected credential root."""

    def __init__(self, credential_root: str | Path):
        root = Path(credential_root)
        if not root.is_absolute():
            raise TodoSyncCredentialError(
                "SYNC_STORE_INVALID", "Nextcloud 凭据根必须是绝对路径"
            )
        self.credential_root = root
        self.store_dir = root / STORE_DIR_NAME
        self.config_path = self.store_dir / CONFIG_FILE_NAME

    # -- reading ---------------------------------------------------------
    def status(self) -> dict:
        """Display-safe state.  Never returns the password; never raises."""
        try:
            data = self._read_config()
        except TodoSyncCredentialError as exc:
            if exc.code == "SYNC_NOT_CONNECTED":
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
                "reason": "SYNC_CREDENTIAL_UNAVAILABLE",
                "detail": "本机保存的 Nextcloud 凭据不可读取，请重新连接",
            }
        url = data.get("url")
        username = data.get("username")
        if not isinstance(url, str) or not isinstance(username, str):
            return {
                "configured": True,
                "password_available": False,
                "reason": "SYNC_CREDENTIAL_UNAVAILABLE",
                "detail": "本机保存的 Nextcloud 凭据不完整，请重新连接",
            }
        result = {
            "configured": True,
            "url": url,
            "username": username,
            "password_available": False,
        }
        try:
            self._decode_password(data)
        except Exception:  # noqa: BLE001 - DPAPI refusal crosses machines
            result["reason"] = "SYNC_CREDENTIAL_UNAVAILABLE"
            result["detail"] = "本机保存的 Nextcloud 密码不可用，请重新输入"
            return result
        result["password_available"] = True
        return result

    def load(self) -> NextcloudAccount:
        try:
            data = self._read_config()
        except TodoSyncCredentialError:
            raise
        url = validate_server_url(data.get("url"))
        username = validate_username(data.get("username"))
        password = self._decode_password(data)
        return NextcloudAccount(url=url, username=username, password=password)

    def identity(self) -> dict | None:
        """The stored account identity (url + username) without the password.

        ``None`` when nothing is stored or the stored row is unusable.  Used
        to bind a settings row to this machine's credential store so a
        restored profile never presents another account's password as its
        own.
        """
        try:
            data = self._read_config()
        except TodoSyncCredentialError:
            return None
        except Exception:  # noqa: BLE001 - identity probe never raises
            return None
        url = data.get("url")
        username = data.get("username")
        if not isinstance(url, str) or not isinstance(username, str):
            return None
        try:
            return {
                "url": validate_server_url(url),
                "username": validate_username(username),
            }
        except TodoSyncCredentialError:
            return None

    def _read_config(self) -> dict:
        path = self.config_path
        if credentials._raw_attributes(path) is None:  # noqa: SLF001
            raise TodoSyncCredentialError("SYNC_NOT_CONNECTED", "尚未连接 Nextcloud")
        owner_sid = credentials._validate_raw_aliases(path)  # noqa: SLF001
        try:
            root_handle = credentials._open_managed_dir(  # noqa: SLF001
                self.credential_root, owner_sid
            )
            try:
                dir_handle = credentials._open_managed_dir(  # noqa: SLF001
                    self.store_dir, owner_sid
                )
            finally:
                credentials._kernel32.CloseHandle(root_handle)  # noqa: SLF001
        except Exception as exc:  # noqa: BLE001 - unsafe dir is a refusal
            raise TodoSyncCredentialError(
                "SYNC_CREDENTIAL_UNAVAILABLE", "本机 Nextcloud 凭据目录不可用"
            ) from exc
        try:
            handle = credentials._open_verified_file(  # noqa: SLF001
                path, owner_sid, "Nextcloud 凭据"
            )
            try:
                raw = credentials._read_file_bounded(  # noqa: SLF001
                    handle, "Nextcloud 凭据"
                )
            finally:
                credentials._kernel32.CloseHandle(handle)  # noqa: SLF001
        except Exception as exc:  # noqa: BLE001 - unreadable config is a refusal
            raise TodoSyncCredentialError(
                "SYNC_CREDENTIAL_UNAVAILABLE", "本机 Nextcloud 凭据不可读取"
            ) from exc
        finally:
            credentials._kernel32.CloseHandle(dir_handle)  # noqa: SLF001
        if len(raw) > MAX_CONFIG_BYTES:
            raise TodoSyncCredentialError(
                "SYNC_CREDENTIAL_UNAVAILABLE", "本机 Nextcloud 凭据超出上限"
            )
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TodoSyncCredentialError(
                "SYNC_CREDENTIAL_UNAVAILABLE", "本机 Nextcloud 凭据格式不正确"
            ) from exc
        if not isinstance(data, dict) or data.get("version") != CONFIG_VERSION:
            raise TodoSyncCredentialError(
                "SYNC_CREDENTIAL_UNAVAILABLE", "本机 Nextcloud 凭据版本不支持"
            )
        return data

    def _decode_password(self, data: dict) -> str:
        encoded = data.get("secret")
        if not isinstance(encoded, str):
            raise TodoSyncCredentialError(
                "SYNC_CREDENTIAL_UNAVAILABLE", "本机保存的 Nextcloud 密码不可用"
            )
        try:
            blob = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (binascii.Error, UnicodeEncodeError) as exc:
            raise TodoSyncCredentialError(
                "SYNC_CREDENTIAL_UNAVAILABLE", "本机保存的 Nextcloud 密码不可用"
            ) from exc
        try:
            plain = credentials._dpapi_unprotect(blob)  # noqa: SLF001
            return plain.decode("utf-8")
        except Exception as exc:  # noqa: BLE001 - DPAPI refusal crosses machines
            raise TodoSyncCredentialError(
                "SYNC_CREDENTIAL_UNAVAILABLE", "本机保存的 Nextcloud 密码不可用"
            ) from exc

    # -- writing ---------------------------------------------------------
    def save(self, *, url: object, username: object, password: object) -> None:
        normalized = validate_server_url(url)
        user = validate_username(username)
        secret = validate_password(password)
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
        account = self.load()
        if (
            account.url != normalized
            or account.username != user
            or account.password != secret
        ):
            raise TodoSyncCredentialError(
                "SYNC_CREDENTIAL_WRITE_FAILED", "Nextcloud 凭据读回校验失败，请重试"
            )

    def clear(self) -> None:
        """Remove only this module's own config file."""
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
                        path, owner_sid, "Nextcloud 凭据"
                    )
                    credentials._kernel32.CloseHandle(handle)  # noqa: SLF001
                    if not credentials._kernel32.DeleteFileW(str(path)):  # noqa: SLF001
                        raise TodoSyncCredentialError(
                            "SYNC_CREDENTIAL_WRITE_FAILED",
                            "无法清除本机 Nextcloud 凭据",
                        )
                finally:
                    credentials._kernel32.CloseHandle(dir_handle)  # noqa: SLF001
            finally:
                credentials._kernel32.CloseHandle(root_handle)  # noqa: SLF001
        except TodoSyncCredentialError:
            raise
        except Exception as exc:  # noqa: BLE001 - unsafe path is a refusal
            raise TodoSyncCredentialError(
                "SYNC_CREDENTIAL_WRITE_FAILED", "无法清除本机 Nextcloud 凭据"
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
        finally:
            credentials._kernel32.CloseHandle(root_handle)  # noqa: SLF001
        tmp_path = self.store_dir / f".tmp-{secrets.token_hex(8)}.json"
        handle = credentials.INVALID_HANDLE_VALUE
        created = False
        moved = False
        try:
            sa = credentials._make_security_attributes(owner_sid)  # noqa: SLF001
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
                    raise TodoSyncCredentialError(
                        "SYNC_CREDENTIAL_WRITE_FAILED",
                        "无法创建本机 Nextcloud 临时凭据",
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
                        raise TodoSyncCredentialError(
                            "SYNC_CREDENTIAL_WRITE_FAILED",
                            "本机 Nextcloud 凭据写入失败",
                        )
                    if written.value == 0:
                        raise TodoSyncCredentialError(
                            "SYNC_CREDENTIAL_WRITE_FAILED",
                            "本机 Nextcloud 凭据写入未完成",
                        )
                    written_total += written.value
                if not credentials._kernel32.FlushFileBuffers(handle):  # noqa: SLF001
                    raise TodoSyncCredentialError(
                        "SYNC_CREDENTIAL_WRITE_FAILED", "本机 Nextcloud 凭据刷盘失败"
                    )
                credentials._kernel32.CloseHandle(handle)  # noqa: SLF001
                handle = credentials.INVALID_HANDLE_VALUE
                check = credentials._open_verified_file(  # noqa: SLF001
                    tmp_path, owner_sid, "Nextcloud 临时凭据"
                )
                credentials._kernel32.CloseHandle(check)  # noqa: SLF001
                if not credentials._kernel32.MoveFileExW(  # noqa: SLF001
                    str(tmp_path),
                    str(self.config_path),
                    credentials.MOVEFILE_WRITE_THROUGH | MOVE_REPLACE_EXISTING,
                ):
                    raise TodoSyncCredentialError(
                        "SYNC_CREDENTIAL_WRITE_FAILED",
                        "本机 Nextcloud 凭据原子替换失败",
                    )
                moved = True
            finally:
                credentials._free_sa(sa)  # noqa: SLF001
        finally:
            if handle != credentials.INVALID_HANDLE_VALUE:
                credentials._kernel32.CloseHandle(handle)  # noqa: SLF001
            credentials._kernel32.CloseHandle(dir_handle)  # noqa: SLF001
            if created and not moved:
                try:
                    tmp_path.unlink()
                except OSError:
                    pass


__all__ = [
    "NextcloudAccount",
    "NextcloudCredentialStore",
    "TodoSyncCredentialError",
    "validate_password",
    "validate_server_url",
    "validate_username",
]
