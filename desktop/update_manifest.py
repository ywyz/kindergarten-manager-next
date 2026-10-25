"""D3-U release metadata and complete onedir ZIP verification.

The outer Ed25519-signed metadata is the source/identity proof. The package's
own manifest is used only to prove the extracted tree is complete and
unmodified; it can never replace the signed metadata.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from update_fs import PathSafetyError, ensure_safe_path, ensure_safe_tree
from update_trust import ReleaseConfigError, ReleaseSource

MAX_METADATA_BYTES = 64 * 1024
MAX_PACKAGE_BYTES = 512 * 1024 * 1024
MAX_PACKAGE_FILES = 20000
MAX_RELEASE_NOTES = 16 * 1024
MAX_PATH_COMPONENT = 200
_SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RESERVED_DEVICE = re.compile(
    r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$", re.IGNORECASE
)
_PAYLOAD_KEYS = {
    "app_id",
    "channel",
    "version",
    "build_id",
    "platform",
    "arch",
    "package_format",
    "package_root",
    "executable",
    "package_url",
    "package_size",
    "package_sha256",
    "database_revision",
    "supported_source_revisions",
    "release_notes",
    "published_at",
}
_REQUIRED_PACKAGE_FILES = {
    "KindergartenManager.exe",
    "_internal/build_identity.json",
    "_internal/frontend/d1.html",
    "_internal/migrations_local/env.py",
    "_internal/app/assets/word_templates/daily_plan.docx",
}
_PACKAGE_MANIFEST = "_internal/package_manifest.json"
_BUILD_IDENTITY = "_internal/build_identity.json"
_PACKAGE_ROOT = "KindergartenManager"
_MAIN_EXECUTABLE = "KindergartenManager.exe"


class ManifestError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class UpdateManifest:
    app_id: str
    channel: str
    version: str
    build_id: str
    platform: str
    arch: str
    package_format: str
    package_root: str
    executable: str
    package_url: str
    package_size: int
    package_sha256: str
    database_revision: str
    supported_source_revisions: tuple[str, ...]
    release_notes: str
    published_at: str
    key_id: str

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "app_id": self.app_id,
            "channel": self.channel,
            "version": self.version,
            "build_id": self.build_id,
            "platform": self.platform,
            "arch": self.arch,
            "package_format": self.package_format,
            "package_size": self.package_size,
            "database_revision": self.database_revision,
            "release_notes": self.release_notes,
            "published_at": self.published_at,
        }


@dataclass(frozen=True)
class VerifiedPackage:
    root: Path
    manifest: UpdateManifest


def canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ManifestError("UPDATE_METADATA_INVALID", "元数据无法规范化") from exc


def _reject_constant(value: str) -> None:
    raise ManifestError("UPDATE_METADATA_INVALID", f"JSON 不允许非有限数：{value}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ManifestError("UPDATE_METADATA_INVALID", "JSON 含重复字段")
        out[key] = value
    return out


def strict_json_loads(raw: bytes, *, package: bool = False) -> Any:
    """Strict JSON for network metadata and package-internal JSON.

    Python's default decoder silently keeps the last duplicate key and accepts
    NaN/Infinity. Both are release-integrity failures here.
    """
    code = "UPDATE_PACKAGE_INVALID" if package else "UPDATE_METADATA_INVALID"
    try:
        text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except ManifestError as exc:
        if exc.code == code:
            raise
        raise ManifestError(code, exc.message) from exc
    except (UnicodeDecodeError, ValueError, TypeError) as exc:
        raise ManifestError(code, "JSON 不合法") from exc


def _is_strict_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def semver(value: object) -> tuple[int, int, int]:
    if not isinstance(value, str):
        raise ManifestError("UPDATE_METADATA_INVALID", "版本必须是字符串")
    match = _SEMVER_RE.match(value)
    if match is None:
        raise ManifestError("UPDATE_METADATA_INVALID", "版本必须是三段数值 SemVer")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def _safe_component(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ManifestError("UPDATE_METADATA_INVALID", f"{label} 不能为空")
    if len(value) > MAX_PATH_COMPONENT:
        raise ManifestError("UPDATE_METADATA_INVALID", f"{label} 过长")
    if value in (".", "..") or any(ch in value for ch in "/\\:*?\"<>|"):
        raise ManifestError("UPDATE_METADATA_INVALID", f"{label} 含非法路径字符")
    if value.endswith((".", " ")):
        raise ManifestError("UPDATE_METADATA_INVALID", f"{label} 不得以点或空格结尾")
    if _RESERVED_DEVICE.match(value):
        raise ManifestError("UPDATE_METADATA_INVALID", f"{label} 是 Windows 设备名")
    return value


def _safe_zip_name(name: str) -> PurePosixPath:
    if not isinstance(name, str) or not name or "\x00" in name:
        raise ManifestError("UPDATE_PACKAGE_INVALID", "ZIP 含空或 NUL 路径")
    if name.startswith(("/", "\\")) or "\\" in name:
        raise ManifestError("UPDATE_PACKAGE_INVALID", "ZIP 含绝对或反斜线路径")
    if re.match(r"^[A-Za-z]:", name):
        raise ManifestError("UPDATE_PACKAGE_INVALID", "ZIP 含盘符路径")
    parts = name.rstrip("/").split("/")
    for part in parts:
        try:
            _safe_component(part, "ZIP 路径段")
        except ManifestError as exc:
            raise ManifestError("UPDATE_PACKAGE_INVALID", exc.message) from exc
    if ".." in parts:
        raise ManifestError("UPDATE_PACKAGE_INVALID", "ZIP 含越界路径")
    return PurePosixPath(*parts)


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0o170000
    return mode == 0o120000


def _decode_signature(value: object) -> bytes:
    if not isinstance(value, str):
        raise ManifestError("UPDATE_METADATA_INVALID", "签名必须是 base64")
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except (ValueError, binascii.Error):
        raise ManifestError("UPDATE_METADATA_INVALID", "签名 base64 不合法") from None


def parse_signed_manifest(
    raw: bytes,
    source: ReleaseSource,
    current_version: str,
    current_database_revision: str,
) -> UpdateManifest:
    if not isinstance(raw, (bytes, bytearray)) or len(raw) == 0:
        raise ManifestError("UPDATE_METADATA_INVALID", "元数据为空")
    if len(raw) > MAX_METADATA_BYTES:
        raise ManifestError("UPDATE_METADATA_INVALID", "元数据超过大小上限")
    try:
        envelope = strict_json_loads(raw)
    except ManifestError:
        raise
    if not isinstance(envelope, dict) or set(envelope) != {
        "schema_version",
        "key_id",
        "payload",
        "signature",
    }:
        raise ManifestError("UPDATE_METADATA_INVALID", "元数据信封字段不合法")
    if not _is_strict_int(envelope.get("schema_version")) or envelope.get("schema_version") != 1:
        raise ManifestError("UPDATE_METADATA_INVALID", "元数据 schema_version 不支持")
    key_id = envelope.get("key_id")
    payload = envelope.get("payload")
    if not isinstance(key_id, str) or not isinstance(payload, dict):
        raise ManifestError("UPDATE_METADATA_INVALID", "元数据信封类型不合法")
    if not isinstance(payload, dict) or set(payload) != _PAYLOAD_KEYS:
        raise ManifestError("UPDATE_METADATA_INVALID", "元数据 payload 字段不合法")
    key = source.public_key(key_id)
    if key is None:
        raise ManifestError("UPDATE_METADATA_UNTRUSTED", "发行元数据签名密钥不受信任")
    signature = _decode_signature(envelope.get("signature"))
    try:
        key.verify(signature, canonical_json(payload))
    except InvalidSignature as exc:
        raise ManifestError("UPDATE_METADATA_UNTRUSTED", "发行元数据签名无效") from exc

    app_id = _safe_component(payload.get("app_id"), "app_id")
    if app_id != "kindergarten-manager-next":
        raise ManifestError("UPDATE_METADATA_INVALID", "应用 ID 不匹配")
    channel = payload.get("channel")
    if channel != source.channel:
        raise ManifestError("UPDATE_METADATA_INVALID", "渠道不匹配")
    version = payload.get("version")
    if semver(version) <= semver(current_version):
        raise ManifestError("UPDATE_NO_NEW_VERSION", "当前已是最新版本")
    build_id = payload.get("build_id")
    try:
        if not isinstance(build_id, str) or str(uuid.UUID(build_id)) != build_id.lower():
            raise ValueError
    except (ValueError, AttributeError):
        raise ManifestError("UPDATE_METADATA_INVALID", "build_id 必须是 UUID") from None
    if payload.get("platform") != "windows" or payload.get("arch") != "x64":
        raise ManifestError("UPDATE_METADATA_INVALID", "平台或架构不匹配")
    if payload.get("package_format") != "pyinstaller-onedir-zip-v1":
        raise ManifestError("UPDATE_METADATA_INVALID", "包格式不匹配")
    package_root = _safe_component(payload.get("package_root"), "package_root")
    executable = _safe_component(payload.get("executable"), "executable")
    if package_root != _PACKAGE_ROOT or executable != _MAIN_EXECUTABLE:
        raise ManifestError("UPDATE_METADATA_INVALID", "包根或主可执行文件不是稳定产品身份")
    if not executable.lower().endswith(".exe"):
        raise ManifestError("UPDATE_METADATA_INVALID", "可执行文件必须是 .exe")
    package_url = payload.get("package_url")
    try:
        source.package_url(package_url if isinstance(package_url, str) else "")
    except ReleaseConfigError as exc:
        raise ManifestError("UPDATE_METADATA_INVALID", str(exc)) from exc
    package_size = payload.get("package_size")
    if (
        not isinstance(package_size, int)
        or isinstance(package_size, bool)
        or package_size <= 0
        or package_size > MAX_PACKAGE_BYTES
    ):
        raise ManifestError("UPDATE_METADATA_INVALID", "包大小不合法")
    package_sha256 = payload.get("package_sha256")
    if not isinstance(package_sha256, str) or not _SHA256_RE.match(package_sha256):
        raise ManifestError("UPDATE_METADATA_INVALID", "包 SHA-256 不合法")
    database_revision = payload.get("database_revision")
    if not isinstance(database_revision, str) or not database_revision:
        raise ManifestError("UPDATE_METADATA_INVALID", "数据库 revision 缺失")
    supported = payload.get("supported_source_revisions")
    if (
        not isinstance(supported, list)
        or not supported
        or not all(isinstance(item, str) and item for item in supported)
        or current_database_revision not in supported
    ):
        raise ManifestError("UPDATE_METADATA_INVALID", "当前数据库 revision 不受目标包支持")
    release_notes = payload.get("release_notes")
    if (
        not isinstance(release_notes, str)
        or len(release_notes.encode("utf-8")) > MAX_RELEASE_NOTES
        or "\x00" in release_notes
    ):
        raise ManifestError("UPDATE_METADATA_INVALID", "更新说明不合法")
    published_at = payload.get("published_at")
    if not isinstance(published_at, str) or not published_at:
        raise ManifestError("UPDATE_METADATA_INVALID", "发布时间缺失")

    return UpdateManifest(
        app_id=app_id,
        channel=channel,
        version=version,
        build_id=build_id.lower(),
        platform="windows",
        arch="x64",
        package_format="pyinstaller-onedir-zip-v1",
        package_root=package_root,
        executable=executable,
        package_url=package_url,
        package_size=package_size,
        package_sha256=package_sha256,
        database_revision=database_revision,
        supported_source_revisions=tuple(supported),
        release_notes=release_notes,
        published_at=published_at,
        key_id=key_id,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_package_manifest(
    root: Path,
    manifest: UpdateManifest,
) -> None:
    manifest_path = root / _PACKAGE_MANIFEST
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ManifestError("UPDATE_PACKAGE_INVALID", "包内清单缺失")
    try:
        data = strict_json_loads(manifest_path.read_bytes(), package=True)
    except (OSError, ManifestError) as exc:
        if isinstance(exc, ManifestError):
            raise
        raise ManifestError("UPDATE_PACKAGE_INVALID", "包内清单无法读取") from exc
    if (
        not isinstance(data, dict)
        or not _is_strict_int(data.get("schema_version"))
        or data.get("schema_version") != 1
    ):
        raise ManifestError("UPDATE_PACKAGE_INVALID", "包内清单 schema 不支持")
    for key, expected in (
        ("app_id", manifest.app_id),
        ("app_name", _PACKAGE_ROOT),
        ("channel", manifest.channel),
        ("version", manifest.version),
        ("build_id", manifest.build_id),
        ("package_format", manifest.package_format),
        ("platform", manifest.platform),
        ("arch", manifest.arch),
        ("database_revision", manifest.database_revision),
    ):
        if data.get(key) != expected:
            raise ManifestError("UPDATE_PACKAGE_INVALID", f"包内清单 {key} 不匹配")
    files = data.get("files")
    if not isinstance(files, list):
        raise ManifestError("UPDATE_PACKAGE_INVALID", "包内清单 files 不合法")
    expected_paths: set[str] = set()
    actual_paths: set[str] = set()
    for item in files:
        if not isinstance(item, dict) or set(item) != {"path", "size", "sha256"}:
            raise ManifestError("UPDATE_PACKAGE_INVALID", "包内清单文件项不合法")
        path_text = item.get("path")
        if not isinstance(path_text, str) or path_text == "package_manifest.json":
            raise ManifestError("UPDATE_PACKAGE_INVALID", "包内清单路径不合法")
        safe = _safe_zip_name(path_text)
        key = safe.as_posix()
        if key in expected_paths:
            raise ManifestError("UPDATE_PACKAGE_INVALID", "包内清单路径重复")
        expected_paths.add(key)
        target = root.joinpath(*safe.parts)
        if target.is_symlink() or not target.is_file():
            raise ManifestError("UPDATE_PACKAGE_INVALID", f"包内文件缺失：{key}")
        size = item.get("size")
        digest = item.get("sha256")
        if (
            not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or target.stat().st_size != size
        ):
            raise ManifestError("UPDATE_PACKAGE_INVALID", f"包内文件大小不符：{key}")
        if not isinstance(digest, str) or not _SHA256_RE.match(digest):
            raise ManifestError("UPDATE_PACKAGE_INVALID", f"包内文件摘要不合法：{key}")
        if _sha256_file(target) != digest:
            raise ManifestError("UPDATE_PACKAGE_INVALID", f"包内文件摘要不符：{key}")
    for path in root.rglob("*"):
        if path.is_file() and path != manifest_path:
            actual_paths.add(path.relative_to(root).as_posix())
    if actual_paths != expected_paths:
        raise ManifestError("UPDATE_PACKAGE_INVALID", "包内文件集合与清单不一致")
    missing_required = _REQUIRED_PACKAGE_FILES - expected_paths
    if missing_required:
        raise ManifestError(
            "UPDATE_PACKAGE_INVALID",
            f"包缺少必需文件：{', '.join(sorted(missing_required))}",
        )
    identity_path = root / _BUILD_IDENTITY
    try:
        identity = strict_json_loads(identity_path.read_bytes(), package=True)
    except (OSError, ManifestError) as exc:
        if isinstance(exc, ManifestError):
            raise
        raise ManifestError("UPDATE_PACKAGE_INVALID", "构建身份无法读取") from exc
    if not isinstance(identity, dict):
        raise ManifestError("UPDATE_PACKAGE_INVALID", "构建身份不合法")
    for key, expected in (
        ("app_id", manifest.app_id),
        ("app_name", _PACKAGE_ROOT),
        ("channel", manifest.channel),
        ("version", manifest.version),
        ("build_id", manifest.build_id),
        ("package_format", manifest.package_format),
        ("platform", manifest.platform),
        ("arch", manifest.arch),
        ("database_revision", manifest.database_revision),
    ):
        if identity.get(key) != expected:
            raise ManifestError("UPDATE_PACKAGE_INVALID", f"构建身份 {key} 不匹配")


def verify_package_zip(
    package_zip: Path,
    manifest: UpdateManifest,
    staging_dir: Path,
) -> VerifiedPackage:
    """Safely extract and verify the complete onedir package."""
    try:
        ensure_safe_path(staging_dir)
        staging_dir.mkdir(parents=True, exist_ok=True)
    except PathSafetyError as exc:
        raise ManifestError("UPDATE_STAGING_UNSAFE", str(exc)) from exc
    except OSError as exc:
        raise ManifestError("UPDATE_STAGING_UNAVAILABLE", "暂存目录不可用") from exc
    root = staging_dir / manifest.package_root
    if root.exists():
        raise ManifestError("UPDATE_PACKAGE_INVALID", "暂存目标已存在")
    try:
        archive = zipfile.ZipFile(package_zip)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ManifestError("UPDATE_PACKAGE_INVALID", "包不是有效 ZIP") from exc
    with archive:
        infos = archive.infolist()
        if not infos or len(infos) > MAX_PACKAGE_FILES:
            raise ManifestError("UPDATE_PACKAGE_INVALID", "ZIP 条目数量不合法")
        total = 0
        seen: set[str] = set()
        folded: set[str] = set()
        for info in infos:
            if info.flag_bits & 0x1:
                raise ManifestError("UPDATE_PACKAGE_INVALID", "ZIP 含加密条目")
            if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise ManifestError("UPDATE_PACKAGE_INVALID", "ZIP 压缩方式不支持")
            safe = _safe_zip_name(info.filename)
            text = safe.as_posix()
            if text in seen:
                raise ManifestError("UPDATE_PACKAGE_INVALID", "ZIP 路径重复")
            seen.add(text)
            if text.casefold() in folded:
                raise ManifestError("UPDATE_PACKAGE_INVALID", "ZIP 路径大小写冲突")
            folded.add(text.casefold())
            parts = safe.parts
            if not parts or parts[0] != manifest.package_root:
                raise ManifestError("UPDATE_PACKAGE_INVALID", "ZIP 顶层目录不匹配")
            if not info.is_dir():
                total += info.file_size
                if total > MAX_PACKAGE_BYTES:
                    raise ManifestError("UPDATE_PACKAGE_INVALID", "ZIP 解压后超过大小上限")
                if info.file_size > 1024 * 1024 and info.compress_size > 0:
                    if info.file_size / info.compress_size > 1000:
                        raise ManifestError("UPDATE_PACKAGE_INVALID", "ZIP 压缩比异常")
            if info.is_dir():
                continue
            if _is_symlink(info):
                raise ManifestError("UPDATE_PACKAGE_INVALID", "ZIP 含符号链接")
            target = staging_dir.joinpath(*parts)
            try:
                ensure_safe_path(target.parent)
                target.resolve().relative_to(staging_dir.resolve())
            except PathSafetyError as exc:
                raise ManifestError("UPDATE_STAGING_UNSAFE", str(exc)) from exc
            except ValueError:
                raise ManifestError("UPDATE_PACKAGE_INVALID", "ZIP 路径越界") from None
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("xb") as destination:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    destination.write(chunk)
        ensure_safe_tree(root)
        _validate_package_manifest(root, manifest)
    return VerifiedPackage(root=root, manifest=manifest)
