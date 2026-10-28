"""Field-by-field 0005 -> 0006 old-row preservation verification (source run).

Builds the existing synthetic 0005 fixture, snapshots it, runs the real
WebView2 observation window (which performs the cold upgrade), and compares
every pre-existing row/column by primary key. Only the new source columns
documented by migration 0006 may be backfilled; every old value must survive
byte-for-byte. It also verifies the pre-upgrade backup + manifest, integrity,
foreign keys, a second open (no re-migration/replay) and the exact migration
row count.

Usage:
    python verify_observation_old_upgrade.py --data-dir DIR --output-dir DIR
        [--frontend DIR] [--timeout 900]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
BACKEND_ROOT = REPO_ROOT / "backend"
for entry in (str(HERE), str(BACKEND_ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from tests.local.test_observation_migration import _build_0005  # noqa: E402

PYTHON_DEFAULT = HERE / ".venv-d1" / "Scripts" / "python.exe"
FRONTEND_DEFAULT = REPO_ROOT / "build" / "desktop-e14-r02" / "frontend"
SOURCE_REVISION = "20261023_0005_local_history"
TARGET_REVISION = "20261025_0006_local_game_observations"

# Tables whose old row count must not change during the window run. Only
# operation/audit append tables may legitimately gain rows from the new
# synthetic observations created by the window driver.
APPEND_ONLY_TABLES = {
    "local_operation_records",
    "local_ai_operations",
    "local_config_operations",
}

# The runtime prompt sync (existing D2 behaviour, not 0006) may add default
# bundles/observation seeds and advance a daily head pointer. Old daily prompt
# version rows and bundle rows themselves must remain unchanged.
RUNTIME_PROMPT_TABLES = {
    "local_prompt_bundles",
    "local_personal_prompt_versions",
    "local_personal_prompt_heads",
}
RUNTIME_PROMPT_MUTABLE_COLUMNS = {
    ("local_personal_prompt_heads", "latest_default_revision"),
    ("local_personal_prompt_heads", "updated_at"),
}
SPECIAL_TABLES = {"local_alembic_version"}

# New columns introduced by 0006 and their only permitted backfill source.
BACKFILL_RULES: dict[str, dict[str, str | None]] = {
    "local_ai_inputs": {
        "profile_id": "daily_plan_creator",
        "source_kind": "daily_plan",
        "source_id": "daily_plan_id",
        "observation_id": None,
        "source_revision": None,
    },
    "local_ai_tasks": {
        "source_kind": "daily_plan",
        "source_id": "daily_plan_id",
        "observation_id": None,
    },
    "local_ai_executions": {
        "source_kind": "daily_plan",
        "source_id": "daily_plan_id",
        "observation_id": None,
    },
    "local_ai_candidates": {
        "profile_id": "execution_profile",
        "source_kind": "daily_plan",
        "source_id": "daily_plan_id",
        "observation_id": None,
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _tables(connection: sqlite3.Connection) -> list[str]:
    return [
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]


def _columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]


def _primary_key(connection: sqlite3.Connection, table: str) -> list[str]:
    rows = [
        row
        for row in connection.execute(f'PRAGMA table_info("{table}")')
        if row[5]
    ]
    rows.sort(key=lambda row: row[5])
    return [row[1] for row in rows]


def _rows(
    connection: sqlite3.Connection, table: str, columns: list[str], key: list[str]
) -> dict[tuple, dict]:
    selected = ", ".join(f'"{name}"' for name in columns)
    result: dict[tuple, dict] = {}
    for row in connection.execute(f'SELECT {selected} FROM "{table}"'):
        values = {name: row[name] for name in columns}
        if key:
            marker = tuple(values[name] for name in key)
        else:
            marker = tuple(values[name] for name in columns)
        result[marker] = values
    return result


def _row_key(values: dict, key: list[str]) -> tuple:
    if key:
        return tuple(values[name] for name in key)
    return tuple(sorted(values.items()))


def _lookup(connection: sqlite3.Connection, table: str, column: str, marker, target: str):
    row = connection.execute(
        f'SELECT "{target}" FROM "{table}" WHERE "{column}" = ?', (marker,)
    ).fetchone()
    return None if row is None else row[0]


def _validate_backfill(
    table: str,
    row: dict,
    after: sqlite3.Connection,
    rule: dict[str, str | None],
) -> list[str]:
    errors: list[str] = []
    for column, expected in rule.items():
        actual = row.get(column)
        if expected is None:
            if actual is not None:
                errors.append(f"{table}.{column} expected NULL, got {actual!r}")
            continue
        if expected == "daily_plan_creator":
            creator = _lookup(
                after, "local_daily_plans", "id", row.get("daily_plan_id"), "creator_id"
            )
            if actual != creator:
                errors.append(
                    f"{table}.profile_id {actual!r} != plan creator {creator!r}"
                )
        elif expected == "execution_profile":
            profile = _lookup(
                after, "local_ai_executions", "id", row.get("execution_id"), "profile_id"
            )
            if actual != profile:
                errors.append(
                    f"{table}.profile_id {actual!r} != execution profile {profile!r}"
                )
        elif expected == "daily_plan_id":
            if actual != row.get("daily_plan_id"):
                errors.append(
                    f"{table}.{column} {actual!r} != daily_plan_id "
                    f"{row.get('daily_plan_id')!r}"
                )
        elif actual != expected:
            errors.append(f"{table}.{column} expected {expected!r}, got {actual!r}")
    return errors


def _compare(
    before_path: Path,
    after_path: Path,
    *,
    exact_counts: bool = True,
    allow_backfill: bool = True,
    allow_runtime_prompt_sync: bool = False,
) -> dict:
    before = _connect(before_path)
    after = _connect(after_path)
    details: dict = {
        "tables": {},
        "errors": [],
        "compared_rows": 0,
        "allowed_backfills": [],
        "special_tables": {},
    }
    try:
        before_tables = _tables(before)
        after_tables = set(_tables(after))
        for table in before_tables:
            if table not in after_tables:
                details["errors"].append(f"missing table after upgrade: {table}")
                continue
            before_columns = _columns(before, table)
            after_columns = _columns(after, table)
            if table in SPECIAL_TABLES:
                details["special_tables"][table] = {
                    "before": [
                        dict(row)
                        for row in before.execute(f'SELECT * FROM "{table}"')
                    ],
                    "after": [
                        dict(row)
                        for row in after.execute(f'SELECT * FROM "{table}"')
                    ],
                }
                continue
            removed = sorted(set(before_columns) - set(after_columns))
            added = sorted(set(after_columns) - set(before_columns))
            if removed:
                details["errors"].append(
                    f"{table}: removed old columns {removed}"
                )
            if allow_backfill:
                unexpected = sorted(set(added) - set(BACKFILL_RULES.get(table, {})))
                if unexpected:
                    details["errors"].append(
                        f"{table}: unexpected new columns {unexpected}"
                    )
            elif added:
                details["errors"].append(f"{table}: unexpected new columns {added}")
            key = _primary_key(before, table)
            before_rows = _rows(before, table, before_columns, key)
            after_rows = _rows(after, table, after_columns, key)
            runtime_prompt = allow_runtime_prompt_sync and table in RUNTIME_PROMPT_TABLES
            if (
                exact_counts
                and table not in APPEND_ONLY_TABLES
                and not runtime_prompt
            ):
                if len(before_rows) != len(after_rows):
                    details["errors"].append(
                        f"{table}: row count {len(before_rows)} -> {len(after_rows)}"
                    )
            compared = 0
            for marker, old_row in before_rows.items():
                new_row = after_rows.get(marker)
                if new_row is None:
                    details["errors"].append(f"{table}: old row missing {marker!r}")
                    continue
                for column in before_columns:
                    if runtime_prompt and (table, column) in RUNTIME_PROMPT_MUTABLE_COLUMNS:
                        continue
                    if old_row[column] != new_row.get(column):
                        details["errors"].append(
                            f"{table}.{column} changed for {marker!r}: "
                            f"{old_row[column]!r} -> {new_row.get(column)!r}"
                        )
                compared += 1
            details["compared_rows"] += compared
            table_backfills = {}
            if allow_backfill:
                rule = BACKFILL_RULES.get(table, {})
                for column in sorted(set(added) & set(rule)):
                    values = sorted(
                        {repr(row.get(column)) for row in after_rows.values()}
                    )
                    table_backfills[column] = values
                    for new_row in after_rows.values():
                        details["errors"].extend(
                            _validate_backfill(table, new_row, after, {column: rule[column]})
                        )
            details["tables"][table] = {
                "before_rows": len(before_rows),
                "after_rows": len(after_rows),
                "compared": compared,
                "added_columns": added,
                "backfill_values": table_backfills,
                "runtime_prompt_sync": runtime_prompt,
            }
    finally:
        before.close()
        after.close()
    details["ok"] = not details["errors"]
    return details


def _integrity(path: Path) -> dict:
    connection = _connect(path)
    try:
        return {
            "integrity": connection.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key": [list(row) for row in connection.execute("PRAGMA foreign_key_check")],
            "migration_rows": [
                list(row)
                for row in connection.execute(
                    "SELECT version_num FROM local_alembic_version"
                )
            ],
        }
    finally:
        connection.close()


def _migration_only(before_path: Path, target_path: Path) -> dict:
    """Run the real Alembic 0006 upgrade without app startup/prompt sync."""
    shutil.copy2(before_path, target_path)
    from app.local.migrate import ensure_local_schema

    inspection = ensure_local_schema(target_path)
    return {
        "state": inspection.state,
        "current_revision": inspection.current_revision,
        "detail": inspection.detail,
    }


def _db_counts(db_path: Path) -> dict[str, int]:
    connection = _connect(db_path)
    try:
        tables = (
            "local_daily_plans",
            "local_daily_plan_contents",
            "local_ai_tasks",
            "local_observation_records",
            "local_prompt_bundles",
            "local_personal_prompt_versions",
            "local_personal_prompt_heads",
        )
        return {
            table: connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
            for table in tables
        }
    finally:
        connection.close()


def _runtime_reopen(data_dir: Path, credential_root: Path) -> dict:
    """Reopen the upgraded DB through the real LocalRuntime (no UI driver)."""
    from sqlalchemy import text

    from app.local.runtime import LocalRuntime

    runtime = LocalRuntime(data_dir, credential_root=credential_root)
    try:
        inspection = runtime.prepare()
        session = runtime.session()
        try:
            plans = [
                dict(row._mapping)
                for row in session.execute(
                    text(
                        "SELECT id, current_content_version FROM local_daily_plans "
                        "ORDER BY id"
                    )
                )
            ]
            contents = [
                dict(row._mapping)
                for row in session.execute(
                    text(
                        "SELECT id, daily_plan_id, version FROM local_daily_plan_contents "
                        "ORDER BY daily_plan_id, version"
                    )
                )
            ]
            tasks = [
                dict(row._mapping)
                for row in session.execute(
                    text("SELECT id, task_type, status FROM local_ai_tasks ORDER BY id")
                )
            ]
            observations = [
                dict(row._mapping)
                for row in session.execute(
                    text(
                        "SELECT id, record_type, current_version "
                        "FROM local_observation_records ORDER BY id"
                    )
                )
            ]
        finally:
            session.close()
        return {
            "revision": inspection.current_revision,
            "state": inspection.state,
            "plans": plans,
            "contents": contents,
            "tasks": tasks,
            "observations": observations,
        }
    finally:
        runtime.dispose()


def _run_window(python: Path, frontend: Path, data_dir: Path, output_dir: Path, timeout: float) -> dict:
    command = [
        str(python),
        str(HERE / "verify_observation_window.py"),
        "--frontend",
        str(frontend),
        "--data-dir",
        str(data_dir),
        "--output-dir",
        str(output_dir),
        "--timeout",
        str(timeout),
    ]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        command,
        cwd=str(HERE),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout + 120,
    )
    report_path = output_dir / "report.json"
    report = {}
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
    return {
        "command": command,
        "exit_code": completed.returncode,
        "stdout_tail": completed.stdout[-2000:],
        "stderr_tail": completed.stderr[-2000:],
        "report": report,
    }


def _backup_report(data_dir: Path, before_path: Path) -> dict:
    backup_dir = data_dir / "migration-backups"
    backups = sorted(backup_dir.glob("pre-D2-*.sqlite"))
    manifests = sorted(backup_dir.glob("pre-D2-*.manifest.json"))
    result: dict = {
        "backup_dir": str(backup_dir),
        "backup_count": len(backups),
        "manifest_count": len(manifests),
        "backups": [path.name for path in backups],
        "manifests": [path.name for path in manifests],
    }
    if len(backups) == 1 and len(manifests) == 1:
        manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
        result["manifest"] = manifest
        result["manifest_matches"] = (
            manifest.get("version") == SOURCE_REVISION
            and manifest.get("sha256") == _sha256(backups[0])
        )
        result["logical_compare"] = _compare(before_path, backups[0])
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--frontend", default=str(FRONTEND_DEFAULT))
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--python", default=str(PYTHON_DEFAULT))
    args = parser.parse_args()

    data_dir = Path(args.data_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    frontend = Path(args.frontend).resolve()
    python = Path(args.python).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if (data_dir / "kindergarten.db").exists():
        raise SystemExit(f"refuse to reuse an existing database: {data_dir}")
    data_dir.mkdir(parents=True, exist_ok=True)

    report: dict = {
        "ok": False,
        "generated_at": _now(),
        "data_dir": str(data_dir),
        "output_dir": str(output_dir),
        "frontend": str(frontend),
        "python": str(python),
        "source_revision": SOURCE_REVISION,
        "target_revision": TARGET_REVISION,
        "checks": {},
        "notes": [],
    }
    checks = report["checks"]

    _build_0005(data_dir / "kindergarten.db")
    before_path = output_dir / "before.sqlite"
    shutil.copy2(data_dir / "kindergarten.db", before_path)
    report["before"] = {
        "sha256": _sha256(before_path),
        "size": before_path.stat().st_size,
    }
    checks["fixture_built"] = True

    # 1. Migration-only proof: real Alembic 0006 without app startup or prompt
    # sync. Every pre-existing row/column except the version table must be
    # byte-identical; only the documented 0006 source columns may be added.
    migration_path = output_dir / "migration-only.sqlite"
    report["migration_only"] = _migration_only(before_path, migration_path)
    report["migration_integrity"] = _integrity(migration_path)
    report["migration_comparison"] = _compare(before_path, migration_path)
    checks["migration_only_0006"] = (
        report["migration_only"]["current_revision"] == TARGET_REVISION
    )
    checks["migration_only_integrity_ok"] = (
        report["migration_integrity"]["integrity"] == "ok"
        and not report["migration_integrity"]["foreign_key"]
    )
    checks["migration_preserves_old_rows"] = report["migration_comparison"]["ok"]
    checks["migration_old_rows_compared"] = (
        report["migration_comparison"]["compared_rows"] > 0
    )

    # 2. Real WebView2 window on the old synthetic DB: the window itself
    # performs the cold upgrade and the full observation flow.
    first = _run_window(python, frontend, data_dir, output_dir / "window-1", args.timeout)
    report["window_1"] = first
    checks["window_1_exit_zero"] = first["exit_code"] == 0
    checks["window_1_ok"] = bool(first["report"].get("ok"))

    db_path = data_dir / "kindergarten.db"
    report["after_1"] = _integrity(db_path)
    checks["integrity_ok"] = report["after_1"]["integrity"] == "ok"
    checks["foreign_keys_ok"] = not report["after_1"]["foreign_key"]
    checks["upgraded_to_0006"] = report["after_1"]["migration_rows"] == [
        [TARGET_REVISION]
    ]

    # Runtime prompt sync is existing D2 behaviour: it may add default bundles
    # and advance a daily head pointer, but old business rows and old prompt
    # version/bundle rows must survive unchanged.
    report["comparison_1"] = _compare(
        before_path, db_path, allow_runtime_prompt_sync=True
    )
    checks["old_rows_preserved"] = report["comparison_1"]["ok"]
    checks["old_rows_compared"] = report["comparison_1"]["compared_rows"] > 0

    report["backup"] = _backup_report(data_dir, before_path)
    checks["backup_created"] = report["backup"]["backup_count"] == 1
    checks["backup_manifest_matches"] = bool(
        report["backup"].get("manifest_matches")
    )
    checks["backup_logically_equals_before"] = bool(
        report["backup"].get("logical_compare", {}).get("ok")
    )

    # 3. Reopen through the real LocalRuntime (no UI driver: the obs-ui driver
    # intentionally creates fixed request IDs and is not a restart driver).
    counts_before = _db_counts(db_path)
    credential_root = data_dir.parent / (data_dir.name + "-credentials")
    report["runtime_reopen"] = _runtime_reopen(data_dir, credential_root)
    counts_after = _db_counts(db_path)
    report["reopen_counts"] = {
        "before": counts_before,
        "after": counts_after,
        "stable": counts_before == counts_after,
    }
    checks["runtime_reopen_ok"] = (
        report["runtime_reopen"]["state"] == "current"
        and report["runtime_reopen"]["revision"] == TARGET_REVISION
    )
    checks["reopen_no_prompt_reseed"] = counts_before == counts_after
    report["after_2"] = _integrity(db_path)
    checks["reopen_integrity_ok"] = report["after_2"]["integrity"] == "ok"
    checks["reopen_foreign_keys_ok"] = not report["after_2"]["foreign_key"]
    checks["reopen_single_migration_row"] = report["after_2"]["migration_rows"] == [
        [TARGET_REVISION]
    ]
    report["comparison_2"] = _compare(
        before_path, db_path, allow_runtime_prompt_sync=True
    )
    checks["reopen_old_rows_preserved"] = report["comparison_2"]["ok"]
    report["backup_after_reopen"] = _backup_report(data_dir, before_path)
    checks["reopen_no_new_backup"] = (
        report["backup_after_reopen"]["backup_count"] == 1
        and report["backup_after_reopen"]["manifest_count"] == 1
    )

    report["ok"] = all(checks.values())
    (output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "report": str(output_dir / "report.json"),
                "failed_checks": [name for name, value in checks.items() if not value],
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
