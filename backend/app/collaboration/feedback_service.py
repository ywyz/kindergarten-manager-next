"""In-app feedback submission, listing and processing-state transactions.

The feedback entry is deliberately independent from teacher collaboration
sessions: a desktop submission carries only the client-generated request id,
the teacher-typed content, optional contact information, the application
version string and — since 2026-11-24 — an optional bounded window of
fixed-shape diagnostic events.  No feedback code, collaboration account,
secret or login is required: the optional ``feedback_code`` exists only for
already-released clients that still send one, and it is never verified
against anything — whether or not the service process still holds a legacy
``KGM_COLLAB_FEEDBACK_CODE`` value, a well-formed supplied code is stored
as a keyed digest (never the plaintext) and a code-free submission stores
null.  The request id is the idempotency key, so a retry after a lost
response returns the original receipt and never creates a second admin-list
entry; the content fingerprint covers every submitted field including the
attached diagnostics (the no-diagnostics form keeps the historical v1
canonical shape so old in-flight retries, and old rows committed by the
0007-era service, still resolve).

Rate limiting is in-process and bounded: per client IP within a sliding
window, with a hard cap on tracked IPs so memory stays bounded even under
abuse.  A multi-process deployment gets one limiter per process, which only
loosens (never removes) the bound.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .admin_models import AdminUser
from .config import CollaborationSettings
from .errors import CollaborationError
from .feedback_models import (
    FEEDBACK_STATUSES,
    FEEDBACK_STATUS_DEFAULT,
    FeedbackSubmission,
)
from app.diagnostics_contract import (
    ERROR_CODES as DIAGNOSTICS_ERROR_CODES,
    EVENT_TYPES as DIAGNOSTICS_EVENT_TYPES,
    FUTURE_TOLERANCE_SECONDS,
    MAX_DIAGNOSTICS_EVENTS,
    MAX_DIAGNOSTICS_JSON_CHARS,
    MIN_EVENT_YEAR,
    RESULTS as DIAGNOSTICS_RESULTS,
    TIME_PATTERN as _DIAGNOSTICS_TIME_PATTERN,
)

MAX_CONTENT_CHARS = 4000
MAX_CONTACT_CHARS = 200
MAX_CODE_CHARS = 512
MAX_APP_VERSION_CHARS = 100
# Hard cap for one JSON submission body (the valid payload stays far below).
MAX_BODY_BYTES = 65_536

# A recorded stamp may run ahead of the receiving clock by this fixed
# tolerance: the teacher's machine is never required to be accurate to the
# second (or even the hour).
_DIAGNOSTICS_FUTURE_TOLERANCE = timedelta(seconds=FUTURE_TOLERANCE_SECONDS)

RATE_WINDOW_SECONDS = 600
RATE_MAX_PER_WINDOW = 5
RATE_MAX_TRACKED_IPS = 10_000

_LIST_LIMIT_DEFAULT = 50
_LIST_LIMIT_MAX = 200


def feedback_code_invalid() -> CollaborationError:
    # Deliberately uniform: over-long or control-character codes look the
    # same.  Raised only as a format bound on the legacy field; the code is
    # never verified against any distributed value.
    return CollaborationError(
        400,
        "FEEDBACK_CODE_INVALID",
        "反馈码无效或未分发给本版本，请核对后重试",
    )


def feedback_request_conflict() -> CollaborationError:
    return CollaborationError(
        409,
        "REQUEST_CONFLICT",
        "同一反馈请求 ID 已用于不同内容，原反馈不会被替换",
    )


def feedback_validation(message: str) -> CollaborationError:
    return CollaborationError(422, "FEEDBACK_INVALID", message)


def feedback_not_found() -> CollaborationError:
    return CollaborationError(404, "FEEDBACK_SUBMISSION_NOT_FOUND", "没有找到该反馈")


def feedback_status_conflict(current_status: str) -> CollaborationError:
    return CollaborationError(
        409,
        "FEEDBACK_STATUS_CONFLICT",
        "反馈处理状态已被其他窗口修改，请刷新后重试",
        details={"current_status": current_status},
    )


def feedback_rate_limited(retry_after: int) -> CollaborationError:
    return CollaborationError(
        429,
        "FEEDBACK_RATE_LIMITED",
        "提交过于频繁，请稍后再试",
        details={"retry_after_seconds": max(1, int(retry_after))},
        headers={"Retry-After": str(max(1, int(retry_after)))},
    )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _reject_control_chars(value: str) -> bool:
    return not any(ord(char) < 32 and char != "\n" for char in value)


def validate_feedback_code(code: object) -> str | None:
    """Bound an old-client supplied code; ``None`` means "no code sent".

    Only the format is checked: the field carries no authentication meaning
    anymore (whether or not the service process still holds a legacy
    ``KGM_COLLAB_FEEDBACK_CODE`` value), so a well-formed code from a
    released client is accepted as-is and only its keyed digest is stored.
    """
    if code is None:
        return None
    if not isinstance(code, str):
        raise feedback_validation("反馈码必须是字符串")
    if code == "":
        # An empty string is the no-code form, not an invalid code.
        return None
    value = code.strip()
    if not value or len(value) > MAX_CODE_CHARS:
        raise feedback_code_invalid()
    if not _reject_control_chars(value) or value != code:
        raise feedback_code_invalid()
    return value


def validate_submission_diagnostics(value: object) -> list[dict] | None:
    """Strict validation of the optional attached diagnostics window.

    Every event must carry exactly the four fixed fields with fixed enum
    values; the UTC time is a real second-resolution stamp; a failed/unknown
    result requires a fixed error code and the other results require none.
    The window is capped by item count and by the serialized size that will
    be stored.  ``None`` or an empty list means "nothing attached".
    """
    if value is None:
        return None
    if not isinstance(value, (list, tuple)):
        raise feedback_validation("诊断事件必须是列表")
    if not value:
        return None
    if len(value) > MAX_DIAGNOSTICS_EVENTS:
        raise feedback_validation(
            f"诊断事件最多 {MAX_DIAGNOSTICS_EVENTS} 条"
        )
    events: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            raise feedback_validation("诊断事件必须是对象")
        if set(item) != {"event_type", "time", "result", "error_code"}:
            raise feedback_validation("诊断事件字段不合法")
        event_type = item.get("event_type")
        if event_type not in DIAGNOSTICS_EVENT_TYPES:
            raise feedback_validation("诊断事件类型不合法")
        result = item.get("result")
        if result not in DIAGNOSTICS_RESULTS:
            raise feedback_validation("诊断事件结果不合法")
        time_value = item.get("time")
        if not isinstance(time_value, str):
            raise feedback_validation("诊断事件时间必须是字符串")
        if _DIAGNOSTICS_TIME_PATTERN.match(time_value) is None:
            raise feedback_validation("诊断事件时间必须是 UTC 秒级时间戳")
        try:
            parsed = datetime.strptime(time_value, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            raise feedback_validation("诊断事件时间不合法") from None
        # The stamp is UTC by format; a naive comparison against a naive UTC
        # now keeps the bound independent of the host clock's tz database.
        # The fixed forward tolerance means the teacher's machine clock is
        # never required to be accurate to the second (or even the hour).
        now = _utcnow().replace(tzinfo=None)
        if parsed.year < MIN_EVENT_YEAR or parsed > now + _DIAGNOSTICS_FUTURE_TOLERANCE:
            raise feedback_validation("诊断事件时间不在可接受范围内")
        error_code = item.get("error_code")
        if result in ("failed", "unknown"):
            if not isinstance(error_code, str):
                raise feedback_validation("失败的诊断事件必须携带固定错误码")
            if error_code not in DIAGNOSTICS_ERROR_CODES:
                # A finite vocabulary shared with the collector: a crafted
                # unknown code (never emitted by the desktop) is refused
                # here and can never reach the admin list.
                raise feedback_validation("诊断事件错误码不合法")
        elif error_code is not None:
            raise feedback_validation("非失败的诊断事件不携带错误码")
        events.append(
            {
                "event_type": event_type,
                "time": time_value,
                "result": result,
                "error_code": error_code,
            }
        )
    canonical = diagnostics_json(events)
    if len(canonical) > MAX_DIAGNOSTICS_JSON_CHARS:
        raise feedback_validation("诊断事件序列化后超过大小限制")
    return events


def diagnostics_json(events: list[dict] | None) -> str | None:
    """The canonical stored form: fixed key order, compact, no free text."""
    if not events:
        return None
    return json.dumps(
        events,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def validate_submission_content(
    content: object,
    contact: object,
    app_version: object,
) -> tuple[str, str | None, str | None]:
    if not isinstance(content, str):
        raise feedback_validation("反馈内容必须是字符串")
    if not content.strip():
        raise feedback_validation("反馈内容不能为空")
    if len(content) > MAX_CONTENT_CHARS or "\x00" in content:
        raise feedback_validation(f"反馈内容长度必须为 1–{MAX_CONTENT_CHARS} 个字符")
    if contact is None:
        clean_contact = None
    else:
        if not isinstance(contact, str):
            raise feedback_validation("联系信息必须是字符串")
        clean_contact = contact.strip()
        if clean_contact:
            if (
                len(clean_contact) > MAX_CONTACT_CHARS
                or "\x00" in clean_contact
                or not _reject_control_chars(clean_contact)
            ):
                raise feedback_validation(
                    f"联系信息长度必须为 1–{MAX_CONTACT_CHARS} 个字符且不含控制字符"
                )
        else:
            clean_contact = None
    if app_version is None or app_version == "":
        clean_version = None
    else:
        if not isinstance(app_version, str):
            raise feedback_validation("应用版本必须是字符串")
        clean_version = app_version.strip()
        if clean_version:
            if (
                len(clean_version) > MAX_APP_VERSION_CHARS
                or "\x00" in clean_version
                or not _reject_control_chars(clean_version)
            ):
                raise feedback_validation("应用版本不合法")
        else:
            clean_version = None
    return content, clean_contact, clean_version


def digest_feedback_code(settings: CollaborationSettings, code: str) -> str:
    return hmac.new(
        settings.token_pepper.encode("utf-8"),
        f"feedback-code:{code}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def content_fingerprint(
    settings: CollaborationSettings,
    request_id: UUID,
    content: str,
    contact: str | None,
    app_version: str | None,
    diagnostics: list[dict] | None = None,
) -> str:
    """Keyed digest of the submitted fields for same-request replay checks.

    A payload without attached diagnostics keeps the historical v1 canonical
    shape byte-for-byte, so a retry from an already-released client still
    resolves against a row committed before the 2026-11-24 change.  A
    payload with diagnostics uses the v2 shape, which also covers the exact
    attached events.
    """
    if diagnostics:
        payload = [
            "feedback-submission-v2",
            str(request_id),
            content,
            contact,
            app_version,
            diagnostics,
        ]
    else:
        payload = [
            "feedback-submission-v1",
            str(request_id),
            content,
            contact,
            app_version,
        ]
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hmac.new(
        settings.token_pepper.encode("utf-8"),
        canonical,
        hashlib.sha256,
    ).hexdigest()


class FeedbackRateLimiter:
    """Thread-safe, bounded per-IP sliding-window counter (process memory)."""

    def __init__(
        self,
        *,
        window_seconds: int = RATE_WINDOW_SECONDS,
        max_per_window: int = RATE_MAX_PER_WINDOW,
        max_tracked_ips: int = RATE_MAX_TRACKED_IPS,
        clock: Any = time.monotonic,
    ) -> None:
        self._window = float(window_seconds)
        self._max = int(max_per_window)
        self._max_ips = int(max_tracked_ips)
        self._clock = clock
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = {}

    def check(self, client_ip: str) -> None:
        """Raise 429 when this IP exceeded the window; record the hit."""
        now = float(self._clock())
        with self._lock:
            hits = self._hits.get(client_ip)
            if hits is None:
                if len(self._hits) >= self._max_ips:
                    # Drop the oldest tracked IPs to keep memory bounded.
                    for key in list(self._hits)[: len(self._hits) - self._max_ips + 1]:
                        self._hits.pop(key, None)
                hits = deque()
                self._hits[client_ip] = hits
            while hits and now - hits[0] >= self._window:
                hits.popleft()
            if len(hits) >= self._max:
                retry_after = int(self._window - (now - hits[0])) + 1
                raise feedback_rate_limited(max(1, retry_after))
            hits.append(now)


rate_limiter = FeedbackRateLimiter()


@dataclass(frozen=True)
class FeedbackReceipt:
    submission_id: UUID
    request_id: UUID
    received_at: datetime
    replayed: bool


def _receipt(row: FeedbackSubmission, *, replayed: bool) -> FeedbackReceipt:
    received_at = _as_utc(row.created_at) or _utcnow()
    return FeedbackReceipt(
        submission_id=row.id,
        request_id=row.request_id,
        received_at=received_at,
        replayed=replayed,
    )


def _resolve_committed_row(
    session: Session, request_id: UUID, fingerprint: str
) -> FeedbackSubmission:
    row = session.scalars(
        select(FeedbackSubmission).where(
            FeedbackSubmission.request_id == request_id
        )
    ).one_or_none()
    if row is None:
        raise feedback_request_conflict()
    if row.content_fingerprint != fingerprint:
        raise feedback_request_conflict()
    return row


def submit_feedback(
    session: Session,
    settings: CollaborationSettings,
    *,
    request_id: UUID,
    code: object,
    content: object,
    contact: object,
    app_version: object,
    client_ip: str,
    diagnostics: object = None,
) -> FeedbackReceipt:
    """Validate the bounds, then commit one idempotent submission.

    No feedback code, collaboration account or login is required — whether
    or not the service process still holds a legacy
    ``KGM_COLLAB_FEEDBACK_CODE`` value, the field is never verified against
    anything: a submission without ``code`` stores a null code digest, and
    a well-formed code sent by an already-released client is stored as a
    keyed digest only.  The old in-flight-request receipt compatibility is
    preserved by the unchanged v1 content fingerprint.  The optional
    diagnostics window is validated against the shared finite vocabulary
    and stored as canonical JSON.
    """
    # The rate limit runs before every other check so abuse stays slow.
    rate_limiter.check(client_ip or "unknown")
    clean_code = validate_feedback_code(code)
    supplied_hash = (
        digest_feedback_code(settings, clean_code) if clean_code else None
    )
    clean_content, clean_contact, clean_version = validate_submission_content(
        content, contact, app_version
    )
    clean_diagnostics = validate_submission_diagnostics(diagnostics)
    fingerprint = content_fingerprint(
        settings,
        request_id,
        clean_content,
        clean_contact,
        clean_version,
        clean_diagnostics,
    )

    def transaction() -> FeedbackReceipt:
        with session.begin():
            existing = session.scalars(
                select(FeedbackSubmission)
                .where(FeedbackSubmission.request_id == request_id)
                .with_for_update()
            ).one_or_none()
            if existing is not None:
                if existing.content_fingerprint != fingerprint:
                    raise feedback_request_conflict()
                return _receipt(existing, replayed=True)
            row = FeedbackSubmission(
                id=uuid4(),
                request_id=request_id,
                content_fingerprint=fingerprint,
                content=clean_content,
                contact=clean_contact,
                app_version=clean_version,
                feedback_code_hash=supplied_hash,
                diagnostics_events=diagnostics_json(clean_diagnostics),
                status=FEEDBACK_STATUS_DEFAULT,
            )
            session.add(row)
            session.flush()
            return _receipt(row, replayed=False)

    try:
        return transaction()
    except IntegrityError:
        # A concurrent same-request submission committed between this
        # request's read and its insert; resolve against the committed row.
        session.rollback()
        return _resolve_committed_row(session, request_id, fingerprint)


@dataclass(frozen=True)
class FeedbackListItem:
    submission_id: UUID
    request_id: UUID
    status: str
    content: str
    contact: str | None
    app_version: str | None
    diagnostics_events: list[dict] | None
    handled_by_admin_username: str | None
    handled_at: datetime | None
    created_at: datetime


def parse_diagnostics_events(raw: object) -> list[dict] | None:
    """Read the stored canonical diagnostics JSON back for the admin list.

    Old rows (and every row without an attachment) stay ``None``; a corrupt
    value is reported as unavailable rather than guessed, so an old feedback
    without logs is still fully viewable.
    """
    if raw is None:
        return None
    if not isinstance(raw, str):
        return None
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(value, list):
        return None
    events: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            return None
        events.append(
            {
                "event_type": item.get("event_type"),
                "time": item.get("time"),
                "result": item.get("result"),
                "error_code": item.get("error_code"),
            }
        )
    return events or None


@dataclass(frozen=True)
class FeedbackListPage:
    items: list[FeedbackListItem]
    total: int
    offset: int
    limit: int


def list_feedback(
    session: Session,
    *,
    status: str | None = None,
    offset: int = 0,
    limit: int = _LIST_LIMIT_DEFAULT,
) -> FeedbackListPage:
    """One bounded page of the admin list plus the filtered total.

    ``limit`` is capped and ``offset`` is non-negative, so a page request can
    never read the whole table at once; the total lets the admin page render
    bounded pagination without a separate unbounded query.
    """
    if status is not None and status not in FEEDBACK_STATUSES:
        raise feedback_validation("处理状态不合法")
    offset = max(0, int(offset))
    limit = min(max(1, int(limit)), _LIST_LIMIT_MAX)
    count_query = select(func.count()).select_from(FeedbackSubmission)
    if status is not None:
        count_query = count_query.where(FeedbackSubmission.status == status)
    total = int(session.scalar(count_query) or 0)
    query = (
        select(FeedbackSubmission, AdminUser.username)
        .join(AdminUser, FeedbackSubmission.handled_by_admin_id == AdminUser.id, isouter=True)
        .order_by(FeedbackSubmission.created_at.desc(), FeedbackSubmission.id.desc())
        .offset(offset)
        .limit(limit)
    )
    if status is not None:
        query = query.where(FeedbackSubmission.status == status)
    rows = session.execute(query).all()
    return FeedbackListPage(
        items=[
            FeedbackListItem(
                submission_id=row.id,
                request_id=row.request_id,
                status=row.status,
                content=row.content,
                contact=row.contact,
                app_version=row.app_version,
                diagnostics_events=parse_diagnostics_events(
                    row.diagnostics_events
                ),
                handled_by_admin_username=username,
                handled_at=_as_utc(row.handled_at),
                created_at=_as_utc(row.created_at) or _utcnow(),
            )
            for row, username in rows
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


def update_feedback_status(
    session: Session,
    *,
    admin_id: UUID,
    submission_id: UUID,
    expected_status: object,
    new_status: object,
) -> FeedbackListItem:
    """Move one submission's processing state with a conflict-safe baseline.

    ``expected_status`` is the baseline the admin saw.  A retry after a lost
    response is idempotent when the current status already equals
    ``new_status``; a different concurrent status returns a 409 with the
    current value.  Unknown statuses are rejected and never guessed.
    """
    if not isinstance(expected_status, str) or expected_status not in FEEDBACK_STATUSES:
        raise feedback_validation("预期处理状态不合法")
    if not isinstance(new_status, str) or new_status not in FEEDBACK_STATUSES:
        raise feedback_validation("新处理状态只能是 new、processing 或 resolved")
    with session.begin():
        row = session.scalars(
            select(FeedbackSubmission)
            .where(FeedbackSubmission.id == submission_id)
            .with_for_update()
        ).one_or_none()
        if row is None:
            raise feedback_not_found()
        if row.status != new_status:
            if row.status != expected_status:
                raise feedback_status_conflict(row.status)
            row.status = new_status
            row.handled_by_admin_id = admin_id
            row.handled_at = _utcnow()
            session.flush()
        username = session.scalars(
            select(AdminUser.username).where(AdminUser.id == row.handled_by_admin_id)
        ).one_or_none()
        return FeedbackListItem(
            submission_id=row.id,
            request_id=row.request_id,
            status=row.status,
            content=row.content,
            contact=row.contact,
            app_version=row.app_version,
            diagnostics_events=parse_diagnostics_events(
                row.diagnostics_events
            ),
            handled_by_admin_username=username,
            handled_at=_as_utc(row.handled_at),
            created_at=_as_utc(row.created_at) or _utcnow(),
        )
