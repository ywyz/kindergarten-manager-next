"""G17 teacher-content corrections: r1 freeze, r2 defaults and request rules.

Synthetic, isolated SQLite only. No supplier call, key, migration or schema
change. These tests exercise the package manifest/version pointers, the real
prompt accept/reject service and the system-message builder.
"""

from __future__ import annotations

import json
import socket
import time
import unittest
import uuid
from datetime import date
from unittest import mock

from app.local import (
    ai_config_service,
    ai_task_service,
    daily_plan_service,
    profile_service,
    prompt_bundles,
    prompt_service,
)
from app.local.ai_transport import now_ticks
from app.local.base import utc_now
from app.local.normalize import normalize_initialization
from app.local.prompt_bundles import (
    PROMPT_BUNDLE_MANIFEST,
    bundle_hash,
)
from tests.local.support import LocalTestCase, initialize_body
from tests.local.test_d2_w3_executor import ExecutorCase
from tests.local import w3_tls

TASKS = (
    "daily_lesson_split",
    "daily_process_adapt",
    "daily_other_activities",
)
R1_HASHES = {
    "daily_lesson_split": "223a77eb9d2f992e910fd59a0d7793e7bb5c63fef1a5e190549c554094db28c5",
    "daily_process_adapt": "33dd13f4800ae428f74b157cdaa484abf50588258b6a4a2e00c12af24f0c73e6",
    "daily_other_activities": "a952d500a843acaf2f1cfeb851bffa90d93cb4d1026e4836d0d237f271cc135b",
}
R2_HASHES = {
    "daily_lesson_split": "16c155a30a898e81d17ddd1a12be9c709cfb68209ce1be9541bb63bfa5b394b1",
    "daily_process_adapt": "dd3aaf65c22a600e4aa50b85360f17bf9c2e6395ededdff5d9428491e7e98751",
    "daily_other_activities": "4700755f7c65380c628bba4104d8f210ec3b6fea6656814f80eb81d593f87a75",
}


def _bundle(task_type: str, default: int) -> dict:
    return next(
        b
        for b in PROMPT_BUNDLE_MANIFEST
        if b["task_type"] == task_type and b["default_revision"] == default
    )


def _latest(task_type: str) -> dict:
    return max(
        (b for b in PROMPT_BUNDLE_MANIFEST if b["task_type"] == task_type),
        key=lambda b: (b["contract_version"], b["default_revision"]),
    )


class G17ContentTests(LocalTestCase):
    def _initialize(self, runtime, *, sync_full: bool = True) -> None:
        session = runtime.session()
        try:
            if sync_full:
                prompt_bundles.sync_prompt_bundles(session)
            from app.local import profile_service

            profile_service.initialize(
                session, normalize_initialization(**initialize_body())
            )
        finally:
            session.close()

    def test_frozen_r1_r2_hashes_unchanged(self):
        for hashes, revision in ((R1_HASHES, 1), (R2_HASHES, 2)):
            for task_type, expected in hashes.items():
                bundle = _bundle(task_type, revision)
                self.assertEqual(bundle["bundle_hash"], expected)
                self.assertEqual(
                    bundle_hash(
                        bundle["input_schema_json"],
                        bundle["output_schema_json"],
                        bundle["guidance_defaults_json"],
                    ),
                    expected,
                )

    def test_new_archive_seeds_current_defaults(self):
        runtime = self.make_runtime()
        self._initialize(runtime)
        session = runtime.session()
        try:
            for task_type in TASKS:
                expected = 3 if task_type == "daily_process_adapt" else 2
                out = prompt_service.get_prompt(session, task_type=task_type)
                self.assertEqual(out["based_default_revision"], expected)
                self.assertEqual(out["latest_default_revision"], expected)
                self.assertEqual(
                    out["guidance"],
                    _bundle(task_type, expected)["guidance_defaults_json"],
                )
        finally:
            session.close()

    def test_existing_r1_accept_or_reject_r2_keeps_personal_text(self):
        r1_only = tuple(
            b for b in PROMPT_BUNDLE_MANIFEST if b["default_revision"] == 1
        )
        with mock.patch.object(prompt_bundles, "PROMPT_BUNDLE_MANIFEST", r1_only):
            runtime = self.make_runtime()
        self._initialize(runtime, sync_full=False)
        # The package now publishes r2 alongside the frozen r1.
        session = runtime.session()
        try:
            prompt_bundles.sync_prompt_bundles(session)
            for task_type in TASKS:
                before = prompt_service.get_prompt(session, task_type=task_type)
                self.assertEqual(before["based_default_revision"], 1)
                self.assertEqual(
                    before["latest_default_revision"],
                    3 if task_type == "daily_process_adapt" else 2,
                )
                self.assertEqual(
                    before["guidance"], _bundle(task_type, 1)["guidance_defaults_json"]
                )

            split = "daily_lesson_split"
            accepted = prompt_service.accept_default(
                session,
                task_type=split,
                expected_personal_revision=1,
                target_contract_version=1,
                target_default_revision=2,
                selected_fields=list(_bundle(split, 2)["guidance_defaults_json"]),
                request_id=str(uuid.uuid4()),
            )
            self.assertEqual(accepted["based_default_revision"], 2)
            self.assertEqual(
                accepted["guidance"], _bundle(split, 2)["guidance_defaults_json"]
            )

            adapt = "daily_process_adapt"
            rejected = prompt_service.reject_default(
                session,
                task_type=adapt,
                expected_personal_revision=1,
                target_contract_version=1,
                target_default_revision=3,
                request_id=str(uuid.uuid4()),
            )
            self.assertEqual(rejected["rejected_default_revision"], 3)
            self.assertEqual(
                rejected["guidance"], _bundle(adapt, 1)["guidance_defaults_json"]
            )
        finally:
            session.close()

    def test_system_rules_and_versions(self):
        for task_type in TASKS:
            bundle = _latest(task_type)
            text = ai_task_service._render_system_text(
                task_type,
                1,
                bundle["output_schema_json"],
                bundle["guidance_defaults_json"],
            )
            payload = json.loads(text)
            self.assertEqual(payload["contract_version"], 1)
            self.assertEqual(payload["guidance"], bundle["guidance_defaults_json"])
            instructions = "\n".join(payload["instructions"])
            self.assertIn("真实换行", instructions)
            self.assertIn("1. ", instructions)
            if task_type == "daily_lesson_split":
                self.assertIn("只整理这些已有条目", instructions)
            if task_type == "daily_process_adapt":
                self.assertIn("可以改写表达、步骤和难度", instructions)
                self.assertIn("即使无需年龄适宜性调整", instructions)
                self.assertIn("教师可直接说的具体话语", instructions)
                self.assertIn("引导语、提问和教师的预设回应或支持语", instructions)
                self.assertIn("保持目标年级适宜的活动难度", instructions)
                self.assertIn("不因话语增加认知或表达要求", instructions)
                self.assertIn("即使无需年龄适宜性调整", instructions)
                self.assertIn("补齐教师可直接说的具体话语", instructions)
                self.assertNotIn("不得为列表编造原文没有的步骤", instructions)
                self.assertNotIn("不需要调整时返回原过程", instructions)
            if task_type == "daily_other_activities":
                self.assertIn("均为户外活动", instructions)
                self.assertIn("不含区域游戏", instructions)
                self.assertNotIn("不改其他游戏计数", instructions)
                self.assertNotIn("手工保存规则", instructions)


class G17AdaptR3UpgradeTests(LocalTestCase):
    def _r2_runtime(self):
        r2_only = tuple(
            b for b in PROMPT_BUNDLE_MANIFEST if b["default_revision"] <= 2
        )
        with mock.patch.object(prompt_bundles, "PROMPT_BUNDLE_MANIFEST", r2_only):
            runtime = self.make_runtime(data_dir=self.tmp_root / "r2-upgrade")
        session = runtime.session()
        try:
            profile_service.initialize(
                session, normalize_initialization(**initialize_body())
            )
            prompt_bundles.sync_prompt_bundles(session)
            ai_config_service.patch_config(
                session,
                expected_ai_config_version=0,
                base_url="https://api.example.com/v1",
                model="g17-talk-model",
                secret="s3cret",
                secret_provided=True,
                request_id=str(uuid.uuid4()),
                credential_root=runtime.credential_root,
            )
            plan, _created = daily_plan_service.create_or_open(
                session,
                plan_date=date(2026, 9, 2),
                raw_lesson_plan="G17 教师话语合成原文",
                adopted_content={
                    "group_activity": {"process": "1. 导入\n2. 观察"},
                    "reflection": "反思",
                },
            )
        finally:
            session.close()
        return runtime, plan

    def _claim_adapt(self, runtime, plan):
        session = runtime.session()
        try:
            task = ai_task_service.create_task(
                session,
                plan_id=plan["id"],
                task_type="daily_process_adapt",
                expected_content_version=plan["current_content_version"],
                target_grade="middle",
                request_id=str(uuid.uuid4()),
            )[0]
        finally:
            session.close()
        claim = ai_task_service.claim_next(
            runtime, now=utc_now(), started_ticks=now_ticks()
        )
        self.assertIsNotNone(claim)
        assert claim is not None
        self.assertEqual(claim.task_id, task["id"])
        return claim

    def test_r2_profile_views_accepts_r3_and_pins_teacher_talk(self):
        runtime, plan = self._r2_runtime()
        session = runtime.session()
        try:
            before = prompt_service.get_prompt(
                session, task_type="daily_process_adapt"
            )
            self.assertEqual(before["based_default_revision"], 2)
            self.assertEqual(before["latest_default_revision"], 3)
            self.assertEqual(
                before["guidance"],
                _bundle("daily_process_adapt", 2)["guidance_defaults_json"],
            )
            default = prompt_service.get_default(
                session,
                task_type="daily_process_adapt",
                contract_version=1,
                default_revision=3,
            )
            self.assertEqual(
                default["guidance"],
                _bundle("daily_process_adapt", 3)["guidance_defaults_json"],
            )
            accepted = prompt_service.accept_default(
                session,
                task_type="daily_process_adapt",
                expected_personal_revision=1,
                target_contract_version=1,
                target_default_revision=3,
                selected_fields=["process"],
                request_id=str(uuid.uuid4()),
            )
            self.assertEqual(accepted["based_default_revision"], 3)
            self.assertEqual(
                accepted["guidance"],
                _bundle("daily_process_adapt", 3)["guidance_defaults_json"],
            )
        finally:
            session.close()
        claim = self._claim_adapt(runtime, plan)
        self.assertEqual(claim.default_revision, 3)
        payload = json.loads(claim.system_text)
        self.assertEqual(
            payload["guidance"],
            _bundle("daily_process_adapt", 3)["guidance_defaults_json"],
        )
        instructions = "\n".join(payload["instructions"])
        self.assertIn("教师可直接说的具体话语", instructions)
        self.assertIn("教师的预设回应或支持语", instructions)

    def test_accepted_r3_controlled_http_receives_teacher_talk_rules(self):
        from app.local.ai_executor import AiExecutor
        from app.local.models import LocalAITask

        runtime, plan = self._r2_runtime()
        session = runtime.session()
        try:
            prompt_service.accept_default(
                session,
                task_type="daily_process_adapt",
                expected_personal_revision=1,
                target_contract_version=1,
                target_default_revision=3,
                selected_fields=["process"],
                request_id=str(uuid.uuid4()),
            )
        finally:
            session.close()

        tls_root = self.tmp_root / "r3-http-tls"
        ca = tls_root / "ca"
        w3_tls.create_ca(ca)
        leaf = w3_tls.create_leaf(ca, tls_root / "leaf")
        reply = w3_tls.envelope(
            json.dumps(
                {"process": "1. 导入\n教师：“请看这里。”\n2. 观察"},
                ensure_ascii=False,
            )
        )
        server = w3_tls.TlsServer(cert=leaf[0], key=leaf[1], reply=reply).start()
        self.addCleanup(server.stop)
        executor = AiExecutor(
            runtime,
            synthetic_transport={
                "resolution": [
                    {"family": socket.AF_INET, "ip": "127.0.0.1", "port": server.port}
                ],
                "ca_pem": (ca / "ca.pem").read_text(encoding="utf-8"),
            },
        )
        executor.start()
        try:
            session = runtime.session()
            try:
                task = ai_task_service.create_task(
                    session,
                    plan_id=plan["id"],
                    task_type="daily_process_adapt",
                    expected_content_version=plan["current_content_version"],
                    target_grade="middle",
                    request_id=str(uuid.uuid4()),
                )[0]
            finally:
                session.close()
            executor.notify()
            deadline = time.monotonic() + 40
            status = None
            while time.monotonic() < deadline:
                session = runtime.session()
                try:
                    row = session.get(LocalAITask, task["id"], populate_existing=True)
                    status = row.status if row is not None else None
                finally:
                    session.close()
                if status in ("succeeded", "failed", "outcome_unknown", "cancelled", "paused"):
                    break
                time.sleep(0.05)
            self.assertEqual(status, "succeeded")
            self.assertEqual(len(server.requests), 1)
            _, _, body = server.requests[0].partition(b"\r\n\r\n")
            outer = json.loads(body.decode("utf-8"))
            system = json.loads(outer["messages"][0]["content"])
            self.assertEqual(system["contract_version"], 1)
            self.assertEqual(
                system["guidance"],
                _bundle("daily_process_adapt", 3)["guidance_defaults_json"],
            )
            instructions = "\n".join(system["instructions"])
            self.assertIn("教师可直接说的具体话语", instructions)
            self.assertIn("教师的预设回应或支持语", instructions)
            self.assertIn("保持目标年级适宜的活动难度", instructions)
        finally:
            executor.dispose()
            server.stop()

    def test_r2_profile_rejects_r3_keeps_r2_and_pins_r2(self):
        runtime, plan = self._r2_runtime()
        session = runtime.session()
        try:
            rejected = prompt_service.reject_default(
                session,
                task_type="daily_process_adapt",
                expected_personal_revision=1,
                target_contract_version=1,
                target_default_revision=3,
                request_id=str(uuid.uuid4()),
            )
            self.assertEqual(rejected["rejected_default_revision"], 3)
            self.assertEqual(
                rejected["guidance"],
                _bundle("daily_process_adapt", 2)["guidance_defaults_json"],
            )
        finally:
            session.close()
        claim = self._claim_adapt(runtime, plan)
        self.assertEqual(claim.default_revision, 2)
        payload = json.loads(claim.system_text)
        self.assertEqual(
            payload["guidance"],
            _bundle("daily_process_adapt", 2)["guidance_defaults_json"],
        )


class G17ClaimSnapshotTests(ExecutorCase):
    def test_claim_system_text_uses_r2_rules_and_versions(self):
        self.configure_ai(model="g17-content-model")
        plan = self.make_plan()
        task = self.submit(plan["id"])
        split = ai_task_service.claim_next(
            self.runtime, now=utc_now(), started_ticks=now_ticks()
        )
        self.assertIsNotNone(split)
        assert split is not None
        self.assertEqual(split.task_id, task["id"])
        self.assertEqual(split.contract_version, 1)
        self.assertEqual(split.default_revision, 2)
        self.assertEqual(split.personal_revision, 1)
        payload = json.loads(split.system_text)
        self.assertEqual(payload["contract_version"], 1)
        self.assertEqual(
            payload["guidance"],
            _bundle("daily_lesson_split", 2)["guidance_defaults_json"],
        )
        instructions = "\n".join(payload["instructions"])
        self.assertIn("真实换行", instructions)
        self.assertIn("只整理这些已有条目", instructions)

        other_task = self.submit(plan["id"], task_type="daily_other_activities")
        other = ai_task_service.claim_next(
            self.runtime, now=utc_now(), started_ticks=now_ticks()
        )
        self.assertIsNotNone(other)
        assert other is not None
        self.assertEqual(other.task_id, other_task["id"])
        self.assertEqual(other.default_revision, 2)
        self.assertEqual(other.personal_revision, 1)
        other_payload = json.loads(other.system_text)
        self.assertEqual(
            other_payload["guidance"],
            _bundle("daily_other_activities", 2)["guidance_defaults_json"],
        )
        other_instructions = "\n".join(other_payload["instructions"])
        self.assertIn("均为户外活动", other_instructions)
        self.assertIn("不含区域游戏", other_instructions)

        adapt_task = self.submit(plan["id"], task_type="daily_process_adapt")
        adapt = ai_task_service.claim_next(
            self.runtime, now=utc_now(), started_ticks=now_ticks()
        )
        self.assertIsNotNone(adapt)
        assert adapt is not None
        self.assertEqual(adapt.task_id, adapt_task["id"])
        self.assertEqual(adapt.default_revision, 3)
        self.assertEqual(adapt.personal_revision, 1)
        adapt_payload = json.loads(adapt.system_text)
        self.assertEqual(
            adapt_payload["guidance"],
            _bundle("daily_process_adapt", 3)["guidance_defaults_json"],
        )
        adapt_instructions = "\n".join(adapt_payload["instructions"])
        self.assertIn("教师可直接说的具体话语", adapt_instructions)
        self.assertIn("引导语、提问和教师的预设回应或支持语", adapt_instructions)


if __name__ == "__main__":
    unittest.main()
