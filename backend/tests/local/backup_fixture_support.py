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
import math
import os
import random
import sqlite3
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageDraw
from sqlalchemy import Date, DateTime, JSON, func, select
from sqlalchemy.orm import Session

from app.local import (
    ai_adoption,
    ai_config_service,
    ai_task_service,
    config_service,
    daily_plan_history_service,
    daily_plan_service,
    observation_ai_service,
    observation_assets,
    observation_history_service,
    observation_service,
    profile_service,
    prompt_service,
)
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

_SPLIT_CANDIDATE = {
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
            raw_lesson_plan="原始教案：秋天的树叶（合成夹具）",
            adopted_content={
                "group_activity": {"process": "一、导入\n二、观察"},
                "reflection": "初始反思",
            },
        )
        if not created:
            raise FixtureError("the fixture daily plan unexpectedly already existed")
        plan_id = plan["id"]

        task, created = ai_task_service.create_task(
            session,
            plan_id=plan_id,
            task_type="daily_lesson_split",
            expected_content_version=1,
            target_grade=FIXTURE_CLASS_GRADE,
            request_id=_request_id(),
        )
        if not created:
            raise FixtureError("the daily plan AI task was not created")
        split_task_id = task["id"]
        split_claim = _claim_exact(session, runtime, split_task_id)
        _finalize_success_claim(session, split_claim, _SPLIT_CANDIDATE)
        split_candidate = session.scalars(
            select(LocalAICandidate).where(LocalAICandidate.task_id == split_task_id)
        ).one()
        split_candidate_id = split_candidate.id

        preview = ai_adoption.preview_adoption(
            session,
            plan_id=plan_id,
            candidate_id=split_candidate_id,
            expected_content_version=1,
            selected_targets=["group_activity"],
            edited_candidate=_SPLIT_CANDIDATE,
        )
        adopted = ai_adoption.adopt(
            session,
            plan_id=plan_id,
            candidate_id=split_candidate_id,
            expected_content_version=1,
            preview_token=preview["preview_token"],
            request_id=_request_id(),
        )
        if adopted["content_version"] != 2:
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
