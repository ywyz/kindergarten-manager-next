"""R10: drive_window must reject saves whose version does not advance exactly
by one, and any disagreement between the API view and the independent DB read.

These tests execute the real ``drive_window`` flow (not just ``combine_ok``);
only the JS bridge seam (``_await_js`` / ``_evaluate``) and the probe are
stubbed, so the assertion logic under test is the production one.
"""

import sys
import zipfile
from types import ModuleType

import d0_driver

CONTENT_A = "D0 合成内容A T"
CONTENT_B = "D0 合成内容B T"
DOCX_NAME = "D0自动保存_日计划.docx"


class FakeWindow:
    def __init__(self):
        self.destroyed = False

    def get_current_url(self):
        return "http://127.0.0.1:1234/"

    def destroy(self):
        self.destroyed = True


class StubProbe:
    """Independent DB read: returns queued snapshots in call order."""

    def __init__(self, *reads):
        self._reads = list(reads)

    def read(self):
        assert self._reads, "probe.read() called more often than scripted"
        return self._reads.pop(0)


def _install_fake_webview(monkeypatch):
    window = FakeWindow()
    module = ModuleType("webview")
    module.windows = [window]
    monkeypatch.setitem(sys.modules, "webview", module)
    return window


def _install_driver(monkeypatch, *, states, saves, word=None):
    monkeypatch.setattr(
        d0_driver,
        "_evaluate",
        lambda window, expr: True if "PageReady" in expr else None,
    )
    state_iter = iter(states)

    def fake_await(window, expr, timeout=15.0):
        if "collectSession" in expr:
            return {"hasToken": True}
        if "getStateNoHeader" in expr:
            return {"ok": False, "status": 401}
        if "getHealth" in expr:
            return {"status": "ok"}
        if "getStateWithHeader" in expr:
            return next(state_iter)
        if "triggerUiSave" in expr:
            return saves(expr)
        if "triggerWordExportAutosave" in expr:
            return word() if word else {"status": "failed", "message": "skip"}
        return {"__error": f"unexpected expression: {expr[:60]}"}

    monkeypatch.setattr(d0_driver, "_await_js", fake_await)


def _make_docx(tmp_path):
    path = tmp_path / DOCX_NAME
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", "<xml/>")
    return path


def _save_ok(expr):
    return {"messageVisible": True, "failureMessageVisible": False}


# -- first phase ------------------------------------------------------------


def test_first_save_advance_and_api_db_consistency_pass(monkeypatch, tmp_path):
    _install_fake_webview(monkeypatch)
    docx = _make_docx(tmp_path)
    _install_driver(
        monkeypatch,
        states=[
            {"status": "empty"},
            {"status": "ok", "content": CONTENT_A, "version": 1},
        ],
        saves=_save_ok,
        word=lambda: {"status": "saved", "path": str(docx)},
    )
    probe = StubProbe({"status": "ok", "content": CONTENT_A, "version": 1})
    result = d0_driver.drive_window(probe, phase="first", session_tag="T")
    assert result["checks"]["save_a_version_advanced"] is True
    assert result["checks"]["save_a_api_db_consistent"] is True
    assert result["ok"] is True


def test_first_save_version_unchanged_is_failure(monkeypatch):
    _install_fake_webview(monkeypatch)
    # DB already at v5; the "successful" save leaves it at v5 (must fail).
    _install_driver(
        monkeypatch,
        states=[
            {"status": "ok", "content": "old", "version": 5},
            {"status": "ok", "content": CONTENT_A, "version": 5},
        ],
        saves=_save_ok,
    )
    probe = StubProbe({"status": "ok", "content": CONTENT_A, "version": 5})
    result = d0_driver.drive_window(probe, phase="first", session_tag="T")
    assert result["checks"]["save_a_version_advanced"] is False
    assert result["ok"] is False


def test_first_save_wrong_version_is_failure(monkeypatch):
    _install_fake_webview(monkeypatch)
    _install_driver(
        monkeypatch,
        states=[
            {"status": "empty"},
            {"status": "ok", "content": CONTENT_A, "version": 3},
        ],
        saves=_save_ok,
    )
    probe = StubProbe({"status": "ok", "content": CONTENT_A, "version": 3})
    result = d0_driver.drive_window(probe, phase="first", session_tag="T")
    assert result["checks"]["save_a_version_advanced"] is False
    assert result["ok"] is False


def test_first_save_api_db_version_mismatch_is_failure(monkeypatch):
    _install_fake_webview(monkeypatch)
    _install_driver(
        monkeypatch,
        states=[
            {"status": "empty"},
            {"status": "ok", "content": CONTENT_A, "version": 1},
        ],
        saves=_save_ok,
    )
    # API says v1 but the independent DB read still says v0.
    probe = StubProbe({"status": "ok", "content": CONTENT_A, "version": 0})
    result = d0_driver.drive_window(probe, phase="first", session_tag="T")
    assert result["checks"]["save_a_api_db_consistent"] is False
    assert result["ok"] is False


def test_first_save_api_db_content_mismatch_is_failure(monkeypatch):
    _install_fake_webview(monkeypatch)
    _install_driver(
        monkeypatch,
        states=[
            {"status": "empty"},
            {"status": "ok", "content": CONTENT_A, "version": 1},
        ],
        saves=_save_ok,
    )
    probe = StubProbe({"status": "ok", "content": "different", "version": 1})
    result = d0_driver.drive_window(probe, phase="first", session_tag="T")
    assert result["checks"]["save_a_api_db_consistent"] is False
    assert result["ok"] is False


# -- restart phase ----------------------------------------------------------


def _restart_saves(expr):
    if '"simulateFailure": true' in expr:
        return {
            "failureMessageVisible": True,
            "messageVisible": False,
            "inputContent": CONTENT_B,
        }
    return {"messageVisible": True, "failureMessageVisible": False}


def _run_restart(monkeypatch, *, api_version, db_version, db_content=CONTENT_B):
    _install_fake_webview(monkeypatch)
    _install_driver(
        monkeypatch,
        states=[
            {"status": "ok", "content": CONTENT_A, "version": 1},
            {"status": "ok", "content": CONTENT_A, "version": 1},
            {"status": "ok", "content": CONTENT_B, "version": api_version},
        ],
        saves=_restart_saves,
    )
    probe = StubProbe(
        {"status": "ok", "content": CONTENT_A, "version": 1},
        {"status": "ok", "content": db_content, "version": db_version},
    )
    return d0_driver.drive_window(
        probe,
        phase="restart",
        expect_content=CONTENT_A,
        expect_version=1,
        session_tag="T",
    )


def test_restart_retry_advance_and_consistency_pass(monkeypatch):
    result = _run_restart(monkeypatch, api_version=2, db_version=2)
    assert result["checks"]["retry_version_advanced"] is True
    assert result["checks"]["retry_api_db_consistent"] is True
    assert result["ok"] is True


def test_restart_retry_version_unchanged_is_failure(monkeypatch):
    result = _run_restart(monkeypatch, api_version=1, db_version=1)
    assert result["checks"]["retry_version_advanced"] is False
    assert result["ok"] is False


def test_restart_retry_wrong_version_is_failure(monkeypatch):
    result = _run_restart(monkeypatch, api_version=3, db_version=3)
    assert result["checks"]["retry_version_advanced"] is False
    assert result["ok"] is False


def test_restart_retry_api_db_mismatch_is_failure(monkeypatch):
    result = _run_restart(monkeypatch, api_version=2, db_version=1)
    assert result["checks"]["retry_api_db_consistent"] is False
    assert result["ok"] is False
