"""Pure multi-photo group-notes contract and projection tests."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.local import listening_ai_contracts as contracts
from app.local import listening_ai_inputs as inputs


def _photo(index: int = 0) -> dict:
    return {
        "work_hash": str(index) * 64,
        "format": "png",
        "width": 10 + index,
        "height": 20 + index,
        "orientation": None,
    }


def _input(positions: tuple[int, ...] = (0, 1, 2)) -> dict:
    return {
        "schema_version": 1,
        "mode": "group_notes",
        "domain": "health",
        "domain_label": "健康",
        "grade": "middle",
        "grade_label": "中班",
        "template_version": "v1",
        "template_sha256": "a" * 64,
        "groups": [
            {
                "position": position,
                "work_date": f"2026-12-{position + 1:02d}",
                "listening_text": f"第{position + 1}组正文",
                "photo": _photo(position),
            }
            for position in positions
        ],
    }


def _candidate(positions: tuple[int, ...] = (0, 1, 2), *, mode="group_notes"):
    return {
        "mode": mode,
        "groups": [
            {
                "position": position,
                "text": f"第{position + 1}组观察",
                "uncertainties": ["需核实"],
            }
            for position in positions
        ],
    }


class GroupNotesContractTests(unittest.TestCase):
    def test_one_two_three_photo_slots_are_one_contract(self) -> None:
        for positions in ((0,), (0, 2), (0, 1, 2)):
            with self.subTest(positions=positions):
                payload = _input(positions)
                self.assertEqual(
                    contracts.validate_input(contracts.TASK_GROUP, payload),
                    payload,
                )
                candidate = _candidate(positions)
                self.assertEqual(
                    contracts.validate_candidate(
                        contracts.TASK_GROUP,
                        candidate,
                        expected_positions=positions,
                    ),
                    candidate,
                )

    def test_empty_duplicate_or_reordered_slots_are_refused(self) -> None:
        for groups in (
            [],
            [
                {**_input()["groups"][0], "position": 1},
                {**_input()["groups"][0], "position": 1},
            ],
            [
                {**_input()["groups"][0], "position": 2},
                {**_input()["groups"][0], "position": 0},
            ],
            [{**_input()["groups"][0], "photo": None}],
        ):
            with self.subTest(groups=groups):
                payload = {**_input(), "groups": groups}
                with self.assertRaises(contracts.ListeningAIContractError):
                    contracts.validate_input(contracts.TASK_GROUP, payload)

    def test_candidate_must_match_exactly_the_sent_positions(self) -> None:
        for positions in ((), (0,), (0, 1), (0, 1, 2)):
            with self.subTest(positions=positions):
                with self.assertRaises(contracts.ListeningAIContractError):
                    contracts.validate_candidate(
                        contracts.TASK_GROUP,
                        _candidate(positions),
                        expected_positions=(0, 2),
                    )
        with self.assertRaises(contracts.ListeningAIContractError):
            contracts.validate_candidate(
                contracts.TASK_GROUP,
                _candidate((0, 1, 1)),
                expected_positions=(0, 1, 1),
            )
        with self.assertRaises(contracts.ListeningAIContractError):
            contracts.validate_candidate(
                contracts.TASK_GROUP,
                _candidate(mode="group_note"),
                expected_positions=(0,),
            )

    def test_guidance_forbids_unsupported_inferences(self) -> None:
        guidance = contracts._GUIDANCE_GROUP["groups"]
        self.assertIn("不得推断幼儿原话", guidance)
        self.assertIn("观察时长", guidance)
        self.assertIn("空槽", guidance)
        bundle = contracts.group_notes_bundle_definition()
        self.assertEqual(bundle["task_type"], contracts.TASK_GROUP)
        self.assertIn(
            contracts.TASK_GROUP,
            [item["task_type"] for item in contracts.bundle_definitions()],
        )

    def test_task_type_is_recognized_by_api_and_service_dispatch(self) -> None:
        from app.local.listening_ai_api import ListeningAICreateIn
        from app.local import listening_ai_service

        body = ListeningAICreateIn(
            request_id="request-1",
            expected_revision=1,
            domain="health",
            group_id=None,
            task_type="listening_group_notes",
        )
        self.assertEqual(body.task_type, contracts.TASK_GROUP)
        self.assertEqual(
            listening_ai_service._op_kind(contracts.TASK_GROUP),
            listening_ai_service.OP_GROUP_CREATE,
        )
        self.assertEqual(contracts.target_keys(contracts.TASK_GROUP, []), ())


class GroupNotesProjectionTests(unittest.TestCase):
    def _project(self, asset_positions: tuple[int, ...]):
        groups = []
        for position in range(3):
            groups.append(
                {
                    "group_id": f"g{position}",
                    "position": position,
                    "work_date": f"2026-12-{position + 1:02d}",
                    "listening_text": f"教师文字{position}",
                    "asset_id": f"asset{position}" if position in asset_positions else None,
                }
            )
        domain = {
            "domain": "health",
            "domain_label": "健康",
            "template_version": "v1",
            "template_sha256": "a" * 64,
            "observation_date": "2026-12",
            "adult_count": None,
            "child_age": None,
            "goal": None,
            "observation_area": None,
            "overall_evaluation": None,
            "support_strategy": None,
            "groups": groups,
            "evaluation": [],
        }
        dto = {
            "record_id": "record-1",
            "grade": "middle",
            "revision": 4,
            "domains": [domain],
        }
        template = SimpleNamespace(
            version="v1", sha256="a" * 64, items=[]
        )
        photos = {}
        for position in asset_positions:
            photos[f"g{position}"] = {
                "asset_id": f"asset{position}",
                "group_id": f"g{position}",
                "position": position,
                "source_hash": "a" * 64,
                "work_hash": "b" * 64,
                "mime_type": "image/png",
                "width": 10,
                "height": 20,
                "orientation": None,
                "rotation_quarters": 0,
                "source_bytes": 100,
                "work_bytes": 80,
            }
        with (
            patch.object(inputs, "_load", return_value=(dto, domain, template)),
            patch.object(
                inputs,
                "_read_photo_isolated",
                side_effect=lambda _runtime, **kwargs: photos[kwargs["group_id"]],
            ),
        ):
            projection = inputs.project(
                object(),
                object(),
                profile_id="p",
                record_id="record-1",
                domain="health",
                group_id=None,
                task_type=contracts.TASK_GROUP,
            )
        return projection, groups, photos

    def test_projection_sends_only_photo_slots_and_binds_text_dates(self) -> None:
        for positions in ((0,), (0, 2), (0, 1, 2)):
            with self.subTest(positions=positions):
                projection, groups, _photos = self._project(positions)
                payload = projection.payload
                self.assertEqual(payload["domain"], "health")
                self.assertEqual(
                    [group["position"] for group in payload["groups"]],
                    list(positions),
                )
                for group in payload["groups"]:
                    source = groups[group["position"]]
                    self.assertEqual(group["work_date"], source["work_date"])
                    self.assertEqual(
                        group["listening_text"], source["listening_text"]
                    )
                    self.assertIsNotNone(group["photo"])
                self.assertEqual(
                    projection.dependencies["group_positions"],
                    list(positions),
                )
                self.assertEqual(
                    set(projection.target_hashes),
                    {
                        contracts.group_note_target_key("health", position)
                        for position in positions
                    },
                )
                for position in positions:
                    target = contracts.group_note_target_key(
                        "health", position
                    )
                    self.assertEqual(
                        projection.target_hashes[target],
                        contracts.value_hash(f"教师文字{position}"),
                    )
                self.assertEqual(contracts.validate_input(contracts.TASK_GROUP, payload), payload)

    def test_no_photo_is_refused(self) -> None:
        with self.assertRaises(contracts.ListeningAIContractError):
            self._project(())

    def test_stored_projection_uses_the_same_positions(self) -> None:
        _projection, _groups, photos = self._project((0, 2))
        domain = {
            "domain": "health",
            "domain_label": "健康",
            "template_version": "v1",
            "template_sha256": "a" * 64,
            "groups": [
                {
                    "group_id": f"g{position}",
                    "position": position,
                    "work_date": None,
                    "listening_text": None,
                    "asset_id": f"asset{position}" if position in (0, 2) else None,
                }
                for position in range(3)
            ],
            "evaluation": [],
        }
        dto = {"record_id": "record-1", "grade": "middle", "revision": 4, "domains": [domain]}
        template = SimpleNamespace(version="v1", sha256="a" * 64, items=[])
        with patch.object(inputs, "_load", return_value=(dto, domain, template)):
            projection = inputs.project(
                object(),
                None,
                profile_id="p",
                record_id="record-1",
                domain="health",
                group_id=None,
                task_type=contracts.TASK_GROUP,
                stored_photos=photos,
            )
        self.assertEqual(
            [group["position"] for group in projection.payload["groups"]],
            [0, 2],
        )


if __name__ == "__main__":
    unittest.main()
