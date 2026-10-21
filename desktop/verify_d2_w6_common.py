"""D2 W6 real Windows window verification (re-runnable drivers).

Reusable functions launch any D2 program (a source ``python d1_main.py`` **or**
the frozen ``KGNext-D2Verify.exe``) in the dedicated selftest phases against
isolated synthetic roots (isolated ``credential_root``/``LOCALAPPDATA`` and
``APP_DISABLE_DOTENV=1``) plus a controlled local TLS provider (real
cert/hostname validation, real ``AiExecutor`` + Windows spawn/Job — never an
external network).

* :func:`run_g14` — G14 closed loop (split -> preview edit -> adopt -> adapt ->
  adopt -> teacher manual edit -> save -> single + merged native DOCX) plus the
  restart phase; the exported DOCX redline is asserted structurally.
* :func:`run_g15_branch` — one G15 degradation branch with a real manual save
  and native export.

``verify_d2_w6_window.py`` drives the source program; ``verify_d2_w6_package``
drives the frozen executable.
"""

from __future__ import annotations

import json
import os
import subprocess
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

SPLIT_OUT = json.dumps(
    {
        "group_activity": {
            "theme": "合成主题",
            "objectives": "合成目标",
            "preparation": "合成准备",
            "key_points": "合成重点",
            "difficult_points": "合成难点",
            "process": "一、导入\n二、观察\n三、比较",
        }
    },
    ensure_ascii=False,
)
ADAPT_OUT = json.dumps({"process": "一、导入\n二、观察\n三、比较（适龄版）"}, ensure_ascii=False)
OTHER_OUT = json.dumps(
    {
        "morning_games": [
            {
                "group_kind": "collective",
                "games": [{"name": "合成集体游戏"}],
                "shared_objectives": "共享目标",
                "focus_guidance": "重点指导",
            },
            {
                "group_kind": "free_choice",
                "games": [{"name": "合成自选游戏"}],
                "guidance_points": "指导要点",
            },
        ],
        "morning_talk": {"topic": "合成晨谈话题", "questions": "合成问题设计"},
        "post_group_games": [
            {"context_kind": "area", "games": [{"name": "合成区域游戏"}], "objectives": "目标"}
        ],
        "afternoon_outdoor": {"games": [{"name": "合成户外游戏"}], "area": "操场"},
    },
    ensure_ascii=False,
)

FINAL_PROCESS = "一、导入\n二、观察（教师改为细致观察）\n三、比较\n四、教师新增段落"
MODEL_PROCESS = "一、导入\n二、观察\n三、比较"

# Fixed, pre-registered expectation registry. The verifiers assert that every
# expected key is present and strictly ``True``; they never derive the expected
# set from the produced checks.
G14_SUFFIXES = (
    "exit_zero",
    "w6_initialized",
    "w6_ai_configured",
    "w6_split_preview_edit_adopt",
    "w6_adapt_adopt",
    "w6_teacher_manual_save",
    "w6_export_single_day",
    "w6_export_merged_range",
    "server_stopped",
    "ai_worker_confirmed_exit",
    "baseline_is_model_process",
    "final_process_recorded",
    "provider_split",
    "provider_split_once",
    "provider_adapt",
    "provider_adapt_once",
    "provider_no_other",
    "docx_single_found",
    "docx_unchanged_not_red",
    "docx_added_red",
    "docx_no_preview_leak",
    "docx_merged_found",
    "docx_merged_two_titles",
    "docx_merged_dates",
    "docx_merged_page_break",
    "docx_merged_second_content",
    "restart_exit_zero",
    "restart_process_saved",
    "restart_baseline_is_model",
    "restart_export_saved",
    "restart_server_stopped",
    "restart_no_provider_requests",
    "restart_docx_found",
    "restart_docx_redline",
)

G15_BASE_SUFFIXES = (
    "exit_zero",
    "config_readable",
    "manual_save",
    "native_export",
    "content_intact",
    "server_stopped",
    "worker_exit",
)
G15_EXTRA_SUFFIXES = {
    "none": (),
    "executor": ("ai_readable", "no_task"),
    "config_error": ("ai_readable", "no_task"),
    "network": ("ai_failed_without_blocking",),
}


def expected_g14(prefix: str = "ui_") -> set[str]:
    return {prefix + suffix for suffix in G14_SUFFIXES}


def expected_g15(prefix: str, expect: str) -> set[str]:
    suffixes = G15_BASE_SUFFIXES + G15_EXTRA_SUFFIXES[expect]
    return {prefix + suffix for suffix in suffixes}


def make_reply_factory(seen: dict, *, stream: bool = False):
    def factory(request: bytes):
        text = request.decode("utf-8", "replace")
        if "process_source" in text:
            seen["adapt"] = seen.get("adapt", 0) + 1
            return _sse_envelope(ADAPT_OUT) if stream else _envelope(ADAPT_OUT)
        if "calendar_context" in text or "morning_games" in text:
            seen["other"] = seen.get("other", 0) + 1
            return _sse_envelope(OTHER_OUT) if stream else _envelope(OTHER_OUT)
        seen["split"] = seen.get("split", 0) + 1
        return _sse_envelope(SPLIT_OUT) if stream else _envelope(SPLIT_OUT)

    return factory


def _sse_envelope(text: str) -> bytes:
    """A standard OpenAI-compatible SSE reply with reasoning + split content."""
    import json as _json

    events = [
        {
            "model": "w6-synthetic",
            "choices": [{"index": 0, "delta": {"role": "assistant", "reasoning_content": "W6 合成思考过程"}}],
        },
        {
            "choices": [
                {"index": 0, "delta": {"content": text[: max(1, len(text) // 3)]}}
            ]
        },
        {
            "choices": [
                {"index": 0, "delta": {"content": text[max(1, len(text) // 3) :]}}
            ]
        },
        {
            "choices": [
                {"index": 0, "delta": {}, "finish_reason": "stop"}
            ]
        },
    ]
    body = b"".join(
        b"data: " + _json.dumps(event, ensure_ascii=False).encode("utf-8") + b"\n\n"
        for event in events
    ) + b"data: [DONE]\n\n"
    return (
        b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: "
        + str(len(body)).encode()
        + b"\r\n\r\n"
        + body
    )


def sse_segments(text: str, *, reasoning: str = "W5 合成思考过程", delay: float = 1.5):
    """A segmented SSE reply: reasoning/partial content, then a delayed final.

    The returned list is ``[(bytes, delay_before_send), ...]`` for the controlled
    TLS server. The delay is what makes the frozen-window progress assertion
    meaningful: the window must show real reasoning *before* the final answer.
    """
    import json as _json

    split = max(1, len(text) // 2)
    first_events = [
        {
            "model": "w5-synthetic",
            "choices": [
                {"index": 0, "delta": {"role": "assistant", "reasoning_content": reasoning}}
            ],
        },
        {
            "choices": [
                {"index": 0, "delta": {"content": text[:split]}}
            ]
        },
    ]
    second_events = [
        {
            "choices": [
                {"index": 0, "delta": {"content": text[split:]}}
            ]
        },
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    first_body = b"".join(
        b"data: " + _json.dumps(event, ensure_ascii=False).encode("utf-8") + b"\n\n"
        for event in first_events
    )
    second_body = b"".join(
        b"data: " + _json.dumps(event, ensure_ascii=False).encode("utf-8") + b"\n\n"
        for event in second_events
    ) + b"data: [DONE]\n\n"
    total = len(first_body) + len(second_body)
    head = (
        b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: "
        + str(total).encode()
        + b"\r\n\r\n"
    )
    return [(head + first_body, 0.0), (second_body, delay)]


def adapt_hold_segments(
    *, reasoning: str = "W5 适配准备", hold: float = 30.0
):
    """A real provider receipt that stays open until the close flow aborts it.

    The first segment is a valid SSE reasoning event (so the window can prove
    the adapt request was actually received), followed by a deliberately
    incomplete body held open. The declared Content-Length is larger than the
    bytes sent; a normal completion never happens. Closing the task therefore
    has real sent evidence, not a pending/claimed guess.
    """
    import json as _json

    event = {
        "model": "w5-synthetic",
        "choices": [
            {"index": 0, "delta": {"role": "assistant", "reasoning_content": reasoning}}
        ],
    }
    first_body = (
        b"data: " + _json.dumps(event, ensure_ascii=False).encode("utf-8") + b"\n\n"
        + b": w5-adapt-hold\n\n"
    )
    head = (
        b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: 1000000\r\n\r\n"
    )
    return [(head + first_body, 0.0), (b"", hold)]


def _envelope(text: str) -> bytes:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from tests.local import w3_tls

    return w3_tls.envelope(text)


def run_window(program, args, env, log_path: Path, timeout: int, *, cwd=None) -> int:
    with log_path.open("wb") as log:
        process = subprocess.run(
            [*program, *args],
            cwd=str(cwd) if cwd is not None else str(HERE),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    return process.returncode


def sanitize_package_env(env: dict) -> dict:
    """A frozen-package environment that cannot reach the source checkout.

    Removes ``PYTHONPATH``/``PYTHONHOME``, every inherited ``KGM_*`` variable and
    restricts ``PATH`` to the system directories, so the packaged executable
    resolves only its own bundled resources.
    """
    clean = dict(env)
    for key in list(clean):
        if key in ("PYTHONPATH", "PYTHONHOME") or key.startswith("KGM_"):
            clean.pop(key, None)
    system_root = os.environ.get("SystemRoot") or r"C:\Windows"
    clean["PATH"] = os.pathsep.join(
        [
            str(Path(system_root) / "System32"),
            system_root,
            str(Path(system_root) / "System32" / "Wbem"),
        ]
    )
    return clean


def load_summary(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def base_env(root: Path, run_name: str) -> dict:
    env = dict(os.environ)
    env["LOCALAPPDATA"] = str(root / f"localappdata-{run_name}")
    env["APP_DISABLE_DOTENV"] = "1"
    env.pop("KGM_LOCAL_DATA_DIR", None)
    return env


def docx_runs(path: Path):
    from lxml import etree

    with zipfile.ZipFile(path) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
    red: list[str] = []
    plain: list[str] = []
    for node in root.iter(f"{W}t"):
        color = node.getparent().find(f"{W}rPr/{W}color")
        is_red = color is not None and color.get(f"{W}val") == "FF0000"
        (red if is_red else plain).append(node.text or "")
    return root, "".join(red), "".join(plain)


def find_saved(save_dir: Path, filename):
    """The exact exported file named by the receipt; never a stray old DOCX."""
    if not filename:
        return None
    candidate = save_dir / filename
    return candidate if candidate.is_file() else None


def closed_port() -> int:
    import socket

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def credential_root_for(root: Path, env_label: str) -> Path:
    """The isolated credential directory for one branch's LOCALAPPDATA."""
    return root / f"localappdata-{env_label}" / "KindergartenManager" / "credentials"


def corrupt_credentials(root: Path, env_label: str) -> int:
    """Corrupt exactly this branch's DPAPI blobs; returns how many were hit."""
    base = credential_root_for(root, env_label)
    count = 0
    if base.is_dir():
        for path in sorted(base.rglob("*.dpapi")):
            path.write_bytes(b"corrupted-dpapi-material")
            count += 1
    return count


def run_g14(program, frontend, root, dates, provider_port, ca_pem, checks, report, seen, *, prefix="ui_", cwd=None, env_transform=None):
    """G14 closed loop + restart; asserts the exported DOCX structure."""
    provider_before_stage = dict(seen)
    data_dir = root / "data"
    save_dir = root / "saved-g14"
    save_dir.mkdir(parents=True, exist_ok=True)
    env = base_env(root, "g14")
    if env_transform is not None:
        env = env_transform(env)
    env["KGM_D1_VERIFY_SAVE_DIR"] = str(save_dir)
    env["KGM_D1_STARTUP_LOG"] = str(root / "startup-g14.log")
    out = root / "g14-ui.json"
    ui_args = [
        "--selftest",
        "--phase",
        "w6-ui",
        "--data",
        str(data_dir),
    ]
    if frontend is not None:
        ui_args.extend(["--frontend", str(frontend)])
    ui_args.extend(
        [
            "--date",
            dates["date"],
            "--date2",
            dates["date2"],
            "--term-start",
            "2026-09-01",
            "--term-end",
            "2026-09-30",
            "--synthetic-provider-port",
            str(provider_port),
            "--out",
            str(out),
        ]
    )
    if ca_pem:
        ui_args.extend(["--synthetic-provider-ca", str(ca_pem)])

    rc1 = run_window(program, ui_args, env, root / "g14-ui.log", 420, cwd=cwd)
    s1 = load_summary(out)
    report["steps"]["g14_ui_exit"] = rc1
    report["steps"]["g14_ui_summary"] = s1
    ui = s1.get("checks", {}) if isinstance(s1, dict) else {}
    checks[f"{prefix}exit_zero"] = rc1 == 0
    for key in (
        "w6_initialized",
        "w6_ai_configured",
        "w6_split_preview_edit_adopt",
        "w6_adapt_adopt",
        "w6_teacher_manual_save",
        "w6_export_single_day",
        "w6_export_merged_range",
        "server_stopped",
        "ai_worker_confirmed_exit",
    ):
        checks[f"{prefix}{key}"] = bool(ui.get(key))
    checks[f"{prefix}baseline_is_model_process"] = (
        (s1.get("w6_split_baseline") or {}).get("group_activity_process") == MODEL_PROCESS
    )
    checks[f"{prefix}final_process_recorded"] = s1.get("w6_final_process") == FINAL_PROCESS
    # The controlled provider must have answered exactly the G14 closed loop:
    # one split and one adapt *in this stage*, and never an "other" request.
    # Other stages (the resource probes) are reported separately.
    split_delta = seen.get("split", 0) - provider_before_stage.get("split", 0)
    adapt_delta = seen.get("adapt", 0) - provider_before_stage.get("adapt", 0)
    other_delta = seen.get("other", 0) - provider_before_stage.get("other", 0)
    report["steps"]["g14_provider_delta"] = {
        "split": split_delta,
        "adapt": adapt_delta,
        "other": other_delta,
    }
    checks[f"{prefix}provider_split"] = split_delta >= 1
    checks[f"{prefix}provider_split_once"] = split_delta == 1
    checks[f"{prefix}provider_adapt"] = adapt_delta >= 1
    checks[f"{prefix}provider_adapt_once"] = adapt_delta == 1
    checks[f"{prefix}provider_no_other"] = other_delta == 0

    single = find_saved(save_dir, (s1.get("w6_export_single") or {}).get("filename"))
    checks[f"{prefix}docx_single_found"] = single is not None
    if single is not None:
        _r, red, plain = docx_runs(single)
        checks[f"{prefix}docx_unchanged_not_red"] = "一、导入" in plain and "三、比较" in plain
        checks[f"{prefix}docx_added_red"] = "教师改为细致观察" in red and "教师新增段落" in red
        checks[f"{prefix}docx_no_preview_leak"] = (
            "（预览版）" not in red + plain and "（适龄版）" not in red + plain
        )

    merged = find_saved(save_dir, (s1.get("w6_export_merged") or {}).get("filename"))
    checks[f"{prefix}docx_merged_found"] = merged is not None
    if merged is not None:
        mroot, _mred, _mplain = docx_runs(merged)
        mtext = "".join(node.text or "" for node in mroot.iter(f"{W}t"))
        page_breaks = [
            br for br in mroot.findall(f".//{W}br") if br.get(f"{W}type") == "page"
        ]
        checks[f"{prefix}docx_merged_two_titles"] = mtext.count("一日活动计划") == 2
        checks[f"{prefix}docx_merged_dates"] = "9 月 15 日" in mtext and "9 月 16 日" in mtext
        checks[f"{prefix}docx_merged_page_break"] = len(page_breaks) >= 1
        checks[f"{prefix}docx_merged_second_content"] = "第二日反思 W6" in mtext

    # Restart phase: an INDEPENDENT launch without any synthetic provider (the
    # restart reads and exports only) and a distinct output file.
    provider_before_restart = dict(seen)
    restart_env = base_env(root, "g14")
    if env_transform is not None:
        restart_env = env_transform(base_env(root, "g14"))
    restart_env["KGM_D1_VERIFY_SAVE_DIR"] = str(root / "saved-g14-restart")
    Path(restart_env["KGM_D1_VERIFY_SAVE_DIR"]).mkdir(parents=True, exist_ok=True)
    restart_env["KGM_D1_STARTUP_LOG"] = str(root / "startup-g14-restart.log")
    out2 = root / "g14-restart.json"
    restart_args = [
        "--selftest",
        "--phase",
        "w6-ui-verify",
        "--data",
        str(data_dir),
    ]
    if frontend is not None:
        restart_args.extend(["--frontend", str(frontend)])
    restart_args.extend(
        [
            "--date",
            dates["date"],
            "--date2",
            dates["date2"],
            "--term-start",
            "2026-09-01",
            "--term-end",
            "2026-09-30",
            "--out",
            str(out2),
        ]
    )
    rc2 = run_window(program, restart_args, restart_env, root / "g14-restart.log", 300, cwd=cwd)
    s2 = load_summary(out2)
    report["steps"]["g14_restart_exit"] = rc2
    report["steps"]["g14_restart_summary"] = s2
    v = s2.get("checks", {}) if isinstance(s2, dict) else {}
    checks[f"{prefix}restart_exit_zero"] = rc2 == 0
    checks[f"{prefix}restart_process_saved"] = bool(v.get("w6v_process_saved"))
    checks[f"{prefix}restart_baseline_is_model"] = bool(v.get("w6v_baseline_is_model_process"))
    checks[f"{prefix}restart_export_saved"] = bool(v.get("w6v_export_saved"))
    checks[f"{prefix}restart_server_stopped"] = bool(v.get("server_stopped"))
    checks[f"{prefix}restart_no_provider_requests"] = dict(seen) == provider_before_restart
    restart_docx = find_saved(
        Path(restart_env["KGM_D1_VERIFY_SAVE_DIR"]),
        (s2.get("w6v_export") or {}).get("filename"),
    )
    checks[f"{prefix}restart_docx_found"] = restart_docx is not None
    if restart_docx is not None:
        _rr, rred, rplain = docx_runs(restart_docx)
        checks[f"{prefix}restart_docx_redline"] = (
            "一、导入" in rplain
            and "三、比较" in rplain
            and "教师改为细致观察" in rred
            and "教师新增段落" in rred
        )


def run_g15_branch(
    program, frontend, root, dates, label, *, expect, configure, checks, report,
    extra=None, provider_port=None, provider_ca=None, data_root=None, prefix="g15_",
    env_label=None, cwd=None, env_transform=None,
):
    """One G15 degradation branch (real manual save + native export).

    ``env_label`` fixes the isolated ``LOCALAPPDATA`` (and therefore the DPAPI
    credential directory) independently from the evidence file ``label``; two
    launches of the same branch share it so a corrupted blob is the *same*
    material, not a missing one.
    """
    env_label = env_label or label
    data = data_root if data_root is not None else (root / f"g15-{env_label}")
    save_dir = root / f"saved-{env_label}"
    save_dir.mkdir(parents=True, exist_ok=True)
    env = base_env(root, env_label)
    if env_transform is not None:
        env = env_transform(env)
    env["KGM_D1_VERIFY_SAVE_DIR"] = str(save_dir)
    env["KGM_D1_STARTUP_LOG"] = str(root / f"startup-{env_label}.log")
    phase_out = root / f"g15-{label}.json"
    command = [
        "--selftest",
        "--phase",
        "g15-noexec",
        "--data",
        str(data),
    ]
    if frontend is not None:
        command.extend(["--frontend", str(frontend)])
    command.extend(
        [
            "--g15-expect-ai",
            expect,
            "--g15-tag",
            label,
            "--out",
            str(phase_out),
            "--date",
            dates["date"],
        ]
    )
    if configure:
        command.append("--g15-configure")
    if extra:
        command.extend(extra)
    if provider_port is not None:
        command.extend(["--synthetic-provider-port", str(provider_port)])
        if provider_ca:
            command.extend(["--synthetic-provider-ca", str(provider_ca)])
    rc = run_window(program, command, env, root / f"g15-{label}.log", 300, cwd=cwd)
    summary = load_summary(phase_out)
    report["steps"][f"g15_{label}_exit"] = rc
    report["steps"][f"g15_{label}_summary"] = summary
    g = summary.get("checks", {}) if isinstance(summary, dict) else {}
    checks[f"{prefix}exit_zero"] = rc == 0
    checks[f"{prefix}config_readable"] = bool(g.get("g15_config_readable"))
    checks[f"{prefix}manual_save"] = bool(g.get("g15_manual_save"))
    checks[f"{prefix}native_export"] = bool(g.get("g15_native_export_saved"))
    checks[f"{prefix}content_intact"] = bool(g.get("g15_manual_content_intact"))
    checks[f"{prefix}server_stopped"] = bool(g.get("server_stopped"))
    checks[f"{prefix}worker_exit"] = bool(g.get("ai_worker_confirmed_exit"))
    if expect in ("executor", "config_error"):
        checks[f"{prefix}ai_readable"] = bool(g.get("g15_ai_unavailable_readable"))
        checks[f"{prefix}no_task"] = bool(g.get("g15_no_task_created"))
    elif expect == "network":
        checks[f"{prefix}ai_failed_without_blocking"] = bool(
            g.get("g15_ai_failed_without_blocking")
        )
    # Status strings live in metadata, never in the boolean check map.
    report["steps"][f"g15_{label}_status"] = summary.get("g15_split_task_status")
    return bool(g) and rc == 0


__all__ = [
    "ADAPT_OUT",
    "FINAL_PROCESS",
    "MODEL_PROCESS",
    "SPLIT_OUT",
    "expected_g14",
    "expected_g15",
    "base_env",
    "closed_port",
    "corrupt_credentials",
    "docx_runs",
    "find_saved",
    "load_summary",
    "make_reply_factory",
    "run_g14",
    "run_g15_branch",
    "run_window",
    "sanitize_package_env",
]
