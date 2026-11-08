"""Runtime hook for the explicit online-integration test package.

This file is injected only by ``desktop/build_e14.py`` when
``--online-integration-test`` is present.  It is not part of the ordinary
desktop build and must remain a single fixed filename so the build can include
it in the source freeze.

The hook runs in every frozen process (including multiprocessing spawn
children) before the D1 entrypoint imports the application.  It:

* forces the fixed public test API origin and disables dotenv loading;
* forces the fixed public prompt-trust origin/key/channel;
* makes the default local data and credential roots live under the isolated
  ``%LOCALAPPDATA%\\KGNextOnlineIntegrationTest`` directory;
* never reads, writes or logs a private key or other secret.

The existing explicit ``--data`` and ``--credential-root`` arguments remain
authoritative: ``d1_main`` sets the data environment variable and passes the
credential root directly to ``LocalRuntime`` after this hook has run.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

TEST_ROOT_NAME = "KGNextOnlineIntegrationTest"
APP_DISABLE_DOTENV = "1"
API_ORIGIN = "https://manager-next.ywyz.tech"
PROMPT_SOURCE_URL = "https://manager-next.ywyz.tech"
PROMPT_KEY_ID = "kgm-it-prompt-20261108"
PROMPT_PUBLIC_KEY_B64 = "GOOfY/r1qhE8nxlkEq0OWKuTqyLMiuOSEloTFIAm59U="
PROMPT_CHANNEL = "stable"


def _local_app_data() -> Path:
    value = os.environ.get("LOCALAPPDATA", "").strip()
    if value:
        path = Path(value).expanduser()
        if path.is_absolute():
            return path
    # No usable LOCALAPPDATA: stay inside the user's canonical Local AppData
    # directory and never fall back to the ordinary KindergartenManager root.
    return Path.home() / "AppData" / "Local"


def integration_root() -> Path:
    return _local_app_data() / TEST_ROOT_NAME


def integration_data_dir() -> Path:
    return integration_root() / "data"


def integration_credential_root() -> Path:
    return integration_root() / "credentials"


def _force_environment() -> None:
    os.environ["APP_DISABLE_DOTENV"] = APP_DISABLE_DOTENV
    os.environ["APP_COLLABORATION_API_ORIGIN"] = API_ORIGIN
    os.environ["KGM_LOCAL_DATA_DIR"] = str(integration_data_dir())
    # Keep any incidental D0 path consumer inside the same test root.
    os.environ["KGM_D0_DATA_DIR"] = str(integration_root())
    os.environ.pop("KGM_LOCAL_DB_PATH", None)
    # A frozen package must use its bundled frontend, not an inherited path.
    os.environ.pop("KGM_D1_FRONTEND_DIR", None)


def _force_prompt_trust() -> None:
    import app.local.prompt_package as prompt_package

    prompt_package.PACKAGED_SOURCE_URL = PROMPT_SOURCE_URL
    prompt_package.PACKAGED_KEY_ID = PROMPT_KEY_ID
    prompt_package.PACKAGED_PUBLIC_KEY_B64 = PROMPT_PUBLIC_KEY_B64
    prompt_package.PACKAGED_CHANNEL = PROMPT_CHANNEL


def _force_default_roots() -> None:
    import app.local.runtime as runtime
    import app.local.sqlite as sqlite

    sqlite.default_data_dir = integration_data_dir
    runtime._default_credential_root = integration_credential_root


def _is_spawn_child() -> bool:
    """True only in a frozen multiprocessing spawn child.

    Spawn children inherit the parent's already-forced environment.  Returning
    before importing application modules keeps the child bootstrap minimal and
    preserves an explicit parent ``--data`` environment.
    """
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return False
    try:
        from multiprocessing.spawn import is_forking

        return bool(is_forking(sys.argv))
    except Exception:  # noqa: BLE001 - no multiprocessing support
        return False


def apply() -> None:
    if _is_spawn_child():
        return
    _force_environment()
    _force_prompt_trust()
    _force_default_roots()


apply()
