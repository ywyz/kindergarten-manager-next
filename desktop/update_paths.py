"""Managed update paths, separate from the data and credential roots.

The signed preview installer allows a user-selected application root.  The
application and updater therefore resolve the *registered* install root instead
of assuming one fixed directory.  Raw paths and reparse/safety attributes are
checked before any ``resolve`` so a junction or alias cannot hide a different
root.  A legacy fixed root remains accepted for the existing per-user preview;
an arbitrary copied directory is never trusted.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "KindergartenManager"
APP_DIR_NAME = APP_NAME
UPDATES_DIR_NAME = "updates"
STAGING_DIR_NAME = "staging"
PROGRAMS_DIR_NAME = "Programs"
DEFAULT_INSTALL_ROOT_NAME = "KindergartenManagerSignedPreview"
LEGACY_INSTALL_ROOT_NAMES = ("KindergartenManager",)
UNINSTALL_KEY = (
    r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    r"\{FD74C3C8-0EEB-4C88-9E7D-3F3042CFF823}_is1"
)


def _local_appdata() -> Path:
    value = os.environ.get("LOCALAPPDATA")
    return Path(value) if value else Path.home() / "AppData" / "Local"


def _programs_root() -> Path:
    return _local_appdata() / PROGRAMS_DIR_NAME


def programs_root() -> Path:
    """Public fixed per-user ``Programs`` parent (no trust by itself)."""
    return _programs_root()


def raw_path(value: str | Path) -> Path:
    """Absolute path without resolving links or aliases."""
    return Path(os.path.abspath(os.fspath(value)))


def same_path(left: str | Path, right: str | Path) -> bool:
    """Raw, case-normalized equality; never treats a link target as equal."""
    return os.path.normcase(str(raw_path(left))) == os.path.normcase(
        str(raw_path(right))
    )


def is_safe_existing(path: str | Path) -> bool:
    """True only when the raw path and ancestors are link-free and exist."""
    raw = raw_path(path)
    try:
        from update_fs import ensure_safe_path

        ensure_safe_path(raw)
    except Exception:  # noqa: BLE001 - any attribute/open failure is a refusal
        return False
    return raw.exists()


def _safe_exists(path: Path) -> bool:
    return is_safe_existing(path)


def _has_app(root: Path) -> bool:
    app = raw_path(root) / "app"
    return _safe_exists(app) and _safe_exists(app / f"{APP_NAME}.exe")


def _registered_location() -> Path | None:
    if os.name != "nt":
        return None
    try:
        import winreg
    except ImportError:  # pragma: no cover - non-Windows
        return None
    views = (0,)
    for attribute in ("KEY_WOW64_64KEY", "KEY_WOW64_32KEY"):
        value = getattr(winreg, attribute, 0)
        if value and value not in views:
            views = views + (value,)
    for view in views:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                UNINSTALL_KEY,
                0,
                winreg.KEY_READ | view,
            ) as key:
                value, _kind = winreg.QueryValueEx(key, "InstallLocation")
        except OSError:
            continue
        if not isinstance(value, str):
            continue
        text = value.strip().strip('"')
        if not text:
            continue
        candidate = raw_path(text)
        if not Path(text).is_absolute():
            continue
        if _has_app(candidate):
            return candidate
    return None


def registered_install_root() -> Path | None:
    """Return the HKCU-registered root only when its managed app entry exists."""
    return _registered_location()


def _fixed_roots() -> list[Path]:
    return [
        raw_path(programs_root() / name)
        for name in (DEFAULT_INSTALL_ROOT_NAME, *LEGACY_INSTALL_ROOT_NAMES)
    ]


def resolve_install_root(app_dir: str | Path | None = None) -> Path | None:
    """Resolve the actual install root for this application entry.

    Raw ancestor/self safety is checked first; the raw app directory must equal
    a registered or fixed legacy ``root/app`` before that root is returned.
    Other preview registrations cannot take over the stable legacy path.
    """
    if app_dir is not None:
        app = raw_path(app_dir)
        if not _safe_exists(app):
            return None
    else:
        app = None
    candidates: list[Path] = []
    registered = _registered_location()
    if registered is not None:
        candidates.append(registered)
    candidates.extend(_fixed_roots())
    for root in candidates:
        if not _has_app(root):
            continue
        if app is None:
            return root
        if same_path(root / "app", app):
            return root
    return None


def _fallback_install_root() -> Path:
    registered = _registered_location()
    if registered is not None:
        return registered
    for candidate in _fixed_roots():
        if _has_app(candidate):
            return candidate
    return raw_path(programs_root() / DEFAULT_INSTALL_ROOT_NAME)


def neutral_staging_root() -> Path:
    """A discovery-only staging location that is not tied to another install."""
    return raw_path(_local_appdata() / APP_NAME / UPDATES_DIR_NAME / STAGING_DIR_NAME)


def install_root() -> Path:
    return _fallback_install_root()


def updates_root() -> Path:
    return install_root() / UPDATES_DIR_NAME


def staging_root() -> Path:
    return updates_root() / STAGING_DIR_NAME


def install_app_dir() -> Path:
    return install_root() / "app"


def updater_dir() -> Path:
    """Stable helper location adjacent to, never inside, the app directory."""
    return install_root() / "updater"


def updater_exe() -> Path:
    return updater_dir() / "KindergartenManagerUpdater.exe"


def managed_layout(root: str | Path) -> tuple[Path, Path, Path, Path]:
    """Return ``(install, app, helper, staging)`` for one managed raw root."""
    install = raw_path(root)
    return (
        install,
        install / "app",
        install / "updater" / "KindergartenManagerUpdater.exe",
        install / UPDATES_DIR_NAME / STAGING_DIR_NAME,
    )
