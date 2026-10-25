"""Managed update paths, separate from the data and credential roots."""

from __future__ import annotations

import os
from pathlib import Path

APP_DIR_NAME = "KindergartenManager"
UPDATES_DIR_NAME = "updates"
STAGING_DIR_NAME = "staging"
PROGRAMS_DIR_NAME = "Programs"


def _local_appdata() -> Path:
    value = os.environ.get("LOCALAPPDATA")
    return Path(value) if value else Path.home() / "AppData" / "Local"


def updates_root() -> Path:
    return _local_appdata() / APP_DIR_NAME / UPDATES_DIR_NAME


def staging_root() -> Path:
    return updates_root() / STAGING_DIR_NAME


def install_root() -> Path:
    return _local_appdata() / PROGRAMS_DIR_NAME / APP_DIR_NAME


def install_app_dir() -> Path:
    return install_root() / "app"


def updater_dir() -> Path:
    """Stable helper location adjacent to, never inside, the app directory."""
    return install_root() / "updater"


def updater_exe() -> Path:
    return updater_dir() / "KindergartenManagerUpdater.exe"
