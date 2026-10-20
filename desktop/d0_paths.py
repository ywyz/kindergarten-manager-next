"""D0 path resolution shared by desktop probe modules (dev and packaged).

Two explicit runtime states:
- dev: running from the repository with a real ``desktop/.venv``; resources
  live in the repository tree.
- packaged: PyInstaller onedir bundle; resources live in
  ``<_internal>/desktop_resources/`` (added via ``--add-data``), and data
  always lives in a user-local data directory, never in the unpack area.

The probe never resolves paths from the CWD, so running from any working
directory behaves identically (D0-7).
"""

import os
import sys
from pathlib import Path

# ``d0_paths.py`` lives in <repo>/desktop/, whatever the launch cwd is.
APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parent
BACKEND_ROOT = REPO_ROOT / "backend"

DEFAULT_DATA_VENDOR_DIRNAME = "KindergartenManager-D0"
PACKAGE_DATA_DIRNAME = "desktop_resources"


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def bundle_base() -> Path:
    """Base directory of container resources for the current run mode."""
    if is_frozen():
        # PyInstaller onedir: bundled resources follow the exe's _internal dir.
        return Path(getattr(sys, "_MEIPASS"))
    return REPO_ROOT


def frontend_dist() -> Path:
    if is_frozen():
        return bundle_base() / PACKAGE_DATA_DIRNAME / "frontend"
    override = os.environ.get("KGM_D0_FRONTEND_DIR")
    if override:
        return Path(override)
    return REPO_ROOT / "build" / "desktop-d0" / "frontend"


def daily_word_template_path() -> Path:
    """Controlled daily template (repo asset; same bytes in the package)."""
    if is_frozen():
        return (
            bundle_base()
            / PACKAGE_DATA_DIRNAME
            / "word_templates"
            / "daily_plan.docx"
        )
    override = os.environ.get("KGM_D0_TEMPLATE_DIR")
    if override:
        return Path(override) / "daily_plan.docx"
    return BACKEND_ROOT / "app" / "assets" / "word_templates" / "daily_plan.docx"


def data_dir() -> Path:
    """Independent local data directory (D0-2: never the unpack temp dir)."""
    override = os.environ.get("KGM_D0_DATA_DIR")
    if override:
        base = Path(override)
    else:
        base = (
            Path(os.environ.get("LOCALAPPDATA") or (REPO_ROOT / "build"))
            / DEFAULT_DATA_VENDOR_DIRNAME
        )
    return base / "data"


def autosave_dir() -> Path:
    """Directory for driver-automated Word saves (verification only)."""
    override = os.environ.get("KGM_D0_AUTOSAVE_DIR")
    if override:
        return Path(override)
    return (
        Path(os.environ.get("LOCALAPPDATA") or (REPO_ROOT / "build"))
        / DEFAULT_DATA_VENDOR_DIRNAME
        / "autosave"
    )
