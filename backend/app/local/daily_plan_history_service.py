"""D3-A local daily-plan history and whole-plan restore.

This service is deliberately separate from ``daily_plan_service.save``. A
restore is not a normal PATCH: it copies a historical content snapshot
(including historical group/game identities and the validated baseline) and
appends a new version in one short write transaction. Normal manual saves keep
their existing current-identity and baseline-inheritance semantics.

Reads are consistent snapshots. Preview tokens are short-lived, in-memory,
bound to the app session/launch/profile/plan and to the exact source/current
content snapshots. Committed restore records are persistent idempotency
receipts: a lost response is read back by request_id and never re-applied.
"""

from __future__ import annotations

import copy
import hashlib
import secrets
import threading
import time
from collections import OrderedDict
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ids import new_opaque_id
from app.local import daily_plan_service
from app.local.ai_provenance import (
    load_candidate,
    resolve_baseline,
)
from app.local.base import utc_now
from app.local.daily_plan_service import (
    _load_content,
    _plan_by_id,
    _record_operation,
    _validate_stored_content,
)
from app.local.prompt_bundles import PACKAGE_CONTRACT_VERSION, canonical_json
from app.local.tx import begin_immediate, is_unique_violation, read_scope, rollback
from app.local.errors import (
    LocalHistoryNotFound,
    LocalHistoryOperationNotFound,
    LocalHistoryPreviewExpired,
    LocalHistoryRequestConflict,
    LocalPlanNotFound,
    LocalStorageError,
    LocalValidationError,
    LocalVersionConflict,
)
from app.local.models import (
    LocalDailyPlan,
    LocalDailyPlanAIProvenance,
    LocalDailyPlanContent,
    LocalDailyPlanRestore,
    LocalProfile,
)
from app.local.profile_service import require_context
from app.local.prompt_bundles import canonical_json
from app.local.tx import begin_immediate, read_scope, rollback

DEFAULT_HISTORY_LIMIT = 50
MAX_HISTORY_LIMIT = 200
PREVIEW_TTL_SECONDS = 600
MAX_PREVIEW_TOKENS = 64
RESTORE_ACTION = "restore_daily_plan"
PLAN_TARGET_TYPE = "daily_plan"


def _now() -> float:
    return time.time()


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _positive_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise LocalValidationError(f"{label} 必须是 >= 1 的整数")
    return value


def _request_id(value: object) -> str:
    import uuid

    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        raise LocalValidationError("request_id 必须是 UUID") from None


def _profile_id(session: Session) -> str:
    row = session.scalars(select(LocalProfile)).first()
    if row is None:
        raise LocalStorageError("本地教师档案缺失")
    return row.id


def _content_identity(
    session: Session, plan: LocalDailyPlan, content: LocalDailyPlanContent
) -> dict[str, Any]:
    baseline_id, _baseline_value = resolve_baseline(session, plan, content)
    return {
        "raw_lesson_plan": content.raw_lesson_plan,
        "split_baseline": content.split_baseline,
        "adopted_content": content.adopted_content,
        "baseline_candidate_id": baseline_id,
    }


def _content_hash(
    session: Session, plan: LocalDailyPlan, content: LocalDailyPlanContent
) -> str:
    return _digest(_content_identity(session, plan, content))


def _validate_history_content(
    session: Session, plan: LocalDailyPlan, content: LocalDailyPlanContent
) -> None:
    """History-only format gate; D2's original historical reads stay unchanged.

    A history restore must not accept a baseline candidate whose contract or
    schema this build cannot validate. ``resolve_baseline`` intentionally keeps
    old-contract D2 baselines readable, so this gate checks the candidate
    identity after its normal chain validation. Guidance revisions r1/r2/r3 are
    all contract v1 and remain restorable.
    """
    _validate_stored_content(session, plan, content)
    baseline_id, _baseline_value = resolve_baseline(session, plan, content)
    if baseline_id is None:
        return
    candidate = load_candidate(session, baseline_id)
    if candidate is None:
        raise LocalStorageError("历史基准候选缺失")
    if (
        candidate.contract_version != PACKAGE_CONTRACT_VERSION
        or candidate.schema_version != PACKAGE_CONTRACT_VERSION
    ):
        raise LocalStorageError("历史基准候选契约或格式不受支持")


def _content_view(content: LocalDailyPlanContent) -> dict[str, Any]:
    return {
        "version": content.version,
        "raw_lesson_plan": content.raw_lesson_plan,
        "split_baseline": copy.deepcopy(content.split_baseline),
        "adopted_content": copy.deepcopy(content.adopted_content),
        "editor_id": content.editor_id,
        "created_at": content.created_at,
    }


def _header(plan: LocalDailyPlan) -> dict[str, Any]:
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
        "school_name": plan.school_name,
        "class_name": plan.class_name,
        "grade": plan.grade,
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
        "current_content_version": plan.current_content_version,
    }


def _require_plan(session: Session, plan_id: str) -> tuple[LocalDailyPlan, str]:
    context = require_context(session, date.today())
    plan = _plan_by_id(session, plan_id)
    if plan.class_id != context.school_class.id:
        raise LocalPlanNotFound()
    return plan, context.profile.id


def _assert_current_is_latest(session: Session, plan: LocalDailyPlan) -> None:
    """A bounded plan+version index check, never a full-table body scan.

    Normal writes keep the current pointer at the maximum content version.
    An orphan future row (possible only in a damaged synthetic database) must
    not be treated as legal history: a later normal append would collide with
    it. Receipt-only reads intentionally do not call this check.
    """
    latest = session.scalar(
        select(func.max(LocalDailyPlanContent.version)).where(
            LocalDailyPlanContent.daily_plan_id == plan.id
        )
    )
    if latest is None or int(latest) != plan.current_content_version:
        raise LocalStorageError("计划当前内容指针不是最新版本")


def _content_at(
    session: Session, plan: LocalDailyPlan, version: int
) -> LocalDailyPlanContent:
    try:
        content = session.scalars(
            select(LocalDailyPlanContent).where(
                LocalDailyPlanContent.daily_plan_id == plan.id,
                LocalDailyPlanContent.version == version,
            )
        ).first()
    except ValueError:
        raise LocalStorageError("历史内容持久数据损坏") from None
    if content is None:
        raise LocalHistoryNotFound()
    _validate_history_content(session, plan, content)
    return content


def _restore_source_version(
    session: Session, plan_id: str, content_id: str
) -> int | None:
    try:
        row = session.scalars(
            select(LocalDailyPlanRestore).where(
                LocalDailyPlanRestore.daily_plan_id == plan_id,
                LocalDailyPlanRestore.result_content_id == content_id,
            )
        ).first()
    except ValueError:
        raise LocalStorageError("历史恢复来源损坏") from None
    return row.source_content_version if row is not None else None


def list_history(
    session: Session,
    *,
    plan_id: str,
    limit: object = DEFAULT_HISTORY_LIMIT,
    before_version: object = None,
) -> dict[str, Any]:
    limit_value = _positive_int(limit, "limit")
    if limit_value > MAX_HISTORY_LIMIT:
        raise LocalValidationError(f"limit 不能超过 {MAX_HISTORY_LIMIT}")
    before = None
    if before_version is not None:
        before = _positive_int(before_version, "before_version")
    with read_scope(session):
        plan, _profile = _require_plan(session, plan_id)
        _assert_current_is_latest(session, plan)
        current = _load_content(session, plan)
        _validate_history_content(session, plan, current)
        statement = select(LocalDailyPlanContent).where(
            LocalDailyPlanContent.daily_plan_id == plan.id
        )
        if before is not None:
            statement = statement.where(LocalDailyPlanContent.version < before)
        try:
            rows = list(
                session.scalars(
                    statement.order_by(LocalDailyPlanContent.version.desc()).limit(
                        limit_value + 1
                    )
                ).all()
            )
        except ValueError:
            raise LocalStorageError("历史内容持久数据损坏") from None
        page = rows[:limit_value]
        for row in page:
            _validate_history_content(session, plan, row)
        next_before = page[-1].version if len(rows) > limit_value and page else None
        source_by_content: dict[str, int] = {}
        if page:
            restore_rows = session.scalars(
                select(LocalDailyPlanRestore).where(
                    LocalDailyPlanRestore.daily_plan_id == plan.id,
                    LocalDailyPlanRestore.result_content_id.in_(
                        [row.id for row in page]
                    ),
                )
            ).all()
            source_by_content = {
                row.result_content_id: row.source_content_version
                for row in restore_rows
            }
        return {
            "items": [
                {
                    "version": row.version,
                    "created_at": row.created_at,
                    "is_current": row.version == plan.current_content_version,
                    "restored_from_version": source_by_content.get(row.id),
                }
                for row in page
            ],
            "current_content_version": plan.current_content_version,
            "next_before_version": next_before,
        }


def get_history(
    session: Session, *, plan_id: str, version: object
) -> dict[str, Any]:
    version_value = _positive_int(version, "version")
    with read_scope(session):
        plan, _profile = _require_plan(session, plan_id)
        _assert_current_is_latest(session, plan)
        current = _load_content(session, plan)
        _validate_history_content(session, plan, current)
        content = _content_at(session, plan, version_value)
        return {
            "plan": _header(plan),
            "content": _content_view(content),
            "is_current": version_value == plan.current_content_version,
            "restored_from_version": _restore_source_version(
                session, plan.id, content.id
            ),
        }


class _TokenStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def issue(self, payload: dict[str, Any]) -> tuple[str, datetime]:
        token = secrets.token_urlsafe(32)
        expires = _now() + PREVIEW_TTL_SECONDS
        value = dict(payload)
        value["exp"] = expires
        with self._lock:
            while len(self._items) >= MAX_PREVIEW_TOKENS:
                self._items.popitem(last=False)
            self._items[token] = value
        return token, datetime.fromtimestamp(expires, tz=timezone.utc)

    def get(self, token: object) -> dict[str, Any] | None:
        if not isinstance(token, str) or not token:
            return None
        with self._lock:
            value = self._items.get(token)
            if value is None:
                return None
            if _now() >= float(value.get("exp", 0)):
                self._items.pop(token, None)
                return None
            return dict(value)

    def consume(self, token: str) -> None:
        with self._lock:
            self._items.pop(token, None)

    def reset(self) -> None:
        with self._lock:
            self._items.clear()


_TOKENS = _TokenStore()


def reset_tokens() -> None:
    _TOKENS.reset()


def _warnings(source: LocalDailyPlanContent, current: LocalDailyPlanContent) -> list[str]:
    if source.split_baseline != current.split_baseline:
        return ["恢复历史拆分基准后，Word 标红比较将按该历史基准进行。"]
    return []


def preview_restore(
    session: Session,
    *,
    plan_id: str,
    source_content_version: object,
    expected_content_version: object,
    launch_id: str = "",
    session_scope: str = "",
) -> dict[str, Any]:
    source_version = _positive_int(source_content_version, "source_content_version")
    expected = _positive_int(expected_content_version, "expected_content_version")
    with read_scope(session):
        plan, profile_id = _require_plan(session, plan_id)
        _assert_current_is_latest(session, plan)
        current = _load_content(session, plan)
        _validate_history_content(session, plan, current)
        if current.version != expected:
            raise LocalVersionConflict()
        source = _content_at(session, plan, source_version)
        if source.version == current.version:
            raise LocalValidationError("当前版本不能作为恢复来源")
        token, expires = _TOKENS.issue(
            {
                "profile_id": profile_id,
                "plan_id": plan.id,
                "launch_id": launch_id or "",
                "session_scope": session_scope or "",
                "source_content_id": source.id,
                "source_content_version": source.version,
                "source_hash": _content_hash(session, plan, source),
                "before_content_id": current.id,
                "before_content_version": current.version,
                "before_hash": _content_hash(session, plan, current),
            }
        )
        return {
            "preview_token": token,
            "expires_at": expires,
            "source_version": source.version,
            "current_version": current.version,
            "before": _content_view(current),
            "after": _content_view(source),
            "warnings": _warnings(source, current),
        }


def _restore_out(row: LocalDailyPlanRestore) -> dict[str, Any]:
    return {
        "request_id": row.request_id,
        "plan_id": row.daily_plan_id,
        "source_content_version": row.source_content_version,
        "before_content_version": row.before_content_version,
        "content_version": row.result_content_version,
        "content_id": row.result_content_id,
        "created_at": row.created_at,
    }


def _receipt(
    session: Session, profile_id: str, request_id: str
) -> LocalDailyPlanRestore | None:
    try:
        return session.scalars(
            select(LocalDailyPlanRestore).where(
                LocalDailyPlanRestore.profile_id == profile_id,
                LocalDailyPlanRestore.request_id == request_id,
            )
        ).first()
    except ValueError:
        raise LocalStorageError("历史恢复回执损坏") from None


def _replay(
    row: LocalDailyPlanRestore, plan_id: str, fingerprint: str
) -> dict[str, Any]:
    if row.daily_plan_id != plan_id or row.request_fingerprint != fingerprint:
        raise LocalHistoryRequestConflict()
    return _restore_out(row)


def restore(
    session: Session,
    *,
    plan_id: str,
    expected_content_version: object,
    preview_token: object,
    request_id: object,
    launch_id: str = "",
    session_scope: str = "",
) -> dict[str, Any]:
    expected = _positive_int(expected_content_version, "expected_content_version")
    rid = _request_id(request_id)
    token = preview_token if isinstance(preview_token, str) else ""
    if not token:
        raise LocalValidationError("preview_token 必须是字符串")
    fingerprint = _digest(
        {
            "plan_id": plan_id,
            "expected_content_version": expected,
            "preview_token": token,
        }
    )
    with read_scope(session):
        plan, _profile = _require_plan(session, plan_id)
        profile_id = _profile_id(session)
        receipt = _receipt(session, profile_id, rid)
        if receipt is not None:
            return _replay(receipt, plan_id, fingerprint)
        _assert_current_is_latest(session, plan)
    payload = _TOKENS.get(token)
    if payload is None:
        with read_scope(session):
            plan, _profile = _require_plan(session, plan_id)
            profile_id = _profile_id(session)
            receipt = _receipt(session, profile_id, rid)
            if receipt is not None:
                return _replay(receipt, plan_id, fingerprint)
            _assert_current_is_latest(session, plan)
        raise LocalHistoryPreviewExpired()
    if (
        payload.get("plan_id") != plan_id
        or payload.get("launch_id") != (launch_id or "")
        or payload.get("session_scope") != (session_scope or "")
    ):
        raise LocalHistoryPreviewExpired()

    begin_immediate(session)
    try:
        plan, profile_id = _require_plan(session, plan_id)
        if payload.get("profile_id") != profile_id:
            raise LocalHistoryPreviewExpired()
        receipt = _receipt(session, profile_id, rid)
        if receipt is not None:
            result = _replay(receipt, plan_id, fingerprint)
            rollback(session)
            return result
        _assert_current_is_latest(session, plan)
        if _now() >= float(payload.get("exp", 0)):
            raise LocalHistoryPreviewExpired()
        current = _load_content(session, plan)
        _validate_history_content(session, plan, current)
        if current.version != expected:
            raise LocalVersionConflict()
        if (
            current.id != payload.get("before_content_id")
            or current.version != payload.get("before_content_version")
            or _content_hash(session, plan, current) != payload.get("before_hash")
        ):
            raise LocalHistoryPreviewExpired()
        try:
            source = session.get(
                LocalDailyPlanContent,
                payload["source_content_id"],
                populate_existing=True,
            )
        except ValueError:
            raise LocalStorageError("历史内容持久数据损坏") from None
        if (
            source is None
            or source.daily_plan_id != plan.id
            or source.version != payload.get("source_content_version")
            or _content_hash(session, plan, source) != payload.get("source_hash")
        ):
            raise LocalHistoryPreviewExpired()
        if source.version == current.version:
            raise LocalValidationError("当前版本不能作为恢复来源")
        _validate_history_content(session, plan, source)
        baseline_candidate_id, baseline_value = resolve_baseline(
            session, plan, source
        )

        now = utc_now()
        new_version = current.version + 1
        new_content_id = new_opaque_id()
        new_content = LocalDailyPlanContent(
            id=new_content_id,
            daily_plan_id=plan.id,
            version=new_version,
            raw_lesson_plan=source.raw_lesson_plan,
            split_baseline=copy.deepcopy(baseline_value),
            adopted_content=copy.deepcopy(source.adopted_content),
            editor_id=profile_id,
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
        restore_row = LocalDailyPlanRestore(
            id=new_opaque_id(),
            profile_id=profile_id,
            request_id=rid,
            request_fingerprint=fingerprint,
            daily_plan_id=plan.id,
            source_content_id=source.id,
            source_content_version=source.version,
            before_content_id=current.id,
            before_content_version=current.version,
            result_content_id=new_content_id,
            result_content_version=new_version,
            created_at=now,
        )
        session.add(restore_row)
        session.flush()
        updated = session.execute(
            update(LocalDailyPlan)
            .where(
                LocalDailyPlan.id == plan.id,
                LocalDailyPlan.deleted_at.is_(None),
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
            raise LocalVersionConflict()
        session.refresh(plan)
        _record_operation(
            session,
            actor_id=profile_id,
            action=RESTORE_ACTION,
            target_id=plan.id,
            target_version_after=new_version,
            created_at=now,
        )
        session.commit()
    except IntegrityError as exc:
        rollback(session)
        if is_unique_violation(exc, columns=("profile_id", "request_id")):
            with read_scope(session):
                _require_plan(session, plan_id)
                profile_id = _profile_id(session)
                receipt = _receipt(session, profile_id, rid)
                if receipt is not None:
                    return _replay(receipt, plan_id, fingerprint)
        # FK/CHECK/trigger/commit failures are storage failures, never an
        # idempotency-key conflict. The transaction is already rolled back.
        raise LocalStorageError() from exc
    except BaseException:
        rollback(session)
        raise
    _TOKENS.consume(token)
    return _restore_out(restore_row)


def get_restore_operation(
    session: Session, *, plan_id: str, request_id: object
) -> dict[str, Any]:
    rid = _request_id(request_id)
    with read_scope(session):
        profile_id = _profile_id(session)
        row = _receipt(session, profile_id, rid)
        if row is None or row.daily_plan_id != plan_id:
            raise LocalHistoryOperationNotFound()
        # Still require the plan to be a currently readable plan of this
        # profile/class; a deleted/foreign plan must not leak a receipt.
        _require_plan(session, plan_id)
        return _restore_out(row)


__all__ = [
    "DEFAULT_HISTORY_LIMIT",
    "MAX_HISTORY_LIMIT",
    "get_history",
    "get_restore_operation",
    "list_history",
    "preview_restore",
    "reset_tokens",
    "restore",
]
