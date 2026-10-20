"""W6 本机合成 AI 人工验收控制器（独立新增；不改既有生产入口/包）。

职责：

1. 在新的独立会话根下，用 SQLite **只读连接 + backup API** 从原人工验收数据
   （默认 ``build/desktop-d2/manual-acceptance-20261019-190131``）制作一致性克隆；
   绝不直接复制运行中的 SQLite 文件，也绝不写原根；
2. 启动受控 loopback TLS 供应商（本机测试 CA、固定 hostname、真实 TLS 校验），
   记录三类请求计数/时间/类型（不记录 Authorization/密钥）；
3. 用正常服务准备克隆副本的合成 AI 配置（明确是准备，不自动发起/采用任务）；
4. 启动独立人工入口 ``d2_manual_ai_main.py``（源码或独立新包），窗口保持打开由
   用户真实操作；控制器只做 clone/provider/config/记录与退出收口；
5. 提供有限 ``--mode smoke``（仅用于自测，用独立合成根，不消费正式人工会话）；
6. ``--fingerprint-package`` 对独立新包做无窗口同源指纹并比对源码/入口归档。

控制根内的 ``control/next.txt`` 可写 ``hold`` 让下一次请求挂起，改回 ``release``
释放，供后续人工“在途关闭/真实睡眠”操作；仅本机文件，不引入产品控制端点。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
BACKEND = REPO_ROOT / "backend"
FRONTEND = REPO_ROOT / "build" / "desktop-d2" / "frontend"
PYTHON_DEFAULT = HERE / ".venv-d1" / "Scripts" / "python.exe"
ORIGINAL_MANUAL_ROOT = REPO_ROOT / "build" / "desktop-d2" / "manual-acceptance-20261019-190131"
ORIGINAL_PACKAGE = REPO_ROOT / "build" / "desktop-d2" / "package" / "KGNext-D2Verify"
MANUAL_PACKAGE_DEFAULT = REPO_ROOT / "build" / "desktop-d2-manual-ai" / "package" / "KGNext-D2ManualAI"
DEFAULT_PLAN_ID = "KIukEWstt2Ib-gxSaDeYWw"

sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(HERE))

SPLIT_OUT = json.dumps(
    {
        "group_activity": {
            "theme": "W6人工验收合成主题",
            "objectives": "合成目标",
            "preparation": "合成准备",
            "key_points": "合成重点",
            "difficult_points": "合成难点",
            "process": "一、导入\n二、观察\n三、比较",
        }
    },
    ensure_ascii=False,
)
ADAPT_OUT = json.dumps(
    {"process": "一、导入\n二、观察\n三、比较（适龄版）"}, ensure_ascii=False
)
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _overlap(a: Path, b: Path) -> bool:
    return _is_under(a, b) or _is_under(b, a)


def _guard_new_session_root(root: Path, clone_from_data: Path) -> None:
    """All new-root checks BEFORE any mkdir/backup/credential/runtime.

    Rejects an existing directory (never overwrite), the real teacher data
    root, the original manual-acceptance root, and any overlap with the clone
    source root/data.
    """
    from app.local.sqlite import default_data_dir

    root = root.resolve()
    source_data = Path(clone_from_data).resolve()
    source_root = source_data.parent
    new_data = (root / "data").resolve()
    for protected in (default_data_dir().resolve(), ORIGINAL_MANUAL_ROOT.resolve()):
        if _overlap(root, protected) or _overlap(new_data, protected):
            raise RuntimeError(f"会话根与受保护根重叠，拒绝创建: {protected}")
    if _overlap(root, source_root) or _overlap(new_data, source_data):
        raise RuntimeError("会话根与克隆源根/源数据重叠，拒绝创建")
    if root.exists():
        raise RuntimeError(f"会话根已存在，拒绝覆盖: {root}")


def _tree_manifest(root: Path) -> dict:
    files = {
        str(p.relative_to(root)): _sha(p)
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }
    return {
        "count": len(files),
        "manifest_sha256": hashlib.sha256(
            json.dumps(files, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }


def classify_request(request: bytes) -> str:
    text = request.decode("utf-8", "replace")
    if "process_source" in text:
        return "adapt"
    if "calendar_context" in text or "morning_games" in text:
        return "other"
    return "split"


def _has_authorization_header(request: bytes) -> bool:
    """True only for a real HTTP ``Authorization:`` header line."""
    head = request.split(b"\r\n\r\n", 1)[0]
    for line in head.split(b"\r\n"):
        if line.lower().startswith(b"authorization:"):
            return True
    return False


def clone_sqlite(source_db: Path, target_db: Path) -> dict:
    """Consistent read-only clone via the SQLite backup API (never a file copy)."""
    from app.local.sqlite import readonly_sqlite_uri

    source_db = Path(source_db)
    target_db = Path(target_db)
    if not source_db.is_file():
        raise RuntimeError(f"克隆源数据库不存在: {source_db}")
    target_db.parent.mkdir(parents=True, exist_ok=True)
    if target_db.exists():
        raise RuntimeError(f"克隆目标已存在，拒绝覆盖: {target_db}")
    source = sqlite3.connect(readonly_sqlite_uri(source_db), uri=True, timeout=30)
    try:
        target = sqlite3.connect(str(target_db), timeout=30)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()
    check = sqlite3.connect(readonly_sqlite_uri(target_db), uri=True)
    try:
        integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
        fk = len(check.execute("PRAGMA foreign_key_check").fetchall())
        revision = check.execute(
            "SELECT version_num FROM local_alembic_version"
        ).fetchall()
    finally:
        check.close()
    if integrity != "ok":
        raise RuntimeError(f"克隆副本完整性检查失败: {integrity}")
    if fk:
        raise RuntimeError(f"克隆副本外键检查失败: {fk} 项")
    if len(revision) != 1:
        raise RuntimeError(f"克隆副本迁移版本非单 head: {revision}")
    return {
        "source_db": str(source_db),
        "source_sha256": _sha(source_db),
        "target_db": str(target_db),
        "target_sha256": _sha(target_db),
        "integrity": integrity,
        "foreign_key_violations": fk,
        "migration_rows": [row[0] for row in revision],
    }


def read_plan_facts(db_path: Path, plan_id: str) -> dict:
    from app.local.sqlite import readonly_sqlite_uri

    connection = sqlite3.connect(readonly_sqlite_uri(Path(db_path)), uri=True)
    try:
        row = connection.execute(
            "SELECT id, plan_date, current_content_version, current_content_id "
            "FROM local_daily_plans WHERE id = ?",
            (plan_id,),
        ).fetchone()
        if row is None:
            return {"plan_id": plan_id, "found": False}
        content = connection.execute(
            "SELECT raw_lesson_plan, adopted_content, split_baseline "
            "FROM local_daily_plan_contents WHERE id = ?",
            (row[3],),
        ).fetchone()
        adopted = json.loads(content[1]) if content and content[1] else {}
        group = (adopted.get("group_activity") or {}) if isinstance(adopted, dict) else {}
        return {
            "plan_id": row[0],
            "found": True,
            "plan_date": row[1],
            "content_version": row[2],
            "theme": group.get("theme"),
            "process": group.get("process"),
            "raw_present": bool(content and content[0]),
            "split_baseline": json.loads(content[2]) if content and content[2] else None,
        }
    finally:
        connection.close()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class ManualProvider:
    """Controlled loopback TLS provider with a file-based hold/release control."""

    def __init__(self, root: Path):
        from tests.local import w3_tls

        self.root = root
        self.logs = root / "logs"
        self.logs.mkdir(parents=True, exist_ok=True)
        self.control = root / "control"
        self.control.mkdir(parents=True, exist_ok=True)
        self.tls_dir = root / "tls"
        self.tls_dir.mkdir(parents=True, exist_ok=True)
        w3_tls.create_ca(self.tls_dir)
        leaf = w3_tls.create_leaf(self.tls_dir, self.tls_dir / "leaf")
        self.ca_pem = self.tls_dir / "ca.pem"
        self._requests: list[dict] = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._listener_stopped = False
        self._seen = {"split": 0, "adapt": 0, "other": 0}
        self._w3 = w3_tls
        self.server = w3_tls.TlsServer(
            cert=leaf[0], key=leaf[1], reply_factory=self._reply
        )
        self.server.start()
        (self.control / "next.txt").write_text("release", encoding="utf-8")
        (self.control / "README.txt").write_text(
            "写 hold 到 next.txt：下一次请求挂起（供在途关闭/真实睡眠）；"
            "改回 release 释放。仅本机文件，不是产品端点。\n",
            encoding="utf-8",
        )

    def _hold_requested(self) -> bool:
        try:
            return (self.control / "next.txt").read_text(encoding="utf-8").strip().lower().startswith("hold")
        except OSError:
            return False

    def _reply(self, request: bytes):
        kind = classify_request(request)
        with self._lock:
            self._seen[kind] = self._seen.get(kind, 0) + 1
            self._requests.append(
                {
                    "ts": _now(),
                    "kind": kind,
                    "bytes": len(request),
                    "has_authorization": _has_authorization_header(request),
                }
            )
            (self.logs / "provider.jsonl").write_text(
                "\n".join(
                    json.dumps(item, ensure_ascii=False) for item in self._requests
                )
                + "\n",
                encoding="utf-8",
            )
        # Hold the NEXT request while the teacher performs an in-flight close or
        # a real sleep. Bounded so a forgotten control file cannot hang forever,
        # and released promptly by ``stop()``.
        deadline = time.monotonic() + 900
        while (
            self._hold_requested()
            and not self._stop_event.is_set()
            and time.monotonic() < deadline
        ):
            time.sleep(0.2)
        if kind == "adapt":
            return self._w3.envelope(ADAPT_OUT)
        if kind == "other":
            return self._w3.envelope(OTHER_OUT)
        return self._w3.envelope(SPLIT_OUT)

    @property
    def port(self) -> int:
        return self.server.port

    def counts(self) -> dict:
        with self._lock:
            return dict(self._seen)

    def stop(self) -> None:
        self._stop_event.set()
        self.server.stop()
        self._listener_stopped = True

    def closed(self) -> bool:
        return self._listener_stopped


# ---------------------------------------------------------------------------
# Session preparation
# ---------------------------------------------------------------------------


def _new_session_root() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return REPO_ROOT / "build" / "desktop-d2" / f"manual-ai-{stamp}-{secrets.token_hex(3)}"


def prepare_session(
    root: Path,
    *,
    clone_from_data: Path,
    plan_id: str,
) -> dict:
    root = root.resolve()
    clone_source = Path(clone_from_data).resolve() / "kindergarten.db"
    source_root = Path(clone_from_data).resolve().parent
    _guard_new_session_root(root, clone_from_data)
    (root / "data").mkdir(parents=True, exist_ok=False)
    (root / "localappdata").mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    (root / "control").mkdir(parents=True, exist_ok=True)

    clone = clone_sqlite(clone_source, root / "data" / "kindergarten.db")
    plan = read_plan_facts(root / "data" / "kindergarten.db", plan_id)
    if not plan.get("found"):
        raise RuntimeError(f"克隆副本缺少目标计划 {plan_id}")
    marker = {
        "manual_root": str(root),
        "data": str(root / "data"),
        "source_root": str(source_root),
        "source_data": str(source_root / "data"),
        "session_id": secrets.token_hex(8),
        "created_at": _now(),
        "clone_source_data": str(clone_from_data),
        "plan_id": plan_id,
    }
    _write_json(root / ".w6-manual-session.json", marker)
    return {"marker": marker, "clone": clone, "plan": plan}


def prepare_ai_config(root: Path) -> dict:
    """Prepare a synthetic AI config on the CLONE (no task is created)."""
    from app.local import ai_config_service
    from app.local.runtime import LocalRuntime

    root = root.resolve()
    data = root / "data"
    credential_root = root / "localappdata" / "KindergartenManager" / "credentials"
    runtime = LocalRuntime(data, credential_root=credential_root)
    try:
        runtime.prepare()
        session = runtime.session()
        try:
            from sqlalchemy import text

            version = session.execute(
                text("SELECT current_config_version FROM local_ai_state")
            ).scalar() or 0
            ai_config_service.patch_config(
                session,
                expected_ai_config_version=int(version),
                base_url="https://api.example.com/v1",
                model="w6-manual-synthetic",
                secret="w6-manual-synthetic-secret",
                secret_provided=True,
                request_id=str(__import__("uuid").uuid4()),
                credential_root=credential_root,
            )
            config = ai_config_service.get_config(
                session, credential_root=credential_root
            )
            if hasattr(config, "to_dict"):
                config_dict = config.to_dict()
            else:
                from dataclasses import asdict, is_dataclass

                config_dict = asdict(config) if is_dataclass(config) else dict(config)
            return {
                "prepared": True,
                "ai_config_version": config_dict.get("ai_config_version"),
                "configured": config_dict.get("configured"),
                "ready": config_dict.get("ready"),
                "reason": config_dict.get("reason"),
                "note": "控制器准备的合成配置；未发起/采用任何任务",
            }
        finally:
            session.close()
    finally:
        runtime.dispose()


# ---------------------------------------------------------------------------
# Launch / verify
# ---------------------------------------------------------------------------


def _entry_program(args) -> tuple[list[str], str, Path, Path | None]:
    if args.package_dir:
        package_dir = Path(args.package_dir).resolve()
        exe = package_dir / f"{package_dir.name}.exe"
        if not exe.is_file():
            raise RuntimeError(f"人工包可执行文件缺失: {exe}")
        return [str(exe)], "package", package_dir, exe
    python = Path(args.python)
    if not python.is_file():
        raise RuntimeError(f"解释器缺失: {python}")
    return (
        [str(python), str(HERE / "d2_manual_ai_main.py")],
        "source",
        HERE,
        None,
    )


def _base_env(root: Path, kind: str) -> dict:
    env = dict(os.environ)
    env["LOCALAPPDATA"] = str(root / "localappdata")
    env["APP_DISABLE_DOTENV"] = "1"
    for key in list(env):
        if key.startswith("KGM_"):
            env.pop(key, None)
    if kind == "package":
        from verify_d2_w6_common import sanitize_package_env

        env = sanitize_package_env(env)
        env["LOCALAPPDATA"] = str(root / "localappdata")
        env["APP_DISABLE_DOTENV"] = "1"
    return env


def run_session(args, checks: dict, report: dict) -> int:
    root = Path(args.session_root).resolve() if args.session_root else _new_session_root()
    report["manual_root"] = str(root)
    prepared = prepare_session(
        root,
        clone_from_data=Path(args.clone_from_data).resolve(),
        plan_id=args.plan_id,
    )
    report["clone"] = prepared["clone"]
    report["plan_before"] = prepared["plan"]
    if not prepared["plan"].get("raw_present"):
        report["note_raw_missing"] = "克隆计划的原始教案为空；人工拆分前需先填写原文"

    config = prepare_ai_config(root)
    report["ai_config_preparation"] = config

    provider = ManualProvider(root)
    entry_stdout = None
    entry_stderr = None
    try:
        program, kind, cwd, exe = _entry_program(args)
        env = _base_env(root, kind)
        entry_args = [
            "--manual-root",
            str(root),
            "--data",
            str(root / "data"),
            "--provider-port",
            str(provider.port),
            "--provider-ca",
            str(provider.ca_pem),
            "--provider-ip",
            "127.0.0.1",
        ]
        # Explicit protected roots (never guessed by the entry, so the same
        # guard works in source and frozen).
        from app.local.sqlite import default_data_dir

        for forbidden in (ORIGINAL_MANUAL_ROOT, default_data_dir()):
            entry_args.extend(["--forbid-root", str(forbidden)])
        if kind == "source":
            entry_args.extend(["--frontend", str(Path(args.frontend_dir).resolve())])
        if args.mode == "smoke":
            entry_args.extend(["--smoke", "--smoke-date", args.date])
        elif args.mode == "dom":
            entry_args.extend(["--dom-check", "--dom-date", args.dom_date])
        entry_stdout = (root / "logs" / "entry.stdout.log").open("wb")
        entry_stderr = (root / "logs" / "entry.stderr.log").open("wb")
        started = time.time()
        try:
            process = subprocess.Popen(
                [*program, *entry_args],
                cwd=str(cwd),
                env=env,
                stdout=entry_stdout,
                stderr=entry_stderr,
            )
        except Exception as exc:  # noqa: BLE001 - close files + report, no leak
            report["entry_launch_error"] = f"{type(exc).__name__}: {exc}"
            checks["entry_launched"] = False
            _write_json(root / "result.json", report)
            return 2
        checks["entry_launched"] = True
        report["entry"] = {
            "kind": kind,
            "program": program,
            "pid": process.pid,
            "cwd": str(cwd),
            "mode": args.mode,
        }
        if exe is not None:
            report["package"] = {
                "dir": str(exe.parent),
                "exe_sha256": _sha(exe),
                "exe_bytes": exe.stat().st_size,
                **_tree_manifest(exe.parent),
            }
        manifest = {
            "created_at": _now(),
            "mode": args.mode,
            "manual_root": str(root),
            "data": str(root / "data"),
            "credential_root": str(root / "localappdata" / "KindergartenManager" / "credentials"),
            "source_root": prepared["marker"]["source_root"],
            "source_data": prepared["marker"]["source_data"],
            "clone": prepared["clone"],
            "plan": prepared["plan"],
            "ai_config_preparation": config,
            "provider": {
                "host": "api.example.com",
                "ip": "127.0.0.1",
                "port": provider.port,
                "ca": str(provider.ca_pem),
            },
            "entry": report["entry"],
            "package": report.get("package"),
            "control": {
                "next": str(root / "control" / "next.txt"),
                "instructions": "hold=挂起下一请求；release=释放",
            },
        }
        _write_json(root / "ready.json", manifest)
        report["ready_manifest"] = str(root / "ready.json")

        if args.mode in ("smoke", "dom"):
            # Only automated modes get a bounded wait; a stuck close/task must
            # fail explicitly instead of hanging the controller. Human mode
            # waits indefinitely for the teacher.
            try:
                exit_code = process.wait(timeout=args.smoke_timeout)
                timed_out = False
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    process.kill()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    exit_code = process.wait(timeout=30)
                except Exception:  # noqa: BLE001
                    exit_code = -1
            report["smoke_timed_out"] = timed_out
            checks["smoke_within_deadline"] = not timed_out
        else:
            exit_code = process.wait()
        report["elapsed_seconds"] = round(time.time() - started, 3)
        report["entry_exit_code"] = exit_code
    finally:
        provider.stop()
        for handle in (entry_stdout, entry_stderr):
            if handle is not None:
                try:
                    handle.close()
                except Exception:  # noqa: BLE001
                    pass

    counts = provider.counts()
    report.setdefault("provider", {})["listener_stopped"] = provider.closed()
    report["provider"] = {
        "counts": counts,
        "log": str(root / "logs" / "provider.jsonl"),
        "listener_stopped": provider.closed(),
    }
    exit_report_path = root / "logs" / "entry-exit.json"
    entry_report = {}
    if exit_report_path.is_file():
        try:
            entry_report = json.loads(exit_report_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            entry_report = {}
    report["entry_report"] = entry_report
    checks["provider_listener_stopped"] = provider.closed()
    if args.mode == "smoke":
        smoke = entry_report.get("smoke") or {}
        checks["smoke_exit_zero"] = report["entry_exit_code"] == 0
        checks["smoke_worker_confirmed"] = bool(entry_report.get("worker_exit_confirmed"))
        checks["smoke_server_stopped"] = bool(entry_report.get("server_stopped"))
        for kind in ("split", "adapt", "other"):
            checks[f"smoke_{kind}_request"] = counts.get(kind, 0) >= 1
            checks[f"smoke_{kind}_candidate"] = bool(
                (smoke.get(kind) or {}).get("candidate_id")
            )
        report["smoke"] = smoke
    elif args.mode == "dom":
        dom = entry_report.get("dom_check") or {}
        report["dom_check"] = dom
        checks["dom_exit_zero"] = report["entry_exit_code"] == 0
        checks["dom_worker_confirmed"] = bool(entry_report.get("worker_exit_confirmed"))
        checks["dom_server_stopped"] = bool(entry_report.get("server_stopped"))
        checks["dom_preview_enabled_after_edit"] = (
            dom.get("preview_disabled_after_edit") is False
        )
        checks["dom_cancel_enabled_after_edit"] = (
            dom.get("cancel_disabled_after_edit") is False
        )
        checks["dom_adopt_enabled_after_compare"] = (
            dom.get("adopt_disabled_after_compare") is False
        )
        checks["dom_adopted"] = dom.get("adopted") is True
        checks["dom_cancel_closed"] = dom.get("cancel_closed") is True
        checks["dom_body_clean_before_compare"] = dom.get("body_dirty_after_edit") is False
        checks["dom_body_version_unchanged"] = (
            dom.get("body_version_after_edit") == dom.get("body_version_saved")
        )
        checks["dom_no_extra_version_on_cancel"] = (
            dom.get("version_after_cancel") == dom.get("version_after_adopt")
        )
        checks["dom_x_close_blocked"] = dom.get("x_close_blocked") is True
        checks["dom_x_close_kept_text"] = dom.get("x_close_kept_text") is True
        # Full exit path: a dirty candidate blocks the host close, the window
        # stays and is not left frozen/locked, the native cancel closes it, and
        # the entry then exits cleanly (worker/service/lock).
        checks["dom_close_blocked_by_draft"] = dom.get("close_blocked_by_draft") is True
        checks["dom_close_window_still_open"] = dom.get("close_window_still_open") is True
        close_state = dom.get("close_state_after_block")
        parsed_state = {}
        if isinstance(close_state, str):
            try:
                parsed_state = json.loads(close_state)
            except Exception:  # noqa: BLE001
                parsed_state = {}
        checks["dom_close_state_structure"] = (
            isinstance(parsed_state, dict) and "locked" in parsed_state
        )
        checks["dom_close_not_locked"] = parsed_state.get("locked") is False
        checks["dom_exit_cancel_closed"] = dom.get("exit_cancel_closed") is True
        checks["dom_lock_released"] = entry_report.get("runtime_lock_released") is True
        # Only the split trigger may reach the provider; preview/adopt never do.
        checks["dom_provider_split"] = counts.get("split", 0) == 1
        checks["dom_provider_no_other_ai"] = (
            counts.get("adapt", 0) == 0 and counts.get("other", 0) == 0
        )
        # Read the adopted body/baseline straight from the clone database.
        plan_id = dom.get("plan_id")
        if plan_id:
            plan = read_plan_facts(root / "data" / "kindergarten.db", plan_id)
            report["dom_plan"] = plan
            checks["dom_plan_process_matches"] = (
                plan.get("process") == dom.get("edited_process")
            )
            checks["dom_plan_baseline_is_original"] = plan.get("split_baseline") == {
                "group_activity_process": dom.get("baseline_process")
            }
            checks["dom_baseline_differs_from_body"] = (
                plan.get("split_baseline", {}).get("group_activity_process")
                != plan.get("process")
            )
        else:
            checks["dom_plan_process_matches"] = False
            checks["dom_plan_baseline_is_original"] = False
            checks["dom_baseline_differs_from_body"] = False
    else:
        checks["human_session_ended"] = report["entry_exit_code"] == 0
        checks["human_worker_confirmed"] = bool(
            entry_report.get("worker_exit_confirmed")
        )
        report["note_human"] = (
            "人工会话已结束；本结果只记录运行事实，不代表用户验收通过。"
        )
    _write_json(root / "result.json", report)
    return 0 if all(checks.values()) else 3


OLD_MANIFEST_SHA256 = "84fbb22f66f14fbbffc5c6fe4c63810855c0fbbbc68571c608ff902f285b1f1d"
OLD_FILE_COUNT = 182
REQUIRED_MODULES = (
    "d1_main",
    "d1_host_api",
    "d1_server",
    "d1_paths",
    "app.local.ai_executor",
    "app.local.ai_transport",
    "app.local.ai_task_service",
    "app.local.export_service",
    "app.local.daily_plan_service",
    "app.local.prompt_bundles",
    "app.services.word_export_docx",
    "app.services.word_export_mapping",
)


def _archive_module_fingerprints(exe: Path, workdir: Path) -> dict[str, str | None]:
    """All production modules from the REAL archive (PYZ) of one EXE."""
    import marshal

    import d2_same_origin
    from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader

    reader = CArchiveReader(str(exe))
    result: dict[str, str | None] = {}
    if "PYZ.pyz" not in reader.toc:
        return result
    pyz_path = workdir / f"{exe.stem}-PYZ.pyz"
    pyz_path.write_bytes(reader.extract("PYZ.pyz"))
    archive = ZlibArchiveReader(str(pyz_path))
    for name in archive.toc:
        # Cover the whole production archive set (host d0_*/d1_*/d2_* and app.*,
        # including the app package itself).
        if not (name == "app" or name.startswith(("app.", "d0_", "d1_", "d2_"))):
            continue
        try:
            code = archive.extract(name)
            result[name] = d2_same_origin.fingerprint_code(code)
        except Exception:  # noqa: BLE001 - recorded as unavailable
            result[name] = None
    return result


def _archive_entry_fingerprint(exe: Path, entry_name: str) -> str | None:
    import marshal

    import d2_same_origin
    from PyInstaller.archive.readers import CArchiveReader

    reader = CArchiveReader(str(exe))
    if entry_name not in reader.toc:
        return None
    data = reader.extract(entry_name)
    return d2_same_origin.fingerprint_code(marshal.loads(bytes(data)))


def fingerprint_package(args, checks: dict, report: dict) -> int:
    import d2_same_origin

    package_dir = Path(args.package_dir).resolve()
    exe = package_dir / f"{package_dir.name}.exe"
    if not exe.is_file():
        raise RuntimeError(f"人工包可执行文件缺失: {exe}")
    report["package"] = {"dir": str(package_dir), "exe_sha256": _sha(exe)}
    workdir = Path(tempfile.mkdtemp(prefix="kgm-manual-ai-fp-"))
    out = workdir / "fingerprints.json"
    env = _base_env(package_dir.parent, "package")
    process = subprocess.run(
        [str(exe), "--fingerprint-out", str(out)],
        cwd=str(package_dir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=180,
    )
    report["fingerprint_exit"] = process.returncode
    checks["fingerprint_exit_zero"] = process.returncode == 0
    frozen = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else {}

    new_modules = _archive_module_fingerprints(exe, workdir)
    old_modules = _archive_module_fingerprints(ORIGINAL_PACKAGE / "KGNext-D2Verify.exe", workdir)
    new_entry = _archive_entry_fingerprint(exe, "d2_manual_ai_main")
    old_entry = _archive_entry_fingerprint(
        ORIGINAL_PACKAGE / "KGNext-D2Verify.exe", "d1_main"
    )
    source_entry_new = d2_same_origin.fingerprint_source(HERE / "d2_manual_ai_main.py")
    source_entry_old = d2_same_origin.fingerprint_source(HERE / "d1_main.py")

    names = sorted(set(new_modules) | set(REQUIRED_MODULES))
    unavailable: list[str] = []
    new_vs_source: dict[str, str] = {}
    for name in names:
        if name == "d2_manual_ai_main":
            continue
        source = d2_same_origin.fingerprint_imported_module(name)
        frozen_fp = new_modules.get(name)
        if source.get("status") != "ok" or not frozen_fp:
            unavailable.append(name)
        elif frozen_fp != source.get("sha256"):
            new_vs_source[name] = frozen_fp
    report["same_origin"] = {
        "modules": names,
        "unavailable": unavailable,
        "new_vs_source_mismatch": new_vs_source,
        "new_entry": new_entry,
        "new_entry_source": source_entry_new,
        "old_entry": old_entry,
        "old_entry_source": source_entry_old,
    }
    checks["same_origin_new_vs_source"] = not unavailable and not new_vs_source
    checks["same_origin_required_present"] = all(
        name in new_modules and new_modules.get(name) for name in REQUIRED_MODULES
    )
    checks["same_origin_module_count"] = len(names) >= 54
    checks["archive_entry_matches_source"] = new_entry == source_entry_new
    checks["old_entry_matches_source"] = old_entry == source_entry_old

    # Old vs new production modules (real archive code, not a self-selected set).
    shared = sorted(set(old_modules) & set(new_modules))
    old_new_mismatch = [
        name for name in shared if old_modules.get(name) != new_modules.get(name)
    ]
    report["old_vs_new"] = {
        "shared": len(shared),
        "mismatch": old_new_mismatch,
        "old_only": sorted(set(old_modules) - set(new_modules)),
        "new_only": sorted(set(new_modules) - set(old_modules)),
    }
    checks["old_vs_new_shared_modules"] = len(shared) >= 54
    checks["old_vs_new_all_match"] = not old_new_mismatch
    checks["old_vs_new_no_missing"] = not report["old_vs_new"]["old_only"]
    checks["old_production_module_count"] = len(old_modules) == 54
    # The old REAL entry (d1_main, stored in the CArchive) must equal the new
    # package's imported d1_main module and the source.
    new_d1_main = new_modules.get("d1_main")
    checks["old_entry_matches_new_module"] = (
        old_entry is not None
        and new_d1_main is not None
        and old_entry == new_d1_main
    )

    # Bundled resources equal the existing build resources.
    def same_tree(a: Path, b: Path) -> bool:
        if not a.is_dir() or not b.is_dir():
            return False
        return {
            str(p.relative_to(a)): _sha(p) for p in a.rglob("*") if p.is_file()
        } == {str(p.relative_to(b)): _sha(p) for p in b.rglob("*") if p.is_file()}

    internal = package_dir / "_internal"
    base = internal if internal.is_dir() else package_dir
    checks["frontend_resources_match"] = same_tree(
        base / "frontend", Path(args.frontend_dir).resolve()
    )
    checks["templates_resources_match"] = same_tree(
        base / "app" / "assets" / "word_templates",
        BACKEND / "app" / "assets" / "word_templates",
    )
    checks["migrations_resources_match"] = same_tree(
        base / "migrations_local", BACKEND / "migrations_local"
    )
    checks["alembic_resource_match"] = (
        (base / "alembic-local.ini").is_file()
        and _sha(base / "alembic-local.ini") == _sha(BACKEND / "alembic-local.ini")
    )

    old_manifest = _tree_manifest(ORIGINAL_PACKAGE)
    report["old_package"] = {
        "dir": str(ORIGINAL_PACKAGE),
        **old_manifest,
        "exe_sha256": _sha(ORIGINAL_PACKAGE / "KGNext-D2Verify.exe"),
    }
    checks["old_package_unchanged"] = (
        old_manifest["count"] == OLD_FILE_COUNT
        and old_manifest["manifest_sha256"] == OLD_MANIFEST_SHA256
        and report["old_package"]["exe_sha256"]
        == "56346c0ac1d874bbf00e947739a40c005f4a2a611b20d6fabf1a7d35a89fafb2"
    )
    return 0 if all(checks.values()) else 3


def main() -> int:
    parser = argparse.ArgumentParser(description="W6 本机合成 AI 人工验收控制器")
    parser.add_argument("--mode", choices=["human", "smoke", "dom"], default="human")
    parser.add_argument("--session-root", default=None)
    parser.add_argument(
        "--frontend-dir",
        default=str(FRONTEND),
        help="用于核对包内前端资源的构建目录（默认既有 build/desktop-d2/frontend）",
    )
    parser.add_argument("--dom-date", default="2026-10-20")
    parser.add_argument(
        "--clone-from-data",
        default=str(ORIGINAL_MANUAL_ROOT / "data"),
        help="只读克隆源数据目录（含 kindergarten.db）",
    )
    parser.add_argument("--plan-id", default=DEFAULT_PLAN_ID)
    parser.add_argument("--date", default="2026-10-19")
    parser.add_argument(
        "--smoke-timeout",
        type=float,
        default=300.0,
        help="仅 smoke 的控制器等待上限（human 不设限）",
    )
    parser.add_argument("--python", default=str(PYTHON_DEFAULT))
    parser.add_argument("--package-dir", default=None, help="独立人工包的目录")
    parser.add_argument("--out", default=None)
    parser.add_argument("--fingerprint-package", action="store_true")
    args = parser.parse_args()

    checks: dict = {}
    report: dict = {"ok": False, "checks": checks, "created_at": _now()}
    try:
        if args.fingerprint_package:
            if not args.package_dir:
                raise RuntimeError("--fingerprint-package 需要 --package-dir")
            rc = fingerprint_package(args, checks, report)
        else:
            rc = run_session(args, checks, report)
        report["failed_checks"] = sorted(k for k, v in checks.items() if not v)
        report["ok"] = bool(checks) and all(checks.values())
        return 0 if report["ok"] else 3
    except Exception as exc:  # noqa: BLE001
        import traceback

        report["script_failure"] = traceback.format_exc()
        report["script_failure_type"] = type(exc).__name__
        report["ok"] = False
        return 2
    finally:
        out = Path(args.out) if args.out else None
        if out is not None:
            _write_json(out, report)


if __name__ == "__main__":
    sys.exit(main())
