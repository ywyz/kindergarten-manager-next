"""Subprocess worker for cross-process local tests.

Runs one action against a real SQLite file through the service layer and
writes a JSON result. Expected domain failures are returned as
``{"error": {code, message}}``; anything else crashes the process.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import sys
import time
from datetime import date
from pathlib import Path
from unittest import mock

from sqlalchemy.orm import sessionmaker

from app.local import daily_plan_service, profile_service
from app.local.errors import LocalError
from app.local.normalize import normalize_initialization
from app.local.runtime import LocalRuntime
from app.local.sqlite import DB_FILENAME, create_local_engine


class _AttachedRuntime:
    """Attach to an already-prepared synthetic database without the run lock.

    Used by cross-process transaction tests where the parent test process is
    the single ``LocalRuntime`` owner: the worker only needs a real engine and
    sessions against the prepared file. It deliberately does *not* migrate and
    does *not* acquire ``.app-runtime.lock`` (there is no production
    ``ignore_lock``/reentrant bypass). SQLite itself provides the write
    arbitration under test.
    """

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir).resolve()
        self.db_path = self.data_dir / DB_FILENAME
        # The parent owner must have prepared this database already. Refuse to
        # silently create a fresh file (a missing database means a broken test
        # setup, not a green run) and require the owner's lock file to exist.
        if not self.db_path.is_file():
            raise RuntimeError(
                f"connect_only worker: database not prepared by an owner: {self.db_path}"
            )
        if not (self.data_dir / ".app-runtime.lock").is_file():
            raise RuntimeError(
                f"connect_only worker: no owner lock present under {self.data_dir}"
            )
        self.engine = create_local_engine(self.db_path)
        self._session_factory = sessionmaker(
            bind=self.engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )

    def session(self):  # noqa: ANN201 - sqlalchemy Session
        return self._session_factory()

    def dispose(self) -> None:
        self.engine.dispose()


def _action_initialize(spec: dict, runtime: LocalRuntime) -> dict:
    session = runtime.session()
    try:
        normalized = normalize_initialization(**spec["input"])
        payload, created = profile_service.initialize(session, normalized)
        return {"created": created, "payload": payload}
    finally:
        session.close()


def _action_create_plan(spec: dict, runtime: LocalRuntime) -> dict:
    session = runtime.session()
    try:
        raw = (
            spec["raw"] if "raw" in spec else daily_plan_service.UNSET
        )
        adopted = (
            spec["adopted"] if "adopted" in spec else daily_plan_service.UNSET
        )
        payload, created = daily_plan_service.create_or_open(
            session,
            plan_date=date.fromisoformat(spec["plan_date"]),
            raw_lesson_plan=raw,
            adopted_content=adopted,
        )
        return {"created": created, "payload": payload}
    finally:
        session.close()


def _action_save_plan(spec: dict, runtime: LocalRuntime) -> dict:
    session = runtime.session()
    try:
        raw = spec["raw"] if "raw" in spec else daily_plan_service.UNSET
        adopted = (
            spec["adopted"] if "adopted" in spec else daily_plan_service.UNSET
        )
        payload = daily_plan_service.save(
            session,
            plan_id=spec["plan_id"],
            expected_content_version=spec["expected"],
            raw_lesson_plan=raw,
            adopted_content=adopted,
        )
        return {"payload": payload}
    finally:
        session.close()


def _action_read_context(spec: dict, runtime: LocalRuntime) -> dict:
    session = runtime.session()
    try:
        as_of = (
            date.fromisoformat(spec["as_of_date"])
            if spec.get("as_of_date")
            else None
        )
        return {"payload": profile_service.read_context(session, as_of)}
    finally:
        session.close()


def _action_config_preview(spec: dict, runtime: LocalRuntime) -> dict:
    from app.local import config_service

    session = runtime.session()
    try:
        payload = config_service.preview(
            session,
            expected_config_version=spec["expected_config_version"],
            change=spec["change"],
        )
        return {"payload": payload}
    finally:
        session.close()


def _action_config_apply(spec: dict, runtime: LocalRuntime) -> dict:
    from app.local import config_service

    session = runtime.session()
    try:
        payload = config_service.apply(
            session,
            request_id=spec["request_id"],
            expected_config_version=spec["expected_config_version"],
            change=spec["change"],
            preview_token=spec["preview_token"],
        )
        return {"payload": payload}
    finally:
        session.close()


def _action_counts(spec: dict, runtime: LocalRuntime) -> dict:
    session = runtime.session()
    try:
        from sqlalchemy import func, select

        from app.local.models import (
            LocalDailyPlan,
            LocalDailyPlanContent,
            LocalOperationRecord,
            LocalProfile,
        )

        def count(model) -> int:
            return int(session.scalar(select(func.count()).select_from(model)) or 0)

        current_version = None
        if spec.get("plan_id"):
            plan = session.get(LocalDailyPlan, spec["plan_id"])
            current_version = plan.current_content_version if plan else None
        return {
            "profile": count(LocalProfile),
            "plans": count(LocalDailyPlan),
            "contents": count(LocalDailyPlanContent),
            "audit": count(LocalOperationRecord),
            "current_version": current_version,
        }
    finally:
        session.close()


def _action_export_snapshot(spec: dict, runtime: LocalRuntime) -> dict:
    """Production export read; pause after the plan-selection SELECT.

    The pause happens inside the service's explicit read transaction after
    the plan rows were selected but before the content rows are read, so the
    main process can commit another save meanwhile. The generated DOCX must
    still contain the pinned old snapshot.
    """
    import base64

    from sqlalchemy import event

    from app.local import export_service

    session = runtime.session()
    fired = False

    def after_cursor_execute(_conn, _cursor, statement, _parameters, _ctx, _many):  # noqa: ANN001
        nonlocal fired
        compact = " ".join(statement.split())
        if not fired and "FROM local_daily_plans" in compact:
            fired = True
            Path(spec["first_file"]).write_text(
                json.dumps({"barrier": "plans_selected"}), encoding="utf-8"
            )
            _wait_for_file(spec["proceed_file"], float(spec.get("wait_seconds", 30)))

    event.listen(runtime.engine, "after_cursor_execute", after_cursor_execute)
    try:
        bundle = export_service.prepare_export(
            session,
            from_date=date.fromisoformat(spec["from_date"]),
            to_date=date.fromisoformat(spec["to_date"]),
            ack_missing=True,
            expected_context=spec["expected_context"],
        )
        payload = export_service.generate_docx(bundle)
        return {
            "docx_base64": base64.b64encode(payload).decode("ascii"),
            "versions": [record.content_version for record in bundle.records],
        }
    finally:
        event.remove(runtime.engine, "after_cursor_execute", after_cursor_execute)
        session.close()


def _action_hold_write_lock(spec: dict, runtime: LocalRuntime) -> dict:
    """Take the SQLite write lock and hold it until released (busy test)."""
    session = runtime.session()
    try:
        connection = session.connection()
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        Path(spec["signal_file"]).write_text("locked", encoding="utf-8")
        release = Path(spec["release_file"])
        deadline = time.time() + float(spec.get("hold_seconds", 8))
        while time.time() < deadline:
            if release.exists():
                break
            time.sleep(0.02)
        connection.exec_driver_sql("ROLLBACK")
        return {"released": True}
    finally:
        session.close()


def _wait_for_file(path: str, timeout: float) -> None:
    target = Path(path)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if target.exists():
            return
        time.sleep(0.02)
    raise TimeoutError(f"barrier file not released: {target}")


def _action_read_list_snapshot(spec: dict, runtime: LocalRuntime) -> dict:
    """Run the production list read; pause after its count(*) statement.

    ``after_cursor_execute`` fires once the count SELECT completed, i.e.
    inside the service's explicit read transaction. Pausing there lets the
    main process commit a new plan before the items SELECT runs; the
    returned total and items must both describe the same snapshot.
    """
    from sqlalchemy import event

    session = runtime.session()
    fired = False

    def after_cursor_execute(_conn, _cursor, statement, _parameters, _ctx, _many):  # noqa: ANN001
        nonlocal fired
        compact = " ".join(statement.split())
        if (
            not fired
            and "count(" in compact
            and "local_daily_plans" in compact
        ):
            fired = True
            Path(spec["first_file"]).write_text(
                json.dumps({"barrier": "count_done"}), encoding="utf-8"
            )
            _wait_for_file(spec["proceed_file"], float(spec.get("wait_seconds", 30)))

    event.listen(runtime.engine, "after_cursor_execute", after_cursor_execute)
    try:
        payload = daily_plan_service.list_plans(
            session,
            from_date=date.fromisoformat(spec["from_date"]),
            to_date=date.fromisoformat(spec["to_date"]),
            offset=0,
            limit=100,
        )
        return {"payload": payload}
    finally:
        event.remove(runtime.engine, "after_cursor_execute", after_cursor_execute)
        session.close()


def _action_read_detail_snapshot(spec: dict, runtime: LocalRuntime) -> dict:
    """Run the production by-date read; pause after its header SELECT.

    The pause happens between the plan-header read and the content read
    inside the service's read transaction, so the response must still be a
    single complete version even though another process commits a save in
    the middle.
    """
    from sqlalchemy import event

    session = runtime.session()
    fired = False

    def after_cursor_execute(_conn, _cursor, statement, _parameters, _ctx, _many):  # noqa: ANN001
        nonlocal fired
        if not fired and "FROM local_daily_plans" in statement:
            fired = True
            Path(spec["first_file"]).write_text(
                json.dumps({"barrier": "header_done"}), encoding="utf-8"
            )
            _wait_for_file(spec["proceed_file"], float(spec.get("wait_seconds", 30)))

    event.listen(runtime.engine, "after_cursor_execute", after_cursor_execute)
    try:
        payload = daily_plan_service.get_by_date(
            session, plan_date=date.fromisoformat(spec["plan_date"])
        )
        return {"payload": payload}
    finally:
        event.remove(runtime.engine, "after_cursor_execute", after_cursor_execute)
        session.close()


def _observation_image(spec: dict) -> bytes:
    if spec.get("image_base64"):
        return base64.b64decode(spec["image_base64"])
    return Path(spec["image_file"]).read_bytes()


def _action_observation_import(spec: dict, runtime) -> dict:
    from sqlalchemy import select

    from app.local import observation_assets
    from app.local.models import LocalObservationAsset

    session = runtime.session()
    try:
        exit_mode = spec.get("exit_mode")

        def marker(stage: str) -> None:
            if not spec.get("marker_file"):
                return
            rows = session.scalars(select(LocalObservationAsset)).all()
            Path(spec["marker_file"]).write_text(
                json.dumps(
                    {
                        "stage": stage,
                        "asset_rows": len(rows),
                        "asset_ids": [row.id for row in rows],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

        if exit_mode == "partial":
            original_flush = session.flush

            def flush_then_exit(*args, **kwargs):  # noqa: ANN001
                original_flush(*args, **kwargs)
                marker("partial")
                os._exit(17)

            session.flush = flush_then_exit  # type: ignore[method-assign]
        elif exit_mode == "before_commit":
            original_commit = session.commit

            def flush_then_exit_before_commit(*args, **kwargs):  # noqa: ANN001
                session.flush()
                marker("before_commit")
                os._exit(17)

            session.commit = flush_then_exit_before_commit  # type: ignore[method-assign]
        if exit_mode == "after_files":
            def begin_then_exit(*args, **kwargs):  # noqa: ANN001
                marker("after_files")
                os._exit(17)

            observation_assets.begin_immediate = begin_then_exit  # type: ignore[assignment]
        result = observation_assets.import_asset(
            session,
            runtime,
            profile_id=spec["profile_id"],
            observation_id=spec["observation_id"],
            request_id=spec["request_id"],
            expected_revision=spec["expected_revision"],
            stream=io.BytesIO(_observation_image(spec)),
            display_name=spec.get("display_name", "worker.jpg"),
            caption=spec.get("caption"),
        )
        if exit_mode == "after_commit":
            Path(spec["result_file"]).write_text(
                json.dumps({"result": result}, ensure_ascii=False), encoding="utf-8"
            )
            marker("after_commit")
            os._exit(17)
        return {"result": result}
    finally:
        session.close()


def _action_observation_read(spec: dict, runtime) -> dict:
    from sqlalchemy import select

    from PIL import Image

    from app.local import observation_assets
    from app.local.models import (
        LocalObservationAsset,
        LocalObservationAssetDerivative,
        LocalObservationDraftPhoto,
        LocalObservationOperation,
        LocalOperationRecord,
    )

    session = runtime.session()
    try:
        photos = observation_assets.list_photos(
            session,
            profile_id=spec["profile_id"],
            observation_id=spec["observation_id"],
        )
        payload = {"photos": photos, "assets": [], "receipts": 0, "audits": 0}
        for asset_id in spec.get("asset_ids", []):
            asset = session.get(LocalObservationAsset, asset_id)
            if asset is None or asset.observation_id != spec["observation_id"]:
                raise AssertionError(f"asset missing or cross-record: {asset_id}")
            original = observation_assets.read_asset_bytes(
                session,
                runtime,
                profile_id=spec["profile_id"],
                observation_id=spec["observation_id"],
                asset_id=asset_id,
            )
            original_hash = hashlib.sha256(original).hexdigest()
            if original_hash != asset.content_hash or len(original) != asset.byte_size:
                raise AssertionError(f"original bytes/hash mismatch: {asset_id}")
            derivatives = {}
            for derivative_id in spec.get("derivatives", {}).get(asset_id, []):
                derivative = session.get(
                    LocalObservationAssetDerivative, derivative_id
                )
                if (
                    derivative is None
                    or derivative.observation_id != spec["observation_id"]
                    or derivative.asset_id != asset_id
                ):
                    raise AssertionError(
                        f"derivative missing or cross-record: {derivative_id}"
                    )
                data = observation_assets.read_derivative_bytes(
                    session,
                    runtime,
                    profile_id=spec["profile_id"],
                    observation_id=spec["observation_id"],
                    asset_id=asset_id,
                    derivative_id=derivative_id,
                )
                digest = hashlib.sha256(data).hexdigest()
                if digest != derivative.content_hash:
                    raise AssertionError(
                        f"derivative hash mismatch: {derivative_id}"
                    )
                with Image.open(io.BytesIO(data)) as image:
                    if image.size != (derivative.width, derivative.height):
                        raise AssertionError(
                            f"derivative dimensions mismatch: {derivative_id}"
                        )
                derivatives[derivative.purpose] = {
                    "derivative_id": derivative_id,
                    "sha256": digest,
                    "bytes": len(data),
                    "width": derivative.width,
                    "height": derivative.height,
                    "params_version": derivative.params_version,
                    "relative_path": derivative.relative_path,
                }
            payload["assets"].append(
                {
                    "asset_id": asset_id,
                    "sha256": original_hash,
                    "bytes": len(original),
                    "content_hash": asset.content_hash,
                    "relative_path": asset.relative_path,
                    "derivatives": derivatives,
                }
            )
        payload["receipts"] = len(
            session.scalars(select(LocalObservationOperation)).all()
        )
        payload["audits"] = len(
            [
                row
                for row in session.scalars(select(LocalOperationRecord)).all()
                if row.action.startswith("observation_")
            ]
        )
        payload["draft_photos"] = [
            (row.asset_id, row.sort_order, row.caption)
            for row in session.scalars(
                select(LocalObservationDraftPhoto)
                .where(
                    LocalObservationDraftPhoto.observation_id
                    == spec["observation_id"]
                )
                .order_by(LocalObservationDraftPhoto.sort_order)
            ).all()
        ]
        return payload
    finally:
        session.close()


ACTIONS = {
    "initialize": _action_initialize,
    "create_plan": _action_create_plan,
    "save_plan": _action_save_plan,
    "read_context": _action_read_context,
    "config_preview": _action_config_preview,
    "config_apply": _action_config_apply,
    "counts": _action_counts,
    "export_snapshot": _action_export_snapshot,
    "hold_write_lock": _action_hold_write_lock,
    "read_list_snapshot": _action_read_list_snapshot,
    "read_detail_snapshot": _action_read_detail_snapshot,
    "observation_import": _action_observation_import,
    "observation_read": _action_observation_read,
}


def main() -> int:
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if spec.get("connect_only"):
        runtime = _AttachedRuntime(spec["data_dir"])
    else:
        runtime = LocalRuntime(
            spec["data_dir"], credential_root=spec.get("credential_root")
        )
        runtime.prepare()
    try:
        result = ACTIONS[spec["action"]](spec, runtime)
    except LocalError as exc:
        result = {"error": {"code": exc.code, "message": exc.message}}
    finally:
        runtime.dispose()
    Path(spec["result_file"]).write_text(
        json.dumps(result, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
