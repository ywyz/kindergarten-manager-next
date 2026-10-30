"""Fixed GitHub Releases discovery and asset binding for product updates.

The public product source is the official GitHub REST endpoint for the fixed
repository. The API response is discovery only: a release is not installable
until the signed manifest asset verifies with the embedded Ed25519 keys and its
package URL is bound to the same release tag/asset.
"""

from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from update_manifest import (
    MAX_RELEASE_NOTES,
    ManifestError,
    semver,
    strict_json_loads,
)
from update_trust import ReleaseConfigError, ReleaseSource

GITHUB_REPO = "ywyz/kindergarten-manager-next"
GITHUB_API_ORIGIN = "https://api.github.com"
GITHUB_API_PATH = f"/repos/{GITHUB_REPO}/releases/latest"
GITHUB_DOWNLOAD_ORIGIN = "https://github.com"
GITHUB_ASSET_HOST = "release-assets.githubusercontent.com"
MANIFEST_ASSET = "update-manifest-windows-x64.json"
PACKAGE_ASSET = "KindergartenManager-windows-x64.zip"
MAX_API_BYTES = 256 * 1024
MAX_GITHUB_REDIRECTS = 3
MAX_CDN_QUERY = 2048
_TAG_RE = re.compile(r"^v?([0-9]+)\.([0-9]+)\.([0-9]+)$")
# GitHub release assets redirect to a fixed host. The observed production
# shape is ``/github-production-release-asset/<tenant>/<uuid>``; the older
# ``github-production-release-asset-<tenant>`` prefix is retained as a strict
# compatibility shape, never as a wildcard.
_CDN_PATH_RE = re.compile(
    r"^/github-production-release-asset(?:-[0-9a-f]{4,})?/[0-9]+/[0-9a-f-]{8,}$"
)


@dataclass(frozen=True)
class GitHubRelease:
    tag: str
    version: str
    published_at: str
    release_notes: str
    assets: dict[str, str]
    assets_complete: bool
    missing_assets: tuple[str, ...]


def _release_notes(value: object) -> str:
    if not isinstance(value, str):
        return ""
    raw = value.encode("utf-8")
    if len(raw) <= MAX_RELEASE_NOTES:
        return value
    return raw[:MAX_RELEASE_NOTES].decode("utf-8", "ignore")


def parse_latest_release(raw: bytes, current_version: str) -> GitHubRelease:
    """Parse one latest-release response; only formal, newer releases pass."""
    if not isinstance(raw, (bytes, bytearray)) or not raw:
        raise ManifestError("UPDATE_METADATA_INVALID", "GitHub Release 响应为空")
    if len(raw) > MAX_API_BYTES:
        raise ManifestError("UPDATE_METADATA_INVALID", "GitHub Release 响应超过大小上限")
    try:
        data = strict_json_loads(bytes(raw))
    except ManifestError:
        raise
    if not isinstance(data, dict):
        raise ManifestError("UPDATE_METADATA_INVALID", "GitHub Release 响应不是对象")
    draft = data.get("draft")
    prerelease = data.get("prerelease")
    if not isinstance(draft, bool) or not isinstance(prerelease, bool):
        raise ManifestError("UPDATE_METADATA_INVALID", "Release draft/prerelease 必须是布尔值")
    if draft or prerelease:
        raise ManifestError("UPDATE_NO_RELEASE", "最新 Release 不是正式版本")
    tag = data.get("tag_name")
    if not isinstance(tag, str) or not _TAG_RE.match(tag):
        raise ManifestError("UPDATE_METADATA_INVALID", "Release tag 不是三段数值 SemVer")
    version = tag[1:] if tag.startswith("v") else tag
    if semver(version) <= semver(current_version):
        raise ManifestError("UPDATE_NO_NEW_VERSION", "当前已是最新版本")
    assets_raw = data.get("assets")
    if not isinstance(assets_raw, list):
        raise ManifestError("UPDATE_METADATA_INVALID", "Release assets 不合法")
    assets: dict[str, str] = {}
    for item in assets_raw:
        if not isinstance(item, dict):
            raise ManifestError("UPDATE_METADATA_INVALID", "Release asset 项不合法")
        name = item.get("name")
        url = item.get("browser_download_url")
        if not isinstance(name, str) or not isinstance(url, str) or not url:
            raise ManifestError("UPDATE_METADATA_INVALID", "Release asset 名称或地址不合法")
        if name in assets:
            raise ManifestError("UPDATE_ASSETS_DUPLICATE", "Release 含重复资产名")
        assets[name] = url
    missing = tuple(
        name for name in (MANIFEST_ASSET, PACKAGE_ASSET) if name not in assets
    )
    return GitHubRelease(
        tag=tag,
        version=version,
        published_at=str(data.get("published_at") or ""),
        release_notes=_release_notes(data.get("body")),
        assets=assets,
        assets_complete=not missing,
        missing_assets=missing,
    )


def _test_fields(
    *,
    test_only: bool,
    ca_pem: str | None,
    connect_host: str | None,
    connect_port: int | None,
    server_hostname: str | None,
) -> dict:
    return {
        "test_only": test_only,
        "ca_pem": ca_pem,
        "connect_host": connect_host,
        "connect_port": connect_port,
        "server_hostname": server_hostname,
    }


def api_source(
    public_keys: dict[str, bytes] | None = None,
    *,
    test_only: bool = False,
    ca_pem: str | None = None,
    connect_host: str | None = None,
    connect_port: int | None = None,
    server_hostname: str | None = None,
) -> ReleaseSource:
    return ReleaseSource(
        origin=GITHUB_API_ORIGIN,
        metadata_path=GITHUB_API_PATH,
        public_keys=dict(public_keys or {}),
        provider="github",
        github_repo=GITHUB_REPO,
        github_tag=None,
        allowed_redirect_hosts=(),
        **_test_fields(
            test_only=test_only,
            ca_pem=ca_pem,
            connect_host=connect_host,
            connect_port=connect_port,
            server_hostname=server_hostname,
        ),
    )


def load_github_source(path=None) -> ReleaseSource:
    """Load embedded public keys from the fixed package config if present.

    This is the ordinary product entry point. A configuration file can never
    enable the test transport: any test-only field is rejected, even when its
    value is false or null. Test TLS sources are built explicitly in memory by
    the controlled test entry points only.
    """
    import base64
    from pathlib import Path

    if path is None:
        import d1_paths

        path = d1_paths.package_root() / "update_release.json"
    candidate = Path(path)
    keys: dict[str, bytes] = {}
    if candidate.is_file():
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ReleaseConfigError("更新发行配置无法读取") from exc
        if not isinstance(data, dict):
            raise ReleaseConfigError("更新发行配置必须是对象")
        if set(data) & {
            "test_only",
            "ca_pem",
            "connect_host",
            "connect_port",
            "server_hostname",
        }:
            raise ReleaseConfigError("更新发行配置不得包含测试专用字段")
        raw_keys = data.get("public_keys")
        if isinstance(raw_keys, dict):
            for key_id, value in raw_keys.items():
                if not isinstance(value, str):
                    raise ReleaseConfigError("公钥必须是 base64 字符串")
                try:
                    key = base64.b64decode(value.encode("ascii"), validate=True)
                except Exception as exc:  # noqa: BLE001
                    raise ReleaseConfigError("公钥 base64 不合法") from exc
                if len(key) != 32:
                    raise ReleaseConfigError("Ed25519 公钥必须是 32 字节")
                keys[str(key_id)] = key
    return api_source(keys)


def manifest_source(
    release: GitHubRelease,
    public_keys: dict[str, bytes],
    *,
    test_only: bool = False,
    ca_pem: str | None = None,
    connect_host: str | None = None,
    connect_port: int | None = None,
    server_hostname: str | None = None,
) -> ReleaseSource:
    return ReleaseSource(
        origin=GITHUB_DOWNLOAD_ORIGIN,
        metadata_path=(
            f"/{GITHUB_REPO}/releases/download/{release.tag}/{MANIFEST_ASSET}"
        ),
        public_keys=dict(public_keys),
        provider="github",
        github_repo=GITHUB_REPO,
        github_tag=release.tag,
        allowed_redirect_hosts=(GITHUB_ASSET_HOST,),
        **_test_fields(
            test_only=test_only,
            ca_pem=ca_pem,
            connect_host=connect_host,
            connect_port=connect_port,
            server_hostname=server_hostname,
        ),
    )


def expected_package_url(release: GitHubRelease) -> str:
    return f"/{GITHUB_REPO}/releases/download/{release.tag}/{PACKAGE_ASSET}"


def validate_manifest_binding(manifest, release: GitHubRelease) -> None:
    if semver(manifest.version) != semver(release.version):
        raise ManifestError("UPDATE_METADATA_INVALID", "签名清单版本与 Release tag 不一致")
    expected = expected_package_url(release)
    if manifest.package_url != expected:
        raise ManifestError("UPDATE_METADATA_INVALID", "签名包地址未绑定当前 Release 资产")


def validate_github_manifest_for_version(manifest, version: str) -> None:
    """Helper-side binding without trusting a mutable plan-supplied tag.

    The manifest is already signature-verified with the updater's embedded
    key. Its own version must match the plan target, and its signed package
    path must be one of the two fixed tag spellings for that version.
    """
    if semver(manifest.version) != semver(version):
        raise ManifestError("UPDATE_METADATA_INVALID", "签名清单版本与安装目标不一致")
    allowed = {
        f"/{GITHUB_REPO}/releases/download/{tag}/{PACKAGE_ASSET}"
        for tag in (version, f"v{version}")
    }
    if manifest.package_url not in allowed:
        raise ManifestError("UPDATE_METADATA_INVALID", "签名包地址未绑定固定 GitHub Release 资产")


def validate_github_url(source: ReleaseSource, url: str) -> str:
    """Validate one GitHub/API/CDN hop; never accepts arbitrary hosts."""
    if source.provider != "github":
        raise ReleaseConfigError("非 GitHub 来源不能使用 GitHub 跳转")
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.netloc:
        raise ReleaseConfigError("GitHub 更新必须使用 HTTPS")
    if parts.username is not None or parts.password is not None:
        raise ReleaseConfigError("GitHub 更新不得包含 userinfo")
    if parts.port not in (None, 443):
        raise ReleaseConfigError("GitHub 更新只允许 HTTPS 443")
    if parts.fragment:
        raise ReleaseConfigError("GitHub 更新不得包含 fragment")
    host = (parts.hostname or "").lower()
    if "\\" in parts.path or ".." in parts.path.split("/"):
        raise ReleaseConfigError("GitHub 更新路径不合法")
    if host == "api.github.com":
        if parts.path != GITHUB_API_PATH or parts.query:
            raise ReleaseConfigError("GitHub API 路径不是固定 latest 资源")
        return url
    if host == "github.com":
        if source.github_tag is None:
            raise ReleaseConfigError("GitHub 下载缺少固定 tag")
        prefix = f"/{GITHUB_REPO}/releases/download/{source.github_tag}/"
        if not parts.path.startswith(prefix) or parts.query:
            raise ReleaseConfigError("GitHub 下载路径不是固定仓库/tag 资产")
        name = parts.path[len(prefix):]
        if name not in (MANIFEST_ASSET, PACKAGE_ASSET):
            raise ReleaseConfigError("GitHub 下载资产名不在固定清单")
        return url
    if host == GITHUB_ASSET_HOST:
        if GITHUB_ASSET_HOST not in source.allowed_redirect_hosts:
            raise ReleaseConfigError("该 GitHub 来源不允许 CDN 跳转")
        if not _CDN_PATH_RE.match(parts.path):
            raise ReleaseConfigError("GitHub CDN 资产路径不合法")
        if len(parts.query) > MAX_CDN_QUERY:
            raise ReleaseConfigError("GitHub CDN 查询过长")
        return url
    raise ReleaseConfigError("GitHub 更新主机不在固定允许列表")


def public_ipv4_or_ipv6(host: str) -> str:
    """Resolve one host to a public address for the pinned TLS connection."""
    import socket

    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ReleaseConfigError("GitHub 更新主机无法解析") from exc
    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            continue
        return str(ip)
    raise ReleaseConfigError("GitHub 更新主机没有公网地址")


__all__ = [
    "GITHUB_API_ORIGIN",
    "GITHUB_API_PATH",
    "GITHUB_ASSET_HOST",
    "GITHUB_REPO",
    "GitHubRelease",
    "MANIFEST_ASSET",
    "PACKAGE_ASSET",
    "api_source",
    "expected_package_url",
    "load_github_source",
    "manifest_source",
    "parse_latest_release",
    "public_ipv4_or_ipv6",
    "validate_github_manifest_for_version",
    "validate_github_url",
    "validate_manifest_binding",
]
