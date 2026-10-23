"""D2 W4 candidate read / preview / adoption service tests.

Real temp SQLite through ``LocalRuntime`` (package prompt-bundle sync runs).
Candidates are produced through the normal W3 chain
(``create_task`` -> ``claim_next`` -> ``commit_dispatch_mark`` ->
``finalize_success``), never by inserting candidate rows directly. Direct
``UPDATE``/``DELETE`` statements are fault injection and are marked as such.
"""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import unittest
import uuid
import zipfile
from datetime import date
from unittest import mock

from app.local import (
    ai_adoption,
    ai_candidates,
    ai_config_service,
    ai_task_service,
    daily_plan_service,
    export_service,
    profile_service,
)
from app.local.ai_provenance import BASELINE_KEY
from app.local.base import utc_now
from app.local.errors import (
    LocalAiContractObsolete,
    LocalAiNotFound,
    LocalAiPreviewExpired,
    LocalAiRequestConflict,
    LocalAiSourceChanged,
    LocalAiTargetChanged,
    LocalStorageError,
    LocalValidationError,
    LocalVersionConflict,
)
from app.local.models import (
    LocalPersonalPromptHead,
    LocalPersonalPromptVersion,
    LocalPromptBundle,
)
from app.local.normalize import normalize_initialization
from app.local.prompt_bundles import canonical_json
from tests.local.support import (
    LocalTestCase,
    execute_sql,
    initialize_body,
    query_rows,
    query_scalar,
)

SPLIT_CANDIDATE = {
    "group_activity": {
        "theme": "秋天的树叶",
        "objectives": "观察树叶",
        "preparation": "树叶若干",
        "key_points": "观察",
        "difficult_points": "比较",
        "process": "一、导入\n二、观察",
    }
}
ADAPT_CANDIDATE = {"process": "调整后的过程\n第二步：比较"}
OTHER_CANDIDATE = {
    "morning_games": [
        {
            "group_kind": "collective",
            "games": [{"name": "阳光体育"}],
            "shared_objectives": "共同目标",
            "focus_guidance": "重点指导",
        },
        {
            "group_kind": "free_choice",
            "games": [{"name": "积木搭建"}],
            "guidance_points": "指导要点",
        },
    ],
    "morning_talk": {"topic": "今日话题", "questions": "你想说什么？"},
    "post_group_games": [
        {"context_kind": "area", "games": [{"name": "区域游戏"}], "objectives": "目标"}
    ],
    "afternoon_outdoor": {
        "games": [{"name": "户外追逐"}],
        "area": "操场",
        "observation_focus": "观察重点",
    },
}

DEFAULT_ADOPTED = {
    "group_activity": {"process": "一、导入\n二、观察"},
    "reflection": "反思",
}
DEFAULT_RAW = "原始教案正文"


def corrupt_sql(db, sql: str, params: tuple = ()) -> None:
    """Fault injection: write directly with FK enforcement disabled."""
    connection = sqlite3.connect(str(db))
    try:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute(sql, params)
        connection.commit()
    finally:
        connection.close()


class W4Case(LocalTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.runtime = self.make_runtime()
        self.runtime.launch_id = str(uuid.uuid4())
        self.db = self.runtime.db_path
        self.session = self.runtime.session()
        self.addCleanup(self.session.close)
        profile_service.initialize(
            self.session, normalize_initialization(**initialize_body())
        )
        self.session.commit()
        ai_adoption.reset_tokens()

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

    def make_plan(
        self, plan_date=date(2026, 9, 2), raw=DEFAULT_RAW, adopted=None
    ) -> dict:
        payload, _created = daily_plan_service.create_or_open(
            self.session,
            plan_date=plan_date,
            raw_lesson_plan=raw,
            adopted_content=adopted or dict(DEFAULT_ADOPTED),
        )
        return payload

    def content_version(self, plan_id: str) -> int:
        return int(
            query_scalar(
                self.db,
                "SELECT current_content_version FROM local_daily_plans WHERE id = ?",
                (plan_id,),
            )
        )

    def generate(self, plan_id, task_type, candidate, grade="middle") -> str:
        result, _created = ai_task_service.create_task(
            self.session,
            plan_id=plan_id,
            task_type=task_type,
            expected_content_version=self.content_version(plan_id),
            target_grade=grade,
            request_id=str(uuid.uuid4()),
        )
        claim = ai_task_service.claim_next(self.runtime, now=utc_now(), started_ticks=1)
        self.assertIsNotNone(claim, result)
        self.assertTrue(ai_task_service.commit_dispatch_mark(self.session, claim, utc_now()))
        ok = ai_task_service.finalize_success(
            self.session,
            claim,
            {
                "kind": "success",
                "candidate_text": json.dumps(candidate, ensure_ascii=False),
            },
            utc_now(),
        )
        self.assertTrue(ok)
        candidate_id = query_scalar(
            self.db,
            "SELECT id FROM local_ai_candidates WHERE execution_id = ?",
            (claim.execution_id,),
        )
        self.assertIsNotNone(candidate_id)
        return candidate_id

    def save_content(self, plan_id, expected_version, adopted, raw=None) -> dict:
        return daily_plan_service.save(
            self.session,
            plan_id=plan_id,
            expected_content_version=expected_version,
            raw_lesson_plan=raw if raw is not None else DEFAULT_RAW,
            adopted_content=adopted,
        )

    def preview(self, plan_id, candidate_id, selected, edited, **kwargs) -> dict:
        self.session.expire_all()
        return ai_adoption.preview_adoption(
            self.session,
            plan_id=plan_id,
            candidate_id=candidate_id,
            expected_content_version=self.content_version(plan_id),
            selected_targets=selected,
            edited_candidate=edited,
            **kwargs,
        )

    def adopt(self, plan_id, candidate_id, token, *, request_id=None, expected=None, **kwargs) -> dict:
        self.session.expire_all()
        return ai_adoption.adopt(
            self.session,
            plan_id=plan_id,
            candidate_id=candidate_id,
            expected_content_version=(
                expected if expected is not None else self.content_version(plan_id)
            ),
            preview_token=token,
            request_id=request_id or str(uuid.uuid4()),
            **kwargs,
        )

    def plan_content(self, plan_id: str) -> dict:
        payload = daily_plan_service.get_plan(self.session, plan_id=plan_id)
        return payload["content"]


# ---------------------------------------------------------------------------
# Candidate read
# ---------------------------------------------------------------------------


class CandidateReadTests(W4Case):
    def setUp(self) -> None:
        super().setUp()
        self.configure_ai()
        self.plan = self.make_plan()

    def test_list_excludes_material_paginates_and_foreign_plan_404(self):
        self.generate(self.plan["id"], "daily_lesson_split", SPLIT_CANDIDATE)
        self.generate(self.plan["id"], "daily_process_adapt", ADAPT_CANDIDATE)
        self.generate(self.plan["id"], "daily_other_activities", OTHER_CANDIDATE)

        page = ai_candidates.list_candidates(self.session, plan_id=self.plan["id"], limit=2)
        self.assertEqual(len(page["items"]), 2)
        self.assertIsNotNone(page["next_cursor"])
        for item in page["items"]:
            self.assertNotIn("raw_candidate", item)
            self.assertNotIn("source", item)
            self.assertIn(item["adoption_state"], ("eligible", "source_changed", "contract_obsolete"))
            self.assertTrue(item["available_targets"])
        page2 = ai_candidates.list_candidates(
            self.session, plan_id=self.plan["id"], limit=2, cursor=page["next_cursor"]
        )
        self.assertEqual(len(page2["items"]), 1)
        self.assertIsNone(page2["next_cursor"])

        # A candidate requested through a foreign plan is a plain 404.
        other_plan = self.make_plan(plan_date=date(2026, 9, 3))
        candidate_id = page["items"][0]["id"]
        with self.assertRaises(LocalAiNotFound):
            ai_candidates.get_candidate(
                self.session, plan_id=other_plan["id"], candidate_id=candidate_id
            )

        with self.assertRaises(LocalValidationError):
            ai_candidates.list_candidates(self.session, plan_id=self.plan["id"], limit=0)
        with self.assertRaises(LocalValidationError):
            ai_candidates.list_candidates(self.session, plan_id=self.plan["id"], limit=101)

    def test_detail_includes_real_source_and_excerpt(self):
        candidate_id = self.generate(
            self.plan["id"], "daily_lesson_split", SPLIT_CANDIDATE
        )
        detail = ai_candidates.get_candidate(
            self.session, plan_id=self.plan["id"], candidate_id=candidate_id
        )
        self.assertEqual(detail["raw_candidate"], SPLIT_CANDIDATE)
        self.assertEqual(detail["adoption_state"], "eligible")
        self.assertEqual(detail["available_targets"], ["group_activity"])
        source = detail["source"]
        self.assertEqual(source["content_version"], 1)
        self.assertEqual(source["target_grade"], "middle")
        self.assertTrue(source["dependency_hash"])
        self.assertEqual(source["dependencies"]["raw_lesson_plan"], DEFAULT_RAW)
        self.assertEqual(source["source_excerpt"]["raw_lesson_plan"], DEFAULT_RAW)

    def test_other_source_excerpt_includes_game_config_and_snapshot(self):
        candidate_id = self.generate(
            self.plan["id"], "daily_other_activities", OTHER_CANDIDATE
        )
        detail = ai_candidates.get_candidate(
            self.session, plan_id=self.plan["id"], candidate_id=candidate_id
        )
        excerpt = detail["source"]["source_excerpt"]
        # The actual activity + game-configuration material must be checkable.
        self.assertIn("game_config", excerpt)
        self.assertIn("daily_plan_snapshot", excerpt)
        self.assertIn("calendar_context", excerpt)
        self.assertIn("game_revision_id", excerpt)
        self.assertEqual(
            set(detail["available_targets"]),
            {"morning_games", "morning_talk", "post_group_games", "afternoon_outdoor"},
        )
        # A list item still never carries the material.
        listed = ai_candidates.list_candidates(self.session, plan_id=self.plan["id"])
        self.assertNotIn("source", listed["items"][0])


# ---------------------------------------------------------------------------
# Preview validation
# ---------------------------------------------------------------------------


class PreviewValidationTests(W4Case):
    def setUp(self) -> None:
        super().setUp()
        self.configure_ai()
        self.plan = self.make_plan()
        self.candidate_id = self.generate(
            self.plan["id"], "daily_lesson_split", SPLIT_CANDIDATE
        )

    def test_preview_is_read_only(self):
        before = {
            table: query_scalar(self.db, f"SELECT count(*) FROM {table}")
            for table in (
                "local_daily_plan_contents",
                "local_daily_plan_ai_provenance",
                "local_ai_operations",
                "local_operation_records",
            )
        }
        preview = self.preview(
            self.plan["id"], self.candidate_id, ["group_activity"], SPLIT_CANDIDATE
        )
        self.assertTrue(preview["preview_token"])
        self.assertEqual(preview["content_version"], 1)
        self.assertEqual(preview["before"], {"group_activity": {"process": "一、导入\n二、观察"}})
        self.assertEqual(preview["after"], {"group_activity": SPLIT_CANDIDATE["group_activity"]})
        after = {
            table: query_scalar(self.db, f"SELECT count(*) FROM {table}")
            for table in before
        }
        self.assertEqual(before, after)
        self.assertEqual(self.content_version(self.plan["id"]), 1)

    def test_preview_strict_edit_schema(self):
        base = self.plan["id"]
        bad_edits = [
            {**SPLIT_CANDIDATE, "unknown": 1},
            {"group_activity": {**SPLIT_CANDIDATE["group_activity"], "theme": None}},
            {
                "group_activity": {
                    **SPLIT_CANDIDATE["group_activity"],
                    "group_id": "forged",
                }
            },
            {
                "group_activity": {**SPLIT_CANDIDATE["group_activity"], "reflection": "x"}
            },
            {"group_activity": {"theme": "缺少其它字段"}},
            "not-an-object",
        ]
        for edited in bad_edits:
            with self.subTest(edited=str(edited)[:40]):
                with self.assertRaises(LocalValidationError):
                    self.preview(base, self.candidate_id, ["group_activity"], edited)

    def test_preview_target_rules(self):
        base = self.plan["id"]
        for selected in ([], ["group_activity", "group_activity"], ["other_board"], [1], "group_activity"):
            with self.subTest(selected=selected):
                with self.assertRaises(LocalValidationError):
                    self.preview(base, self.candidate_id, selected, SPLIT_CANDIDATE)

    def test_preview_old_expected_version_conflicts(self):
        with self.assertRaises(LocalVersionConflict):
            ai_adoption.preview_adoption(
                self.session,
                plan_id=self.plan["id"],
                candidate_id=self.candidate_id,
                expected_content_version=5,
                selected_targets=["group_activity"],
                edited_candidate=SPLIT_CANDIDATE,
            )

    def test_token_expiry_is_enforced(self):
        t0 = 1_000_000.0
        with mock.patch.object(ai_adoption, "_now", return_value=t0):
            preview = self.preview(
                self.plan["id"], self.candidate_id, ["group_activity"], SPLIT_CANDIDATE
            )
        with mock.patch.object(ai_adoption, "_now", return_value=t0 + 601):
            with self.assertRaises(LocalAiPreviewExpired):
                self.adopt(self.plan["id"], self.candidate_id, preview["preview_token"])

    def test_token_store_is_bounded(self):
        token0 = self.preview(
            self.plan["id"], self.candidate_id, ["group_activity"], SPLIT_CANDIDATE
        )["preview_token"]
        for _ in range(ai_adoption.MAX_TOKENS):
            self.preview(
                self.plan["id"], self.candidate_id, ["group_activity"], SPLIT_CANDIDATE
            )
        # The oldest token was evicted and needs a fresh preview.
        with self.assertRaises(LocalAiPreviewExpired):
            self.adopt(self.plan["id"], self.candidate_id, token0)


# ---------------------------------------------------------------------------
# Adoption flow
# ---------------------------------------------------------------------------


class AdoptFlowTests(W4Case):
    def setUp(self) -> None:
        super().setUp()
        self.configure_ai()
        self.plan = self.make_plan()

    def test_split_adopt_is_atomic(self):
        candidate_id = self.generate(
            self.plan["id"], "daily_lesson_split", SPLIT_CANDIDATE
        )
        preview = self.preview(
            self.plan["id"], candidate_id, ["group_activity"], SPLIT_CANDIDATE
        )
        result = self.adopt(self.plan["id"], candidate_id, preview["preview_token"])
        self.assertTrue(result["changed"])
        self.assertEqual(result["content_version"], 2)
        self.assertEqual(result["candidate_id"], candidate_id)

        content = self.plan_content(self.plan["id"])
        self.assertEqual(content["version"], 2)
        self.assertEqual(
            content["split_baseline"],
            {BASELINE_KEY: SPLIT_CANDIDATE["group_activity"]["process"]},
        )
        self.assertEqual(
            content["adopted_content"]["group_activity"], SPLIT_CANDIDATE["group_activity"]
        )
        provenance = query_rows(
            self.db,
            "SELECT baseline_candidate_id, adopted_candidate_id, selected_targets_json "
            "FROM local_daily_plan_ai_provenance WHERE content_id = ?",
            (content["id"],),
        )[0]
        self.assertEqual(provenance["baseline_candidate_id"], candidate_id)
        self.assertEqual(provenance["adopted_candidate_id"], candidate_id)
        targets = (
            provenance["selected_targets_json"]
            if isinstance(provenance["selected_targets_json"], dict)
            else json.loads(provenance["selected_targets_json"])
        )
        self.assertIn("group_activity", targets)
        self.assertEqual(
            query_scalar(
                self.db,
                "SELECT count(*) FROM local_operation_records WHERE action = 'adopt_ai_candidate'",
            ),
            1,
        )
        self.assertEqual(
            query_scalar(
                self.db,
                "SELECT count(*) FROM local_ai_operations WHERE operation_kind = 'ai_candidate_adopt'",
            ),
            1,
        )

    def test_baseline_is_raw_model_process_not_teacher_edit(self):
        candidate_id = self.generate(
            self.plan["id"], "daily_lesson_split", SPLIT_CANDIDATE
        )
        edited = json.loads(json.dumps(SPLIT_CANDIDATE))
        edited["group_activity"]["process"] = "教师预览改后的过程"
        preview = self.preview(self.plan["id"], candidate_id, ["group_activity"], edited)
        self.adopt(self.plan["id"], candidate_id, preview["preview_token"])
        content = self.plan_content(self.plan["id"])
        self.assertEqual(content["adopted_content"]["group_activity"]["process"], "教师预览改后的过程")
        self.assertEqual(
            content["split_baseline"],
            {BASELINE_KEY: SPLIT_CANDIDATE["group_activity"]["process"]},
        )

    def test_adapt_replaces_only_process_and_inherits_baseline(self):
        split_id = self.generate(self.plan["id"], "daily_lesson_split", SPLIT_CANDIDATE)
        preview = self.preview(self.plan["id"], split_id, ["group_activity"], SPLIT_CANDIDATE)
        self.adopt(self.plan["id"], split_id, preview["preview_token"])
        baseline = self.plan_content(self.plan["id"])["split_baseline"]

        adapt_id = self.generate(self.plan["id"], "daily_process_adapt", ADAPT_CANDIDATE)
        preview2 = self.preview(self.plan["id"], adapt_id, ["group_activity.process"], ADAPT_CANDIDATE)
        self.adopt(self.plan["id"], adapt_id, preview2["preview_token"])
        content = self.plan_content(self.plan["id"])
        self.assertEqual(content["version"], 3)
        self.assertEqual(content["adopted_content"]["group_activity"]["process"], ADAPT_CANDIDATE["process"])
        # Theme + objectives are untouched; the baseline + its source identity stay.
        self.assertEqual(content["adopted_content"]["group_activity"]["theme"], "秋天的树叶")
        self.assertEqual(content["split_baseline"], baseline)
        provenance = query_rows(
            self.db,
            "SELECT baseline_candidate_id, adopted_candidate_id FROM local_daily_plan_ai_provenance WHERE content_id = ?",
            (content["id"],),
        )[0]
        self.assertEqual(provenance["baseline_candidate_id"], split_id)
        self.assertEqual(provenance["adopted_candidate_id"], adapt_id)

    def test_other_activities_replaces_selected_boards_only(self):
        candidate_id = self.generate(
            self.plan["id"], "daily_other_activities", OTHER_CANDIDATE
        )
        preview = self.preview(
            self.plan["id"], candidate_id, ["morning_games", "morning_talk"], OTHER_CANDIDATE
        )
        result = self.adopt(self.plan["id"], candidate_id, preview["preview_token"])
        self.assertTrue(result["changed"])
        self.assertEqual(set(result["selected_targets"]), {"morning_games", "morning_talk"})
        content = self.plan_content(self.plan["id"])
        adopted = content["adopted_content"]
        # Selected boards replaced (with server ids), unselected boards kept.
        self.assertEqual(len(adopted["morning_games"]), 2)
        for group in adopted["morning_games"]:
            self.assertTrue(group["group_id"])
            for game in group["games"]:
                self.assertTrue(game["game_id"])
        self.assertEqual(adopted["morning_talk"]["topic"], "今日话题")
        self.assertNotIn("post_group_games", adopted)
        self.assertEqual(adopted["reflection"], "反思")

    def test_other_activities_numbered_candidate_does_not_touch_unselected_boards(self):
        candidate = json.loads(json.dumps(OTHER_CANDIDATE))
        numbered = "1. 问题一\n2. 问题二\n3. 问题三"
        candidate["morning_talk"]["questions"] = numbered
        candidate_id = self.generate(
            self.plan["id"], "daily_other_activities", candidate
        )
        preview = self.preview(
            self.plan["id"], candidate_id, ["morning_talk"], candidate
        )
        result = self.adopt(self.plan["id"], candidate_id, preview["preview_token"])
        self.assertTrue(result["changed"])
        self.assertEqual(set(result["selected_targets"]), {"morning_talk"})
        content = self.plan_content(self.plan["id"])
        adopted = content["adopted_content"]
        self.assertEqual(adopted["morning_talk"]["topic"], "今日话题")
        self.assertEqual(adopted["morning_talk"]["questions"], numbered)
        self.assertIn("\n", adopted["morning_talk"]["questions"])
        self.assertNotIn("morning_games", adopted)
        self.assertNotIn("post_group_games", adopted)
        self.assertNotIn("afternoon_outdoor", adopted)
        self.assertEqual(adopted["reflection"], "反思")

    def test_no_semantic_change_writes_no_new_version(self):
        # Put the candidate's morning talk into the content *first*, so the
        # candidate's input already snapshots it.
        self.save_content(
            self.plan["id"],
            1,
            {
                "group_activity": {"process": "一、导入\n二、观察"},
                "morning_talk": {"topic": "今日话题", "questions": "你想说什么？"},
                "reflection": "反思",
            },
        )
        candidate_id = self.generate(
            self.plan["id"], "daily_other_activities", OTHER_CANDIDATE
        )
        preview = self.preview(
            self.plan["id"], candidate_id, ["morning_talk"], OTHER_CANDIDATE
        )
        result = self.adopt(
            self.plan["id"], candidate_id, preview["preview_token"]
        )
        self.assertFalse(result["changed"])
        self.assertEqual(result["content_version"], 2)
        self.assertEqual(self.content_version(self.plan["id"]), 2)
        self.assertEqual(
            query_scalar(
                self.db,
                "SELECT count(*) FROM local_ai_operations WHERE operation_kind = 'ai_candidate_adopt'",
            ),
            1,
        )

    def test_receipt_replay_after_token_consumed_and_restart(self):
        candidate_id = self.generate(
            self.plan["id"], "daily_lesson_split", SPLIT_CANDIDATE
        )
        preview = self.preview(
            self.plan["id"], candidate_id, ["group_activity"], SPLIT_CANDIDATE
        )
        rid = str(uuid.uuid4())
        first = self.adopt(
            self.plan["id"], candidate_id, preview["preview_token"], request_id=rid
        )
        # Same key + same body (incl. the original expected version) replays the
        # committed result even though the token has been consumed.
        replay = ai_adoption.adopt(
            self.session,
            plan_id=self.plan["id"],
            candidate_id=candidate_id,
            expected_content_version=1,
            preview_token=preview["preview_token"],
            request_id=rid,
        )
        self.assertEqual(replay, first)
        self.assertEqual(self.content_version(self.plan["id"]), 2)

        # A cold restart: the in-memory token is gone but the receipt persists.
        self.session.close()
        self.runtime.dispose()
        runtime2 = self.make_runtime()
        runtime2.launch_id = str(uuid.uuid4())
        session2 = runtime2.session()
        self.addCleanup(session2.close)
        ai_task_service.recover_on_start(session2, now=utc_now())
        session2.expire_all()
        restarted = ai_adoption.adopt(
            session2,
            plan_id=self.plan["id"],
            candidate_id=candidate_id,
            expected_content_version=1,
            preview_token=preview["preview_token"],
            request_id=rid,
        )
        self.assertEqual(restarted, first)

    def test_same_key_different_token_conflicts(self):
        candidate_id = self.generate(
            self.plan["id"], "daily_lesson_split", SPLIT_CANDIDATE
        )
        token_a = self.preview(
            self.plan["id"], candidate_id, ["group_activity"], SPLIT_CANDIDATE
        )["preview_token"]
        edited = json.loads(json.dumps(SPLIT_CANDIDATE))
        edited["group_activity"]["theme"] = "另一编辑"
        token_b = self.preview(
            self.plan["id"], candidate_id, ["group_activity"], edited
        )["preview_token"]
        rid = str(uuid.uuid4())
        self.adopt(self.plan["id"], candidate_id, token_a, request_id=rid)
        with self.assertRaises(LocalAiRequestConflict):
            self.adopt(self.plan["id"], candidate_id, token_b, request_id=rid)
        # No second version from the conflicting request.
        self.assertEqual(self.content_version(self.plan["id"]), 2)

    def test_second_token_rejected_after_first_success(self):
        """Sequential service calls: only the first token is adopted.

        The real threaded/concurrent HTTP interleaving is covered in
        ``test_d2_w4_api``.
        """
        candidate_id = self.generate(
            self.plan["id"], "daily_lesson_split", SPLIT_CANDIDATE
        )
        token_a = self.preview(
            self.plan["id"], candidate_id, ["group_activity"], SPLIT_CANDIDATE
        )["preview_token"]
        token_b = self.preview(
            self.plan["id"], candidate_id, ["group_activity"], SPLIT_CANDIDATE
        )["preview_token"]
        self.adopt(self.plan["id"], candidate_id, token_a, request_id=str(uuid.uuid4()))
        # The second preview was bound to the same (now stale) version and its
        # target hash is stale too: per R06 the target change wins over the
        # version conflict, and nothing is written.
        with self.assertRaises(LocalAiTargetChanged):
            self.adopt(
                self.plan["id"],
                candidate_id,
                token_b,
                request_id=str(uuid.uuid4()),
                expected=1,
            )
        self.assertEqual(self.content_version(self.plan["id"]), 2)
        self.assertEqual(
            query_scalar(self.db, "SELECT count(*) FROM local_daily_plan_contents"), 2
        )
        self.assertEqual(
            query_scalar(
                self.db,
                "SELECT count(*) FROM local_ai_operations WHERE operation_kind = 'ai_candidate_adopt'",
            ),
            1,
        )

    def test_mid_transaction_failure_rolls_back_then_retry(self):
        candidate_id = self.generate(
            self.plan["id"], "daily_lesson_split", SPLIT_CANDIDATE
        )
        preview = self.preview(
            self.plan["id"], candidate_id, ["group_activity"], SPLIT_CANDIDATE
        )
        token = preview["preview_token"]
        rid = str(uuid.uuid4())
        with mock.patch.object(
            ai_adoption, "_record_operation", side_effect=RuntimeError("db down")
        ):
            with self.assertRaises(RuntimeError):
                self.adopt(self.plan["id"], candidate_id, token, request_id=rid)
        # Nothing partial survives: no new version, provenance, receipt or audit.
        self.assertEqual(self.content_version(self.plan["id"]), 1)
        self.assertEqual(
            query_scalar(self.db, "SELECT count(*) FROM local_daily_plan_contents"), 1
        )
        self.assertEqual(
            query_scalar(self.db, "SELECT count(*) FROM local_daily_plan_ai_provenance"), 1
        )
        self.assertEqual(
            query_scalar(self.db, "SELECT count(*) FROM local_daily_plan_ai_provenance WHERE adopted_candidate_id IS NOT NULL"),
            0,
        )
        self.assertEqual(
            query_scalar(
                self.db,
                "SELECT count(*) FROM local_ai_operations WHERE operation_kind = 'ai_candidate_adopt'",
            ),
            0,
        )
        # The token was not consumed by the failed attempt; the same key retries.
        result = self.adopt(self.plan["id"], candidate_id, token, request_id=rid)
        self.assertTrue(result["changed"])
        self.assertEqual(self.content_version(self.plan["id"]), 2)

    def test_commit_boundary_failure_rolls_back_everything(self):
        """Fault at the real `Session.commit`, after every row is flushed."""
        candidate_id = self.generate(
            self.plan["id"], "daily_lesson_split", SPLIT_CANDIDATE
        )
        preview = self.preview(
            self.plan["id"], candidate_id, ["group_activity"], SPLIT_CANDIDATE
        )
        token = preview["preview_token"]
        rid = str(uuid.uuid4())
        with mock.patch.object(
            self.session, "commit", side_effect=RuntimeError("commit failed")
        ):
            with self.assertRaises(RuntimeError):
                self.adopt(self.plan["id"], candidate_id, token, request_id=rid)
        # Content, provenance, audit and receipt all rolled back; the plan
        # pointer and version are untouched.
        self.assertEqual(self.content_version(self.plan["id"]), 1)
        self.assertEqual(
            query_scalar(self.db, "SELECT count(*) FROM local_daily_plan_contents"), 1
        )
        self.assertEqual(
            query_scalar(self.db, "SELECT count(*) FROM local_daily_plan_ai_provenance"), 1
        )
        self.assertEqual(
            query_scalar(
                self.db,
                "SELECT count(*) FROM local_operation_records WHERE action = 'adopt_ai_candidate'",
            ),
            0,
        )
        self.assertEqual(
            query_scalar(
                self.db,
                "SELECT count(*) FROM local_ai_operations WHERE operation_kind = 'ai_candidate_adopt'",
            ),
            0,
        )
        pointer = query_rows(
            self.db,
            "SELECT current_content_id, current_content_version FROM local_daily_plans WHERE id = ?",
            (self.plan["id"],),
        )[0]
        self.assertEqual(pointer["current_content_version"], 1)
        self.assertEqual(pointer["current_content_id"], self.plan["current_content_id"])
        # The token survives and the same key retries to a full commit.
        result = self.adopt(self.plan["id"], candidate_id, token, request_id=rid)
        self.assertTrue(result["changed"])
        self.assertEqual(self.content_version(self.plan["id"]), 2)
        self.assertEqual(
            query_scalar(
                self.db,
                "SELECT count(*) FROM local_ai_operations WHERE operation_kind = 'ai_candidate_adopt'",
            ),
            1,
        )

    def test_old_contract_candidate_readable_but_not_adoptable(self):
        candidate_id = self.generate(
            self.plan["id"], "daily_lesson_split", SPLIT_CANDIDATE
        )
        # Fault injection: point the task's required contract at a v2 bundle.
        row = query_rows(
            self.db,
            "SELECT input_schema_json, output_schema_json, guidance_defaults_json "
            "FROM local_prompt_bundles WHERE task_type = 'daily_lesson_split' AND contract_version = 1",
        )[0]

        def _as_obj(value):
            return json.loads(value) if isinstance(value, str) else value

        bundle = LocalPromptBundle(
            task_type="daily_lesson_split",
            contract_version=2,
            default_revision=1,
            input_schema_json=_as_obj(row["input_schema_json"]),
            output_schema_json=_as_obj(row["output_schema_json"]),
            guidance_defaults_json=_as_obj(row["guidance_defaults_json"]),
            bundle_hash="c" * 64,
            created_at=utc_now(),
        )
        self.session.add(bundle)
        self.session.flush()
        profile_id = query_scalar(self.db, "SELECT id FROM local_profile")
        head = self.session.get(LocalPersonalPromptHead, (profile_id, "daily_lesson_split"))
        self.session.add(
            LocalPersonalPromptVersion(
                profile_id=profile_id,
                task_type="daily_lesson_split",
                revision=head.current_revision + 1,
                contract_version=2,
                based_default_revision=1,
                guidance_json=dict(bundle.guidance_defaults_json),
                action="adapt",
                created_at=utc_now(),
            )
        )
        self.session.flush()
        head.current_revision += 1
        head.required_contract_version = 2
        head.latest_default_revision = 1
        self.session.commit()
        self.session.expire_all()

        detail = ai_candidates.get_candidate(
            self.session, plan_id=self.plan["id"], candidate_id=candidate_id
        )
        self.assertEqual(detail["adoption_state"], "contract_obsolete")
        self.assertEqual(detail["raw_candidate"], SPLIT_CANDIDATE)
        with self.assertRaises(LocalAiContractObsolete):
            self.preview(self.plan["id"], candidate_id, ["group_activity"], SPLIT_CANDIDATE)


# ---------------------------------------------------------------------------
# Source / target / version classification (R06)
# ---------------------------------------------------------------------------


class SourceTargetVersionTests(W4Case):
    def setUp(self) -> None:
        super().setUp()
        self.configure_ai()
        self.plan = self.make_plan()

    def _split_token(self):
        candidate_id = self.generate(
            self.plan["id"], "daily_lesson_split", SPLIT_CANDIDATE
        )
        preview = self.preview(
            self.plan["id"], candidate_id, ["group_activity"], SPLIT_CANDIDATE
        )
        return candidate_id, preview["preview_token"]

    def test_unrelated_change_is_version_conflict(self):
        candidate_id, token = self._split_token()
        self.save_content(
            self.plan["id"],
            1,
            {
                "group_activity": {"process": "一、导入\n二、观察"},
                "reflection": "改写的反思",
            },
        )
        with self.assertRaises(LocalVersionConflict):
            self.adopt(self.plan["id"], candidate_id, token, expected=1)

    def test_target_change_is_target_error(self):
        candidate_id, token = self._split_token()
        self.save_content(
            self.plan["id"],
            1,
            {
                "group_activity": {
                    "process": "一、导入\n二、观察",
                    "theme": "教师另写主题",
                },
                "reflection": "反思",
            },
        )
        with self.assertRaises(LocalAiTargetChanged):
            self.adopt(self.plan["id"], candidate_id, token, expected=1)

    def test_source_change_is_source_error(self):
        candidate_id, token = self._split_token()
        self.save_content(
            self.plan["id"],
            1,
            {
                "group_activity": {"process": "一、导入\n二、观察"},
                "reflection": "反思",
            },
            raw="全新的原文",
        )
        with self.assertRaises(LocalAiSourceChanged) as ctx:
            self.adopt(self.plan["id"], candidate_id, token, expected=1)
        self.assertIn("raw_lesson_plan", ctx.exception.details["changed_fields"])

    def test_changed_expected_cannot_bypass_preview(self):
        candidate_id, token = self._split_token()
        self.save_content(
            self.plan["id"],
            1,
            {
                "group_activity": {"process": "一、导入\n二、观察"},
                "reflection": "改写的反思",
            },
        )
        # The token is bound to version 1; changing expected to 2 is refused.
        with self.assertRaises(LocalAiPreviewExpired):
            self.adopt(self.plan["id"], candidate_id, token, expected=2)
        self.assertEqual(self.content_version(self.plan["id"]), 2)

    def test_other_activity_overlapping_change_is_source_first(self):
        candidate_id = self.generate(
            self.plan["id"], "daily_other_activities", OTHER_CANDIDATE
        )
        preview = self.preview(
            self.plan["id"], candidate_id, ["morning_talk"], OTHER_CANDIDATE
        )
        # Change a selected board that is also part of the other-activities
        # dependency: the source change must win over the target change.
        self.save_content(
            self.plan["id"],
            1,
            {
                "group_activity": {"process": "一、导入\n二、观察"},
                "morning_talk": {"topic": "教师改过的话题", "questions": "问题"},
                "reflection": "反思",
            },
        )
        with self.assertRaises(LocalAiSourceChanged):
            self.adopt(self.plan["id"], candidate_id, preview["preview_token"], expected=1)


# ---------------------------------------------------------------------------
# Corrupt chain / baseline (R04)
# ---------------------------------------------------------------------------


class CorruptChainTests(W4Case):
    def setUp(self) -> None:
        super().setUp()
        self.configure_ai()
        self.plan = self.make_plan()

    def test_failed_execution_blocks_read_preview_adopt(self):
        candidate_id = self.generate(
            self.plan["id"], "daily_lesson_split", SPLIT_CANDIDATE
        )
        preview = self.preview(
            self.plan["id"], candidate_id, ["group_activity"], SPLIT_CANDIDATE
        )
        # Fault injection: the candidate's execution fails after the fact.
        execute_sql(
            self.db,
            "UPDATE local_ai_executions SET state = 'failed' WHERE id = "
            "(SELECT execution_id FROM local_ai_candidates WHERE id = ?)",
            (candidate_id,),
        )
        self.session.expire_all()
        with self.assertRaises(LocalStorageError):
            ai_candidates.get_candidate(
                self.session, plan_id=self.plan["id"], candidate_id=candidate_id
            )
        with self.assertRaises(LocalStorageError):
            ai_candidates.list_candidates(self.session, plan_id=self.plan["id"])
        with self.assertRaises(LocalStorageError):
            self.preview(self.plan["id"], candidate_id, ["group_activity"], SPLIT_CANDIDATE)
        with self.assertRaises(LocalStorageError):
            self.adopt(self.plan["id"], candidate_id, preview["preview_token"])
        # The plan itself is still fully readable and unchanged.
        self.assertEqual(self.content_version(self.plan["id"]), 1)

    def test_missing_input_is_storage_error(self):
        candidate_id = self.generate(
            self.plan["id"], "daily_lesson_split", SPLIT_CANDIDATE
        )
        input_id = query_scalar(
            self.db, "SELECT input_id FROM local_ai_candidates WHERE id = ?", (candidate_id,)
        )
        # Fault injection: drop the input snapshot with FK enforcement off.
        corrupt_sql(self.db, "DELETE FROM local_ai_executions WHERE input_id = ?", (input_id,))
        corrupt_sql(self.db, "DELETE FROM local_ai_inputs WHERE id = ?", (input_id,))
        self.session.expire_all()
        with self.assertRaises(LocalStorageError):
            ai_candidates.get_candidate(
                self.session, plan_id=self.plan["id"], candidate_id=candidate_id
            )

    def test_tampered_candidate_body_is_storage_error(self):
        candidate_id = self.generate(
            self.plan["id"], "daily_lesson_split", SPLIT_CANDIDATE
        )
        execute_sql(
            self.db,
            "UPDATE local_ai_candidates SET candidate_hash = ? WHERE id = ?",
            ("f" * 64, candidate_id),
        )
        self.session.expire_all()
        with self.assertRaises(LocalStorageError):
            ai_candidates.get_candidate(
                self.session, plan_id=self.plan["id"], candidate_id=candidate_id
            )

    def test_malformed_candidate_body_is_storage_error(self):
        candidate_id = self.generate(
            self.plan["id"], "daily_lesson_split", SPLIT_CANDIDATE
        )
        malformed = {"bogus": 1}
        digest = hashlib.sha256(canonical_json(malformed).encode("utf-8")).hexdigest()
        execute_sql(
            self.db,
            "UPDATE local_ai_candidates SET raw_candidate_json = ?, candidate_hash = ? WHERE id = ?",
            (canonical_json(malformed), digest, candidate_id),
        )
        self.session.expire_all()
        with self.assertRaises(LocalStorageError):
            ai_candidates.get_candidate(
                self.session, plan_id=self.plan["id"], candidate_id=candidate_id
            )

    def test_baseline_mismatch_and_missing_provenance_rejected(self):
        candidate_id = self.generate(
            self.plan["id"], "daily_lesson_split", SPLIT_CANDIDATE
        )
        preview = self.preview(
            self.plan["id"], candidate_id, ["group_activity"], SPLIT_CANDIDATE
        )
        self.adopt(self.plan["id"], candidate_id, preview["preview_token"])
        content = self.plan_content(self.plan["id"])
        # A baseline value that disagrees with the source candidate body.
        execute_sql(
            self.db,
            "UPDATE local_daily_plan_contents SET split_baseline = ? WHERE id = ?",
            (canonical_json({BASELINE_KEY: "被改过的基准"}), content["id"]),
        )
        self.session.expire_all()
        with self.assertRaises(LocalStorageError):
            daily_plan_service.get_plan(self.session, plan_id=self.plan["id"])
        # Restore a legal value but remove the provenance row: still refused.
        execute_sql(
            self.db,
            "UPDATE local_daily_plan_contents SET split_baseline = ? WHERE id = ?",
            (canonical_json({BASELINE_KEY: SPLIT_CANDIDATE["group_activity"]["process"]}), content["id"]),
        )
        execute_sql(
            self.db,
            "DELETE FROM local_daily_plan_ai_provenance WHERE content_id = ?",
            (content["id"],),
        )
        self.session.expire_all()
        with self.assertRaises(LocalStorageError):
            daily_plan_service.get_plan(self.session, plan_id=self.plan["id"])

    def test_non_json_candidate_column_is_storage_error(self):
        candidate_id = self.generate(
            self.plan["id"], "daily_lesson_split", SPLIT_CANDIDATE
        )
        preview = self.preview(
            self.plan["id"], candidate_id, ["group_activity"], SPLIT_CANDIDATE
        )
        # Fault injection: the JSON column holds text that is not JSON. This
        # fails while SQLAlchemy materialises the row, so it must still be a
        # 503 storage error (never an internal error).
        execute_sql(
            self.db,
            "UPDATE local_ai_candidates SET raw_candidate_json = 'not-json' WHERE id = ?",
            (candidate_id,),
        )
        self.session.expire_all()
        with self.assertRaises(LocalStorageError):
            ai_candidates.get_candidate(
                self.session, plan_id=self.plan["id"], candidate_id=candidate_id
            )
        with self.assertRaises(LocalStorageError):
            ai_candidates.list_candidates(self.session, plan_id=self.plan["id"])
        with self.assertRaises(LocalStorageError):
            self.preview(self.plan["id"], candidate_id, ["group_activity"], SPLIT_CANDIDATE)
        with self.assertRaises(LocalStorageError):
            self.adopt(self.plan["id"], candidate_id, preview["preview_token"])

    def test_foreign_corrupt_candidate_is_404(self):
        other = self.make_plan(plan_date=date(2026, 9, 3))
        foreign_id = self.generate(other["id"], "daily_lesson_split", SPLIT_CANDIDATE)
        execute_sql(
            self.db,
            "UPDATE local_ai_candidates SET raw_candidate_json = 'not-json' WHERE id = ?",
            (foreign_id,),
        )
        self.session.expire_all()
        with self.assertRaises(LocalAiNotFound):
            ai_candidates.get_candidate(
                self.session, plan_id=self.plan["id"], candidate_id=foreign_id
            )
        with self.assertRaises(LocalStorageError):
            ai_candidates.get_candidate(
                self.session, plan_id=other["id"], candidate_id=foreign_id
            )

    def test_same_text_different_source_identity(self):
        # Two split candidates with identical process text but distinct sources.
        first = self.generate(self.plan["id"], "daily_lesson_split", SPLIT_CANDIDATE)
        preview = self.preview(self.plan["id"], first, ["group_activity"], SPLIT_CANDIDATE)
        self.adopt(self.plan["id"], first, preview["preview_token"])
        # Point the baseline at a second, same-text candidate (still legal).
        second = self.generate(self.plan["id"], "daily_lesson_split", SPLIT_CANDIDATE)
        content = self.plan_content(self.plan["id"])
        execute_sql(
            self.db,
            "UPDATE local_daily_plan_ai_provenance SET baseline_candidate_id = ? WHERE content_id = ?",
            (second, content["id"]),
        )
        self.session.expire_all()
        payload = daily_plan_service.get_plan(self.session, plan_id=self.plan["id"])
        self.assertEqual(payload["content"]["split_baseline"][BASELINE_KEY], SPLIT_CANDIDATE["group_activity"]["process"])
        # A different identity is a different dependency for adapt.
        plan_row = None
        from app.local.models import LocalDailyPlan, LocalDailyPlanContent
        from app.local import ai_inputs

        plan_row = self.session.get(LocalDailyPlan, self.plan["id"])
        content_row = self.session.get(LocalDailyPlanContent, payload["content"]["id"])
        projected = ai_inputs.project_input(
            self.session,
            plan=plan_row,
            content=content_row,
            task_type="daily_process_adapt",
            target_grade="middle",
        )
        self.assertEqual(projected.dependencies["baseline_candidate_id"], second)
        self.assertNotEqual(projected.dependencies["baseline_candidate_id"], first)


# ---------------------------------------------------------------------------
# Save / restart / export chain
# ---------------------------------------------------------------------------


class PersistenceChainTests(W4Case):
    def setUp(self) -> None:
        super().setUp()
        self.configure_ai()
        self.plan = self.make_plan()

    def test_manual_save_and_restart_keep_baseline(self):
        candidate_id = self.generate(
            self.plan["id"], "daily_lesson_split", SPLIT_CANDIDATE
        )
        preview = self.preview(
            self.plan["id"], candidate_id, ["group_activity"], SPLIT_CANDIDATE
        )
        self.adopt(self.plan["id"], candidate_id, preview["preview_token"])
        baseline = self.plan_content(self.plan["id"])["split_baseline"]
        # A later manual edit keeps the baseline and writes its own provenance.
        self.save_content(
            self.plan["id"],
            2,
            {
                "group_activity": {
                    **SPLIT_CANDIDATE["group_activity"],
                    "process": "教师手改后的过程",
                },
                "reflection": "反思",
            },
        )
        content = self.plan_content(self.plan["id"])
        self.assertEqual(content["split_baseline"], baseline)
        self.assertEqual(content["adopted_content"]["group_activity"]["process"], "教师手改后的过程")
        provenance = query_rows(
            self.db,
            "SELECT baseline_candidate_id, adopted_candidate_id FROM local_daily_plan_ai_provenance WHERE content_id = ?",
            (content["id"],),
        )[0]
        self.assertEqual(provenance["baseline_candidate_id"], candidate_id)
        self.assertIsNone(provenance["adopted_candidate_id"])

        # Cold restart still reads the same baseline.
        self.session.close()
        self.runtime.dispose()
        runtime2 = self.make_runtime()
        runtime2.launch_id = str(uuid.uuid4())
        session2 = runtime2.session()
        self.addCleanup(session2.close)
        payload = daily_plan_service.get_plan(session2, plan_id=self.plan["id"])
        self.assertEqual(payload["content"]["split_baseline"], baseline)
        self.assertEqual(payload["content"]["version"], 3)

    def test_export_reads_adopted_baseline_and_docx(self):
        candidate_id = self.generate(
            self.plan["id"], "daily_lesson_split", SPLIT_CANDIDATE
        )
        preview = self.preview(
            self.plan["id"], candidate_id, ["group_activity"], SPLIT_CANDIDATE
        )
        self.adopt(self.plan["id"], candidate_id, preview["preview_token"])
        self.save_content(
            self.plan["id"],
            2,
            {
                "group_activity": {
                    **SPLIT_CANDIDATE["group_activity"],
                    "process": "一、导入\n二、观察\n三、教师新增整理",
                },
                "reflection": "反思",
            },
        )
        bundle = export_service.prepare_export(
            self.session,
            from_date=date(2026, 9, 2),
            to_date=date(2026, 9, 2),
            ack_missing=False,
            expected_context=None,
        )
        record = bundle.records[0]
        self.assertEqual(
            record.split_baseline,
            {BASELINE_KEY: SPLIT_CANDIDATE["group_activity"]["process"]},
        )
        self.assertEqual(record.warnings, ())
        payload = export_service.generate_docx(bundle)
        self.assertTrue(payload)
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            document = archive.read("word/document.xml").decode("utf-8")
        self.assertIn("教师新增整理", document)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
