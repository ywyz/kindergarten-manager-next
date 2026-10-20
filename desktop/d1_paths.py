"""D1 resource resolution (source checkout and frozen package).

Only D1-owned locations: the D1 frontend build, the local Alembic resources
that ship inside the package (``alembic-local.ini`` + ``migrations_local``
next to the frozen ``app`` package), the controlled Word template and the
injected synthetic data directory. Never reads legacy configuration or the
D0 probe locations.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

FRONTEND_ENV = "KGM_D1_FRONTEND_DIR"
DATA_DIR_ENV = "KGM_LOCAL_DATA_DIR"
VERIFY_SAVE_DIR_ENV = "KGM_D1_VERIFY_SAVE_DIR"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def package_root() -> Path:
    """Root the frozen resources live under (``_internal`` when frozen)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[1]


def frontend_dist() -> Path:
    env = os.environ.get(FRONTEND_ENV)
    if env:
        return Path(env).resolve()
    if is_frozen():
        return package_root() / "frontend"
    return package_root() / "build" / "desktop-d1" / "frontend"


def frontend_index() -> Path:
    return frontend_dist() / "d1.html"


def verify_save_dir() -> Path | None:
    """Verification-only pre-authorized save directory (selftest driver).

    This is a host-internal environment switch used by the packaged
    verification runs so the native save path can be exercised without a
    human dialog; it is never exposed through the JS API and the product
    always uses the real native Save As dialog.
    """
    value = os.environ.get(VERIFY_SAVE_DIR_ENV)
    if not value:
        return None
    return Path(value).resolve()
