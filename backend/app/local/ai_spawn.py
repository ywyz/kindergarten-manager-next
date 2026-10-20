"""Guarded frozen spawn bootstrap (shared by ``d1_main`` and the probe).

PyInstaller replaces ``multiprocessing.freeze_support`` with its own helper that
runs the spawn child bootstrap and then exits. That helper must be called early,
before any application side effect. If the bootstrap itself fails — for example
because the parent died before the bootstrap pipe handle could be duplicated —
a *windowed* (no-console) bootloader can show a modal error dialog, which
leaves an orphan process.

This module converts only that case into a fixed non-zero ``SystemExit``. It is
a strict no-op for the normal parent process, for a source run and for any
non-forking child, so normal exception handling (dispose, worker收口 and the
runtime lock release) is completely unchanged.
"""

from __future__ import annotations

import sys

FROZEN_SPAWN_EXIT_CODE = 7


def is_frozen_spawn_child(argv: list[str] | None = None) -> bool:
    """True only inside a frozen Windows spawn child process."""
    argv = sys.argv if argv is None else argv
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return False
    try:
        from multiprocessing.spawn import is_forking
    except Exception:  # noqa: BLE001 - no multiprocessing support: not a child
        return False
    try:
        return bool(is_forking(argv))
    except Exception:  # noqa: BLE001
        return False


def freeze_support_guarded() -> None:
    """Handle the frozen spawn child bootstrap, or return immediately."""
    if not is_frozen_spawn_child():
        return
    import multiprocessing

    try:
        multiprocessing.freeze_support()
    except SystemExit:
        # The child bootstrap completed and asks the process to exit.
        raise
    except BaseException:  # noqa: BLE001 - recognised spawn-child failure only
        raise SystemExit(FROZEN_SPAWN_EXIT_CODE)


__all__ = ["FROZEN_SPAWN_EXIT_CODE", "freeze_support_guarded", "is_frozen_spawn_child"]
