"""W6 本机合成 AI 人工验收入口/控制器的无窗口自测。

不使用弱镜像断言：入口 ``main()`` 用 fake webview / build_runtime / service /
runtime 真实执行，覆盖正常清理、服务启动失败、GUI 抛错、stop 抛错仍存活、
worker 未确认时零 dispose 且锁报告 false；控制器坏根在任何 mkdir/clone/
Runtime 前零副作用；provider 用带唯一 ``Authorization`` 哨兵的请求证明日志
不含密钥；hold 中 stop 能及时解锁；真实活动 WAL + 中文/空格/#/% 路径的
backup 克隆。

全部只用 ``tmp_path``/spies；不触碰原教师根、原人工验收根或原包。
"""

from __future__ import annotations

import json
import sqlite3
import sys
import threading
import time
import types
from datetime import date
from pathlib import Path

import pytest

import d2_manual_ai_main as entry
import verify_d2_manual_ai as controller


# ---------------------------------------------------------------------------
# Entry validation
# ---------------------------------------------------------------------------


def _valid_args(tmp_path: Path, monkeypatch):
    root = (tmp_path / "session").resolve()
    data = root / "data"
    data.mkdir(parents=True)
    localappdata = root / "localappdata"
    localappdata.mkdir(parents=True)
    monkeypatch.setenv("LOCALAPPDATA", str(localappdata))
    ca = root / "ca.pem"
    ca.write_text("dummy-ca", encoding="utf-8")
    source_root = (tmp_path / "source").resolve()
    source_data = source_root / "data"
    source_data.mkdir(parents=True)
    (root / entry.MARKER_NAME).write_text(
        json.dumps(
            {
                "manual_root": str(root),
                "data": str(data),
                "source_root": str(source_root),
                "source_data": str(source_data),
            }
        ),
        encoding="utf-8",
    )
    return entry.argparse.Namespace(
        manual_root=str(root),
        data=str(data),
        frontend=None,
        provider_port=12345,
        provider_ca=str(ca),
        provider_ip="127.0.0.1",
        forbid_root=[],
        smoke=False,
        smoke_date="2026-10-19",
        fingerprint_out=None,
    )


def test_validate_accepts_a_marked_session(tmp_path, monkeypatch):
    entry.validate_args(_valid_args(tmp_path, monkeypatch))


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda a: setattr(a, "manual_root", None), "manual-root"),
        (lambda a: setattr(a, "data", None), "--data"),
        (lambda a: setattr(a, "provider_ip", "10.0.0.1"), "127.0.0.1"),
        (lambda a: setattr(a, "provider_port", 0), "端口"),
        (lambda a: setattr(a, "provider_ca", None), "CA"),
    ],
)
def test_validate_rejects_bad_entry_args(tmp_path, monkeypatch, mutate, message):
    args = _valid_args(tmp_path, monkeypatch)
    mutate(args)
    with pytest.raises(RuntimeError) as caught:
        entry.validate_args(args)
    assert message in str(caught.value)


def test_validate_rejects_data_outside_the_fixed_layout(tmp_path, monkeypatch):
    args = _valid_args(tmp_path, monkeypatch)
    other = Path(args.manual_root) / "other"
    other.mkdir()
    args.data = str(other)
    with pytest.raises(RuntimeError):
        entry.validate_args(args)


def test_validate_rejects_missing_marker(tmp_path, monkeypatch):
    args = _valid_args(tmp_path, monkeypatch)
    (Path(args.manual_root) / entry.MARKER_NAME).unlink()
    with pytest.raises(RuntimeError):
        entry.validate_args(args)


def test_validate_rejects_source_root_overlap(tmp_path, monkeypatch):
    args = _valid_args(tmp_path, monkeypatch)
    marker_path = Path(args.manual_root) / entry.MARKER_NAME
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["source_root"] = args.manual_root
    marker["source_data"] = str(Path(args.manual_root) / "data")
    marker_path.write_text(json.dumps(marker), encoding="utf-8")
    with pytest.raises(RuntimeError):
        entry.validate_args(args)


def test_validate_rejects_forbidden_roots(tmp_path, monkeypatch):
    for name in ("manual-acceptance-20261019-190131", "KindergartenManager/data"):
        args = _valid_args(tmp_path / name, monkeypatch)
        args.forbid_root = [str((tmp_path / name).resolve())]
        with pytest.raises(RuntimeError):
            entry.validate_args(args)


def test_validate_requires_isolated_localappdata(tmp_path, monkeypatch):
    args = _valid_args(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "elsewhere"))
    with pytest.raises(RuntimeError):
        entry.validate_args(args)


def test_main_validates_before_any_runtime(tmp_path, monkeypatch):
    called = {"build": 0, "runtime": 0}

    def fake_build(_args):
        called["build"] += 1
        raise AssertionError("build_runtime must not be reached")

    import d1_main
    import app.local.runtime as runtime_mod

    monkeypatch.setattr(d1_main, "build_runtime", fake_build)
    monkeypatch.setattr(
        runtime_mod,
        "LocalRuntime",
        lambda *a, **k: called.__setitem__("runtime", called["runtime"] + 1),
    )
    monkeypatch.setattr(
        entry.sys,
        "argv",
        [
            "d2_manual_ai_main.py",
            "--manual-root",
            str(tmp_path / "nope"),
            "--data",
            str(tmp_path / "nope" / "data"),
        ],
    )
    with pytest.raises(RuntimeError):
        entry.main()
    assert called == {"build": 0, "runtime": 0}


def test_ordinary_entry_still_rejects_synthetic_injection(tmp_path, monkeypatch):
    import d1_main
    import app.local.runtime as runtime_mod

    class Spy:
        def __init__(self, *a, **k):
            raise AssertionError("LocalRuntime must not be constructed")

    monkeypatch.setattr(runtime_mod, "LocalRuntime", Spy)
    namespace = entry.argparse.Namespace(
        data=str(tmp_path / "data"),
        frontend=None,
        selftest=False,
        phase="first",
        synthetic_provider_port=1234,
        synthetic_provider_ca=None,
        synthetic_provider_ip="127.0.0.1",
        synthetic_executor_fail=None,
    )
    with pytest.raises(RuntimeError):
        d1_main.build_runtime(namespace)


# ---------------------------------------------------------------------------
# Entry lifecycle with fake webview / build_runtime / service / runtime
# ---------------------------------------------------------------------------


class _FakeExecutor:
    def __init__(self, confirmed: bool):
        self.confirmed = confirmed
        self.calls = 0

    def dispose(self):
        self.calls += 1
        return self.confirmed


class _FakeRuntime:
    def __init__(self, confirmed: bool = True):
        self.ai_executor = _FakeExecutor(confirmed)
        self.dispose_calls = 0

    def dispose(self):
        self.dispose_calls += 1


class _FakeService:
    def __init__(self, *, ready=True, stop_raises=False, alive_after_stop=False):
        self.ready = ready
        self.error = None
        self.stop_raises = stop_raises
        self.alive_after_stop = alive_after_stop
        self.port = 12345
        self.stop_calls = 0

    def start_and_wait(self):
        return self.ready

    def stop(self):
        self.stop_calls += 1
        if self.stop_raises:
            raise RuntimeError("stop failed")

    def alive(self):
        return self.alive_after_stop


class _FakeWindow:
    def __init__(self):
        self.destroyed = 0

    def destroy(self):
        self.destroyed += 1


def _run_main_lifecycle(tmp_path, monkeypatch, *, service, runtime, webview_start=None, extra_args=None):
    import d1_main

    window = _FakeWindow()

    def fake_build(_args):
        return service, object(), runtime

    def fake_install(_window, _host_api, _runtime):
        return None

    class ForbiddenDriver:
        def __init__(self, *a, **k):
            raise AssertionError("human mode must not create a JsDriver")

    monkeypatch.setattr(d1_main, "build_runtime", fake_build)
    monkeypatch.setattr(d1_main, "_install_close_handlers", fake_install)
    monkeypatch.setattr(d1_main, "JsDriver", ForbiddenDriver)

    calls = {"create_window": [], "start": []}
    fake_webview = types.SimpleNamespace()

    def create_window(*a, **k):
        calls["create_window"].append((a, k))
        return window

    def start(*a, **k):
        calls["start"].append((a, k))
        if webview_start is not None:
            return webview_start(*a, **k)

    fake_webview.create_window = create_window
    fake_webview.start = start
    monkeypatch.setitem(sys.modules, "webview", fake_webview)

    args = _valid_args(tmp_path, monkeypatch)
    argv = [
        "d2_manual_ai_main.py",
        "--manual-root",
        args.manual_root,
        "--data",
        args.data,
        "--provider-port",
        "12345",
        "--provider-ca",
        args.provider_ca,
    ]
    argv.extend(extra_args or [])
    monkeypatch.setattr(entry.sys, "argv", argv)
    code = entry.main()
    report = json.loads(
        (Path(args.manual_root) / "logs" / "entry-exit.json").read_text(encoding="utf-8")
    )
    return code, report, calls, window


def test_human_lifecycle_cleanup_has_no_driver(tmp_path, monkeypatch):
    service = _FakeService()
    runtime = _FakeRuntime()
    code, report, calls, window = _run_main_lifecycle(
        tmp_path, monkeypatch, service=service, runtime=runtime
    )
    assert code == 0
    assert report["ok"] is True
    assert report["worker_exit_confirmed"] is True
    assert report["server_stopped"] is True
    assert report["runtime_lock_released"] is True
    assert runtime.dispose_calls == 1
    # Human mode: no func/destroy/auto task operations.
    assert calls["start"] and "func" not in calls["start"][0][1]
    assert window.destroyed == 0


def test_service_start_failure_reports_and_cleans(tmp_path, monkeypatch):
    service = _FakeService(ready=False)
    service.error = "bind failed"
    runtime = _FakeRuntime()
    code, report, calls, _window = _run_main_lifecycle(
        tmp_path, monkeypatch, service=service, runtime=runtime
    )
    assert code == 2
    assert "bind failed" in (report["error"] or "")
    assert runtime.dispose_calls == 1
    assert service.stop_calls == 1
    assert not calls["create_window"]


def test_gui_exception_cleans_and_fails(tmp_path, monkeypatch):
    service = _FakeService()
    runtime = _FakeRuntime()

    def boom(*a, **k):
        raise RuntimeError("webview crashed")

    code, report, _calls, _window = _run_main_lifecycle(
        tmp_path, monkeypatch, service=service, runtime=runtime, webview_start=boom
    )
    assert code == 2
    assert "webview crashed" in (report["error"] or "")
    assert report["worker_exit_confirmed"] is True
    assert runtime.dispose_calls == 1


def test_stop_error_still_alive_is_not_reported_stopped(tmp_path, monkeypatch):
    service = _FakeService(stop_raises=True, alive_after_stop=True)
    runtime = _FakeRuntime()
    code, report, _calls, _window = _run_main_lifecycle(
        tmp_path, monkeypatch, service=service, runtime=runtime
    )
    assert code == 3
    assert report["server_stopped"] is False
    assert report["runtime_lock_released"] is False
    assert runtime.dispose_calls == 0, "must not release the lock while the server is alive"
    assert report["ok"] is False


def test_executor_unconfirmed_startup_reports_unconfirmed(tmp_path, monkeypatch):
    import d1_main

    executor = _FakeExecutor(confirmed=False)

    def fake_build(_args):
        raise d1_main._ExecutorUnconfirmed(executor)

    monkeypatch.setattr(d1_main, "build_runtime", fake_build)
    args = _valid_args(tmp_path, monkeypatch)
    monkeypatch.setattr(
        entry.sys,
        "argv",
        [
            "d2_manual_ai_main.py",
            "--manual-root",
            args.manual_root,
            "--data",
            args.data,
            "--provider-port",
            "12345",
            "--provider-ca",
            args.provider_ca,
        ],
    )
    code = entry.main()
    report = json.loads(
        (Path(args.manual_root) / "logs" / "entry-exit.json").read_text(encoding="utf-8")
    )
    assert code == 2
    assert report["worker_exit_confirmed"] is False
    assert report["runtime_lock_released"] is False
    assert report["ok"] is False
    assert "unconfirmed" in (report["error"] or "")
    assert executor.calls == 1  # one best-effort teardown, never a release claim


def test_unconfirmed_worker_keeps_runtime_ownership(tmp_path, monkeypatch):
    service = _FakeService()
    runtime = _FakeRuntime(confirmed=False)
    code, report, _calls, _window = _run_main_lifecycle(
        tmp_path, monkeypatch, service=service, runtime=runtime
    )
    assert code == 3
    assert report["worker_exit_confirmed"] is False
    assert runtime.ai_executor.calls == 1
    assert runtime.dispose_calls == 0  # never release with an unconfirmed worker
    assert report["runtime_lock_released"] is False


# ---------------------------------------------------------------------------
# Controller guards: zero side effects before mkdir/clone/runtime
# ---------------------------------------------------------------------------


def test_controller_guard_rejects_before_any_side_effect(tmp_path, monkeypatch):
    protected = tmp_path / "teacher-root"
    protected.mkdir()
    original = tmp_path / "manual-acceptance-original"
    original.mkdir()
    source = tmp_path / "source-data"
    source.mkdir()
    monkeypatch.setattr(controller, "ORIGINAL_MANUAL_ROOT", original)
    import app.local.sqlite as sqlite_mod

    monkeypatch.setattr(sqlite_mod, "default_data_dir", lambda: protected)

    calls = {"clone": 0, "provider": 0, "config": 0}

    monkeypatch.setattr(controller, "clone_sqlite", lambda *a, **k: calls.__setitem__("clone", calls["clone"] + 1))
    monkeypatch.setattr(controller, "ManualProvider", lambda *a, **k: calls.__setitem__("provider", calls["provider"] + 1))
    monkeypatch.setattr(controller, "prepare_ai_config", lambda *a, **k: calls.__setitem__("config", calls["config"] + 1))

    bad_root = protected / "session"
    with pytest.raises(RuntimeError):
        controller.prepare_session(
            bad_root, clone_from_data=source, plan_id="p"
        )
    assert not bad_root.exists(), "must not create anything before the guard"
    assert calls == {"clone": 0, "provider": 0, "config": 0}

    # An existing directory is refused too (never overwrite).
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(RuntimeError):
        controller.prepare_session(existing, clone_from_data=source, plan_id="p")


# ---------------------------------------------------------------------------
# Clone (active WAL, special characters)
# ---------------------------------------------------------------------------


def _make_source_db(tmp_path: Path, name: str = "source") -> tuple[Path, str]:
    from app.local import daily_plan_service, profile_service
    from app.local.normalize import normalize_initialization
    from app.local.runtime import LocalRuntime

    data_dir = tmp_path / name / "data"
    runtime = LocalRuntime(data_dir, credential_root=tmp_path / name / "cred")
    try:
        runtime.prepare()
        session = runtime.session()
        try:
            profile_service.initialize(
                session,
                normalize_initialization(
                    request_id="11111111-1111-4111-8111-111111111111",
                    display_name="验收教师",
                    class_name="验收中一班",
                    grade="middle",
                    term_name="2026 秋季验收",
                    start_date="2026-09-01",
                    end_date="2027-01-31",
                    school_name="验收园所",
                ),
            )
            session.commit()
            plan, _ = daily_plan_service.create_or_open(
                session,
                plan_date=date(2026, 10, 19),
                raw_lesson_plan="原始教案正文",
                adopted_content={
                    "group_activity": {"process": "一、导入\n二、观察", "theme": "W6睡眠验收（已保存）"},
                    "reflection": "反思",
                },
            )
            version = plan["current_content_version"]
            daily_plan_service.save(
                session,
                plan_id=plan["id"],
                expected_content_version=version,
                raw_lesson_plan="原始教案正文",
                adopted_content={
                    "group_activity": {"process": "一、导入\n二、观察\n三、比较", "theme": "W6睡眠验收（已保存）"},
                    "reflection": "反思",
                },
            )
        finally:
            session.close()
    finally:
        runtime.dispose()
    return data_dir / "kindergarten.db", plan["id"]


def test_clone_active_wal_and_special_character_paths(tmp_path):
    source_db, plan_id = _make_source_db(tmp_path, name="源 数据 #%")
    before = controller._sha(source_db)
    # Keep a live connection (committed WAL) open during the backup.
    live = sqlite3.connect(str(source_db), timeout=10)
    live.execute("PRAGMA journal_mode=WAL")
    live.execute("SELECT count(*) FROM local_daily_plans").fetchone()
    try:
        target_dir = tmp_path / "克隆 目标 #%"
        target = target_dir / "kindergarten.db"
        facts = controller.clone_sqlite(source_db, target)
        assert facts["integrity"] == "ok"
        assert facts["foreign_key_violations"] == 0
        assert len(facts["migration_rows"]) == 1
        assert controller._sha(source_db) == before
        plan = controller.read_plan_facts(target, plan_id)
        assert plan["found"] and plan["content_version"] == 2
        assert plan["process"] == "一、导入\n二、观察\n三、比较"
    finally:
        live.close()


def test_clone_refuses_existing_target(tmp_path):
    source_db, _ = _make_source_db(tmp_path)
    target = tmp_path / "clone" / "kindergarten.db"
    controller.clone_sqlite(source_db, target)
    with pytest.raises(RuntimeError):
        controller.clone_sqlite(source_db, target)


def test_prepare_session_writes_marker_with_source_roots(tmp_path, monkeypatch):
    source_db, plan_id = _make_source_db(tmp_path)
    import app.local.sqlite as sqlite_mod

    protected = tmp_path / "teacher"
    protected.mkdir()
    monkeypatch.setattr(sqlite_mod, "default_data_dir", lambda: protected)
    root = tmp_path / "session"
    prepared = controller.prepare_session(
        root, clone_from_data=source_db.parent, plan_id=plan_id
    )
    marker = json.loads((root / ".w6-manual-session.json").read_text(encoding="utf-8"))
    assert marker["manual_root"] == str(root.resolve())
    assert marker["data"] == str((root / "data").resolve())
    assert marker["source_root"] == str(source_db.parent.parent.resolve())
    assert marker["source_data"] == str(source_db.parent.resolve())
    assert prepared["plan"]["found"]


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


def test_provider_routes_three_types_and_logs_no_secret(tmp_path):
    provider = controller.ManualProvider(tmp_path / "session")
    sentinel = "SENTINEL-BEARER-UNIQUE-9f3a"
    body = (
        b'{"model":"x","content":"raw_lesson_plan","marker":"' + sentinel.encode() + b'"}'
    )
    split = (
        b"POST /v1/chat/completions HTTP/1.1\r\n"
        b"Host: api.example.com\r\n"
        b"Authorization: Bearer " + sentinel.encode() + b"\r\n"
        b"Content-Type: application/json\r\n"
        b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
    )
    adapt = b'{"model":"x","content":"process_source"}'
    other = b'{"model":"x","content":"calendar_context"}'
    try:
        assert provider._reply(split)
        assert provider._reply(adapt)
        assert provider._reply(other)
        assert provider.counts() == {"split": 1, "adapt": 1, "other": 1}
        log = (tmp_path / "session" / "logs" / "provider.jsonl").read_text(encoding="utf-8")
        assert sentinel not in log, "the provider log must never contain the secret"
        assert '"has_authorization": true' in log
    finally:
        provider.stop()


def test_provider_header_detection_is_real_http_only(tmp_path):
    provider = controller.ManualProvider(tmp_path / "session")
    try:
        # A JSON field named Authorization is NOT a real header and must not be
        # recorded as one (only the diagnostic flag; no value is ever logged).
        provider._reply(b'{"headers":{"Authorization":"Bearer x"},"content":"raw_lesson_plan"}')
        log = (tmp_path / "session" / "logs" / "provider.jsonl").read_text(encoding="utf-8")
        assert '"has_authorization": false' in log
    finally:
        provider.stop()


def test_provider_hold_releases_on_control_and_on_stop(tmp_path):
    provider = controller.ManualProvider(tmp_path / "session")
    try:
        control = tmp_path / "session" / "control" / "next.txt"
        control.write_text("hold", encoding="utf-8")
        done = threading.Event()

        def call():
            provider._reply(b'{"content":"raw_lesson_plan"}')
            done.set()

        worker = threading.Thread(target=call, daemon=True)
        worker.start()
        time.sleep(0.4)
        assert not done.is_set(), "hold should block the request"

        started = time.monotonic()
        provider.stop()
        assert done.wait(3.0), "stop must promptly unblock the held handler"
        assert time.monotonic() - started < 3.0
        assert provider.closed() is True
    finally:
        provider.stop()


def test_classify_request_markers():
    assert controller.classify_request(b"process_source") == "adapt"
    assert controller.classify_request(b"calendar_context") == "other"
    assert controller.classify_request(b"raw_lesson_plan") == "split"


def test_archive_module_scope_covers_host_and_same_origin(tmp_path):
    exe = controller.ORIGINAL_PACKAGE / "KGNext-D2Verify.exe"
    if not exe.is_file():
        pytest.skip("原验证包不存在")
    modules = controller._archive_module_fingerprints(exe, tmp_path)
    for name in (
        "app.local.export_service",
        "app.local.ai_executor",
        "d0_main",
        "d0_paths",
        "d1_host_api",
        "d1_paths",
        "d2_same_origin",
    ):
        assert name in modules, name
        assert modules[name], name
    assert len(modules) >= 50
