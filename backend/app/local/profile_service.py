"""Local profile context, one-shot atomic initialization and retry rules.

Processing order follows the D1A spec §4: normalize -> short read
transaction checks the committed initialization record -> build the full
calendar candidate outside the lock -> ``BEGIN IMMEDIATE`` and re-check ->
create profile, settings, class, term, calendar revision/days and audit in
one transaction -> only a committed result becomes ``ready``.

Retry semantics: the same request_id with the same normalized input reads
the *current* configuration back (200); maintenance performed after the
initialization is never rolled back to the first input. The same
request_id with different input returns ``INITIALIZATION_REQUEST_CONFLICT``;
any other request_id after initialization returns ``ALREADY_INITIALIZED``.

D1B §10.1: the context resolves any number of terms. ``as_of_date`` (host
local date when omitted) selects the term/revision shown in the original
``term``/``calendar_revision`` fields; outside every term both are null
while the profile stays ``ready``. The full term list is returned sorted by
``(start_date, id)``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from app.ids import new_opaque_id
from app.local.base import utc_now
from app.local.calendar_build import CalendarDayCandidate, build_calendar_candidate
from app.local.errors import (
    LocalAlreadyInitialized,
    LocalInitializationConflict,
    LocalProfileRequired,
    LocalStorageError,
)
from app.local.models import (
    LocalAIState,
    LocalCalendarDay,
    LocalCalendarRevision,
    LocalClass,
    LocalClassGameHead,
    LocalClassGameRevision,
    LocalOperationRecord,
    LocalPersonalPromptHead,
    LocalPersonalPromptVersion,
    LocalProfile,
    LocalSettings,
    LocalTerm,
)
from app.local.normalize import NormalizedInitialization
from app.local.prompt_bundles import effective_prompt_seed
from app.local.tx import begin_immediate, read_scope, rollback

INIT_PROFILE_ACTION = "initialize_local_profile"
PROFILE_TARGET_TYPE = "local_profile"


@dataclass(frozen=True)
class LocalContext:
    profile: LocalProfile | None
    settings: LocalSettings | None
    school_class: LocalClass | None
    # All terms, ordered by (start_date, id).
    terms: tuple[LocalTerm, ...]
    as_of_date: date
    # Term containing as_of_date (or None) and its current revision.
    term: LocalTerm | None
    revision: LocalCalendarRevision | None

    @property
    def initialized(self) -> bool:
        return self.profile is not None


def _any_business_rows(session: Session) -> bool:
    for model in (LocalClass, LocalTerm, LocalCalendarRevision):
        count = session.scalar(select(func.count()).select_from(model)) or 0
        if count:
            return True
    return False


def _term_revision(
    session: Session, term: LocalTerm
) -> LocalCalendarRevision:
    """Load and validate one term's current calendar revision pointer."""
    revision_id = term.current_calendar_revision_id
    if revision_id is None:
        raise LocalStorageError("学期缺少当前日历修订")
    revision = session.get(LocalCalendarRevision, revision_id)
    if revision is None or revision.term_id != term.id:
        raise LocalStorageError("当前日历修订缺失")
    return revision


def load_context(session: Session, as_of_date: date) -> LocalContext:
    """Load the profile context; partial/corrupt data is a storage error.

    Never falls back to first-setup semantics over an existing database.
    Every persisted term must own its current revision; a dangling or
    foreign pointer is a storage error for the whole context read.
    """
    profile = session.scalars(
        select(LocalProfile).where(LocalProfile.singleton == 1)
    ).one_or_none()
    settings = session.get(LocalSettings, "singleton")
    if profile is None:
        if settings is not None or _any_business_rows(session):
            raise LocalStorageError("本地档案数据不完整")
        return LocalContext(None, None, None, (), as_of_date, None, None)
    if settings is None:
        raise LocalStorageError("本地设置缺失")
    school_class = session.get(LocalClass, settings.current_class_id)
    if school_class is None:
        raise LocalStorageError("当前班级缺失")
    terms = tuple(
        session.scalars(
            select(LocalTerm).order_by(LocalTerm.start_date, LocalTerm.id)
        ).all()
    )
    if not terms:
        raise LocalStorageError("学期缺失")
    # Validate every pointer: the configuration is only readable when each
    # term owns its revision (a dangling pointer would silently hide data).
    for term in terms:
        _term_revision(session, term)
    term = next(
        (t for t in terms if t.start_date <= as_of_date <= t.end_date), None
    )
    revision = _term_revision(session, term) if term is not None else None
    return LocalContext(
        profile, settings, school_class, terms, as_of_date, term, revision
    )


def require_context(session: Session, as_of_date: date) -> LocalContext:
    """Like ``load_context`` but refuses uninitialized databases (409)."""
    context = load_context(session, as_of_date)
    if not context.initialized:
        raise LocalProfileRequired()
    return context


def context_payload(context: LocalContext) -> dict:
    if not context.initialized:
        return {"status": "uninitialized"}
    assert context.settings is not None
    assert context.school_class is not None
    payload: dict = {
        "status": "ready",
        "profile": {
            "id": context.profile.id,
            "display_name": context.profile.display_name,
        },
        "school_name": context.settings.school_name,
        "class": {
            "id": context.school_class.id,
            "name": context.school_class.name,
            "grade": context.school_class.grade,
        },
        "config_version": context.settings.config_version,
        "as_of_date": context.as_of_date.isoformat(),
        "terms": [
            {
                "id": term.id,
                "name": term.name,
                "start_date": term.start_date.isoformat(),
                "end_date": term.end_date.isoformat(),
                "current_calendar_revision_id": term.current_calendar_revision_id,
            }
            for term in context.terms
        ],
        "term": None,
        "calendar_revision": None,
    }
    if context.term is not None and context.revision is not None:
        payload["term"] = {
            "id": context.term.id,
            "name": context.term.name,
            "start_date": context.term.start_date.isoformat(),
            "end_date": context.term.end_date.isoformat(),
        }
        payload["calendar_revision"] = {
            "id": context.revision.id,
            "revision_no": context.revision.revision_no,
            "library_version": context.revision.library_version,
        }
    return payload


def read_context(session: Session, as_of_date: date | None = None) -> dict:
    """Read the context inside one explicit read transaction."""
    target = as_of_date if as_of_date is not None else date.today()
    with read_scope(session):
        return context_payload(load_context(session, target))


def _check_retry(context: LocalContext, normalized: NormalizedInitialization) -> None:
    assert context.settings is not None
    if context.settings.init_request_id == normalized.request_id:
        if context.settings.init_input_fingerprint == normalized.fingerprint():
            return
        raise LocalInitializationConflict()
    raise LocalAlreadyInitialized()


def _existing_decision(
    session: Session,
    normalized: NormalizedInitialization,
    as_of_date: date,
) -> dict | None:
    """Return the current ready payload when committed, else None.

    After maintenance this must read the *current* configuration: the
    retry never rolls later changes back to the first input.
    """
    with read_scope(session):
        context = load_context(session, as_of_date)
        if not context.initialized:
            return None
        _check_retry(context, normalized)
        return context_payload(context)


def initialize(
    session: Session,
    normalized: NormalizedInitialization,
    as_of_date: date | None = None,
) -> tuple[dict, bool]:
    """Create the single local profile atomically; returns (payload, created)."""
    target = as_of_date if as_of_date is not None else date.today()
    payload = _existing_decision(session, normalized, target)
    if payload is not None:
        return payload, False

    candidates, library_version = build_calendar_candidate(
        normalized.start_date, normalized.end_date
    )

    begin_immediate(session)
    try:
        context = load_context(session, target)
        if context.initialized:
            # Another process committed between the precheck and this lock.
            rollback(session)
            payload = _existing_decision(session, normalized, target)
            if payload is None:  # pragma: no cover - unreachable by protocol
                raise LocalStorageError()
            return payload, False
        _create_initialized(session, normalized, candidates, library_version)
        session.commit()
    except BaseException:
        rollback(session)
        raise

    return read_context(session, target), True


def _create_initialized(
    session: Session,
    normalized: NormalizedInitialization,
    candidates: list[CalendarDayCandidate],
    library_version: str,
) -> None:
    now = utc_now()
    profile_id = new_opaque_id()
    class_id = new_opaque_id()
    term_id = new_opaque_id()
    revision_id = new_opaque_id()

    profile = LocalProfile(
        id=profile_id,
        singleton=1,
        display_name=normalized.display_name,
        created_at=now,
        updated_at=now,
    )
    school_class = LocalClass(
        id=class_id,
        name=normalized.class_name,
        grade=normalized.grade,
        created_at=now,
        updated_at=now,
    )
    term = LocalTerm(
        id=term_id,
        name=normalized.term_name,
        start_date=normalized.start_date,
        end_date=normalized.end_date,
        # Preallocated first-revision ID: the non-null composite deferred FK
        # lets the term commit together with its first revision only.
        current_calendar_revision_id=revision_id,
        created_at=now,
        updated_at=now,
    )
    revision = LocalCalendarRevision(
        id=revision_id,
        term_id=term_id,
        revision_no=1,
        library_version=library_version,
        created_by=profile_id,
        created_at=now,
    )
    settings = LocalSettings(
        id="singleton",
        singleton=1,
        school_name=normalized.school_name,
        current_class_id=class_id,
        init_request_id=normalized.request_id,
        init_input_fingerprint=normalized.fingerprint(),
        config_version=1,
        created_at=now,
        updated_at=now,
    )

    session.add(profile)
    session.flush()
    session.add(school_class)
    session.flush()
    # Term first (pointer to the still-to-be-inserted revision; the composite
    # FK is deferred), then its first revision; COMMIT checks both together.
    session.add(term)
    session.flush()
    session.add(revision)
    session.flush()
    session.add(settings)
    session.flush()

    if candidates:
        session.execute(
            insert(LocalCalendarDay),
            [
                {
                    "revision_id": revision_id,
                    "date": candidate.day,
                    "base_state": candidate.base_state,
                    "base_library_version": candidate.base_library_version,
                    "override_state": None,
                    "override_reason": None,
                    "effective_state": candidate.effective_state,
                }
                for candidate in candidates
            ],
        )

    session.add(
        LocalOperationRecord(
            id=new_opaque_id(),
            created_at=now,
            actor_id=profile_id,
            action=INIT_PROFILE_ACTION,
            target_type=PROFILE_TARGET_TYPE,
            target_id=profile_id,
            target_version_after=None,
        )
    )
    session.flush()

    # --- D2 W1 initialization: AI state, personal prompt heads, empty class ---
    # game revision/head. Same frozen seed as migration 0004 so new archives
    # and upgraded archives are equivalent.
    empty_game_payload = {"locations": [], "game_scope": None, "guidance": None}
    empty_game_hash = hashlib.sha256(
        json.dumps(empty_game_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    database_uuid = str(__import__("uuid").uuid4())
    session.add(
        LocalAIState(
            profile_id=profile_id,
            database_uuid=database_uuid,
            current_config_version=None,
            blocked_config_version=None,
            blocked_reason=None,
            created_at=now,
            updated_at=now,
        )
    )

    initial_seed = effective_prompt_seed(session)

    for task_type, seed in initial_seed.items():
        prompt_rev_id = new_opaque_id()
        session.add(
            LocalPersonalPromptVersion(
                profile_id=profile_id,
                task_type=task_type,
                revision=1,
                contract_version=seed["contract_version"],
                based_default_revision=seed["default_revision"],
                guidance_json=seed["guidance"],
                orphaned_guidance_json=None,
                action="initial",
                rejected_default_revision=None,
                created_at=now,
            )
        )
        session.add(
            LocalPersonalPromptHead(
                profile_id=profile_id,
                task_type=task_type,
                current_revision=1,
                required_contract_version=seed["contract_version"],
                latest_default_revision=seed["default_revision"],
                created_at=now,
                updated_at=now,
            )
        )

    game_rev_id = new_opaque_id()
    session.add(
        LocalClassGameRevision(
            id=game_rev_id,
            class_id=class_id,
            revision_no=1,
            payload_json=empty_game_payload,
            payload_hash=empty_game_hash,
            created_at=now,
        )
    )
    session.add(
        LocalClassGameHead(
            class_id=class_id,
            current_revision_id=game_rev_id,
            created_at=now,
            updated_at=now,
        )
    )
