"""Pure signed prompt-package tests (teacher feedback #6).

No SQLite, database connection, migration or real network is used here.  Edge
and UI checks live in their own probes; this file covers strict parsing,
Ed25519 trust, allowlisting/schema preservation, the file ledger and the
default-only personal-version advancement rule.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import inspect
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.local import (
    ai_task_service,
    api,
    app as local_app,
    listening_ai_inputs,
    observation_ai_service,
    profile_service,
    prompt_bundles,
    runtime as local_runtime,
    weekly_ai_contracts,
    weekly_ai_service,
)
from app.local.errors import LocalPromptContractRegression
from app.local.models import (
    LocalPersonalPromptHead,
    LocalPersonalPromptVersion,
    LocalPromptBundle,
)
from app.local.prompt_package import (
    MAX_PACKAGE_BYTES,
    PACKAGE_OPEN_GUIDANCE_FIELDS,
    PACKAGE_OPEN_TASK_TYPES,
    PACKAGE_TASK_TYPES,
    PackageTrust,
    PromptPackageError,
    materialize_bundle_rows,
    validate_against_existing_heads,
    verify_package,
)
from app.local.prompt_package_service import (
    PromptPackageNetworkError,
    PromptPackageService,
    fetch_signed_package,
)
from app.local.prompt_package_store import PromptPackageStore
from app.local.schemas import LocalPromptPackageStatusOut
from app.local.prompt_bundles import (
    GUIDANCE_FIELDS,
    PROMPT_BUNDLE_MANIFEST,
    canonical_json,
)


def _latest(task_type: str) -> dict:
    matches = [
        bundle
        for bundle in PROMPT_BUNDLE_MANIFEST
        if bundle["task_type"] == task_type
    ]
    return max(matches, key=lambda bundle: int(bundle["default_revision"]))


def _payload(*, bump: set[str] | None = None, suffix: str = "") -> dict:
    bump = bump or set()
    bundles = []
    for task_type in PACKAGE_TASK_TYPES:
        latest = _latest(task_type)
        guidance = dict(latest["guidance_defaults_json"])
        revision = int(latest["default_revision"])
        if task_type in bump:
            revision += 1
            first = next(iter(guidance))
            guidance[first] = guidance[first] + suffix
        bundles.append(
            {
                "task_type": task_type,
                "contract_version": int(latest["contract_version"]),
                "default_revision": revision,
                "guidance": guidance,
            }
        )
    return {"schema_version": 1, "bundles": bundles}


def _sign(private: Ed25519PrivateKey, document: dict) -> bytes:
    signed = dict(document)
    signed.pop("signature", None)
    signature = private.sign(canonical_json(signed).encode("utf-8"))
    document = dict(document)
    document["signature"] = base64.b64encode(signature).decode("ascii")
    return canonical_json(document).encode("utf-8")


def _package(
    private: Ed25519PrivateKey,
    *,
    sequence: int = 1,
    payload: dict | None = None,
    key_id: str = "test-key",
    min_client: str = "0.1.0",
    max_client: str = "0.1.99",
    notes: str = "合成测试包",
) -> bytes:
    payload = payload or _payload()
    payload_bytes = canonical_json(payload).encode("utf-8")
    document = {
        "format_version": 1,
        "release_sequence": sequence,
        "published_at": "2026-11-08T00:00:00Z",
        "min_client_version": min_client,
        "max_client_version": max_client,
        "notes": notes,
        "key_id": key_id,
        "payload_bytes": len(payload_bytes),
        "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
        "payload": payload,
    }
    return _sign(private, document)


def _trust(private: Ed25519PrivateKey, *, key_id: str = "test-key") -> PackageTrust:
    return PackageTrust(
        source_url="https://example.test/prompt-package.json",
        keys={key_id: private.public_key().public_bytes_raw()},
        client_version="0.1.0",
    )


def _replace_document(raw: bytes, **changes) -> bytes:
    document = json.loads(raw.decode("utf-8"))
    document.update(changes)
    return json.dumps(document, ensure_ascii=False).encode("utf-8")


class PackageVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.private = Ed25519PrivateKey.generate()
        self.trust = _trust(self.private)

    def test_valid_full_package_and_schema_preservation(self) -> None:
        raw = _package(self.private)
        package = verify_package(raw, self.trust)
        self.assertEqual(package.release_sequence, 1)
        self.assertEqual(
            [bundle.task_type for bundle in package.bundles],
            list(PACKAGE_TASK_TYPES),
        )
        rows = materialize_bundle_rows(package)
        self.assertEqual(len(rows), len(PACKAGE_TASK_TYPES))
        for row in rows:
            task = row["task_type"]
            source = _latest(task)
            self.assertEqual(row["input_schema_json"], source["input_schema_json"])
            self.assertEqual(row["output_schema_json"], source["output_schema_json"])
            self.assertEqual(
                set(row["guidance_defaults_json"]), set(GUIDANCE_FIELDS[task])
            )
            self.assertEqual(
                set(row),
                {
                    "task_type",
                    "contract_version",
                    "default_revision",
                    "input_schema_json",
                    "output_schema_json",
                    "guidance_defaults_json",
                    "bundle_hash",
                },
            )

    def test_weekly_structural_fields_never_come_from_the_package(self) -> None:
        payload = _payload()
        weekly = next(
            item for item in payload["bundles"]
            if item["task_type"] == "weekly_games_select"
        )
        weekly["input_schema_json"] = {"type": "object"}
        raw = _package(self.private, payload=payload)
        with self.assertRaises(PromptPackageError) as raised:
            verify_package(raw, self.trust)
        self.assertEqual(raised.exception.code, "PACKAGE_PAYLOAD_INVALID")

    def test_signature_key_and_tamper_are_refused(self) -> None:
        raw = _package(self.private)
        tampered = bytearray(raw)
        # Change the signature without changing the signed document.
        document = json.loads(raw.decode("utf-8"))
        signature = bytearray(base64.b64decode(document["signature"]))
        signature[0] ^= 1
        document["signature"] = base64.b64encode(bytes(signature)).decode("ascii")
        tampered = json.dumps(document, ensure_ascii=False).encode("utf-8")
        with self.assertRaises(PromptPackageError) as raised:
            verify_package(tampered, self.trust)
        self.assertEqual(raised.exception.code, "PACKAGE_SIGNATURE_INVALID")

        unknown = _package(self.private, key_id="unknown")
        with self.assertRaises(PromptPackageError) as raised:
            verify_package(unknown, self.trust)
        self.assertEqual(raised.exception.code, "PACKAGE_KEY_UNKNOWN")

    def test_duplicate_keys_and_non_finite_numbers_are_refused(self) -> None:
        raw = _package(self.private)
        text = raw.decode("utf-8")
        duplicate = text.replace(
            '"release_sequence":1',
            '"release_sequence":1,"release_sequence":2',
            1,
        )
        with self.assertRaises(PromptPackageError) as raised:
            verify_package(duplicate, self.trust)
        self.assertEqual(raised.exception.code, "PACKAGE_JSON_INVALID")

        nan = text.replace('"release_sequence":1', '"release_sequence":NaN', 1)
        with self.assertRaises(PromptPackageError) as raised:
            verify_package(nan, self.trust)
        self.assertEqual(raised.exception.code, "PACKAGE_JSON_INVALID")

    def test_payload_size_and_hash_are_checked(self) -> None:
        raw = _package(self.private)
        document = json.loads(raw.decode("utf-8"))
        document["payload_sha256"] = "0" * 64
        with self.assertRaises(PromptPackageError) as raised:
            verify_package(json.dumps(document, ensure_ascii=False), self.trust)
        self.assertEqual(raised.exception.code, "PACKAGE_PAYLOAD_INVALID")

        document = json.loads(raw.decode("utf-8"))
        document["payload_bytes"] += 1
        with self.assertRaises(PromptPackageError) as raised:
            verify_package(json.dumps(document, ensure_ascii=False), self.trust)
        self.assertEqual(raised.exception.code, "PACKAGE_PAYLOAD_INVALID")

        with self.assertRaises(PromptPackageError) as raised:
            verify_package(b"{" + b" " * MAX_PACKAGE_BYTES, self.trust)
        self.assertEqual(raised.exception.code, "PACKAGE_TOO_LARGE")

    def test_compatibility_and_allowlist(self) -> None:
        raw = _package(self.private, min_client="0.2.0", max_client="0.3.0")
        with self.assertRaises(PromptPackageError) as raised:
            verify_package(raw, self.trust)
        self.assertEqual(raised.exception.code, "PACKAGE_INCOMPATIBLE")

        payload = _payload()
        payload["bundles"].append(
            {
                "task_type": "daily_reflection_generate",
                "contract_version": 1,
                "default_revision": 1,
                "guidance": {"reflection": "x"},
            }
        )
        raw = _package(self.private, payload=payload)
        with self.assertRaises(PromptPackageError) as raised:
            verify_package(raw, self.trust)
        self.assertEqual(raised.exception.code, "PACKAGE_TASK_NOT_ALLOWED")

        payload = _payload()
        payload["bundles"] = payload["bundles"][:-1]
        raw = _package(self.private, payload=payload)
        with self.assertRaises(PromptPackageError) as raised:
            verify_package(raw, self.trust)
        self.assertEqual(raised.exception.code, "PACKAGE_INCOMPLETE")

    def test_weekly_fixed_metadata_is_never_package_owned(self) -> None:
        payload = _payload()
        habit = next(
            item
            for item in payload["bundles"]
            if item["task_type"] == "weekly_habit_culture"
        )
        habit["guidance"]["allowed_input_fields"] = "[]"
        raw = _package(self.private, payload=payload)
        with self.assertRaises(PromptPackageError) as raised:
            verify_package(raw, self.trust)
        self.assertEqual(raised.exception.code, "PACKAGE_STRUCTURE_IMMUTABLE")

        payload = _payload()
        games = next(
            item
            for item in payload["bundles"]
            if item["task_type"] == "weekly_games_select"
        )
        games["guidance"]["target"] = "changed"
        raw = _package(self.private, payload=payload)
        with self.assertRaises(PromptPackageError) as raised:
            verify_package(raw, self.trust)
        self.assertEqual(raised.exception.code, "PACKAGE_STRUCTURE_IMMUTABLE")

        payload = _payload()
        fixed = next(
            item
            for item in payload["bundles"]
            if item["task_type"] == "weekly_habit_culture"
        )
        declared = fixed["default_revision"] + 1
        fixed["default_revision"] = declared
        raw = _package(self.private, payload=payload)
        package = verify_package(raw, self.trust)
        row = next(
            item
            for item in materialize_bundle_rows(package)
            if item["task_type"] == "weekly_habit_culture"
        )
        builtin = _latest("weekly_habit_culture")
        self.assertEqual(
            row["default_revision"], builtin["default_revision"]
        )
        self.assertNotEqual(declared, row["default_revision"])

    def test_weekly_instructions_are_open_and_metadata_is_merged_locally(self) -> None:
        payload = _payload(bump={"weekly_games_select"}, suffix="")
        games = next(
            item
            for item in payload["bundles"]
            if item["task_type"] == "weekly_games_select"
        )
        games["guidance"] = {"instructions": "只输出合成测试说明。"}
        habit = next(
            item
            for item in payload["bundles"]
            if item["task_type"] == "weekly_habit_culture"
        )
        habit["guidance"] = {}
        raw = _package(self.private, payload=payload)
        package = verify_package(raw, self.trust)
        rows = materialize_bundle_rows(package)
        games_row = next(
            row for row in rows if row["task_type"] == "weekly_games_select"
        )
        habit_row = next(
            row for row in rows if row["task_type"] == "weekly_habit_culture"
        )
        local_games = _latest("weekly_games_select")["guidance_defaults_json"]
        local_habit = _latest("weekly_habit_culture")["guidance_defaults_json"]
        self.assertEqual(
            games_row["guidance_defaults_json"]["instructions"],
            "只输出合成测试说明。",
        )
        for key in ("target", "language", "strict_json", "no_fabricated_sources"):
            self.assertEqual(
                games_row["guidance_defaults_json"][key], local_games[key]
            )
        self.assertEqual(
            habit_row["guidance_defaults_json"]["allowed_input_fields"],
            local_habit["allowed_input_fields"],
        )

    def test_preview_client_identity_is_explicitly_compatible(self) -> None:
        raw = _package(self.private, min_client="0.1.0", max_client="0.2.0")
        preview = verify_package(
            raw,
            self.trust,
            client_version="0.1.0-listening-test.20261107",
        )
        self.assertEqual(preview.release_sequence, 1)
        with self.assertRaises(PromptPackageError) as raised:
            verify_package(
                raw,
                self.trust,
                client_version="0.3.0-listening-test.20261108",
            )
        self.assertEqual(raised.exception.code, "PACKAGE_INCOMPATIBLE")

    def test_lone_surrogate_has_stable_encoding_error(self) -> None:
        raw = _package(self.private)
        surrogate = raw.replace("合成测试包".encode("utf-8"), b"\\ud800")
        with self.assertRaises(PromptPackageError) as raised:
            verify_package(surrogate, self.trust)
        self.assertEqual(raised.exception.code, "PACKAGE_ENCODING")

    def test_contract_fields_and_text_limits(self) -> None:
        payload = _payload()
        payload["bundles"][0]["contract_version"] = 2
        raw = _package(self.private, payload=payload)
        with self.assertRaises(PromptPackageError) as raised:
            verify_package(raw, self.trust)
        self.assertEqual(raised.exception.code, "PACKAGE_CONTRACT_INCOMPATIBLE")

        payload = _payload()
        payload["bundles"][0]["guidance"]["extra"] = "x"
        raw = _package(self.private, payload=payload)
        with self.assertRaises(PromptPackageError) as raised:
            verify_package(raw, self.trust)
        self.assertEqual(raised.exception.code, "PACKAGE_GUIDANCE_FIELDS")

        payload = _payload()
        first = next(iter(payload["bundles"][0]["guidance"]))
        payload["bundles"][0]["guidance"][first] = "x" * 8001
        raw = _package(self.private, payload=payload)
        with self.assertRaises(PromptPackageError) as raised:
            verify_package(raw, self.trust)
        self.assertEqual(raised.exception.code, "PACKAGE_GUIDANCE_TOO_LONG")

    def test_default_revision_rollback_and_identity_conflict(self) -> None:
        payload = _payload()
        adapt = next(
            item for item in payload["bundles"]
            if item["task_type"] == "daily_process_adapt"
        )
        adapt["default_revision"] = 2
        raw = _package(self.private, payload=payload)
        with self.assertRaises(PromptPackageError) as raised:
            verify_package(raw, self.trust)
        self.assertEqual(raised.exception.code, "PACKAGE_DEFAULT_ROLLBACK")

        payload = _payload()
        split = next(
            item for item in payload["bundles"]
            if item["task_type"] == "daily_lesson_split"
        )
        split["guidance"][next(iter(split["guidance"]))] += "改动"
        raw = _package(self.private, payload=payload)
        with self.assertRaises(PromptPackageError) as raised:
            verify_package(raw, self.trust)
        self.assertEqual(raised.exception.code, "PACKAGE_IDENTITY_CONFLICT")

    def test_local_newer_default_or_contract_is_refused(self) -> None:
        package = verify_package(
            _package(
                self.private,
                payload=_payload(
                    bump={"daily_lesson_split"}, suffix="包内新文字"
                ),
            ),
            self.trust,
        )
        item = next(
            bundle
            for bundle in package.bundles
            if bundle.task_type == "daily_lesson_split"
        )
        validate_against_existing_heads(
            package,
            [("daily_lesson_split", item.contract_version, item.default_revision)],
        )
        with self.assertRaises(PromptPackageError) as raised:
            validate_against_existing_heads(
                package,
                [
                    (
                        "daily_lesson_split",
                        item.contract_version,
                        item.default_revision + 1,
                    )
                ],
            )
        self.assertEqual(raised.exception.code, "PACKAGE_DEFAULT_ROLLBACK")
        with self.assertRaises(PromptPackageError) as raised:
            validate_against_existing_heads(
                package,
                [
                    (
                        "daily_lesson_split",
                        item.contract_version + 1,
                        item.default_revision,
                    )
                ],
            )
        self.assertEqual(raised.exception.code, "PACKAGE_CONTRACT_INCOMPATIBLE")

    def test_allowlist_excludes_tasks_not_opened_for_this_release(self) -> None:
        for task_type in PACKAGE_TASK_TYPES:
            self.assertIn(task_type, prompt_bundles.REGISTERED_TASK_TYPES)
            self.assertIn(task_type, GUIDANCE_FIELDS)
        for task_type in (
            "daily_reflection_generate",
            "listening_group_notes",
            "listening_goal_suggest",
            "class_game_config_extract",
        ):
            self.assertNotIn(task_type, PACKAGE_TASK_TYPES)
        for task_type in (
            "weekly_key_week_focus",
            "weekly_environment_setup",
            "weekly_habit_culture",
            "weekly_home_cooperation",
        ):
            self.assertEqual(PACKAGE_OPEN_GUIDANCE_FIELDS[task_type], ())
        self.assertEqual(
            PACKAGE_OPEN_GUIDANCE_FIELDS["weekly_games_select"],
            ("instructions",),
        )
        self.assertEqual(
            PACKAGE_OPEN_GUIDANCE_FIELDS["weekly_materials_generate"],
            ("instructions",),
        )
        self.assertEqual(len(PACKAGE_OPEN_TASK_TYPES), 9)
        self.assertNotIn("weekly_habit_culture", PACKAGE_OPEN_TASK_TYPES)
        self.assertNotIn("weekly_key_week_focus", PACKAGE_OPEN_TASK_TYPES)


class FixedSourceTests(unittest.TestCase):
    def test_fixed_source_requires_https_and_trust(self) -> None:
        key = Ed25519PrivateKey.generate().public_key().public_bytes_raw()
        with self.assertRaises(PromptPackageNetworkError) as raised:
            fetch_signed_package(PackageTrust(None, {}))
        self.assertEqual(raised.exception.code, "PACKAGE_SOURCE_UNCONFIGURED")

        with self.assertRaises(PromptPackageNetworkError) as raised:
            fetch_signed_package(
                PackageTrust("http://example.test/package.json", {"k": key})
            )
        self.assertEqual(raised.exception.code, "PACKAGE_SOURCE_INVALID")

        with self.assertRaises(PromptPackageNetworkError) as raised:
            fetch_signed_package(
                PackageTrust("https://user:pw@example.test/package.json", {"k": key})
            )
        self.assertEqual(raised.exception.code, "PACKAGE_SOURCE_INVALID")


class _FakeRuntime:
    def __init__(self, root: Path):
        self.data_dir = root
        self.prompt_sync_error = None

    def session(self):
        raise AssertionError("pure package test must not open a database session")


class _Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 11, 8, 0, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


class PromptPackageServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.private = Ed25519PrivateKey.generate()
        self.trust = _trust(self.private)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.clock = _Clock()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _service(
        self,
        raw,
        *,
        apply_calls=None,
        fetch_calls=None,
        fallback_calls=None,
        fail=None,
        trust=None,
    ):
        def fetcher(_trust):
            if fetch_calls is not None:
                fetch_calls.append(1)
            if isinstance(raw, Exception):
                raise raw
            return raw

        def apply(_package):
            if apply_calls is not None:
                apply_calls.append(_package.release_sequence)
            if fail is not None:
                raise fail

        fallback = None
        if fallback_calls is not None:
            fallback = lambda reason: fallback_calls.append(reason)
        return PromptPackageService(
            _FakeRuntime(self.root),
            trust=trust or self.trust,
            store=PromptPackageStore(self.root),
            fetcher=fetcher,
            apply_func=apply,
            fallback_func=fallback,
            now=self.clock.now,
        )

    def test_unconfigured_is_zero_network_and_builtin(self) -> None:
        calls: list[int] = []
        fallback: list[str] = []

        def apply(_package):
            calls.append(1)

        service = PromptPackageService(
            _FakeRuntime(self.root),
            trust=PackageTrust(source_url=None, keys={}, client_version="0.1.0"),
            store=PromptPackageStore(self.root),
            fetcher=lambda _trust: (_ for _ in ()).throw(
                AssertionError("unconfigured must not fetch")
            ),
            apply_func=apply,
            fallback_func=lambda reason: fallback.append(reason),
            now=self.clock.now,
        )
        status = service.check(manual=True)
        self.assertFalse(status["configured"])
        self.assertEqual(status["state"], "unconfigured")
        self.assertEqual(status["active_source"], "builtin")
        self.assertEqual(len(status["allowed_tasks"]), 9)
        self.assertNotIn("weekly_habit_culture", status["allowed_tasks"])
        self.assertEqual(calls, [])
        self.assertEqual(fallback, ["unconfigured"])
        self.assertTrue(service.runtime.prompt_package_builtin_only)
        service.start_background_check()
        self.assertEqual(calls, [])

    def test_enable_restart_offline_and_failure_keep_active(self) -> None:
        raw = _package(self.private)
        calls: list[int] = []
        service = self._service(raw, apply_calls=calls)
        status = service.check(manual=True)
        self.assertEqual(status["state"], "updated")
        self.assertEqual(status["release_sequence"], 1)
        self.assertEqual(calls, [1])
        self.assertFalse(service.runtime.prompt_package_builtin_only)
        LocalPromptPackageStatusOut.model_validate(status)
        state = service.store.read_state()
        self.assertEqual(state["accepted"]["release_sequence"], 1)

        # A restart re-verifies and re-applies the active cache.
        restart_calls: list[int] = []
        restarted = self._service(raw, apply_calls=restart_calls)
        restarted.startup()
        self.assertEqual(restart_calls, [1])
        self.assertEqual(restarted.status()["active_source"], "package")

        # Offline and invalid packages leave the active package untouched.
        offline = PromptPackageService(
            _FakeRuntime(self.root),
            trust=self.trust,
            store=PromptPackageStore(self.root),
            fetcher=lambda _trust: (_ for _ in ()).throw(
                PromptPackageNetworkError("PACKAGE_OFFLINE", "断网")
            ),
            apply_func=lambda _package: calls.append(99),
            now=self.clock.now,
        )
        status = offline.check(manual=True)
        self.assertEqual(status["state"], "offline")
        self.assertEqual(status["release_sequence"], 1)
        self.assertEqual(calls, [1])

        broken = bytearray(raw)
        broken[-2] ^= 1
        service_broken = self._service(bytes(broken))
        status = service_broken.check(manual=True)
        self.assertIn(status["state"], {"invalid", "offline"})
        self.assertEqual(status["release_sequence"], 1)

    def test_old_sequence_and_same_sequence_conflict_are_refused(self) -> None:
        raw2 = _package(self.private, sequence=2, payload=_payload(bump={"daily_lesson_split"}, suffix="二"))
        service = self._service(raw2)
        self.assertEqual(service.check(manual=True)["state"], "updated")

        raw1 = _package(self.private, sequence=1, payload=_payload(bump={"daily_lesson_split"}, suffix="一"))
        old = self._service(raw1)
        status = old.check(manual=True)
        self.assertEqual(status["state"], "rollback_rejected")
        self.assertEqual(status["release_sequence"], 2)

        different = _package(
            self.private,
            sequence=2,
            payload=_payload(bump={"daily_lesson_split"}, suffix="不同"),
        )
        conflict = self._service(different)
        status = conflict.check(manual=True)
        self.assertEqual(status["state"], "sequence_conflict")
        self.assertEqual(status["release_sequence"], 2)

        same = self._service(raw2)
        status = same.check(manual=True)
        self.assertEqual(status["state"], "no_update")

        # A new release sequence may not reuse the same single-item identity
        # with different guidance; it must bump default_revision.
        same_identity_different_text = _package(
            self.private,
            sequence=3,
            payload=_payload(bump={"daily_lesson_split"}, suffix="再不同"),
        )
        identity = self._service(same_identity_different_text)
        status = identity.check(manual=True)
        self.assertEqual(status["state"], "rejected")
        self.assertEqual(status["release_sequence"], 2)

    def test_accepted_sequence_survives_missing_active_cache(self) -> None:
        raw2 = _package(
            self.private,
            sequence=2,
            payload=_payload(bump={"daily_lesson_split"}, suffix="二"),
        )
        service = self._service(raw2)
        self.assertEqual(service.check(manual=True)["state"], "updated")
        service.store.active_path.unlink()

        fallback: list[str] = []
        missing = self._service(
            raw2, fallback_calls=fallback
        )
        missing.startup()
        self.assertEqual(len(fallback), 1)

        raw1 = _package(
            self.private,
            sequence=1,
            payload=_payload(bump={"daily_lesson_split"}, suffix="一"),
        )
        old = self._service(raw1)
        status = old.check(manual=True)
        self.assertEqual(status["state"], "rollback_rejected")
        self.assertEqual(status["release_sequence"], 2)
        self.assertEqual(
            old.store.read_state()["accepted"]["release_sequence"], 2
        )

    def test_tampered_active_cache_is_not_reapplied(self) -> None:
        raw = _package(self.private)
        service = self._service(raw)
        self.assertEqual(service.check(manual=True)["state"], "updated")
        active_path = service.store.active_path
        tampered = bytearray(active_path.read_bytes())
        tampered[-2] ^= 1
        active_path.write_bytes(bytes(tampered))

        calls: list[int] = []
        restarted = self._service(raw, apply_calls=calls)
        restarted.startup()
        self.assertEqual(calls, [])
        self.assertEqual(restarted.status()["state"], "cache_invalid")
        self.assertEqual(
            restarted.store.read_state()["accepted"]["release_sequence"], 1
        )

    def test_permanent_bundle_conflict_clears_pending(self) -> None:
        raw = _package(self.private)
        rejected = self._service(
            raw,
            fail=LocalPromptContractRegression(details={"task_type": "synthetic"}),
        )
        status = rejected.check(manual=True)
        self.assertEqual(status["state"], "rejected")
        self.assertEqual(status["active_source"], "builtin")
        self.assertIsNone(rejected.store.read_state()["pending"])

    def test_startup_reapply_does_not_spend_the_network_check_window(self) -> None:
        raw3 = _package(
            self.private,
            sequence=3,
            payload=_payload(bump={"daily_lesson_split"}, suffix="三"),
        )
        payload4 = _payload(bump={"daily_lesson_split"}, suffix="四")
        next(
            item
            for item in payload4["bundles"]
            if item["task_type"] == "daily_lesson_split"
        )["default_revision"] = 4
        raw4 = _package(self.private, sequence=4, payload=payload4)
        fetched: list[str] = []
        source = [raw3]
        calls: list[int] = []

        def fetcher(_trust):
            fetched.append(self.clock.now().isoformat())
            return source[0]

        def apply(package):
            calls.append(package.release_sequence)

        first = PromptPackageService(
            _FakeRuntime(self.root),
            trust=self.trust,
            store=PromptPackageStore(self.root),
            fetcher=fetcher,
            apply_func=apply,
            now=self.clock.now,
        )
        self.assertEqual(first.check(manual=True)["state"], "updated")
        checked_at = first.status()["last_checked_at"]
        self.assertIsNotNone(checked_at)

        self.clock.advance(2 * 24 * 60 * 60)
        source[0] = raw4
        resumed = PromptPackageService(
            _FakeRuntime(self.root),
            trust=self.trust,
            store=PromptPackageStore(self.root),
            fetcher=fetcher,
            apply_func=apply,
            now=self.clock.now,
        )
        resumed.startup()
        self.assertEqual(resumed.status()["last_checked_at"], checked_at)
        result = resumed.check(manual=False)
        self.assertEqual(result["release_sequence"], 4)
        self.assertEqual(result["state"], "updated")
        self.assertEqual(len(fetched), 2)
        self.assertEqual(calls, [3, 3, 4])

    def test_manual_same_package_reapplies_after_failed_startup(self) -> None:
        raw3 = _package(
            self.private,
            sequence=3,
            payload=_payload(bump={"daily_lesson_split"}, suffix="三"),
        )
        calls: list[int] = []
        first = self._service(raw3, apply_calls=calls)
        self.assertEqual(first.check(manual=True)["state"], "updated")
        self.assertEqual(calls, [3])

        blocked = [True]

        def apply(package):
            if blocked[0]:
                raise RuntimeError("synthetic restore application refused")
            calls.append(package.release_sequence)

        resumed = PromptPackageService(
            _FakeRuntime(self.root),
            trust=self.trust,
            store=PromptPackageStore(self.root),
            fetcher=lambda _trust: raw3,
            apply_func=apply,
            now=self.clock.now,
        )
        resumed.startup()
        self.assertEqual(resumed.status()["state"], "failed")
        blocked[0] = False
        result = resumed.check(manual=True)
        self.assertEqual(result["state"], "no_update")
        self.assertEqual(calls, [3, 3])
        self.assertEqual(
            result["message"], "已用同一受信包修复本地缓存 r3。"
        )

    def test_corrupt_active_falls_back_and_same_package_repairs(self) -> None:
        raw3 = _package(
            self.private,
            sequence=3,
            payload=_payload(bump={"daily_lesson_split"}, suffix="三"),
        )
        calls: list[int] = []
        first = self._service(raw3, apply_calls=calls)
        self.assertEqual(first.check(manual=True)["state"], "updated")
        original = first.store.active_path.read_bytes()
        first.store.active_path.write_bytes(b'{"synthetic-corrupt":true}')

        fallback: list[str] = []
        restarted = self._service(
            raw3, apply_calls=calls, fallback_calls=fallback
        )
        restarted.startup()
        status = restarted.status()
        self.assertEqual(status["active_source"], "builtin")
        self.assertEqual(status["state"], "cache_invalid")
        self.assertEqual(len(fallback), 1)
        self.assertTrue(restarted.runtime.prompt_package_builtin_only)
        repaired = restarted.check(manual=True)
        self.assertEqual(repaired["state"], "no_update")
        self.assertEqual(repaired["active_source"], "package")
        self.assertFalse(restarted.runtime.prompt_package_builtin_only)
        self.assertEqual(restarted.store.active_path.read_bytes(), original)
        self.assertEqual(calls, [3, 3])
        self.assertEqual(len(fallback), 1)

    def test_startup_rejects_same_sequence_but_different_signed_content(self) -> None:
        raw3 = _package(
            self.private,
            sequence=3,
            payload=_payload(bump={"daily_lesson_split"}, suffix="三"),
        )
        calls: list[int] = []
        service = self._service(raw3, apply_calls=calls)
        self.assertEqual(service.check(manual=True)["state"], "updated")
        accepted = service.store.read_state()["accepted"]

        other3 = _package(
            self.private,
            sequence=3,
            payload=_payload(bump={"daily_lesson_split"}, suffix="另一"),
        )
        service.store.active_path.write_bytes(other3)
        service.startup()
        after = service.store.read_state()["accepted"]
        self.assertEqual(after["content_sha256"], accepted["content_sha256"])
        self.assertEqual(calls, [3])
        self.assertEqual(service.status()["state"], "sequence_conflict")

    def test_bad_pending_falls_back_to_valid_active(self) -> None:
        raw3 = _package(
            self.private,
            sequence=3,
            payload=_payload(bump={"daily_lesson_split"}, suffix="三"),
        )
        raw4 = _package(
            self.private,
            sequence=4,
            payload=_payload(bump={"daily_lesson_split"}, suffix="四"),
        )
        calls: list[int] = []
        fallback: list[str] = []
        service = self._service(
            raw3, apply_calls=calls, fallback_calls=fallback
        )
        self.assertEqual(service.check(manual=True)["state"], "updated")
        service.store.stage_pending(raw4, verify_package(raw4, self.trust))
        service.store.pending_path.write_bytes(b'{"synthetic-corrupt":true}')

        service.startup()
        self.assertEqual(calls, [3, 3])
        self.assertIsNone(service.store.read_state()["pending"])
        self.assertEqual(service.status()["release_sequence"], 3)
        self.assertEqual(fallback, [])

    def test_interrupted_apply_keeps_pending_and_restart_resumes(self) -> None:
        raw = _package(self.private)
        failing = self._service(raw, fail=RuntimeError("synthetic disk interruption"))
        status = failing.check(manual=True)
        self.assertEqual(status["state"], "failed")
        self.assertEqual(status["active_source"], "builtin")
        self.assertIsNotNone(failing.store.read_state()["pending"])

        calls: list[int] = []
        resumed = self._service(raw, apply_calls=calls)
        resumed.startup()
        self.assertEqual(calls, [1])
        self.assertEqual(resumed.status()["active_source"], "package")
        self.assertIsNone(resumed.store.read_state()["pending"])

    def test_background_check_is_rate_limited(self) -> None:
        raw = _package(self.private)
        calls: list[int] = []
        fetches: list[int] = []
        service = self._service(raw, apply_calls=calls, fetch_calls=fetches)
        self.assertEqual(service.check(manual=True)["state"], "updated")
        self.assertEqual(len(fetches), 1)

        # Within the interval the background entry performs no fetch/apply.
        before = list(calls)
        self.clock.advance(60 * 60)
        service.check(manual=False)
        self.assertEqual(calls, before)
        self.assertEqual(len(fetches), 1)

        # A manual check is always allowed, even for the same package.
        status = service.check(manual=True)
        self.assertEqual(status["state"], "no_update")
        self.assertEqual(len(fetches), 2)
        self.assertEqual(calls, [1])


class _FakeSession:
    def __init__(self) -> None:
        self.rows: dict[tuple[type, object], object] = {}
        self.added: list[object] = []
        self.committed = False

    def get(self, model, key):
        return self.rows.get((model, key))

    def add(self, value) -> None:
        self.added.append(value)
        if isinstance(value, LocalPersonalPromptVersion):
            key = (value.profile_id, value.task_type, value.revision)
            self.rows[(LocalPersonalPromptVersion, key)] = value

    def commit(self) -> None:
        self.committed = True


def _bundle(task: str, default: int, guidance: dict, contract: int = 1):
    return LocalPromptBundle(
        task_type=task,
        contract_version=contract,
        default_revision=default,
        input_schema_json={},
        output_schema_json={},
        guidance_defaults_json=guidance,
        bundle_hash="a" * 64,
        created_at=datetime(2026, 1, 1),
    )


def _head(profile: str, task: str, revision: int = 1, required: int = 1, latest: int = 2):
    return LocalPersonalPromptHead(
        profile_id=profile,
        task_type=task,
        current_revision=revision,
        required_contract_version=required,
        latest_default_revision=latest,
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )


def _version(
    profile: str,
    task: str,
    *,
    action: str = "initial",
    based: int = 1,
    contract: int = 1,
    guidance: dict | None = None,
    rejected: int | None = None,
    revision: int = 1,
):
    return LocalPersonalPromptVersion(
        profile_id=profile,
        task_type=task,
        revision=revision,
        contract_version=contract,
        based_default_revision=based,
        guidance_json=guidance or {"a": "old"},
        orphaned_guidance_json=None,
        action=action,
        rejected_default_revision=rejected,
        created_at=datetime(2026, 1, 1),
    )


class InitialSeedFallbackTests(unittest.TestCase):
    def test_new_profile_uses_builtin_when_cache_is_unavailable(self) -> None:
        task = "daily_lesson_split"
        session = _FakeSession()
        session.rows[
            (LocalPromptBundle, (task, 1, 2))
        ] = _bundle(task, 2, {"theme": "builtin"})
        session.rows[
            (LocalPromptBundle, (task, 1, 3))
        ] = _bundle(task, 3, {"theme": "remote"})
        seed = prompt_bundles.effective_prompt_seed(
            session,
            task_types=(task,),
            required_task_types=(task,),
            builtin_only=True,
        )
        self.assertEqual(seed[task]["default_revision"], 2)
        self.assertEqual(seed[task]["guidance"], {"theme": "builtin"})


class BuiltinFallbackTests(unittest.TestCase):
    def _run(self, version, *, head_required=1):
        task = "daily_lesson_split"
        session = _FakeSession()
        head = _head(
            "p1", task, revision=1, required=head_required, latest=4
        )
        session.rows[(LocalPersonalPromptHead, ("p1", task))] = head
        session.rows[
            (LocalPersonalPromptVersion, ("p1", task, 1))
        ] = version
        session.rows[
            (LocalPromptBundle, (task, 1, 2))
        ] = _bundle(task, 2, {"a": "builtin"})
        session.rows[
            (LocalPromptBundle, (task, 1, 4))
        ] = _bundle(task, 4, {"a": "remote"})
        with (
            patch.object(prompt_bundles, "begin_immediate", lambda _s: None),
            patch.object(prompt_bundles, "rollback", lambda _s: None),
        ):
            reverted = prompt_bundles.revert_default_only_to_builtin(
                session,
                task_types=(task,),
                profile_ids=["p1"],
                now=datetime(2026, 1, 2),
            )
        return reverted, head, session

    def test_pure_default_head_returns_to_builtin_without_losing_history(self) -> None:
        reverted, head, session = self._run(
            _version(
                "p1",
                "daily_lesson_split",
                action="initial",
                based=4,
                guidance={"a": "remote"},
            )
        )
        self.assertEqual(reverted, 1)
        self.assertEqual(head.current_revision, 2)
        self.assertEqual(head.latest_default_revision, 2)
        added = [
            item
            for item in session.added
            if isinstance(item, LocalPersonalPromptVersion)
        ]
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0].based_default_revision, 2)
        self.assertEqual(added[0].guidance_json, {"a": "builtin"})
        self.assertEqual(added[0].action, "initial")
        self.assertIsNotNone(
            session.rows[
                (LocalPersonalPromptVersion, ("p1", "daily_lesson_split", 1))
            ],
            "historical remote version is retained",
        )
        self.assertNotIn(
            "LocalAIExecution",
            inspect.getsource(prompt_bundles.revert_default_only_to_builtin),
            "fallback never rewrites an in-flight execution pin",
        )
        with (
            patch.object(prompt_bundles, "begin_immediate", lambda _s: None),
            patch.object(prompt_bundles, "rollback", lambda _s: None),
        ):
            self.assertEqual(
                prompt_bundles.revert_default_only_to_builtin(
                    session,
                    task_types=("daily_lesson_split",),
                    profile_ids=["p1"],
                ),
                0,
            )

    def test_explicit_personal_text_and_actions_are_not_rewritten(self) -> None:
        for action in ("edit", "accept", "reject", "adapt"):
            with self.subTest(action=action):
                reverted, head, session = self._run(
                    _version(
                        "p1",
                        "daily_lesson_split",
                        action=action,
                        based=4,
                        guidance={"a": "remote"},
                    )
                )
                self.assertEqual(reverted, 1)
                self.assertEqual(head.current_revision, 1)
                self.assertEqual(head.latest_default_revision, 2)
                self.assertEqual(session.added, [])

        reverted, head, session = self._run(
            _version(
                "p1",
                "daily_lesson_split",
                action="initial",
                based=4,
                guidance={"a": "teacher text"},
            )
        )
        self.assertEqual(reverted, 1)
        self.assertEqual(head.current_revision, 1)
        self.assertEqual(head.latest_default_revision, 2)
        self.assertEqual(session.added, [])

        reverted, head, session = self._run(
            _version(
                "p1",
                "daily_lesson_split",
                action="initial",
                based=4,
                guidance={"a": "remote"},
            ),
            head_required=2,
        )
        self.assertEqual(reverted, 0)
        self.assertEqual(head.current_revision, 1)
        self.assertEqual(head.latest_default_revision, 4)


class HeadTargetDecisionTests(unittest.TestCase):
    def test_builtin_sync_keeps_a_later_package_default(self) -> None:
        self.assertEqual(
            prompt_bundles._head_target_decision(
                "daily_lesson_split", 1, 3, 1, 2
            ),
            "keep",
        )
        self.assertEqual(
            prompt_bundles._head_target_decision(
                "daily_lesson_split", 1, 2, 1, 3
            ),
            "update",
        )
        self.assertEqual(
            prompt_bundles._head_target_decision(
                "daily_lesson_split", 1, 2, 1, 2
            ),
            "same",
        )
        with self.assertRaises(LocalPromptContractRegression):
            prompt_bundles._head_target_decision(
                "daily_lesson_split", 2, 1, 1, 2
            )
        sync_source = inspect.getsource(prompt_bundles.sync_prompt_bundles)
        self.assertIn("_head_target_decision(", sync_source)
        self.assertIn('if decision == "keep":', sync_source)


class DefaultOnlyAdvanceTests(unittest.TestCase):
    def _run(self, version, task="daily_lesson_split", target_default=2, target_contract=1):
        session = _FakeSession()
        head = _head("p1", task)
        session.rows[(LocalPersonalPromptHead, ("p1", task))] = head
        session.rows[
            (LocalPersonalPromptVersion, ("p1", task, 1))
        ] = version
        session.rows[
            (LocalPromptBundle, (task, target_contract, 1))
        ] = _bundle(task, 1, {"a": "old"})
        session.rows[
            (LocalPromptBundle, (task, target_contract, target_default))
        ] = _bundle(task, target_default, {"a": "new"})
        prompt_bundles._auto_advance_default_only(
            session,
            {
                task: {
                    "required_contract_version": target_contract,
                    "latest_default_revision": target_default,
                }
            },
            profile_ids=["p1"],
            now=datetime(2026, 1, 2),
        )
        return head, session

    def test_untouched_initial_default_advances(self) -> None:
        head, session = self._run(_version("p1", "daily_lesson_split"))
        self.assertEqual(head.current_revision, 2)
        added = [
            item
            for item in session.added
            if isinstance(item, LocalPersonalPromptVersion)
        ]
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0].revision, 2)
        self.assertEqual(added[0].based_default_revision, 2)
        self.assertEqual(added[0].action, "initial")
        self.assertEqual(added[0].guidance_json, {"a": "new"})

    def test_explicit_personal_actions_and_text_are_preserved(self) -> None:
        for action in ("edit", "accept", "reject", "adapt"):
            with self.subTest(action=action):
                head, session = self._run(
                    _version("p1", "daily_lesson_split", action=action)
                )
                self.assertEqual(head.current_revision, 1)
                self.assertEqual(session.added, [])

        head, session = self._run(
            _version(
                "p1",
                "daily_lesson_split",
                guidance={"a": "teacher text"},
            )
        )
        self.assertEqual(head.current_revision, 1)
        self.assertEqual(session.added, [])

        head, session = self._run(
            _version("p1", "daily_lesson_split", rejected=1)
        )
        self.assertEqual(head.current_revision, 1)
        self.assertEqual(session.added, [])

    def test_contract_or_revision_mismatch_does_not_advance(self) -> None:
        head, session = self._run(
            _version("p1", "daily_lesson_split", contract=2),
            target_contract=1,
        )
        self.assertEqual(head.current_revision, 1)
        self.assertEqual(session.added, [])

        head, session = self._run(
            _version("p1", "daily_lesson_split", based=2),
            target_default=2,
        )
        self.assertEqual(head.current_revision, 1)
        self.assertEqual(session.added, [])


class DesktopStartupOrderTests(unittest.TestCase):
    def test_prompt_package_initializes_before_executor_in_both_paths(self) -> None:
        root = Path(__file__).resolve().parents[3]
        tree = ast.parse((root / "desktop/d1_main.py").read_text(encoding="utf-8"))
        checked = 0
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            names = {}
            for call in ast.walk(node):
                if not isinstance(call, ast.Call):
                    continue
                name = getattr(call.func, "id", None)
                if name:
                    names.setdefault(name, []).append(call.lineno)
            if "_start_ai_executor" not in names:
                continue
            self.assertIn("initialize_prompt_package", names)
            self.assertIn("_prompt_package_client_version", names)
            self.assertLess(
                min(names["_prompt_package_client_version"]),
                min(names["initialize_prompt_package"]),
            )
            self.assertLess(
                min(names["initialize_prompt_package"]),
                min(names["_start_ai_executor"]),
            )
            checked += 1
        self.assertGreaterEqual(
            checked, 2, "normal and reopen startup paths are checked"
        )
        server = (root / "desktop/d1_server.py").read_text(encoding="utf-8")
        self.assertIn("prompt_package_client_version", server)
        self.assertIn(
            "prompt_package_client_version=prompt_package_client_version",
            server,
        )
        main = (root / "desktop/d1_main.py").read_text(encoding="utf-8")
        self.assertEqual(
            main.count("prompt_package_client_version=prompt_version"), 2
        )
        initialize_route = inspect.getsource(api.initialize)
        self.assertIn("prompt_package_builtin_only", initialize_route)
        self.assertIn(
            "prompt_package_builtin_only",
            inspect.getsource(profile_service.initialize),
        )

    def test_initialize_is_idempotent_and_captures_actual_version(self) -> None:
        events: list[tuple[str, str | None]] = []

        class FakeService:
            instances: list["FakeService"] = []

            def __init__(self, runtime, *, client_version=None):
                self.runtime = runtime
                self.client_version = client_version
                self.startup_calls = 0
                FakeService.instances.append(self)

            def startup(self):
                self.startup_calls += 1
                events.append(("package-startup", self.client_version))

        runtime = SimpleNamespace()
        version = "0.1.0-listening-test.20261108"
        with patch(
            "app.local.prompt_package_service.PromptPackageService",
            FakeService,
        ):
            first = local_app.initialize_prompt_package(
                runtime, client_version=version
            )
            second = local_app.initialize_prompt_package(
                runtime, client_version=version
            )
            events.append(("executor-start", version))
        self.assertIs(first, second)
        self.assertEqual(first.client_version, version)
        self.assertEqual(first.startup_calls, 1)
        self.assertIs(runtime.prompt_package_service, first)
        self.assertIs(runtime.prompt_package_restore_hook.__self__, first)
        self.assertEqual(
            events,
            [("package-startup", version), ("executor-start", version)],
        )


class ApiSurfaceTests(unittest.TestCase):
    def test_status_and_manual_check_routes_exist(self) -> None:
        paths = {route.path for route in api.local_router.routes}
        self.assertIn("/api/local/ai/prompt-package", paths)
        self.assertIn("/api/local/ai/prompt-package/check", paths)
        self.assertIn(
            "request", inspect.signature(api.initialize).parameters
        )


class GuidanceConsumptionSourceTests(unittest.TestCase):
    def test_each_allowlisted_task_family_reads_personal_guidance(self) -> None:
        daily_source = inspect.getsource(ai_task_service._load_material)
        self.assertIn("guidance = dict(version.guidance_json or {})", daily_source)
        self.assertIn("_render_system_text(", daily_source)

        observation_source = inspect.getsource(
            observation_ai_service.load_observation_material
        )
        self.assertIn(
            "guidance = dict(version.guidance_json or {})", observation_source
        )
        self.assertIn("_render_system_text(", observation_source)

        weekly_source = inspect.getsource(weekly_ai_service)
        self.assertIn("guidance=dict(version.guidance_json or {})", weekly_source)
        self.assertEqual(
            set(weekly_ai_contracts.TASK_TARGETS),
            {
                "weekly_games_select",
                "weekly_key_week_focus",
                "weekly_environment_setup",
                "weekly_habit_culture",
                "weekly_home_cooperation",
                "weekly_materials_generate",
            },
        )

        listening_source = inspect.getsource(listening_ai_inputs.load_material)
        self.assertIn(
            "guidance = dict(version.guidance_json or {})", listening_source
        )
        self.assertIn("_render_system_text(", listening_source)


class ExecutionPinSourceTests(unittest.TestCase):
    def test_enable_reuses_bundle_sync_and_auto_advances_only_defaults(self) -> None:
        source = inspect.getsource(PromptPackageService._apply)
        self.assertIn("materialize_bundle_rows(package)", source)
        self.assertIn("sync_prompt_bundles(", source)
        self.assertIn("auto_advance_defaults=True", source)

    def test_restore_rechecks_the_verified_cache_hook(self) -> None:
        reopen = inspect.getsource(
            local_runtime.LocalRuntime.reopen_after_restore
        )
        self.assertIn("prompt_package_restore_hook", reopen)
        initializer = inspect.getsource(
            local_app.initialize_prompt_package
        )
        self.assertIn("prompt_package_restore_hook = service.startup", initializer)
        factory = inspect.getsource(local_app.create_local_app)
        self.assertIn("initialize_prompt_package(", factory)
        self.assertIn("prompt_package_client_version", factory)
        self.assertIn(
            "client_version=prompt_package_client_version", factory
        )
        fallback = inspect.getsource(
            PromptPackageService._ensure_builtin_fallback
        )
        self.assertIn("revert_default_only_to_builtin", fallback)
        self.assertIn("PACKAGE_TASK_TYPES", fallback)

    def test_claim_pins_the_personal_and_default_revision(self) -> None:
        pick_source = inspect.getsource(ai_task_service._pick_candidate)
        claim_source = inspect.getsource(ai_task_service.claim_next)
        self.assertIn("default_revision=version.based_default_revision", pick_source)
        self.assertIn("personal_revision=version.revision", pick_source)
        self.assertIn("default_revision=execution.default_revision", pick_source)
        self.assertIn("personal_revision=execution.personal_revision", pick_source)
        self.assertIn("personal_revision=pick.personal_revision", claim_source)
        self.assertIn("default_revision=pick.default_revision", claim_source)


if __name__ == "__main__":
    unittest.main()
