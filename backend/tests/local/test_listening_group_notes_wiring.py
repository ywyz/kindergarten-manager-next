"""Pure #43 central wiring, serialization, worker and backup validation tests.

No database, SQLite connection or migration is opened or executed.
"""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.local import (
    ai_task_service,
    ai_transport,
    ai_worker,
    backup_validate,
    listening_ai_contracts as contracts,
    listening_ai_inputs,
    listening_templates,
    models,
    prompt_bundles,
)
from app.local.prompt_bundles import canonical_json

ROOT = Path(__file__).resolve().parents[2]


class CentralWiringTests(unittest.TestCase):
    def test_prompt_bundle_and_backfill_register_group_notes(self) -> None:
        self.assertIn(contracts.TASK_GROUP, contracts.TASK_TYPES)
        self.assertIn(
            contracts.TASK_GROUP,
            [
                item["task_type"]
                for item in contracts.bundle_definitions()
            ],
        )
        self.assertIn(contracts.TASK_GROUP, prompt_bundles.LISTENING_TASK_TYPES)
        self.assertIn(contracts.TASK_GOAL, prompt_bundles.LISTENING_TASK_TYPES)
        self.assertIn(contracts.TASK_GROUP, prompt_bundles.NEW_TASK_TYPES)
        self.assertIn(contracts.TASK_GROUP, prompt_bundles.REGISTERED_TASK_TYPES)
        self.assertIn(contracts.TASK_GROUP, prompt_bundles.BACKFILL_TASK_TYPES)
        self.assertIn(contracts.TASK_GOAL, prompt_bundles.BACKFILL_TASK_TYPES)
        self.assertIn(
            contracts.TASK_GROUP,
            [
                bundle["task_type"]
                for bundle in prompt_bundles.PROMPT_BUNDLE_MANIFEST
            ],
        )
        self.assertIn(contracts.TASK_GROUP, prompt_bundles.GUIDANCE_FIELDS)
        self.assertIn(contracts.TASK_GOAL, prompt_bundles.GUIDANCE_FIELDS)
        candidate = {
            "mode": "group_notes",
            "groups": [
                {
                    "position": 0,
                    "text": "合成观察",
                    "uncertainties": [],
                }
            ],
        }
        self.assertEqual(
            prompt_bundles.validate_candidate(
                contracts.TASK_GROUP, candidate
            ),
            candidate,
        )
        payload = {
            "schema_version": contracts.INPUT_SCHEMA_VERSION,
            "mode": "group_notes",
            "domain": "health",
            "domain_label": "健康",
            "grade": "middle",
            "grade_label": "中班",
            "template_version": "v1",
            "template_sha256": "a" * 64,
            "groups": [
                {
                    "position": 0,
                    "work_date": None,
                    "listening_text": None,
                    "photo": {
                        "work_hash": "b" * 64,
                        "format": "png",
                        "width": 10,
                        "height": 20,
                        "orientation": None,
                    },
                }
            ],
        }
        self.assertEqual(
            prompt_bundles.validate_input(contracts.TASK_GROUP, payload),
            payload,
        )

    def test_shared_model_constraints_match_the_group_contract(self) -> None:
        for table in (
            models.LocalPromptBundle,
            models.LocalAIInput,
            models.LocalAITask,
            models.LocalAIExecution,
            models.LocalAICandidate,
        ):
            with self.subTest(table=table.__name__):
                text = " ".join(
                    str(item.sqltext)
                    for item in table.__table__.constraints
                    if getattr(item, "sqltext", None) is not None
                )
                self.assertIn(contracts.TASK_GROUP, text)
                self.assertIn(contracts.TASK_GOAL, text)
        adoption_text = " ".join(
            str(item.sqltext)
            for item in models.LocalListeningAIAdoption.__table__.constraints
            if getattr(item, "sqltext", None) is not None
        )
        self.assertIn("'goal'", adoption_text)
        listening_indexes = {
            item.name
            for item in models.LocalAITask.__table__.indexes
            if "listening" in item.name
        }
        self.assertEqual(
            listening_indexes,
            {
                "uq_local_ai_tasks_active_listening_note",
                "uq_local_ai_tasks_active_listening_domain",
                "uq_local_ai_tasks_active_listening_group_notes",
                "uq_local_ai_tasks_active_listening_goal",
            },
        )

    def test_single_forward_migration_successor(self) -> None:
        versions = ROOT / "migrations_local" / "versions"
        migration = versions / "20261108_0015_local_listening_group_notes.py"
        source = migration.read_text(encoding="utf-8")
        self.assertIn(
            'revision: str = "20261108_0015_local_listening_group_notes"',
            source,
        )
        self.assertIn(
            'down_revision: Union[str, None] = '
            '"20261108_0014_local_reflection_ai"',
            source,
        )
        self.assertIn("listening_group_notes", source)
        self.assertIn(
            "uq_local_ai_tasks_active_listening_group_notes", source
        )
        self.assertIn("op.drop_table", source)
        self.assertIn("op.rename_table", source)
        for column in (
            "listening_record_id",
            "listening_domain",
            "listening_group_id",
        ):
            self.assertIn(column, source)
        for foreign_key in (
            "fk_local_ai_inputs_listening_record",
            "fk_local_ai_inputs_listening_domain",
            "fk_local_ai_inputs_listening_group",
            "fk_local_ai_tasks_source_input",
            "fk_local_ai_executions_source_task",
            "fk_local_ai_candidates_source_execution",
        ):
            self.assertIn(foreign_key, source)
        self.assertEqual(
            source.count(
                "task_type IN ('listening_domain_evaluate', "
                "'listening_group_notes')"
            ),
            4,
        )
        successors = []
        for item in versions.glob("*.py"):
            text = item.read_text(encoding="utf-8")
            if (
                'down_revision: Union[str, None] = '
                '"20261108_0014_local_reflection_ai"' in text
            ):
                successors.append(item.name)
        self.assertEqual(
            successors, ["20261108_0015_local_listening_group_notes.py"]
        )
        migration16 = versions / "20261108_0016_local_listening_goal_suggest.py"
        source16 = migration16.read_text(encoding="utf-8")
        self.assertIn(
            'revision: str = "20261108_0016_local_listening_goal_suggest"',
            source16,
        )
        self.assertIn(
            'down_revision: Union[str, None] = '
            '"20261108_0015_local_listening_group_notes"',
            source16,
        )
        self.assertIn("listening_goal_suggest", source16)
        self.assertIn(
            "uq_local_ai_tasks_active_listening_goal", source16
        )
        self.assertIn("_rebuild_listening_ai_adoption", source16)
        self.assertIn("'support_strategy', 'goal'", source16)
        for foreign_key in (
            "fk_local_listening_ai_adoption_record",
            "fk_local_listening_ai_adoption_domain",
            "fk_local_listening_ai_adoption_group",
            "fk_local_listening_ai_adoption_candidate",
            "fk_local_listening_ai_adoption_operation",
        ):
            self.assertIn(foreign_key, source16)
        successors16 = []
        for item in versions.glob("*.py"):
            text = item.read_text(encoding="utf-8")
            if (
                'down_revision: Union[str, None] = '
                '"20261108_0015_local_listening_group_notes"' in text
            ):
                successors16.append(item.name)
        self.assertEqual(
            successors16,
            ["20261108_0016_local_listening_goal_suggest.py"],
        )

    def test_transport_and_worker_keep_group_in_the_vision_set(self) -> None:
        self.assertIn(
            contracts.TASK_GROUP, ai_transport.LISTENING_VISION_TASK_TYPES
        )
        self.assertNotIn(
            contracts.TASK_GROUP, ai_transport.LISTENING_TEXT_TASK_TYPES
        )
        self.assertIn(
            contracts.TASK_GOAL, ai_transport.LISTENING_VISION_TASK_TYPES
        )
        self.assertIn(
            contracts.TASK_GOAL, ai_transport.LISTENING_TEXT_TASK_TYPES
        )
        self.assertIn(contracts.TASK_GROUP, ai_worker.VISION_TASK_TYPES)
        self.assertIn(contracts.TASK_GOAL, ai_worker.VISION_TASK_TYPES)
        budget, body = ai_worker.text_request_body(
            {
                "source_kind": "one_to_one_listening",
                "task_type": contracts.TASK_GOAL,
                "model": "synthetic",
                "system_text": "system",
                "user_text": "{}",
            }
        )
        self.assertGreater(budget.max_tokens, 0)
        self.assertIn(b"synthetic", body)

        def header(count: int, group_id=None, task_type=contracts.TASK_GROUP):
            return {
                "type": "bootstrap_header",
                "vision": True,
                "protocol": ai_transport.VISION_PROTOCOL_ID,
                "schema_version": 1,
                "source_kind": "one_to_one_listening",
                "task_type": task_type,
                "contract_version": 1,
                "image_count": count,
                "listening_record_id": "record",
                "listening_domain": "health",
                "listening_group_id": group_id,
                "frame_size": 1,
            }

        for count in (1, 2, 3):
            with self.subTest(count=count):
                value = header(count)
                self.assertTrue(ai_worker.validate_vision_header(value))
                request = {
                    "protocol": ai_transport.VISION_PROTOCOL_ID,
                    "vision": {
                        key: value[key]
                        for key in (
                            "protocol",
                            "schema_version",
                            "source_kind",
                            "task_type",
                            "contract_version",
                            "image_count",
                            "listening_record_id",
                            "listening_domain",
                            "listening_group_id",
                        )
                    },
                    "image_urls": [
                        "data:image/png;base64,AA"
                    ] * count,
                }
                self.assertTrue(
                    ai_worker.validate_vision_bootstrap(
                        value, request, request["image_urls"]
                    )
                )
        self.assertFalse(ai_worker.validate_vision_header(header(4)))
        self.assertFalse(
            ai_worker.validate_vision_header(header(1, "group-0"))
        )
        self.assertFalse(
            ai_worker.validate_vision_header(
                header(1, None, contracts.TASK_NOTE)
            )
        )
        self.assertTrue(
            ai_worker.validate_vision_header(
                header(1, "group-0", contracts.TASK_NOTE)
            )
        )
        for count in (1, 2, 3):
            self.assertTrue(
                ai_worker.validate_vision_header(
                    header(count, None, contracts.TASK_GOAL)
                )
            )
        self.assertFalse(
            ai_worker.validate_vision_header(
                header(1, "group-0", contracts.TASK_GOAL)
            )
        )

    def test_executor_source_uses_shared_transport_vision_contract(self) -> None:
        source = (
            ROOT / "app" / "local" / "ai_executor.py"
        ).read_text(encoding="utf-8")
        self.assertIn("LISTENING_VISION_TASK_TYPES", source)
        self.assertIn('claim.task_type != "listening_note_draft"', source)

    def test_finalize_rejects_missing_extra_or_reordered_group_positions(self) -> None:
        class FakeSession:
            def get(self, _model, _identity):
                return SimpleNamespace(
                    payload_json={
                        "groups": [
                            {"position": 0},
                            {"position": 2},
                        ]
                    }
                )

        claim = SimpleNamespace(
            source_kind="one_to_one_listening",
            task_type=contracts.TASK_GROUP,
            input_id="input-1",
        )
        failures: list[dict] = []

        def fail(_session, _claim, result, _now):
            failures.append(result)
            return False

        candidates = (
            [2],
            [0, 1, 2],
            [2, 0],
        )
        with patch.object(
            ai_task_service, "finalize_failure", side_effect=fail
        ):
            for positions in candidates:
                with self.subTest(positions=positions):
                    result = ai_task_service.finalize_success(
                        FakeSession(),
                        claim,
                        {
                            "candidate_text": json.dumps(
                                {
                                    "mode": "group_notes",
                                    "groups": [
                                        {
                                            "position": position,
                                            "text": "合成",
                                            "uncertainties": [],
                                        }
                                        for position in positions
                                    ],
                                }
                            )
                        },
                        ai_task_service._now(),
                    )
                    self.assertFalse(result)
        self.assertEqual(len(failures), 3)
        self.assertTrue(
            all(item.get("reason") == "output_invalid" for item in failures)
        )

    def test_production_vision_frames_match_ordered_group_payload(self) -> None:
        template = listening_templates.get_template("middle", "health")
        for positions in ((0,), (0, 2), (0, 1, 2)):
            with self.subTest(positions=positions):
                groups = []
                for position in positions:
                    groups.append(
                        {
                            "position": position,
                            "work_date": "2026-10-01",
                            "listening_text": f"第 {position + 1} 组教师文字",
                            "photo": {
                                "work_hash": str(position + 3) * 64,
                                "format": "jpeg",
                                "width": 40,
                                "height": 30,
                                "orientation": None,
                            },
                        }
                    )
                payload = {
                    "schema_version": contracts.INPUT_SCHEMA_VERSION,
                    "mode": "group_notes",
                    "domain": "health",
                    "domain_label": "健康",
                    "grade": "middle",
                    "grade_label": "中班",
                    "template_version": template.version,
                    "template_sha256": template.sha256,
                    "groups": groups,
                }
                user_text = json.dumps(
                    payload, ensure_ascii=False, separators=(",", ":")
                )
                image_urls = [
                    "data:image/png;base64,AA"
                ] * len(positions)
                frames = listening_ai_inputs.build_vision_frames(
                    base_url="https://example.invalid/v1",
                    model="synthetic-vision",
                    secret="synthetic-secret",
                    system_text="system",
                    user_text=user_text,
                    image_urls=image_urls,
                    deadline_ms=1000,
                    task_type=contracts.TASK_GROUP,
                    contract_version=1,
                    record_id="record",
                    domain="health",
                    group_id=None,
                    synthetic={"provider": "fake"},
                )
                self.assertEqual(len(frames), 2)
                header = json.loads(frames[0])
                body = json.loads(frames[1])
                self.assertEqual(header["frame_size"], len(frames[1]))
                self.assertEqual(header["image_count"], len(positions))
                self.assertEqual(header["task_type"], contracts.TASK_GROUP)
                self.assertIsNone(header["listening_group_id"])
                self.assertEqual(len(body["request"]["image_urls"]), len(positions))
                self.assertTrue(ai_worker.validate_vision_header(header))
                self.assertTrue(
                    ai_worker.validate_vision_bootstrap(
                        header,
                        body["request"],
                        body["request"]["image_urls"],
                        actual_body_size=len(frames[1]),
                    )
                )
                visible = json.loads(body["request"]["user_text"])
                self.assertEqual(
                    [group["position"] for group in visible["groups"]],
                    list(positions),
                )
                for group in visible["groups"]:
                    self.assertEqual(
                        set(group),
                        {
                            "position",
                            "work_date",
                            "listening_text",
                            "photo",
                        },
                    )
                    self.assertNotIn("group_id", group)
                    self.assertNotIn("asset_id", group)
                self.assertNotIn("asset-", body["request"]["user_text"])
                self.assertNotIn("group-", body["request"]["user_text"])
                self.assertNotIn("C:\\", body["request"]["user_text"])

    def test_backup_chain_accepts_historical_group_positions(self) -> None:
        def digest(value):
            return hashlib.sha256(
                canonical_json(value).encode()
            ).hexdigest()

        def data(variant: str):
            template = listening_templates.get_template("middle", "health")
            positions = [0, 2]
            photos = [
                {
                    "asset_id": f"asset-{position}",
                    "source_hash": str(position + 2) * 64,
                    "work_hash": str(position + 3) * 64,
                    "group_id": f"group-{position}",
                    "position": position,
                }
                for position in positions
            ]
            payload = {
                "schema_version": contracts.INPUT_SCHEMA_VERSION,
                "mode": "group_notes",
                "domain": "health",
                "domain_label": "健康",
                "grade": "middle",
                "grade_label": "中班",
                "template_version": template.version,
                "template_sha256": template.sha256,
                "groups": [
                    {
                        "position": photo["position"],
                        "work_date": "2026-10-01",
                        "listening_text": None,
                        "photo": {
                            "work_hash": photo["work_hash"],
                            "format": "jpeg",
                            "width": 40,
                            "height": 30,
                            "orientation": None,
                        },
                    }
                    for photo in photos
                ],
            }
            deps = {
                "wire_schema_version": 1,
                "internal_schema_version": 1,
                "record_id": "record",
                "domain": "health",
                "group_id": None,
                "group_positions": positions,
                "template_version": template.version,
                "template_sha256": template.sha256,
                "photos": photos,
                "source_revision": 2,
            }
            targets = {
                f"health_{position}": contracts.value_hash("")
                for position in positions
            }
            raw_positions = (
                [2, 0] if variant == "wrong-order" else positions
            )
            raw = {
                "mode": "group_notes",
                "groups": [
                    {
                        "position": position,
                        "text": f"合成观察 {position}",
                        "uncertainties": [],
                    }
                    for position in raw_positions
                ],
            }
            adopted = [
                {
                    "target": "health_2",
                    "position": 2,
                    "group_id": "group-2",
                    "value": "合成已采用",
                }
            ]
            result = {
                "request_id": "request",
                "operation_kind": "listening_ai_adopt",
                "listening_record_id": "record",
                "domain": "health",
                "group_id": None,
                "revision_after": 3,
                "adopted": adopted,
                "group_updates": adopted,
                "replayed": False,
            }
            dependency_hash = digest(
                {
                    "payload": payload,
                    "photos": [
                        {
                            key: item[key]
                            for key in (
                                "group_id",
                                "position",
                                "work_hash",
                            )
                        }
                        for item in photos
                    ],
                }
            )
            return {
                "sqlite_master": [("local_listening_ai_adoption",)],
                "local_ai_inputs": [
                    (
                        "input-1",
                        "profile",
                        "record",
                        "record",
                        "health",
                        None,
                        contracts.TASK_GROUP,
                        contracts.INPUT_SCHEMA_VERSION,
                        json.dumps(payload),
                        json.dumps(deps),
                        dependency_hash,
                        json.dumps(targets),
                        None,
                    )
                ],
                "local_ai_tasks": [
                    (
                        "task",
                        "profile",
                        "record",
                        "record",
                        "health",
                        None,
                        "input-1",
                        contracts.TASK_GROUP,
                        "succeeded",
                        "execution",
                    )
                ],
                "local_ai_executions": [
                    (
                        "execution",
                        "task",
                        "profile",
                        "record",
                        "record",
                        "health",
                        None,
                        "input-1",
                        contracts.TASK_GROUP,
                        1,
                        "succeeded",
                        1,
                        1,
                        1,
                    )
                ],
                "local_ai_candidates": [
                    (
                        "candidate",
                        "profile",
                        "execution",
                        "task",
                        "record",
                        "record",
                        "health",
                        None,
                        "input-1",
                        contracts.TASK_GROUP,
                        1,
                        json.dumps(raw),
                        digest(raw),
                    )
                ],
                "local_listening_ai_adoption": [
                    (
                        "adoption",
                        "profile",
                        "record",
                        "health",
                        None,
                        "__domain__"
                        if variant == "wrong-scope"
                        else "__group_notes__",
                        "health_2",
                        "candidate",
                        "input-1",
                        targets["health_2"],
                        contracts.value_hash(adopted[0]["value"]),
                        2,
                        3,
                        "operation",
                    )
                ],
                "local_ai_operations": [
                    ("listening_ai_adopt", json.dumps(result))
                ],
                "local_listening_assets": {
                    photo["asset_id"]: [("record", photo["source_hash"])]
                    for photo in photos
                },
                "local_listening_photo_groups": {
                    f"group-{position}": [
                        (
                            "record",
                            "health",
                            2 - position
                            if variant == "reordered-current"
                            else position,
                        )
                    ]
                    for position in positions
                },
            }

        class Rows:
            def __init__(self, rows):
                self.rows = rows

            def fetchall(self):
                return self.rows

            def fetchone(self):
                return self.rows[0] if self.rows else None

        class FakeConnection:
            def __init__(self, values):
                self.values = values
                self.reads = 0

            def execute(self, sql, parameters=()):
                self.reads += 1
                normalized = " ".join(sql.lower().split())
                for table, rows in self.values.items():
                    if (
                        f"from {table} " in normalized
                        or normalized.endswith(f"from {table}")
                    ):
                        if isinstance(rows, dict):
                            return Rows(rows.get(parameters[-1], []))
                        return Rows(rows)
                raise AssertionError(normalized)

        backup_validate._listening_ai_chain(FakeConnection(data("normal")))
        backup_validate._listening_ai_chain(
            FakeConnection(data("reordered-current"))
        )
        for variant in ("wrong-order", "wrong-scope"):
            with self.subTest(variant=variant):
                with self.assertRaises(backup_validate.BackupValidationError):
                    backup_validate._listening_ai_chain(
                        FakeConnection(data(variant))
                    )

        def add_second_adoption(
            values,
            *,
            swapped=False,
            edited=None,
            tamper=False,
            tampered_target=False,
            wrong_group=False,
        ):
            base_input = values["local_ai_inputs"][0]
            payload = json.loads(base_input[8])
            deps = json.loads(base_input[9])
            photo_by_position = {
                int(photo["position"]): dict(photo)
                for photo in deps["photos"]
            }
            if swapped:
                replacement = {
                    0: dict(photo_by_position[2], position=0),
                    2: dict(photo_by_position[0], position=2),
                }
                deps["photos"] = [replacement[0], replacement[2]]
                for group in payload["groups"]:
                    source = replacement[int(group["position"])]
                    group["photo"]["work_hash"] = source["work_hash"]
            if edited is not None:
                for group in payload["groups"]:
                    if int(group["position"]) == 2:
                        group["listening_text"] = edited
            deps["source_revision"] = 4
            targets = {
                f"health_{group['position']}": contracts.value_hash(
                    (group.get("listening_text") or "").strip()
                )
                for group in payload["groups"]
            }
            if tampered_target:
                targets["health_2"] = contracts.value_hash("篡改")
            dependency_hash = digest(
                {
                    "payload": payload,
                    "photos": [
                        {
                            key: item[key]
                            for key in (
                                "group_id",
                                "position",
                                "work_hash",
                            )
                        }
                        for item in deps["photos"]
                    ],
                }
            )
            second_input = list(base_input)
            second_input[0] = "input-2"
            second_input[8] = json.dumps(payload)
            second_input[9] = json.dumps(deps)
            second_input[10] = dependency_hash
            second_input[11] = json.dumps(targets)
            values["local_ai_inputs"].append(tuple(second_input))

            task = list(values["local_ai_tasks"][0])
            task[0], task[6], task[9] = "task-2", "input-2", "execution-2"
            values["local_ai_tasks"].append(tuple(task))
            execution = list(values["local_ai_executions"][0])
            execution[0], execution[1], execution[7] = (
                "execution-2",
                "task-2",
                "input-2",
            )
            values["local_ai_executions"].append(tuple(execution))
            candidate = {
                "mode": "group_notes",
                "groups": [
                    {
                        "position": position,
                        "text": f"合成观察 {position}",
                        "uncertainties": [],
                    }
                    for position in (0, 2)
                ],
            }
            candidate_row = list(values["local_ai_candidates"][0])
            candidate_row[0] = "candidate-2"
            candidate_row[2] = "execution-2"
            candidate_row[3] = "task-2"
            candidate_row[8] = "input-2"
            candidate_row[11] = json.dumps(candidate)
            candidate_row[12] = digest(candidate)
            values["local_ai_candidates"].append(tuple(candidate_row))

            group_id = "group-0" if swapped else "group-2"
            if wrong_group:
                group_id = "group-2"
            value = "再次采用" if edited is not None else "另一图组已采用"
            adopted = {
                "target": "health_2",
                "position": 2,
                "group_id": group_id,
                "value": value,
            }
            before_hash = (
                contracts.value_hash("篡改")
                if tamper
                else targets["health_2"]
            )
            adoption = list(values["local_listening_ai_adoption"][0])
            adoption[0] = "adoption-2"
            adoption[7] = "candidate-2"
            adoption[8] = "input-2"
            adoption[9] = before_hash
            adoption[10] = contracts.value_hash(value)
            adoption[11] = 4
            adoption[12] = 5
            adoption[13] = "operation-2"
            values["local_listening_ai_adoption"].append(tuple(adoption))
            result = {
                "request_id": "second-request",
                "operation_kind": "listening_ai_adopt",
                "listening_record_id": "record",
                "domain": "health",
                "group_id": None,
                "revision_after": 5,
                "adopted": [adopted],
                "group_updates": [adopted],
                "replayed": False,
            }
            values["local_ai_operations"] = {
                "operation": values["local_ai_operations"],
                "operation-2": [
                    ("listening_ai_adopt", json.dumps(result))
                ],
            }
            return values

        backup_validate._listening_ai_chain(
            FakeConnection(
                add_second_adoption(data("reordered-current"), swapped=True)
            )
        )
        backup_validate._listening_ai_chain(
            FakeConnection(
                add_second_adoption(data("normal"), edited="手工修改")
            )
        )
        for kwargs in (
            {"edited": "手工修改", "tamper": True},
            {"edited": "手工修改", "tampered_target": True},
            {"swapped": True, "wrong_group": True},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(backup_validate.BackupValidationError):
                    backup_validate._listening_ai_chain(
                        FakeConnection(
                            add_second_adoption(data("normal"), **kwargs)
                        )
                    )
        source = Path(backup_validate.__file__).read_text(encoding="utf-8")
        self.assertIn("倾听采用后向链", source)
        self.assertIn(
            'if candidate[9] == "listening_group_notes":', source
        )


if __name__ == "__main__":
    unittest.main()
