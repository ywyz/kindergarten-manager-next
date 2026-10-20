"""R1: a windowed process has no console; startup must not depend on it.

PyInstaller ``--windowed`` (and ``pythonw``) set ``sys.stdout``/``sys.stderr``
to ``None``. uvicorn's default formatter then calls ``sys.stdout.isatty()``
and raises ``AttributeError`` during logging configuration. These tests pin
that ``ensure_console_streams`` makes the uvicorn config safe without any
external redirection, and that error reporting degrades without a console.
"""

import sys

import d0_main


def test_configure_logging_survives_missing_console(monkeypatch):
    import uvicorn

    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    opened = d0_main.ensure_console_streams()
    try:
        config = uvicorn.Config(
            lambda: None, host="127.0.0.1", port=0, log_level="warning"
        )
        # Would raise ValueError/AttributeError without writable streams.
        config.configure_logging()
    finally:
        for stream in opened:
            stream.close()
    assert sys.stdout is not None
    assert sys.stderr is not None


def test_ensure_console_streams_keeps_existing_streams(monkeypatch):
    sentinel = sys.stdout
    opened = d0_main.ensure_console_streams()
    assert opened == []
    assert sys.stdout is sentinel


def test_show_error_falls_back_without_console(monkeypatch):
    monkeypatch.setattr(sys, "stderr", None)

    def broken_box(title, message):
        raise RuntimeError("no native message box here")

    # Must not raise even when the native box and stderr are unavailable.
    d0_main.show_error("标题", "消息", box=broken_box)
