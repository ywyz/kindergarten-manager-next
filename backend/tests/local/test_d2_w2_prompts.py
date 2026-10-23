"""D2 W2 personal prompt service: version, accept/reject/adapt and receipts.

Real temp SQLite through ``LocalRuntime`` (which also runs the package bundle
sync) and a real local Uvicorn server via the standard-library client. No
whole-path mock; the only fault injection is a single ``_store_receipt`` point
and asserts its error propagates without a half-written version.

Scope: three daily tasks, read-only GET, empty strings / 8000 limit, exact
field map, r2-accept while r3 published, reject exact revision, required
contract upgrade (no personal overwrite, new field prefill, removed field
orphaned, explicit adapt), repeated contract evolution (latest-wins orphaned),
receipt priority / cross-domain conflict, commit-failure rollback and request
protection.
"""

from __future__ import annotations

import json
import unittest
import uuid
from unittest import mock

from app.local import prompt_bundles, prompt_service
from app.local.errors import LocalError, LocalStorageError
from app.local.prompt_bundles import PROMPT_BUNDLE_MANIFEST
from app.local.runtime import LocalRuntime
from tests.local.support import (
    LocalTestCase,
    initialize_body,
    query_rows,
    query_scalar,
)

TASKS = ("daily_lesson_split", "daily_process_adapt", "daily_other_activities")


def _task_bundle(task_type: str) -> dict:
    """The current package bundle (highest contract/default) for tests."""
    return max(
        (b for b in PROMPT_BUNDLE_MANIFEST if b["task_type"] == task_type),
        key=lambda b: (b["contract_version"], b["default_revision"]),
    )


def _bundle_at(task_type: str, contract: int, default: int) -> dict:
    return next(
        b
        for b in PROMPT_BUNDLE_MANIFEST
        if b["task_type"] == task_type
        and b["contract_version"] == contract
        and b["default_revision"] == default
    )


def make_bundle(
    task_type: str,
    contract: int,
    default: int,
    *,
    text: dict | None = None,
    drop_fields: tuple[str, ...] = (),
    keep_fields: tuple[str, ...] | None = None,
) -> dict:
    """A synthetic bundle: same schema/field-set unless fields are changed.

    ``text`` overrides default guidance text; ``drop_fields``/``keep_fields``
    change the guidance field set (only allowed across contract versions).
    """
    base = _task_bundle(task_type)
    guidance = dict(base["guidance_defaults_json"])
    if keep_fields is not None:
        guidance = {key: guidance[key] for key in keep_fields}
    for key in drop_fields:
        guidance.pop(key, None)
    if text:
        guidance.update(text)
    return {
        "task_type": task_type,
        "contract_version": contract,
        "default_revision": default,
        "input_schema_json": base["input_schema_json"],
        "output_schema_json": base["output_schema_json"],
        "guidance_defaults_json": guidance,
    }


class PromptCase(LocalTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.runtime = self.make_runtime()
        self.db = self.runtime.db_path
        self.initialize_profile()

    def http_client(self):
        if getattr(self, "_client", None) is None:
            self._client = self.start_server(self.runtime).client()
        return self._client

    def initialize_profile(self) -> None:
        from app.local import profile_service
        from app.local.normalize import normalize_initialization
        from tests.local.support import initialize_body

        session = self.runtime.session()
        try:
            profile_service.initialize(
                session, normalize_initialization(**initialize_body())
            )
        finally:
            session.close()

    def session(self):
        return self.runtime.session()

    def sync(self, bundles) -> dict:
        session = self.session()
        try:
            return prompt_bundles.sync_prompt_bundles(session, bundles)
        finally:
            session.close()

    def revision_of(self, task_type: str) -> int:
        return query_scalar(
            self.db,
            "SELECT current_revision FROM local_personal_prompt_heads "
            "WHERE task_type = ?",
            (task_type,),
        )

    def prompt(self, task_type: str) -> dict:
        session = self.session()
        try:
            return prompt_service.get_prompt(session, task_type=task_type)
        finally:
            session.close()

    def edit(self, task_type: str, guidance: dict, *, expected, contract, request_id=None):
        session = self.session()
        try:
            return prompt_service.save_prompt(
                session,
                task_type=task_type,
                expected_personal_revision=expected,
                contract_version=contract,
                guidance=guidance,
                request_id=request_id or str(uuid.uuid4()),
            )
        finally:
            session.close()


class PromptReadTests(PromptCase):
    def test_list_only_three_daily_tasks_and_no_version_bump(self):
        before = query_scalar(
            self.db, "SELECT count(*) FROM local_personal_prompt_versions"
        )
        session = self.session()
        try:
            out = prompt_service.list_prompts(session)
        finally:
            session.close()
        self.assertEqual([item["task_type"] for item in out["items"]], list(TASKS))
        self.assertEqual(
            query_scalar(
                self.db, "SELECT count(*) FROM local_personal_prompt_versions"
            ),
            before,
        )

    def test_get_prompt_is_read_only(self):
        out = self.prompt("daily_lesson_split")
        self.assertEqual(out["personal_revision"], 1)
        self.assertEqual(out["contract_version"], 1)
        self.assertFalse(out["adaptation_required"])
        self.assertEqual(
            sorted(out["guidance"].keys()),
            sorted(_task_bundle("daily_lesson_split")["guidance_defaults_json"]),
        )
        self.assertEqual(
            [field["key"] for field in out["fields"]],
            list(_task_bundle("daily_lesson_split")["guidance_defaults_json"]),
        )

    def test_get_default_bundle_and_missing_404(self):
        session = self.session()
        try:
            out = prompt_service.get_default(
                session,
                task_type="daily_process_adapt",
                contract_version=1,
                default_revision=1,
            )
            self.assertEqual(out["guidance"]["process"], _bundle_at("daily_process_adapt", 1, 1)["guidance_defaults_json"]["process"])
            with self.assertRaises(LocalError) as ctx:
                prompt_service.get_default(
                    session,
                    task_type="daily_process_adapt",
                    contract_version=9,
                    default_revision=1,
                )
            self.assertEqual(ctx.exception.code, "AI_NOT_FOUND")
        finally:
            session.close()

    def test_unknown_task_and_strict_integers_rejected(self):
        session = self.session()
        try:
            with self.assertRaises(LocalError) as ctx:
                prompt_service.get_prompt(session, task_type="weekly_columns")
            self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
            with self.assertRaises(LocalError):
                prompt_service.get_default(
                    session,
                    task_type="daily_lesson_split",
                    contract_version=True,
                    default_revision=1,
                )
        finally:
            session.close()


class PromptEditTests(PromptCase):
    def test_edit_bumps_and_empty_strings_allowed(self):
        guidance = dict(_task_bundle("daily_lesson_split")["guidance_defaults_json"])
        guidance["theme"] = ""
        out = self.edit(
            "daily_lesson_split", guidance, expected=1, contract=1
        )
        self.assertEqual(out["personal_revision"], 2)
        self.assertEqual(out["guidance"]["theme"], "")
        self.assertEqual(self.revision_of("daily_lesson_split"), 2)
        # Same content again is a no-op (no bump).
        same = self.edit("daily_lesson_split", guidance, expected=2, contract=1)
        self.assertEqual(same["personal_revision"], 2)

    def test_8000_boundary_and_missing_or_unknown_field(self):
        guidance = dict(_task_bundle("daily_lesson_split")["guidance_defaults_json"])
        guidance["process"] = "x" * 8000
        out = self.edit("daily_lesson_split", guidance, expected=1, contract=1)
        self.assertEqual(len(out["guidance"]["process"]), 8000)

        too_long = dict(guidance)
        too_long["process"] = "x" * 8001
        with self.assertRaises(LocalError) as ctx:
            self.edit("daily_lesson_split", too_long, expected=2, contract=1)
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

        missing = dict(guidance)
        missing.pop("theme")
        with self.assertRaises(LocalError):
            self.edit("daily_lesson_split", missing, expected=2, contract=1)
        extra = dict(guidance)
        extra["reflection"] = "x"
        with self.assertRaises(LocalError):
            self.edit("daily_lesson_split", extra, expected=2, contract=1)

    def test_stale_expected_revision_conflict(self):
        guidance = dict(_task_bundle("daily_lesson_split")["guidance_defaults_json"])
        guidance["theme"] = "新主题"
        with self.assertRaises(LocalError) as ctx:
            self.edit("daily_lesson_split", guidance, expected=5, contract=1)
        self.assertEqual(ctx.exception.code, "PROMPT_VERSION_CONFLICT")
        self.assertEqual(ctx.exception.details["personal_revision"], 1)


class PromptAcceptRejectTests(PromptCase):
    def test_accept_r2_while_r3_published_only_selected_fields(self):
        # Keep a custom process in the personal version, then accept only the
        # r2 theme after r3 is published. The unselected process must survive.
        custom = dict(_task_bundle("daily_lesson_split")["guidance_defaults_json"])
        custom["process"] = "教师自定义过程\n不得被默认覆盖"
        custom["theme"] = "教师自定义主题"
        self.edit("daily_lesson_split", custom, expected=1, contract=1)
        self.sync(
            [make_bundle("daily_lesson_split", 1, 3, text={"theme": "r3 主题"})]
        )
        out = self.prompt("daily_lesson_split")
        self.assertEqual(out["latest_default_revision"], 3)
        self.assertEqual(out["personal_revision"], 2)
        session = self.session()
        try:
            accepted = prompt_service.accept_default(
                session,
                task_type="daily_lesson_split",
                expected_personal_revision=2,
                target_contract_version=1,
                target_default_revision=2,
                selected_fields=["theme"],
                request_id=str(uuid.uuid4()),
            )
        finally:
            session.close()
        r2 = _bundle_at("daily_lesson_split", 1, 2)["guidance_defaults_json"]
        self.assertEqual(accepted["guidance"]["theme"], r2["theme"])
        self.assertEqual(accepted["based_default_revision"], 2)
        self.assertEqual(accepted["personal_revision"], 3)
        # r3 is still pending: the later default is neither applied nor rejected.
        self.assertEqual(accepted["latest_default_revision"], 3)
        self.assertIsNone(accepted["rejected_default_revision"])
        self.assertEqual(accepted["guidance"]["process"], custom["process"])

    def test_accept_empty_selected_fields_and_bad_field_rejected(self):
        session = self.session()
        try:
            with self.assertRaises(LocalError):
                prompt_service.accept_default(
                    session,
                    task_type="daily_lesson_split",
                    expected_personal_revision=1,
                    target_contract_version=1,
                    target_default_revision=2,
                    selected_fields=[],
                    request_id=str(uuid.uuid4()),
                )
            with self.assertRaises(LocalError):
                prompt_service.accept_default(
                    session,
                    task_type="daily_lesson_split",
                    expected_personal_revision=1,
                    target_contract_version=1,
                    target_default_revision=2,
                    selected_fields=["theme", "theme"],
                    request_id=str(uuid.uuid4()),
                )
            with self.assertRaises(LocalError):
                prompt_service.accept_default(
                    session,
                    task_type="daily_lesson_split",
                    expected_personal_revision=1,
                    target_contract_version=1,
                    target_default_revision=2,
                    selected_fields=["nope"],
                    request_id=str(uuid.uuid4()),
                )
        finally:
            session.close()

    def test_reject_records_exact_revision_and_is_idempotent(self):
        self.sync([make_bundle("daily_lesson_split", 1, 3, text={"theme": "r3"})])
        session = self.session()
        try:
            rejected = prompt_service.reject_default(
                session,
                task_type="daily_lesson_split",
                expected_personal_revision=1,
                target_contract_version=1,
                target_default_revision=3,
                request_id=str(uuid.uuid4()),
            )
            self.assertEqual(rejected["rejected_default_revision"], 3)
            self.assertEqual(rejected["personal_revision"], 2)
            self.assertEqual(
                rejected["guidance"]["theme"],
                _task_bundle("daily_lesson_split")["guidance_defaults_json"]["theme"],
            )
            # Rejecting the same revision again is a no-op.
            again = prompt_service.reject_default(
                session,
                task_type="daily_lesson_split",
                expected_personal_revision=2,
                target_contract_version=1,
                target_default_revision=3,
                request_id=str(uuid.uuid4()),
            )
            self.assertEqual(again["personal_revision"], 2)
        finally:
            session.close()


class PromptContractTests(PromptCase):
    def _publish_contract_2_drop_difficult(self):
        self.sync(
            [
                make_bundle(
                    "daily_lesson_split",
                    2,
                    1,
                    drop_fields=("difficult_points",),
                )
            ]
        )

    def test_required_upgrade_keeps_text_and_orphans_removed_field(self):
        self._publish_contract_2_drop_difficult()
        out = self.prompt("daily_lesson_split")
        self.assertTrue(out["adaptation_required"])
        self.assertEqual(out["required_contract_version"], 2)
        self.assertEqual(out["contract_version"], 1)
        # Removed field is queryable as orphaned with the current text.
        self.assertIn(
            "difficult_points",
            out["orphaned_guidance"],
        )

    def test_normal_edit_stays_old_contract_and_adapt_clears(self):
        self._publish_contract_2_drop_difficult()
        old_guidance = dict(_task_bundle("daily_lesson_split")["guidance_defaults_json"])
        old_guidance["theme"] = "旧契约修改"
        edited = self.edit(
            "daily_lesson_split", old_guidance, expected=1, contract=1
        )
        self.assertTrue(edited["adaptation_required"])
        self.assertEqual(edited["contract_version"], 1)
        self.assertEqual(edited["guidance"]["theme"], "旧契约修改")

        # A normal edit that pretends to be the required contract is refused.
        with self.assertRaises(LocalError) as ctx:
            self.edit(
                "daily_lesson_split", old_guidance, expected=2, contract=2
            )
        self.assertEqual(ctx.exception.code, "PROMPT_ADAPTATION_REQUIRED")

        # Explicit adapt to the current required contract.
        session = self.session()
        try:
            bundle = prompt_bundles._normalize_manifest(
                [
                    make_bundle(
                        "daily_lesson_split", 2, 1, drop_fields=("difficult_points",)
                    )
                ]
            )[(("daily_lesson_split"), 2, 1)]
            new_guidance = dict(bundle["guidance_defaults_json"])
            adapted = prompt_service.adapt_prompt(
                session,
                task_type="daily_lesson_split",
                expected_personal_revision=2,
                target_contract_version=2,
                target_default_revision=1,
                guidance=new_guidance,
                request_id=str(uuid.uuid4()),
            )
        finally:
            session.close()
        self.assertFalse(adapted["adaptation_required"])
        self.assertEqual(adapted["contract_version"], 2)
        self.assertEqual(adapted["guidance"]["theme"], new_guidance["theme"])
        self.assertIn("difficult_points", adapted["orphaned_guidance"])

    def test_adapt_target_must_be_current_required(self):
        session = self.session()
        try:
            with self.assertRaises(LocalError) as ctx:
                prompt_service.adapt_prompt(
                    session,
                    task_type="daily_lesson_split",
                    expected_personal_revision=1,
                    target_contract_version=2,
                    target_default_revision=1,
                    guidance={},
                    request_id=str(uuid.uuid4()),
                )
            self.assertEqual(ctx.exception.code, "PROMPT_CONTRACT_CHANGED")
        finally:
            session.close()

    def test_repeated_contract_evolution_keeps_latest_orphan_text(self):
        # c1 -> edit theme T1
        guidance = dict(_task_bundle("daily_lesson_split")["guidance_defaults_json"])
        guidance["theme"] = "T1"
        self.edit("daily_lesson_split", guidance, expected=1, contract=1)
        # c2 removes theme -> orphaned T1
        self.sync(
            [
                make_bundle(
                    "daily_lesson_split", 2, 1, drop_fields=("theme",)
                )
            ]
        )
        out = self.prompt("daily_lesson_split")
        self.assertEqual(out["orphaned_guidance"]["theme"], "T1")
        # adapt to c2
        c2 = prompt_bundles._normalize_manifest(
            [make_bundle("daily_lesson_split", 2, 1, drop_fields=("theme",))]
        )["daily_lesson_split", 2, 1]
        session = self.session()
        try:
            prompt_service.adapt_prompt(
                session,
                task_type="daily_lesson_split",
                expected_personal_revision=2,
                target_contract_version=2,
                target_default_revision=1,
                guidance=dict(c2["guidance_defaults_json"]),
                request_id=str(uuid.uuid4()),
            )
        finally:
            session.close()
        # c3 re-adds theme (same six fields) -> adapt back
        self.sync([make_bundle("daily_lesson_split", 3, 1)])
        session = self.session()
        try:
            prompt_service.adapt_prompt(
                session,
                task_type="daily_lesson_split",
                expected_personal_revision=3,
                target_contract_version=3,
                target_default_revision=1,
                guidance=dict(_task_bundle("daily_lesson_split")["guidance_defaults_json"]),
                request_id=str(uuid.uuid4()),
            )
        finally:
            session.close()
        # edit theme to the latest teacher text T2
        latest = dict(_task_bundle("daily_lesson_split")["guidance_defaults_json"])
        latest["theme"] = "T2"
        self.edit("daily_lesson_split", latest, expected=4, contract=3)
        # c4 removes theme again -> orphaned must be T2, not the stale T1
        self.sync([make_bundle("daily_lesson_split", 4, 1, drop_fields=("theme",))])
        out = self.prompt("daily_lesson_split")
        self.assertEqual(out["orphaned_guidance"]["theme"], "T2")

    def test_same_contract_shape_change_is_refused(self):
        with self.assertRaises(LocalError) as ctx:
            self.sync(
                [
                    make_bundle(
                        "daily_lesson_split", 1, 3, drop_fields=("theme",)
                    )
                ]
            )
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_same_key_different_hash_conflict_leaves_state(self):
        bad = make_bundle("daily_lesson_split", 1, 1, text={"theme": "different"})
        with self.assertRaises(LocalError) as ctx:
            self.sync([bad])
        self.assertEqual(ctx.exception.code, "PROMPT_BUNDLE_CONFLICT")
        # The seeded bundle and the personal head are unchanged.
        self.assertEqual(
            query_scalar(
                self.db,
                "SELECT bundle_hash FROM local_prompt_bundles "
                "WHERE task_type='daily_lesson_split' AND contract_version=1 "
                "AND default_revision=1",
            ),
            _bundle_at("daily_lesson_split", 1, 1)["bundle_hash"],
        )
        self.assertEqual(self.revision_of("daily_lesson_split"), 1)


class PromptReceiptTests(PromptCase):
    def _valid_guidance(self):
        return dict(_task_bundle("daily_lesson_split")["guidance_defaults_json"])

    def test_success_receipt_priority_over_stale_expected(self):
        rid = str(uuid.uuid4())
        guidance = self._valid_guidance()
        guidance["theme"] = "receipt"
        first = self.edit(
            "daily_lesson_split", guidance, expected=1, contract=1, request_id=rid
        )
        self.assertEqual(first["personal_revision"], 2)
        # Same request id again with a now-stale expected revision replays.
        replay = self.edit(
            "daily_lesson_split", guidance, expected=1, contract=1, request_id=rid
        )
        self.assertEqual(replay["personal_revision"], 2)
        # The receipt is globally readable.
        status, body = self.http_client().get(f"/api/local/ai/operations/{rid}")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["operation_kind"], "ai_prompt_edit")

    def test_different_body_same_request_id_conflict(self):
        rid = str(uuid.uuid4())
        guidance = self._valid_guidance()
        guidance["theme"] = "one"
        self.edit(
            "daily_lesson_split", guidance, expected=1, contract=1, request_id=rid
        )
        other = self._valid_guidance()
        other["theme"] = "two"
        with self.assertRaises(LocalError) as ctx:
            self.edit(
                "daily_lesson_split", other, expected=2, contract=1, request_id=rid
            )
        self.assertEqual(ctx.exception.code, "AI_REQUEST_CONFLICT")

    def test_cross_domain_same_request_id_conflict(self):
        # An AI-config receipt exists for the id; a prompt op must 409.
        rid = str(uuid.uuid4())
        from app.local import ai_config_service

        session = self.session()
        try:
            ai_config_service.patch_config(
                session,
                expected_ai_config_version=0,
                base_url="https://api.example.com/v1",
                model="m",
                secret=None,
                secret_provided=False,
                request_id=rid,
                credential_root=self.credential_root,
            )
        finally:
            session.close()
        with self.assertRaises(LocalError) as ctx:
            self.edit(
                "daily_lesson_split", self._valid_guidance(), expected=1, contract=1,
                request_id=rid,
            )
        self.assertEqual(ctx.exception.code, "AI_REQUEST_CONFLICT")

    def test_commit_failure_rolls_back_without_half_version(self):
        guidance = self._valid_guidance()
        guidance["theme"] = "should not commit"
        before_versions = query_scalar(
            self.db,
            "SELECT count(*) FROM local_personal_prompt_versions "
            "WHERE task_type='daily_lesson_split'",
        )
        with mock.patch.object(
            prompt_service, "_store_receipt", side_effect=LocalStorageError()
        ):
            with self.assertRaises(LocalStorageError):
                self.edit(
                    "daily_lesson_split", guidance, expected=1, contract=1
                )
        self.assertEqual(self.revision_of("daily_lesson_split"), 1)
        self.assertEqual(
            query_scalar(
                self.db,
                "SELECT count(*) FROM local_personal_prompt_versions "
                "WHERE task_type='daily_lesson_split'",
            ),
            before_versions,
        )


class PromptHttpTests(PromptCase):
    def setUp(self) -> None:
        super().setUp()
        self.client = self.start_server(self.runtime).client()

    def test_session_host_origin_and_no_store(self):
        status, body = self.client.get("/api/local/ai/prompts", token=None)
        self.assertEqual(status, 401, body)
        status, body = self.client.get("/api/local/ai/prompts", host="evil.example")
        self.assertEqual(status, 403, body)
        status, body = self.client.patch(
            "/api/local/ai/prompts/daily_lesson_split",
            {
                "request_id": str(uuid.uuid4()),
                "expected_personal_revision": 1,
                "contract_version": 1,
                "guidance": dict(_task_bundle("daily_lesson_split")["guidance_defaults_json"]),
            },
            origin="http://evil.example",
        )
        self.assertEqual(status, 403, body)
        status, body = self.client.get("/api/local/ai/prompts")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["items"][0]["task_type"], "daily_lesson_split")

    def test_extra_field_and_strict_int_rejected_over_http(self):
        status, body = self.client.patch(
            "/api/local/ai/prompts/daily_lesson_split",
            {
                "request_id": str(uuid.uuid4()),
                "expected_personal_revision": 1,
                "contract_version": 1,
                "guidance": dict(_task_bundle("daily_lesson_split")["guidance_defaults_json"]),
                "class_id": "x",
            },
        )
        self.assertEqual(status, 422, body)
        status, body = self.client.patch(
            "/api/local/ai/prompts/daily_lesson_split",
            {
                "request_id": str(uuid.uuid4()),
                "expected_personal_revision": True,
                "contract_version": 1,
                "guidance": dict(_task_bundle("daily_lesson_split")["guidance_defaults_json"]),
            },
        )
        self.assertEqual(status, 422, body)

    def test_sync_failure_blocks_ai_only(self):
        self.runtime.prompt_sync_error = "PROMPT_BUNDLE_CONFLICT"
        status, body = self.client.get("/api/local/ai/prompts")
        self.assertEqual(status, 503, body)
        # Manual read stays available.
        status, body = self.client.get("/api/local/context")
        self.assertEqual(status, 200, body)
        from tests.local.support import initialize_body

        status, body = self.client.post(
            "/api/daily-plans",
            {"plan_date": "2026-09-02"},
        )
        self.assertEqual(status, 201, body)


class FreshArchiveSyncTests(LocalTestCase):
    """R04: a refused package sync must not block fresh-archive initialization."""

    def _conflict_manifest(self):
        conflict = make_bundle(
            "daily_lesson_split", 1, 1, text={"process": "与登记包冲突的文字"}
        )
        r2 = make_bundle("daily_lesson_split", 1, 2, text={"theme": "r2 主题"})
        return (conflict, r2)

    def test_bad_pack_fresh_init_uses_registered_bundle_and_degrades_ai(self):
        with mock.patch.object(
            prompt_bundles, "PROMPT_BUNDLE_MANIFEST", self._conflict_manifest()
        ):
            runtime = self.make_runtime()
        self.assertEqual(runtime.prompt_sync_error, "PROMPT_BUNDLE_CONFLICT")
        client = self.start_server(runtime).client()
        status, body = client.post("/api/local/initialize", initialize_body())
        self.assertEqual(status, 201, body)
        # The first personal version references a *registered* bundle (frozen r1).
        row = query_rows(
            runtime.db_path,
            "SELECT contract_version, based_default_revision "
            "FROM local_personal_prompt_versions WHERE task_type='daily_lesson_split'",
        )[0]
        self.assertEqual(row["contract_version"], 1)
        self.assertEqual(row["based_default_revision"], 1)
        registered = query_scalar(
            runtime.db_path,
            "SELECT count(*) FROM local_prompt_bundles WHERE task_type='daily_lesson_split' "
            "AND contract_version=1 AND default_revision=1",
        )
        self.assertEqual(registered, 1)
        # Only AI prompts are blocked; manual paths stay usable.
        status, body = client.get("/api/local/ai/prompts")
        self.assertEqual(status, 503, body)
        status, body = client.get("/api/local/context")
        self.assertEqual(status, 200, body)
        status, body = client.post("/api/daily-plans", {"plan_date": "2026-09-02"})
        self.assertEqual(status, 201, body)

    def test_healthy_new_pack_uses_latest_registered_default_and_restart_keeps_revision(self):
        healthy = tuple(PROMPT_BUNDLE_MANIFEST)
        with mock.patch.object(prompt_bundles, "PROMPT_BUNDLE_MANIFEST", healthy):
            runtime = self.make_runtime()
            self.assertIsNone(runtime.prompt_sync_error)
            server = self.start_server(runtime)
            client = server.client()
            status, body = client.post("/api/local/initialize", initialize_body())
            self.assertEqual(status, 201, body)
            status, prompt = client.get("/api/local/ai/prompts/daily_lesson_split")
            self.assertEqual(status, 200, prompt)
            self.assertEqual(prompt["based_default_revision"], 2)
            self.assertEqual(prompt["latest_default_revision"], 2)
            self.assertEqual(
                prompt["guidance"]["theme"],
                _task_bundle("daily_lesson_split")["guidance_defaults_json"]["theme"],
            )
            before = prompt["personal_revision"]
            # Restart on the same data root (still the healthy package).
            server.stop()
            runtime.dispose()
            runtime2 = LocalRuntime(
                data_dir=runtime.data_dir, credential_root=self.credential_root
            )
            runtime2.prepare()
            self.addCleanup(runtime2.dispose)
            self.assertIsNone(runtime2.prompt_sync_error)
            session = runtime2.session()
            try:
                after = prompt_service.get_prompt(
                    session, task_type="daily_lesson_split"
                )
            finally:
                session.close()
            self.assertEqual(after["personal_revision"], before)


if __name__ == "__main__":
    unittest.main()