"""A G1 weekly AI task submission, receipt and scope tests."""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

from sqlalchemy import select

from app.local import (
    ai_config_service,
    ai_task_service,
    ai_transport,
    backup_barrier,
    config_service,
    daily_plan_service,
    profile_service,
    prompt_bundles,
    weekly_ai_adoption,
    weekly_ai_contracts,
    weekly_ai_candidates,
    weekly_ai_inputs,
    weekly_ai_service,
    weekly_ai_sources,
    weekly_plan_content,
    weekly_plan_service,
)
from app.local.ai_executor import AiExecutor
from app.local.errors import (
    LocalAiNotFound,
    LocalAiRetryAckRequired,
    LocalAiTaskStateConflict,
    LocalMaterialContextRequired,
    LocalPromptAdaptationRequired,
    LocalStorageError,
    LocalWeeklyAiRequestConflict,
    LocalWeeklyAiSourceChanged,
    LocalWeeklyAiTaskActive,
    LocalWeeklyVersionConflict,
)
from app.local.models import (
    LocalAIAttempt,
    LocalAICandidate,
    LocalAIExecution,
    LocalDailyPlan,
    LocalAIInput,
    LocalAIOperation,
    LocalAIState,
    LocalAITask,
    LocalPersonalPromptHead,
    LocalPersonalPromptVersion,
    LocalProfile,
    LocalPromptBundle,
    LocalSettings,
    LocalTerm,
    LocalWeeklyPlan,
    LocalWeeklyPlanAIAdoption,
    LocalWeeklyPlanConfirmation,
    LocalWeeklyPlanContent,
)
from app.local.normalize import normalize_initialization
from tests.local.support import LocalTestCase

ANCHOR = date(2026, 9, 7)
DAY = date(2026, 9, 8)


def _weekly_trace(event: str, **fields) -> None:
    path = os.environ.get("KGM_WEEKLY_WORKER_TRACE")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {"event": event, "pid": os.getpid(), **fields},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            )
    except OSError:
        pass


def _weekly_result_frame(
    kind: str,
    *,
    reason: str | None = None,
    sent: bool = True,
    transient: bool = False,
    http_status: int | None = None,
    candidate=None,
) -> dict:
    return {
        "type": "result",
        "result": {
            "kind": kind,
            "reason": reason,
            "transient_not_sent": transient,
            "sent": sent,
            "http_status": http_status,
            "provider_request_id": "weekly-req",
            "returned_model": "weekly-fake",
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            "candidate_text": (
                json.dumps(candidate, ensure_ascii=False, separators=(",", ":"))
                if candidate is not None
                else None
            ),
            "detail": None,
        },
    }


def _weekly_candidate(payload: dict) -> dict:
    task_type = payload.get("task_type")
    if task_type == "weekly_games_select":
        morning = next(
            (
                game["source_handle"]
                for day in payload.get("days") or []
                for group in day.get("morning_games") or []
                for game in group.get("games") or []
            ),
            None,
        )
        post = next(
            (
                game["source_handle"]
                for day in payload.get("days") or []
                for group in day.get("post_group_games") or []
                for game in group.get("games") or []
            ),
            None,
        )
        return {
            "outdoor_game_slots": {
                "collective_1": (
                    {"kind": "source", "source_handle": morning} if morning else None
                ),
                "collective_2": None,
                "free_choice_1": None,
            },
            "focus_area": {"kind": "source", "source_handle": post} if post else None,
        }
    if task_type == "weekly_materials_generate":
        return {"items": []}
    return {"text": f"1. {task_type} 建议\n2. 第二条建议"}


def _weekly_send(conn, frame: dict) -> bool:
    try:
        conn.send_bytes(json.dumps(frame, ensure_ascii=False).encode("utf-8"))
        return True
    except Exception:  # noqa: BLE001
        return False


def weekly_fake_worker(conn) -> None:
    """Spawned fake provider for the real weekly executor path.

    The pinned model string selects a scripted branch.  Every branch records
    ``ready``/``send`` in the trace file named by ``KGM_WEEKLY_WORKER_TRACE`` so
    the parent can prove transport sends independently of finalize calls.
    """
    try:
        if not conn.poll(5.0):
            return
        bootstrap = json.loads(
            bytes(conn.recv_bytes(8 * 1024 * 1024)).decode("utf-8")
        )
        model = bootstrap["request"]["model"]
        spec = model.split("w3weekly|", 1)[1] if "w3weekly|" in model else "success"
        parts = spec.split("|")
        mode = parts[0]
        payload = json.loads(bootstrap["request"]["user_text"])
        task_type = payload.get("task_type")
        if mode == "pre_send":
            kind = parts[1] if len(parts) > 1 else "not_sent"
            reason = parts[2] if len(parts) > 2 else "connection_unavailable"
            _weekly_trace("pre_send", kind=kind, task_type=task_type)
            _weekly_send(
                conn,
                _weekly_result_frame(
                    kind,
                    reason=reason,
                    sent=False,
                    transient=kind == "not_sent",
                ),
            )
            return
        _weekly_trace("ready", task_type=task_type)
        if not _weekly_send(conn, {"type": "ready", "remaining_ms": 1000}):
            return
        if not conn.poll(30.0):
            return
        try:
            command = json.loads(bytes(conn.recv_bytes(64 * 1024)).decode("utf-8"))
        except Exception:  # noqa: BLE001
            return
        if command.get("type") != "send":
            return
        _weekly_trace("send", task_type=task_type)
        if mode == "mixed_columns":
            candidate = (
                _weekly_candidate(payload)
                if task_type == "weekly_key_week_focus"
                else {"unexpected": "x"}
            )
            _weekly_send(
                conn,
                _weekly_result_frame("success", candidate=candidate),
            )
            return
        if mode == "after_send":
            outcome = parts[1] if len(parts) > 1 else "success"
            if outcome == "silent":
                time.sleep(30.0)
                return
            if outcome in ("auth401", "auth403"):
                _weekly_send(
                    conn,
                    _weekly_result_frame(
                        "auth",
                        reason="auth_rejected",
                        http_status=401 if outcome == "auth401" else 403,
                    ),
                )
                return
            if outcome == "rate_limit":
                _weekly_send(
                    conn,
                    _weekly_result_frame(
                        "rate_limited", reason="rate_limited", http_status=429
                    ),
                )
                return
            if outcome == "provider_error":
                _weekly_send(
                    conn,
                    _weekly_result_frame(
                        "provider_error", reason="provider_error", http_status=503
                    ),
                )
                return
            if outcome == "invalid":
                _weekly_send(
                    conn,
                    _weekly_result_frame("success", candidate={"unexpected": "x"}),
                )
                return
            if outcome == "truncated":
                try:
                    conn.send_bytes(b'{"type": "res')
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(30.0)
                return
        _weekly_send(
            conn,
            _weekly_result_frame("success", candidate=_weekly_candidate(payload)),
        )
    except Exception:  # noqa: BLE001
        pass
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


class WeeklyAIServiceFixture(LocalTestCase):
    def setUp(self):
        super().setUp()
        self.runtime = self.make_runtime()
        self.runtime.launch_id = str(uuid.uuid4())
        self.session = self.runtime.session()
        self.addCleanup(self.session.close)
        profile_service.initialize(
            self.session,
            normalize_initialization(
                request_id=str(uuid.uuid4()),
                display_name="测试教师",
                class_name="中一班",
                grade="middle",
                term_name="秋季学期",
                start_date=ANCHOR.isoformat(),
                end_date="2026-10-30",
                school_name="测试幼儿园",
            ),
        )
        self.session.commit()
        self.profile = self.session.scalars(select(LocalProfile)).one()
        self.term = self.session.scalars(select(LocalTerm)).one()
        self.settings = self.session.get(LocalSettings, "singleton")
        ai_config_service.patch_config(
            self.session,
            expected_ai_config_version=0,
            base_url="https://api.example.com/v1",
            model="test-model",
            secret="test-secret",
            secret_provided=True,
            request_id=str(uuid.uuid4()),
            credential_root=self.runtime.credential_root,
        )
        self.session.commit()
        daily_plan_service.create_or_open(
            self.session,
            plan_date=DAY,
            raw_lesson_plan=None,
            adopted_content={
                "morning_talk": {"topic": "秋天"},
                "group_activity": {
                    "theme": "树叶",
                    "objectives": "观察",
                    "process": "看一看",
                },
                "morning_games": [
                    {
                        "group_kind": "collective",
                        "games": [{"name": "老狼老狼几点了"}],
                        "shared_objectives": "听信号",
                        "guidance_points": "注意安全",
                        "focus_guidance": "观察反应",
                    }
                ],
                "post_group_games": [
                    {
                        "context_kind": "area",
                        "area": "积木区",
                        "games": [{"name": "搭小桥"}],
                        "objectives": "合作",
                        "guidance": "协商",
                        "support_strategy": "提供材料",
                    }
                ],
            },
        )
        self.session.commit()
        preview = weekly_plan_service.create_preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
            term_id=self.term.id,
            week_anchor_date=ANCHOR,
        )
        result, created = weekly_plan_service.create_or_open(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
            request_id=str(uuid.uuid4()),
            term_id=self.term.id,
            week_anchor_date=ANCHOR,
            expected_config_version=self.settings.config_version,
            context_token=preview["create_token"],
        )
        self.assertTrue(created)
        self.session.commit()
        self.plan_id = result["weekly_plan_id"]
        self.version = result["draft"]["version"]

    def _create(self, operation_kind, specs, request_id=None, version=None):
        return weekly_ai_service.create_weekly_tasks(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            plan_id=self.plan_id,
            request_id=request_id or str(uuid.uuid4()),
            expected_draft_version=self.version if version is None else version,
            operation_kind=operation_kind,
            task_specs=specs,
        )


    def _apply_term_end(self, end_date: str) -> dict:
        term = self.session.get(LocalTerm, self.term.id)
        version = self.session.get(LocalSettings, "singleton").config_version
        change = {
            "kind": "term_update",
            "term_id": term.id,
            "name": term.name,
            "start_date": term.start_date.isoformat(),
            "end_date": end_date,
        }
        preview = config_service.preview(
            self.session, expected_config_version=version, change=change
        )
        result = config_service.apply(
            self.session,
            request_id=str(uuid.uuid4()),
            expected_config_version=version,
            change=change,
            preview_token=preview["preview_token"],
        )
        self.session.expire_all()
        return result

    def _refresh_plan(self) -> dict:
        detail = weekly_plan_service.get_detail(
            self.session, profile_id=self.profile.id, plan_id=self.plan_id
        )
        version = detail["draft"]["version"]
        preview = weekly_plan_service.refresh_preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
            plan_id=self.plan_id,
            expected_draft_version=version,
        )
        result = weekly_plan_service.refresh_sources(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
            request_id=str(uuid.uuid4()),
            plan_id=self.plan_id,
            expected_draft_version=version,
            preview_token=preview["preview_token"],
        )
        self.session.expire_all()
        return result

    def _confirm_current(self) -> dict:
        detail = weekly_plan_service.get_detail(
            self.session, profile_id=self.profile.id, plan_id=self.plan_id
        )
        version = detail["draft"]["version"]
        preview = weekly_plan_service.confirmation_preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
            plan_id=self.plan_id,
            expected_draft_version=version,
        )
        result = weekly_plan_service.confirm(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
            request_id=str(uuid.uuid4()),
            plan_id=self.plan_id,
            expected_draft_version=version,
            context_token=preview["preview_token"],
            ack_missing=True,
            ack_stale=True,
        )
        self.session.expire_all()
        return result

    def _configure_model(self, model: str) -> int:
        state = self.session.get(LocalAIState, self.profile.id, populate_existing=True)
        version = int(state.current_config_version or 0)
        ai_config_service.patch_config(
            self.session,
            expected_ai_config_version=version,
            base_url="https://api.example.com/v1",
            model=model,
            secret="test-secret",
            secret_provided=True,
            request_id=str(uuid.uuid4()),
            credential_root=self.runtime.credential_root,
        )
        self.session.commit()
        return version + 1

    def _start_weekly_executor(self, model: str, **kwargs) -> tuple[AiExecutor, Path]:
        self._configure_model(model)
        trace = self.tmp_root / f"worker-{uuid.uuid4().hex}.jsonl"
        os.environ["KGM_WEEKLY_WORKER_TRACE"] = str(trace)
        self.addCleanup(lambda: os.environ.pop("KGM_WEEKLY_WORKER_TRACE", None))
        kwargs.setdefault("worker_target", weekly_fake_worker)
        executor = AiExecutor(self.runtime, **kwargs)
        self.assertTrue(executor.start())
        self.addCleanup(lambda: executor.stop())
        return executor, trace

    def _trace(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def _wait_task_status(
        self, task_id: str, statuses: set[str], timeout: float = 30.0
    ) -> str:
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            session = self.runtime.session()
            try:
                task = session.get(LocalAITask, task_id, populate_existing=True)
                status = task.status if task is not None else None
                last = (
                    (status, task.reason if task is not None else None)
                    if task is not None
                    else None
                )
            finally:
                session.close()
            if status in statuses:
                return str(status)
            time.sleep(0.05)
        raise AssertionError(f"task {task_id} did not reach {statuses}: {last}")

    def _submit(self, executor: AiExecutor, operation_kind=weekly_ai_service.GAMES, specs=None):
        specs = specs or [
            weekly_ai_service.WeeklyTaskSpec("weekly_games_select", "games")
        ]
        result, created = self._create(operation_kind, specs)
        self.assertTrue(created)
        executor.notify()
        return result["tasks"][0]["task_id"]

    def _ensure_bundle_version(
        self, task_type: str, contract_version: int = 1, default_revision: int = 1
    ) -> None:
        if self.session.get(
            LocalPromptBundle, (task_type, contract_version, default_revision)
        ) is not None:
            return
        current = self.session.scalars(
            select(LocalPromptBundle)
            .where(LocalPromptBundle.task_type == task_type)
            .order_by(LocalPromptBundle.contract_version.desc())
        ).first()
        self.session.add(
            LocalPromptBundle(
                task_type=task_type,
                contract_version=contract_version,
                default_revision=default_revision,
                input_schema_json=dict(current.input_schema_json),
                output_schema_json=dict(current.output_schema_json),
                guidance_defaults_json=dict(current.guidance_defaults_json),
                bundle_hash=current.bundle_hash,
                created_at=current.created_at,
            )
        )
        self.session.commit()

    def _succeed_games(self):
        result, _ = self._create(
            weekly_ai_service.GAMES,
            [weekly_ai_service.WeeklyTaskSpec("weekly_games_select", "games")],
        )
        task_id = result["tasks"][0]["task_id"]
        claim = ai_task_service.claim_next(
            self.runtime,
            now=ai_task_service._now(),
            started_ticks=1,
        )
        self.assertIsNotNone(claim)
        self.assertEqual(claim.source_kind, "weekly_plan")
        self.assertEqual(claim.weekly_plan_id, self.plan_id)
        self.assertTrue(
            ai_task_service.commit_dispatch_mark(
                self.session, claim, ai_task_service._now()
            )
        )
        payload = claim.payload
        morning = next(
            game["source_handle"]
            for day in payload["days"]
            for group in day["morning_games"]
            for game in group["games"]
        )
        focus = next(
            game["source_handle"]
            for day in payload["days"]
            for group in day["post_group_games"]
            for game in group["games"]
        )
        text = (
            '{"outdoor_game_slots":{"collective_1":{"kind":"source",'
            f'"source_handle":"{morning}"}},"collective_2":null,'
            '"free_choice_1":null},"focus_area":{"kind":"source",'
            f'"source_handle":"{focus}"}}}}'
        )
        self.assertTrue(
            ai_task_service.finalize_success(
                self.session,
                claim,
                {"kind": "success", "candidate_text": text},
                ai_task_service._now(),
            )
        )
        task = self.session.get(LocalAITask, task_id, populate_existing=True)
        self.assertEqual(task.status, "succeeded")
        candidate = self.session.scalars(
            select(LocalAICandidate).where(LocalAICandidate.task_id == task_id)
        ).one()
        self.assertEqual(candidate.source_kind, "weekly_plan")
        self.assertEqual(candidate.weekly_plan_id, self.plan_id)
        return task_id, candidate.id


class WeeklyAIServiceTests(WeeklyAIServiceFixture):
    def _ai_counts(self) -> dict[str, int]:
        return {
            model.__tablename__: self.session.query(model).count()
            for model in (
                LocalAIInput,
                LocalAITask,
                LocalAIOperation,
                LocalAIExecution,
                LocalAIAttempt,
            )
        }

    def test_games_atomic_receipt_replay_and_task_projection(self):
        rid = str(uuid.uuid4())
        result, created = self._create(
            weekly_ai_service.GAMES,
            [weekly_ai_service.WeeklyTaskSpec("weekly_games_select", "games")],
            request_id=rid,
        )
        self.assertTrue(created)
        self.assertFalse(result["replayed"])
        self.assertEqual(len(result["tasks"]), 1)
        task_id = result["tasks"][0]["task_id"]
        task = self.session.get(LocalAITask, task_id)
        inp = self.session.get(LocalAIInput, task.input_id)
        op = self.session.scalars(
            select(LocalAIOperation).where(LocalAIOperation.request_id == rid)
        ).one()
        self.assertEqual(task.source_kind, "weekly_plan")
        self.assertEqual(task.weekly_plan_id, self.plan_id)
        self.assertEqual(inp.source_kind, "weekly_plan")
        self.assertEqual(inp.weekly_plan_id, self.plan_id)
        self.assertEqual(inp.weekly_draft_id, result["draft"]["id"])
        self.assertEqual(inp.source_revision, self.version)
        self.assertEqual(inp.create_operation_id, op.id)
        self.assertIn("_server_manifest", inp.dependencies_json)
        self.assertIn("_batch_snapshot_hash", inp.dependencies_json)
        payload_text = str(inp.payload_json)
        self.assertNotIn(inp.weekly_plan_id, payload_text)
        self.assertNotIn(inp.weekly_draft_id, payload_text)
        self.assertNotIn(task.input_id, payload_text)
        self.assertEqual(op.operation_kind, weekly_ai_service.GAMES)
        out = ai_task_service.get_task(
            self.session, task_id, source_kind="weekly_plan", weekly_plan_id=self.plan_id
        )
        self.assertEqual(out["task_id"], task_id)
        self.assertEqual(out["weekly_plan_id"], self.plan_id)
        self.assertEqual(out["target"], "games")
        self.assertNotIn("plan_id", out)
        self.assertEqual(out["input_summary"]["create_operation_id"], op.id)
        replay, created2 = self._create(
            weekly_ai_service.GAMES,
            [weekly_ai_service.WeeklyTaskSpec("weekly_games_select", "games")],
            request_id=rid,
        )
        self.assertFalse(created2)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["tasks"], result["tasks"])
        self.assertEqual(self.session.query(LocalAITask).count(), 1)
        self.assertEqual(
            self.session.query(LocalAIOperation)
            .filter(LocalAIOperation.operation_kind == weekly_ai_service.GAMES)
            .count(),
            1,
        )
        with self.assertRaises(LocalWeeklyAiRequestConflict):
            self._create(
                weekly_ai_service.GAMES,
                [weekly_ai_service.WeeklyTaskSpec("weekly_games_select", "games")],
                request_id=rid,
                version=self.version + 1,
            )

    def test_term_calendar_change_requires_refresh_before_games_create(self):
        self._apply_term_end("2026-09-12")
        before = self._ai_counts()
        with self.assertRaises(LocalWeeklyAiSourceChanged) as raised:
            weekly_ai_service.create_weekly_tasks(
                self.session,
                runtime=None,
                profile_id=self.profile.id,
                plan_id=self.plan_id,
                request_id=str(uuid.uuid4()),
                expected_draft_version=self.version,
                operation_kind=weekly_ai_service.GAMES,
                task_specs=[
                    weekly_ai_service.WeeklyTaskSpec(
                        "weekly_games_select", "games"
                    )
                ],
            )
        self.assertEqual(raised.exception.code, "WEEKLY_AI_SOURCE_CHANGED")
        self.assertEqual(raised.exception.status_code, 409)
        self.session.expire_all()
        self.assertEqual(self._ai_counts(), before)

    def test_refreshed_term_calendar_change_allows_games_without_mutating_context(self):
        confirmed = self._confirm_current()
        confirmation_id = confirmed["confirmation"]["id"]
        self.session.expire_all()
        confirmation_before = self.session.get(
            LocalWeeklyPlanConfirmation, confirmation_id
        )
        confirmation_bytes = json.dumps(
            confirmation_before.snapshot_json, ensure_ascii=False, sort_keys=True
        )
        confirmation_hash = confirmation_before.snapshot_hash
        plan_before = self.session.get(LocalWeeklyPlan, self.plan_id)
        creation_context = (
            plan_before.term_start_date,
            plan_before.term_end_date,
            plan_before.calendar_revision_id,
        )

        self._apply_term_end("2026-09-12")
        refreshed = self._refresh_plan()
        new_version = refreshed["draft"]["version"]
        self.assertEqual(new_version, self.version + 1)

        self.session.expire_all()
        plan = self.session.get(LocalWeeklyPlan, self.plan_id)
        term = self.session.get(LocalTerm, plan.term_id)
        content = self.session.get(LocalWeeklyPlanContent, plan.current_draft_id)
        saved_content = weekly_plan_content.validate_content(content.content_json)
        manifest = saved_content["source_manifest"]
        raw = weekly_ai_sources.load_raw_manifest(
            self.session, plan=plan, content=content
        )
        self.assertEqual(raw["term_start"], term.start_date.isoformat())
        self.assertEqual(raw["term_end"], term.end_date.isoformat())
        self.assertEqual(raw["term_end"], manifest["term_end"])
        self.assertEqual(
            raw["calendar_revision_id"], term.current_calendar_revision_id
        )
        self.assertEqual(
            raw["calendar_revision_id"], manifest["calendar_revision_id"]
        )
        states = {item["day_state"] for item in raw["calendar_window"]["days"]}
        self.assertTrue({"teaching", "rest", "outside_term"} <= states, states)
        projected = weekly_ai_inputs.project_weekly_input(
            "weekly_key_week_focus", raw, content.content_json
        )
        self.assertEqual(projected.task_type, "weekly_key_week_focus")
        with self.assertRaises(weekly_ai_contracts.WeeklyAIContractError) as missing:
            weekly_ai_inputs.project_weekly_input(
                "weekly_materials_generate", raw, content.content_json
            )
        self.assertEqual(missing.exception.code, "MATERIAL_CONTEXT_REQUIRED")

        before = self._ai_counts()
        result, created = weekly_ai_service.create_weekly_tasks(
            self.session,
            runtime=None,
            profile_id=self.profile.id,
            plan_id=self.plan_id,
            request_id=str(uuid.uuid4()),
            expected_draft_version=new_version,
            operation_kind=weekly_ai_service.GAMES,
            task_specs=[
                weekly_ai_service.WeeklyTaskSpec("weekly_games_select", "games")
            ],
        )
        self.assertTrue(created)
        self.assertEqual(result["draft"]["version"], new_version)
        self.session.expire_all()
        after = self._ai_counts()
        self.assertEqual(after["local_ai_inputs"], before["local_ai_inputs"] + 1)
        self.assertEqual(after["local_ai_tasks"], before["local_ai_tasks"] + 1)
        self.assertEqual(
            after["local_ai_operations"], before["local_ai_operations"] + 1
        )
        self.assertEqual(after["local_ai_executions"], before["local_ai_executions"])
        self.assertEqual(after["local_ai_attempts"], before["local_ai_attempts"])

        confirmation_after = self.session.get(
            LocalWeeklyPlanConfirmation, confirmation_id
        )
        self.assertEqual(
            json.dumps(
                confirmation_after.snapshot_json,
                ensure_ascii=False,
                sort_keys=True,
            ),
            confirmation_bytes,
        )
        self.assertEqual(confirmation_after.snapshot_hash, confirmation_hash)
        plan_after = self.session.get(LocalWeeklyPlan, self.plan_id)
        self.assertEqual(
            (
                plan_after.term_start_date,
                plan_after.term_end_date,
                plan_after.calendar_revision_id,
            ),
            creation_context,
        )
        self.assertEqual(plan_after.current_draft_version, new_version)
        self.assertEqual(plan_after.current_confirmed_version, 1)

    def test_refreshed_term_calendar_change_columns_use_live_window(self):
        self._apply_term_end("2026-09-12")
        refreshed = self._refresh_plan()
        new_version = refreshed["draft"]["version"]
        self.session.expire_all()
        plan = self.session.get(LocalWeeklyPlan, self.plan_id)
        term = self.session.get(LocalTerm, plan.term_id)
        content = self.session.get(LocalWeeklyPlanContent, plan.current_draft_id)
        raw = weekly_ai_sources.load_raw_manifest(
            self.session, plan=plan, content=content
        )
        self.assertEqual(raw["term_end"], term.end_date.isoformat())
        self.assertEqual(
            raw["calendar_revision_id"], term.current_calendar_revision_id
        )

        before = self._ai_counts()
        result, created = weekly_ai_service.create_weekly_tasks(
            self.session,
            runtime=None,
            profile_id=self.profile.id,
            plan_id=self.plan_id,
            request_id=str(uuid.uuid4()),
            expected_draft_version=new_version,
            operation_kind=weekly_ai_service.COLUMNS,
            task_specs=[
                weekly_ai_service.WeeklyTaskSpec(
                    "weekly_key_week_focus", "key_week_focus"
                )
            ],
        )
        self.assertTrue(created)
        self.assertEqual(result["tasks"][0]["target"], "key_week_focus")
        self.session.expire_all()
        after_columns = self._ai_counts()
        self.assertEqual(
            after_columns["local_ai_inputs"], before["local_ai_inputs"] + 1
        )
        self.assertEqual(
            after_columns["local_ai_tasks"], before["local_ai_tasks"] + 1
        )

        with self.assertRaises(LocalMaterialContextRequired):
            weekly_ai_service.create_weekly_tasks(
                self.session,
                runtime=None,
                profile_id=self.profile.id,
                plan_id=self.plan_id,
                request_id=str(uuid.uuid4()),
                expected_draft_version=new_version,
                operation_kind=weekly_ai_service.MATERIALS,
                task_specs=[
                    weekly_ai_service.WeeklyTaskSpec(
                        "weekly_materials_generate", "materials"
                    )
                ],
            )
        self.session.expire_all()
        self.assertEqual(self._ai_counts(), after_columns)

    def test_columns_one_operation_and_active_conflict(self):
        specs = [
            weekly_ai_service.WeeklyTaskSpec("weekly_key_week_focus", "key_week_focus"),
            weekly_ai_service.WeeklyTaskSpec("weekly_environment_setup", "environment_setup"),
        ]
        result, created = self._create(weekly_ai_service.COLUMNS, specs)
        self.assertTrue(created)
        self.assertEqual(
            [item["target"] for item in result["tasks"]],
            ["key_week_focus", "environment_setup"],
        )
        op = self.session.scalars(
            select(LocalAIOperation).where(
                LocalAIOperation.operation_kind == weekly_ai_service.COLUMNS
            )
        ).one()
        tasks = self.session.scalars(
            select(LocalAITask).where(LocalAITask.weekly_plan_id == self.plan_id)
        ).all()
        self.assertEqual(len(tasks), 2)
        self.assertTrue(all(t.input_id for t in tasks))
        self.assertEqual(
            self.session.query(LocalAIInput)
            .filter(LocalAIInput.create_operation_id == op.id)
            .count(),
            2,
        )
        with self.assertRaises(LocalWeeklyAiTaskActive):
            self._create(
                weekly_ai_service.COLUMNS,
                [weekly_ai_service.WeeklyTaskSpec("weekly_key_week_focus", "key_week_focus")],
            )
        self.assertEqual(self.session.query(LocalAITask).count(), 2)

    def test_materials_missing_focus_has_no_receipt_or_task(self):
        with self.assertRaises(LocalMaterialContextRequired):
            self._create(
                weekly_ai_service.MATERIALS,
                [weekly_ai_service.WeeklyTaskSpec("weekly_materials_generate", "materials")],
            )
        self.assertEqual(
            self.session.query(LocalAIOperation)
            .filter(LocalAIOperation.operation_kind == weekly_ai_service.MATERIALS)
            .count(),
            0,
        )
        self.assertEqual(self.session.query(LocalAITask).count(), 0)
        self.assertEqual(self.session.query(LocalAIInput).count(), 0)

    def test_executor_claim_and_success_candidate_stay_weekly(self):
        self._succeed_games()

    def test_failed_weekly_task_retry_uses_weekly_preflight(self):
        result, _ = self._create(
            weekly_ai_service.GAMES,
            [weekly_ai_service.WeeklyTaskSpec("weekly_games_select", "games")],
        )
        task_id = result["tasks"][0]["task_id"]
        claim = ai_task_service.claim_next(
            self.runtime, now=ai_task_service._now(), started_ticks=1
        )
        self.assertIsNotNone(claim)
        self.assertTrue(
            ai_task_service.commit_dispatch_mark(
                self.session, claim, ai_task_service._now()
            )
        )
        self.assertTrue(
            ai_task_service.finalize_failure(
                self.session,
                claim,
                {"kind": "output_invalid", "reason": "output_invalid"},
                ai_task_service._now(),
            )
        )
        task = self.session.get(LocalAITask, task_id, populate_existing=True)
        self.assertEqual(task.status, "failed")
        retried = ai_task_service.retry_task(
            self.session,
            task_id=task_id,
            expected_execution_id=claim.execution_id,
            ack_duplicate_cost=True,
            request_id=str(uuid.uuid4()),
            runtime=self.runtime,
            source_kind="weekly_plan",
            weekly_plan_id=self.plan_id,
        )
        self.assertEqual(retried["status"], "pending")

    def test_candidate_list_and_detail_are_materialized_and_scoped(self):
        _task_id, candidate_id = self._succeed_games()
        listing = weekly_ai_candidates.list_candidates(
            self.session,
            profile_id=self.profile.id,
            plan_id=self.plan_id,
        )
        self.assertEqual([item["candidate_id"] for item in listing["items"]], [candidate_id])
        item = listing["items"][0]
        self.assertEqual(item["eligibility"], "eligible")
        self.assertEqual(item["target"], "games")
        self.assertIsNotNone(item["create_operation_id"])
        detail = weekly_ai_candidates.get_candidate(
            self.session,
            profile_id=self.profile.id,
            plan_id=self.plan_id,
            candidate_id=candidate_id,
        )
        self.assertIn("data", detail)
        self.assertIn("basis", detail)
        self.assertIn("outdoor_game_slots", detail["data"])
        with self.assertRaises(LocalAiNotFound):
            weekly_ai_candidates.get_candidate(
                self.session,
                profile_id=self.profile.id,
                plan_id="another-plan",
                candidate_id=candidate_id,
            )

    def test_corrupt_stored_candidate_is_storage_error_not_source_changed(self):
        _task_id, candidate_id = self._succeed_games()
        candidate = self.session.get(LocalAICandidate, candidate_id)
        candidate.raw_candidate_json = {"outdoor_game_slots": {}, "focus_area": None}
        self.session.commit()
        with self.assertRaises(LocalStorageError):
            weekly_ai_candidates.get_candidate(
                self.session,
                profile_id=self.profile.id,
                plan_id=self.plan_id,
                candidate_id=candidate_id,
            )

    def test_candidate_detail_reports_real_missing_inputs(self):
        result, _ = self._create(
            weekly_ai_service.COLUMNS,
            [
                weekly_ai_service.WeeklyTaskSpec(
                    "weekly_environment_setup", "environment_setup"
                )
            ],
        )
        claim = ai_task_service.claim_next(
            self.runtime, now=ai_task_service._now(), started_ticks=1
        )
        self.assertIsNotNone(claim)
        self.assertTrue(
            ai_task_service.commit_dispatch_mark(
                self.session, claim, ai_task_service._now()
            )
        )
        self.assertTrue(
            ai_task_service.finalize_success(
                self.session,
                claim,
                {"kind": "success", "candidate_text": '{"text":"环境建议"}'},
                ai_task_service._now(),
            )
        )
        candidate = self.session.scalars(
            select(LocalAICandidate).where(LocalAICandidate.task_id == claim.task_id)
        ).one()
        detail = weekly_ai_candidates.get_candidate(
            self.session,
            profile_id=self.profile.id,
            plan_id=self.plan_id,
            candidate_id=candidate.id,
        )
        self.assertIn(
            "no_selected_games_or_focus",
            [item["code"] for item in detail["unavailable_inputs"]],
        )
        self.assertEqual(detail["warnings"], [])

    def test_stored_chain_hash_and_operation_mismatches_are_storage_errors(self):
        _task_id, candidate_id = self._succeed_games()
        candidate = self.session.get(LocalAICandidate, candidate_id)
        input_row = self.session.get(LocalAIInput, candidate.input_id)
        operation = self.session.get(LocalAIOperation, input_row.create_operation_id)
        original = (
            candidate.candidate_hash,
            input_row.dependency_hash,
            dict(input_row.target_hashes_json),
            dict(operation.result_json),
        )
        for name in ("candidate", "dependency", "target", "operation"):
            if name == "candidate":
                candidate.candidate_hash = "0" * 64
            elif name == "dependency":
                input_row.dependency_hash = "0" * 64
            elif name == "target":
                input_row.target_hashes_json = {"games": "0" * 64}
            else:
                operation.result_json = {**operation.result_json, "weekly_plan_id": "other"}
            self.session.commit()
            with self.subTest(name=name):
                try:
                    weekly_ai_candidates.get_candidate(
                        self.session,
                        profile_id=self.profile.id,
                        plan_id=self.plan_id,
                        candidate_id=candidate_id,
                    )
                except LocalStorageError:
                    pass
                else:
                    self.fail(f"chain mismatch {name} was not rejected")
            self.session.expire_all()
            candidate = self.session.get(LocalAICandidate, candidate_id)
            input_row = self.session.get(LocalAIInput, candidate.input_id)
            operation = self.session.get(LocalAIOperation, input_row.create_operation_id)
            candidate.candidate_hash = original[0]
            input_row.dependency_hash = original[1]
            input_row.target_hashes_json = original[2]
            operation.result_json = original[3]
            self.session.commit()
            self.session.expire_all()

    def test_preview_readonly_and_atomic_adoption(self):
        _task_id, candidate_id = self._succeed_games()
        before = self.session.get(LocalWeeklyPlan, self.plan_id).current_draft_id
        preview = weekly_ai_adoption.preview_adoption(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            plan_id=self.plan_id,
            expected_draft_version=self.version,
            selections=[{"candidate_id": candidate_id, "target": "games"}],
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
        )
        self.assertEqual(preview["draft"]["id"], before)
        self.assertIn("collective_1", preview["before"]["games"]["outdoor_game_slots"])
        self.assertIsNotNone(self.session.get(LocalWeeklyPlan, self.plan_id))
        adopted = weekly_ai_adoption.adopt(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            plan_id=self.plan_id,
            request_id=str(uuid.uuid4()),
            expected_draft_version=self.version,
            preview_token=preview["preview_token"],
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
        )
        self.assertEqual(adopted["draft"]["version"], self.version + 1)
        content = self.session.get(LocalWeeklyPlanContent, adopted["draft"]["id"])
        self.assertEqual(content.schema_version, 2)
        self.assertIsNotNone(content.content_json["ai_provenance"]["games"])
        self.assertEqual(
            self.session.query(LocalWeeklyPlanAIAdoption)
            .filter(LocalWeeklyPlanAIAdoption.draft_id == content.id)
            .count(),
            1,
        )
        self.assertEqual(
            self.session.get(LocalWeeklyPlan, self.plan_id).current_draft_version,
            self.version + 1,
        )
        detail = weekly_plan_service.get_detail(
            self.session, profile_id=self.profile.id, plan_id=self.plan_id
        )
        self.assertIn("facts", detail)
        self.assertEqual(detail["draft"]["version"], self.version + 1)

    def test_current_weekly_prompt_heads_and_game_task_pin_contract2(self):
        expected = {
            "weekly_games_select": 2,
            "weekly_materials_generate": 2,
            "weekly_key_week_focus": 1,
            "weekly_environment_setup": 1,
            "weekly_habit_culture": 1,
            "weekly_home_cooperation": 1,
        }
        self.assertEqual(
            weekly_ai_contracts.prompt_contract_version("weekly_materials_generate"), 2
        )
        self.assertTrue(
            weekly_ai_contracts.supports_prompt_contract(
                "weekly_materials_generate", 1
            )
        )
        self.assertFalse(
            weekly_ai_contracts.supports_prompt_contract(
                "weekly_materials_generate", 99
            )
        )
        for task_type, contract in expected.items():
            head = self.session.get(
                LocalPersonalPromptHead, (self.profile.id, task_type)
            )
            version = self.session.get(
                LocalPersonalPromptVersion,
                (self.profile.id, task_type, head.current_revision),
            )
            self.assertEqual(head.required_contract_version, contract, task_type)
            self.assertEqual(head.latest_default_revision, 1, task_type)
            self.assertEqual(version.contract_version, contract, task_type)
            self.assertEqual(version.based_default_revision, 1, task_type)

        result, _ = self._create(
            weekly_ai_service.GAMES,
            [weekly_ai_service.WeeklyTaskSpec("weekly_games_select", "games")],
        )
        task_id = result["tasks"][0]["task_id"]
        claim = ai_task_service.claim_next(
            self.runtime, now=ai_task_service._now(), started_ticks=1
        )
        self.assertIsNotNone(claim)
        self.assertEqual(claim.task_id, task_id)
        self.assertEqual(claim.contract_version, 2)
        self.assertEqual(claim.default_revision, 1)
        self.assertEqual(self.session.get(LocalAIInput, claim.input_id).input_schema_version, 1)

    def test_materials_current_contract2_task_and_candidate_adoption(self):
        plan = self.session.get(LocalWeeklyPlan, self.plan_id)
        snapshot = weekly_plan_service._live_snapshot(self.session, plan)
        focus = next(
            candidate
            for candidate in weekly_plan_content.build_source_candidates(snapshot)
            if candidate["section"] == "post_group_games"
        )
        selector = {
            key: focus[key]
            for key in (
                "source_kind",
                "daily_plan_id",
                "content_id",
                "content_version",
                "content_hash",
                "section",
                "group_id",
                "game_id",
            )
        }
        saved = weekly_plan_service.save_draft(
            self.session,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            plan_id=self.plan_id,
            expected_draft_version=self.version,
            patch={"focus_area": selector},
        )
        material_version = saved["draft"]["version"]
        result, created = self._create(
            weekly_ai_service.MATERIALS,
            [
                weekly_ai_service.WeeklyTaskSpec(
                    "weekly_materials_generate", "materials"
                )
            ],
            version=material_version,
        )
        self.assertTrue(created)
        task_id = result["tasks"][0]["task_id"]
        claim = ai_task_service.claim_next(
            self.runtime, now=ai_task_service._now(), started_ticks=1
        )
        self.assertIsNotNone(claim)
        self.assertEqual(claim.task_type, "weekly_materials_generate")
        self.assertEqual(claim.contract_version, 2)
        self.assertEqual(claim.default_revision, 1)
        self.assertTrue(
            ai_task_service.commit_dispatch_mark(
                self.session, claim, ai_task_service._now()
            )
        )
        self.assertTrue(
            ai_task_service.finalize_success(
                self.session,
                claim,
                {"kind": "success", "candidate_text": '{"items":[]}'},
                ai_task_service._now(),
            )
        )
        candidate = self.session.scalars(
            select(LocalAICandidate).where(LocalAICandidate.task_id == task_id)
        ).one()
        self.assertEqual(candidate.contract_version, 2)
        preview = weekly_ai_adoption.preview_adoption(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            plan_id=self.plan_id,
            expected_draft_version=material_version,
            selections=[{"candidate_id": candidate.id, "target": "materials"}],
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
        )
        adopted = weekly_ai_adoption.adopt(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            plan_id=self.plan_id,
            request_id=str(uuid.uuid4()),
            expected_draft_version=material_version,
            preview_token=preview["preview_token"],
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
        )
        self.assertEqual(adopted["draft"]["version"], material_version + 1)
        content = self.session.get(LocalWeeklyPlanContent, adopted["draft"]["id"])
        self.assertEqual(content.content_json["materials"], "")

    def test_existing_personal_head_is_not_automatically_promoted(self):
        task_type = "weekly_games_select"
        head = self.session.get(LocalPersonalPromptHead, (self.profile.id, task_type))
        version = self.session.get(
            LocalPersonalPromptVersion,
            (self.profile.id, task_type, head.current_revision),
        )
        original_revision = head.current_revision
        original_guidance = dict(version.guidance_json)
        if self.session.get(LocalPromptBundle, (task_type, 1, 1)) is None:
            current_bundle = self.session.get(
                LocalPromptBundle,
                (task_type, head.required_contract_version, 1),
            )
            self.session.add(
                LocalPromptBundle(
                    task_type=task_type,
                    contract_version=1,
                    default_revision=1,
                    input_schema_json=dict(current_bundle.input_schema_json),
                    output_schema_json=dict(current_bundle.output_schema_json),
                    guidance_defaults_json=dict(current_bundle.guidance_defaults_json),
                    bundle_hash=current_bundle.bundle_hash,
                    created_at=current_bundle.created_at,
                )
            )
            self.session.flush()
        version.contract_version = 1
        version.based_default_revision = 1
        head.required_contract_version = 1
        head.latest_default_revision = 1
        self.session.commit()

        prompt_bundles.sync_prompt_bundles(self.session)
        self.session.expire_all()
        head = self.session.get(LocalPersonalPromptHead, (self.profile.id, task_type))
        version = self.session.get(
            LocalPersonalPromptVersion,
            (self.profile.id, task_type, head.current_revision),
        )
        self.assertEqual(head.required_contract_version, 2)
        self.assertEqual(head.latest_default_revision, 1)
        self.assertEqual(head.current_revision, original_revision)
        self.assertEqual(version.contract_version, 1)
        self.assertEqual(version.guidance_json, original_guidance)
        with self.assertRaises(LocalPromptAdaptationRequired):
            self._create(
                weekly_ai_service.GAMES,
                [weekly_ai_service.WeeklyTaskSpec("weekly_games_select", "games")],
            )

    def test_wrong_plan_scope_is_not_found(self):
        result, _ = self._create(
            weekly_ai_service.GAMES,
            [weekly_ai_service.WeeklyTaskSpec("weekly_games_select", "games")],
        )
        task_id = result["tasks"][0]["task_id"]
        with self.assertRaises(LocalAiNotFound):
            ai_task_service.get_task(
                self.session,
                task_id,
                source_kind="weekly_plan",
                weekly_plan_id="another-plan",
            )



    def test_stored_chain_ownership_type_and_schema_mismatches_are_storage_errors(self):
        _task_id, candidate_id = self._succeed_games()
        cases = [
            ("task_week", "task", "weekly_plan_id", "other-week"),
            ("execution_week", "execution", "weekly_plan_id", "other-week"),
            ("input_week", "input", "weekly_plan_id", "other-week"),
            ("task_type", "candidate", "task_type", "weekly_environment_setup"),
            ("contract", "candidate", "contract_version", 1),
            ("schema", "candidate", "schema_version", 2),
            ("execution_input", "execution", "input_id", "other-input"),
            ("task_input", "task", "input_id", "other-input"),
        ]
        for name, kind, attr, value in cases:
            self.session.rollback()
            candidate = self.session.get(LocalAICandidate, candidate_id)
            task = self.session.get(LocalAITask, candidate.task_id)
            execution = self.session.get(LocalAIExecution, candidate.execution_id)
            input_row = self.session.get(LocalAIInput, candidate.input_id)
            target = {
                "candidate": candidate,
                "task": task,
                "execution": execution,
                "input": input_row,
            }[kind]
            setattr(target, attr, value)
            with self.subTest(name=name):
                try:
                    weekly_ai_candidates.get_candidate(
                        self.session,
                        profile_id=self.profile.id,
                        plan_id=self.plan_id,
                        candidate_id=candidate_id,
                    )
                except LocalStorageError:
                    pass
                else:
                    self.fail(f"chain mismatch {name} was not rejected")
        self.session.rollback()



    def test_corrupt_stored_input_is_storage_error_in_list_detail_preview_and_adopt(self):
        _task_id, candidate_id = self._succeed_games()
        candidate = self.session.get(LocalAICandidate, candidate_id)
        input_row = self.session.get(LocalAIInput, candidate.input_id)
        original_payload = dict(input_row.payload_json)
        original_deps = json.loads(json.dumps(input_row.dependencies_json))
        mutations = []
        payload_missing = dict(original_payload)
        payload_missing.pop(next(iter(payload_missing)))
        mutations.append(("payload_missing", payload_missing, original_deps))
        payload_value = json.loads(json.dumps(original_payload))
        payload_value["grade"] = "tampered"
        mutations.append(("payload_value", payload_value, original_deps))
        manifest_plan = json.loads(json.dumps(original_deps))
        manifest_plan["_server_manifest"]["plan"]["draft_version"] += 1
        mutations.append(("manifest_plan", original_payload, manifest_plan))
        manifest_extra = json.loads(json.dumps(original_deps))
        existing_handles = original_deps["_server_manifest"]["handles"]
        if existing_handles:
            manifest_extra["_server_manifest"]["handles"]["z99"] = json.loads(
                json.dumps(next(iter(existing_handles.values())))
            )
            mutations.append(("manifest_extra", original_payload, manifest_extra))
        basis = json.loads(json.dumps(original_deps))
        if basis["config"]:
            basis["config"][0]["guidance"] = "tampered"
            mutations.append(("basis_guidance", original_payload, basis))
        for name, payload, deps in mutations:
            input_row.payload_json = payload
            input_row.dependencies_json = deps
            self.session.commit()
            with self.subTest(name=name):
                with self.assertRaises(LocalStorageError):
                    weekly_ai_candidates.get_candidate(
                        self.session,
                        profile_id=self.profile.id,
                        plan_id=self.plan_id,
                        candidate_id=candidate_id,
                    )
                with self.assertRaises(LocalStorageError):
                    weekly_ai_candidates.list_candidates(
                        self.session,
                        profile_id=self.profile.id,
                        plan_id=self.plan_id,
                    )
                with self.assertRaises(LocalStorageError):
                    weekly_ai_adoption.preview_adoption(
                        self.session,
                        runtime=self.runtime,
                        profile_id=self.profile.id,
                        plan_id=self.plan_id,
                        expected_draft_version=self.version,
                        selections=[{"candidate_id": candidate_id, "target": "games"}],
                        launch_id=self.runtime.launch_id,
                        session_scope_hash="scope",
                    )
            self.session.rollback()
            input_row = self.session.get(LocalAIInput, candidate.input_id)
            input_row.payload_json = original_payload
            input_row.dependencies_json = original_deps
            self.session.commit()
        preview = weekly_ai_adoption.preview_adoption(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            plan_id=self.plan_id,
            expected_draft_version=self.version,
            selections=[{"candidate_id": candidate_id, "target": "games"}],
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
        )
        input_row = self.session.get(LocalAIInput, candidate.input_id)
        input_row.payload_json = payload_value
        self.session.commit()
        with self.assertRaises(LocalStorageError):
            weekly_ai_adoption.adopt(
                self.session,
                runtime=self.runtime,
                profile_id=self.profile.id,
                plan_id=self.plan_id,
                request_id=str(uuid.uuid4()),
                expected_draft_version=self.version,
                preview_token=preview["preview_token"],
                launch_id=self.runtime.launch_id,
                session_scope_hash="scope",
            )
        self.session.expire_all()
        self.assertEqual(
            self.session.get(LocalWeeklyPlan, self.plan_id).current_draft_version,
            self.version,
        )
        self.assertEqual(
            self.session.query(LocalWeeklyPlanAIAdoption)
            .filter(LocalWeeklyPlanAIAdoption.weekly_plan_id == self.plan_id)
            .count(),
            0,
        )

    def test_claim_refuses_corrupt_stored_input_before_creating_execution(self):
        result, _ = self._create(
            weekly_ai_service.GAMES,
            [weekly_ai_service.WeeklyTaskSpec("weekly_games_select", "games")],
        )
        task_id = result["tasks"][0]["task_id"]
        task = self.session.get(LocalAITask, task_id)
        input_row = self.session.get(LocalAIInput, task.input_id)
        input_row.payload_json = {**dict(input_row.payload_json), "grade": "tampered"}
        self.session.commit()
        with self.assertRaises(LocalStorageError):
            ai_task_service.claim_next(
                self.runtime, now=ai_task_service._now(), started_ticks=1
            )
        self.session.expire_all()
        self.assertEqual(self.session.get(LocalAITask, task_id).status, "pending")
        self.assertEqual(
            self.session.query(LocalAIExecution)
            .filter(LocalAIExecution.task_id == task_id)
            .count(),
            0,
        )
        self.assertEqual(
            self.session.query(LocalAIAttempt).count(),
            0,
        )

    def test_operation_task_mapping_is_part_of_the_candidate_chain(self):
        _task_id, candidate_id = self._succeed_games()
        candidate = self.session.get(LocalAICandidate, candidate_id)
        input_row = self.session.get(LocalAIInput, candidate.input_id)
        operation = self.session.get(LocalAIOperation, input_row.create_operation_id)
        broken = dict(operation.result_json)
        broken["tasks"] = []
        operation.result_json = broken
        self.session.commit()
        with self.assertRaises(LocalStorageError):
            weekly_ai_candidates.get_candidate(
                self.session,
                profile_id=self.profile.id,
                plan_id=self.plan_id,
                candidate_id=candidate_id,
            )


class WeeklyAIBarrierTests(WeeklyAIServiceFixture):
    def _lease(self):
        barrier = backup_barrier.get_barrier(self.runtime.db_path.parent)
        lease = barrier.begin_intent("test-close")
        self.addCleanup(lease.release)
        return barrier, lease

    def test_new_create_is_refused_under_intent_and_exclusive_replay_is_read_only(self):
        rid = str(uuid.uuid4())
        first, created = self._create(
            weekly_ai_service.GAMES,
            [weekly_ai_service.WeeklyTaskSpec("weekly_games_select", "games")],
            request_id=rid,
        )
        self.assertTrue(created)
        barrier, lease = self._lease()
        replay, created2 = self._create(
            weekly_ai_service.GAMES,
            [weekly_ai_service.WeeklyTaskSpec("weekly_games_select", "games")],
            request_id=rid,
        )
        self.assertFalse(created2)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["tasks"], first["tasks"])
        with self.assertRaises(backup_barrier.SnapshotBusy):
            self._create(
                weekly_ai_service.COLUMNS,
                [
                    weekly_ai_service.WeeklyTaskSpec(
                        "weekly_key_week_focus", "key_week_focus"
                    )
                ],
                request_id=str(uuid.uuid4()),
            )
        barrier.wait_idle(lease)
        barrier.acquire_exclusive(lease)
        with self.assertRaises(backup_barrier.SnapshotBusy):
            self._create(
                weekly_ai_service.COLUMNS,
                [
                    weekly_ai_service.WeeklyTaskSpec(
                        "weekly_key_week_focus", "key_week_focus"
                    )
                ],
                request_id=str(uuid.uuid4()),
            )
        replay2, created3 = self._create(
            weekly_ai_service.GAMES,
            [weekly_ai_service.WeeklyTaskSpec("weekly_games_select", "games")],
            request_id=rid,
        )
        self.assertFalse(created3)
        self.assertTrue(replay2["replayed"])
        self.assertEqual(
            self.session.query(LocalAIOperation)
            .filter(LocalAIOperation.operation_kind == weekly_ai_service.GAMES)
            .count(),
            1,
        )

    def test_adopt_is_refused_under_intent_without_consuming_token(self):
        _task_id, candidate_id = self._succeed_games()
        preview = weekly_ai_adoption.preview_adoption(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            plan_id=self.plan_id,
            expected_draft_version=self.version,
            selections=[{"candidate_id": candidate_id, "target": "games"}],
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
        )
        _barrier, _lease = self._lease()
        with self.assertRaises(backup_barrier.SnapshotBusy):
            weekly_ai_adoption.adopt(
                self.session,
                runtime=self.runtime,
                profile_id=self.profile.id,
                plan_id=self.plan_id,
                request_id=str(uuid.uuid4()),
                expected_draft_version=self.version,
                preview_token=preview["preview_token"],
                launch_id=self.runtime.launch_id,
                session_scope_hash="scope",
            )
        self.session.expire_all()
        self.assertEqual(
            self.session.get(LocalWeeklyPlan, self.plan_id).current_draft_version,
            self.version,
        )
        self.assertEqual(
            self.session.query(LocalWeeklyPlanContent)
            .filter(LocalWeeklyPlanContent.weekly_plan_id == self.plan_id)
            .count(),
            1,
        )

    def test_close_snapshot_counts_weekly_source_and_revokes_unsent(self):
        result, _ = self._create(
            weekly_ai_service.GAMES,
            [weekly_ai_service.WeeklyTaskSpec("weekly_games_select", "games")],
        )
        task_id = result["tasks"][0]["task_id"]
        snapshot = ai_task_service.active_task_snapshot(self.session)
        self.assertGreaterEqual(snapshot["live"], 1)
        self.assertEqual(snapshot["counts"].get("pending"), 1)
        counts = ai_task_service.revoke_all_for_close(
            self.session, now=ai_task_service._now()
        )
        self.assertGreaterEqual(counts["paused"], 1)
        self.session.expire_all()
        task = self.session.get(LocalAITask, task_id)
        self.assertEqual(task.status, "paused")
        self.assertEqual(task.reason, "user_stop")
        self.assertEqual(
            (task.runtime_meta_json or {}).get("processing_certainty"), "not_sent"
        )
        self.assertEqual(
            self.session.query(LocalAICandidate)
            .filter(LocalAICandidate.task_id == task_id)
            .count(),
            0,
        )


class WeeklyAIExecutorTests(WeeklyAIServiceFixture):
    """WAI21-28: real weekly tasks through the real executor + scripted worker."""

    def test_wai21_partial_success_keeps_success_and_never_resends_invalid(self):
        executor, trace = self._start_weekly_executor("w3weekly|mixed_columns")
        task_a = self._submit(
            executor,
            weekly_ai_service.COLUMNS,
            [
                weekly_ai_service.WeeklyTaskSpec("weekly_key_week_focus", "key_week_focus"),
                weekly_ai_service.WeeklyTaskSpec(
                    "weekly_environment_setup", "environment_setup"
                ),
            ],
        )
        # The second task in the same operation is the sibling job.
        session = self.runtime.session()
        try:
            sibling = session.scalars(
                select(LocalAITask).where(
                    LocalAITask.weekly_plan_id == self.plan_id,
                    LocalAITask.id != task_a,
                )
            ).one()
            task_b = sibling.id
        finally:
            session.close()
        self.assertEqual(
            self._wait_task_status(task_a, {"succeeded", "failed", "paused"}), "succeeded"
        )
        self.assertEqual(self._wait_task_status(task_b, {"failed", "paused"}), "failed")
        session = self.runtime.session()
        try:
            self.assertEqual(
                session.query(LocalAICandidate)
                .filter(LocalAICandidate.task_id == task_a)
                .count(),
                1,
            )
            self.assertEqual(
                session.query(LocalAICandidate)
                .filter(LocalAICandidate.task_id == task_b)
                .count(),
                0,
            )
            self.assertEqual(
                session.query(LocalAIAttempt)
                .filter(LocalAIAttempt.execution_id.in_(
                    select(LocalAIExecution.id).where(
                        LocalAIExecution.task_id.in_([task_a, task_b])
                    )
                ))
                .count(),
                2,
            )
        finally:
            session.close()
        events = self._trace(trace)
        self.assertEqual([event["event"] for event in events].count("send"), 2)
        time.sleep(0.6)
        self.assertEqual([event["event"] for event in self._trace(trace)].count("send"), 2)

    def _assert_terminal(
        self, task_id: str, status: str, *, reason: str, certainty: str, sends: int, task_trace
    ):
        self.assertEqual(self._wait_task_status(task_id, {status}), status)
        session = self.runtime.session()
        try:
            task = session.get(LocalAITask, task_id, populate_existing=True)
            self.assertEqual(task.reason, reason)
            self.assertEqual(
                (task.runtime_meta_json or {}).get("processing_certainty"), certainty
            )
            self.assertEqual(
                session.query(LocalAICandidate)
                .filter(LocalAICandidate.task_id == task_id)
                .count(),
                0,
            )
            attempts = session.query(LocalAIAttempt).filter(
                LocalAIAttempt.execution_id == task.current_execution_id
            ).count()
            self.assertEqual(attempts, 1)
        finally:
            session.close()
        events = self._trace(task_trace)
        self.assertEqual([event["event"] for event in events].count("send"), sends)

    def test_wai24_auth_401_pauses_without_candidate(self):
        executor, trace = self._start_weekly_executor("w3weekly|after_send|auth401")
        task_id = self._submit(executor)
        self._assert_terminal(
            task_id,
            "paused",
            reason="auth_rejected",
            certainty="unknown",
            sends=1,
            task_trace=trace,
        )
        session = self.runtime.session()
        try:
            state = session.get(LocalAIState, self.profile.id, populate_existing=True)
            self.assertEqual(state.blocked_config_version, 2)
        finally:
            session.close()

    def test_wai24_auth_403_pauses_without_candidate(self):
        executor, trace = self._start_weekly_executor("w3weekly|after_send|auth403")
        task_id = self._submit(executor)
        self._assert_terminal(
            task_id,
            "paused",
            reason="auth_rejected",
            certainty="unknown",
            sends=1,
            task_trace=trace,
        )

    def test_wai24_rate_limit_pauses_unknown_and_never_resends(self):
        executor, trace = self._start_weekly_executor("w3weekly|after_send|rate_limit")
        task_id = self._submit(executor)
        self._assert_terminal(
            task_id,
            "paused",
            reason="rate_limited",
            certainty="unknown",
            sends=1,
            task_trace=trace,
        )
        time.sleep(0.6)
        self.assertEqual([event["event"] for event in self._trace(trace)].count("send"), 1)

    def test_wai24_provider_5xx_is_outcome_unknown(self):
        executor, trace = self._start_weekly_executor(
            "w3weekly|after_send|provider_error"
        )
        task_id = self._submit(executor)
        self._assert_terminal(
            task_id,
            "outcome_unknown",
            reason="provider_error",
            certainty="unknown",
            sends=1,
            task_trace=trace,
        )

    def test_wai24_timeout_after_send_is_unknown_with_one_send(self):
        executor, trace = self._start_weekly_executor("w3weekly|after_send|silent")
        with mock.patch.object(ai_transport, "ATTEMPT_BUDGET_MS", 4000):
            task_id = self._submit(executor)
            self._assert_terminal(
                task_id,
                "outcome_unknown",
                reason="timeout_after_dispatch",
                certainty="unknown",
                sends=1,
                task_trace=trace,
            )
        time.sleep(0.5)
        self.assertEqual([event["event"] for event in self._trace(trace)].count("send"), 1)

    def test_wai24_invalid_output_fails_without_auto_repair(self):
        executor, trace = self._start_weekly_executor("w3weekly|after_send|invalid")
        task_id = self._submit(executor)
        self._assert_terminal(
            task_id,
            "failed",
            reason="output_invalid",
            certainty="response_received",
            sends=1,
            task_trace=trace,
        )

    def _make_due(self, task_id: str, executor: AiExecutor) -> None:
        session = self.runtime.session()
        try:
            task = session.get(LocalAITask, task_id, populate_existing=True)
            meta = dict(task.runtime_meta_json or {})
            next_at = datetime.fromisoformat(meta["next_attempt_at"])
            meta["next_attempt_at"] = (
                next_at - timedelta(seconds=60)
            ).isoformat()
            task.runtime_meta_json = meta
            session.commit()
        finally:
            session.close()
        executor.notify()

    def _attempt_count(self, task_id: str) -> int:
        session = self.runtime.session()
        try:
            task = session.get(LocalAITask, task_id, populate_existing=True)
            return (
                session.query(LocalAIAttempt)
                .filter(LocalAIAttempt.execution_id == task.current_execution_id)
                .count()
            )
        finally:
            session.close()

    def test_wai23_pre_send_connection_failures_retry_exactly_three_times(self):
        executor, trace = self._start_weekly_executor("w3weekly|pre_send")
        task_id = self._submit(executor)
        self.assertEqual(
            self._wait_task_status(task_id, {"retry_wait", "failed"}), "retry_wait"
        )
        session = self.runtime.session()
        try:
            task = session.get(LocalAITask, task_id, populate_existing=True)
            meta = task.runtime_meta_json
            delay = datetime.fromisoformat(meta["next_attempt_at"]) - task.updated_at
            self.assertGreaterEqual(delay.total_seconds(), 4.9)
            self.assertLessEqual(delay.total_seconds(), 5.1)
        finally:
            session.close()
        self.assertEqual(self._attempt_count(task_id), 1)
        self._make_due(task_id, executor)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and self._attempt_count(task_id) < 2:
            time.sleep(0.05)
        self.assertEqual(self._attempt_count(task_id), 2)
        self.assertEqual(
            self._wait_task_status(task_id, {"retry_wait", "failed"}), "retry_wait"
        )
        session = self.runtime.session()
        try:
            task = session.get(LocalAITask, task_id, populate_existing=True)
            self.assertEqual(task.status, "retry_wait")
            meta = task.runtime_meta_json
            delay = datetime.fromisoformat(meta["next_attempt_at"]) - task.updated_at
            self.assertGreaterEqual(delay.total_seconds(), 29.9)
            self.assertLessEqual(delay.total_seconds(), 30.1)
        finally:
            session.close()
        self._make_due(task_id, executor)
        self.assertEqual(self._wait_task_status(task_id, {"failed"}), "failed")
        session = self.runtime.session()
        try:
            task = session.get(LocalAITask, task_id, populate_existing=True)
            self.assertEqual(task.reason, "connection_unavailable")
            self.assertEqual(
                (task.runtime_meta_json or {}).get("processing_certainty"), "not_sent"
            )
            self.assertEqual(
                session.query(LocalAICandidate)
                .filter(LocalAICandidate.task_id == task_id)
                .count(),
                0,
            )
        finally:
            session.close()
        self.assertEqual(self._attempt_count(task_id), 3)
        events = self._trace(trace)
        self.assertEqual([item["event"] for item in events].count("pre_send"), 3)
        self.assertEqual([item["event"] for item in events].count("send"), 0)

    def test_wai25_retry_requires_ack_and_creates_new_generation_only(self):
        executor, trace = self._start_weekly_executor("w3weekly|after_send|silent")
        with mock.patch.object(ai_transport, "ATTEMPT_BUDGET_MS", 4000):
            task_id = self._submit(executor)
            self.assertEqual(
                self._wait_task_status(task_id, {"outcome_unknown"}),
                "outcome_unknown",
            )
        session = self.runtime.session()
        try:
            task = session.get(LocalAITask, task_id, populate_existing=True)
            old_execution_id = task.current_execution_id
            old_attempt = (
                session.query(LocalAIAttempt)
                .filter(LocalAIAttempt.execution_id == old_execution_id)
                .one()
            )
            self.assertEqual(old_attempt.dispatch_marked_at is not None, True)
        finally:
            session.close()
        with self.assertRaises(LocalAiRetryAckRequired):
            ai_task_service.retry_task(
                self.session,
                task_id=task_id,
                expected_execution_id=old_execution_id,
                ack_duplicate_cost=False,
                request_id=str(uuid.uuid4()),
                runtime=self.runtime,
                source_kind="weekly_plan",
                weekly_plan_id=self.plan_id,
            )
        self._configure_model("w3weekly|success")
        retried = ai_task_service.retry_task(
            self.session,
            task_id=task_id,
            expected_execution_id=old_execution_id,
            ack_duplicate_cost=True,
            request_id=str(uuid.uuid4()),
            runtime=self.runtime,
            source_kind="weekly_plan",
            weekly_plan_id=self.plan_id,
        )
        self.assertEqual(retried["status"], "pending")
        executor.notify()
        self.assertEqual(self._wait_task_status(task_id, {"succeeded"}), "succeeded")
        session = self.runtime.session()
        try:
            task = session.get(LocalAITask, task_id, populate_existing=True)
            self.assertEqual(task.generation, 2)
            self.assertNotEqual(task.current_execution_id, old_execution_id)
            old = session.get(LocalAIExecution, old_execution_id)
            self.assertEqual(old.state, "outcome_unknown")
            self.assertIsNotNone(old.ended_at)
            self.assertEqual(
                session.query(LocalAICandidate)
                .filter(LocalAICandidate.task_id == task_id)
                .count(),
                1,
            )
        finally:
            session.close()
        events = self._trace(trace)
        self.assertEqual([item["event"] for item in events].count("send"), 2)

    def test_wai27_local_commit_failure_retries_only_the_commit(self):
        executor, trace = self._start_weekly_executor("w3weekly|success")
        original = ai_task_service.finalize_success
        calls: list[int] = []

        def flaky(*args, **kwargs):
            calls.append(1)
            if len(calls) <= 2:
                raise RuntimeError("db unavailable")
            return original(*args, **kwargs)

        with mock.patch.object(ai_task_service, "finalize_success", side_effect=flaky):
            task_id = self._submit(executor)
            self.assertEqual(self._wait_task_status(task_id, {"succeeded"}), "succeeded")
        session = self.runtime.session()
        try:
            self.assertEqual(
                session.query(LocalAICandidate)
                .filter(LocalAICandidate.task_id == task_id)
                .count(),
                1,
            )
            task = session.get(LocalAITask, task_id, populate_existing=True)
            self.assertEqual(
                session.query(LocalAIAttempt)
                .filter(LocalAIAttempt.execution_id == task.current_execution_id)
                .count(),
                1,
            )
        finally:
            session.close()
        self.assertGreaterEqual(len(calls), 3)
        events = self._trace(trace)
        self.assertEqual([item["event"] for item in events].count("send"), 1)

    def test_wai27_unpersistable_result_keeps_unknown_without_resend(self):
        executor, trace = self._start_weekly_executor("w3weekly|success")
        with mock.patch.object(
            ai_task_service, "finalize_success", side_effect=RuntimeError("db down")
        ):
            task_id = self._submit(executor)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if executor.active_snapshot()["pending_persist"]:
                    break
                time.sleep(0.05)
            self.assertEqual(executor.active_snapshot()["pending_persist"], 1)
            self.assertFalse(executor.is_runnable())
            self.assertEqual(self._wait_task_status(task_id, {"dispatching"}), "dispatching")
            session = self.runtime.session()
            try:
                self.assertEqual(
                    session.query(LocalAICandidate)
                    .filter(LocalAICandidate.task_id == task_id)
                    .count(),
                    0,
                )
            finally:
                session.close()
            executor.stop()
        recovery = ai_task_service.recover_on_start(
            self.session, now=ai_task_service._now()
        )
        self.assertGreaterEqual(recovery["unknown"], 1)
        session = self.runtime.session()
        try:
            task = session.get(LocalAITask, task_id, populate_existing=True)
            self.assertEqual(task.status, "outcome_unknown")
            self.assertEqual(task.reason, "restart")
            self.assertEqual(
                (task.runtime_meta_json or {}).get("processing_certainty"), "unknown"
            )
            self.assertEqual(
                session.query(LocalAICandidate)
                .filter(LocalAICandidate.task_id == task_id)
                .count(),
                0,
            )
        finally:
            session.close()
        events = self._trace(trace)
        self.assertEqual([item["event"] for item in events].count("send"), 1)

    def _claim_weekly(self):
        claim = ai_task_service.claim_next(
            self.runtime, now=ai_task_service._now(), started_ticks=1
        )
        self.assertIsNotNone(claim)
        self.assertTrue(
            ai_task_service.commit_dispatch_mark(
                self.session, claim, ai_task_service._now()
            )
        )
        return claim

    def test_wai26_cancel_wins_then_late_success_writes_no_candidate(self):
        result, _ = self._create(
            weekly_ai_service.GAMES,
            [weekly_ai_service.WeeklyTaskSpec("weekly_games_select", "games")],
        )
        task_id = result["tasks"][0]["task_id"]
        claim = self._claim_weekly()
        cancelled, _abort_id, abort_kind = ai_task_service.cancel_task(
            self.session,
            task_id=task_id,
            expected_execution_id=claim.execution_id,
            request_id=str(uuid.uuid4()),
            source_kind="weekly_plan",
            weekly_plan_id=self.plan_id,
        )
        self.assertEqual(cancelled["status"], "outcome_unknown")
        self.assertEqual(abort_kind, "stop_wait")
        self.assertFalse(
            ai_task_service.finalize_success(
                self.session,
                claim,
                {"kind": "success", "candidate_text": '{"text":"late"}'},
                ai_task_service._now(),
            )
        )
        self.session.expire_all()
        self.assertEqual(
            self.session.query(LocalAICandidate)
            .filter(LocalAICandidate.task_id == task_id)
            .count(),
            0,
        )
        self.assertEqual(
            self.session.get(LocalAITask, task_id).status, "outcome_unknown"
        )

    def test_wai26_success_wins_then_cancel_reads_actual_success(self):
        result, _ = self._create(
            weekly_ai_service.GAMES,
            [weekly_ai_service.WeeklyTaskSpec("weekly_games_select", "games")],
        )
        task_id = result["tasks"][0]["task_id"]
        claim = self._claim_weekly()
        text = (
            '{"outdoor_game_slots":{"collective_1":null,"collective_2":null,'
            '"free_choice_1":null},"focus_area":null}'
        )
        self.assertTrue(
            ai_task_service.finalize_success(
                self.session,
                claim,
                {"kind": "success", "candidate_text": text},
                ai_task_service._now(),
            )
        )
        cancelled, _abort_id, abort_kind = ai_task_service.cancel_task(
            self.session,
            task_id=task_id,
            expected_execution_id=claim.execution_id,
            request_id=str(uuid.uuid4()),
            source_kind="weekly_plan",
            weekly_plan_id=self.plan_id,
        )
        self.assertEqual(cancelled["status"], "succeeded")
        self.assertEqual(abort_kind, "none")
        self.assertFalse(
            ai_task_service.finalize_success(
                self.session,
                claim,
                {"kind": "success", "candidate_text": text},
                ai_task_service._now(),
            )
        )
        self.session.expire_all()
        self.assertEqual(
            self.session.query(LocalAICandidate)
            .filter(LocalAICandidate.task_id == task_id)
            .count(),
            1,
        )

    def test_wai26_old_permit_and_generation_never_revive(self):
        result, _ = self._create(
            weekly_ai_service.GAMES,
            [weekly_ai_service.WeeklyTaskSpec("weekly_games_select", "games")],
        )
        task_id = result["tasks"][0]["task_id"]
        old = self._claim_weekly()
        cancelled, _abort_id, _kind = ai_task_service.cancel_task(
            self.session,
            task_id=task_id,
            expected_execution_id=old.execution_id,
            request_id=str(uuid.uuid4()),
            source_kind="weekly_plan",
            weekly_plan_id=self.plan_id,
        )
        self.assertEqual(cancelled["status"], "outcome_unknown")
        retried = ai_task_service.retry_task(
            self.session,
            task_id=task_id,
            expected_execution_id=old.execution_id,
            ack_duplicate_cost=True,
            request_id=str(uuid.uuid4()),
            runtime=self.runtime,
            source_kind="weekly_plan",
            weekly_plan_id=self.plan_id,
        )
        self.assertEqual(retried["status"], "pending")
        new = self._claim_weekly()
        self.assertEqual(new.generation, old.generation + 1)
        self.assertFalse(
            ai_task_service.commit_dispatch_mark(
                self.session, old, ai_task_service._now()
            )
        )
        self.assertFalse(
            ai_task_service.finalize_success(
                self.session,
                old,
                {"kind": "success", "candidate_text": '{"text":"old"}'},
                ai_task_service._now(),
            )
        )
        self.session.expire_all()
        self.assertEqual(
            self.session.query(LocalAICandidate)
            .filter(LocalAICandidate.task_id == task_id)
            .count(),
            0,
        )
        self.assertEqual(self.session.get(LocalAITask, task_id).generation, 2)

    def test_wai28_restart_classifies_by_persisted_send_evidence_and_never_sends(self):
        def create():
            result, _ = self._create(
                weekly_ai_service.GAMES,
                [weekly_ai_service.WeeklyTaskSpec("weekly_games_select", "games")],
            )
            return result["tasks"][0]["task_id"]

        pending = create()
        pending_recovery = ai_task_service.recover_on_start(
            self.session, now=ai_task_service._now()
        )
        self.assertGreaterEqual(pending_recovery["paused"], 1)
        claimed = create()
        claimed_claim = ai_task_service.claim_next(
            self.runtime, now=ai_task_service._now(), started_ticks=1
        )
        self.assertIsNotNone(claimed_claim)
        claimed_recovery = ai_task_service.recover_on_start(
            self.session, now=ai_task_service._now()
        )
        self.assertGreaterEqual(claimed_recovery["paused"], 1)
        dispatched = create()
        dispatched_claim = self._claim_weekly()
        dispatched_recovery = ai_task_service.recover_on_start(
            self.session, now=ai_task_service._now()
        )
        self.assertGreaterEqual(dispatched_recovery["unknown"], 1)
        succeeded = create()
        success_claim = self._claim_weekly()
        text = (
            '{"outdoor_game_slots":{"collective_1":null,"collective_2":null,'
            '"free_choice_1":null},"focus_area":null}'
        )
        self.assertTrue(
            ai_task_service.finalize_success(
                self.session,
                success_claim,
                {"kind": "success", "candidate_text": text},
                ai_task_service._now(),
            )
        )
        final = ai_task_service.recover_on_start(
            self.session, now=ai_task_service._now()
        )
        self.assertEqual(final["unknown"], 0)
        self.session.expire_all()
        self.assertEqual(self.session.get(LocalAITask, pending).status, "paused")
        self.assertEqual(self.session.get(LocalAITask, pending).reason, "restart")
        self.assertEqual(self.session.get(LocalAITask, claimed).status, "paused")
        self.assertEqual(self.session.get(LocalAITask, claimed).reason, "restart")
        self.assertEqual(
            self.session.get(LocalAITask, dispatched).status, "outcome_unknown"
        )
        self.assertEqual(self.session.get(LocalAITask, dispatched).reason, "restart")
        self.assertEqual(self.session.get(LocalAITask, succeeded).status, "succeeded")
        self.assertEqual(
            self.session.query(LocalAICandidate)
            .filter(LocalAICandidate.task_id == succeeded)
            .count(),
            1,
        )
        for task_id in (pending, claimed, dispatched):
            self.assertEqual(
                self.session.query(LocalAICandidate)
                .filter(LocalAICandidate.task_id == task_id)
                .count(),
                0,
            )
        executor, trace = self._start_weekly_executor("w3weekly|success")
        time.sleep(0.6)
        self.assertEqual(self._trace(trace), [])
        self.assertTrue(
            ai_task_service.commit_dispatch_mark(
                self.session, dispatched_claim, ai_task_service._now()
            )
            is False
        )
        executor.stop()

    def test_wai22_truncated_success_response_is_unknown_not_candidate(self):
        executor, trace = self._start_weekly_executor("w3weekly|after_send|truncated")
        with mock.patch.object(ai_transport, "ATTEMPT_BUDGET_MS", 4000):
            task_id = self._submit(executor)
            self._assert_terminal(
                task_id,
                "outcome_unknown",
                reason="timeout_after_dispatch",
                certainty="unknown",
                sends=1,
                task_trace=trace,
            )

    def test_wai23_retry_revalidates_source_before_second_attempt(self):
        executor, trace = self._start_weekly_executor("w3weekly|pre_send")
        task_id = self._submit(executor)
        self.assertEqual(
            self._wait_task_status(task_id, {"retry_wait"}), "retry_wait"
        )
        daily = self.session.scalars(select(LocalDailyPlan)).first()
        daily_plan_service.save(
            self.session,
            plan_id=daily.id,
            expected_content_version=1,
            adopted_content={
                "morning_talk": {"topic": "来源已变化"},
                "group_activity": {
                    "theme": "新活动",
                    "objectives": "观察",
                    "process": "过程",
                },
            },
        )
        self._make_due(task_id, executor)
        self.assertEqual(
            self._wait_task_status(task_id, {"paused"}), "paused"
        )
        session = self.runtime.session()
        try:
            task = session.get(LocalAITask, task_id, populate_existing=True)
            self.assertEqual(task.reason, "source_changed")
            self.assertEqual(self._attempt_count(task_id), 1)
        finally:
            session.close()
        events = self._trace(trace)
        self.assertEqual([item["event"] for item in events].count("pre_send"), 1)
        self.assertEqual([item["event"] for item in events].count("send"), 0)

    def test_wai21_pending_cancel_before_claim_sends_nothing(self):
        result, _ = self._create(
            weekly_ai_service.GAMES,
            [weekly_ai_service.WeeklyTaskSpec("weekly_games_select", "games")],
        )
        task_id = result["tasks"][0]["task_id"]
        cancelled, _abort_id, abort_kind = ai_task_service.cancel_task(
            self.session,
            task_id=task_id,
            expected_execution_id=None,
            request_id=str(uuid.uuid4()),
            source_kind="weekly_plan",
            weekly_plan_id=self.plan_id,
        )
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(abort_kind, "none")
        self.session.expire_all()
        self.assertEqual(
            self.session.query(LocalAIAttempt).count(),
            0,
        )
        self.assertEqual(
            self.session.query(LocalAICandidate)
            .filter(LocalAICandidate.task_id == task_id)
            .count(),
            0,
        )

    def test_wai23_tls_and_policy_refusals_fail_without_retry_or_send(self):
        for model, reason in (
            ("w3weekly|pre_send|tls_invalid", "tls_invalid"),
            ("w3weekly|pre_send|policy", "endpoint_blocked"),
        ):
            executor, trace = self._start_weekly_executor(model)
            task_id = self._submit(executor)
            self.assertEqual(self._wait_task_status(task_id, {"failed"}), "failed")
            session = self.runtime.session()
            try:
                task = session.get(LocalAITask, task_id, populate_existing=True)
                self.assertEqual(task.reason, reason)
                self.assertEqual(
                    (task.runtime_meta_json or {}).get("processing_certainty"),
                    "not_sent",
                )
                self.assertEqual(self._attempt_count(task_id), 1)
                self.assertEqual(
                    session.query(LocalAICandidate)
                    .filter(LocalAICandidate.task_id == task_id)
                    .count(),
                    0,
                )
            finally:
                session.close()
            events = self._trace(trace)
            self.assertEqual([item["event"] for item in events].count("pre_send"), 1)
            self.assertEqual([item["event"] for item in events].count("send"), 0)
            executor.stop()

    def test_executor_claim_refuses_corrupt_stored_input_without_send(self):
        executor, trace = self._start_weekly_executor("w3weekly|success")
        executor.freeze("test")
        result, _ = self._create(
            weekly_ai_service.GAMES,
            [weekly_ai_service.WeeklyTaskSpec("weekly_games_select", "games")],
        )
        task_id = result["tasks"][0]["task_id"]
        task = self.session.get(LocalAITask, task_id)
        input_row = self.session.get(LocalAIInput, task.input_id)
        input_row.payload_json = {**dict(input_row.payload_json), "grade": "tampered"}
        self.session.commit()
        executor.unfreeze("test")
        executor.notify()
        time.sleep(1.0)
        self.session.expire_all()
        self.assertEqual(self.session.get(LocalAITask, task_id).status, "pending")
        self.assertEqual(
            self.session.query(LocalAIExecution)
            .filter(LocalAIExecution.task_id == task_id)
            .count(),
            0,
        )
        self.assertEqual(self.session.query(LocalAIAttempt).count(), 0)
        self.assertEqual(self._trace(trace), [])

    def test_claim_rejects_input_schema_and_extra_target_hash_keys(self):
        result, _ = self._create(
            weekly_ai_service.GAMES,
            [weekly_ai_service.WeeklyTaskSpec("weekly_games_select", "games")],
        )
        task_id = result["tasks"][0]["task_id"]
        task = self.session.get(LocalAITask, task_id)
        input_row = self.session.get(LocalAIInput, task.input_id)
        original_schema = input_row.input_schema_version
        original_targets = dict(input_row.target_hashes_json)
        for name, mutate, restore in (
            (
                "schema_999",
                lambda row: setattr(row, "input_schema_version", 999),
                lambda row: setattr(row, "input_schema_version", original_schema),
            ),
            (
                "target_extra_key",
                lambda row: setattr(
                    row,
                    "target_hashes_json",
                    {**original_targets, "unexpected_extra": "0" * 64},
                ),
                lambda row: setattr(row, "target_hashes_json", original_targets),
            ),
        ):
            self.session.rollback()
            input_row = self.session.get(LocalAIInput, task.input_id)
            mutate(input_row)
            self.session.commit()
            with self.subTest(name=name):
                with self.assertRaises(LocalStorageError):
                    ai_task_service.claim_next(
                        self.runtime, now=ai_task_service._now(), started_ticks=1
                    )
                self.session.expire_all()
                self.assertEqual(
                    self.session.get(LocalAITask, task_id).status, "pending"
                )
                self.assertEqual(
                    self.session.query(LocalAIExecution)
                    .filter(LocalAIExecution.task_id == task_id)
                    .count(),
                    0,
                )
                self.assertEqual(
                    self.session.query(LocalAIAttempt)
                    .filter(LocalAIAttempt.execution_id.in_(
                        select(LocalAIExecution.id).where(
                            LocalAIExecution.task_id == task_id
                        )
                    ))
                    .count(),
                    0,
                )
                self.assertEqual(
                    self.session.query(LocalAICandidate)
                    .filter(LocalAICandidate.task_id == task_id)
                    .count(),
                    0,
                )
            self.session.rollback()
            input_row = self.session.get(LocalAIInput, task.input_id)
            restore(input_row)
            self.session.commit()

    def test_bad_json_row_shapes_are_storage_errors_in_list_and_detail(self):
        _task_id, candidate_id = self._succeed_games()
        candidate = self.session.get(LocalAICandidate, candidate_id)
        input_row = self.session.get(LocalAIInput, candidate.input_id)
        originals = {
            "payload_json": input_row.payload_json,
            "dependencies_json": input_row.dependencies_json,
            "target_hashes_json": input_row.target_hashes_json,
            "raw_candidate_json": candidate.raw_candidate_json,
        }
        for field in ("payload_json", "dependencies_json", "target_hashes_json"):
            for bad in ([], 7, None):
                input_row = self.session.get(LocalAIInput, candidate.input_id)
                setattr(input_row, field, bad)
                self.session.commit()
                with self.subTest(field=field, bad=type(bad).__name__):
                    with self.assertRaises(LocalStorageError):
                        weekly_ai_candidates.list_candidates(
                            self.session,
                            profile_id=self.profile.id,
                            plan_id=self.plan_id,
                        )
                    with self.assertRaises(LocalStorageError):
                        weekly_ai_candidates.get_candidate(
                            self.session,
                            profile_id=self.profile.id,
                            plan_id=self.plan_id,
                            candidate_id=candidate_id,
                        )
                self.session.rollback()
                input_row = self.session.get(LocalAIInput, candidate.input_id)
                setattr(input_row, field, originals[field])
                self.session.commit()
        for bad in ([], 7, None):
            candidate = self.session.get(LocalAICandidate, candidate_id)
            candidate.raw_candidate_json = bad
            self.session.commit()
            with self.subTest(field="raw_candidate_json", bad=type(bad).__name__):
                with self.assertRaises(LocalStorageError):
                    weekly_ai_candidates.list_candidates(
                        self.session,
                        profile_id=self.profile.id,
                        plan_id=self.plan_id,
                    )
                with self.assertRaises(LocalStorageError):
                    weekly_ai_candidates.get_candidate(
                        self.session,
                        profile_id=self.profile.id,
                        plan_id=self.plan_id,
                        candidate_id=candidate_id,
                    )
            self.session.rollback()
            candidate = self.session.get(LocalAICandidate, candidate_id)
            candidate.raw_candidate_json = originals["raw_candidate_json"]
            self.session.commit()
