"""Local manual daily plan service: create/open, read, list and save.

Transaction rules (D1A spec §6): the final write transaction issues
``BEGIN IMMEDIATE`` before any business read; parameters and content
structure are validated outside the lock; the lock re-reads context, date
and current version, appends content, updates the pointer with an
old-version condition and rowcount check, writes the audit record and
commits. Only a successful commit is a successful save.

Reads run inside an explicit ``BEGIN`` so every response is built from one
snapshot. A duplicate same-day create is recognized only from the effective
-date partial unique index and then re-read as "open the existing plan" in
a new transaction; no other integrity failure is disguised.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ids import new_opaque_id
from app.local.base import utc_now
from app.local.ai_provenance import resolve_baseline
from app.local.errors import (
    LocalConfigVersionConflict,
    LocalDateNotEligible,
    LocalOutsideTerm,
    LocalPlanNotFound,
    LocalStorageError,
    LocalTermNotFound,
    LocalValidationError,
    LocalVersionConflict,
    LocalYearNotCovered,
)
from app.local.models import (
    LocalCalendarDay,
    LocalCalendarRevision,
    LocalDailyPlan,
    LocalDailyPlanAIProvenance,
    LocalDailyPlanContent,
    LocalOperationRecord,
    LocalTerm,
)
from app.local.normalize import normalize_raw_lesson_plan
from app.local.profile_service import require_context
from app.local.tx import (
    begin_immediate,
    is_unique_violation,
    read_scope,
    rollback,
)
from app.services import calendar_service as cal
from app.services.daily_plan_content import (
    ContentValidationError,
    collect_identity_sets,
    materialize_adopted_content,
    parse_adopted_content,
    prepare_content,
)

MAX_LIST_LIMIT = 200
DEFAULT_LIST_LIMIT = 100

CREATE_ACTION = "create_daily_plan"
UPDATE_ACTION = "update_daily_plan"
PLAN_TARGET_TYPE = "daily_plan"

# Columns of the partial unique index used for same-day duplicates.
_EFFECTIVE_UNIQUE_COLUMNS = ("class_id", "plan_date")


class _Unset:
    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return "UNSET"


UNSET = _Unset()


def plan_payload(plan: LocalDailyPlan, content: LocalDailyPlanContent) -> dict:
    """Daily plan detail: identity/date/header/pointer/content/times.

    Same shape as the reviewed v1 ``DailyPlanOut`` minus the legacy weekly
    projection summary (no replacement placeholder is generated).
    """
    return {
        "id": plan.id,
        "class_id": plan.class_id,
        "term_id": plan.term_id,
        "plan_date": plan.plan_date,
        "week_number": plan.week_number,
        "weekday": plan.weekday,
        "calendar_revision_id": plan.calendar_revision_id,
        "creator_id": plan.creator_id,
        "creator_display_name": plan.creator_display_name,
        "current_content_id": plan.current_content_id,
        "current_content_version": plan.current_content_version,
        "content": {
            "id": content.id,
            "version": content.version,
            "raw_lesson_plan": content.raw_lesson_plan,
            "split_baseline": content.split_baseline,
            "adopted_content": content.adopted_content,
            "editor_id": content.editor_id,
            "created_at": content.created_at,
        },
        "school_name": plan.school_name,
        "class_name": plan.class_name,
        "grade": plan.grade,
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
    }


def list_item(plan: LocalDailyPlan) -> dict:
    return {
        "id": plan.id,
        "plan_date": plan.plan_date,
        "week_number": plan.week_number,
        "weekday": plan.weekday,
        "creator_id": plan.creator_id,
        "creator_display_name": plan.creator_display_name,
        "current_content_version": plan.current_content_version,
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
    }


def term_list_item(plan: LocalDailyPlan) -> dict:
    """Term-scoped list item: stored class/term ownership is included."""
    item = list_item(plan)
    item["class_id"] = plan.class_id
    item["term_id"] = plan.term_id
    return item


_STORED_CONTENT_CORRUPT = "计划内容持久数据损坏"


def _stored_identity_violation(adopted: object) -> bool:
    """True when stored IDs could not have been written by this server.

    Every group and game object in a server-written snapshot owns a
    non-empty opaque ID, and IDs are unique across the whole content. A
    violation means the persisted row was corrupted outside the normal
    write path; it is refused as a storage error, never repaired.
    """
    if not isinstance(adopted, dict):
        return True
    groups: list[object] = []
    for section in ("morning_games", "post_group_games"):
        value = adopted.get(section)
        if isinstance(value, list):
            groups.extend(value)
    afternoon = adopted.get("afternoon_outdoor")
    if isinstance(afternoon, dict):
        groups.append(afternoon)
    seen_groups: set[str] = set()
    seen_games: set[str] = set()
    for group in groups:
        group_id = group.get("group_id") if isinstance(group, dict) else None
        if not isinstance(group_id, str) or not group_id or group_id in seen_groups:
            return True
        seen_groups.add(group_id)
        games = group.get("games") if isinstance(group, dict) else None
        for game in games if isinstance(games, list) else []:
            game_id = game.get("game_id") if isinstance(game, dict) else None
            if not isinstance(game_id, str) or not game_id or game_id in seen_games:
                return True
            seen_games.add(game_id)
    return False


def _validate_stored_content(
    session: Session, plan: LocalDailyPlan, content: LocalDailyPlanContent
) -> None:
    """Refuse persisted content no server write could have produced (503).

    Structure only: this never generates IDs, normalizes values or drops
    data. Client-supplied input keeps its own 422 path in ``save``.

    D1A manual content keeps a server-owned ``split_baseline`` of ``null``
    (spec §5). D2 AI adoption may persist a legal baseline, but only together
    with a matching provenance row pointing at a same-plan split candidate
    whose raw process is exactly that value: the shared
    :mod:`app.local.ai_provenance` validator accepts that combination and
    refuses everything else. A corrupt baseline is never repaired, cleared or
    copied forward (R4).
    """
    try:
        parse_adopted_content(content.adopted_content)
    except ContentValidationError:
        raise LocalStorageError(_STORED_CONTENT_CORRUPT) from None
    if _stored_identity_violation(content.adopted_content):
        raise LocalStorageError(_STORED_CONTENT_CORRUPT)
    resolve_baseline(session, plan, content)


def _load_content(session: Session, plan: LocalDailyPlan) -> LocalDailyPlanContent:
    try:
        content = session.get(
            LocalDailyPlanContent, plan.current_content_id, populate_existing=True
        )
    except ValueError:
        # json.JSONDecodeError for a raw TEXT value that is not valid JSON.
        raise LocalStorageError(_STORED_CONTENT_CORRUPT) from None
    if (
        content is None
        or content.daily_plan_id != plan.id
        or content.version != plan.current_content_version
    ):
        raise LocalStorageError("计划内容指针不一致")
    _validate_stored_content(session, plan, content)
    return content


def _find_effective_by_date(
    session: Session, class_id: str, plan_date: date
) -> LocalDailyPlan | None:
    rows = list(
        session.scalars(
            select(LocalDailyPlan).where(
                LocalDailyPlan.class_id == class_id,
                LocalDailyPlan.plan_date == plan_date,
                LocalDailyPlan.deleted_at.is_(None),
            )
        ).all()
    )
    if len(rows) > 1:
        raise LocalStorageError("同一日期存在多份有效计划")
    return rows[0] if rows else None


def _plan_by_id(session: Session, plan_id: str) -> LocalDailyPlan:
    plan = session.get(LocalDailyPlan, plan_id, populate_existing=True)
    if plan is None or plan.deleted_at is not None:
        raise LocalPlanNotFound()
    return plan


def _resolve_create_date(
    session: Session, plan_date: date
) -> tuple[LocalTerm, int, int]:
    """Term membership and teaching eligibility from persisted revisions.

    D1B §10.1: the date resolves against *all* terms by its non-overlapping
    range; the browse selection never limits creation. Only the term's
    persisted current revision is read — never a live recompute.
    """
    terms = list(
        session.scalars(select(LocalTerm).order_by(LocalTerm.start_date)).all()
    )
    term = next(
        (t for t in terms if t.start_date <= plan_date <= t.end_date), None
    )
    if term is None:
        raise LocalOutsideTerm()
    if term.current_calendar_revision_id is None:
        raise LocalStorageError("学期缺少当前日历修订")
    revision = session.get(LocalCalendarRevision, term.current_calendar_revision_id)
    if revision is None or revision.term_id != term.id:
        raise LocalStorageError("当前日历修订缺失")
    day = session.get(LocalCalendarDay, (revision.id, plan_date))
    if day is None:
        raise LocalStorageError("日历快照缺少目标日期")
    if day.effective_state == cal.UNKNOWN:
        raise LocalYearNotCovered()
    if day.effective_state != cal.TEACHING:
        raise LocalDateNotEligible()
    week_number, _week_start, weekday = cal.week_info(term.start_date, plan_date)
    return term, week_number, weekday


def get_plan(session: Session, *, plan_id: str) -> dict:
    """Plan detail by id inside one read snapshot; soft-deleted is 404."""
    with read_scope(session):
        context = require_context(session, date.today())
        plan = _plan_by_id(session, plan_id)
        if plan.class_id != context.school_class.id:
            raise LocalPlanNotFound()
        content = _load_content(session, plan)
        return plan_payload(plan, content)


def get_by_date(session: Session, *, plan_date: date) -> dict:
    with read_scope(session):
        context = require_context(session, date.today())
        plan = _find_effective_by_date(session, context.school_class.id, plan_date)
        if plan is None:
            raise LocalPlanNotFound()
        content = _load_content(session, plan)
        return plan_payload(plan, content)


def list_plans(
    session: Session,
    *,
    from_date: date,
    to_date: date,
    offset: int,
    limit: int,
) -> dict:
    if from_date > to_date:
        raise LocalValidationError("from 不能晚于 to")
    if offset < 0 or limit < 1 or limit > MAX_LIST_LIMIT:
        raise LocalValidationError("分页参数超出允许范围")
    with read_scope(session):
        context = require_context(session, date.today())
        conditions = [
            LocalDailyPlan.class_id == context.school_class.id,
            LocalDailyPlan.deleted_at.is_(None),
            LocalDailyPlan.plan_date >= from_date,
            LocalDailyPlan.plan_date <= to_date,
        ]
        total = (
            session.scalar(
                select(func.count()).select_from(LocalDailyPlan).where(*conditions)
            )
            or 0
        )
        rows = list(
            session.scalars(
                select(LocalDailyPlan)
                .where(*conditions)
                .order_by(LocalDailyPlan.plan_date, LocalDailyPlan.id)
                .offset(offset)
                .limit(limit)
            ).all()
        )
        return {
            "items": [list_item(row) for row in rows],
            "total": int(total),
            "offset": offset,
            "limit": limit,
        }


def list_plans_by_term(
    session: Session,
    *,
    term_id: str,
    offset: int,
    limit: int,
) -> dict:
    """Old-term entry (D1B §10.1): all effective records by *stored* term_id.

    Records are never re-filtered through the term's possibly edited date
    range, so a plan moved out of the current range stays visible. A missing
    term is 404 ``TERM_NOT_FOUND``.
    """
    if offset < 0 or limit < 1 or limit > MAX_LIST_LIMIT:
        raise LocalValidationError("分页参数超出允许范围")
    with read_scope(session):
        context = require_context(session, date.today())
        term = session.get(LocalTerm, term_id)
        if term is None:
            raise LocalTermNotFound()
        conditions = [
            LocalDailyPlan.class_id == context.school_class.id,
            LocalDailyPlan.deleted_at.is_(None),
            LocalDailyPlan.term_id == term_id,
        ]
        total = (
            session.scalar(
                select(func.count()).select_from(LocalDailyPlan).where(*conditions)
            )
            or 0
        )
        rows = list(
            session.scalars(
                select(LocalDailyPlan)
                .where(*conditions)
                .order_by(LocalDailyPlan.plan_date, LocalDailyPlan.id)
                .offset(offset)
                .limit(limit)
            ).all()
        )
        return {
            "items": [term_list_item(row) for row in rows],
            "total": int(total),
            "offset": offset,
            "limit": limit,
        }


def _open_existing_payload(
    session: Session, class_id: str, plan_date: date
) -> dict | None:
    """Read the committed winner in a new read transaction (post-conflict)."""
    with read_scope(session):
        require_context(session, date.today())
        plan = _find_effective_by_date(session, class_id, plan_date)
        if plan is None:
            return None
        content = _load_content(session, plan)
        return plan_payload(plan, content)


def create_or_open(
    session: Session,
    *,
    plan_date: date,
    raw_lesson_plan: object = UNSET,
    adopted_content: object = UNSET,
    expected_config_version: object = None,
) -> tuple[dict, bool]:
    """Create version 1 or open the existing effective same-day plan.

    ``expected_config_version`` (D1B §10.1) is the configuration version the
    page last read; a mismatch is 409 ``CONFIG_VERSION_CONFLICT`` with the
    latest version in ``error.details`` and creates nothing. Existing
    same-day records still open first, so a stale version never blocks
    reading.
    """
    if expected_config_version is not None and (
        not isinstance(expected_config_version, int)
        or isinstance(expected_config_version, bool)
        or expected_config_version < 1
    ):
        raise LocalValidationError("expected_config_version 必须是 >= 1 的整数")
    raw_value = (
        None
        if raw_lesson_plan is UNSET
        else normalize_raw_lesson_plan(raw_lesson_plan)
    )
    if adopted_content is UNSET:
        adopted_value: object = {}
    else:
        adopted_value = adopted_content
    try:
        prepared = prepare_content(
            adopted_value,
            allowed_group_ids=frozenset(),
            allowed_game_ids=frozenset(),
        )
    except ContentValidationError as exc:
        raise LocalValidationError(exc.message) from None

    begin_immediate(session)
    class_id: str | None = None
    try:
        context = require_context(session, date.today())
        class_id = context.school_class.id
        # Existing effective records are read first: a committed plan must
        # stay openable even when the date's creation eligibility changed.
        existing = _find_effective_by_date(session, class_id, plan_date)
        if existing is not None:
            rollback(session)
            payload = _open_existing_payload(session, class_id, plan_date)
            if payload is None:  # pragma: no cover - no delete API in D1A
                raise LocalStorageError("有效计划意外缺失")
            return payload, False

        # Only a date without an existing record resolves the current
        # configuration; the page's last-read version must still match.
        if (
            expected_config_version is not None
            and context.settings is not None
            and context.settings.config_version != expected_config_version
        ):
            raise LocalConfigVersionConflict(
                details={"config_version": context.settings.config_version}
            )

        term, week_number, weekday = _resolve_create_date(session, plan_date)

        now = utc_now()
        plan_id = new_opaque_id()
        content_id = new_opaque_id()
        plan = LocalDailyPlan(
            id=plan_id,
            class_id=context.school_class.id,
            term_id=term.id,
            plan_date=plan_date,
            creator_id=context.profile.id,
            week_number=week_number,
            weekday=weekday,
            calendar_revision_id=term.current_calendar_revision_id,
            current_content_id=content_id,
            current_content_version=1,
            creator_display_name=context.profile.display_name,
            school_name=context.settings.school_name,
            class_name=context.school_class.name,
            grade=context.school_class.grade,
            deleted_at=None,
            deleted_by=None,
            created_at=now,
            updated_at=now,
        )
        session.add(plan)
        session.flush()

        content = LocalDailyPlanContent(
            id=content_id,
            daily_plan_id=plan_id,
            version=1,
            raw_lesson_plan=raw_value,
            split_baseline=None,
            adopted_content=prepared,
            editor_id=context.profile.id,
            created_at=now,
        )
        session.add(content)
        session.flush()

        # D2 §2.2: every D2-created version carries a provenance row. A new
        # manual version has no baseline and no adopted candidate.
        session.add(
            LocalDailyPlanAIProvenance(
                content_id=content_id,
                daily_plan_id=plan_id,
                content_version=1,
                baseline_candidate_id=None,
                adopted_candidate_id=None,
                selected_targets_json={},
                adopted_payload_hash=None,
                created_at=now,
            )
        )
        session.flush()

        _record_operation(
            session,
            actor_id=context.profile.id,
            action=CREATE_ACTION,
            target_id=plan_id,
            target_version_after=1,
            created_at=now,
        )
        session.commit()
    except IntegrityError as exc:
        rollback(session)
        if is_unique_violation(exc, columns=_EFFECTIVE_UNIQUE_COLUMNS):
            payload = _open_existing_payload(
                session, class_id or "", plan_date
            )
            if payload is None:
                raise LocalStorageError() from exc
            return payload, False
        raise
    except BaseException:
        rollback(session)
        raise
    return plan_payload(plan, content), True


def save(
    session: Session,
    *,
    plan_id: str,
    expected_content_version: object,
    raw_lesson_plan: object = UNSET,
    adopted_content: object = UNSET,
) -> dict:
    """Append the next content version; stale expected versions are 409."""
    if (
        not isinstance(expected_content_version, int)
        or isinstance(expected_content_version, bool)
        or expected_content_version < 1
    ):
        raise LocalValidationError("expected_content_version 必须是 >= 1 的整数")

    # Lock-free pure validation (D1A review R5): raw normalization and the
    # adopted_content structure parse never touch the database, so invalid
    # input answers 422 immediately instead of waiting on the write lock.
    # Identity membership against the stored version is still decided inside
    # the lock below; no version or ownership value is cached out here.
    if raw_lesson_plan is UNSET:
        normalized_raw: str | None = None
    else:
        normalized_raw = normalize_raw_lesson_plan(raw_lesson_plan)
    parsed_adopted = None
    if adopted_content is not UNSET:
        try:
            parsed_adopted = parse_adopted_content(adopted_content)
        except ContentValidationError as exc:
            raise LocalValidationError(exc.message) from None

    begin_immediate(session)
    try:
        context = require_context(session, date.today())
        plan = _plan_by_id(session, plan_id)
        if plan.class_id != context.school_class.id:
            raise LocalPlanNotFound()

        current = _load_content(session, plan)
        if plan.current_content_version != expected_content_version:
            raise LocalVersionConflict()

        if raw_lesson_plan is UNSET:
            new_raw = current.raw_lesson_plan
        else:
            new_raw = normalized_raw

        if adopted_content is UNSET:
            new_adopted = current.adopted_content
        else:
            group_ids, game_ids = collect_identity_sets(current.adopted_content)
            assert parsed_adopted is not None
            try:
                new_adopted = materialize_adopted_content(
                    parsed_adopted,
                    allowed_group_ids=group_ids,
                    allowed_game_ids=game_ids,
                )
            except ContentValidationError as exc:
                raise LocalValidationError(exc.message) from None

        now = utc_now()
        new_version = current.version + 1
        new_content_id = new_opaque_id()
        # The current baseline source identity is validated (storage error for
        # a corrupt combination) and inherited: a later manual save or a raw
        # text change never silently drops or rebuilds the adopted baseline.
        baseline_candidate_id, baseline_value = resolve_baseline(
            session, plan, current
        )
        new_content = LocalDailyPlanContent(
            id=new_content_id,
            daily_plan_id=plan.id,
            version=new_version,
            raw_lesson_plan=new_raw,
            # Split baseline is server-owned; a manual save inherits it and
            # clients can never inject one.
            split_baseline=baseline_value,
            adopted_content=new_adopted,
            editor_id=context.profile.id,
            created_at=now,
        )
        session.add(new_content)
        session.flush()

        session.add(
            LocalDailyPlanAIProvenance(
                content_id=new_content_id,
                daily_plan_id=plan.id,
                content_version=new_version,
                baseline_candidate_id=baseline_candidate_id,
                adopted_candidate_id=None,
                selected_targets_json={},
                adopted_payload_hash=None,
                created_at=now,
            )
        )
        session.flush()

        updated = session.execute(
            update(LocalDailyPlan)
            .where(
                LocalDailyPlan.id == plan.id,
                LocalDailyPlan.deleted_at.is_(None),
                LocalDailyPlan.current_content_version == expected_content_version,
            )
            .values(
                current_content_id=new_content_id,
                current_content_version=new_version,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if updated.rowcount != 1:
            raise LocalVersionConflict()

        session.refresh(plan)
        _record_operation(
            session,
            actor_id=context.profile.id,
            action=UPDATE_ACTION,
            target_id=plan.id,
            target_version_after=new_version,
            created_at=now,
        )
        session.commit()
    except BaseException:
        rollback(session)
        raise
    return plan_payload(plan, new_content)


def _record_operation(
    session: Session,
    *,
    actor_id: str,
    action: str,
    target_id: str,
    target_version_after: int,
    created_at,
) -> None:
    session.add(
        LocalOperationRecord(
            id=new_opaque_id(),
            created_at=created_at,
            actor_id=actor_id,
            action=action,
            target_type=PLAN_TARGET_TYPE,
            target_id=target_id,
            target_version_after=target_version_after,
        )
    )
    session.flush()
