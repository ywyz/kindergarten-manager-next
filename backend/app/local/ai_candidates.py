"""D2 W4 candidate read service: bounded list, detail, applicability.

Engineering spec §5.1–§5.3, §9.3. A candidate is immutable: these reads never
touch content, a version or the candidate row. The list deliberately omits the
candidate body (``raw_candidate``) and the source excerpt; only the detail
returns them. A candidate whose plan does not match the requested plan is
reported as a plain 404 (unified with "not found") so a caller can never probe
another plan's candidates.

Applicability is derived from the *current* plan content and the task's
current required contract, not from the task status:

* ``eligible`` — the generation input still projects to the same dependency
  hash and the candidate's contract is the currently required one;
* ``source_changed`` — a real source dependency changed;
* ``contract_obsolete`` — the candidate's contract is outside this build's
  supported set or below the task's current required contract, so the
  candidate is view-only.

An integrity-checked candidate body is required for reads and adoption; a
tampered/malformed candidate is a storage error, never silently returned.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.local import ai_inputs
from app.local.ai_provenance import load_candidate_for_plan, require_candidate_chain
from app.local.ai_task_service import (
    SUPPORTED_CONTRACT_VERSIONS,
    _decode_cursor,
    _encode_cursor,
    _load_plan_and_content,
    _profile_id,
)
from app.local.errors import (
    LocalAiNotFound,
    LocalStorageError,
    LocalValidationError,
)
from app.local.models import (
    LocalAICandidate,
    LocalAIInput,
    LocalPersonalPromptHead,
)
from app.local.profile_service import require_context
from app.local.tx import read_scope

TARGET_GROUP_ACTIVITY = "group_activity"
TARGET_PROCESS = "group_activity.process"

OTHER_BOARDS: tuple[str, ...] = (
    "morning_games",
    "morning_talk",
    "post_group_games",
    "afternoon_outdoor",
)

DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 100

STATE_ELIGIBLE = "eligible"
STATE_SOURCE_CHANGED = "source_changed"
STATE_CONTRACT_OBSOLETE = "contract_obsolete"


def raw_candidate(
    session: Session, plan: Any, candidate: LocalAICandidate
) -> dict[str, Any]:
    """The candidate body after full chain validation (corrupt -> 503)."""
    raw, _execution, _input = require_candidate_chain(session, plan, candidate)
    return raw


def chain(session: Session, plan: Any, candidate: LocalAICandidate):
    """``(raw, execution, input)`` after full chain validation."""
    return require_candidate_chain(session, plan, candidate)


def available_targets(task_type: str, raw: dict[str, Any]) -> list[str]:
    """The replaceable targets this candidate actually provides."""
    if task_type == "daily_lesson_split":
        return [TARGET_GROUP_ACTIVITY]
    if task_type == "daily_process_adapt":
        return [TARGET_PROCESS]
    return [board for board in OTHER_BOARDS if raw.get(board) is not None]


def required_contract_version(
    session: Session, profile_id: str, task_type: str
) -> int | None:
    """The task's currently required contract, or None when no head exists."""
    head = session.get(LocalPersonalPromptHead, (profile_id, task_type))
    return head.required_contract_version if head is not None else None


def contract_adoptable(
    session: Session, profile_id: str, candidate: LocalAICandidate
) -> bool:
    """True only when the candidate's contract is the current required one."""
    if candidate.contract_version not in SUPPORTED_CONTRACT_VERSIONS:
        return False
    required = required_contract_version(session, profile_id, candidate.task_type)
    return required is not None and candidate.contract_version == required


def _require_candidate(
    session: Session, plan: Any, candidate_id: str
) -> LocalAICandidate:
    # Scoped by plan in SQL: a foreign-plan candidate is a plain 404 even when
    # its own JSON is corrupt (it is never materialised/decoded).
    candidate = load_candidate_for_plan(session, plan.id, candidate_id)
    if candidate is None or candidate.daily_plan_id != plan.id:
        raise LocalAiNotFound("未找到该 AI 候选")
    return candidate


def candidate_applicability(
    session: Session,
    profile_id: str,
    plan: Any,
    content: Any,
    candidate: LocalAICandidate,
    input_row: LocalAIInput | None,
) -> str:
    if not contract_adoptable(session, profile_id, candidate):
        return STATE_CONTRACT_OBSOLETE
    if input_row is None:
        return STATE_SOURCE_CHANGED
    if ai_inputs.dependency_matches(
        session, plan=plan, content=content, input_row=input_row
    ):
        return STATE_ELIGIBLE
    return STATE_SOURCE_CHANGED


def source_change_details(
    session: Session,
    plan: Any,
    content: Any,
    input_row: LocalAIInput,
) -> dict[str, Any]:
    """A safe hint of *which* dependency fields changed (names only).

    Never contains material: only the top-level business dependency keys whose
    canonical value differs, or a generic marker when the source cannot be
    projected at all (e.g. the raw lesson plan was cleared).
    """
    from app.local.prompt_bundles import canonical_json

    try:
        projected = ai_inputs.project_input(
            session,
            plan=plan,
            content=content,
            task_type=input_row.task_type,
            target_grade=input_row.target_grade,
        )
    except Exception:  # noqa: BLE001 - any projection failure is a safe hint only
        return {"changed_fields": ["source"]}
    old = ai_inputs.business_dependency_view(input_row.dependencies_json or {})
    new = ai_inputs.business_dependency_view(projected.dependencies)
    keys = set(old) | set(new)
    changed = sorted(
        key
        for key in keys
        if canonical_json(old.get(key)) != canonical_json(new.get(key))
    )
    return {"changed_fields": changed[:32] or ["dependency_hash"]}


def _summary(
    session: Session,
    profile_id: str,
    plan: Any,
    content: Any,
    candidate: LocalAICandidate,
) -> dict[str, Any]:
    raw, _execution, input_row = chain(session, plan, candidate)
    return {
        "id": candidate.id,
        "plan_id": candidate.daily_plan_id,
        "task_id": candidate.task_id,
        "execution_id": candidate.execution_id,
        "task_type": candidate.task_type,
        "contract_version": candidate.contract_version,
        "schema_version": candidate.schema_version,
        "adoption_state": candidate_applicability(
            session, profile_id, plan, content, candidate, input_row
        ),
        "available_targets": available_targets(candidate.task_type, raw),
        "latest_content_version": content.version,
        "created_at": candidate.created_at.isoformat()
        if candidate.created_at
        else None,
    }


def list_candidates(
    session: Session,
    *,
    plan_id: str,
    limit: object = DEFAULT_LIST_LIMIT,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Bounded cursor page of one plan's candidates (no candidate body)."""
    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= MAX_LIST_LIMIT
    ):
        raise LocalValidationError("limit 必须在 1–100 之间")
    with read_scope(session):
        profile_id = _profile_id(session)
        context = require_context(session, date.today())
        plan, content = _load_plan_and_content(session, plan_id)
        if plan.class_id != context.school_class.id:
            raise LocalAiNotFound("未找到该日计划")
        statement = select(LocalAICandidate).where(
            LocalAICandidate.daily_plan_id == plan.id
        )
        if cursor:
            created, candidate_id = _decode_cursor(cursor)
            statement = statement.where(
                (LocalAICandidate.created_at > created)
                | (
                    (LocalAICandidate.created_at == created)
                    & (LocalAICandidate.id > candidate_id)
                )
            )
        statement = statement.order_by(
            LocalAICandidate.created_at, LocalAICandidate.id
        ).limit(limit + 1)
        try:
            rows = list(session.scalars(statement).all())
        except ValueError:
            # A candidate row whose JSON column is corrupt fails while being
            # materialised; that is a storage error, never a 500.
            raise LocalStorageError("候选内容损坏") from None
        next_cursor: str | None = None
        if len(rows) > limit:
            rows = rows[:limit]
            last = rows[-1]
            next_cursor = _encode_cursor(last.created_at, last.id)
        return {
            "items": [
                _summary(session, profile_id, plan, content, row) for row in rows
            ],
            "next_cursor": next_cursor,
        }


def get_candidate(
    session: Session, *, plan_id: str, candidate_id: str
) -> dict[str, Any]:
    """Candidate detail including its real source and available targets."""
    with read_scope(session):
        profile_id = _profile_id(session)
        context = require_context(session, date.today())
        plan, content = _load_plan_and_content(session, plan_id)
        if plan.class_id != context.school_class.id:
            raise LocalAiNotFound("未找到该日计划")
        candidate = _require_candidate(session, plan, candidate_id)
        detail = _summary(session, profile_id, plan, content, candidate)
        raw, _execution, input_row = chain(session, plan, candidate)
        detail["raw_candidate"] = raw
        detail["source"] = {
            "content_version": input_row.content_version,
            "target_grade": input_row.target_grade,
            "dependency_hash": input_row.dependency_hash,
            "dependencies": ai_inputs.business_dependency_view(
                input_row.dependencies_json or {}
            ),
            "source_excerpt": ai_inputs.source_excerpt(
                input_row.task_type,
                input_row.payload_json or {},
                input_row.dependencies_json or {},
            ),
        }
        return detail


__all__ = [
    "DEFAULT_LIST_LIMIT",
    "MAX_LIST_LIMIT",
    "OTHER_BOARDS",
    "STATE_CONTRACT_OBSOLETE",
    "STATE_ELIGIBLE",
    "STATE_SOURCE_CHANGED",
    "TARGET_GROUP_ACTIVITY",
    "TARGET_PROCESS",
    "available_targets",
    "candidate_applicability",
    "chain",
    "contract_adoptable",
    "get_candidate",
    "list_candidates",
    "raw_candidate",
    "required_contract_version",
    "source_change_details",
]
