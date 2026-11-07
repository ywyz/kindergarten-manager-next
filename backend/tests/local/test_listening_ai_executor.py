"""Real controlled executor/worker chain for listening AI (fake provider only)."""

from __future__ import annotations

import io
import json
import os
import time
import uuid
from datetime import date, datetime

from PIL import Image

from app.local import (
    ai_config_service,
    ai_task_service,
    listening_ai_service,
    listening_assets,
    listening_service,
    profile_service,
)
from app.local.ai_executor import AiExecutor
from app.local.normalize import normalize_initialization
from tests.local.listening_ai_workers import listening_fake_worker
from tests.local.support import LocalTestCase


class ListeningAIExecutorTests(LocalTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.runtime = self.make_runtime()
        self.runtime.launch_id = str(uuid.uuid4())
        self.session = self.runtime.session()
        self.addCleanup(self.session.close)
        profile_service.initialize(
            self.session,
            normalize_initialization(
                request_id=str(uuid.uuid4()),
                display_name="合成教师",
                class_name="中班",
                grade="middle",
                term_name="秋季",
                start_date="2026-09-01",
                end_date="2026-12-31",
                school_name="合成园",
            ),
        )
        self.session.commit()
        ai_config_service.patch_config(
            self.session,
            expected_ai_config_version=0,
            base_url="https://api.deepseek.com/v1",
            model="deepseek-v4-flash-vision-exp",
            secret="synthetic-secret",
            secret_provided=True,
            request_id=str(uuid.uuid4()),
            credential_root=self.runtime.credential_root,
        )
        self.session.commit()
        context = profile_service.require_context(self.session, date(2026, 11, 7))
        self.profile_id = context.profile.id
        self.term_id = context.terms[0].id
        record = listening_service.create_record(
            self.session,
            profile_id=self.profile_id,
            request_id=str(uuid.uuid4()),
            term_id=self.term_id,
            child_name="甲",
        )
        self.record_id = record["record_id"]
        dto = listening_service.read_record(
            self.session, profile_id=self.profile_id, record_id=self.record_id
        )
        self.group_id = next(
            group["group_id"]
            for domain in dto["domains"]
            if domain["domain"] == "health"
            for group in domain["groups"]
            if group["position"] == 0
        )
        listening_service.save_domain(
            self.session,
            profile_id=self.profile_id,
            record_id=self.record_id,
            domain="health",
            request_id=str(uuid.uuid4()),
            expected_revision=1,
            patch={"goal": "目标"},
        )
        self.revision = 2

    def _add_photo(self) -> None:
        buffer = io.BytesIO()
        Image.new("RGB", (320, 240), (20, 100, 200)).save(buffer, "PNG")
        listening_assets.import_group_photo(
            self.session,
            self.runtime,
            profile_id=self.profile_id,
            record_id=self.record_id,
            domain="health",
            group_id=self.group_id,
            request_id=str(uuid.uuid4()),
            expected_revision=self.revision,
            stream=io.BytesIO(buffer.getvalue()),
            display_name="图.png",
        )
        self.revision += 1

    def _run(self, task_type: str) -> dict:
        trace = self.tmp_root / f"listening-{uuid.uuid4().hex}.jsonl"
        os.environ["KGM_LISTENING_WORKER_TRACE"] = str(trace)
        self.addCleanup(
            lambda: os.environ.pop("KGM_LISTENING_WORKER_TRACE", None)
        )
        executor = AiExecutor(self.runtime, worker_target=listening_fake_worker)
        self.assertTrue(executor.start())
        self.addCleanup(lambda: executor.stop())
        created, _ = listening_ai_service.create_task(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile_id,
            record_id=self.record_id,
            domain="health",
            group_id=self.group_id if task_type == "listening_note_draft" else None,
            task_type=task_type,
            expected_revision=self.revision,
            request_id=str(uuid.uuid4()),
        )
        executor.notify()
        deadline = time.time() + 30
        last = None
        while time.time() < deadline:
            last = listening_ai_service.get_task(
                self.session,
                profile_id=self.profile_id,
                record_id=self.record_id,
                task_id=created["task_id"],
            )
            if last["status"] in ("succeeded", "failed", "outcome_unknown"):
                break
            time.sleep(0.05)
        self.assertEqual(last["status"], "succeeded", last)
        trace_rows = [
            json.loads(line)
            for line in trace.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertTrue(any(row.get("event") == "send" for row in trace_rows))
        candidate = listening_ai_service.get_candidate(
            self.session,
            profile_id=self.profile_id,
            record_id=self.record_id,
            task_id=created["task_id"],
        )
        return candidate

    def test_fake_worker_note_photo_only_and_domain(self) -> None:
        self._add_photo()
        note = self._run("listening_note_draft")
        self.assertIn("text", note["candidate"])
        self.assertTrue(note["candidate"]["uncertainties"])
        domain = self._run("listening_domain_evaluate")
        self.assertIn("overall_evaluation", domain["candidate"])
        self.assertEqual(len(domain["candidate"]["items"]), 6)
