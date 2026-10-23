"""D2 W6 G15 host degradation: the real ``d1_main`` executor startup wiring.

Covers:
* ``AiExecutor.start`` assigns its thread handle only after a successful
  ``start()``, so a genuine ``threading.Thread.start`` failure leaves no
  never-started thread to join (``dispose()`` confirms "no worker");
* ``_start_ai_executor`` degrades to "(no executor)" for an import /
  construction / real-start failure, keeping the manual path available;
* an *unconfirmed* worker (``dispose()`` returns False) is never released:
  ``build_runtime`` refuses startup, keeps the executor and does **not** release
  the runtime lock.
"""

from __future__ import annotations

import argparse

import pytest

import d1_main
from app.local.ai_executor import AiExecutor


def _args(tmp_path, **overrides):
    values = {
        "data": str(tmp_path / "data"),
        "frontend": str(tmp_path / "frontend"),
        "selftest": False,
        "phase": "first",
        "synthetic_provider_port": None,
        "synthetic_provider_ca": None,
        "synthetic_provider_ip": "127.0.0.1",
        "synthetic_executor_fail": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_ai_executor_start_failure_leaves_no_thread(tmp_path):
    from app.local.runtime import LocalRuntime

    runtime = LocalRuntime(str(tmp_path / "data"), credential_root=str(tmp_path / "cred"))
    runtime.prepare()
    try:
        executor = AiExecutor(
            runtime, thread_factory=d1_main._failing_start_thread_factory
        )
        with pytest.raises(RuntimeError):
            executor.start()
        # The never-started thread is not recorded, so the teardown can honestly
        # confirm "no worker" instead of joining a thread that never ran.
        assert executor._thread is None
        assert executor.is_runnable() is False
        assert executor.dispose() is True
    finally:
        runtime.dispose()


def test_start_ai_executor_construction_failure_degrades(tmp_path, monkeypatch):
    import app.local.ai_executor as ai_executor_mod
    from app.local.runtime import LocalRuntime

    runtime = LocalRuntime(str(tmp_path / "data"), credential_root=str(tmp_path / "cred"))
    runtime.prepare()
    try:
        executor, reason, unconfirmed = d1_main._start_ai_executor(
            runtime, _args(tmp_path, synthetic_executor_fail="construct")
        )
        assert executor is None
        assert "synthetic executor construction failure" in reason
        assert unconfirmed is False
    finally:
        runtime.dispose()


def test_start_ai_executor_import_failure_degrades(tmp_path, monkeypatch):
    import sys

    from app.local.runtime import LocalRuntime

    runtime = LocalRuntime(str(tmp_path / "data"), credential_root=str(tmp_path / "cred"))
    runtime.prepare()
    try:
        # A failed `from app.local.ai_executor import AiExecutor` must degrade to
        # "no executor" instead of failing the whole application.
        monkeypatch.setitem(sys.modules, "app.local.ai_executor", None)
        executor, reason, unconfirmed = d1_main._start_ai_executor(runtime, _args(tmp_path))
        assert executor is None
        assert unconfirmed is False
        assert "Error" in reason and "ai_executor" in reason
    finally:
        runtime.dispose()


def test_start_ai_executor_real_thread_start_failure_degrades(tmp_path):
    from app.local.runtime import LocalRuntime

    runtime = LocalRuntime(str(tmp_path / "data"), credential_root=str(tmp_path / "cred"))
    runtime.prepare()
    try:
        executor, reason, unconfirmed = d1_main._start_ai_executor(
            runtime, _args(tmp_path, synthetic_executor_fail="start")
        )
        # A genuine Thread.start failure with no worker degrades to "no
        # executor"; it never leaves a half-started executor behind.
        assert executor is None
        assert "threads can only be started once" in reason
        assert unconfirmed is False
    finally:
        runtime.dispose()


def test_start_ai_executor_unconfirmed_worker_kept(tmp_path, monkeypatch):
    import app.local.ai_executor as ai_executor_mod
    from app.local.runtime import LocalRuntime

    runtime = LocalRuntime(str(tmp_path / "data"), credential_root=str(tmp_path / "cred"))
    runtime.prepare()

    class UnconfirmedExecutor:
        def __init__(self, *a, **k):
            self.disposed = 0

        def start(self):
            raise RuntimeError("start failed with a live worker")

        def dispose(self):
            self.disposed += 1
            return False

    monkeypatch.setattr(ai_executor_mod, "AiExecutor", UnconfirmedExecutor)
    try:
        executor, reason, unconfirmed = d1_main._start_ai_executor(runtime, _args(tmp_path))
        assert isinstance(executor, UnconfirmedExecutor)
        assert unconfirmed is True
        # dispose was attempted before reporting the worker as unconfirmed.
        assert executor.disposed == 1
    finally:
        runtime.dispose()


def _spy_runtime(monkeypatch):
    import app.local.runtime as runtime_mod

    calls: list = []

    class Spy:
        def __init__(self, *a, **k):
            calls.append(("init", a, k))

        def prepare(self):
            calls.append(("prepare",))

        def dispose(self):
            calls.append(("dispose",))

    monkeypatch.setattr(runtime_mod, "LocalRuntime", Spy)
    return calls


def test_validate_refuses_missing_data_before_runtime(tmp_path, monkeypatch):
    calls = _spy_runtime(monkeypatch)
    for phase, port in (
        ("g15-noexec", None),
        ("w6-ui-verify", None),
        ("w6-ui", 1234),
        ("w6-resources", 1234),
        ("w5-ui", 1234),
    ):
        with pytest.raises(RuntimeError):
            d1_main.build_runtime(
                _args(
                    tmp_path,
                    selftest=True,
                    phase=phase,
                    data=None,
                    synthetic_provider_port=port,
                )
            )
    # No LocalRuntime was ever constructed: no default teacher root was touched.
    assert calls == []


def test_validate_requires_provider_for_ui_phase(tmp_path, monkeypatch):
    calls = _spy_runtime(monkeypatch)
    with pytest.raises(RuntimeError):
        d1_main.build_runtime(
            _args(tmp_path, selftest=True, phase="w6-ui", synthetic_provider_port=None)
        )
    assert calls == []


def test_validate_refuses_provider_for_verify_phase(tmp_path, monkeypatch):
    calls = _spy_runtime(monkeypatch)
    with pytest.raises(RuntimeError):
        d1_main.build_runtime(
            _args(
                tmp_path,
                selftest=True,
                phase="w6-ui-verify",
                synthetic_provider_port=12345,
            )
        )
    assert calls == []


def test_validate_refuses_interactive_injection(tmp_path, monkeypatch):
    calls = _spy_runtime(monkeypatch)
    with pytest.raises(RuntimeError):
        d1_main.build_runtime(
            _args(tmp_path, selftest=False, phase="first", synthetic_provider_port=12345)
        )
    assert calls == []


def test_resource_bundle_check_requires_exact_r1_r2_r3_rows():
    from app.local.prompt_bundles import PROMPT_BUNDLE_MANIFEST

    def rows(manifest):
        return [
            (
                b["task_type"],
                b["contract_version"],
                b["default_revision"],
                b["bundle_hash"],
            )
            for b in manifest
        ]

    exact = rows(PROMPT_BUNDLE_MANIFEST)
    assert len(exact) == 7
    assert d1_main._bundle_rows_match_manifest(exact, PROMPT_BUNDLE_MANIFEST)
    assert not d1_main._bundle_rows_match_manifest(
        [r for r in exact if r[2] == 1], PROMPT_BUNDLE_MANIFEST
    )
    assert not d1_main._bundle_rows_match_manifest(
        exact[:-1], PROMPT_BUNDLE_MANIFEST
    )
    assert not d1_main._bundle_rows_match_manifest(
        [r for r in exact if not (r[0] == "daily_process_adapt" and r[2] == 3)],
        PROMPT_BUNDLE_MANIFEST,
    )
    unknown = list(exact)
    unknown[0] = (unknown[0][0], unknown[0][1], 99, unknown[0][3])
    assert not d1_main._bundle_rows_match_manifest(unknown, PROMPT_BUNDLE_MANIFEST)
    wrong_hash = list(exact)
    wrong_hash[0] = (*wrong_hash[0][:3], "0" * 64)
    assert not d1_main._bundle_rows_match_manifest(wrong_hash, PROMPT_BUNDLE_MANIFEST)
    assert not d1_main._bundle_rows_match_manifest(
        exact + [exact[0]], PROMPT_BUNDLE_MANIFEST
    )


def test_w6_resources_requires_explicit_data_before_runtime(tmp_path, monkeypatch):
    calls = _spy_runtime(monkeypatch)
    namespace = _args(
        tmp_path,
        selftest=True,
        phase="w6-resources",
        data=None,
        synthetic_provider_port=1234,
    )
    namespace.out = str(tmp_path / "out.json")
    with pytest.raises(RuntimeError):
        d1_main.run_w6_resources(namespace)
    assert calls == []


def test_build_runtime_refuses_and_keeps_lock_on_unconfirmed_worker(
    tmp_path, monkeypatch
):
    import app.local.ai_executor as ai_executor_mod
    import app.local.runtime as runtime_mod

    disposed: list[bool] = []

    class FakeRuntime:
        def __init__(self, data=None, **kwargs):
            self.data_dir = tmp_path
            self.db_path = tmp_path / "fake.db"
            self.credential_root = tmp_path / "cred"
            self.launch_id = None
            self.ai_executor = None

        def prepare(self):
            return None

        def dispose(self):
            disposed.append(True)

        def session(self):  # pragma: no cover - never reached
            raise AssertionError("session() must not be used here")

    class UnconfirmedExecutor:
        def __init__(self, *a, **k):
            pass

        def start(self):
            raise RuntimeError("start failed with a live worker")

        def dispose(self):
            return False

    monkeypatch.setattr(runtime_mod, "LocalRuntime", FakeRuntime)
    monkeypatch.setattr(ai_executor_mod, "AiExecutor", UnconfirmedExecutor)
    with pytest.raises(d1_main._ExecutorUnconfirmed):
        d1_main.build_runtime(_args(tmp_path))
    # The runtime lock is deliberately not released for an unconfirmed worker.
    assert disposed == []
