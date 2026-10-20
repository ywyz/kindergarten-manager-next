"""D2 W4 candidate adoption: strict preview, bounded token, atomic apply.

Engineering spec §2.2, §5.1–§5.3, §9.3; product spec §9.3.

Flow:

* ``preview_adoption`` validates the teacher edit against the *same* frozen
  candidate contract, requires a non-empty, unique target set that is a subset
  of the boards the candidate actually provides, records no persistence and
  returns a short-lived in-memory token bound to launch/profile/plan/
  candidate/current version/targets/edit hash/dependency hash/target hash.
* ``adopt`` reads a committed receipt first (so a lost response replays even
  after the token is consumed or the process restarted), then the token, then
  re-verifies the pinned contract (against the task's *current required*
  contract), the token-bound version, the source dependency, the selected
  target values, the edit hash and the content version inside one
  ``BEGIN IMMEDIATE`` transaction: merge the selected fields, assign server
  ids, append one content version + provenance row, CAS the plan's current
  content triple (id **and** version), write the receipt and the audit row,
  and COMMIT — all or nothing. The token is consumed only after a successful
  commit.

The split baseline is taken from the **raw model** process, never from the
teacher-edited preview value; adapt / other-activities / later manual saves
inherit the existing baseline and its source identity.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import secrets
import threading
import time
from collections import OrderedDict
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.ids import new_opaque_id
from app.local import ai_candidates, ai_inputs
from app.local.ai_provenance import (
    baseline_from_model_process,
    require_candidate_chain,
    resolve_baseline,
)
from app.local.ai_task_service import (
    _find_receipt,
    _fingerprint,
    _load_plan_and_content,
    _normalize_request_id,
    _profile_id,
    _replay,
    _store_receipt,
)
from app.local.base import utc_now
from app.local.daily_plan_service import _record_operation
from app.local.errors import (
    LocalAiContractObsolete,
    LocalAiNotFound,
    LocalAiPreviewExpired,
    LocalAiSourceChanged,
    LocalAiTargetChanged,
    LocalStorageError,
    LocalValidationError,
    LocalVersionConflict,
)
from app.local.models import (
    LocalAICandidate,
    LocalDailyPlan,
    LocalDailyPlanAIProvenance,
    LocalDailyPlanContent,
)
from app.local.profile_service import require_context
from app.local.prompt_bundles import (
    TASK_TYPES,
    CandidateInvalid,
    canonical_json,
    validate_candidate,
)
from app.local.tx import begin_immediate, read_scope, rollback
from app.services.daily_plan_content import (
    ContentValidationError,
    collect_identity_sets,
    materialize_adopted_content,
    parse_adopted_content,
)

OP_ADOPT = "ai_candidate_adopt"
ADOPTION_AUDIT_ACTION = "adopt_ai_candidate"

# Fixed by the spec: adoption preview tokens are valid for 10 minutes and the
# current session keeps at most 64 of them (evicting the oldest requires a new
# preview).
ADOPTION_TTL_SECONDS = 600
MAX_TOKENS = 64

SPLIT_FIELDS = (
    "theme",
    "objectives",
    "preparation",
    "key_points",
    "difficult_points",
    "process",
)


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _now() -> float:
    """Seam over the clock so token expiry is testable."""
    return time.time()


# ---------------------------------------------------------------------------
# In-memory bounded token store
# ---------------------------------------------------------------------------


class _TokenStore:
    """Bounded, process-local store of preview tokens (never persisted)."""

    def __init__(self) -> None:
        self._items: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
        self._lock = threading.Lock()

    def issue(self, payload: dict[str, Any], now: float) -> tuple[str, float]:
        token = (
            base64.urlsafe_b64encode(secrets.token_bytes(32))
            .rstrip(b"=")
            .decode("ascii")
        )
        expires_at = now + ADOPTION_TTL_SECONDS
        payload = dict(payload)
        payload["exp"] = expires_at
        with self._lock:
            self._evict_expired(now)
            while len(self._items) >= MAX_TOKENS:
                self._items.popitem(last=False)
            self._items[token] = {"payload": payload, "expires_at": expires_at}
        return token, expires_at

    def get(self, token: object) -> dict[str, Any] | None:
        if not isinstance(token, str) or not token:
            return None
        now = _now()
        with self._lock:
            entry = self._items.get(token)
            if entry is None:
                return None
            if entry["expires_at"] <= now:
                self._items.pop(token, None)
                return None
            return entry["payload"]

    def consume(self, token: object) -> None:
        if not isinstance(token, str):
            return
        with self._lock:
            self._items.pop(token, None)

    def reset(self) -> None:
        with self._lock:
            self._items.clear()

    def _evict_expired(self, now: float) -> None:
        expired = [
            key for key, entry in self._items.items() if entry["expires_at"] <= now
        ]
        for key in expired:
            self._items.pop(key, None)


_TOKENS = _TokenStore()


def reset_tokens() -> None:
    """Test seam: drop every outstanding token without touching the DB."""
    _TOKENS.reset()


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_positive_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise LocalValidationError(f"{label} 必须是 >= 1 的整数")
    return value


def _validate_edit(task_type: str, edited: object) -> dict[str, Any]:
    """Validate the teacher edit against the frozen candidate contract."""
    if not isinstance(edited, dict):
        raise LocalValidationError("edited_candidate 必须是对象")
    try:
        return validate_candidate(task_type, edited)
    except CandidateInvalid as exc:
        # ``validate_candidate`` only carries safe field locations / rule types.
        raise LocalValidationError(str(exc)) from None


def _validate_targets(
    task_type: str, raw: dict[str, Any], selected: object
) -> list[str]:
    if not isinstance(selected, list) or not selected:
        raise LocalValidationError("selected_targets 必须是非空列表")
    ordered: list[str] = []
    for target in selected:
        if not isinstance(target, str) or not target:
            raise LocalValidationError("selected_targets 必须是非空字符串")
        if target in ordered:
            raise LocalValidationError("selected_targets 不得重复")
        ordered.append(target)
    allowed = ai_candidates.available_targets(task_type, raw)
    for target in ordered:
        if target not in allowed:
            raise LocalValidationError("selected_targets 必须是该候选已提供板块的子集")
    return ordered


def _raw_process(raw: dict[str, Any]) -> str | None:
    group = raw.get("group_activity")
    process = group.get("process") if isinstance(group, dict) else None
    return process if isinstance(process, str) else None


def _dumped(content: LocalDailyPlanContent) -> dict[str, Any]:
    try:
        return parse_adopted_content(content.adopted_content).model_dump(
            exclude_none=True
        )
    except ContentValidationError:
        raise LocalStorageError("计划内容无法解析") from None


def _current_value(dumped: dict[str, Any], target: str) -> Any:
    if target == ai_candidates.TARGET_GROUP_ACTIVITY:
        return ai_inputs._strip_ids(dumped.get("group_activity"))
    if target == ai_candidates.TARGET_PROCESS:
        group = dumped.get("group_activity") or {}
        return group.get("process")
    return ai_inputs._strip_ids(dumped.get(target))


def _edited_value(edited: dict[str, Any], target: str) -> Any:
    if target == ai_candidates.TARGET_GROUP_ACTIVITY:
        return edited.get("group_activity")
    if target == ai_candidates.TARGET_PROCESS:
        return edited.get("process")
    return edited.get(target)


def _target_hash(content: LocalDailyPlanContent, selected: list[str]) -> str:
    dumped = _dumped(content)
    return _digest({target: _current_value(dumped, target) for target in selected})


def _warnings(
    task_type: str, edited: dict[str, Any], selected: list[str]
) -> list[str]:
    out: list[str] = []
    if task_type == "daily_lesson_split":
        group = edited.get("group_activity") or {}
        empty = [field for field in SPLIT_FIELDS if group.get(field) == ""]
        if empty:
            out.append("部分字段为空字符串，采用后对应字段将为空")
    elif task_type == "daily_process_adapt":
        if edited.get("process") == "":
            out.append("过程为空字符串，采用后将清空活动过程")
    else:
        for target in selected:
            value = edited.get(target)
            if value is None:
                continue
            if target == "morning_talk":
                if not (value.get("topic") or value.get("questions")):
                    out.append("晨间谈话为空内容，采用后该板块将没有内容")
            elif isinstance(value, list) and not value:
                out.append(f"{target} 未提供具体游戏，采用后该板块将为空")
            elif isinstance(value, dict) and not value.get("games"):
                out.append(f"{target} 未提供具体游戏，采用后该板块将为空")
    return out


# ---------------------------------------------------------------------------
# Merge / business comparison
# ---------------------------------------------------------------------------


def _merge(
    content: LocalDailyPlanContent,
    task_type: str,
    selected: list[str],
    edited: dict[str, Any],
) -> dict[str, Any]:
    base = copy.deepcopy(content.adopted_content or {})
    if task_type == "daily_lesson_split":
        base["group_activity"] = copy.deepcopy(edited["group_activity"])
    elif task_type == "daily_process_adapt":
        group = dict(base.get("group_activity") or {})
        group["process"] = edited["process"]
        base["group_activity"] = group
    else:
        for board in selected:
            base[board] = copy.deepcopy(edited[board])
    return base


def _materialize(
    content: LocalDailyPlanContent, merged: dict[str, Any]
) -> dict[str, Any]:
    try:
        parsed = parse_adopted_content(merged)
    except ContentValidationError as exc:
        raise LocalValidationError(exc.message) from None
    group_ids, game_ids = collect_identity_sets(content.adopted_content)
    try:
        return materialize_adopted_content(
            parsed,
            allowed_group_ids=group_ids,
            allowed_game_ids=game_ids,
        )
    except ContentValidationError as exc:
        raise LocalValidationError(exc.message) from None


def _business(value: Any) -> str:
    """Canonical business view with server-owned ids removed."""
    return canonical_json(ai_inputs._strip_ids(value))


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def preview_adoption(
    session: Session,
    *,
    plan_id: str,
    candidate_id: str,
    expected_content_version: object,
    selected_targets: object,
    edited_candidate: object,
    launch_id: str = "",
    session_scope: str = "",
    holiday_provider: ai_inputs.HolidayProvider | None = None,
) -> dict[str, Any]:
    """Validate and describe one adoption; never writes to the database."""
    expected = _validate_positive_int(
        expected_content_version, "expected_content_version"
    )

    with read_scope(session):
        profile_id = _profile_id(session)
        context = require_context(session, date.today())
        plan, content = _load_plan_and_content(session, plan_id)
        if plan.class_id != context.school_class.id:
            raise LocalAiNotFound("未找到该日计划")
        candidate = ai_candidates._require_candidate(session, plan, candidate_id)
        raw, _execution, input_row = require_candidate_chain(
            session, plan, candidate
        )
        if not ai_candidates.contract_adoptable(session, profile_id, candidate):
            raise LocalAiContractObsolete()
        validated = _validate_edit(candidate.task_type, edited_candidate)
        selected = _validate_targets(candidate.task_type, raw, selected_targets)
        if candidate.task_type == "daily_other_activities":
            for target in selected:
                if validated.get(target) is None:
                    raise LocalValidationError("教师编辑缺少所选板块")
        current_version = content.version
        if expected != current_version:
            raise LocalVersionConflict(
                details={"current_content_version": current_version}
            )
        if not ai_inputs.dependency_matches(
            session,
            plan=plan,
            content=content,
            input_row=input_row,
            holiday_provider=holiday_provider,
        ):
            raise LocalAiSourceChanged(
                details=ai_candidates.source_change_details(
                    session, plan, content, input_row
                )
            )
        dumped = _dumped(content)
        before = {target: _current_value(dumped, target) for target in selected}
        after = {target: _edited_value(validated, target) for target in selected}
        target_hash = _target_hash(content, selected)

    now = _now()
    payload = {
        "v": 1,
        "launch_id": launch_id or "",
        "session_scope": session_scope or "",
        "profile_id": profile_id,
        "plan_id": plan.id,
        "candidate_id": candidate.id,
        "task_type": candidate.task_type,
        "contract_version": candidate.contract_version,
        "content_version": current_version,
        "selected_targets": selected,
        "edit_hash": _digest(validated),
        "dependency_hash": input_row.dependency_hash,
        "target_hash": target_hash,
        "edited_candidate": validated,
    }
    token, expires_at = _TOKENS.issue(payload, now)
    return {
        "preview_token": token,
        "expires_at": datetime.fromtimestamp(expires_at, tz=timezone.utc),
        "content_version": current_version,
        "candidate_id": candidate.id,
        "selected_targets": selected,
        "before": before,
        "after": after,
        "warnings": _warnings(candidate.task_type, validated, selected),
    }


# ---------------------------------------------------------------------------
# Adopt
# ---------------------------------------------------------------------------


def _adopt_baseline(
    task_type: str,
    candidate: LocalAICandidate,
    raw: dict[str, Any],
    current_id: str | None,
    current_value: Any,
) -> tuple[str | None, Any]:
    if task_type == "daily_lesson_split":
        # The baseline is the *raw model* process, never the teacher preview.
        return candidate.id, baseline_from_model_process(_raw_process(raw))
    return current_id, current_value


def _receipt_replay(
    session: Session, request_id: str, fingerprint: str
) -> dict[str, Any] | None:
    """Read a committed receipt for this key, or None when there is none."""
    with read_scope(session):
        profile_id = _profile_id(session)
        receipt = _find_receipt(session, profile_id, request_id)
    if receipt is None:
        return None
    return _replay(receipt, OP_ADOPT, fingerprint)


def _write_result(
    *,
    changed: bool,
    plan_id: str,
    content_id: str,
    content_version: int,
    candidate_id: str,
    selected: list[str],
    request_id: str,
) -> dict[str, Any]:
    return {
        "changed": changed,
        "plan_id": plan_id,
        "content_id": content_id,
        "content_version": content_version,
        "candidate_id": candidate_id,
        "selected_targets": list(selected),
        "request_id": request_id,
    }


def adopt(
    session: Session,
    *,
    plan_id: str,
    candidate_id: str,
    expected_content_version: object,
    preview_token: object,
    request_id: object,
    launch_id: str = "",
    session_scope: str = "",
    holiday_provider: ai_inputs.HolidayProvider | None = None,
) -> dict[str, Any]:
    """Atomically adopt a previewed candidate; consumed token, one version."""
    expected = _validate_positive_int(
        expected_content_version, "expected_content_version"
    )
    rid = _normalize_request_id(request_id)
    token_str = preview_token if isinstance(preview_token, str) else ""
    if not token_str:
        raise LocalValidationError("preview_token 必须是字符串")
    # The receipt fingerprint binds the *whole* adoption request: the exact
    # preview token, not just plan/candidate/version. A same key with a
    # different token (different selection/edit) is a request conflict, while a
    # lost-response retry with the same body still replays after consumption
    # or restart. An uncommitted attempt may be retried with a new token/key.
    fingerprint = _fingerprint(
        OP_ADOPT,
        {
            "plan_id": plan_id,
            "candidate_id": candidate_id,
            "expected_content_version": expected,
            "preview_token": token_str,
        },
    )

    # Receipt first: a lost response replays even after the token was consumed.
    replayed = _receipt_replay(session, rid, fingerprint)
    if replayed is not None:
        return replayed

    payload = _TOKENS.get(token_str)
    if payload is None:
        # R09: the token may have been consumed by a concurrent same-key
        # commit whose receipt landed after our first receipt read (the token
        # is only consumed after that commit). Re-read the receipt before
        # reporting an expired preview so a simultaneous duplicate still
        # replays the committed result instead of a spurious 409.
        replayed = _receipt_replay(session, rid, fingerprint)
        if replayed is not None:
            return replayed
        raise LocalAiPreviewExpired(details={"reason": "unknown_or_expired"})
    if (
        payload.get("plan_id") != plan_id
        or payload.get("candidate_id") != candidate_id
        or payload.get("launch_id") != (launch_id or "")
        or payload.get("session_scope") != (session_scope or "")
    ):
        raise LocalAiPreviewExpired(details={"reason": "binding_mismatch"})
    selected = list(payload["selected_targets"])
    edited = payload["edited_candidate"]
    if payload.get("task_type") not in TASK_TYPES:
        raise LocalStorageError("预览凭证损坏")

    begin_immediate(session)
    try:
        profile_id = _profile_id(session)
        receipt = _find_receipt(session, profile_id, rid)
        if receipt is not None:
            result = _replay(receipt, OP_ADOPT, fingerprint)
            rollback(session)
            return result
        if payload.get("profile_id") != profile_id:
            raise LocalAiPreviewExpired(details={"reason": "binding_mismatch"})
        # Expiry is re-checked inside the write transaction: a token that
        # expired while the request waited is never accepted.
        try:
            expired = _now() >= float(payload.get("exp", 0))
        except (TypeError, ValueError):
            expired = True
        if expired:
            raise LocalAiPreviewExpired(details={"reason": "expired"})
        # The token-bound version must equal the request's expected version:
        # changing expected_content_version can never revive an old preview.
        if payload.get("content_version") != expected:
            raise LocalAiPreviewExpired(details={"reason": "version_binding"})
        context = require_context(session, date.today())
        plan, content = _load_plan_and_content(session, plan_id)
        if plan.class_id != context.school_class.id:
            raise LocalAiNotFound("未找到该日计划")
        candidate = ai_candidates._require_candidate(session, plan, candidate_id)
        raw, _execution, input_row = require_candidate_chain(
            session, plan, candidate
        )
        if not ai_candidates.contract_adoptable(session, profile_id, candidate):
            raise LocalAiContractObsolete()
        if payload.get("contract_version") != candidate.contract_version:
            raise LocalAiContractObsolete()
        if payload.get("edit_hash") != _digest(edited) or list(
            payload["selected_targets"]
        ) != _validate_targets(candidate.task_type, raw, selected):
            raise LocalStorageError("预览凭证损坏")

        # Classify the current state strictly: source change first, then target
        # change, then an unrelated version change (W4 review R06). A source /
        # target change is never masked by the version conflict; the token
        # version binding above already blocks a client-changed `expected`.
        if input_row.dependency_hash != payload["dependency_hash"]:
            raise LocalAiSourceChanged(
                details={"changed_fields": ["dependency_hash"]}
            )
        if not ai_inputs.dependency_matches(
            session,
            plan=plan,
            content=content,
            input_row=input_row,
            holiday_provider=holiday_provider,
        ):
            raise LocalAiSourceChanged(
                details=ai_candidates.source_change_details(
                    session, plan, content, input_row
                )
            )
        if _target_hash(content, selected) != payload["target_hash"]:
            raise LocalAiTargetChanged()
        if content.version != expected:
            raise LocalVersionConflict(
                details={"current_content_version": content.version}
            )

        merged = _materialize(
            content, _merge(content, candidate.task_type, selected, edited)
        )
        current_baseline_id, current_baseline = resolve_baseline(
            session, plan, content
        )
        new_baseline_id, new_baseline = _adopt_baseline(
            candidate.task_type,
            candidate,
            raw,
            current_baseline_id,
            current_baseline,
        )
        business_changed = _business(merged) != _business(content.adopted_content)
        baseline_changed = (new_baseline_id, new_baseline) != (
            current_baseline_id,
            current_baseline,
        )
        changed = business_changed or baseline_changed

        now = utc_now()
        if changed:
            new_version = content.version + 1
            new_content_id = new_opaque_id()
            session.add(
                LocalDailyPlanContent(
                    id=new_content_id,
                    daily_plan_id=plan.id,
                    version=new_version,
                    raw_lesson_plan=content.raw_lesson_plan,
                    split_baseline=new_baseline,
                    adopted_content=merged,
                    editor_id=profile_id,
                    created_at=now,
                )
            )
            session.flush()
            adopted_payload = {
                target: _edited_value(edited, target) for target in selected
            }
            session.add(
                LocalDailyPlanAIProvenance(
                    content_id=new_content_id,
                    daily_plan_id=plan.id,
                    content_version=new_version,
                    baseline_candidate_id=new_baseline_id,
                    adopted_candidate_id=candidate.id,
                    selected_targets_json={target: True for target in selected},
                    adopted_payload_hash=_digest(adopted_payload),
                    created_at=now,
                )
            )
            session.flush()
            # CAS on the full current-content triple: both the id and the
            # version must still be the ones this adoption was based on.
            updated = session.execute(
                update(LocalDailyPlan)
                .where(
                    LocalDailyPlan.id == plan.id,
                    LocalDailyPlan.deleted_at.is_(None),
                    LocalDailyPlan.current_content_id == content.id,
                    LocalDailyPlan.current_content_version == expected,
                )
                .values(
                    current_content_id=new_content_id,
                    current_content_version=new_version,
                    updated_at=now,
                )
                .execution_options(synchronize_session=False)
            )
            if updated.rowcount != 1:
                raise LocalVersionConflict(
                    details={"current_content_version": content.version}
                )
            session.refresh(plan)
            _record_operation(
                session,
                actor_id=profile_id,
                action=ADOPTION_AUDIT_ACTION,
                target_id=plan.id,
                target_version_after=new_version,
                created_at=now,
            )
            result = _write_result(
                changed=True,
                plan_id=plan.id,
                content_id=new_content_id,
                content_version=new_version,
                candidate_id=candidate.id,
                selected=selected,
                request_id=rid,
            )
        else:
            result = _write_result(
                changed=False,
                plan_id=plan.id,
                content_id=content.id,
                content_version=content.version,
                candidate_id=candidate.id,
                selected=selected,
                request_id=rid,
            )
        _store_receipt(
            session,
            profile_id=profile_id,
            request_id=rid,
            operation_kind=OP_ADOPT,
            fingerprint=fingerprint,
            result=result,
        )
        session.commit()
    except BaseException:
        rollback(session)
        raise

    # Consume the token only after the commit really succeeded.
    _TOKENS.consume(token_str)
    return result


__all__ = [
    "ADOPTION_AUDIT_ACTION",
    "ADOPTION_TTL_SECONDS",
    "MAX_TOKENS",
    "OP_ADOPT",
    "SPLIT_FIELDS",
    "adopt",
    "preview_adoption",
    "reset_tokens",
]
