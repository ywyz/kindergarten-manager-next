"""Prompt-release service, wire-contract and MySQL integration tests.

The local suite uses only an in-memory SQLite schema and synthetic Ed25519
material in a temporary directory.  The opt-in MySQL class runs after
0001-0005 have been applied to an explicit ``KGM_COLLAB_TEST_DATABASE_URL``;
it never creates a database, applies a migration or touches a real secret.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, event, func, inspect, select
from sqlalchemy.dialects.mysql import dialect as mysql_dialect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable

from app.collaboration import admin_api
from app.collaboration.admin_service import AdminPrincipal
from app.collaboration.api import get_session
from app.collaboration.app import create_collaboration_app
from app.collaboration.config import CollaborationSettings
from app.collaboration.db import create_collaboration_engine
from app.collaboration.errors import CollaborationError
from app.collaboration.prompt_release_models import (
    PromptRelease,
    PromptReleaseDraft,
    PromptReleaseState,
)
from app.collaboration.prompt_release_service import (
    ENV_KEY_ID,
    ENV_PACKAGE_DIR,
    ENV_SIGNING_KEY_FILE,
    MANIFEST_NAME,
    MAX_NOTES_CHARS,
    PromptReleaseConfig,
    create_draft,
    get_workspace,
    latest_manifest_bytes,
    package_root_from_env,
    publish_preview,
    publish_rollback,
    publish_stable,
)
from app.local.prompt_bundles import (
    GUIDANCE_MAX_CHARS,
    PROMPT_BUNDLE_MANIFEST,
    canonical_json,
)
from app.local.prompt_package import (
    PACKAGE_OPEN_GUIDANCE_FIELDS,
    PACKAGE_OPEN_TASK_TYPES,
    PACKAGE_TASK_TYPES,
    PackageTrust,
    verify_package,
)

PEPPER = "synthetic-prompt-release-pepper-0123456789"
PREVIEW_SECRET = "synthetic-prompt-release-preview-0123456789"
KEY_ID = "synthetic-release-key"
BACKEND = Path(__file__).resolve().parents[2]


def _settings(url: str) -> CollaborationSettings:
    return CollaborationSettings(
        database_url=url,
        token_pepper=PEPPER,
        preview_secret=PREVIEW_SECRET,
    )


def _latest_bundle(task_type: str) -> dict:
    matches = [
        bundle
        for bundle in PROMPT_BUNDLE_MANIFEST
        if bundle["task_type"] == task_type
    ]
    return max(matches, key=lambda item: int(item["default_revision"]))


def _builtin_text(task_type: str, field: str) -> str:
    return str(_latest_bundle(task_type)["guidance_defaults_json"][field])


def _create_sqlite_schema(engine) -> None:
    tables = (
        PromptReleaseState.__table__,
        PromptReleaseDraft.__table__,
        PromptRelease.__table__,
    )
    with engine.begin() as connection:
        for table in tables:
            ddl = str(CreateTable(table).compile(dialect=engine.dialect))
            ddl = ddl.replace("CURRENT_TIMESTAMP(6)", "CURRENT_TIMESTAMP")
            connection.exec_driver_sql(ddl)


class _PromptReleaseTestBase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.private_key = Ed25519PrivateKey.generate()
        self.key_path = (self.root / "signing.key").resolve()
        self.key_path.write_bytes(self.private_key.private_bytes_raw())
        self.package_dir = (self.root / "packages").resolve()
        self.config = PromptReleaseConfig(
            signing_key_file=self.key_path,
            key_id=KEY_ID,
            package_dir=self.package_dir,
        )
        self.trust = PackageTrust(
            source_url="https://example.test/prompt-packages",
            keys={KEY_ID: self.private_key.public_key().public_bytes_raw()},
            client_version="0.1.0",
        )

        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.addCleanup(self.engine.dispose)

        @event.listens_for(self.engine, "connect")
        def _register_char_length(dbapi_connection, _record):
            dbapi_connection.create_function("char_length", 1, len)

        _create_sqlite_schema(self.engine)
        self.Session = sessionmaker(
            bind=self.engine, autoflush=False, expire_on_commit=False
        )
        with self.Session() as session:
            with session.begin():
                session.add(
                    PromptReleaseState(
                        id=1,
                        last_sequence=0,
                        updated_at=datetime.now(timezone.utc),
                    )
                )

    def _workspace(self) -> dict:
        with self.Session() as session:
            return get_workspace(session)

    def _draft(self, changes: dict, notes: str = "合成草稿") -> dict:
        with self.Session() as session:
            return create_draft(session, changes=changes, notes=notes)

    def _preview(self, draft_id: UUID) -> dict:
        with self.Session() as session:
            return publish_preview(
                session, self.config, draft_id=draft_id
            )

    def _stable(self, preview_sequence: int) -> dict:
        with self.Session() as session:
            return publish_stable(
                session, self.config, preview_sequence=preview_sequence
            )

    def _rollback(self, target: int, expected: int) -> dict:
        with self.Session() as session:
            return publish_rollback(
                session,
                self.config,
                target_sequence=target,
                expected_stable_sequence=expected,
            )

    def _release_row(self, sequence: int) -> PromptRelease:
        with self.Session() as session:
            row = session.get(PromptRelease, sequence)
            self.assertIsNotNone(row)
            return row

    def _package_for_row(self, row: PromptRelease):
        path = (
            self.package_dir
            / row.channel
            / f"v{row.release_sequence}-{row.package_sha256}.json"
        )
        raw = path.read_bytes()
        self.assertEqual(
            hashlib.sha256(raw).hexdigest(), row.package_sha256
        )
        return verify_package(raw, self.trust)

    def _manifest_for_row(self, row: PromptRelease) -> dict:
        with self.Session() as session:
            body = latest_manifest_bytes(session, row.channel)
        document = json.loads(body)
        self.assertEqual(
            set(document),
            {
                "format_version",
                "channel",
                "release_sequence",
                "package_sha256",
                "key_id",
                "signature",
            },
        )
        self.assertEqual(document["format_version"], 1)
        self.assertEqual(document["channel"], row.channel)
        self.assertEqual(
            document["release_sequence"], row.release_sequence
        )
        self.assertEqual(document["package_sha256"], row.package_sha256)
        self.assertEqual(document["key_id"], row.key_id)
        unsigned = {
            key: document[key]
            for key in (
                "format_version",
                "channel",
                "release_sequence",
                "package_sha256",
                "key_id",
            )
        }
        message = (
            b"kgm-prompt-manifest-v1\n"
            + canonical_json(unsigned).encode("utf-8")
        )
        self.private_key.public_key().verify(
            base64.b64decode(document["signature"]), message
        )
        return document

    def _assert_code(self, code: str, callback):
        with self.assertRaises(CollaborationError) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)
        return caught.exception


class PromptReleaseSQLiteUnitTests(_PromptReleaseTestBase):
    def test_workspace_and_draft_freeze_the_editable_baseline(self):
        workspace = self._workspace()
        self.assertEqual(
            set(workspace), {"editable", "drafts", "releases", "latest"}
        )
        self.assertEqual(workspace["latest"], {"preview": None, "stable": None})
        self.assertEqual(workspace["drafts"], [])
        self.assertEqual(workspace["releases"], [])
        editable = {
            item["task_type"]: item["fields"]
            for item in workspace["editable"]
        }
        self.assertEqual(set(editable), set(PACKAGE_OPEN_TASK_TYPES))
        self.assertEqual(
            set(editable["daily_lesson_split"]),
            set(PACKAGE_OPEN_GUIDANCE_FIELDS["daily_lesson_split"]),
        )
        self.assertEqual(
            editable["daily_lesson_split"]["theme"],
            _builtin_text("daily_lesson_split", "theme"),
        )
        self.assertEqual(
            editable["weekly_games_select"]["instructions"],
            _builtin_text("weekly_games_select", "instructions"),
        )

        draft = self._draft(
            {
                "daily_lesson_split": {"theme": "合成主题"},
                "weekly_games_select": {"instructions": "合成游戏说明"},
            },
            notes="合成草稿",
        )
        self.assertIsNone(draft["base_stable_sequence"])
        self.assertEqual(draft["notes"], "合成草稿")
        self.assertEqual(
            draft["changes"],
            {
                "daily_lesson_split": {"theme": "合成主题"},
                "weekly_games_select": {"instructions": "合成游戏说明"},
            },
        )
        after = self._workspace()
        self.assertEqual(after["drafts"], [draft])
        self.assertEqual(after["releases"], [])
        self.assertEqual(
            {
                item["task_type"]: item["fields"]
                for item in after["editable"]
            },
            editable,
        )

    def test_preview_and_stable_are_idempotent_and_signed(self):
        draft = self._draft(
            {
                "daily_lesson_split": {"theme": "合成主题"},
                "weekly_games_select": {"instructions": "合成游戏说明"},
            }
        )
        draft_id = UUID(draft["draft_id"])
        preview = self._preview(draft_id)
        self.assertEqual(preview["channel"], "preview")
        self.assertEqual(preview["draft_id"], draft["draft_id"])
        self.assertEqual(preview["notes"], "合成草稿")
        self.assertIsNone(preview["rollback_of"])

        repeated_preview = self._preview(draft_id)
        self.assertEqual(repeated_preview, preview)
        with self.Session() as session:
            count = session.scalar(
                select(func.count())
                .select_from(PromptRelease)
                .where(
                    PromptRelease.channel == "preview",
                    PromptRelease.draft_id == draft_id,
                )
            )
        self.assertEqual(count, 1)

        workspace = self._workspace()
        self.assertEqual(
            workspace["latest"],
            {"preview": preview["release_sequence"], "stable": None},
        )
        self.assertEqual(workspace["releases"], [preview])

        stable = self._stable(preview["release_sequence"])
        self.assertEqual(stable["channel"], "stable")
        self.assertEqual(stable["draft_id"], draft["draft_id"])
        self.assertEqual(stable["notes"], "合成草稿")
        self.assertIsNone(stable["rollback_of"])
        self.assertGreater(
            stable["release_sequence"], preview["release_sequence"]
        )
        self.assertEqual(
            self._stable(preview["release_sequence"]), stable
        )
        workspace = self._workspace()
        self.assertEqual(
            workspace["latest"],
            {
                "preview": preview["release_sequence"],
                "stable": stable["release_sequence"],
            },
        )
        self.assertEqual(
            [item["release_sequence"] for item in workspace["releases"]],
            [stable["release_sequence"], preview["release_sequence"]],
        )

        preview_row = self._release_row(preview["release_sequence"])
        stable_row = self._release_row(stable["release_sequence"])
        preview_package = self._package_for_row(preview_row)
        stable_package = self._package_for_row(stable_row)
        self.assertEqual(preview_package.release_sequence, preview["release_sequence"])
        self.assertEqual(stable_package.release_sequence, stable["release_sequence"])
        self.assertEqual(stable_package.notes, "合成草稿")
        self.assertEqual(preview_package.payload, stable_package.payload)
        self.assertEqual(preview_package.notes, stable_package.notes)

        bundle = next(
            item
            for item in stable_package.bundles
            if item.task_type == "daily_lesson_split"
        )
        self.assertEqual(bundle.guidance["theme"], "合成主题")
        self.assertEqual(
            bundle.default_revision,
            int(_latest_bundle("daily_lesson_split")["default_revision"]) + 1,
        )
        games = next(
            item
            for item in stable_package.bundles
            if item.task_type == "weekly_games_select"
        )
        self.assertEqual(games.guidance["instructions"], "合成游戏说明")
        self.assertEqual(
            games.guidance["target"],
            _builtin_text("weekly_games_select", "target"),
        )
        self.assertEqual(
            games.default_revision,
            int(_latest_bundle("weekly_games_select")["default_revision"]) + 1,
        )
        unaffected = next(
            item
            for item in stable_package.bundles
            if item.task_type == "daily_process_adapt"
        )
        self.assertEqual(
            unaffected.default_revision,
            int(_latest_bundle("daily_process_adapt")["default_revision"]),
        )
        self.assertEqual(
            {item.task_type for item in stable_package.bundles},
            set(PACKAGE_TASK_TYPES),
        )
        self._manifest_for_row(preview_row)
        self._manifest_for_row(stable_row)
        self.assertFalse(
            (self.package_dir / "stable" / MANIFEST_NAME).exists()
        )

    def test_preview_retry_reads_the_latest_manifest_from_database(self):
        draft_a = self._draft(
            {"daily_lesson_split": {"theme": "甲主题"}}
        )
        preview_a = self._preview(UUID(draft_a["draft_id"]))
        draft_b = self._draft(
            {"daily_lesson_split": {"theme": "乙主题"}}
        )
        preview_b = self._preview(UUID(draft_b["draft_id"]))
        self.assertGreater(
            preview_b["release_sequence"], preview_a["release_sequence"]
        )
        before = self._manifest_for_row(
            self._release_row(preview_b["release_sequence"])
        )

        retried = self._preview(UUID(draft_a["draft_id"]))
        self.assertEqual(retried, preview_a)
        after = self._manifest_for_row(
            self._release_row(preview_b["release_sequence"])
        )
        self.assertEqual(after, before)
        workspace = self._workspace()
        self.assertEqual(
            workspace["latest"]["preview"],
            preview_b["release_sequence"],
        )
        self.assertFalse(
            (self.package_dir / "preview" / MANIFEST_NAME).exists()
        )

    def test_same_baseline_previews_get_distinct_task_revisions(self):
        draft_a = self._draft(
            {"daily_lesson_split": {"theme": "甲主题"}}
        )
        preview_a = self._preview(UUID(draft_a["draft_id"]))
        draft_b = self._draft(
            {"daily_lesson_split": {"theme": "乙主题"}}
        )
        preview_b = self._preview(UUID(draft_b["draft_id"]))

        package_a = self._package_for_row(
            self._release_row(preview_a["release_sequence"])
        )
        package_b = self._package_for_row(
            self._release_row(preview_b["release_sequence"])
        )
        split_a = next(
            item
            for item in package_a.bundles
            if item.task_type == "daily_lesson_split"
        )
        split_b = next(
            item
            for item in package_b.bundles
            if item.task_type == "daily_lesson_split"
        )
        self.assertEqual(split_a.guidance["theme"], "甲主题")
        self.assertEqual(split_b.guidance["theme"], "乙主题")
        self.assertGreater(
            split_b.default_revision, split_a.default_revision
        )

        stable_a = self._stable(preview_a["release_sequence"])
        stable_package = self._package_for_row(
            self._release_row(stable_a["release_sequence"])
        )
        stable_split = next(
            item
            for item in stable_package.bundles
            if item.task_type == "daily_lesson_split"
        )
        self.assertEqual(stable_split.guidance["theme"], "甲主题")
        self.assertEqual(
            stable_split.guidance["objectives"],
            _builtin_text("daily_lesson_split", "objectives"),
        )
        self.assertEqual(
            dict(stable_split.guidance), dict(split_a.guidance)
        )
        self.assertGreater(
            stable_split.default_revision, split_b.default_revision
        )

    def test_unwritable_latest_mirror_path_does_not_block_publish(self):
        mirror = self.package_dir / "preview" / MANIFEST_NAME
        mirror.mkdir(parents=True)
        draft = self._draft(
            {"daily_lesson_split": {"theme": "独立镜像"}}
        )
        preview = self._preview(UUID(draft["draft_id"]))
        self.assertEqual(preview["channel"], "preview")
        self.assertTrue(mirror.is_dir())
        document = self._manifest_for_row(
            self._release_row(preview["release_sequence"])
        )
        self.assertEqual(
            document["release_sequence"], preview["release_sequence"]
        )

    def test_stable_rejects_a_stale_draft_baseline(self):
        draft_a = self._draft(
            {"daily_lesson_split": {"theme": "甲主题"}}
        )
        preview_a = self._preview(UUID(draft_a["draft_id"]))
        draft_b = self._draft(
            {"daily_lesson_split": {"theme": "乙主题"}}
        )
        preview_b = self._preview(UUID(draft_b["draft_id"]))
        stable_a = self._stable(preview_a["release_sequence"])

        stale = self._assert_code(
            "PROMPT_RELEASE_BASE_STALE",
            lambda: self._stable(preview_b["release_sequence"]),
        )
        self.assertEqual(
            stale.details["current_stable_sequence"],
            stable_a["release_sequence"],
        )
        with self.Session() as session:
            count = session.scalar(
                select(func.count())
                .select_from(PromptRelease)
                .where(
                    PromptRelease.channel == "stable",
                    PromptRelease.draft_id == UUID(draft_b["draft_id"]),
                )
            )
        self.assertEqual(count, 0)
        self.assertEqual(
            self._workspace()["latest"]["stable"],
            stable_a["release_sequence"],
        )

    def test_rollback_uses_target_content_with_new_revisions(self):
        draft_a = self._draft(
            {"daily_lesson_split": {"theme": "甲主题"}}
        )
        preview_a = self._preview(UUID(draft_a["draft_id"]))
        stable_a = self._stable(preview_a["release_sequence"])

        draft_b = self._draft(
            {"daily_lesson_split": {"objectives": "乙目标"}}
        )
        self.assertEqual(
            draft_b["base_stable_sequence"],
            stable_a["release_sequence"],
        )
        preview_b = self._preview(UUID(draft_b["draft_id"]))
        stable_b = self._stable(preview_b["release_sequence"])

        rollback_a = self._rollback(
            stable_a["release_sequence"],
            stable_b["release_sequence"],
        )
        self.assertEqual(rollback_a["channel"], "stable")
        self.assertIsNone(rollback_a["draft_id"])
        self.assertIsNone(rollback_a["notes"])
        self.assertEqual(
            rollback_a["rollback_of"], stable_a["release_sequence"]
        )
        self.assertGreater(
            rollback_a["release_sequence"], stable_b["release_sequence"]
        )
        self.assertEqual(
            self._rollback(
                stable_a["release_sequence"],
                stable_b["release_sequence"],
            ),
            rollback_a,
        )

        rollback_row = self._release_row(rollback_a["release_sequence"])
        package = self._package_for_row(rollback_row)
        split = next(
            item
            for item in package.bundles
            if item.task_type == "daily_lesson_split"
        )
        self.assertEqual(split.guidance["theme"], "甲主题")
        self.assertEqual(
            split.guidance["objectives"],
            _builtin_text("daily_lesson_split", "objectives"),
        )
        current_row = self._release_row(stable_b["release_sequence"])
        current_package = self._package_for_row(current_row)
        current_split = next(
            item
            for item in current_package.bundles
            if item.task_type == "daily_lesson_split"
        )
        self.assertGreater(
            split.default_revision, current_split.default_revision
        )

        rollback_b = self._rollback(
            stable_b["release_sequence"],
            rollback_a["release_sequence"],
        )
        self.assertGreater(
            rollback_b["release_sequence"],
            rollback_a["release_sequence"],
        )
        self.assertEqual(
            rollback_b["rollback_of"], stable_b["release_sequence"]
        )
        package_b = self._package_for_row(
            self._release_row(rollback_b["release_sequence"])
        )
        split_b = next(
            item
            for item in package_b.bundles
            if item.task_type == "daily_lesson_split"
        )
        self.assertEqual(split_b.guidance["objectives"], "乙目标")
        self.assertGreater(
            split_b.default_revision, split.default_revision
        )

        self._assert_code(
            "PROMPT_RELEASE_NOT_FOUND",
            lambda: self._rollback(
                preview_a["release_sequence"],
                rollback_b["release_sequence"],
            ),
        )
        self._assert_code(
            "PROMPT_RELEASE_INVALID",
            lambda: self._rollback(
                rollback_b["release_sequence"],
                rollback_b["release_sequence"],
            ),
        )
        self.assertEqual(
            self._rollback(
                stable_a["release_sequence"],
                stable_b["release_sequence"],
            ),
            rollback_a,
        )
        stale = self._assert_code(
            "PROMPT_RELEASE_BASE_STALE",
            lambda: self._rollback(
                stable_b["release_sequence"],
                stable_b["release_sequence"],
            ),
        )
        self.assertEqual(
            stale.details["current_stable_sequence"],
            rollback_b["release_sequence"],
        )

    def test_input_and_state_validation_fail_closed(self):
        self._assert_code(
            "PROMPT_RELEASE_INVALID",
            lambda: self._draft({"not_a_task": {"theme": "x"}}),
        )
        self._assert_code(
            "PROMPT_RELEASE_INVALID",
            lambda: self._draft(
                {"daily_lesson_split": {"not_a_field": "x"}}
            ),
        )
        self._assert_code(
            "PROMPT_RELEASE_INVALID",
            lambda: self._draft(
                {
                    "daily_lesson_split": {
                        "theme": "x" * (GUIDANCE_MAX_CHARS + 1)
                    }
                }
            ),
        )
        self._assert_code(
            "PROMPT_RELEASE_INVALID",
            lambda: self._draft(
                {"daily_lesson_split": {"theme": "bad\x00text"}}
            ),
        )
        self._assert_code(
            "PROMPT_RELEASE_INVALID",
            lambda: self._draft(
                {"daily_lesson_split": {"theme": "\ud800"}}
            ),
        )
        self._assert_code(
            "PROMPT_RELEASE_INVALID",
            lambda: self._draft(
                {"daily_lesson_split": {"theme": "x"}},
                notes="n" * (MAX_NOTES_CHARS + 1),
            ),
        )
        self._assert_code(
            "PROMPT_RELEASE_INVALID",
            lambda: create_draft(
                self.Session(), changes=[], notes="x"
            ),
        )
        self._assert_code(
            "PROMPT_RELEASE_INVALID",
            lambda: create_draft(
                self.Session(),
                changes={"daily_lesson_split": {"theme": 1}},
                notes="x",
            ),
        )
        self._assert_code(
            "PROMPT_RELEASE_NOT_FOUND",
            lambda: self._preview(uuid4()),
        )
        self._assert_code(
            "PROMPT_RELEASE_NOT_FOUND",
            lambda: self._stable(1),
        )

        bad_id = uuid4()
        with self.Session() as session:
            with session.begin():
                session.add(
                    PromptReleaseDraft(
                        id=bad_id,
                        notes="坏草稿",
                        base_stable_sequence=None,
                        changes={},
                        content={},
                        revisions={},
                        created_at=datetime.now(timezone.utc),
                    )
                )
        self._assert_code(
            "PROMPT_RELEASE_STATE_INVALID",
            lambda: self._preview(bad_id),
        )

    def test_unconfigured_and_invalid_key_material_fail_closed(self):
        with patch.dict(
            os.environ,
            {
                ENV_SIGNING_KEY_FILE: "",
                ENV_KEY_ID: "",
                ENV_PACKAGE_DIR: "",
            },
            clear=False,
        ):
            self._assert_code(
                "PROMPT_RELEASE_NOT_CONFIGURED",
                PromptReleaseConfig.from_env,
            )
            self._assert_code(
                "PROMPT_RELEASE_NOT_CONFIGURED",
                package_root_from_env,
            )

        with patch.dict(
            os.environ,
            {
                ENV_SIGNING_KEY_FILE: str(self.key_path),
                ENV_KEY_ID: KEY_ID,
                ENV_PACKAGE_DIR: "relative/package/root",
            },
            clear=False,
        ):
            self._assert_code(
                "PROMPT_RELEASE_NOT_CONFIGURED",
                PromptReleaseConfig.from_env,
            )

        short_key = self.root / "short.key"
        short_key.write_bytes(b"x" * 31)
        bad_config = PromptReleaseConfig(
            signing_key_file=short_key.resolve(),
            key_id=KEY_ID,
            package_dir=self.package_dir,
        )
        error = self._assert_code(
            "PROMPT_RELEASE_STORAGE_ERROR",
            bad_config.load_private_key,
        )
        self.assertNotIn(str(short_key), str(error))


class PromptReleaseHTTPTests(_PromptReleaseTestBase):
    def setUp(self):
        super().setUp()
        self.app = create_collaboration_app(
            _settings(
                "mysql+pymysql://synthetic:synthetic@127.0.0.1:3306/synthetic_collab"
            )
        )
        self.addCleanup(self.app.state.engine.dispose)
        self.principal = AdminPrincipal(
            admin_id=uuid4(),
            username="synthetic-admin",
            session_id=uuid4(),
            csrf_hash="0" * 64,
        )

        def _session_override():
            session = self.Session()
            try:
                yield session
            finally:
                session.close()

        self.app.dependency_overrides[get_session] = _session_override
        self.app.dependency_overrides[
            admin_api.get_admin_principal
        ] = lambda: self.principal
        self.app.dependency_overrides[
            admin_api.get_admin_csrf_principal
        ] = lambda: self.principal
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.env_patch = patch.dict(
            os.environ,
            {
                ENV_SIGNING_KEY_FILE: str(self.key_path),
                ENV_KEY_ID: KEY_ID,
                ENV_PACKAGE_DIR: str(self.package_dir),
            },
            clear=False,
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def _assert_no_store(self, response) -> None:
        self.assertEqual(
            response.headers.get("cache-control"), "no-store"
        )

    def _assert_nosniff(self, response) -> None:
        self.assertEqual(
            response.headers.get("x-content-type-options"), "nosniff"
        )

    def test_exact_admin_json_and_immutable_package_delivery(self):
        response = self.client.get(
            "/api/collaboration/admin/prompt-releases"
        )
        self.assertEqual(response.status_code, 200, response.text)
        self._assert_no_store(response)
        self._assert_nosniff(response)
        body = response.json()
        self.assertEqual(
            set(body), {"editable", "drafts", "releases", "latest"}
        )
        self.assertEqual(body["drafts"], [])
        self.assertEqual(body["releases"], [])
        self.assertEqual(body["latest"], {"preview": None, "stable": None})
        self.assertEqual(
            {item["task_type"] for item in body["editable"]},
            set(PACKAGE_OPEN_TASK_TYPES),
        )

        draft_response = self.client.post(
            "/api/collaboration/admin/prompt-releases/drafts",
            json={
                "changes": {
                    "daily_lesson_split": {"theme": "HTTP主题"},
                    "weekly_games_select": {"instructions": "HTTP说明"},
                },
                "notes": "HTTP草稿",
            },
        )
        self.assertEqual(
            draft_response.status_code, 200, draft_response.text
        )
        self._assert_no_store(draft_response)
        draft = draft_response.json()
        self.assertEqual(
            set(draft),
            {"draft_id", "notes", "base_stable_sequence", "changes"},
        )
        self.assertIsNone(draft["base_stable_sequence"])

        preview_response = self.client.post(
            "/api/collaboration/admin/prompt-releases/preview",
            json={"draft_id": draft["draft_id"]},
        )
        self.assertEqual(
            preview_response.status_code, 200, preview_response.text
        )
        self._assert_no_store(preview_response)
        preview = preview_response.json()
        self.assertEqual(
            set(preview),
            {
                "release_sequence",
                "channel",
                "draft_id",
                "notes",
                "rollback_of",
            },
        )
        self.assertEqual(preview["channel"], "preview")
        self.assertIsNone(preview["rollback_of"])

        stable_response = self.client.post(
            "/api/collaboration/admin/prompt-releases/stable",
            json={"preview_sequence": preview["release_sequence"]},
        )
        self.assertEqual(
            stable_response.status_code, 200, stable_response.text
        )
        stable = stable_response.json()
        self.assertEqual(stable["channel"], "stable")
        self.assertEqual(stable["draft_id"], draft["draft_id"])
        self.assertGreater(
            stable["release_sequence"], preview["release_sequence"]
        )

        workspace = self.client.get(
            "/api/collaboration/admin/prompt-releases"
        ).json()
        self.assertEqual(
            workspace["latest"],
            {
                "preview": preview["release_sequence"],
                "stable": stable["release_sequence"],
            },
        )

        with self.Session() as session:
            row = session.get(
                PromptRelease, stable["release_sequence"]
            )
            self.assertIsNotNone(row)
            package_sha = row.package_sha256
        package_path = (
            f"/prompt-packages/stable/v{stable['release_sequence']}"
            f"-{package_sha}.json"
        )
        package_response = self.client.get(package_path)
        self.assertEqual(
            package_response.status_code, 200, package_response.text
        )
        self.assertEqual(
            package_response.headers.get("cache-control"),
            "public, max-age=31536000, immutable",
        )
        self.assertEqual(
            package_response.headers.get("x-content-type-options"),
            "nosniff",
        )
        raw = package_response.content
        self.assertEqual(
            hashlib.sha256(raw).hexdigest(), package_sha
        )
        self.assertEqual(
            verify_package(raw, self.trust).release_sequence,
            stable["release_sequence"],
        )

        manifest_response = self.client.get(
            "/prompt-packages/stable/latest.json"
        )
        self.assertEqual(
            manifest_response.status_code, 200, manifest_response.text
        )
        self._assert_no_store(manifest_response)
        self._assert_nosniff(manifest_response)
        manifest = manifest_response.json()
        self.assertEqual(
            set(manifest),
            {
                "format_version",
                "channel",
                "release_sequence",
                "package_sha256",
                "key_id",
                "signature",
            },
        )
        self.assertEqual(manifest["channel"], "stable")
        self.assertEqual(
            manifest["release_sequence"], stable["release_sequence"]
        )
        self.assertEqual(manifest["package_sha256"], package_sha)
        self.assertEqual(manifest["key_id"], KEY_ID)
        unsigned = {
            key: manifest[key]
            for key in (
                "format_version",
                "channel",
                "release_sequence",
                "package_sha256",
                "key_id",
            )
        }
        self.private_key.public_key().verify(
            base64.b64decode(manifest["signature"]),
            b"kgm-prompt-manifest-v1\n"
            + canonical_json(unsigned).encode("utf-8"),
        )

        package_file = (
            self.package_dir
            / "stable"
            / f"v{stable['release_sequence']}-{package_sha}.json"
        )
        package_file.write_bytes(b"{}")
        tampered = self.client.get(package_path)
        self.assertEqual(tampered.status_code, 404)
        self._assert_no_store(tampered)

        missing = self.client.get(
            f"/prompt-packages/stable/v{stable['release_sequence']}"
            f"-{'0' * 64}.json"
        )
        self.assertEqual(missing.status_code, 404)
        self._assert_no_store(missing)
        unknown_channel = self.client.get(
            "/prompt-packages/other/latest.json"
        )
        self.assertEqual(unknown_channel.status_code, 404)
        self._assert_no_store(unknown_channel)

    def test_http_validation_csrf_and_unconfigured_fail_closed(self):
        extra = self.client.post(
            "/api/collaboration/admin/prompt-releases/drafts",
            json={"changes": {}, "notes": "x", "extra": True},
        )
        self.assertEqual(extra.status_code, 422, extra.text)
        self._assert_no_store(extra)
        self.assertEqual(extra.json()["error"]["code"], "INVALID_REQUEST")

        unknown_task = self.client.post(
            "/api/collaboration/admin/prompt-releases/drafts",
            json={"changes": {"not_a_task": {"theme": "x"}}, "notes": "x"},
        )
        self.assertEqual(
            unknown_task.status_code, 422, unknown_task.text
        )
        self._assert_no_store(unknown_task)
        self.assertEqual(
            unknown_task.json()["error"]["code"],
            "PROMPT_RELEASE_INVALID",
        )

        del self.app.dependency_overrides[
            admin_api.get_admin_csrf_principal
        ]
        no_csrf = self.client.post(
            "/api/collaboration/admin/prompt-releases/drafts",
            json={"changes": {}, "notes": "x"},
        )
        self.assertEqual(no_csrf.status_code, 403, no_csrf.text)
        self._assert_no_store(no_csrf)
        self.assertEqual(
            no_csrf.json()["error"]["code"], "ADMIN_CSRF_INVALID"
        )

        with patch.dict(
            os.environ,
            {
                ENV_SIGNING_KEY_FILE: "",
                ENV_KEY_ID: "",
                ENV_PACKAGE_DIR: "",
            },
            clear=False,
        ):
            unconfigured = self.client.get(
                "/api/collaboration/admin/prompt-releases"
            )
        self.assertEqual(
            unconfigured.status_code, 503, unconfigured.text
        )
        self._assert_no_store(unconfigured)
        self.assertEqual(
            unconfigured.json()["error"]["code"],
            "PROMPT_RELEASE_NOT_CONFIGURED",
        )

    def test_manifest_route_uses_database_when_latest_file_path_is_unwritable(self):
        mirror = self.package_dir / "preview" / MANIFEST_NAME
        mirror.mkdir(parents=True)
        draft = self.client.post(
            "/api/collaboration/admin/prompt-releases/drafts",
            json={
                "changes": {
                    "daily_lesson_split": {"theme": "数据库清单"}
                },
                "notes": "数据库清单",
            },
        ).json()
        preview = self.client.post(
            "/api/collaboration/admin/prompt-releases/preview",
            json={"draft_id": draft["draft_id"]},
        ).json()
        manifest = self.client.get(
            "/prompt-packages/preview/latest.json"
        )
        self.assertEqual(manifest.status_code, 200, manifest.text)
        self._assert_no_store(manifest)
        self.assertEqual(
            manifest.json()["release_sequence"],
            preview["release_sequence"],
        )
        self.assertTrue(mirror.is_dir())

    def test_http_rollback_route_returns_release_item(self):
        def create_and_publish(changes, notes):
            draft = self.client.post(
                "/api/collaboration/admin/prompt-releases/drafts",
                json={"changes": changes, "notes": notes},
            ).json()
            preview = self.client.post(
                "/api/collaboration/admin/prompt-releases/preview",
                json={"draft_id": draft["draft_id"]},
            ).json()
            stable = self.client.post(
                "/api/collaboration/admin/prompt-releases/stable",
                json={"preview_sequence": preview["release_sequence"]},
            ).json()
            return stable

        first = create_and_publish(
            {"daily_lesson_split": {"theme": "甲主题"}}, "甲"
        )
        second = create_and_publish(
            {"daily_lesson_split": {"theme": "乙主题"}}, "乙"
        )
        response = self.client.post(
            "/api/collaboration/admin/prompt-releases/rollback",
            json={
                "target_sequence": first["release_sequence"],
                "expected_stable_sequence": second["release_sequence"],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self._assert_no_store(response)
        rollback = response.json()
        self.assertEqual(
            set(rollback),
            {
                "release_sequence",
                "channel",
                "draft_id",
                "notes",
                "rollback_of",
            },
        )
        self.assertEqual(rollback["channel"], "stable")
        self.assertIsNone(rollback["draft_id"])
        self.assertIsNone(rollback["notes"])
        self.assertEqual(
            rollback["rollback_of"], first["release_sequence"]
        )
        self.assertGreater(
            rollback["release_sequence"], second["release_sequence"]
        )


class PromptReleaseSchemaAndRouteTests(unittest.TestCase):
    def test_0005_is_additive_and_matches_mysql_models(self):
        sql = (
            BACKEND
            / "migrations_collaboration"
            / "mysql"
            / "0005_prompt_releases.sql"
        ).read_text(encoding="utf-8")
        upper = sql.upper()
        self.assertEqual(sql.count("CREATE TABLE"), 3)
        self.assertEqual(sql.count("ENGINE=InnoDB"), 3)
        self.assertNotIn("CREATE DATABASE", upper)
        self.assertNotIn("CREATE SCHEMA", upper)
        self.assertNotIn("ALTER TABLE", upper)
        self.assertNotIn("DROP TABLE", upper)
        self.assertIn("INSERT INTO prompt_release_state", sql)
        for marker in (
            "prompt_release_state",
            "prompt_release_drafts",
            "prompt_releases",
            "CHAR(32)",
            "DATETIME(6)",
            "JSON",
            "ascii_bin",
            "CHAR_LENGTH",
            "STOP",
            "uq_prompt_release_channel_draft",
            "uq_prompt_release_rollback",
            "fk_prompt_release_draft",
            "fk_prompt_release_rollback",
            "ck_prompt_release_shape",
        ):
            self.assertIn(marker, sql)

        dialect = mysql_dialect()
        for model in (
            PromptReleaseState,
            PromptReleaseDraft,
            PromptRelease,
        ):
            ddl = str(CreateTable(model.__table__).compile(dialect=dialect))
            self.assertIsNone(model.__table__.schema)
            self.assertIn("ENGINE=InnoDB", ddl)
            self.assertIn("DATETIME(6)", ddl)
            self.assertIn("utf8mb4_0900_ai_ci", ddl)
        for model in (PromptReleaseDraft, PromptRelease):
            ddl = str(CreateTable(model.__table__).compile(dialect=dialect))
            self.assertIn("CHAR(32)", ddl)
            self.assertIn("JSON", ddl)
        release_ddl = str(
            CreateTable(PromptRelease.__table__).compile(dialect=dialect)
        )
        self.assertIn("ascii_bin", release_ddl)

    def test_admin_and_package_routes_are_registered(self):
        app = create_collaboration_app(
            _settings(
                "mysql+pymysql://synthetic:synthetic@127.0.0.1:3306/synthetic_collab"
            )
        )
        self.addCleanup(app.state.engine.dispose)
        paths = set(app.openapi()["paths"])
        base = "/api/collaboration/admin/prompt-releases"
        self.assertTrue(
            {
                base,
                base + "/drafts",
                base + "/preview",
                base + "/stable",
                base + "/rollback",
                "/prompt-packages/{channel}/{filename}",
            }.issubset(paths)
        )

    def test_wire_schemas_forbid_extra_fields(self):
        from app.collaboration.prompt_release_api import (
            DraftIn,
            PreviewIn,
            RollbackIn,
            StableIn,
        )

        DraftIn.model_validate(
            {"changes": {"daily_lesson_split": {"theme": "x"}}, "notes": ""}
        )
        with self.assertRaises(ValidationError):
            DraftIn.model_validate(
                {
                    "changes": {"daily_lesson_split": {"theme": "x"}},
                    "notes": "",
                    "extra": True,
                }
            )
        with self.assertRaises(ValidationError):
            DraftIn.model_validate(
                {
                    "changes": {"daily_lesson_split": {"theme": 1}},
                    "notes": "",
                }
            )
        with self.assertRaises(ValidationError):
            DraftIn.model_validate(
                {"changes": {}, "notes": "x" * (MAX_NOTES_CHARS + 1)}
            )
        with self.assertRaises(ValidationError):
            PreviewIn.model_validate(
                {"draft_id": str(uuid4()), "extra": True}
            )
        with self.assertRaises(ValidationError):
            StableIn.model_validate({"preview_sequence": "1"})
        with self.assertRaises(ValidationError):
            RollbackIn.model_validate(
                {"target_sequence": 1, "expected_stable_sequence": 0}
            )


@unittest.skipUnless(
    os.environ.get("KGM_COLLAB_TEST_DATABASE_URL", "").strip(),
    "set KGM_COLLAB_TEST_DATABASE_URL after applying 0001-0005",
)
class PromptReleaseMySQLIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = os.environ["KGM_COLLAB_TEST_DATABASE_URL"].strip()
        cls.settings = _settings(url)
        cls.settings.validate()
        cls.engine = create_collaboration_engine(cls.settings)
        cls.addClassCleanup(cls.engine.dispose)
        names = set(inspect(cls.engine).get_table_names())
        required = {
            "schools",
            "classes",
            "teachers",
            "teacher_class_memberships",
            "terms",
            "class_promotion_states",
            "class_promotion_history",
            "weekly_plan_weeks",
            "weekly_plan_confirmations",
            "weekly_plan_operations",
            "prompt_release_state",
            "prompt_release_drafts",
            "prompt_releases",
        }
        if not required.issubset(names):
            raise AssertionError(
                "apply MySQL 0001-0005 before running prompt-release integration"
            )
        with cls.engine.connect() as connection:
            version = connection.exec_driver_sql("SELECT VERSION()").scalar_one()
            database = connection.exec_driver_sql("SELECT DATABASE()").scalar_one()
            isolation = connection.exec_driver_sql(
                "SELECT @@transaction_isolation"
            ).scalar_one()
            state_count = connection.exec_driver_sql(
                "SELECT COUNT(*) FROM prompt_release_state WHERE id = 1"
            ).scalar_one()
        if not str(version).startswith("8.4."):
            raise AssertionError(f"MySQL 8.4 required, got {version!r}")
        if int(state_count) != 1:
            raise AssertionError("prompt_release_state singleton row is missing")
        print(
            f"KGM_PROMPT_RELEASE_MYSQL_VERSION={version} "
            f"KGM_PROMPT_RELEASE_MYSQL_DATABASE={database} "
            f"KGM_PROMPT_RELEASE_MYSQL_TRANSACTION_ISOLATION={isolation}"
        )
        cls.Session = sessionmaker(
            bind=cls.engine, autoflush=False, expire_on_commit=False
        )
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        root = Path(cls.temporary.name)
        cls.private_key = Ed25519PrivateKey.generate()
        cls.key_path = (root / "signing.key").resolve()
        cls.key_path.write_bytes(cls.private_key.private_bytes_raw())
        cls.config = PromptReleaseConfig(
            signing_key_file=cls.key_path,
            key_id=KEY_ID,
            package_dir=(root / "packages").resolve(),
        )
        cls.trust = PackageTrust(
            source_url="https://example.test/prompt-packages",
            keys={
                KEY_ID: cls.private_key.public_key().public_bytes_raw()
            },
            client_version="0.1.0",
        )

    def _new_draft(self, changes, notes):
        with self.Session() as session:
            return create_draft(session, changes=changes, notes=notes)

    def _preview(self, draft_id):
        with self.Session() as session:
            return publish_preview(
                session, self.config, draft_id=draft_id
            )

    def _stable(self, preview_sequence):
        with self.Session() as session:
            return publish_stable(
                session,
                self.config,
                preview_sequence=preview_sequence,
            )

    def _rollback(self, target, expected):
        with self.Session() as session:
            return publish_rollback(
                session,
                self.config,
                target_sequence=target,
                expected_stable_sequence=expected,
            )

    def test_transactional_channels_concurrency_and_rollback(self):
        draft_a = self._new_draft(
            {"daily_lesson_split": {"theme": "并发甲"}}, "并发草稿甲"
        )
        draft_a_id = UUID(draft_a["draft_id"])

        barrier = threading.Barrier(2)
        preview_results: list[tuple[str, object]] = []

        def preview_worker():
            with self.Session() as session:
                barrier.wait()
                try:
                    value = publish_preview(
                        session, self.config, draft_id=draft_a_id
                    )
                    preview_results.append(
                        ("ok", value["release_sequence"])
                    )
                except CollaborationError as exc:
                    preview_results.append(("error", exc.code))
                except Exception as exc:  # noqa: BLE001 - diagnostic only
                    preview_results.append(
                        ("error", type(exc).__name__)
                    )

        threads = [
            threading.Thread(target=preview_worker) for _ in range(2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(len(preview_results), 2, preview_results)
        self.assertTrue(
            all(kind == "ok" for kind, _ in preview_results),
            preview_results,
        )
        preview_sequences = {
            value for _, value in preview_results
        }
        self.assertEqual(len(preview_sequences), 1, preview_results)
        preview_sequence = int(next(iter(preview_sequences)))
        with self.Session() as session:
            preview_count = session.scalar(
                select(func.count())
                .select_from(PromptRelease)
                .where(
                    PromptRelease.channel == "preview",
                    PromptRelease.draft_id == draft_a_id,
                )
            )
        self.assertEqual(preview_count, 1)

        barrier = threading.Barrier(2)
        stable_results: list[tuple[str, object]] = []

        def stable_worker():
            with self.Session() as session:
                barrier.wait()
                try:
                    value = publish_stable(
                        session,
                        self.config,
                        preview_sequence=preview_sequence,
                    )
                    stable_results.append(
                        ("ok", value["release_sequence"])
                    )
                except CollaborationError as exc:
                    stable_results.append(("error", exc.code))
                except Exception as exc:  # noqa: BLE001 - diagnostic only
                    stable_results.append(
                        ("error", type(exc).__name__)
                    )

        threads = [
            threading.Thread(target=stable_worker) for _ in range(2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(len(stable_results), 2, stable_results)
        self.assertTrue(
            all(kind == "ok" for kind, _ in stable_results),
            stable_results,
        )
        stable_sequences = {value for _, value in stable_results}
        self.assertEqual(len(stable_sequences), 1, stable_results)
        stable_a_sequence = int(next(iter(stable_sequences)))
        self.assertGreater(stable_a_sequence, preview_sequence)
        with self.Session() as session:
            stable_count = session.scalar(
                select(func.count())
                .select_from(PromptRelease)
                .where(
                    PromptRelease.channel == "stable",
                    PromptRelease.draft_id == draft_a_id,
                )
            )
        self.assertEqual(stable_count, 1)

        draft_b = self._new_draft(
            {"daily_lesson_split": {"objectives": "并发乙目标"}},
            "并发草稿乙",
        )
        draft_c = self._new_draft(
            {"daily_lesson_split": {"objectives": "并发丙目标"}},
            "并发草稿丙",
        )
        draft_b_id = UUID(draft_b["draft_id"])
        draft_c_id = UUID(draft_c["draft_id"])
        barrier = threading.Barrier(2)
        parallel_previews: list[tuple[str, object, object]] = []

        def preview_pair_worker(draft_id):
            with self.Session() as session:
                barrier.wait()
                try:
                    value = publish_preview(
                        session, self.config, draft_id=draft_id
                    )
                    parallel_previews.append(
                        ("ok", draft_id, value["release_sequence"])
                    )
                except CollaborationError as exc:
                    parallel_previews.append(
                        ("error", draft_id, exc.code)
                    )
                except Exception as exc:  # noqa: BLE001 - diagnostic only
                    parallel_previews.append(
                        ("error", draft_id, type(exc).__name__)
                    )

        threads = [
            threading.Thread(
                target=preview_pair_worker, args=(draft_b_id,)
            ),
            threading.Thread(
                target=preview_pair_worker, args=(draft_c_id,)
            ),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(len(parallel_previews), 2, parallel_previews)
        self.assertTrue(
            all(kind == "ok" for kind, _, _ in parallel_previews),
            parallel_previews,
        )
        preview_by_draft = {
            draft_id: int(sequence)
            for _, draft_id, sequence in parallel_previews
        }
        preview_b = {
            "release_sequence": preview_by_draft[draft_b_id]
        }
        preview_c = {
            "release_sequence": preview_by_draft[draft_c_id]
        }
        self.assertEqual(len(set(preview_by_draft.values())), 2)
        self.assertTrue(
            all(
                sequence > stable_a_sequence
                for sequence in preview_by_draft.values()
            )
        )

        def split_revision(sequence):
            with self.Session() as session:
                row = session.get(PromptRelease, sequence)
                self.assertIsNotNone(row)
                path = (
                    self.config.package_dir
                    / row.channel
                    / f"v{sequence}-{row.package_sha256}.json"
                )
                raw = path.read_bytes()
            package = verify_package(raw, self.trust)
            return next(
                item
                for item in package.bundles
                if item.task_type == "daily_lesson_split"
            )

        split_b = split_revision(preview_b["release_sequence"])
        split_c = split_revision(preview_c["release_sequence"])
        self.assertEqual(split_b.guidance["objectives"], "并发乙目标")
        self.assertEqual(split_c.guidance["objectives"], "并发丙目标")
        self.assertNotEqual(
            split_b.default_revision, split_c.default_revision
        )

        barrier = threading.Barrier(2)
        competing: list[tuple[str, object]] = []

        def competing_stable_worker(preview_sequence):
            with self.Session() as session:
                barrier.wait()
                try:
                    value = publish_stable(
                        session,
                        self.config,
                        preview_sequence=preview_sequence,
                    )
                    competing.append(
                        ("ok", value["release_sequence"])
                    )
                except CollaborationError as exc:
                    competing.append(("error", exc.code))
                except Exception as exc:  # noqa: BLE001 - diagnostic only
                    competing.append(
                        ("error", type(exc).__name__)
                    )

        threads = [
            threading.Thread(
                target=competing_stable_worker,
                args=(preview_b["release_sequence"],),
            ),
            threading.Thread(
                target=competing_stable_worker,
                args=(preview_c["release_sequence"],),
            ),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(len(competing), 2, competing)
        self.assertEqual(
            sum(1 for kind, _ in competing if kind == "ok"),
            1,
            competing,
        )
        self.assertIn(
            ("error", "PROMPT_RELEASE_BASE_STALE"), competing
        )
        current_stable_sequence = int(
            next(value for kind, value in competing if kind == "ok")
        )
        self.assertGreater(
            current_stable_sequence, preview_c["release_sequence"]
        )

        barrier = threading.Barrier(2)
        rollback_results: list[tuple[str, object]] = []

        def rollback_worker():
            with self.Session() as session:
                barrier.wait()
                try:
                    value = publish_rollback(
                        session,
                        self.config,
                        target_sequence=stable_a_sequence,
                        expected_stable_sequence=current_stable_sequence,
                    )
                    rollback_results.append(
                        ("ok", value["release_sequence"])
                    )
                except CollaborationError as exc:
                    rollback_results.append(("error", exc.code))
                except Exception as exc:  # noqa: BLE001 - diagnostic only
                    rollback_results.append(
                        ("error", type(exc).__name__)
                    )

        threads = [
            threading.Thread(target=rollback_worker) for _ in range(2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(len(rollback_results), 2, rollback_results)
        self.assertTrue(
            all(kind == "ok" for kind, _ in rollback_results),
            rollback_results,
        )
        rollback_sequences = {value for _, value in rollback_results}
        self.assertEqual(len(rollback_sequences), 1, rollback_results)
        rollback_sequence = int(next(iter(rollback_sequences)))
        self.assertGreater(rollback_sequence, current_stable_sequence)

        with self.Session() as session:
            rollback_count = session.scalar(
                select(func.count())
                .select_from(PromptRelease)
                .where(
                    PromptRelease.rollback_of == stable_a_sequence,
                    PromptRelease.expected_stable_sequence
                    == current_stable_sequence,
                )
            )
            rollback_row = session.get(PromptRelease, rollback_sequence)
            self.assertIsNotNone(rollback_row)
            self.assertEqual(rollback_row.channel, "stable")
            self.assertEqual(
                rollback_row.rollback_of, stable_a_sequence
            )
            self.assertIsNone(rollback_row.draft_id)
            package_path = (
                self.config.package_dir
                / "stable"
                / f"v{rollback_sequence}-{rollback_row.package_sha256}.json"
            )
            raw = package_path.read_bytes()
        self.assertEqual(rollback_count, 1)
        self.assertEqual(
            hashlib.sha256(raw).hexdigest(),
            rollback_row.package_sha256,
        )
        package = verify_package(raw, self.trust)
        self.assertEqual(package.release_sequence, rollback_sequence)
        split = next(
            item
            for item in package.bundles
            if item.task_type == "daily_lesson_split"
        )
        self.assertEqual(split.guidance["theme"], "并发甲")
        self.assertEqual(
            split.guidance["objectives"],
            _builtin_text("daily_lesson_split", "objectives"),
        )
        with self.Session() as session:
            latest = get_workspace(session)["latest"]
        self.assertEqual(latest["stable"], rollback_sequence)
