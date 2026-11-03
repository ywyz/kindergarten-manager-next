"""Read-only weekly AI previews and atomic same-batch adoption (A)."""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ids import new_opaque_id
from app.local import (
    weekly_ai_candidates,
    weekly_ai_contracts,
    weekly_ai_inputs,
    weekly_materials,
    weekly_plan_content,
)
from app.local.errors import (
    LocalAiNotFound,
    LocalStorageError,
    LocalValidationError,
    LocalWeeklyAiContractObsolete,
    LocalWeeklyAiPreviewExpired,
    LocalWeeklyAiRequestConflict,
    LocalWeeklyAiSourceChanged,
    LocalWeeklyAiTargetChanged,
    LocalWeeklyPlanNotFound,
    LocalWeeklyVersionConflict,
)
from app.local.models import (
    LocalAIOperation,
    LocalAICandidate,
    LocalAIInput,
    LocalWeeklyPlan,
    LocalWeeklyPlanAIAdoption,
    LocalWeeklyPlanContent,
)
from app.local.normalize import normalize_request_id
from app.local.prompt_bundles import canonical_json
from app.local.tx import begin_immediate, read_scope, rollback

ADOPTION_TTL_SECONDS = 600
MAX_TOKENS = 64
OP = "weekly_ai_adopt"


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class _TokenStore:
    def __init__(self) -> None:
        self._items: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def issue(self, payload: dict[str, Any], now: float) -> tuple[str, float]:
        token = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
        expires = now + ADOPTION_TTL_SECONDS
        with self._lock:
            while len(self._items) >= MAX_TOKENS:
                self._items.popitem(last=False)
            self._items[token] = {"payload": dict(payload), "expires_at": expires}
        return token, expires

    def get(self, token: object) -> dict[str, Any] | None:
        if not isinstance(token, str) or not token:
            return None
        now = datetime.now(timezone.utc).timestamp()
        with self._lock:
            entry = self._items.get(token)
            if entry is None:
                return None
            if entry["expires_at"] <= now:
                self._items.pop(token, None)
                return None
            return entry["payload"]

    def consume(self, token: object) -> None:
        if isinstance(token, str):
            with self._lock:
                self._items.pop(token, None)

    def reset(self) -> None:
        with self._lock:
            self._items.clear()


_TOKENS = _TokenStore()


def reset_tokens() -> None:
    _TOKENS.reset()


def _plan(session: Session, profile_id: str, plan_id: str) -> LocalWeeklyPlan:
    plan = session.get(LocalWeeklyPlan, plan_id)
    if plan is None or plan.profile_id != profile_id:
        raise LocalWeeklyPlanNotFound()
    return plan


def _content(session: Session, plan: LocalWeeklyPlan) -> LocalWeeklyPlanContent:
    row = session.get(LocalWeeklyPlanContent, plan.current_draft_id, populate_existing=True)
    if row is None or row.weekly_plan_id != plan.id or row.version != plan.current_draft_version:
        raise LocalStorageError("周计划草稿指针不一致")
    return row


def _selections(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise LocalValidationError("selections 必须是非空列表")
    result: list[dict[str, str]] = []
    seen_targets: set[str] = set()
    seen_candidates: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"candidate_id", "target"}:
            raise LocalValidationError("selection 字段不合法")
        candidate_id = item.get("candidate_id")
        target = item.get("target")
        if not isinstance(candidate_id, str) or not candidate_id:
            raise LocalValidationError("candidate_id 不合法")
        if target not in ("games", *weekly_ai_contracts.COLUMN_FIELDS, "materials"):
            raise LocalValidationError("target 不合法")
        if candidate_id in seen_candidates or target in seen_targets:
            raise LocalValidationError("selection 重复")
        seen_candidates.add(candidate_id)
        seen_targets.add(target)
        result.append({"candidate_id": candidate_id, "target": target})
    return result


def _basis(input_row: LocalAIInput) -> dict[str, Any]:
    deps = weekly_ai_inputs.build_business_dependency_view(
        dict(input_row.dependencies_json or {})
    )
    keys = (
        "schema_version",
        "target",
        "grade",
        "theme",
        "manual_text",
        "daily_sources",
        "selected",
        "config",
        "calendar",
    )
    return {key: deps.get(key) for key in keys}


def _candidate_value(
    candidate: LocalAICandidate, input_row: LocalAIInput, target: str
) -> dict[str, Any]:
    raw = dict(candidate.raw_candidate_json or {})
    if target == "materials":
        return {"items": raw.get("items") or []}
    if target in weekly_ai_contracts.COLUMN_FIELDS:
        return {"text": raw.get("text", "")}
    return raw


def _ai_ids(
    selections: Sequence[Mapping[str, Any]],
    candidate_by_id: Mapping[str, LocalAICandidate],
) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for selected in selections:
        target = selected["target"]
        if target != "games":
            continue
        raw = dict(candidate_by_id[selected["candidate_id"]].raw_candidate_json or {})
        ids: dict[str, str] = {}
        for key in ("collective_1", "collective_2", "free_choice_1", "focus_area"):
            item = (
                raw.get("focus_area")
                if key == "focus_area"
                else (raw.get("outdoor_game_slots") or {}).get(key)
            )
            if isinstance(item, Mapping) and item.get("source_kind") == "ai_supplement":
                ids[key] = new_opaque_id()
        result[target] = ids
    return result


def _apply(
    previous: dict[str, Any],
    *,
    selections: Sequence[Mapping[str, Any]],
    candidate_by_id: Mapping[str, LocalAICandidate],
    input_by_id: Mapping[str, LocalAIInput],
    new_draft_id: str,
    new_draft_version: int,
    profile_id: str,
    adopted_at: str,
    ai_ids_by_target: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    content = previous
    for selected in selections:
        target = selected["target"]
        candidate = candidate_by_id[selected["candidate_id"]]
        input_row = input_by_id[candidate.id]
        adoption = {
            "candidate_id": candidate.id,
            "candidate_hash": candidate.candidate_hash,
            "input_id": input_row.id,
            "execution_id": candidate.execution_id,
            "contract_version": candidate.contract_version,
            "dependency_hash": input_row.dependency_hash,
            "adopter_profile_id": profile_id,
            "adopted_draft_id": new_draft_id,
            "adopted_draft_version": new_draft_version,
            "adopted_at": adopted_at,
        }
        ai_ids = (
            dict((ai_ids_by_target or {}).get(target) or {})
            if target == "games"
            else None
        )
        if target == "games" and ai_ids is None:
            ai_ids = {}
        content = weekly_plan_content.apply_weekly_ai_adoption(
            content,
            target=target,
            candidate_value=_candidate_value(candidate, input_row, target),
            adoption=adoption,
            basis=_basis(input_row),
            server_manifest=weekly_ai_inputs.server_manifest_from_dependencies(
                dict(input_row.dependencies_json or {})
            )
            if target == "materials"
            else None,
            ai_item_ids=ai_ids,
        )
    return weekly_plan_content.validate_content(content, expected_schema=2)


def _target_hashes(
    content: Mapping[str, Any], targets: Sequence[str]
) -> dict[str, str]:
    return {target: weekly_ai_inputs.target_hash(content, target) for target in targets}


def _before_after(
    content: Mapping[str, Any], new_content: Mapping[str, Any], targets: Sequence[str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    for target in targets:
        before[target] = weekly_ai_inputs.target_projection(content, target)["value"]
        after[target] = weekly_ai_inputs.target_projection(new_content, target)["value"]
    return before, after


def preview_adoption(
    session: Session,
    *,
    runtime: Any,
    profile_id: str,
    plan_id: str,
    expected_draft_version: object,
    selections: object,
    launch_id: str,
    session_scope_hash: str,
) -> dict[str, Any]:
    selected = _selections(selections)
    if isinstance(expected_draft_version, bool) or not isinstance(expected_draft_version, int):
        raise LocalValidationError("expected_draft_version 必须是正整数")
    with read_scope(session):
        plan = _plan(session, profile_id, plan_id)
        content = _content(session, plan)
        if content.version != expected_draft_version:
            raise LocalWeeklyVersionConflict(details={"draft_version": content.version})
        candidates: dict[str, LocalAICandidate] = {}
        inputs: dict[str, LocalAIInput] = {}
        operation_id: str | None = None
        draft_id: str | None = None
        input_draft_id: str | None = None
        input_draft_version: int | None = None
        batch_hash: str | None = None
        for item in selected:
            candidate = session.get(LocalAICandidate, item["candidate_id"])
            if candidate is None:
                raise LocalAiNotFound("未找到该 AI 候选")
            raw, _execution, inp = weekly_ai_candidates.require_chain(
                session, plan=plan, candidate=candidate
            )
            if weekly_ai_candidates.TARGETS.get(candidate.task_type) != item["target"]:
                raise LocalValidationError("候选目标不匹配")
            state = weekly_ai_candidates.eligibility(
                session, plan=plan, content=content, candidate=candidate, input_row=inp
            )
            if state == "contract_obsolete":
                raise LocalWeeklyAiContractObsolete()
            if state != "eligible":
                raise LocalWeeklyAiSourceChanged()
            if operation_id is None:
                operation_id = inp.create_operation_id
                draft_id = content.id
                input_draft_id = inp.weekly_draft_id
                input_draft_version = inp.source_revision
                batch_hash = dict(inp.dependencies_json or {}).get("_batch_snapshot_hash")
            if (
                inp.create_operation_id != operation_id
                or inp.weekly_draft_id != input_draft_id
                or inp.source_revision != input_draft_version
                or dict(inp.dependencies_json or {}).get("_batch_snapshot_hash") != batch_hash
            ):
                raise LocalWeeklyAiRequestConflict(details={"reason": "cross_batch"})
            candidates[candidate.id] = candidate
            inputs[candidate.id] = inp
        new_id = new_opaque_id()
        new_version = content.version + 1
        ai_ids = _ai_ids(selected, candidates)
        new_content = _apply(
            content.content_json,
            selections=selected,
            candidate_by_id=candidates,
            input_by_id=inputs,
            new_draft_id=new_id,
            new_draft_version=new_version,
            profile_id=profile_id,
            adopted_at=datetime.now(timezone.utc).isoformat(),
            ai_ids_by_target=ai_ids,
        )
        before, after = _before_after(content.content_json, new_content, [x["target"] for x in selected])
        target_hashes = _target_hashes(content.content_json, [x["target"] for x in selected])
        after_hashes = _target_hashes(new_content, [x["target"] for x in selected])
        token, expires = _TOKENS.issue(
            {
                "v": 1,
                "profile_id": profile_id,
                "plan_id": plan.id,
                "draft_id": content.id,
                "draft_version": content.version,
                "content_hash": content.content_hash,
                "input_draft_id": input_draft_id,
                "input_draft_version": input_draft_version,
                "selections": selected,
                "candidate_hashes": {c.id: c.candidate_hash for c in candidates.values()},
                "dependency_hashes": {cid: inputs[cid].dependency_hash for cid in inputs},
                "target_hashes": target_hashes,
                "after_hashes": after_hashes,
                "operation_id": operation_id,
                "batch_snapshot_hash": batch_hash,
                "ai_item_ids": ai_ids,
                "launch_id": launch_id,
                "session_scope_hash": session_scope_hash,
            },
            datetime.now(timezone.utc).timestamp(),
        )
    return {
        "preview_token": token,
        "expires_at": datetime.fromtimestamp(expires, tz=timezone.utc),
        "weekly_plan_id": plan.id,
        "draft": {"id": content.id, "version": content.version},
        "selections": selected,
        "before": before,
        "after": after,
        "warnings": [],
    }


def _receipt(session: Session, profile_id: str, request_id: str):
    return session.scalars(
        select(LocalAIOperation).where(
            LocalAIOperation.profile_id == profile_id,
            LocalAIOperation.request_id == request_id,
        )
    ).first()


def adopt(
    session: Session,
    *,
    runtime: Any,
    profile_id: str,
    plan_id: str,
    request_id: object,
    expected_draft_version: object,
    preview_token: object,
    launch_id: str,
    session_scope_hash: str,
    blocked: bool = False,
) -> dict[str, Any]:
    rid = normalize_request_id(request_id)
    if isinstance(expected_draft_version, bool) or not isinstance(expected_draft_version, int):
        raise LocalValidationError("expected_draft_version 必须是正整数")
    if not isinstance(preview_token, str) or not preview_token:
        raise LocalValidationError("preview_token 不合法")
    fingerprint = _digest(
        {
            "operation_kind": OP,
            "payload": {
                "plan_id": plan_id,
                "expected_draft_version": expected_draft_version,
                "preview_token": preview_token,
            },
        }
    )
    with read_scope(session):
        row = _receipt(session, profile_id, rid)
        if row is not None:
            result = dict(row.result_json or {})
            if row.operation_kind != OP or row.request_fingerprint != fingerprint or result.get("weekly_plan_id") != plan_id:
                raise LocalWeeklyAiRequestConflict()
            result["replayed"] = True
            return result
    if blocked:
        from app.local.errors import LocalAiExecutorUnavailable

        raise LocalAiExecutorUnavailable()
    payload = _TOKENS.get(preview_token)
    if payload is None:
        with read_scope(session):
            row = _receipt(session, profile_id, rid)
            if row is not None:
                result = dict(row.result_json or {})
                if row.operation_kind == OP and row.request_fingerprint == fingerprint:
                    result["replayed"] = True
                    return result
        raise LocalWeeklyAiPreviewExpired()
    if (
        payload.get("profile_id") != profile_id
        or payload.get("plan_id") != plan_id
        or payload.get("launch_id") != launch_id
        or payload.get("session_scope_hash") != session_scope_hash
    ):
        raise LocalWeeklyAiPreviewExpired(details={"reason": "binding_mismatch"})
    selected = list(payload["selections"])
    begin_immediate(session)
    try:
        # Same-key concurrent commit: the loser must read the winner's
        # committed receipt before any version/token/event work.
        row = _receipt(session, profile_id, rid)
        if row is not None:
            result = dict(row.result_json or {})
            if (
                row.operation_kind != OP
                or row.request_fingerprint != fingerprint
                or result.get("weekly_plan_id") != plan_id
            ):
                raise LocalWeeklyAiRequestConflict()
            result["replayed"] = True
            rollback(session)
            return result
        plan = _plan(session, profile_id, plan_id)
        content = _content(session, plan)
        if content.version != expected_draft_version:
            raise LocalWeeklyVersionConflict(details={"draft_version": content.version})
        candidates: dict[str, LocalAICandidate] = {}
        inputs: dict[str, LocalAIInput] = {}
        for item in selected:
            candidate = session.get(LocalAICandidate, item["candidate_id"])
            if candidate is None:
                raise LocalAiNotFound("未找到该 AI 候选")
            _raw, _execution, inp = weekly_ai_candidates.require_chain(
                session, plan=plan, candidate=candidate
            )
            if weekly_ai_candidates.TARGETS.get(candidate.task_type) != item["target"]:
                raise LocalValidationError("候选目标不匹配")
            state = weekly_ai_candidates.eligibility(
                session, plan=plan, content=content, candidate=candidate, input_row=inp
            )
            if state == "contract_obsolete":
                raise LocalWeeklyAiContractObsolete()
            if state != "eligible":
                raise LocalWeeklyAiSourceChanged()
            if (
                inp.create_operation_id != payload.get("operation_id")
                or inp.weekly_draft_id != payload.get("input_draft_id")
                or inp.source_revision != payload.get("input_draft_version")
                or dict(inp.dependencies_json or {}).get("_batch_snapshot_hash") != payload.get("batch_snapshot_hash")
            ):
                raise LocalWeeklyAiRequestConflict(details={"reason": "cross_batch"})
            if candidate.candidate_hash != payload.get("candidate_hashes", {}).get(candidate.id):
                raise LocalWeeklyAiSourceChanged()
            candidates[candidate.id] = candidate
            inputs[candidate.id] = inp
        if _target_hashes(content.content_json, [x["target"] for x in selected]) != payload.get("target_hashes"):
            raise LocalWeeklyAiTargetChanged()
        new_id = new_opaque_id()
        new_version = content.version + 1
        adopted_at = datetime.now(timezone.utc).isoformat()
        new_content = _apply(
            content.content_json,
            selections=selected,
            candidate_by_id=candidates,
            input_by_id=inputs,
            new_draft_id=new_id,
            new_draft_version=new_version,
            profile_id=profile_id,
            adopted_at=adopted_at,
            ai_ids_by_target=payload.get("ai_item_ids") or {},
        )
        if _target_hashes(new_content, [x["target"] for x in selected]) != payload.get("after_hashes"):
            raise LocalWeeklyAiSourceChanged()
        new_hash = weekly_plan_content.content_hash(new_content)
        operation_id = new_opaque_id()
        result = {
            "operation_id": operation_id,
            "request_id": rid,
            "status": "committed",
            "weekly_plan_id": plan.id,
            "draft": {"id": new_id, "version": new_version, "content_hash": new_hash},
            "selections": selected,
            "changed": new_hash != content.content_hash,
            "replayed": False,
        }
        session.add(
            LocalAIOperation(
                id=operation_id,
                profile_id=profile_id,
                request_id=rid,
                operation_kind=OP,
                request_fingerprint=fingerprint,
                fingerprint_kind="sha256",
                fingerprint_key_id=None,
                result_json=result,
                created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )
        session.flush()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        row = LocalWeeklyPlanContent(
            id=new_id,
            weekly_plan_id=plan.id,
            version=new_version,
            schema_version=2,
            content_json=new_content,
            content_hash=new_hash,
            editor_profile_id=profile_id,
            created_at=now,
        )
        session.add(row)
        session.flush()
        plan.current_draft_id = new_id
        plan.current_draft_version = new_version
        plan.updated_at = now
        session.flush()
        before_hashes = payload.get("target_hashes", {})
        after_hashes = payload.get("after_hashes", {})
        for item in selected:
            candidate = candidates[item["candidate_id"]]
            session.add(
                LocalWeeklyPlanAIAdoption(
                    id=new_opaque_id(),
                    profile_id=profile_id,
                    source_kind="weekly_plan",
                    weekly_plan_id=plan.id,
                    draft_id=new_id,
                    draft_version=new_version,
                    candidate_id=candidate.id,
                    target_key=item["target"],
                    before_hash=before_hashes[item["target"]],
                    after_hash=after_hashes[item["target"]],
                    operation_id=operation_id,
                    created_at=now,
                )
            )
        session.commit()
        _TOKENS.consume(preview_token)
        return result
    except BaseException:
        rollback(session)
        raise


__all__ = [
    "ADOPTION_TTL_SECONDS",
    "MAX_TOKENS",
    "OP",
    "adopt",
    "preview_adoption",
    "reset_tokens",
]
