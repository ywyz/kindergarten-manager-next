"""B3 restored-target AI cold start: queued task is paused, never claimed/SENT."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import traceback
from collections import Counter
from pathlib import Path
from typing import Any

from maintenance_lifecycle import LifecycleManager


def _db_dump(db_path: str | Path) -> dict[str, Any]:
    """Full table rows plus the real SQLite primary keys (never guessed)."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        tables = [
            str(row[0])
            for row in con.execute(
                "select name from sqlite_master where type='table' order by name"
            )
            if not str(row[0]).startswith("sqlite_")
            and str(row[0]) != "local_alembic_version"
        ]
        rows = {
            table: [dict(row) for row in con.execute(f'select * from "{table}"')]
            for table in tables
        }
        primary_keys = {
            table: tuple(
                str(row[1])
                for row in con.execute(f'pragma table_info("{table}")')
                if int(row[5]) > 0
            )
            for table in tables
        }
        return {"tables": rows, "primary_keys": primary_keys}
    finally:
        con.close()


def _canonical_row(row: dict[str, Any]) -> str:
    return json.dumps(row, sort_keys=True, ensure_ascii=False, default=str)


def _pk_tuple(row: dict[str, Any], columns: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(str(row.get(column)) for column in columns)


def _diff_dumps(
    source: dict[str, Any],
    target: dict[str, Any],
    live_task_id: str,
) -> list[dict[str, Any]]:
    """Compare full row multiplicities; only the designated task row may differ.

    Composite primary keys (for example calendar (revision_id, date)) are taken
    from SQLite itself.  A guessed single column must never collapse two rows.
    """
    allowed = {"status", "reason", "runtime_meta_json", "updated_at"}
    source_tables = dict(source["tables"])
    target_tables = dict(target["tables"])
    primary_keys = dict(source["primary_keys"])
    diffs: list[dict[str, Any]] = []
    for table in sorted(set(source_tables) | set(target_tables)):
        if table not in source_tables or table not in target_tables:
            diffs.append({"table": table, "kind": "table_set"})
            continue
        before_rows = source_tables[table]
        after_rows = target_tables[table]
        if table == "local_ai_tasks":
            key_columns = primary_keys.get(table) or ("id",)
            before_map = {
                _pk_tuple(row, key_columns): row for row in before_rows
            }
            after_map = {
                _pk_tuple(row, key_columns): row for row in after_rows
            }
            if set(before_map) != set(after_map):
                diffs.append({"table": table, "kind": "row_set"})
                continue
            for key, before in before_map.items():
                after = after_map[key]
                row_id = key[0] if key else ""
                for column in before:
                    if row_id == live_task_id and column in allowed:
                        continue
                    if before[column] != after.get(column):
                        diffs.append(
                            {
                                "table": table,
                                "id": row_id,
                                "column": column,
                                "before": before[column],
                                "after": after.get(column),
                            }
                        )
            continue
        from collections import Counter

        before_multiplicity = Counter(_canonical_row(row) for row in before_rows)
        after_multiplicity = Counter(_canonical_row(row) for row in after_rows)
        if before_multiplicity != after_multiplicity:
            diffs.append({"table": table, "kind": "row_multiset"})
    return diffs


def run_ai_cold_driver(
    window,
    host_api,
    runtime,
    lifecycle: LifecycleManager,
    config: dict[str, Any],
    summary: dict[str, Any],
    checks: dict[str, Any],
    source: dict[str, Any],
    target_pre: dict[str, Any],
    out_path: Path,
    finished: threading.Event,
    dialog_stub=None,
    dialog_calls=None,
) -> None:
    import d1_main
    from maintenance_source_verify import (
        _cleanup_unswitched_maintenance,
        _destroy_owned_windows,
        _js_visible,
        _write_summary,
    )

    driver = d1_main.JsDriver(window)
    destroy_ok = False
    executor = None
    try:
        driver.wait_until(
            "Boolean(window.__d1App && window.__d1App.state() === 'ready')",
            what="AI 冷启动工作台",
            timeout=60,
        )
        checks["ai_cold_new_page_ready"] = True
        con = sqlite3.connect(f"file:{runtime.db_path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            task_row = con.execute(
                "select * from local_ai_tasks where status = 'pending'"
                " order by created_at limit 1"
            ).fetchone()
            if task_row is None:
                raise AssertionError("目标档案缺少 pending AI 任务基线")
            task = dict(task_row)
            live_task_id = str(task.get("id") or "")
            executions_before = con.execute(
                "select count(*) from local_ai_executions where task_id = ?",
                (live_task_id,),
            ).fetchone()[0]
        finally:
            con.close()
        assert live_task_id
        assert executions_before == 0
        checks["ai_cold_source_task"] = {
            key: task.get(key)
            for key in (
                "id",
                "status",
                "reason",
                "generation",
                "current_execution_id",
                "runtime_meta_json",
            )
        }
        checks["ai_cold_source_task_status"] = task.get("status")
        checks["ai_cold_source_task_reason"] = task.get("reason")
        checks["ai_cold_source_task_pending"] = (
            task.get("status") == "pending" and task.get("reason") is None
        )
        assert checks["ai_cold_source_task_pending"]
        baseline_dump = _db_dump(runtime.db_path)
        baseline_resources = __import__(
            "tests.local.backup_fixture_support", fromlist=["resource_fingerprint"]
        ).resource_fingerprint(config["data_dir"])
        checks["ai_cold_baseline_captured"] = True

        events: list[dict[str, Any]] = []

        def _record(name, claim, info=None):
            events.append(
                {
                    "name": str(name),
                    "execution_id": getattr(claim, "execution_id", None),
                    "task_id": getattr(claim, "task_id", None),
                    "info": dict(info or {}),
                }
            )

        from app.local.ai_executor import AiExecutor

        executor = AiExecutor(runtime, on_event=_record)
        started = executor.start()
        checks["ai_cold_executor_started"] = bool(started)
        assert started, "真实 AiExecutor 冷启动失败"
        time.sleep(1.0)
        snapshot = executor.active_snapshot()
        checks["ai_cold_executor_snapshot"] = snapshot
        checks["ai_cold_executor_idle"] = not any(
            bool(snapshot.get(key))
            for key in (
                "live",
                "in_flight",
                "attempt_in_flight",
                "unconfirmed",
                "pending_persist",
            )
        )
        assert checks["ai_cold_executor_idle"], snapshot

        names = Counter(str(item.get("name")) for item in events)
        checks["ai_cold_event_names"] = dict(names)
        checks["ai_cold_no_claim_event"] = names.get("claimed", 0) == 0
        checks["ai_cold_no_send_event"] = names.get("sent", 0) == 0
        checks["ai_cold_no_provider_event"] = all(
            names.get(name, 0) == 0
            for name in ("child_started", "ready", "marked", "result_received")
        )
        assert checks["ai_cold_no_claim_event"], dict(names)
        assert checks["ai_cold_no_send_event"], dict(names)
        assert checks["ai_cold_no_provider_event"], dict(names)

        con = sqlite3.connect(f"file:{runtime.db_path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            task_row = con.execute(
                "select * from local_ai_tasks where id = ?", (live_task_id,)
            ).fetchone()
            executions = con.execute(
                "select * from local_ai_executions where task_id = ?",
                (live_task_id,),
            ).fetchall()
        finally:
            con.close()
        assert task_row is not None
        target_task = dict(task_row)
        checks["ai_cold_target_task"] = {
            key: target_task.get(key)
            for key in (
                "id",
                "status",
                "reason",
                "generation",
                "current_execution_id",
                "runtime_meta_json",
            )
        }
        checks["ai_cold_task_paused"] = (
            target_task.get("status") == "paused"
            and target_task.get("generation") == 0
            and target_task.get("current_execution_id") is None
        )
        meta = json.loads(str(target_task.get("runtime_meta_json") or "{}"))
        checks["ai_cold_target_meta"] = meta
        checks["ai_cold_target_meta_exact"] = bool(
            meta.get("processing_certainty") == "not_sent"
            and meta.get("permit_revoked_at")
            and meta.get("user_stop_requested") is False
            and meta.get("next_attempt_at") is None
        )
        checks["ai_cold_task_reason_restart"] = (
            target_task.get("reason") == "restart"
        )
        changed_columns = sorted(
            column
            for column in target_task
            if task.get(column) != target_task.get(column)
        )
        checks["ai_cold_changed_columns"] = changed_columns
        checks["ai_cold_only_expected_columns"] = set(changed_columns) == {
            "status",
            "reason",
            "runtime_meta_json",
            "updated_at",
        }
        checks["ai_cold_no_execution"] = len(executions) == 0
        assert checks["ai_cold_task_paused"], target_task
        assert checks["ai_cold_target_meta_exact"], meta
        assert checks["ai_cold_task_reason_restart"], target_task
        assert checks["ai_cold_only_expected_columns"], changed_columns
        assert checks["ai_cold_no_execution"]

        target_dump = _db_dump(runtime.db_path)
        diffs = _diff_dumps(baseline_dump, target_dump, live_task_id)
        checks["ai_cold_delta"] = diffs
        checks["ai_cold_only_expected_delta"] = diffs == []
        assert checks["ai_cold_only_expected_delta"], diffs
        from tests.local import backup_fixture_support as fixture

        target_resources = fixture.resource_fingerprint(config["data_dir"])
        checks["ai_cold_resources_unchanged"] = (
            target_resources.get("fingerprint_sha256")
            == baseline_resources.get("fingerprint_sha256")
        )
        checks["resources_equal"] = checks["ai_cold_resources_unchanged"]
        assert checks["ai_cold_resources_unchanged"]

        disposed = executor.dispose()
        checks["ai_cold_executor_disposed"] = bool(disposed)
        assert checks["ai_cold_executor_disposed"]
        executor = None
        destroy_ok = _destroy_owned_windows([window])
        checks["driver_destroy_confirmed"] = destroy_ok
    except Exception as exc:  # noqa: BLE001
        checks["driver_error"] = f"{type(exc).__name__}: {exc}"
        checks["driver_trace"] = traceback.format_exc()
        summary["ok"] = False
        try:
            checks["failure_body_text"] = driver.eval("document.body.innerText")
            if dialog_calls is not None:
                checks["failure_dialog_calls"] = list(dialog_calls)
        except Exception:  # noqa: BLE001
            pass
        _write_summary(summary, out_path)
        checks["driver_cleanup_cancelled"] = _cleanup_unswitched_maintenance(host_api)
        try:
            if not host_api._maintenance_busy_probe():
                host_api._request_retire_destroy()
        except Exception:  # noqa: BLE001
            pass
        if executor is not None:
            try:
                checks["ai_cold_executor_disposed"] = bool(executor.dispose())
            except Exception:  # noqa: BLE001
                checks["ai_cold_executor_disposed"] = False
        destroy_ok = _destroy_owned_windows([window], force=True)
        checks["driver_destroy_confirmed"] = destroy_ok
    finally:
        if destroy_ok:
            finished.set()
