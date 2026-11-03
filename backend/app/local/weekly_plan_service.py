"""Transactional desktop weekly-plan service (engineering spec §3-4/§11).

The service owns source authorization, transactions, request receipts,
preview tokens and immutable history.  All structure/derivation/facts work
is delegated to the pure ``weekly_plan_content`` module (B); this module
never lets that helper read another database snapshot.
"""

from __future__ import annotations

import base64
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ids import new_opaque_id
from app.local import weekly_plan_operations as operations
from app.local import weekly_plan_sources as sources
from app.local import weekly_plan_tokens as tokens
from app.local import weekly_plan_snapshot as confirmation_schema
from app.local.errors import (
    LocalStorageError,
    LocalValidationError,
    LocalWeeklyAckRequired,
    LocalWeeklyConfirmationNotFound,
    LocalWeeklyInvalid,
    LocalWeeklyOperationNotFound,
    LocalWeeklyPlanNotFound,
    LocalWeeklyPreviewStale,
    LocalWeeklySourceChanged,
    LocalWeeklyVersionConflict,
)
from app.local.models import (
    LocalSettings,
    LocalTerm,
    LocalWeeklyPlan,
    LocalWeeklyPlanConfirmation,
    LocalWeeklyPlanContent,
)
from app.local.normalize import normalize_request_id
from app.local.profile_service import _term_revision, require_context
from app.local.tx import begin_immediate, read_scope, rollback
from app.services import calendar_service as cal

MAX_CONTENT_BYTES = 1_048_576
DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 200


def _content_module():
    from app.local import weekly_plan_content

    return weekly_plan_content


def _content_call(function, *args, **kwargs):
    module = _content_module()
    try:
        return function(*args, **kwargs)
    except module.WeeklyContentError as exc:
        raise LocalWeeklyInvalid(
            exc.message,
            details={
                "field_path": getattr(exc, "field_path", ""),
                **getattr(exc, "details", {}),
            },
        ) from None


def _hash(value: Any) -> str:
    return sources.hash_json(value)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _token_expires_at() -> str:
    return (
        datetime.now(timezone.utc)
        + timedelta(seconds=tokens.PREVIEW_TTL_SECONDS)
    ).isoformat()


def _validate_version(value: object, label: str = "expected_draft_version") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise LocalValidationError(f"{label} 必须是正整数")
    return value


def _validate_note(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise LocalWeeklyInvalid("备注必须是字符串或 null")
    if "\x00" in value:
        raise LocalWeeklyInvalid("备注不得包含 NUL")
    return value


def _plan_or_404(session: Session, profile_id: str, plan_id: str) -> LocalWeeklyPlan:
    plan = session.get(LocalWeeklyPlan, plan_id)
    if plan is None or plan.profile_id != profile_id:
        raise LocalWeeklyPlanNotFound()
    return plan


def _current_content(
    session: Session, plan: LocalWeeklyPlan
) -> LocalWeeklyPlanContent:
    content = session.get(
        LocalWeeklyPlanContent, plan.current_draft_id, populate_existing=True
    )
    if (
        content is None
        or content.weekly_plan_id != plan.id
        or content.version != plan.current_draft_version
    ):
        raise LocalStorageError("周计划草稿指针不一致")
    return content


def _draft_payload(content: LocalWeeklyPlanContent) -> dict:
    return {
        "id": content.id,
        "version": content.version,
        "content_hash": content.content_hash,
        "content": content.content_json,
    }


def _summary(plan: LocalWeeklyPlan) -> dict:
    return {
        "id": plan.id,
        "term_id": plan.term_id,
        "week_anchor_date": plan.week_anchor_date.isoformat(),
        "week_number_snapshot": plan.week_number_snapshot,
        "header": plan.header_json,
        "current_draft_version": plan.current_draft_version,
        "current_confirmed_version": plan.current_confirmed_version,
    }


def _confirmation_summary(row: LocalWeeklyPlanConfirmation) -> dict:
    return {
        "id": row.id,
        "version": row.version,
        "draft_version": row.draft_version,
        "snapshot_hash": row.snapshot_hash,
    }


def _settings(session: Session) -> LocalSettings:
    settings = session.get(LocalSettings, "singleton")
    if settings is None:
        raise LocalStorageError("本地设置缺失")
    return settings


def _live_snapshot(session: Session, plan: LocalWeeklyPlan) -> dict:
    """Live comparison basis: current term revision/bounds, fixed plan identity.

    The draft's own calendar_basis/header/anchor/week remain the fixed target;
    only the comparison snapshot follows the term's current revision and
    real bounds so a moved term/calendar is visible as stale/warnings.
    """
    settings = _settings(session)
    term = session.get(LocalTerm, plan.term_id)
    if term is None:
        raise LocalStorageError("周计划所属学期缺失")
    revision = _term_revision(session, term)
    return sources.load_source_snapshot(
        session,
        profile_id=plan.profile_id,
        class_id=plan.class_id,
        term_id=plan.term_id,
        week_anchor_date=plan.week_anchor_date,
        calendar_revision_id=revision.id,
        term_start=term.start_date,
        term_end=term.end_date,
        week_number=plan.week_number_snapshot,
        header=plan.header_json,
        config_version=settings.config_version,
    )


def _create_snapshot(
    session: Session, *, profile_id: str, term_id: str, anchor: date
) -> tuple[dict, LocalTerm]:
    context = require_context(session, date.today())
    assert context.school_class is not None and context.settings is not None
    term = session.get(LocalTerm, term_id)
    if term is None:
        raise LocalValidationError("学期不存在")
    if anchor.isoweekday() != 1:
        raise LocalValidationError("周起始日期必须是周一")
    if anchor < cal.week_anchor(term.start_date) or anchor > term.end_date:
        raise LocalValidationError("周起始日期不在该学期范围内")
    if anchor + timedelta(days=6) < term.start_date:
        raise LocalValidationError("该周与学期没有交集")
    revision = _term_revision(session, term)
    week_number, _start, _weekday = cal.week_info(term.start_date, anchor)
    header = sources.header_from_class(
        context.settings.school_name, context.school_class
    )
    snapshot = sources.load_source_snapshot(
        session,
        profile_id=profile_id,
        class_id=context.school_class.id,
        term_id=term.id,
        week_anchor_date=anchor,
        calendar_revision_id=revision.id,
        term_start=term.start_date,
        term_end=term.end_date,
        week_number=week_number,
        header=header,
        config_version=context.settings.config_version,
    )
    return snapshot, term


def _find_plan(
    session: Session, *, class_id: str, term_id: str, anchor: date
) -> LocalWeeklyPlan | None:
    return session.scalars(
        select(LocalWeeklyPlan).where(
            LocalWeeklyPlan.class_id == class_id,
            LocalWeeklyPlan.term_id == term_id,
            LocalWeeklyPlan.week_anchor_date == anchor,
        )
    ).first()


def _facts(
    session: Session,
    plan: LocalWeeklyPlan | None,
    content: dict,
    snapshot: dict,
) -> dict:
    facts = _content_call(_content_module().build_facts, content, snapshot)
    if plan is not None and content.get("schema_version") == 2:
        try:
            from app.local import weekly_ai_inputs, weekly_ai_sources

            raw = weekly_ai_sources.load_raw_manifest(
                session, plan=plan, content=_current_content(session, plan)
            )
            ai_facts = weekly_ai_inputs.build_ai_facts(content, raw)
            for key in ("missing", "stale_sources", "warnings"):
                facts.setdefault(key, [])
                facts[key].extend(list(ai_facts.get(key) or []))
        except Exception:
            # Facts are advisory; a broken optional AI basis must not hide the
            # manual draft or turn a read into a 500.
            pass
    return facts


def _candidates(snapshot: dict) -> list[dict]:
    return _content_call(_content_module().build_source_candidates, snapshot)


def _new_content(snapshot: dict, *, theme: str = "") -> dict:
    return _content_call(_content_module().new_content, snapshot, theme=theme)


def _manual_ids(patch: dict, previous: dict) -> dict[str, str]:
    """Assign server-owned IDs for new manual slots (client_key only)."""
    mapping: dict[str, str] = {}
    slots = patch.get("outdoor_game_slots")
    if isinstance(slots, dict):
        for value in slots.values():
            if (
                isinstance(value, dict)
                and value.get("source_kind") == "manual"
                and not value.get("manual_item_id")
            ):
                key = value.get("client_key")
                if isinstance(key, str) and key:
                    mapping[key] = new_opaque_id()
    focus = patch.get("focus_area")
    if (
        isinstance(focus, dict)
        and focus.get("source_kind") == "manual"
        and not focus.get("manual_item_id")
    ):
        key = focus.get("client_key")
        if isinstance(key, str) and key:
            mapping[key] = new_opaque_id()
    return mapping


def _selector_matches(snapshot: dict, selector: dict, *, section: str) -> bool:
    if selector.get("source_kind") != "daily_plan":
        return False
    if selector.get("section") != section:
        return False
    day = next(
        (
            item
            for item in snapshot["days"]
            if item.get("source")
            and item["source"]["daily_plan_id"] == selector.get("daily_plan_id")
        ),
        None,
    )
    if day is None:
        return False
    source = day["source"]
    if (
        source["content_id"] != selector.get("content_id")
        or source["content_version"] != selector.get("content_version")
        or source["content_hash"] != selector.get("content_hash")
    ):
        return False
    groups = day["morning_groups"] if section == "morning_games" else day["post_group_groups"]
    for group in groups:
        if group["group_id"] != selector.get("group_id"):
            continue
        if any(
            game["game_id"] == selector.get("game_id")
            for game in group["games"]
        ):
            return True
    return False


def _validate_selectors(patch: dict, snapshot: dict) -> None:
    """Reject an explicit reselect whose exact source is not in the snapshot."""
    slots = patch.get("outdoor_game_slots")
    if isinstance(slots, dict):
        for value in slots.values():
            if not isinstance(value, dict):
                continue
            kind = value.get("source_kind")
            if kind == "manual":
                continue
            if kind != "daily_plan" or not _selector_matches(
                snapshot, value, section="morning_games"
            ):
                raise LocalWeeklySourceChanged()
    focus = patch.get("focus_area")
    if isinstance(focus, dict) and focus.get("source_kind") != "manual":
        if focus.get("source_kind") != "daily_plan" or not _selector_matches(
            snapshot, focus, section="post_group_games"
        ):
            raise LocalWeeklySourceChanged()


def _apply_patch(previous: dict, patch: dict, snapshot: dict) -> dict:
    module = _content_module()
    _validate_selectors(patch, snapshot)
    content = _content_call(
        module.apply_patch,
        previous,
        patch,
        snapshot,
        manual_ids=_manual_ids(patch, previous),
    )
    _content_call(module.validate_content, content, snapshot=snapshot)
    if len(
        _content_call(module.canonical_json, content).encode("utf-8")
    ) > MAX_CONTENT_BYTES:
        raise LocalWeeklyInvalid("周计划正文超过 1MiB 上限")
    return content


def _insert_content(
    session: Session,
    *,
    plan: LocalWeeklyPlan,
    version: int,
    content: dict,
    editor_profile_id: str,
    now: datetime,
) -> LocalWeeklyPlanContent:
    content_hash = _content_call(_content_module().content_hash, content)
    row = LocalWeeklyPlanContent(
        id=new_opaque_id(),
        weekly_plan_id=plan.id,
        version=version,
        schema_version=_content_call(
            _content_module().content_schema_version, content
        ),
        content_json=content,
        content_hash=content_hash,
        editor_profile_id=editor_profile_id,
        created_at=now,
    )
    session.add(row)
    session.flush()
    plan.current_draft_id = row.id
    plan.current_draft_version = version
    plan.updated_at = now
    session.flush()
    return row


def _write_result(
    plan: LocalWeeklyPlan,
    draft: LocalWeeklyPlanContent | None,
    confirmation: LocalWeeklyPlanConfirmation | None,
    *,
    replayed: bool,
) -> dict:
    return {
        "operation_id": None,
        "request_id": None,
        "status": "committed",
        "weekly_plan_id": plan.id,
        "draft": _draft_payload(draft) if draft is not None else None,
        "confirmation": (
            _confirmation_summary(confirmation)
            if confirmation is not None
            else None
        ),
        "replayed": replayed,
    }


def _receipt_payload(result: dict) -> dict:
    """Strict flat §11.6 metadata: identifiers only, no body/header/facts."""
    draft = result.get("draft") if isinstance(result.get("draft"), dict) else None
    confirmation = (
        result.get("confirmation")
        if isinstance(result.get("confirmation"), dict)
        else None
    )
    return {
        "schema_version": 1,
        "weekly_plan_id": result.get("weekly_plan_id"),
        "draft_id": draft.get("id") if draft else None,
        "draft_version": draft.get("version") if draft else None,
        "confirmation_id": confirmation.get("id") if confirmation else None,
        "confirmation_version": (
            confirmation.get("version") if confirmation else None
        ),
        "snapshot_id": None,
        "token_id": None,
    }


def _finish_result(session: Session, row, *, replayed: bool) -> dict:
    metadata = dict(row.result_json)
    payload = {
        "operation_id": row.id,
        "request_id": row.request_id,
        "status": "committed",
        "weekly_plan_id": metadata.get("weekly_plan_id"),
        "draft": None,
        "confirmation": None,
        "replayed": replayed,
    }
    draft_id = metadata.get("draft_id")
    if draft_id is not None:
        content = session.get(
            LocalWeeklyPlanContent, draft_id, populate_existing=True
        )
        if (
            content is None
            or content.weekly_plan_id != metadata.get("weekly_plan_id")
            or content.version != metadata.get("draft_version")
        ):
            raise LocalStorageError("周计划回执草稿版本缺失")
        payload["draft"] = _draft_payload(content)
    confirmation_id = metadata.get("confirmation_id")
    if confirmation_id is not None:
        confirmation = session.get(
            LocalWeeklyPlanConfirmation, confirmation_id, populate_existing=True
        )
        if (
            confirmation is None
            or confirmation.weekly_plan_id != metadata.get("weekly_plan_id")
            or confirmation.version != metadata.get("confirmation_version")
        ):
            raise LocalStorageError("周计划回执确认版本缺失")
        payload["confirmation"] = _confirmation_summary(confirmation)
    return payload


def _store(
    session: Session,
    *,
    profile_id: str,
    request_id: str,
    action: str,
    fingerprint: str,
    result: dict,
    **result_fields: Any,
):
    return operations.store_receipt(
        session,
        profile_id=profile_id,
        request_id=request_id,
        action=action,
        fingerprint=fingerprint,
        result=_receipt_payload(result),
        **result_fields,
    )


# ---------------------------------------------------------------------------
# Create / read
# ---------------------------------------------------------------------------


def create_preview(
    session: Session,
    *,
    runtime: Any,
    profile_id: str,
    launch_id: str,
    session_scope_hash: str,
    term_id: object,
    week_anchor_date: object,
) -> dict:
    if not isinstance(term_id, str) or not term_id or len(term_id) > 32:
        raise LocalValidationError("term_id 不合法")
    if not isinstance(week_anchor_date, date):
        raise LocalValidationError("week_anchor_date 必须是日期")
    with read_scope(session):
        context = require_context(session, date.today())
        assert context.school_class is not None
        existing = _find_plan(
            session,
            class_id=context.school_class.id,
            term_id=term_id,
            anchor=week_anchor_date,
        )
        if existing is not None:
            draft = _current_content(session, existing)
            snapshot = _live_snapshot(session, existing)
            confirmed = None
            if existing.current_confirmed_id:
                row = session.get(
                    LocalWeeklyPlanConfirmation,
                    existing.current_confirmed_id,
                )
                if row is not None and row.weekly_plan_id == existing.id:
                    confirmed = _confirmation_summary(row)
            return {
                "status": "existing",
                "plan": _summary(existing),
                "draft": _draft_payload(draft),
                "confirmed": confirmed,
                "source_candidates": _candidates(snapshot),
                "source_context_hash": snapshot["source_context_hash"],
                "facts": _facts(session, existing, draft.content_json, snapshot),
                "create_token": None,
                "expected_config_version": None,
                "expires_at": None,
            }
        snapshot, term = _create_snapshot(
            session,
            profile_id=profile_id,
            term_id=term_id,
            anchor=week_anchor_date,
        )
    content = _new_content(snapshot)
    object_id = f"{term_id}:{week_anchor_date.isoformat()}"
    create_token = tokens.issue_token(
        runtime,
        purpose="create",
        profile_id=profile_id,
        launch_id=launch_id,
        session_scope_hash=session_scope_hash,
        object_id=object_id,
        expected_version=snapshot["config_version"],
        source_context_hash=snapshot["source_context_hash"],
        target_hash=_hash(snapshot["header"]),
    )
    return {
        "status": "new",
        "header": snapshot["header"],
        "week_number": snapshot["week_number"],
        "calendar": {
            "week_anchor_date": snapshot["week_anchor_date"],
            "term_start": snapshot["term_start"],
            "term_end": snapshot["term_end"],
            "calendar_revision_id": snapshot["calendar_revision_id"],
            "days": [
                {
                    "date": item["date"],
                    "day_state": item["day_state"],
                    "source_state": item["source_state"],
                }
                for item in snapshot["days"]
            ],
        },
        "source_candidates": _candidates(snapshot),
        "source_context_hash": snapshot["source_context_hash"],
        "facts": _facts(session, None, content, snapshot),
        "create_token": create_token,
        "expected_config_version": snapshot["config_version"],
        "expires_at": _token_expires_at(),
    }


def create_or_open(
    session: Session,
    *,
    runtime: Any,
    profile_id: str,
    launch_id: str,
    session_scope_hash: str,
    request_id: object,
    term_id: object,
    week_anchor_date: object,
    expected_config_version: object,
    context_token: object,
) -> tuple[dict, bool]:
    rid = normalize_request_id(request_id)
    if not isinstance(term_id, str) or not term_id:
        raise LocalValidationError("term_id 不合法")
    if not isinstance(week_anchor_date, date):
        raise LocalValidationError("week_anchor_date 必须是日期")
    expected = _validate_version(expected_config_version, "expected_config_version")
    payload = {
        "term_id": term_id,
        "week_anchor_date": week_anchor_date.isoformat(),
        "expected_config_version": expected,
        "context_token_hash": tokens.token_hash(str(context_token)),
    }
    fingerprint = operations.fingerprint("create", payload)
    with read_scope(session):
        receipt = operations.find_receipt(
            session,
            profile_id=profile_id,
            request_id=rid,
            action="create",
            fingerprint=fingerprint,
        )
        if receipt is not None:
            return _finish_result(session, receipt, replayed=True), False
        context = require_context(session, date.today())
        assert context.school_class is not None
        existing = _find_plan(
            session,
            class_id=context.school_class.id,
            term_id=term_id,
            anchor=week_anchor_date,
        )
    if existing is not None:
        begin_immediate(session)
        try:
            receipt = operations.find_receipt(
                session,
                profile_id=profile_id,
                request_id=rid,
                action="create",
                fingerprint=fingerprint,
            )
            if receipt is not None:
                response = _finish_result(session, receipt, replayed=True)
                rollback(session)
                return response, False
            context = require_context(session, date.today())
            assert context.school_class is not None
            existing = _find_plan(
                session,
                class_id=context.school_class.id,
                term_id=term_id,
                anchor=week_anchor_date,
            )
            if existing is not None:
                draft = _current_content(session, existing)
                result = _write_result(existing, draft, None, replayed=False)
                receipt = _store(
                    session,
                    profile_id=profile_id,
                    request_id=rid,
                    action="create",
                    fingerprint=fingerprint,
                    result=result,
                    weekly_plan_id=existing.id,
                    result_draft_id=draft.id,
                    result_draft_version=draft.version,
                )
                response = _finish_result(session, receipt, replayed=False)
                session.commit()
                return response, False
            rollback(session)
        except BaseException:
            rollback(session)
            raise
    tokens.verify_token(
        runtime,
        context_token,
        purpose="create",
        profile_id=profile_id,
        launch_id=launch_id,
        session_scope_hash=session_scope_hash,
        object_id=f"{term_id}:{week_anchor_date.isoformat()}",
        expected_version=expected,
    )
    begin_immediate(session)
    try:
        context = require_context(session, date.today())
        assert context.school_class is not None and context.settings is not None
        receipt = operations.find_receipt(
            session,
            profile_id=profile_id,
            request_id=rid,
            action="create",
            fingerprint=fingerprint,
        )
        if receipt is not None:
            result = _finish_result(session, receipt, replayed=True)
            rollback(session)
            return result, False
        existing = _find_plan(
            session,
            class_id=context.school_class.id,
            term_id=term_id,
            anchor=week_anchor_date,
        )
        if existing is not None:
            draft = _current_content(session, existing)
            result = _write_result(existing, draft, None, replayed=False)
            receipt = _store(
                session,
                profile_id=profile_id,
                request_id=rid,
                action="create",
                fingerprint=fingerprint,
                result=result,
                weekly_plan_id=existing.id,
                result_draft_id=draft.id,
                result_draft_version=draft.version,
            )
            response = _finish_result(session, receipt, replayed=False)
            session.commit()
            return response, False
        if context.settings.config_version != expected:
            raise LocalWeeklyVersionConflict(
                details={"config_version": context.settings.config_version}
            )
        snapshot, term = _create_snapshot(
            session,
            profile_id=profile_id,
            term_id=term_id,
            anchor=week_anchor_date,
        )
        if snapshot["config_version"] != expected:
            raise LocalWeeklyVersionConflict(
                details={"config_version": snapshot["config_version"]}
            )
        tokens.verify_token(
            runtime,
            context_token,
            purpose="create",
            profile_id=profile_id,
            launch_id=launch_id,
            session_scope_hash=session_scope_hash,
            object_id=f"{term_id}:{week_anchor_date.isoformat()}",
            expected_version=expected,
            source_context_hash=snapshot["source_context_hash"],
        )
        content = _new_content(snapshot)
        now = _utc_now()
        plan = LocalWeeklyPlan(
            id=new_opaque_id(),
            profile_id=profile_id,
            class_id=snapshot["class_id"],
            term_id=term.id,
            week_anchor_date=week_anchor_date,
            week_number_snapshot=snapshot["week_number"],
            term_start_date=date.fromisoformat(snapshot["term_start"]),
            term_end_date=date.fromisoformat(snapshot["term_end"]),
            calendar_revision_id=snapshot["calendar_revision_id"],
            header_json=snapshot["header"],
            header_hash=_hash(snapshot["header"]),
            current_draft_id="pending",
            current_draft_version=1,
            created_at=now,
            updated_at=now,
        )
        session.add(plan)
        session.flush()
        row = _insert_content(
            session,
            plan=plan,
            version=1,
            content=content,
            editor_profile_id=profile_id,
            now=now,
        )
        result = _write_result(plan, row, None, replayed=False)
        receipt = _store(
            session,
            profile_id=profile_id,
            request_id=rid,
            action="create",
            fingerprint=fingerprint,
            result=result,
            weekly_plan_id=plan.id,
            result_draft_id=row.id,
            result_draft_version=row.version,
        )
        response = _finish_result(session, receipt, replayed=False)
        session.commit()
        return response, True
    except BaseException:
        rollback(session)
        raise


def list_plans(
    session: Session,
    *,
    profile_id: str,
    term_id: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    cursor: str | None = None,
    limit: int = DEFAULT_LIST_LIMIT,
) -> dict:
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise LocalValidationError("limit 不合法")
    limit = max(1, min(limit, MAX_LIST_LIMIT))
    with read_scope(session):
        context = require_context(session, date.today())
        assert context.school_class is not None
        query = select(LocalWeeklyPlan).where(
            LocalWeeklyPlan.profile_id == profile_id,
            LocalWeeklyPlan.class_id == context.school_class.id,
        )
        if term_id is not None:
            query = query.where(LocalWeeklyPlan.term_id == term_id)
        if from_date is not None:
            query = query.where(LocalWeeklyPlan.week_anchor_date >= from_date)
        if to_date is not None:
            query = query.where(LocalWeeklyPlan.week_anchor_date <= to_date)
        if cursor:
            try:
                raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
                anchor_raw, plan_id = raw.decode("utf-8").split("\x00", 1)
                anchor = date.fromisoformat(anchor_raw)
            except (ValueError, UnicodeDecodeError):
                raise LocalValidationError("cursor 不合法") from None
            query = query.where(
                (LocalWeeklyPlan.week_anchor_date < anchor)
                | (
                    (LocalWeeklyPlan.week_anchor_date == anchor)
                    & (LocalWeeklyPlan.id < plan_id)
                )
            )
        rows = session.scalars(
            query.order_by(
                LocalWeeklyPlan.week_anchor_date.desc(),
                LocalWeeklyPlan.id.desc(),
            ).limit(limit + 1)
        ).all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = []
        for plan in rows:
            content = _current_content(session, plan)
            snapshot = _live_snapshot(session, plan)
            item = _summary(plan)
            item["facts"] = _facts(session, plan, content.content_json, snapshot)
            items.append(item)
        next_cursor = None
        if has_more and rows:
            last = rows[-1]
            next_cursor = base64.urlsafe_b64encode(
                f"{last.week_anchor_date.isoformat()}\x00{last.id}".encode("utf-8")
            ).rstrip(b"=").decode("ascii")
        return {"items": items, "next_cursor": next_cursor}


def get_detail(session: Session, *, profile_id: str, plan_id: str) -> dict:
    with read_scope(session):
        plan = _plan_or_404(session, profile_id, plan_id)
        content = _current_content(session, plan)
        snapshot = _live_snapshot(session, plan)
        confirmation = None
        if plan.current_confirmed_id:
            row = session.get(
                LocalWeeklyPlanConfirmation, plan.current_confirmed_id
            )
            if row is not None and row.weekly_plan_id == plan.id:
                confirmation = _confirmation_summary(row)
        return {
            "plan": _summary(plan),
            "draft": _draft_payload(content),
            "confirmed": confirmation,
            "source_candidates": _candidates(snapshot),
            "source_context_hash": snapshot["source_context_hash"],
            "facts": _facts(session, plan, content.content_json, snapshot),
        }


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------


def save_draft(
    session: Session,
    *,
    profile_id: str,
    request_id: object,
    plan_id: str,
    expected_draft_version: object,
    patch: object,
) -> dict:
    rid = normalize_request_id(request_id)
    expected = _validate_version(expected_draft_version)
    if not isinstance(patch, dict):
        raise LocalWeeklyInvalid("patch 必须是对象")
    fingerprint = operations.fingerprint(
        "save",
        {
            "plan_id": plan_id,
            "expected_draft_version": expected,
            "patch": patch,
        },
    )
    with read_scope(session):
        receipt = operations.find_receipt(
            session,
            profile_id=profile_id,
            request_id=rid,
            action="save",
            fingerprint=fingerprint,
        )
        if receipt is not None:
            return _finish_result(session, receipt, replayed=True)
    begin_immediate(session)
    try:
        plan = _plan_or_404(session, profile_id, plan_id)
        receipt = operations.find_receipt(
            session,
            profile_id=profile_id,
            request_id=rid,
            action="save",
            fingerprint=fingerprint,
        )
        if receipt is not None:
            result = _finish_result(session, receipt, replayed=True)
            rollback(session)
            return result
        content = _current_content(session, plan)
        if content.version != expected:
            raise LocalWeeklyVersionConflict(
                details={"draft_version": content.version}
            )
        snapshot = _live_snapshot(session, plan)
        new_content = _apply_patch(content.content_json, patch, snapshot)
        new_hash = _content_call(
            _content_module().content_hash, new_content
        )
        now = _utc_now()
        if new_hash == content.content_hash:
            row = content
        else:
            row = _insert_content(
                session,
                plan=plan,
                version=content.version + 1,
                content=new_content,
                editor_profile_id=profile_id,
                now=now,
            )
        result = _write_result(plan, row, None, replayed=False)
        receipt = _store(
            session,
            profile_id=profile_id,
            request_id=rid,
            action="save",
            fingerprint=fingerprint,
            result=result,
            weekly_plan_id=plan.id,
            result_draft_id=row.id,
            result_draft_version=row.version,
        )
        response = _finish_result(session, receipt, replayed=False)
        session.commit()
        return response
    except BaseException:
        rollback(session)
        raise


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------


def refresh_preview(
    session: Session,
    *,
    runtime: Any,
    profile_id: str,
    launch_id: str,
    session_scope_hash: str,
    plan_id: str,
    expected_draft_version: object,
) -> dict:
    expected = _validate_version(expected_draft_version)
    with read_scope(session):
        plan = _plan_or_404(session, profile_id, plan_id)
        content = _current_content(session, plan)
        if content.version != expected:
            raise LocalWeeklyVersionConflict(
                details={"draft_version": content.version}
            )
        snapshot = _live_snapshot(session, plan)
    refreshed = _content_call(
        _content_module().refresh_content, content.content_json, snapshot
    )
    target = refreshed["content"]
    target_hash = _content_call(_content_module().content_hash, target)
    token = tokens.issue_token(
        runtime,
        purpose="refresh",
        profile_id=profile_id,
        launch_id=launch_id,
        session_scope_hash=session_scope_hash,
        object_id=plan.id,
        expected_version=expected,
        source_context_hash=snapshot["source_context_hash"],
        target_hash=target_hash,
    )
    return {
        "target_draft_version": expected + 1,
        "content": target,
        "content_hash": target_hash,
        "differences": refreshed.get("differences", []),
        "preserved": refreshed.get("preserved", []),
        "source_candidates": _candidates(snapshot),
        "source_context_hash": snapshot["source_context_hash"],
        "facts": _facts(session, plan, target, snapshot),
        "preview_token": token,
        "expires_at": _token_expires_at(),
    }


def refresh_sources(
    session: Session,
    *,
    runtime: Any,
    profile_id: str,
    launch_id: str,
    session_scope_hash: str,
    request_id: object,
    plan_id: str,
    expected_draft_version: object,
    preview_token: object,
) -> dict:
    rid = normalize_request_id(request_id)
    expected = _validate_version(expected_draft_version)
    fingerprint = operations.fingerprint(
        "refresh",
        {
            "plan_id": plan_id,
            "expected_draft_version": expected,
            "preview_token_hash": tokens.token_hash(str(preview_token)),
        },
    )
    with read_scope(session):
        receipt = operations.find_receipt(
            session,
            profile_id=profile_id,
            request_id=rid,
            action="refresh",
            fingerprint=fingerprint,
        )
        if receipt is not None:
            return _finish_result(session, receipt, replayed=True)
    begin_immediate(session)
    try:
        plan = _plan_or_404(session, profile_id, plan_id)
        receipt = operations.find_receipt(
            session,
            profile_id=profile_id,
            request_id=rid,
            action="refresh",
            fingerprint=fingerprint,
        )
        if receipt is not None:
            result = _finish_result(session, receipt, replayed=True)
            rollback(session)
            return result
        content = _current_content(session, plan)
        if content.version != expected:
            raise LocalWeeklyVersionConflict(
                details={"draft_version": content.version}
            )
        snapshot = _live_snapshot(session, plan)
        payload = tokens.verify_token(
            runtime,
            preview_token,
            purpose="refresh",
            profile_id=profile_id,
            launch_id=launch_id,
            session_scope_hash=session_scope_hash,
            object_id=plan.id,
            expected_version=expected,
            source_context_hash=snapshot["source_context_hash"],
        )
        refreshed = _content_call(
            _content_module().refresh_content, content.content_json, snapshot
        )
        target = refreshed["content"]
        target_hash = _content_call(_content_module().content_hash, target)
        if payload.get("target_hash") != target_hash:
            raise LocalWeeklyPreviewStale()
        row = _insert_content(
            session,
            plan=plan,
            version=content.version + 1,
            content=target,
            editor_profile_id=profile_id,
            now=_utc_now(),
        )
        result = _write_result(plan, row, None, replayed=False)
        receipt = _store(
            session,
            profile_id=profile_id,
            request_id=rid,
            action="refresh",
            fingerprint=fingerprint,
            result=result,
            weekly_plan_id=plan.id,
            result_draft_id=row.id,
            result_draft_version=row.version,
        )
        response = _finish_result(session, receipt, replayed=False)
        session.commit()
        return response
    except BaseException:
        rollback(session)
        raise


# ---------------------------------------------------------------------------
# Confirmation / history
# ---------------------------------------------------------------------------


def confirmation_preview(
    session: Session,
    *,
    runtime: Any,
    profile_id: str,
    launch_id: str,
    session_scope_hash: str,
    plan_id: str,
    expected_draft_version: object,
) -> dict:
    expected = _validate_version(expected_draft_version)
    with read_scope(session):
        plan = _plan_or_404(session, profile_id, plan_id)
        content = _current_content(session, plan)
        if content.version != expected:
            raise LocalWeeklyVersionConflict(
                details={"draft_version": content.version}
            )
        live = _live_snapshot(session, plan)
    facts = _facts(session, plan, content.content_json, live)
    target = _confirmation_snapshot(plan, content, facts)
    target_hash = confirmation_schema.snapshot_hash(target)
    token = tokens.issue_token(
        runtime,
        purpose="confirm",
        profile_id=profile_id,
        launch_id=launch_id,
        session_scope_hash=session_scope_hash,
        object_id=plan.id,
        expected_version=expected,
        source_context_hash=live["source_context_hash"],
        facts_hash=_hash(facts),
        target_hash=target_hash,
    )
    return {
        "target": target,
        "target_hash": target_hash,
        "preview_token": token,
        "expires_at": _token_expires_at(),
    }


def _confirmation_snapshot(
    plan: LocalWeeklyPlan,
    content: LocalWeeklyPlanContent,
    facts: dict,
) -> dict:
    return confirmation_schema.build_confirmation_snapshot(
        weekly_plan_id=plan.id,
        profile_id=plan.profile_id,
        class_id=plan.class_id,
        term_id=plan.term_id,
        draft_id=content.id,
        draft_version=content.version,
        content_hash=content.content_hash,
        header=plan.header_json,
        creation_context={
            "week_anchor_date": plan.week_anchor_date.isoformat(),
            "week_number_snapshot": plan.week_number_snapshot,
            "term_start": plan.term_start_date.isoformat(),
            "term_end": plan.term_end_date.isoformat(),
            "calendar_revision_id": plan.calendar_revision_id,
        },
        content=content.content_json,
        facts=facts,
    )


def confirm(
    session: Session,
    *,
    runtime: Any,
    profile_id: str,
    launch_id: str,
    session_scope_hash: str,
    request_id: object,
    plan_id: str,
    expected_draft_version: object,
    context_token: object,
    ack_missing: object,
    ack_stale: object,
    note: object = None,
) -> dict:
    rid = normalize_request_id(request_id)
    expected = _validate_version(expected_draft_version)
    if not isinstance(ack_missing, bool) or not isinstance(ack_stale, bool):
        raise LocalValidationError("ack_missing/ack_stale 必须是布尔值")
    note_value = _validate_note(note)
    fingerprint = operations.fingerprint(
        "confirm",
        {
            "plan_id": plan_id,
            "expected_draft_version": expected,
            "context_token_hash": tokens.token_hash(str(context_token)),
            "ack_missing": ack_missing,
            "ack_stale": ack_stale,
            "note": note_value,
        },
    )
    with read_scope(session):
        receipt = operations.find_receipt(
            session,
            profile_id=profile_id,
            request_id=rid,
            action="confirm",
            fingerprint=fingerprint,
        )
        if receipt is not None:
            return _finish_result(session, receipt, replayed=True)
    begin_immediate(session)
    try:
        plan = _plan_or_404(session, profile_id, plan_id)
        receipt = operations.find_receipt(
            session,
            profile_id=profile_id,
            request_id=rid,
            action="confirm",
            fingerprint=fingerprint,
        )
        if receipt is not None:
            result = _finish_result(session, receipt, replayed=True)
            rollback(session)
            return result
        content = _current_content(session, plan)
        if content.version != expected:
            raise LocalWeeklyVersionConflict(
                details={"draft_version": content.version}
            )
        live = _live_snapshot(session, plan)
        facts = _facts(session, plan, content.content_json, live)
        facts_hash = _hash(facts)
        snapshot_json = _confirmation_snapshot(plan, content, facts)
        snapshot_hash = confirmation_schema.snapshot_hash(snapshot_json)
        tokens.verify_token(
            runtime,
            context_token,
            purpose="confirm",
            profile_id=profile_id,
            launch_id=launch_id,
            session_scope_hash=session_scope_hash,
            object_id=plan.id,
            expected_version=expected,
            source_context_hash=live["source_context_hash"],
            facts_hash=facts_hash,
            target_hash=snapshot_hash,
        )
        if facts.get("missing") and not ack_missing:
            raise LocalWeeklyAckRequired(details={"reason": "missing"})
        if facts.get("stale_sources") and not ack_stale:
            raise LocalWeeklyAckRequired(details={"reason": "stale"})
        version = (
            session.scalar(
                select(func.max(LocalWeeklyPlanConfirmation.version)).where(
                    LocalWeeklyPlanConfirmation.weekly_plan_id == plan.id
                )
            )
            or 0
        ) + 1
        now = _utc_now()
        row = LocalWeeklyPlanConfirmation(
            id=new_opaque_id(),
            weekly_plan_id=plan.id,
            version=version,
            draft_id=content.id,
            draft_version=content.version,
            schema_version=1,
            snapshot_json=snapshot_json,
            snapshot_hash=snapshot_hash,
            facts_json=facts,
            facts_hash=facts_hash,
            note=note_value,
            confirmed_by=profile_id,
            confirmed_at=now,
        )
        session.add(row)
        session.flush()
        plan.current_confirmed_id = row.id
        plan.current_confirmed_version = row.version
        plan.updated_at = now
        session.flush()
        result = _write_result(plan, content, row, replayed=False)
        receipt = _store(
            session,
            profile_id=profile_id,
            request_id=rid,
            action="confirm",
            fingerprint=fingerprint,
            result=result,
            weekly_plan_id=plan.id,
            result_draft_id=content.id,
            result_draft_version=content.version,
            result_confirmed_id=row.id,
            result_confirmed_version=row.version,
        )
        response = _finish_result(session, receipt, replayed=False)
        session.commit()
        return response
    except BaseException:
        rollback(session)
        raise


def list_confirmations(
    session: Session, *, profile_id: str, plan_id: str
) -> dict:
    with read_scope(session):
        plan = _plan_or_404(session, profile_id, plan_id)
        rows = session.scalars(
            select(LocalWeeklyPlanConfirmation)
            .where(LocalWeeklyPlanConfirmation.weekly_plan_id == plan.id)
            .order_by(LocalWeeklyPlanConfirmation.version.desc())
        ).all()
        return {"items": [_confirmation_summary(row) for row in rows]}


def get_confirmation(
    session: Session, *, profile_id: str, plan_id: str, confirmation_id: str
) -> dict:
    with read_scope(session):
        plan = _plan_or_404(session, profile_id, plan_id)
        row = session.get(LocalWeeklyPlanConfirmation, confirmation_id)
        if row is None or row.weekly_plan_id != plan.id:
            raise LocalWeeklyConfirmationNotFound()
        return {
            "confirmation": _confirmation_summary(row),
            "snapshot": row.snapshot_json,
            "note": row.note,
            "confirmed_by": row.confirmed_by,
            "confirmed_at": row.confirmed_at.isoformat(),
        }


def get_operation(
    session: Session, *, profile_id: str, request_id: str
) -> dict:
    with read_scope(session):
        row = operations.find_receipt(
            session, profile_id=profile_id, request_id=request_id
        )
        if row is None:
            raise LocalWeeklyOperationNotFound()
        return dict(row.result_json)


def get_business_operation(
    session: Session, *, profile_id: str, request_id: str
) -> dict:
    """Public weekly-plan operation projection; export actions stay D-owned."""
    with read_scope(session):
        row = operations.find_receipt(
            session, profile_id=profile_id, request_id=request_id
        )
        if row is None or row.action not in (
            "create",
            "save",
            "refresh",
            "confirm",
        ):
            raise LocalWeeklyOperationNotFound()
        return _finish_result(session, row, replayed=False)
