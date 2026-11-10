"""Reusable synthetic fixture for complete local backup/restore verification.

Ownership and scope (2026-10-30 parallel session):

- This module is a *test support* file.  It never touches the real teacher
  data root, the real DPAPI credential root, user photos, environment secrets
  or a supplier endpoint.
- The caller prepares a ``LocalRuntime`` with explicit synthetic ``data_dir``
  and ``credential_root`` paths and owns its lifecycle.  This module only opens
  sessions on that runtime; it never calls ``prepare()``/``dispose()`` and
  never creates a default runtime.
- Every business record is written through the ordinary local services
  (profile/configuration, daily plan, observation, image import, AI task
  state machine, adoption, prompt edit, history restore, AI configuration).
  There are no direct INSERT/UPDATE statements in the seeding path.  The only
  synthetic material is the image bytes (created with Pillow) and the
  credential secret, which the normal configuration service encrypts with a
  DPAPI-protected master key inside the caller's synthetic credential root.
- No network call is made.  AI task state is produced by the real service
  state machine (``create_task`` -> ``claim_next`` -> ``commit_dispatch_mark``
  -> ``finalize_success``/``finalize_failure``); no worker or transport is
  started.  The one AI task that reaches a provider response is represented by
  a service-validated candidate produced by the same finalization path.

Coverage produced by one default seeding:

- profile, class, term, two calendar revisions, class game revisions,
  settings and committed configuration receipts;
- one daily plan with four business versions, AI adoption/baseline/provenance
  and a whole-plan restore receipt;
- public/indoor/outdoor observations, each with at least two retained history
  versions; the public one originally saved a second photo into history and
  then removed it from the current draft, so that photo remains referenced by
  history only;
- one adopted observation AI candidate with provenance, one failed task and
  one ``outcome_unknown`` task, all with executions/attempts;
- old AI configuration parameters (config version 1, old model/base URL) and
  an old personal prompt revision (revision 1) pinned by a finished
  execution, while the current configuration/prompt head has moved on;
- real JPEG/PNG originals plus the application's actual ``ai``/``export``
  JPEG derivatives, with database hashes, sizes, dimensions and references;
- one active credential row: key id, 12-byte nonce, AES-GCM ciphertext,
  database UUID and the DPAPI master-key file in the synthetic credential
  root (never read or copied by this module);
- optional capacity mode (``capacity_photo_count``) that adds real,
  decodable originals and their derivatives.  The default is zero so the
  self-test stays fast; the real byte size of a 600-photo package must be
  measured by the later capacity test, not asserted here.

Only the two files named in the task prompt are owned by this change:
``backend/tests/local/backup_fixture_support.py`` and
``backend/tests/local/test_backup_fixture_support.py``.
"""

from __future__ import annotations

import hashlib
import io
import json
import base64
import gzip
import math
import os
import random
import sqlite3
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageDraw
from sqlalchemy import Date, DateTime, JSON, func, select
from sqlalchemy.orm import Session

from app.local import (
    ai_adoption,
    ai_config_service,
    ai_task_service,
    appearance_service,
    config_service,
    daily_plan_history_service,
    daily_plan_service,
    observation_ai_service,
    observation_assets,
    observation_history_service,
    observation_service,
    profile_service,
    prompt_service,
    weekly_plan_service,
)
from app.local.weekly_plan_tokens import scope_hash
from app.local.base import LocalBase, utc_now
from app.local.models import (
    LocalAIAttempt,
    LocalAICandidate,
    LocalAIConfigVersion,
    LocalAICredential,
    LocalAIExecution,
    LocalAIState,
    LocalAITask,
    LocalCalendarRevision,
    LocalClass,
    LocalClassGameRevision,
    LocalDailyPlan,
    LocalDailyPlanAIProvenance,
    LocalDailyPlanContent,
    LocalDailyPlanRestore,
    LocalObservationAsset,
    LocalObservationAssetDerivative,
    LocalObservationAIProvenance,
    LocalObservationDraftPhoto,
    LocalObservationAIInputPhoto,
    LocalObservationRecord,
    LocalObservationRestore,
    LocalObservationRestorePreview,
    LocalObservationVersion,
    LocalObservationVersionPhoto,
    LocalPersonalPromptHead,
    LocalPersonalPromptVersion,
    LocalProfile,
    LocalPromptBundle,
    LocalSettings,
    LocalTerm,
)
from app.local.normalize import normalize_initialization

# ---------------------------------------------------------------------------
# Fixed fixture facts
# ---------------------------------------------------------------------------


OLD_0007_DATA_B64 = (
    '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'
    'AAvijLyyUI1DR2jAvbjvtsr48xP2SYg8cZ2NT1Wf6UsAxw5Nh95guBCn+/XFLKojaGu+H7oBAkV6fsj0LerZVabWixiwvlru+6In'
    '0pMBwvflHGqwEektZUotKjRLE/i0x62JXzGxtgcwYb7oS6dJsvwTOZP6cAYW/bAPyRInnslU30t0v3QJRm8Ww/rE7I3B8GmywSZk'
    'knKM7/q98Q1LppdW3gxDJd9Ij05MhYx1oiTiIhn2wP7oG5GeTFQ2JjXgzLfOUhz2yXubS59ILDlZV3aGhAbejQ1fQ+UNB7+fkOIA'
    'EWa4JuXoSGRIqKP30hFlx5IYMonwTFoZT0ipG4nE/WBHT5cIZc/4wnGkfJDkcOi32xt76ppKQ06H1U2zEmyAHVxTnDr7hax0OlYa'
    'TDLJA8HEC5MbkyzW6aTHy+c/HwmOn6J7Xzi6t+8Ct1pNagcGCdbCRrLsXpYwL4u1pStJD+sATZHBU2TwFBk8RQZPkcFTZPAUGTxd'
    '3ykyeIoM/pwig9+w5QltLaB8s+mYdN2k7N3xVhIZOKX6FLmZSXm+/G4Yoy3s1lUte0JvXuIlDLO/QeVQvS0NN290Os32F199dRNP'
    'lZLLrzRalVdVC2GcV9EbBwVHX02fN36FXllWayqkogEGpIFN2dqRLbnba9SUjkpqpqYvwZ+FmL2tXVppSaVH3bTFPLvbphToTHtb'
    '1mo22l9VGFxSjBK+mpnX3zTfaOnH3WpLK/vscLv9Nl63VUmx0lVj465kexvLWltbarjQKUlixSm8bH9g0Lnv9GznkZM3YKeNfGJQ'
    'AR/5yIAyNvKJEZt6TmO9zeHo7SPrlAxscBBDHR7s3KiOZBo9dnmP9GBoOSajj74v45M/fvfguz8/+M23n/7wn57+8i0cRf/07//x'
    '4JsfffrTb3zyX99/+vs/Hvzdb5/95GvJH598+MdP/+c/HnzvO89+87u/fPzTg3f+9dkPfpu8ePCf//703W/hyee//O3zP5u7yfWn'
    '7/7rwTf+KXnx6Y//4/mfvo+PP/uXjw7e+/Gzf/vnTz789798/PYnH37n+T//7bOPf/Tpl3/xv7/8laOm+1Ankx6mffvp+09/8U00'
    '98mff/bsh/+Ex57+6JvPP3jv4J1ff/Lhdz/95UcHH72DJg5+9ZOnP/ul6e13/ufzX7598NY3Pv3JD0wnbfdGdiztyZDtN6YrB9/8'
    'xsGvvnnwja8fvP+Hv3z81rNv/cvz36cX//eX//bZH9/59F/fTn4+e+9bf/n4W8Od7k/csX0aNDzGdOnTb37n2Vf+MHJ2JmpolB48'
    'rrmf/OlMzWXUsjGtPP/zN5/99tuGbv78s6dv/23SCijPEOh/vfv0vV9/+q+/Shb+4B/e7rVuieyXvzYdsB/89JtvP/33XyYk++y7'
    'Hzz/u68c30PDOpS6En6zEIc4xEEAADCSRBQPUMzcM45VD37ySLixhnuVaxI42Ooi7HeoZ65C6keDe+LddE9kr+B8mICx0+2JI5Jx'
    'LngH6LXYbnRbkX5he+JQsy/RlniiLWNiUX95KKXq6S/+8PQ77z97571nH/3m4A+/x7/Pf/fVpz/8vaHWr/86yxyGG/7w+0//9LVP'
    'v/yVg/ffffrl3yTsAqYckOT/ALb4I2QveOLgvX9++rV3Dn76JyMt3/kg/TJk0p/+BOmVcBWeB4sffPTP4Ibnf/7BwU//x8H7b+Mx'
    'I/bt8wff+26PO3/69Me/+PTdLyfXDUslz3/358kD+MKzP37/6f9495M/mZ0CquTTD37w/E9fNU18+VtPv/0vCcsmmwI2l4N3/v7Z'
    'D35uGvrgTwe/+MonH3374P3/0WNK11UKeQKo/OVIzagfe6jTzT2cXYmDTZjEMZYOQjOU+6GQTFJEgSJCZUwZlHdgd8QFMOVoDP5F'
    'kyE0xV51/VFcFzda29LG0exDhjJ3td4qgxlD3Rp4CdJeV3Qr4cx6dduyKzFv9CsfAx2ehuUmUAB1HCcbOqLA+R3si4WOlii0n1ys'
    'QwfO/u7Wt+qN3TokRNp/Jfcn6Lv5JffSX555d6NRQ03e/ZEDka0WvoqHEFvdbk82xpPNfFr9f9TT6PWSrldszXpyVIDYT/S+cLzC'
    'eOT94bXITOOIWTm2ASOHD7MFskP6UmauTHTPfmto0gwzdWx47qzTb/ITjqMricJtFpLQ1Kbqf7nVaGxbfTOF9r1+kpVJKKr/23fs'
    'VHQxe/XBXfFLmS/05yH7KmqmO0fXyQ5o8nXurUM7ajRP1rxvmj9t3/2RfT9c1sFuZVuZhLIOqzYPnVtyeit1Eqo8Yq8enYZ8y3X0'
    'szk27OiHR1uzo58dZ9fmdeWIujLiwTcnWJ7hfLLM9/os3J/jE/BysnqTcHTUqNWSNbBytqUhiDYaVUNePY44u2jJkwhH6X5yXo0b'
    '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'
    'O1I8lVT/f2pMXC4A1AIA')

FIXTURE_DISPLAY_NAME = "王老师"
FIXTURE_CLASS_NAME = "中二班"
FIXTURE_CLASS_GRADE = "middle"
FIXTURE_TERM_NAME = "2026 年秋季学期"
FIXTURE_SCHOOL_NAME = "示范幼儿园（分部）"
FIXTURE_TERM_START = date(2026, 9, 1)
FIXTURE_TERM_END = date(2026, 12, 31)
FIXTURE_OVERRIDE_DAY = date(2026, 9, 5)  # Saturday made a teaching day.
FIXTURE_PLAN_DATE = date(2026, 9, 2)

# Public synthetic values only.  This is not a real supplier key and is never
# sent anywhere; the configuration service encrypts it with a master key that
# lives under the caller's synthetic credential root.
SYNTHETIC_SECRET = "synthetic-fixture-secret-2026-10-30-not-a-real-key"
OLD_AI_BASE_URL = "https://api.example.com/v1"
OLD_AI_MODEL = "fixture-legacy-model"
CURRENT_AI_BASE_URL = "https://api.deepseek.com/v1"
CURRENT_AI_MODEL = "deepseek-flash"

# The app has two real derivative pipelines (AI working copy and export
# working copy); there is no separate thumbnail/display pipeline in this
# codebase.  Both are created by ``observation_assets.import_asset``.
EXPECTED_DERIVATIVE_PURPOSES = ("ai", "export")

# Maximum accepted optional capacity photos.  The requirement is "at least
# 600"; a larger cap still allows tuning without becoming unbounded.
MAX_CAPACITY_PHOTOS = 2000

SPLIT_RAW_LESSON = (
    "活动主题：秋天的树叶\n"
    "活动目标：观察树叶的形状与颜色\n"
    "活动准备：各种树叶、放大镜\n"
    "活动重点：有序观察\n"
    "活动难点：比较异同\n"
    "活动过程：\n"
    "一、导入\n二、观察\n三、比较"
)
SPLIT_CANDIDATE = {
    "group_activity": {
        "theme": "秋天的树叶",
        "objectives": "观察树叶的形状与颜色",
        "preparation": "各种树叶、放大镜",
        "key_points": "有序观察",
        "difficult_points": "比较异同",
        "process": "一、导入\n二、观察\n三、比较",
    }
}
_GENERATE_CANDIDATE = {
    "observation_goal": "观察幼儿合作搭建",
    "observation_process": "幼儿说：“我们一起搭桥吧。”\n两人轮流放置积木。",
    "analysis_evaluation": {
        "health": "动作协调",
        "language": "表达合作意愿",
        "social": "轮流协商",
        "science": "尝试连接",
        "arts": "",
    },
    "support_strategy": "提供更多连接材料，鼓励共同计划。",
}

# Ephemeral fields that are process/session identities rather than teacher
# business content.  They are excluded by default so a fixture and a restored
# copy can be compared without pretending an old launch is resumable.  Every
# other column (including timestamps and scheduler certainty) stays in the
# fingerprint so business or state differences are not swallowed.
RUNTIME_FIELD_EXCLUSIONS: dict[tuple[str, str], str] = {
    ("local_ai_executions", "launch_id"): (
        "per-process launch identity; a restore must not resume the old launch"
    ),
    ("local_ai_executions", "permit_id"): (
        "one-claim authorization nonce; not teacher content and not reusable"
    ),
    ("local_observation_export_snapshots", "launch_id"): (
        "per-process export launch identity; not business content"
    ),
    ("local_observation_export_snapshots", "session_scope_hash"): (
        "page-session binding digest; a restore must establish a new session"
    ),
}


class FixtureError(RuntimeError):
    """The synthetic fixture cannot be built or verified safely."""


class FixtureRootError(FixtureError):
    """The caller supplied a real/default or overlapping data root."""


class FixtureFingerprintError(FixtureError):
    """A database row or JSON value cannot be normalized without guessing."""


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FixtureEvidence:
    """IDs, semantic counts and fingerprints of one seeded synthetic runtime.

    Values are read back from SQLite after seeding; they are not merely the
    ids returned by the services.  ``verified`` becomes true only after
    :func:`validate_fixture` independently re-read the database and files.
    """

    data_dir: Path
    credential_root: Path
    profile_id: str
    class_id: str
    term_id: str
    settings_config_version: int
    calendar_revision_ids: tuple[str, ...]
    class_game_revision_ids: tuple[str, ...]
    daily_plan_id: str
    daily_plan_content_versions: tuple[int, ...]
    daily_plan_current_version: int
    daily_plan_candidate_id: str
    daily_plan_restore_request_id: str
    observation_ids: dict[str, str]
    primary_observation_id: str
    observation_versions: dict[str, tuple[int, ...]]
    asset_ids: dict[str, str]
    capacity_asset_ids: tuple[str, ...]
    current_photo_asset_ids: dict[str, tuple[str, ...]]
    version_photo_refs: dict[str, dict[int, tuple[str, ...]]]
    historical_only_asset_ids: tuple[str, ...]
    ai_tasks: dict[str, dict[str, Any]]
    ai_executions: dict[str, dict[str, Any]]
    credential: dict[str, Any]
    capacity_photo_count: int
    counts: dict[str, int]
    fingerprint: dict[str, Any]
    resources: dict[str, Any]
    schema_revision: str
    verified: bool

    def as_dict(self) -> dict[str, Any]:
        """JSON-safe view for private evidence files."""

        return _jsonable(asdict(self))


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _request_id() -> str:
    import uuid

    return str(uuid.uuid4())


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _is_link_like(path: Path) -> bool:
    """True for a symlink, junction or other reparse point."""

    if path.is_symlink():
        return True
    try:
        stat = path.stat(follow_symlinks=False)
    except OSError:
        return False
    return bool(getattr(stat, "st_file_attributes", 0) & 0x400)


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _database_family_contains(db_path: Path, needle: bytes) -> bool:
    """True if ``needle`` occurs in the main database or its WAL/SHM files."""

    family = [
        db_path,
        db_path.with_name(db_path.name + "-wal"),
        db_path.with_name(db_path.name + "-shm"),
    ]
    for path in family:
        if path.is_file() and needle in path.read_bytes():
            return True
    return False


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _resolved(path: Path) -> Path:
    return path.resolve(strict=False)


def _default_user_roots() -> tuple[Path, Path]:
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = (
        Path(local_app_data)
        if local_app_data
        else Path.home() / "AppData" / "Local"
    )
    return (
        base / "KindergartenManager" / "data",
        base / "KindergartenManager" / "credentials",
    )


def _require_synthetic_runtime(runtime: Any) -> None:
    """Refuse an unprepared, default-user or overlapping runtime.

    The check is deliberately about the caller's declared roots, not about a
    parent directory that happens to contain the word ``Temp``: the contract
    is "explicit synthetic roots", and the only thing this module can prove is
    that neither root is the product default.
    """

    if not getattr(runtime, "prepared", False):
        raise FixtureRootError(
            "caller must prepare the LocalRuntime before seeding the fixture"
        )
    data_dir = _resolved(Path(runtime.data_dir))
    credential_root = _resolved(Path(runtime.credential_root))
    default_data, default_credentials = _default_user_roots()
    default_data = _resolved(default_data)
    default_credentials = _resolved(default_credentials)

    for path, label in (
        (data_dir, "data_dir"),
        (credential_root, "credential_root"),
    ):
        for default_path, default_label in (
            (default_data, "real data root"),
            (default_credentials, "real credential root"),
        ):
            if _is_within(path, default_path) or _is_within(
                default_path, path
            ):
                raise FixtureRootError(
                    f"{label} must not contain or be inside the {default_label}"
                )
        if not path.is_absolute():
            raise FixtureRootError(f"{label} must be absolute")
    if _is_within(data_dir, credential_root) or _is_within(
        credential_root, data_dir
    ):
        raise FixtureRootError(
            "data_dir and credential_root must be separate synthetic roots"
        )
    if not Path(runtime.db_path).is_file():
        raise FixtureRootError("the prepared runtime has no synthetic database")


def _require_empty_business(session: Session) -> None:
    for model in (
        LocalProfile,
        LocalClass,
        LocalTerm,
        LocalSettings,
        LocalDailyPlan,
        LocalObservationRecord,
        LocalAIState,
    ):
        count = int(
            session.scalar(select(func.count()).select_from(model)) or 0
        )
        if count:
            raise FixtureError(
                "seed_existing_runtime requires an initialized-empty runtime; "
                f"{model.__tablename__} already has {count} row(s)"
            )


# ---------------------------------------------------------------------------
# Image material
# ---------------------------------------------------------------------------


def old_0007_data_sql() -> str:
    """Frozen 0007 business data, excluding photo binary rows."""
    raw = gzip.decompress(base64.b64decode(OLD_0007_DATA_B64)).decode("utf-8")
    return "\n".join(
        line.replace('INSERT INTO "local_prompt_bundles"',
                     'INSERT OR IGNORE INTO "local_prompt_bundles"')
        for line in raw.splitlines()
        if not line.startswith('INSERT INTO "local_alembic_version"')
    )


def _write_old_asset(data_dir: Path, relative: str, payload: bytes) -> None:
    path = Path(data_dir).joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)

OLD_0007_TABLE_COLUMNS = {'local_ai_attempts': ['id', 'execution_id', 'attempt_no', 'state', 'dispatch_marked_at', 'ended_at', 'evidence_code', 'http_status', 'provider_request_id', 'returned_model', 'usage_json', 'duration_ms', 'created_at'], 'local_ai_candidates': ['id', 'profile_id', 'execution_id', 'task_id', 'source_kind', 'source_id', 'observation_id', 'daily_plan_id', 'input_id', 'task_type', 'contract_version', 'schema_version', 'raw_candidate_json', 'candidate_hash', 'created_at'], 'local_ai_config_versions': ['profile_id', 'version', 'protocol_id', 'base_url', 'model', 'credential_id', 'created_at'], 'local_ai_credentials': ['id', 'profile_id', 'key_id', 'nonce', 'ciphertext', 'state', 'created_at', 'updated_at'], 'local_ai_executions': ['id', 'task_id', 'source_kind', 'source_id', 'observation_id', 'daily_plan_id', 'input_id', 'task_type', 'generation', 'launch_id', 'permit_id', 'config_version', 'profile_id', 'personal_revision', 'contract_version', 'default_revision', 'state', 'runtime_meta_json', 'started_at', 'created_at', 'ended_at'], 'local_ai_inputs': ['id', 'profile_id', 'source_kind', 'source_id', 'observation_id', 'source_revision', 'daily_plan_id', 'content_id', 'content_version', 'task_type', 'target_grade', 'input_schema_version', 'payload_json', 'dependencies_json', 'dependency_hash', 'target_hashes_json', 'created_at'], 'local_ai_operations': ['id', 'profile_id', 'request_id', 'operation_kind', 'request_fingerprint', 'fingerprint_kind', 'fingerprint_key_id', 'result_json', 'created_at'], 'local_ai_state': ['profile_id', 'database_uuid', 'current_config_version', 'blocked_config_version', 'blocked_reason', 'created_at', 'updated_at'], 'local_ai_tasks': ['id', 'profile_id', 'source_kind', 'source_id', 'observation_id', 'daily_plan_id', 'task_type', 'input_id', 'status', 'reason', 'current_execution_id', 'generation', 'runtime_meta_json', 'created_at', 'updated_at'], 'local_calendar_days': ['revision_id', 'date', 'base_state', 'base_library_version', 'override_state', 'override_reason', 'effective_state'], 'local_calendar_revisions': ['id', 'term_id', 'revision_no', 'library_version', 'created_by', 'created_at'], 'local_class_game_heads': ['class_id', 'current_revision_id', 'created_at', 'updated_at'], 'local_class_game_revisions': ['id', 'class_id', 'revision_no', 'payload_json', 'payload_hash', 'created_at'], 'local_classes': ['id', 'name', 'grade', 'created_at', 'updated_at', 'header_teacher_names', 'caregiver_name'], 'local_config_operations': ['id', 'request_id', 'input_fingerprint', 'result_json', 'config_version', 'created_at'], 'local_daily_plan_ai_provenance': ['content_id', 'daily_plan_id', 'content_version', 'baseline_candidate_id', 'adopted_candidate_id', 'selected_targets_json', 'adopted_payload_hash', 'created_at'], 'local_daily_plan_contents': ['id', 'daily_plan_id', 'version', 'raw_lesson_plan', 'split_baseline', 'adopted_content', 'editor_id', 'created_at'], 'local_daily_plan_restores': ['id', 'profile_id', 'request_id', 'request_fingerprint', 'daily_plan_id', 'source_content_id', 'source_content_version', 'before_content_id', 'before_content_version', 'result_content_id', 'result_content_version', 'created_at'], 'local_daily_plans': ['id', 'class_id', 'term_id', 'plan_date', 'creator_id', 'week_number', 'weekday', 'calendar_revision_id', 'current_content_id', 'current_content_version', 'creator_display_name', 'school_name', 'class_name', 'grade', 'deleted_at', 'deleted_by', 'created_at', 'updated_at'], 'local_observation_ai_input_photos': ['id', 'profile_id', 'source_kind', 'source_id', 'observation_id', 'input_id', 'asset_id', 'derivative_id', 'sort_order', 'caption', 'original_hash', 'work_hash'], 'local_observation_ai_provenance': ['id', 'profile_id', 'source_kind', 'source_id', 'observation_id', 'version', 'candidate_id', 'adopted_targets_json', 'input_hash', 'output_hash', 'created_at'], 'local_observation_asset_derivatives': ['id', 'observation_id', 'asset_id', 'purpose', 'params_version', 'content_hash', 'mime_type', 'width', 'height', 'relative_path', 'created_at'], 'local_observation_assets': ['id', 'observation_id', 'relative_path', 'display_name', 'mime_type', 'content_hash', 'byte_size', 'width', 'height', 'orientation', 'created_at'], 'local_observation_draft_photos': ['observation_id', 'asset_id', 'sort_order', 'caption'], 'local_observation_drafts': ['observation_id', 'revision', 'payload_json', 'payload_hash', 'created_at', 'updated_at'], 'local_observation_export_attempts': ['id', 'profile_id', 'snapshot_id', 'export_id_hash', 'filename_fingerprint', 'status', 'result_hash', 'byte_size', 'started_at', 'ended_at', 'created_at'], 'local_observation_export_snapshots': ['id', 'profile_id', 'launch_id', 'session_scope_hash', 'manifest_json', 'manifest_hash', 'created_at', 'expires_at'], 'local_observation_export_tokens': ['id', 'snapshot_id', 'profile_id', 'token_hash', 'expires_at', 'consumed_at', 'created_at'], 'local_observation_operations': ['id', 'profile_id', 'request_id', 'operation_kind', 'observation_id', 'request_fingerprint', 'status', 'result_json', 'created_at'], 'local_observation_records': ['id', 'creator_profile_id', 'observation_date', 'record_type', 'start_time', 'end_time', 'term_id', 'term_snapshot_json', 'school_name', 'class_name', 'observer_name', 'adult_count', 'child_count', 'age_years', 'subjects_json', 'environment', 'current_draft_revision', 'current_version', 'created_at', 'updated_at'], 'local_observation_restore_previews': ['id', 'token_hash', 'profile_id', 'observation_id', 'source_version', 'source_hash', 'base_draft_revision', 'base_draft_hash', 'effective_term_id', 'term_snapshot_hash', 'effective_payload_hash', 'material_hash', 'request_id', 'expires_at', 'consumed_at', 'created_at'], 'local_observation_restores': ['id', 'operation_id', 'profile_id', 'observation_id', 'source_version', 'result_version', 'before_draft_revision', 'before_version', 'changed', 'term_decision', 'effective_term_id', 'effective_payload_hash', 'created_at'], 'local_observation_version_photos': ['version_id', 'asset_id', 'observation_id', 'sort_order', 'caption'], 'local_observation_versions': ['id', 'observation_id', 'version', 'payload_json', 'payload_hash', 'source_kind', 'creator_profile_id', 'created_at'], 'local_operation_records': ['id', 'created_at', 'actor_id', 'action', 'target_type', 'target_id', 'target_version_after'], 'local_personal_prompt_heads': ['profile_id', 'task_type', 'current_revision', 'required_contract_version', 'latest_default_revision', 'created_at', 'updated_at'], 'local_personal_prompt_versions': ['profile_id', 'task_type', 'revision', 'contract_version', 'based_default_revision', 'guidance_json', 'orphaned_guidance_json', 'action', 'rejected_default_revision', 'created_at'], 'local_profile': ['id', 'singleton', 'display_name', 'created_at', 'updated_at'], 'local_prompt_bundles': ['task_type', 'contract_version', 'default_revision', 'input_schema_json', 'output_schema_json', 'guidance_defaults_json', 'bundle_hash', 'created_at'], 'local_settings': ['id', 'singleton', 'school_name', 'current_class_id', 'init_request_id', 'init_input_fingerprint', 'created_at', 'updated_at', 'config_version', 'ui_theme', 'ui_theme_version'], 'local_terms': ['id', 'name', 'start_date', 'end_date', 'current_calendar_revision_id', 'created_at', 'updated_at'], 'local_weekly_export_attempts': ['id', 'profile_id', 'snapshot_id', 'token_id', 'export_id_hash', 'filename_fingerprint', 'status', 'result_hash', 'byte_size', 'started_at', 'ended_at', 'created_at'], 'local_weekly_export_snapshots': ['id', 'profile_id', 'launch_id', 'session_scope_hash', 'manifest_json', 'manifest_hash', 'created_at', 'expires_at'], 'local_weekly_export_tokens': ['id', 'snapshot_id', 'profile_id', 'token_hash', 'expires_at', 'consumed_at', 'parent_attempt_id', 'created_at'], 'local_weekly_plan_confirmations': ['id', 'weekly_plan_id', 'version', 'draft_id', 'draft_version', 'schema_version', 'snapshot_json', 'snapshot_hash', 'facts_json', 'facts_hash', 'note', 'confirmed_by', 'confirmed_at'], 'local_weekly_plan_contents': ['id', 'weekly_plan_id', 'version', 'schema_version', 'content_json', 'content_hash', 'editor_profile_id', 'created_at'], 'local_weekly_plan_operations': ['id', 'profile_id', 'request_id', 'weekly_plan_id', 'action', 'input_fingerprint', 'result_draft_id', 'result_draft_version', 'result_confirmed_id', 'result_confirmed_version', 'result_snapshot_id', 'result_token_id', 'launch_id', 'session_scope_hash', 'result_json', 'created_at'], 'local_weekly_plans': ['id', 'profile_id', 'class_id', 'term_id', 'week_anchor_date', 'week_number_snapshot', 'term_start_date', 'term_end_date', 'calendar_revision_id', 'header_json', 'header_hash', 'current_draft_id', 'current_draft_version', 'current_confirmed_id', 'current_confirmed_version', 'created_at', 'updated_at']}

def _raw_sql_value(value: Any) -> list[Any]:
    if value is None:
        return ["null"]
    if isinstance(value, bytes):
        return ["blob", len(value), _sha256_bytes(value)]
    if isinstance(value, str):
        return ["text", value]
    if isinstance(value, int):
        return ["int", value]
    if isinstance(value, float):
        return ["float", value.hex()]
    return ["other", type(value).__name__, repr(value)]


def migration_rows(db_path: Path,
                   profile: dict[str, list[str]] | None = None) -> dict[str, Any]:
    profile = profile or OLD_0007_TABLE_COLUMNS
    con = sqlite3.connect(str(db_path))
    try:
        tables = {}
        for table, columns in profile.items():
            quoted = '"' + table.replace('"', '""') + '"'
            names = ", ".join('"' + c.replace('"', '""') + '"' for c in columns)
            rows = con.execute(f"SELECT {names} FROM {quoted}").fetchall()
            canon = [
                json.dumps(
                    [[column, _raw_sql_value(value)] for column, value in zip(columns, row)],
                    ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                )
                for row in rows
            ]
            canon.sort()
            tables[table] = {"columns": list(columns), "rows": canon}
        return {"format": 1, "tables": tables}
    finally:
        con.close()


def migration_fingerprint(db_path: Path,
                          profile: dict[str, list[str]] | None = None) -> dict[str, Any]:
    snapshot = migration_rows(db_path, profile)
    tables = {}
    for table, item in snapshot["tables"].items():
        tables[table] = {
            "columns": item["columns"],
            "row_count": len(item["rows"]),
            "rows_sha256": _sha256_bytes(
                json.dumps(item["rows"], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            ),
        }
    return {"format": 1, "tables": tables}

def _old_photo_specs() -> list[dict[str, Any]]:
    return [
        {
            "asset_id": "fixturea" + "0" * 24,
            "path": "observations/assets/fixture-a/original.jpg",
            "name": "合成当前照片.jpg",
            "payload": _jpeg_bytes((320, 240), 101),
            "mime": "image/jpeg",
            "width": 320,
            "height": 240,
            "orientation": None,
            "derivatives": [
                {
                    "id": "fixtured" + "0" * 24,
                    "purpose": "ai",
                    "path": "observations/assets/fixture-a/derivatives/ai.jpg",
                    "payload": _jpeg_bytes((160, 120), 201),
                    "mime": "image/jpeg",
                    "width": 160,
                    "height": 120,
                },
                {
                    "id": "fixtured" + "1" * 24,
                    "purpose": "export",
                    "path": "observations/assets/fixture-a/derivatives/export.jpg",
                    "payload": _jpeg_bytes((160, 120), 202),
                    "mime": "image/jpeg",
                    "width": 160,
                    "height": 120,
                },
            ],
        },
        {
            "asset_id": "fixtureb" + "0" * 24,
            "path": "observations/assets/fixture-b/original.png",
            "name": "合成历史照片.png",
            "payload": _png_bytes((240, 180)),
            "mime": "image/png",
            "width": 240,
            "height": 180,
            "orientation": None,
            "derivatives": [
                {
                    "id": "fixtured" + "2" * 24,
                    "purpose": "export",
                    "path": "observations/assets/fixture-b/derivatives/export.png",
                    "payload": _png_bytes((120, 90)),
                    "mime": "image/png",
                    "width": 120,
                    "height": 90,
                }
            ],
        },
    ]

def _insert_old_photo_rows(db_path: Path, data_dir: Path) -> None:
    con = sqlite3.connect(str(db_path))
    try:
        con.execute("PRAGMA foreign_keys=OFF")
        record = con.execute(
            "SELECT id, creator_profile_id FROM local_observation_records "
            "ORDER BY id LIMIT 1"
        ).fetchone()
        if record is None:
            raise FixtureError("old fixture has no observation record")
        observation_id, profile_id = record
        draft = con.execute(
            "SELECT observation_id, revision FROM local_observation_drafts "
            "WHERE observation_id=? LIMIT 1", (observation_id,)
        ).fetchone()
        version = con.execute(
            "SELECT id FROM local_observation_versions WHERE observation_id=? "
            "ORDER BY version LIMIT 1", (observation_id,)
        ).fetchone()
        ai_input = con.execute(
            "SELECT id, source_kind, source_id FROM local_ai_inputs "
            "WHERE source_kind='game_observation' ORDER BY id LIMIT 1"
        ).fetchone()
        if draft is None or version is None or ai_input is None:
            raise FixtureError("old fixture photo prerequisites missing")
        now = datetime.utcnow().isoformat()
        specs = _old_photo_specs()
        for spec in specs:
            payload = spec["payload"]
            _write_old_asset(data_dir, spec["path"], payload)
            con.execute(
                "INSERT INTO local_observation_assets (id, observation_id, "
                "relative_path, display_name, mime_type, content_hash, byte_size, "
                "width, height, orientation, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (spec["asset_id"], observation_id, spec["path"], spec["name"],
                 spec["mime"], _sha256_bytes(payload), len(payload),
                 spec["width"], spec["height"], spec["orientation"], now),
            )
            for derivative in spec["derivatives"]:
                dpayload = derivative["payload"]
                _write_old_asset(data_dir, derivative["path"], dpayload)
                con.execute(
                    "INSERT INTO local_observation_asset_derivatives (id, "
                    "observation_id, asset_id, purpose, params_version, content_hash, "
                    "mime_type, width, height, relative_path, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (derivative["id"], observation_id, spec["asset_id"],
                     derivative["purpose"], "v1", _sha256_bytes(dpayload),
                     derivative["mime"], derivative["width"], derivative["height"],
                     derivative["path"], now),
                )
        _insert_old_photo_links(con, observation_id, profile_id, version[0],
                                ai_input, specs, now)
        con.commit()
    finally:
        con.close()


def _insert_old_photo_links(con, observation_id, profile_id, version_id,
                            ai_input, specs, now) -> None:
    con.execute(
        "INSERT INTO local_observation_draft_photos "
        "(observation_id, asset_id, sort_order, caption) VALUES (?,?,?,?)",
        (observation_id, specs[0]["asset_id"], 0, "合成当前照片"),
    )
    con.execute(
        "INSERT INTO local_observation_draft_photos "
        "(observation_id, asset_id, sort_order, caption) VALUES (?,?,?,?)",
        (observation_id, specs[1]["asset_id"], 1, None),
    )
    con.execute(
        "INSERT INTO local_observation_version_photos "
        "(version_id, asset_id, observation_id, sort_order, caption) "
        "VALUES (?,?,?,?,?)",
        (version_id, specs[0]["asset_id"], observation_id, 0, "合成当前照片"),
    )
    con.execute(
        "INSERT INTO local_observation_ai_input_photos (id, profile_id, "
        "source_kind, source_id, observation_id, input_id, asset_id, "
        "derivative_id, sort_order, caption, original_hash, work_hash) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("fixturep" + "0" * 24, profile_id, ai_input[1], ai_input[2],
         observation_id, ai_input[0], specs[0]["asset_id"],
         specs[0]["derivatives"][0]["id"], 0, None,
         _sha256_bytes(specs[0]["payload"]),
         _sha256_bytes(specs[0]["derivatives"][0]["payload"])),
    )

def _align_old_prompt_bundles(conn: sqlite3.Connection) -> None:
    """Opt-in: align synthetic 0007 defaults with this build's manifest.

    This deliberately rewrites frozen 0007 prompt-bundle content/hashes.  It is
    only for current weekly-AI business tests that need normal registration of
    this build's weekly prompts; it must never be used by original 0007 package
    fidelity or restore tests.  The default fixture leaves every frozen row
    byte-for-byte untouched.
    """
    from app.local.prompt_bundles import PROMPT_BUNDLE_MANIFEST

    for item in PROMPT_BUNDLE_MANIFEST:
        conn.execute(
            "UPDATE local_prompt_bundles SET input_schema_json = ?, "
            "output_schema_json = ?, guidance_defaults_json = ?, "
            "bundle_hash = ? WHERE task_type = ? AND contract_version = ? "
            "AND default_revision = ?",
            (
                json.dumps(
                    item["input_schema_json"],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                json.dumps(
                    item["output_schema_json"],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                json.dumps(
                    item["guidance_defaults_json"],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                item["bundle_hash"],
                item["task_type"],
                item["contract_version"],
                item["default_revision"],
            ),
        )


def create_old_0007_fixture(
    db_path: Path,
    data_dir: Path,
    *,
    align_default_prompts: bool = False,
) -> None:
    """Create the frozen synthetic 0007 archive without any new ORM writes.

    ``align_default_prompts=False`` (the default) preserves the original 0007
    prompt-bundle rows and is the only mode valid for original archive/fidelity
    and plaintext/password restore tests.  Passing ``True`` is an explicit
    opt-in for later current-build weekly-AI business tests: it rewrites the
    same-key default bundles to this build's manifest so the normal prompt sync
    can register weekly prompts and backfill their personal heads.
    """
    from alembic import command
    from app.local.migrate import alembic_config

    db_path = Path(db_path)
    data_dir = Path(data_dir)
    if db_path.exists():
        raise FixtureError("old fixture database already exists")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(db_path), "20261101_0007_local_weekly")
    con = sqlite3.connect(str(db_path))
    try:
        con.executescript(old_0007_data_sql())
        if align_default_prompts:
            _align_old_prompt_bundles(con)
        con.commit()
    finally:
        con.close()
    _insert_old_photo_rows(db_path, data_dir)
    _insert_old_export_rows(db_path)

def _insert_old_export_rows(db_path: Path) -> None:
    con = sqlite3.connect(str(db_path))
    try:
        profile_id = con.execute("SELECT id FROM local_profile LIMIT 1").fetchone()[0]
        now = datetime.utcnow().isoformat()
        expires = (datetime.utcnow() + timedelta(days=1)).isoformat()
        obs_snapshot = "oldobssnap" + "0" * 22
        obs_token = "oldobstok" + "0" * 23
        obs_hash = _sha256_bytes(b"{}")
        con.execute(
            "INSERT INTO local_observation_export_snapshots (id, profile_id, "
            "launch_id, session_scope_hash, manifest_json, manifest_hash, "
            "created_at, expires_at) VALUES (?,?,?,?,?,?,?,?)",
            (obs_snapshot, profile_id, "old-launch", "a" * 64, "{}", obs_hash,
             now, expires),
        )
        con.execute(
            "INSERT INTO local_observation_export_tokens (id, snapshot_id, "
            "profile_id, token_hash, expires_at, consumed_at, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (obs_token, obs_snapshot, profile_id, "b" * 64, expires, None, now),
        )
        con.execute(
            "INSERT INTO local_observation_export_attempts (id, profile_id, "
            "snapshot_id, export_id_hash, filename_fingerprint, status, "
            "result_hash, byte_size, started_at, ended_at, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("oldobsatt" + "0" * 23, profile_id, obs_snapshot, "c" * 64,
             "d" * 64, "saved", "e" * 64, 1, now, now, now),
        )
        from app.local import weekly_plan_snapshot
        plan_id, conf_id, conf_version, snap_hash, snapshot_json = con.execute(
            "SELECT p.id, c.id, c.version, c.snapshot_hash, c.snapshot_json "
            "FROM local_weekly_plans p JOIN local_weekly_plan_confirmations c "
            "ON c.weekly_plan_id=p.id ORDER BY c.version DESC LIMIT 1"
        ).fetchone()
        snapshot = weekly_plan_snapshot.validate_confirmation_snapshot(
            json.loads(snapshot_json)
        )
        item = dict(snapshot)
        item["confirmation_id"] = conf_id
        item["confirmation_version"] = conf_version
        item["confirmation_hash"] = snap_hash
        selection = {
            "weekly_plan_id": plan_id,
            "confirmation_id": conf_id,
            "confirmation_version": conf_version,
            "draft_id": snapshot["draft_id"],
            "draft_version": snapshot["draft_version"],
            "content_hash": snapshot["content_hash"],
            "confirmation_hash": snap_hash,
            "week_anchor_date": snapshot["creation_context"]["week_anchor_date"],
            "week_number": snapshot["creation_context"]["week_number_snapshot"],
            "date_range": snapshot["date_range"],
        }
        missing = []
        for fact in snapshot["facts"]["missing"]:
            copied = json.loads(json.dumps(fact, ensure_ascii=False))
            details = dict(copied.get("details") or {})
            details.update(weekly_plan_id=plan_id, confirmation_id=conf_id)
            copied["details"] = details
            missing.append(copied)
        manifest = {
            "schema_version": 1, "profile_id": profile_id, "mode": "single",
            "requested_range": None, "selection": [selection],
            "warnings_as_of": datetime.now(timezone.utc).isoformat(),
            "missing": missing, "warnings": [], "items": [item],
        }
        manifest = weekly_plan_snapshot.validate_export_manifest(manifest)
        manifest_json = json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":"))
        manifest_hash = weekly_plan_snapshot.snapshot_hash(manifest)
        snap_id = "oldweeksna" + "0" * 22
        tok_id = "oldweektok" + "0" * 21
        att_id = "oldweekatt" + "0" * 21
        op_id = "oldweekopr" + "0" * 21
        draft_id, draft_version = snapshot["draft_id"], snapshot["draft_version"]
        con.execute(
            "INSERT INTO local_weekly_export_snapshots (id, profile_id, launch_id, "
            "session_scope_hash, manifest_json, manifest_hash, created_at, expires_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (snap_id, profile_id, "old-launch", "f" * 64, manifest_json,
             manifest_hash, now, expires),
        )
        con.execute(
            "INSERT INTO local_weekly_export_tokens (id, snapshot_id, profile_id, "
            "token_hash, expires_at, consumed_at, parent_attempt_id, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (tok_id, snap_id, profile_id, "9" * 64, expires, None, None, now),
        )
        con.execute(
            "INSERT INTO local_weekly_export_attempts (id, profile_id, snapshot_id, "
            "token_id, export_id_hash, filename_fingerprint, status, result_hash, "
            "byte_size, started_at, ended_at, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (att_id, profile_id, snap_id, tok_id, "8" * 64, "7" * 64,
             "saved", "6" * 64, 1, now, now, now),
        )
        metadata = {
            "schema_version": 1, "weekly_plan_id": None, "draft_id": None,
            "draft_version": None, "confirmation_id": None,
            "confirmation_version": None, "snapshot_id": snap_id,
            "token_id": tok_id,
        }
        con.execute(
            "INSERT INTO local_weekly_plan_operations (id, profile_id, request_id, "
            "weekly_plan_id, action, input_fingerprint, result_draft_id, "
            "result_draft_version, result_confirmed_id, result_confirmed_version, "
            "result_snapshot_id, result_token_id, launch_id, session_scope_hash, "
            "result_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (op_id, profile_id, "00000000-0000-4000-8000-000000000002", None,
             "export_create", "5" * 64, None, None, None, None,
             snap_id, tok_id, "old-launch", "f" * 64,
             json.dumps(metadata, ensure_ascii=False), now),
        )
        con.commit()
    finally:
        con.close()

def _jpeg_bytes(size: tuple[int, int], seed: int, quality: int = 92) -> bytes:
    """Create a deterministic, high-detail JPEG that is a real photo payload.

    Random pixel bytes are used so the capacity mode is not compressed away
    by a flat image; the result is still a normal, decodable JPEG created by
    Pillow.  No byte of the payload is hand-written or masqueraded.
    """

    width, height = size
    generator = random.Random(seed)
    raw = generator.randbytes(width * height * 3)
    with Image.frombytes("RGB", (width, height), raw) as image:
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=quality)
        return buffer.getvalue()


def _png_bytes(size: tuple[int, int]) -> bytes:
    """Create a deterministic RGB PNG with real drawn content."""

    width, height = size
    image = Image.new("RGB", (width, height), (246, 243, 235))
    try:
        draw = ImageDraw.Draw(image)
        step = max(8, min(width, height) // 8)
        colors = (
            (69, 123, 157),
            (168, 218, 220),
            (241, 250, 238),
            (233, 196, 106),
        )
        for index, x in enumerate(range(0, width, step)):
            draw.rectangle(
                (x, 0, x + step - 1, height - 1),
                fill=colors[index % len(colors)],
            )
        draw.line((0, height - 1, width - 1, 0), fill=(29, 53, 87), width=3)
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        return buffer.getvalue()
    finally:
        image.close()


def _assert_decodable(path: Path, *, expected_format: str) -> tuple[int, int]:
    """Pillow verify + full decode; returns the real pixel dimensions."""

    with Image.open(path) as image:
        if (image.format or "").lower() != expected_format:
            raise FixtureError(
                f"{path} is {image.format!r}, expected {expected_format!r}"
            )
        image.verify()
    with Image.open(path) as image:
        image.load()
        return image.size


# ---------------------------------------------------------------------------
# Configuration / prompt / AI helpers
# ---------------------------------------------------------------------------


def _apply_config_change(session: Session, change: dict[str, Any]) -> dict[str, Any]:
    current = int(session.scalar(select(LocalSettings.config_version)) or 0)
    preview = config_service.preview(
        session, expected_config_version=current, change=change
    )
    result = config_service.apply(
        session,
        request_id=_request_id(),
        expected_config_version=current,
        change=change,
        preview_token=preview["preview_token"],
    )
    if not result.get("changed"):
        raise FixtureError(f"configuration change was a no-op: {change['kind']}")
    session.expire_all()
    return result


def _patch_ai_config(
    session: Session,
    runtime: Any,
    *,
    expected_version: int,
    base_url: str,
    model: str,
    secret: str | None,
    secret_provided: bool,
) -> None:
    ai_config_service.patch_config(
        session,
        expected_ai_config_version=expected_version,
        base_url=base_url,
        model=model,
        secret=secret,
        secret_provided=secret_provided,
        request_id=_request_id(),
        credential_root=runtime.credential_root,
    )
    session.expire_all()


def _edit_prompt(session: Session, task_type: str) -> None:
    prompt = prompt_service.get_prompt(session, task_type=task_type)
    guidance = dict(prompt["guidance"])
    first_key = next(iter(guidance))
    guidance[first_key] = guidance[first_key] + "（合成夹具个人修订）"
    prompt_service.save_prompt(
        session,
        task_type=task_type,
        expected_personal_revision=prompt["personal_revision"],
        contract_version=prompt["contract_version"],
        guidance=guidance,
        request_id=_request_id(),
    )
    session.expire_all()


def _claim_exact(session: Session, runtime: Any, task_id: str) -> Any:
    claim = ai_task_service.claim_next(
        runtime, now=utc_now(), started_ticks=1
    )
    if claim is None or claim.task_id != task_id:
        raise FixtureError(
            "the AI claim did not pick the intended task "
            f"(wanted {task_id}, got {getattr(claim, 'task_id', None)})"
        )
    if not ai_task_service.commit_dispatch_mark(session, claim, utc_now()):
        raise FixtureError("the AI dispatch mark was not accepted")
    return claim


def _finalize_success_claim(
    session: Session, claim: Any, candidate: dict[str, Any]
) -> None:
    ok = ai_task_service.finalize_success(
        session,
        claim,
        {
            "kind": "success",
            "sent": True,
            "http_status": 200,
            "candidate_text": json.dumps(candidate, ensure_ascii=False),
        },
        utc_now(),
    )
    if not ok:
        raise FixtureError("the AI success result was not committed")
    session.expire_all()


def _finalize_failed_claim(session: Session, claim: Any) -> None:
    ok = ai_task_service.finalize_failure(
        session,
        claim,
        {
            "kind": "not_sent",
            "reason": "connection_unavailable",
            "sent": False,
            "transient_not_sent": False,
        },
        utc_now(),
    )
    if not ok:
        raise FixtureError("the AI failure result was not committed")
    session.expire_all()


def _finalize_unknown_claim(session: Session, claim: Any) -> None:
    ok = ai_task_service.finalize_failure(
        session,
        claim,
        {
            "kind": "unknown",
            "reason": "timeout_after_dispatch",
            "sent": True,
        },
        utc_now(),
    )
    if not ok:
        raise FixtureError("the AI unknown result was not committed")
    session.expire_all()


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------


def save_split_baseline(
    session: Session,
    runtime: Any,
    *,
    plan_id: str,
    expected_content_version: int,
    target_grade: str,
) -> dict[str, Any]:
    """Run the real split task/adopt path and save its content version.

    The caller must have created the plan with ``SPLIT_RAW_LESSON`` so the
    candidate is a legal cleanup of the original lesson.
    """
    task, created = ai_task_service.create_task(
        session,
        plan_id=plan_id,
        task_type="daily_lesson_split",
        expected_content_version=expected_content_version,
        target_grade=target_grade,
        request_id=_request_id(),
    )
    if not created:
        raise FixtureError("the daily plan split task was not created")
    claim = _claim_exact(session, runtime, task["id"])
    _finalize_success_claim(session, claim, SPLIT_CANDIDATE)
    candidate = session.scalars(
        select(LocalAICandidate).where(LocalAICandidate.task_id == task["id"])
    ).one()
    preview = ai_adoption.preview_adoption(
        session,
        plan_id=plan_id,
        candidate_id=candidate.id,
        expected_content_version=expected_content_version,
        selected_targets=["group_activity"],
        edited_candidate=SPLIT_CANDIDATE,
    )
    adopted = ai_adoption.adopt(
        session,
        plan_id=plan_id,
        candidate_id=candidate.id,
        expected_content_version=expected_content_version,
        preview_token=preview["preview_token"],
        request_id=_request_id(),
    )
    if adopted["content_version"] != expected_content_version + 1:
        raise FixtureError("daily plan split baseline did not advance the content version")
    return {
        "task_id": task["id"],
        "candidate_id": candidate.id,
        "content_version": adopted["content_version"],
    }


def seed_existing_runtime(
    runtime: Any,
    *,
    capacity_photo_count: int = 0,
    capacity_photo_size: tuple[int, int] = (320, 240),
) -> FixtureEvidence:
    """Seed one prepared, initialized-empty synthetic runtime.

    The caller keeps ownership of ``runtime`` (including its lock and
    disposal).  The default run is intentionally small and fast; pass
    ``capacity_photo_count=600`` (or more, up to ``MAX_CAPACITY_PHOTOS``) to
    add real photos for a later measured capacity test.
    """

    _require_synthetic_runtime(runtime)
    if not isinstance(capacity_photo_count, int) or isinstance(
        capacity_photo_count, bool
    ):
        raise FixtureError("capacity_photo_count must be an integer")
    if capacity_photo_count < 0 or capacity_photo_count > MAX_CAPACITY_PHOTOS:
        raise FixtureError(
            f"capacity_photo_count must be 0..{MAX_CAPACITY_PHOTOS}"
        )
    if (
        not isinstance(capacity_photo_size, tuple)
        or len(capacity_photo_size) != 2
        or any(
            not isinstance(item, int) or item < 1
            for item in capacity_photo_size
        )
    ):
        raise FixtureError("capacity_photo_size must be a positive (w, h) tuple")

    session = runtime.session()
    try:
        _require_empty_business(session)

        # --- profile / class / term / calendar -------------------------
        initialization = normalize_initialization(
            request_id=_request_id(),
            display_name=FIXTURE_DISPLAY_NAME,
            class_name="中一班",
            grade=FIXTURE_CLASS_GRADE,
            term_name=FIXTURE_TERM_NAME,
            start_date=FIXTURE_TERM_START.isoformat(),
            end_date=FIXTURE_TERM_END.isoformat(),
            school_name="示范幼儿园",
        )
        profile_service.initialize(session, initialization)
        session.expire_all()

        profile = session.scalars(select(LocalProfile)).one()
        settings = session.get(LocalSettings, "singleton")
        if settings is None:
            raise FixtureError("initialization produced no local settings")
        term = session.scalars(select(LocalTerm)).one()
        profile_id = profile.id
        class_id = settings.current_class_id
        term_id = term.id

        # --- committed configuration history ---------------------------
        _apply_config_change(
            session,
            {
                "kind": "profile",
                "display_name": FIXTURE_DISPLAY_NAME,
                "school_name": FIXTURE_SCHOOL_NAME,
            },
        )
        _apply_config_change(
            session,
            {
                "kind": "current_class",
                "name": FIXTURE_CLASS_NAME,
                "grade": FIXTURE_CLASS_GRADE,
                "header_teacher_names": ["王老师", "李老师", "王老师"],
                "caregiver_name": "张阿姨",
            },
        )
        _apply_config_change(
            session,
            {
                "kind": "class_games",
                "locations": [
                    {
                        "kind": "area",
                        "name": "积木区",
                        "guidance": "先观察再介入",
                    }
                ],
                "game_scope": "室内区域游戏",
                "guidance": "按幼儿兴趣提供材料",
            },
        )
        _apply_config_change(
            session,
            {
                "kind": "calendar_override",
                "term_id": term_id,
                "date": FIXTURE_OVERRIDE_DAY.isoformat(),
                "state": "teaching",
                "reason": "园庆调课（合成夹具）",
            },
        )

        # Appearance preference is independent of config_version.
        appearance_service.update_appearance(
            session, mode="dark", expected_version=1
        )

        # --- old AI configuration parameters ---------------------------
        _patch_ai_config(
            session,
            runtime,
            expected_version=0,
            base_url=OLD_AI_BASE_URL,
            model=OLD_AI_MODEL,
            secret=SYNTHETIC_SECRET,
            secret_provided=True,
        )

        # --- daily plan: v1, AI adoption v2, manual v3, restore v4 ------
        plan, created = daily_plan_service.create_or_open(
            session,
            plan_date=FIXTURE_PLAN_DATE,
            raw_lesson_plan=SPLIT_RAW_LESSON,
            adopted_content={
                "group_activity": {"process": "一、导入\n二、观察"},
                "reflection": "初始反思",
            },
        )
        if not created:
            raise FixtureError("the fixture daily plan unexpectedly already existed")
        plan_id = plan["id"]

        split = save_split_baseline(
            session,
            runtime,
            plan_id=plan_id,
            expected_content_version=1,
            target_grade=FIXTURE_CLASS_GRADE,
        )
        split_task_id = split["task_id"]
        split_candidate_id = split["candidate_id"]
        if split["content_version"] != 2:
            raise FixtureError("daily plan adoption did not create version 2")

        current_plan = daily_plan_service.get_plan(session, plan_id=plan_id)
        edited_adopted = dict(current_plan["content"]["adopted_content"])
        edited_adopted["reflection"] = "教师补充反思"
        daily_plan_service.save(
            session,
            plan_id=plan_id,
            expected_content_version=2,
            adopted_content=edited_adopted,
        )

        restore_preview = daily_plan_history_service.preview_restore(
            session,
            plan_id=plan_id,
            source_content_version=2,
            expected_content_version=3,
        )
        plan_restore_request_id = _request_id()
        restored_plan = daily_plan_history_service.restore(
            session,
            plan_id=plan_id,
            expected_content_version=3,
            preview_token=restore_preview["preview_token"],
            request_id=plan_restore_request_id,
        )
        if restored_plan["content_version"] != 4:
            raise FixtureError("daily plan restore did not create version 4")

        # --- weekly plan: draft + manual save + confirmation -------------
        weekly_anchor = FIXTURE_TERM_START - timedelta(
            days=FIXTURE_TERM_START.isoweekday() - 1
        )
        weekly_scope = scope_hash("fixture-page-scope")
        weekly_preview = weekly_plan_service.create_preview(
            session,
            runtime=runtime,
            profile_id=profile_id,
            launch_id="fixture-launch",
            session_scope_hash=weekly_scope,
            term_id=term_id,
            week_anchor_date=weekly_anchor,
        )
        weekly_result, _weekly_created = weekly_plan_service.create_or_open(
            session,
            runtime=runtime,
            profile_id=profile_id,
            launch_id="fixture-launch",
            session_scope_hash=weekly_scope,
            request_id=_request_id(),
            term_id=term_id,
            week_anchor_date=weekly_anchor,
            expected_config_version=int(settings.config_version),
            context_token=weekly_preview["create_token"],
        )
        weekly_plan_id = weekly_result["weekly_plan_id"]
        weekly_saved = weekly_plan_service.save_draft(
            session,
            profile_id=profile_id,
            request_id=_request_id(),
            plan_id=weekly_plan_id,
            expected_draft_version=weekly_result["draft"]["version"],
            patch={
                "theme": "秋天的树叶",
                "weekly_columns": {"key_week_focus": "观察树叶变化"},
                "deterministic_overrides": {
                    FIXTURE_PLAN_DATE.isoformat(): {
                        "morning_talk_topic": "手填晨谈"
                    }
                },
            },
        )
        weekly_facts = weekly_plan_service.confirmation_preview(
            session,
            runtime=runtime,
            profile_id=profile_id,
            launch_id="fixture-launch",
            session_scope_hash=weekly_scope,
            plan_id=weekly_plan_id,
            expected_draft_version=weekly_saved["draft"]["version"],
        )
        weekly_plan_service.confirm(
            session,
            runtime=runtime,
            profile_id=profile_id,
            launch_id="fixture-launch",
            session_scope_hash=weekly_scope,
            request_id=_request_id(),
            plan_id=weekly_plan_id,
            expected_draft_version=weekly_saved["draft"]["version"],
            context_token=weekly_facts["preview_token"],
            ack_missing=True,
            ack_stale=True,
            note="合成周计划确认",
        )
        session.expire_all()

        # --- an old personal prompt revision stays in history ----------
        # Only the daily-plan prompt service edits personal prompts; the
        # observation prompt keeps its initial revision 1 while the old
        # daily-plan execution still pins the pre-edit revision 1.
        _edit_prompt(session, "daily_lesson_split")

        # --- current AI configuration (vision-capable, still no call) ---
        _patch_ai_config(
            session,
            runtime,
            expected_version=1,
            base_url=CURRENT_AI_BASE_URL,
            model=CURRENT_AI_MODEL,
            secret=None,
            secret_provided=False,
        )

        # --- observations ----------------------------------------------
        primary = _create_observation(
            session,
            profile_id=profile_id,
            record_type="public",
            observation_date="2026-09-15",
            goal="观察幼儿合作搭建",
            process="幼儿在积木区合作搭建。",
            environment="积木区",
        )
        primary_id = primary["observation_id"]
        primary_current = _import_photo(
            session,
            runtime,
            profile_id=profile_id,
            observation_id=primary_id,
            payload=_jpeg_bytes((320, 240), 101),
            display_name="primary-current.jpg",
            caption="当前照片",
        )
        primary_historical = _import_photo(
            session,
            runtime,
            profile_id=profile_id,
            observation_id=primary_id,
            payload=_jpeg_bytes((240, 320), 102),
            display_name="primary-history-only.jpg",
            caption="历史照片",
        )
        _save_observation(
            session,
            profile_id=profile_id,
            observation_id=primary_id,
            payload={
                "observation_goal": "观察幼儿合作搭建",
                "observation_process": "幼儿在积木区合作搭建，并协商轮流。",
                "support_strategy": "提供连接材料。",
            },
            photos=[
                {"asset_id": primary_current, "caption": "当前照片"},
                {"asset_id": primary_historical, "caption": "历史照片"},
            ],
        )
        _save_observation(
            session,
            profile_id=profile_id,
            observation_id=primary_id,
            payload={
                "observation_process": "幼儿在积木区合作搭建，并协商轮流。",
                "support_strategy": "提供连接材料，鼓励共同计划。",
            },
            photos=[{"asset_id": primary_current, "caption": "当前照片"}],
        )
        primary_task = _create_observation_task(
            session, runtime, profile_id=profile_id, observation_id=primary_id
        )
        primary_claim = _claim_exact(session, runtime, primary_task["id"])
        _finalize_success_claim(session, primary_claim, _GENERATE_CANDIDATE)
        primary_candidate = session.scalars(
            select(LocalAICandidate).where(
                LocalAICandidate.task_id == primary_task["id"]
            )
        ).one()
        primary_current_view = observation_service.read_current(
            session, profile_id=profile_id, observation_id=primary_id
        )
        primary_preview = observation_ai_service.preview_adoption(
            session,
            runtime,
            profile_id=profile_id,
            observation_id=primary_id,
            candidate_id=primary_candidate.id,
            expected_revision=primary_current_view["revision"],
            expected_hash=primary_current_view["payload_hash"],
            selected_targets=["observation_goal", "observation_process"],
            request_id=_request_id(),
        )
        observation_ai_service.adopt(
            session,
            runtime,
            profile_id=profile_id,
            observation_id=primary_id,
            candidate_id=primary_candidate.id,
            expected_revision=primary_current_view["revision"],
            expected_hash=primary_current_view["payload_hash"],
            selected_targets=["observation_goal", "observation_process"],
            preview_token=primary_preview["adoption_token"],
            request_id=_request_id(),
        )
        after_adoption = observation_service.read_current(
            session, profile_id=profile_id, observation_id=primary_id
        )
        restore_request_id = _request_id()
        restore_preview = observation_history_service.preview_restore(
            session,
            runtime,
            profile_id=profile_id,
            observation_id=primary_id,
            source_version=2,
            request_id=restore_request_id,
            base_draft_revision=after_adoption["revision"],
            base_draft_hash=after_adoption["payload_hash"],
            term_decision="keep_current",
        )
        observation_history_service.restore_observation(
            session,
            runtime,
            profile_id=profile_id,
            observation_id=primary_id,
            request_id=restore_request_id,
            restore_token=restore_preview["restore_token"],
            expected_base_revision=after_adoption["revision"],
            expected_base_hash=after_adoption["payload_hash"],
            term_decision="keep_current",
        )

        failed = _create_observation(
            session,
            profile_id=profile_id,
            record_type="indoor",
            observation_date="2026-09-16",
            goal="观察室内角色游戏",
            process="幼儿在角色区分配角色。",
            environment="角色区",
        )
        failed_id = failed["observation_id"]
        failed_asset = _import_photo(
            session,
            runtime,
            profile_id=profile_id,
            observation_id=failed_id,
            payload=_png_bytes((240, 180)),
            display_name="indoor.png",
            caption="室内照片",
        )
        _save_two_versions(
            session,
            profile_id=profile_id,
            observation_id=failed_id,
            asset_id=failed_asset,
            goal="观察室内角色游戏",
            process="幼儿在角色区分配角色并协商。",
            support="提供角色标识。",
        )
        failed_task = _create_observation_task(
            session, runtime, profile_id=profile_id, observation_id=failed_id
        )
        failed_claim = _claim_exact(session, runtime, failed_task["id"])
        _finalize_failed_claim(session, failed_claim)

        unknown = _create_observation(
            session,
            profile_id=profile_id,
            record_type="outdoor",
            observation_date="2026-09-17",
            goal="观察户外追逐游戏",
            process="幼儿在操场进行追逐游戏。",
            environment="操场",
        )
        unknown_id = unknown["observation_id"]
        unknown_asset = _import_photo(
            session,
            runtime,
            profile_id=profile_id,
            observation_id=unknown_id,
            payload=_jpeg_bytes((320, 240), 103),
            display_name="outdoor.jpg",
            caption="户外照片",
        )
        _save_two_versions(
            session,
            profile_id=profile_id,
            observation_id=unknown_id,
            asset_id=unknown_asset,
            goal="观察户外追逐游戏",
            process="幼儿在操场进行追逐游戏并制定规则。",
            support="提醒注意安全距离。",
        )
        unknown_task = _create_observation_task(
            session, runtime, profile_id=profile_id, observation_id=unknown_id
        )
        unknown_claim = _claim_exact(session, runtime, unknown_task["id"])
        _finalize_unknown_claim(session, unknown_claim)

        # --- optional real capacity photos -----------------------------
        capacity_asset_ids: list[str] = []
        capacity_observation_id: str | None = None
        if capacity_photo_count:
            capacity = _create_observation(
                session,
                profile_id=profile_id,
                record_type="public",
                observation_date="2026-09-18",
                goal="容量夹具",
                process="容量夹具的合成照片集合。",
                environment="容量区",
            )
            capacity_observation_id = capacity["observation_id"]
            for index in range(capacity_photo_count):
                capacity_asset_ids.append(
                    _import_photo(
                        session,
                        runtime,
                        profile_id=profile_id,
                        observation_id=capacity_observation_id,
                        payload=_jpeg_bytes(
                            capacity_photo_size, 10_000 + index
                        ),
                        display_name=f"capacity-{index:04d}.jpg",
                        caption=None,
                    )
                )
            _save_observation(
                session,
                profile_id=profile_id,
                observation_id=capacity_observation_id,
                payload={
                    "observation_goal": "容量夹具",
                    "observation_process": "容量夹具的合成照片集合。",
                },
                photos=[
                    {"asset_id": asset_id, "caption": None}
                    for asset_id in capacity_asset_ids
                ],
            )

        evidence = _build_evidence(
            session,
            runtime,
            profile_id=profile_id,
            class_id=class_id,
            term_id=term_id,
            plan_id=plan_id,
            plan_restore_request_id=plan_restore_request_id,
            split_task_id=split_task_id,
            split_candidate_id=split_candidate_id,
            primary_id=primary_id,
            failed_id=failed_id,
            unknown_id=unknown_id,
            primary_task_id=primary_task["id"],
            failed_task_id=failed_task["id"],
            unknown_task_id=unknown_task["id"],
            primary_asset_ids={
                "primary_current": primary_current,
                "primary_historical": primary_historical,
                "failed": failed_asset,
                "unknown": unknown_asset,
            },
            capacity_asset_ids=tuple(capacity_asset_ids),
            capacity_photo_count=capacity_photo_count,
            capacity_observation_id=capacity_observation_id,
        )
    finally:
        session.close()

    checks = validate_fixture(runtime, evidence)
    if checks["runtime_fingerprint"] != evidence.fingerprint:
        raise FixtureError("the fingerprint changed during fixture validation")
    return replace(evidence, verified=True)


def _create_observation(
    session: Session,
    *,
    profile_id: str,
    record_type: str,
    observation_date: str,
    goal: str,
    process: str,
    environment: str,
) -> dict[str, Any]:
    return observation_service.create_observation(
        session,
        profile_id=profile_id,
        request_id=_request_id(),
        record_type=record_type,
        payload={
            "observation_date": observation_date,
            "record_type": record_type,
            "start_time": "09:10",
            "end_time": "09:40",
            "subjects": [{"name": "小明"}, {"name": "小红"}],
            "age_years": 5,
            "adult_count": 2,
            "child_count": 18,
            "environment": environment,
            "observation_goal": goal,
            "observation_process": process,
            "support_strategy": "",
        },
    )


def _import_photo(
    session: Session,
    runtime: Any,
    *,
    profile_id: str,
    observation_id: str,
    payload: bytes,
    display_name: str,
    caption: str | None,
) -> str:
    current = observation_service.read_current(
        session, profile_id=profile_id, observation_id=observation_id
    )
    result = observation_assets.import_asset(
        session,
        runtime,
        profile_id=profile_id,
        observation_id=observation_id,
        request_id=_request_id(),
        expected_revision=current["revision"],
        stream=io.BytesIO(payload),
        display_name=display_name,
        caption=caption,
    )
    return result["asset_id"]


def _save_observation(
    session: Session,
    *,
    profile_id: str,
    observation_id: str,
    payload: dict[str, Any],
    photos: list[dict[str, Any]],
) -> dict[str, Any]:
    current = observation_service.read_current(
        session, profile_id=profile_id, observation_id=observation_id
    )
    return observation_service.save_observation(
        session,
        profile_id=profile_id,
        observation_id=observation_id,
        request_id=_request_id(),
        expected_revision=current["revision"],
        payload=payload,
        photos=photos,
        save_reason="manual",
    )


def _save_two_versions(
    session: Session,
    *,
    profile_id: str,
    observation_id: str,
    asset_id: str,
    goal: str,
    process: str,
    support: str,
) -> None:
    _save_observation(
        session,
        profile_id=profile_id,
        observation_id=observation_id,
        payload={
            "observation_goal": goal,
            "observation_process": process,
            "support_strategy": "",
        },
        photos=[{"asset_id": asset_id, "caption": None}],
    )
    _save_observation(
        session,
        profile_id=profile_id,
        observation_id=observation_id,
        payload={"support_strategy": support},
        photos=[{"asset_id": asset_id, "caption": None}],
    )


def _create_observation_task(
    session: Session,
    runtime: Any,
    *,
    profile_id: str,
    observation_id: str,
) -> dict[str, Any]:
    current = observation_service.read_current(
        session, profile_id=profile_id, observation_id=observation_id
    )
    task, created = observation_ai_service.create_observation_task(
        session,
        runtime,
        profile_id=profile_id,
        observation_id=observation_id,
        task_type="game_observation_generate",
        expected_revision=current["revision"],
        expected_hash=current["payload_hash"],
        target=None,
        request_id=_request_id(),
    )
    if not created:
        raise FixtureError("the observation AI task was not created")
    return task


# ---------------------------------------------------------------------------
# Evidence assembly
# ---------------------------------------------------------------------------


def _build_evidence(
    session: Session,
    runtime: Any,
    *,
    profile_id: str,
    class_id: str,
    term_id: str,
    plan_id: str,
    plan_restore_request_id: str,
    split_task_id: str,
    split_candidate_id: str,
    primary_id: str,
    failed_id: str,
    unknown_id: str,
    primary_task_id: str,
    failed_task_id: str,
    unknown_task_id: str,
    primary_asset_ids: dict[str, str],
    capacity_asset_ids: tuple[str, ...],
    capacity_photo_count: int,
    capacity_observation_id: str | None,
) -> FixtureEvidence:
    session.expire_all()
    settings = session.get(LocalSettings, "singleton")
    if settings is None:
        raise FixtureError("settings disappeared after seeding")
    plan = session.get(LocalDailyPlan, plan_id)
    if plan is None:
        raise FixtureError("the seeded daily plan disappeared")
    versions = [
        int(row)
        for row in session.scalars(
            select(LocalDailyPlanContent.version)
            .where(LocalDailyPlanContent.daily_plan_id == plan_id)
            .order_by(LocalDailyPlanContent.version)
        )
    ]
    observation_ids = {
        "public": primary_id,
        "indoor": failed_id,
        "outdoor": unknown_id,
    }
    if capacity_observation_id is not None:
        observation_ids["capacity"] = capacity_observation_id
    observation_versions = {
        label: tuple(
            int(row)
            for row in session.scalars(
                select(LocalObservationVersion.version)
                .where(LocalObservationVersion.observation_id == observation_id)
                .order_by(LocalObservationVersion.version)
            )
        )
        for label, observation_id in observation_ids.items()
    }
    current_photo_asset_ids = {
        label: tuple(
            str(row)
            for row in session.scalars(
                select(LocalObservationDraftPhoto.asset_id)
                .where(
                    LocalObservationDraftPhoto.observation_id == observation_id
                )
                .order_by(LocalObservationDraftPhoto.sort_order)
            )
        )
        for label, observation_id in observation_ids.items()
    }
    version_photo_refs: dict[str, dict[int, tuple[str, ...]]] = {}
    historical_only: set[str] = set()
    for label, observation_id in observation_ids.items():
        refs: dict[int, tuple[str, ...]] = {}
        rows = session.execute(
            select(
                LocalObservationVersion.version,
                LocalObservationVersionPhoto.asset_id,
            )
            .join(
                LocalObservationVersionPhoto,
                (LocalObservationVersionPhoto.observation_id
                 == LocalObservationVersion.observation_id)
                & (LocalObservationVersionPhoto.version_id
                   == LocalObservationVersion.id),
            )
            .where(LocalObservationVersion.observation_id == observation_id)
            .order_by(
                LocalObservationVersion.version,
                LocalObservationVersionPhoto.sort_order,
            )
        ).all()
        for version, asset_id in rows:
            refs.setdefault(int(version), []).append(str(asset_id))
        version_photo_refs[label] = {
            version: tuple(asset_ids)
            for version, asset_ids in sorted(refs.items())
        }
        draft_ids = set(current_photo_asset_ids.get(label, ()))
        for asset_ids in refs.values():
            historical_only.update(set(asset_ids) - draft_ids)

    task_labels = {
        "daily_plan_split": split_task_id,
        "primary_generate": primary_task_id,
        "failed_generate": failed_task_id,
        "unknown_generate": unknown_task_id,
    }
    ai_tasks: dict[str, dict[str, Any]] = {}
    ai_executions: dict[str, dict[str, Any]] = {}
    for label, task_id in task_labels.items():
        task = session.get(LocalAITask, task_id)
        if task is None:
            raise FixtureError(f"AI task {label} disappeared")
        candidate = session.scalars(
            select(LocalAICandidate).where(LocalAICandidate.task_id == task_id)
        ).first()
        execution = (
            session.get(LocalAIExecution, task.current_execution_id)
            if task.current_execution_id
            else None
        )
        ai_tasks[label] = {
            "task_id": task.id,
            "status": task.status,
            "reason": task.reason,
            "execution_id": execution.id if execution else None,
            "candidate_id": candidate.id if candidate else None,
        }
        if execution is not None:
            ai_executions[label] = {
                "execution_id": execution.id,
                "state": execution.state,
                "config_version": execution.config_version,
                "personal_revision": execution.personal_revision,
                "contract_version": execution.contract_version,
                "default_revision": execution.default_revision,
                "launch_id": execution.launch_id,
                "permit_id": execution.permit_id,
            }

    credential = _credential_evidence(session, runtime)
    fingerprint = runtime_fingerprint(runtime)
    return FixtureEvidence(
        data_dir=Path(runtime.data_dir),
        credential_root=Path(runtime.credential_root),
        profile_id=profile_id,
        class_id=class_id,
        term_id=term_id,
        settings_config_version=int(settings.config_version),
        calendar_revision_ids=tuple(
            str(row)
            for row in session.scalars(
                select(LocalCalendarRevision.id).order_by(
                    LocalCalendarRevision.revision_no
                )
            )
        ),
        class_game_revision_ids=tuple(
            str(row)
            for row in session.scalars(
                select(LocalClassGameRevision.id).order_by(
                    LocalClassGameRevision.revision_no
                )
            )
        ),
        daily_plan_id=plan_id,
        daily_plan_content_versions=tuple(versions),
        daily_plan_current_version=int(plan.current_content_version),
        daily_plan_candidate_id=split_candidate_id,
        daily_plan_restore_request_id=plan_restore_request_id,
        observation_ids=observation_ids,
        primary_observation_id=primary_id,
        observation_versions=observation_versions,
        asset_ids=dict(primary_asset_ids),
        capacity_asset_ids=capacity_asset_ids,
        current_photo_asset_ids=current_photo_asset_ids,
        version_photo_refs=version_photo_refs,
        historical_only_asset_ids=tuple(sorted(historical_only)),
        ai_tasks=ai_tasks,
        ai_executions=ai_executions,
        credential=credential,
        capacity_photo_count=capacity_photo_count,
        counts=fingerprint["database"]["counts"],
        fingerprint=fingerprint,
        resources=fingerprint["resources"],
        schema_revision=fingerprint["database"]["schema_revision"],
        verified=False,
    )


def _credential_evidence(session: Session, runtime: Any) -> dict[str, Any]:
    state = session.scalars(select(LocalAIState)).one()
    active = session.scalars(
        select(LocalAICredential).where(
            LocalAICredential.profile_id == state.profile_id,
            LocalAICredential.state == "active",
        )
    ).all()
    if len(active) != 1:
        raise FixtureError(
            f"expected exactly one active credential, found {len(active)}"
        )
    credential = active[0]
    if credential.key_id is None or credential.nonce is None or credential.ciphertext is None:
        raise FixtureError("the active credential has no encrypted material")
    dpapi_path = (
        Path(runtime.credential_root)
        / state.database_uuid
        / f"{credential.key_id}.dpapi"
    )
    if not dpapi_path.is_file():
        raise FixtureError("the synthetic DPAPI master-key file is missing")
    return {
        "credential_id": credential.id,
        "key_id": credential.key_id,
        "state": credential.state,
        "nonce_size": len(credential.nonce),
        "ciphertext_size": len(credential.ciphertext),
        "nonce_sha256": _sha256_bytes(credential.nonce),
        "ciphertext_sha256": _sha256_bytes(credential.ciphertext),
        "database_uuid": state.database_uuid,
        "dpapi_relative_path": str(
            dpapi_path.relative_to(Path(runtime.credential_root))
        ),
        "dpapi_size": dpapi_path.stat().st_size,
        "dpapi_sha256": _sha256_file(dpapi_path),
        "synthetic_plaintext_absent": not _database_family_contains(
            Path(runtime.db_path), SYNTHETIC_SECRET.encode("utf-8")
        ),
    }


# ---------------------------------------------------------------------------
# Fingerprints
# ---------------------------------------------------------------------------


def _business_table_names() -> tuple[str, ...]:
    return tuple(sorted(LocalBase.metadata.tables))


def database_fingerprint(
    db_path: str | Path,
    *,
    include_runtime_fields: bool = False,
) -> dict[str, Any]:
    """Canonical, layout-independent fingerprint of all business tables.

    Every row of every SQLAlchemy local business table is normalized to an
    explicitly typed node tree; table SQL, column metadata and semantic counts
    are included too.  The result does not depend on page order, free pages,
    WAL checkpoints or the physical database path.  Ephemeral process/session
    identity columns are excluded by default (see
    ``RUNTIME_FIELD_EXCLUSIONS``); pass ``include_runtime_fields=True`` to
    compare them as well.
    """

    path = Path(db_path)
    if not path.is_file():
        raise FixtureFingerprintError(f"database does not exist: {path}")
    excluded = (
        {}
        if include_runtime_fields
        else dict(RUNTIME_FIELD_EXCLUSIONS)
    )
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        user_tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
            if not str(row[0]).startswith("sqlite_")
            and str(row[0]) != "local_alembic_version"
        }
        expected = set(_business_table_names())
        if user_tables != expected:
            missing = sorted(expected - user_tables)
            extra = sorted(user_tables - expected)
            raise FixtureFingerprintError(
                f"business table set differs (missing={missing}, extra={extra})"
            )
        schema_revision = _read_schema_revision(connection)
        tables: dict[str, Any] = {}
        for table_name in sorted(expected):
            tables[table_name] = _table_fingerprint(
                connection,
                table_name,
                excluded=excluded,
            )
        counts = _semantic_counts(connection)
    finally:
        connection.close()
    fingerprint = {
        "format": 1,
        "schema_revision": schema_revision,
        "tables": tables,
        "counts": counts,
        "excluded_fields": [
            {"table": table, "column": column, "reason": reason}
            for (table, column), reason in sorted(excluded.items())
        ],
    }
    fingerprint["fingerprint_sha256"] = _sha256_bytes(
        _canonical_json(fingerprint).encode("utf-8")
    )
    return fingerprint


def _read_schema_revision(connection: sqlite3.Connection) -> str:
    try:
        rows = connection.execute(
            "SELECT version_num FROM local_alembic_version"
        ).fetchall()
    except sqlite3.Error as exc:
        raise FixtureFingerprintError(
            "local_alembic_version is missing or unreadable"
        ) from exc
    if len(rows) != 1 or not isinstance(rows[0][0], str) or not rows[0][0]:
        raise FixtureFingerprintError(
            "local_alembic_version must contain exactly one revision"
        )
    return str(rows[0][0])


def _table_fingerprint(
    connection: sqlite3.Connection,
    table_name: str,
    *,
    excluded: dict[tuple[str, str], str],
) -> dict[str, Any]:
    quoted = '"' + table_name.replace('"', '""') + '"'
    info = connection.execute(f"PRAGMA table_info({quoted})").fetchall()
    db_columns = [str(row[1]) for row in info]
    metadata_table = LocalBase.metadata.tables[table_name]
    metadata_columns = [str(column.name) for column in metadata_table.columns]
    type_map = {
        str(column.name): column.type for column in metadata_table.columns
    }
    try:
        row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
    except sqlite3.Error as exc:
        raise FixtureFingerprintError(
            f"cannot read schema SQL for {table_name}"
        ) from exc
    if row is None or not isinstance(row[0], str):
        raise FixtureFingerprintError(f"missing schema SQL for {table_name}")
    normalized_sql = " ".join(row[0].split()).rstrip(";")
    rows = connection.execute(f"SELECT * FROM {quoted}").fetchall()
    excluded_columns = {
        column
        for (table, column) in excluded
        if table == table_name
    }
    canonical_rows = sorted(
        _canonical_json(_row_node(item, db_columns, type_map, excluded_columns))
        for item in rows
    )
    return {
        "sql_sha256": _sha256_bytes(normalized_sql.encode("utf-8")),
        "columns": [
            {
                "name": str(item[1]),
                "type": str(item[2] or ""),
                "notnull": int(item[3]),
                "default": item[4],
                "pk": int(item[5]),
            }
            for item in info
        ],
        "metadata_only_columns": sorted(set(metadata_columns) - set(db_columns)),
        "db_only_columns": sorted(set(db_columns) - set(metadata_columns)),
        "row_count": len(rows),
        "rows_sha256": _sha256_bytes(
            _canonical_json(canonical_rows).encode("utf-8")
        ),
    }


def _row_node(
    row: sqlite3.Row,
    columns: Iterable[str],
    type_map: dict[str, Any],
    excluded_columns: set[str],
) -> list[Any]:
    pairs = []
    for column in sorted(columns):
        if column in excluded_columns:
            continue
        pairs.append(
            [
                column,
                _value_node(row[column], type_map.get(column)),
            ]
        )
    return ["row", pairs]


def _value_node(value: Any, declared_type: Any) -> Any:
    if value is None:
        return ["null"]
    if isinstance(declared_type, JSON):
        if not isinstance(value, str):
            raise FixtureFingerprintError(
                "a JSON column did not contain text"
            )
        try:
            parsed = json.loads(value, parse_constant=_reject_json_constant)
        except ValueError as exc:
            raise FixtureFingerprintError(
                "a persisted JSON column is not valid JSON"
            ) from exc
        return ["json", _node(parsed)]
    if isinstance(declared_type, DateTime):
        if not isinstance(value, str):
            raise FixtureFingerprintError(
                "a datetime column did not contain text"
            )
        try:
            parsed_datetime = datetime.fromisoformat(value)
        except ValueError as exc:
            raise FixtureFingerprintError(
                "a persisted datetime is not ISO-formatted"
            ) from exc
        return ["datetime", parsed_datetime.isoformat()]
    if isinstance(declared_type, Date):
        if not isinstance(value, str):
            raise FixtureFingerprintError("a date column did not contain text")
        try:
            parsed_date = date.fromisoformat(value)
        except ValueError as exc:
            raise FixtureFingerprintError(
                "a persisted date is not ISO-formatted"
            ) from exc
        return ["date", parsed_date.isoformat()]
    if isinstance(value, bytes):
        return ["bytes", len(value), _sha256_bytes(value)]
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, int):
        return ["int", value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise FixtureFingerprintError("a persisted float is not finite")
        return ["float", value.hex()]
    if isinstance(value, str):
        return ["str", value]
    return ["other", type(value).__name__, repr(value)]


def _node(value: Any) -> Any:
    """Typed node tree for JSON values (no float/NULL ambiguity)."""

    if value is None:
        return ["null"]
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, int):
        return ["int", value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise FixtureFingerprintError("a persisted JSON float is not finite")
        return ["float", value.hex()]
    if isinstance(value, str):
        return ["str", value]
    if isinstance(value, list):
        return ["list", [_node(item) for item in value]]
    if isinstance(value, dict):
        pairs = []
        for key in sorted(value, key=str):
            if not isinstance(key, str):
                raise FixtureFingerprintError(
                    "a JSON object key is not a string"
                )
            pairs.append([key, _node(value[key])])
        return ["dict", pairs]
    raise FixtureFingerprintError(
        f"unsupported JSON value type: {type(value).__name__}"
    )


def _reject_json_constant(value: str) -> Any:
    raise FixtureFingerprintError(f"non-finite JSON number: {value}")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _semantic_counts(connection: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table_name in _business_table_names():
        quoted = '"' + table_name.replace('"', '""') + '"'
        counts[table_name] = int(
            connection.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]
        )
    for status in (
        "pending",
        "claimed",
        "dispatching",
        "retry_wait",
        "paused",
        "succeeded",
        "failed",
        "outcome_unknown",
        "cancelled",
    ):
        counts[f"local_ai_tasks.status.{status}"] = int(
            connection.execute(
                "SELECT COUNT(*) FROM local_ai_tasks WHERE status = ?",
                (status,),
            ).fetchone()[0]
        )
    for state in (
        "claimed",
        "dispatching",
        "retry_wait",
        "paused",
        "succeeded",
        "failed",
        "outcome_unknown",
        "cancelled",
    ):
        counts[f"local_ai_executions.state.{state}"] = int(
            connection.execute(
                "SELECT COUNT(*) FROM local_ai_executions WHERE state = ?",
                (state,),
            ).fetchone()[0]
        )
    for state in ("active", "retired", "cleared"):
        counts[f"local_ai_credentials.state.{state}"] = int(
            connection.execute(
                "SELECT COUNT(*) FROM local_ai_credentials WHERE state = ?",
                (state,),
            ).fetchone()[0]
        )
    for purpose in EXPECTED_DERIVATIVE_PURPOSES:
        counts[f"local_observation_asset_derivatives.purpose.{purpose}"] = int(
            connection.execute(
                "SELECT COUNT(*) FROM local_observation_asset_derivatives "
                "WHERE purpose = ?",
                (purpose,),
            ).fetchone()[0]
        )
    for record_type in ("public", "indoor", "outdoor"):
        counts[f"local_observation_records.type.{record_type}"] = int(
            connection.execute(
                "SELECT COUNT(*) FROM local_observation_records "
                "WHERE record_type = ?",
                (record_type,),
            ).fetchone()[0]
        )
    counts["local_observation_versions.total"] = counts[
        "local_observation_versions"
    ]
    counts["local_observation_assets.total_bytes"] = int(
        connection.execute(
            "SELECT COALESCE(SUM(byte_size), 0) FROM local_observation_assets"
        ).fetchone()[0]
    )
    counts["local_ai_candidates.total"] = counts["local_ai_candidates"]
    return counts


def resource_fingerprint(data_dir: str | Path) -> dict[str, Any]:
    """Fingerprint the managed image file set (path, size, SHA-256).

    File mtimes, absolute paths and directory enumeration order are excluded;
    the tree is rooted at ``observations/assets`` and every path is relative to
    it.  Staging entries are reported separately and must be empty in a valid
    fixture.  Symlinks/reparse points are refused rather than followed.
    """

    root = Path(data_dir) / "observations" / "assets"
    files: list[dict[str, Any]] = []
    if root.exists():
        if _is_link_like(root):
            raise FixtureFingerprintError(
                "observations/assets must not be a symlink or reparse point"
            )
        for current_root, directories, filenames in os.walk(
            root, followlinks=False
        ):
            directories.sort()
            filenames.sort()
            current_path = Path(current_root)
            for directory in directories:
                candidate = current_path / directory
                if _is_link_like(candidate):
                    raise FixtureFingerprintError(
                        f"managed asset directory is a link: {candidate}"
                    )
            for filename in filenames:
                path = current_path / filename
                if _is_link_like(path):
                    raise FixtureFingerprintError(
                        f"managed asset file is a link: {path}"
                    )
                stat = path.stat()
                files.append(
                    {
                        "path": path.relative_to(root).as_posix(),
                        "size": int(stat.st_size),
                        "sha256": _sha256_file(path),
                    }
                )
    staging_root = Path(data_dir) / "observations" / "staging"
    staging_entries: list[str] = []
    staging_files: list[str] = []
    if staging_root.exists():
        for entry in sorted(staging_root.rglob("*")):
            relative = entry.relative_to(staging_root).as_posix()
            staging_entries.append(relative)
            if entry.is_file():
                staging_files.append(relative)
    result = {
        "format": 1,
        "root": "observations/assets",
        "files": files,
        "file_count": len(files),
        "total_bytes": sum(item["size"] for item in files),
    }
    result["fingerprint_sha256"] = _sha256_bytes(
        _canonical_json(result).encode("utf-8")
    )
    return result


def staging_report(data_dir: str | Path) -> dict[str, Any]:
    """Report staging leftovers, which are deliberately outside backups.

    The image service keeps successful staging attempt *directories* for
    review; empty directories are harmless.  Any remaining staging file means
    an operation did not reach its normal cleanup boundary.
    """

    staging_root = Path(data_dir) / "observations" / "staging"
    entries: list[str] = []
    files: list[str] = []
    if staging_root.exists():
        for entry in sorted(staging_root.rglob("*")):
            relative = entry.relative_to(staging_root).as_posix()
            entries.append(relative)
            if entry.is_file():
                files.append(relative)
    return {"entries": entries, "files": files}


def runtime_fingerprint(
    runtime: Any, *, include_runtime_fields: bool = False
) -> dict[str, Any]:
    """Combine the database and managed-file fingerprints of one runtime."""

    database = database_fingerprint(
        runtime.db_path, include_runtime_fields=include_runtime_fields
    )
    resources = resource_fingerprint(runtime.data_dir)
    combined = _sha256_bytes(
        _canonical_json(
            [database["fingerprint_sha256"], resources["fingerprint_sha256"]]
        ).encode("utf-8")
    )
    return {
        "format": 1,
        "database": database,
        "resources": resources,
        "combined_sha256": combined,
    }


# ---------------------------------------------------------------------------
# Independent verification
# ---------------------------------------------------------------------------


def validate_fixture(runtime: Any, evidence: FixtureEvidence) -> dict[str, Any]:
    """Independently re-read the seeded database and files.

    This deliberately does not use backup code or the seeding helpers' return
    values: every fact is re-derived from SQLite, Pillow decoding, hashes and
    the ordinary business read services.  It returns a small check summary and
    raises :class:`FixtureError` on the first mismatch.
    """

    database_path = Path(runtime.db_path)
    if not database_path.is_file():
        raise FixtureError("fixture database is missing")
    connection = sqlite3.connect(str(database_path))
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise FixtureError("fixture database integrity_check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise FixtureError("fixture database foreign_key_check failed")
    finally:
        connection.close()

    fingerprint = runtime_fingerprint(runtime)
    if fingerprint != evidence.fingerprint:
        raise FixtureError(
            "the independently recomputed fingerprint differs from the "
            "fingerprint captured during seeding"
        )
    if fingerprint["database"]["schema_revision"] != evidence.schema_revision:
        raise FixtureError("schema revision differs from the evidence")

    staging = staging_report(runtime.data_dir)
    if staging["files"]:
        raise FixtureError(
            "managed image staging still contains files: "
            f"{staging['files']}"
        )

    session = runtime.session()
    counts_connection = sqlite3.connect(str(database_path))
    try:
        _validate_business_reads(session, evidence)
        _validate_photos(session, runtime, evidence)
        _validate_ai(session, evidence)
        _validate_credentials(session, runtime, evidence)
        counts = _semantic_counts(counts_connection)
    finally:
        counts_connection.close()
        session.close()

    if counts != evidence.counts:
        raise FixtureError("semantic counts differ from the evidence")
    return {
        "runtime_fingerprint": fingerprint,
        "integrity_check": "ok",
        "foreign_key_check": "ok",
        "business_reads": "ok",
        "photos": "ok",
        "ai": "ok",
        "credentials": "ok",
    }


def _validate_business_reads(session: Session, evidence: FixtureEvidence) -> None:
    plan = daily_plan_service.get_plan(
        session, plan_id=evidence.daily_plan_id
    )
    if int(plan["current_content_version"]) != evidence.daily_plan_current_version:
        raise FixtureError("daily plan current content pointer is inconsistent")
    if int(plan["content"]["version"]) != evidence.daily_plan_current_version:
        raise FixtureError("daily plan current content version is inconsistent")
    for version in evidence.daily_plan_content_versions:
        history = daily_plan_history_service.get_history(
            session, plan_id=evidence.daily_plan_id, version=version
        )
        if not history["content"]:
            raise FixtureError("daily plan history content is empty")
    plan_restore = session.scalars(select(LocalDailyPlanRestore)).one()
    if (
        plan_restore.source_content_version,
        plan_restore.result_content_version,
    ) != (2, 4):
        raise FixtureError("the daily-plan restore receipt is inconsistent")
    observation_restore = session.scalars(
        select(LocalObservationRestore)
    ).one()
    if (
        observation_restore.source_version,
        observation_restore.result_version,
    ) != (2, 4):
        raise FixtureError("the observation restore receipt is inconsistent")
    observation_preview = session.scalars(
        select(LocalObservationRestorePreview)
    ).one()
    if observation_preview.consumed_at is None:
        raise FixtureError("the observation restore preview was not consumed")
    for label, observation_id in evidence.observation_ids.items():
        current = observation_service.read_current(
            session,
            profile_id=evidence.profile_id,
            observation_id=observation_id,
        )
        if current["observation_id"] != observation_id:
            raise FixtureError(f"observation {label} identity changed")
        listed = observation_history_service.list_history(
            session,
            profile_id=evidence.profile_id,
            observation_id=observation_id,
        )
        got_versions = tuple(
            sorted(int(item["version"]) for item in listed)
        )
        if got_versions != evidence.observation_versions[label]:
            raise FixtureError(
                f"observation {label} history versions differ from evidence"
            )
        for version in got_versions:
            observation_history_service.read_history_version(
                session,
                profile_id=evidence.profile_id,
                observation_id=observation_id,
                version=version,
            )


def _managed_file(runtime: Any, relative: str) -> Path:
    root = Path(runtime.data_dir) / "observations" / "assets"
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise FixtureError(f"managed path is not a safe relative path: {relative}")
    absolute = Path(runtime.data_dir) / path
    if not _is_within(_resolved(absolute), _resolved(root)):
        raise FixtureError(f"managed path escaped the asset root: {relative}")
    if _is_link_like(absolute):
        raise FixtureError(f"managed file is a link or reparse point: {relative}")
    if not absolute.is_file():
        raise FixtureError(f"managed file is missing: {relative}")
    return absolute


def _validate_photos(
    session: Session, runtime: Any, evidence: FixtureEvidence
) -> None:
    assets = session.scalars(select(LocalObservationAsset)).all()
    derivatives = session.scalars(
        select(LocalObservationAssetDerivative)
    ).all()
    if not assets:
        raise FixtureError("no observation assets were seeded")
    derivative_by_id = {item.id: item for item in derivatives}
    for derivative in derivatives:
        if derivative.purpose not in EXPECTED_DERIVATIVE_PURPOSES:
            raise FixtureError(
                f"unexpected derivative purpose: {derivative.purpose}"
            )
    for asset in assets:
        path = _managed_file(runtime, asset.relative_path)
        payload = path.read_bytes()
        if len(payload) != asset.byte_size:
            raise FixtureError(f"asset size mismatch: {asset.relative_path}")
        if _sha256_bytes(payload) != asset.content_hash:
            raise FixtureError(f"asset hash mismatch: {asset.relative_path}")
        expected_format = {
            "image/jpeg": "jpeg",
            "image/png": "png",
        }.get(asset.mime_type)
        if expected_format is None:
            raise FixtureError(
                f"unexpected asset mime type: {asset.mime_type}"
            )
        width, height = _assert_decodable(
            path, expected_format=expected_format
        )
        if (width, height) != (asset.width, asset.height):
            raise FixtureError(f"asset dimensions mismatch: {asset.relative_path}")
    for derivative in derivatives:
        path = _managed_file(runtime, derivative.relative_path)
        payload = path.read_bytes()
        if _sha256_bytes(payload) != derivative.content_hash:
            raise FixtureError(
                f"derivative hash mismatch: {derivative.relative_path}"
            )
        if derivative.mime_type != "image/jpeg":
            raise FixtureError("derivatives must be JPEG")
        width, height = _assert_decodable(path, expected_format="jpeg")
        if (width, height) != (derivative.width, derivative.height):
            raise FixtureError(
                f"derivative dimensions mismatch: {derivative.relative_path}"
            )
        asset = session.get(LocalObservationAsset, derivative.asset_id)
        if asset is None:
            raise FixtureError("derivative references an unknown asset")
        if asset.observation_id != derivative.observation_id:
            raise FixtureError(
                "derivative and asset belong to different observations"
            )

    rows = session.execute(
        select(
            LocalObservationAIInputPhoto.observation_id,
            LocalObservationAIInputPhoto.asset_id,
            LocalObservationAIInputPhoto.derivative_id,
            LocalObservationAIInputPhoto.original_hash,
            LocalObservationAIInputPhoto.work_hash,
        )
    ).all()
    for observation_id, asset_id, derivative_id, original_hash, work_hash in rows:
        asset = session.get(LocalObservationAsset, asset_id)
        derivative = derivative_by_id.get(derivative_id)
        if asset is None or derivative is None:
            raise FixtureError("AI input photo reference is dangling")
        if asset.observation_id != observation_id:
            raise FixtureError("AI input asset belongs to another observation")
        if derivative.observation_id != observation_id:
            raise FixtureError("AI input derivative belongs to another observation")
        if derivative.asset_id != asset_id:
            raise FixtureError("AI input derivative belongs to another asset")
        if original_hash != asset.content_hash:
            raise FixtureError("AI input original hash mismatch")
        if work_hash != derivative.content_hash:
            raise FixtureError("AI input work hash mismatch")

    for version_row in session.scalars(select(LocalObservationVersion)).all():
        rows = session.execute(
            select(
                LocalObservationVersionPhoto.sort_order,
                LocalObservationVersionPhoto.asset_id,
            )
            .where(
                LocalObservationVersionPhoto.observation_id
                == version_row.observation_id,
                LocalObservationVersionPhoto.version_id == version_row.id,
            )
            .order_by(LocalObservationVersionPhoto.sort_order)
        ).all()
        orders = [int(row[0]) for row in rows]
        if orders and orders != list(range(len(orders))):
            raise FixtureError("version photo order is not contiguous")
        for _order, asset_id in rows:
            asset = session.get(LocalObservationAsset, asset_id)
            if asset is None:
                raise FixtureError("version photo references an unknown asset")
            if asset.observation_id != version_row.observation_id:
                raise FixtureError(
                    "version photo asset belongs to another observation"
                )

    for label, observation_id in evidence.observation_ids.items():
        current_rows = session.execute(
            select(LocalObservationDraftPhoto.asset_id)
            .where(LocalObservationDraftPhoto.observation_id == observation_id)
            .order_by(LocalObservationDraftPhoto.sort_order)
        ).all()
        current_ids = tuple(str(row[0]) for row in current_rows)
        if current_ids != evidence.current_photo_asset_ids[label]:
            raise FixtureError(
                f"current photo set of {label} differs from evidence"
            )
        orders = [
            int(item)
            for item in session.scalars(
                select(LocalObservationDraftPhoto.sort_order)
                .where(
                    LocalObservationDraftPhoto.observation_id == observation_id
                )
                .order_by(LocalObservationDraftPhoto.sort_order)
            )
        ]
        if orders and orders != list(range(len(orders))):
            raise FixtureError("draft photo order is not contiguous")

    for asset_id in evidence.historical_only_asset_ids:
        version_refs = session.scalars(
            select(LocalObservationVersionPhoto.asset_id).where(
                LocalObservationVersionPhoto.asset_id == asset_id
            )
        ).all()
        draft_refs = session.scalars(
            select(LocalObservationDraftPhoto.asset_id).where(
                LocalObservationDraftPhoto.asset_id == asset_id
            )
        ).all()
        if not version_refs or draft_refs:
            raise FixtureError(
                "a historical-only photo is not referenced only by history"
            )


def _validate_ai(session: Session, evidence: FixtureEvidence) -> None:
    statuses = {label: item["status"] for label, item in evidence.ai_tasks.items()}
    expected = {
        "daily_plan_split": "succeeded",
        "primary_generate": "succeeded",
        "failed_generate": "failed",
        "unknown_generate": "outcome_unknown",
    }
    if statuses != expected:
        raise FixtureError(f"AI task statuses differ: {statuses}")
    for label, item in evidence.ai_tasks.items():
        task = session.get(LocalAITask, item["task_id"])
        if task is None or task.status != item["status"]:
            raise FixtureError(f"AI task {label} is missing or changed")
        if label in ("failed_generate", "unknown_generate"):
            candidate = session.scalars(
                select(LocalAICandidate).where(
                    LocalAICandidate.task_id == item["task_id"]
                )
            ).first()
            if candidate is not None:
                raise FixtureError(
                    f"failed/unknown AI task {label} must not have a candidate"
                )
        else:
            if item["candidate_id"] is None:
                raise FixtureError(f"succeeded AI task {label} has no candidate")
            candidate = session.get(LocalAICandidate, item["candidate_id"])
            if candidate is None:
                raise FixtureError(f"succeeded AI task {label} candidate missing")
            if candidate.contract_version < 1:
                raise FixtureError("candidate contract_version is invalid")
            if candidate.schema_version < 1:
                raise FixtureError("candidate schema_version is invalid")
        if item["execution_id"] is None:
            raise FixtureError(f"AI task {label} has no execution")
        attempts = session.scalars(
            select(LocalAIAttempt).where(
                LocalAIAttempt.execution_id == item["execution_id"]
            )
        ).all()
        if not attempts:
            raise FixtureError(f"AI task {label} has no attempt history")

    daily_provenance = session.scalars(
        select(LocalDailyPlanAIProvenance).where(
            LocalDailyPlanAIProvenance.daily_plan_id == evidence.daily_plan_id,
            LocalDailyPlanAIProvenance.content_version == 2,
        )
    ).one_or_none()
    if (
        daily_provenance is None
        or daily_provenance.adopted_candidate_id
        != evidence.daily_plan_candidate_id
    ):
        raise FixtureError("the daily-plan adoption provenance is missing")
    adopted_content = session.scalars(
        select(LocalDailyPlanContent).where(
            LocalDailyPlanContent.daily_plan_id == evidence.daily_plan_id,
            LocalDailyPlanContent.version == 2,
        )
    ).one_or_none()
    if adopted_content is None or adopted_content.split_baseline is None:
        raise FixtureError("the adopted split baseline is missing")
    observation_provenance = session.scalars(
        select(LocalObservationAIProvenance).where(
            LocalObservationAIProvenance.observation_id
            == evidence.primary_observation_id
        )
    ).all()
    primary_candidate_id = evidence.ai_tasks["primary_generate"]["candidate_id"]
    if not any(
        row.candidate_id == primary_candidate_id
        for row in observation_provenance
    ):
        raise FixtureError("the observation AI provenance is missing")
    old = evidence.ai_executions["daily_plan_split"]
    current = evidence.ai_executions["primary_generate"]
    if old["config_version"] >= current["config_version"]:
        raise FixtureError("the old execution does not preserve an older config")
    if old["personal_revision"] != 1:
        raise FixtureError(
            "the old execution does not preserve the initial prompt revision"
        )
    split_head = session.get(
        LocalPersonalPromptHead, (evidence.profile_id, "daily_lesson_split")
    )
    if split_head is None or split_head.current_revision <= 1:
        raise FixtureError(
            "the daily-plan prompt head did not advance past the pinned revision"
        )
    if old["contract_version"] != 1:
        raise FixtureError("the old execution contract_version is not 1")
    bundles = session.scalars(select(LocalPromptBundle)).all()
    if not bundles:
        raise FixtureError("no prompt bundles were registered")
    heads = session.scalars(select(LocalPersonalPromptHead)).all()
    if not heads:
        raise FixtureError("no personal prompt heads were seeded")
    versions = session.scalars(select(LocalPersonalPromptVersion)).all()
    if not any(version.revision == 1 for version in versions):
        raise FixtureError("the initial personal prompt revision is missing")
    configs = session.scalars(select(LocalAIConfigVersion)).all()
    if len(configs) < 2:
        raise FixtureError("the old/current AI configuration history is missing")


def _validate_credentials(
    session: Session, runtime: Any, evidence: FixtureEvidence
) -> None:
    credential = evidence.credential
    row = session.get(LocalAICredential, credential["credential_id"])
    if row is None or row.state != "active":
        raise FixtureError("the active credential row is missing")
    if row.key_id != credential["key_id"]:
        raise FixtureError("the credential key id changed")
    if row.nonce is None or len(row.nonce) != 12:
        raise FixtureError("the credential nonce is not 12 bytes")
    if row.ciphertext is None or len(row.ciphertext) < 16:
        raise FixtureError("the credential ciphertext is too short")
    if _sha256_bytes(row.nonce) != credential["nonce_sha256"]:
        raise FixtureError("the credential nonce hash changed")
    if _sha256_bytes(row.ciphertext) != credential["ciphertext_sha256"]:
        raise FixtureError("the credential ciphertext hash changed")
    state = session.scalars(select(LocalAIState)).one()
    if state.database_uuid != credential["database_uuid"]:
        raise FixtureError("the credential database UUID changed")
    dpapi_path = (
        Path(runtime.credential_root)
        / state.database_uuid
        / f"{row.key_id}.dpapi"
    )
    if not dpapi_path.is_file():
        raise FixtureError("the synthetic DPAPI master-key file is missing")
    if dpapi_path.stat().st_size != credential["dpapi_size"]:
        raise FixtureError("the synthetic DPAPI master-key size changed")
    if _sha256_file(dpapi_path) != credential["dpapi_sha256"]:
        raise FixtureError("the synthetic DPAPI master-key hash changed")
    if _database_family_contains(
        Path(runtime.db_path), SYNTHETIC_SECRET.encode("utf-8")
    ):
        raise FixtureError("the synthetic plaintext secret is present in SQLite")


__all__ = [
    "FixtureError",
    "FixtureFingerprintError",
    "FixtureRootError",
    "FixtureEvidence",
    "RUNTIME_FIELD_EXCLUSIONS",
    "database_fingerprint",
    "resource_fingerprint",
    "runtime_fingerprint",
    "seed_existing_runtime",
    "staging_report",
    "validate_fixture",
]
