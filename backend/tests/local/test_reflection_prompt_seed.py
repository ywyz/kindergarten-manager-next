"""Pure old-archive reflection prompt seed and initialization gate tests."""

from __future__ import annotations

import inspect
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.local import ai_task_service, profile_service, prompt_bundles
from app.local.base import utc_now
from app.local.errors import LocalStorageError
from app.local.models import (
    LocalPersonalPromptHead,
    LocalPersonalPromptVersion,
    LocalProfile,
    LocalPromptBundle,
)

TYPE = "daily_reflection_generate"
PROFILE = "synthetic-existing-profile"


class Rows:
    def __init__(self, values=()):
        self.values = list(values)

    def all(self):
        return self.values

    def first(self):
        return self.values[0] if self.values else None


class FakeSession:
    """Only the query surface used by the prompt seed/readiness helpers."""

    def __init__(self, *, profiles=(PROFILE,), bundles=()):
        self.profiles = list(profiles)
        self.bundles = list(bundles)
        self.heads: dict[tuple[str, str], object] = {}
        self.versions: dict[tuple[str, str, int], object] = {}
        self.added: list[object] = []

    def scalars(self, statement):
        description = statement.column_descriptions[0]
        if description.get("name") == "id":
            return Rows(self.profiles)
        entity = description.get("entity")
        if entity is LocalProfile:
            return Rows(self.profiles)
        if entity is LocalPersonalPromptVersion:
            # The seed helper only issues this query for a head-less task.
            # In this fixture the only head-less task is reflection.
            return Rows()
        if entity is LocalPromptBundle:
            return Rows(self.bundles)
        raise AssertionError(f"unexpected scalar query: {description!r}")

    def get(self, model, key):
        if model is LocalPersonalPromptHead:
            return self.heads.get(tuple(key))
        if model is LocalPersonalPromptVersion:
            return self.versions.get(tuple(key))
        return None

    def add(self, row):
        self.added.append(row)
        if isinstance(row, LocalPersonalPromptHead):
            key = (row.profile_id, row.task_type)
            assert key not in self.heads
            self.heads[key] = row
        elif isinstance(row, LocalPersonalPromptVersion):
            key = (row.profile_id, row.task_type, row.revision)
            assert key not in self.versions
            self.versions[key] = row
        else:  # pragma: no cover - the seed only adds these two row kinds
            raise AssertionError(type(row).__name__)


class ReflectionPromptSeedTests(unittest.TestCase):
    def setUp(self):
        self.items = prompt_bundles._normalize_manifest(
            prompt_bundles.PROMPT_BUNDLE_MANIFEST
        )
        self.targets = prompt_bundles._targets(self.items)

    def _seed_target(self, task_type):
        target = self.targets[task_type]
        item = self.items[
            (
                task_type,
                target["required_contract_version"],
                target["latest_default_revision"],
            )
        ]
        return target, item

    def test_existing_profile_gets_only_missing_reflection_seed_once(self):
        session = FakeSession()
        existing: dict[str, tuple[object, object]] = {}
        for task_type in prompt_bundles.BACKFILL_TASK_TYPES:
            if task_type == TYPE:
                continue
            head = SimpleNamespace(
                profile_id=PROFILE,
                task_type=task_type,
                current_revision=1,
                required_contract_version=1,
                latest_default_revision=1,
            )
            version = SimpleNamespace(
                profile_id=PROFILE,
                task_type=task_type,
                revision=1,
                contract_version=1,
                based_default_revision=1,
                guidance_json={"guidance": f"教师已保存的{task_type}文字"},
            )
            session.heads[(PROFILE, task_type)] = head
            session.versions[(PROFILE, task_type, 1)] = version
            existing[task_type] = (head, version)

        seeded = prompt_bundles._ensure_missing_observation_prompt_seeds(
            session, self.items, self.targets, utc_now()
        )
        self.assertEqual(seeded, 1)
        target, item = self._seed_target(TYPE)
        head = session.get(LocalPersonalPromptHead, (PROFILE, TYPE))
        version = session.get(LocalPersonalPromptVersion, (PROFILE, TYPE, 1))
        self.assertIsNotNone(head)
        self.assertIsNotNone(version)
        self.assertEqual(head.current_revision, 1)
        self.assertEqual(head.required_contract_version, target["required_contract_version"])
        self.assertEqual(head.latest_default_revision, target["latest_default_revision"])
        self.assertEqual(version.contract_version, target["required_contract_version"])
        self.assertEqual(
            version.based_default_revision, target["latest_default_revision"]
        )
        self.assertEqual(version.guidance_json, item["guidance_defaults_json"])
        observation_head, observation_version = existing["game_observation_generate"]
        self.assertEqual(observation_head.current_revision, 1)
        self.assertEqual(
            observation_version.guidance_json,
            {"guidance": "教师已保存的game_observation_generate文字"},
        )

        version.guidance_json = {"reflection": "教师后来手写的个人反思指导"}
        version.revision = 1
        self.assertEqual(
            prompt_bundles._ensure_missing_observation_prompt_seeds(
                session, self.items, self.targets, utc_now()
            ),
            0,
        )
        self.assertEqual(
            version.guidance_json, {"reflection": "教师后来手写的个人反思指导"}
        )
        self.assertEqual(version.revision, 1)

        state = SimpleNamespace(profile_id=PROFILE)
        config = SimpleNamespace(
            base_url="https://synthetic.invalid",
            model="synthetic",
            credential_id="synthetic",
        )
        with patch(
            "app.local.ai_config_service._read_config",
            return_value=(state, config, None),
        ):
            ai_task_service._require_ai_ready(session, TYPE)

    def test_initial_hard_gate_is_only_the_original_three(self):
        required = set(prompt_bundles.INITIAL_REQUIRED_TASK_TYPES)
        self.assertEqual(
            required,
            {
                "daily_lesson_split",
                "daily_process_adapt",
                "daily_other_activities",
            },
        )
        self.assertIn(TYPE, prompt_bundles.TASK_TYPES)
        self.assertNotIn(TYPE, required)
        self.assertEqual(
            profile_service.INITIAL_REQUIRED_TASK_TYPES,
            prompt_bundles.INITIAL_REQUIRED_TASK_TYPES,
        )
        initialization_source = inspect.getsource(profile_service._create_initialized)
        self.assertIn(
            "required_task_types=INITIAL_REQUIRED_TASK_TYPES",
            initialization_source,
        )
        self.assertIn(TYPE, prompt_bundles.BACKFILL_TASK_TYPES)
        self.assertFalse(required & set(prompt_bundles.BACKFILL_TASK_TYPES))

        bundles = [
            SimpleNamespace(
                task_type=task_type,
                contract_version=1,
                default_revision=1,
                guidance_defaults_json={"guidance": task_type},
            )
            for task_type in prompt_bundles.INITIAL_REQUIRED_TASK_TYPES
        ]
        seed = prompt_bundles.effective_prompt_seed(
            FakeSession(bundles=bundles),
            task_types=prompt_bundles.REGISTERED_TASK_TYPES,
            required_task_types=prompt_bundles.INITIAL_REQUIRED_TASK_TYPES,
        )
        self.assertEqual(set(seed), required)

        missing_original = [
            bundle
            for bundle in bundles
            if bundle.task_type != "daily_process_adapt"
        ]
        with self.assertRaises(LocalStorageError):
            prompt_bundles.effective_prompt_seed(
                FakeSession(bundles=missing_original),
                task_types=prompt_bundles.REGISTERED_TASK_TYPES,
                required_task_types=prompt_bundles.INITIAL_REQUIRED_TASK_TYPES,
            )

        with_reflection = bundles + [
            SimpleNamespace(
                task_type=TYPE,
                contract_version=1,
                default_revision=1,
                guidance_defaults_json={"reflection": "反思"},
            )
        ]
        optional = prompt_bundles.effective_prompt_seed(
            FakeSession(bundles=with_reflection),
            task_types=prompt_bundles.REGISTERED_TASK_TYPES,
            required_task_types=prompt_bundles.INITIAL_REQUIRED_TASK_TYPES,
        )
        self.assertIn(TYPE, optional)
        self.assertTrue(required <= set(optional))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
