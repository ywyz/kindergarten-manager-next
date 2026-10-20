"""D2 W4 shared candidate-chain and split-baseline validation.

The split baseline is server-owned. In D2 it is exactly
``{"group_activity_process": <string>}`` whose value is the **model** split
process of the referenced ``daily_lesson_split`` candidate — never a value
edited by the teacher in the adoption preview (product spec §9.3.7,
engineering spec §2.2).

A candidate is only usable (for reads, preview and adoption) when its whole
chain is intact:

* its body still matches the stored ``candidate_hash`` and the frozen output
  schema for a supported contract;
* its execution exists, belongs to the same plan / task / input / task type,
  pins the same contract, and **succeeded**;
* its task exists with the same plan / input / task type and status
  ``succeeded``;
* its input snapshot exists and belongs to the same plan / task type.

A persisted non-null baseline additionally needs a matching provenance row for
the exact content triple, a same-plan ``daily_lesson_split`` candidate with a
valid chain, and a baseline value equal to that candidate's raw model process
(an empty string is a legal value, distinct from a ``null`` "no baseline").

Anything else — missing provenance, a failure-injected execution, a tampered or
malformed candidate body, a missing input, a non-string process — is a storage
error: it is refused, never silently cleared, repaired or downgraded. Old D1
content keeps a ``null`` baseline and no provenance row, which stays legal. The
current *required contract* is deliberately **not** consulted here: a
historical baseline referring to an old-contract split candidate must stay
readable and exportable after a contract upgrade (W4 review R04).
"""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.local.errors import LocalStorageError
from app.local.models import (
    LocalAICandidate,
    LocalAIExecution,
    LocalAIInput,
    LocalAITask,
    LocalDailyPlan,
    LocalDailyPlanAIProvenance,
    LocalDailyPlanContent,
)
from app.local.prompt_bundles import (
    PACKAGE_CONTRACT_VERSION,
    TASK_TYPES,
    CandidateInvalid,
    canonical_json,
    validate_candidate,
)

BASELINE_KEY = "group_activity_process"
_BASELINE_KEYS = frozenset({BASELINE_KEY})

_SPLIT_TASK_TYPE = "daily_lesson_split"

# This build only ships the frozen v1 contract; candidate bodies pinned to a
# contract outside this set are historical (readable, not re-schema-checked).
_SUPPORTED_CONTRACT_VERSIONS = (PACKAGE_CONTRACT_VERSION,)


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def load_candidate(
    session: Session, candidate_id: str
) -> LocalAICandidate | None:
    """Load a candidate, mapping a corrupt JSON column to a storage error.

    SQLAlchemy decodes a JSON column while materialising the row, so a
    ``raw_candidate_json`` written as non-JSON text raises ``ValueError``
    *inside* ``session.get`` — before any body-level check can run. Without
    this wrapper that would surface as an internal error instead of a 503
    storage error (W4 review R04, malformed-candidate boundary).
    """
    try:
        return session.get(LocalAICandidate, candidate_id)
    except ValueError:
        raise LocalStorageError("候选内容损坏") from None


def load_candidate_for_plan(
    session: Session, plan_id: str, candidate_id: str
) -> LocalAICandidate | None:
    """Load a candidate scoped to its plan **in the SQL query itself**.

    A candidate that belongs to another plan must be a plain 404 even when its
    own JSON column is corrupt: filtering by ``daily_plan_id`` on the row means
    a foreign row is never materialised (and therefore never decoded), while a
    corrupt candidate of *this* plan is still a 503 storage error (W4 R08).
    """
    try:
        return session.scalars(
            select(LocalAICandidate).where(
                LocalAICandidate.id == candidate_id,
                LocalAICandidate.daily_plan_id == plan_id,
            )
        ).first()
    except ValueError:
        raise LocalStorageError("候选内容损坏") from None


def baseline_from_model_process(process: object) -> dict[str, str]:
    """Build the fixed baseline shape from a raw model process value.

    A non-string process is corrupt input and is refused, never silently
    coerced to an empty string; a genuine empty string is preserved.
    """
    if not isinstance(process, str):
        raise LocalStorageError("拆分候选过程字段损坏")
    return {BASELINE_KEY: process}


def validate_candidate_body(candidate: LocalAICandidate) -> dict[str, Any]:
    """Body-only integrity check: task type, stored hash and frozen schema."""
    if candidate.task_type not in TASK_TYPES:
        raise LocalStorageError("候选任务类型损坏")
    try:
        raw = candidate.raw_candidate_json
    except ValueError:
        raise LocalStorageError("候选内容损坏") from None
    if not isinstance(raw, dict):
        raise LocalStorageError("候选内容损坏")
    if _digest(raw) != candidate.candidate_hash:
        raise LocalStorageError("候选摘要与内容不一致")
    if candidate.contract_version in _SUPPORTED_CONTRACT_VERSIONS:
        try:
            normalized = validate_candidate(candidate.task_type, raw)
        except CandidateInvalid:
            raise LocalStorageError("候选结构损坏") from None
        if canonical_json(normalized) != canonical_json(raw):
            raise LocalStorageError("候选结构损坏")
    return raw


def require_candidate_chain(
    session: Session, plan: LocalDailyPlan, candidate: LocalAICandidate
) -> tuple[dict[str, Any], LocalAIExecution, LocalAIInput]:
    """Validate one candidate's full relationship chain, or raise.

    Used uniformly for list/detail reads, preview and adoption (W4 review R04):
    a failure-injected execution, a missing input or a task/input mismatch must
    never be silently treated as "source changed" or "eligible".
    """
    raw = validate_candidate_body(candidate)
    try:
        execution = session.get(LocalAIExecution, candidate.execution_id)
        task = session.get(LocalAITask, candidate.task_id)
        input_row = session.get(LocalAIInput, candidate.input_id)
    except ValueError:
        raise LocalStorageError("候选关系链损坏") from None
    if execution is None or task is None or input_row is None:
        raise LocalStorageError("候选关系链缺失")
    if (
        execution.state != "succeeded"
        or execution.daily_plan_id != plan.id
        or execution.task_id != candidate.task_id
        or execution.input_id != candidate.input_id
        or execution.task_type != candidate.task_type
        or execution.contract_version != candidate.contract_version
    ):
        raise LocalStorageError("候选执行与候选不一致")
    if (
        task.daily_plan_id != plan.id
        or task.input_id != candidate.input_id
        or task.task_type != candidate.task_type
        or task.status != "succeeded"
    ):
        raise LocalStorageError("候选任务与候选不一致")
    if (
        input_row.daily_plan_id != plan.id
        or input_row.task_type != candidate.task_type
    ):
        raise LocalStorageError("候选输入来源关系损坏")
    return raw, execution, input_row


def _candidate_process(raw: dict[str, Any]) -> str | None:
    group = raw.get("group_activity")
    process = group.get("process") if isinstance(group, dict) else None
    return process if isinstance(process, str) else None


def resolve_baseline(
    session: Session,
    plan: LocalDailyPlan,
    content: LocalDailyPlanContent,
) -> tuple[str | None, Any]:
    """Return ``(baseline_candidate_id, baseline_value)`` after full validation.

    ``(None, None)`` is the legal "no baseline" state (old D1 content or a
    manual plan). Any corrupt combination raises ``LocalStorageError``.
    """
    try:
        provenance = session.get(LocalDailyPlanAIProvenance, content.id)
    except ValueError:  # json.JSONDecodeError for a corrupt JSON column
        raise LocalStorageError("AI 内容来源关联损坏") from None

    if provenance is not None and (
        provenance.daily_plan_id != plan.id
        or provenance.content_version != content.version
    ):
        raise LocalStorageError("AI 内容来源关联与内容不一致")

    baseline = content.split_baseline
    if baseline is None:
        if provenance is not None and provenance.baseline_candidate_id is not None:
            raise LocalStorageError("内容无基准却存在基准来源关联")
        return None, None

    if not isinstance(baseline, dict) or set(baseline.keys()) != _BASELINE_KEYS:
        raise LocalStorageError("拆分基准结构非法")
    value = baseline.get(BASELINE_KEY)
    if not isinstance(value, str):
        raise LocalStorageError("拆分基准结构非法")

    if provenance is None or not provenance.baseline_candidate_id:
        raise LocalStorageError("非空基准缺少来源关联")
    candidate = load_candidate(session, provenance.baseline_candidate_id)
    if candidate is None or candidate.daily_plan_id != plan.id:
        raise LocalStorageError("基准候选缺失或跨计划")
    if candidate.task_type != _SPLIT_TASK_TYPE:
        raise LocalStorageError("基准候选不是拆分候选")

    raw, _execution, _input = require_candidate_chain(session, plan, candidate)
    if _candidate_process(raw) != value:
        raise LocalStorageError("拆分基准与来源候选内容不一致")
    return provenance.baseline_candidate_id, baseline


__all__ = [
    "BASELINE_KEY",
    "baseline_from_model_process",
    "load_candidate",
    "load_candidate_for_plan",
    "require_candidate_chain",
    "resolve_baseline",
    "validate_candidate_body",
]
