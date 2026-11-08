"""Pure multi-photo adoption selection and patch mapping tests.

No database, service session or migration is created here; only the selection
normalizer and the position-to-group mapper used inside the atomic adoption
transaction are exercised.
"""

from __future__ import annotations

import time
import unittest
import uuid
from contextlib import nullcontext
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from app.local import listening_ai_adoption as adoption
from app.local import listening_ai_contracts as contracts
from app.local.errors import (
    LocalStorageError,
    LocalValidationError,
    LocalVersionConflict,
)
from app.local.tx import storage_errors


def _groups() -> list[dict]:
    return [
        {"group_id": "g0", "position": 0},
        {"group_id": "g1", "position": 1},
        {"group_id": "g2", "position": 2},
    ]


class GroupNoteSelectionTests(unittest.TestCase):
    def test_one_two_three_targets_are_one_selection_contract(self) -> None:
        for targets in (
            ("health_0",),
            ("health_0", "health_2"),
            ("health_0", "health_1", "health_2"),
        ):
            with self.subTest(targets=targets):
                selections = [
                    {"target": target, "value": f"正文{position}"}
                    for position, target in enumerate(targets)
                ]
                normalized = adoption._selections(
                    contracts.TASK_GROUP, selections
                )
                self.assertEqual(
                    [item["target"] for item in normalized], list(targets)
                )

    def test_group_selection_refuses_stars_duplicates_and_bad_values(self) -> None:
        for selections in (
            [],
            [{"target": "health_0", "stars": 1}],
            [
                {"target": "health_0", "value": "甲"},
                {"target": "health_0", "value": "乙"},
            ],
            [{"target": "", "value": "甲"}],
            [{"target": "health_0", "value": 1}],
            [{"target": "health_0", "value": "甲", "extra": True}],
            [{"target": "health_0", "value": "甲" * 20_001}],
        ):
            with self.subTest(selections=selections):
                with self.assertRaises(LocalValidationError):
                    adoption._selections(contracts.TASK_GROUP, selections)

    def test_domain_evaluation_still_mixes_text_stars_and_multiple_targets(self) -> None:
        normalized = adoption._selections(
            contracts.TASK_DOMAIN,
            [
                {"target": "overall_evaluation", "value": "综合"},
                {"target": "support_strategy", "value": "支持"},
                {"target": "health_0", "stars": 2},
                {"target": "health_1", "stars": None},
            ],
        )
        self.assertEqual(
            normalized,
            [
                {"target": "overall_evaluation", "value": "综合"},
                {"target": "support_strategy", "value": "支持"},
                {"target": "health_0", "stars": 2},
                {"target": "health_1", "stars": None},
            ],
        )


class GroupNotePatchMappingTests(unittest.TestCase):
    def test_only_selected_sent_positions_become_patch_updates(self) -> None:
        selected = adoption._selections(
            contracts.TASK_GROUP,
            [
                {"target": "health_2", "value": "  第3组正文  "},
                {"target": "health_0", "value": "第1组正文"},
            ],
        )
        updates = adoption.group_note_updates(
            domain="health",
            input_positions=(0, 2),
            groups=_groups(),
            selected=selected,
        )
        self.assertEqual(
            updates,
            [
                {
                    "target": "health_0",
                    "position": 0,
                    "group_id": "g0",
                    "value": "第1组正文",
                },
                {
                    "target": "health_2",
                    "position": 2,
                    "group_id": "g2",
                    "value": "第3组正文",
                },
            ],
        )
        self.assertNotIn(
            1, [update["position"] for update in updates]
        )

    def test_unsent_cross_domain_and_unknown_targets_are_refused(self) -> None:
        for target in ("health_1", "language_0", "health_4", "overall_evaluation"):
            with self.subTest(target=target):
                with self.assertRaises(LocalValidationError):
                    adoption.group_note_updates(
                        domain="health",
                        input_positions=(0, 2),
                        groups=_groups(),
                        selected=[{"target": target, "value": "正文"}],
                    )

    def test_missing_current_group_is_a_storage_error(self) -> None:
        with self.assertRaises(LocalStorageError):
            adoption.group_note_updates(
                domain="health",
                input_positions=(0, 2),
                groups=[{"group_id": "g0", "position": 0}],
                selected=[{"target": "health_2", "value": "正文"}],
            )

    def test_empty_text_is_kept_as_an_explicit_clear(self) -> None:
        updates = adoption.group_note_updates(
            domain="health",
            input_positions=(0,),
            groups=_groups(),
            selected=[{"target": "health_0", "value": "   "}],
        )
        self.assertEqual(updates[0]["value"], "")

    def test_group_target_key_is_domain_position(self) -> None:
        self.assertEqual(
            contracts.group_note_target_key("health", 2), "health_2"
        )
        self.assertEqual(
            contracts.target_keys(contracts.TASK_GROUP, []), ()
        )


class _FakeResult:
    def first(self):
        return None


class _FakeSession:
    def __init__(
        self,
        *,
        commit_error: Exception | None = None,
        rollback_error: Exception | None = None,
    ) -> None:
        self.added: list[object] = []
        self.commits = 0
        self.rollbacks = 0
        self.commit_error = commit_error
        self.rollback_error = rollback_error

    def scalars(self, *_args, **_kwargs) -> _FakeResult:
        return _FakeResult()

    def add(self, value: object) -> None:
        self.added.append(value)

    def flush(self) -> None:
        pass

    def commit(self) -> None:
        self.commits += 1
        if self.commit_error is not None:
            raise self.commit_error

    def rollback(self) -> None:
        self.rollbacks += 1
        if self.rollback_error is not None:
            raise self.rollback_error


class AdoptionCommitBoundaryTests(unittest.TestCase):
    """Fake transaction/session checks; no database or HTTP server is used."""

    def setUp(self) -> None:
        adoption.reset_tokens()
        self.candidate = SimpleNamespace(
            id="cand-1",
            candidate_hash="a" * 64,
            task_type=contracts.TASK_DOMAIN,
        )
        self.inp = SimpleNamespace(
            id="input-1",
            listening_record_id="record-1",
            listening_domain="health",
            listening_group_id=None,
            task_type=contracts.TASK_DOMAIN,
            dependency_hash="d" * 64,
            payload_json={},
            target_hashes_json={},
        )
        self.target_hashes = {
            "overall_evaluation": contracts.value_hash(""),
            "support_strategy": contracts.value_hash(""),
            "health_1": contracts.value_hash(None),
        }
        self.current = {
            "overall_evaluation": "",
            "support_strategy": "",
            "health_1": None,
        }
        self.token, _expires = adoption._TOKENS.issue(
            {
                "v": 1,
                "profile_id": "p",
                "record_id": "record-1",
                "domain": "health",
                "group_id": None,
                "candidate_id": "cand-1",
                "candidate_hash": "a" * 64,
                "input_id": "input-1",
                "task_type": contracts.TASK_DOMAIN,
                "dependency_hash": "d" * 64,
                "target_hashes": self.target_hashes,
                "source_revision": 5,
                "launch_id": "launch-1",
                "session_scope_hash": "scope-1",
            },
            time.time(),
        )

    def tearDown(self) -> None:
        adoption.reset_tokens()

    def _call(self, session, kernel=None):
        if kernel is None:

            def kernel(*_args, **_kwargs):
                return (
                    {
                        "record_id": "record-1",
                        "domain": "health",
                        "revision": 6,
                        "changed": True,
                    },
                    True,
                )

        with (
            patch.object(adoption, "read_scope", lambda _session: nullcontext()),
            patch.object(
                adoption,
                "_candidate_chain",
                return_value=(self.candidate, object(), self.inp),
            ),
            patch.object(
                adoption,
                "_current_projection",
                return_value=SimpleNamespace(dependency_hash="d" * 64),
            ),
            patch.object(
                adoption,
                "_current_targets",
                return_value=(
                    {"revision": 5, "groups": []},
                    self.current,
                ),
            ),
            patch.object(
                adoption.listening_service,
                "read_record_no_tx",
                return_value={"revision": 5, "groups": []},
            ),
            patch.object(
                adoption.listening_ai_inputs,
                "revalidate_source",
                return_value=True,
            ),
            patch.object(
                adoption.listening_service,
                "domain_patch_kernel_no_tx",
                side_effect=kernel,
            ) as kernel_mock,
            patch.object(
                adoption.listening_service, "_audit", return_value=None
            ),
            patch.object(
                adoption.ai_task_service,
                "_now",
                return_value=datetime(2026, 11, 8, 12, 0, 0),
            ),
            patch.object(adoption, "begin_immediate"),
        ):
            result = adoption.adopt(
                session,
                runtime=object(),
                profile_id="p",
                record_id="record-1",
                request_id=str(uuid.uuid4()),
                expected_revision=5,
                preview_token=self.token,
                selections=[
                    {"target": "overall_evaluation", "value": "新综合"}
                ],
                candidate_id="cand-1",
                launch_id="launch-1",
                session_scope_hash="scope-1",
            )
        return result, kernel_mock

    def test_commit_phase_failure_is_typed_with_original_cause(self) -> None:
        cause = RuntimeError("synthetic commit lost")
        session = _FakeSession(commit_error=cause)
        with self.assertRaises(
            adoption.ListeningAIAdoptionCommitUncertain
        ) as raised:
            self._call(session)
        self.assertEqual(
            raised.exception.code, "LISTENING_AI_ADOPTION_COMMIT_UNCERTAIN"
        )
        self.assertEqual(raised.exception.status_code, 503)
        self.assertIs(raised.exception.__cause__, cause)
        self.assertEqual(session.commits, 1)
        self.assertEqual(session.rollbacks, 1)

    def test_rollback_failure_does_not_mask_commit_uncertain(self) -> None:
        cause = RuntimeError("synthetic commit lost")
        session = _FakeSession(
            commit_error=cause,
            rollback_error=OSError("synthetic rollback also failed"),
        )
        with self.assertRaises(
            adoption.ListeningAIAdoptionCommitUncertain
        ) as raised:
            self._call(session)
        self.assertIs(raised.exception.__cause__, cause)
        self.assertEqual(session.rollbacks, 1)

    def test_pre_commit_failure_stays_definite(self) -> None:
        session = _FakeSession()
        with self.assertRaises(LocalVersionConflict) as raised:
            self._call(
                session,
                kernel=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    LocalVersionConflict()
                ),
            )
        self.assertEqual(raised.exception.code, "VERSION_CONFLICT")
        self.assertEqual(session.commits, 0)
        self.assertEqual(session.rollbacks, 1)

    def test_pre_commit_failure_and_rollback_failure_keep_original(self) -> None:
        session = _FakeSession(
            rollback_error=OSError("synthetic rollback also failed")
        )
        with self.assertRaises(LocalValidationError) as raised:
            self._call(
                session,
                kernel=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    LocalValidationError("采用目标已变化")
                ),
            )
        self.assertEqual(raised.exception.message, "采用目标已变化")
        self.assertEqual(session.commits, 0)

    def test_api_storage_wrapper_keeps_commit_uncertain_code(self) -> None:
        with self.assertRaises(
            adoption.ListeningAIAdoptionCommitUncertain
        ) as raised:
            with storage_errors():
                raise adoption.ListeningAIAdoptionCommitUncertain()
        self.assertEqual(
            raised.exception.code, "LISTENING_AI_ADOPTION_COMMIT_UNCERTAIN"
        )
        self.assertEqual(raised.exception.status_code, 503)

    def test_successful_commit_has_one_write_and_one_revision(self) -> None:
        session = _FakeSession()
        result, kernel = self._call(session)
        self.assertEqual(result["revision_after"], 6)
        self.assertEqual(session.commits, 1)
        self.assertEqual(session.rollbacks, 0)
        self.assertEqual(kernel.call_count, 1)


if __name__ == "__main__":
    unittest.main()
