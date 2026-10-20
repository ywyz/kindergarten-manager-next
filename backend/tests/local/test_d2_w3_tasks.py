"""D2 W3 task service: projection, receipts, scheduling state machine, cancel.

Real temp SQLite through ``LocalRuntime`` (which runs the package bundle
sync). No whole-path mock; the only injection is a deterministic holiday
provider used to exercise the calendar-coverage diagnostic.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import date

from app.local import ai_config_service, ai_inputs, ai_task_service, daily_plan_service
from app.local.base import utc_now
from app.local.errors import (
    LocalAiInputTooLarge,
    LocalAiNotConfigured,
    LocalAiRequestConflict,
    LocalAiRetryAckRequired,
    LocalAiSourceChanged,
    LocalAiTaskActive,
    LocalAiTaskStateConflict,
    LocalAiContractUnsupported,
    LocalStorageError,
)
from app.local.models import (
    LocalAICandidate,
    LocalAIExecution,
    LocalAITask,
    LocalDailyPlanAIProvenance,
)
from app.local.normalize import normalize_initialization
from tests.local.support import LocalTestCase, initialize_body, query_rows, query_scalar

SPLIT_CANDIDATE = {
    "group_activity": {
        "theme": "主题",
        "objectives": "目标",
        "preparation": "准备",
        "key_points": "重点",
        "difficult_points": "难点",
        "process": "一、导入\n二、观察",
    }
}


class TaskCase(LocalTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.runtime = self.make_runtime()
        self.runtime.launch_id = str(uuid.uuid4())
        self.db = self.runtime.db_path
        self.session = self.runtime.session()
        self.addCleanup(self.session.close)
        from app.local import profile_service

        profile_service.initialize(
            self.session, normalize_initialization(**initialize_body())
        )
        self.session.commit()

    # -- setup helpers -----------------------------------------------------
    def configure_ai(self, *, model="test-model", secret="s3cret") -> None:
        version = query_scalar(self.db, "SELECT current_config_version FROM local_ai_state")
        ai_config_service.patch_config(
            self.session,
            expected_ai_config_version=version or 0,
            base_url="https://api.example.com/v1",
            model=model,
            secret=secret,
            secret_provided=True,
            request_id=str(uuid.uuid4()),
            credential_root=self.runtime.credential_root,
        )

    def plan_input_id(self, task_id):
        return query_scalar(
            self.db, "SELECT input_id FROM local_ai_tasks WHERE id = ?", (task_id,)
        )

    def make_plan(self, plan_date=date(2026, 9, 2), raw="原始教案正文", adopted=None):
        payload, _created = daily_plan_service.create_or_open(
            self.session,
            plan_date=plan_date,
            raw_lesson_plan=raw,
            adopted_content=adopted
            or {
                "group_activity": {"process": "一、导入\n二、观察"},
                "reflection": "反思",
            },
        )
        return payload

    def create(self, plan_id, task_type="daily_lesson_split", grade="middle", request_id=None):
        return ai_task_service.create_task(
            self.session,
            plan_id=plan_id,
            task_type=task_type,
            expected_content_version=1,
            target_grade=grade,
            request_id=request_id or str(uuid.uuid4()),
        )

    def task_row(self, task_id):
        self.session.expire_all()
        return self.session.get(LocalAITask, task_id)

    def execution_row(self, execution_id):
        self.session.expire_all()
        return self.session.get(LocalAIExecution, execution_id)


class SubmissionTests(TaskCase):
    def test_create_and_idempotent_receipt(self):
        self.configure_ai()
        plan = self.make_plan()
        rid = str(uuid.uuid4())
        result, created = self.create(plan["id"], request_id=rid)
        self.assertTrue(created)
        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["task_type"], "daily_lesson_split")
        self.assertEqual(
            result["input_summary"]["dependency_hash"],
            query_scalar(
                self.db,
                "SELECT dependency_hash FROM local_ai_inputs WHERE id = ?",
                (self.plan_input_id(result["id"]),),
            ),
        )
        # Same key/body reads the original task back (created=False).
        again, created2 = self.create(plan["id"], request_id=rid)
        self.assertFalse(created2)
        self.assertEqual(again["id"], result["id"])

    def test_cross_domain_conflict(self):
        self.configure_ai()
        plan = self.make_plan()
        rid = str(uuid.uuid4())
        self.create(plan["id"], request_id=rid)
        # The same key used for a different D2 domain is a 409.
        from app.local import prompt_service

        with self.assertRaises(LocalAiRequestConflict):
            prompt_service.save_prompt(
                self.session,
                task_type="daily_lesson_split",
                expected_personal_revision=1,
                contract_version=1,
                guidance={k: "x" for k in ai_inputs.__dict__ and ("theme", "objectives", "preparation", "key_points", "difficult_points", "process")},
                request_id=rid,
            )

    def test_single_active_per_plan_type(self):
        self.configure_ai()
        plan = self.make_plan()
        self.create(plan["id"])
        with self.assertRaises(LocalAiTaskActive):
            self.create(plan["id"], request_id=str(uuid.uuid4()))
        # A different type is allowed and both are queued FIFO.
        other, created = self.create(
            plan["id"], task_type="daily_process_adapt", request_id=str(uuid.uuid4())
        )
        self.assertTrue(created)

    def test_not_configured_refused(self):
        plan = self.make_plan()
        with self.assertRaises(LocalAiNotConfigured):
            self.create(plan["id"])

    def test_empty_source_refused(self):
        self.configure_ai()
        plan = self.make_plan(raw="   ")
        from app.local.errors import LocalAiInputEmpty

        with self.assertRaises(LocalAiInputEmpty):
            self.create(plan["id"])

    def test_contract_unsupported_refused(self):
        self.configure_ai()
        plan = self.make_plan()
        # Register a contract 2 bundle + personal version and point the head at
        # it: this build only supports v1 and must refuse the AI operation.
        from app.local.base import utc_now as _now
        from app.local.models import (
            LocalPersonalPromptHead,
            LocalPersonalPromptVersion,
            LocalPromptBundle,
        )

        row = query_rows(self.db, "SELECT * FROM local_prompt_bundles WHERE task_type='daily_lesson_split'")[0]
        import json as _json

        bundle = LocalPromptBundle(
            task_type="daily_lesson_split",
            contract_version=2,
            default_revision=1,
            input_schema_json=_json.loads(row["input_schema_json"])
            if isinstance(row["input_schema_json"], str)
            else row["input_schema_json"],
            output_schema_json=_json.loads(row["output_schema_json"])
            if isinstance(row["output_schema_json"], str)
            else row["output_schema_json"],
            guidance_defaults_json=_json.loads(row["guidance_defaults_json"])
            if isinstance(row["guidance_defaults_json"], str)
            else row["guidance_defaults_json"],
            bundle_hash="c" * 64,
            created_at=_now(),
        )
        self.session.add(bundle)
        self.session.flush()
        head = self.session.get(
            LocalPersonalPromptHead, (self.profile_id(), "daily_lesson_split")
        )
        self.session.add(
            LocalPersonalPromptVersion(
                profile_id=self.profile_id(),
                task_type="daily_lesson_split",
                revision=head.current_revision + 1,
                contract_version=2,
                based_default_revision=1,
                guidance_json=dict(bundle.guidance_defaults_json),
                action="adapt",
                created_at=_now(),
            )
        )
        self.session.flush()
        head.current_revision += 1
        head.required_contract_version = 2
        head.latest_default_revision = 1
        self.session.commit()
        with self.assertRaises(LocalAiContractUnsupported):
            self.create(plan["id"])

    def profile_id(self) -> str:
        return query_scalar(self.db, "SELECT id FROM local_profile")


class ProjectionTests(TaskCase):
    def test_unrelated_change_keeps_dependency_hash(self):
        self.configure_ai()
        plan = self.make_plan()
        result, _ = self.create(plan["id"])
        before = result["input_summary"]["dependency_hash"]
        # A reflection edit bumps the content version but not the split source.
        daily_plan_service.save(
            self.session,
            plan_id=plan["id"],
            expected_content_version=1,
            raw_lesson_plan="原始教案正文",
            adopted_content={
                "group_activity": {"process": "一、导入\n二、观察"},
                "reflection": "改写后的反思",
            },
        )
        inp = query_rows(
            self.db, "SELECT dependency_hash FROM local_ai_inputs WHERE id = ?",
            (self.plan_input_id(result["id"]),),
        )[0]
        self.assertEqual(inp["dependency_hash"], before)
        # The source re-validation still passes.
        self.assertTrue(
            ai_task_service._revalidate_source(self.session, self.task_row(result["id"]))
        )

    def test_process_change_breaks_source(self):
        self.configure_ai()
        plan = self.make_plan()
        result, _ = self.create(plan["id"], task_type="daily_process_adapt")
        daily_plan_service.save(
            self.session,
            plan_id=plan["id"],
            expected_content_version=1,
            raw_lesson_plan="原始教案正文",
            adopted_content={
                "group_activity": {"process": "完全不同的过程"},
                "reflection": "反思",
            },
        )
        self.assertFalse(
            ai_task_service._revalidate_source(self.session, self.task_row(result["id"]))
        )

    def test_baseline_identity_differs_with_same_text(self):
        # Two adopted split candidates with identical process text but
        # different source identity must produce different adapt dependencies.
        self.configure_ai()
        plan = self.make_plan(adopted={
            "group_activity": {"process": "同一过程"},
            "reflection": "反思",
        })
        # Build a real split candidate chain (task -> execution -> candidate).
        split, _ = self.create(plan["id"], request_id=str(uuid.uuid4()))
        split_claim = ai_task_service.claim_next(
            self.runtime, now=utc_now(), started_ticks=1
        )
        ai_task_service.commit_dispatch_mark(self.session, split_claim, utc_now())
        ai_task_service.finalize_success(
            self.session,
            split_claim,
            {"kind": "success", "candidate_text": __import__("json").dumps(SPLIT_CANDIDATE)},
            utc_now(),
        )
        candidate_id = query_scalar(
            self.db, "SELECT id FROM local_ai_candidates WHERE execution_id = ?",
            (split_claim.execution_id,),
        )
        # A second content version with the same process + a provenance row.
        from app.local.models import LocalDailyPlan, LocalDailyPlanContent

        content = query_scalar(
            self.db, "SELECT current_content_id FROM local_daily_plans WHERE id = ?",
            (plan["id"],),
        )
        plan_row = self.session.get(LocalDailyPlan, plan["id"])
        content_row = self.session.get(LocalDailyPlanContent, content)
        # The baseline is exactly the *model* split process of the referenced
        # candidate (W4 strict invariant), so it must match the candidate body.
        baseline_text = {
            "group_activity_process": SPLIT_CANDIDATE["group_activity"]["process"]
        }
        content_row.split_baseline = baseline_text
        # The D2 write path already created the version-1 provenance row;
        # attach the baseline source to it (W4 keeps one row per version).
        provenance = self.session.get(LocalDailyPlanAIProvenance, content)
        self.assertIsNotNone(provenance)
        provenance.baseline_candidate_id = candidate_id
        provenance.adopted_candidate_id = None
        provenance.selected_targets_json = {"group_activity": True}
        provenance.adopted_payload_hash = None
        self.session.flush()
        projected = ai_inputs.project_input(
            self.session,
            plan=plan_row,
            content=content_row,
            task_type="daily_process_adapt",
            target_grade="middle",
        )
        self.assertEqual(projected.dependencies["baseline_candidate_id"], candidate_id)
        self.assertEqual(projected.dependencies["split_baseline"], baseline_text)
        # The same process text without a source identity hashes differently.
        without = dict(projected.dependencies)
        without["baseline_candidate_id"] = None
        self.assertNotEqual(
            ai_task_service._digest(without), projected.dependency_hash
        )

    def test_baseline_corrupt_combinations_rejected(self):
        self.configure_ai()
        plan = self.make_plan()
        content = query_scalar(
            self.db, "SELECT current_content_id FROM local_daily_plans WHERE id = ?", (plan["id"],)
        )
        from app.local.models import LocalDailyPlan, LocalDailyPlanContent

        plan_row = self.session.get(LocalDailyPlan, plan["id"])
        content_row = self.session.get(LocalDailyPlanContent, content)
        # A non-null baseline without provenance is corrupt.
        content_row.split_baseline = {"group_activity_process": "x"}
        with self.assertRaises(LocalStorageError):
            ai_inputs.project_input(
                self.session, plan=plan_row, content=content_row,
                task_type="daily_process_adapt", target_grade="middle",
            )

    def test_holiday_coverage_warning_surfaced(self):
        self.configure_ai()
        plan = self.make_plan()
        # A provider that reports no coverage for a boundary day.
        def provider(day):
            raise NotImplementedError("no coverage")

        t, _ = ai_task_service.create_task(
            self.session,
            plan_id=plan["id"],
            task_type="daily_other_activities",
            expected_content_version=1,
            target_grade="middle",
            request_id=str(uuid.uuid4()),
            holiday_provider=provider,
        )
        warning = t["input_summary"].get("calendar_coverage_warning")
        self.assertIsNotNone(warning)
        self.assertEqual(warning["coverage"], "unknown")
        self.assertTrue(warning["note"])
        # The model-facing payload carries no diagnostic key.
        payload = query_scalar(
            self.db, "SELECT payload_json FROM local_ai_inputs WHERE id = ?",
            (self.plan_input_id(t["id"]),),
        )
        import json as _json

        payload = payload if isinstance(payload, dict) else _json.loads(payload)
        self.assertNotIn("_diagnostics", payload)
        self.assertIn("holiday_context", payload["calendar_context"])


class SerializedSizeTests(TaskCase):
    HEAVY = "\\" * 75000

    def _heavy_plan(self):
        adopted = {
            "group_activity": {
                key: self.HEAVY
                for key in (
                    "theme", "objectives", "preparation",
                    "key_points", "difficult_points", "process",
                )
            },
            "reflection": "反思",
        }
        return self.make_plan(adopted=adopted)

    def test_submit_refuses_over_limit_serialized_request(self):
        self.configure_ai()
        plan = self._heavy_plan()
        from tests.local.support import query_scalar

        # No input / task / task receipt may be created.
        with self.assertRaises(LocalAiInputTooLarge):
            ai_task_service.create_task(
                self.session,
                plan_id=plan["id"],
                task_type="daily_other_activities",
                expected_content_version=1,
                target_grade="middle",
                request_id=str(uuid.uuid4()),
                runtime=self.runtime,
            )
        for table in ("local_ai_inputs", "local_ai_tasks"):
            self.assertEqual(
                query_scalar(self.db, f"SELECT count(*) FROM {table}"), 0, table
            )
        self.assertEqual(
            query_scalar(
                self.db,
                "SELECT count(*) FROM local_ai_operations WHERE operation_kind LIKE 'ai_task%'",
            ),
            0,
        )

    def test_claim_rechecks_serialized_size_before_any_network(self):
        self.configure_ai()
        # A backslash-heavy payload sized to sit just under the 1 MiB
        # *serialized* limit with the small default guidance...
        heavy = "\\" * 42750
        adopted = {
            "group_activity": {
                key: heavy for key in
                ("theme", "objectives", "preparation",
                 "key_points", "difficult_points", "process")
            },
            "reflection": "反思",
        }
        plan = self.make_plan(adopted=adopted)
        from app.local.prompt_bundles import GUIDANCE_FIELDS

        result, _ = ai_task_service.create_task(
            self.session,
            plan_id=plan["id"],
            task_type="daily_other_activities",
            expected_content_version=1,
            target_grade="middle",
            request_id=str(uuid.uuid4()),
            runtime=self.runtime,
        )
        # ...then the guidance grows to the 8000-char limit per field, pushing
        # the real serialized body over 1 MiB.
        from app.local import prompt_service
        from tests.local.support import query_scalar

        revision = query_scalar(
            self.db,
            "SELECT current_revision FROM local_personal_prompt_heads WHERE task_type = ?",
            ("daily_other_activities",),
        )
        guidance = {key: "g" * 8000 for key in GUIDANCE_FIELDS["daily_other_activities"]}
        prompt_service.save_prompt(
            self.session,
            task_type="daily_other_activities",
            expected_personal_revision=revision,
            contract_version=1,
            guidance=guidance,
            request_id=str(uuid.uuid4()),
        )
        claim = ai_task_service.claim_next(self.runtime, now=utc_now(), started_ticks=1)
        self.assertIsNone(claim)
        row = self.task_row(result["id"])
        self.assertEqual(row.status, "paused")
        self.assertEqual(row.reason, "input_too_large")
        # Zero worker/execution/attempt: nothing reached the network layer.
        self.assertEqual(query_scalar(self.db, "SELECT count(*) FROM local_ai_executions"), 0)
        self.assertEqual(query_scalar(self.db, "SELECT count(*) FROM local_ai_attempts"), 0)


class ClaimAndFinalizeTests(TaskCase):
    def _claim(self, task_id):
        return ai_task_service.claim_next(
            self.runtime, now=utc_now(), started_ticks=1000
        )

    def test_claim_pins_versions_and_marks_dispatching(self):
        self.configure_ai()
        plan = self.make_plan()
        result, _ = self.create(plan["id"])
        claim = self._claim(result["id"])
        self.assertIsNotNone(claim)
        self.assertEqual(claim.attempt_no, 1)
        self.assertEqual(self.task_row(result["id"]).status, "claimed")
        self.assertTrue(
            ai_task_service.commit_dispatch_mark(self.session, claim, utc_now())
        )
        self.assertEqual(self.task_row(result["id"]).status, "dispatching")
        # Second mark refused (no longer claimed).
        self.assertFalse(
            ai_task_service.commit_dispatch_mark(self.session, claim, utc_now())
        )

    def test_finalize_success_persists_candidate(self):
        self.configure_ai()
        plan = self.make_plan()
        result, _ = self.create(plan["id"])
        claim = self._claim(result["id"])
        ai_task_service.commit_dispatch_mark(self.session, claim, utc_now())
        ok = ai_task_service.finalize_success(
            self.session,
            claim,
            {"kind": "success", "candidate_text": __import__("json").dumps(SPLIT_CANDIDATE)},
            utc_now(),
        )
        self.assertTrue(ok)
        self.assertEqual(self.task_row(result["id"]).status, "succeeded")
        self.assertEqual(
            query_scalar(
                self.db, "SELECT count(*) FROM local_ai_candidates WHERE execution_id = ?",
                (claim.execution_id,),
            ),
            1,
        )

    def test_finalize_refused_after_cancel(self):
        self.configure_ai()
        plan = self.make_plan()
        result, _ = self.create(plan["id"])
        claim = self._claim(result["id"])
        ai_task_service.commit_dispatch_mark(self.session, claim, utc_now())
        ai_task_service.cancel_task(
            self.session,
            task_id=result["id"],
            expected_execution_id=claim.execution_id,
            request_id=str(uuid.uuid4()),
        )
        ok = ai_task_service.finalize_success(
            self.session,
            claim,
            {"kind": "success", "candidate_text": __import__("json").dumps(SPLIT_CANDIDATE)},
            utc_now(),
        )
        self.assertFalse(ok)
        self.assertEqual(
            query_scalar(
                self.db, "SELECT count(*) FROM local_ai_candidates WHERE execution_id = ?",
                (claim.execution_id,),
            ),
            0,
        )

    def test_classification_mapping(self):
        cases = [
            ({"kind": "rate_limited", "sent": True}, "paused", "rate_limited", "unknown"),
            ({"kind": "auth", "sent": True}, "paused", "auth_rejected", "unknown"),
            ({"kind": "config_rejected", "sent": True}, "paused", "provider_error", "unknown"),
            ({"kind": "provider_error", "sent": True}, "outcome_unknown", "provider_error", "unknown"),
            ({"kind": "output_invalid", "sent": True}, "failed", "output_invalid", "response_received"),
            ({"kind": "policy", "sent": False}, "failed", "endpoint_blocked", "not_sent"),
            ({"kind": "policy", "sent": True}, "paused", "endpoint_blocked", "unknown"),
            ({"kind": "unknown", "sent": True}, "outcome_unknown", "timeout_after_dispatch", "unknown"),
        ]
        self.configure_ai()
        for index, (outcome, status, reason, certainty) in enumerate(cases):
            with self.subTest(outcome=outcome):
                from tests.local.support import execute_sql

                execute_sql(
                    self.db,
                    "UPDATE local_ai_state SET blocked_config_version = NULL, blocked_reason = NULL",
                )
                plan = self.make_plan(plan_date=date(2026, 9, (1, 2, 3, 4, 7, 8, 9, 10, 11)[index]))
                result, _ = self.create(plan["id"], request_id=str(uuid.uuid4()))
                claim = self._claim(result["id"])
                ai_task_service.commit_dispatch_mark(self.session, claim, utc_now())
                ai_task_service.finalize_failure(self.session, claim, outcome, utc_now())
                row = self.task_row(result["id"])
                self.assertEqual(row.status, status)
                self.assertEqual(row.reason, reason)
                self.assertEqual(
                    (row.runtime_meta_json or {}).get("processing_certainty"), certainty
                )

    def test_transient_not_sent_exhausts_to_failed(self):
        self.configure_ai()
        plan = self.make_plan()
        result, _ = self.create(plan["id"])
        outcome = {
            "kind": "not_sent",
            "reason": "connection_unavailable",
            "transient_not_sent": True,
            "sent": False,
        }
        for attempt in (1, 2, 3):
            claim = self._claim(result["id"])
            self.assertIsNotNone(claim, attempt)
            self.assertEqual(claim.attempt_no, attempt)
            ai_task_service.finalize_failure(
                self.session, claim, outcome, utc_now(), wait_seconds=(0, 0)
            )
            row = self.task_row(result["id"])
            if attempt < 3:
                self.assertEqual(row.status, "retry_wait")
                # Make the wait due now.
                row.runtime_meta_json = dict(row.runtime_meta_json or {})
                row.runtime_meta_json["next_attempt_at"] = utc_now().isoformat()
                self.session.commit()
            else:
                self.assertEqual(row.status, "failed")
                self.assertEqual(row.reason, "connection_unavailable")
                self.assertEqual(
                    (row.runtime_meta_json or {}).get("processing_certainty"), "not_sent"
                )


class CancelTests(TaskCase):
    def test_cancel_pending_preserves_history(self):
        self.configure_ai()
        plan = self.make_plan()
        first, _ = self.create(plan["id"])
        claim = ai_task_service.claim_next(self.runtime, now=utc_now(), started_ticks=1)
        ai_task_service.commit_dispatch_mark(self.session, claim, utc_now())
        ai_task_service.finalize_failure(
            self.session, claim, {"kind": "rate_limited", "sent": True}, utc_now()
        )
        # retry -> pending, keeping the old (possibly sent) execution reference.
        row = self.task_row(first["id"])
        snapshot = {
            key: getattr(row, key)
            for key in ("status", "reason", "runtime_meta_json", "generation")
        }
        ai_task_service.retry_task(
            self.session,
            task_id=first["id"],
            expected_execution_id=claim.execution_id,
            ack_duplicate_cost=True,
            request_id=str(uuid.uuid4()),
        )
        self.assertEqual(self.task_row(first["id"]).status, "pending")
        before = self.execution_row(claim.execution_id)
        before_values = {
            "state": before.state,
            "ended_at": before.ended_at,
            "runtime_meta_json": dict(before.runtime_meta_json or {}),
        }
        ai_task_service.cancel_task(
            self.session,
            task_id=first["id"],
            expected_execution_id=claim.execution_id,
            request_id=str(uuid.uuid4()),
        )
        self.assertEqual(self.task_row(first["id"]).status, "cancelled")
        after = self.execution_row(claim.execution_id)
        self.assertEqual(after.state, before_values["state"])
        self.assertEqual(after.ended_at, before_values["ended_at"])
        self.assertEqual(
            dict(after.runtime_meta_json or {}), before_values["runtime_meta_json"]
        )
        self.assertEqual(snapshot["generation"], self.task_row(first["id"]).generation)

    def test_cancel_paused_unknown_projects_user_stop(self):
        self.configure_ai()
        plan = self.make_plan()
        result, _ = self.create(plan["id"])
        claim = ai_task_service.claim_next(self.runtime, now=utc_now(), started_ticks=1)
        ai_task_service.commit_dispatch_mark(self.session, claim, utc_now())
        ai_task_service.finalize_failure(
            self.session, claim, {"kind": "rate_limited", "sent": True}, utc_now()
        )
        ai_task_service.cancel_task(
            self.session,
            task_id=result["id"],
            expected_execution_id=claim.execution_id,
            request_id=str(uuid.uuid4()),
        )
        row = self.task_row(result["id"])
        self.assertEqual(row.status, "outcome_unknown")
        self.assertEqual(row.reason, "user_stop")
        execution = self.execution_row(claim.execution_id)
        self.assertTrue(execution.runtime_meta_json.get("user_stop_requested"))

    def test_cancel_failed_not_sent_becomes_cancelled(self):
        self.configure_ai()
        plan = self.make_plan()
        result, _ = self.create(plan["id"])
        claim = ai_task_service.claim_next(self.runtime, now=utc_now(), started_ticks=1)
        ai_task_service.commit_dispatch_mark(self.session, claim, utc_now())
        ai_task_service.finalize_failure(
            self.session,
            claim,
            {"kind": "not_sent", "reason": "connection_unavailable", "sent": False},
            utc_now(),
        )
        row = self.task_row(result["id"])
        self.assertEqual(row.status, "failed")
        task_out = ai_task_service.get_task(self.session, result["id"])
        self.assertIn("retry", task_out["allowed_actions"])
        ai_task_service.cancel_task(
            self.session,
            task_id=result["id"],
            expected_execution_id=claim.execution_id,
            request_id=str(uuid.uuid4()),
        )
        self.assertEqual(self.task_row(result["id"]).status, "cancelled")


class CredentialLifecycleTests(TaskCase):
    def _new_secret(self, secret="second-secret"):
        from app.local import ai_config_service

        version = query_scalar(self.db, "SELECT current_config_version FROM local_ai_state")
        return ai_config_service.patch_config(
            self.session,
            expected_ai_config_version=version,
            base_url="https://api.example.com/v1",
            model="test-model",
            secret=secret,
            secret_provided=True,
            request_id=str(uuid.uuid4()),
            credential_root=self.runtime.credential_root,
        )

    def test_ended_execution_clears_superseded_credential(self):
        self.configure_ai(secret="first-secret")
        old_credential = query_scalar(self.db, "SELECT id FROM local_ai_credentials")
        plan = self.make_plan()
        result, _ = self.create(plan["id"])
        claim = ai_task_service.claim_next(self.runtime, now=utc_now(), started_ticks=1)
        # Replace the secret: the old credential becomes retired with material.
        self._new_secret()
        row = query_rows(
            self.db, "SELECT state, nonce IS NOT NULL AS has_nonce FROM local_ai_credentials WHERE id = ?",
            (old_credential,),
        )[0]
        self.assertEqual(row["state"], "retired")
        self.assertEqual(row["has_nonce"], 1)
        # A pre-send failure ends the execution: the now-unpinned old key must
        # be cleared (not left with material).
        ai_task_service.finalize_failure(
            self.session,
            claim,
            {"kind": "tls_invalid", "reason": "tls_invalid", "sent": False},
            utc_now(),
        )
        row = query_rows(
            self.db,
            "SELECT state, nonce, ciphertext FROM local_ai_credentials WHERE id = ?",
            (old_credential,),
        )[0]
        self.assertEqual(row["state"], "cleared")
        self.assertIsNone(row["nonce"])
        self.assertIsNone(row["ciphertext"])

    def test_mark_refused_after_secret_cleared(self):
        self.configure_ai(secret="first-secret")
        plan = self.make_plan()
        result, _ = self.create(plan["id"])
        # Retry path pins config v1 for the first execution.
        first = ai_task_service.claim_next(self.runtime, now=utc_now(), started_ticks=1)
        ai_task_service.finalize_failure(
            self.session,
            first,
            {"kind": "not_sent", "reason": "connection_unavailable", "sent": False},
            utc_now(),
        )
        # A new retry pins the current config (v2 after a secret replace).
        self._new_secret()
        ai_task_service.retry_task(
            self.session,
            task_id=result["id"],
            expected_execution_id=first.execution_id,
            ack_duplicate_cost=False,
            request_id=str(uuid.uuid4()),
        )
        claim = ai_task_service.claim_next(self.runtime, now=utc_now(), started_ticks=2)
        self.assertIsNotNone(claim)
        # Clear the secret while the attempt is claimed but not yet marked.
        from app.local import ai_config_service

        version = query_scalar(self.db, "SELECT current_config_version FROM local_ai_state")
        ai_config_service.clear_secret(
            self.session,
            expected_ai_config_version=version,
            request_id=str(uuid.uuid4()),
            credential_root=self.runtime.credential_root,
        )
        self.assertFalse(
            ai_task_service.commit_dispatch_mark(self.session, claim, utc_now())
        )
        row = self.task_row(result["id"])
        self.assertEqual(row.status, "paused")
        self.assertEqual(row.reason, "credential_unavailable")
        self.assertEqual(
            query_scalar(
                self.db,
                "SELECT count(*) FROM local_ai_attempts WHERE dispatch_marked_at IS NOT NULL",
            ),
            0,
        )


    def test_resume_refused_when_credential_unavailable(self):
        self.configure_ai()
        plan = self.make_plan()
        result, _ = self.create(plan["id"])
        claim = ai_task_service.claim_next(self.runtime, now=utc_now(), started_ticks=1)
        ai_task_service.finalize_failure(
            self.session,
            claim,
            {"kind": "not_sent", "reason": "connection_unavailable", "sent": False},
            utc_now(),
        )
        from app.local import ai_config_service
        from app.local.errors import LocalError

        version = query_scalar(self.db, "SELECT current_config_version FROM local_ai_state")
        ai_config_service.clear_secret(
            self.session,
            expected_ai_config_version=version,
            request_id=str(uuid.uuid4()),
            credential_root=self.runtime.credential_root,
        )
        rid = str(uuid.uuid4())
        with self.assertRaises(LocalError) as caught:
            ai_task_service.resume_task(
                self.session,
                task_id=result["id"],
                expected_execution_id=claim.execution_id,
                request_id=rid,
                runtime=self.runtime,
            )
        self.assertIn(
            caught.exception.code, ("AI_NOT_CONFIGURED", "CREDENTIAL_UNAVAILABLE")
        )
        # No receipt, no re-queue, still paused.
        self.assertEqual(
            query_scalar(
                self.db,
                "SELECT count(*) FROM local_ai_operations WHERE request_id = ?",
                (rid,),
            ),
            0,
        )
        self.assertEqual(self.task_row(result["id"]).status, "failed")


class RecoveryTests(TaskCase):
    def test_recovery_classification(self):
        self.configure_ai()
        plan = self.make_plan()
        result, _ = self.create(plan["id"])
        # A pending task (no execution) -> paused/restart.
        ai_task_service.recover_on_start(self.session, now=utc_now())
        row = self.task_row(result["id"])
        self.assertEqual(row.status, "paused")
        self.assertEqual(row.reason, "restart")

    def test_recovery_unknown_after_dispatch(self):
        self.configure_ai()
        plan = self.make_plan()
        result, _ = self.create(plan["id"])
        claim = ai_task_service.claim_next(self.runtime, now=utc_now(), started_ticks=1)
        ai_task_service.commit_dispatch_mark(self.session, claim, utc_now())
        ai_task_service.recover_on_start(self.session, now=utc_now())
        row = self.task_row(result["id"])
        self.assertEqual(row.status, "outcome_unknown")
        self.assertEqual(row.reason, "restart")

    def test_restart_then_resume_creates_new_generation(self):
        self.configure_ai()
        plan = self.make_plan()
        result, _ = self.create(plan["id"])
        claim = ai_task_service.claim_next(self.runtime, now=utc_now(), started_ticks=1)
        self.assertIsNotNone(claim)
        # Restart recovery pauses the not-yet-sent claimed task.
        ai_task_service.recover_on_start(self.session, now=utc_now())
        row = self.task_row(result["id"])
        self.assertEqual(row.status, "paused")
        self.assertEqual(row.reason, "restart")
        self.assertEqual(row.current_execution_id, claim.execution_id)
        # Manual resume reuses nothing from the old execution's versions but
        # keeps its history; the next claim is a new generation.
        resumed = ai_task_service.resume_task(
            self.session,
            task_id=result["id"],
            expected_execution_id=claim.execution_id,
            request_id=str(uuid.uuid4()),
        )
        self.assertEqual(resumed["status"], "pending")
        new_claim = ai_task_service.claim_next(
            self.runtime, now=utc_now(), started_ticks=2
        )
        self.assertIsNotNone(new_claim)
        self.assertNotEqual(new_claim.execution_id, claim.execution_id)
        self.assertEqual(new_claim.generation, claim.generation + 1)
        old = self.execution_row(claim.execution_id)
        self.assertEqual(old.state, "paused")
        self.assertIsNotNone(old.ended_at)


class AllowedActionsTests(TaskCase):
    def test_retry_requires_ack_only_for_unknown(self):
        self.configure_ai()
        plan = self.make_plan()
        result, _ = self.create(plan["id"])
        claim = ai_task_service.claim_next(self.runtime, now=utc_now(), started_ticks=1)
        ai_task_service.commit_dispatch_mark(self.session, claim, utc_now())
        ai_task_service.finalize_failure(
            self.session, claim, {"kind": "unknown", "sent": True}, utc_now()
        )
        out = ai_task_service.get_task(self.session, result["id"])
        self.assertTrue(out["retry_requires_ack"])
        with self.assertRaises(LocalAiRetryAckRequired):
            ai_task_service.retry_task(
                self.session, task_id=result["id"],
                expected_execution_id=claim.execution_id,
                ack_duplicate_cost=False, request_id=str(uuid.uuid4()),
            )

    def test_sent_provider_errors_require_ack(self):
        cases = [
            {"kind": "auth", "sent": True},
            {"kind": "config_rejected", "sent": True},
            {"kind": "policy", "sent": True, "reason": "endpoint_blocked"},
            {"kind": "rate_limited", "sent": True},
            {"kind": "provider_error", "sent": True},
        ]
        self.configure_ai()
        for index, outcome in enumerate(cases):
            with self.subTest(outcome=outcome):
                from tests.local.support import execute_sql

                execute_sql(
                    self.db,
                    "UPDATE local_ai_state SET blocked_config_version = NULL, blocked_reason = NULL",
                )
                plan = self.make_plan(plan_date=date(2026, 9, (1, 2, 3, 4, 7)[index]))
                result, _ = self.create(plan["id"], request_id=str(uuid.uuid4()))
                claim = ai_task_service.claim_next(
                    self.runtime, now=utc_now(), started_ticks=1
                )
                ai_task_service.commit_dispatch_mark(self.session, claim, utc_now())
                ai_task_service.finalize_failure(
                    self.session, claim, outcome, utc_now()
                )
                out = ai_task_service.get_task(self.session, result["id"])
                # A complete provider error does not prove the request was not
                # processed: a retry needs the explicit risk acknowledgement.
                self.assertTrue(out["retry_requires_ack"], outcome)
                with self.assertRaises(LocalAiRetryAckRequired):
                    ai_task_service.retry_task(
                        self.session, task_id=result["id"],
                        expected_execution_id=claim.execution_id,
                        ack_duplicate_cost=False, request_id=str(uuid.uuid4()),
                    )
                # With the ack a new execution generation is created.
                retried = ai_task_service.retry_task(
                    self.session, task_id=result["id"],
                    expected_execution_id=claim.execution_id,
                    ack_duplicate_cost=True, request_id=str(uuid.uuid4()),
                )
                self.assertEqual(retried["status"], "pending")
                new_claim = ai_task_service.claim_next(
                    self.runtime, now=utc_now(), started_ticks=2
                )
                self.assertIsNotNone(new_claim)
                self.assertNotEqual(new_claim.execution_id, claim.execution_id)
                self.assertEqual(new_claim.generation, claim.generation + 1)
                # The old execution's facts are untouched by the retry.
                self.assertEqual(
                    self.execution_row(claim.execution_id).state, out["status"]
                )
                ai_task_service.cancel_task(
                    self.session, task_id=result["id"],
                    expected_execution_id=new_claim.execution_id,
                    request_id=str(uuid.uuid4()),
                )

    def test_not_sent_failure_retry_without_ack(self):
        self.configure_ai()
        plan = self.make_plan()
        result, _ = self.create(plan["id"])
        claim = ai_task_service.claim_next(self.runtime, now=utc_now(), started_ticks=1)
        ai_task_service.commit_dispatch_mark(self.session, claim, utc_now())
        ai_task_service.finalize_failure(
            self.session,
            claim,
            {"kind": "not_sent", "reason": "connection_unavailable", "sent": False},
            utc_now(),
        )
        out = ai_task_service.get_task(self.session, result["id"])
        self.assertFalse(out["retry_requires_ack"])
        # No ack needed for a provably-unsent failure.
        retried = ai_task_service.retry_task(
            self.session, task_id=result["id"],
            expected_execution_id=claim.execution_id,
            ack_duplicate_cost=False, request_id=str(uuid.uuid4()),
        )
        self.assertEqual(retried["status"], "pending")


class FrozenSpawnGuardTests(unittest.TestCase):
    def test_only_a_frozen_spawn_child_is_guarded(self):
        from unittest import mock

        from app.local import ai_spawn

        # Not frozen: never guarded, even with a fork-style command line.
        with mock.patch.object(ai_spawn.sys, "frozen", False, create=True):
            with mock.patch.object(ai_spawn.sys, "argv", ["prog", "--multiprocessing-fork"]):
                self.assertFalse(ai_spawn.is_frozen_spawn_child())
        # Frozen + forking: guarded.
        with mock.patch.object(ai_spawn.sys, "frozen", True, create=True):
            with mock.patch.object(
                ai_spawn.sys, "argv", ["prog", "--multiprocessing-fork"]
            ):
                self.assertTrue(ai_spawn.is_frozen_spawn_child())
        # Frozen but the normal parent: not guarded.
        with mock.patch.object(ai_spawn.sys, "frozen", True, create=True):
            with mock.patch.object(ai_spawn.sys, "argv", ["prog", "--phase", "setup"]):
                self.assertFalse(ai_spawn.is_frozen_spawn_child())

    def test_guard_is_a_noop_outside_a_child(self):
        from unittest import mock

        from app.local import ai_spawn

        with mock.patch.object(ai_spawn, "is_frozen_spawn_child", return_value=False):
            with mock.patch("multiprocessing.freeze_support") as fake:
                ai_spawn.freeze_support_guarded()
                fake.assert_not_called()

    def test_child_bootstrap_failure_becomes_fixed_exit(self):
        from unittest import mock

        from app.local import ai_spawn

        with mock.patch.object(ai_spawn, "is_frozen_spawn_child", return_value=True):
            with mock.patch(
                "multiprocessing.freeze_support", side_effect=OSError("parent gone")
            ):
                with self.assertRaises(SystemExit) as caught:
                    ai_spawn.freeze_support_guarded()
                self.assertEqual(caught.exception.code, ai_spawn.FROZEN_SPAWN_EXIT_CODE)
            # A normal child SystemExit passes through unchanged.
            with mock.patch("multiprocessing.freeze_support", side_effect=SystemExit(0)):
                with self.assertRaises(SystemExit) as normal:
                    ai_spawn.freeze_support_guarded()
                self.assertEqual(normal.exception.code, 0)


class WorkerFrameBoundTests(LocalTestCase):
    def test_frame_bounds(self):
        from app.local import ai_transport, ai_worker

        self.assertEqual(
            ai_worker.REQUEST_FRAME_MAX, ai_transport.REQUEST_MAX_BYTES + 16 * 1024
        )
        self.assertEqual(
            ai_worker.RESPONSE_FRAME_MAX, ai_transport.RESPONSE_MAX_BYTES + 16 * 1024
        )
        self.assertLessEqual(ai_worker.CONTROL_FRAME_MAX, 16 * 1024)
