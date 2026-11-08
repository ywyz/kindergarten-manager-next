"""Deployment-only bootstrap for the first collaboration administrator.

The password is read from standard input/protected configuration, never from a
CLI argument and never printed.  Example::

    python -m app.collaboration.admin_bootstrap

The prompt reads the administrator username first, then the password.  In a
non-interactive deployment the two values may be supplied as the first two
stdin lines, or the username via ``KGM_COLLAB_ADMIN_USERNAME`` and the password
via a protected ``KGM_COLLAB_ADMIN_PASSWORD_FILE`` (first line, newline
trimmed).  No production deployment is performed by this module.
"""

from __future__ import annotations

import getpass
import json
import os
import sys

from .admin_service import bootstrap_admin


def _read_username() -> str:
    username = os.environ.get("KGM_COLLAB_ADMIN_USERNAME", "").strip()
    if username:
        return username
    return input("administrator username: ")


def _read_password() -> str:
    path = os.environ.get("KGM_COLLAB_ADMIN_PASSWORD_FILE", "").strip()
    if path:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.readline().rstrip("\r\n")
    if sys.stdin.isatty():
        return getpass.getpass("administrator password: ")
    return sys.stdin.readline().rstrip("\r\n")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args:
        print(
            "bootstrap accepts no command-line arguments; supply credentials "
            "through stdin or protected configuration",
            file=sys.stderr,
        )
        return 2
    try:
        username = _read_username()
        password = _read_password()
        from .config import CollaborationSettings

        settings = CollaborationSettings.from_env(require_preview_secret=False)
        from .db import create_collaboration_engine
        from sqlalchemy.orm import sessionmaker

        engine = create_collaboration_engine(settings)
        factory = sessionmaker(
            bind=engine,
            autoflush=False,
            expire_on_commit=False,
        )
        with factory() as session:
            row = bootstrap_admin(session, username, password)
            print(
                json.dumps(
                    {"admin_id": str(row.id), "username": row.username},
                    ensure_ascii=False,
                )
            )
        return 0
    except Exception as exc:  # noqa: BLE001 - never echo a password or SQL text
        print(f"administrator bootstrap failed: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
