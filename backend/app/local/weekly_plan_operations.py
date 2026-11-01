"""Persistent weekly-plan request receipts (business and export).

The helper never commits and never owns a transaction.  Callers pass a
trusted session/profile/action and a canonical fingerprint; the same
(profile_id, request_id) replays only when action and fingerprint match.

§11.6 freezes ``result_json`` to one flat versioned metadata object.  It
stores identifiers only: no content, snapshot/header/facts, path, DOCX,
context token or plaintext export id, and never duplicates the operation's
own id/request id.
"""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ids import new_opaque_id
from app.local.errors import LocalWeeklyOperationConflict, LocalWeeklyInvalid
from app.local.models import (
    LocalWeeklyExportAttempt,
    LocalWeeklyExportToken,
    LocalWeeklyPlanOperation,
)
from app.local.weekly_plan_tokens import canonical_json

METADATA_KEYS = frozenset(
    {
        "schema_version",
        "weekly_plan_id",
        "draft_id",
        "draft_version",
        "confirmation_id",
        "confirmation_version",
        "snapshot_id",
        "token_id",
    }
)


def fingerprint(action: str, payload: Any) -> str:
    raw = f"{action}\x00{canonical_json(payload)}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _optional_id(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not (1 <= len(value) <= 32):
        raise LocalWeeklyInvalid(f"回执 {label} 不合法")
    return value


def _optional_version(value: Any, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise LocalWeeklyInvalid(f"回执 {label} 不合法")
    return value


def validate_metadata(
    result: Any,
    *,
    weekly_plan_id: str | None,
    draft_id: str | None,
    draft_version: int | None,
    confirmation_id: str | None,
    confirmation_version: int | None,
    snapshot_id: str | None,
    token_id: str | None,
) -> dict:
    if not isinstance(result, dict) or set(result) != METADATA_KEYS:
        raise LocalWeeklyInvalid("回执 metadata 字段不完整")
    schema_version = result.get("schema_version")
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version != 1
    ):
        raise LocalWeeklyInvalid("回执 metadata schema_version 必须为 1")
    values = {
        "weekly_plan_id": _optional_id(result.get("weekly_plan_id"), "weekly_plan_id"),
        "draft_id": _optional_id(result.get("draft_id"), "draft_id"),
        "draft_version": _optional_version(
            result.get("draft_version"), "draft_version"
        ),
        "confirmation_id": _optional_id(
            result.get("confirmation_id"), "confirmation_id"
        ),
        "confirmation_version": _optional_version(
            result.get("confirmation_version"), "confirmation_version"
        ),
        "snapshot_id": _optional_id(result.get("snapshot_id"), "snapshot_id"),
        "token_id": _optional_id(result.get("token_id"), "token_id"),
    }
    pairs = (
        ("draft_id", "draft_version"),
        ("confirmation_id", "confirmation_version"),
        ("snapshot_id", "token_id"),
    )
    for left, right in pairs:
        if (values[left] is None) != (values[right] is None):
            raise LocalWeeklyInvalid("回执引用必须成对完整")
    if values["confirmation_id"] is not None and values["draft_id"] is None:
        raise LocalWeeklyInvalid("确认回执必须带原草稿引用")
    expected = {
        "weekly_plan_id": weekly_plan_id,
        "draft_id": draft_id,
        "draft_version": draft_version,
        "confirmation_id": confirmation_id,
        "confirmation_version": confirmation_version,
        "snapshot_id": snapshot_id,
        "token_id": token_id,
    }
    if values != expected:
        raise LocalWeeklyInvalid("回执 metadata 与结果列不一致")
    return values


def find_receipt(
    session: Session,
    *,
    profile_id: str,
    request_id: str,
    action: str | None = None,
    fingerprint: str | None = None,
) -> LocalWeeklyPlanOperation | None:
    row = session.scalars(
        select(LocalWeeklyPlanOperation).where(
            LocalWeeklyPlanOperation.profile_id == profile_id,
            LocalWeeklyPlanOperation.request_id == request_id,
        )
    ).first()
    if row is None:
        return None
    if action is not None and row.action != action:
        raise LocalWeeklyOperationConflict()
    if fingerprint is not None and row.input_fingerprint != fingerprint:
        raise LocalWeeklyOperationConflict()
    return row


def store_receipt(
    session: Session,
    *,
    profile_id: str,
    request_id: str,
    action: str,
    fingerprint: str,
    result: dict,
    **result_fields: Any,
) -> LocalWeeklyPlanOperation:
    validate_metadata(
        result,
        weekly_plan_id=result_fields.get("weekly_plan_id"),
        draft_id=result_fields.get("result_draft_id"),
        draft_version=result_fields.get("result_draft_version"),
        confirmation_id=result_fields.get("result_confirmed_id"),
        confirmation_version=result_fields.get("result_confirmed_version"),
        snapshot_id=result_fields.get("result_snapshot_id"),
        token_id=result_fields.get("result_token_id"),
    )
    row = LocalWeeklyPlanOperation(
        id=new_opaque_id(),
        profile_id=profile_id,
        request_id=request_id,
        action=action,
        input_fingerprint=fingerprint,
        result_json=result,
        **result_fields,
    )
    session.add(row)
    session.flush()
    return row


def invalidate_in_progress(session: Session, *, now=None) -> int:
    """Mark interrupted native attempts indeterminate; never delete history."""
    from app.local.base import utc_now

    stamp = now or utc_now()
    rows = session.scalars(
        select(LocalWeeklyExportAttempt).where(
            LocalWeeklyExportAttempt.status == "in_progress"
        )
    ).all()
    for row in rows:
        row.status = "indeterminate"
        row.byte_size = 0
        row.result_hash = None
        row.ended_at = stamp
        token = session.get(LocalWeeklyExportToken, row.token_id)
        if token is not None and token.consumed_at is None:
            token.consumed_at = stamp
    session.flush()
    return len(rows)


def replay(row: LocalWeeklyPlanOperation) -> dict:
    return dict(row.result_json)
