"""D2 W1 R06-R08: AI configuration save, credential lifecycle and receipts.

Real temp databases, real DPAPI/ACL through the credential store, and a real
local Uvicorn server (standard-library ``http.client``). No mock replaces the
whole path; fault injection is a single point and asserts it fired.

Scope: PATCH/GET/clear-secret on ``/api/local/ai/config``, receipt
idempotency/HMAC, version ordering, secret-free configuration changes, the
unconfigured clear path, credential degradation and re-fill, and same-key
concurrency. Prompt/task/candidate APIs (W2-W4) are out of scope.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest import mock

from app.local import ai_config_service as svc
from app.local import profile_service
from app.local.credentials import CredentialStore
from app.local.normalize import normalize_initialization
from app.local.runtime import LocalRuntime
from tests.local.support import (
    LocalTestCase,
    execute_sql,
    initialize_body,
    query_rows,
    query_scalar,
    sqlite_connect,
)


def _json(value):
    return value if isinstance(value, dict) else json.loads(value)


class AiConfigValidationTests(unittest.TestCase):
    """Pure local functions: URL/secret/model syntax only (no network)."""

    def test_url_accepts_global_addresses_and_punycode(self):
        cases = {
            "https://api.example.com/v1": "https://api.example.com/v1",
            "https://api.example.com/v1/": "https://api.example.com/v1",
            "https://api.example.com:443/v1": "https://api.example.com/v1",
            "https://api.example.com:8443/v1": "https://api.example.com:8443/v1",
            "https://api.example.com./v1": "https://api.example.com/v1",
            # "localhost" only rejects the exact name and the *.localhost
            # suffix; an ordinary label elsewhere is a normal public domain
            # (no DNS is performed at save time).
            "https://localhost.example.com/v1":
                "https://localhost.example.com/v1",
            "https://example.localhost.net/v1":
                "https://example.localhost.net/v1",
            "https://8.8.8.8/v1": "https://8.8.8.8/v1",
            "https://[2606:4700:4700::1111]:8443/v1":
                "https://[2606:4700:4700::1111]:8443/v1",
            # A public IPv4-mapped IPv6 is judged by its underlying IPv4 (§4.2).
            "https://[::ffff:8.8.8.8]/v1": "https://[::ffff:8.8.8.8]/v1",
            "https://xn--fiqs8s.example/v1": "https://xn--fiqs8s.example/v1",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(svc._normalize_base_url(value), expected)

    def test_url_rejects_syntax_and_special_addresses(self):
        rejects = [
            "http://api.example.com/v1",
            "https://api.example.com/v1?x=1",
            "https://api.example.com/v1?",
            "https://api.example.com/v1#",
            "https://api.example.com:/v1",
            "https://@api.example.com/v1",
            "https://user:pw@api.example.com/v1",
            "https://localhost/v1",
            "https://localhost./v1",
            "https://sub.localhost/v1",
            "https://localhost.localdomain/v1",
            "https://127.0.0.1/v1",
            "https://127.0.0.1:8080/v1",
            "https://[::1]:8080/v1",
            "https://[::ffff:127.0.0.1]/v1",
            "https://[fe80::1]/v1",
            "https://[fe80::1%25eth0]/v1",
            "https://[fe80::1%eth0]/v1",
            "https://10.0.0.1/v1",
            "https://192.168.1.1/v1",
            "https://169.254.1.1/v1",
            "https://0.0.0.0/v1",
            "https://2130706433/v1",
            "https://2130706433./v1",
            "https://0x7f000001/v1",
            "https://api.example.com:99999/v1",
            "https://exa mple.com/v1",
            "https://api.example.com/v1/chat/completions",
            "https://api.example.com/chat/completions",
            "https://api.example.com/v1\\x",
            "https://api.example.com/v1\x7f",
            "https://api.example.com/v1\u0085",
            "https://api.example.com/\u00a0x",
        ]
        for value in rejects:
            with self.subTest(value=value):
                with self.assertRaises(svc.AiEndpointInvalid) as ctx:
                    svc._normalize_base_url(value)
                self.assertEqual(ctx.exception.code, "AI_ENDPOINT_INVALID")
                # Error messages never echo the offending input.
                self.assertNotIn(value, ctx.exception.message)

    def test_secret_rejects_control_and_whitespace(self):
        for value in [" a", "a ", "   ", "a\tb", "a\x7fb", "a\u0085b"]:
            with self.subTest(value=value):
                with self.assertRaises(svc.LocalValidationError):
                    svc._validate_secret(value)
        self.assertEqual(svc._validate_secret("秘密-ok_123"), "秘密-ok_123")

    def test_model_rejects_control_and_whitespace(self):
        for value in ["", "   ", " m", "m ", "m\x7fn", "m\u0085n"]:
            with self.subTest(value=value):
                with self.assertRaises(svc.LocalValidationError):
                    svc._normalize_model(value)
        self.assertEqual(svc._normalize_model("model-1"), "model-1")

    def test_lone_surrogate_rejected_in_all_text_fields(self):
        surrogate = "\ud800"
        with self.assertRaises(svc.LocalValidationError):
            svc._validate_secret(f"abc{surrogate}")
        with self.assertRaises(svc.LocalValidationError):
            svc._normalize_model(f"model{surrogate}")
        with self.assertRaises(svc.AiEndpointInvalid) as ctx:
            svc._normalize_base_url(f"https://api.example.com/v1/{surrogate}")
        self.assertEqual(ctx.exception.code, "AI_ENDPOINT_INVALID")
        self.assertNotIn(surrogate, ctx.exception.message)

    def test_valid_unicode_still_accepted(self):
        secret = "秘密-emoji-\U0001f600"
        self.assertEqual(svc._validate_secret(secret), secret)
        self.assertEqual(svc._normalize_model("模型-1"), "模型-1")

    def test_fingerprint_never_falls_back_to_sha_with_secret(self):
        with self.assertRaises(svc.LocalStorageError):
            svc._build_receipt_fingerprint(
                operation_kind="ai_config_patch",
                profile_id="p1",
                expected_version=0,
                protocol_id="chat_completions_v1",
                base_url="https://api.example.com/v1",
                model="m",
                secret_present=True,
                secret="s",
                hmac_key=None,
            )
        fingerprint, kind = svc._build_receipt_fingerprint(
            operation_kind="ai_config_clear_secret",
            profile_id="p1",
            expected_version=0,
            protocol_id=None,
            base_url=None,
            model=None,
            secret_present=False,
            secret=None,
            hmac_key=None,
        )
        self.assertEqual(kind, "sha256")
        self.assertEqual(len(fingerprint), 64)


class ConfigServiceCase(LocalTestCase):
    """Common setup: a runtime with an injected, not-yet-created cred root."""

    suffix = "cfg"

    def setUp(self) -> None:
        super().setUp()
        # This batch uses its own temp prefix and an explicit credential root
        # (never the real teacher directory). Secrets are per-process random
        # and are never included in assertion output.
        self.tmp_root = Path(tempfile.mkdtemp(prefix="kgm-d2-w1-"))
        self.addCleanup(shutil.rmtree, self.tmp_root, True)
        self.data_dir = self.tmp_root / "data"
        self.cred_root = self.tmp_root / f"{self.suffix}-credentials"
        self.secret_a = secrets.token_urlsafe(18)
        self.secret_b = secrets.token_urlsafe(18)
        self.secret_c = secrets.token_urlsafe(18)
        self.runtime = LocalRuntime(
            data_dir=self.data_dir, credential_root=self.cred_root
        )
        self.runtime.prepare()
        self.addCleanup(self.runtime.dispose)
        self.db = self.runtime.db_path

    def initialize(self) -> None:
        session = self.runtime.session()
        try:
            profile_service.initialize(
                session, normalize_initialization(**initialize_body())
            )
        finally:
            session.close()

    def patch(self, **overrides):
        body = {
            "expected_ai_config_version": 0,
            "base_url": "https://api.example.com/v1",
            "model": "model-1",
            "secret_provided": True,
            "secret": self.secret_a,
            "request_id": str(uuid.uuid4()),
            "credential_root": self.cred_root,
        }
        body.update(overrides)
        session = self.runtime.session()
        try:
            return svc.patch_config(session, **body)
        finally:
            session.close()

    def clear(self, *, expected, request_id, **extra):
        session = self.runtime.session()
        try:
            return svc.clear_secret(
                session,
                expected_ai_config_version=expected,
                request_id=request_id,
                credential_root=self.cred_root,
                **extra,
            )
        finally:
            session.close()

    def get_config(self):
        session = self.runtime.session()
        try:
            return svc.get_config(session, credential_root=self.cred_root)
        finally:
            session.close()

    def receipts(self) -> list[dict]:
        return query_rows(
            self.db,
            "SELECT request_id, operation_kind, fingerprint_kind, "
            "fingerprint_key_id, result_json FROM local_ai_operations "
            "ORDER BY created_at, id",
        )

    def credential_id(self) -> str | None:
        return query_scalar(
            self.db,
            "SELECT credential_id FROM local_ai_config_versions "
            "WHERE version = (SELECT current_config_version FROM local_ai_state)",
        )

    def key_file(self, credential_id: str) -> Path:
        database_uuid = query_scalar(
            self.db, "SELECT database_uuid FROM local_ai_state"
        )
        return self.cred_root / database_uuid / f"{credential_id}.dpapi"

    def pin_execution(
        self,
        *,
        task_status: str = "claimed",
        execution_state: str = "claimed",
        pointer: bool = True,
        ended: bool = False,
    ) -> tuple[str, str]:
        """Insert a legal plan/input/task/execution pinning config version 1.

        An execution only exists once a claim starts (engineering §4.1), so the
        fixture uses task generation = execution generation = 1. ``pointer``
        controls whether the task's ``current_execution_id`` references it;
        ``ended`` sets ``ended_at``. Returns (execution_id, task_id).
        """
        profile_id = query_scalar(self.db, "SELECT id FROM local_profile")
        klass = query_rows(
            self.db, "SELECT id, name, grade FROM local_classes"
        )[0]
        term = query_rows(
            self.db, "SELECT id, current_calendar_revision_id FROM local_terms"
        )[0]
        token = uuid.uuid4().hex[:20]
        plan_id = f"plan-{token}"
        content_id = f"content-{token}"
        input_id = f"input-{token}"
        task_id = f"task-{token}"
        execution_id = f"exec-{token}"
        current_execution_id = execution_id if pointer else None
        ended_at = "2026-10-17 00:00:00" if ended else None
        stamp = "2026-10-17 00:00:00"
        connection = sqlite_connect(self.db)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO local_daily_plans (id, class_id, term_id, plan_date, "
                "creator_id, week_number, weekday, calendar_revision_id, "
                "current_content_id, current_content_version, creator_display_name, "
                "class_name, grade, created_at, updated_at) "
                "VALUES (?, ?, ?, '2026-09-01', ?, 1, 1, ?, ?, 1, 't', ?, ?, ?, ?)",
                (
                    plan_id,
                    klass["id"],
                    term["id"],
                    profile_id,
                    term["current_calendar_revision_id"],
                    content_id,
                    klass["name"],
                    klass["grade"],
                    stamp,
                    stamp,
                ),
            )
            connection.execute(
                "INSERT INTO local_daily_plan_contents (id, daily_plan_id, version, "
                "raw_lesson_plan, adopted_content, editor_id, created_at) "
                "VALUES (?, ?, 1, NULL, '{}', ?, ?)",
                (content_id, plan_id, profile_id, stamp),
            )
            connection.execute(
                "INSERT INTO local_ai_inputs (id, daily_plan_id, content_id, "
                "content_version, task_type, target_grade, input_schema_version, "
                "payload_json, dependencies_json, dependency_hash, target_hashes_json, "
                "created_at) "
                "VALUES (?, ?, ?, 1, 'daily_lesson_split', ?, 1, '{}', '{}', '{}', "
                "'{}', ?)",
                (input_id, plan_id, content_id, klass["grade"], stamp),
            )
            connection.execute(
                "INSERT OR IGNORE INTO local_personal_prompt_versions (profile_id, "
                "task_type, revision, contract_version, based_default_revision, "
                "guidance_json, action, created_at) "
                "VALUES (?, 'daily_lesson_split', 1, 1, 1, '{}', 'initial', ?)",
                (profile_id, stamp),
            )
            connection.execute(
                "INSERT INTO local_ai_tasks (id, profile_id, daily_plan_id, task_type, "
                "input_id, status, reason, current_execution_id, generation, "
                "runtime_meta_json, created_at, updated_at) "
                "VALUES (?, ?, ?, 'daily_lesson_split', ?, ?, NULL, ?, 1, '{}', ?, ?)",
                (
                    task_id,
                    profile_id,
                    plan_id,
                    input_id,
                    task_status,
                    current_execution_id,
                    stamp,
                    stamp,
                ),
            )
            connection.execute(
                "INSERT INTO local_ai_executions (id, task_id, daily_plan_id, input_id, "
                "task_type, generation, launch_id, permit_id, config_version, profile_id, "
                "personal_revision, contract_version, default_revision, state, "
                "runtime_meta_json, started_at, created_at, ended_at) "
                "VALUES (?, ?, ?, ?, 'daily_lesson_split', 1, ?, ?, 1, ?, 1, 1, 1, ?, "
                "'{}', ?, ?, ?)",
                (
                    execution_id,
                    task_id,
                    plan_id,
                    input_id,
                    str(uuid.uuid4()),
                    str(uuid.uuid4()),
                    profile_id,
                    execution_state,
                    stamp,
                    stamp,
                    ended_at,
                ),
            )
            connection.execute("COMMIT")
        finally:
            connection.close()
        return execution_id, task_id

    def replace_secret(self, old_credential: str) -> dict:
        """Replace the secret with a new one and return the old credential row."""
        out = self.patch(
            expected_ai_config_version=1,
            secret=self.secret_b,
            request_id=str(uuid.uuid4()),
        )
        self.assertEqual(out.ai_config_version, 2)
        return self.credential_row(old_credential)

    def assert_wiped(self, row: dict) -> None:
        self.assertEqual(row["state"], "cleared")
        self.assertIsNone(row["nonce"])
        self.assertIsNone(row["ciphertext"])

    def credential_row(self, credential_id: str) -> dict:
        return query_rows(
            self.db,
            "SELECT state, nonce, ciphertext FROM local_ai_credentials WHERE id = ?",
            (credential_id,),
        )[0]


class ConfigServiceTests(ConfigServiceCase):
    def test_first_save_regression_and_unconfigured_get(self):
        self.initialize()
        # GET before any credential is configured: version 0, no cred dir.
        self.assertFalse(self.cred_root.exists())
        out = self.get_config()
        self.assertEqual(out.ai_config_version, 0)
        self.assertFalse(out.has_secret)
        self.assertFalse(self.cred_root.exists())

        # First PATCH with a secret must not crash (regression) and must
        # create restricted material only now.
        out = self.patch()
        self.assertEqual(out.ai_config_version, 1)
        self.assertTrue(out.ready)
        self.assertEqual(out.reason, None)
        self.assertTrue(self.cred_root.exists())
        self.assertEqual(
            query_scalar(self.db, "SELECT count(*) FROM local_ai_config_versions"), 1
        )

    def test_get_uninitialized_is_profile_required_and_creates_nothing(self):
        with self.assertRaises(svc.LocalProfileRequired) as ctx:
            self.get_config()
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertFalse(self.cred_root.exists())

    def test_same_secret_noop_is_hmac_and_keeps_version(self):
        self.initialize()
        first = self.patch()
        self.assertEqual(first.ai_config_version, 1)
        rid2 = str(uuid.uuid4())
        second = self.patch(
            expected_ai_config_version=1, secret=self.secret_a, request_id=rid2
        )
        self.assertEqual(second.ai_config_version, 1)
        self.assertEqual(first, second)
        self.assertEqual(
            query_scalar(self.db, "SELECT count(*) FROM local_ai_config_versions"), 1
        )
        receipt = query_scalar(
            self.db,
            "SELECT fingerprint_kind FROM local_ai_operations WHERE request_id = ?",
            (rid2,),
        )
        self.assertEqual(receipt, "hmac_sha256")
        self.assertIsNotNone(
            query_scalar(
                self.db,
                "SELECT fingerprint_key_id FROM local_ai_operations "
                "WHERE request_id = ?",
                (rid2,),
            )
        )

    def test_different_secret_new_version_and_full_snapshot(self):
        self.initialize()
        self.patch()
        rid = str(uuid.uuid4())
        out = self.patch(
            expected_ai_config_version=1, secret=self.secret_b, request_id=rid
        )
        self.assertEqual(out.ai_config_version, 2)
        self.assertTrue(out.ready)
        row = query_rows(
            self.db,
            "SELECT result_json FROM local_ai_operations WHERE request_id = ?",
            (rid,),
        )[0]
        snapshot = _json(row["result_json"])
        for key in (
            "ai_config_version",
            "protocol_id",
            "base_url",
            "model",
            "has_secret",
            "configured",
            "ready",
            "reason",
        ):
            self.assertIn(key, snapshot)
        self.assertEqual(snapshot["ai_config_version"], 2)
        self.assertEqual(snapshot["has_secret"], True)
        # Two credentials: the new active one and the superseded one cleared.
        states = {
            r["state"]
            for r in query_rows(self.db, "SELECT state FROM local_ai_credentials")
        }
        self.assertEqual(states, {"active", "cleared"})

    def test_omit_secret_model_change_keeps_secret(self):
        self.initialize()
        self.patch()
        out = self.patch(
            expected_ai_config_version=1,
            model="model-2",
            secret_provided=False,
            secret=None,
            request_id=str(uuid.uuid4()),
        )
        self.assertEqual(out.ai_config_version, 2)
        self.assertTrue(out.has_secret)
        self.assertTrue(out.ready)
        self.assertEqual(out.model, "model-2")

    def test_replay_returns_original_snapshot_after_clear(self):
        self.initialize()
        rid = str(uuid.uuid4())
        original = self.patch(request_id=rid)
        # Clear, then a later re-send of the PATCH must still return the
        # original response (not recomputed from the now-cleared credential).
        self.clear(expected=1, request_id=str(uuid.uuid4()))
        replay = self.patch(request_id=rid, expected_ai_config_version=0)
        self.assertEqual(replay, original)
        self.assertTrue(replay.has_secret)
        self.assertTrue(replay.ready)

    def test_clear_at_version_zero_does_not_bump_or_write_audit_version(self):
        self.initialize()
        rid = str(uuid.uuid4())
        out = self.clear(expected=0, request_id=rid)
        self.assertEqual(out.ai_config_version, 0)
        self.assertFalse(out.has_secret)
        self.assertFalse(self.cred_root.exists())
        # State pointer stays NULL; no pseudo version-0 config row was created.
        self.assertIsNone(
            query_scalar(self.db, "SELECT current_config_version FROM local_ai_state")
        )
        self.assertEqual(
            query_scalar(self.db, "SELECT count(*) FROM local_ai_config_versions"), 0
        )
        audit = query_rows(
            self.db,
            "SELECT target_id, target_version_after FROM local_operation_records "
            "WHERE action = 'clear_local_ai_secret'",
        )
        self.assertEqual(len(audit), 1)
        self.assertIsNone(audit[0]["target_version_after"])

    def test_clear_after_configured_clears_material_retains_keyfile(self):
        self.initialize()
        self.patch()
        old_cred = self.credential_id()
        key_file = self.key_file(old_cred)
        self.assertTrue(key_file.is_file())

        out = self.clear(expected=1, request_id=str(uuid.uuid4()))
        self.assertEqual(out.ai_config_version, 2)
        self.assertFalse(out.has_secret)
        self.assertIsNone(self.credential_id())
        rows = query_rows(
            self.db,
            "SELECT state, nonce IS NULL AS no_nonce, ciphertext IS NULL AS no_ct, "
            "key_id FROM local_ai_credentials",
        )
        for row in rows:
            self.assertEqual(row["state"], "cleared")
            self.assertEqual(row["no_nonce"], 1)
            self.assertEqual(row["no_ct"], 1)
            self.assertIsNotNone(row["key_id"])  # metadata is retained
        self.assertTrue(key_file.is_file())  # key file kept for receipt HMAC

    def test_clear_resend_replays(self):
        self.initialize()
        self.patch()
        rid = str(uuid.uuid4())
        first = self.clear(expected=1, request_id=rid)
        second = self.clear(expected=1, request_id=rid)
        self.assertEqual(first, second)
        self.assertEqual(
            query_scalar(self.db, "SELECT count(*) FROM local_ai_config_versions"), 2
        )

    def test_cross_domain_same_request_id_conflict(self):
        self.initialize()
        rid = str(uuid.uuid4())
        self.patch(request_id=rid)
        with self.assertRaises(svc.AiRequestConflict) as ctx:
            self.clear(expected=1, request_id=rid)
        self.assertEqual(ctx.exception.code, "AI_REQUEST_CONFLICT")

    def test_different_body_same_request_id_conflict(self):
        self.initialize()
        rid = str(uuid.uuid4())
        self.patch(request_id=rid)
        with self.assertRaises(svc.AiRequestConflict):
            self.patch(
                expected_ai_config_version=0,
                model="other-model",
                request_id=rid,
            )

    def test_stale_expected_version_uses_ai_version_conflict(self):
        self.initialize()
        self.patch()
        with self.assertRaises(svc.AiVersionConflict) as ctx:
            self.patch(
                expected_ai_config_version=0,
                request_id=str(uuid.uuid4()),
            )
        self.assertEqual(ctx.exception.code, "AI_VERSION_CONFLICT")

    def test_corrupt_blob_degrades_and_refill_recovers(self):
        self.initialize()
        self.patch()
        cred = self.credential_id()
        # Corrupt the stored ciphertext in place (single synthetic mutation).
        execute_sql(
            self.db,
            "UPDATE local_ai_credentials SET ciphertext = ? WHERE id = ?",
            (bytes(32), cred),
        )
        degraded = self.get_config()
        self.assertFalse(degraded.ready)
        self.assertEqual(degraded.reason, "CREDENTIAL_UNAVAILABLE")
        self.assertTrue(degraded.has_secret)
        self.assertTrue(degraded.configured)
        # Explicit refill with a new secret recovers to a new version.
        refilled = self.patch(
            expected_ai_config_version=1,
            secret=self.secret_b,
            request_id=str(uuid.uuid4()),
        )
        self.assertEqual(refilled.ai_config_version, 2)
        self.assertTrue(refilled.ready)

    def test_live_claimed_execution_retains_material_as_retired(self):
        self.initialize()
        self.patch()  # v1 with credential C1
        old_cred = self.credential_id()
        self.pin_execution(task_status="claimed", execution_state="claimed")

        row = self.replace_secret(old_cred)
        # C1 is pinned by a live claimed execution -> retired, material kept.
        self.assertEqual(row["state"], "retired")
        self.assertIsNotNone(row["nonce"])
        self.assertIsNotNone(row["ciphertext"])

    def test_replaced_without_live_execution_wipes_material(self):
        self.initialize()
        self.patch()
        old_cred = self.credential_id()
        # No execution exists at all.
        self.assert_wiped(self.replace_secret(old_cred))

    def test_pending_task_does_not_retain_material(self):
        self.initialize()
        self.patch()
        old_cred = self.credential_id()
        # The task went back to pending; its old execution is still claimed.
        # An execution only exists once a claim starts (§4.1), so pending is
        # not a live state and the material must be wiped.
        self.pin_execution(task_status="pending", execution_state="claimed")
        self.assert_wiped(self.replace_secret(old_cred))

    def test_execution_not_current_pointer_does_not_retain_material(self):
        self.initialize()
        self.patch()
        old_cred = self.credential_id()
        # The execution is still claimed but the task no longer points at it.
        self.pin_execution(
            task_status="claimed", execution_state="claimed", pointer=False
        )
        self.assert_wiped(self.replace_secret(old_cred))

    def test_paused_task_does_not_retain_material(self):
        self.initialize()
        self.patch()
        old_cred = self.credential_id()
        self.pin_execution(task_status="paused", execution_state="claimed")
        self.assert_wiped(self.replace_secret(old_cred))

    def test_paused_execution_does_not_retain_material(self):
        self.initialize()
        self.patch()
        old_cred = self.credential_id()
        self.pin_execution(task_status="claimed", execution_state="paused")
        self.assert_wiped(self.replace_secret(old_cred))

    def test_outcome_unknown_task_does_not_retain_material(self):
        self.initialize()
        self.patch()
        old_cred = self.credential_id()
        self.pin_execution(task_status="outcome_unknown", execution_state="claimed")
        self.assert_wiped(self.replace_secret(old_cred))

    def test_outcome_unknown_execution_does_not_retain_material(self):
        self.initialize()
        self.patch()
        old_cred = self.credential_id()
        self.pin_execution(task_status="claimed", execution_state="outcome_unknown")
        self.assert_wiped(self.replace_secret(old_cred))

    def test_ended_execution_does_not_retain_material(self):
        self.initialize()
        self.patch()
        old_cred = self.credential_id()
        # Still claimed/claimed and current, but the execution already ended.
        self.pin_execution(
            task_status="claimed", execution_state="claimed", ended=True
        )
        self.assert_wiped(self.replace_secret(old_cred))

    def test_hardlinked_key_degrades_and_refill_creates_new_key(self):
        self.initialize()
        self.patch()
        old_cred = self.credential_id()
        key_file = self.key_file(old_cred)
        os.link(key_file, key_file.with_name("alias-key.dpapi"))
        self.assertEqual(os.stat(key_file).st_nlink, 2)

        degraded = self.get_config()
        self.assertFalse(degraded.ready)
        self.assertEqual(degraded.reason, "CREDENTIAL_UNAVAILABLE")
        self.assertTrue(degraded.has_secret)

        refilled = self.patch(
            expected_ai_config_version=1,
            secret=self.secret_b,
            request_id=str(uuid.uuid4()),
        )
        self.assertEqual(refilled.ai_config_version, 2)
        self.assertTrue(refilled.ready)
        # A brand-new key_id was written; the old one is cleared in the DB.
        self.assertNotEqual(self.credential_id(), old_cred)

    def test_unreadable_receipt_key_keeps_get_and_blocks_replay(self):
        self.initialize()
        rid = str(uuid.uuid4())
        original = self.patch(request_id=rid)  # v1 with credential C1
        self.assertTrue(original.ready)
        credential = self.credential_id()
        key_file = self.key_file(credential)
        self.assertTrue(key_file.is_file())
        # Corrupt the master key file in place (the current user owns it).
        key_file.write_bytes(b"\x00" * 64)

        # GET still returns the persisted facts (degraded, not an error).
        degraded = self.get_config()
        self.assertFalse(degraded.ready)
        self.assertEqual(degraded.reason, "CREDENTIAL_UNAVAILABLE")
        self.assertTrue(degraded.has_secret)
        self.assertTrue(degraded.configured)
        self.assertEqual(degraded.ai_config_version, 1)

        # A secret-bearing re-send cannot be verified -> 409 with the
        # persisted redacted original result.
        with self.assertRaises(svc.AiReceiptUnverifiable) as ctx:
            self.patch(request_id=rid, expected_ai_config_version=0)
        self.assertEqual(ctx.exception.code, "AI_RECEIPT_UNVERIFIABLE")
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.details["result"]["ai_config_version"], 1)
        # No material was written and no new version committed.
        self.assertEqual(
            query_scalar(self.db, "SELECT count(*) FROM local_ai_config_versions"), 1
        )

    def test_key_id_file_collision_is_never_reused(self):
        self.initialize()
        self.patch()  # v1 with credential C1
        database_uuid = query_scalar(
            self.db, "SELECT database_uuid FROM local_ai_state"
        )
        colliding = f"collide{uuid.uuid4().hex[:16]}"
        collision_path = self.cred_root / database_uuid / f"{colliding}.dpapi"
        collision_path.write_bytes(b"sentinel-not-a-key")

        # The allocator keeps returning the colliding id; the store refuses to
        # reuse/overwrite it, so the write fails safely instead of clobbering.
        with mock.patch.object(svc, "new_opaque_id", lambda: colliding):
            with self.assertRaises(svc.LocalStorageError):
                self.patch(
                    expected_ai_config_version=1,
                    secret=self.secret_b,
                    request_id=str(uuid.uuid4()),
                )
        self.assertEqual(collision_path.read_bytes(), b"sentinel-not-a-key")
        self.assertEqual(
            query_scalar(self.db, "SELECT count(*) FROM local_ai_config_versions"), 1
        )
        self.assertEqual(
            query_scalar(self.db, "SELECT count(*) FROM local_ai_credentials"), 1
        )

    def test_junction_credential_root_degrades_and_refuses_write(self):
        self.initialize()
        self.patch()  # v1 material in the real root
        target = self.tmp_root / "junction-target"
        target.mkdir()
        link = self.tmp_root / "junction-link"
        created = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
        )
        if created.returncode != 0:
            self.skipTest(f"junction unavailable: {created.stdout!r}")

        # The aliased root degrades a GET without touching DB state.
        session = self.runtime.session()
        try:
            degraded = svc.get_config(session, credential_root=link)
        finally:
            session.close()
        self.assertFalse(degraded.ready)
        self.assertEqual(degraded.reason, "CREDENTIAL_UNAVAILABLE")
        self.assertTrue(degraded.has_secret)
        self.assertEqual(degraded.ai_config_version, 1)

        # Writing new material through an aliased root is refused (503 path)
        # and the head is unchanged.
        with self.assertRaises(svc.LocalStorageError):
            self.patch(
                expected_ai_config_version=1,
                secret=self.secret_b,
                request_id=str(uuid.uuid4()),
                credential_root=link,
            )
        self.assertEqual(
            query_scalar(self.db, "SELECT current_config_version FROM local_ai_state"),
            1,
        )
        self.assertEqual(
            query_scalar(self.db, "SELECT count(*) FROM local_ai_config_versions"), 1
        )


class ConfigConcurrencyTests(ConfigServiceCase):
    suffix = "cfg-race"

    def _run_two(self, bodies: list[dict]) -> list[tuple[str, object]]:
        barrier = threading.Barrier(2)
        original = CredentialStore.save_master_key

        def wrapped(store_self, key_id):
            master = original(store_self, key_id)
            barrier.wait(timeout=30)
            return master

        results: list[tuple[str, object]] = [
            ("error", "not-run"),
            ("error", "not-run"),
        ]

        def run(index: int) -> None:
            session = self.runtime.session()
            try:
                out = svc.patch_config(
                    session, credential_root=self.cred_root, **bodies[index]
                )
                results[index] = ("ok", out)
            except Exception as exc:  # noqa: BLE001 - record the public code
                results[index] = (
                    "error",
                    getattr(exc, "code", type(exc).__name__),
                )
            finally:
                session.close()

        with mock.patch.object(CredentialStore, "save_master_key", wrapped):
            threads = [
                threading.Thread(target=run, args=(0,)),
                threading.Thread(target=run, args=(1,)),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=60)
        self.assertFalse([t for t in threads if t.is_alive()])
        return results

    def test_same_request_id_concurrent_both_200_single_version(self):
        self.initialize()
        rid = str(uuid.uuid4())
        body = {
            "expected_ai_config_version": 0,
            "base_url": "https://api.example.com/v1",
            "model": "model-1",
            "secret": self.secret_a,
            "secret_provided": True,
            "request_id": rid,
        }
        first, second = self._run_two([dict(body), dict(body)])
        self.assertEqual(first[0], "ok", first)
        self.assertEqual(second[0], "ok", second)
        self.assertEqual(first[0], second[0])
        self.assertEqual(first[1], second[1])
        self.assertEqual(first[1].ai_config_version, 1)
        self.assertEqual(
            query_scalar(self.db, "SELECT count(*) FROM local_ai_config_versions"), 1
        )
        self.assertEqual(
            query_scalar(self.db, "SELECT count(*) FROM local_ai_operations"), 1
        )

    def test_different_request_id_concurrent_one_wins(self):
        self.initialize()
        base = {
            "expected_ai_config_version": 0,
            "base_url": "https://api.example.com/v1",
            "model": "model-1",
        }
        first, second = self._run_two(
            [
                dict(base, secret=self.secret_a, secret_provided=True,
                     request_id=str(uuid.uuid4())),
                dict(base, secret=self.secret_b, secret_provided=True,
                     request_id=str(uuid.uuid4())),
            ]
        )
        results = [first, second]
        oks = [r for r in results if r[0] == "ok"]
        errors = [r for r in results if r[0] == "error"]
        self.assertEqual(len(oks), 1, results)
        self.assertEqual(len(errors), 1, results)
        self.assertEqual(errors[0][1], "AI_VERSION_CONFLICT")
        self.assertEqual(oks[0][1].ai_config_version, 1)
        self.assertEqual(
            query_scalar(self.db, "SELECT count(*) FROM local_ai_config_versions"), 1
        )
        self.assertEqual(
            query_scalar(self.db, "SELECT count(*) FROM local_ai_operations"), 1
        )


class ConfigHttpTests(ConfigServiceCase):
    suffix = "cfg-http"

    def setUp(self) -> None:
        super().setUp()
        self.server = self.start_server(self.runtime)
        self.client = self.server.client()
        self.initialize()
        self.assertEqual(
            self.client.get("/api/local/ai/config")[0], 200
        )

    def patch_body(self, **overrides) -> dict:
        body = {
            "request_id": str(uuid.uuid4()),
            "expected_ai_config_version": 0,
            "protocol_id": "chat_completions_v1",
            "base_url": "https://api.example.com/v1",
            "model": "model-1",
            "secret": secrets.token_urlsafe(18),
        }
        body.update(overrides)
        return body

    def test_required_and_fixed_protocol_validation(self):
        for body, label in [
            (self.patch_body(protocol_id=None), "null"),
            (self.patch_body(protocol_id="other_v1"), "wrong"),
        ]:
            body.pop("protocol_id") if body.get("protocol_id") is None else None
            status, payload = self.client.patch("/api/local/ai/config", body)
            self.assertEqual(status, 422, (label, payload))
            self.assertEqual(payload["error"]["code"], "VALIDATION_ERROR")

        # Missing protocol_id entirely.
        missing = self.patch_body()
        missing.pop("protocol_id")
        status, payload = self.client.patch("/api/local/ai/config", missing)
        self.assertEqual(status, 422, payload)

    def test_secret_null_and_missing_base_url_rejected(self):
        explicit_null = self.patch_body(secret=None)
        status, payload = self.client.patch("/api/local/ai/config", explicit_null)
        self.assertEqual(status, 422, payload)

        missing_url = self.patch_body()
        missing_url.pop("base_url")
        status, payload = self.client.patch("/api/local/ai/config", missing_url)
        self.assertEqual(status, 422, payload)

        null_url = self.patch_body(base_url=None)
        status, payload = self.client.patch("/api/local/ai/config", null_url)
        self.assertEqual(status, 422, payload)

        blank_model = self.patch_body(model="   ")
        status, payload = self.client.patch("/api/local/ai/config", blank_model)
        self.assertEqual(status, 422, payload)

    def test_schema_scalars_and_extra_fields(self):
        for body in [
            self.patch_body(expected_ai_config_version=True),
            self.patch_body(expected_ai_config_version=1.5),
            self.patch_body(request_id="not-a-uuid"),
            self.patch_body(extra_field=1),
        ]:
            status, payload = self.client.patch("/api/local/ai/config", body)
            self.assertEqual(status, 422, payload)
            self.assertEqual(payload["error"]["code"], "VALIDATION_ERROR")

        # A syntactically valid but forbidden endpoint (IPv6 loopback) is a
        # 422 AI_ENDPOINT_INVALID from the service, not a schema error.
        status, payload = self.client.patch(
            "/api/local/ai/config", self.patch_body(base_url="https://[::1]/v1")
        )
        self.assertEqual(status, 422, payload)
        self.assertEqual(payload["error"]["code"], "AI_ENDPOINT_INVALID")

    def test_violation_response_never_echoes_secret(self):
        secret = "top-secret-\u4fdd\u5bc6"
        body = self.patch_body(model="m\x7fdel", secret=secret)
        status, payload = self.client.patch("/api/local/ai/config", body)
        self.assertEqual(status, 422, payload)
        text = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn(secret, text)
        self.assertNotIn("m\x7fdel", text)

    def test_replay_is_verbatim_and_leaks_no_secret(self):
        secret = secrets.token_urlsafe(18)
        body = self.patch_body(secret=secret)
        status, first = self.client.patch("/api/local/ai/config", body)
        self.assertEqual(status, 200, first)
        self.assertEqual(
            set(first),
            {
                "ai_config_version",
                "protocol_id",
                "base_url",
                "model",
                "has_secret",
                "configured",
                "ready",
                "reason",
            },
        )

        # Simulate a lost response: resend the identical request.
        status, second = self.client.patch("/api/local/ai/config", body)
        self.assertEqual(status, 200, second)
        self.assertEqual(second, first)
        first_text = json.dumps(first, ensure_ascii=False)
        second_text = json.dumps(second, ensure_ascii=False)
        self.assertNotIn(secret, first_text)
        self.assertNotIn(secret, second_text)
        # The persisted receipt snapshot is exactly the redacted response.
        snapshot = _json(
            query_scalar(
                self.db,
                "SELECT result_json FROM local_ai_operations WHERE request_id = ?",
                (body["request_id"],),
            )
        )
        for key, value in first.items():
            self.assertEqual(snapshot[key], value)
        self.assertEqual(
            query_scalar(self.db, "SELECT count(*) FROM local_ai_config_versions"), 1
        )
        self.assertEqual(
            query_scalar(self.db, "SELECT count(*) FROM local_ai_operations"), 1
        )

    def test_clear_uses_client_request_id_and_receipt_is_readable(self):
        status, _ = self.client.patch("/api/local/ai/config", self.patch_body())
        self.assertEqual(status, 200)
        rid = str(uuid.uuid4())
        status, payload = self.client.post(
            "/api/local/ai/config/clear-secret",
            {"request_id": rid, "expected_ai_config_version": 1},
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["ai_config_version"], 2)
        status, receipt = self.client.get(f"/api/local/ai/operations/{rid}")
        self.assertEqual(status, 200, receipt)
        self.assertEqual(receipt["operation_kind"], "ai_config_clear_secret")
        # Unknown receipt -> 404.
        status, payload = self.client.get(
            f"/api/local/ai/operations/{uuid.uuid4()}"
        )
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "AI_OPERATION_NOT_FOUND")

    def test_get_before_initialize_is_409(self):
        other = self.tmp_root / "cfg-http-empty" / "data"
        cred = self.tmp_root / "cfg-http-empty" / "credentials"
        runtime = LocalRuntime(data_dir=other, credential_root=cred)
        runtime.prepare()
        self.addCleanup(runtime.dispose)
        server = self.start_server(runtime)
        client = server.client()
        status, payload = client.get("/api/local/ai/config")
        self.assertEqual(status, 409, payload)
        self.assertEqual(payload["error"]["code"], "LOCAL_PROFILE_REQUIRED")

    def test_db_write_failure_is_503_and_head_unchanged(self):
        fired = {"count": 0}
        original = svc._store_receipt_and_audit

        def boom(*args, **kwargs):
            fired["count"] += 1
            raise sqlite3.OperationalError("disk I/O error")

        with mock.patch.object(svc, "_store_receipt_and_audit", boom):
            status, payload = self.client.patch(
                "/api/local/ai/config", self.patch_body()
            )
        self.assertEqual(fired["count"], 1, fired)
        self.assertEqual(status, 503, payload)
        self.assertIn(payload["error"]["code"], {"LOCAL_STORAGE_ERROR"})
        # Head and version did not advance; no receipt committed.
        self.assertIsNone(
            query_scalar(self.db, "SELECT current_config_version FROM local_ai_state")
        )
        self.assertEqual(
            query_scalar(self.db, "SELECT count(*) FROM local_ai_config_versions"), 0
        )
        self.assertEqual(
            query_scalar(self.db, "SELECT count(*) FROM local_ai_operations"), 0
        )


if __name__ == "__main__":
    unittest.main()
