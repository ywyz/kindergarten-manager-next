"""D3-A H2 verification guards (R09).

These are focused tests, not a repeat of the H1/H2 suites:

* the new ``d3-h2-ui``/``d3-h2-verify`` phases require an explicit synthetic
  data root; only the UI phase may receive the controlled provider injection;
* a failed verification step records the first error and aborts the chain;
* the verifier never starts cold restart/Word after a failed first phase, even
  when a restored version is present, and never inspects Word after a failed
  second phase.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import d1_main
import verify_d3_h2_window as verifier


def _args(tmp_path, **overrides):
    values = {
        "selftest": True,
        "phase": "d3-h2-ui",
        "data": str(tmp_path / "data"),
        "synthetic_provider_port": 12345,
        "synthetic_executor_fail": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_d3_h2_ui_requires_explicit_synthetic_data(tmp_path):
    with pytest.raises(RuntimeError, match="必须显式提供 --data"):
        d1_main._validate_synthetic_entry(_args(tmp_path, data=None))


def test_d3_h2_ui_requires_controlled_provider(tmp_path):
    with pytest.raises(RuntimeError, match="受控 provider"):
        d1_main._validate_synthetic_entry(_args(tmp_path, synthetic_provider_port=None))


def test_d3_h2_ui_accepts_explicit_data_and_provider(tmp_path):
    d1_main._validate_synthetic_entry(_args(tmp_path))


def test_d3_h2_verify_refuses_provider_injection(tmp_path):
    with pytest.raises(RuntimeError, match="不接受受控 provider"):
        d1_main._validate_synthetic_entry(
            _args(tmp_path, phase="d3-h2-verify", synthetic_provider_port=12345)
        )


def test_d3_h2_verify_allows_data_without_provider(tmp_path):
    d1_main._validate_synthetic_entry(
        _args(tmp_path, phase="d3-h2-verify", synthetic_provider_port=None)
    )


def test_h2_step_records_first_error_and_stops_dependents():
    summary: dict = {"checks": {}}
    checks: dict = {}
    calls: list[str] = []

    def failing():
        calls.append("failing")
        raise RuntimeError("injected step failure")

    with pytest.raises(d1_main._H2StepFailed):
        d1_main._h2_step(summary, checks, "failing", failing)
        # The exception aborts before this dependent step is reached.
        d1_main._h2_step(summary, checks, "dependent", lambda: calls.append("dependent"))
    assert calls == ["failing"]
    assert checks["failing"] is False
    assert summary["h2_first_error"] == {
        "step": "failing",
        "error": "injected step failure",
    }


def test_verify_chain_stops_when_provider_split_count_not_one():
    calls: list[str] = []

    def first_runner():
        calls.append("first")
        checks = {key: True for key in verifier.REQUIRED_FIRST_CHECKS}
        return 0, {"checks": checks, "h2_restored_version": 6}

    def second_runner(version):
        calls.append("second")
        return 0, {}

    def docx_inspector():
        calls.append("docx")
        return {}

    with pytest.raises(verifier.VerificationAbort, match="provider split count"):
        verifier.run_chain(
            first_runner,
            second_runner,
            docx_inspector,
            provider_split_count=0,
        )
    assert calls == ["first"]


def test_verify_chain_requires_provider_count_fact():
    calls: list[str] = []

    def first_runner():
        calls.append("first")
        checks = {key: True for key in verifier.REQUIRED_FIRST_CHECKS}
        return 0, {"checks": checks, "h2_restored_version": 6}

    def second_runner(version):
        calls.append("second")
        return 0, {}

    with pytest.raises(verifier.VerificationAbort, match="provider split count missing"):
        verifier.run_chain(first_runner, second_runner, lambda: calls.append("docx"))
    assert calls == ["first"]


def test_first_phase_error_wins_over_missing_screenshots():
    first = {
        "checks": {key: True for key in verifier.REQUIRED_FIRST_CHECKS},
        "h2_restored_version": 6,
        "h2_first_error": {"step": "h2_restored", "error": "DOM assertion failed"},
        "screenshots": [],
    }
    with pytest.raises(verifier.VerificationAbort, match="DOM assertion failed"):
        verifier.require_first_phase(
            first,
            0,
            provider_split_count=1,
            required_screenshots={"h2-history-list.bmp"},
        )


def test_verify_chain_stops_before_second_on_first_failure_with_version():
    calls: list[str] = []

    def first_runner():
        calls.append("first")
        return 3, {
            "checks": {"h2_initialized": True},
            "h2_restored_version": 6,
            "provider_split_count": 1,
        }

    def second_runner(version):
        calls.append("second")
        return 0, {}

    def docx_inspector():
        calls.append("docx")
        return {}

    with pytest.raises(verifier.VerificationAbort):
        verifier.run_chain(first_runner, second_runner, docx_inspector)
    assert calls == ["first"]


def test_verify_chain_stops_before_docx_on_second_failure():
    calls: list[str] = []

    def first_runner():
        calls.append("first")
        checks = {key: True for key in verifier.REQUIRED_FIRST_CHECKS}
        return 0, {
            "checks": checks,
            "h2_restored_version": 6,
            "provider_split_count": 1,
        }

    def second_runner(version):
        calls.append("second")
        return 3, {"checks": {"h2_cold_restart_content": False}}

    def docx_inspector():
        calls.append("docx")
        return {}

    with pytest.raises(verifier.VerificationAbort):
        verifier.run_chain(first_runner, second_runner, docx_inspector)
    assert calls == ["first", "second"]


def test_verify_chain_runs_all_on_success():
    calls: list[str] = []

    def first_runner():
        calls.append("first")
        checks = {key: True for key in verifier.REQUIRED_FIRST_CHECKS}
        return 0, {
            "checks": checks,
            "h2_restored_version": 6,
            "provider_split_count": 1,
        }

    def second_runner(version):
        calls.append(f"second:{version}")
        checks = {key: True for key in verifier.REQUIRED_SECOND_CHECKS}
        return 0, {"checks": checks}

    def docx_inspector():
        calls.append("docx")
        return {"ok": True}

    assert verifier.run_chain(first_runner, second_runner, docx_inspector) == {
        "ok": True
    }
    assert calls == ["first", "second:6", "docx"]


def test_cleanup_js_executes_real_injection_without_hanging():
    node = shutil.which("node")
    assert node, "Node is required for the real cleanup JS probe"
    probe = Path(__file__).with_name("h2_cleanup_probe.mjs")
    env = dict(os.environ)
    env["H2_INSTALL_JS"] = d1_main.H2_DELAYED_GET_INSTALL_JS
    env["H2_CLEANUP_JS"] = d1_main.H2_CLEANUP_JS
    result = subprocess.run(
        [node, str(probe)],
        cwd=str(Path(__file__).resolve().parent.parent),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    by_name = {entry["name"]: entry for entry in payload["results"]}
    for name in ("ordinary", "fallback", "cleanup-throws"):
        entry = by_name[name]
        assert entry["settled"] is True
        assert entry["calls"] == 1
        assert entry["released"] is True
        assert entry["fetchRestored"] is True
        assert entry["originalError"] == "DOM assertion failed"
    assert by_name["ordinary"]["cleanupError"] is None
    assert by_name["fallback"]["cleanupError"] is None
    assert by_name["cleanup-throws"]["cleanupError"] == "cleanup boom"


def test_cleanup_h2_fetch_releases_and_restores_even_after_failure():
    class FakeDriver:
        def __init__(self):
            self.calls = []
            self.release_called = False
            self.fetch = "wrapper"

        def eval(self, script):
            self.calls.append(script)
            if "__h2CleanupFetch" in script:
                self.release_called = True
                self.fetch = "real"
            return True

    driver = FakeDriver()
    summary: dict = {}
    d1_main._cleanup_h2_fetch(driver, summary)
    assert driver.release_called is True
    assert driver.fetch == "real"
    assert driver.calls


def test_cleanup_h2_fetch_does_not_replace_original_error():
    class FailingDriver:
        def eval(self, script):
            raise RuntimeError("cleanup transport closed")

    summary: dict = {}
    d1_main._cleanup_h2_fetch(FailingDriver(), summary)
    assert summary["h2_cleanup_errors"] == ["cleanup transport closed"]
