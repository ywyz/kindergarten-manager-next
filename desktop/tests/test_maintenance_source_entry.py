"""B3 source-window entry guards: synthetic roots and explicit config only."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import maintenance_source_verify as source


def _config(root: Path, **overrides):
    data = {
        "root": str(root),
        "source_data_dir": str(root / "source" / "data"),
        "source_credential_root": str(root / "source" / "cred"),
        "evidence_dir": str(root / "evidence"),
        "source_package": str(root / "old.kgmbackup"),
        "target_backup": str(root / "target.kgmbackup"),
        "capacity_photo_count": 3,
        "timeout": 30,
    }
    data.update(overrides)
    return data


def _args(tmp_path: Path, config: dict):
    return SimpleNamespace(
        selftest=True,
        phase="b3-source-window",
        data=str(tmp_path / "b3" / "target" / "data"),
        credential_root=str(tmp_path / "b3" / "target" / "cred"),
        b3_config=str(tmp_path / "b3" / "config.json"),
        frontend=None,
        out=None,
    )


def test_b3_config_is_validated_before_runtime(tmp_path):
    root = tmp_path / "b3"
    root.mkdir()
    config = _config(root)
    args = _args(tmp_path, config)
    Path(args.b3_config).write_text(json.dumps(config), encoding="utf-8")
    resolved = source._validate_config(args, source._load_config(args))
    assert resolved["root"] == root.resolve()
    assert resolved["data_dir"] == (root / "target" / "data").resolve()
    assert resolved["source_data_dir"] == (root / "source" / "data").resolve()


def test_b3_config_rejects_missing_explicit_roots(tmp_path):
    root = tmp_path / "b3"
    root.mkdir()
    config = _config(root)
    args = _args(tmp_path, config)
    args.credential_root = None
    with pytest.raises(source.SourceVerifyError):
        source._validate_config(args, config)


def test_b3_config_rejects_overlapping_source_and_target(tmp_path):
    root = tmp_path / "b3"
    root.mkdir()
    config = _config(root, source_data_dir=str(root / "target" / "data"))
    args = _args(tmp_path, config)
    with pytest.raises(source.SourceVerifyError):
        source._validate_config(args, config)


def test_b3_config_rejects_package_inside_target_data(tmp_path):
    root = tmp_path / "b3"
    root.mkdir()
    config = _config(root, source_package=str(root / "target" / "data" / "old.kgmbackup"))
    args = _args(tmp_path, config)
    with pytest.raises(source.SourceVerifyError):
        source._validate_config(args, config)


def test_b3_config_rejects_outside_root(tmp_path):
    root = tmp_path / "b3"
    root.mkdir()
    other = tmp_path / "outside"
    other.mkdir()
    config = _config(root, source_data_dir=str(other / "data"))
    args = _args(tmp_path, config)
    with pytest.raises(source.SourceVerifyError):
        source._validate_config(args, config)


def test_network_guard_blocks_nonloopback_before_runtime(tmp_path):
    import socket

    from maintenance_source_guard import NetworkGuard

    guard = NetworkGuard(tmp_path / "evidence")
    guard.install()
    try:
        with pytest.raises(OSError, match="B3_NETWORK_BLOCKED"):
            socket.getaddrinfo("example.com", 443)
        # Loopback remains available for the real local API.  Use a controlled
        # bound listener instead of assuming a closed port is unmonitored.
        assert socket.getaddrinfo("127.0.0.1", 1)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        try:
            with socket.socket() as sock:
                sock.connect(("127.0.0.1", listener.getsockname()[1]))
        finally:
            listener.close()
        assert guard.attempts() == 1
    finally:
        guard.uninstall()


def test_child_guard_is_written_for_spawned_workers(tmp_path):
    from maintenance_source_guard import NetworkGuard

    guard = NetworkGuard(tmp_path / "evidence")
    child = guard.install_child_guard()
    text = (child / "sitecustomize.py").read_text(encoding="utf-8")
    assert "B3_NETWORK_BLOCKED" in text
    assert "socket.getaddrinfo" in text


def test_preflight_refuses_existing_package_without_deleting_it(tmp_path):
    root = tmp_path / "b3"
    root.mkdir()
    package = root / "old.kgmbackup"
    package.write_bytes(b"existing-package")
    config = _config(root)
    with pytest.raises(source.SourceVerifyError, match="拒绝覆盖"):
        source._preflight_paths(config)
    assert package.read_bytes() == b"existing-package"


def test_d1_main_b3_phase_requires_explicit_roots_and_config(tmp_path):
    import d1_main

    args = SimpleNamespace(
        selftest=True,
        phase="b3-source-window",
        data=None,
        credential_root=None,
        b3_config=None,
        synthetic_provider_port=None,
        synthetic_executor_fail=None,
    )
    with pytest.raises(RuntimeError):
        d1_main._validate_synthetic_entry(args)
    args.data = str(tmp_path / "data")
    with pytest.raises(RuntimeError):
        d1_main._validate_synthetic_entry(args)
    args.credential_root = str(tmp_path / "cred")
    with pytest.raises(RuntimeError):
        d1_main._validate_synthetic_entry(args)
    args.b3_config = str(tmp_path / "config.json")
    d1_main._validate_synthetic_entry(args)


def test_guard_attempts_are_in_memory_when_log_is_unavailable(tmp_path, monkeypatch):
    import socket
    from unittest import mock

    from maintenance_source_guard import NetworkGuard

    guard = NetworkGuard(tmp_path / "evidence")
    guard.install()
    original_open = Path.open

    def unavailable(path, *args, **kwargs):
        if Path(path) == guard.log_path:
            raise OSError("controlled unavailable guard audit file")
        return original_open(path, *args, **kwargs)

    try:
        with mock.patch.object(Path, "open", unavailable):
            with pytest.raises(OSError, match="B3_NETWORK_BLOCKED"):
                socket.getaddrinfo("blocked.invalid", 443)
            assert guard.attempts() == 1
            assert guard.audit_ok() is False
    finally:
        guard.uninstall()


def test_spawned_python_interpreter_installs_child_guard(tmp_path):
    from maintenance_source_guard import NetworkGuard

    guard = NetworkGuard(tmp_path / "evidence")
    assert guard.verify_child_guard() is True
    assert (tmp_path / "evidence" / "guard-child-blocked.txt").is_file()


def test_early_driver_error_destroys_own_window(tmp_path, monkeypatch):
    import threading
    from types import SimpleNamespace

    import d1_main
    import maintenance_source_verify as source

    class Window:
        def __init__(self):
            self.destroyed = 0

        def destroy(self):
            self.destroyed += 1

    class Api:
        def _request_retire_destroy(self):
            pass

        def _maintenance_busy_probe(self):
            return False

    class Driver:
        def wait_until(self, *args, **kwargs):
            raise RuntimeError("controlled early driver failure")

    window = Window()
    api = Api()
    bundle = SimpleNamespace(generation=1, window=window, host_api=api)
    lifecycle = SimpleNamespace(current=lambda: bundle)
    checks = {}
    summary = {"checks": checks}
    done = threading.Event()
    out = tmp_path / "driverfail.json"
    monkeypatch.setattr(d1_main, "JsDriver", lambda *a, **k: Driver())
    source._run_driver(
        window,
        api,
        None,
        lifecycle,
        {"timeout": 0.1},
        summary,
        checks,
        {},
        {},
        out,
        done,
    )
    assert checks.get("driver_error")
    assert out.is_file()
    assert window.destroyed > 0 or not done.is_set()


def test_log_deleted_after_attempt_is_unknown_not_zero(tmp_path):
    import socket

    from maintenance_source_guard import NetworkGuard

    guard = NetworkGuard(tmp_path / "evidence")
    guard.install()
    try:
        with pytest.raises(OSError, match="B3_NETWORK_BLOCKED"):
            socket.getaddrinfo("blocked.invalid", 443)
        assert guard.attempts() == 1
        assert guard.log_attempts() == 1
        guard.log_path.unlink()
        assert guard.log_attempts() is None
        assert guard.audit_ok() is False
    finally:
        guard.uninstall()


def test_every_embedded_driver_js_literal_parses_in_node(tmp_path):
    import ast
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")

    source_paths = sorted(
        (Path(__file__).resolve().parent.parent).glob("maintenance_source_*.py")
    )
    assert source_paths
    trees = [ast.parse(path.read_text(encoding="utf-8")) for path in source_paths]

    def constant_string(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = constant_string(node.left)
            right = constant_string(node.right)
            if left is not None and right is not None:
                return left + right
        return None

    scripts = []
    for tree in trees:
      for call in ast.walk(tree):
        if not isinstance(call, ast.Call) or not call.args:
            continue
        func = call.func
        name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
        if name not in {"eval", "wait_until"}:
            continue
        value = constant_string(call.args[0])
        if value:
            scripts.append(value)
    assert scripts, "no embedded driver JS literals found"
    payload = tmp_path / "scripts.json"
    payload.write_text(json.dumps(scripts, ensure_ascii=False), encoding="utf-8")
    checker = (
        "const fs=require('fs');"
        "const xs=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));"
        "const bad=[];"
        "for(const x of xs){try{new Function(x)}catch(e){bad.push({script:x,error:String(e)})}}"
        "if(bad.length){console.error(JSON.stringify(bad));process.exit(1)}"
        "console.log('parsed '+xs.length)"
    )
    result = subprocess.run(
        [node, "-e", checker, str(payload)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_driver_cleanup_cancels_only_unswitched_maintenance():
    from types import SimpleNamespace

    import maintenance_source_verify as source

    cancelled = []

    class Maintenance:
        _ops = {
            "preview": {"operation_id": "p", "generation": 1, "phase": "preview"},
            "protection": {"operation_id": "q", "generation": 2, "phase": "protection"},
            "switching": {"operation_id": "s", "generation": 3, "phase": "switching"},
            "done": {"operation_id": "d", "generation": 4, "phase": "completed"},
        }

        def cancel(self, payload):
            cancelled.append(payload["operation_id"])
            return {"accepted": True, "state": "cancelled"}

    host = SimpleNamespace(_maintenance_host=Maintenance())
    assert source._cleanup_unswitched_maintenance(host) == 2
    assert cancelled == ["p", "q"]
    assert "s" not in cancelled and "d" not in cancelled


def test_b3_artifacts_must_stay_inside_synthetic_root(tmp_path):
    root = tmp_path / "b3"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    config = _config(root, bad_package=str(outside / "bad.kgmbackup"))
    args = _args(tmp_path, config)
    Path(args.b3_config).write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(source.SourceVerifyError, match="root"):
        source._validate_config(args, source._load_config(args))


def test_b3_out_must_stay_inside_synthetic_root(tmp_path):
    root = tmp_path / "b3"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    config = _config(root)
    args = _args(tmp_path, config)
    args.out = str(outside / "result.json")
    Path(args.b3_config).write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(source.SourceVerifyError, match="root"):
        source._validate_config(args, source._load_config(args))


def test_b3_artifact_alias_package_is_refused(tmp_path):
    root = tmp_path / "b3"
    root.mkdir()
    config = _config(root, bad_package=str(root / "old.kgmbackup"))
    args = _args(tmp_path, config)
    Path(args.b3_config).write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(source.SourceVerifyError, match="别名"):
        source._validate_config(args, source._load_config(args))


def test_preflight_refuses_existing_out_without_deleting_it(tmp_path):
    root = tmp_path / "b3"
    root.mkdir()
    out = root / "evidence" / "result.json"
    out.parent.mkdir(parents=True)
    out.write_text("existing", encoding="utf-8")
    config = _config(root, out_path=str(out))
    with pytest.raises(source.SourceVerifyError, match="out"):
        source._preflight_paths(config)
    assert out.read_text(encoding="utf-8") == "existing"


def test_ai_cold_diff_detects_composite_pk_calendar_change(tmp_path):
    """A guessed date/id key must not collapse composite-PK calendar rows."""
    import sqlite3

    import maintenance_source_ai_cold as ai_cold

    def build(path: Path, *, base_state: str, task_payload: str) -> Path:
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                "create table local_calendar_days ("
                "revision_id text not null, date text not null,"
                "base_state text not null, primary key (revision_id, date))"
            )
            connection.execute(
                "create table local_ai_tasks ("
                "id text not null primary key, status text not null,"
                "reason text, runtime_meta_json text not null,"
                "updated_at text not null, payload text not null)"
            )
            connection.execute(
                "insert into local_calendar_days values (?,?,?)",
                ("r1", "2026-09-02", base_state),
            )
            connection.execute(
                "insert into local_calendar_days values (?,?,?)",
                ("r2", "2026-09-02", "holiday"),
            )
            connection.execute(
                "insert into local_ai_tasks values (?,?,?,?,?,?)",
                (
                    "t1",
                    "pending" if task_payload == "same" else "paused",
                    None if task_payload == "same" else "restart",
                    '{"processing_certainty":"not_sent"}',
                    "2026-10-31T00:00:00",
                    task_payload,
                ),
            )
            connection.commit()
        finally:
            connection.close()
        return path

    source = build(tmp_path / "source.db", base_state="teaching", task_payload="same")
    target = build(tmp_path / "target.db", base_state="holiday", task_payload="same")
    diffs = ai_cold._diff_dumps(
        ai_cold._db_dump(source), ai_cold._db_dump(target), "t1"
    )
    assert any(item.get("table") == "local_calendar_days" for item in diffs)
    assert not any(item.get("table") == "local_ai_tasks" for item in diffs)

    changed_task = build(
        tmp_path / "target-task.db", base_state="holiday", task_payload="changed"
    )
    task_diffs = ai_cold._diff_dumps(
        ai_cold._db_dump(source), ai_cold._db_dump(changed_task), "t1"
    )
    assert any(
        item.get("table") == "local_ai_tasks"
        and item.get("column") == "payload"
        for item in task_diffs
    )


@pytest.mark.parametrize(
    "kind",
    [
        "bad_equals_encrypted",
        "out_equals_bad",
        "out_equals_encrypted",
        "out_equals_source",
        "out_equals_target",
        "bad_equals_config",
    ],
)
def test_b3_config_rejects_pairwise_file_artifact_aliases(tmp_path, kind):
    root = tmp_path / "b3"
    root.mkdir()
    config = _config(root)
    args = _args(tmp_path, config)
    if kind == "bad_equals_encrypted":
        config["bad_package"] = str(root / "same.kgmbackup")
        config["encrypted_package"] = str(root / "same.kgmbackup")
    elif kind == "out_equals_bad":
        config["bad_package"] = str(root / "same.kgmbackup")
        args.out = str(root / "same.kgmbackup")
    elif kind == "out_equals_encrypted":
        config["encrypted_package"] = str(root / "same.kgmbackup")
        args.out = str(root / "same.kgmbackup")
    elif kind == "out_equals_source":
        args.out = str(root / "old.kgmbackup")
    elif kind == "out_equals_target":
        args.out = str(root / "target.kgmbackup")
    elif kind == "bad_equals_config":
        config["bad_package"] = str(args.b3_config)
    Path(args.b3_config).write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(source.SourceVerifyError):
        source._validate_config(args, config)


@pytest.mark.parametrize(
    "role",
    ["word_dir_is_file", "bad_package_is_dir", "out_is_dir", "source_package_is_dir"],
)
def test_b3_config_rejects_invalid_file_directory_roles(tmp_path, role):
    root = tmp_path / "b3"
    root.mkdir()
    config = _config(root)
    args = _args(tmp_path, config)
    if role == "word_dir_is_file":
        (root / "word").write_text("not a directory", encoding="utf-8")
    elif role == "bad_package_is_dir":
        (root / "bad.kgmbackup").mkdir()
    elif role == "out_is_dir":
        args.out = str(root / "out-as-directory")
        (root / "out-as-directory").mkdir()
    elif role == "source_package_is_dir":
        (root / "old.kgmbackup").mkdir()
    Path(args.b3_config).write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(source.SourceVerifyError):
        source._validate_config(args, config)
