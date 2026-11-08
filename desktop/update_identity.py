"""D3-U application identity and release-build configuration.

The stable identity is deliberately separate from the daily-plan content
version and the database migration revision. Source runs use a deterministic
UUID build id; release builds replace ``build_identity.json`` with the actual
build id and release configuration.
"""

from __future__ import annotations

import json
import re
import sys
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

APP_ID = "kindergarten-manager-next"
APP_NAME = "KindergartenManager"
CHANNEL = "stable"
APP_VERSION = "0.1.0"
PACKAGE_FORMAT = "pyinstaller-onedir-zip-v1"
PLATFORM = "windows"
ARCH = "x64"
PYTHON_VERSION = "3.14.10"

# Source runs are not updatable. A UUID keeps the type/format identical to a
# release build without pretending this checkout is a released package.
SOURCE_BUILD_ID = str(
    uuid.uuid5(uuid.NAMESPACE_URL, f"{APP_ID}:{APP_VERSION}:source")
)
# ASCII-only full matches: ``\d``/``$`` would admit non-ASCII digits and a
# trailing newline, which are not release versions.
_SEMVER_RE = re.compile(
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
)
_PREVIEW_RE = re.compile(
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"-listening-test\.(0|[1-9][0-9]*)"
)


@dataclass(frozen=True)
class AppIdentity:
    app_id: str
    app_name: str
    channel: str
    version: str
    build_id: str
    package_format: str
    platform: str
    arch: str
    python: str
    database_revision: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def is_preview_version(value: object) -> bool:
    """True only for the first-segment ``X.Y.Z-listening-test.N`` shape."""
    return isinstance(value, str) and _PREVIEW_RE.fullmatch(value) is not None


def version_key(value: object) -> tuple[tuple[int, int, int], int, int]:
    """Sortable stable/preview key without changing SemVer precedence.

    A stable ``X.Y.Z`` sorts above every ``X.Y.Z-listening-test.N`` and below
    the next base version.  Preview numbers compare numerically.
    """
    if not isinstance(value, str):
        raise ValueError("版本必须是字符串")
    match = _SEMVER_RE.fullmatch(value)
    if match is not None:
        return (
            (int(match.group(1)), int(match.group(2)), int(match.group(3))),
            1,
            0,
        )
    match = _PREVIEW_RE.fullmatch(value)
    if match is not None:
        return (
            (int(match.group(1)), int(match.group(2)), int(match.group(3))),
            0,
            int(match.group(4)),
        )
    raise ValueError("版本不是正式版或预览版形状")


def _identity_path() -> Path:
    # Kept lazy to avoid importing desktop path helpers in pure tests.
    import d1_paths

    return d1_paths.package_root() / "build_identity.json"


def _valid_packaged_identity(
    values: dict[str, str], database_revision: str
) -> bool:
    if values.get("app_id") != APP_ID:
        return False
    if values.get("app_name") != APP_NAME:
        return False
    channel = values.get("channel")
    if channel not in ("stable", "preview"):
        return False
    if values.get("package_format") != PACKAGE_FORMAT:
        return False
    if values.get("platform") != PLATFORM or values.get("arch") != ARCH:
        return False
    if values.get("python") != PYTHON_VERSION:
        return False
    try:
        version = values.get("version", "")
        version_key(version)
    except ValueError:
        return False
    if is_preview_version(version) != (channel == "preview"):
        return False
    try:
        if str(uuid.UUID(values.get("build_id", ""))) != values.get(
            "build_id", ""
        ).lower():
            return False
    except (ValueError, AttributeError):
        return False
    revision = values.get("database_revision", "")
    if not revision:
        return False
    if database_revision and revision != database_revision:
        return False
    return True


def load_app_identity(
    database_revision: str = "",
    *,
    path: str | Path | None = None,
    require_packaged: bool | None = None,
) -> AppIdentity | None:
    """Load the packaged identity or return the explicit source identity.

    A frozen package with a missing/damaged ``build_identity.json`` returns
    ``None``; it must never silently become a source identity.
    """
    if require_packaged is None:
        require_packaged = bool(getattr(sys, "frozen", False))
    candidate = Path(path) if path is not None else _identity_path()
    if candidate.is_file():
        try:
            from update_manifest import strict_json_loads

            data = strict_json_loads(candidate.read_bytes(), package=True)
        except Exception:  # noqa: BLE001 - invalid identity is a refusal
            data = None
        if isinstance(data, dict):
            values = {
                "app_id": data.get("app_id"),
                "app_name": data.get("app_name"),
                "channel": data.get("channel"),
                "version": data.get("version"),
                "build_id": data.get("build_id"),
                "package_format": data.get("package_format"),
                "platform": data.get("platform"),
                "arch": data.get("arch"),
                "python": data.get("python"),
                "database_revision": data.get("database_revision"),
            }
            if all(isinstance(value, str) and value for value in values.values()):
                if _valid_packaged_identity(values, database_revision):
                    return AppIdentity(**values)
    if require_packaged:
        return None
    return AppIdentity(
        app_id=APP_ID,
        app_name=APP_NAME,
        channel=CHANNEL,
        version=APP_VERSION,
        build_id=SOURCE_BUILD_ID,
        package_format=PACKAGE_FORMAT,
        platform=PLATFORM,
        arch=ARCH,
        python=PYTHON_VERSION,
        database_revision=database_revision,
    )
