"""Pure source-case regressions for B3 maintenance drivers.

No LocalRuntime, service, executor, GUI, window CLI, supplier, WebDAV,
installer or real credential is created.  The only subprocesses are ordinary
Node parse-only processes and ordinary Python imports of the main helper.

The tests are deliberately static/complementary:

* every statically literal ``driver.eval``/``eval_json``/``wait_until`` first
  argument in every ``desktop/maintenance_source_*.py`` file is parsed by
  Node ``new Function`` (parse only, no execution/DOM/network);
* every ``from maintenance_source_verify import NAME`` in those modules is
  checked against the actual imported main helper without importing the case
  module or running any case function;
* the main click/input helpers are driven by a pure recording fake driver and
  their generated JavaScript is parsed the same way, including quoted text,
  newlines and input-versus-container selectors.
"""

from __future__ import annotations

import ast
import importlib
import shutil
import subprocess
from pathlib import Path

import pytest


DESKTOP_DIR = Path(__file__).resolve().parent.parent
NODE_PARSE_SCRIPT = (
    "const fs=require('fs');"
    "const src=fs.readFileSync(0,'utf8');"
    "try{new Function(src);}"
    "catch(e){console.error(e&&e.stack?e.stack:String(e));process.exit(1);}"
)


def _source_files() -> list[Path]:
    files = sorted(DESKTOP_DIR.glob("maintenance_source_*.py"))
    assert files, f"no maintenance_source_*.py files under {DESKTOP_DIR}"
    return files


def _node_executable() -> str:
    executable = shutil.which("node") or shutil.which("node.exe")
    if not executable:
        pytest.fail(
            "Node executable not found; literal driver JavaScript cannot be "
            "parsed (no install attempted)"
        )
    return executable


def _node_parse(node: str, source: str):
    try:
        return subprocess.run(
            [node, "-e", NODE_PARSE_SCRIPT],
            input=source,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f"Node parse timed out for literal JavaScript: {exc}")


def _literal_driver_javascript():
    for path in _source_files():
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            pytest.fail(
                f"cannot parse {path.name}:{exc.lineno}: {exc.msg}"
            )
        relative = path.relative_to(DESKTOP_DIR).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            if (
                not isinstance(function, ast.Attribute)
                or function.attr
                not in {"eval", "eval_json", "wait_until"}
                or not node.args
            ):
                continue
            try:
                value = ast.literal_eval(node.args[0])
            except (ValueError, TypeError, SyntaxError):
                continue
            if isinstance(value, str):
                yield relative, node.lineno, value


def _imported_main_names():
    for path in _source_files():
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            pytest.fail(
                f"cannot parse {path.name}:{exc.lineno}: {exc.msg}"
            )
        relative = path.relative_to(DESKTOP_DIR).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.level != 0 or node.module != "maintenance_source_verify":
                continue
            for alias in node.names:
                yield relative, node.lineno, alias.name


def test_all_literal_driver_javascript_parses_with_node():
    node = _node_executable()
    calls = list(_literal_driver_javascript())
    assert calls, (
        "no statically literal driver eval/eval_json/wait_until first "
        "arguments found; the scanner would otherwise silently pass"
    )
    files = {relative for relative, _line, _source in calls}
    assert any(
        relative == "maintenance_source_verify.py" for relative in files
    ), f"main literal JS not covered: {sorted(files)}"
    assert any(
        relative == "maintenance_source_setup.py" for relative in files
    ), f"setup-case literal JS not covered: {sorted(files)}"

    failures: list[str] = []
    for relative, line, source in calls:
        result = _node_parse(node, source)
        if result.returncode != 0:
            failures.append(
                f"{relative}:{line}\n"
                f"{result.stderr.strip()}\n"
                f"source={source[:400]!r}"
            )
    assert not failures, (
        "Node new Function parse failed for literal driver JavaScript "
        "(parse-only; nothing executed):\n\n" + "\n\n".join(failures)
    )


def test_source_case_imports_from_main_helper_exist():
    imports = list(_imported_main_names())
    assert imports, (
        "no source-case imports from maintenance_source_verify found; "
        "the checker would otherwise silently pass"
    )
    assert any(
        relative == "maintenance_source_setup.py"
        for relative, _line, _name in imports
    ), f"setup-case imports not covered: {sorted({item[0] for item in imports})}"

    try:
        main = importlib.import_module("maintenance_source_verify")
    except Exception as exc:  # noqa: BLE001 - a source failure is reported
        pytest.fail(
            "cannot import the main helper solely for name checks: "
            f"{type(exc).__name__}: {exc}"
        )

    failures: list[str] = []
    for relative, line, name in imports:
        if name == "*":
            failures.append(
                f"{relative}:{line}: star import cannot be verified statically"
            )
        elif not hasattr(main, name):
            failures.append(
                f"{relative}:{line}: maintenance_source_verify has no {name!r}"
            )
    assert not failures, (
        "source-case module imports names missing from the main helper:\n\n"
        + "\n".join(failures)
    )


def test_main_js_helpers_generate_parsable_scripts():
    node = _node_executable()
    try:
        main = importlib.import_module("maintenance_source_verify")
    except Exception as exc:  # noqa: BLE001 - a source failure is reported
        pytest.fail(
            "cannot import the main helper for JS helper checks: "
            f"{type(exc).__name__}: {exc}"
        )

    required = (
        "_js_click",
        "_js_click_visible",
        "_js_click_text",
        "_js_set_input",
    )
    missing = [name for name in required if not hasattr(main, name)]
    assert not missing, (
        "main JS helper(s) missing; generate-script coverage would be "
        f"incomplete: {missing}"
    )

    class RecordingDriver:
        def __init__(self):
            self.scripts: list[str] = []

        def eval(self, script):
            self.scripts.append(script)
            return True

    cases = (
        (
            "_js_click selector",
            lambda driver: main._js_click(
                driver, '[data-d1="open-settings"]'
            ),
        ),
        (
            "_js_click_visible selector",
            lambda driver: main._js_click_visible(
                driver, '[data-d1="setup-restore"]'
            ),
        ),
        (
            "_js_click_text quoted text",
            lambda driver: main._js_click_text(
                driver,
                '[data-d1="backup-password-mode"]',
                '不加密 "quoted" \\ 反斜杠',
            ),
        ),
        (
            "_js_set_input input selector",
            lambda driver: main._js_set_input(
                driver,
                '[data-d1="backup-password"]',
                'line1\n"quoted"\\tail',
            ),
        ),
        (
            "_js_set_input container selector",
            lambda driver: main._js_set_input(
                driver,
                '[data-d1="backup-password-mode"]',
                '容器输入 "quoted"',
            ),
        ),
    )

    failures: list[str] = []
    for label, call in cases:
        driver = RecordingDriver()
        try:
            result = call(driver)
        except Exception as exc:  # noqa: BLE001 - reported to the test
            failures.append(
                f"{label}: helper raised {type(exc).__name__}: {exc}"
            )
            continue
        if result is not True:
            failures.append(f"{label}: helper returned {result!r}, not True")
            continue
        if len(driver.scripts) != 1:
            failures.append(
                f"{label}: expected one generated script, got "
                f"{len(driver.scripts)}"
            )
            continue
        parsed = _node_parse(node, driver.scripts[0])
        if parsed.returncode != 0:
            failures.append(
                f"{label}: Node parse failed\n{parsed.stderr.strip()}\n"
                f"source={driver.scripts[0][:400]!r}"
            )
    assert not failures, (
        "generated main-helper JavaScript failed syntax/quoting checks "
        "(parse-only; no DOM/network):\n\n" + "\n\n".join(failures)
    )
