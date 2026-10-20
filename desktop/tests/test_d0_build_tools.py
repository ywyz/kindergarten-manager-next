"""R4: native Windows npm/npx resolution and effective build flags."""

import sys
from pathlib import Path

import build_d0


def test_missing_tool_returns_empty(monkeypatch):
    monkeypatch.setattr(build_d0.shutil, "which", lambda name: None)
    assert build_d0.resolve_node_tool("npm") == []


def test_cmd_shim_routed_through_cmd(monkeypatch):
    monkeypatch.setattr(
        build_d0.shutil, "which", lambda name: r"C:\Program Files\nodejs\npm.CMD"
    )
    monkeypatch.setenv("COMSPEC", r"C:\Windows\System32\cmd.exe")
    assert build_d0.resolve_node_tool("npm") == [
        r"C:\Windows\System32\cmd.exe",
        "/c",
        r"C:\Program Files\nodejs\npm.CMD",
    ]


def test_bat_shim_routed_through_cmd(monkeypatch):
    monkeypatch.setattr(build_d0.shutil, "which", lambda name: r"C:\tools\npx.bat")
    monkeypatch.setenv("COMSPEC", r"C:\Windows\System32\cmd.exe")
    assert build_d0.resolve_node_tool("npx")[:2] == [
        r"C:\Windows\System32\cmd.exe",
        "/c",
    ]


def test_plain_executable_used_directly(monkeypatch):
    monkeypatch.setattr(build_d0.shutil, "which", lambda name: "/usr/bin/npm")
    assert build_d0.resolve_node_tool("npm") == ["/usr/bin/npm"]


def test_default_build_runs_frontend_then_package(monkeypatch):
    calls = []
    monkeypatch.setattr(build_d0, "build_frontend", lambda: calls.append("frontend"))
    monkeypatch.setattr(
        build_d0, "build_package", lambda: calls.append("package") or Path("pkg")
    )
    monkeypatch.setattr(sys, "argv", ["build_d0.py"])
    assert build_d0.main() == 0
    assert calls == ["frontend", "package"]


def test_skip_frontend_skips_frontend_build(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(build_d0, "build_frontend", lambda: calls.append("frontend"))
    monkeypatch.setattr(
        build_d0, "build_package", lambda: calls.append("package") or Path("pkg")
    )
    monkeypatch.setattr(build_d0, "FRONTEND_DIR", tmp_path)
    (tmp_path / "d0.html").write_text("<html>D0</html>", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["build_d0.py", "--skip-frontend"])
    assert build_d0.main() == 0
    assert calls == ["package"]
