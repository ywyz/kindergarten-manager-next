"""Read-only listening AI preview and atomic same-preview adoption.

The source dependency is the exact send projection (text plus image work
hashes and template standards), never the full record revision.  Adopting one
domain target therefore does not stale the remaining targets; each target's
own before-hash is checked separately.
"""

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
    ai_task_service,
    listening_ai_contracts,
    listening_ai_inputs,
    listening_ai_service,
    listening_service,
)
from app.local.errors import (
    LocalAiNotFound,
    LocalAiOperationNotFound,
    LocalStorageError,
    LocalValidationError,
    LocalVersionConflict,
)
from app.local.models import (
    LocalAICandidate,
    LocalAIInput,
    LocalAIOperation,
    LocalAITask,
    LocalListeningAIAdoption,
)
from app.local.normalize import normalize_request_id
from app.local.prompt_bundles import canonical_json
from app.local.tx import begin_immediate, read_scope, rollback

OP = "listening_ai_adopt"
ADOPTION_TTL_SECONDS = 600
MAX_TOKENS = 64
TEXT_TARGETS = ("overall_evaluation", "support_strategy")


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class _Tokens:
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

    def reset(self) -> None:
        with self._lock:
            self._items.clear()


_TOKENS = _Tokens()


def reset_tokens() -> None:
    _TOKENS.reset()


def _input_for_task(session: Session, task: LocalAITask) -> LocalAIInput:
    inp = session.get(LocalAIInput, task.input_id)
    if (
        inp is None
        or inp.source_kind != listening_ai_service.SOURCE_KIND
        or inp.source_id != task.listening_record_id
        or inp.listening_record_id != task.listening_record_id
        or inp.listening_domain != task.listening_domain
        or inp.listening_group_id != task.listening_group_id
        or inp.profile_id != task.profile_id
        or inp.task_type != task.task_type
    ):
        raise LocalStorageError("倾听 AI 任务输入不一致")
    return inp


def _candidate_chain(
    session: Session, *, profile_id: str, record_id: str, candidate_id: str
) -> tuple[LocalAICandidate, LocalAITask, LocalAIInput]:
    candidate, task, inp, _execution = listening_ai_service.require_candidate_chain(
        session,
        profile_id=profile_id,
        record_id=record_id,
        candidate_id=candidate_id,
    )
    return candidate, task, inp


def _current_projection(
    session: Session, runtime: Any, *, profile_id: str, inp: LocalAIInput
):
    try:
        projection = listening_ai_inputs.project(
            session,
            runtime,
            profile_id=profile_id,
            record_id=inp.listening_record_id,
            domain=inp.listening_domain,
            group_id=inp.listening_group_id,
            task_type=inp.task_type,
        )
    except Exception:  # noqa: BLE001
        raise LocalStorageError("倾听 AI 当前来源不可读") from None
    return projection


def _current_targets(session: Session, profile_id: str, inp: LocalAIInput) -> tuple[dict[str, Any], dict[str, Any]]:
    dto = listening_service.read_record_no_tx(
        session, profile_id=profile_id, record_id=inp.listening_record_id
    )
    domain = next(
        (item for item in dto["domains"] if item["domain"] == inp.listening_domain),
        None,
    )
    if domain is None:
        raise LocalStorageError("倾听领域缺失")
    groups = sorted(domain["groups"], key=lambda item: item["position"])
    group_text = None
    if inp.listening_group_id:
        group = next(
            (g for g in groups if g["group_id"] == inp.listening_group_id), None
        )
        if group is None:
            raise LocalStorageError("倾听小组缺失")
        group_text = (group.get("listening_text") or "").strip()
    stars = {
        item["item_id"]: item.get("stars")
        for item in domain.get("evaluation") or []
    }
    return dto, {
        "listening_text": group_text or "",
        "overall_evaluation": (domain.get("overall_evaluation") or "").strip(),
        "support_strategy": (domain.get("support_strategy") or "").strip(),
        **{item_id: value for item_id, value in stars.items()},
    }


def preview(
    session: Session,
    *,
    runtime: Any,
    profile_id: str,
    record_id: str,
    candidate_id: str,
    launch_id: str,
    session_scope_hash: str,
) -> dict[str, Any]:
    with read_scope(session):
        candidate, task, inp = _candidate_chain(
            session,
            profile_id=profile_id,
            record_id=record_id,
            candidate_id=candidate_id,
        )
        projection = _current_projection(
            session, runtime, profile_id=profile_id, inp=inp
        )
        if projection.dependency_hash != inp.dependency_hash:
            raise LocalValidationError("倾听 AI 来源已变化，请重新生成")
        raw = dict(candidate.raw_candidate_json or {})
        dto, current = _current_targets(session, profile_id, inp)
        target_hashes = dict(inp.target_hashes_json or {})
        adopted_pairs = set(
            session.execute(
                select(
                    LocalListeningAIAdoption.candidate_id,
                    LocalListeningAIAdoption.target_key,
                ).where(
                    LocalListeningAIAdoption.candidate_id == candidate.id,
                    LocalListeningAIAdoption.input_id == inp.id,
                )
            ).all()
        )
        target_states: dict[str, str] = {}
        for target in target_hashes:
            if (candidate.id, target) in adopted_pairs:
                target_states[target] = "adopted"
            elif (
                listening_ai_contracts.value_hash(current.get(target))
                != target_hashes[target]
            ):
                target_states[target] = "changed"
            else:
                target_states[target] = "eligible"
        if candidate.task_type == listening_ai_contracts.TASK_NOTE:
            proposed = {
                "listening_text": raw.get("text") or "",
                "uncertainties": list(raw.get("uncertainties") or []),
                "photo_only": bool(projection.dependencies.get("photo_only")),
                "current": current["listening_text"],
            }
            targets = ["listening_text"]
        else:
            by_id = {
                item["item_id"]: item for item in raw.get("items") or []
            }
            expected_ids = projection.item_ids
            if set(by_id) != set(expected_ids):
                raise LocalStorageError("倾听 AI 候选评价项与模板不一致")
            payload_items = {
                item["item_id"]: item
                for item in dict(inp.payload_json or {}).get("items") or []
            }
            proposed = {
                "overall_evaluation": raw.get("overall_evaluation") or "",
                "support_strategy": raw.get("support_strategy") or "",
                "items": [
                    {
                        "item_id": item_id,
                        "requirement": payload_items.get(item_id, {}).get(
                            "requirement", ""
                        ),
                        "level1": payload_items.get(item_id, {}).get("level1", ""),
                        "level2": payload_items.get(item_id, {}).get("level2", ""),
                        "stars": by_id[item_id].get("stars"),
                        "basis": by_id[item_id].get("basis") or "",
                        "current": current.get(item_id),
                    }
                    for item_id in expected_ids
                ],
                "current": {
                    "overall_evaluation": current["overall_evaluation"],
                    "support_strategy": current["support_strategy"],
                },
            }
            targets = ["overall_evaluation", "support_strategy", *expected_ids]
        token, expires = _TOKENS.issue(
            {
                "v": 1,
                "profile_id": profile_id,
                "record_id": record_id,
                "domain": inp.listening_domain,
                "group_id": inp.listening_group_id,
                "candidate_id": candidate.id,
                "candidate_hash": candidate.candidate_hash,
                "input_id": inp.id,
                "task_type": candidate.task_type,
                "dependency_hash": inp.dependency_hash,
                "target_hashes": target_hashes,
                "source_revision": dto["revision"],
                "launch_id": launch_id,
                "session_scope_hash": session_scope_hash,
            },
            datetime.now(timezone.utc).timestamp(),
        )
    return {
        "preview_token": token,
        "expires_at": datetime.fromtimestamp(expires, tz=timezone.utc),
        "record_id": record_id,
        "domain": inp.listening_domain,
        "group_id": inp.listening_group_id,
        "task_type": candidate.task_type,
        "candidate_id": candidate.id,
        "candidate_hash": candidate.candidate_hash,
        "targets": targets,
        "target_states": target_states,
        "proposed": proposed,
        "revision": dto["revision"],
    }


def _selections(task_type: str, selections: object) -> list[dict[str, Any]]:
    if not isinstance(selections, list) or not selections:
        raise LocalValidationError("请选择至少一个采用目标")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in selections:
        if not isinstance(item, Mapping):
            raise LocalValidationError("采用目标格式不合法")
        target = item.get("target")
        if not isinstance(target, str) or not target or target in seen:
            raise LocalValidationError("采用目标重复或不合法")
        if task_type == listening_ai_contracts.TASK_NOTE:
            if target != "listening_text" or set(item) != {"target", "value"}:
                raise LocalValidationError("倾听正文采用目标不合法")
            value = item.get("value")
            if not isinstance(value, str) or len(value) > 20_000:
                raise LocalValidationError("倾听正文不合法")
            result.append({"target": target, "value": value})
        elif target in TEXT_TARGETS:
            if set(item) != {"target", "value"}:
                raise LocalValidationError("领域文本采用目标不合法")
            value = item.get("value")
            if not isinstance(value, str) or len(value) > 20_000:
                raise LocalValidationError("领域文本不合法")
            result.append({"target": target, "value": value})
        else:
            if set(item) != {"target", "stars"}:
                raise LocalValidationError("领域星级采用目标不合法")
            stars = item.get("stars")
            if stars is not None and (
                isinstance(stars, bool) or stars not in (1, 2, 3)
            ):
                raise LocalValidationError("领域星级不合法")
            result.append({"target": target, "stars": stars})
        seen.add(target)
    return result


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
    record_id: str,
    request_id: object,
    expected_revision: object,
    preview_token: object,
    selections: object,
    candidate_id: str,
    launch_id: str,
    session_scope_hash: str,
) -> dict[str, Any]:
    rid = normalize_request_id(request_id)
    if (
        isinstance(expected_revision, bool)
        or not isinstance(expected_revision, int)
        or expected_revision < 1
    ):
        raise LocalValidationError("expected_revision 必须是正整数")
    if not isinstance(preview_token, str) or not preview_token:
        raise LocalValidationError("preview_token 不合法")
    fingerprint = _digest(
        {
            "operation_kind": OP,
            "payload": {
                "record_id": record_id,
                "expected_revision": expected_revision,
                "preview_token": preview_token,
                "selections": selections,
            },
        }
    )
    with read_scope(session):
        row = _receipt(session, profile_id, rid)
        if row is not None:
            result = dict(row.result_json or {})
            if (
                row.operation_kind != OP
                or row.request_fingerprint != fingerprint
                or result.get("listening_record_id") != record_id
            ):
                raise LocalValidationError("同一请求已用于不同倾听 AI 采用")
            result["replayed"] = True
            return result
    payload = _TOKENS.get(preview_token)
    if payload is None:
        raise LocalValidationError("预览已过期，请重新预览")
    if (
        payload.get("profile_id") != profile_id
        or payload.get("record_id") != record_id
        or payload.get("launch_id") != launch_id
        or payload.get("session_scope_hash") != session_scope_hash
    ):
        raise LocalValidationError("预览不属于当前会话")
    task_type = payload["task_type"]
    selected = _selections(task_type, selections)
    if candidate_id != payload.get("candidate_id"):
        raise LocalValidationError("采用 URL 候选与预览候选不一致")
    candidate, task, inp = _candidate_chain(
        session,
        profile_id=profile_id,
        record_id=record_id,
        candidate_id=payload["candidate_id"],
    )
    if (
        candidate.id != payload["candidate_id"]
        or candidate.candidate_hash != payload["candidate_hash"]
        or inp.id != payload["input_id"]
        or inp.dependency_hash != payload["dependency_hash"]
        or task_type != candidate.task_type
    ):
        raise LocalStorageError("倾听 AI 预览链已变化")
    with read_scope(session):
        dto = listening_service.read_record_no_tx(
            session, profile_id=profile_id, record_id=record_id
        )
        if dto["revision"] != expected_revision:
            raise LocalVersionConflict(
                details={"current_revision": dto["revision"]}
            )
        projection = _current_projection(
            session, runtime, profile_id=profile_id, inp=inp
        )
        if projection.dependency_hash != payload["dependency_hash"]:
            raise LocalValidationError("倾听 AI 来源已变化，请重新预览")
        _, current = _current_targets(session, profile_id, inp)
        for item in selected:
            target = item["target"]
            if target not in payload["target_hashes"]:
                raise LocalValidationError("采用目标不属于候选")
            existing_adoption = session.scalars(
                select(LocalListeningAIAdoption).where(
                    LocalListeningAIAdoption.candidate_id == candidate.id,
                    LocalListeningAIAdoption.input_id == inp.id,
                    LocalListeningAIAdoption.target_key == target,
                )
            ).first()
            if existing_adoption is not None:
                raise LocalValidationError("该候选目标已经采用，不能重复采用")
            if (
                listening_ai_contracts.value_hash(current.get(target))
                != payload["target_hashes"][target]
            ):
                raise LocalValidationError("采用目标已被修改，请重新预览")
    patch: dict[str, Any] = {}
    adopted: list[dict[str, Any]] = []
    before_hashes: dict[str, str] = {}
    after_hashes: dict[str, str] = {}
    if task_type == listening_ai_contracts.TASK_NOTE:
        item = selected[0]
        if not inp.listening_group_id:
            raise LocalStorageError("倾听小组缺失")
        patch = {
            "groups": [
                {
                    "group_id": inp.listening_group_id,
                    "listening_text": item["value"].strip() or None,
                }
            ]
        }
        before_hashes["listening_text"] = payload["target_hashes"]["listening_text"]
        after_hashes["listening_text"] = listening_ai_contracts.value_hash(
            item["value"].strip()
        )
        adopted.append({"target": "listening_text", "value": item["value"].strip()})
    else:
        evaluation: dict[str, int | None] = {}
        for item in selected:
            target = item["target"]
            before_hashes[target] = payload["target_hashes"][target]
            if target == "overall_evaluation":
                patch["overall_evaluation"] = item["value"].strip() or None
                after_hashes[target] = listening_ai_contracts.value_hash(
                    item["value"].strip()
                )
                adopted.append({"target": target, "value": item["value"].strip()})
            elif target == "support_strategy":
                patch["support_strategy"] = item["value"].strip() or None
                after_hashes[target] = listening_ai_contracts.value_hash(
                    item["value"].strip()
                )
                adopted.append({"target": target, "value": item["value"].strip()})
            else:
                evaluation[target] = item["stars"]
                after_hashes[target] = listening_ai_contracts.value_hash(item["stars"])
                adopted.append({"target": target, "stars": item["stars"]})
        if evaluation:
            patch["evaluation"] = evaluation
    if not patch:
        raise LocalValidationError("没有可采用的字段")
    now = ai_task_service._now()
    begin_immediate(session)
    try:
        existing = _receipt(session, profile_id, rid)
        if existing is not None:
            rollback(session)
            replay = dict(existing.result_json or {})
            if existing.operation_kind != OP or existing.request_fingerprint != fingerprint:
                raise LocalValidationError("同一请求已用于不同倾听 AI 采用")
            replay["replayed"] = True
            return replay
        if not listening_ai_inputs.revalidate_source(session, task):
            raise LocalValidationError("倾听 AI 来源已变化，请重新预览")
        dto_now, current_now = _current_targets(session, profile_id, inp)
        if dto_now["revision"] != expected_revision:
            raise LocalVersionConflict(
                details={"current_revision": dto_now["revision"]}
            )
        scope_key = inp.listening_group_id or "__domain__"
        for item in selected:
            target = item["target"]
            existing_adoption = session.scalars(
                select(LocalListeningAIAdoption).where(
                    LocalListeningAIAdoption.candidate_id == candidate.id,
                    LocalListeningAIAdoption.input_id == inp.id,
                    LocalListeningAIAdoption.target_key == target,
                )
            ).first()
            if existing_adoption is not None:
                raise LocalValidationError("该候选目标已经采用，不能重复采用")
            if (
                listening_ai_contracts.value_hash(current_now.get(target))
                != payload["target_hashes"][target]
            ):
                raise LocalValidationError("采用目标已被修改，请重新预览")
        saved, _changed = listening_service.domain_patch_kernel_no_tx(
            session,
            profile_id=profile_id,
            record_id=record_id,
            domain=inp.listening_domain,
            expected_revision=expected_revision,
            patch=patch,
            now=now,
        )
        revision_after = int(saved["revision"])
        result = {
            "request_id": rid,
            "operation_kind": OP,
            "listening_record_id": record_id,
            "domain": inp.listening_domain,
            "group_id": inp.listening_group_id,
            "revision_after": revision_after,
            "adopted": adopted,
            "replayed": False,
        }
        operation_id = new_opaque_id()
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
                created_at=now,
            )
        )
        session.flush()
        for target in before_hashes:
            session.add(
                LocalListeningAIAdoption(
                    id=new_opaque_id(),
                    profile_id=profile_id,
                    source_kind=listening_ai_service.SOURCE_KIND,
                    record_id=record_id,
                    domain=inp.listening_domain,
                    group_id=inp.listening_group_id,
                    scope_key=scope_key,
                    target_key=target,
                    candidate_id=candidate.id,
                    input_id=inp.id,
                    before_hash=before_hashes[target],
                    after_hash=after_hashes[target],
                    revision_before=expected_revision,
                    revision_after=revision_after,
                    operation_id=operation_id,
                    created_at=now,
                )
            )
        if _changed:
            listening_service._audit(
                session,
                profile_id=profile_id,
                action="listening_ai_adopt",
                record_id=record_id,
                revision_after=revision_after,
                now=now,
            )
        session.commit()
        return result
    except BaseException:
        rollback(session)
        raise


def read_operation(
    session: Session,
    *,
    profile_id: str,
    record_id: str,
    request_id: str,
) -> dict[str, Any]:
    rid = normalize_request_id(request_id)
    with read_scope(session):
        row = session.scalars(
            select(LocalAIOperation).where(
                LocalAIOperation.profile_id == profile_id,
                LocalAIOperation.request_id == rid,
            )
        ).first()
        if row is None or row.operation_kind != OP:
            raise LocalAiOperationNotFound()
        result = dict(row.result_json or {})
        if result.get("listening_record_id") != record_id:
            raise LocalAiOperationNotFound()
        ledger = session.scalars(
            select(LocalListeningAIAdoption).where(
                LocalListeningAIAdoption.profile_id == profile_id,
                LocalListeningAIAdoption.record_id == record_id,
                LocalListeningAIAdoption.operation_id == row.id,
            )
        ).all()
        if not ledger:
            raise LocalStorageError("倾听 AI 采用回执缺少采用记录")
        candidate_id = ledger[0].candidate_id
        input_id = ledger[0].input_id
        revision_after = ledger[0].revision_after
        for item in ledger:
            if (
                item.candidate_id != candidate_id
                or item.input_id != input_id
                or item.revision_after != revision_after
                or item.domain != result.get("domain")
                or item.group_id != result.get("group_id")
            ):
                raise LocalStorageError("倾听 AI 采用回执链不一致")
            candidate = session.get(LocalAICandidate, item.candidate_id)
            if (
                candidate is None
                or candidate.profile_id != profile_id
                or candidate.source_kind != listening_ai_service.SOURCE_KIND
                or candidate.source_id != record_id
                or candidate.input_id != item.input_id
            ):
                raise LocalStorageError("倾听 AI 采用候选缺失")
            if len(item.before_hash) != 64 or len(item.after_hash) != 64:
                raise LocalStorageError("倾听 AI 采用散列损坏")
        adopted_targets = {
            str(item.get("target"))
            for item in result.get("adopted") or []
        }
        if adopted_targets != {item.target_key for item in ledger}:
            raise LocalStorageError("倾听 AI 采用目标与回执不一致")
        result["replayed"] = False
        return {
            "request_id": row.request_id,
            "operation_kind": row.operation_kind,
            "status": "committed",
            "result": result,
            "created_at": row.created_at.isoformat(),
        }


__all__ = ["OP", "adopt", "preview", "reset_tokens"]
